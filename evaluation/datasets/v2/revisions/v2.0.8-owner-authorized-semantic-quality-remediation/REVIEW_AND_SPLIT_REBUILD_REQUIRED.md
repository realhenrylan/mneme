# REVIEW_AND_SPLIT_REBUILD_REQUIRED.md

v2.0.8 是 **CANDIDATE**（`activation_blocked=true`、`human_reviewed=false`）。

- 历史 split / dev / holdout 与锁配置**一律不复用**；
- 激活前必须：盲态复审（含批次 C 翻译等价与批次 E mixed-027 定向盲态复审）、
  重新切分（split reseal）、并按要求重建 review 结果；
- **multi-030 已延后（deferred）**：作为 multi-031~034 的链父节点保留，
  draft/evidence 逐字节未改；这不是 resolved / confirmed / 已接受的质量结论，
  其处置需所有者后续决策（见 `deferred-chain-dependent-cases.jsonl`）；
- 不得把 v2.0.7 或更早的 review 结论当作 v2.0.8 的 review 结果；
- 未进入 v2.1；未生成 overlay / active metadata / split / locked config。
