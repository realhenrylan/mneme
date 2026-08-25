"""v2.0.9 automated-review coherence and reject root-cause triage — TDD 测试（先 RED 再 GREEN）。

覆盖任务验收：
- 计数守恒（137/144/strict 144；111+22+0+4=137）；无 overlay；
- 4 条 error 精确归类 model_output_contract_inconsistency，且不得被自动改写；
- 22 条 reject 恰好一次分类（无重复、无遗漏），direct/partial/token/source-scope 边界；
- mixed-033 重复 evidence 去重安全性（只写建议，不修改数据）；
- 输入 SHA 任务前后不变；两次构建逐字节一致；manifest 自校验；
- 禁止生成 after/overlay/active/split/v2.1 文件。
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

import scripts.corpus_v2_v209_coherence_reject_triage as tr


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
    assert tr.EXPECTED_CASE_COUNT == 137
    assert tr.EXPECTED_EVIDENCE_COUNT == 144
    assert tr.EXPECTED_CONFIRMED == 111
    assert tr.EXPECTED_REJECT == 22
    assert tr.EXPECTED_NEEDS_FOLLOWUP == 0
    assert tr.EXPECTED_ERRORS == 4


# ── 2. 预检 fail-closed ─────────────────────────────────────────────────

def test_preflight_real_inputs_pass(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    checks = tr.preflight(
        cand, review, tr.CHUNKS_PATH, tr.CHUNK_MANIFEST_PATH,
        tr.CURRENT_DRAFT_PATH)
    assert checks["case_count_ok"] is True
    assert checks["evidence_count_ok"] is True
    assert checks["strict_144_144_ok"] is True
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
    _tamper_output(cand, "draft-after.jsonl", lambda rows: rows.pop())
    with pytest.raises(tr.TriageError):
        tr.preflight(cand, review, tr.CHUNKS_PATH, tr.CHUNK_MANIFEST_PATH,
                     tr.CURRENT_DRAFT_PATH)


def test_preflight_evidence_count_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    _tamper_output(cand, "evidence-after.jsonl", lambda rows: rows.pop())
    with pytest.raises(tr.TriageError):
        tr.preflight(cand, review, tr.CHUNKS_PATH, tr.CHUNK_MANIFEST_PATH,
                     tr.CURRENT_DRAFT_PATH)


def test_preflight_issues_rows_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    (review / "automated-review-issues.jsonl").write_text(
        "{\"case_id\":\"en-040\",\"kind\":\"reject\",\"attempts\":1}\n",
        encoding="utf-8")
    with pytest.raises(tr.TriageError):
        tr.preflight(cand, review, tr.CHUNKS_PATH, tr.CHUNK_MANIFEST_PATH,
                     tr.CURRENT_DRAFT_PATH)


def test_preflight_overlay_present_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    (review / "automated-overlay.json").write_text("{}", encoding="utf-8")
    with pytest.raises(tr.TriageError):
        tr.preflight(cand, review, tr.CHUNKS_PATH, tr.CHUNK_MANIFEST_PATH,
                     tr.CURRENT_DRAFT_PATH)


def test_preflight_candidate_manifest_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    _rewrite_manifest(cand, lambda m: m.update({"revision_status": "ACTIVE"}))
    with pytest.raises(tr.TriageError):
        tr.preflight(cand, review, tr.CHUNKS_PATH, tr.CHUNK_MANIFEST_PATH,
                     tr.CURRENT_DRAFT_PATH)


def test_preflight_review_manifest_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    m = json.loads((review / "manifest.json").read_text(encoding="utf-8"))
    m["counts"]["confirmed"] = 999
    (review / "manifest.json").write_text(tr._dump(m), encoding="utf-8")
    with pytest.raises(tr.TriageError):
        tr.preflight(cand, review, tr.CHUNKS_PATH, tr.CHUNK_MANIFEST_PATH,
                     tr.CURRENT_DRAFT_PATH)


def test_preflight_chunks_sha_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    bad = tmp_path / "chunks.jsonl"
    bad.write_text("garbage\n", encoding="utf-8")
    with pytest.raises(tr.TriageError):
        tr.preflight(cand, review, bad, tr.CHUNK_MANIFEST_PATH,
                     tr.CURRENT_DRAFT_PATH)


# ── 3. 计数守恒与 issue 集合 ────────────────────────────────────────────

def test_conservation_counts_real(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    issues = _jsonl(review / "automated-review-issues.jsonl")
    kinds = [i["kind"] for i in issues]
    assert kinds.count("reject") == tr.EXPECTED_REJECT
    assert kinds.count("error") == tr.EXPECTED_ERRORS
    assert len(issues) == tr.EXPECTED_REJECT + tr.EXPECTED_ERRORS
    ids = [i["case_id"] for i in issues]
    assert len(ids) == len(set(ids)), "case_id 无重复"


def test_error_case_set_exact():
    _, _, errors = tr.load_issues()  # (issues, rejects, errors)
    err_ids = sorted(e["case_id"] for e in errors)
    assert err_ids == ["en-052", "mixed-030", "mixed-033", "multi-011"]


def test_reject_case_set_no_overlap_with_errors():
    _, rejects, errors = tr.load_issues()
    r_ids = {r["case_id"] for r in rejects}
    e_ids = {e["case_id"] for e in errors}
    assert r_ids.isdisjoint(e_ids)
    assert len(r_ids) == tr.EXPECTED_REJECT


# ── 4. 分流一：4 条 model-output coherence errors ───────────────────────

def test_coherence_errors_all_classified_contract_inconsistency(tmp_path):
    out = tmp_path / "out1"
    _run_build(out)
    rows = _jsonl(out / tr.OUTPUT_ERRORS)
    assert len(rows) == 4
    for r in rows:
        assert r["classification"] == tr.ERROR_CLASS
        assert r["kind"] == "error"
        assert r["attempts"] == 4
        assert r["expected_decision"] == "confirmed"
        assert r["refusal_conflict"] is False


def test_coherence_errors_not_rewritten(tmp_path):
    """error 不得被自动改写：无 decision 改写、无 confirmed 输出。"""
    out = tmp_path / "out2"
    _run_build(out)
    rows = _jsonl(out / tr.OUTPUT_ERRORS)
    for r in rows:
        assert "decision" not in r, "不得改写 error 的 decision"
        assert r["model_decision"] == "reject/needs_followup"
        assert r["rewritten"] is False
    assert all(r["case_id"] not in _jsonl(out / tr.OUTPUT_REJECTS)
               for r in rows)


def test_coherence_errors_expected_decision_derived(tmp_path):
    """本地证据关系核验：4 个 error 的答案点均有直接 evidence（非 no_direct）。"""
    out = tmp_path / "out3"
    _run_build(out)
    for r in _jsonl(out / tr.OUTPUT_ERRORS):
        for ap in r["answer_point_relations"]:
            assert ap["classification"] != tr.CLASS_NO_DIRECT


# ── 5. 分流二：22 条 reject 恰好一次分类 ───────────────────────────────

def test_reject_triage_22_rows_exactly_once(tmp_path):
    out = tmp_path / "out4"
    _run_build(out)
    rows = _jsonl(out / tr.OUTPUT_REJECTS)
    assert len(rows) == 22
    ids = [r["case_id"] for r in rows]
    assert len(ids) == len(set(ids))
    _, rejects, _ = tr.load_issues()
    assert set(ids) == {r["case_id"] for r in rejects}


def test_reject_rows_have_valid_classification_and_action(tmp_path):
    out = tmp_path / "out5"
    _run_build(out)
    for r in _jsonl(out / tr.OUTPUT_REJECTS):
        assert r["case_classification"] in tr.CLASSES
        assert r["suggested_action"] in tr.ACTIONS
        assert r["zero_answer_point_risk"] is False
        assert r["rationale"], "model rationale 原样摘录非空"
        assert r["answer_point_relations"], "每个 reject 至少有 1 条答案点明细"


def test_reject_verbatim_cases_classified_exact(tmp_path):
    """逐字证据支撑的 case 必须归 exact（模型语义分歧）。"""
    out = tmp_path / "out6"
    _run_build(out)
    rows = {r["case_id"]: r for r in _jsonl(out / tr.OUTPUT_REJECTS)}
    for cid in ("mixed-022", "mixed-028", "mixed-029", "multi-012",
                "zh-023", "zh-036", "zh-054"):
        assert rows[cid]["case_classification"] == tr.CLASS_EXACT


def test_reject_multi019_no_direct(tmp_path):
    """multi-019 声明 source 无机械可证候选 → no_direct → retire_case。"""
    out = tmp_path / "out7"
    _run_build(out)
    rows = {r["case_id"]: r for r in _jsonl(out / tr.OUTPUT_REJECTS)}
    assert rows["multi-019"]["case_classification"] == tr.CLASS_NO_DIRECT
    assert rows["multi-019"]["suggested_action"] == tr.ACTION_RETIRE


def test_reject_each_ap_has_evidence_relation(tmp_path):
    out = tmp_path / "out8"
    _run_build(out)
    for r in _jsonl(out / tr.OUTPUT_REJECTS):
        for ap in r["answer_point_relations"]:
            assert ap["classification"] in tr.CLASSES
            assert "evidence_relation" in ap
            assert ap["ap_index"] >= 0


# ── 6. 分类函数边界（确定性） ──────────────────────────────────────────

def test_classify_verbatim_exact():
    chunk_index = {"c": {"chunk_id": "c", "source": "s", "text": "A function returning another function"}}
    res = tr.classify_ap(
        "A function returning another function",
        ["A function returning another function"],
        chunk_index, {"s"}, [])
    assert res["classification"] == tr.CLASS_EXACT
    assert res["evidence_relation"] == "verbatim"


def test_classify_containment_exact():
    res = tr.classify_ap(
        "数量应相等",
        ["序列解包时，左侧变量与右侧序列元素的数量应相等"],
        {}, set(), [])
    assert res["classification"] == tr.CLASS_EXACT
    assert res["evidence_relation"] == "containment"


def test_classify_partial_lcs():
    res = tr.classify_ap(
        "列表内容可以改变（如 cubes[3] = 64）",
        ["与 immutable 字符串不同, 列表是 mutable 类型，其内容可以改变"],
        {}, set(), [])
    assert res["classification"] == tr.CLASS_PARTIAL
    assert res["lcs"] >= 3


def test_classify_cross_language_token_same_source():
    """跨语言且最长不在-span token 命中 → same_source_scope_candidate_exists。"""
    chunk_index = {
        "c6": {"chunk_id": "c6", "source": "postgresql-tutorial.md",
               "text": "Database names must have an alphabetic first character "
                       "and are limited to 63 bytes in length. "
                       "To create that database, simply type: $ createdb"},
    }
    res = tr.classify_ap(
        "PG 用 createdb 且数据库名有限制（字母开头、63 字节）",
        ["Database names must have an alphabetic first character and are "
         "limited to 63 bytes in length"],
        chunk_index, {"postgresql-tutorial.md"}, [("c6", 0, 96)])
    assert res["classification"] == tr.CLASS_SAME_SOURCE
    assert res["same_source_candidates"], "应有 createdb 候选"


def test_classify_cross_language_no_token_translation():
    """跨语言、无 token、共享数字 → translation_equivalence_requires_owner_policy。"""
    res = tr.classify_ap(
        "数据库名限制为 63 字节",
        ["Database names are limited to 63 bytes in length"],
        {}, set(), [])
    assert res["classification"] == tr.CLASS_TRANSLATION


def test_classify_cross_language_no_shared_no_direct():
    res = tr.classify_ap(
        "可以（示例演示直接写数据库文件绕过约束）",
        ["A CHECK constraint may be attached to a column definition"],
        {}, set(), [])
    assert res["classification"] == tr.CLASS_NO_DIRECT


def test_classify_same_language_original_hit_same_source():
    """同语言 AP：原文精确命中同 source chunk（现有 span 之外）→ same_source。"""
    chunk_index = {
        "r1": {"chunk_id": "r1", "source": "rust-book-core.md",
               "text": "Each value in Rust has an owner. There can be only "
                       "one owner at a time."},
    }
    res = tr.classify_ap(
        "Each value in Rust has an owner",
        ["### Ownership Rules\n\nFirst, let's take a look at the ownership "
         "rules."],
        chunk_index, {"rust-book-core.md"}, [])
    assert res["classification"] == tr.CLASS_SAME_SOURCE
    assert res["same_source_candidates"][0]["via"] == "original"


def test_classify_cross_language_tokens_all_in_span_partial():
    """跨语言但 AP 的 ASCII token 全部已出现在现有 span → partial。"""
    res = tr.classify_ap(
        "SQLite SELECT 页有 JOIN 专门小节（LEFT/RIGHT/FULL/INNER/CROSS JOIN 操作符）",
        ["If the join-operator is a \"LEFT JOIN\" or \"LEFT OUTER JOIN\" or "
         "\"RIGHT JOIN\" or \"FULL JOIN\", then after the ON or USING "
         "filtering clauses have been applied.",
         "There is no difference between the \"INNER JOIN\", \"JOIN\" and "
         "\",\" join operators. The \"CROSS JOIN\" join operator produces "
         "the same result. SQLite-specific feature. implement the SELECT"],
        {}, {"sqlite-lang.md"}, [])
    assert res["classification"] == tr.CLASS_PARTIAL


def test_classify_candidate_must_not_overlap_existing_span():
    """候选命中必须不重叠现有 evidence span，否则不算新候选。"""
    chunk_index = {
        "c": {"chunk_id": "c", "source": "s",
              "text": "BEGIN and COMMIT commands automatically. ROLLBACK"},
    }
    res = tr.classify_ap(
        "事务用 BEGIN/COMMIT 包围，可用 ROLLBACK 回滚",
        ["BEGIN and COMMIT commands automatically"],
        chunk_index, {"s"}, [(0, 0, 40)])
    # "ROLLBACK" 命中在 (0,40) 之外 → 有效候选
    assert res["classification"] == tr.CLASS_SAME_SOURCE
    c = res["same_source_candidates"][0]
    assert c["overlaps_existing"] is False


# ── 7. mixed-033 重复 evidence 检查 ─────────────────────────────────────

def test_mixed033_duplicate_check(tmp_path):
    out = tmp_path / "out9"
    _run_build(out)
    chk = json.loads((out / tr.OUTPUT_MIXED033).read_text(encoding="utf-8"))
    assert chk["case_id"] == "mixed-033"
    assert chk["rows"] == 2
    assert chk["byte_identical"] is True
    assert chk["same_chunk"] is True
    assert chk["same_range"] is True
    assert chk["same_raw_span"] is True
    assert chk["supports_same_answer_point"] is True
    assert chk["deletion_advice"]["semantically_safe"] is True
    assert chk["deletion_advice"]["owner_authorization_required"] is True
    assert chk["data_modified"] is False


# ── 8. owner-decision-template ──────────────────────────────────────────

def test_owner_template_structure(tmp_path):
    out = tmp_path / "out10"
    _run_build(out)
    rows = _jsonl(out / tr.OUTPUT_TEMPLATE)
    assert len(rows) == 26  # 4 error + 22 reject
    for r in rows:
        assert r["owner_decision"] is None
        assert r["owner_reviewer"] is None
        assert r["owner_notes"] is None
        assert r["case_id"]
        assert r["classification"]
        assert r["suggested_action"]


# ── 9. manifest 自校验与输出守恒 ────────────────────────────────────────

def test_manifest_self_hash_roundtrip():
    m = tr._manifest({"a": 1, "b": [2, 3]})
    assert tr._verify_manifest(m)
    m2 = dict(m)
    m2["a"] = 99
    assert not tr._verify_manifest(m2)


def test_output_manifest_self_hash(tmp_path):
    out = tmp_path / "out11"
    _run_build(out)
    m = json.loads((out / tr.OUTPUT_MANIFEST).read_text(encoding="utf-8"))
    assert tr._verify_manifest(m)
    assert m["declarations"]["overlay_generated"] is False
    assert m["declarations"]["llm_called"] is False
    assert m["declarations"]["network_used"] is False
    assert m["metadata"]["revision_status"] == "CANDIDATE"
    assert m["metadata"]["activation_blocked"] is True


def test_output_manifest_outputs_sha_match_disk(tmp_path):
    out = tmp_path / "out12"
    _run_build(out)
    m = json.loads((out / tr.OUTPUT_MANIFEST).read_text(encoding="utf-8"))
    for name, sha in m["outputs"].items():
        assert _sha(out / name) == sha


def test_summary_counts_conservation(tmp_path):
    out = tmp_path / "out13"
    _run_build(out)
    s = json.loads((out / tr.OUTPUT_SUMMARY).read_text(encoding="utf-8"))
    assert s["counts"]["confirmed"] == 111
    assert s["counts"]["reject"] == 22
    assert s["counts"]["errors"] == 4
    assert s["coherence_errors"]["count"] == 4
    assert s["reject_triage"]["count"] == 22
    assert sum(s["reject_triage"]["by_classification"].values()) == 22
    assert sum(s["reject_triage"]["by_action"].values()) == 22


# ── 10. 输入 SHA 任务前后不变 ───────────────────────────────────────────

def test_input_sha_unchanged_after_build(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    sha_before = {
        "draft-after.jsonl": _sha(cand / "draft-after.jsonl"),
        "evidence-after.jsonl": _sha(cand / "evidence-after.jsonl"),
        "chunks.jsonl": _sha(tr.CHUNKS_PATH),
        "chunk-manifest.json": _sha(tr.CHUNK_MANIFEST_PATH),
    }
    tr.run(out_dir=tmp_path / "out14", cand=cand, review=review)
    sha_after = {
        "draft-after.jsonl": _sha(cand / "draft-after.jsonl"),
        "evidence-after.jsonl": _sha(cand / "evidence-after.jsonl"),
        "chunks.jsonl": _sha(tr.CHUNKS_PATH),
        "chunk-manifest.json": _sha(tr.CHUNK_MANIFEST_PATH),
    }
    assert sha_before == sha_after
    assert review.exists()  # review 目录未被触碰
    assert not (review / "coherence-reject-triage").exists()


def test_review_inputs_unchanged_after_build(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review(tmp_path, cand)
    before = {p.name: _sha(p) for p in review.iterdir()}
    tr.run(out_dir=tmp_path / "out15", cand=cand, review=review)
    after = {p.name: _sha(p) for p in review.iterdir()}
    assert before == after


# ── 11. 两次构建逐字节一致 ─────────────────────────────────────────────

def test_two_builds_byte_identical(tmp_path):
    tr.run(out_dir=tmp_path / "A")
    tr.run(out_dir=tmp_path / "B")
    for name in tr.OUTPUT_FILES:
        assert _sha(tmp_path / "A" / name) == _sha(tmp_path / "B" / name), name


# ── 12. 禁止生成 after/overlay/active/split/v2.1 文件 ──────────────────

def test_no_forbidden_outputs(tmp_path):
    out = tmp_path / "out16"
    _run_build(out)
    names = {p.name for p in out.iterdir()}
    assert names == set(tr.OUTPUT_FILES)
    for bad in ("automated-overlay.json", "overlay.json", "draft-after.jsonl",
                "evidence-after.jsonl", "active-metadata.json", "split.json",
                "v2.1", "split-seal.json", "locked-config.json"):
        assert bad not in names
    assert not (out / "after").exists()


def test_default_out_dir_is_under_review_dir():
    assert tr.DEFAULT_OUT == tr.REVIEW_DIR / "coherence-reject-triage"
