"""Dataset quality, diversity and cost reporting."""

from __future__ import annotations

import json
from collections import Counter
from statistics import mean
from typing import Any

from .audit import audit_shortcuts
from .config import Config
from .schema import LABELS, Family
from .store import Store
from .topics import coverage_report, load_graph
from .util import atomic_write_json, atomic_write_text, read_jsonl, utcnow


def _dist(values: list[Any]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    c = Counter(values)
    return {
        "n": len(values),
        "counts": dict(sorted(c.items(), key=lambda x: -x[1])),
        "mean": round(mean([v for v in values if isinstance(v, (int, float))]), 3) if all(isinstance(v, (int, float)) for v in values) else None,
    }


def load_accepted(store: Store) -> list[Family]:
    out: list[Family] = []
    for row in store.list_families(status="ACCEPTED"):
        raw = store.load_family(row["family_id"])
        if not raw:
            continue
        try:
            out.append(Family.model_validate(raw))
        except Exception:
            continue
    return out


def build_quality_report(store: Store, cfg: Config, include_audit: bool | None = None) -> dict[str, Any]:
    families = load_accepted(store)
    quarantines = read_jsonl(store.data_dir / "quarantine" / "index.jsonl")
    candidates = store.list_candidates()
    calls = store.call_summary()
    total_cost = sum(row["cost_usd"] for row in calls.get("by_stage", []))
    total_tokens = sum(row["prompt_tokens"] + row["completion_tokens"] for row in calls.get("by_stage", []))

    by_status = Counter(c["status"] for c in candidates)
    reasons = Counter()
    for q in quarantines:
        for reason in q.get("reasons", []):
            reasons[reason.split(":")[0]] += 1

    families_count = len(families)
    lengths = [v.token_count for f in families for v in f.variants.values()]
    base_lengths = [f.base_passage.token_count for f in families]
    novelty_scores = [
        row.get("max_cosine", 0.0)
        for f in families for row in (f.quality.novelty or {}).values()
        if isinstance(row, dict)
    ]
    agreements = [
        v.validation.agreement
        for f in families for v in f.variants.values()
        if v.validation and v.validation.agreement is not None
    ]
    claim_counts = [len(f.claim_set) for f in families]
    claim_types = [c.claim_type for f in families for c in f.claim_set]
    edit_ops = [op for f in families for v in f.variants.values() for op in v.edit_history.operations]
    complete_families = sum(1 for f in families if set(f.variants) == set(LABELS))

    report: dict[str, Any] = {
        "generated_at": utcnow(),
        "config_hash": cfg.config_hash(),
        "families": families_count,
        "candidates": {
            "total": len(candidates),
            "by_status": dict(by_status),
        },
        "acceptance": {
            "families_accepted": families_count,
            "quarantined": len(quarantines),
            "acceptance_rate": round(families_count / max(1, len(candidates)), 4),
            "by_reason": dict(reasons),
        },
        "dataset": {
            "variants": families_count * 3,
            "labels_per_family": {"all_three": complete_families},
            "claims": sum(claim_counts),
            "claim_count_distribution": _dist(claim_counts),
            "claim_types": dict(Counter(claim_types)),
            "edit_operations": dict(Counter(edit_ops)),
            "passage_tokens": {
                "mean": round(mean(lengths), 1) if lengths else 0,
                "min": min(lengths) if lengths else 0,
                "max": max(lengths) if lengths else 0,
            },
            "base_tokens": {
                "mean": round(mean(base_lengths), 1) if base_lengths else 0,
                "min": min(base_lengths) if base_lengths else 0,
                "max": max(base_lengths) if base_lengths else 0,
            },
            "genres": dict(Counter(f.base_passage.genre for f in families)),
            "tones": dict(Counter(f.base_passage.tone for f in families)),
            "narratives": dict(Counter(f.base_passage.narrative for f in families)),
            "structures": dict(Counter(f.base_passage.structure for f in families)),
            "splits": dict(Counter(f.split for f in families)),
            "topics": dict(Counter(" > ".join(f.topic.topic_path) for f in families)),
        },
        "validation": {
            "variants_with_validation": sum(
                1 for f in families for v in f.variants.values() if v.validation
            ),
            "validator_agreement_mean": round(mean(agreements), 4) if agreements else None,
            "graph_diff_misses": sum(
                len((v.graph_diff or {}).get("misses", [])) for f in families for v in f.variants.values()
            ),
            "human_audit_flags": sum(1 for f in families if f.quality.audit_flags),
        },
        "novelty": {
            "max_cosine_mean": round(mean(novelty_scores), 4) if novelty_scores else None,
            "max_cosine_p95": sorted(novelty_scores)[int(len(novelty_scores) * 0.95)] if novelty_scores else None,
            "near_duplicates": sum(
                1 for f in families for row in (f.quality.novelty or {}).values()
                if isinstance(row, dict) and row.get("near_duplicate")
            ),
        },
        "calls": calls,
        "cost": {
            "estimated_usd": round(total_cost, 4),
            "tokens": total_tokens,
            "families": families_count,
            "usd_per_family": round(total_cost / families_count, 4) if families_count else None,
        },
    }

    graph = load_graph(store.data_dir)
    report["topic_coverage"] = coverage_report(graph)

    do_audit = cfg.quality.shortcut_audit if include_audit is None else include_audit
    if do_audit:
        report["shortcut_audit"] = audit_shortcuts(families, cfg)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    d = report.get("dataset", {})
    a = report.get("acceptance", {})
    lines = [
        f"# Quality report — {report['generated_at']}",
        "",
        f"Config hash: `{report['config_hash'][:16]}`",
        "",
        "## Counts",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Accepted families | {report['families']} |",
        f"| Variants | {d.get('variants', 0)} |",
        f"| Claims | {d.get('claims', 0)} |",
        f"| Quarantined candidates | {a.get('quarantined', 0)} |",
        f"| Acceptance rate | {a.get('acceptance_rate', 0):.1%} |",
        f"| Estimated cost | ${report['cost'].get('estimated_usd', 0)} |",
        f"| Cost per family | ${report['cost'].get('usd_per_family') or 0} |",
        "",
        "## Distributions",
        "",
        f"- Claim counts: {d.get('claim_count_distribution', {}).get('counts', {})}",
        f"- Claim types: {d.get('claim_types', {})}",
        f"- Edit operations: {d.get('edit_operations', {})}",
        f"- Genres: {d.get('genres', {})}",
        f"- Tones: {d.get('tones', {})}",
        f"- Narratives: {d.get('narratives', {})}",
        f"- Structures: {d.get('structures', {})}",
        f"- Splits: {d.get('splits', {})}",
        f"- Passage tokens: {d.get('passage_tokens', {})}",
        "",
        "## Validation",
        "",
    ]
    v = report.get("validation", {})
    lines += [
        f"- Validator agreement (mean): {v.get('validator_agreement_mean')}",
        f"- Graph-diff misses: {v.get('graph_diff_misses')}",
        f"- Human audit flags: {v.get('human_audit_flags')}",
        "",
        "## Rejections by reason",
        "",
        f"{a.get('by_reason', {})}",
        "",
        "## Topic coverage",
        "",
        "| Topic | Accepted | Target |",
        "|---|---:|---:|",
    ]
    for row in report.get("topic_coverage", [])[:40]:
        lines.append(f"| {row['path']} | {row['accepted']} | {row['target']} |")
    audit = report.get("shortcut_audit")
    if audit:
        lines += ["", "## Shortcut audit (non-semantic features)", ""]
        if audit.get("status") == "ok":
            lines += [
                f"- Accuracy: {audit['overall']['accuracy']} (95% CI {audit['overall'].get('ci95_accuracy')})",
                f"- Chance: {audit['chance_accuracy']}",
                f"- Flagged: {audit['flagged']}",
                f"- By feature group: {json.dumps(audit['by_feature_group'], default=str)}",
            ]
        else:
            lines.append(f"- {audit.get('message')}")
    lines += ["", "## Top stages by cost", ""]
    by_stage = sorted(report.get("calls", {}).get("by_stage", []), key=lambda r: -r["cost_usd"])[:10]
    lines += ["| Stage | Model | Calls | Tokens | Cost | Avg ms |", "|---|---|---:|---:|---:|---:|"]
    for row in by_stage:
        lines.append(
            f"| {row['stage']} | {row['model']} | {row['calls']} | "
            f"{row['prompt_tokens'] + row['completion_tokens']} | ${row['cost_usd']} | {row['avg_latency_ms']} |"
        )
    return "\n".join(lines) + "\n"


def write_reports(store: Store, cfg: Config, include_audit: bool | None = None) -> dict[str, Any]:
    report = build_quality_report(store, cfg, include_audit)
    out = store.data_dir / "reports"
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out / "quality.json", report)
    atomic_write_text(out / "quality.md", render_markdown(report))
    return report
