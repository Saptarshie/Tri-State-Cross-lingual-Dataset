"""Versioned dataset exports.

The canonical export is one nested family record per line. A flattened one-row-per-
variant file is produced alongside it for training convenience, but is explicitly not
the source of truth.
"""

from __future__ import annotations

import json
from typing import Any

from .config import Config
from .schema import Family, LABELS
from .store import Store
from .util import atomic_write_json, atomic_write_text, read_json, sha256_text, utcnow


def _safe_read_families(store: Store, split: str | None = None) -> tuple[list[Family], list[str]]:
    families: list[Family] = []
    problems: list[str] = []
    for row in store.list_families(status="ACCEPTED", split=split):
        raw = store.load_family(row["family_id"])
        if not raw:
            problems.append(f"{row['family_id']}: file missing")
            continue
        try:
            fam = Family.model_validate(raw)
        except Exception as exc:
            problems.append(f"{row['family_id']}: invalid record: {exc}")
            continue
        families.append(fam)
    return families, problems


def export_dataset(
    store: Store,
    cfg: Config,
    version: str | None = None,
    split: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    families, problems = _safe_read_families(store, split)
    if not families and not dry_run:
        raise RuntimeError("no accepted families to export")

    stamp = utcnow().replace("-", "").replace(":", "").replace("T", "-")[:15]
    version = version or f"ds-{stamp}-{cfg.config_hash()[:8]}"
    out_dir = store.data_dir / "exports" / version
    if out_dir.exists() and (out_dir / "manifest.json").exists() and not dry_run:
        suffix = 1
        while (store.data_dir / "exports" / f"{version}-{suffix}").exists():
            suffix += 1
        version = f"{version}-{suffix}"
        out_dir = store.data_dir / "exports" / version

    nested_path = out_dir / "families.jsonl"
    flat_path = out_dir / "variants.jsonl"
    claims_path = out_dir / "claims.jsonl"

    nested_lines: list[str] = []
    flat_rows: list[dict[str, Any]] = []
    claim_rows: list[dict[str, Any]] = []
    label_counts = {label: 0 for label in LABELS}
    for fam in families:
        nested_lines.append(json.dumps(fam.model_dump(mode="json"), ensure_ascii=False))
        for row in fam.flattened_rows():
            flat_rows.append(row)
            label_counts[row["label"]] += 1
        for claim in fam.claim_set:
            claim_rows.append(
                {
                    "family_id": fam.family_id,
                    "split": fam.split,
                    "language": fam.language,
                    "claim_id": claim.claim_id,
                    "claim_text": claim.claim_text,
                    "claim_type": claim.claim_type,
                    "difficulty": claim.difficulty,
                    "intent": claim.intent,
                    "fact_ids": claim.fact_ids,
                    "evidence": [s.model_dump(mode="json") for s in claim.evidence_spans],
                }
            )

    split_counts: dict[str, int] = {}
    for fam in families:
        split_counts[fam.split] = split_counts.get(fam.split, 0) + 1

    manifest = {
        "dataset_version": version,
        "created_at": utcnow(),
        "config_hash": cfg.config_hash(),
        "language": cfg.project.language,
        "schema_version": "0.1.0",
        "counts": {
            "families": len(families),
            "variants": len(flat_rows),
            "claims": len(claim_rows),
            "by_label": label_counts,
            "by_split": split_counts,
        },
        "files": {
            "families": nested_path.name,
            "variants": flat_path.name,
            "claims": claims_path.name,
        },
        "problems": problems,
        "generation_models": {
            "generator": cfg.llm.generator.name,
            "extractor": cfg.llm.extractor.name,
            "claims": cfg.llm.claims.name,
            "editor": cfg.llm.editor.name,
            "validator": cfg.llm.validator.name,
        },
        "notes": [
            "One row per accepted passage family; the three variants share one claim set.",
            "variants.jsonl is a flattened training view, not the source of truth.",
            "Labels are context-relative; passages may be synthetic or counterfactual.",
        ],
    }

    if dry_run:
        return {"version": version, "dry_run": True, "manifest": manifest}

    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(nested_path, "\n".join(nested_lines) + "\n")
    atomic_write_text(flat_path, "\n".join(json.dumps(r, ensure_ascii=False) for r in flat_rows) + "\n")
    atomic_write_text(claims_path, "\n".join(json.dumps(r, ensure_ascii=False) for r in claim_rows) + "\n")
    for path in (nested_path, flat_path, claims_path):
        manifest.setdefault("hashes", {})[path.name] = sha256_text(path.read_text(encoding="utf-8"))
    atomic_write_json(out_dir / "manifest.json", manifest)
    splits_src = store.data_dir / "splits" / "assignments.json"
    if splits_src.exists():
        atomic_write_json(out_dir / "splits.json", read_json(splits_src, default={}))
    atomic_write_text(out_dir / "README.md", _readme(manifest, cfg))

    store._exec(
        "INSERT OR REPLACE INTO export_versions(version,created_at,path,split_counts,config_hash) "
        "VALUES(?,?,?,?,?)",
        (version, manifest["created_at"], str(out_dir), json.dumps(split_counts), cfg.config_hash()),
    )
    return {"version": version, "path": str(out_dir), "manifest": manifest}


def _readme(manifest: dict[str, Any], cfg: Config) -> str:
    return f"""# Tri-state counterfactual dataset {manifest['dataset_version']}

One row in `families.jsonl` is one indivisible instance: a fixed atomic claim set
({cfg.claims.min_claims_per_family}-{cfg.claims.max_claims_per_family} claims) evaluated against three
passage variants.

## Labels

| Variant | Requirement |
|---|---|
| SUPPORTED | the passage establishes every claim |
| CONTRADICTED | the passage explicitly contradicts every claim |
| UNSUPPORTED | the passage neither establishes nor contradicts any claim |

Labels describe the relation between the passage and the claims only. Passages may be
synthetic or counterfactual; real-world truth is explicitly *not* a criterion.

## Files

- `families.jsonl` — canonical nested records, one per family (all three variants).
- `variants.jsonl` — flattened view, one row per variant, for training.
- `claims.jsonl` — claim table with evidence spans.
- `manifest.json` — counts, hashes, model versions, config hash.

## Splitting

Splits are assigned per family (`family_id`, `split_group_id`) before export. Never split
by variant: the three variants are one unit. The test split is locked in `splits.json`.

## Provenance

Each family records generator/extractor/editor/validator models, prompt versions, config
hash, raw-call references and edit logs (with character offsets and unified diffs).
"""
