# DeepSeek v4 Pro 语义仲裁一致性审计（coherence audit）

> 只读审计：未修改任何标注、盲包、chunks、manifest 或生产配置；违反 case 的定点重审见 coherence-recheck/。

## 一、输入与复算

- blank pack / llm-filled：各 150 行；第三轮分布 confirmed 68 / reject 82 / needs_followup 0。
- 盲态输入：102 条（82 争议 + 20 对照）；盲包重建与现有 blind-input-pack.jsonl 一致；prompt SHA 0aa95c8106b37b0f…。
- 仲裁输出：102 条，index 1..102 连续唯一。

## 二、语义一致性契约

- 拒答题（should_refuse=true）：no_answer / partial_topic_overlap_only → semantic_verdict=confirmed；substantive_answer_exists → reject；unclear → needs_followup；answer_point_supports 必须为空。
- 可答题（should_refuse=false）：每个答案点必须恰好一条 assessment，index 连续且不重复；存在 unsupported → 不得 confirmed；全部有支持→ 不得 reject；needs_followup 必须写明无法判断的具体理由。
- 每条：合法 verdict、非空 rationale、reviewer 模型名、index 与盲态输入一致。

## 三、违反统计

- 总条数：102；违反条数：4；违反规则数：4。

| 规则 | 条数 |
|---|---|
| supports_index_not_contiguous | 3 |
| refusal_assessment_mismatch | 1 |

## 四、违反 case 明细

| index | case_id | 角色 | 层 | semantic_verdict | 违反规则 |
|---|---|---|---|---|---|
| 20 | en-047 | disputed | 跨文档 | confirmed | supports_index_not_contiguous |
| 37 | mixed-028 | disputed | 跨文档 | reject | supports_index_not_contiguous |
| 38 | mixed-029 | disputed | 跨文档 | confirmed | supports_index_not_contiguous |
| 76 | noanswer-052 | disputed | 拒答 | reject | refusal_assessment_mismatch |

原模型输出摘录（每个违反 case）：

### index 20（en-047，disputed / 跨文档）
- semantic_verdict: confirmed
- verdict_rationale: 第一个答案点概括了 SQLite SELECT 页面存在 JOIN 小节并涵盖多种 JOIN 操作符，从证据 chunks 中可找到相关操作符描述，虽未逐字出现“SQLite SELECT 页有 JOIN 专门小节”但属于忠实转述；第二个答案点在 PostgreSQL 教程目录中直接出现“2.6. Joins Between Tables”，逐字支持。因此两个答案点均被证据支持。
- answer_point_supports: [{"answer_point_index": 0, "chunk_id": "8b191b241b93_chunk_39", "excerpt": "If the join-operator is a \"LEFT JOIN\" or \"LEFT OUTER JOIN\"... If the join-operator is a \"RIGHT JOIN\"... A \"FULL JOIN\" or \"FULL OUTER JOIN\"...", "support_level": "faithful_paraphrase"}, {"answer_point_index": 0, "chunk_id": "8b191b241b93_chunk_40", "excerpt": "There is no difference between the \"INNER JOIN\", \"JOIN\" and \",\" join operators... The \"CROSS JOIN\" join operator produces the same result as the \"INNER JOIN\", \"JOIN\" and \",\" operators", "support_level": "direct_snippet"}, {"answer_point_index": 1, "chunk_id": "761b22915b5e_chunk_0", "excerpt": "2.6. Joins Between Tables", "support_level": "direct_snippet"}]

### index 37（mixed-028，disputed / 跨文档）
- semantic_verdict: reject
- verdict_rationale: 答案点1“两者都让数据变化驱动界面更新”在所提供的语料中无法找到支持，尤其是Vue分块未提及界面更新驱动；答案点2中Vue部分有直接证据，React部分可视为忠实转述，但整体答案因答案点1无依据而不可接受。
- answer_point_supports: [{"answer_point_index": 0, "chunk_id": "", "excerpt": "", "support_level": "unsupported"}, {"answer_point_index": 1, "chunk_id": "5927c70d0f8e_chunk_9", "excerpt": "In Vue 3, data is made reactive by leveraging JavaScript Proxies", "support_level": "direct_snippet"}, {"answer_point_index": 1, "chunk_id": "993955159403_chunk_7", "excerpt": "State: 组件的记忆...在 React 中，这种特定于组件的记忆被称为状态。你可以用 useState Hook 为组件添加状态。", "support_level": "faithful_paraphrase"}]

### index 38（mixed-029，disputed / 跨文档）
- semantic_verdict: confirmed
- verdict_rationale: 答案点断言术语表 free-threaded build 与新特性自由线程章节在构建方式上一致，都指 --disable-gil/禁用 GIL 的自由线程构建。术语表 chunk 明确记载“在编译之前使用了 --disable-gil 选项进行配置”，新特性 chunk 也指出“可以附带 --disable-gil 选项使用源代码来构建 CPython”，两者在构建方式上完全吻合，支持答案点。
- answer_point_supports: [{"answer_point_index": 0, "chunk_id": "81544765752f_chunk_3", "excerpt": "可以附带 --disable-gil 选项使用源代码来构建 CPython", "support_level": "within_chunk_outside_snippet"}, {"answer_point_index": 0, "chunk_id": "c9fd20815ea8_chunk_7", "excerpt": "在编译之前使用了 --disable-gil 选项进行配置", "support_level": "direct_snippet"}]

### index 76（noanswer-052，disputed / 拒答）
- semantic_verdict: reject
- verdict_rationale: 提供的chunks与evidence均为空，没有任何语料可支撑回答，因此拒答合理。
- refusal_assessment: no_answer

## 五、结论

- 本审计为机器语义证据，未修改任何标注；违反 case 将以相同盲态输入、同一模型、temperature=0.0 定点重审（最多 3 次），提示词显式包含 verdict 与 support/refusal 映射规则；三次仍不合格按规则固定为 needs_followup 并记录失败证据。
- 结论：**不得视为人工终审、人工批准或上线批准；不构成任何v2.1 进入决策。**

