"""§3: no stage may invent data to hide a failure.

In the original, a failed download wrote a 42-byte placeholder file, audio
extraction returned the input path when ffmpeg was missing, transcription
returned a hardcoded script about AI startups, and the LLM provider returned a
fixed `overall_score: 8.8`. Chained together, a completely failed run printed
full "publish-ready" clips and "[SUCCESS]".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.errors import (
    AudioExtractionError,
    DownloadError,
    LLMError,
    MissingDependencyError,
    TranscriptionError,
)
from src.providers.audio import AudioProcessorProvider
from src.providers.downloader import MediaDownloaderProvider
from src.providers.llm import LLMProvider
from src.providers.transcriber import TranscriberProvider
from src.schema.state import EditorState


class TestDownloaderNeverFabricates:
    def test_empty_source_raises(self):
        with pytest.raises(DownloadError, match="No source provided"):
            MediaDownloaderProvider().download("")

    def test_nonexistent_path_raises(self):
        with pytest.raises(DownloadError, match="neither an existing file"):
            MediaDownloaderProvider().download("/definitely/not/here/ep.mp3")

    def test_garbage_source_raises(self):
        with pytest.raises(DownloadError):
            MediaDownloaderProvider().download("not a url or a path")

    def test_directory_source_raises(self, tmp_path):
        with pytest.raises(DownloadError, match="directory"):
            MediaDownloaderProvider().download(str(tmp_path))

    def test_empty_file_raises(self, tmp_path):
        empty = tmp_path / "silent.mp3"
        empty.write_bytes(b"")
        with pytest.raises(DownloadError, match="empty"):
            MediaDownloaderProvider().download(str(empty))

    def test_no_placeholder_file_is_created_on_failure(self, tmp_path, monkeypatch):
        """The original wrote b'MOCK_AUDIO_DATA_FOR_PODCAST_EDITOR_TESTING'."""
        from config.settings import settings

        monkeypatch.setattr(settings, "cache_dir", tmp_path)
        with pytest.raises(DownloadError):
            MediaDownloaderProvider().download("/nope/missing.mp3")
        assert list(tmp_path.iterdir()) == []

    def test_the_old_mock_payload_appears_nowhere_in_the_codebase(self):
        root = Path(__file__).resolve().parent.parent
        needle = "MOCK_AUDIO_DATA"
        offenders = [
            path
            for path in root.rglob("*.py")
            if ".git" not in path.parts
            and "tests" not in path.parts
            and needle in path.read_text(encoding="utf-8", errors="ignore")
        ]
        assert offenders == []


class TestAudioNeverFabricates:
    def test_missing_media_raises(self):
        with pytest.raises(AudioExtractionError, match="does not exist"):
            AudioProcessorProvider().extract_audio("/nope/missing.mp4")

    def test_does_not_return_the_input_path_on_failure(self, tmp_path):
        """The original returned the *input* path when ffmpeg failed, so a
        placeholder file flowed onward as though it were extracted audio."""
        bogus = tmp_path / "not_really_media.mp4"
        bogus.write_bytes(b"this is not a media container")
        with pytest.raises((AudioExtractionError, MissingDependencyError)):
            AudioProcessorProvider().extract_audio(str(bogus))


class TestTranscriberNeverFabricates:
    def test_no_backend_available_raises(self):
        with pytest.raises(TranscriptionError, match="Could not transcribe"):
            TranscriberProvider().transcribe(None, source_url=None)

    def test_missing_audio_file_raises(self):
        with pytest.raises(TranscriptionError):
            TranscriberProvider().transcribe("/nope/missing.wav", source_url=None)

    def test_error_message_lists_what_was_attempted(self):
        with pytest.raises(TranscriptionError) as exc:
            TranscriberProvider().transcribe("/nope/missing.wav", source_url=None)
        assert "whisper" in str(exc.value).lower()

    def test_fixture_is_only_reachable_explicitly(self):
        """`load_fixture` must be the only route to the sample transcript."""
        result = TranscriberProvider().load_fixture()
        assert result.source == "fixture"
        assert len(result.segments) == 8

    def test_fixture_is_not_returned_by_transcribe(self):
        with pytest.raises(TranscriptionError):
            TranscriberProvider().transcribe(None, source_url=None)

    def test_sample_transcript_is_not_hardcoded_in_the_provider(self):
        """It lived inline in transcriber.py and was returned on any failure."""
        source = Path("src/providers/transcriber.py").read_text(encoding="utf-8")
        assert "99% of AI startups" not in source
        assert "_generate_sample_podcast_transcript" not in source

    def test_fixture_file_declares_itself_synthetic(self):
        data = json.loads(
            Path("src/fixtures/demo_transcript.json").read_text(encoding="utf-8")
        )
        assert "SYNTHETIC" in data["_comment"].upper()


class TestLLMNeverFabricates:
    def test_heuristic_provider_is_not_available_for_model_calls(self):
        provider = LLMProvider(provider="heuristic")
        assert not provider.available

    def test_generate_raises_rather_than_returning_a_canned_score(self):
        with pytest.raises(LLMError, match="cannot make model calls"):
            LLMProvider(provider="heuristic").generate("rate this clip")

    def test_structured_generate_raises(self):
        from src.schema.clips import LLMClipVerdict

        with pytest.raises(LLMError):
            LLMProvider(provider="heuristic").generate_structured(
                "rate this", LLMClipVerdict
            )

    def test_openai_without_a_key_raises(self, monkeypatch):
        from config.settings import settings

        monkeypatch.setattr(settings, "openai_api_key", "")
        with pytest.raises((LLMError, MissingDependencyError)):
            LLMProvider(provider="openai").generate("hello")

    def test_the_canned_fallback_is_gone(self):
        """No `_structured_fallback` function, and no hardcoded score literal.

        Identifier/literal level rather than substring, because the module
        docstring names the removed function deliberately.
        """
        from tests.conftest import code_identifiers, code_string_literals

        assert "_structured_fallback" not in code_identifiers("src/providers/llm.py")
        literals = code_string_literals("src/providers/llm.py")
        assert not any("8.8" in text for text in literals)
        assert not any("High-impact narrative shift" in text for text in literals)


class TestFailedRunsAreNotLabelledFixture:
    """A run that failed before node 3 is not synthetic fixture data.

    `provenance()` defaulted both sources to "fixture" when they were unset.
    Those fields are None until the stage that sets them succeeds, so any run
    that failed early stamped itself SYNTHETIC FIXTURE DATA -- a real local MP4
    that failed at transcription printed "these results describe a bundled
    fixture, not real media". That is exactly the mislabelling the provenance
    record exists to prevent.
    """

    def test_unset_sources_report_unavailable_not_fixture(self):
        state = EditorState(source="episode.mp3", error="boom", failed_stage="download")
        provenance = state.provenance()

        assert provenance.media_source == "unavailable"
        assert provenance.transcript_source == "unavailable"
        assert not provenance.is_synthetic
        assert "SYNTHETIC" not in provenance.banner()

    def test_a_real_source_that_failed_later_keeps_its_real_media_source(self):
        """Node 1 succeeded, node 3 did not. Only the transcript is unknown."""
        state = EditorState(
            source="episode.mp4",
            media_source="local_file",
            error="no transcription backend",
            failed_stage="transcribe",
        )
        provenance = state.provenance()

        assert provenance.media_source == "local_file"
        assert provenance.transcript_source == "unavailable"
        assert not provenance.is_synthetic

    def test_demo_mode_is_still_labelled_fixture(self):
        state = EditorState(
            demo_mode=True, media_source="fixture", transcript_source="fixture"
        )
        provenance = state.provenance()

        assert provenance.is_synthetic
        assert "SYNTHETIC FIXTURE DATA" in provenance.banner()
