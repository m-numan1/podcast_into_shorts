"""Node 9: chief editor. Join the agent branches, rank, dedup, package."""

from __future__ import annotations

from typing import Any

from config.settings import settings
from src.agents.chief_editor import NEAR_DUPLICATE_SIMILARITY, synthesise
from src.errors import PipelineError
from src.nodes._base import pipeline_node
from src.providers.llm import LLMProvider
from src.schema.state import EditorState
from src.utils.logging_config import get_logger

log = get_logger(__name__)


def _near_duplicate_pairs(state: EditorState) -> set[tuple[str, str]]:
    """Chunk pairs whose content is near-identical, from the persisted index."""
    if not state.index_path:
        return set()
    try:
        from src.providers.vectorstore import VectorStoreProvider

        store = VectorStoreProvider.load(state.index_path)
        pairs = store.find_near_duplicates(threshold=NEAR_DUPLICATE_SIMILARITY)
        return {(a, b) for a, b, _ in pairs}
    except PipelineError as exc:
        log.warning("Could not load chunk index for duplicate detection: %s", exc)
        return set()


@pipeline_node(stage="synthesize", label="Node 9 Chief Editor")
def node_09_synthesize(state: EditorState) -> dict[str, Any]:
    if not state.candidate_clips:
        raise PipelineError("No candidate clips to synthesise.")
    if not state.agent_evaluations:
        raise PipelineError(
            "No agent evaluations were produced.",
            "All six evaluator branches failed; check the logs above.",
        )

    llm = LLMProvider() if settings.uses_llm else None
    # Reflect what actually happened rather than what was configured: if every
    # evaluation fell back to heuristics, say heuristic.
    modes = {
        ev.scoring_mode
        for per_agent in state.agent_evaluations.values()
        for ev in per_agent.values()
    }
    scoring_mode = "llm" if "llm" in modes else "heuristic"

    provenance = state.provenance().model_copy(update={"scoring_mode": scoring_mode})

    clips, warnings = synthesise(
        state.candidate_clips,
        state.agent_evaluations,
        podcast_title=state.podcast_title,
        llm=llm,
        provenance=provenance,
        near_duplicate_pairs=_near_duplicate_pairs(state),
    )

    if not clips:
        raise PipelineError(
            "Every candidate was rejected during synthesis.",
            "Loosen DEDUP_OVERLAP_THRESHOLD or widen the clip duration window.",
        )

    update: dict[str, Any] = {
        "final_clips": clips,
        "scoring_mode": scoring_mode,
        "current_node": "NODE_09_SYNTHESIZE_COMPLETE",
        "logs": [
            f"[Node 9 Chief Editor] published {len(clips)} clips "
            f"(scoring={scoring_mode}, top score {clips[0].overall_score:.2f}/10)"
        ],
    }
    if warnings:
        update["warnings"] = warnings
    return update
