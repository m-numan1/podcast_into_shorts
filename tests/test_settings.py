"""Settings validation.

The original used a plain BaseModel with manual os.getenv defaults, no
validation, and an `embedding_dim` of 384 sitting next to
`embedding_model="text-embedding-3-small"` (which emits 1536).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.settings import EMBEDDING_DIMS, Settings


class TestEmbeddingDimensionDerivation:
    def test_lexical_backend_dim(self):
        assert Settings(embedding_backend="lexical").embedding_dim == \
               EMBEDDING_DIMS["lexical"]

    def test_openai_dim_matches_the_model(self):
        s = Settings(
            embedding_backend="openai",
            embedding_model="text-embedding-3-small",
            openai_api_key="sk-test",
        )
        assert s.embedding_dim == 1536

    def test_large_model_dim(self):
        s = Settings(
            embedding_backend="openai",
            embedding_model="text-embedding-3-large",
            openai_api_key="sk-test",
        )
        assert s.embedding_dim == 3072

    def test_dim_cannot_be_set_to_contradict_the_model(self):
        """Passing an explicit value must not survive; it is always derived."""
        s = Settings(
            embedding_backend="openai",
            embedding_model="text-embedding-3-small",
            embedding_dim=384,
            openai_api_key="sk-test",
        )
        assert s.embedding_dim == 1536

    def test_unknown_model_is_rejected(self):
        with pytest.raises(ValidationError, match="Unknown embedding model"):
            Settings(embedding_backend="openai", embedding_model="made-up-model")


class TestClipConstraints:
    def test_min_must_be_below_max(self):
        with pytest.raises(ValidationError, match="must be less than"):
            Settings(min_clip_duration_sec=100.0, max_clip_duration_sec=90.0)

    def test_equal_durations_rejected(self):
        with pytest.raises(ValidationError):
            Settings(min_clip_duration_sec=60.0, max_clip_duration_sec=60.0)

    def test_target_min_cannot_exceed_max(self):
        with pytest.raises(ValidationError, match="must not"):
            Settings(target_clip_count_min=20, target_clip_count_max=5)

    def test_segment_max_must_exceed_min(self):
        with pytest.raises(ValidationError, match="segment_max_duration_sec"):
            Settings(segment_min_duration_sec=100.0, segment_max_duration_sec=50.0)

    def test_negative_durations_rejected(self):
        with pytest.raises(ValidationError):
            Settings(min_clip_duration_sec=-5.0)


class TestScoringWeights:
    def test_default_weights_sum_to_one(self):
        s = Settings()
        total = (s.weight_hook + s.weight_comment_potential + s.weight_educational
                 + s.weight_retention + s.weight_story)
        assert total == pytest.approx(1.0)

    def test_weights_that_do_not_sum_to_one_are_rejected(self):
        with pytest.raises(ValidationError, match="must sum to 1.0"):
            Settings(weight_hook=0.9)


class TestProviderKeyConsistency:
    def test_openai_requires_a_key(self):
        with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
            Settings(default_llm_provider="openai", openai_api_key="")

    def test_gemini_requires_a_key(self):
        with pytest.raises(ValidationError, match="GEMINI_API_KEY"):
            Settings(default_llm_provider="gemini", gemini_api_key="")

    def test_openai_with_a_key_is_accepted(self):
        s = Settings(default_llm_provider="openai", openai_api_key="sk-test")
        assert s.uses_llm
        assert s.active_model_name == s.default_model

    def test_heuristic_needs_no_key(self):
        s = Settings(default_llm_provider="heuristic")
        assert not s.uses_llm
        assert s.active_model_name == "heuristic"

    def test_invalid_provider_is_rejected(self):
        with pytest.raises(ValidationError):
            Settings(default_llm_provider="telepathy")

    def test_gemini_reports_its_own_model(self):
        s = Settings(default_llm_provider="gemini", gemini_api_key="key")
        assert s.active_model_name == s.gemini_model


class TestBoundedFields:
    @pytest.mark.parametrize("field,value", [
        ("llm_temperature", -1.0),
        ("llm_temperature", 3.0),
        ("render_crf", 60),
        ("llm_max_concurrency", 0),
        ("dedup_overlap_threshold", 1.5),
        ("candidate_shortlist_size", 0),
    ])
    def test_out_of_range_values_rejected(self, field, value):
        with pytest.raises(ValidationError):
            Settings(**{field: value})


class TestNoImportSideEffects:
    def test_directories_are_not_created_on_import(self, tmp_path):
        """The original called ensure_directories() at module import time, so
        merely importing config touched the filesystem."""
        target = tmp_path / "should_not_exist"
        Settings(output_dir=target, cache_dir=target)
        assert not target.exists()

    def test_ensure_directories_creates_them_when_called(self, tmp_path):
        s = Settings(
            output_dir=tmp_path / "out",
            cache_dir=tmp_path / "cache",
            render_dir=tmp_path / "renders",
            checkpoint_dir=tmp_path / "ckpt",
        )
        s.ensure_directories()
        for d in (s.output_dir, s.cache_dir, s.render_dir, s.checkpoint_dir):
            assert d.is_dir()


class TestAppModelInfo:
    def test_get_model_info_heuristic(self, monkeypatch):
        import app
        from config.settings import settings
        monkeypatch.setattr(settings, "default_llm_provider", "heuristic")
        info = app._get_model_info(reload_env=False)
        assert "Heuristic" in info

    def test_get_model_info_llm(self, monkeypatch):
        import app
        from config.settings import settings
        monkeypatch.setattr(settings, "default_llm_provider", "gemini")
        monkeypatch.setattr(settings, "gemini_api_key", "test-key")
        info = app._get_model_info(reload_env=False)
        assert "LLM model" in info
        assert "gemini" in info

    def test_run_job_signature_accepts_arguments(self):
        import inspect
        import app
        sig = inspect.signature(app._run_job)
        assert len(sig.parameters) == 7
        assert "aspect_ratio" in sig.parameters
        assert "enable_hook_banner" in sig.parameters
        assert "language" in sig.parameters


