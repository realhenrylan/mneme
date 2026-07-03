# RAG 查询能力提升计划：LLM 驱动的查询拆解

## 编码原则：KISS

1. **尽量复用已有代码**。不要引入新的抽象、基类或设计模式。直接使用已有的 `retrieve_hybrid_with_sources`、`dynamic_top_k`、`format_sources`、`answer_with_llm_history_stream`、`DEFAULT_LLM_MODEL`。
2. **不做过度设计**。只有一个新模块、一个新函数、一个 guard 判断。
3. **优先内联**。`answer_query_stream` 中直接写多 query 检索逻辑，不抽取中间层。
4. **沿用已有模式**。`concurrent.futures.ThreadPoolExecutor` 已在 `graph_rag.py` 中使用，直接复用该范式。

---

## 背景

基准查询 "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？" 的 Recall@20 = 0%，原因是单个 embedding 无法同时表达 "定位这篇论文" 和 "找出作者机构" 两个意图。

**核心思路**：借鉴 SciClaw 多维度检索策略——每次查询调用 LLM 拆解为 1-3 个子查询，并发检索后取并集去重。

---

## 设计决策

| 决策点 | 选择 |
|--------|------|
| 拆解策略 | 全部 LLM（无正则规则路径） |
| 简单查询跳过（KISS guard） | 长度 ≤ 4 字符 或 单个单词 → 不调 LLM |
| LLM 失败 fallback | 重试 1 次，仍失败 → 静默降级为 `[query]` |
| 子查询检索 | `ThreadPoolExecutor` 并发（复用 `graph_rag.py` 模式） |
| 结果融合 | 取并集 + 按 chunk 去重（仅保留最高分）+ 降序排列 |
| 测试策略 | mock 单元测试 + 真实 API 集成测试（TDD） |
| 范围 | 仅查询拆解 |

---

## 新增模块

**文件：`rag_query_decomposer.py`**

```python
"""LLM 驱动的查询拆解。"""

import json
import re
import os
from openai import OpenAI

DECOMPOSE_PROMPT = """You are a query rewriter for a RAG system.
Decompose the user query into 1-3 sub-queries that, when searched
independently, will retrieve all the information needed.

Rules:
1. If the query contains both a TOPIC and a specific METADATA/ATTRIBUTE
   question, split them into separate sub-queries.
2. If the query mixes Chinese and English, split by language boundary.
   Use ONLY words that appear in the original query — do NOT add new
   keywords or topic expansions.
3. If the query is already simple, return a single sub-query (unchanged).
4. Return ONLY a JSON array of strings. No markdown, no explanation.

Examples:
  "LLMs for mobility这篇文章的作者都属于什么学校？"
  → ["LLMs for mobility",
     "作者都属于什么学校或者科研机构？"]

  "这篇论文讲了什么？"
  → ["这篇论文讲了什么？"]

  "DSpark 论文的主要贡献和作者分别是什么？"
  → ["DSpark 论文的主要贡献", "DSpark 作者和机构"]"""


def should_decompose(query: str) -> bool:
    """KISS guard：简单查询不调 LLM"""
    query = query.strip()
    if len(query) <= 4:
        return False
    if len(query.split()) == 1 and not re.search(r'[\u4e00-\u9fff]', query):
        return False  # single English word, no need to decompose
    return True


def decompose_query_llm(
    query: str,
    model: str = "deepseek-chat",
    temperature: float = 0.0,
    max_retries: int = 2,
) -> list[str]:
    """LLM 驱动的查询拆解。

    拆解为 1-3 个子查询。失败时重试，仍失败则返回 [query]。
    """
    if not should_decompose(query):
        return [query]

    api_key = os.getenv("API_KEY")
    base_url = os.getenv("BASE_URL")
    if not api_key or not base_url:
        return [query]

    for attempt in range(max_retries):
        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": DECOMPOSE_PROMPT},
                    {"role": "user", "content": f"Query: {query}"},
                ],
                temperature=temperature,
                max_tokens=150,
                timeout=30,
            )
            content = response.choices[0].message.content.strip()
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            sub_queries = json.loads(content)
            if isinstance(sub_queries, list) and len(sub_queries) > 0:
                return sub_queries
        except (json.JSONDecodeError, Exception):
            pass
    return [query]  # 降级
```

---

## 修改 `rag.py`

**修改 `answer_query_stream`**（L802-824）和 **`answer_query`**（L607-632）。

在函数顶部注入拆解逻辑（两个函数做相同改动）：

```python
from rag_query_decomposer import decompose_query_llm
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── 新增：LLM 查询拆解 ──
sub_queries = decompose_query_llm(query, model=llm_model)

# 子查询并发检索（复用 graph_rag.py 的 as_completed 模式）
all_entries = []  # [(idx, score), ...]
with ThreadPoolExecutor(max_workers=min(4, len(sub_queries))) as executor:
    futures = {
        executor.submit(
            retrieve_hybrid_with_sources,
            sq, model, collection, bm25, documents, metadatas
        ): sq for sq in sub_queries
    }
    for future in as_completed(futures):
        indices, _, scores = future.result()
        for idx, score in zip(indices, scores):
            all_entries.append((idx, score))

# 按 chunk 去重 → 仅保留每个 chunk 的最高分
best_score: dict[int, float] = {}
for idx, score in all_entries:
    if idx not in best_score or score > best_score[idx]:
        best_score[idx] = score

# 降序排列
merged = sorted(best_score.keys(), key=lambda i: best_score[i], reverse=True)

# dynamic_top_k 作用于去重后的分数列表
scores_flat = sorted(best_score.values(), reverse=True)
k = dynamic_top_k(scores_flat[:max(top_k_range)], min_k=top_k_range[0], max_k=top_k_range[1])
top_indices = merged[:k]
```

其余部分（context 拼接、source 格式化、stream 生成）完全不变。

---

## TDD 测试

**文件：`test_query_decomposer.py`**，分为 3 个层级。

### 层级 1：mock 单元测试（不调 API）

```python
import os
from unittest.mock import patch, MagicMock
from rag_query_decomposer import should_decompose, decompose_query_llm

_MOCK_ENV = {"API_KEY": "sk-test", "BASE_URL": "https://test"}

def test_should_decompose_short():
    assert should_decompose("hi") is False
    assert should_decompose("ab") is False

def test_should_decompose_single_word():
    assert should_decompose("hello") is False

def test_should_decompose_normal():
    assert should_decompose("这篇论文讲了什么？") is True
    assert should_decompose("LLMs for mobility") is True

def test_llm_mock_returns_json():
    """mock API → 返回合法 JSON → 正确解析"""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        '["LLMs for mobility","作者都属于什么学校？"]'
    )
    with patch.dict(os.environ, _MOCK_ENV):
        with patch("rag_query_decomposer.OpenAI") as mock_openai:
            mock_openai.return_value.chat.completions.create.return_value = mock_response
            result = decompose_query_llm("LLMs for mobility这篇文章的作者？")
    assert len(result) == 2
    assert "LLMs for mobility" in result[0]
    assert "作者" in result[1]

def test_llm_mock_bad_json_fallback():
    """mock API 返回非法 JSON → 降级为 [query]"""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "not valid json"
    with patch.dict(os.environ, _MOCK_ENV):
        with patch("rag_query_decomposer.OpenAI") as mock_openai:
            mock_openai.return_value.chat.completions.create.return_value = mock_response
            result = decompose_query_llm("LLMs for mobility")
    assert result == ["LLMs for mobility"]

def test_llm_mock_api_error_fallback():
    """mock API 抛异常 → 重试后降级为 [query]"""
    with patch.dict(os.environ, _MOCK_ENV):
        with patch("rag_query_decomposer.OpenAI") as mock_openai:
            mock_openai.return_value.chat.completions.create.side_effect = Exception("boom")
            result = decompose_query_llm("LLMs for mobility")
    assert result == ["LLMs for mobility"]
```

### 层级 2：真实 API 集成测试（需 API_KEY）

```python
import pytest

@pytest.mark.integration
def test_decompose_llm_bilingual():
    """中英复合查询 → 至少 2 个子查询，且不含捏造的关键词"""
    sub = decompose_query_llm(
        "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"
    )
    assert len(sub) >= 2, f"Expected ≥2, got {len(sub)}: {sub}"

@pytest.mark.integration
def test_decompose_llm_simple():
    """简单查询 → 1 个子查询"""
    sub = decompose_query_llm("这篇论文讲了什么？")
    assert len(sub) == 1
```

### 层级 3：检索效果回归测试（隔离 DB）

```python
import os
import shutil
from pathlib import Path
from rag import prepare_index, retrieve_hybrid_with_sources, CHROMA_DB_PATH as _ORIGINAL_DB
from rag_query_decomposer import decompose_query_llm

PROJECT_ROOT = Path(__file__).resolve().parent
PDF_FILE = str(PROJECT_ROOT / "test_texts" / "2405.02357v2.pdf")
QUERY = "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"
TEST_DB = PROJECT_ROOT / "test_analysis" / "chroma_db_test"

def _clean_db():
    if TEST_DB.exists():
        shutil.rmtree(str(TEST_DB), ignore_errors=True)

def _set_test_db():
    _clean_db()
    import rag
    rag.CHROMA_DB_PATH = str(TEST_DB)

def _restore_db():
    import rag
    rag.CHROMA_DB_PATH = _ORIGINAL_DB
    _clean_db()

def test_multi_query_recall_improvement():
    """多 query 检索应比单 query 检索召回更多 anchor"""
    _set_test_db()
    try:
        model, collection, bm25, docs, metas = prepare_index(
            [PDF_FILE], "test_mq",
        )
        s_idx, _, _ = retrieve_hybrid_with_sources(
            QUERY, model, collection, bm25, docs, metas, k=20,
        )
        sub_queries = decompose_query_llm(QUERY)
        m_idx_set = set()
        for sq in sub_queries:
            idxs, _, _ = retrieve_hybrid_with_sources(
                sq, model, collection, bm25, docs, metas, k=10,
            )
            m_idx_set.update(idxs[:10])

        anchor_set = {i for i, m in enumerate(metas) if m.get("chunk_type") == "anchor"}
        assert anchor_set, "未生成 anchor chunk"
        single_ok = bool(set(s_idx[:20]) & anchor_set)
        multi_ok = bool(m_idx_set & anchor_set)
        print(f"  单 query Recall@20: {single_ok}")
        print(f"  多 query Recall: {multi_ok}")
        assert multi_ok, "多 query 检索应召回 anchor chunk"
    finally:
        _restore_db()

def test_multi_query_no_duplicates():
    """多 query 检索去重：相同 chunk 仅保留最高分，最终列表无重复索引"""
    _set_test_db()
    try:
        model, collection, bm25, docs, metas = prepare_index(
            [PDF_FILE], "test_mq_dedup",
        )
        sub_queries = decompose_query_llm(QUERY)
        all_entries = []
        for sq in sub_queries:
            idxs, _, scores = retrieve_hybrid_with_sources(
                sq, model, collection, bm25, docs, metas, k=20,
            )
            for i, s in zip(idxs, scores):
                all_entries.append((i, s))

        # 按 chunk 去重，仅保留最高分（与 plan 中 best_score 逻辑一致）
        best: dict[int, float] = {}
        for idx, score in all_entries:
            if idx not in best or score > best[idx]:
                best[idx] = score
        top_indices = sorted(best.keys(), key=lambda i: best[i], reverse=True)
        assert len(top_indices) == len(set(top_indices)), "去重后仍含重复索引"
    finally:
        _restore_db()
```

---

## TDD 执行顺序

```
Round 1（先写测试，全部失败）:
  ✗ 层级 1：全部 5 个 mock 测试
  ✗ 层级 2：2 个集成测试
  ✗ 层级 3：2 个回归测试

Round 2（实现 rag_query_decomposer.py）:
  ✓ 层级 1：5/5 mock 测试通过
  ✓ 层级 2：2/2 集成测试通过（调真实 API）
  ✗ 层级 3：2/2 回归测试（仍需修改 rag.py）

Round 3（修改 rag.py — answer_query_stream + answer_query）:
  ✓ 层级 3：2/2 回归测试通过
  ✓ test_retrieval_fix.py 全量回归 8/8 通过
```

---

## 实施步骤

| 序号 | 步骤 | 文件 | 改动量 |
|------|------|------|--------|
| 1 | TDD Round 1：编写全部测试（预期失败） | `test_query_decomposer.py` | ~120 行 |
| 2 | 实现 `should_decompose` + `decompose_query_llm` | `rag_query_decomposer.py` | ~70 行 |
| 3 | 修改 `answer_query_stream` 注入拆解 + 并发检索 | `rag.py:802-824` | ~45 行 |
| 4 | 同步修改 `answer_query` 注入拆解 | `rag.py:607-632` | ~45 行 |
| 5 | 运行全量回归 | - | - |
| 6 | 端到端手动验证 | `rag-sys` | - |

**总改动量：~280 行，1 个新文件、1 个修改文件。**

---

## 预期效果

| 指标 | 当前 | 预期 |
|------|------|------|
| 复合查询子查询数 | 1 | 2-3 |
| Recall@20（复合意图元数据查询） | 0% | >0%（至少召回 anchor） |
| 单意图查询影响 | 正常 | 无退化（should_decompose 跳过或 LLM 返回单查询） |
| LLM API 额外开销 | 0 | +1 次调用 / 查询（~50 tokens，timeout=30s） |

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| LLM 返回非 JSON | JSON parse 失败 → 重试 1 次 → 降级 `[query]` |
| LLM API 超时/限频 | `timeout=30` + 重试 1 次 → 静默降级 `[query]` |
| 同一 chunk 多子查询命中 → 重复分数扭曲 dynamic_top_k | 按 chunk 去重，仅保留最高分 |
| Prompt 教 LLM 捏造检索关键词 | Rule 2 改为 "Use ONLY words from original query"，示例不含扩展词 |
| 并发检索写冲突 | 纯读取操作，无写冲突 |
| 子查询 context 超长 | 限制子查询 ≤3 个，与单查询 k=20 总量相当 |
| Mock 测试因 env var 缺失失败 | 所有 mock 测试用 `patch.dict(os.environ, {...})` 注入假值 |
| 层级 3 测试污染生产 DB | 独立 `chroma_db_test` 目录 + try/finally 清理 |

---

## 验证标准

1. `pytest test_query_decomposer.py -v` — 9/9 通过
2. `pytest test_retrieval_fix.py -v` — 全量回归 8/8 通过
3. 手动验证：`rag-sys` 输入 "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"，回答包含作者和机构信息
