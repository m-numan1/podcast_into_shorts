"""Transcript text normalization and cleaning.

Removes spoken filler words ('um', 'uh', 'er', 'ah') and caption noise
like '[Music]', '[Laughter]', '(applause)', etc., to prepare transcript
text for high-quality short video production.
"""

import re

# Regex for bracketed audio/subtitle tags like [Music], (Laughter), [Applause]
CAPTION_TAG_RE = re.compile(
    r"[\(\[\{]\s*(?:"
    r"music|laughter|applause|cheering|coughing|sighs?|chuckle|gasp|snort|"
    r"screaming|groan|sigh|giggles|snicker|audio|silence|sound|background|singing"
    r")\s*[\)\]\}]",
    re.IGNORECASE,
)

# Generic bracket remover for remaining caption markers like [Music playing]
GENERIC_BRACKET_CAPTION_RE = re.compile(r"\[[A-Za-z\s_-]{2,30}\]")

# Filler words: um, uh, er, ah, hmm (with optional punctuation like um, uh..., um--)
FILLER_WORD_RE = re.compile(
    r"\b(?:um+|uh+|er+|ah+|hmm+)\b[\s,\.\-—]*",
    re.IGNORECASE,
)


def clean_transcript_text(text: str) -> str:
    """Clean filler words and caption tags from a transcript string."""
    if not text:
        return ""

    # 1. Strip sound and music tags like [Music], (Laughter)
    cleaned = CAPTION_TAG_RE.sub(" ", text)
    cleaned = GENERIC_BRACKET_CAPTION_RE.sub(" ", cleaned)

    # 2. Strip filler words like "um", "uh"
    cleaned = FILLER_WORD_RE.sub(" ", cleaned)

    # 3. Collapse multiple spaces and fix leading/trailing punctuation whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Clean up orphaned leading punctuation (e.g. if filler word at start had a comma)
    cleaned = re.sub(r"^[,\.\-—:]+\s*", "", cleaned).strip()

    if not cleaned:
        return ""

    # Ensure sentence starts with a capital letter if it began with lowercase
    if cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]

    return cleaned
