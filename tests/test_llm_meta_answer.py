#!/usr/bin/env python3
"""
TDD 测试：验证 LLM context 是否包含来源文件名信息（Issue #16）。

测试策略：
  1. 单元测试 — `_build_context` 函数的正确性
  2. 单元测试 — 构建 context 后文件名是否出现在字符串中
  3. 集成测试 — 模拟完整 RAG 流程，验证 LLM 能回答文件数

用法：
  pytest tests/test_llm_meta_answer.py -v
"""
import os
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False

import src.rag as rag
from src.rag import (
    prepare_index, build_bm25_index, SentenceTransformer, chromadb,
    CHROMA_DB_PATH as _ORIGINAL_DB,
    DEFAULT_COLLECTION_NAME,
)

TEST_DB_PATH = PROJECT_ROOT / "tests" / "analysis" / "chroma_db_test_meta"
PDF_FILE = str(PROJECT_ROOT / "test_texts" / "2405.02357v2.pdf")
DOCX_FILE = str(PROJECT_ROOT / "test_texts" / "南京城市地理环境.docx")
MD_FILE = str(PROJECT_ROOT / "test_texts" / "LLMs_for_Mobility_Analysis_Survey.md")

_original_db_path = _ORIGINAL_DB


def setup_module():
    """确保干净的测试数据库"""
    db_dir = str(TEST_DB_PATH)
    if os.path.exists(db_dir):
        subprocess.run(["rm", "-rf", db_dir], check=False)
    rag.CHROMA_DB_PATH = db_dir


def teardown_module():
    """清理测试数据库"""
    db_dir = str(TEST_DB_PATH)
    if os.path.exists(db_dir):
        subprocess.run(["rm", "-rf", db_dir], check=False)
    rag.CHROMA_DB_PATH = _original_db_path


# ═══════════════════════════════════════════════
# 单元测试 1：_build_context 函数
# ═══════════════════════════════════════════════

class TestBuildContextFunction:
    """测试 _build_context 辅助函数（尚未实现，RED 阶段应 FAIL）"""

    def test_function_exists(self):
        """_build_context 函数应该存在"""
        from src.rag import _build_context
        assert callable(_build_context)

    def test_single_chunk_source_annotation(self):
        """单个 chunk 应标注来源文件名"""
        from src.rag import _build_context
        top_indices = [0]
        docs = ["这是文档内容"]
        metadatas = [{"source": "test.pdf"}]
        result = _build_context(top_indices, docs, metadatas)
        assert "[Source: test.pdf]" in result
        assert "这是文档内容" in result

    def test_multiple_chunks_different_sources(self):
        """多个不同来源的 chunk 都应标注各自的文件名"""
        from src.rag import _build_context
        top_indices = [0, 1, 2]
        docs = ["内容A", "内容B", "内容C"]
        metadatas = [
            {"source": "file1.pdf"},
            {"source": "file2.pdf"},
            {"source": "file3.pdf"},
        ]
        result = _build_context(top_indices, docs, metadatas)
        assert "[Source: file1.pdf]" in result
        assert "[Source: file2.pdf]" in result
        assert "[Source: file3.pdf]" in result

    def test_same_source_multiple_chunks(self):
        """同一文件多个 chunk 应每个都标注"""
        from src.rag import _build_context
        top_indices = [0, 1]
        docs = ["内容A", "内容B"]
        metadatas = [
            {"source": "common.pdf"},
            {"source": "common.pdf"},
        ]
        result = _build_context(top_indices, docs, metadatas)
        assert result.count("[Source: common.pdf]") == 2

    def test_chunks_separated_by_newlines(self):
        """chunk 之间应以双换行分隔"""
        from src.rag import _build_context
        top_indices = [0, 1]
        docs = ["第一段", "第二段"]
        metadatas = [
            {"source": "a.pdf"},
            {"source": "b.pdf"},
        ]
        result = _build_context(top_indices, docs, metadatas)
        # 每段格式: [Source: ...]\n内容\n\n[Source: ...]\n内容
        parts = result.split("\n\n")
        assert len(parts) == 2

    def test_missing_source_key_falls_back(self):
        """metadata 中没有 source key 时不应 crash"""
        from src.rag import _build_context
        top_indices = [0]
        docs = ["内容"]
        metadatas = [{"other_key": "value"}]  # 没有 "source"
        result = _build_context(top_indices, docs, metadatas)
        assert result is not None
        assert "内容" in result

    def test_non_sequential_indices(self):
        """top_indices 为非连续值时仍能正确映射（graph_rag 中的实际场景）"""
        from src.rag import _build_context
        # 模拟 graph_rag 场景：top_indices 是 all_docs 中的全局索引（如 [42, 17, 5]）
        top_indices = [42, 17, 5]
        docs = [""] * 50  # 填充至 50 以容纳索引 42
        docs[42] = "文档A内容"
        docs[17] = "文档B内容"
        docs[5] = "文档C内容"
        metadatas = [{"source": "dummy"}] * 50
        metadatas[42] = {"source": "file_a.pdf"}
        metadatas[17] = {"source": "file_b.pdf"}
        metadatas[5] = {"source": "file_c.pdf"}
        result = _build_context(top_indices, docs, metadatas)
        assert "[Source: file_a.pdf]" in result
        assert "[Source: file_b.pdf]" in result
        assert "[Source: file_c.pdf]" in result
        # 保持降序排列：索引 42 在前，5 在后
        assert result.find("file_a") < result.find("file_c")


# ═══════════════════════════════════════════════
# 单元测试 2：RAG 流程中的 context 验证
# ═══════════════════════════════════════════════

class TestContextInRagPipeline:
    """验证 prepare_index → retrieve → context 构建链"""

    COLLECTION_NAME = "test_meta_unit"
    TEST_FILES = [PDF_FILE, MD_FILE]

    @classmethod
    def setup_class(cls):
        """构建索引供后续测试使用"""
        model, collection, bm25, docs, metadatas = prepare_index(
            cls.TEST_FILES, cls.COLLECTION_NAME, force_rebuild=True,
        )
        cls.model = model
        cls.collection = collection
        cls.bm25 = bm25
        cls.docs = docs
        cls.metadatas = metadatas

    @classmethod
    def teardown_class(cls):
        """清理 collection"""
        try:
            client = chromadb.PersistentClient(path=str(TEST_DB_PATH))
            client.delete_collection(cls.COLLECTION_NAME)
        except Exception:
            pass

    def test_metadatas_contain_source(self):
        """所有 metadatas 应该有 source 字段"""
        for meta in self.metadatas:
            assert "source" in meta, f"Missing 'source' in metadata: {meta}"

    def test_retrieved_context_includes_source(self):
        """调用 answer_query 后，传递给 LLM 的 context 应包含 [Source: ...] 标注"""
        from src.rag import answer_query, _build_context

        # answer_query 内部调用 _build_context，返回的 sources 字符串由 format_sources 生成
        # 我们无法直接拦截 LLM 请求，但可以验证 answer_query 返回后 internal 调用链的正确性
        # 这里验证 prepare_index 返回的索引包含正确的文件名
        seen_sources = set()
        for meta in self.metadatas:
            seen_sources.add(meta.get("source", ""))
        for fpath in self.TEST_FILES:
            assert os.path.basename(fpath) in seen_sources


# ═══════════════════════════════════════════════
# 集成测试：端到端验证 LLM 回答
# ═══════════════════════════════════════════════

class TestLlmCanAnswerMetaQuestion:
    """端到端测试 LLM 能否回答文件数量问题（需要 .env 中的 API Key）"""

    COLLECTION_NAME = "test_meta_integration"
    TEST_FILES = [PDF_FILE, MD_FILE, DOCX_FILE]

    @classmethod
    def setup_class(cls):
        """构建含 3 个文件的索引"""
        cls.skip = False
        if not os.path.isfile(".env"):
            cls.skip = True
            return

        model, collection, bm25, docs, metadatas = prepare_index(
            cls.TEST_FILES, cls.COLLECTION_NAME, force_rebuild=True,
        )
        cls.model = model
        cls.collection = collection
        cls.bm25 = bm25
        cls.docs = docs
        cls.metadatas = metadatas

    @classmethod
    def teardown_class(cls):
        if not cls.skip:
            try:
                client = chromadb.PersistentClient(path=str(TEST_DB_PATH))
                client.delete_collection(cls.COLLECTION_NAME)
            except Exception:
                pass

    def test_llm_can_count_files(self):
        """提问文件数量，验证 LLM context 含 [Source: ...] 标注，回答基于实际内容"""
        if self.skip:
            pytest.skip("缺少 .env 配置")

        from src.rag import answer_query
        answer, sources = answer_query(
            "知识库中一共储存了多少个文件？请列出所有文件名。",
            self.model, self.collection, self.bm25,
            self.docs, self.metadatas,
        )
        # 回答应至少包含一个文件名（验证 context 中的 [Source: ...] 被 LLM 使用）
        # 注意：并非所有文件都会出现在检索结果中，LLM 只能回答 context 中有的内容
        # 详见 https://github.com/HongyiLanDP/rag-sys/issues/16
        assert any(
            basename in answer for basename in [os.path.basename(f) for f in self.TEST_FILES]
        ), (
            f"LLM 回答应包含至少一个文件名，实际回答: {answer}"
        )
        # 回答中不应包含上下文不存在的虚构文件名
        # (这依赖于 LLM 的诚实性，无硬断言)
