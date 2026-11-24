from __future__ import annotations

from tristate.spans import (
    resolve_quote,
    sentences_for_prompt,
    sentence_index,
    span_from_offsets,
)

TEXT = (
    "The Orion language was developed by Alice Brown in 2012. "
    "Orion uses a register-based virtual machine and was designed for embedded use."
)


def test_sentence_index_offsets_reconstruct_text():
    refs = sentence_index(TEXT)
    assert len(refs) == 2
    for r in refs:
        assert TEXT[r.start_char:r.end_char] == r.text
    assert refs[0].sentence_id == "S1"


def test_sentences_for_prompt_shape():
    rows = sentences_for_prompt(TEXT)
    assert rows[0]["sentence_id"] == "S1"
    assert "chars" in rows[0] and len(rows[0]["chars"]) == 2


def test_resolve_quote_exact_in_sentence():
    span = resolve_quote(TEXT, "S1", "Alice Brown")
    assert span is not None
    assert TEXT[span.start_char:span.end_char] == "Alice Brown"
    assert span.sentence_id == "S1"


def test_resolve_quote_whitespace_tolerant():
    span = resolve_quote(TEXT, "S1", "Alice   Brown")
    assert span is not None
    assert "Alice" in span.text and "Brown" in span.text


def test_resolve_quote_absent_returns_none():
    assert resolve_quote(TEXT, "S1", "Guido van Rossum") is None


def test_span_from_offsets():
    span = span_from_offsets(TEXT, 0, 23)
    assert span is not None and span.text.strip() == "The Orion language was"
