from __future__ import annotations

import numpy as np
import pytest

from tristate.embeddings import HashingEmbedder
from tristate.hnsw import HnswIndex


def _vectors(n=300, dim=64, seed=3):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n, dim)).astype(np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return v


def test_hnsw_recall_against_exact():
    vecs = _vectors()
    idx = HnswIndex(64, m=12, ef_construction=120, ef_search=64, seed=5)
    for i, v in enumerate(vecs):
        idx.add(v, {"i": i})
    hits = 0
    total = 0
    for q in vecs[:40]:
        approx = {h.id for h in idx.search(q, k=10)}
        exact = {h.id for h in idx.search_exact(q, k=10)}
        hits += len(approx & exact)
        total += 10
    assert hits / total >= 0.9


def test_hnsw_metadata_roundtrip(tmp_path):
    vecs = _vectors(50)
    idx = HnswIndex(64, seed=9)
    for i, v in enumerate(vecs):
        idx.add(v, {"i": i, "tag": f"t{i}"})
    idx.save(tmp_path)
    loaded = HnswIndex.load(tmp_path)
    assert loaded.size == idx.size
    res = loaded.search(vecs[7], k=3)
    assert res[0].meta["i"] == 7
    assert {h.meta["tag"] for h in res} <= {f"t{i}" for i in range(50)}


def test_hnsw_filter_falls_back_to_exact():
    vecs = _vectors(40)
    idx = HnswIndex(64, seed=1, ef_search=8)
    for i, v in enumerate(vecs):
        idx.add(v, {"i": i, "split": "train" if i % 2 else "test"})
    hits = idx.search(vecs[0], k=5, filter_fn=lambda m: m["split"] == "test")
    assert len(hits) == 5
    assert all(h.meta["split"] == "test" for h in hits)


def test_empty_index_returns_nothing():
    idx = HnswIndex(8)
    assert idx.search(np.ones(8, dtype=np.float32), k=3) == []
    assert idx.search_exact(np.ones(8, dtype=np.float32), k=3) == []


def test_vectors_normalised_on_add():
    idx = HnswIndex(4)
    idx.add(np.array([3.0, 4.0, 0.0, 0.0], dtype=np.float32), {})
    hit = idx.search(np.array([3.0, 4.0, 0.0, 0.0], dtype=np.float32), k=1)[0]
    assert hit.score == pytest.approx(1.0, abs=1e-6)


def test_hashing_embedder_deterministic_and_normalised():
    a = HashingEmbedder(128)
    b = HashingEmbedder(128)
    v1 = a.encode("The Orion language was developed by Alice Brown.")
    v2 = b.encode("The Orion language was developed by Alice Brown.")
    assert np.allclose(v1, v2)
    assert np.linalg.norm(v1) == pytest.approx(1.0, abs=1e-5)
    sim = float(v1 @ a.encode("Alice Brown developed Orion."))
    assert sim > float(v1 @ a.encode("Bananas are a yellow fruit."))
