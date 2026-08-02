"""测试 2.4 多轮检索改写 — History-aware standalone query rewrite。"""

import pytest
from src.rag_query_rewriter import (
    should_rewrite,
    rewrite_query_llm,
    merge_rewrite_results,
    _PRONOUN_PATTERNS,
)


# ═══════════════════════════════════════════════════════════════
# should_rewrite 测试
# ═══════════════════════════════════════════════════════════════

class TestShouldRewrite:
    def test_no_history(self):
        """无历史时不需要改写。"""
        assert should_rewrite("它的作者是谁？", None) is False

    def test_empty_history(self):
        """空历史列表不需要改写。"""
        assert should_rewrite("它的作者是谁？", []) is False

    def test_short_query(self):
        """过短查询不需要改写。"""
        assert should_rewrite("它", [("Q", "A")]) is False

    def test_chinese_pronoun(self):
        """中文代词需要改写。"""
        assert should_rewrite("它的作者是谁？", [("DSpark是什么？", "DSpark是...")]) is True

    def test_chinese_demonstrative(self):
        """中文指示词需要改写。"""
        assert should_rewrite("这个方法有什么优势？", [("什么是X？", "X是...")]) is True

    def test_english_pronoun(self):
        """英文代词需要改写。"""
        assert should_rewrite("What are its main contributions?", [("What is X?", "X is...")]) is True

    def test_standalone_query_no_pronoun(self):
        """独立查询无代词不需要改写。"""
        assert should_rewrite("What is machine learning?", [("What is AI?", "AI is...")]) is False

    def test_chinese_question_starter(self):
        """中文疑问词开头且无明确主语需要改写。"""
        assert should_rewrite("有哪些方法？", [("什么是X？", "X是...")]) is True

    def test_standalone_chinese_query(self):
        """独立中文查询不需要改写。"""
        assert should_rewrite("深度学习的原理是什么？", [("什么是AI？", "AI是...")]) is False


# ═══════════════════════════════════════════════════════════════
# rewrite_query_llm 测试（不依赖 LLM API）
# ═══════════════════════════════════════════════════════════════

class TestRewriteQueryLlm:
    def test_no_history_returns_original(self):
        """无历史时返回原查询。"""
        result, log = rewrite_query_llm("它的作者是谁？", history=None)
        assert result == "它的作者是谁？"
        assert log["changed"] is False
        assert log["reason"] == "no_rewrite_needed"

    def test_empty_history_returns_original(self):
        """空历史时返回原查询。"""
        result, log = rewrite_query_llm("它的作者是谁？", history=[])
        assert result == "它的作者是谁？"
        assert log["changed"] is False

    def test_standalone_query_returns_original(self):
        """独立查询返回原查询。"""
        result, log = rewrite_query_llm(
            "What is machine learning?",
            history=[("What is AI?", "AI is...")],
        )
        assert result == "What is machine learning?"
        assert log["changed"] is False

    def test_no_api_key_returns_original(self, monkeypatch):
        """无 API key 时返回原查询。"""
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("BASE_URL", raising=False)
        result, log = rewrite_query_llm(
            "它的作者是谁？",
            history=[("DSpark是什么？", "DSpark是...")],
        )
        assert result == "它的作者是谁？"
        assert log["changed"] is False
        assert log["reason"] == "no_api_key"

    def test_rewrite_log_structure(self):
        """改写日志结构正确。"""
        _, log = rewrite_query_llm("test query", history=None)
        assert "original" in log
        assert "rewritten" in log
        assert "changed" in log
        assert "reason" in log
        assert log["original"] == "test query"


# ═══════════════════════════════════════════════════════════════
# merge_rewrite_results 测试
# ═══════════════════════════════════════════════════════════════

class TestMergeRewriteResults:
    def test_no_overlap(self):
        """无重叠时合并所有结果。"""
        merged, scores, log = merge_rewrite_results(
            [0, 1, 2], {0: 0.9, 1: 0.8, 2: 0.7},
            [3, 4, 5], {3: 0.6, 4: 0.5, 5: 0.4},
        )
        assert len(merged) == 6
        assert log["overlap_count"] == 0
        assert log["rewrite_only"] == [3, 4, 5]
        assert log["original_only"] == [0, 1, 2]

    def test_full_overlap(self):
        """完全重叠时取最高分。"""
        merged, scores, log = merge_rewrite_results(
            [0, 1], {0: 0.9, 1: 0.8},
            [0, 1], {0: 0.95, 1: 0.7},
        )
        assert len(merged) == 2
        assert scores[0] == 0.95  # max(0.9, 0.95)
        assert scores[1] == 0.8   # max(0.8, 0.7)
        assert log["overlap_count"] == 2
        assert log["rewrite_only"] == []
        assert log["original_only"] == []

    def test_partial_overlap(self):
        """部分重叠时正确合并。"""
        merged, scores, log = merge_rewrite_results(
            [0, 1, 2], {0: 0.9, 1: 0.8, 2: 0.7},
            [1, 2, 3], {1: 0.85, 2: 0.75, 3: 0.6},
        )
        assert len(merged) == 4
        assert scores[1] == 0.85  # max(0.8, 0.85)
        assert log["overlap_count"] == 2
        assert log["original_only"] == [0]
        assert log["rewrite_only"] == [3]

    def test_empty_rewrite(self):
        """改写结果为空时只保留原查询结果。"""
        merged, scores, log = merge_rewrite_results(
            [0, 1], {0: 0.9, 1: 0.8},
            [], {},
        )
        assert len(merged) == 2
        assert log["rewrite_count"] == 0

    def test_empty_original(self):
        """原查询结果为空时只保留改写结果。"""
        merged, scores, log = merge_rewrite_results(
            [], {},
            [0, 1], {0: 0.9, 1: 0.8},
        )
        assert len(merged) == 2
        assert log["original_count"] == 0

    def test_merged_sorted_by_score(self):
        """合并结果按分数降序排列。"""
        merged, scores, log = merge_rewrite_results(
            [0], {0: 0.5},
            [1, 2], {1: 0.9, 2: 0.3},
        )
        assert merged[0] == 1  # 0.9 最高
        assert merged[-1] == 2  # 0.3 最低

    def test_merge_log_counts(self):
        """合并日志计数正确。"""
        _, _, log = merge_rewrite_results(
            [0, 1, 2], {0: 0.9, 1: 0.8, 2: 0.7},
            [1, 3], {1: 0.85, 3: 0.6},
        )
        assert log["original_count"] == 3
        assert log["rewrite_count"] == 2
        assert log["merged_count"] == 4
        assert log["overlap_count"] == 1


# ═══════════════════════════════════════════════════════════════
# 代词模式正则测试
# ═══════════════════════════════════════════════════════════════

class TestPronounPatterns:
    def test_chinese_pronouns(self):
        assert _PRONOUN_PATTERNS.search("它") is not None
        assert _PRONOUN_PATTERNS.search("他") is not None
        assert _PRONOUN_PATTERNS.search("这个") is not None
        assert _PRONOUN_PATTERNS.search("那个") is not None
        assert _PRONOUN_PATTERNS.search("其") is not None
        assert _PRONOUN_PATTERNS.search("上面") is not None
        assert _PRONOUN_PATTERNS.search("前面") is not None

    def test_english_pronouns(self):
        assert _PRONOUN_PATTERNS.search("it") is not None
        assert _PRONOUN_PATTERNS.search("this") is not None
        assert _PRONOUN_PATTERNS.search("that") is not None
        assert _PRONOUN_PATTERNS.search("the above") is not None

    def test_no_pronoun(self):
        assert _PRONOUN_PATTERNS.search("机器学习") is None
        assert _PRONOUN_PATTERNS.search("deep learning") is None
