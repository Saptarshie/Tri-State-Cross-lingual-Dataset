from __future__ import annotations

from tristate.corpus import ingest_local_paths, segment_text, corpus_summary
from tristate.store import Store


def test_segment_text_respects_token_band():
    text = " ".join(f"Sentence number {i} describes a small factual detail about the system." for i in range(30))
    chunks = segment_text(text, 40, 90)
    assert len(chunks) >= 2
    assert all(c.token_count <= 100 for c in chunks)
    assert all(c.text and c.start_char < c.end_char for c in chunks)


def test_segment_drops_documents_below_the_token_band():
    # passages are meant to look like retrieved chunks; a single 8-token fragment is not
    # a usable passage and is dropped rather than padded
    chunks = segment_text("A single short sentence with a few words.", 80, 300)
    assert chunks == []


def test_ingest_local_documents_and_dedupe(cfg, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    body = " ".join(
        f"The laboratory published result {i} with a measured value of {i * 3} units."
        for i in range(20)
    )
    (src / "a.txt").write_text(body, encoding="utf-8")
    (src / "b.txt").write_text(body, encoding="utf-8")  # identical content: dedupe
    (src / "c.md").write_text(body + " An additional closing sentence appears here.", encoding="utf-8")

    store = Store(cfg.data_dir)
    try:
        created = ingest_local_paths(store, cfg, [src])
        assert created
        assert len({c["text_hash"] for c in created}) == len(created)
        docs = list((cfg.data_dir / "corpus" / "documents").glob("*.json"))
        assert len(docs) == 2
        summary = corpus_summary(store)
        assert summary["documents"] == 2
        assert summary["passage_candidates"] == len(created)
        assert created[0]["chunking"]["strategy"] == "sentence_window"
        assert created[0]["source_type"] == "local_document"
    finally:
        store.close()


def test_non_english_document_is_skipped(cfg, tmp_path):
    src = tmp_path / "src2"
    src.mkdir()
    (src / "bn.txt").write_text("এটি সম্পূর্ণ বাংলা লেখা যা ইংরেজি নয়। " * 20, encoding="utf-8")
    store = Store(cfg.data_dir)
    try:
        created = ingest_local_paths(store, cfg, [src])
        assert created == []
    finally:
        store.close()
