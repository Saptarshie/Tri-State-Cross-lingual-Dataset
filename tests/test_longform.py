from __future__ import annotations

from tristate.claims import choose_claim_facts
from tristate.config import load_config
from tristate.editor import editing_view
from tristate.extract import _select_windows, split_windows
from tristate.longform import assemble, check_document, target_section_count, SectionDraft
from tristate.schema import (
    Claim,
    DocumentPlan,
    Fact,
    PassageSection,
    SectionPlan,
    SemanticRepresentation,
    Span,
)


def _long_text(sentences: int = 80) -> str:
    return " ".join(
        f"Sentence {i} records that system {i % 7} changed value {i * 3} during interval {i}."
        for i in range(sentences)
    )


def _plan(n: int = 3) -> DocumentPlan:
    return DocumentPlan(
        plan_id="DP_test",
        sections=[
            SectionPlan(
                section_id=f"S{i + 1}", title=f"T{i + 1}", purpose="p",
                target_tokens=200, key_points=["k"],
            )
            for i in range(n)
        ],
    )


def test_target_section_count_scales_to_long_targets():
    cfg = load_config(overrides={"passage": {"target_tokens_min": 10000, "target_tokens_max": 15000}})
    n = target_section_count(cfg)
    assert 15 <= n <= 24
    assert n * cfg.passage.section_tokens_min <= 15000


def test_split_windows_covers_document_and_respects_cap():
    text = _long_text(120)
    windows = split_windows(text, 200)
    assert len(windows) > 1
    assert windows[0][0] == 0
    assert windows[-1][1] == len(text)
    for (s1, e1), (s2, _) in zip(windows, windows[1:]):
        assert e1 == s2
    capped = _select_windows(windows, 3)
    assert len(capped) == 3


def test_assemble_round_trips_offsets():
    drafts = [
        SectionDraft(_plan(2).sections[0], "First section text."),
        SectionDraft(_plan(2).sections[1], "Second section text."),
    ]
    text, sections = assemble(drafts)
    assert text == "First section text.\n\nSecond section text."
    for sec, draft in zip(sections, drafts):
        assert text[sec.start_char:sec.end_char] == draft.text


def test_document_screening_flags_short_and_repetition(cfg):
    text = _long_text(2)
    problems = check_document(text, cfg)
    assert any(p.startswith("document too short") for p in problems)

    plan = _plan(2)
    repeated = "The same long sentence repeats exactly in both sections for the test."
    drafts = [SectionDraft(plan.sections[0], repeated), SectionDraft(plan.sections[1], repeated)]
    doc, sections = assemble(drafts)
    problems = check_document(doc, cfg, plan, sections)
    assert any("cross-section repetition" in p for p in problems)


def test_choose_claim_facts_spreads_across_sections(cfg):
    facts = []
    for i in range(8):
        span = Span(sentence_id=f"S{i + 1}", start_char=i * 10, end_char=i * 10 + 5, text="x")
        facts.append(
            Fact(
                fact_id=f"F{i + 1}", subject=f"Entity{i}", predicate=f"rel{i % 4}",
                object=f"value{i}", source_spans=[span], section_id=f"S{(i % 4) + 1}",
            )
        )
    semantic = SemanticRepresentation(summary="s", facts=facts)
    sections = [
        PassageSection(section_id=f"S{i}", start_char=i * 100, end_char=(i + 1) * 100, token_count=50)
        for i in range(1, 5)
    ]
    picked = choose_claim_facts(semantic, cfg, sections)
    assert len(picked) == cfg.claims.target_claims_per_document
    assert len({f.section_id for f in picked}) >= 2


def test_choose_claim_facts_still_fills_target_with_repeated_predicates(cfg):
    facts = [
        Fact(
            fact_id=f"F{i + 1}", subject="E", predicate="rel", object=f"v{i}",
            source_spans=[Span(sentence_id=f"S{(i % 4) + 1}", start_char=i * 10, end_char=i * 10 + 1, text="x")],
            section_id=f"S{(i % 4) + 1}",
        )
        for i in range(8)
    ]
    semantic = SemanticRepresentation(summary="s", facts=facts)
    picked = choose_claim_facts(semantic, cfg)
    assert len(picked) == cfg.claims.target_claims_per_document


def test_editing_view_is_local_for_long_documents(tmp_path):
    cfg = load_config(overrides={"passage": {"target_tokens_min": 2000, "target_tokens_max": 3000}})
    text = _long_text(200)
    claim = Claim(
        claim_id="C1", claim_text="System 3 changed value 33.",
        evidence_spans=[Span(sentence_id="S11", start_char=0, end_char=4, text="Sent")],
    )
    view = editing_view(text, [claim], cfg)
    assert 0 < len(view) < len(text.split("."))
    ids = {v["sentence_id"] for v in view}
    assert "S11" in ids
