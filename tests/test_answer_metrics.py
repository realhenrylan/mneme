"""answer-hit 机械指标（containment 族）单元测试。

口径（章程 M1 + owner 批示）：要点经空白/大小写归一后被答案归一文本
包含 → hit；空要点显式排除（不计分母）；answer_hit_rate = hit 数 /
有效要点数，有效要点数为 0 时无指标意义（None）。
"""

import pytest

from evaluation.answer_metrics import (
    AnswerHitResult,
    compute_answer_hit,
    normalize_for_containment,
)


class TestNormalizeForContainment:
    def test_lowercases_and_collapses_whitespace(self):
        assert normalize_for_containment("  Import  Fibo\tAs\nFIB ") == "import fibo as fib"

    def test_empty_string_stays_empty(self):
        assert normalize_for_containment("   ") == ""


class TestComputeAnswerHit:
    def test_point_contained_verbatim_is_hit(self):
        result = compute_answer_hit(
            "列表和字符串都支持索引和切片操作。",
            ["都支持索引和切片操作"],
        )
        assert result.hit_count == 1
        assert result.effective_point_count == 1
        assert result.answer_hit_rate == 1.0
        assert result.point_results[0].verdict == "hit"

    def test_case_difference_still_hits_after_normalization(self):
        result = compute_answer_hit(
            "Use IMPORT FIBO AS FIB to alias the module.",
            ["import fibo as fib"],
        )
        assert result.hit_count == 1
        assert result.answer_hit_rate == 1.0

    def test_whitespace_difference_still_hits_after_normalization(self):
        result = compute_answer_hit(
            "两者都是序列类型，\n且支持  索引。",
            ["两者都是序列类型"],
        )
        assert result.hit_count == 1

    def test_absent_point_is_miss(self):
        result = compute_answer_hit(
            "答案是 42。",
            ["南京总面积6587.02平方公里"],
        )
        assert result.hit_count == 0
        assert result.effective_point_count == 1
        assert result.answer_hit_rate == 0.0
        assert result.point_results[0].verdict == "miss"

    def test_blank_point_is_explicitly_excluded_from_denominator(self):
        result = compute_answer_hit(
            "答案里完全没提第二个要点。",
            ["第一个要点也不在", "   "],
        )
        assert result.effective_point_count == 1
        assert result.hit_count == 0
        assert result.answer_hit_rate == 0.0
        assert result.point_results[1].verdict == "excluded_empty"

    def test_mixed_hit_and_miss_yields_partial_rate(self):
        result = compute_answer_hit(
            "使用 import fibo as fib 即可。",
            ["使用 import fibo as fib", "用 as 后的名称绑定导入模块"],
        )
        assert result.hit_count == 1
        assert result.effective_point_count == 2
        assert result.answer_hit_rate == pytest.approx(0.5)

    def test_all_points_blank_returns_none_rate(self):
        result = compute_answer_hit("任意答案。", ["", "   "])
        assert result.effective_point_count == 0
        assert result.answer_hit_rate is None

    def test_empty_point_list_returns_none_rate(self):
        result = compute_answer_hit("任意答案。", [])
        assert result.effective_point_count == 0
        assert result.answer_hit_rate is None

    def test_result_is_dataclass_with_audit_fields(self):
        result = compute_answer_hit("包含要点A。", ["要点A"])
        assert isinstance(result, AnswerHitResult)
        assert result.point_results[0].point_text == "要点A"
