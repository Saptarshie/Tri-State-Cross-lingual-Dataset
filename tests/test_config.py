from __future__ import annotations

import pytest
from pydantic import ValidationError

from tristate.config import load_config
from tristate.prompts import PromptError, PromptLibrary


def test_overrides_take_precedence(tmp_path):
    cfg = load_config(overrides={"project": {"output_dir": str(tmp_path / "out")}})
    assert cfg.data_dir == tmp_path / "out"
    assert cfg.llm.generator.name


def test_invalid_split_fractions_rejected():
    with pytest.raises(ValidationError):
        load_config(overrides={"splits": {"train": 0.7, "validation": 0.1, "test": 0.1}})


def test_label_set_must_be_exact():
    with pytest.raises(ValidationError):
        load_config(overrides={"variants": {"required_labels": ["SUPPORTED", "UNSUPPORTED"]}})


def test_claim_bounds_validated():
    with pytest.raises(ValidationError):
        load_config(overrides={"claims": {"min_claims_per_family": 5, "max_claims_per_family": 2}})


def test_env_model_and_token_overrides(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "test/generator-model")
    monkeypatch.setenv("LLM_MAX_TOKENS", "1234")
    cfg = load_config()
    assert cfg.llm.generator.name == "test/generator-model"
    assert cfg.llm.generator.max_tokens == 1234
    # stage-specific code models are not clobbered by LLM_MODEL
    assert cfg.llm.validator.name != "test/generator-model"


def test_config_hash_is_stable_and_sensitive():
    a = load_config()
    b = load_config()
    assert a.config_hash() == b.config_hash()
    c = load_config(overrides={"claims": {"max_claims_per_family": 4}})
    assert c.config_hash() != a.config_hash()


def test_prompts_load_and_render():
    lib = PromptLibrary(load_config().prompts_dir)
    assert "validate" in lib.names()
    rendered, version = lib.render(
        "topics_expand", topic_name="Databases", topic_description="x",
        existing_children="(none)", max_children=4, depth=1, max_depth=3,
        target_tokens_min=2000, target_tokens_max=4000,
    )
    assert "Databases" in rendered and "+" in version
    with pytest.raises(PromptError):
        lib.render("topics_expand", topic_name="x")


def test_prompt_values_can_contain_json_braces(tmp_path):
    src = tmp_path / "prompts"
    src.mkdir()
    (src / "p.md").write_text(
        "---\nversion: '1'\nstage: test\n---\nvalue={{value}}\n", encoding="utf-8"
    )
    lib = PromptLibrary(src)
    rendered, _ = lib.render("p", value='{"nested":{"ok":true}}')
    assert rendered.strip() == 'value={"nested":{"ok":true}}'


def test_prompt_versions_change_with_content(tmp_path):
    src = load_config().prompts_dir
    lib = PromptLibrary(src)
    v1 = lib.get("validate").full_version
    copy = tmp_path / "prompts"
    copy.mkdir()
    for p in src.glob("*.md"):
        (copy / p.name).write_text(p.read_text().replace("PASSAGE:", "PASSAGE TEXT:"), encoding="utf-8")
    lib2 = PromptLibrary(copy)
    assert lib2.get("validate").full_version != v1
