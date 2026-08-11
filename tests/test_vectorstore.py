"""Vector store: honest counts (B7), persistence, and a real consumer.

The original returned True unconditionally from `index_chunks` (so the pipeline
logged success with nothing indexed), was constructed as a local and discarded
before any consumer saw it, and `similarity_search` had no callers at all.
"""

from __future__ import annotations

import pytest

from src.errors import EmbeddingError
from src.providers.vectorstore import VectorStoreProvider
from src.schema.clips import SemanticChunk


def chunk(chunk_id: str, text: str, start: float = 0.0) -> SemanticChunk:
    return SemanticChunk(
        id=chunk_id, start=start, end=start + 40.0, text=text,
        topic_summary=text[:40], boundary_reason="test",
    )


PRICING = chunk("chunk_001", "everyone underprices at the start because they fear "
                             "rejection so we doubled our price twice")
HIRING = chunk("chunk_002", "hiring senior engineers too early burned our runway "
                            "so we hired one strong generalist instead", 100.0)
ARCTIC = chunk("chunk_003", "the arctic tern migrates eleven thousand miles "
                            "following ocean currents each year", 200.0)
PRICING_RESTATED = chunk("chunk_050", "everyone underprices at the start because "
                                      "they fear rejection so we doubled our price "
                                      "twice", 900.0)


class TestB7HonestCounts:
    def test_returns_the_number_actually_indexed(self):
        store = VectorStoreProvider()
        assert store.index_chunks([PRICING, HIRING, ARCTIC]) == 3

    def test_empty_input_returns_zero_not_true(self):
        """The original returned True even for an empty list."""
        assert VectorStoreProvider().index_chunks([]) == 0

    def test_count_is_an_int_not_a_bool(self):
        result = VectorStoreProvider().index_chunks([PRICING])
        assert isinstance(result, int)
        assert not isinstance(result, bool)


class TestSimilaritySearch:
    def test_finds_the_matching_chunk(self):
        store = VectorStoreProvider()
        store.index_chunks([PRICING, HIRING, ARCTIC])
        results = store.similarity_search("underprices price rejection doubled", k=1)
        assert results
        assert results[0][0] == "chunk_001"

    def test_returns_at_most_k(self):
        store = VectorStoreProvider()
        store.index_chunks([PRICING, HIRING, ARCTIC])
        assert len(store.similarity_search("pricing", k=2)) <= 2

    def test_empty_index_returns_empty(self):
        assert VectorStoreProvider().similarity_search("anything") == []

    def test_scores_are_ordered_descending(self):
        store = VectorStoreProvider()
        store.index_chunks([PRICING, HIRING, ARCTIC])
        results = store.similarity_search("pricing and price and rejection", k=3)
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)


class TestNearDuplicates:
    def test_detects_a_restated_point(self):
        """Time-overlap dedup cannot see this: the passages are 900s apart."""
        store = VectorStoreProvider()
        store.index_chunks([PRICING, HIRING, ARCTIC, PRICING_RESTATED])
        pairs = store.find_near_duplicates(threshold=0.8)
        found = {(a, b) for a, b, _ in pairs}
        assert ("chunk_001", "chunk_050") in found

    def test_distinct_topics_are_not_flagged(self):
        store = VectorStoreProvider()
        store.index_chunks([PRICING, HIRING, ARCTIC])
        assert store.find_near_duplicates(threshold=0.8) == []

    def test_single_chunk_has_no_pairs(self):
        store = VectorStoreProvider()
        store.index_chunks([PRICING])
        assert store.find_near_duplicates() == []

    def test_results_are_sorted_by_similarity(self):
        store = VectorStoreProvider()
        store.index_chunks([PRICING, PRICING_RESTATED, HIRING, ARCTIC])
        pairs = store.find_near_duplicates(threshold=0.0)
        scores = [s for _, _, s in pairs]
        assert scores == sorted(scores, reverse=True)


class TestPersistence:
    def test_round_trip_preserves_the_index(self, tmp_path):
        store = VectorStoreProvider()
        store.index_chunks([PRICING, HIRING, ARCTIC])
        path = store.save(tmp_path / "idx.npz")

        reloaded = VectorStoreProvider.load(path)
        assert reloaded.chunk_ids == store.chunk_ids
        assert reloaded.vectors.shape == store.vectors.shape

    def test_reloaded_index_still_searches(self, tmp_path):
        store = VectorStoreProvider()
        store.index_chunks([PRICING, HIRING, ARCTIC])
        reloaded = VectorStoreProvider.load(store.save(tmp_path / "idx.npz"))
        results = reloaded.similarity_search("underprices rejection doubled price", k=1)
        assert results[0][0] == "chunk_001"

    def test_reloaded_index_finds_duplicates(self, tmp_path):
        store = VectorStoreProvider()
        store.index_chunks([PRICING, PRICING_RESTATED, ARCTIC])
        reloaded = VectorStoreProvider.load(store.save(tmp_path / "idx.npz"))
        assert reloaded.find_near_duplicates(threshold=0.8)

    def test_loading_a_missing_index_raises(self, tmp_path):
        with pytest.raises(EmbeddingError, match="No persisted index"):
            VectorStoreProvider.load(tmp_path / "absent.npz")

    def test_save_creates_both_files(self, tmp_path):
        store = VectorStoreProvider()
        store.index_chunks([PRICING])
        from pathlib import Path

        path = Path(store.save(tmp_path / "idx.npz"))
        assert path.exists()
        assert path.with_suffix(".meta.json").exists()


class TestDeterminism:
    def test_indexing_the_same_chunks_gives_the_same_vectors(self):
        import numpy as np

        first = VectorStoreProvider()
        first.index_chunks([PRICING, HIRING, ARCTIC])
        second = VectorStoreProvider()
        second.index_chunks([PRICING, HIRING, ARCTIC])
        assert np.array_equal(first.vectors, second.vectors)
