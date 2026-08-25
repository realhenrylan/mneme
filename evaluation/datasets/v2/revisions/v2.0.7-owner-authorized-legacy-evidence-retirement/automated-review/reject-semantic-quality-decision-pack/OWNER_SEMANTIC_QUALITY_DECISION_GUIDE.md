# OWNER_SEMANTIC_QUALITY_DECISION_GUIDE.md — v2.0.7 语义质量闭环决策指南

## 这是什么

本决策包基于 v2.0.7 盲态自动审阅（LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_7）的 22 条 reject 与 reject-triage 根因分流，为**所有者**提供批量决策的只读依据。本决策包**不会自动应用任何动作**：所有推荐动作与批次仅是建议，必须由所有者填写 `owner_decision` / `owner_reviewer` / `owner_notes` 后，在另行授权的修复步骤中执行。

本决策包不是修复、不是人工审核、不是 overlay、不是 v2.1 准入；未调用 LLM/API、未联网；未生成 active metadata / split。

## 输入门禁（fail-closed，全部通过）

- reject 集合恰 22 条；triage 集合 == reject 集合
- triage 类别分布恰好 8 / 5 / 6 / 2 / 1
- candidate 148 条；strict raw-codepoint-v1 evidence 161/161；无 overlay
- review / candidate / triage manifest 自哈希与 SHA 链全部一致

## 五批次建议（不自动应用）

| 批次 | 条数 | case_id |
|---|---|---|
| batch_a_replace_with_self_contained_exact_text | 7 | mixed-028, mixed-029, zh-023, zh-026, zh-029, zh-036, zh-054 |
| batch_b_expand_same_source_scope | 1 | zh-040 |
| batch_c_translation_policy_required | 3 | en-029, multi-019, zh-052 |
| batch_d_retire_or_remove | 10 | en-042, en-044, en-049, en-050, en-051, mixed-026, mixed-033, multi-030, zh-042, zh-045 |
| batch_e_targeted_re_review | 1 | mixed-027 |

## 推荐动作词表

- `replace_answer_point_with_self_contained_exact_raw_text` → `batch_a_replace_with_self_contained_exact_text`
- `replace_with_exact_source_language_text` → `batch_a_replace_with_self_contained_exact_text`
- `expand_same_source_evidence_scope` → `batch_b_expand_same_source_scope`
- `owner_approved_translation_equivalence_policy` → `batch_c_translation_policy_required`
- `remove_semantically_insufficient_answer_point` → `batch_d_retire_or_remove`
- `remove_unsupported_answer_point` → `batch_d_retire_or_remove`
- `retire_case` → `batch_d_retire_or_remove`
- `keep_unresolved` → `batch_d_retire_or_remove`
- `targeted_blind_re_review` → `batch_e_targeted_re_review`

## 各类别决策规则（默认推荐依据）

1. `exact_evidence_present_but_review_semantic_disagrees`（8 条）：不能把逐字 token 命中自动视为高质量真值。找到同 source 自包含完整 clause/sentence → 推荐 `replace_answer_point_with_self_contained_exact_raw_text`；仅孤立 token/标题/短标签 → `remove_semantically_insufficient_answer_point`，若零答案点则 `retire_case`。不提供放宽 review 标准作为默认动作。
2. `evidence_scope_insufficient_but_same_source_candidate_exists`（6 条）：逐条列出唯一、连续、同 source 的 scope expansion evidence；能完整支撑当前答案点 → `expand_same_source_evidence_scope`；只能部分支撑 → 收窄/删除/退役选项，不假装充分。
3. `partial_or_paraphrase_only`（5 条）：区分中文答案点 + 英文来源的 translation-equivalence 情况；提供五个选项，翻译等价**不自动判为 confirmed**。
4. `no_direct_support_in_declared_source`（2 条）：仅 `retire_case` / `keep_unresolved`。
5. `review_contract_or_model_semantics_inconsistency`（1 条，mixed-027）：输出本地契约证明；仅 `targeted_blind_re_review` / `keep_unresolved`；不因“模型似乎矛盾”自动改为 confirmed。

## 候选与标记

- `self-contained-raw-candidates.jsonl`：全部候选均满足 `chunk_text[start:end] == raw_span`，`coverage >= 0.75`；partial / paraphrase 不会被写成 exact。
- `scope_expansion_required=true`：候选不在当前 evidence span 内，作为证据需扩展 scope；候选 source/chunk 不会跨越声明范围而不标记。
- `semantic_quality_insufficient=true`：答案点仅由孤立 token / 标题 / 短标签支撑（无自包含完整句/段候选）。
- `removal_zero_risk=true`：推荐移除/退役会清空全部答案点。

## 模板填写

`owner-batch-decision-template.jsonl` 每行含 `recommended_action`，但 `owner_decision` / `owner_reviewer` / `owner_notes` 必须由所有者填写：
- `owner_decision`：接受 / 拒绝 / 修改推荐动作（从该行 `owner_options` 中选择）；
- `owner_reviewer`：决策人标识；
- `owner_notes`：决策理由。

## 后续步骤

所有者完成批量决策后，需另行授权一个确定性修复/重审步骤（本决策包不做任何修改）。
