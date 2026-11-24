"""Offline deterministic mock client.

Used by tests and by ``--mock`` runs to exercise the full pipeline without network
access. It is explicitly not a data source: it produces templated passages and a
rule-based relation checker, and every artefact it touches is marked mock in metadata.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Type, TypeVar

from pydantic import BaseModel

from .config import Config, ModelCfg
from .prompts import PromptLibrary

M = TypeVar("M", bound=BaseModel)


class _Result:
    def __init__(self, data: BaseModel, model: str = "mock", prompt_version: str = "mock-1.0"):
        self.data = data
        self.raw_text = json.dumps(data.model_dump(mode="json"))
        self.model = model
        self.prompt_version = prompt_version
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}
        self.latency_ms = 0
        self.cached = False
        self.request_hash = "mock"
        self.raw_ref = None
        self.attempts = 1


class MockClient:
    """Duck-types :class:`tristate.llm.LlmClient` for the pipeline."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.prompts = PromptLibrary(cfg.prompts_dir)
        self.state: dict[str, dict[str, Any]] = {}
        self.calls = 0

    # ------------------------------------------------------------------ #
    def stats(self) -> dict[str, Any]:
        return {"calls": self.calls, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0, "mock": True}

    def _passage_key(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())

    # ------------------------------------------------------------------ #
    def structured(
        self,
        prompt_name: str,
        variables: dict[str, Any],
        schema: Type[M],
        model_cfg: ModelCfg,
        stage: str | None = None,
        family_id: str | None = None,
        candidate_id: str | None = None,
    ):
        self.calls += 1
        handler = getattr(self, f"_h_{prompt_name}", None)
        if handler is None:
            raise RuntimeError(f"mock does not implement prompt {prompt_name}")
        payload = handler(variables)
        return _Result(schema.model_validate(payload))

    # ------------------------------------------------------------------ #
    def _h_topics_expand(self, v: dict[str, Any]) -> dict[str, Any]:
        base = v["topic_name"]
        return {
            "subtopics": [
                {"name": f"{base} Methods", "description": "Common methods and practice.", "importance": 0.6},
                {"name": f"{base} History", "description": "Origins and change over time.", "importance": 0.5},
                {"name": f"{base} Policy", "description": "Rules and governance.", "importance": 0.4},
            ]
        }

    def _h_blueprint(self, v: dict[str, Any]) -> dict[str, Any]:
        focus = f"{v.get('topic_path', '')} :: {v.get('main_concept', '')}"
        return {
            "main_concept": f"How {focus} works in practice, with concrete examples.",
            "subtopics": ["origins", "mechanism", "outcomes"],
            "planned_entity_types": ["organization", "software", "person"],
            "planned_relation_types": ["developed_by", "released_in", "designed_for"],
            "planned_fact_types": ["relationship", "temporal", "purpose"],
            "target_fact_count": 4,
        }

    def _make_entities(self, v: dict[str, Any]) -> dict[str, str]:
        topic = (v.get("blueprint_json") and json.loads(v["blueprint_json"]).get("main_concept")) or "system"
        digest = hashlib.sha256(str(topic).encode("utf-8")).digest()
        seed = int.from_bytes(digest[:4], "little")
        names = ["Orion", "Kestrel", "Halcyon", "Marlowe", "Vantage", "Sable", "Tessera", "Lumen", "Cinder", "Pallas"]
        founders = ["Alice Brown", "Marcus Reed", "Priya Nair", "Tomas Ehrlich",
                    "Dana Whitfield", "Ivo Petrov", "Mei Lin", "Rafael Ortiz"]
        purposes = ["embedded applications", "marine surveying", "medical imaging", "crop monitoring",
                    "freight scheduling", "language instruction", "grid balancing", "archive digitisation"]
        topic_word = re.sub(r"[^a-z ]", "", str(topic).lower()).split()
        return {
            "subject": names[seed % len(names)],
            "founder": founders[seed % len(founders)],
            "year": str(1998 + seed % 20),
            "purpose": purposes[seed % len(purposes)],
            "alt_founder": founders[(seed + 3) % len(founders)],
            "alt_year": str(2005 + seed % 12),
            "alt_purpose": purposes[(seed + 5) % len(purposes)],
            "mechanism": "register-based virtual machine",
            "topic_word": topic_word[-1] if topic_word else "technical",
            "key": self._passage_key(str(topic)),
        }

    def _h_passage(self, v: dict[str, Any]) -> dict[str, Any]:
        e = self._make_entities(v)
        text = (
            f"{e['subject']} was developed by {e['founder']} in {e['year']}. "
            f"It uses a {e['mechanism']} and was designed primarily for {e['purpose']}. "
            f"The project released version two in {int(e['year']) + 3} with forty additional modules. "
            f"A field trial in {int(e['year']) + 5} covered twelve sites and reported stable results. "
            f"Analysts describe it as a representative example of {e['topic_word']} practice, "
            f"and its documentation is updated every quarter."
        )
        self.state[e["key"]] = e
        self.state[self._passage_key(text)] = e
        return {"text": text}

    def _lookup(self, text: str) -> dict[str, str]:
        key = self._passage_key(text)
        if key in self.state:
            return self.state[key]
        # reconstruct by scanning the passage
        m = re.search(r"(\w+) was developed by ([A-Z][\w]+ [A-Z][\w]+) in (\d{4})", text)
        if not m:
            return self._make_entities({"blueprint_json": json.dumps({"main_concept": text[:40]})})
        subject, founder, year = m.group(1), m.group(2), m.group(3)
        p = re.search(r"designed primarily for ([a-z ]+?)\.", text)
        return {
            "subject": subject, "founder": founder, "year": year,
            "purpose": p.group(1) if p else "general use",
            "alt_founder": "Bob Smith", "alt_year": "2004", "alt_purpose": "desktop applications",
            "mechanism": "register-based virtual machine", "key": key,
        }

    def _h_extract(self, v: dict[str, Any]) -> dict[str, Any]:
        sentences = json.loads(v["passage_json"])
        text = " ".join(s["text"] for s in sentences)
        first = sentences[0] if sentences else {"text": text, "sentence_id": "S1"}
        subj_m = re.search(r"\b([A-Z][a-zA-Z]{2,})\b", text)
        subject = subj_m.group(1) if subj_m else "The system"
        facts: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def add(predicate: str, obj: str, sid: str, quote: str, conf: float = 0.95) -> None:
            key = (predicate, obj)
            if key in seen or not obj:
                return
            seen.add(key)
            facts.append({
                "subject": subject, "predicate": predicate, "object": obj.strip(),
                "sentence_id": sid, "quote": quote, "confidence": conf,
            })

        for s in sentences:
            t, sid = s["text"], s["sentence_id"]
            m = re.search(r"developed by ([A-Z][\w]+(?: [A-Z][\w]+)+) in (\d{4})", t)
            if m:
                add("developed_by", m.group(1), sid, f"developed by {m.group(1)}")
                add("released_in", m.group(2), sid, f"in {m.group(2)}")
            m = re.search(r"released (?:version \w+ )?in (\d{4})", t)
            if m:
                add("released_version_in", m.group(1), sid, m.group(0))
            m = re.search(r"designed primarily for ([a-z][a-z ]+)", t)
            if m:
                add("designed_for", m.group(1).strip(), sid, m.group(0))
            m = re.search(r"uses an? ([a-z][a-z\- ]+)", t)
            if m:
                add("uses", m.group(1).strip(), sid, m.group(0))
            m = re.search(r"covered (\w+) sites", t)
            if m:
                add("covered_sites", m.group(1), sid, m.group(0))
            m = re.search(r"maintained by ([a-z][a-z ]+)", t)
            if m:
                add("maintained_by", m.group(1).strip(), sid, m.group(0))
        if len(facts) < 2:
            add("describes", subject, first["sentence_id"], first["text"][:40], 0.8)
        founder = None
        fm = re.search(r"developed by ([A-Z][\w]+(?: [A-Z][\w]+)+)", text)
        if fm:
            founder = fm.group(1)
        entities = [{"name": subject, "entity_type": "SOFTWARE"}]
        if founder:
            entities.append({"name": founder, "entity_type": "PERSON"})
        return {
            "summary": f"A short profile of {subject}.",
            "entities": entities,
            "facts": facts,
        }

    def _h_claims(self, v: dict[str, Any]) -> dict[str, Any]:
        sentences = json.loads(v["passage_json"])
        text = " ".join(s["text"] for s in sentences)
        e = self._lookup(text)
        s1 = sentences[0]["sentence_id"]
        s2 = sentences[min(1, len(sentences) - 1)]["sentence_id"]
        return {
            "claims": [
                {"claim_text": f"{e['subject']} was developed by {e['founder']}.",
                 "fact_ids": ["F1"], "claim_type": "ENTITY_RELATION", "difficulty": "easy",
                 "intent": "who", "evidence": [{"sentence_id": s1, "quote": f"developed by {e['founder']}"}]},
                {"claim_text": f"{e['subject']} was first released in {e['year']}.",
                 "fact_ids": ["F2"], "claim_type": "TEMPORAL", "difficulty": "easy",
                 "intent": "when", "evidence": [{"sentence_id": s1, "quote": f"in {e['year']}"}]},
                {"claim_text": f"{e['subject']} was designed primarily for {e['purpose']}.",
                 "fact_ids": ["F3"], "claim_type": "PURPOSE", "difficulty": "medium",
                 "intent": "why", "evidence": [{"sentence_id": s2, "quote": f"designed primarily for {e['purpose']}"}]},
            ]
        }

    def _h_edit_plan(self, v: dict[str, Any]) -> dict[str, Any]:
        label = v["label"]
        sentences = json.loads(v["sentences_json"])
        claims = json.loads(v.get("claims_json", "[]"))
        text = " ".join(s["text"] for s in sentences)
        e = self._lookup(text)
        sids = [s["sentence_id"] for s in sentences]

        def ids_for(keyword: str) -> list[str]:
            def text_of(c: dict[str, Any]) -> str:
                return str(c.get("claim") or c.get("claim_text") or "").lower()

            return [c["claim_id"] for c in claims if keyword in text_of(c)]

        founder_ids = ids_for("developed by") or ["C1"]
        year_ids = ids_for("released in") or ["C3"]
        purpose_ids = ids_for("designed") or ["C2"]
        if label == "SUPPORTED":
            return {"patches": [], "reasoning": "base already supports every claim"}
        if label == "CONTRADICTED":
            return {
                "patches": [
                    {"operation": "ENTITY_SUBSTITUTION", "target_sentence_id": sids[0],
                     "original_text": e["founder"], "replacement_text": e["alt_founder"],
                     "affected_claim_ids": founder_ids, "reason": "different developer"},
                    {"operation": "TEMPORAL_MUTATION", "target_sentence_id": sids[0],
                     "original_text": e["year"], "replacement_text": e["alt_year"],
                     "affected_claim_ids": year_ids, "reason": "different year"},
                    {"operation": "CATEGORY_SUBSTITUTION", "target_sentence_id": sids[1],
                     "original_text": e["purpose"], "replacement_text": e["alt_purpose"],
                     "affected_claim_ids": purpose_ids, "reason": "different purpose"},
                ],
                "reasoning": "replace each claim-bearing value",
            }
        neutral = f"{e['subject']} is a compact system with a documented toolchain."
        patches = [
            {"operation": "REPLACE_CLAUSE", "target_sentence_id": sids[0],
             "original_text": sentences[0]["text"], "replacement_text": neutral,
             "affected_claim_ids": founder_ids + year_ids, "reason": "remove origin and date"},
        ]
        if len(sentences) > 1:
            clause = f" and was designed primarily for {e['purpose']}"
            if clause in sentences[1]["text"]:
                patches.append(
                    {"operation": "DELETE_SPAN", "target_sentence_id": sids[1],
                     "original_text": clause, "replacement_text": "",
                     "affected_claim_ids": purpose_ids, "reason": "remove purpose"}
                )
        return {"patches": patches, "reasoning": "remove all claim evidence, keep topic"}

    def _h_validate(self, v: dict[str, Any]) -> dict[str, Any]:
        sentences = json.loads(v["passage_json"])
        text = " ".join(s["text"] for s in sentences)
        claims = json.loads(v["claims_json"])
        rels = []
        for c in claims:
            ct = c["claim"].lower()
            if "developed by" in ct or "created by" in ct:
                founder = c["claim"].split(" by ")[-1].rstrip(".")
                if founder.lower() in text.lower():
                    rel = "ENTAILED"
                elif re.search(r"developed by [A-Z][\w]+ [A-Z][\w]+", text):
                    rel = "CONTRADICTED"
                else:
                    rel = "NEUTRAL"
            elif "released in" in ct:
                year = re.search(r"(\d{4})", c["claim"])
                first_text = sentences[0]["text"] if sentences else text
                if year and year.group(1) in first_text:
                    rel = "ENTAILED"
                elif re.search(r"in \d{4}", first_text):
                    rel = "CONTRADICTED"
                else:
                    rel = "NEUTRAL"
            elif "designed" in ct:
                purpose = ct.split("designed primarily for ")[-1].rstrip(".")
                if purpose in text.lower():
                    rel = "ENTAILED"
                elif "designed primarily for" in text.lower():
                    rel = "CONTRADICTED"
                else:
                    rel = "NEUTRAL"
            else:
                rel = "NEUTRAL"
            rels.append({
                "claim_id": c["claim_id"], "relation": rel, "confidence": 0.9,
                "sentence_id": sentences[0]["sentence_id"],
                "quote": sentences[0]["text"][:40], "rationale": "mock rule",
            })
        return {"claim_relations": rels}

    def _h_validate_second(self, v: dict[str, Any]) -> dict[str, Any]:
        out = self._h_validate(v)
        out["passage_summary"] = "mock summary"
        return out
