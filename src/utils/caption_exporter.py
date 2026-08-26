"""Utility to format and export full video transcripts and short clip captions to .txt files."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from config.settings import settings
from src.utils.logging_config import get_logger

if TYPE_CHECKING:
    from src.schema.state import EditorState

log = get_logger(__name__)


def _format_seconds(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS string."""
    seconds = max(0.0, seconds)
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def _slugify(text: str) -> str:
    """Convert string to safe filename slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:50] or "captions"


def generate_captions_text(state: EditorState) -> str:
    """Format full video transcript and short clips captions into a readable text document."""
    lines: list[str] = []
    sep_double = "=" * 80
    sep_single = "-" * 80
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    provenance = state.provenance()

    # HEADER
    lines.append(sep_double)
    lines.append("                       PODCAST TO SHORTS: CAPTIONS & TRANSCRIPT REPORT")
    lines.append(sep_double)
    lines.append(f"Episode Title   : {state.podcast_title}")
    lines.append(f"Source / File   : {state.source or state.media_file_path or 'N/A'}")
    lines.append(f"Duration        : {_format_seconds(state.duration_seconds)} ({state.duration_seconds:.1f}s)")
    lines.append(f"Generated On    : {now_str}")
    lines.append(f"Scoring Mode    : {state.scoring_mode.upper()}")
    lines.append(f"Media Source    : {provenance.media_source}")
    lines.append(f"Transcript Source: {provenance.transcript_source}")
    lines.append(f"Total Shorts    : {len(state.final_clips)}")
    lines.append(sep_double)
    lines.append("")

    # PART 1: COMPLETE VIDEO TRANSCRIPT
    lines.append(sep_single)
    lines.append("PART 1: COMPLETE VIDEO TRANSCRIPT & CAPTIONS")
    lines.append(sep_single)

    units = state.sentence_units
    if not units and state.transcript_segments:
        # Fallback if sentence units were not built
        for seg in state.transcript_segments:
            t_start = _format_seconds(seg.start)
            t_end = _format_seconds(seg.end)
            lines.append(f"[{t_start} - {t_end}] {seg.speaker}: {seg.text}")
    elif units:
        for u in units:
            t_start = _format_seconds(u.start)
            t_end = _format_seconds(u.end)
            lines.append(f"[{t_start} - {t_end}] {u.speaker}: {u.text}")
    else:
        lines.append("(No transcript segments available for this video)")

    lines.append("")
    lines.append("")

    # PART 2: EXTRACTED SHORTS & CAPTIONS
    lines.append(sep_single)
    lines.append(f"PART 2: EXTRACTED SHORTS & CAPTIONS ({len(state.final_clips)} SHORTS GENERATED)")
    lines.append(sep_single)
    lines.append("")

    if not state.final_clips:
        lines.append("No short clips were extracted.")
    else:
        for idx, clip in enumerate(state.final_clips, start=1):
            lines.append(sep_double)
            lines.append(f"SHORT #{clip.rank}: {clip.title}")
            lines.append(sep_double)
            lines.append(f"• Rank            : #{clip.rank}")
            lines.append(f"• Timestamp Range : {clip.start_timestamp} -> {clip.end_timestamp} ({clip.duration_seconds:.1f}s)")
            lines.append(f"• Adjusted Cut    : {clip.start_adjustment_sec:+.2f}s start / {clip.end_adjustment_sec:+.2f}s end")
            lines.append(f"• Overall Score   : {clip.overall_score:.2f} / 10")
            lines.append(f"• Virality Score  : {clip.virality_score:.2f} / 10")
            lines.append(f"• Confidence Score: {clip.confidence_score:.2f} / 10")
            lines.append(f"• Retention Pred. : {clip.viewer_retention_prediction}")
            lines.append(f"• Target Audience : {clip.target_audience}")
            lines.append(f"• Hook Line       : \"{clip.hook}\"")
            lines.append(f"• Summary         : {clip.one_sentence_summary}")
            lines.append(f"• Selection Why   : {clip.why_this_clip_was_selected}")
            lines.append("")
            lines.append("--- RECOMMENDED SOCIAL MEDIA CAPTION ---")
            lines.append(f"Title    : {clip.title}")
            lines.append(f"Caption  : {clip.suggested_caption}")
            lines.append(f"Hashtags : {' '.join(clip.suggested_hashtags)}")
            lines.append("")
            lines.append("--- VERBATIM SHORT TRANSCRIPT & CAPTIONS ---")

            # Extract matching sentence units for this clip
            clip_start = clip.adjusted_start_seconds if clip.adjusted_start_seconds > 0 else clip.start_seconds
            clip_end = clip.adjusted_end_seconds if clip.adjusted_end_seconds > 0 else clip.end_seconds

            clip_units = [
                u for u in units
                if (u.start >= clip_start - 1.0 and u.end <= clip_end + 1.0)
                or (u.start <= clip_start and u.end >= clip_start)
                or (u.start <= clip_end and u.end >= clip_end)
            ]

            if clip_units:
                for u in clip_units:
                    t_start = _format_seconds(u.start)
                    t_end = _format_seconds(u.end)
                    lines.append(f"  [{t_start} - {t_end}] {u.speaker}: {u.text}")
            else:
                lines.append(f"  \"{clip.hook}\"")

            if clip.rendered_file_path:
                lines.append("")
                lines.append(f"Rendered Video File: {clip.rendered_file_path}")

            lines.append("")
            lines.append("")

    return "\n".join(lines)


def export_captions_to_txt(state: EditorState, output_dir: Path | str | None = None) -> Path:
    """Export formatted captions and transcripts to a TXT file in the outputs directory."""
    out_dir = Path(output_dir) if output_dir else settings.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    text_content = generate_captions_text(state)

    # Write master captions.txt
    master_file = out_dir / "captions.txt"
    master_file.write_text(text_content, encoding="utf-8")
    log.info("Wrote master captions TXT to %s", master_file)

    # Write episode-specific captions file if podcast title is available
    slug_title = _slugify(state.podcast_title)
    if slug_title and slug_title != "captions":
        named_file = out_dir / f"{slug_title}_captions.txt"
        named_file.write_text(text_content, encoding="utf-8")
        log.info("Wrote named captions TXT to %s", named_file)

    return master_file
