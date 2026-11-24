---
version: 1.0.0
stage: validate
description: Independently classify each claim's relation to a passage.
---
Decide how the passage below relates to each claim.

Judge ONLY the supplied passage. Do not use outside knowledge, common sense about the
real world, or anything you believe to be true. The passage may describe fictional
entities, places, products, studies or events; that is allowed and is not an error.

Definitions:
- ENTAILED: the passage asserts or clearly establishes the claim. A paraphrase of the
  claim's content by the passage still counts. Evidence anywhere in the passage counts.
- CONTRADICTED: the passage asserts something explicitly incompatible with the claim, for
  example a different value, a different entity, a reversed relation, or a negated
  version. Merely omitting the claim is NOT contradiction.
- NEUTRAL: the passage neither establishes nor contradicts the claim. It may discuss the
  topic, mention related entities, or give background that does not settle the claim.
- UNCERTAIN: the passage is internally inconsistent about the claim, is unintelligible,
  or you cannot tell whether it establishes it.

PASSAGE:
{{passage_json}}

CLAIMS:
{{claims_json}}

For each claim, give the relation, a confidence between 0 and 1, the sentence ID that
decides it (or null), and a short verbatim quote (or ""). Do not skip claims. Do not add
claims. Decide claim by claim independently.

Return JSON only:
{
  "claim_relations": [
    {"claim_id": "C1", "relation": "ENTAILED", "confidence": 0.93, "sentence_id": "S2", "quote": "exact words", "rationale": "short"}
  ]
}
