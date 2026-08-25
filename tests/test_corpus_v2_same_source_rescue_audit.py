"""TDD tests for the deterministic v2.0.4 same-source rescue audit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.corpus_v2_same_source_rescue_audit as rp


def test_risk_case_ids_dynamic_export_is_exactly_ten():
    rows = rp.load_pack_rows()
    ids = rp.risk_case_ids(rows)
    assert len(ids) == 10
    assert all(rp.zero_answer_point_risk(row) for row in rows if row["case_id"] in ids)


def test_full_unique_match_roundtrip_preserves_raw_unicode():
    chunk_text = "头\r\n正文，代码 `x` 末尾"
    start, end = rp.locate_unique_raw(chunk_text, "正文，代码 `x`")
    assert chunk_text[start:end] == "正文，代码 `x`"


def test_ambiguous_duplicate_is_not_auto_usable():
    chunk_text = "重复 词 重复 词 结束"
    kind = rp.match_full(chunk_text, "重复 词")
    assert kind["category"] == "ambiguous_duplicate"


def test_full_vs_lexical_categories_are_distinct():
    # unique full match in one chunk
    a = rp.match_full("只有一处 目标文本 出现", "目标文本")
    assert a["category"] == "verbatim_full_answer_point_found"
    # keyword only in another chunk: must never claim support
    b = rp.match_full("目标 与 文本 分散", "目标文本")
    assert b["category"] != "verbatim_full_answer_point_found"


def test_suggestion_contract_is_owner_gated():
    for category in rp.CATEGORY_TO_SUGGESTION:
        suggestion = rp.suggest_for(category)
        assert suggestion["name"] in rp.SUGGESTIONS
        assert suggestion["requires_owner_authorization"] is True
        assert suggestion["auto_applicable"] is False


def test_scan_only_declared_source_and_out_of_scope_excluded():
    chunks = {
        "c1": {"chunk_id": "c1", "source": "s1", "text": "甲 文档 内容"},
        "c2": {"chunk_id": "c2", "source": "s1", "text": "其他 内容 唯一 目标 文本"},
        "c3": {"chunk_id": "c3", "source": "s2", "text": "其他 内容 唯一 目标 文本"},
    }
    result = rp.scan_case("case", "唯一 目标 文本", chunks, "c1", "s1")
    assert result["category"] == "verbatim_full_answer_point_found"
    assert result["best_candidate"]["chunk_id"] == "c2"
    assert all(c["scope"] == "out_of_scope" for c in result["out_of_scope_hits"])


def test_real_audit_has_ten_rows_and_read_only_outputs(tmp_path):
    result = rp.run(out_dir=tmp_path / "audit")
    assert result["status"] == "AUDIT_OK"
    rows = [json.loads(line) for line in (tmp_path / "audit" / "same-source-rescue-results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 10
    assert not list((tmp_path / "audit").glob("*after*"))
    assert not (tmp_path / "audit" / "overlay").exists()
    assert not (tmp_path / "audit" / "active").exists()


def test_audit_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    rp.run(out_dir=a)
    rp.run(out_dir=b)
    assert sorted(p.name for p in a.iterdir()) == sorted(p.name for p in b.iterdir())
    for name in sorted(p.name for p in a.iterdir()):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
