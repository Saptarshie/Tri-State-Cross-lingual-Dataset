from __future__ import annotations

from tristate.novelty import NoveltyService
from tristate.schema import (
    Claim,
    EditLog,
    Fact,
    Family,
    PassageRecord,
    SemanticRepresentation,
    Span,
    Variant,
)
from tristate.store import Store
from tristate.util import approx_tokens, sha256_text

BASE = (
    "The Calder City Transit Authority launched a yearlong bus pilot in March 2025. "
    "VoltEdge buses averaged 0.84 dollars per mile while H2Cruiser buses averaged 1.17 dollars per mile. "
    "Depot charging required 3.5 hours per bus and hydrogen refuelling took 18 minutes."
)


def _span(text="Calder City Transit Authority"):
    return Span(sentence_id="S1", start_char=0, end_char=len(text), text=text)


def _variant(label, text):
    return Variant(
        variant_id=f"V_{label[0]}_000001",
        label=label,  # type: ignore[arg-type]
        text=text,
        token_count=approx_tokens(text),
        checksum=sha256_text(text),
        edit_history=EditLog(base_checksum="b", result_checksum="r"),
    )


def _family(fid="FAM_000001", split="train", status="ACCEPTED"):
    claim = Claim(
        claim_id="C1", claim_text="VoltEdge buses averaged 0.84 dollars per mile.",
        fact_ids=["F1"], evidence_spans=[_span()], claim_type="NUMERICAL",
    )
    fact = Fact(
        fact_id="F1", subject="VoltEdge buses", predicate="operating_cost", object="0.84",
        source_spans=[_span()], confidence=0.9,
    )
    return Family(
        family_id=fid,
        split_group_id=f"GROUP_{fid[-6:]}",
        blueprint={
            "blueprint_id": "BP_0000000001",
            "topic_path": ["Technology", "Transit"],
            "main_concept": "A battery-electric bus pilot in a mid-sized city.",
            "planned_relation_types": ["operating_cost"],
        },
        base_passage=PassageRecord(
            passage_id="P_000001", text=BASE, genre="news_report",
            tone="concise_journalistic", structure="paragraph",
        ),
        semantic_representation=SemanticRepresentation(summary="Bus pilot costs.", facts=[fact], entities=[]),
        claim_set=[claim],
        variants={
            "SUPPORTED": _variant("SUPPORTED", BASE),
            "CONTRADICTED": _variant("CONTRADICTED", BASE.replace("0.84", "1.06").replace("3.5 hours", "45 minutes")),
            "UNSUPPORTED": _variant("UNSUPPORTED", "The authority studied bus options and tracked operating costs during the pilot."),
        },
        quality={"status": status, "hard_checks_passed": True},
        split=split,
    )


def test_accepted_family_is_indexed_in_all_namespaces(cfg):
    store = Store(cfg.data_dir)
    try:
        svc = NoveltyService(store, cfg)
        svc.add_family(_family())
        assert svc.indexes["blueprint"].size == 1
        assert svc.indexes["passage"].size == 4  # 3 variants + base
        assert svc.indexes["fact_claim"].size == 1
        assert svc.indexes["edit_signature"].size == 3
        assert svc.stats["genres"]["news_report"] == 1
    finally:
        store.close()


def test_rejected_family_is_not_indexed(cfg):
    store = Store(cfg.data_dir)
    try:
        svc = NoveltyService(store, cfg)
        svc.add_family(_family(status="REJECTED"))
        assert svc.indexes["passage"].size == 0
    finally:
        store.close()


def test_pre_generation_report_has_guidance(cfg):
    store = Store(cfg.data_dir)
    try:
        svc = NoveltyService(store, cfg)
        report = svc.pre_generation_report("Technology > Transit | bus costs", ["Technology", "Transit"])
        assert "guidance" in report and report["suggested"]["genre"]
        assert report["max_similarity"] == 0.0
        svc.add_family(_family())
        report2 = svc.pre_generation_report(BASE, ["Technology", "Transit"])
        assert report2["max_similarity"] > 0.0
        assert report2["similar_passages"]
    finally:
        store.close()


def test_post_generation_detects_exact_duplicate(cfg):
    store = Store(cfg.data_dir)
    try:
        svc = NoveltyService(store, cfg)
        svc.add_family(_family())
        dup = svc.post_generation_check(BASE)
        assert dup["exact_duplicate"] is True
        assert dup["near_duplicate"] is True
        # punctuation-only difference is not an exact duplicate but is still near
        variant = svc.post_generation_check("An unrelated sentence about municipal water treatment.")
        assert variant["exact_duplicate"] is False
    finally:
        store.close()


def test_test_split_is_excluded_from_retrieval(cfg):
    store = Store(cfg.data_dir)
    try:
        svc = NoveltyService(store, cfg)
        svc.add_family(_family(split="test"))
        assert svc.indexes["passage"].size == 4
        check = svc.post_generation_check(BASE)
        assert check["max_cosine"] == 0.0
        assert check["near_duplicate"] is False
    finally:
        store.close()


def test_rebuild_from_families(cfg):
    store = Store(cfg.data_dir)
    try:
        svc = NoveltyService(store, cfg)
        result = svc.rebuild([_family("FAM_000001"), _family("FAM_000002")])
        assert result["families_indexed"] == 2
        assert result["vectors"]["passage"] == 8
    finally:
        store.close()
