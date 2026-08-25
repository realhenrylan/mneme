"""Corpus v2 LLM review apply — diagnostic-only import of the machine
filled review pack.

处理机器填写副本（``human-review-pack.llm-filled.jsonl``，reviewer 标识
为 ``LLM_ASSISTED_*``，例如 LLM_ASSISTED_THIRD_PASS）。**本脚本复用**
``corpus_v2_human_review_apply`` 的严格校验函数（manifest 输入 SHA
复算、确定性重建 SHA 链、证据映射），不复制校验代码；但绝不调用其
HUMAN_REVIEWED 分支，也绝不改写空白 pack 或第三方产物。三分支：

1. **150/150 confirmed** → 生成独立、确定性的**诊断用** overlay
   ``evaluation/datasets/v2/llm-reviewed-truth/llm-reviewed-truth-overlay.json``
   （status=``LLM_REVIEWED_DIAGNOSTIC_ONLY``、reviewer_type=``LLM``）；
2. **存在 reject / needs_followup** → 只输出问题清单
   ``llm-review-issues.jsonl`` + ``llm-review-issues-report.md``，
   **零 overlay**；
3. **任何非法状态**（行数/键集/篡改/证据/third-pass manifest 或 report
   统计漂移/空白 pack 被填写）→ **整体失败且零输出**。

机器填写副本的额外契约：

- reviewer 必须是非空 LLM 标识，且以 ``LLM_ASSISTED_`` 开头；
- reject / needs_followup 必须附 notes；
- third-pass manifest（total_cases / confirmed / reject /
  needs_followup / non_confirmed）与 report（头部统计 + 逐 case 清单
  统计）必须与填写副本复算一致；manifest 若声明含 ``{path, sha256}``
  的 inputs/outputs 条目则复算（当前 third-pass manifest 未声明 SHA
  字段，本工具自己的输出 manifest 会记录输入/输出 SHA-256 链）。

**诊断专用、绝不越权**：本 overlay 不得使用 ``HUMAN_REVIEWED`` /
``HUMAN_APPROVED`` / 上线批准等字样；它**不是人工终审，不能单独解除
v2.1 人工门槛**，不得自动进入 v2.1。

本任务**不调用任何 LLM/API**，不联网，不运行检索、生成评测、特征/
阈值扫描；禁止模型 ``gpt-5.6-sol``（本脚本不含任何模型调用路径）。

CLI
---
::

    python scripts/corpus_v2_llm_review_apply.py apply \
        [--out human-review 目录] [--overlay-out llm-reviewed-truth 目录]
    python scripts/corpus_v2_llm_review_apply.py verify \
        [--overlay-out llm-reviewed-truth 目录]
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
import scripts.corpus_v2_human_review_apply as hra  # noqa: E402
import scripts.corpus_v2_human_review_pack as hp  # noqa: E402

DEFAULT_OUT = hp.DEFAULT_OUT
DEFAULT_LLM_OUT = ROOT / "evaluation" / "datasets" / "v2" / "llm-reviewed-truth"

OVERLAY_VERSION = 1
STATUS_LLM_DIAGNOSTIC = "LLM_REVIEWED_DIAGNOSTIC_ONLY"
REVIEWER_TYPE = "LLM"
REVIEWER_PREFIX = "LLM_ASSISTED_"
# 输出中任何地方都不得出现的字样（诊断 overlay ≠ 人工审阅）
FORBIDDEN_PHRASES = ("HUMAN_REVIEWED", "HUMAN_APPROVED", "上线批准",
                     "已完成人工审核", "人工批准")

REPORT_STAT_RE = re.compile(
    r"^- (Total cases|Confirmed|Reject|Needs follow-up): (\d+)\s*$")
REPORT_CASE_RE = re.compile(
    r"^- ([A-Za-z0-9][A-Za-z0-9-]*): (confirmed|reject|needs_followup)"
    r"(?: .*)?$")


def _counts(filled: list[dict]) -> dict[str, int]:
    return {d: sum(1 for r in filled
                   if r["human_review_decision"] == d) for d in hra.DECISIONS}


def _parse_report(path: Path, errors: list[str]) -> dict[str, Any] | None:
    """解析 third-pass report 的头部统计与逐 case 清单统计。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"llm report 无法读取: {exc}")
        return None
    stats: dict[str, int] = {}
    case_counts: Counter[str] = Counter()
    case_lines = 0
    for ln in text.splitlines():
        mt = REPORT_STAT_RE.match(ln)
        if mt:
            stats[mt.group(1)] = int(mt.group(2))
            continue
        mc = REPORT_CASE_RE.match(ln)
        if mc:
            case_lines += 1
            case_counts[mc.group(2)] += 1
    return {"stats": stats, "case_counts": case_counts,
            "case_lines": case_lines}


def _llm_meta_errors(llm_manifest_path: Path, llm_report_path: Path,
                     filled: list[dict], errors: list[str]) -> None:
    """third-pass manifest 与 report 的统计必须与填写副本复算一致。"""
    try:
        m = json.loads(llm_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"llm manifest 无法读取: {exc}")
        return
    counts = _counts(filled)
    if m.get("total_cases") != len(filled):
        errors.append(f"llm manifest total_cases {m.get('total_cases')!r} "
                      f"!= 填写副本行数 {len(filled)}")
    for key in ("confirmed", "reject", "needs_followup"):
        if m.get(key) != counts[key]:
            errors.append(f"llm manifest {key} {m.get(key)} != 填写副本"
                          f"复算 {counts[key]}")
    nc = m.get("non_confirmed")
    actual = sorted(cid for cid, r in
                    ((x["case_id"], x) for x in filled)
                    if r["human_review_decision"] != "confirmed")
    if nc is not None and not isinstance(nc, list):
        errors.append("llm manifest non_confirmed 非列表")
    elif isinstance(nc, list):
        got = sorted(e.get("case_id") for e in nc if isinstance(e, dict))
        if got != actual:
            errors.append(f"llm manifest non_confirmed case 集合 {got} != "
                          f"填写副本 {actual}")
        dec = {r["case_id"]: r["human_review_decision"] for r in filled}
        for entry in nc:
            if isinstance(entry, dict) and entry.get("case_id") in dec and \
                    entry.get("decision") != dec[entry["case_id"]]:
                errors.append(f"llm manifest non_confirmed "
                              f"{entry.get('case_id')}: decision 与填写"
                              "副本不一致")
    # 输入/输出 SHA：manifest 声明 {path, sha256} 条目则复算（未声明
    # 的字段无从比较——本工具的产物 manifest 会记录自己的 SHA 链）
    for section in ("inputs", "outputs"):
        obj = m.get(section)
        if not isinstance(obj, dict):
            continue
        for key, info in obj.items():
            if not isinstance(info, dict) or "path" not in info or \
                    "sha256" not in info:
                continue
            p = Path(info["path"])
            if not p.exists():
                errors.append(f"llm manifest {section}.{key}: 文件不存在: "
                              f"{p}")
            elif info["sha256"] != hra._sha256_file(p):
                errors.append(f"llm manifest {section}.{key}: SHA-256 漂移")
    # report：头部统计 + 逐 case 清单统计
    rep = _parse_report(llm_report_path, errors)
    if rep is None:
        return
    stats = rep["stats"]
    if stats.get("Total cases") != len(filled):
        errors.append(f"llm report Total cases {stats.get('Total cases')} "
                      f"!= 填写副本行数 {len(filled)}")
    for label, key in (("Confirmed", "confirmed"), ("Reject", "reject"),
                       ("Needs follow-up", "needs_followup")):
        if stats.get(label) != counts[key]:
            errors.append(f"llm report {label} {stats.get(label)} != "
                          f"填写副本复算 {counts[key]}")
    if rep["case_lines"]:
        if rep["case_lines"] != len(filled):
            errors.append(f"llm report 逐 case 清单 {rep['case_lines']} 行 "
                          f"!= 填写副本 {len(filled)}")
        for key in ("confirmed", "reject", "needs_followup"):
            if rep["case_counts"].get(key, 0) != counts[key]:
                errors.append(f"llm report 逐 case 清单 {key} "
                              f"{rep['case_counts'].get(key, 0)} != 填写"
                              f"副本复算 {counts[key]}")


# ── 导入主流程 ────────────────────────────────────────────────────────

def apply(llm_filled_path: Path, pack_path: Path, pack_manifest_path: Path,
          llm_manifest_path: Path, llm_report_path: Path, out_dir: Path,
          overlay_dir: Path | None = None,
          chunks_path: Path | None = None) -> dict[str, Any]:
    """严格导入机器填写副本；返回状态 dict（fail-closed，失败零输出）。"""
    errors: list[str] = []
    overlay_dir = overlay_dir or DEFAULT_LLM_OUT

    # 1) pack manifest：五类输入 SHA 复算（输入不可变性）
    try:
        m = json.loads(pack_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "failed",
                "errors": [f"pack manifest 无法读取: {exc}"]}
    hra._manifest_input_errors(m, errors)

    # 2) 空白 pack 文件 SHA == pack_sha256（空白包不可变）
    try:
        blank_sha = hra._sha256_file(pack_path)
    except OSError as exc:
        errors.append(f"blank pack 无法读取: {exc}")
        blank_sha = ""
    if blank_sha and blank_sha != m["pack_sha256"]:
        errors.append("blank pack sha256 != manifest pack_sha256（空白包"
                      "被改写）")

    # 3) 确定性重建（SHA 链）：重建 SHA 必须等于 manifest pack_sha256
    orig_rows = hra._rebuild_original_pack(m, errors)

    # 4) 空白 pack 行：结构合法、三个人工字段全空、与确定性重建一致
    blank = hra._load_rows(pack_path, "blank pack", errors)
    hra._blank_errors(blank, orig_rows, errors, expected_total=m["n_cases"])

    # 5) 机器填写 pack：结构、逐行对齐（除三个人工字段外）、LLM 语义
    filled = hra._load_rows(llm_filled_path, "llm-filled pack", errors)
    hra._filled_errors(filled, blank, errors, expected_total=m["n_cases"])
    hra._llm_filled_extra_errors(filled, errors, REVIEWER_PREFIX)

    # 7) 证据引用仍能映射到 chunks 与 source（独立复验）
    hra._evidence_errors(filled, chunks_path, m, errors)

    # 8) third-pass manifest 与 report 统计一致性
    _llm_meta_errors(llm_manifest_path, llm_report_path, filled, errors)

    # fail-closed：任何非法状态 → 零输出
    if errors:
        return {"status": "failed", "errors": sorted(set(errors))}

    counts = _counts(filled)
    blocked = sorted(cid for cid, r in
                     ((x["case_id"], x) for x in filled)
                     if r["human_review_decision"] != "confirmed")

    if blocked:
        # 分支 2：只输出问题清单，绝不生成 overlay
        out_dir.mkdir(parents=True, exist_ok=True)
        issues = [{"case_id": r["case_id"], "decision": r["human_review_decision"],
                   "reviewer": r["human_reviewer"],
                   "notes": r["human_review_notes"]} for r in filled
                  if r["human_review_decision"] != "confirmed"]
        issues_text = "\n".join(hra._line(x) for x in sorted(
            issues, key=lambda x: x["case_id"])) + "\n"
        report_text = _issues_report_text(filled, blocked)
        if any(p in issues_text or p in report_text
               for p in FORBIDDEN_PHRASES):
            return {"status": "failed",
                    "errors": ["输出包含禁止字样（LLM 诊断路径）"]}
        (out_dir / "llm-review-issues.jsonl").write_text(
            issues_text, encoding="utf-8")
        (out_dir / "llm-review-issues-report.md").write_text(
            report_text, encoding="utf-8")
        return {"status": "issues", "errors": [], "counts": counts,
                "blocked": blocked,
                "outputs": ["llm-review-issues.jsonl",
                            "llm-review-issues-report.md"]}

    # 分支 3：150/150 confirmed → 独立、确定性诊断 overlay + manifest
    cases = [{
        "case_id": r["case_id"],
        "should_refuse": bool(r["should_refuse"]),
        "relevance_level": r["relevance_level"],
        "acceptable_answer_points": r["acceptable_answer_points"],
        "relevant_source_ids": r["relevant_source_ids"],
        "relevant_chunk_ids": [ev["chunk_id"] for ev in r["evidence"]],
        "reviewer": r["human_reviewer"],
    } for r in sorted(filled, key=lambda x: x["case_id"])]
    overlay = {
        "overlay_version": OVERLAY_VERSION,
        "status": STATUS_LLM_DIAGNOSTIC,
        "reviewer_type": REVIEWER_TYPE,
        "n_cases": len(cases),
        "note": "机器审阅诊断专用（LLM 填写副本）；非人工终审，不能单独"
                "解除 v2.1 人工门槛，不得自动进入 v2.1。",
        "cases": cases,
        "created_by": "corpus_v2_llm_review_apply.py",
    }
    overlay_text = json.dumps(overlay, ensure_ascii=False, indent=1) + "\n"
    if any(p in overlay_text for p in FORBIDDEN_PHRASES):
        return {"status": "failed",
                "errors": ["输出包含禁止字样（LLM 诊断路径）"]}
    overlay_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = overlay_dir / "llm-reviewed-truth-overlay.json"
    overlay_path.write_text(overlay_text, encoding="utf-8")
    reviewers = sorted({r["human_reviewer"] for r in filled})
    inputs = {
        "llm_filled_pack": {"path": str(llm_filled_path.resolve()),
                            "sha256": hra._sha256_file(llm_filled_path)},
        "blank_pack": {"path": str(pack_path.resolve()),
                       "sha256": blank_sha},
        "llm_third_pass_manifest": {
            "path": str(llm_manifest_path.resolve()),
            "sha256": hra._sha256_file(llm_manifest_path)},
        "llm_third_pass_report": {
            "path": str(llm_report_path.resolve()),
            "sha256": hra._sha256_file(llm_report_path)},
        "original_pack_sha256": m["pack_sha256"],
    }
    for key in ("draft", "chunks", "chunk_manifest", "corpus_manifest",
                "repair_ledger"):
        inputs[key] = {"path": m["inputs"][key]["path"],
                       "sha256": m["inputs"][key]["sha256"]}
    manifest = {
        "overlay_version": OVERLAY_VERSION,
        "status": STATUS_LLM_DIAGNOSTIC,
        "reviewer_type": REVIEWER_TYPE,
        "n_cases": len(cases),
        "decision_counts": counts,
        "reviewers": reviewers,
        "inputs": inputs,
        # 与人工路径一致：SHA 取已写入文件的字节（Windows 文本写入会
        # 把 \n 转成 \r\n，因此从文件复算保证链一致）
        "overlay_sha256": hra._sha256_file(overlay_path),
        "created_by": "corpus_v2_llm_review_apply.py",
    }
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=1) + "\n"
    if any(p in manifest_text for p in FORBIDDEN_PHRASES):
        return {"status": "failed",
                "errors": ["输出包含禁止字样（LLM 诊断路径）"]}
    (overlay_dir / "llm-reviewed-truth-overlay-manifest.json").write_text(
        manifest_text, encoding="utf-8")
    return {"status": "overlay", "errors": [], "counts": counts,
            "blocked": [],
            "outputs": ["llm-reviewed-truth-overlay.json",
                        "llm-reviewed-truth-overlay-manifest.json"]}


def _issues_report_text(rows: list[dict], blocked: list[str]) -> str:
    counts = _counts(rows)
    lines = [
        "# v2 机器审阅（LLM 第三轮）问题清单报告",
        "",
        "> 存在 reject / needs_followup：**未生成任何 overlay**。",
        "> 该结果不是人工终审，不能单独解除 v2.1 人工门槛；",
        "> 不得自动进入 v2.1，仍须等待真人逐条终审。",
        "",
        "## 计数（全量，不按划分分析）",
        "",
        f"- confirmed：{counts['confirmed']}",
        f"- reject：{counts['reject']}",
        f"- needs_followup：{counts['needs_followup']}",
        "",
        "## 阻断 case 清单",
        "",
        "| case_id | decision | reviewer | notes |",
        "|---|---|---|---|",
    ]
    for cid in blocked:
        r = next(x for x in rows if x["case_id"] == cid)
        notes = (r["human_review_notes"] or "").replace("|", "\\|")
        lines.append(f"| {cid} | {r['human_review_decision']} | "
                     f"{r['human_reviewer']} | {notes} |")
    lines += [
        "",
        "## 结论",
        "",
        "overlay 未生成；本报告仅为机器审阅诊断的问题清单；",
        "不是人工终审，不能单独解除 v2.1 人工门槛；不得自动进入 v2.1。",
    ]
    return "\n".join(lines) + "\n"


# ── overlay 链复检 ────────────────────────────────────────────────────

def verify(overlay_manifest_path: Path, *, overlay_path: Path | None = None,
           llm_filled_path: Path | None = None) -> list[str]:
    """对既有 LLM 诊断 overlay + manifest 复检（SHA 链、输入不可变性、
    结构、禁止字样）；返回错误列表（空 = 通过）。"""
    errors: list[str] = []
    try:
        m = json.loads(overlay_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"overlay manifest 无法读取: {exc}"]

    if m.get("status") != STATUS_LLM_DIAGNOSTIC:
        errors.append(f"status 必须为 {STATUS_LLM_DIAGNOSTIC}")
    if m.get("reviewer_type") != REVIEWER_TYPE:
        errors.append("reviewer_type 必须为 LLM")
    if m.get("overlay_version") != OVERLAY_VERSION:
        errors.append("overlay_version 非法")

    ov = overlay_path or overlay_manifest_path.parent / \
        "llm-reviewed-truth-overlay.json"
    if not ov.exists():
        errors.append(f"overlay 文件不存在: {ov}")
    elif m.get("overlay_sha256") != hra._sha256_file(ov):
        errors.append("overlay sha256 漂移（产物被改写）")

    # 输入不可变性：全部文件类 inputs 复算（original_pack_sha256 是
    # SHA 链引用值、无对应文件，跳过——它在 apply 阶段已与空白包比对）
    for key, info in m.get("inputs", {}).items():
        if not isinstance(info, dict) or "path" not in info or \
                "sha256" not in info:
            continue
        p = Path(info["path"])
        if not p.exists():
            errors.append(f"inputs.{key}: 文件不存在: {p}")
        elif info["sha256"] != hra._sha256_file(p):
            errors.append(f"inputs.{key}: SHA-256 漂移（输入被改写）")

    # 结构：n_cases、排序唯一、每 case 键集与枚举
    try:
        overlay = json.loads(ov.read_text(encoding="utf-8"))
        cases = overlay.get("cases", [])
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"overlay 无法解析: {exc}")
        cases = []
    if len(cases) != m.get("n_cases"):
        errors.append(f"overlay cases {len(cases)} != manifest "
                      f"{m.get('n_cases')}")
    cids = [c.get("case_id", "") for c in cases]
    if len(set(cids)) != len(cids):
        dup = sorted({i for i in cids if cids.count(i) > 1})
        errors.append(f"overlay 存在重复 case id: {dup}")
    if cids != sorted(cids):
        errors.append("overlay cases 未按 case_id 排序")
    for c in cases:
        extra = set(c) - hra.CASE_KEYS
        if extra:
            errors.append(f"{c.get('case_id')}: overlay 非法字段 "
                          f"{sorted(extra)}")
        if c.get("relevance_level") not in hra.RELEVANCE_LEVELS:
            errors.append(f"{c.get('case_id')}: relevance_level 非法")

    # decision_counts 与已填写 pack 复算一致
    pack = llm_filled_path or Path(m.get("inputs", {}).get(
        "llm_filled_pack", {}).get("path", ""))
    if pack.exists():
        rows = hra._load_rows(pack, "llm-filled pack", errors)
        counts = _counts(rows)
        if counts != m.get("decision_counts"):
            errors.append(f"decision_counts 与 llm-filled pack 复算不一致: "
                          f"{counts} vs {m.get('decision_counts')}")

    # 禁止字样：overlay 与 manifest 内容不得出现人工审阅/批准声明
    for label, p in (("overlay", ov), ("manifest", overlay_manifest_path)):
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for phrase in FORBIDDEN_PHRASES:
            if phrase in text:
                errors.append(f"{label} 包含禁止字样 {phrase!r}")
    return sorted(set(errors))


# ── CLI ───────────────────────────────────────────────────────────────

def _flag(args: list[str], name: str) -> str | None:
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: corpus_v2_llm_review_apply.py apply|verify "
              "[--out DIR] [--overlay-out DIR]")
        return 2
    cmd = args.pop(0)
    try:
        if cmd == "apply":
            out = Path(_flag(args, "--out") or DEFAULT_OUT)
            overlay_dir = Path(_flag(args, "--overlay-out") or
                               DEFAULT_LLM_OUT)
            res = apply(llm_filled_path=out /
                        "human-review-pack.llm-filled.jsonl",
                        pack_path=out / "human-review-pack.jsonl",
                        pack_manifest_path=out /
                        "human-review-pack-manifest.json",
                        llm_manifest_path=out /
                        "llm-third-pass-manifest.json",
                        llm_report_path=out / "llm-third-pass-report.md",
                        out_dir=out, overlay_dir=overlay_dir)
            if res["status"] == "failed":
                for e in res["errors"]:
                    print("FAILED:", e)
                print("apply failed: zero output (no overlay, no issues)")
                return 2
            counts = res["counts"]
            print(f"apply done: status={res['status']} "
                  f"confirmed={counts['confirmed']} "
                  f"reject={counts['reject']} "
                  f"needs_followup={counts['needs_followup']}")
            if res["status"] == "issues":
                print("blocked: " + ", ".join(res["blocked"]))
                print("no overlay generated (LLM diagnostic issues only; "
                      "not human review; v2.1 human gate stays)")
            else:
                print("overlay generated: llm-reviewed-truth-overlay.json "
                      "(LLM_REVIEWED_DIAGNOSTIC_ONLY, reviewer_type=LLM, "
                      "not human review, not entering v2.1 automatically)")
            return 0
        if cmd == "verify":
            overlay_dir = Path(_flag(args, "--overlay-out") or
                               DEFAULT_LLM_OUT)
            errs = verify(overlay_dir /
                          "llm-reviewed-truth-overlay-manifest.json")
            if errs:
                for e in errs:
                    print("VERIFY FAILED:", e)
                return 1
            print("verify ok: LLM diagnostic overlay + manifest chain "
                  "intact (LLM_REVIEWED_DIAGNOSTIC_ONLY)")
            return 0
    except ValueError as exc:
        print(f"FAILED: {exc}")
        return 2
    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
