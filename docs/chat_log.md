do that paper uses any tri-state dataset ? can you that to me...

Yes. But there is an important distinction between the paper's three-class classification and the **tri-state dataset construction** in your screenshot.

The HalluGuard paper uses three labels, but it does **not** use exactly the same three context types that you're proposing.

## **1. Does HalluGuard use a tri-state dataset?**

The paper uses three categories:

| HalluGuard label        | Meaning                                   |
| ----------------------- | ----------------------------------------- |
| Grounded                | Claim is supported by the document.       |
| Intrinsic Hallucination | Claim contradicts the document.           |
| Extrinsic Hallucination | Claim is not established by the document. |

Your proposed dataset uses:

| Your label                | Meaning                                                                             |
| ------------------------- | ----------------------------------------------------------------------------------- |
| Supported                 | Passage contains evidence supporting the correct answer.                            |
| Missing Evidence          | Passage is relevant but does not contain enough information to answer the question. |
| Conflicting / Distracting | Passage contains contradictory, misleading, or distracting information.             |

**The difference is fundamental:**

- HalluGuard classifies the relationship between a claim and a document.
- Your approach classifies the evidential relationship between a question-answer pair and a supplied context passage.

Your approach is particularly interesting for RAG systems because it tests whether a model can distinguish relevant context from genuinely sufficient evidence.

You can absolutely build this using ideas from HalluGuard, particularly its synthetic data generation, preference filtering, and reasoning-oriented training methodology.

# **2. Your proposed tri-state dataset construction**

I would structure this as follows.

## **Tri-State Dataset Pipeline**

**English–Bengali QA sources**

BEnQA + IndicKLAR + native Bengali and code-mixed Banglish examples

**Question normalization and deduplication**

Preserve question IDs, language, script and answer alignment.

**Question-ID-based train / validation / test split**

Prevent parallel and paraphrased questions from leaking across splits.

**Three-context generation per question**

Supported · Missing Evidence · Conflicting / Distracting

S

**Supported**

Answer evidence present

M

**Missing**

Relevant, insufficient evidence

C

**Conflicting**

Misleading or contradictory evidence

# **3. Ready-to-use methodology section for your research proposal**

I would write your section like this, with a few methodological improvements to make it more rigorous.

### 1. Tri-State Dataset Construction

We will construct a multilingual, tri-state evidence-verification dataset by combining parallel English–Bengali question-answer pairs from resources such as BEnQA with native Bengali and code-mixed Banglish examples from resources such as IndicKLAR. We will additionally incorporate carefully curated native examples to capture natural Bengali expressions, transliteration variations, and realistic English–Bengali code-switching patterns.

**Data splitting and leakage prevention:** All data will be divided into training, validation, and test sets using question IDs before context generation or augmentation. Parallel English–Bengali versions, paraphrases, and derived examples belonging to the same underlying question will be assigned to the same split, ensuring that semantically equivalent questions cannot leak across training and evaluation sets.

**Tri-state context generation:** For every question-answer pair, we will construct three distinct types of context passages:

a. **Supported:** A passage containing sufficient and explicit evidence to establish the correct answer. The evidence may be directly stated or require straightforward inference.

b. **Missing Evidence:** A semantically relevant passage discussing the question's subject or surrounding topic but not containing sufficient information to establish the correct answer. The passage should not explicitly contradict the answer.

c. **Conflicting / Distracting:** A passage containing misleading or contradictory information that could lead a model to produce an incorrect answer. This includes explicit contradictions, incorrect factual alternatives, and highly relevant distractors involving similar entities, dates, numbers, or relationships.

**Multilingual and code-mixed coverage:** The three context types will be represented across English, Bengali (native script), and code-mixed Banglish (including Bengali written in Latin script where appropriate). We will ensure that the dataset captures both translation-equivalent examples and naturally occurring language-specific expressions rather than relying exclusively on machine-translated passages.

**Quality assurance:** Generated passages will be checked against the original answer and source evidence. We will use automated consistency checks and human verification by bilingual annotators to validate the context labels, semantic relevance, and language naturalness. Conflicting passages will additionally be annotated with their contradiction or distraction subtype.

Each resulting example will contain a question, its reference answer, a context passage, a tri-state label, language/script metadata, and supporting evidence or annotation rationale where applicable.

# **4. Example: what would the actual dataset look like?**

Let's construct a hypothetical example.

**Question:**

Who wrote the national anthem of Bangladesh?

**Reference answer:** Rabindranath Tagore.

Now generate three contexts.

**Example A — Supported**

SUPPORTED

English context

Rabindranath Tagore wrote the lyrics and composed the music of Amar Shonar Bangla, which became the national anthem of Bangladesh.

The answer is explicitly supported.

**Example B — Missing Evidence**

MISSING

Bengali context

বাংলাদেশের জাতীয় সংগীত হলো "আমার সোনার বাংলা"। গানটি বাংলাদেশের জাতীয় পরিচয় ও সাংস্কৃতিক ঐতিহ্যের একটি গুরুত্বপূর্ণ অংশ।

This passage discusses the anthem but does not identify its author.

**Example C — Conflicting**

CONFLICTING

Banglish context

Bangladesh er national anthem "Amar Shonar Bangla" Kazi Nazrul Islam likhechilen.

The passage provides an incorrect author, explicitly conflicting with the reference answer.

Notice something important: all three passages discuss the same topic.

A simple relevance-based retriever might consider all three relevant.

But only the first passage provides sufficient evidence for the correct answer.

This is exactly the distinction your dataset should teach the model.

# **5. Three important improvements I recommend**

### **A. Don't merge contradictory and distracting passages without additional annotations**

Your third category currently combines two slightly different problems.

| Subtype       | Example                                                                             |
| ------------- | ----------------------------------------------------------------------------------- |
| Contradictory | Passage explicitly says the wrong person wrote the anthem.                          |
| Distracting   | Passage discusses another Bengali poet, but says nothing about the anthem's author. |

The distinction matters because the model must learn two different things:

- Detecting contradictory evidence.
- Recognizing that relevant information is not necessarily sufficient evidence.

I would retain your three primary classes but introduce a secondary metadata field:

```
CONFLICTING:
    - EXPLICIT_CONTRADICTION
    - MISLEADING_FACT
    - RELEVANT_DISTRACTOR
```

This preserves your tri-state classification while enabling more detailed evaluation.

### **B. Keep the parallel language examples together during splitting**

Suppose you have:

- English question: Who wrote Bangladesh's national anthem?
- Bengali question: বাংলাদেশের জাতীয় সংগীত কে রচনা করেছিলেন?
- Banglish question: Bangladesh er national anthem ke likhechilen?

These are essentially the same question.

If the English version enters training and the Bengali version enters testing, your evaluation could overestimate generalization.

Therefore, create a shared `question_group_id` and split by that ID.

### **C. Don't let the model learn superficial language-label correlations**

For example, don't generate:

- English = Supported.
- Bengali = Missing.
- Banglish = Conflicting.

Every language/script combination should contain all three labels.

Otherwise, the model might learn language-based shortcuts rather than evidence verification.

# **6. Suggested dataset schema**

I would store your data in JSONL format, with one context passage per record.

```
{
  "question_id": "Q001",
  "question_group_id": "Q001",
  "question": "Who wrote the national anthem of Bangladesh?",
  "reference_answer": "Rabindranath Tagore",
  "context": "Rabindranath Tagore wrote Amar Shonar Bangla.",
  "label": "SUPPORTED",
  "language": "English",
  "script": "Latin",
  "context_subtype": null,
  "evidence": "Rabindranath Tagore wrote Amar Shonar Bangla.",
  "split": "train"
}
```

For the same question, you would have two additional records with `MISSING_EVIDENCE` and `CONFLICTING` labels.

One important implementation detail: keep the original question ID, group ID, and source provenance throughout synthetic generation. Never assign entirely new independent IDs to paraphrases or translations without retaining their relationships.

# **7. How this connects to HalluGuard**

There is a particularly interesting research possibility here.

You can borrow the following components from HalluGuard:

| HalluGuard component              | Your adaptation                                                 |
| --------------------------------- | --------------------------------------------------------------- |
| FineWeb documents                 | English–Bengali QA sources                                      |
| Document reformation              | Bengali, Banglish and code-mixed context generation             |
| Three hallucination categories    | Three context-evidence states                                   |
| Synthetic claim generation        | Synthetic context generation                                    |
| Large/small preference generators | Large/small multilingual verifier teachers                      |
| Consensus filtering               | Bilingual human + independent LLM verification                  |
| ORPO + LoRA                       | Preference-based fine-tuning of a compact multilingual verifier |

But your task is not identical to HalluGuard's task. You should not simply reuse its labels or claim that your dataset is a reproduction of HalluGuard.

You are adapting its synthetic-data and training methodology to a different verification problem.

## **8. What I would evaluate**

Beyond ordinary classification accuracy, I would specifically investigate:

| Experiment                  | Research question                                                      |
| --------------------------- | ---------------------------------------------------------------------- |
| English-only training       | How well does the model verify English contexts?                       |
| Bengali-only training       | How well does it verify native Bengali contexts?                       |
| Banglish-only training      | Can it understand code-mixed contexts?                                 |
| Multilingual joint training | Does multilingual training improve cross-language generalization?      |
| Cross-lingual testing       | Can it verify Bengali questions using English evidence and vice versa? |
| Distractor robustness       | Can it distinguish relevance from actual evidence sufficiency?         |
| Translation leakage control | Does performance remain strong on genuinely unseen question groups?    |

One additional experiment I particularly recommend is testing whether a model trained on English and Bengali can generalize to Banglish without seeing Banglish training examples.

That would provide an interesting measure of cross-lingual transfer.

## **My recommendation**

Your tri-state dataset is a good foundation for a multilingual RAG hallucination-verification project.

I would make one distinction central to your research:

**Retrieval relevance ≠ Evidence sufficiency.**

A passage can be highly relevant to a question without containing the answer. A passage can even contain convincing but incorrect information.

Your dataset should explicitly teach the model to distinguish these cases.

That is a more interesting research problem than simply training another multilingual question-answering classifier.

is this paper altering the claim into 3 variant (supported , contradiction , missing evidance) or is it altering the passage (context) into 3 variant ?

**HalluGuard alters the CLAIM, not the passage (context).**

This is an important distinction, and after checking Sections 3, 4.2 and Figure 2 of the actual paper, I can confirm it.

## **1. What HalluGuard actually does**

It starts with a document \\(x\\), then generates a claim \\(c\\) whose relationship with that document determines its label.

**Original document&#x20;**\\(x\\)

Apple shares hit record highs, briefly valuing the company at $900B, after beating Wall Street forecasts with strong international sales.

**Claim generation**

Grounded

Apple stock hit record highs, valuing the company at $900B.

Intrinsic

Apple shares fell sharply, reducing its valuation below $600B.

Extrinsic

Apple's performance was driven by iPhone X demand in emerging markets.

Conceptual representation of Figure 2. The same document is paired with different types of claims.

Notice that the document remains unchanged. Only the claim changes.

The three relationships are:

| Label                   | How the claim is constructed                                            |
| ----------------------- | ----------------------------------------------------------------------- |
| Grounded                | Claim is supported by the document.                                     |
| Intrinsic hallucination | Claim directly contradicts the document.                                |
| Extrinsic hallucination | Claim introduces information that cannot be verified from the document. |

## **2. How they construct the actual dataset**

According to Section 4.2:

1. They collect 300,000 documents from FineWeb.
2. They filter and curate these documents, resulting in 104,966 documents.
3. They reform each document into a different writing style using a Data Reformer.
4. They generate one synthetic claim per reformed document.
5. The Claim Generator assigns one of three labels to each document-claim pair.
6. They balance the dataset across the three classes.

The resulting structure is:

\\[ \boxed{(x_i,c_i,t_i)} \\]

Where:

- \\(x_i\\) = document.
- \\(c_i\\) = generated claim.
- \\(t_i\\) = relationship label.

Importantly, they generate one claim per document, rather than necessarily generating all three claim variants for every individual document.

They subsequently generate two candidate model responses for each document-claim pair and use preference filtering.

**Sources:** HalluGuard, Sections 3–4.3, pages 16919–16922, particularly Figure 2 and Figure 3.&#x20;

2026.findings-acl.835(1).pdf

## **3. How this differs from your proposed dataset**

This is where your research proposal takes a different approach.

|                    | HalluGuard                              | Your proposed approach                 |
| ------------------ | --------------------------------------- | -------------------------------------- |
| Fixed component    | Document                                | Question + reference answer            |
| Modified component | Claim                                   | Context passage                        |
| Class assignment   | Relationship between claim and document | Evidence available in context          |
| Three classes      | Grounded, intrinsic, extrinsic          | Supported, missing, conflicting        |
| Main task          | Document-claim verification             | Question-context evidence verification |

Your proposed dataset would look like:

\\[ (q,a,x_1,S),\quad(q,a,x_2,M),\quad(q,a,x_3,C) \\]

Here, the question and reference answer remain fixed, while the context changes.

**My recommendation:** Keep your context-variant approach. It is particularly suitable for studying whether multilingual RAG systems can distinguish relevant passages from sufficient evidence and misleading evidence.

You can borrow HalluGuard's synthetic generation, preference construction, consensus filtering and ORPO training methodology without copying its claim-variant dataset construction.

That is the key methodological difference.

I want to create a tristate dataset using llms (in massive scales) , I need a complete pipeline plan (so that i dont get repeative low quality essays)....

# **Complete pipeline: Large-scale LLM-generated Tri-State Evidence Dataset**

I would approach this as a **controlled synthetic data factory**, rather than asking LLMs to generate thousands of passages and subsequently cleaning them.

The most important design decision is:

> Generate many candidate passages from verified factual sources, but accept only passages that satisfy strict evidence, label, relevance, linguistic and diversity constraints.

This is how we avoid the typical failure of LLM-generated datasets: thousands of lengthy, repetitive, superficially different but semantically identical passages.

Your target is not an essay-generation dataset. It is a **multilingual evidence-sufficiency and evidence-conflict dataset for RAG verification**.

I'll design the pipeline around English, native Bengali and code-mixed Banglish, while keeping it extensible to additional Indic languages.

# **1. First, define exactly what you are generating**

For every canonical question-answer pair, we want three different context passages.

Let:

\\[ Q=\text{Question} \\]

\\[ A=\text{Verified reference answer} \\]

\\[ C=\text{Context passage} \\]

The model should learn:

\\[ f(Q,A,C)\rightarrow\\{S,M,C_f\\} \\]

Where:

- \\(S\\): Supported.
- \\(M\\): Missing Evidence.
- \\(C_f\\): Conflicting / Distracting.

The actual training input can be either `(Q, C)` with the answer hidden and the output being answerability, or `(Q, A, C)` with the reference answer supplied and the output being evidence status.

I recommend starting with the second formulation because it allows you to explicitly measure whether the supplied context supports the known answer.

## **1.1 Operational definitions — be extremely precise**

This is critical. Ambiguous definitions will produce noisy synthetic data regardless of how good your LLMs are.

| Label                       | Strict definition                                                                                        | What must be true                                           |
| --------------------------- | -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| **SUPPORTED**               | Context contains sufficient evidence to establish the reference answer.                                  | At least one verifiable supporting evidence span exists.    |
| **MISSING_EVIDENCE**        | Context is relevant to the question but insufficient to establish its answer.                            | No sufficient support and no direct contradiction.          |
| **CONFLICTING_DISTRACTING** | Context contains misleading, incompatible or competing information that can lead to an incorrect answer. | An identifiable misleading fact or competing answer exists. |

I would introduce secondary labels:

| Primary label | Secondary subtype                                                                               |
| ------------- | ----------------------------------------------------------------------------------------------- |
| Supported     | Explicit, Paraphrased, Multi-sentence inference                                                 |
| Missing       | Answer omitted, Partial information, Incomplete evidence                                        |
| Conflicting   | Explicit contradiction, Wrong entity, Wrong date/number, Misleading relation, Distractor entity |

This gives you a three-class primary classification task while retaining fine-grained analysis.

**Important distinction:** A completely unrelated passage should not automatically become a conflicting passage. It is simply irrelevant. You should either exclude it from this tri-state task or explicitly add it as an additional subcategory of a separate retrieval-relevance experiment.

## **1.2 Example of the desired output**

Question:

> Who developed the Python programming language?

Reference answer:

> Guido van Rossum.

SUPPORTED

Python was originally developed by Guido van Rossum, with its first implementation released in 1991. The language was designed to emphasize readability and simplicity.

Answer is directly established.

MISSING EVIDENCE

Python is a high-level, interpreted programming language that supports multiple programming paradigms. It is widely used in web development, automation, scientific computing and machine learning.

Highly relevant to Python, but says nothing about its developer.

CONFLICTING / DISTRACTING

Python was created by James Gosling in the late 1980s as a language intended for cross-platform enterprise applications.

Wrong developer, with a plausible but misleading association with another programming language.

The important property is that the same question and answer are retained while the context changes.

# **2. Dataset sources: where should the questions and answers come from?**

I would use three different types of seed sources, because relying on a single QA dataset will give you limited topic coverage.

## **2.1 BEnQA**

[BanglaRQA: A Benchmark Dataset for Under-resourced Bangla Language Reading Comprehension-based Question Answering with Diverse Question-Answer Types - ACL Anthology](https://images.openai.com/static-rsc-4/eVM1ofYLyUimmemx6n8zIBTKtfrinzJky0XJ3ec7EyCuogUJr8_ur4xPU37xTC22yDYnC0CNPdDSReyIMeG6gDk1yq1FcUFGFQEGL_x3sMMpjZGlRpNnwM7FpcrvnCbSOYXca-J15aPLXpIH46Y7IyviUXIrK3IQt4yR1LI0vfw?purpose=inline)

**BEnQA**

ACL Findings 2024

[Paper](https://aclanthology.org/2024.findings-acl.68/?utm_source=chatgpt.com) · [Dataset repository](https://github.com/sheikhshafayat/BEnQA?utm_source=chatgpt.com)

BEnQA provides approximately 5,000 parallel Bengali-English exam questions for middle and high school students in Bangladesh. It covers science subjects and factual, application and reasoning questions.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://aclanthology.org&sz=32)

ACL Anthology+1

**My recommendation:** Use it as a high-quality seed source for educational QA and reasoning examples.

However, do not assume the existing BEnQA questions come with evidence passages suitable for your task. Its documented dataset is a QA benchmark distributed in CSV format. You will need to construct an independent evidence layer for each question.

## **2.2 IndicKLAR**

[Factual Consistency of Multilingual Pretrained Language Models - ACL Anthology](https://images.openai.com/static-rsc-4/ABsP0xIKqocZSzJdoHCSp1nC-9PS-dan1WE3LRJTseHTYyJ1x8iZAObitvmdSKs2aausSOf2ZsAHduheuJ81GW_qxti3wVMciLg_uCxCBHQoshSMTOgBRE75Bb4LRKHHGVEN1zRkB-RO9q581djB_LHwbiJ58iQE_U1_FVHzoU0?purpose=inline)

**IndicKLAR**

2026 research release

[Microsoft Research publication](https://www.microsoft.com/en-us/research/publication/evaluating-cross-lingual-knowledge-consistency-in-code-mixed-vis-a-vis-indian-languages-using-indicklar/?lang=ja&utm_source=chatgpt.com) · [GitHub repository](https://github.com/debajyotimaz/IndicKLAR_EMNLP_2026?utm_source=chatgpt.com)

IndicKLAR is especially interesting for your project. It studies cross-lingual consistency of factual QA across native Indic languages, English and code-mixed variants.

Its published description covers 18 Indic languages and code-mixed variants for 11 language pairs, with native-speaker verification of language variants.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.microsoft.com&sz=32)

Microsoft Research+1

It can give you:

- Bengali native-script questions.
- Romanized/code-mixed Bengali variants.
- Structured factual relationships.
- Entity and relation-based questions.
- Cross-lingual equivalent examples.

**One limitation:** IndicKLAR is primarily a structured factual knowledge benchmark, not a large collection of naturally written passages. Its structured facts are excellent seeds for controlled question and distractor generation, but you should not treat its question templates as a source of diverse passage content.

## **2.3 Additional sources**

I would add three additional pools:

| Source type                                  | What to extract                                              |
| -------------------------------------------- | ------------------------------------------------------------ |
| Bengali educational material                 | Science, history, geography, mathematics and textbooks       |
| Bengali news and informational material      | Realistic factual passages, entities, dates and events       |
| Native Bengali/Banglish question collections | Natural question formulations and conversational expressions |

The Bangladesh National Corpus also provides extensive Bangla text resources and a Romanized Bangla corpus, which could be useful for language-quality and linguistic variation work.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://corpus.bangla.gov.bd&sz=32)

corpus.bangla.gov.bd

My preference would be to prioritize sources with known provenance, identifiable publication dates and clear usage permissions.

# **3. The most important architectural decision: separate factual knowledge from passage generation**

Do not give an LLM just a question and tell it:

> Generate supported, missing and conflicting passages.

This creates an avoidable problem.

The generator has to invent the supporting facts, invent the missing information, and invent the contradictions. You have no reliable way of knowing whether its generated facts are correct.

Instead, introduce an intermediate **Evidence Dossier**.

**Canonical Question Record**

```
{
  "question_id": "Q001",
  "question": "Who developed Python?",
  "answer": "Guido van Rossum",
  "topic": "Computer Science",
  "relation": "developed_by"
}
```

**Verified Evidence Dossier**

```
{
  "fact": "Python was developed by Guido van Rossum.",
  "entity": "Python",
  "relation": "developed_by",
  "value": "Guido van Rossum",
  "source_id": "SRC_001",
  "source_span": "..."
}
```

**Context Generator**

Receives the verified question, answer, evidence dossier and a particular generation objective.

**Three independently generated context candidates**

Supported / Missing / Conflicting

This architecture is the foundation of the whole system.

## **Why is the Evidence Dossier so important?**

It allows you to distinguish three things:

1. What is actually known from a trusted source.
2. What a generated context says.
3. Whether that generated context really supports the answer.

For every question, preserve:

- Canonical question.
- Verified answer.
- Answer type.
- Source documents.
- Supporting evidence spans.
- Related facts.
- Contradictory candidate facts, if any.
- Entities and relations.
- Language and script variants.

This gives you a factual grounding layer that the synthetic generation system cannot silently change.

**Never let a context generator redefine the ground-truth answer.**

# **4. Stage 1 — Normalize and validate the question-answer pool**

Before generating anything, create canonical question records.

You will likely receive the same question in multiple forms:

- English: Who developed Python?
- Bengali: পাইথন প্রোগ্রামিং ভাষা কে তৈরি করেন?
- Banglish: Python programming language ke develop korechilen?

These should be treated as one underlying question, not three independent questions.

Create a `question_group_id`:

```
{
  "question_group_id": "KG_001",
  "variants": [
    {
      "language": "en",
      "script": "latin",
      "question": "Who developed Python?"
    },
    {
      "language": "bn",
      "script": "bengali",
      "question": "পাইথন প্রোগ্রামিং ভাষা কে তৈরি করেন?"
    },
    {
      "language": "bn",
      "script": "latin",
      "question": "Python programming language ke develop korechilen?"
    }
  ],
  "reference_answer": "Guido van Rossum"
}
```

### **Operations**

**A. Unicode normalization**

Normalize Bengali Unicode representations, whitespace, punctuation and common formatting differences. Preserve the raw original strings separately.

**B. Question deduplication**

Use three layers:

1. Exact normalized-text matching.
2. Multilingual embedding similarity.
3. LLM-assisted semantic equivalence checking for ambiguous pairs.

For example, these should be recognized as the same question:

- Who invented the telephone?
- Who is credited with inventing the telephone?
- Who invented the telephone device?

But these should not necessarily be merged:

- Who invented the telephone?
- Who patented the telephone?

Related questions can have different answers or different interpretations.

**C. Answer normalization**

Normalize aliases, spelling variations, dates and numerical formats.

For example:

- Guido van Rossum
- Guido Van Rossum
- Guido van-Rossum

These refer to the same canonical entity.

**D. Answer validation**

Use original source data and independent evidence. Reject questions with ambiguous or disputed answers unless you explicitly annotate their temporal or source-dependent nature.

Do not rely exclusively on multiple LLMs agreeing on the answer.

# **5. Stage 2 — Split the dataset BEFORE generating passages**

This is extremely important for avoiding data leakage.

Suppose you have one canonical question:

```
Q001: Who developed Python?
```

You generate:

- Supported context.
- Missing context.
- Conflicting context.
- English versions.
- Bengali versions.
- Banglish versions.
- Five different paraphrases of each.

Every generated variant must remain in the same dataset split.

Otherwise, the model might encounter the same factual question in training and testing, simply with slightly different wording.

I recommend:

| Split      | Proportion |
| ---------- | ---------- |
| Training   | 80%        |
| Validation | 10%        |
| Test       | 10%        |

But do not split randomly over individual passages.

Split by `question_group_id`, and where possible group related questions by underlying entity-relation or fact.

There should be two additional evaluation settings:

**Source-held-out evaluation:** Test on documents or sources never used to generate the training contexts.

**Topic/relation-held-out evaluation:** Test on selected unseen domains, entities or relation types to investigate generalization.

Keep the final test set locked. Do not repeatedly tune prompts against its results.

# **6. Stage 3 — Build a controlled context-generation system**

This is the core of your project.

I would create three independent generation pipelines rather than one enormous prompt that asks the LLM to produce all three types.

Each pipeline should have its own generation instructions, constraints and validation rules.

## **Context Generation Factory**

**Input**

Question + Verified Answer + Evidence Dossier + Target Language

**Generator S**

Supported

Generate evidence-containing contexts.

**Generator M**

Missing

Generate relevant but insufficient contexts.

**Generator C**

Conflicting

Generate misleading or contradictory contexts.

**Candidate pool**

Multiple independent candidate passages per target class

**Quality control + deduplication**

Accept, regenerate or reject

Let's define each generator.

## **6.1 Supported passage generation**

The objective is to create contexts that contain enough information to answer the question correctly.

However, don't ask the model to write an essay.

Instead, give it a verified source passage or an evidence dossier and request a compact passage.

I would use several generation modes:

| Mode                     | Description                                                      |
| ------------------------ | ---------------------------------------------------------------- |
| Extractive               | Use original source wording with minimal surrounding context.    |
| Faithful paraphrase      | Rewrite the evidence without changing its meaning.               |
| Contextual explanation   | Add relevant background while retaining the answer-bearing fact. |
| Multi-sentence synthesis | Combine two or more verified evidence spans.                     |
| Structured text          | Use a short bullet list, record or table where natural.          |

These modes vary the evidence representation without inventing unnecessary narrative.

### **Prompt: Supported Generator**

**Prompt template**

Generator S

```
You are generating evidence passages for a
multilingual question-answer verification dataset.

QUESTION:
{question}

VERIFIED ANSWER:
{answer}

VERIFIED EVIDENCE:
{evidence}

TARGET LANGUAGE:
{language}

TARGET SCRIPT:
{script}

PASSAGE FORM:
{passage_form}

TASK:
Generate one natural, compact passage containing
sufficient evidence to establish the verified answer.

REQUIREMENTS:
1. Preserve the factual meaning of the supplied evidence.
2. The answer must be directly identifiable or
   inferable from the passage.
3. Do not introduce unsupported names, dates,
   quantities, causal claims or relationships.
4. Avoid generic introductions and conclusions.
5. Do not write an essay.
6. Use natural language appropriate to the target
   language and script.
7. Avoid repeatedly using the same sentence patterns.

LENGTH:
Prefer 1-4 sentences, normally 40-100 words.
Longer passages are allowed only when the evidence
genuinely requires them.

Return JSON only:
{
  "context": "...",
  "evidence_span": "...",
  "generation_mode": "...",
  "language": "..."
}
```

&#x20;Copy prompt

The `evidence_span` field is very important. It tells your validator precisely which portion is supposed to support the answer.

Don't automatically trust it. The validator must independently locate and verify that span.

## **6.2 Missing Evidence generation**

This is probably the most difficult class to generate correctly.

Why?

Because generating an irrelevant passage is easy.

Generating a passage that is:

- Highly relevant to the question.
- Topically connected to the answer.
- Natural and informative.
- Yet genuinely insufficient to establish the answer.

is considerably harder.

Consider:

Question:

> Who developed Python?

Bad Missing example:

> The Mughal Empire was established in 1526.

This is irrelevant. It doesn't test evidence sufficiency.

Better Missing example:

> Python is a popular high-level programming language. Its syntax emphasizes readability, and it is widely used in data science, automation and web development.

This is related to the question's subject but doesn't identify its developer.

### **How to generate these passages reliably**

I suggest two different strategies.

**Strategy A: Evidence deletion / omission**

Start with a trusted passage that contains several facts.

Select the answer-bearing fact and generate a new passage that preserves related information while omitting the information needed to answer the question.

Example:

Original:

> Python was developed by Guido van Rossum. Its first release occurred in 1991. It emphasizes readability and supports multiple programming paradigms.

Generated Missing:

> Python was first released in 1991. It emphasizes readability and supports multiple programming paradigms.

The model must not introduce any substitute answer.

**Strategy B: Related-source retrieval**

Retrieve a genuinely related passage about the same entity or topic, but from a section that does not contain the answer.

For example, retrieve a Python passage about its programming paradigms.

This produces more realistic retrieval scenarios than merely deleting one sentence from an existing paragraph.

I would use both strategies and maintain separate metadata for them.

### **Prompt: Missing Evidence Generator**

```
TASK:
Generate a naturally written passage for a
question-answer evidence verification dataset.

QUESTION:
{question}

REFERENCE ANSWER:
{answer}

TOPIC:
{topic}

RELATED VERIFIED MATERIAL:
{related_evidence}

TARGET LANGUAGE:
{language}

TARGET SCRIPT:
{script}

OBJECTIVE:
Construct a context that is relevant to the
question and its topic, but does NOT contain
sufficient information to establish the reference
answer.

STRICT REQUIREMENTS:
1. Do not state the reference answer.
2. Do not paraphrase the answer-bearing fact.
3. Do not state an incompatible alternative.
4. Do not include an obvious contradiction.
5. Preserve relevant contextual information.
6. Avoid unrelated filler or generic text.
7. The passage must sound like a realistic
   retrieved document chunk, not an essay.
8. Do not use phrases like "the document does
   not mention the answer" or "the answer is unknown".

Return JSON only:
{
  "context": "...",
  "omitted_fact": "...",
  "relevance_reason": "...",
  "generation_method": "..."
}
```

The most important instruction is that the generator must not explicitly announce that the answer is missing.

Otherwise your classifier can learn an extremely superficial shortcut:

> "The passage says the information is not mentioned" → Missing Evidence.

You want it to infer evidence insufficiency from the content itself.

## **6.3 Conflicting / Distracting passage generation**

For this class, I strongly recommend controlled fact transformations rather than unconstrained creative writing.

Consider:

Question:

> Who developed Python?

Correct answer:

> Guido van Rossum.

You can construct several hard-negative types:

| Transformation           | Generated misinformation                                  |
| ------------------------ | --------------------------------------------------------- |
| Entity substitution      | Python was developed by James Gosling.                    |
| Entity confusion         | Python was developed by the creator of Java.              |
| Temporal mutation        | Python was initially developed in 1998.                   |
| Relation reversal        | Guido van Rossum was a user of Python, not its developer. |
| Similar-entity confusion | Java was developed by Guido van Rossum.                   |

Some of these are direct contradictions; others are entity or relation distractors.

An important point: your negative passages should be realistic. They should not contain absurd statements that a model can reject based on common sense alone.

### **Prompt: Conflicting Generator**

```
TASK:
Generate a misleading passage for a multilingual
question-answer verification dataset.

QUESTION:
{question}

VERIFIED ANSWER:
{answer}

VERIFIED EVIDENCE:
{evidence}

TARGET LANGUAGE:
{language}

TARGET SCRIPT:
{script}

NEGATIVE TYPE:
{negative_subtype}

TASK:
Generate a compact passage containing a plausible
but incorrect or misleading fact relevant to the
question.

POSSIBLE TRANSFORMATIONS:
- Entity substitution
- Wrong date
- Wrong numerical value
- Incorrect subject-object relation
- Confusion between similar entities
- Misleading attribution

REQUIREMENTS:
1. The passage should be topically relevant.
2. It must introduce identifiable misleading
   information.
3. Do not accidentally reproduce the correct answer.
4. Do not create multiple unrelated falsehoods.
5. Preserve natural language and realistic writing.
6. Do not write an essay or explanatory justification.
7. Do not disclose the intended classification.

Return JSON:
{
  "context": "...",
  "negative_subtype": "...",
  "misleading_fact": "...",
  "target_fact": "..."
}
```

### **One important safety and scientific decision**

Keep all intentionally fabricated counterfactual passages explicitly tagged as synthetic.

Do not mix them with supposedly authentic factual sources without provenance metadata.

You are building adversarial training examples, not producing a factual knowledge corpus.

# **7. Preventing repetitive, low-quality passages: the diversity engine**

This is the part I would spend significant effort on.

The typical failure of large-scale LLM-generated datasets is that models produce different sentences with almost identical underlying structures.

For example:

1. Python is widely used in data science and web development.
2. Python is commonly used in web development and data science.
3. Python has applications in data science and web development.
4. Python is popular for data science and web development.

These may look different lexically, but they are essentially the same example.

You need diversity at multiple levels.

## **7.1 Diversity should be controlled across independent dimensions**

I would create a `diversity_profile` for every generated passage.

| Dimension          | Example values                                       |
| ------------------ | ---------------------------------------------------- |
| Domain             | Science, history, geography, technology, culture     |
| Topic              | Programming languages, astronomy, biology            |
| Passage length     | Short, medium, long                                  |
| Source form        | News, textbook, encyclopedia, manual, conversational |
| Evidence density   | One fact, multiple facts                             |
| Sentence structure | Simple, compound, complex                            |
| Passage form       | Paragraph, bullets, record, table                    |
| Entity type        | Person, organization, location, concept              |
| Question type      | Who, when, where, why, how, numeric                  |
| Language           | English, Bengali                                     |
| Script             | Latin, Bengali                                       |
| Code mixing        | None, light, moderate, heavy                         |
| Negative subtype   | Entity, date, number, relation                       |

The point is not to make every context artificially different.

The point is to make sure the dataset covers different real-world RAG situations.

## **7.2 Do not force every context into an essay format**

I recommend a controlled length distribution such as:

**Initial passage-length sampling policy**

Short: 1–2 sentences

**30%**

Medium: 3–4 sentences

**50%**

Long: 5–7 sentences

**20%**

Proposed starting distribution, not a measured property of the source datasets. Adjust after analysing realistic RAG retrieval chunks.

These length bands should be measured in actual tokens during implementation, not just words.

Also vary source structure. A real retrieval system might return:

- A paragraph from a textbook.
- Two adjacent sentences from a report.
- A small list.
- A table row.
- A short dialogue excerpt.
- A section heading and a paragraph.

These are more valuable variations than generating dozens of stylistically rewritten essays.

## **7.3 Use multiple generator prompts**

Do not call the same prompt 10,000 times with a different question.

Maintain a collection of prompt templates.

For example:

- P1: Encyclopedic passage.
- P2: Educational explanation.
- P3: News passage.
- P4: Formal report.
- P5: Conversational explanation.
- P6: Technical documentation.
- P7: Table/structured record.
- P8: Short informational passage.

Randomly sample a compatible template for each candidate.

However, source and factual diversity matter more than superficial tone diversity. Eight different prompts cannot fix an underlying dataset containing only the same 20 facts.

## **7.4 Use semantic deduplication, not just exact duplicate removal**

You need four levels of deduplication.

| Layer         | Technique                          | Purpose                         |
| ------------- | ---------------------------------- | ------------------------------- |
| Exact         | Normalized string hash             | Identical passages              |
| Near-exact    | N-gram overlap / MinHash           | Slightly rewritten passages     |
| Semantic      | Multilingual embeddings            | Meaning-equivalent passages     |
| Question/fact | Canonical fact and entity grouping | Repeated underlying information |

For example:

> Python was created by Guido van Rossum.

and

> Guido van Rossum is the creator of Python.

These should be recognized as semantically equivalent.

But be careful: a supported passage and a conflicting passage may intentionally contain the same entities with different relations. Cross-label deduplication should not blindly eliminate meaningful contradictions.

Instead, use semantic similarity to identify suspicious candidates for additional review.

### **A useful approach**

Cluster passages using multilingual sentence embeddings.

Within each cluster:

- Preserve different genuine information.
- Remove trivial paraphrases.
- Retain hard negatives if they provide a meaningful contrast.
- Enforce a maximum number of near-duplicate examples.
- Audit clusters with high concentrations of identical templates.

You should also maintain a dataset-level diversity report:

- Unique n-gram ratio.
- Average nearest-neighbour cosine similarity.
- Cluster-size distribution.
- Template frequency.
- Vocabulary diversity by language.
- Entity and relation coverage.
- Passage-length distribution.

A dataset can have millions of records and still contain very little information diversity.

# **8. Stage 4 — Automated quality control: the most important stage**

I would never use the generating LLM as the sole judge of its own output.

Instead, implement a multi-stage quality-control pipeline.

Think of the process as an assembly line:

\\[ \text{Generated candidates} \rightarrow \text{Cheap filters} \rightarrow \text{Semantic verification} \rightarrow \text{Independent evaluation} \rightarrow \text{Human audit} \\]

Each stage should reject a different category of errors.

## **8.1 Gate 1: Structural and linguistic validation**

These checks are cheap and should run on every candidate.

| Validation    | Reject when                                                         |
| ------------- | ------------------------------------------------------------------- |
| JSON validity | Output cannot be parsed                                             |
| Length        | Passage is excessively short or long                                |
| Language      | Generated language differs from requested language                  |
| Script        | Native Bengali output contains unintended Latin-script substitution |
| Repetition    | Repeated phrases or sentences                                       |
| Boilerplate   | Generic introductions and conclusions                               |
| Formatting    | Contains unwanted explanations, labels or meta-commentary           |
| Safety        | Contains disallowed material or privacy violations                  |

For Bengali, use language and script identification separately. Bengali written in Latin characters should not be mistakenly classified as English just because the script is Latin.

For Banglish, validate code-mixing explicitly rather than relying only on language identification.

## **8.2 Gate 2: Evidence verification**

This is the most important quality gate.

Every candidate should pass different tests depending on its class.

**Supported verification**

1. Extract the answer-bearing evidence from the context.
2. Check whether the evidence establishes the reference answer.
3. Compare the generated context with its trusted source dossier.
4. Reject invented information and unsupported additions.

Accept only when support is established

**Missing Evidence verification**

1. Check semantic relevance to the question.
2. Check that the correct answer is not explicitly or implicitly established.
3. Check that the passage does not contain a contradictory answer.
4. Check that the passage does not reveal the intended class through explicit phrases.

Accept only when relevant but insufficient

**Conflicting verification**

1. Extract the misleading factual assertion.
2. Compare it against the verified answer and source dossier.
3. Determine exactly why the fact is misleading.
4. Check that the misleading information is relevant to the question.

Accept only when a real misleading relationship exists

An important nuance: for Missing Evidence, the evaluator should be allowed to say that the passage is relevant but insufficient. It must not confuse "I personally know the answer" with "the passage contains the answer."

That means your evaluator prompt must explicitly restrict its judgment to the supplied context.

## **8.3 Gate 3: Independent LLM verification**

Following HalluGuard's general approach, use independent evaluators, but make the verification considerably more structured.

For example:

- Generator: Model A.
- Verifier 1: Model B.
- Verifier 2: Model C.
- Optional adjudicator: Model D.

Prefer different model families or independently trained systems where possible.

Don't tell the evaluators which class the passage was generated for.

Give them:

- Question.
- Reference answer.
- Context.
- Source evidence dossier when required for checking factual correctness.

Ask them to predict the class independently.

Example output:

```
{
  "predicted_label": "MISSING_EVIDENCE",
  "relevance": 0.94,
  "answer_sufficiency": 0.12,
  "contradiction_detected": false,
  "evidence_spans": [],
  "reason": "The passage discusses Python's properties but does not identify its developer.",
  "confidence": 0.96
}
```

For a Supported example, require a corresponding evidence span.

For a Conflicting example, require the exact misleading assertion and its contradiction or distractor relationship.

### **Important: don't use simple majority voting blindly**

Suppose two LLMs say Supported and one says Missing.

That does not necessarily mean Supported is correct.

Instead, define explicit conditions:

| Condition                 | Action                           |
| ------------------------- | -------------------------------- |
| All checks pass           | Accept                           |
| One evaluator disagrees   | Send for additional adjudication |
| Evidence validation fails | Reject                           |
| Source truth is ambiguous | Reject or mark for human review  |
| Language quality fails    | Regenerate                       |
| Multiple quality failures | Reject                           |

Keep the individual evaluator decisions. Do not retain only the final majority label.

## **8.4 Gate 4: Context-only question-answering test**

This is an additional test I strongly recommend.

Take each generated context and give it to an independent QA model.

Ask:

> Answer the original question using ONLY the supplied passage. If the answer cannot be established by the passage, explicitly abstain.

Expected behaviour:

| Intended label | Expected QA behaviour                                       |
| -------------- | ----------------------------------------------------------- |
| Supported      | Produces the reference answer with evidence                 |
| Missing        | Abstains because evidence is insufficient                   |
| Conflicting    | Produces or identifies the competing misleading information |

This is a useful round-trip consistency check.

However, one caveat: a model may know the answer from its pretrained knowledge even when the context does not contain it.

Therefore, QA output alone must not determine the label.

Combine it with explicit evidence extraction and entailment checks.

## **8.5 Gate 5: Human quality audit**

You cannot realistically manually inspect every example in a massive dataset.

But you should not skip human validation either.

I would use a stratified audit.

During the initial pilot, have bilingual annotators inspect a substantial sample from every language-label combination.

At scale, audit:

- Random accepted examples.
- Low-confidence examples.
- Disagreement cases.
- High-similarity duplicate clusters.
- Rare negative subtypes.
- Bengali and Banglish passages separately.

Use two annotators for the gold evaluation set, with adjudication of disagreements.

Measure inter-annotator agreement using Cohen's kappa or Krippendorff's alpha, depending on the annotation design.

Keep a separately human-verified benchmark. It should never be automatically expanded using the same generation pipeline without preserving the human verification provenance.

# **9. Stage 5 — Quality scoring and selection**

In addition to binary acceptance rules, I would assign each candidate a quality profile.

For example:

\\[ Q(p)= w_1G+ w_2R+ w_3L+ w_4D+ w_5F \\]

Where:

- \\(G\\): Grounding and label validity.
- \\(R\\): Relevance.
- \\(L\\): Linguistic naturalness.
- \\(D\\): Diversity.
- \\(F\\): Format and structural quality.

A possible initial scoring scheme:

| Dimension                    | Initial weight |
| ---------------------------- | -------------- |
| Evidence / label correctness | 35%            |
| Semantic relevance           | 20%            |
| Linguistic quality           | 15%            |
| Diversity / novelty          | 15%            |
| Naturalness and realism      | 10%            |
| Formatting                   | 5%             |

These weights are only starting hypotheses; validate them against human judgments.

**My recommendation is to use hard acceptance gates for factual correctness, and quality scoring only to rank the candidates that have already passed those gates.**

A beautifully written false passage should never outrank a factually valid passage simply because it reads better.

For every question and desired label, generate multiple candidates and retain one or more distinct high-quality candidates.

For example:

\\[ K=3\text{ candidates per class} \\]

Keep the best passing candidate, or more than one when they represent genuinely different evidence patterns.

This is much better than generating a single passage and hoping it is good.

# **10. Stage 6 — Multilingual generation without translation artifacts**

This deserves its own pipeline because Bengali and Banglish generation can introduce different kinds of errors.

I would maintain three explicit language/script conditions.

| Condition | Example                                     |
| --------- | ------------------------------------------- |
| English   | Python was developed by Guido van Rossum.   |
| Bengali   | পাইথন তৈরি করেছিলেন গুইডো ভ্যান রসম।        |
| Banglish  | Python Guido van Rossum develop korechilen. |

But do not just translate every English paragraph into Bengali and then transliterate it into Banglish.

That will produce artificial language patterns.

Instead, use two generation paths:

**Path A: Parallel semantic preservation**

Start from the same factual evidence and generate independently in the three language conditions.

The underlying facts should remain equivalent.

**Path B: Native formulation**

Use native Bengali writing examples and naturally occurring Banglish formulations as references for sentence construction.

Bilingual annotators should evaluate these outputs.

### **Language balancing**

Every class should occur in every language condition.

**Proposed training coverage matrix**

| **Language** | **S** | **M** | **C** |
| ------------ | ----- | ----- | ----- |
| English      | **✓** | **✓** | **✓** |
| Bengali      | **✓** | **✓** | **✓** |
| Banglish     | **✓** | **✓** | **✓** |

All three labels must be represented across all language/script conditions.

Also introduce controlled cross-lingual evaluation:

- Bengali question + English context.
- English question + Bengali context.
- Banglish question + Bengali context.
- Bengali question + Banglish context.

I would initially reserve many of these combinations for evaluation rather than making them dominate training.

Otherwise, you risk confusing the model about whether it is learning evidence sufficiency or merely language translation.

# **11. Stage 7 — Massive-scale generation and orchestration**

Now let's talk about the engineering.

You want to produce potentially hundreds of thousands of contexts, so generation should be a distributed, resumable data pipeline.

I would implement it as a DAG with independently executable stages.

## **11.1 Proposed architecture**

## **LLM Data Generation Infrastructure**

**Seed Dataset + Evidence Dossiers**

Canonical questions, answers and source material

**Job Orchestrator**

Assign question groups, generation labels, languages and templates

**S workers**

Supported

**M workers**

Missing

**C workers**

Conflicting

**Candidate Storage**

Store raw generations, metadata, source lineage and model versions

**Quality-Control Workers**

Deterministic filtering → LLM evaluation → deduplication → human audit

**Accepted Dataset**

Versioned JSONL / Parquet partitions

### **Suggested components**

| Component            | Possible implementation              |
| -------------------- | ------------------------------------ |
| Orchestration        | Python asyncio / Prefect / Dagster   |
| Generation           | LLM API with batch support           |
| Queue                | Redis / RabbitMQ                     |
| Intermediate storage | JSONL / Parquet                      |
| Metadata and status  | PostgreSQL                           |
| Embeddings           | Multilingual embedding model         |
| Deduplication        | MinHash + vector similarity          |
| Evaluation           | Separate LLM evaluators + NLI models |
| Human annotation     | Label Studio                         |
| Final dataset        | Hugging Face Datasets / Parquet      |

You don't need to install and maintain all of these immediately. Python, JSONL, asynchronous API calls and a simple database are enough for an initial prototype.

## **11.2 Generate candidates in batches**

For each canonical question:

```
for question in questions:    for language in ["english", "bengali", "banglish"]:        for label in [            "SUPPORTED",            "MISSING_EVIDENCE",            "CONFLICTING_DISTRACTING"        ]:            enqueue_generation_job(                question=question,                language=language,                target_label=label,                num_candidates=2            )
```

In production, the loops above should create durable jobs, not synchronously wait for every request.

Each job should have:

- A unique job ID.
- An idempotency key.
- A bounded retry policy.
- A generation model/version.
- A prompt-template version.
- A timeout.
- A validation status.

Store raw model responses before parsing them so you can investigate failures and regenerate individual records without losing the original outputs.

## **11.3 How many candidates should you generate?**

Suppose you start with 5,000 canonical questions.

You want three classes and three language conditions.

If you generate two candidates for each combination:

\\[ 5000\times3\times3\times2 = 90,000 \\]

**Example generation budget**

# **90,000**

Candidate passages generated

Supported\
**30,000**

Missing Evidence\
**30,000**

Conflicting / Distracting\
**30,000**

Each category includes three language/script conditions, with two candidate generations per condition.

Ideally, you retain 45,000 high-quality contexts: one per question, class and language.

The acceptance rate is not guaranteed, of course. If many candidates fail validation, generate replacements only for the failed combinations.

This is much more efficient than regenerating an entire dataset whenever quality is insufficient.

# **12. Stage 8 — Final dataset schema**

I would use one record per question-context pair, not one enormous record containing all three passages.

This makes filtering, shuffling, training and evaluation significantly easier.

Example:

```
{
  "sample_id": "Q001_EN_S_001",
  "question_group_id": "KG_001",
  "question_id": "Q001",

  "question": "Who developed Python?",
  "reference_answer": "Guido van Rossum",

  "context": "Python was originally developed by Guido van Rossum.",

  "label": "SUPPORTED",
  "subtype": "EXPLICIT",

  "question_language": "en",
  "context_language": "en",
  "script": "latin",
  "code_mix_ratio": 0.0,

  "source_ids": ["SRC_001"],
  "evidence_spans": [
    "Python was originally developed by Guido van Rossum."
  ],

  "generation_method": "faithful_paraphrase",
  "generator_model": "model_version",
  "prompt_version": "supported_v1",

  "validation": {
    "schema_valid": true,
    "language_valid": true,
    "evidence_valid": true,
    "label_valid": true,
    "dedup_pass": true,
    "human_verified": false
  },

  "split": "train"
}
```

For generated conflicting passages, include:

```
{
  "synthetic_counterfactual": true,
  "negative_subtype": "ENTITY_SUBSTITUTION",
  "misleading_fact": "Python was developed by James Gosling."
}
```

This allows you to distinguish naturally sourced evidence from intentionally generated counterfactual material.

Also preserve the original source passage and all intermediate generations in separate provenance records.

Never discard rejected samples immediately. They are valuable for studying the limitations of your generator and validator.

# **13. Stage 9 — Dataset-level evaluation**

Having 90,000 accepted records does not mean you have a good dataset.

You must evaluate quality at two different levels:

**Sample-level quality:** Is each individual passage valid?

**Dataset-level quality:** Is the overall collection diverse, balanced and representative?

I would create a dataset dashboard with the following metrics.

| Metric                               | What it measures                          |
| ------------------------------------ | ----------------------------------------- |
| Label distribution                   | Class balance                             |
| Language distribution                | English/Bengali/Banglish balance          |
| Exact duplicate rate                 | Repeated records                          |
| Semantic duplicate rate              | Repeated meanings                         |
| Average nearest-neighbour similarity | Overall redundancy                        |
| Topic coverage                       | Diversity of subjects                     |
| Entity coverage                      | Diversity of factual entities             |
| Relation coverage                    | Diversity of factual relationships        |
| Length distribution                  | Passage-length diversity                  |
| Human acceptance rate                | Actual quality of generated examples      |
| Inter-annotator agreement            | Reliability of human labels               |
| False-label rate                     | Generator/evaluator classification errors |

An especially useful metric is the **human-audited label precision**.

For example:

\\[ Precision\_{\text{Supported}}= \frac{\text{Human-confirmed Supported}} {\text{All sampled model-accepted Supported}} \\]

Calculate it separately for all three classes and all language conditions.

Do not just report aggregate accuracy; a system might generate excellent English passages and poor Banglish passages while hiding the difference in an overall average.

## **13.1 Maintain a separate real-context benchmark**

This is a very important research requirement.

Your training dataset will be synthetic.

But your final evaluation should not consist exclusively of passages created by the same LLMs using the same prompts.

Create a human-verified benchmark containing genuine retrieved passages:

- Actual answer-bearing passages.
- Relevant but incomplete passages.
- Genuine contradictory or misleading passages.

This lets you test whether your model learns evidence reasoning or simply learns the stylistic patterns of your synthetic generator.

# **14. My recommended implementation roadmap**

Don't begin by generating 100,000 examples.

Build the generator and validator first, and establish that the entire process works.

I would implement it in four phases.

1. **Phase 1 — Pilot dataset**

   Start here

   # **100–200 questions**

   Implement canonical IDs, answer verification, evidence dossiers, three context generators and a basic validator.

   Generate two candidates per class and language condition.

   Have bilingual annotators inspect the output.

2. **Phase 2 — Quality engineering**

   # **1,000 questions**

   Add multilingual semantic deduplication, independent evaluators, controlled negative generation, language-quality filtering and dataset-level diversity monitoring.

   Measure acceptance rates and human-audited precision.

3. **Phase 3 — Massive-scale construction**

   # **10,000–50,000 questions**

   Enable asynchronous generation, job queues, retry handling, incremental storage, candidate ranking and selective regeneration.

   Use source-balanced and topic-balanced sampling.

4. **Phase 4 — Research benchmark**

   # **Locked evaluation set**

   Create a human-verified real-retrieval benchmark, cross-lingual challenge sets and OOD evaluations.

   Publish dataset cards, annotation guidelines, source provenance and generation/validation details.

## **14.1 Pilot generation budget**

For 200 underlying questions, with three classes, three language conditions and two candidate passages per combination:

\\[ 200\times3\times3\times2=3,600 \\]

You get 3,600 initial candidate generations.

After validation, you could retain up to:

\\[ 200\times3\times3=1,800 \\]

accepted records.

This is a sufficiently meaningful pilot to discover whether the prompts and validators work before investing in large-scale generation.

# **15. Important research experiments I would add**

Your dataset itself can become a research contribution, rather than just a source of fine-tuning examples.

I would build the following experiments into the dataset design.

| Experiment                            | What you can establish                                                    |
| ------------------------------------- | ------------------------------------------------------------------------- |
| LLM-generated vs real passages        | Synthetic-to-real generalization                                          |
| Supported vs Missing discrimination   | Evidence sufficiency understanding                                        |
| Missing vs Conflicting discrimination | Whether the model detects contradictions rather than simply missing facts |
| English vs Bengali vs Banglish        | Cross-lingual evidence reasoning                                          |
| Same fact, different contexts         | Whether predictions depend on evidence instead of memorized answers       |
| Paraphrased evidence                  | Robustness to linguistic variation                                        |
| Hard-negative evaluation              | Resistance to misleading but plausible passages                           |
| Cross-source evaluation               | Robustness to document/source changes                                     |
| Context length variation              | Sensitivity to longer retrieval chunks                                    |
| Answer leakage test                   | Whether the model relies on question priors instead of context            |

One particularly valuable experiment:

**Give the model the exact same question and reference answer, but change only the context between Supported, Missing and Conflicting.**

If the model predicts the same label for all three, it is probably relying too heavily on prior knowledge or question-answer patterns.

Your dataset should make this shortcut detectable.

# **16. My final recommended architecture**

Putting everything together, this is the pipeline I would actually implement.

## **Final end-to-end pipeline**

1. **Seed data acquisition**

   BEnQA, IndicKLAR, native Bengali QA and additional licensed sources.

2. **Canonicalization**

   Question grouping, multilingual alignment, answer normalization and deduplication.

3. **Source-grounded fact verification**

   Build evidence dossiers from trusted sources.

4. **Leakage-safe data splitting**

   Group by canonical question and underlying fact before augmentation.

5. **Controlled LLM generation**

   Separate Supported, Missing and Conflicting context generators.

6. **Diversity engine**

   Vary content, domains, evidence density, passage structure and linguistic form.

7. **Candidate validation**

   Structural checks, evidence verification, answerability testing and contradiction checks.

8. **Independent LLM consensus**

   Blind evaluation with separate multilingual evaluators.

9. **Semantic deduplication**

   Remove repeated meanings and preserve useful hard negatives.

10. **Human audit**

    Bilingual annotation and adjudication.

11. **Final dataset release**

    Versioned records, provenance, quality metrics and locked test benchmark.

## **17. A few decisions I would lock before implementation**

**Implementation design checklist**

0/7

**Three primary labels with fine-grained subtypes**

Keep the tri-state task but track contradiction, misleading entity and distractor subtypes.

**One evidence dossier per canonical question**

All three context classes must be grounded in the same verified answer and factual source.

**Generate passages, not essays**

Use compact retrieval-like chunks, varied structures and controlled lengths.

**Generate multiple candidates per class**

Start with two candidates and selectively regenerate failed combinations.

**Independent quality evaluation**

Separate generation from factual, semantic and bilingual validation.

**Group-aware splitting**

All translations, paraphrases and synthetic variants of one underlying question stay in one split.

**Human-verified real-context test set**

Do not rely exclusively on synthetic data when evaluating the final verifier.

## **My strongest recommendation**

There is one thing I would prioritize above everything else:

**Build the validator before scaling the generator.**

A weak generator with a strong validator can produce a useful dataset by generating more candidates and filtering aggressively.

A strong generator with a weak validator can produce a massive dataset of confidently mislabeled examples.

Your most valuable research asset will not be the number of passages generated. It will be the reliability of the relationship between the question, reference answer, context and label.

I would build the first prototype around the following three subsystems:

1. **Evidence Dossier Builder** — constructs verified factual material from your QA sources.
2. **Tri-State Context Generator** — independently creates the three types of passages, with multilingual and diversity controls.
3. **Evidence-Aware Quality Gate** — checks answer sufficiency, missing evidence, contradiction, language naturalness and semantic duplication.

Once those three components work on a 200-question pilot, scaling to tens of thousands becomes primarily an orchestration and compute problem rather than an uncontrolled data-quality problem.

but why cant we create first set of dataset passage corpus --> then for each passage: create a small set of supporting claims on that passage --> then let another react agent will surgically edit the passage (and create unsupported and contradictory versions of the same passage on those claims) ,....to generate truly diversified passages ,...use might first ganerate [topics -> sub topics -> sub-sub topics ..so on + also random news scrapper] \* (set of tonality) [initially everything will we english only] ...then instead of divings directly into ganrating ...we can create a abstract concept graph / very sort abstract version of what we are going to ganerate , ...then HNSW vector store ... retrival-based feedback (to avoid repetitions) [it will return the closely generated abatrase-passages and passages] --> then model will ganerate (avoid those close versions) ,...everything is english only (since models are better in English , closs-lingual / translations will we be addeded in the last) ...

**Yes. In fact, I think your proposed architecture is a better direction for this project than independently generating three passages for every question.** I would change the architecture around your idea rather than use my previous question-first generation pipeline.

What you're proposing is essentially a combination of:

1. **Corpus-first generation:** Build a large, diverse collection of natural passages before generating QA examples.
2. **Knowledge abstraction:** Extract a compact semantic representation of each passage, including its topics, entities, facts and relationships.
3. **Claim-conditioned counterfactual editing:** Generate factual claims from the original passage, then surgically modify the passage to create Missing and Conflicting variants.
4. **Retrieval-based diversity control:** Maintain an HNSW-indexed memory of previously generated semantic representations and passages, and use nearest-neighbour feedback to avoid repetitive generations.
5. **Agentic generation:** Use bounded ReAct-style loops to plan edits, apply patches, evaluate them and repair failures.
6. **Delayed multilingual expansion:** Build and validate the entire English dataset first, then introduce Bengali and Banglish through controlled language adaptation.

There is a very important advantage here:

**You are not asking an LLM to independently imagine what a supported, missing and conflicting passage should look like. You are asking it to transform an existing, semantically understood passage while preserving most of its content.**

That gives you much better control over factual changes and allows you to construct contrastive examples.

Let's design this properly.

# **1. The proposed architecture**

I would call this a **Corpus-First, Graph-Guided, Retrieval-Aware Counterfactual Data Generation Pipeline**.

## **End-to-end architecture**

**1. Diverse Corpus Acquisition**

Topic hierarchy + subtopics + random curated news ingestion + other factual sources

**2. Semantic Abstraction**

Abstract summaries + entity-relation graphs + fact extraction + source provenance

**3. Diversity Memory**

HNSW indexes for semantic concepts and generated passages; retrieve nearest examples

**4. Supporting Claim Generation**

Generate a small collection of atomic, evidence-grounded claims and corresponding questions for each passage.

**5. Counterfactual Editing Agent**

**Original / Supported Passage**

**Surgical deletion / omission**

Missing

**Controlled fact mutation**

Conflicting

All variants retain their original passage lineage and target claim.

**6. Quality-Control Agents**

Evidence validation + edit integrity + linguistic quality + diversity + independent adjudication

**7. Accepted Dataset + Updated HNSW Memory**

Versioned passages, claims, evidence spans, counterfactual variants and metadata

**8. Later: Bengali + Banglish Adaptation**

Native-language generation, semantic preservation and bilingual validation

Let's examine each component and some things I would modify in your proposal.

# **2. Stage 1 — Corpus-first acquisition: generate the source material before questions**

I completely agree with this.

Instead of initially generating passages for specific questions, we create a diverse source corpus.

Your two proposed acquisition mechanisms are complementary.

## **2.1 Mechanism A: Hierarchical topic exploration**

Start with broad topics and recursively explore increasingly specific topics.

For example:

**Technology**

Artificial Intelligence

Machine learningNeural networksLLM architecturesAI infrastructure

Computer Science

Operating systemsDatabasesNetworkingCompilers

Hardware

SemiconductorsGPUsMemory systemsArchitecture

Illustrative topic hierarchy; each leaf can be explored further into more specific concepts.

You can use an LLM to expand a topic into subtopics recursively.

But I would not generate an exhaustive tree. That can become combinatorially expensive and encourage artificial categories.

Instead, maintain a topic graph with:

- Parent topic.
- Child topic.
- Related topics.
- Core entities.
- Typical factual relations.
- Topic coverage count.
- Existing passage count.
- Underrepresented subtopics.

Why a graph instead of a strict tree? Because concepts overlap. For example, GPU memory management belongs to both hardware architecture and operating systems.

A simple schema:

```
{
  "topic_id": "T001",
  "topic": "Artificial Intelligence",
  "parent_topics": ["Technology"],
  "children": [
    "Machine Learning",
    "Deep Learning",
    "LLM Architectures",
    "AI Infrastructure"
  ],
  "related_topics": [
    "Distributed Computing",
    "Information Retrieval"
  ],
  "coverage": {
    "passages_generated": 0,
    "target_passages": 500
  }
}
```

The topic graph determines what to generate next, not simply what the LLM finds interesting.

### **Make generation adaptive**

Suppose AI infrastructure has 5,000 passages, but compiler design has only 50.

Your topic scheduler should prioritize underrepresented areas, while still allowing some random exploration.

One possible sampling policy:

\\[ P(T_i)\propto \frac{1}{\sqrt{1+n_i}} \\]

where \\(n_i\\) is the number of accepted passages in topic \\(T_i\\).

This is only a starting sampling strategy. You can also combine it with topic importance, source availability and quality statistics.

The intuition is simple: the more a topic is represented, the less frequently we need to sample it.

## **2.2 Mechanism B: Random news and factual-content ingestion**

I also like your idea of randomly ingesting news articles.

This introduces something the topic hierarchy cannot easily provide: an ongoing supply of entities, events, relationships and emerging facts.

For example, a news article about a semiconductor company might provide facts concerning:

- Company acquisitions.
- Executive appointments.
- Revenue.
- Manufacturing facilities.
- New products.
- Government policy.
- Supply-chain relationships.

A single article could produce several questions.

But I would make the news crawler _controlled-random_, not completely random.

Suggested source pipeline:

```
Source discovery
      |
      v
Domain / source allowlist
      |
      v
Article extraction
      |
      v
Metadata extraction
      |
      v
Language and quality filtering
      |
      v
Article deduplication
      |
      v
Passage segmentation
      |
      v
Corpus storage
```

Store:

```
{
  "document_id": "DOC_001",
  "source_url": "...",
  "source_domain": "...",
  "published_at": "...",
  "retrieved_at": "...",
  "title": "...",
  "topic": ["Technology", "Semiconductors"],
  "text": "...",
  "license": "...",
  "source_type": "news"
}
```

A few important precautions:

**Temporal consistency:** News can contain statements that become outdated. Preserve the publication date and source snapshot. Don't treat two reports from different dates as contradictory without considering when each was true.

**Source diversity:** Avoid repeatedly ingesting articles syndicated from the same original wire report.

**Content permission:** Respect robots.txt, website terms, copyright and redistribution rights. Retain provenance and avoid assuming scraped full-text material can be redistributed in your dataset.

**Source reliability:** You are creating evidence-verification examples, so ideally use sources whose factual claims have identifiable provenance. The synthetic edits will provide your controlled misleading data; there is no need to contaminate the original corpus with arbitrary misinformation.

### **2.3 Passage segmentation**

Don't immediately turn whole articles into essays.

First, segment them into realistic chunks.

I would retain two representations:

- Original source documents.
- Smaller passages extracted from those documents.

A reasonable initial chunking experiment might use 80–300 tokens per passage, with sentence-boundary preservation and some overlapping windows.

Don't make every passage exactly 200 tokens. Real RAG systems retrieve chunks of different lengths.

Also preserve the sentence-level source offsets so you can trace every fact and later surgically modify the relevant sentences.

# **3. Stage 2 — Abstract representation and concept graph**

This is where I think your proposal becomes particularly interesting.

Instead of directly generating questions and synthetic passages from raw text, first create a compact, structured representation of every passage.

I would call this the **Semantic Blueprint**.

The purpose is not to replace the original passage. It is to represent its semantic content independently of its wording.

## **3.1 What should a Semantic Blueprint contain?**

Suppose our original passage is:

> Python was created by Guido van Rossum and first released in 1991. The programming language emphasizes code readability and supports multiple programming paradigms. Its development began in the late 1980s.

We can extract:

**Original passage**

DOC_001 / PASSAGE_001

Python was created by Guido van Rossum and first released in 1991. The programming language emphasizes code readability and supports multiple programming paradigms. Its development began in the late 1980s.

**Abstract semantic representation**

```
{
  "topic": "Programming Languages",
  "subtopics": [
    "Python",
    "Programming Language History"
  ],
  "entities": [
    "Python",
    "Guido van Rossum"
  ],
  "facts": [
    {
      "subject": "Python",
      "predicate": "created_by",
      "object": "Guido van Rossum",
      "time": null,
      "evidence_span_id": "E1"
    },
    {
      "subject": "Python",
      "predicate": "first_released",
      "object": "1991",
      "evidence_span_id": "E2"
    },
    {
      "subject": "Python",
      "predicate": "has_property",
      "object": "code readability",
      "evidence_span_id": "E3"
    }
  ]
}
```

The important thing is that each fact is linked to its exact source span.

I would make the Blueprint contain six parts:

| Component        | What it represents                                       |
| ---------------- | -------------------------------------------------------- |
| Abstract summary | Short description of what the passage discusses          |
| Topic path       | Topic, subtopic and specific concept                     |
| Entities         | People, companies, products, locations, etc.             |
| Fact triples     | Subject–predicate–object relationships                   |
| Qualifiers       | Date, quantity, units, polarity, conditions, uncertainty |
| Evidence anchors | Exact sentence/span supporting each extracted fact       |

The qualifiers are particularly important.

For example, these two facts are not equivalent:

```
Revenue increased in 2023.
Revenue increased BY 20% in 2023.
```

Similarly:

```
Company A acquired Company B.
Company B acquired Company A.
```

A concept graph that ignores numerical qualifiers, temporal conditions, negation or entity roles will be dangerous for your counterfactual generator.

## **3.2 Build an actual concept/fact graph**

You can represent the extracted information as a property graph.

## **Example fact graph**

Illustrative entity-relation graph. Actual implementation should also retain source-span and qualifier metadata on each edge.

This graph serves several purposes:

1. Helps generate different question types.
2. Enables targeted factual mutations.
3. Identifies potentially redundant facts.
4. Helps measure semantic diversity.
5. Preserves the relationship between the original source and edited passages.

**Important technical distinction:** The concept graph and HNSW index are separate components.

- The concept graph stores explicit semantic relationships.
- The HNSW index provides approximate nearest-neighbour retrieval over vector embeddings.

You can build embeddings from the graph's abstract representation and index them in HNSW. You should not try to make HNSW itself store or represent the knowledge graph.

## **3.3 Generate a compact abstract signature**

I would create an additional compact representation specifically for diversity retrieval.

For the Python example:

```
{
  "signature": {
    "topic": "Programming language history",
    "entities": ["Python", "Guido van Rossum"],
    "relations": [
      "creator_of",
      "first_release_year",
      "language_property"
    ],
    "fact_types": [
      "PERSON_ATTRIBUTION",
      "TEMPORAL",
      "DESCRIPTIVE"
    ],
    "numerical_facts": 1,
    "causal_relations": 0,
    "main_concept": "Python origins and characteristics"
  }
}
```

This is valuable because two passages can have very different surface wording but the same underlying semantic structure.

For example:

> Python was created by Guido van Rossum and released in 1991.

and

> The Python language was originally developed by Guido van Rossum, with its first release arriving in 1991.

A normal text embedding might identify these as similar.

But their abstract signatures make the underlying duplication even more explicit.

Do not discard the full text or graph after abstraction. These are complementary representations.

# **4. Stage 3 — HNSW-based diversity memory and retrieval feedback**

This is another part of your proposal I strongly like.

You are essentially creating a memory of everything that has already been generated, so future generation can be informed by existing material.

I would maintain **two separate vector indexes**, backed by a common metadata database.

**Index A — Abstract Semantic Index**

Embeddings of semantic blueprints, concept summaries and fact signatures.

Purpose: Detect repetition of underlying ideas, entities, relations and factual structures.

**Index B — Passage Surface Index**

Embeddings of actual generated and source passages.

Purpose: Detect paraphrases, repeated sentence structures, similar passage wording and stylistic repetition.

**Metadata Store**

Document IDs, question IDs, source IDs, topics, relations, tone, labels, language, timestamps and generation lineage.

### **4.1 How the retrieval feedback loop should work**

Suppose the next generation task is:

> Generate a passage about the early development of a programming language.

Before generating, create a proposed semantic signature.

Embed it and retrieve its nearest neighbours from both indexes.

For example:

| Existing passage                   | Semantic similarity | What it tells the generator       |
| ---------------------------------- | ------------------- | --------------------------------- |
| Python's early development         | 0.94                | Too close; avoid reproducing      |
| Java's original design goals       | 0.81                | Related topic, different relation |
| C language development history     | 0.79                | Potentially useful alternative    |
| Evolution of programming paradigms | 0.65                | Broader conceptual context        |

These similarities are illustrative, not real measured scores.

Now feed selected neighbours back into the generator.

Rather than showing it ten full passages and saying "don't repeat", give it a concise novelty report:

```
PREVIOUSLY COVERED:

- Python creator and initial release year.
- Java creator and original design goals.
- C language development history.
- Evolution of programming paradigms.

HIGHLY REPRESENTED RELATION TYPES:

- Created_by
- First_released
- Designed_for

UNDERREPRESENTED OPPORTUNITIES:

- Language interoperability.
- Compiler implementation.
- Runtime architecture.
- Historical design trade-offs.

INSTRUCTION:
Generate content exploring an underrepresented
semantic area. Do not simply paraphrase the
existing passages.
```

This is much more effective than merely changing the temperature or writing style.

### **4.2 Don't rely only on nearest-neighbour retrieval**

There is a subtle problem here.

Suppose you generate a thousand passages about programming languages and then ask HNSW for the nearest ten examples.

You might successfully avoid those ten, but still repeatedly generate similar passages to the other 990.

The nearest-neighbour search is an information source, not a complete diversity mechanism.

I would use three additional mechanisms.

**A. Cluster saturation**

Track how many passages already exist in each semantic cluster.

Penalize highly saturated clusters.

**B. Entity-relation frequency**

Count the occurrence of important entities and relation types.

Don't let the generator repeatedly use the same popular entities.

**C. Diversity-aware candidate selection**

Generate multiple candidates and rank them according to semantic novelty, factual validity and topic coverage.

You can use Maximum Marginal Relevance (MMR) for candidate selection.

A common form is:

\\[ MMR(c)= \lambda \operatorname{Rel}(c) -(1-\lambda) \max\_{s\in S}\operatorname{Sim}(c,s) \\]

Where:

- \\(c\\) is a candidate.
- \\(S\\) is the already selected set.
- \\(\operatorname{Rel}\\) measures relevance to the desired topic.
- \\(\operatorname{Sim}\\) measures similarity to existing selections.
- \\(\lambda\\) balances relevance and novelty.

You want candidates that are relevant but not excessively similar to what you have already generated.

### **4.3 An important ordering improvement**

I would actually use retrieval feedback twice:

**Before generation:** Retrieve similar semantic signatures to inform topic/fact selection.

**After generation:** Retrieve similar accepted passages to decide whether the candidate is sufficiently novel.

So:

\\[ \text{Plan} \rightarrow \text{Retrieve neighbours} \rightarrow \text{Generate} \rightarrow \text{Retrieve again} \rightarrow \text{Accept/Regenerate} \\]

This is better than only retrieving after generation.

# **5. Stage 4 — Generate supporting claims from each original passage**

Now that we have a corpus and its semantic representation, we generate questions and atomic claims.

I would not ask the LLM to generate arbitrary questions directly from the passage.

Use the fact graph to select candidate facts first.

For the Python passage, the graph gives:

```
Python
 ├── created_by → Guido van Rossum
 ├── first_released → 1991
 ├── emphasizes → Code readability
 └── supports → Multiple programming paradigms
```

Now generate questions corresponding to individual relations.

| Fact           | Question                                        | Answer             |
| -------------- | ----------------------------------------------- | ------------------ |
| created_by     | Who created Python?                             | Guido van Rossum   |
| first_released | When was Python first released?                 | 1991               |
| emphasizes     | What does Python emphasize?                     | Code readability   |
| supports       | What programming paradigms does Python support? | Multiple paradigms |

I would initially generate 2–5 high-quality question-answer pairs per passage, depending on its fact density.

### **Why atomic claims?**

Because they give you a precise editing target.

Consider:

> Python was developed by Guido van Rossum and first released in 1991.

This contains two factual propositions:

\\[ c_1=\text{Python was developed by Guido van Rossum} \\]

\\[ c_2=\text{Python was first released in 1991} \\]

If your question concerns \\(c_1\\), the editing agent should modify only the evidence relevant to \\(c_1\\), leaving \\(c_2\\) unchanged.

This gives you much stronger control over the resulting context.

## **5.1 Store claim-evidence mappings**

Each claim should have its own record:

```
{
  "claim_id": "CL_001",
  "passage_id": "P_001",
  "question": "Who developed Python?",
  "claim": "Python was developed by Guido van Rossum.",
  "answer": "Guido van Rossum",
  "evidence_spans": ["E1"],
  "fact_ids": ["F1"],
  "answer_type": "PERSON",
  "difficulty": "EASY"
}
```

I would also record claim difficulty:

- Direct factual retrieval.
- Paraphrase matching.
- Entity disambiguation.
- Numerical reasoning.
- Temporal reasoning.
- Relational reasoning.
- Multi-sentence inference.

This will become useful when you want to balance easy and hard examples.

# **6. Stage 5 — The ReAct-style surgical passage editing agent**

Now we get to your most interesting proposal.

You have:

- An original passage.
- Its semantic blueprint.
- A small set of supported factual claims.
- Exact evidence spans for those claims.

Now you can use an agent to create the two synthetic negative variants.

I would absolutely implement this as a tool-using, iterative editing agent.

But I would not allow it to freely rewrite the entire passage.

**Give it an editing budget and a constrained set of operations.**

## **6.1 First, understand the desired transformation**

Original passage:

> Python was created by Guido van Rossum and first released in 1991. It emphasizes code readability and supports multiple programming paradigms.

Question:

> Who created Python?

Reference answer:

> Guido van Rossum.

The three passages should be:

**Original passage**

SUPPORTED

Python was created by Guido van Rossum and first released in 1991. It emphasizes code readability and supports multiple programming paradigms.

**Edited variant 1**

MISSING

Python was first released in 1991. It emphasizes code readability and supports multiple programming paradigms.

One answer-bearing clause is removed while the rest of the passage remains intact.

**Edited variant 2**

CONFLICTING

Python was created by James Gosling and first released in 1991. It emphasizes code readability and supports multiple programming paradigms.

Only the creator relationship is modified.

This is a clean contrastive triple.

The question, answer and underlying source remain fixed, while the evidence context changes.

## **6.2 Give the agent explicit editing operations**

I would define two categories of edit tools.

**Missing-evidence operations**

| Operation                      | Action                                                                        |
| ------------------------------ | ----------------------------------------------------------------------------- |
| Remove evidence span           | Delete the sentence or clause establishing the answer                         |
| Partial deletion               | Remove only the answer-bearing part of a sentence                             |
| Context-preserving replacement | Replace the evidence with related information that does not reveal the answer |
| Entity omission                | Retain surrounding entities but remove their relevant relationship            |
| Evidence fragmentation         | Remove a necessary supporting component from a multi-hop fact                 |

**Conflicting-evidence operations**

| Operation            | Action                                          |
| -------------------- | ----------------------------------------------- |
| Entity substitution  | Replace the correct person or organization      |
| Numeric mutation     | Change a value while keeping units and context  |
| Temporal mutation    | Change a year or time interval                  |
| Relation mutation    | Reverse subject and object                      |
| Polarity mutation    | Change a positive statement into a negative one |
| Attribution mutation | Attribute a fact to the wrong entity            |

These should be schema-constrained actions, not arbitrary creative rewrites.

For example, a numerical mutation should preserve the number format and units rather than accidentally creating a grammatical error.

## **6.3 How the ReAct loop should work**

I would implement something like:

## **Counterfactual editing loop**

1. **Observe**

   Read the original passage, semantic graph, question, answer and evidence anchors.

2. **Plan**

   Decide which factual relation must be removed or modified, and choose a valid edit operation.

3. **Retrieve**

   Check the HNSW memory for similar previously accepted counterfactuals and overused edit patterns.

4. **Act**

   Apply a localized patch to the relevant passage span.

5. **Verify**

   Check grammar, semantic relevance, evidence sufficiency and consistency with the target label.

6. **Reflect**

   Identify failures and propose one repair, if appropriate.

7. **Commit or reject**

   Store the accepted version with its exact edit history, or reject it.

Do not let the agent loop indefinitely.

I recommend:

- Maximum 2 repair attempts.
- Maximum 1–2 targeted edits per candidate, unless a multi-hop example explicitly requires more.
- A fixed token budget.
- Mandatory validation after every patch.
- Reject rather than force an invalid result.

## **6.4 Use explicit patches and diffs**

This is particularly important for your surgical-editing approach.

Instead of asking the agent to return the whole rewritten paragraph, ask it for a patch:

```
{
  "operation": "ENTITY_SUBSTITUTION",
  "target_span_id": "E1",
  "original_span": "Guido van Rossum",
  "replacement": "James Gosling",
  "reason": "Create a plausible entity-attribution conflict"
}
```

Your editing engine can then apply the patch and record the exact difference.

For deletion:

```
{
  "operation": "REMOVE_EVIDENCE",
  "target_span_id": "E1",
  "original_span": "created by Guido van Rossum",
  "replacement": "",
  "preserve_surrounding_context": true
}
```

The advantage is that you can later answer:

- What exactly changed?
- Why was it changed?
- Which claim was targeted?
- Which original evidence was removed?
- Did anything unrelated accidentally change?

This is very helpful for debugging and dataset auditing.

## **6.5 A critical complication: missing evidence is not always equivalent to deleting one sentence**

Imagine the original passage says:

> Guido van Rossum created Python. His programming language was initially released in 1991.

If you simply delete the first sentence, the answer is missing.

But what if the passage says:

> Guido van Rossum is a Dutch programmer. Python was the programming language he created.

Deleting only the first occurrence of the name might leave the answer easily inferable.

Therefore, your agent must perform a **global evidence check** for the target claim, not just remove the sentence containing the answer.

For multi-hop claims, remove or mask the necessary chain of facts.

For example:

\\[ A\rightarrow B,\quad B\rightarrow C \\]

If the answer requires both relations, deleting only one may or may not remove answerability depending on other available facts.

The validator needs to check whether the remaining passage still establishes the answer.

# **7. Stage 6 — Make the generation process diversity-aware at every level**

Your HNSW idea becomes even more useful when it controls the edit strategy itself, not just the original passage generation.

Consider these examples of conflicting passage generation:

- 10,000 examples created by changing people's names.
- 8,000 examples created by changing dates.
- 5,000 examples created by changing numbers.

Even if the original passages are diverse, your negative dataset could become repetitive.

So maintain separate diversity statistics for:

1. Original source passages.
2. Abstract semantic graphs.
3. Question-answer claims.
4. Missing-evidence edit operations.
5. Conflicting-evidence edit operations.
6. Final edited passages.

Your generation scheduler should select underrepresented combinations.

For example:

| Topic      | Missing operation        | Conflicting operation |
| ---------- | ------------------------ | --------------------- |
| Science    | Delete causal evidence   | Change quantity       |
| History    | Remove temporal evidence | Change attribution    |
| Technology | Remove entity relation   | Substitute entity     |
| Geography  | Remove location          | Change location       |
| Business   | Omit financial evidence  | Change fiscal year    |
| Biology    | Remove mechanism         | Reverse relation      |

This is an example of a _coverage matrix_, not a requirement to fill every possible combination.

You can prioritize underrepresented combinations according to the current dataset statistics.

### **One more sophisticated idea: edit-strategy memory**

Store every accepted edit as an abstract record:

```
{
  "edit_id": "EDIT_001",
  "topic": "Programming Languages",
  "target_relation": "created_by",
  "edit_type": "ENTITY_SUBSTITUTION",
  "original_entity_type": "PERSON",
  "replacement_entity_type": "PERSON",
  "difficulty": "EASY",
  "result_label": "CONFLICTING"
}
```

Embed these records as well.

Now, before the agent plans an edit, retrieve similar edit histories.

If entity substitution is already massively overrepresented for programming-language claims, instruct the agent to try another applicable relation or select a different source fact.

This is more powerful than passage-level deduplication alone.

# **8. Stage 7 — Tone and genre as an independent generation dimension**

I agree with including a set of tonalities, but I would separate _tone_, _genre_ and _writing structure_.

These are related but different.

| Dimension     | Examples                                                     |
| ------------- | ------------------------------------------------------------ |
| Genre         | News report, encyclopedia, textbook, technical documentation |
| Tone/register | Formal, neutral, conversational, academic                    |
| Structure     | Paragraph, dialogue, list, table, transcript                 |
| Complexity    | Simple, intermediate, expert                                 |
| Length        | Short, medium, long                                          |

Avoid relying too much on emotional tones such as persuasive, aggressive or promotional in the first dataset version. They can introduce changes in factual stance, not simply surface style.

A more useful starting distribution could be:

- 30% encyclopedic / informational.
- 20% news / report.
- 15% technical documentation.
- 15% educational / textbook.
- 10% conversational / Q&A.
- 10% structured records / bullet lists.

These are proposed experimental sampling weights, not fixed requirements.

**Very important:** Keep style distribution approximately balanced across all three labels.

Otherwise, the model might learn:

> Formal writing = Supported; conversational writing = Missing.

You want the model to learn evidence relationships, not presentation cues.

# **9. Stage 8 — Quality-control system: don't trust the editing agent**

This will determine whether your project produces a research-quality dataset or just a large amount of synthetic text.

I would use separate validators for separate failure types.

The generation agent should never be allowed to approve its own edit.

## **9.1 Five quality gates**

**Gate 1 — Edit integrity**

Deterministic + graph comparison

Did the agent actually perform the intended modification? Did it accidentally modify unrelated facts?

**Gate 2 — Evidence sufficiency**

Independent verifier

Does the Supported version establish the answer? Does the Missing version genuinely fail to establish it?

**Gate 3 — Contradiction verification**

Independent verifier

Does the conflicting version actually contain an assertion incompatible with the reference answer?

**Gate 4 — Naturalness and coherence**

Language evaluator

Does the passage read like a realistic retrieved document, or does it look artificially edited?

**Gate 5 — Novelty and diversity**

HNSW + statistics

Is the example sufficiently different from previously accepted passages, facts and edit patterns?

### **Gate 1: Graph-diff verification**

This is a particularly useful feature of your architecture.

Remember, you already have a Semantic Blueprint for the original passage.

After an edit, run fact extraction again.

Compare:

\\[ G\_{\text{original}} \quad\text{versus}\quad G\_{\text{edited}} \\]

For a Missing variant, the intended behaviour is:

\\[ G\_{\text{edited}} = G\_{\text{original}} - \\{f\_{\text{target}}\\} \\]

For a Conflicting variant:

\\[ G\_{\text{edited}} = G\_{\text{original}} - \\{f\_{\text{target}}\\} + \\{f\_{\text{mutated}}\\} \\]

These are conceptual targets; the actual diff should operate on facts and qualifiers, not simply delete every triple containing a particular entity.

For all other unrelated facts:

\\[ f_j^{\text{original}} \approx f_j^{\text{edited}} \\]

This gives you a measurable definition of surgical editing.

For more complicated passages, graph extraction can itself be imperfect, so use the original evidence spans and deterministic patch logs alongside the graph comparison.

### **Gate 2: Evidence-sufficiency verification**

Give the validator:

- Original question.
- Reference answer.
- Edited passage.
- Original source evidence.
- Target label (for the internal validation process only).

Ask it to judge whether the edited passage establishes the answer, and require exact evidence spans.

For quality control, you can use the target label. But for a separate blind evaluation, don't expose the intended label.

Expected results:

| Variant     | Answer support | Contradiction |
| ----------- | -------------- | ------------- |
| Supported   | Yes            | No            |
| Missing     | No             | No            |
| Conflicting | No             | Yes           |

This is a very useful validation table because it gives you an explicit logical specification.

### **Gate 3: Check whether conflicting passages are genuinely conflicting**

This requires extra care.

A passage about Java being developed by James Gosling is relevant to the topic of programming languages, but it does not necessarily contradict a claim about who developed Python.

It may be a distractor, not a direct contradiction.

I suggest preserving two subtypes:

- `EXPLICIT_CONTRADICTION`
- `MISLEADING_DISTRACTOR`

For the latter, store the competing entity or relationship responsible for the distraction.

If the distractor does not assert anything incompatible with the target question, classify it as Missing Evidence with a `DISTRACTOR_PRESENT` metadata flag. This prevents you from accidentally mixing semantically different classes.

### **Gate 4: Naturalness**

Run a separate coherence evaluator and compare the edited text with the original.

Check:

- Grammatical correctness.
- Sentence transitions.
- Discourse consistency.
- Natural information flow.
- Absence of unnatural gaps.
- No references such as "the deleted information" or "the correct answer".

One issue with surgical deletion is that it can produce passages that are obviously edited.

For example:

> Python was developed. It was released in 1991.

This might be grammatical, but it is an unnatural deletion artifact depending on the original sentence.

The editing agent should therefore make the smallest necessary grammatical repair without accidentally restoring the answer.

### **Gate 5: Novelty**

Perform a second HNSW search for the completed candidate.

Then compare it with close neighbours using:

- Semantic graph similarity.
- Passage embedding similarity.
- Fact-set overlap.
- Edit-strategy frequency.
- Source and entity reuse frequency.

Reject or reroute overly repetitive examples.

# **10. One critical issue with your approach: the model might learn editing artifacts**

This is probably the biggest methodological risk I see.

Your approach produces controlled minimal pairs, which is excellent for causal analysis.

But the model may learn shortcuts.

For example:

- Supported passages are always original.
- Missing passages are always shorter.
- Conflicting passages always contain an incorrect person's name.
- Every missing passage has an awkward transition.
- Every conflicting passage has one obviously changed number.

Then the model may classify based on these superficial features instead of learning evidence sufficiency.

There are several ways to prevent this.

## **10.1 Introduce multiple transformation types per class**

Do not let a class be associated with one editing operation.

For Missing:

- Evidence deletion.
- Evidence fragmentation.
- Partial relation omission.
- Relevant alternative context.
- Removal of one component of multi-hop evidence.

For Conflicting:

- Entity substitution.
- Temporal mutation.
- Numerical mutation.
- Relation reversal.
- Incorrect attribution.

## **10.2 Apply neutral transformations to Supported examples too**

For example, take the supported passage and also perform:

- Faithful paraphrasing.
- Sentence reordering where logically safe.
- Neutral stylistic transformation.
- Chunk-boundary changes.
- Removal of redundant but nonessential details.

Now Supported doesn't simply mean "unedited original."

## **10.3 Control passage lengths across labels**

A Missing passage should not systematically be shorter than Supported.

You can preserve most of the surrounding material, replace omitted evidence with equally relevant background, or use natural source chunks of similar lengths.

## **10.4 Maintain two evaluation suites**

I would actually create two separate benchmark suites.

**Benchmark A: Controlled counterfactual benchmark**

Uses original passages and surgical variations.

Its strength is causal control: you know precisely which fact has changed.

**Benchmark B: Natural retrieval benchmark**

Uses real retrieved contexts from different documents and sources, including naturally occurring irrelevant, incomplete and contradictory evidence.

Its strength is realism and generalization.

You need both.

The first can establish whether a verifier understands the intended evidence relationship in controlled conditions. The second establishes whether that ability transfers to actual retrieval situations.

# **11. Stage 9 — Dataset lineage and splitting**

There is one subtle improvement I would make to your original question-ID splitting idea.

Your new architecture has a richer lineage:

```
Source document
    |
    +-- Original passage
          |
          +-- Fact F1
          |     |
          |     +-- Claim Q1
          |            |
          |            +-- Supported variant
          |            +-- Missing variant
          |            +-- Conflicting variant
          |
          +-- Fact F2
                |
                +-- Claim Q2
                       |
                       +-- Supported variant
                       +-- Missing variant
                       +-- Conflicting variant
```

Therefore, maintain:

- `source_document_id`
- `passage_family_id`
- `fact_group_id`
- `claim_id`
- `question_group_id`
- `variant_family_id`

All variants of a target question must remain together.

More importantly, if two claims originate from the same source document and share facts, you should avoid accidentally splitting related source material across train and test.

I recommend:

1. Deduplicate source documents.
2. Create groups of related documents and fact clusters.
3. Split those groups.
4. Generate all descendants inside the assigned split.

Use separate HNSW memory/index configurations for each split, so test examples cannot influence training-generation decisions or leak information through retrieved examples.

Your test benchmark should also include held-out sources and preferably held-out topic or entity groups.

# **12. Stage 10 — English first, multilingual expansion later**

I agree with this decision.

I would not introduce Bengali and Banglish generation until the English pipeline has passed its quality tests.

There are two reasons:

1. You want to debug the generation and verification architecture without introducing another source of errors.
2. You need to know whether failures come from evidence reasoning or language understanding.

Once the English dataset is stable, expand each passage family.

But I wouldn't simply machine-translate the finished three variants and declare the multilingual dataset complete.

The translation process can accidentally:

- Restore omitted information.
- Remove a contradiction.
- Change entity relations.
- Introduce a different meaning.
- Make Banglish unnaturally formal.

A better multilingual process:

\\[ \text{English semantic blueprint} \rightarrow \text{Native Bengali generation} \rightarrow \text{Banglish adaptation} \rightarrow \text{Independent evidence verification} \\]

Use the underlying fact graph and edit history to preserve the intended label.

Retain the original English record as the canonical parent of its multilingual descendants.

**One particularly good experiment:** Train on English, then evaluate on Bengali and Banglish before adding multilingual examples. After that, test whether multilingual fine-tuning improves transfer.

This gives you a meaningful cross-lingual generalization study.

# **13. One refinement: use TWO semantic abstraction stages, not just one**

I would actually make your abstract-graph idea more powerful by separating it into two representations.

This is an improvement to the architecture I described above.

### **A. Pre-generation Blueprint**

Before generating a passage, the planner creates a short abstract plan.

For example:

```
{
  "topic": "Artificial Intelligence",
  "subtopic": "Distributed training",
  "concept": "Communication bottlenecks in large-scale model training",
  "entities": [
    "GPU clusters",
    "Network interconnects"
  ],
  "relations_to_cover": [
    "communication_overhead",
    "gradient_synchronization",
    "scaling_efficiency"
  ],
  "passage_genre": "technical_explanation",
  "tone": "neutral",
  "difficulty": "intermediate",
  "target_fact_density": 3
}
```

There is no essay here. It is just an abstract description of what you intend to generate.

Now retrieve similar blueprints from HNSW.

If many existing passages already cover gradient synchronization and GPU communication overhead, the planner can choose another underrepresented aspect of distributed training.

Only after the novelty check passes does it generate the actual passage.

### **B. Post-generation Semantic Blueprint**

After producing the passage, extract its actual factual content:

- Entities.
- Relations.
- Atomic facts.
- Numerical and temporal qualifiers.
- Evidence spans.
- Candidate questions.

This is the representation we use for generating and validating counterfactual edits.

So the complete loop becomes:

**Topic scheduler**

**Pre-generation semantic blueprint**

**HNSW retrieval feedback**

Find similar previous generation plans.

**Passage generation**

**Post-generation factual graph extraction**

**Claim and question generation**

**Surgical counterfactual editing**

**Quality validation and HNSW index update**

&#x20;Repeat

This is much closer to what I would implement.

# **14. How to organize the agents**

I would avoid creating one enormous autonomous agent that performs the entire pipeline.

Instead, use specialized agents with strict input/output contracts.

| Agent                 | Responsibility                                                 | Tools                          |
| --------------------- | -------------------------------------------------------------- | ------------------------------ |
| Topic Planner         | Explore topic hierarchies and choose underrepresented concepts | Topic graph, coverage database |
| Content Planner       | Generate abstract passage blueprints                           | Semantic HNSW search           |
| Corpus Generator      | Create natural passages from blueprints and sources            | LLM, source material           |
| Semantic Extractor    | Extract facts, entities and relationships                      | LLM, structured parser         |
| Question Generator    | Generate atomic claims and QA pairs                            | Fact graph                     |
| Counterfactual Editor | Surgically remove or alter target evidence                     | Read/replace/delete tools      |
| Evidence Verifier     | Verify support, absence and contradiction                      | NLI/LLM, evidence spans        |
| Quality Evaluator     | Evaluate coherence, naturalness and novelty                    | LLM, embeddings                |
| Dataset Curator       | Commit accepted examples and update indices                    | Database, Parquet, HNSW        |

The Counterfactual Editor should be the agent with the most tightly constrained permissions.

It should not be able to rewrite original source documents or ground-truth answers.

### **A useful implementation principle**

Separate the following:

- **Planner:** Decides what needs to be generated.
- **Executor:** Performs a particular generation or edit.
- **Verifier:** Checks whether the result satisfies the intended properties.
- **Curator:** Accepts or rejects the result.

This separation also makes your pipeline easier to evaluate experimentally.

# **15. Actual dataset structure**

I would preserve the original passage and all its descendants in one lineage structure.

For example:

```
DOC_001
  |
  +-- PASSAGE_001
        |
        +-- SEMANTIC_GRAPH_001
        |
        +-- CLAIM_001
        |     |
        |     +-- SUPPORTED_001
        |     +-- MISSING_001
        |     +-- CONFLICTING_001
        |
        +-- CLAIM_002
              |
              +-- SUPPORTED_002
              +-- MISSING_002
              +-- CONFLICTING_002
```

The final training records can still be stored separately in JSONL or Parquet.

I would preserve this metadata:

```
{
  "sample_id": "SAMPLE_001",
  "source_document_id": "DOC_001",
  "passage_family_id": "PASSAGE_001",
  "semantic_graph_id": "GRAPH_001",
  "fact_id": "FACT_001",
  "claim_id": "CLAIM_001",
  "variant_family_id": "VARIANT_001",

  "question": "...",
  "reference_answer": "...",
  "context": "...",

  "label": "MISSING_EVIDENCE",

  "edit_history": [
    {
      "operation": "REMOVE_EVIDENCE",
      "target_fact": "FACT_001"
    }
  ],

  "generation_metadata": {
    "generator": "...",
    "prompt_version": "...",
    "genre": "...",
    "tone": "..."
  },

  "quality": {
    "evidence_valid": true,
    "edit_integrity": true,
    "naturalness": 0.95,
    "novelty": 0.91
  },

  "lineage": {
    "parent_sample": "SUPPORTED_001",
    "split_group": "GROUP_001"
  }
}
```

This will make it possible to study the entire creation process instead of simply publishing a flat collection of text passages.

# **16. A few additional improvements worth considering**

There are four things I would consider beyond your original proposal.

### **A. Two corpus-generation tracks**

Maintain:

**Track 1 — Source-grounded corpus**

Real articles, reports, documentation and other trusted source material.

**Track 2 — Synthetic corpus**

LLM-generated passages based on abstract blueprints and, where appropriate, verified factual material.

This gives you both real-world linguistic diversity and controlled semantic coverage.

Keep their provenance separate.

### **B. Multiple claims per passage, but avoid excessive reuse**

Generating 2–5 questions per passage is a good starting point.

But don't generate 50 questions from the same paragraph simply because the fact extractor found 50 candidate relationships.

That would create a large number of highly correlated training samples.

Control passage-family contribution and make the train/test split source-aware.

### **C. Counterfactual minimal-pair evaluation**

Because you retain the original passage and its edited versions, you can construct an interesting evaluation:

Give a verifier:

- Original passage + question.
- Missing variant + same question.
- Conflicting variant + same question.

Then measure whether its prediction changes correctly.

You can also measure its sensitivity to the targeted edit and robustness to unrelated changes.

This is a significant advantage of your approach: you have controlled contrastive examples with known edit histories.

### **D. Keep an explicit failed-generation corpus**

Store rejected examples with their rejection reasons.

For example:

```
MISSING_GENERATION_FAILED:
- Answer still inferable from remaining context.

CONFLICTING_GENERATION_FAILED:
- Modified entity does not contradict target fact.

DIVERSITY_REJECTION:
- Near duplicate of an existing passage.

LANGUAGE_REJECTION:
- Awkward or unnatural wording.

EDIT_INTEGRITY_FAILURE:
- Unrelated factual relations changed.
```

Over time, this becomes a valuable dataset for improving the generation agent and its prompts.

You can even analyse which operations have the highest acceptance rates and which tend to produce bad examples.

# **17. Recommended implementation sequence**

I would not build the entire multi-agent system simultaneously.

Here is the order I would use.

1. **Build the corpus and topic planner**

   First milestone

   Start with approximately 500–1,000 source passages, combining source-grounded and synthetic material.

   Build the topic graph, pre-generation blueprints and metadata.

2. **Build semantic extraction**

   Extract facts, entities, relations, qualifiers and source spans.

   Manually inspect a sample to determine whether the fact graph is reliable enough to drive generation.

3. **Implement HNSW memory**

   Index semantic blueprints and accepted passages separately.

   Implement nearest-neighbour feedback, cluster saturation and basic diversity selection.

4. **Generate claims and questions**

   Start with 2–5 atomic claims per passage.

   Validate every claim against the original passage before using it for edits.

5. **Implement surgical editing**

   Begin with deterministic patches and constrained LLM edit proposals.

   Add the ReAct-style planning, execution and repair loop after the basic editor works.

6. **Build independent validation**

   Implement graph-diff checks, evidence sufficiency verification, contradiction checking, naturalness and human audits.

7. **Run a controlled pilot**

   Generate 5,000–10,000 accepted records, inspect label quality, diversity and real-context generalization.

8. **Scale and expand languages**

   Add asynchronous distributed generation, then Bengali and Banglish adaptation after the English benchmark stabilizes.

# **18. My final assessment: what makes your approach interesting?**

I see three particularly valuable research properties in this architecture.

**1. Controlled counterfactual generation**

You can hold the original source, question and answer constant while changing the evidence context.

This lets you investigate whether a model actually responds to changes in evidence.

**2. Semantic diversity rather than superficial linguistic diversity**

Your pre-generation blueprint, concept graph, HNSW retrieval and edit-strategy memory give you mechanisms to avoid generating 10,000 variations of the same underlying fact.

**3. Full generation lineage**

You can trace every training example back to its original source passage, extracted fact, question, editing operation and validation result.

That improves reproducibility and makes data-quality analysis much more meaningful.

## **One research-level caution**

Your counterfactual generation process is powerful, but controlled synthetic examples and naturally occurring retrieval errors are not interchangeable.

A Missing passage created by deleting a sentence is not necessarily equivalent to an actually retrieved passage that happens to omit the answer. Similarly, a synthetically modified fact may not behave like a naturally occurring contradiction between two documents.

That is why I would retain both:

- A **controlled counterfactual dataset** generated through your surgical editing pipeline.
- A **natural retrieval-context dataset** generated from actual source retrieval and human-verified.

You can train on both and evaluate them separately.

This separation will make your research claims significantly stronger.

## **The architecture I would ultimately pursue**

# **Corpus-First Counterfactual Generation**

A compact description of the proposed research system

**Topic Graph**

Controls semantic coverage and exploration.

**Abstract Blueprint + HNSW**

Prevents repetitive content planning.

**Source Passage Corpus**

Creates diverse, realistic source material.

**Fact Graph + Atomic Claims**

Establishes exactly what information the passage contains.

**ReAct Surgical Editor**

Produces Supported, Missing and Conflicting variants.

**Evidence and Diversity Validators**

Ensure correctness, naturalness, novelty and lineage.

**Tri-State Dataset**\

English first

Bengali/Banglish later

**My strongest recommendation:** Build the two-stage semantic representation (pre-generation blueprint and post-generation fact graph) and the HNSW novelty-feedback mechanism before implementing the full ReAct editing agent. Those components establish the structure of the data factory. The agent then becomes a controlled executor operating on well-defined facts and passage spans, rather than an autonomous essay writer.

That is the direction I would take.

<q>
1. i disagree with the idea "that passages should be factually correct" , ...incorrect passages penalizes extrinsic hallucinations (ie., answering from its own weights)
2. To clarify: Here Each passage (and its 3 variants) + its-claim-set is a single data instance , ....so there is not risk of train-test split , ...and nothing the lose even if there is inter-passage contradictions , and also to clarify: [supported variant --> support all the claim from that corresponding claim set , contradicted variant --> contradict all the claim from that corresponding claim set , unsupported variant --> not support all the claim from that corresponding claim set]... </q>

I think your clarification changes the architecture in an important way. And I agree with both of your points. My previous pipeline was unnecessarily imposing a real-world factual-correctness requirement on the source passages, and I was treating individual passage variants too independently.

Your intended task is better understood as **context-conditioned evidence verification, with controlled counterfactual passage families**.

Let's redefine the system around that.

# **1. First correction: passages do NOT need to be factually correct in the real world**

This is an important distinction.

There are two different notions of truth:

**World truth:** Is a statement actually true in reality?

**Contextual support:** Does the supplied passage support the claim?

Your model is being trained for the second.

For example, suppose you generate this synthetic passage:

> The fictional Orion programming language was developed by Alice Brown in 2012. It was initially designed for embedded systems.

And generate the claim:

> Alice Brown developed Orion.

Even though Orion and Alice Brown are fictitious, the claim is fully supported by the passage.

Therefore:

SUPPORTED

&#x20;is the correct label.

You do not need to verify whether the passage's facts are true in the real world.

In fact, deliberately generating passages containing counterfactual information can be useful for your research.

Consider:

| Context                                  | Claim                        | Expected result |
| ---------------------------------------- | ---------------------------- | --------------- |
| Orion was developed by Alice Brown.      | Alice Brown developed Orion. | Supported       |
| Orion was developed by Alice Brown.      | Bob Smith developed Orion.   | Contradicted    |
| Orion was designed for embedded systems. | Alice Brown developed Orion. | Missing         |

Now consider the third example.

A model might already know that a real-world programming language was developed by someone else. But it should not use that knowledge to claim that the supplied context establishes the answer.

This is precisely the behaviour you want to encourage:

\\[ \boxed{\text{Evidence in context} > \text{Parametric knowledge}} \\]

More precisely, the model must base its _evidence-sufficiency decision_ on the supplied context, rather than treating its pretrained knowledge as evidence contained in that context.

This gives you a powerful experimental opportunity: deliberately construct contexts whose content disagrees with well-known world knowledge and test whether the verifier follows the context.

**A necessary distinction:** Your synthetic passage should still be internally coherent and linguistically natural. It does not need to be externally factual, but its intended semantic content must be unambiguous.

# **2. Second correction: the unit of construction is a passage family**

I now understand your data structure.

You aren't generating three independent training examples from three unrelated passages.

You are creating one structured data instance containing:

- Original passage.
- Supporting claim set.
- Supported passage variant.
- Contradicted passage variant.
- Unsupported passage variant.

Let's formalize it.

Let the original passage be:

\\[ P=\\{s_1,s_2,\ldots,s_n\\} \\]

Let the associated claim set be:

\\[ C=\\{c_1,c_2,\ldots,c_k\\} \\]

The generation system constructs three variants:

\\[ P_S,\quad P_C,\quad P_U \\]

Where:

- \\(P_S\\): Supported variant.
- \\(P_C\\): Contradicted variant.
- \\(P_U\\): Unsupported variant.

The **same claim set remains fixed** across all three variants.

## **One passage family = one data instance**

**Original passage&#x20;**\\(P\\)

Source text and semantic blueprint

**Fixed claim set&#x20;**\\(C\\)

\\(\\{c_1,c_2,c_3,\ldots,c_k\\}\\)

S

**Supported**

All claims supported.

C

**Contradicted**

All claims contradicted.

U

**Unsupported**

No claim established.

All three variants share the same claim-set ID, passage-family ID and data-split assignment.

This also addresses your train-test concern.

**All descendants of one passage family are assigned to the same split.** You will not have the Supported version in training and its Contradicted version in testing.

And you're right that contradictions between different passage families are not inherently a problem.

For example:

- Family A says a fictional company was founded in 2012.
- Family B says a fictional company was founded in 2015.

There is no inherent problem with both existing in the dataset. Your task is to determine the relationship between a particular context and its associated claims, not to construct a globally consistent knowledge base.

I would still prevent accidental duplication of the same source passage or passage family across splits, but there's no requirement to reconcile unrelated passages into one globally consistent fact database.

# **3. The three variants need strict logical conditions**

Your clarification also suggests an important refinement to the validator.

For every claim \\(c_i\\):

| Variant   | Required relationship                      |
| --------- | ------------------------------------------ |
| \\(P_S\\) | Supports \\(c_i\\)                         |
| \\(P_C\\) | Contradicts \\(c_i\\)                      |
| \\(P_U\\) | Neither supports nor contradicts \\(c_i\\) |

Formally:

\\[ \forall c_i\in C: \\]

\\[ \operatorname{Rel}(P_S,c_i)=\text{Entailment} \\]

\\[ \operatorname{Rel}(P_C,c_i)=\text{Contradiction} \\]

\\[ \operatorname{Rel}(P_U,c_i)=\text{Neutral} \\]

This is a strong design because it eliminates ambiguity between your three classes.

One subtlety: "not support all claims" could mean that at least one claim is unsupported, while other claims remain supported.

I recommend the stricter interpretation above for your primary dataset: every claim in the set should be unsupported by the Unsupported variant. Otherwise, the passage is partially supported, which introduces a mixed-label problem.

You can retain such mixed examples separately rather than silently assigning them to one of the three classes.

# **4. How I would now modify your surgical editing architecture**

The editing agent should not be given an individual claim in isolation.

It should receive the entire claim set and generate a coordinated transformation.

For example:

**Original passage:**

> The fictional Orion language was developed by Alice Brown in 2012. Orion uses a register-based virtual machine and was designed primarily for embedded applications.

**Claim set:**

\\[ C=\\{c_1,c_2,c_3\\} \\]

- \\(c_1\\): Alice Brown developed Orion.
- \\(c_2\\): Orion was developed in 2012.
- \\(c_3\\): Orion was designed for embedded applications.

SUPPORTED VARIANT

> Orion was developed by Alice Brown in 2012. It uses a register-based virtual machine and was designed primarily for embedded applications.

All three claims are supported.

CONTRADICTED VARIANT

> Orion was developed by Bob Smith in 2015. It uses a register-based virtual machine and was designed primarily for desktop applications.

All three claims are explicitly contradicted.

UNSUPPORTED VARIANT

> Orion is a programming language that uses a register-based virtual machine. Its design focuses on efficient execution and resource management.

None of the three target claims is established or contradicted.

Notice that the Unsupported passage is still informative and relevant. It does not become a meaningless paragraph simply because we removed the answer-bearing information.

This is the type of coordinated editing I would want your agent to perform.

# **5. A change I would make to your Semantic Blueprint**

Previously, I suggested extracting facts and relations from the original passage.

Now I would explicitly divide the Blueprint into two parts:

**A. Passage-level semantic representation**

What is the overall passage about?

**B. Claim-target representation**

Which specific factual propositions are selected for the tri-state transformation?

For example:

```
{
  "passage_id": "P001",

  "semantic_blueprint": {
    "topic": "Programming Languages",
    "subtopics": [
      "Programming Language Design",
      "Virtual Machines",
      "Embedded Systems"
    ],
    "entities": [
      "Orion",
      "Alice Brown"
    ],
    "passage_summary": "Description of a fictional programming language and its origins."
  },

  "claim_set": [
    {
      "claim_id": "C1",
      "claim": "Alice Brown developed Orion.",
      "fact_type": "ENTITY_RELATION"
    },
    {
      "claim_id": "C2",
      "claim": "Orion was developed in 2012.",
      "fact_type": "TEMPORAL"
    },
    {
      "claim_id": "C3",
      "claim": "Orion was designed for embedded applications.",
      "fact_type": "PURPOSE"
    }
  ],

  "variants": {
    "supported": "P001_S",
    "contradicted": "P001_C",
    "unsupported": "P001_U"
  }
}
```

This separates the overall content from the specific claims you want to challenge.

It also means you can generate a different claim set from the same passage if it contains enough independent factual relationships.

# **6. A particularly valuable research opportunity: context-prior conflict**

Your first correction exposes something I think should become an explicit part of your benchmark.

Consider a model that already knows the real-world answer.

Example:

Question:

> Who developed Python?

Claim:

> Guido van Rossum developed Python.

Now give it three contexts:

| Context      | What it says                                                                      | Expected label |
| ------------ | --------------------------------------------------------------------------------- | -------------- |
| Supported    | Python was developed by Guido van Rossum.                                         | Supported      |
| Contradicted | Python was developed by James Gosling.                                            | Contradicted   |
| Unsupported  | Python is a high-level programming language used for automation and data science. | Unsupported    |

The model has strong pretrained knowledge about this question.

But it must produce three different contextual judgments.

This is a direct test of whether the verifier is using the supplied passage or falling back on parametric knowledge.

I would explicitly measure:

**Parametric Knowledge Intrusion Rate**

The proportion of Unsupported examples where the model incorrectly predicts Supported because its pretrained knowledge supplies the answer.

**Context Sensitivity**

The fraction of passage families where the model changes its classification appropriately across all three variants.

**Counterfactual Consistency**

Whether the model correctly follows an intentionally modified context even when that context conflicts with its learned world knowledge.

These metrics could become interesting contributions to your research.

# **7. Revised architecture — reflecting your actual intended methodology**

I would now organize the system like this:

## **Corpus-first, family-level generation**

1. **Corpus generation**

   Hierarchical topic exploration, random news/content ingestion, multiple genres and tonalities.

2. **Semantic planning**

   Abstract passage blueprints, concept graph and HNSW-based novelty feedback.

3. **Base passage generation**

   Generate diverse, coherent passages without requiring real-world factual correctness.

4. **Semantic extraction**

   Extract entities, relations, facts and qualifiers.

5. **Claim-set generation**

   Generate a small set of atomic claims supported by the original passage.

6. **Coordinated counterfactual editing**

   Create three variants from the same base and claim set.

7. **Family-level verification**

   Check that all claims satisfy the intended relation in each respective variant.

8. **Diversity and quality filtering**

   Validate passage naturalness, edit integrity, semantic novelty and claim coverage.

9. **Family-level storage and splitting**

   Preserve all three variants together as one indivisible data family.

## **Final point: what I would now make the central research objective**

Rather than describing your work simply as multilingual hallucination detection, I would frame its central objective as:

**Training models to perform evidence-conditioned verification under controlled changes to the supplied context, while resisting interference from pretrained parametric knowledge.**

That framing captures both of your clarifications.

It also creates a much more interesting research question:

> When the same claim is evaluated against semantically related contexts that alternately support, contradict, or omit its evidence, can a language model consistently follow the context rather than its own parametric knowledge?

I think that should be one of the central hypotheses around which you design the dataset and subsequent experiments.
