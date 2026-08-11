from src.schema.state import EditorState
from src.providers.transcriber import TranscriberProvider

def node_03_transcribe(state: EditorState) -> dict:
    """
    Node 3: Generate timestamped transcript with word-level timestamps and speaker labels.
    """
    logs = list(state.logs)
    logs.append("[Node 3] Running timestamped transcription...")
    
    transcriber = TranscriberProvider()
    
    # Prefer extracted audio file for Whisper, fall back to source URL for YouTube Transcript API
    audio_path = state.audio_file_path or state.media_file_path or state.source_url or ""
    segments = transcriber.transcribe(audio_path, source_url=state.source_url)
    
    full_transcript_text = "\n".join([f"[{seg.start:.1f}s - {seg.end:.1f}s] {seg.speaker}: {seg.text}" for seg in segments])
    
    logs.append(f"[Node 3] Transcription complete. {len(segments)} timestamped segments generated.")
    
    return {
        "transcript_segments": segments,
        "full_transcript_text": full_transcript_text,
        "current_node": "NODE_03_TRANSCRIBE_COMPLETE",
        "logs": logs
    }
