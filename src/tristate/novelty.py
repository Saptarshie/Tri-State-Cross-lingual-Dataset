"""HNSW-backed novelty memory and feedback.

Four independent namespaces (blueprint, passage, fact_claim, edit_signature) each hold
vectors plus metadata that points back to a durable family record. Only accepted
material is indexed, so the novelty signal cannot be poisoned by rejected candidates,
and test-split families are excluded from the retrieval pool used to steer generation.
"""

from __future__ import annotations

from typing import Any, Iterable

from .config import Config
from .embeddings import get_embedder
from .hnsw import HnswIndex
from .schema import Family
from .store import Store
from .util import atomic_write_json, jaccard, read_json, sha256_text, truncate, utcnow, word_ngrams

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
            "tones": {}, "structures": {}, "topic_paths": {}, "edit_ops": {}, "labels": {},
            "families": 0,
        }

    # ------------------------------------------------------------------ #
    def _not_test(self, meta: dict[str, Any]) -> bool:
        if not self.cfg.hnsw.split_aware:
            return True
        return meta.get("split") != "test"

    def _embed(self, text: str):
        return self.embedder.encode(text)

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
            "structure": self._least_used(self.cfg.blueprint.structures, self.stats.get("structures", {})),
            "relation": self._least_used(RELATION_POOL, self.stats.get("relation_types", {})),
        }
        max_sim = max([h.score for h in blueprints] + [0.0])
        guidance = (
            f"Similar prior plans: {len(blueprints)}; top similarity {max_sim:.2f}. "
            f"Overrepresented relations: {', '.join(x['key'] for x in over['relations'][:4]) or 'none yet'}. "
            f"Prefer genre '{suggested['genre']}', tone '{suggested['tone']}', structure "
            f"'{suggested['structure']}' and a relation like '{suggested['relation']}'."
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
        return min(options, key=lambda o: (counter.get(o, 0), options.index(o)))

    # ------------------------------------------------------------------ #
    # Post-generation novelty check
    # ------------------------------------------------------------------ #
    def post_generation_check(self, text: str, split: str = "candidate") -> dict[str, Any]:
        vec = self._embed(text)
        hits = self.indexes["passage"].search(vec, k=5, filter_fn=self._not_test)
        nearest = hits[0] if hits else None
        ngram_sim = 0.0
        exact = any(
            h.meta.get("text_hash") == sha256_text(text.strip()) for h in hits
        )
        if nearest:
            other_text = self._variant_text(nearest.meta)
            if other_text:
                ngram_sim = jaccard(word_ngrams(text, 2), word_ngrams(other_text, 2))
        cosine_max = max([h.score for h in hits] + [0.0])
        near_dup = (
            cosine_max >= self.cfg.hnsw.near_duplicate_cosine
            or ngram_sim >= self.cfg.hnsw.near_duplicate_jaccard
            or exact
        )
        return {
            "max_cosine": round(cosine_max, 4),
            "nearest": (
                {"family_id": nearest.meta.get("family_id"),
                 "variant_id": nearest.meta.get("variant_id"),
                 "label": nearest.meta.get("label"),
                 "score": round(nearest.score, 4)}
                if nearest else None
            ),
            "ngram_jaccard": round(ngram_sim, 4),
            "exact_duplicate": exact,
            "near_duplicate": near_dup,
            "thresholds": {
                "cosine": self.cfg.hnsw.near_duplicate_cosine,
                "jaccard": self.cfg.hnsw.near_duplicate_jaccard,
            },
        }

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
        for label, variant in family.variants.items():
            self.indexes["passage"].add(
                self._embed(variant.text),
                {
                    **common,
                    "variant_id": variant.variant_id,
                    "label": label,
                    "text_hash": variant.checksum,
                    "token_count": variant.token_count,
                    "excerpt": truncate(variant.text, 280),
                    "base": False,
                },
            )
        self.indexes["passage"].add(
            self._embed(family.base_passage.text),
            {
                **common,
                "variant_id": family.base_passage.passage_id,
                "label": "BASE",
                "text_hash": family.base_passage.checksum,
                "token_count": family.base_passage.token_count,
                "excerpt": truncate(family.base_passage.text, 280),
                "base": True,
            },
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
            "tones": {}, "structures": {}, "topic_paths": {}, "edit_ops": {}, "labels": {},
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
