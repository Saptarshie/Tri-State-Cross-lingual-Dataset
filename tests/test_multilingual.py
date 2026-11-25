from __future__ import annotations

from types import SimpleNamespace

import pytest

from tristate.config import load_config as load_base_config
from tristate.multilingual.config import load_config as load_ml_config
from tristate.multilingual.ledger import SourceError, claim_cards, preflight
from tristate.multilingual.models import (
    ClaimReviewItem,
    ClaimReviewPayload,
    ClaimTranslationItem,
    ClaimTranslationPayload,
    FamilyReviewPayload,
    SentenceTranslationItem,
    WindowTranslationPayload,
)
from tristate.multilingual.pipeline import TranslationPipeline, build_windows, script_ok, number_tokens
from tristate.schema import (
    Blueprint,
    Claim,
    ClaimRelation,
    EditLog,
    Entity,
    Fact,
    Family,
    PassageRecord,
    SemanticRepresentation,
    Variant,
)


def make_family() -> Family:
    texts = {
        "SUPPORTED": "The river is monitored. Fish counts rise in spring.",
        "CONTRADICTED": "The river is not monitored. Fish counts fall in spring.",
        "UNSUPPORTED": "The valley has a new bridge. Visitors arrive in summer.",
    }
    claims = [
        Claim(claim_id="C1", claim_text="The river is monitored.", fact_ids=["F1"], claim_type="PROCEDURAL"),
        Claim(claim_id="C2", claim_text="Fish counts rise in spring.", fact_ids=["F2"], claim_type="ENTITY_RELATION"),
    ]
    variants = {}
    for label, text in texts.items():
        rels = [
            ClaimRelation(claim_id=c.claim_id, relation=label)
            for c in claims
        ]
        variants[label] = Variant(
            variant_id=f"VAR_{label}",
            label=label,
            text=text,
            token_count=max(1, len(text.split())),
            checksum=f"checksum-{label}",
            edit_history=EditLog(base_checksum="base", result_checksum=f"result-{label}"),
            relations_by_claim=rels,
        )
    return Family(
        family_id="FAM_TEST",
        split_group_id="GROUP_TEST",
        blueprint=Blueprint(
            blueprint_id="BP_TEST",
            topic_path=["Environment"],
            main_concept="river monitoring",
        ),
        base_passage=PassageRecord(
            passage_id="P_TEST",
            text=texts["SUPPORTED"],
            genre="report",
            tone="neutral_explanatory",
            structure="multi_section_report",
        ),
        semantic_representation=SemanticRepresentation(
            summary="river monitoring",
            entities=[Entity(name="river", entity_type="LOCATION")],
            facts=[
                Fact(fact_id="F1", subject="river", predicate="is_monitored", object="true"),
                Fact(fact_id="F2", subject="fish counts", predicate="rise", object="spring"),
            ],
        ),
        claim_set=claims,
        variants=variants,
        split="train",
        quality={"status": "ACCEPTED", "hard_checks_passed": True},
    )


class MockClient:
    def __init__(self, *, drift: bool = False):
        self.cfg = SimpleNamespace(
            llm=SimpleNamespace(
                generator=SimpleNamespace(name="mock-translator"),
                validator=SimpleNamespace(name="mock-reviewer"),
            )
        )
        self.drift = drift
        self._calls = 0

    def structured(self, prompt, variables, schema, model_cfg, stage=None, family_id=None):
        self._calls += 1
        if prompt == "multilingual_glossary":
            from tristate.multilingual.models import GlossaryPayload

            payload = GlossaryPayload(
                glossary=[
                    {**g, "target_term": f"বাংলা {g['source_term']}"}
                    for g in self._loads(variables["glossary_json"])
                ]
            )
        elif prompt == "multilingual_claim_translation":
            payload = ClaimTranslationPayload(
                claims=[
                    ClaimTranslationItem(claim_id=cid, target_text=f"দাবি {cid}।")
                    for cid in [
                        c["claim_id"] for c in self._loads(variables["claim_cards_json"])
                    ]
                ]
            )
        elif prompt == "multilingual_claim_review":
            payload = ClaimReviewPayload(
                claims=[
                    ClaimReviewItem(claim_id=c["claim_id"], status="PASS")
                    for c in self._loads(variables["target_claims_json"])
                ]
            )
        elif prompt == "multilingual_window_translation":
            ids = self._loads(variables["sentence_ids_json"])
            payload = WindowTranslationPayload(
                sentences=[SentenceTranslationItem(sentence_id=sid, target_text=f"বাক্য {variables['label']} {sid}।") for sid in ids]
            )
        elif prompt == "multilingual_window_review":
            from tristate.multilingual.models import WindowReview

            payload = WindowReview(window_id="W001", verdict="PASS")
        elif prompt == "multilingual_family_review":
            from tristate.multilingual.models import ClaimFinding

            expected = self._loads(variables["expected_relations_json"])
            findings = []
            for cid, relation in expected.items():
                observed = {"SUPPORTED": "ENTAILED", "CONTRADICTED": "CONTRADICTED", "UNSUPPORTED": "NEUTRAL"}[relation]
                if self.drift and relation == "CONTRADICTED":
                    observed = "ENTAILED"
                findings.append(
                    ClaimFinding(
                        claim_id=cid,
                        observed_relation=observed,
                        expected_relation=relation,
                        evidence_sentence_ids=["S1"],
                    )
                )
            payload = FamilyReviewPayload(
                variant_label=variables["label"],
                verdict="PASS",
                findings=findings,
            )
        else:
            raise AssertionError(f"unexpected prompt {prompt}")
        return SimpleNamespace(data=payload)

    def stats(self):
        return {"calls": self._calls, "cost_usd": 0.0}

    @staticmethod
    def _loads(value):
        import json

        return json.loads(value)


class SurgicalRepairMock(MockClient):
    def __init__(self):
        super().__init__()
        self.window_requests: list[list[str]] = []
        self.window_reviews = 0

    def structured(self, prompt, variables, schema, model_cfg, stage=None, family_id=None):
        if prompt == "multilingual_window_translation":
            self.window_requests.append(list(self._loads(variables["sentence_ids_json"])))
        if prompt == "multilingual_window_review":
            self.window_reviews += 1
            if self.window_reviews == 1:
                from tristate.multilingual.models import WindowReview

                return SimpleNamespace(
                    data=WindowReview(
                        window_id="W001",
                        verdict="REPAIR",
                        affected_sentence_ids=["S1"],
                        feedback="S1: replace the tense.",
                    )
                )
        return super().structured(prompt, variables, schema, model_cfg, stage=stage, family_id=family_id)


class FixerMock(SurgicalRepairMock):
    def __init__(self):
        super().__init__()
        self.fixer_actions = 0

    def structured(self, prompt, variables, schema, model_cfg, stage=None, family_id=None):
        if prompt == "multilingual_fixer":
            from tristate.multilingual.fixer import FixerAction, FixerEdit

            self.fixer_actions += 1
            if self.fixer_actions == 1:
                return SimpleNamespace(
                    data=FixerAction(
                        action="apply_sentence_edits",
                        edits=[FixerEdit(sentence_id="S1", target_text="বাক্য FIXED S1।", reason="repair")],
                    )
                )
            return SimpleNamespace(data=FixerAction(action="run_review"))
        return super().structured(prompt, variables, schema, model_cfg, stage=stage, family_id=family_id)


@pytest.fixture
def ml(tmp_path):
    return load_ml_config(
        overrides={
            "source_dir": str(tmp_path / "source"),
            "output_dir": str(tmp_path / "translations"),
            "window": {"target_words_min": 2, "target_words_max": 8, "context_sentences": 1, "max_repairs": 1},
            "fixer": {"enabled": False},
        }
    )


@pytest.fixture
def base_cfg(tmp_path):
    return load_base_config(overrides={"project": {"output_dir": str(tmp_path / "base")}})


def test_preflight_and_cards_are_deterministic():
    family = make_family()
    report = preflight(family)
    assert report["claims"] == 2
    assert report["variants"] == 3
    cards = claim_cards(family)
    assert [c.claim_id for c in cards] == ["C1", "C2"]
    assert cards[0].negation is False
    # The CONTRADICTED variant contains negation, but cards are built from the
    # canonical claim, not from a variant's surface form.
    assert cards[1].numbers == []


def test_windows_cover_every_sentence_once():
    text = "One two three. Four five six. Seven eight nine. Ten eleven twelve."
    windows = build_windows(text, load_ml_config().window)
    ids = [sid for w in windows for sid in w.sentence_ids]
    assert len(ids) == len(set(ids)) == 4
    assert " ".join(w.source_text for w in windows) == text


def test_windows_preserve_paragraph_boundaries():
    text = "One two. Three four.\n\nFive six. Seven eight."
    windows = build_windows(text, load_ml_config().window)
    by_id = {sid: p for w in windows for sid, p in w.paragraph_by_sentence.items()}
    assert by_id["S1"] == by_id["S2"] == 0
    assert by_id["S3"] == by_id["S4"] == 1


def test_script_policy_is_explicit():
    assert script_ok("এটি একটি বাংলা বাক্য।", "native")
    assert not script_ok("ekti bangla bakyo", "native")
    assert not script_ok("এটি বাংলা", "romanized")
    assert script_ok("eta bangla", "romanized")
    assert script_ok("mixed বাংলা text", "mixed")


def test_number_tokens_handle_bengali_suffixes_and_separators():
    assert "1400" in number_tokens("প্রায় 1,400টি অ্যাকাউন্ট")
    assert number_tokens("১,৪০০টি") == {"1400"}


def test_mock_pipeline_accepts_three_aligned_variants(ml, base_cfg):
    family = make_family()
    source_before = family.variants["SUPPORTED"].text
    pipe = TranslationPipeline(ml, base_cfg, "bn_in_native", MockClient())
    rec = pipe.translate_family(family)
    assert rec.status == "ACCEPTED", rec.rejection_reasons
    assert len(rec.variants) == 3
    assert {v.label for v in rec.variants} == {"SUPPORTED", "CONTRADICTED", "UNSUPPORTED"}
    assert {v.target_text for v in rec.variants}  # all variants were translated
    assert {c.claim_id for c in rec.target_claims} == {"C1", "C2"}
    assert family.variants["SUPPORTED"].text == source_before
    assert rec.created_at and rec.updated_at


def test_relation_drift_is_quarantined(ml, base_cfg):
    rec = TranslationPipeline(ml, base_cfg, "bn_in_native", MockClient(drift=True)).translate_family(make_family())
    assert rec.status == "QUARANTINED"
    assert any("relation drift" in r for r in rec.rejection_reasons)


def test_repair_only_resends_affected_sentences(ml, base_cfg):
    ml.window.target_words_min = 100
    ml.window.target_words_max = 100
    ml.window.concurrency = 1
    mock = SurgicalRepairMock()
    rec = TranslationPipeline(ml, base_cfg, "bn_in_native", mock).translate_family(make_family())
    assert rec.status == "ACCEPTED", rec.rejection_reasons
    # First translation covers both source sentences; the repair request
    # contains only the reviewer-selected S1, then merges it back.
    assert mock.window_requests[0] == ["S1", "S2"]
    assert mock.window_requests[1] == ["S1"]


def test_react_fixer_applies_sentence_edit_and_accepts(ml, base_cfg):
    ml.fixer.enabled = True
    ml.window.target_words_min = 100
    ml.window.target_words_max = 100
    ml.window.concurrency = 1
    mock = FixerMock()
    rec = TranslationPipeline(ml, base_cfg, "bn_in_native", mock).translate_family(make_family())
    assert rec.status == "ACCEPTED", rec.rejection_reasons
    assert mock.fixer_actions >= 2
    fixed = rec.variants[0].target_text
    assert "FIXED" in fixed
    assert rec.variants[0].sentences[0].source_text == "The river is monitored."


def test_run_profile_processes_families_concurrently(ml, base_cfg, tmp_path):
    from tristate.multilingual.pipeline import run_profile

    src = tmp_path / "source" / "families"
    src.mkdir(parents=True)
    for i in (1, 2):
        family = make_family()
        family.family_id = f"FAM_TEST{i}"
        (src / f"FAM_TEST{i}.json").write_text(family.model_dump_json(indent=2), encoding="utf-8")
    manifest = run_profile(ml, base_cfg, "bn_in_native", MockClient(), limit=2, concurrency=2)
    assert manifest.accepted == 2
    assert manifest.status == "complete"


def test_pending_source_is_rejected():
    family = make_family()
    family.quality.status = "PENDING"
    with pytest.raises(SourceError):
        preflight(family)
