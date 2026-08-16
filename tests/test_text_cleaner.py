"""Unit tests for transcript text cleaner utility."""

import pytest
from src.utils.text_cleaner import clean_transcript_text


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("[Music] Hello world", "Hello world"),
        ("[Laughter] That was funny (applause)", "That was funny"),
        ("Um, so basically, uh, we went there.", "So basically, we went there."),
        ("Ah... [music] this is great.", "This is great."),
        ("[Music] [coughing] Um, hello!", "Hello!"),
        ("", ""),
        (None, ""),
        ("Just a normal sentence.", "Just a normal sentence."),
    ],
)
def test_clean_transcript_text(raw, expected):
    assert clean_transcript_text(raw) == expected
