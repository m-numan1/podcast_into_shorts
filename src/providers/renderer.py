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
) -> list[CaptionCue]:
    """Group words into caption cues, keeping each word's own timing.

    Grouping is unchanged -- flush at WORDS_PER_CUE words or MAX_CUE_SECONDS --
    but the per-word times are carried through so the ASS writer can highlight
    the word being spoken.
    """
    inside = [
        w for w in words
        if w.end > clip_start and w.start < clip_end and w.word.strip()
    ]
    cues: list[CaptionCue] = []
    group: list[WordTimestamp] = []

    def flush() -> None:
        if not group:
            return
        start = max(0.0, group[0].start - clip_start)
        end = max(start + 0.2, min(group[-1].end, clip_end) - clip_start)
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
        cues.append(CaptionCue(start=start, end=end, text=text, words=spans))

    for word in inside:
        if group:
            span = word.end - group[0].start
            if len(group) >= WORDS_PER_CUE or span > MAX_CUE_SECONDS:
                flush()
                group = []
        group.append(word)
    flush()
    return cues


def build_caption_cues(
    words: list[WordTimestamp],
    clip_start: float,
    clip_end: float,
) -> list[tuple[float, float, str]]:
    """Cues as plain (start, end, text) tuples, without word timings."""
    return [(c.start, c.end, c.text) for c in group_caption_cues(words, clip_start, clip_end)]


def _cue_dialogue_lines(cue: CaptionCue, highlight: bool) -> list[str]:
    """Dialogue events for one cue.

    Static: a single event showing the whole cue.

    Highlighted: one event per word, each showing the *whole* cue with only the
    active word recoloured. Discrete per-word events are used rather than ASS
    `\\k` karaoke tags because `\\k` renders as a progressive colour wipe whose
    appearance varies between libass builds, while an explicit `\\c` override
    gives the crisp word-pop the format actually expects.

    Events are made contiguous -- each word runs until the next one starts --
    so the caption never blinks out in the gaps between word timings.
    """
    escaped_cue = _ass_escape(cue.text)
    if not escaped_cue:
        return []

    escaped_words = [_ass_escape(word) for word, _, _ in cue.words]
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

    lines: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else cue.end
        if end <= start:
            continue
        text = " ".join(
            f"{{\\c{HIGHLIGHT_COLOUR}}}{word}{{\\c{BASE_COLOUR}}}"
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


def write_ass_file(
    cues: list[tuple[float, float, str]] | list[CaptionCue],
    path: Path,
    width: int,
    height: int,
    *,
    hook_text: str | None = None,
    hook_duration: float = 3.5,
    highlight: bool | None = None,
) -> Path:
    """Write an ASS subtitle file styled for vertical/multi-format video with top hook banner."""
    font_size = max(26, int(height * 0.038))
    margin_v = int(height * 0.16)
    margin_h = int(width * 0.07)

    hook_font_size = max(28, int(height * 0.042))
    hook_margin_v = int(height * 0.06)
    hook_margin_h = int(width * 0.05)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00101010,&HA0000000,-1,0,0,0,100,100,0,0,1,{max(2, font_size // 12)},2,2,{margin_h},{margin_h},{margin_v},1
Style: HookHeader,Arial,{hook_font_size},&H00FFFFFF,&H000000FF,&H006366F1,&HA0000000,-1,0,0,0,100,100,0,0,1,{max(2, hook_font_size // 10)},2,8,{hook_margin_h},{hook_margin_h},{hook_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines: list[str] = []
    if hook_text and _ass_escape(hook_text):
        lines.append(
            f"Dialogue: 1,0:00:00.00,{_ass_time(hook_duration)},HookHeader,,0,0,0,,{_ass_escape(hook_text)}"
        )

    use_highlight = (
        settings.render_caption_highlight if highlight is None else highlight
    )
    for cue in _as_cues(cues):
        lines.extend(_cue_dialogue_lines(cue, use_highlight))

    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return path


class ClipRenderer:
    def __init__(self, aspect_ratio: str | None = None, enable_hook_banner: bool = True) -> None:
        self.aspect_ratio = aspect_ratio or settings.aspect_ratio
        self.enable_hook_banner = enable_hook_banner
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
        enable_hook_banner: bool | None = None,
    ) -> RenderResult:
        ratio = aspect_ratio or self.aspect_ratio
        self.width, self.height = settings.resolve_dimensions(ratio)
        use_hook = self.enable_hook_banner if enable_hook_banner is None else enable_hook_banner

        source = Path(media_path)
        if not source.exists():
            from src.providers.downloader import is_url, MediaDownloaderProvider
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

        hook_text = None
        if use_hook:
            hook_text = (
                clip.suggested_thumbnail_text
                or clip.hook
                or clip.title
            )

        ass_path: Path | None = None
        cues: list[CaptionCue] = []
        if settings.render_burn_captions or hook_text:
            if settings.render_burn_captions:
                cues = group_caption_cues(all_words, start, end)
            if cues or hook_text:
                ass_path = write_ass_file(
                    cues,
                    out_dir / f"{safe_id}.ass",
                    self.width,
                    self.height,
                    hook_text=hook_text if use_hook else None,
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

        log.info("Rendering %s (%.1fs, ratio=%s, hook_banner=%s)", clip.id, duration, ratio, bool(hook_text))
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
