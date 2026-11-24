from __future__ import annotations

import json

from tristate.ids import candidate_id, family_id_from_seq, is_valid_id, variant_id
from tristate.util import (
    approx_tokens,
    atomic_write_json,
    english_score,
    jaccard,
    meta_statement_hits,
    normalize_for_match,
    read_json,
    sha256_text,
    short_hash,
    split_sentences,
    word_ngrams,
)


def test_split_sentences_handles_abbreviations():
    text = "Dr. Smith joined in 2019. The lab moved to Oslo. It grew fast."
    parts = split_sentences(text)
    assert len(parts) == 3
    assert parts[0].startswith("Dr. Smith")


def test_split_sentences_preserves_text():
    text = "One sentence. Two sentence! Three sentence?"
    assert " ".join(split_sentences(text)) == text


def test_short_hash_is_stable_and_length():
    a = short_hash("hello", 10)
    b = short_hash("hello", 10)
    assert a == b and len(a) == 10 and a != short_hash("hellp", 10)


def test_ids_are_deterministic_and_valid():
    key = sha256_text("candidate-key")
    cid = candidate_id(key)
    assert cid == candidate_id(key)
    assert cid.startswith("CAND_") and len(cid) == 15
    fam = family_id_from_seq(7)
    assert is_valid_id("family", fam)
    assert variant_id(fam, "CONTRADICTED") == "V_C_000007"


def test_english_score_distinguishes_scripts():
    assert english_score("This is plain English text.") == 1.0
    assert english_score("এটি বাংলা") < 0.1


def test_meta_statement_detection_is_label_focused():
    assert meta_statement_hits("The passage does not mention the founder.")
    assert meta_statement_hits("This claim is unsupported by the context.")
    assert meta_statement_hits("The label for this example is hidden.")
    # ordinary prose must not trip the detector
    assert not meta_statement_hits("The bridge supported the full load during testing.")
    assert not meta_statement_hits("A neutral tone was adopted throughout the report.")


def test_atomic_write_and_read(tmp_path):
    p = tmp_path / "nested" / "a.json"
    atomic_write_json(p, {"x": 1})
    assert read_json(p) == {"x": 1}
    assert json.loads(p.read_text()) == {"x": 1}


def test_token_estimate_monotonic():
    assert approx_tokens("word " * 100) > approx_tokens("word " * 10)


def test_normalize_for_match_and_jaccard():
    assert normalize_for_match("  Hello\u2014World  ") == "hello-world"
    assert jaccard(word_ngrams("a b c"), word_ngrams("a b c")) == 1.0
    assert jaccard(word_ngrams("a b c"), word_ngrams("x y z")) == 0.0
