# Reranker 修复后受控重新评测 — 决策报告

> **状态：AUTOMATED_DIAGNOSTIC（自动化诊断结论）**
> 本报告全部标注、评测与结论由自动化流程生成，**未经人工审核**，不构成正式
> GO/NO-GO 上线结论。生产默认配置未修改。
> 运行目录：`results/graph-gate/reranker-recheck-20260804T185937/`
> 生成时间：2026-08-04

---

## 1. 实验设置

| 项目 | 值 |
|---|---|
| 唯一实验变量 | reranker：A=`RAG_RERANKER=none`，B=修复后 chunk-aware cross-encoder（ms-marco-MiniLM-L-6-v2） |
| 固定要素 | 同一数据（v1.jsonl，SHA `57602995…`）、同一语料（test_texts，SHA `41fdb853…`）、同一索引（index_sha256 `c6b54781…`、736 chunks、复用缓存）、同一 QueryPlan（单进程共享缓存）、同一 context selector（`select_context_candidates(top_k=min(k,20), max_per_source=3)`，A/B 同代码路径）、同一 budgets/模型/generation 配置 |
| Graph | **禁用**（arms 不含 graph-rerank；alpha=1.0，无 graph 通道） |
| 锁配置 | `lock-AB.json`（arms=[standard, standard-rerank]，reranker_mode=cross-encoder，kg_sha256=None not-applicable；固定字段与原 auto-run 锁逐字段一致，dev/holdout 均通过 fail-closed 校验） |
| overlay | 复用 auto-run 自动标注 overlay（27 entries + 12 case levels，dataset SHA 校验通过） |
| 环境 | deepseek-chat（BASE_URL/API_KEY present，值不入库）、all-MiniLM-L6-v2、seed 42、bootstrap 1000 iters/seed 42 |
| 代码 | git 37d076a + 工作区改动（reranker 修复已含）；不 stage/commit |

预检：完整 pytest **738 passed / 7 skipped**，py_compile OK，`git diff --check` 干净；
分层 smoke（12 例：zh/多轮/graph_target/source-only/refusal）通过后自动进入 dev/holdout 全量。

**口径声明**：本目录 A 臂与 `auto-run-20260804T121410/` 的 A 臂不可直接比
（旧 A 无 source diversity、无对称 selector）；一切结论仅来自本次受控 A/B。

## 2. Dev 全量（95 例）A/B 结果

### 2.1 检索层（chunk 真值 n=63；source 真值 n=73）

| 指标 | A | B | Δ(B−A) |
|---|---|---|---|
| context_recall | 0.544 | **0.568** | +0.024 |
| context_precision | 0.078 | 0.087 | +0.009 |
| 相关 chunk 保留率（cand→ctx） | 0.592 | **0.626** | +0.034 |
| 挤出率（cand∩rel 未进 ctx） | 0.408 | **0.374** | −0.034 |
| candidate recall（同池） | 0.844 | 0.844 | 0（候选池逐 case 相同） |
| source_recall@5 / @10 | 0.983 / 0.983 | 0.983 / 0.983 | 0 |
| context_source_recall | **0.929** | 0.884 | −0.045 |
| context_source_coverage | 0.587 | 0.607 | +0.021 |
| 同源候选排名≥4 的相关 chunk 保留 | 12/45 | **20/45** | +8（26.7%→44.4%） |

### 2.2 生成层（answerable n=73）

| 指标 | A | B | Δ |
|---|---|---|---|
| answer_point_coverage | 0.612 | 0.611 | **−0.001** |
| citation_id_validity | 0.695 | 0.653 | −0.042 |
| 无引用答案数 | 11 | 12 | +1 |
| false_refusal | 16 | 13 | −3 |
| false_answer（拒答题假答） | 9 | 8 | −1 |

### 2.3 Dev 配对检验

- **answer_point_coverage delta = −0.001，95% CI [−0.071, +0.073]**（n=73，block 重采样，跨 0）
- **W/L/T = 5/6/62**（B 赢 5、输 6、平 62；coverage 粗粒度 0/0.5/1.0 高度平局）
- context_recall delta = +0.024，95% CI [−0.078, +0.126]（跨 0，不显著）
- McNemar citation：discordant=11（A_only=5, B_only=6），p=1.000
- McNemar refusal：discordant=14，p=0.424

## 3. Holdout 全量（15 例）A/B 结果（独立确认）

| 指标 | A | B | Δ |
|---|---|---|---|
| context_recall（n=10） | **0.925** | 0.775 | −0.150 |
| 保留率 / 挤出率 | 0.950 / 0.050 | 0.800 / 0.200 | −0.150 / +0.150 |
| context_source_recall（n=12） | **0.917** | 0.833 | −0.083 |
| answer_point_coverage（n=12） | **0.611** | 0.500 | −0.111，CI [−0.278, 0.000] |
| citation_id_validity | 0.667 | 0.467 | −0.200 |
| 无引用答案 | 2 | **5** | +3 |
| false_refusal | 2 | 4 | +2 |
| W/L/T（cov） | — | — | **0/2/10** |
| McNemar citation / refusal | — | — | p=0.250 / p=0.625 |

## 4. 切片（dev）

| 切片 | n | cov A | cov B | W/L/T | ctx_recall A | ctx_recall B |
|---|---|---|---|---|---|---|
| zh | 29 | 0.661 | 0.670 | 3/3/23 | 0.760 | 0.800 |
| en | 29 | 0.534 | 0.517 | 1/2/26 | 0.413 | 0.415 |
| mixed | 15 | 0.667 | 0.678 | 1/1/13 | 0.385 | 0.418 |
| single_fact | 31 | 0.710 | 0.718 | 3/4/24 | 0.597 | 0.661 |
| cross_document | 11 | 0.424 | 0.424 | 1/1/9 | 0.303 | 0.306 |
| mixed_intent | 10 | 0.583 | 0.650 | 1/0/9 | 0.425 | 0.375 |
| metadata | 14 | 0.643 | 0.571 | 0/1/13 | 0.900 | 0.900 |
| multi_turn | 7 | 0.452 | 0.452 | 0/0/7 | 0.571 | 0.571 |
| graph_target（=cross_document+mixed_intent） | 21 | 0.500 | 0.532 | 2/1/18 | 0.364 | 0.341 |
| source_only（cov） | 10 | 0.450 | 0.350 | 0/1/9 | — | — |
| source_only（检索） | 10 | ctx_src_recall A=0.650 B=0.550；coverage A=0.467 B=0.383 | | | | |

无一个切片出现 B 的稳定净收益；metadata/source-only 切片 B 明确偏负，
multi_turn 完全平局。

## 5. 单独验证：同源第 4 个相关 chunk 保留

- **zh-002（诊断回归场景）**：相关 chunk `…chunk_2`（南京城市地理环境.docx）在候选池中
  同 source 排名 = **4**（第 4 个同源候选）→ **A 未保留进 context，B 保留** ✓
- Dev 全量：同源候选排名 ≥4 的相关 chunk 共 **45 个（34 例）**，
  A 保留 12/45（26.7%），**B 保留 20/45（44.4%）**；排名 <4 的 41 个中
  A 保留 33、B 保留 29（B 在低排名段略有损失）。
- 结论：**chunk-aware reranking 修复在检索层精确生效**——被 diversity
  max_per_source=3 挤出的第 4 个同源相关 chunk 恢复保留（12→20/45），
  与 reranker-fix-implementation-report 的预期一致。

## 6. 公平性审计（A/B 对称性）

| 检查 | 结果 |
|---|---|
| 共享 QueryPlan（rewrite_ms 逐 case 一致） | ✓ 95/95（dev）、15/15（holdout） |
| A 未应用 reranker（rerank_ms） | ✓ A=0.0ms（95/95 <1ms）；B 均值 507ms（95/95 >1ms） |
| 同一 context selector 代码路径 | ✓ 双臂均调用 `select_context_candidates(top_k=min(k,20), max_per_source=3)`（单元测试 TestContextSelectorSymmetry 守护） |
| context 长度上限 | ✓ 双臂 max=10（context_max_k） |
| 候选池一致 | ✓ 95/95 例 candidate_chunk_ids 逐位相同（记录为预重排基池） |
| budgets 锁定 | ✓ lock-AB.json budgets 与原锁逐字段一致，fail-closed 校验通过 |

## 7. 自动决策

**结论：AUTOMATED_DIAGNOSTIC_NO_GO — 保持生产默认 `RAG_RERANKER=none`（A）。**

判定依据（按任务规则）：
1. **B 在 dev 的 answer_point_coverage 无稳定净收益**：Δ=−0.001（95% CI
   [−0.071, +0.073] 跨 0；W/L/T=5/6/62，73 例中 62 例平局）→ 不满足
   "稳定净收益" 门槛，**不进入"值得 holdout 复核"结论路径**。
2. **holdout 独立确认方向为负**：cov Δ=−0.111（CI 上界恰好 0.000）、
   context_recall Δ=−0.150、citation_id_validity −0.200、无引用答案 2→5、
   false_refusal 2→4——检索层与生成层一致向负。
3. citation/refusal/source-recall 无实质正向改善（全部 McNemar p>0.05；
   dev source_recall@5 持平 0.983；context_source_recall dev/holdout 均下降）。
4. 检索层修复目标达成（zh-002 恢复、同源第 4 chunk 保留 12→20/45、
   dev context_recall +0.024）——但检索层收益**未转化为生成质量收益**，
   reranker 作为产品配置整体净收益为负/中性。

**执行动作**：不修改生产默认配置（`RAG_RERANKER=none` 保持不变）；
不 stage/commit；不修改任何历史产物。

## 8. 剩余风险与功效限制

- **Holdout 样本量小**（生成配对 n=12、检索配对 n=10）：cov CI [−0.278, 0.000]
  与 ctx_recall CI [−0.350, 0.000] 上界均触 0，**不能在 α=0.05 下断言显著回归**；
  但点估计与所有相关指标（citation、refusal、source）方向一致为负，非孤立噪声。
- **Coverage 粗粒度**：0/0.5/1.0 离散值导致 dev 62/73 平局，paired bootstrap
  功效有限；dev 检索层 +0.024 与生成层 0 的脱节可能是 coverage 不敏感所致，
  也可能是 rerank 引入的 context 扰动无净收益——两者不可区分。
- **B 的 context_source_recall 持续下降**（dev 0.929→0.884；holdout 0.917→0.833；
  source-only 0.650→0.550）：rerank 使 context 集中在少数高分 source，source 级
  覆盖变窄——对 source-only/元数据类查询可能不利（dev source-only cov
  A=0.450→B=0.350）。
- **延迟成本**：B 检索 p95 982ms vs A 123ms（rerank 推理，CPU）；dev B 生成
  total_ms_p95 14.7s vs A 3.2s（含 rerank 与更大 context 波动），无收益下的
  成本代价明确。
- 未人工审核；自动化标注（overlay）本身的风险沿用 auto-run 报告。

## 9. 与旧诊断的关系（禁止直接比较）

- 旧 `reranker-regression-diagnosis.md` 的绝对分数（A=0.646、B=0.575 等）与
  本次**口径不同**（旧 A 无 diversity/对称 selector、旧 B 以 source_name 打分），
  任何直接数值比较均为无效比较，本报告不做。
- 本次确认了诊断的两条根因：根因 1（source_name 打分）与根因 2（diversity
  挤出）已在检索层被修复验证（zh-002、12→20/45）；但**修复后的 B 在端到端
  生成质量上仍无净收益**——诊断"值得单独 reranker 修复任务"的预期收益未在
  生成层兑现，修复任务本身有效、产品收益待定。

## 10. 产物清单

`reranker-recheck-20260804T185937/`：precheck.py/precheck-snapshot.json、
gen_locks.py、lock-A/B/AB.json、prep_smoke.py、smoke-v1.jsonl、smoke-overlay.json、
smoke/、dev-full/（run-manifest/summary/generation-summary/retrieval-cases/
generation-cases/failures.csv/ground-truth-map）、holdout-full/（同结构）、
ab-analysis.json、analyze_ab.py、run-commands.md、smoke-run.log、dev-full.log、
holdout-full.log。
历史产物（auto-run-20260804T121410/、decision-report.md）未修改（immutability
快照见 precheck-snapshot.json，结束时复验）。
