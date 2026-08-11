"""B3: embeddings must be deterministic across processes.

The original seeded numpy from Python's builtin `hash()`, which is salted per
process via PYTHONHASHSEED, so vectors documented as "deterministic" changed
every run -- and they were `randn()` noise carrying no signal at all.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import numpy as np
import pytest

from src.errors import EmbeddingError
from src.providers.embeddings import (
    LexicalHashingEmbedder,
    build_embedder,
    cosine_similarity,
)

CHILD = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, sys.argv[1])
    from src.providers.embeddings import LexicalHashingEmbedder
    v = LexicalHashingEmbedder(256).embed_one("proprietary data flywheels")
    print(",".join(f"{x:.8f}" for x in v[:12]))
    """
)


class TestDeterminism:
    def test_same_text_gives_the_same_vector_in_process(self):
        embedder = LexicalHashingEmbedder(256)
        a = embedder.embed_one("pricing strategy for founders")
        b = embedder.embed_one("pricing strategy for founders")
        assert np.array_equal(a, b)

    def test_stable_across_separate_processes(self, tmp_path):
        """The actual B3 regression: run in fresh interpreters and compare."""
        script = tmp_path / "child.py"
        script.write_text(CHILD, encoding="utf-8")
        root = str(__import__("pathlib").Path(__file__).resolve().parent.parent)
        outputs = set()
        for _ in range(3):
            proc = subprocess.run(
                [sys.executable, str(script), root],
                capture_output=True, text=True, check=True,
            )
            outputs.add(proc.stdout.strip())
        assert len(outputs) == 1, f"vectors differ between processes: {outputs}"

    def test_hash_builtin_is_not_used_for_bucketing(self):
        """Identifier-level check: neither `hash` nor `seed` may be referenced."""
        from tests.conftest import code_identifiers

        identifiers = code_identifiers("src/providers/embeddings.py")
        assert "hash" not in identifiers, "builtin hash() is salted per process"
        assert "seed" not in identifiers, "no seeded RNG in an embedder"
        assert "randn" not in identifiers, "random vectors carry no signal"


class TestSignal:
    """Random vectors carry no information; these must."""

    def test_identical_text_is_maximally_similar(self):
        e = LexicalHashingEmbedder(512)
        text = "we doubled our price twice and churn went down"
        assert cosine_similarity(e.embed_one(text), e.embed_one(text)) == pytest.approx(1.0)

    def test_paraphrase_scores_far_above_unrelated(self):
        e = LexicalHashingEmbedder(512)
        base = "they built proprietary data flywheels from user interaction"
        para = "proprietary data flywheels built from every user interaction"
        other = "the arctic tern migrates eleven thousand miles each year"
        assert cosine_similarity(e.embed_one(base), e.embed_one(para)) > \
               cosine_similarity(e.embed_one(base), e.embed_one(other)) + 0.3

    def test_morphological_variants_partially_match(self):
        """Character n-grams are what let price/pricing/underprices relate."""
        e = LexicalHashingEmbedder(512)
        assert cosine_similarity(
            e.embed_one("pricing"), e.embed_one("underprices")
        ) > 0.05

    def test_topic_blocks_separate_at_block_scale(self):
        e = LexicalHashingEmbedder(512)
        pricing = ("everyone underprices at the start because they fear rejection "
                   "we doubled our price twice and churn went down")
        pricing2 = ("a low price signals low value so charge more than feels "
                    "comfortable and put pricing on the website")
        arctic = ("the arctic tern migrates eleven thousand miles following ocean "
                  "currents and feeding on small fish near the surface")
        within = cosine_similarity(e.embed_one(pricing), e.embed_one(pricing2))
        across = cosine_similarity(e.embed_one(pricing), e.embed_one(arctic))
        assert within > across

    def test_vectors_are_unit_normalised(self):
        e = LexicalHashingEmbedder(256)
        v = e.embed_one("some reasonable amount of text about pricing")
        assert float(np.linalg.norm(v)) == pytest.approx(1.0, abs=1e-5)

    def test_empty_text_returns_a_zero_vector(self):
        e = LexicalHashingEmbedder(128)
        assert float(np.linalg.norm(e.embed_one(""))) == 0.0

    def test_stopword_only_text_returns_zero(self):
        e = LexicalHashingEmbedder(128)
        assert float(np.linalg.norm(e.embed_one("the and but of to"))) == 0.0


class TestBatching:
    def test_embed_returns_one_row_per_text(self):
        e = LexicalHashingEmbedder(128)
        out = e.embed(["first text here", "second text here", "third one"])
        assert out.shape == (3, 128)

    def test_empty_batch(self):
        e = LexicalHashingEmbedder(128)
        assert e.embed([]).shape == (0, 128)

    def test_batch_matches_single(self):
        e = LexicalHashingEmbedder(128)
        texts = ["alpha beta gamma", "delta epsilon zeta"]
        batch = e.embed(texts)
        for i, text in enumerate(texts):
            assert np.allclose(batch[i], e.embed_one(text))


class TestBuildEmbedder:
    def test_lexical_backend(self):
        assert build_embedder("lexical", 256).name == "lexical"

    def test_unknown_backend_raises(self):
        with pytest.raises(EmbeddingError, match="Unknown embedding backend"):
            build_embedder("telepathy", 256)

    def test_zero_dimension_rejected(self):
        with pytest.raises(EmbeddingError, match="must be positive"):
            LexicalHashingEmbedder(0)


class TestCosineSimilarity:
    def test_zero_vectors_do_not_divide_by_zero(self):
        assert cosine_similarity(np.zeros(4), np.ones(4)) == 0.0

    def test_orthogonal(self):
        assert cosine_similarity(
            np.array([1.0, 0.0]), np.array([0.0, 1.0])
        ) == pytest.approx(0.0)

    def test_opposite(self):
        assert cosine_similarity(
            np.array([1.0, 0.0]), np.array([-1.0, 0.0])
        ) == pytest.approx(-1.0)
