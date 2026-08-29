# v2 人工终审包准备报告

> 本报告只包含全量计数、字段说明与输入 SHA-256，不含任何划分
> 身份、自动审阅结论或评测指标。终审包供真人逐条填写，**尚未进行人工终审**，绝不伪称人工审核。

## 全量计数

- 条数：150
- relevance_level：chunk 122；source 0；none 28
- should_refuse：true 28；false 122
- language：en 60；mixed 30；zh 60
- query_type：cross_document 31；metadata 19；mixed_intent 12；multi_turn 24；no_answer 30；single_fact 34
- 多轮行数（previous_turns 非空）：15
- 带证据行数：122
- 证据条目总数：166

## 字段说明

| 字段 | 说明 |
|---|---|
| case_id | 草稿 case 标识（与 v2 草稿一致） |
| query | 待审阅问题原文 |
| language / query_type | 语言与问题类型 |
| previous_turns | 多轮链中前序轮次（case_id + query），单轮为空 |
| should_refuse | 草稿的拒答判定（true = 判定无法从语料回答） |
| relevance_level | 草稿的证据层级（chunk / source / none） |
| acceptable_answer_points | 草稿答案点列表（拒答行为空） |
| relevant_source_ids | 草稿声明的相关源文件 |
| evidence[] | 每条 chunk 证据：source_id / chunk_id / 连续 snippet / section |
| human_review_decision | 人工填写：confirmed / reject / needs_followup |
| human_reviewer | 人工填写：审阅人标识 |
| human_review_notes | 人工填写：理由（reject / needs_followup 必填） |

## 输入 SHA-256

- draft：08d0d917e9ea06a3c8758ad1bc8e4fcfc14fb98f0cf4ada0e8cc8eaeaa67e730（D:\GitHub\mneme\evaluation\datasets\v2\annotations\v2-cases-draft.jsonl）
- chunks：a23d739aa9876b54cd197d32f16138e9799c74a1a1c6717bb9d232fb6a06d772（D:\GitHub\mneme\data\v2-corpus\chunks\chunks.jsonl）
- chunk_manifest：de5a580bac323e535e86936d71f2d2d714d07408a3c999999d632667342ffa0a（D:\GitHub\mneme\data\v2-corpus\chunks\chunk-manifest.json）
- corpus_manifest：84f04699c07ff1a7a8d13caabba3e377569b217816bb39db73f65df842037943（D:\GitHub\mneme\evaluation\datasets\v2\corpus-manifest.json）
- repair_ledger：24c1bf97c2aac1147165a22779c2882df7f79a118b9539d7df43dc5d5fe3cf7e（D:\GitHub\mneme\evaluation\datasets\v2\review\repair-ledger.jsonl）

## fail-closed 校验

- 行数 150、case_id 唯一且与草稿一致；
- 证据 chunk/source 存在、snippet 连续；人工字段初始全部为空；
- 行键与证据键均为严格白名单，无任何划分 / 自动审阅结构字段；
- 输入 SHA 漂移、缺失 chunk、重复/遗漏 case、禁止字样出现均失败。

## 结论

人工终审包已准备，尚未进行人工终审；不得进入 v2.1。

填写判定口径（详见 HUMAN_REVIEW_INSTRUCTIONS.md）：
- confirmed：问题、答案点、拒答判定和所有证据都正确；
- reject：存在事实、证据、来源或拒答错误；
- needs_followup：人工无法确定，需要补充来源或证据。

仅当 150 条均由真人填写后，才可另行讨论如何导入人工审阅结果；
本工具绝不自动填值。
