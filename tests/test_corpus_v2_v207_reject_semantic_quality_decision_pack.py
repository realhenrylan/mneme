"""TDD tests for v2.0.7 reject semantic-quality closure decision pack（只读决策包）。

覆盖：输入门禁（reject 22、triage 集合 == reject、类别分布恰 8/5/6/2/1、
candidate 148、strict 161/161、无 overlay、SHA 链）、22 条逐条语义质量分析
（同 source 自包含 clause/sentence/paragraph 候选、唯一性、scope 标记、
semantic_quality_insufficient、零答案点风险）、五批次建议与推荐动作映射、
owner 批量决策模板（recommended_action 必填、owner 三字段留空）、候选 raw
span 全部可重建（chunk_text[start:end] == raw_span）、不得把 partial/paraphrase
写成 exact（候选 coverage >= 0.75）、输入 SHA 运行前后不变、两次构建逐字节
一致、manifest 自哈希、fail-closed 零输出、data-analytics skill 不可用记录与
等价五维检查。不读取 split/dev/holdout/历史 review/评测结果。
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts import corpus_v2_v207_reject_semantic_quality_decision_pack as p

REVIEW_DIR = p.REVIEW_DIR
CANDIDATE_DIR = p.CANDIDATE_DIR
TRIAGE_DIR = p.TRIAGE_DIR

EXPECTED_REJECTS = frozenset({
    "en-029", "en-042", "en-044", "en-049", "en-050", "en-051",
    "mixed-026", "mixed-027", "mixed-028", "mixed-029", "mixed-033",
    "multi-019", "multi-030",
    "zh-023", "zh-026", "zh-029", "zh-036", "zh-040", "zh-042", "zh-045",
    "zh-052", "zh-054",
})

# 类别分布门禁：8 / 5 / 6 / 2 / 1（其余 0）
EXPECTED_DISTRIBUTION = {
    "exact_evidence_present_but_review_semantic_disagrees": 8,
    "partial_or_paraphrase_only": 5,
    "evidence_scope_insufficient_but_same_source_candidate_exists": 6,
    "no_direct_support_in_declared_source": 2,
    "review_contract_or_model_semantics_inconsistency": 1,
}

# 五批次预测（基于真实数据的确定性分析结果）
EXPECTED_BATCHES = {
    "batch_a_replace_with_self_contained_exact_text": frozenset({
        "mixed-028", "mixed-029", "zh-023", "zh-026", "zh-029", "zh-036",
        "zh-054",
    }),
    "batch_b_expand_same_source_scope": frozenset({"zh-040"}),
    "batch_c_translation_policy_required": frozenset({
        "en-029", "multi-019", "zh-052",
    }),
    "batch_d_retire_or_remove": frozenset({
        "en-042", "en-044", "en-049", "en-050", "en-051", "mixed-026",
        "mixed-033", "multi-030", "zh-042", "zh-045",
    }),
    "batch_e_targeted_re_review": frozenset({"mixed-027"}),
}

EXPECTED_RECOMMENDATIONS = {
    "replace_answer_point_with_self_contained_exact_raw_text": frozenset({
        "mixed-028", "mixed-029", "zh-023", "zh-026", "zh-029", "zh-036",
        "zh-054",
    }),
    "expand_same_source_evidence_scope": frozenset({"zh-040"}),
    "owner_approved_translation_equivalence_policy": frozenset({
        "en-029", "multi-019", "zh-052",
    }),
    "remove_unsupported_answer_point": frozenset({
        "en-042", "en-049", "en-051", "mixed-033",
    }),
    "retire_case": frozenset({
        "en-044", "en-050", "mixed-026", "multi-030", "zh-042", "zh-045",
    }),
    "targeted_blind_re_review": frozenset({"mixed-027"}),
}

# 推荐动作全部移除答案点后 case 归零（删除/退役风险）
REMOVAL_ZERO_RISK_CASES = frozenset({
    "en-044", "en-050", "mixed-026", "multi-030", "zh-042", "zh-045",
})

# 至少一个答案点无自包含完整句候选（仅孤立 token/标题/短标签支撑）
SEMANTIC_QUALITY_INSUFFICIENT_CASES = frozenset({
    "en-029", "en-042", "en-044", "en-049", "en-050", "en-051", "mixed-026",
    "mixed-027", "mixed-033", "multi-019", "multi-030", "zh-040", "zh-042",
    "zh-045", "zh-052",
})


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in
            p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _recompute_self_hash(manifest: dict) -> str:
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    return hashlib.sha256(
        (json.dumps(body, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    ).hexdigest()


def _tampered_triage(tmp_path: Path, mutate) -> Path:
    """复制真实 triage 目录到 tmp，修改一行并修补 manifest（outputs+自哈希）。"""
    tmp_triage = tmp_path / "triage"
    shutil.copytree(TRIAGE_DIR, tmp_triage)
    rows = _jsonl(tmp_triage / "review-reject-triage.jsonl")
    rows = mutate(rows)
    (tmp_triage / "review-reject-triage.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                for r in rows), encoding="utf-8")
    man = json.loads(
        (tmp_triage / "manifest.json").read_text(encoding="utf-8"))
    man["outputs"]["review-reject-triage.jsonl"] = _sha(
        tmp_triage / "review-reject-triage.jsonl")
    body = {k: v for k, v in man.items() if k != "manifest_sha256"}
    man["manifest_sha256"] = hashlib.sha256(
        (json.dumps(body, ensure_ascii=False, indent=1) + "\n").encode(
            "utf-8")).hexdigest()
    (tmp_triage / "manifest.json").write_text(
        json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return tmp_triage


def _copy_all_inputs(tmp_path: Path) -> dict:
    """复制 review/candidate/triage/draft/chunks 到 tmp，返回参数映射。"""
    tmp_review = tmp_path / "review"
    tmp_candidate = tmp_path / "candidate"
    tmp_triage = tmp_path / "triage"
    shutil.copytree(REVIEW_DIR, tmp_review)
    shutil.copytree(CANDIDATE_DIR, tmp_candidate)
    # triage 目录可能已被 _tampered_triage 预置：不得用原件覆盖篡改版
    if not tmp_triage.exists():
        shutil.copytree(TRIAGE_DIR, tmp_triage)
    tmp_draft = tmp_path / "v2-cases-draft.jsonl"
    tmp_chunks = tmp_path / "chunks.jsonl"
    tmp_cm = tmp_path / "chunk-manifest.json"
    shutil.copy(p.DRAFT, tmp_draft)
    shutil.copy(p.CHUNKS, tmp_chunks)
    shutil.copy(p.CHUNK_MANIFEST, tmp_cm)
    return {"review_dir": tmp_review, "candidate_dir": tmp_candidate,
            "triage_dir": tmp_triage, "draft": tmp_draft,
            "chunks_path": tmp_chunks, "chunk_manifest": tmp_cm}


# ── 常量 / 门禁 ───────────────────────────────────────────────────────

def test_constants():
    assert p.OUTPUT_FILES == (
        "semantic-quality-decision-pack.jsonl",
        "self-contained-raw-candidates.jsonl",
        "owner-batch-decision-template.jsonl",
        "OWNER_SEMANTIC_QUALITY_DECISION_GUIDE.md",
        "decision-pack-summary.json",
        "decision-pack-report.md",
        "data-quality-report.json",
        "manifest.json",
    )
    assert p.BATCHES == (
        "batch_a_replace_with_self_contained_exact_text",
        "batch_b_expand_same_source_scope",
        "batch_c_translation_policy_required",
        "batch_d_retire_or_remove",
        "batch_e_targeted_re_review",
    )
    assert p.OWNER_TEMPLATE_KEYS == ("owner_decision", "owner_reviewer",
                                     "owner_notes")
    # 推荐动作 → 批次映射完整（9 个动作全覆盖）
    assert set(p.ACTIONS_TO_BATCHES) == {
        "replace_answer_point_with_self_contained_exact_raw_text",
        "replace_with_exact_source_language_text",
        "expand_same_source_evidence_scope",
        "owner_approved_translation_equivalence_policy",
        "remove_semantically_insufficient_answer_point",
        "remove_unsupported_answer_point",
        "retire_case",
        "keep_unresolved",
        "targeted_blind_re_review",
    }


def test_preflight_real_inputs():
    checks = p.preflight()
    assert set(checks["reject_ids"]) == EXPECTED_REJECTS
    assert set(checks["triage_ids"]) == EXPECTED_REJECTS
    assert checks["triage_rows"] == 22
    assert checks["distribution"] == EXPECTED_DISTRIBUTION
    assert checks["case_count"] == 148
    assert checks["strict_validator_covered"] == 161
    assert checks["strict_validator_passed"] == 161
    assert checks["overlay_absent"] is True
    assert checks["inputs_unchanged"] is True
    assert checks["triage_manifest_ok"] is True
    # data-analytics skill 不可用必须如实记录
    dq = checks["data_quality"]
    assert dq["skill"]["available"] is False
    assert "Skill not found" in dq["skill"]["failure"]


def test_preflight_fail_closed_distribution_drift(tmp_path):
    """triage 类别分布漂移（如改 1 条类别）→ DecisionPackError。"""
    tmp_triage = _tampered_triage(
        tmp_path, lambda rows: [
            dict(r, category="unresolved_requires_owner_judgment")
            if r["case_id"] == "mixed-027" else r for r in rows])
    inputs = _copy_all_inputs(tmp_path)
    inputs["triage_dir"] = tmp_triage
    with pytest.raises(p.DecisionPackError):
        p.preflight(**inputs)


def test_preflight_fail_closed_triage_set_drift(tmp_path):
    """triage 集合与 reject 集合不一致（删 1 条）→ DecisionPackError。"""
    tmp_triage = _tampered_triage(
        tmp_path, lambda rows: [r for r in rows if r["case_id"] != "zh-054"])
    inputs = _copy_all_inputs(tmp_path)
    inputs["triage_dir"] = tmp_triage
    with pytest.raises(p.DecisionPackError):
        p.preflight(**inputs)


def test_preflight_fail_closed_review_drift(tmp_path):
    """review canonical 漂移（改 1 条 decision）→ DecisionPackError。"""
    inputs = _copy_all_inputs(tmp_path)
    canon = _jsonl(inputs["review_dir"] / "automated-review.jsonl")
    canon[0] = dict(canon[0], decision="confirmed")
    (inputs["review_dir"] / "automated-review.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                for r in canon), encoding="utf-8")
    with pytest.raises(p.DecisionPackError):
        p.preflight(**inputs)


def test_preflight_fail_closed_missing_triage(tmp_path):
    inputs = _copy_all_inputs(tmp_path)
    (inputs["triage_dir"] / "review-reject-triage.jsonl").unlink()
    with pytest.raises(p.DecisionPackError):
        p.preflight(**inputs)


def test_triage_rows_match_canonical_rejects():
    triage = _jsonl(TRIAGE_DIR / "review-reject-triage.jsonl")
    assert len(triage) == 22
    assert {r["case_id"] for r in triage} == EXPECTED_REJECTS
    assert all(r["review_decision"] == "reject" for r in triage)


# ── run 输出结构 / 守恒 ───────────────────────────────────────────────

def test_run_outputs_22_rows_unique_sorted(tmp_path):
    out = tmp_path / "out"
    result = p.run(out_dir=out)
    rows = _jsonl(out / "semantic-quality-decision-pack.jsonl")
    assert len(rows) == 22
    ids = [r["case_id"] for r in rows]
    assert ids == sorted(ids)
    assert len(set(ids)) == 22
    assert set(ids) == EXPECTED_REJECTS
    assert result["summary"]["n_rejects"] == 22


def test_batch_conservation_and_mapping(tmp_path):
    result = p.run(out_dir=tmp_path / "out")
    rows = result["rows"]
    by_batch = {b: 0 for b in p.BATCHES}
    for row in rows:
        assert row["recommended_action"] in p.ACTIONS_TO_BATCHES
        assert row["recommended_batch"] == \
            p.ACTIONS_TO_BATCHES[row["recommended_action"]]
        by_batch[row["recommended_batch"]] += 1
    assert sum(by_batch.values()) == 22
    for b in p.BATCHES:
        assert len(result["summary"]["by_batch"][b]["case_ids"]) == by_batch[b]


def test_expected_batch_composition(tmp_path):
    """五批次 case 集合与预测完全一致。"""
    result = p.run(out_dir=tmp_path / "out")
    for batch, info in result["summary"]["by_batch"].items():
        assert set(info["case_ids"]) == EXPECTED_BATCHES[batch], batch
    # 每行推荐动作与预测一致
    by_id = {r["case_id"]: r for r in result["rows"]}
    for action, ids in EXPECTED_RECOMMENDATIONS.items():
        for cid in ids:
            assert by_id[cid]["recommended_action"] == action, cid


def test_category_conservation(tmp_path):
    result = p.run(out_dir=tmp_path / "out")
    counts = {}
    for row in result["rows"]:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    assert counts == EXPECTED_DISTRIBUTION


def test_options_per_category(tmp_path):
    result = p.run(out_dir=tmp_path / "out")
    by_id = {r["case_id"]: r for r in result["rows"]}
    # cat 5：只允许 retire_case / keep_unresolved
    for cid in ("mixed-026", "zh-045"):
        assert by_id[cid]["owner_options"] == ["retire_case",
                                               "keep_unresolved"]
    # cat 8：只允许 targeted_blind_re_review / keep_unresolved
    assert by_id["mixed-027"]["owner_options"] == ["targeted_blind_re_review",
                                                   "keep_unresolved"]
    # cat 2：五个选项齐全
    for cid in ("en-029", "en-044", "en-050", "multi-019", "zh-052"):
        assert set(by_id[cid]["owner_options"]) == {
            "replace_with_exact_source_language_text",
            "owner_approved_translation_equivalence_policy",
            "remove_unsupported_answer_point", "retire_case",
            "keep_unresolved"}
    # cat 1：不得提供“放宽 review 标准”类动作
    for row in result["rows"]:
        if row["category"] == \
                "exact_evidence_present_but_review_semantic_disagrees":
            assert "relax" not in " ".join(row["owner_options"])


def test_removal_zero_risk(tmp_path):
    result = p.run(out_dir=tmp_path / "out")
    by_id = {r["case_id"]: r for r in result["rows"]}
    zero = {cid for cid, r in by_id.items() if r["removal_zero_risk"]}
    assert zero == REMOVAL_ZERO_RISK_CASES
    # retire_case 必然零答案点风险；批次 A/B/C/e 不得标记
    for cid in REMOVAL_ZERO_RISK_CASES:
        assert by_id[cid]["recommended_action"] == "retire_case"
    for cid in EXPECTED_RECOMMENDATIONS[
            "replace_answer_point_with_self_contained_exact_raw_text"]:
        assert by_id[cid]["removal_zero_risk"] is False


def test_semantic_quality_insufficient_flag(tmp_path):
    result = p.run(out_dir=tmp_path / "out")
    by_id = {r["case_id"]: r for r in result["rows"]}
    flagged = {cid for cid, r in by_id.items()
               if r["semantic_quality_insufficient"]}
    assert flagged == SEMANTIC_QUALITY_INSUFFICIENT_CASES
    for row in result["rows"]:
        for ap in row["answer_point_analysis"]:
            assert ap["semantic_quality_insufficient"] == \
                (ap["n_self_contained"] == 0)


# ── 逐条语义质量分析 ──────────────────────────────────────────────────

def test_mixed027_contract_proof(tmp_path):
    """mixed-027：本地契约证明 + 仅 re-review/keep_unresolved。"""
    result = p.run(out_dir=tmp_path / "out")
    row = next(r for r in result["rows"] if r["case_id"] == "mixed-027")
    assert row["recommended_action"] == "targeted_blind_re_review"
    assert row["recommended_batch"] == "batch_e_targeted_re_review"
    proof = row["contract_proof"]
    assert proof is not None
    assert proof["case_id"] == "mixed-027"
    assert proof["decision"] == "reject"
    # 全部答案点模型评估为 directly_supported 却 reject
    assert all(a["assessment"] == "directly_supported"
               for a in proof["answer_point_assessments"])
    # 本地逐字事实与模型评估并列（不作为事实）
    assert "local_verbatim_facts" in proof


def test_zh040_expand_scope_with_exact_toc_candidates(tmp_path):
    """zh-040：三个答案点均有同 source 逐字 TOC 行候选 → 扩 scope。"""
    result = p.run(out_dir=tmp_path / "out")
    row = next(r for r in result["rows"] if r["case_id"] == "zh-040")
    assert row["recommended_action"] == "expand_same_source_evidence_scope"
    assert row["recommended_batch"] == "batch_b_expand_same_source_scope"
    by_ap = {a["answer_point_index"]: a for a in row["answer_point_analysis"]}
    # AP0 已覆盖于 evidence span [0:55)；AP1/AP2 在 chunk_1 内但在证据之外
    refs0 = by_ap[0]["candidate_refs"]
    assert any(r["chunk_id"] == "32c427fb50e2_chunk_1"
               and r["raw_chunk_char_range"] == {"start": 0, "end": 7}
               and r["coverage"] >= 0.75 for r in refs0)
    assert all(r["scope_expansion_required"] is False
               for r in refs0 if r["chunk_id"] == "32c427fb50e2_chunk_1"
               and r["raw_chunk_char_range"] == {"start": 0, "end": 7})
    # AP1 '输入与输出' 与 AP2 '错误和异常' 的 TOC 行（证据范围外 → 需扩 scope）
    chunks = {c["chunk_id"]: c for c in _jsonl(p.CHUNKS)}
    for idx, expect in ((1, "输入与输出"), (2, "错误和异常")):
        refs = by_ap[idx]["candidate_refs"]
        hits = [r for r in refs if r["chunk_id"] == "32c427fb50e2_chunk_1"
                and expect in chunks[r["chunk_id"]]["text"][
                    r["raw_chunk_char_range"]["start"]:
                    r["raw_chunk_char_range"]["end"]]]
        assert hits, (idx, expect)
        assert all(r["scope_expansion_required"] for r in hits)


def test_zh023_self_contained_range_sentence(tmp_path):
    """zh-023：range(10) 完整句候选 → replace 推荐。"""
    result = p.run(out_dir=tmp_path / "out")
    row = next(r for r in result["rows"] if r["case_id"] == "zh-023")
    assert row["recommended_action"] == \
        "replace_answer_point_with_self_contained_exact_raw_text"
    cands = _jsonl(tmp_path / "out" / "self-contained-raw-candidates.jsonl")
    hits = [c for c in cands if c["case_id"] == "zh-023"
            and "range(10)" in c["raw_span"] and "生成 10 个值" in c["raw_span"]]
    assert hits
    assert all(c["candidate_type"] == "full_sentence" for c in hits)
    assert all(c["self_contained"] for c in hits)
    assert all(c["unique"] for c in hits)


def test_mixed028_self_contained_state_sentence(tmp_path):
    result = p.run(out_dir=tmp_path / "out")
    row = next(r for r in result["rows"] if r["case_id"] == "mixed-028")
    assert row["recommended_action"] == \
        "replace_answer_point_with_self_contained_exact_raw_text"
    cands = _jsonl(tmp_path / "out" / "self-contained-raw-candidates.jsonl")
    hits = [c for c in cands if c["case_id"] == "mixed-028"
            and "在 React 中，随时间变化的数据被称为状态（state）"
            in c["raw_span"]]
    assert hits
    assert all(c["candidate_type"] == "full_sentence" for c in hits)


def test_multi030_isolated_heading_only_retire(tmp_path):
    """multi-030：仅标题/短标签（无自包含完整句）→ retire_case。"""
    result = p.run(out_dir=tmp_path / "out")
    row = next(r for r in result["rows"] if r["case_id"] == "multi-030")
    assert row["recommended_action"] == "retire_case"
    assert row["removal_zero_risk"] is True
    assert row["semantic_quality_insufficient"] is True
    ap = row["answer_point_analysis"][0]
    assert ap["n_self_contained"] == 0
    assert all(r["candidate_type"] not in ("full_sentence", "full_paragraph")
               for r in ap["candidate_refs"])


def test_translation_cases_default_policy(tmp_path):
    """中文答案点 + 英文源（language_mismatch）→ 翻译等价策略批次。"""
    result = p.run(out_dir=tmp_path / "out")
    by_id = {r["case_id"]: r for r in result["rows"]}
    for cid in ("en-029", "multi-019", "zh-052"):
        row = by_id[cid]
        assert row["category"] == "partial_or_paraphrase_only"
        assert row["sub_type"] == "language_mismatch"
        assert row["recommended_action"] == \
            "owner_approved_translation_equivalence_policy"
        assert row["recommended_batch"] == "batch_c_translation_policy_required"
        # 不得自动判翻译等价为 confirmed：全部无逐字候选
        assert all(a["n_candidates"] == 0 for a in row["answer_point_analysis"])


def test_remove_unsupported_points_cases(tmp_path):
    """AP0 无证据支撑、AP1 部分支撑 → 仅移除无证据答案点。"""
    result = p.run(out_dir=tmp_path / "out")
    by_id = {r["case_id"]: r for r in result["rows"]}
    for cid in ("en-042", "en-049", "en-051", "mixed-033"):
        row = by_id[cid]
        assert row["recommended_action"] == "remove_unsupported_answer_point"
        assert row["recommended_batch"] == "batch_d_retire_or_remove"
        assert row["removal_zero_risk"] is False
        # 移除目标恰为 in_evidence=none 的答案点
        ap0 = row["answer_point_analysis"][0]
        assert ap0["in_evidence"] == "none"
        assert 0 in row["removal_targets"]


def test_zh042_retire_single_unsupported_point(tmp_path):
    result = p.run(out_dir=tmp_path / "out")
    row = next(r for r in result["rows"] if r["case_id"] == "zh-042")
    assert row["recommended_action"] == "retire_case"
    assert row["removal_zero_risk"] is True
    assert row["answer_point_analysis"][0]["in_evidence"] == "none"
    assert row["answer_point_analysis"][0]["n_candidates"] == 0


def test_no_repairable_no_auto_apply(tmp_path):
    result = p.run(out_dir=tmp_path / "out")
    assert all(r["recommended_action"] for r in result["rows"])
    # 模板行：三字段空、包含 recommended_action、无已填写决策
    template = _jsonl(tmp_path / "out" / "owner-batch-decision-template.jsonl")
    assert len(template) == 22
    by_id = {r["case_id"]: r for r in result["rows"]}
    for row in template:
        assert row["recommended_action"] == by_id[row["case_id"]][
            "recommended_action"]
        for key in p.OWNER_TEMPLATE_KEYS:
            assert row.get(key) == ""
        allowed = set(by_id[row["case_id"]].keys()) | set(p.OWNER_TEMPLATE_KEYS)
        assert set(row.keys()) == allowed


# ── 候选 raw span 可重建性 ────────────────────────────────────────────

def test_all_candidates_raw_provable(tmp_path):
    """self-contained-raw-candidates.jsonl 每行 raw_span == chunk_text[start:end]。"""
    chunks = {c["chunk_id"]: c for c in _jsonl(p.CHUNKS)}
    result = p.run(out_dir=tmp_path / "out")
    cands = _jsonl(tmp_path / "out" / "self-contained-raw-candidates.jsonl")
    assert len(cands) >= 22
    for c in cands:
        rng = c["raw_chunk_char_range"]
        text = chunks[c["chunk_id"]]["text"]
        assert 0 <= rng["start"] <= rng["end"] <= len(text)
        assert text[rng["start"]:rng["end"]] == c["raw_span"]
        # 候选不得把 partial/paraphrase 写成 exact
        assert c["coverage"] >= 0.75
        assert c["candidate_type"] in ("full_sentence", "full_paragraph",
                                       "heading", "line_label")
        assert c["self_contained"] == (c["candidate_type"] in (
            "full_sentence", "full_paragraph"))
        assert c["unique"] == (c["exact_count_in_source"] == 1)
    by_case = {c["case_id"] for c in cands}
    # 无候选的 case 不出现在 candidates 文件中；有候选的必须全部出现
    expected = {r["case_id"] for r in result["rows"]
                if any(a["n_candidates"] > 0
                       for a in r["answer_point_analysis"])}
    assert by_case == expected
    assert by_case <= EXPECTED_REJECTS


def test_scope_expansion_required_consistency(tmp_path):
    """候选不在当前 evidence span 内 → scope_expansion_required=true。"""
    result = p.run(out_dir=tmp_path / "out")
    by_id = {r["case_id"]: r for r in result["rows"]}
    for row in result["rows"]:
        ev_spans = {(e["chunk_id"], e["raw_chunk_char_range"]["start"],
                     e["raw_chunk_char_range"]["end"])
                    for e in row["current_evidence"]}
        for ap in row["answer_point_analysis"]:
            for ref in ap["candidate_refs"]:
                rng = ref["raw_chunk_char_range"]
                covered = any(
                    ref["chunk_id"] == cid and rng["start"] >= s
                    and rng["end"] <= e for cid, s, e in ev_spans)
                assert ref["scope_expansion_required"] == (not covered), (
                    row["case_id"], ap["answer_point_index"], ref)


def test_pack_rows_reference_candidate_file(tmp_path):
    """决策包行 candidate_refs 与 candidates 文件一致（chunk/range 双向）。"""
    result = p.run(out_dir=tmp_path / "out")
    cands = _jsonl(tmp_path / "out" / "self-contained-raw-candidates.jsonl")
    cand_keys = {(c["case_id"], c["answer_point_index"], c["chunk_id"],
                  c["raw_chunk_char_range"]["start"],
                  c["raw_chunk_char_range"]["end"]) for c in cands}
    ref_keys = set()
    for row in result["rows"]:
        for ap in row["answer_point_analysis"]:
            for ref in ap["candidate_refs"]:
                ref_keys.add((row["case_id"], ap["answer_point_index"],
                              ref["chunk_id"],
                              ref["raw_chunk_char_range"]["start"],
                              ref["raw_chunk_char_range"]["end"]))
    assert ref_keys == cand_keys


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
        TRIAGE_DIR / "review-reject-triage.jsonl",
        TRIAGE_DIR / "candidate-evidence-spans.jsonl",
        TRIAGE_DIR / "review-reject-triage-summary.json",
        TRIAGE_DIR / "owner-decision-template.jsonl",
        TRIAGE_DIR / "review-reject-triage-report.md",
        TRIAGE_DIR / "data-quality-report.json",
        TRIAGE_DIR / "manifest.json",
        p.DRAFT, p.CHUNKS, p.CHUNK_MANIFEST,
    ]
    before = {str(path): _sha(path) for path in inputs}
    p.run(out_dir=tmp_path / "out")
    after = {str(path): _sha(path) for path in inputs}
    assert before == after


def test_candidate_review_triage_outputs_unchanged(tmp_path):
    """candidate 11 输出 / review 9 输出 / triage 6 输出 SHA 运行前后不变。"""
    cand_manifest = json.loads(
        (CANDIDATE_DIR / "manifest.json").read_text(encoding="utf-8"))
    rev_manifest = json.loads(
        (REVIEW_DIR / "manifest.json").read_text(encoding="utf-8"))
    tri_manifest = json.loads(
        (TRIAGE_DIR / "manifest.json").read_text(encoding="utf-8"))
    files = [CANDIDATE_DIR / name for name in cand_manifest["outputs"]]
    files += [REVIEW_DIR / name for name in rev_manifest["outputs"]]
    files += [TRIAGE_DIR / name for name in tri_manifest["outputs"]]
    before = {str(path): _sha(path) for path in files}
    p.run(out_dir=tmp_path / "out")
    after = {str(path): _sha(path) for path in files}
    assert before == after


def test_deterministic_two_runs_byte_identical(tmp_path):
    out1, out2 = tmp_path / "out1", tmp_path / "out2"
    p.run(out_dir=out1)
    p.run(out_dir=out2)
    for name in p.OUTPUT_FILES:
        assert _sha(out1 / name) == _sha(out2 / name), name


def test_manifest_self_hash_matches_disk(tmp_path):
    out = tmp_path / "out"
    p.run(out_dir=out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_sha256"] == _recompute_self_hash(manifest)
    for name, h in manifest["outputs"].items():
        assert _sha(out / name) == h


# ── 产物约束 ──────────────────────────────────────────────────────────

def test_exact_output_file_set(tmp_path):
    out = tmp_path / "out"
    p.run(out_dir=out)
    names = sorted(x.name for x in out.iterdir())
    assert names == sorted(p.OUTPUT_FILES)
    for name in names:
        assert "draft-after" not in name
        assert "evidence-after" not in name
        assert "overlay" not in name
        assert "active" not in name
        assert "v2.1" not in name
        assert "split" not in name.lower()


def test_manifest_declarations(tmp_path):
    out = tmp_path / "out"
    result = p.run(out_dir=out)
    manifest = result["manifest"]
    assert manifest["declarations"] == {
        "llm_called": False, "network_used": False,
        "overlay_generated": False, "data_modified": False,
        "v2_1_entered": False, "split_created": False,
        "historical_verdicts_read": False,
    }
    assert manifest["task"] == "v2.0.7-reject-semantic-quality-decision-pack"
    assert manifest["gate_verdict"] == "DECISION_PACK_OK"
    assert manifest["n_rejects"] == 22


def test_data_quality_report_five_dimensions(tmp_path):
    out = tmp_path / "out"
    p.run(out_dir=out)
    dq = json.loads((out / "data-quality-report.json").read_text(
        encoding="utf-8"))
    assert dq["skill"]["available"] is False
    assert "Skill not found" in dq["skill"]["failure"]
    for dim in ("completeness", "uniqueness", "referential_integrity",
                "continuity", "consistency"):
        assert dim in dq["equivalent_deterministic_checks"]
    checks = dq["equivalent_deterministic_checks"]
    assert checks["completeness"]["pack_rows"] == 22
    assert checks["completeness"]["candidate_rows"] >= 22
    assert checks["referential_integrity"]["candidate_chunks_in_corpus"] is True
    assert checks["continuity"]["candidates_raw_proved"] >= 22
    assert checks["consistency"]["input_shas_unchanged"] is True
    assert checks["consistency"]["distribution_exact"] is True


def test_guide_contains_vocabulary_and_no_auto_apply(tmp_path):
    out = tmp_path / "out"
    p.run(out_dir=out)
    guide = (out / "OWNER_SEMANTIC_QUALITY_DECISION_GUIDE.md").read_text(
        encoding="utf-8")
    for action in p.ACTIONS_TO_BATCHES:
        assert action in guide
    for batch in p.BATCHES:
        assert batch in guide
    assert "owner_decision" in guide
    assert "不自动应用" in guide or "不会自动" in guide
    # 凡提及“放宽 review 标准”处必须是否定语境（不提供/不得/不会）
    for line in guide.splitlines():
        if "放宽" in line:
            assert "不提供" in line or "不得" in line or "不会" in line, line


def test_report_lists_all_22_with_actions(tmp_path):
    out = tmp_path / "out"
    result = p.run(out_dir=out)
    report = (out / "decision-pack-report.md").read_text(encoding="utf-8")
    for row in result["rows"]:
        assert row["case_id"] in report
        assert row["recommended_action"] in report
        assert row["review_rationale"][:60] in report
    assert "22 条" in report
    assert "不是修复" in report or "只读" in report


# ── fail-closed 零输出 ────────────────────────────────────────────────

def test_fail_closed_zero_output(tmp_path):
    """门禁失败 → DecisionPackError 且 out_dir 不存在。"""
    tmp_triage = _tampered_triage(
        tmp_path, lambda rows: [
            dict(r, category="unresolved_requires_owner_judgment")
            if r["case_id"] == "mixed-027" else r for r in rows])
    inputs = _copy_all_inputs(tmp_path)
    inputs["triage_dir"] = tmp_triage
    out = tmp_path / "out"
    with pytest.raises(p.DecisionPackError):
        p.run(out_dir=out, **inputs)
    assert not out.exists()


def test_cli_main_fail_closed(tmp_path, monkeypatch, capsys):
    tmp_triage = _tampered_triage(
        tmp_path, lambda rows: [r for r in rows if r["case_id"] != "zh-054"])
    inputs = _copy_all_inputs(tmp_path)
    inputs["triage_dir"] = tmp_triage
    monkeypatch.setattr(p.sys, "argv", [
        "pack", "--review-dir", str(inputs["review_dir"]),
        "--candidate-dir", str(inputs["candidate_dir"]),
        "--triage-dir", str(tmp_triage), "--out-dir", str(tmp_path / "out")])
    assert p.main() == 2
    assert "failed closed" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()
