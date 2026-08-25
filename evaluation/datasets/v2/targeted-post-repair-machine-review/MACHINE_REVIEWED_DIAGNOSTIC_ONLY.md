# MACHINE_REVIEWED_DIAGNOSTIC_ONLY — v2 持续 reject 修复后定点机器复审

> 本报告为 **MACHINE_REVIEWED_DIAGNOSTIC_ONLY** 机器复审诊断报告：只提供机器语义复审证据，**不是人工终审、不是上线批准、不是 v2.1 准入**；不修改任何标注，不生成任何 overlay。

## 一、输入（盲态）

- 复审条数：5（en-052 / en-055 / mixed-016 / mixed-026 / multi-014）。
- 每条仅含 query、previous_turns（仅 query 文本）、should_refuse、修复后的 acceptable_answer_points、evidence 与完整 scoped chunks；不含 case_id、历史 decision、第三轮 notes、cohort、split 或任何「持续 reject」标签与预期 verdict。
- 盲包 targeted-input-pack.jsonl 逐字节确定可重建。

## 二、模型与契约

- 模型：deepseek-v4-pro，temperature=0.0，max_tokens=8000。
- 契约：语义仲裁 JSON 契约 + coherence 校验（verdict 与 support/refusal 映射、逐答案点 support index 连续唯一）。

## 三、逐条结果

| index | semantic_verdict | parse_retries | transport_retries |
|---|---|---|---|
| 1 | confirmed | 0 | 0 |
| 2 | confirmed | 0 | 0 |
| 3 | confirmed | 0 | 0 |
| 4 | confirmed | 0 | 0 |
| 5 | confirmed | 0 | 0 |

## 四、逐条留痕

| index | prompt_sha256 | response_sha256 |
|---|---|---|
| 1 | 2d2ecdbac85f4e2a… | 77507c1b62e7c70a… |
| 2 | 91fa2acd69860d21… | 1817af2934dec338… |
| 3 | fa2e8419df22d290… | 6653bd25120257eb… |
| 4 | 8dcc561656475f31… | 4850c3fab6cc5857… |
| 5 | 4319c802dffefbca… | a58ccd2f2267e05e… |

原始响应、解析重试与传输重试记录见 raw-responses.jsonl。

## 五、结论

5 条全部通过机器复审（confirmed）仅代表机器语义证据；**不是人工终审、不是人工批准、不是 v2.1 准入**。

