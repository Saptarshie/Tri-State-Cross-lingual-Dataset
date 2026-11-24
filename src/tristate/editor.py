"""Coordinated counterfactual editing.

The editor sees the whole claim set, plans every patch before applying any, and works
through a bounded plan -> apply -> screen -> repair loop. It never mutates the base
passage, never rewrites the whole text by default, and cannot certify its own output
(validation is a separate module with a different model).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from .config import Config
from .errors import StageError
from .llm import LlmClient
from .patch import PatchError, apply_patches, coverage_gaps, describe_patches
from .schema import Claim, EditLog, Patch, SemanticRepresentation
from .spans import sentence_index
from .util import (
    approx_tokens,
    content_overlap,
    english_score,
    meta_statement_hits,
    sha256_text,
    split_sentences,
)

LABEL_OBJECTIVE = {
    "SUPPORTED": "every claim is established by the passage",
    "CONTRADICTED": "every claim is explicitly contradicted by the passage",
    "UNSUPPORTED": "every claim is neither established nor contradicted by the passage",
}

LABEL_INSTRUCTIONS = {
    "SUPPORTED": """\
Keep every claim's evidence intact. If the passage already establishes every claim, return
an empty patch list. You may make at most light neutral edits (paraphrase a clause, replace
a word with a synonym) that cannot weaken or strengthen any claim. Never remove a fact that
carries a claim.""",
    "CONTRADICTED": """\
For EACH claim, replace the specific fact that carries it with a plausible but incompatible
alternative of the same type: a different person, organisation, number, year, place,
category, or a reversed relation. Apply the SAME alternative to every sentence in the claim's
`mentions` list so the document stays internally consistent. Do not merely add "not" in front
of a clause; rewrite the clause so it reads naturally. Keep the sentence structure, register
and length. Never delete evidence, never soften, and never leave a mention stating the
original value.""",
    "UNSUPPORTED": """\
For EACH claim, remove or defuse the exact evidence that establishes it in EVERY sentence in
the claim's `mentions` list: delete the answer-bearing clause or replace it with related but
non-committing background. One untouched mention is enough to keep the claim established.
Do not replace the fact with a different value, do not negate it, and do not hint that the
information is missing. The result must stay on the same topic, keep its other facts, stay
grammatical, and stay within about 25% of the original length.""",
}

ALLOWED_BY_LABEL = {
    "SUPPORTED": {"NEUTRAL_REWRITE", "REPLACE_CLAUSE"},
    "CONTRADICTED": {
        "ENTITY_SUBSTITUTION", "NUMERICAL_MUTATION", "TEMPORAL_MUTATION",
        "RELATION_REVERSAL", "POLARITY_CHANGE", "CATEGORY_SUBSTITUTION", "REPLACE_CLAUSE",
    },
    "UNSUPPORTED": {"DELETE_SPAN", "NEUTRAL_REWRITE", "REPLACE_CLAUSE"},
}


class _EditPlanPayload(BaseModel):
    patches: list[Patch] = Field(default_factory=list)
    reasoning: str = ""


@dataclass
class EditOutcome:
    label: str
    text: str
    log: EditLog
    attempts: int
    pure_patch: bool = True
    history: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "text": self.text,
            "edit_log": self.log.model_dump(mode="json"),
            "attempts": self.attempts,
            "is_pure_patch": self.pure_patch,
            "history": self.history,
        }


def _structural_problems(
    text: str, base_text: str, label: str, cfg: Config
) -> list[str]:
    problems: list[str] = []
    tokens = approx_tokens(text)
    base_tokens = max(1, approx_tokens(base_text))
    ratio = tokens / base_tokens
    long_doc = base_tokens >= cfg.variants.long_document_tokens
    lo = cfg.variants.min_length_ratio_long if long_doc else cfg.variants.min_length_ratio
    hi = cfg.variants.max_length_ratio_long if long_doc else cfg.variants.max_length_ratio
    if ratio < lo:
        problems.append(f"too short after editing ({ratio:.2f} of base)")
    if ratio > hi:
        problems.append(f"too long after editing ({ratio:.2f} of base)")
    if english_score(text) < cfg.quality.min_english_score:
        problems.append("non-English characters introduced")
    hits = meta_statement_hits(text)
    if hits and cfg.quality.forbid_meta_statements:
        problems.append(f"label/task meta-language: {hits[:3]}")
    if content_overlap(text, base_text) < cfg.variants.min_content_overlap:
        problems.append("edit changed too much of the passage")
    if len(split_sentences(text)) < 1:
        problems.append("no sentences after editing")
    if label == "UNSUPPORTED" and ratio < cfg.quality.min_distractor_length_ratio:
        problems.append("unsupported variant is an obvious truncation")
    return problems


_MENTION_STOP = {
    "the", "a", "an", "and", "or", "but", "of", "in", "on", "at", "to", "for", "from", "with",
    "by", "as", "is", "are", "was", "were", "be", "been", "being", "that", "this", "these",
    "those", "it", "its", "their", "his", "her", "they", "them", "we", "our", "you", "your",
    "has", "have", "had", "does", "did", "do", "not", "no", "than", "then", "which", "who",
    "when", "where", "while", "into", "over", "under", "about", "after", "before", "during",
    "more", "most", "less", "least", "same", "such", "also", "only", "very", "can", "could",
    "would", "should", "may", "might", "must", "will", "shall", "up", "down", "out", "per",
}


def _claim_terms(claim_text: str) -> tuple[list[str], list[str]]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'\-]+|\d+(?:[.,]\d+)*", claim_text.lower())
    terms = [w for w in words if w not in _MENTION_STOP and len(w) >= 4]
    numbers = re.findall(r"\d+(?:[.,]\d+)*", claim_text)
    return terms, numbers


def claim_mentions(base_text: str, claim: Claim, limit: int = 8) -> list[dict[str, Any]]:
    """Sentences that could establish or contradict a claim.

    A long document restates key facts in several sections. Editing only the evidence sentence
    leaves another mention intact, which makes CONTRADICTED read as self-contradictory
    (UNCERTAIN) and UNSUPPORTED still entailed. The planner therefore receives every plausible
    mention and must cover all of them.
    """
    refs = sentence_index(base_text)
    terms, numbers = _claim_terms(claim.claim_text)
    evidence = {s.sentence_id for s in claim.evidence_spans}
    if not terms:
        return [{"sentence_id": r.sentence_id, "text": r.text, "evidence": r.sentence_id in evidence}
                for r in refs if r.sentence_id in evidence]
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for i, ref in enumerate(refs):
        low = ref.text.lower()
        hits = [t for t in terms if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low)]
        score = len(hits) / len(terms)
        num_hit = any(
            re.search(rf"(?<![\d.]){re.escape(n)}(?![\d.])", ref.text) for n in numbers
        )
        is_evidence = ref.sentence_id in evidence
        if is_evidence or score >= 0.34 or (num_hit and score >= 0.2):
            scored.append(
                (
                    1.0 if is_evidence else score,
                    i,
                    {
                        "sentence_id": ref.sentence_id,
                        "text": ref.text,
                        "evidence": is_evidence,
                        "required": bool(is_evidence or score >= 0.5 or (num_hit and score >= 0.3)),
                        "matched_terms": hits[:8],
                    },
                )
            )
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [row for _, _, row in scored[:limit]]


def editing_view(base_text: str, claims: list[Claim], cfg: Config) -> list[dict]:
    """Sentences the editor needs: claim evidence plus a local neighbourhood.

    Long documents are not sent whole. Patch targets are still global sentence IDs, and the
    patch engine applies against the full base text.
    """
    refs = sentence_index(base_text)
    max_view = cfg.variants.edit_view_max_sentences
    if len(refs) <= max_view and approx_tokens(base_text) < cfg.variants.long_document_tokens:
        return [{"sentence_id": r.sentence_id, "text": r.text, "chars": [r.start_char, r.end_char]} for r in refs]

    indexes: set[int] = set()
    evidence_ids = {s.sentence_id for c in claims for s in c.evidence_spans}
    mention_ids = {m["sentence_id"] for c in claims for m in claim_mentions(base_text, c)}
    wanted = evidence_ids | mention_ids
    neighbours = max(0, cfg.variants.edit_view_sentences)
    for i, ref in enumerate(refs):
        if ref.sentence_id in evidence_ids:
            indexes.update(range(max(0, i - neighbours), min(len(refs), i + neighbours + 1)))
        elif ref.sentence_id in wanted:
            indexes.add(i)

    if len(indexes) > max_view:
        # keep evidence sentences first, then fill with neighbours by proximity
        keep = sorted(i for i, r in enumerate(refs) if r.sentence_id in evidence_ids)[:max_view]
        for i in sorted(indexes, key=lambda idx: (idx not in keep, idx)):
            if len(keep) >= max_view:
                break
            if i not in keep:
                keep.append(i)
        indexes = set(keep)
    if not indexes:
        indexes = set(range(min(max_view, len(refs))))

    return [
        {"sentence_id": refs[i].sentence_id, "text": refs[i].text, "chars": [refs[i].start_char, refs[i].end_char]}
        for i in sorted(indexes)
    ]


def create_variant(
    llm: LlmClient,
    cfg: Config,
    label: str,
    base_text: str,
    claims: list[Claim],
    semantic: SemanticRepresentation,
    candidate_id: str | None = None,
    prior_feedback: str = "",
    attempts_budget: int | None = None,
) -> EditOutcome:
    if label not in LABEL_OBJECTIVE:
        raise StageError("bad_label", f"unknown label {label}")
    max_attempts = 1 + max(0, cfg.variants.max_edit_repair_attempts)
    if attempts_budget is not None:
        max_attempts = max(1, attempts_budget)
    claim_ids = [c.claim_id for c in claims]
    claim_payload = [
        {
            "claim_id": c.claim_id,
            "claim_text": c.claim_text,
            "evidence": [s.text for s in c.evidence_spans],
            "mentions": claim_mentions(base_text, c),
        }
        for c in claims
    ]
    feedback = prior_feedback or ""
    history: list[dict[str, Any]] = []
    allowed_ops = ", ".join(sorted(ALLOWED_BY_LABEL[label]))

    for attempt in range(1, max_attempts + 1):
        result = llm.structured(
            "edit_plan",
            {
                "label": label,
                "label_objective": LABEL_OBJECTIVE[label],
                "sentences_json": json.dumps(editing_view(base_text, claims, cfg), indent=2),
                "claims_json": json.dumps(claim_payload, indent=2),
                "feedback": feedback or "(none)",
                "allowed_operations": allowed_ops,
                "label_instructions": LABEL_INSTRUCTIONS[label],
            },
            _EditPlanPayload,
            cfg.llm.editor,
            stage=f"variant_{label}",
            candidate_id=candidate_id,
        )
        patches = result.data.patches
        history.append(
            {
                "attempt": attempt,
                "reasoning": result.data.reasoning,
                "patches": [p.model_dump(mode="json") for p in patches],
                "plan_ref": result.raw_ref,
            }
        )

        if label == "SUPPORTED" and not patches:
            log = EditLog(
                entries=[],
                is_pure_patch=True,
                base_checksum=sha256_text(base_text),
                result_checksum=sha256_text(base_text),
                unified_diff="",
                attempts=attempt,
                notes=["unmodified_base"],
            )
            return EditOutcome(label=label, text=base_text, log=log, attempts=attempt, history=history)

        if not patches:
            feedback = "You returned no patches. Every claim must be addressed with at least one patch."
            continue

        unknown = [p for p in patches if not set(p.affected_claim_ids).issubset(set(claim_ids))]
        if unknown:
            unknown_ids = sorted({c for p in unknown for c in p.affected_claim_ids if c not in claim_ids})
            feedback = (
                f"These claim IDs do not exist: {unknown_ids}. Valid IDs are {claim_ids}. "
                "Fix affected_claim_ids and try again."
            )
            continue
        gaps = coverage_gaps(patches, claim_ids)
        if gaps:
            feedback = (
                f"Your plan does not address these claims: {gaps}. Add at least one patch per "
                "claim and re-plan the whole set."
            )
            continue

        disallowed = [p.operation for p in patches if p.operation not in ALLOWED_BY_LABEL[label]]
        if disallowed:
            feedback = (
                f"Operations {sorted(set(disallowed))} are not allowed for {label}. "
                f"Allowed: {sorted(ALLOWED_BY_LABEL[label])}."
            )
            continue

        if label != "SUPPORTED":
            # every restatement must move to the same target relation; one untouched mention
            # leaves the document self-contradictory (UNCERTAIN) or still entailed
            missing_mentions: dict[str, list[str]] = {}
            for c in claims:
                needed = {m["sentence_id"] for m in claim_mentions(base_text, c)}
                covered = {p.target_sentence_id for p in patches if c.claim_id in p.affected_claim_ids}
                absent = sorted(needed - covered)
                if absent:
                    missing_mentions[c.claim_id] = absent
            if missing_mentions:
                detail = "; ".join(f"{cid}: {ids}" for cid, ids in missing_mentions.items())
                feedback = (
                    f"These sentences also state the claim's facts and were not edited: {detail}. "
                    "Edit EVERY mention so they all express the same target relation; leaving one "
                    "original mention makes the document self-contradictory and it will be rejected."
                )
                continue

        try:
            applied = apply_patches(base_text, patches)
        except PatchError as exc:
            feedback = (
                f"A patch could not be applied ({exc.code}): {exc}. "
                "Copy original_text verbatim from the numbered sentences, keep it inside one "
                "sentence, and make sure it occurs exactly once."
            )
            continue

        problems = _structural_problems(applied.text, base_text, label, cfg)
        if problems:
            feedback = "The edited passage was rejected: " + "; ".join(problems) + ". Revise the patches."
            continue

        applied.log.attempts = attempt
        return EditOutcome(
            label=label,
            text=applied.text,
            log=applied.log,
            attempts=attempt,
            history=history,
        )

    raise StageError(
        "edit_failed",
        f"could not produce a valid {label} variant in {max_attempts} attempt(s)",
        {
            "label": label,
            "last_feedback": feedback,
            "history": history,
            "patch_summary": describe_patches(
                [Patch.model_validate(p) for h in history for p in h.get("patches", [])]
            ),
        },
    )
