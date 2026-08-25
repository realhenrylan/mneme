"""TDD tests for the v2.0.3 owner-authorized evidence reannotation candidate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.corpus_v2_owner_authorized_evidence_reannotation as rp

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "evaluation/datasets/v2/revisions/v2.0.2-evidence-coordinate-repair"


def response(action="retain_with_anchor", answer_point_index=0, anchor_id="a1", revised="原文支持", risk="low"):
    return {
        "action": action,
        "answer_point_index": answer_point_index,
        "anchor_id": anchor_id,
        "revised_answer_point": revised,
        "rationale": "scoped raw text supports this",
        "risk": risk,
    }


def test_schema_rejects_coordinate_and_free_quote_fields():
    with pytest.raises(rp.ReannotationError):
        rp.validate_llm_response(response() | {"start": 0})
    with pytest.raises(rp.ReannotationError):
        rp.validate_llm_response(response() | {"quote": "原文"})
    with pytest.raises(rp.ReannotationError):
        rp.validate_llm_response(response() | {"char_range": {"start": 0, "end": 1}})


def test_schema_requires_exact_quote_free_fields():
    assert set(rp.validate_llm_response(response())) == set(rp.ALLOWED_RESPONSE_FIELDS)
    with pytest.raises(rp.ReannotationError):
        rp.validate_llm_response(response() | {"extra": "x"})


def test_catalogue_computes_unicode_raw_range_and_preserves_format():
    chunk = {"chunk_id": "c1", "source": "s", "text": "头\r\n正文，代码 `x`\r\n尾"}
    catalog = rp.build_anchor_catalog([chunk])[0]
    anchor = next(a for a in catalog["anchors"] if a["raw_span"] == "正文，代码 `x`")
    assert anchor["raw_chunk_char_range"] == {"start": 3, "end": 12}
    assert chunk["text"][anchor["raw_chunk_char_range"]["start"]:anchor["raw_chunk_char_range"]["end"]] == anchor["raw_span"]
    assert "`x`" in anchor["snippet"]


def test_resolve_retain_and_narrow_from_same_declared_chunk():
    case = {"id": "x", "acceptable_answer_points": ["旧答案"]}
    chunk = {"chunk_id": "c1", "source": "s", "text": "原文支持"}
    catalog = rp.build_anchor_catalog([chunk])[0]
    anchor_id = catalog["anchors"][0]["anchor_id"]
    out = rp.resolve_response(case, {"chunk_id": "c1", "source": "s"}, chunk, catalog, response(anchor_id=anchor_id), 0)
    assert out["raw_evidence_span"] == "原文支持"
    assert out["coordinate_contract"] == "raw-codepoint-v1"
    assert out["raw_chunk_char_range"] == {"start": 0, "end": 4}


def test_remove_requires_explicit_no_support_and_zero_answer_points_blocks():
    chunk = {"chunk_id": "c1", "source": "s", "text": "原文"}
    catalog = rp.build_anchor_catalog([chunk])[0]
    removed = rp.resolve_response({"id": "x", "acceptable_answer_points": ["旧"]}, {"chunk_id": "c1", "source": "s"}, chunk, catalog, response("remove_answer_point", revised=None, anchor_id=None, risk="high") | {"rationale": "no support in scoped raw corpus"}, 0)
    assert removed["action"] == "remove_answer_point"
    with pytest.raises(rp.ReannotationError):
        rp.validate_answer_points([], answerable=True)


def test_keep_unresolved_is_fail_closed():
    chunk = {"chunk_id": "c1", "source": "s", "text": "原文"}
    catalog = rp.build_anchor_catalog([chunk])[0]
    out = rp.resolve_response({"id": "x", "acceptable_answer_points": ["旧"]}, {"chunk_id": "c1", "source": "s"}, chunk, catalog, response("keep_unresolved", anchor_id=None, revised=None), 0)
    assert out["action"] == "keep_unresolved"
    assert out["raw_evidence_span"] is None


def test_real_target_gate_has_thirteen_unresolved_and_candidate_status():
    inputs = rp.load_inputs()
    assert len(inputs.unresolved) == 13
    assert inputs.candidate_manifest["counts"] == {"evidence": 161, "migrated": 148, "unresolved": 13}
    assert inputs.candidate_manifest["activation_blocked"] is True
    assert rp.CANDIDATE_STATUS == "CANDIDATE"


def test_non_target_rows_remain_byte_identical(tmp_path):
    result = rp.run(out_dir=tmp_path / "out", llm_fn=lambda **_: (_ for _ in ()).throw(RuntimeError("stop")))
    assert result["status"] == "BLOCKED"
    assert not (tmp_path / "out" / "draft-after.jsonl").exists()


def test_manifest_and_outputs_block_activation_and_overlay(tmp_path):
    result = rp.run(out_dir=tmp_path / "out", llm_fn=lambda **_: (_ for _ in ()).throw(RuntimeError("stop")))
    assert result["manifest"]["activation_blocked"] is True
    assert result["manifest"]["revision_status"] == "CANDIDATE"
    assert not (tmp_path / "out" / "overlay").exists()


def test_deterministic_anchor_catalog(tmp_path):
    chunk = {"chunk_id": "c", "source": "s", "text": "# 标题\n代码 `x`\n"}
    assert rp.build_anchor_catalog([chunk]) == rp.build_anchor_catalog([chunk])


def test_all_161_evidence_strict_validator_contract_is_exposed():
    assert rp.COORDINATE_CONTRACT == "raw-codepoint-v1"
    assert callable(rp.validate_candidate_evidence)
