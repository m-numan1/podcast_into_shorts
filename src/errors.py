"""Exception hierarchy for the pipeline.

Every stage raises a specific subclass instead of degrading to fabricated
output. Nodes convert these into `state.error` so the graph can abort with an
accurate reason, and the CLI/web layer surfaces it verbatim.
"""


class PipelineError(Exception):
    """Base class for every recoverable pipeline failure.

    `stage` names the pipeline stage for log/report attribution. `remedy` is an
    optional operator-facing hint printed alongside the message.
    """

    stage: str = "pipeline"

    def __init__(self, message: str, remedy: str | None = None):
        super().__init__(message)
        self.message = message
        self.remedy = remedy

    def __str__(self) -> str:
        if self.remedy:
            return f"{self.message}  (fix: {self.remedy})"
        return self.message


class ConfigError(PipelineError):
    """Settings are missing or internally inconsistent."""

    stage = "config"


class DownloadError(PipelineError):
    """The source URL or file could not be fetched or validated."""

    stage = "download"


class AudioExtractionError(PipelineError):
    """Audio could not be decoded out of the source media."""

    stage = "audio"


class TranscriptionError(PipelineError):
    """No transcript could be produced by any configured backend."""

    stage = "transcribe"


class SegmentationError(PipelineError):
    """The transcript could not be divided into usable topic chunks."""

    stage = "segment"


class EmbeddingError(PipelineError):
    """Embeddings could not be generated."""

    stage = "embed"


class CandidateGenerationError(PipelineError):
    """No clip candidates satisfied the configured duration constraints."""

    stage = "candidates"


class LLMError(PipelineError):
    """The language model could not be reached or returned unusable output."""

    stage = "llm"


class RenderError(PipelineError):
    """ffmpeg failed to cut, reframe, or encode a clip."""

    stage = "render"


class MissingDependencyError(PipelineError):
    """A required Python package or system binary is not installed."""

    stage = "dependency"

    def __init__(self, what: str, install_hint: str):
        super().__init__(f"Required dependency not available: {what}", install_hint)
        self.what = what
