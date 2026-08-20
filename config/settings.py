"""Typed, validated application settings.

Loaded from environment / `.env` via pydantic-settings. Two things the previous
version got wrong and this one enforces:

  * `embedding_dim` no longer contradicts `embedding_model` -- it is derived
    from the model name instead of being an independently-set constant.
  * Directories are no longer created as an import side effect. Call
    `settings.ensure_directories()` from an entry point.
"""

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

LLMProviderName = Literal["openai", "gemini", "heuristic"]
EmbeddingBackend = Literal["openai", "gemini", "lexical"]

# Output dimensionality per embedding model. `lexical` is our deterministic
# offline hashing vectoriser, whose width we choose ourselves.
EMBEDDING_DIMS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "models/text-embedding-004": 768,
    "lexical": 512,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Absolute so behaviour does not depend on the current working directory.
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- App ----
    app_name: str = "AI Video Editor for Podcasters"
    env: str = "development"
    log_level: str = "INFO"
    output_dir: Path = BASE_DIR / "outputs"
    cache_dir: Path = BASE_DIR / "cache"
    render_dir: Path = BASE_DIR / "renders"
    checkpoint_dir: Path = BASE_DIR / "checkpoints"

    # ---- Download ----
    ytdlp_cookies_from_browser: str | None = None
    ytdlp_cookies_file: Path | str | None = None

    # ---- LLM ----
    openai_api_key: str = ""
    gemini_api_key: str = ""
    # "heuristic" means: score without a model. It is a real, declared mode --
    # never a silent fallback. Output is stamped with scoring_mode="heuristic".
    default_llm_provider: LLMProviderName = "heuristic"
    default_model: str = "gpt-4o-mini"
    gemini_model: str = "gemini-3.6-flash"
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    llm_max_retries: int = Field(default=3, ge=0, le=10)
    llm_timeout_sec: float = Field(default=60.0, gt=0)
    llm_max_concurrency: int = Field(default=6, ge=1, le=32)
    llm_cache_enabled: bool = True

    # ---- Embeddings ----
    embedding_backend: EmbeddingBackend = "lexical"
    embedding_model: str = "text-embedding-3-small"
    # Derived in the validator below; do not set directly.
    embedding_dim: int = 0

    # ---- Transcription ----
    whisper_model: str = "base"
    transcript_language: str | None = None
    enable_diarization: bool = False

    # ---- Segmentation ----
    # Boundary is declared where adjacent-window cosine similarity dips below
    # this value relative to the local mean. Tuned empirically; see tests.
    segment_similarity_drop: float = Field(default=0.82, ge=0.0, le=1.0)
    segment_min_duration_sec: float = Field(default=8.0, gt=0)
    # Hard ceiling: any chunk longer than this is force-split so a whole
    # episode can never collapse into one unusable chunk.
    segment_max_duration_sec: float = Field(default=120.0, gt=0)

    # ---- Clip constraints ----
    target_clip_count_min: int = Field(default=5, ge=1)
    target_clip_count_max: int = Field(default=15, ge=1)
    min_clip_duration_sec: float = Field(default=15.0, gt=0)
    max_clip_duration_sec: float = Field(default=90.0, gt=0)
    optimal_clip_duration_sec: float = Field(default=45.0, gt=0)
    # Two clips are duplicates when their intersection-over-shorter exceeds
    # this. Symmetric, unlike the old candidate-duration-only comparison.
    dedup_overlap_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    # Candidate generation can legitimately produce hundreds of windows for a
    # long episode. Every shortlisted candidate costs one LLM call per agent
    # (x6), so cap it before evaluation rather than after.
    candidate_shortlist_size: int = Field(default=40, ge=1, le=500)
    # Max time-overlap allowed between two shortlisted candidates, so the
    # budget is spread across the episode instead of on one hot region.
    shortlist_overlap_threshold: float = Field(default=0.55, ge=0.0, le=1.0)

    # ---- Composite scoring weights (must sum to 1.0) ----
    weight_hook: float = 0.25
    weight_comment_potential: float = 0.20
    weight_educational: float = 0.20
    weight_retention: float = 0.20
    weight_story: float = 0.15

    # ---- Rendering ----
    render_enabled: bool = False
    render_width: int = 1080
    render_height: int = 1920
    # "blur_pad" keeps the whole 16:9 frame visible against a blurred fill;
    # "crop" fills the frame but can cut faces out of an interview shot.
    render_mode: Literal["blur_pad", "crop"] = "blur_pad"
    # Cap renders per run; encoding is by far the slowest stage.
    render_max_clips: int = Field(default=5, ge=1, le=100)

    render_crf: int = Field(default=20, ge=0, le=51)
    render_preset: str = "medium"
    render_burn_captions: bool = True
    render_loudness_lufs: float = -14.0
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    ffmpeg_timeout_sec: float = Field(default=1800.0, gt=0)

    # ---- Graph execution ----
    # Checkpointing makes a run resumable after a crash mid-transcription.
    checkpoint_enabled: bool = True

    # ---- Web ----
    server_host: str = "127.0.0.1"
    server_port: int = 8000
    max_request_bytes: int = 10 * 1024 * 1024


    @model_validator(mode="after")
    def _derive_and_check(self) -> "Settings":
        # Derive embedding width from the chosen backend/model.
        key = "lexical" if self.embedding_backend == "lexical" else self.embedding_model
        derived = EMBEDDING_DIMS.get(key)
        if derived is None:
            raise ValueError(
                f"Unknown embedding model {self.embedding_model!r} for backend "
                f"{self.embedding_backend!r}. Add it to EMBEDDING_DIMS with its "
                f"output dimensionality."
            )
        object.__setattr__(self, "embedding_dim", derived)

        if self.min_clip_duration_sec >= self.max_clip_duration_sec:
            raise ValueError(
                f"min_clip_duration_sec ({self.min_clip_duration_sec}) must be "
                f"less than max_clip_duration_sec ({self.max_clip_duration_sec})"
            )
        if self.target_clip_count_min > self.target_clip_count_max:
            raise ValueError(
                f"target_clip_count_min ({self.target_clip_count_min}) must not "
                f"exceed target_clip_count_max ({self.target_clip_count_max})"
            )
        if self.segment_max_duration_sec <= self.segment_min_duration_sec:
            raise ValueError(
                "segment_max_duration_sec must exceed segment_min_duration_sec"
            )

        weights = (
            self.weight_hook
            + self.weight_comment_potential
            + self.weight_educational
            + self.weight_retention
            + self.weight_story
        )
        if abs(weights - 1.0) > 1e-6:
            raise ValueError(f"Composite scoring weights must sum to 1.0, got {weights}")

        # A provider is only usable with its key present. Catch this at startup
        # rather than swallowing an auth error mid-run.
        if self.default_llm_provider == "openai" and not self.openai_api_key:
            raise ValueError(
                "DEFAULT_LLM_PROVIDER=openai but OPENAI_API_KEY is empty. Set the "
                "key, or use DEFAULT_LLM_PROVIDER=heuristic for offline scoring."
            )
        if self.default_llm_provider == "gemini" and not self.gemini_api_key:
            raise ValueError(
                "DEFAULT_LLM_PROVIDER=gemini but GEMINI_API_KEY is empty. Set the "
                "key, or use DEFAULT_LLM_PROVIDER=heuristic for offline scoring."
            )
        return self

    @property
    def uses_llm(self) -> bool:
        return self.default_llm_provider in ("openai", "gemini")

    @property
    def active_model_name(self) -> str:
        if self.default_llm_provider == "openai":
            return self.default_model
        if self.default_llm_provider == "gemini":
            return self.gemini_model
        return "heuristic"

    def ensure_directories(self) -> None:
        """Create runtime directories. Call from an entry point, not on import."""
        for d in (self.output_dir, self.cache_dir, self.render_dir, self.checkpoint_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
