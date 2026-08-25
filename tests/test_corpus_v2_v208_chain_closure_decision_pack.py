"""TDD tests for v2.0.8 chain-closure decision audit（只读、确定性）。

行为契约（fail-closed）：
- 输入仅限 v2.0.8 candidate 目录（manifest / draft-before/after /
  evidence-before/after / deferred ledger）+ 当前 v2 draft + chunks +
  chunk manifest + raw-codepoint strict validator；不调用 LLM/API、不联网、
  不读取 split/dev/holdout/锁配置/历史评测/早于 v2.0.7 的审阅结论。
- 已知事实门禁：v2.0.8 = 143 case / 151 strict evidence 151/151 /
  legacy=0 / unresolved=0 / manifest 自哈希 / gate REMEDIATION_CANDIDATE_OK；
  multi-030 在 deferred ledger（恰 1 条、原因固定、dependent_cases 与
  图引用一致）；multi-031.follow_up_to=="multi-030" 且
  multi-032/033/034.chain_id=="multi-030"（无其他引用）；
  multi-030.follow_up_to==None 且 chain_id=="multi-028"（multi-031 同链）；
  mixed-027 完全隔离（无 follow_up/chain/doc_target/previous_turns/任何
  进出引用）；multi-030~034 在 draft/evidence before→after 逐字节不变。
- 传递闭包：multi-030 下游 = {multi-031,multi-032,multi-033,multi-034}；
  上游可达 = {multi-015,multi-016,multi-018,multi-020,multi-022,
  multi-024,multi-025,multi-027,multi-028}；同链成员（chain multi-028）
  = {multi-030,multi-031}；无多节点环；自环仅 chain root 自标号
  （multi-011、multi-015，良性）。
- 退役场景：仅 retire multi-030 → 4 条悬挂引用，不可执行；retire
  multi-030~034 → 0 悬挂引用，可执行（143→138、evidence 151→146、
  5 AP；上游 chain multi-028 失去全部成员、chain multi-030 整链退役）；
  最小无悬挂闭包 == {multi-030..034}，可执行。
- mixed-027：AP0/AP1 均无完整、唯一、连续、同 source 直接支持（strict
  口径不放松）；无任何依赖 → retire_single_case_safely=true
  （143→142、evidence 151→149、2 AP）。
- 输出 8 个文件到 chain-closure-decision-pack/；owner-decision-template
  仅三个空字段；无 after/overlay/active/split/locked/v2.1 产物；
  不修改 candidate 任何既有文件；输入 SHA 不变；两次构建逐字节一致；
  manifest 自哈希一致。
"""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

import scripts.corpus_v2_v208_chain_closure_decision_pack as p

ROOT = Path(__file__).resolve().parents[1]
V208 = ROOT / "evaluation/datasets/v2/revisions/v2.0.8-owner-authorized-semantic-quality-remediation"
OUT = V208 / "chain-closure-decision-pack"
CHUNKS = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"

BLOCKERS = ("multi-030", "mixed-027")
CHAIN_CASES = ("multi-030", "multi-031", "multi-032", "multi-033", "multi-034")
MINIMAL_COHORT = ["multi-030", "multi-031", "multi-032", "multi-033", "multi-034"]
DEFER_REASON = "retirement_deferred_due_to_active_follow_up_chain_dependency"
SCENARIOS = ("retire_only_multi_030", "retire_multi030_to_multi034_group",
             "retire_minimal_dependency_closed_cohort")
OPTIONS_M030 = ("keep_deferred_and_block_fresh_review",
                "retire_minimal_dependency_closed_cohort",
                "retire_only_multi_030")
OPTIONS_M027 = ("retire_single_case_safely",
                "keep_deferred_and_block_fresh_review")

OUTPUT_FILES = (
    "dependency-graph.json", "multi-030-closure-options.json",
    "mixed-027-retirement-check.json", "chain-impact-map.json",
    "owner-decision-template.jsonl", "OWNER_DECISION_GUIDE.md",
    "chain-closure-report.md", "manifest.json",
)
FORBIDDEN_NAMES = ("overlay", "active-", "v2.1", "v2-1", "locked",
                   "holdout", "seal", "freeze", "after", "review-result",
                   "truth-overlay")

# 传递闭包（真实数据，确定性）
DOWNSTREAM_ALL = ["multi-031", "multi-032", "multi-033", "multi-034"]
UPSTREAM_ALL = ["multi-015", "multi-016", "multi-018", "multi-020",
                "multi-022", "multi-024", "multi-025", "multi-027",
                "multi-028"]
CHAIN_028_MEMBERS = ["multi-030", "multi-031"]
CHAIN_030_MEMBERS = ["multi-032", "multi-033", "multi-034"]


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
    除 final-blockers-decision-pack 与 chain-closure-decision-pack 外全部
    文件 SHA)。"""
    cand = _copy_tree(V208, tmp_path / "cand")
    sha_map = {}
    for f in V208.rglob("*"):
        if f.is_file() and "final-blockers-decision-pack" not in f.parts \
                and "chain-closure-decision-pack" not in f.parts:
            sha_map[str(f.relative_to(V208))] = _sha(f)
    return cand, sha_map


def _synthetic_draft(rows: list[dict]) -> list[dict]:
    """从 (id, follow_up_to, chain_id) 三元组构造最小 draft 行。"""
    out = []
    for cid, fu, ch in rows:
        meta = {}
        if fu:
            meta["follow_up_to"] = fu
        if ch:
            meta["chain_id"] = ch
        meta["turn"] = 1
        meta["construction"] = "follow_up"
        out.append({"id": cid, "doc_target": None, "metadata": meta,
                    "acceptable_answer_points": ["AP"]})
    return out


def _dump_like(obj: dict, template_line: str) -> str:
    """按 template_line 的既有序列化风格输出 obj。

    v2.0.8 的 jsonl 文件混用两种风格：复制行（default separators）与
    新写行（compact + sorted keys）。按原行格式重写可保证未篡改行逐字节
    不变（byte-identical 门禁依赖这一点）。
    """
    compact = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    if compact == template_line:
        return compact
    return json.dumps(obj, ensure_ascii=False)


def _rewrite_jsonl(path: Path, mutator) -> None:
    """按原格式逐行重写 jsonl；mutator(obj) 返回替换对象或 None（不改）。"""
    lines = open(path, encoding="utf-8").read().splitlines()
    out = []
    for l in lines:
        obj = json.loads(l)
        new = mutator(dict(obj))
        out.append(_dump_like(obj if new is None else new, l))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


# ── 1. 常量守恒 ───────────────────────────────────────────────────────

def test_constants_conservation():
    assert p.BLOCKERS == BLOCKERS
    assert p.CHAIN_CASES == CHAIN_CASES
    assert set(p.OUTPUT_FILES) == set(OUTPUT_FILES)
    assert p.DEFER_REASON == DEFER_REASON
    assert set(p.SCENARIOS) == set(SCENARIOS)
    assert set(p.OPTIONS_M030) == set(OPTIONS_M030)
    assert set(p.OPTIONS_M027) == set(OPTIONS_M027)
    assert len(BLOCKERS) == 2 and len(SCENARIOS) == 3
    assert p.OUT == OUT


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
    assert checks["byte_identical_cases"] == set(CHAIN_CASES)


def test_known_facts_multi030_relations():
    """multi-030 自身关系：无 follow_up 父节点、chain_id=multi-028；
    multi-031 与 multi-030 同链（chain multi-028）。"""
    checks = p.preflight()
    kf = checks["known_facts"]
    assert kf["multi030_follow_up_to"] is None
    assert kf["multi030_chain_id"] == "multi-028"
    assert kf["multi031_chain_id"] == "multi-028"
    assert kf["chain_028_members"] == CHAIN_028_MEMBERS
    assert kf["chain_030_members"] == CHAIN_030_MEMBERS
    assert kf["chain_deps"] == {"multi-031": ["follow_up_to"],
                                "multi-032": ["chain_id"],
                                "multi-033": ["chain_id"],
                                "multi-034": ["chain_id"]}


def test_mixed027_isolation():
    """mixed-027 完全隔离：无 follow_up/chain/doc_target/previous_turns，
    且无任何其他 case 引用它。"""
    checks = p.preflight()
    iso = checks["known_facts"]["mixed027_isolation"]
    assert iso["follow_up_to"] is None
    assert iso["chain_id"] is None
    assert iso["doc_target"] is None
    assert iso["previous_turns"] is None
    assert iso["incoming_refs"] == []
    assert iso["outgoing_refs"] == []


def test_deferred_ledger_dependent_cases_match_graph():
    """deferred ledger 的 dependent_cases 与图引用完全一致。"""
    checks = p.preflight()
    assert checks["deferred_ledger_consistent"] is True


def test_chain_cases_byte_identical_in_candidate():
    checks = p.preflight()
    assert checks["byte_identical"] is True
    assert checks["byte_identical_cases"] == set(CHAIN_CASES)


# ── 3. 依赖图（真实数据）──────────────────────────────────────────────

@pytest.fixture(scope="module")
def checks():
    return p.preflight()


def test_graph_nodes_and_edges(checks):
    g = checks["graph"]
    assert g["case_count"] == 143
    assert len(g["nodes"]) == 143
    by_rel = g["refs_by_type"]
    assert by_rel["follow_up_to"] == 15
    assert by_rel["chain_id"] == 24
    assert by_rel["doc_target"] == 0
    assert by_rel["previous_turns"] == 0
    assert len(g["edges"]) == 39


def test_graph_referential_integrity(checks):
    g = checks["graph"]
    ids = set(g["nodes"])
    for e in g["edges"]:
        assert e["from"] in ids and e["to"] in ids


def test_graph_chain_members_map(checks):
    g = checks["graph"]
    assert g["chain_members"] == {
        "multi-011": ["multi-011", "multi-012", "multi-013", "multi-014"],
        "multi-015": ["multi-015", "multi-016", "multi-017"],
        "multi-016": ["multi-018", "multi-019"],
        "multi-018": ["multi-020", "multi-021"],
        "multi-020": ["multi-022", "multi-023"],
        "multi-022": ["multi-024", "multi-025", "multi-026"],
        "multi-025": ["multi-027", "multi-028", "multi-029"],
        "multi-028": CHAIN_028_MEMBERS,
        "multi-030": CHAIN_030_MEMBERS,
    }


def test_graph_cycles_and_self_loops(checks):
    g = checks["graph"]
    assert g["cycles"] == []
    # 自环仅 chain root 自标号（multi-011、multi-015），良性
    loops = {(e["from"], e["to"], e["relation"], e.get("benign"))
             for e in g["self_loops"]}
    assert loops == {("multi-011", "multi-011", "chain_id", True),
                     ("multi-015", "multi-015", "chain_id", True)}


def test_graph_previous_turns_absent(checks):
    g = checks["graph"]
    assert g["previous_turns_facts"]["rows_with_field"] == 0
    assert g["previous_turns_facts"]["edges"] == 0


def test_downstream_closure(checks):
    """multi-030 下游直接与传递依赖。"""
    r = checks["reachability"]
    assert r["seed"] == "multi-030"
    assert r["downstream"]["all"] == DOWNSTREAM_ALL
    assert r["downstream"]["n"] == 4
    direct = r["downstream"]["direct"]
    assert direct["multi-031"] == ["follow_up_to"]
    assert direct["multi-032"] == ["chain_id"]
    assert direct["multi-033"] == ["chain_id"]
    assert direct["multi-034"] == ["chain_id"]
    assert r["downstream"]["transitive"] == {}


def test_upstream_closure_and_same_chain(checks):
    """上游父节点、同链成员、链传递引用。"""
    r = checks["reachability"]
    assert r["follow_up_parent"] is None
    assert r["chain_id"] == "multi-028"
    assert r["same_chain_members"] == ["multi-031"]
    assert r["upstream"]["all"] == UPSTREAM_ALL
    assert r["upstream"]["n"] == 9
    assert r["upstream"]["direct"]["multi-028"] == ["chain_id"]
    assert "multi-027" in r["upstream"]["transitive"]
    assert "multi-015" in r["upstream"]["transitive"]


def test_minimal_closed_cohort_real(checks):
    """最小无悬挂闭包 == {multi-030..034}（不包含 multi-028）。"""
    cohort = p._minimal_closed_cohort(checks["graph"], "multi-030")
    assert cohort == MINIMAL_COHORT


# ── 4. 退役场景（multi-030）───────────────────────────────────────────

def test_retire_only_multi030_not_executable(checks):
    """仅 retire multi-030 → 4 条悬挂引用（multi-031 fu + 032/033/034
    chain_id），不可执行。"""
    scen = p._retirement_scenario(checks["graph"], ["multi-030"])
    assert scen["cohort"] == ["multi-030"]
    assert scen["executable"] is False
    dangling = {(e["from"], e["relation"]) for e in scen["dangling_refs"]}
    assert dangling == {("multi-031", "follow_up_to"),
                        ("multi-032", "chain_id"),
                        ("multi-033", "chain_id"),
                        ("multi-034", "chain_id")}
    assert scen["case_count_after"] == 142
    assert scen["evidence_count_after"] == 150
    # chain multi-028 部分缺员（multi-031 仍在）
    assert scen["chain_impact"]["multi-028"]["remaining_members"] == \
        ["multi-031"]


def test_retire_multi030_to_multi034_group_executable(checks):
    """retire multi-030~034 → 0 悬挂引用；143→138、evidence 151→146、
    5 AP；上游 chain multi-028 失去全部成员。"""
    scen = p._retirement_scenario(checks["graph"], list(CHAIN_CASES))
    assert scen["executable"] is True
    assert scen["dangling_refs"] == []
    assert scen["cohort_size"] == 5
    assert scen["evidence_rows_removed"] == 5
    assert scen["answer_points_removed"] == 5
    assert scen["case_count_after"] == 138
    assert scen["evidence_count_after"] == 146
    assert scen["upstream_chains_affected"] == ["multi-028", "multi-030"]
    ci = scen["chain_impact"]
    assert ci["multi-028"]["retired_members"] == CHAIN_028_MEMBERS
    assert ci["multi-028"]["remaining_members"] == []
    assert ci["multi-028"]["status"] == "fully_retired"
    assert ci["multi-030"]["retired_members"] == CHAIN_030_MEMBERS
    assert ci["multi-030"]["status"] == "fully_retired"
    assert scen["orphan_previous_turns"] == []
    assert scen["case_id_doc_target_refs"] == []


def test_retire_minimal_cohort_executable(checks):
    """最小无悬挂闭包可执行，且与 5 组一致。"""
    cohort = p._minimal_closed_cohort(checks["graph"], "multi-030")
    scen = p._retirement_scenario(checks["graph"], cohort)
    assert scen["executable"] is True
    assert scen["cohort"] == MINIMAL_COHORT
    assert scen["case_count_after"] == 138


def test_multi030_closure_options(checks):
    """multi-030 选项：只核实，不选择。"""
    row = p._assess_multi030(checks)
    assert row["case_id"] == "multi-030"
    assert row["blocker_type"] == "deferred_chain_parent"
    opts = {o["option"]: o for o in row["options"]}
    assert set(opts) == set(OPTIONS_M030)
    keep = opts["keep_deferred_and_block_fresh_review"]
    assert keep["meets_criteria"] is True
    retire = opts["retire_minimal_dependency_closed_cohort"]
    assert retire["meets_criteria"] is True
    assert retire["impact"]["cohort"] == MINIMAL_COHORT
    only = opts["retire_only_multi_030"]
    assert only["meets_criteria"] is False
    assert only["criteria"]["dangling_ref_count"] == 4
    assert row["recommendation"] is None
    assert row["owner_decision_required"] is True
    # 场景全部给出
    assert {s["name"] for s in row["scenarios"]} == set(SCENARIOS)


# ── 5. mixed-027 退役核验 ─────────────────────────────────────────────

def test_mixed027_ap_verification(checks):
    """AP0/AP1 均无完整、唯一、连续、同 source 直接支持（strict 口径）。"""
    row = p._assess_mixed027(checks)
    aps = {a["answer_point_index"]: a for a in row["answer_points"]}
    ap0 = aps[0]
    assert ap0["answer_point"] == "术语表：原子化操作不可再分"
    assert ap0["direct_strict_support"] is False
    assert ap0["complete_verbatim_hit_in_source"] is False
    assert ap0["unique"] is False
    assert ap0["contiguous_support"] is False
    best0 = ap0["best_evidence"]
    assert best0["chunk_id"] == "c9fd20815ea8_chunk_2"
    assert best0["strict_in_span_coverage"] == 0.0
    assert best0["max_contiguous_coverage"] == 0.3846
    assert best0["token_fragments"]
    ap1 = aps[1]
    assert ap1["answer_point"] == "SQLite 语法页仅列出 begin-stmt，未展开事务原子性说明"
    assert ap1["direct_strict_support"] is False
    assert ap1["complete_verbatim_hit_in_source"] is False
    best1 = ap1["best_evidence"]
    assert best1["chunk_id"] == "8b191b241b93_chunk_1"
    assert best1["strict_in_span_coverage"] == 0.2857
    assert best1["exact_contiguous"] is False
    assert ap1["source_wide"]["longest_substring_text"] == "begin-stmt"
    assert ap1["source_wide"]["longest_substring_occurrences"] == 1


def test_mixed027_no_dependencies(checks):
    row = p._assess_mixed027(checks)
    deps = row["dependency_facts"]
    assert deps["follow_up_to"] is None
    assert deps["chain_id"] is None
    assert deps["doc_target"] is None
    assert deps["previous_turns"] is None
    assert deps["incoming_case_refs"] == []
    assert deps["outgoing_case_refs"] == []
    assert deps["chain_membership"] is None


def test_mixed027_retire_safely(checks):
    row = p._assess_mixed027(checks)
    assert row["retire_single_case_safely"] is True
    imp = row["impact"]
    assert imp["cohort"] == ["mixed-027"]
    assert imp["evidence_rows_removed"] == 2
    assert imp["answer_points_removed"] == 2
    assert imp["case_count_after"] == 142
    assert imp["evidence_count_after"] == 149
    assert imp["chain_impact"] == {}
    opts = {o["option"]: o for o in row["options"]}
    assert opts["retire_single_case_safely"]["meets_criteria"] is True
    assert opts["keep_deferred_and_block_fresh_review"]["meets_criteria"] is True
    assert row["recommendation"] is None


# ── 6. 环检测 / 悬挂引用 / 闭包增长（合成 fixture，单元级）────────────

def test_cycle_detection_fail_closed():
    """多节点环 → fail-closed。"""
    rows = _synthetic_draft([
        ("multi-030", None, "multi-028"),
        ("multi-028", None, "multi-025"),  # 被引用节点须存在
        ("multi-025", None, "multi-025"),
        ("multi-033", "multi-034", "multi-030"),  # 篡改：033→034 成环
        ("multi-034", "multi-033", "multi-030"),
    ])
    with pytest.raises(p.ClosureAuditError) as exc:
        p._build_dependency_graph(rows)
    assert "cycle" in str(exc.value).lower()


def test_self_loop_benign_and_invalid():
    """chain root 自标号（follow_up 为空）良性；follow_up 自环非法。"""
    rows = _synthetic_draft([("multi-011", None, "multi-011")])
    g = p._build_dependency_graph(rows)
    assert g["self_loops"][0]["benign"] is True
    bad = _synthetic_draft([("multi-011", "multi-011", "multi-011")])
    with pytest.raises(p.ClosureAuditError):
        p._build_dependency_graph(bad)


def test_unresolved_reference_fail_closed():
    """引用不存在的 case id → fail-closed。"""
    rows = _synthetic_draft([("multi-012", None, "multi-999")])
    with pytest.raises(p.ClosureAuditError):
        p._build_dependency_graph(rows)


def test_minimal_cohort_grows_with_new_referrer():
    """新引用者出现时最小闭包必须包含它（不预设 5 组范围）。"""
    rows = _synthetic_draft([
        ("multi-030", None, "multi-028"),
        ("multi-028", None, "multi-025"),
        ("multi-025", None, "multi-025"),
        ("multi-031", "multi-030", "multi-028"),
        ("multi-032", None, "multi-030"),
        ("multi-033", "multi-032", "multi-030"),
        ("multi-034", "multi-033", "multi-030"),
        ("multi-035", "multi-034", None),  # 新下游：035 follow_up 034
    ])
    g = p._build_dependency_graph(rows)
    cohort = p._minimal_closed_cohort(g, "multi-030")
    assert cohort == ["multi-030", "multi-031", "multi-032", "multi-033",
                      "multi-034", "multi-035"]


def test_scenario_dangling_refs_not_executable():
    """组内退役残留组外悬挂引用 → 该场景不可执行。"""
    rows = _synthetic_draft([
        ("multi-030", None, "multi-028"),
        ("multi-028", None, "multi-025"),
        ("multi-025", None, "multi-025"),
        ("multi-031", "multi-030", "multi-028"),
        ("multi-032", None, "multi-030"),
    ])
    g = p._build_dependency_graph(rows)
    scen = p._retirement_scenario(g, ["multi-030", "multi-031"])
    assert scen["executable"] is False
    assert len(scen["dangling_refs"]) == 1  # multi-032.chain_id → multi-030


# ── 7. 输出与模板 ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def built(tmp_path_factory):
    base = tmp_path_factory.mktemp("cc")
    out = base / "out"
    result = p.run(out_dir=out)
    return out, result


def test_output_file_set(built):
    out, _ = built
    assert set(f.name for f in out.iterdir()) == set(OUTPUT_FILES)


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


def test_dependency_graph_file(built):
    out, _ = built
    g = json.load(open(out / "dependency-graph.json", encoding="utf-8"))
    assert g["case_count"] == 143
    assert len(g["nodes"]) == 143
    assert g["cycles"] == []
    assert len(g["self_loops"]) == 2
    assert g["refs_by_type"]["doc_target"] == 0
    assert g["refs_by_type"]["previous_turns"] == 0
    r = g["reachability"]
    assert r["downstream"]["all"] == DOWNSTREAM_ALL
    assert r["upstream"]["all"] == UPSTREAM_ALL


def test_multi030_closure_options_file(built):
    out, _ = built
    doc = json.load(open(out / "multi-030-closure-options.json",
                         encoding="utf-8"))
    assert doc["case_id"] == "multi-030"
    assert doc["minimal_cohort"] == MINIMAL_COHORT
    by_name = {s["name"]: s for s in doc["scenarios"]}
    assert by_name["retire_only_multi_030"]["executable"] is False
    assert by_name["retire_multi030_to_multi034_group"]["executable"] is True
    assert by_name["retire_minimal_dependency_closed_cohort"]["executable"] is True
    assert doc["recommendation"] is None


def test_mixed027_retirement_check_file(built):
    out, _ = built
    doc = json.load(open(out / "mixed-027-retirement-check.json",
                         encoding="utf-8"))
    assert doc["case_id"] == "mixed-027"
    assert doc["retire_single_case_safely"] is True
    assert doc["dependency_facts"]["incoming_case_refs"] == []
    assert doc["recommendation"] is None
    assert doc["impact"]["evidence_count_after"] == 149


def test_chain_impact_map(built):
    out, _ = built
    m = json.load(open(out / "chain-impact-map.json", encoding="utf-8"))
    assert m["cohort"] == MINIMAL_COHORT
    edges = {(e["from"], e["to"], e["relation"]) for e in m["edges"]}
    assert ("multi-031", "multi-030", "follow_up_to") in edges
    assert ("multi-032", "multi-030", "chain_id") in edges
    assert ("multi-033", "multi-030", "chain_id") in edges
    assert ("multi-034", "multi-030", "chain_id") in edges
    assert ("multi-033", "multi-032", "follow_up_to") in edges
    assert ("multi-034", "multi-033", "follow_up_to") in edges
    assert ("multi-030", "multi-028", "chain_id") in edges
    assert ("multi-031", "multi-028", "chain_id") in edges
    assert "multi-028" in m["upstream_impact"]
    assert m["upstream_impact"]["multi-028"]["lost_chain_members"] == \
        CHAIN_028_MEMBERS
    s = m["impact_summary"]
    assert s["cases_removed"] == 5
    assert s["evidence_rows_removed"] == 5
    assert s["answer_points_removed"] == 5
    assert s["case_count_after"] == 138
    assert s["evidence_count_after"] == 146
    assert s["external_refs_outside_group"] == 2
    assert s["dangling_refs"] == 0
    for cid in CHAIN_CASES:
        assert m["cases"][cid]["n_evidence"] == 1
        assert m["cases"][cid]["n_answer_points"] == 1


def test_candidate_files_unchanged(tmp_path):
    """构建后 candidate 既有文件（除两个 pack 外）SHA 逐字节不变。"""
    sha_map = {}
    for f in V208.rglob("*"):
        if f.is_file() and "final-blockers-decision-pack" not in f.parts \
                and "chain-closure-decision-pack" not in f.parts:
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
    assert m["gate_verdict"] == "CHAIN_CLOSURE_DECISION_PACK_OK"
    assert m["deterministic"] is True


def test_two_runs_byte_identical(tmp_path):
    p.run(out_dir=tmp_path / "o1")
    p.run(out_dir=tmp_path / "o2")
    for name in OUTPUT_FILES:
        assert _sha(tmp_path / "o1" / name) == _sha(tmp_path / "o2" / name), name


def test_guide_and_report_files(built):
    out, _ = built
    guide = (out / "OWNER_DECISION_GUIDE.md").read_text(encoding="utf-8")
    assert "multi-030" in guide and "mixed-027" in guide
    assert "retire_minimal_dependency_closed_cohort" in guide
    assert "retire_single_case_safely" in guide
    assert "不自动选择" in guide or "不自行采纳" in guide
    report = (out / "chain-closure-report.md").read_text(encoding="utf-8")
    assert "multi-030" in report and "mixed-027" in report
    assert DEFER_REASON in report
    assert "multi-028" in report


def test_no_llm_and_read_only_declared(built):
    _, result = built
    m = result["manifest"]
    assert m["declarations"]["llm_called"] is False
    assert m["declarations"]["data_modified"] == "none"
    assert m["declarations"]["input_scope"] == \
        ["v2.0.8 candidate dir", "chunks", "chunk manifest",
         "raw-codepoint strict validator"]


def test_skill_note_recorded(built):
    _, result = built
    assert "data-analytics:analyze-data-quality" in \
        result["manifest"]["skill_note"]


# ── 8. fail-closed 漂移门禁（真实输入篡改副本）────────────────────────

def test_fail_closed_manifest_drift(tmp_path):
    cand, _ = _snapshot_candidate(tmp_path)
    m_path = cand / "manifest.json"
    m = json.load(open(m_path, encoding="utf-8"))
    m["counts"]["case_after"] = 144
    m_path.write_text(json.dumps(m, ensure_ascii=False, indent=1,
                                 sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(p.ClosureAuditError):
        p.run(candidate_dir=cand, out_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_fail_closed_chain_drift(tmp_path):
    cand, _ = _snapshot_candidate(tmp_path)
    path = cand / "draft-after.jsonl"
    _rewrite_jsonl(path, lambda r: None
                   if r["id"] != "multi-031"
                   else {**r, "metadata": {**r["metadata"],
                                           "follow_up_to": None}})
    with pytest.raises(p.ClosureAuditError):
        p.run(candidate_dir=cand, out_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_fail_closed_multi030_chain_id_drift(tmp_path):
    """multi-030.chain_id 不再是 multi-028 → 已知事实漂移。"""
    cand, _ = _snapshot_candidate(tmp_path)
    path = cand / "draft-after.jsonl"
    _rewrite_jsonl(path, lambda r: None
                   if r["id"] != "multi-030"
                   else {**r, "metadata": {**r["metadata"],
                                           "chain_id": "multi-025"}})
    with pytest.raises(p.ClosureAuditError):
        p.run(candidate_dir=cand, out_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_fail_closed_mixed027_isolation_drift(tmp_path):
    """mixed-027 出现 follow_up 引用 → 隔离门禁。"""
    cand, _ = _snapshot_candidate(tmp_path)
    path = cand / "draft-after.jsonl"
    _rewrite_jsonl(path, lambda r: None
                   if r["id"] != "mixed-027"
                   else {**r, "metadata": {**r["metadata"],
                                           "follow_up_to": "en-021"}})
    with pytest.raises(p.ClosureAuditError):
        p.run(candidate_dir=cand, out_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_fail_closed_unresolved_reference(tmp_path):
    """图引用指向不存在的 case id → fail-closed。"""
    cand, _ = _snapshot_candidate(tmp_path)
    path = cand / "draft-after.jsonl"
    _rewrite_jsonl(path, lambda r: None
                   if r["id"] != "multi-012"
                   else {**r, "metadata": {**r["metadata"],
                                           "chain_id": "multi-999"}})
    with pytest.raises(p.ClosureAuditError):
        p.run(candidate_dir=cand, out_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_fail_closed_cycle_detection(tmp_path):
    """图出现多节点环（033↔034）→ fail-closed。"""
    cand, _ = _snapshot_candidate(tmp_path)
    path = cand / "draft-after.jsonl"
    _rewrite_jsonl(path, lambda r: None
                   if r["id"] != "multi-033"
                   else {**r, "metadata": {**r["metadata"],
                                           "follow_up_to": "multi-034"}})
    with pytest.raises(p.ClosureAuditError) as exc:
        p.run(candidate_dir=cand, out_dir=tmp_path / "out")
    assert "cycle" in str(exc.value).lower()
    assert not (tmp_path / "out").exists()


def test_fail_closed_deferred_ledger_drift(tmp_path):
    cand, _ = _snapshot_candidate(tmp_path)
    path = cand / "deferred-chain-dependent-cases.jsonl"
    _rewrite_jsonl(path, lambda r: None
                   if r.get("case_id") != "multi-030"
                   else {**r, "dependent_cases": r["dependent_cases"][:-1]})
    with pytest.raises(p.ClosureAuditError):
        p.run(candidate_dir=cand, out_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_fail_closed_evidence_drift(tmp_path):
    cand, _ = _snapshot_candidate(tmp_path)
    path = cand / "evidence-after.jsonl"
    lines = open(path, encoding="utf-8").read().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(p.ClosureAuditError):
        p.run(candidate_dir=cand, out_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()


# ── 9. CLI ────────────────────────────────────────────────────────────

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
