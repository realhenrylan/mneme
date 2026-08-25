# REVIEW_AND_SPLIT_REBUILD_REQUIRED.md

v2.0.9 是 **CANDIDATE**（`activation_blocked=true`、`human_reviewed=false`）。

- 本次确定性退役：6 条 case / 7 条 evidence（143 → 137 case、151 → 144 evidence）；
- 历史 split / dev / holdout 与锁配置**一律不复用**；
- 激活前必须：一次全新的 137-case 盲态复审（**不得复用 v2.0.7 / v2.0.8 的 review 结果**）、重新切分（split reseal），并按要求重建 review 结果；
- 严格证据验证通过（covered==passed）**不构成**审阅通过、confirmed 或 active 准入；
- 退役 case（multi-030~multi-034、mixed-027）及其 evidence 已从 candidate 移除，不得作为已审阅结论复用；
- 未进入 v2.1；未生成 overlay / active metadata / split / locked config。
