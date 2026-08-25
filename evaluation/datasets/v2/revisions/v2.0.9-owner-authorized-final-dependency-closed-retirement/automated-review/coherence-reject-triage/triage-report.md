# v2.0.9 Automated-Review Coherence & Reject Root-Cause Triage Report

- **任务**：`v2.0.9-automated-review-coherence-and-reject-root-cause-triage`
- **规则版本**：`v2.0.9-coherence-reject-triage-1`（run_at=2026-08-11T00:00:00+00:00）
- **性质**：只读、确定性、无 LLM/API、无联网
- **输入**：v2.0.9 candidate（draft/evidence/manifest）、automated-review（issues/gate report/manifest）、chunks、chunk-manifest、current draft（仅哈希）
- **上游结论**：`AUTOMATED_REVIEW_GATE_BLOCKED`（111 confirmed / 22 reject / 0 needs_followup / 4 errors）

## 1. 预检（fail-closed）

- candidate：137 cases / 144 strict evidence，covered==passed==144，legacy=0
- review canonical 守恒：111 + 22 + 0 + 4 = 137；issues 26 条，case_id 无重复、无遗漏
- 无 overlay；candidate/review manifest 自哈希与输入输出 SHA 一致
- 引用完整性 / 连续性 / 五维确定性检查通过

## 2. 分流一：4 条 model-output coherence errors

| case_id | attempts | expected decision | classification |
|---|---|---|---|
| en-052 | 4 | confirmed | model_output_contract_inconsistency |
| mixed-030 | 4 | confirmed | model_output_contract_inconsistency |
| mixed-033 | 4 | confirmed | model_output_contract_inconsistency |
| multi-011 | 4 | confirmed | model_output_contract_inconsistency |

判定依据：issue detail 明确 `reject/needs_followup without any disagreement`；本地契约校验无任何分歧 ⇒ 契约要求 confirmed；模型输出自相矛盾（4 次同模型重试一致）。**未**改写模型输出、**未**重跑模型。可选后续：对这 4 条做一次全新盲态重审或人工核验（见 owner-decision-template.jsonl）。

## 3. 分流二：22 条 substantive rejects

| case_id | case 分类 | 建议动作 | 答案点明细 |
|---|---|---|---|
| en-040 | partial_or_paraphrase_only | targeted_recheck_required | AP1=partial_or_paraphrase_only; AP2=partial_or_paraphrase_only |
| en-041 | partial_or_paraphrase_only | targeted_recheck_required | AP1=partial_or_paraphrase_only; AP2=partial_or_paraphrase_only |
| en-045 | partial_or_paraphrase_only | targeted_recheck_required | AP1=partial_or_paraphrase_only; AP2=partial_or_paraphrase_only |
| en-047 | same_source_scope_candidate_exists | repair_candidate | AP1=same_source_scope_candidate_exists; AP2=partial_or_paraphrase_only |
| en-048 | same_source_scope_candidate_exists | repair_candidate | AP1=same_source_scope_candidate_exists; AP2=partial_or_paraphrase_only |
| en-051 | partial_or_paraphrase_only | targeted_recheck_required | AP1=partial_or_paraphrase_only |
| mixed-022 | exact_evidence_present_but_review_semantic_disagrees | targeted_recheck_required | AP1=exact_evidence_present_but_review_semantic_disagrees |
| mixed-028 | exact_evidence_present_but_review_semantic_disagrees | targeted_recheck_required | AP1=exact_evidence_present_but_review_semantic_disagrees |
| mixed-029 | exact_evidence_present_but_review_semantic_disagrees | targeted_recheck_required | AP1=exact_evidence_present_but_review_semantic_disagrees |
| mixed-034 | partial_or_paraphrase_only | targeted_recheck_required | AP1=partial_or_paraphrase_only; AP2=partial_or_paraphrase_only |
| multi-012 | exact_evidence_present_but_review_semantic_disagrees | targeted_recheck_required | AP1=exact_evidence_present_but_review_semantic_disagrees |
| multi-019 | no_direct_support_in_declared_source | retire_case | AP1=no_direct_support_in_declared_source |
| multi-020 | same_source_scope_candidate_exists | repair_candidate | AP1=same_source_scope_candidate_exists |
| multi-027 | partial_or_paraphrase_only | targeted_recheck_required | AP1=partial_or_paraphrase_only |
| multi-028 | same_source_scope_candidate_exists | repair_candidate | AP1=same_source_scope_candidate_exists |
| zh-023 | exact_evidence_present_but_review_semantic_disagrees | targeted_recheck_required | AP1=exact_evidence_present_but_review_semantic_disagrees |
| zh-036 | exact_evidence_present_but_review_semantic_disagrees | targeted_recheck_required | AP1=exact_evidence_present_but_review_semantic_disagrees |
| zh-046 | same_source_scope_candidate_exists | repair_candidate | AP1=same_source_scope_candidate_exists; AP2=partial_or_paraphrase_only |
| zh-050 | partial_or_paraphrase_only | targeted_recheck_required | AP1=partial_or_paraphrase_only; AP2=partial_or_paraphrase_only |
| zh-052 | same_source_scope_candidate_exists | repair_candidate | AP1=partial_or_paraphrase_only; AP2=same_source_scope_candidate_exists |
| zh-054 | exact_evidence_present_but_review_semantic_disagrees | targeted_recheck_required | AP1=exact_evidence_present_but_review_semantic_disagrees |
| zh-058 | partial_or_paraphrase_only | targeted_recheck_required | AP1=partial_or_paraphrase_only; AP2=partial_or_paraphrase_only |

分类计数：partial_or_paraphrase_only=8, same_source_scope_candidate_exists=6, exact_evidence_present_but_review_semantic_disagrees=7, no_direct_support_in_declared_source=1
建议动作计数：targeted_recheck_required=15, repair_candidate=6, retire_case=1

## 4. mixed-033 重复 evidence

- 两条 evidence 行字节级一致：True；同 chunk：True；同 raw range：True；同 raw span：True；支撑同一保留答案点：True
- 删除建议：语义安全=True；需 owner 授权=True；本任务只写建议，未修改任何数据。

## 5. 产物与验证

- 8 个文件写入 `automated-review/coherence-reject-triage/`（见 manifest.json outputs SHA）；两次构建逐字节一致。
- 输入 SHA（draft-after / evidence-after / chunks / chunk-manifest）任务前后不变；未 stage/commit/push。

## 6. 边界声明

本次是用户授权的**机器复审根因分流**：不是人工审核、不是人工批准、不是 active 版本、不是 v2.1 准入。Gate 保持 BLOCKED：不生成任何 overlay；v2.0.9 保持 CANDIDATE / activation_blocked / split_reseal_required。22 条 reject 与 4 条 error 的逐答案点明细见本目录 jsonl 产物，owner 可据此在 owner-decision-template 中填决策。
