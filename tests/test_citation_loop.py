"""Tests for citation validation — _validate_and_repair_citations.

Product P0.1 起：校验不再做"最近合法编号替换"。非法引用保留原回答
文本并标记 unverified——编号替换不能证明事实真的由该来源支持。
"""
from __future__ import annotations

import pytest
from src.rag import _validate_and_repair_citations
from src.domain import CitationValidation


def _make_metadatas(n: int) -> list[dict]:
    """生成 n 个元数据，每个有 source_name 和 source_id。"""
    return [
        {"source_name": f"doc{i}.pdf", "source_id": f"s{i}", "chunk_id": f"chunk_{i}"}
        for i in range(n)
    ]


class TestValidateAndRepairCitations:
    """引用校验（不修复）：非法引用保留原文 + 标记 unverified。"""

    def test_all_valid_citations(self):
        """所有引用合法，直接返回。"""
        docs = ["chunk text 1", "chunk text 2"]
        metas = _make_metadatas(2)
        answer = "根据[S1]和[S2]的描述"
        result_answer, validation = _validate_and_repair_citations(
            answer, [0, 1], docs, metas,
        )
        assert result_answer == answer
        assert validation.invalid_ids == set()
        assert validation.repaired is False
        assert validation.unverified is False

    def test_invalid_citation_kept_and_marked_unverified(self):
        """非法引用不再被替换为最接近的合法 ID。"""
        docs = ["chunk text 1", "chunk text 2"]
        metas = _make_metadatas(2)
        answer = "根据[S3]的描述"
        result_answer, validation = _validate_and_repair_citations(
            answer, [0, 1], docs, metas,
        )
        assert result_answer == answer          # 原样保留
        assert "S3" in result_answer
        assert validation.invalid_ids == {"S3"}
        assert validation.unverified is True
        assert validation.repaired is False

    def test_no_citations_in_answer(self):
        """回答中没有引用，校验通过（无非法引用）。"""
        docs = ["chunk text 1"]
        metas = _make_metadatas(1)
        answer = "这是一段没有引用的回答"
        result_answer, validation = _validate_and_repair_citations(
            answer, [0], docs, metas,
        )
        assert result_answer == answer
        assert validation.invalid_ids == set()

    def test_empty_answer(self):
        """空回答，校验通过。"""
        docs = ["chunk text 1"]
        metas = _make_metadatas(1)
        result_answer, validation = _validate_and_repair_citations(
            "", [0], docs, metas,
        )
        assert result_answer == ""
        assert validation.invalid_ids == set()

    def test_context_k_limits_valid_ids(self):
        """context_k 限制合法引用 ID 范围；越界 ID 保留并标记。"""
        docs = ["chunk 0", "chunk 1", "chunk 2"]
        metas = _make_metadatas(3)
        # top_indices=[0,1,2]，context_k=2 → 只有 S1, S2 合法
        answer = "根据[S1]和[S3]的描述"
        result_answer, validation = _validate_and_repair_citations(
            answer, [0, 1, 2], docs, metas, context_k=2,
        )
        # S3 不合法 → 保留原文，标记 unverified
        assert "S3" in result_answer
        assert validation.invalid_ids == {"S3"}
        assert validation.unverified is True
