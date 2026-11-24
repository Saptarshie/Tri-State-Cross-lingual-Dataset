---
version: 3.0.0
stage: blueprint
description: Plan a long-form document before any prose is written.
---
You are planning a long-form English document for a corpus of evidence-verification examples.
You produce an abstract plan only. Do not write the document.

The plan is a SOFT DIRECTION for a much longer text. It should fix the subject, angle and
territory, but it must leave room for the document to add concrete entities, sequences,
measurements, comparisons and consequences that are not listed here.

TOPIC PATH: {{topic_path}}
TOPIC FOCUS: {{main_concept}}
SOURCE MATERIAL (may be empty): {{source_excerpt}}
GENRE: {{genre}}
TONE: {{tone}} — {{tone_directive}}
NARRATIVE: {{narrative}} — {{narrative_directive}}
STRUCTURE: {{structure}}
COMPLEXITY: {{complexity}}
STYLE PRECEDENCE: tone governs diction/rhythm/formality; narrative governs
structure/point-of-view/stance. Keep the narrative inside the tone's register.
TARGET DOCUMENT LENGTH: {{token_min}}-{{token_max}} tokens (model tokens)
TARGET FACT COUNT: {{target_fact_count}}
SEED INTENT: {{seed_intent}}

NOVELTY FEEDBACK (prior generations; use it to choose a different angle):
{{novelty_report}}

Design a plan that:
1. is specific enough that the document can state many concrete, checkable facts;
2. avoids the overrepresented concepts, relations and entity combinations listed above;
3. includes several non-trivial relations (causal, comparative, temporal, numeric, purpose)
   rather than only naming things;
4. is internally consistent, so the document can develop it without contradicting itself;
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
