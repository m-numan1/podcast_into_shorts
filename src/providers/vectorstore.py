import numpy as np
from typing import List, Dict, Any, Tuple
from src.schema.clips import SemanticChunk
from config.settings import settings

class VectorStoreProvider:
    def __init__(self, dimension: int = None):
        self.dimension = dimension or settings.embedding_dim
        self.chunks: List[SemanticChunk] = []
        self.vectors: List[np.ndarray] = []
        self._index = None
        self._init_faiss()

    def _init_faiss(self):
        try:
            import faiss
            self._index = faiss.IndexFlatL2(self.dimension)
        except ImportError:
            self._index = None

    def _mock_embedding(self, text: str) -> np.ndarray:
        """Generates deterministic synthetic embedding vector for text string."""
        np.random.seed(abs(hash(text)) % (2**32))
        vec = np.random.randn(self.dimension).astype('float32')
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    def index_chunks(self, chunks: List[SemanticChunk]) -> bool:
        """Indexes semantic chunks into vector store."""
        self.chunks = chunks
        self.vectors = [self._mock_embedding(c.text) for c in chunks]
        
        if self._index is not None and len(self.vectors) > 0:
            mat = np.vstack(self.vectors)
            self._index.reset()
            self._index.add(mat)
        return True

    def similarity_search(self, query: str, k: int = 3) -> List[Tuple[SemanticChunk, float]]:
        """Performs semantic vector search and returns top-k matching chunks with similarity score."""
        if not self.chunks:
            return []
            
        q_vec = self._mock_embedding(query)
        
        if self._index is not None and self._index.ntotal > 0:
            distances, indices = self._index.search(np.array([q_vec]), min(k, len(self.chunks)))
            results = []
            for dist, idx in zip(distances[0], indices[0]):
                if 0 <= idx < len(self.chunks):
                    # convert distance to similarity score
                    score = float(1.0 / (1.0 + dist))
                    results.append((self.chunks[idx], score))
            return results
        else:
            # Numpy cosine similarity fallback
            scores = []
            for chunk, v in zip(self.chunks, self.vectors):
                sim = float(np.dot(q_vec, v))
                scores.append((chunk, sim))
            scores.sort(key=lambda x: x[1], reverse=True)
            return scores[:k]
