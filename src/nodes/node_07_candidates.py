"""Node 7: build candidate clips and shortlist them for evaluation."""

from __future__ import annotations

from typing import Any

from config.settings import settings
from src.analysis.candidates import generate_candidates, shortlist_candidates
from src.nodes._base import pipeline_node
from src.schema.state import EditorState


@pipeline_node(stage="candidates", label="Node 7 Candidates")
def node_07_candidates(state: EditorState) -> dict[str, Any]:
    candidates = generate_candidates(
        state.sentence_units,
        state.semantic_chunks,
        state.extracted_features,
        min_duration=settings.min_clip_duration_sec,
        max_duration=settings.max_clip_duration_sec,
    )
    total_generated = len(candidates)

    shortlisted = shortlist_candidates(
        candidates,
        limit=settings.candidate_shortlist_size,
        optimal_duration=settings.optimal_clip_duration_sec,
        overlap_threshold=settings.shortlist_overlap_threshold,
    )

    logs = [
        f"[Node 7 Candidates] generated {total_generated}, "
        f"shortlisted {len(shortlisted)} for evaluation"
    ]
    warnings: list[str] = []
    if len(shortlisted) < settings.target_clip_count_min:
        warnings.append(
            f"Only {len(shortlisted)} candidate(s) available, below the target "
            f"minimum of {settings.target_clip_count_min} final clips."
        )

    update: dict[str, Any] = {
        "candidate_clips": shortlisted,
        "current_node": "NODE_07_CANDIDATES_COMPLETE",
        "logs": logs,
    }
    if warnings:
        update["warnings"] = warnings
    return update
