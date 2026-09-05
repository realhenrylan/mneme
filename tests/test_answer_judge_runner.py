"""M3 judge runner 单元测试：输入抽取 / 密封自哈希 / fail-closed / 跑批。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.answer_judge_runner import (
    extract_judge_inputs,
    run_judge,
    write_judge_sealed,
)


def _m2_row(case_id="c1", query_type="single_fact", point_texts=("p1", "p2"),
            answer="答案文本", should_refuse=False, verdicts=("miss", "hit")):
    return {
        "case_id": case_id,
        "query_type": query_type,
        "language": "zh",
        "should_refuse": should_refuse,
        "answer": answer,
        "answer_hit": {
            "effective_point_count": len(point_texts),
            "hit_count": sum(1 for v in verdicts if v == "hit"),
            "point_results": [
                {"point_text": p, "normalized": p, "verdict": v}
                for p, v in zip(point_texts, verdicts)
            ],
        },
    }


def test_extract_judge_inputs_only_miss_with_context() -> None:
    """抽取面：只取机械 miss 要点，携带 answer/point/should_refuse。"""
    rows = [
        _m2_row("c1", verdicts=("miss", "hit")),
        _m2_row("c2", verdicts=("miss", "miss"), should_refuse=True),
    ]
    inputs = extract_judge_inputs(rows)
    assert len(inputs) == 3
    for inp in inputs:
        assert inp["point_text"] in ("p1", "p2")
        assert inp["answer"] == "答案文本"
        assert "context" not in inp  # judge 不读 context
    assert all(i["case_id"] == "c1" for i in inputs[:1])
    assert inputs[1]["should_refuse"] is True and inputs[2]["should_refuse"] is True


def test_run_judge_injected_call_fn_all_ok() -> None:
    """注入 call_fn：全部合法响应 → 行数=输入数，字段落位。"""
    from evaluation.answer_judge import JudgePointResult

    def fake(messages, max_tokens):
        return '{"verdict": "miss", "evidence": "答案文本"}'

    results = run_judge([
        {"case_id": "c1", "query_type": "single_fact", "language": "zh",
         "should_refuse": False, "point_text": "p1", "answer": "答案文本"},
        {"case_id": "c2", "query_type": "multi_turn", "language": "zh",
         "should_refuse": False, "point_text": "p2", "answer": "答案文本"},
    ], call_fn=fake, progress=False)
    assert len(results) == 2
    assert results[0].case_id == "c1" and results[0].query_type == "single_fact"
    assert results[0].judge_verdict == "miss"
    assert results[1].case_id == "c2"


def test_write_judge_sealed_refuses_existing_dir(tmp_path) -> None:
    """输出目录已存在 → fail-closed RuntimeError，不覆盖。"""
    agg = {"judged_count": 1}
    from evaluation.answer_judge import JudgePointResult
    result = JudgePointResult(
        case_id="c1", query_type="x", point_text="p", mechanical_verdict="miss",
        judge_verdict="hit", evidence="e", attempts=1, contract_error=False)
    out = tmp_path / "sealed"
    out.mkdir()
    with pytest.raises(RuntimeError):
        write_judge_sealed(
            out, judge_results=[result], aggregate=agg, token_summary={},
            m2_dir=tmp_path, m2_outcomes_sha256="abc",
            dataset_name="v2.1", dataset_path=tmp_path / "v2.1.jsonl",
            dataset_sha256="def", judge_model="m")


def test_write_judge_sealed_self_hash_matches(tmp_path) -> None:
    """密封自哈希：去 manifest_sha256 字段重算 body 哈希 == 记录值。"""
    import hashlib
    from evaluation.answer_judge_runner import _dump
    from evaluation.answer_judge import JudgePointResult

    result = JudgePointResult(
        case_id="c1", query_type="x", point_text="p", mechanical_verdict="miss",
        judge_verdict="hit", evidence="e", attempts=1, contract_error=False)
    write_judge_sealed(
        tmp_path / "sealed", judge_results=[result],
        aggregate={"judged_count": 1}, token_summary={},
        m2_dir=tmp_path, m2_outcomes_sha256="abc",
        dataset_name="v2.1", dataset_path=tmp_path / "v2.1.jsonl",
        dataset_sha256="def", judge_model="m")

    manifest = json.loads((tmp_path / "sealed" / "manifest.json")
                          .read_text(encoding="utf-8"))
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    recomputed = hashlib.sha256(_dump(body).encode("utf-8")).hexdigest()
    assert manifest["manifest_sha256"] == recomputed
    # 快照要求：M2 outcomes 与数据集 SHA 落在 manifest
    assert manifest["m2_outcomes_sha256"] == "abc"
    assert manifest["dataset_sha256"] == "def"
    # 逐要点行落盘
    rows = [json.loads(l) for l in (tmp_path / "sealed" / "outcomes-judge.jsonl")
            .read_text(encoding="utf-8").splitlines()]
    assert rows[0]["case_id"] == "c1" and rows[0]["contract_error"] is False
