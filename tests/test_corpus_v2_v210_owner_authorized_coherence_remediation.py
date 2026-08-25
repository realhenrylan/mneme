"""v2.0.10 coherence-remediation candidate: RED-first contract tests."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

import scripts.corpus_v2_v210_owner_authorized_coherence_remediation as p


ROOT = Path(__file__).resolve().parents[1]
V209 = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.9-owner-authorized-final-dependency-closed-retirement"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _recompute_self_hash(manifest: dict) -> str:
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    text = json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _copy_candidate(tmp_path: Path) -> Path:
    """Copy exactly the v2.0.9 candidate and its authorised triage inputs."""
    dest = tmp_path / "candidate"
    shutil.copytree(V209, dest)
    return dest


def _build(tmp_path: Path):
    candidate = _copy_candidate(tmp_path)
    out = tmp_path / "out"
    result = p.run(out_dir=out, candidate_dir=candidate)
    return candidate, out, result


def test_preflight_accepts_exact_v209_authorized_inputs(tmp_path):
    candidate = _copy_candidate(tmp_path)

    checks = p.preflight(candidate_dir=candidate)

    assert checks["case_count"] == 137
    assert checks["evidence_count"] == 144
    assert checks["strict_covered"] == checks["strict_passed"] == 144
    assert checks["repair_case_ids"] == list(p.REPAIR_CASE_IDS)
    assert checks["retirement"]["scenario"]["executable"] is True
    assert checks["mixed_033"]["byte_identical"] is True


def test_builds_the_authorized_v210_candidate_with_exact_counts(tmp_path):
    _, out, result = _build(tmp_path)

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert result["manifest"] == manifest
    assert manifest["gate_verdict"] == p.GATE_OK
    assert manifest["revision_status"] == "CANDIDATE"
    assert manifest["activation_blocked"] is True
    assert manifest["human_reviewed"] is False
    assert manifest["overlay_generated"] is False
    assert manifest["split_reseal_required"] is True
    assert manifest["v2_1_entered"] is False
    assert manifest["counts"] == {
        "case_before": 137,
        "case_after": 136,
        "evidence_before": 144,
        "evidence_after": 148,
        "same_source_evidence_added": 6,
        "retired_cases": 1,
        "retired_evidence": 1,
        "duplicate_evidence_removed": 1,
    }
    assert {path.name for path in out.iterdir()} == set(p.OUTPUT_FILES)


def test_manifest_self_hash_and_every_output_sha_are_valid(tmp_path):
    _, out, _ = _build(tmp_path)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["manifest_sha256"] == _recompute_self_hash(manifest)
    assert all(_sha(out / name) == digest
               for name, digest in manifest["outputs"].items())


def test_only_authorized_draft_row_is_removed_and_others_are_byte_identical(tmp_path):
    candidate, out, _ = _build(tmp_path)
    before = {json.loads(line)["id"]: line
              for line in (candidate / "draft-after.jsonl").read_text(
                  encoding="utf-8").splitlines() if line.strip()}
    after = {json.loads(line)["id"]: line
             for line in (out / "draft-after.jsonl").read_text(
                 encoding="utf-8").splitlines() if line.strip()}

    assert set(before) - set(after) == {"multi-019"}
    assert all(after[cid] == line for cid, line in before.items()
               if cid != "multi-019")


def test_evidence_changes_are_only_retirement_deduplication_and_six_fixed_spans(tmp_path):
    candidate, out, _ = _build(tmp_path)
    before_lines = (candidate / "evidence-after.jsonl").read_text(
        encoding="utf-8").splitlines()
    after_lines = (out / "evidence-after.jsonl").read_text(
        encoding="utf-8").splitlines()
    before = [json.loads(line) for line in before_lines if line.strip()]
    after = [json.loads(line) for line in after_lines if line.strip()]

    retained_before = [line for line in before_lines if line.strip()
                       and json.loads(line)["case_id"] != "multi-019"]
    mixed033 = [line for line in retained_before
                if json.loads(line)["case_id"] == "mixed-033"]
    assert len(mixed033) == 2 and mixed033[0] == mixed033[1]
    retained_before.remove(mixed033[1])
    assert after_lines[:len(retained_before)] == retained_before

    additions = after[len(retained_before):]
    assert len(additions) == 6
    assert [(row["case_id"], row["chunk_id"], row["raw_chunk_char_range"])
            for row in additions] == [
                (spec["case_id"], spec["chunk_id"],
                 {"start": spec["start"], "end": spec["end"]})
                for spec in p.REPAIR_SPECS
            ]
    assert len(after) == 148
    assert sum(row["case_id"] == "multi-019" for row in after) == 0
    assert sum(row["case_id"] == "mixed-033" for row in after) == 1
    assert len({json.dumps(row, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")) for row in after}) == len(after)


def test_added_evidence_is_raw_codepoint_strict_and_same_source(tmp_path):
    _, out, _ = _build(tmp_path)
    added = _jsonl(out / "added-same-source-evidence.jsonl")
    chunks = {row["chunk_id"]: row for row in _jsonl(p.CHUNKS_PATH)}

    assert len(added) == 6
    for row in added:
        start = row["raw_chunk_char_range"]["start"]
        end = row["raw_chunk_char_range"]["end"]
        assert row["coordinate_contract"] == "raw-codepoint-v1"
        assert chunks[row["chunk_id"]]["source"] == row["source_id"]
        assert chunks[row["chunk_id"]]["text"][start:end] == row["raw_evidence_span"]


def test_multi019_retirement_ledger_preserves_original_and_dependency_proof(tmp_path):
    candidate, out, _ = _build(tmp_path)
    retired = _jsonl(out / "retired-cases.jsonl")
    retired_evidence = _jsonl(out / "retired-evidence.jsonl")

    assert len(retired) == 1
    assert retired[0]["case_id"] == "multi-019"
    assert retired[0]["original_draft_row"]["id"] == "multi-019"
    assert retired[0]["retirement_scenario"]["executable"] is True
    assert retired[0]["retirement_scenario"]["dangling_ref_count"] == 0
    assert len(retired_evidence) == 1
    assert retired_evidence[0]["original_evidence_row"]["case_id"] == "multi-019"
    assert (candidate / "draft-after.jsonl").exists()


def test_data_quality_report_records_five_quality_dimensions_and_no_duplicate_rows(tmp_path):
    _, out, _ = _build(tmp_path)
    report = json.loads((out / "data-quality-report.json").read_text(
        encoding="utf-8"))
    checks = report["deterministic_data_quality_checks"]

    assert set(checks) == {"completeness", "uniqueness", "referential_integrity",
                           "continuity", "consistency"}
    assert all(value is True for group in checks.values() for value in group.values())
    assert report["skill"]["name"] == "data-analytics:analyze-data-quality"
    assert report["skill"]["available"] is True


def test_manifest_or_triage_drift_fails_closed_without_output(tmp_path):
    candidate = _copy_candidate(tmp_path)
    triage = candidate / "automated-review" / "coherence-reject-triage" / \
        "reject-root-cause-triage.jsonl"
    triage.write_text(triage.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    out = tmp_path / "out"

    with pytest.raises(p.RemediationError):
        p.run(out_dir=out, candidate_dir=candidate)

    assert not out.exists()


def test_unexpected_dependency_on_multi019_fails_closed(tmp_path):
    candidate = _copy_candidate(tmp_path)
    draft = candidate / "draft-after.jsonl"
    rows = _jsonl(draft)
    rows[0] = dict(rows[0])
    rows[0]["metadata"] = dict(rows[0].get("metadata") or {},
                               follow_up_to="multi-019")
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")) + "\n" for row in rows)
    draft.write_text(text, encoding="utf-8", newline="\n")
    manifest_path = candidate / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["outputs"]["draft-after.jsonl"] = _sha(draft)
    manifest["manifest_sha256"] = _recompute_self_hash(manifest)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1,
                                        sort_keys=True) + "\n", encoding="utf-8",
                             newline="\n")
    out = tmp_path / "out"

    with pytest.raises(p.RemediationError):
        p.run(out_dir=out, candidate_dir=candidate)

    assert not out.exists()


def test_two_builds_are_byte_identical_and_no_review_or_activation_artifacts_exist(tmp_path):
    candidate = _copy_candidate(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    p.run(out_dir=first, candidate_dir=candidate)
    p.run(out_dir=second, candidate_dir=candidate)

    assert {path.name for path in first.iterdir()} == {path.name for path in second.iterdir()}
    for path in first.iterdir():
        assert path.read_bytes() == (second / path.name).read_bytes(), path.name
    forbidden = {"automated-review", "automated-overlay.json", "active", "split", "v2.1"}
    assert not ({path.name for path in first.iterdir()} & forbidden)


def test_cli_build_succeeds(tmp_path):
    out = tmp_path / "out"

    assert p.main(["build", "--out-dir", str(out)]) == 0
    assert (out / "manifest.json").exists()
