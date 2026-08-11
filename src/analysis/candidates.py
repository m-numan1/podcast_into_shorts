"""Chunks + units -> candidate clips.

Fixes the original node_07, which:
  * discarded any chunk outside [min, max] duration and never sub-split it, so
    a long chunk yielded nothing at all;
  * only ever merged *adjacent pairs*, never longer runs or sub-windows;
  * ignored word timings, so cuts landed mid-sentence;
  * silently returned an empty list, letting the pipeline continue.
"""

from __future__ import annotations

from src.errors import CandidateGenerationError
from src.schema.clips import (
    CandidateClip,
    ExtractedFeatures,
    SemanticChunk,
    SentenceUnit,
)
from src.utils.logging_config import get_logger
from src.utils.metrics import overlap_ratio

log = get_logger(__name__)

# How many consecutive chunks may be merged into one candidate.
MAX_MERGE_RUN = 3


def chunk_unit_ranges(
    units: list[SentenceUnit], chunks: list[SemanticChunk]
) -> list[tuple[int, int]]:
    """Map each chunk to its inclusive (first, last) unit index.

    `segment_units` emits chunks that contiguously partition the unit list, so
    a time-based scan recovers the ranges exactly.
    """
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for chunk in chunks:
        first = cursor
        last = cursor
        while last + 1 < len(units) and units[last + 1].end <= chunk.end + 1e-6:
            last += 1
        ranges.append((first, last))
        cursor = last + 1
    return ranges


def _merge_features(
    candidate_id: str, feats: list[ExtractedFeatures]
) -> ExtractedFeatures:
    """Combine per-chunk features for a multi-chunk candidate.

    Maxima for "best moment" signals, sums for counts, means for rates.
    """
    if not feats:
        return ExtractedFeatures(chunk_id=candidate_id)
    if len(feats) == 1:
        return feats[0].model_copy(update={"chunk_id": candidate_id})

    n = len(feats)
    # dict.fromkeys preserves first-seen order; list(set(...)) would not,
    # making output non-deterministic between runs.
    entities = list(dict.fromkeys(e for f in feats for e in f.named_entities))
    density: dict[str, int] = {}
    for f in feats:
        for k, v in f.keyword_density.items():
            density[k] = density.get(k, 0) + v
    # Dominant emotion = the one from the highest-scoring chunk.
    strongest = max(feats, key=lambda f: f.emotion_score)
    return ExtractedFeatures(
        chunk_id=candidate_id,
        emotion_label=strongest.emotion_label,
        emotion_score=max(f.emotion_score for f in feats),
        sentiment_score=sum(f.sentiment_score for f in feats) / n,
        named_entities=entities[:8],
        speaking_rate_wpm=sum(f.speaking_rate_wpm for f in feats) / n,
        question_count=sum(f.question_count for f in feats),
        curiosity_score=max(f.curiosity_score for f in feats),
        strong_statement_score=max(f.strong_statement_score for f in feats),
        silence_duration_sec=sum(f.silence_duration_sec for f in feats),
        longest_pause_sec=max(f.longest_pause_sec for f in feats),
        keyword_density=density,
        topic_confidence=sum(f.topic_confidence for f in feats) / n,
        story_likelihood=max(f.story_likelihood for f in feats),
    )


def _build(
    candidate_id: str,
    units: list[SentenceUnit],
    first: int,
    last: int,
    chunk_ids: list[str],
    features_map: dict[str, ExtractedFeatures],
) -> CandidateClip:
    group = units[first : last + 1]
    start, end = group[0].start, group[-1].end
    text = " ".join(u.text for u in group).strip()

    # Real boundary quality, from the transcript structure rather than a
    # hardcoded sentence about "capturing initial breath".
    starts_clean = first == 0 or units[first - 1].ends_sentence
    ends_clean = group[-1].ends_sentence
    lead_in = group[0].gap_before
    lead_out = units[last + 1].gap_before if last + 1 < len(units) else 0.0

    feats = [features_map[c] for c in chunk_ids if c in features_map]
    return CandidateClip(
        id=candidate_id,
        start_time=round(start, 3),
        end_time=round(end, 3),
        duration=round(end - start, 3),
        raw_text=text,
        semantic_chunk_ids=chunk_ids,
        feature_summary=_merge_features(candidate_id, feats),
        starts_on_sentence_boundary=starts_clean,
        ends_on_sentence_boundary=ends_clean,
        lead_in_silence_sec=round(lead_in, 3),
        lead_out_silence_sec=round(lead_out, 3),
    )


def generate_candidates(
    units: list[SentenceUnit],
    chunks: list[SemanticChunk],
    features_map: dict[str, ExtractedFeatures],
    *,
    min_duration: float,
    max_duration: float,
) -> list[CandidateClip]:
    """Build candidate clips from chunks and their underlying units.

    Raises:
        CandidateGenerationError: the source is too short to yield any clip.
    """
    if not units or not chunks:
        raise CandidateGenerationError(
            "No transcript content available to build candidates from."
        )

    total = units[-1].end - units[0].start
    if total < min_duration:
        raise CandidateGenerationError(
            f"Source is only {total:.1f}s of speech, shorter than the "
            f"{min_duration:.0f}s minimum clip length.",
            "Lower MIN_CLIP_DURATION_SEC or supply a longer episode.",
        )

    ranges = chunk_unit_ranges(units, chunks)
    seen: set[tuple[int, int]] = set()
    candidates: list[CandidateClip] = []

    def emit(first: int, last: int, chunk_ids: list[str]) -> None:
        if (first, last) in seen or first > last:
            return
        duration = units[last].end - units[first].start
        if not (min_duration <= duration <= max_duration):
            return
        seen.add((first, last))
        candidates.append(
            _build(
                f"cand_{len(candidates) + 1:03d}",
                units, first, last, chunk_ids, features_map,
            )
        )

    # 1. Each chunk on its own.
    for (first, last), chunk in zip(ranges, chunks):
        emit(first, last, [chunk.id])

    # 2. Runs of 2..MAX_MERGE_RUN consecutive chunks.
    for run in range(2, MAX_MERGE_RUN + 1):
        for i in range(len(ranges) - run + 1):
            first = ranges[i][0]
            last = ranges[i + run - 1][1]
            emit(first, last, [c.id for c in chunks[i : i + run]])

    # 3. Sub-windows inside any chunk that is long enough to contain a shorter
    #    self-contained clip. This is what the original never did.
    for (first, last), chunk in zip(ranges, chunks):
        if units[last].end - units[first].start <= min_duration * 1.4:
            continue
        for s in range(first, last + 1):
            for e in range(s, last + 1):
                duration = units[e].end - units[s].start
                if duration > max_duration:
                    break
                if duration < min_duration:
                    continue
                # Prefer sub-windows that begin and end cleanly.
                if s > first and not units[s - 1].ends_sentence:
                    continue
                if not units[e].ends_sentence and e != last:
                    continue
                emit(s, e, [chunk.id])

    if not candidates:
        # Last resort: walk units greedily so a valid transcript always yields
        # something, rather than returning [] and letting node_08 fail.
        log.warning(
            "No candidate satisfied the duration band via chunk structure; "
            "falling back to a greedy unit walk."
        )
        i = 0
        while i < len(units):
            j = i
            while j < len(units) and units[j].end - units[i].start < min_duration:
                j += 1
            if j >= len(units):
                break
            if units[j].end - units[i].start <= max_duration:
                emit(i, j, [])
            i = j + 1

    if not candidates:
        raise CandidateGenerationError(
            f"Could not form any clip between {min_duration:.0f}s and "
            f"{max_duration:.0f}s from {total:.1f}s of speech.",
            "Widen MIN_CLIP_DURATION_SEC / MAX_CLIP_DURATION_SEC.",
        )

    candidates.sort(key=lambda c: (c.start_time, c.end_time))
    for idx, cand in enumerate(candidates, start=1):
        cand.id = f"cand_{idx:03d}"

    clean = sum(
        1 for c in candidates if c.starts_on_sentence_boundary and c.ends_on_sentence_boundary
    )
    log.info(
        "Generated %d candidates (%d with clean sentence boundaries on both edges)",
        len(candidates), clean,
    )
    return candidates


def cheap_prescore(candidate: CandidateClip, optimal_duration: float) -> float:
    """Model-free quality estimate, used only to choose what to spend LLM
    calls on. Deliberately crude -- the real judgement happens in node_08."""
    score = 0.0

    # Duration near the optimum, decaying to 0 at 0x and 2x.
    if optimal_duration > 0:
        ratio = candidate.duration / optimal_duration
        score += max(0.0, 1.0 - abs(1.0 - ratio)) * 3.0

    # Clean edges matter more than anything else for a publishable clip.
    if candidate.starts_on_sentence_boundary:
        score += 2.0
    if candidate.ends_on_sentence_boundary:
        score += 2.0
    # Breathing room at the edges makes the cut sound natural.
    score += min(candidate.lead_in_silence_sec, 1.0)
    score += min(candidate.lead_out_silence_sec, 1.0)

    f = candidate.feature_summary
    score += f.curiosity_score * 1.5
    score += f.strong_statement_score * 1.5
    score += f.story_likelihood * 1.5
    score += min(f.question_count, 3) * 0.3

    # Penalise very sparse text (long silence, little speech).
    words = len(candidate.raw_text.split())
    if candidate.duration > 0:
        wpm = words / candidate.duration * 60.0
        if wpm < 80:
            score -= 2.0
    return score


def shortlist_candidates(
    candidates: list[CandidateClip],
    *,
    limit: int,
    optimal_duration: float,
    overlap_threshold: float,
) -> list[CandidateClip]:
    """Pick at most `limit` candidates, spread across the episode.

    Greedy non-maximum suppression on `cheap_prescore`: take the best remaining
    candidate, then reject anything overlapping it by more than
    `overlap_threshold`. Without this, a two-hour episode shortlists hundreds of
    near-identical windows and every one costs six LLM calls.
    """
    if len(candidates) <= limit:
        return list(candidates)

    ranked = sorted(
        candidates,
        # Tie-break on start time so the result is deterministic.
        key=lambda c: (-cheap_prescore(c, optimal_duration), c.start_time),
    )

    kept: list[CandidateClip] = []
    for cand in ranked:
        if len(kept) >= limit:
            break
        if any(
            overlap_ratio(cand.start_time, cand.end_time, k.start_time, k.end_time)
            > overlap_threshold
            for k in kept
        ):
            continue
        kept.append(cand)

    # If suppression was so aggressive we fell short, top up with the best
    # remaining candidates regardless of overlap.
    if len(kept) < limit:
        kept_ids = {c.id for c in kept}
        for cand in ranked:
            if len(kept) >= limit:
                break
            if cand.id not in kept_ids:
                kept.append(cand)

    kept.sort(key=lambda c: c.start_time)
    log.info(
        "Shortlisted %d of %d candidates for evaluation (%d LLM calls at 6 agents each)",
        len(kept), len(candidates), len(kept) * 6,
    )
    return kept
