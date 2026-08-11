"""Node 5: embed and index chunks, persisting the index for later nodes.

Indexing failure is not fatal: the index only powers semantic near-duplicate
detection in the chief editor, so the pipeline degrades to time-overlap dedup
and records a warning. The original returned `faiss_indexed=True`
unconditionally and logged success even with nothing indexed.
"""

from __future__ import annotations

from typing import Any

from src.errors import PipelineError
from src.nodes._base import pipeline_node
from src.providers.vectorstore import VectorStoreProvider
from src.schema.state import EditorState
from src.utils.logging_config import get_logger

log = get_logger(__name__)


@pipeline_node(stage="index", label="Node 5 Index")
def node_05_index(state: EditorState) -> dict[str, Any]:
    if not state.semantic_chunks:
        raise PipelineError("No semantic chunks available to index.")

    try:
        store = VectorStoreProvider()
        indexed = store.index_chunks(state.semantic_chunks)
        index_path = store.save()
    except PipelineError as exc:
        log.warning("Chunk indexing failed: %s", exc)
        return {
            "indexed_chunk_count": 0,
            "current_node": "NODE_05_INDEX_DEGRADED",
            "logs": [f"[Node 5 Index] indexing unavailable: {exc}"],
            "warnings": [
                f"Chunk indexing failed ({exc}). Semantic near-duplicate "
                f"detection is disabled; time-overlap dedup still applies."
            ],
        }

    return {
        "indexed_chunk_count": indexed,
        "index_path": index_path,
        "current_node": "NODE_05_INDEX_COMPLETE",
        "logs": [f"[Node 5 Index] indexed {indexed} chunks -> {index_path}"],
    }
