"""Segmentation, including the §4 regression that produced zero clips.

The original node split only on 20 hardcoded phrases. On the bundled demo
transcript every segment happened to contain one, giving 7 tidy chunks. On real
YouTube captions none matched, so a 30-minute episode collapsed into a single
1800-second chunk which node_07 then discarded, yielding zero candidates -- while
the CLI still printed "[SUCCESS]".
"""

from __future__ import annotations

import pytest

from src.analysis.segmentation import (
    build_sentence_units,
    extract_key_concepts,
    score_seams,
    segment_units,
)
from src.schema.clips import TranscriptSegment
from tests.conftest import make_caption_segments

MIN_D, MAX_D, OPT_D = 15.0, 90.0, 45.0


def segment(segments):
    units = build_sentence_units(segments)
    return units, segment_units(
        units, min_duration=MIN_D, max_duration=MAX_D, optimal_duration=OPT_D
    )


class TestSentenceUnits:
    def test_caption_fragments_merge_into_fewer_units(self, caption_segments):
        units = build_sentence_units(caption_segments)
        assert 0 < len(units) < len(caption_segments)

    def test_punctuated_segments_split_on_terminators(self, punctuated_segments):
        units = build_sentence_units(punctuated_segments)
        # Each input segment is one sentence, so units track them 1:1.
        assert len(units) == len(punctuated_segments)
        assert all(u.ends_sentence for u in units)

    def test_gap_before_is_measured(self):
        segs = [
            TranscriptSegment(id=1, start=0.0, end=3.0, text="First thing.", speaker="A"),
            TranscriptSegment(id=2, start=5.5, end=8.0, text="Second thing.", speaker="A"),
        ]
        units = build_sentence_units(segs)
        assert len(units) == 2
        assert units[0].gap_before == 0.0
        assert units[1].gap_before == pytest.approx(2.5)

    def test_speaker_change_forces_a_unit_break(self):
        segs = [
            TranscriptSegment(id=1, start=0.0, end=3.0, text="no punctuation here", speaker="A"),
            TranscriptSegment(id=2, start=3.0, end=6.0, text="different speaker now", speaker="B"),
        ]
        units = build_sentence_units(segs)
        assert len(units) == 2
        assert units[0].speaker == "A"
        assert units[1].speaker == "B"

    def test_empty_input(self):
        assert build_sentence_units([]) == []

    def test_blank_text_segments_are_dropped(self):
        segs = [
            TranscriptSegment(id=1, start=0.0, end=1.0, text="   ", speaker="A"),
            TranscriptSegment(id=2, start=1.0, end=4.0, text="real content here.", speaker="A"),
        ]
        units = build_sentence_units(segs)
        assert len(units) == 1
        assert "real content" in units[0].text

    def test_unpunctuated_run_is_capped_by_duration(self):
        """Auto-captions with no punctuation and no pauses must still break."""
        segs = make_caption_segments(40, fragment_duration=3.0, gap=0.0)
        units = build_sentence_units(segs)
        assert len(units) > 1
        # UNIT_MAX_DURATION_SEC is 20s; allow one fragment of slack.
        assert max(u.duration for u in units) <= 23.0

    def test_segments_are_sorted_by_start(self):
        segs = [
            TranscriptSegment(id=2, start=10.0, end=13.0, text="Second.", speaker="A"),
            TranscriptSegment(id=1, start=0.0, end=3.0, text="First.", speaker="A"),
        ]
        units = build_sentence_units(segs)
        assert units[0].text.startswith("First")


class TestSection4Regression:
    """The exact inputs that used to yield zero clips."""

    def test_thirty_minute_caption_transcript_yields_many_chunks(
        self, long_caption_segments
    ):
        units, chunks = segment(long_caption_segments)
        assert len(chunks) > 20, "one giant chunk was the original bug"
        assert all(c.duration <= MAX_D + 1e-6 for c in chunks)
        assert all(c.duration > 0 for c in chunks)

    def test_short_caption_transcript_yields_chunks(self, caption_segments):
        _, chunks = segment(caption_segments)
        assert len(chunks) >= 1
        assert all(c.duration <= MAX_D + 1e-6 for c in chunks)

    def test_coverage_is_essentially_complete(self, long_caption_segments):
        units, chunks = segment(long_caption_segments)
        total = units[-1].end - units[0].start
        covered = sum(c.duration for c in chunks)
        assert covered / total > 0.95

    def test_chunks_do_not_overlap_and_are_ordered(self, long_caption_segments):
        _, chunks = segment(long_caption_segments)
        for earlier, later in zip(chunks, chunks[1:]):
            assert earlier.end <= later.start + 1e-6

    def test_chunk_ids_are_unique(self, long_caption_segments):
        _, chunks = segment(long_caption_segments)
        ids = [c.id for c in chunks]
        assert len(ids) == len(set(ids))


class TestMaxDurationGuarantee:
    """No input may produce a chunk over the ceiling."""

    @pytest.mark.parametrize("count", [1, 2, 5, 26, 100, 600])
    def test_never_exceeds_ceiling(self, count):
        _, chunks = segment(make_caption_segments(count))
        assert all(c.duration <= MAX_D + 1e-6 for c in chunks)

    def test_single_enormous_unpunctuated_segment_is_force_split(self):
        """One 600s segment with no pauses and no punctuation."""
        segs = [
            TranscriptSegment(
                id=1, start=0.0, end=600.0,
                text=" ".join(["word"] * 1200), speaker="A",
            )
        ]
        _, chunks = segment(segs)
        assert len(chunks) >= 7
        assert all(c.duration <= MAX_D + 1e-6 for c in chunks)

    def test_very_long_single_segment_covers_the_whole_span(self):
        segs = [
            TranscriptSegment(id=1, start=0.0, end=300.0,
                              text=" ".join(["token"] * 600), speaker="A")
        ]
        _, chunks = segment(segs)
        assert chunks[0].start == pytest.approx(0.0, abs=1.0)
        assert chunks[-1].end == pytest.approx(300.0, abs=2.0)


class TestSeamScoring:
    def test_pause_raises_the_seam_score(self):
        segs = [
            TranscriptSegment(id=1, start=0.0, end=3.0, text="first idea", speaker="A"),
            TranscriptSegment(id=2, start=3.1, end=6.0, text="continues on", speaker="A"),
            TranscriptSegment(id=3, start=9.0, end=12.0, text="new topic now", speaker="A"),
        ]
        units = build_sentence_units(segs)
        seams = score_seams(units)
        assert seams, "expected at least one seam"
        best = max(seams, key=lambda s: s.score)
        assert "pause" in best.reason

    def test_semantic_dips_contribute_when_supplied(self):
        segs = make_caption_segments(12)
        units = build_sentence_units(segs)
        without = score_seams(units)
        # A similarity of 0 is a maximal dip.
        with_dips = score_seams(units, semantic_dips={0: 0.0})
        assert with_dips[0].score > without[0].score
        assert "semantic dip" in with_dips[0].reason

    def test_seam_count_matches_unit_gaps(self):
        units = build_sentence_units(make_caption_segments(30))
        assert len(score_seams(units)) == len(units) - 1


class TestBoundaryReasons:
    def test_reasons_are_populated(self, punctuated_segments):
        _, chunks = segment(punctuated_segments)
        assert all(c.boundary_reason for c in chunks)

    def test_not_every_boundary_claims_a_topic_transition(self, long_caption_segments):
        """The original labelled every boundary 'Linguistic topic transition
        indicator detected', including on input with no such indicators."""
        _, chunks = segment(long_caption_segments)
        reasons = {c.boundary_reason for c in chunks}
        assert len(reasons) > 1 or "no strong cue" in reasons


class TestKeyConcepts:
    def test_ranks_by_frequency_not_transcript_order(self):
        text = "pricing pricing pricing customers customers alphabetical"
        concepts = extract_key_concepts(text, limit=3)
        assert concepts[0] == "pricing"
        assert concepts[1] == "customers"

    def test_is_deterministic_across_calls(self):
        text = "alpha beta gamma delta alpha beta gamma alpha beta alpha"
        assert extract_key_concepts(text) == extract_key_concepts(text)

    def test_drops_stopwords_and_short_words(self):
        concepts = extract_key_concepts("the and but a of to pricing")
        assert "the" not in concepts
        assert "pricing" in concepts

    def test_empty_text(self):
        assert extract_key_concepts("") == []


class TestSummary:
    def test_topic_summary_does_not_cut_mid_word(self, punctuated_segments):
        """The original used text[:60] + '...' and routinely split words."""
        _, chunks = segment(punctuated_segments)
        for chunk in chunks:
            summary = chunk.topic_summary
            if summary.endswith("..."):
                stem = summary[:-3].rstrip()
                assert not stem or stem[-1] != "-"
                # The truncated form must end on a whole word from the text.
                assert stem.split()[-1] in chunk.text.split()
