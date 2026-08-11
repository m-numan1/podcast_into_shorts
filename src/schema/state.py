"""The graph state object.

Two structural fixes over the original:

  * `logs` and `warnings` use `operator.add` reducers, so nodes return only
    their *new* lines. The old code copied `state.logs` into every return value
    and appended -- which works for a straight line but silently drops entries
    the moment two nodes run concurrently. The reducer is what makes the
    parallel evaluator fan-out safe.

  * `agent_evaluations` uses a nested-merge reducer for the same reason: six
    agent branches write into it simultaneously.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any

from pydantic import BaseModel, Field

from src.schema.clips import (
    CandidateClip,
    ClipEvaluation,
    DataProvenance,
    ExtractedFeatures,
    FinalClipOutput,
    SemanticChunk,
    SentenceUnit,
    TranscriptSegment,
)


def merge_agent_evaluations(
    left: dict[str, dict[str, ClipEvaluation]],
    right: dict[str, dict[str, ClipEvaluation]],
) -> dict[str, dict[str, ClipEvaluation]]:
    """Reducer: deep-merge `{clip_id: {agent_name: evaluation}}`.

    A plain dict update would have one agent branch clobber the others'
    results for the same clip, since they all target the same clip_id keys.
    """
    merged: dict[str, dict[str, ClipEvaluation]] = {k: dict(v) for k, v in left.items()}
    for clip_id, per_agent in right.items():
        merged.setdefault(clip_id, {}).update(per_agent)
    return merged


class EditorState(BaseModel):
    # ---- Inputs ----
    source: str = ""
    source_url: str | None = None
    input_file_path: str | None = None
    podcast_title: str = "Untitled Podcast Episode"
    # Explicitly requested fixture mode (--demo). Never set implicitly.
    demo_mode: bool = False
    render_requested: bool = False

    # ---- Processed artifacts ----
    media_file_path: str | None = None
    audio_file_path: str | None = None
    # Real probed duration. 0.0 means "not yet determined", never a placeholder.
    duration_seconds: float = 0.0
    media_has_video: bool = False

    # ---- Transcript & segmentation ----
    transcript_segments: list[TranscriptSegment] = Field(default_factory=list)
    # Sentence-length units merged from raw fragments. Every later stage reasons
    # about these rather than about 3-second caption fragments.
    sentence_units: list[SentenceUnit] = Field(default_factory=list)
    semantic_chunks: list[SemanticChunk] = Field(default_factory=list)

    # ---- Vector index ----
    # Number of chunks actually embedded and added to the index. Replaces the
    # old `faiss_indexed: bool` that was hardcoded True even when FAISS was
    # absent and nothing had been indexed.
    indexed_chunk_count: int = 0
    index_path: str | None = None

    # ---- Features & candidates ----
    extracted_features: dict[str, ExtractedFeatures] = Field(default_factory=dict)
    candidate_clips: list[CandidateClip] = Field(default_factory=list)

    # ---- Agent evaluations: clip_id -> agent_name -> evaluation ----
    agent_evaluations: Annotated[
        dict[str, dict[str, ClipEvaluation]], merge_agent_evaluations
    ] = Field(default_factory=dict)

    # ---- Final output ----
    final_clips: list[FinalClipOutput] = Field(default_factory=list)
    rendered_files: list[str] = Field(default_factory=list)

    # ---- Provenance ----
    media_source: str | None = None
    transcript_source: str | None = None
    scoring_mode: str = "heuristic"

    # ---- Pipeline metadata ----
    current_node: str = "INITIALIZED"
    logs: Annotated[list[str], operator.add] = Field(default_factory=list)
    warnings: Annotated[list[str], operator.add] = Field(default_factory=list)
    error: str | None = None
    failed_stage: str | None = None

    def provenance(self) -> DataProvenance:
        """Build the provenance record from what actually happened."""
        from config.settings import settings

        return DataProvenance(
            media_source=self.media_source or "fixture",
            transcript_source=self.transcript_source or "fixture",
            scoring_mode="llm" if self.scoring_mode == "llm" else "heuristic",
            embedding_backend=settings.embedding_backend,
            model_name=settings.active_model_name if self.scoring_mode == "llm" else None,
            whisper_model=(
                settings.whisper_model if self.transcript_source == "whisper" else None
            ),
        )

    @property
    def is_synthetic(self) -> bool:
        return self.media_source == "fixture" or self.transcript_source == "fixture"

    @property
    def succeeded(self) -> bool:
        return self.error is None and bool(self.final_clips)


def fail(stage: str, message: str, *, log_prefix: str) -> dict[str, Any]:
    """Build the standard node return value for a failure.

    Always sets `current_node` too -- the old error returns omitted it, leaving
    a stale value that made post-mortem logs misleading.
    """
    return {
        "error": message,
        "failed_stage": stage,
        "current_node": f"{log_prefix}_FAILED",
        "logs": [f"[{log_prefix}] ERROR: {message}"],
    }
