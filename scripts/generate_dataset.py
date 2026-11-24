#!/usr/bin/env python
"""Resumable long-run batch driver for a target number of accepted families.

Each family is one base document plus SUPPORTED / CONTRADICTED / UNSUPPORTED
variants. The driver:

1. grows the topic graph until there are enough leaves for the target;
2. runs batches until the accepted-family count reaches the target;
3. checkpoints a manifest after every round and on every exit path;
4. stops cleanly on budget exhaustion, no-progress, or repeated failures.

Safe to re-run: completed candidates are skipped by the pipeline.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tristate.config import load_config  # noqa: E402
from tristate.llm import BudgetExceeded  # noqa: E402
from tristate.pipeline import Pipeline  # noqa: E402
from tristate.store import Store  # noqa: E402
from tristate.topics import expand_to_target, load_graph, seed_graph  # noqa: E402
from tristate.util import atomic_write_json, utcnow  # noqa: E402


def accepted_count(store: Store) -> int:
    return int(store.family_counts().get("ACCEPTED", 0))


def total_cost(store: Store) -> float:
    summary = store.call_summary()
    return round(sum(float(r["cost_usd"]) for r in summary["by_stage"]), 6)


def write_manifest(path: Path, payload: dict) -> None:
    atomic_write_json(path, payload)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--target-families", type=int, default=200)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--budget-usd", type=float, default=25.0)
    ap.add_argument("--max-rounds", type=int, default=40)
    ap.add_argument("--candidates-per-topic", type=int, default=2)
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = load_config(
        args.config,
        overrides={
            "project": {"output_dir": args.data_dir},
            "execution": {
                "max_concurrency": args.concurrency,
                "max_total_cost_usd": args.budget_usd,
            },
            "blueprint": {"candidates_per_topic": args.candidates_per_topic},
        },
    )
    store = Store(cfg.data_dir)
    manifest_path = Path(cfg.data_dir) / "batch_manifest.json"
    manifest: dict = {
        "target_families": args.target_families,
        "concurrency": args.concurrency,
        "budget_usd": args.budget_usd,
        "started_at": utcnow(),
        "updated_at": utcnow(),
        "status": "running",
        "accepted": accepted_count(store),
        "cost_usd": total_cost(store),
        "rounds": [],
    }
    write_manifest(manifest_path, manifest)

    pipeline = Pipeline(cfg, store=store)

    # Pre-grow enough leaves that a few quarantine losses do not starve the run.
    graph = seed_graph(cfg.data_dir)
    target_leaves = max(40, math.ceil(args.target_families / max(1, args.candidates_per_topic)) + 40)
    if manifest["accepted"] < args.target_families and len(graph.leaves()) < target_leaves:
        print(
            f"[batch] expanding topics: {len(graph.leaves())} -> at least {target_leaves} leaves",
            flush=True,
        )
        calls = expand_to_target(
            graph, cfg, pipeline.client, target_leaves, max_calls=90,
            log=lambda m: print(f"[batch] {m}", flush=True),
        )
        print(f"[batch] topic expansion calls={calls} leaves={len(load_graph(cfg.data_dir).leaves())}", flush=True)

    try:
        for round_no in range(1, args.max_rounds + 1):
            accepted = accepted_count(store)
            remaining = args.target_families - accepted
            manifest.update(accepted=accepted, cost_usd=total_cost(store), updated_at=utcnow())
            if remaining <= 0:
                manifest["status"] = "complete"
                break

            before_round = accepted
            print(
                f"[batch] round {round_no}: accepted={accepted} remaining={remaining} "
                f"cost=${total_cost(store):.4f}",
                flush=True,
            )
            summary = pipeline.run(limit=remaining, expand=False)
            round_info = {
                "round": round_no,
                "started_at": utcnow(),
                "requested": summary.requested,
                "accepted": summary.accepted,
                "quarantined": summary.quarantined,
                "failed": summary.failed,
                "skipped": summary.skipped,
                "processed": summary.processed,
                "elapsed_s": round(summary.elapsed_s, 1),
                "cost_usd": summary.llm.get("cost_usd"),
                "run_id": summary.run_id,
            }
            manifest["rounds"].append(round_info)
            manifest.update(
                accepted=accepted_count(store),
                cost_usd=total_cost(store),
                updated_at=utcnow(),
                last_run=summary.run_id,
            )
            write_manifest(manifest_path, manifest)
            print(
                f"[batch] round {round_no} done: accepted_total={manifest['accepted']} "
                f"cost=${manifest['cost_usd']:.4f}",
                flush=True,
            )

            if manifest["accepted"] >= args.target_families:
                manifest["status"] = "complete"
                break
            if manifest["accepted"] == before_round and summary.processed <= summary.skipped:
                # No new work was possible this round: grow the graph and try once more.
                before_leaves = len(load_graph(cfg.data_dir).leaves())
                grow_to = before_leaves + 40
                print(f"[batch] no progress; expanding topics toward {grow_to} leaves", flush=True)
                expand_to_target(
                    load_graph(cfg.data_dir), cfg, pipeline.client, grow_to, max_calls=60,
                    log=lambda m: print(f"[batch] {m}", flush=True),
                )
                if len(load_graph(cfg.data_dir).leaves()) == before_leaves:
                    manifest["status"] = "stalled"
                    break
            time.sleep(2)
        else:
            manifest["status"] = "round_limit"
    except BudgetExceeded as exc:
        manifest["status"] = "budget_exceeded"
        manifest["error"] = str(exc)
        print(f"[batch] budget stop: {exc}", flush=True)
    except KeyboardInterrupt:
        manifest["status"] = "interrupted"
        raise
    except Exception as exc:  # checkpoint before surfacing
        manifest["status"] = "error"
        manifest["error"] = f"{type(exc).__name__}: {exc}"
        print(f"[batch] fatal: {manifest['error']}", flush=True)
        raise
    finally:
        manifest.update(
            accepted=accepted_count(store),
            cost_usd=total_cost(store),
            updated_at=utcnow(),
        )
        if manifest["status"] == "running":
            manifest["status"] = "incomplete"
        write_manifest(manifest_path, manifest)
        pipeline.close()
        store.close()
        print(
            f"[batch] exit status={manifest['status']} accepted={manifest['accepted']} "
            f"cost=${manifest['cost_usd']:.4f}",
            flush=True,
        )
    return 0 if manifest["status"] == "complete" else 1


def _client(cfg):  # pragma: no cover - kept for ad-hoc imports
    from tristate.llm import LlmClient

    return LlmClient(cfg, "RUN_topic_expand")


if __name__ == "__main__":
    raise SystemExit(main())
