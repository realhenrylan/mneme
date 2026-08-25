# Citation 评测语义修复 — 实现报告

> 目录：`results/graph-gate/citation-eval-fix-20260804T200234/`
> 日期：2026-08-04
> 范围：仅修复评测与可观测性。不调参、不重跑真实 LLM 评测、不修改任何
> 已有 results 目录与 `results/graph-gate/decision-report.md`、不 stage/commit。

---

## 1. 问题

旧 `evaluate_citations` 调用存在占位输入（`evaluation/compare.py` 旧调用点）：

```python
all_retrieved_ids=set(),  # 占位 → citation_precision 恒为 0
context="",               # 占位 → faithfulness 恒为 0（answer_points 非空时）
```

- `citation_id_validity` 只验证"引用 ID 是否出现在本次引用展示（sources）的
  `[S#]` 中"（retrieval-level visible），**无法回答"答案引用的证据是否真的
  进入了最终送入 LLM 的 prompt context"**。
- 该问题在旧 A/B/C 中方向上大致对称（三臂同口径），不破坏组间相对比较，
  但使**绝对引用指标**（有效性/精确率/忠实度）及后续 guardrail 不可靠。

## 2. 契约 v2（本修复定义并实现）

### 2.1 三层语义（显式区分，不混为一个集合）

| 层 | 指标 | 定义 |
|---|---|---|
| retrieval-level visible | `citation_id_validity`（旧字段保留） | 答案引用 ID ∈ sources 展示（`format_sources` 输出）解析出的 ID 集 |
| context-level supported | `context_supported_citation_validity`（**新，正式 guardrail 口径**） | 引用 ID 解析出的 chunk ∈ 最终 context chunk 集（`supported_chunk`），或该 chunk 的 source ∈ 最终 context source 集（`supported_source`） |
| 最终答案引用有效性 | = context-level supported | guardrail 使用的指标 |

证据链（每个调用点必须传真实值，禁止占位）：
- `sources`：生产引用展示 → `parse_sources_citation_map()` 解析 S#→chunk 权威映射；
- `context_chunk_ids` / `context_source_ids`：评测检索网格记录的**最终 context**
  （`_run_retrieval_arm` 输出，与 source recall 同口径）；
- `candidate_chunk_ids`：候选池（区分"检索可见"与"context 支持"）；
- `chunk_to_source`：`_source_label_from_meta`（source_name 优先）构建，
  与已修复的 source recall 口径一致，**禁止 filename/hash 混用回归**；
- `context_text`：faithfulness 用（compare.py 由 context_chunk_ids 重建
  `_rebuild_context_text`；generation_runner 用 sources 全文）。

### 2.2 确定性处理规则（单条 answer）

- 引用提取 `referenced_citation_ids`（`\bS\d+\b`，set）——**重复引用按唯一 ID
  计一次**，不放大有效性；
- **空引用**：validity=0.0，total/unique=0，无证据；
- **fabricated/未知**：引用 ID 无法从 sources 解析（幻觉或行缺 chunk_id）→
  `fabricated`，无效；
- **候选池但未进 context**：chunk ∈ candidate 记录但不在 context chunk/source
  记录 → `retrieved_not_in_context`，无效（检索可见 ≠ context 支持）；
- **多 source/多引用**：每引用 ID 解析到单一 chunk → 单一 source；同一 ID
  重复出现取首行（确定性）；逐引用按 ID 数字升序判定，`CitationEvidence`
  逐条记录状态（可审计）；
- `citation_precision`/`citation_recall`：分母/分子**只计 context-supported
  引用**（chunk 域），消除 `all_retrieved_ids=set()` 占位导致的 precision 恒 0。

### 2.3 fail-closed

`evaluate_citations_context_aware` 要求
`sources/context_chunk_ids/context_source_ids/candidate_chunk_ids/
chunk_to_source/context_text` **全部显式提供**（任一 `None` → `ValueError`）；
空列表/空字符串是"真实空"（合法，如拒绝路径）。`_run_generation_arm` 在
`retrieval_result` 缺失时抛 `RuntimeError` → 结果以 `error` 标记，**不静默产出
"有效/无效"指标**。

## 3. 修改清单

| 文件 | 修改 |
|---|---|
| `evaluation/citation_metrics.py` | 新增 `CitationEvidence`、`parse_sources_citation_map()`、`evaluate_citations_context_aware()`；`CitationMetrics` 扩展 7 个字段（默认值向后兼容）；模块 docstring 写入契约 v2 |
| `evaluation/compare.py` | `_run_generation_arm` 三臂（A/B/C）统一传真实证据；`retrieval_result` 缺失 fail-closed；新增 `_chunk_to_source_map`/`_rebuild_context_text`/`_citation_status_counts`；`GenerationCaseResult` 新增 4 字段；`compute_summary` 聚合 `context_supported_citation_validity`/`fabricated_citation_avg`/`retrieved_not_in_context_avg` |
| `evaluation/generation_runner.py` | 改用契约 v2 入口；runner 无独立检索网格，以 sources 解析 chunk 为 context 证据（生产 `_build_context` 与 `format_sources` 使用同一 `top_indices[:context_k]`，同源同截断，口径等价） |
| `src/rag.py` | **未修改**（生产路径 `_validate_and_repair_citations` 的 valid_ids 本就基于 context 内 `citation_map`；流式路径不做引用修复——生产行为不变，本任务只修评测） |

未触碰：`RAG_RERANKER` 默认配置、Graph 逻辑、QueryPlan、锁配置、review
overlay、任何已有 results 目录、`decision-report.md`。

## 4. 新旧口径差异与受影响的历史指标

| 指标 | 旧口径（历史结果） | 新口径（本修复后） | 历史数值影响 |
|---|---|---|---|
| `citation_id_validity` | 引用 ID ∈ sources `[S#]` 集（retrieval-visible） | 同左（字段语义保留） | **不变**（`parse_sources_citation_map` 的 ID 集与旧正则等价）；历史值仍可解释 |
| `citation_precision` | `all_retrieved_ids=set()`（compare.py）→ **恒 0.0**；generation_runner 用 sources chunk（retrieval-visible） | context-supported 引用 ∩ relevant / context-supported 引用 | **历史值失效**（占位/口径不同） |
| `citation_recall` | `cited ∩ relevant / relevant`（无 context 过滤） | context-supported 引用 chunk ∩ relevant / relevant（更严） | **历史值失效**（口径变严） |
| `faithfulness` | `context=""` → answer_points 非空时恒 0.0 | 真实 context 文本（重建/sources） | **历史值失效**（占位） |
| `context_supported_citation_validity` 等 4 新字段 | 不存在 | 正式 guardrail 指标 + 状态计数 | 历史结果中无此数据，**不可追溯填充** |

受影响的历史产物：
- `auto-run-20260804T121410/`（dev-full/holdout-full 的 generation-summary.json、
  generation-cases.jsonl、automated-decision-report.md 中引用指标）；
- `reranker-recheck-20260804T185937/`（同上）；
- 旧 P0 baseline（generation_runner 产出）。

**口径说明**：旧 `citation_id_validity` 的组间相对比较（A/B/C 方向对称）
仍可解释，但其**绝对数值**不是"证据进入 prompt"的证明；本修复后的
`context_supported_citation_validity` 才是。两个指标不可互相比对。

## 5. 测试结果

新增 25 个单元测试（TDD：先写失败测试 → 实现 → 通过）：

`tests/test_eval_citation_metrics.py`（+21）：
- `TestParseSourcesCitationMap`（4）：标准行解析、无 chunk_id 行跳过、空输入、
  确定性首现保留；
- `TestEvaluateCitationsContextAware`（15）：context chunk 支持、context source
  支持、**候选池未进 context 无效**、幻觉引用、空引用、重复引用计一次、
  多引用混合确定性（状态顺序）、source-only（recall=0 且 validity 正常）、
  precision 只计 context-supported、**缺任一证据 fail-closed（ValueError ×4）**、
  空 context 真实空合法、chunk 无检索记录视为 fabricated；
- `TestProductionPathConsistency`（2）：生产非流式 `_validate_and_repair_citations`
  的合法 ID 集（context 内 `citation_map`）与 sources 解析 ID 集一致；
  流式/非流式共用 `format_sources` 产物 → 同证据同评估结果。

`tests/test_compare.py`（+4）：
- `TestGenerationArmCitationEvidence`（3）：**A/B/C 三臂调用均传真实证据**
  （sources 映射 + 检索网格 context/candidate + chunk→source + 重建 context 文本，
  断言无占位）；`GenerationCaseResult` 写入新字段与状态计数；
  **retrieval_result 缺失 → fail-closed（error 标记，不产正常指标）**；
- `TestComputeSummaryCitationContextSupported`（1）：summary 聚合
  `context_supported_citation_validity`/`fabricated_citation_avg`。

验证命令（全部通过）：
```
python -m pytest tests/test_eval_citation_metrics.py tests/test_compare.py -q
→ 208 passed
python -m pytest -q
→ 763 passed, 7 skipped（原 738 + 新增 25）
python -m py_compile evaluation/citation_metrics.py evaluation/compare.py \
    evaluation/generation_runner.py tests/test_eval_citation_metrics.py \
    tests/test_compare.py   → PY_COMPILE_OK
git diff --check            → clean（仅 LF/CRLF 提示）
```

## 6. Guardrail 前置条件（重要）

**修复后必须重新跑新的 selector policy ablation，才能用 citation 指标作为
正式 guardrail。** 理由：

1. `context_supported_citation_validity` 是 **selector policy 的函数**——context
   由 `select_context_candidates(top_k, max_per_source=3)` + 相邻扩展决定，
   不同 policy 产生不同 context，同一答案的引用支持性随之不同；
2. 本修复只改变"如何测量"，不改变任何 policy；当前没有任何在新口径下运行的
   评测结果（历史结果无法追溯填充新指标）；
3. 生产默认 `RAG_RERANKER=none`（A）下的 citation 基线尚未在新口径下建立；
   reranker 开启（B）对引用有效性的净影响（context 集中 vs source 覆盖收窄）
   必须在受控 ablation 中重新测量（沿用 reranker-recheck 的受控框架与锁配置）。

建议的 ablation：在 `reranker-recheck` 受控框架（A vs B，同一 QueryPlan/
selector/budgets，locked-config）下重跑 dev full，输出
`context_supported_citation_validity` 基线，再决定 guardrail 阈值。

## 7. 产物与约束

- 代码修改：`evaluation/citation_metrics.py`、`evaluation/compare.py`、
  `evaluation/generation_runner.py`、`tests/test_eval_citation_metrics.py`、
  `tests/test_compare.py`、`CHANGELOG.md`；
- 本报告位于新独立目录 `results/graph-gate/citation-eval-fix-20260804T200234/`；
- 未调用 LLM/API；未重跑真实评测；未改写任何已有 results 目录与
  `decision-report.md`；未 stage/commit。
