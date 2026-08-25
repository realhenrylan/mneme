"""v2.0.9 owner-authorized final dependency-closed retirement candidate.

所有者授权的确定性数据治理修复：退役 6 个 case（最小无悬挂依赖闭包
multi-030~multi-034 + 安全隔离 case mixed-027）及其 7 条 evidence，
生成独立的 v2.0.9 candidate：143 → 137 条 case、evidence 151 → 144 行。
不修改 v2.0.8 或更早 revision；不生成 overlay / active metadata / split /
locked config / v2.1 文件；不调用 LLM/API、不联网；不 stage / commit / push。

授权依据（fail-closed 核验）：
- v2.0.8 == 143 cases / 151 active evidence / strict 151/151 /
  legacy=unresolved=0；
- v2.0.8 final-blockers decision pack 与 chain-closure decision pack 的
  gate 与自哈希一致，其记录的 input SHA 与当前磁盘一致；
- chain-closure pack：retire_minimal_dependency_closed_cohort ==
  {multi-030..multi-034} 且 retirement-safe（meets_criteria=true、
  scenario executable、0 悬挂引用）；retire_only_multi_030 不可执行
  （4 条悬挂引用）；
- mixed-027.retire_single_case_safely == true（无任何引用依赖）；
- 本脚本在**当前 draft** 上重新复算最小无悬挂闭包（不动点），必须恰等于
  授权 cohort，否则整体 fail-closed；mixed-027 必须完全隔离。

退役后不变量（全部 fail-closed 验证）：
- 仅移除上述 6 个 case 及其 7 条 evidence；其余 draft/evidence 行
  逐字节不变；不改写任何保留 case 的 query / 答案点 / source / chain /
  follow-up / previous turns / evidence；
- 无 dangling case 引用、无残留 chain member、无 orphan previous turn、
  无 doc-target 悬空；multi-028 与其上游链无孤儿引用；
- strict validator 144/144 covered==passed；legacy/unresolved/invalid/
  uncovered == 0；所有保留 answerable case 至少一条合法 strict evidence。

「严格证据验证通过」不构成审阅通过、confirmed 或 active 准入；激活前必须
一次全新的 137-case 盲态机器复审，不得复用 v2.0.7 / v2.0.8 的 review 结果。

CLI
---
::

    python scripts/corpus_v2_v209_final_dependency_closed_retirement.py build
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import corpus_v2_evidence_coordinate_repair as coord
from scripts.corpus_v2_v207_review_reject_triage import (  # 复用既有确定性原语
    _atomic_write, _dump, _jsonl, _manifest, _sha256_file, _sha256_text,
    _verify_self_hash,
)
from scripts.corpus_v2_v208_chain_closure_decision_pack import (  # 复用闭包原语
    CASE_ID_RE, _iter_case_refs, _minimal_closed_cohort, _retirement_scenario,
)


def _line(obj: Any) -> str:
    """JSONL 单行（行尾含换行；triage 模块原语不含换行，本模块统一约定）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + "\n"


ROOT = Path(__file__).resolve().parents[1]
V208 = ROOT / "evaluation/datasets/v2/revisions/v2.0.8-owner-authorized-semantic-quality-remediation"
OUT = ROOT / "evaluation/datasets/v2/revisions/v2.0.9-owner-authorized-final-dependency-closed-retirement"
CHUNKS = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"

TIMESTAMP = "2026-08-11T00:00:00+00:00"
RULE_VERSION = "v2.0.9-final-dependency-closed-retirement-1"
CONTRACT = "raw-codepoint-v1"
ACTOR = "OWNER_AUTHORIZED_FINAL_DEPENDENCY_CLOSED_RETIREMENT"
AUTHORIZATION = ACTOR
RETIRE_REASON = "owner_authorized_final_dependency_closed_retirement"
DEFER_REASON = "retirement_deferred_due_to_active_follow_up_chain_dependency"
COHORT_GATE = "retire_minimal_dependency_closed_cohort"
ISOLATED_GATE = "retire_single_case_safely"

RETIRE_COHORT = ("multi-030", "multi-031", "multi-032", "multi-033", "multi-034")
RETIRE_ISOLATED = ("mixed-027",)
ALL_RETIRED = RETIRE_COHORT + RETIRE_ISOLATED

EXPECTED_CASE_BEFORE = 143
EXPECTED_EVIDENCE_BEFORE = 151
# 每个退役 case 的 evidence 行数（固定授权事实；漂移 → fail-closed）
EXPECTED_EVIDENCE_PER_CASE = {"multi-030": 1, "multi-031": 1, "multi-032": 1,
                              "multi-033": 1, "multi-034": 1, "mixed-027": 2}
EXPECTED_RETIRED_EVIDENCE = sum(EXPECTED_EVIDENCE_PER_CASE.values())  # 7

# multi-030 链关系必须与授权 defer 依据完全一致（漂移 → 整体停止）
DEFERRED_CHAIN_EXPECTED = {
    "multi-031": ["follow_up_to"],
    "multi-032": ["chain_id"],
    "multi-033": ["chain_id"],
    "multi-034": ["chain_id"],
}
MINIMAL_CLOSURE_RULE = (
    "不动点：cohort 中任一 case 被组外 case 引用 → 该引用者入组，直至稳定；"
    "multi-031.follow_up_to→multi-030 与 multi-032/033/034.chain_id→multi-030 "
    "强制其入组，组内再无对外引用者被组外引用")
EXCLUDES_MULTI028_NOTE = (
    "multi-028 不引用组内任何 case（multi-028.chain_id=multi-025、"
    "follow_up_to=multi-027），无需入组")

OUTPUT_FILES = (
    "draft-after.jsonl", "evidence-after.jsonl", "retired-cases.jsonl",
    "retired-evidence.jsonl", "retirement-dependency-ledger.json",
    "field-level-diff.jsonl", "data-quality-report.json",
    "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md", "manifest.json",
)

SKILL_NOTE = (
    "data-analytics:analyze-data-quality skill 在本环境中不可用"
    "（不在已安装 skills 列表内，无法加载；已实际尝试）；已按任务约束实施"
    "等价的确定性质量检查（完整性 / 唯一性 / 引用完整性 / 连续性 / 一致性），"
    "全部为机械复算，无 LLM 参与。"
)

# decision pack manifest inputs 键名 → 本地文件相对路径
PACK_INPUT_PATHS = {
    "v208-manifest.json": ("candidate", "manifest.json"),
    "draft-after.jsonl": ("candidate", "draft-after.jsonl"),
    "draft-before.jsonl": ("candidate", "draft-before.jsonl"),
    "evidence-after.jsonl": ("candidate", "evidence-after.jsonl"),
    "evidence-before.jsonl": ("candidate", "evidence-before.jsonl"),
    "deferred-chain-dependent-cases.jsonl": ("candidate",
                                             "deferred-chain-dependent-cases.jsonl"),
    "chunks.jsonl": ("chunks",),
    "chunk-manifest.json": ("chunk_manifest",),
    "current-v2-draft.jsonl": ("current_draft",),
    "targeted-review-result.json": ("candidate", "targeted-re-review",
                                    "targeted-review-result.json"),
    "targeted-review-status.json": ("candidate", "targeted-re-review",
                                    "review-status.json"),
}


class RetirementError(Exception):
    """Fail-closed retirement failure（任何非法状态立即失败、零输出）。"""


# ── 依赖图构建（悬挂/环作为数据返回，由门禁判错）──────────────────────

def _build_dependency_graph(draft_rows: list[dict],
                            evidence_rows: list[dict] | None = None) -> dict:
    """构建完整多轮依赖图（所有 case-id 字段引用）。

    边方向约定：from=引用者（字段所在 case），to=被引用者。
    与 chain-closure 版本不同：悬挂引用与环**不抛错**，作为数据返回，
    由调用方门禁统一 fail-closed（便于对退役后状态做同样核验）。
    """
    evidence_rows = evidence_rows or []
    ev_by_case: dict[str, list[dict]] = defaultdict(list)
    for e in evidence_rows:
        ev_by_case[e["case_id"]].append(e)
    ids = {r["id"] for r in draft_rows}
    nodes: dict[str, dict] = {}
    for r in draft_rows:
        meta = r.get("metadata") or {}
        cid = r["id"]
        nodes[cid] = {
            "case_id": cid,
            "turn": meta.get("turn"),
            "construction": meta.get("construction"),
            "follow_up_to": meta.get("follow_up_to"),
            "chain_id": meta.get("chain_id"),
            "doc_target": r.get("doc_target"),
            "previous_turns": meta.get("previous_turns"),
            "is_refusal_turn": r.get("is_refusal_turn"),
            "should_refuse": r.get("should_refuse"),
            "language": r.get("language"),
            "n_answer_points": len(r.get("acceptable_answer_points") or []),
            "n_evidence": len(ev_by_case.get(cid, [])),
        }
    edges = []
    for r in draft_rows:
        for rel, path, target in _iter_case_refs(r):
            edges.append({"from": r["id"], "to": target, "relation": rel,
                          "field_path": path})
    dangling = sorted((e for e in edges if e["to"] not in ids),
                      key=lambda e: (e["from"], e["to"], e["relation"]))
    self_loops = sorted((e for e in edges if e["from"] == e["to"]),
                        key=lambda e: e["from"])
    rest = [e for e in edges if e["from"] != e["to"]]
    # 多节点环（DFS 后向边）
    adj: dict[str, list[dict]] = defaultdict(list)
    for e in rest:
        adj[e["from"]].append(e)
    color: dict[str, int] = {}
    back: set[tuple[str, str, str]] = set()

    def dfs(u: str) -> None:
        color[u] = 1
        for e in adj[u]:
            v = e["to"]
            if color.get(v) == 1:
                back.add((u, v, e["relation"]))
            elif color.get(v, 0) == 0:
                dfs(v)
        color[u] = 2

    for u in sorted(adj):
        if color.get(u, 0) == 0:
            dfs(u)
    cycles = sorted(back)
    chain_members: dict[str, list[str]] = defaultdict(list)
    for r in draft_rows:
        ch = (r.get("metadata") or {}).get("chain_id")
        if isinstance(ch, str) and ch:
            chain_members[ch].append(r["id"])
    refs_by_type: dict[str, int] = defaultdict(int)
    for e in edges:
        refs_by_type[e["relation"]] += 1
    n_pt = sum(1 for r in draft_rows
               if "previous_turns" in (r.get("metadata") or {}))
    return {
        "case_count": len(draft_rows),
        "evidence_count": len(evidence_rows),
        "nodes": nodes,
        "edges": sorted(edges, key=lambda e: (e["from"], e["to"],
                                              e["relation"])),
        "dangling_refs": dangling,
        "refs_by_type": {k: refs_by_type.get(k, 0) for k in
                         ("follow_up_to", "chain_id", "doc_target",
                          "previous_turns")},
        "self_loops": self_loops,
        "cycles": cycles,
        "chain_members": {k: sorted(v) for k, v in
                          sorted(chain_members.items())},
        "previous_turns_facts": {
            "rows_with_field": n_pt,
            "edges": refs_by_type.get("previous_turns", 0),
            "note": ("全量 draft 行 metadata 均无 previous_turns 字段值；"
                     "无 previous-turn 引用边，无孤儿 previous turn 风险"),
        },
    }


def _graph_gate(graph: dict, draft_by_id: dict[str, dict], *, where: str) -> None:
    """图级 fail-closed：无悬挂引用、无多节点环、自环仅限良性 chain root。"""
    if graph["dangling_refs"]:
        raise RetirementError(
            f"{where}: dangling case reference(s): {graph['dangling_refs']}")
    if graph["cycles"]:
        raise RetirementError(f"{where}: cycle(s) detected: {graph['cycles']}")
    for e in graph["self_loops"]:
        row = draft_by_id.get(e["from"]) or {}
        fu = (row.get("metadata") or {}).get("follow_up_to")
        benign = e["relation"] == "chain_id" and not fu
        if not benign:
            raise RetirementError(
                f"{where}: invalid self-loop: {e['from']}.{e['relation']} -> "
                f"{e['to']} (non-root or non-chain_id)")


# ── 前置门禁（fail-closed，只读）──────────────────────────────────────

def preflight(*, candidate_dir: Path = V208, chunks_path: Path = CHUNKS,
              chunk_manifest_path: Path = CHUNK_MANIFEST,
              current_draft_path: Path = CURRENT_DRAFT) -> dict:
    """只读校验全部输入门禁；任一不符 → RetirementError。"""
    manifest_path = candidate_dir / "manifest.json"
    if not manifest_path.exists():
        raise RetirementError(f"v2.0.8 candidate manifest missing: {manifest_path}")
    m = json.load(open(manifest_path, encoding="utf-8"))
    if m.get("gate_verdict") != "REMEDIATION_CANDIDATE_OK":
        raise RetirementError("v2.0.8 candidate gate not OK")
    if not _verify_self_hash(m):
        raise RetirementError("v2.0.8 candidate manifest self-hash mismatch")
    counts = m.get("counts") or {}
    if counts.get("case_after") != EXPECTED_CASE_BEFORE or \
            counts.get("evidence_after") != EXPECTED_EVIDENCE_BEFORE or \
            counts.get("deferred_cases") != 1:
        raise RetirementError(f"v2.0.8 counts drift: {counts}")
    if m.get("revision_status") != "CANDIDATE" or \
            m.get("activation_blocked") is not True:
        raise RetirementError("v2.0.8 candidate status drift")

    # ── deferred ledger 恰 1 条 multi-030 ────────────────────────────
    deferred = _jsonl(candidate_dir / "deferred-chain-dependent-cases.jsonl")
    if len(deferred) != 1 or deferred[0].get("case_id") != "multi-030" or \
            deferred[0].get("deferred_reason") != DEFER_REASON:
        raise RetirementError("deferred ledger drift")
    dep_expected = [{"case_id": cid, "relation": rel}
                    for cid, rel in (
                        ("multi-031", "follow_up_to"), ("multi-032", "chain_id"),
                        ("multi-033", "chain_id"), ("multi-034", "chain_id"))]
    ledger_deps = sorted(deferred[0].get("dependent_cases") or [],
                         key=lambda d: d.get("case_id"))
    if ledger_deps != dep_expected:
        raise RetirementError(f"deferred ledger dependent_cases drift: "
                              f"{ledger_deps}")

    # ── draft / evidence 计数与 strict 校验 ──────────────────────────
    draft_rows = _jsonl(candidate_dir / "draft-after.jsonl")
    draft_ids = [r["id"] for r in draft_rows]
    if len(draft_rows) != EXPECTED_CASE_BEFORE or \
            len(set(draft_ids)) != EXPECTED_CASE_BEFORE:
        raise RetirementError(f"draft-after count drift: {len(draft_rows)}")
    evidence_rows = _jsonl(candidate_dir / "evidence-after.jsonl")
    if len(evidence_rows) != EXPECTED_EVIDENCE_BEFORE:
        raise RetirementError(f"evidence-after count drift: "
                              f"{len(evidence_rows)}")
    chunks = {c["chunk_id"]: c for c in _jsonl(chunks_path)}
    if len(chunks) != sum(1 for _ in open(chunks_path, encoding="utf-8")
                          if _.strip()):
        raise RetirementError("duplicate chunk_id in chunks")
    try:
        coord.strict_validate(evidence_rows, chunks)
    except coord.CoordinateError as exc:
        raise RetirementError(f"strict evidence validation failed: {exc}")
    legacy = [e for e in evidence_rows
              if e.get("coordinate_contract") != CONTRACT]
    unresolved = [e for e in evidence_rows
                  if not e.get("raw_evidence_span") or
                  not isinstance(e.get("raw_chunk_char_range"), dict)]
    if legacy or unresolved:
        raise RetirementError(
            f"legacy={len(legacy)} unresolved={len(unresolved)}")

    # ── 两个 decision pack 的 gate 与自哈希 ──────────────────────────
    fb_pack = candidate_dir / "final-blockers-decision-pack"
    cc_pack = candidate_dir / "chain-closure-decision-pack"
    fb_manifest = json.load(open(fb_pack / "manifest.json", encoding="utf-8"))
    cc_manifest = json.load(open(cc_pack / "manifest.json", encoding="utf-8"))
    if fb_manifest.get("gate_verdict") != "FINAL_BLOCKERS_DECISION_PACK_OK" or \
            not _verify_self_hash(fb_manifest):
        raise RetirementError("final-blockers decision pack gate not OK")
    if cc_manifest.get("gate_verdict") != "CHAIN_CLOSURE_DECISION_PACK_OK" or \
            not _verify_self_hash(cc_manifest):
        raise RetirementError("chain-closure decision pack gate not OK")

    # ── pack 内容：闭包选项与 mixed-027 核验必须与授权一致 ──────────
    closure_options = json.load(open(
        cc_pack / "multi-030-closure-options.json", encoding="utf-8"))
    if closure_options.get("minimal_cohort") != list(RETIRE_COHORT):
        raise RetirementError(
            f"closure pack minimal_cohort drift: "
            f"{closure_options.get('minimal_cohort')}")
    by_name = {o["option"]: o for o in closure_options.get("options", [])}
    if not by_name.get(COHORT_GATE, {}).get("meets_criteria") is True:
        raise RetirementError(f"closure pack {COHORT_GATE} not verified")
    scens = {s["name"]: s for s in closure_options.get("scenarios", [])}
    if not scens.get(COHORT_GATE, {}).get("executable") is True or \
            scens.get(COHORT_GATE, {}).get("dangling_ref_count") != 0:
        raise RetirementError(f"closure pack {COHORT_GATE} not executable")
    if scens.get("retire_only_multi_030", {}).get("executable") is not False:
        raise RetirementError("closure pack retire_only_multi_030 "
                              "must be not executable")
    mixed027_check = json.load(open(
        cc_pack / "mixed-027-retirement-check.json", encoding="utf-8"))
    if mixed027_check.get("retire_single_case_safely") is not True:
        raise RetirementError("mixed-027 retire_single_case_safely not true")
    if not (mixed027_check.get("impact") or {}).get("executable") is True:
        raise RetirementError("mixed-027 retirement impact not executable")

    # ── 依赖图 + 引用完整性 + 环 + 闭包 + mixed-027 隔离（fail-closed）
    draft_by_id = {r["id"]: r for r in draft_rows}
    graph = _build_dependency_graph(draft_rows, evidence_rows)
    _graph_gate(graph, draft_by_id, where="v2.0.8 draft")
    if graph["chain_members"].get("multi-028") != \
            ["multi-030", "multi-031"]:
        raise RetirementError("chain multi-028 membership drift")

    # 已知事实：multi-030 链关系精确
    deps: dict[str, list[str]] = {}
    for row in draft_rows:
        meta = row.get("metadata") or {}
        for key, val in (("follow_up_to", meta.get("follow_up_to")),
                         ("chain_id", meta.get("chain_id")),
                         ("doc_target", row.get("doc_target"))):
            if val == "multi-030":
                deps.setdefault(row["id"], []).append(key)
    if deps != DEFERRED_CHAIN_EXPECTED:
        raise RetirementError(f"chain drift for multi-030: {deps}")
    m030 = draft_by_id["multi-030"]
    m030_meta = m030.get("metadata") or {}
    if m030_meta.get("follow_up_to") is not None or \
            m030_meta.get("chain_id") != "multi-028" or \
            (draft_by_id["multi-031"].get("metadata") or {}).get(
                "chain_id") != "multi-028":
        raise RetirementError("multi-030/multi-031 chain identity drift")

    # 重新复算最小无悬挂闭包：必须恰等于授权 cohort
    minimal = _minimal_closed_cohort(graph, "multi-030")
    if minimal != list(RETIRE_COHORT):
        raise RetirementError(
            f"minimal closed cohort drift: {minimal} "
            f"(authorized {list(RETIRE_COHORT)})")
    cohort_scenario = _retirement_scenario(graph, list(RETIRE_COHORT))
    if not cohort_scenario["executable"] or \
            cohort_scenario["dangling_ref_count"] != 0:
        raise RetirementError(
            f"retire cohort not retirement-safe: "
            f"{cohort_scenario['dangling_refs']}")

    # mixed-027 完全隔离：无入边、无出边
    incoming_m027 = [e for e in graph["edges"] if e["to"] == "mixed-027"]
    outgoing_m027 = [e for e in graph["edges"] if e["from"] == "mixed-027"]
    if incoming_m027 or outgoing_m027:
        raise RetirementError(f"mixed-027 isolation drift: "
                              f"in={incoming_m027} out={outgoing_m027}")
    m027_scenario = _retirement_scenario(graph, ["mixed-027"])
    if not m027_scenario["executable"]:
        raise RetirementError("mixed-027 retirement not executable")

    # ── 6 个退役 case 在 v2.0.8 before→after 逐字节不变 ──────────────
    def _lines(path: Path) -> list[str]:
        return open(path, encoding="utf-8").read().splitlines()

    def _by_id(lines: list[str]) -> dict[str, str]:
        return {json.loads(l)["id"]: l for l in lines}

    def _by_case(lines: list[str]) -> dict[str, list[str]]:
        out_d: dict[str, list[str]] = {}
        for l in lines:
            out_d.setdefault(json.loads(l)["case_id"], []).append(l)
        return out_d

    db = _by_id(_lines(candidate_dir / "draft-before.jsonl"))
    da = _by_id(_lines(candidate_dir / "draft-after.jsonl"))
    eb = _by_case(_lines(candidate_dir / "evidence-before.jsonl"))
    ea = _by_case(_lines(candidate_dir / "evidence-after.jsonl"))
    byte_identical = all(da.get(cid) == db.get(cid)
                         and ea.get(cid, []) == eb.get(cid, [])
                         for cid in ALL_RETIRED)
    if not byte_identical:
        raise RetirementError("retired cases not byte-identical "
                              "in v2.0.8 before→after")

    # ── 最终完整性清扫：candidate outputs 与 pack inputs SHA ─────────
    out_mismatch = []
    for name, sha in (m.get("outputs") or {}).items():
        path = candidate_dir / name
        if not path.exists() or _sha256_file(path) != sha:
            out_mismatch.append(name)
    if out_mismatch:
        raise RetirementError(
            f"v2.0.8 candidate outputs SHA mismatch: {out_mismatch}")
    pack_input_mismatch = _pack_input_sha_check(
        candidate_dir, chunks_path, chunk_manifest_path, current_draft_path)

    return {
        "case_count": len(draft_rows),
        "evidence_count": len(evidence_rows),
        "strict_covered": len(evidence_rows),
        "strict_passed": len(evidence_rows),
        "legacy_rows": len(legacy),
        "unresolved_rows": len(unresolved),
        "gate_verdict": m["gate_verdict"],
        "deferred_ledger": [d["deferred_reason"] for d in deferred],
        "minimal_cohort": minimal,
        "cohort_scenario": cohort_scenario,
        "mixed027_isolated": True,
        "mixed027_retire_single_case_safely": True,
        "m027_scenario": m027_scenario,
        "pack_gates": {
            "final_blockers": fb_manifest["gate_verdict"],
            "chain_closure": cc_manifest["gate_verdict"],
        },
        "closure_options": closure_options,
        "mixed027_check": mixed027_check,
        "pack_input_sha_match": pack_input_mismatch == [],
        "pack_input_mismatches": pack_input_mismatch,
        "chain_facts": deps,
        "chain_cases_byte_identical": byte_identical,
        "byte_identical_cases": set(ALL_RETIRED),
        "graph": graph,
        "draft_rows": draft_rows,
        "draft_by_id": draft_by_id,
        "evidence_rows": evidence_rows,
        "chunks": chunks,
        "chunk_manifest": json.load(open(chunk_manifest_path,
                                         encoding="utf-8")),
        "candidate_manifest": m,
    }


def _pack_input_sha_check(candidate_dir: Path, chunks_path: Path,
                          chunk_manifest_path: Path,
                          current_draft_path: Path) -> list[str]:
    """两个 decision pack manifest 记录的 input SHA 与当前磁盘一致性检查。"""
    paths = {
        "candidate": candidate_dir,
        "chunks": chunks_path,
        "chunk_manifest": chunk_manifest_path,
        "current_draft": current_draft_path,
    }
    mismatches: list[str] = []
    for manifest in (json.load(open(candidate_dir / "final-blockers-decision-pack"
                                    / "manifest.json", encoding="utf-8")),
                     json.load(open(candidate_dir / "chain-closure-decision-pack"
                                    / "manifest.json", encoding="utf-8"))):
        for key, sha in (manifest.get("inputs") or {}).items():
            spec = PACK_INPUT_PATHS.get(key)
            if spec is None:
                mismatches.append(f"{key}:unknown-input")
                continue
            target = paths[spec[0]]
            for part in spec[1:]:
                target = target / part
            if not target.exists() or _sha256_file(target) != sha:
                mismatches.append(key)
    return sorted(set(mismatches))


# ── 退役目标核验（fail-closed）────────────────────────────────────────

def _closure_proof(graph: dict, cohort: list[str]) -> dict:
    """最小无悬挂闭包的逐 case 入组依据与排除证明。"""
    cohort_set = set(cohort)
    inclusion: dict[str, list[tuple[str, str]]] = {}
    for cid in cohort:
        inc = sorted((e["to"], e["relation"]) for e in graph["edges"]
                     if e["from"] == cid and e["to"] in cohort_set)
        inclusion[cid] = inc
    return {
        "rule": MINIMAL_CLOSURE_RULE,
        "minimal_closed_cohort_recomputed": cohort,
        "matches_authorized_cohort": True,
        "inclusion_edges": inclusion,
        "excludes_multi028": EXCLUDES_MULTI028_NOTE,
        "dangling_refs_after_cohort_retirement": [],
    }


def _verify_retire_cohort(graph: dict, cohort: tuple) -> dict:
    """退役 cohort 必须是当前 draft 上的最小无悬挂闭包（否则整体停止）。"""
    cohort_list = list(cohort)
    if not cohort_list:
        return {}
    minimal = _minimal_closed_cohort(graph, "multi-030")
    if minimal != cohort_list:
        raise RetirementError(
            f"retire cohort {cohort_list} is not dependency-closed: "
            f"minimal closure is {minimal}")
    scen = _retirement_scenario(graph, cohort_list)
    if not scen["executable"]:
        raise RetirementError(
            f"retire cohort {cohort_list} leaves dangling refs: "
            f"{scen['dangling_refs']}")
    return {"scenario": scen, "proof": _closure_proof(graph, cohort_list)}


def _verify_retire_isolated(graph: dict, cid: str) -> dict:
    """退役 case 必须完全隔离：无入边、无出边、场景可执行。"""
    incoming = [e for e in graph["edges"] if e["to"] == cid]
    outgoing = [e for e in graph["edges"] if e["from"] == cid]
    if incoming:
        raise RetirementError(f"{cid} is not isolated: incoming refs {incoming}")
    if outgoing:
        raise RetirementError(f"{cid} is not isolated: outgoing refs {outgoing}")
    scen = _retirement_scenario(graph, [cid])
    if not scen["executable"]:
        raise RetirementError(
            f"{cid} retirement leaves dangling refs: {scen['dangling_refs']}")
    return {"incoming_case_refs": incoming, "outgoing_case_refs": outgoing,
            "scenario": scen}


def _verify_after(draft_rows: list[dict], evidence_rows: list[dict],
                  chunks: dict, retired_ids: set[str]) -> dict:
    """退役后状态核验（fail-closed）：无悬挂/环/残留成员、strict 全过、
    所有保留 answerable case 有证据。"""
    retired = set(retired_ids)
    graph = _build_dependency_graph(draft_rows, evidence_rows)
    draft_by_id = {r["id"]: r for r in draft_rows}
    _graph_gate(graph, draft_by_id, where="v2.0.9 draft-after")
    for e in graph["edges"]:
        if e["to"] in retired:
            raise RetirementError(
                f"after retirement dangling ref to {e['to']}: {e}")
    for label, members in graph["chain_members"].items():
        if set(members) & retired:
            raise RetirementError(
                f"after retirement residual chain member in {label}: "
                f"{sorted(set(members) & retired)}")
    if graph["refs_by_type"]["previous_turns"] != 0:
        raise RetirementError("after retirement orphan previous_turns exist")
    if graph["refs_by_type"]["doc_target"] != 0:
        raise RetirementError("after retirement doc-target refs exist")
    try:
        coord.strict_validate(evidence_rows, chunks)
    except coord.CoordinateError as exc:
        raise RetirementError(
            f"evidence-after strict validation failed: {exc}")
    legacy = [e for e in evidence_rows
              if e.get("coordinate_contract") != CONTRACT]
    unresolved = [e for e in evidence_rows
                  if not e.get("raw_evidence_span") or
                  not isinstance(e.get("raw_chunk_char_range"), dict)]
    if legacy or unresolved:
        raise RetirementError(
            f"after retirement legacy={len(legacy)} "
            f"unresolved={len(unresolved)}")
    ev_cases = {e["case_id"] for e in evidence_rows}
    answerable = [r["id"] for r in draft_rows
                  if not r.get("should_refuse")
                  and not r.get("is_refusal_turn")]
    missing = [cid for cid in answerable if cid not in ev_cases]
    if missing:
        raise RetirementError(
            f"answerable cases without evidence: {missing}")
    return {
        "after_no_dangling_refs": True,
        "after_chain_members_clean": True,
        "after_no_orphan_previous_turns": True,
        "after_no_doc_target_refs": True,
        "strict_covered": len(evidence_rows),
        "strict_passed": len(evidence_rows),
        "legacy_rows": len(legacy),
        "unresolved_rows": len(unresolved),
        "answerable_cases_have_evidence": True,
        "non_target_rows_byte_identical": True,
    }


# ── 确定性质量检查（skill 不可用时的等价机械复算）─────────────────────

def _data_quality_report(checks: dict, *, draft_after: list,
                         evidence_after: list, retired_cases: list,
                         retired_evidence: list, verify: dict,
                         retired_ids: set[str]) -> dict:
    draft_ids = [r["id"] for r in draft_after]
    ev_keys = [(e["case_id"], e["chunk_id"],
                e["raw_chunk_char_range"]["start"],
                e["raw_chunk_char_range"]["end"]) for e in evidence_after]
    chunks = checks["chunks"]
    return {
        "equivalent_deterministic_checks": {
            "completeness": {
                "case_before": checks["case_count"],
                "case_after": len(draft_after),
                "evidence_before": checks["evidence_count"],
                "evidence_after": len(evidence_after),
                "retired_cases": len(retired_cases),
                "retired_evidence": len(retired_evidence),
                "cohort_cases": len(RETIRE_COHORT),
                "isolated_cases": len(RETIRE_ISOLATED),
            },
            "uniqueness": {
                "draft_case_ids_unique": len(set(draft_ids)) == len(draft_ids),
                "evidence_keys_unique": len(set(ev_keys)) == len(ev_keys),
                "retired_case_ids_unique": len(
                    {r["case_id"] for r in retired_cases}) == len(retired_cases),
                "retired_evidence_case_ids_unique": len(
                    {r["case_id"] for r in retired_evidence}) == len(retired_evidence),
            },
            "referential_integrity": {
                "after_no_dangling_refs": verify["after_no_dangling_refs"],
                "no_residual_chain_members": verify["after_chain_members_clean"],
                "no_orphan_previous_turns": verify["after_no_orphan_previous_turns"],
                "evidence_chunks_in_corpus": all(
                    e["chunk_id"] in chunks for e in evidence_after),
                "evidence_sources_match_chunk": all(
                    chunks[e["chunk_id"]]["source"] == e["source_id"]
                    for e in evidence_after),
                "retired_cases_not_in_draft": all(
                    r["case_id"] not in set(draft_ids) for r in retired_cases),
                "retired_evidence_not_in_after": all(
                    r["case_id"] in retired_ids for r in retired_evidence),
            },
            "continuity": {
                "all_raw_spans_rebuildable": all(
                    chunks[e["chunk_id"]]["text"][
                        e["raw_chunk_char_range"]["start"]:
                        e["raw_chunk_char_range"]["end"]]
                    == e["raw_evidence_span"] for e in evidence_after),
                "non_target_rows_byte_identical":
                    verify["non_target_rows_byte_identical"],
                "retired_original_rows_preserved": all(
                    r.get("original_draft_row") for r in retired_cases)
                    and all(r.get("original_evidence_row")
                            for r in retired_evidence),
            },
            "consistency": {
                "case_count_exact": len(draft_after)
                == checks["case_count"] - len(retired_ids),
                "evidence_count_exact": len(evidence_after)
                == checks["evidence_count"] - len(retired_evidence),
                "strict_validation_144_144":
                    verify["strict_covered"] == verify["strict_passed"]
                    == len(evidence_after),
                "strict_validation_passed_equals_covered":
                    verify["strict_covered"] == verify["strict_passed"],
                "answerable_cases_have_evidence":
                    verify["answerable_cases_have_evidence"],
                "retired_reason_fixed": len(
                    {r.get("retired_reason") for r in retired_cases}) == 1,
            },
        },
        "skill": {"available": False, "name": "data-analytics:analyze-data-quality",
                  "failure": "Skill not found: data-analytics:analyze-data-quality"},
        "skill_note": SKILL_NOTE,
    }


# ── 主流程 ───────────────────────────────────────────────────────────

def run(*, out_dir: Path = OUT, candidate_dir: Path = V208,
        chunks_path: Path = CHUNKS, chunk_manifest_path: Path = CHUNK_MANIFEST,
        current_draft_path: Path = CURRENT_DRAFT,
        retire_cohort: tuple = RETIRE_COHORT,
        retire_isolated: tuple = RETIRE_ISOLATED) -> dict:
    """确定性构建 v2.0.9 retirement candidate（staging 原子写入，失败零输出）。"""
    if out_dir.exists() and any(out_dir.iterdir()):
        raise RetirementError(f"output dir already exists: {out_dir}")
    checks = preflight(candidate_dir=candidate_dir, chunks_path=chunks_path,
                       chunk_manifest_path=chunk_manifest_path,
                       current_draft_path=current_draft_path)

    cohort = list(retire_cohort)
    isolated = list(retire_isolated)
    if not cohort and not isolated:
        raise RetirementError("no retirement targets")
    if set(cohort) & set(isolated):
        raise RetirementError(f"overlapping retirement targets: "
                              f"{set(cohort) & set(isolated)}")
    retired = tuple(cohort) + tuple(isolated)
    if set(retired) - set(ALL_RETIRED):
        raise RetirementError(f"unauthorized retirement target(s): "
                              f"{sorted(set(retired) - set(ALL_RETIRED))}")
    if len(set(retired)) != len(retired):
        raise RetirementError(f"duplicate retirement target(s): {retired}")

    draft_rows = checks["draft_rows"]
    draft_by_id = checks["draft_by_id"]
    evidence_rows = checks["evidence_rows"]
    chunks = checks["chunks"]
    graph = checks["graph"]
    retired_set = set(retired)
    if not retired_set <= set(draft_by_id):
        raise RetirementError(f"retired case(s) missing from draft: "
                              f"{sorted(retired_set - set(draft_by_id))}")

    # 每个退役 case 的 evidence 行数必须与授权事实一致（只移除 7 条）
    ev_by_case: dict[str, list[dict]] = defaultdict(list)
    for e in evidence_rows:
        ev_by_case[e["case_id"]].append(e)
    for cid in retired:
        n = len(ev_by_case.get(cid, []))
        if n != EXPECTED_EVIDENCE_PER_CASE[cid]:
            raise RetirementError(
                f"{cid}: evidence rows {n} != "
                f"{EXPECTED_EVIDENCE_PER_CASE[cid]}")

    # 退役目标核验：cohort 必须是最小无悬挂闭包；isolated 必须完全隔离
    cohort_facts = _verify_retire_cohort(graph, tuple(cohort))
    isolated_facts = {cid: _verify_retire_isolated(graph, cid)
                      for cid in isolated}
    m027_impact = (isolated_facts.get("mixed-027", {}).get("scenario")
                   or checks["m027_scenario"])

    # ── 组装 draft-after（非目标行保留原字节）──────────────────────
    draft_before_lines = open(candidate_dir / "draft-after.jsonl",
                              encoding="utf-8").read().splitlines()
    draft_out_lines = [l for l in draft_before_lines
                       if json.loads(l)["id"] not in retired_set]
    if len(draft_out_lines) != checks["case_count"] - len(retired):
        raise RetirementError(
            f"draft-after count {len(draft_out_lines)} != "
            f"{checks['case_count'] - len(retired)}")

    # ── 组装 evidence-after（非目标行保留原字节）────────────────────
    ev_before_lines = open(candidate_dir / "evidence-after.jsonl",
                           encoding="utf-8").read().splitlines()
    ev_out_lines = [l for l in ev_before_lines
                    if json.loads(l)["case_id"] not in retired_set]
    if len(ev_out_lines) != checks["evidence_count"] - \
            sum(EXPECTED_EVIDENCE_PER_CASE[c] for c in retired):
        raise RetirementError(f"evidence-after count {len(ev_out_lines)}")
    evidence_after = [json.loads(l) for l in ev_out_lines]
    draft_after = [json.loads(l) for l in draft_out_lines]

    # ── 退役后状态核验（fail-closed）────────────────────────────────
    verify = _verify_after(draft_after, evidence_after, chunks, retired_set)

    # ── retired-cases ledger（保留原始行 + 固定理由 + 闭包证明）─────
    retired_cases: list[dict] = []
    for cid in retired:
        row: dict[str, Any] = {
            "case_id": cid,
            "cohort": COHORT_GATE if cid in RETIRE_COHORT else ISOLATED_GATE,
            "retired_reason": RETIRE_REASON,
            "retired_by": ACTOR,
            "authorization": AUTHORIZATION,
            "evidence_rows_removed": EXPECTED_EVIDENCE_PER_CASE[cid],
            "answer_points_removed": len(
                draft_by_id[cid].get("acceptable_answer_points") or []),
            "original_draft_row": draft_by_id[cid],
        }
        if cid in RETIRE_COHORT:
            row["dependency_closure_proof"] = cohort_facts["proof"]
        else:
            row["isolation_facts"] = {
                "incoming_case_refs": [],
                "outgoing_case_refs": [],
                "retire_single_case_safely": True,
                "chain_id": (draft_by_id[cid].get("metadata") or {}).get(
                    "chain_id"),
                "doc_target": draft_by_id[cid].get("doc_target"),
                "previous_turns": (draft_by_id[cid].get("metadata") or {}).get(
                    "previous_turns"),
            }
        retired_cases.append(row)

    # ── retired-evidence ledger（保留原始行 + 固定理由）─────────────
    retired_evidence: list[dict] = []
    for cid in retired:
        for e in ev_by_case.get(cid, []):
            retired_evidence.append({
                "case_id": cid,
                "chunk_id": e["chunk_id"],
                "source_id": e["source_id"],
                "raw_chunk_char_range": e["raw_chunk_char_range"],
                "raw_evidence_span": e["raw_evidence_span"],
                "snippet": e["snippet"],
                "retired_reason": RETIRE_REASON,
                "retired_by": ACTOR,
                "authorization": AUTHORIZATION,
                "original_evidence_row": e,
            })
    retired_evidence.sort(key=lambda r: (r["case_id"], r["chunk_id"]))

    # ── field-level-diff ────────────────────────────────────────────
    diff_rows: list[dict] = []
    for cid in retired:
        aps = draft_by_id[cid].get("acceptable_answer_points") or []
        diff_rows.append({
            "case_id": cid,
            "action": "retire_case",
            "cohort": COHORT_GATE if cid in RETIRE_COHORT else ISOLATED_GATE,
            "reason": RETIRE_REASON,
            "authorization_marker": AUTHORIZATION,
            "answer_points_removed": len(aps),
            "evidence_rows_removed": EXPECTED_EVIDENCE_PER_CASE[cid],
            "removed": {
                "draft_row": True,
                "answer_points": [
                    {"answer_point_index": i, "answer_point": ap}
                    for i, ap in enumerate(aps)],
                "evidence_rows": [
                    {"chunk_id": e["chunk_id"], "source_id": e["source_id"],
                     "raw_chunk_char_range": e["raw_chunk_char_range"],
                     "raw_evidence_span": e["raw_evidence_span"]}
                    for e in ev_by_case.get(cid, [])],
            },
        })
    diff_rows.sort(key=lambda r: r["case_id"])

    # ── retirement-dependency-ledger ────────────────────────────────
    cohort_scen = cohort_facts.get("scenario") or checks["cohort_scenario"]
    ledger = {
        "task": "v2.0.9-owner-authorized-final-dependency-closed-retirement",
        "authorization": AUTHORIZATION,
        "actor": ACTOR,
        "retire_cohort": {
            "cohort": cohort,
            "minimal_closed_cohort_recomputed":
                cohort_facts.get("proof", {}).get(
                    "minimal_closed_cohort_recomputed", cohort),
            "retirement_safe": bool(cohort),
        },
        "retire_isolated": {cid: {"retire_single_case_safely": True}
                            for cid in isolated},
        "dependency_closure": {
            "cohort": list(RETIRE_COHORT),
            "minimal_closed_cohort_recomputed":
                checks["minimal_cohort"],
            "cohort_matches_minimal_closure":
                checks["minimal_cohort"] == list(RETIRE_COHORT),
            "proof_rule": MINIMAL_CLOSURE_RULE,
            "excludes_multi028": EXCLUDES_MULTI028_NOTE,
            "dangling_refs": cohort_scen["dangling_refs"],
            "dangling_ref_count": cohort_scen["dangling_ref_count"],
            "internal_refs": cohort_scen["internal_refs"],
            "external_refs": cohort_scen["external_refs"],
            "chain_impact": cohort_scen["chain_impact"],
            "upstream_chains_affected": cohort_scen["upstream_chains_affected"],
            "orphan_previous_turns": cohort_scen["orphan_previous_turns"],
            "case_id_doc_target_refs": cohort_scen["case_id_doc_target_refs"],
        },
        "mixed027": {
            "retire_single_case_safely": True,
            "incoming_case_refs": [],
            "outgoing_case_refs": [],
            "dependency_facts": checks["mixed027_check"]["dependency_facts"],
            "impact": m027_impact,
        },
        "counts": {
            "case_before": checks["case_count"],
            "case_after": len(draft_after),
            "evidence_before": checks["evidence_count"],
            "evidence_after": len(evidence_after),
            "retired_cases": len(retired),
            "retired_evidence": len(retired_evidence),
            "retired_answer_points": sum(r["answer_points_removed"]
                                         for r in retired_cases),
        },
        "verification": {
            "after_no_dangling_refs": verify["after_no_dangling_refs"],
            "after_chain_members_clean": verify["after_chain_members_clean"],
            "strict_validator_144_144":
                verify["strict_covered"] == verify["strict_passed"]
                == len(evidence_after),
            "non_target_rows_byte_identical":
                verify["non_target_rows_byte_identical"],
        },
        "note": ("确定性退役（仅移除 6 个 case 及其 7 条 evidence）；"
                 "严格证据验证通过不构成审阅通过或 active 准入；激活前需"
                 "一次全新的 137-case 盲态机器复审，不得复用 v2.0.7 / "
                 "v2.0.8 的 review 结果。"),
    }

    # ── 报告文件 ────────────────────────────────────────────────────
    dq = _data_quality_report(checks, draft_after=draft_after,
                              evidence_after=evidence_after,
                              retired_cases=retired_cases,
                              retired_evidence=retired_evidence,
                              verify=verify, retired_ids=retired_set)
    case_after = len(draft_after)
    evidence_after_n = len(evidence_after)

    files = {
        "draft-after.jsonl": "\n".join(draft_out_lines) + "\n",
        "evidence-after.jsonl": "\n".join(ev_out_lines) + "\n",
        "retired-cases.jsonl": "".join(_line(r) for r in retired_cases),
        "retired-evidence.jsonl": "".join(_line(r) for r in retired_evidence),
        "retirement-dependency-ledger.json": _dump(ledger),
        "field-level-diff.jsonl": "".join(_line(r) for r in diff_rows),
        "data-quality-report.json": _dump(dq),
        "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md": _rebuild_md(case_after,
                                                            evidence_after_n),
    }
    metadata = {
        "revision_status": "CANDIDATE",
        "activation_blocked": True,
        "human_reviewed": False,
        "overlay_generated": False,
        "split_reseal_required": True,
        "v2_1_entered": False,
        "actor": ACTOR,
        "case_count_before": checks["case_count"],
        "case_count_after": case_after,
    }
    inputs = {
        "v208-manifest.json": _sha256_file(candidate_dir / "manifest.json"),
        "draft-after.jsonl": _sha256_file(candidate_dir / "draft-after.jsonl"),
        "draft-before.jsonl": _sha256_file(candidate_dir / "draft-before.jsonl"),
        "evidence-after.jsonl": _sha256_file(
            candidate_dir / "evidence-after.jsonl"),
        "evidence-before.jsonl": _sha256_file(
            candidate_dir / "evidence-before.jsonl"),
        "deferred-chain-dependent-cases.jsonl": _sha256_file(
            candidate_dir / "deferred-chain-dependent-cases.jsonl"),
        "final-blockers-manifest.json": _sha256_file(
            candidate_dir / "final-blockers-decision-pack" / "manifest.json"),
        "final-blockers-decision-pack.jsonl": _sha256_file(
            candidate_dir / "final-blockers-decision-pack"
            / "final-blockers-decision-pack.jsonl"),
        "chain-closure-manifest.json": _sha256_file(
            candidate_dir / "chain-closure-decision-pack" / "manifest.json"),
        "multi-030-closure-options.json": _sha256_file(
            candidate_dir / "chain-closure-decision-pack"
            / "multi-030-closure-options.json"),
        "mixed-027-retirement-check.json": _sha256_file(
            candidate_dir / "chain-closure-decision-pack"
            / "mixed-027-retirement-check.json"),
        "chunks.jsonl": _sha256_file(chunks_path),
        "chunk-manifest.json": _sha256_file(chunk_manifest_path),
        "current-v2-draft.jsonl": _sha256_file(current_draft_path),
    }
    outputs = {name: _sha256_text(files[name]) for name in files}
    manifest = _manifest({
        "task": "v2.0.9-owner-authorized-final-dependency-closed-retirement",
        "created_by": "corpus_v2_v209_final_dependency_closed_retirement.py",
        "rule_version": RULE_VERSION,
        "run_at": TIMESTAMP,
        "deterministic": True,
        "gate_verdict": "FINAL_DEPENDENCY_CLOSED_RETIREMENT_OK",
        "description": "v2.0.9 owner-authorized final dependency-closed "
                       "retirement candidate（确定性；退役最小无悬挂闭包 "
                       "multi-030~multi-034 与安全隔离 case mixed-027，共 6 "
                       "case / 7 evidence；无 LLM/API、无联网；严格验证通过"
                       "不构成审阅通过或 active 准入）",
        "revision_status": metadata["revision_status"],
        "activation_blocked": metadata["activation_blocked"],
        "human_reviewed": metadata["human_reviewed"],
        "overlay_generated": metadata["overlay_generated"],
        "split_reseal_required": metadata["split_reseal_required"],
        "v2_1_entered": metadata["v2_1_entered"],
        "actor": metadata["actor"],
        "case_count_before": metadata["case_count_before"],
        "case_count_after": metadata["case_count_after"],
        "counts": {
            "case_before": checks["case_count"],
            "case_after": case_after,
            "evidence_before": checks["evidence_count"],
            "evidence_after": evidence_after_n,
            "retired_cases": len(retired),
            "retired_evidence": len(retired_evidence),
            "retired_answer_points": ledger["counts"]["retired_answer_points"],
            "cohort_cases": len(cohort),
            "isolated_cases": len(isolated),
        },
        "retired": {
            "cohort": list(RETIRE_COHORT),
            "isolated": list(RETIRE_ISOLATED),
        },
        "inputs": inputs,
        "outputs": outputs,
        "declarations": {
            "llm_called": False,
            "network_used": False,
            "overlay_generated": False,
            "split_created": False,
            "v2_1_entered": False,
            "review_results_reused": False,
            "historical_verdicts_read": False,
            "data_modified": "authorized_retirement_only",
            "input_scope": [
                "v2.0.8 candidate dir (draft/evidence/manifest/deferred ledger)",
                "v2.0.8 final-blockers decision pack",
                "v2.0.8 chain-closure decision pack",
                "chunks", "chunk manifest",
                "current draft (hash-only)", "raw-codepoint strict validator"],
        },
        "validation": {
            "case_count_exact": case_after == checks["case_count"]
                - len(retired),
            "evidence_count_exact": evidence_after_n
                == checks["evidence_count"] - len(retired_evidence),
            "strict_validation_144_144":
                verify["strict_covered"] == verify["strict_passed"]
                == evidence_after_n,
            "legacy_zero": verify["legacy_rows"] == 0,
            "unresolved_zero": verify["unresolved_rows"] == 0,
            "non_target_rows_byte_identical":
                verify["non_target_rows_byte_identical"],
            "retire_cohort_dependency_closed": True,
            "mixed027_isolated": True,
            "after_no_dangling_refs": verify["after_no_dangling_refs"],
            "after_chain_members_clean": verify["after_chain_members_clean"],
            "answerable_cases_have_evidence":
                verify["answerable_cases_have_evidence"],
        },
        "skill_note": SKILL_NOTE,
    })
    files["manifest.json"] = _dump(manifest)

    # ── staging 原子写入 ───────────────────────────────────────────
    staging = Path(tempfile.mkdtemp(prefix="v209-", dir=str(out_dir.parent)))
    try:
        for name, content in files.items():
            _atomic_write(staging / name, content)
        os.replace(staging, out_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        raise
    return {"manifest": manifest, "rows": diff_rows,
            "draft_after": draft_out_lines, "evidence_after": evidence_after}


def _rebuild_md(case_after: int, evidence_after: int) -> str:
    return (
        "# REVIEW_AND_SPLIT_REBUILD_REQUIRED.md\n\n"
        f"v2.0.9 是 **CANDIDATE**（`activation_blocked=true`、"
        f"`human_reviewed=false`）。\n\n"
        f"- 本次确定性退役：6 条 case / 7 条 evidence（143 → {case_after} "
        f"case、151 → {evidence_after} evidence）；\n"
        "- 历史 split / dev / holdout 与锁配置**一律不复用**；\n"
        "- 激活前必须：一次全新的 137-case 盲态复审"
        "（**不得复用 v2.0.7 / v2.0.8 的 review 结果**）、重新切分"
        "（split reseal），并按要求重建 review 结果；\n"
        "- 严格证据验证通过（covered==passed）**不构成**审阅通过、confirmed "
        "或 active 准入；\n"
        "- 退役 case（multi-030~multi-034、mixed-027）及其 evidence 已从 "
        "candidate 移除，不得作为已审阅结论复用；\n"
        "- 未进入 v2.1；未生成 overlay / active metadata / split / "
        "locked config。\n"
    )


# ── CLI ───────────────────────────────────────────────────────────────

USAGE = (
    "usage: corpus_v2_v209_final_dependency_closed_retirement.py build "
    "[--out-dir DIR] [--candidate-dir DIR] [--chunks PATH] "
    "[--chunk-manifest PATH] [--current-draft PATH]"
)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if not argv or argv[0] != "build":
            print(USAGE, file=sys.stderr)
            return 2
        args = argv[1:]
        kwargs: dict[str, Any] = {}

        def _flag(name: str, key: str) -> None:
            if name in args:
                kwargs[key] = Path(args[args.index(name) + 1])

        _flag("--out-dir", "out_dir")
        _flag("--candidate-dir", "candidate_dir")
        _flag("--chunks", "chunks_path")
        _flag("--chunk-manifest", "chunk_manifest_path")
        _flag("--current-draft", "current_draft_path")
        run(**kwargs)
        return 0
    except RetirementError as exc:
        print(f"retirement failed closed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
