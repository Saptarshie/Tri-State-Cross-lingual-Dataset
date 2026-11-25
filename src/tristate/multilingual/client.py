"""Client construction for the translation branch.

By default this uses the same OpenAI-compatible credential as the English
factory, with DeepSeek model names.  The provider/base URL/key environment are
configurable, so a separately provisioned translation key is also supported.
The existing client gives both branches identical retries, caching, JSON
validation and call ledgers.
"""

from __future__ import annotations

from ..config import Config, ModelCfg
from ..llm import LlmClient, PermanentLlmError
from ..schema import Family
from .config import MultilingualCfg
from .ledger import preflight as source_preflight


def build_client(base: Config, ml: MultilingualCfg, run_id: str) -> LlmClient:
    cfg = base.model_copy(deep=True)
    ds = ml.deepseek
    if not ds.api_key():
        raise PermanentLlmError(
            f"missing translation API key: set ${ds.api_key_env}; the translation branch "
            "uses the configured OpenAI-compatible provider and will not silently fall back"
        )
    cfg.project.output_dir = str(ml.output_path)
    cfg.llm.base_url = ds.base_url
    cfg.llm.api_key_env = ds.api_key_env
    cfg.llm.json_mode = True
    cfg.llm.cache_enabled = True
    cfg.execution.max_retries = max(1, ds.max_retries)
    cfg.execution.request_timeout_s = ds.request_timeout_s
    common = ModelCfg(
        name=ds.model,
        temperature=ds.temperature,
        max_tokens=ds.max_tokens,
        cost_in_per_mtok=ds.cost_in_per_mtok,
        cost_out_per_mtok=ds.cost_out_per_mtok,
        extra_body=dict(ds.extra_body_generate),
    )
    review = ModelCfg(
        name=ds.review_model,
        temperature=ds.review_temperature,
        max_tokens=ds.max_tokens,
        cost_in_per_mtok=ds.cost_in_per_mtok,
        cost_out_per_mtok=ds.cost_out_per_mtok,
        extra_body=dict(ds.extra_body_review),
    )
    cfg.llm.generator = common
    cfg.llm.extractor = common.model_copy(update={"temperature": 0.0})
    cfg.llm.claims = common.model_copy(update={"temperature": 0.1})
    cfg.llm.validator = review
    cfg.llm.validator_second = review
    client = LlmClient(cfg, run_id=run_id)
    return client


def preflight(ml: MultilingualCfg) -> dict[str, object]:
    ds = ml.deepseek
    missing = [] if ds.api_key() else [ds.api_key_env]
    source_count = 0
    source_failures: list[dict[str, str]] = []
    families_dir = ml.source_path / "families"
    if not families_dir.exists():
        source_failures.append({"family_id": "", "error": f"missing source families: {families_dir}"})
    else:
        for path in sorted(families_dir.glob("FAM_*.json")):
            try:
                family = Family.model_validate_json(path.read_text(encoding="utf-8"))
                if family.quality.status != "ACCEPTED":
                    source_failures.append({"family_id": family.family_id, "error": f"quality {family.quality.status}"})
                    continue
                source_preflight(family)
                source_count += 1
            except Exception as exc:  # noqa: BLE001 - report every bad source, do not abort discovery
                source_failures.append({"family_id": path.stem, "error": str(exc)})
    return {
        "provider": "openai-compatible",
        "base_url": ds.base_url,
        "model": ds.model,
        "review_model": ds.review_model,
        "missing_env": missing,
        "profiles": [p.profile_id for p in ml.profiles],
        "source_dir": str(ml.source_path),
        "output_dir": str(ml.output_path),
        "source_families": source_count,
        "source_failures": source_failures[:20],
        "source_failure_count": len(source_failures),
        "ready": not missing and not source_failures,
    }
