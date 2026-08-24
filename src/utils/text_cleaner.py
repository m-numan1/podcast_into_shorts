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
#
# `er` deliberately has no `+`. The old `er+` also matched "err", so
# "to err is human" came out as "to is human". Filler spelled with repeated
# r's is rare enough that losing it is a far better trade than deleting a real
# verb; `\ber\b` cannot match inside "err" because there is no word boundary
# between the two r's.
FILLER_WORD_RE = re.compile(
    r"\b(?:um+|uh+|er|ah+|hmm+)\b[\s,\.\-—]*",
    re.IGNORECASE,
)


def clean_transcript_text(text: str, *, sentence_case: bool = True) -> str:
    """Clean filler words and caption tags from a transcript string.

    `sentence_case` capitalises the first character. That is right for a
    sentence and wrong for a single word: the Whisper path cleans each word
    separately when building word timings, so every burned caption word came
    out capitalised -- "The Quick Brown Fox" -- and brand casing was destroyed
    ("iPhone" -> "IPhone", "eBay" -> "EBay"). Per-word callers pass False.
    """
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
    if sentence_case and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]

    return cleaned
