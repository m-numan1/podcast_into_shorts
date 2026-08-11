"""Chief editor synthesis: B1, B2, B12, B13, B14, B15."""

from __future__ import annotations

import pytest

from config.settings import settings
from src.agents.chief_editor import (
    RankedCandidate,
    aggregate_confidence,
    aggregate_virality,
    composite_score,
    compute_adjustments,
    deduplicate,
    derive_hashtags,
    derive_title,
    first_sentence,
    retention_label,
    summarise,
    synthesise,
)
from src.agents.editors import AGENTS, evaluate_heuristically
from src.schema.clips import ClipEvaluation, DataProvenance, ExtractedFeatures
from tests.conftest import make_candidate

PROVENANCE = DataProvenance(
    media_source="local_file",
    transcript_source="whisper",
    scoring_mode="heuristic",
    embedding_backend="lexical",
)


def build_evaluation(**overrides) -> ClipEvaluation:
    base = dict(
        agent_name="Test", hook_strength=5.0, curiosity=5.0, emotional_impact=5.0,
        story_completeness=5.0, educational_value=5.0, entertainment=5.0,
        standalone_quality=5.0, shareability=5.0, comment_potential=5.0,
        watch_time_prediction=5.0, virality_score=5.0, replay_value=5.0,
        confidence_score=5.0, overall_score=5.0, reasoning="test",
    )
    base.update(overrides)
    return ClipEvaluation(**base)


def all_agent_evaluations(candidate) -> dict[str, ClipEvaluation]:
    return {a.key: evaluate_heuristically(a, candidate) for a in AGENTS}


class TestB1Summarise:
    """The original checked words[-1] -- the last word of the whole transcript,
    not of the 28-word slice -- and raised IndexError on empty input."""

    def test_empty_text_returns_empty_not_indexerror(self):
        assert summarise("") == ""
        assert summarise("   ") == ""

    def test_short_text_already_terminated_is_unchanged(self):
        assert summarise("A complete sentence.") == "A complete sentence."

    def test_short_text_without_terminator_gets_a_period(self):
        assert summarise("No terminator here") == "No terminator here."

    def test_long_text_is_truncated_with_ellipsis(self):
        text = " ".join(f"w{i}" for i in range(1, 40)) + " end."
        result = summarise(text, max_words=28)
        assert result.endswith("...")
        # 28 words plus the ellipsis.
        assert len(result.split()) == 28
        assert "w29" not in result

    def test_terminator_check_inspects_the_slice_not_the_whole_text(self):
        """The regression: the 40th word ends with '.', so the original added
        nothing even though the 28-word slice ended mid-sentence."""
        text = " ".join(f"w{i}" for i in range(1, 40)) + " end."
        result = summarise(text, max_words=28)
        assert result.split()[-1] != "w28", "must be marked as truncated"
        assert result.endswith("...")

    def test_slice_ending_on_a_terminator_is_not_ellipsised(self):
        words = ["word"] * 27 + ["final."] + ["extra"] * 5
        result = summarise(" ".join(words), max_words=28)
        assert result.endswith("final.")

    def test_first_sentence_handles_empty(self):
        assert first_sentence("") == ""

    def test_first_sentence_stops_at_terminator(self):
        assert first_sentence("First one. Second one.") == "First one."


class TestB2Deduplication:
    """Containment must be detected regardless of which clip is longer."""

    def test_long_clip_containing_a_kept_short_clip_is_dropped(self):
        short = make_candidate("short", 100.0, 130.0)
        long = make_candidate("long", 90.0, 180.0)
        ranked = [
            RankedCandidate(short, {"hook": build_evaluation()}, 9.0),
            RankedCandidate(long, {"hook": build_evaluation()}, 8.0),
        ]
        kept = deduplicate(ranked, overlap_threshold=0.5)
        assert [r.candidate.id for r in kept] == ["short"]

    def test_short_clip_inside_a_kept_long_clip_is_dropped(self):
        long = make_candidate("long", 90.0, 180.0)
        short = make_candidate("short", 100.0, 130.0)
        ranked = [
            RankedCandidate(long, {"hook": build_evaluation()}, 9.0),
            RankedCandidate(short, {"hook": build_evaluation()}, 8.0),
        ]
        kept = deduplicate(ranked, overlap_threshold=0.5)
        assert [r.candidate.id for r in kept] == ["long"]

    def test_disjoint_clips_are_both_kept(self):
        ranked = [
            RankedCandidate(make_candidate("a", 0.0, 40.0), {"hook": build_evaluation()}, 9.0),
            RankedCandidate(make_candidate("b", 100.0, 140.0), {"hook": build_evaluation()}, 8.0),
        ]
        kept = deduplicate(ranked, overlap_threshold=0.5)
        assert len(kept) == 2

    def test_small_overlap_is_kept(self):
        ranked = [
            RankedCandidate(make_candidate("a", 0.0, 60.0), {"hook": build_evaluation()}, 9.0),
            RankedCandidate(make_candidate("b", 55.0, 115.0), {"hook": build_evaluation()}, 8.0),
        ]
        kept = deduplicate(ranked, overlap_threshold=0.5)
        assert len(kept) == 2

    def test_semantic_near_duplicates_are_dropped(self):
        """Same point restated later; the clips do not overlap in time at all."""
        first = make_candidate("first", 0.0, 40.0)
        first.semantic_chunk_ids = ["chunk_001"]
        later = make_candidate("later", 600.0, 640.0)
        later.semantic_chunk_ids = ["chunk_050"]
        ranked = [
            RankedCandidate(first, {"hook": build_evaluation()}, 9.0),
            RankedCandidate(later, {"hook": build_evaluation()}, 8.0),
        ]
        kept = deduplicate(
            ranked, overlap_threshold=0.5,
            near_duplicate_pairs={("chunk_001", "chunk_050")},
        )
        assert [r.candidate.id for r in kept] == ["first"]


class TestB15Aggregation:
    """virality came from one agent; confidence was the literal 9.2."""

    def test_virality_averages_all_agents(self):
        evaluations = {
            "hook": build_evaluation(virality_score=10.0),
            "debate": build_evaluation(virality_score=0.0),
            "story": build_evaluation(virality_score=5.0),
        }
        assert aggregate_virality(evaluations) == pytest.approx(5.0)

    def test_confidence_is_reduced_when_agents_disagree(self):
        agreeing = {
            "a": build_evaluation(confidence_score=8.0, overall_score=7.0),
            "b": build_evaluation(confidence_score=8.0, overall_score=7.0),
        }
        disagreeing = {
            "a": build_evaluation(confidence_score=8.0, overall_score=1.0),
            "b": build_evaluation(confidence_score=8.0, overall_score=9.0),
        }
        assert aggregate_confidence(agreeing) > aggregate_confidence(disagreeing)

    def test_confidence_is_not_a_constant_across_clips(self):
        low = make_candidate("low", 0.0, 45.0, starts_clean=False, ends_clean=False)
        high = make_candidate(
            "high", 0.0, 45.0,
            features=ExtractedFeatures(chunk_id="c", topic_confidence=1.0),
        )
        assert aggregate_confidence(all_agent_evaluations(low)) != \
               aggregate_confidence(all_agent_evaluations(high))

    def test_empty_evaluations(self):
        assert aggregate_virality({}) == 0.0
        assert aggregate_confidence({}) == 0.0


class TestCompositeScore:
    def test_uses_configured_weights(self):
        evaluations = {
            "hook": build_evaluation(hook_strength=10.0),
            "debate": build_evaluation(comment_potential=10.0),
            "educational": build_evaluation(educational_value=10.0),
            "retention": build_evaluation(watch_time_prediction=10.0),
            "story": build_evaluation(story_completeness=10.0),
        }
        # All authoritative metrics at 10 and weights summing to 1.0 -> 10.
        assert composite_score(evaluations) == pytest.approx(10.0)

    def test_missing_agents_do_not_crash(self):
        assert composite_score({"hook": build_evaluation(hook_strength=10.0)}) > 0

    def test_empty(self):
        assert composite_score({}) == 0.0


class TestB14RetentionLabel:
    """A 0-10 editorial score was rendered as a completion percentage."""

    def test_label_reports_the_score_not_a_fabricated_percentage(self):
        label = retention_label(7.0)
        assert "7.0/10" in label
        assert "%" not in label

    @pytest.mark.parametrize("score,word", [
        (9.0, "High"), (7.0, "Moderate"), (5.0, "Uncertain"), (2.0, "Low"),
    ])
    def test_bands(self, score, word):
        assert retention_label(score).startswith(word)


class TestB12DeterministicHashtags:
    """`list(set(...))` reordered between runs because str hashing is salted."""

    def test_same_input_gives_same_order(self):
        candidate = make_candidate(
            "a", 0.0, 45.0,
            features=ExtractedFeatures(
                chunk_id="c",
                keyword_density={"pricing": 4, "customers": 3, "churn": 2},
                named_entities=["OpenAI", "Stripe"],
            ),
        )
        assert derive_hashtags(candidate) == derive_hashtags(candidate)

    def test_ordering_follows_the_input(self):
        candidate = make_candidate(
            "a", 0.0, 45.0,
            features=ExtractedFeatures(
                chunk_id="c", keyword_density={"pricing": 4, "customers": 3},
            ),
        )
        tags = derive_hashtags(candidate)
        assert tags.index("#Pricing") < tags.index("#Customers")

    def test_falls_back_when_no_keywords(self):
        assert derive_hashtags(make_candidate("a", 0.0, 45.0)) == \
               ["#Podcast", "#Shorts", "#Clips"]

    def test_no_duplicates(self):
        candidate = make_candidate(
            "a", 0.0, 45.0,
            features=ExtractedFeatures(
                chunk_id="c", keyword_density={"pricing": 2}, named_entities=["pricing"],
            ),
        )
        tags = derive_hashtags(candidate)
        assert len(tags) == len(set(tags))


class TestTitleDerivation:
    def test_uses_the_opening_clause_not_word_salad(self):
        """The original capitalised the first four long words, producing
        "That Terrifying Share Concrete (Clip #1)"."""
        candidate = make_candidate(
            "a", 0.0, 45.0,
            text="That is a terrifying reality. Can you share a concrete example?",
        )
        title = derive_title(candidate, "Tech Insights", 1)
        assert "That is a terrifying reality" in title
        assert "Terrifying Share Concrete" not in title

    def test_length_is_bounded(self):
        candidate = make_candidate("a", 0.0, 45.0, text="word " * 200)
        assert len(derive_title(candidate, "A Very Long Podcast Name Indeed", 1)) <= 74

    def test_falls_back_to_keywords_for_tiny_text(self):
        candidate = make_candidate(
            "a", 0.0, 45.0, text="Ok.",
            features=ExtractedFeatures(chunk_id="c", keyword_density={"pricing": 3}),
        )
        assert "Pricing" in derive_title(candidate, "Show", 1)


class TestAdjustments:
    """The original emitted identical hardcoded prose for every clip."""

    def test_adjustments_derive_from_measured_silence(self):
        candidate = make_candidate("a", 10.0, 55.0)
        candidate.lead_in_silence_sec = 1.0
        candidate.lead_out_silence_sec = 0.8
        start_adj, end_adj, rationale = compute_adjustments(candidate)
        assert start_adj == pytest.approx(-0.5)
        assert end_adj == pytest.approx(0.4)
        assert "lead-in silence" in rationale

    def test_no_silence_means_no_adjustment(self):
        candidate = make_candidate("a", 10.0, 55.0)
        candidate.lead_in_silence_sec = 0.0
        candidate.lead_out_silence_sec = 0.0
        start_adj, end_adj, _ = compute_adjustments(candidate)
        assert start_adj == 0.0
        assert end_adj == 0.0

    def test_adjustments_are_capped(self):
        candidate = make_candidate("a", 10.0, 55.0)
        candidate.lead_in_silence_sec = 60.0
        candidate.lead_out_silence_sec = 60.0
        start_adj, end_adj, _ = compute_adjustments(candidate)
        assert start_adj == pytest.approx(-0.6)
        assert end_adj == pytest.approx(0.5)

    def test_ragged_edges_are_reported(self):
        candidate = make_candidate(
            "a", 10.0, 55.0, starts_clean=False, ends_clean=False
        )
        candidate.lead_in_silence_sec = 0.0
        candidate.lead_out_silence_sec = 0.0
        _, _, rationale = compute_adjustments(candidate)
        assert "mid-sentence" in rationale

    def test_adjustments_differ_between_clips(self):
        a = make_candidate("a", 0.0, 45.0)
        a.lead_in_silence_sec = 1.2
        b = make_candidate("b", 0.0, 45.0)
        b.lead_in_silence_sec = 0.2
        assert compute_adjustments(a)[0] != compute_adjustments(b)[0]


class TestSynthesise:
    def _candidates(self, count, spacing=200.0):
        return [
            make_candidate(f"cand_{i:03d}", i * spacing, i * spacing + 45.0,
                           text=f"Point number {i} about pricing and customers. "
                                f"It stands alone and makes a claim.")
            for i in range(count)
        ]

    def _evaluations(self, candidates):
        return {c.id: all_agent_evaluations(c) for c in candidates}

    def test_produces_clips_with_sequential_ranks(self):
        candidates = self._candidates(8)
        clips, _ = synthesise(
            candidates, self._evaluations(candidates),
            podcast_title="Show", llm=None, provenance=PROVENANCE,
        )
        assert [c.rank for c in clips] == list(range(1, len(clips) + 1))

    def test_b13_honours_the_configured_maximum(self, monkeypatch):
        monkeypatch.setattr(settings, "target_clip_count_max", 3)
        candidates = self._candidates(12)
        clips, _ = synthesise(
            candidates, self._evaluations(candidates),
            podcast_title="Show", llm=None, provenance=PROVENANCE,
        )
        assert len(clips) == 3

    def test_b13_warns_when_below_the_minimum(self, monkeypatch):
        monkeypatch.setattr(settings, "target_clip_count_min", 10)
        candidates = self._candidates(2)
        clips, warnings = synthesise(
            candidates, self._evaluations(candidates),
            podcast_title="Show", llm=None, provenance=PROVENANCE,
        )
        assert len(clips) == 2
        assert any("fewer than the configured minimum" in w for w in warnings)

    def test_clips_are_ordered_by_descending_score(self):
        candidates = self._candidates(6)
        clips, _ = synthesise(
            candidates, self._evaluations(candidates),
            podcast_title="Show", llm=None, provenance=PROVENANCE,
        )
        scores = [c.overall_score for c in clips]
        assert scores == sorted(scores, reverse=True)

    def test_provenance_is_attached_to_every_clip(self):
        candidates = self._candidates(4)
        clips, _ = synthesise(
            candidates, self._evaluations(candidates),
            podcast_title="Show", llm=None, provenance=PROVENANCE,
        )
        assert all(c.provenance is not None for c in clips)
        assert all(c.provenance.scoring_mode == "heuristic" for c in clips)

    def test_adjusted_timestamps_are_populated(self):
        candidates = self._candidates(3)
        clips, _ = synthesise(
            candidates, self._evaluations(candidates),
            podcast_title="Show", llm=None, provenance=PROVENANCE,
        )
        for clip in clips:
            assert clip.adjusted_start_seconds >= 0
            assert clip.adjusted_end_seconds > clip.adjusted_start_seconds

    def test_output_is_deterministic(self):
        candidates = self._candidates(6)
        evaluations = self._evaluations(candidates)
        first, _ = synthesise(candidates, evaluations, podcast_title="Show",
                             llm=None, provenance=PROVENANCE)
        second, _ = synthesise(candidates, evaluations, podcast_title="Show",
                               llm=None, provenance=PROVENANCE)
        assert [c.id for c in first] == [c.id for c in second]
        assert [c.suggested_hashtags for c in first] == \
               [c.suggested_hashtags for c in second]

    def test_candidates_without_evaluations_are_reported(self):
        candidates = self._candidates(4)
        evaluations = self._evaluations(candidates)
        del evaluations[candidates[0].id]
        clips, warnings = synthesise(
            candidates, evaluations, podcast_title="Show",
            llm=None, provenance=PROVENANCE,
        )
        assert any("no agent evaluation" in w for w in warnings)
        assert all(c.id != candidates[0].id for c in clips)
