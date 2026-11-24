---
version: 3.2.0
stage: edit_plan
description: Plan coordinated localized patches for one target variant of a document.
---
You are a careful editor. You will modify ONE document so that a FIXED set of claims ends
up in a REQUIRED relation to it. The claim set never changes. Only the document changes.

TARGET RELATION FOR EVERY CLAIM: {{label}} — {{label_objective}}

DOCUMENT EXCERPTS (sentences are numbered; every patch target must be one of these):
{{sentences_json}}

Only the sentences relevant to the claims are shown. The rest of the document stays exactly
as it is: never propose a patch for a sentence that is not listed, never refer to unseen
text, and assume unlisted sentences neither establish nor contradict any claim.

CLAIM SET (every one of these must reach the target relation):
{{claims_json}}

Each claim lists `mentions`: sentences that plausibly state that claim's facts, not just the
primary evidence sentence. A long document often restates the same fact in an introduction, a
body section and a conclusion. EVERY listed mention must be patched for CONTRADICTED and
UNSUPPORTED, and all of them must reach the same target relation:
- CONTRADICTED: change every mention to the SAME incompatible alternative. If one sentence says
  38 and another still says 52, the document becomes self-contradictory and is rejected.
- UNSUPPORTED: remove/defuse the claiming information in EVERY mention. If any mention still
  states it, the document still establishes the claim.
- SUPPORTED: leave the mentions intact.

PRIOR ATTEMPT FEEDBACK (empty on the first attempt):
{{feedback}}

ALLOWED OPERATIONS
{{allowed_operations}}

HOW TO EDIT
- Produce the smallest set of localized patches that changes every claim's relation.
- "original_text" must be copied VERBATIM from one of the numbered excerpts. It must not span
  sentences and must appear exactly once in that sentence.
- Give the sentence ID you are editing.
- A patch replaces "original_text" with "replacement_text". For a deletion, set
  "replacement_text" to "".
- Every claim ID must appear in at least one patch's "affected_claim_ids".
- For CONTRADICTED and UNSUPPORTED, every `mentions` entry must be the target of at least one
  patch that lists that claim ID.
- Every `mentions` entry has a `sentence_id`; use exactly those IDs. Do not invent sentence IDs.
- Do not rewrite the whole passage. Do not reorder sentences. Do not add new sentences
  unless replacing an entire clause/sentence is unavoidable.
- Keep the result grammatical and natural. Repair broken grammar inside the same patch.
- Keep the result about the same length (within 25%).
- Preserve all unrelated facts. Do not touch sentences that carry no target claim.
- Preserve the source's register and narrative stance (person, tense, stance, comic or argued
  mode). Do not flatten a story into a summary, a first-person account into third person, or a
  comic passage into a neutral one.
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
