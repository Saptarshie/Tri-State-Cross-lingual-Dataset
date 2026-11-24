---
version: 2.0.0
stage: topics_expand
description: Expand one topic node into bounded, diverse child concepts.
---
You are a topic-graph planner for an English passage-generation corpus.

Expand the topic below into at most {{max_children}} child concepts. Children must be
genuinely distinct subject areas that a long informative document ({{target_tokens_min}}-{{target_tokens_max}}
tokens) could develop on their own. Do not produce near-synonyms, do not produce questions, and
do not write explanations.

Prefer specific, generative concepts over vague umbrella labels. Avoid children that
repeat the parent's own name. Concepts may legitimately be fictional or specialized.

TOPIC: {{topic_name}}
DESCRIPTION: {{topic_description}}
EXISTING CHILDREN (do not duplicate): {{existing_children}}
CURRENT DEPTH: {{depth}} of maximum {{max_depth}}

Return JSON only, exactly this shape:
{"subtopics": [{"name": "...", "description": "one clause", "importance": 0.0}]}

Rules:
- 3 to {{max_children}} items.
- "name" is 1-5 words, Title Case.
- "description" is at most 18 words.
- "importance" is between 0.0 and 1.0.
