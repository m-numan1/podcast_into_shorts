"""Node 1: acquire media, or short-circuit in demo mode."""

from __future__ import annotations

from typing import Any

from src.nodes._base import pipeline_node
from src.providers.downloader import MediaDownloaderProvider
from src.schema.state import EditorState


@pipeline_node(stage="download", label="Node 1 Download")
def node_01_download(state: EditorState) -> dict[str, Any]:
    if state.demo_mode:
        # No media exists in demo mode; the fixture transcript is loaded in
        # node 3. Provenance is stamped here so it propagates even if the run
        # is inspected mid-pipeline.
        return {
            "media_source": "fixture",
            "current_node": "NODE_01_SKIPPED_DEMO",
            "podcast_title": "Tech Insights (demo fixture)",
            "logs": ["[Node 1 Download] DEMO MODE: no media acquired."],
            "warnings": [
                "Running on the bundled fixture transcript. Output is synthetic."
            ],
        }

    source = state.source or state.source_url or state.input_file_path or ""
    info = MediaDownloaderProvider().download(source)

    return {
        "podcast_title": info.title,
        "media_file_path": info.file_path,
        "duration_seconds": info.duration,
        "media_has_video": info.has_video,
        "media_source": info.media_source,
        "current_node": "NODE_01_DOWNLOAD_COMPLETE",
        "logs": [
            f"[Node 1 Download] {info.media_source}: {info.title!r} "
            f"({info.duration:.1f}s, video={info.has_video})"
        ],
    }
