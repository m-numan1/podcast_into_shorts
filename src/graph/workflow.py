"""Graph assembly.

Changes over the original wiring:

  * Every node is followed by an error check. The original checked only after
    nodes 2, 4 and 7, so a failure in node 1, 3, 5 or 6 let the pipeline run on
    with empty state -- node 5 in particular set `error` and the unconditional
    edge to node 6 ignored it.
  * The six evaluators are real parallel branches fanned out from node 7 and
    joined at node 9, instead of a `for` loop inside one node that logged
    "in parallel".
  * A checkpointer is attached, so a run that dies during a 30-minute Whisper
    transcription resumes instead of starting over.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from config.settings import settings
from src.agents.editors import AGENTS
from src.nodes import (
    AGENT_NODES,
    node_01_download,
    node_02_audio,
    node_03_transcribe,
    node_04_segment,
    node_05_index,
    node_06_features,
    node_07_candidates,
    node_09_synthesize,
    node_10_render,
)
from src.schema.state import EditorState
from src.utils.logging_config import get_logger

log = get_logger(__name__)

AGENT_NODE_NAMES = [f"node_08_{agent.key}" for agent in AGENTS]

# Linear part of the pipeline: (node_name, callable).
LINEAR_NODES: list[tuple[str, Any]] = [
    ("node_01_download", node_01_download),
    ("node_02_audio", node_02_audio),
    ("node_03_transcribe", node_03_transcribe),
    ("node_04_segment", node_04_segment),
    ("node_05_index", node_05_index),
    ("node_06_features", node_06_features),
    ("node_07_candidates", node_07_candidates),
]


def _abort_node(state: EditorState) -> dict[str, Any]:
    return {
        "current_node": "ABORTED",
        "logs": [
            f"[ABORT] halted at stage {state.failed_stage or 'unknown'}: {state.error}"
        ],
    }


def _guard(next_node: str):
    """Path function: continue to `next_node` unless an error is set."""

    def route(state: EditorState) -> str:
        return "abort" if state.error else next_node

    route.__name__ = f"guard_to_{next_node}"
    return route


def _fan_out(state: EditorState) -> list[str] | str:
    """Dispatch to all six evaluator branches at once.

    Returning a list from a conditional edge is how LangGraph expresses
    fan-out; the branches then join at node 9.
    """
    if state.error:
        return "abort"
    return list(AGENT_NODE_NAMES)


def build_checkpointer():
    """SQLite checkpointer when available, else in-memory, else none."""
    if not settings.checkpoint_enabled:
        return None
    try:
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver

        settings.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        db = settings.checkpoint_dir / "pipeline.sqlite"
        # Own the connection directly rather than calling `__enter__()` on
        # `from_conn_string()`: that context manager closes the connection when
        # the (unreferenced) generator is garbage-collected, so the very first
        # checkpoint read raised "Cannot operate on a closed database".
        # check_same_thread=False because LangGraph runs nodes on worker threads.
        conn = sqlite3.connect(str(db), check_same_thread=False)
        saver = SqliteSaver(conn)
        log.info("Checkpointing to %s", db)
        return saver
    except ImportError:
        log.debug(
            "langgraph-checkpoint-sqlite is not installed; trying the in-memory saver."
        )
    except Exception as exc:
        log.warning("SQLite checkpointer unavailable (%s); using in-memory.", exc)

    try:
        from langgraph.checkpoint.memory import InMemorySaver

        log.info(
            "Using in-memory checkpointer (install langgraph-checkpoint-sqlite "
            "to make runs resumable across processes)."
        )
        return InMemorySaver()
    except ImportError:
        log.warning("No checkpointer available; runs will not be resumable.")
        return None


def create_editor_graph(checkpointer=None):
    """Assemble and compile the pipeline."""
    builder = StateGraph(EditorState)

    for name, fn in LINEAR_NODES:
        builder.add_node(name, fn)
    for agent in AGENTS:
        builder.add_node(f"node_08_{agent.key}", AGENT_NODES[agent.key])
    builder.add_node("node_09_synthesize", node_09_synthesize)
    builder.add_node("node_10_render", node_10_render)
    builder.add_node("abort", _abort_node)

    builder.add_edge(START, LINEAR_NODES[0][0])

    # Error check after *every* linear node.
    for idx, (name, _) in enumerate(LINEAR_NODES):
        is_last = idx == len(LINEAR_NODES) - 1
        if is_last:
            builder.add_conditional_edges(
                name,
                _fan_out,
                AGENT_NODE_NAMES + ["abort"],
            )
        else:
            nxt = LINEAR_NODES[idx + 1][0]
            builder.add_conditional_edges(
                name, _guard(nxt), {nxt: nxt, "abort": "abort"}
            )

    # All six branches join here.
    for node_name in AGENT_NODE_NAMES:
        builder.add_edge(node_name, "node_09_synthesize")

    builder.add_conditional_edges(
        "node_09_synthesize",
        _guard("node_10_render"),
        {"node_10_render": "node_10_render", "abort": "abort"},
    )
    builder.add_edge("node_10_render", END)
    builder.add_edge("abort", END)

    return builder.compile(checkpointer=checkpointer)


class VideoEditorPipeline:
    def __init__(self, checkpointer: Any | None = None, use_checkpointer: bool = True):
        self.checkpointer = checkpointer or (build_checkpointer() if use_checkpointer else None)
        self.graph = create_editor_graph(self.checkpointer)

    def run(
        self,
        source: str,
        *,
        demo_mode: bool = False,
        render: bool = False,
        thread_id: str = "default",
    ) -> EditorState:
        from src.providers.downloader import is_url

        initial = EditorState(
            source=source,
            source_url=source if is_url(source) else None,
            input_file_path=None if is_url(source) else (source or None),
            demo_mode=demo_mode,
            render_requested=render,
            # Set explicitly, not left to the field default. LangGraph writes
            # only the fields a Pydantic input actually sets (`model_fields_set`),
            # so an unset `error` left the *checkpointed* value in place: after
            # any failed run, every later run on the same thread id was routed
            # straight to `abort` by `_guard`, reporting the earlier run's
            # failure and never executing. `--thread-id` defaults to "cli", so
            # a single bad path broke the default CLI thread permanently.
            error=None,
            failed_stage=None,
        )

        config: dict[str, Any] = {}
        if self.checkpointer is not None:
            # Checkpointers require a thread id to scope the saved state.
            config["configurable"] = {"thread_id": thread_id}
        # Six parallel branches plus the linear chain; the default limit of 25
        # is tight once fan-out is involved.
        config["recursion_limit"] = 50

        result = self.graph.invoke(initial, config=config)
        if isinstance(result, EditorState):
            return result
        return EditorState.model_validate(result)
