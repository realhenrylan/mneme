"""Tests for src/retrieval.py — Reranker interface, source diversity, refusal features."""

from __future__ import annotations

import pytest
from src.retrieval import (
    CrossEncoderReranker,
    NoOpReranker,
    Reranker,
    apply_source_diversity,
    extract_refusal_features,
    should_refuse_with_features,
)
from src.domain import RefusalFeatures, RetrievalCandidate


def _make_candidate(
    index: int,
    source_id: str = "s0",
    source_name: str = "doc.pdf",
    rrf_score: float | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        index=index,
        chunk_id=f"c{index}",
        source_id=source_id,
        source_name=source_name,
        rrf_score=rrf_score,
    )


# ── Reranker Protocol ──


class TestRerankerProtocol:
    """Reranker 是一个 Protocol，检查结构一致性。"""

    def test_noop_is_reranker(self):
        r = NoOpReranker()
        assert isinstance(r, Reranker)

    def test_cross_encoder_is_reranker(self):
        r = CrossEncoderReranker()
        assert isinstance(r, Reranker)


# ── NoOpReranker ──


class TestNoOpReranker:
    """NoOp Reranker 不做重排。"""

    def test_returns_top_k(self):
        candidates = [_make_candidate(i) for i in range(5)]
        r = NoOpReranker()
        result = r.rerank("query", candidates, top_k=3)
        assert len(result) == 3
        assert result[0].index == 0
        assert result[1].index == 1
        assert result[2].index == 2

    def test_empty_candidates(self):
        r = NoOpReranker()
        result = r.rerank("query", [], top_k=3)
        assert result == []

    def test_fewer_than_top_k(self):
        candidates = [_make_candidate(i) for i in range(2)]
        r = NoOpReranker()
        result = r.rerank("query", candidates, top_k=5)
        assert len(result) == 2


# ── apply_source_diversity ──


class TestApplySourceDiversity:
    """来源多样性约束。"""

    def test_single_source_capped(self):
        """同一来源最多 max_per_source 个。"""
        candidates = [
            _make_candidate(i, source_id="s0", rrf_score=1.0 - i * 0.1)
            for i in range(6)
        ]
        result = apply_source_diversity(candidates, max_per_source=3, top_k=10)
        assert len(result) == 3
        assert all(c.source_id == "s0" for c in result)

    def test_multiple_sources_balanced(self):
        """多来源时各来源都有代表。"""
        candidates = [
            _make_candidate(0, source_id="s0", rrf_score=0.9),
            _make_candidate(1, source_id="s0", rrf_score=0.8),
            _make_candidate(2, source_id="s0", rrf_score=0.7),
            _make_candidate(3, source_id="s1", rrf_score=0.6),
            _make_candidate(4, source_id="s1", rrf_score=0.5),
            _make_candidate(5, source_id="s2", rrf_score=0.4),
        ]
        result = apply_source_diversity(candidates, max_per_source=2, top_k=5)
        assert len(result) == 5
        # s0 最多 2 个，s1 最多 2 个，s2 1 个
        source_counts = {}
        for c in result:
            source_counts[c.source_id] = source_counts.get(c.source_id, 0) + 1
        assert source_counts.get("s0", 0) <= 2
        assert source_counts.get("s1", 0) <= 2
        assert source_counts.get("s2", 0) <= 2

    def test_top_k_limit(self):
        """top_k 限制最终返回数。"""
        candidates = [
            _make_candidate(i, source_id=f"s{i % 3}", rrf_score=1.0 - i * 0.01)
            for i in range(20)
        ]
        result = apply_source_diversity(candidates, max_per_source=5, top_k=7)
        assert len(result) == 7

    def test_preserves_order(self):
        """保持原始排序。"""
        candidates = [
            _make_candidate(0, source_id="s0", rrf_score=0.9),
            _make_candidate(1, source_id="s1", rrf_score=0.8),
            _make_candidate(2, source_id="s0", rrf_score=0.7),
        ]
        result = apply_source_diversity(candidates, max_per_source=2, top_k=3)
        assert [c.index for c in result] == [0, 1, 2]

    def test_empty_candidates(self):
        result = apply_source_diversity([], max_per_source=3, top_k=10)
        assert result == []

    def test_default_max_per_source(self):
        """默认每来源最多 3 个。"""
        candidates = [
            _make_candidate(i, source_id="s0", rrf_score=1.0 - i * 0.01)
            for i in range(10)
        ]
        result = apply_source_diversity(candidates, top_k=10)
        assert len(result) == 3  # 默认 max_per_source=3


# ── extract_refusal_features ──


class TestExtractRefusalFeatures:
    """拒答特征提取。"""

    def test_empty_candidates(self):
        features = extract_refusal_features([], "测试查询")
        assert features.top_score == 0.0
        assert features.effective_source_count == 0
        assert features.has_cjk is True

    def test_single_candidate(self):
        candidates = [
            _make_candidate(0, rrf_score=0.05),
        ]
        features = extract_refusal_features(candidates, "test query")
        assert features.top_score == 0.05
        assert features.top1_top2_margin == 0.0  # 只有一个候选
        assert features.effective_source_count == 1
        assert features.has_cjk is False

    def test_multiple_candidates(self):
        candidates = [
            _make_candidate(0, source_id="s0", rrf_score=0.06),
            _make_candidate(1, source_id="s1", rrf_score=0.04),
            _make_candidate(2, source_id="s0", rrf_score=0.02),
        ]
        features = extract_refusal_features(candidates, "查询")
        assert features.top_score == 0.06
        assert features.top1_top2_margin == pytest.approx(0.02, abs=0.001)
        assert features.effective_source_count == 2  # s0, s1
        assert features.has_cjk is True

    def test_reranker_score_preferred(self):
        """有 rerank_score 时优先使用。"""
        candidates = [
            RetrievalCandidate(
                index=0, chunk_id="c0", source_id="s0", source_name="doc.pdf",
                rrf_score=0.05, rerank_score=0.8,
            ),
        ]
        features = extract_refusal_features(candidates, "query")
        assert features.top_score == 0.8  # rerank_score 优先

    def test_zero_score_candidates(self):
        """分数为 0 的候选不计入有效来源。"""
        candidates = [
            _make_candidate(0, source_id="s0", rrf_score=0.0),
        ]
        features = extract_refusal_features(candidates, "query")
        assert features.effective_source_count == 0


# ── should_refuse_with_features ──


class TestShouldRefuseWithFeatures:
    """基于特征的拒答判断。"""

    def test_no_sources_refuse(self):
        """无有效来源时拒答。"""
        features = RefusalFeatures(
            top_score=0.0, top1_top2_margin=0.0, effective_source_count=0,
            query_length=5, has_cjk=False, max_dense_similarity=0.0, max_bm25_score=0.0,
        )
        assert should_refuse_with_features(features) is True

    def test_low_rrf_score_refuse(self):
        """RRF 分数低于阈值时拒答。"""
        features = RefusalFeatures(
            top_score=0.01, top1_top2_margin=0.005, effective_source_count=1,
            query_length=5, has_cjk=False, max_dense_similarity=0.3, max_bm25_score=1.0,
        )
        assert should_refuse_with_features(features, rrf_threshold=0.015) is True

    def test_high_rrf_score_accept(self):
        """RRF 分数高于阈值时不拒答。"""
        features = RefusalFeatures(
            top_score=0.03, top1_top2_margin=0.01, effective_source_count=2,
            query_length=5, has_cjk=False, max_dense_similarity=0.5, max_bm25_score=2.0,
        )
        assert should_refuse_with_features(features, rrf_threshold=0.015) is False

    def test_low_reranker_score_refuse(self):
        """Reranker 分数低于阈值时拒答。"""
        features = RefusalFeatures(
            top_score=0.2, top1_top2_margin=0.1, effective_source_count=1,
            query_length=5, has_cjk=False, max_dense_similarity=0.3, max_bm25_score=1.0,
        )
        # has_reranker=True 触发 reranker 阈值判断，0.2 < 0.3 → 拒答
        assert should_refuse_with_features(features, reranker_threshold=0.3, has_reranker=True) is True

    def test_high_reranker_score_accept(self):
        """Reranker 分数高于阈值时不拒答。"""
        features = RefusalFeatures(
            top_score=0.6, top1_top2_margin=0.2, effective_source_count=2,
            query_length=5, has_cjk=False, max_dense_similarity=0.7, max_bm25_score=3.0,
        )
        assert should_refuse_with_features(features, reranker_threshold=0.3, has_reranker=True) is False
