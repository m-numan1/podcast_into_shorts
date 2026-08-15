"""Fast JSON timestamp clip trimmer and batch renderer.

Provides instant cutting of video/audio clips from JSON timestamp metadata
without running full transcription or AI model evaluations.

Supports:
  * Fast stream copy mode (`fast_mode=True`): Cuts clips in < 0.5s with zero
    quality loss and minimal CPU usage.
  * Vertical render mode (`fast_mode=False`): Uses ClipRenderer to produce 9:16
    vertical MP4s with captions and background blur.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from config.settings import settings
from src.errors import PipelineError, RenderError
from src.providers import ffmpeg_tools
from src.utils.logging_config import get_logger

log = get_logger(__name__)


def parse_timestamp(val: Any) -> float:
    """Parse timestamp value (float, int, or 'MM:SS' / 'HH:MM:SS' string) to seconds."""
    if isinstance(val, (int, float)):
        return max(0.0, float(val))
    if not isinstance(val, str):
        raise ValueError(f"Invalid timestamp format: {val!r}")

    text = val.strip()
    # Check for seconds float format "60.5"
    try:
        return max(0.0, float(text))
    except ValueError:
        log.debug("Timestamp %r is not a raw float, trying HH:MM:SS format", val)


    # Match HH:MM:SS or MM:SS
    parts = text.split(":")
    if len(parts) == 2:
        # MM:SS
        m, s = float(parts[0]), float(parts[1])
        return max(0.0, m * 60 + s)
    elif len(parts) == 3:
        # HH:MM:SS
        h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
        return max(0.0, h * 3600 + m * 60 + s)

    raise ValueError(f"Unrecognized timestamp format: {val!r}")


def parse_timestamp_range(val: str) -> tuple[float, float]:
    """Parse range string like '1:00 to 1:05' or '01:00-01:05' into (start, end)."""
    text = val.strip()
    match = re.search(r"(.+?)\s*(?:to|->|-)\s*(.+)", text, re.IGNORECASE)
    if match:
        start = parse_timestamp(match.group(1))
        end = parse_timestamp(match.group(2))
        return start, end
    raise ValueError(f"Cannot parse timestamp range: {val!r}")



def extract_clip_timestamps(clip_data: dict[str, Any]) -> tuple[float, float, str, str]:
    """Extract (start_sec, end_sec, title, clip_id) from clip dictionary."""
    clip_id = str(clip_data.get("id") or "clip_001")
    title = str(clip_data.get("title") or clip_id)

    # Check numeric seconds fields first
    if "adjusted_start_seconds" in clip_data and "adjusted_end_seconds" in clip_data:
        start = float(clip_data["adjusted_start_seconds"])
        end = float(clip_data["adjusted_end_seconds"])
        return start, end, title, clip_id

    if "start_seconds" in clip_data and "end_seconds" in clip_data:
        start = float(clip_data["start_seconds"])
        end = float(clip_data["end_seconds"])
        return start, end, title, clip_id

    if "start_time" in clip_data and "end_time" in clip_data:
        start = parse_timestamp(clip_data["start_time"])
        end = parse_timestamp(clip_data["end_time"])
        return start, end, title, clip_id

    # Check formatted string fields
    if "start_timestamp" in clip_data and "end_timestamp" in clip_data:
        start = parse_timestamp(clip_data["start_timestamp"])
        end = parse_timestamp(clip_data["end_timestamp"])
        return start, end, title, clip_id

    if "start" in clip_data and "end" in clip_data:
        start = parse_timestamp(clip_data["start"])
        end = parse_timestamp(clip_data["end"])
        return start, end, title, clip_id

    # Check if there is a single timestamp string range e.g. "timestamp": "1:00 to 1:05"
    if "timestamp" in clip_data:
        start, end = parse_timestamp_range(str(clip_data["timestamp"]))
        return start, end, title, clip_id

    raise ValueError(f"Clip object missing start/end timestamp fields: {clip_data}")


class ClipTrimmer:
    """Fast clip trimmer that cuts videos directly based on timestamp JSONs."""

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or settings.render_dir

    def trim_fast_copy(
        self,
        media_path: str | Path,
        start_sec: float,
        end_sec: float,
        out_path: Path,
    ) -> Path:
        """Fast cut using ffmpeg stream copy (-c copy). Cuts in <0.5s."""
        source = Path(media_path)
        if not source.exists():
            raise RenderError(f"Source file not found: {source}")

        duration = max(0.1, end_sec - start_sec)
        binary = ffmpeg_tools.ffmpeg_path()

        args = [
            binary, "-y", "-hide_banner",
            "-accurate_seek",
            "-ss", f"{start_sec:.3f}",
            "-t", f"{duration:.3f}",
            "-i", str(source),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            str(out_path),
        ]

        ffmpeg_tools.run(
            args,
            error_cls=RenderError,
            what=f"fast stream-copy trim to {out_path.name}",
        )

        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RenderError(f"Fast trim produced no output file at {out_path}")

        return out_path

    def trim_clip(
        self,
        media_path: str | Path,
        clip_data: dict[str, Any],
        *,
        fast_mode: bool = True,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Trim one clip based on timestamp dictionary."""
        out_dir = output_dir or self.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        start, end, title, clip_id = extract_clip_timestamps(clip_data)
        safe_id = re.sub(r"[^0-9A-Za-z_-]", "_", clip_id)
        out_filename = f"{safe_id}_fast.mp4" if fast_mode else f"{safe_id}.mp4"
        out_path = out_dir / out_filename

        log.info("Trimming clip %s (%.1fs -> %.1fs, fast=%s)", clip_id, start, end, fast_mode)

        if fast_mode:
            self.trim_fast_copy(media_path, start, end, out_path)
        else:
            # Reframe mode via ClipRenderer if model available
            from src.providers.renderer import ClipRenderer
            from src.schema.clips import FinalClipOutput

            renderer = ClipRenderer()
            # Construct a basic FinalClipOutput object if needed
            duration = max(0.1, end - start)
            formatted_clip = FinalClipOutput(
                id=clip_id,
                rank=int(clip_data.get("rank", 1)),
                title=title,
                start_timestamp=f"{int(start//60):02d}:{int(start%60):02d}",
                end_timestamp=f"{int(end//60):02d}:{int(end%60):02d}",
                start_seconds=start,
                end_seconds=end,
                duration_seconds=duration,
                adjusted_start_seconds=start,
                adjusted_end_seconds=end,
                hook=str(clip_data.get("hook", title)),
                one_sentence_summary=str(clip_data.get("one_sentence_summary", title)),
                why_this_clip_was_selected=str(clip_data.get("why_this_clip_was_selected", "")),
                viewer_retention_prediction=str(clip_data.get("viewer_retention_prediction", "")),
                virality_score=float(clip_data.get("virality_score", 8.0)),
                confidence_score=float(clip_data.get("confidence_score", 8.0)),
                overall_score=float(clip_data.get("overall_score", 8.0)),
                target_platform=list(clip_data.get("target_platform", ["TikTok"])),
                target_audience=str(clip_data.get("target_audience", "General")),
                suggested_caption=str(clip_data.get("suggested_caption", "")),
                suggested_thumbnail_text=str(clip_data.get("suggested_thumbnail_text", "")),
                suggested_hashtags=list(clip_data.get("suggested_hashtags", ["#shorts"])),
            )
            has_vid = ffmpeg_tools.probe_has_video_stream(media_path)
            res = renderer.render(
                clip=formatted_clip,
                media_path=str(media_path),
                units=[],
                all_words=[],
                has_video=has_vid,
                output_dir=out_dir,
            )
            out_path = Path(res.output_path)

        result_clip = dict(clip_data)
        result_clip["rendered_file_path"] = str(out_path.resolve())
        return result_clip

    def trim_all_from_json(
        self,
        media_path: str | Path,
        json_input: str | Path | dict[str, Any] | list[dict[str, Any]],
        *,
        fast_mode: bool = True,
        output_dir: Path | None = None,
    ) -> list[dict[str, Any]]:
        """Batch trim all clips specified in a JSON file or object."""
        if isinstance(json_input, (str, Path)):
            path = Path(json_input)
            if not path.exists():
                raise PipelineError(f"JSON input file not found: {path}")
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = json_input

        # Handle different top-level JSON structures
        if isinstance(data, dict):
            clips_list = data.get("clips") or data.get("final_clips") or [data]
        elif isinstance(data, list):
            clips_list = data
        else:
            raise ValueError(f"Invalid JSON data structure: {type(data)}")

        if not clips_list:
            log.warning("No clips found in JSON data for batch trimming.")
            return []

        out_dir = output_dir or self.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        rendered_clips: list[dict[str, Any]] = []
        for idx, clip in enumerate(clips_list, 1):
            if not isinstance(clip, dict):
                continue
            if "id" not in clip:
                clip["id"] = f"clip_{idx:03d}"
            try:
                processed = self.trim_clip(
                    media_path=media_path,
                    clip_data=clip,
                    fast_mode=fast_mode,
                    output_dir=out_dir,
                )
                rendered_clips.append(processed)
            except Exception as exc:
                log.error("Failed to trim clip #%d (%s): %s", idx, clip.get("id"), exc)
                clip["error"] = str(exc)
                rendered_clips.append(clip)

        return rendered_clips
