"""TDD tests for the deterministic v2.0.4 owner decision pack."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.corpus_v2_owner_decision_pack as rp


def test_target_groups_are_exact_and_disjoint():
    assert len(rp.EXPECTED_CASE_IDS) == 13
    assert sum(len(v) for v in rp.TARGET_GROUPS.values()) == 13
    assert set().union(*rp.TARGET_GROUPS.values()) == set(rp.EXPECTED_CASE_IDS)
    groups = list(rp.TARGET_GROUPS.values())
    assert all(not (groups[i] & groups[j]) for i in range(3) for j in range(i + 1, 3))


def test_anchor_ranges_reconstruct_original_unicode_text():
    chunk = {"chunk_id": "c", "source": "s", "text": "头\r\n正文，代码 `x`\r\n尾"}
    row = rp.build_context_row("case", chunk, rp.build_anchor_catalog([chunk])[0], "current")
    assert row["anchors"]
    anchor = next(a for a in row["anchors"] if a["raw_span"] == "正文，代码 `x`")
    assert chunk["text"][anchor["raw_chunk_char_range"]["start"]:anchor["raw_chunk_char_range"]["end"]] == anchor["raw_span"]


def test_scope_expansion_is_not_current_evidence():
    chunks = [
        {"chunk_id": "c1", "source": "s", "text": "声明 chunk"},
        {"chunk_id": "c2", "source": "s", "text": "其他 chunk"},
        {"chunk_id": "c3", "source": "other", "text": "外部"},
    ]
    result = rp.scope_candidates(chunks, "c1", "s")
    assert [x["chunk_id"] for x in result] == ["c2"]
    assert result[0]["status"] == "needs_scope_expansion"
    assert result[0]["current_evidence"] is False


def test_zero_answer_point_risk_is_explicit():
    case = {"acceptable_answer_points": ["only"], "should_refuse": False}
    assert rp.zero_answer_point_risk(case) is True
    assert rp.zero_answer_point_risk({"acceptable_answer_points": ["a", "b"], "should_refuse": False}) is False


def test_patch_template_has_exact_whitelist():
    template = rp.patch_template("zh-032")
    assert set(template) == {"owner_action", "revised_answer_point", "chosen_anchor_id", "owner_note"}


def test_real_pack_is_13_rows_and_read_only_outputs(tmp_path):
    result = rp.run(out_dir=tmp_path / "pack")
    assert result["status"] == "DECISION_PACK"
    out = tmp_path / "pack"
    rows = [json.loads(line) for line in (out / "owner-decision-pack.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 13
    assert not list(out.glob("*after*"))
    assert not (out / "overlay").exists()
    assert not (out / "active").exists()
    assert all(set(json.loads(line)) == {"owner_action", "revised_answer_point", "chosen_anchor_id", "owner_note"} for line in (out / "candidate-patch-template.jsonl").read_text(encoding="utf-8").splitlines())


def test_pack_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    rp.run(out_dir=a)
    rp.run(out_dir=b)
    assert sorted(p.name for p in a.iterdir()) == sorted(p.name for p in b.iterdir())
    for name in sorted(p.name for p in a.iterdir()):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
