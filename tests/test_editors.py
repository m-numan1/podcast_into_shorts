"""Editor agents.

The original returned 12 hardcoded constants out of 14 metrics per evaluation,
gave every clip `confidence_score=9.2`, and keyed off literal phrases from the
demo transcript ("99% of ai startups fail", "flywheels", "moat") so real
episodes scored the constant floor. `LLMProvider` was built and never called.
"""

from __future__ import annotations

import pytest

from src.agents.editors import (
    AGENTS,
    AGENTS_BY_KEY,
    evaluate,
    evaluate_heuristically,
)
from src.schema.clips import ExtractedFeatures
from tests.conftest import make_candidate

RICH = ExtractedFeatures(
    chunk_id="c", curiosity_score=0.9, strong_statement_score=0.85,
    story_likelihood=0.8, emotion_score=0.7, sentiment_score=0.6,
    speaking_rate_wpm=155.0, question_count=2, topic_confidence=0.9,
    keyword_density={"pricing": 4, "churn": 2}, named_entities=["Stripe"],
)
PLAIN = ExtractedFeatures(
    chunk_id="c", curiosity_score=0.15, strong_statement_score=0.15,
    story_likelihood=0.15, emotion_score=0.05, sentiment_score=0.0,
    speaking_rate_wpm=95.0, question_count=0, topic_confidence=0.3,
)


def test_there_are_six_agents_with_distinct_keys():
    assert len(AGENTS) == 6
    assert len({a.key for a in AGENTS}) == 6
    assert len({a.name for a in AGENTS}) == 6


def test_each_agent_has_a_distinct_persona_and_focus():
    assert len({a.persona for a in AGENTS}) == 6
    assert len({a.focus for a in AGENTS}) == 6


def test_agent_weights_sum_to_one():
    for agent in AGENTS:
        assert sum(agent.weights.values()) == pytest.approx(1.0), agent.key


def test_focus_metric_is_weighted_in_the_overall_score():
    for agent in AGENTS:
        assert agent.focus in agent.weights


class TestScoresVaryNotConstant:
    def test_rich_content_outscores_plain_content(self):
        rich = make_candidate("r", 0.0, 45.0, features=RICH)
        plain = make_candidate("p", 0.0, 45.0, features=PLAIN)
        for agent in AGENTS:
            rich_eval = evaluate_heuristically(agent, rich)
            plain_eval = evaluate_heuristically(agent, plain)
            assert rich_eval.overall_score > plain_eval.overall_score, agent.key

    def test_confidence_is_not_always_nine_point_two(self):
        candidate = make_candidate("a", 0.0, 45.0, features=PLAIN)
        for agent in AGENTS:
            assert evaluate_heuristically(agent, candidate).confidence_score != 9.2

    def test_confidence_varies_with_signal_quality(self):
        strong = make_candidate("s", 0.0, 45.0, features=RICH)
        weak = make_candidate(
            "w", 0.0, 45.0, features=PLAIN, starts_clean=False, ends_clean=False
        )
        agent = AGENTS_BY_KEY["hook"]
        assert evaluate_heuristically(agent, strong).confidence_score > \
               evaluate_heuristically(agent, weak).confidence_score

    def test_different_agents_disagree_about_the_same_clip(self):
        candidate = make_candidate("a", 0.0, 45.0, features=RICH)
        scores = {
            a.key: evaluate_heuristically(a, candidate).overall_score for a in AGENTS
        }
        assert len(set(scores.values())) > 1, "six agents returning one value is a smell"

    def test_metrics_within_one_evaluation_are_not_all_identical(self):
        candidate = make_candidate("a", 0.0, 45.0, features=RICH)
        ev = evaluate_heuristically(AGENTS_BY_KEY["hook"], candidate)
        values = {
            ev.hook_strength, ev.curiosity, ev.emotional_impact,
            ev.story_completeness, ev.educational_value, ev.entertainment,
            ev.standalone_quality, ev.shareability, ev.comment_potential,
            ev.watch_time_prediction, ev.replay_value,
        }
        assert len(values) >= 6, "the original had 12 of 14 as literal constants"


class TestBoundaryAwareness:
    def test_clean_edges_beat_ragged_edges(self):
        clean = make_candidate("c", 0.0, 45.0, features=RICH,
                               starts_clean=True, ends_clean=True)
        ragged = make_candidate("r", 0.0, 45.0, features=RICH,
                                starts_clean=False, ends_clean=False)
        agent = AGENTS_BY_KEY["story"]
        assert evaluate_heuristically(agent, clean).standalone_quality > \
               evaluate_heuristically(agent, ragged).standalone_quality

    def test_unresolved_opening_reference_is_penalised(self):
        dangling = make_candidate(
            "d", 0.0, 45.0, features=RICH,
            text="And then he said the thing about pricing that changed everything.",
        )
        standalone = make_candidate(
            "s", 0.0, 45.0, features=RICH,
            text="Pricing is the single most underrated lever a founder controls.",
        )
        agent = AGENTS_BY_KEY["hook"]
        assert evaluate_heuristically(agent, dangling).hook_strength < \
               evaluate_heuristically(agent, standalone).hook_strength

    def test_dangling_reference_is_mentioned_in_the_reasoning(self):
        dangling = make_candidate(
            "d", 0.0, 45.0, features=RICH, text="But it was the same problem again.",
        )
        reasoning = evaluate_heuristically(AGENTS_BY_KEY["hook"], dangling).reasoning
        assert "unresolved opening reference" in reasoning


class TestScoringModeIsStamped:
    def test_heuristic_evaluations_are_labelled(self):
        candidate = make_candidate("a", 0.0, 45.0, features=RICH)
        for agent in AGENTS:
            ev = evaluate_heuristically(agent, candidate)
            assert ev.scoring_mode == "heuristic"
            assert ev.model_name is None

    def test_reasoning_says_no_model_was_used(self):
        candidate = make_candidate("a", 0.0, 45.0, features=RICH)
        reasoning = evaluate_heuristically(AGENTS_BY_KEY["hook"], candidate).reasoning
        assert "no model configured" in reasoning

    def test_evaluate_without_an_llm_uses_the_heuristic_path(self):
        candidate = make_candidate("a", 0.0, 45.0, features=RICH)
        ev = evaluate(AGENTS_BY_KEY["hook"], candidate, None, 600.0)
        assert ev.scoring_mode == "heuristic"


class TestScoreBounds:
    @pytest.mark.parametrize("features", [RICH, PLAIN, ExtractedFeatures(chunk_id="c")])
    def test_all_metrics_stay_within_zero_to_ten(self, features):
        candidate = make_candidate("a", 0.0, 45.0, features=features)
        for agent in AGENTS:
            ev = evaluate_heuristically(agent, candidate)
            for field, value in ev.model_dump().items():
                if isinstance(value, float):
                    assert 0.0 <= value <= 10.0, f"{agent.key}.{field} = {value}"

    def test_extreme_features_do_not_overflow(self):
        extreme = ExtractedFeatures(
            chunk_id="c", curiosity_score=1.0, strong_statement_score=1.0,
            story_likelihood=1.0, emotion_score=1.0, sentiment_score=1.0,
            speaking_rate_wpm=400.0, question_count=50, topic_confidence=1.0,
            keyword_density={f"w{i}": 10 for i in range(20)},
            named_entities=[f"E{i}" for i in range(20)],
        )
        candidate = make_candidate("a", 0.0, 45.0, features=extreme)
        for agent in AGENTS:
            ev = evaluate_heuristically(agent, candidate)
            assert 0.0 <= ev.overall_score <= 10.0


class TestNoDemoTranscriptKeywords:
    def test_agents_do_not_key_off_demo_transcript_phrases(self):
        """Checks code string literals only.

        The module docstring names these phrases to record what was removed, so
        a raw substring scan over the file would match its own documentation.
        """
        from tests.conftest import code_string_literals

        literals = " ".join(code_string_literals("src/agents/editors.py")).lower()
        for phrase in ("99% of ai startups fail", "flywheels", "vanishes overnight",
                       "rule number one", "stop chasing", "moat"):
            assert phrase not in literals, phrase

    def test_demo_content_gets_no_special_treatment(self):
        """Demo-transcript text must not score above unrelated text of equal
        measured quality."""
        features = RICH
        demo_text = "Rule number one: stop chasing shiny technology. Build a moat."
        other_text = "The arctic tern migrates eleven thousand miles every year."
        demo = make_candidate("d", 0.0, 45.0, features=features, text=demo_text)
        other = make_candidate("o", 0.0, 45.0, features=features, text=other_text)
        agent = AGENTS_BY_KEY["educational"]
        assert evaluate_heuristically(agent, demo).educational_value == \
               evaluate_heuristically(agent, other).educational_value
