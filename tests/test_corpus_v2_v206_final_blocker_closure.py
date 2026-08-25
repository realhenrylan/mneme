"""TDD tests for the v2.0.6 owner-authorized final blocker closure candidate.

Four fixed owner actions on the four remaining blockers; the candidate never
asks a model for judgment.  All gates are fail-closed and every raw span must
be proven by chunk_text[start:end] == raw_evidence_span.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.corpus_v2_v206_final_blocker_closure as rp
from scripts import corpus_v2_evidence_coordinate_repair as coord


@pytest.fixture(scope="module")
def pack(tmp_path_factory):
    out = tmp_path_factory.mktemp("v206")
    result = rp.run(out_dir=out)
    return result, out


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _row(rows: list[dict], case_id: str) -> dict:
    return next(row for row in rows if row["case_id"] == case_id)


def test_target_set_is_exact_four():
    assert rp.TARGETS == frozenset({"zh-035", "zh-032", "mixed-022", "mixed-028"})
    assert len(rp.TARGETS) == 4


def test_case_count_149_to_148_and_retired_ledger(pack):
    _, out = pack
    before = _jsonl(out / "draft-before.jsonl")
    after = _jsonl(out / "draft-after.jsonl")
    assert len(before) == 149
    assert len(after) == 148
    assert all(row["id"] != "zh-032" for row in after)
    retired = _jsonl(out / "retired-cases.jsonl")
    assert [row["case_id"] for row in retired] == ["zh-032"]
    assert retired[0]["reason"] == "no_directly_supported_answer_point_after_owner_authorized_review"
    retired_evidence = _jsonl(out / "retired-evidence.jsonl")
    assert all(row["case_id"] == "zh-032" for row in retired_evidence)
    assert len(retired_evidence) == 1


def test_zh032_retirement_dependency_gate_passes(pack):
    _, out = pack
    before = _jsonl(out / "draft-before.jsonl")
    zh032 = next(row for row in before if row["id"] == "zh-032")
    for row in before:
        if row["id"] == "zh-032":
            continue
        assert row.get("doc_target") != "zh-032"
        assert (row.get("metadata") or {}).get("follow_up_to") != "zh-032"
        assert "zh-032" not in str((row.get("metadata") or {}).get("chain_id") or "")
    assert zh032.get("doc_target") is None
    assert zh032["metadata"]["follow_up_to"] is None
    assert zh032["metadata"]["chain_id"] is None


def test_zh035_six_spans_ledger_complete_sorted_and_proved(pack):
    chunks = coord.load_chunks(rp.CHUNKS)
    _, out = pack
    ledger = _jsonl(out / "multi-span-evidence-ledger.jsonl")
    assert len(ledger) == 6
    keys = [(row["source_id"], row["chunk_id"], row["raw_chunk_char_range"]["start"], row["raw_chunk_char_range"]["end"]) for row in ledger]
    assert keys == sorted(keys)
    assert keys == [
        ("python-tutorial-en.md", "e564a122a7a2_chunk_61", 1492, 1499),
        ("python-tutorial-en.md", "e564a122a7a2_chunk_64", 1523, 1530),
        ("python-tutorial-en.md", "e564a122a7a2_chunk_65", 190, 197),
        ("python-tutorial-zh.md", "32c427fb50e2_chunk_30", 550, 557),
        ("python-tutorial-zh.md", "32c427fb50e2_chunk_31", 992, 999),
        ("python-tutorial-zh.md", "32c427fb50e2_chunk_31", 1263, 1270),
    ]
    for row in ledger:
        rng = row["raw_chunk_char_range"]
        raw = chunks[row["chunk_id"]]["text"][rng["start"]:rng["end"]]
        assert raw == row["raw_evidence_span"] == "fibo.py"
        assert row["raw_span_sha256"] == hashlib.sha256(b"fibo.py").hexdigest()
        assert row["policy"] == "multi_span_exact_evidence_v1"
    # exactly these 6 spans as evidence rows, no cherry-picking
    evidence = _jsonl(out / "evidence-after.jsonl")
    zh035_rows = [row for row in evidence if row["case_id"] == "zh-035"]
    assert len(zh035_rows) == 6
    assert {(row["chunk_id"], row["raw_chunk_char_range"]["start"]) for row in zh035_rows} == {
        (row["chunk_id"], row["raw_chunk_char_range"]["start"]) for row in ledger
    }


def test_zh035_multi_span_policy_and_scope_expansion(pack):
    _, out = pack
    assert (out / "multi-span-evidence-policy.md").exists()
    after = _jsonl(out / "draft-after.jsonl")
    zh035 = next(row for row in after if row["id"] == "zh-035")
    assert zh035["acceptable_answer_points"] == ["fibo.py"]
    assert zh035["query"] == "教程里那个存放斐波那契数列函数的文件叫什么名字？"
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["multi_span_policy"] == "multi_span_exact_evidence_v1"
    expansion = manifest["source_scope_expansion"]
    assert expansion["case_id"] == "zh-035"
    assert expansion["marker"] == "OWNER_AUTHORIZED_MULTI_SOURCE_EXACT_EVIDENCE_SCOPE_EXPANSION"
    assert set(expansion["sources"]) == {"python-tutorial-en.md"}
    assert len(expansion["chunk_ids"]) == 3
    diff = _jsonl(out / "reannotation-diff.jsonl")
    en_adds = [row for row in diff
               if row["case_id"] == "zh-035" and row["kind"] == "evidence_added"
               and row["source_id"] == "python-tutorial-en.md"]
    assert len(en_adds) == 3
    assert all(row["scope_expansion"] == "OWNER_AUTHORIZED_MULTI_SOURCE_EXACT_EVIDENCE_SCOPE_EXPANSION" for row in en_adds)


def test_mixed022_answer_point_narrowed_and_orphan_removed(pack):
    chunks = coord.load_chunks(rp.CHUNKS)
    _, out = pack
    after = _jsonl(out / "draft-after.jsonl")
    row = next(r for r in after if r["id"] == "mixed-022")
    assert row["acceptable_answer_points"] == ["A function returning another function"]
    assert row["query"] == "术语表中，decorator 条目用的是中文还是英文解释？"
    evidence = [r for r in _jsonl(out / "evidence-after.jsonl") if r["case_id"] == "mixed-022"]
    assert len(evidence) == 1
    rng = evidence[0]["raw_chunk_char_range"]
    assert evidence[0]["chunk_id"] == "c9fd20815ea8_chunk_5"
    assert rng == {"start": 18, "end": 55}
    assert chunks["c9fd20815ea8_chunk_5"]["text"][18:55] == evidence[0]["raw_evidence_span"] == "A function returning another function"
    diff = _jsonl(out / "reannotation-diff.jsonl")
    kinds = {(row["case_id"], row["kind"]) for row in diff}
    assert ("mixed-022", "answer_point_removed") in kinds
    assert ("mixed-022", "evidence_removed") in kinds
    assert ("mixed-022", "evidence_added") in kinds


def test_mixed028_answer_point_narrowed_and_orphan_removed(pack):
    chunks = coord.load_chunks(rp.CHUNKS)
    _, out = pack
    after = _jsonl(out / "draft-after.jsonl")
    row = next(r for r in after if r["id"] == "mixed-028")
    assert row["acceptable_answer_points"] == ["state"]
    evidence = [r for r in _jsonl(out / "evidence-after.jsonl") if r["case_id"] == "mixed-028"]
    assert len(evidence) == 1
    rng = evidence[0]["raw_chunk_char_range"]
    assert evidence[0]["chunk_id"] == "993955159403_chunk_7"
    assert rng == {"start": 152, "end": 157}
    assert chunks["993955159403_chunk_7"]["text"][152:157] == evidence[0]["raw_evidence_span"] == "state"


def test_no_zero_answer_point_cases(pack):
    _, out = pack
    after = _jsonl(out / "draft-after.jsonl")
    for case_id in ("zh-035", "mixed-022", "mixed-028"):
        row = next(r for r in after if r["id"] == case_id)
        assert len(row["acceptable_answer_points"]) >= 1
        assert row.get("should_refuse") is not True


def test_non_target_rows_byte_identical(pack):
    _, out = pack
    before_draft = [l for l in (out / "draft-before.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    after_draft = [l for l in (out / "draft-after.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    kept = [l for l in after_draft if json.loads(l)["id"] not in rp.TARGETS]
    expected = [l for l in before_draft if json.loads(l)["id"] not in rp.TARGETS]
    assert kept == expected
    before_ev = [l for l in (out / "evidence-before.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    after_ev = [l for l in (out / "evidence-after.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    kept_ev = [l for l in after_ev if json.loads(l)["case_id"] not in rp.TARGETS]
    expected_ev = [l for l in before_ev if json.loads(l)["case_id"] not in rp.TARGETS]
    assert kept_ev == expected_ev


def test_evidence_counts(pack):
    _, out = pack
    before = _jsonl(out / "evidence-before.jsonl")
    after = _jsonl(out / "evidence-after.jsonl")
    assert len(before) == 159
    assert len(after) == 162
    for case_id, count in (("zh-035", 6), ("mixed-022", 1), ("mixed-028", 1)):
        assert len([r for r in after if r["case_id"] == case_id]) == count
    assert all(r["case_id"] != "zh-032" for r in after)


def test_strict_validation_all_raw_rows(pack):
    chunks = coord.load_chunks(rp.CHUNKS)
    _, out = pack
    evidence = _jsonl(out / "evidence-after.jsonl")
    raw_rows = [r for r in evidence if r.get("coordinate_contract") == rp.CONTRACT]
    assert len(raw_rows) == len(evidence) - 1  # one legacy row remains outside the targets
    coord.strict_validate(raw_rows, chunks)


def test_no_legacy_rows_for_targets(pack):
    _, out = pack
    evidence = _jsonl(out / "evidence-after.jsonl")
    for case_id in rp.TARGETS - {"zh-032"}:  # zh-032 is retired: zero rows
        rows = [r for r in evidence if r["case_id"] == case_id]
        assert rows and all(r.get("coordinate_contract") == rp.CONTRACT for r in rows)
    assert all(r["case_id"] != "zh-032" for r in evidence)


def test_all_answerable_cases_have_evidence(pack):
    _, out = pack
    draft = _jsonl(out / "draft-after.jsonl")
    evidence = _jsonl(out / "evidence-after.jsonl")
    covered = {r["case_id"] for r in evidence}
    missing = [r["id"] for r in draft if r.get("should_refuse") is not True and r["id"] not in covered]
    assert missing == []


def test_case_ids_unique(pack):
    _, out = pack
    after = _jsonl(out / "draft-after.jsonl")
    assert len(after) == 148
    assert len({r["id"] for r in after}) == 148


def test_input_shas_unchanged(pack):
    _, out = pack
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    inputs = manifest["inputs"]
    v205 = json.loads(rp.V205_MANIFEST.read_text(encoding="utf-8"))
    assert inputs["v205_draft_after"] == v205["outputs"]["draft-after.jsonl"]
    assert inputs["v205_evidence_after"] == v205["outputs"]["evidence-after.jsonl"]
    assert inputs["draft"] == v205["inputs"]["draft"]
    assert inputs["chunks"] == v205["inputs"]["chunks"]
    assert inputs["chunk_manifest"] == v205["inputs"]["chunk_manifest"]
    pack_manifest = json.loads((rp.PACK_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert inputs["pack_jsonl"] == pack_manifest["outputs"]["remaining-blockers-decision-pack.jsonl"]
    assert inputs["v205_manifest"] == hashlib.sha256(rp.V205_MANIFEST.read_bytes()).hexdigest()


def test_manifest_metadata_and_self_hash(pack):
    _, out = pack
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    expected = hashlib.sha256((json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")).hexdigest()
    assert manifest["manifest_sha256"] == expected
    assert manifest["revision_status"] == "CANDIDATE"
    assert manifest["activation_blocked"] is True
    assert manifest["human_reviewed"] is False
    assert manifest["actor"] == "OWNER_AUTHORIZED_FINAL_BLOCKER_CLOSURE"
    assert manifest["case_count_before"] == 149
    assert manifest["case_count_after"] == 148
    assert manifest["overlay_generated"] is False
    assert manifest["v2_1_entered"] is False
    for name, sha in manifest["outputs"].items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == sha


def test_exact_output_file_set_and_no_forbidden(pack):
    _, out = pack
    assert sorted(p.name for p in out.iterdir()) == [
        "REPAIR_REPORT.md",
        "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md",
        "coordinate-validation-report.json",
        "data-quality-report.json",
        "draft-after.jsonl",
        "draft-before.jsonl",
        "evidence-after.jsonl",
        "evidence-before.jsonl",
        "manifest.json",
        "multi-span-evidence-ledger.jsonl",
        "multi-span-evidence-policy.md",
        "reannotation-diff.jsonl",
        "retired-cases.jsonl",
        "retired-evidence.jsonl",
    ]
    for name in ("overlay", "active", "v2.1", "split", "lock"):
        assert not any(name in p.name.lower() for p in out.iterdir() if p.name != "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md")


def test_deterministic_rebuild_byte_identical(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    rp.run(out_dir=a)
    rp.run(out_dir=b)
    assert sorted(p.name for p in a.iterdir()) == sorted(p.name for p in b.iterdir())
    for name in sorted(p.name for p in a.iterdir()):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
