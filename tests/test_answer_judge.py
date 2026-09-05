"""M3 受约束 judge 协议单元测试（TDD：校验函数先行 RED→GREEN）。

覆盖（owner 批示协议逐条）：
- verdict 词表外 → 重试（fail-closed）
- evidence 为空 → 重试
- evidence 非答案归一连续子串 → 重试
- JSON 解析失败 → 重试
- ≤3 次尝试仍失败 → contract_error=true（按 miss 计入）
- 修正口径两个公式（partial 计 0.5 / 计 0）与分歧率
- call_type="judge" 进入网关调用记录（mock 网关返回合法 JSON）
"""

from __future__ import annotations

import pytest

from evaluation.answer_judge import (
    JUDGE_MAX_ATTEMPTS,
    JUDGE_SYSTEM_PROMPT,
    JUDGE_VERDICTS,
    JudgeContractError,
    JudgePointResult,
    aggregate_judge_results,
    build_judge_messages,
    judge_point_with_llm,
    parse_judge_response,
)

# ── 词表与提示（单一事实源）──────────────────────────────────────

def test_judge_verdicts_whitelist_exactly_three_values() -> None:
    """外置词表 = {hit, miss, partial}，三值枚举，单一事实源。"""
    assert JUDGE_VERDICTS == ("hit", "miss", "partial")


def test_system_prompt_contains_refusal_rule() -> None:
    """判定语义必须包含「拒答/语义式陈述一律 miss」规则（协议原意）。"""
    assert "miss" in JUDGE_SYSTEM_PROMPT
    assert "拒答" in JUDGE_SYSTEM_PROMPT


# ── parse_judge_response：合法响应 ───────────────────────────────

def test_parse_judge_response_valid_hit() -> None:
    """合法响应：verdict 在词表内 + evidence 非空且在答案内。"""
    answer = "列表和字符串都是序列类型，支持索引和切片。"
    parsed = parse_judge_response(
        '{"verdict": "hit", "evidence": "列表和字符串都是序列类型"}', answer)
    assert parsed.verdict == "hit"
    assert parsed.evidence == "列表和字符串都是序列类型"


def test_parse_evidence_normalization_matches_containment_family() -> None:
    """evidence 空白归一后是 answer 归一文本的连续子串即通过（与机械指标同口径）。"""
    answer = "列表和字符串  都是序列\n类型。"
    parsed = parse_judge_response(
        '{"verdict": "partial", "evidence": "列表和字符串 都是序列 类型"}', answer)
    assert parsed.verdict == "partial"


# ── parse_judge_response：fail-closed 校验 ───────────────────────

def test_parse_rejects_verdict_outside_vocab() -> None:
    """词表外 verdict（如 yes/no/true）→ JudgeContractError。"""
    with pytest.raises(JudgeContractError):
        parse_judge_response('{"verdict": "unknown", "evidence": "x"}', "x")


def test_parse_rejects_empty_evidence() -> None:
    """evidence 为空 → JudgeContractError。"""
    with pytest.raises(JudgeContractError):
        parse_judge_response('{"verdict": "hit", "evidence": ""}', "x")


def test_parse_rejects_evidence_not_substring_of_answer() -> None:
    """evidence 不是答案归一文本的连续子串（篡改/拼凑）→ JudgeContractError。"""
    with pytest.raises(JudgeContractError):
        parse_judge_response(
            '{"verdict": "hit", "evidence": "完全不存在的句子"}',
            "列表和字符串都是序列类型")


def test_parse_rejects_invalid_json() -> None:
    """JSON 解析失败（截断/多文本）→ JudgeContractError。"""
    with pytest.raises(JudgeContractError):
        parse_judge_response('{"verdict": "hit", "evidence": "列表"', "列表是序列")


# ── judge_point_with_llm：重试协议 ───────────────────────────────

def test_success_no_retry() -> None:
    """合法响应（mock call_fn）：attempts=1，verdict/evidence 正确，无契约错误。"""
    calls: list[list[dict]] = []

    def fake(messages, max_tokens):
        calls.append(messages)
        return '{"verdict": "hit", "evidence": "列表是序列"}'

    r = judge_point_with_llm(
        "列表是序列。", "列表是序列类型", call_fn=fake)
    assert r.judge_verdict == "hit"
    assert r.evidence == "列表是序列"
    assert r.attempts == 1
    assert r.contract_error is False
    assert len(calls) == 1


def test_retry_on_out_of_vocab_then_success_with_reason_in_prompt() -> None:
    """词表外 verdict → 重试；第二次成功；重试提示附上次失败原因。"""
    calls: list[list[dict]] = []

    def fake(messages, max_tokens):
        calls.append(messages)
        if len(calls) == 1:
            return '{"verdict": "yes", "evidence": "列表是序列"}'
        return '{"verdict": "hit", "evidence": "列表是序列"}'

    r = judge_point_with_llm("列表是序列。", "列表是序列类型", call_fn=fake)
    assert r.judge_verdict == "hit"
    assert r.attempts == 2
    assert r.contract_error is False
    # 第二次调用的 user 消息必须附带失败原因（可重试性可审计）
    joined = " ".join(m["content"] for m in calls[1] if m["role"] == "user")
    assert "verdict" in joined and "词表" in joined or "allowed" in joined.lower()


def test_retry_on_gateway_failure_then_success() -> None:
    """网关失败（call_fn 返回 None，取消/超时路径）→ 计入重试，第二次成功。"""
    calls = 0

    def fake(messages, max_tokens):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None  # 网关失败（超时/取消）
        return '{"verdict": "miss", "evidence": "列表是序列"}'

    r = judge_point_with_llm("列表是序列。", "列表是序列类型", call_fn=fake)
    assert r.judge_verdict == "miss"
    assert r.attempts == 2


def test_contract_error_after_three_failures() -> None:
    """≤3 次尝试全部不合法 → contract_error=true，judge_verdict=None，attempts=3。"""
    def fake(messages, max_tokens):
        return '{"verdict": "yes", "evidence": "x"}'

    r = judge_point_with_llm("候选答案。", "要点", call_fn=fake)
    assert r.attempts == JUDGE_MAX_ATTEMPTS
    assert r.contract_error is True
    assert r.judge_verdict is None
    assert r.evidence is None


def test_call_type_judge_recorded_in_gateway(monkeypatch) -> None:
    """call_type="judge" 进入网关调用记录（mock 网关返回合法 JSON）。"""
    from src.llm_gateway import (
        LLMCallRecord, _record_call, clear_call_records, get_call_records,
    )
    from evaluation import answer_judge

    def fake_llm_call_safe(call_type, messages, **kwargs):
        assert call_type == "judge"
        _record_call(LLMCallRecord(call_type="judge", model="fake-model", latency_ms=1.0))
        return '{"verdict": "miss", "evidence": "列表是序列"}', None

    monkeypatch.setattr(answer_judge, "llm_call_safe", fake_llm_call_safe)
    clear_call_records()
    try:
        r = judge_point_with_llm("列表是序列。", "无关要点", call_fn=None)
        assert r.judge_verdict == "miss"
        records = get_call_records()
        assert any(rec.call_type == "judge" for rec in records)
    finally:
        clear_call_records()


# ── 聚合：修正口径两个公式 ───────────────────────────────────────

def _m2_row(case_id, effective, hit_count, query_type="single_fact"):
    """构造一条 M2 outcomes 行（聚合派生所需的最小字段）。"""
    points = []
    for i in range(effective):
        verdict = "hit" if i < hit_count else "miss"
        points.append({"point_text": f"p{i}", "normalized": f"p{i}",
                       "verdict": verdict})
    return {
        "case_id": case_id,
        "query_type": query_type,
        "should_refuse": False,
        "answer_hit": {
            "effective_point_count": effective,
            "hit_count": hit_count,
            "point_results": points,
        },
    }


def _judge_row(case_id, point_text, judge_verdict, contract_error=False,
               query_type="single_fact", **extra):
    return {
        "case_id": case_id,
        "query_type": query_type,
        "point_text": point_text,
        "judge_verdict": judge_verdict,
        "contract_error": contract_error,
        "evidence": "e",
        "attempts": 1,
        **extra,
    }


def test_aggregate_corrected_rates_and_divergence() -> None:
    """修正口径两公式 + 分歧率：
    构造 4 要点（机械 hit 1 + miss 3），judge: hit 1 / partial 1 / miss 1 →
    修正0.5=(1+1+0.5)/4=0.625；保守=(1+1)/4=0.5；分歧率=2/3。"""
    m2_rows = [
        _m2_row("c1", 2, 1),
        _m2_row("c2", 2, 0),
    ]
    judge_rows = [
        _judge_row("c1", "p1", "hit"),
        _judge_row("c1", "p2", "partial"),
        _judge_row("c2", "p0", "miss"),
    ]
    agg = aggregate_judge_results(m2_rows, judge_rows)
    assert agg["total_points"] == 4
    assert agg["mechanical_hit_count"] == 1
    assert agg["corrected_rate_partial_05"] == pytest.approx(0.625)
    assert agg["corrected_rate_partial_0"] == pytest.approx(0.5)
    assert agg["divergence_rate"] == pytest.approx(2 / 3)
    assert agg["judged_count"] == 3
    assert agg["count_hit"] == 1 and agg["count_partial"] == 1 and agg["count_miss"] == 1


def test_aggregate_contract_error_counts_as_miss() -> None:
    """contract_error 行按 miss 计入：不进修正分子，contract_error_rate 单列。"""
    m2_rows = [_m2_row("c1", 2, 1), _m2_row("c2", 2, 0)]
    judge_rows = [
        _judge_row("c1", "p1", "hit"),
        _judge_row("c1", "p2", "partial"),
        _judge_row("c2", "p0", None, contract_error=True),
    ]
    agg = aggregate_judge_results(m2_rows, judge_rows)
    # W=1 只出现在 contract_error_rate，不进两个修正分子/分母
    assert agg["corrected_rate_partial_05"] == pytest.approx(0.625)
    assert agg["corrected_rate_partial_0"] == pytest.approx(0.5)
    assert agg["contract_error_rate"] == pytest.approx(1 / 3)
    assert agg["count_contract_error"] == 1
    assert agg["judged_count"] == 3
