"""Strict records for the multilingual (translation) branch.

These records are deliberately separate from the English ``Family`` record.
A translation family inherits only immutable identifiers from its source:
``family_id``, ``split`` and ``split_group_id``.  Everything language-specific
is materialised here so a failed translation can never rewrite the source.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..schema import StrictModel

Relation = Literal["SUPPORTED", "CONTRADICTED", "UNSUPPORTED"]
ReviewVerdict = Literal["PASS", "REPAIR", "QUARANTINE"]


class TargetProfile(StrictModel):
    """A target-language variety and its approved surface policy."""

    profile_id: str
    base_language: str
    locale: str
    display_name: str
    script_policy: Literal["native", "romanized", "mixed"]
    primary_script: Literal["Bengali", "Latin", "Mixed"]
    sentence_syntax: str
    code_switching: bool = False
    code_switching_intensity: Literal["none", "light", "moderate"] = "none"
    register_style: str = "neutral"
    regional_style: str = "standard"
    romanization_policy: str = "not applicable"
    number_policy: str = "preserve source numerals"
    proper_noun_policy: str = "transliterate consistently; keep the English form on first mention"
    english_term_policy: str = "use the conventional target-language term; keep the English term in parentheses on first mention when it is a technical term"
    version: str = "1.0.0"


class ClaimSemanticCard(StrictModel):
    """The meaning that must survive translation, independent of wording."""

    claim_id: str
    source_text: str
    subject: str = ""
    predicate: str = ""
    object: str = ""
    relation_obligation: Relation
    modifiers: list[str] = Field(default_factory=list)
    numbers: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    negation: bool = False
    modality: str = "asserted"
    polarity: Literal["positive", "negative", "unknown"] = "positive"
    critical_distinctions: list[str] = Field(default_factory=list)
    allowed_paraphrase: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)
    source_fact_ids: list[str] = Field(default_factory=list)


class TargetClaim(StrictModel):
    claim_id: str
    source_text: str
    target_text: str
    relation_obligation: Relation
    preserved_terms: list[str] = Field(default_factory=list)
    review_status: Literal["PASS", "FAIL"] = "PASS"
    review_note: str = ""
    repair_attempts: int = 0


class GlossaryEntry(StrictModel):
    source_term: str
    target_term: str
    kind: Literal["entity", "technical", "ordinary", "number"] = "ordinary"
    note: str = ""


class SentenceTranslation(StrictModel):
    sentence_id: str
    paragraph_id: int = 0
    source_text: str
    target_text: str


class WindowReview(StrictModel):
    window_id: str
    verdict: ReviewVerdict
    affected_sentence_ids: list[str] = Field(default_factory=list)
    missing_sentence_ids: list[str] = Field(default_factory=list)
    added_content: list[str] = Field(default_factory=list)
    meaning_errors: list[str] = Field(default_factory=list)
    style_errors: list[str] = Field(default_factory=list)
    feedback: str = ""


class ClaimFinding(StrictModel):
    claim_id: str
    observed_relation: Literal["ENTAILED", "CONTRADICTED", "NEUTRAL", "UNCERTAIN"]
    evidence_sentence_ids: list[str] = Field(default_factory=list)
    evidence_text: str = ""
    note: str = ""
    expected_relation: Relation


class VariantReview(StrictModel):
    variant_label: Relation
    verdict: ReviewVerdict
    findings: list[ClaimFinding] = Field(default_factory=list)
    faithfulness_notes: list[str] = Field(default_factory=list)
    feedback: str = ""


class TranslatedVariant(StrictModel):
    variant_id: str
    label: Relation
    source_checksum: str
    source_text: str
    target_text: str
    sentences: list[SentenceTranslation] = Field(default_factory=list)
    token_count: int = 0
    checksum: str = ""
    review: VariantReview | None = None
    repair_attempts: int = 0


class FamilyTranslation(StrictModel):
    family_id: str
    split_group_id: str
    split: Literal["train", "dev", "test", "validation"]
    source_checksum: str
    source_language: str = "en"
    profile_id: str
    profile_version: str
    target_language: str
    target_script: str
    target_claims: list[TargetClaim] = Field(default_factory=list)
    claim_cards: list[ClaimSemanticCard] = Field(default_factory=list)
    glossary: list[GlossaryEntry] = Field(default_factory=list)
    variants: list[TranslatedVariant] = Field(default_factory=list)
    status: Literal["PENDING", "RUNNING", "ACCEPTED", "QUARANTINED"] = "PENDING"
    rejection_reasons: list[str] = Field(default_factory=list)
    audit_flags: list[str] = Field(default_factory=list)
    stage: str = "source_loaded"
    calls: int = 0
    cost_usd: float = 0.0
    created_at: str = ""
    updated_at: str = ""


class TranslationManifest(StrictModel):
    profile_id: str
    profile_version: str
    source_dir: str
    output_dir: str
    source_families: int = 0
    accepted: int = 0
    quarantined: int = 0
    pending: int = 0
    calls: int = 0
    cost_usd: float = 0.0
    status: Literal["running", "complete", "stopped"] = "running"
    updated_at: str = ""


class ClaimTranslationItem(StrictModel):
    claim_id: str
    target_text: str
    preserved_terms: list[str] = Field(default_factory=list)


class ClaimTranslationPayload(StrictModel):
    claims: list[ClaimTranslationItem] = Field(default_factory=list)


class ClaimReviewItem(StrictModel):
    claim_id: str
    status: Literal["PASS", "FAIL"]
    note: str = ""


class ClaimReviewPayload(StrictModel):
    claims: list[ClaimReviewItem] = Field(default_factory=list)


class SentenceTranslationItem(StrictModel):
    sentence_id: str
    target_text: str


class WindowTranslationPayload(StrictModel):
    sentences: list[SentenceTranslationItem] = Field(default_factory=list)


class FamilyReviewPayload(StrictModel):
    variant_label: str
    verdict: ReviewVerdict
    findings: list[ClaimFinding] = Field(default_factory=list)
    faithfulness_notes: list[str] = Field(default_factory=list)
    feedback: str = ""


class GlossaryPayload(StrictModel):
    glossary: list[GlossaryEntry] = Field(default_factory=list)
