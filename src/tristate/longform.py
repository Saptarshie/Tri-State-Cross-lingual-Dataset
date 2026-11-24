"""Long-form base document planning and sectioned generation.

The blueprint is a soft direction, not a length target. This module expands it into a
section plan and writes the document section by section, carrying continuity context and
screening each section before assembly. Sections are cached as independent artefacts so a
crash mid-document resumes without paying for completed sections.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel

from .config import Config
from .errors import StageError
from .llm import LlmClient
from .schema import Blueprint, DocumentPlan, PassageSection, SectionPlan
from .util import (
    approx_tokens,
    english_score,
    jaccard,
    meta_statement_hits,
    normalize_ws,
    sha256_json,
    sha256_text,
    split_sentences,
    truncate,
    word_ngrams,
)


class _SectionPayload(BaseModel):
    text: str


@dataclass
class SectionDraft:
    plan: SectionPlan
    text: str


def target_section_count(cfg: Config) -> int:
    p = cfg.passage
    mean_section = (p.section_tokens_min + p.section_tokens_max) / 2
    target_total = (p.target_tokens_min + p.target_tokens_max) / 2
    n = int(round(target_total / max(1.0, mean_section)))
    return max(p.sections_min, min(p.max_sections, n))


def plan_document(
    llm: LlmClient,
    cfg: Config,
    blueprint: Blueprint,
    candidate_id: str | None = None,
) -> DocumentPlan:
    p = cfg.passage
    expected_sections = target_section_count(cfg)
    effective_max = max(p.sections_max, expected_sections)
    result = llm.structured(
        "document_plan",
        {
            "topic_path": " > ".join(blueprint.topic_path),
            "blueprint_json": json.dumps(blueprint.model_dump(mode="json"), indent=2),
            "genre": blueprint.genre,
            "tone": blueprint.tone,
            "structure": blueprint.structure,
            "complexity": blueprint.complexity,
            "token_min": p.target_tokens_min,
            "token_max": p.target_tokens_max,
            "sections_min": p.sections_min,
            "sections_max": effective_max,
            "section_tokens_min": p.section_tokens_min,
            "section_tokens_max": p.section_tokens_max,
            "target_fact_count": blueprint.target_fact_count,
            "seed_intent": blueprint.main_concept,
            "novelty_report": blueprint.novelty_report.get("guidance", "(no prior generations)"),
        },
        DocumentPlan,
        cfg.llm.generator,
        stage="document_plan",
        candidate_id=candidate_id,
    )
    plan = result.data
    if not (p.sections_min <= len(plan.sections) <= effective_max):
        raise StageError(
            "document_plan_invalid",
            f"planned {len(plan.sections)} sections, expected {p.sections_min}-{effective_max}",
            {"sections": [s.section_id for s in plan.sections]},
        )
    ids = [s.section_id for s in plan.sections]
    if ids != [f"S{i}" for i in range(1, len(ids) + 1)]:
        # normalise IDs rather than rejecting a workable plan
        for i, sec in enumerate(plan.sections, start=1):
            sec.section_id = f"S{i}"
    for sec in plan.sections:
        sec.target_tokens = max(
            p.section_tokens_min,
            min(p.section_tokens_max * 2, int(sec.target_tokens or p.section_tokens_min)),
        )
    plan.total_target_tokens = sum(s.target_tokens for s in plan.sections)
    if not plan.plan_id:
        plan.plan_id = "DP_" + sha256_text(json.dumps(ids))[:10]
    return plan


def _section_problems(text: str, target: int, cfg: Config, structure: str = "") -> list[str]:
    problems: list[str] = []
    tokens = approx_tokens(text)
    if tokens < target * 0.5:
        problems.append(f"too short: {tokens} tokens (target ~{target})")
    if tokens > target * 1.8:
        problems.append(f"too long: {tokens} tokens (target ~{target})")
    if english_score(text) < cfg.quality.min_english_score:
        problems.append("non-English characters present")
    hits = meta_statement_hits(text)
    if hits and cfg.quality.forbid_meta_statements:
        problems.append(f"meta-language: {hits[:3]}")
    if re.search(r"^#{1,6}\s", text, flags=re.M):
        problems.append("markdown heading in section")
    if structure not in ("bulleted_explanation", "numbered_procedure"):
        if re.search(r"(^|\s)[*•]\s", text):
            problems.append("bullet formatting in prose section")
    if text.rstrip().endswith(":"):
        problems.append("section ends with a colon")
    sentences = split_sentences(text)
    if len(sentences) < 3:
        problems.append("fewer than three sentences")
    uniq = {s.strip().lower() for s in sentences}
    if sentences and 1 - len(uniq) / len(sentences) > cfg.quality.max_repeated_sentence_ratio:
        problems.append("repeated sentences")
    if "lorem ipsum" in text.lower():
        problems.append("placeholder text")
    return problems


def _covered_points(plan: DocumentPlan, upto: int) -> list[dict[str, Any]]:
    return [
        {
            "section_id": s.section_id,
            "title": s.title,
            "key_points": s.key_points,
        }
        for s in plan.sections[:upto]
    ]


def generate_document(
    llm: LlmClient,
    cfg: Config,
    blueprint: Blueprint,
    plan: DocumentPlan,
    candidate_id: str | None = None,
    prompt_version: str = "",
    load_section: Callable[[str], dict[str, Any] | None] | None = None,
    save_section: Callable[[str, dict[str, Any]], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> tuple[str, list[PassageSection], dict[str, Any]]:
    """Write the document. Section artefacts are keyed by plan + prompt version."""
    p = cfg.passage
    texts: list[str] = []
    drafts: list[SectionDraft] = []
    reused = 0
    stats: list[dict[str, Any]] = []

    for index, section in enumerate(plan.sections):
        key = sha256_json(
            {
                "plan_id": plan.plan_id,
                "section": section.model_dump(mode="json"),
                "prompt": prompt_version,
            }
        )[:16]
        cached = load_section(key) if load_section else None
        if cached and cached.get("text"):
            text = normalize_ws(cached["text"])
            reused += 1
        else:
            prior = "\n\n".join(texts)
            tail = prior[-max(0, p.section_context_chars):] if prior else "(document start)"
            feedback = ""
            problems: list[str] = []
            text = ""
            for attempt in range(1 + max(0, p.section_repair_attempts)):
                result = llm.structured(
                    "section",
                    {
                        "blueprint_json": json.dumps(blueprint.model_dump(mode="json"), indent=2),
                        "throughline": plan.throughline or blueprint.main_concept,
                        "section_json": json.dumps(section.model_dump(mode="json"), indent=2),
                        "covered_json": json.dumps(_covered_points(plan, index), indent=2),
                        "prior_tail": tail,
                        "genre": blueprint.genre,
                        "tone": blueprint.tone,
                        "structure": blueprint.structure,
                        "complexity": blueprint.complexity,
                        "token_min": section.target_tokens,
                        "token_max": int(section.target_tokens * 1.25),
                        "word_min": int(section.target_tokens / 0.75 * 0.9),
                        "word_max": int(section.target_tokens / 0.75 * 1.2),
                        "feedback": feedback or "(none)",
                    },
                    _SectionPayload,
                    cfg.llm.generator,
                    stage=f"section_{section.section_id}",
                    candidate_id=candidate_id,
                )
                text = normalize_ws(result.data.text)
                problems = _section_problems(text, section.target_tokens, cfg, blueprint.structure)
                if not problems:
                    break
                feedback = "The previous section was rejected: " + "; ".join(problems) + ". Rewrite it."
            if problems:
                raise StageError(
                    "section_quality",
                    f"section {section.section_id} failed screening after retries",
                    {"section_id": section.section_id, "problems": problems},
                )
            if save_section:
                save_section(
                    key,
                    {
                        "section_id": section.section_id,
                        "key": key,
                        "prompt_version": prompt_version,
                        "target_tokens": section.target_tokens,
                        "text": text,
                        "token_count": approx_tokens(text),
                    },
                )
        if log:
            log(f"{candidate_id} section {section.section_id}: {approx_tokens(text)} tokens"
                f"{' (reused)' if cached else ''}")
        texts.append(text)
        drafts.append(SectionDraft(section, text))
        stats.append(
            {
                "section_id": section.section_id,
                "target_tokens": section.target_tokens,
                "tokens": approx_tokens(text),
                "reused": bool(cached),
            }
        )

    # Assemble and screen the whole document; expand the weakest section if it is short.
    text, sections = assemble(drafts)
    problems = check_document(text, cfg, plan, sections)
    expansion_rounds = 0
    while problems and any(p.startswith("document too short") for p in problems) and expansion_rounds < max(
        1, p.section_repair_attempts
    ):
        expansion_rounds += 1
        shortest = min(drafts, key=lambda d: approx_tokens(d.text))
        if log:
            log(f"{candidate_id} expanding {shortest.plan.section_id} to reach document length")
        result = llm.structured(
            "section",
            {
                "blueprint_json": json.dumps(blueprint.model_dump(mode="json"), indent=2),
                "throughline": plan.throughline or blueprint.main_concept,
                "section_json": json.dumps(shortest.plan.model_dump(mode="json"), indent=2),
                "covered_json": json.dumps(_covered_points(plan, len(drafts)), indent=2),
                "prior_tail": "\n\n".join(t for t in texts if t != shortest.text)[-max(0, p.section_context_chars):],
                "genre": blueprint.genre,
                "tone": blueprint.tone,
                "structure": blueprint.structure,
                "complexity": blueprint.complexity,
                "token_min": int(shortest.plan.target_tokens * 1.3),
                "token_max": int(shortest.plan.target_tokens * 1.6),
                "word_min": int(shortest.plan.target_tokens / 0.75),
                "word_max": int(shortest.plan.target_tokens / 0.75 * 1.5),
                "feedback": "The document is too short. Expand this section with additional concrete "
                            "detail, examples, numbers, steps or consequences, without repeating other sections.",
            },
            _SectionPayload,
            cfg.llm.generator,
            stage=f"expand_{shortest.plan.section_id}_{expansion_rounds}",
            candidate_id=candidate_id,
        )
        expanded = normalize_ws(result.data.text)
        if not _section_problems(expanded, shortest.plan.target_tokens, cfg, blueprint.structure):
            texts[texts.index(shortest.text)] = expanded
            shortest.text = expanded
            text, sections = assemble(drafts)
            problems = check_document(text, cfg, plan, sections)

    if problems:
        raise StageError("document_quality", "assembled document failed screening", {"problems": problems})

    meta = {
        "sections": stats,
        "reused_sections": reused,
        "expansion_rounds": expansion_rounds,
        "tokens": approx_tokens(text),
        "plan_id": plan.plan_id,
    }
    return text, sections, meta


def assemble(drafts: list[SectionDraft]) -> tuple[str, list[PassageSection]]:
    parts: list[str] = []
    sections: list[PassageSection] = []
    cursor = 0
    for draft in drafts:
        if parts:
            parts.append("\n\n")
            cursor += 2
        start = cursor
        parts.append(draft.text)
        cursor += len(draft.text)
        sections.append(
            PassageSection(
                section_id=draft.plan.section_id,
                title=draft.plan.title,
                start_char=start,
                end_char=cursor,
                token_count=approx_tokens(draft.text),
                checksum=sha256_text(draft.text),
            )
        )
    text = "".join(parts)
    # offsets must reconstruct the exact section text
    for sec, draft in zip(sections, drafts):
        if text[sec.start_char:sec.end_char] != draft.text:
            raise StageError("assembly_broken", "section offsets do not match assembled text", {"section": sec.section_id})
    return text, sections


def check_document(
    text: str,
    cfg: Config,
    plan: DocumentPlan | None = None,
    sections: list[PassageSection] | None = None,
) -> list[str]:
    p = cfg.passage
    problems: list[str] = []
    tokens = approx_tokens(text)
    lo = int(p.target_tokens_min * p.min_document_ratio)
    hi = int(p.target_tokens_max * p.max_document_ratio)
    if tokens < lo:
        problems.append(f"document too short: {tokens} tokens (target {p.target_tokens_min}-{p.target_tokens_max})")
    if tokens > hi:
        problems.append(f"document too long: {tokens} tokens (target {p.target_tokens_min}-{p.target_tokens_max})")
    if english_score(text) < cfg.quality.min_english_score:
        problems.append("non-English characters present")
    hits = meta_statement_hits(text)
    if hits and cfg.quality.forbid_meta_statements:
        problems.append(f"meta-language: {hits[:3]}")
    sentences = split_sentences(text)
    if len(sentences) < 6:
        problems.append("fewer than six sentences")
    uniq = {s.strip().lower() for s in sentences}
    if sentences and 1 - len(uniq) / len(sentences) > cfg.quality.max_repeated_sentence_ratio:
        problems.append("repeated sentences")
    if sections and len(sections) > 1:
        # cross-section copy/paste: compare 12-gram shingles between section pairs
        chunks = [text[sec.start_char:sec.end_char] for sec in sections]
        worst = 0.0
        for i in range(len(chunks)):
            for j in range(i + 1, len(chunks)):
                worst = max(worst, jaccard(word_ngrams(chunks[i], 12), word_ngrams(chunks[j], 12)))
        if worst > p.max_cross_section_overlap:
            problems.append(f"cross-section repetition {worst:.2f} exceeds {p.max_cross_section_overlap}")
    return problems


def sections_from_plan(text: str, plan: DocumentPlan) -> list[PassageSection]:
    """Recompute offsets from `\n\n` boundaries matching the plan order (for screening only)."""
    parts = text.split("\n\n")
    out: list[PassageSection] = []
    cursor = 0
    for i, section in enumerate(plan.sections):
        if i >= len(parts):
            break
        chunk = parts[i]
        start = cursor
        end = start + len(chunk)
        out.append(
            PassageSection(
                section_id=section.section_id,
                title=section.title,
                start_char=start,
                end_char=end,
                token_count=approx_tokens(chunk),
            )
        )
        cursor = end + 2
    return out


def section_for_offset(sections: list[PassageSection], offset: int) -> str | None:
    for sec in sections:
        if sec.start_char <= offset < sec.end_char:
            return sec.section_id
    return None


def document_excerpt(text: str, sections: list[PassageSection], max_chars: int = 600) -> str:
    return truncate(text, max_chars)
