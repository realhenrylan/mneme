# 错误场景不显示 Sources 修复 — TDD 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 RAG 系统在 LLM 调用失败时同时显示错误消息和 Sources 的问题，确保错误场景只显示错误消息。

**Architecture:** 使用生成器包装器 + out-of-band 错误信号方案。LLM 错误通过自定义异常 `LLMError` 传播，在 `answer_query_stream` 层捕获并设置错误标记，`chat.py` 检测标记后决定是否显示 Sources。

**Tech Stack:** Python 3.12, pytest, unittest.mock, OpenAI API (RateLimitError/APIConnectionError/APIError)

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `src/rag.py` | 定义 `LLMError` 异常；修改 `answer_with_llm_history_stream` 改 yield 为 raise；修改 `answer_query_stream` 添加包装器 |
| `src/graph_rag.py` | 修改 `graph_query_stream` 添加包装器 |
| `tui/screens/chat.py` | 修改 sources 显示逻辑，检查错误信号 |
| `tests/test_error_no_sources.py` | 新增测试文件，验证错误场景不显示 Sources |

---

## Task 1: 定义 LLMError 异常类

**Files:**
- Modify: `src/rag.py:56`（在 DEFAULT_TEMPERATURE 之后）

- [ ] **Step 1: Write the failing test**

创建 `tests/test_error_no_sources.py`:

```python
"""错误场景不显示 Sources — TDD 测试套件"""

import os
from unittest.mock import patch, MagicMock
import pytest


# ── Task 1: LLMError 异常类 ─────────────────────────────

def test_llm_error_exception_exists():
    """LLMError 异常类应可正常导入和创建"""
    from src.rag import LLMError

    # 可创建实例
    err = LLMError("test error")
    assert str(err) == "test error"

    # 可被捕获
    try:
        raise LLMError("API failed")
    except LLMError as e:
        assert str(e) == "API failed"
    else:
        pytest.fail("LLMError should be catchable")


def test_llm_error_is_exception():
    """LLMError 应是 Exception 的子类"""
    from src.rag import LLMError

    assert issubclass(LLMError, Exception)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd D:/deepprinciple/mneme && .venv/Scripts/python -m pytest tests/test_error_no_sources.py::test_llm_error_exception_exists -v
```

Expected: FAIL with "cannot import name 'LLMError' from 'src.rag'"

- [ ] **Step 3: Write minimal implementation**

在 `src/rag.py` 第 56 行（`DEFAULT_TEMPERATURE = 0.2` 之后）添加:

```python

# ═══════════════════════════════════════════════
# 自定义异常
# ═══════════════════════════════════════════════

class LLMError(Exception):
    """LLM 调用失败的统一异常"""
    pass
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd D:/deepprinciple/mneme && .venv/Scripts/python -m pytest tests/test_error_no_sources.py::test_llm_error_exception_exists tests/test_error_no_sources.py::test_llm_error_is_exception -v
```

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd D:/deepprinciple/mneme && git add src/rag.py tests/test_error_no_sources.py && git commit -m "feat(rag): add LLMError exception class for unified error handling"
```

---

## Task 2: 修改 answer_with_llm_history_stream 改 yield 为 raise

**Files:**
- Modify: `src/rag.py:869-871`（API 配置检查）
- Modify: `src/rag.py:887-892`（异常处理）
- Test: `tests/test_error_no_sources.py`

- [ ] **Step 1: Write the failing test**

在 `tests/test_error_no_sources.py` 末尾追加:

```python


# ── Task 2: answer_with_llm_history_stream 异常抛出 ─────────────────────────────

_MOCK_ENV = {"API_KEY": "sk-test", "BASE_URL": "https://test"}


def test_answer_with_llm_raises_on_api_config_missing():
    """API 配置缺失应转换为 LLMError 并抛出"""
    from src.rag import answer_with_llm_history_stream, LLMError

    # 不设置 API_KEY 和 BASE_URL
    with patch.dict(os.environ, {}, clear=True):
        gen = answer_with_llm_history_stream("test question", "test context", [])
        with pytest.raises(LLMError) as exc_info:
            list(gen)

        assert "API_KEY" in str(exc_info.value) or "BASE_URL" in str(exc_info.value)


def test_answer_with_llm_raises_on_rate_limit():
    """RateLimitError 应转换为 LLMError 并抛出"""
    from src.rag import answer_with_llm_history_stream, LLMError
    from openai import RateLimitError

    with patch.dict(os.environ, _MOCK_ENV):
        with patch("src.rag.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            # 模拟 RateLimitError
            mock_client.chat.completions.create.side_effect = RateLimitError(
                "Rate limit exceeded",
                response=MagicMock(status_code=429),
                body=None,
            )

            # 生成器迭代时应抛出 LLMError
            gen = answer_with_llm_history_stream("test question", "test context", [])
            with pytest.raises(LLMError) as exc_info:
                list(gen)

            assert "频率超限" in str(exc_info.value)


def test_answer_with_llm_raises_on_connection_error():
    """APIConnectionError 应转换为 LLMError 并抛出"""
    from src.rag import answer_with_llm_history_stream, LLMError
    from openai import APIConnectionError

    with patch.dict(os.environ, _MOCK_ENV):
        with patch("src.rag.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.side_effect = APIConnectionError(
                "Connection failed"
            )

            gen = answer_with_llm_history_stream("test question", "test context", [])
            with pytest.raises(LLMError) as exc_info:
                list(gen)

            assert "无法连接" in str(exc_info.value)


def test_answer_with_llm_raises_on_api_error():
    """APIError 应转换为 LLMError 并抛出"""
    from src.rag import answer_with_llm_history_stream, LLMError
    from openai import APIError

    with patch.dict(os.environ, _MOCK_ENV):
        with patch("src.rag.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.side_effect = APIError(
                "API error",
                response=MagicMock(status_code=500),
                body=None,
            )

            gen = answer_with_llm_history_stream("test question", "test context", [])
            with pytest.raises(LLMError) as exc_info:
                list(gen)

            assert "API 请求失败" in str(exc_info.value)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd D:/deepprinciple/mneme && .venv/Scripts/python -m pytest tests/test_error_no_sources.py::test_answer_with_llm_raises_on_api_config_missing -v
```

Expected: FAIL - 当前代码 yield 错误消息，不抛出异常

- [ ] **Step 3: Write minimal implementation**

**修改 1**：`src/rag.py` 第 869-871 行（API 配置检查）:

**修改前:**
```python
    if not api_key or not base_url:
        yield "[错误] 请在 .env 文件中设置 API_KEY 和 BASE_URL"
        return
```

**修改后:**
```python
    if not api_key or not base_url:
        raise LLMError("请在 .env 文件中设置 API_KEY 和 BASE_URL")
```

**修改 2**：`src/rag.py` 第 887-892 行（异常处理）:

**修改前:**
```python
    except RateLimitError:
        yield "\n[API 请求频率超限，请稍后重试]"
    except APIConnectionError:
        yield "\n[无法连接到 API 服务，请检查网络或 BASE_URL 配置]"
    except APIError as e:
        yield f"\n[API 请求失败: {e}]"
```

**修改后:**
```python
    except RateLimitError:
        raise LLMError("API 请求频率超限，请稍后重试")
    except APIConnectionError:
        raise LLMError("无法连接到 API 服务，请检查网络或 BASE_URL 配置")
    except APIError as e:
        raise LLMError(f"API 请求失败: {e}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd D:/deepprinciple/mneme && .venv/Scripts/python -m pytest tests/test_error_no_sources.py::test_answer_with_llm_raises_on_api_config_missing tests/test_error_no_sources.py::test_answer_with_llm_raises_on_rate_limit tests/test_error_no_sources.py::test_answer_with_llm_raises_on_connection_error tests/test_error_no_sources.py::test_answer_with_llm_raises_on_api_error -v
```

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd D:/deepprinciple/mneme && git add src/rag.py tests/test_error_no_sources.py && git commit -m "refactor(rag): convert LLM errors from yield to LLMError exception"
```

---

## Task 3: 修改 answer_query_stream 添加生成器包装器

**Files:**
- Modify: `src/rag.py:951-955`
- Test: `tests/test_error_no_sources.py`

- [ ] **Step 1: Write the failing test**

在 `tests/test_error_no_sources.py` 末尾追加:

```python


# ── Task 3: answer_query_stream 包装器捕获异常 ─────────────────────────────

def test_answer_query_stream_catches_llm_error():
    """answer_query_stream 应捕获 LLMError 并设置错误信号"""
    from src.rag import answer_query_stream, LLMError
    from openai import RateLimitError

    # Mock 依赖
    mock_model = MagicMock()
    mock_collection = MagicMock()
    mock_bm25 = MagicMock()
    mock_docs = ["test doc"]
    mock_metas = [{"source": "test.txt"}]

    with patch.dict(os.environ, _MOCK_ENV):
        with patch("src.rag.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.side_effect = RateLimitError(
                "Rate limit exceeded",
                response=MagicMock(status_code=429),
                body=None,
            )

            # Mock 检索相关函数（完整 mock 链，避免空列表导致 dynamic_top_k 崩溃）
            with patch("src.rag.decompose_query_llm", return_value=["test query"]):
                with patch("src.rag.retrieve_hybrid_with_sources", return_value=([0], [], [0.9])):
                    with patch("src.rag.dynamic_top_k", return_value=1):
                        with patch("src.rag.enrich_context", return_value=["enriched doc"]):
                            with patch("src.rag._build_context", return_value="test context"):
                                with patch("src.rag.format_sources", return_value="source text"):
                                    stream, sources = answer_query_stream(
                                        "test query", mock_model, mock_collection, mock_bm25,
                                        mock_docs, mock_metas,
                                    )

                                    # 迭代 stream
                                    chunks = list(stream)

                                    # 验证错误消息
                                    assert any("[错误]" in c for c in chunks)

                                    # 验证错误信号被设置
                                    assert hasattr(stream, "_mneme_error")
                                    assert stream._mneme_error == [True]


def test_answer_query_stream_normal_query():
    """正常查询不应设置错误信号"""
    from src.rag import answer_query_stream

    mock_model = MagicMock()
    mock_collection = MagicMock()
    mock_bm25 = MagicMock()
    mock_docs = ["test doc content"]
    mock_metas = [{"source": "test.txt"}]

    # 使用 side_effect 返回可迭代的 mock response
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "This is the answer"

    with patch.dict(os.environ, _MOCK_ENV):
        with patch("src.rag.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            # 使用 return_value 返回可迭代对象
            mock_client.chat.completions.create.return_value = [mock_chunk]

            with patch("src.rag.decompose_query_llm", return_value=["test query"]):
                with patch("src.rag.retrieve_hybrid_with_sources", return_value=([0], [], [0.9])):
                    with patch("src.rag.dynamic_top_k", return_value=1):
                        with patch("src.rag.enrich_context", return_value=["enriched"]):
                            with patch("src.rag._build_context", return_value="context"):
                                with patch("src.rag.format_sources", return_value="source text"):
                                    stream, sources = answer_query_stream(
                                        "test query", mock_model, mock_collection, mock_bm25,
                                        mock_docs, mock_metas,
                                    )

                                    chunks = list(stream)

                                    # 正常查询不应有错误信号
                                    assert not getattr(stream, "_mneme_error", None)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd D:/deepprinciple/mneme && .venv/Scripts/python -m pytest tests/test_error_no_sources.py::test_answer_query_stream_catches_llm_error -v
```

Expected: FAIL - 当前代码没有包装器，异常未被捕获

- [ ] **Step 3: Write minimal implementation**

修改 `src/rag.py` 第 951-955 行:

**修改前:**
```python
    enriched_docs = enrich_context(top_indices, documents, metadatas)
    context = _build_context(top_indices, enriched_docs, metadatas)
    sources = format_sources(top_indices, enriched_docs, metadatas)
    stream = answer_with_llm_history_stream(
        query, context, history or [], model=llm_model, temperature=temperature,
    )
    return stream, sources
```

**修改后:**
```python
    enriched_docs = enrich_context(top_indices, documents, metadatas)
    context = _build_context(top_indices, enriched_docs, metadatas)
    sources = format_sources(top_indices, enriched_docs, metadatas)

    # 包装生成器：捕获 LLM 错误，通过 out-of-band 信号传递
    error_occurred: list[bool] = []

    def _safe_stream():
        try:
            yield from answer_with_llm_history_stream(
                query, context, history or [], model=llm_model, temperature=temperature,
            )
        except LLMError as e:
            error_occurred.append(True)
            yield f"[错误] {e}"
        except (RateLimitError, APIConnectionError, APIError) as e:
            # 兜底：捕获未转换的原始异常
            error_occurred.append(True)
            yield f"[错误] {e}"

    stream = _safe_stream()
    stream._mneme_error = error_occurred  # 挂载错误信号
    return stream, sources
```

需要在文件顶部添加导入（如果尚未导入 `RateLimitError`, `APIConnectionError`, `APIError`）:

检查 `src/rag.py` 第 863 行附近是否有这些导入，如果没有，添加:

```python
from openai import RateLimitError, APIConnectionError, APIError
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd D:/deepprinciple/mneme && .venv/Scripts/python -m pytest tests/test_error_no_sources.py::test_answer_query_stream_catches_llm_error tests/test_error_no_sources.py::test_answer_query_stream_normal_query -v
```

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd D:/deepprinciple/mneme && git add src/rag.py tests/test_error_no_sources.py && git commit -m "feat(rag): add generator wrapper to catch LLM errors in answer_query_stream"
```

---

## Task 4: 修改 graph_query_stream 添加生成器包装器

**Files:**
- Modify: `src/graph_rag.py:27`（添加 openai 异常导入）
- Modify: `src/graph_rag.py:14-25`（添加 LLMError 导入）
- Modify: `src/graph_rag.py:587-591`
- Test: `tests/test_error_no_sources.py`

- [ ] **Step 1: Write the failing test**

在 `tests/test_error_no_sources.py` 末尾追加:

```python


# ── Task 4: graph_query_stream 包装器捕获异常 ─────────────────────────────

def test_graph_query_stream_catches_llm_error():
    """graph_query_stream 应捕获 LLMError 并设置错误信号"""
    from src.graph_rag import graph_query_stream
    from openai import RateLimitError

    mock_model = MagicMock()
    mock_collection = MagicMock()
    mock_bm25 = MagicMock()
    mock_docs = ["test doc"]
    mock_metas = [{"source": "test.txt"}]
    mock_kg = MagicMock()

    with patch.dict(os.environ, _MOCK_ENV):
        with patch("src.rag.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.side_effect = RateLimitError(
                "Rate limit exceeded",
                response=MagicMock(status_code=429),
                body=None,
            )

            # Mock 图增强检索（完整 mock 链）
            with patch("src.graph_rag.graph_augmented_retrieve", return_value=([0], ["doc"], [0.9])):
                with patch("src.graph_rag.dynamic_top_k", return_value=1):
                    with patch("src.graph_rag._build_context", return_value="context"):
                        with patch("src.graph_rag.format_sources", return_value="source"):
                            stream, sources = graph_query_stream(
                                "test query", mock_model, mock_collection, mock_bm25,
                                mock_docs, mock_metas, mock_kg,
                            )

                            chunks = list(stream)

                            assert any("[错误]" in c for c in chunks)
                            assert hasattr(stream, "_mneme_error")
                            assert stream._mneme_error == [True]


def test_graph_query_stream_normal_query():
    """graph_query_stream 正常查询不应设置错误信号"""
    from src.graph_rag import graph_query_stream

    mock_model = MagicMock()
    mock_collection = MagicMock()
    mock_bm25 = MagicMock()
    mock_docs = ["test doc content"]
    mock_metas = [{"source": "test.txt"}]
    mock_kg = MagicMock()

    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "Answer"

    with patch.dict(os.environ, _MOCK_ENV):
        with patch("src.rag.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = [mock_chunk]

            with patch("src.graph_rag.graph_augmented_retrieve", return_value=([0], ["doc"], [0.9])):
                with patch("src.graph_rag.dynamic_top_k", return_value=1):
                    with patch("src.graph_rag._build_context", return_value="context"):
                        with patch("src.graph_rag.format_sources", return_value="source"):
                            stream, sources = graph_query_stream(
                                "test query", mock_model, mock_collection, mock_bm25,
                                mock_docs, mock_metas, mock_kg,
                            )

                            chunks = list(stream)

                            assert not getattr(stream, "_mneme_error", None)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd D:/deepprinciple/mneme && .venv/Scripts/python -m pytest tests/test_error_no_sources.py::test_graph_query_stream_catches_llm_error -v
```

Expected: FAIL - 当前代码没有包装器

- [ ] **Step 3: Write minimal implementation**

**修改 1**：`src/graph_rag.py` 第 27 行，添加 openai 异常导入:

**修改前:**
```python
from openai import OpenAI
```

**修改后:**
```python
from openai import OpenAI, RateLimitError, APIConnectionError, APIError
```

**修改 2**：`src/graph_rag.py` 第 14 行，添加 `LLMError` 导入:

**修改前:**
```python
from rag import (
    build_bm25_index,
    build_index, ask_for_files, _collection_exists,
    add_files_to_index,
    retrieve_hybrid_with_sources, dynamic_top_k,
    answer_with_llm_history, format_sources,
    _build_context,
    SentenceTransformer, chromadb,
    EMBEDDING_MODEL_NAME, DEFAULT_COLLECTION_NAME,
    DEFAULT_TOP_K, DEFAULT_MIN_K, DEFAULT_MAX_K,
    CHROMA_DB_PATH, DEFAULT_LLM_MODEL,
)
```

**修改后:**
```python
from rag import (
    build_bm25_index,
    build_index, ask_for_files, _collection_exists,
    add_files_to_index,
    retrieve_hybrid_with_sources, dynamic_top_k,
    answer_with_llm_history, format_sources,
    _build_context,
    SentenceTransformer, chromadb,
    EMBEDDING_MODEL_NAME, DEFAULT_COLLECTION_NAME,
    DEFAULT_TOP_K, DEFAULT_MIN_K, DEFAULT_MAX_K,
    CHROMA_DB_PATH, DEFAULT_LLM_MODEL,
    LLMError,
)
```

**修改 3**：`src/graph_rag.py` 第 587-591 行:

**修改前:**
```python
    sources = format_sources(top_indices, all_docs, all_metadatas)
    stream = answer_with_llm_history_stream(
        query, context, history or [], model=llm_model, temperature=temperature,
    )
    return stream, sources
```

**修改后:**
```python
    sources = format_sources(top_indices, all_docs, all_metadatas)

    # 包装生成器：捕获 LLM 错误，通过 out-of-band 信号传递
    error_occurred: list[bool] = []

    def _safe_stream():
        try:
            yield from answer_with_llm_history_stream(
                query, context, history or [], model=llm_model, temperature=temperature,
            )
        except LLMError as e:
            error_occurred.append(True)
            yield f"[错误] {e}"
        except (RateLimitError, APIConnectionError, APIError) as e:
            error_occurred.append(True)
            yield f"[错误] {e}"

    stream = _safe_stream()
    stream._mneme_error = error_occurred
    return stream, sources
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd D:/deepprinciple/mneme && .venv/Scripts/python -m pytest tests/test_error_no_sources.py::test_graph_query_stream_catches_llm_error tests/test_error_no_sources.py::test_graph_query_stream_normal_query -v
```

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd D:/deepprinciple/mneme && git add src/graph_rag.py tests/test_error_no_sources.py && git commit -m "feat(graph_rag): add generator wrapper to catch LLM errors in graph_query_stream"
```

---

## Task 5: 修改 chat.py 显示逻辑

**Files:**
- Modify: `tui/screens/chat.py:145`
- Test: `tests/test_error_no_sources.py`

- [ ] **Step 1: Write the failing test**

由于 `chat.py` 是 TUI 层，测试需要验证行为变化。在 `tests/test_error_no_sources.py` 末尾追加:

```python


# ── Task 5: chat.py sources 显示逻辑 ─────────────────────────────

def test_sources_not_shown_when_error():
    """验证错误信号存在时，sources 显示逻辑返回 False"""
    # 模拟 stream 对象
    class MockStream:
        _mneme_error = [True]

    sources = "source text"
    stream = MockStream()

    # 这是 chat.py:145 应用的逻辑
    should_show = sources.strip() and not getattr(stream, "_mneme_error", None)

    assert should_show is False


def test_sources_shown_when_no_error():
    """验证正常情况下，sources 显示逻辑返回 True"""
    class MockStream:
        _mneme_error = []

    sources = "source text"
    stream = MockStream()

    should_show = sources.strip() and not getattr(stream, "_mneme_error", None)

    assert should_show is True


def test_sources_shown_when_no_error_attribute():
    """验证 stream 没有 _mneme_error 属性时，sources 正常显示"""
    class MockStream:
        pass

    sources = "source text"
    stream = MockStream()

    should_show = sources.strip() and not getattr(stream, "_mneme_error", None)

    assert should_show is True
```

- [ ] **Step 2: Run test to verify it passes (逻辑测试)**

```bash
cd D:/deepprinciple/mneme && .venv/Scripts/python -m pytest tests/test_error_no_sources.py::test_sources_not_shown_when_error tests/test_error_no_sources.py::test_sources_shown_when_no_error tests/test_error_no_sources.py::test_sources_shown_when_no_error_attribute -v
```

Expected: PASS (3 tests) - 这是纯逻辑测试，验证显示条件

- [ ] **Step 3: Write minimal implementation**

修改 `tui/screens/chat.py` 第 145 行:

**修改前:**
```python
        if sources.strip():
            console.print(source_reference(sources))
```

**修改后:**
```python
        # 只有在没有错误时才显示 Sources
        if sources.strip() and not getattr(stream, '_mneme_error', None):
            console.print(source_reference(sources))
```

- [ ] **Step 4: Run all tests to verify integration**

```bash
cd D:/deepprinciple/mneme && .venv/Scripts/python -m pytest tests/test_error_no_sources.py -v
```

Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd D:/deepprinciple/mneme && git add tui/screens/chat.py tests/test_error_no_sources.py && git commit -m "fix(chat): only show sources when no LLM error occurred"
```

---

## Task 6: 运行完整测试套件并验证

**Files:**
- All modified files

- [ ] **Step 1: Run all project tests**

```bash
cd D:/deepprinciple/mneme && .venv/Scripts/python -m pytest tests/ -v --tb=short
```

Expected: All tests PASS

- [ ] **Step 2: Manual verification - API 配置缺失**

临时修改 `.env` 移除 API_KEY，启动 TUI 验证:
- 输入查询
- 应只显示错误消息，不显示 Sources

- [ ] **Step 3: Manual verification - 模拟 LLM 错误**

使用 mock 或临时断网，启动 TUI 验证:
- 输入查询
- 触发 RateLimitError 或 APIConnectionError
- 应只显示错误消息，不显示 Sources

- [ ] **Step 4: Final commit if all tests pass**

```bash
cd D:/deepprinciple/mneme && git add -A && git commit -m "fix: error scenarios no longer show Sources (TDD implementation complete)"
```

---

## 验收清单

- [ ] `test_llm_error_exception_exists` PASS
- [ ] `test_llm_error_is_exception` PASS
- [ ] `test_answer_with_llm_raises_on_api_config_missing` PASS
- [ ] `test_answer_with_llm_raises_on_rate_limit` PASS
- [ ] `test_answer_with_llm_raises_on_connection_error` PASS
- [ ] `test_answer_with_llm_raises_on_api_error` PASS
- [ ] `test_answer_query_stream_catches_llm_error` PASS
- [ ] `test_answer_query_stream_normal_query` PASS
- [ ] `test_graph_query_stream_catches_llm_error` PASS
- [ ] `test_graph_query_stream_normal_query` PASS
- [ ] `test_sources_not_shown_when_error` PASS
- [ ] `test_sources_shown_when_no_error` PASS
- [ ] `test_sources_shown_when_no_error_attribute` PASS
- [ ] API 配置缺失时，只显示错误消息，不显示 Sources
- [ ] LLM RateLimitError 时，只显示错误消息，不显示 Sources
- [ ] LLM APIConnectionError 时，只显示错误消息，不显示 Sources
- [ ] LLM APIError 时，只显示错误消息，不显示 Sources
- [ ] 正常查询时，sources 正常显示
