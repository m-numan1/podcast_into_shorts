from src.schema.state import EditorState
from src.providers.downloader import MediaDownloaderProvider

def node_01_download(state: EditorState) -> dict:
    """
    Node 1: Ingest video from YouTube URL or validate local file path.
    """
    source = state.source_url or state.input_file_path or "https://www.youtube.com/watch?v=sample_podcast"
    downloader = MediaDownloaderProvider()
    
    logs = list(state.logs)
    logs.append(f"[Node 1] Ingesting media source: {source}")
    
    info = downloader.download(source)
    
    podcast_title = info.get("title", state.podcast_title)
    media_file_path = info.get("file_path")
    duration_seconds = info.get("duration", 0.0)
    
    logs.append(f"[Node 1] Download complete: '{podcast_title}' ({duration_seconds}s)")
    
    return {
        "podcast_title": podcast_title,
        "media_file_path": media_file_path,
        "duration_seconds": duration_seconds,
        "current_node": "NODE_01_DOWNLOAD_COMPLETE",
        "logs": logs
    }
