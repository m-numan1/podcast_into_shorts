"""Transcription: YouTube captions when available, otherwise local Whisper.

Two behaviour changes:

  * There is no hidden fallback transcript. When every backend fails this
    raises `TranscriptionError`. The original returned a hardcoded 8-segment
    script about AI startups, which is why the pipeline "worked" offline and
    why every keyword heuristic downstream was tuned to that script.

  * YouTube ID extraction is host-anchored. The old regex `(?:v=|/)([\\w-]{11})`
    matched ordinary file paths -- `/home/user/episode_042.mp3` yielded the
    "video id" `episode_042` and triggered a bogus API call.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from config.settings import settings
from src.errors import MissingDependencyError, TranscriptionError
from src.schema.clips import TranscriptSegment, WordTimestamp
from src.utils.logging_config import get_logger
from src.utils.text_cleaner import clean_transcript_text

log = get_logger(__name__)


YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "music.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com",
}
YOUTUBE_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
VIDEO_ID_RE = re.compile(r"^[0-9A-Za-z_-]{11}$")
# Path prefixes that carry the id as the next path element.
ID_BEARING_PREFIXES = ("shorts", "embed", "live", "v")

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "demo_transcript.json"


@dataclass(frozen=True)
class TranscriptResult:
    """Segments plus where they came from, so provenance is never guessed."""

    segments: list[TranscriptSegment]
    source: str  # "youtube_captions" | "whisper" | "fixture"


def extract_youtube_id(source: str) -> str:
    """Return an 11-character YouTube video id, or "" if this is not a
    YouTube URL. Host-anchored: never matches local paths or other domains."""
    if not source:
        return ""
    try:
        parsed = urlparse(source)
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https"):
        return ""

    host = (parsed.netloc or "").lower().split(":")[0]
    parts = [p for p in (parsed.path or "").split("/") if p]

    if host in YOUTUBE_SHORT_HOSTS:
        candidate = parts[0] if parts else ""
        return candidate if VIDEO_ID_RE.match(candidate) else ""

    if host in YOUTUBE_HOSTS:
        # /watch?v=<id>
        vals = parse_qs(parsed.query or "").get("v", [])
        if vals and VIDEO_ID_RE.match(vals[0]):
            return vals[0]
        # /shorts/<id>, /embed/<id>, /live/<id>, /v/<id>
        if len(parts) >= 2 and parts[0].lower() in ID_BEARING_PREFIXES:
            return parts[1] if VIDEO_ID_RE.match(parts[1]) else ""
    return ""


@lru_cache(maxsize=2)
def _load_whisper_model(name: str):
    """Load and cache a Whisper model.

    The original called `whisper.load_model("base")` inside the transcribe
    method, reloading ~140 MB of weights on every invocation.
    """
    try:
        import whisper  # type: ignore[import-untyped,import-not-found]
    except ImportError as exc:
        raise MissingDependencyError(
            "openai-whisper",
            "pip install openai-whisper  (also requires torch and ffmpeg)",
        ) from exc
    log.info("Loading Whisper model %r (first call only)", name)
    return whisper.load_model(name)



class TranscriberProvider:

    def transcribe(
        self,
        audio_path: str | None,
        *,
        source_url: str | None = None,
    ) -> TranscriptResult:
        """Produce a timestamped transcript.

        Tries YouTube captions (fast, free) then Whisper. Raises
        `TranscriptionError` if neither yields segments -- it never invents one.
        """
        attempts: list[str] = []

        video_id = extract_youtube_id(source_url or "")
        if video_id:
            try:
                segments = self._from_youtube_captions(video_id)
                if segments:
                    log.info("Using YouTube captions (%d segments)", len(segments))
                    return TranscriptResult(segments, "youtube_captions")
                attempts.append("youtube_captions: returned no usable segments")
            except MissingDependencyError as exc:
                attempts.append(f"youtube_captions: {exc}")
                log.warning("YouTube captions unavailable: %s", exc)
            except Exception as exc:
                attempts.append(f"youtube_captions: {type(exc).__name__}: {exc}")
                log.warning("YouTube caption fetch failed: %s: %s", type(exc).__name__, exc)

        if audio_path and Path(audio_path).exists():
            try:
                segments = self._from_whisper(audio_path)
                if segments:
                    log.info("Using Whisper transcript (%d segments)", len(segments))
                    return TranscriptResult(segments, "whisper")
                attempts.append("whisper: produced no segments")
            except MissingDependencyError as exc:
                attempts.append(f"whisper: {exc}")
                log.warning("Whisper unavailable: %s", exc)
            except Exception as exc:
                attempts.append(f"whisper: {type(exc).__name__}: {exc}")
                log.warning("Whisper transcription failed: %s: %s", type(exc).__name__, exc)
        else:
            attempts.append(f"whisper: no readable audio file at {audio_path!r}")

        raise TranscriptionError(
            "Could not transcribe the source. Attempts:\n  - " + "\n  - ".join(attempts),
            "Install openai-whisper for local transcription, or use a YouTube URL "
            "that has captions. Run with --demo to exercise the pipeline on the "
            "bundled fixture transcript instead.",
        )

    # ------------------------------------------------------------- fixture

    def load_fixture(self) -> TranscriptResult:
        """Load the bundled demo transcript.

        Only reachable via an explicit `--demo` flag. Results built from it are
        stamped `transcript_source="fixture"` all the way to the JSON output.
        """
        if not FIXTURE_PATH.exists():
            raise TranscriptionError(f"Demo fixture missing at {FIXTURE_PATH}")
        raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        segments = [
            self._build_segment(
                idx=i + 1,
                start=float(item["start"]),
                end=float(item["end"]),
                speaker=item.get("speaker", "Speaker_1"),
                text=clean_transcript_text(item["text"]),
            )
            for i, item in enumerate(raw["segments"])
            if clean_transcript_text(item["text"])
        ]
        log.warning(
            "DEMO MODE: using bundled fixture transcript (%d segments). "
            "Output is synthetic and must not be treated as a real analysis.",
            len(segments),
        )
        return TranscriptResult(segments, "fixture")

    # ------------------------------------------------------------ backends

    def _from_youtube_captions(self, video_id: str) -> list[TranscriptSegment]:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError as exc:
            raise MissingDependencyError(
                "youtube-transcript-api", "pip install youtube-transcript-api"
            ) from exc

        raw = self._fetch_captions(YouTubeTranscriptApi, video_id)
        segments: list[TranscriptSegment] = []
        for item in raw:
            raw_text = str(self._field(item, "text", "") or "").replace("\n", " ").strip()
            text = clean_transcript_text(raw_text)
            if not text:
                continue
            start_val = self._field(item, "start", 0.0)
            dur_val = self._field(item, "duration", 0.0)
            start = float(start_val) if start_val is not None else 0.0
            duration = float(dur_val) if dur_val is not None else 0.0
            # Caption cues carry no reliable end time; clamp to a sane minimum
            # rather than the old blanket `max(duration, 2.0)`.
            end = start + max(duration, 0.5)
            speaker = self._guess_speaker(segments)
            segments.append(
                self._build_segment(len(segments) + 1, start, end, speaker, text)
            )
        return segments

    @staticmethod
    def _fetch_captions(api_cls, video_id: str):
        """Support both youtube-transcript-api v1.x and v0.6.x call shapes."""
        errors = []
        try:
            return api_cls().fetch(video_id)  # v1.x instance API
        except AttributeError as exc:
            errors.append(f"v1 fetch: {exc}")
        except Exception as exc:
            errors.append(f"v1 fetch: {type(exc).__name__}: {exc}")
        try:
            return api_cls.get_transcript(video_id)  # v0.6.x classmethod
        except Exception as exc:
            errors.append(f"v0 get_transcript: {type(exc).__name__}: {exc}")
        raise TranscriptionError(
            f"No caption track retrievable for video {video_id}: " + "; ".join(errors)
        )

    def _from_whisper(self, audio_path: str) -> list[TranscriptSegment]:
        model = _load_whisper_model(settings.whisper_model)
        log.info("Transcribing with Whisper (%s); this can take a while.", settings.whisper_model)
        result = model.transcribe(
            audio_path,
            word_timestamps=True,
            language=settings.transcript_language,
            verbose=False,
        )
        segments: list[TranscriptSegment] = []
        for idx, seg in enumerate(result.get("segments", [])):
            words = [
                WordTimestamp(
                    word=clean_transcript_text(w.get("word", "")).strip(),
                    start=float(w.get("start", 0.0) or 0.0),
                    end=float(w.get("end", 0.0) or 0.0),
                    confidence=float(w.get("probability", 1.0) or 1.0),
                )
                for w in seg.get("words", [])
                if clean_transcript_text(w.get("word", "")).strip()
            ]
            raw_text = (seg.get("text") or "").strip()
            text = clean_transcript_text(raw_text)
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    id=idx + 1,
                    start=float(seg.get("start", 0.0) or 0.0),
                    end=float(seg.get("end", 0.0) or 0.0),
                    text=text,
                    # Whisper does not diarize. Label honestly instead of
                    # alternating "Host"/"Guest" by segment index, which the
                    # original did and which is indistinguishable from a guess.
                    speaker="Speaker_unknown",
                    words=words,
                )
            )
        return segments

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _field(item, name: str, default):
        if isinstance(item, dict):
            val = item.get(name, default)
        else:
            val = getattr(item, name, default)
        return default if val is None else val


    @staticmethod
    def _guess_speaker(previous: list[TranscriptSegment]) -> str:
        """Heuristic turn-taking label for caption tracks, which carry no
        speaker data. Named `Speaker_A`/`Speaker_B` rather than `Host`/`Guest`
        so nobody mistakes it for real diarization."""
        if not previous:
            return "Speaker_A"
        prev = previous[-1]
        looks_like_turn_change = prev.text.rstrip().endswith("?")
        if looks_like_turn_change:
            return "Speaker_B" if prev.speaker == "Speaker_A" else "Speaker_A"
        return prev.speaker

    @staticmethod
    def _build_segment(
        idx: int, start: float, end: float, speaker: str, text: str
    ) -> TranscriptSegment:
        """Build a segment, interpolating word timings evenly.

        Interpolation is only a placeholder for caption/fixture input, which
        has no word data. Whisper supplies real per-word times.
        """
        word_list = text.split()
        span = max(end - start, 0.01)
        per_word = span / max(len(word_list), 1)
        words = [
            WordTimestamp(
                word=w,
                start=round(start + i * per_word, 3),
                end=round(start + (i + 1) * per_word, 3),
                # Flag interpolation so downstream code can prefer real timings.
                confidence=0.5,
            )
            for i, w in enumerate(word_list)
        ]
        return TranscriptSegment(
            id=idx, start=round(start, 3), end=round(end, 3),
            text=text, speaker=speaker, words=words,
        )
