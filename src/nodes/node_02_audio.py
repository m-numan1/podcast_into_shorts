"""Node 2: extract 16 kHz mono audio for transcription."""

from __future__ import annotations

from typing import Any

from src.errors import AudioExtractionError
from src.nodes._base import pipeline_node
from src.providers.audio import AudioProcessorProvider
from src.schema.state import EditorState


@pipeline_node(stage="audio", label="Node 2 Audio")
def node_02_audio(state: EditorState) -> dict[str, Any]:
    if state.demo_mode:
        return {
            "current_node": "NODE_02_SKIPPED_DEMO",
            "logs": ["[Node 2 Audio] DEMO MODE: no audio to extract."],
        }

    if not state.media_file_path:
        raise AudioExtractionError(
            "No media file available to extract audio from.",
            "Node 1 did not produce a file; check the download stage.",
        )

    audio_path = AudioProcessorProvider().extract_audio(state.media_file_path)
    return {
        "audio_file_path": audio_path,
        "current_node": "NODE_02_AUDIO_COMPLETE",
        "logs": [f"[Node 2 Audio] extracted to {audio_path}"],
    }
