# State

Snapshot of what exists, what was measured, and what is next. Update after every substantive run.

Last updated: 2026-11-25 02:40 IST (long-form generator verified; `pilot-03-longform` exported).

---

## 1. Where things stand

Milestones 0–3 of the objective are implemented and exercised against the live provider.

| Area | State |
|---|---|
| package, config, schema, store | complete |
| topic graph + coverage scheduler | complete (LLM expansion, local corpus ingestion) |
| blueprint → document plan → sections → extraction → claims | complete, real-provider verified (short and 3k-token long-form) |
| coordinated tri-state editing + bounded repair | complete |
| independent validation + deterministic gates | complete (second validator, disagreement queue) |
| graph diff | implemented, advisory (`require_graph_diff: false`) |
| novelty memory (4 HNSW namespaces) | complete, Ollama `embeddinggemma` 768-d |
| splits, export, reports, shortcut audit | complete |
| multilingual (Bengali/Banglish) | not started |

Artifacts are durable per stage; `run`/`resume` continue after a crash or `Ctrl-C`. Accepted
families are immutable; quarantined candidates keep their workdir and reasons.

---

## 2. Environment actually used

- Windows 11, git-bash; `.venv` (Python 3.13) created with `uv`.
- Provider `https://api.commandcode.ai/provider/v1`, key in `.env` (never logged).
- `LLM_MAX_TOKENS=64000` from `.env`, applied to every stage; raw request artefacts confirm
  `max_tokens: 64000` and `finish_reason: stop`.
- Models: **all stages `deepseek/deepseek-v4.1-flash`** (operator changed every stage; this removes
  the cross-family separation the validator design preferred — see limitations).
- Embeddings: local Ollama `embeddinggemma` (768-d), cached under `data/embeddings/`.
- Tests: `130 passed` (offline); `ruff check --select F,E9` clean.
- Base-document length: configurable (`passage.target_tokens_*`), default 2,000–4,000; the
  pilot-02 export predates this and is the short-passage regime.

Note: every command must run with `env -u PYTHONPATH` on this host (foreign `PYTHONPATH` shadows
the project's packages).

---

## 3. Dataset inventory (`pilot-02`, short-passage regime)

> `pilot-02` is retained as the 130-token pilot. The current generator defaults to 2,000–4,000
> token documents; its first successful long-form export is `pilot-03-longform`
> (`data-v3/exports/`): 2 families / 6 variants / 7 claims, base mean 3,169 tokens, 5 sections,
> `manifest.problems: []`, all `train`. It is deliberately small (one topic group) and is not a
> quality benchmark; it proves the long-form path end to end.

Exported to `data/exports/pilot-02/` (immutable copy: `families.jsonl`, `variants.jsonl`,
`claims.jsonl`, `manifest.json`, `splits.json`, `README.md`).

| Metric | Value |
|---|---|
| families | 15 |
| variants | 45 (15 per label) |
| claims | 54 |
| claims per family | mean 3.6 (2×2, 3×4, 4×7, 5×2) |
| passage tokens | mean 128.8, range 72–169 |
| base passage tokens | mean 134.3, range 99–169 |
| splits | train 15 (hash assignment; no test/dev at this N) |
| acceptance | 15 accepted / 18 candidates (83.3%) |
| quarantined | 3: 2× `llm_permanent` (pre-64k run), 1× `claims_insufficient` |
| near-duplicates in index | 0; mean max cosine 0.310, p95 0.548 |
| index vectors | blueprint 15, passage 60, fact_claim 15, edit_signature 45 |
| total LLM cost | $0.1383 · 641,184 tokens · $0.0092/family (excludes a pre-pricing failed run of 4.4k/7.8k tokens recorded at $0, ≈$0.003 at current rates) |

Label balance is exact by construction (every accepted family has all three variants).

Distribution across recipes (pilot): 8 genres, 7 tones, 5 structures, 8 topic branches.
Claim types: TEMPORAL 12, PROCEDURAL 11, NUMERICAL 9, COMPARATIVE 7, PURPOSE 5,
ENTITY_RELATION 4, CAUSAL 4, LOCATION 2.
Edit operations: REPLACE_CLAUSE 49, NUMERICAL 19, NEUTRAL_REWRITE 14, TEMPORAL 8,
RELATION_REVERSAL 8, ENTITY 8, POLARITY 5, CATEGORY 2.

---

## 4. Runs

### Run 0 — pre-64k attempt (failed, kept for the record)

`--limit 1 --topic Technology` at the original 2,000-token stage ceilings: blueprint and passage
succeeded, both extraction calls returned empty content with `finish_reason: length`, and both
candidates were quarantined `llm_permanent`. 6 ledgered calls (4,360 prompt / 7,791 completion),
cost recorded as $0 because per-stage pricing was not yet configured. This run is the evidence
behind the 64k decision; the failed candidates are the two `QUARANTINED` rows in `pilot-02`.

### Run A — first successful real-provider run (2 families)

Two communities-transit families accepted after switching stage models and raising the output
ceiling. Proved the vertical slice; one family (`FAM_000001`) is in the pilot export.

### Run B — pilot, `--limit 12` (background, 17:34–17:52)

- 12 candidates processed, **12 accepted** (`FAM_000003`–`FAM_000014`), 0 failed.
- 188 calls · 214,865 prompt · 278,301 completion · **$0.1080** · 1,071 s.
- Three repair rounds were needed across the batch; one candidate needed two rounds on
  UNSUPPORTED (`C1: expected NEUTRAL, got ENTAILED`, then `C3: expected NEUTRAL, got
  CONTRADICTED`), both recovered.
- The run overshot its limit by 2 candidates because it works in batches; the extra candidates
  stayed `PENDING` and were resumed in Run C.

### Run C — resume the two pending candidates (17:57–18:02)

- 1 accepted (`FAM_000015`), 1 quarantined `claims_insufficient` (only one atomic claim survived
  filtering).
- 26 calls · 30,002 prompt · 36,275 completion · **$0.0144** · 291 s.
- Confirms resume reuses successful stage artefacts and only re-runs the remainder.

### Run D — first long-form run, 2k–4k targets (20:48–21:16, failed)

- Passage became a real document: 5 sections, ~3.1k tokens per base, ~45–60 s per section on
  `deepseek-v4.1-flash`.
- Both candidates were quarantined `family_rejected` after repair rounds:
  UNSUPPORTED still entailed a claim restated in another section; CONTRADICTED returned
  `UNCERTAIN` because one sentence carried the original value and another the mutated one.
- 99 calls · 634k prompt · 341k completion · **$0.1724** · 0 accepted.
- This run is kept as the evidence for the mention-coverage + validator-rubric fixes; do not
  export it.

### Run E — long-form after mention coverage (21:17–21:33, succeeded)

Fresh `data-v3`, `prompts/edit_plan.md` 3.1.0 (every restatement must be patched) and
`validate/validate_second` 1.1.0 (no cross-sentence chaining; `UNCERTAIN` only for genuine
internal contradiction).

- **2 candidates processed, 2 accepted** (`FAM_000001`, `FAM_000002`), 0 quarantined.
- Base documents: **3,049** and **3,288** tokens (mean 3,168), 5 sections each
  (section sizes 542–696 tokens); variants 2,999–3,294 tokens.
- 48 calls · 259,901 prompt · 186,680 completion · **$0.0887** · 975 s
  (≈$0.044/family, ≈8 min/family at concurrency 3).
- One CONTRADICTED repair round was needed (`C2/C3 expected CONTRADICTED, got NEUTRAL`);
  the repaired variant validated. UNSUPPORTED passed first validation for both candidates.
- Exported as **`pilot-03-longform`**: 2 families / 6 variants / 7 claims, 2 per label,
  all `train`; `manifest.problems: []`.

---

## 5. Quality observations

1. **Validator agreement is complete on accepted families** (mean 1.0), but that is a
   post-selection statistic: families that disagree are quarantined or repaired, so the accepted
   set is agreement-biased. Report it as such; the disagreement count is in each validation
   artefact.
2. **Graph diff is noisy.** 65 of 135 (claim × variant) rows report a miss, mostly because
   extraction paraphrases predicates or drops facts. Treated as advisory; do not use it to
   reject. This is the largest known measurement gap before scaling.
3. **Surface-form audit is at chance.** A text-only logistic regression (length, punctuation,
   casing, digits) reaches 0.467 accuracy (95% CI 0.27–0.73) on a family-wise split, versus 0.333
   chance; not flagged. Earlier 0.615 came from leaking recipe metadata and edit counts into the
   audit — fixed, and the audit is now a fair test.
4. **All 15 families landed in `train`.** At this N the hash split is expected to skew; do not
   rebalance by hand (it would break the stability guarantee). Fix by scale or a deliberate salt
   for a fresh dataset.
5. **Repair loop works but is the cost driver.** Failed variants trigger full re-planning; most
   extra calls are repairs. Two rounds are common for UNSUPPORTED when the editor re-establishes
   the fact it was asked to remove.
6. **Quarantine is doing its job.** One candidate produced only one atomic claim, another two
   hit the pre-64k truncation. Both are recorded with workdirs, not silently dropped.
7. **Echo/meta language** is screened deterministically and did not appear in accepted variants.
8. **Long-form path now accepts (2/2), but only after mention coverage.** The first long-form run
   (Run D) failed exactly on cross-section restatements; with `claim_mentions()` and the stricter
   validator rubric, Run E accepted both. Claims per 3k document were 3–4 (target 4), i.e. roughly
   one claim per 800–1,000 tokens — raise `target_claims_per_document` if the research design needs
   denser claim coverage.
9. **All stages now run on one model family** (`deepseek-v4.1-flash`). The independent-validator
   separation is structural only (separate prompts, hidden intended label, second validator on
   failure/low confidence), not cross-family. Restore a different validator model before making
   claims about validator independence.

Spot review of `FAM_000003`, `FAM_000005`, `FAM_000008`, `FAM_000015`: claims are atomic and
single-proposition; CONTRADICTED variants change the exact value or relation a claim depends on;
UNSUPPORTED variants keep topic, length and style while removing the evidence (no sentence
deletion to a stub). One structural caveat: when the sampled structure is `bulleted_explanation`
or `numbered_procedure`, variants legitimately contain bullets/labels, so "prose-only" checks
must stay structure-aware.

---

## 6. Known gaps and next steps (priority order)

1. **Human-audited per-class precision.** Sample ~30 variants per label (short and long-form
   separately), blind to construction, and record adjudications. This is the only way to state
   label precision. The flag queue exists (`quality.human_verified`, `human_audit_flags`), but
   there is no annotation UI.
2. **Graph-diff calibration.** Compare extraction on a small hand-checked subset, then either
   promote it to a gate with a calibrated threshold or demote it to a pure diagnostic and say so.
3. **Prove the split under scale.** Generate ≥100 families or set a fresh split salt so
   test/dev are non-empty; verify no group crosses splits and report variant-level counts.
4. **More CONTRADICTED operation families.** `REPLACE_CLAUSE` dominates (49/103 operations). Add
   scope/quantifier/causal reversal and measure per-operation validator pass rates.
5. **SUPPORTED paraphrase diversity.** Some SUPPORTED variants are close to the base (cosine
   ~0.9). Add a minimum paraphrase distance for SUPPORTED, below the near-duplicate threshold.
6. **Network corpus ingestion.** Local ingestion is done; add a connector with robots/terms,
   dedupe, and licence metadata before claiming corpus-first generation at scale.
7. **Full-dataset regeneration policy.** Stage invalidation is local; document/enforce a clean
   rebuild when prompts change downstream (or add artefact lineage hashes).
8. **Multilingual extension.** Schema already carries `language`, `script`, `locale`; prompts and
   validators are English-only.

---

## 7. Where to look

| Need | Path |
|---|---|
| design and contracts | `docs/design.md` |
| operations and recovery | `docs/runbook.md` |
| chronological decisions | `docs/devlog.md` |
| dataset card | `docs/dataset-card.md` |
| pilot report | `docs/reports/pilot-02-report.md` |
| shortcut audit | `docs/reports/pilot-02-audit.json` |
| accepted records | `data/families/FAM_*.json` |
| exported dataset | `data/exports/pilot-02/` (short), `data-v3/exports/pilot-03-longform/` (3k docs) |
| quarantine diagnostics | `data/quarantine/` |
| raw provider calls | `data/raw/<run_id>/<stage>/` |
| state database | `data/state/state.db` |

Reproduce a fresh pilot:

```bash
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate config-check
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate run --limit 10 --data-dir data2
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate export --version pilot-03 --data-dir data2
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate report md --data-dir data2
```

A new data directory is required to avoid mixing with the locked splits and existing index; it
also gives a clean test-bed for prompt changes.
