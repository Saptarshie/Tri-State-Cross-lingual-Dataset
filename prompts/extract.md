---
version: 1.2.0
stage: extract
description: Extract a fact graph with exact evidence anchors from a passage or excerpt.
---
Extract the factual structure of the passage below. Work only from the passage text.

The passage may be one excerpt of a larger document. Extract facts only from the text shown,
and only facts that this text states. Every sentence is listed with an ID. For every fact you
extract, you must give the ID of the sentence that states it and quote the exact words that
carry the fact. Quotes must be verbatim substrings of that sentence. Do not paraphrase inside
"quote". Do not infer facts from surrounding context that is not shown.

PASSAGE:
{{passage_json}}

Extract:
- a one-sentence abstract summary (no evaluation, no labels);
- entities with a short type (person, organization, software, place, event, study,
  product, metric, other);
- atomic facts as subject-predicate-object triples. One fact per proposition. Split
  compound statements into separate facts. Keep predicates short and relation-like
  (developed_by, released_in, located_in, increased_by, part_of, designed_for, ...).
- qualifiers when they matter: year, value, unit, condition, comparison, negation.

Do not invent facts. Do not use outside knowledge. Do not mark a fact as verified or
unverified. Confidence is your extraction certainty, not real-world truth.

PRIOR ATTEMPT FEEDBACK (empty on the first attempt):
{{feedback}}

Return JSON only:
{
  "summary": "...",
  "entities": [{"name": "...", "entity_type": "..."}],
  "facts": [
    {
      "subject": "...",
      "predicate": "...",
      "object": "...",
      "qualifiers": {"year": "2012"},
      "sentence_id": "S2",
      "quote": "exact substring of that sentence",
      "confidence": 0.95
    }
  ]
}

Fact IDs are assigned by the system, so do not invent them. Extract 4-8 facts.
