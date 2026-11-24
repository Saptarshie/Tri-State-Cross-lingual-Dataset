# Quality report — 2026-11-24T18:05:23+00:00

Config hash: `2c0f4f715062b3c6`

## Counts

| Metric | Value |
|---|---|
| Accepted families | 15 |
| Variants | 45 |
| Claims | 54 |
| Quarantined candidates | 3 |
| Acceptance rate | 83.3% |
| Estimated cost | $0.1383 |
| Cost per family | $0.0092 |

## Distributions

- Claim counts: {4: 7, 3: 4, 2: 2, 5: 2}
- Claim types: {'COMPARATIVE': 7, 'PROCEDURAL': 11, 'TEMPORAL': 12, 'LOCATION': 2, 'NUMERICAL': 9, 'ENTITY_RELATION': 4, 'CAUSAL': 4, 'PURPOSE': 5}
- Edit operations: {'TEMPORAL_MUTATION': 8, 'RELATION_REVERSAL': 8, 'NUMERICAL_MUTATION': 19, 'POLARITY_CHANGE': 5, 'REPLACE_CLAUSE': 49, 'ENTITY_SUBSTITUTION': 8, 'NEUTRAL_REWRITE': 14, 'CATEGORY_SUBSTITUTION': 2}
- Genres: {'news_report': 3, 'faq_answer': 1, 'encyclopedia_entry': 2, 'field_report': 2, 'textbook_excerpt': 1, 'technical_explanation': 3, 'research_summary': 2, 'business_brief': 1}
- Tones: {'neutral_explanatory': 4, 'analytical': 2, 'formal': 3, 'conversational': 2, 'academic': 2, 'concise_journalistic': 1, 'instructional': 1}
- Structures: {'paragraph': 2, 'two_paragraph': 2, 'numbered_procedure': 5, 'bulleted_explanation': 4, 'qa_pair': 2}
- Splits: {'train': 15}
- Passage tokens: {'mean': 128.8, 'min': 72, 'max': 169}

## Validation

- Validator agreement (mean): 1.0
- Graph-diff misses: 65
- Human audit flags: 1

## Rejections by reason

{'llm_permanent': 2, 'claims_insufficient': 1}

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
| Law and Policy > Data Protection | 1.0 | 4 |
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
| Law and Policy | 0.5 | 6 |

## Top stages by cost

| Stage | Model | Calls | Tokens | Cost | Avg ms |
|---|---|---:|---:|---:|---:|
| variant_UNSUPPORTED | deepseek/deepseek-v4.1-flash | 19 | 85183 | $0.02035 | 29454.6 |
| variant_CONTRADICTED | deepseek/deepseek-v4.1-flash | 17 | 58348 | $0.013147 | 20168.3 |
| passage | deepseek/deepseek-v4.1-flash | 19 | 69778 | $0.012098 | 14157.6 |
| extract_CONTRADICTED | xiaomi/mimo-v2.6-flash | 17 | 49500 | $0.01189 | 24092.8 |
| extract | xiaomi/mimo-v2.6-flash | 16 | 45703 | $0.010968 | 14947.5 |
| validation_UNSUPPORTED | google/gemini-3.8-flash | 19 | 47721 | $0.01079 | 11412.8 |
| extract_UNSUPPORTED | xiaomi/mimo-v2.6-flash | 19 | 45893 | $0.010762 | 14751.6 |
| extract_SUPPORTED | xiaomi/mimo-v2.6-flash | 15 | 41469 | $0.009883 | 17829.3 |
| claims | xiaomi/mimo-v2.6-flash | 16 | 43412 | $0.009112 | 15045.2 |
| validation_CONTRADICTED | google/gemini-3.8-flash | 17 | 33503 | $0.006961 | 7861.6 |

