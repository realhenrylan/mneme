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


# ── select_context_candidates（A/B/C 统一 context selector） ──


class TestSelectContextCandidates:
    """统一 context selector：三臂共用，diversity + top-k 截断。"""

    def test_same_as_diversity_behavior(self):
        """与 apply_source_diversity 行为一致（每源 ≤ max_per_source、保序）。"""
        from src.retrieval import select_context_candidates
        candidates = [
            _make_candidate(i, source_id="s0", rrf_score=1.0 - i * 0.01)
            for i in range(6)
        ] + [_make_candidate(i, source_id="s1", rrf_score=0.1) for i in range(6, 9)]
        result = select_context_candidates(candidates, top_k=10, max_per_source=3)
        assert len(result) == 6  # s0×3 + s1×3
        assert [c.index for c in result] == [0, 1, 2, 6, 7, 8]  # 保序

    def test_top_k_truncation(self):
        """总长不超过 top_k。"""
        from src.retrieval import select_context_candidates
        candidates = [
            _make_candidate(i, source_id=f"s{i % 3}", rrf_score=1.0 - i * 0.01)
            for i in range(20)
        ]
        result = select_context_candidates(candidates, top_k=10, max_per_source=10)
        assert len(result) == 10  # 只被 top_k 截断

    def test_zh002_scenario_fourth_same_source_chunk_kept_when_limit_raised(self):
        """回归：zh-002 类「同源第 4 个相关 chunk」场景。

        诊断发现：相关 chunk 排在同源第 4 位，max_per_source=3 会把它挤出。
        本测试验证：selector 在 max_per_source≥4 时保留第 4 个；且当限制为 3
        时明确丢弃（行为确定、可解释），不会出现不稳定顺序。
        """
        from src.retrieval import select_context_candidates
        # 同源 4 个 chunk，相关的是第 4 个（index=3）
        candidates = [
            _make_candidate(0, source_id="s0", rrf_score=0.9),
            _make_candidate(1, source_id="s0", rrf_score=0.8),
            _make_candidate(2, source_id="s0", rrf_score=0.7),
            _make_candidate(3, source_id="s0", rrf_score=0.6),  # 相关 chunk
            _make_candidate(4, source_id="s1", rrf_score=0.5),
        ]
        r3 = select_context_candidates(candidates, top_k=10, max_per_source=3)
        assert [c.index for c in r3] == [0, 1, 2, 4]  # 第 4 个同源被挤出
        r4 = select_context_candidates(candidates, top_k=10, max_per_source=4)
        assert [c.index for c in r4] == [0, 1, 2, 3, 4]  # 放宽后保留

    def test_deterministic_order(self):
        """相同输入产生相同输出（稳定顺序）。"""
        from src.retrieval import select_context_candidates
        candidates = [
            _make_candidate(i, source_id=f"s{i % 2}", rrf_score=1.0 - i * 0.01)
            for i in range(8)
        ]
        a = select_context_candidates(candidates, top_k=10, max_per_source=3)
        b = select_context_candidates(candidates, top_k=10, max_per_source=3)
        assert [c.index for c in a] == [c.index for c in b]


# ── CrossEncoderReranker chunk-aware 打分 ──


class TestCrossEncoderChunkAware:
    """reranker 必须按 chunk 文本打分，而非 source_name。"""

    def test_same_source_different_texts_get_different_scores(self):
        """同一 source 下文本不同的两个 chunk，传给模型的 pair 不同且分数可不同。

        用 mock 模型断言：(query, text) 被用于打分，而非 (query, source_name)。
        """
        from unittest.mock import MagicMock, patch
        reranker = CrossEncoderReranker()
        # 伪造 model：按文本内容返回不同分数（文本含 query token 则高分）
        fake_model = MagicMock()

        def fake_predict(pairs):
            # sentence-transformers predict 返回一维 score 数组
            out = []
            for q, doc in pairs:
                if "storage" in doc.lower():
                    out.append(2.0)
                else:
                    out.append(-1.0)
            return out

        fake_model.predict.side_effect = fake_predict
        reranker._model = fake_model

        c1 = RetrievalCandidate(
            index=0, chunk_id="c0", source_id="s0", source_name="OneDrive 入门.pdf",
            text="OneDrive free storage is 5GB",
        )
        c2 = RetrievalCandidate(
            index=1, chunk_id="c1", source_id="s0", source_name="OneDrive 入门.pdf",
            text="南京市总面积6587平方公里",
        )
        # 两者 source_name 相同；若按 source_name 打分则分数必相同
        result = reranker.rerank("how much storage", [c1, c2], top_k=2)
        assert result[0].index == 0  # 含 storage 的 c1 应排前
        assert result[0].rerank_score != result[1].rerank_score
        # 断言传给模型的 doc 侧是文本而非 source_name
        call_pairs = fake_model.predict.call_args.args[0]
        assert call_pairs[0] == ("how much storage", "OneDrive free storage is 5GB")

    def test_does_not_use_source_name_as_document(self):
        """reranker 不再把 source_name 当正文：pair 的 doc 侧必须是 text。"""
        from unittest.mock import MagicMock
        reranker = CrossEncoderReranker()
        fake_model = MagicMock()
        fake_model.predict.return_value = [0.5, 0.4]
        reranker._model = fake_model

        c1 = RetrievalCandidate(
            index=0, chunk_id="c0", source_id="s0", source_name="A.pdf",
            text="alpha beta gamma",
        )
        c2 = RetrievalCandidate(
            index=1, chunk_id="c1", source_id="s0", source_name="B.pdf",
            text="delta epsilon zeta",
        )
        reranker.rerank("query", [c1, c2], top_k=2)
        pairs = fake_model.predict.call_args.args[0]
        assert pairs[0][1] == "alpha beta gamma"  # 是文本，不是 "A.pdf"
        assert pairs[1][1] == "delta epsilon zeta"  # 不是 "B.pdf"
        assert "A.pdf" not in pairs[0][1]
        assert "B.pdf" not in pairs[1][1]

    def test_empty_text_falls_back_to_source_name(self):
        """空文本不崩溃，fallback 到 source_name（兼容无文本候选）。"""
        from unittest.mock import MagicMock
        reranker = CrossEncoderReranker()
        fake_model = MagicMock()
        fake_model.predict.return_value = [1.0]
        reranker._model = fake_model

        c = RetrievalCandidate(
            index=0, chunk_id="c0", source_id="s0", source_name="doc.pdf",
            text="   ",  # 空白文本
        )
        reranker.rerank("query", [c], top_k=1)
        pairs = fake_model.predict.call_args.args[0]
        assert pairs[0][1] == "doc.pdf"  # fallback

    def test_tie_break_by_index_deterministic(self):
        """并列分数时按 index 稳定排序（确定性）。"""
        from unittest.mock import MagicMock
        reranker = CrossEncoderReranker()
        fake_model = MagicMock()
        fake_model.predict.return_value = [1.0, 1.0, 1.0]  # 全并列
        reranker._model = fake_model

        cands = [
            RetrievalCandidate(index=5, chunk_id="c5", source_id="s0",
                               source_name="d.pdf", text="x"),
            RetrievalCandidate(index=2, chunk_id="c2", source_id="s0",
                               source_name="d.pdf", text="y"),
            RetrievalCandidate(index=9, chunk_id="c9", source_id="s0",
                               source_name="d.pdf", text="z"),
        ]
        r1 = reranker.rerank("q", cands, top_k=3)
        r2 = reranker.rerank("q", cands, top_k=3)
        assert [c.index for c in r1] == [c.index for c in r2]  # 确定性
        assert [c.index for c in r1] == [9, 5, 2]  # index 降序 tie-break

    def test_empty_candidates(self):
        """空候选列表返回空。"""
        reranker = CrossEncoderReranker()
        assert reranker.rerank("q", [], top_k=3) == []


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


# ── selector 不限同源语义（S0 消融臂） ──────────────────────────────


class TestSelectorUnlimitedSemantics:
    """max_per_source=None/0 表示「不限同源 chunk」（仅 top_k 截断、保序）。

    S0（selector-unlimited）消融臂依赖此语义；生产默认 max_per_source=3 不变。
    """

    def test_none_keeps_all_same_source(self):
        """max_per_source=None：同源 6 个候选全部保留。"""
        from src.retrieval import select_context_candidates
        candidates = [
            _make_candidate(i, source_id="s0", rrf_score=1.0 - i * 0.01)
            for i in range(6)
        ]
        result = select_context_candidates(candidates, top_k=10, max_per_source=None)
        assert [c.index for c in result] == [0, 1, 2, 3, 4, 5]

    def test_zero_is_unlimited(self):
        """max_per_source=0 与 None 等价（不限同源）。"""
        from src.retrieval import select_context_candidates
        candidates = [
            _make_candidate(i, source_id="s0", rrf_score=1.0 - i * 0.01)
            for i in range(6)
        ]
        result = select_context_candidates(candidates, top_k=10, max_per_source=0)
        assert [c.index for c in result] == [0, 1, 2, 3, 4, 5]

    def test_unlimited_still_respects_top_k(self):
        """不限同源时仍按 top_k 截断且保序。"""
        from src.retrieval import select_context_candidates
        candidates = [
            _make_candidate(i, source_id="s0", rrf_score=1.0 - i * 0.01)
            for i in range(8)
        ]
        result = select_context_candidates(candidates, top_k=5, max_per_source=None)
        assert [c.index for c in result] == [0, 1, 2, 3, 4]

    def test_unlimited_multi_source_keeps_all(self):
        """多来源且不限同源：全部候选保留（无 diversity 挤出）。"""
        from src.retrieval import select_context_candidates
        candidates = [
            _make_candidate(i, source_id=f"s{i % 2}", rrf_score=1.0 - i * 0.01)
            for i in range(8)
        ]
        result = select_context_candidates(candidates, top_k=10, max_per_source=None)
        assert [c.index for c in result] == [0, 1, 2, 3, 4, 5, 6, 7]

    def test_cap3_vs_unlimited_contrast(self):
        """cap=3 与 unlimited 的可观察差异：同源第 4 个 chunk。"""
        from src.retrieval import select_context_candidates
        candidates = [
            _make_candidate(i, source_id="s0", rrf_score=1.0 - i * 0.01)
            for i in range(6)
        ]
        capped = select_context_candidates(candidates, top_k=10, max_per_source=3)
        unlimited = select_context_candidates(candidates, top_k=10, max_per_source=None)
        assert len(capped) == 3
        assert len(unlimited) == 6
