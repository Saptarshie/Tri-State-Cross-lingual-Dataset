# Translation ablation: ReAct fixer vs deterministic repair

Status: **running**. Update this file when each arm finishes; do not report a
winner before both arms use the same source sample, profile, model and review
policy.

## Question

Does the bounded ReAct quality fixer improve accepted-family rate and
cross-sentence repair quality enough to justify its extra calls, compared with
the older deterministic sentence-targeted repair path?

## Design

- Source: first 10 accepted families in `data-v5/families/` (sorted by family id).
- Profile: `bn_in_native` only.
- Model/reviewer: `deepseek/deepseek-v4.1-flash`, same prompt versions.
- Both arms use `--limit 10 --concurrency 4`, independent output directories, and
  no prior accepted records.
- Arm A (`fixer-on`): `configs/multilingual-ablation-on.yaml`, `fixer.enabled: true`.
- Arm B (`fixer-off`): `configs/multilingual-ablation-off.yaml`,
  `fixer.enabled: false`; falls back to the deterministic
  `affected_sentence_ids` repair path.
- The only intended difference is the repair mechanism.

## Commands

```bash
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate translate run \
  --profile bn_in_native --limit 10 --concurrency 4 \
  --translation-config configs/multilingual-ablation-on.yaml \
  --output-dir data-v5/ablation/fixer-on --run-id ablation-fixer-on

env -u PYTHONPATH .venv/Scripts/python.exe -m tristate translate run \
  --profile bn_in_native --limit 10 --concurrency 4 \
  --translation-config configs/multilingual-ablation-off.yaml \
  --output-dir data-v5/ablation/fixer-off --run-id ablation-fixer-off
```

## Metrics

Per arm:

- accepted / quarantined / pending families;
- provider calls and cost;
- fixer action count and rejected edits (on arm);
- quarantine reasons grouped by stage and finding type;
- sentence-id alignment failures and relation drift;
- target word counts per label;
- a small manual spot-check of repaired windows (not a substitute for the
  bilingual audit).

Primary comparison: accepted families per 100 calls, then quarantine reason
distribution. A higher acceptance rate with worse relation or alignment quality
is not a win.

## Results

Completed 2026-11-25. Full report:
`docs/reports/ablation-fixer-2026-11-25.md`.

| Metric | Fixer on | Fixer off |
|---|---:|---:|
| Accepted | 1 / 10 | 2 / 10 |
| Quarantined | 9 | 8 |
| Manifest calls | 807 | 724 |
| Logged OK calls | 754 | 658 |
| Fixer actions | 247 | 0 |
| Prompt tokens | 3,224,663 | 2,509,283 |

The deterministic arm accepted more families with fewer calls. The fixer
diagnosed several repairs correctly but exhausted its six-sentence edit budget
on broad alignment shifts. This is not a statistically meaningful result at
n=10, and one family per arm hit a provider 429. Raw outputs stay under
`data-v5/ablation/` (ignored by git).

## Round 2: loosened verifier + 30-step/30-edit budgets

Running 2026-11-25. The window verifier now separates blocking defects from
advisory style findings (see `prompts/multilingual_window_review.md`):
sentence-boundary differences, first-mention glosses, register, punctuation and
conventional Latin technical terms are advisory unless they change meaning,
coverage, numbers, modality or script. The repair budgets are now 30 steps,
30 edits per step and 30 total edits; `window.max_repairs` is 30.

- Arm A: `configs/multilingual-ablation2-on.yaml`, `data-v5/ablation2/fixer-on`.
- Arm B: `configs/multilingual-ablation2-off.yaml`, `data-v5/ablation2/fixer-off`.

Round-1 results remain the baseline; do not pool the two rounds.

### Round-2 result

| Metric | Fixer on | Fixer off |
|---|---:|---:|
| Accepted | **8 / 10** | **6 / 10** |
| Quarantined | 2 | 4 |
| Manifest calls | 995 | 869 |
| Logged calls | 948 | 949 |
| Fixer actions | 100 | 0 |
| Prompt tokens | 4,217,874 | 3,898,541 |

The loosened verifier and 30-step/30-edit budgets materially improved both
arms. The ReAct fixer now wins on accepted families (8 vs 6) and resolves
repairs that the deterministic arm cannot. The remaining failures are family
relation failures in `FAM_000006` and `FAM_000008`, not repair-budget failures.
Full report: `docs/reports/ablation-fixer-round2-2026-11-25.md`.
