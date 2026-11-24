---
version: 1.0.0
stage: document_plan
description: Expand a soft blueprint into a sectioned long-form document plan.
---
You are planning ONE long-form English document for a retrieval-grounded verification corpus.
You produce an outline only. Do not write the document.

The blueprint below is a SOFT DIRECTION: it fixes the subject, the angle and the general
territory, but it is not a summary to be restated or padded. The finished document should be
10-100 times longer than the blueprint and must add concrete material: specific entities,
sequences, measurements, conditions, comparisons, procedures, findings and consequences.

TOPIC PATH: {{topic_path}}
BLUEPRINT (soft direction):
{{blueprint_json}}
GENRE: {{genre}}
TONE: {{tone}}
STRUCTURE: {{structure}}
COMPLEXITY: {{complexity}}
TARGET DOCUMENT LENGTH: {{token_min}}-{{token_max}} tokens (model tokens)
TARGET SECTION COUNT: {{sections_min}}-{{sections_max}}
TARGET SECTION LENGTH: {{section_tokens_min}}-{{section_tokens_max}} tokens
TARGET CHECKABLE FACTS: about {{target_fact_count}} across the document, spread out
SEED INTENT: {{seed_intent}}
NOVELTY FEEDBACK:
{{novelty_report}}

Design sections that:
1. together cover the subject without repeating one another;
2. each advance the document with new, concrete material rather than restating the blueprint;
3. are ordered so a reader can follow the throughline from beginning to end;
4. each carry at most 1-2 checkable facts worth turning into a claim, placed in different
   sections rather than clustered in the opening;
5. fit the genre and structure (a report, a manual, a study write-up, a policy brief, ...);
6. contain fictional entities, places, products, studies or events where useful. Real-world
   truth is not required and must never constrain the plan.

Section IDs must be S1, S2, S3, ... in reading order. Section token targets must sum to
approximately the document target.

Return JSON only:
{
  "plan_id": "DP_<short>",
  "throughline": "one or two sentences describing what the document establishes",
  "sections": [
    {
      "section_id": "S1",
      "title": "short section title",
      "purpose": "what this section does for the document",
      "target_tokens": 700,
      "key_points": ["concrete point", "concrete point"],
      "entities": ["named entity", "named entity"],
      "relations": ["developed_by", "measured_at"]
    }
  ]
}

No prose, no markdown, no commentary outside the JSON.
