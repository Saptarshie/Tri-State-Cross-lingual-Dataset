"""Small deterministic helpers shared across the pipeline.

Everything here is deliberately dependency-light and side-effect free so it can
be unit tested without an LLM, a database, or a network.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

# --------------------------------------------------------------------------- #
# Time / hashing
# --------------------------------------------------------------------------- #


def utcnow() -> str:
    """ISO-8601 UTC timestamp with second precision (stable for JSON diffs)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(obj: Any) -> str:
    return sha256_text(canonical_json(obj))


def short_hash(text: str, n: int = 8) -> str:
    return sha256_text(text)[:n]


def stable_seed(*parts: Any) -> int:
    """Deterministic 64-bit seed derived from arbitrary parts."""
    return int(sha256_json(list(parts))[:16], 16)


# --------------------------------------------------------------------------- #
# Durable file IO (atomic, append-only)
# --------------------------------------------------------------------------- #


def atomic_write_text(path: str | Path, text: str) -> Path:
    """Write text atomically: temp file in the same dir, fsync, then replace."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".tmp-", suffix=p.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def atomic_write_json(path: str | Path, obj: Any) -> Path:
    return atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def append_jsonl(path: str | Path, obj: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return p


def read_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# --------------------------------------------------------------------------- #
# Text utilities
# --------------------------------------------------------------------------- #

_ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e",
    "fig", "al", "inc", "ltd", "co", "no", "vol", "ch", "approx", "dept", "est",
}

_SENT_BOUNDARY = re.compile(r"(?<=[.!?])[\"')\]]*\s+")


def split_sentences(text: str) -> list[str]:
    """Best-effort sentence segmentation.

    This is segmentation, not natural-language classification: it never decides
    meaning, it only proposes spans that are validated downstream. Abbreviations
    and initials are protected so offsets remain usable for patch targets.
    """
    text = text.strip()
    if not text:
        return []
    raw: list[str] = []
    start = 0
    for m in _SENT_BOUNDARY.finditer(text):
        end = m.start()
        chunk = text[start:end]
        words = chunk.rstrip("\"')]").rsplit(" ", 1)
        last = words[-1].lower().strip(".,;:!?") if words else ""
        prev_word = text[max(0, end - 8):end].rstrip("\"')]").rsplit(" ", 1)[-1].lower()
        is_abbrev = last in _ABBREV or (len(prev_word) == 2 and prev_word.endswith("."))
        if is_abbrev:
            continue
        raw.append(chunk)
        start = m.end()
    tail = text[start:]
    if tail:
        raw.append(tail)
    out = [s.strip() for s in raw if s.strip()]
    return out or [text]


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_match(text: str) -> str:
    """Aggressive normalisation used only to relocate a patch target."""
    t = normalize_ws(text).lower()
    t = t.replace("\u2019", "'").replace("\u2018", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = t.replace("\u2013", "-").replace("\u2014", "-")
    t = re.sub(r"[^\w\s'%.,;:!?/+-]", " ", t)
    return normalize_ws(t)


def approx_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars per token + word punctuation split).

    Never used for hard token accounting; provider usage numbers are recorded
    separately. Used only for length bands and diversity reports.
    """
    words = re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE)
    return max(1, math.ceil(len(words) * 0.75))


def char_ngrams(text: str, n: int = 5) -> set[str]:
    t = normalize_for_match(text)
    if len(t) <= n:
        return {t} if t else set()
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def word_ngrams(text: str, n: int = 2) -> set[str]:
    words = re.findall(r"[a-z0-9']+", normalize_for_match(text))
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def similarity_features(a: str, b: str) -> dict[str, float]:
    return {
        "jaccard_word_bigram": round(jaccard(word_ngrams(a, 2), word_ngrams(b, 2)), 4),
        "jaccard_char5": round(jaccard(char_ngrams(a, 5), char_ngrams(b, 5)), 4),
        "length_ratio": round(min(len(a), len(b)) / max(len(a), len(b), 1), 4),
    }


def english_score(text: str) -> float:
    """Fraction of alphabetic characters that are Latin-script letters.

    Deterministic script check for the English-only phase; not a language model
    and not a classifier of meaning.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    latin = sum(1 for c in letters if "a" <= c.lower() <= "z")
    return latin / len(letters)


# Meta statements that leak the label or the task itself. These are checked
# literally in generated prose because a passage must never describe the label.
META_PATTERNS = [
    r"\bthis (passage|text|document|context)\s+(does|do)\s+not\s+(mention|say|state|provide)",
    r"\bthe (passage|text|context)\s+(does not|doesn't)\s+(mention|state|say|provide|establish)",
    r"\b(no|not enough|insufficient)\s+(information|evidence)\s+(is\s+)?(provided|given|available)",
    r"\bthe claim\b", r"\bthis claim\b", r"\bthe claim set\b",
    r"\bthe (correct|reference) answer\b",
    r"\blabel(led|ed)?\b", r"\bunsupported\b",
    r"\b(supported|contradicted) by the passage\b",
    r"\bevidence (span|anchor)\b",
    r"\bthe task\b", r"\bas an ai\b",
]


def meta_statement_hits(text: str) -> list[str]:
    low = text.lower()
    hits: list[str] = []
    for pat in META_PATTERNS:
        m = re.search(pat, low)
        if m:
            hits.append(m.group(0))
    return hits


def token_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def content_overlap(a: str, b: str) -> float:
    """Unweighted content-token overlap (Jaccard) for edit-integrity checks."""
    return jaccard(token_set(a), token_set(b))


def containment(a: str, b: str) -> float:
    """Fraction of a's content tokens that appear in b (asymmetric support check)."""
    ta, tb = token_set(a), token_set(b)
    if not ta:
        return 0.0
    return len(ta & tb) / len(ta)


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: max(0, limit - 3)].rstrip() + "..."


def chunked(seq: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]
