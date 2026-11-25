"""Deterministic source inspection and claim cards.

The English family is the authority.  This module never edits it; it only
checks that the family is complete and derives the *semantic obligations* that
every translation must satisfy.  Claim cards are built deterministically from
the source claim, its linked facts, numbers and polarity words.  A target
language call can enrich wording, but it cannot silently change these cards.
"""

from __future__ import annotations

import re
from collections import OrderedDict

from ..schema import Claim, Family, Variant, variant_checksum
from ..util import normalize_ws, sha256_json, sha256_text
from .models import ClaimSemanticCard, GlossaryEntry, Relation, TargetProfile

LABELS: tuple[Relation, ...] = ("SUPPORTED", "CONTRADICTED", "UNSUPPORTED")
_NUMBER_RE = re.compile(r"(?<![\w])(?:\d[\d,]*(?:\.\d+)?%?)(?![\w])")
_YEAR_RE = re.compile(r"\b(?:1[5-9]\d{2}|20\d{2})\b")
_NEGATION_RE = re.compile(r"\b(?:not|no|never|none|neither|nor|without|cannot|can't|doesn't|isn't|aren't|wasn't|weren't|fail(?:s|ed)?\s+to)\b", re.IGNORECASE)
_MODAL_RE = re.compile(r"\b(?:may|might|could|can|should|would|likely|possibly|probably|suggests?|appears?|reportedly)\b", re.IGNORECASE)


class SourceError(ValueError):
    """The source family cannot be translated as-is."""


def source_checksum(family: Family) -> str:
    """Checksum of the immutable source payload (not the mutable quality block)."""

    payload = {
        "family_id": family.family_id,
        "split": family.split,
        "split_group_id": family.split_group_id,
        "base_passage": family.base_passage.model_dump(mode="json"),
        "semantic_representation": family.semantic_representation.model_dump(mode="json"),
        "claims": [c.model_dump(mode="json") for c in family.claim_set],
        "variants": [
            {
                "variant_id": v.variant_id,
                "label": v.label,
                "text": v.text,
                "checksum": variant_checksum(v),
                "relations": [r.model_dump(mode="json") for r in v.relations_by_claim],
                "semantic_representation": v.semantic_representation.model_dump(mode="json") if v.semantic_representation else None,
            }
            for v in family.variants.values()
        ],
    }
    return sha256_json(payload)


def preflight(family: Family) -> dict[str, object]:
    """Return a machine-readable source audit, or raise ``SourceError``."""

    problems: list[str] = []
    if not family.family_id:
        problems.append("missing family_id")
    if family.quality.status != "ACCEPTED":
        problems.append(f"source quality is {family.quality.status}, not ACCEPTED")
    labels = [v.label for v in family.variants.values()]
    if sorted(labels) != sorted(LABELS):
        problems.append(f"expected exactly {list(LABELS)}, got {labels}")
    if not family.claim_set:
        problems.append("family has no claims")
    claim_ids = [c.claim_id for c in family.claim_set]
    if len(set(claim_ids)) != len(claim_ids):
        problems.append("duplicate claim ids")
    for variant in family.variants.values():
        if not variant.text.strip():
            problems.append(f"{variant.variant_id} is empty")
        rels = {r.claim_id for r in variant.relations_by_claim}
        if rels and rels != set(claim_ids):
            problems.append(f"{variant.label} relations do not cover the claim set")
        if variant.validation and variant.validation.status not in ("PASS",):
            problems.append(f"{variant.label} source validation is {variant.validation.status}")
    if family.split not in ("train", "dev", "test", "validation"):
        problems.append(f"invalid split: {family.split}")
    if problems:
        raise SourceError("; ".join(problems))
    return {
        "family_id": family.family_id,
        "split": family.split,
        "claims": len(claim_ids),
        "variants": len(labels),
        "source_checksum": source_checksum(family),
    }


def expected_relations(family: Family) -> dict[str, dict[str, Relation]]:
    """label -> claim_id -> expected relation, copied from the English source."""

    out: dict[str, dict[str, Relation]] = {}
    for variant in family.variants.values():
        if variant.label not in LABELS:
            continue
        rels = {r.claim_id: _as_relation(r.relation) for r in variant.relations_by_claim}
        if not rels and variant.validation:
            rels = {r.claim_id: _as_relation(r.relation) for r in variant.validation.relations}
        # A variant's own label is the contract; a missing per-claim relation
        # must not become an accidental NEUTRAL.
        out[variant.label] = {c.claim_id: rels.get(c.claim_id, variant.label) for c in family.claim_set}
    return out


def _as_relation(value: str) -> Relation:
    normalized = (value or "").strip().upper()
    aliases = {
        "ENTAILED": "SUPPORTED",
        "ENTAILMENT": "SUPPORTED",
        "SUPPORTS": "SUPPORTED",
        "NEUTRAL": "UNSUPPORTED",
        "UNSUPPORTED": "UNSUPPORTED",
        "CONTRADICTED": "CONTRADICTED",
        "CONTRADICTION": "CONTRADICTED",
    }
    if normalized in aliases:
        return aliases[normalized]  # type: ignore[return-value]
    raise SourceError(f"unknown relation in source: {value!r}")


def _facts(family: Family) -> dict[str, object]:
    out: dict[str, object] = {}
    if family.semantic_representation:
        for fact in family.semantic_representation.facts:
            out.setdefault(fact.fact_id, fact)
    for variant in family.variants.values():
        sem = variant.semantic_representation
        if not sem:
            continue
        for fact in sem.facts:
            out.setdefault(fact.fact_id, fact)
    return out


def _fact_supports_claim(fact: object, claim_text: str) -> bool:
    text = normalize_ws(claim_text).casefold()
    parts = [
        normalize_ws(str(getattr(fact, "subject", ""))).casefold(),
        normalize_ws(str(getattr(fact, "object", ""))).casefold(),
    ]
    return any(p and p in text for p in parts)


def claim_cards(family: Family) -> list[ClaimSemanticCard]:
    facts = _facts(family)
    cards: list[ClaimSemanticCard] = []
    for claim in family.claim_set:
        # A section-level semantic graph can attach a fact that is not the
        # sentence's own (fact reuse across claims).  Keep only facts whose
        # subject/object actually occur in this claim; otherwise the card would
        # silently assert a different triple than the claim.
        linked = [facts[fid] for fid in claim.fact_ids if fid in facts and _fact_supports_claim(facts[fid], claim.claim_text)]
        if linked:
            subject = "; ".join(OrderedDict.fromkeys(str(getattr(f, "subject", "")) for f in linked if getattr(f, "subject", "")))
            predicate = "; ".join(OrderedDict.fromkeys(str(getattr(f, "predicate", "")) for f in linked if getattr(f, "predicate", "")))
            obj = "; ".join(OrderedDict.fromkeys(str(getattr(f, "object", "")) for f in linked if getattr(f, "object", "")))
            qualifiers = []
            for fact in linked:
                qualifiers.extend(f"{k}={v}" for k, v in (getattr(fact, "qualifiers", {}) or {}).items())
        else:
            subject = predicate = obj = ""
            qualifiers = []
        text = normalize_ws(claim.claim_text)
        numbers = list(OrderedDict.fromkeys(_NUMBER_RE.findall(text)))
        dates = list(OrderedDict.fromkeys(_YEAR_RE.findall(text)))
        negation = bool(_NEGATION_RE.search(text))
        modal_match = _MODAL_RE.search(text)
        modality = "qualified" if modal_match else "asserted"
        distinctions = []
        if negation:
            distinctions.append("negation or absence is part of the claim and must remain explicit")
        if numbers or dates:
            distinctions.append("numbers/dates must keep the same value and scope")
        if claim.claim_type:
            distinctions.append(f"claim type: {claim.claim_type}")
        cards.append(
            ClaimSemanticCard(
                claim_id=claim.claim_id,
                source_text=claim.claim_text,
                subject=subject,
                predicate=predicate,
                object=obj,
                relation_obligation="SUPPORTED",
                modifiers=list(OrderedDict.fromkeys(qualifiers)),
                numbers=numbers,
                dates=dates,
                negation=negation,
                modality=modality,
                polarity="negative" if negation else "positive",
                critical_distinctions=distinctions,
                allowed_paraphrase=[
                    "reorder clauses to satisfy target-language syntax",
                    "replace an English construction with its idiomatic target-language equivalent",
                    "split one long sentence into shorter target-language sentences",
                ],
                forbidden_changes=[
                    "do not change the entity, number, date, polarity, or scope of the claim",
                    "do not add a cause, consequence, or evaluation that the source does not state",
                    "do not turn a qualified or negated statement into an unqualified positive one",
                ],
                source_fact_ids=list(claim.fact_ids),
            )
        )
    return cards


def seed_glossary(family: Family) -> list[GlossaryEntry]:
    """Seed terminology from source entities.  Target terms are resolved later."""

    entries: list[GlossaryEntry] = []
    seen: set[str] = set()
    for variant in family.variants.values():
        sem = variant.semantic_representation
        if not sem:
            continue
        for entity in sem.entities:
            term = normalize_ws(entity.name)
            key = term.casefold()
            if not term or key in seen:
                continue
            seen.add(key)
            kind = "entity" if getattr(entity, "entity_type", "") in ("PERSON", "ORG", "LOCATION", "GPE") else "technical"
            entries.append(GlossaryEntry(source_term=term, target_term="", kind=kind))
        if len(entries) >= 40:
            break
    return entries


def source_digest(family: Family) -> str:
    return sha256_text(source_checksum(family))


def claim_by_id(family: Family) -> dict[str, Claim]:
    return {c.claim_id: c for c in family.claim_set}


def variant_by_label(family: Family) -> dict[str, Variant]:
    return {v.label: v for v in family.variants.values()}


def profile_payload(profile: TargetProfile) -> dict[str, object]:
    return profile.model_dump(mode="json")
