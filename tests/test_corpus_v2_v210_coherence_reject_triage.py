"""v2.0.10 automated-review coherence and reject root-cause triage — TDD 测试（先 RED 再 GREEN）。

覆盖任务验收：
- 计数守恒（136 cases / 148 strict evidence；113 confirmed + 19 reject + 0 needs_followup
  + 4 errors = 136）；issues 恰 23 条且 case_id 唯一；
- 4 条 error（en-052 / mixed-030 / mixed-033 / zh-040）精确归类
  model_output_contract_inconsistency，且不得被自动改写；
- 19 条 reject 恰好一次分类（无重复、无遗漏），exact/partial/same_source/translation/
  no_direct 边界与 token/跨 source/重叠 span 红线；
- owner-decision-template 恰 23 行，owner 三字段必须为空；
- candidate/review manifest 自哈希与 inputs/outputs SHA 与磁盘一致；输入 SHA 任务前后
  不变；两次构建逐字节一致；
- 五维数据质量（完整性/唯一性/引用完整性/连续性/一致性）；
- 禁止生成 after/overlay/active/split/v2.1 文件。
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

import scripts.corpus_v2_v210_coherence_reject_triage as tr


# ── helpers ─────────────────────────────────────────────────────────────

def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _jsonl(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _copy_candidate(tmp_path: Path) -> Path:
    dst = tmp_path / "candidate"
    shutil.copytree(tr.CANDIDATE, dst)
    # review 目录（含 coherence-reject-triage 产物）由 _copy_review 单独控制
    shutil.rmtree(dst / "automated-review", ignore_errors=True)
    return dst


def _copy_review(tmp_path: Path, cand: Path | None = None) -> Path:
    """只复制 review 的 3 个核心文件（不含 coherence-reject-triage 子目录）。"""
    src = tr.REVIEW_DIR
    dst = (cand or tmp_path) / "automated-review"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("automated-review-issues.jsonl",
                 "automated-review-gate-report.md", "manifest.json"):
        shutil.copy2(src / name, dst / name)
    return dst


def _rewrite_manifest(cand: Path, mutate) -> None:
    """读取 manifest、应用 mutate、重算自哈希后写回。"""
    p = cand / "manifest.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    mutate(m)
    p.write_text(tr._dump(tr._manifest(m)), encoding="utf-8")


def _tamper_output(cand: Path, name: str, mutate_rows) -> None:
    """篡改候选输出文件并同步 manifest outputs SHA。"""
    p = cand / name
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    mutate_rows(rows)
    p.write_text("".join(tr._line(r) + "\n" for r in rows), encoding="utf-8")

    def _sync(m):
        m["outputs"][name] = tr._sha256_file(p)
    _rewrite_manifest(cand, _sync)


def _run_build(out_dir: Path) -> dict:
    return tr.run(out_dir=out_dir)


# ── 1. 常量与输入存在性 ────────────────────────────────────────────────

def test_input_paths_exist():
    assert tr.CANDIDATE.is_dir()
    assert tr.REVIEW_DIR.is_dir()
    assert tr.CHUNKS_PATH.is_file()
    assert tr.CHUNK_MANIFEST_PATH.is_file()
    assert tr.CURRENT_DRAFT_PATH.is_file()
    assert (tr.CANDIDATE / "draft-after.jsonl").is_file()
    assert (tr.CANDIDATE / "evidence-after.jsonl").is_file()
    assert (tr.REVIEW_DIR / "automated-review-issues.jsonl").is_file()


def test_expected_counts_constants():
    assert tr.EXPECTED_CASE_COUNT == 136
    assert tr.EXPECTED_EVIDENCE_COUNT == 148
    assert tr.EXPECTED_CONFIRMED == 113
    assert tr.EXPECTED_REJECT == 19
    assert tr.EXPECTED_NEEDS_FOLLOWUP == 0
    assert tr.EXPECTED_ERRORS == 4


def test_error_case_set_exact():
    assert set(tr.ERROR_CASES) == {"en-052", "mixed-030", "mixed-033", "zh-040"}


# ── 2. 预检 fail-closed ─────────────────────────────────────────────────

def test_preflight_real_inputs_pass(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    checks = tr.preflight(
        cand, review, tr.CHUNKS_PATH, tr.CHUNK_MANIFEST_PATH,
        tr.CURRENT_DRAFT_PATH)
    assert checks["case_count_ok"] is True
    assert checks["evidence_count_ok"] is True
    assert checks["strict_148_148_ok"] is True
    assert checks["issues_rows_ok"] is True
    assert checks["reject_rows_ok"] is True
    assert checks["error_rows_ok"] is True
    assert checks["reject_error_disjoint"] is True
    assert checks["no_overlay_ok"] is True
    assert checks["candidate_manifest_ok"] is True
    assert checks["review_manifest_ok"] is True
    assert checks["input_sha_ok"] is True
    assert checks["five_dims_ok"] is True


def test_preflight_case_count_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)

    def _drop(m):
        m["counts"]["case_after"] = 135
        m["counts"]["case_before"] = 135
    _rewrite_manifest(cand, _drop)
    with pytest.raises(tr.TriageError):
        tr.preflight(cand, review, tr.CHUNKS_PATH, tr.CHUNK_MANIFEST_PATH,
                     tr.CURRENT_DRAFT_PATH)


def test_preflight_evidence_count_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    _tamper_output(cand, "evidence-after.jsonl",
                   lambda rows: rows[: len(rows) - 1])
    with pytest.raises(tr.TriageError):
        tr.preflight(cand, review, tr.CHUNKS_PATH, tr.CHUNK_MANIFEST_PATH,
                     tr.CURRENT_DRAFT_PATH)


def test_preflight_issues_rows_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    p = review / "automated-review-issues.jsonl"
    rows = _jsonl(p)
    p.write_text("".join(tr._line(r) + "\n" for r in rows[:-1]),
                 encoding="utf-8", newline="\n")
    with pytest.raises(tr.TriageError):
        tr.preflight(cand, review, tr.CHUNKS_PATH, tr.CHUNK_MANIFEST_PATH,
                     tr.CURRENT_DRAFT_PATH)


def test_preflight_overlay_present_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    (review / "overlay-evidence.jsonl").write_text("{}", encoding="utf-8")
    with pytest.raises(tr.TriageError):
        tr.preflight(cand, review, tr.CHUNKS_PATH, tr.CHUNK_MANIFEST_PATH,
                     tr.CURRENT_DRAFT_PATH)


def test_preflight_candidate_manifest_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)

    def _mutate(m):
        m["revision_status"] = "ACTIVE"
    _rewrite_manifest(cand, _mutate)
    with pytest.raises(tr.TriageError):
        tr.preflight(cand, review, tr.CHUNKS_PATH, tr.CHUNK_MANIFEST_PATH,
                     tr.CURRENT_DRAFT_PATH)


def test_preflight_review_manifest_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    p = review / "manifest.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    m["counts"]["reject"] = 18
    p.write_text(tr._dump(tr._manifest(m)), encoding="utf-8")
    with pytest.raises(tr.TriageError):
        tr.preflight(cand, review, tr.CHUNKS_PATH, tr.CHUNK_MANIFEST_PATH,
                     tr.CURRENT_DRAFT_PATH)


def test_preflight_chunks_sha_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    p = tmp_path / "chunks.jsonl"
    shutil.copy2(tr.CHUNKS_PATH, p)
    with p.open("a", encoding="utf-8") as f:
        f.write("\n")
    with pytest.raises(tr.TriageError):
        tr.preflight(cand, review, p, tr.CHUNK_MANIFEST_PATH,
                     tr.CURRENT_DRAFT_PATH)


# ── 3. 守恒与集合 ──────────────────────────────────────────────────────

def test_conservation_counts_real(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    tr.preflight(cand, review, tr.CHUNKS_PATH, tr.CHUNK_MANIFEST_PATH,
                 tr.CURRENT_DRAFT_PATH)
    issues = _jsonl(review / "automated-review-issues.jsonl")
    kinds = {}
    for i in issues:
        kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
    assert kinds == {"reject": 19, "error": 4}
    assert len(issues) == 23
    assert len({i["case_id"] for i in issues}) == 23


def test_reject_case_set_no_overlap_with_errors(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    tr.preflight(cand, review, tr.CHUNKS_PATH, tr.CHUNK_MANIFEST_PATH,
                 tr.CURRENT_DRAFT_PATH)
    issues = _jsonl(review / "automated-review-issues.jsonl")
    rejects = {i["case_id"] for i in issues if i["kind"] == "reject"}
    errors = {i["case_id"] for i in issues if i["kind"] == "error"}
    assert len(rejects) == 19
    assert len(errors) == 4
    assert not (rejects & errors)
    assert rejects | errors == set(tr.ERROR_CASES) | rejects


# ── 4. 分流一：coherence errors ────────────────────────────────────────

def test_coherence_errors_all_classified_contract_inconsistency(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    out = tmp_path / "out"
    tr.run(out_dir=out, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    rows = _jsonl(out / "review-coherence-errors.jsonl")
    assert len(rows) == 4
    assert [r["case_id"] for r in rows] == sorted(tr.ERROR_CASES)
    for r in rows:
        assert r["kind"] == "error"
        assert r["classification"] == "model_output_contract_inconsistency"
        assert r["rewritten"] is False
        assert r["refusal_conflict"] is False
        assert r["schema_conflict"] is False
        assert r["expected_decision"] == "confirmed"


def test_coherence_errors_not_rewritten(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    issues = _jsonl(review / "automated-review-issues.jsonl")
    out = tmp_path / "out"
    tr.run(out_dir=out, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    rows = _jsonl(out / "review-coherence-errors.jsonl")
    for r in rows:
        issue = next(i for i in issues if i["case_id"] == r["case_id"])
        assert r["issue_detail"] == issue["detail"]
        assert r["attempts"] == issue["attempts"]


def test_coherence_errors_expected_decision_derived(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    out = tmp_path / "out"
    tr.run(out_dir=out, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    rows = _jsonl(out / "review-coherence-errors.jsonl")
    for r in rows:
        assert r["model_decision"] == "reject/needs_followup"
        assert r["remediation"]["recheck_required"] is True
        note = r["remediation"]["note"]
        # 契约矛盾三要素：本地契约无分歧 / 契约要求 confirmed / 模型输出自相矛盾
        assert "without any disagreement" in note
        assert "confirmed" in note
        assert "自相矛盾" in note


# ── 5. 分流二：substantive rejects ─────────────────────────────────────

def test_reject_triage_19_rows_exactly_once(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    out = tmp_path / "out"
    tr.run(out_dir=out, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    rows = _jsonl(out / "reject-root-cause-triage.jsonl")
    assert len(rows) == 19
    assert len({r["case_id"] for r in rows}) == 19
    issues = _jsonl(review / "automated-review-issues.jsonl")
    reject_ids = {i["case_id"] for i in issues if i["kind"] == "reject"}
    assert {r["case_id"] for r in rows} == reject_ids


def test_reject_rows_have_valid_classification_and_action(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    out = tmp_path / "out"
    tr.run(out_dir=out, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    rows = _jsonl(out / "reject-root-cause-triage.jsonl")
    for r in rows:
        assert r["case_classification"] in tr.CLASSES
        assert r["suggested_action"] in tr.ACTIONS
        assert r["attempts"] == 1 or r["attempts"] >= 1
        for ap in r["answer_point_relations"]:
            assert ap["classification"] in tr.CLASSES
            assert "evidence_relation" in ap
            assert "ap_index" in ap
            assert "answer_point" in ap


def test_reject_each_ap_has_evidence_relation(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    out = tmp_path / "out"
    tr.run(out_dir=out, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    rows = _jsonl(out / "reject-root-cause-triage.jsonl")
    drafts = {d["id"]: d for d in _jsonl(cand / "draft-after.jsonl")}
    for r in rows:
        ap_count = len(drafts[r["case_id"]]["acceptable_answer_points"] or [])
        assert len(r["answer_point_relations"]) == ap_count
        assert [a["ap_index"] for a in r["answer_point_relations"]] == \
            list(range(ap_count))


def test_same_source_candidates_have_full_provenance(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    out = tmp_path / "out"
    tr.run(out_dir=out, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    rows = _jsonl(out / "reject-root-cause-triage.jsonl")
    for r in rows:
        for c in r["same_source_candidates"]:
            assert c["source_id"]
            assert c["chunk_id"]
            assert isinstance(c["start"], int) and isinstance(c["end"], int)
            assert c["end"] > c["start"]
            assert c["span"]
            assert c["unique"] >= 1
            assert c["overlaps_existing"] is False


# ── 6. classify_ap 单元测试（合成数据） ───────────────────────────────

def test_classify_verbatim_exact():
    r = tr.classify_ap("索引和切片",
                       ["列表和字符串支持索引和切片操作"],
                       {}, set(), [])
    assert r["classification"] == "exact"
    assert r["evidence_relation"] == "containment"


def test_classify_containment_exact():
    r = tr.classify_ap("索引操作",
                       ["列表支持索引操作"],
                       {}, set(), [])
    assert r["classification"] == "exact"
    assert r["evidence_relation"] == "containment"


def test_classify_partial_lcs():
    r = tr.classify_ap("escape 用于转义特殊字符",
                       ["使用 escaping 机制处理特殊字符"],
                       {}, set(), [])
    assert r["classification"] in ("partial", "exact")


def test_classify_cross_language_token_same_source():
    chunks = {"c1": {"chunk_id": "c1", "source": "doc.md",
                     "text": "The ROLLBACK statement undoes the transaction."}}
    r = tr.classify_ap("支持 ROLLBACK 回滚事务",
                       ["Some unrelated Chinese evidence text"],
                       chunks, {"doc.md"}, [])
    assert r["classification"] == "same_source"
    assert r["same_source_candidates"][0]["chunk_id"] == "c1"
    assert r["same_source_candidates"][0]["overlaps_existing"] is False
    assert r["same_source_candidates"][0]["source_id"] == "doc.md"


def test_classify_cross_language_token_second_occurrence_same_source():
    # 首个 token 命中与现有 span 重叠时，必须继续扫描后续出现位置（防漏报）
    chunks = {"c1": {"chunk_id": "c1", "source": "doc.md",
                     "text": "ROLLBACK undoes; and ROLLBACK restores."}}
    r = tr.classify_ap("支持 ROLLBACK 回滚",
                       ["irrelevant evidence text"],
                       chunks, {"doc.md"},
                       [("c1", 0, 8)])
    assert r["classification"] == "same_source"
    assert r["same_source_candidates"][0]["start"] > 8


def test_classify_cross_language_no_token_translation():
    r = tr.classify_ap("支持ROLLBACK回滚事务",
                       ["Some English evidence text about transactions"],
                       {}, set(), [])
    assert r["classification"] == "translation"


def test_classify_cross_language_no_shared_no_direct():
    r = tr.classify_ap("完全无关的中文主张",
                       ["English evidence without relation"],
                       {}, set(), [])
    assert r["classification"] == "no_direct"


def test_classify_same_language_original_hit_same_source():
    # 同语言：整句原文命中同 source chunk 其他位置 → same_source 候选
    chunks = {"c1": {"chunk_id": "c1", "source": "doc.md",
                     "text": "OVER win 是简化形式，完整形式为 OVER window-name。"}}
    r = tr.classify_ap("OVER win 是简化形式",
                       ["完全不同的证据文本内容"],
                       chunks, {"doc.md"}, [])
    assert r["classification"] == "same_source"
    cand = r["same_source_candidates"][0]
    assert cand["chunk_id"] == "c1"
    assert cand["span"] == "OVER win 是简化形式"
    assert cand["unique"] == 1
    assert cand["overlaps_existing"] is False


def test_classify_candidate_must_not_overlap_existing_span():
    chunks = {"c1": {"chunk_id": "c1", "source": "doc.md",
                     "text": "ROLLBACK 可以回滚事务，ROLLBACK 也可恢复。"}}
    # 现有 span 覆盖 [0,8)，唯一命中点重叠 → 无新候选
    r = tr.classify_ap("支持 ROLLBACK 回滚",
                       ["无关证据文本"],
                       chunks, {"doc.md"},
                       [("c1", 0, 8)])
    assert r["classification"] in ("no_direct", "translation")


# ── 7. owner-decision-template ─────────────────────────────────────────

def test_owner_template_structure(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    out = tmp_path / "out"
    tr.run(out_dir=out, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    rows = _jsonl(out / "owner-decision-template.jsonl")
    assert len(rows) == 23
    assert len({r["case_id"] for r in rows}) == 23
    for r in rows:
        assert r["kind"] in ("reject", "error")
        assert r["classification"]
        assert r["suggested_action"]
        assert r["owner_decision"] is None
        assert r["owner_reviewer"] is None
        assert r["owner_notes"] is None


# ── 8. data-quality-report ─────────────────────────────────────────────

def test_data_quality_report_five_dims(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    out = tmp_path / "out"
    tr.run(out_dir=out, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    dq = json.loads((out / "data-quality-report.json").read_text(encoding="utf-8"))
    dims = dq["deterministic_data_quality_checks"]
    for dim in ("completeness", "uniqueness", "referential_integrity",
                "continuity", "consistency"):
        assert dim in dims
        assert all(v is True for v in dims[dim].values())
    assert dq.get("findings") == []
    assert "skill" in dq
    assert dq["skill"]["available"] is False


# ── 9. manifest 与 SHA ─────────────────────────────────────────────────

def test_manifest_self_hash_roundtrip():
    m = {"a": 1, "b": {"c": [1, 2]}}
    signed = tr._manifest(m)
    assert tr._verify_manifest(signed)


def test_output_manifest_self_hash(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    out = tmp_path / "out"
    tr.run(out_dir=out, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert tr._verify_manifest(m)


def test_output_manifest_outputs_sha_match_disk(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    out = tmp_path / "out"
    tr.run(out_dir=out, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for name, digest in m["outputs"].items():
        assert (out / name).is_file()
        assert tr._sha256_file(out / name) == digest


def test_output_manifest_inputs_sha_match_sources(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    out = tmp_path / "out"
    tr.run(out_dir=out, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    inputs = m["inputs"]
    assert inputs["candidate-draft-after.jsonl"] == _sha(cand / "draft-after.jsonl")
    assert inputs["candidate-evidence-after.jsonl"] == _sha(cand / "evidence-after.jsonl")
    assert inputs["chunks.jsonl"] == _sha(tr.CHUNKS_PATH)
    assert inputs["chunk-manifest.json"] == _sha(tr.CHUNK_MANIFEST_PATH)


def test_summary_counts_conservation(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    out = tmp_path / "out"
    summary = tr.run(out_dir=out, cand=cand, review=review,
                     chunks_path=tr.CHUNKS_PATH,
                     chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
                     current_draft_path=tr.CURRENT_DRAFT_PATH)
    counts = summary["counts"]
    assert counts["case_count"] == 136
    assert counts["evidence_count"] == 148
    assert counts["confirmed"] == 113
    assert counts["reject"] == 19
    assert counts["needs_followup"] == 0
    assert counts["errors"] == 4
    assert counts["issues_rows"] == 23
    assert summary["coherence_errors"]["count"] == 4
    assert summary["reject_triage"]["count"] == 19
    assert summary["gate_verdict"] == "COHERENCE_REJECT_TRIAGE_OK"
    assert summary["deterministic"] is True
    assert summary["declarations"]["data_modified"] is False
    assert summary["declarations"]["llm_called"] is False
    assert summary["declarations"]["network_used"] is False
    assert summary["declarations"]["overlay_generated"] is False


def test_input_sha_unchanged_after_build(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    before = {
        "draft": _sha(cand / "draft-after.jsonl"),
        "evidence": _sha(cand / "evidence-after.jsonl"),
        "chunks": _sha(tr.CHUNKS_PATH),
        "chunk-manifest": _sha(tr.CHUNK_MANIFEST_PATH),
    }
    out = tmp_path / "out"
    tr.run(out_dir=out, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    assert _sha(cand / "draft-after.jsonl") == before["draft"]
    assert _sha(cand / "evidence-after.jsonl") == before["evidence"]
    assert _sha(tr.CHUNKS_PATH) == before["chunks"]
    assert _sha(tr.CHUNK_MANIFEST_PATH) == before["chunk-manifest"]


def test_review_inputs_unchanged_after_build(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    issues = _sha(review / "automated-review-issues.jsonl")
    manifest = _sha(review / "manifest.json")
    out = tmp_path / "out"
    tr.run(out_dir=out, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    assert _sha(review / "automated-review-issues.jsonl") == issues
    assert _sha(review / "manifest.json") == manifest


def test_two_builds_byte_identical(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    out1, out2 = tmp_path / "out1", tmp_path / "out2"
    tr.run(out_dir=out1, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    tr.run(out_dir=out2, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    names1 = {p.name for p in out1.iterdir()}
    names2 = {p.name for p in out2.iterdir()}
    assert names1 == names2
    for name in names1:
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()


def test_no_forbidden_outputs(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    out = tmp_path / "out"
    tr.run(out_dir=out, cand=cand, review=review, chunks_path=tr.CHUNKS_PATH,
           chunk_manifest_path=tr.CHUNK_MANIFEST_PATH,
           current_draft_path=tr.CURRENT_DRAFT_PATH)
    for p in out.iterdir():
        name = p.name.lower()
        assert not name.startswith(("overlay", "active", "split", "after"))
        assert "v2.1" not in name
        assert not name.startswith(".")


def test_default_out_dir_is_under_review_dir():
    assert str(tr.DEFAULT_OUT).startswith(str(tr.REVIEW_DIR))
