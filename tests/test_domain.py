"""Tests for src/domain.py — RetrievalCandidate, RefusalFeatures, compute_context_k."""

from __future__ import annotations

import pytest
from src.domain import (
    CitationValidation,
    RefusalFeatures,
    RetrievalCandidate,
    compute_context_k,
)


# ── RetrievalCandidate ──


class TestRetrievalCandidate:
    """RetrievalCandidate frozen dataclass 测试。"""

    def test_creation_with_required_fields(self):
        c = RetrievalCandidate(index=0, chunk_id="c0", source_id="s0", source_name="doc.pdf")
        assert c.index == 0
        assert c.chunk_id == "c0"
        assert c.source_id == "s0"
        assert c.source_name == "doc.pdf"

    def test_optional_scores_default_none(self):
        c = RetrievalCandidate(index=0, chunk_id="c0", source_id="s0", source_name="doc.pdf")
        assert c.dense_similarity is None
        assert c.bm25_score is None
        assert c.rrf_score is None
        assert c.graph_score is None
        assert c.rerank_score is None
        assert c.dense_rank is None
        assert c.bm25_rank is None
        assert c.rrf_rank is None

    def test_with_scores_returns_new_instance(self):
        c = RetrievalCandidate(index=0, chunk_id="c0", source_id="s0", source_name="doc.pdf")
        c2 = c.with_scores(rrf_score=0.05, rrf_rank=1)
        assert c.rrf_score is None  # 原实例不变
        assert c2.rrf_score == 0.05
        assert c2.rrf_rank == 1
        assert c2.index == 0  # 其他字段保持

    def test_with_scores_preserves_existing(self):
        c = RetrievalCandidate(
            index=0, chunk_id="c0", source_id="s0", source_name="doc.pdf",
            dense_similarity=0.8,
        )
        c2 = c.with_scores(rrf_score=0.05)
        assert c2.dense_similarity == 0.8  # 保留已有分数
        assert c2.rrf_score == 0.05

    def test_with_scores_override_existing(self):
        c = RetrievalCandidate(
            index=0, chunk_id="c0", source_id="s0", source_name="doc.pdf",
            rrf_score=0.05,
        )
        c2 = c.with_scores(rrf_score=0.1)
        assert c2.rrf_score == 0.1

    def test_frozen_immutable(self):
        c = RetrievalCandidate(index=0, chunk_id="c0", source_id="s0", source_name="doc.pdf")
        with pytest.raises(AttributeError):
            c.index = 1  # type: ignore[misc]


# ── compute_context_k ──


class TestComputeContextK:
    """compute_context_k 基于 token budget 计算实际进入 prompt 的候选数。"""

    def _make_candidates(self, n: int) -> list[RetrievalCandidate]:
        return [
            RetrievalCandidate(index=i, chunk_id=f"c{i}", source_id="s0", source_name="doc.pdf")
            for i in range(n)
        ]

    def test_default_budget_fits_15_candidates(self):
        # 默认 budget=3000, avg_chunk_tokens=200 → 3000//200=15, clamped to max_k=10
        candidates = self._make_candidates(20)
        assert compute_context_k(candidates) == 10

    def test_candidates_fewer_than_budget(self):
        # 只有 3 个候选，budget 允许 15，但受 min(len, budget_k) 限制
        candidates = self._make_candidates(3)
        assert compute_context_k(candidates) == 3

    def test_custom_budget(self):
        # budget=1000, avg=200 → 5, min_k=3, max_k=10 → 5
        candidates = self._make_candidates(20)
        assert compute_context_k(candidates, token_budget=1000) == 5

    def test_min_k_floor(self):
        # budget=200, avg=200 → 1, 但 min_k=3 → 3
        candidates = self._make_candidates(10)
        assert compute_context_k(candidates, token_budget=200) == 3

    def test_max_k_ceiling(self):
        # budget=10000, avg=200 → 50, 但 max_k=10 → 10
        candidates = self._make_candidates(20)
        assert compute_context_k(candidates, token_budget=10000) == 10

    def test_empty_candidates(self):
        assert compute_context_k([]) == 0

    def test_custom_min_max_k(self):
        # budget=5000, avg=200 → 25, max_k=15 → 15
        candidates = self._make_candidates(20)
        assert compute_context_k(candidates, token_budget=5000, max_k=15) == 15


# ── RefusalFeatures ──


class TestRefusalFeatures:
    """RefusalFeatures frozen dataclass 测试。"""

    def test_creation(self):
        f = RefusalFeatures(
            top_score=0.5,
            top1_top2_margin=0.2,
            effective_source_count=3,
            query_length=10,
            has_cjk=True,
            max_dense_similarity=0.8,
            max_bm25_score=2.5,
        )
        assert f.top_score == 0.5
        assert f.has_cjk is True

    def test_frozen(self):
        f = RefusalFeatures(
            top_score=0.5, top1_top2_margin=0.2, effective_source_count=1,
            query_length=5, has_cjk=False, max_dense_similarity=0.5, max_bm25_score=1.0,
        )
        with pytest.raises(AttributeError):
            f.top_score = 0.1  # type: ignore[misc]


# ── CitationValidation ──


class TestCitationValidation:
    """CitationValidation dataclass 测试。"""

    def test_defaults(self):
        v = CitationValidation(valid_ids={"S1"}, invalid_ids=set())
        assert v.repaired is False
        assert v.repair_success is False
        assert v.unverified is False

    def test_mutable_sets(self):
        # CitationValidation 不是 frozen，允许修改
        v = CitationValidation(valid_ids={"S1", "S2"}, invalid_ids={"S99"})
        v.invalid_ids.discard("S99")
        assert v.invalid_ids == set()
