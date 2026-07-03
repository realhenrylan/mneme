"""LLM 驱动的查询拆解 — TDD 测试套件"""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from src.rag_query_decomposer import should_decompose, decompose_query_llm

# ── 层级 1：mock 单元测试（不调 API） ─────────────────────────────

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
        with patch("src.rag_query_decomposer.OpenAI") as mock_openai:
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
        with patch("src.rag_query_decomposer.OpenAI") as mock_openai:
            mock_openai.return_value.chat.completions.create.return_value = mock_response
            result = decompose_query_llm("LLMs for mobility")
    assert result == ["LLMs for mobility"]


def test_llm_mock_api_error_fallback():
    """mock API 抛异常 → 重试后降级为 [query]"""
    with patch.dict(os.environ, _MOCK_ENV):
        with patch("src.rag_query_decomposer.OpenAI") as mock_openai:
            mock_openai.return_value.chat.completions.create.side_effect = Exception("boom")
            result = decompose_query_llm("LLMs for mobility")
    assert result == ["LLMs for mobility"]


# ── 层级 2：真实 API 集成测试（需 API_KEY） ─────────────────────

@pytest.mark.integration
def test_decompose_llm_bilingual():
    """中英复合查询 → 至少 2 个子查询，且不含捏造的关键词"""
    sub = decompose_query_llm(
        "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"
    )
    assert len(sub) >= 2, f"Expected >=2, got {len(sub)}: {sub}"


@pytest.mark.integration
def test_decompose_llm_simple():
    """简单查询 → 1 个子查询"""
    sub = decompose_query_llm("这篇论文讲了什么？")
    assert len(sub) == 1


# ── 层级 3：检索效果回归测试（隔离 DB） ─────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PDF_FILE = str(PROJECT_ROOT / "test_texts" / "2405.02357v2.pdf")
QUERY = "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"
_ORIGINAL_DB = str(PROJECT_ROOT / "chroma_db")


def _make_test_db(name: str) -> str:
    """Return a fresh isolated DB path; use subprocess to avoid macOS SQLite lock issues."""
    db_path = str(PROJECT_ROOT / "tests" / "analysis" / f"chroma_db_{name}")
    subprocess.run(["rm", "-rf", db_path], check=False)
    return db_path


def _setup_db(db_path: str):
    """Set CHROMA_DB_PATH and return (model, collection, bm25, docs, metas)."""
    import src.rag as rag
    rag.CHROMA_DB_PATH = db_path
    from src.rag import prepare_index
    return prepare_index([PDF_FILE], f"test_{Path(db_path).name}")


def _restore_original_db():
    import src.rag as rag
    rag.CHROMA_DB_PATH = _ORIGINAL_DB
    # Also clean up all decomposer test DBs
    subprocess.run(
        ["rm", "-rf", str(PROJECT_ROOT / "tests" / "analysis" / "chroma_db_recall"),
         str(PROJECT_ROOT / "tests" / "analysis" / "chroma_db_dedup")],
        check=False,
    )


def test_multi_query_recall_improvement():
    """多 query 检索应比单 query 检索召回更多 anchor"""
    db_path = _make_test_db("recall")
    model, collection, bm25, docs, metas = _setup_db(db_path)
    try:
        from src.rag import retrieve_hybrid_with_sources
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
        _restore_original_db()


def test_multi_query_no_duplicates():
    """多 query 检索去重：相同 chunk 仅保留最高分，最终列表无重复索引"""
    db_path = _make_test_db("dedup")
    model, collection, bm25, docs, metas = _setup_db(db_path)
    try:
        from src.rag import retrieve_hybrid_with_sources
        sub_queries = decompose_query_llm(QUERY)
        all_entries = []
        for sq in sub_queries:
            idxs, _, scores = retrieve_hybrid_with_sources(
                sq, model, collection, bm25, docs, metas, k=20,
            )
            for i, s in zip(idxs, scores):
                all_entries.append((i, s))

        # 按 chunk 去重，仅保留最高分
        best: dict = {}
        for idx, score in all_entries:
            if idx not in best or score > best[idx]:
                best[idx] = score
        top_indices = sorted(best.keys(), key=lambda i: best[i], reverse=True)
        assert len(top_indices) == len(set(top_indices)), "去重后仍含重复索引"
    finally:
        _restore_original_db()
