"""Tests for the owner-decision-only v2.0.2 coordinate proposal package."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.corpus_v2_coordinate_resolution_proposals as rp

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "evaluation/datasets/v2/revisions/v2.0.2-evidence-coordinate-repair"
UNRESOLVED = BASE / "coordinate-unresolved.jsonl"
MIGRATION = BASE / "coordinate-migration.jsonl"
MANIFEST = BASE / "manifest.json"
DRAFT = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"
CHUNKS = ROOT / "data/v2-corpus/chunks/chunks.jsonl"


def test_real_candidate_gate_and_thirteen_rows_without_llm(tmp_path):
    with pytest.raises(rp.ProposalError, match="LLM"):  # no implicit fallback
        rp.run(out_dir=tmp_path / "out", llm_fn=lambda **_: None)
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").iterdir())


def test_blind_payload_has_no_history_verdict_or_split_leaks():
    row = {"case_id": "x", "chunk_id": "c", "source_id": "s", "reason": "snippet not found"}
    payload = rp.build_blind_payload(
        {"id": "x", "query": "问题", "acceptable_answer_points": ["答案"], "should_refuse": False},
        row, {"chunk_id": "c", "source": "s", "text": "原文"}, "旧片段",
    )
    dumped = json.dumps(payload, ensure_ascii=False).lower()
    assert "case_id" not in payload
    assert not any(term in dumped for term in ("decision", "reviewer", "split", "holdout", "confirmed", "reject"))


def test_model_identity_and_json_are_fail_closed():
    assert rp.MODEL == "deepseek-v4-flash"
    with pytest.raises(rp.ProposalError):
        rp.parse_model_response("{}", returned_model="deepseek-v4-pro")
    with pytest.raises(rp.ProposalError):
        rp.parse_model_response("not json", returned_model=rp.MODEL)


def test_probe_uses_only_flash_and_fixed_budget(monkeypatch):
    calls = []

    def fake_llm(messages, model, temperature, max_tokens):
        calls.append((model, temperature, max_tokens))
        return (json.dumps({
            "action": "keep_unresolved", "recommendation": "保留",
            "risk": "高", "owner_decisions": [], "evidence": [],
            "rationale": "无法证明",
        }, ensure_ascii=False), model)

    result = rp.probe(llm_fn=fake_llm)
    assert result["model"] == "deepseek-v4-flash"
    assert calls == [("deepseek-v4-flash", 0.0, 8000)]


def test_raw_span_rebuild_and_format_never_auto_apply():
    chunk = {"chunk_id": "c", "source": "s", "text": "头\n正文\n尾"}
    proposal = {"action": "add_exact_raw_evidence", "raw_span": {"start": 2, "end": 5, "span": "正文\n"}}
    checked = rp.validate_raw_span(proposal, chunk)
    assert checked["raw_span_proof"] is True
    assert rp.auto_applicable({"root_cause_category": "format_transform_requires_policy"}) is False


def _valid_response():
    return {
        "action": "keep_unresolved",
        "recommendation": "保留",
        "risk": "高",
        "owner_decisions": [],
        "evidence": [],
        "rationale": "无法证明",
    }


def test_strict_json_accepts_safe_outer_wrappers():
    raw = json.dumps(_valid_response(), ensure_ascii=False)
    for content in (raw, "\\ufeff  " + raw + "  ", "```json\n" + raw + "\n```", "```\n" + raw + "\n```", "说明文字：\n" + raw):
        assert rp.parse_model_json_strict(content, rp.MODEL)["action"] == "keep_unresolved"


@pytest.mark.parametrize("content", [
    json.dumps(_valid_response()) + json.dumps(_valid_response()),
    json.dumps(_valid_response())[:-1],
    "```json\\n" + json.dumps(_valid_response()),
    '{"action":"keep_unresolved","recommendation":"\\q","risk":"高","owner_decisions":[],"evidence":[],"rationale":"x"}',
    json.dumps(_valid_response()) + "\\n说明",
])
def test_strict_json_rejects_ambiguous_or_invalid_content(content):
    with pytest.raises(rp.StrictJSONParseError):
        rp.parse_model_json_strict(content, rp.MODEL)


def test_strict_json_rejects_schema_and_model_errors():
    invalid = _valid_response()
    invalid.pop("rationale")
    with pytest.raises(rp.StrictJSONParseError):
        rp.parse_model_json_strict(json.dumps(invalid), rp.MODEL)
    invalid = _valid_response()
    invalid["evidence"] = {}
    with pytest.raises(rp.StrictJSONParseError):
        rp.parse_model_json_strict(json.dumps(invalid), rp.MODEL)
    with pytest.raises(rp.ProposalError, match="model identity"):
        rp.parse_model_json_strict(json.dumps(_valid_response()), "deepseek-v4-pro")


def test_system_prompt_forbids_reasoning_and_markdown_fence():
    prompt = rp.SYSTEM_PROMPT
    assert "不要输出任何思考" in prompt
    assert "直接输出" in prompt
    assert "代码块" in prompt


def test_empty_response_is_fail_closed_with_safe_diagnostic():
    with pytest.raises(rp.StrictJSONParseError, match="empty"):
        rp.parse_model_json_strict("", rp.MODEL)


def test_format_errors_retry_same_flash_model_three_attempts():
    calls = []
    valid = json.dumps(_valid_response(), ensure_ascii=False)

    def fake_llm(messages, model, temperature, max_tokens):
        calls.append((model, temperature, max_tokens))
        return ("not json" if len(calls) < 3 else valid, model)

    result = rp.probe(llm_fn=fake_llm)
    assert result["retries_used"] == 2
    assert calls == [(rp.MODEL, 0.0, 8000)] * 3


def test_call_forwards_extra_body_to_gateway(monkeypatch):
    """真实调用路径必须关闭推理模型的 thinking，防止预算耗尽。"""
    captured = {}

    def fake_llm_call(call_type, messages, model=None, temperature=0.0, max_tokens=1000,
                      timeout=None, max_retries=3, stream=False, extra_body=None):
        captured.update(model=model, temperature=temperature, max_tokens=max_tokens, extra_body=extra_body)
        fake_message = type("M", (), {"content": "{}", "reasoning_content": ""})
        fake_choice = type("C", (), {"message": fake_message(), "finish_reason": "stop"})
        fake_response = type("R", (), {"model": model, "choices": [fake_choice()], "usage": None})()
        return fake_response, type("Rec", (), {"retries_used": 0})()

    monkeypatch.setattr("scripts.corpus_v2_coordinate_resolution_proposals.llm_call", fake_llm_call)
    content, model, retries = rp._call([{"role": "user", "content": "x"}], None)
    assert captured["extra_body"] == rp.EXTRA_BODY
    assert captured["model"] == rp.MODEL
    assert captured["temperature"] == 0.0
    assert captured["max_tokens"] == 8000
    assert content == "{}"


def test_run_uses_triage_category_mapping(tmp_path):
    """proposals 的 root_cause_category 必须来自 triage 产物，而非空字符串。"""
    import scripts.corpus_v2_coordinate_resolution_proposals as rp_mod

    def fake_llm(messages, model, temperature, max_tokens):
        return (json.dumps({
            "action": "keep_unresolved", "recommendation": "保留",
            "risk": "高", "owner_decisions": [], "evidence": [],
            "rationale": "无法证明",
        }, ensure_ascii=False), model)

    result = rp.run(out_dir=tmp_path / "out", llm_fn=fake_llm)
    by_case = {r["case_id"]: r for r in result["proposals"]}
    assert by_case["mixed-022"]["root_cause_category"] == "format_transform_requires_policy"
    assert by_case["zh-054"]["root_cause_category"] == "format_transform_requires_policy"
    assert by_case["zh-023"]["root_cause_category"] == "semantic_or_content_drift"
    counts = result["summary"]["category_counts"]
    assert counts == {"format_transform_requires_policy": 2,
                      "semantic_or_content_drift": 11,
                      "whitespace_or_line_ending_only": 0,
                      "legacy_range_disambiguable_duplicate": 0,
                      "source_or_chunk_integrity_problem": 0}


def test_manifest_self_hash():
    body = {"version": "x", "activation_blocked": True}
    manifest = rp.build_manifest(body)
    assert rp.verify_manifest(manifest)
