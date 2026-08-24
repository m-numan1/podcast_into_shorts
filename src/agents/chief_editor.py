"""Chief editor: synthesise agent verdicts, deduplicate, rank, package.

Bug fixes from the audit, all covered by tests:

  B1  `summary_text` checked `words[-1]` -- the last word of the whole
      transcript rather than of the 28-word slice -- and raised IndexError on
      empty text.
  B2  Deduplication compared overlap against half the *candidate's own*
      duration, so a long clip fully containing an already-published short clip
      passed the check and the same content shipped twice.
  B13 The output cap was a hardcoded `rank > 15`, ignoring
      target_clip_count_min/max, and the minimum was never enforced or reported.
  B14 A 0-10 score was named `retention_wpm` and rendered as a completion
      percentage via `int(score * 10)`.
  B15 `virality_score` was taken from one agent, and `confidence_score` was the
      literal 9.2 for every clip.
  B12 `list(set(...))` made hashtag order differ between runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from config.settings import settings
from src.agents.editors import AGENTS
from src.errors import LLMError
from src.providers.llm import LLMProvider
from src.schema.clips import (
    CandidateClip,
    ClipEvaluation,
    ClipPackaging,
    DataProvenance,
    FinalClipOutput,
)
from src.utils.logging_config import get_logger
from src.utils.metrics import overlap_ratio, seconds_to_timestamp
from src.utils.text_cleaner import clean_transcript_text

log = get_logger(__name__)

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
HASHTAG_CLEAN_RE = re.compile(r"[^0-9A-Za-z]")

# Semantic similarity above which two clips are treated as the same point
# restated, even when they do not overlap in time.
NEAR_DUPLICATE_SIMILARITY = 0.88


@dataclass
class RankedCandidate:
    candidate: CandidateClip
    evaluations: dict[str, ClipEvaluation]
    composite: float


def composite_score(evaluations: dict[str, ClipEvaluation]) -> float:
    """Blend the agents' authoritative metrics using the configured weights."""
    if not evaluations:
        return 0.0

    def metric(agent_key: str, field: str, default: float = 0.0) -> float:
        ev = evaluations.get(agent_key)
        return getattr(ev, field) if ev else default

    return round(
        metric("hook", "hook_strength") * settings.weight_hook
        + metric("debate", "comment_potential") * settings.weight_comment_potential
        + metric("educational", "educational_value") * settings.weight_educational
        + metric("retention", "watch_time_prediction") * settings.weight_retention
        + metric("story", "story_completeness") * settings.weight_story,
        3,
    )


def aggregate_virality(evaluations: dict[str, ClipEvaluation]) -> float:
    """Mean virality across all agents (B15), not one agent's number."""
    if not evaluations:
        return 0.0
    return round(sum(e.virality_score for e in evaluations.values()) / len(evaluations), 2)


def aggregate_confidence(evaluations: dict[str, ClipEvaluation]) -> float:
    """Mean self-reported confidence, reduced when agents disagree.

    Disagreement is real information: six agents split on a clip is a less
    reliable signal than six agreeing, and the score should say so.
    """
    if not evaluations:
        return 0.0
    confidences = [e.confidence_score for e in evaluations.values()]
    overalls = [e.overall_score for e in evaluations.values()]
    mean_conf = sum(confidences) / len(confidences)
    if len(overalls) > 1:
        mean_overall = sum(overalls) / len(overalls)
        variance = sum((o - mean_overall) ** 2 for o in overalls) / len(overalls)
        spread_penalty = min(3.0, variance**0.5)
    else:
        spread_penalty = 0.0
    return round(max(0.0, min(10.0, mean_conf - spread_penalty)), 2)


def retention_label(watch_time_score: float) -> str:
    """Describe predicted retention without inventing a percentage.

    The original computed `int(score * 10)` and printed it as a completion
    percentage, which has no basis -- a 0-10 editorial score is not a measured
    completion rate.
    """
    if watch_time_score >= 8.5:
        return f"High (model watch-time score {watch_time_score:.1f}/10)"
    if watch_time_score >= 6.5:
        return f"Moderate (model watch-time score {watch_time_score:.1f}/10)"
    if watch_time_score >= 4.0:
        return f"Uncertain (model watch-time score {watch_time_score:.1f}/10)"
    return f"Low (model watch-time score {watch_time_score:.1f}/10)"


def first_sentence(text: str, max_words: int = 16) -> str:
    """The opening sentence, or the first `max_words` words if it runs long."""
    text = text.strip()
    if not text:
        return ""
    sentence = SENTENCE_SPLIT_RE.split(text, maxsplit=1)[0]
    words = sentence.split()
    if len(words) <= max_words:
        return sentence
    return " ".join(words[:max_words]) + "..."


def first_substantial_sentence(text: str, min_words: int = 5) -> str:
    """First sentence carrying real content, else the longest one.

    Openers are often a single word -- "Absolutely.", "Right." -- and titling on
    those forced a fallback to frequency-ranked keywords, which reads as word
    salad ("Single Build Developer"). Skipping to the first substantial sentence
    keeps titles readable without a model.
    """
    text = text.strip()
    if not text:
        return ""
    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if not sentences:
        return ""
    for sentence in sentences:
        if len(sentence.split()) >= min_words:
            return sentence
    return max(sentences, key=lambda s: len(s.split()))


def summarise(text: str, max_words: int = 28) -> str:
    """Extractive summary of the opening.

    B1: the terminator check now inspects the last word of the *slice*, and an
    empty input returns "" instead of raising IndexError.
    """
    words = text.split()
    if not words:
        return ""
    slice_words = words[:max_words]
    body = " ".join(slice_words)
    if slice_words[-1].endswith((".", "!", "?")):
        return body
    return body + ("." if len(words) <= max_words else "...")


def derive_hashtags(candidate: CandidateClip, limit: int = 5) -> list[str]:
    """Deterministic hashtags from the measured keyword density (B12).

    Ordered by frequency then alphabetically -- `list(set(...))` reordered
    between runs because string hashing is salted per process.
    """
    tags: list[str] = []
    for word in candidate.feature_summary.keyword_density:
        cleaned = HASHTAG_CLEAN_RE.sub("", word)
        if len(cleaned) >= 4:
            tags.append("#" + cleaned.capitalize())
    for entity in candidate.feature_summary.named_entities:
        cleaned = HASHTAG_CLEAN_RE.sub("", entity)
        if len(cleaned) >= 3:
            tags.append("#" + cleaned)
    # dict.fromkeys dedupes while preserving order.
    ordered = list(dict.fromkeys(tags))[:limit]
    return ordered or ["#Podcast", "#Shorts", "#Clips"]


def derive_title(candidate: CandidateClip, podcast_title: str, rank: int) -> str:
    """Readable title without a model.

    Prefers the clip's own opening clause over the original approach of
    capitalising the first four long words, which produced word salad like
    "That Terrifying Share Concrete".
    """
    sentence = first_substantial_sentence(candidate.raw_text)
    opening = " ".join(sentence.split()[:11]).rstrip(".!?,;:")
    if len(opening) < 12:
        keywords = list(candidate.feature_summary.keyword_density)[:3]
        opening = " ".join(w.capitalize() for w in keywords) or f"Highlight {rank}"
    if len(opening) > 68:
        opening = opening[:65].rsplit(" ", 1)[0] + "..."
    show = podcast_title.strip()
    if show and len(opening) + len(show) + 3 <= 70:
        return f"{opening} | {show}"
    return opening


def compute_adjustments(candidate: CandidateClip) -> tuple[float, float, str]:
    """Numeric cut adjustments from measured silence, plus a rationale.

    The original emitted the identical strings "-0.8s (captures initial
    breath/consonant before hook word)" and "+0.4s (holds trailing echo...)" for
    every clip, derived from nothing. These come from the real pause either side.
    """
    reasons: list[str] = []

    # Pull the start back into the preceding silence, so the first consonant is
    # not clipped -- but never more than half of it, and cap at 0.6s.
    lead_in = candidate.lead_in_silence_sec
    start_adj = -min(0.6, lead_in * 0.5) if lead_in > 0.1 else 0.0
    if start_adj:
        reasons.append(f"start {start_adj:+.2f}s into {lead_in:.2f}s of lead-in silence")
    elif not candidate.starts_on_sentence_boundary:
        reasons.append("no lead-in silence; opens mid-sentence")

    lead_out = candidate.lead_out_silence_sec
    end_adj = min(0.5, lead_out * 0.5) if lead_out > 0.1 else 0.0
    if end_adj:
        reasons.append(f"end {end_adj:+.2f}s into {lead_out:.2f}s of trailing silence")
    elif not candidate.ends_on_sentence_boundary:
        reasons.append("no trailing silence; ends mid-sentence")

    return (
        round(start_adj, 3),
        round(end_adj, 3),
        "; ".join(reasons) or "edges already sit on clean boundaries",
    )


def _packaging_prompt(candidate: CandidateClip, podcast_title: str) -> str:
    return (
        f"Podcast: {podcast_title}\n"
        f"Clip length: {candidate.duration:.1f}s\n"
        f"Recurring terms: {', '.join(candidate.feature_summary.keyword_density) or 'none'}\n\n"
        f"TRANSCRIPT:\n\"\"\"\n{candidate.raw_text}\n\"\"\"\n\n"
        "Write publishing metadata for this clip. The hook must be copied "
        "verbatim from the transcript's opening. Do not invent facts that are "
        "not in the transcript."
    )


PACKAGING_SYSTEM = (
    "You write publishing metadata for short-form video clips. Be specific and "
    "concrete; never use generic filler like 'you won't believe' or 'this "
    "changes everything'. Every claim must be supported by the transcript."
)


def package_clip(
    candidate: CandidateClip,
    podcast_title: str,
    rank: int,
    llm: LLMProvider | None,
) -> tuple[ClipPackaging, bool]:
    """Return packaging metadata and whether a model produced it."""
    if llm is not None and llm.available:
        try:
            packaging = llm.generate_structured(
                _packaging_prompt(candidate, podcast_title),
                ClipPackaging,
                system_prompt=PACKAGING_SYSTEM,
            )
            # Ensure model output is also cleaned of filler / sound tags
            return (
                ClipPackaging(
                    title=clean_transcript_text(packaging.title),
                    hook=clean_transcript_text(packaging.hook),
                    one_sentence_summary=clean_transcript_text(packaging.one_sentence_summary),
                    why_selected=packaging.why_selected,
                    suggested_caption=clean_transcript_text(packaging.suggested_caption),
                    suggested_thumbnail_text=packaging.suggested_thumbnail_text,
                    suggested_hashtags=packaging.suggested_hashtags,
                    target_audience=packaging.target_audience,
                ),
                True,
            )
        except LLMError as exc:
            log.warning("Packaging via model failed for %s (%s); deriving locally.",
                        candidate.id, exc)

    raw_text_clean = clean_transcript_text(candidate.raw_text)
    hook = first_sentence(raw_text_clean)
    tags = derive_hashtags(candidate)
    summary = summarise(raw_text_clean)
    title = derive_title(candidate, podcast_title, rank)
    return (
        ClipPackaging(
            title=clean_transcript_text(title),
            hook=clean_transcript_text(hook),
            one_sentence_summary=clean_transcript_text(summary),
            why_selected=(
                "Selected on measured signals only (no model configured): "
                "duration, boundary cleanliness and cue density."
            ),
            suggested_caption=f"{hook}\n\nFrom {podcast_title}.\n{summary}",
            suggested_thumbnail_text=" ".join(
                w.upper() for w in list(candidate.feature_summary.keyword_density)[:4]
            ) or "KEY MOMENT",
            suggested_hashtags=tags,
            target_audience="Podcast listeners interested in "
            + (", ".join(list(candidate.feature_summary.keyword_density)[:3]) or "this topic"),
        ),
        False,
    )



def deduplicate(
    ranked: list[RankedCandidate],
    *,
    overlap_threshold: float,
    near_duplicate_pairs: set[tuple[str, str]] | None = None,
) -> list[RankedCandidate]:
    """Drop candidates that repeat already-selected content.

    Two independent checks:
      * time overlap, using intersection-over-shorter so containment always
        registers (B2);
      * semantic near-duplication, catching the same point restated elsewhere in
        the episode, which time overlap cannot see.
    """
    near_duplicate_pairs = near_duplicate_pairs or set()
    kept: list[RankedCandidate] = []

    for item in ranked:
        cand = item.candidate
        duplicate_of: str | None = None

        for accepted in kept:
            acc = accepted.candidate
            ratio = overlap_ratio(cand.start_time, cand.end_time, acc.start_time, acc.end_time)
            if ratio > overlap_threshold:
                duplicate_of = f"{acc.id} (time overlap {ratio:.0%})"
                break
            shared = {
                (a, b)
                for a in cand.semantic_chunk_ids
                for b in acc.semantic_chunk_ids
            }
            if shared & near_duplicate_pairs or {(b, a) for a, b in shared} & near_duplicate_pairs:
                duplicate_of = f"{acc.id} (restates the same point)"
                break

        if duplicate_of:
            log.debug("Dropping %s as duplicate of %s", cand.id, duplicate_of)
            continue
        kept.append(item)

    return kept


def synthesise(
    candidates: list[CandidateClip],
    evaluations: dict[str, dict[str, ClipEvaluation]],
    *,
    podcast_title: str,
    llm: LLMProvider | None,
    provenance: DataProvenance,
    near_duplicate_pairs: set[tuple[str, str]] | None = None,
) -> tuple[list[FinalClipOutput], list[str]]:
    """Rank, deduplicate, cap and package. Returns (clips, warnings)."""
    warnings: list[str] = []

    ranked = [
        RankedCandidate(
            candidate=cand,
            evaluations=evaluations.get(cand.id, {}),
            composite=composite_score(evaluations.get(cand.id, {})),
        )
        for cand in candidates
    ]
    scored = [r for r in ranked if r.evaluations]
    if len(scored) < len(ranked):
        warnings.append(
            f"{len(ranked) - len(scored)} candidate(s) had no agent evaluation and were skipped."
        )

    # Deterministic ordering: composite desc, then start time asc.
    scored.sort(key=lambda r: (-r.composite, r.candidate.start_time))
    unique = deduplicate(
        scored,
        overlap_threshold=settings.dedup_overlap_threshold,
        near_duplicate_pairs=near_duplicate_pairs,
    )

    # B13: honour the configured range instead of a hardcoded 15.
    selected = unique[: settings.target_clip_count_max]
    if len(selected) < settings.target_clip_count_min:
        warnings.append(
            f"Produced {len(selected)} clip(s), fewer than the configured minimum of "
            f"{settings.target_clip_count_min}. The source may be short, repetitive, "
            f"or outside the {settings.min_clip_duration_sec:.0f}-"
            f"{settings.max_clip_duration_sec:.0f}s clip window."
        )

    clips: list[FinalClipOutput] = []
    model_packaged = 0
    for rank, item in enumerate(selected, start=1):
        cand = item.candidate
        packaging, from_model = package_clip(cand, podcast_title, rank, llm)
        model_packaged += int(from_model)

        start_adj, end_adj, rationale = compute_adjustments(cand)
        retention_ev = item.evaluations.get("retention")
        watch_score = retention_ev.watch_time_prediction if retention_ev else 0.0

        clips.append(
            FinalClipOutput(
                id=f"clip_{rank:02d}",
                rank=rank,
                title=packaging.title,
                start_timestamp=seconds_to_timestamp(cand.start_time),
                end_timestamp=seconds_to_timestamp(cand.end_time),
                start_seconds=cand.start_time,
                end_seconds=cand.end_time,
                duration_seconds=cand.duration,
                start_adjustment_sec=start_adj,
                end_adjustment_sec=end_adj,
                adjustment_rationale=rationale,
                adjusted_start_seconds=max(0.0, cand.start_time + start_adj),
                adjusted_end_seconds=cand.end_time + end_adj,
                hook=packaging.hook,
                one_sentence_summary=packaging.one_sentence_summary,
                why_this_clip_was_selected=packaging.why_selected,
                viewer_retention_prediction=retention_label(watch_score),
                virality_score=aggregate_virality(item.evaluations),
                confidence_score=aggregate_confidence(item.evaluations),
                overall_score=item.composite,
                target_platform=["YouTube Shorts", "TikTok", "Instagram Reels"],
                target_audience=packaging.target_audience,
                suggested_caption=packaging.suggested_caption,
                suggested_thumbnail_text=packaging.suggested_thumbnail_text,
                suggested_hashtags=packaging.suggested_hashtags,
                agent_evaluations=item.evaluations,
                provenance=provenance,
            )
        )

    log.info(
        "Chief editor: %d candidates -> %d after dedup -> %d published (%d packaged by model)",
        len(scored), len(unique), len(clips), model_packaged,
    )
    return clips, warnings


AGENT_KEYS = tuple(a.key for a in AGENTS)
