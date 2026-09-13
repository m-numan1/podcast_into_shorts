"""Render helpers: caption cue building, ASS output, filter-path escaping.

The ffmpeg invocation itself is not exercised here (it needs the binary and real
media); these cover the pure logic that is easy to get wrong, especially Windows
path escaping inside filter arguments.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config.settings import settings
from src.errors import RenderError
from src.providers import ffmpeg_tools
from src.providers.ffmpeg_tools import have_ffmpeg
from src.providers.renderer import (
    BASE_COLOUR,
    HIGHLIGHT_COLOUR,
    ClipRenderer,
    _ass_escape,
    _ass_time,
    build_caption_cues,
    escape_filter_path,
    group_caption_cues,
    write_ass_file,
)
from src.schema.clips import FinalClipOutput, WordTimestamp


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



class TestApostrophePaths:
    """A path containing an apostrophe must not break the filtergraph (TP-3).

    `escape_filter_path` used to emit `\'`, but ffmpeg performs no escaping
    inside a single-quoted filter argument, so the quote terminated early and
    the rest of the graph -- including the `[vout]` pad label -- was swallowed
    into the filename:

        Unable to open .../My Podcasts Folder/out/clip.ass[vout]
        Error initializing filters

    Measured against ffmpeg 9.0, an apostrophe cannot be carried through the
    filter argument by *any* quoting form: `'\''`, `'\\''` and `'\'\''`
    all parse but silently drop it, and unquoted forms fail outright. So the
    renderer never puts a directory in the filter at all -- it passes the bare
    filename and sets ffmpeg's cwd. These tests pin both halves.
    """

    def test_apostrophe_uses_close_escape_reopen_not_backslash(self):
        out = escape_filter_path(Path("/tmp/O'Brien/clip.ass"))
        assert r"'\''" in out
        # The bare `\'` form is what terminated the quoted section early.
        assert out == r"/tmp/O'\''Brien/clip.ass"

    def test_subtitles_clause_never_contains_a_directory(self):
        """The clause the filtergraph actually receives.

        Whatever the output directory is called, only the bare filename may
        reach the filter -- that is what makes an apostrophe in the directory
        irrelevant.
        """
        renderer = ClipRenderer()
        clause = renderer._subtitles_clause("clip_01.ass")
        assert "subtitles='clip_01.ass'" in clause
        assert "/" not in clause.split("subtitles=")[1]

    def test_no_captions_gives_a_passthrough(self):
        assert ClipRenderer()._subtitles_clause(None) == ";[v]null[vout]"

    @pytest.mark.skipif(not have_ffmpeg(), reason="needs the ffmpeg binary")
    def test_renders_from_a_directory_containing_an_apostrophe(self, tmp_path):
        """The end-to-end proof: this raised RenderError before the fix."""
        source = tmp_path / "source.mp4"
        ffmpeg_tools.run(
            [
                ffmpeg_tools.ffmpeg_path(), "-y", "-hide_banner",
                "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=3",
                "-f", "lavfi", "-i", "sine=frequency=300:duration=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-shortest", str(source),
            ],
            error_cls=RenderError,
            what="build apostrophe-test fixture",
        )

        out_dir = tmp_path / "O'Brien's Show" / "renders"
        out_dir.mkdir(parents=True)

        clip = FinalClipOutput(
            id="clip_01", rank=1, title="T",
            start_timestamp="00:00", end_timestamp="00:02",
            start_seconds=0.0, end_seconds=2.0, duration_seconds=2.0,
            adjusted_start_seconds=0.0, adjusted_end_seconds=2.0,
            hook="h", one_sentence_summary="s", why_this_clip_was_selected="w",
            viewer_retention_prediction="High", virality_score=5.0,
            confidence_score=5.0, overall_score=5.0, target_platform=["TikTok"],
            target_audience="a", suggested_caption="c",
            suggested_thumbnail_text="T", suggested_hashtags=["#x"],
        )
        spoken = words([("hello", 0.0, 0.5), ("there", 0.5, 1.0), ("world", 1.0, 1.5)])

        result = ClipRenderer().render(
            clip, str(source), [], spoken, has_video=True, output_dir=out_dir
        )

        rendered = Path(result.output_path)
        assert rendered.is_file() and rendered.stat().st_size > 0
        assert result.captions_burned


class TestWordHighlightCues:
    r"""Word-level highlighting, the short-form caption convention.

    One Dialogue event per word, each showing the whole cue with only the
    active word recoloured. Discrete events rather than ASS \k karaoke tags:
    \k renders as a progressive colour wipe whose appearance varies between
    libass builds, while an explicit \c override gives a crisp word-pop.
    """

    @staticmethod
    def dialogue(path: Path) -> list[str]:
        return [
            line.split(",,0,0,0,,", 1)[1]
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("Dialogue")
        ]

    @pytest.fixture
    def cues(self):
        spoken = words([("the", 0.0, 0.3), ("quick", 0.3, 0.7), ("brown", 0.7, 1.1)])
        return group_caption_cues(spoken, 0.0, 2.0)

    def test_cue_keeps_its_word_timings(self, cues):
        assert cues[0].words == (("the", 0.0, 0.3), ("quick", 0.3, 0.7), ("brown", 0.7, 1.1))

    def test_one_event_per_word(self, cues, tmp_path):
        path = write_ass_file(cues, tmp_path / "h.ass", 1080, 1920, highlight=True)
        assert len(self.dialogue(path)) == 3

    def test_each_event_shows_the_whole_cue(self, cues, tmp_path):
        path = write_ass_file(cues, tmp_path / "h.ass", 1080, 1920, highlight=True)
        for line in self.dialogue(path):
            for word in ("the", "quick", "brown"):
                assert word in line

    def test_the_highlighted_word_advances(self, cues, tmp_path):
        path = write_ass_file(cues, tmp_path / "h.ass", 1080, 1920, highlight=True)
        lines = self.dialogue(path)
        for index, word in enumerate(("the", "quick", "brown")):
            assert rf"{{\c{HIGHLIGHT_COLOUR}}}{word}{{\c{BASE_COLOUR}}}" in lines[index]

    def test_events_are_contiguous_so_captions_never_blink(self, cues, tmp_path):
        """A gap between word timings must not blank the caption."""
        path = write_ass_file(cues, tmp_path / "h.ass", 1080, 1920, highlight=True)
        raw = [
            line.split(",")[1:3]
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("Dialogue")
        ]
        for (_, end), (next_start, _) in zip(raw, raw[1:], strict=False):
            assert end == next_start

    def test_highlight_false_gives_one_static_event(self, cues, tmp_path):
        path = write_ass_file(cues, tmp_path / "s.ass", 1080, 1920, highlight=False)
        lines = self.dialogue(path)
        assert lines == ["the quick brown"]
        assert r"\c" not in lines[0]

    def test_setting_drives_the_default(self, cues, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "render_caption_highlight", False)
        assert len(self.dialogue(write_ass_file(cues, tmp_path / "a.ass", 1080, 1920))) == 1
        monkeypatch.setattr(settings, "render_caption_highlight", True)
        assert len(self.dialogue(write_ass_file(cues, tmp_path / "b.ass", 1080, 1920))) == 3

    def test_single_word_cue_falls_back_to_static(self, tmp_path):
        """Nothing to advance through, so per-word events would be noise."""
        cues = group_caption_cues(words([("hello", 0.0, 0.4)]), 0.0, 1.0)
        path = write_ass_file(cues, tmp_path / "one.ass", 1080, 1920, highlight=True)
        assert self.dialogue(path) == ["hello"]

    def test_tuple_cues_still_accepted_and_static(self, tmp_path):
        """The plain (start, end, text) form has no word data to highlight."""
        path = write_ass_file([(0.0, 1.0, "no word timings")], tmp_path / "t.ass",
                              1080, 1920, highlight=True)
        assert self.dialogue(path) == ["no word timings"]

    def test_style_computation_is_unchanged(self, cues, tmp_path):
        """Font size, margins and outline must survive the rewrite."""
        body = write_ass_file(cues, tmp_path / "h.ass", 1080, 1920,
                              highlight=True).read_text(encoding="utf-8")
        assert f"Style: Caption,Arial,{max(26, int(1920 * 0.038))}," in body
        assert f",{int(1080 * 0.07)},{int(1080 * 0.07)},{int(1920 * 0.16)},1" in body

    def test_hook_banner_still_emitted_alongside_highlights(self, cues, tmp_path):
        path = write_ass_file(cues, tmp_path / "h.ass", 1080, 1920,
                              highlight=True, hook_text="WATCH THIS")
        body = path.read_text(encoding="utf-8")
        assert "HookHeader" in body and "WATCH THIS" in body

    def test_build_caption_cues_tuple_api_is_unchanged(self):
        """Existing callers and tests must keep working."""
        spoken = words([("a", 0.0, 0.3), ("b", 0.3, 0.7)])
        assert build_caption_cues(spoken, 0.0, 2.0) == [(0.0, 0.7, "a b")]


class TestSubtitlePresets:
    @pytest.fixture
    def sample_cues(self):
        spoken = words([("make", 0.0, 0.3), ("money", 0.3, 0.6), ("online", 0.6, 1.0)])
        return group_caption_cues(spoken, 0.0, 2.0)

    def test_hormozi_preset_styling(self, sample_cues, tmp_path):
        from src.providers.renderer import SUBTITLE_PRESETS
        path = write_ass_file(sample_cues, tmp_path / "hormozi.ass", 1080, 1920, preset="hormozi", highlight=True)
        content = path.read_text(encoding="utf-8")
        # Check font, uppercase, and pop scale
        assert "Style: Caption,Impact" in content
        assert "MAKE" in content
        assert r"\fscx115\fscy115" in content
        assert r"\c&H3BF5FF&" in content

    def test_capcut_neon_preset_styling(self, sample_cues, tmp_path):
        path = write_ass_file(sample_cues, tmp_path / "capcut.ass", 1080, 1920, preset="capcut_neon", highlight=True)
        content = path.read_text(encoding="utf-8")
        assert "Style: Caption,Arial Black" in content
        assert r"\fscx112\fscy112" in content
        assert r"\c&HFFFF00&" in content

    def test_mrbeast_preset_styling(self, sample_cues, tmp_path):
        path = write_ass_file(sample_cues, tmp_path / "mrbeast.ass", 1080, 1920, preset="mrbeast", highlight=True)
        content = path.read_text(encoding="utf-8")
        assert r"\fscx120\fscy120" in content
        assert r"\c&H22E544&" in content

    def test_single_word_preset_grouping(self):
        spoken = words([("one", 0.0, 0.2), ("two", 0.2, 0.4), ("three", 0.4, 0.6)])
        cues = group_caption_cues(spoken, 0.0, 1.0, words_per_cue=1)
        assert len(cues) == 3
        assert cues[0].text == "one"
        assert cues[1].text == "two"
        assert cues[2].text == "three"

    def test_minimal_preset_styling(self, sample_cues, tmp_path):
        path = write_ass_file(sample_cues, tmp_path / "minimal.ass", 1080, 1920, preset="minimal", highlight=True)
        content = path.read_text(encoding="utf-8")
        # Minimal is not uppercase and has no pop scale
        assert "make" in content
        assert r"\fscx" not in content

    def test_urdu_preserves_noto_font_despite_preset(self, tmp_path):
        urdu_words = words([("یہ", 0.0, 0.3), ("ایک", 0.3, 0.6), ("ٹیسٹ", 0.6, 1.0)])
        urdu_cues = group_caption_cues(urdu_words, 0.0, 2.0)
        path = write_ass_file(urdu_cues, tmp_path / "urdu.ass", 1080, 1920, preset="hormozi")
        content = path.read_text(encoding="utf-8")
        # Even with Hormozi preset (Impact), Urdu text gets Noto Nastaliq Urdu
        assert "Style: Caption,Noto Nastaliq Urdu" in content

    def test_cues_never_overlap_even_with_jittered_or_backwards_words(self):
        """Regression test: overlapping words from rolling captions must not produce overlapping cues."""
        jittered = words([
            ("first", 1.0, 3.5),
            ("phrase", 1.5, 3.8),
            # Backwards timestamp simulating rolling ASR caption
            ("second", 2.0, 4.0),
            ("phrase", 2.5, 4.2),
            ("third", 3.0, 5.0),
        ])
        cues = group_caption_cues(jittered, 0.0, 10.0, words_per_cue=2)
        assert len(cues) >= 2
        for i in range(len(cues) - 1):
            assert cues[i].end <= cues[i + 1].start + 1e-5, (
                f"Cue {i} (end={cues[i].end}) overlaps with Cue {i+1} (start={cues[i+1].start})"
            )

    def test_dialogue_events_never_overlap_in_ass(self, tmp_path):
        """Dialogue lines in generated .ass file must never overlap across cues."""
        overlapping_words = words([
            ("we", 0.0, 1.5),
            ("have", 0.5, 2.0),
            ("more", 1.0, 2.5),
            ("generation", 1.8, 3.5),
            ("in", 2.2, 3.8),
            ("history", 2.6, 4.0),
        ])
        cues = group_caption_cues(overlapping_words, 0.0, 5.0, words_per_cue=2)
        path = write_ass_file(cues, tmp_path / "no_overlap.ass", 1080, 1920, highlight=True)
        dialogue_lines = [
            l for l in path.read_text(encoding="utf-8").splitlines()
            if l.startswith("Dialogue: 0,")
        ]
        # Parse start and end times for all caption dialogue events
        intervals = []
        for line in dialogue_lines:
            parts = line.split(",")
            s_parts = parts[1].split(":")
            e_parts = parts[2].split(":")
            s_sec = int(s_parts[0]) * 3600 + int(s_parts[1]) * 60 + float(s_parts[2])
            e_sec = int(e_parts[0]) * 3600 + int(e_parts[1]) * 60 + float(e_parts[2])
            intervals.append((s_sec, e_sec))

        for i in range(len(intervals) - 1):
            assert intervals[i][1] <= intervals[i + 1][0] + 1e-4, (
                f"Dialogue {i} ends at {intervals[i][1]} but dialogue {i+1} starts at {intervals[i+1][0]}"
            )

    def test_single_word_preset_pops_highlight(self, tmp_path):
        """Single-word preset must pop-scale and highlight the active word."""
        spoken = words([("focus", 0.0, 0.5)])
        cues = group_caption_cues(spoken, 0.0, 1.0, words_per_cue=1)
        path = write_ass_file(cues, tmp_path / "single.ass", 1080, 1920, preset="single_word", highlight=True)
        content = path.read_text(encoding="utf-8")
        assert r"\fscx115\fscy115" in content
        assert r"\c&H00FFFF&" in content
        assert "FOCUS" in content


