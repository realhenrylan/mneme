"""M5b al3-refusal-judge-v1 协议测试（TDD RED→GREEN）。

一个测试一个行为：校验链（JSON/词表/evidence 子串）、重试协议、
契约错误保守计入、聚合口径、词表口径对照。
"""

from __future__ import annotations

import json

import pytest

from evaluation.refusal_judge import (
    JUDGE_MAX_ATTEMPTS,
    REFUSAL_VERDICTS,
    RefusalJudgeContractError,
    aggregate_refusal_results,
    build_refusal_messages,
    judge_refusal_with_llm,
    parse_refusal_response,
)


ANSWER = "根据提供的文档内容，没有找到关于 Git 版本控制的内容。文档仅提到 Git 在 venv 中被提及。[S3]"


class TestParseRefusalResponse:
    def test_valid_refused_passes(self):
        text = json.dumps({"verdict": "refused", "evidence": "没有找到关于 Git 版本控制的内容"})
        parsed = parse_refusal_response(text, ANSWER)
        assert parsed.verdict == "refused"
        assert parsed.evidence == "没有找到关于 Git 版本控制的内容"

    def test_valid_answered_passes(self):
        text = json.dumps({"verdict": "answered", "evidence": "文档仅提到 Git 在 venv 中被提及"})
        parsed = parse_refusal_response(text, ANSWER)
        assert parsed.verdict == "answered"

    def test_verdict_outside_vocab_rejected(self):
        text = json.dumps({"verdict": "maybe", "evidence": "没有找到"})
        with pytest.raises(RefusalJudgeContractError, match="词表外"):
            parse_refusal_response(text, ANSWER)

    def test_empty_evidence_rejected(self):
        text = json.dumps({"verdict": "refused", "evidence": "  "})
        with pytest.raises(RefusalJudgeContractError, match="evidence 为空"):
            parse_refusal_response(text, ANSWER)

    def test_evidence_not_substring_rejected(self):
        text = json.dumps({"verdict": "refused", "evidence": "答案里没有这句话"})
        with pytest.raises(RefusalJudgeContractError, match="连续子串"):
            parse_refusal_response(text, ANSWER)

    def test_invalid_json_rejected(self):
        with pytest.raises(RefusalJudgeContractError, match="JSON 解析失败"):
            parse_refusal_response("not json", ANSWER)

    def test_non_object_json_rejected(self):
        with pytest.raises(RefusalJudgeContractError, match="不是 JSON 对象"):
            parse_refusal_response("[1, 2]", ANSWER)

    def test_evidence_whitespace_normalized_match(self):
        # 空白折叠后仍是连续子串（containment 族口径）
        text = json.dumps({"verdict": "refused",
                           "evidence": "没有找到关于 Git   版本控制的内容"})
        parsed = parse_refusal_response(text, ANSWER)
        assert parsed.verdict == "refused"

    def test_evidence_insensitive_to_markdown_bold(self):
        # RED 证据（M5b 冒烟 noanswer-026 三次尝试全失败）：答案含 markdown
        # 加粗 **没有找到**，归一化把 ** 变空白；judge 摘录时自然省略标记，
        # 逐字匹配系统性误报。al3 口径 = 空白不敏感 containment。
        answer = "根据提供的文档内容，**没有找到**关于 pandas 库的介绍。"
        text = json.dumps({"verdict": "refused",
                           "evidence": "没有找到关于 pandas 库的介绍"})
        parsed = parse_refusal_response(text, answer)
        assert parsed.verdict == "refused"

    def test_evidence_insensitive_to_backtick_code(self):
        answer = "文档中没有 `PRAGMA journal_mode` 的说明。"
        text = json.dumps({"verdict": "refused",
                           "evidence": "文档中没有 PRAGMA journal_mode 的说明"})
        parsed = parse_refusal_response(text, answer)
        assert parsed.verdict == "refused"


class TestJudgeRetryProtocol:
    def test_first_attempt_success(self):
        calls = []

        def fake(messages, max_tokens):
            calls.append(messages)
            return json.dumps({"verdict": "refused", "evidence": "没有找到关于 Git 版本控制的内容"})

        verdict, evidence, attempts, ce = judge_refusal_with_llm(
            "q", ANSWER, call_fn=fake)
        assert (verdict, attempts, ce) == ("refused", 1, False)
        assert len(calls) == 1

    def test_contract_violation_then_success(self):
        calls = []

        def fake(messages, max_tokens):
            calls.append(messages)
            if len(calls) == 1:
                return json.dumps({"verdict": "maybe", "evidence": "x"})
            return json.dumps({"verdict": "answered", "evidence": "文档仅提到 Git 在 venv 中被提及"})

        verdict, evidence, attempts, ce = judge_refusal_with_llm(
            "q", ANSWER, call_fn=fake)
        assert (verdict, attempts, ce) == ("answered", 2, False)
        # 重试提示附上次失败原因
        assert "上次输出无效" in calls[1][-1]["content"]

    def test_exhausted_retries_contract_error(self):
        def fake(messages, max_tokens):
            return json.dumps({"verdict": "maybe", "evidence": "x"})

        verdict, evidence, attempts, ce = judge_refusal_with_llm(
            "q", ANSWER, call_fn=fake)
        assert (verdict, evidence, ce) == (None, None, True)
        assert attempts == JUDGE_MAX_ATTEMPTS

    def test_gateway_failure_counts_as_attempt(self):
        calls = []

        def fake(messages, max_tokens):
            calls.append(messages)
            if len(calls) < 3:
                return None  # 网关失败
            return json.dumps({"verdict": "refused", "evidence": "没有找到关于 Git 版本控制的内容"})

        verdict, _, attempts, ce = judge_refusal_with_llm(
            "q", ANSWER, call_fn=fake)
        assert (verdict, attempts, ce) == ("refused", 3, False)


class TestBuildMessages:
    def test_contains_query_and_answer(self):
        messages = build_refusal_messages("查询X", ANSWER)
        assert messages[0]["role"] == "system"
        assert "查询X" in messages[1]["content"]
        assert ANSWER in messages[1]["content"]

    def test_retry_appends_failure_reason(self):
        messages = build_refusal_messages("q", ANSWER, last_failure="verdict 词表外")
        assert len(messages) == 3
        assert "verdict 词表外" in messages[2]["content"]


class TestAggregate:
    def test_empty(self):
        agg = aggregate_refusal_results([])
        assert agg["probe_count"] == 0
        assert agg["semantic_refusal_accuracy"] is None

    def test_mixed_rows(self):
        rows = [
            {"semantic_verdict": "refused", "contract_error": False, "lexical_verdict": False},
            {"semantic_verdict": "refused", "contract_error": False, "lexical_verdict": False},
            {"semantic_verdict": "answered", "contract_error": False, "lexical_verdict": False},
            {"semantic_verdict": None, "contract_error": True, "lexical_verdict": True},
        ]
        agg = aggregate_refusal_results(rows)
        assert agg["probe_count"] == 4
        assert agg["semantic_correct"] == 2
        assert agg["semantic_refusal_accuracy"] == 0.5
        assert agg["lexical_correct"] == 1
        assert agg["lexical_refusal_accuracy"] == 0.25
        assert agg["contract_error_count"] == 1
        assert agg["contract_error_rate"] == 0.25
        # 分歧：语义与词表口径不一致的 3 例（2 例语义 refused/词表 False +
        # 1 例语义 None（契约错误）/词表 True）
        assert agg["disagreement_count"] == 3

    def test_contract_error_counted_conservatively(self):
        # 契约错误（verdict=None）不算语义正确
        rows = [{"semantic_verdict": None, "contract_error": True, "lexical_verdict": False}]
        agg = aggregate_refusal_results(rows)
        assert agg["semantic_correct"] == 0
        assert agg["semantic_refusal_accuracy"] == 0.0


class TestVocabSingleSource:
    def test_vocab_is_two_values(self):
        assert REFUSAL_VERDICTS == ("refused", "answered")


class TestPromptContract:
    """防回归：v1.1 的「否定 + 解释该否定 = refused」条款必须存在于 prompt。"""

    def test_negation_with_explanation_clause_present(self):
        from evaluation.refusal_judge import REFUSAL_JUDGE_SYSTEM_PROMPT
        assert "否定 + 解释/引证该否定本身" in REFUSAL_JUDGE_SYSTEM_PROMPT

    def test_protocol_version_is_v1_1(self):
        from evaluation.refusal_judge import REFUSAL_JUDGE_PROTOCOL_VERSION
        assert REFUSAL_JUDGE_PROTOCOL_VERSION == "al3-refusal-judge-v1.1"
