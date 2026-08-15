"""CLI entry point.

Behaviour changes from the original:
  * checks `final_state.error` and exits non-zero -- the original printed
    "[SUCCESS] Pipeline execution complete!" unconditionally, including for runs
    that produced zero clips or failed outright;
  * prints a provenance banner, so synthetic or heuristic output is never
    mistaken for a real model-scored analysis of real media;
  * validates `--output` stays inside the output directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from config.settings import settings
from src.errors import ConfigError
from src.utils.logging_config import setup_logging

EXIT_OK = 0
EXIT_PIPELINE_ERROR = 1
EXIT_NO_CLIPS = 2
EXIT_BAD_USAGE = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="podcast-into-shorts",
        description="Find and render short vertical clips from long-form audio or video.",
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--source",
        help="YouTube URL or path to a local audio/video file.",
    )
    src.add_argument(
        "--demo",
        action="store_true",
        help="Run on the bundled synthetic fixture transcript. Output is clearly "
             "marked and is not an analysis of real media.",
    )
    parser.add_argument(
        "--output", default="final_clips.json",
        help="Output JSON filename, written inside the outputs directory.",
    )
    parser.add_argument(
        "--trim-json", default=None,
        help="Path to a JSON file (e.g. final_clips.json or timestamp list) to "
             "batch cut MP4 clips directly from --source without re-running transcription.",
    )
    parser.add_argument(
        "--fast", action="store_true", default=True,
        help="Fast cut using stream-copy (-c copy) for instant trimming (< 0.5s per clip).",
    )
    parser.add_argument(
        "--full-render", action="store_true",
        help="Force full 9:16 vertical re-frame render instead of fast stream-copy.",
    )
    parser.add_argument(
        "--render", action="store_true",
        help="Also encode the top clips to vertical MP4 with burned captions "
             "(requires ffmpeg).",
    )

    parser.add_argument(
        "--max-clips", type=int, default=None,
        help=f"Maximum clips to publish (default {settings.target_clip_count_max}).",
    )
    parser.add_argument(
        "--log-level", default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default from LOG_LEVEL, else INFO).",
    )
    parser.add_argument(
        "--thread-id", default="cli",
        help="Checkpoint thread id; reuse it to resume an interrupted run.",
    )
    parser.add_argument(
        "--no-checkpoint", action="store_true",
        help="Disable checkpointing for this run.",
    )
    return parser


def resolve_output_path(filename: str) -> Path:
    """Resolve `filename` inside the output directory, rejecting traversal.

    `--output ../../etc/whatever` previously wrote wherever it pointed, because
    `settings.output_dir / filename` happily accepts absolute paths and `..`.
    """
    candidate = (settings.output_dir / filename).resolve()
    root = settings.output_dir.resolve()
    if root not in candidate.parents and candidate != root:
        raise ConfigError(
            f"--output must stay inside {root}; got {candidate}",
            "Pass a bare filename such as final_clips.json.",
        )
    return candidate


def print_banner(state) -> None:
    provenance = state.provenance()
    width = 78
    print("=" * width)
    print(" PODCAST -> SHORTS".center(width))
    print("=" * width)
    print(f" Episode      : {state.podcast_title}")
    print(f" Duration     : {state.duration_seconds:.1f}s")
    print(f" Provenance   : {provenance.banner()}")
    if provenance.is_synthetic:
        print()
        print(" !! SYNTHETIC DATA: these results describe a bundled fixture,".center(width))
        print(" !! not real media. Do not publish or act on them.".center(width))
    # Only relevant when there are results to interpret.
    if provenance.scoring_mode == "heuristic" and state.final_clips:
        print()
        print(" NOTE: scored without a language model. Rankings come from measured")
        print("       signals only (pauses, cue density, boundary cleanliness) and")
        print("       are a weak proxy for editorial judgement. Set")
        print("       DEFAULT_LLM_PROVIDER and an API key for model scoring.")
    print("=" * width)


def print_clips(state) -> None:
    print()
    print(f"--- {len(state.final_clips)} CLIPS ---")
    for clip in state.final_clips:
        print()
        print(f"[#{clip.rank}] {clip.title}")
        print(f"   {clip.start_timestamp} -> {clip.end_timestamp}  ({clip.duration_seconds:.1f}s)")
        print(f"   adjust: start {clip.start_adjustment_sec:+.2f}s, end {clip.end_adjustment_sec:+.2f}s")
        print(f"           {clip.adjustment_rationale}")
        print(f"   hook  : \"{clip.hook}\"")
        print(f"   sum   : {clip.one_sentence_summary}")
        print(f"   score : overall {clip.overall_score:.2f}  virality {clip.virality_score:.2f}"
              f"  confidence {clip.confidence_score:.2f}  (all /10)")
        print(f"   retain: {clip.viewer_retention_prediction}")
        print(f"   why   : {clip.why_this_clip_was_selected}")
        print(f"   tags  : {' '.join(clip.suggested_hashtags)}")
        if clip.rendered_file_path:
            print(f"   render: {clip.rendered_file_path}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.log_level or settings.log_level)

    if args.max_clips is not None:
        if args.max_clips < 1:
            print("--max-clips must be at least 1", file=sys.stderr)
            return EXIT_BAD_USAGE
        settings.target_clip_count_max = args.max_clips
        # An explicit cap is the user's decision, so do not then warn that the
        # result is below the configured minimum.
        settings.target_clip_count_min = min(
            settings.target_clip_count_min, args.max_clips
        )

    try:
        settings.ensure_directories()
        out_file = resolve_output_path(args.output)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_BAD_USAGE

    if args.trim_json:
        if not args.source and not args.demo:
            print("Error: --source media path or --demo is required when using --trim-json", file=sys.stderr)
            return EXIT_BAD_USAGE

        from src.providers.trimmer import ClipTrimmer

        trimmer = ClipTrimmer()
        source_media = args.source
        if args.demo:
            source_media = str(settings.cache_dir / "synthetic_demo.mp4")

        fast_cut = not args.full_render
        print(f"--- FAST JSON BATCH TRIMMER ---")
        print(f"  Source Media : {source_media}")
        print(f"  JSON Input   : {args.trim_json}")
        print(f"  Cut Mode     : {'Fast Stream-Copy (-c copy)' if fast_cut else 'Vertical Reframe (9:16)'}")
        print()

        try:
            trimmed = trimmer.trim_all_from_json(
                media_path=source_media,
                json_input=args.trim_json,
                fast_mode=fast_cut,
            )
            print(f"Successfully trimmed {len(trimmed)} clip(s) to {settings.render_dir}:")
            for item in trimmed:
                path = item.get("rendered_file_path") or item.get("error")
                print(f"  * [{item.get('id', 'clip')}] {item.get('title', 'Clip')}: {path}")
            return EXIT_OK
        except Exception as exc:
            print(f"Error during JSON trimming: {exc}", file=sys.stderr)
            return EXIT_PIPELINE_ERROR

    # Imported here so --help works without pulling in langgraph.
    from src.graph.workflow import VideoEditorPipeline


    pipeline = VideoEditorPipeline(use_checkpointer=not args.no_checkpoint)
    state = pipeline.run(
        args.source or "",
        demo_mode=args.demo,
        render=args.render,
        thread_id=args.thread_id,
    )

    print_banner(state)

    if state.warnings:
        print()
        print("--- WARNINGS ---")
        for warning in state.warnings:
            print(f"  ! {warning}")

    if state.error:
        print()
        print("--- FAILED ---")
        print(f"  stage : {state.failed_stage}")
        print(f"  reason: {state.error}")
        print()
        print("  Pipeline log:")
        for line in state.logs:
            print(f"    {line}")
        return EXIT_PIPELINE_ERROR

    if not state.final_clips:
        print()
        print("No clips were produced. Pipeline log:")
        for line in state.logs:
            print(f"    {line}")
        return EXIT_NO_CLIPS

    print_clips(state)

    payload = {
        "episode": state.podcast_title,
        "duration_seconds": state.duration_seconds,
        "provenance": state.provenance().model_dump(mode="json"),
        "is_synthetic": state.provenance().is_synthetic,
        "warnings": state.warnings,
        "clips": [clip.model_dump(mode="json") for clip in state.final_clips],
    }
    out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print()
    print(f"Wrote {len(state.final_clips)} clips to {out_file}")
    if state.rendered_files:
        print(f"Rendered {len(state.rendered_files)} MP4(s) to {settings.render_dir}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
