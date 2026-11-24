# Tri-State Counterfactual Dataset Factory

Corpus-first, graph-guided generation of **passage families** for training models that must
judge whether a fixed claim set is supported by a supplied context — rather than by what the
model already believes.

One family is one indivisible instance:

| Variant | Requirement |
|---|---|
| `SUPPORTED` | the passage establishes **every** claim |
| `CONTRADICTED` | the passage explicitly contradicts **every** claim |
| `UNSUPPORTED` | the passage neither establishes nor contradicts **any** claim |

All three variants share one claim set, one family ID, one lineage group and one split.
Passages may be synthetic or counterfactual: real-world truth is explicitly **not** a gate.

## Status

- Milestone 0–3 vertical slice implemented and exercised end to end.
- `pytest`: 120 tests passing (unit, semantic-contract, editor, novelty, corpus, audit, end-to-end with mocked workers).
- Real-provider pilot: families generated, validated and exported (see `docs/state.md`).
- Planned next: corpus expansion, richer editing patterns, larger scale-out
  (see `docs/state.md`).

## Quick start

```bash
# 1. environment (Python 3.11+; on this host a local venv)
uv venv --python 3.13 .venv
env -u PYTHONPATH uv pip install --python .venv/Scripts/python.exe -e ".[dev]"

# 2. configuration: copy .env.example -> .env and set LLM_API_KEY
#    stage models and every threshold live in configs/default.yaml

# 3. inspect providers, prompts, config
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate config-check

# 4. offline end-to-end smoke test (no network, templated mock workers)
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate run --limit 2 --data-dir data/mock --mock

# 5. real generation
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate run --limit 10

# 6. reports, index snapshot, export
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate report md
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate index build
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate export
```

> `env -u PYTHONPATH` is only needed on hosts whose shell exports a foreign `PYTHONPATH`
> (this Windows/Hermes host does). In a normal activated venv, drop it.

## Commands

| Command | Purpose |
|---|---|
| `config-check` | config hash, prompt versions, API + embedder probe (no secrets printed) |
| `topics seed/expand/select/report` | topic graph and coverage-aware sampling |
| `corpus ingest --path …` | local seed documents → segmented passage candidates |
| `run --limit N [--topic X] [--expand] [--stop-after STAGE]` | generate families end to end |
| `resume --limit N` | resume PENDING/FAILED candidates (idempotent) |
| `stage {blueprint,passage,extract,claims,variants,validate}` | run one stage over candidates |
| `index build/update/stats` | rebuild HNSW indexes from accepted families |
| `report {json,md} [--shortcut-audit]` | quality, diversity, cost, shortcut diagnostics |
| `splits report` | family-level split assignments |
| `export [--split] [--version]` | versioned JSONL export + manifest |
| `families list/show` | inspect accepted records |
| `quarantine list` | inspect rejected candidates and reasons |

## Data layout

```
data/
  state/state.db              # jobs, candidates, families, LLM call ledger, counters
  work/<candidate_id>/        # one JSON artefact per stage (crash-resumable)
  raw/<run_id>/<stage>/       # every raw provider request/response, pre-parse
  llm_cache/<stage>/          # content-addressed responses (free re-runs)
  families/FAM_000001.json    # canonical family records (immutable once accepted)
  quarantine/<candidate>.json # rejected candidates + reasons + workdir pointer
  index/{blueprint,passage,fact_claim,edit_signature}/  # HNSW snapshots + metadata
  embeddings/<model>/         # Ollama embedding cache (content-addressed)
  splits/assignments.json     # family → split/group, stable and locked
  reports/quality.{json,md}   # dataset metrics
  exports/<version>/          # families.jsonl, variants.jsonl, claims.jsonl, manifest
  topics/graph.json           # topic graph + coverage counters
  corpus/                     # ingested documents and passage candidates
```

## Documentation

- `docs/objective.md` — authoritative task specification (unchanged).
- `docs/design.md` — architecture, contracts, schema, algorithms, decisions, trade-offs.
- `docs/state.md` — what is implemented, verified numbers, known issues, next steps.
- `docs/devlog.md` — chronological build log, bugs found and fixed.
- `docs/runbook.md` — operations, failure recovery, environment pitfalls.
- `docs/chat_log.md` — original research discussion (context, not a spec).

## Non-negotiables encoded in code

1. Labels are context-relative; there is no world-truth gate (`validation.allow_world_truth_gate: false`).
2. One family is one data instance; claim IDs are identical across all three variants.
3. All-or-nothing family contract; mixed families are quarantined, never relabelled.
4. Editing is patch-based and deterministic; the editor cannot certify its own output.
5. Validation uses an independent model family from the editor, with the intended label hidden.
6. Only accepted families enter the novelty index; test-split records never steer training generation.
7. Splits are assigned per family lineage, never per variant.
8. Every stage is resumable and every accepted family is idempotent by construction.
