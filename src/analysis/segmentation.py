"""Transcript -> sentence units -> topic chunks.

Design note, from measurement rather than intuition
---------------------------------------------------
The original node split only on 20 hardcoded phrases ("welcome", "rule number
one", "precisely", ...). Those phrases happened to appear in every segment of
the bundled demo transcript, so it produced 7 tidy chunks there -- and exactly
one 1800-second chunk on real YouTube captions, which node_07 then discarded,
yielding zero clips.

The obvious fix is "use embeddings to find topic shifts". We measured that. With
the offline `lexical` backend, adjacent-window cosine dips do **not** recover
planted topic boundaries at any window size from 2 to 10 units -- the
boundary/non-boundary ratio stays around 1.0, because incidental word variation
between neighbouring sentences swamps the topic signal. Shipping dip detection
on that backend would be the same failure as the keyword list: an impressive
component that does nothing.

So the backbone here is signals that are actually reliable in speech:

  1. sentence structure  -- punctuation, where present
  2. pause length        -- the strongest real cue for a safe cut in speech
  3. speaker turns       -- where the transcript carries them
  4. hard duration bounds -- the guarantee that no chunk can be unusable

Semantic dip detection is layered on top only when a genuinely semantic backend
(`openai`/`gemini`) is configured, and is reported as such in `boundary_reason`.
Discourse markers survive as a small additive nudge, generalised well beyond the
original demo-specific list -- never as the primary mechanism.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.schema.clips import SemanticChunk, SentenceUnit, TranscriptSegment
from src.utils.logging_config import get_logger

log = get_logger(__name__)

SENTENCE_END_RE = re.compile(r"""[.!?]['")\]]*\s*$""")

# A pause this long implies the speaker finished a thought.
UNIT_BREAK_PAUSE_SEC = 0.55
# Safety cap so unpunctuated auto-captions cannot accumulate without bound.
UNIT_MAX_DURATION_SEC = 20.0

# Generic discourse markers that signal a shift in most spoken English, rather
# than the previous list of phrases lifted from one demo transcript.
DISCOURSE_MARKERS = (
    "anyway", "so anyway", "moving on", "next thing", "the next",
    "another thing", "another point", "on the other hand", "that said",
    "but here's", "here's the thing", "the point is", "bottom line",
    "let me", "let's talk", "talking about", "speaking of", "which brings",
    "to be fair", "the second", "the third", "first of all", "finally",
    "in conclusion", "to wrap", "one more thing", "before we",
    "i want to talk", "shifting gears", "changing topic", "new topic",
)


@dataclass(frozen=True)
class Seam:
    """A candidate cut point *after* `unit_index`."""

    unit_index: int
    score: float
    reason: str


def _speaker_of(segments: list[TranscriptSegment]) -> str:
    return segments[0].speaker if segments else "Speaker_1"


def build_sentence_units(segments: list[TranscriptSegment]) -> list[SentenceUnit]:
    """Merge raw transcript fragments into sentence-length units.

    Flushes on a sentence terminator, a pause longer than
    `UNIT_BREAK_PAUSE_SEC`, a speaker change, or the duration safety cap.
    """
    if not segments:
        return []

    ordered = sorted(segments, key=lambda s: (s.start, s.id))
    units: list[SentenceUnit] = []
    buffer: list[TranscriptSegment] = []
    prev_unit_end: float | None = None

    def flush() -> None:
        nonlocal buffer, prev_unit_end
        if not buffer:
            return
        text = " ".join(s.text.strip() for s in buffer if s.text.strip()).strip()
        if not text:
            buffer = []
            return
        start, end = buffer[0].start, buffer[-1].end
        gap = 0.0 if prev_unit_end is None else max(0.0, start - prev_unit_end)
        units.append(
            SentenceUnit(
                id=len(units) + 1,
                start=start,
                end=end,
                text=text,
                speaker=_speaker_of(buffer),
                segment_ids=[s.id for s in buffer],
                gap_before=round(gap, 3),
                ends_sentence=bool(SENTENCE_END_RE.search(text)),
            )
        )
        prev_unit_end = end
        buffer = []

    for seg in ordered:
        if not seg.text.strip():
            continue
        if buffer:
            gap = seg.start - buffer[-1].end
            span = seg.end - buffer[0].start
            speaker_changed = seg.speaker != buffer[-1].speaker
            buffered_text = " ".join(s.text for s in buffer)
            if (
                SENTENCE_END_RE.search(buffered_text)
                or gap >= UNIT_BREAK_PAUSE_SEC
                or speaker_changed
                or span > UNIT_MAX_DURATION_SEC
            ):
                flush()
        buffer.append(seg)
    flush()

    log.info("Built %d sentence units from %d transcript segments", len(units), len(segments))
    return units


def score_seams(
    units: list[SentenceUnit],
    semantic_dips: dict[int, float] | None = None,
) -> list[Seam]:
    """Score every position between consecutive units as a cut point.

    `semantic_dips` maps unit_index -> similarity-to-next in [0, 1], and is
    only supplied when a genuinely semantic embedding backend is active. Lower
    similarity raises the score.
    """
    seams: list[Seam] = []
    for i in range(len(units) - 1):
        nxt = units[i + 1]
        reasons: list[str] = []
        score = 0.0

        # Pause: the most trustworthy signal. Saturates at 2s.
        pause = min(nxt.gap_before, 2.0)
        if pause > 0.15:
            score += pause * 3.0
            reasons.append(f"pause {nxt.gap_before:.2f}s")

        if units[i].ends_sentence:
            score += 2.0
            reasons.append("sentence end")

        if nxt.speaker != units[i].speaker:
            score += 1.5
            reasons.append("speaker change")

        lowered = nxt.text.lower()
        if any(lowered.startswith(m) or f" {m}" in lowered[:60] for m in DISCOURSE_MARKERS):
            score += 1.0
            reasons.append("discourse marker")

        if semantic_dips and i in semantic_dips:
            similarity = semantic_dips[i]
            # Map similarity in [0,1] to a bonus in [0,3]; a dip to 0 is a
            # strong signal, a similarity of 1 contributes nothing.
            score += max(0.0, (1.0 - similarity)) * 3.0
            reasons.append(f"semantic dip (sim {similarity:.2f})")

        seams.append(
            Seam(
                unit_index=i,
                score=round(score, 3),
                reason=", ".join(reasons) if reasons else "no strong cue",
            )
        )
    return seams


def _duration_preference(duration: float, optimal: float) -> float:
    """Bonus peaking at the optimal clip length, decaying either side."""
    if optimal <= 0:
        return 0.0
    ratio = duration / optimal
    # Triangular preference: 1.0 at optimal, 0 at 0x or 2x.
    return max(0.0, 1.0 - abs(1.0 - ratio)) * 2.0


def _split_overlong_unit(unit: SentenceUnit, max_duration: float) -> list[SentenceUnit]:
    """Hard-split a single unit that alone exceeds `max_duration`.

    Only reachable for pathological input (an unpunctuated caption run with no
    pauses). Splits proportionally by word count so timings stay plausible.
    """
    pieces = max(2, int(unit.duration // max_duration) + 1)
    words = unit.text.split()
    if not words:
        return [unit]
    per_piece = max(1, len(words) // pieces)
    out: list[SentenceUnit] = []
    for p in range(pieces):
        w_start = p * per_piece
        w_end = len(words) if p == pieces - 1 else min(len(words), (p + 1) * per_piece)
        if w_start >= len(words):
            break
        frac_start = w_start / len(words)
        frac_end = w_end / len(words)
        out.append(
            SentenceUnit(
                id=unit.id,
                start=round(unit.start + unit.duration * frac_start, 3),
                end=round(unit.start + unit.duration * frac_end, 3),
                text=" ".join(words[w_start:w_end]),
                speaker=unit.speaker,
                segment_ids=unit.segment_ids,
                gap_before=unit.gap_before if p == 0 else 0.0,
                ends_sentence=unit.ends_sentence if p == pieces - 1 else False,
            )
        )
    log.debug("Force-split a %.1fs unit into %d pieces", unit.duration, len(out))
    return out


def segment_units(
    units: list[SentenceUnit],
    *,
    min_duration: float,
    max_duration: float,
    optimal_duration: float,
    semantic_dips: dict[int, float] | None = None,
) -> list[SemanticChunk]:
    """Group units into topic chunks.

    Guarantees, which is the point of this rewrite:
      * every returned chunk has `duration <= max_duration`
      * a whole episode can never collapse into one chunk
      * the seam chosen is the best-scoring one that lands in the acceptable
        duration band, preferring lengths near `optimal_duration`
    """
    if not units:
        return []

    # Pre-split any single unit that already violates the ceiling.
    expanded: list[SentenceUnit] = []
    for u in units:
        if u.duration > max_duration:
            expanded.extend(_split_overlong_unit(u, max_duration))
        else:
            expanded.append(u)
    units = expanded

    seams = score_seams(units, semantic_dips)
    seam_by_index = {s.unit_index: s for s in seams}

    chunks: list[SemanticChunk] = []
    i = 0
    while i < len(units):
        best_j: int | None = None
        best_total = float("-inf")
        best_seam: Seam | None = None
        j = i
        last_within_max = i

        while j < len(units):
            duration = units[j].end - units[i].start
            if duration > max_duration and j > i:
                break
            last_within_max = j
            if duration >= min_duration:
                seam = seam_by_index.get(j)
                total = (seam.score if seam else 0.0) + _duration_preference(
                    duration, optimal_duration
                )
                if total > best_total:
                    best_total, best_j, best_seam = total, j, seam
            j += 1

        if best_j is None:
            # Nothing in [min, max] was reachable: we are at a short tail, or
            # duration accumulates too slowly. Take everything that fits under
            # the ceiling so progress is always made.
            best_j = last_within_max
            best_seam = seam_by_index.get(best_j)

        group = units[i : best_j + 1]
        chunks.append(_make_chunk(len(chunks) + 1, group, best_seam, semantic_dips))
        i = best_j + 1

    chunks = _merge_short_tail(chunks, min_duration, max_duration)

    over = [c for c in chunks if c.duration > max_duration + 1e-6]
    if over:  # pragma: no cover - guarded by construction and tested
        raise AssertionError(
            f"segment_units produced {len(over)} chunk(s) over the "
            f"{max_duration}s ceiling: {[c.id for c in over]}"
        )
    log.info(
        "Segmented %d units into %d chunks (%.1fs-%.1fs, mean %.1fs)",
        len(units), len(chunks),
        min(c.duration for c in chunks), max(c.duration for c in chunks),
        sum(c.duration for c in chunks) / len(chunks),
    )
    return chunks


def _make_chunk(
    index: int,
    group: list[SentenceUnit],
    seam: Seam | None,
    semantic_dips: dict[int, float] | None,
) -> SemanticChunk:
    text = " ".join(u.text for u in group).strip()
    reason = seam.reason if seam else "end of transcript"
    similarity = None
    if semantic_dips and seam is not None:
        similarity = semantic_dips.get(seam.unit_index)
    return SemanticChunk(
        id=f"chunk_{index:03d}",
        start=group[0].start,
        end=group[-1].end,
        text=text,
        topic_summary=_summarise(text),
        key_concepts=extract_key_concepts(text),
        boundary_reason=reason,
        segment_ids=[sid for u in group for sid in u.segment_ids],
        boundary_similarity=similarity,
    )


def _merge_short_tail(
    chunks: list[SemanticChunk], min_duration: float, max_duration: float
) -> list[SemanticChunk]:
    """Fold a final sub-minimum chunk into its predecessor when that stays
    under the ceiling. Avoids emitting a 3-second orphan chunk."""
    if len(chunks) < 2:
        return chunks
    last, prev = chunks[-1], chunks[-2]
    if last.duration >= min_duration:
        return chunks
    if (last.end - prev.start) > max_duration:
        return chunks
    merged = SemanticChunk(
        id=prev.id,
        start=prev.start,
        end=last.end,
        text=f"{prev.text} {last.text}".strip(),
        topic_summary=prev.topic_summary,
        key_concepts=prev.key_concepts,
        boundary_reason=f"{prev.boundary_reason}; absorbed short tail",
        segment_ids=prev.segment_ids + last.segment_ids,
        boundary_similarity=last.boundary_similarity,
    )
    return chunks[:-2] + [merged]


def _summarise(text: str, max_chars: int = 110) -> str:
    """First sentence, truncated on a word boundary.

    Still extractive -- but the original took `text[:60] + "..."`, which
    routinely cut mid-word and was labelled `topic_summary`. An abstractive
    summary is the LLM's job (node_08), not this module's.
    """
    first = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    if len(first) <= max_chars:
        return first
    cut = first[:max_chars].rsplit(" ", 1)[0]
    return f"{cut}..."


def extract_key_concepts(text: str, limit: int = 6) -> list[str]:
    """Frequent content words, longest-and-most-frequent first.

    The original returned "words longer than 6 characters" in transcript order,
    which surfaced arbitrary long words rather than topical ones.
    """
    from src.providers.embeddings import STOPWORDS

    words = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text.lower())
    counts: dict[str, int] = {}
    for w in words:
        if w in STOPWORDS or len(w) < 4:
            continue
        counts[w] = counts.get(w, 0) + 1
    # Deterministic: sort by (-count, -length, alphabetical). `list(set(...))`
    # would reorder between runs.
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    return [w for w, _ in ranked[:limit]]
