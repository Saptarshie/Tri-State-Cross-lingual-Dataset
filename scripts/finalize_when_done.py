#!/usr/bin/env python
"""Wait for a batch manifest to reach 'complete', then index and export it.

Run detached alongside a long generation batch. It does not touch the batch
process; it only polls the manifest and finalizes once the batch says complete.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--version", default="v1-200")
    ap.add_argument("--poll-seconds", type=int, default=300)
    ap.add_argument("--max-hours", type=float, default=12.0)
    ap.add_argument("--no-index", action="store_true")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    manifest_path = Path(args.data_dir) / "batch_manifest.json"
    final_path = Path(args.data_dir) / "finalize.json"
    deadline = time.time() + args.max_hours * 3600
    state: dict = {"started_at": now(), "status": "waiting", "steps": []}

    def save() -> None:
        final_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    save()
    while time.time() < deadline:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            time.sleep(args.poll_seconds)
            continue
        status = manifest.get("status")
        state.update(batch_status=status, accepted=manifest.get("accepted"),
                     cost_usd=manifest.get("cost_usd"), updated_at=now())
        save()
        if status == "complete":
            break
        if status in {"error", "stalled", "budget_exceeded", "interrupted", "round_limit"}:
            state["status"] = f"stopped:{status}"
            save()
            return 2
        time.sleep(args.poll_seconds)
    else:
        state["status"] = "timeout"
        save()
        return 3

    commands = []
    if not args.no_index:
        commands.append(("index", [sys.executable, "-m", "tristate", "index", "build",
                                   "--data-dir", args.data_dir]))
    commands.append(("export", [sys.executable, "-m", "tristate", "export",
                                "--version", args.version, "--data-dir", args.data_dir]))
    commands.append(("report", [sys.executable, "-m", "tristate", "report", "md",
                                "--data-dir", args.data_dir]))
    for name, cmd in commands:
        started = time.time()
        proc = subprocess.run(cmd, cwd=root, text=True, capture_output=True)
        state["steps"].append({
            "step": name,
            "returncode": proc.returncode,
            "elapsed_s": round(time.time() - started, 1),
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        })
        save()
        # Indexing is useful but not required for a valid export. Do not let an
        # embedder problem block the dataset itself.
        if proc.returncode != 0 and name != "index":
            state["status"] = f"failed:{name}"
            save()
            return 4
    state["status"] = "finalized"
    state["finished_at"] = now()
    save()
    print(json.dumps(state, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
