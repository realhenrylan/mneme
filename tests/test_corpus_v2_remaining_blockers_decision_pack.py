"""TDD tests for the v2.0.5 remaining-four blocker closure decision pack.

This pack is read-only and deterministic: it presents the exact raw facts and
owner-only action options for the four unresolved cases (zh-035, zh-032,
mixed-022, mixed-028) and never selects an action by itself.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

import scripts.corpus_v2_remaining_blockers_decision_pack as rp
from scripts import corpus_v2_evidence_coordinate_repair as coord


@pytest.fixture(scope="module")
def pack(tmp_path_factory):
    out = tmp_path_factory.mktemp("rb-pack")
    result = rp.run(out_dir=out)
    return result, out


def _rows(out: Path) -> list[dict]:
    path = out / "remaining-blockers-decision-pack.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _row(out: Path, case_id: str) -> dict:
    return next(row for row in _rows(out) if row["case_id"] == case_id)


def test_target_set_is_exact_four():
    assert rp.TARGETS == frozenset({"zh-035", "zh-032", "mixed-022", "mixed-028"})
    assert len(rp.TARGETS) == 4


def test_fixed_action_sets_are_exact():
    assert set(rp.FIXED_ACTIONS["zh-035"]) == {
        "keep_unresolved",
        "retain_all_exact_duplicate_spans_with_explicit_multi_span_policy",
        "retire_case",
    }
    assert set(rp.FIXED_ACTIONS["zh-032"]) == {
        "remove_unsupported_answer_point",
        "retire_case",
        "keep_unresolved",
    }


def test_zh035_all_duplicate_spans_enumerated_and_stable_sorted(pack):
    _, out = pack
    row = _row(out, "zh-035")
    spans = row["analysis"]["duplicate_raw_spans"]
    assert len(spans) == 6
    assert [(s["source_id"], s["chunk_id"], s["raw_chunk_char_range"]["start"], s["raw_chunk_char_range"]["end"]) for s in spans] == [
        ("python-tutorial-en.md", "e564a122a7a2_chunk_61", 1492, 1499),
        ("python-tutorial-en.md", "e564a122a7a2_chunk_64", 1523, 1530),
        ("python-tutorial-en.md", "e564a122a7a2_chunk_65", 190, 197),
        ("python-tutorial-zh.md", "32c427fb50e2_chunk_30", 550, 557),
        ("python-tutorial-zh.md", "32c427fb50e2_chunk_31", 992, 999),
        ("python-tutorial-zh.md", "32c427fb50e2_chunk_31", 1263, 1270),
    ]
    assert all(s["raw_span"] == "fibo.py" for s in spans)
    assert sum(1 for s in spans if s["in_declared_source"]) == 3


def test_zh035_actions_and_multi_span_policy_flags(pack):
    _, out = pack
    row = _row(out, "zh-035")
    actions = row["available_actions"]
    assert {a["action"] for a in actions} == {
        "keep_unresolved",
        "retain_all_exact_duplicate_spans_with_explicit_multi_span_policy",
        "retire_case",
    }
    multi = next(a for a in actions if a["action"].startswith("retain_all"))
    assert multi["new_evidence_policy"] is True
    assert multi["requires_owner_approval"] is True
    assert all(a["zero_answer_point_risk"] is False for a in actions)


def test_zh032_no_full_or_clause_exact_evidence_and_actions_fixed(pack):
    _, out = pack
    row = _row(out, "zh-032")
    for point in row["analysis"]["per_answer_point"]:
        assert point["full_point_matches"] == []
        assert point["clause_matches"] == []
        assert point["unsupported"] is True
        assert point["narrow_candidates"] == []
    p0 = row["analysis"]["per_answer_point"][0]
    frags = [f for f in p0["fragment_matches"] if f["chunk_id"] == "32c427fb50e2_chunk_52"]
    assert [f["fragment"] for f in frags] == ["异常实例"]
    assert frags[0]["raw_spans"][0]["raw_chunk_char_range"] == {"start": 141, "end": 145}
    assert frags[0]["unique"] is True
    assert {a["action"] for a in row["available_actions"]} == {
        "remove_unsupported_answer_point",
        "retire_case",
        "keep_unresolved",
    }
    remove = next(a for a in row["available_actions"] if a["action"] == "remove_unsupported_answer_point")
    assert remove["zero_answer_point_risk"] is True


def test_mixed022_point0_narrow_candidate_and_point1_not(pack):
    _, out = pack
    row = _row(out, "mixed-022")
    p0, p1 = row["analysis"]["per_answer_point"]
    assert p0["narrow_suggestible"] is True
    cands = p0["narrow_candidates"]
    assert {c["clause"] for c in cands} == {"A function returning another function", "returning", "another"}
    best = cands[0]
    assert best["clause"] == "A function returning another function"
    assert best["chunk_id"] == "c9fd20815ea8_chunk_5"
    assert best["raw_chunk_char_range"] == {"start": 18, "end": 55}
    assert p1["narrow_suggestible"] is False
    assert p1["narrow_candidates"] == []
    narrow = next(a for a in row["available_actions"] if a["action"] == "narrow_answer_point_to_exact_raw_text")
    assert narrow["applies_to_point_indices"] == [0]
    remove = next(a for a in row["available_actions"] if a["action"] == "remove_unsupported_answer_point")
    assert remove["zero_answer_point_risk"] is False


def test_mixed022_point1_ambiguous_clause_not_labeled_exact(pack):
    _, out = pack
    row = _row(out, "mixed-022")
    p1 = row["analysis"]["per_answer_point"][1]
    dec = [c for c in p1["clause_matches"] if c["chunk_id"] == "c9fd20815ea8_chunk_5" and c["clause"] == "装饰器"]
    assert dec and dec[0]["unique"] is False
    assert dec[0]["occurrence_count"] == 3


def test_mixed028_narrow_candidate_is_state_in_react_chunk(pack):
    _, out = pack
    row = _row(out, "mixed-028")
    p0, p1 = row["analysis"]["per_answer_point"]
    assert p0["narrow_suggestible"] is False
    assert p0["narrow_candidates"] == []
    assert p1["narrow_suggestible"] is True
    cands = p1["narrow_candidates"]
    assert any(c["clause"] == "state" and c["chunk_id"] == "993955159403_chunk_7"
               and c["raw_chunk_char_range"] == {"start": 152, "end": 157} for c in cands)
    narrow = next(a for a in row["available_actions"] if a["action"] == "narrow_answer_point_to_exact_raw_text")
    assert narrow["applies_to_point_indices"] == [1]
    remove = next(a for a in row["available_actions"] if a["action"] == "remove_unsupported_answer_point")
    assert remove["zero_answer_point_risk"] is False


def test_zero_answer_point_risk_overall(pack):
    _, out = pack
    risks = {row["case_id"]: row["zero_answer_point_risk_overall"] for row in _rows(out)}
    assert risks == {"zh-035": False, "zh-032": True, "mixed-022": False, "mixed-028": False}


def test_template_rows_only_owner_fields_empty(pack):
    _, out = pack
    rows = [json.loads(line) for line in (out / "candidate-patch-template.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4
    for row in rows:
        assert row["case_id"] in rp.TARGETS
        assert set(rp.OWNER_FIELDS) <= set(row)
        for field in rp.OWNER_FIELDS:
            assert row[field] is None
        others = {key: value for key, value in row.items() if key not in rp.OWNER_FIELDS}
        assert all(value not in (None, "") for value in others.values())


def test_exact_seven_output_files_and_no_forbidden_content(pack):
    _, out = pack
    assert sorted(p.name for p in out.iterdir()) == [
        "OWNER_DECISION_GUIDE.md",
        "candidate-patch-template.jsonl",
        "decision-pack-report.md",
        "decision-pack-summary.json",
        "manifest.json",
        "raw-source-contexts.jsonl",
        "remaining-blockers-decision-pack.jsonl",
    ]
    assert not list(out.glob("*after*"))
    for name in ("overlay", "active", "v2.1"):
        assert not any(name in p.name for p in out.iterdir())
    forbidden = re.compile(r"(verdict|holdout|draft-after|evidence-after|auto-review)")
    for path in out.iterdir():
        if path.name == "manifest.json":
            continue
        assert not forbidden.search(path.read_text(encoding="utf-8")), path.name


def test_manifest_self_hash_matches_disk(pack):
    _, out = pack
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    expected = hashlib.sha256((json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")).hexdigest()
    assert manifest["manifest_sha256"] == expected
    assert manifest["status"] == "DECISION_PACK"
    assert manifest["revision_status"] == "CANDIDATE"
    assert manifest["activation_blocked"] is True
    assert manifest["human_reviewed"] is False
    for name, sha in manifest["outputs"].items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == sha


def test_input_shas_are_unchanged(pack):
    _, out = pack
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    inputs = manifest["inputs"]
    v205 = json.loads(rp.V205_MANIFEST.read_text(encoding="utf-8"))
    assert inputs["draft_after"] == v205["outputs"]["draft-after.jsonl"]
    assert inputs["evidence_after"] == v205["outputs"]["evidence-after.jsonl"]
    assert inputs["draft"] == v205["inputs"]["draft"]
    assert inputs["chunks"] == v205["inputs"]["chunks"]
    assert inputs["chunk_manifest"] == v205["inputs"]["chunk_manifest"]
    pack_manifest = json.loads((rp.PACK_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert inputs["pack_jsonl"] == pack_manifest["outputs"]["owner-decision-pack.jsonl"]
    rescue_manifest = json.loads((rp.RESCUE_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert inputs["rescue_results"] == rescue_manifest["outputs"]["same-source-rescue-results.jsonl"]


def test_current_evidence_rows_per_case(pack):
    _, out = pack
    expected = {"zh-035": 1, "zh-032": 1, "mixed-022": 1, "mixed-028": 2}
    for case_id, count in expected.items():
        row = _row(out, case_id)
        assert len(row["current_evidence"]) == count
        for evidence in row["current_evidence"]:
            chunk = coord.load_chunks(rp.CHUNKS)[evidence["chunk_id"]]
            assert chunk["source"] == evidence["source_id"]


def test_all_raw_spans_prove_equality(pack):
    chunks = coord.load_chunks(rp.CHUNKS)
    _, out = pack

    def prove(span: dict) -> None:
        rng = span["raw_chunk_char_range"]
        assert chunks[span["chunk_id"]]["text"][rng["start"]:rng["end"]] == span["raw_span"], span

    for row in _rows(out):
        for span in row["analysis"].get("duplicate_raw_spans", []):
            prove(span)
        for point in row["analysis"]["per_answer_point"]:
            for span in point["full_point_matches"]:
                prove(span)
            for entry in point["clause_matches"] + point["fragment_matches"]:
                assert entry["occurrence_count"] == len(entry["raw_spans"])
                assert entry["unique"] == (entry["occurrence_count"] == 1)
                for span in entry["raw_spans"]:
                    prove(span)
            for span in point["narrow_candidates"]:
                prove(span)


def test_answer_points_match_draft_after(pack):
    draft_after = {row["id"]: row for row in coord.load_jsonl(rp.DRAFT_AFTER)}
    draft_now = {row["id"]: row for row in coord.load_jsonl(rp.DRAFT)}
    for case_id in rp.TARGETS:
        assert draft_after[case_id] == draft_now[case_id]
    _, out = pack
    for row in _rows(out):
        assert row["answer_points"] == draft_after[row["case_id"]]["acceptable_answer_points"]


def test_deterministic_rebuild_byte_identical(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    rp.run(out_dir=a)
    rp.run(out_dir=b)
    assert sorted(p.name for p in a.iterdir()) == sorted(p.name for p in b.iterdir())
    for name in sorted(p.name for p in a.iterdir()):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
