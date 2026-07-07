# Graph RAG enrich_context 集成 — TDD 修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `graph_rag.py` 的四个查询路径中集成 `enrich_context`，使 Graph RAG 模式的 PDF 元数据（作者、机构等）与标准 RAG 一致。

**Architecture:** 最小改动方案：在 import 区增加 `enrich_context`，四个路径各自在调用 `_build_context` 和 `format_sources` 前先调 `enrich_context` 替换 anchor chunk 文本。与 `rag.py` 中 `answer_query`/`answer_query_stream` 的模式保持一致。

**Tech Stack:** Python, pytest, unittest.mock

---

## 问题

`src/graph_rag.py` 中四个查询路径均直接使用 `all_docs` 构建 LLM context，未调用 `enrich_context` 将 anchor chunk 替换为 PDF 首页全文。导致 Graph RAG 模式下 PDF 元数据（作者、机构等）严重缩水。

**受影响路径**：

| 路径 | 函数/位置 | 代码行（实际行号） |
|---|---|---|
| `graph_rag_pipeline()` | 公共 API 函数 | `_build_context` → 446, `format_sources` → 455 |
| `--query` CLI 单次查询 | `main()` 内 `if args.query:` 分支 | `_build_context` → 500, `format_sources` → 503 |
| 交互式循环 | `main()` 内 `while True:` 分支 | `_build_context` → 538, `format_sources` → 547 |
| `graph_query_stream()` | 独立函数 | `_build_context` → 578, `format_sources` → 579 |

**对标**：标准 RAG 的 `answer_query` 和 `answer_query_stream` 已正确集成 `enrich_context`（`rag.py:712`、`rag.py:937`）。

## 方案

最小改动方案：

1. 在 `graph_rag.py` import 区增加 `enrich_context`
2. 四个路径各自先调 `enrich_context`，再将 enriched docs 传给 `_build_context` 和 `format_sources`

```python
# 旧
context = _build_context(top_indices, all_docs, all_metadatas)
sources = format_sources(top_indices, all_docs, all_metadatas)

# 新
enriched_docs = enrich_context(top_indices, all_docs, all_metadatas)
context = _build_context(top_indices, enriched_docs, all_metadatas)
sources = format_sources(top_indices, enriched_docs, all_metadatas)
```

### 不变部分

- `enrich_context` 函数本身（`rag.py:541`）无需修改
- 现有测试全部保持通过
- 行为语义不变：仅 anchor chunk 的文本被 PDF 首页全文替换
- 边界条件由 `enrich_context` 内部 try/except 处理

### 影响范围

| 路径 | 变更前 | 变更后 |
|---|---|---|
| 标准 RAG `answer_query` | ✅ 已 enrich | ✅ 不变 |
| 标准 RAG `answer_query_stream` | ✅ 已 enrich | ✅ 不变 |
| Graph RAG `graph_rag_pipeline()` | ❌ 未 enrich | ✅ 已 enrich |
| Graph RAG `--query` | ❌ 未 enrich | ✅ 已 enrich |
| Graph RAG 交互式循环 | ❌ 未 enrich | ✅ 已 enrich |
| Graph RAG `graph_query_stream` | ❌ 未 enrich | ✅ 已 enrich |

---

## 实施任务

### Task 1: 写测试文件（Red 阶段）

**Files:**
- Create: `tests/test_graph_rag_enrich.py`
- Modify: (none yet)

> **说明**：TDD Red 阶段写测试时，`enrich_context` 尚未在 `graph_rag.py` 中 import。但 `patch("src.graph_rag.enrich_context")` 会在模块命名空间中动态创建该属性——不会报错。Task 2 真正导入后，patch 替换的是模块级属性，行为一致。
>
> **`patch("builtins.input")` 的前提**：`graph_rag.py` 模块加载时没有任何代码调用 `input`（已确认——`input` 仅在 `while True` 循环内出现）。如果未来添加模块级 `input` 调用，此测试需要同步更新。
>
> **`graph_augmented_retrieve` mock 返回值约定**：返回的 indices 是 `all_docs` 全集的索引。测试数据保证 indices 在 `all_docs` 范围内即可。
>
> **`argparse` 真实执行**：`main()` 的测试让 `argparse` 真实解析 `sys.argv`。如果未来 `graph_rag.py` 的 CLI 参数定义变化，需同步更新 `sys.argv` 测试数据。

- [ ] **Step 1: 创建测试文件**

```python
"""
测试 graph_rag.py 中 enrich_context 集成。

TDD: Red → Green → Refactor

Mock 策略注解：
- 所有涉及 main() 的测试都需要 mock prepare_graph_index（否则会真正初始化 ChromaDB）
- main() 中 exit(0)/exit(1) 是 Python 内建函数，需 patch("builtins.exit")
- input() 是 Python 内建函数，需 patch("builtins.input")
- time.time() 必须设 return_value，否则 MagicMock - MagicMock 导致 int() TypeError
- 涉及 print 的测试可 patch("builtins.print") 减少输出噪音
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.graph_rag import (
    graph_query_stream,
    graph_rag_pipeline,
    main,
)


def test_graph_query_stream_calls_enrich_context():
    """graph_query_stream 调用 enrich_context 并将 enrich 后的 docs 传递下去"""
    all_docs = ["short anchor", "body text 1", "body text 2"]
    all_metas = [
        {"source": "a.pdf", "chunk_type": "anchor", "source_path": "/fake/a.pdf"},
        {"source": "a.pdf", "chunk_type": "body"},
        {"source": "a.pdf", "chunk_type": "body"},
    ]
    enriched_expected = ["full first page text...", "body text 1", "body text 2"]

    with (
        patch("src.graph_rag.graph_augmented_retrieve") as mock_retrieve,
        patch("src.graph_rag.dynamic_top_k") as mock_top_k,
        patch("src.graph_rag.enrich_context") as mock_enrich,
        patch("src.graph_rag._build_context") as mock_build,
        patch("src.graph_rag.format_sources") as mock_sources,
        patch("src.graph_rag.answer_with_llm_history_stream") as mock_stream,
    ):
        mock_retrieve.return_value = ([0, 1, 2], all_docs, [0.9, 0.8, 0.7])
        mock_top_k.return_value = 3
        mock_enrich.return_value = enriched_expected
        mock_stream.return_value = iter(["t1", "t2"])

        stream, sources = graph_query_stream(
            "test query", None, None, None,
            all_docs, all_metas, None,
        )

        # enrich_context 应被调用
        mock_enrich.assert_called_once_with([0, 1, 2], all_docs, all_metas)

        # _build_context 应收到 enriched_docs
        mock_build.assert_called_once_with([0, 1, 2], enriched_expected, all_metas)

        # format_sources 应收到 enriched_docs
        mock_sources.assert_called_once_with([0, 1, 2], enriched_expected, all_metas)
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd /d/GitHub/mneme && python -m pytest tests/test_graph_rag_enrich.py::test_graph_query_stream_calls_enrich_context -v
```

预期：FAIL — `mock_enrich.assert_called_once_with` 验证失败，因为 `graph_query_stream` 内部未调用 `enrich_context`。

---

### Task 2: 修复 import + `graph_query_stream`（Green 阶段）

**Files:**
- Modify: `src/graph_rag.py`（import 区 + `graph_query_stream` 函数体内）

- [ ] **Step 1: 在 import 区增加 `enrich_context`**

修改 `src/graph_rag.py` 顶部 `from rag import (...)` 块，在 `_build_context` 之后增加 `enrich_context`：

```python
from rag import (
    build_bm25_index,
    build_index, ask_for_files, _collection_exists,
    add_files_to_index,
    retrieve_hybrid_with_sources, dynamic_top_k,
    answer_with_llm_history, format_sources,
    _build_context,
    enrich_context,              # ← 新增
    SentenceTransformer, chromadb,
    EMBEDDING_MODEL_NAME, DEFAULT_COLLECTION_NAME,
    DEFAULT_TOP_K, DEFAULT_MIN_K, DEFAULT_MAX_K,
    CHROMA_DB_PATH, DEFAULT_LLM_MODEL,
)
```

- [ ] **Step 2: 修改 `graph_query_stream` 函数**

在 `graph_query_stream` 函数体内（`top_indices = indices[:k]` 之后），将原来的两行替换为：

```python
    # 旧
    context = _build_context(top_indices, all_docs, all_metadatas)
    sources = format_sources(top_indices, all_docs, all_metadatas)

    # 新
    enriched_docs = enrich_context(top_indices, all_docs, all_metadatas)
    context = _build_context(top_indices, enriched_docs, all_metadatas)
    sources = format_sources(top_indices, enriched_docs, all_metadatas)
```

- [ ] **Step 3: 跑测试确认 Green**

```bash
cd /d/GitHub/mneme && python -m pytest tests/test_graph_rag_enrich.py::test_graph_query_stream_calls_enrich_context -v
```

预期：PASS

- [ ] **Step 4: 提交**

```bash
cd /d/GitHub/mneme
git add tests/test_graph_rag_enrich.py src/graph_rag.py
git commit -m "fix: integrate enrich_context into graph_query_stream"
```

---

### Task 3: 修复 `graph_rag_pipeline()` 公共 API 函数

**Files:**
- Modify: `src/graph_rag.py`（`graph_rag_pipeline` 函数体内第 446、455 行）

- [ ] **Step 1: 写失败测试**

在 `tests/test_graph_rag_enrich.py` 末尾追加：

```python
def test_graph_rag_pipeline_calls_enrich_context():
    """graph_rag_pipeline 调用 enrich_context 并传递 enrich 后的 docs"""
    all_docs = ["short anchor", "body text"]
    all_metas = [
        {"source": "a.pdf", "chunk_type": "anchor", "source_path": "/fake/a.pdf"},
        {"source": "a.pdf", "chunk_type": "body"},
    ]
    enriched_expected = ["full first page...", "body text"]

    with (
        patch("src.graph_rag.graph_augmented_retrieve") as mock_retrieve,
        patch("src.graph_rag.dynamic_top_k") as mock_top_k,
        patch("src.graph_rag.enrich_context") as mock_enrich,
        patch("src.graph_rag._build_context") as mock_build,
        patch("src.graph_rag.format_sources") as mock_sources,
        patch("src.graph_rag.answer_with_llm_history") as mock_answer,
        patch("src.graph_rag.prepare_graph_index") as mock_prepare,
        patch("time.time", return_value=0.0),   # 必须设返回值，否则 MagicMock 差值导致 int() TypeError
        patch("builtins.print"),                 # 消除函数内大量 print 对测试输出的噪音
    ):
        mock_retrieve.return_value = ([0, 1], all_docs, [0.9, 0.8])
        mock_top_k.return_value = 2
        mock_enrich.return_value = enriched_expected
        mock_answer.return_value = "mock answer"
        mock_prepare.return_value = (None, None, None, all_docs, all_metas, None)

        result = graph_rag_pipeline(
            ["/fake/test.pdf"], "test query",
        )

        # enrich_context 应被调用
        mock_enrich.assert_called_once_with([0, 1], all_docs, all_metas)

        # _build_context 应收到 enriched_docs
        mock_build.assert_called_once_with([0, 1], enriched_expected, all_metas)

        # format_sources 应收到 enriched_docs
        mock_sources.assert_called_once_with([0, 1], enriched_expected, all_metas)
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd /d/GitHub/mneme && python -m pytest tests/test_graph_rag_enrich.py::test_graph_rag_pipeline_calls_enrich_context -v
```

预期：FAIL

- [ ] **Step 3: 修改 `graph_rag_pipeline()`**

在 `graph_rag_pipeline` 函数体内，修改第 446 行和第 455 行：

```python
    # 旧（第 446 行）
    context = _build_context(top_indices, all_docs, all_metadatas)
    ...
    # 旧（第 455 行）
    sources = format_sources(top_indices, all_docs, all_metadatas)

    # 新
    enriched_docs = enrich_context(top_indices, all_docs, all_metadatas)
    context = _build_context(top_indices, enriched_docs, all_metadatas)
    ...
    sources = format_sources(top_indices, enriched_docs, all_metadatas)
```

- [ ] **Step 4: 跑测试确认 Green**

```bash
cd /d/GitHub/mneme && python -m pytest tests/test_graph_rag_enrich.py::test_graph_rag_pipeline_calls_enrich_context -v
```

预期：PASS

- [ ] **Step 5: 提交**

```bash
cd /d/GitHub/mneme
git add tests/test_graph_rag_enrich.py src/graph_rag.py
git commit -m "fix: integrate enrich_context into graph_rag_pipeline"
```

---

### Task 4: 修复 `--query` CLI 路径

**Files:**
- Modify: `src/graph_rag.py`（`main()` 内 `if args.query:` 分支，第 500、503 行）

- [ ] **Step 1: 写失败测试**

在 `tests/test_graph_rag_enrich.py` 末尾追加：

```python
def test_cli_query_calls_enrich_context():
    """main() 中 --query 参数路径调用 enrich_context"""
    all_docs = ["short anchor", "body text"]
    all_metas = [
        {"source": "a.pdf", "chunk_type": "anchor", "source_path": "/fake/a.pdf"},
        {"source": "a.pdf", "chunk_type": "body"},
    ]
    enriched_expected = ["full first page...", "body text"]

    with (
        patch("src.graph_rag.graph_augmented_retrieve") as mock_retrieve,
        patch("src.graph_rag.dynamic_top_k") as mock_top_k,
        patch("src.graph_rag.enrich_context") as mock_enrich,
        patch("src.graph_rag._build_context") as mock_build,
        patch("src.graph_rag.format_sources") as mock_sources,
        patch("src.graph_rag.answer_with_llm_history") as mock_answer,
        patch("src.graph_rag.prepare_graph_index") as mock_prepare,
        patch("builtins.exit") as mock_exit,     # main() 用内建 exit() 结束，非 sys.exit
        patch("time.time", return_value=0.0),    # 必须设返回值，否则 int() TypeError
        patch("builtins.print"),                 # 消除 main() 内 print 噪音
        patch("sys.argv", [
            "graph_rag.py",
            "--files", "/fake/test.pdf",         # 必须提供 --files，否则走 ask_for_files → exit(1)
            "--query", "test query",
        ]),
    ):
        mock_retrieve.return_value = ([0, 1], all_docs, [0.9, 0.8])
        mock_top_k.return_value = 2
        mock_enrich.return_value = enriched_expected
        mock_answer.return_value = "mock answer"
        mock_prepare.return_value = (None, None, None, all_docs, all_metas, None)
        # exit(0) 被 mock 接管，不真正退出进程
        mock_exit.side_effect = SystemExit(0)

        try:
            main()
        except SystemExit:
            pass

        # enrich_context 应被调用
        mock_enrich.assert_called_once_with([0, 1], all_docs, all_metas)

        # _build_context 应收到 enriched_docs
        mock_build.assert_called_once_with([0, 1], enriched_expected, all_metas)

        # format_sources 应收到 enriched_docs
        mock_sources.assert_called_once_with([0, 1], enriched_expected, all_metas)
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd /d/GitHub/mneme && python -m pytest tests/test_graph_rag_enrich.py::test_cli_query_calls_enrich_context -v
```

预期：FAIL

- [ ] **Step 3: 修改 `--query` CLI 路径**

在 `main()` 函数内 `if args.query:` 分支（`top_indices = indices[:k]` 之后），修改第 500 行和第 503 行：

```python
    # 旧（第 500 行）
    context = _build_context(top_indices, all_docs, all_metadatas)
    ...
    # 旧（第 503 行）
    sources = format_sources(top_indices, all_docs, all_metadatas)

    # 新
    enriched_docs = enrich_context(top_indices, all_docs, all_metadatas)
    context = _build_context(top_indices, enriched_docs, all_metadatas)
    ...
    sources = format_sources(top_indices, enriched_docs, all_metadatas)
```

- [ ] **Step 4: 跑测试确认 Green**

```bash
cd /d/GitHub/mneme && python -m pytest tests/test_graph_rag_enrich.py::test_cli_query_calls_enrich_context -v
```

预期：PASS

- [ ] **Step 5: 提交**

```bash
cd /d/GitHub/mneme
git add tests/test_graph_rag_enrich.py src/graph_rag.py
git commit -m "fix: integrate enrich_context into --query CLI path"
```

---

### Task 5: 修复交互式循环路径

**Files:**
- Modify: `src/graph_rag.py`（`main()` 内 `while True:` 分支，第 538、547 行）

- [ ] **Step 1: 写失败测试**

在 `tests/test_graph_rag_enrich.py` 末尾追加：

```python
def test_interactive_loop_calls_enrich_context():
    """main() 交互式循环调用 enrich_context"""
    all_docs = ["short anchor", "body text"]
    all_metas = [
        {"source": "a.pdf", "chunk_type": "anchor", "source_path": "/fake/a.pdf"},
        {"source": "a.pdf", "chunk_type": "body"},
    ]
    enriched_expected = ["full first page...", "body text"]

    with (
        patch("src.graph_rag.graph_augmented_retrieve") as mock_retrieve,
        patch("src.graph_rag.dynamic_top_k") as mock_top_k,
        patch("src.graph_rag.enrich_context") as mock_enrich,
        patch("src.graph_rag._build_context") as mock_build,
        patch("src.graph_rag.format_sources") as mock_sources,
        patch("src.graph_rag.answer_with_llm_history") as mock_answer,
        patch("src.graph_rag.prepare_graph_index") as mock_prepare,
        patch("builtins.input") as mock_input,   # input 是内建函数，graph_rag.py 无模块级引用
        patch("time.time", return_value=0.0),    # 必须设返回值，否则 int() TypeError
        patch("builtins.print"),                 # 消除 main() 内 print 噪音
        patch("sys.argv", [
            "graph_rag.py",
            "--files", "/fake/test.pdf",         # 绕过 ask_for_files，直接给文件
        ]),
    ):
        mock_retrieve.return_value = ([0, 1], all_docs, [0.9, 0.8])
        mock_top_k.return_value = 2
        mock_enrich.return_value = enriched_expected
        mock_answer.return_value = "mock answer"
        mock_prepare.return_value = (None, None, None, all_docs, all_metas, None)
        # 先发一个查询，再退出
        mock_input.side_effect = ["test query", "q"]

        main()

        # enrich_context 应被调用一次（查询时）
        mock_enrich.assert_called_once_with([0, 1], all_docs, all_metas)

        # _build_context 应收到 enriched_docs
        mock_build.assert_called_once_with([0, 1], enriched_expected, all_metas)

        # format_sources 应收到 enriched_docs
        mock_sources.assert_called_once_with([0, 1], enriched_expected, all_metas)
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd /d/GitHub/mneme && python -m pytest tests/test_graph_rag_enrich.py::test_interactive_loop_calls_enrich_context -v
```

预期：FAIL

- [ ] **Step 3: 修改交互式循环**

在 `main()` 函数内 `while True:` 分支（`top_indices = indices[:k]` 之后），修改第 538 行和第 547 行：

```python
    # 旧（第 538 行）
    context = _build_context(top_indices, all_docs, all_metadatas)
    ...
    # 旧（第 547 行）
    sources = format_sources(top_indices, all_docs, all_metadatas)

    # 新
    enriched_docs = enrich_context(top_indices, all_docs, all_metadatas)
    context = _build_context(top_indices, enriched_docs, all_metadatas)
    ...
    sources = format_sources(top_indices, enriched_docs, all_metadatas)
```

- [ ] **Step 4: 跑测试确认 Green**

```bash
cd /d/GitHub/mneme && python -m pytest tests/test_graph_rag_enrich.py::test_interactive_loop_calls_enrich_context -v
```

预期：PASS

- [ ] **Step 5: 提交**

```bash
cd /d/GitHub/mneme
git add tests/test_graph_rag_enrich.py src/graph_rag.py
git commit -m "fix: integrate enrich_context into interactive loop"
```

---

### Task 6: 回归测试

- [ ] **Step 1: 跑全部测试**

```bash
cd /d/GitHub/mneme && python -m pytest tests/ -v --tb=short 2>&1
```

预期：所有测试通过（0 failures）

- [ ] **Step 2: 确认老测试未被破坏**

重点关注：
- `tests/test_hierarchical_enrich.py` — enrich_context 原始功能测试
- `tests/test_graph_rag_batch.py` — graph_rag 原有测试
- `tests/test_retrieval_fix.py` — 检索修复测试

---

### Task 7: 更新 CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 追加变更记录**

在 `CHANGELOG.md` 中找到 `## [Unreleased]` 段（若无则新建），在其 `### Fixed` 小节下追加（若无 `Fixed` 则新建）：

```markdown
## [Unreleased]

### Fixed
- Graph RAG 模式集成 enrich_context，修复 PDF 元数据（作者、机构等）缩水问题
  - `graph_rag_pipeline()` 调用 enrich_context
  - `graph_query_stream()` 调用 enrich_context
  - 交互式循环调用 enrich_context
  - `--query` CLI 路径调用 enrich_context
```

- [ ] **Step 2: 提交**

```bash
cd /d/GitHub/mneme
git add CHANGELOG.md
git commit -m "chore: update CHANGELOG for enrich_context fix"
```
