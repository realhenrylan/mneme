# Mneme RAG 改进最终就绪审计 — 自动化闭环结论

> 审计方式：只读交叉核验（不修改代码、不运行 LLM/API、不重跑评测、不 stage/commit）。
> 目录：`results/graph-gate/final-readiness-20260804T204839/`
> 审计时间：2026-08-04 20:48
> 状态：**AUTOMATED_READY**（工程可合并、策略保持基线）—— 非人工审核、非正式上线批准。

---

## 1. 结论摘要

| 项目 | 结论 |
|---|---|
| 代码默认与建议生产基线一致 | ✅ 完全一致（见 §2） |
| 全部离线单元测试 | ✅ **783 passed / 7 skipped**（本次重新运行验证） |
| 编译与 diff 卫生 | ✅ py_compile OK；`git diff --check` exit 0（仅 LF/CRLF 提示） |
| 受控评测框架与门禁 | ✅ QueryPlan 共享、locked-config fail-closed、review overlay、citation v2 就绪 |
| Graph / reranker / selector 三项自动决策 | 均为 **AUTOMATED_DIAGNOSTIC_NO_GO**（保持现状，见 §4） |
| 人工审核与正式上线批准 | ❌ **未获得**——按 §5 清单完成后才能重新讨论策略变更 |

**自动化就绪状态：达到「工程可合并、策略保持基线」。**
即：当前工作区代码（未 commit）可安全合并；生产默认应保持 `RAG_RERANKER=none` +
`RAG_SELECTOR_MAX_PER_SOURCE=3` + Graph 不产品化；任何策略切换都需要人工审核后的
新受控评测，本审计不授权任何自动切换。

---

## 2. 建议生产基线 vs 代码默认（逐项核验）

| 建议基线 | 代码默认 | 核验依据 | 一致 |
|---|---|---|---|
| `RAG_RERANKER=none` | `RAG_RERANKER_MODE = os.getenv("RAG_RERANKER", "none").lower()` | `src/rag.py:205` | ✅ |
| `RAG_SELECTOR_MAX_PER_SOURCE=3` | env 未设置时 `SELECTOR_MAX_PER_SOURCE = 3`；`none/unlimited/0` → None（不限同源），非法值导入期 fail-fast | `src/rag.py:213-219`；生产 4 处 selector 调用点均读该变量（`src/rag.py:1795/1810/2054/2069`） | ✅ |
| Graph 不作为产品化路径 | `src/rag.py` 无任何 alpha/Graph 引用——生产 `answer_query` 链路不含 Graph 通道；Graph 仅存在于 `src/graph_rag.py` 与评测框架 `_graph_enhanced_answer_query`（`evaluation/compare.py:1579`） | grep `alpha`/`graph` in `src/rag.py` 为空 | ✅ |
| alpha=1.0 仅为对照 | auto-run 锁定的 `active_alpha=1.0`（即"无 Graph 同路径对照"本身胜出，alpha-selection 证据在 `auto-run-20260804T121410/alpha-selection.json`） | locked-config + automated-decision-report §2 | ✅ |

**差异与风险**：无配置差异。唯一需注意的能力性观察（非不一致）：`RAG_RERANKER`
env 被显式设为 `cross-encoder` 时生产会启用 reranker——这是受支持的可配置能力，
但三项自动评测（auto-run、reranker-recheck、selector-ablation）均判定其无生成层
净收益，**不建议在生产启用**。

---

## 3. 各项改进状态汇总

### 3.1 评测/工程能力（阶段 0 + 本会话基础设施）

| 能力 | 状态 | 证据 |
|---|---|---|
| 阶段 0：评测基线框架（dataset/runner/metrics/generation/citation/compare 受控对比） | ✅ 完成 | `evaluation/`；`results/graph-gate/dev/`（旧）与三次受控运行 |
| QueryPlan 共享（A/B/C 双臂复用同一 rewrite/decompose 计划，rewrite_ms 逐 case 一致） | ✅ 完成 | `evaluation/compare.py:887` `QueryPlan` / `prepare_query_plan`；reranker-recheck 公平性审计 95/95、selector-ablation 逐 case 一致 |
| review overlay（导出 → 人工填写 → 严格导入门禁，source-only 分母隔离） | ✅ 完成 | `evaluation/review_pack.py` / `review_apply.py`；37 个单元测试；`REVIEW_PACK_README.md` |
| locked-config（版本化、确定性、fail-closed 指纹/预算/arms/per-arm selector policy 校验） | ✅ 完成 | `evaluation/locked_config.py`；43 个单元测试（34 基础 + 9 selector policy） |
| citation 契约 v2（`context_supported_citation_validity` 正式 guardrail + 逐引用证据链） | ✅ 完成 | `evaluation/citation_metrics.py`；28 个单元测试 |

### 3.2 阶段 2/3 工程能力（RAG-IMPROVEMENT-PLAN-2026-08-01.md 定义）

> 注：该计划状态仍为「待审批」，以下为**代码先行落地**状态，非计划整体闭环。

| 能力 | 代码状态 | 证据 |
|---|---|---|
| 结构化摄取（统一 loader 模型） | ✅ 已实现 | `src/loaders/{base,pdf_loader,docx_loader,text_loader}.py`（`Document/Section/Chunk` 在 `src/domain.py`） |
| Parent-Child / 邻接扩展（结构化分块） | ✅ 已实现 | `src/chunking.py`（Section 边界切分 + parent chunk + 相邻 chunk 记录）；生产 `expand_with_parent/expand_with_adjacent` 已在受控评测中生效（context 可超 selector 预算即扩展行为） |
| 多轮检索改写 + 漂移防护（QueryPlan 的生产侧对应） | ✅ 已实现 | `src/rag_query_rewriter.py`（standalone rewrite + 原 query 保底合并）、`src/rag_query_decomposer.py`；multi_turn 切片在三次受控评测中均有覆盖 |
| BM25 增量 / 索引并发安全 | ✅ 已实现（能力层） | `src/lexical.py`（BM25）；`src/index_queue.py`（串行化索引变更 + 不可变 `IndexSnapshot` 查询输入快照）；评测索引复用缓存（`force_rebuild=False`） |
| 可观测性（分阶段延迟/TTFT/token/持久化） | ✅ 已实现 | `src/metrics.py`（隐私：不记录查询文本/API Key） |
| LLM Gateway（单例、timeout/retry/stream/usage） | ✅ 已实现 | `src/llm_gateway.py` |

### 3.3 三项自动决策及其适用边界

| 决策 | 结论 | 核心证据 | 适用边界（不可外推） |
|---|---|---|---|
| **Graph**（C 通道） | AUTOMATED_DIAGNOSTIC_NO_GO | `auto-run-20260804T121410/automated-decision-report.md`：alpha 扫描后锁定 1.0（无图对照胜出）；alpha<1 时 graph_target context_recall 反而下降（0.340-0.390 vs 0.390）；lift/pollution 均 0 | 仅 6 文档小语料（736 chunks、KG 1290 entities/5124 edges）；graph_target dev 仅 20、holdout 仅 3；结论不构成大知识库下的 Graph 判据 |
| **Reranker**（B 通道） | AUTOMATED_DIAGNOSTIC_NO_GO | `reranker-recheck-20260804T185937/reranker-recheck-decision-report.md`：dev cov Δ=−0.001（CI [−0.071,+0.073]）、holdout 方向为负（Δ=−0.111，CI 上界 0.000）；检索层修复生效（同源 rank≥4 保留 12→20/45、zh-002 恢复）但未转化生成收益；延迟成本明确（dev p95 3.2s→14.7s） | 受控框架内有效（A/B 同 QueryPlan/selector/budgets）；holdout n=12 功效不足，不能断言显著回归，只能判"无净收益" |
| **Selector**（同源上限 3 vs 不限） | AUTOMATED_DIAGNOSTIC_NO_GO | `selector-ablation-20260804T202048/selector-ablation-decision-report.md`：S0 检索层显著优（ctx_recall Δ=−0.089，CI [−0.153,−0.032]；rank≥4 保留 22 vs 15）但生成层打平（cov Δ=+0.002，CI [−0.063,+0.069]，W/L/T=6/4/62）；holdout n=12 功效不足 | 仅无 reranker（RAG_RERANKER=none）基线有效；unlimited 在单源集中（38% vs 10%）与 en 切片（S3 优）有明确风险方向；切换需人工审核后重跑独立 holdout |

---

## 4. 失效/不可用于正式上线判定的历史指标与产物

以下内容**只能作诊断参考**，不得作为上线 guardrail 或策略判据：

1. **citation v1 的 precision/recall/faithfulness（全部失效）**
   - 占位输入 bug：`all_retrieved_ids=set()`、`context=""` → precision 恒 0、faithfulness 恒 0
   - 受影响产物：`auto-run-20260804T121410/`（dev-full/holdout-full generation-summary 与 automated-decision-report 引用指标）、`reranker-recheck-20260804T185937/ab-analysis.json`（`citation_precision: 0.0, citation_recall: 0.0`，本次核验确认）、旧 P0 baseline（generation_runner 产出）
   - 修复见 `citation-eval-fix-20260804T200234/citation-evaluation-fix-report.md` §4

2. **citation_id_validity（retrieval-level，语义未变但非 guardrail）**
   - 只证明"引用 ID 在 sources 展示集中"，不证明"证据进入最终 LLM prompt context"；绝对值不可与 `context_supported_citation_validity` 互比。历史值（auto-run 0.726/0.632/0.653、reranker-recheck 0.695/0.653）仅可用于组间相对方向参考

3. **使用修复前 selector 的旧 A/B 绝对分数（不可与修复后比较）**
   - 旧 A 无 source diversity、无对称 `select_context_candidates`（修复于 reranker-fix 批次）
   - 受影响产物：`results/graph-gate/dev/`（旧 P1 dev：recall@5 0.337、context_recall 0.429——本次核验确认）、`auto-run-20260804T121410` 的 A 臂绝对分数（0.646 cov）、`reranker-regression-diagnosis.md` 绝对分数（A=0.646/B=0.575）
   - reranker-recheck 与 selector-ablation 已声明「禁止与旧绝对值比较」，本审计确认其遵守

4. **含自动 provisional 真值的结论（全部自动评测）**
   - 27 条 overlap 标注中 **22 条低置信 `auto_provisional`**（`auto-annotation-evidence.json` 核验：`overlap_provisional_count=22`、`overlap_confirmed=27`、`missing_source=12`、`missing_provisional_count=5`）
   - 因此 auto-run、reranker-recheck、selector-ablation 的 chunk 级指标（context_recall 等）均基于未人工审核真值 → 只能作诊断参考；若人工审核改变真值，结论可能改变，必须重跑

5. **口径不一致观察（正式 guardrail 必须固定分母）**
   - reranker-recheck 报告 citation_id_validity 用**全体分母**（0.695 = 66/95）；selector-ablation 报告 citation v2 用**可答分母**（0.875 = 63/72）；selector-ablation 目录内 `generation-summary.json` 又是全体分母（0.713 = 67/94）。三者数值不同但各自计算正确，均无 bug；差异来自分母选择。**guardrail 阈值建立前必须先固定分母口径**
   - 附带观察：4 个 noanswer-* case（noanswer-002/003/013/023）在 `should_refuse=True` 下仍有非零 citation validity——即假答（false_answer）案例，属预期行为，非指标异常

6. **空目录残留（无害，无内容）**：`citation-eval-fix-20260804T210416/`、`reranker-recheck/`（19:39 创建）

---

## 5. 证据链接（全部核验通过项）

| 证据 | 位置 |
|---|---|
| 本会话三次受控评测 + 全部脚本/锁/日志 | `results/graph-gate/{auto-run-20260804T121410, reranker-recheck-20260804T185937, selector-ablation-20260804T202048}/` |
| citation v2 实现报告 | `results/graph-gate/citation-eval-fix-20260804T200234/citation-evaluation-fix-report.md` |
| 原 Graph 决策报告（v1.1，未改动） | `results/graph-gate/decision-report.md`（mtime 2026-08-02 19:54，早于全部后续运行；v1.1 为原作者会话更新，immutability 快照复验 PASS） |
| 自动标注证据（22 低置信） | `auto-run-20260804T121410/auto-annotation-evidence.json` |
| 代码默认 | `src/rag.py:205`（reranker none）、`src/rag.py:213-219`（selector 3）、`evaluation/compare.py:93-108`（消融臂映射 A/B/C→3） |
| 测试 | 本次运行 `python -m pytest -q` → **783 passed, 7 skipped**（55s）；`py_compile` OK；`git diff --check` exit 0 |
| git 状态 | HEAD `37d076a`；全部改动未 stage/commit（含 `evaluation/compare.py` 等 12 个修改 + 新文件 + 结果目录）；无敏感凭据入库（`.gitignore` 含 `.env`；各 manifest 仅记录 env 存在性） |

---

## 6. 约束遵守声明

- 未修改代码、未运行 LLM/API、未重跑评测、未 stage/commit；
- 未改写任何历史 results 目录与 `decision-report.md`（本审计仅新增
  `final-readiness-20260804T204839/`）；
- 全部结论为自动化审计/自动化诊断，真值仍含自动 provisional 标注；
- 不构成人工审核或正式上线批准。
