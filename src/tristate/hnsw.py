"""A compact HNSW index (Malkov & Yashunin) over cosine-normalised vectors.

Implemented in pure numpy because no HNSW library is available in this environment.
Used for approximate nearest-neighbour novelty retrieval; exact search is kept as a
fallback and as the reference implementation in tests.

Persistence stores vectors + metadata + parameters; the graph is deterministically
rebuilt on load (seeded level assignment, stable insertion order), which avoids
serialising a pointer graph and keeps snapshots portable.
"""

from __future__ import annotations

import heapq
import json
import math
import random
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np


@dataclass
class SearchHit:
    id: int
    score: float
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "score": round(self.score, 6), "meta": self.meta}


class HnswIndex:
    def __init__(
        self,
        dim: int,
        m: int = 16,
        ef_construction: int = 200,
        ef_search: int = 64,
        seed: int = 42,
    ):
        if m < 4:
            raise ValueError("m must be >= 4")
        self.dim = dim
        self.m = m
        self.ef_construction = max(ef_construction, m)
        self.ef_search = ef_search
        self.seed = seed
        self._rng = random.Random(seed)
        self._vectors: list[np.ndarray] = []
        self._metas: list[dict[str, Any]] = []
        self._links: list[list[list[int]]] = []
        self._entry: int | None = None
        self._max_level = -1
        self._level_mult = 1.0 / math.log(m)
        self._lock = threading.RLock()
        self._matrix: np.ndarray | None = None
        self._matrix_version = -1

    # ------------------------------------------------------------------ #
    @property
    def size(self) -> int:
        return len(self._vectors)

    def _random_level(self) -> int:
        u = max(self._rng.random(), 1e-12)
        return int(-math.log(u) * self._level_mult)

    def _sim(self, a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b))

    # ------------------------------------------------------------------ #
    def add(self, vector: np.ndarray, meta: dict[str, Any]) -> int:
        v = np.asarray(vector, dtype=np.float32).copy()
        if v.shape != (self.dim,):
            raise ValueError(f"vector dim {v.shape} != {self.dim}")
        norm = float(np.linalg.norm(v))
        if norm > 0:
            v /= norm
        with self._lock:
            node = len(self._vectors)
            level = self._random_level()
            self._vectors.append(v)
            self._metas.append(dict(meta))
            self._links.append([[] for _ in range(level + 1)])
            self._matrix_version += 1

            if self._entry is None:
                self._entry = node
                self._max_level = level
                return node

            ep = self._entry
            for lc in range(self._max_level, level, -1):
                ep = self._greedy(v, ep, lc)
            for lc in range(min(level, self._max_level), -1, -1):
                candidates = self._search_layer(v, [ep], self.ef_construction, lc)
                neighbors = self._select(v, candidates, self.m)
                self._links[node][lc] = neighbors
                for nb in neighbors:
                    bucket = self._links[nb][lc]
                    if node not in bucket:
                        bucket.append(node)
                    if len(bucket) > self.m:
                        self._links[nb][lc] = self._select(
                            self._vectors[nb],
                            [(self._sim(self._vectors[nb], self._vectors[x]), x) for x in bucket],
                            self.m,
                        )
                if candidates:
                    ep = candidates[0][1]
            if level > self._max_level:
                self._entry = node
                self._max_level = level
            return node

    def add_many(self, vectors: np.ndarray, metas: list[dict[str, Any]]) -> list[int]:
        return [self.add(vec, meta) for vec, meta in zip(vectors, metas)]

    # ------------------------------------------------------------------ #
    def _greedy(self, query: np.ndarray, entry: int, layer: int) -> int:
        current = entry
        best = self._sim(query, self._vectors[current])
        improved = True
        while improved:
            improved = False
            for nb in self._links[current][layer]:
                s = self._sim(query, self._vectors[nb])
                if s > best:
                    best = s
                    current = nb
                    improved = True
        return current

    def _search_layer(
        self, query: np.ndarray, entries: list[int], ef: int, layer: int
    ) -> list[tuple[float, int]]:
        visited = set(entries)
        candidates: list[tuple[float, int]] = []
        results: list[tuple[float, int]] = []
        for e in entries:
            s = self._sim(query, self._vectors[e])
            heapq.heappush(candidates, (-s, e))
            heapq.heappush(results, (s, e))
        if len(results) > ef:
            heapq.heappop(results)

        while candidates:
            neg_s, c = heapq.heappop(candidates)
            if len(results) >= ef and -neg_s < results[0][0]:
                break
            if layer >= len(self._links[c]):
                continue
            for nb in self._links[c][layer]:
                if nb in visited:
                    continue
                visited.add(nb)
                s = self._sim(query, self._vectors[nb])
                if len(results) < ef or s > results[0][0]:
                    heapq.heappush(candidates, (-s, nb))
                    heapq.heappush(results, (s, nb))
                    if len(results) > ef:
                        heapq.heappop(results)
        return sorted(((s, i) for s, i in results), key=lambda x: -x[0])

    def _select(self, query: np.ndarray, candidates: list[tuple[float, int]], m: int) -> list[int]:
        """Diversified neighbour selection (keeps connectivity and coverage)."""
        if not candidates:
            return []
        ordered = sorted(candidates, key=lambda x: -x[0])
        selected: list[int] = []
        rejected: list[int] = []
        threshold = ordered[0][0]
        for sim, cid in ordered:
            if len(selected) >= m:
                break
            good = True
            for sid in selected:
                if self._sim(self._vectors[cid], self._vectors[sid]) >= sim:
                    good = False
                    break
            if good:
                selected.append(cid)
            else:
                rejected.append(cid)
            threshold = min(threshold, sim)
        # guarantee degree: fill leftover slots with the closest rejected nodes
        for cid in rejected:
            if len(selected) >= m:
                break
            if cid not in selected:
                selected.append(cid)
        return selected

    # ------------------------------------------------------------------ #
    def search(
        self,
        vector: np.ndarray,
        k: int = 10,
        ef: int | None = None,
        filter_fn: Callable[[dict[str, Any]], bool] | None = None,
    ) -> list[SearchHit]:
        with self._lock:
            if self._entry is None:
                return []
            q = np.asarray(vector, dtype=np.float32)
            norm = float(np.linalg.norm(q))
            if norm > 0:
                q = q / norm
            ef = max(ef or self.ef_search, k)
            ep = self._entry
            for lc in range(self._max_level, 0, -1):
                ep = self._greedy(q, ep, lc)
            results = self._search_layer(q, [ep], ef, 0)
            hits = [SearchHit(i, s, self._metas[i]) for s, i in results]
            if filter_fn is None:
                return hits[:k]
            filtered = [h for h in hits if filter_fn(h.meta)]
            if len(filtered) < k and self.size > len(hits):
                return self._search_exact_unlocked(q, k, filter_fn)
            return filtered[:k]

    def search_exact(
        self, vector: np.ndarray, k: int = 10,
        filter_fn: Callable[[dict[str, Any]], bool] | None = None,
    ) -> list[SearchHit]:
        q = np.asarray(vector, dtype=np.float32)
        norm = float(np.linalg.norm(q))
        if norm > 0:
            q = q / norm
        with self._lock:
            return self._search_exact_unlocked(q, k, filter_fn)

    def _search_exact_unlocked(self, q, k, filter_fn) -> list[SearchHit]:
        if not self._vectors:
            return []
        if self._matrix is None or self._matrix_version != self.size:
            self._matrix = np.vstack(self._vectors)
            self._matrix_version = self.size
        sims = self._matrix @ q
        order = np.argsort(-sims)
        out: list[SearchHit] = []
        for idx in order:
            meta = self._metas[int(idx)]
            if filter_fn and not filter_fn(meta):
                continue
            out.append(SearchHit(int(idx), float(sims[idx]), meta))
            if len(out) >= k:
                break
        return out

    # ------------------------------------------------------------------ #
    def save(self, directory: str | Path) -> Path:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if self._vectors:
                np.save(d / "vectors.npy", np.vstack(self._vectors))
            else:
                np.save(d / "vectors.npy", np.zeros((0, self.dim), dtype=np.float32))
            with (d / "meta.jsonl").open("w", encoding="utf-8") as fh:
                for m in self._metas:
                    fh.write(json.dumps(m, ensure_ascii=False) + "\n")
            (d / "config.json").write_text(
                json.dumps(
                    {
                        "dim": self.dim, "m": self.m,
                        "ef_construction": self.ef_construction,
                        "ef_search": self.ef_search, "seed": self.seed,
                        "size": self.size,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return d

    @classmethod
    def load(cls, directory: str | Path) -> "HnswIndex":
        d = Path(directory)
        cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
        index = cls(
            dim=cfg["dim"], m=cfg["m"],
            ef_construction=cfg["ef_construction"],
            ef_search=cfg["ef_search"], seed=cfg["seed"],
        )
        vecs = np.load(d / "vectors.npy")
        metas = [json.loads(line) for line in (d / "meta.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        for i, meta in enumerate(metas):
            index.add(vecs[i], meta)
        return index

    def metas(self) -> list[dict[str, Any]]:
        return list(self._metas)
