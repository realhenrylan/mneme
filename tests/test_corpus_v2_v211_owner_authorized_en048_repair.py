"""v2.0.11 owner-authorized en-048 same-source repair — TDD 测试（先 RED 再 GREEN）。

覆盖任务验收：
- en-048 的 same_source 候选必须直接读取自 v2.0.10 triage（不得重新搜索）；
- 新增 evidence 逐项验证：case_id 仅为 en-048、source/chunk/Unicode [start,end)/
  raw span/snippet SHA 与 chunk 原文严格一致、不与现有 evidence span 重叠、
  通过 strict validator、不造成重复 evidence；
- draft-after 与 v2.0.10 draft-after 逐字节一致；evidence-after 仅新增单条；
- 预期 136 cases / 149 strict evidence，任一不符 fail-closed、零输出；
- 新 candidate 保持 CANDIDATE / activation_blocked=true / human_reviewed=false /
  overlay_generated=false / split_reseal_required=true / v2_1_entered=false；
- 生成 before/after、added-evidence ledger、field-level diff、data-quality report、
  review/split rebuild note、manifest；manifest 自哈希 + 全部 outputs SHA；
- 两次构建逐字节一致；禁止生成 overlay/active/split/locked/v2.1 产物；
- 输入文件（v2.0.10 candidate/review/triage、chunks、chunk manifest、current draft）
  构建前后 SHA 不变。
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

import scripts.corpus_v2_v211_owner_authorized_en048_repair as rep


# ── helpers ─────────────────────────────────────────────────────────────

def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _jsonl(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _copy_candidate(tmp_path: Path) -> Path:
    """复制真实 v2.0.10 candidate 树，并剥离 review/triage（由单独 helper 重建）。"""
    dst = tmp_path / "candidate"
    shutil.copytree(rep.CANDIDATE, dst)
    shutil.rmtree(dst / "automated-review", ignore_errors=True)
    return dst


def _copy_review(tmp_path: Path, cand: Path) -> Path:
    src = rep.CANDIDATE / "automated-review"
    dst = cand / "automated-review"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("automated-review-issues.jsonl",
                 "automated-review-gate-report.md", "manifest.json"):
        shutil.copy2(src / name, dst / name)
    return dst


def _copy_triage(tmp_path: Path, cand: Path) -> Path:
    src = rep.TRIAGE_DIR
    dst = cand / "automated-review" / "coherence-reject-triage"
    shutil.copytree(src, dst)
    return dst


def _rewrite_manifest(path: Path, mutate) -> None:
    m = json.loads(path.read_text(encoding="utf-8"))
    mutate(m)
    path.write_text(rep._dump(rep._manifest(m)), encoding="utf-8")


def _tamper_output(cand: Path, name: str, mutate_rows) -> None:
    """篡改 candidate 输出文件并同步 manifest outputs SHA。"""
    p = cand / name
    rows = _jsonl(p)
    rows = mutate_rows(rows)
    p.write_text("".join(rep._line(r) + "\n" for r in rows),
                 encoding="utf-8", newline="\n")

    def _sync(m):
        m["outputs"][name] = rep._sha256_file(p)
    _rewrite_manifest(cand / "manifest.json", _sync)


def _tamper_triage(cand: Path, name: str, mutate_rows) -> None:
    """篡改 triage 输出文件并同步 triage manifest outputs SHA。"""
    triage = cand / "automated-review" / "coherence-reject-triage"
    p = triage / name
    rows = _jsonl(p)
    rows = mutate_rows(rows)
    p.write_text("".join(rep._line(r) + "\n" for r in rows),
                 encoding="utf-8", newline="\n")

    def _sync(m):
        m["outputs"][name] = rep._sha256_file(p)
    _rewrite_manifest(triage / "manifest.json", _sync)


def _build(out_dir: Path, cand: Path) -> dict:
    return rep.run(out_dir=out_dir, candidate_dir=cand,
                   chunks_path=rep.CHUNKS_PATH,
                   chunk_manifest_path=rep.CHUNK_MANIFEST_PATH,
                   current_draft_path=rep.CURRENT_DRAFT_PATH)


# ── 1. 常量与输入存在性 ────────────────────────────────────────────────

def test_input_paths_exist():
    assert rep.CANDIDATE.is_dir()
    assert rep.TRIAGE_DIR.is_dir()
    assert rep.CHUNKS_PATH.is_file()
    assert rep.CHUNK_MANIFEST_PATH.is_file()
    assert rep.CURRENT_DRAFT_PATH.is_file()
    assert (rep.CANDIDATE / "draft-after.jsonl").is_file()
    assert (rep.CANDIDATE / "evidence-after.jsonl").is_file()
    assert (rep.TRIAGE_DIR / "reject-root-cause-triage.jsonl").is_file()


def test_expected_counts_constants():
    assert rep.EXPECTED_CASE_BEFORE == 136
    assert rep.EXPECTED_EVIDENCE_BEFORE == 148
    assert rep.EXPECTED_CASE_AFTER == 136
    assert rep.EXPECTED_EVIDENCE_AFTER == 149
    assert rep.TARGET_CASE_ID == "en-048"
    assert rep.EXPECTED_REFUSAL_CASES == 31
    assert rep.EXPECTED_ANSWERABLE_CASES == 105


def test_candidate_flags_constants():
    assert rep.GATE_OK == "EN048_SAME_SOURCE_REPAIR_CANDIDATE_OK"
    assert rep.CONTRACT == "raw-codepoint-v1"
    assert rep.ALGORITHM == "raw-span-map-1"
    assert rep.NORMALIZATION == "display-whitespace-v1"


# ── 2. 预检 fail-closed ─────────────────────────────────────────────────

def test_preflight_real_inputs_pass(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    checks = rep.preflight(candidate_dir=cand, chunks_path=rep.CHUNKS_PATH,
                           chunk_manifest_path=rep.CHUNK_MANIFEST_PATH,
                           current_draft_path=rep.CURRENT_DRAFT_PATH)
    assert checks["case_count_ok"] is True
    assert checks["evidence_count_ok"] is True
    assert checks["strict_covered_equals_passed"] is True
    assert checks["candidate_manifest_ok"] is True
    assert checks["review_manifest_ok"] is True
    assert checks["triage_manifest_ok"] is True
    assert checks["input_sha_ok"] is True
    assert checks["en048_authorized"] is True
    assert checks["candidate_rebuilds"] is True
    assert checks["candidate_unique"] is True
    assert checks["no_span_overlap"] is True
    assert checks["no_duplicate_anchor"] is True
    assert checks["declared_source"] is True


def test_preflight_candidate_manifest_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    _rewrite_manifest(cand / "manifest.json",
                      lambda m: m.__setitem__("revision_status", "ACTIVE"))
    with pytest.raises(rep.RepairError):
        rep.preflight(candidate_dir=cand, chunks_path=rep.CHUNKS_PATH,
                      chunk_manifest_path=rep.CHUNK_MANIFEST_PATH,
                      current_draft_path=rep.CURRENT_DRAFT_PATH)


def test_preflight_candidate_counts_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    _rewrite_manifest(cand / "manifest.json",
                      lambda m: m["counts"].__setitem__("case_after", 135))
    with pytest.raises(rep.RepairError):
        rep.preflight(candidate_dir=cand, chunks_path=rep.CHUNKS_PATH,
                      chunk_manifest_path=rep.CHUNK_MANIFEST_PATH,
                      current_draft_path=rep.CURRENT_DRAFT_PATH)


def test_preflight_candidate_evidence_tamper_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    _tamper_output(cand, "evidence-after.jsonl",
                   lambda rows: rows[: len(rows) - 1])
    with pytest.raises(rep.RepairError):
        rep.preflight(candidate_dir=cand, chunks_path=rep.CHUNKS_PATH,
                      chunk_manifest_path=rep.CHUNK_MANIFEST_PATH,
                      current_draft_path=rep.CURRENT_DRAFT_PATH)


def test_preflight_review_manifest_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    _rewrite_manifest(cand / "automated-review" / "manifest.json",
                      lambda m: m["counts"].__setitem__("reject", 18))
    with pytest.raises(rep.RepairError):
        rep.preflight(candidate_dir=cand, chunks_path=rep.CHUNKS_PATH,
                      chunk_manifest_path=rep.CHUNK_MANIFEST_PATH,
                      current_draft_path=rep.CURRENT_DRAFT_PATH)


def test_preflight_triage_manifest_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    _rewrite_manifest(
        cand / "automated-review" / "coherence-reject-triage" / "manifest.json",
        lambda m: m["counts"].__setitem__("reject", 18))
    with pytest.raises(rep.RepairError):
        rep.preflight(candidate_dir=cand, chunks_path=rep.CHUNKS_PATH,
                      chunk_manifest_path=rep.CHUNK_MANIFEST_PATH,
                      current_draft_path=rep.CURRENT_DRAFT_PATH)


def test_preflight_triage_en048_candidate_span_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    _tamper_triage(cand, "reject-root-cause-triage.jsonl", lambda rows: [
        {**r, "same_source_candidates": [
            {**c, "start": 531, "end": 537, "span": "window"}
            for c in r["same_source_candidates"]]}
        if r["case_id"] == "en-048" else r
        for r in rows])
    with pytest.raises(rep.RepairError):
        rep.preflight(candidate_dir=cand, chunks_path=rep.CHUNKS_PATH,
                      chunk_manifest_path=rep.CHUNK_MANIFEST_PATH,
                      current_draft_path=rep.CURRENT_DRAFT_PATH)


def test_preflight_triage_en048_removed_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    _tamper_triage(cand, "reject-root-cause-triage.jsonl",
                   lambda rows: [r for r in rows if r["case_id"] != "en-048"])
    with pytest.raises(rep.RepairError):
        rep.preflight(candidate_dir=cand, chunks_path=rep.CHUNKS_PATH,
                      chunk_manifest_path=rep.CHUNK_MANIFEST_PATH,
                      current_draft_path=rep.CURRENT_DRAFT_PATH)


def test_preflight_triage_unique_flag_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    _tamper_triage(cand, "reject-root-cause-triage.jsonl", lambda rows: [
        {**r, "same_source_candidates": [
            {**c, "unique": 0} for c in r["same_source_candidates"]]}
        if r["case_id"] == "en-048" else r
        for r in rows])
    with pytest.raises(rep.RepairError):
        rep.preflight(candidate_dir=cand, chunks_path=rep.CHUNKS_PATH,
                      chunk_manifest_path=rep.CHUNK_MANIFEST_PATH,
                      current_draft_path=rep.CURRENT_DRAFT_PATH)


def test_preflight_chunks_sha_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    p = tmp_path / "chunks.jsonl"
    shutil.copy2(rep.CHUNKS_PATH, p)
    with p.open("a", encoding="utf-8") as f:
        f.write("\n")
    with pytest.raises(rep.RepairError):
        rep.preflight(candidate_dir=cand, chunks_path=p,
                      chunk_manifest_path=rep.CHUNK_MANIFEST_PATH,
                      current_draft_path=rep.CURRENT_DRAFT_PATH)


def test_run_output_dir_exists_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(rep.RepairError):
        _build(out, cand)


# ── 3. 构建结果 ─────────────────────────────────────────────────────────

def test_run_builds_v211_candidate(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    out = tmp_path / "out"
    result = _build(out, cand)
    assert result["manifest"]["gate_verdict"] == rep.GATE_OK
    assert result["manifest"]["revision_status"] == "CANDIDATE"
    assert result["manifest"]["activation_blocked"] is True
    assert len(result["draft_after"]) == 136
    assert len(result["evidence_after"]) == 149
    assert set(p.name for p in out.iterdir()) == set(rep.OUTPUT_FILES)


def test_evidence_after_adds_exactly_one_row(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    out = tmp_path / "out"
    _build(out, cand)
    before = (cand / "evidence-after.jsonl").read_text(encoding="utf-8").splitlines()
    after = (out / "evidence-after.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(after) == len(before) + 1
    assert after[: len(before)] == before
    new_row = json.loads(after[-1])
    assert new_row["case_id"] == "en-048"
    assert new_row["chunk_id"] == "761b22915b5e_chunk_14"
    assert new_row["raw_chunk_char_range"] == {"start": 769, "end": 778}
    assert new_row["raw_evidence_span"] == "functions"
    assert new_row["source_id"] == "postgresql-tutorial.md"
    assert new_row["snippet"] == "functions"
    assert new_row["coordinate_contract"] == "raw-codepoint-v1"
    assert new_row["mapping_algorithm_version"] == "raw-span-map-1"
    assert new_row["snippet_normalization"] == "display-whitespace-v1"
    assert new_row["snippet_sha256"] == rep._sha256_text("functions")
    assert new_row["chunk_text_sha256"] == rep._sha256_text(
        rep._load_chunks(rep.CHUNKS_PATH)["761b22915b5e_chunk_14"]["text"])


def test_draft_after_byte_identical_to_v210(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    out = tmp_path / "out"
    _build(out, cand)
    assert (out / "draft-after.jsonl").read_bytes() == \
        (cand / "draft-after.jsonl").read_bytes()
    assert (out / "draft-before.jsonl").read_bytes() == \
        (cand / "draft-after.jsonl").read_bytes()
    assert (out / "evidence-before.jsonl").read_bytes() == \
        (cand / "evidence-after.jsonl").read_bytes()


def test_new_evidence_passes_strict_validation(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    out = tmp_path / "out"
    _build(out, cand)
    chunks = rep._load_chunks(rep.CHUNKS_PATH)
    rows = _jsonl(out / "evidence-after.jsonl")
    rep.strict_validate(rows, chunks)
    new_row = json.loads(
        (out / "evidence-after.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    rep.strict_validate_row(new_row, chunks)


def test_no_evidence_span_overlap(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    out = tmp_path / "out"
    _build(out, cand)
    rows = _jsonl(out / "evidence-after.jsonl")
    en048 = [r for r in rows if r["case_id"] == "en-048"]
    spans = [(r["chunk_id"], r["raw_chunk_char_range"]["start"],
              r["raw_chunk_char_range"]["end"]) for r in en048]
    for i, (cid, s, e) in enumerate(spans):
        for cid2, s2, e2 in spans:
            if (cid, s, e) == (cid2, s2, e2):
                continue
            if cid == cid2:
                assert not (s < e2 and s2 < e), "overlapping spans on same chunk"
    assert (("761b22915b5e_chunk_14", 769, 778)) in spans


def test_added_ledger_single_row(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    out = tmp_path / "out"
    _build(out, cand)
    rows = _jsonl(out / "added-same-source-evidence.jsonl")
    assert len(rows) == 1
    r = rows[0]
    assert r["case_id"] == "en-048"
    assert r["raw_chunk_char_range"] == {"start": 769, "end": 778}
    assert r["raw_evidence_span"] == "functions"
    assert r["source_id"] == "postgresql-tutorial.md"
    assert r["coordinate_contract"] == "raw-codepoint-v1"


def test_field_level_diff_single_row(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    out = tmp_path / "out"
    _build(out, cand)
    rows = _jsonl(out / "field-level-diff.jsonl")
    assert len(rows) == 1
    r = rows[0]
    assert r["case_id"] == "en-048"
    assert r["action"] == "add_same_source_evidence_scope"
    assert r["raw_chunk_char_range"] == {"start": 769, "end": 778}
    assert r["raw_evidence_span"] == "functions"
    assert r["candidate_origin"] == "v2.0.10-coherence-reject-triage"
    assert r["via"] == "token"
    assert r["unique"] == 1
    assert r["overlaps_existing"] is False


def test_data_quality_report_five_dims(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    out = tmp_path / "out"
    _build(out, cand)
    dq = json.loads((out / "data-quality-report.json").read_text(encoding="utf-8"))
    dims = dq["deterministic_data_quality_checks"]
    for dim in ("completeness", "uniqueness", "referential_integrity",
                "continuity", "consistency"):
        assert dim in dims
        assert all(v is True for v in dims[dim].values())
    assert dq.get("findings") == []


def test_manifest_self_hash_roundtrip():
    m = {"a": 1, "b": {"c": [1, 2]}}
    signed = rep._manifest(m)
    assert rep._verify_self_hash(signed)


def test_output_manifest_self_hash(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    out = tmp_path / "out"
    _build(out, cand)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert rep._verify_self_hash(m)


def test_output_manifest_outputs_sha_match_disk(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    out = tmp_path / "out"
    _build(out, cand)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for name, digest in m["outputs"].items():
        assert (out / name).is_file()
        assert rep._sha256_file(out / name) == digest


def test_output_manifest_inputs_sha_match_sources(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    out = tmp_path / "out"
    _build(out, cand)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    inputs = m["inputs"]
    assert inputs["v210-draft-after.jsonl"] == _sha(cand / "draft-after.jsonl")
    assert inputs["v210-evidence-after.jsonl"] == _sha(cand / "evidence-after.jsonl")
    assert inputs["v210-review-manifest.json"] == \
        _sha(cand / "automated-review" / "manifest.json")
    assert inputs["v210-triage-reject-root-cause-triage.jsonl"] == \
        _sha(cand / "automated-review" / "coherence-reject-triage" /
             "reject-root-cause-triage.jsonl")
    assert inputs["chunks.jsonl"] == _sha(rep.CHUNKS_PATH)
    assert inputs["chunk-manifest.json"] == _sha(rep.CHUNK_MANIFEST_PATH)


def test_manifest_counts_and_metadata(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    out = tmp_path / "out"
    _build(out, cand)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["counts"] == {
        "case_before": 136, "case_after": 136,
        "evidence_before": 148, "evidence_after": 149,
        "same_source_evidence_added": 1,
        "retired_cases": 0, "retired_evidence": 0, "duplicate_evidence_removed": 0,
    }
    assert m["revision_status"] == "CANDIDATE"
    assert m["activation_blocked"] is True
    assert m["human_reviewed"] is False
    assert m["overlay_generated"] is False
    assert m["split_reseal_required"] is True
    assert m["v2_1_entered"] is False
    assert m["deterministic"] is True
    assert m["declarations"]["llm_called"] is False
    assert m["declarations"]["network_used"] is False
    assert m["declarations"]["overlay_generated"] is False
    assert m["validation"]["strict_covered_equals_passed"] is True
    assert m["validation"]["draft_byte_identical_to_v210"] is True
    assert m["validation"]["evidence_non_target_rows_byte_identical"] is True


def test_input_sha_unchanged_after_build(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    before = {
        "draft": _sha(cand / "draft-after.jsonl"),
        "evidence": _sha(cand / "evidence-after.jsonl"),
        "review": _sha(cand / "automated-review" / "manifest.json"),
        "triage": _sha(cand / "automated-review" / "coherence-reject-triage" /
                       "reject-root-cause-triage.jsonl"),
        "chunks": _sha(rep.CHUNKS_PATH),
        "chunk-manifest": _sha(rep.CHUNK_MANIFEST_PATH),
    }
    out = tmp_path / "out"
    _build(out, cand)
    assert _sha(cand / "draft-after.jsonl") == before["draft"]
    assert _sha(cand / "evidence-after.jsonl") == before["evidence"]
    assert _sha(cand / "automated-review" / "manifest.json") == before["review"]
    assert _sha(cand / "automated-review" / "coherence-reject-triage" /
                "reject-root-cause-triage.jsonl") == before["triage"]
    assert _sha(rep.CHUNKS_PATH) == before["chunks"]
    assert _sha(rep.CHUNK_MANIFEST_PATH) == before["chunk-manifest"]


def test_two_builds_byte_identical(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    out1, out2 = tmp_path / "out1", tmp_path / "out2"
    _build(out1, cand)
    _build(out2, cand)
    names1 = {p.name for p in out1.iterdir()}
    names2 = {p.name for p in out2.iterdir()}
    assert names1 == names2
    for name in names1:
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()


def test_no_forbidden_outputs(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    out = tmp_path / "out"
    _build(out, cand)
    for p in out.iterdir():
        name = p.name.lower()
        assert not name.startswith(("overlay", "active", "split", "after"))
        assert "v2.1" not in name
        assert "retired" not in name
        assert "dedup" not in name
        assert not name.startswith(".")


def test_v210_inputs_unchanged_by_build(tmp_path):
    cand = _copy_candidate(tmp_path)
    _copy_review(tmp_path, cand)
    _copy_triage(tmp_path, cand)
    out = tmp_path / "out"
    _build(out, cand)
    # 真实 v2.0.10 源目录不得被触碰
    assert (rep.CANDIDATE / "manifest.json").is_file()
    assert (rep.CANDIDATE / "draft-after.jsonl").is_file()
    assert (rep.CANDIDATE / "evidence-after.jsonl").is_file()
    assert (rep.TRIAGE_DIR / "manifest.json").is_file()
