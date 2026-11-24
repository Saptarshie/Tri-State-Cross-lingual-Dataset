"""Identifier helpers.

Stable, human-scannable IDs plus hash-based idempotency keys. Sequential IDs are
allocated by :class:`tristate.store.JobStore` inside a transaction; never derive
them from wall-clock time or in-memory counters that reset.
"""

from __future__ import annotations

import re

from .util import sha256_json, short_hash

LABEL_TO_CODE = {"SUPPORTED": "S", "CONTRADICTED": "C", "UNSUPPORTED": "U"}
CODE_TO_LABEL = {v: k for k, v in LABEL_TO_CODE.items()}


def candidate_id(idempotency_key: str) -> str:
    return f"CAND_{short_hash(idempotency_key, 10)}"


def family_id_from_seq(n: int) -> str:
    return f"FAM_{n:06d}"


def split_group_from_seq(n: int) -> str:
    return f"GROUP_{n:06d}"


def passage_id_from_seq(n: int) -> str:
    return f"P_{n:06d}"


def variant_id(family_id: str, label: str) -> str:
    return f"V_{LABEL_TO_CODE[label]}_{family_id.split('_', 1)[1]}"


def blueprint_id(candidate_key: str) -> str:
    return f"BP_{short_hash(candidate_key, 10)}"


def claim_id(i: int) -> str:
    return f"C{i}"


def fact_id(i: int) -> str:
    return f"F{i}"


def span_id(i: int) -> str:
    return f"S{i}"


def document_id(idempotency_key: str) -> str:
    return f"DOC_{short_hash(idempotency_key, 10)}"


def make_idempotency_key(*parts: object) -> str:
    return sha256_json(list(parts))


_ID_RE = {
    "family": re.compile(r"^FAM_\d{6}$"),
    "group": re.compile(r"^GROUP_\d{6}$"),
    "passage": re.compile(r"^P_\d{6}$"),
    "blueprint": re.compile(r"^BP_[0-9a-f]{10}$"),
    "claim": re.compile(r"^C\d{1,2}$"),
    "fact": re.compile(r"^F\d{1,3}$"),
    "span": re.compile(r"^S\d{1,3}$"),
}


def is_valid_id(kind: str, value: str) -> bool:
    pat = _ID_RE.get(kind)
    return bool(pat and pat.match(value or ""))
