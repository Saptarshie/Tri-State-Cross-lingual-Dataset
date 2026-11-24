from __future__ import annotations

from tristate.blueprint import choose_style
from tristate.config import load_config
from tristate.schema import BlueprintCandidate
from tristate.style import library, priming_block, style_fields


def _candidate(cid: str = "CAND_style_test") -> BlueprintCandidate:
    return BlueprintCandidate(
        candidate_id=cid,
        idempotency_key="style-test",
        topic_ids=["T_1"],
        topic_path=["Technology", "Reliability"],
    )


def test_every_configured_axis_has_directive_and_example():
    cfg = load_config()
    lib = library(cfg)
    for tone in cfg.blueprint.tones:
        entry = lib["tones"][tone]
        assert entry["directive"].strip()
        assert entry["example"]["output"].strip()
    for narrative in cfg.blueprint.narratives:
        entry = lib["narratives"][narrative]
        assert entry["directive"].strip()
        assert entry["example"]["output"].strip()


def test_style_is_deterministic_and_includes_narrative():
    cfg = load_config()
    first = choose_style(cfg, _candidate(), {})
    second = choose_style(cfg, _candidate(), {})
    assert first == second
    assert first["narrative"] in cfg.blueprint.narratives
    assert {"genre", "tone", "structure", "narrative", "complexity"} <= set(first)


def test_priming_contains_both_axes_and_conflict_example():
    cfg = load_config()
    style = {
        "genre": "encyclopedia_entry",
        "tone": "academic",
        "structure": "chaptered_explainer",
        "narrative": "humorous",
        "complexity": "advanced",
    }
    block = priming_block(cfg, style)
    assert "TONE — academic" in block
    assert "NARRATIVE — humorous" in block
    assert "COMPOSED EXAMPLE: academic x humorous" in block
    assert "Do not reuse their topics" in block
    fields = style_fields(cfg, style)
    assert fields["narrative"] == "humorous"
    assert "scholarly" in fields["tone_directive"].lower()
