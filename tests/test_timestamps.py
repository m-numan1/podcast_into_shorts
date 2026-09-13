"""Unit tests for timestamp parsing and clip timestamp extraction."""

from __future__ import annotations

import pytest

from src.utils.timestamps import (
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

    def test_missing_timestamps_raises(self):
        with pytest.raises(ValueError, match="missing start/end timestamp"):
            extract_clip_timestamps({"id": "clip_bad"})
