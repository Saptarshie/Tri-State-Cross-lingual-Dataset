"""Family-level validation gates.

The validator never sees the intended label or the editor's reasoning, always judges the
passage alone, and is a different model family from the generator. Hard deterministic
checks run alongside it; a family is accepted only when both agree.
"""

from __future__ import annotations

import json
import random
from typing import Any

from pydantic import BaseModel, Field

from .config import Config
from .errors import StageError
from .llm import LlmClient
from .schema import (
    EXPECTED_RELATION,
    Claim,
    ClaimRelation,
    SemanticRepresentation,
    ValidationResult,
)
from .spans import resolve_quote, sentences_for_prompt
from .util import (
    approx_tokens,
    content_overlap,
    english_score,
    meta_statement_hits,
    normalize_ws,
    split_sentences,
    stable_seed,
    truncate,
)


class _RawRelation(BaseModel):
    claim_id: str
    relation: str
    confidence: float = 0.0
    sentence_id: str | None = None
    quote: str = ""
    rationale: str = ""


class _ValidatePayload(BaseModel):
    claim_relations: list[_RawRelation] = Field(default_factory=list)


def _claims_payload(claims: list[Claim]) -> str:
    return json.dumps(
        [{"claim_id": c.claim_id, "claim": c.claim_text} for c in claims], indent=2
    )


def _normalise_relations(
    payload: list[_RawRelation], claims: list[Claim]
) -> tuple[list[ClaimRelation], list[str]]:
    by_id: dict[str, _RawRelation] = {}
    for raw in payload:
        if raw.claim_id and raw.claim_id not in by_id:
            by_id[raw.claim_id] = raw
    out: list[ClaimRelation] = []
    missing: list[str] = []
    for claim in claims:
        raw = by_id.get(claim.claim_id)
        if raw is None:
            missing.append(claim.claim_id)
            out.append(
                ClaimRelation(
                    claim_id=claim.claim_id,
                    relation="UNCERTAIN",
                    confidence=0.0,
                    rationale="validator did not return this claim",
                )
            )
            continue
        try:
            out.append(
                ClaimRelation(
                    claim_id=claim.claim_id,
                    relation=raw.relation,
                    confidence=max(0.0, min(1.0, float(raw.confidence))),
                    evidence_span=raw.quote or None,
                    evidence_sentence_id=raw.sentence_id,
                    rationale=truncate(raw.rationale or "", 300),
                )
            )
        except ValueError:
            out.append(
                ClaimRelation(
                    claim_id=claim.claim_id,
                    relation="UNCERTAIN",
                    confidence=0.0,
                    rationale=f"invalid relation label: {raw.relation}",
                )
            )
    return out, missing


def _run_validation(
    llm: LlmClient,
    cfg: Config,
    prompt_name: str,
    claims: list[Claim],
    text: str,
    model_cfg,
    stage: str,
    candidate_id: str | None,
) -> tuple[list[ClaimRelation], str, str | None]:
    result = llm.structured(
        prompt_name,
        {
            "passage_json": json.dumps(sentences_for_prompt(text), indent=2),
            "claims_json": _claims_payload(claims),
        },
        _ValidatePayload,
        model_cfg,
        stage=stage,
        candidate_id=candidate_id,
    )
    relations, missing = _normalise_relations(result.data.claim_relations, claims)
    return relations, result.prompt_version, result.raw_ref


def validate_passage(
    llm: LlmClient,
    cfg: Config,
    claims: list[Claim],
    text: str,
    label: str,
    candidate_id: str | None = None,
    stage: str = "family_validate",
    use_second: bool = True,
    second_reason: str = "",
) -> ValidationResult:
    expected = EXPECTED_RELATION[label]
    relations, prompt_version, raw_ref = _run_validation(
        llm, cfg, "validate", claims, text, cfg.llm.validator, stage, candidate_id
    )
    failures: list[str] = []
    low_conf: list[str] = []
    for rel in relations:
        if rel.relation != expected:
            failures.append(
                f"{rel.claim_id}: expected {expected}, got {rel.relation} "
                f"(conf {rel.confidence:.2f})"
            )
        elif rel.confidence < cfg.validation.min_relation_confidence:
            low_conf.append(rel.claim_id)

    should_second = use_second and (
        bool(low_conf)
        or (bool(failures) and cfg.validation.second_validator_on_failure)
        or (
            cfg.validation.sample_second_validator > 0
            and random.Random(stable_seed(candidate_id or text, label)).random()
            < cfg.validation.sample_second_validator
        )
    )
    second_relations: list[ClaimRelation] = []
    agreement: float | None = None
    second_model: str | None = None
    if should_second:
        second_relations, _, _ = _run_validation(
            llm, cfg, "validate_second", claims, text, cfg.llm.validator_second, stage, candidate_id
        )
        second_model = cfg.llm.validator_second.name
        agree = sum(
            1 for a, b in zip(relations, second_relations) if a.relation == b.relation
        )
        agreement = round(agree / max(1, len(relations)), 4)
        for a, b in zip(relations, second_relations):
            if a.relation != b.relation and a.relation == expected:
                failures.append(
                    f"{a.claim_id}: validator disagreement ({a.relation} vs {b.relation})"
                )

    status = "PASS" if not failures and not low_conf else "FAIL"
    if not failures and low_conf and not second_relations:
        status = "UNCERTAIN"
    return ValidationResult(
        variant_label=label,
        status=status,  # type: ignore[arg-type]
        relations=relations,
        failures=failures + ([f"low confidence: {low_conf}"] if low_conf else []),
        validator_model=cfg.llm.validator.name,
        prompt_version=prompt_version,
        second_validator_model=second_model,
        second_relations=second_relations,
        agreement=agreement,
        raw_ref=raw_ref,
        hard_checks={"second_reason": second_reason} if second_reason else {},
    )


def verify_base_claims(
    llm: LlmClient,
    cfg: Config,
    claims: list[Claim],
    base_text: str,
    candidate_id: str | None = None,
) -> tuple[list[Claim], list[dict[str, Any]], ValidationResult]:
    """Independently confirm the base passage supports every selected claim.

    Claims that fail are dropped (and reported). If too few survive the family cannot
    proceed; the caller quarantines rather than editing an unsupported claim set.
    """
    result = validate_passage(
        llm, cfg, claims, base_text, "SUPPORTED", candidate_id,
        stage="base_check", use_second=False,
    )
    rel_map = {r.claim_id: r for r in result.relations}
    kept: list[Claim] = []
    dropped: list[dict[str, Any]] = []
    for claim in claims:
        rel = rel_map.get(claim.claim_id)
        if rel and rel.relation == "ENTAILED" and rel.confidence >= cfg.validation.min_relation_confidence:
            kept.append(claim)
        else:
            dropped.append(
                {
                    "claim_id": claim.claim_id,
                    "claim_text": claim.claim_text,
                    "relation": rel.relation if rel else "MISSING",
                    "confidence": rel.confidence if rel else 0.0,
                    "rationale": rel.rationale if rel else "",
                }
            )
    if len(kept) < cfg.claims.min_claims_per_family:
        raise StageError(
            "base_claims_unsupported",
            f"base passage supports only {len(kept)} of {len(claims)} claims",
            {"dropped": dropped, "kept": [c.claim_id for c in kept]},
        )
    # compact IDs so the claim set is contiguous again
    for i, claim in enumerate(kept, start=1):
        claim.claim_id = f"C{i}"
    return kept, dropped, result


# --------------------------------------------------------------------------- #
# Deterministic family checks
# --------------------------------------------------------------------------- #


def family_hard_checks(
    cfg: Config,
    claims: list[Claim],
    base_text: str,
    variant_texts: dict[str, str],
    source_type: str,
    semantic: SemanticRepresentation,
) -> dict[str, Any]:
    checks: dict[str, Any] = {}

    def record(name: str, ok: bool, detail: str = "") -> None:
        checks[name] = {"ok": bool(ok), "detail": detail}

    record("three_labels", set(variant_texts) == {"SUPPORTED", "CONTRADICTED", "UNSUPPORTED"},
           str(sorted(variant_texts)))
    record(
        "claim_count_in_range",
        cfg.claims.min_claims_per_family <= len(claims) <= cfg.claims.max_claims_per_family,
        f"{len(claims)} claims",
    )
    record("unique_claim_ids", len({c.claim_id for c in claims}) == len(claims))
    record("claims_have_evidence", all(c.evidence_spans for c in claims))
    record("claims_have_facts", all(c.fact_ids for c in claims))
    record("language_en", cfg.project.language == "en")
    record("source_provenance", bool(source_type), source_type)
    distinct = len({normalize_ws(t) for t in variant_texts.values()})
    record("variants_distinct", distinct == 3, f"{distinct} distinct texts")

    base_tokens = max(1, approx_tokens(base_text))
    for label, text in variant_texts.items():
        toks = approx_tokens(text)
        ratio = toks / base_tokens
        record(f"{label}_length_ratio", cfg.variants.min_length_ratio <= ratio <= cfg.variants.max_length_ratio,
               f"{ratio:.2f}")
        record(f"{label}_english", english_score(text) >= cfg.quality.min_english_score,
               f"{english_score(text):.3f}")
        hits = meta_statement_hits(text)
        record(f"{label}_no_meta", not hits, ",".join(hits[:3]))
        record(f"{label}_content_overlap", content_overlap(text, base_text) >= cfg.variants.min_content_overlap,
               f"{content_overlap(text, base_text):.2f}")
        sents = split_sentences(text)
        uniq = {s.strip().lower() for s in sents}
        record(f"{label}_no_repetition",
               bool(sents) and 1 - len(uniq) / len(sents) <= cfg.quality.max_repeated_sentence_ratio)

    unsup_ratio = approx_tokens(variant_texts.get("UNSUPPORTED", "")) / base_tokens
    record(
        "unsupported_not_truncated",
        unsup_ratio >= cfg.quality.min_distractor_length_ratio,
        f"{unsup_ratio:.2f}",
    )
    record(
        "base_checksum_present",
        bool(base_text.strip()),
        "immutable base text is non-empty",
    )

    failures = [name for name, c in checks.items() if not c["ok"]]
    return {"ok": not failures, "checks": checks, "failures": failures}


def summarise_family_validation(
    results: dict[str, ValidationResult], hard: dict[str, Any]
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for label, res in results.items():
        if res.status != "PASS":
            reasons.extend([f"{label}:{f}" for f in (res.failures or ["validation_failed"])])
    if not hard.get("ok", False):
        reasons.extend([f"hard_check:{f}" for f in hard.get("failures", [])])
    return (not reasons), reasons


def evidence_spans_from_relations(text: str, relations: list[ClaimRelation]):
    spans = []
    for rel in relations:
        if not rel.evidence_span:
            continue
        span = resolve_quote(text, rel.evidence_sentence_id, rel.evidence_span)
        if span and span not in spans:
            spans.append(span)
    return spans
