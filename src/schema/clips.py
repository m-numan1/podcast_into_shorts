"""Pydantic models for transcript, chunk, candidate and output shapes.

Changes from the original schema:
  * Provenance is explicit (`DataProvenance`) so synthetic or heuristic output
    can never be mistaken for a real analysis of real media.
  * Boundary adjustments are numeric seconds derived from word timings, not
    hardcoded prose strings.
  * Time ranges are validated (end > start) instead of trusted.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# "unavailable" means the stage that sets this never completed -- a run that
# failed before node 1 or node 3. It is distinct from "fixture", which is only
# ever set by an explicit --demo.
TranscriptSource = Literal["youtube_captions", "whisper", "fixture", "unavailable"]
MediaSource = Literal["youtube_download", "local_file", "fixture", "unavailable"]
ScoringMode = Literal["llm", "heuristic"]
EmbeddingBackendName = Literal["openai", "gemini", "lexical"]


class DataProvenance(BaseModel):
    """Where every part of a result came from.

    Attached to the final output and surfaced in the CLI and web UI. The old
    pipeline could fabricate media, transcript and scores and still print
    "[SUCCESS]"; this model makes that impossible to hide.
    """

    media_source: MediaSource
    transcript_source: TranscriptSource
    scoring_mode: ScoringMode
    embedding_backend: EmbeddingBackendName
    model_name: str | None = None
    whisper_model: str | None = None

    @property
    def is_synthetic(self) -> bool:
        """True when any input was fixture data rather than real media."""
        return self.media_source == "fixture" or self.transcript_source == "fixture"

    @property
    def is_incomplete(self) -> bool:
        """True when a stage never ran, so there is nothing to describe."""
        return (
            self.media_source == "unavailable"
            or self.transcript_source == "unavailable"
        )

    def banner(self) -> str:
        """One-line human summary for logs and UI."""
        bits = [
            f"media={self.media_source}",
            f"transcript={self.transcript_source}",
            f"scoring={self.scoring_mode}",
            f"embeddings={self.embedding_backend}",
        ]
        if self.model_name:
            bits.append(f"model={self.model_name}")
        if self.is_synthetic:
            prefix = "SYNTHETIC FIXTURE DATA"
        elif self.is_incomplete:
            prefix = "INCOMPLETE RUN"
        else:
            prefix = "real media"
        return f"[{prefix}] " + "  ".join(bits)


class WordTimestamp(BaseModel):
    word: str
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    confidence: float | None = 1.0

    @model_validator(mode="after")
    def _check_range(self) -> WordTimestamp:
        if self.end < self.start:
            raise ValueError(f"word {self.word!r}: end {self.end} precedes start {self.start}")
        return self


class TranscriptSegment(BaseModel):
    id: int
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    text: str
    speaker: str = "Speaker_1"
    words: list[WordTimestamp] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_range(self) -> TranscriptSegment:
        if self.end < self.start:
            raise ValueError(f"segment {self.id}: end {self.end} precedes start {self.start}")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start


class SentenceUnit(BaseModel):
    """One sentence-ish span, built by merging raw transcript fragments.

    YouTube caption tracks arrive as 2-4 second fragments split mid-sentence.
    Reasoning about topics or cut points on raw fragments is hopeless, so
    everything downstream works on these units instead.
    """

    id: int
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    text: str
    speaker: str = "Speaker_1"
    segment_ids: list[int] = Field(default_factory=list)
    # Silence between the previous unit and this one, in seconds. The single
    # most reliable cue for a safe cut point in speech.
    gap_before: float = 0.0
    # True when the text ends with . ! or ? -- i.e. cutting here will not
    # truncate a sentence.
    ends_sentence: bool = False

    @model_validator(mode="after")
    def _check_range(self) -> SentenceUnit:
        if self.end < self.start:
            raise ValueError(f"unit {self.id}: end {self.end} precedes start {self.start}")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def word_count(self) -> int:
        return len(self.text.split())


class SemanticChunk(BaseModel):
    id: str
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    text: str
    topic_summary: str
    key_concepts: list[str] = Field(default_factory=list)
    boundary_reason: str
    # Index range into the transcript segment list this chunk was built from,
    # so downstream nodes can recover word-level timings.
    segment_ids: list[int] = Field(default_factory=list)
    # Cosine similarity to the following chunk; low values mark real topic
    # shifts. None for the last chunk or when embeddings were unavailable.
    boundary_similarity: float | None = None

    @model_validator(mode="after")
    def _check_range(self) -> SemanticChunk:
        if self.end < self.start:
            raise ValueError(f"chunk {self.id}: end {self.end} precedes start {self.start}")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start


class ExtractedFeatures(BaseModel):
    chunk_id: str
    emotion_label: str = "neutral"
    emotion_score: float = Field(default=0.5, ge=0.0, le=1.0)
    sentiment_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    named_entities: list[str] = Field(default_factory=list)
    speaking_rate_wpm: float = Field(default=150.0, ge=0.0)
    question_count: int = Field(default=0, ge=0)
    curiosity_score: float = Field(default=0.5, ge=0.0, le=1.0)
    strong_statement_score: float = Field(default=0.5, ge=0.0, le=1.0)
    # Measured from word-timestamp gaps, not hardcoded.
    silence_duration_sec: float = Field(default=0.0, ge=0.0)
    longest_pause_sec: float = Field(default=0.0, ge=0.0)
    keyword_density: dict[str, int] = Field(default_factory=dict)
    topic_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    story_likelihood: float = Field(default=0.5, ge=0.0, le=1.0)


class CandidateClip(BaseModel):
    id: str
    start_time: float = Field(ge=0.0)
    end_time: float = Field(ge=0.0)
    duration: float = Field(gt=0.0)
    raw_text: str
    semantic_chunk_ids: list[str] = Field(default_factory=list)
    feature_summary: ExtractedFeatures
    # True when both edges landed on a sentence terminator, so the clip does
    # not open or close mid-sentence.
    starts_on_sentence_boundary: bool = False
    ends_on_sentence_boundary: bool = False
    # Seconds of silence immediately before/after the cut, from word timings.
    lead_in_silence_sec: float = 0.0
    lead_out_silence_sec: float = 0.0

    @model_validator(mode="after")
    def _check_range(self) -> CandidateClip:
        if self.end_time <= self.start_time:
            raise ValueError(
                f"candidate {self.id}: end {self.end_time} must exceed start {self.start_time}"
            )
        return self


class ClipEvaluation(BaseModel):
    """One editor agent's judgement of one candidate."""

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
    # How this evaluation was produced. Never inferred by the reader.
    scoring_mode: ScoringMode = "heuristic"
    model_name: str | None = None


class LLMClipVerdict(BaseModel):
    """Schema the LLM is asked to fill. Deliberately smaller than
    `ClipEvaluation`: we only ask the model for what it can actually judge, and
    derive the rest. Wide schemas produce confident noise."""

    hook_strength: float = Field(ge=0.0, le=10.0, description="Scroll-stop power of the first sentence")
    curiosity: float = Field(ge=0.0, le=10.0, description="Open loop / information gap created")
    emotional_impact: float = Field(ge=0.0, le=10.0)
    story_completeness: float = Field(ge=0.0, le=10.0, description="Setup-tension-payoff present without outside context")
    educational_value: float = Field(ge=0.0, le=10.0, description="Actionable, transferable insight")
    entertainment: float = Field(ge=0.0, le=10.0)
    standalone_quality: float = Field(ge=0.0, le=10.0, description="Understandable with zero episode context")
    shareability: float = Field(ge=0.0, le=10.0)
    comment_potential: float = Field(ge=0.0, le=10.0, description="Likelihood of provoking replies/disagreement")
    watch_time_prediction: float = Field(ge=0.0, le=10.0)
    replay_value: float = Field(ge=0.0, le=10.0)
    confidence_score: float = Field(ge=0.0, le=10.0, description="Your own certainty in these ratings")
    reasoning: str = Field(description="Two sentences citing specific words from the transcript")


class ClipPackaging(BaseModel):
    """Publishing metadata for one selected clip.

    Requested from the model as constrained output. The original derived titles
    by capitalising the first four long words of the transcript, which produced
    strings like "That Terrifying Share Concrete (Clip #1)".
    """

    title: str = Field(description="Under 70 characters, specific, no clickbait punctuation")
    hook: str = Field(description="The clip's opening line, verbatim from the transcript")
    one_sentence_summary: str = Field(description="One sentence on what the clip actually says")
    why_selected: str = Field(description="One sentence on why this works as a short")
    suggested_caption: str = Field(description="2-3 lines for the post body, no hashtags inline")
    suggested_thumbnail_text: str = Field(description="3-6 words, upper case, high contrast")
    suggested_hashtags: list[str] = Field(
        description="4-6 topical hashtags including the leading #",
        min_length=1,
        max_length=10,
    )
    target_audience: str = Field(description="Who specifically would watch this")


class FinalClipOutput(BaseModel):
    id: str
    rank: int = Field(ge=1)
    title: str
    start_timestamp: str  # "MM:SS" or "HH:MM:SS"
    end_timestamp: str
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    duration_seconds: float = Field(gt=0.0)
    # Numeric, derived from word timings and measured silence.
    start_adjustment_sec: float = 0.0
    end_adjustment_sec: float = 0.0
    adjustment_rationale: str = ""
    adjusted_start_seconds: float = Field(ge=0.0)
    adjusted_end_seconds: float = Field(ge=0.0)
    hook: str
    one_sentence_summary: str
    why_this_clip_was_selected: str
    viewer_retention_prediction: str
    virality_score: float = Field(ge=0.0, le=10.0)
    confidence_score: float = Field(ge=0.0, le=10.0)
    overall_score: float = Field(ge=0.0, le=10.0)
    target_platform: list[str]
    target_audience: str
    suggested_caption: str
    suggested_thumbnail_text: str
    suggested_hashtags: list[str]
    agent_evaluations: dict[str, ClipEvaluation] = Field(default_factory=dict)
    # Set once the render node has produced a file.
    rendered_file_path: str | None = None
    provenance: DataProvenance | None = None

    @model_validator(mode="after")
    def _check_range(self) -> FinalClipOutput:
        if self.end_seconds <= self.start_seconds:
            raise ValueError(
                f"clip {self.id}: end {self.end_seconds} must exceed start {self.start_seconds}"
            )
        return self
