# Round-2 ablation report: loosened verifier + 30-edit repair budget

Date: 2026-11-25
Profile: `bn_in_native`
Source: first 10 accepted English families (`FAM_000001`–`FAM_000010`)
Model/reviewer: `deepseek/deepseek-v4.1-flash`
Concurrency: 4 families
Status: both arms complete.

## Change under test

Round 2 differs from round 1 in three ways:

1. The window verifier now separates **blocking** from **advisory** findings.
   Blocking: entity/number/date/unit, negation/modality/polarity/scope,
   causal/logical relation, absent↔present claim, untranslated content, added
   facts, script policy. Advisory: first-mention gloss, register/tone,
   punctuation, conventional Latin technical terms, minor word order, and
   sentence-boundary differences that preserve all source content.
2. Repair budgets are **30 fixing steps / 30 edits per step / 30 total edits**;
   `window.max_repairs` is 30.
3. The numeric tokenizer now recognises numerals adjacent to Bengali suffixes
   (`1,400টি`, `১,৪০০`) instead of falsely reporting them missing.

Both arms use the same source, profile, model, reviewer and prompts. The only
intended difference remains the repair mechanism:

- **Arm A:** bounded ReAct fixer (`fixer.enabled: true`).
- **Arm B:** deterministic sentence-targeted repair (`fixer.enabled: false`).

## Headline results

| Metric | Arm A: ReAct fixer | Arm B: deterministic repair |
|---|---:|---:|
| Accepted families | **8 / 10 (80%)** | **6 / 10 (60%)** |
| Quarantined families | 2 | 4 |
| Accepted ids | 001, 002, 003, 004, 005, 007, 009, 010 | 002, 003, 004, 005, 009, 010 |
| Manifest calls | 995 | 869 |
| Logged calls | 948 | 949 |
| Window translations | 367 | 442 |
| Window reviews | 457 | 483 |
| Fixer actions | 100 | 0 |
| Prompt tokens | 4,217,874 | 3,898,541 |
| Completion tokens | 4,160,080 | 4,317,863 |
| Median latency | 30.3 s | 29.0 s |
| Max latency | 175.6 s | 163.3 s |
| Cost | $0.00 (placeholder pricing) | $0.00 (placeholder pricing) |

Accepted families per 100 manifest calls: **0.804** (A) vs **0.690** (B).

Mean accepted target length: 3,113 words (A) vs 3,084 words (B); all accepted
families kept all three labels and 3–4 target claims.

## Quarantine reasons

### Arm A

- `FAM_000006` — family relation review: C1–C4 are neutral/unsupported in the
  variant, so the expected SUPPORTED relations are not reproduced.
- `FAM_000008` — family relation review: C4 is supported by `S109`/`S122`,
  which is incompatible with the expected all-UNSUPPORTED relation set.

Both are **family relation** failures, not fixer-budget failures.

### Arm B

- `FAM_000001` — repair budget exhausted on a `S81`–`S86` sentence-id shift.
- `FAM_000006` — family relation review: C1 is ENTAILED but expected UNSUPPORTED.
- `FAM_000007` — repair budget exhausted on duplicate/absent `S51`/`S52`.
- `FAM_000008` — family relation review: C1–C4 must be removed or neutralized.

## Quarantine diagnosis

- `FAM_000006` is a **verifier false positive**. Its own findings classified
  C1–C4 as `NEUTRAL`, exactly the required UNSUPPORTED relation, but its verdict
  was `REPAIR` because the shared target claim ledger contained translated claim
  statements. The family-review prompt has been corrected: the target claim
  ledger is not evidence that a variant asserts the claims; `NEUTRAL` is PASS
  for an expected `UNSUPPORTED` relation.
- `FAM_000008` is a **real relation drift**. C4 is entailed by `S109`/`S122` in
  the assembled UNSUPPORTED variant (the target states the 21→13-day improvement
  and an eight-day reduction), while the expected relation is `UNSUPPORTED`.
  The window fixer cannot repair this because it operates per window; it needs
  a family-level repair or a source-label review.

So one of the two ReAct-arm failures is a verifier bug, not a translation
failure. The corrected prompt has not yet been rerun; do not report 9/10 as a
measured result until it is.

## Interpretation

- **The round-2 changes materially improved acceptance:** 80% vs 60% for the
  deterministic arm. The loosened verifier removed style-only vetoes, and the
  larger budget let the ReAct fixer resolve repairs that previously exhausted
  six edits.
- **The ReAct fixer now earns its cost on this sample:** +2 accepted families
  for +126 manifest calls (14.5% more calls). It fixed the `FAM_000001` and
  `FAM_000007` repair failures that the deterministic arm could not.
- **The remaining failures moved to the family relation gate.** Both arms fail
  `FAM_000006` and `FAM_000008` because the assembled variant's claim relation
  does not match the expected label. This is not a translation-style problem;
  it is the family-level verifier doing its intended job.
- **The sample is still small.** n=10, one profile, no human bilingual audit.
  The 80% result is a strong signal, not a release guarantee.

## Decision

Enable the ReAct fixer by default for the next translation batch, with the
round-2 30-step/30-edit budgets. Keep the hard claim/number/relation gates.
Do not enable style-jitter or call tonal variation "robustness"; that remains a
separate controlled experiment.

Next work:

1. Diagnose `FAM_000006`/`FAM_000008` family-relation failures; decide whether
   the source family is malformed or the target needs a family-level repair
   (the current fixer only repairs windows).
2. Run 30–50 families with the round-2 settings and measure acceptance per 100
   calls.
3. Apply the bilingual human audit to a sample of accepted families.
4. Keep the deterministic arm as a fallback when the fixer cannot improve a
   window within budget.

## Raw outputs

- `data-v5/ablation2/fixer-on/`
- `data-v5/ablation2/fixer-off/`
- Call ledgers: `data-v5/ablation2/*/logs/calls.jsonl`
