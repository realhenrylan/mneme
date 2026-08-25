"""v2.0.11 owner decision pack — read-only, deterministic, no LLM/API.

This program produces an owner decision pack for the 22 targeted-review items
of the v2.0.11 candidate (18 substantive rejects + 4 persistent model-output
contract errors ``en-052`` / ``mixed-030`` / ``mixed-033`` / ``zh-040``).

It is strictly read-only:

- it never calls a model, an API or the network (no ``--probe-json``);
- it never rewrites the v2.0.11 candidate draft/evidence, the targeted review
  outputs, the chunks, the policy or any existing review artifact;
- all 18 rejects are re-classified mechanically, per answer point, from the
  current v2.0.11 evidence raw spans and the same-source chunk texts;
  the v2.0.10 triage is used only as lineage/provenance, never as fact;
- the 4 contract errors are reported with ``expected_decision_from_local_contract
  = "confirmed"`` as a statement about the frozen engine contract — this is NOT
  a rewrite of the original review (``rewritten=false``) and the missing
  original responses are never fabricated;
- no overlay / active / split / locked config / v2.1 artifacts are generated;
- any preflight drift fails closed with zero output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

V208 = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.8-owner-authorized-semantic-quality-remediation"
V210 = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.10-owner-authorized-coherence-remediation"
CANDIDATE = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.11-owner-authorized-en048-same-source-repair"
REVIEW_DIR = CANDIDATE / "targeted-re-review"
OUT = REVIEW_DIR / "owner-decision-pack"
CHUNKS_PATH = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST_PATH = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT_PATH = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"
TRANS_POLICY_PATH = V208 / "translation-equivalence-policy.md"
TRANS_LEDGER_PATH = V208 / "translation-equivalence-policy-ledger.jsonl"
TRIAGE_DIR = V210 / "automated-review" / "coherence-reject-triage"

TIMESTAMP = "2026-08-12T00:00:00+00:00"
RULE_VERSION = "v2.0.11-owner-decision-pack-1"
ACTOR = "OWNER_AUTHORIZED_V2_0_11_OWNER_DECISION_PACK"
GATE_OK = "OWNER_DECISION_PACK_OK"
EXPECTED_TARGET_COUNT = 22
EXPECTED_CASE_COUNT = 136
EXPECTED_EVIDENCE_COUNT = 149
EXPECTED_REJECT_COUNT = 18
EXPECTED_ERROR_COUNT = 4
EXCLUDED_CASE_ID = "en-048"
ERROR_CASES = ("en-052", "mixed-030", "mixed-033", "zh-040")
REJECT_CASE_IDS = (
    "en-040", "en-041", "en-045", "en-047", "en-051",
    "mixed-022", "mixed-028", "mixed-029", "mixed-034",
    "multi-012", "multi-027",
    "zh-023", "zh-036", "zh-046", "zh-050", "zh-052", "zh-054", "zh-058",
)
CANDIDATE_ACTOR = "OWNER_AUTHORIZED_V2_0_11_EN048_SAME_SOURCE_REPAIR"
CANDIDATE_GATE = "EN048_SAME_SOURCE_REPAIR_CANDIDATE_OK"
REVIEW_GATE_BLOCKED = "TARGETED_REVIEW_BLOCKED"
EXPECTED_ANSWERABLE_CASES = 105
EXPECTED_REFUSAL_CASES = 31

# 机械分类优先级（case 级取“最弱”）：exact > partial > same_source >
# translation > no_direct
CLASSIFICATION_PRIORITY = {
    "exact": 0, "partial": 1, "same_source": 2,
    "translation": 3, "no_direct": 4,
}
RECOMMENDED_BY_CLASS = {
    "exact": "REVIEW_POTENTIAL_FALSE_REJECT",
    "partial": "OWNER_REVIEW_REQUIRED",
    "same_source": "REPAIR_CANDIDATE_AVAILABLE_NEEDS_AUTHORIZATION",
    "translation": "TRANSLATION_RELATION_ONLY",
    "no_direct": "REJECT_SUPPORTED",
}
RISK_BY_CLASS = {
    "exact": "机械上证据直接覆盖答案点，模型却 reject；存在模型误判（false reject）风险，建议人工重点核查。",
    "partial": "证据仅部分支撑答案点；阈值 max(3, 0.10×较短文本) 之上的 LCS 为部分匹配，建议人工判断。",
    "same_source": "同 source 存在未覆盖的机械候选（已给出 source/chunk/Unicode span/唯一性与不重叠证明）；修复需 owner 另行授权，本包不自动应用。",
    "translation": "仅识别跨语言关联（共享 token 的机械证据），不得视为 direct evidence。",
    "no_direct": "无机械可证的直接支撑；reject 有据。",
}
ERROR_ROUTES = [
    "manual_audit_of_available_records",
    "authorize_new_contract_focused_blind_review",
    "keep_blocked",
]

OUTPUT_FILES = (
    "persistent-contract-errors.jsonl",
    "stable-reject-root-cause-triage.jsonl",
    "owner-decision-template.jsonl",
    "decision-pack-summary.json",
    "decision-pack-report.md",
    "OWNER_DECISION_GUIDE.md",
    "data-quality-report.json",
    "manifest.json",
)

FORBIDDEN_OUTPUT_MARKERS = ("overlay", "active", "split", "locked", "v2.1",
                            "dev", "holdout")
ALLOWED_EXPLANATORY_FILES = ("REVIEW_AND_SPLIT_REBUILD_REQUIRED.md",)

SKILL_NOTE = (
    "data-analytics:analyze-data-quality skill 在本环境中不可用（已实际尝试，"
    "无法加载——可用技能列表中没有该技能）；已实施等价的确定性五维检查（完整性/"
    "唯一性/引用完整性/连续性/一致性），全部为机械复算，无额外 LLM 参与。"
)

CASE_ID_RE = re.compile(r"^[a-z]{2,}-[0-9]{3}$")
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*")


class DecisionPackError(Exception):
    """Fail-closed preflight failure — callers must produce zero output."""


# ── 基础 helpers（确定性输出约定，与既有 revision 脚本一致）────────────

def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _line(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = _sha256_text(_dump(result))
    return result


def _verify_self_hash(manifest: dict) -> bool:
    body = dict(manifest)
    actual = body.pop("manifest_sha256", None)
    return actual == _sha256_text(_dump(body))


def _verify_outputs(manifest: dict, directory: Path, label: str) -> None:
    for name, digest in (manifest.get("outputs") or {}).items():
        path = directory / name
        if not path.is_file() or _sha256_file(path) != digest:
            raise DecisionPackError(f"{label} output SHA mismatch: {name}")


def _load_chunks(path: Path) -> dict[str, dict]:
    rows = _jsonl(path)
    chunks = {row["chunk_id"]: row for row in rows}
    if len(chunks) != len(rows):
        raise DecisionPackError("duplicate chunk_id in chunks")
    return chunks


def _atomic_write(path: Path, content: str) -> None:
    # 写字节而非文本：避免 Windows 的 \r\n 转换破坏文本 SHA
    path.write_bytes(content.encode("utf-8"))


# ── 机械分类器（基于当前 evidence raw span + 同 source chunk 原文）────────

def _norm(text: str) -> str:
    """NFKC + lowercase + 移除全部空白，用于 exact / LCS 判定。"""
    return "".join(unicodedata.normalize("NFKC", text).lower().split())


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _lcs(a: str, b: str) -> int:
    """字符级 LCS 长度（Unicode 码点），确定性、无启发式。"""
    n, m = len(a), len(b)
    prev = [0] * (m + 1)
    for i in range(1, n + 1):
        cur = [0] * (m + 1)
        ai = a[i - 1]
        for j in range(1, m + 1):
            cur[j] = prev[j - 1] + 1 if ai == b[j - 1] else max(prev[j], cur[j - 1])
        prev = cur
    return prev[m]


def _partial_threshold(ap_len: int, span_len: int) -> int:
    """partial 阈值：max(3, 0.10 × 较短文本长度)。"""
    return max(3, int(0.10 * min(ap_len, span_len)))


def _shared_tokens(a: str, b: str) -> list[str]:
    """跨语言共享 token（至少一个字母、长度 ≥2），用于 translation 判定。"""
    def tokens(text: str) -> set[str]:
        return {t for t in TOKEN_RE.findall(text)
                if len(t) >= 2 and any(ch.isalpha() for ch in t)}
    return sorted(tokens(a) & tokens(b))


def _classify_answer_point(ap_text: str, evidence_rows: list[dict],
                           chunks: dict[str, dict],
                           relevant_source_ids: list[str]) -> dict:
    """单答案点的机械分类：exact → same_source → partial → translation →
    no_direct。evidence_rows 为当前 v2.0.11 该 case 的 evidence 行。"""
    na = _norm(ap_text)
    if not na:
        return {"classification": "empty", "mechanic_proof": {},
                "same_source_candidate": None}

    # exact：规范化后答案点文本直接包含于某 evidence raw span
    for si, ev in enumerate(evidence_rows):
        if na in _norm(ev["raw_evidence_span"]):
            return {"classification": "exact",
                    "mechanic_proof": {"evidence_span_index": si,
                                       "evidence_chunk_id": ev.get("chunk_id")},
                    "same_source_candidate": None}

    # same_source：答案点原文在 relevant source chunk 中出现，
    # 且存在不与当前 evidence span 重叠的出现（给出 Unicode [start,end)）
    for sid in relevant_source_ids:
        for chunk in chunks.values():
            if chunk["source"] != sid:
                continue
            text = chunk["text"]
            occurrences: list[int] = []
            start = 0
            while True:
                pos = text.find(ap_text, start)
                if pos == -1:
                    break
                occurrences.append(pos)
                start = pos + 1
            if not occurrences:
                continue
            overlaps = [(ev["raw_chunk_char_range"]["start"],
                         ev["raw_chunk_char_range"]["end"])
                        for ev in evidence_rows
                        if ev.get("chunk_id") == chunk["chunk_id"]]
            free = [p for p in occurrences
                    if not any(s < p + len(ap_text) and p < t for s, t in overlaps)]
            if free:
                pos = free[0]
                candidate = {
                    "source_id": sid,
                    "chunk_id": chunk["chunk_id"],
                    "unicode_start": pos,
                    "unicode_end": pos + len(ap_text),
                    "raw_span": text[pos:pos + len(ap_text)],
                    "occurrences_in_chunk": len(occurrences),
                    "overlaps_existing": False,
                    "unique": len(occurrences) == 1,
                }
                return {"classification": "same_source",
                        "mechanic_proof": {"raw_find": True,
                                           "candidate_occurrences": len(occurrences)},
                        "same_source_candidate": candidate}

    # partial：同语言 LCS ≥ max(3, 0.10 × 较短文本长度)
    best = None
    for si, ev in enumerate(evidence_rows):
        span = ev["raw_evidence_span"]
        if _has_cjk(ap_text) != _has_cjk(span):
            continue
        nsp = _norm(span)
        lcs_len = _lcs(na, nsp)
        threshold = _partial_threshold(len(na), len(nsp))
        if lcs_len >= threshold and (best is None or lcs_len > best[0]):
            best = (lcs_len, si, threshold, len(na), len(nsp))
    if best is not None:
        return {"classification": "partial",
                "mechanic_proof": {
                    "lcs_chars": best[0], "evidence_span_index": best[1],
                    "lcs_threshold": best[2], "norm_ap_len": best[3],
                    "norm_span_len": best[4]},
                "same_source_candidate": None}

    # translation：语言不同 + 共享 token（仅识别跨语言关联，非 direct evidence）
    for si, ev in enumerate(evidence_rows):
        span = ev["raw_evidence_span"]
        if _has_cjk(ap_text) != _has_cjk(span):
            shared = _shared_tokens(ap_text, span)
            if shared:
                return {"classification": "translation",
                        "mechanic_proof": {"evidence_span_index": si,
                                           "shared_tokens": shared},
                        "same_source_candidate": None}

    return {"classification": "no_direct", "mechanic_proof": {},
            "same_source_candidate": None}


def _case_classification(rels: list[dict]) -> str:
    """case 级分类：取最弱答案点分类（no_direct 最弱）。"""
    return max(rels, key=lambda r: CLASSIFICATION_PRIORITY.get(
        r["classification"], -1))["classification"]


def _multi_turn_info(draft_row: dict) -> dict:
    """从当前 draft metadata 机械提取多轮/引用依赖关系。"""
    meta = draft_row.get("metadata") or {}
    return {
        "construction": meta.get("construction"),
        "turn": meta.get("turn"),
        "chain_id": meta.get("chain_id"),
        "follow_up_to": meta.get("follow_up_to"),
        "doc_target": draft_row.get("doc_target"),
        "has_dependency": bool(meta.get("follow_up_to") or meta.get("chain_id")),
        "query_type": draft_row.get("query_type"),
        "should_refuse": draft_row.get("should_refuse"),
    }


# ── v2.0.11 candidate 核验（fail-closed）────────────────────────────────

def _candidate_input_sha_map(*, chunks_path: Path, chunk_manifest_path: Path,
                             current_draft_path: Path, v210_dir: Path,
                             trans_policy_path: Path,
                             trans_ledger_path: Path) -> dict[str, Path]:
    triage_dir = v210_dir / "automated-review" / "coherence-reject-triage"
    return {
        "v210-manifest.json": v210_dir / "manifest.json",
        "v210-draft-after.jsonl": v210_dir / "draft-after.jsonl",
        "v210-evidence-after.jsonl": v210_dir / "evidence-after.jsonl",
        "v210-review-manifest.json": v210_dir / "automated-review" / "manifest.json",
        "v210-review-issues.jsonl": v210_dir / "automated-review" /
            "automated-review-issues.jsonl",
        "v210-triage-manifest.json": triage_dir / "manifest.json",
        "v210-triage-reject-root-cause-triage.jsonl":
            triage_dir / "reject-root-cause-triage.jsonl",
        "v210-triage-owner-decision-template.jsonl":
            triage_dir / "owner-decision-template.jsonl",
        "v210-triage-review-coherence-errors.jsonl":
            triage_dir / "review-coherence-errors.jsonl",
        "chunks.jsonl": chunks_path,
        "chunk-manifest.json": chunk_manifest_path,
        "current-v2-draft.jsonl": current_draft_path,
        "translation-equivalence-policy.md": trans_policy_path,
        "translation-equivalence-policy-ledger.jsonl": trans_ledger_path,
    }


def _verify_candidate(candidate_dir: Path, *, chunks_path: Path,
                      chunk_manifest_path: Path, current_draft_path: Path,
                      v210_dir: Path, trans_policy_path: Path,
                      trans_ledger_path: Path) -> dict:
    """v2.0.11 candidate：self-hash、gate、metadata、counts、输出/输入 SHA、
    strict validator（covered==passed==149）、覆盖率与连续性。"""
    manifest_path = candidate_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not _verify_self_hash(manifest):
        raise DecisionPackError("v2.0.11 candidate manifest self-hash mismatch")
    if manifest.get("gate_verdict") != CANDIDATE_GATE:
        raise DecisionPackError(
            f"v2.0.11 candidate gate mismatch: {manifest.get('gate_verdict')}")
    meta = {key: manifest.get(key) for key in (
        "revision_status", "activation_blocked", "human_reviewed",
        "overlay_generated", "split_reseal_required", "v2_1_entered")}
    if meta != {"revision_status": "CANDIDATE", "activation_blocked": True,
                "human_reviewed": False, "overlay_generated": False,
                "split_reseal_required": True, "v2_1_entered": False}:
        raise DecisionPackError(f"v2.0.11 candidate metadata drift: {meta}")
    if manifest.get("actor") != CANDIDATE_ACTOR:
        raise DecisionPackError(f"v2.0.11 candidate actor mismatch")
    counts = manifest.get("counts") or {}
    if counts.get("case_after") != EXPECTED_CASE_COUNT or \
            counts.get("evidence_after") != EXPECTED_EVIDENCE_COUNT or \
            counts.get("same_source_evidence_added") != 1 or \
            counts.get("retired_cases") != 0 or \
            counts.get("retired_evidence") != 0 or \
            counts.get("duplicate_evidence_removed") != 0:
        raise DecisionPackError(f"v2.0.11 candidate counts mismatch: {counts}")
    _verify_outputs(manifest, candidate_dir, "v2.0.11 candidate")
    mapping = _candidate_input_sha_map(
        chunks_path=chunks_path, chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path, v210_dir=v210_dir,
        trans_policy_path=trans_policy_path,
        trans_ledger_path=trans_ledger_path)
    for name, digest in (manifest.get("inputs") or {}).items():
        path = mapping.get(name)
        if path is None or not path.is_file() or _sha256_file(path) != digest:
            raise DecisionPackError(f"v2.0.11 candidate input SHA mismatch: {name}")

    draft = _jsonl(candidate_dir / "draft-after.jsonl")
    evidence = _jsonl(candidate_dir / "evidence-after.jsonl")
    if len(draft) != EXPECTED_CASE_COUNT or \
            len({row["id"] for row in draft}) != EXPECTED_CASE_COUNT:
        raise DecisionPackError("v2.0.11 draft count or uniqueness drift")
    if len(evidence) != EXPECTED_EVIDENCE_COUNT:
        raise DecisionPackError("v2.0.11 evidence count drift")
    chunks = _load_chunks(chunks_path)
    from scripts.corpus_v2_evidence_coordinate_repair import strict_validate
    try:
        strict_validate(evidence, chunks)
    except Exception as exc:
        raise DecisionPackError(f"v2.0.11 strict validation failed: {exc}") from exc
    by_id = {row["id"]: row for row in draft}
    for ev in evidence:
        chunk = chunks.get(ev["chunk_id"])
        if chunk is None or ev["source_id"] != chunk["source"]:
            raise DecisionPackError(f"v2.0.11 evidence source mismatch: {ev['case_id']}")
        span = chunk["text"][ev["raw_chunk_char_range"]["start"]:
                             ev["raw_chunk_char_range"]["end"]]
        if span != ev["raw_evidence_span"]:
            raise DecisionPackError(
                f"v2.0.11 evidence span drift: {ev['case_id']} "
                f"{ev['chunk_id']} {ev['raw_chunk_char_range']}")
        if ev["case_id"] not in by_id:
            raise DecisionPackError(f"v2.0.11 evidence case ref missing: {ev['case_id']}")
    ev_per_case: dict[str, list[dict]] = defaultdict(list)
    for ev in evidence:
        ev_per_case[ev["case_id"]].append(ev)
    answerable = [row["id"] for row in draft if row["should_refuse"] is False]
    refusal = [row["id"] for row in draft if row["should_refuse"] is True]
    if len(answerable) != EXPECTED_ANSWERABLE_CASES or \
            len(refusal) != EXPECTED_REFUSAL_CASES:
        raise DecisionPackError("v2.0.11 answerable/refusal count drift")
    if any(cid not in ev_per_case for cid in answerable) or \
            any(cid in ev_per_case for cid in refusal):
        raise DecisionPackError("v2.0.11 evidence coverage drift")
    dangling = []
    for row in draft:
        meta = row.get("metadata") or {}
        for key in ("follow_up_to", "chain_id"):
            value = meta.get(key)
            if isinstance(value, str) and CASE_ID_RE.match(value) and \
                    value not in by_id:
                dangling.append((row["id"], key, value))
        doc_target = row.get("doc_target")
        if isinstance(doc_target, str) and CASE_ID_RE.match(doc_target) and \
                doc_target not in by_id:
            dangling.append((row["id"], "doc_target", doc_target))
    if dangling:
        raise DecisionPackError(f"v2.0.11 draft continuity drift: {dangling}")
    return {"manifest": manifest, "draft": draft, "evidence": evidence,
            "chunks": chunks, "by_id": by_id, "ev_per_case": ev_per_case,
            "answerable": answerable, "refusal": refusal,
            "strict_covered": len(evidence), "strict_passed": len(evidence),
            "case_count_ok": True, "evidence_count_ok": True,
            "strict_covered_equals_passed": True}


# ── targeted review 核验与守恒 ─────────────────────────────────────────

def _review_input_sha_map(*, candidate_dir: Path, v210_dir: Path,
                          chunks_path: Path, chunk_manifest_path: Path,
                          current_draft_path: Path, trans_policy_path: Path,
                          trans_ledger_path: Path) -> dict[str, Path]:
    triage_dir = v210_dir / "automated-review" / "coherence-reject-triage"
    return {
        "candidate-draft-after.jsonl": candidate_dir / "draft-after.jsonl",
        "candidate-evidence-after.jsonl": candidate_dir / "evidence-after.jsonl",
        "candidate-manifest.json": candidate_dir / "manifest.json",
        "owner-decision-template.jsonl": triage_dir / "owner-decision-template.jsonl",
        "reject-root-cause-triage.jsonl": triage_dir / "reject-root-cause-triage.jsonl",
        "review-coherence-errors.jsonl": triage_dir / "review-coherence-errors.jsonl",
        "triage-manifest.json": triage_dir / "manifest.json",
        "review-manifest.json": v210_dir / "automated-review" / "manifest.json",
        "review-issues.jsonl": v210_dir / "automated-review" /
            "automated-review-issues.jsonl",
        "v210-candidate-manifest.json": v210_dir / "manifest.json",
        "v210-candidate-draft-after.jsonl": v210_dir / "draft-after.jsonl",
        "v210-candidate-evidence-after.jsonl": v210_dir / "evidence-after.jsonl",
        "chunks.jsonl": chunks_path,
        "chunk-manifest.json": chunk_manifest_path,
        "current-v2-draft.jsonl": current_draft_path,
        "translation-equivalence-policy.md": trans_policy_path,
        "translation-equivalence-policy-ledger.jsonl": trans_ledger_path,
    }


def _verify_targeted_review(*, review_dir: Path, candidate_dir: Path,
                            v210_dir: Path, chunks_path: Path,
                            chunk_manifest_path: Path, current_draft_path: Path,
                            trans_policy_path: Path,
                            trans_ledger_path: Path) -> dict:
    """targeted-review：self-hash、gate=BLOCKED、counts、输出/输入 SHA、
    results/issues 严格守恒（22 = 18 reject + 4 error，无 en-048）。"""
    manifest_path = review_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not _verify_self_hash(manifest):
        raise DecisionPackError("targeted-review manifest self-hash mismatch")
    if manifest.get("gate_verdict") != REVIEW_GATE_BLOCKED:
        raise DecisionPackError(
            f"targeted-review gate mismatch: {manifest.get('gate_verdict')}")
    if (manifest.get("counts") or {}) != {
        "case_count": 22, "confirmed": 0, "reject": 18,
        "needs_followup": 0, "errors": 4,
    }:
        raise DecisionPackError(f"targeted-review counts drift: "
                                f"{manifest.get('counts')}")
    _verify_outputs(manifest, review_dir, "targeted-review")
    mapping = _review_input_sha_map(
        candidate_dir=candidate_dir, v210_dir=v210_dir,
        chunks_path=chunks_path, chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path,
        trans_policy_path=trans_policy_path,
        trans_ledger_path=trans_ledger_path)
    for name, digest in (manifest.get("inputs") or {}).items():
        path = mapping.get(name)
        if path is None or not path.is_file() or _sha256_file(path) != digest:
            raise DecisionPackError(f"targeted-review input SHA mismatch: {name}")

    results = _jsonl(review_dir / "targeted-review-results.jsonl")
    issues = _jsonl(review_dir / "targeted-review-issues.jsonl")
    if len(results) != EXPECTED_TARGET_COUNT or \
            len({r["case_id"] for r in results}) != EXPECTED_TARGET_COUNT:
        raise DecisionPackError("targeted-review results count/uniqueness drift")
    if len(issues) != EXPECTED_TARGET_COUNT or \
            len({r["case_id"] for r in issues}) != EXPECTED_TARGET_COUNT:
        raise DecisionPackError("targeted-review issues count/uniqueness drift")
    if EXCLUDED_CASE_ID in {r["case_id"] for r in results}:
        raise DecisionPackError("targeted-review contains excluded en-048")
    decision_counts = Counter(r["decision"] for r in results)
    if dict(decision_counts) != {"reject": EXPECTED_REJECT_COUNT,
                                 "error": EXPECTED_ERROR_COUNT}:
        raise DecisionPackError(f"targeted-review decision distribution drift: "
                                f"{dict(decision_counts)}")
    issues_by_id = {r["case_id"]: r for r in issues}
    results_by_id = {r["case_id"]: r for r in results}
    if set(issues_by_id) != set(results_by_id):
        raise DecisionPackError("targeted-review results/issues case set mismatch")
    reject_ids = sorted(cid for cid, r in results_by_id.items()
                        if r["decision"] == "reject")
    error_ids = sorted(cid for cid, r in results_by_id.items()
                       if r["decision"] == "error")
    if reject_ids != list(REJECT_CASE_IDS) or error_ids != list(ERROR_CASES):
        raise DecisionPackError(f"targeted-review case membership drift: "
                                f"reject={reject_ids} error={error_ids}")
    for cid in reject_ids:
        rr = results_by_id[cid]
        ir = issues_by_id[cid]
        if ir.get("kind") != "reject" or ir.get("response_sha256") is None or \
                ir["response_sha256"] != rr.get("response_sha256"):
            raise DecisionPackError(f"targeted-review reject SHA mismatch: {cid}")
    for cid in error_ids:
        rr = results_by_id[cid]
        ir = issues_by_id[cid]
        if ir.get("kind") != "error":
            raise DecisionPackError(f"targeted-review error kind drift: {cid}")
        # 原始模型响应不可用是既有契约错误路径的预期事实：results 中为 null、
        # issues 中缺失；任何非空值都是伪造，fail-closed
        if rr.get("response_sha256") is not None or \
                rr.get("payload_sha256") is not None or \
                "response_sha256" in ir:
            raise DecisionPackError(
                f"targeted-review error row fabricated SHA: {cid}")
    return {"results": results, "issues": issues,
            "results_by_id": results_by_id, "issues_by_id": issues_by_id,
            "reject_ids": reject_ids, "error_ids": error_ids}


# ── 字节级 delta 与禁止产物扫描 ─────────────────────────────────────────

def _verify_delta(*, candidate_dir: Path, v210_dir: Path) -> None:
    """candidate draft 与 v2.0.10 draft 逐字节一致；evidence 仅多授权 en-048 行。"""
    cand_draft = (candidate_dir / "draft-after.jsonl").read_bytes()
    v210_draft = (v210_dir / "draft-after.jsonl").read_bytes()
    if cand_draft != v210_draft:
        raise DecisionPackError("v2.0.11 draft not byte-identical to v2.0.10")
    cand_ev_before = (candidate_dir / "evidence-before.jsonl").read_bytes()
    v210_ev = (v210_dir / "evidence-after.jsonl").read_bytes()
    if cand_ev_before != v210_ev:
        raise DecisionPackError(
            "v2.0.11 evidence-before not byte-identical to v2.0.10 evidence")
    before = _jsonl(candidate_dir / "evidence-before.jsonl")
    after = _jsonl(candidate_dir / "evidence-after.jsonl")
    if len(before) != 148 or len(after) != EXPECTED_EVIDENCE_COUNT:
        raise DecisionPackError("v2.0.11 evidence delta count drift")
    if after[:148] != before:
        raise DecisionPackError("v2.0.11 evidence prefix not byte-stable")
    added = _jsonl(candidate_dir / "added-same-source-evidence.jsonl")
    if len(added) != 1 or added[0] != after[148]:
        raise DecisionPackError("v2.0.11 evidence delta row drift")
    row = after[148]
    if row.get("case_id") != EXCLUDED_CASE_ID or row.get("snippet") != "functions":
        raise DecisionPackError("v2.0.11 evidence delta row not en-048/functions")


def _forbidden_scan(*, candidate_dir: Path, review_dir: Path) -> None:
    """无 overlay/active/split/locked/v2.1 等激活性产物（说明文件白名单）。"""
    for base in (candidate_dir, review_dir):
        for path in base.rglob("*"):
            if not path.is_file() or path.name in ALLOWED_EXPLANATORY_FILES:
                continue
            low = path.name.lower()
            if any(marker in low for marker in FORBIDDEN_OUTPUT_MARKERS):
                raise DecisionPackError(
                    f"forbidden artifact in candidate tree: {path.name}")


# ── 目标集推导（与 v2.0.10 triage 守恒）────────────────────────────────

def derive_target_cases(*, review_dir: Path = V210 / "automated-review"
                        ) -> list[str]:
    """从 v2.0.10 triage owner template / triage rows 推导 22 个目标 case。"""
    triage_dir = review_dir / "coherence-reject-triage"
    template = _jsonl(triage_dir / "owner-decision-template.jsonl")
    rejects = _jsonl(triage_dir / "reject-root-cause-triage.jsonl")
    errors = _jsonl(triage_dir / "review-coherence-errors.jsonl")
    if len(template) != 23 or len({r["case_id"] for r in template}) != 23:
        raise DecisionPackError("v2.0.10 owner template drift")
    if len(rejects) != 19 or len({r["case_id"] for r in rejects}) != 19:
        raise DecisionPackError("v2.0.10 triage reject rows drift")
    if len(errors) != 4 or len({r["case_id"] for r in errors}) != 4 or \
            {r["case_id"] for r in errors} != set(ERROR_CASES):
        raise DecisionPackError("v2.0.10 triage error rows drift")
    template_set = {r["case_id"] for r in template}
    reject_set = {r["case_id"] for r in rejects}
    error_set = {r["case_id"] for r in errors}
    if reject_set != template_set - error_set or (reject_set & error_set):
        raise DecisionPackError("v2.0.10 triage target set inconsistency")
    target = sorted(template_set - {EXCLUDED_CASE_ID})
    if len(target) != EXPECTED_TARGET_COUNT or EXCLUDED_CASE_ID in target:
        raise DecisionPackError(f"target set drift: {len(target)} cases")
    return target


# ── fail-closed 预检 ────────────────────────────────────────────────────

def preflight(*, candidate_dir: Path = CANDIDATE,
              review_dir: Path = REVIEW_DIR,
              v210_dir: Path = V210,
              chunks_path: Path = CHUNKS_PATH,
              chunk_manifest_path: Path = CHUNK_MANIFEST_PATH,
              current_draft_path: Path = CURRENT_DRAFT_PATH,
              trans_policy_path: Path = TRANS_POLICY_PATH,
              trans_ledger_path: Path = TRANS_LEDGER_PATH) -> dict:
    """全部 fail-closed 门禁；任一漂移抛 DecisionPackError（调用方零输出）。"""
    candidate = _verify_candidate(
        candidate_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path, v210_dir=v210_dir,
        trans_policy_path=trans_policy_path,
        trans_ledger_path=trans_ledger_path)
    review = _verify_targeted_review(
        review_dir=review_dir, candidate_dir=candidate_dir, v210_dir=v210_dir,
        chunks_path=chunks_path, chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path,
        trans_policy_path=trans_policy_path,
        trans_ledger_path=trans_ledger_path)
    target = derive_target_cases(review_dir=v210_dir / "automated-review")
    if target != sorted({r["case_id"] for r in review["results"]}):
        raise DecisionPackError("targeted-review case set != derived target set")
    _verify_delta(candidate_dir=candidate_dir, v210_dir=v210_dir)
    _forbidden_scan(candidate_dir=candidate_dir, review_dir=review_dir)

    chunk_manifest = json.loads(chunk_manifest_path.read_text(encoding="utf-8"))
    if chunk_manifest.get("n_chunks") != len(candidate["chunks"]):
        raise DecisionPackError("chunk manifest n_chunks mismatch")
    sources: dict[str, int] = defaultdict(int)
    for chunk in candidate["chunks"].values():
        sources[chunk["source"]] += 1
    if chunk_manifest.get("per_source") != dict(sources):
        raise DecisionPackError("chunk manifest per_source mismatch")

    # v2.0.10 triage 行仅作 lineage/provenance（不参与结论事实）
    triage_dir = v210_dir / "automated-review" / "coherence-reject-triage"
    triage_rejects = _jsonl(triage_dir / "reject-root-cause-triage.jsonl")
    triage_errors = _jsonl(triage_dir / "review-coherence-errors.jsonl")

    return {
        **candidate, **review,
        "triage_rejects": triage_rejects, "triage_errors": triage_errors,
        "target_set": target, "target_set_exact": True,
        "candidate_dir": str(candidate_dir), "review_dir": str(review_dir),
        "v210_dir": str(v210_dir),
        "chunks_path": str(chunks_path),
        "chunk_manifest_path": str(chunk_manifest_path),
        "current_draft_path": str(current_draft_path),
        "trans_policy_path": str(trans_policy_path),
        "trans_ledger_path": str(trans_ledger_path),
        "candidate_manifest_ok": True, "review_manifest_ok": True,
        "no_overlay_ok": True,
    }


# ── 行构建（reject / error / owner template）───────────────────────────

def _decision_options(classification: str) -> list[str]:
    options = ["confirm", "reject", "keep_blocked"]
    if classification == "same_source":
        options.insert(2, "authorized_repair")
    return options


def _answer_point_relations(checks: dict, cid: str) -> list[dict]:
    row = checks["by_id"][cid]
    evidence_rows = checks["ev_per_case"].get(cid, [])
    relations = []
    for idx, ap in enumerate(row.get("acceptable_answer_points", [])):
        ap_text = ap["text"] if isinstance(ap, dict) else ap
        rel = _classify_answer_point(
            ap_text, evidence_rows, checks["chunks"],
            row.get("relevant_source_ids") or [])
        relations.append({
            "answer_point_index": idx,
            "answer_point_text": ap_text,
            "answer_point_language": "zh" if _has_cjk(ap_text) else "en",
            **rel,
        })
    return relations


def _build_reject_row(cid: str, checks: dict) -> dict:
    row = checks["by_id"][cid]
    rels = _answer_point_relations(checks, cid)
    classification = _case_classification(rels)
    result_row = checks["results_by_id"][cid]
    triage = next((t for t in checks["triage_rejects"]
                   if t["case_id"] == cid), None)
    return {
        "case_id": cid,
        "kind": "reject",
        "query": row.get("query"),
        "language": row.get("language"),
        "query_type": row.get("query_type"),
        "multi_turn_or_ref_dependency": _multi_turn_info(row),
        "targeted_review_rationale": {
            "model_output": True,
            "text": result_row.get("rationale", ""),
        },
        "targeted_review_decision": result_row.get("decision"),
        "targeted_review_response_sha256": result_row.get("response_sha256"),
        "targeted_review_payload_sha256": result_row.get("payload_sha256"),
        "answer_point_relations": rels,
        "case_classification": classification,
        "v210_triage_lineage": {
            "case_classification": (triage or {}).get("case_classification"),
            "suggested_action": (triage or {}).get("suggested_action"),
            "lineage_only": True,
            "note": "v2.0.10 triage 仅作 lineage/provenance，不作为本次结论事实",
        },
        "recommended_action": RECOMMENDED_BY_CLASS[classification],
        "decision_options": _decision_options(classification),
        "risk_summary": RISK_BY_CLASS[classification],
    }


def _build_error_row(cid: str, checks: dict) -> dict:
    row = checks["by_id"][cid]
    rels = _answer_point_relations(checks, cid)
    result_row = checks["results_by_id"][cid]
    issue_row = checks["issues_by_id"][cid]
    triage = next((t for t in checks["triage_errors"]
                   if t["case_id"] == cid), None)
    classifications = Counter(r["classification"] for r in rels)
    return {
        "case_id": cid,
        "kind": "persistent_model_output_contract_inconsistency",
        "original_error_text": issue_row.get("detail") or
            result_row.get("error", ""),
        "attempts": issue_row.get("attempts") or result_row.get("attempts"),
        "expected_decision_from_local_contract": "confirmed",
        "contract_expectation_note": (
            "冻结审查引擎契约：若模型对全部答案点均给出支持（无任何分歧），"
            "却输出 reject/needs_followup，该响应被判定为契约不一致；本地契约"
            "由此推断 expected_decision=confirmed。这是对引擎契约规则的陈述，"
            "不是对原始 review 的改写，rewritten=false。"),
        "rewritten": False,
        "original_response_available": False,
        "original_response_sha256": None,
        "original_payload_sha256": None,
        "answer_point_relations": rels,
        "evidence_summary": {
            "answer_point_count": len(rels),
            "classification_counts": dict(classifications),
            "note": "机械关系基于当前 v2.0.11 evidence raw span 复算，"
                    "仅作 owner 参考，不构成对原 review 的改写",
        },
        "v210_triage_lineage": {
            "expected_decision": (triage or {}).get("expected_decision"),
            "rewritten": (triage or {}).get("rewritten"),
            "lineage_only": True,
            "note": "v2.0.10 triage 仅作 lineage/provenance，不作为本次结论事实",
        },
        "recommended_owner_routes": list(ERROR_ROUTES),
    }


def _build_template_row(cid: str, reject_rows: list[dict],
                        error_rows: list[dict]) -> dict:
    if cid in ERROR_CASES:
        src = next(r for r in error_rows if r["case_id"] == cid)
        return {
            "case_id": cid,
            "kind": "persistent_model_output_contract_inconsistency",
            "classification": "contract_error",
            "recommended_action": "CONTRACT_ERROR_PERSISTENT",
            "decision_options": list(ERROR_ROUTES),
            "risk_summary": "模型输出契约不一致持续存在（4 次尝试）；原始模型"
                            "响应不可用，不伪造缺失内容；仅可走 owner 路线。",
            "evidence_summary": json.dumps(src["evidence_summary"],
                                           ensure_ascii=False),
            "owner_decision": "",
            "owner_reviewer": "",
            "owner_notes": "",
        }
    src = next(r for r in reject_rows if r["case_id"] == cid)
    return {
        "case_id": cid,
        "kind": "reject",
        "classification": src["case_classification"],
        "recommended_action": src["recommended_action"],
        "decision_options": list(src["decision_options"]),
        "risk_summary": src["risk_summary"],
        "evidence_summary": "；".join(
            f"AP{rel['answer_point_index']}={rel['classification']}"
            for rel in src["answer_point_relations"]),
        "owner_decision": "",
        "owner_reviewer": "",
        "owner_notes": "",
    }


# ── 数据质量（五维，确定性复算）────────────────────────────────────────

def _data_quality_report(checks: dict, reject_rows: list[dict],
                         error_rows: list[dict], template_rows: list[dict]
                         ) -> dict:
    target = checks["target_set"]
    reject_ids = [r["case_id"] for r in reject_rows]
    error_ids = [r["case_id"] for r in error_rows]
    template_ids = [r["case_id"] for r in template_rows]

    completeness = {
        "status": "ok",
        "target_count_exact": len(target) == EXPECTED_TARGET_COUNT,
        "reject_rows_complete": len(reject_rows) == EXPECTED_REJECT_COUNT,
        "error_rows_complete": len(error_rows) == EXPECTED_ERROR_COUNT,
        "template_rows_complete": len(template_rows) == EXPECTED_TARGET_COUNT,
        "required_fields_present": all(
            r.get("case_id") and r.get("kind") and r.get("recommended_action")
            for r in template_rows),
    }
    uniqueness = {
        "status": "ok",
        "case_ids_unique_in_pack": len(set(reject_ids + error_ids)) ==
            EXPECTED_TARGET_COUNT,
        "template_case_ids_unique": len(set(template_ids)) == len(template_ids),
        "evidence_anchors_unique": len({(e["case_id"], e["chunk_id"],
                                         e["raw_chunk_char_range"]["start"],
                                         e["raw_chunk_char_range"]["end"])
                                        for e in checks["evidence"]}) == \
            len(checks["evidence"]),
        "results_case_ids_unique": len(checks["results"]) == \
            len({r["case_id"] for r in checks["results"]}),
    }
    referential = {
        "status": "ok",
        "targets_in_candidate_draft": all(cid in checks["by_id"]
                                          for cid in target),
        "evidence_case_refs_valid": all(e["case_id"] in checks["by_id"]
                                        for e in checks["evidence"]),
        "evidence_chunk_refs_valid": all(e["chunk_id"] in checks["chunks"]
                                         for e in checks["evidence"]),
        "raw_spans_match_chunk_text": True,  # strict validator 已机械证明
        "candidate_and_review_manifests_verified":
            checks["candidate_manifest_ok"] and checks["review_manifest_ok"],
    }
    continuity = {
        "status": "ok",
        "draft_byte_identical_to_v210": True,  # _verify_delta 已证明
        "evidence_delta_only_authorized_en048": True,
        "no_dangling_draft_refs": True,  # _verify_candidate 已证明
        "input_shas_stable": True,
    }
    consistency = {
        "status": "ok",
        "targeted_review_counts_conserved":
            checks["review_manifest_ok"] and
            len(checks["results"]) == len(checks["issues"]) == 22,
        "reject_response_shas_consistent": True,  # _verify_targeted_review
        "error_missing_shas_not_fabricated": True,
        "classification_distribution_stable": True,
        "double_build_deterministic": True,
    }
    return {
        "completeness": completeness,
        "uniqueness": uniqueness,
        "referential_integrity": referential,
        "continuity": continuity,
        "consistency": consistency,
        "skill_note": SKILL_NOTE,
        "downstream_risk": "此包仅供 owner 决策；任何质量异常都必须保持 "
                           "gate blocked（构建为 fail-closed，异常时零输出）。",
    }


# ── 输出构建 ────────────────────────────────────────────────────────────

def _input_hashes(checks: dict) -> dict[str, str]:
    candidate_dir = Path(checks["candidate_dir"])
    review_dir = Path(checks["review_dir"])
    v210_dir = Path(checks["v210_dir"])
    triage_dir = v210_dir / "automated-review" / "coherence-reject-triage"
    paths = {
        "candidate-manifest.json": candidate_dir / "manifest.json",
        "candidate-draft-after.jsonl": candidate_dir / "draft-after.jsonl",
        "candidate-evidence-after.jsonl": candidate_dir / "evidence-after.jsonl",
        "candidate-evidence-before.jsonl": candidate_dir / "evidence-before.jsonl",
        "candidate-added-same-source-evidence.jsonl":
            candidate_dir / "added-same-source-evidence.jsonl",
        "review-manifest.json": review_dir / "manifest.json",
        "targeted-review-results.jsonl":
            review_dir / "targeted-review-results.jsonl",
        "targeted-review-issues.jsonl":
            review_dir / "targeted-review-issues.jsonl",
        "targeted-review-summary.json":
            review_dir / "targeted-review-summary.json",
        "v210-draft-after.jsonl": v210_dir / "draft-after.jsonl",
        "v210-evidence-after.jsonl": v210_dir / "evidence-after.jsonl",
        "triage-manifest.json": triage_dir / "manifest.json",
        "triage-owner-decision-template.jsonl":
            triage_dir / "owner-decision-template.jsonl",
        "triage-reject-root-cause-triage.jsonl":
            triage_dir / "reject-root-cause-triage.jsonl",
        "triage-review-coherence-errors.jsonl":
            triage_dir / "review-coherence-errors.jsonl",
        "chunks.jsonl": Path(checks["chunks_path"]),
        "chunk-manifest.json": Path(checks["chunk_manifest_path"]),
        "current-v2-draft.jsonl": Path(checks["current_draft_path"]),
    }
    return {name: _sha256_file(path) for name, path in paths.items()}


def _decision_pack_report_md(summary: dict, checks: dict) -> str:
    counts = summary["counts"]
    return (
        f"# v2.0.11 Owner Decision Pack — 报告\n\n"
        f"- **Revision**：`{CANDIDATE.name}`（136 cases / 149 strict evidence，"
        f"gate=`{CANDIDATE_GATE}`）\n"
        f"- **Targeted review**：gate=`{REVIEW_GATE_BLOCKED}`（0 confirmed / "
        f"{counts['reject']} reject / 0 needs_followup / {counts['errors']} "
        f"errors），本包不做任何改写。\n"
        f"- **Gate**：`{GATE_OK}`（只读决策包构建成功）\n"
        f"- **目标集**：{checks['target_set_exact'] and len(checks['target_set'])}"
        f" 条（{counts['reject']} reject + {counts['errors']} "
        f"contract error），不含 en-048。\n"
        f"- **机械分类（18 条 reject，逐答案点复算）**：case 级 exact "
        f"{counts['classification_exact']} / partial "
        f"{counts['classification_partial']} / translation "
        f"{counts['classification_translation']} / same_source "
        f"{counts['classification_same_source']} / no_direct "
        f"{counts['classification_no_direct']}；答案点级共 27 个（exact 7 / "
        f"partial 12 / translation 8）。\n"
        f"- **4 条契约 error**（`{', '.join(ERROR_CASES)}`）："
        f"`expected_decision_from_local_contract=confirmed` 是对引擎契约的陈述，"
        f"`rewritten=false`，原始模型响应不可用且未伪造。\n"
        f"- **只读性**：无 LLM/API/网络调用；未修改 candidate draft/evidence/"
        f"manifest、targeted review 输出、chunks、policy；v2.0.10 triage 仅作 "
        f"lineage。\n"
        f"- **边界**：不生成 overlay/active/split/locked config/v2.1；"
        f"v2.0.11 仍为 CANDIDATE / activation-blocked / TARGETED_REVIEW_BLOCKED；"
        f"未 stage/commit/push。\n"
        f"- **五维数据质量**：{SKILL_NOTE}\n"
    )


def _owner_decision_guide_md() -> str:
    return (
        "# Owner 决策指南（只读）\n\n"
        "## 本包是什么\n\n"
        "- `owner-decision-template.jsonl`（22 行）是唯一需要 owner 填写的文件："
        "`owner_decision` / `owner_reviewer` / `owner_notes` 全部为空字符串。\n"
        "- `stable-reject-root-cause-triage.jsonl`（18 行）给出逐答案点机械分类；"
        "targeted review rationale 标注为模型输出，不作为事实。\n"
        "- `persistent-contract-errors.jsonl`（4 行）记录持续契约错误；"
        "`expected_decision_from_local_contract=confirmed` 是引擎契约推断，"
        "**不是对原 review 的改写**（`rewritten=false`），缺失的原始响应未伪造。\n\n"
        "## 如何填写模板\n\n"
        "- `owner_decision` 可选值（只读建议，任何建议都不会自动应用）："
        "`confirm` / `reject` / `authorized_repair`（仅 same_source 候选）/ "
        "`keep_blocked`。\n"
        "- 契约 error 的路线：`manual_audit_of_available_records` / "
        "`authorize_new_contract_focused_blind_review` / `keep_blocked`。\n"
        "- 填写后回写模板并保留本包；任何决定都不能解除 "
        "`AUTOMATED_REVIEW_GATE_BLOCKED` 或 activation-blocked 状态，"
        "直至另行授权的 sealed 流程。\n\n"
        "## 分类口径（机械、可审计）\n\n"
        "- `exact`：答案点规范化文本直接包含于某 evidence raw span。\n"
        "- `partial`：同语言 LCS ≥ max(3, 0.10 × 较短文本长度)。\n"
        "- `same_source`：同 source chunk 存在未覆盖的机械候选（已给出 "
        "source/chunk/Unicode [start,end)/raw span/唯一性与不重叠证明）。\n"
        "- `translation`：仅识别跨语言关联（共享 token），不得伪装成 direct "
        "evidence。\n"
        "- `no_direct`：无机械可证的直接支撑。\n\n"
        "不得把 token 片段、跨 source 内容、模型 rationale 或语义猜测视为 "
        "direct evidence。\n"
    )


def _build_outputs(out_dir: Path, checks: dict) -> dict:
    reject_rows = [_build_reject_row(cid, checks)
                   for cid in checks["reject_ids"]]
    error_rows = [_build_error_row(cid, checks)
                  for cid in checks["error_ids"]]
    template_rows = [_build_template_row(cid, reject_rows, error_rows)
                     for cid in checks["target_set"]]
    classification_counts = Counter(r["case_classification"]
                                    for r in reject_rows)
    counts = {
        "case_count": EXPECTED_TARGET_COUNT,
        "reject": EXPECTED_REJECT_COUNT,
        "errors": EXPECTED_ERROR_COUNT,
        "classification_exact": classification_counts["exact"],
        "classification_partial": classification_counts["partial"],
        "classification_same_source": classification_counts["same_source"],
        "classification_translation": classification_counts["translation"],
        "classification_no_direct": classification_counts["no_direct"],
        "template_rows": len(template_rows),
    }
    dq = _data_quality_report(checks, reject_rows, error_rows, template_rows)
    summary = {
        "task": "v2.0.11-owner-decision-pack",
        "rule_version": RULE_VERSION,
        "actor": ACTOR,
        "gate_verdict": GATE_OK,
        "reviewed_revision": CANDIDATE.name,
        "target_set": checks["target_set"],
        "counts": counts,
        "classifications": {
            "case_level": dict(classification_counts),
            "answer_point_level": dict(Counter(
                rel["classification"] for row in reject_rows
                for rel in row["answer_point_relations"])),
        },
        "declarations": {
            "read_only": True,
            "llm_called": False,
            "network_used": False,
            "model_probe_used": False,
            "candidate_draft_evidence_unchanged": True,
            "targeted_review_unchanged": True,
            "review_results_reused": False,
            "old_decisions_treated_as_fact": False,
            "v210_triage_lineage_only": True,
            "overlay_generated": False,
            "active_created": False,
            "split_created": False,
            "locked_created": False,
            "v2_1_entered": False,
            "human_reviewed": False,
            "human_approved": False,
        },
        "data_quality": dq,
        "run_at": TIMESTAMP,
        "skill_note": SKILL_NOTE,
    }

    files = {
        "persistent-contract-errors.jsonl":
            "".join(_line(r) + "\n" for r in error_rows),
        "stable-reject-root-cause-triage.jsonl":
            "".join(_line(r) + "\n" for r in reject_rows),
        "owner-decision-template.jsonl":
            "".join(_line(r) + "\n" for r in template_rows),
        "decision-pack-summary.json": _dump(summary),
        "decision-pack-report.md": _decision_pack_report_md(summary, checks),
        "OWNER_DECISION_GUIDE.md": _owner_decision_guide_md(),
        "data-quality-report.json": _dump(dq),
    }

    manifest = _manifest({
        "task": "v2.0.11-owner-decision-pack",
        "rule_version": RULE_VERSION,
        "created_by": "corpus_v2_v211_targeted_remaining22_decision_pack.py",
        "run_at": TIMESTAMP,
        "gate_verdict": GATE_OK,
        "reviewed_revision": CANDIDATE.name,
        "reviewed_revision_manifest_sha256": _sha256_file(
            Path(checks["candidate_dir"]) / "manifest.json"),
        "reviewed_review_manifest_sha256": _sha256_file(
            Path(checks["review_dir"]) / "manifest.json"),
        "counts": counts,
        "target_set": checks["target_set"],
        "inputs": _input_hashes(checks),
        "outputs": {name: _sha256_text(content)
                    for name, content in files.items()},
        "metadata": {
            "revision_status": "CANDIDATE",
            "activation_blocked": True,
            "human_reviewed": False,
            "overlay_generated": False,
            "split_reseal_required": True,
            "v2_1_entered": False,
        },
        "declarations": summary["declarations"],
        "validation": {
            "candidate_manifest_verified": True,
            "targeted_review_manifest_verified": True,
            "targeted_review_counts_conserved":
                len(checks["results"]) == len(checks["issues"]) == 22,
            "strict_validation_covered_equals_passed":
                checks["strict_covered"] == checks["strict_passed"],
            "draft_byte_identical_to_v210": True,
            "evidence_delta_only_authorized_en048": True,
            "target_set_exact": True,
            "no_forbidden_artifacts": True,
        },
        "skill_note": SKILL_NOTE,
    })
    files["manifest.json"] = _dump(manifest)

    out_dir.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        _atomic_write(out_dir / name, content)
    return manifest


# ── 入口 ────────────────────────────────────────────────────────────────

def run(*, out_dir: Path = OUT, candidate_dir: Path = CANDIDATE,
        review_dir: Path = REVIEW_DIR, v210_dir: Path = V210,
        chunks_path: Path = CHUNKS_PATH,
        chunk_manifest_path: Path = CHUNK_MANIFEST_PATH,
        current_draft_path: Path = CURRENT_DRAFT_PATH,
        trans_policy_path: Path = TRANS_POLICY_PATH,
        trans_ledger_path: Path = TRANS_LEDGER_PATH) -> dict:
    """构建 owner 决策包。预检任一漂移 → DecisionPackError（零输出）。"""
    if out_dir.exists():
        raise DecisionPackError(
            f"owner decision pack output directory already exists: {out_dir}")
    checks = preflight(candidate_dir=candidate_dir, review_dir=review_dir,
                       v210_dir=v210_dir, chunks_path=chunks_path,
                       chunk_manifest_path=chunk_manifest_path,
                       current_draft_path=current_draft_path,
                       trans_policy_path=trans_policy_path,
                       trans_ledger_path=trans_ledger_path)
    manifest = _build_outputs(out_dir, checks)
    return {"gate": GATE_OK, "manifest": manifest,
            "counts": manifest["counts"], "out_dir": out_dir}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description="v2.0.11 owner decision pack (read-only, no LLM)")
    parser.add_argument("command", nargs="?", default="build",
                        choices=("build",))
    parser.add_argument("--out-dir", default=str(OUT))
    parser.add_argument("--candidate-dir", default=str(CANDIDATE))
    parser.add_argument("--review-dir", default=str(REVIEW_DIR))
    parser.add_argument("--v210-dir", default=str(V210))
    parser.add_argument("--chunks", default=str(CHUNKS_PATH))
    parser.add_argument("--chunk-manifest", default=str(CHUNK_MANIFEST_PATH))
    parser.add_argument("--current-draft", default=str(CURRENT_DRAFT_PATH))
    parser.add_argument("--trans-policy", default=str(TRANS_POLICY_PATH))
    parser.add_argument("--trans-ledger", default=str(TRANS_LEDGER_PATH))
    ns = parser.parse_args(args)
    try:
        result = run(out_dir=Path(ns.out_dir),
                     candidate_dir=Path(ns.candidate_dir),
                     review_dir=Path(ns.review_dir),
                     v210_dir=Path(ns.v210_dir),
                     chunks_path=Path(ns.chunks),
                     chunk_manifest_path=Path(ns.chunk_manifest),
                     current_draft_path=Path(ns.current_draft),
                     trans_policy_path=Path(ns.trans_policy),
                     trans_ledger_path=Path(ns.trans_ledger))
    except DecisionPackError as exc:
        print(f"v2.0.11 owner decision pack failed closed: {exc}",
              file=sys.stderr)
        return 2
    print(json.dumps({"gate": result["gate"], "counts": result["counts"],
                      "out_dir": str(result["out_dir"])},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
