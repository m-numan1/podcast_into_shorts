"""Timestamp formatting and interval geometry, including the B2 fix."""

from __future__ import annotations

import pytest

from src.utils.metrics import (
    format_duration,
    intersection_over_union,
    overlap_ratio,
    overlap_seconds,
    seconds_to_timestamp,
    timestamp_to_seconds,
)


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "00:00"),
        (5.4, "00:05"),
        (59.6, "01:00"),
        (90, "01:30"),
        (3599, "59:59"),
        (3600, "01:00:00"),
        (7325, "02:02:05"),
    ],
)
def test_seconds_to_timestamp(seconds, expected):
    assert seconds_to_timestamp(seconds) == expected


def test_negative_seconds_clamp_to_zero():
    """The original produced malformed output like "-1:-30" for negatives."""
    assert seconds_to_timestamp(-5) == "00:00"
    assert seconds_to_timestamp(-3600) == "00:00"


@pytest.mark.parametrize("stamp,expected", [("00:30", 30.0), ("01:30", 90.0),
                                            ("01:00:00", 3600.0), ("02:02:05", 7325.0)])
def test_timestamp_to_seconds(stamp, expected):
    assert timestamp_to_seconds(stamp) == expected


def test_timestamp_roundtrip():
    for seconds in (0, 7, 61, 599, 3600, 7325):
        assert timestamp_to_seconds(seconds_to_timestamp(seconds)) == float(seconds)


@pytest.mark.parametrize("bad", ["", "12", "1:2:3:4", "aa:bb"])
def test_timestamp_to_seconds_rejects_garbage(bad):
    with pytest.raises(ValueError):
        timestamp_to_seconds(bad)


def test_overlap_seconds_disjoint_is_zero():
    assert overlap_seconds(0, 10, 20, 30) == 0.0
    assert overlap_seconds(0, 10, 10, 20) == 0.0  # touching, not overlapping


def test_overlap_seconds_partial():
    assert overlap_seconds(0, 10, 5, 15) == 5.0


class TestOverlapRatioB2:
    """B2: dedup must be symmetric so containment always registers.

    The original compared overlap against half the *candidate's own* duration.
    For a kept clip at (100,130) and a candidate at (90,180), overlap was 30s
    against a 45s threshold, so the candidate passed the check and shipped the
    same content a second time.
    """

    def test_containment_scores_one_regardless_of_argument_order(self):
        # The long interval fully contains the short one.
        assert overlap_ratio(90, 180, 100, 130) == 1.0
        assert overlap_ratio(100, 130, 90, 180) == 1.0

    def test_the_exact_regression_case_is_now_caught(self):
        kept_start, kept_end = 100.0, 130.0
        cand_start, cand_end = 90.0, 180.0

        # What the original computed: overlap vs half the candidate's duration.
        old_overlap = overlap_seconds(cand_start, cand_end, kept_start, kept_end)
        old_threshold = (cand_end - cand_start) * 0.5
        assert old_overlap == 30.0
        assert old_threshold == 45.0
        assert not (old_overlap > old_threshold), "reproduces the original miss"

        # What we compute now.
        assert overlap_ratio(cand_start, cand_end, kept_start, kept_end) > 0.5

    def test_identical_intervals(self):
        assert overlap_ratio(0, 60, 0, 60) == 1.0

    def test_disjoint(self):
        assert overlap_ratio(0, 30, 40, 70) == 0.0

    def test_half_of_shorter(self):
        # Shorter is (0,20); intersection is (10,20) = 10s -> 0.5
        assert overlap_ratio(0, 20, 10, 100) == pytest.approx(0.5)

    def test_zero_length_interval_does_not_divide_by_zero(self):
        assert overlap_ratio(10, 10, 0, 100) == 0.0


def test_intersection_over_union():
    assert intersection_over_union(0, 10, 0, 10) == pytest.approx(1.0)
    assert intersection_over_union(0, 10, 5, 15) == pytest.approx(5 / 15)
    assert intersection_over_union(0, 10, 20, 30) == 0.0


def test_format_duration():
    assert format_duration(5.2) == "5.2s"
    assert format_duration(72) == "1m 12.0s"
    assert format_duration(-3) == "0.0s"
