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


# --------------------------------------------------------------- backchannel
#
# A backchannel is the listener noise that punctuates conversation -- "Mhm.",
# "Absolutely.", "No difference." A clip that opens on one is opening on the
# *previous* speaker's tail, not on its own content. A real run selected clips
# starting "Mhm.", "Absolutely.", "Exactly.", "No difference." and "Yeah,
# yeah, and it takes you outside of your body."
#
# Two questions are asked of the same vocabulary:
#   is_backchannel(text)          -- is this unit *nothing but* acknowledgment?
#                                    Such units are trimmed off a clip's start.
#   starts_with_backchannel(text) -- does it merely *open* with one? Those keep
#                                    their content but score down on hook.

# Acknowledgment proper. A phrase needs at least one of these to be a
# backchannel at all, which is what stops "and the" or "it is" qualifying.
BACKCHANNEL_ACKS = frozenset(["mhm", "mmhmm", "mmhm", "hmm", "mm", "uhhuh", "huh", "yeah", "yep", "yup", "yes", "ya", "yah", "right", "exactly", "absolutely", "definitely", "precisely", "totally", "certainly", "sure", "ok", "okay", "correct", "true", "indeed", "agreed", "understood", "gotcha", "wow", "nice", "cool", "great", "awesome", "amazing", "perfect"])

# Permitted alongside an acknowledgment without making the phrase substantive.
# Deliberately narrow: over-trimming silently deletes real content, which is a
# worse failure than leaving a weak opener in place.
BACKCHANNEL_FILLER = frozenset(["oh", "ah", "well", "and", "but", "so", "no", "not", "now", "then", "just", "really", "very", "quite", "i", "you", "it", "that", "this", "is", "s", "re", "a", "an", "the", "of", "course", "for", "to", "me", "my"])

# Multi-word backchannels whose individual tokens are not acknowledgments, so
# the token test alone would miss them.
BACKCHANNEL_PHRASES = frozenset({
    "no difference", "i see", "got it", "makes sense", "fair enough",
    "good point", "no doubt", "no way", "i know", "i bet", "you bet",
    "of course", "for sure", "thats right", "thats true", "thats fair",
    "i hear you", "say no more", "no kidding", "come on", "you know",
    "i mean", "go on", "and then", "keep going",
})

# "roughly under 5 words" -- the same threshold `first_substantial_sentence`
# already uses to decide a sentence carries real content.
BACKCHANNEL_MAX_WORDS = 4

_PUNCT_RE = re.compile(r"[^\w\s]+")


def normalise_tokens(text: str) -> list[str]:
    """Lowercase word tokens with punctuation stripped.

    Case-insensitive and punctuation-tolerant, so "Mhm.", "MHM", "mhm --" and
    "Mm-hmm!" all reduce to the same thing.
    """
    if not text:
        return []
    return _PUNCT_RE.sub(" ", text.lower()).split()


def is_backchannel(text: str) -> bool:
    """True when a unit is pure acknowledgment and carries no content.

    Short, every token drawn from the backchannel vocabulary, and at least one
    token an acknowledgment proper.
    """
    tokens = normalise_tokens(text)
    if not tokens:
        return False
    if " ".join(tokens) in BACKCHANNEL_PHRASES:
        return True
    if len(tokens) > BACKCHANNEL_MAX_WORDS:
        return False
    if not any(token in BACKCHANNEL_ACKS for token in tokens):
        return False
    return all(
        token in BACKCHANNEL_ACKS or token in BACKCHANNEL_FILLER for token in tokens
    )


def starts_with_backchannel(text: str) -> bool:
    """True when a unit *opens* with acknowledgment, whatever follows.

    "Yeah, yeah, and it takes you outside of your body." keeps its content --
    it is too long and too substantive to trim -- but it is still a poor first
    three seconds, so the hook scorer needs to see it.
    """
    tokens = normalise_tokens(text)
    if not tokens:
        return False
    if tokens[0] in BACKCHANNEL_ACKS:
        return True
    # "oh yeah, ...", "well right, ...": one filler then an acknowledgment.
    return (
        len(tokens) > 1
        and tokens[0] in BACKCHANNEL_FILLER
        and tokens[1] in BACKCHANNEL_ACKS
    )
