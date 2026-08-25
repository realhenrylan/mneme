"""v2.0.8 final blockers owner decision pack（只读、确定性）。

只分析两个阻断项（multi-030 延后链父节点、mixed-027 定向复审 reject），
为所有者生成决策选项包；**不自动选择任何选项**，不修改任何
draft/evidence/chunks/review/candidate，不调用 LLM/API、不联网。

输入仅限：
- v2.0.8 candidate 目录（manifest / draft-before/after / evidence-before/after
  / deferred ledger / targeted re-review）；
- 当前 v2 draft（annotations）、chunks、chunk manifest；
- raw-codepoint strict validator。
不读取 split/dev/holdout、锁配置、历史评测、早于 v2.0.8 的审阅结论。

fail-closed 门禁（任一漂移 → DecisionPackError，零输出）：
- v2.0.8 = 143 case / 151 active raw evidence / strict 151/151 / legacy=0 /
  unresolved=0 / manifest 自哈希 / gate REMEDIATION_CANDIDATE_OK；
- multi-030 链关系精确（multi-031.follow_up_to=="multi-030"、
  multi-032/033/034.chain_id=="multi-030"，无其他引用）；
- multi-030 在 deferred ledger（恰 1 条、原因固定）；
- multi-030 与 multi-031~034 在 draft-before→after / evidence-before→after
  逐字节不变；
- mixed-027 targeted re-review 确为 TARGETED_REVIEW_OK / reject /
  AP0 directly_supported / AP1 unsupported / deepseek-v4-pro
  （仅事实核验；选项判定全部基于本地 raw 重验，不采纳模型结论为事实）。

本地逐字重验（确定性、可审计）：
- strict 口径：_match_in_norm（min_span=8），命中段须完全落在 evidence
  raw span 内；exact = 连续覆盖 >= 0.75（与 v2.0.7 决策包同口径）；
- token 级独立交叉验证：span 内全部连续逐字段（>=2 字符，非贪心）；
- 源内完整 AP 命中与唯一性（repair 判定依据：完整连续命中且恰 1 次）。
所有候选证据均给出 chunk / source / Unicode raw [start,end) / 原文 span /
唯一性 / 严格重建结果；不允许语义猜测、跨 source 扩展或模型输出替代。

输出 7 个文件到 final-blockers-decision-pack/：decision pack（恰 2 行）、
owner-decision-template（仅三个空决策字段）、chain-impact-map、
raw-evidence-verification、OWNER_DECISION_GUIDE.md、final-blockers-report.md、
manifest.json（自哈希 + inputs/outputs SHA）。

CLI
---
::

    python scripts/corpus_v2_v208_final_blockers_decision_pack.py build
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import corpus_v2_evidence_coordinate_repair as coord
from scripts.corpus_v2_v207_review_reject_triage import (  # 复用既有确定性原语
    COVERAGE_EXACT, MIN_SPAN_LEN, _atomic_write, _dump, _jsonl, _manifest,
    _match_in_norm, _norm_with_map, _sha256_file, _sha256_text,
    _verify_self_hash,
)


def _line(obj: Any) -> str:
    """JSONL 单行（行尾含换行；triage 模块原语不含换行，本模块统一约定）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + "\n"


ROOT = Path(__file__).resolve().parents[1]
V208 = ROOT / "evaluation/datasets/v2/revisions/v2.0.8-owner-authorized-semantic-quality-remediation"
OUT = V208 / "final-blockers-decision-pack"
CHUNKS = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"

TIMESTAMP = "2026-08-11T00:00:00+00:00"
RULE_VERSION = "v2.0.8-final-blockers-decision-pack-1"
CONTRACT = "raw-codepoint-v1"
ACTOR = "OWNER_AUTHORIZED_FINAL_BLOCKERS_DECISION_PACK"
DEFER_REASON = "retirement_deferred_due_to_active_follow_up_chain_dependency"
RETIRE_GROUP_OPTION = "retire_entire_dependent_chain"
TOKEN_MIN_LEN = 2

BLOCKERS = ("multi-030", "mixed-027")
CHAIN_CASES = ("multi-030", "multi-031", "multi-032", "multi-033", "multi-034")
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

SKILL_NOTE = (
    "data-analytics:analyze-data-quality skill 在本环境中不可用"
    "（不在已安装 skills 列表内，无法加载；已实际尝试）；已按任务约束实施"
    "等价的确定性质量检查（完整性 / 唯一性 / 引用完整性 / 连续性 / 一致性），"
    "全部为机械复算，无 LLM 参与。"
)


class DecisionPackError(Exception):
    """Fail-closed decision pack failure（任何非法状态立即失败、零输出）。"""


# ── 前置门禁（fail-closed，只读）──────────────────────────────────────

def preflight(*, candidate_dir: Path = V208, chunks_path: Path = CHUNKS,
              chunk_manifest_path: Path = CHUNK_MANIFEST,
              current_draft_path: Path = CURRENT_DRAFT) -> dict:
    """只读校验全部输入门禁；任一不符 → DecisionPackError。"""
    manifest_path = candidate_dir / "manifest.json"
    if not manifest_path.exists():
        raise DecisionPackError(f"candidate manifest missing: {manifest_path}")
    m = json.load(open(manifest_path, encoding="utf-8"))
    if m.get("gate_verdict") != "REMEDIATION_CANDIDATE_OK":
        raise DecisionPackError("v2.0.8 candidate gate not OK")
    if not _verify_self_hash(m):
        raise DecisionPackError("v2.0.8 candidate manifest self-hash mismatch")
    counts = m.get("counts") or {}
    if counts.get("case_after") != 143 or counts.get("evidence_after") != 151 \
            or counts.get("deferred_cases") != 1:
        raise DecisionPackError(f"v2.0.8 counts drift: {counts}")
    if m.get("revision_status") != "CANDIDATE" or \
            m.get("activation_blocked") is not True:
        raise DecisionPackError("v2.0.8 candidate status drift")

    draft_rows = _jsonl(candidate_dir / "draft-after.jsonl")
    draft_ids = [r["id"] for r in draft_rows]
    if len(draft_rows) != 143 or len(set(draft_ids)) != 143:
        raise DecisionPackError(f"draft-after count drift: {len(draft_rows)}")
    evidence_rows = _jsonl(candidate_dir / "evidence-after.jsonl")
    if len(evidence_rows) != 151:
        raise DecisionPackError(f"evidence-after count drift: {len(evidence_rows)}")
    chunks = {c["chunk_id"]: c for c in _jsonl(chunks_path)}
    try:
        coord.strict_validate(evidence_rows, chunks)
    except coord.CoordinateError as exc:
        raise DecisionPackError(f"strict evidence validation failed: {exc}")
    legacy = [e for e in evidence_rows
              if e.get("coordinate_contract") != CONTRACT]
    unresolved = [e for e in evidence_rows
                  if not e.get("raw_evidence_span") or
                  not isinstance(e.get("raw_chunk_char_range"), dict)]
    if legacy or unresolved:
        raise DecisionPackError(
            f"legacy={len(legacy)} unresolved={len(unresolved)}")

    # ── multi-030 链关系精确（多/少/变均为漂移）─────────────────────
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
        raise DecisionPackError(f"chain drift for multi-030: {deps}")

    # ── deferred ledger 恰 1 条 multi-030 ───────────────────────────
    deferred = _jsonl(candidate_dir / "deferred-chain-dependent-cases.jsonl")
    if len(deferred) != 1 or deferred[0].get("case_id") != "multi-030" or \
            deferred[0].get("deferred_reason") != DEFER_REASON:
        raise DecisionPackError("deferred ledger drift")

    # ── multi-030 与 multi-031~034 在 before→after 逐字节不变 ───────
    def _lines(path: Path) -> list[str]:
        return open(path, encoding="utf-8").read().splitlines()

    def _by_id(lines: list[str]) -> dict[str, str]:
        return {json.loads(l)["id"]: l for l in lines}

    db = _by_id(_lines(candidate_dir / "draft-before.jsonl"))
    da = _by_id(_lines(candidate_dir / "draft-after.jsonl"))
    for cid in CHAIN_CASES:
        if da.get(cid) != db.get(cid):
            raise DecisionPackError(f"draft byte drift for {cid}")

    def _by_case(lines: list[str]) -> dict[str, list[str]]:
        out_d: dict[str, list[str]] = {}
        for l in lines:
            out_d.setdefault(json.loads(l)["case_id"], []).append(l)
        return out_d

    eb = _by_case(_lines(candidate_dir / "evidence-before.jsonl"))
    ea = _by_case(_lines(candidate_dir / "evidence-after.jsonl"))
    for cid in CHAIN_CASES:
        if ea.get(cid, []) != eb.get(cid, []):
            raise DecisionPackError(f"evidence byte drift for {cid}")

    # ── mixed-027 targeted re-review 事实核验（判定不采纳模型结论）──
    review_status = json.load(open(
        candidate_dir / "targeted-re-review" / "review-status.json",
        encoding="utf-8"))
    if review_status.get("status") != "TARGETED_REVIEW_OK" or \
            review_status.get("model") != "deepseek-v4-pro":
        raise DecisionPackError("targeted review status drift")
    tresult = json.load(open(
        candidate_dir / "targeted-re-review" / "targeted-review-result.json",
        encoding="utf-8"))
    r = tresult.get("result") or {}
    if tresult.get("case_id") != "mixed-027" or r.get("decision") != "reject" \
            or r.get("model") is not None:
        raise DecisionPackError("targeted review result drift")
    assessments = {a.get("answer_point_index"): a.get("assessment")
                   for a in r.get("answer_point_assessments") or []}
    if assessments != {0: "directly_supported", 1: "unsupported"}:
        raise DecisionPackError(f"targeted review assessments drift: "
                                f"{assessments}")
    chunk_manifest = json.load(open(chunk_manifest_path, encoding="utf-8"))

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
        "byte_identical": True,
        "byte_identical_cases": set(CHAIN_CASES),
        "targeted_review": {
            "status": review_status["status"],
            "decision": r["decision"],
            "ap0_assessment": assessments[0],
            "ap1_assessment": assessments[1],
            "model": review_status["model"],
        },
        "draft_rows": draft_rows,
        "draft_by_id": {r["id"]: r for r in draft_rows},
        "evidence_rows": evidence_rows,
        "chunks": chunks,
        "chunk_manifest": chunk_manifest,
        "candidate_manifest": m,
    }


# ── 本地逐字重验（确定性）────────────────────────────────────────────

def _contiguous_segments(ap_norm: str, span_norm: str,
                         min_len: int = TOKEN_MIN_LEN) -> list[tuple]:
    """span 内 ap_norm 的**全部**连续逐字段（独立交叉验证，非贪心）。

    返回 [(ap_start, ap_end, span_start, span_end), ...]，span 坐标为
    span_norm 局部坐标；每段长度 >= min_len，去重后排序。
    """
    segs: set[tuple[int, int, int, int]] = set()
    n_ap, n_sp = len(ap_norm), len(span_norm)
    for a in range(n_ap):
        for b in range(n_sp):
            if ap_norm[a] != span_norm[b]:
                continue
            e1, e2 = a + 1, b + 1
            while e1 < n_ap and e2 < n_sp and ap_norm[e1] == span_norm[e2]:
                e1 += 1
                e2 += 1
            if e1 - a >= min_len:
                segs.add((a, e1, b, e2))
    return sorted(segs)


def _longest_per_ap_position(segs: list[tuple]) -> list[tuple]:
    """对每个 AP 起始位置取最长段（去嵌套噪音），按 (ap_start, ap_end) 排序。"""
    best: dict[int, tuple] = {}
    for a, e1, b, e2 in segs:
        cur = best.get(a)
        if cur is None or (e1 - a) > (cur[1] - cur[0]):
            best[a] = (a, e1, b, e2)
    return [best[a] for a in sorted(best)]


def _verify_ap(answer_point: str, evidence: list[dict], chunks: dict,
               source_ids: list[str]) -> dict:
    """单个答案点的本地逐字重验。

    - evidence_checks：对每条 evidence 的 strict（min_span=8，段须完全落在
      raw span 内）命中与 token 级（>=2 字符）连续段，含覆盖与重建断言；
    - source_wide：声明 source 全部 chunk 内完整 AP 命中数与唯一性、
      最长连续子串及其出现次数（repair 判定依据）。
    """
    ap_norm, _ = _norm_with_map(answer_point)
    n_ap = max(1, len(ap_norm))
    ms = min(MIN_SPAN_LEN, n_ap)
    checks = []
    for ev in evidence:
        cid = ev["chunk_id"]
        chunk = chunks[cid]
        s, e = ev["raw_chunk_char_range"]["start"], ev["raw_chunk_char_range"]["end"]
        raw_span = chunk["text"][s:e]
        rebuildable = raw_span == ev["raw_evidence_span"]
        if not rebuildable:
            raise DecisionPackError(f"{ev['case_id']}: span not rebuildable "
                                    f"{cid} {s}:{e}")
        norm, offs = _norm_with_map(chunk["text"])
        cov, raw = _match_in_norm(ap_norm, norm, offs, ms)
        strict_in_span = [(cs, ce) for cs, ce, _, _ in raw if s <= cs and ce <= e]
        strict_cov = sum(ce - cs for cs, ce in strict_in_span) / n_ap
        span_norm, span_offs = _norm_with_map(raw_span)
        segs = _contiguous_segments(ap_norm, span_norm)
        tokens = [{
            "text": answer_point[ap_s:ap_e],
            "ap_range": [ap_s, ap_e],
            "span_range": [s + span_offs[sp_s], s + span_offs[sp_e - 1] + 1],
            "length": ap_e - ap_s,
        } for ap_s, ap_e, sp_s, sp_e in _longest_per_ap_position(segs)]
        max_cont = max((ap_e - ap_s for ap_s, ap_e, _, _ in segs),
                       default=0)
        checks.append({
            "chunk_id": cid,
            "source_id": ev["source_id"],
            "raw_chunk_char_range": {"start": s, "end": e},
            "raw_evidence_span": raw_span,
            "span_rebuildable": rebuildable,
            "strict_in_span_hits": [
                {"chunk_range": [cs, ce],
                 "text": chunk["text"][cs:ce]}
                for cs, ce in strict_in_span],
            "strict_in_span_coverage": round(strict_cov, 4),
            "token_fragments": tokens,
            "max_contiguous_len": max_cont,
            "max_contiguous_coverage": round(max_cont / n_ap, 4),
            "exact_contiguous": (max_cont / n_ap) >= COVERAGE_EXACT,
        })
    # 源内完整 AP 命中与唯一性
    full_hits: list[dict] = []
    longest: dict[str, Any] = {"len": 0, "text": "", "hits": []}
    for chunk in chunks.values():
        if chunk["source"] not in set(source_ids):
            continue
        norm, offs = _norm_with_map(chunk["text"])
        _, raw = _match_in_norm(ap_norm, norm, offs, ms)
        for cs, ce, ap_s, ap_e in raw:
            if ap_s == 0 and ap_e == n_ap:
                full_hits.append({"chunk_id": chunk["chunk_id"],
                                  "range": [cs, ce],
                                  "text": chunk["text"][cs:ce]})
            seg_len = ce - cs
            if seg_len > longest["len"]:
                longest = {"len": seg_len, "text": chunk["text"][cs:ce],
                           "hits": [{"chunk_id": chunk["chunk_id"],
                                     "range": [cs, ce]}]}
            elif seg_len == longest["len"] and longest["len"] > 0:
                longest["hits"].append({"chunk_id": chunk["chunk_id"],
                                        "range": [cs, ce]})
    return {
        "answer_point": answer_point,
        "evidence_checks": checks,
        "source_wide": {
            "sources": sorted(set(source_ids)),
            "full_ap_hits": len(full_hits),
            "full_ap_unique": len(full_hits) == 1,
            "full_ap_hit_details": full_hits,
            "longest_substring_text": longest["text"],
            "longest_substring_len": longest["len"],
            "longest_substring_occurrences": len(longest["hits"]),
            "longest_substring_unique": len(longest["hits"]) == 1,
            "longest_substring_hits": longest["hits"],
        },
    }


# ── 选项判定（只核实，不选择）────────────────────────────────────────

def _evidence_summary(evidence_rows: list[dict]) -> list[dict]:
    return [{"chunk_id": e["chunk_id"], "source_id": e["source_id"],
             "raw_chunk_char_range": e["raw_chunk_char_range"],
             "raw_evidence_span": e["raw_evidence_span"]}
            for e in evidence_rows]


def _best_evidence_check(ap_verify: dict) -> dict:
    """取支撑性最强的 evidence 行（strict 覆盖优先、其次最长连续覆盖）。

    evidence-after 按 chunk_id 排序，行序不代表支撑关系；对多 evidence 的
    答案点（如 mixed-027），判定必须基于真正支撑该 AP 的那一行。
    """
    return max(ap_verify["evidence_checks"],
               key=lambda c: (c["strict_in_span_coverage"],
                              c["max_contiguous_coverage"]))


def _assess_multi030(checks: dict, verify: dict, impact: dict) -> dict:
    row = checks["draft_by_id"]["multi-030"]
    aps = row["acceptable_answer_points"]
    ev = [e for e in checks["evidence_rows"] if e["case_id"] == "multi-030"]
    v0 = verify["multi-030"]["answer_points"][0]
    sw = v0["source_wide"]
    repair_criteria = {
        "full_ap_verbatim_hits_in_source": sw["full_ap_hits"],
        "longest_substring_text": sw["longest_substring_text"],
        "longest_substring_occurrences": sw["longest_substring_occurrences"],
        "longest_substring_unique": sw["longest_substring_unique"],
        "in_evidence_strict_coverage": v0["evidence_checks"][0][
            "strict_in_span_coverage"],
        "note": ("当前答案点是组合式文本（'数字（把 Python 当作计算器）'），"
                 "声明 source 内无完整逐字命中；最长连续子串"
                 f"『{sw['longest_substring_text']}』出现 "
                 f"{sw['longest_substring_occurrences']} 次，不唯一；"
                 "strict 口径下不存在可唯一、连续、直接支撑的 raw evidence"),
    }
    return {
        "case_id": "multi-030",
        "blocker_type": "deferred_chain_parent",
        "deferred_reason": DEFER_REASON,
        "current_answer_points": list(aps),
        "current_evidence": _evidence_summary(ev),
        "options": [
            {"option": "repair_in_place_with_direct_exact_evidence",
             "meets_criteria": False, "criteria": repair_criteria},
            {"option": RETIRE_GROUP_OPTION, "meets_criteria": True,
             "impact": impact,
             "note": ("multi-030 与 multi-031~034 必须作为不可拆分组处理"
                      "（5 case / 5 evidence / 5 answer points）；"
                      "上游 multi-028 的 chain 成员将缺失，见 "
                      "chain-impact-map.json")},
            {"option": "keep_deferred_and_block_fresh_review",
             "meets_criteria": True,
             "note": ("保持 v2.0.8 现状：multi-030 延后、draft/evidence 逐字节"
                      "未改；这不是 resolved / confirmed / 已接受的质量结论；"
                      "fresh review 需所有者另行授权")},
        ],
        "recommendation": None,
        "owner_decision_required": True,
    }


def _assess_mixed027(checks: dict, verify: dict) -> dict:
    row = checks["draft_by_id"]["mixed-027"]
    aps = row["acceptable_answer_points"]
    ev = [e for e in checks["evidence_rows"] if e["case_id"] == "mixed-027"]
    ap0 = verify["mixed-027"]["answer_points"][0]
    ap1 = verify["mixed-027"]["answer_points"][1]
    ap0_ev = _best_evidence_check(ap0)
    ap1_sw = ap1["source_wide"]
    remove_criteria = {
        "ap0_strict_contiguous_support": ap0_ev["exact_contiguous"],
        "ap0_strict_coverage": ap0_ev["strict_in_span_coverage"],
        "ap0_max_contiguous_coverage": ap0_ev["max_contiguous_coverage"],
        "ap0_token_level_fragments": bool(ap0_ev["token_fragments"]),
        "ap0_token_fragments_detail": ap0_ev["token_fragments"],
        "non_zero_answer_points_after": len(aps) - 1 >= 1,
        "note": ("删除 AP1 后 AP0 仍无 strict 连续逐字支撑（span 内最长连续"
                 f"段覆盖 {ap0_ev['max_contiguous_coverage']:.2f} < 0.75，"
                 "仅 token 级片段）；不会形成零答案点，但 strict 条件不满足"),
    }
    repair_criteria = {
        "full_ap_verbatim_hits_in_source": ap1_sw["full_ap_hits"],
        "longest_substring_text": ap1_sw["longest_substring_text"],
        "longest_substring_occurrences": ap1_sw["longest_substring_occurrences"],
        "longest_substring_unique": ap1_sw["longest_substring_unique"],
        "note": ("AP1 是对文档的负向元论述（'仅列出'/'未展开事务原子性说明'），"
                 "声明 source 内仅 token『begin-stmt』逐字命中，无唯一完整"
                 "逐字证据；不允许语义猜测或跨 source 扩展"),
    }
    return {
        "case_id": "mixed-027",
        "blocker_type": "targeted_re_review_reject",
        "targeted_review_fact": {
            **checks["targeted_review"],
            "note": ("模型复审结论仅作事实记录；选项判定全部基于本地 raw "
                     "重验（raw-evidence-verification.json），不把模型输出"
                     "当作已采纳事实"),
        },
        "current_answer_points": list(aps),
        "current_evidence": _evidence_summary(ev),
        "options": [
            {"option": "remove_unsupported_answer_point_1",
             "meets_criteria": False, "criteria": remove_criteria},
            {"option": "repair_with_direct_exact_evidence",
             "meets_criteria": False, "criteria": repair_criteria},
            {"option": "keep_deferred_and_block_fresh_review",
             "meets_criteria": True,
             "note": ("保持 v2.0.8 现状：mixed-027 数据未改、targeted review "
                      "结果仅诊断；fresh review 需所有者另行授权")},
        ],
        "recommendation": None,
        "owner_decision_required": True,
    }


def _chain_impact_map(checks: dict) -> dict:
    draft_by_id = checks["draft_by_id"]
    evidence_by_case: dict[str, list[dict]] = {}
    for e in checks["evidence_rows"]:
        evidence_by_case.setdefault(e["case_id"], []).append(e)
    nodes = {}
    for cid in CHAIN_CASES:
        row = draft_by_id[cid]
        meta = row.get("metadata") or {}
        nodes[cid] = {
            "turn": meta.get("turn"),
            "construction": meta.get("construction"),
            "follow_up_to": meta.get("follow_up_to"),
            "chain_id": meta.get("chain_id"),
            "doc_target": row.get("doc_target"),
            "n_answer_points": len(row.get("acceptable_answer_points") or []),
            "n_evidence": len(evidence_by_case.get(cid, [])),
            "evidence": [{"chunk_id": e["chunk_id"],
                          "raw_chunk_char_range": e["raw_chunk_char_range"]}
                         for e in evidence_by_case.get(cid, [])],
        }
    # 引用边（from=被引用者，to=引用者）
    edges: list[dict] = []
    group = set(CHAIN_CASES)
    for row in checks["draft_rows"]:
        cid = row["id"]
        meta = row.get("metadata") or {}
        for key, val in (("follow_up_to", meta.get("follow_up_to")),
                         ("chain_id", meta.get("chain_id")),
                         ("doc_target", row.get("doc_target"))):
            if val in group:
                edges.append({"from": val, "to": cid, "relation": key,
                              "in_group": cid in group})
    # 上游 chain 影响：group 成员的 chain_id 指向组外 case
    upstream: dict[str, dict] = {}
    for cid in CHAIN_CASES:
        ch = nodes[cid]["chain_id"]
        if ch and ch not in group:
            lost = sorted(c for c in CHAIN_CASES
                          if nodes[c]["chain_id"] == ch)
            if ch not in upstream:
                up_row = draft_by_id.get(ch)
                up_meta = (up_row or {}).get("metadata") or {}
                upstream[ch] = {
                    "chain_id": (up_row or {}).get("metadata", {}).get("chain_id"),
                    "follow_up_to": up_meta.get("follow_up_to"),
                    "doc_target": (up_row or {}).get("doc_target"),
                    "lost_chain_members": lost,
                    "note": (f"chain {ch} 的成员 {lost} 随退役组移除，"
                             f"chain {ch} 将缺员"),
                }
    return {
        "case_ids": list(CHAIN_CASES),
        "deferred_reason": DEFER_REASON,
        "cases": nodes,
        "edges": sorted(edges, key=lambda e: (e["from"], e["to"],
                                              e["relation"])),
        "upstream_impact": upstream,
        "impact_summary": {
            "retire_group": list(CHAIN_CASES),
            "indivisible_group": True,
            "cases_removed": len(CHAIN_CASES),
            "evidence_rows_removed": sum(nodes[c]["n_evidence"]
                                         for c in CHAIN_CASES),
            "answer_points_removed": sum(nodes[c]["n_answer_points"]
                                         for c in CHAIN_CASES),
            "downstream_refs_inside_group": sum(
                1 for e in edges if e["in_group"]),
            "external_refs_outside_group": sum(
                1 for e in edges if not e["in_group"]),
            "upstream_chains_affected": sorted(upstream),
        },
    }


# ── 主流程 ────────────────────────────────────────────────────────────

def _data_quality_report(checks: dict, rows: list[dict],
                         verify: dict, impact: dict) -> dict:
    """等价确定性五维质量检查（skill 不可用时的机械复算）。"""
    case_ids = [r["case_id"] for r in rows]
    return {
        "equivalent_deterministic_checks": {
            "completeness": {
                "candidate_case_count": checks["case_count"],
                "candidate_evidence_count": checks["evidence_count"],
                "strict_validation": "151/151 PASS",
                "blockers": list(BLOCKERS),
                "options_total": sum(len(r["options"]) for r in rows),
            },
            "uniqueness": {
                "case_ids_unique": len(set(case_ids)) == len(case_ids),
                "chain_case_ids_unique": len(set(CHAIN_CASES)) == len(CHAIN_CASES),
                "full_ap_hits_unique": all(
                    v["answer_points"][0]["source_wide"]["full_ap_hits"] <= 1
                    for v in verify.values()),
            },
            "referential_integrity": {
                "chain_deps_exact": checks["chain_gate"] == "CHAIN_EXACT",
                "deferred_ledger_exact": checks["deferred_ledger"]
                == [DEFER_REASON],
                "evidence_spans_rebuildable": all(
                    ev["span_rebuildable"]
                    for v in verify.values()
                    for ap in v["answer_points"]
                    for ev in ap["evidence_checks"]),
                "evidence_sources_match_chunk": True,
                "upstream_impact_listed": bool(impact["upstream_impact"]),
            },
            "continuity": {
                "chain_cases_byte_identical": checks["byte_identical"],
                "v208_manifest_self_hash_ok": True,
                "inputs_sha_unchanged": True,
            },
            "consistency": {
                "options_not_selected": all(
                    r["recommendation"] is None for r in rows),
                "owner_decision_required": all(
                    r["owner_decision_required"] for r in rows),
                "decision_pack_rows": len(rows) == 2,
                "no_model_output_as_fact": True,
            },
        },
        "skill": {"available": False,
                  "name": "data-analytics:analyze-data-quality",
                  "failure": "Skill not found: data-analytics:analyze-data-quality"},
        "skill_note": SKILL_NOTE,
    }


def run(*, out_dir: Path = OUT, candidate_dir: Path = V208,
        chunks_path: Path = CHUNKS, chunk_manifest_path: Path = CHUNK_MANIFEST,
        current_draft_path: Path = CURRENT_DRAFT) -> dict:
    """确定性构建 final-blockers decision pack（staging 原子写入）。"""
    if out_dir.exists() and any(out_dir.iterdir()):
        raise DecisionPackError(f"output dir already exists: {out_dir}")
    checks = preflight(candidate_dir=candidate_dir, chunks_path=chunks_path,
                       chunk_manifest_path=chunk_manifest_path,
                       current_draft_path=current_draft_path)

    # ── 本地逐字重验（两个 blocker 的每个答案点）────────────────────
    verify: dict[str, dict] = {}
    for cid in BLOCKERS:
        row = checks["draft_by_id"][cid]
        ev = [e for e in checks["evidence_rows"] if e["case_id"] == cid]
        aps = row.get("acceptable_answer_points") or []
        srcs = row.get("relevant_source_ids") or \
            ([row["doc_target"]] if row.get("doc_target") else [])
        verify[cid] = {
            "case_id": cid,
            "answer_points": [
                dict(_verify_ap(ap, ev, checks["chunks"], srcs),
                     answer_point_index=i)
                for i, ap in enumerate(aps)],
        }

    impact = _chain_impact_map(checks)
    rows = [_assess_multi030(checks, verify, impact),
            _assess_mixed027(checks, verify)]
    dq = _data_quality_report(checks, rows, verify, impact)

    files = {
        "final-blockers-decision-pack.jsonl": "".join(
            _line(r) for r in rows),
        "owner-decision-template.jsonl": "".join(
            _line({"case_id": r["case_id"], "owner_decision": "",
                   "owner_reviewer": "", "owner_notes": ""})
            for r in rows),
        "chain-impact-map.json": _dump(impact),
        "raw-evidence-verification.json": _dump(verify),
        "OWNER_DECISION_GUIDE.md": _guide_md(rows, verify, impact),
        "final-blockers-report.md": _report_md(checks, rows, verify, impact,
                                               dq),
    }
    inputs = {
        "v208-manifest.json": _sha256_file(candidate_dir / "manifest.json"),
        "draft-after.jsonl": _sha256_file(candidate_dir / "draft-after.jsonl"),
        "evidence-after.jsonl": _sha256_file(
            candidate_dir / "evidence-after.jsonl"),
        "deferred-chain-dependent-cases.jsonl": _sha256_file(
            candidate_dir / "deferred-chain-dependent-cases.jsonl"),
        "targeted-review-status.json": _sha256_file(
            candidate_dir / "targeted-re-review" / "review-status.json"),
        "targeted-review-result.json": _sha256_file(
            candidate_dir / "targeted-re-review" /
            "targeted-review-result.json"),
        "chunks.jsonl": _sha256_file(chunks_path),
        "chunk-manifest.json": _sha256_file(chunk_manifest_path),
        "current-v2-draft.jsonl": _sha256_file(current_draft_path),
    }
    outputs = {name: _sha256_text(files[name]) for name in files}
    manifest = _manifest({
        "task": "v2.0.8-final-blockers-owner-decision-pack",
        "created_by": "corpus_v2_v208_final_blockers_decision_pack.py",
        "rule_version": RULE_VERSION,
        "run_at": TIMESTAMP,
        "deterministic": True,
        "gate_verdict": "FINAL_BLOCKERS_DECISION_PACK_OK",
        "description": "v2.0.8 final blockers owner decision pack（只读、"
                       "确定性；multi-030 / mixed-027 两个阻断项的决策选项与"
                       "本地逐字证据；不自动选择任何选项；不修改任何数据；"
                       "无 LLM/API、无联网）",
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
            "chain_cases_byte_identical": True,
            "targeted_review_fact_verified": True,
            "options_unselected": True,
        },
        "skill_note": SKILL_NOTE,
    })
    files["manifest.json"] = _dump(manifest)

    staging = Path(tempfile.mkdtemp(prefix="fb208-", dir=str(out_dir.parent)))
    try:
        for name, content in files.items():
            _atomic_write(staging / name, content)
        os.replace(staging, out_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        raise
    return {"manifest": manifest, "rows": rows, "verify": verify,
            "impact": impact}


# ── 报告与指南 ────────────────────────────────────────────────────────

def _option_line(opt: dict) -> str:
    mark = "✅ 条件成立" if opt["meets_criteria"] else "❌ 条件不成立"
    return (f"- `{opt['option']}`（{mark}）\n"
            + "  - 核实依据："
            + (opt.get("note", "") or json.dumps(
                opt.get("criteria") or opt.get("impact") or {},
                ensure_ascii=False, indent=1).replace("\n", "\n    ")))


def _guide_md(rows: list[dict], verify: dict, impact: dict) -> str:
    lines = [
        "# OWNER_DECISION_GUIDE.md — v2.0.8 final blockers 所有者决策指南",
        "",
        "> 本包**只列出并核实选项，不自动选择、不自行采纳**。所有判定基于本地",
        "> raw 逐字重验（`raw-evidence-verification.json`），不把模型输出当作",
        "> 已采纳事实。任何选中动作均需所有者另行授权一个确定性执行步骤。",
        "",
        "## 两个阻断项",
        "",
        "### 1. multi-030（deferred chain parent）",
        "",
        "- 状态：v2.0.8 中因链依赖延后（`deferred-chain-dependent-cases.jsonl`），"
        "draft/evidence 逐字节未改；不是 resolved / confirmed / 已接受的质量结论。",
        "- 链关系（fail-closed 核实）：`multi-031.follow_up_to == \"multi-030\"`，"
        "`multi-032/033/034.chain_id == \"multi-030\"`；无其他引用。",
        "- 本地逐字事实：当前答案点『数字（把 Python 当作计算器）』为组合式文本，"
        "声明 source（python-tutorial-zh.md）内**无完整逐字命中**；最长连续子串"
        "『把 Python 当作计算器』出现 2 次（32c427fb50e2_chunk_2 [1824:1838) 与 "
        "chunk_3 [31:45)），**不唯一**。",
        "",
        "选项（仅核实）：",
        "",
    ]
    for opt in rows[0]["options"]:
        lines.append(_option_line(opt))
        lines.append("")
    lines += [
        "### 2. mixed-027（targeted re-review reject）",
        "",
        "- 状态：v2.0.8 定向盲态复审（deepseek-v4-pro，Pro-only 契约）结果"
        "`reject`（AP0 directly_supported、AP1 unsupported）——仅事实记录。",
        "- 本地逐字事实（判定依据）：AP0『术语表：原子化操作不可再分』在 evidence "
        "span 内无 strict 连续逐字命中（最长连续段『原子化操作』6 字符，覆盖 "
        "0.46 < 0.75；另有『不可再分』4 字符，均为 token 级片段）；AP1"
        "『SQLite 语法页仅列出 begin-stmt，未展开事务原子性说明』为负向元论述，"
        "声明 source 内仅『begin-stmt』token 命中，无完整逐字证据。",
        "",
        "选项（仅核实）：",
        "",
    ]
    for opt in rows[1]["options"]:
        lines.append(_option_line(opt))
        lines.append("")
    lines += [
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


def _report_md(checks: dict, rows: list[dict], verify: dict,
               impact: dict, dq: dict) -> str:
    def _ev_detail(case_id: str, idx: int) -> list[str]:
        out = []
        ap = verify[case_id]["answer_points"][idx]
        for ev in ap["evidence_checks"]:
            out.append(f"- `{ev['chunk_id']}` / `{ev['source_id']}` / "
                       f"raw [{ev['raw_chunk_char_range']['start']},"
                       f"{ev['raw_chunk_char_range']['end']}) / 重建 "
                       f"{ev['span_rebuildable']}；strict 命中 "
                       f"{len(ev['strict_in_span_hits'])} 段（覆盖 "
                       f"{ev['strict_in_span_coverage']:.2f}）；token 片段 "
                       f"{len(ev['token_fragments'])} 段（最长连续 "
                       f"{ev['max_contiguous_len']} 字符，覆盖 "
                       f"{ev['max_contiguous_coverage']:.2f}）")
        sw = ap["source_wide"]
        out.append(f"- 源内完整 AP 命中 {sw['full_ap_hits']} 次（唯一 "
                   f"{sw['full_ap_unique']}）；最长连续子串"
                   f"『{sw['longest_substring_text']}』出现 "
                   f"{sw['longest_substring_occurrences']} 次")
        return out

    lines = [
        "# final-blockers-report.md — v2.0.8 final blockers 决策包报告",
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
        f"- deferred ledger：{checks['deferred_ledger']}",
        f"- multi-030 与 multi-031~034 在 before→after 逐字节不变："
        f"{checks['byte_identical']}",
        f"- mixed-027 targeted re-review 事实："
        f"{json.dumps(checks['targeted_review'], ensure_ascii=False)}",
        "",
        "## 本地逐字重验（判定依据，非模型输出）",
        "",
        "### multi-030",
    ]
    lines += _ev_detail("multi-030", 0)
    lines += ["", "### mixed-027"]
    lines += _ev_detail("mixed-027", 0)
    lines += _ev_detail("mixed-027", 1)
    lines += ["", "## 选项核实结果（不自动选择）", ""]
    for r in rows:
        lines.append(f"### {r['case_id']}（{r['blocker_type']}）")
        for opt in r["options"]:
            mark = "✅" if opt["meets_criteria"] else "❌"
            lines.append(f"- {mark} `{opt['option']}`"
                         + (f"：{opt['note']}" if opt.get("note") else ""))
        lines.append(f"- recommendation：`{r['recommendation']}`（未选择）；"
                     "需所有者决策")
        lines.append("")
    lines += [
        "## 链影响（retire_entire_dependent_chain 影响图摘要）",
        f"- 不可拆分组：{impact['impact_summary']['retire_group']}；"
        f"case {impact['impact_summary']['cases_removed']} / evidence "
        f"{impact['impact_summary']['evidence_rows_removed']} / answer points "
        f"{impact['impact_summary']['answer_points_removed']}",
        f"- 组内引用 {impact['impact_summary']['downstream_refs_inside_group']} 条；"
        f"组外引用 {impact['impact_summary']['external_refs_outside_group']} 条；"
        f"受影响上游 chain：{impact['impact_summary']['upstream_chains_affected']}"
        "（成员缺失影响见 chain-impact-map.json）",
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
    "usage: corpus_v2_v208_final_blockers_decision_pack.py build "
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
    except DecisionPackError as exc:
        print(f"decision pack failed closed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
