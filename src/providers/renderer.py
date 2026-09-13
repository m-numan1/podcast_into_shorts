"""Cut, reframe and caption clips with ffmpeg.

This is the stage the project was named for and did not have: the original
pipeline emitted JSON timestamps only, so "turn a podcast into shorts" stopped
one step short of producing a short.

Handles both cases:
  * source with video -> 9:16 via a blurred-fill background (no face cropping)
    or a centre crop;
  * audio-only source -> 9:16 solid background with an animated waveform, which
    is what most podcast feeds need.

Captions are burned from the transcript's word timings, grouped into short cues.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.settings import settings
from src.errors import RenderError
from src.providers import ffmpeg_tools
from src.schema.clips import FinalClipOutput, SentenceUnit, WordTimestamp
from src.utils.logging_config import get_logger

log = get_logger(__name__)

# Words per burned caption cue. Short cues are the shorts convention and stay
# readable on a phone.
WORDS_PER_CUE = 3
MAX_CUE_SECONDS = 2.5
ASS_UNSAFE_RE = re.compile(r"[{}\\]")

# Colour of the currently-spoken word. ASS colours are &HBBGGRR -- byte order
# reversed from HTML. This is #FFE066, a saturated yellow chosen because it
# stays legible against both bright and dark footage, where the project's
# indigo accent (#6366F1) does not.
HIGHLIGHT_COLOUR = "&H66E0FF&"
BASE_COLOUR = "&HFFFFFF&"


@dataclass(frozen=True)
class SubtitlePreset:
    """Style configuration for burned subtitles (OpusClip / CapCut presets)."""

    name: str
    font_name: str | None = None
    font_size_ratio: float = 0.038
    base_colour: str = "&HFFFFFF&"
    highlight_colour: str = "&H66E0FF&"
    outline_colour: str = "&H101010&"
    outline_ratio: float = 1 / 12
    shadow_width: int = 2
    alignment: int = 2  # 2 = Bottom-Center, 5 = Middle-Center
    margin_v_ratio: float = 0.16
    margin_h_ratio: float = 0.07
    words_per_cue: int = 3
    uppercase: bool = False
    pop_scale: int = 100  # 100 = normal scale, 115 = 115% scale pop on active word


def _ass_style_color(color_code: str) -> str:
    """Format color into &HAABBGGRR for ASS style definitions."""
    clean = color_code.strip("&").lstrip("Hh")
    if len(clean) == 6:
        return f"&H00{clean}&"
    if len(clean) == 8:
        return f"&H{clean}&"
    return color_code


def _ass_tag_color(color_code: str) -> str:
    """Format color into &HBBGGRR& for ASS override tags (\\c)."""
    clean = color_code.strip("&").lstrip("Hh")
    if len(clean) == 8:
        clean = clean[2:]
    return f"&H{clean}&"


SUBTITLE_PRESETS: dict[str, SubtitlePreset] = {
    "default": SubtitlePreset(
        name="Classic (Standard)",
        font_name=None,
        font_size_ratio=0.038,
        base_colour="&HFFFFFF&",
        highlight_colour="&H66E0FF&",
        outline_colour="&H101010&",
        outline_ratio=1 / 12,
        shadow_width=2,
        alignment=2,
        margin_v_ratio=0.16,
        margin_h_ratio=0.07,
        words_per_cue=3,
        uppercase=False,
        pop_scale=100,
    ),
    "hormozi": SubtitlePreset(
        name="Hormozi Bold (Yellow Pop)",
        font_name="Impact",
        font_size_ratio=0.046,
        base_colour="&HFFFFFF&",
        highlight_colour="&H3BF5FF&",  # Warm saturated yellow in ASS BGR
        outline_colour="&H000000&",     # Solid thick black border
        outline_ratio=1 / 8,
        shadow_width=3,
        alignment=2,
        margin_v_ratio=0.28,             # Raised to central eye level
        margin_h_ratio=0.07,
        words_per_cue=3,
        uppercase=True,
        pop_scale=115,                   # Active word pops 15% larger
    ),
    "capcut_neon": SubtitlePreset(
        name="CapCut Neon (Cyan)",
        font_name="Arial Black",
        font_size_ratio=0.044,
        base_colour="&HFFFFFF&",
        highlight_colour="&HFFFF00&",  # Electric Cyan in ASS BGR (&HBBGGRR)
        outline_colour="&H101010&",
        outline_ratio=1 / 9,
        shadow_width=2,
        alignment=2,
        margin_v_ratio=0.26,
        margin_h_ratio=0.07,
        words_per_cue=3,
        uppercase=True,
        pop_scale=112,
    ),
    "mrbeast": SubtitlePreset(
        name="MrBeast (Green Punch)",
        font_name="Impact",
        font_size_ratio=0.048,
        base_colour="&HFFFFFF&",
        highlight_colour="&H22E544&",  # Vibrant neon green in ASS BGR
        outline_colour="&H000000&",
        outline_ratio=1 / 7,
        shadow_width=3,
        alignment=2,
        margin_v_ratio=0.30,
        margin_h_ratio=0.07,
        words_per_cue=2,
        uppercase=True,
        pop_scale=120,                   # Punchy bounce
    ),
    "single_word": SubtitlePreset(
        name="Single Word (Rapid Fire)",
        font_name="Impact",
        font_size_ratio=0.052,
        base_colour="&HFFFFFF&",
        highlight_colour="&H00FFFF&",  # Pure bright yellow pop in ASS BGR
        outline_colour="&H000000&",
        outline_ratio=1 / 7,
        shadow_width=4,
        alignment=2,
        margin_v_ratio=0.35,             # Centered in frame
        margin_h_ratio=0.07,
        words_per_cue=1,
        uppercase=True,
        pop_scale=115,
    ),
    "minimal": SubtitlePreset(
        name="Clean Minimal (Bottom)",
        font_name="Arial",
        font_size_ratio=0.035,
        base_colour="&HF0F0F0&",
        highlight_colour="&H66E0FF&",
        outline_colour="&H202020&",
        outline_ratio=1 / 14,
        shadow_width=1,
        alignment=2,
        margin_v_ratio=0.12,             # Traditional lower third
        margin_h_ratio=0.08,
        words_per_cue=5,
        uppercase=False,
        pop_scale=100,
    ),
}


def get_subtitle_preset(name_or_preset: str | SubtitlePreset | None) -> SubtitlePreset:
    """Resolve a subtitle preset name or instance to a SubtitlePreset."""
    if isinstance(name_or_preset, SubtitlePreset):
        return name_or_preset
    if not name_or_preset:
        return SUBTITLE_PRESETS["default"]
    key = str(name_or_preset).strip().lower()
    return SUBTITLE_PRESETS.get(key, SUBTITLE_PRESETS["default"])


@dataclass(frozen=True)
class CaptionCue:
    """A caption cue that remembers the timing of each word inside it.

    Times are relative to the clip start. `words` is what makes word-level
    highlighting possible; it is empty when the source had no usable word
    timings, and rendering falls back to a static cue for that cue alone.
    """

    start: float
    end: float
    text: str
    words: tuple[tuple[str, float, float], ...] = ()


@dataclass(frozen=True)
class RenderResult:
    clip_id: str
    output_path: str
    duration: float
    had_video: bool
    captions_burned: bool


def _ass_time(seconds: float) -> str:
    """ASS timestamps are H:MM:SS.cc (centiseconds)."""
    total = max(0.0, seconds)
    hrs = int(total // 3600)
    mins = int((total % 3600) // 60)
    secs = total % 60
    return f"{hrs}:{mins:02d}:{secs:05.2f}"


def _ass_escape(text: str) -> str:
    return ASS_UNSAFE_RE.sub("", text).replace("\n", " ").strip()


def escape_filter_path(path: Path) -> str:
    """Escape a path for use inside a single-quoted ffmpeg filter argument.

    Windows paths break the filter parser twice over: backslashes are escapes
    and the drive colon separates filter options. Both must be neutralised.

    Apostrophes need close-escape-reopen (`'\\''`), not a backslash. ffmpeg
    performs no escaping inside a single-quoted section, so the `\\'` this used
    to emit ended the quote early and the rest of the filtergraph -- including
    the `[vout]` pad label -- was swallowed into the filename:

        Unable to open .../My Podcasts Folder/out/clip.ass[vout]
        Error initializing filters

    That is fixed here. Note the separate, harder limitation measured against
    ffmpeg 9.0: an apostrophe cannot be carried through the filter argument at
    all. Every quoted form (`'\\''`, `'\\\\''`, `'\\'\\''`) parses cleanly but
    silently *drops* the apostrophe, and every unquoted form fails with
    "Invalid argument". `ClipRenderer` therefore never passes a directory to
    the subtitles filter -- see `_run_ffmpeg`.
    """
    text = str(path).replace("\\", "/")
    text = text.replace(":", r"\:")
    # Close the quoted section, emit an escaped literal quote, reopen it.
    text = text.replace("'", r"'\''")
    text = text.replace("[", r"\[").replace("]", r"\]")
    text = text.replace(",", r"\,")
    return text


def group_caption_cues(
    words: list[WordTimestamp],
    clip_start: float,
    clip_end: float,
    words_per_cue: int = WORDS_PER_CUE,
) -> list[CaptionCue]:
    """Group words into caption cues, keeping each word's own timing.

    Grouping is flushed at `words_per_cue` words or `MAX_CUE_SECONDS`.
    The per-word times are carried through so the ASS writer can highlight
    the word being spoken. Cues are guaranteed to be strictly chronological
    and non-overlapping so old words never linger when new words are spoken.
    """
    inside = [
        w for w in words
        if w.end > clip_start and w.start < clip_end and w.word.strip()
    ]
    if not inside:
        return []

    # Sort words chronologically to resolve any out-of-order timings
    inside.sort(key=lambda w: (w.start, w.end))

    # Clean word intervals: ensure monotonicity and eliminate intra-word overlaps
    resolved_words: list[WordTimestamp] = []
    for w in inside:
        if not resolved_words:
            resolved_words.append(w)
            continue
        prev = resolved_words[-1]
        w_start = max(w.start, prev.start)
        if prev.end > w_start:
            clamped_prev_end = max(prev.start + 0.05, w_start)
            resolved_words[-1] = WordTimestamp(
                word=prev.word,
                start=prev.start,
                end=clamped_prev_end,
                confidence=prev.confidence,
            )
        w_end = max(w.end, w_start + 0.05)
        resolved_words.append(
            WordTimestamp(
                word=w.word,
                start=w_start,
                end=w_end,
                confidence=w.confidence,
            )
        )

    raw_cues: list[CaptionCue] = []
    group: list[WordTimestamp] = []

    def flush() -> None:
        if not group:
            return
        start = max(0.0, group[0].start - clip_start)
        end = max(start + 0.15, min(group[-1].end, clip_end) - clip_start)
        text = " ".join(w.word.strip() for w in group)
        # Clamp each word into the cue so a highlight can never precede the
        # cue's own start or outlive its end.
        spans = tuple(
            (
                w.word.strip(),
                min(max(w.start - clip_start, start), end),
                min(max(w.end - clip_start, start), end),
            )
            for w in group
        )
        raw_cues.append(CaptionCue(start=start, end=end, text=text, words=spans))

    for word in resolved_words:
        if group:
            span = word.end - group[0].start
            if len(group) >= words_per_cue or span > MAX_CUE_SECONDS:
                flush()
                group = []
        group.append(word)
    flush()

    # Guarantee strictly non-overlapping cue intervals so libass never renders
    # multiple caption lines simultaneously on screen.
    raw_cues.sort(key=lambda c: (c.start, c.end))
    cues: list[CaptionCue] = []
    for c in raw_cues:
        if not cues:
            cues.append(c)
            continue
        prev = cues[-1]
        if c.start < prev.start:
            continue
        if prev.end > c.start:
            clamped_end = max(prev.start + 0.1, c.start)
            prev_words = tuple(
                (w, min(ws, clamped_end), min(we, clamped_end))
                for w, ws, we in prev.words
            )
            cues[-1] = CaptionCue(
                start=prev.start,
                end=clamped_end,
                text=prev.text,
                words=prev_words,
            )
            if c.start < clamped_end:
                c_start = clamped_end
                c_end = max(c_start + 0.15, c.end)
                c_words = tuple(
                    (w, max(ws, c_start), max(we, c_start))
                    for w, ws, we in c.words
                )
                c = CaptionCue(start=c_start, end=c_end, text=c.text, words=c_words)
        cues.append(c)

    return cues


def build_caption_cues(
    words: list[WordTimestamp],
    clip_start: float,
    clip_end: float,
) -> list[tuple[float, float, str]]:
    """Cues as plain (start, end, text) tuples, without word timings."""
    return [(c.start, c.end, c.text) for c in group_caption_cues(words, clip_start, clip_end)]


def _cue_dialogue_lines(
    cue: CaptionCue,
    highlight: bool,
    *,
    highlight_colour: str = HIGHLIGHT_COLOUR,
    base_colour: str = BASE_COLOUR,
    pop_scale: int = 100,
    uppercase: bool = False,
) -> list[str]:
    """Dialogue events for one cue.

    Static: a single event showing the whole cue.

    Highlighted: one event per word, each showing the *whole* cue with only the
    active word recoloured (and optionally pop-scaled). Discrete per-word events
    are used rather than ASS `\\k` karaoke tags because `\\k` renders as a
    progressive colour wipe whose appearance varies between libass builds, while
    an explicit `\\c` override gives the crisp word-pop the format actually expects.

    Events are made contiguous -- each word runs until the next one starts --
    so the caption never blinks out in the gaps between word timings.
    """
    raw_cue_text = cue.text.upper() if uppercase else cue.text
    escaped_cue = _ass_escape(raw_cue_text)
    if not escaped_cue:
        return []

    escaped_words = [
        _ass_escape(word.upper() if uppercase else word)
        for word, _, _ in cue.words
    ]

    # Single-word cue with active pop scaling (e.g. single_word preset)
    if len(cue.words) == 1 and escaped_words and escaped_words[0] and highlight and pop_scale != 100:
        scale_prefix = f"\\fscx{pop_scale}\\fscy{pop_scale}"
        scale_reset = "\\fscx100\\fscy100"
        single_text = f"{{{scale_prefix}\\c{highlight_colour}}}{escaped_words[0]}{{{scale_reset}\\c{base_colour}}}"
        return [
            f"Dialogue: 0,{_ass_time(cue.start)},{_ass_time(cue.end)},"
            f"Caption,,0,0,0,,{single_text}"
        ]

    usable = highlight and len(cue.words) > 1 and all(escaped_words)
    if not usable:
        return [
            f"Dialogue: 0,{_ass_time(cue.start)},{_ass_time(cue.end)},"
            f"Caption,,0,0,0,,{escaped_cue}"
        ]

    starts = [max(cue.start, span[1]) for span in cue.words]
    # Monotonic starts: a jittered word timing must not produce a zero- or
    # negative-length event that libass would drop.
    for i in range(1, len(starts)):
        starts[i] = max(starts[i], starts[i - 1])

    scale_prefix = f"\\fscx{pop_scale}\\fscy{pop_scale}" if pop_scale != 100 else ""
    scale_reset = "\\fscx100\\fscy100" if pop_scale != 100 else ""

    lines: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else cue.end
        if end <= start:
            continue
        text = " ".join(
            f"{{{scale_prefix}\\c{highlight_colour}}}{word}{{{scale_reset}\\c{base_colour}}}"
            if position == index
            else word
            for position, word in enumerate(escaped_words)
        )
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,{text}"
        )
    return lines or [
        f"Dialogue: 0,{_ass_time(cue.start)},{_ass_time(cue.end)},"
        f"Caption,,0,0,0,,{escaped_cue}"
    ]


def _as_cues(
    cues: list[tuple[float, float, str]] | list[CaptionCue],
) -> list[CaptionCue]:
    """Accept either the plain tuple form or the word-aware form."""
    return [c if isinstance(c, CaptionCue) else CaptionCue(*c) for c in cues]


def detect_subtitle_font(texts: list[str]) -> str:
    """Select appropriate font for subtitles based on text script (Urdu, Hindi/Devanagari, or Latin)."""
    if getattr(settings, "caption_font", ""):
        return settings.caption_font
    sample = " ".join(texts)
    # Urdu / Arabic Unicode blocks
    if re.search(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]", sample):
        return "Noto Nastaliq Urdu"
    # Hindi / Devanagari Unicode blocks
    if re.search(r"[\u0900-\u097F]", sample):
        return "Noto Sans Devanagari"
    return "Arial"


def resolve_font(
    sample_texts: list[str],
    font_override: str | None = None,
    preset_font: str | None = None,
) -> str:
    """Resolve font respecting language scripts and preset preferences."""
    detected = detect_subtitle_font(sample_texts)
    if detected in ("Noto Nastaliq Urdu", "Noto Sans Devanagari"):
        return detected
    return font_override or preset_font or detected


def write_ass_file(
    cues: list[tuple[float, float, str]] | list[CaptionCue],
    path: Path,
    width: int,
    height: int,
    *,
    highlight: bool | None = None,
    font_name: str | None = None,
    preset: str | SubtitlePreset | None = None,
) -> Path:
    """Write an ASS subtitle file styled for vertical/multi-format video."""
    p = get_subtitle_preset(preset)

    font_size = max(26, int(height * p.font_size_ratio))
    margin_v = int(height * p.margin_v_ratio)
    margin_h = int(width * p.margin_h_ratio)
    outline = max(2, int(font_size * p.outline_ratio))

    resolved_cues = _as_cues(cues)
    sample_texts = [c.text for c in resolved_cues]
    active_font = resolve_font(sample_texts, font_name, p.font_name)

    style_base = _ass_style_color(p.base_colour)
    style_outline = _ass_style_color(p.outline_colour)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{active_font},{font_size},{style_base},&H000000FF,{style_outline},&HA0000000,-1,0,0,0,100,100,0,0,1,{outline},{p.shadow_width},{p.alignment},{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines: list[str] = []

    use_highlight = (
        settings.render_caption_highlight if highlight is None else highlight
    )
    tag_hl = _ass_tag_color(p.highlight_colour)
    tag_base = _ass_tag_color(p.base_colour)
    for cue in resolved_cues:
        lines.extend(
            _cue_dialogue_lines(
                cue,
                use_highlight,
                highlight_colour=tag_hl,
                base_colour=tag_base,
                pop_scale=p.pop_scale,
                uppercase=p.uppercase,
            )
        )

    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return path


class ClipRenderer:
    def __init__(
        self,
        aspect_ratio: str | None = None,
        subtitle_preset: str | SubtitlePreset | None = None,
    ) -> None:
        self.aspect_ratio = aspect_ratio or settings.aspect_ratio
        self.subtitle_preset = subtitle_preset or getattr(settings, "subtitle_preset", "hormozi")
        self.width, self.height = settings.resolve_dimensions(self.aspect_ratio)

    def _subtitles_clause(self, ass_name: str | None) -> str:
        """Chain the subtitles filter, or a passthrough when there are none.

        `ass_name` is a bare filename, never a path: ffmpeg is run with its cwd
        set to the directory holding it. A directory component cannot be
        escaped safely once it contains an apostrophe (see
        `escape_filter_path`), and clip ids are already sanitised to
        [0-9A-Za-z_-], so the bare name is always representable.
        """
        if not ass_name:
            return ";[v]null[vout]"
        return f";[v]subtitles='{escape_filter_path(Path(ass_name))}'[vout]"

    def _video_filter(self, has_captions: bool, ass_name: str | None) -> str:
        w, h = self.width, self.height
        if settings.render_mode == "crop":
            base = (
                f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},setsar=1[v]"
            )
        else:
            # Blurred fill: keeps the whole frame visible instead of cropping
            # faces out of a 16:9 interview shot.
            base = (
                f"[0:v]split=2[bg][fg];"
                f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},gblur=sigma=28[bgb];"
                f"[fg]scale={w}:-2:force_original_aspect_ratio=decrease[fgs];"
                f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
            )
        return base + self._subtitles_clause(ass_name if has_captions else None)

    def _audio_only_filter(self, has_captions: bool, ass_name: str | None) -> str:
        w, h = self.width, self.height
        wave_h = int(h * 0.18)
        base = (
            f"[0:a]showwaves=s={w}x{wave_h}:mode=cline:rate=25:colors=0x6366F1[wave];"
            f"[1:v][wave]overlay=0:(H-h)/2:shortest=1,setsar=1[v]"
        )
        return base + self._subtitles_clause(ass_name if has_captions else None)

    def render(
        self,
        clip: FinalClipOutput,
        media_path: str,
        units: list[SentenceUnit],
        all_words: list[WordTimestamp],
        *,
        has_video: bool,
        output_dir: Path | None = None,
        aspect_ratio: str | None = None,
        subtitle_preset: str | SubtitlePreset | None = None,
    ) -> RenderResult:
        ratio = aspect_ratio or self.aspect_ratio
        self.width, self.height = settings.resolve_dimensions(ratio)
        active_preset = get_subtitle_preset(subtitle_preset or self.subtitle_preset)

        source = Path(media_path)
        if not source.exists():
            from src.providers.downloader import MediaDownloaderProvider, is_url
            if is_url(media_path):
                info = MediaDownloaderProvider().download(media_path)
                source = Path(info.file_path)
            elif (settings.cache_dir / media_path).exists():
                source = (settings.cache_dir / media_path).resolve()

        if not source.exists():
            raise RenderError(f"Source media missing for render: {source}")

        out_dir = (output_dir or settings.render_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        # Absolute: ffmpeg runs with cwd=out_dir so the subtitles filter can
        # reference the .ass by bare name, which means every other path in the
        # argv must not depend on the caller's cwd.
        out_dir = out_dir.resolve()
        source = source.resolve()
        safe_id = re.sub(r"[^0-9A-Za-z_-]", "_", clip.id)
        out_path = out_dir / f"{safe_id}.mp4"

        start = max(0.0, clip.adjusted_start_seconds)
        end = max(start + 0.5, clip.adjusted_end_seconds)
        duration = end - start

        ass_path: Path | None = None
        cues: list[CaptionCue] = []
        if settings.render_burn_captions:
            cues = group_caption_cues(all_words, start, end, words_per_cue=active_preset.words_per_cue)
            if cues:
                ass_path = write_ass_file(
                    cues,
                    out_dir / f"{safe_id}.ass",
                    self.width,
                    self.height,
                    preset=active_preset,
                )

        binary = ffmpeg_tools.ffmpeg_path()
        args: list[str] = [binary, "-y", "-hide_banner"]
        # -ss before -i seeks fast; -accurate_seek keeps the cut frame-exact.
        args += ["-accurate_seek", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}"]
        args += ["-i", str(source)]

        ass_name = ass_path.name if ass_path is not None else None
        if has_video:
            filter_complex = self._video_filter(bool(ass_name), ass_name)
        else:
            # A synthetic background track for audio-only sources.
            args += [
                "-f", "lavfi",
                "-t", f"{duration:.3f}",
                "-i", f"color=c=0x0B0F19:s={self.width}x{self.height}:r=25",
            ]
            filter_complex = self._audio_only_filter(bool(ass_name), ass_name)

        args += [
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "0:a?",
            "-af", f"loudnorm=I={settings.render_loudness_lufs}:TP=-1.5:LRA=11",
            "-c:v", "libx264",
            "-preset", settings.render_preset,
            "-crf", str(settings.render_crf),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "160k",
            "-movflags", "+faststart",
            str(out_path),
        ]

        log.info(
            "Rendering %s (%.1fs, ratio=%s, preset=%s)",
            clip.id, duration, ratio, active_preset.name,
        )
        ffmpeg_tools.run(
            args,
            error_cls=RenderError,
            what=f"render of {clip.id}",
            # So the subtitles filter can name the .ass without a directory.
            cwd=out_dir,
        )

        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RenderError(f"ffmpeg produced no output for {clip.id}")

        return RenderResult(
            clip_id=clip.id,
            output_path=str(out_path.resolve()),
            duration=duration,
            had_video=has_video,
            captions_burned=bool(ass_path),
        )

    def render_clip(
        self,
        clip_data: dict[str, Any] | FinalClipOutput,
        media_path: str | Path | None = None,
        all_words: list[WordTimestamp] | None = None,
        *,
        output_dir: Path | None = None,
        aspect_ratio: str | None = None,
        subtitle_preset: str | SubtitlePreset | None = None,
    ) -> dict[str, Any]:
        """Convenience method to render a single clip dict or FinalClipOutput to MP4."""
        from src.providers.downloader import is_url
        from src.utils.timestamps import extract_clip_timestamps

        out_dir = output_dir or settings.render_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        ratio = aspect_ratio or self.aspect_ratio or "9:16"
        preset = subtitle_preset or self.subtitle_preset

        if isinstance(clip_data, dict):
            start, end, title, clip_id = extract_clip_timestamps(clip_data)
            duration = max(0.1, end - start)
            formatted_clip = FinalClipOutput(
                id=clip_id,
                rank=int(clip_data.get("rank", 1)),
                title=title,
                start_timestamp=f"{int(start//60):02d}:{int(start%60):02d}",
                end_timestamp=f"{int(end//60):02d}:{int(end%60):02d}",
                start_seconds=start,
                end_seconds=end,
                duration_seconds=duration,
                adjusted_start_seconds=start,
                adjusted_end_seconds=end,
                hook=str(clip_data.get("hook", title)),
                one_sentence_summary=str(clip_data.get("one_sentence_summary", title)),
                why_this_clip_was_selected=str(clip_data.get("why_this_clip_was_selected", "")),
                viewer_retention_prediction=str(clip_data.get("viewer_retention_prediction", "")),
                virality_score=float(clip_data.get("virality_score", 8.0)),
                confidence_score=float(clip_data.get("confidence_score", 8.0)),
                overall_score=float(clip_data.get("overall_score", 8.0)),
                target_platform=list(clip_data.get("target_platform", ["TikTok"])),
                target_audience=str(clip_data.get("target_audience", "General")),
                suggested_caption=str(clip_data.get("suggested_caption", "")),
                suggested_thumbnail_text=str(clip_data.get("suggested_thumbnail_text", "")),
                suggested_hashtags=list(clip_data.get("suggested_hashtags", ["#shorts"])),
            )
            raw_clip_dict = dict(clip_data)
        else:
            formatted_clip = clip_data
            raw_clip_dict = formatted_clip.model_dump(mode="json")

        source = Path(str(media_path).strip()) if media_path else Path()
        if not source.exists() or not source.is_file():
            str_path = str(media_path or "").strip()
            if str_path and (settings.cache_dir / str_path).is_file():
                source = (settings.cache_dir / str_path).resolve()
            elif str_path and is_url(str_path):
                from src.providers.downloader import MediaDownloaderProvider
                log.info("Media path is URL (%s); resolving via downloader...", str_path)
                info = MediaDownloaderProvider().download(str_path)
                source = Path(info.file_path).resolve()
            else:
                # Search cache_dir for recent media file
                cached = [
                    f for f in settings.cache_dir.glob("*")
                    if f.is_file() and f.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov", ".mp3", ".wav", ".m4a")
                ]
                if cached:
                    source = max(cached, key=lambda f: f.stat().st_mtime).resolve()

        if not source.exists():
            raise RenderError(f"Media file not found for render: {media_path}")

        has_vid = ffmpeg_tools.probe_has_video_stream(source)
        res = self.render(
            clip=formatted_clip,
            media_path=str(source),
            units=[],
            all_words=all_words or [],
            has_video=has_vid,
            output_dir=out_dir,
            aspect_ratio=ratio,
            subtitle_preset=preset,
        )

        raw_clip_dict["rendered_file_path"] = res.output_path
        return raw_clip_dict
