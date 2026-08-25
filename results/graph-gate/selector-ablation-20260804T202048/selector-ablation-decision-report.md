# Selector 策略消融自动决策报告（AUTOMATED_DIAGNOSTIC）

> **状态：AUTOMATED_DIAGNOSTIC_NO_GO** — 保持生产默认 `RAG_SELECTOR_MAX_PER_SOURCE`（cap=3）。
> 全部结论为自动化诊断，非人工审核；真值 overlay 为 auto-run 自动标注的
> provisional 版本。运行目录：`results/graph-gate/selector-ablation-20260804T202048/`。

## 一、实验设计（受控）

| 维度 | 设定 |
|---|---|
| 实验变量 | context selector 同源上限：**S0**=selector-unlimited（`max_per_source=None`，不限同源）/ **S3**=selector-cap3（`max_per_source=3`，每源最多 3） |
| 固定 | 同一数据集/QueryPlan/候选池（逐 case 相同）、同一 budgets/top-k/邻接规则、同一模型（deepseek-chat）与 generation 配置；双臂均 `RAG_RERANKER=none`、Graph 禁用、alpha=1.0 |
| 控制 | 双臂同进程共享 QueryPlan（rewrite_ms 逐 case 一致）；候选池逐 case 逐 chunk 相同；双臂 rerank_ms≈0（无 reranker）；lock-S0S3.json 含 per-arm `arm_selector_policy`，预检/后验 fail-closed 校验通过 |
| 数据 | dev 94 例（chunk 真值 62、source 有效 72、生成 72）+ holdout 15 例（10/12/12）；分层 smoke 12 例先行通过 |
| 引用口径 | 契约 v2：`context_supported_citation_validity`（正式 guardrail 指标）；历史 citation precision/faithfulness 不参与判断 |

## 二、dev 结果（n=94）

### 生成层（answer 质量）
| 指标 | S0 (unlimited) | S3 (cap=3) | 差异（S3−S0） |
|---|---|---|---|
| answer_point_coverage | 0.660 | 0.662 | +0.002，95%CI [−0.063, +0.069]，W/L/T=6/4/62 |
| context_supported_citation_validity | **0.875** | 0.847 | −0.028，95%CI [−0.083, +0.014]，W/L/T=1/3/68；McNemar p=0.625 |
| citation_id_validity | 0.713 | 0.691 | −0.022 |
| 无引用答案数（validity=0） | 9 | 11 | S0 更少 |
| 无 context-supported 引用数 | 9 | 11 | S0 更少 |
| fabricated 引用均值 | 0.00 | 0.00 | 无 |
| false_refusal（可答误拒） | **10** | 15 | McNemar 不一致 7（S0 侧 1 / S3 侧 6），p=0.125 |
| 生成延迟 mean / p95 (ms) | 3137 / 7600 | 2359 / 3492 | context tokens 几乎相同（2850 vs 2823）→ 主要为 API 方差 |

### 检索层
| 指标 | S0 | S3 | 差异 |
|---|---|---|---|
| context_recall | **0.666** | 0.577 | 配对 Δ=−0.089，**95%CI [−0.153, −0.032]（不含 0，S0 显著更优）** |
| retention（相关 chunk 保留率） | **0.720** | 0.625 | +0.095 |
| squeeze（候选→context 挤出率） | **0.280** | 0.375 | −0.095 |
| candidate_recall | 0.845 | 0.845 | 相同（候选池一致） |
| 同源候选排名≥4 的相关 chunk 保留 | **22/47** | 15/47 | cap3 挤出 7 个 |
| source_recall@5 / @10 | 0.983 | 0.983 | 相同 |
| context_source_recall | 0.903 | **0.928** | S3 更广 |
| context_source_coverage | **0.725** | 0.590 | S0 更高 |

### Context 形态（diversity 的可观察差异）
| 指标 | S0 | S3 |
|---|---|---|
| context chunk 数均值 / 最大 | 10.0 / 10 | 9.7 / 10 |
| context source 数均值 | 1.74 | 2.13 |
| 单源 context 占比 | **38%** | 10% |
| context 内单源最大 chunk 数（最终，含扩展） | 10 | 9 |

> 说明：cap=3 是「选择层」约束（select_context_candidates 时每源 ≤3）；
> 最终 context 经 parent/adjacent 扩展可超 3（生产既有行为，双臂一致）。
> 选择层差异由「同源 rank≥4 保留数」与 context_recall 佐证。

### 切片（cov，S0 vs S3，W/L/T）
- zh n=27：0.802 vs 0.691（S0 优，0/3/24）；en n=30：0.544 vs 0.633（S3 优，5/1/24）；mixed n=15：0.633 vs 0.667（1/0/14）
- single_fact n=31：0.737 vs 0.710（4/4/23）；cross_document n=11：0.424 vs 0.470（1/0/10）；mixed_intent n=10：0.533 vs 0.583；metadata n=14：0.643 持平；multi_turn n=6：0.944 持平
- graph_target n=21：0.476 vs 0.524（2/0/19）；source_only n=10：0.450 持平（cit v2 0.300 vs 0.400）

## 三、holdout 结果（n=15；生成 12 例）

| 指标 | S0 | S3 | 差异 |
|---|---|---|---|
| answer_point_coverage | 0.639 | 0.681 | +0.042，95%CI [−0.083, +0.250]，W/L/T=1/1/10 |
| context_supported_citation_validity | 0.833 | 0.833 | 0（McNemar 不一致 0） |
| context_recall | 0.875 | 0.875 | 0（配对 Δ=0） |
| false_refusal | 1 | 3 | S0 更少（p=0.5） |
| 同源 rank≥4 保留 | 4/6 | 4/6 | 持平 |
| context source 数均值 / 单源占比 | 1.73 / 40% | 2.13 / 7% | 形态差异与 dev 一致 |

**功效限制**：holdout 生成配对仅 n=12，95%CI 宽度 ±0.25，无法区分 ±0.04 级差异；
检索配对 n=10。holdout 仅作独立方向确认，不具统计功效。

## 四、自动决策

**门槛判定**（按任务规则）：
1. dev 是否有一方获得**稳定 answer 质量收益**？→ **否**：cov Δ=+0.002，CI [−0.063, +0.069] 跨 0，72 例中 62 例打平；citation v2 与拒答均无显著差异（McNemar p=0.625 / 0.125）。
2. 因此**不满足**「进入 holdout 确认」的条件（holdout 结果仅作记录：cov 方向偏 S3 但不显著、ctx_recall 与 citation v2 完全持平，未确认任何一方）。
3. **结论：AUTOMATED_DIAGNOSTIC_NO_GO** — 不自动修改生产默认（保持 `RAG_RERANKER=none` + selector 同源上限 3）。

**诊断性发现（供人工复核，非自动结论）**：
- S0（unlimited）在 dev 检索层有**统计显著**收益：context_recall +0.089（CI 不含 0）、同源 rank≥4 相关 chunk 保留 22 vs 15；且生成层**无实质回归**（cov 打平、citation v2 与拒答均略优）。
- S3（cap=3）的优势在 source 覆盖广度：context_source_recall 0.928 vs 0.903、单源 context 占比仅 10% vs 38%；en 切片 cov 0.633 vs 0.544。
- 检索收益未转化为 answer 收益（与 reranker-recheck 的「生成层打平」一致），故不满足自动切换门槛。

## 五、建议（是否切换生产默认）

**自动建议：保持生产默认 cap=3（不切换）。**
- 若人工复核优先「answer 质量确定性」：维持现状（cap=3）。
- 若人工复核接受「检索层显著收益 + 生成层无回归」并愿承担单源集中/跨文档覆盖风险：unlimited（S0）是合理候选——但需先人工审核真值标注、评估 en/跨文档切片（S3 占优方向）与延迟差异后，再重跑受控确认。

## 六、产物与约束

- 产物：`precheck.py / gen_locks.py / prep_smoke.py / analyze_s0s3.py`、
  `lock-S0/S3/S0S3.json`、`precheck-snapshot.json`、`smoke/`、`dev-full/`、
  `holdout-full/`（summary/generation-summary/逐 case JSONL/manifest/failures.csv）、
  `s0s3-analysis.json`、`smoke-run.log / dev-full.log / holdout-full.log`、
  `run-commands.md`、本报告。
- 约束遵守：未修改 `decision-report.md` 与任何历史 results 目录（immutability
  快照 14 文件复验 PASS）；未改生产默认配置；未 stage/commit；无 secret 入库。
- 前置条件（未做，需另行确认）：若要把 citation v2 作为正式 guardrail，需在
  本受控框架上重跑 selector policy ablation 建立基线（本报告即该基线的一版）。
