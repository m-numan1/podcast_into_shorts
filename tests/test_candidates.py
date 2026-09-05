"""Candidate generation and shortlisting.

The original node discarded any chunk outside the duration band without ever
sub-splitting it, only merged adjacent pairs, and returned an empty list
silently so node_08 failed downstream instead of the real cause being reported.
"""

from __future__ import annotations

import pytest

from src.analysis.candidates import (
    cheap_prescore,
    chunk_unit_ranges,
    generate_candidates,
    shortlist_candidates,
    trim_leading_backchannel,
)
from src.analysis.features import extract_all
from src.analysis.segmentation import build_sentence_units, segment_units
from src.errors import CandidateGenerationError
from src.schema.clips import ExtractedFeatures, SemanticChunk, TranscriptSegment
from tests.conftest import make_candidate, make_caption_segments, make_unit

MIN_D, MAX_D, OPT_D = 15.0, 90.0, 45.0


def pipeline_to_candidates(segments, min_d=MIN_D, max_d=MAX_D):
    units = build_sentence_units(segments)
    chunks = segment_units(
        units, min_duration=8.0, max_duration=max_d, optimal_duration=OPT_D
    )
    features = extract_all(chunks, units)
    return units, chunks, generate_candidates(
        units, chunks, features, min_duration=min_d, max_duration=max_d
    )


class TestGeneration:
    def test_thirty_minute_transcript_produces_candidates(self, long_caption_segments):
        _, _, candidates = pipeline_to_candidates(long_caption_segments)
        assert len(candidates) >= 5, "zero candidates was the original §4 failure"

    def test_short_transcript_produces_candidates(self, caption_segments):
        _, _, candidates = pipeline_to_candidates(caption_segments)
        assert len(candidates) >= 1

    def test_all_candidates_respect_the_duration_band(self, long_caption_segments):
        _, _, candidates = pipeline_to_candidates(long_caption_segments)
        assert all(MIN_D <= c.duration <= MAX_D for c in candidates)

    def test_candidate_ids_are_unique_and_sequential(self, long_caption_segments):
        _, _, candidates = pipeline_to_candidates(long_caption_segments)
        ids = [c.id for c in candidates]
        assert len(ids) == len(set(ids))
        assert ids == [f"cand_{i:03d}" for i in range(1, len(ids) + 1)]

    def test_candidates_are_sorted_by_start_time(self, long_caption_segments):
        _, _, candidates = pipeline_to_candidates(long_caption_segments)
        starts = [c.start_time for c in candidates]
        assert starts == sorted(starts)

    def test_boundary_flags_set_for_punctuated_input(self, punctuated_segments):
        _, _, candidates = pipeline_to_candidates(punctuated_segments)
        assert any(
            c.starts_on_sentence_boundary and c.ends_on_sentence_boundary
            for c in candidates
        )

    def test_sub_windows_are_generated_inside_long_chunks(self):
        """A long chunk must yield more than one candidate, not be discarded."""
        segs = make_caption_segments(30, fragment_duration=3.0, gap=0.0)
        units = build_sentence_units(segs)
        chunks = segment_units(
            units, min_duration=8.0, max_duration=90.0, optimal_duration=45.0
        )
        features = extract_all(chunks, units)
        candidates = generate_candidates(
            units, chunks, features, min_duration=15.0, max_duration=90.0
        )
        # More candidates than chunks means merging and/or sub-windowing ran.
        assert len(candidates) > len(chunks)

    def test_raises_when_source_is_too_short(self):
        segs = [
            TranscriptSegment(id=1, start=0.0, end=4.0, text="Way too short.", speaker="A")
        ]
        units = build_sentence_units(segs)
        chunks = segment_units(
            units, min_duration=1.0, max_duration=90.0, optimal_duration=45.0
        )
        features = extract_all(chunks, units)
        with pytest.raises(CandidateGenerationError, match="shorter than"):
            generate_candidates(
                units, chunks, features, min_duration=15.0, max_duration=90.0
            )

    def test_raises_rather_than_returning_empty(self):
        with pytest.raises(CandidateGenerationError):
            generate_candidates([], [], {}, min_duration=15.0, max_duration=90.0)

    def test_merged_features_are_deterministic(self, caption_segments):
        """`list(set(...))` on entities made ordering vary between runs."""
        _, _, first = pipeline_to_candidates(caption_segments)
        _, _, second = pipeline_to_candidates(caption_segments)
        assert [c.feature_summary.named_entities for c in first] == \
               [c.feature_summary.named_entities for c in second]


class TestChunkUnitRanges:
    def test_ranges_partition_the_units(self, caption_segments):
        units = build_sentence_units(caption_segments)
        chunks = segment_units(
            units, min_duration=8.0, max_duration=90.0, optimal_duration=45.0
        )
        ranges = chunk_unit_ranges(units, chunks)
        assert len(ranges) == len(chunks)
        assert ranges[0][0] == 0
        for (_, prev_last), (next_first, _) in zip(ranges, ranges[1:], strict=False):
            assert next_first == prev_last + 1


class TestShortlist:
    def test_respects_the_limit(self):
        candidates = [
            make_candidate(f"cand_{i:03d}", i * 10.0, i * 10.0 + 40.0)
            for i in range(60)
        ]
        kept = shortlist_candidates(
            candidates, limit=10, optimal_duration=OPT_D, overlap_threshold=0.55
        )
        assert len(kept) == 10

    def test_returns_everything_when_under_the_limit(self):
        candidates = [make_candidate("cand_001", 0.0, 40.0)]
        kept = shortlist_candidates(
            candidates, limit=10, optimal_duration=OPT_D, overlap_threshold=0.55
        )
        assert len(kept) == 1

    def test_output_is_time_ordered(self):
        candidates = [
            make_candidate(f"cand_{i:03d}", i * 30.0, i * 30.0 + 45.0)
            for i in range(40)
        ]
        kept = shortlist_candidates(
            candidates, limit=12, optimal_duration=OPT_D, overlap_threshold=0.5
        )
        starts = [c.start_time for c in kept]
        assert starts == sorted(starts)

    def test_spreads_across_the_episode_rather_than_clustering(self):
        """Twenty near-identical windows plus five spread out: suppression
        should reach the later ones instead of spending the budget on one spot."""
        clustered = [
            make_candidate(f"cluster_{i:03d}", 100.0 + i * 0.5, 145.0 + i * 0.5)
            for i in range(20)
        ]
        spread = [
            make_candidate(f"spread_{i:03d}", 400.0 + i * 200.0, 445.0 + i * 200.0)
            for i in range(5)
        ]
        kept = shortlist_candidates(
            clustered + spread, limit=6, optimal_duration=OPT_D, overlap_threshold=0.5
        )
        assert sum(1 for c in kept if c.id.startswith("spread")) >= 3

    def test_is_deterministic(self):
        candidates = [
            make_candidate(f"cand_{i:03d}", i * 25.0, i * 25.0 + 45.0)
            for i in range(50)
        ]
        first = shortlist_candidates(
            candidates, limit=8, optimal_duration=OPT_D, overlap_threshold=0.55
        )
        second = shortlist_candidates(
            candidates, limit=8, optimal_duration=OPT_D, overlap_threshold=0.55
        )
        assert [c.id for c in first] == [c.id for c in second]


class TestCheapPrescore:
    def test_optimal_duration_scores_higher_than_extremes(self):
        good = make_candidate("a", 0.0, OPT_D)
        short = make_candidate("b", 0.0, 15.0)
        assert cheap_prescore(good, OPT_D) > cheap_prescore(short, OPT_D)

    def test_clean_edges_score_higher(self):
        clean = make_candidate("a", 0.0, 45.0, starts_clean=True, ends_clean=True)
        ragged = make_candidate("b", 0.0, 45.0, starts_clean=False, ends_clean=False)
        assert cheap_prescore(clean, OPT_D) > cheap_prescore(ragged, OPT_D)

    def test_high_cue_features_score_higher(self):
        plain = make_candidate("a", 0.0, 45.0)
        rich = make_candidate(
            "b", 0.0, 45.0,
            features=ExtractedFeatures(
                chunk_id="c", curiosity_score=1.0,
                strong_statement_score=1.0, story_likelihood=1.0,
            ),
        )
        assert cheap_prescore(rich, OPT_D) > cheap_prescore(plain, OPT_D)


class TestLeadingBackchannelTrim:
    """A clip must not open on the previous speaker's tail.

    A real run shipped clips starting "Mhm.", "Absolutely.", "Exactly." and
    "No difference." -- acknowledgment noise, not the clip's content.
    """

    @staticmethod
    def units(texts_and_spans, gap_before=0.5):
        """Sentence units from (text, start, end) triples."""
        return [
            make_unit(i + 1, start, end, text=text,
                      ends_sentence=True, gap_before=gap_before)
            for i, (text, start, end) in enumerate(texts_and_spans)
        ]

    def test_leading_backchannels_are_skipped(self):
        units = self.units([
            ("Mhm.", 0.0, 1.0),
            ("Absolutely.", 1.0, 2.0),
            ("Most founders skip the hardest part of building a company.", 2.0, 30.0),
        ])
        assert trim_leading_backchannel(units, 0, 2, min_duration=15.0) == 2

    def test_candidate_starts_at_the_first_substantive_unit(self):
        units = self.units([
            ("Mhm.", 0.0, 1.0),
            ("Absolutely.", 1.0, 2.0),
            ("Most founders skip the hardest part of building a company.", 2.0, 30.0),
        ])
        chunk = SemanticChunk(
            id="chunk_001", start=0.0, end=30.0,
            text=" ".join(u.text for u in units),
            topic_summary="t", boundary_reason="r", segment_ids=[1, 2, 3],
        )
        candidates = generate_candidates(
            units, [chunk], {}, min_duration=15.0, max_duration=90.0
        )
        assert candidates
        assert candidates[0].start_time == 2.0
        assert not candidates[0].raw_text.lower().startswith("mhm")
        assert candidates[0].raw_text.startswith("Most founders")

    def test_trim_stops_when_it_would_break_the_minimum_duration(self):
        """Trimming must never turn a valid candidate into a discarded one."""
        units = self.units([
            ("Mhm.", 0.0, 1.0),
            ("We doubled our price twice and churn went down.", 1.0, 16.0),
        ])
        # Dropping "Mhm." leaves 15.0s exactly; dropping more is impossible
        # anyway, but a 16s minimum makes the constraint bite.
        assert trim_leading_backchannel(units, 0, 1, min_duration=16.0) == 0
        assert trim_leading_backchannel(units, 0, 1, min_duration=15.0) == 1

    def test_a_clip_with_no_backchannel_opener_is_untouched(self):
        units = self.units([
            ("Most founders skip the hardest part.", 0.0, 10.0),
            ("We doubled our price twice.", 10.0, 25.0),
        ])
        assert trim_leading_backchannel(units, 0, 1, min_duration=15.0) == 0

    def test_never_advances_past_the_first_substantive_unit(self):
        units = self.units([
            ("Yeah.", 0.0, 1.0),
            ("Pricing is the whole game for early companies.", 1.0, 20.0),
            ("Exactly.", 20.0, 21.0),
        ])
        # The trailing "Exactly." is not a *leading* backchannel and stays.
        assert trim_leading_backchannel(units, 0, 2, min_duration=15.0) == 1

    def test_a_window_is_never_emptied(self):
        units = self.units([("Mhm.", 0.0, 1.0), ("Absolutely.", 1.0, 2.0)])
        assert trim_leading_backchannel(units, 0, 1, min_duration=0.5) == 1

    def test_trim_requires_a_sentence_boundary(self):
        """Skipping a unit that does not end a sentence would create a
        mid-sentence cut where the original start was clean."""
        units = [
            make_unit(1, 0.0, 1.0, text="Yeah", ends_sentence=False, gap_before=0.5),
            make_unit(2, 1.0, 30.0, text="pricing changed everything for us.",
                      ends_sentence=True, gap_before=0.0),
        ]
        assert trim_leading_backchannel(units, 0, 1, min_duration=15.0) == 0

    def test_lead_in_silence_is_recomputed_for_the_new_start(self):
        units = [
            make_unit(1, 0.0, 1.0, text="Mhm.", ends_sentence=True, gap_before=0.1),
            make_unit(2, 1.0, 30.0, text="Most founders skip the hardest part.",
                      ends_sentence=True, gap_before=0.9),
        ]
        chunk = SemanticChunk(
            id="chunk_001", start=0.0, end=30.0,
            text=" ".join(u.text for u in units),
            topic_summary="t", boundary_reason="r", segment_ids=[1, 2],
        )
        candidates = generate_candidates(
            units, [chunk], {}, min_duration=15.0, max_duration=90.0
        )
        # 0.9 is the gap before the *new* first unit, not the 0.1 of the old one.
        assert candidates[0].lead_in_silence_sec == pytest.approx(0.9)
