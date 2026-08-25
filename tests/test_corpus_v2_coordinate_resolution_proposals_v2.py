"""TDD tests for quote-only coordinate proposal generation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.corpus_v2_coordinate_resolution_proposals_v2 as rp

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "evaluation/datasets/v2/revisions/v2.0.2-evidence-coordinate-repair"


def response(quote="正文"):
    return {
        "action": "add_exact_raw_evidence",
        "declared_chunk_id": "c1",
        "evidence_quote": quote,
        "rationale": "原文引文建议",
        "risk": "需要所有者确认",
        "owner_decision_required": True,
    }


def test_quote_schema_rejects_coordinate_fields():
    with pytest.raises(rp.QuoteSchemaError):
        rp.validate_quote_response(response() | {"start": 0})
    with pytest.raises(rp.QuoteSchemaError):
        rp.validate_quote_response(response() | {"char_range": {"start": 0, "end": 2}})


def test_quote_schema_accepts_only_declared_fields():
    parsed = rp.validate_quote_response(response())
    assert parsed["evidence_quote"] == "正文"
    assert "start" not in parsed and "end" not in parsed


@pytest.mark.parametrize("quote", ["", "不存在", "正\n文", "正文"])
def test_local_anchor_is_strict_and_fail_closed(quote):
    chunk = {"chunk_id": "c1", "source": "s", "text": "正文正文"}
    result = rp.anchor_quote(response(quote), chunk)
    if quote == "正文":
        assert result["anchor_match_count"] == 2
        assert result["raw_evidence_span"] is None
        assert result["action"] == "keep_unresolved"
    else:
        assert result["raw_evidence_span"] is None
        assert result["action"] == "keep_unresolved"


def test_unique_quote_gets_program_computed_raw_range_only():
    chunk = {"chunk_id": "c1", "source": "s", "text": "头\r\n正文，代码 `x`\r\n尾"}
    result = rp.anchor_quote(response("正文，代码 `x`"), chunk)
    assert result["action"] == "add_exact_raw_evidence"
    assert result["raw_chunk_char_range"] == {"start": 3, "end": 12}
    assert result["raw_evidence_span"] == "正文，代码 `x`"
    assert chunk["text"][result["raw_chunk_char_range"]["start"]:result["raw_chunk_char_range"]["end"]] == result["evidence_quote"]
    assert result["anchor_algorithm_version"] == rp.ANCHOR_ALGORITHM_VERSION


def test_declared_chunk_mismatch_stays_unresolved():
    item = response("正文") | {"declared_chunk_id": "other"}
    result = rp.anchor_quote(item, {"chunk_id": "c1", "source": "s", "text": "正文"})
    assert result["action"] == "keep_unresolved"
    assert result["raw_evidence_span"] is None


def test_quote_schema_rejects_semantic_extra_fields_and_bad_owner_flag():
    with pytest.raises(rp.QuoteSchemaError):
        rp.validate_quote_response(response() | {"recommendation": "自动修复"})
    with pytest.raises(rp.QuoteSchemaError):
        rp.validate_quote_response(response() | {"owner_decision_required": False})


def test_output_rows_remain_owner_gated():
    row = rp.serialize_proposal(
        {"case_id": "x", "chunk_id": "c1", "source_id": "s"},
        response("正文"),
        {"action": "keep_unresolved", "anchor_match_count": 0, "raw_evidence_span": None,
         "raw_chunk_char_range": None, "anchor_algorithm_version": rp.ANCHOR_ALGORITHM_VERSION},
    )
    assert row["auto_applicable"] is False
    assert row["requires_owner_authorization"] is True
    assert row["proposal_status"] == "LLM_ASSISTED_OWNER_DECISION_REQUIRED"


def test_main_schema_prompt_forbids_coordinate_fields():
    assert '"start"' not in rp.SYSTEM_PROMPT
    assert '"end"' not in rp.SYSTEM_PROMPT
    assert '"char_range"' not in rp.SYSTEM_PROMPT
    assert "evidence_quote" in rp.SYSTEM_PROMPT
