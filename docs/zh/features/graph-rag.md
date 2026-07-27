# Graph RAG

当问题跨越文档、人物、组织或概念时，单纯增大 Top-K 通常是在加噪音。Mneme 的 Graph RAG 流程使用实体关系来选择性地扩展检索。

## 流程阶段

1. **实体提取**：让 LLM 批量从 chunk 中提取实体
2. **Chunk 映射**：保留实体到 chunk 的映射
3. **共现统计**：统计实体跨 chunk 的共现次数
4. **边过滤**：用以下条件过滤偶然关系：
   - `min_cooccur` 阈值（默认：2）— 两个实体至少在 N 个 chunk 中共现才建边
   - `max_entities_per_chunk` 上限（默认：20）— 每 chunk 仅前 N 个实体参与建边
5. **查询扩展**：提取查询实体，在图中扩展一跳
6. **Alpha 融合**：用 `alpha` 权重将图候选与标准混合检索结果融合

## 为什么约束条件重要

早期对每个 chunk 的实体集合建立完全子图，产生了大量弱共现噪音。图看起来很丰富，但检索效果很差。

Mneme 现在：
- 保留完整的实体-to-chunk 映射
- 使用共现阈值进行边构建
- 限制每 chunk 实体数以防止组合爆炸

"实体出现在哪里？"和"哪些实体值得建边？"是两个独立的决策。

## 回退机制

如果图为空，Graph RAG 会退化到标准语义/混合检索，而不是让空图阻塞整个流程。

## 客户端刷新

实体提取跟随当前的模型和端点配置。当长生命周期的 TUI 会话中 API key 或 Base URL 改变时，Graph RAG client 会随配置指纹刷新。

## CLI 用法

```bash
# 交互式 Graph RAG 会话
python -m src.graph_rag --files /path/to/docs --collection my_docs --alpha 0.7

# 单次查询
python -m src.graph_rag \
  --files /path/to/docs \
  --query "主要发现是什么？"
```

## 参数

| 参数 | 默认值 | 说明 |
|-----------|---------|-------------|
| `--alpha` | `0.7` | 标准检索和图扩展之间的融合权重 |
| `--rebuild` | `False` | 强制重建 collection 和图 |

## 适用场景

Graph RAG 最适合跨文档关联问题——涉及多个文件的查询、实体之间的关系，或需要理解概念如何跨知识库连接的场景。
