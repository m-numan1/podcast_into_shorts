"""Unit tests for ClipTrimmer and timestamp parsing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.providers.trimmer import (
    ClipTrimmer,
    extract_clip_timestamps,
    parse_timestamp,
    parse_timestamp_range,
)


class TestParseTimestamp:
    @pytest.mark.parametrize("input_val,expected", [
        (0.0, 0.0),
        (45.5, 45.5),
        (60, 60.0),
        ("0.0", 0.0),
        ("12.5", 12.5),
        ("1:00", 60.0),
        ("01:30", 90.0),
        ("10:05", 605.0),
        ("1:02:30", 3750.0),
        ("01:00:00", 3600.0),
    ])
    def test_valid_timestamps(self, input_val, expected):
        assert parse_timestamp(input_val) == pytest.approx(expected)

    def test_invalid_timestamps(self):
        with pytest.raises(ValueError):
            parse_timestamp("invalid_time")
        with pytest.raises(ValueError):
            parse_timestamp(None)


class TestParseTimestampRange:
    @pytest.mark.parametrize("input_str,expected_start,expected_end", [
        ("1:00 to 1:30", 60.0, 90.0),
        ("01:00 - 01:15", 60.0, 75.0),
        ("00:10 -> 00:40", 10.0, 40.0),
    ])
    def test_valid_ranges(self, input_str, expected_start, expected_end):
        start, end = parse_timestamp_range(input_str)
        assert start == pytest.approx(expected_start)
        assert end == pytest.approx(expected_end)

    def test_invalid_range(self):
        with pytest.raises(ValueError):
            parse_timestamp_range("just a single timestamp 1:00")


class TestExtractClipTimestamps:
    def test_adjusted_seconds(self):
        data = {
            "id": "clip_1",
            "title": "Test",
            "adjusted_start_seconds": 10.0,
            "adjusted_end_seconds": 25.0,
        }
        start, end, title, clip_id = extract_clip_timestamps(data)
        assert (start, end, title, clip_id) == (10.0, 25.0, "Test", "clip_1")

    def test_start_end_seconds(self):
        data = {
            "id": "clip_2",
            "title": "Title 2",
            "start_seconds": 60.0,
            "end_seconds": 120.0,
        }
        start, end, title, clip_id = extract_clip_timestamps(data)
        assert (start, end, title, clip_id) == (60.0, 120.0, "Title 2", "clip_2")

    def test_string_timestamps(self):
        data = {
            "id": "clip_3",
            "start_timestamp": "01:00",
            "end_timestamp": "01:30",
        }
        start, end, title, clip_id = extract_clip_timestamps(data)
        assert (start, end, title, clip_id) == (60.0, 90.0, "clip_3", "clip_3")

    def test_timestamp_range(self):
        data = {
            "id": "clip_4",
            "timestamp": "1:00 to 1:05",
        }
        start, end, title, clip_id = extract_clip_timestamps(data)
        assert (start, end, title, clip_id) == (60.0, 65.0, "clip_4", "clip_4")


class TestClipTrimmer:
    def test_init_with_aspect_ratio_and_hook_banner(self, tmp_path):
        trimmer = ClipTrimmer(output_dir=tmp_path, aspect_ratio="9:16", enable_hook_banner=False)
        assert trimmer.aspect_ratio == "9:16"
        assert trimmer.enable_hook_banner is False

    @patch("src.providers.trimmer.ClipTrimmer.trim_fast_copy")
    def test_trim_all_from_json_dict(self, mock_fast_copy, tmp_path):
        trimmer = ClipTrimmer(output_dir=tmp_path)
        media_path = tmp_path / "test.mp4"
        media_path.write_bytes(b"dummy")

        def fake_copy(media, start, end, out_path):
            out_path.write_bytes(b"clipped")
            return out_path

        mock_fast_copy.side_effect = fake_copy

        json_data = {
            "clips": [
                {"id": "c1", "title": "Short 1", "start": "0:00", "end": "0:10"},
                {"id": "c2", "title": "Short 2", "start": "0:15", "end": "0:25"},
            ]
        }

        results = trimmer.trim_all_from_json(media_path, json_data, fast_mode=True)
        assert len(results) == 2
        assert results[0]["rendered_file_path"].endswith("c1_fast.mp4")
        assert results[1]["rendered_file_path"].endswith("c2_fast.mp4")
        assert mock_fast_copy.call_count == 2

    @patch("src.providers.trimmer.ClipTrimmer.trim_fast_copy")
    def test_trim_all_from_json_file(self, mock_fast_copy, tmp_path):
        trimmer = ClipTrimmer(output_dir=tmp_path)
        media_path = tmp_path / "test.mp4"
        media_path.write_bytes(b"dummy")

        def fake_copy(media, start, end, out_path):
            out_path.write_bytes(b"clipped")
            return out_path

        mock_fast_copy.side_effect = fake_copy

        json_path = tmp_path / "final_clips.json"
        json_path.write_text(json.dumps([
            {"id": "clip_a", "start_seconds": 5.0, "end_seconds": 15.0}
        ]), encoding="utf-8")

        results = trimmer.trim_all_from_json(media_path, json_path, fast_mode=True)
        assert len(results) == 1
        assert results[0]["id"] == "clip_a"
        assert "rendered_file_path" in results[0]

    @patch("src.providers.downloader.MediaDownloaderProvider.download")
    def test_resolve_media_path_url(self, mock_download, tmp_path):
        from src.providers.downloader import MediaInfo
        dummy_file = tmp_path / "downloaded.mp4"
        dummy_file.write_bytes(b"downloaded_content")
        mock_download.return_value = MediaInfo(
            title="Test",
            file_path=str(dummy_file),
            duration=100.0,
            media_source="youtube_download",
            has_video=True,
        )
        trimmer = ClipTrimmer(output_dir=tmp_path)
        resolved = trimmer._resolve_media_path("https://youtu.be/uGAmyldSlhE")
        assert resolved == dummy_file.resolve()
        mock_download.assert_called_once_with("https://youtu.be/uGAmyldSlhE")

    @patch("src.providers.trimmer.ClipTrimmer.trim_fast_copy")
    @patch("src.providers.downloader.MediaDownloaderProvider.download")
    def test_trim_with_youtube_url(self, mock_download, mock_fast_copy, tmp_path):
        from src.providers.downloader import MediaInfo
        dummy_file = tmp_path / "uGAmyldSlhE.mp4"
        dummy_file.write_bytes(b"video_bytes")
        mock_download.return_value = MediaInfo(
            title="Video Title",
            file_path=str(dummy_file),
            duration=600.0,
            media_source="youtube_download",
            has_video=True,
        )

        def fake_copy(media, start, end, out_path):
            out_path.write_bytes(b"clip")
            return out_path

        mock_fast_copy.side_effect = fake_copy

        trimmer = ClipTrimmer(output_dir=tmp_path)
        clips_data = [{"id": "c1", "start": "0:10", "end": "0:20"}]

        results = trimmer.trim_all_from_json("https://youtu.be/uGAmyldSlhE?si=CwPDdH6srS7feFBg", clips_data)
        assert len(results) == 1
        assert "rendered_file_path" in results[0]
        assert not results[0].get("error")
