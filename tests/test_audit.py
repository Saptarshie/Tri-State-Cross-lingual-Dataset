from __future__ import annotations

from tristate.audit import NUMERIC_NAMES, _group_split, audit_shortcuts, feature_matrix


def _rows(families=6):
    rows = []
    for f in range(families):
        for label, text in (
            ("SUPPORTED", f"Family {f} reports a value of {f}. The system was tested in year {2000 + f}."),
            ("CONTRADICTED", f"Family {f} reports a value of {f + 7}. The system was tested in year {1990 + f}."),
            ("UNSUPPORTED", f"Family {f} discusses the system and its general context without stating the value."),
        ):
            rows.append(
                {
                    "family_id": f"FAM_{f:06d}",
                    "variant_id": f"V_{f}_{label[0]}",
                    "label": label,
                    "passage": text,
                    "token_count": len(text.split()),
                }
            )
    return rows


def test_features_are_surface_only():
    X, y, names = feature_matrix(_rows())
    assert names == NUMERIC_NAMES
    assert "edit_count" not in names and "is_pure_patch" not in names
    assert "genre_hash0" not in names and "tone_hash0" not in names
    assert X.shape == (18, len(NUMERIC_NAMES))
    assert set(y.tolist()) == {0, 1, 2}


def test_group_split_keeps_families_together():
    rows = _rows(10)
    train, test = _group_split(rows, fraction=0.7)
    assert len(train) + len(test) == len(rows)
    assert not set(train.tolist()) & set(test.tolist())
    for side in (train, test):
        fams = {rows[i]["family_id"] for i in side.tolist()}
        for fam in fams:
            present = {i for i in side.tolist() if rows[i]["family_id"] == fam}
            assert len(present) == 3


def test_audit_reports_insufficient_data():
    from tristate.config import load_config

    cfg = load_config(overrides={"hnsw": {"embedder": "hashing"}})
    result = audit_shortcuts([], cfg)
    assert result["status"] == "insufficient_data"
    assert result["variants"] == 0
