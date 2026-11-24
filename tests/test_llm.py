from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from tristate.config import load_config
from tristate.llm import (
    BudgetExceeded,
    LlmClient,
    MockTransport,
    PermanentLlmError,
    SchemaViolation,
)

VARS = {
    "topic_name": "Databases",
    "topic_description": "Storage and query systems.",
    "existing_children": "(none)",
    "max_children": 4,
    "depth": 2,
    "max_depth": 4,
}


class Sub(BaseModel):
    name: str
    description: str = ""
    importance: float = 0.5


class Payload(BaseModel):
    subtopics: list[Sub] = []


def _client(cfg, responder, run_id="test-run"):
    transport = MockTransport(responder)
    client = LlmClient(cfg, run_id=run_id, transport=transport)
    return client, transport


def _valid():
    return {"subtopics": [{"name": "Indexing", "description": "B-trees", "importance": 0.7}]}


def test_structured_call_parses_json_and_sends_ua(cfg):
    client, transport = _client(cfg, lambda p: _valid())
    res = client.structured("topics_expand", VARS, Payload, cfg.llm.generator)
    assert isinstance(res.data, Payload)
    assert res.data.subtopics[0].name == "Indexing"
    assert "tristate" in transport.headers[0]["User-Agent"]
    assert res.usage["prompt_tokens"] == 100


def test_raw_response_is_checkpointed(cfg):
    client, _ = _client(cfg, lambda p: _valid(), run_id="run-ckpt")
    res = client.structured("topics_expand", VARS, Payload, cfg.llm.generator)
    assert res.raw_ref and Path(res.raw_ref).exists()
    raw = json.loads(Path(res.raw_ref).read_text())
    assert raw["request"]["model"] == cfg.llm.generator.name
    assert "Authorization" not in json.dumps(raw)


def test_cache_prevents_duplicate_network_calls(cfg_cached):
    client, transport = _client(cfg_cached, lambda p: _valid())
    a = client.structured("topics_expand", VARS, Payload, cfg_cached.llm.generator)
    b = client.structured("topics_expand", VARS, Payload, cfg_cached.llm.generator)
    assert len(transport.calls) == 1
    assert a.cached is False and b.cached is True


def test_transient_error_is_retried(cfg):
    state = {"n": 0}

    def responder(payload):
        state["n"] += 1
        if state["n"] == 1:
            return 503, {"error": {"message": "busy"}}
        return _valid()

    client, transport = _client(cfg, responder)
    res = client.structured("topics_expand", VARS, Payload, cfg.llm.generator)
    assert res.data.subtopics
    assert len(transport.calls) == 2


def test_permanent_error_is_not_retried(cfg):
    client, transport = _client(cfg, lambda p: (400, {"error": {"message": "bad request"}}))
    with pytest.raises(PermanentLlmError):
        client.structured("topics_expand", VARS, Payload, cfg.llm.generator)
    assert len(transport.calls) == 1


def test_schema_repair_round(cfg):
    state = {"n": 0}

    def responder(payload):
        state["n"] += 1
        return "not json at all" if state["n"] == 1 else _valid()

    client, transport = _client(cfg, responder)
    res = client.structured("topics_expand", VARS, Payload, cfg.llm.generator)
    assert res.attempts == 2
    assert len(transport.calls) == 2


def test_unrecoverable_schema_error_raises(cfg):
    client, transport = _client(cfg, lambda p: {"subtopics": [{"name": 5}]})
    with pytest.raises((SchemaViolation, PermanentLlmError)):
        client.structured("topics_expand", VARS, Payload, cfg.llm.generator)
    assert len(transport.calls) == 2  # original + one repair


def test_budget_guard_stops_run(tmp_path):
    cfg = load_config(
        overrides={
            "project": {"output_dir": str(tmp_path / "d")},
            "execution": {"max_total_cost_usd": 1e-9, "max_retries": 1, "backoff_base_s": 0.01},
            "llm": {
                "cache_enabled": False,
                "generator": {"cost_in_per_mtok": 10.0, "cost_out_per_mtok": 10.0},
            },
        }
    )
    client, transport = _client(cfg, lambda p: _valid())
    client.structured("topics_expand", VARS, Payload, cfg.llm.generator)
    with pytest.raises(BudgetExceeded):
        client.structured("topics_expand", VARS, Payload, cfg.llm.generator)
    assert len(transport.calls) == 1


def test_missing_api_key_fails_clearly(cfg, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    cfg.llm.api_key_env = "TRISTATE_DEFINITELY_UNSET_KEY"
    client, _ = _client(cfg, lambda p: _valid())
    with pytest.raises(PermanentLlmError) as exc:
        client.structured("topics_expand", VARS, Payload, cfg.llm.generator)
    assert "missing API key" in str(exc.value)
