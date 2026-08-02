# Mneme Graph RAG 阶段 4 入场评测决策报告

> 版本：1.0  
> 日期：2026-08-02  
> 结论：**NO-GO**

---

## 1. 结论

**NO-GO** — Graph RAG 在当前实现下对目标查询没有净收益，不应进入阶段 4。

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

1. **保留 Standard RAG** 作为生产默认，不进入阶段 4 产品化。
2. **Graph 分数标定**：若未来重新评估，需先将 Graph 分数与 RRF 转换为同量纲（评测方案 §4.4 价值验证轨），再做 alpha 扫描。
3. **Graph pollution 根因**：分析 19% pollution case 中 Graph 引入了哪些无关实体和 chunk，确定是实体抽取精度问题还是图遍历深度问题。
4. **扩大评测集**：当前 6 文件语料可能不足以产生高连接密度图谱，可考虑在更大语料上重新评估。
5. 本结论 6 个月后或有重大架构变更时可重新评估。

---

*报告自动生成于 P1 检索实验结果。生成实验（P2）和 holdout 验证因检索层已明确 NO-GO 而跳过。*
