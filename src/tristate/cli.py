"""Command-line interface.

Every command is safe to run more than once: stages are cached by prompt/model version,
candidates are keyed by idempotency hash, and exports are versioned.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import DEFAULT_CONFIG, Config, load_config
from .corpus import corpus_summary, ingest_local_paths
from .export import export_dataset
from .llm import LlmClient
from .novelty import NoveltyService
from .pipeline import Pipeline
from .prompts import PromptLibrary
from .reports import render_markdown, write_reports
from .store import Store
from .topics import (
    coverage_report,
    expand_topic,
    seed_graph,
)
from .util import read_jsonl

STAGE_ALIASES = {
    "blueprint": "blueprint",
    "blueprints": "blueprint",
    "document_plan": "document_plan",
    "plan": "document_plan",
    "passage": "passage",
    "passages": "passage",
    "extract": "extract",
    "claims": "claims",
    "variants": "variants",
    "validate": "validate",
}


def _cfg(args: argparse.Namespace) -> Config:
    overrides: dict[str, Any] = {}
    if getattr(args, "data_dir", None):
        overrides.setdefault("project", {})["output_dir"] = args.data_dir
    if getattr(args, "prompts_dir", None):
        overrides.setdefault("prompts", {})["dir"] = args.prompts_dir
    if getattr(args, "mock", False):
        overrides.setdefault("project", {})["output_dir"] = args.data_dir or str(Path("data") / "mock")
        overrides.setdefault("hnsw", {})["embedder"] = "hashing"
        overrides.setdefault("hnsw", {}).update({"near_duplicate_cosine": 1.0, "near_duplicate_jaccard": 1.0})
        overrides.setdefault("execution", {})["max_concurrency"] = 1
    return load_config(getattr(args, "config", None), overrides)


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _pipeline(cfg: Config, args: argparse.Namespace) -> Pipeline:
    return Pipeline(cfg, mock=getattr(args, "mock", False), run_id=getattr(args, "run_id", None))


# --------------------------------------------------------------------------- #
def cmd_config_check(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    prompts = PromptLibrary(cfg.prompts_dir)
    out: dict[str, Any] = {
        "config_hash": cfg.config_hash(),
        "data_dir": str(cfg.data_dir),
        "prompts_dir": str(cfg.prompts_dir),
        "language": cfg.project.language,
        "labels": cfg.variants.required_labels,
        "models": {
            "generator": cfg.llm.generator.name,
            "extractor": cfg.llm.extractor.name,
            "claims": cfg.llm.claims.name,
            "editor": cfg.llm.editor.name,
            "validator": cfg.llm.validator.name,
            "validator_second": cfg.llm.validator_second.name,
        },
        "prompts": {name: prompts.get(name).full_version for name in prompts.names()},
        "api_key_present": bool(cfg.api_key()),
        "budget_usd": cfg.execution.max_total_cost_usd,
    }
    if not args.no_network and not args.mock:
        client = LlmClient(cfg, run_id="config-check", prompts=prompts)
        out["api_probe"] = client.probe()
        from .embeddings import get_embedder

        emb = get_embedder(cfg)
        try:
            vec = emb.encode("configuration probe")
            out["embedder"] = {
                "name": getattr(emb, "name", "unknown"),
                "dim": int(vec.shape[0]),
                "available": getattr(emb, "available", True),
            }
        except Exception as exc:
            out["embedder"] = {"error": str(exc)}
    _print(out)
    ok = out["api_key_present"] and (args.no_network or out.get("api_probe", {}).get("ok", False))
    return 0 if ok or args.mock else 1


def cmd_topics(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    graph = seed_graph(cfg.data_dir, force=args.seed)
    if args.action == "expand":
        if not args.topic:
            print("--topic is required (id or name)", file=sys.stderr)
            return 2
        node = graph.nodes.get(args.topic) or next(
            (n for n in graph.nodes.values() if n.name.lower() == args.topic.lower()), None
        )
        if node is None:
            print(f"topic not found: {args.topic}", file=sys.stderr)
            return 2
        pipeline = _pipeline(cfg, args)
        children = expand_topic(graph, cfg, pipeline.client, node.topic_id)
        _print({"expanded": node.name, "children": [c.model_dump(mode="json") for c in children]})
        return 0
    if args.action == "select":
        pipeline = _pipeline(cfg, args)
        rows = pipeline.ensure_candidates(args.limit)
        _print({"candidates": [r["candidate_id"] for r in rows]})
        return 0
    _print({"totals": graph.totals(), "coverage": coverage_report(graph)})
    return 0


def cmd_corpus(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    store = Store(cfg.data_dir)
    if args.action == "ingest":
        if not args.path:
            print("--path is required", file=sys.stderr)
            return 2
        created = ingest_local_paths(store, cfg, args.path)
        _print({"ingested_candidates": len(created), "summary": corpus_summary(store)})
        return 0
    _print(corpus_summary(store))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    pipeline = _pipeline(cfg, args)
    try:
        topic_ids = args.topic_id or None
        summary = pipeline.run(
            limit=args.limit,
            seed_topic=args.topic,
            topic_ids=topic_ids,
            expand=args.expand,
            stop_after=STAGE_ALIASES.get(args.stop_after) if args.stop_after else None,
            retry_quarantined=args.retry_quarantined,
        )
        _print(summary.as_dict())
        return 0
    finally:
        pipeline.close()


def cmd_resume(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    pipeline = _pipeline(cfg, args)
    try:
        summary = pipeline.resume(limit=args.limit, retry_quarantined=args.retry_quarantined)
        _print(summary.as_dict())
        return 0
    finally:
        pipeline.close()


def cmd_stage(args: argparse.Namespace) -> int:
    stage = STAGE_ALIASES.get(args.stage)
    if not stage:
        print(f"unknown stage: {args.stage}", file=sys.stderr)
        return 2
    args.stop_after = stage
    return cmd_run(args)


def cmd_index(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    store = Store(cfg.data_dir)
    if args.action == "stats":
        novelty = NoveltyService(store, cfg)
        _print(novelty.summary())
        return 0
    from .reports import load_accepted

    families = load_accepted(store)
    novelty = NoveltyService(store, cfg)
    result = novelty.rebuild(families)
    novelty.save()
    _print({"action": args.action, **result, "note": "index rebuilt from accepted families"})
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    store = Store(cfg.data_dir)
    result = export_dataset(store, cfg, version=args.version, split=args.split, dry_run=args.dry_run)
    _print(
        {
            "version": result["version"],
            "path": result.get("path"),
            "counts": result["manifest"]["counts"],
            "dry_run": result.get("dry_run", False),
        }
    )
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    store = Store(cfg.data_dir)
    report = write_reports(store, cfg, include_audit=args.shortcut_audit)
    if args.format == "md":
        print(render_markdown(report))
    else:
        _print(report)
    return 0


def cmd_splits(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    from .splits import SplitManager

    mgr = SplitManager(cfg.data_dir, cfg)
    _print(mgr.report())
    return 0


def cmd_quarantine(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    rows = read_jsonl(cfg.data_dir / "quarantine" / "index.jsonl")
    rows = rows[-args.limit:]
    _print(
        [
            {
                "candidate_id": r.get("candidate_id"),
                "stage": r.get("stage"),
                "reasons": r.get("reasons"),
                "updated_at": r.get("updated_at"),
            }
            for r in rows
        ]
    )
    return 0


def cmd_families(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    store = Store(cfg.data_dir)
    if args.action == "show":
        family_id = args.family_id or args.family_id_flag
        if not family_id:
            print("family id required", file=sys.stderr)
            return 2
        fam = store.load_family(family_id)
        if not fam:
            print("not found", file=sys.stderr)
            return 1
        if args.json:
            _print(fam)
        else:
            print(f"{fam['family_id']}  split={fam['split']}  status={fam['quality']['status']}")
            print(f"topic: {' > '.join(fam['topic']['topic_path'])}")
            print(f"claims: {[c['claim_text'] for c in fam['claim_set']]}")
            for label, v in fam["variants"].items():
                print(f"\n--- {label} ({v['token_count']} tok) ---\n{v['text']}")
        return 0
    rows = store.list_families(status=args.status, split=args.split)
    _print(
        [
            {
                "family_id": r["family_id"],
                "split": r["split"],
                "status": r["status"],
                "group": r["split_group_id"],
                "topic": json.loads(r["topic_path"]) if r.get("topic_path") else [],
            }
            for r in rows
        ]
    )
    return 0


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tristate", description="Tri-state counterfactual dataset factory")
    p.add_argument("--config", default=None, help=f"YAML config (default: {DEFAULT_CONFIG})")
    p.add_argument("--data-dir", default=None, help="override project.output_dir")
    p.add_argument("--prompts-dir", default=None, help="override prompts dir")
    p.add_argument("--mock", action="store_true", help="offline deterministic mock workers")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("config-check", help="inspect config, prompts, providers")
    c.add_argument("--no-network", action="store_true")
    c.set_defaults(func=cmd_config_check)

    t = sub.add_parser("topics", help="topic graph operations")
    t.add_argument("action", choices=["seed", "expand", "select", "report"])
    t.add_argument("--seed", action="store_true", help="reseed the graph from configs/seed_topics.yaml")
    t.add_argument("--topic", default=None)
    t.add_argument("--limit", type=int, default=5)
    t.set_defaults(func=cmd_topics)

    co = sub.add_parser("corpus", help="local corpus ingestion and segmentation")
    co.add_argument("action", choices=["ingest", "summary"])
    co.add_argument("--path", action="append", default=[])
    co.set_defaults(func=cmd_corpus)

    r = sub.add_parser("run", help="generate families end to end")
    r.add_argument("--limit", type=int, default=5)
    r.add_argument("--topic", default=None, help="seed topic name")
    r.add_argument("--topic-id", action="append", default=[])
    r.add_argument("--expand", action="store_true")
    r.add_argument("--stop-after", default=None, choices=list(STAGE_ALIASES))
    r.add_argument("--retry-quarantined", action="store_true")
    r.add_argument("--run-id", default=None)
    r.set_defaults(func=cmd_run)

    rs = sub.add_parser("resume", help="resume unfinished candidates")
    rs.add_argument("--limit", type=int, default=100)
    rs.add_argument("--retry-quarantined", action="store_true")
    rs.add_argument("--run-id", default=None)
    rs.set_defaults(func=cmd_resume)

    st = sub.add_parser("stage", help="run one pipeline stage for pending candidates")
    st.add_argument("stage", choices=sorted(set(STAGE_ALIASES)))
    st.add_argument("--limit", type=int, default=5)
    st.add_argument("--run-id", default=None)
    st.set_defaults(func=cmd_stage)

    ix = sub.add_parser("index", help="HNSW index operations")
    ix.add_argument("action", choices=["build", "update", "stats"])
    ix.set_defaults(func=cmd_index)

    ex = sub.add_parser("export", help="versioned dataset export")
    ex.add_argument("--version", default=None)
    ex.add_argument("--split", default=None)
    ex.add_argument("--dry-run", action="store_true")
    ex.set_defaults(func=cmd_export)

    rp = sub.add_parser("report", help="quality, diversity and cost reports")
    rp.add_argument("format", nargs="?", default="json", choices=["json", "md"])
    rp.add_argument("--shortcut-audit", action="store_true")
    rp.set_defaults(func=cmd_report)

    sp = sub.add_parser("splits", help="split assignments")
    sp.add_argument("action", nargs="?", default="report", choices=["report"])
    sp.set_defaults(func=cmd_splits)

    q = sub.add_parser("quarantine", help="quarantine inspection")
    q.add_argument("action", nargs="?", default="list", choices=["list"])
    q.add_argument("--limit", type=int, default=20)
    q.set_defaults(func=cmd_quarantine)

    f = sub.add_parser("families", help="accepted family inspection")
    f.add_argument("action", choices=["list", "show"])
    f.add_argument("family_id", nargs="?", default=None)
    f.add_argument("--family-id", dest="family_id_flag", default=None)
    f.add_argument("--status", default=None)
    f.add_argument("--split", default=None)
    f.add_argument("--json", action="store_true")
    f.set_defaults(func=cmd_families)

    # accept the global options after the subcommand too (argparse otherwise rejects them)
    for sp in sub.choices.values():
        sp.add_argument("--config", default=argparse.SUPPRESS)
        sp.add_argument("--data-dir", default=argparse.SUPPRESS)
        sp.add_argument("--prompts-dir", default=argparse.SUPPRESS)
        sp.add_argument("--mock", action="store_true", default=argparse.SUPPRESS)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\ninterrupted: state is durable; run `resume` to continue", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
