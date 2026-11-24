"""Semantic graph diff between base and edited passages.

This is one validator among several, not a source of truth: extraction is noisy, so a
miss is recorded and reported rather than used to overrule the independent validator.
"""

from __future__ import annotations

import re
from typing import Any

from .schema import Claim, Fact, SemanticRepresentation


def _tokens(value: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9.]+", value.lower()) if t not in {"the", "a", "an", "of", "its", "their"}}


def _pred_match(a: str, b: str) -> bool:
    a_n, b_n = a.lower().replace(" ", "_"), b.lower().replace(" ", "_")
    if a_n == b_n or a_n in b_n or b_n in a_n:
        return True
    ta, tb = _tokens(a_n), _tokens(b_n)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.5


def _obj_match(a: str, b: str) -> bool:
    a, b = a.strip().lower(), b.strip().lower()
    if a == b:
        return True
    # "2012" vs "in 2012"; allow containment when the shorter string is informative
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 3 and shorter in longer:
        return True
    ta, tb = _tokens(a), _tokens(b)
    return bool(ta and tb) and (ta <= tb or tb <= ta)


NEUTRAL_OBJECT_WORDS = {
    "tracked", "monitored", "reviewed", "studied", "considered", "examined", "assessed",
    "discussed", "reported", "documented", "analysed", "analyzed", "pending", "unknown",
    "unclear", "under", "various", "several", "some", "ongoing",
}


def _neutral_mention(obj: str) -> bool:
    return bool(_tokens(obj) & NEUTRAL_OBJECT_WORDS)


def fact_states(facts: list[Fact], target: Fact) -> dict[str, list[Fact]]:
    """Classify variant facts relative to one base fact.

    A reversed triple is treated as a neutral mention, not a contradiction: extraction
    frequently swaps voice ("X launched Y" vs "Y launched_by X") and a graph diff must
    not manufacture contradictions out of paraphrase.
    """
    same: list[Fact] = []
    incompatible: list[Fact] = []
    for f in facts:
        if _pred_match(f.predicate, target.predicate) and (
            _obj_match(f.subject, target.subject) or _obj_match(f.object, target.subject)
        ):
            forward = _obj_match(f.subject, target.subject) and _obj_match(f.object, target.object)
            reverse = _obj_match(f.subject, target.object) and _obj_match(f.object, target.subject)
            if forward:
                same.append(f)
            elif not reverse and not _neutral_mention(f.object):
                incompatible.append(f)
    return {"same": same, "incompatible": incompatible}


def diff_graph(
    base: SemanticRepresentation,
    variant: SemanticRepresentation,
    claims: list[Claim],
    label: str,
) -> dict[str, Any]:
    per_claim: dict[str, Any] = {}
    misses: list[str] = []
    for claim in claims:
        claim_facts = [base.fact_by_id(fid) for fid in claim.fact_ids]
        claim_facts = [f for f in claim_facts if f is not None]
        if not claim_facts:
            per_claim[claim.claim_id] = {"status": "no_base_facts", "same": 0, "incompatible": 0}
            misses.append(f"{claim.claim_id}:no_base_facts")
            continue
        same_total, incompatible_total = 0, 0
        for bf in claim_facts:
            states = fact_states(variant.facts, bf)
            same_total += len(states["same"])
            incompatible_total += len(states["incompatible"])
        if label == "SUPPORTED":
            ok = same_total >= 1
        elif label == "CONTRADICTED":
            ok = incompatible_total >= 1
        else:
            ok = same_total == 0 and incompatible_total == 0
        if not ok:
            misses.append(claim.claim_id)
        per_claim[claim.claim_id] = {
            "status": "ok" if ok else "miss",
            "same": same_total,
            "incompatible": incompatible_total,
        }

    claim_fact_ids = {fid for c in claims for fid in c.fact_ids}
    unrelated_base = [f for f in base.facts if f.fact_id not in claim_fact_ids]
    preserved, changed = 0, 0
    for f in unrelated_base:
        states = fact_states(variant.facts, f)
        if states["same"]:
            preserved += 1
        else:
            changed += 1
    unrelated_total = len(unrelated_base)
    return {
        "label": label,
        "status": "ok",
        "per_claim": per_claim,
        "misses": misses,
        "ok": not misses,
        "unrelated_preserved": preserved,
        "unrelated_changed": changed,
        "unrelated_total": unrelated_total,
        "unrelated_stability": round(preserved / unrelated_total, 4) if unrelated_total else 1.0,
    }
