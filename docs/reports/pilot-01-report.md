# Quality report — 2026-11-24T17:53:16+00:00

Config hash: `2c0f4f715062b3c6`

## Counts

| Metric | Value |
|---|---|
| Accepted families | 14 |
| Variants | 42 |
| Claims | 51 |
| Quarantined candidates | 2 |
| Acceptance rate | 77.8% |
| Estimated cost | $0.1239 |
| Cost per family | $0.0089 |

## Distributions

- Claim counts: {4: 7, 3: 3, 2: 2, 5: 2}
- Claim types: {'COMPARATIVE': 7, 'PROCEDURAL': 10, 'TEMPORAL': 11, 'LOCATION': 2, 'NUMERICAL': 8, 'ENTITY_RELATION': 4, 'CAUSAL': 4, 'PURPOSE': 5}
- Edit operations: {'TEMPORAL_MUTATION': 8, 'RELATION_REVERSAL': 7, 'NUMERICAL_MUTATION': 18, 'POLARITY_CHANGE': 4, 'REPLACE_CLAUSE': 45, 'ENTITY_SUBSTITUTION': 8, 'NEUTRAL_REWRITE': 14, 'CATEGORY_SUBSTITUTION': 2}
- Genres: {'news_report': 3, 'faq_answer': 1, 'encyclopedia_entry': 2, 'field_report': 2, 'textbook_excerpt': 1, 'technical_explanation': 3, 'research_summary': 2}
- Tones: {'neutral_explanatory': 4, 'analytical': 2, 'formal': 3, 'conversational': 2, 'academic': 2, 'concise_journalistic': 1}
- Structures: {'paragraph': 2, 'two_paragraph': 2, 'numbered_procedure': 4, 'bulleted_explanation': 4, 'qa_pair': 2}
- Splits: {'train': 14}
- Passage tokens: {'mean': 127.4, 'min': 72, 'max': 169}

## Validation

- Validator agreement (mean): 1.0
- Graph-diff misses: 62
- Human audit flags: 1

## Rejections by reason

{'llm_permanent': 2}

## Topic coverage

| Topic | Accepted | Target |
|---|---:|---:|
| Science | 1.0 | 6 |
| Health > Diagnostics | 0.0 | 4 |
| Technology > Consumer Devices | 2.0 | 4 |
| Science > Astronomy | 0.0 | 4 |
| Culture > Film Production | 2.0 | 4 |
| Technology | 3.0 | 6 |
| Business | 1.0 | 6 |
| Law and Policy > Data Protection | 0.0 | 4 |
| Culture > Museums | 0.0 | 4 |
| Environment > Wildlife Conservation | 0.0 | 4 |
| Education | 0.0 | 6 |
| Sport | 0.0 | 6 |
| Sport > Endurance Training | 0.0 | 4 |
| Business > Logistics | 0.0 | 4 |
| Science > Materials Science | 2.0 | 4 |
| Environment | 1.0 | 6 |
| Health | 1.0 | 6 |
| Environment > Urban Water Systems | 2.0 | 4 |
| History | 0.0 | 6 |
| Culture | 1.0 | 6 |
| Health > Nutrition | 2.0 | 4 |
| Business > Manufacturing | 0.0 | 4 |
| Technology > Programming Languages | 0.0 | 4 |
| Science > Marine Biology | 0.0 | 4 |
| Technology > Databases | 0.0 | 4 |
| Technology > Networking | 0.0 | 4 |
| Education > Vocational Training | 0.0 | 4 |
| Business > Consumer Finance | 2.0 | 4 |
| History > Maritime Trade | 0.0 | 4 |
| Law and Policy | 0.0 | 6 |

## Top stages by cost

| Stage | Model | Calls | Tokens | Cost | Avg ms |
|---|---|---:|---:|---:|---:|
| variant_UNSUPPORTED | deepseek/deepseek-v4.1-flash | 16 | 71445 | $0.017051 | 28998.8 |
| variant_CONTRADICTED | deepseek/deepseek-v4.1-flash | 16 | 55896 | $0.012638 | 20266.8 |
| extract_CONTRADICTED | xiaomi/mimo-v2.6-flash | 16 | 46089 | $0.011053 | 24675.8 |
| passage | deepseek/deepseek-v4.1-flash | 17 | 61158 | $0.0106 | 14350.0 |
| extract | xiaomi/mimo-v2.6-flash | 14 | 41037 | $0.009879 | 15660.2 |
| validation_UNSUPPORTED | google/gemini-3.8-flash | 16 | 42465 | $0.009733 | 12525.0 |
| extract_SUPPORTED | xiaomi/mimo-v2.6-flash | 14 | 38887 | $0.009277 | 17750.9 |
| extract_UNSUPPORTED | xiaomi/mimo-v2.6-flash | 16 | 36986 | $0.008619 | 14805.1 |
| claims | xiaomi/mimo-v2.6-flash | 14 | 38708 | $0.008152 | 14681.6 |
| validation_CONTRADICTED | google/gemini-3.8-flash | 16 | 31877 | $0.006645 | 8085.9 |

