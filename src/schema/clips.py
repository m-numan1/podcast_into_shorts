from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class WordTimestamp(BaseModel):
    word: str
    start: float
    end: float
    confidence: Optional[float] = 1.0

class TranscriptSegment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    speaker: Optional[str] = "Speaker_1"
    words: List[WordTimestamp] = Field(default_factory=list)

class SemanticChunk(BaseModel):
    id: str
    start: float
    end: float
    text: str
    topic_summary: str
    key_concepts: List[str] = Field(default_factory=list)
    boundary_reason: str

class ExtractedFeatures(BaseModel):
    chunk_id: str
    emotion_label: str = "neutral"
    emotion_score: float = 0.5
    sentiment_score: float = 0.0
    named_entities: List[str] = Field(default_factory=list)
    speaking_rate_wpm: float = 150.0
    question_count: int = 0
    curiosity_score: float = 0.5
    strong_statement_score: float = 0.5
    silence_duration_sec: float = 0.0
    keyword_density: Dict[str, int] = Field(default_factory=dict)
    topic_confidence: float = 0.8
    story_likelihood: float = 0.5

class CandidateClip(BaseModel):
    id: str
    start_time: float
    end_time: float
    duration: float
    raw_text: str
    semantic_chunk_ids: List[str] = Field(default_factory=list)
    feature_summary: ExtractedFeatures

class ClipEvaluation(BaseModel):
    agent_name: str
    hook_strength: float = Field(ge=0.0, le=10.0)
    curiosity: float = Field(ge=0.0, le=10.0)
    emotional_impact: float = Field(ge=0.0, le=10.0)
    story_completeness: float = Field(ge=0.0, le=10.0)
    educational_value: float = Field(ge=0.0, le=10.0)
    entertainment: float = Field(ge=0.0, le=10.0)
    standalone_quality: float = Field(ge=0.0, le=10.0)
    shareability: float = Field(ge=0.0, le=10.0)
    comment_potential: float = Field(ge=0.0, le=10.0)
    watch_time_prediction: float = Field(ge=0.0, le=10.0)
    virality_score: float = Field(ge=0.0, le=10.0)
    replay_value: float = Field(ge=0.0, le=10.0)
    confidence_score: float = Field(ge=0.0, le=10.0)
    overall_score: float = Field(ge=0.0, le=10.0)
    reasoning: str

class FinalClipOutput(BaseModel):
    id: str
    rank: int
    title: str
    start_timestamp: str  # Format: "MM:SS" or "HH:MM:SS"
    end_timestamp: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    suggested_start_adjustment: str  # e.g., "-1.5s to capture breathing before hook"
    suggested_end_adjustment: str    # e.g., "+0.5s to avoid abrupt sentence cutoff"
    hook: str
    one_sentence_summary: str
    why_this_clip_was_selected: str
    viewer_retention_prediction: str
    virality_score: float
    confidence_score: float
    overall_score: float
    target_platform: List[str]  # e.g. ["YouTube Shorts", "TikTok", "Instagram Reels"]
    target_audience: str
    suggested_caption: str
    suggested_thumbnail_text: str
    suggested_hashtags: List[str]
    agent_evaluations: Dict[str, ClipEvaluation] = Field(default_factory=dict)
