"""TDD tests for the v2.0.7 owner-authorized redundant legacy evidence retirement.

Removes exactly one retained legacy coordinate row (zh-037 / chunk_33) from the
v2.0.6 candidate evidence set (162 -> 161).  The draft is untouched, no legacy
char_range is ever reinterpreted as a raw coordinate, and every gate is
fail-closed with zero output on failure.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.corpus_v2_v207_legacy_evidence_retirement as rp
from scripts import corpus_v2_evidence_coordinate_repair as coord


@pytest.fixture(scope="module")
def pack(tmp_path_factory):
    out = tmp_path_factory.mktemp("v207")
    result = rp.run(out_dir=out)
    return result, out


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _self_hash(manifest: dict) -> str:
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    return hashlib.sha256(
        (json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
    ).hexdigest()


EXPECTED_FILES = frozenset({
    "draft-before.jsonl", "draft-after.jsonl", "evidence-before.jsonl",
    "evidence-after.jsonl", "reannotation-diff.jsonl", "retired-legacy-evidence.jsonl",
    "coordinate-validation-report.json", "data-quality-report.json",
    "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md", "REPAIR_REPORT.md", "manifest.json",
})


def test_constants_fixed():
    assert rp.ACTOR == "OWNER_AUTHORIZED_REDUNDANT_LEGACY_EVIDENCE_RETIREMENT"
    assert rp.AUTHORIZATION_MARKER == "OWNER_AUTHORIZED_REDUNDANT_LEGACY_EVIDENCE_RETIREMENT"
    assert rp.RETIREMENT_REASON == "redundant_legacy_coordinate_superseded_by_raw_codepoint_v1_evidence"
    assert rp.TARGET_CASE_ID == "zh-037"
    assert rp.TARGET_CHUNK_ID == "32c427fb50e2_chunk_33"
    assert rp.TARGET_IDENTITY == "zh-037::32c427fb50e2_chunk_33::legacy"
    assert rp.CONTRACT == "raw-codepoint-v1"


def test_reconciliation_only_blocker_is_the_target_row():
    """Gate 1: the v2.0.6 reconciliation's only blocker is exactly this legacy row."""
    rec = json.loads((rp.RECONCILIATION_DIR / "evidence-count-reconciliation.json").read_text(encoding="utf-8"))
    assert rec["status"] == "RECONCILIATION_BLOCKED"
    assert len(rec["non_strictly_legal_rows"]) == 1
    row = rec["non_strictly_legal_rows"][0]
    assert row["evidence_identity"] == "zh-037::32c427fb50e2_chunk_33::legacy"
    assert row["category"] == "legacy_coordinate"
    assert rec["counts"]["evidence_after"] == 162
    assert rec["counts"]["raw_codepoint_v1_count"] == 161
    assert rec["counts"]["legacy_count"] == 1
    sv = rec["strict_validation"]
    assert sv["covered_count"] == 161 and sv["passed_count"] == 161
    assert sv["uncovered_count"] == 1 and sv["invalid_count"] == 1


def test_draft_unchanged_148_and_byte_identical_to_v206(pack):
    _, out = pack
    v206_draft = (rp.V206 / "draft-after.jsonl").read_text(encoding="utf-8")
    assert (out / "draft-before.jsonl").read_text(encoding="utf-8") == v206_draft
    assert (out / "draft-after.jsonl").read_text(encoding="utf-8") == v206_draft
    rows = _jsonl(out / "draft-after.jsonl")
    assert len(rows) == 148
    assert len({row["id"] for row in rows}) == 148


def test_evidence_162_to_161_exactly_one_line_removed(pack):
    _, out = pack
    before = _lines(out / "evidence-before.jsonl")
    after = _lines(out / "evidence-after.jsonl")
    assert len(before) == 162
    assert len(after) == 161
    legacy = json.loads(next(line for line in before if "coordinate_contract" not in json.loads(line)))
    assert legacy["case_id"] == "zh-037"
    assert legacy["chunk_id"] == "32c427fb50e2_chunk_33"
    legacy_line = json.dumps(legacy, ensure_ascii=False, sort_keys=True)
    assert before.count(legacy_line) == 1
    assert after == [line for line in before if line != legacy_line]


def test_retired_legacy_ledger_records_original_row_reason_and_successor(pack):
    _, out = pack
    ledger = _jsonl(out / "retired-legacy-evidence.jsonl")
    assert len(ledger) == 1
    row = ledger[0]
    assert row["evidence_identity"] == "zh-037::32c427fb50e2_chunk_33::legacy"
    assert row["retirement_reason"] == rp.RETIREMENT_REASON
    assert row["authorized_by"] == rp.AUTHORIZATION_MARKER
    assert row["retired_by"] == rp.ACTOR
    assert row["evidence_count_before"] == 162
    assert row["evidence_count_after"] == 161
    # The original row is preserved verbatim (round-trips to the exact source line).
    original = row["original_row"]
    before = _lines(out / "evidence-before.jsonl")
    assert json.dumps(original, ensure_ascii=False, sort_keys=True) in before
    assert original["case_id"] == "zh-037"
    assert original["chunk_id"] == "32c427fb50e2_chunk_33"
    assert "coordinate_contract" not in original
    assert original["char_range"] == {"start": 74, "end": 112}
    assert original["snippet"] == "内置函数 dir() 用于查找模块定义的名称。返回结果是经过排序的字符串列表"
    assert row["successor_evidence_identity"] == "zh-037::32c427fb50e2_chunk_32::raw-codepoint-v1"
    assert row["successor_raw_chunk_char_range"] == {"start": 1921, "end": 1931}
    assert row["successor_raw_evidence_span"] == "经过排序的字符串列表"


def test_legacy_range_never_reinterpreted_as_raw(pack):
    """The legacy char_range must be carried verbatim, never converted."""
    _, out = pack
    ledger = _jsonl(out / "retired-legacy-evidence.jsonl")[0]
    original = ledger["original_row"]
    assert original["char_range"] == {"start": 74, "end": 112}
    assert original["char_range_start"] == 74 and original["char_range_end"] == 112
    assert "raw_chunk_char_range" not in original
    assert "raw_evidence_span" not in original
    assert "coordinate_contract" not in original
    # Only the successor records raw coordinates.
    assert ledger["successor_raw_chunk_char_range"] == {"start": 1921, "end": 1931}


def test_successor_coverage_proof(pack):
    """Gates 3/4: zh-037 has a strict successor covering the retained answer point."""
    chunks = coord.load_chunks(rp.CHUNKS)
    _, out = pack
    after = _jsonl(out / "evidence-after.jsonl")
    zh037_raw = [row for row in after
                 if row["case_id"] == "zh-037" and row.get("coordinate_contract") == "raw-codepoint-v1"]
    assert len(zh037_raw) == 1
    successor = zh037_raw[0]
    coord.strict_validate_row(successor, chunks)
    chunk = chunks[successor["chunk_id"]]
    rng = successor["raw_chunk_char_range"]
    assert chunk["text"][rng["start"]:rng["end"]] == successor["raw_evidence_span"]
    draft = _jsonl(out / "draft-after.jsonl")
    points = next(row for row in draft if row["id"] == "zh-037")["acceptable_answer_points"]
    assert points == ["经过排序的字符串列表"]
    # Same case as the retired row and the raw span covers the answer point.
    assert successor["case_id"] == "zh-037"
    assert successor["raw_evidence_span"] == points[0]
    # The successor already existed byte-identically in v2.0.5 and v2.0.6.
    raw_lines = lambda rows: {json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows
                              if r.get("case_id") == "zh-037" and r.get("coordinate_contract") == "raw-codepoint-v1"}
    assert raw_lines(_jsonl(rp.V205 / "evidence-after.jsonl")) == raw_lines(_jsonl(rp.V206 / "evidence-after.jsonl"))
    assert raw_lines(_jsonl(rp.V206 / "evidence-after.jsonl")) == {json.dumps(successor, ensure_ascii=False, sort_keys=True)}


def test_strict_161_161_acceptance(pack):
    chunks = coord.load_chunks(rp.CHUNKS)
    _, out = pack
    after = _jsonl(out / "evidence-after.jsonl")
    assert len(after) == 161
    raw = [row for row in after if row.get("coordinate_contract") == "raw-codepoint-v1"]
    legacy = [row for row in after if row.get("coordinate_contract") != "raw-codepoint-v1"]
    assert len(raw) == 161
    assert len(legacy) == 0
    coord.strict_validate(raw, chunks)  # every row covered and passed
    report = json.loads((out / "coordinate-validation-report.json").read_text(encoding="utf-8"))
    assert report["strict_validation"] == "PASS"
    assert report["raw_rows_validated"] == 161
    assert report["legacy_rows_remaining"] == 0
    assert report["unresolved_rows"] == 0
    assert report["strict_validator_covered_count"] == 161
    assert report["strict_validator_passed_count"] == 161
    assert report["uncovered_count"] == 0
    assert report["invalid_count"] == 0


def test_all_answerable_cases_have_strict_legal_evidence(pack):
    _, out = pack
    after = _jsonl(out / "evidence-after.jsonl")
    covered = {row["case_id"] for row in after}
    draft = _jsonl(out / "draft-after.jsonl")
    missing = [row["id"] for row in draft
               if row.get("should_refuse") is not True and row["id"] not in covered]
    assert missing == []


def test_zh037_retains_answer_point_and_successor(pack):
    _, out = pack
    for source in (rp.V205 / "draft-after.jsonl", rp.V206 / "draft-after.jsonl", out / "draft-after.jsonl"):
        rows = _jsonl(source)
        zh037 = next(row for row in rows if row["id"] == "zh-037")
        assert zh037["acceptable_answer_points"] == ["经过排序的字符串列表"]
    after = _jsonl(out / "evidence-after.jsonl")
    raw = [r for r in after if r["case_id"] == "zh-037" and r.get("coordinate_contract") == "raw-codepoint-v1"]
    assert len(raw) >= 1


def test_inputs_unchanged_and_manifest_shas(pack):
    _, out = pack
    v206 = json.loads((rp.V206 / "manifest.json").read_text(encoding="utf-8"))
    assert v206["manifest_sha256"] == _self_hash(v206)
    for name in ("draft-after.jsonl", "evidence-after.jsonl"):
        assert v206["outputs"][name] == _sha(rp.V206 / name)
    for name, path in (("draft", rp.DRAFT), ("chunks", rp.CHUNKS), ("chunk_manifest", rp.CHUNK_MANIFEST)):
        assert v206["inputs"][name] == _sha(path)
    rec = json.loads((rp.RECONCILIATION_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert rec["manifest_sha256"] == _self_hash(rec)
    for name, sha in rec["outputs"].items():
        assert sha == _sha(rp.RECONCILIATION_DIR / name)


def test_single_legacy_gate_rejects_extra_or_missing_target():
    rows = _jsonl(rp.V206 / "evidence-after.jsonl")
    legacy = next(row for row in rows if "coordinate_contract" not in row)
    assert legacy["case_id"] == "zh-037"
    assert legacy["chunk_id"] == "32c427fb50e2_chunk_33"
    with pytest.raises(rp.LegacyRetirementError):
        rp._verify_single_legacy_target(rows + [dict(legacy)])
    with pytest.raises(rp.LegacyRetirementError):
        rp._verify_single_legacy_target([row for row in rows if row is not legacy])


def test_fail_closed_zero_output_on_gate_failure(tmp_path, monkeypatch):
    out = tmp_path / "build"
    monkeypatch.setattr(rp, "RECONCILIATION_JSON", tmp_path / "missing-reconciliation.json")
    with pytest.raises(rp.LegacyRetirementError):
        rp.run(out_dir=out)
    assert not out.exists()


def test_determinism_two_builds_byte_identical(tmp_path_factory):
    out1 = tmp_path_factory.mktemp("v207a")
    out2 = tmp_path_factory.mktemp("v207b")
    rp.run(out_dir=out1)
    rp.run(out_dir=out2)
    for name in EXPECTED_FILES:
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()


def test_exact_file_set_no_forbidden_outputs_manifest_self_hash(pack):
    _, out = pack
    assert {p.name for p in out.iterdir()} == EXPECTED_FILES
    assert not any(p.is_dir() for p in out.iterdir())
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_sha256"] == _self_hash(manifest)
    for name in EXPECTED_FILES - {"manifest.json"}:
        assert manifest["outputs"][name] == _sha(out / name)
    # The exact 11-file set is the proof that no overlay / active metadata /
    # v2.1 / review / split-config / locked-config artifact was generated
    # (REVIEW_AND_SPLIT_REBUILD_REQUIRED.md is a required advisory document).


def test_manifest_metadata_fixed(pack):
    _, out = pack
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["revision_status"] == "CANDIDATE"
    assert manifest["activation_blocked"] is True
    assert manifest["human_reviewed"] is False
    assert manifest["actor"] == "OWNER_AUTHORIZED_REDUNDANT_LEGACY_EVIDENCE_RETIREMENT"
    assert manifest["case_count_before"] == 148
    assert manifest["case_count_after"] == 148
    assert manifest["evidence_count_before"] == 162
    assert manifest["evidence_count_after"] == 161
    assert manifest["overlay_generated"] is False
    assert manifest["v2_1_entered"] is False
    assert manifest["counts"]["evidence_after"] == 161
    assert manifest["counts"]["legacy_retired"] == 1
    assert manifest["counts"]["case_after"] == 148


def test_reannotation_diff_records_single_removal(pack):
    _, out = pack
    diff = _jsonl(out / "reannotation-diff.jsonl")
    assert len(diff) == 1
    assert diff[0]["case_id"] == "zh-037"
    assert diff[0]["kind"] == "evidence_removed"
    assert diff[0]["evidence_identity"] == "zh-037::32c427fb50e2_chunk_33::legacy"
    assert diff[0]["reason"] == rp.RETIREMENT_REASON
    assert diff[0]["authorized_by"] == rp.AUTHORIZATION_MARKER
    assert diff[0]["successor_evidence_identity"] == "zh-037::32c427fb50e2_chunk_32::raw-codepoint-v1"
