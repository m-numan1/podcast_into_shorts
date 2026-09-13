"""Timestamp parsing and normalization utilities.

Handles numeric seconds, 'MM:SS', 'HH:MM:SS', and range expressions ('MM:SS to MM:SS').
"""

from __future__ import annotations

import re
from typing import Any

from src.utils.logging_config import get_logger

log = get_logger(__name__)


def parse_timestamp(val: Any) -> float:
    """Parse timestamp value (float, int, or 'MM:SS' / 'HH:MM:SS' string) to seconds."""
    if isinstance(val, (int, float)):
        return max(0.0, float(val))
    if not isinstance(val, str):
        raise ValueError(f"Invalid timestamp format: {val!r}")

    text = val.strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        log.debug("Timestamp %r is not a raw float, trying HH:MM:SS format", val)

    parts = text.split(":")
    if len(parts) == 2:
        m, s = float(parts[0]), float(parts[1])
        return max(0.0, m * 60 + s)
    elif len(parts) == 3:
        h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
        return max(0.0, h * 3600 + m * 60 + s)

    raise ValueError(f"Unrecognized timestamp format: {val!r}")


def parse_timestamp_range(val: str) -> tuple[float, float]:
    """Parse range string like '1:00 to 1:05' or '01:00-01:05' into (start, end)."""
    text = val.strip()
    match = re.search(r"(.+?)\s*(?:to|->|-)\s*(.+)", text, re.IGNORECASE)
    if match:
        start = parse_timestamp(match.group(1))
        end = parse_timestamp(match.group(2))
        return start, end
    raise ValueError(f"Cannot parse timestamp range: {val!r}")


def extract_clip_timestamps(clip_data: dict[str, Any]) -> tuple[float, float, str, str]:
    """Extract (start_sec, end_sec, title, clip_id) from clip dictionary."""
    clip_id = str(clip_data.get("id") or "clip_001")
    title = str(clip_data.get("title") or clip_id)

    # Check numeric seconds fields first
    if "adjusted_start_seconds" in clip_data and "adjusted_end_seconds" in clip_data:
        start = float(clip_data["adjusted_start_seconds"])
        end = float(clip_data["adjusted_end_seconds"])
        return start, end, title, clip_id

    if "start_seconds" in clip_data and "end_seconds" in clip_data:
        start = float(clip_data["start_seconds"])
        end = float(clip_data["end_seconds"])
        return start, end, title, clip_id

    if "start_time" in clip_data and "end_time" in clip_data:
        start = parse_timestamp(clip_data["start_time"])
        end = parse_timestamp(clip_data["end_time"])
        return start, end, title, clip_id

    # Check formatted string fields
    if "start_timestamp" in clip_data and "end_timestamp" in clip_data:
        start = parse_timestamp(clip_data["start_timestamp"])
        end = parse_timestamp(clip_data["end_timestamp"])
        return start, end, title, clip_id

    if "start" in clip_data and "end" in clip_data:
        start = parse_timestamp(clip_data["start"])
        end = parse_timestamp(clip_data["end"])
        return start, end, title, clip_id

    # Check if there is a single timestamp string range e.g. "timestamp": "1:00 to 1:05"
    if "timestamp" in clip_data:
        start, end = parse_timestamp_range(str(clip_data["timestamp"]))
        return start, end, title, clip_id

    raise ValueError(f"Clip object missing start/end timestamp fields: {clip_data}")
