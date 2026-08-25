"""TDD tests for the v2.0.4 conservative reannotation candidate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.corpus_v2_v204_conservative_reannotation as rp

ROOT = Path(__file__).resolve().parents[1]


def test_target_groups_are_exact_and_disjoint():
    groups = rp.TARGET_GROUPS
    assert set().union(*map(set, groups.values())) == set(rp.EXPECTED_CASE_IDS)
    assert sum(map(len, groups.values())) == 13
    assert all(len(a & b) == 0 for i, a in enumerate(map(set, groups.values())) for b in list(map(set, groups.values()))[i + 1 :])


def test_anchor_catalog_preserves_unicode_raw_ranges():
    chunk = {"chunk_id": "c", "source": "s", "text": "头\r\n正文，代码 `x`\r\n尾"}
    anchor = next(a for a in rp.build_anchor_catalog([chunk])[0]["anchors"] if a["raw_span"] == "正文，代码 `x`")
    assert chunk["text"][anchor["raw_chunk_char_range"]["start"] : anchor["raw_chunk_char_range"]["end"]] == anchor["raw_span"]
    assert anchor["raw_chunk_char_range"] == {"start": 3, "end": 12}


def test_model_schema_rejects_coordinates_and_quotes():
    base = {"action": "retain_with_anchor", "answer_point_index": 0, "anchor_id": "c::a0000", "rationale": "direct", "risk": "low"}
    with pytest.raises(rp.ReannotationError):
        rp.validate_llm_response(base | {"quote": "原文", "revised_answer_point": None})
    with pytest.raises(rp.ReannotationError):
        rp.validate_llm_response(base | {"revised_answer_point": None, "start": 0})


def test_conservative_answer_point_is_local_anchor_text_only():
    chunk = {"chunk_id": "c", "source": "s", "text": "原文\r\n第二行"}
    catalog = rp.build_anchor_catalog([chunk])[0]
    response = {"action": "retain_with_anchor", "answer_point_index": 0, "anchor_id": catalog["anchors"][0]["anchor_id"], "rationale": "direct", "risk": "low"}
    resolved = rp.resolve_anchor_response(response, chunk, catalog, original_answer="旧表述", preserve_original=False)
    assert resolved["revised_answer_point"] == "原文"
    assert resolved["raw_evidence_span"] == "原文"


def test_invalid_anchor_fails_closed():
    chunk = {"chunk_id": "c", "source": "s", "text": "原文"}
    catalog = rp.build_anchor_catalog([chunk])[0]
    with pytest.raises(rp.ReannotationError):
        rp.resolve_anchor_response({"action": "retain_with_anchor", "answer_point_index": 0, "anchor_id": "bad", "rationale": "direct", "risk": "low"}, chunk, catalog, original_answer="旧", preserve_original=False)


def test_real_preflight_has_exact_thirteen_targets():
    inputs = rp.load_inputs()
    assert len(inputs.unresolved) == 13
    assert set(inputs.target_case_ids) == set(rp.EXPECTED_CASE_IDS)


def test_failure_writes_no_after_files(tmp_path):
    result = rp.run(out_dir=tmp_path / "out", llm_fn=lambda **_: (_ for _ in ()).throw(RuntimeError("stop")))
    assert result["status"] == "BLOCKED"
    assert not (tmp_path / "out" / "draft-after.jsonl").exists()
    assert not (tmp_path / "out" / "evidence-after.jsonl").exists()


def test_candidate_metadata_is_activation_blocked(tmp_path):
    result = rp.run(out_dir=tmp_path / "out", llm_fn=lambda **_: (_ for _ in ()).throw(RuntimeError("stop")))
    assert result["manifest"]["revision_status"] == "CANDIDATE"
    assert result["manifest"]["activation_blocked"] is True
    assert result["manifest"]["human_reviewed"] is False
    assert not (tmp_path / "out" / "overlay").exists()
