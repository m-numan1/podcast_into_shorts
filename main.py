import sys
import json
import argparse
from pathlib import Path
from src.graph.workflow import VideoEditorPipeline
from config.settings import settings

def print_banner():
    print("=" * 80)
    print(" [AI VIDEO EDITOR FOR PODCASTERS] - LANGGRAPH MULTI-AGENT PIPELINE")
    print("=" * 80)

def main():
    print_banner()
    parser = argparse.ArgumentParser(description="AI Video Editor for Podcasters")
    parser.add_argument("--source", type=str, default="https://www.youtube.com/watch?v=sample_podcast_episode", help="YouTube URL or local video/audio file path")
    parser.add_argument("--output", type=str, default="final_clips.json", help="Output JSON filename")
    args = parser.parse_args()

    print(f">> Input Source: {args.source}")
    print(f">> Initializing 8-Node LangGraph StateMachine & 6 Specialized AI Editor Agents...")
    
    pipeline = VideoEditorPipeline()
    final_state = pipeline.run(args.source)
    
    print("\n" + "=" * 80)
    print(" PIPELINE EXECUTION LOGS")
    print("=" * 80)
    for log in final_state.logs:
        print(f"  -> {log}")
        
    print("\n" + "=" * 80)
    print(f" FINAL TOP RECOMMENDATIONS ({len(final_state.final_clips)} PUBLISH-READY CLIPS)")
    print("=" * 80)
    
    output_clips_data = []
    for clip in final_state.final_clips:
        clip_dict = clip.model_dump()
        output_clips_data.append(clip_dict)
        print(f"\n[RANK #{clip.rank}] {clip.title.upper()}")
        print(f"   Timestamps: [{clip.start_timestamp} -> {clip.end_timestamp}] ({clip.duration_seconds:.1f}s)")
        print(f"   Adjustments: Start ({clip.suggested_start_adjustment}) | End ({clip.suggested_end_adjustment})")
        print(f"   Hook: \"{clip.hook}\"")
        print(f"   One-Sentence Summary: {clip.one_sentence_summary}")
        print(f"   Virality Score: {clip.virality_score:.1f}/10 | Confidence: {clip.confidence_score:.1f}/10")
        print(f"   Why Selected: {clip.why_this_clip_was_selected}")
        print(f"   Retention Prediction: {clip.viewer_retention_prediction}")
        print(f"   Target Platforms: {', '.join(clip.target_platform)}")
        print(f"   Thumbnail Text: \"{clip.suggested_thumbnail_text}\"")
        print(f"   Caption: {clip.suggested_caption}")
        print(f"   Hashtags: {' '.join(clip.suggested_hashtags)}")
        print("   " + "-" * 70)

    out_file = settings.output_dir / args.output
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output_clips_data, f, indent=2)
        
    print(f"\n[SUCCESS] Pipeline execution complete! Full structured recommendations saved to: {out_file.resolve()}")

if __name__ == "__main__":
    main()
