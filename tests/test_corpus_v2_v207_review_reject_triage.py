"""TDD tests for v2.0.7 automated-review reject root-cause triage（只读分流）。

覆盖：输入门禁（canonical 148/126/22/0、issues 集合、candidate 161/161、
无 overlay、SHA 链）、22 条 reject 恰好一次互斥分类与守恒、模型 rationale 与
本地 raw 文本事实并列、全部 span 满足 chunk_text[start:end] == raw_span、
owner-decision-template 仅三个空字段、输入/candidate/review SHA 运行前后
不变、两次构建逐字节一致、manifest 自哈希、fail-closed 零输出、
touched_by_v205_v206 标记、零答案点风险记录、data-analytics skill 不可用
记录与等价五维检查。不读取 split/dev/holdout/历史 review/评测结果。
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts import corpus_v2_v207_review_reject_triage as t

REVIEW_DIR = t.REVIEW_DIR
CANDIDATE_DIR = t.CANDIDATE_DIR

EXPECTED_REJECTS = frozenset({
    "en-029", "en-042", "en-044", "en-049", "en-050", "en-051",
    "mixed-026", "mixed-027", "mixed-028", "mixed-029", "mixed-033",
    "multi-019", "multi-030",
    "zh-023", "zh-026", "zh-029", "zh-036", "zh-040", "zh-042", "zh-045",
    "zh-052", "zh-054",
})

# v2.0.5/v2.0.6 曾改动的 case（不得预设其结论，仅标记）
TOUCHED = frozenset({"mixed-029", "zh-023", "zh-026", "zh-029", "zh-036",
                     "zh-054", "zh-055", "mixed-028"})


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _recompute_self_hash(manifest: dict) -> str:
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    return hashlib.sha256(
        (json.dumps(body, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    ).hexdigest()


# ── 常量 / 门禁 ───────────────────────────────────────────────────────

def test_constants():
    assert t.EXPECTED_CASE_COUNT == 148
    assert t.EXPECTED_CONFIRMED == 126
    assert t.EXPECTED_REJECT == 22
    assert t.EXPECTED_FOLLOWUP == 0
    assert t.CATEGORIES == (
        "exact_evidence_present_but_review_semantic_disagrees",
        "partial_or_paraphrase_only",
        "answer_point_overclaims_available_evidence",
        "evidence_scope_insufficient_but_same_source_candidate_exists",
        "no_direct_support_in_declared_source",
        "cross_source_or_cross_document_coverage_gap",
        "refusal_label_or_schema_inconsistency",
        "review_contract_or_model_semantics_inconsistency",
        "unresolved_requires_owner_judgment",
    )
    assert t.OUTPUT_FILES == (
        "review-reject-triage.jsonl",
        "candidate-evidence-spans.jsonl",
        "review-reject-triage-summary.json",
        "owner-decision-template.jsonl",
        "review-reject-triage-report.md",
        "data-quality-report.json",
        "manifest.json",
    )
    assert t.OWNER_TEMPLATE_KEYS == ("owner_decision", "owner_reviewer",
                                     "owner_notes")
    assert t.TOUCHED_BY_V205_V206 == TOUCHED


def test_preflight_real_candidate():
    checks = t.preflight()
    assert checks["canonical_rows"] == 148
    assert checks["confirmed"] == 126
    assert checks["reject"] == 22
    assert checks["needs_followup"] == 0
    assert checks["issues_set_matches_rejects"] is True
    assert checks["issues_rows"] == 22
    assert checks["case_count"] == 148
    assert checks["strict_validator_covered"] == 161
    assert checks["strict_validator_passed"] == 161
    assert checks["legacy_coordinate_count"] == 0
    assert checks["unresolved_count"] == 0
    assert checks["overlay_absent"] is True
    assert checks["inputs_unchanged"] is True
    assert checks["manifest_ok"] is True
    assert checks["pack_consistent"] is True
    assert checks["review_manifest_ok"] is True
    # data-analytics skill 不可用必须如实记录
    dq = checks["data_quality"]
    assert dq["skill"]["available"] is False
    assert "Skill not found" in dq["skill"]["failure"]
    # 22 条 reject 集合与期望一致
    assert set(checks["reject_ids"]) == EXPECTED_REJECTS
    # 31 个 refusal case 全部 confirmed（不在 triage 集合内）
    assert len(checks["refusal_ids"]) == 31


def test_preflight_fail_closed_any_drift(tmp_path):
    """任一输入漂移 → TriageError 且零输出。"""
    # 复制输入到 tmp，修改 canonical 一条 decision → 必须失败
    canon = _jsonl(REVIEW_DIR / "automated-review.jsonl")
    canon[0] = dict(canon[0], decision="confirmed")
    tmp_review = tmp_path / "review"
    tmp_review.mkdir()
    for name in t.REVIEW_FILES:
        shutil.copy(REVIEW_DIR / name, tmp_review / name)
    (tmp_review / "automated-review.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in canon) + "\n",
        encoding="utf-8")
    with pytest.raises(t.TriageError):
        t.preflight(review_dir=tmp_review)


def test_preflight_fail_closed_missing_input(tmp_path):
    canon = _jsonl(REVIEW_DIR / "automated-review.jsonl")
    # 只复制 canonical，缺 issues/manifest → 失败
    tmp_review = tmp_path / "review"
    tmp_review.mkdir()
    (tmp_review / "automated-review.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in canon) + "\n",
        encoding="utf-8")
    with pytest.raises(t.TriageError):
        t.preflight(review_dir=tmp_review)


def test_issues_rows_equal_canonical_rows():
    canon = _jsonl(REVIEW_DIR / "automated-review.jsonl")
    issues = _jsonl(REVIEW_DIR / "automated-review-issues.jsonl")
    by_id = {r["case_id"]: r for r in canon}
    assert all(by_id[i["case_id"]] == i for i in issues)


# ── run 输出结构 / 分类守恒 ───────────────────────────────────────────

def test_run_outputs_22_rows_unique_sorted(tmp_path):
    out = tmp_path / "out"
    result = t.run(out_dir=out)
    triage = _jsonl(out / "review-reject-triage.jsonl")
    assert len(triage) == 22
    ids = [r["case_id"] for r in triage]
    assert len(set(ids)) == 22
    assert ids == sorted(ids)
    assert set(ids) == EXPECTED_REJECTS
    assert result["summary"]["n_rejects"] == 22


def test_category_conservation(tmp_path):
    result = t.run(out_dir=tmp_path / "out")
    triage = result["triage"]
    counts = {cat: 0 for cat in t.CATEGORIES}
    for row in triage:
        assert row["category"] in t.CATEGORIES
        counts[row["category"]] += 1
    assert sum(counts.values()) == 22
    # summary 中 by_category 计数 == 逐行复算
    for cat in t.CATEGORIES:
        assert len(result["summary"]["by_category"].get(cat, [])) == counts[cat]
    # 每行恰好一个主类别（category 字段唯一）
    assert all(row["category"] for row in triage)
    # 每行都是 reject
    assert all(row["review_decision"] == "reject" for row in triage)


def test_mixed027_model_contract_contradiction(tmp_path):
    """mixed-027 两个答案点均 directly_supported 却 reject → 模型语义矛盾。"""
    result = t.run(out_dir=tmp_path / "out")
    row = next(r for r in result["triage"] if r["case_id"] == "mixed-027")
    assert row["category"] == "review_contract_or_model_semantics_inconsistency"
    assert row["sub_type"] == "supported_assessment_with_reject"
    assert row["contradiction"] is not None
    assert row["mechanically_repairable"] is False
    assert row["requires_owner_decision"] is True


def test_touched_by_v205_v206_marked_only(tmp_path):
    result = t.run(out_dir=tmp_path / "out")
    touched_in_rejects = TOUCHED & EXPECTED_REJECTS
    assert touched_in_rejects == {
        "mixed-029", "zh-023", "zh-026", "zh-029", "zh-036", "zh-054",
        "mixed-028"}
    for row in result["triage"]:
        expected = row["case_id"] in touched_in_rejects
        assert row["touched_by_v205_v206"] is expected
    # zh-055 被 v2.0.5/v2.0.6 改过但不在此次 reject 集合中，不应出现在 triage
    assert "zh-055" not in {r["case_id"] for r in result["triage"]}


def test_zero_answer_point_risk_recorded(tmp_path):
    result = t.run(out_dir=tmp_path / "out")
    for row in result["triage"]:
        assert isinstance(row["zero_answer_point_risk"], bool)
        assert isinstance(row["zero_answer_point_risk_reason"], str)
        # 全部答案点无 evidence 逐字支持 → 零答案点风险 true
        all_none = all(p["in_evidence"] == "none" for p in row["answer_points"])
        assert row["zero_answer_point_risk"] == all_none


def test_no_repairable_no_auto_fix(tmp_path):
    """只读分流：没有任何机械可修复标记，模板字段必须留空。"""
    result = t.run(out_dir=tmp_path / "out")
    assert all(r["mechanically_repairable"] is False for r in result["triage"])
    assert all(r["requires_owner_decision"] is True for r in result["triage"])
    template = _jsonl(tmp_path / "out" / "owner-decision-template.jsonl")
    assert len(template) == 22
    for row in template:
        for key in t.OWNER_TEMPLATE_KEYS:
            assert row.get(key) == ""
        # 模板行除了三个空决策字段外不得携带任何已填写决策
        assert set(t.OWNER_TEMPLATE_KEYS).issubset(row.keys())


def test_owner_template_contains_only_allowlisted_keys(tmp_path):
    """模板行只允许新增三个空字段：owner_decision/owner_reviewer/owner_notes。"""
    result = t.run(out_dir=tmp_path / "out")
    triage_by_id = {r["case_id"]: r for r in result["triage"]}
    template = _jsonl(tmp_path / "out" / "owner-decision-template.jsonl")
    for row in template:
        cid = row["case_id"]
        allowed = set(triage_by_id[cid].keys()) | set(t.OWNER_TEMPLATE_KEYS)
        assert set(row.keys()) == allowed
        for key in t.OWNER_TEMPLATE_KEYS:
            assert row[key] == ""


# ── span 可重建性 ─────────────────────────────────────────────────────

def test_all_spans_raw_provable(tmp_path):
    """candidate-evidence-spans.jsonl 每行 span_text == chunk_text[start:end]。"""
    chunks = {c["chunk_id"]: c for c in _jsonl(t.CHUNKS)}
    result = t.run(out_dir=tmp_path / "out")
    spans = _jsonl(tmp_path / "out" / "candidate-evidence-spans.jsonl")
    assert len(spans) >= 22
    for s in spans:
        rng = s["raw_chunk_char_range"]
        text = chunks[s["chunk_id"]]["text"]
        assert 0 <= rng["start"] <= rng["end"] <= len(text)
        assert text[rng["start"]:rng["end"]] == s["span_text"]
    # 每个 reject case 至少有一条 span 记录
    by_case = {}
    for s in spans:
        by_case.setdefault(s["case_id"], 0)
        by_case[s["case_id"]] += 1
    assert set(by_case) == EXPECTED_REJECTS


def test_evidence_span_in_chunk_text(tmp_path):
    """triage 行 evidence_summary 的 raw span 与 chunk 文本一致（可复核）。"""
    chunks = {c["chunk_id"]: c for c in _jsonl(t.CHUNKS)}
    result = t.run(out_dir=tmp_path / "out")
    for row in result["triage"]:
        for ev in row["evidence_summary"]:
            rng = ev["raw_chunk_char_range"]
            assert chunks[ev["chunk_id"]]["text"][rng["start"]:rng["end"]] \
                == ev["raw_evidence_span"]


# ── SHA 链 / 确定性 ───────────────────────────────────────────────────

def test_input_shas_unchanged(tmp_path):
    inputs = [
        REVIEW_DIR / "automated-review.jsonl",
        REVIEW_DIR / "automated-review-issues.jsonl",
        REVIEW_DIR / "automated-review-evidence.jsonl",
        REVIEW_DIR / "automated-review-pack.jsonl",
        REVIEW_DIR / "manifest.json",
        CANDIDATE_DIR / "manifest.json",
        CANDIDATE_DIR / "draft-after.jsonl",
        CANDIDATE_DIR / "evidence-after.jsonl",
        t.DRAFT, t.CHUNKS, t.CHUNK_MANIFEST,
    ]
    before = {str(p): _sha(p) for p in inputs}
    t.run(out_dir=tmp_path / "out")
    after = {str(p): _sha(p) for p in inputs}
    assert before == after


def test_candidate_and_review_outputs_unchanged(tmp_path):
    """candidate 11 个输出与 automated-review 9 个输出 SHA 运行前后不变。"""
    cand_manifest = json.loads(
        (CANDIDATE_DIR / "manifest.json").read_text(encoding="utf-8"))
    rev_manifest = json.loads(
        (REVIEW_DIR / "manifest.json").read_text(encoding="utf-8"))
    files = [CANDIDATE_DIR / name for name in cand_manifest["outputs"]]
    files += [REVIEW_DIR / name for name in rev_manifest["outputs"]]
    before = {str(p): _sha(p) for p in files}
    t.run(out_dir=tmp_path / "out")
    after = {str(p): _sha(p) for p in files}
    assert before == after
    # 与 manifest 记录值一致
    for name, h in cand_manifest["outputs"].items():
        assert _sha(CANDIDATE_DIR / name) == h
    for name, h in rev_manifest["outputs"].items():
        assert _sha(REVIEW_DIR / name) == h


def test_deterministic_two_runs_byte_identical(tmp_path):
    out1, out2 = tmp_path / "out1", tmp_path / "out2"
    t.run(out_dir=out1)
    t.run(out_dir=out2)
    for name in t.OUTPUT_FILES:
        assert _sha(out1 / name) == _sha(out2 / name), name


def test_manifest_self_hash_matches_disk(tmp_path):
    out = tmp_path / "out"
    t.run(out_dir=out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_sha256"] == _recompute_self_hash(manifest)
    # outputs SHA 与磁盘一致
    for name, h in manifest["outputs"].items():
        assert _sha(out / name) == h


# ── 产物约束 ──────────────────────────────────────────────────────────

def test_exact_output_file_set(tmp_path):
    out = tmp_path / "out"
    t.run(out_dir=out)
    names = sorted(p.name for p in out.iterdir())
    assert names == sorted(t.OUTPUT_FILES)
    # 无任何修复/after/overlay/active/v2.1/split 产物
    for name in names:
        assert "draft-after" not in name
        assert "evidence-after" not in name
        assert "overlay" not in name
        assert "active" not in name
        assert "v2.1" not in name
        assert "split" not in name.lower()


def test_manifest_declarations(tmp_path):
    out = tmp_path / "out"
    result = t.run(out_dir=out)
    manifest = result["manifest"]
    assert manifest["declarations"] == {
        "llm_called": False, "network_used": False,
        "overlay_generated": False, "data_modified": False,
        "v2_1_entered": False, "split_created": False,
        "historical_verdicts_read": False,
    }
    assert manifest["task"] == "v2.0.7-review-reject-triage"
    assert manifest["gate_verdict"] == "REJECT_TRIAGE_OK"
    assert manifest["n_rejects"] == 22
    assert manifest["forbidden_outputs"] == [
        "overlay", "active metadata", "v2.1 pointer", "split reuse",
        "locked config", "evaluation results"]


def test_data_quality_report_five_dimensions(tmp_path):
    out = tmp_path / "out"
    t.run(out_dir=out)
    dq = json.loads((out / "data-quality-report.json").read_text(encoding="utf-8"))
    assert dq["skill"]["available"] is False
    assert "Skill not found" in dq["skill"]["failure"]
    for dim in ("completeness", "uniqueness", "referential_integrity",
                "continuity", "consistency"):
        assert dim in dq["equivalent_deterministic_checks"]
    checks = dq["equivalent_deterministic_checks"]
    assert checks["completeness"]["canonical_rows"] == 148
    assert checks["completeness"]["reject_rows"] == 22
    assert checks["completeness"]["evidence_rows"] == 161
    assert checks["uniqueness"]["reject_case_ids_unique"] is True
    assert checks["referential_integrity"]["evidence_chunks_in_corpus"] is True
    assert checks["continuity"]["spans_proved"] >= 22
    assert checks["consistency"]["input_shas_unchanged"] is True
    assert checks["consistency"]["issues_set_matches_rejects"] is True


def test_report_lists_all_22_with_rationale_and_facts(tmp_path):
    out = tmp_path / "out"
    result = t.run(out_dir=out)
    report = (out / "review-reject-triage-report.md").read_text(encoding="utf-8")
    for row in result["triage"]:
        assert row["case_id"] in report
        assert row["category"] in report
        # 模型 rationale 必须逐条列出（前 80 字符片段）
        assert row["review_rationale"][:80] in report
    assert "不是修复" in report or "只读分流" in report
    assert "22 条" in report


# ── fail-closed 零输出 ────────────────────────────────────────────────

def test_fail_closed_zero_output(tmp_path):
    """门禁失败 → TriageError 且 out_dir 不存在（无半成品）。"""
    canon = _jsonl(REVIEW_DIR / "automated-review.jsonl")
    canon[0] = dict(canon[0], decision="confirmed")
    tmp_review = tmp_path / "review"
    tmp_review.mkdir()
    for name in t.REVIEW_FILES:
        shutil.copy(REVIEW_DIR / name, tmp_review / name)
    (tmp_review / "automated-review.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in canon) + "\n",
        encoding="utf-8")
    out = tmp_path / "out"
    with pytest.raises(t.TriageError):
        t.run(review_dir=tmp_review, out_dir=out)
    assert not out.exists()


def test_cli_main_fail_closed(tmp_path, monkeypatch, capsys):
    """CLI 入口在门禁失败时返回 2 并输出错误信息。"""
    canon = _jsonl(REVIEW_DIR / "automated-review.jsonl")
    canon[0] = dict(canon[0], decision="confirmed")
    tmp_review = tmp_path / "review"
    tmp_review.mkdir()
    for name in t.REVIEW_FILES:
        shutil.copy(REVIEW_DIR / name, tmp_review / name)
    (tmp_review / "automated-review.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in canon) + "\n",
        encoding="utf-8")
    monkeypatch.setattr(t.sys, "argv", ["triage", "--review-dir", str(tmp_review)])
    assert t.main() == 2
    assert "failed closed" in capsys.readouterr().err


# ── 分类细节可复核性 ──────────────────────────────────────────────────

def test_en042_same_source_candidate_present(tmp_path):
    """en-042：'generic URI syntax' 存在于 rfc3986 同 source，evidence 未覆盖。"""
    result = t.run(out_dir=tmp_path / "out")
    row = next(r for r in result["triage"] if r["case_id"] == "en-042")
    assert row["category"] == "evidence_scope_insufficient_but_same_source_candidate_exists"
    candidates = row["scope_candidates"]
    assert any("generic URI syntax" in c["span_text"] for c in candidates)
    assert any(c["chunk_id"] == "86ef1bf559c5_chunk_0" for c in candidates)
    # 候选 span 必须可重建
    chunks = {c["chunk_id"]: c for c in _jsonl(t.CHUNKS)}
    for c in row["scope_candidates"]:
        rng = c["raw_chunk_char_range"]
        assert chunks[c["chunk_id"]]["text"][rng["start"]:rng["end"]] == c["span_text"]


def test_zh040_other_answer_points_in_same_chunk(tmp_path):
    """zh-040：'输入与输出'/'错误和异常' 在 chunk_1 内、evidence span 之外。"""
    result = t.run(out_dir=tmp_path / "out")
    row = next(r for r in result["triage"] if r["case_id"] == "zh-040")
    assert row["category"] == "evidence_scope_insufficient_but_same_source_candidate_exists"
    texts = {c["span_text"] for c in row["scope_candidates"]}
    assert any("输入与输出" in txt for txt in texts)
    assert any("错误和异常" in txt for txt in texts)


def test_exact_evidence_cases_classified_semantic_disagreement(tmp_path):
    """逐字答案点（孤立 token）在 evidence 中可重建但模型语义拒绝。"""
    result = t.run(out_dir=tmp_path / "out")
    by_id = {r["case_id"]: r for r in result["triage"]}
    for cid in ("mixed-028", "mixed-029", "zh-023", "zh-026", "zh-029",
                "zh-036", "zh-054"):
        row = by_id[cid]
        assert row["category"] == \
            "exact_evidence_present_but_review_semantic_disagrees"
        # 每个答案点 in_evidence == exact
        assert all(p["in_evidence"] == "exact" for p in row["answer_points"])


def test_language_mismatch_cases(tmp_path):
    """中文答案点对英文源 → 逐字不适用 → partial_or_paraphrase_only。"""
    result = t.run(out_dir=tmp_path / "out")
    by_id = {r["case_id"]: r for r in result["triage"]}
    for cid in ("en-029", "multi-019", "zh-052"):
        row = by_id[cid]
        assert row["category"] == "partial_or_paraphrase_only"
        assert row["sub_type"] == "language_mismatch"
        assert any(p["language_mismatch"] for p in row["answer_points"])


def test_mixed026_no_direct_support(tmp_path):
    result = t.run(out_dir=tmp_path / "out")
    row = next(r for r in result["triage"] if r["case_id"] == "mixed-026")
    assert row["category"] == "no_direct_support_in_declared_source"


def test_rationale_never_treated_as_fact(tmp_path):
    """分类依据本地文本事实：每行记录模型 assessment 与本地事实分离。"""
    result = t.run(out_dir=tmp_path / "out")
    for row in result["triage"]:
        # 模型输出原样记录
        assert isinstance(row["review_rationale"], str)
        assert isinstance(row["answer_point_assessments"], list)
        # 本地事实独立记录
        assert isinstance(row["facts"], dict)
        assert "evidence_status_by_point" in row["facts"]
        # 分类是本地事实判定，不依赖 rationale 文本
        assert row["category"] in t.CATEGORIES
