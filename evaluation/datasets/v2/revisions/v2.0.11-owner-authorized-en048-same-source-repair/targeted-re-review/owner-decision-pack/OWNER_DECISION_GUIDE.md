# Owner 决策指南（只读）

## 本包是什么

- `owner-decision-template.jsonl`（22 行）是唯一需要 owner 填写的文件：`owner_decision` / `owner_reviewer` / `owner_notes` 全部为空字符串。
- `stable-reject-root-cause-triage.jsonl`（18 行）给出逐答案点机械分类；targeted review rationale 标注为模型输出，不作为事实。
- `persistent-contract-errors.jsonl`（4 行）记录持续契约错误；`expected_decision_from_local_contract=confirmed` 是引擎契约推断，**不是对原 review 的改写**（`rewritten=false`），缺失的原始响应未伪造。

## 如何填写模板

- `owner_decision` 可选值（只读建议，任何建议都不会自动应用）：`confirm` / `reject` / `authorized_repair`（仅 same_source 候选）/ `keep_blocked`。
- 契约 error 的路线：`manual_audit_of_available_records` / `authorize_new_contract_focused_blind_review` / `keep_blocked`。
- 填写后回写模板并保留本包；任何决定都不能解除 `AUTOMATED_REVIEW_GATE_BLOCKED` 或 activation-blocked 状态，直至另行授权的 sealed 流程。

## 分类口径（机械、可审计）

- `exact`：答案点规范化文本直接包含于某 evidence raw span。
- `partial`：同语言 LCS ≥ max(3, 0.10 × 较短文本长度)。
- `same_source`：同 source chunk 存在未覆盖的机械候选（已给出 source/chunk/Unicode [start,end)/raw span/唯一性与不重叠证明）。
- `translation`：仅识别跨语言关联（共享 token），不得伪装成 direct evidence。
- `no_direct`：无机械可证的直接支撑。

不得把 token 片段、跨 source 内容、模型 rationale 或语义猜测视为 direct evidence。
