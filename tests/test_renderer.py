"""Render helpers: caption cue building, ASS output, filter-path escaping.

The ffmpeg invocation itself is not exercised here (it needs the binary and real
media); these cover the pure logic that is easy to get wrong, especially Windows
path escaping inside filter arguments.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.providers.renderer import (
    _ass_escape,
    _ass_time,
    build_caption_cues,
    escape_filter_path,
    write_ass_file,
)
from src.schema.clips import WordTimestamp


def words(spec: list[tuple[str, float, float]]) -> list[WordTimestamp]:
    return [WordTimestamp(word=w, start=s, end=e) for w, s, e in spec]


class TestAssTime:
    @pytest.mark.parametrize("seconds,expected", [
        (0.0, "0:00:00.00"),
        (1.5, "0:00:01.50"),
        (61.25, "0:01:01.25"),
        (3661.0, "1:01:01.00"),
    ])
    def test_format(self, seconds, expected):
        assert _ass_time(seconds) == expected

    def test_negative_clamps(self):
        assert _ass_time(-5.0) == "0:00:00.00"


class TestAssEscape:
    def test_strips_override_braces(self):
        """Unescaped braces are ASS override blocks and would inject styling."""
        assert "{" not in _ass_escape("hello {\\an8} world")
        assert "}" not in _ass_escape("hello {\\an8} world")

    def test_collapses_newlines(self):
        assert "\n" not in _ass_escape("line one\nline two")

    def test_plain_text_survives(self):
        assert _ass_escape("  normal words  ") == "normal words"


class TestEscapeFilterPath:
    """ffmpeg filter args treat backslash as escape and colon as a separator,
    so a raw Windows path breaks the parser twice."""

    def test_no_backslash_remains_a_path_separator(self):
        """Escaping the drive colon legitimately introduces `\\:`, so the check
        is that every remaining backslash escapes a special character rather
        than separating path components."""
        out = escape_filter_path(Path(r"C:\Users\me\clip.ass"))
        assert "/Users/me/clip.ass" in out
        for index, char in enumerate(out):
            if char == "\\":
                assert out[index + 1] in ":'[],", f"stray backslash at {index}: {out!r}"

    def test_drive_colon_is_escaped(self):
        out = escape_filter_path(Path(r"C:\tmp\clip.ass"))
        assert r"\:" in out

    def test_special_characters_are_escaped(self):
        out = escape_filter_path(Path("/tmp/a[1],b'c.ass"))
        for token in (r"\[", r"\]", r"\,", r"\'"):
            assert token in out

    def test_simple_posix_path_is_mostly_unchanged(self):
        assert escape_filter_path(Path("/tmp/clip.ass")) == "/tmp/clip.ass"


class TestCaptionCues:
    def test_groups_words_into_short_cues(self):
        spec = [(f"w{i}", i * 0.4, (i + 1) * 0.4) for i in range(12)]
        cues = build_caption_cues(words(spec), 0.0, 10.0)
        assert cues
        assert all(len(text.split()) <= 3 for _, _, text in cues)

    def test_times_are_relative_to_the_clip_start(self):
        spec = [("hello", 100.0, 100.5), ("world", 100.5, 101.0)]
        cues = build_caption_cues(words(spec), 100.0, 110.0)
        assert cues[0][0] == pytest.approx(0.0, abs=0.01)

    def test_words_outside_the_clip_are_excluded(self):
        spec = [("before", 0.0, 1.0), ("inside", 50.0, 51.0), ("after", 200.0, 201.0)]
        cues = build_caption_cues(words(spec), 40.0, 60.0)
        joined = " ".join(text for _, _, text in cues)
        assert "inside" in joined
        assert "before" not in joined
        assert "after" not in joined

    def test_no_words_gives_no_cues(self):
        assert build_caption_cues([], 0.0, 10.0) == []

    def test_blank_words_are_skipped(self):
        spec = [("  ", 0.0, 0.5), ("real", 0.5, 1.0)]
        cues = build_caption_cues(words(spec), 0.0, 5.0)
        assert " ".join(t for _, _, t in cues).strip() == "real"

    def test_cue_end_never_precedes_start(self):
        spec = [(f"w{i}", i * 0.3, (i + 1) * 0.3) for i in range(20)]
        for start, end, _ in build_caption_cues(words(spec), 0.0, 6.0):
            assert end > start

    def test_cues_do_not_extend_past_the_clip(self):
        spec = [("late", 9.0, 15.0)]
        cues = build_caption_cues(words(spec), 0.0, 10.0)
        for _, end, _ in cues:
            assert end <= 10.0 + 1e-6

    def test_long_word_spans_are_split_by_duration(self):
        # Two words per second would exceed MAX_CUE_SECONDS if not split.
        spec = [(f"w{i}", i * 2.0, i * 2.0 + 2.0) for i in range(6)]
        cues = build_caption_cues(words(spec), 0.0, 12.0)
        assert len(cues) >= 3


class TestWriteAssFile:
    def test_writes_a_parseable_header(self, tmp_path):
        path = write_ass_file(
            [(0.0, 1.0, "hello world")], tmp_path / "c.ass", 1080, 1920
        )
        text = path.read_text(encoding="utf-8")
        assert "[Script Info]" in text
        assert "PlayResX: 1080" in text
        assert "PlayResY: 1920" in text
        assert "[V4+ Styles]" in text
        assert "[Events]" in text

    def test_one_dialogue_line_per_cue(self, tmp_path):
        cues = [(0.0, 1.0, "one"), (1.0, 2.0, "two"), (2.0, 3.0, "three")]
        path = write_ass_file(cues, tmp_path / "c.ass", 1080, 1920)
        lines = [
            line for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("Dialogue:")
        ]
        assert len(lines) == 3

    def test_empty_cue_text_is_dropped(self, tmp_path):
        path = write_ass_file(
            [(0.0, 1.0, "   "), (1.0, 2.0, "real")], tmp_path / "c.ass", 1080, 1920
        )
        lines = [
            line for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("Dialogue:")
        ]
        assert len(lines) == 1

    def test_font_size_scales_with_height(self, tmp_path):
        small = write_ass_file([(0.0, 1.0, "x")], tmp_path / "s.ass", 540, 960)
        large = write_ass_file([(0.0, 1.0, "x")], tmp_path / "l.ass", 1080, 1920)

        def font_size(path: Path) -> int:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("Style: Caption"):
                    return int(line.split(",")[2])
            raise AssertionError("no style line")

        assert font_size(large) > font_size(small)

    def test_hook_header_in_ass_file(self, tmp_path):
        path = write_ass_file(
            [(0.0, 1.0, "hello world")],
            tmp_path / "h.ass",
            1080,
            1920,
            hook_text="MUST WATCH: Amazing Insight",
        )
        text = path.read_text(encoding="utf-8")
        assert "Style: HookHeader" in text
        assert "MUST WATCH: Amazing Insight" in text
        lines = [line for line in text.splitlines() if line.startswith("Dialogue:")]
        assert len(lines) == 2
        assert "HookHeader" in lines[0]


class TestClipRendererAspectRatios:
    def test_aspect_ratio_resolutions(self):
        from src.providers.renderer import ClipRenderer

        r916 = ClipRenderer(aspect_ratio="9:16")
        assert (r916.width, r916.height) == (1080, 1920)

        r11 = ClipRenderer(aspect_ratio="1:1")
        assert (r11.width, r11.height) == (1080, 1080)

        r169 = ClipRenderer(aspect_ratio="16:9")
        assert (r169.width, r169.height) == (1920, 1080)

