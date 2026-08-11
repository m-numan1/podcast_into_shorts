"""Node 10: render selected clips to vertical MP4s.

Opt-in (`--render`). A render failure degrades to a warning rather than
discarding the JSON recommendations, which are useful on their own.
"""

from __future__ import annotations

from typing import Any

from config.settings import settings
from src.errors import PipelineError, RenderError
from src.nodes._base import pipeline_node
from src.providers.renderer import ClipRenderer
from src.schema.state import EditorState
from src.utils.logging_config import get_logger

log = get_logger(__name__)


@pipeline_node(stage="render", label="Node 10 Render")
def node_10_render(state: EditorState) -> dict[str, Any]:
    if not state.render_requested:
        return {
            "current_node": "NODE_10_RENDER_SKIPPED",
            "logs": ["[Node 10 Render] not requested; skipping."],
        }

    if state.demo_mode or not state.media_file_path:
        return {
            "current_node": "NODE_10_RENDER_SKIPPED",
            "logs": ["[Node 10 Render] no source media available; skipping."],
            "warnings": [
                "Rendering was requested but there is no media file "
                "(demo mode or audio acquisition failed)."
            ],
        }

    clips = state.final_clips[: settings.render_max_clips]
    if not clips:
        return {
            "current_node": "NODE_10_RENDER_SKIPPED",
            "logs": ["[Node 10 Render] no clips to render."],
        }

    all_words = [w for seg in state.transcript_segments for w in seg.words]
    renderer = ClipRenderer()

    rendered: list[str] = []
    warnings: list[str] = []
    logs: list[str] = []

    for clip in clips:
        try:
            result = renderer.render(
                clip,
                state.media_file_path,
                state.sentence_units,
                all_words,
                has_video=state.media_has_video,
            )
        except (RenderError, PipelineError) as exc:
            log.warning("Render failed for %s: %s", clip.id, exc)
            warnings.append(f"Render failed for {clip.id}: {exc}")
            continue
        rendered.append(result.output_path)
        clip.rendered_file_path = result.output_path
        logs.append(
            f"[Node 10 Render] {clip.id} -> {result.output_path} "
            f"({result.duration:.1f}s, captions={result.captions_burned})"
        )

    if not rendered and not warnings:
        warnings.append("Rendering produced no files.")

    logs.append(
        f"[Node 10 Render] rendered {len(rendered)}/{len(clips)} clips "
        f"to {settings.render_dir}"
    )

    update: dict[str, Any] = {
        "rendered_files": rendered,
        # Carry the mutated clips back so rendered_file_path persists in state.
        "final_clips": state.final_clips,
        "current_node": "NODE_10_RENDER_COMPLETE",
        "logs": logs,
    }
    if warnings:
        update["warnings"] = warnings
    return update
