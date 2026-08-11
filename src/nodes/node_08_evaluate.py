"""Node 8: the six editor agents, one LangGraph node each.

The original ran all six inside a single node's `for` loop while logging
"Running 6 Specialized AI Editor Agents in parallel". These are real graph
nodes, fanned out from node 7 and joined at node 9, so the framework schedules
them concurrently -- which is only safe because `agent_evaluations` now has a
merge reducer (see src/schema/state.py).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from config.settings import settings
from src.agents.editors import AGENTS, EditorAgent, evaluate
from src.nodes._base import pipeline_node
from src.providers.llm import LLMProvider
from src.schema.clips import ClipEvaluation
from src.schema.state import EditorState
from src.utils.logging_config import get_logger

log = get_logger(__name__)


def _evaluate_agent(state: EditorState, agent: EditorAgent) -> dict[str, Any]:
    candidates = state.candidate_clips
    if not candidates:
        return {
            "logs": [f"[Node 8 {agent.name}] no candidates to evaluate."],
        }

    llm = LLMProvider() if settings.uses_llm else None
    episode_duration = state.duration_seconds

    def score_one(candidate) -> tuple[str, ClipEvaluation]:
        return candidate.id, evaluate(agent, candidate, llm, episode_duration)

    # Within an agent, candidates are independent, so overlap the network waits.
    # Bounded by llm_max_concurrency to respect rate limits.
    if llm is not None and len(candidates) > 1:
        with ThreadPoolExecutor(max_workers=settings.llm_max_concurrency) as pool:
            results = list(pool.map(score_one, candidates))
    else:
        results = [score_one(c) for c in candidates]

    evaluations = {cid: {agent.key: ev} for cid, ev in results}
    modes = {ev.scoring_mode for _, ev in results}
    mean_overall = sum(ev.overall_score for _, ev in results) / len(results)

    return {
        # Merged by merge_agent_evaluations, so the six branches compose
        # instead of overwriting one another.
        "agent_evaluations": evaluations,
        "logs": [
            f"[Node 8 {agent.name}] scored {len(results)} candidates "
            f"(mean {mean_overall:.2f}/10, mode={'/'.join(sorted(modes))})"
        ],
    }


def make_agent_node(agent: EditorAgent) -> Callable[[EditorState], dict[str, Any]]:
    """Build a decorated graph node for one agent."""

    # Tolerant: a single agent failing leaves five usable verdicts, so it must
    # degrade to a warning rather than abort the whole run.
    @pipeline_node(
        stage=f"evaluate:{agent.key}", label=f"Node 8 {agent.name}", tolerant=True
    )
    def _node(state: EditorState) -> dict[str, Any]:
        return _evaluate_agent(state, agent)

    _node.__name__ = f"node_08_{agent.key}"
    return _node


AGENT_NODES: dict[str, Callable[[EditorState], dict[str, Any]]] = {
    agent.key: make_agent_node(agent) for agent in AGENTS
}
