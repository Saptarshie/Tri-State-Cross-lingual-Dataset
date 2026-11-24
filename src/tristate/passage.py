"""Base passage generation with deterministic pre-screening."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel

from .config import Config
from .errors import StageError
from .llm import LlmClient
from .schema import Blueprint
from .util import (
    approx_tokens,
    english_score,
    meta_statement_hits,
    normalize_ws,
    split_sentences,
)


class _PassagePayload(BaseModel):
    text: str


def check_passage_text(text: str, cfg: Config, blueprint: Blueprint) -> list[str]:
    problems: list[str] = []
    text = normalize_ws(text)
    if not text:
        return ["empty passage"]
    tokens = approx_tokens(text)
    lo, hi = blueprint.target_length_tokens
    if tokens < lo * 0.55:
        problems.append(f"too short: {tokens} tokens (target {lo}-{hi})")
    if tokens > hi * 1.6:
        problems.append(f"too long: {tokens} tokens (target {lo}-{hi})")
    if english_score(text) < cfg.quality.min_english_score:
        problems.append("non-English characters present")
    hits = meta_statement_hits(text)
    if hits and cfg.quality.forbid_meta_statements:
        problems.append(f"label/task meta-language: {hits[:3]}")
    sentences = split_sentences(text)
    if len(sentences) < 2 and blueprint.structure not in ("qa_pair",):
        problems.append("fewer than two sentences")
    if blueprint.structure not in ("bulleted_explanation", "numbered_procedure"):
        if re.search(r"(^|\s)[#*\-•]\s", text) or "##" in text:
            problems.append("markdown or bullet formatting in prose passage")
    if text.rstrip().endswith(":"):
        problems.append("passage ends with a colon")
    uniq = {s.strip().lower() for s in sentences}
    if sentences and 1 - len(uniq) / len(sentences) > cfg.quality.max_repeated_sentence_ratio:
        problems.append("repeated sentences")
    if "lorem ipsum" in text.lower():
        problems.append("placeholder text")
    return problems


def generate_passage(
    llm: LlmClient,
    cfg: Config,
    blueprint: Blueprint,
    source_excerpt: str = "",
    candidate_id: str | None = None,
    max_attempts: int = 2,
) -> str:
    feedback = ""
    problems: list[str] = []
    for attempt in range(max_attempts):
        result = llm.structured(
            "passage",
            {
                "blueprint_json": json.dumps(blueprint.model_dump(mode="json"), indent=2),
                "source_excerpt": source_excerpt or "(none)",
                "token_min": blueprint.target_length_tokens[0],
                "token_max": blueprint.target_length_tokens[1],
                "word_min": int(blueprint.target_length_tokens[0] / 0.75),
                "word_max": int(blueprint.target_length_tokens[1] / 0.75),
                "max_facts": min(6, blueprint.target_fact_count + 1),
                "target_fact_count": blueprint.target_fact_count,
                "genre": blueprint.genre,
                "tone": blueprint.tone,
                "structure": blueprint.structure,
                "complexity": blueprint.complexity,
                "feedback": feedback or "(none)",
            },
            _PassagePayload,
            cfg.llm.generator,
            stage="passage",
            candidate_id=candidate_id,
        )
        text = normalize_ws(result.data.text)
        problems = check_passage_text(text, cfg, blueprint)
        if not problems:
            return text
        feedback = "The previous attempt was rejected because: " + "; ".join(problems) + ". Rewrite the passage."
    raise StageError(
        "passage_quality",
        "generated passage failed deterministic screening after retries",
        {"problems": problems},
    )
