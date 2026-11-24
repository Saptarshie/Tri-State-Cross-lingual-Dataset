from __future__ import annotations

from tristate.graphdiff import diff_graph
from tristate.schema import Claim, Fact, SemanticRepresentation, Span


def _span(text="span"):
    return Span(sentence_id="S1", start_char=0, end_char=max(1, len(text)), text=text)


def _fact(fid, s, p, o):
    return Fact(fact_id=fid, subject=s, predicate=p, object=o, source_spans=[_span()], confidence=0.9)


def _sem(*facts):
    return SemanticRepresentation(summary="x", facts=list(facts))


def _claims():
    return [
        Claim(claim_id="C1", claim_text="VoltEdge cost 0.84 per mile.", fact_ids=["F1"], evidence_spans=[_span()]),
        Claim(claim_id="C2", claim_text="Charging took 3.5 hours.", fact_ids=["F2"], evidence_spans=[_span()]),
    ]


BASE = _sem(
    _fact("F1", "VoltEdge buses", "has_operating_cost", "0.84"),
    _fact("F2", "Depot charging", "required", "3.5 hours"),
    _fact("F9", "CCTA", "assigned", "120-mile routes"),
)


def test_supported_same_values_pass():
    variant = _sem(
        _fact("F1", "VoltEdge buses", "operating_cost", "0.84 per mile"),
        _fact("F2", "Depot charging", "required", "3.5 hours"),
        _fact("F9", "CCTA", "assigned", "120-mile routes"),
    )
    res = diff_graph(BASE, variant, _claims(), "SUPPORTED")
    assert res["per_claim"]["C1"]["status"] == "ok"
    assert res["per_claim"]["C2"]["status"] == "ok"
    assert res["ok"] and res["unrelated_stability"] == 1.0


def test_contradicted_different_value_passes():
    variant = _sem(
        _fact("F1", "VoltEdge buses", "operating_cost", "1.06 per mile"),
        _fact("F2", "Depot charging", "required", "45 minutes"),
        _fact("F9", "CCTA", "assigned", "120-mile routes"),
    )
    res = diff_graph(BASE, variant, _claims(), "CONTRADICTED")
    assert res["ok"], res


def test_unsupported_missing_evidence_passes():
    variant = _sem(
        _fact("F1", "VoltEdge buses", "operating_cost", "tracked during pilot"),
        _fact("F9", "CCTA", "assigned", "120-mile routes"),
    )
    res = diff_graph(BASE, variant, _claims(), "UNSUPPORTED")
    assert res["ok"], res


def test_unsupported_with_supporting_fact_is_a_miss():
    variant = _sem(_fact("F1", "VoltEdge buses", "operating_cost", "0.84"))
    res = diff_graph(BASE, variant, _claims(), "UNSUPPORTED")
    assert not res["ok"]
    assert "C1" in res["misses"]


def test_supported_without_evidence_is_a_miss():
    variant = _sem(_fact("F9", "CCTA", "assigned", "120-mile routes"))
    res = diff_graph(BASE, variant, _claims(), "SUPPORTED")
    assert not res["ok"]
    assert "C1" in res["misses"] and "C2" in res["misses"]


def test_reversed_relation_is_neutral_not_contradiction():
    variant = _sem(
        _fact("F1", "0.84", "operating_cost_of", "VoltEdge buses"),
        _fact("F2", "3.5 hours", "required_by", "Depot charging"),
    )
    res = diff_graph(BASE, variant, _claims(), "CONTRADICTED")
    # voice-swapped extraction is a paraphrase, not an incompatible value
    assert res["per_claim"]["C1"]["incompatible"] == 0
    assert res["per_claim"]["C1"]["same"] == 0
    assert not res["ok"]  # and it cannot certify a contradiction either


def test_unrelated_fact_changes_are_reported():
    variant = _sem(
        _fact("F1", "VoltEdge buses", "has_operating_cost", "0.84"),
        _fact("F2", "Depot charging", "required", "3.5 hours"),
    )
    res = diff_graph(BASE, variant, _claims(), "SUPPORTED")
    assert res["ok"]
    assert res["unrelated_total"] == 1
    assert res["unrelated_changed"] == 1
