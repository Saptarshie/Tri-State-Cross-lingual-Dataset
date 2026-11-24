from __future__ import annotations

import json

from tristate.config import load_config
from tristate.pipeline import Pipeline
from tristate.schema import Family, LABELS
from tristate.util import approx_tokens


def _run(cfg, limit=1, topic="Technology", **kw):
    p = Pipeline(cfg, mock=True, log=lambda m: None)
    summary = p.run(limit=limit, seed_topic=topic, **kw)
    return p, summary


def test_mock_pipeline_produces_valid_family(cfg):
    p, summary = _run(cfg)
    try:
        assert summary.accepted == 1, summary.as_dict()
        rows = p.store.list_families(status="ACCEPTED")
        assert len(rows) == 1
        fam = Family.model_validate(p.store.load_family(rows[0]["family_id"]))
        assert set(fam.variants) == set(LABELS)
        assert fam.split in {"train", "validation", "test"}
        assert fam.quality.hard_checks_passed
        # claim set identical across variants (one shared claim set + relation rows)
        for label, v in fam.variants.items():
            assert v.validation is not None and v.validation.status == "PASS"
            assert sorted(r.claim_id for r in v.relations_by_claim) == sorted(fam.claim_ids)
        # lineage / edit provenance
        assert fam.variants["SUPPORTED"].edit_history.attempts >= 1
        assert fam.variants["CONTRADICTED"].edit_history.entries
        assert "diff" in fam.variants["CONTRADICTED"].edit_history.unified_diff or "--" in fam.variants["CONTRADICTED"].edit_history.unified_diff
        # split group is family level
        assert fam.split_group_id.startswith("GROUP_")
        # generation metadata
        assert fam.generation.prompt_versions["validate"].startswith("1.")
        assert fam.generation.config_hash == cfg.config_hash()
    finally:
        p.close()


def test_stage_artifacts_are_durable(cfg):
    p, summary = _run(cfg)
    try:
        row = next(r for r in p.store.list_candidates() if r["status"] == "ACCEPTED")
        cid = row["candidate_id"]
        for name in ["candidate", "blueprint", "passage", "extract", "claims", "base_check",
                     "variant_SUPPORTED", "variant_CONTRADICTED", "variant_UNSUPPORTED",
                     "validation_SUPPORTED", "validation_CONTRADICTED", "validation_UNSUPPORTED",
                     "hard_checks", "novelty"]:
            assert (p.store.workdir(cid) / f"{name}.json").exists(), name
        assert p.store.job_status(cid, "accept") == "SUCCEEDED"
    finally:
        p.close()


def test_rerun_does_not_duplicate_families(cfg):
    p, first = _run(cfg)
    try:
        assert first.accepted == 1
        second = p.run(limit=1, seed_topic="Technology")
        assert second.accepted == 0
        assert len(p.store.list_families(status="ACCEPTED")) == 1
    finally:
        p.close()


def test_resume_from_partial_stage(cfg):
    p, partial = _run(cfg, stop_after="variants")
    try:
        assert partial.accepted == 0
        assert not p.store.list_families(status="ACCEPTED")
        assert p.novelty.indexes["passage"].size == 0  # index only after acceptance
        rows = p.store.list_candidates()
        assert rows and rows[0]["status"] == "PENDING"
        resumed = p.run(limit=1, candidates=rows)
        assert resumed.accepted == 1
        assert p.novelty.indexes["passage"].size == 4  # 3 variants + base
    finally:
        p.close()


def test_split_assignment_covers_all_variants(cfg):
    p, _ = _run(cfg)
    try:
        rows = p.store.list_families(status="ACCEPTED")
        fid = rows[0]["family_id"]
        fam = Family.model_validate(p.store.load_family(fid))
        assignment = p.splits.data["assignments"][fid]
        assert fam.split == assignment["split"]
        assert fam.split_group_id == assignment["group_id"]
        # every variant belongs to the same family split by construction
        assert all(v.label in LABELS for v in fam.variants.values())
    finally:
        p.close()


def test_same_topic_families_share_lineage_group(cfg):
    p, summary = _run(cfg, limit=2, topic="Technology")
    try:
        assert summary.accepted >= 1
        rows = p.store.list_families(status="ACCEPTED")
        # candidates from one topic belong to one lineage group (split-leakage guard)
        assert len({r["split_group_id"] for r in rows}) == 1
    finally:
        p.close()


def test_graph_diff_extraction_failure_is_advisory(cfg, monkeypatch):
    import tristate.pipeline as pl
    from tristate.errors import StageError

    original = pl.extract_semantics

    def fake_extract(llm, cfg_, text, candidate_id=None, stage="extract", feedback="", **kwargs):
        if stage.startswith("extract_"):
            raise StageError("extraction_insufficient", "forced graph-diff extraction failure")
        return original(llm, cfg_, text, candidate_id=candidate_id, stage=stage, feedback=feedback, **kwargs)

    monkeypatch.setattr(pl, "extract_semantics", fake_extract)
    p, summary = _run(cfg)
    try:
        assert summary.accepted == 1, summary.as_dict()
        cid = next(r["candidate_id"] for r in p.store.list_candidates() if r["status"] == "ACCEPTED")
        diffs = json.loads((p.store.workdir(cid) / "graphdiff.json").read_text())
        assert set(diffs) == set(LABELS)
        assert all(d["status"] == "unavailable" and d["ok"] is None for d in diffs.values())
        fam = Family.model_validate(p.store.load_family(p.store.list_families()[0]["family_id"]))
        assert all(v.graph_diff["status"] == "unavailable" for v in fam.variants.values())
    finally:
        p.close()


def test_long_form_pipeline_writes_sectioned_document(cfg_long):
    p = Pipeline(cfg_long, mock=True, log=lambda m: None)
    try:
        summary = p.run(limit=1, seed_topic="Technology", stop_after="passage")
        assert summary.accepted == 0
        rows = p.store.list_candidates()
        cid = rows[0]["candidate_id"]
        plan_raw = p.store.load_artifact(cid, "document_plan")
        doc = p.store.load_artifact(cid, "passage")
        assert plan_raw and doc
        assert len(plan_raw["sections"]) >= cfg_long.passage.sections_min
        assert len(doc["sections"]) == len(plan_raw["sections"])
        text = doc["text"]
        assert approx_tokens(text) >= cfg_long.passage.target_tokens_min * cfg_long.passage.min_document_ratio
        for sec in doc["sections"]:
            assert text[sec["start_char"]:sec["end_char"]]
            assert sec["token_count"] > 0
        assert doc["meta"]["tokens"] == approx_tokens(text)
    finally:
        p.close()


def test_quarantine_records_stage_and_reason(tmp_path):
    cfg = load_config(
        overrides={
            "project": {"output_dir": str(tmp_path / "data")},
            "hnsw": {"embedder": "hashing"},
            "execution": {"max_concurrency": 1},
            "claims": {"min_claims_per_family": 6, "max_claims_per_family": 6},
        }
    )
    p = Pipeline(cfg, mock=True, log=lambda m: None)
    try:
        summary = p.run(limit=1, seed_topic="Technology")
        assert summary.quarantined >= 1 and summary.accepted == 0
        rows = p.store.list_candidates()
        assert rows[0]["status"] == "QUARANTINED"
        q = json.loads((cfg.data_dir / "quarantine" / f"{rows[0]['candidate_id']}.json").read_text())
        assert q["reasons"]
    finally:
        p.close()
