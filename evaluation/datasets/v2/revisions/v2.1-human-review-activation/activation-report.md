# v2.1 数据集激活报告（v2.1.0-human-review-activation）

> 生成工具：`scripts/corpus_v2_v21_activate.py`（确定性产物：无时间戳、无随机数、无网络/LLM 调用）
> 激活版本：**v2.1.0**；激活日期常量：2026-08-30；owner 终审裁决日期：2026-08-29
> gate_verdict：**ACTIVATED**（四门全过，fail-closed）

## 一、结论

v2 人工终审 overlay（`human-reviewed-truth-overlay.json`，SHA-256 `7d9bceb16a41b3b48914e2d5593e3d09057312062a3cdb1cac07f60840a37e75`）作为**最新权威真值层**启用，生成 v2.1 正式数据集（150 case）。数据集顶层真值字段自草稿原样透传（不重排、不重算），唯一改动是 `annotation` 内三个审阅字段：`review_status` = `human_review_confirmed_agent_adjudicated`（诚实取值：终审 confirmed 由授权代理复核 + owner 仲裁达成，非真人逐条复核）、`reviewed_by` = `zcode-agent-2026-08-29`、`review_notes` 追加 owner 裁决日期（2026-08-29）与激活版本号（v2.1.0）。

## 二、Phase A 谱系侦察四问

### A1 草稿 150 行 vs v2.0.11 冻结候选 136 行的构成差异

- 草稿 150 行 = case-freeze（corpus_version v2.0.0，2026-08-05 密封，`split/case-freeze.json`）`partition=new` 的 150 case 全集；**legacy_dev 110 行不在草稿池中**（partition=legacy_dev 与草稿 id 零交集，属另一批遗留分区，由 `evaluation/split_seal.py` 在密封时划分）。
- v2.0.11 冻结候选 136 行全部在草稿池内（v211 ⊂ draft，反向差集为空）。草稿多出的 14 行是 v2.0.x 治理链在冻结候选层**分批退休**的 case，退休轨迹（依据各修订目录 manifest 的 counts.retired 与 draft-before/after 逐版比对）：
  - v2.0.5 退休 zh-033 → 149；v2.0.6 退休 zh-032 → 148；
  - v2.0.8 退休 en-044 / en-050 / mixed-026 / zh-042 / zh-045 → 143；v2.0.9 退休 mixed-027 / multi-030~034 → 137；v2.0.10 退休 multi-019 → 136。
- 这 14 行自草稿创建（annotation_version=v2.0.0、created_at=2026-08-05、annotated_by=zcode-draft）起就在草稿池：v2.0.x 链只在冻结候选层退休它们，草稿层从未删除。
- 2026-08-29 人工终审对草稿 150 行全集执行（commit f28cce5），overlay 覆盖全部 150 case → 被退休的 14 行经终审 confirmed，按 **supersession** 取代旧退休状态。
- 草稿与 v2.0.11 交集 136 行存在 31 处真值字段差异：全部源于 owner 2026-08-29 仲裁的 8 条证据优先修复（en-044 / en-048 / en-052 / mixed-022 / zh-057 / noanswer-039 / noanswer-040 / noanswer-050）落草稿（f28cce5）；overlay 与修复后的草稿一致。
- 依据 manifest/ledger：v2.0.5/6/8/9/10 各修订目录 manifest、v2.0.11 evaluation-freeze（含 18 条 deferred-owner-decisions）、commit f28cce5、overlay manifest inputs SHA 链。

### A2 batch1 里 18 条 deferred-owner-decisions 的现状

- v2.0.11-freeze 阶段（`evaluation-freeze/deferred-owner-decisions.jsonl`，owner_decision=deferred）
  的 18 条 case 已被**完整消解**，无遗留：
  1. 全部 18 条进入 batch1 rulings ledger（`v2.1-owner-rulings-batch1/rulings-ledger.jsonl`）：15 条 maintained_reject_archived + 3 条 restored_pending_verification（mixed-022 / multi-012 / zh-023）；
  2. batch2 终裁（final-rulings-batch2）：mixed-022 → retired_ambiguous_phrasing；multi-012 / zh-023 → verified_active；
  3. 2026-08-29 人工终审：18 条全部在 overlay 150 池内且 confirmed——旧处置（含 15 条 maintained_reject_archived 的「维持退休」）被终审真值取代（supersession），历史 ledger 保持原样未改写。

### A3 草稿 id 集合与 rulings 分类账的交集

- rulings ledger 共 22 条 case（15 maintained + 4 contract_blind_review_authorized + 3 restored），**全部在草稿 150 行池内**（ledger − draft = 空集）。
- 6 条 final-rulings case（en-052, mixed-022, mixed-030, mixed-033, multi-012, zh-023）**全部在池内**（本工具门 4 固化该约束）。

### A4 草稿与 overlay 逐 case 真值一致性预检

- 预检与正式门 3 双重确认：150 case × 5 真值字段（should_refuse, relevance_level, acceptable_answer_points, relevant_source_ids, relevant_chunk_ids）草稿顶层值 == overlay 值，零不一致、零顺序差异——无系统性错位。

## 三、池构成

| 构成 | 数量 | 说明 |
|---|---|---|
| 草稿池（= overlay 池 = v2.1 数据集） | 150 | case-freeze partition=new 全集 |
| ├ 与 v2.0.11 冻结候选交集 | 136 | 修订链持续维护的候选 |
| └ v2.0.x 链外行（曾在候选层退休） | 14 | 2026-08-29 终审 confirmed，supersession 取代旧退休 |
| legacy_dev 分区 | 110 | 不在草稿池；与激活无关 |
| rulings ledger 涉及 case | 22 | 全在池内 |

## 四、supersession 逐 case 记录（6 条 final-rulings case）

历史 ledger 永不改写；下表仅记录「旧裁决 → 新证据链 → 新状态」的取代链。

| case | batch1（2026-08-27） | batch2 终裁（2026-08-27） | 2026-08-29 新证据链 | v2.1 终态 |
|---|---|---|---|---|
| zh-023 | restored_pending_verification | verified_active（机械包含证据 + 新鲜密封盲审两线一致） | 修复后草稿 → 终审 confirmed（f28cce5 转移）→ overlay | confirmed |
| multi-012 | restored_pending_verification | verified_active（同上两线一致） | 同上 | confirmed |
| mixed-022 | restored_pending_verification | retired_ambiguous_phrasing（命题双读歧义退休） | owner 批示「同意 reject（草稿错误成立）」→ 答案点改写「条目为中英混合：英文定义 + 中文正文解释」→ round-2 修复复核 confirmed （notes 留档） | confirmed（取代 retired） |
| en-052 | contract_blind_review_authorized | retired_persistent_contract_error（契约盲审三次独立复现） | owner 批示 → 问题改「各自保证什么」+ Rust 答案点=内存安全保证 + 证据 chunk_37→chunk_53+43 → round-2 修复复核 confirmed | confirmed（取代 retired） |
| mixed-030 | contract_blind_review_authorized | retired_persistent_contract_error | 无专项仲裁修复；由 owner 授权的人工终审对修复后草稿 150 行全集直接 confirmed （round-1，142 confirmed 之内）→ overlay | confirmed（取代 retired） |
| mixed-033 | contract_blind_review_authorized | retired_persistent_contract_error | 同 mixed-030（round-1 confirmed）→ overlay | confirmed（取代 retired） |

> 诚实说明：mixed-030 / mixed-033 的旧 retired 裁决由 2026-08-29 授权代理终审的 150/150 confirmed overlay 整体取代，未单独走 owner 仲裁修复；若 owner 要求补强，可在 v2.1.x 治理轮对这两条追加专项裁决（历史账本依旧不改写）。

## 五、激活门结果

| 门 | 结果 | 详情 |
|---|---|---|
| 1 overlay manifest 状态/计数/SHA 链（含 inputs 全量复算） | PASS | {"decision_counts":{"confirmed":150,"needs_followup":0,"reject":0},"inputs_verified":["human_review_pack","draft","chunks","chunk_manifest","corpus_manifest","repair_ledger"],"o… |
| 2 草稿 id 集合 == overlay case_id 集合（双向差集空） | PASS | {"draft_count":150,"draft_only":[],"overlay_count":150,"overlay_only":[]} |
| 3 逐 case 五真值字段一致（顺序敏感） | PASS | {"cases_compared":150,"mismatches":[],"order_only":[]} |
| 4 6 条 final-rulings case 在池内 | PASS | {"cases":["en-052","mixed-022","mixed-030","mixed-033","multi-012","zh-023"],"missing_from_pool":[]} |

## 六、产物

| 产物 | 说明 |
|---|---|
| `v2.1-dataset.jsonl` | 150 行，草稿 schema，顶层透传 + annotation 终审状态 |
| `manifest.json` | 输入 SHA 快照、声明、四门结果、自哈希 |
| `evaluation/datasets/v2.1.jsonl` | 发布副本（与数据集逐字节一致） |

## 七、evaluation/schema.py 兼容性边界发现（schema 未改动）

- `evaluation.schema.EvalCase` 为「annotators write, runners read」的静态契约，仅接受 9 个核心字段；v2 草稿扩展的顶层字段 `note / annotation / relevance_level / is_refusal_turn / relevant_chunk_ids / doc_target` 以及 `relevant_chunks[].chunk_id` 会导致 `from_dict` 的 `cls(**d)` 抛 TypeError。
- 发布自检采用**投影验证**：去除上述 6 个顶层扩展字段与 chunk 内 `chunk_id` 后 `load_dataset` 加载 150 条、`validate_dataset` 零警告；真值字段（should_refuse / relevant_chunks / acceptable_answer_points 等）均在契约内。
- v2.1 数据集以草稿 schema（超集）为准发布；schema.py 一字未改，消费方需要时可自行投影。

## 八、确定性

- 产物不含时间戳与随机源；激活日期、裁决日期均为常量。
- run 内置**双构建字节断言**：构建链执行两次，任一字节差异即 fail-closed 零输出。
- 验收时另做外部文件级双跑比对（连跑两次脚本，产物 SHA 一致），见验收记录。

## 九、身份与授权声明

- 终审 confirmed 由 AI 代理（zcode-agent-2026-08-29）在 owner 明确授权下执行；owner 于 2026-08-29 对 8 条阻断 case 作出真人仲裁批示（6 条 reject 草稿错误成立 + noanswer-039/040 翻可答）。
- review_status = `human_review_confirmed_agent_adjudicated` 如实标识「代理复核 + owner 仲裁」，绝不伪称真人逐条复核。
- 冻结资产只读：v2.0.x 修订树、v2.0.11 冻结候选、v1 数据集、rulings ledger 未被写改；本工具无任何 git 操作。

## 十、发布自检

- `ok: 150 cases loaded via evaluation.schema.load_dataset, validate_dataset 0 warnings（投影去除 6 个顶层扩展字段与 relevant_chunks[].chunk_id；schema 本身未改动）`

