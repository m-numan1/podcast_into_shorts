"""Node 6: per-chunk linguistic and timing features."""

from __future__ import annotations

from typing import Any

from src.analysis.features import extract_all
from src.errors import PipelineError
from src.nodes._base import pipeline_node
from src.schema.state import EditorState


@pipeline_node(stage="features", label="Node 6 Features")
def node_06_features(state: EditorState) -> dict[str, Any]:
    if not state.semantic_chunks:
        raise PipelineError("No semantic chunks available for feature extraction.")

    features = extract_all(state.semantic_chunks, state.sentence_units)
    measured_pauses = sum(1 for f in features.values() if f.longest_pause_sec > 0)

    return {
        "extracted_features": features,
        "current_node": "NODE_06_FEATURES_COMPLETE",
        "logs": [
            f"[Node 6 Features] extracted for {len(features)} chunks "
            f"({measured_pauses} with measurable internal pauses)"
        ],
    }
