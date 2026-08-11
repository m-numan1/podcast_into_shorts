from typing import List
from src.schema.state import EditorState
from src.schema.clips import CandidateClip, ExtractedFeatures
from config.settings import settings

def node_07_candidates(state: EditorState) -> dict:
    """
    Node 7: Generate candidate clips. Every candidate must represent ONE complete idea.
    No mechanical cutting. Aligned strictly to semantic chunk boundaries.
    """
    logs = list(state.logs)
    logs.append("[Node 7] Building candidate clips representing standalone complete ideas...")
    
    chunks = state.semantic_chunks
    features_map = state.extracted_features
    candidates: List[CandidateClip] = []
    
    if not chunks:
        return {
            "error": "No semantic chunks available to build candidates in Node 7.",
            "logs": logs + ["[Node 7] ERROR: No semantic chunks available."]
        }

    candidate_idx = 1
    
    for c in chunks:
        dur = c.end - c.start
        if settings.min_clip_duration_sec <= dur <= settings.max_clip_duration_sec:
            feat = features_map.get(c.id, ExtractedFeatures(chunk_id=c.id))
            candidates.append(CandidateClip(
                id=f"cand_{candidate_idx:03d}",
                start_time=c.start,
                end_time=c.end,
                duration=round(dur, 2),
                raw_text=c.text,
                semantic_chunk_ids=[c.id],
                feature_summary=feat
            ))
            candidate_idx += 1
            
    for i in range(len(chunks) - 1):
        c1, c2 = chunks[i], chunks[i+1]
        combined_dur = c2.end - c1.start
        if settings.min_clip_duration_sec <= combined_dur <= settings.max_clip_duration_sec:
            f1 = features_map.get(c1.id, ExtractedFeatures(chunk_id=c1.id))
            f2 = features_map.get(c2.id, ExtractedFeatures(chunk_id=c2.id))
            merged_feat = ExtractedFeatures(
                chunk_id=f"{c1.id}+{c2.id}",
                emotion_label=f1.emotion_label,
                curiosity_score=max(f1.curiosity_score, f2.curiosity_score),
                strong_statement_score=max(f1.strong_statement_score, f2.strong_statement_score),
                story_likelihood=max(f1.story_likelihood, f2.story_likelihood),
                question_count=f1.question_count + f2.question_count,
                named_entities=list(set(f1.named_entities + f2.named_entities))
            )
            candidates.append(CandidateClip(
                id=f"cand_{candidate_idx:03d}",
                start_time=c1.start, end_time=c2.end,
                duration=round(combined_dur, 2),
                raw_text=f"{c1.text} {c2.text}",
                semantic_chunk_ids=[c1.id, c2.id],
                feature_summary=merged_feat
            ))
            candidate_idx += 1

    logs.append(f"[Node 7] Generated {len(candidates)} candidate clips.")
    
    return {
        "candidate_clips": candidates,
        "current_node": "NODE_07_CANDIDATES_COMPLETE",
        "logs": logs
    }
