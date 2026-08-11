from src.schema.state import EditorState
from src.providers.vectorstore import VectorStoreProvider

def node_05_index(state: EditorState) -> dict:
    """
    Node 5: Generate embeddings for every semantic chunk and store them in FAISS.
    """
    logs = list(state.logs)
    logs.append("[Node 5] Indexing semantic chunks in FAISS Vector Store...")
    
    if not state.semantic_chunks:
        return {
            "error": "No semantic chunks available to index in FAISS for Node 5.",
            "logs": logs + ["[Node 5] ERROR: No semantic chunks to index."]
        }
        
    vectorstore = VectorStoreProvider()
    success = vectorstore.index_chunks(state.semantic_chunks)
    
    logs.append(f"[Node 5] FAISS vector store indexing completed successfully for {len(state.semantic_chunks)} chunks.")
    
    return {
        "faiss_indexed": success,
        "current_node": "NODE_05_INDEX_COMPLETE",
        "logs": logs
    }
