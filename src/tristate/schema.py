"""Canonical data models.

The family object is the indivisible unit of generation, validation, storage and
splitting. These models are the schema of record; LLM-facing payloads are parsed
into them (or rejected) before anything is persisted.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ids import LABEL_TO_CODE
from .util import approx_tokens, normalize_ws, sha256_text, split_sentences, utcnow

Label = Literal["SUPPORTED", "CONTRADICTED", "UNSUPPORTED"]
Relation = Literal["ENTAILED", "CONTRADICTED", "NEUTRAL", "UNCERTAIN"]
Status = Literal["ACCEPTED", "QUARANTINED", "REJECTED", "PENDING"]

LABELS: tuple[str, ...] = ("SUPPORTED", "CONTRADICTED", "UNSUPPORTED")

EXPECTED_RELATION: dict[str, str] = {
    "SUPPORTED": "ENTAILED",
    "CONTRADICTED": "CONTRADICTED",
    "UNSUPPORTED": "NEUTRAL",
}

ALLOWED_OPS = (
    "ENTITY_SUBSTITUTION",
    "NUMERICAL_MUTATION",
    "TEMPORAL_MUTATION",
    "RELATION_REVERSAL",
    "POLARITY_CHANGE",
    "CATEGORY_SUBSTITUTION",
    "DELETE_SPAN",
    "REPLACE_CLAUSE",
    "NEUTRAL_REWRITE",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LlmModel(BaseModel):
    """Permissive base for model output; extra keys are ignored, not fatal."""

    model_config = ConfigDict(extra="ignore")


# --------------------------------------------------------------------------- #
# Spans and facts
# --------------------------------------------------------------------------- #


class Span(StrictModel):
    sentence_id: str
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    text: str

    @model_validator(mode="after")
    def _order(self) -> "Span":
        if self.end_char <= self.start_char:
            raise ValueError("span end_char must be > start_char")
        return self


class SentenceRef(StrictModel):
    sentence_id: str
    start_char: int
    end_char: int
    text: str


class Entity(LlmModel):
    name: str
    entity_type: str = "OTHER"


class Fact(LlmModel):
    fact_id: str
    subject: str
    predicate: str
    object: str
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    source_spans: list[Span] = Field(default_factory=list)
    confidence: float = 0.8
    section_id: str | None = None

    @property
    def triple(self) -> tuple[str, str, str]:
        return normalize_triple(self.subject, self.predicate, self.object)


def normalize_entity(x: str) -> str:
    t = normalize_ws(x).lower()
    for prefix in ("the ", "a ", "an "):
        if t.startswith(prefix):
            t = t[len(prefix):]
    return t.strip(" .,;:'\"")


def normalize_predicate(x: str) -> str:
    t = normalize_entity(x).replace(" ", "_").replace("-", "_")
    return t


def normalize_triple(subject: str, predicate: str, obj: str) -> tuple[str, str, str]:
    return (normalize_entity(subject), normalize_predicate(predicate), normalize_entity(obj))


class SemanticRepresentation(StrictModel):
    summary: str
    entities: list[Entity] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    graph_version: str = "v1"
    topic_hint: str | None = None

    def fact_by_id(self, fact_id: str) -> Fact | None:
        for f in self.facts:
            if f.fact_id == fact_id:
                return f
        return None

    def triples(self) -> set[tuple[str, str, str]]:
        return {f.triple for f in self.facts}


# --------------------------------------------------------------------------- #
# Blueprint
# --------------------------------------------------------------------------- #


class Blueprint(LlmModel):
    blueprint_id: str
    topic_path: list[str]
    main_concept: str
    subtopics: list[str] = Field(default_factory=list)
    planned_entity_types: list[str] = Field(default_factory=list)
    planned_relation_types: list[str] = Field(default_factory=list)
    planned_fact_types: list[str] = Field(default_factory=list)
    genre: str = "encyclopedia_entry"
    tone: str = "neutral_explanatory"
    structure: str = "paragraph"
    complexity: str = "intermediate"
    target_fact_count: int = 4
    target_length_tokens: list[int] = Field(default_factory=lambda: [2000, 4000])
    target_sections: int = 4
    novelty_report: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow)

    @property
    def semantic_text(self) -> str:
        return " | ".join(
            [
                " > ".join(self.topic_path),
                self.main_concept,
                ", ".join(self.subtopics),
                "relations: " + ", ".join(self.planned_relation_types),
                "facts: " + ", ".join(self.planned_fact_types),
                self.genre,
                self.complexity,
            ]
        )


# --------------------------------------------------------------------------- #
# Document plan (long-form base artifact)
# --------------------------------------------------------------------------- #


class SectionPlan(LlmModel):
    section_id: str
    title: str
    purpose: str
    target_tokens: int
    key_points: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)


class DocumentPlan(LlmModel):
    plan_id: str = ""
    throughline: str = ""
    sections: list[SectionPlan] = Field(default_factory=list)
    total_target_tokens: int = 0
    created_at: str = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _sections(self) -> "DocumentPlan":
        ids = [s.section_id for s in self.sections]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate section ids in document plan")
        if not self.total_target_tokens:
            self.total_target_tokens = sum(s.target_tokens for s in self.sections)
        return self


class PassageSection(StrictModel):
    section_id: str
    title: str = ""
    start_char: int
    end_char: int
    token_count: int
    checksum: str = ""


# --------------------------------------------------------------------------- #
# Claims
# --------------------------------------------------------------------------- #


class Claim(LlmModel):
    claim_id: str
    claim_text: str
    fact_ids: list[str] = Field(default_factory=list)
    evidence_spans: list[Span] = Field(default_factory=list)
    claim_type: str = "ENTITY_RELATION"
    difficulty: str = "medium"
    intent: str = "what"
    section_ids: list[str] = Field(default_factory=list)

    @field_validator("claim_text")
    @classmethod
    def _single_sentence(cls, v: str) -> str:
        v = normalize_ws(v)
        if not v.endswith((".", "?", "!")):
            v = v + "."
        return v


# --------------------------------------------------------------------------- #
# Editing
# --------------------------------------------------------------------------- #


class Patch(LlmModel):
    operation: str
    target_sentence_id: str | None = None
    original_text: str
    replacement_text: str = ""
    affected_claim_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    preserve_surrounding_context: bool = True

    @field_validator("operation")
    @classmethod
    def _op(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in ALLOWED_OPS:
            raise ValueError(f"unsupported edit operation: {v}")
        return v


class AppliedPatch(StrictModel):
    operation: str
    target_sentence_id: str | None
    original_text: str
    replacement_text: str
    affected_claim_ids: list[str]
    reason: str
    start_char: int
    end_char: int
    matched_exactly: bool = True
    after_text: str


class EditLog(StrictModel):
    entries: list[AppliedPatch] = Field(default_factory=list)
    is_pure_patch: bool = True
    base_checksum: str
    result_checksum: str
    unified_diff: str = ""
    attempts: int = 0
    notes: list[str] = Field(default_factory=list)

    @property
    def operations(self) -> list[str]:
        return [e.operation for e in self.entries]

    def coverage(self) -> set[str]:
        out: set[str] = set()
        for e in self.entries:
            out.update(e.affected_claim_ids)
        return out


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


class ClaimRelation(LlmModel):
    claim_id: str
    relation: str
    confidence: float = 0.0
    evidence_span: str | None = None
    evidence_sentence_id: str | None = None
    rationale: str | None = None
    source: str = "validator"

    @field_validator("relation")
    @classmethod
    def _rel(cls, v: str) -> str:
        v = (v or "").strip().upper()
        aliases = {
            "ENTAILMENT": "ENTAILED",
            "SUPPORTED": "ENTAILED",
            "SUPPORTS": "ENTAILED",
            "CONTRADICTION": "CONTRADICTED",
            "CONTRADICTS": "CONTRADICTED",
            "REFUTED": "CONTRADICTED",
            "NOT_ENTAILED": "NEUTRAL",
            "UNSUPPORTED": "NEUTRAL",
            "UNKNOWN": "UNCERTAIN",
            "AMBIGUOUS": "UNCERTAIN",
        }
        v = aliases.get(v, v)
        if v not in ("ENTAILED", "CONTRADICTED", "NEUTRAL", "UNCERTAIN"):
            raise ValueError(f"invalid relation: {v}")
        return v


class ValidationResult(StrictModel):
    variant_label: str
    status: Literal["PASS", "FAIL", "UNCERTAIN"]
    relations: list[ClaimRelation] = Field(default_factory=list)
    hard_checks: dict[str, Any] = Field(default_factory=dict)
    failures: list[str] = Field(default_factory=list)
    validator_model: str = ""
    prompt_version: str = ""
    second_validator_model: str | None = None
    second_relations: list[ClaimRelation] = Field(default_factory=list)
    agreement: float | None = None
    raw_ref: str | None = None
    created_at: str = Field(default_factory=utcnow)

    def relation_map(self) -> dict[str, str]:
        return {r.claim_id: r.relation for r in self.relations}

    def observed_label(self) -> str | None:
        """Map the observed relation vector to a label, or None if mixed."""
        rels = set(self.relation_map().values())
        if rels == {"ENTAILED"}:
            return "SUPPORTED"
        if rels == {"CONTRADICTED"}:
            return "CONTRADICTED"
        if rels == {"NEUTRAL"}:
            return "UNSUPPORTED"
        return None


# --------------------------------------------------------------------------- #
# Passages and variants
# --------------------------------------------------------------------------- #


class PassageRecord(StrictModel):
    passage_id: str
    document_id: str | None = None
    document_plan_id: str | None = None
    text: str
    genre: str
    tone: str
    structure: str
    complexity: str = "intermediate"
    token_count: int = 0
    sentence_count: int = 0
    checksum: str = ""
    source_type: str = "synthetic"
    sections: list[PassageSection] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fill(self) -> "PassageRecord":
        if not self.token_count:
            self.token_count = approx_tokens(self.text)
        if not self.sentence_count:
            self.sentence_count = len(split_sentences(self.text))
        if not self.checksum:
            self.checksum = sha256_text(self.text)
        return self


class Variant(StrictModel):
    variant_id: str
    label: Label
    text: str
    token_count: int
    checksum: str
    edit_history: EditLog
    is_pure_patch: bool = True
    relations_by_claim: list[ClaimRelation] = Field(default_factory=list)
    evidence_spans: list[Span] = Field(default_factory=list)
    contradiction_spans: list[Span] = Field(default_factory=list)
    validation: ValidationResult | None = None
    semantic_representation: SemanticRepresentation | None = None
    graph_diff: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _counts(self) -> "Variant":
        if not self.token_count:
            self.token_count = approx_tokens(self.text)
        if not self.checksum:
            self.checksum = sha256_text(self.text)
        return self


# --------------------------------------------------------------------------- #
# Family
# --------------------------------------------------------------------------- #


class SourceRef(StrictModel):
    source_type: str = "synthetic"
    document_id: str | None = None
    source_url: str | None = None
    publisher: str | None = None
    published_at: str | None = None
    retrieved_at: str | None = None
    license_or_usage_notes: str | None = None


class TopicRef(StrictModel):
    topic_ids: list[str] = Field(default_factory=list)
    topic_path: list[str] = Field(default_factory=list)


class GenerationMeta(StrictModel):
    planner_model: str = ""
    passage_generator_model: str = ""
    claim_generator_model: str = ""
    editor_model: str = ""
    extractor_model: str = ""
    validator_model: str = ""
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    config_hash: str = ""
    seed: int | None = None
    run_id: str = ""
    created_at: str = Field(default_factory=utcnow)
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    attempt_count: int = 1


class Quality(StrictModel):
    status: Status = "PENDING"
    hard_checks_passed: bool = False
    human_verified: bool = False
    rejection_reasons: list[str] = Field(default_factory=list)
    scores: dict[str, Any] = Field(default_factory=dict)
    audit_flags: list[str] = Field(default_factory=list)
    novelty: dict[str, Any] = Field(default_factory=dict)


class Family(StrictModel):
    family_id: str
    split_group_id: str
    language: str = "en"
    script: str = "Latin"
    locale: str = "en_US"
    language_generation_method: str = "native_generation"
    source: SourceRef = Field(default_factory=SourceRef)
    topic: TopicRef = Field(default_factory=TopicRef)
    blueprint: Blueprint
    base_passage: PassageRecord
    semantic_representation: SemanticRepresentation
    claim_set: list[Claim]
    variants: dict[str, Variant]
    generation: GenerationMeta = Field(default_factory=GenerationMeta)
    quality: Quality = Field(default_factory=Quality)
    split: str = "unassigned"
    dataset_version: str = "0.1.0"
    idempotency_key: str = ""
    created_at: str = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _invariants(self) -> "Family":
        labels = tuple(self.variants.keys())
        if set(labels) != set(LABELS) or len(labels) != 3:
            raise ValueError(f"family must contain exactly the three labels, got {labels}")
        claim_ids = [c.claim_id for c in self.claim_set]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("duplicate claim ids inside family")
        if not (1 <= len(self.claim_set) <= 8):
            raise ValueError("claim set size out of bounds")
        for label, v in self.variants.items():
            if v.label != label:
                raise ValueError(f"variant under {label} declares label {v.label}")
            if v.validation and v.validation.variant_label != label:
                raise ValueError(f"validation label mismatch for {label}")
        if len({v.checksum for v in self.variants.values()}) < 3 and self.quality.status == "ACCEPTED":
            raise ValueError("accepted family must have three distinct variant texts")
        return self

    @property
    def claim_ids(self) -> list[str]:
        return [c.claim_id for c in self.claim_set]

    def variant(self, label: str) -> Variant:
        return self.variants[label]

    def flattened_rows(self) -> list[dict[str, Any]]:
        rows = []
        for label in LABELS:
            v = self.variants[label]
            rows.append(
                {
                    "family_id": self.family_id,
                    "split_group_id": self.split_group_id,
                    "split": self.split,
                    "language": self.language,
                    "label": label,
                    "variant_id": v.variant_id,
                    "passage": v.text,
                    "claim_set": [c.model_dump(mode="json") for c in self.claim_set],
                    "claim_ids": self.claim_ids,
                    "topic_path": self.topic.topic_path,
                    "genre": self.base_passage.genre,
                    "tone": self.base_passage.tone,
                    "structure": self.base_passage.structure,
                    "complexity": self.base_passage.complexity,
                    "token_count": v.token_count,
                    "source_type": self.source.source_type,
                    "is_pure_patch": v.is_pure_patch,
                    "edit_operations": v.edit_history.operations,
                    "human_verified": self.quality.human_verified,
                    "dataset_version": self.dataset_version,
                }
            )
        return rows


# --------------------------------------------------------------------------- #
# Candidate / work artefacts (pre-acceptance)
# --------------------------------------------------------------------------- #


class BlueprintCandidate(StrictModel):
    candidate_id: str
    idempotency_key: str
    topic_ids: list[str]
    topic_path: list[str]
    parent_topic_ids: list[str] = Field(default_factory=list)
    source_type: str = "synthetic"
    document_id: str | None = None
    seed_intent: str = ""
    created_at: str = Field(default_factory=utcnow)


class ExtractionPayload(LlmModel):
    """Raw shape returned by the extraction prompt."""

    summary: str
    entities: list[dict[str, Any]] = Field(default_factory=list)
    facts: list[dict[str, Any]] = Field(default_factory=list)
    topic_hint: str | None = None


class ClaimDraft(LlmModel):
    claim_text: str
    fact_ids: list[str] = Field(default_factory=list)
    claim_type: str = "ENTITY_RELATION"
    difficulty: str = "medium"
    intent: str = "what"


class EditPlan(LlmModel):
    patches: list[Patch] = Field(default_factory=list)
    reasoning: str = ""
    needs_rewrite: bool = False
    rewrite_sentence_ids: list[str] = Field(default_factory=list)


class ValidationPayload(LlmModel):
    claim_relations: list[dict[str, Any]] = Field(default_factory=list)


def variant_checksum(variant: Variant) -> str:
    return sha256_text(normalize_ws(variant.text))


def label_code(label: str) -> str:
    return LABEL_TO_CODE[label]
