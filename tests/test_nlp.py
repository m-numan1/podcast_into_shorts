"""Tests for local free offline NLP capabilities:
1. FastEmbed semantic embeddings and topic boundary detection
2. spaCy Named Entity Recognition
3. VADER sentiment and emotion classification
"""

from __future__ import annotations

import numpy as np
import pytest

from src.analysis.features import extract_features, extract_named_entities
from src.analysis.nlp import analyze_sentiment, extract_spacy_entities, get_vader_analyzer
from src.providers.embeddings import FastEmbedEmbedder, build_embedder, cosine_similarity
from src.schema.clips import SemanticChunk, SentenceUnit


class TestFastEmbed:
    def test_fastembed_embeds_and_normalizes(self):
        embedder = FastEmbedEmbedder(dim=384)
        texts = [
            "Electric vehicles and autonomous driving technology",
            "Self-driving cars and battery powered automobiles",
            "How to bake a chocolate fudge cake for a birthday party",
        ]
        vectors = embedder.embed(texts)

        assert vectors.shape == (3, 384)
        # Check normalization (norm == 1.0)
        norms = np.linalg.norm(vectors, axis=1)
        np.testing.assert_allclose(norms, [1.0, 1.0, 1.0], atol=1e-4)

        # Semantic test: vehicles and cars must have much higher similarity than baking a cake
        sim_related = cosine_similarity(vectors[0], vectors[1])
        sim_unrelated = cosine_similarity(vectors[0], vectors[2])

        assert sim_related > sim_unrelated
        assert sim_related > 0.6
        assert sim_unrelated < 0.4

    def test_build_embedder_fastembed(self):
        embedder = build_embedder("fastembed", dim=384)
        assert isinstance(embedder, FastEmbedEmbedder)
        vec = embedder.embed_one("Test sentence")
        assert len(vec) == 384


class TestSentimentAndEmotion:
    def test_vader_handles_negation_and_emphasis(self):
        analyzer = get_vader_analyzer()
        if analyzer is None:
            pytest.skip("vaderSentiment is not installed")

        pos_text = "This breakthrough strategy is absolutely brilliant and amazing!"
        neg_text = "The launch was a complete disaster and everything failed terribly."
        negation_text = "The product is not bad at all, actually quite decent."

        pos_score = analyze_sentiment(pos_text)
        neg_score = analyze_sentiment(neg_text)
        negation_score = analyze_sentiment(negation_text)

        assert pos_score is not None and pos_score > 0.5
        assert neg_score is not None and neg_score < -0.5
        # "not bad" must not be classified as deeply negative
        assert negation_score is not None and negation_score >= 0.0

    def test_extract_features_with_nlp(self):
        chunk = SemanticChunk(
            id="chunk_01",
            start=0.0,
            end=15.0,
            text="Did you know that OpenAI invested $10 billion into AI infrastructure? It completely shocked the industry!",
            unit_ids=["u1"],
            topic_summary="OpenAI AI investment",
            boundary_reason="sentence end",
        )
        unit = SentenceUnit(
            id=1,
            start=0.0,
            end=15.0,
            text="Did you know that OpenAI invested $10 billion into AI infrastructure? It completely shocked the industry!",
            segment_ids=[1],
            ends_sentence=True,
        )

        features = extract_features(chunk, [unit])

        assert -1.0 <= features.sentiment_score <= 1.0
        assert 0.0 <= features.emotion_score <= 1.0
        assert features.emotion_label in {
            "positive/enthusiastic",
            "negative/cautionary",
            "narrative",
            "inquisitive",
            "neutral/analytical",
        }
        assert features.question_count == 1
        assert any("billion" in ent or "OpenAI" in ent for ent in features.named_entities)


class TestEntityExtraction:
    def test_entity_extraction_extracts_entities_or_fallback(self):
        text = "Sundar Pichai announced that Google invested $5 billion in London yesterday."
        entities = extract_named_entities(text)
        assert len(entities) > 0
        # Should catch Google or Sundar Pichai or $5 billion
        assert any(e in {"Google", "Sundar Pichai", "London", "$5 billion"} or "billion" in e for e in entities)
