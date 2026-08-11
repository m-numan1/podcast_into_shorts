"""Node 4: group sentence units into topic chunks.

Semantic dip detection is only enabled when a genuinely semantic embedding
backend is configured. See the module docstring in src/analysis/segmentation.py
for the measurement behind that decision.
"""

from __future__ import annotations

from typing import Any

from config.settings import settings
from src.analysis.segmentation import segment_units
from src.errors import SegmentationError
from src.nodes._base import pipeline_node
from src.schema.state import EditorState
from src.utils.logging_config import get_logger

log = get_logger(__name__)


def _semantic_dips(state: EditorState) -> dict[int, float] | None:
    """Adjacent-window similarity per unit index, or None when unavailable.

    Skipped for the `lexical` backend: measured on planted boundaries, lexical
    dips do not separate topics at any window size, so feeding them in would add
    noise while looking sophisticated.
    """
    if settings.embedding_backend == "lexical":
        log.info(
            "Semantic dip detection disabled for the lexical embedding backend "
            "(it does not separate topics); using pause and sentence structure."
        )
        return None

    from src.providers.embeddings import build_embedder, cosine_similarity

    units = state.sentence_units
    if len(units) < 4:
        return None

    window = 4
    embedder = build_embedder()
    texts: list[str] = []
    for i in range(len(units) - 1):
        left = " ".join(u.text for u in units[max(0, i - window + 1) : i + 1])
        right = " ".join(u.text for u in units[i + 1 : i + 1 + window])
        texts.append(left)
        texts.append(right)

    vectors = embedder.embed(texts)
    dips: dict[int, float] = {}
    for i in range(len(units) - 1):
        left_vec, right_vec = vectors[2 * i], vectors[2 * i + 1]
        # Map cosine from [-1, 1] into [0, 1] for the seam scorer.
        dips[i] = max(0.0, min(1.0, (cosine_similarity(left_vec, right_vec) + 1.0) / 2.0))
    log.info("Computed %d semantic boundary similarities", len(dips))
    return dips


@pipeline_node(stage="segment", label="Node 4 Segment")
def node_04_segment(state: EditorState) -> dict[str, Any]:
    units = state.sentence_units
    if not units:
        raise SegmentationError(
            "No sentence units available to segment.",
            "Node 3 must run first and produce a transcript.",
        )

    chunks = segment_units(
        units,
        min_duration=settings.segment_min_duration_sec,
        # Chunks must be capable of being a clip, so the ceiling is the smaller
        # of the segmentation ceiling and the maximum clip length.
        max_duration=min(settings.segment_max_duration_sec, settings.max_clip_duration_sec),
        optimal_duration=settings.optimal_clip_duration_sec,
        semantic_dips=_semantic_dips(state),
    )
    if not chunks:
        raise SegmentationError("Segmentation produced no chunks.")

    durations = [c.duration for c in chunks]
    return {
        "semantic_chunks": chunks,
        "current_node": "NODE_04_SEGMENT_COMPLETE",
        "logs": [
            f"[Node 4 Segment] {len(units)} units -> {len(chunks)} chunks "
            f"({min(durations):.1f}-{max(durations):.1f}s, "
            f"mean {sum(durations) / len(durations):.1f}s)"
        ],
    }
