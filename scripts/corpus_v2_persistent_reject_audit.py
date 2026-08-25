"""v2 持续 reject case 的本地证据可修复性审计（确定性、离线、无 LLM）。

背景：第三轮机器审阅 reject 且 DeepSeek v4 Pro 盲态语义仲裁仍 reject 的
5 条 case（en-052 / en-055 / mixed-016 / mixed-026 / multi-014，合并后
102 条中仅剩的 5 条 reject）——本脚本逐答案点审计「本地证据能否修复」：
在相关 source 的全文 chunks 中机械搜索逐字候选 span，给出
repair_feasibility 与 proposed_action 建议。

判定规则（纯机械、确定性、无 LLM/API）：
- 搜索限定在 relevant_source_ids；范围外命中单独标 out_of_scope_only，
  不作为修复依据（规格要求 1）。
- 答案点归一化（NFKC + 空白折叠 + ASCII 小写）后在相关源 chunk 全文中
  收集互不重叠的最长逐字匹配段（_collect_spans，贪心锚点 + 双向扩展）；
  span 覆盖 >= COVERAGE_EXACT → exact；否则 >= MIN_SPAN_LEN → partial；
  否则 none（规格要求：候选 span 必须带 chunk_id/source_id/字符范围/
  最短必要原文，不得只列关键词）。
- proposed_action（规格要求 2：只有候选原文能直接支撑拟议后的完整答案点
  时才允许 add_exact_evidence / narrow_answer_point）：
  - exact + span 不在当前 evidence snippet → add_exact_evidence；
  - exact + 已在 snippet → manual（evidence_already_present）；
  - partial + 至少一个完整子句逐字出现 → narrow_answer_point（收窄到有
    逐字证据的子句）；
  - partial 无完整子句 / 语言不匹配 / 仅范围外有 → manual_semantic_
    adjudication_required（改写与收窄边界需人工语义裁决）；
  - none 且范围外也无 → remove_unsupported_answer_point。
- 已被 v4 Pro 判 supported 的答案点不属于修复范围 → manual
  （point_already_supported）。

fail-closed 输入校验：merged 行数 == selection-manifest mapping、
merged reject 集合 == 目标 5 条、目标 ∈ disputed（第三轮 reject 事实）、
pack 行数与目标覆盖、chunk_id 唯一、evidence chunk 存在、
supports index 覆盖全部答案点。

产物（persistent-reject-evidence-audit/）：persistent-reject-cases.jsonl /
candidate-evidence-spans.jsonl / repair-feasibility-summary.json /
persistent-reject-evidence-audit.md / manifest.json（输入输出 SHA 链）。
本审计是证据可修复性分析：不代表自动修复、人工审核或 v2.1 准入。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

# ── 常量 ────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "evaluation/datasets/v2/persistent-reject-evidence-audit"
DEFAULT_MERGED = ROOT / "evaluation/datasets/v2/llm-semantic-adjudication" \
    / "coherence-recheck/merged-adjudications.jsonl"
DEFAULT_SEL = ROOT / "evaluation/datasets/v2/llm-semantic-adjudication" \
    / "selection-manifest.json"
DEFAULT_PACK = ROOT / "evaluation/datasets/v2/human-review/human-review-pack.jsonl"
DEFAULT_CHUNKS = ROOT / "data/v2-corpus/chunks/chunks.jsonl"

# 持续 reject：第三轮 reject（∈ selection-manifest.disputed）且合并后
# v4 Pro 仲裁仍为 reject 的 5 条 case（merged 中唯一 5 条 reject）。
TARGET_CASE_IDS = ["en-052", "en-055", "mixed-016", "mixed-026", "multi-014"]
EXPECTED_PACK_ROWS = 150

# 机械判定阈值（写入 manifest 以便复算）
MIN_SPAN_LEN = 8          # 候选 span 的最小归一化长度（短语级，排除词级噪声）
COVERAGE_EXACT = 0.75     # span 覆盖答案点 >= 该比例 → exact
CJK_THRESHOLD = 0.3       # 答案点 CJK 占比阈值
CJK_SOURCE_THRESHOLD = 0.1  # 源文档 CJK 占比阈值（低于 → 视为非 CJK 文档）

OUTPUT_FILES = ("persistent-reject-cases.jsonl",
                "candidate-evidence-spans.jsonl",
                "repair-feasibility-summary.json",
                "persistent-reject-evidence-audit.md",
                "manifest.json")

# 第三轮理由位于 llm-filled pack / third-pass report，不在本任务允许读取的
# 4 个文件内——如实记录缺口，不猜测、不重建。
THIRD_PASS_REASON_NOTE = (
    "第三轮 reject 理由位于 human-review-pack.llm-filled.jsonl 与 "
    "llm-third-pass-report.md，不在本任务允许读取范围（仅 "
    "merged-adjudications.jsonl / selection-manifest.json / "
    "human-review-pack.jsonl / chunks.jsonl）；第三轮 decision=reject "
    "已由 selection-manifest.disputed 集合确认。")

# 子句切分：句子/逗号/冒号级标点（NFKC 后中文标点已转半角，两种都列）
_CLAUSE_SPLIT_RE = re.compile(r"[。．；;！？!?，,、：:…]")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

FEASIBILITIES = ("exact_local_evidence_available",
                 "only_paraphrase_or_partial_evidence",
                 "no_local_evidence_found")
ACTIONS = ("add_exact_evidence", "narrow_answer_point",
           "remove_unsupported_answer_point",
           "manual_semantic_adjudication_required")


class PersistentRejectAuditError(Exception):
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
            # 折叠为一个空格；首尾空白直接丢弃（段后无内容则不产出空格）
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


def _clauses(ap_norm: str) -> list[str]:
    """把归一化答案点按标点切分为子句，过滤过短片段（< MIN_SPAN_LEN）。"""
    return [c.strip() for c in _CLAUSE_SPLIT_RE.split(ap_norm)
            if len(c.strip()) >= MIN_SPAN_LEN]


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


# ── 纯函数：答案点分类 ───────────────────────────────────────────────

def classify_answer_point(answer_point: str, in_spans: list[dict],
                          out_spans: list[dict], language_mismatch: bool,
                          current_support: str,
                          evidence_snippets: list[str]) -> dict:
    """对一个答案点给出机械的修复可行性分类（纯函数，不修改输入）。

    in_spans/out_spans 为 span dict（含 ap_start/ap_end/text 等）。
    """
    ap_norm = _norm_with_map(answer_point)[0]
    n_ap = max(1, len(ap_norm))
    max_cover = max(((s["ap_end"] - s["ap_start"]) / n_ap
                     for s in in_spans), default=0.0)
    clauses = _clauses(ap_norm)
    clause_hit = any(ap_norm[s["ap_start"]:s["ap_end"]] in clauses
                     for s in in_spans)
    # 「已在当前 evidence」只对能支撑完整答案点的 exact span（覆盖达标）
    # 判断——小碎片（如 "e widget"）不代表该点已被证据覆盖
    exact_spans = [s for s in in_spans
                   if (s["ap_end"] - s["ap_start"]) / n_ap >= COVERAGE_EXACT]
    evidence_already_present = any(
        _norm_with_map(s["span_text"])[0] in ev
        for ev in evidence_snippets for s in exact_spans)
    point_already_supported = current_support != "unsupported"
    out_of_scope_only = bool(out_spans) and not in_spans

    if language_mismatch:
        feasibility = ("only_paraphrase_or_partial_evidence" if in_spans
                       else "no_local_evidence_found")
        action = "manual_semantic_adjudication_required"
        reason = ("language_mismatch: 答案点与相关源文档语言不同，逐字匹配"
                  "不适用，需人工语义判断")
    elif point_already_supported:
        feasibility = ("exact_local_evidence_available"
                       if max_cover >= COVERAGE_EXACT
                       else ("only_paraphrase_or_partial_evidence" if in_spans
                             else "no_local_evidence_found"))
        action = "manual_semantic_adjudication_required"
        reason = ("point_already_supported: 已被 v4 Pro 判定为 supported，"
                  "不属于本次修复范围")
    elif max_cover >= COVERAGE_EXACT:
        feasibility = "exact_local_evidence_available"
        if evidence_already_present:
            action = "manual_semantic_adjudication_required"
            reason = "evidence_already_present: 精确原文已在当前 evidence snippet 中"
        else:
            action = "add_exact_evidence"
            reason = f"候选原文直接支撑完整答案点（覆盖 {max_cover:.0%}）"
    elif in_spans:
        feasibility = "only_paraphrase_or_partial_evidence"
        if clause_hit:
            action = "narrow_answer_point"
            reason = "存在逐字完整的子句，可收窄答案点到有证据的子句"
        else:
            action = "manual_semantic_adjudication_required"
            reason = "仅部分/改写支撑且无完整子句，收窄边界需语义判断"
    else:
        feasibility = "no_local_evidence_found"
        if out_of_scope_only:
            action = "manual_semantic_adjudication_required"
            reason = "out_of_scope_only: 相似内容仅存在于范围外文档，不得作为修复依据"
        else:
            action = "remove_unsupported_answer_point"
            reason = "相关源全文内无任何逐字证据"

    return {
        "repair_feasibility": feasibility,
        "proposed_action": action,
        "action_reason": reason,
        "max_cover": round(max_cover, 4),
        "clause_hit": clause_hit,
        "evidence_already_present": evidence_already_present,
        "point_already_supported": point_already_supported,
        "language_mismatch": language_mismatch,
        "out_of_scope_only": out_of_scope_only,
        "matches": {"in_scope": len(in_spans), "out_of_scope": len(out_spans)},
    }


# ── 工具 ─────────────────────────────────────────────────────────────

def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).open(encoding="utf-8")]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    Path(path).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")


def _counts(values: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


# ── fail-closed 输入校验 ─────────────────────────────────────────────

def _validate_inputs(merged: list[dict], sel: dict, packs: list[dict],
                     chunks: list[dict], target: list[str],
                     expected_pack_rows: int) -> tuple[dict, dict, dict]:
    """校验全部输入契约；任何漂移 → PersistentRejectAuditError（零输出）。

    返回 (by_index, pack_by_id, chunk_by_id) 供组装复用。
    """
    mapping = sel.get("mapping", [])
    if len(mapping) != sel.get("total_cases"):
        raise PersistentRejectAuditError(
            "selection-manifest mapping 行数与 total_cases 不一致")
    if len(merged) != len(mapping):
        raise PersistentRejectAuditError(
            f"merged 行数 {len(merged)} != selection-manifest mapping {len(mapping)}")
    by_index = {e["index"]: e["case_id"] for e in mapping}
    if len(by_index) != len(mapping):
        raise PersistentRejectAuditError("selection-manifest mapping index 重复")
    idx_merged = {r["index"] for r in merged}
    if idx_merged != set(by_index):
        raise PersistentRejectAuditError(
            "merged index 集合与 selection-manifest mapping 不一致")
    if sorted(by_index) != list(range(1, len(mapping) + 1)):
        raise PersistentRejectAuditError("selection-manifest mapping index 不连续")

    target_set = set(target)
    reject_set = {by_index[r["index"]] for r in merged
                  if r.get("semantic_verdict") == "reject"}
    if reject_set != target_set:
        raise PersistentRejectAuditError(
            "merged reject 集合 " + json.dumps(sorted(reject_set),
                                               ensure_ascii=False)
            + " != 目标集合 " + json.dumps(sorted(target_set),
                                          ensure_ascii=False))
    disputed_set = set(sel.get("disputed", []))
    if not target_set <= disputed_set:
        raise PersistentRejectAuditError(
            "目标 case 必须全部在 selection-manifest.disputed（第三轮 reject）集合中")

    if len(packs) != expected_pack_rows:
        raise PersistentRejectAuditError(
            f"pack 行数 {len(packs)} != 期望 {expected_pack_rows}")
    pack_by_id = {p["case_id"]: p for p in packs}
    if not target_set <= set(pack_by_id):
        raise PersistentRejectAuditError("目标 case 缺失于 human-review-pack")

    chunk_ids = [c["chunk_id"] for c in chunks]
    if len(set(chunk_ids)) != len(chunk_ids):
        raise PersistentRejectAuditError("chunks.jsonl chunk_id 重复")
    chunk_by_id = {c["chunk_id"]: c for c in chunks}

    for t in target:
        p = pack_by_id[t]
        for ev in p.get("evidence", []):
            if ev.get("chunk_id") not in chunk_by_id:
                raise PersistentRejectAuditError(
                    f"{t} evidence chunk_id {ev.get('chunk_id')!r} 不存在于 chunks")
        row = next(r for r in merged if by_index[r["index"]] == t)
        points = p.get("acceptable_answer_points") or []
        sups = row.get("answer_point_supports") or []
        if sorted(s["answer_point_index"] for s in sups) != \
                list(range(len(points))):
            raise PersistentRejectAuditError(
                f"{t} answer_point_supports index 未覆盖全部 acceptable_answer_points")
    return by_index, pack_by_id, chunk_by_id


# ── 组装与输出 ───────────────────────────────────────────────────────

def _make_span(case_id: str, point_idx: int, answer_point: str,
               chunk: dict, chunk_norm: str, chunk_offs: list[int],
               ap_start: int, ap_end: int, ch_start: int, ch_end: int,
               in_scope: bool) -> dict:
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
        "in_scope": in_scope,
        "out_of_scope_only": not in_scope,
    }


def _build_case(row: dict, pack_row: dict, chunks_by_source: dict,
                out_chunks: list[dict], min_span_len: int,
                coverage_exact: float) -> tuple[dict, list[dict]]:
    """组装一个 target case 的审计行与全部候选 span 行。"""
    case_id = pack_row["case_id"]
    sources = list(pack_row.get("relevant_source_ids") or [])
    in_chunks: list[dict] = []
    for s in sources:
        in_chunks.extend(chunks_by_source.get(s, []))
    in_chunks.sort(key=lambda c: (c.get("index", 0), c["chunk_id"]))

    # 归一化缓存：chunk 文本 norm 只算一次，跨答案点共享
    cache: dict[str, tuple[str, list[int]]] = {}

    def norm_of(chunk: dict) -> tuple[str, list[int]]:
        cid = chunk["chunk_id"]
        if cid not in cache:
            cache[cid] = _norm_with_map(chunk["text"])
        return cache[cid]

    points = pack_row.get("acceptable_answer_points") or []
    sups = {s["answer_point_index"]: s
            for s in (row.get("answer_point_supports") or [])}
    evidence_norms = [_norm_with_map(ev.get("snippet", ""))[0]
                      for ev in pack_row.get("evidence", [])]
    lang_mismatch = _language_mismatch(
        " ".join(points), sources,
        [c for c in in_chunks] + out_chunks)

    answer_points: list[dict] = []
    all_spans: list[dict] = []
    for i, ap in enumerate(points):
        ap_norm, _ = _norm_with_map(ap)
        clauses = _clauses(ap_norm)
        in_spans: list[dict] = []
        out_spans: list[dict] = []
        for chunk in in_chunks:
            chunk_norm, chunk_offs = norm_of(chunk)
            for a, e1, b, e2 in _collect_spans(ap_norm, chunk_norm,
                                               min_span_len):
                in_spans.append((a, e1, _make_span(
                    case_id, i, ap, chunk, chunk_norm, chunk_offs,
                    a, e1, b, e2, True)))
        for chunk in out_chunks:
            chunk_norm, chunk_offs = norm_of(chunk)
            for a, e1, b, e2 in _collect_spans(ap_norm, chunk_norm,
                                               min_span_len):
                out_spans.append((a, e1, _make_span(
                    case_id, i, ap, chunk, chunk_norm, chunk_offs,
                    a, e1, b, e2, False)))
        in_spans.sort(key=lambda t: (t[2]["source_id"], t[2]["chunk_index"],
                                     t[2]["char_start"]))
        out_spans.sort(key=lambda t: (t[2]["source_id"], t[2]["chunk_index"],
                                      t[2]["char_start"]))

        support = sups.get(i, {})
        verdict = classify_answer_point(
            ap, [s for _, _, s in in_spans], [s for _, _, s in out_spans],
            _language_mismatch(ap, sources, in_chunks + out_chunks),
            support.get("support_level", ""), evidence_norms)

        # match_type：full（覆盖 >= COVERAGE_EXACT）/ clause（完整子句）/
        # partial（其余）
        n_ap = max(1, len(ap_norm))
        match_spans = in_spans + out_spans
        for a, e1, s in match_spans:
            s["match_type"] = ("full"
                               if (e1 - a) / n_ap >= coverage_exact
                               else ("clause" if ap_norm[a:e1] in clauses
                                     else "partial"))
            s["in_evidence"] = _norm_with_map(s["span_text"])[0] in \
                evidence_norms
        all_spans.extend(s for _, _, s in match_spans)

        answer_points.append({
            "answer_point_index": i,
            "answer_point": ap,
            "current_support": {
                "support_level": support.get("support_level", ""),
                "chunk_id": support.get("chunk_id", ""),
                "excerpt": support.get("excerpt", "")},
            **verdict,
        })

    case_row = {
        "case_id": case_id,
        "index": row["index"],
        "language": pack_row.get("language", ""),
        "query_type": pack_row.get("query_type", ""),
        "should_refuse": bool(pack_row.get("should_refuse", False)),
        "query": pack_row.get("query", ""),
        "relevant_source_ids": sources,
        "current_evidence": pack_row.get("evidence", []),
        "third_pass_reject_reason": None,
        "third_pass_reject_reason_note": THIRD_PASS_REASON_NOTE,
        "third_pass_reject_confirmed": True,
        "v4pro_verdict": row.get("semantic_verdict", ""),
        "v4pro_reject_rationale": row.get("verdict_rationale", ""),
        "answer_points": answer_points,
    }
    return case_row, all_spans


def _manifest_dict(merged_path: Path, sel_path: Path, pack_path: Path,
                   chunks_path: Path, target: list[str],
                   merged_rows: int, mapping_rows: int, pack_rows: int,
                   chunk_rows: int, summary: dict, outputs: dict,
                   constants: dict) -> dict:
    body = {
        "task": "persistent-reject-evidence-audit",
        "description": "v2 持续 reject case 的本地证据可修复性审计"
                       "（确定性、离线、无 LLM/API）",
        "llm": None,
        "target_case_ids": target,
        "constants": constants,
        "inputs": {
            "merged-adjudications.jsonl": {
                "path": str(merged_path), "rows": merged_rows,
                "sha256": _sha256_file(merged_path)},
            "selection-manifest.json": {
                "path": str(sel_path), "rows": mapping_rows,
                "sha256": _sha256_file(sel_path)},
            "human-review-pack.jsonl": {
                "path": str(pack_path), "rows": pack_rows,
                "sha256": _sha256_file(pack_path)},
            "chunks.jsonl": {
                "path": str(chunks_path), "rows": chunk_rows,
                "sha256": _sha256_file(chunks_path)},
        },
        "validation": {
            "merged_rows_ok": merged_rows == mapping_rows,
            "reject_set_matches_target": True,
            "target_in_disputed": True,
            "pack_rows_ok": True,
            "chunk_ids_unique": True,
        },
        "outputs": outputs,
        "created_by": "scripts/corpus_v2_persistent_reject_audit.py",
        "note": "证据可修复性审计，不代表自动修复、人工审核或 v2.1 准入",
    }
    return body


def run(*, merged_path: Path, sel_path: Path, pack_path: Path,
        chunks_path: Path, out_dir: Path, target_case_ids: list[str] | None
        = None, expected_pack_rows: int = EXPECTED_PACK_ROWS,
        min_span_len: int = MIN_SPAN_LEN,
        coverage_exact: float = COVERAGE_EXACT) -> dict:
    """执行持续 reject 证据可修复性审计，写入 5 个产物，返回 summary。"""
    target = list(target_case_ids if target_case_ids is not None
                  else TARGET_CASE_IDS)
    out_dir = Path(out_dir)
    merged_path = Path(merged_path)
    sel_path = Path(sel_path)
    pack_path = Path(pack_path)
    chunks_path = Path(chunks_path)

    merged = _load_jsonl(merged_path)
    sel = json.loads(sel_path.read_text(encoding="utf-8"))
    packs = _load_jsonl(pack_path)
    chunks = _load_jsonl(chunks_path)

    by_index, pack_by_id, chunk_by_id = _validate_inputs(
        merged, sel, packs, chunks, target, expected_pack_rows)

    # 范围外 chunks：相关源之外的全部文档（仅用于 out_of_scope_only 标记）
    in_sources = {s for t in target for s in
                  (pack_by_id[t].get("relevant_source_ids") or [])}
    chunks_by_source: dict[str, list[dict]] = {}
    for c in chunks:
        chunks_by_source.setdefault(c["source"], []).append(c)
    out_chunks = [c for c in chunks if c["source"] not in in_sources]

    case_rows: list[dict] = []
    all_spans: list[dict] = []
    for t in target:
        row = next(r for r in merged if by_index[r["index"]] == t)
        case_row, spans = _build_case(row, pack_by_id[t], chunks_by_source,
                                      out_chunks, min_span_len, coverage_exact)
        case_rows.append(case_row)
        all_spans.extend(spans)

    # 确定性排序：case 按目标顺序，span 按 (case, 答案点, 范围内优先,
    # source, chunk_index, char_start)
    case_order = {cid: i for i, cid in enumerate(target)}
    all_spans.sort(key=lambda s: (case_order[s["case_id"]],
                                  s["answer_point_index"],
                                  0 if s["in_scope"] else 1,
                                  s["source_id"], s["chunk_index"],
                                  s["char_start"]))

    # 汇总统计
    n_points = sum(len(c["answer_points"]) for c in case_rows)
    n_unsupported = sum(
        1 for c in case_rows for p in c["answer_points"]
        if p["current_support"]["support_level"] == "unsupported")
    feasibility_counts = _counts(
        [p["repair_feasibility"] for c in case_rows
         for p in c["answer_points"]])
    action_counts = _counts(
        [p["proposed_action"] for c in case_rows
         for p in c["answer_points"]])
    n_out_of_scope = sum(1 for s in all_spans if s["out_of_scope_only"])

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / "persistent-reject-cases.jsonl", case_rows)
    _write_jsonl(out_dir / "candidate-evidence-spans.jsonl", all_spans)

    summary_json = {
        "task": "persistent-reject-evidence-audit",
        "n_cases": len(case_rows),
        "case_ids": target,
        "n_answer_points": n_points,
        "n_unsupported_points": n_unsupported,
        "constants": {"min_span_len": min_span_len,
                      "coverage_exact": coverage_exact,
                      "cjk_threshold": CJK_THRESHOLD,
                      "cjk_source_threshold": CJK_SOURCE_THRESHOLD,
                      "expected_pack_rows": expected_pack_rows},
        "per_case": {
            c["case_id"]: {
                "n_points": len(c["answer_points"]),
                "n_unsupported": sum(
                    1 for p in c["answer_points"]
                    if p["current_support"]["support_level"] == "unsupported"),
                "points": [{"answer_point_index": p["answer_point_index"],
                            "repair_feasibility": p["repair_feasibility"],
                            "proposed_action": p["proposed_action"]}
                           for p in c["answer_points"]],
            } for c in case_rows},
        "feasibility_counts": feasibility_counts,
        "action_counts": action_counts,
        "spans": {"total": len(all_spans),
                  "in_scope": len(all_spans) - n_out_of_scope,
                  "out_of_scope_only": n_out_of_scope},
    }
    (out_dir / "repair-feasibility-summary.json").write_text(
        json.dumps(summary_json, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    md = _report_md(case_rows, all_spans, summary_json)
    (out_dir / "persistent-reject-evidence-audit.md").write_text(
        md, encoding="utf-8")

    # manifest：先算 4 个产物 sha，再算 manifest self-sha（移除自身条目）
    outputs = {}
    for name in OUTPUT_FILES:
        if name == "manifest.json":
            continue
        outputs[name] = {"rows": _count_rows(out_dir / name),
                         "sha256": _sha256_file(out_dir / name)}
    body = _manifest_dict(merged_path, sel_path, pack_path, chunks_path,
                          target, len(merged), len(sel["mapping"]),
                          len(packs), len(chunks), summary_json, outputs,
                          summary_json["constants"])
    self_sha = _sha256_bytes(json.dumps(
        body, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8"))
    outputs["manifest.json"] = {"rows": 1, "sha256": self_sha}
    body["outputs"] = outputs
    (out_dir / "manifest.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    summary = dict(summary_json)
    summary["outputs"] = {name: {"rows": info["rows"],
                                 "sha256": info["sha256"]}
                          for name, info in outputs.items()}
    return summary


def _count_rows(path: Path) -> int:
    return len(Path(path).read_text(encoding="utf-8").splitlines())


def _report_md(case_rows: list[dict], spans: list[dict],
               summary: dict) -> str:
    """人类可读报告：逐 case 答案点明细 + 汇总 + 限制声明。"""
    lines = [
        "# v2 持续 reject case 本地证据可修复性审计",
        "",
        "> 本审计为**证据可修复性分析**（确定性、离线、无 LLM/API）：逐答案点机械搜索"
        "相关 source 全文 chunks 中的逐字候选 span，评估 `repair_feasibility` 与 "
        "`proposed_action`。**不代表自动修复、人工审核或 v2.1 准入**。",
        "",
        f"- 目标 case：{', '.join(summary['case_ids'])}（合并后 102 条中唯一 5 条"
        "持续 reject：第三轮 reject 且 v4 Pro reject）",
        f"- 答案点：{summary['n_answer_points']} 个（其中 v4 Pro 判 unsupported "
        f"{summary['n_unsupported_points']} 个）",
        f"- 候选 span：{summary['spans']['total']} 条（范围内 "
        f"{summary['spans']['in_scope']} / 范围外 out_of_scope_only "
        f"{summary['spans']['out_of_scope_only']}）",
        f"- 阈值：MIN_SPAN_LEN={summary['constants']['min_span_len']}、"
        f"COVERAGE_EXACT={summary['constants']['coverage_exact']}",
        "",
        "## 判定规则（机械、确定性）",
        "",
        "- 搜索限定 `relevant_source_ids`；范围外命中标 `out_of_scope_only`，"
        "不作为修复依据",
        "- span 覆盖答案点 ≥ 75% → `exact_local_evidence_available`；"
        "≥ 8 字符 → `only_paraphrase_or_partial_evidence`；否则 "
        "`no_local_evidence_found`",
        "- `add_exact_evidence`：候选原文直接支撑完整答案点且不在当前 evidence；"
        "`narrow_answer_point`：至少一个完整子句逐字出现；"
        "`remove_unsupported_answer_point`：相关源内无任何逐字证据；其余改写/"
        "跨语言/仅范围外情形 → `manual_semantic_adjudication_required`",
        "- 已被 v4 Pro 判 supported 的答案点不属于修复范围",
        "",
        "## 逐 case 明细",
        "",
    ]
    for c in case_rows:
        lines.append(f"### {c['case_id']}（index {c['index']}，"
                     f"{c['language']} / {c['query_type']}）")
        lines.append("")
        lines.append(f"- query：{c['query']}")
        lines.append(f"- relevant_source_ids：{', '.join(c['relevant_source_ids'])}")
        lines.append(f"- v4 Pro reject 理由：{c['v4pro_reject_rationale']}")
        lines.append(f"- 第三轮 reject 理由：不可用（{c['third_pass_reject_reason_note']}）")
        lines.append("")
        for ev in c["current_evidence"]:
            lines.append(f"- 当前 evidence：`{ev['chunk_id']}` / "
                         f"`{ev['source_id']}` / section "
                         f"{ev.get('section', '')} / snippet "
                         f"「{ev.get('snippet', '')[:80]}…」")
        lines.append("")
        lines.append("| 答案点 | v4 Pro 支持 | 匹配 | repair_feasibility | proposed_action |")
        lines.append("|---|---|---|---|---|")
        for p in c["answer_points"]:
            sup = p["current_support"]["support_level"]
            m = p["matches"]
            flag = ""
            if p["language_mismatch"]:
                flag = "（语言不匹配）"
            elif p["evidence_already_present"]:
                flag = "（已在 evidence）"
            elif p["out_of_scope_only"]:
                flag = "（仅范围外）"
            lines.append(f"| {p['answer_point_index']} "
                         f"{p['answer_point'][:40]} | {sup} | "
                         f"{m['in_scope']} / {m['out_of_scope']} | "
                         f"{p['repair_feasibility']} | "
                         f"{p['proposed_action']}{flag} |")
        lines.append("")
        pt_spans = [s for s in spans if s["case_id"] == c["case_id"]]
        if pt_spans:
            lines.append("候选 span（chunk 内字符范围）：")
            lines.append("")
            lines.append("| 答案点 | chunk_id | source_id | 范围 | 最短必要原文 | 类型 |")
            lines.append("|---|---|---|---|---|---|")
            for s in pt_spans:
                scope = "范围外" if s["out_of_scope_only"] else "范围内"
                lines.append(f"| {s['answer_point_index']} | `{s['chunk_id']}` "
                             f"| `{s['source_id']}` | {s['char_start']}-"
                             f"{s['char_end']}（{scope}） | "
                             f"`{s['span_text'][:60]}` | {s['match_type']} |")
            lines.append("")
    lines.extend([
        "## 汇总",
        "",
        "| repair_feasibility | 计数 |",
        "|---|---|",
    ])
    for k, v in sorted(summary["feasibility_counts"].items()):
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("| proposed_action | 计数 |")
    lines.append("|---|---|")
    for k, v in sorted(summary["action_counts"].items()):
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.extend([
        "## 限制与结论",
        "",
        "- 第三轮 reject 理由位于 llm-filled pack / third-pass report，不在本任务"
        "允许读取范围，未输出（已如实记录）",
        "- 候选 span 是归一化逐字匹配；改写/翻译/语义等价关系超出机械审计能力，"
        "已路由到 `manual_semantic_adjudication_required`",
        "- `remove_unsupported_answer_point` / `narrow_answer_point` 是机械建议，"
        "采纳与否须由人工裁决",
        "- 本审计**不是自动修复、不是人工审核、不构成 v2.1 准入决策**；"
        "未修改任何 draft / human pack / chunks / 审阅产物 / 生产配置，"
        "未生成 overlay",
    ])
    return "\n".join(lines) + "\n"


# ── CLI ──────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out_dir = DEFAULT_OUT_DIR
    if "--out-dir" in argv:
        i = argv.index("--out-dir")
        out_dir = Path(argv[i + 1])
        del argv[i:i + 2]
    try:
        summary = run(merged_path=DEFAULT_MERGED, sel_path=DEFAULT_SEL,
                      pack_path=DEFAULT_PACK, chunks_path=DEFAULT_CHUNKS,
                      out_dir=out_dir)
    except PersistentRejectAuditError as exc:
        print(f"persistent-reject audit failed closed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
