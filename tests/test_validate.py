from __future__ import annotations

import json
from typing import Any

import pytest

from tristate.errors import StageError
from tristate.schema import Claim, SemanticRepresentation, Span
from tristate.validate import (
    family_hard_checks,
    summarise_family_validation,
    validate_passage,
    verify_base_claims,
)


class FakeClient:
    """Returns canned validator payloads, keyed by prompt name."""

    def __init__(self, responses: dict[str, list[dict[str, Any]]]):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.calls: list[tuple[str, dict]] = []

    def structured(self, prompt_name, variables, schema, model_cfg, stage=None,
                   family_id=None, candidate_id=None):
        self.calls.append((prompt_name, variables))
        queue = self.responses.get(prompt_name) or []
        payload = queue.pop(0) if len(queue) > 1 else (queue[0] if queue else {})
        data = schema.model_validate(payload)

        class R:
            pass

        r = R()
        r.data = data
        r.prompt_version = "fake-1.0"
        r.raw_ref = None
        r.usage = {}
        r.model = model_cfg.name
        return r


def _claims(n=2):
    return [
        Claim(
            claim_id=f"C{i + 1}",
            claim_text=f"Orion attribute {i + 1} was established by the passage.",
            fact_ids=["F1"],
            evidence_spans=[Span(sentence_id="S1", start_char=0, end_char=18, text="Orion is a system.")],
        )
        for i in range(n)
    ]


def _rel(claim_id, relation, conf=0.9, quote="Orion is a system."):
    return {
        "claim_id": claim_id,
        "relation": relation,
        "confidence": conf,
        "sentence_id": "S1",
        "quote": quote,
        "rationale": "test",
    }


BASE = (
    "Orion is a system used by analysts. It was developed by Alice Brown in 2012 "
    "and supports embedded deployments. The team released a second version later."
)


def test_supported_pass(cfg):
    client = FakeClient({"validate": [{"claim_relations": [_rel("C1", "ENTAILED"), _rel("C2", "ENTAILED")]}]})
    res = validate_passage(client, cfg, _claims(), BASE, "SUPPORTED", use_second=False)
    assert res.status == "PASS"
    assert res.observed_label() == "SUPPORTED"
    assert res.failures == []


def test_mixed_relations_fail(cfg):
    client = FakeClient({"validate": [{"claim_relations": [_rel("C1", "ENTAILED"), _rel("C2", "NEUTRAL")]}]})
    res = validate_passage(client, cfg, _claims(), BASE, "SUPPORTED", use_second=False)
    assert res.status == "FAIL"
    assert any("C2" in f for f in res.failures)
    assert res.observed_label() is None


def test_contradicted_pass(cfg):
    client = FakeClient({"validate": [{"claim_relations": [_rel("C1", "CONTRADICTED"), _rel("C2", "CONTRADICTED")]}]})
    res = validate_passage(client, cfg, _claims(), BASE, "CONTRADICTED", use_second=False)
    assert res.status == "PASS" and res.observed_label() == "CONTRADICTED"


def test_unsupported_requires_neutral_for_all(cfg):
    client = FakeClient({"validate": [{"claim_relations": [_rel("C1", "NEUTRAL"), _rel("C2", "CONTRADICTED")]}]})
    res = validate_passage(client, cfg, _claims(), BASE, "UNSUPPORTED", use_second=False)
    assert res.status == "FAIL"


def test_low_confidence_triggers_second_validator_and_disagreement_fails(cfg):
    client = FakeClient(
        {
            "validate": [{"claim_relations": [_rel("C1", "ENTAILED", 0.3), _rel("C2", "ENTAILED", 0.3)]}],
            "validate_second": [{"claim_relations": [_rel("C1", "NEUTRAL", 0.9), _rel("C2", "ENTAILED", 0.9)]}],
        }
    )
    res = validate_passage(client, cfg, _claims(), BASE, "SUPPORTED")
    assert res.second_relations
    assert res.status == "FAIL"
    assert any("disagreement" in f for f in res.failures)
    assert [c[0] for c in client.calls].count("validate_second") == 1


def test_second_validator_not_called_when_disabled(cfg):
    client = FakeClient({"validate": [{"claim_relations": [_rel("C1", "ENTAILED", 0.2), _rel("C2", "ENTAILED", 0.2)]}]})
    validate_passage(client, cfg, _claims(), BASE, "SUPPORTED", use_second=False)
    assert {c[0] for c in client.calls} == {"validate"}


def test_verify_base_claims_keeps_only_entailed(cfg):
    client = FakeClient(
        {"validate": [{"claim_relations": [
            _rel("C1", "ENTAILED", 0.95),
            _rel("C2", "NEUTRAL", 0.9),
            _rel("C3", "ENTAILED", 0.9),
        ]}]}
    )
    kept, dropped, result = verify_base_claims(client, cfg, _claims(3), BASE)
    assert [c.claim_id for c in kept] == ["C1", "C2"]
    assert dropped and dropped[0]["claim_id"] == "C2"
    assert result.status == "FAIL"


def test_verify_base_claims_fails_when_too_few_survive(cfg):
    client = FakeClient(
        {"validate": [{"claim_relations": [_rel("C1", "ENTAILED"), _rel("C2", "NEUTRAL")]}]}
    )
    with pytest.raises(StageError) as exc:
        verify_base_claims(client, cfg, _claims(2), BASE)
    assert exc.value.code == "base_claims_unsupported"


def test_hard_checks_accept_balanced_variants(cfg):
    semantic = SemanticRepresentation(summary="Orion.", entities=[], facts=[])
    variants = {
        "SUPPORTED": BASE,
        "CONTRADICTED": BASE.replace("Alice Brown", "Bob Smith").replace("2012", "2004"),
        "UNSUPPORTED": "Orion is a system used by analysts. It supports embedded deployments and a second version exists.",
    }
    res = family_hard_checks(cfg, _claims(), BASE, variants, "synthetic", semantic)
    assert res["ok"], res["failures"]


def test_hard_checks_reject_truncated_unsupported(cfg):
    semantic = SemanticRepresentation(summary="Orion.", entities=[], facts=[])
    variants = {"SUPPORTED": BASE, "CONTRADICTED": BASE, "UNSUPPORTED": "Orion exists."}
    res = family_hard_checks(cfg, _claims(), BASE, variants, "synthetic", semantic)
    assert not res["ok"]
    assert "unsupported_not_truncated" in res["failures"] or "UNSUPPORTED_length_ratio" in res["failures"]


def test_hard_checks_reject_label_leak(cfg):
    semantic = SemanticRepresentation(summary="Orion.", entities=[], facts=[])
    leaky = BASE + " The passage does not mention the founder."
    variants = {"SUPPORTED": BASE, "CONTRADICTED": BASE, "UNSUPPORTED": leaky}
    res = family_hard_checks(cfg, _claims(), BASE, variants, "synthetic", semantic)
    assert not res["ok"]


def test_summary_reports_all_failures(cfg):
    client = FakeClient({"validate": [{"claim_relations": [_rel("C1", "ENTAILED"), _rel("C2", "NEUTRAL")]}]})
    res = validate_passage(client, cfg, _claims(), BASE, "SUPPORTED", use_second=False)
    ok, reasons = summarise_family_validation({"SUPPORTED": res}, {"ok": False, "failures": ["language_en"]})
    assert not ok
    assert any("language_en" in r for r in reasons)
    assert any(r.startswith("SUPPORTED") for r in reasons)


def test_no_world_truth_gate_by_default(cfg):
    assert cfg.validation.allow_world_truth_gate is False
    # fictional content that matches the passage must pass: no external check exists
    client = FakeClient({"validate": [{"claim_relations": [_rel("C1", "ENTAILED"), _rel("C2", "ENTAILED")]}]})
    res = validate_passage(client, cfg, _claims(), BASE, "SUPPORTED", use_second=False)
    assert res.status == "PASS"


def test_claims_payload_hides_intended_label(cfg):
    client = FakeClient({"validate": [{"claim_relations": [_rel("C1", "ENTAILED"), _rel("C2", "ENTAILED")]}]})
    validate_passage(client, cfg, _claims(), BASE, "SUPPORTED", use_second=False)
    _, variables = client.calls[0]
    rendered = json.dumps(variables)
    assert "SUPPORTED" not in rendered
    assert "intended" not in rendered.lower()
