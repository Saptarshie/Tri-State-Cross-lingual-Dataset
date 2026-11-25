"""Bounded ReAct-style quality fixer for translated windows.

The fixer is deliberately not a free-form prose rewriter.  It may inspect the
window, its ledger/glossary and adjacent context, and it may replace *existing*
sentence ids.  It cannot insert, delete, change the source, change labels, or
certify its own output.  Every action is recorded as a structured trace.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Literal

from ..schema import StrictModel
from .models import GlossaryEntry, TargetClaim, ClaimSemanticCard, WindowReview


class FixerEdit(StrictModel):
    sentence_id: str
    target_text: str
    reason: str = ""


class FixerAction(StrictModel):
    thought: str = ""
    action: Literal[
        "read_window",
        "read_neighbor_target",
        "read_claim_ledger",
        "read_glossary",
        "apply_sentence_edits",
        "run_review",
        "rollback",
        "finish",
        "abort",
    ]
    edits: list[FixerEdit] = []
    sentence_ids: list[str] = []
    direction: Literal["previous", "next"] | None = None
    reason: str = ""


@dataclass
class FixerResult:
    accepted: bool
    target: dict[str, str]
    review: WindowReview | None
    trace: list[dict]
    error: str = ""


class QualityFixer:
    def __init__(
        self,
        client,
        *,
        profile: object,
        source_by_id: dict[str, str],
        target: dict[str, str],
        review: WindowReview,
        review_fn: Callable[[dict[str, str]], WindowReview],
        target_claims: list[TargetClaim],
        cards: list[ClaimSemanticCard],
        glossary: list[GlossaryEntry],
        prev_context: str = "",
        next_context: str = "",
        neighbor_targets: dict[str, str] | None = None,
        max_steps: int = 8,
        max_edits_per_step: int = 2,
        max_total_edits: int = 6,
        stage: str = "fix_window",
        family_id: str | None = None,
    ):
        self.client = client
        self.profile = profile
        self.source_by_id = source_by_id
        self.target = dict(target)
        self.review = review
        self.review_fn = review_fn
        self.target_claims = target_claims
        self.cards = cards
        self.glossary = glossary
        self.prev_context = prev_context
        self.next_context = next_context
        self.neighbor_targets = neighbor_targets or {}
        self.max_steps = max(1, max_steps)
        self.max_edits_per_step = max(1, max_edits_per_step)
        self.max_total_edits = max(1, max_total_edits)
        self.stage = stage
        self.family_id = family_id
        self.trace: list[dict] = []
        self._snapshots: list[dict[str, str]] = []
        self._total_edits = 0

    def run(self) -> FixerResult:
        if self.review.verdict == "PASS":
            return FixerResult(True, self.target, self.review, self.trace)
        model = self.client.cfg.llm.validator
        for step in range(1, self.max_steps + 1):
            action: FixerAction = self.client.structured(
                "multilingual_fixer",
                {
                    "profile_json": _json(self.profile.model_dump(mode="json")),
                    "source_sentences_json": _json(
                        [{"sentence_id": sid, "text": self.source_by_id[sid]} for sid in self.target]
                    ),
                    "current_target_json": _json(
                        [{"sentence_id": sid, "target_text": self.target[sid]} for sid in self.target]
                    ),
                    "latest_review_json": _json(self.review.model_dump(mode="json")),
                    "claim_cards_json": _json([c.model_dump(mode="json") for c in self.cards]),
                    "target_claims_json": _json([t.model_dump(mode="json") for t in self.target_claims]),
                    "glossary_json": _json([g.model_dump(mode="json") for g in self.glossary]),
                    "prev_context": self.prev_context,
                    "next_context": self.next_context,
                    "trace_json": _json(self.trace[-6:]),
                    "max_steps": self.max_steps,
                    "max_edits_per_step": self.max_edits_per_step,
                    "max_total_edits": self.max_total_edits,
                    "step": step,
                },
                FixerAction,
                model,
                stage=self.stage,
                family_id=self.family_id,
            ).data
            self.trace.append(
                {
                    "step": step,
                    "action": action.action,
                    "sentence_ids": action.sentence_ids,
                    "edits": [e.model_dump(mode="json") for e in action.edits],
                    "reason": action.reason or action.thought,
                }
            )
            if action.action == "abort":
                return FixerResult(False, self.target, self.review, self.trace, action.reason or "fixer aborted")
            if action.action == "read_window":
                self.trace[-1]["observation"] = {
                    "source": self.source_by_id,
                    "target": self.target,
                    "review": self.review.model_dump(mode="json"),
                }
                continue
            if action.action == "read_neighbor_target":
                # Neighbor targets are optional: during concurrent window
                # generation they may not exist yet.  The source contexts remain
                # available in the next prompt.
                self.trace[-1]["observation"] = {
                    "direction": action.direction,
                    "target": {
                        sid: text for sid, text in self.neighbor_targets.items()
                    },
                    "source_context": self.prev_context if action.direction == "previous" else self.next_context,
                }
                continue
            if action.action == "read_claim_ledger":
                self.trace[-1]["observation"] = [c.model_dump(mode="json") for c in self.cards]
                continue
            if action.action == "read_glossary":
                self.trace[-1]["observation"] = [g.model_dump(mode="json") for g in self.glossary]
                continue
            if action.action == "rollback":
                if self._snapshots:
                    self.target = self._snapshots.pop()
                continue
            if action.action == "apply_sentence_edits":
                error = self._apply(action.edits)
                if error:
                    self.trace[-1]["rejected"] = error
                continue
            if action.action == "run_review":
                self.review = self.review_fn(self.target)
                self.trace[-1]["review_verdict"] = self.review.verdict
                if self.review.verdict == "PASS":
                    return FixerResult(True, self.target, self.review, self.trace)
                if self.review.verdict == "QUARANTINE":
                    return FixerResult(
                        False,
                        self.target,
                        self.review,
                        self.trace,
                        self.review.feedback or "review quarantined",
                    )
                continue
            if action.action == "finish":
                if self.review.verdict == "PASS":
                    return FixerResult(True, self.target, self.review, self.trace)
                return FixerResult(False, self.target, self.review, self.trace, "finish without a passing review")
        return FixerResult(False, self.target, self.review, self.trace, f"step budget exhausted ({self.max_steps})")

    def _apply(self, edits: list[FixerEdit]) -> str:
        if not edits:
            return "no edits supplied"
        if len(edits) > self.max_edits_per_step:
            return f"too many edits in one step: {len(edits)} > {self.max_edits_per_step}"
        if self._total_edits + len(edits) > self.max_total_edits:
            return f"total edit budget exhausted: {self._total_edits + len(edits)} > {self.max_total_edits}"
        ids = [e.sentence_id for e in edits]
        if len(ids) != len(set(ids)):
            return "duplicate sentence ids in edit set"
        unknown = [sid for sid in ids if sid not in self.target]
        if unknown:
            return f"unknown sentence ids: {unknown}"
        empty = [e.sentence_id for e in edits if not e.target_text.strip()]
        if empty:
            return f"empty target text for: {empty}"
        self._snapshots.append(dict(self.target))
        for edit in edits:
            self.target[edit.sentence_id] = edit.target_text.strip()
        self._total_edits += len(edits)
        return ""


def _json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
