"""CLI for the DeepSeek translation branch."""

from __future__ import annotations

import json
from typing import Any

from ..config import load_config as load_base_config
from .client import build_client, preflight
from .config import load_config
from .models import FamilyTranslation
from .pipeline import run_profile


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _load(args) -> tuple:
    overrides: dict[str, Any] = {}
    if getattr(args, "data_dir", None):
        overrides["source_dir"] = args.data_dir
    if getattr(args, "output_dir", None):
        overrides["output_dir"] = args.output_dir
    ml = load_config(getattr(args, "translation_config", None), overrides)
    base = load_base_config(getattr(args, "config", None))
    if getattr(args, "data_dir", None):
        base.project.output_dir = args.data_dir
    return ml, base


def cmd_translate(args) -> int:
    ml, base = _load(args)
    action = args.action
    if action == "profiles":
        print(_json([p.model_dump(mode="json") for p in ml.profiles]))
        return 0
    if action == "preflight":
        out = preflight(ml)
        print(_json(out))
        return 0 if out["ready"] else 2
    if action == "status":
        rows = []
        for p in ml.profiles:
            path = ml.output_path / p.profile_id / "manifest.json"
            if path.exists():
                rows.append(json.loads(path.read_text(encoding="utf-8")))
            else:
                rows.append({"profile_id": p.profile_id, "status": "not_started", "accepted": 0, "quarantined": 0})
        print(_json(rows))
        return 0
    if action == "run":
        if not ml.deepseek.api_key():
            print(_json({"error": f"missing ${ml.deepseek.api_key_env}; configure the translation provider credential", "preflight": preflight(ml)}))
            return 2
        client = build_client(base, ml, run_id=args.run_id)
        manifest = run_profile(
            ml,
            base,
            args.profile,
            client,
            limit=args.limit,
            concurrency=args.concurrency,
            retry_quarantined=args.retry_quarantined,
            run_id=args.run_id,
            family_id=getattr(args, "family_id", None),
        )
        print(_json(manifest.model_dump(mode="json")))
        return 0
    if action == "show":
        p = ml.output_path / args.profile / "families" / f"{args.family_id}.json"
        if not p.exists():
            p = ml.output_path / args.profile / "quarantine" / f"{args.family_id}.json"
        if not p.exists():
            print(_json({"error": f"not found: {args.family_id}"}))
            return 1
        print(p.read_text(encoding="utf-8"))
        return 0
    if action == "export":
        return _export(ml, args)
    print(_json({"error": f"unknown action: {action}"}))
    return 1


def _export(ml, args) -> int:
    profile = args.profile
    root = ml.output_path / profile / "families"
    rows = []
    for path in sorted(root.glob("*.json")):
        rec = FamilyTranslation.model_validate_json(path.read_text(encoding="utf-8"))
        if rec.status != "ACCEPTED":
            continue
        for variant in rec.variants:
            rows.append(
                {
                    "family_id": rec.family_id,
                    "split_group_id": rec.split_group_id,
                    "split": rec.split,
                    "language": rec.target_language,
                    "script": rec.target_script,
                    "profile_id": rec.profile_id,
                    "profile_version": rec.profile_version,
                    "label": variant.label,
                    "variant_id": variant.variant_id,
                    "passage": variant.target_text,
                    "claim_set": [c.model_dump(mode="json") for c in rec.target_claims],
                    "claim_cards": [c.model_dump(mode="json") for c in rec.claim_cards],
                    "glossary": [g.model_dump(mode="json") for g in rec.glossary],
                    "source_checksum": rec.source_checksum,
                    "target_checksum": variant.checksum,
                }
            )
    version = args.version
    out = ml.output_path / profile / "exports" / version
    out.mkdir(parents=True, exist_ok=True)
    jsonl = out / "translations.jsonl"
    jsonl.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    manifest = {
        "profile_id": profile,
        "version": version,
        "rows": len(rows),
        "families": len({r["family_id"] for r in rows}),
        "path": str(jsonl),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0
