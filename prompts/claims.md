---
version: 2.0.0
stage: claims
description: Select atomic claims spread across a document from extracted facts.
---
Select atomic claims that the document clearly supports. A claim is a single factual
proposition that can be checked against the document without outside knowledge.

EVIDENCE EXCERPTS (sentences that carry the candidate facts; the document is longer):
{{passage_json}}

CANDIDATE FACTS (each fact occurs in the document; you may rephrase its claim):
{{facts_json}}

CONSTRAINTS
- Select exactly {{target_claims}} claims (at least {{min_claims}}, never more than {{max_claims}}).
- Draw claims from different sections: at least {{min_sections}} distinct sections.
- Each claim must be ONE proposition. Never join two independent facts with "and".
- Each claim must be stated as a full declarative sentence naming its entities, with no
  pronouns whose antecedent is outside the claim.
- Each claim must be supported by the document as written. Fictional content is fine.
- Do not use world knowledge to add, correct or qualify anything.
- Each claim must map to one fact ID (or several only if they state the same proposition) and
  quote the exact supporting text from the excerpt above.
- Claims must not paraphrase each other. Prefer different relation types (attribution,
  temporal, numerical, purpose, comparison, process).
- Avoid claims that merely restate the document's topic or opening framing.
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
