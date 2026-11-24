"""Corpus acquisition: local seed documents, sentence-aware segmentation, dedupe.

Track A (topic-driven synthetic passages) needs no corpus. Track B (external content)
is optional and starts with local files; a network connector is deliberately not a hard
dependency. When a document is ingested its provenance and offsets are preserved and
the full document is retained (config: corpus.retain_source_documents).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import Config
from .spans import sentence_index
from .store import Store
from .util import (
    append_jsonl,
    approx_tokens,
    atomic_write_json,
    english_score,
    normalize_ws,
    read_jsonl,
    sha256_text,
    truncate,
    utcnow,
)
from .ids import document_id as make_document_id


@dataclass
class Chunk:
    text: str
    start_char: int
    end_char: int
    token_count: int
    sentence_ids: list[str]


def segment_text(text: str, min_tokens: int, max_tokens: int) -> list[Chunk]:
    """Sentence-aware chunking into configurable token bands."""
    refs = sentence_index(text)
    chunks: list[Chunk] = []
    buf: list = []
    buf_tokens = 0
    for ref in refs:
        toks = approx_tokens(ref.text)
        if buf and buf_tokens + toks > max_tokens:
            chunks.append(_make_chunk(buf))
            buf, buf_tokens = [], 0
        buf.append(ref)
        buf_tokens += toks
    if buf:
        if chunks and buf_tokens < min_tokens:
            # merge a short tail into the previous chunk rather than emit a stub
            prev = chunks.pop()
            merged = prev.text + " " + " ".join(r.text for r in buf)
            merged_refs = sentence_index(merged)
            chunks.append(
                Chunk(
                    text=normalize_ws(merged),
                    start_char=prev.start_char,
                    end_char=buf[-1].end_char,
                    token_count=approx_tokens(merged),
                    sentence_ids=[r.sentence_id for r in merged_refs],
                )
            )
        else:
            chunks.append(_make_chunk(buf))
    return [c for c in chunks if c.token_count >= max(20, min_tokens // 3)]


def _make_chunk(refs: list) -> Chunk:
    text = " ".join(r.text for r in refs)
    return Chunk(
        text=normalize_ws(text),
        start_char=refs[0].start_char,
        end_char=refs[-1].end_char,
        token_count=approx_tokens(text),
        sentence_ids=[r.sentence_id for r in refs],
    )


def ingest_local_paths(
    store: Store,
    cfg: Config,
    paths: Iterable[str | Path],
    license_note: str = "local seed document supplied by project owner",
) -> list[dict[str, Any]]:
    """Ingest .txt/.md files into documents + passage candidates with provenance."""
    created: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    existing = load_candidates(store)
    for d in existing:
        seen_hashes.add(d.get("text_hash", ""))

    for raw_path in paths:
        p = Path(raw_path)
        if not p.exists():
            continue
        files = [p] if p.is_file() else sorted(
            f for f in p.rglob("*") if f.suffix.lower() in (".txt", ".md")
        )
        for f in files:
            text = f.read_text(encoding="utf-8", errors="replace")
            if english_score(text) < cfg.quality.min_english_score:
                continue
            content_hash = sha256_text(normalize_ws(text))
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)
            doc_id = make_document_id(content_hash)
            doc = {
                "document_id": doc_id,
                "path": str(f),
                "title": f.stem,
                "publisher": "local",
                "source_type": "local_document",
                "retrieved_at": utcnow(),
                "license_or_usage_notes": license_note,
                "content_hash": content_hash,
                "token_count": approx_tokens(text),
                "char_count": len(text),
            }
            doc["text"] = text if cfg.corpus.retain_source_documents else truncate(text, 400)
            atomic_write_json(store.data_dir / "corpus" / "documents" / f"{doc_id}.json", doc)

            for i, chunk in enumerate(
                segment_text(text, cfg.corpus.passage_token_min, cfg.corpus.passage_token_max)
            ):
                cand = {
                    "candidate_text_id": f"{doc_id}_P{i:03d}",
                    "document_id": doc_id,
                    "source_type": "local_document",
                    "title": doc["title"],
                    "publisher": "local",
                    "source_url": None,
                    "license_or_usage_notes": license_note,
                    "text": chunk.text,
                    "text_hash": sha256_text(chunk.text),
                    "start_char": chunk.start_char,
                    "end_char": chunk.end_char,
                    "sentence_ids": chunk.sentence_ids,
                    "token_count": chunk.token_count,
                    "chunking": {
                        "strategy": "sentence_window",
                        "min_tokens": cfg.corpus.passage_token_min,
                        "max_tokens": cfg.corpus.passage_token_max,
                    },
                    "created_at": utcnow(),
                    "used": False,
                }
                append_jsonl(store.data_dir / "corpus" / "candidates.jsonl", cand)
                created.append(cand)
    return created


def load_candidates(store: Store, limit: int | None = None) -> list[dict[str, Any]]:
    rows = read_jsonl(store.data_dir / "corpus" / "candidates.jsonl")
    if limit:
        return rows[:limit]
    return rows


def unused_candidates(store: Store) -> list[dict[str, Any]]:
    return [r for r in load_candidates(store) if not r.get("used")]


def mark_used(store: Store, candidate_text_id: str) -> None:
    rows = load_candidates(store)
    for r in rows:
        if r["candidate_text_id"] == candidate_text_id:
            r["used"] = True
            r["used_at"] = utcnow()
    path = store.data_dir / "corpus" / "candidates.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )


def near_duplicate(text: str, others: Iterable[str], threshold: float = 0.9) -> str | None:
    from .util import jaccard, word_ngrams

    grams = word_ngrams(text, 2)
    for other in others:
        if jaccard(grams, word_ngrams(other, 2)) >= threshold:
            return other
    return None


def corpus_summary(store: Store) -> dict[str, Any]:
    docs = list((store.data_dir / "corpus" / "documents").glob("*.json"))
    cands = load_candidates(store)
    return {
        "documents": len(docs),
        "passage_candidates": len(cands),
        "used": sum(1 for c in cands if c.get("used")),
        "total_tokens": sum(int(c.get("token_count", 0)) for c in cands),
    }
