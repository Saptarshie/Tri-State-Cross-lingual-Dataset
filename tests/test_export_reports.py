from __future__ import annotations

import json

from tristate.export import export_dataset
from tristate.pipeline import Pipeline
from tristate.reports import build_quality_report, write_reports


def _families(cfg, limit=2):
    p = Pipeline(cfg, mock=True, log=lambda m: None)
    p.run(limit=limit, seed_topic="Technology")
    return p


def test_export_writes_nested_and_flattened_views(cfg):
    p = _families(cfg)
    try:
        result = export_dataset(p.store, cfg)
        out = p.store.data_dir / "exports" / result["version"]
        assert (out / "families.jsonl").exists()
        assert (out / "variants.jsonl").exists()
        assert (out / "claims.jsonl").exists()
        assert (out / "manifest.json").exists()
        nested = [json.loads(l) for l in (out / "families.jsonl").read_text().splitlines() if l.strip()]
        flat = [json.loads(l) for l in (out / "variants.jsonl").read_text().splitlines() if l.strip()]
        assert len(nested) >= 1
        assert len(flat) == 3 * len(nested)
        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["counts"]["families"] == len(nested)
        assert manifest["counts"]["by_label"]["SUPPORTED"] == len(nested)
        assert all(r["claim_ids"] for r in flat)
    finally:
        p.close()


def test_export_is_versioned(cfg):
    p = _families(cfg, limit=1)
    try:
        a = export_dataset(p.store, cfg, version="v-test")
        b = export_dataset(p.store, cfg, version="v-test")
        assert a["path"] != b["path"]
        assert b["version"].startswith("v-test")
    finally:
        p.close()


def test_report_has_core_sections(cfg):
    p = _families(cfg, limit=2)
    try:
        report = build_quality_report(p.store, cfg, include_audit=True)
        for key in ("families", "acceptance", "dataset", "validation", "novelty", "cost", "calls"):
            assert key in report
        assert report["families"] >= 1
        assert report["dataset"]["claim_types"]
        assert report["shortcut_audit"]["status"] in {"ok", "insufficient_data"}
        written = write_reports(p.store, cfg)
        assert (p.store.data_dir / "reports" / "quality.md").exists()
        assert written["families"] == report["families"]
    finally:
        p.close()


def test_export_rejects_duplicate_jsonl_states(cfg):
    p = _families(cfg, limit=1)
    try:
        result = export_dataset(p.store, cfg)
        out = p.store.data_dir / "exports" / result["version"]
        rows = [json.loads(l) for l in (out / "families.jsonl").read_text().splitlines() if l.strip()]
        fam = rows[0]
        assert fam["claim_set"] and len(fam["variants"]) == 3
        assert fam["quality"]["status"] == "ACCEPTED"
    finally:
        p.close()
