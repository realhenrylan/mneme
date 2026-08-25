# v2.0.11 Contract-Error Diagnostic — 报告

- **Revision**：`v2.0.11-owner-authorized-en048-same-source-repair`（136 cases / 149 strict evidence，gate=`EN048_SAME_SOURCE_REPAIR_CANDIDATE_OK`）
- **Targeted review**：gate=`TARGETED_REVIEW_BLOCKED`；Phase 4 pack gate=`OWNER_DECISION_PACK_OK`（owner 模板 22 行保持空白）
- **Gate**：`CONTRACT_ERROR_DIAGNOSTIC_COMPLETE` —— 诊断完成不是 review acceptance、不是人工批准、不解除 `TARGETED_REVIEW_BLOCKED`
- **目标集**：恰 4 条（en-052 / mixed-030 / mixed-033 / zh-040），由 Phase 4 pack 与 targeted review 三源交叉推导并断言
- **模型**：`deepseek-v4-pro`（temperature=0.0 / max_tokens=8000 / thinking disabled / 最多 3 次同模型重试 / 无 fallback）；探针身份 `deepseek-v4-pro` ok=true
- **盲态**：payload 不含 case_id / 历史 verdict / rationale / owner decision / 分类 / 治理标签；不因旧 contract error 预设 confirmed
- **统计**：resolved 0 / contract_error 4 / transport_blocked 0 / identity_blocked 0；总尝试 16 次，每次原始响应均保存在 raw-model-attempts.jsonl
- **逐 case**：en-052=contract_error(4 次)；mixed-030=contract_error(4 次)；mixed-033=contract_error(4 次)；zh-040=contract_error(4 次)
- **数据质量**：data-analytics:analyze-data-quality skill 在本环境中不可用（已实际尝试，无法加载——可用技能列表中没有该技能）；已实施等价的确定性五维检查（完整性/唯一性/引用完整性/连续性/一致性），全部为机械复算，无额外 LLM 参与。
