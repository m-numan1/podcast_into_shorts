from src.schema.state import EditorState
from src.providers.audio import AudioProcessorProvider

def node_02_audio(state: EditorState) -> dict:
    """
    Node 2: Extract audio stream for downstream transcription & acoustic feature extraction.
    """
    if not state.media_file_path:
        return {
            "error": "No media file path found in state for Node 2.",
            "logs": state.logs + ["[Node 2] ERROR: No media file path found."]
        }
        
    logs = list(state.logs)
    logs.append(f"[Node 2] Extracting audio stream from {state.media_file_path}")
    
    audio_provider = AudioProcessorProvider()
    extracted_audio = audio_provider.extract_audio(state.media_file_path)
    
    logs.append(f"[Node 2] Audio stream ready at: {extracted_audio}")
    
    return {
        "audio_file_path": extracted_audio,
        "current_node": "NODE_02_AUDIO_COMPLETE",
        "logs": logs
    }
