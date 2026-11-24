"""Blueprint planning: abstract plan before prose, informed by novelty feedback."""

from __future__ import annotations

import random
from typing import Any

from pydantic import BaseModel, Field

from .config import Config
from .errors import StageError
from .ids import blueprint_id as make_blueprint_id
from .llm import LlmClient
from .schema import Blueprint, BlueprintCandidate
from .util import stable_seed


class _BlueprintPayload(BaseModel):
    main_concept: str
    subtopics: list[str] = Field(default_factory=list)
    planned_entity_types: list[str] = Field(default_factory=list)
    planned_relation_types: list[str] = Field(default_factory=list)
    planned_fact_types: list[str] = Field(default_factory=list)
    target_fact_count: int = 4


def choose_style(cfg: Config, candidate: BlueprintCandidate, novelty_report: dict[str, Any]) -> dict[str, str]:
    """Balance genre/tone/structure across the corpus, with deterministic rotation."""
    rng = random.Random(stable_seed("style", cfg.project.seed, candidate.candidate_id))
    suggested = novelty_report.get("suggested", {}) if novelty_report else {}

    def pick(options: list[str], key: str) -> str:
        if key in suggested and suggested[key] in options and rng.random() < 0.6:
            return suggested[key]
        return options[rng.randrange(len(options))]

    return {
        "genre": pick(cfg.blueprint.genres, "genre"),
        "tone": pick(cfg.blueprint.tones, "tone"),
        "structure": pick(cfg.blueprint.structures, "structure"),
        "complexity": cfg.blueprint.complexities[rng.randrange(len(cfg.blueprint.complexities))],
    }


def plan_blueprint(
    llm: LlmClient,
    cfg: Config,
    candidate: BlueprintCandidate,
    novelty_report: dict[str, Any] | None = None,
    source_excerpt: str = "",
) -> Blueprint:
    novelty_report = novelty_report or {}
    style = choose_style(cfg, candidate, novelty_report)
    focus = candidate.seed_intent or (candidate.topic_path[-1] if candidate.topic_path else "general")
    token_min = cfg.passage.target_tokens_min
    token_max = cfg.passage.target_tokens_max
    mean_section = (cfg.passage.section_tokens_min + cfg.passage.section_tokens_max) / 2
    target_sections = int(round(((token_min + token_max) / 2) / max(1.0, mean_section)))
    target_sections = max(cfg.passage.sections_min, min(cfg.passage.sections_max, target_sections))
    planned_facts = max(6, min(12, int(((token_min + token_max) / 2) / 400)))
    result = llm.structured(
        "blueprint",
        {
            "topic_path": " > ".join(candidate.topic_path) or candidate.seed_intent,
            "main_concept": focus,
            "source_excerpt": source_excerpt or "(none)",
            "genre": style["genre"],
            "tone": style["tone"],
            "structure": style["structure"],
            "complexity": style["complexity"],
            "token_min": token_min,
            "token_max": token_max,
            "target_fact_count": planned_facts,
            "seed_intent": candidate.seed_intent or "explore this topic from an unusual angle",
            "novelty_report": novelty_report.get("guidance", "(no prior generations)"),
        },
        _BlueprintPayload,
        cfg.llm.generator,
        stage="blueprint",
        candidate_id=candidate.candidate_id,
    )
    payload = result.data
    concept = (payload.main_concept or "").strip()
    if len(concept) < 12:
        raise StageError("blueprint_invalid", "main_concept too short", {"main_concept": concept})
    subtopics = [s.strip() for s in payload.subtopics if s and s.strip()][:6]
    if len(subtopics) < 2:
        raise StageError("blueprint_invalid", "too few subtopics", {"subtopics": subtopics})
    relations = [r.strip() for r in payload.planned_relation_types if r and r.strip()][:8]
    if not relations:
        relations = ["developed_by", "located_in"]

    return Blueprint(
        blueprint_id=make_blueprint_id(candidate.candidate_id),
        topic_path=candidate.topic_path or [candidate.topic_ids[0] if candidate.topic_ids else "General"],
        main_concept=concept,
        subtopics=subtopics,
        planned_entity_types=[e.strip() for e in payload.planned_entity_types if e.strip()][:8],
        planned_relation_types=relations,
        planned_fact_types=[t.strip() for t in payload.planned_fact_types if t.strip()][:8],
        genre=style["genre"],
        tone=style["tone"],
        structure=style["structure"],
        complexity=style["complexity"],
        target_fact_count=max(planned_facts, min(12, int(payload.target_fact_count or planned_facts))),
        target_length_tokens=[token_min, token_max],
        target_sections=target_sections,
        novelty_report=novelty_report,
    )
