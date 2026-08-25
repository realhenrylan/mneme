# v2.0.1 自动审阅 acceptance 文档

> **版本**：v2.0.1
> **生效日期**：2026-08-07
> **状态**：用户授权自动审阅完成，待 v2.1 准入决策

---

## 1. 前置条件变更

**原要求**：v2.1 准入前必须完成真人逐条审核（150 条人工终审）。

**当前状态**：用户已明确授权，**跳过真人逐条审核**，由子代理完成 150 条证据审阅。
审核结果作为 v2.1 的自动化前置条件。

> ⚠️ **重要声明**：本自动审阅是用户授权的 LLM 自动审阅，**不是人工审核**。
> 审阅执行者为 LLM（`deepseek-v4-pro`），不代表人工批准、不代表生产上线批准。

---

## 2. 自动审阅执行摘要

| 维度 | 值 |
|------|-----|
| 审阅模型 | `deepseek-v4-pro` |
| 参数 | temperature=0.0, max_tokens=8000 |
| 禁止模型 | `gpt-5.6-sol`, `deepseek-v4-flash`, 回退模型, 联网 |
| 审阅人身份 | `LLM_ASSISTED_OWNER_AUTHORIZED` |
| 输入版本 | v2.0.1 draft + chunks + chunk-manifest |
| 审阅范围 | 150 条全量 |
| 独立重审 | `en-052`, `en-055`, `mixed-016`, `mixed-026`, `multi-014` |
| 结果 | **113 confirmed / 20 reject / 17 needs_followup** |
| 确认率 | 75.3% |
| 传输重试 | 0 |
| 解析重试 | 0 |
| Overlay 生成 | **未生成**（37 条未通过门禁） |

---

## 3. 门禁状态

### 3.1 准入门禁脚本

`scripts/corpus_v2_automated_review_apply.py` 实施严格校验：

1. **完整性**：150 行、case_id 唯一、集合与当前 draft 一致
2. **字段守恒**：非审阅字段与当前 draft / 证据映射一致
3. **证据校验**：chunk 存在、source 一致、snippet 连续、字符范围正确
4. **模型固定**：`deepseek-v4-pro`，参数固定，响应/manifest SHA 可复算
5. **身份固定**：`reviewer_type = LLM_ASSISTED_OWNER_AUTHORIZED`，不允许任何 human 标识
6. **Overlay 条件**：150/150 confirmed → 生成 overlay + manifest
7. **fail-closed**：任意 reject/needs_followup → 仅生成 issues 清单和报告，禁止生成 overlay
8. **SHA 链**：输入或输出 SHA 漂移 → fail-closed
9. **不触碰人工包**：不调用 `corpus_v2_human_review_apply.py`，不改写 blank human-review pack

### 3.2 当前门禁结果

```
GATE BLOCKED — 37 条未通过
- reject: 20 条
- needs_followup: 17 条
- confirmed: 113 条
```

**未生成 automated overlay**。修复后须重新运行 automated-review 脚本。

---

## 4. 限制说明（保留）

### 4.1 机器审阅限制

- 本审阅为 **机器审阅**，受 LLM 能力限制
- 审阅结论基于本地证据文本，不包含外部知识
- 置信度分布：high 145 条 / medium 5 条 / low 0 条

### 4.2 同供应商模型限制

- 仅使用 `deepseek-v4-pro`（同供应商）
- 禁止使用 `gpt-5.6-sol`、`deepseek-v4-flash` 或其他模型
- 代码级 FORBIDDEN_MODELS 守卫，任何偏离立即触发 fail-closed

### 4.3 非人工签署限制

- 产物标识为 `LLM_ASSISTED_OWNER_AUTHORIZED`
- **绝不生成** `HUMAN_REVIEWED`、`HUMAN_APPROVED`、`人工审核完成` 等字样
- 原始人工审阅包（`human-review-pack.jsonl`）**保留未填写状态**
- 本自动审阅**不代表**人工批准、不代表生产上线批准

---

## 5. 产物清单

| 产物 | 路径 | 说明 |
|------|------|------|
| 治理策略 | `evaluation/datasets/v2/automated-review/AUTOMATED_REVIEW_POLICY.md` | 用户授权自动审阅策略 |
| 审阅包 | `evaluation/datasets/v2/automated-review/automated-review-pack.jsonl` | 150 条审阅输入 |
| 证据产物 | `evaluation/datasets/v2/automated-review/automated-review-evidence.jsonl` | 证据链明细 |
| 审阅结果 | `evaluation/datasets/v2/automated-review/automated-review.jsonl` | 150 条审阅决策 |
| 统计摘要 | `evaluation/datasets/v2/automated-review/automated-review-summary.json` | 决策统计 |
| 审阅报告 | `evaluation/datasets/v2/automated-review/automated-review-report.md` | 全量审阅报告 |
| 门禁报告 | `evaluation/datasets/v2/automated-review/automated-review-gate-report.md` | 门禁结果 |
| Issues 清单 | `evaluation/datasets/v2/automated-review/automated-review-issues.jsonl` | 37 条未通过 |
| Manifest | `evaluation/datasets/v2/automated-review/manifest.json` | 输入输出 SHA 链 |

---

## 6. 五条修复 case 本轮结论

| case_id | 本轮决策 | 说明 |
|---------|----------|------|
| `en-052` | **reject** | 仅 PostgreSQL durability 有证据，Rust ownership 无证据 |
| `en-055` | **confirmed** | `&` operator 证据充分（chunk_49） |
| `mixed-016` | **reject** | argument 译名无直接术语表证据 |
| `mixed-026` | **confirmed** | 章节标题对应结论有证据 |
| `multi-014` | **confirmed** | `from package import specific_submodule` 证据充分（chunk_38） |

---

## 7. 后续路径

1. **修复未通过 case**：对 20 reject + 17 needs_followup 的 37 条实施证据修复
2. **重新审阅**：修复后重新运行 `corpus_v2_automated_review.py review`
3. **门禁重检**：运行 `corpus_v2_automated_review_apply.py apply`，期望 150/150 confirmed
4. **生成 Overlay**：门禁通过后生成 `automated-reviewed-truth-overlay.json`
5. **v2.1 准入**：由用户授权决定是否以自动 overlay 作为 v2.1 准入条件

---

## 8. 声明

本自动审阅由用户授权，执行者为 LLM（deepseek-v4-pro），审阅人身份为 `LLM_ASSISTED_OWNER_AUTHORIZED`。
结论仅作为 v2.1 自动化前置条件，**不代表人工批准或生产上线批准**。
原始人工审阅包未修改，未暂存、未提交、未 push。
