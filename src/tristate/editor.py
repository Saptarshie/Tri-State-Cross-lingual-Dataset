"""Coordinated counterfactual editing.

The editor sees the whole claim set, plans every patch before applying any, and works
through a bounded plan -> apply -> screen -> repair loop. It never mutates the base
passage, never rewrites the whole text by default, and cannot certify its own output
(validation is a separate module with a different model).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from .config import Config
from .errors import StageError
from .llm import LlmClient
from .patch import PatchError, apply_patches, coverage_gaps, describe_patches
from .schema import Claim, EditLog, Patch, SemanticRepresentation
from .spans import sentences_for_prompt
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
category, or a reversed relation. Do not merely add "not" in front of a clause; rewrite the
clause so it reads naturally. Keep the sentence structure, register and length. Never delete
evidence, never soften, and never leave any claim still established elsewhere.""",
    "UNSUPPORTED": """\
For EACH claim, remove or defuse the exact evidence that establishes it: delete the
answer-bearing clause or replace it with related but non-committing background. You must
ALSO check the rest of the passage for another place that still states the claim, and remove
that too if present. Do not replace the fact with a different value, do not negate it, and do
not hint that the information is missing. The result must stay on the same topic, keep its
other facts, stay grammatical, and stay within about 25% of the original length.""",
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
    if ratio < cfg.variants.min_length_ratio:
        problems.append(f"too short after editing ({ratio:.2f} of base)")
    if ratio > cfg.variants.max_length_ratio:
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
                "sentences_json": json.dumps(sentences_for_prompt(base_text), indent=2),
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
