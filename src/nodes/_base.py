"""Shared node plumbing.

Every node is wrapped so that a `PipelineError` becomes a clean `state.error`
with the failing stage recorded, and an unexpected exception is logged with a
traceback rather than tearing down the graph. The original nodes had no
try/except at all, so a `yt_dlp` or ffmpeg raise killed the whole run with a
stack trace and no partial state.
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable

from src.errors import PipelineError
from src.schema.state import EditorState, fail
from src.utils.logging_config import get_logger

log = get_logger(__name__)

NodeFn = Callable[[EditorState], dict[str, Any]]


def pipeline_node(
    stage: str, label: str, *, tolerant: bool = False
) -> Callable[[NodeFn], NodeFn]:
    """Decorate a node with error capture, timing and consistent logging.

    `tolerant` nodes record a warning instead of aborting the run. Used for the
    six evaluator branches: five agents' verdicts are still a usable result, so
    one failing branch must not halt the pipeline.
    """

    def decorator(fn: NodeFn) -> NodeFn:
        @functools.wraps(fn)
        def wrapper(state: EditorState) -> dict[str, Any]:
            started = time.perf_counter()
            try:
                result = fn(state)
            except PipelineError as exc:
                log.error("[%s] %s", label, exc)
                if tolerant:
                    return {
                        "logs": [f"[{label}] FAILED (non-fatal): {exc}"],
                        "warnings": [f"{label} failed: {exc}"],
                    }
                return fail(stage, str(exc), log_prefix=label)
            except Exception as exc:  # unexpected: keep the traceback
                log.exception("[%s] unexpected failure", label)
                if tolerant:
                    return {
                        "logs": [f"[{label}] FAILED (non-fatal): {exc}"],
                        "warnings": [
                            f"{label} failed with {type(exc).__name__}: {exc}"
                        ],
                    }
                return fail(
                    stage,
                    f"Unexpected {type(exc).__name__}: {exc}",
                    log_prefix=label,
                )
            elapsed = time.perf_counter() - started
            logs = result.setdefault("logs", [])
            if isinstance(logs, list):
                logs.append(f"[{label}] completed in {elapsed:.2f}s")
            return result

        return wrapper

    return decorator
