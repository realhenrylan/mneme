# v2.0.10 Automated-Review Coherence & Reject Root-Cause Triage Report

- **任务**：`v2.0.10-automated-review-coherence-and-reject-root-cause-triage`
- **规则版本**：`v2.0.10-coherence-reject-triage-1`（run_at=2026-08-11T00:00:00+00:00）
- **性质**：只读、确定性、无 LLM/API、无联网
- **输入**：v2.0.10 candidate（draft/evidence/manifest）、automated-review（issues/gate report/manifest）、chunks、chunk-manifest、current draft（仅哈希）
- **上游结论**：`AUTOMATED_REVIEW_GATE_BLOCKED`（113 confirmed / 19 reject / 0 needs_followup / 4 errors）

## 1. 预检（fail-closed）

- candidate：136 cases / 148 strict evidence，covered==passed==148，legacy=0
- review canonical 守恒：113 + 19 + 0 + 4 = 136；issues 23 条，case_id 无重复、无遗漏
- 无 overlay；candidate/review manifest 自哈希与输入输出 SHA 一致
- 引用完整性 / 连续性 / 五维确定性检查通过

## 2. 分流一：4 条 model-output coherence errors

| case_id | attempts | expected decision | classification |
|---|---|---|---|
| en-052 | 4 | confirmed | model_output_contract_inconsistency |
| mixed-030 | 4 | confirmed | model_output_contract_inconsistency |
| mixed-033 | 4 | confirmed | model_output_contract_inconsistency |
| zh-040 | 4 | confirmed | model_output_contract_inconsistency |

判定依据：issue detail 明确 `reject/needs_followup without any disagreement`；本地契约校验无任何分歧 ⇒ 契约要求 confirmed；模型输出自相矛盾（4 次同模型重试一致）。**未**改写模型输出、**未**重跑模型。可选后续：对这 4 条做一次全新盲态重审或人工核验（见 owner-decision-template.jsonl）。

## 3. 分流二：19 条 substantive rejects

| case_id | case 分类 | 建议动作 | 答案点明细 |
|---|---|---|---|
| en-040 | partial | targeted_recheck_required | AP1=partial; AP2=partial |
| en-041 | partial | targeted_recheck_required | AP1=partial; AP2=partial |
| en-045 | partial | targeted_recheck_required | AP1=partial; AP2=partial |
| en-047 | partial | targeted_recheck_required | AP1=partial; AP2=partial |
| en-048 | same_source | repair_candidate | AP1=same_source; AP2=partial |
| en-051 | partial | targeted_recheck_required | AP1=partial |
| mixed-022 | exact | targeted_recheck_required | AP1=exact |
| mixed-028 | exact | targeted_recheck_required | AP1=exact |
| mixed-029 | exact | targeted_recheck_required | AP1=exact |
| mixed-034 | partial | targeted_recheck_required | AP1=partial; AP2=partial |
| multi-012 | exact | targeted_recheck_required | AP1=exact |
| multi-027 | partial | targeted_recheck_required | AP1=partial |
| zh-023 | exact | targeted_recheck_required | AP1=exact |
| zh-036 | exact | targeted_recheck_required | AP1=exact |
| zh-046 | partial | targeted_recheck_required | AP1=partial; AP2=partial |
| zh-050 | partial | targeted_recheck_required | AP1=partial; AP2=partial |
| zh-052 | partial | targeted_recheck_required | AP1=partial; AP2=exact |
| zh-054 | exact | targeted_recheck_required | AP1=exact |
| zh-058 | partial | targeted_recheck_required | AP1=partial; AP2=partial |

分类计数：partial=11, same_source=1, exact=7
建议动作计数：targeted_recheck_required=18, repair_candidate=1

## 4. 五维数据质量

- `data-quality-report.json`：完整性 / 唯一性 / 引用完整性 / 连续性 / 一致性全部通过；skill 可用性已如实记录（可用则实际使用）。

## 5. 产物与验证

- 8 个文件写入 `automated-review/coherence-reject-triage/`（见 manifest.json outputs SHA）；两次构建逐字节一致。
- 输入 SHA（draft-after / evidence-after / review issues / review manifest / chunks / chunk-manifest）任务前后不变；未 stage/commit/push。

## 6. 边界声明

本次是用户授权的**机器复审根因分流**：不是人工审核、不是人工批准、不是 active 版本、不是 v2.1 准入。Gate 保持 BLOCKED：不生成任何 overlay；v2.0.10 保持 CANDIDATE / activation_blocked / split_reseal_required。19 条 reject 与 4 条 error 的逐答案点明细见本目录 jsonl 产物，owner 可据此在 owner-decision-template 中填决策。
