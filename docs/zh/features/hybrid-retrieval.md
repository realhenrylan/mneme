# 混合检索

纯向量检索擅长语义相似，但对文件名、缩写、数字、专有名词或精确短语并不总是可靠。纯 BM25 可能错过一个有用的同义改写。Mneme 保留两种检索信号。

## 架构

```
用户问题
  → 查询拆解
  → 并发混合检索 / Graph RAG 扩展
  → chunk 去重和动态 Top-K
  → PDF anchor enrich
  → 带引用的、有边界的不可信文档上下文
  → LLM 回答 + 可验证来源
```

## 组件

### 语义搜索

- **Sentence Transformers** 生成 embedding
- **ChromaDB** 提供余弦相似度语义检索
- 默认模型：`all-MiniLM-L6-v2`（未缓存时从 ModelScope 自动下载）

### 词法搜索

- **BM25** 提供基于关键词的检索
- 自定义 tokenization 支持双语文本、大小写折叠和标点剥离
- 对未变更的 chunk 增量复用 BM25 tokenization

### RRF 融合

RRF（倒数排名融合）融合排序结果，而不是比较不可兼容的原始分数：

```
RRF 分数 = Σ 1 / (k + rank)
```

RRF 简单且可解释。它不要求语义距离和 BM25 分数共享同一量纲。

### 动态 Top-K

融合后，Mneme 从分数 gap 中选取动态 Top-K：
- 明显的 gap 成为天然截断点
- 配置的下界（`LLM_TOP_K_MIN`）和上界（`LLM_TOP_K_MAX`）在 gap 不够明显时仍然生效

## 检索质量

这套设计让检索质量变得可度量。Recall@k、MRR、nDCG 可以作为回归信号，而不是依赖"感觉回答更好了"这种印象。仓库在 `benchmarks/` 下包含 benchmark 数据和 quality-gate 工具。

## 适用场景

Standard RAG（混合检索）最适合一般问答和广泛的文档集。对于跨文档关联问题，请使用 [Graph RAG](/zh/features/graph-rag)。
