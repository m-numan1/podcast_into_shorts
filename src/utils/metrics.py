"""Timestamp formatting and interval geometry."""

from __future__ import annotations


def seconds_to_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS, or HH:MM:SS past one hour.

    Negative input is clamped to zero rather than producing "-1:-30"-style
    output, which the original produced silently.
    """
    total = int(round(max(0.0, seconds)))
    hrs, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def timestamp_to_seconds(stamp: str) -> float:
    """Parse "MM:SS" or "HH:MM:SS" back into seconds."""
    parts = stamp.strip().split(":")
    if not 2 <= len(parts) <= 3:
        raise ValueError(f"Expected MM:SS or HH:MM:SS, got {stamp!r}")
    try:
        values = [float(p) for p in parts]
    except ValueError as exc:
        raise ValueError(f"Non-numeric component in timestamp {stamp!r}") from exc
    if len(parts) == 2:
        mins, secs = values
        return mins * 60 + secs
    hrs, mins, secs = values
    return hrs * 3600 + mins * 60 + secs


def overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Length of the intersection of two intervals; 0 when disjoint."""
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def overlap_ratio(
    a_start: float, a_end: float, b_start: float, b_end: float
) -> float:
    """Intersection over the *shorter* interval, in [0, 1].

    This is the symmetric measure the deduplicator needs. The original compared
    the overlap against half of the *candidate's own* duration only, so a long
    clip that entirely contained an already-published short clip was kept:
    overlap 30s vs threshold 0.5 x 90s = 45s did not trip, and the same content
    shipped twice. Using the shorter interval makes containment always score 1.0.
    """
    inter = overlap_seconds(a_start, a_end, b_start, b_end)
    if inter <= 0:
        return 0.0
    shorter = min(a_end - a_start, b_end - b_start)
    if shorter <= 0:
        return 0.0
    return min(1.0, inter / shorter)


def intersection_over_union(
    a_start: float, a_end: float, b_start: float, b_end: float
) -> float:
    """Standard IoU, for reporting and diversity checks."""
    inter = overlap_seconds(a_start, a_end, b_start, b_end)
    if inter <= 0:
        return 0.0
    union = (a_end - a_start) + (b_end - b_start) - inter
    return inter / union if union > 0 else 0.0


def format_duration(seconds: float) -> str:
    """Human-friendly duration, e.g. "1m 12s"."""
    total = max(0.0, seconds)
    mins, secs = divmod(total, 60)
    if mins >= 1:
        return f"{int(mins)}m {secs:04.1f}s"
    return f"{secs:.1f}s"
