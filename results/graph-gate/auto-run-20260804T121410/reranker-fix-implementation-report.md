# Reranker 正确性与公平对比修复 — 实施报告

> 基于 `reranker-regression-diagnosis.md` 的最小、可回归验证修复。
> **未重跑真实评测**；本报告不宣称任何效果提升，仅记录修改点、兼容性与
> 验证结果。Graph 产品化未被改动或重新开启；历史结果
> `results/graph-gate/decision-report.md` 未修改；未 stage/commit。

---

## 1. 修改点

### 1.1 `src/domain.py` — RetrievalCandidate 携带 chunk 文本
- `RetrievalCandidate` 新增字段 `text: str = ""`（默认空串）。
- 向后兼容：所有既有构造点（未传 `text`）不受影响；frozen dataclass 的
  `with_scores()`/`replace` 语义不变。

### 1.2 `src/retrieval.py` — chunk-aware reranking + 统一 context selector
- **`CrossEncoderReranker.rerank`**：
  - 配对改为 `(query, (c.text or "").strip() or c.source_name)`——
    **优先用 chunk 文本打分，禁止把 source_name 当正文**；空文本 fallback
    source_name（不崩溃，兼容无文本候选）。
  - 排序键改为 `(rerank_score or 0.0, c.index)` 降序——**并列分数按 index
    稳定 tie-break**，相同输入永远产生相同顺序（确定性）。
  - 分数方向不变（越高越好），`top_k` 截断行为不变。
- **新增 `select_context_candidates(candidates, top_k=10, max_per_source=3)`**：
  统一的「已排序候选 → context」选择器 = `apply_source_diversity`（每源最多
  `max_per_source` 个）+ top_k 截断，保序、确定性。作为 A/B/C 三臂共用的
  context selector 入口。

### 1.3 `evaluation/compare.py` — A/B/C context 构建对称化
- `_run_retrieval_arm`（评测检索路径）：
  - **A 臂（standard）现在也调用 `select_context_candidates`**——消除诊断
    发现的「A 无 diversity、B/C 独有 top-20 截断」不对称；三臂只有候选
    排序来源不同（A=RRF 序；B/C=reranker 后）。
  - B/C 臂：rerank 后走同一 `select_context_candidates`（替代原
    `apply_source_diversity` 调用）。
  - 候选构造携带 `text=all_docs[i]`（供 reranker 按内容打分）。
- `_graph_enhanced_answer_query`（C 组生成路径）：同步 chunk-aware + 统一
  selector（含无 reranker 分支，行为与 A 一致）。
- **未改动**：QueryPlan 共享、Graph 增量合并（`merge_graph_candidates`）、
  locked-config / review overlay 逻辑。

### 1.4 `src/rag.py` — 生产路径同步（评测/生产行为一致）
- `answer_query`（非流式）与流式路径：reranker 启用时按 chunk 文本打分；
  无论是否启用 reranker 都走统一 `select_context_candidates`；候选携带
  `text`。`RAG_RERANKER=none`（reranker=None）时走 selector 的
  `else` 分支，行为确定。

---

## 2. 兼容性

| 项目 | 状态 |
|------|------|
| CLI 参数 | 未改动任何 flag/默认值 |
| `RAG_RERANKER=none` | 行为兼容：reranker 关闭时走统一 selector 的 else 分支，候选排序仍为 RRF 序 |
| `RetrievalCandidate` 既有构造点 | 全部兼容（`text` 默认空串） |
| `apply_source_diversity` | 保留原函数（`select_context_candidates` 包装它），未删除 |
| `Reranker` Protocol | 签名不变（`rerank(query, candidates, top_k)`） |
| source diversity 默认 | `max_per_source=3` 保留，默认值/关闭方式通过 `select_context_candidates` 参数显式可测 |
| 邻接/父块扩展 | 未改（`expand_with_parent`/`expand_with_adjacent` 保持原行为；预算由 `compute_context_k` 兜底，不突破） |
| locked-config / review overlay / Graph | 未触碰 |

---

## 3. 新增单元测试（15 个）

`tests/test_retrieval.py`（8 个，类 `TestSelectContextCandidates` + `TestCrossEncoderChunkAware`）：
1. `test_same_source_different_texts_get_different_scores` — 同源不同文本的
   两个 chunk 传给模型的 pair 不同、可得到不同分数/顺序
2. `test_does_not_use_source_name_as_document` — pair 的 doc 侧必须是 text，
   不得是 source_name
3. `test_empty_text_falls_back_to_source_name` — 空/空白文本不崩溃，fallback
4. `test_tie_break_by_index_deterministic` — 并列分数按 index 降序，两次调用同序
5. `test_empty_candidates` — 空候选返回空
6. `test_same_as_diversity_behavior` — selector 与 diversity 行为一致（保序/每源上限）
7. `test_top_k_truncation` — 总长不超过 top_k
8. `test_zh002_scenario_fourth_same_source_chunk_kept_when_limit_raised` —
   **zh-002 类回归场景**：同源第 4 个相关 chunk 在 `max_per_source=3` 被挤出、
   放宽到 4 时保留（行为确定可解释）
9. `test_deterministic_order` — selector 相同输入同序

`tests/test_compare.py`（7 个，`TestContextSelectorSymmetry` + 更新 `TestRerankerInjection`）：
10. `test_a_arm_also_applies_select_context_candidates` — **A 臂必须调用统一
    selector**（对称化回归）
11. `test_a_passes_chunk_text_to_candidates` — A 臂候选携带 chunk 文本
12. `test_bc_share_same_instance_and_call_rerank`（更新 patch 目标）—
    B/C 共用注入 reranker、`_get_reranker` 零调用

> 其余 `TestSelectContextCandidates`/`TestCrossEncoderChunkAware` 计数按上表。

---

## 4. 验证结果

| 验证项 | 结果 |
|--------|------|
| 定向测试（reranker/selector/symmetry） | 15 passed |
| **完整测试套件 `pytest tests/`** | **738 passed, 7 skipped**（0 failures） |
| `py_compile`（src/retrieval.py, domain.py, rag.py, evaluation/compare.py, 测试） | COMPILE_OK |
| `git diff --check` | 干净（无 whitespace error / conflict marker） |
| 未调用 LLM/API | ✅（全部为 mock/纯函数测试） |
| 未重跑真实评测 | ✅ |
| 未修改历史结果 / decision-report.md | ✅ |
| 未 stage / commit | ✅ |

---

## 5. 与诊断报告根因的对应

| 诊断根因 | 修复 |
|----------|------|
| 根因 1：reranker 按 source_name 打分 | `RetrievalCandidate.text` + `(query, chunk_text)` 配对（1.1/1.2） |
| 根因 2/3：B/C 独有 top-20 截断 + diversity，A 无 diversity | `select_context_candidates` 统一 selector，A 臂同规则（1.3/1.4） |
| 根因 4：B 引用更少/无效引用（传导） | 通过 1/2 间接缓解（相关 chunk 不再被系统性挤出） |
| 次要：citation repair 非语义 | **未修**（超出本任务范围，三臂同路径，不影响对称性） |
| 待验证：ms-marco 对中文/多轮适配 | **未验证**（需重跑真实评测） |

---

## 6. 尚未重跑真实评测 — 不可宣称效果提升

- 本修复**未重跑 dev/holdout 评测**（用户要求 + 成本约束）。
- 因此：**不能宣称修复后 B/C 会胜 A**；"A 胜 B" 的历史诊断结论是基于
  修复前的 bug 实现，修复后需重新评测才能给出新结论。
- 预期（待验证假设，非结论）：
  - zh-002 类「同源第 4 个相关 chunk」case 在 B/C 的 context 保留率提升
    （A_only 12 个 case 中多数源于此机制）；
  - A 的 answer_point_coverage 可能因 diversity 应用而略降（A 不再无限制
    保留同源 chunk）——**这是对称化的代价**，需评测确认净效果。

---

## 7. 已知限制与下一步

- **阻塞点（如需完全对称）**：A 臂应用 diversity 会改变 A 的历史行为
  （历史 dev 结果 A=0.646 基于无 diversity 的 A）；这是任务目标的明确要求
  （三臂同规则），但意味着历史结果不可直接对比。若产品侧希望 A 保留
  无 diversity 行为，需将 selector 的 `max_per_source` 设为三臂一致的新
  默认（如 None=不限）——本实现保留了该参数可配置，未做此选择。
- 下一步（独立任务）：重跑 dev/holdout 评测验证净效果；若需产品级结论，
  再评估 diversity 默认值调优。

---

*本报告由实施会话生成；所有产物只读验证，未触碰评测结果与决策报告。*
