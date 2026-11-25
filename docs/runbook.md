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

# large resumable batch (200 base documents = 600 variants), concurrency 10
env -u PYTHONPATH .venv/Scripts/python.exe scripts/generate_dataset.py \
  --data-dir data-v5 --target-families 200 --concurrency 10 --budget-usd 25
```

`generate_dataset.py` seeds/expands the topic graph, runs batches until the accepted-family
target is met, and checkpoints `batch_manifest.json` after every round. Re-running the same
command resumes; completed candidates are skipped. If the provider or host dies, run it again.

Interrupting a run is safe: press Ctrl-C, or kill the process. State is in SQLite plus atomic
artefacts; `resume` continues from the last successful stage.

Cost/latency (2k–4k documents, concurrency 10): roughly 50 provider calls and $0.05 per accepted
family; a 2-family pilot took ~20 minutes wall-clock when only two families were in flight.
Budget 200 families at several hours and roughly $10–20 including repairs. Budgets:
`execution.max_total_cost_usd`, `execution.max_calls_per_family` (default 80; long documents
need more calls).

### 3.1 Document length and claim count

Both are configuration, not prompt edits:

```yaml
passage:
  target_tokens_min: 2000     # whole-document target (model tokens)
  target_tokens_max: 4000
  sections_min: 3
  sections_max: 8
  section_tokens_min: 450
  section_tokens_max: 900
  max_sections: 24            # raise for 10k-15k targets if the derived count exceeds it
claims:
  target_claims_per_document: 4
  min_claims_per_family: 2
  max_claims_per_family: 12
```

The section count is derived from the mean target divided by the mean section size, so a
10k–15k document becomes ~15–22 sections with no other change. Prompt versions change when the
prompt text changes, not when these numbers change: `blueprint`/`passage` receive the numbers as
render variables, so editing config does not invalidate unrelated artefacts.

Cost scales roughly with document length: a 2k–4k document is ~1 section call per 675 tokens plus
one extraction call per 1.5k tokens, three variant edits, three validations and three advisory
re-extractions. Expect materially more than the short pilot per family; set
`execution.max_total_cost_usd` deliberately.

Long documents are edited from an **editing view** (claim evidence sentences ±
`variants.edit_view_sentences`, capped by `edit_view_max_sentences`); patches still target global
sentence IDs in the full document. This keeps the editor prompt bounded without changing the
patch contract.

### 3.2 Style axes and in-context priming

`blueprint.tones` (7 register labels) and `blueprint.narratives` (6 modes) are sampled once per
family and shared by all three variants. `prompts/style_shots.yaml` holds one directive and one
short exemplar per label, plus composed exemplars for conflict pairs. Section and short-passage
prompts receive the rendered priming block; the blueprint receives directives only.

Adding a new label requires **both** a config entry and a matching YAML block
(`tones.<label>` or `narratives.<label>` with `directive` and `example`). Missing entries fall
back to a generic directive and no exemplar — the run still works, but the label is weakly
specified. `tests/test_style.py` enforces coverage of every configured label.

Styles are not deterministically verified. To inspect balance after a run:

```bash
env -u PYTHONPATH .venv/Scripts/python.exe - <<'PY'
import json, glob
from collections import Counter
rows=[json.load(open(f))["base_passage"] for f in glob.glob("data-v5/families/FAM_*.json")]
print("tones", Counter(r["tone"] for r in rows))
print("narratives", Counter(r["narrative"] for r in rows))
print("genres", Counter(r["genre"] for r in rows))
PY
```

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
| `document_quality` / `section_quality` | assembled document or one section missed the length/quality band | inspect `data/quarantine/<cand>.json` `payload.problems`; the model usually wrote too little — raise `section_tokens_*` or lower `target_tokens_*`, do not weaken screening blindly |
| `document_plan_invalid` | plan section count outside the derived band | check `passage.sections_min/max_sections` against the target length |
| `claims_insufficient` | too few claims survived deterministic filtering | inspect `payload`; the document may not state enough checkable facts (raise `blueprint.target_fact_count` indirectly via a longer target) |
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

## 7.1 Translation branch

Translation is a separate product with its own config and output tree. It reads
only `data-v5/families/FAM_*.json` whose quality is `ACCEPTED`.

```bash
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate translate preflight
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate translate run \
  --profile bn_in_native --limit 1 --concurrency 1 --run-id translate-pilot
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate translate status
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate translate export \
  --profile bn_in_native --version v1-100
```

By default the branch uses the same `LLM_API_KEY` as English generation; a
separate `base_url`/`api_key_env` can be configured. There is no silent
fallback. The four profiles (`bn_in_native`, `bn_bd_native`, `bn_romanized`,
`banglish_code_mixed`) are independent products. See `docs/translation.md` for
the stage contract and quarantine rules.

`configs/multilingual.yaml` enables the ReAct fixer by default after the
round-2 ablation: ReAct accepted 8/10 vs deterministic 6/10 on the same sample.
The configuration uses `fixer.max_steps: 30`, `fixer.max_edits_per_step: 30`
and `fixer.max_total_edits: 30`; `window.max_repairs` is also 30. Set
`fixer.enabled: false` to use the deterministic sentence-targeted repair path.
Either path requires an independent `PASS` before acceptance.

---

## 8. Tests

```bash
env -u PYTHONPATH .venv/Scripts/python.exe -m pytest -q
```

145 tests, no network, ~15 seconds. The mock pipeline tests exercise the full stage graph,
resume, idempotency, index-update ordering, splits, quarantine, export and reports; the long-form
tests cover window splitting, section assembly offsets, document screening and claim spreading; the
translation tests cover preflight, claim cards, window/paragraph coverage, script gates, a mock
end-to-end family and relation-drift quarantine.
