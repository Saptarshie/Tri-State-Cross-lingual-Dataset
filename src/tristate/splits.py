"""Family-level splits with lineage grouping.

A split is assigned once, at acceptance, from a salted hash of the family's lineage
cluster. All three variants share it by construction. Assignments are persisted so a
later export cannot silently re-split a family, and test assignments are locked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Config
from .util import atomic_write_json, read_json, sha256_text, utcnow


class SplitManager:
    def __init__(self, data_dir: str | Path, cfg: Config, autosave: bool = True):
        self.cfg = cfg
        self.autosave = autosave
        self.path = Path(data_dir) / "splits" / "assignments.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, Any] = read_json(self.path, default=None) or {
            "salt": cfg.splits.salt,
            "groups": {},
            "group_seq": 0,
            "assignments": {},
            "created_at": utcnow(),
        }

    # ------------------------------------------------------------------ #
    def _hash_split(self, key: str) -> str:
        h = sha256_text(f"{self.data['salt']}|{key}")
        x = int(h[:16], 16) / float(16 ** 16)
        if x < self.cfg.splits.train:
            return "train"
        if x < self.cfg.splits.train + self.cfg.splits.validation:
            return "validation"
        return "test"

    def group_for(self, cluster_key: str) -> str:
        groups: dict[str, str] = self.data["groups"]
        if cluster_key in groups:
            return groups[cluster_key]
        self.data["group_seq"] = int(self.data.get("group_seq", 0)) + 1
        gid = f"GROUP_{self.data['group_seq']:06d}"
        groups[cluster_key] = gid
        return gid

    def assign(self, family_id: str, cluster_key: str | None = None) -> tuple[str, str]:
        assignments: dict[str, dict] = self.data["assignments"]
        if family_id in assignments:
            a = assignments[family_id]
            return a["split"], a["group_id"]
        key = cluster_key or family_id
        gid = self.group_for(key)
        # A family inherits the split of its lineage group, never a new draw.
        for other, a in assignments.items():
            if a["group_id"] == gid:
                split = a["split"]
                break
        else:
            split = self._hash_split(key)
        assignments[family_id] = {
            "split": split,
            "group_id": gid,
            "cluster_key": key,
            "assigned_at": utcnow(),
        }
        if self.autosave:
            self.save()
        return split, gid

    def split_of(self, family_id: str) -> str | None:
        a = self.data["assignments"].get(family_id)
        return a["split"] if a else None

    def counts(self) -> dict[str, int]:
        out = {"train": 0, "validation": 0, "test": 0}
        for a in self.data["assignments"].values():
            out[a["split"]] = out.get(a["split"], 0) + 1
        return out

    def report(self) -> dict[str, Any]:
        counts = self.counts()
        total = sum(counts.values()) or 1
        return {
            "counts": counts,
            "fractions": {k: round(v / total, 4) for k, v in counts.items()},
            "groups": len(self.data.get("groups", {})),
            "families": len(self.data.get("assignments", {})),
            "salt": self.data.get("salt"),
        }

    def save(self) -> None:
        atomic_write_json(self.path, self.data)
