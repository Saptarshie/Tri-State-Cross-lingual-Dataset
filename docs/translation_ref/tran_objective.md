# Objective: Claim-Aware Multilingual Extension for Existing English Tri-State Families

## 1. Mission

Extend the already implemented English-only tri-state passage-family pipeline so that it can produce high-quality Bengali, romanized Bengali, and naturally code-mixed Bengali-English versions of the **existing English tri-state dataset**.

This is a multilingual transformation layer, not a second dataset-generation pipeline. The English dataset is already generated and is the authoritative source. The implementation must preserve its passage-family structure, fixed claim sets, labels, source text, evidence relationships, provenance, and split assignments.

The core requirement is **claim-aware translation from the beginning of the translation process**. Do not translate passages first and only check their labels at the end. Before translating any passage window, the translation agent must know:

- the complete fixed claim set for the family;
- the semantic meaning and critical components of every claim;
- the intended relation between each claim and the current passage variant;
- the target language profile, script, locale, register, and code-switching policy;
- the source passage's relevant context, terminology, entity spellings, and qualifiers.

It must then translate, transliterate, or code-mix the passage while actively preserving the required evidence relation. This is a semantic constraint, not permission to rewrite the text to make a label easier to satisfy.

Use **DeepSeek only** for every model-based language operation in this extension: translation, transliteration, romanization, code-mix generation, linguistic naturalization, semantic planning, claim-aware review, and repair. Do not call Google Translate, another translation API, Gemini, OpenAI, or another LLM. Deterministic software components such as text segmentation, Unicode normalization, alignment, JSON validation, storage, hashing, and ordinary database or search operations remain allowed.

The default API model identifier should be configurable and initially set to `deepseek-flash`. Do not hard-code a dated model checkpoint into application logic. Record the exact model identifier and relevant request settings used for every generation and review call.

---

## 2. Scope and non-goals

### 2.1 In scope

1. Load accepted English passage families from the existing pipeline.
2. Validate their existing tri-state contracts before translation.
3. Build a structured, claim-aware semantic constraint ledger for every family.
4. Create target-language renderings of the fixed claims exactly once per family and target profile.
5. Translate all three passage variants in sentence-aligned, paragraph-aware windows.
6. Perform Bengali-script rendering, romanization/transliteration, and natural code-mixing using DeepSeek.
7. Preserve the family-level label contract in every target language profile.
8. Independently review translated claims and passages using separate DeepSeek review calls and deterministic checks.
9. Repair localized translation defects without changing the original English data or the canonical claims.
10. Store all language outputs, sentence/window alignments, prompts, model metadata, validation reports, and lineage.
11. Support resumable jobs, caching, retries, cost tracking, and family-level acceptance/rejection.
12. Export multilingual data while retaining the original source-family split assignment.

### 2.2 Explicitly out of scope

Do not:

- regenerate the English corpus, blueprints, claims, or tri-state variants;
- create new claims during translation;
- independently invent three new target-language passages;
- make an unsupported passage more informative to improve readability;
- insert missing facts because DeepSeek knows them from pretraining;
- remove or weaken a contradiction because it sounds awkward in the target language;
- change the canonical claim set between SUPPORTED, CONTRADICTED, and UNSUPPORTED variants;
- use another model/API as a fallback translator or transliterator;
- fact-check intentionally fictional or counterfactual source content against the real world;
- use back-translation as the sole proof of semantic fidelity;
- silently accept mixed or ambiguous evidence relations;
- overwrite or mutate the original English records.

The multilingual extension must remain usable without internet access to any translation service other than the configured DeepSeek API. If DeepSeek is unavailable, pause/retry the job; do not silently fall back to a different provider.

---

## 3. Existing English pipeline is authoritative

Assume the previous Hermes implementation has already generated and accepted English tri-state families. Reuse its existing identifiers, semantic artifacts, evidence anchors, family objects, versioning, storage, HNSW infrastructure, and split policy wherever available. Inspect the repository and current schemas before implementing anything. Extend existing interfaces instead of creating competing copies.

The English source family contains:

- one `passage_family_id`;
- one fixed set of atomic claims `C = {c1, c2, ..., ck}`;
- a `SUPPORTED` passage variant;
- a `CONTRADICTED` passage variant;
- an `UNSUPPORTED` passage variant;
- source sentence/paragraph IDs and offsets, where available;
- claim evidence/contradiction/neutrality anchors and semantic graph data, where available;
- the family-level split assignment and lineage metadata.

Before any translation work, run a **source-family preflight**. Confirm that the source English family itself satisfies the strict all-claims tri-state rule. If the English parent fails, is mixed, has missing claims, or lacks enough evidence to determine a relation, quarantine it for review. Do not use translation to repair the English source family.

The original English passage text, claims, labels, IDs, evidence anchors, family metadata, and split assignment are immutable inputs to this extension. Store target-language outputs as versioned children of the source family.

---

## 4. Non-negotiable semantic contract

### 4.1 Family-level relation invariant

For a family with fixed claim set `C = {c1, ..., ck}`, every target-language profile must retain the same three-way relationship:

| Target passage variant | Required relation to every translated claim |
|---|---|
| `SUPPORTED` | The passage entails or sufficiently establishes the claim. |
| `CONTRADICTED` | The passage explicitly or unambiguously contradicts the claim. |
| `UNSUPPORTED` | The passage neither establishes nor contradicts the claim. |

For a target profile `L`, let `T_L(c_i)` be the canonical target-language rendering of claim `c_i`, and let `P_{L,v}` be the target rendering of variant `v`:

\[
\forall c_i \in C:\quad
P_{L,SUPPORTED} \models T_L(c_i)
\]

\[
\forall c_i \in C:\quad
P_{L,CONTRADICTED} \models \neg T_L(c_i)
\]

\[
\forall c_i \in C:\quad
P_{L,UNSUPPORTED} \not\models T_L(c_i)
\quad\text{and}\quad
P_{L,UNSUPPORTED} \not\models \neg T_L(c_i)
\]

The last condition is essential: **UNSUPPORTED means neutral/not established, not false**. Do not translate it as a denial, negation, or contradiction.

### 4.2 Same claims across all three variants

Translate the claim set once for each target profile. Store one canonical target rendering for every `claim_id`. Reuse those exact claim strings when exporting all three passage variants in that profile. Do not independently retranslate or paraphrase a claim for each variant.

A family may have multiple target profiles, and each profile may have its own canonical wording, but within one profile the claim set is fixed across the entire triad.

### 4.3 Translation must preserve, not manufacture, evidence

The intended relation is a hard guardrail, but it does not authorize semantic editing. The target passage must remain a faithful rendering of its specific English source variant.

Examples:

- If the English SUPPORTED passage states that a fictional person named Mira founded a fictional company, preserve that statement in translation. Do not replace it with real-world knowledge.
- If the English CONTRADICTED passage names Ravi while the claim names Mira, preserve Ravi as the subject. Do not switch the name to Mira during naturalization.
- If the English UNSUPPORTED passage does not mention who founded the company, do not insert Mira, Ravi, a denial, or an inferred answer to make the passage sound complete.
- If a contradiction is expressed through a date, number, polarity, comparison, condition, or subject-object reversal, preserve that exact semantic distinction.

The translator must never “fix” a target-language relation by adding a new fact, deleting a critical fact, changing a name, changing a date, flipping negation, changing modality, or changing who did what to whom.

### 4.4 All-or-nothing family acceptance

Every claim in a variant must satisfy the expected relation. A target variant that supports some claims but not others, contradicts only some claims, or becomes ambiguous is `MIXED_INVALID` for this task. Quarantine or repair the translation. Never force it into one of the three classes.

---

## 5. Target language profiles

The labels “Benglish/Banglish” and “Engali” are not universally standardized. Define them as **project-specific, explicit profiles**, not as assumptions inferred from the word alone. The profiles must be configurable and versioned.

### 5.1 Initial profiles

Implement these profiles initially:

| Profile ID | Intended language behaviour | Default script |
|---|---|---|
| `bn_in_native` | Natural Bengali, with an Indian Bengali / West Bengal default locale. | Bengali script |
| `bn_latn_romanized` | Bengali language expressed primarily in Latin characters; preserve conventional romanized Bengali spellings where practical. | Latin script |
| `benglish_latn` | Bengali-led sentence structure and conversational voice, with natural English lexical insertions; primarily romanized Bengali. | Latin script |
| `engali_mixed` | English-led sentence structure with natural Bengali words or phrases inserted. | Mixed: Bengali script for Bengali spans by default; configurable to Latin script. |

Do not assume every user or corpus writer uses these names identically. Keep the profiles explicit so that their definitions can be changed without changing the source dataset.

### 5.2 Profile fields

Each profile configuration should include:

```yaml
profile_id: bn_in_native
base_language: Bengali
locale: bn-IN
primary_language: Bengali
secondary_language: English
script_policy: Bengali
sentence_syntax: Bengali-led
code_switching: false
code_switching_intensity: none
register: neutral_conversational
regional_style: west_bengal
romanization_policy: not_applicable
english_lexical_insertion_policy: preserve_only_when_source_or_style_requires
proper_noun_policy: preserve_identity; transliterate_only_when_natural
number_policy: preserve_numeric_value; locale_formatting_allowed
```

For `bn_latn_romanized`, `benglish_latn`, and `engali_mixed`, adjust `script_policy`, `sentence_syntax`, `code_switching`, and `romanization_policy` accordingly.

Support at least:

- locale/dialect preference (for example `bn-IN` versus `bn-BD`);
- script choice;
- primary sentence language;
- code-switch direction (Bengali-led or English-led);
- code-switch intensity (`light`, `moderate`, `heavy`);
- formal, neutral, conversational, colloquial, or technical register;
- treatment of names, acronyms, technical terms, numbers, dates, and units;
- profile version and prompt version.

Do not enforce a fixed English/Bengali word percentage sentence by sentence. Natural code-switching is syntactic and contextual, not merely a ratio of words. The profile should guide the style while the semantic guardrails remain invariant.

### 5.3 Bengali and Bengali-English rendering

For Bengali-native output, target fluent Bengali, not English syntax with Bengali words substituted one by one.

For romanized Bengali, produce Bengali-language syntax in Latin script. Do not merely leave English sentences unchanged and transliterate a few nouns.

For Bengali-led code-mixing, allow English words and phrases where a fluent speaker would naturally insert them, but preserve Bengali grammatical structure and the source's propositions.

For English-led mixed output, retain English syntax as the backbone and insert Bengali words/phrases naturally. Do not force every Bengali concept into English or every English concept into Bengali.

Use the user's intended style examples as style references only. Profanity, informality, slang, or emotional intensity must be preserved only when consistent with the source passage and the selected profile; do not introduce new sentiment or tone.

---

## 6. DeepSeek-only model policy

### 6.1 One provider for all language intelligence

All model-based operations in this extension must use DeepSeek. The default configuration is:

```env
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_THINKING_MODE=off
DEEPSEEK_REVIEW_THINKING_MODE=on
```

The model and settings must be configurable. Confirm the currently available model name and API contract during deployment; do not assume a model alias will always point to the same checkpoint.

Use the same DeepSeek model for:

- claim decomposition and semantic-card generation;
- target claim translation;
- family terminology/glossary planning;
- faithful passage translation;
- Bengali script rendering and romanization;
- code-mix realization;
- linguistic naturalization;
- claim-aware semantic review;
- localized repair;
- final family-level review.

Do not use a second LLM as a “judge” or fallback. The reviewer must be a separate DeepSeek call with a distinct role, prompt, and input format from the translator. Where possible, do not show the reviewer the translator's self-assessment or rationale.

### 6.2 API documentation and model configuration

Use the current official DeepSeek API documentation as the implementation authority for model IDs, request formats, structured/JSON output, thinking-mode controls, rate limits, and pricing. In particular, verify the model list and API contract at deployment time rather than relying on a model name copied into this document. The initial configured model name is `deepseek-flash`; the source code must keep it configurable.

Official references:

- API quick start: https://api-docs.deepseek.com/en/
- Models and pricing: https://api-docs.deepseek.com/quick_start/pricing/
- Model list: https://api-docs.deepseek.com/api/list-models/

### 6.3 Thinking mode policy

Use non-thinking mode by default for routine faithful translation and deterministic surface realization. Use thinking mode for tasks requiring explicit multi-step semantic comparison, difficult claim interpretation, ambiguity diagnosis, or coordinated repair planning. These are configuration choices, not separate model providers.

The reviewer must return a structured verdict and evidence spans, not a free-form chain-of-thought. Store concise explanations and findings, not hidden reasoning traces.

### 6.4 No fallback provider

If the DeepSeek API call fails because of quota, timeout, rate limit, network outage, malformed output, or service error:

1. persist the current job checkpoint;
2. retry with bounded exponential backoff for retryable errors;
3. record the failure and request metadata;
4. pause or mark the job retryable after the configured retry budget is exhausted.

Never route the request to another translation service. Do not scrape a public translation website or use unofficial wrappers.

### 6.5 Deterministic components remain allowed

DeepSeek-only does not mean every operation must be an LLM call. Use ordinary code for:

- Unicode validation and normalization;
- sentence and paragraph segmentation;
- sentence IDs and offset tracking;
- window construction and assembly;
- JSON schema validation;
- number/date/unit extraction and comparison;
- named-entity string checks where safe;
- checksums, hashes, caching, queueing, retries, database operations, and export;
- HNSW or lexical retrieval using the project's existing infrastructure.

Do not add an external embedding API or another language model merely to implement this extension. Reuse existing indexes and embeddings where useful. If a new embedding dependency is truly required, keep it outside the language-transformation path, make it optional, and document it explicitly rather than silently violating the DeepSeek-only policy.

---

## 7. Claim-aware semantic constraint ledger

This ledger is the central component of the multilingual extension. Build it **before translating any passage text**.

### 7.1 Why it is required

Ordinary translation focuses on preserving general meaning. This dataset requires preserving a much more specific relationship: every target passage must support, contradict, or remain neutral toward every member of a fixed claim set.

A sentence can remain broadly understandable while accidentally changing the exact fact that determines its class. Examples include:

- changing the grammatical subject or object;
- changing the agent of an action;
- converting “may” into “will”;
- dropping a negation;
- turning “at least 8” into “8”;
- changing “before” into “after”;
- changing a year, unit, range, comparison, or condition;
- adding an omitted fact to make a sentence more natural;
- romanizing a name in a way that makes it look like a different entity;
- using a code-switched English phrase that accidentally supplies a missing fact.

The ledger makes these claim-bearing details explicit and available to every translation window.

### 7.2 Claim semantic card

For every canonical English claim, create or reuse a structured card:

```json
{
  "claim_id": "claim_001",
  "source_claim": "...",
  "proposition": "normalized natural-language proposition",
  "subject": {"text": "...", "entity_id": "..."},
  "predicate": "...",
  "object": {"text": "...", "entity_id": "..."},
  "attributes": [],
  "polarity": "positive",
  "modality": "asserted",
  "quantifiers": [],
  "numbers": [],
  "dates": [],
  "units": [],
  "temporal_scope": "...",
  "spatial_scope": "...",
  "conditions": [],
  "comparisons": [],
  "causal_or_attribution_relation": "...",
  "critical_distinctions": [],
  "source_evidence_anchor_ids": [],
  "source_contradiction_anchor_ids": [],
  "source_neutrality_notes": {}
}
```

Fields may be null or empty when inapplicable. Do not hallucinate structure that is not in the source claim. Reuse the existing English fact graph and claim metadata when available; use DeepSeek to fill only missing semantic fields.

### 7.3 Variant-specific obligations

Create one relation obligation per claim per variant:

```json
{
  "claim_id": "claim_001",
  "expected_relation": "SUPPORTED",
  "must_preserve": ["subject", "predicate", "object", "date", "polarity"],
  "critical_source_anchor_ids": ["sentence_004"],
  "relation_explanation": "The source variant states ...",
  "forbidden_translation_effects": [
    "do not change the agent",
    "do not remove the date",
    "do not introduce a different attribution"
  ]
}
```

Use the matching expected relation for each variant:

- SUPPORTED variant → `SUPPORTED` for every claim;
- CONTRADICTED variant → `CONTRADICTED` for every claim;
- UNSUPPORTED variant → `UNSUPPORTED` for every claim.

The ledger must be passed into every window-level translation request. Do not leave the target translator to infer the required relation from the passage alone.

### 7.4 Target-language claim rendering

Translate every claim once per target profile. The claim-translation request must receive:

- original English claim;
- claim semantic card;
- target profile;
- regional/locale settings;
- script and romanization requirements;
- term/entity glossary, when already available;
- instruction to preserve proposition, polarity, modality, scope, numbers, dates, units, and attribution.

The result must include:

- one canonical target claim string;
- a structured target-language proposition card;
- a list of critical terms and variants/aliases that are acceptable;
- unresolved ambiguity flags, if any.

Do not translate a claim separately for each passage variant. Do not allow later passage translation calls to rewrite the canonical target claim. If a claim cannot be rendered unambiguously in a profile, mark the family/profile as `CLAIM_TRANSLATION_AMBIGUOUS` and quarantine it for review.

### 7.5 Claim-aware glossary

Build a **claim-critical glossary seed before target-claim translation** from the existing entity/fact graph and claim semantic cards. It should resolve the canonical treatment of entities and technical terms that appear in claims. After the target claims are reviewed, expand this seed into the full family/profile glossary using the complete source family. Freeze the resulting glossary version before translating passage windows.

Build the glossary at family/profile level, not independently for each window. It should cover:

- named entities and their stable target forms;
- technical terms and abbreviations;
- locations and organization names;
- role names and titles;
- recurring noun phrases;
- claim-bearing predicates and relational terms;
- numerals, dates, units, and transliteration policy;
- aliases or acceptable romanized spellings.

A glossary entry must preserve identity and meaning. It must not add a fact absent from the passage. A glossary can specify the target spelling of a person or product name, but it cannot decide that an unmentioned person is the answer to a claim.

---

## 8. Family-level translation architecture

Implement the extension as a sequence of durable, resumable stages:

```text
EXISTING ACCEPTED ENGLISH FAMILY
              |
              v
     SOURCE FAMILY PREFLIGHT
     verify tri-state invariants
              |
              v
     CLAIM SEMANTIC LEDGER
     facts, qualifiers, anchors,
     per-variant relation obligations
              |
              v
      TARGET PROFILE PLANNER
     locale, script, register,
     syntax direction, code-mix policy
              |
              v
      CLAIM-CRITICAL GLOSSARY SEED
     claim entities and key terms
              |
              v
      TARGET CLAIM TRANSLATION
     one canonical claim set/profile
              |
              v
      FAMILY GLOSSARY + PLAN
     full terminology and style policy
              |
              v
       WINDOW TRANSLATION LOOP
     one source variant at a time;
     global claim ledger + local window;
     translate / render / review / repair
              |
              v
      VARIANT ASSEMBLY + ALIGNMENT
     preserve sentence IDs and order
              |
              v
      FAMILY-LEVEL REVIEW
     compare all three target variants
     against same translated claims
              |
              v
      ACCEPT / REPAIR / QUARANTINE
              |
              v
      VERSIONED MULTILINGUAL CHILD
     inherit source family split + lineage
```

### 8.1 Translate one variant at a time

Process the three variants as members of one family, but do not put the full text of all three variants into every translator prompt. Each variant should be translated from its own English text with:

- the shared family claim ledger;
- the fixed target claim set;
- the same family glossary;
- its own intended label relation;
- its own source passage and current window.

This reduces cross-contamination. For example, the SUPPORTED passage must not leak evidence into an UNSUPPORTED translation simply because both texts are visible in the same prompt.

A final family-level reviewer may inspect all three completed target passages together, because its task is to verify the complete triad rather than generate any passage text.

### 8.2 Shared family plan

Create a family translation plan once per `passage_family_id` and `target_profile_id`. The ordering is: build the claim-critical glossary seed, translate and review the canonical target claims, expand/finalize the full family glossary, then freeze the plan before passage translation. The plan contains:

- target profile and locale;
- claim semantic cards and fixed target claim strings;
- glossary and canonical names;
- global synopsis for referential continuity;
- paragraph and sentence segmentation map;
- style/voice constraints;
- script/romanization policy;
- claim-bearing semantic invariants;
- known ambiguity warnings.

The plan may be reused across all three variants. Keep evidence text and variant-specific content isolated in each translation job.

---

## 9. Long-passage windowing and alignment

### 9.1 Do not translate long passages as arbitrary token slices

Long passages must be translated in windows, but windows should respect the document's structure. Prefer paragraph and sentence boundaries. Never split a sentence in the middle merely to hit a fixed word count unless the sentence itself exceeds the configured context budget.

A reasonable initial window size is approximately **250–500 source words**, adjusted by token count, passage complexity, target output size, and DeepSeek request limits. This is a starting configuration, not a hard limit. Use smaller windows for dense passages with many claim-bearing details and larger windows for simple prose.

### 9.2 Sentence and paragraph IDs

Before translation:

1. assign stable IDs to paragraphs and sentences;
2. store the exact source text and offsets;
3. map existing claim evidence/contradiction anchors to sentence IDs;
4. create contiguous windows from these IDs;
5. retain a deterministic order for assembly.

Suggested IDs:

```text
paragraph_0001
sentence_000001
sentence_000002
window_0001
```

Do not derive stable IDs from translated text. The source English IDs remain the alignment anchors.

### 9.3 Context overlap

Each window request may include:

- the complete current window as translatable text;
- the previous sentence or paragraph as read-only context;
- the next sentence or paragraph as read-only context;
- a short global synopsis;
- the family glossary;
- the full target claim set and claim ledger.

Mark read-only context explicitly. It is supplied only for pronoun, terminology, discourse, and referential continuity. Do not emit the overlap text twice in the assembled passage.

### 9.4 Window request contract

Every window-level request must include at minimum:

```json
{
  "job_id": "...",
  "passage_family_id": "...",
  "source_dataset_version": "...",
  "target_profile_id": "benglish_latn",
  "variant_label": "UNSUPPORTED",
  "expected_relation_for_all_claims": "UNSUPPORTED",
  "target_claims": [],
  "claim_constraint_ledger": [],
  "family_glossary": [],
  "global_synopsis": "...",
  "window_id": "window_0003",
  "source_sentence_ids": ["sentence_000021", "sentence_000022"],
  "translatable_source_text": "...",
  "previous_context_read_only": "...",
  "next_context_read_only": "...",
  "style_profile": {},
  "required_output_script": "Latin",
  "translation_instructions_version": "..."
}
```

The `variant_label` and expected relation are explicit. The model must not infer whether the current passage should support, contradict, or omit each claim.

### 9.5 Window output contract

Require structured JSON with:

- `window_id`;
- target text aligned to source sentence IDs;
- per-sentence target strings;
- glossary changes proposed (not automatically accepted);
- unresolved ambiguity flags;
- critical semantic transformations applied;
- any source phrase that could not be translated safely;
- a concise self-check status.

Do not accept a response that silently drops a sentence, merges unrelated sentences, duplicates overlap text, or returns an unparseable structure. Validate the response against a JSON schema and source sentence inventory.

### 9.6 Cross-window continuity pass

After all windows for a variant are translated, run a continuity review across the assembled target passage. Check:

- pronoun and entity reference consistency;
- stable transliteration and terminology;
- consistent tense/aspect and temporal references;
- discourse connectors and paragraph flow;
- repeated names and technical terms;
- sentence order and omissions;
- accidental repeated overlap.

The continuity pass may make localized linguistic corrections only. It must retain the same claim relation and cannot add or remove facts to smooth the prose.

---

## 10. Translation, transliteration, and code-mix realization

Treat these as different language operations with different constraints, even though the same DeepSeek model performs them.

### 10.1 Pass A — semantic translation

Create a faithful semantic target draft for each window. This pass must preserve all propositional content, qualifiers, relationships, and omissions in the source window.

For Bengali-native output, the result should already be natural Bengali in Bengali script.

For romanized Bengali and Bengali-led code-mix, produce an internal Bengali-language semantic draft first if that makes the rendering more reliable. This intermediate draft is internal and must retain source sentence IDs.

For English-led `engali_mixed`, retain the English sentence backbone while planning Bengali spans for natural insertion. Do not force a fully Bengali translation if the profile calls for English-led speech.

### 10.2 Pass B — surface realization

For profiles that require it, render the semantic draft into the requested script and code-mix style:

- Bengali script;
- romanized Bengali in Latin script;
- Bengali-led Bengali-English mix;
- English-led English-Bengali mix.

This pass is not free rewriting. It may change word choice, spelling, script, syntax, and code-switch placement only when the underlying proposition is unchanged.

Every surface-realization request must receive the same claim ledger and variant-specific relation obligations as Pass A. Do not assume that a faithful semantic draft makes a later romanization/code-mix step safe automatically.

### 10.3 Romanization rules

For romanized Bengali:

- use consistent, readable Latin spellings;
- preserve Bengali grammatical markers and word order;
- do not transliterate English lexical items that should remain English;
- retain stable spellings for names and terms across the entire family;
- do not switch romanization conventions within one family;
- allow a configured alias list for common colloquial spellings;
- do not use transliteration to disguise a semantic rewrite.

A single canonical target claim string must be fixed for the profile. Any spelling variants used in passage text must still resolve unambiguously to the same entity/term and must not create a second interpretation.

### 10.4 Code-switch rules

For Bengali-led code-mixing:

- Bengali syntax remains the primary grammatical structure;
- English insertions should sound natural and context-appropriate;
- do not insert English phrases that add a fact or make an omitted claim explicit;
- preserve technical expressions where English is natural, but do not automatically translate every technical word into English;
- keep tense, negation, modality, quantity, attribution, and argument structure unchanged.

For English-led code-mixing:

- English syntax remains the primary structure;
- Bengali words/phrases may be inserted where natural;
- Bengali insertions must not alter the subject, object, relation, polarity, temporal scope, or degree of certainty;
- do not paraphrase an absent target fact into a Bengali aside or parenthetical explanation.

Do not optimize for an arbitrary percentage of English tokens. Prefer natural discourse and semantic fidelity.

### 10.5 No explanatory additions

Do not add parenthetical explanations, translator notes, definitions, examples, or background facts unless they were present in the English source. Translation must not become summarization or enrichment.

---

## 11. Claim-aware ReAct workflow

Implement a bounded ReAct-style loop. It should be surgical, stateful, observable, and resumable. Do not allow an unlimited agent loop.

### 11.1 Per-family/profile planning loop

1. **Observe:** load the accepted English family, all source claims, the three variants, source evidence anchors, and existing semantic graph.
2. **Check:** verify the English family-level tri-state contract. Quarantine invalid source families.
3. **Analyze:** build the claim semantic cards and per-variant relation obligations.
4. **Plan:** resolve target profile, locale, script, register, glossary, transliteration conventions, and ambiguous terms.
5. **Translate claims:** create the fixed target claim set once.
6. **Review claims:** use a separate DeepSeek call to check proposition preservation, atomicity, polarity, scope, modality, and all critical attributes.
7. **Commit plan:** freeze the claim strings and family glossary version for this job. A later change requires a new job version.

### 11.2 Per-window loop

For each variant and window:

1. **Observe:** load the exact source window, source sentence IDs, adjacent read-only context, target claim set, claim ledger, and variant relation obligations.
2. **Plan:** determine which source sentence IDs and claim-bearing elements need special attention in this window.
3. **Translate:** generate the faithful semantic translation.
4. **Render:** apply script conversion, romanization, or code-mix realization for the selected profile.
5. **Check structurally:** validate JSON, sentence inventory, output completeness, and deterministic number/date/unit/name constraints.
6. **Review semantically:** ask a separate DeepSeek reviewer to compare the source window and target window against the claim ledger and expected relation.
7. **Diagnose:** if there is a defect, identify the precise target sentence(s), claim ID(s), and semantic element(s) involved.
8. **Repair:** regenerate or patch only the defective sentence/span, using source text and the complete claim constraints. Do not rewrite unaffected windows.
9. **Re-check:** rerun the structural and semantic checks after repair.
10. **Commit:** store the accepted window and its review record.

Maximum default repairs per window: **2**. Make this configurable. If the window still fails, mark it `NEEDS_HUMAN_REVIEW` or quarantine the whole family/profile. Do not continue making uncontrolled edits.

### 11.3 Family-level ReAct review

After all three variants are assembled:

1. review the canonical target claim set;
2. review each variant against every target claim;
3. check the all-claims tri-state matrix;
4. compare the target family to the English source family for proposition preservation;
5. check that the three texts remain distinct in the intended evidence relationship;
6. check cross-variant entity spelling and terminology consistency;
7. accept, request a bounded localized repair, or quarantine.

The family-level reviewer may see all three completed target passages. The translator for an individual variant/window should not receive the other variants' full text as generation context.

### 11.4 Repair policy

A repair must state:

- defect type;
- affected source sentence ID(s);
- affected target sentence ID(s);
- affected claim ID(s);
- expected relation;
- exact semantic element that changed or became ambiguous;
- minimal required correction.

The repair prompt must explicitly forbid changing any unrelated meaning. Prefer a sentence-level replacement over rewriting the whole passage. After a repair, re-run review for the entire affected window and family-level review when the repair could affect a claim relation.

### 11.5 Do not expose hidden reasoning

The agent should store concise plans, checklists, structured decisions, defect descriptions, and evidence spans. It does not need to store private chain-of-thought. Require explicit machine-readable outcomes rather than hidden reasoning dumps.

---

## 12. Prompt contracts

Store prompt templates in versioned files. Do not scatter long prompt strings throughout application code. Each prompt must declare its role, allowed operations, input schema, output schema, and hard semantic constraints.

### 12.1 Core translator system instructions

Use the following as the basis for the translation role. Adapt wording to the selected target profile but retain all invariants:

> You are a faithful multilingual renderer for a controlled evidence-verification dataset. Translate or render only the supplied source text. You are not a fact completer, fact checker, summarizer, editor, or answer generator.
>
> You are given a fixed set of claims and an expected evidence relation between the current passage variant and every claim. Treat these as hard semantic constraints while translating. Preserve the source passage's actual assertions, omissions, contradictions, entities, relations, polarity, numbers, dates, units, modality, conditions, comparisons, and attribution.
>
> Do not add information from world knowledge, common sense, another passage variant, or an imagined context. Do not insert a claim merely because it is supplied to you. The claims are constraints for preserving meaning, not content to copy into the passage.
>
> For SUPPORTED, preserve the source statements that establish every claim. For CONTRADICTED, preserve the source statements that contradict every claim. For UNSUPPORTED, preserve the source's neutrality toward every claim: do not add support and do not add a denial or contradiction.
>
> Do not change the expected relation by changing facts. If a source phrase is ambiguous or cannot be rendered safely in the requested language profile, report the ambiguity instead of guessing. Return only the required structured output.

### 12.2 Target-claim translator instructions

> Translate the supplied atomic claims into the requested language profile. Preserve each proposition exactly, including subject, predicate, object, negation, modality, qualifiers, numbers, dates, units, conditions, and scope. Do not add explanatory detail. Keep each claim atomic. Return exactly one canonical target rendering per claim ID and a structured proposition card. These canonical claim strings will be reused unchanged across all three passage variants.

### 12.3 Claim-aware window translator instructions

> Translate only `translatable_source_text`. Use adjacent context only to resolve references and terminology; it is read-only and must not be emitted. The target claim set and relation obligations are guardrails. Do not copy claim text into the passage unless the source passage itself says the same thing. Do not infer missing facts. Preserve every source sentence's meaning and sentence ID. Report any phrase that cannot be rendered without altering a claim relationship.

### 12.4 Surface-realization instructions

> Render the supplied semantic translation in the requested script and code-switch profile. Preserve the exact proposition of each sentence. Do not add, remove, weaken, strengthen, or infer factual content. Do not change who did what, when, where, how much, under what condition, or with what degree of certainty. The expected relation to every fixed claim must remain unchanged. Code-switch naturally, but semantic fidelity outranks stylistic fluency.

### 12.5 Reviewer instructions

> You are a separate evaluator, not the translator. Do not trust the translator's self-check. Compare the English source sentence(s), target translation, canonical target claims, and relation obligations. Determine whether the target sentence preserves the source meaning and whether it preserves the required evidence relation. Check every claim independently. Return structured findings with target/source sentence IDs and claim IDs. Do not repair the text in this call.

### 12.6 Required structured reviewer output

```json
{
  "status": "PASS | FAIL | AMBIGUOUS",
  "window_id": "window_0003",
  "sentence_findings": [
    {
      "source_sentence_id": "sentence_000021",
      "target_sentence_id": "sentence_000021",
      "semantic_fidelity": "PASS | FAIL | AMBIGUOUS",
      "defect_types": [],
      "critical_elements_checked": [],
      "notes": "concise finding"
    }
  ],
  "claim_findings": [
    {
      "claim_id": "claim_001",
      "expected_relation": "UNSUPPORTED",
      "observed_relation": "UNSUPPORTED | SUPPORTED | CONTRADICTED | AMBIGUOUS",
      "status": "PASS | FAIL | AMBIGUOUS",
      "evidence_sentence_ids": [],
      "defect_description": null
    }
  ],
  "number_date_unit_check": "PASS | FAIL | AMBIGUOUS",
  "entity_and_relation_check": "PASS | FAIL | AMBIGUOUS",
  "omission_or_addition_check": "PASS | FAIL | AMBIGUOUS",
  "recommended_repair_scope": []
}
```

Do not request chain-of-thought in the reviewer output. Evidence spans and concise defect explanations are sufficient.

---

## 13. Semantic validation and quality gates

Validation must be layered. A successful translation call is not a successful dataset item.

### 13.1 Gate A — source-family integrity

Before translation:

- all expected variants exist;
- every variant contains the same claim IDs;
- the source family passes its strict English all-claims relation matrix;
- claim IDs and evidence anchors resolve;
- the source text and split assignment are present;
- no source fields are silently changed by the extension.

### 13.2 Gate B — claim translation integrity

For every target claim:

- proposition preserved;
- subject, predicate, object, and attribution preserved;
- polarity and modality preserved;
- dates, quantities, units, ranges, and comparisons preserved;
- conditions and temporal/spatial scope preserved;
- claim remains atomic;
- target wording is natural and unambiguous in the target profile;
- same canonical target claim is used in all three variants.

### 13.3 Gate C — window integrity

For every window:

- all source sentence IDs are represented exactly once in assembled output;
- no sentence is omitted or duplicated;
- read-only overlap is not emitted twice;
- sentence ordering is preserved;
- output script/profile is followed;
- no unsupported explanatory content is added;
- key entities, relations, negation, numbers, dates, and units are preserved;
- reviewer finds semantic fidelity acceptable;
- expected claim relations are not altered.

### 13.4 Gate D — claim relation preservation

For every claim in every variant, the reviewer must assign one of:

- `SUPPORTED`;
- `CONTRADICTED`;
- `UNSUPPORTED`;
- `AMBIGUOUS`.

The expected observed relation must match the source family label for every claim. A single mismatch or ambiguity fails the variant and therefore blocks family acceptance.

Do not accept based solely on sentiment, keyword overlap, or the presence/absence of a claim's exact words. Evaluate semantic entailment, contradiction, and neutrality.

### 13.5 Gate E — target-language quality

Check:

- grammaticality and readability;
- naturalness for the selected locale;
- natural code-switch behaviour, where applicable;
- stable script and romanization;
- consistent terminology;
- preserved tone and register;
- no machine-translation-like word substitution that makes the passage unnatural;
- no awkward or inconsistent mixing of Bengali and English;
- no unintended ambiguity caused by transliteration or homographs.

### 13.6 Gate F — full-family consistency

Check the complete target triad as a family:

- same fixed target claim set across all variants;
- SUPPORTED supports all claims;
- CONTRADICTED contradicts all claims;
- UNSUPPORTED neither supports nor contradicts any claim;
- no information leaks from one variant into another during generation;
- consistent rendering of shared entities and terminology;
- no accidental changes to unrelated parts of the passage;
- target family is aligned to the exact English source family version.

### 13.7 Deterministic checks

Implement deterministic checks wherever practical:

- source/target sentence ID inventory;
- source and target sentence counts;
- missing or duplicated IDs;
- Unicode script validation;
- number/date/unit extraction and value comparison;
- acronym and named-entity consistency where exact matching is safe;
- known glossary spelling consistency;
- claim ID set equality across variant exports;
- variant label set equality;
- checksum of immutable English source fields;
- source split inheritance;
- JSON schema validation.

Do not over-trust string-level checks for names and numbers because localization may legitimately change digit style, inflection, spacing, punctuation, or script. Normalize values before comparing; retain original text for audit.

### 13.8 Independent review limitation

The translator and reviewer use the same DeepSeek model family because the project is DeepSeek-only. A separate prompt is useful but does not make the reviewer statistically independent. Compensate through deterministic checks, strict contracts, diverse test cases, blind review prompts, and bilingual human audits. Never describe same-model review as fully independent ground truth.

### 13.9 Human bilingual audit

Create a review interface or export that shows, side by side:

- English source variant;
- target-language passage;
- canonical English claims;
- canonical target-language claims;
- expected relation for each claim;
- reviewer findings and exact sentence anchors.

Human auditors should be fluent in the target language/profile. Sample across every profile, all three labels, short and long passages, different genres, and all important relation types. Auditors should specifically check whether code-mix or transliteration changed evidence relations.

Start with a pilot of at least 100 source families per target profile, balanced across the three labels. Human-audit a stratified sample and all model-flagged cases. Set the production audit rate based on observed error rates and risk; do not reduce it to zero merely because DeepSeek's reviewer passes.

---

## 14. Common failure modes to actively prevent

### 14.1 Unsupported becomes supported

A translator may know the answer from pretraining or infer it from surrounding context and add it to the passage. Prevent this by explicitly identifying the target claims and requiring neutrality for every one. Do not allow explanatory additions or fact completion.

### 14.2 Unsupported becomes contradicted

A translator may insert a denial to make the omission clearer. This is wrong. The target passage must remain neutral, not state that the claim is false.

### 14.3 Contradicted becomes supported

Names, dates, agent/object relationships, numerals, or negation can flip during translation, transliteration, or code-mix. Track these as explicit claim-bearing elements and review them sentence by sentence.

### 14.4 Supported becomes weaker or ambiguous

A Bengali translation may omit a qualifier, attribution, time expression, or causal connector. Do not accept a broad paraphrase if it no longer establishes the exact claim.

### 14.5 Cross-variant contamination

The model may see a supported fact while translating the unsupported variant and accidentally import it. Keep each variant's source text isolated in translation calls. Pass only the shared claim constraints and glossary.

### 14.6 Naturalization adds facts

A style-editing pass may explain a proper noun, add a common-sense detail, or resolve an omitted fact. The surface realization pass must receive the same claim constraints and be reviewed separately.

### 14.7 Transliteration changes identity

Different spellings can make two entities look identical or make one entity appear to be another. Maintain stable family-level entity IDs, canonical spellings, and aliases. Flag ambiguous collisions.

### 14.8 Mechanical code-mix

Do not generate code-mix by random word substitution or fixed word ratios. The result must follow the selected syntax profile and preserve the proposition.

### 14.9 Window seams

Independent windows can create inconsistent names, pronouns, tense, and terminology. Use read-only adjacent context, a family glossary, stable sentence IDs, and one cross-window continuity pass.

### 14.10 Over-editing during repair

Do not rewrite a whole passage to fix a single phrase. Repairs must be localized and bounded. If the relation cannot be preserved without a substantial rewrite, quarantine the family/profile rather than silently changing the source meaning.

---

## 15. Data model and lineage

Extend the existing family schema instead of duplicating it. The following is a logical schema; adapt field names to the repository's established conventions.

### 15.1 Multilingual extension object

```json
{
  "multilingual_extension": {
    "extension_version": "1.0.0",
    "source_family_id": "family_000001",
    "source_dataset_version": "english_dataset_vX",
    "source_family_checksum": "sha256:...",
    "source_split": "train",
    "target_profiles": {
      "benglish_latn": {
        "profile_version": "1.0",
        "locale": "bn-IN",
        "script_policy": "Latin",
        "profile_config_hash": "sha256:...",
        "canonical_target_claims": [
          {
            "claim_id": "claim_001",
            "text": "...",
            "semantic_card": {},
            "glossary_refs": [],
            "review_status": "PASS"
          }
        ],
        "family_glossary": [],
        "variant_translations": {
          "SUPPORTED": {
            "text": "...",
            "sentences": [],
            "windows": [],
            "claim_relation_results": [],
            "review_status": "PASS"
          },
          "CONTRADICTED": {
            "text": "...",
            "sentences": [],
            "windows": [],
            "claim_relation_results": [],
            "review_status": "PASS"
          },
          "UNSUPPORTED": {
            "text": "...",
            "sentences": [],
            "windows": [],
            "claim_relation_results": [],
            "review_status": "PASS"
          }
        },
        "family_validation": {},
        "status": "ACCEPTED"
      }
    }
  }
}
```

### 15.2 Sentence record

```json
{
  "sentence_id": "sentence_000021",
  "source_sentence_id": "sentence_000021",
  "source_text": "...",
  "target_text": "...",
  "paragraph_id": "paragraph_0004",
  "window_id": "window_0003",
  "claim_anchor_ids": ["claim_001"],
  "glossary_refs": ["entity_004"],
  "translation_status": "ACCEPTED",
  "review_findings": []
}
```

A translated sentence may be split into multiple target sentences or combine adjacent short sentences only when necessary for naturalness and when alignment remains explicit. Prefer one source sentence to one target sentence where practical. Do not lose the ability to trace target text back to source spans.

### 15.3 Window record

```json
{
  "window_id": "window_0003",
  "source_sentence_ids": ["sentence_000021", "sentence_000022"],
  "target_sentence_ids": ["sentence_000021", "sentence_000022"],
  "source_text_hash": "sha256:...",
  "target_text_hash": "sha256:...",
  "prompt_version": "window_translation_v1",
  "model_id": "deepseek-flash",
  "thinking_mode": "off",
  "attempt_count": 1,
  "review_status": "PASS",
  "repair_history": []
}
```

### 15.4 Claim relation result

```json
{
  "claim_id": "claim_001",
  "expected_relation": "UNSUPPORTED",
  "observed_relation": "UNSUPPORTED",
  "review_status": "PASS",
  "target_evidence_sentence_ids": [],
  "target_contradiction_sentence_ids": [],
  "neutrality_notes": "No supporting or contradicting assertion was found."
}
```

For `UNSUPPORTED`, both evidence and contradiction sentence lists should normally be empty. The reviewer may cite surrounding sentences as context for a neutrality finding, but must not invent a supporting or contradicting span.

### 15.5 Required lineage and version fields

At minimum store:

- `source_family_id` / `passage_family_id`;
- `source_dataset_version`;
- `source_family_checksum`;
- `target_profile_id` and profile version;
- extension and schema version;
- source split/group ID, inherited without change;
- canonical target claim version/hash;
- glossary version/hash;
- source sentence/window IDs;
- prompt template versions and hashes;
- DeepSeek model ID, API endpoint/version where available, thinking mode, request timestamp;
- generation/review attempt IDs;
- validation results and reviewer output;
- repair history;
- human audit result, when present;
- final status and rejection/quarantine reason.

### 15.6 Immutable source and versioning

Never overwrite English fields. A target retranslation creates a new extension version. Keep prior target versions for reproducibility. If the source English family changes, its checksum changes and all target translations based on the old checksum become stale; require explicit retranslation rather than silently mixing source versions.

---

## 16. Split and leakage policy

Reuse the existing family-level split assignment. Do not independently random-split translated passages.

All of the following must inherit the same source family split/group:

- English source passage family;
- its three English variants;
- target-language claim set;
- all target-language variants;
- all script/code-mix realizations of the same family;
- all revisions and alternate renderings derived from that family.

Do not place an English family in train and its Bengali or romanized version in test. The multilingual extension is a derived view of the same underlying family and must remain grouped.

Do not alter the prior dataset's split assignment during translation. Record the inherited split explicitly and test it during export.

---

## 17. Orchestration, caching, failures, and cost controls

### 17.1 Durable job structure

Use durable jobs at these levels:

- one job per source family/profile;
- one claim-translation stage per family/profile;
- one glossary/plan stage per family/profile;
- one job per variant/window;
- one assembly/continuity job per variant;
- one final triad-review job per family/profile.

A process restart must resume from the last accepted checkpoint. Do not repeat completed paid API calls unnecessarily.

### 17.2 Idempotency and caching

Use an idempotency key derived from:

```text
source_family_checksum
+ target_profile_config_hash
+ source_variant_label
+ source_window_hash
+ target_claim_set_hash
+ glossary_hash
+ prompt_template_hash
+ model_id
+ generation_settings_hash
```

If any of these inputs change, the cache key must change. Never return a cached result generated with a different target profile, claim ledger, source version, model identifier, or prompt version.

### 17.3 Rate limits and retries

- Respect API rate limits and configured concurrency.
- Use bounded exponential backoff for retryable failures.
- Distinguish transient API errors from malformed model output and semantic-review failures.
- Do not endlessly retry a semantic failure with the same unchanged prompt.
- Record token usage, input/output size, latency, estimated cost, and retry count.
- Allow off-peak scheduling as an optional operational optimization, but do not make correctness depend on it.

### 17.4 Cost control

- Use non-thinking mode for routine translation where quality permits.
- Use thinking mode selectively for planning, ambiguity resolution, and difficult review/repair.
- Reuse cached family plans, target claims, glossaries, and accepted windows.
- Avoid sending the entire long passage when only one window needs translation.
- Send the complete small claim ledger to each window; it is a core correctness constraint and should not be dropped to save tokens.
- Track cost per family, per profile, per variant, and per accepted target word/token.

Do not trade away claim awareness by removing the claim ledger from prompts. Optimize elsewhere first.

### 17.5 Failure states

Use explicit statuses, for example:

- `PENDING`;
- `SOURCE_PREFLIGHT_FAILED`;
- `CLAIM_LEDGER_PENDING`;
- `CLAIM_TRANSLATION_FAILED`;
- `CLAIM_TRANSLATION_AMBIGUOUS`;
- `GLOSSARY_PENDING`;
- `TRANSLATION_PENDING`;
- `WINDOW_TRANSLATION_FAILED`;
- `WINDOW_REVIEW_FAILED`;
- `NEEDS_HUMAN_REVIEW`;
- `FAMILY_RELATION_FAILED`;
- `FAMILY_QUALITY_FAILED`;
- `ACCEPTED`;
- `QUARANTINED`.

Do not use a generic `FAILED` status for all semantic and operational failures. Keep the failure reason and failed stage explicit.

---

## 18. Evaluation plan

### 18.1 Pilot design

Start with 100 accepted English source families per target profile, stratified across:

- SUPPORTED, CONTRADICTED, UNSUPPORTED;
- short, medium, and long passages;
- different genres and writing styles;
- different claim structures;
- names, dates, numbers, units, negation, modality, comparison, attribution, and conditional statements;
- simple and difficult code-switch cases.

Do not select only easy, short, factual passages. Long and linguistically awkward passages are part of the intended operating domain.

### 18.2 Core metrics

Track at least:

1. **Claim translation fidelity** — fraction of target claims judged proposition-equivalent to their English originals.
2. **Variant relation preservation** — fraction of claim/variant pairs whose target relation matches the source relation.
3. **Strict family pass rate** — fraction of families for which every claim passes in all three variants.
4. **Unsupported neutrality preservation** — fraction of unsupported claim/variant pairs that remain neither supported nor contradicted.
5. **Contradiction preservation** — fraction of contradicted claim/variant pairs that remain explicitly contradicted.
6. **Support preservation** — fraction of supported claim/variant pairs that remain established.
7. **Semantic addition rate** — rate of new factual propositions introduced by translation or naturalization.
8. **Semantic deletion rate** — rate of source propositions omitted or weakened.
9. **Named-entity consistency** — consistency of identity and spelling across windows and variants.
10. **Qualifier preservation** — preservation of numbers, dates, units, polarity, modality, conditions, comparisons, and scope.
11. **Window alignment completeness** — fraction of source sentence IDs represented exactly once.
12. **Naturalness score** — bilingual human rating of fluency and appropriateness.
13. **Code-mix naturalness** — bilingual human rating for the two mixed-language profiles.
14. **Latency and cost** — per window, variant, family, and profile.
15. **Repair rate** — proportion of windows/families needing repairs and average attempts.
16. **Quarantine rate** — proportion of source families rejected for profile-specific ambiguity or relation failure.

BLEU, chrF, or similar surface metrics may be reported as secondary diagnostics. They are not sufficient measures of claim preservation or code-mix quality.

### 18.3 Acceptance thresholds

For the controlled pilot, require:

- 100% of accepted families pass the strict all-claims relation matrix under the automated reviewer;
- 100% of accepted families use the same canonical target claim set across their three variants;
- 100% of accepted families preserve source-family split assignment;
- 100% of accepted families have complete sentence/window alignment metadata;
- zero known semantic additions or deletions in the audited accepted sample;
- bilingual human review confirms that target text is understandable and natural enough for the selected profile.

These are acceptance conditions for each accepted record, not an instruction to force every attempted record to pass. Reject or quarantine difficult cases rather than relaxing the invariant.

---

## 19. Testing requirements

### 19.1 Unit tests

Test:

- source-family loading and immutability;
- claim ledger construction and serialization;
- target claim ID preservation;
- profile configuration validation;
- Bengali Unicode and Latin-script handling;
- romanization consistency checks;
- paragraph/sentence segmentation;
- window construction and context overlap;
- deterministic sentence assembly;
- JSON schema validation;
- number/date/unit normalization;
- idempotency and caching;
- retry/resume behaviour;
- inherited split assignment;
- source checksum/version handling.

### 19.2 Semantic contract tests

Create controlled fixtures in which the claim relationship depends on:

- named entity identity;
- subject/object reversal;
- attribution;
- negation;
- dates and temporal order;
- numeric values and units;
- greater-than/less-than comparisons;
- modality (`may`, `must`, `did`, `will`);
- conditional clauses;
- causal language;
- location and scope;
- explicit omission/neutrality.

For each fixture, create all three source variants and verify that every target profile retains the intended relation.

### 19.3 Code-mix and script tests

Include:

- Bengali-native prose;
- Bengali-led romanized prose;
- Bengali-led code-mix with English technical vocabulary;
- English-led code-mix with Bengali insertions;
- code-mix containing names, acronyms, numbers, dates, negation, and modal verbs;
- repeated entities across distant windows;
- Bengali words with multiple plausible romanizations;
- long passages with paragraph breaks and quotations.

Test for script-policy compliance without rejecting normal embedded English names or technical terms.

### 19.4 Long-window tests

Use long families that require multiple windows. Verify:

- no sentence loss;
- no duplicated overlap;
- no reordered sentence;
- no pronoun/antecedent drift;
- consistent named-entity transliteration;
- consistent claim terminology;
- correct relation preservation even when the evidence anchor occurs in a different window from contextual references.

### 19.5 Negative tests

The following must be rejected:

- translator inserts an answer into UNSUPPORTED;
- translator changes UNSUPPORTED into an explicit denial;
- translator changes a CONTRADICTED entity into the claim entity;
- translator flips negation;
- translator changes a date/number/unit;
- translator drops a qualifier that is required to support the claim;
- code-mix inserts a missing fact;
- romanization makes two distinct names ambiguous;
- target claim is rephrased differently across the three variants;
- one target window omits a source sentence;
- a target family receives a new split assignment.

### 19.6 End-to-end tests

Run the complete pipeline on a small fixture dataset and verify that:

1. the English parent records remain byte-for-byte or checksum-identical in immutable fields;
2. target claims are generated once per family/profile;
3. all three variants use the same target claims;
4. all windows are translated and assembled in order;
5. the strict relation matrix passes for every accepted target family;
6. failed families are quarantined with useful reports;
7. a restarted process resumes without duplicate paid calls;
8. exports include lineage and inherited split metadata.

---

## 20. CLI and operational interface

Integrate with the existing Hermes CLI conventions. Do not create a parallel command structure if the previous pipeline already has one.

Provide equivalent commands or tasks for:

```text
multilingual inspect --family <family_id>
multilingual preflight --input <dataset>
multilingual plan --profile <profile_id>
multilingual translate --profile <profile_id> --limit <n>
multilingual translate-family --family <family_id> --profile <profile_id>
multilingual resume --job <job_id>
multilingual review --family <family_id> --profile <profile_id>
multilingual audit-report --profile <profile_id>
multilingual export --profile <profile_id> --split <split>
```

Required options should include:

- `--profile`;
- `--limit`;
- `--family`;
- `--resume`;
- `--force-new-version`;
- `--max-repairs`;
- `--concurrency`;
- `--dry-run`;
- `--audit-sample`.

A dry run must show source-family eligibility, profile settings, claim counts, estimated window counts, and planned API stages without making translation API calls.

---

## 21. Suggested implementation milestones

### Milestone 0 — Repository and schema inspection

- Inspect the existing English pipeline, family schema, claim IDs, evidence anchors, split handling, model wrapper, storage, CLI, and tests.
- Identify reusable utilities for sentence segmentation, HNSW/novelty retrieval, structured outputs, and job persistence.
- Write a short implementation map before changing the code.
- Do not duplicate functionality already implemented.

### Milestone 1 — Source preflight and claim ledger

- Load accepted English families.
- Verify the source tri-state matrix.
- Build structured claim semantic cards and per-variant obligations.
- Add unit and semantic tests.
- Do not translate passages yet.

### Milestone 2 — Profiles and canonical target claims

- Implement the profile configuration model.
- Implement DeepSeek-only target claim translation.
- Add independent claim review and ambiguity handling.
- Freeze one canonical target claim set per family/profile.

### Milestone 3 — Family glossary and short-passage translation

- Generate the family glossary and translation plan.
- Implement semantic translation and surface realization.
- Translate short windows for one profile first (`bn_in_native`).
- Implement sentence alignment and structured outputs.

### Milestone 4 — Claim-aware window review and bounded repair

- Implement the window-level ReAct loop.
- Add deterministic checks and separate DeepSeek reviewer prompts.
- Add localized repair with a maximum of two attempts by default.
- Add family-level triad review.

### Milestone 5 — Romanization and code-mix profiles

- Implement `bn_latn_romanized`.
- Implement `benglish_latn`.
- Implement `engali_mixed`.
- Add explicit script, locale, register, and code-switch controls.
- Test for semantic drift during surface realization.

### Milestone 6 — Long passages and production orchestration

- Add paragraph-aware window planning and read-only overlap context.
- Add continuity review, caching, resumability, rate limits, cost metrics, and job dashboards.
- Complete long-window and failure-recovery tests.

### Milestone 7 — Pilot audit and controlled rollout

- Run at least 100 families per profile, balanced across labels.
- Produce relation-preservation, semantic-fidelity, naturalness, cost, and repair reports.
- Conduct bilingual human audits.
- Fix systematic issues before processing the full English dataset.

---

## 22. Configuration requirements

Use configuration files/environment variables rather than scattering constants through code.

Example starting configuration:

```yaml
multilingual:
  enabled: true
  source_dataset: existing_english_tri_state
  preserve_source_immutable: true
  inherit_source_split: true
  profiles:
    - bn_in_native
    - bn_latn_romanized
    - benglish_latn
    - engali_mixed

model:
  provider: deepseek
  base_url: https://api.deepseek.com
  model: deepseek-flash
  translation_thinking_mode: off
  review_thinking_mode: on
  timeout_seconds: 120
  max_retries: 5
  no_fallback_provider: true

translation:
  semantic_pass_enabled: true
  surface_realization_enabled: true
  preserve_sentence_order: true
  preserve_sentence_ids: true
  allow_sentence_merge: false
  allow_sentence_split: true
  add_explanatory_content: false
  use_world_knowledge: false
  translate_claims_once_per_profile: true
  pass_claim_ledger_to_every_window: true
  pass_other_variant_text_to_translator: false

windowing:
  strategy: paragraph_sentence_aware
  target_source_words_min: 250
  target_source_words_max: 500
  include_previous_context: true
  include_next_context: true
  overlap_is_read_only: true
  adaptive_to_token_budget: true

agent:
  max_repairs_per_window: 2
  max_family_repair_rounds: 1
  reviewer_separate_call: true
  reviewer_sees_translator_self_check: false
  quarantine_on_ambiguous_relation: true

quality:
  require_all_claims_to_pass: true
  reject_mixed_relations: true
  reject_semantic_additions: true
  reject_semantic_deletions: true
  require_human_audit_for_pilot: true

storage:
  preserve_prior_translation_versions: true
  store_prompt_hashes: true
  store_source_checksums: true
  store_window_alignment: true
  store_model_metadata: true
```

All profile-specific values must live in versioned profile files. The values above are defaults to start with and should be tuned from the pilot, not treated as universal constants.

---

## 23. Observability and reporting

Every family/profile job should produce a compact report containing:

- source family ID and checksum;
- target profile and profile version;
- source label counts and claim count;
- number of source sentences, windows, and target sentences;
- canonical target claims and review status;
- glossary status;
- per-window translation/review status;
- per-claim expected versus observed relation for each variant;
- number/date/unit/entity checks;
- repair attempts and repair scopes;
- language naturalness/code-mix review status;
- API calls, token usage, latency, and estimated cost;
- final accepted/quarantined status and reason;
- inherited split assignment.

Provide aggregate reports by profile, label, passage length, genre, claim type, and error type. This should make it possible to identify, for example, whether romanized Bengali causes more entity-identity errors or whether unsupported passages are disproportionately turned into supported passages during code-mix naturalization.

---

## 24. Security, privacy, and responsible handling

- Keep the DeepSeek API key in environment variables or a secret manager; never commit it.
- Do not log API keys or sensitive request headers.
- Send only the data needed for the translation job.
- Preserve external-source licensing/provenance metadata inherited from the English dataset.
- Do not claim that synthetic or fictional passages are real-world facts.
- Retain source and target lineage so that errors can be traced and corrected.
- Provide a way to delete or reprocess target-language derivatives without deleting the immutable English source family.

---

## 25. Expected Hermes implementation behaviour

Hermes must act as an engineering agent implementing a reliable data pipeline, not as an unconstrained writing assistant.

Before coding:

1. inspect the repository and the actual English pipeline implementation;
2. find the existing schema and reuse its field names and abstractions;
3. identify how the current pipeline stores claims, variants, evidence anchors, splits, and job state;
4. identify the existing DeepSeek client wrapper or add one reusable wrapper;
5. map each milestone to files/modules/tests;
6. call out any mismatch between this objective and the actual repository rather than silently inventing a schema.

During implementation:

- keep modules small and responsibilities explicit;
- make every generation stage restartable;
- validate every model output against a schema;
- log concise structured events;
- write tests before declaring a stage complete;
- avoid destructive changes to the English dataset;
- keep model calls centralized behind a configurable DeepSeek client;
- maintain prompt templates as versioned assets;
- ensure every window receives the claim ledger;
- keep translator and reviewer roles separate at the prompt/task level;
- make repairs bounded and localized;
- expose explicit quarantine reasons;
- never silently fall back to another LLM or translation provider.

When implementation details are ambiguous, prefer the option that preserves the source English family, canonical claims, and strict tri-state relation. If a target-language rendering cannot safely preserve the relation, reject that family/profile rather than weaken the dataset contract.

Do not claim success based only on code compilation or a handful of fluent translations. Run the semantic contract tests, long-window tests, end-to-end tests, pilot metrics, and bilingual audit workflow.

---

## 26. Definition of done

The multilingual extension is complete only when:

1. It loads and validates the existing English tri-state dataset without mutating it.
2. It builds a claim semantic ledger before translating passage text.
3. It translates each fixed claim set exactly once per target profile and reuses the same target claims across all three variants.
4. Every translation window receives the complete claim ledger and the explicit expected relation for its variant.
5. Bengali translation, romanization, transliteration, and code-mix realization all use DeepSeek only.
6. Long passages are translated through sentence/paragraph-aware windows with stable alignment and no missing/duplicated text.
7. Each window receives structural and claim-aware semantic review.
8. Repairs are localized, bounded, auditable, and do not alter the English source.
9. The final target family passes the strict all-claims relation matrix: all supported, all contradicted, and all neutral respectively.
10. The target text is reviewed for naturalness and target-profile compliance.
11. The system records prompts, model settings, checksums, alignments, lineage, cost, repairs, and validation results.
12. The target family inherits the source family's split assignment.
13. Jobs resume safely after interruption without unnecessary repeated API calls.
14. Pilot evaluation and bilingual human audit have been completed for every profile.
15. Failed or ambiguous families are quarantined with actionable reports rather than silently accepted.

---

## 27. Non-negotiable principles — quick reference

1. **English source families are immutable.** This extension creates versioned target-language derivatives only.
2. **Claims are translated before passages.** The claim set is the semantic guardrail for every later operation.
3. **Every window is claim-aware.** Never translate a window without the full claim ledger and the expected relation.
4. **One canonical target claim set per profile/family.** Reuse it unchanged across all three variants.
5. **Preserve source meaning; do not manufacture evidence.** Relation preservation must come from faithful translation, not rewriting the facts.
6. **UNSUPPORTED means neither supported nor contradicted.** Never turn omission into denial.
7. **CONTRADICTED must stay contradicted.** Preserve the exact conflicting entity, value, relation, polarity, or qualifier.
8. **SUPPORTED must stay supported.** Do not weaken the evidence or drop a critical qualifier.
9. **DeepSeek only for language intelligence.** No alternate LLM or translation API fallback.
10. **Separate translation from review.** The reviewer is a distinct DeepSeek task and must not trust the translator's self-check.
11. **Use window-aware translation for long passages.** Preserve sentence IDs, context, order, and continuity.
12. **Code-mix naturally, not mechanically.** Naturalness never outranks semantic fidelity.
13. **Repair locally and with a hard limit.** Quarantine unresolved cases.
14. **Keep family lineage and split assignments.** English and all multilingual descendants remain in the same split group.
15. **Audit bilingual quality.** Same-model review is not independent ground truth; retain human auditing.
