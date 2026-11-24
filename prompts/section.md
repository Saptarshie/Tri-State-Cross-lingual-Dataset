---
version: 1.0.0
stage: section
description: Write one section of a long-form document in a fixed voice.
---
Write ONE section of an English document. Continue the document naturally. Do not write the
whole document, an introduction to the whole document, or a conclusion unless this section is
the last one.

BLUEPRINT (soft direction):
{{blueprint_json}}

DOCUMENT THROUGHLINE:
{{throughline}}

SECTION TO WRITE:
{{section_json}}

ALREADY WRITTEN (do not repeat these points, do not paraphrase them):
{{covered_json}}

END OF THE PREVIOUS SECTION (for continuity; do not copy it):
{{prior_tail}}

STYLE
- Genre: {{genre}}. Tone: {{tone}}. Structure: {{structure}}. Complexity: {{complexity}}.
- Length: about {{token_min}}-{{token_max}} model tokens (roughly {{word_min}}-{{word_max}} words).
- Plain prose. No document title, no section heading, no markdown, no bullet characters
  unless the structure explicitly calls for a list or procedure.
- Name entities explicitly. Do not open every sentence with "it", "they" or "this".
- State concrete, checkable facts: names, numbers, dates, locations, causes, comparisons,
  steps or purposes. Prefer specificity over general commentary.
- The content may be fictional or counterfactual. Keep it internally consistent with the
  blueprint and with what has already been written. Real-world truth is irrelevant.
- Never mention claims, evidence, labels, truth, verification, tasks, or the fact that this
  is generated data. Never address the reader as a dataset consumer.

CONTINUITY RULES
- Start with a sentence that connects to the previous section or opens this section's topic.
- Do not restate the throughline or repeat a sentence already written.
- Introduce new material; if you need an earlier fact, refer to it briefly rather than
  re-explaining it.
- End at a natural stopping point, not with a moral or a summary of the whole document.

PRIOR ATTEMPT FEEDBACK (empty on the first attempt):
{{feedback}}

Return JSON only: {"text": "..."}
