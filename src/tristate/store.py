"""Durable state: stage jobs, idempotency ledger, accepted-family registry.

SQLite is the metadata store; JSON files are the artefacts. Every write is atomic
and every stage is addressable by (candidate_id, stage), which is what makes
resume-after-crash possible and reruns idempotent.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from .util import (
    append_jsonl,
    atomic_write_json,
    read_json,
    sha256_json,
    utcnow,
)

STAGE_ORDER = [
    "blueprint",
    "passage",
    "extract",
    "claims",
    "base_check",
    "variant_SUPPORTED",
    "variant_CONTRADICTED",
    "variant_UNSUPPORTED",
    "family_validate",
    "accept",
]

TERMINAL_OK = "SUCCEEDED"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates(
  candidate_id TEXT PRIMARY KEY,
  idempotency_key TEXT UNIQUE,
  topic_ids TEXT,
  topic_path TEXT,
  source_type TEXT,
  document_id TEXT,
  status TEXT,
  workdir TEXT,
  created_at TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS jobs(
  job_id INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 0,
  model TEXT,
  prompt_version TEXT,
  error TEXT,
  artifact_ref TEXT,
  created_at TEXT,
  updated_at TEXT,
  UNIQUE(candidate_id, stage)
);
CREATE TABLE IF NOT EXISTS families(
  family_id TEXT PRIMARY KEY,
  idempotency_key TEXT UNIQUE,
  status TEXT,
  split TEXT,
  split_group_id TEXT,
  path TEXT,
  topic_path TEXT,
  created_at TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS calls(
  call_id TEXT PRIMARY KEY,
  run_id TEXT,
  stage TEXT,
  model TEXT,
  prompt_name TEXT,
  prompt_version TEXT,
  request_hash TEXT,
  status TEXT,
  latency_ms INTEGER,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  cost_usd REAL,
  cached INTEGER,
  family_id TEXT,
  candidate_id TEXT,
  error TEXT,
  raw_ref TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS counters(name TEXT PRIMARY KEY, value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS export_versions(
  version TEXT PRIMARY KEY,
  created_at TEXT,
  path TEXT,
  split_counts TEXT,
  config_hash TEXT
);
CREATE TABLE IF NOT EXISTS events(
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT,
  candidate_id TEXT,
  family_id TEXT,
  stage TEXT,
  event TEXT,
  detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_candidate ON jobs(candidate_id, stage);
CREATE INDEX IF NOT EXISTS idx_families_status ON families(status, split);
CREATE INDEX IF NOT EXISTS idx_calls_run ON calls(run_id, stage);
"""


class Store:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for sub in ("state", "work", "families", "quarantine", "raw", "logs",
                    "index", "reports", "exports", "corpus", "topics"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "state" / "state.db"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # low level
    # ------------------------------------------------------------------ #
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _exec(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def _query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, tuple(params)).fetchall())

    def log_event(self, event: str, **kw: Any) -> None:
        self._exec(
            "INSERT INTO events(ts,candidate_id,family_id,stage,event,detail) VALUES(?,?,?,?,?,?)",
            (
                utcnow(),
                kw.get("candidate_id"),
                kw.get("family_id"),
                kw.get("stage"),
                event,
                json.dumps(kw.get("detail", {}), ensure_ascii=False)[:4000],
            ),
        )

    def next_counter(self, name: str) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT value FROM counters WHERE name=?", (name,))
            row = cur.fetchone()
            nxt = (row["value"] if row else 0) + 1
            self._conn.execute(
                "INSERT INTO counters(name,value) VALUES(?,?) "
                "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                (name, nxt),
            )
            self._conn.commit()
            return nxt

    # ------------------------------------------------------------------ #
    # candidates
    # ------------------------------------------------------------------ #
    def workdir(self, candidate_id: str) -> Path:
        p = self.data_dir / "work" / candidate_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def upsert_candidate(
        self,
        idempotency_key: str,
        candidate_id: str,
        topic_ids: list[str],
        topic_path: list[str],
        source_type: str = "synthetic",
        document_id: str | None = None,
    ) -> tuple[str, bool]:
        """Return (candidate_id, created). Existing keys resume the same candidate."""
        rows = self._query("SELECT candidate_id FROM candidates WHERE idempotency_key=?", (idempotency_key,))
        if rows:
            return rows[0]["candidate_id"], False
        now = utcnow()
        self._exec(
            "INSERT INTO candidates(candidate_id,idempotency_key,topic_ids,topic_path,"
            "source_type,document_id,status,workdir,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                candidate_id,
                idempotency_key,
                json.dumps(topic_ids),
                json.dumps(topic_path),
                source_type,
                document_id,
                "PENDING",
                str(self.workdir(candidate_id)),
                now,
                now,
            ),
        )
        self.log_event("candidate_created", candidate_id=candidate_id)
        return candidate_id, True

    def set_candidate_status(self, candidate_id: str, status: str, detail: dict | None = None) -> None:
        self._exec(
            "UPDATE candidates SET status=?, updated_at=? WHERE candidate_id=?",
            (status, utcnow(), candidate_id),
        )
        self.log_event("candidate_status", candidate_id=candidate_id, detail={"status": status, **(detail or {})})

    def get_candidate(self, candidate_id: str) -> dict | None:
        rows = self._query("SELECT * FROM candidates WHERE candidate_id=?", (candidate_id,))
        return dict(rows[0]) if rows else None

    def list_candidates(self, status: str | None = None, limit: int | None = None) -> list[dict]:
        sql = "SELECT * FROM candidates"
        params: list[Any] = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY created_at, candidate_id"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [dict(r) for r in self._query(sql, params)]

    # ------------------------------------------------------------------ #
    # jobs
    # ------------------------------------------------------------------ #
    def job(self, candidate_id: str, stage: str) -> dict | None:
        rows = self._query(
            "SELECT * FROM jobs WHERE candidate_id=? AND stage=?", (candidate_id, stage)
        )
        return dict(rows[0]) if rows else None

    def job_status(self, candidate_id: str, stage: str) -> str:
        j = self.job(candidate_id, stage)
        return j["status"] if j else "MISSING"

    def start_job(self, candidate_id: str, stage: str, model: str = "", prompt_version: str = "") -> int:
        now = utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs(candidate_id,stage,status,attempt,model,prompt_version,created_at,updated_at) "
                "VALUES(?,?,'RUNNING',1,?,?,?,?) "
                "ON CONFLICT(candidate_id,stage) DO UPDATE SET "
                "status='RUNNING', attempt=jobs.attempt+1, updated_at=excluded.updated_at, "
                "model=excluded.model, prompt_version=excluded.prompt_version, error=NULL",
                (candidate_id, stage, model, prompt_version, now, now),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT job_id, attempt FROM jobs WHERE candidate_id=? AND stage=?",
                (candidate_id, stage),
            ).fetchone()
            return int(row["job_id"])

    def finish_job(
        self,
        candidate_id: str,
        stage: str,
        status: str,
        artifact_ref: str | None = None,
        error: str | None = None,
    ) -> None:
        self._exec(
            "UPDATE jobs SET status=?, artifact_ref=?, error=?, updated_at=? "
            "WHERE candidate_id=? AND stage=?",
            (status, artifact_ref, (error or "")[:4000] or None, utcnow(), candidate_id, stage),
        )

    def stage_succeeded(self, candidate_id: str, stage: str) -> bool:
        j = self.job(candidate_id, stage)
        if not j or j["status"] != TERMINAL_OK:
            return False
        ref = j.get("artifact_ref")
        return bool(ref) and Path(ref).exists()

    def completed_stages(self, candidate_id: str) -> list[str]:
        rows = self._query(
            "SELECT stage FROM jobs WHERE candidate_id=? AND status=?",
            (candidate_id, TERMINAL_OK),
        )
        done = {r["stage"] for r in rows}
        return [s for s in STAGE_ORDER if s in done]

    # ------------------------------------------------------------------ #
    # families
    # ------------------------------------------------------------------ #
    def register_family(
        self,
        family_id: str,
        idempotency_key: str,
        status: str,
        split: str,
        split_group_id: str,
        path: str,
        topic_path: list[str],
    ) -> None:
        now = utcnow()
        self._exec(
            "INSERT INTO families(family_id,idempotency_key,status,split,split_group_id,path,"
            "topic_path,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(family_id) DO UPDATE SET status=excluded.status, "
            "split=excluded.split, split_group_id=excluded.split_group_id, path=excluded.path, "
            "updated_at=excluded.updated_at",
            (
                family_id,
                idempotency_key,
                status,
                split,
                split_group_id,
                path,
                json.dumps(topic_path),
                now,
                now,
            ),
        )

    def family_by_key(self, idempotency_key: str) -> dict | None:
        rows = self._query("SELECT * FROM families WHERE idempotency_key=?", (idempotency_key,))
        return dict(rows[0]) if rows else None

    def get_family_row(self, family_id: str) -> dict | None:
        rows = self._query("SELECT * FROM families WHERE family_id=?", (family_id,))
        return dict(rows[0]) if rows else None

    def list_families(self, status: str | None = None, split: str | None = None) -> list[dict]:
        sql = "SELECT * FROM families"
        where, params = [], []
        if status:
            where.append("status=?")
            params.append(status)
        if split:
            where.append("split=?")
            params.append(split)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY family_id"
        return [dict(r) for r in self._query(sql, params)]

    def family_counts(self) -> dict[str, int]:
        rows = self._query("SELECT status, COUNT(*) AS n FROM families GROUP BY status")
        return {r["status"]: int(r["n"]) for r in rows}

    # ------------------------------------------------------------------ #
    # calls
    # ------------------------------------------------------------------ #
    def record_call(self, rec: Any) -> None:
        d = rec.as_dict() if hasattr(rec, "as_dict") else dict(rec)
        self._exec(
            "INSERT OR REPLACE INTO calls(call_id,run_id,stage,model,prompt_name,prompt_version,"
            "request_hash,status,latency_ms,prompt_tokens,completion_tokens,cost_usd,cached,"
            "family_id,candidate_id,error,raw_ref,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                d["call_id"], d.get("run_id"), d.get("stage"), d.get("model"),
                d.get("prompt_name"), d.get("prompt_version"), d.get("request_hash"),
                d.get("status"), d.get("latency_ms"), d.get("prompt_tokens"),
                d.get("completion_tokens"), d.get("cost_usd"), int(bool(d.get("cached"))),
                d.get("family_id"), d.get("candidate_id"), d.get("error"),
                d.get("raw_ref"), d.get("created_at"),
            ),
        )

    def calls_for_candidate(self, candidate_id: str) -> int:
        rows = self._query(
            "SELECT COUNT(*) AS n FROM calls WHERE candidate_id=? AND status != 'CACHED'",
            (candidate_id,),
        )
        return int(rows[0]["n"]) if rows else 0

    def call_summary(self, run_id: str | None = None) -> dict[str, Any]:
        where, params = "", []
        if run_id:
            where = " WHERE run_id=?"
            params.append(run_id)
        rows = self._query(
            "SELECT stage, model, status, COUNT(*) n, SUM(prompt_tokens) pt, "
            "SUM(completion_tokens) ct, SUM(cost_usd) cost, "
            "SUM(CASE WHEN cached=1 THEN 1 ELSE 0 END) cached_n, "
            "AVG(latency_ms) avg_ms "
            f"FROM calls{where} GROUP BY stage, model, status",
            params,
        )
        return {
            "by_stage": [
                {
                    "stage": r["stage"], "model": r["model"], "status": r["status"],
                    "calls": int(r["n"]), "prompt_tokens": int(r["pt"] or 0),
                    "completion_tokens": int(r["ct"] or 0),
                    "cost_usd": round(float(r["cost"] or 0), 6),
                    "cached": int(r["cached_n"] or 0),
                    "avg_latency_ms": round(float(r["avg_ms"] or 0), 1),
                }
                for r in rows
            ]
        }

    # ------------------------------------------------------------------ #
    # artefact helpers
    # ------------------------------------------------------------------ #
    def artifact_path(self, candidate_id: str, name: str, ext: str = "json") -> Path:
        return self.workdir(candidate_id) / f"{name}.{ext}"

    def save_artifact(self, candidate_id: str, name: str, obj: Any) -> Path:
        p = self.artifact_path(candidate_id, name)
        atomic_write_json(p, obj)
        return p

    def load_artifact(self, candidate_id: str, name: str) -> Any:
        return read_json(self.artifact_path(candidate_id, name))

    def save_family(self, family_obj: dict, status: str, split: str, split_group_id: str,
                    idempotency_key: str) -> Path:
        family_id = family_obj["family_id"]
        path = self.data_dir / "families" / f"{family_id}.json"
        atomic_write_json(path, family_obj)
        self.register_family(
            family_id, idempotency_key, status, split, split_group_id, str(path),
            family_obj.get("topic", {}).get("topic_path", []),
        )
        return path

    def load_family(self, family_id: str) -> dict | None:
        row = self.get_family_row(family_id)
        if not row:
            return None
        return read_json(row["path"])

    def quarantine(
        self,
        candidate_id: str,
        reasons: list[str],
        stage: str,
        payload: dict | None = None,
    ) -> Path:
        path = self.data_dir / "quarantine" / f"{candidate_id}.json"
        entry = {
            "candidate_id": candidate_id,
            "stage": stage,
            "reasons": reasons,
            "updated_at": utcnow(),
            "payload": payload or {},
            "workdir": str(self.workdir(candidate_id)),
        }
        atomic_write_json(path, entry)
        append_jsonl(self.data_dir / "quarantine" / "index.jsonl", entry)
        self.set_candidate_status(candidate_id, "QUARANTINED", {"reasons": reasons, "stage": stage})
        self.finish_job(candidate_id, stage, "QUARANTINED", error="; ".join(reasons)[:1000])
        return path

    def update_manifest(self, extra: dict | None = None) -> dict:
        families = self.list_families()
        manifest = {
            "updated_at": utcnow(),
            "counts": {
                "families": len(families),
                "accepted": sum(1 for f in families if f["status"] == "ACCEPTED"),
                "quarantined": sum(1 for f in families if f["status"] == "QUARANTINED"),
                "candidates": len(self.list_candidates()),
            },
            "splits": {
                s: sum(1 for f in families if f["split"] == s)
                for s in ("train", "validation", "test", "unassigned")
            },
            "config_hash": sha256_json(extra or {}),
        }
        if extra:
            manifest.update(extra)
        atomic_write_json(self.data_dir / "manifest.json", manifest)
        return manifest
