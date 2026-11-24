"""Validated configuration model.

Every knob from the objective lives here (YAML file + environment overrides).
Nothing operational is hard-coded in prompts or stage code.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

LABELS = ("SUPPORTED", "CONTRADICTED", "UNSUPPORTED")
RELATIONS = ("ENTAILED", "CONTRADICTED", "NEUTRAL", "UNCERTAIN")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "default.yaml"
DEFAULT_PROMPTS = REPO_ROOT / "prompts"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no dependency); real environment always wins."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class ProjectCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "tri_state_counterfactual_dataset"
    language: str = "en"
    script: str = "Latin"
    locale: str = "en_US"
    output_dir: str = "data"
    seed: int = 20261124


class CorpusCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled_tracks: list[str] = Field(default_factory=lambda: ["topic_generated"])
    topic_max_depth: int = 3
    max_children_per_topic: int = 8
    passage_token_min: int = 80
    passage_token_max: int = 300
    retain_source_documents: bool = True
    local_source_dirs: list[str] = Field(default_factory=list)
    news_feeds: list[str] = Field(default_factory=list)
    news_fetch_enabled: bool = False
    dedupe_similarity: float = 0.9

    @model_validator(mode="after")
    def _bands(self) -> "CorpusCfg":
        if self.passage_token_min >= self.passage_token_max:
            raise ValueError("passage_token_min must be < passage_token_max")
        if self.topic_max_depth < 1 or self.max_children_per_topic < 1:
            raise ValueError("topic bounds must be positive")
        return self


class PassageCfg(BaseModel):
    """Base artifact length and sectioning.

    Tokens are model tokens estimated by util.approx_tokens (~0.75 per word). The default
    band is deliberately moderate; raise it to 10k-15k for long-context RAG training.
    """

    model_config = ConfigDict(extra="forbid")
    target_tokens_min: int = 2000
    target_tokens_max: int = 4000
    sections_min: int = 3
    sections_max: int = 8
    section_tokens_min: int = 450
    section_tokens_max: int = 900
    max_sections: int = 24
    section_context_chars: int = 1600
    single_call_below_tokens: int = 700
    section_repair_attempts: int = 1
    min_document_ratio: float = 0.8
    max_document_ratio: float = 1.25
    max_cross_section_overlap: float = 0.15

    @model_validator(mode="after")
    def _bands(self) -> "PassageCfg":
        if self.target_tokens_min >= self.target_tokens_max:
            raise ValueError("passage.target_tokens_min must be < target_tokens_max")
        if self.sections_min < 1 or self.sections_min > self.sections_max:
            raise ValueError("passage.sections_min must be >= 1 and <= sections_max")
        if self.section_tokens_min >= self.section_tokens_max:
            raise ValueError("passage.section_tokens_min must be < section_tokens_max")
        if self.max_sections < self.sections_max:
            raise ValueError("passage.max_sections must be >= sections_max")
        if not (0 < self.min_document_ratio <= 1 <= self.max_document_ratio):
            raise ValueError("document ratios must satisfy 0 < min <= 1 <= max")
        return self


class ExtractionCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window_tokens: int = 1500  # 0 = extract the whole document in one call
    max_windows: int = 12
    min_facts: int = 2

    @model_validator(mode="after")
    def _windows(self) -> "ExtractionCfg":
        if self.window_tokens < 0 or self.max_windows < 1:
            raise ValueError("extraction window bounds must be non-negative")
        return self


class BlueprintCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates_per_topic: int = 2
    novelty_top_k: int = 10
    similarity_threshold: float = 0.9
    genres: list[str] = Field(
        default_factory=lambda: [
            "news_report", "encyclopedia_entry", "textbook_excerpt",
            "technical_explanation", "research_summary", "business_brief",
            "faq_answer", "product_documentation", "interview_excerpt",
            "field_report", "policy_brief", "manual_procedure",
        ]
    )
    tones: list[str] = Field(
        default_factory=lambda: [
            "neutral_explanatory", "formal", "conversational", "academic",
            "concise_journalistic", "instructional", "analytical",
        ]
    )
    structures: list[str] = Field(
        default_factory=lambda: [
            "multi_section_report", "chaptered_explainer", "technical_brief",
            "case_study", "policy_briefing", "research_summary",
            "manual_procedure", "qa_pair",
        ]
    )
    narratives: list[str] = Field(
        default_factory=lambda: [
            "expository", "storytelling", "first_person", "persuasive",
            "humorous", "opinionated",
        ]
    )
    complexities: list[str] = Field(default_factory=lambda: ["introductory", "intermediate", "advanced"])
    summary_max_chars: int = 600


class ClaimsCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_claims_per_family: int = 2
    max_claims_per_family: int = 12
    target_claims_per_document: int = 4
    min_distinct_sections: int = 2
    min_fact_confidence: float = 0.55
    require_atomic_claims: bool = True
    max_claim_chars: int = 220

    @model_validator(mode="after")
    def _order(self) -> "ClaimsCfg":
        if self.min_claims_per_family < 1:
            raise ValueError("min_claims_per_family >= 1")
        if self.min_claims_per_family > self.max_claims_per_family:
            raise ValueError("min_claims_per_family must be <= max_claims_per_family")
        # keep the target inside bounds rather than rejecting a test/config that only
        # overrides min/max (common when widening the claim range)
        self.target_claims_per_document = max(
            self.min_claims_per_family, min(self.max_claims_per_family, self.target_claims_per_document)
        )
        return self


class VariantsCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    required_labels: list[str] = Field(default_factory=lambda: list(LABELS))
    require_all_claims_to_match_label: bool = True
    max_edit_repair_attempts: int = 2
    prefer_patch_editing: bool = True
    min_length_ratio: float = 0.45
    max_length_ratio: float = 1.9
    min_content_overlap: float = 0.25
    long_document_tokens: int = 1200
    min_length_ratio_long: float = 0.7
    max_length_ratio_long: float = 1.3
    edit_view_sentences: int = 2
    edit_view_max_sentences: int = 120

    @field_validator("required_labels")
    @classmethod
    def _labels(cls, v: list[str]) -> list[str]:
        if set(v) != set(LABELS):
            raise ValueError(f"required_labels must be exactly {LABELS}")
        return list(LABELS)


class HnswCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    indexes: list[str] = Field(
        default_factory=lambda: ["blueprint", "passage", "fact_claim", "edit_signature"]
    )
    m: int = 16
    ef_construction: int = 200
    ef_search: int = 64
    top_k: int = 10
    dim: int = 768
    embedder: Literal["ollama", "hashing", "api"] = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "embeddinggemma"
    embed_batch: int = 16
    embed_timeout_s: float = 120.0
    api_model: str = ""
    near_duplicate_cosine: float = 0.93
    near_duplicate_jaccard: float = 0.82
    passage_chunk_tokens: int = 1200
    near_duplicate_chunk_fraction: float = 0.5
    split_aware: bool = True


class ValidationCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    require_independent_verification: bool = True
    require_evidence_spans: bool = True
    allow_world_truth_gate: bool = False
    quarantine_mixed_families: bool = True
    human_audit_fraction: float = 0.05
    second_validator_confidence: float = 0.75
    min_relation_confidence: float = 0.5
    require_graph_diff: bool = False
    max_graph_diff_misses: int = 1
    second_validator_on_failure: bool = True
    sample_second_validator: float = 0.1


class SplitsCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    train: float = 0.8
    validation: float = 0.1
    test: float = 0.1
    group_key: str = "passage_family_id"
    salt: str = "tristate-v1"
    duplicate_clustering: bool = True

    @model_validator(mode="after")
    def _sum(self) -> "SplitsCfg":
        total = self.train + self.validation + self.test
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"split fractions must sum to 1.0 (got {total})")
        return self


class ExecutionCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_concurrency: int = 10
    max_retries: int = 3
    backoff_base_s: float = 1.5
    backoff_max_s: float = 30.0
    max_total_cost_usd: float = 20.0
    max_calls_per_family: int = 80
    request_timeout_s: float = 120.0
    checkpoint_every: int = 5
    retry_permanent_errors: bool = False


class ModelCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = ""
    temperature: float = 0.8
    max_tokens: int = 1200
    cost_in_per_mtok: float = 0.0
    cost_out_per_mtok: float = 0.0


class LlmCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = "https://api.commandcode.ai/provider/v1"
    api_key_env: str = "LLM_API_KEY"
    user_agent: str = "Mozilla/5.0 (compatible; tristate-factory/0.1)"
    json_mode: bool = True
    json_schema_mode: bool = False
    schema_repair_attempts: int = 1
    cache_enabled: bool = True
    live_probe_on_start: bool = True
    generator: ModelCfg = Field(
        default_factory=lambda: ModelCfg(name="deepseek/deepseek-v4.1-flash", temperature=0.85, max_tokens=1600)
    )
    extractor: ModelCfg = Field(
        default_factory=lambda: ModelCfg(name="deepseek/deepseek-v4.1-flash", temperature=0.0, max_tokens=2000)
    )
    claims: ModelCfg = Field(
        default_factory=lambda: ModelCfg(name="deepseek/deepseek-v4.1-flash", temperature=0.2, max_tokens=1200)
    )
    editor: ModelCfg = Field(
        default_factory=lambda: ModelCfg(name="deepseek/deepseek-v4.1-flash", temperature=0.5, max_tokens=1800)
    )
    validator: ModelCfg = Field(
        default_factory=lambda: ModelCfg(name="xiaomi/mimo-v2.6-flash", temperature=0.0, max_tokens=1500)
    )
    validator_second: ModelCfg = Field(
        default_factory=lambda: ModelCfg(name="google/gemini-3.8-flash", temperature=0.0, max_tokens=1500)
    )
    fallback_models: list[str] = Field(default_factory=list)


class QualityCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_english_score: float = 0.97
    forbid_meta_statements: bool = True
    min_distractor_length_ratio: float = 0.45
    max_repeated_sentence_ratio: float = 0.25
    shortcut_audit: bool = True
    shortcut_audit_flag_accuracy: float = 0.72


class PromptsCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dir: str = str(DEFAULT_PROMPTS)


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: ProjectCfg = Field(default_factory=ProjectCfg)
    corpus: CorpusCfg = Field(default_factory=CorpusCfg)
    passage: PassageCfg = Field(default_factory=PassageCfg)
    extraction: ExtractionCfg = Field(default_factory=ExtractionCfg)
    blueprint: BlueprintCfg = Field(default_factory=BlueprintCfg)
    claims: ClaimsCfg = Field(default_factory=ClaimsCfg)
    variants: VariantsCfg = Field(default_factory=VariantsCfg)
    hnsw: HnswCfg = Field(default_factory=HnswCfg)
    validation: ValidationCfg = Field(default_factory=ValidationCfg)
    splits: SplitsCfg = Field(default_factory=SplitsCfg)
    execution: ExecutionCfg = Field(default_factory=ExecutionCfg)
    llm: LlmCfg = Field(default_factory=LlmCfg)
    quality: QualityCfg = Field(default_factory=QualityCfg)
    prompts: PromptsCfg = Field(default_factory=PromptsCfg)

    # ------------------------------------------------------------------ #
    @property
    def data_dir(self) -> Path:
        p = Path(self.project.output_dir)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def prompts_dir(self) -> Path:
        p = Path(self.prompts.dir)
        return p if p.is_absolute() else REPO_ROOT / p

    def api_key(self) -> str | None:
        return os.environ.get(self.llm.api_key_env) or None

    def config_hash(self) -> str:
        from .util import sha256_json

        return sha256_json(self.model_dump(mode="json"))

    def fingerprint(self) -> dict[str, Any]:
        """Non-secret summary safe to log and embed in dataset metadata."""
        return {
            "config_hash": self.config_hash(),
            "models": {
                "generator": self.llm.generator.name,
                "extractor": self.llm.extractor.name,
                "claims": self.llm.claims.name,
                "editor": self.llm.editor.name,
                "validator": self.llm.validator.name,
                "validator_second": self.llm.validator_second.name,
            },
            "seed": self.project.seed,
            "labels": list(self.variants.required_labels),
            "language": self.project.language,
        }


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> Config:
    """Load YAML config, then apply environment overrides, then explicit overrides."""
    _load_dotenv(REPO_ROOT / ".env")
    raw: dict = {}
    p = Path(path) if path else DEFAULT_CONFIG
    if p.exists():
        with p.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    elif path:
        raise FileNotFoundError(f"config not found: {p}")

    env: dict = {}
    if os.environ.get("LLM_BASE_URL"):
        env.setdefault("llm", {})["base_url"] = os.environ["LLM_BASE_URL"]
    if os.environ.get("LLM_MODEL"):
        # LLM_MODEL is the default creative model; stage-specific models live in config.
        for stage in ("generator", "editor"):
            env.setdefault("llm", {}).setdefault(stage, {})["name"] = os.environ["LLM_MODEL"]
    max_tokens = os.environ.get("LLM_MAX_TOKENS") or os.environ.get("MAX_TOKENS")
    if max_tokens:
        try:
            mt = int(max_tokens)
        except ValueError:
            mt = 0
        if mt > 0:
            for stage in ("generator", "extractor", "claims", "editor", "validator", "validator_second"):
                env.setdefault("llm", {}).setdefault(stage, {})["max_tokens"] = mt
    if os.environ.get("TRISTATE_DATA_DIR"):
        env.setdefault("project", {})["output_dir"] = os.environ["TRISTATE_DATA_DIR"]
    if os.environ.get("TRISTATE_PROMPTS_DIR"):
        env.setdefault("prompts", {})["dir"] = os.environ["TRISTATE_PROMPTS_DIR"]
    if os.environ.get("OLLAMA_BASE_URL"):
        env.setdefault("hnsw", {})["ollama_base_url"] = os.environ["OLLAMA_BASE_URL"]
    if os.environ.get("EMBED_MODEL"):
        env.setdefault("hnsw", {})["ollama_model"] = os.environ["EMBED_MODEL"]

    merged = _deep_merge(_deep_merge(raw, env), overrides or {})
    return Config.model_validate(merged)
