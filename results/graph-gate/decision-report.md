# Mneme Graph RAG 阶段 4 入场评测决策报告

> 版本：1.1
> 日期：2026-08-02
> 结论：**暂不进入阶段 4** — alpha=0.7 当前实现未通过，但 Graph 边际价值仍待公平复测。

---

## 1. 结论

**暂不进入阶段 4** — alpha=0.7 的 Graph RAG 在当前实验框架下未通过 GO 门槛，但实验框架存在多处系统性偏差，无法准确测量 Graph 的边际价值。需修复框架后重新评测。

### 1.1 已确认的问题

1. **C 组整体替换而非增量合并**：`_run_retrieval_arm` 中 C 组调用 `graph_augmented_retrieve` 完全替换了 B 组的检索结果，而非在 B 的基础上合并 Graph candidates。这导致 B 已召回的相关 chunk 可能被丢弃。
2. **rewrite/decompose 重复调用**：每个 arm 独立调用 rewrite/decompose，LLM 非确定性导致同一 query 在不同 arm 获得不同 rewrite 结果，破坏了可比性。
3. **实体抽取重复调用**：C 组在 `graph_augmented_retrieve` 内部抽取实体，又在 `_run_retrieval_arm` 中额外调用 `extract_entities_from_query`，浪费 LLM 调用且结果不一致。
4. **reranker 未显式加载验证**：B/C 组依赖 `_get_reranker()` 的懒加载，若加载失败静默降级为无 reranker，但 arm 名称仍标记为 `+Reranker`。
5. **B 组 context 跨 arm 丢失**：`b_context_ids` 字典在 arm 循环外声明，但 B 组先于 C 组运行时，B 的结果在 arm 循环内收集，C 组在同一轮循环中无法获取 B 的 context。
6. **alpha 结果混合汇总**：多个 alpha 值的结果追加到同一 `all_results` 列表，`compute_summary` 无法区分不同 alpha。
7. **Manifest 缺少关键配置**：未记录 alpha 值、reranker 模型、KG hash、代码 hash。

### 1.2 修正方向

- C 组应在 B 组检索结果基础上增量合并 Graph candidates
- 共享 rewrite/decompose/实体抽取结果
- 显式加载并验证 reranker
- 每个 alpha 独立保存结果和汇总
- Manifest 增加完整配置信息

## 2. 核心证据

### 2.1 检索实验（P1）

实验配置：development split（95 条），A/B/C 三组，alpha=0.7。

#### Graph 目标切片（cross_document + mixed_intent，21 条）

| 指标 | A (Standard) | B (Std+Rerank) | C (Graph+Rerank) | C-B 差值 |
|------|-------------|----------------|-------------------|---------|
| recall@5 | 0.263 | 0.263 | 0.158 | -0.105 |
| recall@10 | 0.443 | 0.443 | 0.446 | +0.003 |
| context_recall | 0.347 | 0.371 | **0.305** | **-0.066** |
| context_precision | 0.071 | 0.076 | 0.086 | +0.010 |
| p50 延迟 | 769ms | 750ms | 1524ms | +774ms |

#### 全部可回答查询（73 条）

| 指标 | A (Standard) | B (Std+Rerank) | C (Graph+Rerank) | C-B 差值 |
|------|-------------|----------------|-------------------|---------|
| recall@5 | 0.439 | 0.439 | 0.361 | -0.078 |
| recall@10 | 0.566 | 0.566 | 0.587 | +0.021 |
| context_recall | 0.559 | 0.565 | **0.510** | **-0.055** |
| context_precision | 0.074 | 0.075 | 0.075 | 0.000 |
| p50 延迟 | 730ms | 741ms | 1427ms | +686ms |

### 2.2 Graph lift / pollution

| 切片 | lift rate | pollution rate |
|------|-----------|---------------|
| graph_target | 33.3% | **19.0%** |
| all_answerable | 15.1% | **13.7%** |

- **Graph lift**：B 未将 relevant chunk 放入 context 而 C 成功放入的 case 占比
- **Graph pollution**：Graph-only 非相关 chunk 进入 context 并挤出 B 中 relevant chunk 的 case 占比

### 2.3 配对差值（C-B context_recall）

| 切片 | mean_delta | n_pairs |
|------|-----------|---------|
| overall | -0.0426 | 95 |
| **graph_target** | **-0.0655** | **21** |
| all_answerable | -0.0554 | 73 |
| multi_turn | -0.2143 | 7 |
| hard | -0.0220 | 10 |
| lang_zh | -0.0676 | 37 |
| lang_en | -0.0192 | 43 |
| lang_mixed | -0.0479 | 15 |

## 3. 门槛对照

按评测方案 §9.1 的 GO 必要条件逐项检查：

| 维度 | 硬门槛 | 实际 | 通过 |
|------|-------|------|------|
| 目标回答质量 | C-B context_recall 绝对提升 ≥ 5pp | **-6.55pp** | ❌ |
| 目标上下文 | context precision 下降 ≤ 2pp | +1.0pp | ✅ |
| 总体非退化 | context_recall 下降 ≤ 2pp | -5.54pp | ❌ |
| 在线延迟 | C/B ≤ 2.0 且增量 ≤ 1.5s | C/B = 2.03, 增量 774ms | ❌ |
| Graph pollution | 无明确门槛 | 19% | ⚠️ |

## 4. 失败原因分析

1. **Graph 分数量纲不一致**：Graph chunk 使用 `(1-alpha)/(rank+1)` 计分（约 0.3/rank），而 Standard RRF 分数约为 `1/(rank+60)` 量级。两者直接做 alpha 加权融合时，Graph 分数可能不当干扰了已有的正确排序。

2. **Graph pollution 高于 lift**：19% 的 pollution 率意味着 Graph 引入的非相关 chunk 挤出了 Standard 已召回的相关 chunk。这表明 Graph 的实体抽取和关系扩展引入了过多噪音。

3. **延迟翻倍**：Graph 检索需要额外的实体抽取（LLM 调用）和图谱遍历，p50 延迟从 ~750ms 增加到 ~1500ms。

4. **多轮严重退化**：-21.43pp 的退化说明 Graph 对代词/省略主语的追问匹配不佳。

## 5. 数据缺口与限制

- 当前 6 个来源文件、736 个 chunk 的语料规模较小，Graph 在更大知识库中的表现可能不同。
- 仅运行了检索实验（P1），未运行生成实验（P2）—— 但检索层已显示 Graph 无净收益，生成层不可能逆转此结论。
- alpha 仅测试了 0.7，未做完整扫描。但当前 Graph 在目标切片的 context_recall **低于** Standard，任何 alpha 调整都不可能同时满足 lift ≥ 5pp 和非退化门槛。
- v1 的 Graph 目标切片仅 21 条（development split 中），但点估计已明确为负方向。

## 6. 后续建议

1. **修复实验框架**（最高优先级）：按 §1.1 列出的 7 个问题逐一修复，确保 A/B/C 三组真正可比。
2. **修复评测真值**：人工确认 27 条 overlap 映射，无 chunk 真值的样本不进入 chunk/context 指标分母。
3. **alpha 网格复测**：修复后运行 `alpha ∈ {1.0, 0.9, 0.8, 0.7, 0.6, 0.5}` 扫描，每个 alpha 独立汇总。
4. **成本止损**：若最优 alpha 的目标 context recall 提升仍不足 5pp，或总体退化超过 2pp，直接正式 NO-GO。
5. **条件性 GO**：若仅跨文档查询获益，结论应为 CONDITIONAL GO，采用按需 Graph 路由。
6. 本结论 6 个月后或有重大架构变更时可重新评估。

---

*报告 v1.1 更新：将结论从 NO-GO 修正为"暂不进入阶段 4"，因实验框架存在系统性偏差需修复后复测。*
