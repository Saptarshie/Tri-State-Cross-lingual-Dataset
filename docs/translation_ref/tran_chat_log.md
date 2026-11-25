<q>
now, assuming that the earlier english-only tristate generation is done, ....we need to now make it cross-lingual, Bengali English , ...may be mixed (benglish , Engali), ....since the generated passages can be long ...one off translation request might give incorrect results , so we need a window by window translation (like surgical edits .... the react agent will read it window by window and translate it.... , ....also let me know if the is a better approach ... (and currently i am using deepseek v4.1 flash for all these , ... can i do this better way? , ...is there any free google translate api [in that case it wont support mix language though like, "Dress ta dekhte fucking awesome, wonna have it?"])...
</q>

# **Cross-lingual expansion pipeline: English → Bengali → Benglish / Engali**

I would **not** simply run your existing English passages through a translation API, nor would I let the ReAct agent independently translate each chunk without global context.

I recommend a hybrid architecture:

**Structure-aware windowed translation + semantic-preservation constraints + claim-set invariance checks + code-switch adaptation.**

The most important requirement is that your three-state relationship must survive translation.

You have already created English passage families:

\\[ F\_{en}=(P_S,P_C,P_U,\mathcal C) \\]

where \\(\mathcal C\\) is the fixed claim set.

You now want corresponding language variants:

\\[ F\_{bn},\quad F\_{benglish},\quad F\_{engali} \\]

All of them must preserve the same underlying factual relationships.

## **1. First, define exactly what you mean by the language variants**

I recommend explicitly distinguishing script from language composition.

| Dataset variant     | Definition                                                                      | Example                                                 |
| ------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------- |
| English             | English language, Latin script                                                  | The dress looks absolutely awesome.                     |
| Bengali             | Bengali language, Bengali script                                                | পোশাকটা দেখতে দারুণ সুন্দর।                             |
| Benglish / Banglish | Bengali-led speech, predominantly Latin script, with natural English insertions | Dress ta dekhte fucking awesome, ota nite iccha korche. |
| Engali              | English-led sentence structure with Bengali words or phrases in Bengali script  | The dress টা দেখতে really awesome লাগছে.                |

The terms Benglish and Engali are not universally standardized linguistic categories. These are proposed operational definitions for your dataset.

I would also store the following metadata for every record:

```
{
  "language_profile": "BENGLISH",
  "base_language": "bn",
  "script": "latin",
  "secondary_language": "en",
  "english_insertion_level": "moderate",
  "style": "conversational"
}
```

For Engali, use:

```
{
  "language_profile": "ENGALI",
  "base_language": "en",
  "script": "mixed",
  "secondary_language": "bn",
  "bengali_script_insertion_level": "moderate"
}
```

This allows you to control code-switching rather than asking a model to generate something vaguely bilingual.

# **2. The most important design choice: windowed translation with global context**

Your intuition about translating long passages window by window is correct.

But there is a subtle difference between ordinary window-based translation and the process you actually need.

Suppose the original passage contains 2,000 words.

A naive strategy:

```
Split into chunks
    |
    v
Translate chunk 1 independently
Translate chunk 2 independently
Translate chunk 3 independently
    |
    v
Concatenate
```

This can produce:

- Inconsistent translations of the same entity.
- Different terminology in different sections.
- Pronoun-reference errors.
- Incorrect interpretation of sentences that depend on previous paragraphs.
- Changes in the meaning of specific claims.
- Repeated or missing sentences at chunk boundaries.

What I recommend is **hierarchical, structure-aware translation with shared memory**.

## **Windowed translation architecture**

**Global passage-family context**

Original passage family, three-state semantics, complete claim set, terminology and entity glossary.

**Structure-aware segmentation**

Split into paragraphs, sections and sentence-aligned windows.

**ReAct Translation Agent**

Window 1: Read + translate + validate

Window 2: Read + translate + validate

Window 3: Read + translate + validate

Each window receives global context and a limited amount of neighbouring context.

**Translation memory**

Maintain consistent terminology, named entities, sentence mappings and previously translated windows.

**Whole-passage consistency check**

Reconstruct the complete passage and verify its factual and linguistic relationships.

## **2.1 Do not use arbitrary fixed token windows**

I would use semantic boundaries.

For example:

1. Split the passage into sections.
2. Split sections into paragraphs.
3. Split paragraphs into sentence groups.
4. Form windows containing approximately 250–500 source words, adjusting for paragraph boundaries and sentence completeness.

This is an initial heuristic, not a hard limit.

For every window, also provide:

- The preceding sentence or paragraph summary.
- The following sentence or paragraph summary, where available.
- The global glossary.
- The complete claim-set summary.
- The target translation style.

The neighbouring text is context only. The agent must translate only the assigned window.

This avoids the common issue where the model translates isolated sentences without understanding what pronouns and references mean.

## **2.2 Preserve sentence-level alignment**

Give each source sentence a stable ID.

For example:

```
{
  "window_id": "W001",
  "sentences": [
    {
      "sentence_id": "S001",
      "text": "Python was developed by Guido van Rossum."
    },
    {
      "sentence_id": "S002",
      "text": "Its first version was released in 1991."
    },
    {
      "sentence_id": "S003",
      "text": "The language emphasizes readability."
    }
  ]
}
```

The translated output should retain these IDs:

```
{
  "window_id": "W001",
  "translations": [
    {
      "sentence_id": "S001",
      "translated_text": "পাইথন তৈরি করেছিলেন গুইডো ভ্যান রসম।"
    },
    {
      "sentence_id": "S002",
      "translated_text": "এর প্রথম সংস্করণ প্রকাশিত হয় ১৯৯১ সালে।"
    },
    {
      "sentence_id": "S003",
      "translated_text": "ভাষাটিতে কোডের পাঠযোগ্যতার ওপর গুরুত্ব দেওয়া হয়েছে।"
    }
  ]
}
```

This makes it possible to identify precisely which sentence introduced a semantic error.

It also facilitates selective regeneration. You don't have to translate the entire passage again because one window failed validation.

## **2.3 Maintain a global translation memory**

Create a translation glossary before starting the window loop.

For example:

| English expression | Bengali rendering    | Treatment                  |
| ------------------ | -------------------- | -------------------------- |
| Python             | পাইথন                | Consistent transliteration |
| Guido van Rossum   | গুইডো ভ্যান রসম      | Preserve identity          |
| Machine learning   | মেশিন লার্নিং        | Preferred terminology      |
| Neural network     | নিউরাল নেটওয়ার্ক    | Preferred terminology      |
| Gradient descent   | গ্রেডিয়েন্ট ডিসেন্ট | Preferred terminology      |
| API                | API                  | Preserve acronym           |

The LLM should be allowed to use more natural contextual forms, but it should not arbitrarily change technical terms throughout one passage.

You should also preserve:

- Entity IDs.
- Numbers.
- Dates.
- Units.
- Negation.
- Causal relations.
- Subject-object relationships.
- Named entities.

# **3. A critical issue: your three variants must be translated differently from ordinary text**

This is something I would explicitly enforce in your Hermes implementation.

Remember, your English variants have deliberately different evidential properties.

A normal translation model might unintentionally correct them.

Consider:

**English Supported:**

> Python was developed by Guido van Rossum.

**English Contradicted:**

> Python was developed by James Gosling.

**English Unsupported:**

> Python is a high-level programming language used for automation and data science.

Now imagine a translator with strong pretrained knowledge of programming languages.

It sees:

> Python was developed by James Gosling.

It might "correct" the translation based on its understanding of the real-world fact.

That would destroy your dataset.

Likewise, when translating Missing Evidence, it might add a previously omitted fact for grammatical or explanatory completeness.

These are unacceptable.

I would add a strict translation invariant:

Non-negotiable invariant

**Translate the supplied text, not the world knowledge associated with the text.**

- Never correct intentionally false statements.
- Never restore information intentionally removed from a Missing passage.
- Never add supporting details merely to make a passage more informative.
- Never alter numerical, temporal or relational values.
- Never weaken an explicit contradiction.
- Never convert an unsupported statement into an established statement.

The translator must behave as a meaning-preserving transformation system, not a fact-checking or rewriting system.

# **4. Translate the entire passage family as one logical unit**

There is one more improvement I would make to the windowing approach.

Don't process the three variants as three unrelated translation jobs.

Process the entire passage family as a single coordinated translation task.

Suppose you have:

```
FAMILY_001
    |
    +-- Claim set C = {c1, c2, c3}
    |
    +-- Supported passage
    |      W1, W2, W3, W4
    |
    +-- Contradicted passage
    |      W1, W2, W3, W4
    |
    +-- Unsupported passage
           W1, W2, W3, W4
```

The agent should first translate the claim set and establish a shared bilingual glossary.

Then it should translate all three passages, window by window, while preserving their original relationships.

## **Recommended execution order**

| Step | Task                                                                      |
| ---- | ------------------------------------------------------------------------- |
| 1    | Read the complete original passage family and claim set.                  |
| 2    | Create a terminology and entity glossary.                                 |
| 3    | Translate the question and claim set.                                     |
| 4    | Verify that the translated claims preserve the English claims' semantics. |
| 5    | Translate Supported passage windows.                                      |
| 6    | Translate Contradicted passage windows.                                   |
| 7    | Translate Unsupported passage windows.                                    |
| 8    | Run family-level semantic verification across all three variants.         |
| 9    | Repair individual failed windows, followed by family-level revalidation.  |

Why translate the claims first?

Because they are the semantic anchors for all three passages.

Suppose the original claim is:

> Company A acquired Company B in 2021.

Your Bengali translation of the claim must preserve:

- Company A as the buyer.
- Company B as the target.
- 2021 as the acquisition year.

If the translation accidentally reverses the entities, the downstream verifier will be trained on an incorrectly aligned claim.

## **4.1 Suggested ReAct translation-agent loop**

The agent should have bounded tools such as:

```
read_source_window(window_id)
read_neighbor_context(window_id)
read_global_glossary()
read_claim_set()
translate_window(window_id, target_profile)
check_sentence_alignment(window_id)
check_entity_consistency(window_id)
patch_translation(window_id, sentence_id)
commit_window(window_id)
```

The agent loop:

```
OBSERVE
  Read current window and neighbouring context.

PLAN
  Identify terminology, references and relevant claims.

TRANSLATE
  Translate only the designated window.

CHECK
  Verify every sentence against the original.

COMPARE
  Check terminology against previously translated windows.

PATCH
  Fix any semantic or linguistic inconsistencies.

COMMIT
  Save translation and alignment metadata.

NEXT
  Continue to the next window.
```

Do not allow it to repeatedly rewrite already validated windows unless a downstream consistency check identifies a concrete problem.

## **4.2 Prompt for the translation agent**

This is the core instruction I would give Hermes to use with DeepSeek or a translation model.

**Windowed translation system prompt**

Core prompt

```
You are a bilingual semantic-preservation
translation agent.

Your task is to translate a specified passage
window while preserving its exact factual and
semantic relationships.

GLOBAL CONTEXT:
{passage_family_summary}

ORIGINAL CLAIM SET:
{english_claims}

TRANSLATED CLAIM SET:
{target_claims}

GLOBAL GLOSSARY:
{glossary}

CURRENT PASSAGE VARIANT:
{variant_type}

CURRENT WINDOW:
{source_window}

PREVIOUS CONTEXT:
{previous_context}

NEXT CONTEXT:
{next_context}

TARGET PROFILE:
{target_language_profile}

STRICT REQUIREMENTS:

1. Translate the supplied window faithfully.
2. Preserve names, entities, relations, numbers,
   dates, units, negation and modality.
3. Do not fact-check or correct the source.
4. Preserve intentionally false statements.
5. Never reintroduce information absent from the
   original window or passage.
6. Never add explanatory facts.
7. Maintain terminology consistency using the
   global glossary.
8. Preserve the distinction between the original
   Supported, Contradicted and Unsupported
   variants.
9. Do not translate the neighbouring context.
   It is provided only for disambiguation.
10. Preserve sentence IDs and source alignment.

Output valid JSON only.
```

&#x20;Copy prompt

I would actually add a second, independent semantic-verification prompt rather than asking the translator to self-certify its output.

# **5. The most important validation: verify the tri-state relationship AFTER translation**

This is the part that makes your pipeline different from a conventional translation workflow.

For every family:

\\[ F\_{bn}=(P\_{S,bn},P\_{C,bn},P\_{U,bn},\mathcal C\_{bn}) \\]

You must check:

\\[ \forall c_i\in\mathcal C\_{bn} \\]

\\[ P\_{S,bn}\models c_i \\]

\\[ P\_{C,bn}\models\neg c_i \\]

\\[ P\_{U,bn}\not\models c_i \\]

Here, the last expression means that the passage does not establish the claim. It does not mean that the passage establishes its negation.

Use the original English fact graph, translated claim set and translated passage together during validation.

### **Validation matrix**

| Check                   | Supported | Contradicted                      | Unsupported                      |
| ----------------------- | --------- | --------------------------------- | -------------------------------- |
| All claims supported    | Must pass | Must fail                         | Must fail                        |
| All claims contradicted | Must fail | Must pass                         | Must fail                        |
| All claims neutral      | Must fail | Must fail                         | Must pass                        |
| Numerical meaning       | Preserve  | Preserve intended wrong values    | Preserve omissions               |
| Entity relations        | Preserve  | Preserve intended wrong relations | Do not restore omitted relations |

This should be an independent validator.

For an ambiguous translation, regenerate that window or mark the family for human review. Never automatically change the label to make the validator happy.

## **5.1 Add a round-trip consistency check**

You can also translate the Bengali result back into English and compare it with the original English passage.

But don't use round-trip translation as the primary validator.

It can introduce its own errors and hide some semantic changes.

Instead, use three signals:

1. Direct bilingual entailment/contradiction assessment.
2. Entity-relation and numerical consistency checking.
3. Optional back-translation for identifying suspicious changes.

Finally, run a human bilingual audit on a stratified sample.

# **6. Benglish and Engali should have their own adaptation pipeline**

This is where I would NOT rely on Google Translate or ordinary NMT alone.

Your example:

> Dress ta dekhte fucking awesome, wanna have it?

is not simply an English sentence translated into Bengali.

It contains:

- Bengali lexical content.
- Bengali grammatical structure.
- English adjectives.
- English intensifiers.
- English question construction.

This is code-switching, and the translation system needs to preserve or intentionally construct those choices.

## **6.1 My recommended approach: Bengali translation first, then code-switch adaptation**

For Benglish:

\\[ \text{English} \rightarrow \text{Natural Bengali} \rightarrow \text{Bengali-led Roman code-mixing} \\]

For Engali:

\\[ \text{English} \rightarrow \text{Natural Bengali} \rightarrow \text{English-led Bengali-script mixing} \\]

However, I would give the agent the original English passage and the verified Bengali translation simultaneously during the code-mix adaptation.

That way, it can preserve the source meaning while using the Bengali translation as a linguistic reference.

### **Example**

Original English:

> The new application provides an efficient way to manage financial transactions. Users can track their expenses and generate monthly reports.

Natural Bengali:

> নতুন অ্যাপ্লিকেশনটি আর্থিক লেনদেন পরিচালনার একটি কার্যকর উপায় প্রদান করে। ব্যবহারকারীরা নিজেদের খরচের হিসাব রাখতে পারেন এবং মাসিক রিপোর্ট তৈরি করতে পারেন।

Benglish:

> Notun application ta financial transactions manage korar ekta efficient way provide kore. Users ra nijeder expenses track korte pare aar monthly reports generate korte pare.

Engali:

> The নতুন application টা financial transactions manage করার একটা efficient way provide করে। Users রা নিজেদের expenses track করতে পারে এবং monthly reports generate করতে পারে।

These are illustrative code-mixed renderings, not claims that every Bengali speaker would naturally phrase them this way.

The important thing is that the underlying propositions remain unchanged.

## **6.2 Use explicit code-switch controls**

Don't just ask:

> Make this Banglish.

Instead, specify a target linguistic profile.

```
{
  "profile": "BENGLISH",
  "base_language": "Bengali",
  "script": "Latin",
  "code_switching": {
    "level": "moderate",
    "keep_english_technical_terms": true,
    "preserve_english_brand_names": true,
    "allow_english_adjectives": true,
    "allow_english_nouns": true,
    "preserve_bengali_grammar": true,
    "transliterate_bengali_words": true
  },
  "tone": "natural_conversational"
}
```

For Engali:

```
{
  "profile": "ENGALI",
  "base_language": "English",
  "script": "mixed",
  "code_switching": {
    "level": "moderate",
    "english_structure": true,
    "bengali_script_phrases": true,
    "retain_english_technical_terms": true
  },
  "tone": "natural_conversational"
}
```

You could create three mixing intensities:

- Light.
- Moderate.
- Heavy.

But don't enforce a fixed English/Bengali word ratio mechanically. That often produces unnatural output.

Use the ratio as a corpus-level target, not a sentence-level rule.

# **7. Which translation model should you use?**

Now to your question about DeepSeek V4.1 Flash and whether you can do better.

I checked the current official documentation and pricing as of November 25, 2026.

First, one thing: **DeepSeek V4.1 Flash is actually a very reasonable choice for your project. I would not replace it just because you're moving into Bengali. But I wouldn't use one LLM for every operation either.**

There are now several useful options.

## **7.1 DeepSeek V4.1 Flash — keep it as your primary agent model**

The current API name is `deepseek-flash`, serving DeepSeek-V4.1-Flash-1017.

Its documented specifications include:

| Property       | Value       |
| -------------- | ----------- |
| Context window | 1M tokens   |
| Maximum output | 384K tokens |
| Thinking mode  | Yes         |
| JSON output    | Yes         |
| Tool calling   | Yes         |
| Image input    | Yes         |

Official pricing per million tokens:&#x20;

[image](https://www.google.com/s2/favicons?domain=https://api-docs.deepseek.com&sz=32)

DeepSeek API Docs+1

| Usage             | Off-peak | Peak   |
| ----------------- | -------- | ------ |
| Input, cache miss | $0.15    | $0.30  |
| Input, cache hit  | $0.003   | $0.006 |
| Output            | $0.60    | $1.20  |

Peak pricing applies during specified weekday UTC periods; weekends and other off-peak periods cost half the peak rates.

[DeepSeek official API pricing](https://api-docs.deepseek.com/quick_start/pricing/?utm_source=chatgpt.com).

This is exceptionally inexpensive for an LLM that you also use for agentic workflows.

### **Where I would use it**

- Window translation when contextual adaptation is necessary.
- Claim-set translation.
- Bengali naturalness refinement.
- Benglish/Engali generation.
- Semantic preservation checks.
- ReAct agent planning and repair.

### **One important recommendation**

Use two inference configurations.

**Translation mode:** Non-thinking, constrained JSON output, low-to-moderate temperature.

**Difficult semantic review:** Thinking mode, especially for ambiguous sentence references, idioms, technical language and complicated claims.

You don't need an elaborate reasoning trace for every straightforward translation window.

Also, its 1M context window doesn't mean you should send an entire 100-page passage family in one translation call. Context capacity and translation reliability are different things.

## **7.2 Google Cloud Translation API — excellent option for standard Bengali**

This is the official Google service I would test first for conventional English-to-Bengali translation.

Google officially supports Bengali (`bn`) and Bengali India (`bn-IN`) in its Translation LLM language list, and Bengali is also supported by its Neural Machine Translation model.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://docs.cloud.google.com&sz=32)

Google Cloud Documentation+1

[Google Cloud Translation API Pricing 2026](https://images.openai.com/static-rsc-4/ipudQY2ow1gv4rRYg2e_sL6TGAssxzYeoeAGwR-mEm-hUm-iZksCteqWJJv_nVvZowf9YkWMDHjzUH830gQ4iK5o123muU9RhuBJ4SM5OcbNX8sO_U8n3y6RnHjnXYSHzOeOud7n5gNkRaGafjkxx18VWbw6WETLbvB56wh2GjU?purpose=inline)

**Google Cloud Translation**

# **$0**

**First 500,000 characters per month**

NMT translation allowance, applied through a $10 monthly credit.

**After the free allowance**

# **$20**

Per additional million characters for the standard NMT pricing tier.

**Google Translation LLM**

# **$10 + $10**

Per million input characters plus per million output characters.

Official pricing: [Cloud Translation pricing](https://cloud.google.com/products/translate/pricing?utm_source=chatgpt.com).

So, yes, there is an official free allowance.

But it isn't an unlimited free Google Translate API. The monthly credit applies to eligible NMT usage; LLM translation has separate charges.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://cloud.google.com&sz=32)

Google Cloud+1

### **What about Benglish?**

Google has a Romanization/Transliteration feature for Bengali through Cloud Translation Advanced, currently documented as Preview.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://docs.cloud.google.com&sz=32)

Google Cloud Documentation+1

However, there's an important distinction:

\\[ \text{Translation}\neq\text{Transliteration}\neq\text{Code-switch generation} \\]

For example:

| Operation       | Input                  | Output                         |
| --------------- | ---------------------- | ------------------------------ |
| Translation     | আমি পোশাকটি পছন্দ করি। | I like the dress.              |
| Transliteration | আমি পোশাকটি পছন্দ করি। | Ami poshak-ti pochondo kori.   |
| Code-mixing     | আমি পোশাকটি পছন্দ করি। | Dress ta amar really pochondo. |

Google's transliteration feature can help with script conversion, but it does not solve the linguistic decisions involved in generating natural English-Bengali code-switching.

**My verdict:** Use Google NMT as a strong baseline for standard Bengali text. Don't make it your primary Benglish/Engali generator.

## **7.3 Gemini 3.5 Flash-Lite — worth benchmarking**

Another option is Google's Gemini 3.5 Flash-Lite.

Google describes it as a cost-efficient model designed for high-volume agentic tasks, translation and simple data processing.

The documented paid pricing is:

| Mode      | Input / 1M tokens | Output / 1M tokens |
| --------- | ----------------- | ------------------ |
| Standard  | $0.30             | $2.50              |
| Batch     | $0.15             | $1.25              |
| Free tier | Free of charge    | Free of charge     |

The free tier is subject to limited access and usage limits. Google also states that free-tier content can be used to improve its products, whereas paid-tier content is not used for that purpose under its pricing terms.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://aistudio.google.com&sz=32)

AI Studio+1

[Gemini 3.5 Flash-Lite pricing](https://aistudio.google.com/docs/pricing?utm_source=chatgpt.com).

This is particularly interesting for your project because you have large numbers of relatively independent translation windows.

You could batch these requests, maintain the same glossary and passage-family metadata, and compare output quality against DeepSeek.

I wouldn't assume it will necessarily translate Bengali better. That needs an actual experiment.

## **7.4 AI4Bharat IndicXlit — useful for Benglish script conversion**

[AI4Bharat](https://images.openai.com/static-rsc-4/sjfCt819_o2QTOOg4d1eXcuDe4K3T1--UMBr3AV6J6lcd3sVnSjFAAz9_wxRvAorKW63XxU4eol9htx4pmcGjfjNMyqzoVrqqS_LwxHZcmcnRXdDwd5L2uDdsCIFnOWAfaPnVoJpIgw1YXkXUZkj4Cas5TdLidkb-i5VpeyPFnc?purpose=inline)

**IndicXlit**

Open-source transliteration model

[Official documentation](https://indicnlp.ai4bharat.org/indic-xlit/?utm_source=chatgpt.com)

This is a different kind of tool.

IndicXlit is an approximately 11-million-parameter Transformer-based transliteration model supporting 21 Indic languages.

Its Bengali transliteration training data contains approximately 1.23 million Bengali-English word pairs.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://indicnlp.ai4bharat.org&sz=32)

AI4Bharat IndicNLP

For example:

```
Romanized Bengali:
Python er syntax onek readable.

Indic-script Bengali:
Python-এর syntax অনেক readable.
```

It can be useful for converting Romanized Bengali into Bengali script.

But it does not understand your complete code-switching style or decide which words should remain English.

Use it as a utility in your Benglish/Engali pipeline, not as a replacement for an LLM.

# **8. My recommended model stack**

I would use a hybrid arrangement.

## **Translation model allocation**

**English → Natural Bengali**

Google Cloud NMT

Primary baseline

Use DeepSeek or Gemini for difficult contextual translation, terminology and naturalness refinement.

**English → Benglish**

DeepSeek V4.1 Flash

Primary

Use controlled code-switch generation. IndicXlit can help with Bengali romanization.

**English → Engali**

DeepSeek V4.1 Flash

Primary

Generate English-dominant mixed-script writing using explicit linguistic profiles.

**Independent quality review**

Gemini Flash-Lite / separate verifier

Secondary

Evaluate semantic preservation, claim relationships and linguistic naturalness independently of the translator.

**Bengali script conversion**

IndicXlit

Utility

Use for romanized Bengali to native-script conversion, where appropriate.

I would not call four different APIs on every single window. Use the cheaper translation path first and escalate only failed or ambiguous cases.

Also, don't make the same model both the translator and the only validator. That's an easy way to create correlated errors.

# **9. One thing I would do differently: use translation as a two-pass process**

I think this will improve your results more than simply switching to a stronger model.

### **Pass 1: Faithful translation**

Translate every window while preserving:

- Meaning.
- Sentence structure where practical.
- Entities and relations.
- Numbers and dates.
- The original claim-evidence relationship.

No creative rewriting.

### **Pass 2: Linguistic naturalization**

Now provide:

- Original English window.
- First-pass Bengali translation.
- Global context.
- Translation glossary.
- Target language profile.

Ask the LLM to improve naturalness without changing semantics.

For Benglish and Engali, the second pass will do the code-switch adaptation.

This separation is important because translation and naturalization are different objectives.

You don't want an LLM to simultaneously translate, rewrite, improve and creatively modify a passage. That makes debugging semantic drift much harder.

# **10. How I would benchmark the translation models before choosing one**

Don't decide based on model reputation or benchmark scores alone.

Create a small manually verified translation benchmark from your existing dataset.

I suggest starting with 100 passage families, including all three variants.

**Translation pilot**

# **100 families**

Each family contains three passages and one shared claim set.

Bengali translation\
**300 passages**

Benglish adaptation\
**300 passages**

Engali adaptation\
**300 passages**

# **900**

Target translated passage outputs, excluding translated claims and questions.

Compare three pipelines:

| Experiment | Translation procedure                                          |
| ---------- | -------------------------------------------------------------- |
| A          | DeepSeek V4.1 Flash windowed translation                       |
| B          | Google NMT followed by DeepSeek semantic-preserving refinement |
| C          | Gemini 3.5 Flash-Lite contextual translation                   |

Then use DeepSeek or another independent evaluator to check the outputs. Human bilingual annotators should assess a subset.

### **Evaluation criteria**

| Metric                  | What you are testing                                         |
| ----------------------- | ------------------------------------------------------------ |
| Semantic fidelity       | Does the translation preserve the original meaning?          |
| Claim preservation      | Does every translated claim mean the same thing?             |
| Tri-state invariance    | Does each passage retain its intended label for every claim? |
| Completeness            | Were any facts accidentally omitted or introduced?           |
| Entity consistency      | Are names and relationships preserved?                       |
| Bengali naturalness     | Does it sound like naturally written Bengali?                |
| Code-switch naturalness | Does the Benglish/Engali sound authentic?                    |
| Window consistency      | Are terminology and references consistent across windows?    |

I would give **tri-state invariance and semantic fidelity hard acceptance gates**, not merely weighted quality scores.

BLEU or chrF scores can be included as supplementary translation metrics, but they should not be the primary acceptance criteria. A translation can have different wording while perfectly preserving the evidence relationship.

## **10.1 Interactive pilot configuration**

These are the starting settings I would use for the experiment.

**Translation experiment configuration**

Primary translation engine

DeepSeek V4.1 Flash

Google NMT + DeepSeek

Gemini Flash-Lite

Target language profile

Native Bengali

Benglish / Banglish

Engali

All three

Approximate source window size (words)

250400500

Translation strategy

One-pass translation

Translation + naturalization

Translation + naturalization + independent verification

Generate implementation specification&#x20;

# **11. One further research opportunity: test parametric knowledge across languages**

There is something particularly interesting that your original tri-state dataset enables.

You can test whether a model's reliance on pretrained knowledge changes when the evidence is presented in a different language.

For instance:

**Claim:**

> Guido van Rossum developed Python.

**Three contexts:**

- English context: Python was developed by James Gosling.
- Bengali context: পাইথন তৈরি করেছিলেন জেমস গসলিং।
- Benglish context: Python James Gosling develop korechilen.

All three should be classified as Contradicted relative to the claim.

Now suppose the model has strong parametric knowledge that Guido van Rossum developed Python.

Does it follow the supplied context consistently across all three languages?

You could measure:

\\[ \text{CrossLingualConsistency} = \frac{ \text{Correctly classified equivalent variants} }{ \text{Total equivalent variants} } \\]

You could also measure whether parametric-knowledge intrusion is higher in Bengali or code-mixed contexts than in English contexts.

This would give your multilingual extension a meaningful scientific objective beyond simply increasing the number of languages supported.

# **12. My final recommendation**

I would make the following decisions:

| Decision           | My recommendation                                            |
| ------------------ | ------------------------------------------------------------ |
| Long passages      | Sentence-aligned, structure-aware window translation         |
| Agent architecture | ReAct translator with persistent glossary and bounded repair |
| Bengali            | Google NMT baseline + LLM refinement                         |
| Benglish           | DeepSeek controlled code-switch generation                   |
| Engali             | DeepSeek controlled mixed-script generation                  |
| Script conversion  | IndicXlit where appropriate                                  |
| Independent QA     | Separate bilingual semantic verifier                         |
| Validation         | Claim-set-level tri-state invariance                         |
| Scale-up           | 100-family pilot before bulk translation                     |

**Regarding your current DeepSeek setup:** Keep it. DeepSeek V4.1 Flash is already inexpensive enough that replacing it with another general-purpose LLM might not produce a worthwhile improvement. Add Google NMT for standard translation and benchmark Gemini Flash-Lite rather than switching your entire pipeline.

The architecture I would ultimately implement is:

\\[ \boxed{ \begin{aligned} &\text{English passage family}\\\ &\downarrow\\\ &\text{Global semantic/claim manifest}\\\ &\downarrow\\\ &\text{Structure-aware window extraction}\\\ &\downarrow\\\ &\text{Faithful translation}\\\ &\downarrow\\\ &\text{Naturalization / Code-switch adaptation}\\\ &\downarrow\\\ &\text{Independent semantic verification}\\\ &\downarrow\\\ &\text{Family-level tri-state invariance}\\\ &\downarrow\\\ &\text{Multilingual dataset} \end{aligned} } \\]

The one rule I would absolutely enforce in Hermes is: **a multilingual passage family is not accepted until all three translated variants preserve the intended relationship with every translated claim.**

That is more important than translation fluency alone.

<q>
okay, then we will use deepseek only ...., also I think the translation-agent (ie., doing all translation , transliteration, code mixing) should also be claim aware (rather that just verifying at the end, ...so that it dont accidently alter it in the wrong direction)... , can you also write me objective.md for this part (assuming that my hermes agent has alteady implemented the earlier tri-state english-only pipeline , ...and we have the tri-state ensligh-only data/passages) ...
</q>

The translation subsystem will use **DeepSeek as its only language model**, with `deepseek-flash` as the configurable API model identifier. DeepSeek’s current API documentation lists that identifier for its V4.1 Flash model and supports both thinking and non-thinking requests, so the same model can handle translation, transliteration, code-mixing, planning, and review. Deterministic code can still handle segmentation, alignment, storage, and validation checks; no Google Translate or second LLM will be introduced.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://api-docs.deepseek.com&sz=32)

DeepSeek API Docs+1

A key design decision in the objective: **the claims become translation constraints before passage translation begins**. The translator receives the fixed claim set and the required relation for each variant on every relevant window. It must preserve that relation—not rewrite the passage to make it easier to classify.

**Multilingual extension objective.md**

Created

Download objective.md

The document is approximately **10,000 words** and is written as an implementation specification for your existing Hermes pipeline.

### **Important design decisions included**

1. **Claims first, passages second:** Build a semantic constraint ledger and translate the canonical claims before translating any passage.
2. **Every window is claim-aware:** Each translation window receives the complete claim set, semantic constraints, and expected relation (`SUPPORTED`, `CONTRADICTED`, or `UNSUPPORTED`).
3. **One fixed claim set:** The same translated claims are reused across all three variants.
4. **No cross-variant contamination:** Translate each variant separately, while sharing the family glossary and claim constraints.
5. **DeepSeek throughout:** Translation, romanization, transliteration, code-mixing, naturalization, review, and repair all use DeepSeek. No fallback translation provider.
6. **Long-passage support:** Sentence-aware windows, read-only overlapping context, alignment IDs, continuity checks, and resumable jobs.
7. **Bounded ReAct repairs:** Localized repairs, two attempts by default, then quarantine if unresolved.
8. **Strict semantic preservation:** Unsupported must remain neutral—not become a denial. Contradicted must remain contradicted. Supported must retain its evidence.

It also defines the four initial profiles: native Bengali, romanized Bengali, Bengali-led Benglish, and English-led Engali; plus schemas, prompts, tests, metrics, CLI requirements, and implementation milestones.

**One important safeguard:** DeepSeek performs both translation and review, but the reviewer is a separate task—not independent ground truth. The specification therefore includes deterministic checks and bilingual human audits as well.
