"""Translation pipeline: immutable source -> claim ledger -> windows -> review.

The branch is intentionally staged and resumable.  A family is written only
after all three translated variants pass both window review and family-level
claim-relation review.  Any failure is written to the profile's quarantine
directory with a machine-readable reason; it is never silently relabelled.
"""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..config import Config
from ..llm import LlmClient, LlmError, PermanentLlmError
from ..schema import Family
from ..spans import sentence_index
from ..util import approx_tokens, normalize_ws, sha256_text
from .config import MultilingualCfg, WindowCfg
from .fixer import QualityFixer
from .ledger import (
    LABELS,
    SourceError,
    claim_cards,
    expected_relations,
    preflight,
    seed_glossary,
    source_checksum,
)
from .models import (
    ClaimReviewPayload,
    ClaimSemanticCard,
    ClaimTranslationPayload,
    FamilyReviewPayload,
    FamilyTranslation,
    GlossaryEntry,
    GlossaryPayload,
    SentenceTranslation,
    TargetClaim,
    TranslatedVariant,
    TranslationManifest,
    VariantReview,
    WindowReview,
    WindowTranslationPayload,
)

_BENGALI = re.compile(r"[\u0980-\u09FF]")
_NUMBER = re.compile(r"(?<!\d)(?:\d[\d,]*(?:\.\d+)?%?)(?!\d)")
_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def number_tokens(text: str) -> set[str]:
    """Compare numerals across scripts without treating punctuation as a digit."""

    normalized = text.translate(_BN_DIGITS)
    return {token.strip(".,").replace(",", "") for token in _NUMBER.findall(normalized)}


def critical_numbers(text: str) -> set[str]:
    """Only enforce values that must not drift (years, decimals, percentages).

    Small cardinals may be legitimately spelled out in the target language;
    the semantic reviewer handles those.  Dates/decimals/percentages are
    deterministic anchors and are safe to gate here.
    """

    return {n for n in number_tokens(text) if len(n) >= 4 or "%" in n or "." in n}


class Quarantine(Exception):
    """A family cannot be accepted; the message is stored verbatim."""


@dataclass
class Window:
    window_id: str
    sentence_ids: list[str]
    paragraph_by_sentence: dict[str, int]
    source_text: str
    prev_context: str
    next_context: str


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def build_windows(text: str, cfg: WindowCfg) -> list[Window]:
    """Cover every source sentence exactly once, in order, without overlap."""

    refs = sentence_index(text)
    if not refs:
        raise Quarantine("source variant has no sentences")
    # Paragraph boundaries are source offsets; sentence segmentation must not
    # turn a multi-paragraph document into one flat block of translated text.
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    paragraph_by_sentence: dict[str, int] = {}
    cursor = 0
    for pidx, paragraph in enumerate(paragraphs):
        start = text.find(paragraph, cursor)
        if start < 0:
            start = cursor
        end = start + len(paragraph)
        for ref in refs:
            if start <= ref.start_char < end:
                paragraph_by_sentence[ref.sentence_id] = pidx
        cursor = end
    for ref in refs:
        paragraph_by_sentence.setdefault(ref.sentence_id, 0)
    windows: list[Window] = []
    start = 0
    while start < len(refs):
        end = start
        words = 0
        while end < len(refs):
            n = len(refs[end].text.split())
            if end > start and words + n > cfg.target_words_max:
                break
            words += n
            end += 1
            if words >= cfg.target_words_min:
                break
        if end == start:
            end += 1
        chunk = refs[start:end]
        prev_context = " ".join(r.text for r in refs[max(0, start - cfg.context_sentences):start])
        next_context = " ".join(r.text for r in refs[end:end + cfg.context_sentences])
        windows.append(
            Window(
                window_id=f"W{len(windows) + 1:03d}",
                sentence_ids=[r.sentence_id for r in chunk],
                paragraph_by_sentence={r.sentence_id: paragraph_by_sentence[r.sentence_id] for r in chunk},
                source_text=" ".join(r.text for r in chunk),
                prev_context=prev_context,
                next_context=next_context,
            )
        )
        start = end
    flat = [sid for w in windows for sid in w.sentence_ids]
    expected = [r.sentence_id for r in refs]
    if flat != expected:
        raise Quarantine("window builder did not preserve sentence order/coverage")
    return windows


def _feedback_block(feedback: str) -> str:
    return "" if not feedback.strip() else f"\nREVIEWER FEEDBACK (repair this, do not restate it):\n{feedback.strip()}\n"


def _relation_map(label: str) -> str:
    return {"SUPPORTED": "ENTAILED", "CONTRADICTED": "CONTRADICTED", "UNSUPPORTED": "NEUTRAL"}[label]


def _as_label(observed: str) -> str:
    return {
        "ENTAILED": "SUPPORTED",
        "SUPPORTED": "SUPPORTED",
        "CONTRADICTED": "CONTRADICTED",
        "NEUTRAL": "UNSUPPORTED",
        "UNSUPPORTED": "UNSUPPORTED",
    }.get((observed or "").upper(), "UNCERTAIN")


def script_ok(text: str, policy: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    bengali = len(_BENGALI.findall(text))
    if policy == "native":
        return bool(letters) and bengali / max(1, len(letters)) >= 0.20
    if policy == "romanized":
        return bengali == 0
    return True  # mixed permits either script


class TranslationPipeline:
    def __init__(
        self,
        ml: MultilingualCfg,
        base_cfg: Config,
        profile_id: str,
        client: LlmClient,
        run_id: str = "translate",
    ):
        self.ml = ml
        self.base_cfg = base_cfg
        self.profile = ml.profile(profile_id)
        self.client = client
        self.run_id = run_id
        self.out = ml.output_path / self.profile.profile_id
        self.families_dir = self.out / "families"
        self.quarantine_dir = self.out / "quarantine"
        self.manifest_path = self.out / "manifest.json"
        self.lock = threading.Lock()
        self.families_dir.mkdir(parents=True, exist_ok=True)
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    def _call(self, prompt: str, variables: dict[str, Any], schema, *, stage: str, family_id: str, review: bool = False):
        model = self.client.cfg.llm.validator if review else self.client.cfg.llm.generator
        return self.client.structured(
            prompt,
            variables,
            schema,
            model,
            stage=stage,
            family_id=family_id,
        ).data

    def _glossary(self, family: Family, cards: list[ClaimSemanticCard], seed: list[GlossaryEntry]) -> list[GlossaryEntry]:
        if not seed:
            return []
        payload: GlossaryPayload = self._call(
            "multilingual_glossary",
            {
                "profile_json": _json(self.profile.model_dump(mode="json")),
                "claim_cards_json": _json([c.model_dump(mode="json") for c in cards]),
                "glossary_json": _json([g.model_dump(mode="json") for g in seed]),
            },
            GlossaryPayload,
            stage="translate_glossary",
            family_id=family.family_id,
        )
        got = {g.source_term: g for g in payload.glossary}
        missing = [g.source_term for g in seed if g.source_term not in got]
        empty = [g.source_term for g in payload.glossary if not g.target_term.strip()]
        if missing or empty:
            raise Quarantine(f"glossary incomplete: missing={missing}, untranslated={empty}")
        # Keep source order and the seed's kind unless the model explicitly
        # classified the term; do not let the model add unrelated entities.
        out = []
        for original in seed:
            item = got[original.source_term]
            out.append(GlossaryEntry(source_term=original.source_term, target_term=item.target_term.strip(), kind=item.kind, note=item.note))
        return out

    def _claims(self, family: Family, cards: list[ClaimSemanticCard], glossary: list[GlossaryEntry]) -> list[TargetClaim]:
        source_claims = [c.model_dump(mode="json") for c in family.claim_set]
        feedback = ""
        last_error = ""
        for attempt in range(2):
            payload: ClaimTranslationPayload = self._call(
                "multilingual_claim_translation",
                {
                    "profile_json": _json(self.profile.model_dump(mode="json")),
                    "claim_cards_json": _json([c.model_dump(mode="json") for c in cards]),
                    "glossary_json": _json([g.model_dump(mode="json") for g in glossary]),
                    "feedback_block": _feedback_block(feedback),
                },
                ClaimTranslationPayload,
                stage="translate_claims",
                family_id=family.family_id,
            )
            got = [c.claim_id for c in payload.claims]
            if sorted(got) != sorted(c.claim_id for c in family.claim_set):
                last_error = f"claim translation id mismatch: {got}"
                feedback = last_error
                continue
            target = [
                TargetClaim(
                    claim_id=c.claim_id,
                    source_text=next(x.claim_text for x in family.claim_set if x.claim_id == c.claim_id),
                    target_text=normalize_ws(c.target_text),
                    relation_obligation="SUPPORTED",
                    preserved_terms=c.preserved_terms,
                    repair_attempts=attempt,
                )
                for c in payload.claims
            ]
            empty = [t.claim_id for t in target if not t.target_text]
            number_gaps = [
                f"{t.claim_id}: missing {sorted(number_tokens(t.source_text) - number_tokens(t.target_text))}"
                for t in target
                if number_tokens(t.source_text) - number_tokens(t.target_text)
            ]
            if empty or number_gaps:
                last_error = f"claim translation incomplete: empty={empty}, numbers={number_gaps}"
                feedback = last_error
                continue
            review: ClaimReviewPayload = self._call(
                "multilingual_claim_review",
                {
                    "profile_json": _json(self.profile.model_dump(mode="json")),
                    "source_claims_json": _json(source_claims),
                    "target_claims_json": _json([t.model_dump(mode="json") for t in target]),
                },
                ClaimReviewPayload,
                stage="review_claims",
                family_id=family.family_id,
                review=True,
            )
            verdicts = {r.claim_id: r for r in review.claims}
            failed = [r for r in review.claims if r.status == "FAIL"]
            if not failed and set(verdicts) == {t.claim_id for t in target}:
                for t in target:
                    t.review_status = "PASS"
                return target
            last_error = "; ".join(f"{r.claim_id}: {r.note}" for r in failed) or "claim review did not cover every claim"
            feedback = last_error
        raise Quarantine(f"claim translation failed review: {last_error}")

    def _review_window(
        self,
        family: Family,
        variant_label: str,
        window: Window,
        target: dict[str, str],
        cards: list[ClaimSemanticCard],
        target_claims: list[TargetClaim],
    ) -> WindowReview:
        source_by_id = {r.sentence_id: r.text for r in sentence_index(self._source_text(family, variant_label))}
        return self._call(
            "multilingual_window_review",
            {
                "profile_json": _json(self.profile.model_dump(mode="json")),
                "source_sentences_json": _json(
                    [{"sentence_id": sid, "text": source_by_id[sid]} for sid in window.sentence_ids]
                ),
                "target_sentences_json": _json(
                    [{"sentence_id": sid, "text": target[sid]} for sid in window.sentence_ids]
                ),
                "claim_cards_json": _json([c.model_dump(mode="json") for c in cards]),
                "target_claims_json": _json([t.model_dump(mode="json") for t in target_claims]),
            },
            WindowReview,
            stage=f"review_{window.window_id}",
            family_id=family.family_id,
            review=True,
        )

    def _translate_window(
        self,
        family: Family,
        variant_label: str,
        window: Window,
        target_claims: list[TargetClaim],
        cards: list[ClaimSemanticCard],
        glossary: list[GlossaryEntry],
    ) -> list[SentenceTranslation]:
        source_by_id = {r.sentence_id: r.text for r in sentence_index(self._source_text(family, variant_label))}
        feedback = ""
        previous: dict[str, str] = {}
        repair_ids: list[str] = []
        for _attempt in range(self.ml.window.max_repairs + 1):
            # A repair is a surgical update: send only the sentence ids named by
            # the reviewer, then merge them into the prior full-window target.
            if repair_ids:
                ids = [sid for sid in window.sentence_ids if sid in set(repair_ids)]
                if not ids:
                    ids = list(window.sentence_ids)
                attempt_window = Window(
                    window_id=window.window_id,
                    sentence_ids=ids,
                    paragraph_by_sentence={sid: window.paragraph_by_sentence[sid] for sid in ids},
                    source_text=" ".join(source_by_id[sid] for sid in ids),
                    prev_context=window.prev_context,
                    next_context=window.next_context,
                )
            else:
                attempt_window = window
            payload: WindowTranslationPayload = self._call(
                "multilingual_window_translation",
                {
                    "profile_json": _json(self.profile.model_dump(mode="json")),
                    "label": variant_label,
                    "expected_relation": _relation_map(variant_label),
                    "global_synopsis": family.semantic_representation.summary if family.semantic_representation else "",
                    "claim_cards_json": _json([c.model_dump(mode="json") for c in cards]),
                    "target_claims_json": _json([t.model_dump(mode="json") for t in target_claims]),
                    "glossary_json": _json([g.model_dump(mode="json") for g in glossary]),
                    "prev_context": window.prev_context,
                    "previous_target_json": _json(
                        [{"sentence_id": sid, "target_text": previous[sid]} for sid in attempt_window.sentence_ids if sid in previous]
                    ),
                    "source_text": attempt_window.source_text,
                    "sentence_ids_json": _json(attempt_window.sentence_ids),
                    "next_context": window.next_context,
                    "feedback_block": _feedback_block(feedback),
                },
                WindowTranslationPayload,
                stage=f"translate_{window.window_id}",
                family_id=family.family_id,
            )
            got = [s.sentence_id for s in payload.sentences]
            if sorted(got) != sorted(attempt_window.sentence_ids):
                feedback = f"your output ids were {got}; required exactly {attempt_window.sentence_ids}"
                continue
            current = {s.sentence_id: normalize_ws(s.target_text) for s in payload.sentences}
            if not previous:
                previous = current
            else:
                previous.update(current)
            missing_ids = [sid for sid in window.sentence_ids if sid not in previous]
            if missing_ids:
                feedback = f"missing target sentence ids after repair merge: {missing_ids}"
                repair_ids = missing_ids
                continue
            full_target = {sid: previous[sid] for sid in window.sentence_ids}
            source_numbers = critical_numbers(window.source_text)
            target_numbers = critical_numbers(" ".join(full_target.values()))
            missing_numbers = sorted(source_numbers - target_numbers)
            if missing_numbers:
                feedback = f"missing numbers/dates: {missing_numbers}; preserve every numeric value exactly"
                repair_ids = []
                continue
            review: WindowReview = self._review_window(
                family, variant_label, window, full_target, cards, target_claims
            )
            if review.verdict == "PASS":
                return [
                    SentenceTranslation(
                        sentence_id=sid,
                        paragraph_id=window.paragraph_by_sentence[sid],
                        source_text=source_by_id.get(sid, ""),
                        target_text=full_target[sid],
                    )
                    for sid in window.sentence_ids
                ]
            if review.verdict == "QUARANTINE":
                raise Quarantine(f"{variant_label} {window.window_id}: {review.feedback or 'review quarantined'}")
            if self.ml.fixer.enabled:
                result = QualityFixer(
                    self.client,
                    profile=self.profile,
                    source_by_id=source_by_id,
                    target=full_target,
                    review=review,
                    review_fn=lambda current: self._review_window(
                        family, variant_label, window, current, cards, target_claims
                    ),
                    target_claims=target_claims,
                    cards=cards,
                    glossary=glossary,
                    prev_context=window.prev_context,
                    next_context=window.next_context,
                    max_steps=self.ml.fixer.max_steps,
                    max_edits_per_step=self.ml.fixer.max_edits_per_step,
                    max_total_edits=self.ml.fixer.max_total_edits,
                    stage=f"fix_{window.window_id}",
                    family_id=family.family_id,
                ).run()
                if result.accepted:
                    return [
                        SentenceTranslation(
                            sentence_id=sid,
                            paragraph_id=window.paragraph_by_sentence[sid],
                            source_text=source_by_id.get(sid, ""),
                            target_text=result.target[sid],
                        )
                        for sid in window.sentence_ids
                    ]
                raise Quarantine(
                    f"{variant_label} {window.window_id}: fixer failed: {result.error or 'no accepted repair'}"
                )
            affected = [sid for sid in review.affected_sentence_ids if sid in window.sentence_ids]
            if not affected:
                # Older/looser reviewer output may name ids only in free text.
                blob = " ".join(
                    [review.feedback]
                    + [str(x) for x in review.meaning_errors + review.style_errors + review.missing_sentence_ids]
                )
                affected = [sid for sid in window.sentence_ids if re.search(rf"{re.escape(sid)}", blob)]
            repair_ids = affected or list(window.sentence_ids)
            feedback = review.feedback or "; ".join(
                str(x) for x in review.meaning_errors + review.style_errors + review.missing_sentence_ids
            )
        raise Quarantine(f"{variant_label} {window.window_id}: repair budget exhausted: {feedback}")

    def _assemble(self, sentences: list[SentenceTranslation]) -> str:
        """Join translated sentences, restoring source paragraph boundaries."""

        paragraphs: dict[int, list[str]] = {}
        for sentence in sentences:
            paragraphs.setdefault(sentence.paragraph_id, []).append(sentence.target_text.strip())
        return "\n\n".join(
            " ".join(parts).strip()
            for _, parts in sorted(paragraphs.items())
            if " ".join(parts).strip()
        ).strip()

    def _source_text(self, family: Family, label: str) -> str:
        return family.variants[label].text

    def _review_variant(
        self,
        family: Family,
        label: str,
        source: str,
        target: str,
        sentences: list[SentenceTranslation],
        cards: list[ClaimSemanticCard],
        target_claims: list[TargetClaim],
        expected: dict[str, str],
    ) -> VariantReview:
        payload: FamilyReviewPayload = self._call(
            "multilingual_family_review",
            {
                "profile_json": _json(self.profile.model_dump(mode="json")),
                "label": label,
                "expected_relations_json": _json(expected),
                "claim_cards_json": _json([c.model_dump(mode="json") for c in cards]),
                "target_claims_json": _json([t.model_dump(mode="json") for t in target_claims]),
                "source_variant": source,
                "target_variant": target,
                "target_sentences_json": _json([s.model_dump(mode="json") for s in sentences]),
            },
            FamilyReviewPayload,
            stage=f"review_variant_{label}",
            family_id=family.family_id,
            review=True,
        )
        return VariantReview(
            variant_label=label,  # type: ignore[arg-type]
            verdict=payload.verdict,
            findings=payload.findings,
            faithfulness_notes=payload.faithfulness_notes,
            feedback=payload.feedback,
        )

    def _one_variant(
        self,
        family: Family,
        label: str,
        cards: list[ClaimSemanticCard],
        target_claims: list[TargetClaim],
        glossary: list[GlossaryEntry],
        expected: dict[str, str],
    ) -> TranslatedVariant:
        source = self._source_text(family, label)
        windows = build_windows(source, self.ml.window)
        sentences: list[SentenceTranslation] = []
        if self.ml.window.concurrency <= 1:
            for window in windows:
                sentences.extend(self._translate_window(family, label, window, target_claims, cards, glossary))
        else:
            # Windows are independent (context is source-side only), so this
            # is a safe second level of concurrency inside one family.  Submit
            # in source order and assemble in that same order.
            with ThreadPoolExecutor(max_workers=max(1, self.ml.window.concurrency)) as pool:
                futures = [
                    pool.submit(self._translate_window, family, label, window, target_claims, cards, glossary)
                    for window in windows
                ]
                for future in futures:
                    sentences.extend(future.result())
        all_ids = [s.sentence_id for s in sentences]
        if len(all_ids) != len(set(all_ids)):
            raise Quarantine(f"{label}: duplicate target sentence ids")
        target = self._assemble(sentences)
        if not target:
            raise Quarantine(f"{label}: empty target")
        if not script_ok(target, self.profile.script_policy):
            raise Quarantine(f"{label}: target violates script policy {self.profile.script_policy}")
        review = self._review_variant(family, label, source, target, sentences, cards, target_claims, expected)
        if review.verdict == "QUARANTINE":
            raise Quarantine(f"{label}: family review quarantined: {review.feedback}")
        if review.verdict == "REPAIR":
            raise Quarantine(f"{label}: family review requested repair: {review.feedback}")
        by_claim = {f.claim_id: f for f in review.findings}
        if set(by_claim) != set(expected):
            raise Quarantine(f"{label}: family review missing claim findings")
        mismatches = [
            cid
            for cid, exp in expected.items()
            if _as_label(by_claim[cid].observed_relation) != exp
        ]
        if mismatches:
            shapes = ", ".join(f"{cid}: expected {expected[cid]}, got {by_claim[cid].observed_relation}" for cid in mismatches)
            raise Quarantine(f"{label}: relation drift after translation: {shapes}")
        return TranslatedVariant(
            variant_id=family.variants[label].variant_id,
            label=label,  # type: ignore[arg-type]
            source_checksum=family.variants[label].checksum,
            source_text=source,
            target_text=target,
            sentences=sentences,
            token_count=approx_tokens(target),
            checksum=sha256_text(target),
            review=review,
        )

    def translate_family(self, family: Family) -> FamilyTranslation:
        try:
            preflight(family)
        except SourceError as exc:
            return self._quarantine(family, str(exc))
        cards = claim_cards(family)
        expected_all = expected_relations(family)
        seed = seed_glossary(family)
        result = FamilyTranslation(
            family_id=family.family_id,
            split_group_id=family.split_group_id,
            split=family.split,  # type: ignore[arg-type]
            source_checksum=source_checksum(family),
            profile_id=self.profile.profile_id,
            profile_version=self.profile.version,
            target_language=self.profile.base_language,
            target_script=self.profile.primary_script,
            claim_cards=cards,
            glossary=[],
            created_at=now(),
            updated_at=now(),
            stage="started",
        )
        try:
            glossary = self._glossary(family, cards, seed)
            result.glossary = glossary
            result.target_claims = self._claims(family, cards, glossary)
            result.stage = "claims_accepted"
            variants: list[TranslatedVariant] = []
            for label in LABELS:
                variants.append(
                    self._one_variant(family, label, cards, result.target_claims, glossary, expected_all[label])
                )
                result.stage = f"variant_{label}"
            result.variants = variants
            target_texts = [v.target_text for v in variants]
            if len(set(target_texts)) != 3:
                raise Quarantine("translated variants are not distinct")
            if len({v.checksum for v in variants}) != 3:
                raise Quarantine("translated variant checksums collide")
            result.status = "ACCEPTED"
            result.stage = "accepted"
            result.audit_flags.append("source_immutable_checksum_verified")
            result.audit_flags.append("three_labels_share_target_claims")
        except Quarantine as exc:
            result.status = "QUARANTINED"
            result.rejection_reasons.append(str(exc))
            result.stage = "quarantined"
        except (LlmError, PermanentLlmError) as exc:
            result.status = "QUARANTINED"
            result.rejection_reasons.append(f"llm_error: {exc}")
            result.stage = "quarantined"
        result.updated_at = now()
        stats = self.client.stats()
        result.calls = int(stats.get("calls", 0))
        result.cost_usd = float(stats.get("cost_usd", 0.0))
        self._write(result)
        return result

    def _quarantine(self, family: Family, reason: str) -> FamilyTranslation:
        rec = FamilyTranslation(
            family_id=family.family_id,
            split_group_id=family.split_group_id,
            split=family.split,  # type: ignore[arg-type]
            source_checksum=source_checksum(family),
            profile_id=self.profile.profile_id,
            profile_version=self.profile.version,
            target_language=self.profile.base_language,
            target_script=self.profile.primary_script,
            status="QUARANTINED",
            rejection_reasons=[reason],
            stage="quarantined",
            created_at=now(),
            updated_at=now(),
        )
        self._write(rec)
        return rec

    def _write(self, rec: FamilyTranslation) -> None:
        with self.lock:
            target = self.families_dir / f"{rec.family_id}.json" if rec.status == "ACCEPTED" else self.quarantine_dir / f"{rec.family_id}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text(rec.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(target)
            self._write_manifest()

    def _write_manifest(self, status: str = "running") -> None:
        accepted = len(list(self.families_dir.glob("*.json")))
        quarantined = len(list(self.quarantine_dir.glob("*.json")))
        stats = self.client.stats()
        manifest = TranslationManifest(
            profile_id=self.profile.profile_id,
            profile_version=self.profile.version,
            source_dir=str(self.ml.source_path),
            output_dir=str(self.out),
            source_families=len(list((self.ml.source_path / "families").glob("FAM_*.json"))),
            accepted=accepted,
            quarantined=quarantined,
            pending=max(0, len(list((self.ml.source_path / "families").glob("FAM_*.json"))) - accepted - quarantined),
            calls=int(stats.get("calls", 0)),
            cost_usd=float(stats.get("cost_usd", 0.0)),
            status=status,  # type: ignore[arg-type]
            updated_at=now(),
        )
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(self.manifest_path)

    def existing(self, family_id: str) -> str | None:
        """Return ACCEPTED/QUARANTINED without parsing a quarantine stub as a record.

        Quarantine files intentionally contain only the failure envelope, not the
        full FamilyTranslation.  Treating them as accepted records makes
        ``--retry-quarantined`` crash before the retry starts.
        """
        for path in (self.families_dir / f"{family_id}.json", self.quarantine_dir / f"{family_id}.json"):
            if not path.exists():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            status = raw.get("status")
            if status in ("ACCEPTED", "QUARANTINED"):
                return status
            return None
        return None


def source_families(ml: MultilingualCfg) -> list[Family]:
    out: list[Family] = []
    for path in sorted((ml.source_path / "families").glob("FAM_*.json")):
        family = Family.model_validate_json(path.read_text(encoding="utf-8"))
        if family.quality.status == "ACCEPTED":
            out.append(family)
    return out


def run_profile(
    ml: MultilingualCfg,
    base_cfg: Config,
    profile_id: str,
    client: LlmClient,
    *,
    limit: int | None = None,
    concurrency: int = 4,
    retry_quarantined: bool = False,
    run_id: str = "translate",
    family_id: str | None = None,
) -> TranslationManifest:
    pipe = TranslationPipeline(ml, base_cfg, profile_id, client, run_id=run_id)
    families = source_families(ml)
    if family_id:
        families = [f for f in families if f.family_id == family_id]
    if limit:
        families = families[:limit]
    todo = []
    for family in families:
        prior = pipe.existing(family.family_id)
        if prior == "ACCEPTED":
            continue
        if prior == "QUARANTINED" and not retry_quarantined:
            continue
        todo.append(family)
    if not todo:
        if not pipe.manifest_path.exists():
            pipe._write_manifest(status="complete")  # noqa: SLF001 - same module owns the manifest
        return TranslationManifest.model_validate_json(pipe.manifest_path.read_text(encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(pipe.translate_family, f): f.family_id for f in todo}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001 - one family must not sink the batch
                fid = futures[fut]
                (pipe.quarantine_dir / f"{fid}.json").write_text(
                    json.dumps({"family_id": fid, "status": "QUARANTINED", "rejection_reasons": [f"worker error: {exc}"]}, indent=2),
                    encoding="utf-8",
                )
    pipe._write_manifest(status="complete")  # noqa: SLF001 - same module owns the manifest
    return TranslationManifest.model_validate_json(pipe.manifest_path.read_text(encoding="utf-8"))
