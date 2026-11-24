"""Sentence indexing and evidence-span resolution.

The editor and extractor both speak in (sentence_id, quote) pairs; this module turns
those into exact character spans and back. Anchors are recomputed from the immutable
base text, never trusted from the model.
"""

from __future__ import annotations

import re

from .schema import SentenceRef, Span
from .util import split_sentences


def sentence_index(text: str) -> list[SentenceRef]:
    refs: list[SentenceRef] = []
    cursor = 0
    for i, sentence in enumerate(split_sentences(text), start=1):
        idx = text.find(sentence, cursor)
        if idx < 0:
            idx = max(cursor, 0)
        refs.append(
            SentenceRef(
                sentence_id=f"S{i}",
                start_char=idx,
                end_char=idx + len(sentence),
                text=sentence,
            )
        )
        cursor = idx + len(sentence)
    return refs


def sentences_for_prompt(text: str) -> list[dict]:
    return [
        {"sentence_id": r.sentence_id, "text": r.text, "chars": [r.start_char, r.end_char]}
        for r in sentence_index(text)
    ]


def find_sentence(refs: list[SentenceRef], sentence_id: str | None) -> SentenceRef | None:
    if not sentence_id:
        return None
    for r in refs:
        if r.sentence_id == sentence_id:
            return r
    return None


def _whitespace_map(text: str) -> tuple[str, list[int]]:
    """Collapse whitespace and return a map from collapsed index to source index."""
    out: list[str] = []
    mapping: list[int] = []
    prev_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            mapping.append(i)
            prev_space = True
        else:
            out.append(ch)
            mapping.append(i)
            prev_space = False
    return "".join(out), mapping


def resolve_quote(text: str, sentence_id: str | None, quote: str) -> Span | None:
    """Resolve a quoted evidence string to a Span, or None if it is not present."""
    quote = (quote or "").strip()
    if not quote:
        return None
    refs = sentence_index(text)
    ref = find_sentence(refs, sentence_id)
    if ref is not None:
        idx = ref.text.find(quote)
        if idx >= 0 and ref.text.count(quote) == 1:
            start = ref.start_char + idx
            return Span(
                sentence_id=ref.sentence_id,
                start_char=start,
                end_char=start + len(quote),
                text=quote,
            )
        # whitespace-tolerant match inside the target sentence
        ntext, mapping = _whitespace_map(ref.text)
        needle = " ".join(quote.split())
        pos = ntext.find(needle)
        if pos >= 0 and ntext.count(needle) == 1:
            s = ref.start_char + mapping[pos]
            e = ref.start_char + mapping[pos + len(needle) - 1] + 1
            return Span(
                sentence_id=ref.sentence_id,
                start_char=s,
                end_char=e,
                text=text[s:e],
            )

    # fall back to the whole passage, but only when the quote is unambiguous
    if text.count(quote) == 1:
        start = text.find(quote)
        containing = next((r for r in refs if r.start_char <= start < r.end_char), None)
        return Span(
            sentence_id=containing.sentence_id if containing else "S1",
            start_char=start,
            end_char=start + len(quote),
            text=quote,
        )

    ntext, mapping = _whitespace_map(text)
    needle = " ".join(quote.split())
    if needle and ntext.count(needle) == 1:
        pos = ntext.find(needle)
        s = mapping[pos]
        e = mapping[pos + len(needle) - 1] + 1
        containing = next((r for r in refs if r.start_char <= s < r.end_char), None)
        return Span(
            sentence_id=containing.sentence_id if containing else "S1",
            start_char=s,
            end_char=e,
            text=text[s:e],
        )
    return None


def span_from_offsets(text: str, start: int, end: int) -> Span | None:
    if start < 0 or end <= start or end > len(text):
        return None
    refs = sentence_index(text)
    containing = next((r for r in refs if r.start_char <= start < r.end_char), None)
    if containing is None:
        return None
    return Span(
        sentence_id=containing.sentence_id,
        start_char=start,
        end_char=end,
        text=text[start:end],
    )


def exact_substring_count(haystack: str, needle: str) -> int:
    if not needle:
        return 0
    return len(re.findall(re.escape(needle), haystack))
