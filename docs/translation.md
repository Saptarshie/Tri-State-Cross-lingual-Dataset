# Multilingual translation branch

The English factory produces the immutable source families. This branch
translates **whole families**, not isolated passages, into Bengali varieties and
Banglish. It is intentionally separate from generation: a translation failure
must never edit, relabel, or delete an English record.

## 1. Scope and non-goals

Implemented:

- four target profiles (`bn_in_native`, `bn_bd_native`, `bn_romanized`,
  `banglish_code_mixed`);
- deterministic source preflight and checksum;
- claim semantic cards, family glossary, one shared target claim set;
- sentence-aligned translation windows with previous/next context;
- independent window review and family-level claim-relation review;
- bounded ReAct quality fixer with sentence-level edit tools, quarantine with
  reasons, atomic per-family outputs;
- profile-scoped manifests and a versioned JSONL export.

Not yet implemented:

- human adjudication of quarantine;
- a separate surface-realization pass for romanized/Banglish; those profiles
  currently receive surface instructions in the same semantic-translation call;
- provider-specific thinking-mode request fields. `thinking_mode` /
  `review_thinking_mode` are policy flags, while the exact current DeepSeek
  parameter must be supplied in `extra_body_generate` / `extra_body_review`;
  we do not guess an API field name;
- per-profile cost pricing (translation calls are recorded, but the configured
  DeepSeek prices are placeholders until the operator supplies them);
- native-speaker quality certification.

## 2. Immutable source contract

Input is `data-v5/families/FAM_*.json` with `quality.status == "ACCEPTED"`.
Before any paid call, `ledger.preflight()` requires:

- exactly the three labels (`SUPPORTED`, `CONTRADICTED`, `UNSUPPORTED`);
- a non-empty claim set with unique ids;
- per-variant relation coverage when relations are present;
- `PASS` source validation when a validation block exists;
- a valid split (`train`, `dev`, `test`, `validation`).

`source_checksum()` covers the base passage, claim set and all three variant
texts/checksums. The checksum is copied into every target record. The source
directory is never written by this branch.

## 3. Profiles

Profiles are explicit records in `configs/multilingual.yaml`, versioned with the
output. A profile fixes:

- language and locale;
- native / romanized / mixed script policy;
- syntax and register;
- regional style;
- romanization and English-term policy;
- code-switching permission and intensity.

The four initial profiles are West Bengal Bengali, Bangladesh Bengali,
romanized Bengali, and Banglish code-mixed Bengali. They are separate products:
do not pool them as one "Bengali" split without a profile column.

## 4. Pipeline

```
source family
  └─ preflight + source checksum
      └─ deterministic claim cards
          └─ profile glossary (DeepSeek)
              └─ target claim set (DeepSeek, one shared set per family)
                  └─ target claim review (independent call)
                      └─ for each variant:
                           sentence windows (250–500 words, no overlap)
                             └─ semantic translation
                                 └─ window fidelity review
                                     └─ bounded repair (max 2)
                           assemble with source paragraph boundaries
                             └─ family claim-relation review
                                 └─ accept or quarantine
```

### 4.1 Claim cards

Cards are deterministic. They preserve the source claim's entities, numbers,
dates, negation, modality, polarity and scope. Facts are used only when their
subject/object actually occurs in the claim; a section-level fact that was
reused across claims must not silently become the claim's triple.

`relation_obligation` is `SUPPORTED` for the canonical target claim. The
three-way obligation is enforced per variant by the family review, not by
changing the claim text three times.

### 4.2 Target claims

One target claim set is created per family/profile and shared by all three
variants. This is the key alignment control: the labels differ in evidence and
stance, not in what the claim means. A claim translation is retried once with
review feedback; if it still fails, the family is quarantined.

### 4.3 Windows

Each source variant is segmented into sentence windows of roughly 250–500
words, with two sentences of previous/next context. Every source sentence must
appear exactly once and no sentence may be duplicated. Windows preserve source
paragraph ids; assembly restores `\n\n` boundaries.

The translation call returns one target sentence per source sentence id. A
window review separates **blocking** defects from **advisory** style findings.
Blocking: missing/changed entity, number, date, unit or quantifier; negation,
modality, certainty, polarity or scope change; causal/logical change; an absent
claim becoming present or a present claim absent; untranslated/empty content;
added facts; script-policy violation. Advisory (reported but not a `REPAIR`):
first-mention gloss/terminology preference, register/tone/punctuation, a
conventional Latin technical term, minor word order, and source/target sentence
boundary differences when every source sentence is represented and no content
is lost.

A blocking `REPAIR` goes to the deterministic surgical repair path by default:
the reviewer's affected sentence ids are retranslated, merged into the prior
target, and every other sentence is preserved. The optional bounded ReAct
quality fixer (`fixer.enabled: true`) can inspect the current window, ledger,
glossary and adjacent context, then apply sentence-level edits through
`apply_sentence_edits`; it cannot insert, delete, merge or reorder sentence ids.
It must call `run_review` after editing and can finish only on `PASS`. Its loop
is capped by `fixer.max_steps` (30), `fixer.max_edits_per_step` (30) and
`fixer.max_total_edits` (30) in the current ablation configuration; the prompt
includes the recent action trace and the edit budgets. The 10-family ablation
(`docs/reports/ablation-fixer-2026-11-25.md`) found the deterministic path
accepted 2/10 versus 1/10 for the fixer; after loosening the verifier and
raising budgets to 30, the round-2 result reversed to **ReAct 8/10 vs
deterministic 6/10**, so the fixer is enabled by default. The remaining
quarantines in round 2 were family-relation failures, not repair budgets.
See `docs/reports/ablation-fixer-round2-2026-11-25.md`.

### 4.4 Family review

For each variant, an independent call receives the English source variant, the
target claim set, the claim cards and the assembled target sentences. It returns
one relation per claim. The expected relation is copied from the English
variant's per-claim relations (falling back to the variant label). The target
must reproduce the expected vector exactly:

| English label | Required observed relation |
|---|---|
| SUPPORTED | ENTAILED |
| CONTRADICTED | CONTRADICTED |
| UNSUPPORTED | NEUTRAL |

The target claim set is a shared translation of the claim ledger; its presence
does not mean the variant asserts every claim. For an `UNSUPPORTED` variant,
`NEUTRAL` is a pass even when the target claim ledger contains the claim text.
Any missing finding, relation drift, or `QUARANTINE` quarantines the family; a
`REPAIR` must name an actual target relation mismatch or evidence loss. The
branch never changes an English label to make a translation pass.

### 4.5 Script gate

A deterministic gate rejects a target that violates its profile:

- native profiles require at least 20% Bengali letters;
- romanized profiles reject any Bengali-script character;
- mixed profiles may contain both.

This is a guard against a silent fallback to English or to the wrong script. It
is not a native-speaker quality judgement.

## 5. Storage

```
data-v5/multilingual/<profile_id>/
  manifest.json
  families/FAM_000001.json     # accepted FamilyTranslation records
  quarantine/FAM_000001.json   # rejected records + reasons
  exports/<version>/translations.jsonl
  exports/<version>/manifest.json
  raw/...                      # raw provider responses (existing client)
  logs/calls.jsonl
```

Every record is written to a temporary file and atomically replaced. Re-running
`run` skips accepted families and, unless `--retry-quarantined` is passed,
leaves quarantined ones alone. A crash therefore loses at most the in-flight
family.

## 6. Commands

All commands use the project venv and clear the host's foreign `PYTHONPATH`:

```bash
cd D:/hermes_workspace/Workspaces/papers-small-lm/EthicalAI/TristateDataset/v0

# inspect profiles without a provider call
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate translate profiles

# check source/product readiness; exits 2 when the configured key is missing
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate translate preflight

# one profile, first family only
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate translate run \
  --profile bn_in_native --limit 1 --concurrency 1 --run-id translate-pilot

# resume / scale a profile
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate translate run \
  --profile bn_in_native --concurrency 4 --run-id translate-v1

# all four profiles (operator loop; profiles are separate products)
for p in bn_in_native bn_bd_native bn_romanized banglish_code_mixed; do
  env -u PYTHONPATH .venv/Scripts/python.exe -m tristate translate run \
    --profile "$p" --concurrency 4 --run-id "translate-$p"
done

# status and export
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate translate status
env -u PYTHONPATH .venv/Scripts/python.exe -m tristate translate export \
  --profile bn_in_native --version v1-100
```

The translation credential is read from the configured `deepseek.api_key_env`;
the default is `LLM_API_KEY`, i.e. the same credential as the English factory,
with the model still DeepSeek. Set a separate `base_url`/`api_key_env` only if
an isolated translation credential is provisioned. The key is never written to
config, logs, records or git. There is no silent fallback: if it is absent, the
command fails clearly.

## 7. Tests and current verification

`tests/test_multilingual.py` covers:

- deterministic source preflight and claim cards;
- exact, non-overlapping window coverage;
- paragraph-boundary preservation;
- profile script gates;
- end-to-end mock translation of three aligned variants;
- ReAct fixer action/edit/acceptance flow;
- surgical repair that resends only the affected sentence id;
- concurrent processing of two families through `run_profile`;
- relation-drift quarantine;
- non-ACCEPTED source rejection.

Run:

```bash
env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/test_multilingual.py -q
env -u PYTHONPATH .venv/Scripts/python.exe -m ruff check src/tristate/multilingual tests/test_multilingual.py
```

The mock tests do not prove translation quality. They prove the control flow,
alignment, storage and failure semantics.

A real one-family `bn_in_native` pilot has now run with the shared
`LLM_API_KEY` (37 calls). It was **quarantined**, not accepted: the final window
review retained style-only findings requiring English forms in parentheses for
proper nouns and technical terms, after an earlier tense/modality repair. The
machine-readable reason is in
`data-v5/multilingual/bn_in_native/quarantine/FAM_000001.json`. This is the
current quality gate doing its job; it means the translation prompts/repair
policy need tuning before a larger run.

## 8. Cost and latency estimate

For a ~3,300-word variant, the default 250–500-word windows yield about 13
windows. With one translation and one review call per window:

- per variant: ~26 calls;
- per family: ~78 window calls + claim/glossary/review calls (~7);
- per 100-family profile: roughly 8,500 calls;
- all four profiles: roughly 34,000 calls.

The initial `FAM_000001` pilot used 37 calls for one family because it is
claim/glossary plus 13 windows across three variants, with two repair rounds on
some windows.

Cost is not estimated until the operator supplies the actual DeepSeek price and
a pilot measures call sizes. The client records token usage and call counts;
`cost_usd` remains zero while the configured price fields are zero.

## 9. Failure policy

- transport / timeout errors are retried by the shared client;
- schema errors use the client's bounded schema repair;
- semantic failure is never repaired by relabelling;
- after the repair budget, the family is written to `quarantine/` with the
  reviewer's exact reasons;
- accepted records carry `source_immutable_checksum_verified` and
  `three_labels_share_target_claims` audit flags.

## 10. Next gates before a release

1. Run one family for `bn_in_native` with the shared `LLM_API_KEY` and inspect the output.
2. Native-speaker review of the first 3 families (claims, windows, final
   variants); record findings in `docs/reports/`.
3. Add separate surface-realization for romanized/Banglish if the semantic call
   leaks English syntax or inconsistent romanization.
4. Freeze profile versions and export per profile; never mix profiles in one
   split without a profile key.
5. Add human adjudication for quarantined relation drift.
