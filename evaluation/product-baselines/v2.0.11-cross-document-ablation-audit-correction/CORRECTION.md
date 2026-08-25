# Audit Correction — Phase 6-C1.1（v2.0.11 跨文档检索消融）

## 范围

- 对 Phase 6-C1 产物的**报告/产物语义修正**（只读审计）：不重跑实验、不迭代测试集/语料/v2.0.11。
- 原 C1 目录与全部 7 个原文件字节不变：本包只读核验并记录 SHA，绝不覆盖。
- 无 LLM / 网络 / Chroma 建索引 / 检索重跑 / overlay/active/split/locked/v2.1 产物；默认产品检索路径不变。

## 语义修正 1：运行一致性表述

- **原表述**：原 CHANGELOG/记录以「运行一致」概括两次独立完整运行（并称基线聚合与 hardened 相同、cd recall@5 跨构建噪声为 0），未区分「结论方向稳定」与「逐案例/部分聚合指标一致」——该表述不成立。
- **更正后**：NO_PROMOTION 结论与 cross-document recall@5 失败方向在两次独立完整运行间稳定；但 raw ranking（跨运行 per-case 差异 baseline 34 / candidate 90；运行内第二次构建 raw 差异 baseline 77 / candidate 225）、逐案例指标（运行内 metric 差异 baseline 1 / candidate 20 case）与候选整体聚合指标（运行内 build2 相对主构建：recall@5 Δ+0.009524, recall@10 Δ-0.004762, ndcg@5 Δ+0.002437, ndcg@10 Δ-0.003015, ndcg@20 Δ-0.001368, mrr Δ-0.001729，max|Δ|=0.009524；跨运行聚合 Δ max|Δ|=0.005215）存在已记录的 HNSW 非确定性差异——任何「完全一致/逐位一致」的表述均不成立。
- 证据（全部取自原 C1 manifest/summary 记录，本包不重算）：
  - 运行内第二次独立构建整体指标差异：基线 max|Δ|=1.6e-05，候选 max|Δ|=0.009524；
  - 运行内跨构建 raw 差异：基线 77 / 候选 225；metric 差异：基线 1 / 候选 20 case；
  - 跨运行 per-case 差异：baseline 34 / candidate 90；cd recall@5 跨构建噪声 0.0。

## 语义修正 2：data_quality 与 promotion_eligibility 分离

- **原表述**：原 data-quality-report.json passed=True / error_count=0，但 30 条 checks 中追加了 4 条 ok=false 的 gate 条件（追加于 error_count 计算之后）——「全部通过」的表述不成立。
- **更正后**：核心 data-quality 检查（完整性/唯一性/指标复算/引用完整性/谱系与 manifest 闭环）共 21 项全部通过；promotion gate 6 条中 4 条未通过 → NO_PROMOTION；失败 gate 是实验决策结果，不是 data-quality 失败，也不得混入 data-quality checks。
- 数据模型（corrected-data-quality-report.json）：
  - `data_quality`：核心完整性/唯一性/指标复算/引用完整性/谱系与 manifest 闭环检查，`passed` 由这些检查重新计算——passed=true 时 核心 checks 必无 false；
  - `promotion_eligibility`：6 条预先锁定的 gate 条件、失败条件与 决策——失败 gate 不是 data-quality 失败，也不混入 `data_quality.checks`；`data_quality.passed` **不暗示** promotion 通过。

## 原 C1 核验

- manifest self-hash：`45f40c63e5dccb18ebe855f575d10410ff59af186585af1d943f5ca35b0cf350`（复算一致）；
- 6 个原 C1 outputs 字节 SHA 全部复算一致（7 项检查；明细见 manifest.json inputs 与 correction-summary.json）。

## 最终判定（更正后，与原 C1 一致）

- 核心数据质量：通过。
- Promotion gate：4/6 条未通过（['cd_recall@5_gain', 'overall_recall@5_no_drop', 'overall_ndcg10_mrr_no_drop', 'exceeds_recorded_noise']）→ **NO_PROMOTION**。
- 默认产品检索策略**未改变**（候选仅记录于消融产物，任何采用须经后续独立阶段决策）。
- v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、human_reviewed=false），不是 active、release 或人工批准。

## 未测项与限制

- not_measured：answer quality / citation faithfulness / answer-level refusal accuracy（沿用原 C1 声明，见 manifest）。
- `data-analytics:analyze-data-quality` 实际检查：zcode 运行环境不可用（本次会话可用技能列表、`~/.zcode/skills`、`~/.agents/skills`、插件目录均无）——不能声称所有环境均不可用；实施等价确定性复算。
- 本包不重算检索指标；全部数字取自原 C1 记录并如实转述。
- 未 stage/commit/push；既有脏工作区保留。
