# false-refusal 与 guardrail 阈值只读审计报告

> 目录：`results/graph-gate/refusal-guardrail-audit-20260805T113849/`
> 性质：**只读审计包（CANDIDATE 辅助材料）** — 仅复算与展示，不修改
> 任何生产配置或 guardrail 阈值，不构成阈值批准；批准待人工。
> 输入：`production-baseline-stable-20260805T084256/`（稳定 split +
> split_fingerprint 锁定的正式候选评测 v2）；生成时间
> 2026-08-05T11:42:25。

---

## 一、false-refusal 提取（fail-closed）

**定义**：`should_refuse=False`（answerable）且 `correctly_refused=False`。
**判定依据**：`evaluation/citation_metrics.compute_refusal_accuracy` 对
回答做拒答指示短语子串匹配（中文：未找到/无法回答/没有足够/暂无/
无法提供；英文：cannot/unable to/no information/not found/don't have/
does not contain/not available），命中即判定为拒答；本包逐条复算命中
短语，并与 JSONL 中 `correctly_refused` 一致。

**计数断言**（不符即整体失败）：dev = **14** / 73 answerable；
holdout = **1** / 12 answerable。

| split | false_refusal case_id |
|---|---|
| dev | cross-005, cross-007, cross-009, cross-010, en-012, en-013, en-016, meta-006, meta-008, mixed-006, mixed-008, multi-009, zh-011, zh-014 |
| holdout | meta-002 |

### 逐 case 明细

| split | case_id | lang | type | diff | 拒答命中 | answer_point_coverage | 真值来源进 context | 真值 chunk 候选/context |
|---|---|---|---|---|---|---|---|---|
| dev | cross-005 | en | cross_document | hard | 无法回答 | 0.0000 | 是 | 是/否 |
| dev | cross-007 | mixed | cross_document | medium | 无法回答 | 1.0000 | 是 | 是/是 |
| dev | cross-009 | zh | cross_document | medium | 无法回答 | 0.6667 | 是 | 是/是 |
| dev | cross-010 | en | cross_document | medium | 未找到/无法回答 | 0.0000 | 是 | 是/否 |
| dev | en-012 | en | single_fact | medium | 无法回答 | 0.0000 | 是 | 否/否 |
| dev | en-013 | en | metadata | hard | 未找到/无法回答 | 0.0000 | 是 | 否/否 |
| dev | en-016 | en | single_fact | hard | 无法回答 | 0.0000 | 是 | 是/否 |
| dev | meta-006 | en | metadata | easy | 未找到/无法回答 | 0.0000 | 否 | 是/否 |
| dev | meta-008 | en | metadata | hard | 未找到/无法回答 | 1.0000 | 是 | 否/否 |
| dev | mixed-006 | mixed | cross_document | hard | 无法回答 | 0.6667 | 是 | 是/否 |
| dev | mixed-008 | mixed | cross_document | medium | 未找到 | 0.5000 | 是 | 是/是 |
| dev | multi-009 | en | multi_turn | medium | 无法回答 | 0.0000 | 是 | 是/否 |
| dev | zh-011 | zh | single_fact | easy | 无法回答 | 0.0000 | 是 | 是/否 |
| dev | zh-014 | zh | single_fact | easy | 未找到 | 0.0000 | 是 | 是/否 |
| holdout | meta-002 | en | metadata | easy | 未找到/无法回答 | 0.0000 | 是 | 是/是 |

> 说明：`真值 chunk 候选/context` 表示相关 chunk 是否进入候选池 / 是否
> 进入最终 prompt context；「候选=是、context=否」说明检索命中但被
> Top-K/每来源上限截断，「候选=否」说明检索层未命中（en-012、en-013、
> meta-008 为 source-only 或单文档检索失败）。

## 二、拒答切片分析（分子/分母 + Wilson 95% CI）

### dev（14 / 73，rate = 0.1918）

| 维度 | 分组 | false_refusal / answerable | 比率 | Wilson 95% CI |
|---|---|---|---|---|
| overall | all | 14 / 73 | 0.1918 | [0.1178, 0.2966] |
| language | zh | 3 / 29 | 0.1034 | [0.0358, 0.2639] |
| language | en | 8 / 29 | 0.2759 | [0.1470, 0.4572] |
| language | mixed | 3 / 15 | 0.2000 | [0.0705, 0.4519] |
| query_type | single_fact | 4 / 31 | 0.1290 | [0.0513, 0.2885] |
| query_type | cross_document | 6 / 11 | 0.5455 | [0.2801, 0.7873] |
| query_type | metadata | 3 / 14 | 0.2143 | [0.0757, 0.4759] |
| query_type | mixed_intent | 0 / 10 | 0.0000 | [0.0000, 0.2775] |
| query_type | multi_turn | 1 / 7 | 0.1429 | [0.0257, 0.5131] |
| difficulty | easy | 3 / 33 | 0.0909 | [0.0314, 0.2357] |
| difficulty | medium | 6 / 30 | 0.2000 | [0.0950, 0.3731] |
| difficulty | hard | 5 / 10 | 0.5000 | [0.2366, 0.7634] |
| source_only | True | 2 / 4 | 0.5000 | [0.1500, 0.8500] |
| source_only | False | 12 / 69 | 0.1739 | [0.1024, 0.2798] |
| multi_turn | True | 1 / 5 | 0.2000 | [0.0362, 0.6245] |
| multi_turn | False | 13 / 68 | 0.1912 | [0.1153, 0.3001] |

### holdout（1 / 12，rate = 0.0833）

| 维度 | 分组 | false_refusal / answerable | 比率 | Wilson 95% CI |
|---|---|---|---|---|
| overall | all | 1 / 12 | 0.0833 | [0.0149, 0.3539] |
| language | zh | 0 / 4 | 0.0000 | [0.0000, 0.4899] |
| language | en | 1 / 5 | 0.2000 | [0.0362, 0.6245] |
| language | mixed | 0 / 3 | 0.0000 | [0.0000, 0.5615] |
| query_type | single_fact | 0 / 4 | 0.0000 | [0.0000, 0.4899] |
| query_type | cross_document | 0 / 2 | 0.0000 | [0.0000, 0.6576] |
| query_type | metadata | 1 / 2 | 0.5000 | [0.0945, 0.9055] |
| query_type | mixed_intent | 0 / 1 | 0.0000 | [0.0000, 0.7935] |
| query_type | multi_turn | 0 / 3 | 0.0000 | [0.0000, 0.5615] |
| difficulty | easy | 1 / 6 | 0.1667 | [0.0301, 0.5635] |
| difficulty | medium | 0 / 3 | 0.0000 | [0.0000, 0.5615] |
| difficulty | hard | 0 / 3 | 0.0000 | [0.0000, 0.5615] |
| source_only | True | 0 / 0 | — | — |
| source_only | False | 1 / 12 | 0.0833 | [0.0149, 0.3539] |
| multi_turn | True | 0 / 2 | 0.0000 | [0.0000, 0.6576] |
| multi_turn | False | 1 / 10 | 0.1000 | [0.0179, 0.4042] |

### 集中性观察（仅 dev，样本量小仅作方向性判断）

- **cross_document 明显集中**：6 / 11 =
  0.5455，远高于总体 0.1918 —— 跨文档比较类问题最易
  被误拒答，且 6 例中 4 例相关 chunk 已在候选池（cross-005/010 被截断、
  cross-007/009 已进 context 仍拒答）。
- **hard 难度集中**：5 / 10 =
  0.5000（总体 0.1918）。
- **英文偏高**：8 / 29 =
  0.2759。
- **source-only 敏感**：2 / 4 =
  0.5000（source-only 无 chunk 真值，仅 4 例）。
- 4 例真值 chunk 已进入 context 仍被误拒（cross-007、cross-009、
  mixed-008、meta-002@holdout）→ 属模型侧误判而非检索失败，最值得人工
  复核。

## 三、guardrail 敏感性

### false_refusal 阈值模拟（rate ≤ threshold → PASS）

**dev** rate = 0.1918（14/73）

| 阈值 | verdict | margin (rate − threshold) |
|---|---|---|
| 0.15 | FAIL | +0.0418 |
| 0.18 | FAIL | +0.0118 |
| 0.20 | PASS | -0.0082 |
| 0.25 | PASS | -0.0582 |

**holdout** rate = 0.0833（1/12）

| 阈值 | verdict | margin (rate − threshold) |
|---|---|---|
| 0.15 | PASS | -0.0667 |
| 0.18 | PASS | -0.0967 |
| 0.20 | PASS | -0.1167 |
| 0.25 | PASS | -0.1667 |

> **当前建议阈值 0.20 下 dev margin = -0.0082**（紧贴阈值，
> 单例变化即翻转：14/73→15/73 = 0.2055 即 FAIL）。收紧到 0.18 会立即
> FAIL（dev margin +0.0118）。

### citation v2 复算（numerator/denominator 全部来自 candidate-report-data.json，未手填）

**dev**

| 指标 | 阈值 | numerator / denominator | 复算值 | margin | verdict |
|---|---|---|---|---|---|
| context_supported_citation_validity_micro | 0.95 | 153 / 153 | 1.0000 | +0.0500 | PASS |
| context_supported_answer_rate | 0.80 | 66 / 73 | 0.9041 | +0.1041 | PASS |
| no_citation_answer_rate | 0.20 | 7 / 73 | 0.0959 | -0.1041 | PASS |

**holdout**

| 指标 | 阈值 | numerator / denominator | 复算值 | margin | verdict |
|---|---|---|---|---|---|
| context_supported_citation_validity_micro | 0.95 | 22 / 22 | 1.0000 | +0.0500 | PASS |
| context_supported_answer_rate | 0.80 | 10 / 12 | 0.8333 | +0.0333 | PASS |
| no_citation_answer_rate | 0.20 | 2 / 12 | 0.1667 | -0.0333 | PASS |

### 组合 guardrail 状态（模拟）

| 项 | dev | holdout |
|---|---|---|
| false_refusal ≤ 0.20 | PASS | PASS |
| citation v2 全指标 | True | True |

> 模拟结果仅用于敏感性审计，**不构成阈值批准**；生产阈值变更仍待人工
> 签署（candidate-report.md §四为 CANDIDATE 建议）。

## 四、风险与限制

1. **拒答判定是短语匹配而非语义**：个别回答（如 zh-014「无法从文档中
   确认」）命中「无法回答/未找到」被计为拒答，边界 case 需人工复核。
2. **holdout 功效不足**：answerable 仅 12 例、false_refusal 仅 1 例，
   holdout 的拒答率点估计（0.0833）不可作为校准依据。
3. **语料规模**：14 例误拒答集中在 cross_document/hard，语料扩充后需
   重新评估；当前数字仅对当前语料 + prompt_id + deepseek-chat 有效。
4. **本包不修改任何输入**：所有输入文件 SHA-256 见 manifest.json；
   历史 results 产物与 candidate-report.md 未被改写。

## 五、结论

- dev false_refusal = 0.1918（14/73）在建议阈值 0.20 下
  **PASS，但 margin 仅 -0.0082**，不满足「收紧」条件；
  任何阈值 ≤ 0.18 在当前 dev 分布下直接 FAIL。
- **不建议在现阶段自动收紧或批准阈值**；建议：① 人工复核本包 15 条
  false_refusal（尤其 4 条真值 chunk 已进 context 仍拒答的 case）；
  ② 扩充语料后在稳定 split 新指纹下重跑，再以更大样本校准拒答阈值。
- 拒答问题优先指向 **cross_document 与 hard 切片**，而非全局拒答
  机制——后续阶段（RAG-IMPROVEMENT-PLAN 阶段 1.5 拒答校准）应针对该
  切片设计特征与验证。

*本报告由只读脚本生成（`generate_refusal_audit.py` 可复现）；未调用
LLM/API；未修改任何生产配置、阈值与历史产物。*
