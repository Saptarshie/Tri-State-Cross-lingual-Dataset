# Runbook

Operational notes for running the factory on the current Windows host. Everything here was
exercised during the pilot.

---

## 1. Environment

```bash
cd <repo>
uv venv --python 3.13 .venv
env -u PYTHONPATH uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
```

**Host quirk:** this shell exports a foreign `PYTHONPATH` pointing at the Hermes venv, which
shadows the project's packages (`ModuleNotFoundError: tristate`, or a `pydantic_core` mismatch).
Either unset it per command:

```bash
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate config-check
```

or clear it once in the shell (`unset PYTHONPATH`) before activating the venv.

Secrets live in `.env` (git-ignored):

```
LLM_BASE_URL=https://api.commandcode.ai/provider/v1
LLM_API_KEY=...
LLM_MODEL=deepseek/deepseek-v4.1-flash
LLM_MAX_TOKENS=64000
OLLAMA_BASE_URL=http://127.0.0.1:11434
EMBED_MODEL=embeddinggemma
```

`load_config()` reads `.env` only for variables not already present in the environment, and
never logs or serialises the key.

---

## 2. Pre-flight

```bash
.venv/Scripts/python.exe -m tristate config-check            # network probes
.venv/Scripts/python.exe -m tristate config-check --no-network
```

Checks config hash, prompt versions, API `/models`, generator presence, and the embedder
(dimension + availability). Exit code 1 means no key or failed probe.

Ollama must be running for the default embedder:

```bash
"$LOCALAPPDATA/Programs/Ollama/ollama.exe" serve     # background
"$LOCALAPPDATA/Programs/Ollama/ollama.exe" list      # embeddinggemma:latest
```

If Ollama is down the embedder degrades to hashing at the same dimension. Do **not** switch
back and forth against an existing index: `index/embedder.json` mismatch is refused with a
clear error; rebuild with `index build` after choosing one.

---

## 3. Running

```bash
# offline smoke test (templated mock workers, relaxed duplicate thresholds)
.venv/Scripts/python.exe -m tristate run --limit 2 --data-dir data/mock --mock

# real generation, bounded topics
.venv/Scripts/python.exe -m tristate run --limit 5 --topic Technology
.venv/Scripts/python.exe -m tristate run --limit 12            # coverage-selected topics

# stage-by-stage
.venv/Scripts/python.exe -m tristate run --limit 5 --stop-after blueprint
.venv/Scripts/python.exe -m tristate stage variant --limit 5
.venv/Scripts/python.exe -m tristate resume --limit 50
```

Interrupting a run is safe: press Ctrl-C, or kill the process. State is in SQLite plus atomic
artefacts; `resume` continues from the last successful stage.

Cost/latency (pilot, concurrency 3): ~14 provider calls and ~$0.008 per accepted family,
roughly 1–2 minutes per family wall-clock. Budgets: `execution.max_total_cost_usd`,
`execution.max_calls_per_family`.

---

## 4. Inspecting results

```bash
.venv/Scripts/python.exe -m tristate families list
.venv/Scripts/python.exe -m tristate families show FAM_000001
.venv/Scripts/python.exe -m tristate quarantine list
.venv/Scripts/python.exe -m tristate report md
.venv/Scripts/python.exe -m tristate splits report
.venv/Scripts/python.exe -m tristate export --version pilot-01
```

Raw provider calls for a run: `data/raw/<run_id>/<stage>/*.json` (request, response, usage,
latency; no credentials). Call ledger: `sqlite3 data/state/state.db 'select stage,status,count(*)
from calls group by 1,2'`.

---

## 5. Failure recovery

| Symptom | Diagnosis | Action |
|---|---|---|
| All candidates `llm_permanent` | key revoked / route changed / UA blocked | `config-check`; check `data/raw/...` status codes |
| Extraction quarantined, content empty | reasoning model consumed the token budget | raise `LLM_MAX_TOKENS` (64k in `.env`) or change stage model |
| `index/embedder mismatch` | different embedding model than the index | pick one embedder; `index build` to rebuild |
| Candidate stuck `RUNNING` | process died mid-stage | `resume` — the job restarts and overwrites its artefact |
| Family rejected `family_rejected` | validator or hard check failed | inspect `data/quarantine/<cand>.json` `payload.validations` and `workdir/hard_checks.json` |
| `near_duplicate_variants` | template overlap with an accepted family | regenerate with a different topic/intent; adjust `hnsw.near_duplicate_*` only with calibration |
| Split skew (all train) | small N hash assignment | expected; do not hand-edit `splits.json` |
| Export writes no rows | no ACCEPTED families | `families list --status ACCEPTED` |
| `ModuleNotFoundError: tristate` | foreign `PYTHONPATH` | `env -u PYTHONPATH …` |

Re-running a quarantined candidate:

```bash
.venv/Scripts/python.exe -m tristate resume --limit 50 --retry-quarantined
```

It will only re-execute failed stages; stages that succeeded keep their artefacts. If you
changed a prompt, that stage re-runs, but later artefacts are not automatically invalidated —
for a clean regeneration, remove the candidate workdir or use a new data directory.

---

## 6. Provider pitfalls (observed)

1. **403 without a browser-like User-Agent.** Python's default and curl's default agents were
   rejected by Cloudflare; `llm.user_agent` is set on every request.
2. **Reasoning tokens.** `deepseek/deepseek-v4.1-flash`, `xiaomi/mimo-v2.6-flash` and
   `google/gemini-3.8-flash` emit hidden reasoning. A 2000-token ceiling produced
   `finish_reason: length` with empty `content`. The project sets 64k via `.env`; observed calls
   stop far below it.
3. **No embeddings endpoint** in the catalogue: embeddings come from local Ollama.
4. **`response_format`**: `json_object` is accepted by all three models used; the client still
   parses defensively and repairs once on schema failure.

---

## 7. Data hygiene

- Never edit `data/families/*.json` in place: accepted records are immutable and export
  re-validates them.
- Never copy `data/index` between machines without also copying `index/embedder.json` and the
  matching embedding model; otherwise rebuild.
- `data/llm_cache` is content-addressed and safe to delete (costs re-calls).
- Quarantine files are diagnostics; they are not part of the dataset and are never exported.
- Treat everything under `data/` as potentially licence-encumbered if external documents were
  ingested; keep it out of public repositories (`.gitignore` already excludes `data/`).

---

## 8. Tests

```bash
env -u PYTHONPATH .venv/Scripts/python.exe -m pytest -q
```

120 tests, no network, ~10 seconds. The mock pipeline tests exercise the full stage graph,
resume, idempotency, index-update ordering, splits, quarantine, export and reports.
