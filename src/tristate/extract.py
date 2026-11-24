"""Post-generation semantic extraction with exact evidence anchors."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from .config import Config
from .errors import StageError
from .llm import LlmClient
from .schema import Entity, Fact, SemanticRepresentation, normalize_triple
from .spans import resolve_quote, sentences_for_prompt
from .util import normalize_ws


class _RawFact(BaseModel):
    subject: str
    predicate: str
    object: str
    qualifiers: dict = Field(default_factory=dict)
    sentence_id: str | None = None
    quote: str = ""
    confidence: float = 0.8


class _RawEntity(BaseModel):
    name: str
    entity_type: str = "OTHER"


class _ExtractionPayload(BaseModel):
    summary: str = ""
    entities: list[_RawEntity] = Field(default_factory=list)
    facts: list[_RawFact] = Field(default_factory=list)
    topic_hint: str | None = None


def extract_semantics(
    llm: LlmClient,
    cfg: Config,
    text: str,
    candidate_id: str | None = None,
    stage: str = "extract",
    feedback: str = "",
) -> SemanticRepresentation:
    result = llm.structured(
        "extract",
        {"passage_json": json.dumps(sentences_for_prompt(text), indent=2), "feedback": feedback or "(none)"},
        _ExtractionPayload,
        cfg.llm.extractor,
        stage=stage,
        candidate_id=candidate_id,
    )
    payload = result.data
    facts: list[Fact] = []
    seen: set[tuple[str, str, str]] = set()
    dropped: list[str] = []
    for raw in payload.facts:
        if not raw.subject.strip() or not raw.object.strip() or not raw.predicate.strip():
            dropped.append("incomplete triple")
            continue
        if raw.confidence < cfg.claims.min_fact_confidence:
            dropped.append(f"low confidence: {raw.quote[:60]}")
            continue
        span = resolve_quote(text, raw.sentence_id, raw.quote)
        if span is None:
            dropped.append(f"span not found: {raw.quote[:60]!r}")
            continue
        triple = normalize_triple(raw.subject, raw.predicate, raw.object)
        if triple in seen:
            continue
        seen.add(triple)
        facts.append(
            Fact(
                fact_id=f"F{len(facts) + 1}",
                subject=normalize_ws(raw.subject),
                predicate=normalize_ws(raw.predicate),
                object=normalize_ws(raw.object),
                qualifiers=raw.qualifiers or {},
                source_spans=[span],
                confidence=float(raw.confidence),
            )
        )
    if len(facts) < 2:
        raise StageError(
            "extraction_insufficient",
            f"only {len(facts)} facts with valid evidence spans",
            {"facts": len(facts), "dropped": dropped[:8]},
        )

    entities: list[Entity] = []
    seen_ent: set[str] = set()
    for raw in payload.entities:
        name = normalize_ws(raw.name)
        key = name.lower()
        if not name or key in seen_ent:
            continue
        seen_ent.add(key)
        entities.append(Entity(name=name, entity_type=(raw.entity_type or "OTHER").upper()))

    summary = normalize_ws(payload.summary) or " ".join(f.subject for f in facts[:3])
    return SemanticRepresentation(
        summary=summary,
        entities=entities,
        facts=facts,
        graph_version="v1",
        topic_hint=payload.topic_hint,
    )
