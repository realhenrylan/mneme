# v2 标注覆盖矩阵（coverage matrix）

> 来源：`v2-cases-draft.jsonl`（LLM_ASSISTED 草稿，未终审）

## 类型 × 语言
| 类型 | zh | en | mixed | 合计 |
|---|---|---|---|---|
| single_fact | 17 | 12 | 5 | 34 |
| metadata | 7 | 7 | 5 | 19 |
| cross_document | 10 | 14 | 7 | 31 |
| multi_turn | 10 | 9 | 5 | 24 |
| mixed_intent | 5 | 4 | 3 | 12 |
| no_answer | 11 | 14 | 5 | 30 |
| **合计** | 60 | 60 | 30 | 150 |

## 语言 / 难度 / band_target / construction

| 维度 | 分布 |
|---|---|
| 语言 | en=60, mixed=30, zh=60 |
| 难度 | easy=36, hard=52, medium=62 |
| band_target | low_answerable=20, low_refuse=20, near_band=19, normal=91 |
| construction | cross_doc=21, follow_up=24, fuzzy_query=20, natural=55, out_of_corpus=30 |

## 多轮链

| 链 | 轮次 | 语言 | 主题 |
|---|---|---|---|
| multi-011 | 4 | zh | multi-011 |
| multi-015 | 3 | en | multi-015 |
| multi-016 | 2 | en | multi-016 |
| multi-018 | 2 | en | multi-018 |
| multi-020 | 2 | en | multi-020 |
| multi-022 | 3 | zh | multi-022 |
| multi-025 | 3 | mixed | multi-025 |
| multi-028 | 2 | mixed | multi-028 |
| multi-030 | 3 | zh | multi-030 |

## 每文档用例数

| 文档 | 语言 | 用例数 |
|---|---|---|
| art-of-war.txt | en | 1 |
| nodejs-fs.md | en | 9 |
| postgresql-tutorial.md | en | 14 |
| python-datetime-zh.md | zh | 2 |
| python-glossary-zh.md | mixed | 13 |
| python-tutorial-en.md | en | 13 |
| python-tutorial-zh.md | zh | 40 |
| python-whatsnew313-zh.md | zh | 6 |
| react-learn-zh.md | mixed | 8 |
| rfc3986.txt | en | 7 |
| rust-book-core.md | en | 10 |
| sqlite-lang.md | en | 20 |
| vue-guide-zh.md | zh | 6 |
