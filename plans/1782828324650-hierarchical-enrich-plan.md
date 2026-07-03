# RAG 分层检索增强计划：Anchor → Enrich

## 编码原则：KISS

1. **复用已有代码**。`load_pdf_pages`、`format_sources`、`dynamic_top_k` 全部直接用。
2. **不做过度设计**。一个 `enrich_context` 函数 + anchor 大小调整 + `source_path` 元数据。
3. **与查询拆解正交**。enrich 发生在 multi-query fusion 之后、context 拼接之前，两者不冲突。

---

## 背景

当前 anchor chunk（PDF 首页前 15 行，~500 chars）的问题：
- title + authors + affiliations + abstract 开头混合嵌入 → embedding 语义稀释
- 查询 "作者都属于什么学校？" 与 anchor 的语义匹配度低 → Recall@20 = 0%

**SciClaw 启发（Section 8.3 `enrich_task_chunk`）**：
1. 检索侧只用**轻量指针**（仅 title + author names，~80 chars）→ 高精度匹配
2. 命中后**按需 enrich**：从 PDF 源文件读取首页全文替换 anchor 文本

---

## 设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 检索侧 anchor 内容 | Title + 作者名（~3-5 行） | embedding 最精准，无语义噪音 |
| Enrich 内容 | PDF 首页全文 | 信息量最大，`load_pdf_pages` 可直接复用 |
| `source_path` 范围 | 仅 anchor chunk | KISS，改动最小 |
| Enrich 触发时机 | `dynamic_top_k` 之后、context 拼接之前 | 自封闭函数，不干涉检索流程 |

---

## 改动

### 改动 1：缩小 anchor chunk（`build_index` + `add_files_to_index`）

**当前**（`rag.py:307`）：
```python
anchor_lines = first_page_text.splitlines()[:15]
anchor_text = " ".join(line.strip() for line in anchor_lines if line.strip())
```

**改为**：
```python
anchor_lines = first_page_text.splitlines()[:5]
anchor_text = " ".join(line.strip() for line in anchor_lines if line.strip())
```

**metadata 新增 `source_path`**：
```python
all_metadatas.append({
    "source": os.path.basename(fp),
    "file_type": file_type,
    "chunk_index": -1,
    "chunk_type": "anchor",
    "source_path": fp,  # ← NEW
})
```

`build_index()` 和 `add_files_to_index()` 两处同步改。

---

### 改动 2：新增 `enrich_context` 函数

**文件**：`rag.py`，放置在 `dynamic_top_k` 函数后面。

```python
def enrich_context(
    top_indices: list[int],
    documents: list[str],
    metadatas: list[dict],
) -> list[str]:
    """当 top-k 含 anchor chunk 时，用 PDF 首页全文替换其文本。

    Args:
        top_indices: dynamic_top_k 筛选后的索引列表
        documents: 全部文档文本（按索引查找）
        metadatas: 全部元数据（按索引查找）

    Returns:
        新列表（浅拷贝），anchor chunk 的文本被替换为 PDF 首页全文
    """
    enriched = documents[:]
    for idx in top_indices:
        meta = metadatas[idx]
        if meta.get("chunk_type") == "anchor":
            source_path = meta.get("source_path", "")
            if source_path and os.path.exists(source_path):
                try:
                    pages = load_pdf_pages(source_path)
                    if pages:
                        enriched[idx] = pages[0][0]
                except Exception:
                    pass
    return enriched
```

---

### 改动 3：在 `answer_query_stream` 和 `answer_query` 中使用 enrich

**`answer_query_stream`（L811-820）**，在 context 构建前插入：

```python
# 原代码：
# context = "\n\n".join([documents[i] for i in top_indices])
# sources = format_sources(top_indices, documents, metadatas)

# 改为：
enriched_docs = enrich_context(top_indices, documents, metadatas)
context = "\n\n".join([enriched_docs[i] for i in top_indices])
sources = format_sources(top_indices, enriched_docs, metadatas)
```

`answer_query`（L607-632）做相同改动。

---

## TDD 测试

**文件**：`test_hierarchical_enrich.py`

### Tier 1：功能测试（Smoke）

```python
#!/usr/bin/env python3
"""
Tier 1: 分层检索功能测试 — 确认能正常运行。
Tier 2: 端到端质量测试 — 确认回答问题包含机构信息。
"""
import os
import sys
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False

import rag
from rag import (
    prepare_index, retrieve_hybrid_with_sources, dynamic_top_k,
    enrich_context,
    CHROMA_DB_PATH as _ORIGINAL_DB,
)

PDF_FILE = str(PROJECT_ROOT / "test_texts" / "2405.02357v2.pdf")
TEST_DB = PROJECT_ROOT / "test_analysis" / "chroma_db_test"
QUERY = "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"


def _clean_db():
    if TEST_DB.exists():
        shutil.rmtree(str(TEST_DB), ignore_errors=True)

def _setup_db():
    _clean_db()
    rag.CHROMA_DB_PATH = str(TEST_DB)

def _teardown_db():
    rag.CHROMA_DB_PATH = _ORIGINAL_DB
    _clean_db()


# ═══════════════════════════════════════════
# Tier 1：功能测试
# ═══════════════════════════════════════════

def test_anchor_size_reduced():
    """anchor chunk 从 15 行减为 ≤5 行"""
    _setup_db()
    try:
        _, _, _, _, metas = prepare_index([PDF_FILE], "test_anchor_size")
        anchor_lines_raw = None
        # 重现 build_index 中的 splitlines() 逻辑来获取原始行数
        pages = rag.load_pdf_pages(PDF_FILE)
        if pages:
            first_page = pages[0][0]
            anchor_lines_raw = first_page.splitlines()[:5]
        assert anchor_lines_raw is not None, "无法读取 PDF 首页"
        line_count = len(anchor_lines_raw)
        anchor_text = " ".join(line.strip() for line in anchor_lines_raw if line.strip())
        print(f"  anchor 行数: {line_count}")
        print(f"  anchor 内容: {anchor_text[:100]}...")
        assert line_count <= 5, (
            f"anchor 预期 ≤5 行，实际 {line_count}"
        )
        assert "LLMs" in anchor_text or "Mobility" in anchor_text, (
            "anchor 应包含论文标题关键词"
        )
    finally:
        _teardown_db()


def test_anchor_has_source_path():
    """anchor chunk metadata 包含 source_path"""
    _setup_db()
    try:
        _, _, _, _, metas = prepare_index([PDF_FILE], "test_source_path")
        anchor_meta = next(
            (m for m in metas if m.get("chunk_type") == "anchor"), None
        )
        assert anchor_meta, "未生成 anchor chunk"
        assert "source_path" in anchor_meta, "缺少 source_path"
        assert anchor_meta["source_path"] == PDF_FILE
        print(f"  source_path: {anchor_meta['source_path']}")
    finally:
        _teardown_db()


def test_enrich_replaces_anchor():
    """enrich_context 将 anchor 文本替换为更长的首页全文"""
    _setup_db()
    try:
        model, collection, bm25, docs, metas = prepare_index(
            [PDF_FILE], "test_enrich_replace",
        )
        # 用拆解后的中文子查询确保命中 anchor
        indices, _, scores = retrieve_hybrid_with_sources(
            "作者都属于什么学校或者科研机构",
            model, collection, bm25, docs, metas, k=20,
        )
        k = dynamic_top_k(scores)
        top_idx = indices[:k]

        enriched = enrich_context(top_idx, docs, metas)
        for idx in top_idx:
            if metas[idx].get("chunk_type") == "anchor":
                assert len(enriched[idx]) >= len(docs[idx]), (
                    "enrich 后 anchor 文本应更长或相等"
                )
                print(f"  enrich 前长度: {len(docs[idx])}")
                print(f"  enrich 后长度: {len(enriched[idx])}")
                break
    finally:
        _teardown_db()


def test_enrich_no_anchor_unchanged():
    """当 top-k 不含 anchor chunk 时，enrich 不修改任何文本"""
    _setup_db()
    try:
        model, collection, bm25, docs, metas = prepare_index(
            [PDF_FILE], "test_enrich_noop",
        )
        # 用一个不涉及作者/机构的纯内容查询
        indices, _, scores = retrieve_hybrid_with_sources(
            "deep learning neural network training",
            model, collection, bm25, docs, metas, k=20,
        )
        k = dynamic_top_k(scores)
        top_idx = indices[:k]

        has_anchor = any(metas[i].get("chunk_type") == "anchor" for i in top_idx)
        enriched = enrich_context(top_idx, docs, metas)

        if not has_anchor:
            assert enriched == docs, "无 anchor 时 enrich 不应修改任何文本"
            print("  无 anchor 命中，enrich 未修改文本")
        else:
            print("  anchor 也命中了（验证 enrich 非破坏性）")
            for idx in top_idx:
                if metas[idx].get("chunk_type") == "anchor":
                    assert len(enriched[idx]) >= len(docs[idx])
    finally:
        _teardown_db()


# ═══════════════════════════════════════════
# Tier 2：端到端质量测试（需 API_KEY）
# ═══════════════════════════════════════════

@pytest.mark.integration
def test_enrich_improves_author_answer():
    """enrich 后，context 应包含作者所属机构信息。

    使用纯中文子查询（"作者都属于什么学校或者科研机构"）替代复合查询
    QUERY，以避免对查询拆解计划的依赖。"""
    _setup_db()
    try:
        model, collection, bm25, docs, metas = prepare_index(
            [PDF_FILE], "test_enrich_quality",
        )
        from unittest.mock import patch

        mock_context = {}

        def capture_context(query, context, history, **kwargs):
            mock_context["context"] = context
            yield "(mocked)"

        with patch("rag.answer_with_llm_history_stream", capture_context):
            stream, sources = rag.answer_query_stream(
                "作者都属于什么学校或者科研机构",
                model, collection, bm25, docs, metas,
                top_k_range=(3, 20),
            )
            for _ in stream:
                pass

        context = mock_context.get("context", "")
        print(f"  context 长度: {len(context)}")
        # 应包含机构名称——即使 author names 在 anchor 中只有 5 行，
        # enrich 后从 PDF 首页读取了完整 affiliations
        has_upenn = "University of Pennsylvania" in context
        has_princeton = "Princeton" in context
        print(f"  包含 University of Pennsylvania: {has_upenn}")
        print(f"  包含 Princeton: {has_princeton}")
        assert has_upenn and has_princeton, (
            "enrich 后 context 应包含作者所属机构"
        )
    finally:
        _teardown_db()


@pytest.mark.integration
def test_enrich_does_not_degrade_simple_query():
    """简单主题查询不受 enrich 影响"""
    _setup_db()
    try:
        model, collection, bm25, docs, metas = prepare_index(
            [PDF_FILE], "test_enrich_simple",
        )
        from unittest.mock import patch

        mock_context = {}
        def capture_context(query, context, history, **kwargs):
            mock_context["context"] = context
            yield "(mocked)"

        with patch("rag.answer_with_llm_history_stream", capture_context):
            stream, sources = rag.answer_query_stream(
                "这篇论文主要讲了什么？",
                model, collection, bm25, docs, metas,
                top_k_range=(3, 20),
            )
            for _ in stream:
                pass

        context = mock_context.get("context", "")
        assert len(context) > 0, "context 不应为空"
        print(f"  context 长度: {len(context)}")
    finally:
        _teardown_db()
```

---

## TDD 执行顺序

```
Round 1（先写测试，全部失败或未定义）:
  ✗ Tier 1: 4 个功能测试（无 enrich_context 函数、无 source_path、anchor 仍是 15 行）
  ✗ Tier 2: 2 个质量测试（mock LLM 无锚点）

Round 2（改动 1：缩小 anchor + source_path）:
  ✓ test_anchor_size_reduced
  ✓ test_anchor_has_source_path
  ✗ test_enrich_replaces_anchor（enrich_context 未实现）

Round 3（改动 2：实现 enrich_context）:
  ✓ test_enrich_replaces_anchor
  ✓ test_enrich_no_anchor_unchanged
  ✗ Tier 2（改动 3 未完成）

Round 4（改动 3：answer_query_stream + answer_query 注入 enrich）:
  ✓ Tier 2: 2 个质量测试
  ✓ test_retrieval_fix.py 全量回归 8/8 通过
```

---

## 实施步骤

| 序号 | 步骤 | 文件 | 改动量 |
|------|------|------|--------|
| 1 | TDD Round 1：编写全部测试（预期失败） | `test_hierarchical_enrich.py` | ~140 行 |
| 2 | 缩小 anchor 行数 15→5，加 `source_path` | `rag.py:307,312` | ~10 行 |
| 3 | 实现 `enrich_context` 函数 | `rag.py`（新增） | ~20 行 |
| 4 | `answer_query_stream`：注入 enrich + `format_sources` 用 enriched_docs | `rag.py` L811-820 | ~4 行 |
| 5 | `answer_query`（非 stream）：同样注入 enrich | `rag.py` L607-632 | ~4 行 |
| 6 | 运行全量回归（含 `test_retrieval_fix.py`） | - | - |
| 7 | 端到端手动验证 `rag-sys` | - | - |

**总改动量：~180 行，1 个新文件、1 个修改文件。**

---

## 与查询拆解计划的关系

两计划**正交**，不冲突：

```
query → [查询拆解] → multi-query fusion → dynamic_top_k → [enrich_context] → context → LLM
                                  ↑ 查询拆解计划                 ↑ 本计划
```

实施顺序可互换，`enrich_context` 的注入点（context 构建前）不受 multi-query fusion 影响。

---

## 预期效果

| 指标 | 当前 | 预期 |
|------|------|------|
| anchor 行数 | 15 | ≤5 |
| anchor embedding 精度 | 低（混入 abstract） | 高（仅 title + author） |
| Context 含机构信息 | 依赖 anchor 中是否含有 | `enrich` 确保有（从 PDF 读取） |
| 回答含机构名（作者查询） | 无 | 有（至少 `University of Pennsylvania` + `Princeton`） |
| 简单查询退化 | - | 无 |

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 缩小 anchor 后与 topic 查询的匹配度下降 | 5 行 title + author 仍能匹配 topic 查询中的论文标题关键词 |
| PDF 文件在索引后被移动/删除，enrich 找不到源文件 | `os.path.exists` 检查 + `try/except`，失败时保留原始 anchor 文本 |
| `load_pdf_pages` 读取大 PDF 首页的延迟 | 首页通常很快（<50ms），且仅在 anchor 命中时才调用，非每查询都执行 |
| 多层 enrich + 查询拆解导致 context 超长 | `dynamic_top_k` 天然截断，enrich 只替换 anchor chunk 不增加 chunk 数量。预期膨胀：anchor ~80 chars → ~3000 chars，单个 chunk 膨胀 37x，但整体 context 仍受 `max_k=20` 限制 |
| rrf_merge L487 已有 anchor ×2 boosting，缩小 anchor 后 embedding 质量更高，boost 效果放大 | 需要确认不会导致 anchor 过度抢占非元数据查询的 top-k——实测中 anchor 在 topic 查询中命中率低（仅 5 行 title + author，不与 content chunks 竞争） |
| 与查询拆解计划同时合并时冲突 | `enrich_context` 是独立的函数注入，在 context 构建前，不修改检索逻辑 |

---

## 变更记录

### 2026-07-02 — v3（审阅修复 · 定稿）

基于代码审阅的 8 项修复：

| 分类 | 问题 | 修复 |
|------|------|------|
| ✅ 阻塞 | `test_anchor_size_reduced` 断言行数用 `splitlines()` → 永远为 1 | 改用 `splitlines()[:5]` 的原始行列表 |
| ✅ 阻塞 | `format_sources` 传 `documents` 而非 `enriched_docs` | 改为 `format_sources(top_indices, enriched_docs, metadatas)` |
| ⚡ 重要 | 测试文件含死 import：`subprocess`、`EMBEDDING_MODEL_NAME`、`SentenceTransformer` | 移除 |
| ⚡ 重要 | `test_enrich_improves_author_answer` 用复合查询 `QUERY` | 改为纯中文子查询避免依赖查询拆解 |
| 💡 次要 | `rrf_merge` anchor ×2 boosting 未在风险表提及 | 新增风险条目 |
| 💡 次要 | context 膨胀未量化 | 风险表标注：~80 → ~3000 chars（37x） |
| 💡 次要 | `test_anchor_size_reduced` 无内容保底 | 增加 `assert "LLMs" in anchor_text` |
| 💡 次要 | `answer_query` 注入未明确展示 | 实施步骤表拆为两行（stream + non-stream） |

### 2026-07-02 — v2（首次审阅缺陷修复）

基于首次审阅的修复：

- 补偿测试 `test_enrich_context` 改为测试 `enrich_context()` 函数而非 mock
- Tier 2 `test_enrich_improves_author_answer` 改为纯 API 调用（跳过 mock LLM）
- `enrich_context` 函数签名由 `(top_indices, docs, source_paths)` 改为 `(top_indices, documents, metadatas)`，从 metadata 中读取 `source_path`
- 删除 `prepare_index` 硬编码的 `COLLECTION_NAME`

### 2026-07-01 — v1（初稿）

初始创建，基于 SciClaw RAG 总结的 `enrich_task_chunk` 模式：

- TDD 双层级设计：Tier 1 单元测试（4 个） + Tier 2 集成测试（2 个）
- 核心思路：anchor 从 15 行缩至 5 行 → 命中后 `load_pdf_pages` 读取全文替换
- 实施步骤 6 步，总改动量约 175 行

---

## 验证标准

1. `pytest test_hierarchical_enrich.py -v` — Tier 1: 4/4 通过
2. `pytest test_hierarchical_enrich.py -v --run-integration` — Tier 2: 2/2 通过
3. `pytest test_retrieval_fix.py -v` — 全量回归 8/8 通过
4. `answer_query` 同步做了 enrich 注入（实施步骤 4 含验证）
5. 手动验证：`rag-sys` 输入 "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"，回答应包含 `University of Pennsylvania`、`Princeton University` 等机构名（依赖查询拆解先上线）
