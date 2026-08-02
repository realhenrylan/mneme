"""Tests for citation validation loop — _validate_and_repair_citations."""

from __future__ import annotations

import pytest
from src.rag import _validate_and_repair_citations, _repair_citations
from src.domain import CitationValidation


def _make_metadatas(n: int) -> list[dict]:
    """生成 n 个元数据，每个有 source_name 和 source_id。"""
    return [
        {"source_name": f"doc{i}.pdf", "source_id": f"s{i}", "chunk_id": f"chunk_{i}"}
        for i in range(n)
    ]


# ── _repair_citations ──


class TestRepairCitations:
    """引用修复逻辑。"""

    def test_replace_invalid_with_closest_valid(self):
        """非法引用替换为最接近的合法引用。"""
        repaired = _repair_citations(
            "根据[S3]和[S5]的描述",
            invalid_ids={"S3", "S5"},
            valid_ids={"S1", "S2"},
        )
        # S3 → S2 (|3-2|=1 < |3-1|=2), S5 → S2 (|5-2|=3 < |5-1|=4)
        # 但 S3 和 S5 都替换为 S2，最终结果应该是 S2 和 S2
        assert "S3" not in repaired
        assert "S5" not in repaired

    def test_no_valid_ids_no_change(self):
        """无合法 ID 时不修复。"""
        repaired = _repair_citations(
            "根据[S3]的描述",
            invalid_ids={"S3"},
            valid_ids=set(),
        )
        assert repaired == "根据[S3]的描述"

    def test_no_invalid_ids_no_change(self):
        """无非法引用时不修复。"""
        repaired = _repair_citations(
            "根据[S1]的描述",
            invalid_ids=set(),
            valid_ids={"S1"},
        )
        assert repaired == "根据[S1]的描述"


# ── _validate_and_repair_citations ──


class TestValidateAndRepairCitations:
    """引用闭环校验和修复。"""

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

    def test_invalid_citation_repaired(self):
        """非法引用被修复。"""
        docs = ["chunk text 1", "chunk text 2"]
        metas = _make_metadatas(2)
        # S3 不在合法 ID 中，应被替换为 S1 或 S2
        answer = "根据[S3]的描述"
        result_answer, validation = _validate_and_repair_citations(
            answer, [0, 1], docs, metas,
        )
        assert "S3" not in result_answer
        assert validation.repaired is True
        assert validation.repair_success is True

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
        """context_k 限制合法引用 ID 范围。"""
        docs = ["chunk 0", "chunk 1", "chunk 2"]
        metas = _make_metadatas(3)
        # top_indices=[0,1,2]，context_k=2 → 只有 S1, S2 合法
        answer = "根据[S1]和[S3]的描述"
        result_answer, validation = _validate_and_repair_citations(
            answer, [0, 1, 2], docs, metas, context_k=2,
        )
        # S3 不合法，应被替换
        assert "S3" not in result_answer
        assert validation.repaired is True
