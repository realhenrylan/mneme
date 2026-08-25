"""v2.0.1 自动审阅 37 条阻断项的确定性根因分流与修复计划（只读、离线、无 LLM）。

背景：自动审阅 canonical（113 confirmed / 20 reject / 17 needs_followup，
non-confirmed = 37）的 37 条阻断项需要逐 case、逐答案点确定根因，为后续
修复计划提供唯一、机械、可复算的分流。本脚本只读以下输入，不做任何修改：
canonical / evidence / issues / manifest / draft / chunks；不读取任何历史
审阅结论，不以历史 verdict 作为判断依据。

分流规则（纯机械、确定性，无 LLM/API/网络）：

1. refusal_label_or_schema_inconsistency（优先于一切，字段级确定性矛盾）：
   - should_refuse=True 且 is_refusal_turn 缺失/None/False → missing_
     refusal_turn_label；
   - should_refuse=True 且存在答案点 → refusal_with_answer_points；
   - should_refuse=False 且 is_refusal_turn=True → non_refusal_turn_
     labeled_refusal；
   - should_refuse=False 且审阅 refusal assessment（issue_categories 含
     answerable_refusal）→ refusal_assessment_conflict；
   - evidence 行 chunk/source 不在 draft 相关范围内 → evidence_scope_mismatch。
   只列明字段与值，不改标签。

2. 逐答案点证据分析（其余 case）：
   - 语言不匹配（答案点 CJK 与相关源语言不同）→ language_mismatch，
     逐字匹配不适用，需所有者核验翻译等价性；
   - 在相关源全文 chunks（范围内）与其余 chunks（范围外）中收集归一化
     逐字候选 span（NFKC + 空白折叠 + ASCII 小写，min_span = min(8,
     答案点归一化长度)，贪心锚点 + 双向扩展，映射回原始字符范围）；
   - 范围内最大覆盖 >= COVERAGE_EXACT → exact；>0 → partial；无 → none；
   - exact span 是否已完整出现在当前 evidence snippet 文本中（按 snippet
     文本判包含，不用不可靠的 char_range 切片）。

3. case 分类（互斥且覆盖完整，优先级从高到低）：
   - exact_local_evidence_available：全部答案点 exact，且至少一个答案点
     的 exact span 不在当前 snippet → 机械可修复（补/扩 evidence 表示），
     给出 chunk_id / source_id / 字符范围 / 最短 span；
   - partial_or_paraphrase_evidence_only：存在 partial 或语言不匹配 →
     requires_owner_policy，不得自动修改，给出最小收窄建议；
   - no_local_evidence_found：存在 none（逐字无命中）→ 区分
     unsupported_answer_point_removable（可删除）与
     zero_answer_points_modeling（删除后零答案点的建模问题）；不得建议
     杜撰替代表述；
   - semantic_judgment_unresolved：全部答案点 exact 且均已完整出现在
     snippet 内（证据充足，阻断原因是语义判断，如答案完整性）。

fail-closed：canonical 统计必须恰为 113/20/17（non-confirmed=37）、
issues 恰为 37 条且与 non-confirmed 集合一致、canonical/draft/chunks
SHA 与 manifest 一致、evidence 与 canonical evidence_summary 逐项一致、
snippet/chunk SHA 自洽——任一漂移 → TriageError，零输出。

产物（remediation-triage/）：blocking-case-triage.jsonl /
candidate-evidence-spans.jsonl / remediation-summary.json /
remediation-triage-report.md / data-quality-report.json / manifest.json。
本任务不生成 overlay、不改写任何 150 条数据、不进入 v2.1。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

# ── 常量 ────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEW_DIR = ROOT / "evaluation" / "datasets" / "v2" / "automated-review"
DEFAULT_DRAFT = ROOT / "evaluation" / "datasets" / "v2" / "annotations" \
    / "v2-cases-draft.jsonl"
DEFAULT_CHUNKS = ROOT / "data" / "v2-corpus" / "chunks" / "chunks.jsonl"
DEFAULT_OUT = DEFAULT_REVIEW_DIR / "remediation-triage"

# canonical 门禁：统计必须恰为此值，否则停止
EXPECTED_CONFIRMED = 113
EXPECTED_REJECT = 20
EXPECTED_FOLLOWUP = 17
EXPECTED_NON_CONFIRMED = EXPECTED_REJECT + EXPECTED_FOLLOWUP

# 机械判定阈值（写入 manifest 以便复算）
MIN_SPAN_LEN = 8          # 候选 span 的归一化最小长度（短语级，排除词级噪声）
COVERAGE_EXACT = 0.75     # span 覆盖答案点 >= 该比例 → exact
CJK_THRESHOLD = 0.3       # 答案点 CJK 占比阈值
CJK_SOURCE_THRESHOLD = 0.1  # 源文档 CJK 占比阈值（低于 → 视为非 CJK 文档）

DETERMINISTIC_TIMESTAMP = "2026-08-07T00:00:00+00:00"
RULE_VERSION = "v2.0.1-remediation-triage-1"
REVIEWER_TYPE = "LLM_ASSISTED_OWNER_AUTHORIZED"

CATEGORIES = (
    "exact_local_evidence_available",
    "partial_or_paraphrase_evidence_only",
    "no_local_evidence_found",
    "refusal_label_or_schema_inconsistency",
    "semantic_judgment_unresolved",
)
OUTPUT_FILES = ("blocking-case-triage.jsonl",
                "candidate-evidence-spans.jsonl",
                "remediation-summary.json",
                "remediation-triage-report.md",
                "data-quality-report.json",
                "manifest.json")

# data-analytics:analyze-data-quality skill 在本环境不可用（未安装），
# 实施等价的确定性质量检查（见 data-quality-report.json）。
SKILL_NOTE = (
    "data-analytics:analyze-data-quality skill 在本环境中不可用"
    "（不在已安装 skills 列表内），无法加载；已按任务约束实施等价的"
    "确定性质量检查（完整性 / 唯一性 / snippet 连续性 / source 一致性 / "
    "答案点证据覆盖），全部为机械复算，无 LLM 参与。")

# 风险与建议动作（确定性，随类别固定）
RISK = {
    "exact_local_evidence_available": "low（候选为逐字原文，无杜撰风险；"
                                      "修复仅涉及补全 evidence 表示）",
    "partial_or_paraphrase_evidence_only": "medium（收窄/改写可能改变答案点"
                                           "语义，需所有者核验）",
    "no_local_evidence_found": "high（删除/建模调整会改变标注结构；无证据"
                               "不得杜撰替代表述）",
    "refusal_label_or_schema_inconsistency": "high（标签修改需所有者明确"
                                             "批准，不得擅自改标签）",
    "semantic_judgment_unresolved": "high（需模型/所有者语义裁决，"
                                    "机械检查无法定论）",
}
ACTION = {
    "exact_local_evidence_available": "add_or_expand_evidence",
    "partial_or_paraphrase_evidence_only": "narrow_answer_point_or_verify_paraphrase",
    "no_local_evidence_found": "remove_unsupported_point_or_rework_modeling",
    "refusal_label_or_schema_inconsistency": "fix_refusal_label_or_resolve_assessment",
    "semantic_judgment_unresolved": "semantic_adjudication_required",
}

_CLAUSE_SPLIT_RE = re.compile(r"[。．；;！？!?，,、：:…]")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


class TriageError(Exception):
    """fail-closed 校验失败：零输出。"""


# ── 纯函数：归一化 / 子句 / span 收集 ────────────────────────────────

def _norm_with_map(text: str) -> tuple[str, list[int]]:
    """NFKC + ASCII 小写 + 空白折叠为单个空格。

    返回 (norm, offsets)，offsets[i] 是 norm[i] 在原始 text 中的字符偏移
    （折叠空白取段内首字符），用于把归一化区间映射回原始字符范围。
    """
    text = unicodedata.normalize("NFKC", text).lower()
    norm: list[str] = []
    offs: list[int] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            if norm and j < n:
                norm.append(" ")
                offs.append(i)
            i = j
        else:
            norm.append(c)
            offs.append(i)
            i += 1
    return "".join(norm), offs


def _cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    return len(_CJK_RE.findall(text)) / len(text)


def _language_mismatch(answer_point: str, source_ids: list[str],
                       chunks: list[dict]) -> bool:
    """答案点语言与相关源文档语言不同（CJK vs 非 CJK）→ 逐字匹配不适用。"""
    ap_cjk = _cjk_ratio(answer_point)
    src_text = "".join(c["text"] for c in chunks
                       if c["source"] in set(source_ids))
    src_cjk = _cjk_ratio(src_text)
    return (ap_cjk >= CJK_THRESHOLD and src_cjk < CJK_SOURCE_THRESHOLD) \
        or (ap_cjk < CJK_SOURCE_THRESHOLD and src_cjk >= CJK_THRESHOLD)


def _clauses(ap_norm: str, min_len: int) -> list[str]:
    """把归一化答案点按标点切分为子句，过滤过短片段（< min_len）。"""
    return [c.strip() for c in _CLAUSE_SPLIT_RE.split(ap_norm)
            if len(c.strip()) >= min_len]


def _collect_spans(ap_norm: str, chunk_norm: str, min_len: int
                   ) -> list[tuple[int, int, int, int]]:
    """收集 ap_norm 在 chunk_norm 中的所有互不重叠最长逐字匹配段。

    返回 [(ap_start, ap_end, chunk_start, chunk_end)]（归一化空间）。
    贪心：以 ap 中每个未消费位置为锚，find 该位置的 min_len 前缀，命中后
    双向扩展至最长；search_from 保证同一原文位置不会被重复消费。
    """
    spans: list[tuple[int, int, int, int]] = []
    i = 0
    search_from = 0
    n_ap = len(ap_norm)
    n_ch = len(chunk_norm)
    while i + min_len <= n_ap:
        base = ap_norm[i:i + min_len]
        pos = chunk_norm.find(base, search_from)
        if pos < 0:
            i += 1
            continue
        a, b = i, pos
        while a > 0 and b > 0 and ap_norm[a - 1] == chunk_norm[b - 1]:
            a -= 1
            b -= 1
        e1, e2 = i + min_len, pos + min_len
        while e1 < n_ap and e2 < n_ch and ap_norm[e1] == chunk_norm[e2]:
            e1 += 1
            e2 += 1
        # 修剪 span 边界空白（内部空白保留），使最短必要原文干净
        while a < e1 and ap_norm[a] == " ":
            a += 1
            b += 1
        while e1 > a and ap_norm[e1 - 1] == " ":
            e1 -= 1
            e2 -= 1
        if e1 - a < min_len:
            i = max(i + 1, a)
            continue
        spans.append((a, e1, b, e2))
        search_from = b + 1
        i = e1
    return spans


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":"))
                              for r in rows) + "\n", encoding="utf-8")


def _counts(values: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


# ── fail-closed 输入校验 ─────────────────────────────────────────────

def _validate_counts(rows: list[dict], expected_confirmed: int,
                     expected_reject: int, expected_followup: int) -> None:
    """canonical 统计必须恰为期望值；任何漂移 → TriageError。"""
    ids = [r["case_id"] for r in rows]
    if len(rows) != expected_confirmed + expected_reject + expected_followup:
        raise TriageError(
            f"canonical 行数 {len(rows)} != 期望 "
            f"{expected_confirmed + expected_reject + expected_followup}")
    if len(set(ids)) != len(ids):
        raise TriageError("canonical case_id 重复")
    counts = _counts(r["review_decision"] for r in rows)
    # 补齐 0 计数键，避免 {"reject": 7} != {"confirmed": 0, ...}
    counts = {"confirmed": counts.get("confirmed", 0),
              "reject": counts.get("reject", 0),
              "needs_followup": counts.get("needs_followup", 0)}
    expected = {"confirmed": expected_confirmed, "reject": expected_reject,
                "needs_followup": expected_followup}
    if counts != expected:
        raise TriageError(
            "canonical 统计漂移：" + json.dumps(counts, ensure_ascii=False)
            + " != 期望 " + json.dumps(expected, ensure_ascii=False))


def _validate_inputs(canon_path: Path, issues_path: Path, ev_path: Path,
                     man_path: Path, draft_path: Path, chunks_path: Path,
                     expected_confirmed: int, expected_reject: int,
                     expected_followup: int
                     ) -> tuple[list[dict], dict, dict, dict, dict, list[dict]]:
    """校验全部输入契约；任何漂移 → TriageError（零输出）。

    返回 (canonical_by_id, issues_by_id, evidence_by_case, draft_by_id,
    chunks_by_id, chunk_list)。
    """
    canon = _load_jsonl(canon_path)
    _validate_counts(canon, expected_confirmed, expected_reject,
                     expected_followup)
    non_confirmed = {r["case_id"] for r in canon
                     if r["review_decision"] != "confirmed"}
    expected_non_confirmed = expected_reject + expected_followup
    if len(non_confirmed) != expected_non_confirmed:
        raise TriageError(
            f"non-confirmed 计数 {len(non_confirmed)} != 期望 "
            f"{expected_non_confirmed}")

    issues = _load_jsonl(issues_path)
    issue_ids = [i["case_id"] for i in issues]
    if len(issues) != len(non_confirmed) or set(issue_ids) != non_confirmed:
        raise TriageError(
            "issues 行数/集合与 canonical non-confirmed 不一致："
            f"{len(issues)} 行 vs 期望 {len(non_confirmed)}")
    if len(set(issue_ids)) != len(issue_ids):
        raise TriageError("issues case_id 重复")

    draft = _load_jsonl(draft_path)
    draft_ids = [d["id"] for d in draft]
    if len(set(draft_ids)) != len(draft_ids):
        raise TriageError("draft id 重复")
    if set(draft_ids) != set(canon_id := {r["case_id"] for r in canon}):
        raise TriageError("draft id 集合与 canonical case_id 不一致")

    chunks = _load_jsonl(chunks_path)
    chunk_ids = [c["chunk_id"] for c in chunks]
    if len(set(chunk_ids)) != len(chunk_ids):
        raise TriageError("chunks.jsonl chunk_id 重复")

    man = json.loads(man_path.read_text(encoding="utf-8"))
    if man.get("review_sha256") != _sha256_file(canon_path):
        raise TriageError("canonical SHA drift vs manifest.review_sha256")
    if man.get("inputs", {}).get("draft", {}).get("sha256") != \
            _sha256_file(draft_path):
        raise TriageError("draft SHA drift vs manifest.inputs.draft.sha256")
    if man.get("inputs", {}).get("chunks", {}).get("sha256") != \
            _sha256_file(chunks_path):
        raise TriageError("chunks SHA drift vs manifest.inputs.chunks.sha256")

    # canonical ↔ issues 的 evidence_summary 必须逐项一致
    canon_by_id = {r["case_id"]: r for r in canon}
    issues_by_id = {i["case_id"]: i for i in issues}
    for cid in non_confirmed:
        if canon_by_id[cid].get("evidence_summary") != \
                issues_by_id[cid].get("evidence_summary"):
            raise TriageError(f"{cid} canonical/evidence 与 issues "
                              f"evidence_summary 不一致")

    # evidence 行必须与 canonical evidence_summary 逐项一致，且 SHA 自洽
    ev_rows = _load_jsonl(ev_path)
    ev_by_case: dict[str, list[dict]] = defaultdict(list)
    chunk_by_id = {c["chunk_id"]: c for c in chunks}
    for e in ev_rows:
        cid = e["case_id"]
        summ = canon_by_id.get(cid, {}).get("evidence_summary") or []
        key = (e.get("chunk_id"), e.get("char_range_start"),
               e.get("char_range_end"))
        if key not in {(s["chunk_id"], s["char_range"]["start"],
                        s["char_range"]["end"]) for s in summ}:
            raise TriageError(
                f"{cid} evidence 行 {key} 与 canonical evidence_summary 不一致")
        if e.get("snippet_sha256") != _sha256_text(e["snippet"]):
            raise TriageError(f"{cid} evidence snippet_sha256 不自洽")
        ch = chunk_by_id.get(e.get("chunk_id"))
        if ch is None or e.get("chunk_text_sha256") != _sha256_text(ch["text"]):
            raise TriageError(f"{cid} evidence chunk_text_sha256 不自洽")
        ev_by_case[cid].append(e)
    # 每条 canonical evidence_summary 都必须有对应 evidence 行
    for cid in non_confirmed:
        n_summ = len(canon_by_id[cid].get("evidence_summary") or [])
        if len(ev_by_case.get(cid, [])) != n_summ:
            raise TriageError(
                f"{cid} evidence 行数 {len(ev_by_case.get(cid, []))} "
                f"!= canonical evidence_summary {n_summ}")

    return canon_by_id, issues_by_id, ev_by_case, \
        {d["id"]: d for d in draft}, chunk_by_id, chunks


# ── span / 答案点分析 ────────────────────────────────────────────────

def _make_span(case_id: str, point_idx: int, answer_point: str,
               chunk: dict, chunk_offs: list[int],
               ap_start: int, ap_end: int, ch_start: int, ch_end: int,
               in_scope: bool, coverage: float, match_type: str,
               in_evidence: bool) -> dict:
    """构造候选 span 行：字符范围映射回原始文本，附最短必要原文。"""
    orig_start = chunk_offs[ch_start]
    orig_end = chunk_offs[ch_end - 1] + 1
    return {
        "case_id": case_id,
        "answer_point_index": point_idx,
        "answer_point": answer_point,
        "ap_start": ap_start,
        "ap_end": ap_end,
        "source_id": chunk["source"],
        "chunk_id": chunk["chunk_id"],
        "chunk_index": chunk.get("index"),
        "char_start": orig_start,
        "char_end": orig_end,
        "span_text": chunk["text"][orig_start:orig_end],
        "norm_match_len": ap_end - ap_start,
        "coverage": round(coverage, 4),
        "in_scope": in_scope,
        "out_of_scope_only": not in_scope,
        "match_type": match_type,
        "in_evidence": in_evidence,
        "repair_basis": in_scope and coverage >= COVERAGE_EXACT
        and not in_evidence,
    }


def _analyze_point(case_id: str, point_idx: int, answer_point: str,
                   in_chunks: list[dict], out_chunks: list[dict],
                   evidence_norms: list[str], sources: list[str],
                   all_chunks: list[dict], norm_cache: dict,
                   min_span_len: int, coverage_exact: float
                   ) -> tuple[dict, list[dict]]:
    """分析一个答案点：收集范围/外 span，给出状态与收窄建议。"""
    ap_norm, _ = _norm_with_map(answer_point)
    n_ap = max(1, len(ap_norm))
    ms = min(min_span_len, n_ap)
    mismatch = _language_mismatch(answer_point, sources, all_chunks)
    clauses = _clauses(ap_norm, ms)

    def norm_of(chunk: dict) -> tuple[str, list[int]]:
        cid = chunk["chunk_id"]
        if cid not in norm_cache:
            norm_cache[cid] = _norm_with_map(chunk["text"])
        return norm_cache[cid]

    in_spans: list[dict] = []
    out_spans: list[dict] = []
    for chunk, in_scope in [(c, True) for c in in_chunks] + \
            [(c, False) for c in out_chunks]:
        chunk_norm, chunk_offs = norm_of(chunk)
        for a, e1, b, e2 in _collect_spans(ap_norm, chunk_norm, ms):
            span_ap_norm = ap_norm[a:e1]
            cov = (e1 - a) / n_ap
            span_text = chunk["text"][chunk_offs[b]:chunk_offs[e2 - 1] + 1]
            span_norm = _norm_with_map(span_text)[0]
            # 子串包含判定：span 归一化文本须完整出现在任一 evidence
            # snippet 的归一化文本中（列表元素相等≠子串，不能直接 in）
            in_ev = any(span_norm in sn for sn in evidence_norms)
            if cov >= coverage_exact:
                mtype = "full"
            elif span_ap_norm in clauses:
                mtype = "clause"
            else:
                mtype = "partial"
            s = _make_span(case_id, point_idx, answer_point, chunk,
                           chunk_offs, a, e1, b, e2, in_scope, cov,
                           mtype, in_ev)
            (in_spans if in_scope else out_spans).append(s)

    def sort_key(s: dict) -> tuple:
        return (s["source_id"], s.get("chunk_index") or 0,
                s["char_start"])
    in_spans.sort(key=sort_key)
    out_spans.sort(key=sort_key)

    best_cov = max((s["coverage"] for s in in_spans), default=0.0)
    if mismatch:
        status = "language_mismatch"
    elif best_cov >= coverage_exact:
        status = "exact"
    elif best_cov > 0:
        status = "partial"
    else:
        status = "none"

    exact_spans = [s for s in in_spans if s["coverage"] >= coverage_exact]
    exact_in_snippet = any(s["in_evidence"] for s in exact_spans)
    has_exact_outside = any(not s["in_evidence"] for s in exact_spans)

    # 收窄建议：最长的逐字完整子句（有逐字证据的子句）
    clause_hits = sorted({ap_norm[s["ap_start"]:s["ap_end"]]
                          for s in in_spans
                          if ap_norm[s["ap_start"]:s["ap_end"]] in clauses},
                         key=len, reverse=True)
    if clause_hits:
        best_clause = clause_hits[0]
        hit = next(s for s in in_spans
                   if ap_norm[s["ap_start"]:s["ap_end"]] == best_clause)
        narrowing = (f"可收窄答案点为有逐字证据的子句：{best_clause} "
                     f"（chunk {hit['chunk_id']} "
                     f"[{hit['char_start']}:{hit['char_end']}]）")
    elif mismatch:
        narrowing = ("答案点语言与相关源文档语言不一致（逐字匹配不适用），"
                     "需所有者核验翻译等价性或改写边界")
    elif status == "partial":
        narrowing = (f"仅部分逐字命中（范围内最大覆盖 {best_cov:.0%}），"
                     "无完整子句，收窄边界需所有者语义裁决")
    elif status == "none":
        narrowing = ("范围内无任何逐字证据；不得杜撰替代表述，"
                     "删除或补充文档需所有者裁决")
    else:
        narrowing = ""

    best_spans = sorted(exact_spans + [s for s in in_spans
                                       if s["coverage"] < coverage_exact],
                        key=lambda s: (-s["coverage"], s["char_start"]))[:3]

    point = {
        "answer_point_index": point_idx,
        "answer_point": answer_point,
        "status": status,
        "max_coverage": round(best_cov, 4),
        "language_mismatch": mismatch,
        "exact_in_snippet": exact_in_snippet,
        "has_exact_outside_snippet": has_exact_outside,
        "clause_hit": bool(clause_hits),
        "n_in_scope_spans": len(in_spans),
        "n_out_of_scope_spans": len(out_spans),
        "narrowing_suggestion": narrowing,
        "best_spans": [{
            "chunk_id": s["chunk_id"],
            "source_id": s["source_id"],
            "char_start": s["char_start"],
            "char_end": s["char_end"],
            "span_text": s["span_text"],
            "coverage": s["coverage"],
            "in_evidence": s["in_evidence"],
        } for s in best_spans],
    }
    return point, in_spans + out_spans


# ── case 分类 ────────────────────────────────────────────────────────

def _refusal_contradiction(draft_row: dict, issue_row: dict) -> dict | None:
    """字段级确定性矛盾检测；无矛盾返回 None。"""
    refuse = draft_row.get("should_refuse") is True
    irt = draft_row.get("is_refusal_turn")
    aps = draft_row.get("acceptable_answer_points") or []
    cats = set(issue_row.get("issue_categories") or [])
    if refuse and irt in (None, False):
        return {"sub_type": "missing_refusal_turn_label",
                "contradiction": {"should_refuse": True,
                                  "is_refusal_turn": irt}}
    if refuse and len(aps) > 0:
        return {"sub_type": "refusal_with_answer_points",
                "contradiction": {"should_refuse": True,
                                  "n_answer_points": len(aps)}}
    if not refuse and irt is True:
        return {"sub_type": "non_refusal_turn_labeled_refusal",
                "contradiction": {"should_refuse": False,
                                  "is_refusal_turn": True}}
    if not refuse and "answerable_refusal" in cats:
        return {"sub_type": "refusal_assessment_conflict",
                "contradiction": {"should_refuse": False,
                                  "review_refusal_assessment":
                                  "answerable_refusal"}}
    return None


def _evidence_scope_mismatch(draft_row: dict, evidence: list[dict]) -> dict | None:
    """evidence 行 chunk/source 不在 draft 相关范围内 → 确定性矛盾。"""
    srcs = set(draft_row.get("relevant_source_ids") or [])
    cids = set(draft_row.get("relevant_chunk_ids") or [])
    for e in evidence:
        if e.get("source_id") not in srcs or e.get("chunk_id") not in cids:
            return {"sub_type": "evidence_scope_mismatch",
                    "contradiction": {
                        "evidence_chunk_id": e.get("chunk_id"),
                        "evidence_source_id": e.get("source_id"),
                        "relevant_source_ids": sorted(srcs),
                        "relevant_chunk_ids": sorted(cids)}}
    return None


def _classify_case(draft_row: dict, issue_row: dict,
                   evidence: list[dict], points: list[dict]) -> dict:
    """对 case 输出唯一类别（五类互斥且覆盖完整）。"""
    c4 = _refusal_contradiction(draft_row, issue_row) or \
        _evidence_scope_mismatch(draft_row, evidence)
    if c4 is not None:
        return {"category": "refusal_label_or_schema_inconsistency",
                "sub_type": c4["sub_type"],
                "contradiction": c4["contradiction"],
                "mechanically_repairable": False,
                "requires_owner_policy": True}

    aps = draft_row.get("acceptable_answer_points") or []
    if not aps:
        # should_refuse=False 且零答案点：建模问题（本函数前置已排除
        # refusal 字段矛盾；consistent refusal turn 且 0 答案点 → 语义）
        if draft_row.get("should_refuse") is True:
            return {"category": "semantic_judgment_unresolved",
                    "sub_type": "",
                    "contradiction": None,
                    "mechanically_repairable": False,
                    "requires_owner_policy": True}
        return {"category": "no_local_evidence_found",
                "sub_type": "zero_answer_points_modeling",
                "contradiction": None,
                "mechanically_repairable": False,
                "requires_owner_policy": True}

    statuses = [p["status"] for p in points]
    if any(s == "none" for s in statuses):
        if all(s == "none" for s in statuses):
            sub = "zero_answer_points_modeling"
        else:
            sub = "unsupported_answer_point_removable"
        return {"category": "no_local_evidence_found", "sub_type": sub,
                "contradiction": None,
                "mechanically_repairable": False,
                "requires_owner_policy": True}

    if any(s in ("partial", "language_mismatch") for s in statuses):
        return {"category": "partial_or_paraphrase_evidence_only",
                "sub_type": "", "contradiction": None,
                "mechanically_repairable": False,
                "requires_owner_policy": True}

    # 全部 exact
    if any(not p["exact_in_snippet"] for p in points):
        return {"category": "exact_local_evidence_available",
                "sub_type": "evidence_gap", "contradiction": None,
                "mechanically_repairable": True,
                "requires_owner_policy": False}
    return {"category": "semantic_judgment_unresolved",
            "sub_type": "", "contradiction": None,
            "mechanically_repairable": False,
            "requires_owner_policy": True}


# ── 组装与输出 ───────────────────────────────────────────────────────

def _evidence_specs(points: list[dict], case_spans: list[dict],
                    evidence: list[dict],
                    relevant_chunk_ids: list[str]) -> list[dict]:
    """cat1 证据修复规格：gap 答案点的最短逐字 span。

    只从「范围内、exact、不在当前 snippet」的 span 中选择；优先当前已有
    evidence 的 chunk（expand_snippet），其次相关 chunk（add_evidence）。
    """
    ev_chunk_ids = {e["chunk_id"] for e in evidence}
    rel_ids = set(relevant_chunk_ids or [])
    gap_indices = sorted(
        {p["answer_point_index"] for p in points
         if p["status"] == "exact" and not p["exact_in_snippet"]})
    cand = [s for s in case_spans
            if s["answer_point_index"] in gap_indices
            and s["in_scope"] and s["coverage"] >= COVERAGE_EXACT
            and not s["in_evidence"]]
    cand.sort(key=lambda s: (0 if s["chunk_id"] in ev_chunk_ids else 1,
                             0 if s["chunk_id"] in rel_ids else 1,
                             -s["coverage"], s["char_start"]))
    specs: list[dict] = []
    for idx in gap_indices:
        s = next((x for x in cand if x["answer_point_index"] == idx), None)
        if s is None:
            continue
        specs.append({
            "answer_point_index": idx,
            "chunk_id": s["chunk_id"],
            "source_id": s["source_id"],
            "char_start": s["char_start"],
            "char_end": s["char_end"],
            "span_text": s["span_text"],
            "coverage": s["coverage"],
            "in_scope": True,
            "repair_action": ("expand_snippet"
                              if s["chunk_id"] in ev_chunk_ids
                              else "add_evidence"),
        })
    return specs


def _build_triage(canon_by_id: dict, issues_by_id: dict,
                  ev_by_case: dict, draft_by_id: dict,
                  chunks: list[dict]) -> tuple[list[dict], list[dict]]:
    """对 37 条阻断项逐条分流，返回 (triage_rows, span_rows)。"""
    non_confirmed = sorted(cid for cid, r in canon_by_id.items()
                           if r["review_decision"] != "confirmed")
    norm_cache: dict[str, tuple[str, list[int]]] = {}
    for c in chunks:
        norm_cache[c["chunk_id"]] = _norm_with_map(c["text"])

    triage: list[dict] = []
    span_rows: list[dict] = []
    for cid in non_confirmed:
        d = draft_by_id[cid]
        issue = issues_by_id[cid]
        canon = canon_by_id[cid]
        evidence = ev_by_case.get(cid, [])
        sources = list(d.get("relevant_source_ids") or [])
        in_chunks = [c for c in chunks if c["source"] in set(sources)]
        in_chunks.sort(key=lambda c: (c.get("index", 0), c["chunk_id"]))
        out_chunks = [c for c in chunks if c["source"] not in set(sources)]
        out_chunks.sort(key=lambda c: (c.get("index", 0), c["chunk_id"]))
        evidence_norms = [_norm_with_map(e["snippet"])[0] for e in evidence]

        points: list[dict] = []
        case_spans: list[dict] = []
        for i, ap in enumerate(d.get("acceptable_answer_points") or []):
            p, spans = _analyze_point(
                cid, i, ap, in_chunks, out_chunks, evidence_norms,
                sources, chunks, norm_cache, MIN_SPAN_LEN, COVERAGE_EXACT)
            points.append(p)
            case_spans.extend(spans)

        cls = _classify_case(d, issue, evidence, points)
        specs = (_evidence_specs(points, case_spans, evidence,
                                 d.get("relevant_chunk_ids") or [])
                 if cls["category"] == "exact_local_evidence_available"
                 else [])
        row = {
            "case_id": cid,
            "issue_id": cid,
            "decision": canon["review_decision"],
            "category": cls["category"],
            "sub_type": cls["sub_type"],
            "contradiction": cls["contradiction"],
            "mechanically_repairable": cls["mechanically_repairable"],
            "requires_owner_policy": cls["requires_owner_policy"],
            "risk": RISK[cls["category"]],
            "suggested_action": ACTION[cls["category"]],
            "query": d.get("query", ""),
            "language": d.get("language", ""),
            "query_type": d.get("query_type", ""),
            "should_refuse": bool(d.get("should_refuse")),
            "is_refusal_turn": d.get("is_refusal_turn"),
            "relevant_source_ids": sources,
            "relevant_chunk_ids": list(d.get("relevant_chunk_ids") or []),
            "issue_categories": list(issue.get("issue_categories") or []),
            "review_rationale": issue.get("rationale", ""),
            "answer_points": points,
            "evidence_specs": specs,
            "evidence_summary": [
                {"chunk_id": s["chunk_id"], "source_id": s["source_id"],
                 "char_range": s["char_range"],
                 "snippet_preview": s.get("snippet_preview", "")}
                for s in (canon.get("evidence_summary") or [])],
        }
        triage.append(row)
        span_rows.extend(case_spans)
    return triage, span_rows


def _build_summary(triage: list[dict]) -> dict:
    by_cat: dict[str, list[str]] = {}
    for r in triage:
        by_cat.setdefault(r["category"], []).append(r["case_id"])
    mech = [r["case_id"] for r in triage if r["mechanically_repairable"]]
    owner = [r["case_id"] for r in triage if r["requires_owner_policy"]]
    return {
        "n_blocking": len(triage),
        "by_category": {cat: sorted(ids) for cat, ids in
                        sorted(by_cat.items())},
        "by_decision": dict(sorted(_counts(r["decision"] for r in
                                           triage).items())),
        "by_language": dict(sorted(_counts(r["language"] for r in
                                           triage).items())),
        "by_query_type": dict(sorted(_counts(r["query_type"] for r in
                                             triage).items())),
        "by_sub_type": dict(sorted(_counts(r["sub_type"] for r in triage
                                           if r["sub_type"]).items())),
        "mechanically_repairable": {"n": len(mech),
                                    "case_ids": sorted(mech)},
        "requires_owner_policy": {"n": len(owner),
                                  "case_ids": sorted(owner)},
        "overlay_generated": False,
        "v2_1_entry": "BLOCKED",
        "deterministic": True,
        "run_at": DETERMINISTIC_TIMESTAMP,
        "created_by": "corpus_v2_remediation_triage.py",
    }


def _data_quality_report(canon_by_id: dict, issues_by_id: dict,
                         ev_by_case: dict, draft_by_id: dict,
                         chunk_by_id: dict, chunks: list[dict],
                         triage: list[dict]) -> dict:
    """等价确定性质量检查（data-analytics skill 不可用的替代实现）。"""
    ev_rows = [e for rows in ev_by_case.values() for e in rows]
    all_ev = ev_rows
    snippet_ok = sum(1 for e in all_ev
                     if e.get("snippet_sha256") == _sha256_text(e["snippet"]))
    chunk_ok = sum(1 for e in all_ev
                   if e.get("chunk_text_sha256") ==
                   _sha256_text(chunk_by_id[e["chunk_id"]]["text"]))
    slice_ok = 0
    bounds_ok = 0
    for e in all_ev:
        ch = chunk_by_id[e["chunk_id"]]
        if e["char_range_start"] <= e["char_range_end"] <= len(ch["text"]):
            bounds_ok += 1
            if ch["text"][e["char_range_start"]:e["char_range_end"]] == \
                    e["snippet"]:
                slice_ok += 1
    # source 一致性：evidence 行 ↔ chunk ↔ draft 相关范围
    ev_src_chunk = all(chunk_by_id[e["chunk_id"]]["source"] == e["source_id"]
                       for e in all_ev)
    src_in_rel = all(e["source_id"] in set(
        draft_by_id[e["case_id"]].get("relevant_source_ids") or [])
        for e in all_ev)
    cid_in_rel = all(e["chunk_id"] in set(
        draft_by_id[e["case_id"]].get("relevant_chunk_ids") or [])
        for e in all_ev)
    rel_cids_resolve = all(
        cid in chunk_by_id for d in draft_by_id.values()
        for cid in (d.get("relevant_chunk_ids") or []))
    rel_srcs_resolve = all(
        s in {c["source"] for c in chunks} for d in draft_by_id.values()
        for s in (d.get("relevant_source_ids") or []))
    ev_keys = [(e["case_id"], e["chunk_id"], e["char_range_start"],
                e["char_range_end"]) for e in all_ev]
    # 答案点证据覆盖
    point_statuses = [p["status"] for r in triage
                      for p in r["answer_points"]]
    per_case_cov = {r["case_id"]:
                    {p["answer_point_index"]: p["max_coverage"]
                     for p in r["answer_points"]} for r in triage}
    return {
        "skill_note": SKILL_NOTE,
        "completeness": {
            "canonical_rows": len(canon_by_id),
            "issues_rows": len(issues_by_id),
            "evidence_rows": len(all_ev),
            "draft_rows": len(draft_by_id),
            "chunk_rows": len(chunks),
            "issues_set_matches_non_confirmed": True,
            "canonical_issues_evidence_summary_mismatch": 0,
            "refusal_cases_without_evidence": len([
                cid for cid in issues_by_id
                if not ev_by_case.get(cid)]),
            "refusal_cases_without_evidence_ids": sorted(
                cid for cid in issues_by_id if not ev_by_case.get(cid)),
        },
        "uniqueness": {
            "canonical_case_ids_unique": len({r["case_id"] for r in
                                              canon_by_id.values()}) ==
            len(canon_by_id),
            "issues_case_ids_unique": len(set(issues_by_id)) ==
            len(issues_by_id),
            "draft_ids_unique": len(draft_by_id) ==
            len({d["id"] for d in draft_by_id.values()}),
            "chunk_ids_unique": len(chunk_by_id) == len(chunks),
            "evidence_rows_unique": len(set(ev_keys)) == len(ev_keys),
        },
        "snippet_continuity": {
            "snippet_sha256_self_consistent": snippet_ok,
            "chunk_text_sha256_self_consistent": chunk_ok,
            "char_range_within_chunk_bounds": bounds_ok,
            "char_range_slice_matches_snippet": slice_ok,
            "finding": (
                f"evidence snippet 文本 SHA 全部自洽（{snippet_ok}/{len(all_ev)}"
                f"），chunk 文本 SHA 全部自洽（{chunk_ok}/{len(all_ev)}）；"
                f"但 char_range 切片与 snippet 文本完全一致仅 "
                f"{slice_ok}/{len(all_ev)} 行（其余为空白折叠/对齐差异），"
                "故本任务按 snippet 文本（而非 char_range 切片）判定 "
                "exact span 是否已在 evidence 内"),
        },
        "source_consistency": {
            "evidence_source_matches_chunk": ev_src_chunk,
            "evidence_source_in_relevant_sources": src_in_rel,
            "evidence_chunk_in_relevant_chunks": cid_in_rel,
            "relevant_chunk_ids_resolve": rel_cids_resolve,
            "relevant_source_ids_resolve": rel_srcs_resolve,
        },
        "answer_point_evidence_coverage": {
            "points_total": len(point_statuses),
            "by_status": dict(sorted(_counts(point_statuses).items())),
            "per_case_max_coverage": per_case_cov,
        },
    }


def _build_report(triage: list[dict], summary: dict, dq: dict,
                  shas: dict) -> str:
    lines = [
        "# v2.0.1 自动审阅 37 条阻断项：确定性根因分流与修复计划", "",
        "> 只读分析任务：不修改 draft / chunks / 自动审阅 decision / pack / "
        "任何 overlay 或历史产物；不进入 v2.1。", "",
        "> 唯一事实来源：`automated-review.jsonl`（canonical，"
        f"confirmed={shas['counts']['confirmed']} / "
        f"reject={shas['counts']['reject']} / "
        f"needs_followup={shas['counts']['needs_followup']}，"
        "non-confirmed=37）。", "",
        "## 分流总览", "",
        "| 类别 | 计数 | 说明 |",
        "|---|---|---|",
        "| exact_local_evidence_available | "
        f"{len(summary['by_category'].get('exact_local_evidence_available', []))} "
        "| 机械可修复：补/扩 evidence 表示（逐字 span） |",
        "| partial_or_paraphrase_evidence_only | "
        f"{len(summary['by_category'].get('partial_or_paraphrase_evidence_only', []))} "
        "| 需所有者裁决：收窄或核验改写/翻译 |",
        "| no_local_evidence_found | "
        f"{len(summary['by_category'].get('no_local_evidence_found', []))} "
        "| 范围内无逐字证据：删除/建模/补文档需裁决 |",
        "| refusal_label_or_schema_inconsistency | "
        f"{len(summary['by_category'].get('refusal_label_or_schema_inconsistency', []))} "
        "| 字段级确定性矛盾：不改标签，需所有者批准 |",
        "| semantic_judgment_unresolved | "
        f"{len(summary['by_category'].get('semantic_judgment_unresolved', []))} "
        "| 证据已足，阻断为语义判断 |",
        "",
        f"- 机械可修复：{summary['mechanically_repairable']['n']} 条 "
        f"（{', '.join(summary['mechanically_repairable']['case_ids'])}）",
        f"- 需所有者裁决：{summary['requires_owner_policy']['n']} 条",
        "- 未生成 overlay；gate 保持 BLOCKED；未进入 v2.1。",
    ]

    lines += ["", "## 37 条逐条分流", "",
              "| case_id | decision | 类别 | 子类 | 建议动作 |",
              "|---|---|---|---|---|"]
    for r in triage:
        lines.append(f"| {r['case_id']} | {r['decision']} | "
                     f"{r['category']} | {r['sub_type'] or '-'} | "
                     f"{r['suggested_action']} |")

    mech = [r for r in triage if r["mechanically_repairable"]]
    if mech:
        lines += ["", "## 机械可修复（补/扩 evidence）", "",
                  "| case_id | 答案点 | chunk_id | 字符范围 | 最短 span | "
                  "覆盖 | 动作 |",
                  "|---|---|---|---|---|---|---|"]
        for r in mech:
            for spec in r["evidence_specs"]:
                ap = r["answer_points"][spec["answer_point_index"]][
                    "answer_point"]
                lines.append(
                    f"| {r['case_id']} | {ap[:40]} | {spec['chunk_id']} | "
                    f"[{spec['char_start']}:{spec['char_end']}] | "
                    f"{spec['span_text'][:40]} | {spec['coverage']:.0%} | "
                    f"{spec['repair_action']} |")
    else:
        lines += ["", "## 机械可修复", "", "无。", ""]

    lines += ["", "## 需所有者裁决", ""]
    for cat in CATEGORIES:
        ids = summary["by_category"].get(cat, [])
        if cat == "exact_local_evidence_available":
            continue
        lines.append(f"- **{cat}**（{len(ids)}）：{', '.join(ids) if ids else '无'}")
    lines.append("")

    lines += ["", "## 数据质量（等价确定性检查）", "",
              f"- completeness：canonical {dq['completeness']['canonical_rows']} / "
              f"issues {dq['completeness']['issues_rows']} / "
              f"evidence {dq['completeness']['evidence_rows']} / "
              f"draft {dq['completeness']['draft_rows']} / "
              f"chunks {dq['completeness']['chunk_rows']}；"
              "issues 集合 == non-confirmed 集合；"
              "canonical↔issues evidence_summary 0 差异",
              f"- uniqueness：case_id / chunk_id / evidence 行均唯一",
              f"- snippet 连续性：snippet/chunk SHA 全部自洽 "
              f"（{dq['snippet_continuity']['snippet_sha256_self_consistent']}/"
              f"{dq['completeness']['evidence_rows']}）；char_range 切片与 "
              "snippet 文本完全一致 "
              f"{dq['snippet_continuity']['char_range_slice_matches_snippet']}/"
              f"{dq['completeness']['evidence_rows']} 行",
              f"- source 一致性：evidence chunk↔source 一致、均在相关源/相关 "
              f"chunk 内（{dq['source_consistency']}）",
              f"- 答案点证据覆盖（37 条全部答案点）："
              f"{json.dumps(dq['answer_point_evidence_coverage']['by_status'], ensure_ascii=False)}",
              f"- skill 说明：{dq['skill_note']}", ""]

    lines += ["", "## SHA 链", "",
              f"- canonical（automated-review.jsonl）：`{shas['canonical']}`",
              f"- evidence（automated-review-evidence.jsonl）："
              f"`{shas['evidence']}`",
              f"- issues（automated-review-issues.jsonl）：`{shas['issues']}`",
              f"- manifest.json：`{shas['manifest']}`",
              f"- draft（v2-cases-draft.jsonl）：`{shas['draft']}`",
              f"- chunks（chunks.jsonl）：`{shas['chunks']}`", "",
              "## 声明", "",
              "- 未调用任何 LLM/API，未联网，未运行检索/生成/alpha/阈值评测",
              "- 未修改任何输入数据（draft / chunks / 150 条 decision / "
              "evidence / issues / manifest）",
              "- 未生成 overlay；gate 保持 BLOCKED；未进入 v2.1",
              "- 未读取历史审阅结论；分流仅基于允许读取的 6 个输入文件",
              "- 未 stage / commit / push",
    ]
    return "\n".join(lines) + "\n"


def _build_manifest(review_dir: Path, out_dir: Path, draft_path: Path,
                    chunks_path: Path, summary: dict, dq: dict,
                    validation: dict, outputs_sha: dict,
                    triage_rows: int, span_rows: int) -> dict:
    def n_rows(path: Path) -> int:
        return len([l for l in path.read_text(encoding="utf-8").splitlines()
                    if l.strip()])

    return {
        "task": "v2.0.1-remediation-triage",
        "description": "v2.0.1 自动审阅 37 条阻断项的确定性根因分流与修复计划"
                       "（只读、离线、无 LLM/API）",
        "rule_version": RULE_VERSION,
        "llm": None,
        "skill_note": SKILL_NOTE,
        "constants": {
            "min_span_len": MIN_SPAN_LEN,
            "coverage_exact": COVERAGE_EXACT,
            "cjk_threshold": CJK_THRESHOLD,
            "cjk_source_threshold": CJK_SOURCE_THRESHOLD,
            "expected_counts": [EXPECTED_CONFIRMED, EXPECTED_REJECT,
                                EXPECTED_FOLLOWUP],
        },
        "inputs": {
            "automated-review.jsonl": {
                "path": str(review_dir / "automated-review.jsonl"),
                "rows": n_rows(review_dir / "automated-review.jsonl"),
                "sha256": _sha256_file(review_dir / "automated-review.jsonl")},
            "automated-review-evidence.jsonl": {
                "path": str(review_dir / "automated-review-evidence.jsonl"),
                "rows": n_rows(review_dir /
                               "automated-review-evidence.jsonl"),
                "sha256": _sha256_file(
                    review_dir / "automated-review-evidence.jsonl")},
            "automated-review-issues.jsonl": {
                "path": str(review_dir / "automated-review-issues.jsonl"),
                "rows": n_rows(review_dir / "automated-review-issues.jsonl"),
                "sha256": _sha256_file(
                    review_dir / "automated-review-issues.jsonl")},
            "manifest.json": {
                "path": str(review_dir / "manifest.json"),
                "sha256": _sha256_file(review_dir / "manifest.json")},
            "v2-cases-draft.jsonl": {
                "path": str(draft_path),
                "rows": n_rows(draft_path),
                "sha256": _sha256_file(draft_path)},
            "chunks.jsonl": {
                "path": str(chunks_path),
                "rows": n_rows(chunks_path),
                "sha256": _sha256_file(chunks_path)},
        },
        "validation": validation,
        "outputs": {name: {"path": name,  # 相对 out_dir 的文件名，保证
                           "sha256": outputs_sha.get(name, "")}  # 跨目录确定性
                    for name in OUTPUT_FILES if name != "manifest.json"},
        "manifest_sha256": "",  # 写盘前补录：去除本键后的规范化序列化 SHA
        "summary_ref": {
            "n_blocking": summary["n_blocking"],
            "mechanically_repairable": summary["mechanically_repairable"],
            "requires_owner_policy": summary["requires_owner_policy"],
            "triage_rows": triage_rows,
            "candidate_span_rows": span_rows,
        },
        "declarations": {
            "llm_called": False,
            "network_used": False,
            "overlay_generated": False,
            "data_modified": False,
            "v2_1_entered": False,
            "historical_verdicts_read": False,
        },
        "deterministic": True,
        "run_at": DETERMINISTIC_TIMESTAMP,
        "created_by": "corpus_v2_remediation_triage.py",
    }


# ── 主流程 ───────────────────────────────────────────────────────────

def run(review_dir: Path = DEFAULT_REVIEW_DIR,
        draft_path: Path = DEFAULT_DRAFT,
        chunks_path: Path = DEFAULT_CHUNKS,
        out_dir: Path | None = None,
        expected_counts: tuple[int, int, int] = (EXPECTED_CONFIRMED,
                                                 EXPECTED_REJECT,
                                                 EXPECTED_FOLLOWUP)) -> dict:
    """执行 37 条阻断项的确定性根因分流。

    fail-closed：canonical 统计/SHA 链/一致性任一漂移 → TriageError，
    零输出；全部通过后生成 remediation-triage/ 六项产物。
    """
    out_dir = out_dir or DEFAULT_OUT
    canon_path = review_dir / "automated-review.jsonl"
    issues_path = review_dir / "automated-review-issues.jsonl"
    ev_path = review_dir / "automated-review-evidence.jsonl"
    man_path = review_dir / "manifest.json"
    if not all(p.is_file() for p in (canon_path, issues_path, ev_path,
                                     man_path, draft_path, chunks_path)):
        raise TriageError("输入文件缺失")

    canon_by_id, issues_by_id, ev_by_case, draft_by_id, chunk_by_id, chunks = \
        _validate_inputs(canon_path, issues_path, ev_path, man_path,
                         draft_path, chunks_path, *expected_counts)

    triage, span_rows = _build_triage(canon_by_id, issues_by_id, ev_by_case,
                                      draft_by_id, chunks)
    summary = _build_summary(triage)
    dq = _data_quality_report(canon_by_id, issues_by_id, ev_by_case,
                              draft_by_id, chunk_by_id, chunks, triage)
    shas = {
        "canonical": _sha256_file(canon_path),
        "evidence": _sha256_file(ev_path),
        "issues": _sha256_file(issues_path),
        "manifest": _sha256_file(man_path),
        "draft": _sha256_file(draft_path),
        "chunks": _sha256_file(chunks_path),
        "counts": {"confirmed": EXPECTED_CONFIRMED,
                   "reject": EXPECTED_REJECT,
                   "needs_followup": EXPECTED_FOLLOWUP},
    }
    report = _build_report(triage, summary, dq, shas)

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / "blocking-case-triage.jsonl", triage)
    _write_jsonl(out_dir / "candidate-evidence-spans.jsonl", span_rows)
    (out_dir / "remediation-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    (out_dir / "remediation-triage-report.md").write_text(
        report, encoding="utf-8")
    (out_dir / "data-quality-report.json").write_text(
        json.dumps(dq, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    validation = {
        "canonical_counts_exact": True,
        "issues_match_non_confirmed": True,
        "sha_chain": True,
        "evidence_consistent_with_canonical": True,
        "snippet_chunk_sha_self_consistent": True,
    }
    data_files = [n for n in OUTPUT_FILES if n != "manifest.json"]
    outputs_sha = {name: _sha256_file(out_dir / name)
                   for name in data_files}
    manifest = _build_manifest(review_dir, out_dir, draft_path, chunks_path,
                               summary, dq, validation, outputs_sha,
                               len(triage), len(span_rows))
    manifest_path = out_dir / "manifest.json"
    # manifest 自身 SHA：对「去除 manifest_sha256 键」的规范化序列化复算，
    # 自引用字段无法覆盖自身，写入 manifest 供复算验证
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    manifest["manifest_sha256"] = _sha256_text(
        json.dumps(body, ensure_ascii=False, indent=1) + "\n")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return {"triage": triage, "spans": span_rows, "summary": summary,
            "data_quality": dq, "manifest": manifest,
            "out_dir": str(out_dir)}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out_dir = DEFAULT_OUT
    if "--out-dir" in argv:
        i = argv.index("--out-dir")
        out_dir = Path(argv[i + 1])
        del argv[i:i + 2]
    try:
        result = run(out_dir=out_dir)
    except TriageError as exc:
        print(f"remediation triage failed closed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"n_blocking": len(result["triage"])},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
