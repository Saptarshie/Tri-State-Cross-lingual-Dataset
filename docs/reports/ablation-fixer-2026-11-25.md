# Ablation report: ReAct fixer vs deterministic surgical repair

Date: 2026-11-25
Profile: `bn_in_native`
Source: first 10 accepted English families (`FAM_000001`–`FAM_000010`)
Model/reviewer: `deepseek/deepseek-v4.1-flash`
Concurrency: 4 families
Status: both arms completed; **no statistically meaningful winner** at n=10.

## What was compared

Both arms used the same source, claim ledger, glossary, target claims, reviewer,
prompts and output contract. The only intended difference was what happens after
a window review returns `REPAIR`.

- **Arm A (`fixer-on`)**: bounded ReAct fixer with `read_*`,
  `apply_sentence_edits`, `run_review`, `rollback`, `finish`, `abort`.
  Budgets: 8 steps, 2 edits per step, 6 total sentence edits.
- **Arm B (`fixer-off`)**: deterministic surgical repair. The pipeline reads the
  reviewer's `affected_sentence_ids`, retranslates only those source sentences,
  merges them into the prior target and preserves every other sentence verbatim.

Arm B is a real repair baseline, not a no-repair control.

## Headline results

| Metric | Arm A: ReAct fixer | Arm B: deterministic repair |
|---|---:|---:|
| Accepted families | **1 / 10 (10%)** | **2 / 10 (20%)** |
| Quarantined families | 9 | 8 |
| Accepted family ids | FAM_000003 | FAM_000003, FAM_000004 |
| Manifest calls | 807 | 724 |
| Logged OK calls | 754 | 658 |
| Window translation calls | 192 | 312 |
| Window review calls | 291 | 324 |
| Fixer actions | 247 | 0 |
| Prompt tokens | 3,224,663 | 2,509,283 |
| Completion tokens | 3,011,793 | 3,056,850 |
| Median call latency | 23.3 s | 28.5 s |
| Max call latency | 153.1 s | 168.4 s |
| Cost | $0.00 (placeholder pricing) | $0.00 (placeholder pricing) |

Accepted families per 100 manifest calls: **0.124** (A) vs **0.276** (B).

## Quarantine reasons

### Arm A — fixer on

- `FAM_000001`: fixer total sentence-edit budget exhausted (6/6) on `S80`.
- `FAM_000002`: claim translation review failed; missing `1,400`.
- `FAM_000004`: fixer budget exhausted after `S89`/`S96`; `S99`/`S100` still
  contain standalone Latin `DOC`.
- `FAM_000005`: fixer says one-to-one alignment needs `S15`–`S28` (14 sentences),
  above the 6-edit cap.
- `FAM_000006`: gloss fixes required in `S100`, `S101`, `S104`; only one edit
  remained.
- `FAM_000007`: alignment shift after `S60` would require editing `S60`–`S73`
  (14 sentences), above the cap.
- `FAM_000008`: HTTP 429 five-hour usage limit.
- `FAM_000009`: claim translation review failed; missing `38`, `6`.
- `FAM_000010`: fixer budget exhausted on `S5`.

### Arm B — fixer off

- `FAM_000001`: repair budget exhausted on a conditional-force repair in `S98`.
- `FAM_000002`: claim translation review failed; missing `1,400`.
- `FAM_000005`: repair budget exhausted on `S36` wording.
- `FAM_000006`: repair budget exhausted on term glosses in `S90`, `S91`, `S104`,
  `S105`.
- `FAM_000007`: repair budget exhausted on `S35` either/or construction.
- `FAM_000008`: repair budget exhausted; missing numbers `0.81`, `1.42`.
- `FAM_000009`: claim translation review failed; missing `38`, `6`.
- `FAM_000010`: HTTP 429 five-hour usage limit.

## Interpretation

1. **The deterministic arm won this sample.** It accepted two families instead
   of one, used fewer calls, and used fewer prompt tokens.
2. **The ReAct fixer over-ran its edit budget.** In six quarantines it correctly
   diagnosed the problem, but the repair required more sentence edits than the
   six-edit cap. Broad alignment shifts (`S15`–`S28`, `S60`–`S73`) cannot be
   fixed by a small agent patch under the current budget.
3. **Claim-translation failures are upstream and identical.** `FAM_000002` and
   `FAM_000009` failed before the window repair policy mattered, so they do not
   distinguish the arms.
4. **One family per arm hit the provider's 429 limit.** That is an environmental
   failure, not a repair-policy result. A targeted retry was launched for
   `FAM_000008` (Arm A) and `FAM_000010` (Arm B), but these headline numbers are
   from the completed 10-family runs and must be read with that caveat.
5. **The sample is too small and the accepted outputs are not human-audited.**
   Do not claim the ReAct fixer improves quality from this run.

## Decision

Keep the **deterministic surgical repair as the default** for now. The ReAct
fixer is implemented and auditable, but it is not yet earning its extra calls.

Before enabling it by default:

- Add a pre-check: if the reviewer-named repair scope exceeds
  `fixer.max_total_edits`, do not start the agent; use deterministic subset
  retranslation or quarantine with a `repair_scope_too_large` reason.
- Give the fixer a fallback to deterministic retranslation when its edit budget
  is exhausted, instead of spending all steps on an impossible broad repair.
- Re-run this ablation at a larger sample (at least 30–50 families) after those
  changes, and compare accepted families per 100 calls plus human spot-checks.
- Keep style-jitter as a separate augmentation experiment; do not count it as
  robustness without a fixed-vs-jittered evaluation.

## Raw outputs

- `data-v5/ablation/fixer-on/`
- `data-v5/ablation/fixer-off/`
- Call ledgers: `data-v5/ablation/*/logs/calls.jsonl`
