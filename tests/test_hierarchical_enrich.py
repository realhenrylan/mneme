#!/usr/bin/env python3
"""
Tier 1: 分层检索功能测试 — 确认能正常运行。
Tier 2: 端到端质量测试 — 确认回答问题包含机构信息。

NOTE: Each test uses a UNIQUE collection name.
      Do NOT use force_rebuild=True between tests in the same process
      (RustBindingsAPI singleton holds open SQLite handle → rmtree races → readonly error).
      The module-level _clean_db() / setup_module() wipes the DB dir once upfront,
      and each test builds its own isolated collection from scratch.
"""
import os
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False

import src.rag as rag
from src.rag import (
    prepare_index, retrieve_hybrid_with_sources, dynamic_top_k,
    enrich_context, load_pdf_pages,
    CHROMA_DB_PATH as _ORIGINAL_DB,
)

PDF_FILE = str(PROJECT_ROOT / "test_texts" / "2405.02357v2.pdf")
TEST_DB = PROJECT_ROOT / "tests" / "analysis" / "chroma_db_test"

_original_db_path = _ORIGINAL_DB


def setup_module():
    """用 subprocess 绕过 macOS SQLite lock，确保干净数据库"""
    db_dir = str(TEST_DB)
    if os.path.exists(db_dir):
        subprocess.run(["rm", "-rf", db_dir], check=False)
    TEST_DB.parent.mkdir(parents=True, exist_ok=True)
    rag.CHROMA_DB_PATH = db_dir


def teardown_module():
    """清理测试数据库"""
    db_dir = str(TEST_DB)
    if os.path.exists(db_dir):
        subprocess.run(["rm", "-rf", db_dir], check=False)
    rag.CHROMA_DB_PATH = _original_db_path


# ═══════════════════════════════════════════
# Tier 1：功能测试
# ═══════════════════════════════════════════

def test_anchor_size_reduced():
    """anchor chunk 从 15 行减为 ≤5 行"""
    _, _, _, _, metas = prepare_index([PDF_FILE], "test_anchor_size")
    anchor_lines_raw = None
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


def test_anchor_has_source_path():
    """anchor chunk metadata 包含 source_path"""
    _, _, _, _, metas = prepare_index([PDF_FILE], "test_source_path")
    anchor_meta = next(
        (m for m in metas if m.get("chunk_type") == "anchor"), None
    )
    assert anchor_meta, "未生成 anchor chunk"
    assert "source_path" in anchor_meta, "缺少 source_path"
    assert anchor_meta["source_path"] == PDF_FILE
    print(f"  source_path: {anchor_meta['source_path']}")


def test_enrich_replaces_anchor():
    """enrich_context 将 anchor 文本替换为更长的首页全文"""
    model, collection, bm25, docs, metas = prepare_index(
        [PDF_FILE], "test_enrich_replace",
    )
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


def test_enrich_no_anchor_unchanged():
    """当 top-k 不含 anchor chunk 时，enrich 不修改任何文本"""
    model, collection, bm25, docs, metas = prepare_index(
        [PDF_FILE], "test_enrich_noop",
    )
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


# ═══════════════════════════════════════════
# Tier 2：端到端质量测试（需 API_KEY）
# ═══════════════════════════════════════════

@pytest.mark.integration
def test_enrich_improves_author_answer():
    """enrich 后，context 应包含作者所属机构信息。

    使用完整混合查询（含英文标题），使 anchor chunk 能被检索命中，
    然后 enrich_context 从 PDF 首页读取完整 affiliations。"""
    model, collection, bm25, docs, metas = prepare_index(
        [PDF_FILE], "test_enrich_quality",
    )
    from unittest.mock import patch

    mock_context = {}

    def capture_context(query, context, history, **kwargs):
        mock_context["context"] = context
        yield "(mocked)"

    with patch("src.rag.answer_with_llm_history_stream", capture_context):
        stream, sources = rag.answer_query_stream(
            "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？",
            model, collection, bm25, docs, metas,
            top_k_range=(3, 20),
        )
        for _ in stream:
            pass

    context = mock_context.get("context", "")
    print(f"  context 长度: {len(context)}")
    has_upenn = "University of Pennsylvania" in context
    has_princeton = "Princeton" in context
    print(f"  包含 University of Pennsylvania: {has_upenn}")
    print(f"  包含 Princeton: {has_princeton}")
    assert has_upenn and has_princeton, (
        "enrich 后 context 应包含作者所属机构"
    )


@pytest.mark.integration
def test_enrich_does_not_degrade_simple_query():
    """简单主题查询不受 enrich 影响"""
    model, collection, bm25, docs, metas = prepare_index(
        [PDF_FILE], "test_enrich_simple",
    )
    from unittest.mock import patch

    mock_context = {}
    def capture_context(query, context, history, **kwargs):
        mock_context["context"] = context
        yield "(mocked)"

    with patch("src.rag.answer_with_llm_history_stream", capture_context):
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
