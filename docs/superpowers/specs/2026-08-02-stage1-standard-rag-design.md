# 阶段1设计：修复 Standard RAG 核心效果闭环

> 制定日期：2026-08-02
> 状态：待审批
> 前置条件：阶段0完成（评测集 v1 + 基线分数 + CI 三层架构）

---

## 一、执行策略

### 执行顺序

```
1.3 (S, ~3天) → 1.1+1.2 (M+M, ~2周) → 1.4 (M, ~1周) → 1.5 (M, ~1周) → 1.6 (M, ~1周)
```

### 依赖关系

- **1.3 先行**：RetrievalCandidate 数据类是 1.4（Reranker）和 1.5（拒答校准）的前置——reranker 需要在候选上写 rerank_score，拒答特征需要各通道原始分数。
- **1.1+1.2 合并**：CJK tokenizer 和 embedding 模型切换都会触发索引重建，合并为一次「sparse + dense 联合基线对比」避免重测。
- **1.4 → 1.5**：拒答校准依赖 reranker 的 top_score 作为核心特征。
- **1.6 独立**：引用闭环不依赖 1.4/1.5，但放在最后确保检索质量已稳定。

### 每个工作项的完成标准

- 更新 CHANGELOG
- 全量测试通过（pytest）
- 在评测集 v1 上跑基线对比，记录指标变化

---

## 二、1.3 统一 Candidate 模型与 Top-K 语义

### 问题

| 问题 | 位置 | 影响 |
|---|---|---|
| 检索结果无统一数据模型 | `src/rag.py` 全局 | 各通道原始分数丢失，无法做精细排序和拒答判断 |
| `_build_context` 硬编码 `[:5]` | `src/rag.py:1185` | dynamic_top_k 计算被浪费 |
| `format_sources` 硬编码 `[:5]` | `src/rag.py:1346` | 与 context 不一致 |
| `selected_count` 记录错误 | `src/rag.py:1402` | 记录 dynamic_top_k 值而非实际进入 prompt 的数量 |

### 设计

#### 新增 `src/domain.py`

```python
@dataclass(frozen=True)
class RetrievalCandidate:
    """检索候选，保留各通道原始分数和融合分数。"""
    index: int                    # 在 collection 中的原始位置
    chunk_id: str
    source_id: str
    source_name: str

    # 各通道原始分数（None 表示该通道未召回此候选）
    dense_similarity: float | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    graph_score: float | None = None
    rerank_score: float | None = None

    # 各通道排名
    dense_rank: int | None = None
    bm25_rank: int | None = None
    rrf_rank: int | None = None
```

#### 三层 K 语义

| 层级 | 名称 | 含义 | 当前值 | 改为 |
|---|---|---|---|---|
| candidate_k | 召回候选数 | 各通道召回后合并去重的总数 | dynamic_top_k (12-70) | 保持不变 |
| context_k | 进入 prompt 的证据数 | 实际构建 LLM context 的候选数 | 硬编码 5 | token budget 控制 |
| display_k | 展示给用户的来源数 | format_sources 展示的来源数 | 硬编码 5 | 与 context_k 一致 |

#### context_k 计算

```python
def compute_context_k(
    candidates: list[RetrievalCandidate],
    token_budget: int = 3000,
    avg_chunk_tokens: int = 200,
    min_k: int = 3,
    max_k: int = 10,
) -> int:
    """基于 token budget 计算实际进入 prompt 的候选数。

    token_budget: LLM context 中分配给检索证据的 token 预算（默认 3000，约 4K 字符）
    avg_chunk_tokens: 每个 chunk 的平均 token 数（默认 200，基于 DEFAULT_CHUNK_SIZE=500 字符 ÷ ~2.5 字符/token）
    """
    budget_k = max(min_k, min(max_k, token_budget // avg_chunk_tokens))
    return min(len(candidates), budget_k)
```

#### 修复点

1. `_build_context()` 的 `top_indices[:5]` → `top_indices[:context_k]`
2. `format_sources()` 的 `indices[:5]` → `indices[:context_k]`
3. `selected_count` 记录 `context_k` 而非 `len(top_indices)`
4. `QueryMetric` 新增 `context_k: int` 字段

#### 不改变

- `dynamic_top_k()` 的逻辑保持不变，它决定 candidate_k
- `rrf_merge()` 的接口不变，但返回值改为 `list[RetrievalCandidate]`

---

## 三、1.1+1.2 Sparse+Dense 联合基线对比

### 问题

| 问题 | 位置 | 影响 |
|---|---|---|
| CJK 连续字符被当作一个 token | `src/rag.py:1090-1092` | 中文 BM25 几乎无效 |
| 分块分隔符缺少中文标点 | `src/rag.py:153-170` | 中文文本在句号处不分块 |
| 英文中心 embedding 模型 | `src/rag.py:67` | 中文语义检索质量差 |
| 1.1 和 1.2 有索引重建依赖 | 计划文档 | 先做 1.1 后切换模型需重测 |

### 设计

#### 3a. CJK n-gram tokenizer

**新建 `src/lexical.py`**：

```python
_CJK_RANGES = (
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3400, 0x4DBF),   # CJK Extension A
    (0xF900, 0xFAFF),   # CJK Compatibility Ideographs
)

def is_cjk(ch: str) -> bool:
    """判断字符是否为 CJK 字符。"""
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)

def cjk_ngram_tokenize(text: str, n: int = 2) -> list[str]:
    """CJK 字符按 n-gram 切分，英文/数字按空格和标点分词。

    处理规则：
    1. CJK 字符：收集连续 CJK 序列，生成 bigram（如"南京总面积"→["南京","京总","总面","面积"]）
    2. 英文/数字：按空格和标点分词，保留完整词（如"6587km2"→["6587km2"]）
    3. 混合文本：CJK 和非 CJK 交替出现时，各自独立处理
    4. 所有 token 小写化
    5. 不做停用词过滤（BM25Okapi 内部有 IDF 处理）

    示例：
      "南京总面积约6587km2" → ["南京", "京总", "总面", "面积", "6587km2"]
      "What is RAG?" → ["what", "is", "rag"]
    """
    tokens = []
    cjk_buffer = []

    for ch in text:
        if is_cjk(ch):
            cjk_buffer.append(ch)
        else:
            # flush CJK buffer → generate n-grams
            if cjk_buffer:
                tokens.extend(_cjk_ngrams(cjk_buffer, n))
                cjk_buffer = []

    if cjk_buffer:
        tokens.extend(_cjk_ngrams(cjk_buffer, n))

    # 英文/数字部分按空格分词
    # 先提取非CJK文本段，按空格分词
    # ...（完整实现见代码）

    return tokens

def _cjk_ngrams(chars: list[str], n: int) -> list[str]:
    """从 CJK 字符列表生成 n-gram。"""
    if len(chars) < n:
        return ["".join(chars)] if chars else []
    return ["".join(chars[i:i+n]) for i in range(len(chars) - n + 1)]
```

**元数据字段加权**：

```python
def build_weighted_bm25_corpus(
    documents: list[str],
    metadatas: list[dict],
    field_weights: dict[str, float] | None = None,
) -> list[str]:
    """构建带字段权重的 BM25 语料。

    字段权重通过重复文本实现：source_name 权重 2.0 意味着重复 2 次。
    """
    weights = field_weights or {"content": 1.0, "source_name": 2.0, "section": 1.5}
    corpus = []
    for doc, meta in zip(documents, metadatas):
        parts = [doc]  # content * 1.0
        name = meta.get("source_name", "")
        if name:
            parts.extend([name] * int(weights.get("source_name", 1)))
        section = meta.get("section", "")
        if section:
            parts.extend([section] * int(weights.get("section", 1)))
        corpus.append(" ".join(parts))
    return corpus
```

**分块分隔符修复**：

```python
# 修改 CHUNKING_CONFIG 的 separators
separators = ["\n\n", "\n", "。", "！", "？", "；", ".", " ", ""]
```

**manifest 指纹更新**：tokenizer 类型（`whitespace` / `cjk_bigram`）纳入 manifest，tokenizer 变更自动触发索引重建。

#### 3b. 多语种 Embedding 对比

**新增 `evaluation/embedding_benchmark.py`**：

```python
@dataclass
class EmbeddingComparison:
    model_name: str
    recall_at_5: float
    recall_at_10: float
    mrr: float
    ndcg_at_5: float
    index_build_ms: float
    query_ms_p50: float
    memory_mb: float
    index_size_mb: float

class EmbeddingBenchmark:
    """对比不同 embedding 模型的检索质量。"""

    def run_comparison(
        self,
        models: list[str],
        dataset_path: str,
        corpus_dir: str,
    ) -> list[EmbeddingComparison]:
        """对每个模型：构建索引 → 运行检索评测 → 记录指标。"""
        ...
```

**候选模型**：
- 当前：`all-MiniLM-L6-v2`（384d，英文中心）
- 候选：`BAAI/bge-m3`（1024d，100+语言，dense+sparse+multi-vector）

**决策标准**：
- bge-m3 在中文/混合查询的 Recall@5 提升 ≥ 15% → 切换
- 延迟增加 < 2x → 可接受
- 内存增加 < 3x → 可接受

**若决定切换**：
- 修改 `DEFAULT_EMBEDDING_MODEL` 为 `BAAI/bge-m3`
- bge-m3 输出维度 1024（vs 当前 384），ChromaDB collection 维度不兼容，必须删除旧 collection 并全量重建
- manifest 指纹包含 embedding 模型名 + 维度，自动检测不兼容并触发索引重建
- Docker 镜像预下载 bge-m3（约 2.2GB），需更新 Dockerfile 和 docker-entrypoint.sh
- 提供迁移提示：首次启动时检测到维度不匹配，自动重建并打印提示

**若决定不切换**：
- 记录对比结果，保持当前模型
- 后续可考虑更轻量的多语种模型

---

## 四、1.4 Reranker

### 设计

**新增 `src/retrieval.py`**，封装 reranker 接口和融合逻辑：

```python
from typing import Protocol

class Reranker(Protocol):
    """重排器接口。"""
    def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        top_k: int,
    ) -> list[RetrievalCandidate]:
        ...

class CrossEncoderReranker:
    """本地 cross-encoder reranker。"""

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    ) -> None:
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model_name)
        self._model_name = model_name

    def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        top_k: int = 10,
    ) -> list[RetrievalCandidate]:
        """对候选列表重排，返回 top_k 候选（带 rerank_score）。"""
        if not candidates:
            return []
        pairs = [(query, self._get_snippet(c)) for c in candidates]
        scores = self.model.predict(pairs)
        scored = [
            dataclasses.replace(c, rerank_score=float(scores[i]))
            for i, c in enumerate(candidates)
        ]
        scored.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        return scored[:top_k]
```

**插入位置**：RRF 融合后、`_build_context()` 前：

```
dense + bm25 → RRF merge → dynamic_top_k → Reranker → context_k → _build_context
```

**约束**：
- 每来源上限：同一来源最多 3 个 chunk 进入 context
- 跨文档覆盖：优先覆盖不同来源（对 cross_document 类型查询尤其重要）

**可选方案**：若 cross-encoder 延迟过高，可考虑 LLM-based reranker（更准但更慢）或简单特征加权（无额外模型）。

---

## 五、1.5 拒答校准

### 问题

| 问题 | 位置 | 影响 |
|---|---|---|
| RRF `1/(rank+30)` 导致阈值形同虚设 | `src/rag.py:1131-1153` | 任一通道第一名就超 0.03 阈值 |
| 拒答阈值 0.03 过低 | `src/rag.py:183` | 几乎从不拒答 |
| BM25 不剔除 0 分文档 | `src/rag.py:1282-1324` | 无关文档参与排名 |

### 设计

#### 可解释拒答特征

```python
@dataclass(frozen=True)
class RefusalFeatures:
    """拒答判断的可解释特征。"""
    top_score: float              # reranker 最高分（若有）或 RRF 最高分
    top1_top2_margin: float       # top1 与 top2 的分数差
    effective_source_count: int   # 有效来源数（score > 0 的不同来源）
    query_length: int             # 查询长度
    has_cjk: bool                 # 是否含中文
    max_dense_similarity: float   # dense 通道最高相似度
    max_bm25_score: float         # BM25 通道最高分
```

#### 阈值策略

1. **修复 RRF k 值**：`1/(rank+30)` → `1/(rank+60)`，降低单通道第一名的权重
2. **拒答判断基于 reranker top_score**（若有 reranker）或 RRF top_score
3. **在评测集 v1 的 `should_refuse` 子集上选阈值**：
   - 初始阈值：reranker top_score < 0.3 → 拒答
   - RRF top_score < 0.015 → 拒答（无 reranker 时）
4. **分开记录**：检索拒答、生成拒答、API 错误，不把三者都当作普通回答文本

#### BM25 零分剔除

在 `rrf_merge()` 中，BM25 得分为 0 的文档不参与 RRF 排名。

---

## 六、1.6 引用闭环

### 设计

#### 流程

```
LLM 生成回答 → validate_citations() →
  ├─ 全部合法 → 正常返回
  ├─ 有非法引用 → 一次修复请求 →
  │    ├─ 修复成功 → 返回修复后回答
  │    └─ 修复失败 → 标记"不可验证" + TUI 警告
  └─ 无引用但有事实陈述 → 标记"缺少引用"
```

#### 实现

1. 在 `answer_query()` 和 `answer_query_stream()` 生成结束后，调用 `src/citations.py` 的 `validate_citations()` 校验引用 ID
2. 非法 ID 触发一次受限修复：向 LLM 发送"请修正以下非法引用"的修复请求（限制 token 数，避免长对话）
3. 修复仍失败则明确标记回答为"不可验证"，TUI 展示警告
4. 对需要事实依据的回答要求至少一个有效引用；纯对话/操作说明按 query 类型豁免
5. 在评测集 v1 上测量 citation precision/recall

#### 新增数据

```python
@dataclass
class CitationValidation:
    """引用校验结果。"""
    valid_ids: set[str]           # 合法引用 ID
    invalid_ids: set[str]         # 非法引用 ID
    repaired: bool = False        # 是否经过修复
    repair_success: bool = False  # 修复是否成功
    unverified: bool = False      # 是否标记为不可验证
```

---

## 七、模块重构路线（阶段1范围）

阶段1涉及的模块变更：

```
src/domain.py          新增：RetrievalCandidate、RefusalFeatures、CitationValidation
src/lexical.py         新增：CJK n-gram tokenizer、字段加权 BM25 语料构建
src/retrieval.py       新增：Reranker 接口、CrossEncoderReranker、融合逻辑
src/rag.py             修改：使用 RetrievalCandidate、修复硬编码、集成 reranker
src/metrics.py         修改：QueryMetric 新增 context_k 字段
evaluation/embedding_benchmark.py  新增：Embedding 对比评测
```

**迁移原则**：
- 每次只移动一个职责
- 原模块通过 import 委托，不破坏外部接口
- 新模块有独立测试

---

## 八、验收指标

| 工作项 | 核心指标 | 目标 |
|---|---|---|
| 1.3 | context_k 与 display_k 一致性 | 100% |
| 1.1+1.2 | 中文/混合查询 Recall@5 | ≥ 当前基线 + 15% |
| 1.4 | Context precision | 上升且 recall 不显著下降 |
| 1.5 | should_refuse 子集 precision/recall | ≥ 0.8 / ≥ 0.7 |
| 1.6 | Citation ID validity | 100% |

每次检索相关变更都应附对比表：总体、中文、英文、中英混合、无答案、跨文档六个切片。
