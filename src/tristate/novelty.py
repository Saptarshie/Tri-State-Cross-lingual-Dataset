"""HNSW-backed novelty memory and feedback.

Four independent namespaces (blueprint, passage, fact_claim, edit_signature) each hold
vectors plus metadata that points back to a durable family record. Only accepted
material is indexed, so the novelty signal cannot be poisoned by rejected candidates,
and test-split families are excluded from the retrieval pool used to steer generation.
"""

from __future__ import annotations

import random
from typing import Any, Iterable

from .config import Config
from .embeddings import get_embedder
from .hnsw import HnswIndex
from .schema import Family
from .spans import sentence_index
from .store import Store
from .util import (
    approx_tokens,
    atomic_write_json,
    jaccard,
    read_json,
    sha256_text,
    truncate,
    utcnow,
    word_ngrams,
)

NAMESPACES = ("blueprint", "passage", "fact_claim", "edit_signature")

RELATION_POOL = [
    "developed_by", "located_in", "founded_in", "increased_by", "part_of",
    "designed_for", "replaced_by", "operated_by", "measured_at", "requires",
    "produces", "compared_with", "scheduled_for", "owned_by", "derived_from",
]


class NoveltyService:
    def __init__(self, store: Store, cfg: Config, embedder=None):
        self.store = store
        self.cfg = cfg
        self.embedder = embedder or get_embedder(cfg)
        self.root = store.data_dir / "index"
        self.root.mkdir(parents=True, exist_ok=True)
        self.dim = int(getattr(self.embedder, "dim", cfg.hnsw.dim))
        embedder_file = self.root / "embedder.json"
        current = read_json(embedder_file, default=None)
        fingerprint = {"name": getattr(self.embedder, "name", "unknown"), "model": getattr(self.embedder, "model", ""), "dim": self.dim}
        if current and (current.get("dim") != self.dim or current.get("name") != fingerprint["name"]):
            raise RuntimeError(
                "index/embedder mismatch: index was built with "
                f"{current} but current embedder is {fingerprint}. Run `python -m tristate index build`."
            )
        if not current:
            atomic_write_json(embedder_file, fingerprint)
        self.indexes: dict[str, HnswIndex] = {}
        for ns in NAMESPACES:
            d = self.root / ns
            if (d / "config.json").exists():
                self.indexes[ns] = HnswIndex.load(d)
            else:
                self.indexes[ns] = HnswIndex(
                    dim=self.dim,
                    m=self.cfg.hnsw.m,
                    ef_construction=self.cfg.hnsw.ef_construction,
                    ef_search=self.cfg.hnsw.ef_search,
                    seed=self.cfg.project.seed,
                )
        self.stats = read_json(self.root / "stats.json", default=None) or {
            "relation_types": {}, "entity_types": {}, "entities": {}, "genres": {},
            "tones": {}, "narratives": {}, "structures": {}, "topic_paths": {}, "edit_ops": {}, "labels": {},
            "families": 0,
        }

    # ------------------------------------------------------------------ #
    def _not_test(self, meta: dict[str, Any]) -> bool:
        if not self.cfg.hnsw.split_aware:
            return True
        return meta.get("split") != "test"

    def _embed(self, text: str):
        return self.embedder.encode(text)

    def _chunks(self, text: str) -> list[tuple[int, int, str]]:
        """Sentence-aligned chunks sized for the embedding model's context."""
        target = max(200, int(self.cfg.hnsw.passage_chunk_tokens))
        refs = sentence_index(text)
        if not refs:
            return [(0, len(text), text)]
        out: list[tuple[int, int, str]] = []
        start = refs[0].start_char
        tokens = 0
        for ref in refs:
            if tokens >= target:
                out.append((start, ref.start_char, text[start:ref.start_char]))
                start = ref.start_char
                tokens = 0
            tokens += approx_tokens(ref.text)
        out.append((start, len(text), text[start:]))
        return [(s, e, c) for s, e, c in out if c.strip()]

    # ------------------------------------------------------------------ #
    # Pre-generation feedback
    # ------------------------------------------------------------------ #
    def pre_generation_report(
        self,
        semantic_text: str,
        topic_path: list[str],
        split_hint: str | None = None,
    ) -> dict[str, Any]:
        vec = self._embed(semantic_text)
        k = self.cfg.blueprint.novelty_top_k
        blueprints = self.indexes["blueprint"].search(vec, k=k, filter_fn=self._not_test)
        passages = self.indexes["passage"].search(vec, k=k, filter_fn=self._not_test)
        facts = self.indexes["fact_claim"].search(vec, k=max(3, k // 2), filter_fn=self._not_test)

        over = {
            "relations": self._top(self.stats.get("relation_types", {}), 6),
            "entities": self._top(self.stats.get("entities", {}), 8),
            "genres": self._top(self.stats.get("genres", {}), 4),
            "topic_paths": self._top(self.stats.get("topic_paths", {}), 4),
        }
        suggested = {
            "genre": self._least_used(self.cfg.blueprint.genres, self.stats.get("genres", {})),
            "tone": self._least_used(self.cfg.blueprint.tones, self.stats.get("tones", {})),
            "narrative": self._least_used(self.cfg.blueprint.narratives, self.stats.get("narratives", {})),
            "structure": self._least_used(self.cfg.blueprint.structures, self.stats.get("structures", {})),
            "relation": self._least_used(RELATION_POOL, self.stats.get("relation_types", {})),
        }
        max_sim = max([h.score for h in blueprints] + [0.0])
        guidance = (
            f"Similar prior plans: {len(blueprints)}; top similarity {max_sim:.2f}. "
            f"Overrepresented relations: {', '.join(x['key'] for x in over['relations'][:4]) or 'none yet'}. "
            f"Prefer genre '{suggested['genre']}', tone '{suggested['tone']}', narrative "
            f"'{suggested['narrative']}', structure '{suggested['structure']}' and a relation "
            f"like '{suggested['relation']}'."
        )
        return {
            "topic_path": topic_path,
            "similar_blueprints": [
                {"score": round(h.score, 4), "topic_path": h.meta.get("topic_path"),
                 "main_concept": h.meta.get("main_concept", "")}
                for h in blueprints
            ],
            "similar_passages": [
                {"score": round(h.score, 4), "excerpt": h.meta.get("excerpt", ""),
                 "family_id": h.meta.get("family_id")}
                for h in passages
            ],
            "similar_fact_sets": [
                {"score": round(h.score, 4), "family_id": h.meta.get("family_id")}
                for h in facts
            ],
            "max_similarity": round(max_sim, 4),
            "overrepresented": over,
            "suggested": suggested,
            "guidance": guidance,
            "indexed_families": self.stats.get("families", 0),
        }

    def _top(self, counter: dict[str, int], n: int) -> list[dict[str, Any]]:
        items = list(counter.items())
        total = sum(v for _, v in items) or 1
        ordered = sorted(items, key=lambda x: -x[1])[:n]
        return [
            {"key": k, "count": v, "share": round(v / total, 4)} for k, v in ordered
        ]

    def _least_used(self, options: list[str], counter: dict[str, int]) -> str:
        if not options:
            return ""
        low = min(counter.get(o, 0) for o in options)
        ties = [o for o in options if counter.get(o, 0) == low]
        # Random tie-breaking prevents the first list entry from winning every
        # zero-count round (that bug collapsed narrative variety to expository).
        return ties[random.randrange(len(ties))]

    # ------------------------------------------------------------------ #
    # Post-generation novelty check
    # ------------------------------------------------------------------ #
    def post_generation_check(self, text: str, split: str = "candidate") -> dict[str, Any]:
        chunks = self._chunks(text)
        best_score = 0.0
        best_hit = None
        best_chunk_text = ""
        best_hit_text = ""
        exact = False
        near_chunks = 0
        for start, end, chunk in chunks:
            hits = self.indexes["passage"].search(self._embed(chunk), k=5, filter_fn=self._not_test)
            for hit in hits:
                if hit.score > best_score:
                    best_score = hit.score
                    best_hit = hit
                    best_chunk_text = chunk
                    best_hit_text = self._hit_text(hit.meta) or ""
                if hit.meta.get("chunk_hash") == sha256_text(chunk.strip()):
                    exact = True
            if hits and hits[0].score >= self.cfg.hnsw.near_duplicate_cosine:
                near_chunks += 1

        ngram_sim = 0.0
        if best_hit and best_chunk_text and best_hit_text:
            ngram_sim = jaccard(word_ngrams(best_chunk_text, 2), word_ngrams(best_hit_text, 2))
        fraction = near_chunks / max(1, len(chunks))
        near_dup = (
            best_score >= self.cfg.hnsw.near_duplicate_cosine
            or ngram_sim >= self.cfg.hnsw.near_duplicate_jaccard
            or exact
            or (len(chunks) >= 2 and fraction >= self.cfg.hnsw.near_duplicate_chunk_fraction)
        )
        return {
            "chunks": len(chunks),
            "max_cosine": round(best_score, 4),
            "nearest": (
                {"family_id": best_hit.meta.get("family_id"),
                 "variant_id": best_hit.meta.get("variant_id"),
                 "label": best_hit.meta.get("label"),
                 "score": round(best_hit.score, 4)}
                if best_hit else None
            ),
            "ngram_jaccard": round(ngram_sim, 4),
            "near_duplicate_chunks": near_chunks,
            "chunk_fraction": round(fraction, 4),
            "exact_duplicate": exact,
            "near_duplicate": near_dup,
            "thresholds": {
                "cosine": self.cfg.hnsw.near_duplicate_cosine,
                "jaccard": self.cfg.hnsw.near_duplicate_jaccard,
                "chunk_fraction": self.cfg.hnsw.near_duplicate_chunk_fraction,
            },
        }

    def _hit_text(self, meta: dict[str, Any]) -> str | None:
        full = self._variant_text(meta)
        if full is None:
            return meta.get("excerpt")
        start = meta.get("chunk_start")
        end = meta.get("chunk_end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(full):
            return full[start:end]
        return full

    def _variant_text(self, meta: dict[str, Any]) -> str | None:
        fid = meta.get("family_id")
        if not fid:
            return None
        fam = self.store.load_family(fid)
        if not fam:
            return None
        vid = meta.get("variant_id")
        if meta.get("base"):
            return fam.get("base_passage", {}).get("text")
        for v in fam.get("variants", {}).values():
            if v.get("variant_id") == vid:
                return v.get("text")
        return None

    # ------------------------------------------------------------------ #
    # Index writes
    # ------------------------------------------------------------------ #
    def add_family(self, family: Family) -> None:
        if family.quality.status != "ACCEPTED":
            return
        split = family.split
        common = {
            "family_id": family.family_id,
            "split": split,
            "topic_path": family.topic.topic_path,
            "genre": family.base_passage.genre,
            "tone": family.base_passage.tone,
            "structure": family.base_passage.structure,
            "created_at": utcnow(),
        }
        bp_text = family.blueprint.semantic_text
        self.indexes["blueprint"].add(
            self._embed(bp_text),
            {**common, "main_concept": family.blueprint.main_concept},
        )
        def add_document(text: str, checksum: str, token_count: int, variant_id_: str,
                         label: str, base: bool) -> None:
            chunks = self._chunks(text)
            for i, (start, end, chunk) in enumerate(chunks):
                self.indexes["passage"].add(
                    self._embed(chunk),
                    {
                        **common,
                        "variant_id": variant_id_,
                        "label": label,
                        "text_hash": checksum,
                        "chunk_hash": sha256_text(chunk.strip()),
                        "chunk_index": i,
                        "n_chunks": len(chunks),
                        "chunk_start": start,
                        "chunk_end": end,
                        "token_count": approx_tokens(chunk),
                        "doc_token_count": token_count,
                        "excerpt": truncate(chunk, 280),
                        "base": base,
                    },
                )

        for label, variant in family.variants.items():
            add_document(
                variant.text, variant.checksum, variant.token_count,
                variant.variant_id, label, False,
            )
        add_document(
            family.base_passage.text, family.base_passage.checksum,
            family.base_passage.token_count, family.base_passage.passage_id,
            "BASE", True,
        )

        triples = "; ".join(
            f"{f.subject} {f.predicate} {f.object}" for f in family.semantic_representation.facts
        )
        claims = " | ".join(c.claim_text for c in family.claim_set)
        self.indexes["fact_claim"].add(
            self._embed(f"{triples} || {claims}"),
            {
                **common,
                "claim_types": sorted({c.claim_type for c in family.claim_set}),
                "fact_types": sorted({str(f.qualifiers.get('type', 'relation')) for f in family.semantic_representation.facts}),
                "n_claims": len(family.claim_set),
            },
        )
        for label, variant in family.variants.items():
            ops = variant.edit_history.operations or ["PRESERVE"]
            self.indexes["edit_signature"].add(
                self._embed(f"{label} {' '.join(ops)}"),
                {**common, "label": label, "operations": ops},
            )

        self._bump_stats(family)
        self.save()

    def _bump_stats(self, family: Family) -> None:
        def inc(key: str, sub: str, n: int = 1) -> None:
            bucket = self.stats.setdefault(key, {})
            bucket[sub] = int(bucket.get(sub, 0)) + n

        for fact in family.semantic_representation.facts:
            inc("relation_types", fact.predicate)
        for ent in family.semantic_representation.entities:
            inc("entity_types", ent.entity_type)
            if len(self.stats["entities"]) < 2000:
                inc("entities", ent.name)
        inc("genres", family.base_passage.genre)
        inc("tones", family.base_passage.tone)
        inc("narratives", family.base_passage.narrative)
        inc("structures", family.base_passage.structure)
        inc("topic_paths", " > ".join(family.topic.topic_path))
        for label, variant in family.variants.items():
            inc("labels", label)
            for op in variant.edit_history.operations or ["PRESERVE"]:
                inc("edit_ops", op)
        self.stats["families"] = int(self.stats.get("families", 0)) + 1

    def save(self) -> None:
        for ns, index in self.indexes.items():
            index.save(self.root / ns)
        atomic_write_json(self.root / "stats.json", self.stats)

    # ------------------------------------------------------------------ #
    def rebuild(self, families: Iterable[Family]) -> dict[str, int]:
        for ns in NAMESPACES:
            self.indexes[ns] = HnswIndex(
                dim=self.cfg.hnsw.dim, m=self.cfg.hnsw.m,
                ef_construction=self.cfg.hnsw.ef_construction,
                ef_search=self.cfg.hnsw.ef_search, seed=self.cfg.project.seed,
            )
        self.stats = {
            "relation_types": {}, "entity_types": {}, "entities": {}, "genres": {},
            "tones": {}, "narratives": {}, "structures": {}, "topic_paths": {}, "edit_ops": {}, "labels": {},
            "families": 0,
        }
        n = 0
        for fam in families:
            self.add_family(fam)
            n += 1
        return {"families_indexed": n, "vectors": {ns: i.size for ns, i in self.indexes.items()}}

    def summary(self) -> dict[str, Any]:
        return {
            "vectors": {ns: i.size for ns, i in self.indexes.items()},
            "families": self.stats.get("families", 0),
            "top_relations": self._top(self.stats.get("relation_types", {}), 5),
            "embedder": getattr(self.embedder, "name", "unknown"),
        }
