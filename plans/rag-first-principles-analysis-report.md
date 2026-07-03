# RAG 检索失效第一性原理分析报告

> 日期：2026-07-02
> 项目：skill-compose
> 范围：`app/rag/` 全部模块（索引、查询、embedding、Qdrant）
> 诊断测试：`tests/test_rag/diagnostic_test_rag_gaps.py`（31 tests, 0 failures, 未修改任何现有代码）

---

## 1. 问题复现

通过多组对照实验确认，这是一个**系统性的架构缺陷**：

| 查询类型 | 示例 | 结果 |
|----------|------|------|
| 纯主题查询 | "traffic forecasting using deep learning" | ✓ 正常 |
| 纯中文元数据 | "这篇文章的作者都属于什么学校" | ✓ 正常 |
| **中英混合 + 元数据** | "LLMs for mobility的作者是谁" | **✗ 失败** |
| **中英混合 + 原题** | "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？" | **✗ 失败** |
| **英文 + 论文名** | "authors affiliations of LLMs for mobility survey paper" | **✗ 失败** |

**规律：只要查询同时包含"论文标识"和"元数据意图"，检索就会失败。**

---

## 2. 根本原因：单一 embedding 无法表达复合意图

### 2.1 数学本质

RAG 做的是语义匹配——将 query embedding 与 chunk embedding 做最近邻搜索。这依赖一个根本假设：

> **假设：一个 query embedding 能完整表达用户的检索意图。**

该假设在简单查询下成立，但在复合意图查询下崩溃。

以 "LLMs for mobility 这篇文章的作者都属于什么学校" 为例，用户实际包含两层意图：

1. **定位文档**：找到 "LLMs for mobility" 这篇论文
2. **提取元数据**：从该文档中找到作者和机构信息

Gemini embedding-2 将整个 query 压缩为一个固定维度向量。该向量是两层意图的**加权平均**，而 "LLMs for mobility" 作为高信息量短语（专有名词），**主导了 embedding 的语义方向**：

- 语义重心 → "讨论 LLMs for mobility 的内容"（匹配正文 chunks）
- 被淹没的意图 → "作者、学校"（作者 chunks 排名 20+）

**这不是调参能解决的问题，是单向量检索的数学本质决定的。**

### 2.2 项目的现有应对：LLM Query Rewrite + RRF

项目在检索端做了多层融合：

```
用户查询 → LLM 改写(3-5 variants) → 每个 variant 独立 embed → 独立向量搜索
                                                       ↓          ↓
                                               独立 FTS 搜索 ──→ RRF 融合
                                                                  ↓
                                                          literal match boost
                                                                  ↓
                                                          document merge
```

**代码位置**：`app/rag/services/rag_query_service.py` 的 `search_chunks()` / `search_chunks_sync()`

**查询改写 prompt**（`rag_query_service.py:37-45`）：

```python
_QUERY_REWRITE_SYSTEM = """You are a search query optimizer. Given a user question,
generate 3-5 alternative search queries that capture the same intent but use
different wording, perspectives, or granularity. ...
- Vary vocabulary: use synonyms, rephrase, or decompose the question"""
```

**RRF 融合**（`rag_query_service.py:395-422`）：`score = Σ(1/(60+rank+1))`，来自所有 query variant 的向量 + FTS 结果列表。

**Literal match boost**（`rag_query_service.py:269-292`）：`_prioritize_literal_passage_matches()` 提升包含精确查询文本的 chunks。

**Document-level merge**（`rag_query_service.py:567-614`）：`_merge_chunks_by_document_sync/async()` 将同一文档的相邻 chunks 合并为连续段落。

### 2.3 为什么这些措施治标不治本

| 措施 | 做的 | 为什么不够 |
|------|------|-----------|
| Query Rewrite | 生成 3-5 个同义改写 | 改写是**词法层面**的，每个改写仍是复合意图的加权平均。不会生成"LLMs for mobility" + "authors affiliations"两个独立子查询 |
| RRF 融合 | 多路结果取交集/并集 | RRF 能"救"已在某路结果中的 chunk，但若作者 chunk **不在任何结果列表中**（因为 embedding 被正文语义主导），RRF 无数据可融合 |
| Literal boost | 精确文本匹配优先 | 依赖查询文本出现在 chunk 中——但作者 chunk 的语义与正文不同，可能根本不在 top-k 召回中 |
| Document merge | 合并相邻 chunks | 若作者 chunks 未被召回，merge 无法凭空补全 |

**核心矛盾**：系统在**检索端**做了复杂的多层融合，但在**索引端**把 PDF 当扁平文本流处理——信息源头就已经损失了结构。

---

## 3. 加剧因素 1：PDF 文本提取质量（信息源头污染）

### 3.1 现有实现

**文件**：`app/rag/services/rag_parsing_service.py:164-183`

```python
def _parse_pdf(file_path: Path) -> list[dict[str, Any]]:
    with fitz.open(str(file_path)) as doc:
        for page_num, page in enumerate(doc, start=1):
            page_text = page.get_text()
            if page_text.strip():
                segments.append({
                    "text": page_text,
                    "metadata": {"source": file_path.name, "page": page_num},
                })
    return segments
```

**完全没有后处理**：无空格修复、无两栏布局重排、无 PDF 元数据（作者/标题）提取。

### 3.2 对 FTS 的影响

Qdrant FTS 索引配置（`app/services/qdrant_service.py:185-194`）：

```python
field_schema=models.TextIndexParams(
    type=models.TextIndexType.TEXT,
    tokenizer=models.TokenizerType.MULTILINGUAL,
    min_token_len=2,
    max_token_len=20,         # ← 关键限制
)
```

`max_token_len=20` 意味着 "UniversityofPennsylvania"（25 字符）被直接跳过或截断。**搜索 "University" 或 "Pennsylvania" 将无法匹配此 token。**

诊断测试 `test_simulated_pdf_artifact_fts_failure` 模拟了这种场景：

```
提取文本：LLMsforMobility, JohnDoe, UniversityofPennsylvania, MIT
可索引 tokens (<20 chars)：[LLMsforMobility, JohnDoe, MIT]
无法索引 tokens (>20 chars)：[UniversityofPennsylvania]
搜索词匹配：University ✗, Pennsylvania ✗, John ✗, Doe ✗, LLMs ✗, Mobility ✗
```

**结论：FTS keyword search 这一道防线在 PDF 提取质量面前完全失效。**

### 3.3 现有应对总结

- **PDF 端**：无任何质量处理
- **FTS 端**：`max_token_len=20` 是 Qdrant MULTILINGUAL tokenizer 的硬约束
- **效果**：该问题在索引端 / 检索端均未得到处理

---

## 4. 加剧因素 2：切片策略不感知文档结构（信息碎片化）

### 4.1 现有实现

**文件**：`app/rag/services/rag_parsing_service.py:478-527`

```python
def chunk_text(text_content, metadata=None, chunk_size=7168, chunk_overlap=896):
    paragraphs = text_content.split("\n\n")
    for para in paragraphs:
        # 贪心拼接至 chunk_size
        # 超出则按句子边界切分
        # 仍超出则硬切
    return chunks  # metadata 只有 {source, page, chunk_index}
```

**完全盲切**：不区分标题/作者/摘要/正文/参考文献。

### 4.2 后果

| chunk 类型 | 特点 | 问题 |
|-----------|------|------|
| **标题 chunk** | "LLMs for Mobility: A Comprehensive Survey" | 被正文淹没，无法作为文档级锚点 |
| **作者 chunk** | "John Doe, University of Pennsylvania" | 被切成 2-3 个碎片，每个 200-300 字符，语义稀薄 |
| **摘要 chunk** | "This survey covers 200+ papers..." | 无法与正文区分，无优先权重 |
| **正文 chunk** | 大段连贯技术内容 | token 数量远超元数据 chunk，在索引中占主导 |

诊断测试 `test_author_info_is_fragmented_across_chunks` 确认：15 位作者的信息在 `chunk_size=500` 时被切成 2 个碎片，每个都不完整。

诊断测试 `test_body_chunks_have_higher_semantic_density_than_author_chunks` 确认：正文 chunk 的 token 数是作者 chunk 的 3.6 倍，在向量索引中的"存在感"大幅领先。

### 4.3 现有应对总结

- **索引端**：无结构标签、无 chunk 权重、无 section type 区分
- **检索端**：`_prioritize_literal_passage_matches()` 只考虑文本匹配，无结构感知
- **Qdrant 层**：只有单一 `rag_assets` 集合，无独立元数据集合
- **效果**：元数据在切片时碎片化 → 碎片化元数据在 embedding 空间中语义稀薄 → 复合查询的元数据意图被主题语义淹没

---

## 5. 系统级缺失汇总

| 缺失项 | 代码位置 | 影响 |
|--------|---------|------|
| **无文档结构层级** | `chunk_text()` | 标题/作者/摘要/正文/参考文献无区分 |
| **无结构化元数据提取** | `_parse_pdf()` | PDF 标题/作者/机构/DOI 不提取 |
| **无独立元数据索引** | `qdrant_service.py:ensure_collections()` | 只有 `rag_assets` 一个集合 |
| **无实体识别（NER）** | `search_chunks()` | 查询不解析文档名/作者名 |
| **无语义意图分解** | `_QUERY_REWRITE_SYSTEM` | 改写是词法级的，非意图级的 |
| **无 chunk 权重机制** | `_build_qdrant_text_assets()` | 所有 chunk 等权重 |
| **PDF 提取无质量后处理** | `_parse_pdf()` | 空格缺失/两栏混乱无修复 |
| **FTS 无长 token 处理** | `ensure_collections()` | `max_token_len=20` |
| **Literal match 的 CJK 限制** | `_build_literal_match_fragments()` | CJK min_length=16，短元数据 token 不构成独立 fragment |

---

## 6. 完整失败链路（以 "LLMs for mobility 的作者是谁" 为例）

```
1. 用户输入："LLMs for mobility的作者是谁"
2. Query embed → Gemini embedding-2 产生单一向量
   - "LLMs for mobility" 作为专有名词主导了语义方向（→ 正文内容匹配）
   - "的作者是谁" 作为功能连接词，语义权重被淹没
3. LLM Query Rewrite → 生成 3-5 个同义改写
   - 例如："LLMs for mobility authors", "who wrote LLMs for mobility survey", ...
   - 每个改写仍是复合意图的加权平均，未分离"定位文档"与"提取元数据"
4. 每个 variant 独立向量搜索
   - 返回结果：正文 chunks（讨论 LLMs/交通预测/深度学习方法）排名 1-10
   - 作者 chunks 排名 20+ 或根本不在结果中
5. 每个 variant 独立 FTS 搜索
   - "LLMs for mobility" → 匹配正文 chunks
   - "authors" / "affiliations" → 如果 PDF 提取质量好，可能匹配作者 chunks
   - 但如果提取出 "JohnDoe"、"UniversityofPennsylvania" → FTS 无法匹配
6. RRF 融合所有结果列表
   - 作者 chunk 若出现在某些列表中，RRF 能将其拉高
   - 但多数情况下，作者 chunk 根本不在任何列表中 → RRF 无数据可融合
7. Literal match boost
   - 查找精确匹配 "LLMs for mobility的作者是谁" → 无 chunk 包含完整查询
   - 短 fragment "作者" 因 CJK min_length=16 不构成独立 fragment
8. Document merge → 合并被召回的 chunks
   - 若作者 chunks 未被召回，merge 无法补全
9. 最终返回：正文 chunks → 用户得到的是论文内容，不是作者信息
```

**9 步中，从第 2 步（embedding）开始就已偏离正确方向，后续 6 步的复杂检索机制都在错误的结果集上操作。**

---

## 7. 项目现有检索架构完整图

### 索引链路

```
Upload → RagEnqueueService → RagWorkerService → RagIndexingOrchestrator
                                                    ├─ _parse_pdf()        [pymupdf, flat text]
                                                    ├─ _parse_docx()       [heading-aware]
                                                    ├─ chunk_text()        [paragraph → sentence → hard]
                                                    ├─ embed_rag_texts()   [Gemini embedding-2]
                                                    ├─ embed_rag_image_files() [multimodal]
                                                    └─ upsert_rag_asset_points() [Qdrant]

rag_assets collection:
├─ payload indexes: user_id, document_id, project_id, index_generation,
│   asset_type, asset_index, chunk_index, modality, index_profile
├─ FTS index: search_text (MULTILINGUAL, min=2, max=20)
└─ vector index: cosine similarity
```

### 检索链路

```
search_chunks(query, user_id, top_k, merge, modalities, precise_passage_lookup)
├─ normalize modalities
├─ [optional] _arewrite_queries_via_llm() → 3-5 variants
│   └─ _shared_arewrite_queries_via_llm() [LLM + cache + retry + timeout 5s]
│       └─ _QUERY_REWRITE_SYSTEM: "different wording, perspectives, granularity"
├─ For each variant:
│   ├─ aembed_rag_texts(variant, task="retrieval.query") → vector
│   ├─ vector_search_rag_text_assets(embedding, fetch_k=top_k*2)
│   └─ keyword_search_rag_text_assets(variant_text, fetch_k)
├─ [optional] image vector + image keyword search
├─ filter result_lists to completed documents only
├─ rrf_merge(all_result_lists, top_k) → Reciprocal Rank Fusion (k=60)
├─ _prioritize_literal_passage_matches(query, chunks)
│   └─ _literal_match_score() [normalize → fragment matching, score 0-3]
└─ [optional] _merge_chunks_by_document()
    ├─ _group_chunks_by_document() [segment detection, gap-fill]
    └─ _combine_merged_and_assets() [sort by rank_score, clip to top_k]
```

---

## 8. 结论

### 8.1 根本矛盾

> **RAG 系统把所有信息当作"同质文本流"处理，没有区分文档结构层（元数据）和内容层（正文），且单向量检索无法分解复合查询意图。**

这导致：
1. 元数据信息在切片时被碎片化
2. 碎片化元数据在 embedding 空间中语义稀薄
3. 复合查询的元数据意图被主题语义淹没
4. PDF 提取质量问题进一步恶化了上述所有环节

### 8.2 项目在此问题上的投入

| 层级 | 投入 | 效果 |
|------|------|------|
| 检索端 | LLM query rewrite + 混合搜索 + RRF + literal boost + document merge | 5 层融合，但都作用在"错误的召回集合"上 |
| 索引端 | 无结构化解析、无质量后处理、无结构感知切片 | 信息在源头就已经损失 |
| FTS 端 | Qdrant MULTILINGUAL tokenizer | `max_token_len=20` 让长 token 完全不可查 |
| Query 端 | 词法级别改写 | 非意图级别分解 |

**核心矛盾：检索端投入了大量工程复杂度（5 层融合），但索引端把 PDF 当扁平文本流处理——信息源头就已损失结构，后续所有优化都是在损失的基础上修补。**

### 8.3 诊断测试覆盖

`tests/test_rag/diagnostic_test_rag_gaps.py` — 31 个测试，0 失败，覆盖：

- 切片策略结构感知缺失（4 tests）
- PDF 解析元数据缺失（3 tests）
- 复合查询 embedding 坍塌（3 tests）
- Literal match CJK 限制（3 tests）
- 确定性 query variant 分解不足（4 tests）
- Qdrant FTS tokenizer 限制（4 tests）
- RRF 融合限制（2 tests）
- 作者信息密度碎片化（3 tests）
- 系统级搜索流程缺失（4 tests）
- 端到端失败链路（1 test）
