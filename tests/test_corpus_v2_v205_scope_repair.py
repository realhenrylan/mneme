"""TDD tests for the v2.0.5 owner-authorized deterministic scope repair."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.corpus_v2_v205_scope_repair as rp


RETIRED = {"zh-033"}
EXPANDED = {"zh-037"}
NARROWED = {"mixed-029", "zh-023", "zh-026", "zh-029", "zh-036", "zh-054", "zh-055"}
UNRESOLVED = {"zh-035", "zh-032", "mixed-022", "mixed-028"}


def test_action_partition_is_exact():
    assert RETIRED | EXPANDED | NARROWED | UNRESOLVED == set(rp.ALL_TARGETS)
    assert len(RETIRED) == 1 and len(EXPANDED) == 1 and len(NARROWED) == 7 and len(UNRESOLVED) == 4


def test_case_count_150_to_149_and_retired_ledger(tmp_path):
    result = rp.run(out_dir=tmp_path / "out")
    before = [json.loads(line) for line in (tmp_path / "out" / "draft-before.jsonl").read_text(encoding="utf-8").splitlines()]
    after = [json.loads(line) for line in (tmp_path / "out" / "draft-after.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(before) == 150 and len(after) == 149
    retired = [json.loads(line) for line in (tmp_path / "out" / "retired-cases.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["case_id"] for r in retired] == ["zh-033"]
    assert retired[0]["reason"] == "no_same_source_candidate_found_after_owner_authorized_rescue_scan"
    assert all(r["id"] != "zh-033" for r in after)
    assert result["counts"]["case_before"] == 150 and result["counts"]["case_after"] == 149


def test_narrowed_answer_points_equal_raw_span(tmp_path):
    rp.run(out_dir=tmp_path / "out")
    after = [json.loads(line) for line in (tmp_path / "out" / "draft-after.jsonl").read_text(encoding="utf-8").splitlines()]
    additions = [json.loads(line) for line in (tmp_path / "out" / "raw-scope-additions.jsonl").read_text(encoding="utf-8").splitlines()]
    narrowed = {a["case_id"]: a for a in additions if a["case_id"] in NARROWED}
    assert len(narrowed) == 7
    by_case = {row["id"]: row for row in after}
    for case_id, add in narrowed.items():
        assert by_case[case_id]["acceptable_answer_points"][0] == add["raw_span"].replace("\r\n", "\n").replace("\r", "\n")


def test_zh037_answer_point_unchanged_and_new_evidence_added(tmp_path):
    rp.run(out_dir=tmp_path / "out")
    before = {json.loads(line)["id"]: json.loads(line) for line in (tmp_path / "out" / "draft-before.jsonl").read_text(encoding="utf-8").splitlines()}
    after = {json.loads(line)["id"]: json.loads(line) for line in (tmp_path / "out" / "draft-after.jsonl").read_text(encoding="utf-8").splitlines()}
    assert after["zh-037"]["acceptable_answer_points"] == before["zh-037"]["acceptable_answer_points"]
    additions = [json.loads(line) for line in (tmp_path / "out" / "raw-scope-additions.jsonl").read_text(encoding="utf-8").splitlines()]
    zh037_adds = [a for a in additions if a["case_id"] == "zh-037"]
    assert len(zh037_adds) == 1
    assert zh037_adds[0]["candidate_type"] == "full"


def test_no_cross_source_and_ranges_rebuild(tmp_path):
    rp.run(out_dir=tmp_path / "out")
    additions = [json.loads(line) for line in (tmp_path / "out" / "raw-scope-additions.jsonl").read_text(encoding="utf-8").splitlines()]
    chunks = rp.load_chunks()
    for add in additions:
        chunk = chunks[add["chunk_id"]]
        assert chunk["source"] == add["source_id"]
        rng = add["raw_chunk_char_range"]
        assert chunk["text"][rng["start"]:rng["end"]] == add["raw_span"]
        assert rp.coord.strict_validate_row(add["evidence"], chunks) is None


def test_orphan_evidence_removed_and_evidence_count(tmp_path):
    result = rp.run(out_dir=tmp_path / "out")
    before = [json.loads(line) for line in (tmp_path / "out" / "evidence-before.jsonl").read_text(encoding="utf-8").splitlines()]
    after = [json.loads(line) for line in (tmp_path / "out" / "evidence-after.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(before) == 161
    assert len(after) == result["counts"]["evidence_after"]
    assert all(r["case_id"] != "zh-033" for r in after)
    for case_id in NARROWED:
        assert all(r["case_id"] != case_id or r["chunk_id"] != rp.old_declared_chunk(case_id) for r in after)


def test_non_target_rows_byte_identical_and_blockers_listed(tmp_path):
    rp.run(out_dir=tmp_path / "out")
    before = [json.loads(line) for line in (tmp_path / "out" / "draft-before.jsonl").read_text(encoding="utf-8").splitlines()]
    after = [json.loads(line) for line in (tmp_path / "out" / "draft-after.jsonl").read_text(encoding="utf-8").splitlines()]
    before_by = {r["id"]: r for r in before}
    after_by = {r["id"]: r for r in after}
    for case_id in before_by:
        if case_id in (RETIRED | NARROWED):
            continue
        assert json.dumps(after_by[case_id], ensure_ascii=False, sort_keys=True) == json.dumps(before_by[case_id], ensure_ascii=False, sort_keys=True)
    remaining = (tmp_path / "out" / "REMAINING_BLOCKERS.md").read_text(encoding="utf-8")
    for case_id in sorted(UNRESOLVED):
        assert case_id in remaining


def test_activation_blocked_and_no_overlay_or_split(tmp_path):
    result = rp.run(out_dir=tmp_path / "out")
    manifest = result["manifest"]
    assert manifest["revision_status"] == "CANDIDATE"
    assert manifest["activation_blocked"] is True
    assert manifest["human_reviewed"] is False
    assert manifest["actor"] == "OWNER_AUTHORIZED_DETERMINISTIC_SCOPE_REPAIR"
    out = tmp_path / "out"
    assert not (out / "overlay").exists()
    assert not (out / "active").exists()
    assert not list(out.glob("*.v2.1*"))
    assert "SPLIT_RESEAL_REQUIRED.md" in [p.name for p in out.iterdir()]


def test_input_sha_unchanged_and_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    r1 = rp.run(out_dir=a)
    r2 = rp.run(out_dir=b)
    assert sorted(p.name for p in a.iterdir()) == sorted(p.name for p in b.iterdir())
    for name in sorted(p.name for p in a.iterdir()):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
    assert r1["manifest"]["inputs"] == r2["manifest"]["inputs"]
