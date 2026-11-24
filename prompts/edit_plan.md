---
version: 1.0.0
stage: edit_plan
description: Plan coordinated localized patches for one target variant.
---
You are a careful editor. You will modify ONE passage so that a FIXED set of claims ends
up in a REQUIRED relation to it. The claim set never changes. Only the passage changes.

TARGET RELATION FOR EVERY CLAIM: {{label}} — {{label_objective}}

BASE PASSAGE (sentences are numbered; this exact text will be patched):
{{sentences_json}}

CLAIM SET (every one of these must reach the target relation):
{{claims_json}}

PRIOR ATTEMPT FEEDBACK (empty on the first attempt):
{{feedback}}

ALLOWED OPERATIONS
{{allowed_operations}}

HOW TO EDIT
- Produce the smallest set of localized patches that changes every claim's relation.
- "original_text" must be copied VERBATIM from one sentence above. It must not span
  sentences and must appear exactly once in that sentence.
- Give the sentence ID you are editing.
- A patch replaces "original_text" with "replacement_text". For a deletion, set
  "replacement_text" to "".
- Every claim ID must appear in at least one patch's "affected_claim_ids".
- Do not rewrite the whole passage. Do not reorder sentences. Do not add new sentences
  unless replacing an entire clause/sentence is unavoidable.
- Keep the result grammatical and natural. Repair broken grammar inside the same patch.
- Keep the result about the same length (within 25%).
- Preserve all unrelated facts. Do not touch sentences that carry no target claim.
- The result must read as an ordinary passage. Never mention claims, evidence, labels,
  truth, verification, uncertainty about authorship, or "the text".
- Do not use hedges that imply the original statement was wrong ("actually", "in fact",
  "contrary to reports").

FOR {{label}} SPECIFICALLY
{{label_instructions}}

Return JSON only:
{
  "patches": [
    {
      "operation": "ENTITY_SUBSTITUTION",
      "target_sentence_id": "S2",
      "original_text": "exact substring",
      "replacement_text": "new text",
      "affected_claim_ids": ["C1"],
      "reason": "short reason",
      "preserve_surrounding_context": true
    }
  ],
  "reasoning": "one or two sentences"
}

No prose outside the JSON.
