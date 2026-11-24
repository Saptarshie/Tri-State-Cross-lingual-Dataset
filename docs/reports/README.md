# Pilot reports

Generated snapshots, kept for audit. They are not inputs to the pipeline.

| File | What it is |
|---|---|
| `pilot-01-report.md` | quality report for 14 families, before the split-skew and audit fixes |
| `pilot-01-audit.json` | **superseded** shortcut audit: 0.615 accuracy. It leaked recipe metadata, edit counts and `is_pure_patch`, and split by variant rather than family. Do not cite. |
| `pilot-02-report.md` | quality report for the current dataset (15 families / 45 variants / 54 claims) |
| `pilot-02-audit.json` | current surface-only audit: 0.467 accuracy, 95% CI 0.27–0.73, chance 0.333, not flagged |

Regenerate:

```bash
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate report md  --data-dir data
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate report json --shortcut-audit --data-dir data
```

The shortcut audit is a diagnostic of surface-form leakage, not an evaluation of model accuracy.
Its split is internal (family-wise 70/30); it is unrelated to the dataset's train/dev/test split.
