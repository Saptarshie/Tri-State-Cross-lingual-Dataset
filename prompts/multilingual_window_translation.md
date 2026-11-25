---
version: 0.1.0
stage: translate_window
description: Translate one sentence-aligned window under a profile.
---
You are translating one window of a long document for a research dataset.
Translate meaning, not words. The source window and the target claim ledger are
both authoritative; the previous and next context are provided only to preserve
cohesion and must not be translated again.

TARGET PROFILE
{{profile_json}}

VARIANT LABEL
{{label}}

EXPECTED RELATION FOR THIS VARIANT (all claims)
{{expected_relation}}

CLAIM LEDGER
{{claim_cards_json}}

TARGET CLAIMS (use these exact target formulations when a claim appears)
{{target_claims_json}}

GLOSSARY
{{glossary_json}}

GLOBAL SYNOPSIS (context only; do not translate)
{{global_synopsis}}

PREVIOUS CONTEXT (do not translate)
{{prev_context}}

PREVIOUS TARGET FOR REPAIR (empty on the first attempt; do not translate it)
{{previous_target_json}}

SOURCE WINDOW (translate every sentence exactly once)
{{source_text}}

SENTENCE IDS IN THIS WINDOW
{{sentence_ids_json}}

NEXT CONTEXT (do not translate)
{{next_context}}

RULES
- Preserve entities, numbers, dates, negation, modality, scope and causal direction.
- Preserve the variant's stance: a supporting passage must still support the
  target claims, a contradicting passage must still contradict them, and an
  unsupported passage must still leave them genuinely unsupported. Never add a
  claim just to make the passage easier to classify.
- Follow the profile's script, syntax, register, code-switching and terminology
  policy. Native-script profiles must use the native script; romanized profiles
  must not contain native-script characters.
- Do not add headings, notes, explanations, or facts absent from the source.
- Keep strict one-to-one sentence alignment. Return exactly one target string
  for each source sentence id. Do not split one source sentence across two
  target ids, and do not merge two source sentences into one target id. You may
  split or join clauses **inside the same target string**, but never across
  sentence ids. No content may be dropped.
- If `previous_target_json` is non-empty, this is a REPAIR, not a fresh
  translation. Change only the sentence(s) named in the reviewer feedback.
  Every other sentence must keep its previous target text exactly. Never
  reintroduce a defect that an earlier repair already fixed.
{{feedback_block}}

Return JSON only:
{
  "sentences": [
    {"sentence_id": "S1", "target_text": "..."}
  ]
}
Every input sentence id must appear exactly once.
