"""Atomic claim selection from an extracted fact graph.

Claims are filtered by deterministic atomicity checks before any validator sees them:
one proposition, no pronoun-led sentence, anchored evidence, distinct from siblings.
For long documents, candidate facts are chosen across sections first, so claims are
distributed through the document instead of clustering in the opening.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from .config import Config
from .errors import StageError
from .llm import LlmClient
from .schema import Claim, Fact, PassageSection, SemanticRepresentation
from .spans import resolve_quote, sentence_index
from .util import containment, jaccard, normalize_ws, token_set, word_ngrams

_PRONOUN_START = re.compile(
    r"^(it|they|this|these|those|he|she|his|her|their|its|we|you)\b", re.I
)
_AUX = re.compile(
    r"\b(is|was|were|are|has|have|had|will|would|can|could|uses|used|produces|produced|"
    r"contains|contained|includes|included|became|become|remains|remained|requires|"
    r"required|holds|held|reports|reported)\b",
    re.I,
)


class _Evidence(BaseModel):
    sentence_id: str | None = None
    quote: str = ""


class _RawClaim(BaseModel):
    claim_text: str
    fact_ids: list[str] = Field(default_factory=list)
    claim_type: str = "ENTITY_RELATION"
    difficulty: str = "medium"
    intent: str = "what"
    evidence: list[_Evidence] = Field(default_factory=list)


class _ClaimsPayload(BaseModel):
    claims: list[_RawClaim] = Field(default_factory=list)


def looks_compound(text: str, fact_ids: list[str]) -> bool:
    low = text.lower()
    if ";" in low:
        return True
    if re.search(r",\s+(and|but|while|whereas|although)\b", low):
        return True
    if " and " in low:
        parts = [p for p in low.split(" and ") if p.strip()]
        if len(parts) >= 2 and all(_AUX.search(p) for p in parts):
            return True
        if len(fact_ids) > 1:
            return True
    return False


def _claim_problems(
    text: str, fact_ids: list[str], passage: str, semantic: SemanticRepresentation, cfg: Config
) -> list[str]:
    problems: list[str] = []
    if len(text) > cfg.claims.max_claim_chars:
        problems.append("too long")
    if not text.endswith("."):
        problems.append("not a declarative sentence")
    if _PRONOUN_START.match(text):
        problems.append("starts with a pronoun")
    if cfg.claims.require_atomic_claims and looks_compound(text, fact_ids):
        problems.append("compound claim")
    if containment(text, passage) < 0.6:
        problems.append("low lexical support in passage")
    entity_names = {e.name.lower() for e in semantic.entities}
    low = text.lower()
    if entity_names and not any(name in low for name in entity_names if len(name) > 2):
        problems.append("does not mention a known entity")
    return problems


def _fact_section(fact: Fact, sections: list[PassageSection] | None) -> str | None:
    if fact.section_id:
        return fact.section_id
    if not sections:
        return None
    for span in fact.source_spans:
        for sec in sections:
            if sec.start_char <= span.start_char < sec.end_char:
                return sec.section_id
    return None


def choose_claim_facts(
    semantic: SemanticRepresentation,
    cfg: Config,
    sections: list[PassageSection] | None = None,
) -> list[Fact]:
    """Pick up to the target number of facts, spread across sections and predicates."""
    target = cfg.claims.target_claims_per_document
    buckets: dict[str, list[Fact]] = {}
    order: list[str] = []
    for fact in semantic.facts:
        key = _fact_section(fact, sections) or "_doc"
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(fact)

    # if no sectioning is available, bucket by the single "_doc" key
    selected: list[Fact] = []
    deferred: list[Fact] = []
    seen_pred: set[str] = set()
    while len(selected) < target and any(buckets.values()):
        progressed = False
        for key in order:
            bucket = buckets.get(key) or []
            while bucket:
                fact = bucket.pop(0)
                pred = fact.predicate.lower()
                if pred in seen_pred and len(selected) + 1 < target:
                    deferred.append(fact)
                    continue
                selected.append(fact)
                seen_pred.add(pred)
                progressed = True
                break
            if len(selected) >= target:
                break
        if not progressed:
            break

    # predicate diversity is a preference, not a reason to underfill the target
    for fact in deferred:
        if len(selected) >= target:
            break
        selected.append(fact)

    # if section bucketing produced nothing useful, fall back to even sampling by offset
    if not selected:
        facts = sorted(semantic.facts, key=lambda f: f.source_spans[0].start_char if f.source_spans else 0)
        step = max(1, len(facts) // max(1, target))
        selected = facts[::step][:target]
    return selected


def _evidence_sentences(
    passage_text: str, facts: list[Fact]
) -> list[dict[str, Any]]:
    refs = sentence_index(passage_text)
    wanted: set[str] = set()
    for fact in facts:
        for span in fact.source_spans:
            wanted.add(span.sentence_id)
    return [
        {"sentence_id": r.sentence_id, "text": r.text}
        for r in refs
        if r.sentence_id in wanted
    ]


def select_claims(
    llm: LlmClient,
    cfg: Config,
    passage_text: str,
    semantic: SemanticRepresentation,
    candidate_id: str | None = None,
    sections: list[PassageSection] | None = None,
) -> list[Claim]:
    candidate_facts = choose_claim_facts(semantic, cfg, sections)
    evidence_sentences = _evidence_sentences(passage_text, candidate_facts)
    if not evidence_sentences:
        raise StageError("claims_insufficient", "no evidence sentences for candidate facts", {})

    result = llm.structured(
        "claims",
        {
            "passage_json": json.dumps(evidence_sentences, indent=2),
            "facts_json": json.dumps(
                [
                    {
                        "fact_id": f.fact_id,
                        "subject": f.subject,
                        "predicate": f.predicate,
                        "object": f.object,
                        "qualifiers": f.qualifiers,
                        "section_id": f.section_id,
                    }
                    for f in candidate_facts
                ],
                indent=2,
            ),
            "target_claims": cfg.claims.target_claims_per_document,
            "min_claims": cfg.claims.min_claims_per_family,
            "max_claims": cfg.claims.max_claims_per_family,
            "min_sections": cfg.claims.min_distinct_sections,
        },
        _ClaimsPayload,
        cfg.llm.claims,
        stage="claims",
        candidate_id=candidate_id,
    )
    valid_fact_ids = {f.fact_id for f in semantic.facts}
    accepted: list[Claim] = []
    rejected: list[dict] = []
    for raw in result.data.claims:
        text = normalize_ws(raw.claim_text)
        if not text.endswith((".", "?", "!")):
            text += "."
        fact_ids = [fid for fid in raw.fact_ids if fid in valid_fact_ids]
        spans = []
        for ev in raw.evidence:
            span = resolve_quote(passage_text, ev.sentence_id, ev.quote)
            if span is not None and span not in spans:
                spans.append(span)
        if not spans:
            rejected.append({"claim": text, "reason": "no resolvable evidence span"})
            continue
        problems = _claim_problems(text, fact_ids, passage_text, semantic, cfg)
        if problems:
            rejected.append({"claim": text, "reason": "; ".join(problems)})
            continue
        if any(
            jaccard(word_ngrams(text, 2), word_ngrams(c.claim_text, 2)) > 0.8
            or (set(fact_ids) and set(fact_ids) == set(c.fact_ids))
            for c in accepted
        ):
            rejected.append({"claim": text, "reason": "duplicate of another claim"})
            continue
        section_ids = sorted(
            {
                sec.section_id
                for span in spans
                for sec in (sections or [])
                if sec.start_char <= span.start_char < sec.end_char
            }
        )
        accepted.append(
            Claim(
                claim_id="",
                claim_text=text,
                fact_ids=fact_ids,
                evidence_spans=spans,
                claim_type=(raw.claim_type or "ENTITY_RELATION").upper(),
                difficulty=(raw.difficulty or "medium").lower(),
                intent=(raw.intent or "what").lower(),
                section_ids=section_ids,
            )
        )

    if len(accepted) < cfg.claims.min_claims_per_family:
        raise StageError(
            "claims_insufficient",
            f"only {len(accepted)} usable claims (need {cfg.claims.min_claims_per_family})",
            {"rejected": rejected[:10]},
        )

    # Diversity-aware selection: round-robin over claim types, keep order stable.
    buckets: dict[str, list[Claim]] = {}
    for c in accepted:
        buckets.setdefault(c.claim_type, []).append(c)
    selected: list[Claim] = []
    while len(selected) < cfg.claims.target_claims_per_document and any(buckets.values()):
        for key in sorted(buckets):
            if buckets[key] and len(selected) < cfg.claims.target_claims_per_document:
                selected.append(buckets[key].pop(0))
    for i, claim in enumerate(selected, start=1):
        claim.claim_id = f"C{i}"

    # Section spread is a construction property: a long document should not yield all
    # claims from one paragraph. Only enforce it when sectioning is available.
    if sections:
        distinct = {sid for c in selected for sid in c.section_ids}
        needed = min(cfg.claims.min_distinct_sections, len(sections))
        if len(distinct) < needed:
            raise StageError(
                "claims_insufficient",
                f"claims cover {len(distinct)} sections (need {needed})",
                {"claims": [c.claim_id for c in selected], "sections": sorted(distinct)},
            )
    return selected


def claim_signature(claims: list[Claim]) -> str:
    return " | ".join(sorted(c.claim_text for c in claims))


def claim_types(claims: list[Claim]) -> list[str]:
    return sorted({c.claim_type for c in claims})


def claim_word_overlap(claims: list[Claim]) -> float:
    """Mean pairwise bigram Jaccard inside the claim set (redundancy signal)."""
    if len(claims) < 2:
        return 0.0
    sims = []
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            sims.append(jaccard(word_ngrams(claims[i].claim_text), word_ngrams(claims[j].claim_text)))
    return round(sum(sims) / len(sims), 4)


def claim_tokens(claims: list[Claim]) -> set[str]:
    out: set[str] = set()
    for c in claims:
        out |= token_set(c.claim_text)
    return out
