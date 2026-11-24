# Development log

Chronological, newest last. Each entry records what changed, what was verified, and any bug
worth remembering. Times are local (IST).

---

## 2026-11-24

### 1. Environment and provider inspection

- Repo contained only `docs/` (`objective.md`, `chat_log.md`); no code, no git history.
- Python: system 3.13 available; created `.venv` with `uv`. Installed pydantic, pyyaml, numpy,
  httpx, pytest.
- **Bug (host):** shell `PYTHONPATH` points at the Hermes venv and shadows project packages /
  breaks `pydantic_core`. Workaround: `env -u PYTHONPATH` for every Python invocation.
- Probed the commandcode endpoint:
  - `GET /models` → 105 models; no embeddings model.
  - `POST /chat/completions` with `json_object` and `json_schema` → valid JSON on
    deepseek-v4.1-flash, mimo-v2.6-flash, gemini-3.8-flash.
  - **403 without a normal User-Agent** (Python/urllib, curl default). Set
    `Mozilla/5.0 (compatible; tristate-factory/0.1)` on all requests.
- Ollama was installed but not running; started `ollama serve`, confirmed
  `embeddinggemma:latest` responds via `/api/embed` with **768-dim** vectors.

### 2. Foundation

- `config.py`: validated pydantic config for every objective knob; `.env` loading (real env
  wins); env overrides for base URL, key, model, max tokens, Ollama, data/prompt dirs; config
  hash for provenance.
- `schema.py`: Span/Fact/Claim/Blueprint/Patch/EditLog/ValidationResult/Variant/Family with
  family-level invariants (three labels, unique claim IDs, distinct accepted variants).
- `ids.py`, `util.py`, `store.py`: stable hashed candidate IDs, sequential family/group/passage
  counters in SQLite, atomic JSON writes, job table with attempts, call ledger, quarantine index.
- Verified: imports, config hash, schema validators, atomic IO.

### 3. Deterministic editing and retrieval primitives

- `spans.py`: sentence index with character offsets; quote resolution exact → whitespace
  tolerant → whole-passage fallback.
- `patch.py`: locate/validate/apply patches, reject missing/ambiguous/overlapping/no-op,
  record offsets and unified diff; cleanup only whitespace/punctuation.
- `hnsw.py`: numpy HNSW (M, ef, diversified neighbour selection). Recall@10 = **1.0** vs exact
  search on 400 random 64-d vectors; snapshot save/load round-trips.
- `embeddings.py`: Ollama embedder with on-disk content-addressed cache; signed-hashing fallback
  at the same dimension.
- `splits.py`: hash-threshold family splits with lineage groups and locked assignments.

### 4. LLM client

- OpenAI-compatible caller with raw pre-parse checkpoints, content-addressed cache, transient
  retry with jitter and `Retry-After`, one schema-repair round, budget guard, UA header, call
  ledger (tokens, cost, latency, cached flag).
- **Bug fixed:** duplicate `cost_usd` keyword introduced while refactoring cost accounting —
  caught by import-time SyntaxError, removed the stale `cost` field.

### 5. Generation stages

- `topics.py` + `configs/seed_topics.yaml`: two-level graph, bounded LLM expansion, inverse
  frequency selection with parent diversity and exploration, ancestor coverage propagation.
- `corpus.py`: local `.txt/.md` ingestion, sentence-window segmentation, provenance, dedupe.
- `blueprint.py`, `passage.py`, `extract.py`, `claims.py`: LLM stages with deterministic
  screening (length band, script, meta-language, atomicity, containment, evidence resolution).
- **Bug fixed:** claim support used symmetric Jaccard against a much longer passage, rejecting
  every valid claim (0 usable claims). Replaced with asymmetric containment ≥0.6; mock pipeline
  then produced claims.

### 6. Editing, validation, novelty, orchestration

- `editor.py`: label-specific operation whitelists, coverage/unknown-claim checks, patch
  application, structural screening, bounded repair with feedback.
- `validate.py`: independent per-claim relation classification with hidden intended label,
  deterministic status mapping, low-confidence/failure/sample second validator, disagreement as
  hard failure, base-claim verification, family hard checks.
- `graphdiff.py`: fact-state comparison, soft gate; initially too strict (voice-swapped triples
  and neutral mentions looked like contradictions) — later refined.
- `novelty.py`: four HNSW namespaces, embedding cache, novelty reports, near-duplicate checks,
  acceptance-only indexing, style/relation underrepresentation stats.
- `pipeline.py`: durable stage runner, prefix runs (`stop-after`), resume, repair rounds,
  gate composition, acceptance (family record, index, topic outcome, split), quarantine paths,
  budget handling, error file.

### 7. CLI, mock workers, first end-to-end runs

- `mock.py`: deterministic templated workers for every stage (rule-based relation checker) so
  the full graph can run offline; explicitly not a data source.
- CLI: `config-check`, `topics`, `corpus`, `run`, `resume`, `stage`, `index`, `report`,
  `splits`, `export`, `quarantine`, `families`.
- **Bugs found by the mock run, fixed in order:**
  1. `TopicNode.accepted_family_count` was `int`; ancestor propagation stores `0.5` → validation
     error on the next graph load. Changed to `float`.
  2. Mock passage was below the token band → deterministic screening rejected it. Lengthened the
     template and added topic-specific content.
  3. Mock entity derivation used Python's salted `hash()` → non-deterministic across processes.
     Replaced with blake2/sha256-derived seeds.
  4. Mock edit plans assumed a fixed claim order; affected-claim IDs were attached to the wrong
     claims. Plans now map patches to claim IDs by claim text.
  5. Export attempted to serialise a `WindowsPath` into `splits.json`; now reads and writes the
     JSON object.
  6. `families show FAM_…` was flag-only; added a positional argument.
- Result: mock run accepted 4/4 families; export, reports, index build and split report all
  executed offline.

### 8. Real-provider calibration

- First real run: both candidates quarantined `llm: no JSON value found in response (head='')`.
  Raw artefacts showed `finish_reason: length` with **2000/2000 completion tokens spent on
  reasoning** and empty content on the extraction call.
- Probed alternative models/limits: deepseek at 4000 still consumed everything on reasoning;
  mimo at 2000 produced 3530 chars of content but truncated; gemini truncated at 2500. All three
  are reasoning models.
- **Fix:** `.env` sets `LLM_MAX_TOKENS=64000` (also overrides every stage ceiling); per objective
  guidance the user asked for a 64k ceiling. Stage models rebalanced:
  blueprint/passage/editor on deepseek, extractor/claims on mimo, validator on gemini,
  second validator on mimo. Re-run accepted **2/2 families** in 220s for $0.016 (28 calls,
  25.5k prompt / 44k completion tokens).
- Inspected both families: passages are natural, claim sets are atomic (comparative, temporal,
  numerical, procedural, location), contradicting edits change the exact value, unsupported
  edits remove evidence while keeping the topic and length. Example: a transit-pilot family with
  cost-per-mile, charging-time, launch-date and decision-date claims.

### 9. Hardening, pilot, audit correction

- Graph diff refined: token-based predicate matching, containment-based entity matching, neutral
  mention detection (`tracked`, `monitored`, …), and voice-swapped triples treated as neutral,
  not contradictions. Added `tests/test_graphdiff.py`.
- **Pilot (limit 12):** 12 candidates processed, 12 accepted, 188 calls, 214.9k prompt /
  278.3k completion tokens, **$0.108**, 1,071 s. Two candidates left `PENDING` by batching were
  resumed: 1 accepted, 1 quarantined `claims_insufficient` (26 calls, $0.014, 291 s). Final
  corpus: **15 families / 45 variants / 54 claims**, all three labels per family.
- **Shortcut audit was wrong, then fixed.** The first audit reported 0.615 accuracy and looked
  like a leak. Cause: it included recipe metadata (genre/tone/structure one-hots), edit counts and
  `is_pure_patch`, which are unavailable at inference and correlate with the label by
  construction; it also split by variant, so siblings crossed the train/test boundary. Rewrote it
  to text-only surface features (length, punctuation, casing, digits) with a family-wise split.
  Honest result: **0.467 accuracy, 95% CI 0.27–0.73**, chance 0.333, not flagged. Added
  `tests/test_audit.py`.
- **Graph diff cannot reject on its own failure.** Found while reviewing the advisory path: a
  failed per-variant re-extraction was stored as an error artefact, then `model_validate` raised
  and the candidate was quarantined `internal` — the diagnostic could veto a family it is
  explicitly not supposed to gate. Now recorded as `status: unavailable` with no misses, and a
  regression test forces the extraction failure to prove the family still accepts.
- **Long-form base documents (2026-11-25).** A 130-token "passage" is not a RAG context, so the
  base artifact became a configurable document. `passage.target_tokens_min/max` (default
  2,000–4,000) drives a soft blueprint, a `DocumentPlan`, and one call per
  `section_tokens`-sized section with per-section artefacts and repair. Assembly verifies
  offsets and screens total length and 12-gram cross-section overlap. The compact concept is now
  only a novelty constraint, not a length target.
- **Long documents broke single-vector novelty.** The embedding model cannot see a 10k-token
  document, so the passage index stores sentence-aligned chunks (`passage_chunk_tokens`, default
  1,200) with offsets and per-chunk hashes; a document is a near-duplicate if any chunk matches
  or at least half its chunks individually match.
- **Extraction and claims scale with length.** `extraction.window_tokens` (default 1,500) windows
  the document at sentence boundaries with global sentence-ID offsets; `max_windows` caps calls.
  `claims.target_claims_per_document` replaces the run-level constant and
  `claims.min_distinct_sections` spreads claims across sections; prompts receive the numbers as
  render variables.
- **Long-document tri-state editing failed on restatements.** First real 3k-token run: 2/2
  quarantined `family_rejected`; UNSUPPORTED still entailed a claim stated in another section,
  CONTRADICTED returned `UNCERTAIN` because the document contained both the original and the
  mutated value. Fixes: `claim_mentions()` collects every plausible restatement (evidence +
  term/number overlap), the editor view includes them, and CONTRADICTED/UNSUPPORTED plans are
  rejected until every mention is a patch target; the validator prompt now forbids chaining
  separate facts and reserves `UNCERTAIN` for genuine internal contradiction.
- Test suite grown to **129 tests**, all passing offline (`pytest -q`); ruff `F,E9` clean.
- Wrote `README.md`, `docs/design.md`, `docs/state.md`, `docs/runbook.md`,
  `docs/dataset-card.md`, `docs/reports/pilot-02-*`, this log.
- Exported immutable versions `pilot-01` (14 families) and `pilot-02` (15 families).

---

## Open items (carried forward)

- Network news ingestion with robots/terms handling and licence metadata.
- Human-review export/queue (flagged records exist; no annotation UI).
- Additional SUPPORTED paraphrase operations and more CONTRADICTED operation families to reduce
  edit-signature concentration.
- Full-corpus regeneration when prompts change downstream (stage invalidation is local today).
- Larger pilot with human-audited per-class precision before scaling; at N=15 every family landed
  in `train`, so no held-out number can be reported yet.
