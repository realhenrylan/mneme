# FROZEN EVALUATION BASELINE — v2.0.11

- **冻结对象**：`v2.0.11-owner-authorized-en048-same-source-repair`（136 cases / 149 strict evidence）。
- **冻结含义**：v2.0.11 作为工程评测候选基线，不再打磨、不回写、不退役。
- **明确不是**：不是 active 版本、不是人工批准、不是 review acceptance、不是 v2.1 准入。
- **状态**：`revision_status=CANDIDATE`、`activation_blocked=true`、`human_reviewed=false`、`overlay_generated=false`、`split_reseal_required=true`、`v2_1_entered=false`；candidate gate=`EN048_SAME_SOURCE_REPAIR_CANDIDATE_OK`、targeted review gate=`TARGETED_REVIEW_BLOCKED`、owner decision pack gate=`OWNER_DECISION_PACK_OK`、contract-error diagnostic gate=`CONTRACT_ERROR_DIAGNOSTIC_COMPLETE`。
- **owner 决策记录**：18 条 reject 全部 `deferred`（无 candidate 数据动作；未来仅可进入 v2.1 治理流程）；4 条 contract error 的诊断状态见 `freeze-summary.json` 与 `contract-error-diagnostic/`。
- **治理约束**：后续任何语料改进仅允许新建 v2.1，绝不回写 v2.0.11；冻结不解除 `TARGETED_REVIEW_BLOCKED` 与 activation-blocked。
- **不变量**：candidate / targeted review / owner decision pack / contract-error diagnostic 的字节 SHA 在冻结前后完全不变（见 `manifest.json` inputs）。
