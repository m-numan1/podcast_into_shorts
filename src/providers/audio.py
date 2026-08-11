"""Audio extraction for transcription and acoustic analysis.

Behaviour change: extraction failure now raises. The original silently returned
the *input* path when ffmpeg was missing or failed, so a 42-byte placeholder
was handed to the transcriber as if it were audio.
"""

from __future__ import annotations

from pathlib import Path

from config.settings import settings
from src.errors import AudioExtractionError, PipelineError
from src.providers import ffmpeg_tools
from src.utils.logging_config import get_logger

log = get_logger(__name__)

# 16 kHz mono PCM is what Whisper expects.
TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1


class AudioProcessorProvider:
    def extract_audio(self, media_path: str, *, force: bool = False) -> str:
        """Extract 16 kHz mono WAV from `media_path` and return its path.

        Raises:
            AudioExtractionError: ffmpeg failed or produced unusable output.
            MissingDependencyError: ffmpeg is not installed.
        """
        in_path = Path(media_path)
        if not in_path.exists():
            raise AudioExtractionError(f"Media file does not exist: {in_path}")

        out_path = settings.cache_dir / f"{in_path.stem}_16k_mono.wav"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if not force and self._is_usable(out_path):
            log.info("Reusing cached audio: %s", out_path.name)
            return str(out_path.resolve())

        # ffmpeg_path() raises MissingDependencyError with an install hint,
        # rather than printing a warning and carrying on.
        binary = ffmpeg_tools.ffmpeg_path()
        log.info("Extracting audio from %s", in_path.name)
        ffmpeg_tools.run(
            [
                binary, "-y",
                "-i", str(in_path),
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", str(TARGET_SAMPLE_RATE),
                "-ac", str(TARGET_CHANNELS),
                str(out_path),
            ],
            error_cls=AudioExtractionError,
            what=f"audio extraction from {in_path.name}",
        )

        if not self._is_usable(out_path):
            raise AudioExtractionError(
                f"ffmpeg exited cleanly but {out_path.name} is not decodable audio.",
                "The source may have no audio stream.",
            )

        log.info("Audio ready: %s", out_path.name)
        return str(out_path.resolve())

    @staticmethod
    def _is_usable(path: Path) -> bool:
        """Validate by probing, not by file size.

        The original used `size > 1000` as a proxy for validity, which both
        accepted truncated garbage and rejected legitimately tiny clips.
        """
        if not path.exists() or path.stat().st_size == 0:
            return False
        try:
            return ffmpeg_tools.probe_duration(path) > 0
        except PipelineError:
            return False

    def measure_silences(
        self, audio_path: str, noise_db: float = -32.0, min_silence: float = 0.35
    ) -> list[tuple[float, float]]:
        """Detect silent intervals via ffmpeg's silencedetect filter.

        Returns a list of (start, end) seconds. Used to place cuts inside
        natural pauses instead of guessing a fixed offset. The original
        hardcoded `silence_duration_sec = 0.4` for every chunk and never
        looked at the audio at all.
        """
        binary = ffmpeg_tools.ffmpeg_path()
        proc = ffmpeg_tools.run(
            [
                binary, "-hide_banner", "-nostats",
                "-i", str(audio_path),
                "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
                "-f", "null", "-",
            ],
            error_cls=AudioExtractionError,
            what=f"silence detection on {Path(audio_path).name}",
        )
        # silencedetect writes to stderr.
        stderr = proc.stderr.decode("utf-8", errors="replace")
        silences: list[tuple[float, float]] = []
        pending_start: float | None = None
        for line in stderr.splitlines():
            if "silence_start:" in line:
                try:
                    pending_start = float(line.split("silence_start:")[1].strip().split()[0])
                except (IndexError, ValueError):
                    pending_start = None
            elif "silence_end:" in line and pending_start is not None:
                try:
                    end = float(line.split("silence_end:")[1].strip().split()[0])
                    silences.append((pending_start, end))
                except (IndexError, ValueError):
                    log.debug("Unparseable silence_end line from ffmpeg: %r", line)
                pending_start = None
        log.debug("Detected %d silent intervals", len(silences))
        return silences
