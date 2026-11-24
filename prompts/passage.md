---
version: 3.0.0
stage: passage
description: Generate one short passage (single-call mode) from a soft blueprint.
---
Write one short English passage from the plan below. The plan is a SOFT DIRECTION, not a
summary to restate: you may and should add concrete detail that the plan does not spell out.
It must read like a genuine retrieved chunk from the stated genre, not like an encyclopedic
essay and not like a list of disconnected facts.

PLAN:
{{blueprint_json}}

SOURCE MATERIAL (may be empty; use only for factual grounding and never copy long spans):
{{source_excerpt}}

STYLE PRIMING
{{style_priming}}

CONSTRAINTS
- Length: about {{token_min}}-{{token_max}} model tokens (roughly {{word_min}}-{{word_max}} words).
- Genre: {{genre}}. Tone: {{tone}}. Narrative: {{narrative}}. Structure: {{structure}}. Complexity: {{complexity}}.
- State {{target_fact_count}}-{{max_facts}} concrete, checkable facts, including at least one
  numeric, temporal, causal, comparative or purpose relation when the plan allows it.
- Name every entity explicitly. Do not use "it", "they" or "this" to refer to the main
  subject across sentences when a name is clearer.
- The passage may be fictional or counterfactual. Real-world truth is irrelevant. Keep it
  internally consistent.
- Do not mention claims, labels, evidence, tasks, or the fact that this is generated data.
- Do not end with a moral, summary sentence, or a sentence about what is not known.
- No headings, no markdown, no bullet characters unless the structure says bulleted.
- Plain prose only. No meta commentary.

PRIOR ATTEMPT FEEDBACK (empty on the first attempt; fix exactly what it lists):
{{feedback}}

Return JSON only: {"text": "..."}
