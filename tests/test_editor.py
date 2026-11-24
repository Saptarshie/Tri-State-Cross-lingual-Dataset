from __future__ import annotations

from typing import Any

import pytest

from tristate.editor import create_variant
from tristate.errors import StageError
from tristate.schema import Claim, SemanticRepresentation, Span

BASE = (
    "The Orion language was developed by Alice Brown in 2012. "
    "Orion uses a register-based virtual machine and was designed primarily for embedded applications. "
    "A second version shipped in 2015 with forty additional modules."
)


class FakeEditor:
    def __init__(self, plans: list[dict[str, Any]]):
        self.plans = list(plans)
        self.calls: list[dict] = []

    def structured(self, prompt_name, variables, schema, model_cfg, stage=None,
                   family_id=None, candidate_id=None):
        self.calls.append(variables)
        payload = self.plans.pop(0) if len(self.plans) > 1 else self.plans[0]
        data = schema.model_validate(payload)

        class R:
            pass

        r = R()
        r.data = data
        r.prompt_version = "fake"
        r.raw_ref = None
        r.usage = {}
        return r


def _claims():
    return [
        Claim(claim_id="C1", claim_text="Alice Brown developed Orion.",
              fact_ids=["F1"], evidence_spans=[Span(sentence_id="S1", start_char=0, end_char=5, text="Orion")]),
        Claim(claim_id="C2", claim_text="Orion was released in 2012.",
              fact_ids=["F2"], evidence_spans=[Span(sentence_id="S1", start_char=0, end_char=5, text="Orion")]),
    ]


def _plan(*patches):
    return {"patches": list(patches), "reasoning": "test"}


def _patch(op, sentence, original, replacement, claims):
    return {
        "operation": op,
        "target_sentence_id": sentence,
        "original_text": original,
        "replacement_text": replacement,
        "affected_claim_ids": claims,
        "reason": "test",
    }


def test_supported_without_patches_keeps_base():
    client = FakeEditor([_plan()])
    out = create_variant(client, _cfg(), "SUPPORTED", BASE, _claims(), SemanticRepresentation(summary="x"))
    assert out.text == BASE
    assert out.log.entries == [] and out.log.notes == ["unmodified_base"]


def test_coverage_gap_is_rejected_then_repaired(cfg):
    client = FakeEditor([
        _plan(_patch("ENTITY_SUBSTITUTION", "S1", "Alice Brown", "Bob Smith", ["C1"])),
        _plan(
            _patch("ENTITY_SUBSTITUTION", "S1", "Alice Brown", "Bob Smith", ["C1"]),
            _patch("TEMPORAL_MUTATION", "S1", "2012", "2008", ["C2"]),
        ),
    ])
    out = create_variant(client, cfg, "CONTRADICTED", BASE, _claims(), SemanticRepresentation(summary="x"))
    assert out.attempts == 2
    assert "Bob Smith" in out.text and "2008" in out.text
    assert "does not address" in client.calls[1]["feedback"]


def test_forbidden_operation_is_rejected(cfg):
    client = FakeEditor([
        _plan(_patch("DELETE_SPAN", "S1", "Alice Brown", "", ["C1"]),
              _patch("TEMPORAL_MUTATION", "S1", "2012", "2008", ["C2"])),
        _plan(
            _patch("ENTITY_SUBSTITUTION", "S1", "Alice Brown", "Bob Smith", ["C1"]),
            _patch("TEMPORAL_MUTATION", "S1", "2012", "2008", ["C2"]),
        ),
    ])
    out = create_variant(client, cfg, "CONTRADICTED", BASE, _claims(), SemanticRepresentation(summary="x"))
    assert out.attempts == 2
    assert "DELETE_SPAN" in client.calls[1]["feedback"]


def test_unapplicable_span_is_rejected_then_repaired(cfg):
    client = FakeEditor([
        _plan(_patch("ENTITY_SUBSTITUTION", "S1", "Alice Brown", "Bob Smith", ["C1"]),
              _patch("TEMPORAL_MUTATION", "S1", "1999", "2008", ["C2"])),
        _plan(
            _patch("ENTITY_SUBSTITUTION", "S1", "Alice Brown", "Bob Smith", ["C1"]),
            _patch("TEMPORAL_MUTATION", "S1", "2012", "2008", ["C2"]),
        ),
    ])
    out = create_variant(client, cfg, "CONTRADICTED", BASE, _claims(), SemanticRepresentation(summary="x"))
    assert out.attempts == 2
    assert "TARGET_NOT_FOUND" in client.calls[1]["feedback"]


def test_unsupported_rejects_value_mutation(cfg):
    client = FakeEditor([
        _plan(_patch("NUMERICAL_MUTATION", "S1", "2012", "2008", ["C1"]),
              _patch("DELETE_SPAN", "S2", " and was designed primarily for embedded applications", "", ["C2"])),
        _plan(
            _patch("REPLACE_CLAUSE", "S1", BASE.split(".")[0] + ".", "Orion is a tool with a small team.", ["C1"]),
            _patch("DELETE_SPAN", "S2", " and was designed primarily for embedded applications", "", ["C2"]),
        ),
    ])
    out = create_variant(client, cfg, "UNSUPPORTED", BASE, _claims(), SemanticRepresentation(summary="x"))
    assert out.attempts == 2
    assert "NUMERICAL_MUTATION" in client.calls[1]["feedback"]


def test_exhausted_attempts_raise(cfg):
    client = FakeEditor([_plan(_patch("ENTITY_SUBSTITUTION", "S1", "Alice Brown", "Bob Smith", ["C1"]))])
    with pytest.raises(StageError) as exc:
        create_variant(client, cfg, "CONTRADICTED", BASE, _claims(), SemanticRepresentation(summary="x"))
    assert exc.value.code == "edit_failed"


def test_unknown_claim_id_is_rejected(cfg):
    client = FakeEditor([
        _plan(_patch("ENTITY_SUBSTITUTION", "S1", "Alice Brown", "Bob Smith", ["C1", "C9"]),
              _patch("TEMPORAL_MUTATION", "S1", "2012", "2008", ["C2"])),
        _plan(
            _patch("ENTITY_SUBSTITUTION", "S1", "Alice Brown", "Bob Smith", ["C1"]),
            _patch("TEMPORAL_MUTATION", "S1", "2012", "2008", ["C2"]),
        ),
    ])
    out = create_variant(client, cfg, "CONTRADICTED", BASE, _claims(), SemanticRepresentation(summary="x"))
    assert out.attempts == 2
    assert "C9" in client.calls[1]["feedback"]


def _cfg():
    from tristate.config import load_config

    return load_config(overrides={"hnsw": {"embedder": "hashing"}})
