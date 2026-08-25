"""TDD tests for v2.0.8 final-blockers owner decision pack（只读、确定性）。

行为契约（fail-closed）：
- 输入仅限 v2.0.8 candidate 目录（manifest/draft-before/after/evidence-
  before/after/deferred ledger/targeted re-review）+ chunks + chunk manifest +
  raw-codepoint strict validator；不调用 LLM/API、不联网、不读取
  split/dev/holdout/锁配置/历史评测/早于 v2.0.8 的审阅结论。
- 门禁：v2.0.8 143 case、151 条 active raw evidence、strict validator
  151/151、legacy/unresolved=0；multi-030 链关系精确
  （multi-031.follow_up_to=="multi-030"、multi-032/033/034.chain_id==
  "multi-030" 且无其他引用）；multi-030 在 deferred ledger；multi-030 与
  multi-031~034 在 draft-before→after / evidence-before→after 逐字节不变；
  mixed-027 targeted re-review 确为 TARGETED_REVIEW_OK / reject /
  AP0 directly_supported / AP1 unsupported（仅作事实核验，判定依据是本地
  raw 重验，不采纳模型结论为事实）。
- 两个 blocker（multi-030、mixed-027），各恰 3 个选项，不自动选择；
  本地逐字重验：strict（连续、覆盖≥0.75）、token 片段（≥2 字符）、
  源内完整 AP 命中唯一性；候选证据必须给出 chunk/source/raw range/span/
  唯一性/重建结果，不允许语义猜测、跨 source 或模型输出替代。
- 输出 7 个文件到 final-blockers-decision-pack/；无 after/overlay/active/
  split/locked/v2.1 产物；不修改 candidate 任何既有文件；输入 SHA 不变；
  两次构建逐字节一致；manifest 自哈希一致。
"""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

import scripts.corpus_v2_v208_final_blockers_decision_pack as p

ROOT = Path(__file__).resolve().parents[1]
V208 = ROOT / "evaluation/datasets/v2/revisions/v2.0.8-owner-authorized-semantic-quality-remediation"
OUT = V208 / "final-blockers-decision-pack"
CHUNKS = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"

BLOCKERS = ("multi-030", "mixed-027")
CHAIN_CASES = ("multi-030", "multi-031", "multi-032", "multi-033", "multi-034")
DEFER_REASON = "retirement_deferred_due_to_active_follow_up_chain_dependency"
RETIRE_GROUP = "retire_entire_dependent_chain"
OPTIONS_M030 = ("repair_in_place_with_direct_exact_evidence",
                "retire_entire_dependent_chain",
                "keep_deferred_and_block_fresh_review")
OPTIONS_M027 = ("remove_unsupported_answer_point_1",
                "repair_with_direct_exact_evidence",
                "keep_deferred_and_block_fresh_review")

OUTPUT_FILES = (
    "final-blockers-decision-pack.jsonl", "owner-decision-template.jsonl",
    "chain-impact-map.json", "raw-evidence-verification.json",
    "OWNER_DECISION_GUIDE.md", "final-blockers-report.md", "manifest.json",
)
FORBIDDEN_NAMES = ("overlay", "active-", "v2.1", "v2-1", "locked",
                   "holdout", "seal", "freeze", "after", "review-result",
                   "truth-overlay")


# ── helpers ────────────────────────────────────────────────────────────

def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in open(path, encoding="utf-8")]


def _recompute_self_hash(manifest: dict) -> str:
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    return hashlib.sha256((json.dumps(body, ensure_ascii=False, indent=1,
                                      sort_keys=True) + "\n").encode("utf-8")).hexdigest()


def _copy_tree(src: Path, dst: Path) -> Path:
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return dst


def _snapshot_candidate(tmp_path: Path) -> tuple[Path, dict]:
    """拷贝 v2.0.8 candidate 到 tmp 作为可篡改输入；返回 (cand_dir, 原目录
    除 final-blockers-decision-pack 外全部文件 SHA)。"""
    cand = _copy_tree(V208, tmp_path / "cand")
    sha_map = {}
    for f in V208.rglob("*"):
        if f.is_file() and "final-blockers-decision-pack" not in f.parts:
            sha_map[str(f.relative_to(V208))] = _sha(f)
    return cand, sha_map


# ── 1. 常量守恒 ───────────────────────────────────────────────────────

def test_constants_conservation():
    assert p.BLOCKERS == BLOCKERS
    assert p.CHAIN_CASES == CHAIN_CASES
    assert set(p.OPTIONS_M030) == set(OPTIONS_M030)
    assert set(p.OPTIONS_M027) == set(OPTIONS_M027)
    assert set(p.OUTPUT_FILES) == set(OUTPUT_FILES)
    assert p.DEFER_REASON == DEFER_REASON
    assert len(BLOCKERS) == 2 and len(OPTIONS_M030) == 3 and len(OPTIONS_M027) == 3


# ── 2. 前置门禁（真实输入全部通过）───────────────────────────────────

def test_preflight_real_inputs():
    checks = p.preflight()
    assert checks["case_count"] == 143
    assert checks["evidence_count"] == 151
    assert checks["strict_covered"] == 151
    assert checks["strict_passed"] == 151
    assert checks["legacy_rows"] == 0
    assert checks["unresolved_rows"] == 0
    assert checks["gate_verdict"] == "REMEDIATION_CANDIDATE_OK"
    assert checks["deferred_ledger"] == [DEFER_REASON]
    assert checks["chain_gate"] == "CHAIN_EXACT"
    assert checks["byte_identical"] is True
    assert checks["targeted_review"] == {
        "status": "TARGETED_REVIEW_OK", "decision": "reject",
        "ap0_assessment": "directly_supported",
        "ap1_assessment": "unsupported", "model": "deepseek-v4-pro"}


def test_chain_relations_exact():
    """multi-030 链关系精确：031 follow_up_to、032/033/034 chain_id，且
    无其他 case 引用 multi-030（fail-closed 依据）。"""
    checks = p.preflight()
    deps = checks["chain_deps"]
    assert deps == {"multi-031": ["follow_up_to"],
                    "multi-032": ["chain_id"],
                    "multi-033": ["chain_id"],
                    "multi-034": ["chain_id"]}


def test_multi030_and_chain_cases_byte_identical_in_candidate():
    """multi-030 与 multi-031~034 在 v2.0.8 draft-before→after /
    evidence-before→after 逐字节不变（deferred 语义：v2.0.7→v2.0.8 未动）。"""
    checks = p.preflight()
    assert checks["byte_identical"] is True
    assert checks["byte_identical_cases"] == set(CHAIN_CASES)


# ── 3. fail-closed 漂移门禁 ───────────────────────────────────────────

def test_fail_closed_candidate_manifest_drift(tmp_path):
    cand, _ = _snapshot_candidate(tmp_path)
    m_path = cand / "manifest.json"
    m = json.load(open(m_path, encoding="utf-8"))
    m["counts"]["case_after"] = 144
    m_path.write_text(json.dumps(m, ensure_ascii=False, indent=1,
                                 sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(p.DecisionPackError):
        p.run(candidate_dir=cand, out_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_fail_closed_chain_drift(tmp_path):
    cand, _ = _snapshot_candidate(tmp_path)
    path = cand / "draft-after.jsonl"
    rows = _jsonl(path)
    next(r for r in rows if r["id"] == "multi-031")["metadata"]["follow_up_to"] = None
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")) + "\n"
                            for r in rows), encoding="utf-8")
    with pytest.raises(p.DecisionPackError) as exc:
        p.run(candidate_dir=cand, out_dir=tmp_path / "out")
    assert "multi-030" in str(exc.value)
    assert not (tmp_path / "out").exists()


def test_fail_closed_deferred_ledger_drift(tmp_path):
    cand, _ = _snapshot_candidate(tmp_path)
    path = cand / "deferred-chain-dependent-cases.jsonl"
    rows = _jsonl(path)
    rows[0]["deferred_reason"] = "something_else"
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")) + "\n"
                            for r in rows), encoding="utf-8")
    with pytest.raises(p.DecisionPackError):
        p.run(candidate_dir=cand, out_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_fail_closed_targeted_review_status_drift(tmp_path):
    cand, _ = _snapshot_candidate(tmp_path)
    path = cand / "targeted-re-review" / "review-status.json"
    st = json.load(open(path, encoding="utf-8"))
    st["status"] = "TARGETED_REVIEW_BLOCKED"
    path.write_text(json.dumps(st, ensure_ascii=False, indent=1,
                               sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(p.DecisionPackError):
        p.run(candidate_dir=cand, out_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_fail_closed_targeted_review_result_drift(tmp_path):
    cand, _ = _snapshot_candidate(tmp_path)
    path = cand / "targeted-re-review" / "targeted-review-result.json"
    r = json.load(open(path, encoding="utf-8"))
    r["result"]["decision"] = "confirmed"
    path.write_text(json.dumps(r, ensure_ascii=False, indent=1,
                               sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(p.DecisionPackError):
        p.run(candidate_dir=cand, out_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_fail_closed_evidence_drift(tmp_path):
    cand, _ = _snapshot_candidate(tmp_path)
    path = cand / "evidence-after.jsonl"
    rows = _jsonl(path)
    rows.pop()
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")) + "\n"
                            for r in rows), encoding="utf-8")
    with pytest.raises(p.DecisionPackError):
        p.run(candidate_dir=cand, out_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()


# ── 4. multi-030 选项判定（本地逐字，不自动选择）────────────────────

@pytest.fixture(scope="module")
def built(tmp_path_factory):
    base = tmp_path_factory.mktemp("fb")
    out = base / "out"
    result = p.run(out_dir=out)
    return out, result


def test_multi030_options(built):
    out, _ = built
    rows = {r["case_id"]: r for r in
            _jsonl(out / "final-blockers-decision-pack.jsonl")}
    row = rows["multi-030"]
    assert row["blocker_type"] == "deferred_chain_parent"
    opts = {o["option"]: o for o in row["options"]}
    assert set(opts) == set(OPTIONS_M030)
    # repair：无唯一、连续、直接支撑（完整 AP 无逐字命中；最长子串不唯一）
    repair = opts["repair_in_place_with_direct_exact_evidence"]
    assert repair["meets_criteria"] is False
    crit = repair["criteria"]
    assert crit["full_ap_verbatim_hits_in_source"] == 0
    assert crit["longest_substring_unique"] is False
    assert crit["longest_substring_text"] == "把 Python 当作计算器"
    assert crit["longest_substring_occurrences"] == 2
    # retire：影响恰 5 条 case（不可拆分组）
    retire = opts["retire_entire_dependent_chain"]
    assert retire["meets_criteria"] is True
    impact = retire["impact"]
    assert set(impact["case_ids"]) == set(CHAIN_CASES)
    for cid in CHAIN_CASES:
        assert impact["cases"][cid]["n_answer_points"] == 1
        assert impact["cases"][cid]["n_evidence"] == 1
    # keep：现状
    keep = opts["keep_deferred_and_block_fresh_review"]
    assert keep["meets_criteria"] is True
    assert row["recommendation"] is None
    assert row["owner_decision_required"] is True


def test_chain_impact_map(built):
    out, _ = built
    m = json.load(open(out / "chain-impact-map.json", encoding="utf-8"))
    assert set(m["case_ids"]) == set(CHAIN_CASES)
    edges = {(e["from"], e["to"], e["relation"]) for e in m["edges"]}
    assert ("multi-030", "multi-031", "follow_up_to") in edges
    assert ("multi-030", "multi-032", "chain_id") in edges
    assert ("multi-030", "multi-033", "chain_id") in edges
    assert ("multi-030", "multi-034", "chain_id") in edges
    assert ("multi-032", "multi-033", "follow_up_to") in edges
    assert ("multi-033", "multi-034", "follow_up_to") in edges
    # 上游 multi-028 的 chain 成员缺失影响必须列出
    assert "multi-028" in m["upstream_impact"]
    assert set(m["upstream_impact"]["multi-028"]["lost_chain_members"]) == \
        {"multi-030", "multi-031"}
    for cid in CHAIN_CASES:
        assert m["cases"][cid]["n_evidence"] == 1
        assert m["cases"][cid]["doc_target"]


# ── 5. mixed-027 选项判定 ────────────────────────────────────────────

def test_mixed027_options(built):
    out, _ = built
    rows = {r["case_id"]: r for r in
            _jsonl(out / "final-blockers-decision-pack.jsonl")}
    row = rows["mixed-027"]
    assert row["blocker_type"] == "targeted_re_review_reject"
    opts = {o["option"]: o for o in row["options"]}
    assert set(opts) == set(OPTIONS_M027)
    # remove AP1：AP0 无 strict 连续逐字支撑（token 级片段存在）→ 条件不满足
    remove = opts["remove_unsupported_answer_point_1"]
    assert remove["meets_criteria"] is False
    crit = remove["criteria"]
    assert crit["ap0_strict_contiguous_support"] is False
    assert crit["ap0_token_level_fragments"] is True
    assert crit["non_zero_answer_points_after"] is True
    assert crit["ap0_max_contiguous_coverage"] < 0.75
    # repair：AP1 无唯一完整逐字证据（仅 begin-stmt token）
    repair = opts["repair_with_direct_exact_evidence"]
    assert repair["meets_criteria"] is False
    assert repair["criteria"]["full_ap_verbatim_hits_in_source"] == 0
    # keep：现状
    keep = opts["keep_deferred_and_block_fresh_review"]
    assert keep["meets_criteria"] is True
    assert row["recommendation"] is None


def test_raw_evidence_verification(built):
    """本地逐字重验细节：strict 命中、token 段、源内完整命中、重建。"""
    out, _ = built
    v = json.load(open(out / "raw-evidence-verification.json", encoding="utf-8"))
    chunks = {c["chunk_id"]: c for c in _jsonl(CHUNKS)}
    for case_id in BLOCKERS:
        for ap in v[case_id]["answer_points"]:
            idx = ap["answer_point_index"]
            for ev in ap["evidence_checks"]:
                cid = ev["chunk_id"]
                s, e = ev["raw_chunk_char_range"]["start"], ev["raw_chunk_char_range"]["end"]
                assert chunks[cid]["text"][s:e] == ev["raw_evidence_span"]  # 重建
                assert ev["source_id"] == chunks[cid]["source"]
    m030 = v["multi-030"]["answer_points"][0]
    assert m030["answer_point"] == "数字（把 Python 当作计算器）"
    assert m030["evidence_checks"][0]["strict_in_span_coverage"] > 0.75
    assert m030["source_wide"]["full_ap_hits"] == 0
    assert m030["source_wide"]["longest_substring_occurrences"] == 2
    m027 = v["mixed-027"]["answer_points"]
    ap0 = m027[0]
    # evidence-after 按 chunk_id 排序，按 chunk 定位真正支撑 AP0 的 glossary 行
    ap0_glossary = next(c for c in ap0["evidence_checks"]
                        if c["chunk_id"] == "c9fd20815ea8_chunk_2")
    assert ap0_glossary["strict_in_span_coverage"] == 0.0
    assert ap0_glossary["token_fragments"]  # 原子化操作/不可再分
    ap1 = m027[1]
    ap1_sqlite = next(c for c in ap1["evidence_checks"]
                      if c["chunk_id"] == "8b191b241b93_chunk_1")
    assert ap1_sqlite["strict_in_span_hits"]  # begin-stmt
    assert ap1["source_wide"]["full_ap_hits"] == 0


# ── 6. 输出与模板 ────────────────────────────────────────────────────

def test_output_file_set(built):
    out, _ = built
    assert set(f.name for f in out.iterdir()) == set(OUTPUT_FILES)


def test_decision_pack_two_rows(built):
    out, _ = built
    rows = _jsonl(out / "final-blockers-decision-pack.jsonl")
    assert len(rows) == 2
    assert {r["case_id"] for r in rows} == set(BLOCKERS)


def test_owner_decision_template(built):
    out, _ = built
    rows = _jsonl(out / "owner-decision-template.jsonl")
    assert len(rows) == 2
    assert {r["case_id"] for r in rows} == set(BLOCKERS)
    for r in rows:
        assert sorted(r.keys()) == sorted(
            ["case_id", "owner_decision", "owner_reviewer", "owner_notes"])
        assert r["owner_decision"] == "" and r["owner_reviewer"] == "" \
            and r["owner_notes"] == ""


def test_candidate_files_unchanged(tmp_path):
    """构建后 candidate 既有文件（除本 pack 外）SHA 逐字节不变。"""
    sha_map = {}
    for f in V208.rglob("*"):
        if f.is_file() and "final-blockers-decision-pack" not in f.parts:
            sha_map[str(f.relative_to(V208))] = _sha(f)
    p.run(out_dir=tmp_path / "out")
    for rel, sha in sha_map.items():
        assert _sha(V208 / rel) == sha, rel


def test_no_forbidden_outputs(built):
    out, _ = built
    for f in out.rglob("*"):
        if f.is_file():
            low = f.name.lower()
            assert not any(bad in low for bad in FORBIDDEN_NAMES), f.name
    m = json.load(open(out / "manifest.json", encoding="utf-8"))
    assert m["declarations"]["llm_called"] is False
    assert m["declarations"]["network_used"] is False
    assert m["declarations"]["overlay_generated"] is False
    assert m["declarations"]["v2_1_entered"] is False
    assert m["declarations"]["recommendation_made"] is False
    assert m["declarations"]["model_output_used_as_fact"] is False


def test_manifest_self_hash_and_outputs(built):
    out, _ = built
    m = json.load(open(out / "manifest.json", encoding="utf-8"))
    assert m["manifest_sha256"] == _recompute_self_hash(m)
    for name, sha in m["outputs"].items():
        assert _sha(out / name) == sha, name
    assert m["gate_verdict"] == "FINAL_BLOCKERS_DECISION_PACK_OK"
    assert m["deterministic"] is True


def test_inputs_sha_unchanged(built):
    inputs = [V208 / "manifest.json", V208 / "draft-after.jsonl",
              V208 / "evidence-after.jsonl",
              V208 / "deferred-chain-dependent-cases.jsonl",
              V208 / "targeted-re-review" / "review-status.json",
              V208 / "targeted-re-review" / "targeted-review-result.json",
              CHUNKS, CHUNK_MANIFEST, CURRENT_DRAFT]
    for path in inputs:
        assert _sha(path) == _sha(path)


def test_two_runs_byte_identical(tmp_path):
    p.run(out_dir=tmp_path / "o1")
    p.run(out_dir=tmp_path / "o2")
    for name in OUTPUT_FILES:
        assert _sha(tmp_path / "o1" / name) == _sha(tmp_path / "o2" / name), name


def test_guide_and_report_files(built):
    out, _ = built
    guide = (out / "OWNER_DECISION_GUIDE.md").read_text(encoding="utf-8")
    assert "multi-030" in guide and "mixed-027" in guide
    for opt in OPTIONS_M030 + OPTIONS_M027:
        assert opt in guide
    assert "不自动选择" in guide or "不自行采纳" in guide
    report = (out / "final-blockers-report.md").read_text(encoding="utf-8")
    assert "multi-030" in report and "mixed-027" in report
    assert DEFER_REASON in report


def test_no_llm_and_read_only_declared(built):
    _, result = built
    m = result["manifest"]
    assert m["declarations"]["llm_called"] is False
    assert m["declarations"]["data_modified"] == "none"
    assert m["declarations"]["input_scope"] == \
        ["v2.0.8 candidate dir", "chunks", "chunk manifest",
         "raw-codepoint strict validator"]


# ── 7. CLI ────────────────────────────────────────────────────────────

def test_cli_build_success(tmp_path):
    assert p.main(["build", "--out-dir", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "manifest.json").exists()


def test_cli_unknown_command_exit_2():
    assert p.main(["frobnicate"]) == 2


def test_cli_fail_closed_exit_2(tmp_path):
    cand, _ = _snapshot_candidate(tmp_path)
    rc = p.main(["build", "--out-dir", str(tmp_path / "out"),
                 "--candidate-dir", str(cand / "nonexistent")])
    assert rc == 2
    assert not (tmp_path / "out").exists()
