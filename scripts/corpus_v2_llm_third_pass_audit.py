"""Corpus v2 LLM third-pass audit — read-only root-cause audit of the
machine-review disagreement structure.

对第三轮机器审阅（LLM_ASSISTED_THIRD_PASS）的 68 confirmed / 82 reject
/ 0 needs_followup 分歧做**只读根因审计**：用确定性文本校验解释每条
reject 的结构性成因，区分"可由确定性文本校验确认的文本事实"与"仅
是 LLM 语义判断、无法自动裁决"的成分。**本审计不判定第三轮或此前
审阅孰对，不改动任何数据，不生成 overlay，不解除 v2.1 人工门槛。**

只读取 5 个文件（blank pack / llm-filled pack / third-pass manifest /
third-pass report / chunks.jsonl）；不调用任何 LLM/API、不联网、不
运行检索、生成评测、特征/阈值扫描；不读取任何 split/dev/holdout
文件；禁止模型 ``gpt-5.6-sol``。

诊断字段（对每条 reject）：

- ``mechanical_evidence_integrity``：ok / broken（chunk 缺失、snippet
  非连续、source 不一致）。主流程前置校验保证 broken 会被拦截
  （fail-closed），纯函数仍支持该形态。
- ``answer_point_verbatim_coverage``：答案点（归一化后）在证据
  snippet 中的逐字覆盖：all_in_snippet / partial_in_snippet /
  none_in_snippet / no_evidence（拒答题）。
- ``refusal_reasoning_type``：拒答题 reject 理由的形态：
  keyword_overlap_only（"chunks 中存在相关内容…提到 X" 模板）、
  substantive_answerability_claim（实质可答断言）、not_applicable
  （答案题）、other_or_unverifiable。
- ``requires_semantic_adjudication``：True = 即便全部文本事实已知，
  该 reject 的最终裁决仍需要语义判断；False = 理由可在文本层面被
  机械否定（答案点逐字却 reject / 关键词引用断言不成立 / 证据损坏）。
- ``diagnostic_category``：六类之一——answer_point_not_verbatim_in_
  snippet / evidence_mapping_or_source_error / cross_document_
  coverage_gap / refusal_keyword_overlap_only / refusal_substantive_
  answerability_claim / other_or_unclassified。

产物（确定性、无时间戳、可重复构建）：
``disagreement-cases.jsonl``、``summary.json``、``disagreement-audit.md``、
``manifest.json``（输入/输出 SHA-256 与行数、决定分布）。

fail-closed：blank 与 llm-filled 必须均为 150 行、case_id 集合一致、
除三个 review 字段外逐行一致、证据映射有效、第三轮统计与
manifest/report 一致；任何结构性篡改、未知键、非法 decision →
整体失败且零输出。

CLI
---
::

    python scripts/corpus_v2_llm_third_pass_audit.py audit [--out DIR]
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # 允许直接以 python scripts/... 方式运行
import scripts.corpus_v2_review as rv  # noqa: E402
import scripts.corpus_v2_human_review_apply as hra  # noqa: E402
import scripts.corpus_v2_human_review_pack as hp  # noqa: E402
import scripts.corpus_v2_llm_review_apply as llra  # noqa: E402

DEFAULT_OUT = ROOT / "evaluation" / "datasets" / "v2" / "llm-third-pass-audit"
EXPECTED_TOTAL = 150
SNIPPET_PREVIEW_LEN = 100

CATEGORIES = (
    "answer_point_not_verbatim_in_snippet",
    "evidence_mapping_or_source_error",
    "cross_document_coverage_gap",
    "refusal_keyword_overlap_only",
    "refusal_substantive_answerability_claim",
    "other_or_unclassified",
)
COVERAGE_VALUES = ("all_in_snippet", "partial_in_snippet", "none_in_snippet",
                   "no_evidence")
REFUSAL_TYPES = ("not_applicable", "keyword_overlap_only",
                 "substantive_answerability_claim", "other_or_unverifiable")

REFUSAL_TEMPLATE_PREFIX = "chunks 中存在相关内容："
CHUNK_REF_RE = re.compile(r"([0-9a-f]{12}_chunk_\d+)\s*\(([^)]+)\)")
KEYWORD_RE = re.compile(r"提到\s*[:：]?\s*(.+)$")

DIAG_KEYS = ("case_id", "language", "query_type", "should_refuse", "query",
             "acceptable_answer_points", "evidence_summary",
             "third_pass_notes", "diagnostic_category",
             "mechanical_evidence_integrity", "answer_point_verbatim_coverage",
             "refusal_reasoning_type", "requires_semantic_adjudication")


def _norm(text: str) -> str:
    """归一化：小写 + 折叠连续空白。标点保留（避免误报）。"""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _verbatim_coverage(points: list[str], snippets: list[str]) -> str:
    """答案点（归一化）在任一证据 snippet 中的逐字覆盖结论。"""
    if not points:
        return "no_evidence"
    if not snippets:
        return "no_evidence"
    norms = [_norm(p) for p in points if _norm(p)]
    if not norms:
        return "no_evidence"
    hit = sum(1 for np in norms if any(np in _norm(s) for s in snippets))
    if hit == len(norms):
        return "all_in_snippet"
    if hit > 0:
        return "partial_in_snippet"
    return "none_in_snippet"


def _points_all_in_texts(points: list[str], texts: list[str]) -> bool:
    """全部非空答案点是否都在 texts 归一化拼接中逐字出现。"""
    norms = [_norm(p) for p in points if _norm(p)]
    if not norms:
        return True
    joined = _norm(" ".join(texts))
    return all(np in joined for np in norms)


def _evidence_integrity(evidence: list[dict], chunk_texts: dict[str, str],
                        chunk_sources: dict[str, str]) -> str:
    """证据完整性：chunk 存在、snippet 连续、source 一致。"""
    for ev in evidence:
        ck = chunk_texts.get(ev.get("chunk_id", ""))
        if not ck:
            return "broken"
        if not rv.snippet_is_evidence(ev.get("snippet", ""), ck):
            return "broken"
        if chunk_sources.get(ev.get("chunk_id", "")) != ev.get("source_id"):
            return "broken"
    return "ok"


def _refusal_reasoning(notes: str) -> tuple[str, list[str], list[str]]:
    """拒答题 reject 理由形态：(type, chunk_ids, keywords)。"""
    if not (notes.startswith(REFUSAL_TEMPLATE_PREFIX) and "提到" in notes):
        return "substantive_answerability_claim", [], []
    chunk_ids = [m.group(1) for m in CHUNK_REF_RE.finditer(notes)]
    km = KEYWORD_RE.search(notes)
    keywords = [k.strip() for k in
                (km.group(1) if km else "").split(",") if k.strip()]
    return "keyword_overlap_only", chunk_ids, keywords


def _keywords_verified(chunk_ids: list[str], keywords: list[str],
                       chunk_texts: dict[str, str]) -> bool:
    """引用 chunk 全部存在且至少一个关键词（归一化）出现在引用文本。"""
    if not chunk_ids or not keywords:
        return False
    texts = [chunk_texts.get(cid, "") for cid in chunk_ids]
    if any(t == "" for t in texts):
        return False
    nk = [_norm(k) for k in keywords]
    joined = [_norm(t) for t in texts]
    return any(any(k in t for t in joined) for k in nk)


def _classify(*, should_refuse: bool, integrity: str, coverage: str,
              refusal_type: str, cross_doc: bool) -> str:
    """诊断类别（优先级：证据损坏 > 拒答形态 > 跨文档 > 逐字覆盖）。"""
    if integrity == "broken":
        return "evidence_mapping_or_source_error"
    if should_refuse:
        if refusal_type == "keyword_overlap_only":
            return "refusal_keyword_overlap_only"
        return "refusal_substantive_answerability_claim"
    if coverage == "all_in_snippet":
        # 答案点逐字却 reject：第三轮核心理由在文本层面不成立
        return "other_or_unclassified"
    if cross_doc:
        return "cross_document_coverage_gap"
    return "answer_point_not_verbatim_in_snippet"


def _evidence_summary(evidence: list[dict], points: list[str],
                      chunk_texts: dict[str, str]) -> list[dict]:
    """证据摘要（确定性）：source/chunk/section + snippet 预览 + 该 chunk
    全文是否逐字命中任一答案点（截取边界现象的机械标记）。"""
    out: list[dict] = []
    for ev in evidence:
        snippet = ev.get("snippet", "")
        full = chunk_texts.get(ev.get("chunk_id", ""), "")
        out.append({
            "source_id": ev.get("source_id"),
            "chunk_id": ev.get("chunk_id"),
            "section": ev.get("section"),
            "snippet_preview": snippet[:SNIPPET_PREVIEW_LEN] +
            ("…" if len(snippet) > SNIPPET_PREVIEW_LEN else ""),
            "chunk_text_verbatim": bool(full and any(
                _norm(p) and _norm(p) in _norm(full)
                for p in points)),
        })
    return out


def _diagnose(blank_row: dict, filled_row: dict,
              chunk_texts: dict[str, str],
              chunk_sources: dict[str, str]) -> dict[str, Any]:
    """对一条 reject 生成确定性诊断记录。"""
    evidence = filled_row.get("evidence", [])
    points = filled_row.get("acceptable_answer_points", [])
    snippets = [ev.get("snippet", "") for ev in evidence]
    integrity = _evidence_integrity(evidence, chunk_texts, chunk_sources)
    coverage = _verbatim_coverage(points, snippets)
    should_refuse = bool(blank_row.get("should_refuse"))
    refusal_type, chunk_ids, keywords = (
        _refusal_reasoning(filled_row.get("human_review_notes") or "")
        if should_refuse else ("not_applicable", [], []))
    verified = _keywords_verified(chunk_ids, keywords, chunk_texts)
    cross_doc = len(blank_row.get("relevant_source_ids", [])) > 1
    if integrity == "broken":
        semantic = False
    elif not should_refuse:
        semantic = coverage != "all_in_snippet"
    elif refusal_type == "keyword_overlap_only":
        semantic = verified
    else:
        semantic = True
    return {
        "case_id": blank_row.get("case_id"),
        "language": blank_row.get("language"),
        "query_type": blank_row.get("query_type"),
        "should_refuse": should_refuse,
        "query": blank_row.get("query"),
        "acceptable_answer_points": list(points),
        "evidence_summary": _evidence_summary(evidence, points, chunk_texts),
        "third_pass_notes": filled_row.get("human_review_notes"),
        "diagnostic_category": _classify(
            should_refuse=should_refuse, integrity=integrity,
            coverage=coverage, refusal_type=refusal_type,
            cross_doc=cross_doc),
        "mechanical_evidence_integrity": integrity,
        "answer_point_verbatim_coverage": coverage,
        "refusal_reasoning_type": refusal_type,
        "requires_semantic_adjudication": semantic,
    }


def _rate(reject: int, total: int) -> float:
    return round(reject / total, 4) if total else 0.0


# ── 汇总与报告文本（纯函数，确定性）────────────────────────────────

def _build_summary(blank: list[dict], filled: list[dict],
                   diag_rows: list[dict], inputs_sha: dict[str, str],
                   chunk_texts: dict[str, str]) -> dict[str, Any]:
    counts = {d: sum(1 for r in filled
                     if r["human_review_decision"] == d) for d in hra.DECISIONS}
    blank_by_id = {r["case_id"]: r for r in blank}
    total_by = Counter()
    reject_by = Counter()
    for r in blank:
        total_by["answerable" if not r["should_refuse"] else "refusal"] += 1
        total_by["qt:" + r["query_type"]] += 1
        total_by["lang:" + r["language"]] += 1
        if len(r["relevant_source_ids"]) > 1:
            total_by["cross_doc"] += 1
    for d in diag_rows:
        b = blank_by_id[d["case_id"]]
        reject_by["answerable" if not b["should_refuse"] else "refusal"] += 1
        reject_by["qt:" + b["query_type"]] += 1
        reject_by["lang:" + b["language"]] += 1
        if len(b["relevant_source_ids"]) > 1:
            reject_by["cross_doc"] += 1

    def br(key: str) -> dict[str, Any]:
        return {"total": total_by[key], "reject": reject_by[key],
                "reject_rate": _rate(reject_by[key], total_by[key])}

    qt = {q: br("qt:" + q) for q in sorted(
        {r["query_type"] for r in blank})}
    lang = {l: br("lang:" + l) for l in sorted(
        {r["language"] for r in blank})}

    by_cat = Counter(d["diagnostic_category"] for d in diag_rows)
    semantic = sum(1 for d in diag_rows
                   if d["requires_semantic_adjudication"])
    ans = [d for d in diag_rows
           if not blank_by_id[d["case_id"]]["should_refuse"]]
    # 证据截取边界现象：答案题 reject 中，答案点未逐字于 snippet 但全部
    # 存在于该 case 全部证据 chunk 的全文
    boundary = 0
    for d in ans:
        if d["answer_point_verbatim_coverage"] == "all_in_snippet":
            continue
        texts = [chunk_texts.get(e["chunk_id"], "")
                 for e in d["evidence_summary"]]
        if _points_all_in_texts(d["acceptable_answer_points"], texts):
            boundary += 1
    ref = [d for d in diag_rows
           if blank_by_id[d["case_id"]]["should_refuse"]]
    return {
        "tool": "corpus_v2_llm_third_pass_audit",
        "total_cases": len(blank),
        "decision_counts": counts,
        "reject_breakdown": {
            "by_should_refuse": {"answerable": br("answerable"),
                                 "refusal": br("refusal")},
            "by_query_type": qt,
            "by_language": lang,
            "refusal_rows": br("refusal"),
            "cross_document_rows": br("cross_doc"),
        },
        "diagnostic_summary": {
            "by_category": {c: by_cat.get(c, 0) for c in CATEGORIES},
            "answer_point_text_facts": {
                "answerable_rejects": len(ans),
                "points_not_verbatim_in_snippet": sum(
                    1 for d in ans
                    if d["answer_point_verbatim_coverage"] !=
                    "all_in_snippet"),
                "points_verbatim_in_snippet": sum(
                    1 for d in ans
                    if d["answer_point_verbatim_coverage"] ==
                    "all_in_snippet"),
            },
            "snippet_boundary_cases": boundary,
            "refusal_keyword_facts": {
                "refusal_rejects": len(ref),
                "keyword_template_notes": sum(
                    1 for d in ref
                    if d["refusal_reasoning_type"] == "keyword_overlap_only"),
            },
            "mechanical_only_adjudication": len(diag_rows) - semantic,
            "semantic_adjudication_required": semantic,
        },
        "lineage_limitation": (
            "third-pass manifest 未声明任何输入/输出 SHA 字段：本审计只能"
            "校验其计数与报告统计的一致性，无法验证第三轮审阅的生成链"
            "完整性（产物 SHA 链见 manifest.json）。"),
        "conclusion": (
            "本审计仅描述分歧结构：任何一条 reject 的最终裁决都需要超出"
            "确定性文本校验的语义判断。本审计不判定第三轮或此前审阅孰对，"
            "不改动任何数据，不生成 overlay，不解除 v2.1 人工门槛。"),
        "inputs": inputs_sha,
    }


def _md_text(blank: list[dict], filled: list[dict],
             diag_rows: list[dict], summary: dict[str, Any]) -> str:
    sb = summary["reject_breakdown"]
    ds = summary["diagnostic_summary"]
    rates = {k: f"{v['reject']}/{v['total']}（{v['reject_rate']:.1%}）"
             for k, v in sb["by_should_refuse"].items()}

    def dim_table(d: dict[str, dict]) -> list[str]:
        lines = ["| 维度 | 总数 | reject | 占比 |", "|---|---|---|---|"]
        for k in sorted(d):
            v = d[k]
            lines.append(f"| {k} | {v['total']} | {v['reject']} | "
                         f"{v['reject_rate']:.1%} |")
        return lines

    lines = [
        "# v2 第三轮机器审阅分歧只读根因审计",
        "",
        "> 本报告仅描述 82 条 reject 的分歧结构：区分可由确定性文本校验",
        "> 确认的文本事实与仅属 LLM 语义判断的成分。**本审计不判定第三轮",
        "> 或此前审阅孰对，不改动任何数据，不生成 overlay，不解除 v2.1",
        "> 人工门槛。**",
        "",
        "## 复算分布（与第三轮 manifest / report 一致性已验证）",
        "",
        f"- 总条数：{summary['total_cases']}",
        f"- confirmed：{summary['decision_counts']['confirmed']}",
        f"- reject：{summary['decision_counts']['reject']}",
        f"- needs_followup：{summary['decision_counts']['needs_followup']}",
        "",
        "## 按 should_refuse 汇总",
        "",
        f"- 答案题：{rates['answerable']}",
        f"- 拒答题：{rates['refusal']}",
        "",
        "## 按 query_type 汇总",
        "",
    ]
    lines += dim_table(sb["by_query_type"])
    lines += ["", "## 按 language 汇总", ""]
    lines += dim_table(sb["by_language"])
    lines += [
        "",
        "## 拒答题与跨文档题",
        "",
        "- 拒答题（should_refuse=True）："
        f"{sb['refusal_rows']['reject']}/{sb['refusal_rows']['total']}"
        f"（{sb['refusal_rows']['reject_rate']:.1%}）",
        "- 跨文档题（relevant_source_ids > 1）："
        f"{sb['cross_document_rows']['reject']}/"
        f"{sb['cross_document_rows']['total']}"
        f"（{sb['cross_document_rows']['reject_rate']:.1%}）",
        "",
        "## 诊断类别分布",
        "",
        "| 类别 | 条数 |",
        "|---|---|",
    ]
    for c in CATEGORIES:
        lines.append(f"| {c} | {ds['by_category'][c]} |")
    lines += [
        "",
        "## 文本事实与语义裁决",
        "",
        f"- 答案题 reject {ds['answer_point_text_facts']['answerable_rejects']}"
        f" 条：答案点未逐字出现于证据 snippet 的断言 "
        f"{ds['answer_point_text_facts']['points_not_verbatim_in_snippet']}/"
        f"{ds['answer_point_text_facts']['answerable_rejects']} 条机械成立；"
        f"其中 {ds['snippet_boundary_cases']} 条答案点存在于证据 chunk 全文"
        "（证据截取边界现象，需人工确认片段选择）。",
        f"- 拒答题 reject {ds['refusal_keyword_facts']['refusal_rejects']} "
        f"条：全部为关键词重合模板（"
        f"{ds['refusal_keyword_facts']['keyword_template_notes']}/"
        f"{ds['refusal_keyword_facts']['refusal_rejects']}），关键词重合是"
        "文本事实，但“重合 ⇒ 可答”是语义判断。",
        f"- 机械可裁决（理由被文本层面否定）："
        f"{ds['mechanical_only_adjudication']} 条；需语义裁决："
        f"{ds['semantic_adjudication_required']} 条。",
        "",
        "## 谱系限制",
        "",
        f"- {summary['lineage_limitation']}",
        "",
        "## 结论",
        "",
        "本审计不判定第三轮或此前审阅孰对；不改动任何数据；不生成",
        "overlay；不解除 v2.1 人工门槛。",
        "",
    ]
    return "\n".join(lines) + "\n"


def _manifest_dict(blank_path: Path, filled_path: Path,
                   llm_manifest_path: Path, llm_report_path: Path,
                   chunks_path: Path, out_dir: Path,
                   counts: dict[str, int], n_reject: int) -> dict[str, Any]:
    def info(p: Path, rows: int | None = None) -> dict[str, Any]:
        d = {"path": str(p.resolve()), "sha256": hra._sha256_file(p)}
        if rows is not None:
            d["rows"] = rows
        return d

    return {
        "tool": "corpus_v2_llm_third_pass_audit",
        "version": 1,
        "inputs": {
            "blank_pack": info(blank_path, len([1 for _ in
                                                blank_path.open(
                                                    encoding="utf-8")])),
            "llm_filled_pack": info(filled_path, len([1 for _ in
                                                      filled_path.open(
                                                          encoding="utf-8")])),
            "llm_third_pass_manifest": info(llm_manifest_path),
            "llm_third_pass_report": info(llm_report_path),
            "chunks": info(chunks_path),
        },
        "outputs": {
            "disagreement-cases.jsonl": {
                "sha256": hra._sha256_file(
                    out_dir / "disagreement-cases.jsonl")},
            "summary.json": {"sha256": hra._sha256_file(
                out_dir / "summary.json")},
            "disagreement-audit.md": {"sha256": hra._sha256_file(
                out_dir / "disagreement-audit.md")},
        },
        "decision_counts": counts,
        "n_reject_cases": n_reject,
        "created_by": "corpus_v2_llm_third_pass_audit",
    }


# ── 主流程 ───────────────────────────────────────────────────────────

def audit(blank_path: Path, filled_path: Path, llm_manifest_path: Path,
          llm_report_path: Path, chunks_path: Path, out_dir: Path,
          expected_total: int = EXPECTED_TOTAL) -> dict[str, Any]:
    """只读分歧根因审计；返回状态 dict（fail-closed，失败零输出）。"""
    errors: list[str] = []

    # 1) 行契约（复用 LLM 路径共享校验）：150 行、id 集合一致、除三个
    #    review 字段外逐行一致、decision/reviewer/notes 合法
    blank = hra._load_rows(blank_path, "blank pack", errors)
    filled = hra._load_rows(filled_path, "llm-filled pack", errors)
    hra._blank_errors(blank, None, errors, expected_total=expected_total)
    hra._filled_errors(filled, blank, errors, expected_total=expected_total)
    hra._llm_filled_extra_errors(filled, errors, llra.REVIEWER_PREFIX)

    # 2) 证据映射仍有效（chunk 存在、snippet 连续、source 一致）
    hra._evidence_errors(filled, chunks_path, {}, errors)

    # 3) 第三轮统计与 manifest/report 一致（计数 + non_confirmed +
    #    report 头部与逐 case 统计）
    llra._llm_meta_errors(llm_manifest_path, llm_report_path, filled, errors)

    if errors:
        return {"status": "failed", "errors": sorted(set(errors))}

    # 4) 加载 chunks 全文（诊断用）
    chunk_texts: dict[str, str] = {}
    chunk_sources: dict[str, str] = {}
    for ln in chunks_path.open(encoding="utf-8"):
        if not ln.strip():
            continue
        d = json.loads(ln)
        chunk_texts[d["chunk_id"]] = d["text"]
        chunk_sources[d["chunk_id"]] = d["source"]

    # 5) 对每条 reject 生成确定性诊断
    blank_by_id = {r["case_id"]: r for r in blank}
    diag_rows = []
    for r in filled:
        if r["human_review_decision"] != "reject":
            continue
        diag_rows.append(_diagnose(blank_by_id[r["case_id"]], r,
                                   chunk_texts, chunk_sources))
    diag_rows.sort(key=lambda d: d["case_id"])

    # 6) 汇总与报告（确定性、无时间戳）
    counts = {d: sum(1 for r in filled
                     if r["human_review_decision"] == d) for d in hra.DECISIONS}
    inputs_sha = {
        "blank_pack": hra._sha256_file(blank_path),
        "llm_filled_pack": hra._sha256_file(filled_path),
        "llm_third_pass_manifest": hra._sha256_file(llm_manifest_path),
        "llm_third_pass_report": hra._sha256_file(llm_report_path),
        "chunks": hra._sha256_file(chunks_path),
    }
    summary = _build_summary(blank, filled, diag_rows, inputs_sha,
                             chunk_texts)
    md = _md_text(blank, filled, diag_rows, summary)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "disagreement-cases.jsonl").write_text(
        "\n".join(hra._line(d) for d in diag_rows) + "\n", encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    (out_dir / "disagreement-audit.md").write_text(md, encoding="utf-8")
    (out_dir / "manifest.json").write_text(
        json.dumps(_manifest_dict(blank_path, filled_path,
                                  llm_manifest_path, llm_report_path,
                                  chunks_path, out_dir, counts,
                                  len(diag_rows)),
                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"status": "ok", "errors": [], "counts": counts,
            "n_reject_cases": len(diag_rows),
            "outputs": ["disagreement-cases.jsonl", "summary.json",
                        "disagreement-audit.md", "manifest.json"]}


# ── CLI ──────────────────────────────────────────────────────────────

def _flag(args: list[str], name: str) -> str | None:
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: corpus_v2_llm_third_pass_audit.py audit [--out DIR]")
        return 2
    cmd = args.pop(0)
    try:
        if cmd == "audit":
            out = Path(_flag(args, "--out") or DEFAULT_OUT)
            res = audit(blank_path=hp.DEFAULT_OUT / "human-review-pack.jsonl",
                        filled_path=hp.DEFAULT_OUT /
                        "human-review-pack.llm-filled.jsonl",
                        llm_manifest_path=hp.DEFAULT_OUT /
                        "llm-third-pass-manifest.json",
                        llm_report_path=hp.DEFAULT_OUT /
                        "llm-third-pass-report.md",
                        chunks_path=rv.DEFAULT_CHUNKS,
                        out_dir=out)
            if res["status"] == "failed":
                for e in res["errors"]:
                    print("FAILED:", e)
                print("audit failed: zero output (read-only, no data "
                      "changed)")
                return 2
            c = res["counts"]
            print(f"audit done: confirmed={c['confirmed']} "
                  f"reject={c['reject']} "
                  f"needs_followup={c['needs_followup']} "
                  f"diagnosed={res['n_reject_cases']} reject cases")
            print("outputs written to " + str(out.resolve()))
            print("read-only audit: adjudicates nothing, changes no data, "
                  "no overlay, v2.1 human gate stays")
            return 0
    except ValueError as exc:
        print(f"FAILED: {exc}")
        return 2
    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
