"""Thin, explicit wrappers around the ffmpeg/ffprobe binaries.

Shared by audio extraction and clip rendering. Every failure raises with the
captured stderr attached -- the previous code discarded ffmpeg's stderr, which
is where the actual reason always lives.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from config.settings import settings
from src.errors import MissingDependencyError, PipelineError
from src.utils.logging_config import get_logger

log = get_logger(__name__)

FFMPEG_INSTALL_HINT = (
    "Install ffmpeg and ensure it is on PATH. "
    "Windows: `winget install Gyan.FFmpeg`  macOS: `brew install ffmpeg`  "
    "Debian/Ubuntu: `sudo apt install ffmpeg`"
)


def _find_binary(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found

    # Fallback for Windows if PATH environment variable has not refreshed in current shell session
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        executable = name if name.lower().endswith(".exe") else f"{name}.exe"
        winget_link = Path(local_app_data) / "Microsoft" / "WinGet" / "Links" / executable
        if winget_link.exists():
            return str(winget_link)
    return None


def ffmpeg_path() -> str:
    """Absolute path to ffmpeg, or raise MissingDependencyError."""
    found = _find_binary(settings.ffmpeg_binary)
    if not found:
        raise MissingDependencyError(f"ffmpeg ({settings.ffmpeg_binary})", FFMPEG_INSTALL_HINT)
    return found


def ffprobe_path() -> str:
    """Absolute path to ffprobe, or raise MissingDependencyError."""
    found = _find_binary(settings.ffprobe_binary)
    if not found:
        raise MissingDependencyError(f"ffprobe ({settings.ffprobe_binary})", FFMPEG_INSTALL_HINT)
    return found


def have_ffmpeg() -> bool:
    return _find_binary(settings.ffmpeg_binary) is not None


def run(
    args: list[str],
    *,
    error_cls: type[PipelineError],
    what: str,
    timeout: float | None = None,
    cwd: str | Path | None = None,
) -> subprocess.CompletedProcess:
    """Run a binary, raising `error_cls` with stderr included on failure.

    `cwd` lets the caller reference a file by bare name instead of by path.
    The renderer needs it because a path cannot be escaped into the subtitles
    filter once it contains an apostrophe; see `renderer.escape_filter_path`.
    Every other path in `args` must be absolute when `cwd` is set.
    """
    timeout = timeout if timeout is not None else settings.ffmpeg_timeout_sec
    log.debug("exec: %s", " ".join(args))
    try:
        proc = subprocess.run(
            args,
            check=False,
            capture_output=True,
            timeout=timeout,
            cwd=str(cwd) if cwd is not None else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise error_cls(
            f"{what} timed out after {timeout:.0f}s",
            "Raise FFMPEG_TIMEOUT_SEC, or use a shorter source file.",
        ) from exc

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        tail = "\n".join(stderr.splitlines()[-12:])
        raise error_cls(f"{what} failed (exit {proc.returncode}):\n{tail}")
    return proc


def _probe_duration_fallback(path: Path) -> float | None:
    try:
        proc = run(
            [ffmpeg_path(), "-i", str(path), "-f", "null", "-"],
            error_cls=PipelineError,
            what=f"ffmpeg fallback duration probe of {path.name}",
            timeout=60.0,
        )
        stderr_text = proc.stderr.decode("utf-8", errors="replace")
        matches = re.findall(r"time=(\d+):(\d+):(\d+\.\d+)", stderr_text)
        if matches:
            last = matches[-1]
            return int(last[0]) * 3600 + int(last[1]) * 60 + float(last[2])
    except Exception:
        pass
    return None


def probe_duration(media_path: str | Path) -> float:
    """Return real media duration in seconds.

    Replaces the previous hardcoded 1800.0 placeholder, which silently
    propagated a fake half-hour duration for every local file.
    """
    path = Path(media_path)
    if not path.exists():
        raise PipelineError(f"Cannot probe duration, file does not exist: {path}")

    proc = run(
        [
            ffprobe_path(),
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        error_cls=PipelineError,
        what=f"ffprobe duration of {path.name}",
        timeout=60.0,
    )
    raw = proc.stdout.decode("utf-8", errors="replace").strip()
    try:
        duration = float(raw)
    except ValueError as exc:
        fallback = _probe_duration_fallback(path)
        if fallback is not None and fallback > 0:
            duration = fallback
        else:
            raise PipelineError(
                f"ffprobe returned an unparseable duration for {path.name}: {raw!r}"
            ) from exc
    if duration <= 0:
        raise PipelineError(f"ffprobe reported non-positive duration for {path.name}: {duration}")
    return duration


def probe_has_video_stream(media_path: str | Path) -> bool:
    """True when the file carries at least one video stream (needed to render)."""
    proc = run(
        [
            ffprobe_path(),
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_type",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ],
        error_cls=PipelineError,
        what=f"ffprobe video stream of {Path(media_path).name}",
        timeout=60.0,
    )
    return "video" in proc.stdout.decode("utf-8", errors="replace")
