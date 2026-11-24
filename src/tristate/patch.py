"""Deterministic patch engine.

Rules enforced here (objective §9.5):
* target spans must actually match the immutable base text;
* patches apply deterministically, never overlapping;
* untouched spans are byte-identical in the output;
* before/after text and character offsets are recorded;
* the original passage is never mutated.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from .schema import AppliedPatch, EditLog, Patch
from .spans import find_sentence, sentence_index
from .util import normalize_for_match, sha256_text, truncate


class PatchError(RuntimeError):
    def __init__(self, code: str, message: str, patch: Patch | None = None):
        super().__init__(message)
        self.code = code
        self.patch = patch

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "message": str(self),
            "patch": self.patch.model_dump(mode="json") if self.patch else None,
        }


@dataclass
class PatchResult:
    text: str
    log: EditLog


def _normalized_offsets(haystack: str, needle_normalized: str) -> tuple[int, int] | None:
    """Locate a whitespace/punctuation-normalized needle inside raw text."""
    norm_chars: list[str] = []
    mapping: list[int] = []
    for i, ch in enumerate(haystack):
        lowered = ch.lower()
        if lowered.isspace():
            if norm_chars and norm_chars[-1] == " ":
                continue
            norm_chars.append(" ")
            mapping.append(i)
        else:
            norm_chars.append(lowered)
            mapping.append(i)
    norm = "".join(norm_chars)
    pos = norm.find(needle_normalized)
    if pos < 0 or norm.count(needle_normalized) != 1:
        return None
    start = mapping[pos]
    end = mapping[pos + len(needle_normalized) - 1] + 1
    return start, end


def _locate(base: str, patch: Patch) -> tuple[int, int, bool]:
    """Return (start, end, exact) for the patch target, or raise PatchError."""
    needle = patch.original_text or ""
    if not needle.strip():
        raise PatchError("EMPTY_TARGET", "patch.original_text is empty", patch)

    refs = sentence_index(base)
    ref = find_sentence(refs, patch.target_sentence_id)
    scopes = [ref.text] if ref else [r.text for r in refs]
    scope_offsets = [ref.start_char] if ref else [r.start_char for r in refs]

    hits: list[tuple[int, int, bool]] = []
    for scope, offset in zip(scopes, scope_offsets):
        count = scope.count(needle)
        if count == 1:
            idx = scope.find(needle)
            hits.append((offset + idx, offset + idx + len(needle), True))
        elif count > 1:
            # ambiguous even inside the requested sentence
            raise PatchError(
                "AMBIGUOUS_TARGET",
                f"original_text occurs {count} times in {patch.target_sentence_id or 'passage'}",
                patch,
            )
    if len(hits) > 1:
        exact_unique = [h for h in hits if h[2]]
        if len(exact_unique) == 1:
            return exact_unique[0]
        raise PatchError("AMBIGUOUS_TARGET", "original_text matched multiple sentences", patch)
    if len(hits) == 1:
        return hits[0]

    # whitespace-tolerant fallback within the requested sentence, then whole passage
    if ref is not None:
        located = _normalized_offsets(ref.text, normalize_for_match(needle))
        if located:
            s, e = located
            return ref.start_char + s, ref.start_char + e, False
    located = _normalized_offsets(base, normalize_for_match(needle))
    if located:
        return located[0], located[1], False

    raise PatchError(
        "TARGET_NOT_FOUND",
        f"original_text not found in base passage: {truncate(needle, 120)!r}",
        patch,
    )


def _cleanup(text: str) -> str:
    t = re.sub(r"[ \t]{2,}", " ", text)
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r"([,;:])(?=[A-Za-z])", r"\1 ", t)
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r"\s+\)", ")", t)
    t = re.sub(r"\s*\n\s*", " ", t)
    return t.strip()


def apply_patches(
    base_text: str,
    patches: list[Patch],
    base_checksum: str | None = None,
    allow_cleanup: bool = True,
) -> PatchResult:
    if base_checksum and sha256_text(base_text) != base_checksum:
        raise PatchError("BASE_CHECKSUM_MISMATCH", "base passage changed since planning")
    if not patches:
        raise PatchError("NO_PATCHES", "no patches supplied")

    located: list[tuple[int, int, Patch, bool]] = []
    for p in patches:
        if p.replacement_text == p.original_text:
            raise PatchError("NOOP_PATCH", "replacement equals original", p)
        start, end, exact = _locate(base_text, p)
        located.append((start, end, p, exact))

    located.sort(key=lambda x: x[0])
    for prev, cur in zip(located, located[1:]):
        if cur[0] < prev[1]:
            raise PatchError(
                "OVERLAPPING_PATCHES",
                f"patches overlap at chars {cur[0]}-{cur[1]}",
                cur[2],
            )

    out_parts: list[str] = []
    entries: list[AppliedPatch] = []
    cursor = 0
    delta = 0
    for start, end, patch, exact in located:
        out_parts.append(base_text[cursor:start])
        after_text = patch.replacement_text
        out_parts.append(after_text)
        entries.append(
            AppliedPatch(
                operation=patch.operation,
                target_sentence_id=patch.target_sentence_id,
                original_text=patch.original_text,
                replacement_text=patch.replacement_text,
                affected_claim_ids=list(patch.affected_claim_ids),
                reason=patch.reason,
                start_char=start,
                end_char=end,
                matched_exactly=exact,
                after_text=after_text,
            )
        )
        delta += len(after_text) - (end - start)
        cursor = end
    out_parts.append(base_text[cursor:])
    result = "".join(out_parts)

    notes: list[str] = []
    if not all(e.matched_exactly for e in entries):
        notes.append("normalized_whitespace_match")
    if allow_cleanup:
        cleaned = _cleanup(result)
        if cleaned != result:
            notes.append("whitespace_cleanup")
            result = cleaned
    if not result.strip():
        raise PatchError("EMPTY_RESULT", "editing produced an empty passage")

    diff = "\n".join(
        difflib.unified_diff(
            base_text.splitlines(),
            result.splitlines(),
            fromfile="base",
            tofile="edited",
            lineterm="",
            n=2,
        )
    )
    log = EditLog(
        entries=entries,
        is_pure_patch=True,
        base_checksum=sha256_text(base_text),
        result_checksum=sha256_text(result),
        unified_diff=diff,
        attempts=1,
        notes=notes,
    )
    return PatchResult(text=result, log=log)


def coverage_gaps(patches: list[Patch], claim_ids: list[str]) -> list[str]:
    covered: set[str] = set()
    for p in patches:
        covered.update(p.affected_claim_ids)
    return [c for c in claim_ids if c not in covered]


def patches_by_claim(patches: list[Patch]) -> dict[str, list[Patch]]:
    out: dict[str, list[Patch]] = {}
    for p in patches:
        for cid in p.affected_claim_ids:
            out.setdefault(cid, []).append(p)
    return out


def describe_patches(patches: list[Patch]) -> str:
    if not patches:
        return "(none)"
    lines = []
    for i, p in enumerate(patches, 1):
        lines.append(
            f"{i}. {p.operation} in {p.target_sentence_id or '?'}: "
            f"{truncate(p.original_text, 60)!r} -> {truncate(p.replacement_text, 60)!r} "
            f"[{','.join(p.affected_claim_ids)}]"
        )
    return "\n".join(lines)
