from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from src.schema.clips import (
    TranscriptSegment,
    SemanticChunk,
    ExtractedFeatures,
    CandidateClip,
    ClipEvaluation,
    FinalClipOutput
)

class EditorState(BaseModel):
    # Inputs
    source_url: Optional[str] = None
    input_file_path: Optional[str] = None
    podcast_title: str = "Untitled Podcast Episode"
    
    # Processed Artifacts
    media_file_path: Optional[str] = None
    audio_file_path: Optional[str] = None
    duration_seconds: float = 0.0
    
    # Transcripts & Segmentation
    transcript_segments: List[TranscriptSegment] = Field(default_factory=list)
    full_transcript_text: str = ""
    semantic_chunks: List[SemanticChunk] = Field(default_factory=list)
    
    # Vector Indexing
    faiss_indexed: bool = False
    
    # Features & Candidates
    extracted_features: Dict[str, ExtractedFeatures] = Field(default_factory=dict)
    candidate_clips: List[CandidateClip] = Field(default_factory=list)
    
    # Agent Evaluations: clip_id -> { agent_name -> ClipEvaluation }
    agent_evaluations: Dict[str, Dict[str, ClipEvaluation]] = Field(default_factory=dict)
    
    # Final Output
    final_clips: List[FinalClipOutput] = Field(default_factory=list)
    
    # Pipeline Metadata
    current_node: str = "INITIALIZED"
    logs: List[str] = Field(default_factory=list)
    error: Optional[str] = None

    def add_log(self, message: str):
        self.logs.append(message)
