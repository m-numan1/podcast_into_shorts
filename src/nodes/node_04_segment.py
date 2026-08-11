from typing import List
from src.schema.state import EditorState
from src.schema.clips import SemanticChunk, TranscriptSegment

def node_04_segment(state: EditorState) -> dict:
    """
    Node 4: Perform semantic segmentation.
    CRITICAL RULE: Never split by token count. Split ONLY when topics naturally change.
    """
    logs = list(state.logs)
    logs.append("[Node 4] Performing topic-based semantic segmentation (no token count splits)...")
    
    segments = state.transcript_segments
    if not segments:
        return {
            "error": "No transcript segments found for Node 4 semantic segmentation.",
            "logs": logs + ["[Node 4] ERROR: No transcript segments available."]
        }
        
    semantic_chunks: List[SemanticChunk] = []
    
    # Topic transition signals
    topic_indicators = [
        "welcome", "today we're", "the truth is", "concrete example",
        "so what is the", "rule number one", "that is incredible", "precisely",
        "let me tell you", "here's the thing", "what people don't realize",
        "the key takeaway", "moving on", "another important", "speaking of",
        "discovered", "unprecedented", "breakthrough", "unseen", "remarkable"
    ]
    
    current_group: List[TranscriptSegment] = []
    chunk_index = 1
    
    for idx, seg in enumerate(segments):
        text_lower = seg.text.lower()
        
        # Check if natural boundary occurs (Question shift, strong transition indicator, or speaker turn change after complete idea)
        is_topic_boundary = False
        boundary_reason = "natural flow"
        
        if any(ind in text_lower for ind in topic_indicators) and current_group:
            is_topic_boundary = True
            boundary_reason = "Linguistic topic transition indicator detected"
        elif seg.speaker != current_group[-1].speaker if current_group else False:
            if len(current_group) >= 2 and "?" in current_group[-1].text:
                is_topic_boundary = True
                boundary_reason = "Speaker role transition following question"

        if is_topic_boundary and current_group:
            chunk_start = current_group[0].start
            chunk_end = current_group[-1].end
            combined_text = " ".join([s.text for s in current_group])
            summary = current_group[0].text[:60] + "..."
            
            semantic_chunks.append(SemanticChunk(
                id=f"chunk_{chunk_index:03d}",
                start=chunk_start,
                end=chunk_end,
                text=combined_text,
                topic_summary=summary,
                key_concepts=[w for w in combined_text.split() if len(w) > 6][:4],
                boundary_reason=boundary_reason
            ))
            chunk_index += 1
            current_group = [seg]
        else:
            current_group.append(seg)
            
    # Add final group
    if current_group:
        chunk_start = current_group[0].start
        chunk_end = current_group[-1].end
        combined_text = " ".join([s.text for s in current_group])
        semantic_chunks.append(SemanticChunk(
            id=f"chunk_{chunk_index:03d}",
            start=chunk_start,
            end=chunk_end,
            text=combined_text,
            topic_summary=current_group[0].text[:60] + "...",
            key_concepts=[w for w in combined_text.split() if len(w) > 6][:4],
            boundary_reason="End of transcript segment sequence"
        ))
    
    logs.append(f"[Node 4] Semantic segmentation complete. Generated {len(semantic_chunks)} natural topic chunks.")
    
    return {
        "semantic_chunks": semantic_chunks,
        "current_node": "NODE_04_SEGMENT_COMPLETE",
        "logs": logs
    }
