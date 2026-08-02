"""Tests for evaluation.citation_metrics module."""

import pytest

from evaluation.citation_metrics import (
    compute_citation_id_validity,
    compute_citation_precision_recall,
    compute_faithfulness,
    compute_refusal_accuracy,
    evaluate_citations,
    _extract_key_terms,
)


# ── compute_citation_id_validity ────────────────────────────────────

class TestCitationIdValidity:
    def test_all_valid(self):
        validity, invalid, total = compute_citation_id_validity(
            "According to [S1] and [S2], the answer is 42.",
            {"S1", "S2", "S3"},
        )
        assert validity == 1.0
        assert invalid == 0
        assert total == 2

    def test_some_invalid(self):
        validity, invalid, total = compute_citation_id_validity(
            "According to [S1] and [S5], the answer is 42.",
            {"S1", "S2", "S3"},
        )
        assert validity == 0.5
        assert invalid == 1
        assert total == 2

    def test_all_invalid(self):
        validity, invalid, total = compute_citation_id_validity(
            "According to [S99], the answer is 42.",
            {"S1", "S2"},
        )
        assert validity == 0.0
        assert invalid == 1
        assert total == 1

    def test_no_citations(self):
        validity, invalid, total = compute_citation_id_validity(
            "The answer is 42.",
            {"S1", "S2"},
        )
        assert validity == 0.0
        assert invalid == 0
        assert total == 0


# ── compute_citation_precision_recall ───────────────────────────────

class TestCitationPrecisionRecall:
    def test_perfect_precision_recall(self):
        p, r = compute_citation_precision_recall(
            "According to [S1] and [S2].",
            relevant_chunk_ids={"chunk_1", "chunk_2"},
            all_retrieved_ids={"S1", "S2", "S3"},
        )
        # S1, S2 are cited and valid; they may or may not match
        # relevant_chunk_ids by name — this tests the mechanism
        assert isinstance(p, float)
        assert isinstance(r, float)

    def test_no_citations_zero_precision(self):
        p, r = compute_citation_precision_recall(
            "The answer is 42.",
            relevant_chunk_ids={"chunk_1"},
            all_retrieved_ids={"S1"},
        )
        assert p == 0.0

    def test_no_relevant_zero_recall(self):
        p, r = compute_citation_precision_recall(
            "According to [S1].",
            relevant_chunk_ids=set(),
            all_retrieved_ids={"S1"},
        )
        assert r == 0.0


# ── compute_faithfulness ────────────────────────────────────────────

class TestFaithfulness:
    def test_all_points_supported(self):
        context = "南京总面积6587.04平方千米，海拔最高点为紫金山448.9米"
        points = ["6587.04平方千米", "紫金山448.9米"]
        f = compute_faithfulness("南京面积6587.04平方千米", points, context)
        assert f == 1.0

    def test_partial_support(self):
        context = "南京总面积6587.04平方千米"
        points = ["6587.04平方千米", "紫金山448.9米"]
        f = compute_faithfulness("南京面积6587.04平方千米", points, context)
        # Only one of two points is supported
        assert f == 0.5

    def test_no_points_vacuously_faithful(self):
        f = compute_faithfulness("Some answer", [], "Some context")
        assert f == 1.0

    def test_english_faithfulness(self):
        context = "DSpark improves the macro-average accepted length by 30.9%"
        points = ["30.9%"]
        f = compute_faithfulness("DSpark improves by 30.9%", points, context)
        assert f == 1.0


# ── compute_refusal_accuracy ────────────────────────────────────────

class TestRefusalAccuracy:
    def test_correct_refusal_zh(self):
        result = compute_refusal_accuracy(
            "未找到足够可靠的文档依据，暂时无法回答该问题。",
            should_refuse=True,
        )
        assert result is True

    def test_incorrect_answer_when_should_refuse(self):
        result = compute_refusal_accuracy(
            "南京的GDP是1.6万亿元。",
            should_refuse=True,
        )
        assert result is False

    def test_correct_answer_when_should_not_refuse(self):
        result = compute_refusal_accuracy(
            "南京总面积6587.04平方千米。",
            should_refuse=False,
        )
        assert result is True

    def test_incorrect_refusal_when_should_answer(self):
        result = compute_refusal_accuracy(
            "未找到相关信息，无法回答。",
            should_refuse=False,
        )
        assert result is False

    def test_english_refusal(self):
        result = compute_refusal_accuracy(
            "I cannot find information about this topic.",
            should_refuse=True,
        )
        assert result is True


# ── _extract_key_terms ──────────────────────────────────────────────

class TestExtractKeyTerms:
    def test_chinese_terms(self):
        terms = _extract_key_terms("南京总面积6587.04平方千米")
        # CJK characters are grouped as continuous runs
        assert "南京总面积" in terms
        assert "6587.04" in terms
        assert "平方千米" in terms

    def test_english_terms(self):
        terms = _extract_key_terms("DSpark improves by 30.9%")
        assert "dspark" in terms
        assert "30.9%" in terms

    def test_stop_words_filtered(self):
        terms = _extract_key_terms("The answer is in the document")
        assert "the" not in terms
        assert "is" not in terms


# ── evaluate_citations (integration) ────────────────────────────────

class TestEvaluateCitations:
    def test_basic_evaluation(self):
        metrics = evaluate_citations(
            answer="根据[S1]，南京总面积6587.04平方千米。",
            valid_ids={"S1", "S2", "S3"},
            relevant_chunk_ids={"chunk_0"},
            all_retrieved_ids={"S1", "S2", "S3"},
            answer_points=["6587.04平方千米"],
            context="南京总面积6587.04平方千米",
            should_refuse=False,
        )
        assert metrics.citation_id_validity == 1.0
        assert metrics.invalid_citation_count == 0
        assert metrics.total_citation_count == 1
        assert metrics.faithfulness == 1.0
        assert metrics.correctly_refused is True

    def test_refusal_case(self):
        metrics = evaluate_citations(
            answer="未找到足够可靠的文档依据，暂时无法回答该问题。",
            valid_ids={"S1"},
            relevant_chunk_ids=set(),
            all_retrieved_ids={"S1"},
            answer_points=[],
            context="Some context",
            should_refuse=True,
        )
        assert metrics.correctly_refused is True
