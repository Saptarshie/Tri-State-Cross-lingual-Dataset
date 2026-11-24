---
version: 1.0.0
stage: blueprint
description: Plan one compact passage before any prose is written.
---
You are planning a single short English passage for a corpus of evidence-verification
examples. You produce an abstract plan only. Do not write the passage.

TOPIC PATH: {{topic_path}}
TOPIC FOCUS: {{main_concept}}
SOURCE MATERIAL (may be empty): {{source_excerpt}}
GENRE: {{genre}}
TONE: {{tone}}
STRUCTURE: {{structure}}
COMPLEXITY: {{complexity}}
TARGET LENGTH: {{token_min}}-{{token_max}} tokens
TARGET FACT COUNT: {{target_fact_count}}
SEED INTENT: {{seed_intent}}

NOVELTY FEEDBACK (prior generations; use it to choose a different angle):
{{novelty_report}}

Design a plan that:
1. is specific enough that a reader learns 3-5 concrete, checkable facts;
2. avoids the overrepresented concepts, relations and entity combinations listed above;
3. includes at least one non-trivial relation (causal, comparative, temporal, numeric or
   purpose) rather than only naming things;
4. is internally consistent, so a short passage can state it plainly;
5. can contain fictional entities, places, products, studies or events. Real-world truth
   is not required and must not be a constraint.

Return JSON only:
{
  "main_concept": "one sentence",
  "subtopics": ["3-6 short noun phrases"],
  "planned_entity_types": ["software", "organization", "person", "place", "study", "..."],
  "planned_relation_types": ["developed_by", "located_in", "increased_by", "..."],
  "planned_fact_types": ["definition", "mechanism", "relationship", "temporal", "numerical", "causal", "comparative", "procedural"],
  "target_fact_count": 4
}

Do not include a passage, a claim, or a label. Do not explain.
