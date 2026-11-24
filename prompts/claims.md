---
version: 1.0.0
stage: claims
description: Select atomic, independently checkable claims supported by the passage.
---
Select atomic claims that the passage below clearly supports. A claim is a single factual
proposition that can be checked against a passage without outside knowledge.

PASSAGE:
{{passage_json}}

EXTRACTED FACTS (reference only; you may rephrase):
{{facts_json}}

CONSTRAINTS
- Select {{min_claims}} to {{max_claims}} claims.
- Each claim must be ONE proposition. Never join two independent facts with "and".
- Each claim must be stated as a full declarative sentence naming its entities, with no
  pronouns whose antecedent is outside the claim.
- Each claim must be supported by the passage as written. Fictional content is fine.
- Do not use world knowledge to add, correct or qualify anything.
- Each claim must map to one or more fact IDs and quote the exact supporting passage text.
- Claims must not paraphrase each other. Prefer different relation types (attribution,
  temporal, numerical, purpose, comparison, process).
- Avoid claims that merely restate the passage's title or topic.
- Keep each claim under 25 words.

Prefer claims that a careless reader could get wrong if they ignored the passage, and
avoid trivial named-entity lookup when the passage supports a richer relation.

Return JSON only:
{
  "claims": [
    {
      "claim_text": "...",
      "fact_ids": ["F1"],
      "claim_type": "ENTITY_RELATION|TEMPORAL|NUMERICAL|CAUSAL|COMPARATIVE|DEFINITIONAL|PROCEDURAL|LOCATION|PURPOSE",
      "difficulty": "easy|medium|hard",
      "intent": "who|what|when|where|why|how|how_many|which",
      "evidence": [{"sentence_id": "S1", "quote": "exact substring"}]
    }
  ]
}
