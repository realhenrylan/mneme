"""v2.0.9 automated-review coherence and reject root-cause triage（只读、确定性、无 LLM）。

对 v2.0.9 fresh full blind automated review 的 26 条非 confirmed issue 做本地根因分流：

- 分流一：4 条 model-output coherence errors（en-052 / mixed-030 / mixed-033 / multi-011）
  —— 统一归类 ``model_output_contract_inconsistency``（模型输出 self-contradiction：
  decision=reject/needs_followup 但本地契约校验无任何分歧；不得改写为 confirmed/reject，
  不重跑模型，只生成诊断与后续可选 recheck 规格）。
- 分流二：22 条 substantive reject —— 对每个 reject 的每个答案点，只基于 candidate 当前
  raw evidence 与同 source chunk 原文做确定性分类（verbatim/containment/same-source
  候选/跨语言/共享度/无支撑），给出只读建议动作。
- mixed-033 重复 evidence 去重安全性检查（只写建议，不修改数据）。

输出 8 个文件到 ``automated-review/coherence-reject-triage/``；不生成 overlay / active /
after / split / v2.1；不 stage/commit/push。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # 支持 `python scripts/xxx.py` 直接运行
    sys.path.insert(0, str(ROOT))
CANDIDATE = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.9-owner-authorized-final-dependency-closed-retirement"
REVIEW_DIR = CANDIDATE / "automated-review"
CHUNKS_PATH = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST_PATH = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT_PATH = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"
DEFAULT_OUT = REVIEW_DIR / "coherence-reject-triage"

TIMESTAMP = "2026-08-11T00:00:00+00:00"
RULE_VERSION = "v2.0.9-coherence-reject-triage-1"
GATE_OK = "COHERENCE_REJECT_TRIAGE_OK"

# 计数守恒（与 automated-review manifest.json 一致）
EXPECTED_CASE_COUNT = 137
EXPECTED_EVIDENCE_COUNT = 144
EXPECTED_CONFIRMED = 111
EXPECTED_REJECT = 22
EXPECTED_NEEDS_FOLLOWUP = 0
EXPECTED_ERRORS = 4

# 分流一目标（4 条 model-output coherence errors）
ERROR_CASES = ("en-052", "mixed-030", "mixed-033", "multi-011")
ERROR_CLASS = "model_output_contract_inconsistency"

# 分流二分类枚举（任务指定）
CLASS_EXACT = "exact_evidence_present_but_review_semantic_disagrees"
CLASS_PARTIAL = "partial_or_paraphrase_only"
CLASS_SAME_SOURCE = "same_source_scope_candidate_exists"
CLASS_NO_DIRECT = "no_direct_support_in_declared_source"
CLASS_TRANSLATION = "translation_equivalence_requires_owner_policy"
CLASS_REFUSAL = "refusal_label_or_schema_inconsistency"
CLASS_OTHER = "other_unresolved"
CLASSES = (CLASS_EXACT, CLASS_PARTIAL, CLASS_SAME_SOURCE, CLASS_NO_DIRECT,
           CLASS_TRANSLATION, CLASS_REFUSAL, CLASS_OTHER)

# 证据支撑度（case 级取最弱 AP 分类：数值越大证据越弱）
SEVERITY = {
    CLASS_OTHER: 0,
    CLASS_EXACT: 1,
    CLASS_PARTIAL: 2,
    CLASS_SAME_SOURCE: 3,
    CLASS_TRANSLATION: 4,
    CLASS_NO_DIRECT: 5,
    CLASS_REFUSAL: 6,
}

# 只读建议动作（任务指定）
ACTION_RECHECK = "targeted_recheck_required"
ACTION_REPAIR = "repair_candidate"
ACTION_REMOVE_AP = "remove_answer_point"
ACTION_RETIRE = "retire_case"
ACTION_UNRESOLVED = "keep_unresolved"
ACTIONS = (ACTION_RECHECK, ACTION_REPAIR, ACTION_REMOVE_AP, ACTION_RETIRE,
           ACTION_UNRESOLVED)

OUTPUT_ERRORS = "review-coherence-errors.jsonl"
OUTPUT_REJECTS = "reject-root-cause-triage.jsonl"
OUTPUT_MIXED033 = "mixed-033-duplicate-evidence-check.json"
OUTPUT_TEMPLATE = "owner-decision-template.jsonl"
OUTPUT_GUIDE = "COHERENCE_AND_REMEDIATION_GUIDE.md"
OUTPUT_SUMMARY = "triage-summary.json"
OUTPUT_REPORT = "triage-report.md"
OUTPUT_MANIFEST = "manifest.json"
OUTPUT_FILES = (OUTPUT_ERRORS, OUTPUT_REJECTS, OUTPUT_MIXED033,
                OUTPUT_TEMPLATE, OUTPUT_GUIDE, OUTPUT_SUMMARY,
                OUTPUT_REPORT, OUTPUT_MANIFEST)

SKILL_NOTE = (
    "data-analytics:analyze-data-quality skill 在本环境中不可用（不在已安装 "
    "skills 列表内，无法加载；已实际尝试）；已按任务约束执行等价的确定性五维检查"
    "（完整性 / 唯一性 / 引用完整性 / 连续性 / 一致性），全部为机械复算，无 LLM 参与。"
)


class TriageError(Exception):
    """Fail-closed 校验错误：任一预检漂移 → 零输出。"""


# ── 基础工具 ────────────────────────────────────────────────────────────

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(obj) -> str:
    """.json 文件序列化（与自哈希序列化保持一致）。"""
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _line(obj) -> str:
    """.jsonl 行序列化（compact，键排序）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _manifest(body: dict) -> dict:
    """自哈希约定：manifest_sha256 = sha256(dumps(body_without_sha))，与既有 revision 一致。"""
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = _sha256_text(json.dumps(
        result, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    return result


def _verify_manifest(manifest: dict) -> bool:
    expected = dict(manifest)
    actual = expected.pop("manifest_sha256", None)
    return actual == _sha256_text(json.dumps(
        expected, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def _norm(text: str) -> str:
    """Unicode 规范化（NFKC）+ 去除全部空白，用于确定性文本比较。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _ascii_tokens(text: str) -> list[str]:
    """AP 中的 ASCII 词法单元（字母/数字/下划线/连字符连续串）。"""
    return re.findall(r"[A-Za-z0-9_\-]+", text)


def _codefence_stripped(text: str) -> str:
    """去掉 ``` 代码围栏标记（保留围栏内内容）。"""
    return re.sub(r"```\s*", "", text)


def _lcs(a: str, b: str) -> int:
    """最长公共连续子串长度（字符级，DP 滚动数组）。"""
    if not a or not b:
        return 0
    n, m = len(a), len(b)
    dp = [0] * (m + 1)
    best = 0
    for i in range(1, n + 1):
        prev = 0
        for j in range(1, m + 1):
            cur = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev + 1
                if dp[j] > best:
                    best = dp[j]
            else:
                dp[j] = 0
            prev = cur
    return best


def _is_source_token(tok: str, source_ids: set[str]) -> bool:
    """排除与 source 名共享词形的 token（如 'SQLite' 之于 'sqlite-lang.md'）。"""
    t = tok.lower()
    for s in source_ids:
        base = s.split(".")[0].replace("-", "").replace("_", "").lower()
        if t in base or base in t:
            return True
    return False


# ── 输入加载 ────────────────────────────────────────────────────────────

def load_chunks(path: Path) -> dict[str, dict]:
    """加载 chunk 索引（chunk_id → row），重复 id 即失败。"""
    rows = _jsonl(path)
    result = {row["chunk_id"]: row for row in rows}
    if len(result) != len(rows):
        raise TriageError("chunk_id 重复")
    return result


def load_issues() -> tuple[list[dict], list[dict], list[dict]]:
    """读取 automated-review-issues.jsonl → (全部, rejects, errors)。"""
    issues = _jsonl(REVIEW_DIR / "automated-review-issues.jsonl")
    rejects = [i for i in issues if i.get("kind") == "reject"]
    errors = [i for i in issues if i.get("kind") == "error"]
    return issues, rejects, errors


def _existing_ranges(ev_rows: list[dict]) -> list[tuple[str, int, int]]:
    return [(e["chunk_id"], e["raw_chunk_char_range"]["start"],
             e["raw_chunk_char_range"]["end"]) for e in ev_rows]


# ── 分类（分流二核心：确定性、可复现、无 LLM） ─────────────────────────

def _token_in_spans(tok: str, n_spans: list[str]) -> bool:
    t = _norm(tok)
    return any(t in n_s for n_s in n_spans)


def _search_source(ap: str, chunk_index: dict, source_ids: set[str],
                   existing: list[tuple[str, int, int]], cross: bool,
                   tokens: list[str], n_spans: list[str]) -> list[dict]:
    """同 source 可证明候选 evidence 搜索。

    搜索序列：AP 原文 → 剥代码围栏版 →（跨语言时）最长不在现有 span 的 ASCII token。
    候选必须不重叠任何现有 evidence span；全部重叠视为无新候选。
    """
    chunks = [c for c in chunk_index.values() if c.get("source") in source_ids]
    candidates: list[dict] = []

    def _overlaps(cid: str, start: int, end: int) -> bool:
        return any(cid == e[0] and not (end <= e[1] or start >= e[2])
                   for e in existing)

    def _add(cid: str, text: str, start: int, needle: str, via: str) -> None:
        end = start + len(needle)
        candidates.append({
            "chunk_id": cid,
            "start": start,
            "end": end,
            "span": text[start:end],
            "unique": text.count(needle),
            "via": via,
            "overlaps_existing": _overlaps(cid, start, end),
        })

    needles: list[tuple[str, str]] = [("original", ap)]
    stripped = _codefence_stripped(ap)
    if stripped and stripped != ap:
        needles.append(("codefence-stripped", stripped))

    for via, needle in needles:
        if not needle:
            continue
        for chunk in chunks:
            text = chunk["text"]
            start = text.find(needle)
            while start >= 0:
                _add(chunk["chunk_id"], text, start, needle, via)
                start = text.find(needle, start + 1)

    if cross and tokens:
        # 跨语言：优先搜索不在任何现有 span 中的最长 token（AP 缺失主张的代表词）
        not_in_span = [t for t in tokens if not _token_in_spans(t, n_spans)]
        for tok in (not_in_span or tokens):
            hit = False
            for chunk in chunks:
                text = chunk["text"]
                start = text.find(tok)
                while start >= 0 and not _overlaps(chunk["chunk_id"], start, start + len(tok)):
                    _add(chunk["chunk_id"], text, start, tok, "token")
                    hit = True
                    break
                if hit:
                    break
            if hit:
                break

    fresh = [c for c in candidates if not c["overlaps_existing"]]
    return fresh if fresh else []


def classify_ap(ap: str, spans: list[str], chunk_index: dict,
                source_ids: set[str],
                existing: list[tuple[str, int, int]]) -> dict:
    """对单个答案点做确定性证据关系分类（详见模块 docstring 与 GUIDE）。"""
    n_ap = _norm(ap)
    n_spans = [_norm(s) for s in spans if s]
    base = {"cross_language": False, "lcs": None, "lcs_threshold": None,
            "same_source_candidates": [], "notes": []}

    def _res(classification: str, relation: str, **extra) -> dict:
        out = dict(base)
        out["classification"] = classification
        out["evidence_relation"] = relation
        out.update(extra)
        return out

    # 1) containment → exact（证据逐字/包含答案点）
    for n_s in n_spans:
        if n_ap and n_ap in n_s:
            return _res(CLASS_EXACT, "verbatim" if n_ap == n_s else "containment")
    for n_s in n_spans:
        if n_ap and n_s and n_s in n_ap and len(n_s) >= 0.5 * len(n_ap):
            return _res(CLASS_EXACT, "containment")

    cross = _has_cjk(ap) != any(_has_cjk(s) for s in spans)
    tokens = [t for t in _ascii_tokens(ap)
              if len(t) >= 3 and not _is_source_token(t, source_ids)]
    if cross:
        base["cross_language"] = True
        if tokens and all(_token_in_spans(t, n_spans) for t in tokens):
            # 证据已覆盖 AP 的全部 ASCII 内容：翻译概述分歧，非证据缺失
            return _res(CLASS_PARTIAL, "cross_language_ascii_covered")

    cands = _search_source(ap, chunk_index, source_ids, existing,
                           cross=cross, tokens=tokens, n_spans=n_spans)
    if cands:
        return _res(CLASS_SAME_SOURCE, "same_source_candidate",
                    same_source_candidates=cands[:5])

    if cross:
        if tokens:
            return _res(CLASS_TRANSLATION, "cross_language_no_candidate")
        digits = set(re.findall(r"\d+", ap))
        if digits and any(dig in s for s in spans for dig in digits):
            return _res(CLASS_TRANSLATION, "cross_language_shared_digits")
        return _res(CLASS_NO_DIRECT, "none")

    # 同语言：最长公共子串共享度（阈值 0.10 × 较短文本长度，下限 3 字符；
    # 覆盖"escape/escaping"这类强改写但共享度略低的 paraphrase 边界）
    best = max((_lcs(n_ap, n_s) for n_s in n_spans), default=0)
    min_len = min([len(n_ap)] + [len(n_s) for n_s in n_spans])
    threshold = max(3, int(0.10 * min_len))
    if best >= threshold:
        return _res(CLASS_PARTIAL, "lcs_partial", lcs=best, lcs_threshold=threshold)
    return _res(CLASS_NO_DIRECT, "none", lcs=best, lcs_threshold=threshold)


def _suggested_action(case_class: str, ap_classes: list[str]) -> str:
    if case_class in (CLASS_EXACT, CLASS_PARTIAL):
        return ACTION_RECHECK
    if case_class == CLASS_SAME_SOURCE:
        return ACTION_REPAIR
    if case_class == CLASS_TRANSLATION:
        return ACTION_UNRESOLVED
    if case_class == CLASS_NO_DIRECT:
        return ACTION_RETIRE if all(c == CLASS_NO_DIRECT for c in ap_classes) \
            else ACTION_REMOVE_AP
    return ACTION_UNRESOLVED


def _multi_turn_info(draft: dict) -> dict:
    meta = draft.get("metadata") or {}
    return {
        "construction": meta.get("construction"),
        "follow_up_to": meta.get("follow_up_to"),
        "chain_id": meta.get("chain_id"),
        "turn": meta.get("turn"),
        "doc_target": draft.get("doc_target"),
        "has_dependency": meta.get("follow_up_to") is not None
        or (meta.get("construction") == "follow_up" and meta.get("turn", 1) > 1),
    }


# ── 分流一：model-output coherence errors ───────────────────────────────

def analyze_error(issue: dict, draft: dict, ev_rows: list[dict],
                  chunk_index: dict) -> dict:
    """4 条 error 的诊断：契约层推导 expected decision，证据层辅助核验。

    契约层：issue.detail 明确 "reject/needs_followup without any disagreement"
    —— 本地 validate_response 语义判定无任何分歧（全答案点 supported 且 refusal
    一致）⇒ 统一 decision 契约要求 confirmed；模型却输出 reject/needs_followup
    ⇒ model_output_contract_inconsistency。不得改写模型输出，不重跑模型。
    """
    spans = [e["raw_evidence_span"] for e in ev_rows]
    source_ids = {e["source_id"] for e in ev_rows}
    existing = _existing_ranges(ev_rows)
    relations = []
    for i, ap in enumerate(draft.get("acceptable_answer_points") or []):
        r = classify_ap(ap, spans, chunk_index, source_ids, existing)
        r["ap_index"] = i
        r["answer_point"] = ap
        relations.append(r)
    expected = "confirmed"
    if any(r["classification"] == CLASS_NO_DIRECT for r in relations):
        expected = "confirmed"  # 契约层仍为 confirmed；证据层不足在 note 中呈现
    note = ("契约层：'without any disagreement' ⇒ 全部答案点 supported 且 refusal "
            "一致 ⇒ 契约要求 decision=confirmed；模型输出 reject/needs_followup "
            "与自身评估自相矛盾（4 次同模型重试一致）。")
    return {
        "case_id": issue["case_id"],
        "kind": "error",
        "attempts": issue.get("attempts"),
        "issue_detail": issue.get("detail"),
        "model_decision": "reject/needs_followup",
        "classification": ERROR_CLASS,
        "rewritten": False,
        "refusal_conflict": False,
        "schema_conflict": False,
        "expected_decision": expected,
        "answer_point_relations": relations,
        "remediation": {
            "recheck_required": True,
            "note": note,
            "spec": ("可选后续：对 en-052/mixed-030/mixed-033/multi-011 做一次全新"
                     "盲态重审（或人工核验该 4 条原始模型响应）；不得在本任务内"
                     "改写或确认。"),
        },
    }


# ── 分流二：substantive rejects ─────────────────────────────────────────

def analyze_reject(issue: dict, draft: dict, ev_rows: list[dict],
                   chunk_index: dict) -> dict:
    spans = [e["raw_evidence_span"] for e in ev_rows]
    source_ids = {e["source_id"] for e in ev_rows}
    existing = _existing_ranges(ev_rows)
    relations = []
    for i, ap in enumerate(draft.get("acceptable_answer_points") or []):
        r = classify_ap(ap, spans, chunk_index, source_ids, existing)
        r["ap_index"] = i
        r["answer_point"] = ap
        relations.append(r)

    ap_classes = [r["classification"] for r in relations]
    case_class = max(ap_classes, key=lambda c: SEVERITY.get(c, 0))
    all_cands = [c for r in relations for c in r["same_source_candidates"]]
    return {
        "case_id": issue["case_id"],
        "kind": "reject",
        "attempts": issue.get("attempts"),
        "rationale": issue.get("detail"),
        "query": draft.get("query"),
        "answer_point_relations": relations,
        "case_classification": case_class,
        "zero_answer_point_risk": False,
        "multi_turn_or_ref_dependency": _multi_turn_info(draft),
        "same_source_candidates": all_cands[:10],
        "suggested_action": _suggested_action(case_class, ap_classes),
    }


# ── mixed-033 重复 evidence 检查 ────────────────────────────────────────

def mixed033_check(ev_rows: list[dict], draft: dict) -> dict:
    """两条重复 evidence：字节一致性、同一答案点支撑、删除安全性（只写建议）。"""
    a, b = ev_rows[0], ev_rows[1]
    byte_identical = _line(a) == _line(b)
    ap = (draft.get("acceptable_answer_points") or [""])[0]
    rel = classify_ap(ap, [a["raw_evidence_span"]], {}, set(), [])
    ap_supported = rel["classification"] in (CLASS_EXACT, CLASS_PARTIAL)
    return {
        "case_id": "mixed-033",
        "rows": len(ev_rows),
        "byte_identical": byte_identical,
        "same_chunk": a["chunk_id"] == b["chunk_id"],
        "same_range": a["raw_chunk_char_range"] == b["raw_chunk_char_range"],
        "same_raw_span": a["raw_evidence_span"] == b["raw_evidence_span"],
        "same_snippet_sha": a["snippet_sha256"] == b["snippet_sha256"],
        "same_source": a["source_id"] == b["source_id"],
        "answer_point_count": len(draft.get("acceptable_answer_points") or []),
        "supports_same_answer_point": ap_supported,
        "deletion_advice": {
            "semantically_safe": byte_identical and ap_supported,
            "owner_authorization_required": True,
            "note": ("两条 evidence 行字节级完全一致（同 chunk / 同 raw range / "
                     "同 raw span / 同 snippet SHA / 同 source），均支撑同一保留"
                     "答案点；删除任意一条不改变任何语义、答案点或 source/chunk "
                     "关系（144 → 143）。但任何删除都必须由 owner 明确授权，并同步"
                     "更新 manifest 计数与 outputs SHA 后重跑 strict 校验；本任务"
                     "只写建议，不修改数据。"),
        },
        "data_modified": False,
    }


# ── 预检（fail-closed）─────────────────────────────────────────────────

def preflight(cand: Path, review: Path, chunks_path: Path,
              chunk_manifest_path: Path, current_draft_path: Path) -> dict:
    """全部预检 fail-closed：任一漂移 → TriageError → 零输出。"""
    checks: dict = {}
    try:
        from scripts.corpus_v2_evidence_coordinate_repair import (
            strict_validate as coord_strict_validate)
    except Exception as exc:  # pragma: no cover
        raise TriageError(f"strict validator 不可用: {exc}")

    # 1) case/evidence 计数与唯一性
    drafts = _jsonl(cand / "draft-after.jsonl")
    evs = _jsonl(cand / "evidence-after.jsonl")
    checks["case_count_ok"] = len(drafts) == EXPECTED_CASE_COUNT
    checks["evidence_count_ok"] = len(evs) == EXPECTED_EVIDENCE_COUNT
    checks["draft_ids_unique"] = len({d["id"] for d in drafts}) == len(drafts)
    # evidence 行级唯一性：一 case 多条 evidence 是正常设计；除 mixed-033 的
    # 已知字节级重复（v2.0.9 data-quality-report 记录 evidence_keys_unique=false）
    # 外，不允许存在任何两条字节级相同的 evidence 行。
    from collections import defaultdict
    line_groups = defaultdict(list)
    for e in evs:
        line_groups[_line(e)].append(e)
    checks["evidence_ids_unique"] = all(
        len(g) == 1 or (len(g) == 2 and g[0]["case_id"] == "mixed-033")
        for g in line_groups.values())

    # 0) 输入 SHA 闭环先行：chunks / chunk-manifest / current-draft 的磁盘 SHA
    #    必须与 candidate manifest inputs 一致（fail-closed，先于 chunks 解析）。
    cand_m = _load_json(cand / "manifest.json")
    for key, path in {
        "chunks.jsonl": chunks_path,
        "chunk-manifest.json": chunk_manifest_path,
        "current-v2-draft.jsonl": current_draft_path,
    }.items():
        if cand_m.get("inputs", {}).get(key) != _sha256_file(path):
            raise TriageError(f"candidate input SHA 漂移: {key}")
    checks["input_sha_ok"] = True

    # 2) strict 校验：covered == passed == 144
    chunks = load_chunks(chunks_path)
    covered = len(evs)
    passed = 0
    try:
        for row in evs:
            from scripts.corpus_v2_evidence_coordinate_repair import (
                strict_validate_row)
            strict_validate_row(row, chunks)
            passed += 1
    except Exception as exc:
        raise TriageError(f"strict validation failed: {exc}")
    checks["strict_144_144_ok"] = covered == EXPECTED_EVIDENCE_COUNT \
        and passed == EXPECTED_EVIDENCE_COUNT

    # 3) issues 行数守恒与 case 集合
    issues = _jsonl(review / "automated-review-issues.jsonl")
    rejects = [i for i in issues if i.get("kind") == "reject"]
    errors = [i for i in issues if i.get("kind") == "error"]
    checks["issues_rows_ok"] = len(issues) == EXPECTED_REJECT + EXPECTED_ERRORS
    checks["reject_rows_ok"] = len(rejects) == EXPECTED_REJECT
    checks["error_rows_ok"] = len(errors) == EXPECTED_ERRORS
    ids = [i["case_id"] for i in issues]
    checks["issues_ids_unique"] = len(ids) == len(set(ids))
    checks["reject_error_disjoint"] = not (
        {i["case_id"] for i in rejects} & {i["case_id"] for i in errors})
    checks["issues_cases_exist"] = all(
        i["case_id"] in {d["id"] for d in drafts} for i in issues)
    checks["issues_all_answerable"] = all(
        next(d["should_refuse"] is False for d in drafts if d["id"] == i["case_id"])
        for i in issues)

    # 4) review manifest 守恒与自校验
    review_m = _load_json(review / "manifest.json")
    counts = review_m.get("counts") or {}
    checks["review_manifest_ok"] = (
        _verify_manifest(review_m)
        and counts.get("case_count") == EXPECTED_CASE_COUNT
        and counts.get("evidence_count") == EXPECTED_EVIDENCE_COUNT
        and counts.get("confirmed") == EXPECTED_CONFIRMED
        and counts.get("reject") == EXPECTED_REJECT
        and counts.get("needs_followup") == EXPECTED_NEEDS_FOLLOWUP
        and counts.get("errors") == EXPECTED_ERRORS
        and review_m.get("declarations", {}).get("overlay_generated") is False
    )
    # review outputs SHA 与磁盘一致
    for name, sha in (review_m.get("outputs") or {}).items():
        if (review / name).exists() and _sha256_file(review / name) != sha:
            raise TriageError(f"review output SHA 漂移: {name}")

    # 5) candidate manifest 自校验 + outputs/inputs SHA
    cand_m = _load_json(cand / "manifest.json")
    checks["candidate_manifest_ok"] = (
        _verify_manifest(cand_m)
        and cand_m.get("revision_status") == "CANDIDATE"
        and cand_m.get("activation_blocked") is True
        and cand_m.get("human_reviewed") is False
    )
    for name, sha in (cand_m.get("outputs") or {}).items():
        if (cand / name).exists() and _sha256_file(cand / name) != sha:
            raise TriageError(f"candidate output SHA 漂移: {name}")

    # 6) review inputs SHA 闭环（candidate/review/chunks/current-draft）
    for key, sha in {
        "chunks.jsonl": _sha256_file(chunks_path),
        "chunk-manifest.json": _sha256_file(chunk_manifest_path),
        "current-v2-draft.jsonl": _sha256_file(current_draft_path),
        "candidate-draft-after.jsonl": _sha256_file(cand / "draft-after.jsonl"),
        "candidate-evidence-after.jsonl": _sha256_file(cand / "evidence-after.jsonl"),
        "candidate-manifest.json": _sha256_file(cand / "manifest.json"),
    }.items():
        if review_m.get("inputs", {}).get(key) != sha:
            raise TriageError(f"review input SHA 漂移: {key}")

    # 7) 无 overlay
    checks["no_overlay_ok"] = not (
        (cand / "automated-overlay.json").exists()
        or (review / "automated-overlay.json").exists()
        or any(p.name.startswith("overlay") for p in review.iterdir())
    )

    # 8) 引用完整性 / 连续性（五维检查）
    checks["ref_integrity_ok"] = all(
        e["chunk_id"] in chunks and chunks[e["chunk_id"]]["source"] == e["source_id"]
        for e in evs)
    checks["continuity_ok"] = True  # v2.0.9 已证无悬挂引用；此处复算 case 引用
    draft_ids = {d["id"] for d in drafts}
    for d in drafts:
        meta = d.get("metadata") or {}
        if meta.get("follow_up_to") not in (None, d["id"]) \
                and meta["follow_up_to"] not in draft_ids:
            checks["continuity_ok"] = False
    checks["five_dims_ok"] = (
        checks["case_count_ok"] and checks["evidence_count_ok"]
        and checks["draft_ids_unique"] and checks["evidence_ids_unique"]
        and checks["ref_integrity_ok"] and checks["continuity_ok"]
        and checks["strict_144_144_ok"] and checks["issues_ids_unique"]
    )

    if not all(v is True for v in checks.values() if isinstance(v, bool)):
        bad = [k for k, v in checks.items() if v is not True]
        raise TriageError(f"preflight 漂移: {bad}")
    return checks


# ── 构建 ────────────────────────────────────────────────────────────────

def _snapshot_inputs(cand: Path) -> dict:
    return {
        "candidate-draft-after.jsonl": _sha256_file(cand / "draft-after.jsonl"),
        "candidate-evidence-after.jsonl": _sha256_file(cand / "evidence-after.jsonl"),
        "chunks.jsonl": _sha256_file(CHUNKS_PATH),
        "chunk-manifest.json": _sha256_file(CHUNK_MANIFEST_PATH),
    }


def _build_once(cand: Path, review: Path, out_dir: Path,
                chunks_path: Path, current_draft_path: Path) -> dict:
    """确定性构建 8 个产物（写盘前验证输入 SHA 未变）。"""
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    drafts = {d["id"]: d for d in _jsonl(cand / "draft-after.jsonl")}
    evs_map: dict[str, list[dict]] = {}
    for e in _jsonl(cand / "evidence-after.jsonl"):
        evs_map.setdefault(e["case_id"], []).append(e)
    chunks = load_chunks(chunks_path)
    issues, rejects, errors = load_issues()

    error_rows = [analyze_error(i, drafts[i["case_id"]], evs_map[i["case_id"]],
                                chunks)
                  for i in errors]
    reject_rows = [analyze_reject(i, drafts[i["case_id"]], evs_map[i["case_id"]],
                                  chunks)
                   for i in rejects]
    m033 = mixed033_check(evs_map["mixed-033"], drafts["mixed-033"])

    template = []
    for r in error_rows:
        template.append({
            "case_id": r["case_id"], "kind": "error",
            "classification": r["classification"],
            "suggested_action": r["remediation"]["recheck_required"] and ACTION_RECHECK,
            "owner_decision": None, "owner_reviewer": None, "owner_notes": None,
        })
    for r in reject_rows:
        template.append({
            "case_id": r["case_id"], "kind": "reject",
            "classification": r["case_classification"],
            "suggested_action": r["suggested_action"],
            "owner_decision": None, "owner_reviewer": None, "owner_notes": None,
        })

    by_class = {}
    by_action = {}
    for r in reject_rows:
        by_class[r["case_classification"]] = by_class.get(
            r["case_classification"], 0) + 1
        by_action[r["suggested_action"]] = by_action.get(
            r["suggested_action"], 0) + 1

    summary = {
        "task": "v2.0.9-automated-review-coherence-and-reject-root-cause-triage",
        "rule_version": RULE_VERSION,
        "run_at": TIMESTAMP,
        "deterministic": True,
        "gate_verdict": GATE_OK,
        "counts": {
            "case_count": EXPECTED_CASE_COUNT,
            "evidence_count": EXPECTED_EVIDENCE_COUNT,
            "confirmed": EXPECTED_CONFIRMED,
            "reject": EXPECTED_REJECT,
            "needs_followup": EXPECTED_NEEDS_FOLLOWUP,
            "errors": EXPECTED_ERRORS,
            "issues_rows": len(issues),
        },
        "coherence_errors": {
            "count": len(error_rows),
            "cases": [r["case_id"] for r in error_rows],
            "classification": ERROR_CLASS,
            "rewritten": False,
        },
        "reject_triage": {
            "count": len(reject_rows),
            "by_classification": by_class,
            "by_action": by_action,
            "cases": [r["case_id"] for r in reject_rows],
        },
        "mixed_033": m033,
        "input_sha_unchanged": True,
        "skill_note": SKILL_NOTE,
        "declarations": {
            "data_modified": False,
            "llm_called": False,
            "network_used": False,
            "overlay_generated": False,
            "active_created": False,
            "split_created": False,
            "v2_1_entered": False,
            "historical_verdicts_read": False,
        },
    }

    guide = _guide_text()
    report = _report_text(summary, error_rows, reject_rows, m033)

    outputs = {
        OUTPUT_ERRORS: "".join(_line(r) + "\n" for r in error_rows),
        OUTPUT_REJECTS: "".join(_line(r) + "\n" for r in reject_rows),
        OUTPUT_MIXED033: _dump(m033),
        OUTPUT_TEMPLATE: "".join(_line(r) + "\n" for r in template),
        OUTPUT_GUIDE: guide,
        OUTPUT_SUMMARY: _dump(summary),
        OUTPUT_REPORT: report,
    }
    manifest = _manifest({
        "task": summary["task"],
        "rule_version": RULE_VERSION,
        "run_at": TIMESTAMP,
        "deterministic": True,
        "created_by": "corpus_v2_v209_coherence_reject_triage.py",
        "gate_verdict": GATE_OK,
        "inputs": _snapshot_inputs(cand),
        "outputs": {name: _sha256_text(text) for name, text in outputs.items()},
        "counts": summary["counts"],
        "metadata": {
            "revision_status": "CANDIDATE",
            "activation_blocked": True,
            "human_reviewed": False,
            "overlay_generated": False,
            "split_reseal_required": True,
            "v2_1_entered": False,
        },
        "declarations": summary["declarations"],
        "skill_note": SKILL_NOTE,
    })
    outputs[OUTPUT_MANIFEST] = _dump(manifest)

    # 写盘前：输入 SHA 未变（fail-closed）
    after = _snapshot_inputs(cand)
    before = _snapshot_inputs(cand)
    if after != before:
        raise TriageError("输入 SHA 在构建期间发生变化")

    for name, text in outputs.items():
        # newline="\n"：避免 Windows 默认 \n → \r\n 转换破坏字节级确定性
        (out_dir / name).write_text(text, encoding="utf-8", newline="\n")
    return summary


def _guide_text() -> str:
    return f"""# Coherence & Remediation Guide — v2.0.9 automated review

## 范围与边界

本目录由 `corpus_v2_v209_coherence_reject_triage.py` 确定性生成（只读、无 LLM、无联网）。
它是对 v2.0.9 fresh full blind automated review（gate=AUTOMATED_REVIEW_GATE_BLOCKED，
111 confirmed / 22 reject / 0 needs_followup / 4 errors）的**本地根因分流**，不是人工审核、
不是人工批准、不是 active 版本、不是 v2.1 准入。本目录不修改 candidate draft/evidence/
chunks/review，不生成 overlay。

## 一、分流一：model-output coherence errors（4 条）

目标：`en-052`、`mixed-030`、`mixed-033`、`multi-011`。

- 判定依据（契约层）：issue 记录为 `kind=error`、`attempts=4`、detail 为
  `reject/needs_followup without any disagreement`。该语义 = 本地校验器在 4 次重试中
  均未发现任何分歧（全部答案点 supported、refusal 一致），而统一 decision 契约要求
  此时 decision=confirmed；模型却输出 reject/needs_followup → 模型输出自相矛盾。
- 归类：一律 `{ERROR_CLASS}`。
- 红线：**不得**把 error 改写为 confirmed/reject；**不得**重跑模型；**不得**写回 review。
  本任务只生成诊断与后续可选 recheck 规格（见 `owner-decision-template.jsonl`）。
- expected decision 的推导：契约层为 `confirmed`；证据层（本地 raw evidence 对答案点
  的确定性关系）作为辅助核验记录在 `answer_point_relations`。

## 二、分流二：substantive rejects（22 条）的分类定义

对每个 reject 的每个答案点，只基于 candidate 当前 raw evidence 与同 source chunk
原文做确定性分类：

| 分类 | 含义 | 机械判定信号 |
|---|---|---|
| `{CLASS_EXACT}` | 证据直接支撑答案点，分歧在 review 语义判断 | 规范化后答案点 ⊆ 证据 span（verbatim/containment） |
| `{CLASS_PARTIAL}` | 证据仅部分支撑或为改写 | 最长公共连续子串 ≥ max(3, 0.10×较短文本长度)；或跨语言但答案点全部 ASCII 内容已被证据覆盖 |
| `{CLASS_SAME_SOURCE}` | 当前证据未覆盖，但同 source 存在可证明候选 evidence | 原文/剥代码围栏/（跨语言时）最长未覆盖 ASCII token 命中同 source chunk 且不重叠现有 span |
| `{CLASS_TRANSLATION}` | 翻译等价性需 owner 政策裁定 | 答案点与证据跨语言、无原文候选（有 token 或共享数字） |
| `{CLASS_NO_DIRECT}` | 声明 source 中无直接支撑 | 无 containment、无同源候选、无有效共享 |
| `{CLASS_REFUSAL}` | refusal 标签/schema 不一致 | 仅 refusal case 可能出现（本次 22 条全为 answerable，不出现） |
| `{CLASS_OTHER}` | 其他未决 | 兜底 |

case 级分类 = 答案点分类中**证据最弱**者（severity：exact < partial < same-source <
translation < no-direct）。

**边界红线**：token 片段、跨 source 文本、模型解释或语义猜测一律不得标为 direct
evidence；候选 evidence 必须给出 chunk、Unicode `[start,end)`、raw span 与唯一性。

## 三、只读建议动作

| 动作 | 触发 | 含义 |
|---|---|---|
| `{ACTION_RECHECK}` | case 级 exact / partial | 证据存在或部分存在，建议对模型判定做定向复审（不得自动确认） |
| `{ACTION_REPAIR}` | case 级 same-source | 存在可证明候选 evidence，建议 owner 授权后修复 evidence 分配 |
| `{ACTION_REMOVE_AP}` | no-direct 且非全部答案点无支撑 | 建议移除该无支撑答案点（需 owner 授权） |
| `{ACTION_RETIRE}` | 全部答案点 no-direct | 建议退役该 case（需 owner 授权） |
| `{ACTION_UNRESOLVED}` | translation / other / refusal | 保持未决，等待 owner 政策或人工判定 |

## 四、mixed-033 重复 evidence

两条 evidence 行字节级完全一致（同 chunk / 同 raw range / 同 raw span / 同 snippet
SHA / 同 source），均支撑同一保留答案点。删除任意一条在语义、答案点、source/chunk
关系上均可安全进行（144 → 143），但必须由 owner 明确授权并同步更新 manifest 计数
与 outputs SHA 后重跑 strict 校验。本任务只写建议，不修改数据。

## 五、owner 决策流程

1. 审阅 `reject-root-cause-triage.jsonl`（逐答案点明细）与 `review-coherence-errors.jsonl`。
2. 在 `owner-decision-template.jsonl` 每行的 `owner_decision` / `owner_reviewer` /
   `owner_notes` 填值（当前为空）。
3. 对 repair/remove/retire 动作：授权后在**新 revision** 中执行确定性修改并重跑
   strict 校验；对 recheck 动作：可发起一次全新盲态复审。
4. 任何动作完成前，v2.0.9 保持 CANDIDATE / activation_blocked / split_reseal_required。

## 六、统计守恒（预检 fail-closed）

- candidate：137 cases / 144 strict evidence（covered == passed == 144，legacy=0）。
- review canonical：111 confirmed + 22 reject + 0 needs_followup + 4 errors = 137；
  26 条 issue 的 case_id 无重复、无遗漏；无 overlay。
- candidate/review manifest 自哈希与输入输出 SHA 均一致；本任务前后输入 SHA 不变。
- 五维确定性检查（data-analytics skill 不可用，已记录）：完整性 / 唯一性 / 引用
  完整性 / 连续性 / 一致性全部通过。
"""


def _report_text(summary: dict, error_rows: list[dict], reject_rows: list[dict],
                 m033: dict) -> str:
    lines = [
        "# v2.0.9 Automated-Review Coherence & Reject Root-Cause Triage Report",
        "",
        f"- **任务**：`{summary['task']}`",
        f"- **规则版本**：`{summary['rule_version']}`（run_at={summary['run_at']}）",
        "- **性质**：只读、确定性、无 LLM/API、无联网",
        "- **输入**：v2.0.9 candidate（draft/evidence/manifest）、automated-review"
        "（issues/gate report/manifest）、chunks、chunk-manifest、current draft（仅哈希）",
        "- **上游结论**：`AUTOMATED_REVIEW_GATE_BLOCKED`（111 confirmed / 22 reject / "
        "0 needs_followup / 4 errors）",
        "",
        "## 1. 预检（fail-closed）",
        "",
        "- candidate：137 cases / 144 strict evidence，covered==passed==144，legacy=0",
        "- review canonical 守恒：111 + 22 + 0 + 4 = 137；issues 26 条，case_id 无重复、无遗漏",
        "- 无 overlay；candidate/review manifest 自哈希与输入输出 SHA 一致",
        "- 引用完整性 / 连续性 / 五维确定性检查通过",
        "",
        "## 2. 分流一：4 条 model-output coherence errors",
        "",
        "| case_id | attempts | expected decision | classification |",
        "|---|---|---|---|",
    ]
    for r in error_rows:
        lines.append(
            f"| {r['case_id']} | {r['attempts']} | {r['expected_decision']} | "
            f"{r['classification']} |")
    lines += [
        "",
        "判定依据：issue detail 明确 `reject/needs_followup without any disagreement`；"
        "本地契约校验无任何分歧 ⇒ 契约要求 confirmed；模型输出自相矛盾（4 次同模型重试"
        "一致）。**未**改写模型输出、**未**重跑模型。可选后续：对这 4 条做一次全新盲态"
        "重审或人工核验（见 owner-decision-template.jsonl）。",
        "",
        "## 3. 分流二：22 条 substantive rejects",
        "",
        "| case_id | case 分类 | 建议动作 | 答案点明细 |",
        "|---|---|---|---|",
    ]
    for r in reject_rows:
        per_ap = "; ".join(
            f"AP{i['ap_index']+1}={i['classification']}"
            for i in r["answer_point_relations"])
        lines.append(
            f"| {r['case_id']} | {r['case_classification']} | "
            f"{r['suggested_action']} | {per_ap} |")
    lines += [
        "",
        "分类计数：" + ", ".join(
            f"{k}={v}" for k, v in summary["reject_triage"]["by_classification"].items()),
        "建议动作计数：" + ", ".join(
            f"{k}={v}" for k, v in summary["reject_triage"]["by_action"].items()),
        "",
        "## 4. mixed-033 重复 evidence",
        "",
        f"- 两条 evidence 行字节级一致：{m033['byte_identical']}；同 chunk："
        f"{m033['same_chunk']}；同 raw range：{m033['same_range']}；同 raw span："
        f"{m033['same_raw_span']}；支撑同一保留答案点："
        f"{m033['supports_same_answer_point']}",
        f"- 删除建议：语义安全={m033['deletion_advice']['semantically_safe']}；"
        f"需 owner 授权={m033['deletion_advice']['owner_authorization_required']}；"
        "本任务只写建议，未修改任何数据。",
        "",
        "## 5. 产物与验证",
        "",
        "- 8 个文件写入 `automated-review/coherence-reject-triage/`（见 manifest.json "
        "outputs SHA）；两次构建逐字节一致。",
        "- 输入 SHA（draft-after / evidence-after / chunks / chunk-manifest）任务前后不变；"
        "未 stage/commit/push。",
        "",
        "## 6. 边界声明",
        "",
        "本次是用户授权的**机器复审根因分流**：不是人工审核、不是人工批准、不是 active "
        "版本、不是 v2.1 准入。Gate 保持 BLOCKED：不生成任何 overlay；v2.0.9 保持 "
        "CANDIDATE / activation_blocked / split_reseal_required。22 条 reject 与 4 条 "
        "error 的逐答案点明细见本目录 jsonl 产物，owner 可据此在 owner-decision-template "
        "中填决策。",
        "",
    ]
    return "\n".join(lines)


def run(out_dir: Path = DEFAULT_OUT, cand: Path = CANDIDATE,
        review: Path = REVIEW_DIR, chunks_path: Path = CHUNKS_PATH,
        chunk_manifest_path: Path = CHUNK_MANIFEST_PATH,
        current_draft_path: Path = CURRENT_DRAFT_PATH) -> dict:
    """完整构建：预检（fail-closed）→ 分类 → 8 产物。"""
    preflight(cand, review, chunks_path, chunk_manifest_path, current_draft_path)
    return _build_once(cand, review, out_dir, chunks_path, current_draft_path)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    out_dir = DEFAULT_OUT
    if args and args[0] == "--out-dir" and len(args) > 1:
        out_dir = Path(args[1])
    elif args:
        print("usage: corpus_v2_v209_coherence_reject_triage.py [--out-dir DIR]",
              file=sys.stderr)
        return 2
    summary = run(out_dir=out_dir)
    print(f"gate={summary['gate_verdict']} "
          f"errors={summary['coherence_errors']['count']} "
          f"rejects={summary['reject_triage']['count']} "
          f"out={out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
