"""Deterministic embeddings.

The configured provider exposes no embeddings endpoint, so the default embedder is a
signed-hashing TF vectoriser over word unigrams/bigrams and character 4-grams. It is
fully deterministic across processes and platforms (blake2b, not Python's hash), needs
no model download, and is good enough for near-duplicate retrieval. An OpenAI-compatible
API embedder can be enabled in config when one becomes available.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from .config import Config

_TOKEN = re.compile(r"[a-z0-9']+")


def _bucket(token: str, dim: int) -> tuple[int, float]:
    h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(h, "little")
    sign = 1.0 if (value >> 63) & 1 else -1.0
    return value % dim, sign


class HashingEmbedder:
    name = "hashing-tf-v1"

    def __init__(self, dim: int = 384):
        if dim < 32:
            raise ValueError("embedding dim too small")
        self.dim = dim

    def encode(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        low = (text or "").lower()
        words = _TOKEN.findall(low)

        counts: dict[str, float] = {}
        for w in words:
            counts[f"w:{w}"] = counts.get(f"w:{w}", 0.0) + 1.0
        for a, b in zip(words, words[1:]):
            counts[f"b:{a} {b}"] = counts.get(f"b:{a} {b}", 0.0) + 1.0
        compact = re.sub(r"\s+", " ", low)
        for i in range(max(0, len(compact) - 3)):
            g = compact[i:i + 4]
            counts[f"c:{g}"] = counts.get(f"c:{g}", 0.0) + 1.0

        for token, count in counts.items():
            weight = 1.0 + math.log(count)
            if token.startswith("b:"):
                weight *= 0.7
            elif token.startswith("c:"):
                weight *= 0.35
            idx, sign = _bucket(token, self.dim)
            vec[idx] += sign * weight

        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec

    def encode_many(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self.encode(t) for t in texts])


class ApiEmbedder:
    """OpenAI-compatible embeddings with a deterministic local fallback."""

    name = "api-embedding"

    def __init__(self, base_url: str, api_key: str | None, model: str, dim: int,
                 user_agent: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim
        self.user_agent = user_agent
        self.timeout = timeout
        self.fallback = HashingEmbedder(dim)

    def encode(self, text: str) -> np.ndarray:
        import httpx

        if not self.api_key or not self.model:
            return self.fallback.encode(text)
        try:
            r = httpx.post(
                self.base_url + "/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": self.user_agent,
                },
                json={"model": self.model, "input": text},
                timeout=self.timeout,
            )
            if r.status_code >= 400:
                return self.fallback.encode(text)
            data = r.json()["data"][0]["embedding"]
            vec = np.asarray(data, dtype=np.float32)
            n = float(np.linalg.norm(vec))
            return vec / n if n > 0 else vec
        except Exception:
            return self.fallback.encode(text)

    def encode_many(self, texts: Sequence[str]) -> np.ndarray:
        return np.vstack([self.encode(t) for t in texts]) if texts else np.zeros((0, self.dim), np.float32)


class OllamaEmbedder:
    """Local embedding model served by Ollama (default: embeddinggemma, 768-d).

    Vectors are cached on disk by (model, text) hash so re-runs and resumable jobs do
    not pay for the same embedding twice. If the service is unreachable the embedder
    degrades to the deterministic hashing embedder at the same dimensionality.
    """

    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        dim: int = 768,
        cache_dir: str | Path | None = None,
        batch_size: int = 16,
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim
        self.batch_size = max(1, batch_size)
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.fallback = HashingEmbedder(dim)
        self.available = self._probe()

    def _probe(self) -> bool:
        try:
            import httpx

            r = httpx.get(self.base_url + "/api/tags", timeout=3.0)
            if r.status_code >= 400:
                return False
            names = [m.get("name", "") for m in r.json().get("models", [])]
            base = self.model.split(":")[0]
            return any(n == self.model or n.split(":")[0] == base for n in names)
        except Exception:
            return False

    def _cache_path(self, text: str):
        if not self.cache_dir:
            return None
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "_", self.model)
        return self.cache_dir / safe_model / f"{h}.npy"

    def _from_cache(self, text: str):
        p = self._cache_path(text)
        if p and p.exists():
            try:
                v = np.load(p)
                if v.shape == (self.dim,):
                    return v.astype(np.float32)
            except Exception:
                return None
        return None

    def _write_cache(self, text: str, vec: np.ndarray) -> None:
        p = self._cache_path(text)
        if not p:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp.npy")
        np.save(tmp, vec)
        tmp.replace(p)

    def _normalise(self, vec: np.ndarray) -> np.ndarray:
        n = float(np.linalg.norm(vec))
        return (vec / n).astype(np.float32) if n > 0 else vec.astype(np.float32)

    def encode_many(self, texts: Sequence[str]) -> np.ndarray:
        texts = list(texts)
        out = [self._from_cache(t) for t in texts]
        missing = [i for i, v in enumerate(out) if v is None]
        if missing and self.available:
            import httpx

            for start in range(0, len(missing), self.batch_size):
                chunk = missing[start:start + self.batch_size]
                try:
                    r = httpx.post(
                        self.base_url + "/api/embed",
                        json={"model": self.model, "input": [texts[i] for i in chunk]},
                        timeout=self.timeout,
                    )
                    r.raise_for_status()
                    embs = r.json()["embeddings"]
                    for i, emb in zip(chunk, embs):
                        vec = self._normalise(np.asarray(emb, dtype=np.float32))
                        if vec.shape != (self.dim,):
                            raise ValueError(f"unexpected embedding dim {vec.shape}")
                        out[i] = vec
                        self._write_cache(texts[i], vec)
                except Exception:
                    self.available = False
                    break
        return np.vstack(
            [v if v is not None else self.fallback.encode(t) for v, t in zip(out, texts)]
        ) if texts else np.zeros((0, self.dim), dtype=np.float32)

    def encode(self, text: str) -> np.ndarray:
        return self.encode_many([text])[0]


def get_embedder(cfg: Config):
    if cfg.hnsw.embedder == "ollama":
        e = OllamaEmbedder(
            base_url=cfg.hnsw.ollama_base_url,
            model=cfg.hnsw.ollama_model,
            dim=cfg.hnsw.dim,
            cache_dir=cfg.data_dir / "embeddings",
            batch_size=cfg.hnsw.embed_batch,
            timeout=cfg.hnsw.embed_timeout_s,
        )
        e.name = f"ollama:{e.model}" if e.available else "ollama-unavailable:hashing"
        return e
    if cfg.hnsw.embedder == "api":
        return ApiEmbedder(
            base_url=cfg.llm.base_url,
            api_key=cfg.api_key(),
            model=cfg.hnsw.api_model,
            dim=cfg.hnsw.dim,
            user_agent=cfg.llm.user_agent,
        )
    return HashingEmbedder(cfg.hnsw.dim)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def mean_vector(vectors: Iterable[np.ndarray]) -> np.ndarray:
    vs = list(vectors)
    if not vs:
        raise ValueError("no vectors")
    m = np.mean(np.vstack(vs), axis=0)
    n = float(np.linalg.norm(m))
    return (m / n).astype(np.float32) if n > 0 else m.astype(np.float32)
