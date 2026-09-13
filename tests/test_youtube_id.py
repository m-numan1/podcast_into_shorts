"""B4: YouTube id extraction must be host-anchored.

The original regex `(?:v=|/)([0-9A-Za-z_-]{11})` matched any 11-character path
segment, so ordinary local paths produced a "video id" and triggered a pointless
caption API call for garbage.
"""

from __future__ import annotations

import pytest

from src.providers.downloader import is_url
from src.providers.transcriber import extract_youtube_id

VALID = [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("http://youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://music.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/watch?list=PL123&v=dQw4w9WgXcQ&t=42", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?t=30", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
]

# Every one of these produced a false-positive "video id" in the original.
NOT_YOUTUBE = [
    "C:/cache/my_podcast_audio.wav",
    "C:\\cache\\my_podcast_audio.wav",
    "/home/user/recordings/episode_042.mp3",
    "./relative/interview_ep7.mp4",
    "cache/sample_podcast.mp3",
    "https://example.com/media/interview_ep7.mp4",
    "https://vimeo.com/channels/staffpicks/123456789",
    "https://notyoutube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
    "",
    "just some text",
    "ftp://youtube.com/watch?v=dQw4w9WgXcQ",
]


@pytest.mark.parametrize("url,expected", VALID)
def test_extracts_real_youtube_ids(url, expected):
    assert extract_youtube_id(url) == expected


@pytest.mark.parametrize("source", NOT_YOUTUBE)
def test_never_matches_non_youtube_sources(source):
    assert extract_youtube_id(source) == ""


def test_rejects_wrong_length_ids():
    assert extract_youtube_id("https://youtu.be/tooshort") == ""
    assert extract_youtube_id("https://youtu.be/waaaaaaaaytoolongforanid") == ""


def test_specific_paths_that_previously_yielded_fake_ids():
    """Documents the exact old behaviour these inputs used to trigger."""
    assert extract_youtube_id("/home/user/recordings/episode_042.mp3") == ""
    assert extract_youtube_id("C:/cache/my_podcast_audio.wav") == ""
    assert extract_youtube_id("https://example.com/media/interview_ep7.mp4") == ""


class TestIsUrl:
    """`source.startswith("http")` also matched paths and 'httpfoo'."""

    @pytest.mark.parametrize("value", [
        "https://youtube.com/watch?v=abc", "http://example.com/a.mp3",
    ])
    def test_accepts_real_urls(self, value):
        assert is_url(value)

    @pytest.mark.parametrize("value", [
        "httpfoo", "http", "https", "/tmp/http/file.mp3",
        "C:/http_recordings/a.wav", "", "ftp://example.com/a.mp3",
        "https://",  # scheme but no host
    ])
    def test_rejects_non_urls(self, value):
        assert not is_url(value)


def test_fetch_captions_transliterates_hi_for_ur_and_rejects_other(monkeypatch):
    """When target_lang is 'ur', accept 'hi' for transliteration; for 'es', reject it."""
    from config.settings import settings
    from src.errors import TranscriptionError
    from src.providers.transcriber import TranscriberProvider

    class MockTranscript:
        language = "Hindi"
        language_code = "hi"
        is_generated = True
        def fetch(self):
            return [{"text": "नमस्ते", "start": 0.0, "duration": 2.0}]

    class MockTranscriptList:
        def find_transcript(self, preferred_langs):
            if "ur" in preferred_langs or "es" in preferred_langs:
                raise Exception("Not found")
            if "hi" in preferred_langs:
                return MockTranscript()
            raise Exception("Not found")

    class MockApi:
        @classmethod
        def list(cls, video_id):
            return MockTranscriptList()

    # For Spanish, Hindi track must be rejected
    monkeypatch.setattr(settings, "transcript_language", "es")
    with pytest.raises(TranscriptionError):
        TranscriberProvider._fetch_captions(MockApi, "dQw4w9WgXcQ")

    # For Urdu, Hindi track is accepted for transliteration
    monkeypatch.setattr(settings, "transcript_language", "ur")
    captions = TranscriberProvider._fetch_captions(MockApi, "dQw4w9WgXcQ")
    assert len(captions) == 1
    assert captions[0]["text"] == "नमस्ते"


def test_from_youtube_captions_transliterates_devanagari_when_target_is_ur(monkeypatch):
    from config.settings import settings
    from src.providers.transcriber import TranscriberProvider

    monkeypatch.setattr(settings, "transcript_language", "ur")
    provider = TranscriberProvider()

    # Mock _fetch_captions to return Devanagari Hindi text
    monkeypatch.setattr(
        provider,
        "_fetch_captions",
        lambda api, vid: [{"text": "सामना करना पड़ेगा?", "start": 0.0, "duration": 2.5}],
    )

    segments = provider._from_youtube_captions("dQw4w9WgXcQ")
    assert len(segments) == 1
    # Check that Urdu text was produced instead of Devanagari
    assert "सामना" not in segments[0].text
    assert "سامنا" in segments[0].text
    assert "پڑے گا" in segments[0].text


def test_from_youtube_captions_clamps_rolling_durations(monkeypatch):
    """YouTube captions have rolling multi-line durations that overlap. They must be clamped."""
    from config.settings import settings
    from src.providers.transcriber import TranscriberProvider

    monkeypatch.setattr(settings, "transcript_language", "")
    provider = TranscriberProvider()

    # Two segments where segment 0 duration (3.5s) extends past segment 1 start (2.0s)
    raw = [
        {"text": "we have more access", "start": 0.0, "duration": 3.5},
        {"text": "to knowledge than any", "start": 2.0, "duration": 3.0},
    ]
    monkeypatch.setattr(provider, "_fetch_captions", lambda api, vid: raw)

    segments = provider._from_youtube_captions("dQw4w9WgXcQ")
    assert len(segments) == 2
    # Segment 0 end must be clamped to 2.0 (start of segment 1)
    assert segments[0].end == pytest.approx(2.0, abs=0.01)
    assert segments[1].start == pytest.approx(2.0, abs=0.01)
    # Words in segment 0 must not exceed 2.0
    for w in segments[0].words:
        assert w.end <= 2.0 + 1e-4

