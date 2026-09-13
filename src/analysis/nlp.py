"""Local NLP utilities: spaCy entity recognition, VADER sentiment, and emotion classification.

All models and analyzers are lazily loaded and cached. If any dependency or model
is unavailable, the functions degrade gracefully to lightweight heuristics
without failing the pipeline.
"""

from __future__ import annotations

import threading
from typing import Any

from config.settings import settings
from src.utils.logging_config import get_logger

log = get_logger(__name__)

_spacy_lock = threading.Lock()
_spacy_nlp: Any | None = None
_spacy_load_failed: bool = False

_vader_lock = threading.Lock()
_vader_analyzer: Any | None = None
_vader_load_failed: bool = False


def get_spacy_nlp() -> Any | None:
    """Lazy load the spaCy model with fast NER configuration."""
    global _spacy_nlp, _spacy_load_failed
    if _spacy_load_failed:
        return None
    if _spacy_nlp is not None:
        return _spacy_nlp

    with _spacy_lock:
        if _spacy_nlp is not None:
            return _spacy_nlp
        if _spacy_load_failed:
            return None

        try:
            import spacy
            model_name = getattr(settings, "spacy_model", "en_core_web_sm")
            try:
                _spacy_nlp = spacy.load(model_name, disable=["parser"])
            except Exception:
                # Attempt direct download or fallback to basic spacy model
                log.info("Attempting to load spacy model %s...", model_name)
                _spacy_nlp = spacy.load(model_name)
            log.info("Loaded spaCy NLP model: %s", model_name)
            return _spacy_nlp
        except Exception as exc:
            _spacy_load_failed = True
            log.info("spaCy or model not available (%s: %s); using fallback heuristic NER", type(exc).__name__, exc)
            return None


def get_vader_analyzer() -> Any | None:
    """Lazy load the VADER sentiment analyzer."""
    global _vader_analyzer, _vader_load_failed
    if _vader_load_failed:
        return None
    if _vader_analyzer is not None:
        return _vader_analyzer

    with _vader_lock:
        if _vader_analyzer is not None:
            return _vader_analyzer
        if _vader_load_failed:
            return None

        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            _vader_analyzer = SentimentIntensityAnalyzer()
            log.info("Loaded VADER SentimentIntensityAnalyzer")
            return _vader_analyzer
        except Exception as exc:
            _vader_load_failed = True
            log.info("vaderSentiment not available (%s: %s); using cue-based sentiment fallback", type(exc).__name__, exc)
            return None


def analyze_sentiment(text: str) -> float | None:
    """Compute signed sentiment polarity in [-1.0, 1.0] using VADER.

    Returns None if VADER is unavailable, signalling fallback to cue matching.
    """
    analyzer = get_vader_analyzer()
    if analyzer is None:
        return None
    try:
        scores = analyzer.polarity_scores(text)
        return float(scores.get("compound", 0.0))
    except Exception as exc:
        log.warning("VADER polarity scoring failed (%s); using fallback", exc)
        return None


def extract_spacy_entities(text: str, limit: int = 12) -> list[str] | None:
    """Extract named entities using spaCy.

    Captures PERSON, ORG, GPE, MONEY, PRODUCT, EVENT, WORK_OF_ART, PERCENT.
    Returns None if spaCy is unavailable.
    """
    nlp = get_spacy_nlp()
    if nlp is None:
        return None

    try:
        doc = nlp(text)
        seen: set[str] = set()
        entities: list[str] = []
        valid_labels = {
            "PERSON", "ORG", "GPE", "LOC", "PRODUCT", "EVENT",
            "WORK_OF_ART", "MONEY", "PERCENT", "FAC", "NORP"
        }

        for ent in doc.ents:
            cleaned = ent.text.strip()
            # Drop single-char or purely stopword-like entities
            if len(cleaned) < 2 or cleaned.lower() in {"i", "the", "a", "an", "today", "yesterday"}:
                continue
            if ent.label_ in valid_labels and cleaned not in seen:
                seen.add(cleaned)
                entities.append(cleaned)

        return entities[:limit]
    except Exception as exc:
        log.warning("spaCy entity extraction failed (%s); using fallback", exc)
        return None
