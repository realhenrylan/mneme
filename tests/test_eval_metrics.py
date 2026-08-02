"""Tests for evaluation.metrics module."""

import math

import pytest

from evaluation.metrics import (
    compute_retrieval_metrics,
    compute_stratified_metrics,
    mean_reciprocal_rank,
    ndcg_at_k,
    recall_at_k,
    source_recall_at_k,
)


# ── recall_at_k ─────────────────────────────────────────────────────

class TestRecallAtK:
    def test_perfect_recall(self):
        retrieved = ["a", "b", "c", "d", "e"]
        relevant = {"a", "b", "c"}
        assert recall_at_k(retrieved, relevant, k=5) == 1.0

    def test_partial_recall(self):
        retrieved = ["a", "x", "y", "b", "z"]
        relevant = {"a", "b", "c"}
        # top-5: found a, b → 2/3
        assert recall_at_k(retrieved, relevant, k=5) == pytest.approx(2 / 3)

    def test_no_relevant_found(self):
        retrieved = ["x", "y", "z"]
        relevant = {"a", "b"}
        assert recall_at_k(retrieved, relevant, k=3) == 0.0

    def test_empty_relevant(self):
        assert recall_at_k(["a", "b"], set(), k=5) == 0.0

    def test_k_smaller_than_retrieved(self):
        retrieved = ["a", "x", "b", "y", "c"]
        relevant = {"a", "b", "c"}
        # k=2: only "a" found → 1/3
        assert recall_at_k(retrieved, relevant, k=2) == pytest.approx(1 / 3)


# ── mean_reciprocal_rank ────────────────────────────────────────────

class TestMRR:
    def test_perfect_mrr(self):
        retrieved = [["a", "b"], ["c", "d"]]
        relevant = [{"a"}, {"c"}]
        assert mean_reciprocal_rank(retrieved, relevant) == 1.0

    def test_second_rank_mrr(self):
        retrieved = [["x", "a"], ["y", "c"]]
        relevant = [{"a"}, {"c"}]
        # 1/2 + 1/2 = 1.0, avg = 0.5
        assert mean_reciprocal_rank(retrieved, relevant) == pytest.approx(0.5)

    def test_no_match_mrr(self):
        retrieved = [["x", "y"], ["z", "w"]]
        relevant = [{"a"}, {"b"}]
        assert mean_reciprocal_rank(retrieved, relevant) == 0.0

    def test_empty_input(self):
        assert mean_reciprocal_rank([], []) == 0.0


# ── ndcg_at_k ───────────────────────────────────────────────────────

class TestNDCG:
    def test_perfect_ndcg(self):
        retrieved = ["a", "b", "c"]
        relevant = {"a", "b", "c"}
        # All relevant at top → DCG = IDCG → nDCG = 1.0
        assert ndcg_at_k(retrieved, relevant, k=3) == pytest.approx(1.0)

    def test_partial_ndcg(self):
        retrieved = ["x", "a", "y", "b"]
        relevant = {"a", "b", "c"}
        # DCG: 0 + 1/log2(3) + 0 + 1/log2(5)
        # IDCG: 1/log2(2) + 1/log2(3) + 1/log2(4)
        dcg = 1.0 / math.log2(3) + 1.0 / math.log2(5)
        idcg = 1.0 / math.log2(2) + 1.0 / math.log2(3) + 1.0 / math.log2(4)
        expected = dcg / idcg
        assert ndcg_at_k(retrieved, relevant, k=4) == pytest.approx(expected)

    def test_no_relevant_ndcg(self):
        assert ndcg_at_k(["x", "y"], set(), k=5) == 0.0

    def test_empty_relevant(self):
        assert ndcg_at_k(["a"], set(), k=5) == 0.0


# ── source_recall_at_k ──────────────────────────────────────────────

class TestSourceRecall:
    def test_perfect_source_recall(self):
        retrieved = ["doc1", "doc2", "doc3"]
        relevant = {"doc1", "doc2"}
        assert source_recall_at_k(retrieved, relevant, k=3) == 1.0

    def test_partial_source_recall(self):
        retrieved = ["doc1", "doc4", "doc5"]
        relevant = {"doc1", "doc2", "doc3"}
        # Found doc1 → 1/3
        assert source_recall_at_k(retrieved, relevant, k=3) == pytest.approx(1 / 3)

    def test_empty_relevant(self):
        assert source_recall_at_k(["doc1"], set(), k=5) == 0.0


# ── compute_retrieval_metrics ───────────────────────────────────────

class TestComputeRetrievalMetrics:
    def test_basic_computation(self):
        retrieved = [
            ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j",
             "k", "l", "m", "n", "o", "p", "q", "r", "s", "t"],
            ["x", "a", "y", "b", "z", "c", "w", "d", "v", "e",
             "u", "f", "t", "g", "s", "h", "r", "i", "q", "j"],
        ]
        relevant = [{"a", "b", "c"}, {"a", "b", "c"}]
        metrics = compute_retrieval_metrics(retrieved, relevant, ks=(5, 10))
        assert "recall@5" in metrics
        assert "recall@10" in metrics
        assert "ndcg@5" in metrics
        assert "ndcg@10" in metrics
        assert "mrr" in metrics
        # First query has perfect recall@5
        assert metrics["recall@5"] > 0.0

    def test_empty_input(self):
        metrics = compute_retrieval_metrics([], [], ks=(5,))
        assert metrics["recall@5"] == 0.0
        assert metrics["mrr"] == 0.0


# ── compute_stratified_metrics ──────────────────────────────────────

class TestStratifiedMetrics:
    def test_stratified_by_language(self):
        retrieved = [["a", "b"], ["x", "y"]]
        relevant = [{"a"}, {"x"}]
        groups = ["zh", "en"]
        result = compute_stratified_metrics(retrieved, relevant, groups, ks=(5,))
        assert "zh" in result
        assert "en" in result
        assert result["zh"]["recall@5"] == 1.0
        assert result["en"]["recall@5"] == 1.0
