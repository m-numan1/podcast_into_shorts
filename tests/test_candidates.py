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
)
from src.analysis.features import extract_all
from src.analysis.segmentation import build_sentence_units, segment_units
from src.errors import CandidateGenerationError
from src.schema.clips import ExtractedFeatures, TranscriptSegment
from tests.conftest import make_candidate, make_caption_segments

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
