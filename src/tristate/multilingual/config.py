"""Configuration and fixed target profiles for the translation branch."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from ..schema import StrictModel
from .models import TargetProfile

DEFAULT_CONFIG = "configs/multilingual.yaml"
REPO_ROOT = Path(__file__).resolve().parents[3]


class DeepSeekCfg(StrictModel):
    # The branch uses the same OpenAI-compatible credential as the English
    # factory by default; the model is still DeepSeek.  Override base_url /
    # api_key_env only when a separate translation credential is provisioned.
    base_url: str = "https://api.commandcode.ai/provider/v1"
    api_key_env: str = "LLM_API_KEY"
    model: str = "deepseek/deepseek-v4.1-flash"
    review_model: str = "deepseek/deepseek-v4.1-flash"
    temperature: float = 0.2
    review_temperature: float = 0.0
    max_tokens: int = 64000
    cost_in_per_mtok: float = 0.0
    cost_out_per_mtok: float = 0.0
    thinking_mode: bool = False
    review_thinking_mode: bool = True
    # Provider-specific request extensions (for example the current DeepSeek
    # thinking-mode parameter).  Kept explicit so we never guess a field name.
    extra_body_generate: dict[str, object] = Field(default_factory=dict)
    extra_body_review: dict[str, object] = Field(default_factory=dict)
    request_timeout_s: int = 300
    max_retries: int = 3

    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) or None


class WindowCfg(StrictModel):
    target_words_min: int = 250
    target_words_max: int = 500
    context_sentences: int = 2
    max_repairs: int = 2
    concurrency: int = 4


class FixerCfg(StrictModel):
    enabled: bool = True
    max_steps: int = 30
    max_edits_per_step: int = 30
    max_total_edits: int = 30


class MultilingualCfg(StrictModel):
    source_dir: str = "data-v5"
    output_dir: str = "data-v5/multilingual"
    prompts_dir: str = "prompts"
    profiles: list[TargetProfile] = Field(default_factory=list)
    deepseek: DeepSeekCfg = Field(default_factory=DeepSeekCfg)
    window: WindowCfg = Field(default_factory=WindowCfg)
    fixer: FixerCfg = Field(default_factory=FixerCfg)
    max_profiles: int = 4
    require_independent_review: bool = True

    @property
    def source_path(self) -> Path:
        p = Path(self.source_dir)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def output_path(self) -> Path:
        p = Path(self.output_dir)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def prompts_path(self) -> Path:
        p = Path(self.prompts_dir)
        return p if p.is_absolute() else REPO_ROOT / p

    def profile(self, profile_id: str) -> TargetProfile:
        for p in self.profiles:
            if p.profile_id == profile_id:
                return p
        raise KeyError(f"unknown target profile: {profile_id}; known: {[p.profile_id for p in self.profiles]}")


def default_profiles() -> list[TargetProfile]:
    """The four target profiles approved for the first translation release."""

    common_proper = "transliterate proper nouns consistently and give the English form on first mention"
    return [
        TargetProfile(
            profile_id="bn_in_native",
            base_language="Bengali",
            locale="bn-IN",
            display_name="West Bengal Bengali, native script",
            script_policy="native",
            primary_script="Bengali",
            sentence_syntax="natural Bengali SOV; split long English sentences when Bengali clause order would become unreadable",
            register_style="educated standard Bengali; spoken rhythm without slang",
            regional_style="West Bengal / Kolkata standard",
            romanization_policy="not applicable",
            proper_noun_policy=common_proper,
        ),
        TargetProfile(
            profile_id="bn_bd_native",
            base_language="Bengali",
            locale="bn-BD",
            display_name="Bangladesh Bengali, native script",
            script_policy="native",
            primary_script="Bengali",
            sentence_syntax="natural Bangladeshi Bengali SOV; prefer shorter clauses than the English source",
            register_style="educated standard Bengali; Bangladeshi spelling and vocabulary",
            regional_style="Dhaka standard",
            romanization_policy="not applicable",
            proper_noun_policy=common_proper,
        ),
        TargetProfile(
            profile_id="bn_romanized",
            base_language="Bengali",
            locale="bn-IN-rom",
            display_name="Romanized Bengali",
            script_policy="romanized",
            primary_script="Latin",
            sentence_syntax="Bengali syntax and idiom written in Latin script; avoid English word order",
            register_style="informal online register; consistent romanization",
            regional_style="West Bengal online romanization",
            romanization_policy="one consistent scheme throughout; no mixing with native script; common English loanwords may remain English",
            proper_noun_policy="keep established Latin spelling for names; do not alternate spellings",
            code_switching=False,
            code_switching_intensity="none",
        ),
        TargetProfile(
            profile_id="banglish_code_mixed",
            base_language="Bengali",
            locale="bn-IN-mixed",
            display_name="Banglish / code-mixed Bengali",
            script_policy="mixed",
            primary_script="Mixed",
            sentence_syntax="Bengali matrix syntax with natural English technical insertions; code-switch at phrase boundaries, not random word substitution",
            register_style="urban conversational; competent bilingual speaker",
            regional_style="Kolkata urban code-mixing",
            romanization_policy="Bengali content in Latin script; English technical terms in English",
            proper_noun_policy=common_proper,
            code_switching=True,
            code_switching_intensity="moderate",
            english_term_policy="keep established English technical terms in English; translate ordinary vocabulary into Bengali",
        ),
    ]


def load_config(path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> MultilingualCfg:
    raw: dict[str, Any] = {}
    chosen = Path(path) if path else REPO_ROOT / DEFAULT_CONFIG
    if chosen.exists():
        loaded = yaml.safe_load(chosen.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"multilingual config must be a mapping: {chosen}")
        raw = loaded
    if overrides:
        raw = _deep_merge(raw, overrides)
    if not raw.get("profiles"):
        raw["profiles"] = [p.model_dump() for p in default_profiles()]
    return MultilingualCfg.model_validate(raw)


def _deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out
