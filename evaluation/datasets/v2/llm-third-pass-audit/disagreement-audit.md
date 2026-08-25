# v2 第三轮机器审阅分歧只读根因审计

> 本报告仅描述 82 条 reject 的分歧结构：区分可由确定性文本校验
> 确认的文本事实与仅属 LLM 语义判断的成分。**本审计不判定第三轮
> 或此前审阅孰对，不改动任何数据，不生成 overlay，不解除 v2.1
> 人工门槛。**

## 复算分布（与第三轮 manifest / report 一致性已验证）

- 总条数：150
- confirmed：68
- reject：82
- needs_followup：0

## 按 should_refuse 汇总

- 答案题：67/119（56.3%）
- 拒答题：15/31（48.4%）

## 按 query_type 汇总

| 维度 | 总数 | reject | 占比 |
|---|---|---|---|
| cross_document | 31 | 28 | 90.3% |
| metadata | 19 | 6 | 31.6% |
| mixed_intent | 12 | 6 | 50.0% |
| multi_turn | 24 | 13 | 54.2% |
| no_answer | 30 | 15 | 50.0% |
| single_fact | 34 | 14 | 41.2% |

## 按 language 汇总

| 维度 | 总数 | reject | 占比 |
|---|---|---|---|
| en | 60 | 36 | 60.0% |
| mixed | 30 | 17 | 56.7% |
| zh | 60 | 29 | 48.3% |

## 拒答题与跨文档题

- 拒答题（should_refuse=True）：15/31（48.4%）
- 跨文档题（relevant_source_ids > 1）：28/30（93.3%）

## 诊断类别分布

| 类别 | 条数 |
|---|---|
| answer_point_not_verbatim_in_snippet | 39 |
| evidence_mapping_or_source_error | 0 |
| cross_document_coverage_gap | 28 |
| refusal_keyword_overlap_only | 15 |
| refusal_substantive_answerability_claim | 0 |
| other_or_unclassified | 0 |

## 文本事实与语义裁决

- 答案题 reject 67 条：答案点未逐字出现于证据 snippet 的断言 67/67 条机械成立；其中 3 条答案点存在于证据 chunk 全文（证据截取边界现象，需人工确认片段选择）。
- 拒答题 reject 15 条：全部为关键词重合模板（15/15），关键词重合是文本事实，但“重合 ⇒ 可答”是语义判断。
- 机械可裁决（理由被文本层面否定）：0 条；需语义裁决：82 条。

## 谱系限制

- third-pass manifest 未声明任何输入/输出 SHA 字段：本审计只能校验其计数与报告统计的一致性，无法验证第三轮审阅的生成链完整性（产物 SHA 链见 manifest.json）。

## 结论

本审计不判定第三轮或此前审阅孰对；不改动任何数据；不生成
overlay；不解除 v2.1 人工门槛。

