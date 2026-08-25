# Reranker 回归诊断报告（只读）

> **只读诊断**：基于 `results/graph-gate/auto-run-20260804T121410/` 的既有产物
> （dev-full / holdout-full / dev-grid / alpha-selection / locked-config /
> auto-annotation-evidence），未重跑评测、未调 alpha、未修改任何代码或历史结果。
> 报告只给出建议与根因证据，不实施修复。
>
> 结论性质：**自动化诊断**，真值未经人工审核。

---

## 0. 问题定义

在锁定 alpha=1.0 的正式诊断中，**A（standard，无 reranker）的 answer_point_coverage
高于 B（standard-rerank）与 C**：

| 集 | A | B | C |
|----|-----|-----|-----|
| dev overall | **0.646** | 0.575 | 0.591 |
| dev graph_target | 0.500 | **0.611** | 0.508 |
| holdout overall | **0.474** | 0.372 | 0.372 |
| dev citation_id_validity | **0.726** | 0.632 | 0.653 |
| dev false_refusal_rate | **0.137** | 0.219 | 0.233 |

本报告回答：为什么 A 优于 B/C？生产默认是否应回退到 A？

---

## 1. 按 case 对齐的胜负分布（dev，95 cases，answer_point_coverage）

### 1.1 总量

| 对比 | A 胜 | B 胜 | 平局 |
|------|------|------|------|
| A vs B | **13** | 7 | 75 |
| holdout A vs B | **2** | 0 | 14 |

> 平局占比极高（79%），主要因 answer_point_coverage 是离散值（0/0.33/0.5/1.0）
> 且多数 case 两者都答对或都答错。差异集中在少数 case，但方向一致偏向 A。

### 1.2 切片分布（A vs B）

| 切片 | A 胜 | B 胜 | 平局 |
|------|------|------|------|
| zh | **5** | 0 | 32 |
| en | 6 | 4 | 33 |
| mixed | 2 | 3 | 10 |
| multi_turn | **3** | 0 | 4 |
| metadata | **2** | 0 | 12 |
| single_fact | 5 | 2 | 24 |
| cross_document | 1 | 2 | 8 |
| mixed_intent | 1 | 3 | 6 |
| graph_target | 2 | 5 | 14 |
| source_only | **2** | 0 | 8 |
| refusal | 1 | 0 | 21 |

> **中文（zh）与多轮（multi_turn）是 A 的绝对优势区**（zh 5-0、multi_turn 3-0）。
> graph_target 中 B 反而略优（5-2），与 generation summary 中 B 的
> graph_target answer_pt_cov（0.611）高于 A（0.500）一致——说明 reranker 在
> 跨文档/混合意图场景有一定正面作用，但被 overall 中的中文/多轮/元数据场景
> 的损失抵消。

---

## 2. 关键机制证据（为什么 B 输）

### 2.1 【已证实】CrossEncoder 只按 source_name（文件名）评分，不读 chunk 文本

`src/retrieval.py:72` 的 `rerank()`：

```python
pairs = [(query, c.source_name) for c in candidates]   # ← 只传文件名！
```

**直接验证**（加载真实模型对 2 个源 × 2 个不同 chunk）：

```
a_chunk_0  src=OneDrive 入门.pdf   rerank_score=1.5394
a_chunk_1  src=OneDrive 入门.pdf   rerank_score=1.5394   ← 同一源内分数完全相同
b_chunk_0  src=南京城市地理环境.docx  rerank_score=-5.8838
b_chunk_1  src=南京城市地理环境.docx  rerank_score=-5.8838
```

**同一 source 的所有 chunk 获得完全相同的 rerank_score**。原因：`RetrievalCandidate`
没有 text/snippet 字段（`src/domain.py:131-168`），reranker 只能用文件名配对。
这导致：
- rerank 只重排**源之间的顺序**，源内 chunk 顺序完全保持 RRF 原序；
- ms-marco（英文模型）对中文文件名与 query 的匹配不可靠，可把错误源整组排前；
- 但当 query 含明确文件名 token 时（如 "OneDrive"），排序正确（实测 zh-002 南京
  排第一）——**因此问题不仅是"排错源"，更主要是 diversity 截断**（见 2.2）。

### 2.2 【已证实】source diversity（max_per_source=3）+ top-20 截断把相关 chunk 挤出 context

`apply_source_diversity(reranked, max_per_source=3, top_k=min(k, 20))`
（`src/retrieval.py:106-136`，按 `source_id` 去重）只保留每源前 3 个 chunk。
由于 rerank 分数同源相同、源内顺序=RRF 原序，**每源只有前 3 个 chunk 能进入
后续 context 构建**（+邻接扩展最多 2 个 → 每源约 5 个）。

**dev 全量量化（63 个 chunk-truth case）**：

| 指标 | A（无 diversity） | B（rerank + diversity） |
|------|-------------------|------------------------|
| context 中保留相关 chunk 的 case | **47（75%）** | **38（60%）** |
| A 保留但 B 挤出（A_only） | **12** | — |
| B 保留但 A 挤出（B_only） | — | **3** |
| context chunk 数（avg / 分布） | 10.00（全 10） | 9.55（3~10，不均匀） |

> 12 vs 3：B 挤出相关 chunk 的概率是 A 的 **4 倍**。

**单 case 实证（zh-002 "南京的海拔最高点是什么山？"）**：
- A（RRF 序）：相关 `chunk_2` 在候选 pos=3 → 进入 context → **A=1.0**
- B：rerank 后（同源分数相同，序不变）→ diversity 只保留南京源前 3 个 chunk
  （pos 0-2），相关 `chunk_2`（pos 3）被截断 → B context 无相关 chunk → **B=0.0**

**11 个"相关 chunk 在 B 的 top-20 内但被挤出 context"的 case**（diversity 截断，
非 top-k 截断）：zh-011、en-015、en-006、zh-014、zh-016、zh-002、mixed-007、
mixed-013、multi-006、multi-008、multi-009（相关 chunk 位置 2~11，全部 ≤20）。

### 2.3 【已证实】A 与 B/C 的 context 构建不对称（评测口径偏差）

| 步骤 | A | B/C |
|------|---|---|
| 候选 | `merged[:k]`（dynamic k，可达 70） | 同，但 **rerank top_k=min(k,20)** |
| source diversity | **不应用** | 应用（max 3/源） |
| 邻接/父块扩展 | 应用 | 应用 |
| context_k | min(#chunks, 10) | 同 |

B/C 的 context 输入被压缩到 ≤20 且每源 ≤3+2；A 直达 10。**这不是"reranker
不好"，而是 reranker 生效路径（截断+diversity）在 6 文档小语料中系统性丢失
同源内靠后的相关 chunk**——而这些 chunk 恰恰是单源事实类 query 的答案所在。

### 2.4 【已证实】B 的引用更少、拒答更多

| 指标 | A | B |
|------|---|---|
| 答案平均引用数 | 2.14 | 1.79 |
| 无引用答案数 | 26/95 | **35/95** |
| false_refusal | 18/95 | **24/95** |
| 错误 | 0 | 1 |

且 `citation_id_validity=0` 的 B case 平均 answer_point_coverage=0.543，
`=1.00` 时 0.733——**引用质量与答案质量强相关**。B 的 context 相关 chunk
缺失 → LLM 无据可引 → 引用少/错误 → 答案要点覆盖率低。

### 2.5 【已证实】citation repair 是"数字最近邻"替换，非语义修复

`_repair_citations`（`src/rag.py:1608-1636`）把无效 `[Sx]` 替换为数字最接近的
有效 ID，**不做语义对应**；单次尝试，失败标 `unverified`。当 context 丢失相关
chunk 时，repair 只能把引用映射到错误的相邻 chunk → `citation_id_validity`
下降（B 0.632 vs A 0.726）。

---

## 3. 评测口径/实现偏差核对表

| 检查项 | 结论 |
|--------|------|
| 共享 QueryPlan（rewrite/decompose/实体） | ✅ 同一 case 的 A/B/C 共用同一 QueryPlan（`build_query_plan_cache` 按 case_id 缓存），无偏差 |
| 候选集一致性（rerank 前） | ✅ A/B/C 的 RRF 候选集相同（`merged` 相同）；C 在 alpha<1 时才加 Graph-only |
| reranker 分数方向 | ✅ 越高越好（predict logits 降序）——方向正确 |
| reranker 输入 | ❌ **只用 source_name，不用 chunk 文本**（2.1） |
| top-k 截断 | ❌ B/C 截到 min(k,20)，A 用 dynamic k（可达 70）——不对称（2.3） |
| source diversity | ❌ **只对 B/C 应用**（max 3/源），A 不应用——不对称（2.3） |
| 邻接/父块扩展 | ✅ 三臂一致 |
| context budget | ✅ context_k=min(#chunks,10) 一致（B 因 diversity 常 <10） |
| citation repair | ⚠️ 数字最近邻替换，非语义；A/B/C 均走同一 repair 路径（`answer_query`/`_graph_enhanced_answer_query`），无臂间偏差，但 B 因 context 缺失更易触发无效引用（2.5） |
| citation_precision / faithfulness 指标 | ⚠️ 已知口径缺陷：`evaluate_citations` 传 `all_retrieved_ids=set()` 与 `context=""`（compare.py:1449,1451），导致 citation_precision 恒 0、faithfulness≈0——**三臂同缺陷，不影响 A/B 对比方向** |

---

## 4. 根因排序（证据优先）

| # | 根因 | 类型 | 置信度 | 证据 |
|---|------|------|--------|------|
| 1 | **reranker 按 source_name 评分，不读 chunk 文本** | 实现缺陷 | **已证实**（实测同源 chunk 分数完全相同） | §2.1 |
| 2 | **source diversity（max 3/源）+ top-20 截断把同源内靠后相关 chunk 挤出** | 实现缺陷（diversity 参数+应用不对称） | **已证实**（11 个 case 相关 chunk 在 top-20 内仍被挤出；12 vs 3 保留差） | §2.2 |
| 3 | **A/B context 构建不对称**（A 无 diversity/无截断） | 评测口径偏差 | **已证实**（表 2.3） | §2.3 |
| 4 | **B 引用更少/无效引用更多 → 答案质量低** | 2 的传导 | **已证实**（无引用 35 vs 26；citv 与 apc 相关） | §2.4 |
| 5 | citation repair 非语义 | 次要（三臂同路径） | 部分证实 | §2.5 |
| 6 | ms-marco 对中文文件名匹配弱 | 模型适配 | **待验证**（zh 5-0 全胜；需在修复后单独复测） | §1.2 |
| 7 | rerank_ms 开销（B avg 154ms/case，C 45ms） | 性能 | 已证实（非根因） | 运行日志 |

---

## 5. 最小修复方案（建议，不实施）

按影响/成本排序：

### 修复 1（根因 1，最高优先）：reranker 输入改为 chunk 文本
- `RetrievalCandidate` 增加 `text` 字段（构建处从 `all_docs[idx]` 填充）；
- `CrossEncoderReranker.rerank` 配对改为 `(query, c.text)`；
- 预期影响：rerank 真正按 chunk 语义评分，同源 chunk 可区分，diversity
  截断不再系统性丢弃相关 chunk；
- 回归测试：`test_reranker_uses_chunk_text_not_source_name`（构造同源不同
  内容的 2 个 chunk，断言 rerank 后分数不同、内容相关的排前）。

### 修复 2（根因 2/3）：diversity 与截断对 A/B/C 对称化
- 方案 a：A 也应用 source diversity（max_per_source=3）——口径统一，但会
  拉低 A（当前 A 未受限）；方案 b：B/C 移除 diversity 或放宽
  `max_per_source`（如 6）——保留 reranker 收益同时减少同源截断；
- 预期影响：消除臂间不对称，B 的 context 恢复 10 chunk；
- 回归测试：`test_source_diversity_does_not_drop_relevant_chunk_beyond_limit`
  （构造 4 个同源 chunk，相关 chunk 排第 4，断言 diversity 后仍保留或记录
  丢弃率）。

### 修复 3（根因 4，低成本）：diversity 前先按相关信号保底
- 或：`apply_source_diversity` 增加"每源 N=3 外的 chunk 若 rerank_score 高于
  阈值仍保留"的软限制；
- 或：context 构建允许每源 >3（对单源事实 query 更重要）。

### 修复 4（口径，辅助）：补 `evaluate_citations` 的
`all_retrieved_ids` 与 `context`
- 把真实候选 ids 与 context 传入（compare.py:1449,1451），使
  citation_precision/faithfulness 可解释（三臂同修，不影响 A/B 对比结论）。

---

## 6. 已证实 vs 待验证

### 已证实
- reranker 只用 source_name（实测同源分数相同）
- diversity+top-20 截断挤出相关 chunk（11 个 top-20 内仍被挤出的 case）
- A/B context 不对称（diversity 仅 B/C）
- B 引用更少、拒答更多、citv 与 apc 相关
- 12 vs 3 的 context 保留差（A_only vs B_only）
- 引用 repair 为数字最近邻（代码级）

### 待验证（需修复后复测）
- ms-marco 对中文/多轮场景的系统性劣势（zh 5-0、multi_turn 3-0，但样本小）
- reranker 若改用 chunk 文本后，graph_target 中 B 相对 A 的优势（0.611 vs
  0.500）是否保留/扩大（跨文档场景 reranker 可能真有价值）
- diversity 参数（3 vs 6 vs none）对整体指标的最优点
- 修复后 dev/holdout 的统计显著性与 McNemar 结论是否变化

---

## 7. 结论与建议

### 7.1 生产默认是否应回退到 A？
**建议：是，暂时回退。**
- 证据：dev A=0.646 > B=0.575，holdout A=0.474 > B=0.372；B 无任何切片
  系统性胜出（仅 graph_target 5-2）；B 的 false_refusal 更高（24 vs 18）；
  reranker 当前实现（按文件名评分）无理论收益，且引入 4 倍的相关 chunk
  挤出概率（12 vs 3）。
- 例外：graph_target 中 B 的 answer_pt_cov 更高（dev 0.611 vs 0.500）——但
  alpha 扫描已锁定 1.0（C 不经过 Graph），且该差异在修复 reranker 输入前
  不可归因于"reranker 有效"（可能只是多样性恰好保留了跨文档所需的多源）。
- **注意**：这是"回退到 A 的 reranker 路径"（`RAG_RERANKER=none` 已是默认），
  即**生产现状即为 A**；本建议等价于"保持现状，不启用 cross-encoder 默认"。

### 7.2 是否值得单独开启下一轮 reranker 修复任务？
**建议：值得，但作为独立、低优先任务。**
- 理由：根因 1（reranker 不读 chunk 文本）是明确实现缺陷，修复成本低
  （RetrievalCandidate 加 text 字段 + 配对改 text），且有清晰回归测试可写；
  修复后 reranker 才真正"有用"，届时才能判断其价值（特别是 graph_target
  的跨文档场景）。
- 不理由：当前数据不足以证明"修复后 B 会胜 A"（zh/multi_turn 的 5-0/3-0
  可能源自模型对中文的适配而非输入缺陷）；需修复后重跑才能定论。
- 建议顺序：先做修复 1 + 修复 2b（对称化），小样本（10-20 case）快速验证
  zh/multi_turn 是否改善，再决定是否全量重跑。

### 7.3 最小行动清单
1. （建议）生产默认维持 `RAG_RERANKER=none`（即 A），不回切 cross-encoder。
2. （建议）开启修复任务：reranker 输入改 chunk 文本 + diversity 对称化 +
   回归测试；修复后重跑 dev/holdout 对比。
3. （建议）修复 `evaluate_citations` 的口径（all_retrieved_ids/context），
   使 citation_precision/faithfulness 可解释。
4. （不实施）本报告不修改任何代码/结果；所有证据可复现于
   `scripts/reranker_diagnosis_analysis.py`。

---

*生成时间：2026-08-04。仅基于 auto-run-20260804T121410/ 既有产物与代码阅读，
未重跑评测、未修改文件。*
