from typing import Dict, Any
from langgraph.graph import StateGraph, START, END
from src.schema.state import EditorState
from src.nodes import (
    node_01_download,
    node_02_audio,
    node_03_transcribe,
    node_04_segment,
    node_05_index,
    node_06_features,
    node_07_candidates,
    node_08_editors
)

def _should_continue(state: EditorState) -> str:
    """Conditional edge: short-circuit pipeline if any node set an error."""
    if state.error:
        return "abort"
    return "continue"

def _abort_node(state: EditorState) -> dict:
    """Terminal node reached when a pipeline error is detected."""
    return {
        "current_node": "ABORTED",
        "logs": state.logs + [f"[ABORT] Pipeline halted due to error: {state.error}"]
    }

def create_editor_graph():
    """
    Assembles and compiles the full AI Video Editor LangGraph workflow.
    Includes conditional edges that short-circuit the pipeline on errors.
    """
    builder = StateGraph(EditorState)
    
    # Register Nodes
    builder.add_node("node_01_download", node_01_download)
    builder.add_node("node_02_audio", node_02_audio)
    builder.add_node("node_03_transcribe", node_03_transcribe)
    builder.add_node("node_04_segment", node_04_segment)
    builder.add_node("node_05_index", node_05_index)
    builder.add_node("node_06_features", node_06_features)
    builder.add_node("node_07_candidates", node_07_candidates)
    builder.add_node("node_08_editors", node_08_editors)
    builder.add_node("abort", _abort_node)
    
    # Wire Edges with error checking after critical nodes
    builder.add_edge(START, "node_01_download")
    builder.add_edge("node_01_download", "node_02_audio")
    
    # After audio extraction, check for errors before transcription
    builder.add_conditional_edges("node_02_audio", _should_continue, {
        "continue": "node_03_transcribe",
        "abort": "abort"
    })
    
    builder.add_edge("node_03_transcribe", "node_04_segment")
    
    # After segmentation, check — no segments means downstream nodes will fail
    builder.add_conditional_edges("node_04_segment", _should_continue, {
        "continue": "node_05_index",
        "abort": "abort"
    })
    
    builder.add_edge("node_05_index", "node_06_features")
    builder.add_edge("node_06_features", "node_07_candidates")
    
    # After candidate generation, check before expensive editor evaluation
    builder.add_conditional_edges("node_07_candidates", _should_continue, {
        "continue": "node_08_editors",
        "abort": "abort"
    })
    
    builder.add_edge("node_08_editors", END)
    builder.add_edge("abort", END)
    
    return builder.compile()

class VideoEditorPipeline:
    def __init__(self):
        self.graph = create_editor_graph()

    def run(self, source_url_or_path: str) -> EditorState:
        initial_state = EditorState(
            source_url=source_url_or_path if source_url_or_path.startswith("http") else None,
            input_file_path=source_url_or_path if not source_url_or_path.startswith("http") else None
        )
        
        # Invoke LangGraph
        result_dict = self.graph.invoke(initial_state)
        if isinstance(result_dict, dict):
            return EditorState(**result_dict)
        return result_dict
