"""Post-generation semantic extraction with exact evidence anchors.

Long documents are extracted in sentence-aligned windows: each window is a normal extraction
call, and every span is mapped back to global character offsets and sentence IDs. This keeps
prompts bounded and lets claims be drawn from different parts of the document.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from .config import Config
from .errors import StageError
from .llm import LlmClient
from .schema import Entity, Fact, PassageSection, SemanticRepresentation, normalize_triple
from .spans import resolve_quote, sentence_index, sentences_for_prompt, span_from_offsets
from .util import approx_tokens, normalize_ws


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


def split_windows(text: str, target_tokens: int) -> list[tuple[int, int]]:
    """Sentence-aligned character windows of roughly `target_tokens` each."""
    if target_tokens <= 0 or not text.strip():
        return [(0, len(text))]
    refs = sentence_index(text)
    if not refs:
        return [(0, len(text))]
    windows: list[tuple[int, int]] = []
    start = refs[0].start_char
    tokens = 0
    for ref in refs:
        if tokens >= target_tokens:
            windows.append((start, ref.start_char))
            start = ref.start_char
            tokens = 0
        tokens += approx_tokens(ref.text)
    windows.append((start, len(text)))
    return [(s, e) for s, e in windows if text[s:e].strip()]


def _select_windows(windows: list[tuple[int, int]], max_windows: int) -> list[tuple[int, int]]:
    if len(windows) <= max_windows:
        return windows
    if max_windows == 1:
        return [windows[0]]
    step = (len(windows) - 1) / (max_windows - 1)
    idx = sorted({int(round(i * step)) for i in range(max_windows)})
    return [windows[i] for i in idx]


def _section_for(sections: list[PassageSection] | None, offset: int) -> str | None:
    if not sections:
        return None
    for sec in sections:
        if sec.start_char <= offset < sec.end_char:
            return sec.section_id
    return None


def _extract_one(
    llm: LlmClient,
    cfg: Config,
    text: str,
    candidate_id: str | None,
    stage: str,
    feedback: str,
) -> _ExtractionPayload:
    result = llm.structured(
        "extract",
        {"passage_json": json.dumps(sentences_for_prompt(text), indent=2), "feedback": feedback or "(none)"},
        _ExtractionPayload,
        cfg.llm.extractor,
        stage=stage,
        candidate_id=candidate_id,
    )
    return result.data


def extract_semantics(
    llm: LlmClient,
    cfg: Config,
    text: str,
    candidate_id: str | None = None,
    stage: str = "extract",
    feedback: str = "",
    window_tokens: int = 0,
    max_windows: int = 12,
    sections: list[PassageSection] | None = None,
) -> SemanticRepresentation:
    windows = _select_windows(split_windows(text, window_tokens), max_windows)
    payloads: list[tuple[int, int, _ExtractionPayload]] = []
    window_errors: list[str] = []
    for i, (ws, we) in enumerate(windows):
        try:
            payload = _extract_one(
                llm,
                cfg,
                text[ws:we],
                candidate_id,
                stage=stage if window_tokens <= 0 else f"{stage}_w{i + 1}",
                feedback=feedback,
            )
            payloads.append((ws, we, payload))
        except StageError as exc:
            if window_tokens <= 0:
                raise
            window_errors.append(f"window {i + 1}: {exc}")

    facts: list[Fact] = []
    seen: set[tuple[str, str, str]] = set()
    dropped: list[str] = []
    entities: list[Entity] = []
    seen_ent: set[str] = set()
    summary = ""

    for ws, we, payload in payloads:
        if not summary and payload.summary.strip():
            summary = normalize_ws(payload.summary)[:600]
        window_text = text[ws:we]
        for raw in payload.facts:
            if not raw.subject.strip() or not raw.object.strip() or not raw.predicate.strip():
                dropped.append("incomplete triple")
                continue
            if raw.confidence < cfg.claims.min_fact_confidence:
                dropped.append(f"low confidence: {raw.quote[:60]}")
                continue
            local = resolve_quote(window_text, raw.sentence_id, raw.quote)
            if local is None:
                dropped.append(f"span not found: {raw.quote[:60]!r}")
                continue
            span = span_from_offsets(text, ws + local.start_char, ws + local.end_char)
            if span is None:
                dropped.append("global span mapping failed")
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
                    section_id=_section_for(sections, span.start_char),
                )
            )
        for raw in payload.entities:
            name = normalize_ws(raw.name)
            key = name.lower()
            if not name or key in seen_ent:
                continue
            seen_ent.add(key)
            entities.append(Entity(name=name, entity_type=(raw.entity_type or "OTHER").upper()))

    if len(facts) < cfg.extraction.min_facts:
        raise StageError(
            "extraction_insufficient",
            f"only {len(facts)} facts with valid evidence spans",
            {
                "facts": len(facts),
                "dropped": dropped[:8],
                "windows": len(windows),
                "window_errors": window_errors[:4],
            },
        )

    if not summary:
        summary = " ".join(f.subject for f in facts[:3])
    return SemanticRepresentation(
        summary=summary,
        entities=entities,
        facts=facts,
        graph_version="v1",
        topic_hint=None,
    )
