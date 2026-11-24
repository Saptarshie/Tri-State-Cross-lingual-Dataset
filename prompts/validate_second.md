---
version: 1.1.0
stage: validate_second
description: Second independent relation check with a different decomposition.
---
You are a strict evidence auditor. Your job is to prevent two mistakes: accepting a
passage that only looks related, and treating silence as contradiction.

Work in two steps, but return only the final JSON.

STEP 1 (internal): summarize, in one line per claim, exactly what the passage says about
the claim's subject and relation. Quote the deciding words. If the passage never mentions
the subject, say so.

STEP 2: assign each claim one relation using this rubric.
- ENTAILED only if a single sentence (or an immediately adjacent paraphrase) states the
  claim's specific entities, relation and value, read literally. Do not chain separate facts
  from different sentences to construct the claim; if the specific value/entity/relation is
  never stated in one place, it is NEUTRAL.
- CONTRADICTED only if the passage makes the claim false by asserting an incompatible
  alternative. A missing statement, a different topic, a vague gesture, or "the passage
  does not say" is never a contradiction.
- NEUTRAL if the passage neither makes the claim true nor false.
- UNCERTAIN only if the passage contradicts itself about the claim or the claim is unreadable.

External facts are irrelevant. If the passage says a fictional company was founded in
1998, then that is what the passage establishes, whatever the real world says. Never
"correct" a passage using your own knowledge.

PASSAGE:
{{passage_json}}

CLAIMS:
{{claims_json}}

Return JSON only:
{
  "passage_summary": "one sentence",
  "claim_relations": [
    {"claim_id": "C1", "relation": "NEUTRAL", "confidence": 0.8, "sentence_id": "S4", "quote": "exact words or empty string", "rationale": "short"}
  ]
}

Every claim must appear exactly once.
