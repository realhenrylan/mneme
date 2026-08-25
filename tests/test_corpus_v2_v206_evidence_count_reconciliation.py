"""TDD tests for the v2.0.6 candidate evidence-count reconciliation.

Read-only reconciliation: independently recounts evidence rows, partitions
evidence-after into mutually exclusive categories, verifies strict-validator
coverage and every raw span, and checks the manifest/SHA chain.  Never writes
candidate data; verdict is RECONCILIATION_BLOCKED unless every one of the 162
rows is covered by the strict validator and passes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.corpus_v2_v206_evidence_count_reconciliation as rp
from scripts import corpus_v2_evidence_coordinate_repair as coord


@pytest.fixture(scope="module")
def rec(tmp_path_factory):
    out = tmp_path_factory.mktemp("evcount")
    result = rp.run(out_dir=out)
    return result, out


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_evidence_line_counts(rec):
    result, out = rec
    assert result["counts"]["evidence_before"] == 159
    assert result["counts"]["evidence_after"] == 162
    assert result["counts"]["retired_evidence"] == 1
    assert len(_jsonl(out / "strict-validation-coverage.jsonl")) == 162


def test_arithmetic_159_to_162_is_exact(rec):
    _, out = rec
    result = None  # placeholder, verdict data is inside the json output
    data = json.loads((out / "evidence-count-reconciliation.json").read_text(encoding="utf-8"))
    counts = data["counts"]
    assert counts["target_old_evidence_removed"] == 5
    assert counts["newly_added_raw_evidence"] == 8
    assert counts["arithmetic_holds"] is True
    assert 159 - 5 + 8 == 162
    # set-based identity check: after == (before - target_old) | newly_added
    assert data["set_check"]["after_equals_before_minus_removed_plus_added"] is True
    assert data["set_check"]["removed_and_added_disjoint"] is True


def test_partition_is_mutually_exclusive_and_complete(rec):
    _, out = rec
    data = json.loads((out / "evidence-count-reconciliation.json").read_text(encoding="utf-8"))
    partition = data["partition"]
    assert partition["raw_codepoint_v1_active"] == 161
    assert partition["legacy_coordinate"] == 1
    assert partition["unresolved_non_active"] == 0
    assert partition["malformed_missing_coordinate"] == 0
    assert partition["total"] == 162
    assert partition["partition_exact"] is True
    assert sum(partition[k] for k in ("raw_codepoint_v1_active", "legacy_coordinate",
                                      "unresolved_non_active", "malformed_missing_coordinate")) == 162
    coverage = _jsonl(out / "strict-validation-coverage.jsonl")
    assert sum(1 for row in coverage if row["category"] == "raw_codepoint_v1_active") == 161
    legacy = [row for row in coverage if row["category"] == "legacy_coordinate"]
    assert len(legacy) == 1
    assert legacy[0]["case_id"] == "zh-037"
    assert legacy[0]["chunk_id"] == "32c427fb50e2_chunk_33"


def test_strict_validator_coverage_sets(rec):
    _, out = rec
    data = json.loads((out / "evidence-count-reconciliation.json").read_text(encoding="utf-8"))
    sv = data["strict_validation"]
    assert sv["input_set_count"] == 161
    assert sv["covered_count"] == 161
    assert sv["passed_count"] == 161
    assert sv["failed_count"] == 0
    assert sv["uncovered_count"] == 1
    coverage = _jsonl(out / "strict-validation-coverage.jsonl")
    uncovered = [row for row in coverage if not row["covered"]]
    assert len(uncovered) == 1
    assert uncovered[0]["case_id"] == "zh-037"
    assert uncovered[0]["category"] == "legacy_coordinate"


def test_every_covered_row_proves_raw_span(rec):
    chunks = coord.load_chunks(rp.CHUNKS)
    _, out = rec
    coverage = _jsonl(out / "strict-validation-coverage.jsonl")
    for row in coverage:
        if not row["covered"]:
            continue
        rng = row["raw_chunk_char_range"]
        assert chunks[row["chunk_id"]]["text"][rng["start"]:rng["end"]] == row["raw_evidence_span"], row
        assert row["passed"] is True
        assert row["invalid"] is False


def test_invalid_rows_listed_precisely(rec):
    _, out = rec
    data = json.loads((out / "evidence-count-reconciliation.json").read_text(encoding="utf-8"))
    invalid = data["non_strictly_legal_rows"]
    assert len(invalid) == 1
    assert invalid[0]["case_id"] == "zh-037"
    assert invalid[0]["identity"]["chunk_id"] == "32c427fb50e2_chunk_33"
    assert invalid[0]["category"] == "legacy_coordinate"
    assert "coordinate_contract" in invalid[0]["reason"]
    coverage = _jsonl(out / "strict-validation-coverage.jsonl")
    invalid_rows = [row for row in coverage if row["invalid"]]
    assert len(invalid_rows) == 1
    assert invalid_rows[0]["case_id"] == "zh-037"


def test_target_multi_span_rows_covered_and_passed(rec):
    _, out = rec
    data = json.loads((out / "evidence-count-reconciliation.json").read_text(encoding="utf-8"))
    targets = data["target_rows"]
    assert targets["zh-035"] == {"rows": 6, "covered": 6, "passed": 6}
    assert targets["mixed-022"] == {"rows": 1, "covered": 1, "passed": 1}
    assert targets["mixed-028"] == {"rows": 1, "covered": 1, "passed": 1}


def test_v206_manifest_sha_verified(rec):
    _, out = rec
    data = json.loads((out / "evidence-count-reconciliation.json").read_text(encoding="utf-8"))
    manifest_checks = data["manifest_checks"]
    assert manifest_checks["v206_manifest_self_hash_ok"] is True
    assert manifest_checks["v206_outputs_sha_match_disk"] is True
    assert manifest_checks["v206_manifest_status"] == "CANDIDATE"
    # reconciliation manifest self-hash matches disk
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    expected = hashlib.sha256((json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")).hexdigest()
    assert manifest["manifest_sha256"] == expected
    for name, sha in manifest["outputs"].items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == sha


def test_input_sha_invariance(rec):
    _, out = rec
    data = json.loads((out / "evidence-count-reconciliation.json").read_text(encoding="utf-8"))
    checks = data["manifest_checks"]
    assert checks["draft_unchanged"] is True
    assert checks["chunks_unchanged"] is True
    assert checks["chunk_manifest_unchanged"] is True
    assert checks["v205_manifest_unchanged"] is True
    v205 = json.loads(rp.V205_MANIFEST.read_text(encoding="utf-8"))
    assert checks["draft_sha"] == v205["inputs"]["draft"]
    assert checks["chunks_sha"] == v205["inputs"]["chunks"]
    assert checks["chunk_manifest_sha"] == v205["inputs"]["chunk_manifest"]


def test_verdict_is_blocked_with_exact_failing_conditions(rec):
    _, out = rec
    data = json.loads((out / "evidence-count-reconciliation.json").read_text(encoding="utf-8"))
    assert data["status"] == "RECONCILIATION_BLOCKED"
    conditions = data["pass_conditions"]
    assert conditions["all_pass"] is False
    assert conditions["evidence_after_count == 162"] is True
    assert conditions["active_evidence_count == 162"] is True
    assert conditions["strict_validator_covered_count == 162"] is False
    assert conditions["strict_validator_passed_count == 162"] is False
    assert conditions["uncovered_count == 0"] is False
    assert conditions["invalid_count == 0"] is False
    assert data["counts"]["active_evidence_count"] == 162
    assert data["counts"]["raw_codepoint_v1_count"] == 161
    assert data["counts"]["legacy_count"] == 1


def test_exact_four_output_files_and_inputs_untouched(rec):
    _, out = rec
    assert sorted(p.name for p in out.iterdir()) == [
        "evidence-count-reconciliation.json",
        "manifest.json",
        "reconciliation-report.md",
        "strict-validation-coverage.jsonl",
    ]
    for name in ("overlay", "active", "v2.1", "split", "lock", "review"):
        assert not any(name in p.name.lower() for p in out.iterdir())
    # read-only: no candidate or historical file may change
    inputs = {
        "evidence_after": rp.EVIDENCE_AFTER_206, "evidence_before": rp.EVIDENCE_BEFORE_206,
        "retired_evidence": rp.RETIRED_EVIDENCE_206, "draft_after": rp.DRAFT_AFTER_206,
        "v206_manifest": rp.V206_MANIFEST, "v205_manifest": rp.V205_MANIFEST,
        "draft": rp.DRAFT, "chunks": rp.CHUNKS, "chunk_manifest": rp.CHUNK_MANIFEST,
    }
    before = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in inputs.items()}
    rp.run(out_dir=out / "second")
    after = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in inputs.items()}
    assert before == after


def test_deterministic_rebuild_byte_identical(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    rp.run(out_dir=a)
    rp.run(out_dir=b)
    assert sorted(p.name for p in a.iterdir()) == sorted(p.name for p in b.iterdir())
    for name in sorted(p.name for p in a.iterdir()):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
