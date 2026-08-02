"""测试 2.2 Parent-Child/邻接扩展。"""

import pytest
from src.domain import Chunk, Document, Section, SectionType
from src.chunking import (
    chunk_document, expand_with_parent, expand_with_adjacent,
    MAX_PARENT_CHUNK_CHARS,
)


def _make_doc(sections=None, file_type="text") -> Document:
    return Document(
        source_id="test123",
        source_path="/test/doc.txt",
        source_name="doc.txt",
        file_type=file_type,
        sections=sections if sections is not None else [
            Section(section_type=SectionType.PARAGRAPH, text="Short paragraph."),
        ],
    )


def _make_metadatas(n: int, source_id="src1", parent_ids=None) -> list[dict]:
    """创建 n 个测试用元数据。"""
    metadatas = []
    for i in range(n):
        meta = {
            "chunk_id": f"src1_chunk_{i}",
            "chunk_index": i,
            "source_id": source_id,
            "source_name": "doc.txt",
            "section_heading": "",
            "section_type": "paragraph",
        }
        if parent_ids and i in parent_ids:
            meta["chunk_type"] = "child"
            meta["parent_chunk_id"] = parent_ids[i]
        metadatas.append(meta)
    return metadatas


# ═══════════════════════════════════════════════════════════════
# Parent-Chunk 创建测试
# ═══════════════════════════════════════════════════════════════

class TestParentChunkCreation:
    def test_short_section_no_parent(self):
        """短 Section 不创建 parent chunk。"""
        doc = _make_doc(sections=[
            Section(section_type=SectionType.PARAGRAPH, text="Short text."),
        ])
        chunks = chunk_document(doc)
        # 没有 parent/child 标记
        assert all(c.metadata.get("chunk_type") is None for c in chunks)

    def test_long_section_creates_parent_and_children(self):
        """超长 Section 创建 parent + child chunks。"""
        long_text = "Word " * 200  # ~1000 chars, exceeds pdf chunk_size=400
        doc = _make_doc(sections=[
            Section(section_type=SectionType.PARAGRAPH, text=long_text),
        ], file_type="pdf")
        chunks = chunk_document(doc)
        # 应有 parent chunk
        parents = [c for c in chunks if c.metadata.get("chunk_type") == "parent"]
        children = [c for c in chunks if c.metadata.get("chunk_type") == "child"]
        assert len(parents) == 1
        assert len(children) >= 2
        # parent 文本 = 完整 Section 文本
        assert parents[0].text == long_text
        # children 都指向 parent
        for child in children:
            assert child.parent_chunk_id == parents[0].chunk_id

    def test_very_long_section_no_parent(self):
        """超长 Section（超过 MAX_PARENT_CHUNK_CHARS）不创建 parent chunk。"""
        very_long = "A " * (MAX_PARENT_CHUNK_CHARS + 100)
        doc = _make_doc(sections=[
            Section(section_type=SectionType.PARAGRAPH, text=very_long),
        ], file_type="pdf")
        chunks = chunk_document(doc)
        parents = [c for c in chunks if c.metadata.get("chunk_type") == "parent"]
        # 超过 MAX_PARENT_CHUNK_CHARS，不创建 parent
        assert len(parents) == 0
        # 但仍有 child chunks
        children = [c for c in chunks if c.metadata.get("chunk_type") == "child"]
        assert len(children) >= 2
        # child 没有 parent_chunk_id
        for child in children:
            assert child.parent_chunk_id is None

    def test_multiple_sections_each_get_parent(self):
        """多个超长 Section 各自创建 parent。"""
        long1 = "Section1 " * 100  # ~900 chars
        long2 = "Section2 " * 100
        doc = _make_doc(sections=[
            Section(section_type=SectionType.PARAGRAPH, text=long1),
            Section(section_type=SectionType.PARAGRAPH, text=long2),
        ], file_type="pdf")
        chunks = chunk_document(doc)
        parents = [c for c in chunks if c.metadata.get("chunk_type") == "parent"]
        assert len(parents) == 2


# ═══════════════════════════════════════════════════════════════
# expand_with_parent 测试
# ═══════════════════════════════════════════════════════════════

class TestExpandWithParent:
    def test_no_child_chunks_passthrough(self):
        """无 child chunk 时直接传递。"""
        docs = ["text1", "text2"]
        metas = _make_metadatas(2)
        result, info = expand_with_parent([0, 1], docs, metas, context_k=5)
        assert result == [0, 1]

    def test_child_replaced_by_parent(self):
        """child chunk 被替换为 parent chunk。"""
        docs = ["parent_text", "child1_text", "child2_text", "other_text"]
        metas = [
            {"chunk_id": "src1_chunk_0", "chunk_index": 0, "source_id": "s1",
             "chunk_type": "parent", "source_name": "doc.txt"},
            {"chunk_id": "src1_chunk_1", "chunk_index": 1, "source_id": "s1",
             "chunk_type": "child", "parent_chunk_id": "src1_chunk_0", "source_name": "doc.txt"},
            {"chunk_id": "src1_chunk_2", "chunk_index": 2, "source_id": "s1",
             "chunk_type": "child", "parent_chunk_id": "src1_chunk_0", "source_name": "doc.txt"},
            {"chunk_id": "src1_chunk_3", "chunk_index": 3, "source_id": "s1",
             "source_name": "doc.txt"},
        ]
        # 召回 child1 和 other
        result, info = expand_with_parent([1, 3], docs, metas, context_k=5)
        # child1 → parent (index 0), other 不变
        assert 0 in result  # parent 替换了 child
        assert 3 in result  # other 不变
        assert 1 not in result  # child 被替换
        assert 2 not in result  # 同 parent 的另一个 child 不重复

    def test_multiple_children_same_parent_dedup(self):
        """多个 child 指向同一 parent 时只保留一个 parent。"""
        docs = ["parent", "child1", "child2"]
        metas = [
            {"chunk_id": "p0", "chunk_index": 0, "source_id": "s1", "chunk_type": "parent", "source_name": "doc.txt"},
            {"chunk_id": "c1", "chunk_index": 1, "source_id": "s1", "chunk_type": "child", "parent_chunk_id": "p0", "source_name": "doc.txt"},
            {"chunk_id": "c2", "chunk_index": 2, "source_id": "s1", "chunk_type": "child", "parent_chunk_id": "p0", "source_name": "doc.txt"},
        ]
        result, info = expand_with_parent([1, 2], docs, metas, context_k=5)
        # 两个 child 都指向 p0，只保留一个 parent
        assert result.count(0) == 1

    def test_context_k_limit(self):
        """扩展后不超过 context_k。"""
        docs = ["p0", "c1", "c2", "other"]
        metas = [
            {"chunk_id": "p0", "chunk_index": 0, "source_id": "s1", "chunk_type": "parent", "source_name": "doc.txt"},
            {"chunk_id": "c1", "chunk_index": 1, "source_id": "s1", "chunk_type": "child", "parent_chunk_id": "p0", "source_name": "doc.txt"},
            {"chunk_id": "c2", "chunk_index": 2, "source_id": "s1", "chunk_type": "child", "parent_chunk_id": "p0", "source_name": "doc.txt"},
            {"chunk_id": "o3", "chunk_index": 3, "source_id": "s1", "source_name": "doc.txt"},
        ]
        result, info = expand_with_parent([1, 2, 3], docs, metas, context_k=2)
        assert len(result) <= 2

    def test_child_without_parent_id_passthrough(self):
        """child 没有 parent_chunk_id 时直接传递。"""
        docs = ["child_no_parent"]
        metas = [
            {"chunk_id": "c0", "chunk_index": 0, "source_id": "s1",
             "chunk_type": "child", "source_name": "doc.txt"},
        ]
        result, info = expand_with_parent([0], docs, metas, context_k=5)
        assert result == [0]


# ═══════════════════════════════════════════════════════════════
# expand_with_adjacent 测试
# ═══════════════════════════════════════════════════════════════

class TestExpandWithAdjacent:
    def test_no_expand(self):
        """max_expand=0 时不扩展。"""
        metas = _make_metadatas(5)
        result = expand_with_adjacent([2], metas, max_expand=0)
        assert result == [2]

    def test_expand_prev_and_next(self):
        """扩展前后各 1 个相邻 chunk。"""
        metas = _make_metadatas(5)
        result = expand_with_adjacent([2], metas, max_expand=2)
        # 应包含 chunk 1, 2, 3
        assert 2 in result  # 原始
        assert 1 in result  # 前一个
        assert 3 in result  # 后一个

    def test_expand_at_boundary(self):
        """chunk_index=0 时没有前一个 chunk。"""
        metas = _make_metadatas(3)
        result = expand_with_adjacent([0], metas, max_expand=2)
        assert 0 in result
        assert 1 in result  # 后一个
        # chunk_index=-1 不存在，所以没有前一个

    def test_expand_at_end(self):
        """最后一个 chunk 没有后一个。"""
        metas = _make_metadatas(3)
        result = expand_with_adjacent([2], metas, max_expand=2)
        assert 2 in result
        assert 1 in result  # 前一个
        # chunk_index=3 不存在

    def test_dedup_multiple_hits(self):
        """多个召回的 chunk 扩展后去重。"""
        metas = _make_metadatas(5)
        # 召回 chunk 1 和 2，扩展后可能有重叠
        result = expand_with_adjacent([1, 2], metas, max_expand=2)
        # 去重
        assert len(result) == len(set(result))

    def test_different_sources_no_cross_expand(self):
        """不同 source 的 chunk 不会互相扩展。"""
        metas = [
            {"chunk_id": "s1_c0", "chunk_index": 0, "source_id": "src1", "source_name": "a.txt"},
            {"chunk_id": "s1_c1", "chunk_index": 1, "source_id": "src1", "source_name": "a.txt"},
            {"chunk_id": "s2_c0", "chunk_index": 0, "source_id": "src2", "source_name": "b.txt"},
            {"chunk_id": "s2_c1", "chunk_index": 1, "source_id": "src2", "source_name": "b.txt"},
        ]
        # 召回 src2 的 chunk 0，不应扩展到 src1
        result = expand_with_adjacent([2], metas, max_expand=2)
        assert 2 in result  # 原始
        assert 3 in result  # src2 的下一个
        assert 0 not in result  # src1 的 chunk 不应出现
        assert 1 not in result

    def test_anchor_chunk_not_expanded(self):
        """anchor chunk（chunk_index=-1）不参与邻接扩展。"""
        metas = [
            {"chunk_id": "s1_anchor", "chunk_index": -1, "source_id": "src1", "source_name": "a.txt"},
            {"chunk_id": "s1_c0", "chunk_index": 0, "source_id": "src1", "source_name": "a.txt"},
        ]
        result = expand_with_adjacent([0], metas, max_expand=2)
        # anchor (index 0 in list, chunk_index=-1) 不应扩展
        assert result == [0]
