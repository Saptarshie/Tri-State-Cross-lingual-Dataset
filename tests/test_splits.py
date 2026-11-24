from __future__ import annotations

from tristate.splits import SplitManager


def test_split_ratios_are_approximately_configured(cfg, tmp_path):
    mgr = SplitManager(tmp_path, cfg, autosave=False)
    for i in range(600):
        mgr.assign(f"FAM_{i:06d}")
    counts = mgr.counts()
    total = sum(counts.values())
    assert total == 600
    assert abs(counts["train"] / total - 0.8) < 0.06
    assert abs(counts["validation"] / total - 0.1) < 0.04
    assert abs(counts["test"] / total - 0.1) < 0.04


def test_assignment_is_stable_and_locked(cfg, tmp_path):
    mgr = SplitManager(tmp_path, cfg, autosave=False)
    first = mgr.assign("FAM_000042")
    second = mgr.assign("FAM_000042")
    assert first == second
    mgr.save()
    reloaded = SplitManager(tmp_path, cfg)
    assert reloaded.split_of("FAM_000042") == first[0]
    assert reloaded.assign("FAM_000042") == first


def test_lineage_groups_share_split(cfg, tmp_path):
    mgr = SplitManager(tmp_path, cfg, autosave=False)
    s1, g1 = mgr.assign("FAM_000001", cluster_key="cand:T_X")
    s2, g2 = mgr.assign("FAM_000002", cluster_key="cand:T_X")
    assert g1 == g2
    assert s1 == s2
    assert mgr.report()["groups"] == 1


def test_different_groups_can_differ(cfg, tmp_path):
    mgr = SplitManager(tmp_path, cfg, autosave=False)
    splits = set()
    for i in range(80):
        splits.add(mgr.assign(f"FAM_{i:06d}", cluster_key=f"cand:T_{i}")[0])
    assert len(splits) >= 2
