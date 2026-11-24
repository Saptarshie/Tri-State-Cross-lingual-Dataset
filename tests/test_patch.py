from __future__ import annotations

import pytest

from tristate.patch import PatchError, apply_patches, coverage_gaps
from tristate.schema import Patch
from tristate.util import sha256_text

BASE = (
    "The Orion language was developed by Alice Brown in 2012. "
    "Orion uses a register-based virtual machine and was designed primarily for embedded applications."
)


def p(op, sentence, original, replacement, claims=("C1",)):
    return Patch(
        operation=op,
        target_sentence_id=sentence,
        original_text=original,
        replacement_text=replacement,
        affected_claim_ids=list(claims),
        reason="test",
    )


def test_exact_patches_apply_and_offsets_are_recorded():
    res = apply_patches(
        BASE,
        [
            p("ENTITY_SUBSTITUTION", "S1", "Alice Brown", "Bob Smith"),
            p("NUMERICAL_MUTATION", "S1", "2012", "2015", ("C2",)),
        ],
    )
    assert "Bob Smith" in res.text and "2015" in res.text
    assert "Alice Brown" not in res.text and "2012" not in res.text
    assert [e.start_char for e in res.log.entries] == sorted(e.start_char for e in res.log.entries)
    assert res.log.is_pure_patch
    assert "Alice Brown" in res.log.unified_diff
    assert all(e.matched_exactly for e in res.log.entries)


def test_untouched_text_is_byte_identical():
    res = apply_patches(BASE, [p("ENTITY_SUBSTITUTION", "S2", "embedded", "desktop")])
    assert res.text.startswith("The Orion language was developed by Alice Brown in 2012.")
    assert res.text.endswith("desktop applications.")


def test_whitespace_tolerant_match():
    patch = p("DELETE_SPAN", "S1", "developed  by Alice Brown", "")
    # doubled space in the target must still resolve (non-exact, recorded)
    res = apply_patches(BASE, [patch])
    assert "Alice Brown" not in res.text
    assert res.log.entries[0].matched_exactly is False


def test_target_not_found_raises():
    with pytest.raises(PatchError) as exc:
        apply_patches(BASE, [p("DELETE_SPAN", "S1", "Guido van Rossum", "")])
    assert exc.value.code == "TARGET_NOT_FOUND"


def test_ambiguous_target_raises():
    text = "Orion grew. Orion grew again."
    with pytest.raises(PatchError) as exc:
        apply_patches(text, [Patch(operation="DELETE_SPAN", original_text="Orion grew", affected_claim_ids=["C1"])])
    assert exc.value.code in {"AMBIGUOUS_TARGET", "TARGET_NOT_FOUND"} or "Orion grew" in str(exc.value)


def test_overlapping_patches_rejected():
    text = "The Orion language was developed by Alice Brown."
    with pytest.raises(PatchError) as exc:
        apply_patches(
            text,
            [
                Patch(operation="REPLACE_CLAUSE", original_text="Orion language", replacement_text="Orion system", affected_claim_ids=["C1"]),
                Patch(operation="ENTITY_SUBSTITUTION", original_text="language was developed", replacement_text="platform was built", affected_claim_ids=["C1"]),
            ],
        )
    assert exc.value.code in {"OVERLAPPING_PATCHES", "AMBIGUOUS_TARGET"}


def test_wrong_sentence_id_falls_back_to_passage_scope():
    res = apply_patches(
        BASE,
        [Patch(operation="CATEGORY_SUBSTITUTION", target_sentence_id="S1",
               original_text="embedded applications", replacement_text="desktop applications",
               affected_claim_ids=["C1"])],
    )
    assert "desktop applications" in res.text
    assert "embedded applications" not in res.text


def test_noop_patch_rejected():
    with pytest.raises(PatchError) as exc:
        apply_patches(BASE, [p("ENTITY_SUBSTITUTION", "S1", "Alice Brown", "Alice Brown")])
    assert exc.value.code == "NOOP_PATCH"


def test_checksum_mismatch_rejected():
    with pytest.raises(PatchError) as exc:
        apply_patches(BASE, [p("ENTITY_SUBSTITUTION", "S1", "Alice Brown", "Bob")], base_checksum="deadbeef")
    assert exc.value.code == "BASE_CHECKSUM_MISMATCH"


def test_deletion_cleanup_removes_double_spaces():
    res = apply_patches(BASE, [p("DELETE_SPAN", "S2", " and was designed primarily for embedded applications", "")])
    assert "  " not in res.text
    assert res.text.endswith("register-based virtual machine.")


def test_coverage_gaps():
    patches = [p("ENTITY_SUBSTITUTION", "S1", "Alice Brown", "Bob", ("C1",))]
    assert coverage_gaps(patches, ["C1", "C2"]) == ["C2"]
    assert coverage_gaps(patches, ["C1"]) == []


def test_base_text_not_mutated():
    original = BASE
    apply_patches(BASE, [p("ENTITY_SUBSTITUTION", "S1", "Alice Brown", "Bob")])
    assert BASE == original
    assert sha256_text(BASE) == sha256_text(original)
