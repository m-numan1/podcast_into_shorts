"""Chunk embedding index, with persistence.

Three defects in the original are addressed:

  * `index_chunks` returned `True` unconditionally, even when FAISS was absent
    and `_index` was None, so the pipeline logged "FAISS indexing completed
    successfully" having indexed nothing. It now returns the real count.
  * The provider was constructed as a local inside node_05 and garbage-collected
    on return, so the index never reached any consumer. It now persists to disk
    and is reloaded by the node that uses it.
  * `similarity_search` had no callers at all. The chief editor now uses
    `find_near_duplicates` to catch the same point made twice in an episode --
    which time-overlap dedup cannot see.

FAISS is optional: with it we use an inner-product index, without it a NumPy
matrix multiply. Both give identical results on normalised vectors, and the
NumPy path is fast enough for the low-thousands of chunks an episode produces.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from config.settings import settings
from src.errors import EmbeddingError
from src.providers.embeddings import build_embedder
from src.schema.clips import SemanticChunk
from src.utils.logging_config import get_logger

log = get_logger(__name__)


class VectorStoreProvider:
    def __init__(self, dimension: int | None = None, embedder=None):
        self.dimension = dimension or settings.embedding_dim
        self._embedder = embedder or build_embedder(dim=self.dimension)
        self.chunk_ids: list[str] = []
        self.chunk_texts: list[str] = []
        self.vectors: np.ndarray = np.zeros((0, self.dimension), dtype="float32")
        self._faiss_index = None

    # ------------------------------------------------------------ indexing

    def index_chunks(self, chunks: list[SemanticChunk]) -> int:
        """Embed and index chunks. Returns the number actually indexed."""
        if not chunks:
            log.warning("index_chunks called with no chunks; nothing indexed.")
            return 0

        texts = [c.text for c in chunks]
        vectors = self._embedder.embed(texts)
        if vectors.shape[0] != len(chunks):
            raise EmbeddingError(
                f"Embedder returned {vectors.shape[0]} vectors for {len(chunks)} chunks"
            )

        self.chunk_ids = [c.id for c in chunks]
        self.chunk_texts = texts
        self.vectors = np.ascontiguousarray(vectors, dtype="float32")
        self._faiss_index = self._try_build_faiss(self.vectors)

        backend = "faiss" if self._faiss_index is not None else "numpy"
        log.info(
            "Indexed %d chunks (%d-dim, %s backend, %s embeddings)",
            len(chunks), self.dimension, backend, self._embedder.name,
        )
        return len(chunks)

    def _try_build_faiss(self, matrix: np.ndarray):
        try:
            import faiss
        except ImportError:
            log.debug("FAISS not installed; using the NumPy search path.")
            return None
        except Exception as exc:  # a broken install should not be fatal
            log.warning("FAISS unavailable (%s: %s); using NumPy.", type(exc).__name__, exc)
            return None
        # Vectors are L2-normalised, so inner product == cosine similarity.
        index = faiss.IndexFlatIP(self.dimension)
        index.add(matrix)
        return index

    # ------------------------------------------------------------- queries

    def similarity_search(self, query: str, k: int = 3) -> list[tuple[str, float]]:
        """Return up to k (chunk_id, cosine_similarity), best first."""
        if not self.chunk_ids:
            return []
        q = self._embedder.embed_one(query).astype("float32")
        return self._search_vector(q, k)

    def _search_vector(
        self, q: np.ndarray, k: int, exclude: int | None = None
    ) -> list[tuple[str, float]]:
        k = min(k, len(self.chunk_ids))
        if k <= 0:
            return []

        if self._faiss_index is not None:
            # Ask for one extra so we can drop the excluded row.
            scores, idxs = self._faiss_index.search(
                np.ascontiguousarray([q]), min(k + 1, len(self.chunk_ids))
            )
            pairs = list(zip(idxs[0].tolist(), scores[0].tolist(), strict=True))
        else:
            sims = self.vectors @ q
            order = np.argsort(-sims)[: k + 1]
            pairs = [(int(i), float(sims[i])) for i in order]

        out: list[tuple[str, float]] = []
        for idx, score in pairs:
            if idx < 0 or idx >= len(self.chunk_ids) or idx == exclude:
                continue
            out.append((self.chunk_ids[idx], float(score)))
            if len(out) >= k:
                break
        return out

    def find_near_duplicates(self, threshold: float = 0.85) -> list[tuple[str, str, float]]:
        """Find chunk pairs whose content is near-identical.

        Catches a point restated later in the episode, which time-based overlap
        dedup cannot detect because the two passages do not overlap in time.
        Returns (earlier_id, later_id, similarity).
        """
        if len(self.chunk_ids) < 2:
            return []
        sims = self.vectors @ self.vectors.T
        pairs: list[tuple[str, str, float]] = []
        for i in range(len(self.chunk_ids)):
            for j in range(i + 1, len(self.chunk_ids)):
                score = float(sims[i, j])
                if score >= threshold:
                    pairs.append((self.chunk_ids[i], self.chunk_ids[j], round(score, 4)))
        pairs.sort(key=lambda p: -p[2])
        if pairs:
            log.info("Found %d near-duplicate chunk pair(s) at threshold %.2f",
                     len(pairs), threshold)
        return pairs

    # --------------------------------------------------------- persistence

    def save(self, path: str | Path | None = None) -> str:
        """Persist vectors and metadata so later nodes can reload the index."""
        target = Path(path) if path else settings.cache_dir / "chunk_index.npz"
        target.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(target, vectors=self.vectors)
        meta = {
            "dimension": self.dimension,
            "embedder": self._embedder.name,
            "chunk_ids": self.chunk_ids,
            "chunk_texts": self.chunk_texts,
        }
        target.with_suffix(".meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        log.debug("Saved chunk index to %s", target)
        return str(target)

    @classmethod
    def load(cls, path: str | Path) -> VectorStoreProvider:
        target = Path(path)
        meta_path = target.with_suffix(".meta.json")
        if not target.exists() or not meta_path.exists():
            raise EmbeddingError(f"No persisted index at {target}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        store = cls(dimension=int(meta["dimension"]))
        store.chunk_ids = list(meta["chunk_ids"])
        store.chunk_texts = list(meta["chunk_texts"])
        with np.load(target) as data:
            store.vectors = np.ascontiguousarray(data["vectors"], dtype="float32")
        store._faiss_index = store._try_build_faiss(store.vectors)
        log.debug("Loaded chunk index with %d vectors", len(store.chunk_ids))
        return store
