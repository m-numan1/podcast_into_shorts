"""Media acquisition: local file validation or yt-dlp download.

Behaviour change from the original: this provider no longer writes a 42-byte
placeholder file and returns it as if the download had worked. A failed
download raises `DownloadError`. That single fabricated file was what allowed a
completely failed run to reach the end of the pipeline and print "[SUCCESS]".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from config.settings import settings
from src.errors import DownloadError, MissingDependencyError, PipelineError
from src.providers import ffmpeg_tools
from src.utils.logging_config import get_logger

log = get_logger(__name__)

# Extensions we accept as directly-usable local media.
MEDIA_SUFFIXES = {
    ".mp3", ".mp4", ".wav", ".m4a", ".aac", ".flac", ".opus", ".ogg",
    ".webm", ".mkv", ".mov", ".avi", ".wma", ".aiff",
}


@dataclass(frozen=True)
class MediaInfo:
    """Result of acquiring media. `duration` is always real, never assumed."""

    title: str
    file_path: str
    duration: float
    media_source: str  # "local_file" | "youtube_download"
    has_video: bool
    url: str | None = None


def is_url(source: str) -> bool:
    """True for http/https URLs. Replaces `source.startswith("http")`, which
    also matched paths and strings like "httpfoo"."""
    try:
        parsed = urlparse(source)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


class MediaDownloaderProvider:
    def download(self, source: str) -> MediaInfo:
        """Acquire media from a local path or a remote URL.

        Raises:
            DownloadError: source is unusable, unreachable, or produced no file.
        """
        if not source or not source.strip():
            raise DownloadError(
                "No source provided.",
                "Pass --source with a YouTube URL or a local media file path.",
            )
        source = source.strip()

        path = Path(source)
        if path.exists():
            if path.is_dir():
                raise DownloadError(
                    f"Source is a directory, not a media file: {path}",
                    "Point --source at a single audio or video file.",
                )
            return self._local_file(path)

        if is_url(source):
            return self._remote(source)

        raise DownloadError(
            f"Source is neither an existing file nor an http(s) URL: {source!r}",
            "Check the path for typos, or pass a full https:// URL.",
        )

    # ---------------------------------------------------------------- local

    def _local_file(self, path: Path) -> MediaInfo:
        if path.suffix.lower() not in MEDIA_SUFFIXES:
            log.warning(
                "Unrecognised media extension %r; attempting to probe anyway.",
                path.suffix,
            )
        if path.stat().st_size == 0:
            raise DownloadError(f"Local media file is empty: {path}")

        resolved = str(path.resolve())
        try:
            duration = ffmpeg_tools.probe_duration(resolved)
            has_video = ffmpeg_tools.probe_has_video_stream(resolved)
        except MissingDependencyError:
            raise
        except PipelineError as exc:
            raise DownloadError(
                f"Could not read media properties from {path.name}: {exc}",
                "The file may be corrupt or not a media container.",
            ) from exc

        log.info("Local media: %s (%.1fs, video=%s)", path.name, duration, has_video)
        return MediaInfo(
            title=path.stem,
            file_path=resolved,
            duration=duration,
            media_source="local_file",
            has_video=has_video,
        )

    # --------------------------------------------------------------- remote

    def _remote(self, url: str) -> MediaInfo:
        try:
            import yt_dlp
        except ImportError as exc:
            raise MissingDependencyError("yt-dlp", "pip install yt-dlp") from exc

        outtmpl = str(settings.cache_dir / "%(id)s.%(ext)s")
        ydl_opts = {
            # Prefer a real video stream when present so the render node has
            # pixels to work with; fall back to audio-only.
            "format": "bestvideo[height<=1080]+bestaudio/best/bestaudio",
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            # Was True. It converted hard failures into silent empty results,
            # which then fed the placeholder-file path.
            "ignoreerrors": False,
            "noplaylist": True,
            "retries": 3,
            "extractor_args": {
                "youtube": {
                    "player_client": ["mweb", "android", "web"]
                }
            },
        }
        if getattr(settings, "ytdlp_cookies_from_browser", None):
            ydl_opts["cookiesfrombrowser"] = settings.ytdlp_cookies_from_browser
        if getattr(settings, "ytdlp_cookies_file", None):
            ydl_opts["cookiefile"] = str(settings.ytdlp_cookies_file)

        log.info("Downloading %s", url)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Single call with download=True. The original called
                # extract_info twice, doubling the network round-trip.
                info = ydl.extract_info(url, download=True)
                if not info:
                    raise DownloadError(f"yt-dlp returned no metadata for {url}")
                file_path = self._resolve_downloaded_path(ydl, info)
        except DownloadError:
            raise
        except Exception as exc:
            # yt_dlp raises many private exception types; report the reason
            # rather than swallowing it as the original did.
            raise DownloadError(
                f"Download failed for {url}: {type(exc).__name__}: {exc}",
                "Check the URL is public and reachable, and that yt-dlp is current "
                "(`pip install -U yt-dlp`).",
            ) from exc

        if not file_path.exists() or file_path.stat().st_size == 0:
            raise DownloadError(
                f"yt-dlp reported success but produced no usable file at {file_path}"
            )

        title = info.get("title") or "Downloaded Episode"
        # Trust ffprobe over metadata; container duration is authoritative.
        try:
            duration = ffmpeg_tools.probe_duration(file_path)
        except PipelineError:
            meta_duration = info.get("duration")
            if not meta_duration:
                raise DownloadError(
                    f"Could not determine duration for {file_path.name}"
                ) from None
            duration = float(meta_duration)
            log.warning("ffprobe failed; using yt-dlp metadata duration %.1fs", duration)

        try:
            has_video = ffmpeg_tools.probe_has_video_stream(file_path)
        except PipelineError:
            has_video = False

        log.info("Downloaded %r (%.1fs, video=%s)", title, duration, has_video)
        return MediaInfo(
            title=title,
            file_path=str(file_path.resolve()),
            duration=duration,
            media_source="youtube_download",
            has_video=has_video,
            url=url,
        )

    @staticmethod
    def _resolve_downloaded_path(ydl: Any, info: Any) -> Path:
        """Find the file yt-dlp actually wrote.

        `requested_downloads[].filepath` is authoritative post-processing;
        `prepare_filename` only predicts the pre-processing name. The original
        fabricated `<id>.mp3` on failure, producing a path that did not exist.
        """
        for entry in info.get("requested_downloads") or []:
            candidate = entry.get("filepath") or entry.get("_filename")
            if candidate:
                return Path(candidate)
        return Path(ydl.prepare_filename(info))
