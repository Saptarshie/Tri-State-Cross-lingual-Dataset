from __future__ import annotations

import pytest
from pydantic import ValidationError

from tristate.schema import (
    Claim,
    Family,
    PassageRecord,
    Span,
    Variant,
    normalize_triple,
)


def _variant(label: str, text: str) -> Variant:
    from tristate.schema import EditLog
    from tristate.util import sha256_text, approx_tokens

    return Variant(
        variant_id=f"V_{label[0]}_000001",
        label=label,  # type: ignore[arg-type]
        text=text,
        token_count=approx_tokens(text),
        checksum=sha256_text(text),
        edit_history=EditLog(base_checksum="x", result_checksum="y"),
    )


def _family(**overrides):
    claim = Claim(claim_id="C1", claim_text="Orion was developed by Alice Brown.")
    base = "Orion was developed by Alice Brown in 2012 and uses a virtual machine."
    data = dict(
        family_id="FAM_000001",
        split_group_id="GROUP_000001",
        blueprint={
            "blueprint_id": "BP_0000000001",
            "topic_path": ["Technology"],
            "main_concept": "A fictional language.",
        },
        base_passage=PassageRecord(
            passage_id="P_000001", text=base, genre="technical_explanation",
            tone="neutral_explanatory", structure="paragraph",
        ),
        semantic_representation={"summary": "Orion profile.", "entities": [], "facts": []},
        claim_set=[claim],
        variants={
            "SUPPORTED": _variant("SUPPORTED", base),
            "CONTRADICTED": _variant("CONTRADICTED", "Orion was developed by Bob Smith in 2004."),
            "UNSUPPORTED": _variant("UNSUPPORTED", "Orion uses a virtual machine and a small toolchain."),
        },
        quality={"status": "ACCEPTED", "hard_checks_passed": True},
    )
    data.update(overrides)
    return Family(**data)


def test_family_requires_three_labels():
    fam = _family()
    del fam.variants["UNSUPPORTED"]
    with pytest.raises(ValidationError):
        Family(**fam.model_dump(mode="json"))


def test_duplicate_claim_ids_rejected():
    claim = Claim(claim_id="C1", claim_text="Orion was developed by Alice Brown.")
    with pytest.raises(ValidationError):
        _family(claim_set=[claim, claim])


def test_accepted_family_needs_distinct_variants():
    base = "Orion was developed by Alice Brown in 2012 and uses a virtual machine."
    with pytest.raises(ValidationError):
        _family(
            variants={
                "SUPPORTED": _variant("SUPPORTED", base),
                "CONTRADICTED": _variant("CONTRADICTED", base),
                "UNSUPPORTED": _variant("UNSUPPORTED", base),
            }
        )


def test_flattened_rows_share_claim_set():
    fam = _family()
    rows = fam.flattened_rows()
    assert len(rows) == 3
    assert {r["label"] for r in rows} == {"SUPPORTED", "CONTRADICTED", "UNSUPPORTED"}
    assert all(r["claim_ids"] == ["C1"] for r in rows)
    assert all(r["family_id"] == "FAM_000001" for r in rows)


def test_normalize_triple_strips_articles_and_case():
    assert normalize_triple("The Orion", "Developed By", "Alice Brown") == (
        "orion", "developed_by", "alice brown"
    )


def test_span_rejects_inverted_offsets():
    with pytest.raises(ValidationError):
        Span(sentence_id="S1", start_char=10, end_char=5, text="bad")
