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
