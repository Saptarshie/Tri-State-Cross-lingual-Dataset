---
version: 0.1.0
stage: translate_glossary
description: Resolve family terminology into one target profile.
---
You are the terminology lead for one translated family. Resolve the source
terms below into the target language/variety. Consistency matters more than
elegance: the same source term must have one target term throughout the family.

TARGET PROFILE
{{profile_json}}

SOURCE CLAIM CARDS
{{claim_cards_json}}

SOURCE GLOSSARY SEED
{{glossary_json}}

RULES
- Translate ordinary terms; transliterate proper nouns consistently.
- Keep an established English technical term in English only when the profile
  allows it; otherwise give the conventional target term.
- Numbers, dates and identifiers are not translated.
- Do not introduce entities that are absent from the claims.
- Every seed term must appear exactly once in the output.

Return JSON only:
{
  "glossary": [
    {"source_term": "...", "target_term": "...", "kind": "entity|technical|ordinary|number", "note": ""}
  ]
}
