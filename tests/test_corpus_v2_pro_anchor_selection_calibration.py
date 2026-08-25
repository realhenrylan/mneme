"""TDD tests for the read-only v2.0.4 Pro anchor calibration."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.corpus_v2_pro_anchor_selection_calibration as rp


def test_pro_only_contract_and_exact_targets():
    assert rp.MODEL == "deepseek-v4-pro"
    assert rp.TEMPERATURE == 0.0
    assert rp.MAX_TOKENS == 8000
    assert rp.MAX_RETRIES == 3
    assert len(rp.EXPECTED_CASE_IDS) == 13


def test_payload_contains_only_allowed_model_inputs():
    chunk = {"chunk_id": "c", "source": "s", "text": "头\r\n原文 anchor\r\n尾"}
    catalog = rp.build_anchor_catalog([chunk])[0]
    payload = rp.build_payload("问题", ["答案"], catalog)
    assert set(payload) == {"query", "answer_points", "anchors"}
    assert set(payload["anchors"][0]) == {"anchor_id", "raw_span"}
    encoded = json.dumps(payload, ensure_ascii=False)
    for forbidden in ("case_id", "source", "chunk_id", "start", "end", "char_range", "verdict"):
        assert forbidden not in encoded


def test_response_schema_is_strict_and_action_specific():
    valid = {"action": "no_valid_anchor", "answer_point_index": 0, "anchor_id": None, "rationale": "无直接支持", "risk": "high"}
    assert rp.validate_model_response(valid) == valid
    with pytest.raises(rp.CalibrationError):
        rp.validate_model_response(valid | {"quote": "原文"})
    with pytest.raises(rp.CalibrationError):
        rp.validate_model_response(valid | {"action": "select_anchor"})
    with pytest.raises(rp.CalibrationError):
        rp.validate_model_response(valid | {"anchor_id": "c::a0000"})


def test_local_validation_proves_unicode_raw_range_and_ownership():
    chunk = {"chunk_id": "c", "source": "s", "text": "头\r\n正文\r\n尾"}
    catalog = rp.build_anchor_catalog([chunk])[0]
    anchor = next(a for a in catalog["anchors"] if a["raw_span"] == "正文")
    result = rp.validate_anchor_selection({"action": "select_anchor", "answer_point_index": 0, "anchor_id": anchor["anchor_id"], "rationale": "direct", "risk": "low"}, chunk, catalog)
    assert result["valid"] is True
    assert chunk["text"][result["raw_chunk_char_range"]["start"]:result["raw_chunk_char_range"]["end"]] == "正文"
    with pytest.raises(rp.CalibrationError):
        rp.validate_anchor_selection({"action": "select_anchor", "answer_point_index": 0, "anchor_id": "other::a0000", "rationale": "x", "risk": "low"}, chunk, catalog)


def test_run_with_stub_writes_only_calibration_outputs(tmp_path):
    def stub(**kwargs):
        assert kwargs["model"] == rp.MODEL
        assert kwargs["temperature"] == 0.0
        assert kwargs["max_tokens"] == 8000
        assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
        return json.dumps({"action": "no_valid_anchor", "answer_point_index": 0, "anchor_id": None, "rationale": "none", "risk": "high"}), rp.MODEL

    result = rp.run(out_dir=tmp_path / "out", llm_fn=stub)
    assert result["status"] == "CALIBRATED"
    assert (tmp_path / "out" / "pro-anchor-selections.jsonl").exists()
    assert not (tmp_path / "out" / "draft-after.jsonl").exists()
    assert not (tmp_path / "out" / "evidence-after.jsonl").exists()
    assert not (tmp_path / "out" / "overlay").exists()
    assert result["summary"]["no_valid_anchor"] == 13


def test_failure_cleans_final_output_directory(tmp_path):
    def fail(**_):
        raise TimeoutError("timeout")

    with pytest.raises(rp.CalibrationError):
        rp.run(out_dir=tmp_path / "out", llm_fn=fail)
    assert not (tmp_path / "out").exists()
