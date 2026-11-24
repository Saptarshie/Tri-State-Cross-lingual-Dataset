# Design

Status: living document. Implementation matches this document as of the pilot run recorded in
`docs/state.md`. Where the objective allows a choice, the decision and its failure mode are
recorded here rather than in code comments only.

---

## 1. Purpose and non-goals

The system manufactures **passage families** for evidence-conditioned verification: one fixed
claim set, three passages whose relationship to that claim set is known by construction and
verified independently.

In scope:

- corpus-first generation of short English passages;
- abstract blueprint before prose, fact graph after prose;
- 2–5 atomic claims anchored to exact evidence spans;
- coordinated SUPPORTED / CONTRADICTED / UNSUPPORTED variants from one base;
- independent validation, deterministic gates, quarantine, novelty memory;
- family-level splits, versioned exports, resumable jobs, reports.

Out of scope in this milestone (deliberately):

- real-world fact checking as an acceptance criterion;
- multilingual/Bengali/Banglish descendants;
- a distributed queue or hosted service;
- external news crawling at scale (local ingestion is implemented; network ingestion is not);
- model training or evaluation harnesses (the dataset is built so they can be added).

---

## 2. System overview

```
topic graph ──► coverage-aware selection ──► candidate (idempotency key)
                                                   │
                                          pre-generation novelty report
                                                   ▼
                                        blueprint (LLM, JSON)
                                                   ▼
                                        base passage (LLM + screening)
                                                   ▼
                                   extraction: facts + exact spans (LLM)
                                                   ▼
                                      atomic claims (LLM + filters)
                                                   ▼
                             independent base-support check (LLM validator)
                                                   ▼
            ┌─────────────── coordinated patch editing (LLM → deterministic engine)
            │        SUPPORTED            CONTRADICTED            UNSUPPORTED
            │              └──────────── repair loop (bounded) ──────────┘
            ▼
     per-variant independent validation (different model family, label hidden)
            ▼
     deterministic family checks + graph diff (soft) + novelty post-check
            ▼
     ACCEPT (immutable record, HNSW update, split assignment)  |  QUARANTINE
            ▼
     reports, index snapshots, versioned export
```

Every arrow is a durable job with an atomic JSON artefact; nothing is held only in memory.

---

## 3. Data contracts

### 3.1 Labels and the family contract

`SUPPORTED`, `CONTRADICTED`, `UNSUPPORTED` are the only stored labels. For claim set
`C = {c1..ck}`:

- SUPPORTED ⇒ every `c_i` entailed;
- CONTRADICTED ⇒ every `c_i` explicitly contradicted;
- UNSUPPORTED ⇒ every `c_i` neither entailed nor contradicted.

Any other relation vector is **mixed**. Mixed families are quarantined with a structured
failure report; they are never assigned a primary label. The mapping from validator output to
a label is deterministic (`schema.EXPECTED_RELATION`), not an LLM judgement.

### 3.2 Family record

`schema.Family` is the schema of record and enforces at parse time:

- exactly the three labels, each variant declaring its own label;
- unique claim IDs, 1–8 claims;
- validation label agreement per variant;
- for ACCEPTED records, three distinct variant texts.

A family carries: source/provenance, topic path, blueprint, base passage (checksummed),
semantic representation (entities, facts with spans), claim set with evidence spans, three
variants (text, checksum, edit log, relation rows, spans, graph diff, validation), generation
metadata (models, prompt versions, config hash, run ID, tokens, cost), quality block, split.

### 3.3 IDs

`FAM_000001`, `GROUP_000001`, `P_000001`, `V_S_000001`, `BP_<hash10>`, `CAND_<hash10>`,
`C1..`, `F1..`, `S1..`. Sequential IDs are allocated inside SQLite transactions. Candidate IDs
are hash-derived so the same planning intent maps to the same candidate after a crash. Family
IDs are allocated at acceptance, so a quarantined candidate can leave a gap in the sequence;
this is intentional (acceptance order, not generation order).

---

## 4. Stages, jobs and resumability

Each stage writes `work/<candidate>/<stage>.json` atomically, then records `SUCCEEDED` with the
artefact path. A rerun skips a stage when:

1. its job is `SUCCEEDED`,
2. the artefact still exists, and
3. the recorded prompt version **and** model name equal the current ones.

Otherwise the stage re-runs and overwrites its artefact (the attempt counter increments).

Failure semantics:

| Failure                               | Result                                                                |
| ------------------------------------- | --------------------------------------------------------------------- |
| `StageError` (quality/semantic)       | candidate quarantined with `code: message` + details                  |
| permanent provider error (4xx/schema) | candidate quarantined as `llm_permanent`                              |
| transient provider error              | bounded exponential backoff with jitter, then fail                    |
| budget exhausted                      | candidate returned to `PENDING`; run stops cleanly                    |
| unexpected exception                  | full traceback to `logs/errors.log`, candidate quarantined `internal` |

Known limitation: invalidating a prompt or model re-runs that stage in isolation; downstream
artefacts produced from the older output are not automatically invalidated. For a clean
rebuild, use a fresh data directory or delete the affected candidate workdirs. Recorded prompt
versions make the inconsistency auditable.

---

## 5. Providers, prompts and cost

### 5.1 Provider

OpenAI-compatible `POST {base}/chat/completions`. The commandcode endpoint returns **403 to
Python's default user agent**; every request therefore sets a normal `User-Agent`
(`llm.user_agent`). The client supports:

- content-addressed cache (`data/llm_cache/<stage>/<hash>.json`) → free, deterministic reruns;
- raw request/response checkpoint **before** parsing (`data/raw/<run>/<stage>/<hash>.json`);
- retries only for 408/409/425/429/5xx, honouring `Retry-After`, with jittered backoff;
- one schema-repair round (re-prompt with the validation error and the offending text);
- per-call token/cost ledger in SQLite (`calls`) plus an append-only JSONL mirror;
- an optional global USD budget (`execution.max_total_cost_usd`).

`LLM_MAX_TOKENS` (from `.env`) sets the output ceiling for every stage. This matters because the
hosted DeepSeek/MiMo/Gemini models are *reasoning* models: with a low ceiling they spend the
entire budget on hidden reasoning and return an empty `content` with `finish_reason: length`.
The pilot therefore runs with a 64k ceiling; observed outputs stop well below it.

### 5.2 Prompts

Prompts are files under `prompts/` with YAML front matter (`version`, `stage`) and `{{vars}}`.
`Prompt.version + sha256(body)` is recorded per call and per family, and is part of the stage
cache key. Variables are validated: a missing placeholder raises before any network call.

Prompt set: `topics_expand`, `blueprint`, `passage`, `extract`, `claims`, `edit_plan`,
`validate`, `validate_second`.

### 5.3 Model assignment (pilot defaults)

| Stage              | Model                          | Why                                                |
| ------------------ | ------------------------------ | -------------------------------------------------- |
| blueprint, passage | `deepseek/deepseek-v4.1-flash` | creative prose quality                             |
| extraction, claims | `xiaomi/mimo-v2.6-flash`       | dependable JSON, faster/cheaper                    |
| editing            | `deepseek/deepseek-v4.1-flash` | precise localized patches                          |
| validation         | `google/gemini-3.8-flash`      | independent family from editor and claim generator |
| second validation  | `xiaomi/mimo-v2.6-flash`       | disagreement check, cheap                          |

Independence is structural: the editor is DeepSeek, the validator is Gemini, and the intended
label is never included in the validation prompt.

---

## 6. Generation details

### 6.1 Topic graph

Two-level seed graph (`configs/seed_topics.yaml`) with descriptions, importance, parent links
and related siblings. `expand_topic` may add bounded children (`topic_max_depth`,
`max_children_per_topic`). Selection is inverse-frequency:

```
score = (1 / sqrt(1 + accepted)) · (0.4 + importance) · saturation · jitter
```

with an exploration probability, a preference for unused parent branches, and every score
component logged. Acceptance propagates `accepted += 1` to the topic and `×0.5` per ancestor.

### 6.2 Blueprint

An LLM plan (concept, subtopics, planned entity/relation/fact types, fact count) plus style
sampled deterministically from the configured genre/tone/structure/complexity lists, biased
toward the least-used options reported by the novelty service. A novelty report (similar
blueprints, overrepresented relations/entities, suggested style) is computed twice: a
topic-level report before planning, and a plan-level report attached to the blueprint.

### 6.3 Document generation (length-configurable)

The base artifact is a **document**, not a paragraph. Length is a configuration dial, not a
prompt constant:

```yaml
passage:
  target_tokens_min: 2000      # default pilot band
  target_tokens_max: 4000
  sections_min: 3
  sections_max: 8
  section_tokens_min: 450
  section_tokens_max: 900
  max_sections: 24
  single_call_below_tokens: 700  # <= this max -> legacy single-call path
```

`target_tokens_max <= single_call_below_tokens` keeps the legacy single-call path (used by the
test suite). Otherwise generation is sectioned:

1. **Blueprint** remains an abstract plan and is explicitly a *soft direction*: it fixes subject
   and angle but requires room for added entities, sequences, measurements and consequences.
   `target_fact_count` scales with document size (6–12) and blueprint length bounds come from
   `passage.target_tokens_*`.
2. **Document plan** (`prompts/document_plan.md` → `DocumentPlan`) fixes a throughline and a list
   of `SectionPlan`s: id, title, purpose, target tokens, key points, expected entities/relations.
   Section count is derived (`target_mean / section_mean`, clamped to
   `sections_min..max_sections`); the plan is rejected if it falls outside
   `sections_min..max(sections_max, derived)`.
3. **Section writing** (`prompts/section.md`) is one call per section with the blueprint, the
   throughline, the section spec, the covered-point list and the last
   `section_context_chars` of prior text. Sections are independent artefacts
   (`work/<candidate>/section_<key>.json`, keyed by plan + section + prompt version), so a crash
   resumes without re-paying completed sections.
4. **Screen and repair**: each section is checked for the token band (0.5–1.8× target), script
   ratio, meta-language, markdown/bullets, trailing colon, sentence count, repeated sentences.
   One repair attempt carries explicit feedback.
5. **Assembly**: sections are joined with `\n\n`; offsets are verified to reconstruct each
   section exactly; `PassageSection` records start/end/tokens/checksum. The assembled document is
   screened against `target_tokens_min*min_document_ratio .. target_tokens_max*max_document_ratio`,
   English/meta/repetition rules and 12-gram cross-section overlap
   (`max_cross_section_overlap`). If it is short, the weakest section is expanded once.

The abstract compact concept is therefore retained as a **novelty constraint**, not as a length
target: the document extends it with new material instead of restating it.

Declared `sections` are carried into the `PassageRecord` and family export, so claim/evidence
section attribution survives into the dataset.

### 6.4 Extraction and claims

Extraction is whole-document for short texts and **windowed** for long ones:

- `extraction.window_tokens` (default 1500, 0 = whole document) splits the document at sentence
  boundaries; every window carries a global sentence-ID offset so quotes resolve against the full
  base text;
- `max_windows` caps calls; leftover windows are sampled deterministically, recorded in the
  representation;
- each fact gets `section_id` from its evidence span; this is what lets claims-per-document and
  claim spread be enforced.

Extraction returns facts with a sentence ID and a verbatim quote. Quotes are resolved by
`spans.resolve_quote` against the immutable document: exact, then whitespace-tolerant, and only
then whole-document fallback. Facts without a resolvable span are dropped; fewer than
`extraction.min_facts` triggers one re-extraction with feedback.

Claims are filtered deterministically before validation:

- one sentence, ≤`claims.max_claim_chars`, no pronoun-led subject;
- no compound proposition (`;`, `, and/but/while`, or two auxiliary verbs joined by “and”);
- ≥60% of claim content tokens present in the document;
- mentions a known entity;
- ≥1 resolvable evidence span;
- near-duplicate of a sibling claim (bigram Jaccard > 0.8 or identical fact set) rejected.

Selection is configurable:

```yaml
claims:
  min_claims_per_family: 2
  max_claims_per_family: 12
  target_claims_per_document: 4   # approximate count to request per document
  min_distinct_sections: 2        # spread claims across the document
```

`choose_claim_facts` first fills one fact per section (round-robin over evidence spans), then
balances claim types and fact confidence up to the target. The prompt receives the boundary
numbers as literal strings (`{{min_claims}}`, `{{max_claims}}`, `{{target_claims}}`), so changing
the count needs no prompt edit. Surviving claims are renumbered and an independent validator
re-checks that the **base document** entails every claim; failing claims are dropped (recorded),
and if fewer than the minimum survive the candidate is quarantined rather than edited.

---

## 7. Editing

### 7.1 Patch engine (`patch.py`)

Patches are `{operation, target_sentence_id, original_text, replacement_text,
affected_claim_ids, reason}`. The engine:

- verifies the base checksum;
- locates `original_text` exactly once inside the named sentence, else once in the passage,
  else via whitespace-normalized matching (recorded as non-exact);
- rejects missing, ambiguous, overlapping and no-op patches;
- applies in ascending offset order, tracking before/after offsets per entry;
- performs only whitespace/punctuation cleanup (double spaces, space before punctuation);
- returns the new text plus an `EditLog` with a unified diff, checksums and attempts.

The base text is never mutated; variants are new strings with their own checksums.

### 7.2 Coordinated plan → apply → validate loop

The editor sees the whole claim set, the numbered sentences, per-claim evidence **and every
plausible mention of each claim**. It must produce patches covering every claim ID. Allowed
operations are label-specific:

| Label        | Allowed                                                                                |
| ------------ | -------------------------------------------------------------------------------------- |
| SUPPORTED    | `NEUTRAL_REWRITE`, `REPLACE_CLAUSE` (or no patches at all → base kept)                 |
| CONTRADICTED | entity/number/time substitution, relation reversal, polarity, category, clause rewrite |
| UNSUPPORTED  | delete span, neutral rewrite, clause replacement                                       |

**Mention coverage.** A long document restates facts in the introduction, body and conclusion.
Editing only the evidence sentence leaves the original statement in place; the validator then
sees a document that says both 52 and 38 and returns `UNCERTAIN`, or one that still entails an
"UNSUPPORTED" claim. `claim_mentions()` scans the document for sentences sharing the claim's
content terms or numbers, marks evidence and high-overlap sentences `required`, and the planner
receives them. For CONTRADICTED/UNSUPPORTED a plan is rejected until every required mention is a
patch target, and the prompt requires the same replacement value in all of them. Unlisted
sentences remain unchanged and are treated as neither establishing nor contradicting.

A plan is rejected before application if it leaves coverage gaps, misses a required mention,
references unknown claims, uses a forbidden operation, produces an unapplicable patch, or fails
structural screening (length ratio 0.45–1.9, content overlap ≥0.25, script check, meta-language
check, sentence presence). Feedback from each rejection is fed into the next attempt, within
`1 + max_edit_repair_attempts` attempts. After family validation, failed variants get additional
bounded repair rounds driven by the validator's structured failure report (all claims
re-planned, not just the failing one).

This is a ReAct-style loop in the sense required by the objective — observe, plan, act,
re-extract, verify, repair, commit/reject — with hard bounds at every step.

### 7.3 Shortcut controls

- SUPPORTED variants may be paraphrased, not only copied;
- CONTRADICTED uses multiple operation types (entity, number, time, category, polarity);
- UNSUPPORTED must keep the topic and length (≥45% of base tokens), not become a stub;
- style is sampled across all labels, never tied to a label;
- the shortcut audit (§12) measures residual surface signals.

---

## 8. Validation

### 8.1 Independent relation check

`validate.md` receives the passage (numbered sentences) and the claim set — **not** the intended
label, the editor's reasoning, or the base passage. It returns, per claim, one of
`ENTAILED / CONTRADICTED / NEUTRAL / UNCERTAIN`, a confidence, a deciding sentence and a quote.
The prompt states explicitly: judge the passage only; fictional/counterfactual content is
allowed; omission is not contradiction; internal inconsistency is `UNCERTAIN`.

Mapping to status:

```
PASS  ⇔ every claim has the expected relation and confidence ≥ min_relation_confidence
FAIL  ⇔ any claim has a wrong relation, missing row, or insufficient confidence
```

A second validator (different model, different prompt decomposition) runs when confidence is
low, when the first result fails (`second_validator_on_failure`), or on a random audit sample.
Any disagreement on a claim that the first validator accepted is a hard failure and lands in the
disagreement queue (recorded in the validation artefact).

### 8.2 Deterministic family checks (`validate.family_hard_checks`)

Three labels present; claim count in range; unique claim IDs; every claim has evidence and fact
links; English/Latin; source provenance present; three distinct variant texts; per-variant
length ratio; per-variant script; no meta-language; content overlap with base; no repeated
sentences; UNSUPPORTED not an obvious truncation; base non-empty.

A family is accepted only when all three validations PASS **and** every deterministic check
passes. Otherwise it is quarantined with machine-readable reasons.

### 8.3 Graph diff (soft signal)

After each edit the passage is re-extracted and compared fact-by-fact with the base graph:
supported claims must remain established, contradicted claims must have an incompatible value,
unsupported claims must have neither. Predicate matching is token-based; a reversed triple is
treated as a neutral mention (extraction frequently swaps voice, and a voice swap is a
paraphrase, not a contradiction). Unrelated-fact stability is reported.

Because extraction is lossy, graph diff is **advisory** by default
(`validation.require_graph_diff: false`). It is stored per variant, reported, and can be made a
gate by configuration with `max_graph_diff_misses`. If the per-variant re-extraction fails or its
artefact is malformed, the diff is recorded with `status: unavailable` and contributes no miss:
a failed diagnostic must never reject a family that already passed independent validation.
When the gate is enabled, only entries with `ok: false` count toward the miss budget. Graph diff
never overrides the independent validator's decision.

### 8.4 Quarantine, not relabel

Mixed families, edit failures, unsupported base claim sets, near-duplicates and budget
overruns are quarantined with their workdir pointer. The original candidate can be re-run after
a prompt/config change; accepted families are immutable.

---

## 9. Novelty memory (HNSW)

### 9.1 Embeddings

- Default: Ollama `embeddinggemma` (768-d), L2-normalised, cached by `(model, text)` hash under
  `data/embeddings/`.
- If Ollama is unavailable, a deterministic signed-hashing TF vectoriser at the same dimension
  is used, and the index records which embedder built it. Mixing embedders is refused with an
  explicit `index build` instruction.
- No hosted embeddings endpoint was assumed (the provider exposes none).

### 9.2 Index

`hnsw.py` is a compact implementation of the Malkov–Yashunin graph: geometric level
assignment, greedy descent, `ef_construction` beam at each level, diversified neighbour
selection (`sim(candidate, selected) < sim(candidate, query)`), and a `ef_search` beam at layer
0. Exact cosine search is retained for fallback and for the recall test (recall@10 ≥ 0.9 on 300
random vectors; measured 1.0 at the current settings).

Snapshots store vectors, metadata and parameters; the graph is rebuilt deterministically from
insertion order on load, which keeps snapshots portable.

**Chunked document indexing.** A 2k–15k-token document cannot be embedded as one vector: the
local embedding model has a small context, so a single embedding would silently represent only
the opening of the text. The passage namespace therefore stores **sentence-aligned chunks** of
`passage_chunk_tokens` (default 1200) with `chunk_index`, `n_chunks`, `chunk_start`, `chunk_end`
and a per-chunk `chunk_hash`; the document-level `text_hash` is repeated on every chunk.

Post-generation novelty is computed per chunk: best cosine, exact chunk-hash match, and a
near-duplicate chunk fraction (`near_duplicate_chunk_fraction`, default 0.5). A document is a
near-duplicate if the best chunk passes the cosine/Jaccard thresholds, any chunk is an exact
copy, or at least half its chunks individually match an indexed chunk. This is stricter than a
best-chunk match and prevents "new document, copied sections" from passing.

### 9.3 Namespaces

| Namespace        | Text embedded                                    | Metadata anchors                      |
| ---------------- | ------------------------------------------------ | ------------------------------------- |
| `blueprint`      | topic path, concept, subtopics, relations, genre | family, split, concept                |
| `passage`        | sentence-aligned document chunks (base+variant)  | variant ID, label, chunk offsets/hash |
| `fact_claim`     | extracted triples + claim texts                  | family, claim/fact types              |
| `edit_signature` | label + operation sequence                       | operations, family                    |

Only accepted families are indexed. Test-split entries are filtered out of every retrieval used
to steer generation (`hnsw.split_aware`). Stats (`index/stats.json`) count relations, entities,
genres, tones, structures, topic paths and edit operations, and drive the pre-generation
"underrepresented alternative" suggestions.

Post-generation checks compare cosine and bigram Jaccard against the chunked passage index.
Near duplicates are quarantined by default (thresholds configurable); a high cosine alone is a
review signal, not a rejection.

---

## 10. Splits and export

Splits are assigned once at acceptance from `sha256(salt | cluster_key)` with cumulative
thresholds 0.8/0.1/0.1. All candidates from the same topic share a cluster key, so they inherit
one group and one split; a family never appears in two splits, and its three variants cannot be
separated. Assignments are persisted; existing assignments are locked (re-assignment returns the
stored value).

Export writes:

- `families.jsonl` — canonical nested records (source of truth);
- `variants.jsonl` — flattened one-row-per-variant view, each row repeating the claim set;
- `claims.jsonl` — claim table with evidence;
- `manifest.json` — counts, hashes, model versions, config hash, problems;
- `splits.json`, `README.md`.

Records are re-validated through `Family` before writing; invalid files are reported, not
silently exported.

---

## 11. Storage and operations

- SQLite (`state/state.db`, WAL): candidates, jobs, families, calls, counters, export versions,
  events.
- JSON artefacts for stage outputs; atomic replace on write.
- A thread lock serialises index mutation, split assignment and family registration; SQLite
  writes are serialised through a connection lock.
- `manifest.json` is refreshed after every candidate for operational visibility.
- `run` processes candidates in batches of `2 × max_concurrency`; the acceptance count can
  overshoot the requested limit by at most one batch (documented and observable in the summary).
- `stop-after` runs a prefix of the pipeline and leaves the candidate `PENDING`, which
  `resume`/`run` continues from the cached artefacts.

---

## 12. Reporting and shortcut audit

`report quality` aggregates: counts by status, acceptance rate and rejection reasons, dataset
distributions (topic, genre, tone, structure, length, claims, claim types, edit operations),
split counts, validator agreement, graph-diff misses, novelty scores, token/cost totals and
per-stage cost/latency.

The shortcut audit trains a multinomial logistic regression on **surface-form features of the
passage text only** (length, sentence count, punctuation density, uppercase/digit ratios,
apostrophes). Recipe metadata (genre/tone/structure), edit counts and patch flags are deliberately
excluded: a model at inference cannot see them, so including them measures bookkeeping rather than
a learnable shortcut. The audit split is by family, so siblings cannot leak style into training.
It reports accuracy, macro-F1, a bootstrap 95% CI, and accuracy by feature group. If surface
features alone exceed `shortcut_audit_flag_accuracy`, the generator is flagged for rebalancing.
It is a diagnostic, not a model-selection signal.

---

## 13. Configuration map

`configs/default.yaml` is validated by `config.Config` (extra keys rejected). Environment
overrides: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (generator/editor), `LLM_MAX_TOKENS`,
`OLLAMA_BASE_URL`, `EMBED_MODEL`, `TRISTATE_DATA_DIR`, `TRISTATE_PROMPTS_DIR`. `.env` is read
without overriding real environment variables, and is git-ignored.

Important knobs: `passage.target_tokens_*` (document length) and `sections_*`/`max_sections`
(sectioning, derived count), `extraction.window_*`, `claims.target_claims_per_document` and
`min_distinct_sections`, variant length/overlap bounds, repair attempts, validator confidence and
second-validator policy, HNSW M/ef/thresholds and `passage_chunk_tokens`, near-duplicate
thresholds, split fractions and salt, concurrency/retries/budget, per-stage models and costs.

Length and count are set in config, not in prompts. `passage.target_tokens_min/max` is the whole
document; the prompt receives the numbers as literal strings, and section count is computed. To
change the document size, edit only these bounds (and raise `max_sections` if the derived count
would exceed it):

```yaml
passage:
  target_tokens_min: 10000
  target_tokens_max: 15000
  max_sections: 24        # 15k / ~675 mean section ~= 22
claims:
  target_claims_per_document: 12   # approximate; bounded by min/max
```

---

## 14. Testing

129 tests, no network:

- utilities: sentence segmentation, hashing, script/meta checks, atomic IO;
- IDs and schema invariants (three labels, unique claims, distinct accepted variants);
- patch engine: exact/normalized matching, ambiguity, overlap, no-op, checksum, cleanup,
  offsets, diff;
- editor loop: coverage-gap rejection and repair, forbidden operation per label, unapplicable
  span, unknown claim IDs, unmodified SUPPORTED, exhausted attempts;
- novelty service: all four namespaces indexed, rejected families not indexed, pre/post reports,
  exact-duplicate detection, test-split exclusion, rebuild;
- corpus: token-band segmentation, below-band documents dropped, local ingestion with content
  dedupe and provenance, non-English skip;
- spans: offsets and quote resolution;
- HNSW: recall vs exact, persistence, filters, normalisation;
- splits: ratios, stability, lineage groups, persistence;
- config and prompts: validation, overrides, prompt versioning;
- LLM client: parsing, cache, retry/permanent errors, schema repair, budget, checkpointing, UA;
- semantic contract: relation→status mapping, mixed rejection, low-confidence second validator
  disagreement, base-claim dropping, hard-check rejections, no world-truth gate, label hidden;
- graph diff: supported/contradicted/unsupported, neutral mentions, reversed triples, unrelated
  stability;
- end-to-end with mock workers: accepted family shape, artefacts, idempotent rerun, resume from
  a partial stage, index updated only after acceptance, split inheritance, quarantine path;
- export/report: file set, counts, versioning, report sections.

Run: `env -u PYTHONPATH .venv/Scripts/python.exe -m pytest -q` (see runbook for the PYTHONPATH
caveat).

---

## 15. Known limitations and risks

1. **Graph diff is noisy.** Extraction paraphrases subjects/predicates; the diff is advisory and
   its misses should not be read as label errors. Mitigation: independent validator is the gate.
2. **Small-N split skew.** Hash assignment can put all pilot families in `train`; ratios converge
   with scale. Do not rebalance by hand — that would break the stability guarantee.
3. **Stage invalidation is local.** Changing a prompt re-runs that stage only; downstream
   artefacts are stale. Use a clean data dir for full regeneration.
4. **Reasoning-model cost/latency.** All hosted models reason internally; 64k ceilings avoid
   truncation but calls can take 10–30s. Concurrency 3 keeps the pilot tractable.
5. **Mock workers are templated.** They exercise plumbing, not generation quality; near-duplicate
   thresholds are relaxed in `--mock` mode for that reason.
6. **No external news ingestion yet.** Local document ingestion and segmentation exist; a
   network connector must add robots/terms handling, dedupe and licence metadata.
7. **Acceptance overshoot.** A batch may accept slightly more than `--limit`.
8. **Human audit is a queue, not a tool.** Records are flagged and listed; no annotation UI or
   adjudication workflow yet.
9. **Token counts are estimates.** Length bands use a word/punctuation heuristic; billed tokens
   are recorded separately from provider usage.

---

## 16. Milestone alignment

| Milestone                                                              | State                                                                                                        |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| 0 repository/environment inspection                                    | done (docs, provider probe, embedder probe)                                                                  |
| 1 minimal end-to-end family generator                                  | done; pilot families accepted and exported                                                                   |
| 2 topic graph, HNSW indexes, pre/post novelty                          | done (four namespaces; split-aware)                                                                          |
| 3 patch editing, bounded repair, graph diff, disagreement queue        | done, except human-review export/UI                                                                          |
| 4 corpus expansion, news ingestion, style sampling, coverage scheduler | partial: topic expansion, style sampling, coverage selection and local ingestion done; network ingestion not |
| 5 scale-out (async queues, dashboards, snapshots, locked test set)     | partial: durable jobs, concurrency, budget, exports, splits done; dashboards/async workers not               |
| 6 multilingual                                                         | not started (schema fields present: language/script/locale)                                                  |

---

## 17. Decision log

| Decision                                                         | Rationale                                                  | Failure mode accepted                                                      |
| ---------------------------------------------------------------- | ---------------------------------------------------------- | -------------------------------------------------------------------------- |
| Hash-based candidate IDs, sequential family IDs                  | reruns resume the same work; acceptance order is separable | ID gaps when a candidate is quarantined                                    |
| Patch-first editing with deterministic engine                    | auditable diffs, no silent rewrites                        | model must copy spans exactly; repairs cost calls                          |
| Intended label hidden from validator | reduces confirmation bias                                  | validator may fail a correct variant; second validator and repair mitigate |
| Different model family for validation                            | avoids self-approval                                       | cost; still LLM judgement                                                  |
| Graph diff advisory                                              | extraction is lossy                                        | weak signal for subtle edits                                               |
| Ollama embeddings + hashing fallback                             | offline, deterministic, no hosted embedding API            | two embedder families cannot share an index                                |
| Only accepted records indexed                                    | novelty must not be poisoned by rejects                    | indexing lags acceptance by seconds                                        |
| Hash splits with lineage groups                                  | stable, family-level, leakage-safe                         | small-N skew                                                               |
| Quarantine mixed families                                        | preserves the all-or-nothing contract                      | lower initial yield                                                        |
| Local embeddings cache                                           | free reruns                                                | disk usage                                                                 |
