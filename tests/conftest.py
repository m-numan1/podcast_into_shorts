"""Shared fixtures.

Deliberately builds transcripts in the two shapes that behave very differently:

  * `caption_segments` -- YouTube auto-caption shape: 2-4 second fragments, no
    punctuation, no speaker data, no pauses. This is the shape that broke the
    original pipeline, and it is the default for any YouTube source.
  * `punctuated_segments` -- Whisper/clean shape: sentence-length segments with
    terminators, inter-sentence pauses and alternating speakers.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.schema.clips import (
    CandidateClip,
    ExtractedFeatures,
    SentenceUnit,
    TranscriptSegment,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _docstrings(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            text = ast.get_docstring(node, clean=False)
            if text is not None:
                found.add(text)
    return found


def code_string_literals(relative_path: str) -> list[str]:
    """String literals in a module, excluding docstrings.

    Several tests assert that specific phrases are not used as *scoring
    keywords*. A plain substring scan over the file also matches the docstrings
    that document what was removed, so those tests must look at code only.
    """
    tree = ast.parse((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
    skip = _docstrings(tree)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in skip
    ]


def code_identifiers(relative_path: str) -> set[str]:
    """Defined function/class names plus every referenced attribute and name."""
    tree = ast.parse((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names

FRAGMENTS = [
    "so the thing about building a company", "is that you have to understand",
    "your customer better than anyone else", "and most people skip that part",
    "they go straight to the product", "which is honestly backwards",
    "i learned this the hard way", "we spent eight months on features",
    "nobody actually wanted any of them", "so we threw it all away",
    "started over talking to users", "twenty conversations a week",
    "and that changed everything for us", "revenue went up four times",
    "in about six months", "it was not magic it was listening",
    "the second thing is pricing", "everyone underprices at the start",
    "because they are afraid of rejection", "but low price signals low value",
    "we doubled our price twice", "and churn actually went down",
    "which surprised our whole team", "the customers we lost were the wrong ones",
    "so my advice is charge more", "and talk to people constantly",
]


def make_caption_segments(
    count: int, fragment_duration: float = 3.0, gap: float = 0.0
) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    cursor = 0.0
    for i in range(count):
        segments.append(
            TranscriptSegment(
                id=i + 1,
                start=round(cursor, 3),
                end=round(cursor + fragment_duration, 3),
                text=FRAGMENTS[i % len(FRAGMENTS)],
                speaker="Speaker_A",
            )
        )
        cursor += fragment_duration + gap
    return segments


def make_punctuated_segments(
    count: int, segment_duration: float = 4.0, gap: float = 0.8
) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    cursor = 0.0
    for i in range(count):
        text = FRAGMENTS[i % len(FRAGMENTS)].capitalize() + "."
        segments.append(
            TranscriptSegment(
                id=i + 1,
                start=round(cursor, 3),
                end=round(cursor + segment_duration, 3),
                text=text,
                speaker="Speaker_A" if i % 4 < 2 else "Speaker_B",
            )
        )
        cursor += segment_duration + gap
    return segments


@pytest.fixture
def caption_segments() -> list[TranscriptSegment]:
    """26 caption fragments, ~78 seconds."""
    return make_caption_segments(26)


@pytest.fixture
def long_caption_segments() -> list[TranscriptSegment]:
    """600 caption fragments, ~30 minutes. The §4 regression input."""
    return make_caption_segments(600)


@pytest.fixture
def punctuated_segments() -> list[TranscriptSegment]:
    """60 punctuated segments with pauses and speaker turns, ~288 seconds."""
    return make_punctuated_segments(60)


def make_unit(
    unit_id: int,
    start: float,
    end: float,
    text: str = "some words here",
    *,
    ends_sentence: bool = True,
    gap_before: float = 0.5,
    speaker: str = "Speaker_A",
) -> SentenceUnit:
    return SentenceUnit(
        id=unit_id,
        start=start,
        end=end,
        text=text,
        speaker=speaker,
        segment_ids=[unit_id],
        gap_before=gap_before,
        ends_sentence=ends_sentence,
    )


def make_candidate(
    candidate_id: str,
    start: float,
    end: float,
    *,
    text: str = "A complete thought about pricing and customers.",
    features: ExtractedFeatures | None = None,
    starts_clean: bool = True,
    ends_clean: bool = True,
) -> CandidateClip:
    return CandidateClip(
        id=candidate_id,
        start_time=start,
        end_time=end,
        duration=end - start,
        raw_text=text,
        semantic_chunk_ids=[f"chunk_{candidate_id}"],
        feature_summary=features or ExtractedFeatures(chunk_id=f"chunk_{candidate_id}"),
        starts_on_sentence_boundary=starts_clean,
        ends_on_sentence_boundary=ends_clean,
        lead_in_silence_sec=0.6,
        lead_out_silence_sec=0.4,
    )
