"""Node 3: transcribe, then merge fragments into sentence units."""

from __future__ import annotations

from typing import Any

from src.analysis.segmentation import build_sentence_units
from src.errors import TranscriptionError
from src.nodes._base import pipeline_node
from src.providers.transcriber import TranscriberProvider
from src.schema.state import EditorState


@pipeline_node(stage="transcribe", label="Node 3 Transcribe")
def node_03_transcribe(state: EditorState) -> dict[str, Any]:
    provider = TranscriberProvider()

    if state.demo_mode:
        result = provider.load_fixture()
    else:
        result = provider.transcribe(state.audio_file_path, source_url=state.source_url)

    if not result.segments:
        raise TranscriptionError("Transcription produced no segments.")

    units = build_sentence_units(result.segments)
    if not units:
        raise TranscriptionError(
            "Transcript contained no usable text after merging fragments."
        )

    speech_duration = units[-1].end - units[0].start
    logs = [
        f"[Node 3 Transcribe] {result.source}: {len(result.segments)} segments "
        f"-> {len(units)} sentence units covering {speech_duration:.1f}s"
    ]
    warnings: list[str] = []
    if result.source == "youtube_captions":
        warnings.append(
            "YouTube captions carry no speaker or word-level timing data; "
            "speaker labels are heuristic and word timings are interpolated."
        )

    update: dict[str, Any] = {
        "transcript_segments": result.segments,
        "sentence_units": units,
        "transcript_source": result.source,
        "current_node": "NODE_03_TRANSCRIBE_COMPLETE",
        "logs": logs,
    }
    if warnings:
        update["warnings"] = warnings
    # Without probed media (demo mode) the transcript defines the duration.
    if state.duration_seconds <= 0:
        update["duration_seconds"] = round(units[-1].end, 3)
    return update
