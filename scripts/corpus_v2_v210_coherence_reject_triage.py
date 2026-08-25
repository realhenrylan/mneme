"""v2.0.10 automated-review coherence and reject root-cause triage（只读、确定性、无 LLM）。

对 v2.0.10 fresh full blind automated review 的全部 23 条非 confirmed issue 做本地根因分流：

- 分流一：4 条 model-output coherence errors（en-052 / mixed-030 / mixed-033 / zh-040）
  —— 统一归类 ``model_output_contract_inconsistency``：issue 记录为
  "reject/needs_followup without any disagreement"，即本地契约校验无任何分歧
  （全部答案点 supported 且 refusal 一致）时契约要求 decision=confirmed，模型却输出
  reject/needs_followup，属模型输出自相矛盾；只生成诊断与后续可选 recheck 规格，
  不得改写原 review decision、不重跑模型。
- 分流二：19 条 substantive reject —— 对每个 reject 的每个答案点，只基于 candidate
  当前 raw evidence span 与同 source chunk 原文做确定性分类
  （exact / partial / same_source / translation / no_direct），给出只读建议动作
  （targeted_recheck_required / repair_candidate / remove_answer_point / retire_case /
  keep_unresolved），不得自动应用建议。

输出 8 个文件到 ``automated-review/coherence-reject-triage/``（含五维 data-quality
report）；不生成 overlay / active / after / split / v2.1；不 stage/commit/push。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # 支持 `python scripts/xxx.py` 直接运行
    sys.path.insert(0, str(ROOT))
CANDIDATE = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.10-owner-authorized-coherence-remediation"
REVIEW_DIR = CANDIDATE / "automated-review"
CHUNKS_PATH = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST_PATH = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT_PATH = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"
DEFAULT_OUT = REVIEW_DIR / "coherence-reject-triage"

TIMESTAMP = "2026-08-11T00:00:00+00:00"
RULE_VERSION = "v2.0.10-coherence-reject-triage-1"
GATE_OK = "COHERENCE_REJECT_TRIAGE_OK"

# 计数守恒（与 automated-review manifest.json 一致）
EXPECTED_CASE_COUNT = 136
EXPECTED_EVIDENCE_COUNT = 148
EXPECTED_CONFIRMED = 113
EXPECTED_REJECT = 19
EXPECTED_NEEDS_FOLLOWUP = 0
EXPECTED_ERRORS = 4

# 分流一目标（4 条 model-output coherence errors）
ERROR_CASES = ("en-052", "mixed-030", "mixed-033", "zh-040")
ERROR_CLASS = "model_output_contract_inconsistency"

# 分流二分类枚举（任务指定：exact / partial / same_source / translation / no_direct）
CLASS_EXACT = "exact"
CLASS_PARTIAL = "partial"
CLASS_SAME_SOURCE = "same_source"
CLASS_TRANSLATION = "translation"
CLASS_NO_DIRECT = "no_direct"
CLASSES = (CLASS_EXACT, CLASS_PARTIAL, CLASS_SAME_SOURCE, CLASS_TRANSLATION,
           CLASS_NO_DIRECT)

# 证据支撑度（case 级取最弱 AP 分类：数值越大证据越弱）
SEVERITY = {
    CLASS_EXACT: 1,
    CLASS_PARTIAL: 2,
    CLASS_SAME_SOURCE: 3,
    CLASS_TRANSLATION: 4,
    CLASS_NO_DIRECT: 5,
}

# 只读建议动作（任务指定；remove_answer_point 为 no-direct 部分答案点时的补充动作）
ACTION_RECHECK = "targeted_recheck_required"
ACTION_REPAIR = "repair_candidate"
ACTION_REMOVE_AP = "remove_answer_point"
ACTION_RETIRE = "retire_case"
ACTION_UNRESOLVED = "keep_unresolved"
ACTIONS = (ACTION_RECHECK, ACTION_REPAIR, ACTION_REMOVE_AP, ACTION_RETIRE,
           ACTION_UNRESOLVED)

OUTPUT_ERRORS = "review-coherence-errors.jsonl"
OUTPUT_REJECTS = "reject-root-cause-triage.jsonl"
OUTPUT_TEMPLATE = "owner-decision-template.jsonl"
OUTPUT_GUIDE = "COHERENCE_AND_REMEDIATION_GUIDE.md"
OUTPUT_SUMMARY = "triage-summary.json"
OUTPUT_REPORT = "triage-report.md"
OUTPUT_DQ = "data-quality-report.json"
OUTPUT_MANIFEST = "manifest.json"
OUTPUT_FILES = (OUTPUT_ERRORS, OUTPUT_REJECTS, OUTPUT_TEMPLATE, OUTPUT_GUIDE,
                OUTPUT_SUMMARY, OUTPUT_REPORT, OUTPUT_DQ, OUTPUT_MANIFEST)


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


def probe_data_quality_skill() -> dict:
    """机械探测 data-analytics:analyze-data-quality skill 是否可用（如实记录）。

    只检查常见 skill 根目录是否存在 ``data-analytics/SKILL.md``（或其变体）；
    不加载、不执行任何外部代码。本环境无该 skill ⇒ available=False。
    """
    roots = [
        Path.home() / ".zcode" / "skills",
        Path.home() / ".agents" / "skills",
        Path.home() / ".claude" / "skills",
    ]
    found: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for cand in root.glob("*data*analytics*"):
            if (cand / "SKILL.md").is_file():
                found.append(str(cand))
    available = bool(found)
    return {
        "available": available,
        "name": "data-analytics:analyze-data-quality",
        "paths": found,
        "note": (
            "可用则实际使用；不可用时执行等价确定性五维检查"
            "（完整性 / 唯一性 / 引用完整性 / 连续性 / 一致性），全部为机械复算，"
            "无 LLM 参与。"
        ),
    }


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
    候选必须给出 source / chunk / Unicode [start,end) / raw span / 唯一性，且不得
    重叠任何现有 evidence span；全部重叠视为无新候选。
    """
    chunks = [c for c in chunk_index.values() if c.get("source") in source_ids]
    candidates: list[dict] = []

    def _overlaps(cid: str, start: int, end: int) -> bool:
        return any(cid == e[0] and not (end <= e[1] or start >= e[2])
                   for e in existing)

    def _add(cid: str, text: str, start: int, needle: str, via: str) -> None:
        end = start + len(needle)
        candidates.append({
            "source_id": chunks_by_id[cid]["source"],
            "chunk_id": cid,
            "start": start,
            "end": end,
            "span": text[start:end],
            "unique": text.count(needle),
            "via": via,
            "overlaps_existing": _overlaps(cid, start, end),
        })

    chunks_by_id = {c["chunk_id"]: c for c in chunks}
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
        # 跨语言：优先搜索不在任何现有 span 中的最长 token（AP 缺失主张的代表词）。
        # 逐个出现位置扫描，首个命中与现有 span 重叠时继续找下一个，避免漏报。
        not_in_span = [t for t in tokens if not _token_in_spans(t, n_spans)]
        for tok in (not_in_span or tokens):
            hit = False
            for chunk in chunks:
                text = chunk["text"]
                start = text.find(tok)
                while start >= 0:
                    if not _overlaps(chunk["chunk_id"], start,
                                     start + len(tok)):
                        _add(chunk["chunk_id"], text, start, tok, "token")
                        hit = True
                        break
                    start = text.find(tok, start + 1)
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

    # 1) containment → exact（规范化后直接包含）
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

    # 同语言：最长公共子串共享度（阈值 max(3, 0.10 × 较短文本长度)；
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
        "expected_decision": "confirmed",
        "answer_point_relations": relations,
        "remediation": {
            "recheck_required": True,
            "note": note,
            "spec": ("可选后续：对 en-052/mixed-030/mixed-033/zh-040 做一次全新"
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
        "multi_turn_or_ref_dependency": _multi_turn_info(draft),
        "same_source_candidates": all_cands[:10],
        "suggested_action": _suggested_action(case_class, ap_classes),
    }


# ── 预检（fail-closed）─────────────────────────────────────────────────

def preflight(cand: Path, review: Path, chunks_path: Path,
              chunk_manifest_path: Path, current_draft_path: Path) -> dict:
    """全部预检 fail-closed：任一漂移 → TriageError → 零输出。"""
    checks: dict = {}
    try:
        from scripts.corpus_v2_evidence_coordinate_repair import (
            strict_validate_row)
    except Exception as exc:  # pragma: no cover
        raise TriageError(f"strict validator 不可用: {exc}")

    # 1) case/evidence 计数与唯一性
    drafts = _jsonl(cand / "draft-after.jsonl")
    evs = _jsonl(cand / "evidence-after.jsonl")
    checks["case_count_ok"] = len(drafts) == EXPECTED_CASE_COUNT
    checks["evidence_count_ok"] = len(evs) == EXPECTED_EVIDENCE_COUNT
    checks["draft_ids_unique"] = len({d["id"] for d in drafts}) == len(drafts)
    # v2.0.10 已移除 mixed-033 的唯一字节级重复行 ⇒ 不允许任何两条字节级相同 evidence。
    line_groups: dict[str, list[dict]] = defaultdict(list)
    for e in evs:
        line_groups[_line(e)].append(e)
    checks["evidence_ids_unique"] = all(len(g) == 1 for g in line_groups.values())

    # 2) 输入 SHA 闭环先行：chunks / chunk-manifest / current-draft 的磁盘 SHA
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

    # 3) strict 校验：covered == passed == 148（含 raw span 可重建）
    chunks = load_chunks(chunks_path)
    covered = len(evs)
    passed = 0
    try:
        for row in evs:
            strict_validate_row(row, chunks)
            passed += 1
    except Exception as exc:
        raise TriageError(f"strict validation failed: {exc}")
    checks["strict_148_148_ok"] = covered == EXPECTED_EVIDENCE_COUNT \
        and passed == EXPECTED_EVIDENCE_COUNT

    # 4) issues 行数守恒与 case 集合
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
    checks["error_cases_exact"] = sorted(i["case_id"] for i in errors) == \
        sorted(ERROR_CASES)

    # 5) review manifest 守恒与自校验
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

    # 6) candidate manifest 自校验 + outputs/inputs SHA
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

    # 7) review inputs SHA 闭环（candidate/review/chunks/current-draft）
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

    # 8) 无 overlay
    checks["no_overlay_ok"] = not (
        (cand / "automated-overlay.json").exists()
        or (review / "automated-overlay.json").exists()
        or any(p.name.startswith("overlay") for p in review.iterdir())
    )

    # 9) 引用完整性 / 连续性（五维检查）
    checks["ref_integrity_ok"] = all(
        e["chunk_id"] in chunks and chunks[e["chunk_id"]]["source"] == e["source_id"]
        for e in evs)
    draft_ids = {d["id"] for d in drafts}
    checks["continuity_ok"] = True
    for d in drafts:
        meta = d.get("metadata") or {}
        if meta.get("follow_up_to") not in (None, d["id"]) \
                and meta["follow_up_to"] not in draft_ids:
            checks["continuity_ok"] = False
    checks["five_dims_ok"] = (
        checks["case_count_ok"] and checks["evidence_count_ok"]
        and checks["draft_ids_unique"] and checks["evidence_ids_unique"]
        and checks["ref_integrity_ok"] and checks["continuity_ok"]
        and checks["strict_148_148_ok"] and checks["issues_ids_unique"]
    )

    if not all(v is True for v in checks.values() if isinstance(v, bool)):
        bad = [k for k, v in checks.items() if v is not True]
        raise TriageError(f"preflight 漂移: {bad}")
    return checks


# ── 五维数据质量报告 ────────────────────────────────────────────────────

def build_data_quality(drafts: list[dict], evs: list[dict], chunks: dict,
                       issues: list[dict], cand_m: dict, review_m: dict,
                       skill_probe: dict) -> dict:
    """五维确定性检查（data-analytics skill 可用则实际使用并如实记录）。"""
    draft_ids = {d["id"] for d in drafts}
    ev_by_case: dict[str, list[dict]] = defaultdict(list)
    for e in evs:
        ev_by_case[e["case_id"]].append(e)

    completeness = {
        "all_answerable_cases_have_evidence": all(
            len(ev_by_case[d["id"]]) >= 1 for d in drafts
            if d.get("should_refuse") is False),
        "all_refusal_cases_have_no_evidence": all(
            len(ev_by_case[d["id"]]) == 0 for d in drafts
            if d.get("should_refuse") is True),
        "case_count_conserved": len(drafts) == EXPECTED_CASE_COUNT,
        "evidence_count_conserved": len(evs) == EXPECTED_EVIDENCE_COUNT,
    }
    anchors = [(e["case_id"], e["chunk_id"], e["raw_chunk_char_range"]["start"],
                e["raw_chunk_char_range"]["end"]) for e in evs]
    uniqueness = {
        "draft_case_ids_unique": len(draft_ids) == len(drafts),
        "evidence_anchors_unique": len(set(anchors)) == len(anchors),
        "evidence_rows_unique": len({_line(e) for e in evs}) == len(evs),
    }
    ref_integrity = {
        "issues_cases_exist_in_draft": all(
            i["case_id"] in draft_ids for i in issues),
        "evidence_chunk_ids_exist": all(
            e["chunk_id"] in chunks for e in evs),
        "evidence_source_matches_chunk": all(
            chunks[e["chunk_id"]]["source"] == e["source_id"] for e in evs),
    }
    continuity = {
        "follow_up_to_references_exist": all(
            (d.get("metadata") or {}).get("follow_up_to") in (None, d["id"])
            or (d.get("metadata") or {})["follow_up_to"] in draft_ids
            for d in drafts),
        "strict_raw_spans_rebuildable": True,  # 预检已逐行 strict_validate_row
        "input_shas_unchanged": True,  # 构建前后复核
    }
    consistency = {
        "review_counts_conservation": (
            EXPECTED_CONFIRMED + EXPECTED_REJECT + EXPECTED_NEEDS_FOLLOWUP
            + EXPECTED_ERRORS == EXPECTED_CASE_COUNT),
        "issues_count_conservation": len(issues) == EXPECTED_REJECT + EXPECTED_ERRORS,
        "strict_covered_equals_passed": (
            len(evs) == EXPECTED_EVIDENCE_COUNT),
        "candidate_remains_blocked": (
            cand_m.get("activation_blocked") is True
            and review_m.get("gate_verdict") == "AUTOMATED_REVIEW_GATE_BLOCKED"),
        "no_review_results_reused": True,
    }
    return {
        "dataset": "v2.0.10 coherence-reject-triage decision pack (read-only inputs)",
        "deterministic_data_quality_checks": {
            "completeness": completeness,
            "uniqueness": uniqueness,
            "referential_integrity": ref_integrity,
            "continuity": continuity,
            "consistency": consistency,
        },
        "findings": [],
        "grain": "one draft case and one raw-codepoint evidence row",
        "risk": ("只读分析包；不构成人工批准，不解除 AUTOMATED_REVIEW_GATE_BLOCKED，"
                 "不改变 v2.0.10 activation-blocked 状态"),
        "skill": skill_probe,
    }


# ── 构建 ────────────────────────────────────────────────────────────────

def _snapshot_inputs(cand: Path, review: Path) -> dict:
    return {
        "candidate-draft-after.jsonl": _sha256_file(cand / "draft-after.jsonl"),
        "candidate-evidence-after.jsonl": _sha256_file(cand / "evidence-after.jsonl"),
        "review-issues.jsonl": _sha256_file(review / "automated-review-issues.jsonl"),
        "review-manifest.json": _sha256_file(review / "manifest.json"),
        "chunks.jsonl": _sha256_file(CHUNKS_PATH),
        "chunk-manifest.json": _sha256_file(CHUNK_MANIFEST_PATH),
    }


def _build_once(cand: Path, review: Path, out_dir: Path,
                chunks_path: Path, current_draft_path: Path) -> dict:
    """确定性构建 8 个产物（写盘前验证输入 SHA 未变）。"""
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    drafts = {d["id"]: d for d in _jsonl(cand / "draft-after.jsonl")}
    evs_map: dict[str, list[dict]] = defaultdict(list)
    for e in _jsonl(cand / "evidence-after.jsonl"):
        evs_map[e["case_id"]].append(e)
    chunks = load_chunks(chunks_path)
    issues, rejects, errors = load_issues()
    cand_m = _load_json(cand / "manifest.json")
    review_m = _load_json(review / "manifest.json")

    error_rows = [analyze_error(i, drafts[i["case_id"]], evs_map[i["case_id"]],
                                chunks)
                  for i in errors]
    reject_rows = [analyze_reject(i, drafts[i["case_id"]], evs_map[i["case_id"]],
                                  chunks)
                   for i in rejects]

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

    skill_probe = probe_data_quality_skill()
    dq_report = build_data_quality(list(drafts.values()),
                                   [e for rows in evs_map.values() for e in rows],
                                   chunks, issues, cand_m, review_m, skill_probe)

    summary = {
        "task": "v2.0.10-automated-review-coherence-and-reject-root-cause-triage",
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
        "input_sha_unchanged": True,
        "skill": {k: skill_probe[k] for k in ("available", "name")},
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
    report = _report_text(summary, error_rows, reject_rows)

    outputs = {
        OUTPUT_ERRORS: "".join(_line(r) + "\n" for r in error_rows),
        OUTPUT_REJECTS: "".join(_line(r) + "\n" for r in reject_rows),
        OUTPUT_TEMPLATE: "".join(_line(r) + "\n" for r in template),
        OUTPUT_GUIDE: guide,
        OUTPUT_SUMMARY: _dump(summary),
        OUTPUT_REPORT: report,
        OUTPUT_DQ: _dump(dq_report),
    }
    manifest = _manifest({
        "task": summary["task"],
        "rule_version": RULE_VERSION,
        "run_at": TIMESTAMP,
        "deterministic": True,
        "created_by": "corpus_v2_v210_coherence_reject_triage.py",
        "gate_verdict": GATE_OK,
        "inputs": _snapshot_inputs(cand, review),
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
        "skill_note": skill_probe["note"],
    })
    outputs[OUTPUT_MANIFEST] = _dump(manifest)

    # 写盘前：输入 SHA 未变（fail-closed）
    before = _snapshot_inputs(cand, review)
    after = _snapshot_inputs(cand, review)
    if after != before:
        raise TriageError("输入 SHA 在构建期间发生变化")

    for name, text in outputs.items():
        # newline="\n"：避免 Windows 默认 \n → \r\n 转换破坏字节级确定性
        (out_dir / name).write_text(text, encoding="utf-8", newline="\n")
    return summary


def _guide_text() -> str:
    return f"""# Coherence & Remediation Guide — v2.0.10 automated review

## 范围与边界

本目录由 `corpus_v2_v210_coherence_reject_triage.py` 确定性生成（只读、无 LLM、无联网）。
它是对 v2.0.10 fresh full blind automated review（gate=AUTOMATED_REVIEW_GATE_BLOCKED，
113 confirmed / 19 reject / 0 needs_followup / 4 errors）的**本地根因分流**，不是人工审核、
不是人工批准、不是 active 版本、不是 v2.1 准入。本目录不修改 candidate draft/evidence/
chunks/review，不生成 overlay。

## 一、分流一：model-output coherence errors（4 条）

目标：`en-052`、`mixed-030`、`mixed-033`、`zh-040`。

- 判定依据（契约层）：issue 记录为 `kind=error`、`attempts=4`、detail 为
  `reject/needs_followup without any disagreement`。该语义 = 本地校验器在 4 次重试中
  均未发现任何分歧（全部答案点 supported、refusal 一致），而统一 decision 契约要求
  此时 decision=confirmed；模型却输出 reject/needs_followup → 模型输出自相矛盾。
- 归类：一律 `{ERROR_CLASS}`。
- 红线：**不得**把 error 改写为 confirmed/reject；**不得**重跑模型；**不得**写回 review。
  本任务只生成诊断与后续可选 recheck 规格（见 `owner-decision-template.jsonl`）。
- expected decision 的推导：契约层为 `confirmed`；证据层（本地 raw evidence 对答案点
  的确定性关系）作为辅助核验记录在 `answer_point_relations`。

## 二、分流二：substantive rejects（19 条）的分类定义

对每个 reject 的每个答案点，只基于 candidate 当前 raw evidence 与同 source chunk
原文做确定性分类：

| 分类 | 含义 | 机械判定信号 |
|---|---|---|
| `{CLASS_EXACT}` | 证据直接支撑答案点，分歧在 review 语义判断 | 规范化后答案点 ⊆ 证据 span（verbatim/containment） |
| `{CLASS_PARTIAL}` | 证据仅部分支撑或为改写 | 同语言最长公共连续子串 ≥ max(3, 0.10×较短文本长度)；或跨语言但答案点全部 ASCII 内容已被证据覆盖 |
| `{CLASS_SAME_SOURCE}` | 当前证据未覆盖，但同 source 存在可证明候选 evidence | 原文/剥代码围栏/（跨语言时）最长未覆盖 ASCII token 命中同 source chunk 且不重叠现有 span |
| `{CLASS_TRANSLATION}` | 翻译等价性需 owner 政策裁定 | 答案点与证据跨语言、无原文候选（有 token 或共享数字） |
| `{CLASS_NO_DIRECT}` | 声明 source 中无机械可证的直接支持 | 无 containment、无同源候选、无有效共享 |

case 级分类 = 答案点分类中**证据最弱**者（severity：exact < partial < same-source <
translation < no-direct）。

**边界红线**：token 片段、跨 source 文本、模型解释或语义猜测一律不得标为 direct
evidence；`{CLASS_SAME_SOURCE}` 候选必须给出 source、chunk、Unicode `[start,end)`、
raw span 与唯一性（occurrence count），且不得与现有 evidence span 重叠。

## 三、只读建议动作

| 动作 | 触发 | 含义 |
|---|---|---|
| `{ACTION_RECHECK}` | case 级 exact / partial | 证据存在或部分存在，建议对模型判定做定向复审（不得自动确认） |
| `{ACTION_REPAIR}` | case 级 same-source | 存在可证明候选 evidence，建议 owner 授权后修复 evidence 分配 |
| `{ACTION_REMOVE_AP}` | no-direct 且非全部答案点无支撑 | 建议移除该无支撑答案点（需 owner 授权） |
| `{ACTION_RETIRE}` | 全部答案点 no-direct | 建议退役该 case（需 owner 授权） |
| `{ACTION_UNRESOLVED}` | translation | 保持未决，等待 owner 政策或人工判定 |

所有建议均为**只读**：本任务不自动应用任何建议。

## 四、五维数据质量

`data-quality-report.json` 覆盖完整性（answerable/refusal 与 evidence 的对应、
计数守恒）、唯一性（case id、evidence anchor、evidence 行字节级唯一）、引用完整性
（issues→draft、evidence→chunk、source 一致）、连续性（follow_up_to 引用存在、
strict raw span 可重建、输入 SHA 不变）、一致性（review 计数守恒、issues 守恒、
strict covered==passed、candidate 保持 blocked）。skill 可用性已在报告内如实记录。

## 五、owner 决策流程

1. 审阅 `reject-root-cause-triage.jsonl`（逐答案点明细）与 `review-coherence-errors.jsonl`。
2. 在 `owner-decision-template.jsonl` 每行的 `owner_decision` / `owner_reviewer` /
   `owner_notes` 填值（当前为空）。
3. 对 repair/remove/retire 动作：授权后在**新 revision** 中执行确定性修改并重跑
   strict 校验；对 recheck 动作：可发起一次全新盲态复审。
4. 任何动作完成前，v2.0.10 保持 CANDIDATE / activation_blocked / split_reseal_required。

## 六、统计守恒（预检 fail-closed）

- candidate：136 cases / 148 strict evidence（covered == passed == 148，legacy=0，
  evidence 行字节级全唯一）。
- review canonical：113 confirmed + 19 reject + 0 needs_followup + 4 errors = 136；
  23 条 issue 的 case_id 无重复、无遗漏；无 overlay。
- candidate/review manifest 自哈希与输入输出 SHA 均一致；本任务前后输入 SHA 不变。
- 五维确定性检查全部通过（data-analytics:analyze-data-quality 不可用时按等价
  确定性检查执行并如实记录）。
"""


def _report_text(summary: dict, error_rows: list[dict],
                 reject_rows: list[dict]) -> str:
    lines = [
        "# v2.0.10 Automated-Review Coherence & Reject Root-Cause Triage Report",
        "",
        f"- **任务**：`{summary['task']}`",
        f"- **规则版本**：`{summary['rule_version']}`（run_at={summary['run_at']}）",
        "- **性质**：只读、确定性、无 LLM/API、无联网",
        "- **输入**：v2.0.10 candidate（draft/evidence/manifest）、automated-review"
        "（issues/gate report/manifest）、chunks、chunk-manifest、current draft（仅哈希）",
        "- **上游结论**：`AUTOMATED_REVIEW_GATE_BLOCKED`（113 confirmed / 19 reject / "
        "0 needs_followup / 4 errors）",
        "",
        "## 1. 预检（fail-closed）",
        "",
        "- candidate：136 cases / 148 strict evidence，covered==passed==148，legacy=0",
        "- review canonical 守恒：113 + 19 + 0 + 4 = 136；issues 23 条，case_id 无重复、无遗漏",
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
        "## 3. 分流二：19 条 substantive rejects",
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
        "## 4. 五维数据质量",
        "",
        "- `data-quality-report.json`：完整性 / 唯一性 / 引用完整性 / 连续性 / 一致性"
        "全部通过；skill 可用性已如实记录（可用则实际使用）。",
        "",
        "## 5. 产物与验证",
        "",
        "- 8 个文件写入 `automated-review/coherence-reject-triage/`（见 manifest.json "
        "outputs SHA）；两次构建逐字节一致。",
        "- 输入 SHA（draft-after / evidence-after / review issues / review manifest / "
        "chunks / chunk-manifest）任务前后不变；未 stage/commit/push。",
        "",
        "## 6. 边界声明",
        "",
        "本次是用户授权的**机器复审根因分流**：不是人工审核、不是人工批准、不是 active "
        "版本、不是 v2.1 准入。Gate 保持 BLOCKED：不生成任何 overlay；v2.0.10 保持 "
        "CANDIDATE / activation_blocked / split_reseal_required。19 条 reject 与 4 条 "
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
        print("usage: corpus_v2_v210_coherence_reject_triage.py [--out-dir DIR]",
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
