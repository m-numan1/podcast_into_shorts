"""Feature extraction: the B9, B10 and B11 fixes."""

from __future__ import annotations

import pytest

from src.analysis.features import (
    PERCENT_RE,
    extract_features,
    extract_named_entities,
    keyword_density,
)
from src.analysis.segmentation import build_sentence_units, segment_units
from src.schema.clips import SemanticChunk

SAMPLE = (
    "Welcome back to Tech Insights. Today we are diving into why 99% of AI startups "
    "fail. The evidence is available and certain founders explained it. OpenAI "
    "updates a model and the business vanishes. Sam Altman said OpenAI would raise "
    "$6.5 billion."
)


class TestB9PercentRegex:
    """`\\b\\d+%\\b` never matched: `%` before a space is not a word boundary."""

    def test_percentages_are_captured(self):
        assert PERCENT_RE.findall("99% of startups") == ["99%"]

    def test_the_original_pattern_did_not_match(self):
        import re
        assert re.findall(r"\b\d+%\b", "99% of startups") == []

    @pytest.mark.parametrize("text,expected", [
        ("50% done", ["50%"]),
        ("12.5% growth", ["12.5%"]),
        ("up 30 % annually", ["30 %"]),
        ("ends with 80%", ["80%"]),
        ("no digits here", []),
    ])
    def test_variants(self, text, expected):
        assert PERCENT_RE.findall(text) == expected


class TestB10NamedEntities:
    """The original returned any capitalised word, including sentence-initial
    ones: ['Welcome', 'Tech', 'Insights', 'Today', '99', 'The']."""

    def test_extracts_real_entities(self):
        entities = extract_named_entities(SAMPLE)
        assert "OpenAI" in entities
        assert "Tech Insights" in entities

    def test_drops_sentence_initial_non_entities(self):
        entities = extract_named_entities(SAMPLE)
        for junk in ("Welcome", "Today", "The"):
            assert junk not in entities

    def test_captures_quantities_not_bare_numbers(self):
        entities = extract_named_entities(SAMPLE)
        assert "99%" in entities
        assert "99" not in entities

    def test_billion_is_not_truncated_to_b(self):
        """Ordered alternation: 'b' listed before 'billion' truncated the match."""
        entities = extract_named_entities("They raised $6.5 billion last year.")
        assert any("billion" in e for e in entities)
        assert "$6.5 b" not in entities

    def test_is_deterministic(self):
        assert extract_named_entities(SAMPLE) == extract_named_entities(SAMPLE)

    def test_empty_text(self):
        assert extract_named_entities("") == []


class TestB11KeywordDensity:
    """`text.count("ai")` had no word boundaries, so one 'AI' scored 5 by also
    matching f-ai-l, av-ai-lable, cert-ai-n and expl-ai-ned."""

    def test_no_substring_inflation(self):
        density = keyword_density(SAMPLE)
        assert density.get("ai", 0) <= 1

    def test_substring_matches_are_not_counted(self):
        text = "fail available certain explained mountain"
        assert "ai" not in keyword_density(text)

    def test_vocabulary_comes_from_the_text(self):
        """The old fixed 8-word list scored 0 on unrelated content."""
        arctic = (
            "The arctic tern migrates eleven thousand miles. The tern follows "
            "ocean currents and the tern feeds on fish. Researchers tracked the tern."
        )
        density = keyword_density(arctic)
        assert "tern" in density
        assert density["tern"] >= 3

    def test_counts_whole_words(self):
        density = keyword_density("pricing pricing pricing strategy")
        assert density["pricing"] == 3

    def test_stopwords_excluded(self):
        density = keyword_density("the the the and and but pricing pricing")
        assert "the" not in density
        assert "and" not in density

    def test_is_deterministic(self):
        assert keyword_density(SAMPLE) == keyword_density(SAMPLE)


class TestMeasuredNotHardcoded:
    """The original hardcoded silence_duration_sec=0.4, emotion_score=0.85 and
    topic_confidence=0.92 for every chunk and never looked at timings."""

    def _features_for(self, segments):
        units = build_sentence_units(segments)
        chunks = segment_units(
            units, min_duration=8.0, max_duration=90.0, optimal_duration=45.0
        )
        return [extract_features(c, units) for c in chunks], units

    def test_silence_is_measured_from_gaps(self, punctuated_segments):
        features, _ = self._features_for(punctuated_segments)
        # Input has 0.8s gaps between sentences, so silence must be non-zero.
        assert any(f.silence_duration_sec > 0 for f in features)
        assert any(f.longest_pause_sec > 0 for f in features)

    def test_no_silence_when_input_has_no_gaps(self, caption_segments):
        features, _ = self._features_for(caption_segments)
        assert all(f.silence_duration_sec == pytest.approx(0.0, abs=0.01)
                   for f in features)

    def test_values_vary_across_chunks(self, punctuated_segments):
        features, _ = self._features_for(punctuated_segments)
        assert len({f.topic_confidence for f in features}) > 1

    def test_speaking_rate_is_computed(self):
        chunk = SemanticChunk(
            id="c1", start=0.0, end=60.0,
            text=" ".join(["word"] * 150),
            topic_summary="s", boundary_reason="r",
        )
        features = extract_features(chunk, [])
        assert features.speaking_rate_wpm == pytest.approx(150.0, abs=0.5)

    def test_sentiment_is_signed_and_bounded(self):
        positive = SemanticChunk(
            id="p", start=0.0, end=10.0,
            text="This was great, amazing, wonderful success and growth.",
            topic_summary="s", boundary_reason="r",
        )
        negative = SemanticChunk(
            id="n", start=0.0, end=10.0,
            text="This was terrible, awful, a painful failure and a crisis.",
            topic_summary="s", boundary_reason="r",
        )
        pos = extract_features(positive, [])
        neg = extract_features(negative, [])
        assert pos.sentiment_score > 0
        assert neg.sentiment_score < 0
        assert -1.0 <= pos.sentiment_score <= 1.0
        assert -1.0 <= neg.sentiment_score <= 1.0

    def test_question_count(self):
        chunk = SemanticChunk(
            id="q", start=0.0, end=10.0,
            text="Why does this work? And how? Really?",
            topic_summary="s", boundary_reason="r",
        )
        assert extract_features(chunk, []).question_count == 3

    def test_scores_stay_in_range(self, punctuated_segments):
        features, _ = self._features_for(punctuated_segments)
        for f in features:
            assert 0.0 <= f.curiosity_score <= 1.0
            assert 0.0 <= f.strong_statement_score <= 1.0
            assert 0.0 <= f.story_likelihood <= 1.0
            assert 0.0 <= f.emotion_score <= 1.0
            assert 0.0 <= f.topic_confidence <= 1.0
