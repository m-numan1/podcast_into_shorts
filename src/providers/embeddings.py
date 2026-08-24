"""Text embeddings, with a deterministic offline backend.

The original `_mock_embedding` seeded numpy from Python's `hash()` and returned
`randn()`. That had two fatal properties:

  1. `hash()` on str is salted per process (PYTHONHASHSEED), so the vectors --
     documented as "deterministic" -- changed on every run.
  2. Random vectors carry no signal, so any similarity computed from them is
     noise. Nothing could be learned from comparing them.

The `lexical` backend here is a hashing vectoriser (the "hashing trick"): it is
stable across processes because it uses BLAKE2, and cosine similarity between
two of its vectors reflects genuine lexical overlap. It is not semantic -- it
cannot see that "car" and "automobile" are related -- and it says so. That is
enough for adjacent-window topic-shift detection, and it degrades honestly.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections.abc import Sequence

import numpy as np

from config.settings import settings
from src.errors import EmbeddingError, MissingDependencyError
from src.utils.logging_config import get_logger

log = get_logger(__name__)

TOKEN_RE = re.compile(r"[a-z0-9']+")

# Extremely common words carry no topic signal; dropping them sharpens the
# similarity dip at real topic boundaries.
STOPWORDS = frozenset(["a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for", "from", "had", "has", "have", "he", "her", "his", "i", "if", "in", "is", "it", "its", "me", "my", "not", "of", "on", "or", "our", "she", "so", "than", "that", "the", "their", "them", "then", "there", "these", "they", "this", "to", "too", "was", "we", "were", "what", "when", "which", "who", "will", "with", "would", "you", "your"])


def _tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


# Relative weights per feature family. Character n-grams are noisier than whole
# words, so they contribute less, but they are what lets "price", "pricing" and
# "underprices" match at all -- without them the backend only sees exact
# repeats and same-topic passages score ~0.
WEIGHT_WORD = 1.0
WEIGHT_BIGRAM = 0.8
WEIGHT_CHARGRAM = 0.45
CHARGRAM_N = 4


FAMILY_WEIGHTS = {"w": WEIGHT_WORD, "b": WEIGHT_BIGRAM, "c": WEIGHT_CHARGRAM}


def _feature_counts(text: str) -> dict[str, int]:
    """Raw occurrence counts, keyed `<family>:<token>`.

    Families: `w` word unigram, `b` word bigram, `c` character n-gram.
    """
    tokens = _tokenize(text)
    if not tokens:
        return {}

    counts: dict[str, int] = {}

    def bump(key: str) -> None:
        counts[key] = counts.get(key, 0) + 1

    for tok in tokens:
        bump(f"w:{tok}")
    for a, b in zip(tokens, tokens[1:], strict=False):
        bump(f"b:{a}_{b}")
    for tok in tokens:
        if len(tok) >= CHARGRAM_N:
            padded = f"^{tok}$"
            for i in range(len(padded) - CHARGRAM_N + 1):
                bump(f"c:{padded[i : i + CHARGRAM_N]}")
    return counts


class LexicalHashingEmbedder:
    """Deterministic, offline, dependency-free bag-of-ngrams embedder."""

    name = "lexical"

    def __init__(self, dim: int):
        if dim <= 0:
            raise EmbeddingError(f"Embedding dimension must be positive, got {dim}")
        self.dim = dim

    @staticmethod
    def _bucket(token: str, dim: int) -> tuple[int, float]:
        """Map a token to (index, sign) using a stable hash.

        BLAKE2b is process-stable, unlike the builtin `hash()`.
        """
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        index = value % dim
        sign = 1.0 if (value >> 63) & 1 else -1.0
        return index, sign

    def embed_one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype="float32")
        feats = _feature_counts(text)
        if not feats:
            return vec

        for key, count in feats.items():
            idx, sign = self._bucket(key, self.dim)
            family_weight = FAMILY_WEIGHTS[key[0]]
            # Sublinear TF: a feature seen 10x is not 10x as informative.
            vec[idx] += sign * family_weight * (1.0 + math.log(count))

        norm = float(np.linalg.norm(vec))
        return vec / norm if norm > 0 else vec

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype="float32")
        return np.vstack([self.embed_one(t) for t in texts])


class _RemoteEmbedder:
    """Shared retry/batching logic for API-backed embedders."""

    name = "remote"

    def __init__(self, dim: int):
        self.dim = dim

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype="float32")

        out: list[list[float]] = []
        batch_size = 64
        for start in range(0, len(texts), batch_size):
            batch = list(texts[start : start + batch_size])
            out.extend(self._with_retries(batch))

        arr = np.asarray(out, dtype="float32")
        if arr.shape[1] != self.dim:
            raise EmbeddingError(
                f"{self.name} returned {arr.shape[1]}-dim vectors but settings "
                f"expect {self.dim}. Update EMBEDDING_DIMS in config/settings.py."
            )
        # Normalise so dot product is cosine similarity.
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms

    def _with_retries(self, batch: list[str]) -> list[list[float]]:
        last: Exception | None = None
        for attempt in range(settings.llm_max_retries + 1):
            try:
                return self._embed_batch(batch)
            except Exception as exc:
                last = exc
                if attempt < settings.llm_max_retries:
                    delay = 2.0**attempt
                    log.warning(
                        "%s embedding attempt %d/%d failed (%s); retrying in %.0fs",
                        self.name, attempt + 1, settings.llm_max_retries + 1,
                        type(exc).__name__, delay,
                    )
                    time.sleep(delay)
        raise EmbeddingError(
            f"{self.name} embedding failed after {settings.llm_max_retries + 1} attempts: {last}",
            "Check the API key and network, or set EMBEDDING_BACKEND=lexical.",
        ) from last

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


class OpenAIEmbedder(_RemoteEmbedder):
    name = "openai"

    def __init__(self, dim: int):
        super().__init__(dim)
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError as exc:
            raise MissingDependencyError(
                "langchain-openai", "pip install langchain-openai"
            ) from exc
        if not settings.openai_api_key:
            raise EmbeddingError(
                "EMBEDDING_BACKEND=openai requires OPENAI_API_KEY.",
                "Set the key or use EMBEDDING_BACKEND=lexical.",
            )
        self._client = OpenAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.openai_api_key,
        )

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed_documents(texts)


class GeminiEmbedder(_RemoteEmbedder):
    name = "gemini"

    def __init__(self, dim: int):
        super().__init__(dim)
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
        except ImportError as exc:
            raise MissingDependencyError(
                "langchain-google-genai", "pip install langchain-google-genai"
            ) from exc
        if not settings.gemini_api_key:
            raise EmbeddingError(
                "EMBEDDING_BACKEND=gemini requires GEMINI_API_KEY.",
                "Set the key or use EMBEDDING_BACKEND=lexical.",
            )
        self._client = GoogleGenerativeAIEmbeddings(
            model=settings.embedding_model,
            google_api_key=settings.gemini_api_key,
        )

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed_documents(texts)


def build_embedder(backend: str | None = None, dim: int | None = None):
    """Construct the configured embedder."""
    backend = backend or settings.embedding_backend
    dim = dim if dim is not None else settings.embedding_dim
    if backend == "openai":
        return OpenAIEmbedder(dim)
    if backend == "gemini":
        return GeminiEmbedder(dim)
    if backend == "lexical":
        log.info(
            "Using the lexical hashing embedder (offline, deterministic, "
            "lexical-overlap only -- not semantic)."
        )
        return LexicalHashingEmbedder(dim)
    raise EmbeddingError(f"Unknown embedding backend {backend!r}")


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity for possibly-unnormalised vectors."""
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))
