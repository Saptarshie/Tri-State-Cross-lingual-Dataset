"""End-to-end orchestration: candidate -> family, resumable at every stage.

Each stage is a durable job that writes one atomic JSON artifact. A rerun skips stages
whose artifact exists *and whose prompt/model version still matches*, which makes the
pipeline safe to interrupt, rerun and parallelise without duplicating accepted families.
"""

from __future__ import annotations

import json
import math
import threading
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .blueprint import plan_blueprint
from .claims import claim_types, claim_word_overlap, select_claims
from .config import Config
from .editor import create_variant
from .errors import StageError
from .extract import extract_semantics
from .graphdiff import diff_graph
from .ids import (
    family_id_from_seq,
    passage_id_from_seq,
    variant_id,
)
from .llm import BudgetExceeded, LlmClient, PermanentLlmError, TransientLlmError
from .longform import generate_document, plan_document
from .mock import MockClient
from .novelty import NoveltyService
from .passage import generate_passage
from .prompts import PromptLibrary
from .schema import (
    LABELS,
    Blueprint,
    BlueprintCandidate,
    Claim,
    DocumentPlan,
    EditLog,
    Family,
    GenerationMeta,
    PassageRecord,
    PassageSection,
    Quality,
    SemanticRepresentation,
    SourceRef,
    TopicRef,
    ValidationResult,
    Variant,
)
from .splits import SplitManager
from .store import Store
from .topics import (
    expand_to_target,
    expand_topic,
    load_graph,
    record_candidate,
    record_outcome,
    save_graph,
    seed_graph,
    select_topics,
)
from .util import (
    approx_tokens,
    atomic_write_json,
    read_json,
    sha256_json,
    sha256_text,
    stable_seed,
    utcnow,
)
from .validate import (
    evidence_spans_from_relations,
    family_hard_checks,
    summarise_family_validation,
    validate_passage,
    verify_base_claims,
)

SEED_INTENTS = [
    "explain the practical mechanism and how it is used",
    "trace the origin and early development",
    "compare it with a plausible alternative",
    "describe a measurable outcome and the numbers involved",
    "focus on constraints, failure modes and maintenance",
    "explain who operates it and under what rules",
]

STAGE_ORDER_RUN = ["blueprint", "passage", "extract", "claims", "base_check", "variants", "validate", "accept"]


@dataclass
class CandidateResult:
    candidate_id: str
    status: str
    family_id: str | None = None
    reasons: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    stages: list[str] = field(default_factory=list)


@dataclass
class RunSummary:
    run_id: str
    requested: int
    accepted: int
    quarantined: int
    failed: int
    skipped: int
    processed: int
    elapsed_s: float
    llm: dict[str, Any]
    accepted_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "requested": self.requested,
            "accepted": self.accepted,
            "quarantined": self.quarantined,
            "failed": self.failed,
            "skipped": self.skipped,
            "processed": self.processed,
            "elapsed_s": round(self.elapsed_s, 2),
            "llm": self.llm,
            "accepted_ids": self.accepted_ids,
            "notes": self.notes,
        }


class Pipeline:
    def __init__(
        self,
        cfg: Config,
        store: Store | None = None,
        client: Any | None = None,
        novelty: NoveltyService | None = None,
        run_id: str | None = None,
        mock: bool = False,
        log: Callable[[str], None] | None = None,
    ):
        self.cfg = cfg
        self.store = store or Store(cfg.data_dir)
        self.run_id = run_id or f"RUN_{utcnow().replace(':', '').replace('-', '')}"
        self.prompts = PromptLibrary(cfg.prompts_dir)
        self.mock = mock
        self.client = client or (
            MockClient(cfg) if mock else LlmClient(cfg, self.run_id, prompts=self.prompts, recorder=self.store.record_call)
        )
        if not mock and isinstance(self.client, LlmClient):
            self.client.recorder = self.store.record_call
        self.novelty = novelty or NoveltyService(self.store, cfg)
        self.splits = SplitManager(cfg.data_dir, cfg)
        self._log_fn = log or (lambda msg: print(msg, flush=True))
        self._lock = threading.RLock()
        self._touched_index = False

    # ------------------------------------------------------------------ #
    def log(self, msg: str) -> None:
        self._log_fn(f"[{utcnow()[11:19]}] {msg}")

    # ------------------------------------------------------------------ #
    # Candidate planning
    # ------------------------------------------------------------------ #
    def ensure_candidates(
        self,
        limit: int,
        seed_topic: str | None = None,
        topic_ids: list[str] | None = None,
        expand: bool = False,
    ) -> list[dict[str, Any]]:
        graph = seed_graph(self.cfg.data_dir)
        if not graph.nodes:
            raise StageError("no_topics", "topic graph is empty")

        per_topic = max(1, self.cfg.blueprint.candidates_per_topic)
        expanded_for_selection = False
        if expand and not seed_topic and not topic_ids:
            target_leaves = max(8, math.ceil(limit / per_topic) + 8)
            calls = expand_to_target(
                graph, self.cfg, self.client, target_leaves, log=self.log
            )
            graph = load_graph(self.cfg.data_dir)
            self.log(f"topic graph expansion: {calls} calls, {len(graph.leaves())} leaves")
            expanded_for_selection = True

        if seed_topic:
            matches = [
                n for n in graph.nodes.values()
                if n.name.lower() == seed_topic.lower()
            ] or [n for n in graph.nodes.values() if seed_topic.lower() in n.name.lower()]
            if not matches:
                from .topics import TopicNode, topic_id_for

                tid = topic_id_for(seed_topic, [])
                node = TopicNode(
                    topic_id=tid, name=seed_topic, description=f"ad-hoc seed topic: {seed_topic}",
                    depth=0, importance=1.0, target_coverage=limit,
                )
                graph.add(node)
                save_graph(graph, self.cfg.data_dir)
                matches = [node]
            selected = [
                type("S", (), {"topic_id": n.topic_id, "name": n.name, "topic_path": graph.path_of(n.topic_id),
                               "score": 1.0, "components": {}})()
                for n in matches[:2]
            ]  # type: ignore[list-item]
            nodes = matches[:2]
        elif topic_ids:
            nodes = [graph.nodes[t] for t in topic_ids if t in graph.nodes]
            selected = [
                type("S", (), {"topic_id": n.topic_id, "name": n.name, "topic_path": graph.path_of(n.topic_id),
                               "score": 1.0, "components": {}})()
                for n in nodes
            ]  # type: ignore[list-item]
        else:
            per_topic = max(1, self.cfg.blueprint.candidates_per_topic)
            n_topics = max(1, math.ceil(limit / per_topic) + 1)
            selected = select_topics(graph, n_topics, self.cfg.project.seed)
            nodes = [graph.nodes[s.topic_id] for s in selected]

        if expand and not expanded_for_selection:
            for node in list(nodes):
                if node.depth < self.cfg.corpus.topic_max_depth and not node.child_topic_ids:
                    try:
                        children = expand_topic(graph, self.cfg, self.client, node.topic_id)
                        self.log(f"expanded topic {node.name} -> {[c.name for c in children]}")
                    except Exception as exc:  # noqa: BLE001 - expansion is best-effort
                        self.log(f"topic expansion failed for {node.name}: {exc}")

        per_topic = max(1, self.cfg.blueprint.candidates_per_topic)
        rows: list[dict[str, Any]] = []
        for sel in selected:
            node = graph.nodes.get(sel.topic_id)
            if node is None:
                continue
            for k in range(per_topic):
                intent = SEED_INTENTS[(k + stable_seed(node.topic_id) % len(SEED_INTENTS)) % len(SEED_INTENTS)]
                key = sha256_json(
                    {
                        "config": self.cfg.config_hash(),
                        "topic": node.topic_id,
                        "ordinal": k,
                        "intent": intent,
                        "seed": self.cfg.project.seed,
                    }
                )
                from .ids import candidate_id as make_candidate_id

                cid = make_candidate_id(key)
                existing, created = self.store.upsert_candidate(
                    key, cid, [node.topic_id], graph.path_of(node.topic_id),
                )
                if created:
                    meta = BlueprintCandidate(
                        candidate_id=cid,
                        idempotency_key=key,
                        topic_ids=[node.topic_id],
                        topic_path=graph.path_of(node.topic_id),
                        parent_topic_ids=list(node.parent_topic_ids),
                        seed_intent=intent,
                    )
                    atomic_write_json(self.store.workdir(cid) / "candidate.json", meta.model_dump(mode="json"))
                    record_candidate(graph, node.topic_id)
                    self.log(f"queued candidate {cid} for {node.name} ({intent})")
                row = self.store.get_candidate(existing)
                if row:
                    rows.append(row)
        save_graph(graph, self.cfg.data_dir)
        return rows

    # ------------------------------------------------------------------ #
    # Stage machinery
    # ------------------------------------------------------------------ #
    def _stage(
        self,
        candidate_id: str,
        name: str,
        prompt_name: str,
        model_name: str,
        fn: Callable[[], Any],
    ) -> Any:
        prompt_version = self.prompts.get(prompt_name).full_version
        job = self.store.job(candidate_id, name)
        if job and job["status"] == "SUCCEEDED" and job.get("artifact_ref"):
            same_prompt = (job.get("prompt_version") or "") == prompt_version
            same_model = (job.get("model") or "") == model_name
            if same_prompt and same_model and Path(job["artifact_ref"]).exists():
                return read_json(job["artifact_ref"])

        self.store.start_job(candidate_id, name, model_name, prompt_version)
        try:
            out = fn()
            payload = out.model_dump(mode="json") if hasattr(out, "model_dump") else out
            path = self.store.save_artifact(candidate_id, name, payload)
            self.store.finish_job(candidate_id, name, "SUCCEEDED", str(path))
            self.log(f"{candidate_id} {name}: ok")
            return payload
        except StageError as exc:
            self.store.finish_job(candidate_id, name, "FAILED", error=json.dumps(exc.as_dict())[:3500])
            raise
        except Exception as exc:
            self.store.finish_job(
                candidate_id, name, "FAILED",
                error=f"{type(exc).__name__}: {exc}"[:3500],
            )
            raise

    def _call_budget_ok(self, candidate_id: str) -> bool:
        used = self.store.calls_for_candidate(candidate_id)
        return used < self.cfg.execution.max_calls_per_family

    def _partial(self, cid: str, started: float, stages: list[str]) -> CandidateResult:
        self.store.set_candidate_status(cid, "PENDING", {"note": "partial", "stages": stages})
        return CandidateResult(cid, "PARTIAL", None, [], time.perf_counter() - started, stages)

    # ------------------------------------------------------------------ #
    # One candidate
    # ------------------------------------------------------------------ #
    def process_candidate(self, row: dict[str, Any], stop_after: str | None = None) -> CandidateResult:
        started = time.perf_counter()
        cid = row["candidate_id"]
        stages: list[str] = []
        family: Family | None = None
        stats_before = self._client_stats()
        try:
            meta_raw = read_json(self.store.workdir(cid) / "candidate.json")
            if not meta_raw:
                raise StageError("missing_candidate_meta", "candidate.json not found")
            cand = BlueprintCandidate.model_validate(meta_raw)

            if self.store.family_by_key(cand.idempotency_key):
                self.store.set_candidate_status(cid, "ACCEPTED", {"note": "family already exists"})
                fam = self.store.family_by_key(cand.idempotency_key)
                return CandidateResult(cid, "SKIPPED", fam["family_id"] if fam else None,
                                       ["family already exists"], time.perf_counter() - started, [])

            self.store.set_candidate_status(cid, "RUNNING")

            # ---------------- blueprint ----------------
            pre_report = self.novelty.pre_generation_report(
                " | ".join(cand.topic_path + [cand.seed_intent]),
                cand.topic_path,
            )

            def do_blueprint() -> Blueprint:
                bp = plan_blueprint(self.client, self.cfg, cand, pre_report)
                bp.novelty_report = self.novelty.pre_generation_report(bp.semantic_text, bp.topic_path)
                return bp

            bp_raw = self._stage(cid, "blueprint", "blueprint", self.cfg.llm.generator.name, do_blueprint)
            blueprint = Blueprint.model_validate(bp_raw)
            stages.append("blueprint")
            if stop_after == "blueprint":
                return self._partial(cid, started, stages)

            # ---------------- base artifact (short single call or long-form sections) ----------
            short_mode = self.cfg.passage.target_tokens_max <= self.cfg.passage.single_call_below_tokens
            document_plan: DocumentPlan | None = None
            sections: list[PassageSection] = []

            if short_mode:
                text = self._stage(
                    cid, "passage", "passage", self.cfg.llm.generator.name,
                    lambda: {"text": generate_passage(self.client, self.cfg, blueprint, candidate_id=cid)},
                )["text"]
            else:
                plan_doc = self._stage(
                    cid, "document_plan", "document_plan", self.cfg.llm.generator.name,
                    lambda: plan_document(self.client, self.cfg, blueprint, candidate_id=cid)
                    .model_dump(mode="json"),
                )
                document_plan = DocumentPlan.model_validate(plan_doc)
                if stop_after == "document_plan":
                    stages.append("document_plan")
                    return self._partial(cid, started, stages)

                section_prompt_version = self.prompts.get("section").full_version

                def load_section(key: str) -> dict[str, Any] | None:
                    return self.store.load_artifact(cid, f"section_{key}")

                def save_section(key: str, payload: dict[str, Any]) -> None:
                    self.store.save_artifact(cid, f"section_{key}", payload)

                def do_document() -> dict[str, Any]:
                    doc_text, doc_sections, doc_meta = generate_document(
                        self.client,
                        self.cfg,
                        blueprint,
                        document_plan,
                        candidate_id=cid,
                        prompt_version=section_prompt_version,
                        load_section=load_section,
                        save_section=save_section,
                        log=self.log,
                    )
                    return {
                        "text": doc_text,
                        "sections": [s.model_dump(mode="json") for s in doc_sections],
                        "meta": doc_meta,
                        "document_plan_id": document_plan.plan_id,
                    }

                doc = self._stage(
                    cid, "passage", "section", self.cfg.llm.generator.name, do_document
                )
                text = doc["text"]
                sections = [PassageSection.model_validate(s) for s in doc.get("sections", [])]
                if document_plan:
                    stages.append("document_plan")
            stages.append("passage")
            if stop_after == "passage":
                return self._partial(cid, started, stages)

            # ---------------- semantic extraction (windowed for long documents) -------------
            def do_extract() -> SemanticRepresentation:
                kwargs = {
                    "candidate_id": cid,
                    "window_tokens": self.cfg.extraction.window_tokens,
                    "max_windows": self.cfg.extraction.max_windows,
                    "sections": sections or None,
                }
                try:
                    return extract_semantics(self.client, self.cfg, text, **kwargs)
                except StageError as exc:
                    if exc.code != "extraction_insufficient":
                        raise
                    self.log(f"{cid} extract retry with feedback: {exc}")
                    return extract_semantics(
                        self.client, self.cfg, text,
                        feedback=f"Previous extraction was rejected: {exc}. Quote exact substrings from the listed sentences.",
                        **kwargs,
                    )

            semantic = SemanticRepresentation.model_validate(
                self._stage(cid, "extract", "extract", self.cfg.llm.extractor.name, do_extract)
            )
            stages.append("extract")
            if stop_after == "extract":
                return self._partial(cid, started, stages)

            # ---------------- claims ----------------
            claims_raw = self._stage(
                cid, "claims", "claims", self.cfg.llm.claims.name,
                lambda: [
                    c.model_dump(mode="json")
                    for c in select_claims(self.client, self.cfg, text, semantic, cid, sections=sections or None)
                ],
            )
            claims = [Claim.model_validate(c) for c in claims_raw]
            stages.append("claims")
            if stop_after == "claims":
                return self._partial(cid, started, stages)
            if not self._call_budget_ok(cid):
                raise StageError("call_budget", "per-family call budget exhausted")

            # ---------------- base support check ----------------
            def do_base_check() -> dict[str, Any]:
                kept, dropped, result = verify_base_claims(self.client, self.cfg, claims, text, cid)
                return {
                    "claims": [c.model_dump(mode="json") for c in kept],
                    "dropped": dropped,
                    "validation": result.model_dump(mode="json"),
                }

            base_check = self._stage(cid, "base_check", "validate", self.cfg.llm.validator.name, do_base_check)
            claims = [Claim.model_validate(c) for c in base_check["claims"]]
            stages.append("base_check")
            if stop_after == "base_check":
                return self._partial(cid, started, stages)

            # ---------------- variants ----------------
            variant_state: dict[str, dict[str, Any]] = {}
            for label in LABELS:
                if not self._call_budget_ok(cid):
                    raise StageError("call_budget", "per-family call budget exhausted before variants")
                outcome = self._make_variant(cid, label, text, claims, semantic)
                variant_state[label] = outcome
            stages.append("variants")
            if stop_after == "variants":
                return self._partial(cid, started, stages)

            # ---------------- validation + bounded repair ----------------
            validations: dict[str, ValidationResult] = {}
            for label in LABELS:
                validations[label] = self._validate_variant(cid, label, claims, variant_state[label]["text"])

            repair_rounds = 0
            while any(v.status != "PASS" for v in validations.values()) and repair_rounds < self.cfg.variants.max_edit_repair_attempts:
                repair_rounds += 1
                for label in LABELS:
                    if validations[label].status == "PASS":
                        continue
                    if not self._call_budget_ok(cid):
                        raise StageError("call_budget", "per-family call budget exhausted during repair")
                    feedback = (
                        f"The previous {label} variant failed independent validation: "
                        + "; ".join(validations[label].failures or ["unknown failure"])
                        + ". Re-plan patches for the full claim set; every claim must reach the target relation. "
                        "Do not repeat the same edit."
                    )
                    self.log(f"{cid} repairing {label} (round {repair_rounds}): {validations[label].failures[:2]}")
                    outcome = self._make_variant(cid, label, text, claims, semantic,
                                                 prior_feedback=feedback, force=True)
                    variant_state[label] = outcome
                    validations[label] = self._validate_variant(cid, label, claims, outcome["text"], force=True)

            stages.append("validate")

            # ---------------- graph diff + novelty + hard checks ----------------
            graph_diffs: dict[str, dict] = {}
            for label in LABELS:
                variant_sem_raw = self.store.load_artifact(cid, f"semantic_{label}")
                if not variant_sem_raw or "error" in variant_sem_raw:
                    # graph diff is advisory: a failed re-extraction must not reject a family
                    # that already passed independent validation
                    graph_diffs[label] = {
                        "label": label,
                        "status": "unavailable",
                        "ok": None,
                        "misses": [],
                        "reason": (variant_sem_raw or {}).get("error", "missing variant semantics"),
                    }
                    continue
                try:
                    variant_sem = SemanticRepresentation.model_validate(variant_sem_raw)
                    graph_diffs[label] = diff_graph(semantic, variant_sem, claims, label)
                except Exception as exc:  # malformed artefact, never a quality verdict
                    graph_diffs[label] = {
                        "label": label,
                        "status": "unavailable",
                        "ok": None,
                        "misses": [],
                        "reason": str(exc)[:200],
                    }
            if graph_diffs:
                self.store.save_artifact(cid, "graphdiff", graph_diffs)

            novelty_rows = {}
            for label in LABELS:
                novelty_rows[label] = self.novelty.post_generation_check(variant_state[label]["text"])
            self.store.save_artifact(cid, "novelty", novelty_rows)

            variant_texts = {label: variant_state[label]["text"] for label in LABELS}
            hard = family_hard_checks(self.cfg, claims, text, variant_texts, cand.source_type, semantic)
            self.store.save_artifact(cid, "hard_checks", hard)

            ok, reasons = summarise_family_validation(validations, hard)
            if self.cfg.validation.require_graph_diff:
                misses = [
                    f"{label}:{d['misses']}"
                    for label, d in graph_diffs.items()
                    if d.get("ok") is False
                ]
                if len(misses) > self.cfg.validation.max_graph_diff_misses:
                    ok = False
                    reasons.append(f"graph_diff:{misses}")
            dupes = [label for label, n in novelty_rows.items() if n.get("near_duplicate")]
            if dupes:
                ok = False
                reasons.append(f"near_duplicate_variants:{dupes}")

            if not ok:
                raise StageError("family_rejected", "family failed validation", {"reasons": reasons, "validations": {k: v.model_dump(mode="json") for k, v in validations.items()}})

            if stop_after == "validate":
                return self._partial(cid, started, stages)

            # ---------------- build + accept ----------------
            family = self._build_family(cid, cand, blueprint, text, semantic, claims,
                                        variant_state, validations, novelty_rows, graph_diffs, stats_before,
                                        sections=sections,
                                        document_plan_id=document_plan.plan_id if document_plan else None)
            path = self._accept(cid, cand, family, semantic)
            stages.append("accept")
            self.log(f"{cid} ACCEPTED as {family.family_id} ({family.split}) -> {path.name}")
            elapsed = time.perf_counter() - started
            return CandidateResult(cid, "ACCEPTED", family.family_id, [], elapsed, stages)

        except BudgetExceeded as exc:
            self.log(f"{cid} budget exceeded: {exc}")
            self.store.set_candidate_status(cid, "PENDING", {"note": "budget exceeded"})
            return CandidateResult(cid, "PENDING", None, [f"budget: {exc}"], time.perf_counter() - started, stages)
        except StageError as exc:
            self.store.quarantine(cid, [f"{exc.code}: {exc}"], exc.code, exc.details)
            self.log(f"{cid} QUARANTINED ({exc.code}): {exc}")
            return CandidateResult(cid, "QUARANTINED", None, [exc.code], time.perf_counter() - started, stages)
        except PermanentLlmError as exc:
            self.store.quarantine(cid, [f"llm_permanent: {exc}"], "llm", {})
            self.log(f"{cid} QUARANTINED (llm): {exc}")
            return CandidateResult(cid, "QUARANTINED", None, ["llm_permanent"], time.perf_counter() - started, stages)
        except TransientLlmError as exc:
            # Network/DNS/5xx failures are not data failures. Keep the candidate
            # pending so a later run/resume retries it from its cached stages.
            self.store.set_candidate_status(cid, "PENDING", {"transient_error": str(exc)})
            self.log(f"{cid} PENDING after transient transport error: {exc}")
            return CandidateResult(cid, "PENDING", None, ["transient_llm"], time.perf_counter() - started, stages)
        except Exception as exc:
            tb = traceback.format_exc()[-4000:]
            err_path = self.store.data_dir / "logs" / "errors.log"
            with err_path.open("a", encoding="utf-8") as fh:
                fh.write(f"\n=== {utcnow()} {cid} ===\n{tb}\n")
            self.store.quarantine(cid, [f"internal_error: {type(exc).__name__}: {exc}"], "internal", {"traceback": tb})
            self.log(f"{cid} FAILED internal: {type(exc).__name__}: {exc}")
            return CandidateResult(cid, "FAILED", None, ["internal_error"], time.perf_counter() - started, stages)
        finally:
            self.store.update_manifest({"run_id": self.run_id, "config_hash": self.cfg.config_hash()})

    # ------------------------------------------------------------------ #
    def _client_stats(self) -> dict[str, Any]:
        try:
            return dict(self.client.stats())
        except Exception:
            return {}

    def _make_variant(
        self,
        cid: str,
        label: str,
        base_text: str,
        claims: list[Claim],
        semantic: SemanticRepresentation,
        prior_feedback: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        stage = f"variant_{label}"
        model = self.cfg.llm.editor.name
        if force:
            self.store.start_job(cid, stage, model, self.prompts.get("edit_plan").full_version)

        def do_edit() -> dict[str, Any]:
            outcome = create_variant(
                self.client, self.cfg, label, base_text, claims, semantic,
                candidate_id=cid, prior_feedback=prior_feedback,
            )
            self.store.save_artifact(cid, f"variant_{label}", outcome.as_dict())
            # re-extract edited passage for graph diff
            try:
                variant_sem = extract_semantics(
                    self.client, self.cfg, outcome.text, candidate_id=cid,
                    stage=f"extract_{label}",
                )
                self.store.save_artifact(cid, f"semantic_{label}", variant_sem.model_dump(mode="json"))
            except StageError as exc:
                self.store.save_artifact(cid, f"semantic_{label}", {"error": exc.as_dict()})
            return outcome.as_dict()

        if force:
            out = do_edit()
            self.store.finish_job(cid, stage, "SUCCEEDED", str(self.store.artifact_path(cid, stage)))
            return out
        return self._stage(cid, stage, "edit_plan", model, do_edit)

    def _validate_variant(
        self, cid: str, label: str, claims: list[Claim], text: str, force: bool = False
    ) -> ValidationResult:
        stage = f"validation_{label}"
        model = self.cfg.llm.validator.name

        def do_validate() -> ValidationResult:
            return validate_passage(
                self.client, self.cfg, claims, text, label, candidate_id=cid, stage=stage,
            )

        if force:
            self.store.start_job(cid, stage, model, self.prompts.get("validate").full_version)
            try:
                out = do_validate()
                payload = out.model_dump(mode="json")
                self.store.save_artifact(cid, stage, payload)
                self.store.finish_job(cid, stage, "SUCCEEDED", str(self.store.artifact_path(cid, stage)))
                return out
            except Exception as exc:
                self.store.finish_job(cid, stage, "FAILED", error=str(exc)[:1000])
                raise
        raw = self._stage(cid, stage, "validate", model, do_validate)
        return ValidationResult.model_validate(raw)

    # ------------------------------------------------------------------ #
    def _build_family(
        self,
        cid: str,
        cand: BlueprintCandidate,
        blueprint: Blueprint,
        base_text: str,
        semantic: SemanticRepresentation,
        claims: list[Claim],
        variant_state: dict[str, dict[str, Any]],
        validations: dict[str, ValidationResult],
        novelty_rows: dict[str, dict],
        graph_diffs: dict[str, dict],
        stats_before: dict[str, Any],
        sections: list[PassageSection] | None = None,
        document_plan_id: str | None = None,
    ) -> Family:
        seq = self.store.next_counter("passage")
        with self._lock:
            family_seq = self.store.next_counter("family")
            fid = family_id_from_seq(family_seq)
            split, group_id = self.splits.assign(
                fid, cluster_key=f"cand:{cand.topic_ids[0] if cand.topic_ids else cid}"
            )
        variants: dict[str, Variant] = {}
        for label in LABELS:
            state = variant_state[label]
            log = EditLog.model_validate(state["edit_log"])
            vtext = state["text"]
            sem_raw = self.store.load_artifact(cid, f"semantic_{label}")
            variant_sem = None
            if sem_raw and isinstance(sem_raw, dict) and "error" not in sem_raw and sem_raw.get("facts") is not None:
                try:
                    variant_sem = SemanticRepresentation.model_validate(sem_raw)
                except Exception:
                    variant_sem = None
            v = Variant(
                variant_id=variant_id(fid, label),
                label=label,
                text=vtext,
                token_count=approx_tokens(vtext),
                checksum=sha256_text(vtext),
                edit_history=log,
                is_pure_patch=bool(state.get("is_pure_patch", True)),
                relations_by_claim=validations[label].relations,
                evidence_spans=evidence_spans_from_relations(vtext, validations[label].relations),
                contradiction_spans=evidence_spans_from_relations(vtext, validations[label].relations) if label == "CONTRADICTED" else [],
                validation=validations[label],
                semantic_representation=variant_sem,
                graph_diff=graph_diffs.get(label, {}),
            )
            variants[label] = v

        stats_after = self._client_stats()
        calls = int(stats_after.get("calls", 0)) - int(stats_before.get("calls", 0))
        pt = int(stats_after.get("prompt_tokens", 0)) - int(stats_before.get("prompt_tokens", 0))
        ct = int(stats_after.get("completion_tokens", 0)) - int(stats_before.get("completion_tokens", 0))
        cost = float(stats_after.get("cost_usd", 0.0)) - float(stats_before.get("cost_usd", 0.0))
        prompt_versions = self.prompts.versions()
        agreement_vals = [v.agreement for v in validations.values() if v.agreement is not None]
        audit_flags: list[str] = []
        if self.cfg.validation.human_audit_fraction > 0:
            h = int(sha256_text(fid)[:8], 16) / float(16 ** 8)
            if h < self.cfg.validation.human_audit_fraction:
                audit_flags.append("sampled_human_audit")

        family = Family(
            family_id=fid,
            split_group_id=group_id,
            language=self.cfg.project.language,
            script=self.cfg.project.script,
            locale=self.cfg.project.locale,
            source=SourceRef(
                source_type=cand.source_type,
                document_id=cand.document_id,
                license_or_usage_notes="synthetic generation" if cand.source_type == "synthetic" else None,
            ),
            topic=TopicRef(topic_ids=cand.topic_ids, topic_path=cand.topic_path),
            blueprint=blueprint,
            base_passage=PassageRecord(
                passage_id=passage_id_from_seq(seq),
                document_id=cand.document_id,
                document_plan_id=document_plan_id,
                text=base_text,
                genre=blueprint.genre,
                tone=blueprint.tone,
                structure=blueprint.structure,
                narrative=blueprint.narrative,
                complexity=blueprint.complexity,
                source_type=cand.source_type,
                sections=sections or [],
            ),
            semantic_representation=semantic,
            claim_set=claims,
            variants=variants,
            generation=GenerationMeta(
                planner_model=self.cfg.llm.generator.name,
                passage_generator_model=self.cfg.llm.generator.name,
                claim_generator_model=self.cfg.llm.claims.name,
                editor_model=self.cfg.llm.editor.name,
                extractor_model=self.cfg.llm.extractor.name,
                validator_model=self.cfg.llm.validator.name,
                prompt_versions=prompt_versions,
                config_hash=self.cfg.config_hash(),
                seed=self.cfg.project.seed,
                run_id=self.run_id,
                llm_calls=calls,
                prompt_tokens=pt,
                completion_tokens=ct,
                estimated_cost_usd=round(cost, 8),
            ),
            quality=Quality(
                status="ACCEPTED",
                hard_checks_passed=True,
                human_verified=False,
                rejection_reasons=[],
                scores={
                    "validator_agreement": round(sum(agreement_vals) / len(agreement_vals), 4) if agreement_vals else None,
                    "claim_types": claim_types(claims),
                    "claim_redundancy": claim_word_overlap(claims),
                    "length_ratios": {
                        label: round(variants[label].token_count / max(1, approx_tokens(base_text)), 3)
                        for label in LABELS
                    },
                    "graph_diff_misses": {k: d.get("misses", []) for k, d in graph_diffs.items()},
                },
                audit_flags=audit_flags,
                novelty={label: novelty_rows[label] for label in LABELS},
            ),
            split=split,
            idempotency_key=cand.idempotency_key,
        )
        return family

    def _accept(self, cid: str, cand: BlueprintCandidate, family: Family, semantic: SemanticRepresentation) -> Path:
        self.store.start_job(cid, "accept")
        with self._lock:
            path = self.store.save_family(
                family.model_dump(mode="json"), family.quality.status, family.split,
                family.split_group_id, cand.idempotency_key,
            )
            self.store.save_artifact(cid, "family", family.model_dump(mode="json"))
            self.store.set_candidate_status(cid, "ACCEPTED", {"family_id": family.family_id})
            self.store.finish_job(cid, "accept", "SUCCEEDED", str(path))
            try:
                self.novelty.add_family(family)
            except Exception as exc:
                self.log(f"index update failed for {family.family_id}: {exc}")
            graph = load_graph(self.cfg.data_dir)
            for tid in cand.topic_ids:
                record_outcome(graph, tid, accepted=True)
            save_graph(graph, self.cfg.data_dir)
            self.store.log_event("family_accepted", candidate_id=cid, family_id=family.family_id,
                                 detail={"split": family.split, "claims": len(family.claim_set)})
        return path

    # ------------------------------------------------------------------ #
    # Batch runs
    # ------------------------------------------------------------------ #
    def run(
        self,
        limit: int,
        seed_topic: str | None = None,
        topic_ids: list[str] | None = None,
        expand: bool = False,
        stop_after: str | None = None,
        retry_quarantined: bool = False,
        candidates: list[dict[str, Any]] | None = None,
    ) -> RunSummary:
        started = time.perf_counter()
        notes: list[str] = []
        rows = candidates if candidates is not None else self.ensure_candidates(limit, seed_topic, topic_ids, expand)

        def is_terminal(row: dict) -> bool:
            status = row.get("status")
            if status == "ACCEPTED":
                return True
            if status == "QUARANTINED" and not retry_quarantined:
                return True
            return False

        pending = [r for r in rows if not is_terminal(r)]
        skipped = len(rows) - len(pending)
        processed = accepted = quarantined = failed = 0
        accepted_ids: list[str] = []
        max_workers = max(1, self.cfg.execution.max_concurrency)
        pending_iter = iter(pending)

        def can_submit() -> bool:
            if stop_after is None and accepted >= limit:
                return False
            if stop_after is not None and processed >= limit:
                return False
            return self._budget_ok()

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            inflight: dict[Any, dict[str, Any]] = {}

            def fill() -> None:
                while len(inflight) < max_workers and can_submit():
                    try:
                        row = next(pending_iter)
                    except StopIteration:
                        break
                    inflight[pool.submit(self.process_candidate, row, stop_after)] = row

            fill()
            while inflight:
                done, _ = wait(inflight, return_when=FIRST_COMPLETED)
                for fut in done:
                    inflight.pop(fut, None)
                    res = fut.result()
                    processed += 1
                    if res.status == "ACCEPTED":
                        accepted += 1
                        if res.family_id:
                            accepted_ids.append(res.family_id)
                    elif res.status == "QUARANTINED":
                        quarantined += 1
                    elif res.status == "FAILED":
                        failed += 1
                    elif res.status == "PENDING":
                        notes.append(f"{res.candidate_id}: {res.reasons}")
                fill()
            if not can_submit() and not inflight:
                notes.append("stopped: acceptance/processing limit or cost budget reached")

        elapsed = time.perf_counter() - started
        try:
            stats = self.client.stats()
        except Exception:
            stats = {}
        summary = RunSummary(
            run_id=self.run_id,
            requested=limit,
            accepted=accepted,
            quarantined=quarantined,
            failed=failed,
            skipped=skipped,
            processed=processed,
            elapsed_s=elapsed,
            llm=stats,
            accepted_ids=accepted_ids,
            notes=notes,
        )
        self.store.update_manifest({
            "last_run": summary.as_dict(),
            "config_hash": self.cfg.config_hash(),
        })
        self.log(
            f"run complete: accepted={accepted} quarantined={quarantined} failed={failed} "
            f"skipped={skipped} in {elapsed:.1f}s"
        )
        return summary

    def _budget_ok(self) -> bool:
        limit = self.cfg.execution.max_total_cost_usd
        if limit <= 0:
            return True
        try:
            return float(self.client.stats().get("cost_usd", 0.0)) < limit
        except Exception:
            return True

    # ------------------------------------------------------------------ #
    def resume(self, limit: int = 1000, retry_quarantined: bool = False) -> RunSummary:
        rows = [r for r in self.store.list_candidates() if r["status"] in ("PENDING", "FAILED", "RUNNING")]
        if retry_quarantined:
            rows += self.store.list_candidates("QUARANTINED")
        return self.run(limit=limit, candidates=rows, retry_quarantined=retry_quarantined)

    def close(self) -> None:
        try:
            self.novelty.save()
        except Exception:
            pass
        self.store.close()
