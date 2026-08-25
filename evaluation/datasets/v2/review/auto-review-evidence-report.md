# v2 证据驱动二次审阅报告（LLM_ASSISTED_SECOND_PASS）

> 自动二审：独立审阅 LLM 逐条核验草稿真值；审阅人身份固定为
> `LLM_ASSISTED_SECOND_PASS`。本报告与 auto-review 产物均为 LLM
> 辅助结果，**未经人工批准**，绝不伪称人工审核。

## 全量汇总（不按 split 分析）

- 审阅条数：150
- 审阅模型：deepseek-chat
- confirmed：150
- reject：0
- needs_followup：0
- 草稿与二审一致率（confirmed / 总数）：150/150 = 100.0%

### 置信度分布

| 置信度 | 条数 |
|---|---|
| high | 150 |
| medium | 0 |
| low | 0 |

### 问题类别分布（reject / needs_followup 提及）

| 问题类别 | 提及次数 |
|---|---|
| answerable_refusal | 0 |
| chunk_source_relevance | 0 |
| snippet_sufficiency | 0 |
| multi_turn_chain | 0 |
| other | 0 |

### 待修复清单

无（全部 confirmed）。

## fail-closed 校验

- 输入（草稿 / chunks）SHA 与 pack manifest 一致；
- 每条 evidence SHA-256 复算一致；case 无重复、无遗漏；
- reviewer 身份固定为 `LLM_ASSISTED_SECOND_PASS`；
- 原始草稿未被改写（本次审阅为只读，未修改任何标注）。

## 结论

**LLM-assisted candidate review complete**（仍为 LLM_ASSISTED 状态，未经人工批准；下一步：人工终审或进入 dev-only v2.1 校准）
