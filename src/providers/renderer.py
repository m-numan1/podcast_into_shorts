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
    """Escape a path for use inside an ffmpeg filter argument.

    Windows paths break the filter parser twice over: backslashes are escapes
    and the drive colon separates filter options. Both must be neutralised.
    """
    text = str(path).replace("\\", "/")
    text = text.replace(":", r"\:")
    text = text.replace("'", r"\'")
    text = text.replace("[", r"\[").replace("]", r"\]")
    text = text.replace(",", r"\,")
    return text


def build_caption_cues(
    words: list[WordTimestamp],
    clip_start: float,
    clip_end: float,
) -> list[tuple[float, float, str]]:
    """Group words into caption cues, with times relative to the clip start."""
    inside = [
        w for w in words
        if w.end > clip_start and w.start < clip_end and w.word.strip()
    ]
    cues: list[tuple[float, float, str]] = []
    group: list[WordTimestamp] = []

    def flush() -> None:
        if not group:
            return
        start = max(0.0, group[0].start - clip_start)
        end = max(start + 0.2, min(group[-1].end, clip_end) - clip_start)
        text = " ".join(w.word.strip() for w in group)
        cues.append((start, end, text))

    for word in inside:
        if group:
            span = word.end - group[0].start
            if len(group) >= WORDS_PER_CUE or span > MAX_CUE_SECONDS:
                flush()
                group = []
        group.append(word)
    flush()
    return cues


def write_ass_file(
    cues: list[tuple[float, float, str]],
    path: Path,
    width: int,
    height: int,
    *,
    hook_text: str | None = None,
    hook_duration: float = 3.5,
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

    lines.extend([
        f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Caption,,0,0,0,,{_ass_escape(t)}"
        for s, e, t in cues
        if _ass_escape(t)
    ])
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return path


class ClipRenderer:
    def __init__(self, aspect_ratio: str | None = None, enable_hook_banner: bool = True) -> None:
        self.aspect_ratio = aspect_ratio or settings.aspect_ratio
        self.enable_hook_banner = enable_hook_banner
        self.width, self.height = settings.resolve_dimensions(self.aspect_ratio)

    def _video_filter(self, has_captions: bool, ass_path: Path | None) -> str:
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
        if has_captions and ass_path is not None:
            base += f";[v]subtitles='{escape_filter_path(ass_path)}'[vout]"
        else:
            base += ";[v]null[vout]"
        return base

    def _audio_only_filter(self, has_captions: bool, ass_path: Path | None) -> str:
        w, h = self.width, self.height
        wave_h = int(h * 0.18)
        base = (
            f"[0:a]showwaves=s={w}x{wave_h}:mode=cline:rate=25:colors=0x6366F1[wave];"
            f"[1:v][wave]overlay=0:(H-h)/2:shortest=1,setsar=1[v]"
        )
        if has_captions and ass_path is not None:
            base += f";[v]subtitles='{escape_filter_path(ass_path)}'[vout]"
        else:
            base += ";[v]null[vout]"
        return base

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

        out_dir = output_dir or settings.render_dir
        out_dir.mkdir(parents=True, exist_ok=True)
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
        cues: list[tuple[float, float, str]] = []
        if settings.render_burn_captions or hook_text:
            if settings.render_burn_captions:
                cues = build_caption_cues(all_words, start, end)
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

        if has_video:
            filter_complex = self._video_filter(bool(ass_path), ass_path)
        else:
            # A synthetic background track for audio-only sources.
            args += [
                "-f", "lavfi",
                "-t", f"{duration:.3f}",
                "-i", f"color=c=0x0B0F19:s={self.width}x{self.height}:r=25",
            ]
            filter_complex = self._audio_only_filter(bool(ass_path), ass_path)

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
