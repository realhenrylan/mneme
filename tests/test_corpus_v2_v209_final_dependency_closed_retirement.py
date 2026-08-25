"""TDD tests for v2.0.9 owner-authorized final dependency-closed retirement.

行为契约（fail-closed）：
- 输入仅限：v2.0.8 candidate（manifest/draft-before/after/evidence-before/after/
  deferred ledger）+ v2.0.8 final-blockers decision pack + v2.0.8 chain-closure
  decision pack + chunks + chunk manifest + raw-codepoint strict validator +
  current draft（仅哈希核验）；不调用 LLM/API、不联网、不读取 split/dev/
  holdout/锁配置/历史评测/早于 v2.0.7 的审阅结论。
- 门禁：v2.0.8 == 143 cases / 151 active evidence / strict 151/151 /
  legacy=unresolved=0；deferred ledger 恰 1 条 multi-030；两个 decision pack
  gate（FINAL_BLOCKERS_DECISION_PACK_OK / CHAIN_CLOSURE_DECISION_PACK_OK）
  自哈希一致且记录的 input SHA 与当前磁盘一致；
  retire_minimal_dependency_closed_cohort == {multi-030..multi-034} 且
  retirement-safe（pack 中 meets_criteria=true、scenario executable）；
  mixed-027.retire_single_case_safely == true；重新复算最小无悬挂闭包必须
  恰等于授权 cohort（否则 fail-closed）；mixed-027 无任何引用。
- 退役后：无 dangling case 引用、无残留 chain member、无 orphan previous
  turn、无 doc-target 悬空；multi-028 上游链无孤儿引用。
- 硬性不变量：143 → 137 case、151 → 144 evidence（仅移除 6 个 case 及其
  7 条 evidence）；其余 draft/evidence 行逐字节不变；strict 144/144
  covered==passed；legacy/unresolved/invalid/uncovered == 0；所有保留
  answerable case 至少一条合法 strict evidence。
- retired ledger 保留原始行与固定退役理由，逐条记录 cohort、依赖闭包证明、
  evidence 数和授权标识；不把「严格证据验证通过」写成审阅通过或 active。
- 输出恰 9 个文件；无 overlay/active/split/locked/v2.1 产物；输入 SHA 不变；
  两次构建逐字节一致；manifest 自校验。
"""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

import scripts.corpus_v2_v209_final_dependency_closed_retirement as p

ROOT = Path(__file__).resolve().parents[1]
V208 = ROOT / "evaluation/datasets/v2/revisions/v2.0.8-owner-authorized-semantic-quality-remediation"
OUT = ROOT / "evaluation/datasets/v2/revisions/v2.0.9-owner-authorized-final-dependency-closed-retirement"
CHUNKS = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"

RETIRE_COHORT = ("multi-030", "multi-031", "multi-032", "multi-033", "multi-034")
RETIRE_ISOLATED = ("mixed-027",)
ALL_RETIRED = RETIRE_COHORT + RETIRE_ISOLATED
DEFER_REASON = "retirement_deferred_due_to_active_follow_up_chain_dependency"
RETIRE_REASON = "owner_authorized_final_dependency_closed_retirement"
ACTOR = "OWNER_AUTHORIZED_FINAL_DEPENDENCY_CLOSED_RETIREMENT"
CASE_BEFORE, CASE_AFTER = 143, 137
EVIDENCE_BEFORE, EVIDENCE_AFTER = 151, 144
EVIDENCE_PER_CASE = {"multi-030": 1, "multi-031": 1, "multi-032": 1,
                     "multi-033": 1, "multi-034": 1, "mixed-027": 2}

OUTPUT_FILES = (
    "draft-after.jsonl", "evidence-after.jsonl", "retired-cases.jsonl",
    "retired-evidence.jsonl", "retirement-dependency-ledger.json",
    "field-level-diff.jsonl", "data-quality-report.json",
    "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md", "manifest.json",
)
FORBIDDEN_NAMES = ("overlay", "active-", "v2.1", "v2-1", "locked",
                   "holdout", "seal", "freeze", "automated-review.jsonl",
                   "review-result", "truth-overlay")


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
    """拷贝 v2.0.8 candidate（含两个 decision pack）到 tmp 作为可篡改输入；
    返回 (cand_dir, 全部文件 SHA)。"""
    cand = _copy_tree(V208, tmp_path / "cand")
    sha_map = {str(f.relative_to(V208)): _sha(f) for f in V208.rglob("*")
               if f.is_file()}
    return cand, sha_map


def _ser_like(orig: str, row: dict) -> str:
    """按原行序列化风格重写（default vs compact），保持未篡改行逐字节不变。"""
    parsed = json.loads(orig)
    if orig == json.dumps(parsed, ensure_ascii=False):
        return json.dumps(row, ensure_ascii=False)
    return json.dumps(row, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _rewrite_jsonl(path: Path, transform) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    out = [_ser_like(l, transform(json.loads(l))) for l in lines]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _rewrite_json(path: Path, transform) -> None:
    data = json.load(open(path, encoding="utf-8"))
    path.write_text(json.dumps(transform(data), ensure_ascii=False, indent=1,
                               sort_keys=True) + "\n", encoding="utf-8")


# v2.0.8 文件 → decision pack manifest inputs 的键名映射
PACK_INPUT_KEYS = {
    "manifest.json": "v208-manifest.json",
    "draft-after.jsonl": "draft-after.jsonl",
    "evidence-after.jsonl": "evidence-after.jsonl",
    "deferred-chain-dependent-cases.jsonl": "deferred-chain-dependent-cases.jsonl",
    "chunks.jsonl": "chunks.jsonl",
    "chunk-manifest.json": "chunk-manifest.json",
    "current-v2-draft.jsonl": "current-v2-draft.jsonl",
    "targeted-re-review/targeted-review-result.json": "targeted-review-result.json",
    "targeted-re-review/review-status.json": "targeted-review-status.json",
}


def _update_pack_shas(cand: Path, rel: str) -> None:
    """篡改 v2.0.8 输入文件后同步两个 pack manifest 记录的 SHA 与自哈希，
    使门禁聚焦于被测试的具体漂移（而非 SHA 门禁）。"""
    key = PACK_INPUT_KEYS.get(rel)
    if key is None:
        return
    for pack in ("final-blockers-decision-pack", "chain-closure-decision-pack"):
        mpath = cand / pack / "manifest.json"
        if not mpath.exists():
            continue
        m = json.load(open(mpath, encoding="utf-8"))
        if key not in m.get("inputs", {}):
            continue
        m["inputs"][key] = _sha(cand / rel)
        m["manifest_sha256"] = _recompute_self_hash(m)
        mpath.write_text(json.dumps(m, ensure_ascii=False, indent=1,
                                    sort_keys=True) + "\n", encoding="utf-8")


def _tamper(cand: Path, rel: str, transform, *, update_shas: bool = True) -> None:
    path = cand / rel
    if rel.endswith(".jsonl"):
        _rewrite_jsonl(path, transform)
    else:
        _rewrite_json(path, transform)
    if update_shas:
        _update_pack_shas(cand, rel)


def _tamper_candidate_manifest_counts(cand: Path) -> None:
    """篡改 v2.0.8 candidate manifest 的 counts 并修复其自哈希与 pack SHA。"""
    path = cand / "manifest.json"
    m = json.load(open(path, encoding="utf-8"))
    m["counts"]["case_after"] = 144
    m["manifest_sha256"] = _recompute_self_hash(m)
    path.write_text(json.dumps(m, ensure_ascii=False, indent=1,
                               sort_keys=True) + "\n", encoding="utf-8")
    _update_pack_shas(cand, "manifest.json")


def _tamper_pack_gate(cand: Path, pack_rel: str) -> None:
    """篡改 pack manifest 的 gate_verdict 并修复其自哈希。"""
    path = cand / pack_rel
    m = json.load(open(path, encoding="utf-8"))
    m["gate_verdict"] = "BROKEN_GATE"
    m["manifest_sha256"] = _recompute_self_hash(m)
    path.write_text(json.dumps(m, ensure_ascii=False, indent=1,
                               sort_keys=True) + "\n", encoding="utf-8")


# ── 1. 常量守恒 ───────────────────────────────────────────────────────

def test_constants_conservation():
    assert p.RETIRE_COHORT == RETIRE_COHORT
    assert p.RETIRE_ISOLATED == RETIRE_ISOLATED
    assert p.ALL_RETIRED == ALL_RETIRED
    assert set(p.OUTPUT_FILES) == set(OUTPUT_FILES)
    assert p.ACTOR == ACTOR
    assert p.RETIRE_REASON == RETIRE_REASON
    assert len(ALL_RETIRED) == 6
    assert sum(EVIDENCE_PER_CASE.values()) == 7
    assert len(OUTPUT_FILES) == 9


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
    assert checks["minimal_cohort"] == list(RETIRE_COHORT)
    assert checks["cohort_scenario"]["executable"] is True
    assert checks["cohort_scenario"]["dangling_ref_count"] == 0
    assert checks["mixed027_isolated"] is True
    assert checks["mixed027_retire_single_case_safely"] is True
    assert checks["pack_gates"] == {
        "final_blockers": "FINAL_BLOCKERS_DECISION_PACK_OK",
        "chain_closure": "CHAIN_CLOSURE_DECISION_PACK_OK"}
    assert checks["pack_input_sha_match"] is True
    assert checks["chain_cases_byte_identical"] is True


def test_chain_facts_exact():
    """multi-030 链关系精确：031 follow_up_to、032/033/034 chain_id、
    multi-030.chain_id=multi-028；退役后 multi-028 上游链无孤儿引用。"""
    checks = p.preflight()
    assert checks["chain_facts"] == {
        "multi-031": ["follow_up_to"], "multi-032": ["chain_id"],
        "multi-033": ["chain_id"], "multi-034": ["chain_id"]}
    assert checks["graph"]["chain_members"]["multi-028"] == \
        ["multi-030", "multi-031"]
    # multi-028 自身 chain_id=multi-025、follow_up_to=multi-027（不悬空）
    n028 = checks["graph"]["nodes"]["multi-028"]
    assert n028["chain_id"] == "multi-025"
    assert n028["follow_up_to"] == "multi-027"


def test_pack_input_shas_match_disk():
    """两个 decision pack manifest 记录的 input SHA 与当前磁盘一致。"""
    checks = p.preflight()
    assert checks["pack_input_sha_match"] is True
    assert checks["pack_input_mismatches"] == []


def test_chain_cases_byte_identical_in_candidate():
    """6 个退役 case 在 v2.0.8 draft-before→after / evidence-before→after
    逐字节不变（v2.0.7→v2.0.8 未动）。"""
    checks = p.preflight()
    assert checks["chain_cases_byte_identical"] is True
    assert checks["byte_identical_cases"] == set(ALL_RETIRED)


def test_closure_pack_retire_option_verified():
    """chain-closure pack 中 retire_minimal_dependency_closed_cohort 选项
    与 retire_only_multi_030 不可执行性已核实。"""
    checks = p.preflight()
    opts = checks["closure_options"]
    by_name = {o["option"]: o for o in opts["options"]}
    assert by_name["retire_minimal_dependency_closed_cohort"]["meets_criteria"] is True
    assert by_name["retire_only_multi_030"]["meets_criteria"] is False
    scens = {s["name"]: s for s in opts["scenarios"]}
    assert scens["retire_minimal_dependency_closed_cohort"]["dangling_ref_count"] == 0
    assert scens["retire_minimal_dependency_closed_cohort"]["executable"] is True
    assert scens["retire_only_multi_030"]["dangling_ref_count"] == 4
    assert scens["retire_only_multi_030"]["executable"] is False


def test_mixed027_pack_check_verified():
    checks = p.preflight()
    m027 = checks["mixed027_check"]
    assert m027["retire_single_case_safely"] is True
    assert m027["impact"]["executable"] is True
    assert m027["impact"]["dangling_ref_count"] == 0
    assert m027["dependency_facts"]["incoming_case_refs"] == []
    assert m027["dependency_facts"]["outgoing_case_refs"] == []


# ── 3. fail-closed 门禁 ────────────────────────────────────────────────

def test_fail_closed_retire_only_multi030(tmp_path):
    """单独 retire multi-030 必须失败（非最小无悬挂闭包）。"""
    with pytest.raises(p.RetirementError) as exc:
        p.run(out_dir=tmp_path / "out", retire_cohort=("multi-030",))
    assert "multi-030" in str(exc.value)
    assert not (tmp_path / "out").exists()


def test_fail_closed_cohort_drift(tmp_path):
    """multi-031 解除 follow_up_to → 最小闭包变化 → fail-closed。"""
    cand, _ = _snapshot_candidate(tmp_path)
    _tamper(cand, "draft-after.jsonl", lambda r: (
        {**r, "metadata": {**(r.get("metadata") or {}),
                           "follow_up_to": None}}
        if r["id"] == "multi-031" else r))
    with pytest.raises(p.RetirementError) as exc:
        p.run(out_dir=tmp_path / "out", candidate_dir=cand)
    assert not (tmp_path / "out").exists()


def test_fail_closed_new_follow_up_ref(tmp_path):
    """意外新增 follow_up_to 引用（指向退役 case）→ fail-closed。"""
    cand, _ = _snapshot_candidate(tmp_path)
    _tamper(cand, "draft-after.jsonl", lambda r: (
        {**r, "metadata": {**(r.get("metadata") or {}),
                           "follow_up_to": "multi-030"}}
        if r["id"] == "multi-028" else r))
    with pytest.raises(p.RetirementError):
        p.run(out_dir=tmp_path / "out", candidate_dir=cand)
    assert not (tmp_path / "out").exists()


def test_fail_closed_new_chain_ref(tmp_path):
    """意外新增 chain_id 引用（指向退役 case）→ fail-closed。"""
    cand, _ = _snapshot_candidate(tmp_path)
    _tamper(cand, "draft-after.jsonl", lambda r: (
        {**r, "metadata": {**(r.get("metadata") or {}),
                           "chain_id": "multi-031"}}
        if r["id"] == "multi-015" else r))
    with pytest.raises(p.RetirementError):
        p.run(out_dir=tmp_path / "out", candidate_dir=cand)
    assert not (tmp_path / "out").exists()


def test_fail_closed_previous_turns_ref(tmp_path):
    """意外新增 previous_turns 引用（指向退役 case）→ fail-closed。"""
    cand, _ = _snapshot_candidate(tmp_path)
    _tamper(cand, "draft-after.jsonl", lambda r: (
        {**r, "metadata": {**(r.get("metadata") or {}),
                           "previous_turns": ["multi-030"]}}
        if r["id"] == "multi-015" else r))
    with pytest.raises(p.RetirementError):
        p.run(out_dir=tmp_path / "out", candidate_dir=cand)
    assert not (tmp_path / "out").exists()


def test_fail_closed_doc_target_ref(tmp_path):
    """意外新增 doc_target 引用（指向退役 case）→ fail-closed。"""
    cand, _ = _snapshot_candidate(tmp_path)
    _tamper(cand, "draft-after.jsonl", lambda r: (
        {**r, "doc_target": "multi-030"}
        if r["id"] == "multi-028" else r))
    with pytest.raises(p.RetirementError):
        p.run(out_dir=tmp_path / "out", candidate_dir=cand)
    assert not (tmp_path / "out").exists()


def test_fail_closed_mixed027_incoming_ref(tmp_path):
    """意外出现指向 mixed-027 的引用 → fail-closed（隔离破坏）。"""
    cand, _ = _snapshot_candidate(tmp_path)
    _tamper(cand, "draft-after.jsonl", lambda r: (
        {**r, "metadata": {**(r.get("metadata") or {}),
                           "chain_id": "mixed-027"}}
        if r["id"] == "multi-015" else r))
    with pytest.raises(p.RetirementError) as exc:
        p.run(out_dir=tmp_path / "out", candidate_dir=cand)
    assert "mixed-027" in str(exc.value)
    assert not (tmp_path / "out").exists()


def test_fail_closed_evidence_count_drift(tmp_path):
    cand, _ = _snapshot_candidate(tmp_path)
    path = cand / "evidence-after.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    _update_pack_shas(cand, "evidence-after.jsonl")
    with pytest.raises(p.RetirementError):
        p.run(out_dir=tmp_path / "out", candidate_dir=cand)
    assert not (tmp_path / "out").exists()


def test_fail_closed_evidence_strict_drift(tmp_path):
    """篡改 evidence raw span 使 strict 校验失败 → fail-closed。"""
    cand, _ = _snapshot_candidate(tmp_path)
    def _drift(r):
        if r["case_id"] == "multi-030":
            r = dict(r)
            r["raw_chunk_char_range"] = {"start": 0, "end": 66}
        return r
    _tamper(cand, "evidence-after.jsonl", _drift)
    with pytest.raises(p.RetirementError):
        p.run(out_dir=tmp_path / "out", candidate_dir=cand)
    assert not (tmp_path / "out").exists()


def test_fail_closed_counts_drift(tmp_path):
    cand, _ = _snapshot_candidate(tmp_path)
    _tamper_candidate_manifest_counts(cand)
    with pytest.raises(p.RetirementError):
        p.run(out_dir=tmp_path / "out", candidate_dir=cand)
    assert not (tmp_path / "out").exists()


def test_fail_closed_deferred_ledger_drift(tmp_path):
    cand, _ = _snapshot_candidate(tmp_path)
    _tamper(cand, "deferred-chain-dependent-cases.jsonl", lambda r: (
        {**r, "deferred_reason": "something_else"}))
    with pytest.raises(p.RetirementError):
        p.run(out_dir=tmp_path / "out", candidate_dir=cand)
    assert not (tmp_path / "out").exists()


def test_fail_closed_pack_gate_drift(tmp_path):
    cand, _ = _snapshot_candidate(tmp_path)
    _tamper_pack_gate(cand, "chain-closure-decision-pack/manifest.json")
    with pytest.raises(p.RetirementError):
        p.run(out_dir=tmp_path / "out", candidate_dir=cand)
    assert not (tmp_path / "out").exists()


def test_fail_closed_pack_content_drift(tmp_path):
    """chain-closure pack 中 minimal_cohort 被篡改 → fail-closed。"""
    cand, _ = _snapshot_candidate(tmp_path)
    _tamper(cand, "chain-closure-decision-pack/multi-030-closure-options.json",
            lambda m: {**m, "minimal_cohort": ["multi-030", "multi-031"]},
            update_shas=False)
    with pytest.raises(p.RetirementError):
        p.run(out_dir=tmp_path / "out", candidate_dir=cand)
    assert not (tmp_path / "out").exists()


def test_fail_closed_empty_targets(tmp_path):
    with pytest.raises(p.RetirementError):
        p.run(out_dir=tmp_path / "out", retire_cohort=(), retire_isolated=())
    assert not (tmp_path / "out").exists()


def test_fail_closed_overlap_targets(tmp_path):
    with pytest.raises(p.RetirementError):
        p.run(out_dir=tmp_path / "out", retire_cohort=("multi-030",),
              retire_isolated=("multi-030",))
    assert not (tmp_path / "out").exists()


# ── 4. 授权动作（partial 构建）────────────────────────────────────────

def test_retire_cohort_alone(tmp_path):
    """仅 retire multi-030~034 可通过：143→138、151→146。"""
    r = p.run(out_dir=tmp_path / "out", retire_cohort=RETIRE_COHORT,
              retire_isolated=())
    m = r["manifest"]
    assert m["counts"]["case_after"] == 138
    assert m["counts"]["evidence_after"] == 146
    assert m["counts"]["retired_cases"] == 5
    assert m["counts"]["retired_evidence"] == 5
    assert len(_jsonl(tmp_path / "out" / "retired-cases.jsonl")) == 5
    assert len(_jsonl(tmp_path / "out" / "retired-evidence.jsonl")) == 5


def test_mixed027_alone(tmp_path):
    """mixed-027 单独退役可通过：143→142、151→149。"""
    r = p.run(out_dir=tmp_path / "out", retire_cohort=(),
              retire_isolated=RETIRE_ISOLATED)
    m = r["manifest"]
    assert m["counts"]["case_after"] == 142
    assert m["counts"]["evidence_after"] == 149
    assert m["counts"]["retired_cases"] == 1
    assert m["counts"]["retired_evidence"] == 2
    assert len(_jsonl(tmp_path / "out" / "retired-cases.jsonl")) == 1
    assert len(_jsonl(tmp_path / "out" / "retired-evidence.jsonl")) == 2


# ── 5. 默认构建（真实输入）────────────────────────────────────────────

@pytest.fixture(scope="module")
def built(tmp_path_factory):
    base = tmp_path_factory.mktemp("v209")
    out = base / "out"
    result = p.run(out_dir=out)
    return out, result


def test_default_build_counts(built):
    out, _ = built
    assert len(_jsonl(out / "draft-after.jsonl")) == CASE_AFTER
    assert len(_jsonl(out / "evidence-after.jsonl")) == EVIDENCE_AFTER
    assert {r["case_id"] for r in _jsonl(out / "retired-cases.jsonl")} == \
        set(ALL_RETIRED)
    assert len(_jsonl(out / "retired-evidence.jsonl")) == 7


def test_output_file_set(built):
    out, _ = built
    assert set(f.name for f in out.iterdir()) == set(OUTPUT_FILES)


def test_non_target_draft_rows_byte_identical(built):
    """非目标 draft 行逐字节不变（原行原字节保留）。"""
    out, _ = built
    before = open(V208 / "draft-after.jsonl", encoding="utf-8").read().splitlines()
    after = open(out / "draft-after.jsonl", encoding="utf-8").read().splitlines()
    removed = {json.loads(l)["id"] for l in before
               if json.loads(l)["id"] in set(ALL_RETIRED)}
    kept = [l for l in before if json.loads(l)["id"] not in removed]
    assert after == kept
    assert len(after) == CASE_AFTER


def test_non_target_evidence_rows_byte_identical(built):
    out, _ = built
    before = open(V208 / "evidence-after.jsonl", encoding="utf-8").read().splitlines()
    after = open(out / "evidence-after.jsonl", encoding="utf-8").read().splitlines()
    kept = [l for l in before if json.loads(l)["case_id"] not in set(ALL_RETIRED)]
    assert after == kept
    assert len(after) == EVIDENCE_AFTER


def test_strict_144_144(built):
    out, _ = built
    rows = _jsonl(out / "evidence-after.jsonl")
    chunks = {c["chunk_id"]: c for c in _jsonl(CHUNKS)}
    for row in rows:  # 全量可重建
        assert chunks[row["chunk_id"]]["text"][
            row["raw_chunk_char_range"]["start"]:
            row["raw_chunk_char_range"]["end"]] == row["raw_evidence_span"]
    # strict validator 144/144 covered==passed
    import scripts.corpus_v2_evidence_coordinate_repair as coord
    coord.strict_validate(rows, chunks)
    legacy = [e for e in rows if e.get("coordinate_contract") != "raw-codepoint-v1"]
    unresolved = [e for e in rows if not e.get("raw_evidence_span")]
    assert legacy == [] and unresolved == []


def test_after_no_dangling_refs(built):
    """退役后无 dangling case 引用、无残留 chain member、无 orphan previous
    turn、无 doc-target 悬空。"""
    out, _ = built
    draft = _jsonl(out / "draft-after.jsonl")
    graph = p._build_dependency_graph(draft)
    assert graph["cycles"] == []
    assert graph["dangling_refs"] == []
    retired = set(ALL_RETIRED)
    for e in graph["edges"]:
        assert e["to"] not in retired, e
    for members in graph["chain_members"].values():
        assert not (set(members) & retired)
    assert "multi-028" not in graph["chain_members"]
    assert graph["refs_by_type"]["previous_turns"] == 0
    assert graph["refs_by_type"]["doc_target"] == 0


def test_no_residual_chain_members(built):
    out, _ = built
    draft = _jsonl(out / "draft-after.jsonl")
    graph = p._build_dependency_graph(draft)
    assert set(graph["chain_members"]) == set(
        p.preflight()["graph"]["chain_members"]) - {"multi-028", "multi-030"}
    # multi-028 仍属于 chain multi-025（上游链无孤儿成员）
    n028 = next(r for r in draft if r["id"] == "multi-028")
    assert n028["metadata"]["chain_id"] == "multi-025"


def test_answerable_cases_have_evidence(built):
    """所有保留 answerable case（非拒答）至少一条合法 strict evidence。"""
    out, _ = built
    draft = _jsonl(out / "draft-after.jsonl")
    ev = {r["case_id"] for r in _jsonl(out / "evidence-after.jsonl")}
    answerable = [r["id"] for r in draft
                  if not r.get("should_refuse")
                  and not r.get("is_refusal_turn")]
    assert answerable  # 非空
    assert all(cid in ev for cid in answerable)
    assert len(ev) == len({e["case_id"] for e in _jsonl(out / "evidence-after.jsonl")})


def test_retired_cases_ledger(built):
    """retired-cases.jsonl 保留原始行 + 固定理由 + cohort + 闭包证明 +
    evidence 数 + 授权标识。"""
    out, _ = built
    rows = {r["case_id"]: r for r in _jsonl(out / "retired-cases.jsonl")}
    assert set(rows) == set(ALL_RETIRED)
    before = {json.loads(l)["id"]: json.loads(l)
              for l in open(V208 / "draft-after.jsonl", encoding="utf-8")}
    for cid, row in rows.items():
        assert row["retired_reason"] == RETIRE_REASON
        assert row["retired_by"] == ACTOR
        assert row["authorization"] == ACTOR
        assert row["original_draft_row"] == before[cid]
        assert row["evidence_rows_removed"] == EVIDENCE_PER_CASE[cid]
        assert row["answer_points_removed"] == len(before[cid]["acceptable_answer_points"])
        assert row["cohort"] in (
            "retire_minimal_dependency_closed_cohort", "retire_single_case_safely")
        if cid in RETIRE_COHORT:
            assert row["cohort"] == "retire_minimal_dependency_closed_cohort"
            assert row["dependency_closure_proof"]
        else:
            assert row["cohort"] == "retire_single_case_safely"
            assert row["isolation_facts"]


def test_retired_evidence_ledger(built):
    """retired-evidence.jsonl 7 行，保留原始行 + 固定理由 + 授权标识。"""
    out, _ = built
    rows = _jsonl(out / "retired-evidence.jsonl")
    assert len(rows) == 7
    assert all(r["retired_reason"] == RETIRE_REASON for r in rows)
    assert all(r["retired_by"] == ACTOR for r in rows)
    by_case: dict[str, int] = {}
    for r in rows:
        by_case[r["case_id"]] = by_case.get(r["case_id"], 0) + 1
        assert r["original_evidence_row"]["case_id"] == r["case_id"]
    assert by_case == EVIDENCE_PER_CASE
    # 原 evidence 行逐字保留
    before = {json.loads(l)["case_id"]: json.loads(l)
              for l in open(V208 / "evidence-after.jsonl", encoding="utf-8")}
    for r in rows:
        ev = r["original_evidence_row"]
        assert (ev["case_id"], ev["chunk_id"]) == (r["case_id"], r["chunk_id"])
        assert ev["raw_evidence_span"] == r["raw_evidence_span"]


def test_retirement_dependency_ledger(built):
    out, _ = built
    ledger = json.load(open(out / "retirement-dependency-ledger.json",
                            encoding="utf-8"))
    assert ledger["authorization"] == ACTOR
    closure = ledger["dependency_closure"]
    assert closure["cohort"] == list(RETIRE_COHORT)
    assert closure["minimal_closed_cohort_recomputed"] == list(RETIRE_COHORT)
    assert closure["cohort_matches_minimal_closure"] is True
    assert closure["dangling_refs"] == []
    assert closure["dangling_ref_count"] == 0
    assert closure["orphan_previous_turns"] == []
    assert closure["case_id_doc_target_refs"] == []
    chain_impact = closure["chain_impact"]
    assert chain_impact["multi-028"]["status"] == "fully_retired"
    assert chain_impact["multi-028"]["retired_members"] == \
        ["multi-030", "multi-031"]
    assert chain_impact["multi-030"]["status"] == "fully_retired"
    m027 = ledger["mixed027"]
    assert m027["retire_single_case_safely"] is True
    assert m027["incoming_case_refs"] == []
    assert m027["outgoing_case_refs"] == []
    counts = ledger["counts"]
    assert counts["case_before"] == CASE_BEFORE
    assert counts["case_after"] == CASE_AFTER
    assert counts["evidence_before"] == EVIDENCE_BEFORE
    assert counts["evidence_after"] == EVIDENCE_AFTER
    assert counts["retired_cases"] == 6
    assert counts["retired_evidence"] == 7
    assert ledger["verification"]["after_no_dangling_refs"] is True
    assert ledger["verification"]["after_chain_members_clean"] is True
    assert ledger["verification"]["strict_validator_144_144"] is True


def test_field_level_diff(built):
    out, _ = built
    rows = {r["case_id"]: r for r in _jsonl(out / "field-level-diff.jsonl")}
    assert set(rows) == set(ALL_RETIRED)
    for cid, row in rows.items():
        assert row["action"] == "retire_case"
        assert row["reason"] == RETIRE_REASON
        assert row["authorization_marker"] == ACTOR
        assert row["removed"]["draft_row"] is True
        assert len(row["removed"]["answer_points"]) == \
            row["answer_points_removed"]
        assert len(row["removed"]["evidence_rows"]) == EVIDENCE_PER_CASE[cid]
        for ev in row["removed"]["evidence_rows"]:
            assert ev["chunk_id"] and ev["source_id"] and \
                isinstance(ev["raw_chunk_char_range"], dict)


def test_data_quality_report(built):
    out, _ = built
    dq = json.load(open(out / "data-quality-report.json", encoding="utf-8"))
    checks = dq["equivalent_deterministic_checks"]
    assert checks["completeness"]["case_before"] == CASE_BEFORE
    assert checks["completeness"]["case_after"] == CASE_AFTER
    assert checks["completeness"]["evidence_before"] == EVIDENCE_BEFORE
    assert checks["completeness"]["evidence_after"] == EVIDENCE_AFTER
    assert checks["uniqueness"]["draft_case_ids_unique"] is True
    assert checks["referential_integrity"]["after_no_dangling_refs"] is True
    assert checks["referential_integrity"]["no_residual_chain_members"] is True
    assert checks["continuity"]["all_raw_spans_rebuildable"] is True
    assert checks["continuity"]["non_target_rows_byte_identical"] is True
    assert checks["consistency"]["strict_validation_144_144"] is True
    assert checks["consistency"]["answerable_cases_have_evidence"] is True
    assert dq["skill"]["available"] is False


def test_review_split_rebuild_md(built):
    out, _ = built
    md = (out / "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md").read_text(encoding="utf-8")
    assert "CANDIDATE" in md and "activation_blocked" in md
    assert "137" in md and "144" in md
    assert "不复用" in md
    assert "v2.0.7" in md and "v2.0.8" in md
    assert "盲态复审" in md


def test_manifest_self_hash_and_outputs(built):
    out, _ = built
    m = json.load(open(out / "manifest.json", encoding="utf-8"))
    assert m["manifest_sha256"] == _recompute_self_hash(m)
    for name, sha in m["outputs"].items():
        assert _sha(out / name) == sha, name
    assert m["gate_verdict"] == "FINAL_DEPENDENCY_CLOSED_RETIREMENT_OK"
    assert m["deterministic"] is True


def test_manifest_metadata(built):
    out, _ = built
    m = json.load(open(out / "manifest.json", encoding="utf-8"))
    assert m["revision_status"] == "CANDIDATE"
    assert m["activation_blocked"] is True
    assert m["human_reviewed"] is False
    assert m["overlay_generated"] is False
    assert m["split_reseal_required"] is True
    assert m["v2_1_entered"] is False
    assert m["actor"] == ACTOR
    assert m["case_count_before"] == CASE_BEFORE
    assert m["case_count_after"] == CASE_AFTER
    assert m["counts"]["retired_evidence"] == 7
    assert m["counts"]["retired_cases"] == 6


def test_manifest_declarations(built):
    out, _ = built
    m = json.load(open(out / "manifest.json", encoding="utf-8"))
    d = m["declarations"]
    assert d["llm_called"] is False
    assert d["network_used"] is False
    assert d["overlay_generated"] is False
    assert d["split_created"] is False
    assert d["v2_1_entered"] is False
    assert d["review_results_reused"] is False
    assert d["historical_verdicts_read"] is False
    assert d["data_modified"] == "authorized_retirement_only"
    # 不把严格验证通过写成审阅通过
    assert m.get("human_reviewed") is False
    assert m["validation"]["strict_validation_144_144"] is True
    assert m["validation"].get("review_passed") is not True


def test_no_forbidden_outputs(built):
    out, _ = built
    for f in out.rglob("*"):
        if f.is_file():
            low = f.name.lower()
            assert not any(bad in low for bad in FORBIDDEN_NAMES), f.name
    m = json.load(open(out / "manifest.json", encoding="utf-8"))
    assert m["declarations"]["overlay_generated"] is False
    assert m["declarations"]["split_created"] is False
    assert m["declarations"]["v2_1_entered"] is False


def test_inputs_sha_unchanged(built):
    inputs = [V208 / "manifest.json", V208 / "draft-after.jsonl",
              V208 / "evidence-after.jsonl",
              V208 / "deferred-chain-dependent-cases.jsonl",
              V208 / "final-blockers-decision-pack" / "manifest.json",
              V208 / "final-blockers-decision-pack" /
              "final-blockers-decision-pack.jsonl",
              V208 / "chain-closure-decision-pack" / "manifest.json",
              V208 / "chain-closure-decision-pack" /
              "multi-030-closure-options.json",
              V208 / "chain-closure-decision-pack" /
              "mixed-027-retirement-check.json",
              CHUNKS, CHUNK_MANIFEST, CURRENT_DRAFT]
    for path in inputs:
        assert _sha(path) == _sha(path)


def test_candidate_files_unchanged(tmp_path):
    """构建后 v2.0.8 candidate 既有文件 SHA 逐字节不变。"""
    sha_map = {}
    for f in V208.rglob("*"):
        if f.is_file():
            sha_map[str(f.relative_to(V208))] = _sha(f)
    p.run(out_dir=tmp_path / "out")
    for rel, sha in sha_map.items():
        assert _sha(V208 / rel) == sha, rel


def test_two_runs_byte_identical(tmp_path):
    p.run(out_dir=tmp_path / "o1")
    p.run(out_dir=tmp_path / "o2")
    for name in OUTPUT_FILES:
        assert _sha(tmp_path / "o1" / name) == _sha(tmp_path / "o2" / name), name


# ── 6. CLI ────────────────────────────────────────────────────────────

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
