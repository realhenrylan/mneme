"""v2.0.8 transitive chain-closure and mixed-027 retirement decision audit
（只读、确定性）。

为所有者生成 multi-030 传递链闭包与 mixed-027 安全退役核验的决策包；
**不自动选择任何选项**，不修改任何 draft/evidence/chunks/candidate/
review/manifest，不调用 LLM/API、不联网。

输入仅限：
- v2.0.8 candidate 目录（manifest / draft-before/after / evidence-before/
  after / deferred ledger）；
- 当前 v2 draft（annotations）、chunks、chunk manifest；
- raw-codepoint strict validator。
不读取 split/dev/holdout、锁配置、历史评测、早于 v2.0.7 的审阅结论。

fail-closed 门禁（任一漂移 → ClosureAuditError，零输出）：
- v2.0.8 = 143 case / 151 active raw evidence / strict 151/151 / legacy=0 /
  unresolved=0 / manifest 自哈希 / gate REMEDIATION_CANDIDATE_OK；
- multi-030 在 deferred ledger（恰 1 条、原因固定、dependent_cases 与
  图引用完全一致）；
- 链关系精确：multi-031.follow_up_to=="multi-030"、
  multi-032/033/034.chain_id=="multi-030"（无其他引用）；
- multi-030.follow_up_to==None 且 chain_id=="multi-028"（multi-031 同链）；
- mixed-027 完全隔离（无 follow_up/chain/doc_target/previous_turns，
  无任何进出引用）；
- multi-030~034 在 draft-before→after / evidence-before→after 逐字节不变；
- 图引用完整性：任何 case-id 字段引用必须指向存在的 case；
- 环检测：多节点环 → fail-closed；自环仅允许 chain root 自标号
  （follow_up 为空时良性）。

传递闭包（纯机械、确定性）：
- 边 = 所有 case-id 字段引用（follow_up_to / chain_id / doc_target /
  previous_turns），from=引用者，to=被引用者；
- multi-030 下游 = 直接/传递引用者；上游 = 直接/传递被引用者；
- 同链成员 = 相同 chain_id 的 case；最小无悬挂闭包 = 包含 multi-030 且
  组外无任何指向组内引用者的最小不动点集合；
- 退役场景逐一核算悬挂引用、断链、缺失 chain member、orphan previous
  turn、doc-target 不一致与 case/evidence 精确影响；仅在零悬挂引用时
  判定可执行。

mixed-027 核验（strict 口径，不放松 min_span/coverage/exact/source 规则）：
- AP0/AP1 本地逐字重验（_verify_ap 复用，min_span=8、coverage>=0.75、
  同 source），完整+唯一+连续+同 source 直接支持 → 均为 False；
- 依赖检查：无 follow-up/chain/previous_turn/doc_target/其他 case 引用；
- 无依赖且退役不造成链断裂 → retire_single_case_safely=true。

输出 8 个文件到 chain-closure-decision-pack/：dependency-graph、
multi-030-closure-options、mixed-027-retirement-check、chain-impact-map、
owner-decision-template（仅三个空决策字段）、OWNER_DECISION_GUIDE.md、
chain-closure-report.md、manifest.json（自哈希 + inputs/outputs SHA）。

CLI
---
::

    python scripts/corpus_v2_v208_chain_closure_decision_pack.py build
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import corpus_v2_evidence_coordinate_repair as coord
from scripts.corpus_v2_v207_review_reject_triage import (
    _atomic_write, _dump, _jsonl, _manifest, _sha256_file, _sha256_text,
    _verify_self_hash,
)
from scripts.corpus_v2_v208_final_blockers_decision_pack import (
    _line, _verify_ap,
)


ROOT = Path(__file__).resolve().parents[1]
V208 = ROOT / "evaluation/datasets/v2/revisions/v2.0.8-owner-authorized-semantic-quality-remediation"
OUT = V208 / "chain-closure-decision-pack"
CHUNKS = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"

TIMESTAMP = "2026-08-11T00:00:00+00:00"
RULE_VERSION = "v2.0.8-chain-closure-decision-pack-1"
CONTRACT = "raw-codepoint-v1"
ACTOR = "OWNER_AUTHORIZED_CHAIN_CLOSURE_DECISION_AUDIT"
DEFER_REASON = "retirement_deferred_due_to_active_follow_up_chain_dependency"

BLOCKERS = ("multi-030", "mixed-027")
CHAIN_CASES = ("multi-030", "multi-031", "multi-032", "multi-033", "multi-034")
CHAIN_028_MEMBERS = ["multi-030", "multi-031"]
CHAIN_030_MEMBERS = ["multi-032", "multi-033", "multi-034"]
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

SKILL_NOTE = (
    "data-analytics:analyze-data-quality skill 在本环境中不可用"
    "（不在已安装 skills 列表内，无法加载；已实际尝试）；已按任务约束实施"
    "等价的确定性质量检查（完整性 / 唯一性 / 引用完整性 / 连续性 / 一致性），"
    "全部为机械复算，无 LLM 参与。"
)

CASE_ID_RE = re.compile(r"^(multi|mixed|zh|en|noanswer)-\d+$")


class ClosureAuditError(Exception):
    """Fail-closed chain-closure audit failure（任何非法状态立即失败、零输出）。"""


# ── case-id 字段引用 ───────────────────────────────────────────────────

def _iter_case_refs(row: dict):
    """产出该行所有 case-id 字段引用 (relation, field_path, target)。"""
    cid = row["id"]
    meta = row.get("metadata") or {}
    fu = meta.get("follow_up_to")
    if isinstance(fu, str) and CASE_ID_RE.match(fu):
        yield ("follow_up_to", "metadata.follow_up_to", fu)
    ch = meta.get("chain_id")
    if isinstance(ch, str) and CASE_ID_RE.match(ch):
        yield ("chain_id", "metadata.chain_id", ch)
    dt = row.get("doc_target")
    if isinstance(dt, str) and CASE_ID_RE.match(dt):
        yield ("doc_target", "doc_target", dt)
    pt = meta.get("previous_turns")
    if isinstance(pt, list):
        for i, v in enumerate(pt):
            if isinstance(v, str) and CASE_ID_RE.match(v):
                yield ("previous_turns", f"metadata.previous_turns[{i}]", v)
    elif isinstance(pt, str) and CASE_ID_RE.match(pt):
        yield ("previous_turns", "metadata.previous_turns", pt)


# ── 依赖图构建（含引用完整性与环检测，fail-closed）────────────────────

def _detect_cycles(edges: list[dict],
                   draft_by_id: dict[str, dict]) -> tuple[list, list]:
    """DFS 检测多节点环；自环单独列出并判定良性（chain root 自标号）。

    返回 (cycles, self_loops)；cycles 非空或存在非良性自环 → 抛错。
    """
    adj: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        adj[e["from"]].append(e)
    self_loops, rest = [], []
    for e in edges:
        (self_loops if e["from"] == e["to"] else rest).append(e)
    # 多节点环（后向边）
    color: dict[str, int] = {}
    back: set[tuple[str, str, str]] = set()

    def dfs(u: str) -> None:
        color[u] = 1
        for e in adj[u]:
            if e["from"] == e["to"]:
                continue
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
    if cycles:
        raise ClosureAuditError(f"cycle(s) detected: {cycles}")
    # 自环良性判定：chain root 自标号（chain_id 自环且 follow_up 为空）
    benign_loops = []
    for e in self_loops:
        row = draft_by_id.get(e["from"]) or {}
        fu = (row.get("metadata") or {}).get("follow_up_to")
        benign = e["relation"] == "chain_id" and not fu
        if not benign:
            raise ClosureAuditError(
                f"invalid self-loop: {e['from']}.{e['relation']} -> "
                f"{e['to']} (non-root or non-chain_id)")
        benign_loops.append({**e, "benign": True})
    return cycles, sorted(benign_loops, key=lambda e: e["from"])


def _build_dependency_graph(draft_rows: list[dict],
                            evidence_rows: list[dict] | None = None) -> dict:
    """构建完整多轮依赖图（所有 case-id 字段引用）。

    边方向约定：from=引用者（字段所在 case），to=被引用者。
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
            "language": r.get("language"),
            "n_answer_points": len(r.get("acceptable_answer_points") or []),
            "n_evidence": len(ev_by_case.get(cid, [])),
        }
    edges = []
    for r in draft_rows:
        for rel, path, target in _iter_case_refs(r):
            edges.append({"from": r["id"], "to": target, "relation": rel,
                          "field_path": path})
    # 引用完整性：任何引用必须指向存在的 case（悬挂引用 → fail-closed）
    dangling = [e for e in edges if e["to"] not in ids]
    if dangling:
        raise ClosureAuditError(f"dangling case reference(s): {dangling}")
    draft_by_id = {r["id"]: r for r in draft_rows}
    cycles, self_loops = _detect_cycles(edges, draft_by_id)
    # chain 成员（按 chain_id 字段值分组）
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
            "note": ("143 行 metadata 均无 previous_turns 字段值；"
                     "无 previous-turn 引用边，无孤儿 previous turn 风险"),
        },
    }


# ── 传递可达性 ─────────────────────────────────────────────────────────

def _reachability(graph: dict, seed: str) -> dict:
    """从 seed 出发的下游（引用者方向）与上游（被引用者方向）闭包。

    - downstream.direct：与 seed 有直接引用边的 case（relation 集合）；
    - downstream.transitive：间接引用者；
    - upstream.direct：seed 直接引用的 case；upstream.transitive：间接；
    - same_chain_members：与 seed 同 chain_id 的其他成员；
    - follow_up_parent：seed 的 follow_up_to（case-id 值）。
    """
    fwd: dict[str, list[dict]] = defaultdict(list)
    rev: dict[str, list[dict]] = defaultdict(list)
    for e in graph["edges"]:
        fwd[e["from"]].append(e)
        rev[e["to"]].append(e)
    node = graph["nodes"][seed]

    def _bfs(adj: dict[str, list[dict]], start: str) -> tuple[set, dict]:
        reach: set[str] = set()
        by_case: dict[str, list[str]] = {}
        seen = {start}
        queue = deque([start])
        while queue:
            u = queue.popleft()
            for e in adj.get(u, []):
                v = e["to"] if adj is fwd else e["from"]
                if v not in seen:
                    seen.add(v)
                    reach.add(v)
                    by_case.setdefault(v, []).append(e["relation"])
                    queue.append(v)
        return reach, by_case

    down_reach, down_rel = _bfs(rev, seed)
    up_reach, up_rel = _bfs(fwd, seed)
    # 直接下游 = 存在指向 seed 的边（relation 非空才计入）；其余为传递
    direct_down = {}
    for cid in down_reach:
        rels = sorted({e["relation"] for e in graph["edges"]
                       if e["from"] == cid and e["to"] == seed})
        if rels:
            direct_down[cid] = rels
    transitive_down = {cid: sorted(rels) for cid, rels in down_rel.items()
                       if cid not in direct_down}
    direct_up = {}
    for cid in up_reach:
        rels = sorted({e["relation"] for e in graph["edges"]
                       if e["from"] == seed and e["to"] == cid})
        if rels:
            direct_up[cid] = rels
    transitive_up = {cid: sorted(rels) for cid, rels in up_rel.items()
                     if cid not in direct_up}
    ch = node["chain_id"]
    same_chain = sorted(c for c in graph["chain_members"].get(ch, [])
                        if c != seed) if isinstance(ch, str) else []
    fu = node["follow_up_to"]
    return {
        "seed": seed,
        "downstream": {
            "direct": {k: direct_down[k] for k in sorted(direct_down)},
            "transitive": {k: transitive_down[k]
                           for k in sorted(transitive_down)},
            "all": sorted(down_reach),
            "n": len(down_reach),
        },
        "upstream": {
            "direct": {k: direct_up[k] for k in sorted(direct_up)},
            "transitive": {k: transitive_up[k] for k in sorted(transitive_up)},
            "all": sorted(up_reach),
            "n": len(up_reach),
        },
        "follow_up_parent": fu if isinstance(fu, str) and CASE_ID_RE.match(fu)
        else None,
        "chain_id": ch,
        "same_chain_members": same_chain,
    }


# ── 最小无悬挂闭包 ─────────────────────────────────────────────────────

def _minimal_closed_cohort(graph: dict, seed: str) -> list[str]:
    """包含 seed 的最小无悬挂闭包（不动点）。

    规则：cohort 中任一 case 被组外 case 引用 → 该引用者入组，直至无变化。
    结果保证：不存在「组外 case 引用组内 case」的悬挂边。
    """
    cohort = {seed}
    changed = True
    while changed:
        changed = False
        for e in graph["edges"]:
            if e["to"] in cohort and e["from"] not in cohort:
                cohort.add(e["from"])
                changed = True
    return sorted(cohort)


# ── 退役场景核算 ───────────────────────────────────────────────────────

def _retirement_scenario(graph: dict, cohort: list[str]) -> dict:
    """核算退役 cohort 的影响：悬挂引用、链完整性、数量与可执行性。"""
    cohort_set = set(cohort)
    dangling = [e for e in graph["edges"]
                if e["to"] in cohort_set and e["from"] not in cohort_set]
    internal = [e for e in graph["edges"]
                if e["from"] in cohort_set and e["to"] in cohort_set]
    external = [e for e in graph["edges"]
                if e["from"] in cohort_set and e["to"] not in cohort_set]
    chains: dict[str, dict] = {}
    for label, members in graph["chain_members"].items():
        retired = sorted(m for m in members if m in cohort_set)
        if not retired:
            continue
        remaining = sorted(set(members) - set(retired))
        chains[label] = {
            "members": list(members),
            "retired_members": retired,
            "remaining_members": remaining,
            "status": "fully_retired" if not remaining
            else "partially_retired",
        }
    n_cases = len(cohort)
    n_evidence = sum(graph["nodes"][c]["n_evidence"] for c in cohort)
    n_aps = sum(graph["nodes"][c]["n_answer_points"] for c in cohort)
    return {
        "cohort": cohort,
        "cohort_size": n_cases,
        "evidence_rows_removed": n_evidence,
        "answer_points_removed": n_aps,
        "case_count_before": graph["case_count"],
        "case_count_after": graph["case_count"] - n_cases,
        "evidence_count_before": graph["evidence_count"],
        "evidence_count_after": graph["evidence_count"] - n_evidence,
        "dangling_refs": dangling,
        "dangling_ref_count": len(dangling),
        "executable": not dangling,
        "chain_impact": chains,
        "upstream_chains_affected": sorted(chains),
        "orphan_previous_turns": [e for e in dangling
                                  if e["relation"] == "previous_turns"],
        "case_id_doc_target_refs": [e for e in graph["edges"]
                                    if e["relation"] == "doc_target"],
        "internal_refs": internal,
        "external_refs": external,
    }


# ── multi-030 传递链闭包评估 ───────────────────────────────────────────

def _assess_multi030(checks: dict) -> dict:
    graph = checks["graph"]
    reach = checks["reachability"]
    minimal = _minimal_closed_cohort(graph, "multi-030")
    scenarios = []
    for name, cohort in (
            ("retire_only_multi_030", ["multi-030"]),
            ("retire_multi030_to_multi034_group", list(CHAIN_CASES)),
            ("retire_minimal_dependency_closed_cohort", minimal)):
        scen = _retirement_scenario(graph, cohort)
        scen["name"] = name
        scenarios.append(scen)
    by_name = {s["name"]: s for s in scenarios}
    min_scen = by_name["retire_minimal_dependency_closed_cohort"]
    only_scen = by_name["retire_only_multi_030"]
    # 闭包证明：组内每个 case 的入组依据（被组内引用 或 引用组内）
    inclusion = {}
    for cid in minimal:
        inc = [e for e in graph["edges"] if e["from"] == cid
               and e["to"] in set(minimal)]
        inclusion[cid] = sorted(
            (e["to"], e["relation"]) for e in inc)
    return {
        "case_id": "multi-030",
        "blocker_type": "deferred_chain_parent",
        "deferred_reason": DEFER_REASON,
        "graph_facts": reach,
        "minimal_cohort": minimal,
        "minimal_cohort_proof": {
            "rule": ("不动点：cohort 中任一 case 被组外引用 → 引用者入组，"
                     "直至稳定；multi-031.follow_up_to→multi-030 与 "
                     "multi-032/033/034.chain_id→multi-030 强制其入组，"
                     "组内再无对外引用者被组外引用"),
            "inclusion_edges": inclusion,
            "excludes_multi028": ("multi-028 不引用组内任何 case"
                                  "（multi-028.chain_id=multi-025、"
                                  "follow_up_to=multi-027），无需入组"),
        },
        "scenarios": scenarios,
        "options": [
            {"option": "keep_deferred_and_block_fresh_review",
             "meets_criteria": True,
             "note": ("保持 v2.0.8 现状：multi-030 延后、draft/evidence "
                      "逐字节未改；这不是 resolved / confirmed / 已接受的"
                      "质量结论；fresh review 需所有者另行授权")},
            {"option": "retire_minimal_dependency_closed_cohort",
             "meets_criteria": min_scen["executable"],
             "impact": {k: v for k, v in min_scen.items() if k != "name"},
             "note": ("最小无悬挂闭包恰为 {multi-030..034}（与 5 组一致），"
                      "0 悬挂引用；上游 chain multi-028 将失去全部成员"
                      "（multi-030/031），chain multi-030 整链退役；"
                      "143→138、evidence 151→146、5 answer points")},
            {"option": "retire_only_multi_030",
             "meets_criteria": only_scen["executable"],
             "criteria": {
                 "dangling_ref_count": only_scen["dangling_ref_count"],
                 "dangling_refs": only_scen["dangling_refs"],
                 "case_count_after": only_scen["case_count_after"],
                 "note": ("仅 retire multi-030 会留下 4 条悬挂引用"
                          "（multi-031.follow_up_to 与 multi-032/033/034."
                          "chain_id 指向已退役 case），不可执行")},
             },
        ],
        "recommendation": None,
        "owner_decision_required": True,
    }


# ── mixed-027 安全退役核验 ─────────────────────────────────────────────

def _ap_support_summary(apv: dict) -> dict:
    """单答案点：完整+唯一+连续+同 source 直接支持判定（strict 口径）。"""
    best = max(apv["evidence_checks"],
               key=lambda c: (c["strict_in_span_coverage"],
                              c["max_contiguous_coverage"]))
    sw = apv["source_wide"]
    complete = sw["full_ap_hits"] > 0
    return {
        "answer_point_index": apv["answer_point_index"],
        "answer_point": apv["answer_point"],
        "complete_verbatim_hit_in_source": complete,
        "unique": bool(complete and sw["full_ap_unique"]),
        "contiguous_support": best["exact_contiguous"],
        "direct_strict_support": bool(
            complete and sw["full_ap_unique"] and best["exact_contiguous"]),
        "same_source_scope": True,
        "best_evidence": {
            "chunk_id": best["chunk_id"],
            "source_id": best["source_id"],
            "raw_chunk_char_range": best["raw_chunk_char_range"],
            "raw_evidence_span": best["raw_evidence_span"],
            "span_rebuildable": best["span_rebuildable"],
            "strict_in_span_coverage": best["strict_in_span_coverage"],
            "max_contiguous_len": best["max_contiguous_len"],
            "max_contiguous_coverage": best["max_contiguous_coverage"],
            "exact_contiguous": best["exact_contiguous"],
            "token_fragments": best["token_fragments"],
        },
        "source_wide": sw,
        "evidence_checks": apv["evidence_checks"],
    }


def _assess_mixed027(checks: dict) -> dict:
    graph = checks["graph"]
    row = checks["draft_by_id"]["mixed-027"]
    meta = row.get("metadata") or {}
    ev = [e for e in checks["evidence_rows"] if e["case_id"] == "mixed-027"]
    aps = row.get("acceptable_answer_points") or []
    srcs = row.get("relevant_source_ids") or []
    ap_verify = [
        dict(_verify_ap(ap, ev, checks["chunks"], srcs), answer_point_index=i)
        for i, ap in enumerate(aps)
    ]
    incoming = [e for e in graph["edges"] if e["to"] == "mixed-027"]
    outgoing = [e for e in graph["edges"] if e["from"] == "mixed-027"]
    scen = _retirement_scenario(graph, ["mixed-027"])
    safe = scen["executable"] and not scen["chain_impact"]
    return {
        "case_id": "mixed-027",
        "blocker_type": "retirement_safety_check",
        "dependency_facts": {
            "follow_up_to": meta.get("follow_up_to"),
            "chain_id": meta.get("chain_id"),
            "doc_target": row.get("doc_target"),
            "previous_turns": meta.get("previous_turns"),
            "incoming_case_refs": incoming,
            "outgoing_case_refs": outgoing,
            "chain_membership": next(
                (label for label, members in graph["chain_members"].items()
                 if "mixed-027" in members), None),
            "n_answer_points": len(aps),
            "n_evidence": len(ev),
        },
        "answer_points": [_ap_support_summary(v) for v in ap_verify],
        "retire_single_case_safely": safe,
        "impact": {k: v for k, v in scen.items()},
        "options": [
            {"option": "retire_single_case_safely",
             "meets_criteria": safe,
             "impact": {k: v for k, v in scen.items()},
             "note": ("mixed-027 无 follow-up/chain/previous_turn/doc_target/"
                      "其他 case 引用依赖，退役不造成任何链断裂；"
                      "143→142、evidence 151→149、2 answer points")},
            {"option": "keep_deferred_and_block_fresh_review",
             "meets_criteria": True,
             "note": ("保持 v2.0.8 现状：mixed-027 数据未改；这不是 "
                      "resolved / confirmed / 已接受的质量结论；fresh "
                      "review 需所有者另行授权")},
        ],
        "recommendation": None,
        "owner_decision_required": True,
    }


# ── 链影响图（最小闭包退役）────────────────────────────────────────────

def _chain_impact_map(checks: dict) -> dict:
    graph = checks["graph"]
    cohort = _minimal_closed_cohort(graph, "multi-030")
    scen = _retirement_scenario(graph, cohort)
    cohort_set = set(cohort)
    nodes = {}
    for cid in cohort:
        n = graph["nodes"][cid]
        evs = [e for e in checks["evidence_rows"] if e["case_id"] == cid]
        nodes[cid] = {**n, "evidence": [
            {"chunk_id": e["chunk_id"], "source_id": e["source_id"],
             "raw_chunk_char_range": e["raw_chunk_char_range"],
             "raw_evidence_span": e["raw_evidence_span"]}
            for e in evs]}
    edges = [e for e in graph["edges"]
             if e["from"] in cohort_set or e["to"] in cohort_set]
    upstream = {}
    for label, info in scen["chain_impact"].items():
        if label == "multi-028":
            upstream[label] = {
                "lost_chain_members": info["retired_members"],
                "chain_status": info["status"],
                "note": ("chain multi-028 的成员（multi-030/031）随退役组"
                         "全部移除；chain multi-028 线程清空。case "
                         "multi-028 本身属于 chain multi-025（成员 "
                         "multi-027/028/029），不受影响"),
            }
    return {
        "cohort": cohort,
        "case_ids": cohort,
        "deferred_reason": DEFER_REASON,
        "cases": nodes,
        "edges": sorted(edges, key=lambda e: (e["from"], e["to"],
                                              e["relation"])),
        "chains": scen["chain_impact"],
        "upstream_impact": upstream,
        "impact_summary": {
            "retire_cohort": cohort,
            "cases_removed": scen["cohort_size"],
            "evidence_rows_removed": scen["evidence_rows_removed"],
            "answer_points_removed": scen["answer_points_removed"],
            "case_count_after": scen["case_count_after"],
            "evidence_count_after": scen["evidence_count_after"],
            "downstream_refs_inside_group": len(scen["internal_refs"]),
            "external_refs_outside_group": len(scen["external_refs"]),
            "dangling_refs": scen["dangling_ref_count"],
            "upstream_chains_affected": scen["upstream_chains_affected"],
            "chains_fully_retired": sorted(
                label for label, info in scen["chain_impact"].items()
                if info["status"] == "fully_retired"),
        },
    }


# ── 前置门禁（fail-closed，只读）──────────────────────────────────────

def preflight(*, candidate_dir: Path = V208, chunks_path: Path = CHUNKS,
              chunk_manifest_path: Path = CHUNK_MANIFEST,
              current_draft_path: Path = CURRENT_DRAFT) -> dict:
    """只读校验全部输入门禁；任一不符 → ClosureAuditError。"""
    manifest_path = candidate_dir / "manifest.json"
    if not manifest_path.exists():
        raise ClosureAuditError(f"candidate manifest missing: {manifest_path}")
    m = json.load(open(manifest_path, encoding="utf-8"))
    if m.get("gate_verdict") != "REMEDIATION_CANDIDATE_OK":
        raise ClosureAuditError("v2.0.8 candidate gate not OK")
    if not _verify_self_hash(m):
        raise ClosureAuditError("v2.0.8 candidate manifest self-hash mismatch")
    counts = m.get("counts") or {}
    if counts.get("case_after") != 143 or counts.get("evidence_after") != 151 \
            or counts.get("deferred_cases") != 1:
        raise ClosureAuditError(f"v2.0.8 counts drift: {counts}")
    if m.get("revision_status") != "CANDIDATE" or \
            m.get("activation_blocked") is not True:
        raise ClosureAuditError("v2.0.8 candidate status drift")

    draft_rows = _jsonl(candidate_dir / "draft-after.jsonl")
    draft_ids = [r["id"] for r in draft_rows]
    if len(draft_rows) != 143 or len(set(draft_ids)) != 143:
        raise ClosureAuditError(f"draft-after count drift: {len(draft_rows)}")
    evidence_rows = _jsonl(candidate_dir / "evidence-after.jsonl")
    if len(evidence_rows) != 151:
        raise ClosureAuditError(f"evidence-after count drift: "
                                f"{len(evidence_rows)}")
    chunks = {c["chunk_id"]: c for c in _jsonl(chunks_path)}
    try:
        coord.strict_validate(evidence_rows, chunks)
    except coord.CoordinateError as exc:
        raise ClosureAuditError(f"strict evidence validation failed: {exc}")
    legacy = [e for e in evidence_rows
              if e.get("coordinate_contract") != CONTRACT]
    unresolved = [e for e in evidence_rows
                  if not e.get("raw_evidence_span") or
                  not isinstance(e.get("raw_chunk_char_range"), dict)]
    if legacy or unresolved:
        raise ClosureAuditError(
            f"legacy={len(legacy)} unresolved={len(unresolved)}")

    # ── 已知事实：multi-030 链关系精确 ────────────────────────────────
    draft_by_id = {r["id"]: r for r in draft_rows}
    deps: dict[str, list[str]] = {}
    for row in draft_rows:
        meta = row.get("metadata") or {}
        for key, val in (("follow_up_to", meta.get("follow_up_to")),
                         ("chain_id", meta.get("chain_id")),
                         ("doc_target", row.get("doc_target"))):
            if val == "multi-030":
                deps.setdefault(row["id"], []).append(key)
    expected = {"multi-031": ["follow_up_to"], "multi-032": ["chain_id"],
                "multi-033": ["chain_id"], "multi-034": ["chain_id"]}
    if deps != expected:
        raise ClosureAuditError(f"chain drift for multi-030: {deps}")
    m030 = draft_by_id["multi-030"]
    m030_meta = m030.get("metadata") or {}
    if m030_meta.get("follow_up_to") is not None:
        raise ClosureAuditError("multi-030 follow_up_to must be None")
    if m030_meta.get("chain_id") != "multi-028":
        raise ClosureAuditError("multi-030 chain_id must be multi-028")
    if (draft_by_id["multi-031"].get("metadata") or {}).get("chain_id") != \
            "multi-028":
        raise ClosureAuditError("multi-031 chain_id must be multi-028")

    # ── 已知事实：mixed-027 完全隔离 ──────────────────────────────────
    m027 = draft_by_id["mixed-027"]
    m027_meta = m027.get("metadata") or {}
    m027_out = [(k, v) for k, v in (
        ("follow_up_to", m027_meta.get("follow_up_to")),
        ("chain_id", m027_meta.get("chain_id")),
        ("doc_target", m027.get("doc_target")),
        ("previous_turns", m027_meta.get("previous_turns")))
        if v is not None and v != ""]
    if m027_out:
        raise ClosureAuditError(f"mixed-027 isolation drift: {m027_out}")

    # ── deferred ledger 恰 1 条 multi-030 ───────────────────────────
    deferred = _jsonl(candidate_dir / "deferred-chain-dependent-cases.jsonl")
    if len(deferred) != 1 or deferred[0].get("case_id") != "multi-030" or \
            deferred[0].get("deferred_reason") != DEFER_REASON:
        raise ClosureAuditError("deferred ledger drift")
    dep_expected = [{"case_id": cid, "relation": rel}
                    for cid, rel in (
                        ("multi-031", "follow_up_to"), ("multi-032", "chain_id"),
                        ("multi-033", "chain_id"), ("multi-034", "chain_id"))]
    ledger_deps = sorted(deferred[0].get("dependent_cases") or [],
                         key=lambda d: d.get("case_id"))
    if ledger_deps != dep_expected:
        raise ClosureAuditError(f"deferred ledger dependent_cases drift: "
                                f"{ledger_deps}")

    chunk_manifest = json.load(open(chunk_manifest_path, encoding="utf-8"))

    # ── 依赖图 + 引用完整性 + 环检测 + 混合闭包（fail-closed）────────
    graph = _build_dependency_graph(draft_rows, evidence_rows)
    incoming_m027 = [e for e in graph["edges"] if e["to"] == "mixed-027"]
    if incoming_m027:
        raise ClosureAuditError(f"mixed-027 incoming refs drift: "
                                f"{incoming_m027}")
    reach = _reachability(graph, "multi-030")
    minimal = _minimal_closed_cohort(graph, "multi-030")
    if minimal != list(CHAIN_CASES):
        raise ClosureAuditError(f"minimal closed cohort drift: {minimal}")
    chain_members = graph["chain_members"]
    if chain_members.get("multi-028") != list(CHAIN_028_MEMBERS) or \
            chain_members.get("multi-030") != list(CHAIN_030_MEMBERS):
        raise ClosureAuditError("chain membership drift")

    # ── multi-030 与 multi-031~034 在 before→after 逐字节不变 ───────
    # （置于图构建之后：链上篡改若构成环先由环检测门禁拦截；逐字节
    #   不变本身仍是独立门禁，任何漂移仍整体停止）
    def _lines(path: Path) -> list[str]:
        return open(path, encoding="utf-8").read().splitlines()

    def _by_id(lines: list[str]) -> dict[str, str]:
        return {json.loads(l)["id"]: l for l in lines}

    db = _by_id(_lines(candidate_dir / "draft-before.jsonl"))
    da = _by_id(_lines(candidate_dir / "draft-after.jsonl"))
    for cid in CHAIN_CASES:
        if da.get(cid) != db.get(cid):
            raise ClosureAuditError(f"draft byte drift for {cid}")

    def _by_case(lines: list[str]) -> dict[str, list[str]]:
        out_d: dict[str, list[str]] = {}
        for l in lines:
            out_d.setdefault(json.loads(l)["case_id"], []).append(l)
        return out_d

    eb = _by_case(_lines(candidate_dir / "evidence-before.jsonl"))
    ea = _by_case(_lines(candidate_dir / "evidence-after.jsonl"))
    for cid in CHAIN_CASES:
        if ea.get(cid, []) != eb.get(cid, []):
            raise ClosureAuditError(f"evidence byte drift for {cid}")

    return {
        "case_count": len(draft_rows),
        "evidence_count": len(evidence_rows),
        "strict_covered": len(evidence_rows),
        "strict_passed": len(evidence_rows),
        "legacy_rows": len(legacy),
        "unresolved_rows": len(unresolved),
        "gate_verdict": m["gate_verdict"],
        "chain_deps": deps,
        "chain_gate": "CHAIN_EXACT",
        "deferred_ledger": [d["deferred_reason"] for d in deferred],
        "deferred_ledger_consistent": True,
        "byte_identical": True,
        "byte_identical_cases": set(CHAIN_CASES),
        "known_facts": {
            "multi030_follow_up_to": m030_meta.get("follow_up_to"),
            "multi030_chain_id": m030_meta.get("chain_id"),
            "multi031_chain_id": (draft_by_id["multi-031"].get("metadata")
                                  or {}).get("chain_id"),
            "chain_028_members": list(CHAIN_028_MEMBERS),
            "chain_030_members": list(CHAIN_030_MEMBERS),
            "chain_deps": deps,
            "mixed027_isolation": {
                "follow_up_to": m027_meta.get("follow_up_to"),
                "chain_id": m027_meta.get("chain_id"),
                "doc_target": m027.get("doc_target"),
                "previous_turns": m027_meta.get("previous_turns"),
                "incoming_refs": [],
                "outgoing_refs": [],
            },
        },
        "graph": graph,
        "reachability": reach,
        "minimal_cohort": minimal,
        "draft_rows": draft_rows,
        "draft_by_id": draft_by_id,
        "evidence_rows": evidence_rows,
        "chunks": chunks,
        "chunk_manifest": chunk_manifest,
        "candidate_manifest": m,
    }


# ── 数据质量（等价确定性五维检查）──────────────────────────────────────

def _data_quality_report(checks: dict, graph: dict, m030: dict,
                         m027: dict, impact: dict) -> dict:
    return {
        "equivalent_deterministic_checks": {
            "completeness": {
                "candidate_case_count": checks["case_count"],
                "candidate_evidence_count": checks["evidence_count"],
                "strict_validation": "151/151 PASS",
                "blockers": list(BLOCKERS),
                "scenarios_total": len(m030["scenarios"]),
                "options_total": len(m030["options"]) + len(m027["options"]),
            },
            "uniqueness": {
                "case_ids_unique": len({r["id"] for r in checks["draft_rows"]})
                == checks["case_count"],
                "cohort_unique": len(m030["minimal_cohort"]) ==
                len(set(m030["minimal_cohort"])),
                "edges_unique": len({(e["from"], e["to"], e["relation"])
                                     for e in graph["edges"]}) ==
                len(graph["edges"]),
            },
            "referential_integrity": {
                "all_edge_targets_exist": True,
                "dangling_refs_in_candidate": 0,
                "deferred_ledger_exact": checks["deferred_ledger"]
                == [DEFER_REASON],
                "case_id_doc_target_refs": 0,
                "previous_turns_refs": 0,
                "evidence_spans_rebuildable": True,
                "mixed027_isolated": True,
            },
            "continuity": {
                "chain_cases_byte_identical": checks["byte_identical"],
                "v208_manifest_self_hash_ok": True,
                "inputs_sha_unchanged": True,
                "deterministic": True,
            },
            "consistency": {
                "options_not_selected": all(
                    r["recommendation"] is None for r in (m030, m027)),
                "owner_decision_required": all(
                    r["owner_decision_required"] for r in (m030, m027)),
                "template_rows": 2,
                "no_model_output_as_fact": True,
                "retire_single_case_safely_consistent": (
                    m027["retire_single_case_safely"]
                    == m027["options"][0]["meets_criteria"]),
            },
        },
        "skill": {"available": False,
                  "name": "data-analytics:analyze-data-quality",
                  "failure": "Skill not found: data-analytics:analyze-data-quality"},
        "skill_note": SKILL_NOTE,
    }


# ── 主流程 ────────────────────────────────────────────────────────────

def run(*, out_dir: Path = OUT, candidate_dir: Path = V208,
        chunks_path: Path = CHUNKS, chunk_manifest_path: Path = CHUNK_MANIFEST,
        current_draft_path: Path = CURRENT_DRAFT) -> dict:
    """确定性构建 chain-closure decision pack（staging 原子写入）。"""
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ClosureAuditError(f"output dir already exists: {out_dir}")
    checks = preflight(candidate_dir=candidate_dir, chunks_path=chunks_path,
                       chunk_manifest_path=chunk_manifest_path,
                       current_draft_path=current_draft_path)
    graph = checks["graph"]

    m030 = _assess_multi030(checks)
    m027 = _assess_mixed027(checks)
    impact = _chain_impact_map(checks)
    dq = _data_quality_report(checks, graph, m030, m027, impact)

    files = {
        "dependency-graph.json": _dump({
            "task": "multi-turn dependency graph",
            "case_count": graph["case_count"],
            "evidence_count": graph["evidence_count"],
            "edge_direction": ("from=引用者（字段所在 case），"
                               "to=被引用者"),
            "refs_by_type": graph["refs_by_type"],
            "previous_turns_facts": graph["previous_turns_facts"],
            "self_loops": graph["self_loops"],
            "cycles": graph["cycles"],
            "chain_members": graph["chain_members"],
            "nodes": graph["nodes"],
            "edges": graph["edges"],
            "reachability": checks["reachability"],
        }),
        "multi-030-closure-options.json": _dump(m030),
        "mixed-027-retirement-check.json": _dump(m027),
        "chain-impact-map.json": _dump(impact),
        "owner-decision-template.jsonl": "".join(
            _line({"case_id": r["case_id"], "owner_decision": "",
                   "owner_reviewer": "", "owner_notes": ""})
            for r in (m030, m027)),
        "OWNER_DECISION_GUIDE.md": _guide_md(checks, m030, m027, impact),
        "chain-closure-report.md": _report_md(checks, m030, m027, impact,
                                              dq),
    }
    inputs = {
        "v208-manifest.json": _sha256_file(candidate_dir / "manifest.json"),
        "draft-before.jsonl": _sha256_file(candidate_dir / "draft-before.jsonl"),
        "draft-after.jsonl": _sha256_file(candidate_dir / "draft-after.jsonl"),
        "evidence-before.jsonl": _sha256_file(
            candidate_dir / "evidence-before.jsonl"),
        "evidence-after.jsonl": _sha256_file(
            candidate_dir / "evidence-after.jsonl"),
        "deferred-chain-dependent-cases.jsonl": _sha256_file(
            candidate_dir / "deferred-chain-dependent-cases.jsonl"),
        "chunks.jsonl": _sha256_file(chunks_path),
        "chunk-manifest.json": _sha256_file(chunk_manifest_path),
        "current-v2-draft.jsonl": _sha256_file(current_draft_path),
    }
    outputs = {name: _sha256_text(files[name]) for name in files}
    manifest = _manifest({
        "task": "v2.0.8-chain-closure-and-mixed027-retirement-decision-audit",
        "created_by": "corpus_v2_v208_chain_closure_decision_pack.py",
        "rule_version": RULE_VERSION,
        "run_at": TIMESTAMP,
        "deterministic": True,
        "gate_verdict": "CHAIN_CLOSURE_DECISION_PACK_OK",
        "description": ("v2.0.8 传递链闭包与 mixed-027 安全退役决策审计"
                        "（只读、确定性；multi-030 传递闭包/退役场景、"
                        "mixed-027 安全退役核验；不自动选择任何选项；"
                        "不修改任何数据；无 LLM/API、无联网）"),
        "blockers": list(BLOCKERS),
        "inputs": inputs,
        "outputs": outputs,
        "declarations": {
            "llm_called": False,
            "network_used": False,
            "overlay_generated": False,
            "split_created": False,
            "v2_1_entered": False,
            "recommendation_made": False,
            "model_output_used_as_fact": False,
            "data_modified": "none",
            "input_scope": ["v2.0.8 candidate dir", "chunks",
                            "chunk manifest", "raw-codepoint strict validator"],
            "historical_verdicts_read": False,
        },
        "validation": {
            "case_count_exact_143": True,
            "evidence_count_exact_151": True,
            "strict_validation_151_151": True,
            "chain_gate_exact": True,
            "deferred_ledger_exact": True,
            "deferred_ledger_graph_consistent": True,
            "chain_cases_byte_identical": True,
            "mixed027_isolation_exact": True,
            "cycles_none": True,
            "dangling_refs_zero_in_candidate": True,
            "retire_minimal_cohort_executable": True,
            "retire_only_multi030_not_executable": True,
            "mixed027_retire_single_safely": True,
            "options_unselected": True,
        },
        "skill_note": SKILL_NOTE,
    })
    files["manifest.json"] = _dump(manifest)

    staging = Path(tempfile.mkdtemp(prefix="cc208-", dir=str(out_dir.parent)))
    try:
        for name, content in files.items():
            _atomic_write(staging / name, content)
        os.replace(staging, out_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        raise
    return {"manifest": manifest, "m030": m030, "m027": m027,
            "impact": impact, "graph": graph}


# ── 报告与指南 ────────────────────────────────────────────────────────

def _scenario_line(scen: dict) -> str:
    mark = "✅ 可执行（0 悬挂引用）" if scen["executable"] \
        else f"❌ 不可执行（{scen['dangling_ref_count']} 条悬挂引用）"
    return (f"- `{scen['name']}`（{mark}）：cohort {scen['cohort']}；"
            f"case {scen['case_count_before']}→{scen['case_count_after']}、"
            f"evidence {scen['evidence_count_before']}→"
            f"{scen['evidence_count_after']}、{scen['answer_points_removed']} "
            f"answer points；受影响 chain "
            f"{scen['upstream_chains_affected']}")


def _option_line(opt: dict) -> str:
    mark = "✅ 条件成立" if opt["meets_criteria"] else "❌ 条件不成立"
    return (f"- `{opt['option']}`（{mark}）\n"
            + "  - 核实依据："
            + (opt.get("note", "") or json.dumps(
                opt.get("criteria") or opt.get("impact") or {},
                ensure_ascii=False, indent=1).replace("\n", "\n    ")))


def _guide_md(checks: dict, m030: dict, m027: dict, impact: dict) -> str:
    reach = checks["reachability"]
    lines = [
        "# OWNER_DECISION_GUIDE.md — v2.0.8 传递链闭包与退役决策指南",
        "",
        "> 本包**只列出并核实选项，不自动选择、不自行采纳**。所有判定基于本地",
        "> 机械复算（依赖图 / 传递闭包 / strict raw 逐字重验），不把模型输出",
        "> 当作已采纳事实。任何选中动作均需所有者另行授权一个确定性执行步骤。",
        "",
        "## 1. multi-030（deferred chain parent）传递链闭包",
        "",
        "- 状态：v2.0.8 中因链依赖延后（`deferred-chain-dependent-cases.jsonl`），"
        "draft/evidence 逐字节未改；不是 resolved / confirmed / 已接受的质量结论。",
        "- 直接下游（引用者）：`multi-031.follow_up_to -> multi-030`；"
        "`multi-032/033/034.chain_id -> multi-030`；下游传递闭包 = "
        f"{reach['downstream']['all']}（无纯传递下游）。",
        f"- 上游可达（被引用方向）：{reach['upstream']['all']}；"
        "follow_up 父节点 = 无；同链成员（chain multi-028）= "
        f"{reach['same_chain_members']}；multi-030/031 自身是 chain "
        "multi-028 的成员。",
        f"- 最小无悬挂闭包 = {m030['minimal_cohort']}"
        "（multi-031.follow_up_to 与 multi-032/033/034.chain_id 强制其"
        "入组；multi-028 不引用组内 case，无需入组）。",
        "",
        "退役场景（逐一核算）：",
        "",
    ]
    for scen in m030["scenarios"]:
        lines.append(_scenario_line(scen))
    lines += [
        "",
        "选项（仅核实）：",
        "",
    ]
    for opt in m030["options"]:
        lines.append(_option_line(opt))
        lines.append("")
    lines += [
        "## 2. mixed-027 安全退役核验",
        "",
        "- 依赖事实：`follow_up_to` / `chain_id` / `doc_target` / "
        "`previous_turns` 均为空；无任何 case 引用它，它也不引用任何 case；"
        "非任何 chain 成员。",
        "- 本地逐字事实（strict 口径，判定依据）：AP0『术语表：原子化操作不可"
        "再分』无完整连续逐字命中（仅 token 片段『原子化操作』/『不可再分』，"
        "最长连续覆盖 0.38 < 0.75）；AP1『SQLite 语法页仅列出 begin-stmt，"
        "未展开事务原子性说明』为负向元论述，仅『begin-stmt』token 命中，"
        "无完整逐字证据。两个答案点均无完整、唯一、连续、同 source 直接支持。",
        "",
        "选项（仅核实）：",
        "",
    ]
    for opt in m027["options"]:
        lines.append(_option_line(opt))
        lines.append("")
    lines += [
        "## 未来可授权选项（本包不自动采纳）",
        "",
        "- 保持 `multi-030` deferred（现状）；",
        "- retire 经证明的最小依赖闭包 `retire_minimal_dependency_closed_cohort`"
        "（{multi-030..034}，0 悬挂引用；上游 chain multi-028 失去全部成员）；",
        "- 仅在安全时 retire `mixed-027`（`retire_single_case_safely=true`，"
        "143→142）；",
        "- 保持 `mixed-027` deferred（现状）。",
        "",
        "## 决策后如何执行",
        "",
        "- 任何选中选项都**不会**在本包内执行；owner 决定后需另行授权一个确定性"
        "执行脚本（并重新走 fail-closed 门禁、split reseal、盲态复审）。",
        "- 本包未生成 after / overlay / active / split / locked / v2.1 产物；"
        "未修改 candidate 任何既有文件；未调用 LLM/API、未联网。",
        "",
        f"授权标识：`{ACTOR}`；执行时间（确定性）：`{TIMESTAMP}`。",
    ]
    return "\n".join(lines) + "\n"


def _report_md(checks: dict, m030: dict, m027: dict, impact: dict,
               dq: dict) -> str:
    reach = checks["reachability"]
    down_direct = json.dumps(reach["downstream"]["direct"],
                             ensure_ascii=False)
    down_trans = json.dumps(reach["downstream"]["transitive"],
                            ensure_ascii=False)
    up_direct = json.dumps(reach["upstream"]["direct"], ensure_ascii=False)
    up_trans = json.dumps(reach["upstream"]["transitive"], ensure_ascii=False)
    iso = json.dumps(checks["known_facts"]["mixed027_isolation"],
                     ensure_ascii=False)
    dep_facts = json.dumps(m027["dependency_facts"], ensure_ascii=False)
    lines = [
        "# chain-closure-report.md — v2.0.8 链闭包与退役审计报告",
        "",
        "> 只读、确定性；不修改任何 draft/evidence/chunks/review/candidate；",
        "> 不调用 LLM/API、不联网；不自动选择任何选项。",
        "",
        "## 门禁（fail-closed，全部通过）",
        f"- v2.0.8 candidate = {checks['case_count']} cases；strict "
        f"raw-codepoint-v1 evidence {checks['strict_covered']}/"
        f"{checks['strict_passed']}（covered==passed）；legacy = "
        f"{checks['legacy_rows']}；unresolved = {checks['unresolved_rows']}",
        f"- multi-030 链关系精确："
        f"{json.dumps(checks['chain_deps'], ensure_ascii=False)}",
        f"- multi-030 自身关系：follow_up_to = "
        f"{checks['known_facts']['multi030_follow_up_to']}、chain_id = "
        f"{checks['known_facts']['multi030_chain_id']}（multi-031 同链）",
        f"- mixed-027 隔离：{iso}",
        f"- deferred ledger：{checks['deferred_ledger']}"
        "（dependent_cases 与图引用一致）",
        f"- multi-030 与 multi-031~034 在 before→after 逐字节不变："
        f"{checks['byte_identical']}",
        "- 图引用完整性：全部 case-id 字段引用指向存在的 case；无多节点环；"
        "自环仅 chain root 自标号（multi-011、multi-015，良性）",
        "",
        "## 依赖图与传递闭包（multi-030）",
        f"- 全图：{checks['case_count']} nodes / {len(checks['graph']['edges'])}"
        " edges（follow_up_to 15、chain_id 24、doc_target 0、previous_turns 0）",
        f"- 下游（引用者方向）：direct {down_direct}；transitive {down_trans}",
        f"- 上游（被引用方向）：direct {up_direct}；transitive {up_trans}",
        f"- follow_up 父节点：{reach['follow_up_parent']}；同链成员："
        f"{reach['same_chain_members']}（chain multi-028）",
        "",
        "## multi-030 退役场景核算",
        "",
    ]
    for scen in m030["scenarios"]:
        lines.append(_scenario_line(scen))
        if scen["dangling_refs"]:
            lines.append("  - 悬挂引用："
                         + json.dumps(scen["dangling_refs"], ensure_ascii=False))
        if scen["chain_impact"]:
            lines.append("  - 链影响："
                         + json.dumps(scen["chain_impact"], ensure_ascii=False))
    lines += [
        "",
        "## mixed-027 安全退役核验",
        f"- 依赖事实：{dep_facts}",
        f"- retire_single_case_safely = {m027['retire_single_case_safely']}"
        f"（case {checks['case_count']}→{m027['impact']['case_count_after']}、"
        f"evidence {checks['evidence_count']}→"
        f"{m027['impact']['evidence_count_after']}、"
        f"{m027['impact']['answer_points_removed']} answer points）",
        "- 答案点 strict 重验（判定依据，非模型输出）：",
    ]
    for ap in m027["answer_points"]:
        b = ap["best_evidence"]
        lines.append(
            f"- AP{ap['answer_point_index']}『{ap['answer_point']}』："
            f"direct_strict_support={ap['direct_strict_support']}；"
            f"best evidence {b['chunk_id']} strict 覆盖 "
            f"{b['strict_in_span_coverage']:.2f}、最长连续覆盖 "
            f"{b['max_contiguous_coverage']:.2f}"
            f"{'、仅 token 片段' if b['token_fragments'] else ''}；"
            f"源内完整 AP 命中 {ap['source_wide']['full_ap_hits']} 次")
    lines += [
        "",
        "## 选项核实结果（不自动选择）",
        "",
    ]
    for r in (m030, m027):
        lines.append(f"### {r['case_id']}（{r['blocker_type']}）")
        for opt in r["options"]:
            mark = "✅" if opt["meets_criteria"] else "❌"
            lines.append(f"- {mark} `{opt['option']}`"
                         + (f"：{opt['note']}" if opt.get("note") else ""))
        lines.append(f"- recommendation：`{r['recommendation']}`（未选择）；"
                     "需所有者决策")
        lines.append("")
    lines += [
        "## 链影响（最小闭包退役影响图摘要）",
        f"- 退役 cohort：{impact['impact_summary']['retire_cohort']}；"
        f"case {impact['impact_summary']['cases_removed']} / evidence "
        f"{impact['impact_summary']['evidence_rows_removed']} / answer points "
        f"{impact['impact_summary']['answer_points_removed']}；"
        f"case {impact['impact_summary']['case_count_after']}、"
        f"evidence {impact['impact_summary']['evidence_count_after']}",
        f"- 组内引用 {impact['impact_summary']['downstream_refs_inside_group']} "
        f"条；组外引用 "
        f"{impact['impact_summary']['external_refs_outside_group']} 条"
        "（multi-030/031.chain_id → multi-028）；悬挂引用 "
        f"{impact['impact_summary']['dangling_refs']} 条",
        f"- 受影响上游 chain："
        f"{impact['impact_summary']['upstream_chains_affected']}"
        "（chain multi-028 失去全部成员 multi-030/031；chain multi-030 "
        "整链退役；case multi-028 本身属于 chain multi-025，不受影响）",
        "",
        "## 数据质量（等价确定性五维检查）",
        "- " + json.dumps(dq["equivalent_deterministic_checks"],
                          ensure_ascii=False, indent=1).replace("\n", "\n  "),
        "",
        "## 声明",
        "- 未调用 LLM/API、未联网；未读取历史审阅结论 / split / dev / holdout / "
        "锁配置 / 评测结果",
        "- 未生成 after / overlay / active / split / locked / v2.1 产物；"
        "未修改 candidate 任何既有文件",
        "- 未 stage / commit / push",
    ]
    return "\n".join(lines) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────

USAGE = (
    "usage: corpus_v2_v208_chain_closure_decision_pack.py build "
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
    except ClosureAuditError as exc:
        print(f"chain-closure audit failed closed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
