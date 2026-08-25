# v2.0.1 用户授权自动审阅策略

> **生效版本**：v2.0.1（绑定 `v2-cases-draft.jsonl` / `chunks.jsonl` /
> `chunk-manifest.json` / case-freeze / split-lock 的 SHA-256 指纹）。
> 本策略由用户明确授权，替代此前"必须真人逐条审核"的流程要求。

---

## 1. 性质声明

本审阅是 **"用户授权的 LLM 自动审阅"**，**不是人工审核**。

- 审阅执行者为 LLM（`deepseek-v4-pro`），**不涉及任何人类审阅员**。
- 审阅结论仅作为 **v2.1 的自动化前置条件**，不代表人工批准、不代表生产上线批准。
- **禁止**将机器审阅结果写作"人工审核"、"人工批准"、"HUMAN_REVIEWED"、
  "HUMAN_APPROVED" 或任何声称真人审核的字段/报告。
- 原人工审阅包（`human-review-pack.jsonl` 及其空白原始版本）**保留未填写状态**，
  不因本策略而改变。

---

## 2. 授权依据

用户已明确授权：**跳过真人逐条审核，由子代理完成 150 条证据审阅**；
审核结果可作为 v2.1 的自动化前置条件。

---

## 3. 模型与参数

| 参数 | 固定值 |
|------|--------|
| 模型 | `deepseek-v4-pro` |
| temperature | `0.0` |
| max_tokens | `8000` |
| 禁止模型 | `gpt-5.6-sol`、`deepseek-v4-flash`、任何回退模型 |
| 联网 | 禁止 |

模型与参数在代码中硬编码为常量，任何偏离立即触发 **fail-closed**。

---

## 4. 输入边界

审阅输入**仅限**以下文件（不传任何历史审阅结论）：

- `evaluation/datasets/v2/annotations/v2-cases-draft.jsonl`
- `data/v2-corpus/chunks/chunks.jsonl`
- 当前 v2.0.1 revision manifest / 证据校验产物
- 必要的 pack/schema/validator 代码

**禁止传入**：
- 第三轮 verdict、历史 reject、历史 notes
- selection cohort、人工包字段
- split / dev / holdout 身份
- 任何评测结论（alpha、阈值、检索分数等）

---

## 5. 审阅规则

逐条对 150 条 case 执行独立审阅：

| 决策 | 含义 |
|------|------|
| `confirmed` | 所有必要答案点有本地证据支持，或正确拒答 |
| `reject` | 存在明确无证据答案点、错误来源、证据不连续或核心结论不成立 |
| `needs_followup` | 无法由本地文本判定，需进一步人工或系统处理 |

- **此前修复的五条必须独立重新审阅**，不得继承历史结论：
  `en-052`、`en-055`、`mixed-016`、`mixed-026`、`multi-014`。
- 审阅人身份固定为 `LLM_ASSISTED_OWNER_AUTHORIZED`。
- 任何 `reject` 或 `needs_followup` → **阻止自动 overlay 生成**。

---

## 6. 输出标识

即使 150/150 全部 `confirmed`，结论标识仅为：

```
AUTOMATED_REVIEWED_OWNER_AUTHORIZED
```

该标识**不代表**：
- 人工批准（`HUMAN_APPROVED`）
- 生产上线批准
- 任何人类审阅员的签字或确认

---

## 7. 准入门禁（apply 脚本）

`scripts/corpus_v2_automated_review_apply.py` 实施以下校验：

1. **完整性**：150 行、case_id 唯一、集合与当前 draft 一致。
2. **字段守恒**：非审阅字段与当前 draft / 证据映射一致。
3. **证据校验**：chunk 存在、source 一致、snippet 连续、字符范围正确。
4. **模型固定**：`deepseek-v4-pro`，参数固定，响应/manifest SHA 可复算。
5. **身份固定**：`reviewer_type = LLM_ASSISTED_OWNER_AUTHORIZED`，
   不允许任何 human 标识。
6. **overlay 条件**：150/150 `confirmed` → 生成
   `automated-reviewed-truth-overlay.json` + manifest。
7. **fail-closed**：任意 `reject` / `needs_followup` → 仅生成 issues 清单和报告，
   **禁止**生成 overlay。
8. **SHA 链**：输入或输出 SHA 漂移 → fail-closed。
9. **不触碰人工包**：不调用 `corpus_v2_human_review_apply.py`，
   不改写 blank human-review pack。

---

## 8. 数据质量检查

由于 `data-analytics:analyze-data-quality` skill 在本环境不可用，
以以下**确定性等价检查**覆盖五维：

| 维度 | 检查内容 |
|------|----------|
| 完整性 | 150 行全量覆盖、无缺失 case、所有必要字段非空 |
| 唯一性 | case_id 唯一、chunk_id 在 case 内唯一 |
| 引用完整性 | 所有 chunk_id ∈ chunks.jsonl |
| 连续性 | 所有 snippet 为 chunk_text 的连续子串 |
| 一致性 | source_id ∈ relevant_source_ids、字符范围 ∈ chunk_text |

---

## 9. 版本绑定

本策略**仅适用于** v2.0.1 数据版本，绑定以下 SHA-256 指纹：

- `v2-cases-draft.jsonl` SHA-256
- `chunks.jsonl` SHA-256
- `chunk-manifest.json` SHA-256
- case-freeze SHA-256
- split-lock SHA-256

任何上述文件的 SHA 漂移 → 本策略自动失效，须重新评估授权。

---

## 10. 结论模板

```
本自动审阅由用户授权，执行者为 LLM（deepseek-v4-pro），
审阅人身份为 LLM_ASSISTED_OWNER_AUTHORIZED。
结论仅作为 v2.1 自动化前置条件，不代表人工批准或生产上线批准。
原始人工审阅包未修改，未暂存、未提交、未 push。
```
