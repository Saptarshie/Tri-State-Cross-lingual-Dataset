# Dataset card — Tri-state evidence families (pilot)

Version: `pilot-02` · Language: English (`en`) · Schema: `0.1.0` · Built: 2026-11-24

---

## 1. What this dataset is

A set of **families**. Each family is one base document plus a fixed set of 2–5 atomic claims,
reproduced in three variants whose relationship to the claim set is known by construction:

| Label | Relation of passage to every claim |
|---|---|
| `SUPPORTED` | each claim is entailed by the passage |
| `CONTRADICTED` | each claim is explicitly contradicted by the passage |
| `UNSUPPORTED` | each claim is neither entailed nor contradicted (evidence absent) |

The unit of use is the family. Variants of one family share a claim set, a topic, a style, a
split and a group ID; they are not independent examples and must never be split across partitions.

The intended learning signal is *evidence-conditioned verification*: decide what the supplied
passage establishes, not what the model believes about the world. The passages are largely
synthetic and deliberately counterfactual; fictional entities and numbers are the point.

---

## 2. Size (pilot)

| Item | Count |
|---|---|
| families | 15 |
| variants | 45 |
| claims | 54 |
| claims per family | mean 3.6 (min 2, max 5) |
| passage length | mean 128.8 tokens (72–169) — **short pilot version**; the generator now defaults to 2,000–4,000-token documents (`passage.target_tokens_min/max`) |
| splits | train 15, dev 0, test 0 |
| labels | 15 SUPPORTED, 15 CONTRADICTED, 15 UNSUPPORTED |

Files: `families.jsonl` (source of truth), `variants.jsonl` (one row per variant, claim set
repeated), `claims.jsonl` (claim table with evidence spans), `manifest.json` (counts, hashes,
models, problems), `splits.json`, `README.md`.

---

## 3. Construction

1. A topic is selected from a seeded, coverage-tracked graph (inverse-frequency score with
   parent-branch diversity); style is sampled across 12 genres, 7 tones, 8 structures, 6
   narrative modes and 3 complexity levels.
2. An LLM plans a blueprint (concept, subtopics, expected entities/relations, fact count) after a
   novelty report over previously accepted blueprints.
3. A base document (2k–4k model tokens by default) is generated section by section and screened
   deterministically (length band, Latin script, no task/meta language, no markdown in prose
   structures).
4. Facts are extracted with verbatim sentence-level evidence spans; 2–5 atomic claims are
   generated and filtered for single-proposition form, entity presence and passage support.
5. An independent validator checks that the base entails every claim; claims that fail are
   dropped (or the candidate is abandoned).
6. A coordinated editor produces label-specific patches for the whole claim set; a deterministic
   engine applies them (exact span match required) and screens structure/length/overlap.
7. Each variant is validated by a model from a different family, with the intended label hidden;
   failures trigger bounded re-planning.
8. Deterministic family checks, an advisory graph diff and a novelty check decide acceptance;
   mixed or failing families are quarantined rather than relabelled.

Models used for this version: `deepseek/deepseek-v4.1-flash` (blueprint, passage, editing),
`xiaomi/mimo-v2.6-flash` (extraction, claims, second validator),
`google/gemini-3.8-flash` (primary validation). Total cost of the pilot corpus: **$0.138**.
Prompts are versioned in `prompts/`; the config hash and prompt versions are recorded per family.

---

## 4. Fields (families.jsonl)

`family_id`, `split_group_id`, `language`, `script`, `locale`, `language_generation_method`,
`source` (mode, provenance, licence note), `topic` (path, node IDs), `blueprint` (concept,
subtopics, planned relations, style including genre/tone/narrative/structure/complexity),
`base_passage` (text, tokens, style, checksum),
`semantic_representation` (summary, entities, facts with spans), `claim_set` (claim text, type,
fact links, evidence spans), `variants` (three labelled variants with text, checksum, edit
history/diff, relation rows, per-variant graph diff and validation), `generation` (models, prompt
versions, config hash, run ID, tokens, cost), `quality` (status, hard checks, scores,
`human_verified`), `split`, `dataset_version`, `idempotency_key`, `created_at`.

`variants.jsonl` flattens the same data for training pipelines and repeats the claim set per row.

---

## 5. Validation and measured caveats

- **Independent validation** is the acceptance gate: per-claim relation label plus confidence,
  with the intended label withheld. A second validator runs on low confidence, on failure, and on
  a random sample; disagreements are hard failures.
- **Deterministic checks** cover label completeness, claim uniqueness, evidence presence, script,
  length ratios, meta-language, content overlap, repeated sentences and obvious truncation.
- **Graph diff** is reported per variant but is advisory; extraction paraphrases and misses make
  it too noisy to gate on. Do not read a graph-diff miss as a label error.
- **Shortcut audit (surface form only):** 0.467 accuracy (95% CI 0.27–0.73) against 0.333 chance
  on a family-wise split; not flagged. Recipe metadata and edit counts were excluded because they
  are unavailable at inference.
- **Human verification:** none yet. One record is flagged for review; per-class precision has not
  been estimated. Treat labels as construction-verified, not human-verified.
- **Splits:** at this N, hash assignment put every family in `train`; there is no usable
  held-out partition in `pilot-02`. Regenerate at larger N before measuring generalisation.
- **Spurious cues:** some structures (bulleted/numbered) legitimately differ in formatting across
  labels only through the edit, not by design; check your model for formatting shortcuts rather
  than assuming none exist.

---

## 6. Intended use

Appropriate:

- training and evaluating context-faithfulness / evidence-grounded verification;
- measuring abstention and "insufficient evidence" behaviour;
- stress-testing retrieval pipelines for whether the model follows the retrieved passage instead
  of parametric memory;
- controlled experiments on contradiction detection where the claim set is held fixed.

Not appropriate:

- treating passages as factual statements about the real world (many are counterfactual and all
  are synthetic in this pilot);
- fact-checking ground truth, news verification, or safety-critical adjudication;
- inferring prevalence of any real-world phenomenon from these numbers;
- splitting variants of one family across train/test, or counting variants as independent samples.

---

## 7. Ethics, privacy, provenance

- No personal data was collected or ingested for this version; entities, organisations and people
  are invented. Any resemblance is coincidental.
- Claims and passages can assert false or misleading propositions **by design**. Publishing a
  `CONTRADICTED` passage without its label would be misinformation; keep labels attached and do
  not surface variants as standalone text.
- The corpus is machine-generated with hosted models; outputs may reflect model biases in topic
  selection and phrasing. Topic coverage is skewed toward technology, health, science, business,
  environment, culture and policy seeds.
- Licence and redistribution terms are **not yet set** by the dataset owner; do not redistribute
  until that decision is recorded in `manifest.json`.
- Provider terms and per-call costs are recorded in the local ledger; raw provider responses are
  retained under `data/raw/` for audit and are not part of the dataset.

---

## 8. Maintenance

- Version immutably: `tristate export --version <name>`; never edit `families.jsonl` by hand.
- Re-running with a changed prompt regenerates only the affected stage; use a fresh data
  directory for a clean rebuild (see `docs/runbook.md`).
- Report problems via `manifest.json` `problems` and `docs/reports/`; quarantine files are
  diagnostics, not dataset rows.
- Companion documents: `docs/design.md` (contracts), `docs/state.md` (current status),
  `docs/runbook.md` (operations), `docs/devlog.md` (decisions).
