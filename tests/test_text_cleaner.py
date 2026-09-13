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


class TestSentenceCaseFlag:
    """Capitalising the first character is right for a sentence, wrong for a
    word. The Whisper path cleans each word separately when building word
    timings, so every burned caption word came out capitalised."""

    def test_default_still_capitalises_a_sentence(self):
        assert clean_transcript_text("hello world") == "Hello world"

    def test_per_word_preserves_lowercase(self):
        for word in ("the", "quick", "brown", "fox"):
            assert clean_transcript_text(word, sentence_case=False) == word

    def test_per_word_preserves_brand_casing(self):
        for brand in ("iPhone", "eBay", "iOS", "macOS"):
            assert clean_transcript_text(brand, sentence_case=False) == brand

    def test_a_whole_caption_cue_reads_naturally(self):
        """The visible symptom: 'The Quick Brown Fox' instead of 'the quick...'."""
        spoken = ["the", "quick", "brown", "fox"]
        cleaned = [clean_transcript_text(w, sentence_case=False) for w in spoken]
        assert " ".join(cleaned) == "the quick brown fox"

    def test_per_word_still_strips_filler_and_tags(self):
        assert clean_transcript_text("uh", sentence_case=False) == ""
        assert clean_transcript_text("[Music]", sentence_case=False) == ""


class TestErrIsNotFiller:
    """`er+` also matched 'err', so 'to err is human' became 'to is human'."""

    def test_err_survives_as_a_word(self):
        assert clean_transcript_text("To err is human") == "To err is human"

    def test_err_survives_mid_sentence(self):
        assert "err" in clean_transcript_text("We all err sometimes")

    def test_bare_er_is_still_filler(self):
        assert clean_transcript_text("er, well, maybe").lower().startswith("well")

    def test_other_fillers_unaffected(self):
        for filler in ("um", "umm", "uh", "uhh", "ah", "ahh", "hmm"):
            assert clean_transcript_text(filler) == "", filler
