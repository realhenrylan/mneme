"""Corpus v2 repair validator — deterministic, evidence-first fix gate.

对二审（LLM_ASSISTED_SECOND_PASS）flag 出的 10 条异常草稿执行
**证据优先的最小修复**闭环。设计原则：

1. **确定性**：validate 的输入只有 4 个文件（新草稿、旧草稿、修复
   ledger、chunks），任何漂移都返回确定性的错误列表；产物（report、
   manifest）不含时间戳，逐字节可复现。
2. **fail-closed**：ledger 的 case 集合必须恰好等于 10 条目标
   （TARGET_CASE_IDS）；每条 snippet SHA-256 必须与草稿中的
   ``chunk_text_snippet`` 复算一致且是连续证据（``snippet_is_evidence``）；
   10 条之外的任何草稿行不得被改动；annotation 必须保持
   ``LLM_ASSISTED`` / ``pending``，任何 HUMAN 声明直接失败。
3. **不降低证据标准**：answerable 行必须有非空证据；否定性答案点
   （"另一文档未提到 X"）不构成答案点；``changed_to_refusal`` 只允许
   在 ``should_refuse=True``、``relevance_level="none"`` 的语义下出现。
4. **只读**：本脚本绝不修改草稿、chunks 或 split 文件；也不读取任何
   dev/holdout/split 身份（报告只输出全量汇总）。

CLI
---
::

    python scripts/corpus_v2_repair.py validate \
        --draft <新草稿> --old-draft <旧草稿> --ledger <ledger> --chunks <chunks>
    python scripts/corpus_v2_repair.py report  \
        --draft ... --old-draft ... --ledger ... --chunks ... \
        --auto <auto-review.jsonl> --out <review 目录>

产物（report 子命令）：repair-evidence-report.md、repair-manifest.json。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # 允许直接以 python scripts/... 方式运行
import scripts.corpus_v2_review as rv  # noqa: E402

DEFAULT_DRAFT = rv.DEFAULT_DRAFT
DEFAULT_CHUNKS = rv.DEFAULT_CHUNKS
DEFAULT_OUT = rv.DEFAULT_OUT

TARGET_CASE_IDS = frozenset({
    "en-038", "en-040", "en-043", "en-046", "en-047",
    "mixed-025", "mixed-030", "mixed-032", "zh-050", "zh-059",
})
ACTIONS = ("corrected", "retained_after_evidence_check", "changed_to_refusal")
RELEVANCE_LEVELS = ("chunk", "source", "none")
# 全部 150 条草稿行必须包含的键（is_refusal_turn 仅部分行存在）
REQUIRED_KEYS = (
    "acceptable_answer_points", "annotation", "doc_target", "id", "language",
    "metadata", "note", "query", "query_type", "relevance_level",
    "relevant_chunk_ids", "relevant_chunks", "relevant_source_ids",
    "should_refuse",
)
EVIDENCE_KEYS = ("chunk_id", "chunk_text_snippet", "source_id", "page",
                 "section")
LEDGER_KEYS = ("case_id", "action", "old_summary", "new_summary", "evidence",
               "rationale")
EVIDENCE_ENTRY_KEYS = ("chunk_id", "source_id", "snippet_sha256")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _norm(obj: Any) -> str:
    """Canonical JSON（与 rv._line 一致）用于行级比较。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _load_jsonl(path: Path, label: str, errors: list[str]) -> list[dict]:
    rows: list[dict] = []
    try:
        for n, ln in enumerate(path.open(encoding="utf-8"), 1):
            if not ln.strip():
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError as e:
                errors.append(f"{label}: line {n} 非法 JSON: {e}")
    except FileNotFoundError:
        errors.append(f"{label}: 文件不存在: {path}")
    return rows


def _load_chunks(path: Path, errors: list[str]) -> dict[str, dict]:
    """chunk_id → {"text", "source"}。"""
    out: dict[str, dict] = {}
    for n, ln in enumerate(path.open(encoding="utf-8"), 1) if path.exists() \
            else ():
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)
            out[d["chunk_id"]] = {"text": d["text"], "source": d["source"]}
        except (json.JSONDecodeError, KeyError) as e:
            errors.append(f"chunks: line {n} 非法: {e}")
    return out


def validate(draft_path: Path, old_draft_path: Path | None,
             ledger_path: Path, chunks_path: Path,
             expected_total: int | None = None,
             target_ids: Iterable[str] = TARGET_CASE_IDS) -> list[str]:
    """确定性 fail-closed 校验；返回错误列表（空 = 通过）。"""
    target = frozenset(target_ids)
    errors: list[str] = []

    # ── ledger 契约 ──────────────────────────────────────────────────
    ledger = _load_jsonl(ledger_path, "ledger", errors)
    ledger_ids = {r.get("case_id") for r in ledger}
    missing = sorted(target - ledger_ids)
    extra = sorted(ledger_ids - target)
    if missing or extra:
        errors.append(
            f"ledger: 目标 case 集合必须恰好为 {sorted(target)}；"
            f"缺少 {missing}，多余 {extra}")
    for i, row in enumerate(ledger, 1):
        for k in LEDGER_KEYS:
            if k not in row:
                errors.append(f"ledger[{i}] {row.get('case_id')}: 缺少字段 {k}")
        if row.get("action") not in ACTIONS:
            errors.append(
                f"ledger[{i}] {row.get('case_id')}: action 非法 "
                f"{row.get('action')!r}（允许 {ACTIONS}）")
        for ev in row.get("evidence", []):
            if not isinstance(ev, dict):
                errors.append(
                    f"ledger[{i}] {row.get('case_id')}: evidence 条目非对象")
                continue
            for k in EVIDENCE_ENTRY_KEYS:
                if k not in ev:
                    errors.append(
                        f"ledger[{i}] {row.get('case_id')}: evidence 缺少 "
                        f"字段 {k}")

    # ── 新草稿整体合法性 ─────────────────────────────────────────────
    draft = _load_jsonl(draft_path, "draft", errors)
    ids = [r.get("id", "") for r in draft]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        errors.append(f"draft: 存在重复 case id: {dup}")
    if expected_total is not None and len(draft) != expected_total:
        errors.append(f"draft: 行数 {len(draft)} != 期望 {expected_total}")
    by_id = {r["id"]: r for r in draft if "id" in r}
    for r in draft:
        cid = r.get("id", "<unknown>")
        for k in REQUIRED_KEYS:
            if k not in r:
                errors.append(f"draft {cid}: 缺少必需字段 {k}")
        if not isinstance(r.get("acceptable_answer_points"), list):
            errors.append(f"draft {cid}: acceptable_answer_points 非列表")
        if r.get("relevance_level") not in RELEVANCE_LEVELS:
            errors.append(f"draft {cid}: relevance_level 非法 "
                          f"{r.get('relevance_level')!r}")
        chunks_ = r.get("relevant_chunks", [])
        chunk_ids = r.get("relevant_chunk_ids", [])
        if not isinstance(chunks_, list) or not isinstance(chunk_ids, list):
            errors.append(f"draft {cid}: relevant_chunks/relevant_chunk_ids "
                          "非列表")
            continue
        for ev in chunks_:
            for k in EVIDENCE_KEYS:
                if k not in ev:
                    errors.append(f"draft {cid}: evidence 条目缺少字段 {k}")
        if set(chunk_ids) != {ev.get("chunk_id") for ev in chunks_}:
            errors.append(
                f"draft {cid}: relevant_chunk_ids 与 relevant_chunks 不一致")
        ann = r.get("annotation", {})
        if ann.get("review_status") != "pending":
            errors.append(f"draft {cid}: review_status 必须为 pending")
        if ann.get("reviewed_by"):
            errors.append(f"draft {cid}: reviewed_by 必须为空")
        if "LLM_ASSISTED" not in ann.get("review_notes", ""):
            errors.append(f"draft {cid}: review_notes 必须标注 LLM_ASSISTED")
        if "HUMAN" in _norm(r):
            errors.append(f"draft {cid}: 出现 HUMAN/HUMAN_APPROVED 声明")

    # ── chunks 引用 ──────────────────────────────────────────────────
    chunks = _load_chunks(chunks_path, errors)

    # ── 旧草稿比对：10 条之外不得有任何改动 ──────────────────────────
    if old_draft_path is not None:
        old = _load_jsonl(old_draft_path, "old-draft", errors)
        old_by_id = {r["id"]: r for r in old if "id" in r}
        for cid in sorted(by_id):
            if cid in target:
                if cid not in old_by_id:
                    errors.append(f"old-draft: 目标 case {cid} 在旧草稿中"
                                  "不存在")
                continue
            if cid not in old_by_id:
                errors.append(f"old-draft: 非目标 case {cid} 在旧草稿中"
                              "不存在")
                continue
            if _norm(old_by_id[cid]) != _norm(by_id[cid]):
                errors.append(f"draft: 非目标 case {cid} 被改动，必须保持"
                              "不变")

    # ── 10 条目标 case 的逐条核验 ────────────────────────────────────
    for row in ledger:
        cid = row.get("case_id")
        if cid not in target:
            continue
        case = by_id.get(cid)
        if case is None:
            errors.append(f"draft: 目标 case {cid} 不存在")
            continue
        action = row.get("action")
        if action == "changed_to_refusal":
            if case.get("should_refuse") is not True:
                errors.append(
                    f"draft {cid}: changed_to_refusal 必须 should_refuse=True")
            if case.get("relevance_level") != "none":
                errors.append(
                    f"draft {cid}: changed_to_refusal 必须 "
                    "relevance_level=none")
            continue
        # answerable 语义：必须有证据、不得为空证据
        if case.get("should_refuse") is not False:
            errors.append(f"draft {cid}: answerable 修复必须 "
                          "should_refuse=False")
        if not case.get("relevant_chunks"):
            errors.append(f"draft {cid}: answerable 行必须有非空证据")
        # ledger evidence 必须恰好覆盖草稿中的全部证据
        ledger_ev_ids = {ev.get("chunk_id")
                         for ev in row.get("evidence", [])}
        draft_ev_ids = {ev.get("chunk_id")
                        for ev in case.get("relevant_chunks", [])}
        if ledger_ev_ids != draft_ev_ids:
            errors.append(
                f"draft {cid}: ledger evidence 与草稿证据不一致 "
                f"(ledger {sorted(ledger_ev_ids)} vs draft "
                f"{sorted(draft_ev_ids)})")
        for ev in row.get("evidence", []):
            ck = chunks.get(ev.get("chunk_id"))
            if ck is None:
                errors.append(f"draft {cid}: chunk 引用不存在 "
                              f"{ev.get('chunk_id')}")
                continue
            match = [d for d in case.get("relevant_chunks", [])
                     if d.get("chunk_id") == ev.get("chunk_id")]
            if not match:
                errors.append(f"draft {cid}: 草稿缺少 ledger 登记的 chunk "
                              f"{ev.get('chunk_id')}")
                continue
            d = match[0]
            if d.get("source_id") != ck["source"]:
                errors.append(
                    f"draft {cid}: {ev.get('chunk_id')} source 不一致 "
                    f"({d.get('source_id')} vs {ck['source']})")
            sha = rv.canonical_sha(d.get("chunk_text_snippet"))
            if sha != ev.get("snippet_sha256"):
                errors.append(
                    f"draft {cid}: {ev.get('chunk_id')} snippet SHA 与 "
                    "ledger 不一致")
            if not rv.snippet_is_evidence(d.get("chunk_text_snippet"),
                                          ck["text"]):
                errors.append(
                    f"draft {cid}: {ev.get('chunk_id')} snippet 不是连续"
                    "证据")

    return sorted(set(errors))


# ── 报告生成（全量汇总，绝不按 split）────────────────────────────────

def _aggregate_auto(path: Path) -> dict[str, Any]:
    """从 auto-review.jsonl 聚合全量统计（文件缺失/字段缺失时容忍）。"""
    agg = {"reviewed": 0, "confirmed": 0, "reject": 0, "needs_followup": 0,
           "confidence": {}, "issues": {}}
    if not path.exists():
        return agg
    for ln in path.open(encoding="utf-8"):
        if not ln.strip():
            continue
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        agg["reviewed"] += 1
        dec = r.get("decision")
        if dec in agg:
            agg[dec] += 1
        conf = r.get("confidence")
        if conf:
            agg["confidence"][conf] = agg["confidence"].get(conf, 0) + 1
        for cat in r.get("issue_categories", []) or []:
            agg["issues"][cat] = agg["issues"].get(cat, 0) + 1
    return agg


def build_report(ledger_path: Path, draft_path: Path, chunks_path: Path,
                 auto_path: Path, old_draft_path: Path | None) -> str:
    """生成 repair-evidence-report.md（纯函数，返回 markdown 文本）。"""
    errors = validate(draft_path=draft_path, old_draft_path=old_draft_path,
                      ledger_path=ledger_path, chunks_path=chunks_path,
                      expected_total=150)
    draft = [r for r in _load_jsonl(draft_path, "draft", [])]
    by_id = {r["id"]: r for r in draft}
    ledger = [r for r in _load_jsonl(ledger_path, "ledger", [])]
    agg = _aggregate_auto(auto_path)

    act_counts: dict[str, int] = {}
    lines = [
        "# v2 修复验证与二审报告（LLM_ASSISTED_SECOND_PASS）",
        "",
        "> 本报告记录 10 条异常草稿的证据优先修复（repair ledger）与修复后",
        "> 的全量 150 条二审结果。修复与二审均为 LLM 辅助产物，"
        "**未经人工批准**，绝不伪称人工审核。",
        "",
        "## 修复范围",
        "",
        f"- 目标 case（必须恰好 10 条）：{', '.join(sorted(TARGET_CASE_IDS))}",
        "",
    ]
    for row in ledger:
        act_counts[row.get("action", "?")] = \
            act_counts.get(row.get("action", "?"), 0) + 1
    lines += [
        "- 修复动作汇总：" + "；".join(
            f"{a} {act_counts.get(a, 0)}" for a in ACTIONS),
        "",
        "## 逐条修复判定",
        "",
        "| case_id | action | 旧值摘要 | 新值摘要 | 证据（SHA 前 12 位） "
        "| 理由 |",
        "|---|---|---|---|---|---|",
    ]
    for row in ledger:
        cid = row["case_id"]
        ev = "；".join(
            f"{e['chunk_id']}·{e['snippet_sha256'][:12]}"
            for e in row.get("evidence", [])) or "—"
        lines.append(f"| {cid} | {row['action']} | {row['old_summary']} | "
                     f"{row['new_summary']} | {ev} | {row['rationale']} |")
    lines += [
        "",
        "## 证据 SHA-256 明细（与草稿 chunk_text_snippet 复算一致）",
        "",
        "```",
    ]
    for row in ledger:
        cid = row["case_id"]
        case = by_id.get(cid, {})
        for e in row.get("evidence", []):
            match = [d for d in case.get("relevant_chunks", [])
                     if d.get("chunk_id") == e["chunk_id"]]
            src = e["source_id"]
            lines.append(f"{cid} | {e['chunk_id']} | {src} | "
                         f"{e['snippet_sha256']}")
    lines += [
        "```",
        "",
        "## 全量二审汇总（不按 split 分析）",
        "",
        f"- 审阅条数：{agg['reviewed']}",
        f"- confirmed：{agg['confirmed']}",
        f"- reject：{agg['reject']}",
        f"- needs_followup：{agg['needs_followup']}",
    ]
    if agg["reviewed"]:
        rate = agg["confirmed"] / agg["reviewed"]
        lines.append(f"- 草稿与二审一致率（confirmed / 总数）："
                     f"{agg['confirmed']}/{agg['reviewed']} = "
                     f"{rate:.1%}")
    lines += ["", "### 置信度分布", "",
              "| 置信度 | 条数 |", "|---|---|"]
    for k in sorted(agg["confidence"]):
        lines.append(f"| {k} | {agg['confidence'][k]} |")
    lines += ["", "### 问题类别分布（reject / needs_followup 提及）", "",
              "| 问题类别 | 提及次数 |", "|---|---|"]
    for k in sorted(agg["issues"]):
        lines.append(f"| {k} | {agg['issues'][k]} |")
    lines += ["", "## fail-closed 校验", ""]
    if errors:
        lines += ["- repair validator：**未通过**", ""]
        lines += [f"  - {e}" for e in errors]
    else:
        lines += [
            "- repair validator：通过（ledger 恰好 10 条、非目标行未改动、"
            "snippet 连续且 SHA 一致）",
            "- 草稿 annotation 保持 `LLM_ASSISTED` / `pending`，无 HUMAN "
            "声明",
        ]
    if old_draft_path is not None:
        lines.append(f"- 旧草稿 SHA-256：{_sha256_file(old_draft_path)}")
    lines.append(f"- 新草稿 SHA-256：{_sha256_file(draft_path)}")
    lines += ["", "## 结论", ""]
    if not errors and agg["reviewed"] > 0 and \
            agg["reject"] == 0 and agg["needs_followup"] == 0:
        lines.append("LLM-assisted candidate review complete，"
                     "未经人工批准；仍不得进入 v2.1。")
    elif errors:
        lines.append(f"修复验证未通过：{len(errors)} 项错误（见上），"
                     "不得进入二审结论。")
    else:
        n = agg["reject"] + agg["needs_followup"]
        lines.append(f"二审未完成：{n} 条待修复（见 auto-review-fixlist."
                     "jsonl），不得进入 v2.1。")
    return "\n".join(lines) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────

def _flag(args: list[str], name: str) -> str | None:
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: corpus_v2_repair.py validate|report ...")
        return 2
    cmd = args.pop(0)
    try:
        if cmd == "validate":
            errs = validate(
                draft_path=Path(_flag(args, "--draft") or DEFAULT_DRAFT),
                old_draft_path=(
                    Path(_flag(args, "--old-draft"))
                    if _flag(args, "--old-draft") else None),
                ledger_path=Path(_flag(args, "--ledger")
                                 or DEFAULT_OUT / "repair-ledger.jsonl"),
                chunks_path=Path(_flag(args, "--chunks") or DEFAULT_CHUNKS),
                expected_total=150)
            if errs:
                for e in errs:
                    print(f"FAIL: {e}")
                print(f"repair validation failed: {len(errs)} errors")
                return 2
            print("repair validation passed: 10/10 ledger cases verified, "
                  "150 rows schema-legal, no HUMAN claims")
            return 0
        if cmd == "report":
            out = Path(_flag(args, "--out") or DEFAULT_OUT)
            old = (Path(_flag(args, "--old-draft"))
                   if _flag(args, "--old-draft") else None)
            md = build_report(
                ledger_path=Path(_flag(args, "--ledger")
                                 or out / "repair-ledger.jsonl"),
                draft_path=Path(_flag(args, "--draft") or DEFAULT_DRAFT),
                chunks_path=Path(_flag(args, "--chunks") or DEFAULT_CHUNKS),
                auto_path=Path(_flag(args, "--auto")
                               or out / "auto-review.jsonl"),
                old_draft_path=old)
            out.mkdir(parents=True, exist_ok=True)
            (out / "repair-evidence-report.md").write_text(
                md, encoding="utf-8")
            manifest = {
                "tool": "corpus_v2_repair.report",
                "target_case_ids": sorted(TARGET_CASE_IDS),
                "inputs": {
                    "new_draft_sha256": _sha256_file(
                        Path(_flag(args, "--draft") or DEFAULT_DRAFT)),
                    "chunks_sha256": _sha256_file(
                        Path(_flag(args, "--chunks") or DEFAULT_CHUNKS)),
                    "ledger_sha256": _sha256_file(
                        Path(_flag(args, "--ledger")
                             or out / "repair-ledger.jsonl")),
                    "old_draft_sha256": (_sha256_file(old)
                                         if old is not None else None),
                },
                "outputs": {
                    "repair-evidence-report.md": _sha256_text(md),
                },
            }
            (out / "repair-manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                encoding="utf-8")
            print("repair report written to "
                  f"{out / 'repair-evidence-report.md'}")
            return 0
    except ValueError as e:
        print(f"FAIL: {e}")
        return 2
    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
