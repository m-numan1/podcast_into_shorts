"""Transcription: YouTube captions when available, otherwise local Whisper.

Local transcription runs on faster-whisper (CTranslate2), which needs neither
openai-whisper nor torch. Same models, same word-level timestamps, a fraction
of the install size and several times faster on CPU.

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
    """Load and cache a faster-whisper model.

    Cached because the original called `load_model` inside the transcribe
    method, reloading the weights on every invocation.

    `device="auto"` picks CUDA when it is available and CPU otherwise;
    `compute_type="auto"` then picks the fastest precision that device
    supports (int8 on a typical CPU, float16 on a GPU). Neither needs a
    setting, and neither needs torch -- faster-whisper runs on CTranslate2.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise MissingDependencyError(
            "faster-whisper",
            "pip install faster-whisper  (also requires ffmpeg)",
        ) from exc
    log.info("Loading faster-whisper model %r (first call only)", name)
    return WhisperModel(name, device="auto", compute_type="auto")



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
            "Install faster-whisper for local transcription, or use a YouTube URL "
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
        """Support both youtube-transcript-api v1.x and v0.6.x call shapes with multilingual fallback."""
        target_lang = settings.transcript_language
        preferred_langs = [target_lang] if target_lang else ["en"]
        errors = []

        # 1. Try v1.x transcript listing & intelligent language selection
        try:
            api = api_cls() if callable(api_cls) else api_cls
            if hasattr(api, "list"):
                transcript_list = api.list(video_id)
                transcript = None
                try:
                    transcript = transcript_list.find_transcript(preferred_langs)
                except Exception:
                    # Fallback to any available transcript (prefer manual over generated)
                    manual = [t for t in transcript_list if not getattr(t, "is_generated", False)]
                    if manual:
                        transcript = manual[0]
                    else:
                        generated = [t for t in transcript_list if getattr(t, "is_generated", False)]
                        if generated:
                            transcript = generated[0]
                        else:
                            transcript = next(iter(transcript_list), None)

                if transcript is not None:
                    log.info(
                        "Found YouTube caption track: language=%s (%s, generated=%s)",
                        getattr(transcript, "language", "unknown"),
                        getattr(transcript, "language_code", "?"),
                        getattr(transcript, "is_generated", False),
                    )
                    return transcript.fetch()
        except AttributeError as exc:
            errors.append(f"v1 list: {exc}")
        except Exception as exc:
            errors.append(f"v1 list: {type(exc).__name__}: {exc}")

        # 2. Try v0.6.x list_transcripts if available
        try:
            if hasattr(api_cls, "list_transcripts"):
                transcript_list = api_cls.list_transcripts(video_id)
                transcript = None
                try:
                    transcript = transcript_list.find_transcript(preferred_langs)
                except Exception:
                    transcript = next(iter(transcript_list), None)
                if transcript is not None:
                    return transcript.fetch()
        except Exception as exc:
            errors.append(f"v0 list_transcripts: {type(exc).__name__}: {exc}")

        # 3. Direct fetch attempts
        try:
            api = api_cls() if callable(api_cls) else api_cls
            if hasattr(api, "fetch"):
                return api.fetch(video_id, languages=preferred_langs)
        except Exception as exc:
            errors.append(f"v1 direct fetch: {type(exc).__name__}: {exc}")

        try:
            if hasattr(api_cls, "get_transcript"):
                return api_cls.get_transcript(video_id, languages=preferred_langs)
        except Exception as exc:
            errors.append(f"v0 get_transcript: {type(exc).__name__}: {exc}")

        raise TranscriptionError(
            f"No caption track retrievable for video {video_id}: " + "; ".join(errors)
        )


    def _from_whisper(self, audio_path: str) -> list[TranscriptSegment]:
        model = _load_whisper_model(settings.whisper_model)
        language = settings.transcript_language or None
        log.info(
            "Transcribing with faster-whisper (%s, language=%s); this can take a while.",
            settings.whisper_model, language or "auto-detect",
        )
        # faster-whisper returns (generator, info). Nothing is decoded until the
        # generator is consumed, so `info` is read first for the log line and
        # the segments are iterated below.
        raw_segments, info = model.transcribe(
            audio_path,
            word_timestamps=True,
            language=language,
        )
        log.info(
            "Detected language %r (probability %.2f), audio duration %.1fs",
            info.language, info.language_probability, info.duration,
        )

        segments: list[TranscriptSegment] = []
        for idx, seg in enumerate(raw_segments):
            # sentence_case=False: these are individual words, not sentences.
            # Capitalising each one rendered every burned caption as
            # "The Quick Brown Fox" and turned "iPhone" into "IPhone".
            words = [
                WordTimestamp(
                    word=clean_transcript_text(w.word, sentence_case=False).strip(),
                    start=float(w.start or 0.0),
                    end=float(w.end or 0.0),
                    confidence=float(w.probability if w.probability is not None else 1.0),
                )
                for w in (seg.words or [])
                if clean_transcript_text(w.word, sentence_case=False).strip()
            ]
            text = clean_transcript_text((seg.text or "").strip())
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    id=idx + 1,
                    start=float(seg.start or 0.0),
                    end=float(seg.end or 0.0),
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
        val = (
            item.get(name, default)
            if isinstance(item, dict)
            else getattr(item, name, default)
        )
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
