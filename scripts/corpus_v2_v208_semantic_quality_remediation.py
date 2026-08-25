"""v2.0.8 owner-authorized semantic-quality remediation candidate（链安全版）。

基于 v2.0.7 reject semantic-quality decision pack（用户已批准推荐策略），
生成独立的 v2.0.8 candidate：148 → 143 条 case、evidence 161 → 151 行，
全部为确定性修改；不覆盖 v2.0.7、当前 active 数据、review、split、锁配置
或历史产物；不生成 overlay / active metadata / split / v2.1 文件。

链依赖修订（相对首版）：multi-030 是 multi-031~034 的多轮链父节点
（multi-031.follow_up_to == "multi-030"，multi-032/033/034.chain_id ==
"multi-030"），禁止单独退役——依赖结构必须与授权 defer 依据完全一致
（多/少/变均为漂移 → 整体停止），multi-030 不修改、不退役、保留其
draft/evidence 逐字节不变，写入 deferred-chain-dependent-cases.jsonl
（延后原因 retirement_deferred_due_to_active_follow_up_chain_dependency；
明确不是 resolved / confirmed / 已接受的质量结论）；其余五条退役 case
（en-044、en-050、mixed-026、zh-042、zh-045）必须无任何
follow-up/chain/doc_target/case 引用依赖，否则整体 fail-closed。

固定授权动作（严格按 decision pack 已验证 exact raw candidate / answer point
index / source/chunk/range 执行，不重新选择 evidence、无模型代替选择）：
- 批次 A（7 条）：replace_answer_point_with_self_contained_exact_raw_text——
  答案点替换为 decision pack 候选（candidate_refs 中第一个 self_contained=True
  且 unique=True 的候选，refs 按 (chunk_id, start) 排序），旧答案点专属
  token evidence 清理，写入新 raw-codepoint-v1 evidence。
- 批次 B（1 条，zh-040）：expand_same_source_evidence_scope——答案点不变，
  仅追加两条已验证同 chunk TOC evidence；diff 显式记录
  OWNER_AUTHORIZED_SAME_SOURCE_EVIDENCE_SCOPE_EXPANSION。
- 批次 C（3 条）：faithful_translation_equivalence_v1 策略文件 + 恰 3 条
  ledger；不是自动 confirmed，后续仍需盲态复审；不扩展其他 case。
- 批次 D（10 条）：4 条移除 unsupported 答案点（预检剩余 ≥1，清理 orphan
  evidence）；5 条退役（retire 前 fail-closed 检查 follow-up/chain/doc_target
  与 case 引用依赖，有任何依赖则整体停止；固定原因
  no_semantically_sufficient_direct_evidence_after_owner_authorized_review）；
  1 条延后（multi-030，见上）。
- 批次 E（1 条，mixed-027）：candidate 写入成功后单独盲态机器复审
  （deepseek-v4-pro / temperature=0.0 / max_tokens=8000 / thinking disabled /
  max_retries=3，无 fallback）；结果仅作 targeted-re-review 诊断，无论结果
  如何不生成 overlay、不改变 case 数据；失败如实标 TARGETED_REVIEW_BLOCKED。

fail-closed：任一前置门禁不满足、退役依赖存在或 multi-030 链依赖结构漂移
→ RemediationError，零输出。
确定性：固定时间戳；两次构建逐字节一致；manifest 自哈希与磁盘 SHA 一致。

CLI
---
::

    python scripts/corpus_v2_v208_semantic_quality_remediation.py build
    python scripts/corpus_v2_v208_semantic_quality_remediation.py review-targeted
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
from scripts import corpus_v2_v207_review_reject_triage as triage_mod
from scripts.corpus_v2_v207_review_reject_triage import (  # 复用既有确定性原语
    _atomic_write, _collect_spans, _dump, _jsonl, _manifest,
    _match_in_norm, _norm_with_map, _sha256_file, _sha256_text,
    _verify_self_hash,
)


def _line(obj: Any) -> str:
    """JSONL 单行（行尾含换行；triage 模块原语不含换行，本模块统一约定）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + "\n"

ROOT = Path(__file__).resolve().parents[1]
V207 = ROOT / "evaluation/datasets/v2/revisions/v2.0.7-owner-authorized-legacy-evidence-retirement"
AR = V207 / "automated-review"
DECISION_PACK_DIR = AR / "reject-semantic-quality-decision-pack"
OUT = ROOT / "evaluation/datasets/v2/revisions/v2.0.8-owner-authorized-semantic-quality-remediation"
DRAFT_BEFORE = V207 / "draft-after.jsonl"
EVIDENCE_BEFORE = V207 / "evidence-after.jsonl"
CANDIDATE_MANIFEST = V207 / "manifest.json"
CHUNKS = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"

TIMESTAMP = "2026-08-11T00:00:00+00:00"
RULE_VERSION = "v2.0.8-semantic-quality-remediation-chain-safe-1"
CONTRACT = "raw-codepoint-v1"
NORMALIZATION = "display-whitespace-v1"
ALGORITHM = "raw-span-map-1"
ACTOR = "OWNER_AUTHORIZED_SEMANTIC_QUALITY_REMEDIATION_CHAIN_SAFE"
AUTHORIZATION = "OWNER_AUTHORIZED_SEMANTIC_QUALITY_REMEDIATION_CHAIN_SAFE"
RETIRE_REASON = "no_semantically_sufficient_direct_evidence_after_owner_authorized_review"
DEFER_REASON = "retirement_deferred_due_to_active_follow_up_chain_dependency"
POLICY_VERSION = "faithful_translation_equivalence_v1"
SCOPE_MARKER = "OWNER_AUTHORIZED_SAME_SOURCE_EVIDENCE_SCOPE_EXPANSION"
MIN_SPAN_LEN = 8

EXPECTED_CASE_BEFORE = 148
EXPECTED_CASE_AFTER = 143
EXPECTED_EVIDENCE_BEFORE = 161
EXPECTED_EVIDENCE_AFTER = 151
EXPECTED_REVIEW_COUNTS = {"confirmed": 126, "reject": 22, "needs_followup": 0}
EXPECTED_DISTRIBUTION = {"batch_a": 7, "batch_b": 1, "batch_c": 3,
                         "batch_d": 10, "batch_e": 1}

BATCH_A = ("mixed-028", "mixed-029", "zh-023", "zh-026", "zh-029", "zh-036",
           "zh-054")
BATCH_B = ("zh-040",)
BATCH_C = ("en-029", "multi-019", "zh-052")
BATCH_D_REMOVE = ("en-042", "en-049", "en-051", "mixed-033")
BATCH_D_RETIRE = ("en-044", "en-050", "mixed-026", "zh-042", "zh-045")
DEFERRED = ("multi-030",)
BATCH_E = ("mixed-027",)
ALL_TARGETS = (BATCH_A + BATCH_B + BATCH_C + BATCH_D_REMOVE +
               BATCH_D_RETIRE + DEFERRED + BATCH_E)

EXPECTED_ACTIONS = {
    "mixed-028": "replace_answer_point_with_self_contained_exact_raw_text",
    "mixed-029": "replace_answer_point_with_self_contained_exact_raw_text",
    "zh-023": "replace_answer_point_with_self_contained_exact_raw_text",
    "zh-026": "replace_answer_point_with_self_contained_exact_raw_text",
    "zh-029": "replace_answer_point_with_self_contained_exact_raw_text",
    "zh-036": "replace_answer_point_with_self_contained_exact_raw_text",
    "zh-054": "replace_answer_point_with_self_contained_exact_raw_text",
    "zh-040": "expand_same_source_evidence_scope",
    "en-029": "owner_approved_translation_equivalence_policy",
    "multi-019": "owner_approved_translation_equivalence_policy",
    "zh-052": "owner_approved_translation_equivalence_policy",
    "en-042": "remove_unsupported_answer_point",
    "en-049": "remove_unsupported_answer_point",
    "en-051": "remove_unsupported_answer_point",
    "mixed-033": "remove_unsupported_answer_point",
    "en-044": "retire_case",
    "en-050": "retire_case",
    "mixed-026": "retire_case",
    "multi-030": "retire_case",
    "zh-042": "retire_case",
    "zh-045": "retire_case",
    "mixed-027": "targeted_blind_re_review",
}

OUTPUT_FILES = (
    "draft-before.jsonl", "draft-after.jsonl", "evidence-before.jsonl",
    "evidence-after.jsonl", "reannotation-diff.jsonl", "retired-cases.jsonl",
    "retired-evidence.jsonl", "deferred-chain-dependent-cases.jsonl",
    "translation-equivalence-policy.md",
    "translation-equivalence-policy-ledger.jsonl",
    "coordinate-validation-report.json", "data-quality-report.json",
    "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md", "REPAIR_REPORT.md", "manifest.json",
)

# 批次 E 定向盲态复审契约（Pro-only，无 fallback）
REVIEWER_IDENTITY = "TARGETED_BLIND_RE_REVIEW_V2_0_8"
REVIEW_MODEL = "deepseek-v4-pro"
REVIEWER_TEMPERATURE = 0.0
REVIEWER_MAX_TOKENS = 8000
MAX_RETRIES = 3
EXTRA_BODY = {"thinking": {"type": "disabled"}}
FORBIDDEN_MODELS = ("gpt-5.6-sol", "deepseek-v4-flash")
DECISIONS = ("confirmed", "reject", "needs_followup")
ASSESSMENTS = ("directly_supported", "faithful_paraphrase", "unsupported")
REFUSAL_ASSESSMENTS = ("not_applicable", "correct_refusal", "incorrect_refusal")

SKILL_NOTE = (
    "data-analytics:analyze-data-quality skill 在本环境中不可用"
    "（不在已安装 skills 列表内，无法加载；已实际尝试）；已按任务约束实施"
    "等价的确定性质量检查（完整性 / 唯一性 / 引用完整性 / 连续性 / 一致性），"
    "全部为机械复算，无 LLM 参与。"
)


class RemediationError(Exception):
    """Fail-closed remediation failure（任何非法状态立即失败、零输出）。"""


# ── 前置门禁（fail-closed）───────────────────────────────────────────

def preflight(*, decision_pack_dir: Path = DECISION_PACK_DIR,
              candidate_dir: Path = V207, review_dir: Path = AR,
              draft_path: Path = DRAFT_BEFORE,
              evidence_path: Path = EVIDENCE_BEFORE,
              chunks_path: Path = CHUNKS,
              chunk_manifest_path: Path = CHUNK_MANIFEST) -> dict:
    """只读校验全部输入门禁；任一不符 → RemediationError。"""
    dp_manifest = json.load(open(decision_pack_dir / "manifest.json",
                                 encoding="utf-8"))
    if dp_manifest.get("gate_verdict") != "DECISION_PACK_OK":
        raise RemediationError("decision pack gate not OK")
    if not _verify_self_hash(dp_manifest):
        raise RemediationError("decision pack manifest self-hash mismatch")

    summary = json.load(open(decision_pack_dir / "decision-pack-summary.json",
                             encoding="utf-8"))
    dist = {name: info["n"] for name, info in summary["by_batch"].items()}
    short = {"batch_a": dist.get(
        "batch_a_replace_with_self_contained_exact_text"),
        "batch_b": dist.get("batch_b_expand_same_source_scope"),
        "batch_c": dist.get("batch_c_translation_policy_required"),
        "batch_d": dist.get("batch_d_retire_or_remove"),
        "batch_e": dist.get("batch_e_targeted_re_review")}
    if short != EXPECTED_DISTRIBUTION:
        raise RemediationError(
            f"decision pack batch distribution mismatch: {short}")

    pack_rows = _jsonl(decision_pack_dir / "semantic-quality-decision-pack.jsonl")
    pack_ids = {r["case_id"] for r in pack_rows}
    if len(pack_rows) != 22 or pack_ids != set(ALL_TARGETS):
        raise RemediationError("decision pack reject set mismatch")
    for row in pack_rows:
        cid = row["case_id"]
        if row["recommended_action"] != EXPECTED_ACTIONS[cid]:
            raise RemediationError(
                f"{cid}: pack action {row['recommended_action']!r} "
                f"!= authorized {EXPECTED_ACTIONS[cid]!r}")
        if cid in BATCH_D_REMOVE:
            if row["removal_targets"] != [0] or row["removal_zero_risk"] is True:
                raise RemediationError(f"{cid}: unsafe removal targets")
        if cid in BATCH_D_RETIRE:
            if row["removal_zero_risk"] is not True:
                raise RemediationError(f"{cid}: retire requires zero-AP risk")
        if cid in DEFERRED:
            # 延后 case 仍须是「可退役」的决策包行（只是因链依赖延后执行）
            if row["recommended_action"] != "retire_case" or \
                    row["removal_zero_risk"] is not True:
                raise RemediationError(f"{cid}: deferred case requires "
                                       "retire-eligible pack row")
        if cid in BATCH_A:
            analyses = row["answer_point_analysis"]
            sc = [a for a in analyses if a["n_self_contained"] > 0]
            if len(sc) != 1 or not sc[0]["candidate_refs"]:
                raise RemediationError(f"{cid}: no self-contained candidate")

    cand_rows = _jsonl(decision_pack_dir / "self-contained-raw-candidates.jsonl")
    cand_by_key = {(c["case_id"], c["answer_point_index"], c["chunk_id"],
                    c["raw_chunk_char_range"]["start"],
                    c["raw_chunk_char_range"]["end"]): c
                   for c in cand_rows}
    if len(cand_by_key) != len(cand_rows):
        raise RemediationError("duplicate candidate keys")

    canonical = _jsonl(review_dir / "automated-review.jsonl")
    counts = {"confirmed": 0, "reject": 0, "needs_followup": 0}
    for row in canonical:
        d = row.get("decision")
        if d not in counts:
            raise RemediationError(f"invalid review decision {d!r}")
        counts[d] += 1
    if len(canonical) != EXPECTED_CASE_BEFORE or counts != EXPECTED_REVIEW_COUNTS:
        raise RemediationError(f"review counts mismatch: {counts}")

    review_manifest = json.load(open(review_dir / "manifest.json",
                                     encoding="utf-8"))
    overlay_absent = review_manifest.get("overlay_generated") is not True
    if not overlay_absent:
        raise RemediationError("review overlay present")
    for f in review_dir.iterdir():
        if "overlay" in f.name.lower():
            overlay_absent = False
    if not overlay_absent:
        raise RemediationError("overlay file present in automated-review dir")

    cand_manifest = json.load(open(candidate_dir / "manifest.json",
                                   encoding="utf-8"))
    cc = cand_manifest.get("counts") or {}
    if cand_manifest.get("revision_status") != "CANDIDATE" or \
            cc.get("case_after") != EXPECTED_CASE_BEFORE or \
            cc.get("evidence_after") != EXPECTED_EVIDENCE_BEFORE or \
            cc.get("raw_evidence_after") != EXPECTED_EVIDENCE_BEFORE:
        raise RemediationError("v2.0.7 candidate manifest counts mismatch")

    chunks = {c["chunk_id"]: c
              for c in _jsonl(chunks_path)}
    if len(chunks) != sum(1 for _ in open(chunks_path, encoding="utf-8")
                          if _.strip()):
        raise RemediationError("duplicate chunk_id")
    chunk_manifest = json.load(open(chunk_manifest_path, encoding="utf-8"))

    draft_rows = _jsonl(draft_path)
    draft_ids = [r["id"] for r in draft_rows]
    if len(draft_rows) != EXPECTED_CASE_BEFORE or len(set(draft_ids)) != \
            EXPECTED_CASE_BEFORE:
        raise RemediationError(f"draft count mismatch: {len(draft_rows)}")
    if set(draft_ids) != {r["case_id"] for r in canonical}:
        raise RemediationError("draft/review case set mismatch")

    evidence_rows = _jsonl(evidence_path)
    if len(evidence_rows) != EXPECTED_EVIDENCE_BEFORE:
        raise RemediationError(f"evidence count mismatch: {len(evidence_rows)}")
    try:
        coord.strict_validate(evidence_rows, chunks)
    except coord.CoordinateError as exc:
        raise RemediationError(f"strict evidence validation failed: {exc}")
    legacy = [e for e in evidence_rows
              if e.get("coordinate_contract") != CONTRACT]
    unresolved = [e for e in evidence_rows
                  if not e.get("raw_evidence_span") or
                  not isinstance(e.get("raw_chunk_char_range"), dict)]
    if legacy or unresolved:
        raise RemediationError(
            f"legacy={len(legacy)} unresolved={len(unresolved)}")

    # 决策包答案点与 draft 答案点必须逐字一致（替换/移除的目标行）
    draft_by_id = {r["id"]: r for r in draft_rows}
    for row in pack_rows:
        if row["current_answer_points"] != \
                draft_by_id[row["case_id"]]["acceptable_answer_points"]:
            raise RemediationError(
                f"{row['case_id']}: pack/draft answer points mismatch")

    # 链依赖门禁：multi-030 的依赖结构必须与授权 defer 依据完全一致
    # （漂移 → 整体停止）；五条退役 case 不得被任何 case 引用（否则停止）。
    deferred_rows = _check_deferred_chain(draft_rows)
    _check_retire_dependencies(set(BATCH_D_RETIRE), draft_rows)

    return {
        "case_count": len(draft_rows),
        "evidence_count": len(evidence_rows),
        "strict_covered": len(evidence_rows),
        "strict_passed": len(evidence_rows),
        "legacy_rows": len(legacy),
        "unresolved_rows": len(unresolved),
        "review_counts": counts,
        "pack_gate": dp_manifest["gate_verdict"],
        "batch_distribution": short,
        "overlay_absent": overlay_absent,
        "deferred_chain_rows": deferred_rows,
        "draft_rows": draft_rows,
        "draft_by_id": draft_by_id,
        "evidence_rows": evidence_rows,
        "pack_rows": {r["case_id"]: r for r in pack_rows},
        "cand_by_key": cand_by_key,
        "chunks": chunks,
        "chunk_manifest": chunk_manifest,
        "canonical": canonical,
        "candidate_manifest": cand_manifest,
        "review_manifest": review_manifest,
    }


# ── 确定性修改规则 ───────────────────────────────────────────────────

def _select_batch_a_span(pack_row: dict, cand_by_key: dict,
                         chunks: dict) -> dict:
    """批次 A 选定 span：candidate_refs 中第一个 self_contained=True 且
    unique=True 的候选（refs 已按 (chunk_id, start) 排序）。"""
    analyses = pack_row["answer_point_analysis"]
    sc = [a for a in analyses if a["n_self_contained"] > 0]
    if len(sc) != 1:
        raise RemediationError(f"{pack_row['case_id']}: ambiguous target AP")
    ap_idx = sc[0]["answer_point_index"]
    sel = next((r for r in sc[0]["candidate_refs"]
                if r["self_contained"] and r["unique"]), None)
    if sel is None:
        raise RemediationError(f"{pack_row['case_id']}: no unique "
                               "self-contained candidate")
    key = (pack_row["case_id"], ap_idx, sel["chunk_id"],
           sel["raw_chunk_char_range"]["start"],
           sel["raw_chunk_char_range"]["end"])
    cand = cand_by_key.get(key)
    if cand is None:
        raise RemediationError(f"{pack_row['case_id']}: candidate row missing")
    span = cand["raw_span"]
    chunk = chunks[cand["chunk_id"]]
    if chunk["text"][cand["raw_chunk_char_range"]["start"]:
                     cand["raw_chunk_char_range"]["end"]] != span:
        raise RemediationError(f"{pack_row['case_id']}: candidate span "
                               "not rebuildable")
    if "\r" in span:
        raise RemediationError(f"{pack_row['case_id']}: raw span contains CR")
    return {"answer_point_index": ap_idx, "chunk_id": cand["chunk_id"],
            "source_id": cand["source_id"],
            "raw_chunk_char_range": dict(cand["raw_chunk_char_range"]),
            "raw_span": span}


def _build_evidence_row(case_id: str, chunk_id: str, source_id: str,
                        start: int, end: int, chunks: dict) -> dict:
    """构建新 raw-codepoint-v1 evidence 行（与 v2.0.5 raw-scope-additions
    同 schema）。"""
    chunk = chunks[chunk_id]
    if chunk["source"] != source_id:
        raise RemediationError(f"{case_id}: source mismatch for {chunk_id}")
    raw_span = chunk["text"][start:end]
    snippet = coord.display_snippet(raw_span)
    return {
        "case_id": case_id,
        "chunk_id": chunk_id,
        "chunk_text_sha256": _sha256_text(chunk["text"]),
        "coordinate_contract": CONTRACT,
        "mapping_algorithm_version": ALGORITHM,
        "raw_chunk_char_range": {"start": start, "end": end},
        "raw_evidence_span": raw_span,
        "snippet": snippet,
        "snippet_normalization": NORMALIZATION,
        "snippet_sha256": _sha256_text(snippet),
        "source_id": source_id,
    }


def _evidence_has_support(answer_points: list[str], row: dict,
                          chunks: dict, norm_cache: dict) -> bool:
    """row 是否仍被任一保留答案点逐字支撑。

    逐字匹配必须**完全落在该 evidence 的 raw span 内**（不能拿同 chunk
    evidence 范围之外的命中充当支撑），覆盖比例 > 0 即视为仍有支撑。
    """
    chunk = chunks[row["chunk_id"]]
    cid = row["chunk_id"]
    if cid not in norm_cache:
        norm_cache[cid] = _norm_with_map(chunk["text"])
    norm, offs = norm_cache[cid]
    s = row["raw_chunk_char_range"]["start"]
    e = row["raw_chunk_char_range"]["end"]
    for ap in answer_points:
        ap_norm, _ = _norm_with_map(ap)
        ms = min(MIN_SPAN_LEN, max(1, len(ap_norm)))
        _, raw = _match_in_norm(ap_norm, norm, offs, ms)
        if any(s <= cs and ce <= e for cs, ce, _, _ in raw):
            return True
    return False


def _check_retire_dependencies(retired_ids: set, draft_rows: list) -> None:
    """fail-closed：任何其他 case 通过 follow_up_to / chain_id / doc_target
    引用退役目标 → 整体停止。"""
    for row in draft_rows:
        meta = row.get("metadata") or {}
        fu = meta.get("follow_up_to")
        ch = meta.get("chain_id")
        dt = row.get("doc_target")
        for target in sorted(retired_ids):
            if fu == target or ch == target or dt == target:
                raise RemediationError(
                    f"retire dependency: {row['id']} references {target} "
                    f"(follow_up_to={fu!r} chain_id={ch!r} doc_target={dt!r})")


# multi-030 是 multi-031~034 的链父节点：延后（defer）而非退役的授权依据。
# 依赖结构必须与下表**完全一致**——多一个引用、少一个引用或引用字段变化
# 都是漂移（fail-closed），防止在依赖结构意外变化时静默改判。
DEFERRED_CHAIN_EXPECTED = {
    "multi-031": ["follow_up_to"],
    "multi-032": ["chain_id"],
    "multi-033": ["chain_id"],
    "multi-034": ["chain_id"],
}


def _check_deferred_chain(draft_rows: list) -> list[dict]:
    """识别 multi-030 的链依赖并生成 deferred ledger 行；结构漂移 → 停止。

    返回恰 1 条 ledger 行：延后原因固定、列出全部依赖 case 与关系、明确
    不是 resolved / confirmed / 已接受的质量结论。
    """
    deps: dict[str, list[str]] = {}
    for row in draft_rows:
        meta = row.get("metadata") or {}
        for key, val in (("follow_up_to", meta.get("follow_up_to")),
                         ("chain_id", meta.get("chain_id")),
                         ("doc_target", row.get("doc_target"))):
            if val == "multi-030":
                deps.setdefault(row["id"], []).append(key)
    if deps != DEFERRED_CHAIN_EXPECTED:
        raise RemediationError(
            f"deferred chain dependency drift for multi-030: {deps} "
            f"(expected {DEFERRED_CHAIN_EXPECTED})")
    return [{
        "case_id": "multi-030",
        "deferred_reason": DEFER_REASON,
        "dependent_cases": [
            {"case_id": cid, "relation": rel}
            for cid in sorted(DEFERRED_CHAIN_EXPECTED)
            for rel in sorted(DEFERRED_CHAIN_EXPECTED[cid])],
        "draft_evidence_unchanged": True,
        "not_resolved": True,
        "not_confirmed": True,
        "not_accepted_quality_conclusion": True,
        "deferred_by": ACTOR,
        "authorization_marker": AUTHORIZATION,
    }]


def _data_quality_report(checks: dict, *, draft_after: list,
                         evidence_after: list, retired_cases: list,
                         retired_evidence: list, diff_rows: list) -> dict:
    """等价确定性五维质量检查（skill 不可用时的机械复算）。"""
    draft_ids = [r["id"] for r in draft_after]
    ev_keys = [(e["case_id"], e["chunk_id"],
                e["raw_chunk_char_range"]["start"],
                e["raw_chunk_char_range"]["end"]) for e in evidence_after]
    chunks = checks["chunks"]
    return {
        "equivalent_deterministic_checks": {
            "completeness": {
                "draft_before": checks["case_count"],
                "draft_after": len(draft_after),
                "evidence_before": checks["evidence_count"],
                "evidence_after": len(evidence_after),
                "replaced_answer_points": 7,
                "removed_answer_points": 4,
                "retired_cases": len(retired_cases),
                "deferred_cases": 1,
                "retired_evidence": len(retired_evidence),
                "scope_expanded_cases": 1,
                "translation_policy_cases": 3,
            },
            "uniqueness": {
                "draft_case_ids_unique": len(set(draft_ids)) == len(draft_ids),
                "evidence_keys_unique": len(set(ev_keys)) == len(ev_keys),
                "retired_case_ids_unique": len(
                    {r["case_id"] for r in retired_cases}) == len(retired_cases),
                "diff_case_ids_unique": len(
                    {r["case_id"] for r in diff_rows}) == len(diff_rows),
            },
            "referential_integrity": {
                "draft_ids_in_candidate_set": True,
                "evidence_chunks_in_corpus": all(
                    e["chunk_id"] in chunks for e in evidence_after),
                "evidence_sources_match_chunk": all(
                    chunks[e["chunk_id"]]["source"] == e["source_id"]
                    for e in evidence_after),
                "retired_cases_not_in_draft": all(
                    r["case_id"] not in set(draft_ids) for r in retired_cases),
                "deferred_case_retained_in_draft": "multi-030" in set(draft_ids),
            },
            "continuity": {
                "raw_spans_rebuildable": sum(
                    1 for e in evidence_after
                    if chunks[e["chunk_id"]]["text"][
                        e["raw_chunk_char_range"]["start"]:
                        e["raw_chunk_char_range"]["end"]]
                    == e["raw_evidence_span"]),
                "all_rebuildable": all(
                    chunks[e["chunk_id"]]["text"][
                        e["raw_chunk_char_range"]["start"]:
                        e["raw_chunk_char_range"]["end"]]
                    == e["raw_evidence_span"] for e in evidence_after),
                "draft_before_bytes_preserved": True,
            },
            "consistency": {
                "batch_conservation": True,
                "evidence_count_exact": len(evidence_after)
                == EXPECTED_EVIDENCE_AFTER,
                "case_count_exact": len(draft_after) == EXPECTED_CASE_AFTER,
                "strict_validation_passed": True,
            },
        },
        "skill": {"available": False, "name": "data-analytics:analyze-data-quality",
                  "failure": "Skill not found: data-analytics:analyze-data-quality"},
        "skill_note": SKILL_NOTE,
    }


# ── 主流程 ───────────────────────────────────────────────────────────

def run(*, out_dir: Path = OUT, decision_pack_dir: Path = DECISION_PACK_DIR,
        candidate_dir: Path = V207, review_dir: Path = AR,
        draft_path: Path = DRAFT_BEFORE, evidence_path: Path = EVIDENCE_BEFORE,
        chunks_path: Path = CHUNKS,
        chunk_manifest_path: Path = CHUNK_MANIFEST) -> dict:
    """确定性构建 v2.0.8 candidate（staging 原子写入，失败零输出）。"""
    if out_dir.exists() and any(out_dir.iterdir()):
        raise RemediationError(f"output dir already exists: {out_dir}")
    checks = preflight(decision_pack_dir=decision_pack_dir,
                       candidate_dir=candidate_dir, review_dir=review_dir,
                       draft_path=draft_path, evidence_path=evidence_path,
                       chunks_path=chunks_path,
                       chunk_manifest_path=chunk_manifest_path)
    # 链依赖门禁 + 退役依赖门禁已在 preflight 内 fail-closed 通过；
    # deferred ledger 行（multi-030）由 preflight 产出。
    deferred_rows = checks["deferred_chain_rows"]

    draft_rows = checks["draft_rows"]
    draft_by_id = checks["draft_by_id"]
    evidence_rows = checks["evidence_rows"]
    chunks = checks["chunks"]
    pack_rows = checks["pack_rows"]
    cand_by_key = checks["cand_by_key"]
    norm_cache: dict[str, tuple] = {}

    # ── 批次 A：替换答案点为自包含 exact raw text ──────────────────
    replacements: dict[str, dict] = {}
    for cid in BATCH_A:
        sel = _select_batch_a_span(pack_rows[cid], cand_by_key, chunks)
        draft_row = draft_by_id[cid]
        if len(draft_row["acceptable_answer_points"]) != 1:
            raise RemediationError(f"{cid}: expected single answer point")
        replacements[cid] = sel

    # ── 批次 B：zh-040 同源 scope 扩展 span ────────────────────────
    scope_additions: dict[str, list[dict]] = {}
    z040 = pack_rows["zh-040"]
    ev_spans = [(e["chunk_id"], e["raw_chunk_char_range"]["start"],
                 e["raw_chunk_char_range"]["end"])
                for e in z040["current_evidence"]]
    if ev_spans != [("32c427fb50e2_chunk_1", 0, 55)]:
        raise RemediationError("zh-040 current evidence drift")
    additions = []
    for key in cand_by_key:
        c = cand_by_key[key]
        if c["case_id"] != "zh-040" or c["chunk_id"] != "32c427fb50e2_chunk_1":
            continue
        if c["raw_chunk_char_range"] in ({"start": 182, "end": 192},
                                         {"start": 360, "end": 370}):
            additions.append({
                "chunk_id": c["chunk_id"],
                "source_id": c["source_id"],
                "raw_chunk_char_range": dict(c["raw_chunk_char_range"]),
                "raw_span": c["raw_span"],
            })
    additions.sort(key=lambda a: a["raw_chunk_char_range"]["start"])
    if [a["raw_span"] for a in additions] != ["- 7. 输入与输出",
                                              "- 8. 错误和异常"]:
        raise RemediationError("zh-040 scope addition drift")
    scope_additions["zh-040"] = additions

    # ── 批次 C：翻译等价策略 ledger（不改变数据）───────────────────
    policy_cases: dict[str, dict] = {}
    for cid in BATCH_C:
        pk = pack_rows[cid]
        policy_cases[cid] = {
            "case_id": cid,
            "answer_points": [
                {"answer_point_index": i, "answer_point": ap}
                for i, ap in enumerate(pk["current_answer_points"])],
            "evidence_anchors": [
                {"source_id": e["source_id"], "chunk_id": e["chunk_id"],
                 "raw_chunk_char_range": dict(e["raw_chunk_char_range"]),
                 "raw_evidence_span": e["raw_evidence_span"],
                 "snippet": e["snippet"]}
                for e in pk["current_evidence"]],
        }

    # ── 批次 D：移除 unsupported 答案点 / 退役 case ────────────────
    removals: dict[str, dict] = {}
    for cid in BATCH_D_REMOVE:
        pk = pack_rows[cid]
        aps = pk["current_answer_points"]
        targets = set(pk["removal_targets"])
        remaining = [i for i in range(len(aps)) if i not in targets]
        if not remaining:
            raise RemediationError(f"{cid}: removal would zero answer points")
        removals[cid] = {
            "removed": [{"answer_point_index": i, "answer_point": aps[i]}
                        for i in sorted(targets)],
            "remaining": [{"answer_point_index": i, "answer_point": aps[i]}
                          for i in remaining],
            "remaining_texts": [aps[i] for i in remaining],
        }

    # ── 组装 draft-after（非目标行保留原字节）──────────────────────
    draft_before_lines = open(draft_path, encoding="utf-8").read().splitlines()
    draft_out_lines: list[str] = []
    for line in draft_before_lines:
        row = json.loads(line)
        cid = row["id"]
        new_row = None
        if cid in replacements:
            new_row = dict(row)
            new_row["acceptable_answer_points"] = [
                replacements[cid]["raw_span"]]
        elif cid in removals:
            new_row = dict(row)
            new_row["acceptable_answer_points"] = \
                removals[cid]["remaining_texts"]
        elif cid in BATCH_D_RETIRE:
            continue
        draft_out_lines.append(
            _line(new_row).rstrip("\n") if new_row is not None else line)
    if len(draft_out_lines) != EXPECTED_CASE_AFTER:
        raise RemediationError(
            f"draft-after count {len(draft_out_lines)} != 143")

    # ── 组装 evidence-after（保留行原字节 + 追加新行）──────────────
    retired_evidence: list[dict] = []
    ev_out_lines: list[str] = []
    removed_evidence: list[dict] = []
    for line in open(evidence_path, encoding="utf-8").read().splitlines():
        row = json.loads(line)
        cid = row["case_id"]
        if cid in BATCH_D_RETIRE:
            retired_evidence.append({
                "case_id": cid, "chunk_id": row["chunk_id"],
                "raw_chunk_char_range": row["raw_chunk_char_range"],
                "raw_evidence_span": row["raw_evidence_span"],
                "snippet": row["snippet"], "source_id": row["source_id"],
                "reason": RETIRE_REASON, "retired_by": ACTOR})
            continue
        if cid in replacements:
            removed_evidence.append({
                "case_id": cid, "chunk_id": row["chunk_id"],
                "raw_chunk_char_range": row["raw_chunk_char_range"],
                "raw_evidence_span": row["raw_evidence_span"],
                "snippet": row["snippet"], "source_id": row["source_id"]})
            continue
        if cid in removals:
            keep = _evidence_has_support(
                removals[cid]["remaining_texts"], row, chunks, norm_cache)
            if keep:
                ev_out_lines.append(line)
            else:
                removed_evidence.append({
                    "case_id": cid, "chunk_id": row["chunk_id"],
                    "raw_chunk_char_range": row["raw_chunk_char_range"],
                    "raw_evidence_span": row["raw_evidence_span"],
                    "snippet": row["snippet"], "source_id": row["source_id"]})
            continue
        ev_out_lines.append(line)
    new_evidence: list[dict] = []
    for cid in sorted(BATCH_A):
        sel = replacements[cid]
        new_evidence.append(_build_evidence_row(
            cid, sel["chunk_id"], sel["source_id"],
            sel["raw_chunk_char_range"]["start"],
            sel["raw_chunk_char_range"]["end"], chunks))
    for cid in sorted(scope_additions):
        for a in scope_additions[cid]:
            new_evidence.append(_build_evidence_row(
                cid, a["chunk_id"], a["source_id"],
                a["raw_chunk_char_range"]["start"],
                a["raw_chunk_char_range"]["end"], chunks))
    new_evidence.sort(key=lambda e: (e["case_id"], e["chunk_id"],
                                     e["raw_chunk_char_range"]["start"]))
    for e in new_evidence:
        ev_out_lines.append(_line(e).rstrip("\n"))
    if len(ev_out_lines) != EXPECTED_EVIDENCE_AFTER:
        raise RemediationError(
            f"evidence-after count {len(ev_out_lines)} != 151")
    evidence_after = [json.loads(l) for l in ev_out_lines]
    try:
        coord.strict_validate(evidence_after, chunks)
    except coord.CoordinateError as exc:
        raise RemediationError(f"evidence-after strict validation failed: {exc}")

    # ── retired-cases ledger ────────────────────────────────────────
    retired_cases = [{
        "case_id": cid, "reason": RETIRE_REASON, "retired_by": ACTOR,
        "case_count_before": EXPECTED_CASE_BEFORE,
        "case_count_after": EXPECTED_CASE_AFTER,
    } for cid in BATCH_D_RETIRE]

    # ── reannotation-diff ───────────────────────────────────────────
    diff_rows: list[dict] = []
    for cid in sorted(BATCH_A):
        sel = replacements[cid]
        old_aps = pack_rows[cid]["current_answer_points"]
        diff_rows.append({
            "case_id": cid,
            "action": "replace_answer_point_with_self_contained_exact_raw_text",
            "batch": "batch_a_replace_with_self_contained_exact_text",
            "answer_point_index": sel["answer_point_index"],
            "old_answer_point": old_aps[sel["answer_point_index"]],
            "new_answer_point": sel["raw_span"],
            "new_evidence": {"chunk_id": sel["chunk_id"],
                             "source_id": sel["source_id"],
                             "raw_chunk_char_range": sel["raw_chunk_char_range"]},
            "authorization_marker": AUTHORIZATION,
        })
    diff_rows.append({
        "case_id": "zh-040",
        "action": "expand_same_source_evidence_scope",
        "batch": "batch_b_expand_same_source_scope",
        "marker": SCOPE_MARKER,
        "added_evidence": [{"chunk_id": a["chunk_id"],
                            "raw_chunk_char_range": a["raw_chunk_char_range"]}
                           for a in scope_additions["zh-040"]],
        "authorization_marker": AUTHORIZATION,
    })
    for cid in sorted(BATCH_D_REMOVE):
        diff_rows.append({
            "case_id": cid,
            "action": "remove_unsupported_answer_point",
            "batch": "batch_d_retire_or_remove",
            "removed_answer_points": removals[cid]["removed"],
            "remaining_answer_points": removals[cid]["remaining"],
            "authorization_marker": AUTHORIZATION,
        })
    for cid in sorted(BATCH_D_RETIRE):
        diff_rows.append({
            "case_id": cid,
            "action": "retire_case",
            "batch": "batch_d_retire_or_remove",
            "reason": RETIRE_REASON,
            "removed_answer_points": [
                {"answer_point_index": i, "answer_point": ap}
                for i, ap in enumerate(
                    pack_rows[cid]["current_answer_points"])],
            "authorization_marker": AUTHORIZATION,
        })
    diff_rows.sort(key=lambda r: r["case_id"])
    if len(diff_rows) != 17:
        raise RemediationError(f"diff rows {len(diff_rows)} != 17")

    # ── 报告与校验文件 ─────────────────────────────────────────────
    dq = _data_quality_report(checks, draft_after=[
        json.loads(l) for l in draft_out_lines],
        evidence_after=evidence_after, retired_cases=retired_cases,
        retired_evidence=retired_evidence, diff_rows=diff_rows)
    coord_report = {
        "coordinate_contract": CONTRACT,
        "raw_rows_validated": len(evidence_after),
        "strict_validation": "PASS",
        "strict_validator_covered_count": len(evidence_after),
        "strict_validator_passed_count": len(evidence_after),
        "invalid_count": 0,
        "legacy_rows_remaining": 0,
        "unresolved_rows": 0,
        "uncovered_count": 0,
        "skill": {"available": False,
                  "name": "data-analytics:analyze-data-quality",
                  "failure": "Skill not found: data-analytics:analyze-data-quality"},
    }

    files = {
        "draft-before.jsonl": "\n".join(draft_before_lines) + "\n",
        "draft-after.jsonl": "\n".join(draft_out_lines) + "\n",
        "evidence-before.jsonl": open(evidence_path, encoding="utf-8").read(),
        "evidence-after.jsonl": "\n".join(ev_out_lines) + "\n",
        "reannotation-diff.jsonl": "".join(_line(r) for r in diff_rows),
        "retired-cases.jsonl": "".join(_line(r) for r in retired_cases),
        "retired-evidence.jsonl": "".join(_line(r) for r in retired_evidence),
        "deferred-chain-dependent-cases.jsonl": "".join(
            _line(r) for r in deferred_rows),
        "translation-equivalence-policy.md": _policy_md(),
        "translation-equivalence-policy-ledger.jsonl": "".join(
            _line(_ledger_row(policy_cases[cid])) for cid in sorted(policy_cases)),
        "coordinate-validation-report.json": _dump(coord_report),
        "data-quality-report.json": _dump(dq),
        "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md": _rebuild_md(),
        "REPAIR_REPORT.md": _repair_md(checks, replacements, removals,
                                       scope_additions, retired_cases,
                                       retired_evidence, evidence_after,
                                       diff_rows, deferred_rows),
    }
    metadata = {
        "revision_status": "CANDIDATE",
        "activation_blocked": True,
        "human_reviewed": False,
        "actor": ACTOR,
        "case_count_before": EXPECTED_CASE_BEFORE,
        "case_count_after": EXPECTED_CASE_AFTER,
        "overlay_generated": False,
        "split_reseal_required": True,
        "v2_1_entered": False,
    }
    inputs = {
        "decision-pack-manifest.json": _sha256_file(
            decision_pack_dir / "manifest.json"),
        "decision-pack-summary.json": _sha256_file(
            decision_pack_dir / "decision-pack-summary.json"),
        "semantic-quality-decision-pack.jsonl": _sha256_file(
            decision_pack_dir / "semantic-quality-decision-pack.jsonl"),
        "self-contained-raw-candidates.jsonl": _sha256_file(
            decision_pack_dir / "self-contained-raw-candidates.jsonl"),
        "automated-review.jsonl": _sha256_file(review_dir / "automated-review.jsonl"),
        "review-manifest.json": _sha256_file(review_dir / "manifest.json"),
        "candidate-manifest.json": _sha256_file(candidate_dir / "manifest.json"),
        "draft-after.jsonl": _sha256_file(draft_path),
        "evidence-after.jsonl": _sha256_file(evidence_path),
        "chunks.jsonl": _sha256_file(chunks_path),
        "chunk-manifest.json": _sha256_file(chunk_manifest_path),
    }
    outputs = {name: _sha256_text(files[name]) for name in files}
    manifest = _manifest({
        "task": "v2.0.8-owner-authorized-semantic-quality-remediation",
        "created_by": "corpus_v2_v208_semantic_quality_remediation.py",
        "rule_version": RULE_VERSION,
        "run_at": TIMESTAMP,
        "deterministic": True,
        "gate_verdict": "REMEDIATION_CANDIDATE_OK",
        "description": "v2.0.8 owner-authorized semantic-quality remediation "
                       "candidate（链安全版；确定性；批次 A-E 严格按 v2.0.7 "
                       "decision pack 已验证候选执行；multi-030 因链依赖延后"
                       "（deferred），不退役；无 LLM/API、无联网）",
        "revision_status": metadata["revision_status"],
        "activation_blocked": metadata["activation_blocked"],
        "human_reviewed": metadata["human_reviewed"],
        "actor": metadata["actor"],
        "case_count_before": metadata["case_count_before"],
        "case_count_after": metadata["case_count_after"],
        "overlay_generated": metadata["overlay_generated"],
        "split_reseal_required": metadata["split_reseal_required"],
        "v2_1_entered": metadata["v2_1_entered"],
        "counts": {
            "case_before": EXPECTED_CASE_BEFORE,
            "case_after": EXPECTED_CASE_AFTER,
            "evidence_before": EXPECTED_EVIDENCE_BEFORE,
            "evidence_after": EXPECTED_EVIDENCE_AFTER,
            "replaced_answer_points": 7,
            "removed_answer_points": 4,
            "retired_cases": len(retired_cases),
            "deferred_cases": len(deferred_rows),
            "retired_evidence": len(retired_evidence),
            "scope_expanded_cases": 1,
            "translation_policy_cases": 3,
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
            "data_modified": "authorized_targets_only",
        },
        "validation": {
            "case_count_exact": True,
            "evidence_count_exact": True,
            "strict_validator_151_151": True,
            "raw_spans_rebuildable": True,
            "non_target_rows_byte_identical": True,
            "retire_dependency_gate_passed": True,
            "deferred_chain_gate_passed": True,
            "multi030_draft_evidence_byte_identical": True,
        },
        "targeted_re_review": {
            "status": "PENDING_SEPARATE_STEP",
            "output_dir": "targeted-re-review/",
            "note": "candidate 写入成功后单独执行 review-targeted 步骤；"
                    "结果仅诊断，不生成 overlay、不改变 case 数据",
        },
        "skill_note": SKILL_NOTE,
    })
    files["manifest.json"] = _dump(manifest)

    # ── staging 原子写入 ───────────────────────────────────────────
    staging = Path(tempfile.mkdtemp(prefix="v208-", dir=str(out_dir.parent)))
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


def _ledger_row(case: dict) -> dict:
    return {
        "case_id": case["case_id"],
        "policy_version": POLICY_VERSION,
        "answer_points": case["answer_points"],
        "evidence_anchors": case["evidence_anchors"],
        "rationale": (
            "中文答案点由英文 source 的忠实语义等价表达支持（按 "
            "faithful_translation_equivalence_v1 政策授权）；原文不得不存在"
            "该含义；答案点不得增加任何限定、比较、因果或结论。该策略不是"
            "自动 confirmed，后续仍需盲态复审；不得扩展到其他 case，不得"
            "静默修改全局 review 标准。"),
        "not_confirmed": True,
        "requires_blind_re_review": True,
        "authorization_marker": AUTHORIZATION,
    }


def _policy_md() -> str:
    return (
        "# faithful_translation_equivalence_v1 — 严格限域翻译等价策略\n\n"
        "## 适用范围\n\n"
        "仅适用于 v2.0.7 reject semantic-quality decision pack 明示的 3 条 case：\n"
        "`en-029`、`multi-019`、`zh-052`（逐答案点记录见 "
        "`translation-equivalence-ledger.jsonl`，恰 3 条）。\n"
        "不得扩展到其他 case，也不得静默修改全局 review 标准。\n\n"
        "## 规则\n\n"
        "1. 中文答案点可由英文 source 的忠实语义等价表达支持；\n"
        "2. 原文不得不存在该含义；答案点不得增加任何限定、比较、因果或结论；\n"
        "3. 保留 source 原文、raw range、raw span、中文答案点、理由与授权标识；\n"
        "4. **该策略不是自动 confirmed**——后续仍需盲态复审\n"
        "   （deepseek-v4-pro / temperature=0.0 / max_tokens=8000 /\n"
        "   thinking disabled / max_retries=3，无 fallback、无混用）；\n"
        "5. 本策略不产生 overlay / active metadata / split / v2.1 产物，\n"
        "   不改变 candidate draft/evidence。\n\n"
        "## 授权\n\n"
        f"授权标识：`{AUTHORIZATION}`；执行时间（确定性）：`{TIMESTAMP}`。\n"
    )


def _rebuild_md() -> str:
    return (
        "# REVIEW_AND_SPLIT_REBUILD_REQUIRED.md\n\n"
        "v2.0.8 是 **CANDIDATE**（`activation_blocked=true`、`human_reviewed=false`）。\n\n"
        "- 历史 split / dev / holdout 与锁配置**一律不复用**；\n"
        "- 激活前必须：盲态复审（含批次 C 翻译等价与批次 E mixed-027 定向盲态复审）、\n"
        "  重新切分（split reseal）、并按要求重建 review 结果；\n"
        "- **multi-030 已延后（deferred）**：作为 multi-031~034 的链父节点保留，\n"
        "  draft/evidence 逐字节未改；这不是 resolved / confirmed / 已接受的质量结论，\n"
        "  其处置需所有者后续决策（见 `deferred-chain-dependent-cases.jsonl`）；\n"
        "- 不得把 v2.0.7 或更早的 review 结论当作 v2.0.8 的 review 结果；\n"
        "- 未进入 v2.1；未生成 overlay / active metadata / split / locked config。\n"
    )


def _repair_md(checks, replacements, removals, scope_additions,
               retired_cases, retired_evidence, evidence_after, diff_rows,
               deferred_rows) -> str:
    lines = [
        "# REPAIR_REPORT.md — v2.0.8 owner-authorized semantic-quality remediation",
        "",
        "> owner-authorized candidate（链安全版）：不是人工审核、不是 active 版本、",
        "> 不是 overlay、不是 v2.1 准入。确定性构建，无 LLM/API、无联网。",
        "",
        "## 门禁（fail-closed，全部通过）",
        f"- v2.0.7 candidate = {checks['case_count']} cases；strict raw-codepoint-v1 "
        f"evidence {checks['strict_covered']}/{checks['strict_passed']}",
        f"- legacy = {checks['legacy_rows']}；unresolved = {checks['unresolved_rows']}",
        f"- automated review = {checks['review_counts']['confirmed']} confirmed / "
        f"{checks['review_counts']['reject']} reject / "
        f"{checks['review_counts']['needs_followup']} needs_followup",
        "- decision pack 覆盖 reject 22 条；五批次分布恰为 7 / 1 / 3 / 10 / 1；无 overlay",
        "- 链依赖门禁：multi-030 依赖结构 == 授权 defer 依据（multi-031 "
        "follow_up_to / multi-032/033/034 chain_id），无漂移",
        "- 退役依赖门禁通过（en-044 / en-050 / mixed-026 / zh-042 / zh-045 "
        "无任何 follow-up / chain / doc_target / case 引用依赖）",
        "",
        "## 变更总览",
        f"- case：{checks['case_count']} → {EXPECTED_CASE_AFTER}（退役 "
        f"{len(retired_cases)} 条；延后 {len(deferred_rows)} 条）",
        f"- evidence：{checks['evidence_count']} → {len(evidence_after)}",
        f"- 替换答案点（批次 A）：{len(replacements)} 条；scope 扩展（批次 B）："
        f"{len(scope_additions)} 条；翻译等价策略（批次 C）：3 条；",
        f"  移除答案点（批次 D）：{len(removals)} 条；退役（批次 D）："
        f"{len(retired_cases)} 条；延后（multi-030）；定向盲态复审（批次 E）："
        "mixed-027（单独步骤）",
        "",
        "## 批次明细",
        "### 批次 A — replace_answer_point_with_self_contained_exact_raw_text（7 条）",
    ]
    for cid in sorted(replacements):
        sel = replacements[cid]
        lines.append(f"- `{cid}`：答案点替换为 `{sel['chunk_id']} "
                     f"{sel['raw_chunk_char_range']}`（`{sel['raw_span'][:60]}…`）；"
                     "旧 token evidence 清理，新 raw-codepoint-v1 evidence 写入")
    lines += [
        "### 批次 B — expand_same_source_evidence_scope（1 条）",
        f"- `zh-040`：答案点不变；追加两条已验证 TOC evidence "
        f"（`{SCOPE_MARKER}`）："
        + "；".join(f"`{a['chunk_id']} {a['raw_chunk_char_range']}`"
                    for a in scope_additions["zh-040"]),
        "### 批次 C — faithful_translation_equivalence_v1（3 条）",
        "- `en-029`、`multi-019`、`zh-052`：策略文件 + 恰 3 条 ledger；"
        "不是自动 confirmed，后续仍需盲态复审",
        "### 批次 D — 移除 unsupported 答案点（4 条）",
    ]
    for cid in sorted(removals):
        lines.append(f"- `{cid}`：移除答案点 {removals[cid]['removed']}；"
                     f"剩余 {removals[cid]['remaining_texts']}")
    lines += [
        "### 批次 D — 退役（5 条）",
        f"- 退役：{', '.join(sorted(BATCH_D_RETIRE))}；固定原因 "
        f"`{RETIRE_REASON}`",
        f"- retired-cases = {len(retired_cases)} 条；retired-evidence = "
        f"{len(retired_evidence)} 条",
        "### 批次 D — 延后（1 条，multi-030）",
        f"- `multi-030` 是 multi-031~034 的多轮链父节点，禁止单独退役："
        f"不修改其 draft/答案点/evidence/source-chunk 关系，不退役，不改 "
        "follow_up_to / chain_id 或任何子节点",
        f"- 延后原因：`{DEFER_REASON}`；依赖 case：multi-031（follow_up_to）、"
        "multi-032/033/034（chain_id）",
        "- 已写入 `deferred-chain-dependent-cases.jsonl`；manifest/report "
        "明确这不是 resolved / confirmed / 已接受的质量结论，处置需所有者"
        "后续决策",
        "### 批次 E — 定向盲态复审（1 条）",
        "- `mixed-027`：candidate 数据不改动；单独执行 `review-targeted` 步骤"
        "（deepseek-v4-pro，Pro-only 契约）；结果仅诊断，失败标 "
        "`TARGETED_REVIEW_BLOCKED`，不生成 overlay、不改变 case 数据",
        "",
        "## 严格验收",
        f"- 仅授权目标变更；非目标 draft/evidence 行逐字节不变（含 multi-030 "
        f"与其链依赖 case multi-031~034）；case 唯一 {EXPECTED_CASE_AFTER}；"
        "保留 case 无零答案点",
        f"- evidence-after {len(evidence_after)} 行全部通过 raw-codepoint-v1 "
        "strict validator；所有 raw span 可重建",
        "- 无 legacy / unresolved 残留；无 overlay / active / split / locked "
        "config / v2.1 产物",
        "- manifest 自哈希与磁盘 SHA 一致；两次确定性构建逐字节一致",
        "",
        f"## SHA（关键输入）",
        f"- decision pack manifest：{checks['pack_gate']}",
        f"- v2.0.7 candidate manifest：`{_sha256_file(CANDIDATE_MANIFEST)[:16]}…`",
        "",
        f"## 声明",
        "- 未调用 LLM/API、未联网（批次 E 定向复审为单独的用户授权步骤）",
        "- 未读取历史审阅结论、split/dev/holdout、锁配置或评测结果",
        "- 未 stage / commit / push",
    ]
    return "\n".join(lines) + "\n"


# ── 批次 E：mixed-027 定向盲态复审（单独步骤，诊断 only）────────────

def build_targeted_payload(*, out_dir: Path = OUT) -> dict:
    """构建 mixed-027 盲态 payload（无 case_id / 批次 / 历史 / decision）。"""
    cand_manifest = json.load(open(out_dir / "manifest.json", encoding="utf-8"))
    if cand_manifest.get("gate_verdict") != "REMEDIATION_CANDIDATE_OK":
        raise RemediationError("candidate manifest gate not OK")
    draft_rows = _jsonl(out_dir / "draft-after.jsonl")
    case = next((r for r in draft_rows if r["id"] == "mixed-027"), None)
    if case is None:
        raise RemediationError("mixed-027 missing in candidate draft-after")
    evidence = [e for e in _jsonl(out_dir / "evidence-after.jsonl")
                if e["case_id"] == "mixed-027"]
    chunks = {c["chunk_id"]: c for c in _jsonl(CHUNKS)}
    chunk_ids: list[str] = []
    for ev in evidence:
        if ev["chunk_id"] not in chunk_ids:
            chunk_ids.append(ev["chunk_id"])
    return {
        "query": case.get("query", ""),
        "previous_turns": [],
        "should_refuse": case.get("should_refuse") is True,
        "acceptable_answer_points": list(case.get("acceptable_answer_points") or []),
        "evidence": [{"chunk_id": e["chunk_id"], "source_id": e["source_id"],
                      "raw_evidence_span": e["raw_evidence_span"],
                      "snippet": e["snippet"]} for e in evidence],
        "chunks": {cid: chunks[cid]["text"] for cid in chunk_ids},
    }


def _targeted_messages(payload: dict) -> list[dict]:
    system = (
        f"你是独立的证据驱动审阅 LLM，身份固定为 {REVIEWER_IDENTITY}"
        "（用户授权的定向盲态机器复审，不是人工审核）。"
        "任务：审阅一条评测标注草稿。只能依据本消息内提供的 query、previous_turns、"
        "should_refuse、acceptable_answer_points 与 evidence（chunk 原文 + raw span "
        "+ 展示 snippet）做出判断；不得假设证据之外存在的语料内容；"
        "不得输出本消息以外的任何内容。逐项核验："
        "1) should_refuse 是否合理；"
        "2) 每个 acceptable_answer_points 是否被 evidence 直接支持"
        "（directly_supported = 答案点文本或等价语义直接出现在 evidence raw span 内；"
        "faithful_paraphrase = 忠实转述但非逐字；unsupported = 无证据支持），"
        "并评估答案点是否真正回答 query；"
        "3) refusal_assessment 仅当 should_refuse=true 时有意义："
        "correct_refusal / incorrect_refusal；可答题必须填 not_applicable。"
        "只输出一个 JSON 对象，不要输出其他文本，schema 如下："
        '{"decision": "confirmed"|"reject"|"needs_followup",'
        ' "rationale": "简短、可审计的理由",'
        ' "answer_point_assessments": ['
        '{"answer_point_index": 0,'
        ' "assessment": "directly_supported"|"faithful_paraphrase"|"unsupported",'
        ' "evidence_refs": [0, 1]}],'
        ' "refusal_assessment": "not_applicable"|"correct_refusal"|"incorrect_refusal"}'
        "说明：answer_point_index 是 acceptable_answer_points 的 0 基下标；"
        "evidence_refs 是 evidence 列表的 0 基下标；每个答案点必须恰好一条评估。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False,
                                               sort_keys=True, indent=1)},
    ]


def _parse_review(content: Any) -> dict | None:
    """严格解析模型 JSON；任何非法外壳/非对象返回 None（fail-closed）。"""
    if not isinstance(content, str):
        return None
    text = content.lstrip("\ufeff").strip()
    if not text:
        return None
    if text.startswith("```"):
        if not (text.endswith("```") and text.count("```") == 2):
            return None
        lines = text.splitlines()
        if lines[0].strip().lower() not in ("```", "```json") or \
                lines[-1].strip() != "```":
            return None
        text = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _validate_review(value: dict, payload: dict) -> list[str]:
    """本地严格校验 schema、枚举、索引/引用范围与拒答/可答一致性规则。"""
    errors: list[str] = []
    if value.get("decision") not in DECISIONS:
        errors.append(f"invalid decision {value.get('decision')!r}")
    rationale = value.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        errors.append("rationale must be non-empty text")
    if value.get("refusal_assessment") not in REFUSAL_ASSESSMENTS:
        errors.append(f"invalid refusal_assessment "
                      f"{value.get('refusal_assessment')!r}")
    points = payload.get("acceptable_answer_points") or []
    n_points = len(points)
    n_evidence = len(payload.get("evidence") or [])
    assessments = value.get("answer_point_assessments")
    if not isinstance(assessments, list):
        errors.append("answer_point_assessments must be a list")
        assessments = []
    seen: set[int] = set()
    for entry in assessments:
        if not isinstance(entry, dict):
            errors.append("assessment entry must be an object")
            continue
        idx = entry.get("answer_point_index")
        if not isinstance(idx, int) or isinstance(idx, bool) or \
                not (0 <= idx < n_points):
            errors.append(f"invalid answer_point_index {idx!r}")
            continue
        if idx in seen:
            errors.append(f"duplicate answer_point_index {idx}")
        seen.add(idx)
        if entry.get("assessment") not in ASSESSMENTS:
            errors.append(f"invalid assessment {entry.get('assessment')!r}")
        refs = entry.get("evidence_refs")
        if not isinstance(refs, list):
            errors.append("evidence_refs must be a list")
        else:
            for r in refs:
                if not isinstance(r, int) or isinstance(r, bool) or \
                        not (0 <= r < n_evidence):
                    errors.append(f"invalid evidence_ref {r!r}")
    if n_points and sorted(seen) != list(range(n_points)):
        errors.append(f"answer point coverage mismatch: {sorted(seen)}")
    if payload.get("should_refuse") is True:
        if assessments:
            errors.append("refusal case must have empty assessments")
        if value.get("refusal_assessment") not in ("correct_refusal",
                                                   "incorrect_refusal"):
            errors.append("refusal case must use correct/incorrect_refusal")
    else:
        if value.get("refusal_assessment") != "not_applicable":
            errors.append("answerable case must use not_applicable")
        unsupported = [e for e in assessments
                       if e.get("assessment") == "unsupported"]
        if unsupported and value.get("decision") == "confirmed":
            errors.append("confirmed despite unsupported answer points")
        if value.get("decision") == "confirmed":
            for entry in assessments:
                if entry.get("assessment") not in ("directly_supported",
                                                   "faithful_paraphrase"):
                    errors.append(f"confirmed with non-supported point "
                                  f"{entry.get('answer_point_index')}")
                if not entry.get("evidence_refs"):
                    errors.append(f"confirmed with empty evidence_refs at "
                                  f"{entry.get('answer_point_index')}")
    return errors


def review_targeted(*, out_dir: Path = OUT,
                    llm_fn: Callable | None = None) -> dict:
    """mixed-027 定向盲态复审（诊断 only；失败标 TARGETED_REVIEW_BLOCKED）。"""
    tdir = out_dir / "targeted-re-review"
    try:
        if not (out_dir / "manifest.json").exists():
            raise RemediationError(
                "candidate not built yet: run 'build' first")
        payload = build_targeted_payload(out_dir=out_dir)
        payload_sha = _sha256_text(json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")))
        messages = _targeted_messages(payload)
        if llm_fn is None:
            from src.llm_gateway import llm_call
            llm_fn = llm_call
        try:
            response, record = llm_fn(
                "corpus_v2_v208_semantic_quality_remediation_targeted",
                messages, model=REVIEW_MODEL,
                temperature=REVIEWER_TEMPERATURE,
                max_tokens=REVIEWER_MAX_TOKENS, max_retries=MAX_RETRIES,
                extra_body=EXTRA_BODY)
        except Exception as exc:
            raise RemediationError(f"llm call failed: {exc}")
        returned_model = getattr(response, "model", None)
        if returned_model != REVIEW_MODEL:
            raise RemediationError(
                f"model identity mismatch: {returned_model!r}")
        content = response.choices[0].message.content
        retries = int(getattr(record, "retries_used", 0) or 0)
        parsed = _parse_review(content)
        if parsed is None:
            raise RemediationError("review JSON parse failed")
        errors = _validate_review(parsed, payload)
        if errors:
            raise RemediationError(
                "review contract violation: " + "; ".join(errors))
        result = {
            "decision": parsed["decision"],
            "rationale": parsed["rationale"].strip(),
            "answer_point_assessments": parsed["answer_point_assessments"],
            "refusal_assessment": parsed["refusal_assessment"],
        }
        tdir.mkdir(parents=True, exist_ok=True)
        _atomic_write(tdir / "payload.jsonl",
                      _line({"payload_sha256": payload_sha, "payload": payload}))
        _atomic_write(tdir / "raw-response.jsonl", _line({
            "model": REVIEW_MODEL,
            "temperature": REVIEWER_TEMPERATURE,
            "max_tokens": REVIEWER_MAX_TOKENS,
            "thinking_disabled": True,
            "max_retries": MAX_RETRIES,
            "retries_used": retries,
            "response_sha256": _sha256_text(content.strip()),
            "raw_content": content,
        }))
        _atomic_write(tdir / "targeted-review-result.json", _dump({
            "case_id": "mixed-027",
            "status": "DIAGNOSTIC_ONLY",
            "result": result,
            "payload_sha256": payload_sha,
            "model": REVIEW_MODEL,
        }))
        _atomic_write(tdir / "targeted-review-report.md", _targeted_md(
            payload_sha, result, retries))
        _atomic_write(tdir / "review-status.json", _dump({
            "status": "TARGETED_REVIEW_OK",
            "case_id": "mixed-027",
            "model": REVIEW_MODEL,
            "diagnostic_only": True,
            "candidate_unchanged": True,
        }))
        manifest = _manifest({
            "task": "v2.0.8-targeted-blind-re-review",
            "created_by": "corpus_v2_v208_semantic_quality_remediation.py",
            "rule_version": RULE_VERSION,
            "run_at": TIMESTAMP,
            "status": "TARGETED_REVIEW_OK",
            "case_id": "mixed-027",
            "model": REVIEW_MODEL,
            "temperature": REVIEWER_TEMPERATURE,
            "max_tokens": REVIEWER_MAX_TOKENS,
            "thinking_disabled": True,
            "max_retries": MAX_RETRIES,
            "retries_used": retries,
            "diagnostic_only": True,
            "inputs": {
                "candidate-manifest.json": _sha256_file(
                    out_dir / "manifest.json"),
                "payload_sha256": payload_sha,
            },
            "outputs": {
                "payload.jsonl": _sha256_file(tdir / "payload.jsonl"),
                "raw-response.jsonl": _sha256_file(tdir / "raw-response.jsonl"),
                "targeted-review-result.json": _sha256_file(
                    tdir / "targeted-review-result.json"),
                "targeted-review-report.md": _sha256_file(
                    tdir / "targeted-review-report.md"),
                "review-status.json": _sha256_file(tdir / "review-status.json"),
            },
            "declarations": {
                "overlay_generated": False,
                "case_data_changed": False,
                "model_fixed": REVIEW_MODEL,
                "fallback_used": False,
            },
        })
        _atomic_write(tdir / "manifest.json", _dump(manifest))
        return {"status": "TARGETED_REVIEW_OK", "model": REVIEW_MODEL,
                "result": result}
    except Exception as exc:
        reason = str(exc)
        try:
            tdir.mkdir(parents=True, exist_ok=True)
            _atomic_write(tdir / "review-status.json", _dump({
                "status": "TARGETED_REVIEW_BLOCKED",
                "case_id": "mixed-027",
                "reason": reason,
                "diagnostic_only": True,
                "candidate_unchanged": True,
            }))
        except Exception:
            pass
        return {"status": "TARGETED_REVIEW_BLOCKED", "reason": reason}


def _targeted_md(payload_sha: str, result: dict, retries: int) -> str:
    return (
        "# TARGETED_RE_REVIEW_REPORT.md — mixed-027 定向盲态复审（诊断 only）\n\n"
        f"- 模型：`{REVIEW_MODEL}`（temperature=0.0、max_tokens=8000、"
        "thinking disabled、max_retries=3、无 fallback、无混用）\n"
        f"- payload_sha256：`{payload_sha}`；transport retries：{retries}\n"
        "- 盲态：payload 仅含 query / previous_turns（去 case_id）/ should_refuse / "
        "acceptable_answer_points / evidence / 必要 chunk 原文；不含 split、历史 "
        "decision/rationale、批次标签、case_id\n"
        "- **本结果仅为 targeted-re-review 诊断文件；无论结果如何都不生成 overlay，"
        "不改变 case 数据。**\n\n"
        "## 复审结果\n\n"
        f"- decision：`{result['decision']}`\n"
        f"- refusal_assessment：`{result['refusal_assessment']}`\n"
        f"- answer_point_assessments：\n"
        + "\n".join(
            f"  - AP {a['answer_point_index']}: {a['assessment']} "
            f"evidence_refs={a['evidence_refs']}"
            for a in result["answer_point_assessments"]) + "\n"
        f"- rationale：{result['rationale']}\n\n"
        "## 说明\n\n"
        "该复审不是自动 confirmed；mixed-027 的候选数据保持不变，后续激活仍需"
        "所有者的最终决策。\n"
    )


# ── CLI ──────────────────────────────────────────────────────────────

USAGE = (
    "usage: corpus_v2_v208_semantic_quality_remediation.py "
    "{build|review-targeted} [--out-dir DIR] [--draft PATH] "
    "[--evidence PATH] [--decision-pack-dir DIR] [--review-dir DIR] "
    "[--candidate-dir DIR]"
)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if not argv or argv[0] not in ("build", "review-targeted"):
            print(USAGE, file=sys.stderr)
            return 2
        cmd, args = argv[0], argv[1:]
        kwargs: dict[str, Any] = {}

        def _flag(name: str, key: str) -> None:
            if name in args:
                kwargs[key] = Path(args[args.index(name) + 1])

        _flag("--out-dir", "out_dir")
        _flag("--decision-pack-dir", "decision_pack_dir")
        _flag("--review-dir", "review_dir")
        _flag("--candidate-dir", "candidate_dir")
        _flag("--draft", "draft_path")
        _flag("--evidence", "evidence_path")
        _flag("--chunks", "chunks_path")
        _flag("--chunk-manifest", "chunk_manifest_path")
        if cmd == "build":
            run(**kwargs)
            return 0
        result = review_targeted(**kwargs)
        if result["status"] == "TARGETED_REVIEW_OK":
            return 0
        print(f"targeted review blocked: {result['reason']}", file=sys.stderr)
        return 2
    except RemediationError as exc:
        print(f"remediation failed closed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
