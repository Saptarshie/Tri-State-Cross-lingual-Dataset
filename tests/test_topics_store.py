from __future__ import annotations


from tristate.store import Store
from tristate.topics import (
    coverage_report,
    record_outcome,
    save_graph,
    seed_graph,
    select_topics,
)


def test_seed_graph_has_two_levels(cfg):
    graph = seed_graph(cfg.data_dir)
    assert graph.nodes
    assert graph.totals()["leaves"] >= 10
    paths = [graph.path_of(n.topic_id) for n in graph.leaves()]
    assert all(len(p) >= 2 for p in paths)


def test_seed_graph_is_idempotent(cfg):
    a = seed_graph(cfg.data_dir)
    b = seed_graph(cfg.data_dir)
    assert a.model_dump()["nodes"].keys() == b.model_dump()["nodes"].keys()


def test_selection_is_deterministic(cfg):
    graph = seed_graph(cfg.data_dir)
    a = select_topics(graph, 4, seed=7)
    b = select_topics(graph, 4, seed=7)
    assert [x.topic_id for x in a] == [x.topic_id for x in b]
    assert all(0 <= x.score for x in a)


def test_selection_prefers_underrepresented_topics(cfg):
    graph = seed_graph(cfg.data_dir)
    leaves = graph.leaves()
    for node in leaves:
        node.accepted_family_count = 0.0
    busy = leaves[0]
    busy.accepted_family_count = 50.0
    chosen = select_topics(graph, 1, seed=3)
    assert chosen and chosen[0].topic_id != busy.topic_id


def test_outcome_propagates_to_parent(cfg):
    graph = seed_graph(cfg.data_dir)
    leaf = graph.leaves()[0]
    parent_id = leaf.parent_topic_ids[0]
    before = graph.nodes[parent_id].accepted_family_count
    record_outcome(graph, leaf.topic_id, accepted=True)
    assert leaf.accepted_family_count >= 1
    assert graph.nodes[parent_id].accepted_family_count > before
    save_graph(graph, cfg.data_dir)
    assert graph.nodes[parent_id].accepted_family_count > before


def test_coverage_report_fields(cfg):
    graph = seed_graph(cfg.data_dir)
    rows = coverage_report(graph)
    assert rows and {"topic_id", "accepted", "target", "path"} <= set(rows[0])
    # every leaf lineage is represented
    assert any(" > " in r["path"] for r in rows)


def test_store_candidate_idempotency(cfg):
    store = Store(cfg.data_dir)
    try:
        cid, created = store.upsert_candidate("key-1", "CAND_aaaaaaaaaa", ["T_X"], ["Tech"])
        assert created
        cid2, created2 = store.upsert_candidate("key-1", "CAND_different", ["T_X"], ["Tech"])
        assert cid2 == cid and not created2
        assert store.next_counter("x") == 1
        assert store.next_counter("x") == 2
    finally:
        store.close()


def test_store_jobs_and_quarantine(cfg):
    store = Store(cfg.data_dir)
    try:
        store.upsert_candidate("k", "CAND_bbbbbbbbbb", ["T"], ["Tech"])
        store.start_job("CAND_bbbbbbbbbb", "blueprint", "m", "v1")
        store.finish_job("CAND_bbbbbbbbbb", "blueprint", "SUCCEEDED", str(cfg.data_dir / "x.json"))
        assert store.job_status("CAND_bbbbbbbbbb", "blueprint") == "SUCCEEDED"
        assert store.job("CAND_bbbbbbbbbb", "blueprint")["attempt"] == 1
        store.start_job("CAND_bbbbbbbbbb", "blueprint", "m", "v1")
        assert store.job("CAND_bbbbbbbbbb", "blueprint")["attempt"] == 2
        store.quarantine("CAND_bbbbbbbbbb", ["edit_failed: test"], "variant_SUPPORTED")
        assert store.get_candidate("CAND_bbbbbbbbbb")["status"] == "QUARANTINED"
        assert (cfg.data_dir / "quarantine" / "CAND_bbbbbbbbbb.json").exists()
    finally:
        store.close()
