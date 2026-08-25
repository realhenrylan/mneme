"""TDD tests for v2.0.2 raw-codepoint evidence coordinates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import corpus_v2_evidence_coordinate_repair as repair


ROOT = Path(__file__).resolve().parents[1]


def test_raw_codepoint_range_preserves_markdown_and_code() -> None:
    text = "标题\r\n```\r\nfrom package import specific_submodule\r\n```\r\n值：&s1"
    start = text.index("from package")
    span = repair.build_raw_span(text, start, start + len("from package import specific_submodule"))
    assert span == "from package import specific_submodule"
    assert repair.display_snippet(span) == span


def test_unicode_offsets_are_codepoint_offsets() -> None:
    text = "中文，\u00a0 代码"
    start = text.index("中文")
    result = repair.locate_unique_raw(text, "中文，\u00a0 代码")
    assert result == (start, len(text))


def test_duplicate_match_is_unresolved() -> None:
    with pytest.raises(repair.CoordinateUnresolved, match="multiple"):
        repair.locate_unique_raw("same\n same", "same")


def test_invalid_range_and_empty_snippet_fail_closed() -> None:
    with pytest.raises(repair.CoordinateUnresolved):
        repair.validate_raw_record("chunk", "source", "text", {"start": 5, "end": 2}, "x")
    with pytest.raises(repair.CoordinateUnresolved):
        repair.locate_unique_raw("text", "")


def test_real_input_has_161_rows_and_12_legacy_direct_matches() -> None:
    rows = repair.load_jsonl(repair.DEFAULT_EVIDENCE)
    assert len(rows) == 161
    chunks = repair.load_chunks(repair.DEFAULT_CHUNKS)
    direct = 0
    for row in rows:
        text = chunks[row["chunk_id"]]["text"]
        cr = row["char_range"]
        if cr and text[cr["start"]:cr["end"]] == row["snippet"]:
            direct += 1
    assert direct == 12


def test_unresolved_blocks_activation() -> None:
    assert repair.activation_allowed(1, 161) is False
    assert repair.activation_allowed(0, 161) is True


def test_manifest_self_hash_and_deterministic_relative_outputs(tmp_path: Path) -> None:
    body = {"outputs": {"a": "x"}, "activation_blocked": True}
    manifest = repair.build_manifest(body)
    assert repair.verify_manifest(manifest)
    assert "manifest_sha256" in manifest


def test_source_mismatch_is_unresolved() -> None:
    with pytest.raises(repair.CoordinateUnresolved, match="source"):
        repair.validate_source("expected", "actual")
