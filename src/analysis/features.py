"""Per-chunk linguistic and timing features.

Fixes carried over from the audit of the original node_06:

  * `\\b\\d+%\\b` never matched anything -- `%` followed by a space is not a word
    boundary -- so every percentage was captured as a bare number instead.
  * "Named entities" were any capitalised word, which returned sentence-initial
    words like "Welcome", "Today" and "The".
  * `keyword_density` used `text.count("ai")` with no word boundaries, so one
    mention of "AI" scored 5 by also matching f-ai-l, av-ai-lable, cert-ai-n and
    expl-ai-ned. The vocabulary was also a fixed 8-word list lifted from the
    demo transcript, so it scored 0 on any real episode.
  * `silence_duration_sec`, `emotion_score` and `topic_confidence` were
    hardcoded constants presented as measurements.
"""

from __future__ import annotations

import re

from src.schema.clips import ExtractedFeatures, SemanticChunk, SentenceUnit
from src.utils.logging_config import get_logger

log = get_logger(__name__)

# Percentages: the `%` must not be followed by \b. Also accepts decimals.
PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s?%")
# Money and large quantities.
QUANTITY_RE = re.compile(
    # Longest-first alternation: regex alternation is ordered, so listing "b"
    # before "billion" would truncate "$6.5 billion" to "$6.5 b".
    r"\$\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:trillion|billion|million|bn|tn|k|m|b))?",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
# Runs of capitalised words (proper-noun-ish), captured with position so we can
# drop sentence-initial ones.
CAP_RUN_RE = re.compile(r"\b[A-Z][a-zA-Z'’]*(?:\s+[A-Z][a-zA-Z'’]*)*\b")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")

# Cue families. Matched on whole words, and kept generic rather than tuned to
# one transcript.
CURIOSITY_CUES = frozenset(["why", "how", "secret", "secrets", "truth", "hidden", "mystery", "unknown", "puzzle", "surprising", "counterintuitive", "nobody", "everyone", "myth", "misconception", "reason", "actually", "wrong", "believe", "assume", "realise", "realize", "imagine", "suppose", "wonder", "question", "questions", "weird", "strange", "unexpected"])
STRONG_CUES = frozenset(["never", "always", "must", "every", "none", "nobody", "everyone", "impossible", "guaranteed", "absolutely", "critical", "essential", "devastating", "unprecedented", "terrifying", "shocking", "huge", "massive", "worst", "best", "only", "single", "biggest", "hardest", "fastest", "proof", "proven"])
STORY_CUES = frozenset(["story", "remember", "happened", "once", "when", "started", "began", "first", "time", "day", "night", "year", "example", "case", "customer", "client", "friend", "told", "said", "asked", "realised", "realized", "learned", "mistake", "failed", "failure", "lesson", "journey", "built", "discovered"])
POSITIVE_CUES = frozenset(["great", "good", "best", "amazing", "incredible", "wonderful", "fantastic", "brilliant", "love", "loved", "success", "successful", "win", "won", "growth", "grew", "improve", "improved", "better", "easy", "simple", "remarkable", "fascinating", "excited", "exciting", "happy", "proud"])
NEGATIVE_CUES = frozenset(["bad", "worst", "terrible", "awful", "fail", "failed", "failure", "hard", "difficult", "painful", "pain", "mistake", "wrong", "lose", "lost", "loss", "decline", "declined", "crisis", "catastrophe", "danger", "dangerous", "risk", "scared", "afraid", "fear", "angry", "frustrated", "broken", "hate"])

# Words too generic to be useful as topic keywords.
KEYWORD_STOPLIST = frozenset(["about", "actually", "after", "again", "against", "all", "also", "always", "and", "any", "are", "because", "been", "before", "being", "between", "both", "but", "came", "come", "could", "did", "does", "doing", "done", "down", "each", "even", "every", "first", "from", "gets", "getting", "give", "given", "going", "gone", "got", "had", "has", "have", "here", "how", "into", "just", "kind", "know", "like", "little", "look", "looking", "made", "make", "making", "many", "maybe", "mean", "means", "might", "more", "most", "much", "need", "never", "new", "next", "not", "now", "only", "other", "our", "out", "over", "own", "really", "right", "said", "same", "say", "says", "see", "seen", "she", "should", "since", "some", "something", "still", "such", "take", "taken", "than", "that", "the", "their", "them", "then", "there", "these", "they", "thing", "things", "think", "this", "those", "though", "thought", "through", "time", "too", "under", "until", "very", "want", "wanted", "was", "way", "well", "went", "were", "what", "when", "where", "which", "while", "who", "why", "will", "with", "without", "would", "yeah", "year", "years", "you", "your", "really", "quite", "sort", "lot", "bit", "going", "gonna", "okay", "right", "kinda", "basically", "literally"])


def _words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def extract_named_entities(text: str, limit: int = 8) -> list[str]:
    """Heuristic proper-noun and quantity extractor.

    Not a trained NER model, and named accordingly in the docs. Capitalised
    runs that begin a sentence are dropped unless they recur mid-sentence,
    which is what removes "Welcome", "Today" and "The".
    """
    sentences = SENTENCE_SPLIT_RE.split(text.strip())
    mid_sentence: dict[str, int] = {}
    sentence_initial: set[str] = set()

    for sentence in sentences:
        stripped = sentence.strip()
        if not stripped:
            continue
        for match in CAP_RUN_RE.finditer(stripped):
            token = match.group(0).strip()
            if not token or token.lower() in {"i"}:
                continue
            if match.start() == 0:
                sentence_initial.add(token)
            else:
                mid_sentence[token] = mid_sentence.get(token, 0) + 1

    entities = list(mid_sentence)
    # A sentence-initial capital is only an entity if it also appears
    # mid-sentence somewhere (so "OpenAI" survives, "Today" does not).
    entities.extend(t for t in sentence_initial if t in mid_sentence)

    quantities = PERCENT_RE.findall(text) + QUANTITY_RE.findall(text)

    # Deterministic order: by frequency then alphabetically. Never list(set()).
    ranked = sorted(
        dict.fromkeys(entities),
        key=lambda t: (-mid_sentence.get(t, 0), t),
    )
    out = list(dict.fromkeys([*ranked, *quantities]))
    return out[:limit]


def keyword_density(text: str, limit: int = 8) -> dict[str, int]:
    """Most frequent content words, counted on whole-word boundaries.

    Vocabulary is derived from the text itself, so it works on any episode.
    """
    counts: dict[str, int] = {}
    for raw in _words(text.lower()):
        word = raw.strip("'’-")
        if len(word) < 4 or word in KEYWORD_STOPLIST:
            continue
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {w: c for w, c in ranked[:limit] if c > 1} or {
        w: c for w, c in ranked[:limit]
    }


def _cue_hits(words: set[str], cues: frozenset[str]) -> int:
    return len(words & cues)


def extract_features(
    chunk: SemanticChunk,
    units: list[SentenceUnit],
) -> ExtractedFeatures:
    """Compute features for one chunk from its text and its units' timings."""
    text = chunk.text
    lower_words = [w.lower().strip("'’-") for w in _words(text)]
    word_set = set(lower_words)
    word_count = len(lower_words)
    duration = max(chunk.duration, 0.01)

    speaking_rate = (word_count / duration) * 60.0
    question_count = text.count("?")

    curiosity_hits = _cue_hits(word_set, CURIOSITY_CUES)
    strong_hits = _cue_hits(word_set, STRONG_CUES)
    story_hits = _cue_hits(word_set, STORY_CUES)
    pos_hits = _cue_hits(word_set, POSITIVE_CUES)
    neg_hits = _cue_hits(word_set, NEGATIVE_CUES)

    # Saturating maps so a wall of cue words cannot exceed 1.0.
    curiosity = min(1.0, 0.15 + curiosity_hits * 0.14 + (0.2 if question_count else 0.0))
    strong = min(1.0, 0.15 + strong_hits * 0.16)
    story = min(1.0, 0.15 + story_hits * 0.13)

    # Signed sentiment in [-1, 1], normalised by total cue count so a long
    # chunk is not automatically more extreme than a short one.
    total_cues = pos_hits + neg_hits
    sentiment = (pos_hits - neg_hits) / (total_cues + 1.0)

    if pos_hits > neg_hits and pos_hits > 0:
        emotion = "positive/enthusiastic"
    elif neg_hits > pos_hits and neg_hits > 0:
        emotion = "negative/cautionary"
    elif story_hits >= 2:
        emotion = "narrative"
    elif question_count > 0:
        emotion = "inquisitive"
    else:
        emotion = "neutral/analytical"

    # Emotional intensity: cue density per 100 words, saturating.
    emotion_score = min(1.0, total_cues / max(word_count / 100.0, 1.0) / 6.0)

    # Real pause measurement from the unit gaps inside this chunk.
    chunk_units = [
        u for u in units if u.start >= chunk.start - 1e-6 and u.end <= chunk.end + 1e-6
    ]
    internal_gaps = [u.gap_before for u in chunk_units[1:]] if len(chunk_units) > 1 else []
    silence_total = sum(internal_gaps)
    longest_pause = max(internal_gaps) if internal_gaps else 0.0

    # Confidence in the topic label: proxied by how much of the chunk is
    # actually speech rather than silence, and by having enough words to judge.
    speech_ratio = 1.0 - min(1.0, silence_total / duration)
    length_confidence = min(1.0, word_count / 60.0)
    topic_confidence = round(max(0.0, min(1.0, 0.5 * speech_ratio + 0.5 * length_confidence)), 3)

    return ExtractedFeatures(
        chunk_id=chunk.id,
        emotion_label=emotion,
        emotion_score=round(emotion_score, 3),
        sentiment_score=round(sentiment, 3),
        named_entities=extract_named_entities(text),
        speaking_rate_wpm=round(speaking_rate, 1),
        question_count=question_count,
        curiosity_score=round(curiosity, 3),
        strong_statement_score=round(strong, 3),
        silence_duration_sec=round(silence_total, 3),
        longest_pause_sec=round(longest_pause, 3),
        keyword_density=keyword_density(text),
        topic_confidence=topic_confidence,
        story_likelihood=round(story, 3),
    )


def extract_all(
    chunks: list[SemanticChunk], units: list[SentenceUnit]
) -> dict[str, ExtractedFeatures]:
    features = {c.id: extract_features(c, units) for c in chunks}
    log.info("Extracted features for %d chunks", len(features))
    return features
