"""Corpus v2 human-review apply — strict import of human review decisions.

导入人工终审结果：读取已填写的人工审阅 pack（`human_review_decision`
∈ confirmed/reject/needs_followup、`human_reviewer` 非空），按三种
分支产出：

1. **150/150 confirmed** → 生成独立、确定性的真值覆盖层
   `human-reviewed-truth-overlay.json`（status=``HUMAN_REVIEWED``）
   与 `human-reviewed-truth-overlay-manifest.json`；
2. **存在 reject / needs_followup** → 只输出问题清单
   `human-review-issues.jsonl` + `human-review-issues-report.md`，
   **绝不生成可用于评测的正式 overlay**；
3. **任何非法状态**（空/非法 decision、空 reviewer、重复/缺失/未知
   case、除三个人工字段外的任何字段被篡改、证据无法映射到 chunks/
   source、输入 SHA 漂移、原始 pack 重建不一致）→ **整体失败且零输出**
   （不写任何文件）。

设计原则：

- **只读、不改写**：本脚本绝不修改 v2 草稿、chunks、语料 manifest、
  case-freeze、split-lock 或生产配置；overlay 是独立产物，仅记录真值
  与审阅人，不替代草稿。
- **确定性**：产物无时间戳、按 case_id 排序；相同输入两次 apply 逐
  字节一致；原始 pack 由 manifest 记录的五类输入确定性重建，重建
  SHA-256 必须等于 pack manifest 的 ``pack_sha256``（SHA 链）。
- **输入不可变性**：pack manifest 记录的 draft / chunks /
  chunk_manifest / corpus_manifest / repair_ledger SHA-256 全部复算
  一致才允许继续；已填写 pack 每行去掉三个人工字段后必须与原始
  pack 对应行规范化 JSON 一致（任何篡改 → 失败）。
- **不伪称批准**：产物如实记录 ``HUMAN_REVIEWED``，但绝不自动宣称
  "上线批准"，也不自动进入 v2.1——启用与否需另行人工决策。

本任务**不调用任何 LLM/API**，不运行检索、生成评测、特征/阈值扫描；
禁止模型 ``gpt-5.6-sol``（本脚本不含任何模型调用路径）。

CLI
---
::

    python scripts/corpus_v2_human_review_apply.py apply   # 导入人工结果
    python scripts/corpus_v2_human_review_apply.py verify  # 复检 overlay 链

产物目录：evaluation/datasets/v2/human-review/
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # 允许直接以 python scripts/... 方式运行
import scripts.corpus_v2_review as rv  # noqa: E402
import scripts.corpus_v2_human_review_pack as hp  # noqa: E402

DEFAULT_OUT = hp.DEFAULT_OUT

OVERLAY_VERSION = 1
STATUS_HUMAN_REVIEWED = "HUMAN_REVIEWED"
DECISIONS = ("confirmed", "reject", "needs_followup")
HUMAN_FIELDS = ("human_review_decision", "human_reviewer",
                "human_review_notes")
RELEVANCE_LEVELS = ("chunk", "source", "none")
# overlay 每 case 的严格键集（真值 + 审阅人，不包含证据原文）
CASE_KEYS = frozenset({
    "case_id", "should_refuse", "relevance_level",
    "acceptable_answer_points", "relevant_source_ids",
    "relevant_chunk_ids", "reviewer",
})


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _canon(row: dict, exclude: Iterable[str]) -> str:
    """去掉排除键后的规范化 JSON（用于行级篡改比较）。"""
    return json.dumps({k: v for k, v in row.items() if k not in exclude},
                      ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _load_rows(path: Path, label: str, errors: list[str]) -> list[dict]:
    rows: list[dict] = []
    try:
        for n, ln in enumerate(path.open(encoding="utf-8"), 1):
            if not ln.strip():
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError as e:
                errors.append(f"{label}: 第 {n} 行非法 JSON: {e}")
    except OSError as exc:
        errors.append(f"{label}: 无法读取: {exc}")
    return rows


# ── 共享校验函数（human / LLM 两条导入路径复用）─────────────────────

def _manifest_input_errors(m: dict, errors: list[str]) -> None:
    """pack manifest 五类输入 SHA 复算（输入不可变性）；追加错误列表。"""
    for key in ("draft", "chunks", "chunk_manifest", "corpus_manifest",
                "repair_ledger"):
        info = m["inputs"][key]
        p = Path(info["path"])
        if not p.exists():
            errors.append(f"{key}: 文件不存在: {p}")
        elif info["sha256"] != _sha256_file(p):
            errors.append(f"{key}: SHA-256 漂移（输入被改写）")


def _rebuild_original_pack(m: dict, errors: list[str]) -> list[dict]:
    """确定性重建原始 pack：重建 SHA 必须等于 manifest pack_sha256；
    返回重建后的行（SHA 链）。"""
    orig_rows: list[dict] = []
    if errors:
        return orig_rows
    try:
        with tempfile.TemporaryDirectory() as td:
            orig = hp.build_pack(
                draft_path=Path(m["inputs"]["draft"]["path"]),
                chunks_path=Path(m["inputs"]["chunks"]["path"]),
                chunk_manifest_path=Path(m["inputs"]["chunk_manifest"]["path"]),
                corpus_manifest_path=Path(m["inputs"]["corpus_manifest"]["path"]),
                ledger_path=Path(m["inputs"]["repair_ledger"]["path"]),
                out_dir=Path(td), expected_total=m["n_cases"])
            if _sha256_file(orig) != m["pack_sha256"]:
                errors.append("original pack rebuild sha256 != "
                              "manifest pack_sha256（pack 产物或输入"
                              "链被破坏）")
            orig_rows = _load_rows(orig, "original pack", errors)
    except ValueError as exc:
        errors.append(f"original pack rebuild failed: {exc}")
    return orig_rows


def _evidence_errors(rows: list[dict], chunks_path: Path | None,
                     m: dict, errors: list[str]) -> None:
    """证据引用复验：chunk 存在、snippet 连续、source 一致。"""
    try:
        text, sources, _ = hp._load_chunks(chunks_path or Path(
            m["inputs"]["chunks"]["path"]))
    except (OSError, ValueError) as exc:
        errors.append(f"chunks 无法加载: {exc}")
        text, sources = {}, {}
    for r in rows:
        cid = r.get("case_id", "<unknown>")
        for ev in r.get("evidence", []):
            ck = text.get(ev.get("chunk_id", ""))
            if not ck:
                errors.append(f"{cid}: chunk 引用不存在 "
                              f"{ev.get('chunk_id')}")
                continue
            if not rv.snippet_is_evidence(ev.get("snippet", ""), ck):
                errors.append(f"{cid}: {ev.get('chunk_id')}: snippet 不是"
                              "连续证据")
            if sources.get(ev.get("chunk_id", "")) != ev.get("source_id"):
                errors.append(f"{cid}: {ev.get('chunk_id')}: source 与"
                              "chunks.jsonl 不一致")


def _blank_errors(blank: list[dict], orig_rows: list[dict] | None,
                  errors: list[str], *, expected_total: int | None) -> None:
    """空白 pack 行：结构合法、三个人工字段全空、与确定性重建一致
    （orig_rows 为 None 时跳过重建比对）。"""
    if expected_total is not None and len(blank) != expected_total:
        errors.append(f"blank pack rows {len(blank)} != expected "
                      f"{expected_total}")
    for r in blank:
        cid = r.get("case_id", "<unknown>")
        extra = set(r) - hp.ALLOWED_KEYS
        if extra:
            errors.append(f"{cid}: 非法字段 {sorted(extra)}")
        for f in HUMAN_FIELDS:
            if (r.get(f) or "").strip():
                errors.append(f"空白 pack {cid}: 人工字段 {f} 已被填写"
                              "（必须全空）")
    if orig_rows is not None:
        orig_by_id = {r["case_id"]: r for r in orig_rows}
        for r in blank:
            o = orig_by_id.get(r.get("case_id"))
            if o is not None and _canon(r, ()) != _canon(o, ()):
                errors.append(f"空白 pack {r.get('case_id')}: 与确定性重建"
                              "不一致")


def _filled_errors(filled: list[dict], blank: list[dict],
                   errors: list[str], *,
                   expected_total: int | None) -> None:
    """已填写 pack：行数、唯一 id、键集、逐行对齐（除三个人工字段外
    规范化一致）、decision 枚举、reviewer 非空。LLM 路径特有的
    reviewer 前缀与 reject 必须附 notes 规则由调用方追加。"""
    if expected_total is not None and len(filled) != expected_total:
        errors.append(f"filled pack rows {len(filled)} != expected "
                      f"{expected_total}（重复/缺失 case）")
    ids = [r.get("case_id", "") for r in filled]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        errors.append(f"filled pack 存在重复 case id: {dup}")
    for r in filled:
        extra = set(r) - hp.ALLOWED_KEYS
        if extra:
            errors.append(f"{r.get('case_id')}: 非法字段 {sorted(extra)}")
        missing = hp.ALLOWED_KEYS - set(r)
        if missing:
            errors.append(f"{r.get('case_id')}: 缺少字段 {sorted(missing)}")
    blank_by_id = {r["case_id"]: r for r in blank}
    for r in filled:
        cid = r.get("case_id", "<unknown>")
        o = blank_by_id.get(cid)
        if o is None:
            errors.append(f"{cid}: 未知 case（不在原始 pack 中）")
            continue
        if _canon(r, HUMAN_FIELDS) != _canon(o, HUMAN_FIELDS):
            errors.append(f"{cid}: 除人工字段外被篡改（必须与原 pack "
                          "一致）")
        d = r.get("human_review_decision")
        if d not in DECISIONS:
            errors.append(f"{cid}: decision 为空或非法 {d!r}（仅允许 "
                          f"{DECISIONS}）")
        if not (r.get("human_reviewer") or "").strip():
            errors.append(f"{cid}: reviewer 为空")


def _llm_filled_extra_errors(filled: list[dict], errors: list[str],
                             reviewer_prefix: str) -> None:
    """LLM 路径特有：reviewer 必须 reviewer_prefix 前缀；reject /
    needs_followup 必须附 notes。"""
    for r in filled:
        cid = r.get("case_id", "<unknown>")
        reviewer = (r.get("human_reviewer") or "").strip()
        if reviewer and not reviewer.startswith(reviewer_prefix):
            errors.append(f"{cid}: reviewer 必须以 {reviewer_prefix} 开头"
                          "（LLM 标识）")
        if r.get("human_review_decision") in ("reject", "needs_followup") \
                and not (r.get("human_review_notes") or "").strip():
            errors.append(f"{cid}: {r.get('human_review_decision')} 必须"
                          "附 notes")


# ── 导入主流程 ────────────────────────────────────────────────────────

def apply(pack_path: Path, pack_manifest_path: Path, out_dir: Path,
          chunks_path: Path | None = None) -> dict[str, Any]:
    """严格导入人工审阅结果；返回状态 dict（fail-closed，失败零输出）。"""
    errors: list[str] = []

    # 1) pack manifest：五类输入 SHA 复算（输入不可变性）
    try:
        m = json.loads(pack_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "failed",
                "errors": [f"pack manifest 无法读取: {exc}"]}
    _manifest_input_errors(m, errors)

    # 2) 确定性重建原始 pack：SHA 必须等于 pack manifest 的 pack_sha256
    orig_rows = _rebuild_original_pack(m, errors)

    # 3) 已填写 pack：行数、唯一 id、键集
    filled = _load_rows(pack_path, "human review pack", errors)
    if len(filled) != m["n_cases"]:
        errors.append(f"filled pack rows {len(filled)} != manifest "
                      f"{m['n_cases']}（重复/缺失 case）")
    ids = [r.get("case_id", "") for r in filled]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        errors.append(f"filled pack 存在重复 case id: {dup}")
    for r in filled:
        extra = set(r) - hp.ALLOWED_KEYS
        if extra:
            errors.append(f"{r.get('case_id')}: 非法字段 {sorted(extra)}")
        missing = hp.ALLOWED_KEYS - set(r)
        if missing:
            errors.append(f"{r.get('case_id')}: 缺少字段 {sorted(missing)}")

    # 4) 逐行对齐比较（除三个人工字段外规范化一致）+ 人工字段语义
    orig_by_id = {r["case_id"]: r for r in orig_rows}
    for r in filled:
        cid = r.get("case_id", "<unknown>")
        o = orig_by_id.get(cid)
        if o is None:
            errors.append(f"{cid}: 未知 case（不在原始 pack 中）")
            continue
        if _canon(r, HUMAN_FIELDS) != _canon(o, HUMAN_FIELDS):
            errors.append(f"{cid}: 除人工字段外被篡改（必须与原 pack "
                          "一致）")
        d = r.get("human_review_decision")
        if d not in DECISIONS:
            errors.append(f"{cid}: decision 为空或非法 {d!r}（仅允许 "
                          f"{DECISIONS}）")
        if not (r.get("human_reviewer") or "").strip():
            errors.append(f"{cid}: reviewer 为空")

    # 5) 证据引用仍能映射到 chunks 与 source（独立复验）
    _evidence_errors(filled, chunks_path, m, errors)

    # fail-closed：任何非法状态 → 零输出
    if errors:
        return {"status": "failed", "errors": sorted(set(errors))}

    counts = {d: sum(1 for r in filled
                     if r["human_review_decision"] == d) for d in DECISIONS}
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
        (out_dir / "human-review-issues.jsonl").write_text(
            "\n".join(_line(x) for x in sorted(issues,
                                               key=lambda x: x["case_id"]))
            + "\n", encoding="utf-8")
        (out_dir / "human-review-issues-report.md").write_text(
            _issues_report_text(filled, blocked), encoding="utf-8")
        return {"status": "issues", "errors": [], "counts": counts,
                "blocked": blocked,
                "outputs": ["human-review-issues.jsonl",
                            "human-review-issues-report.md"]}

    # 分支 3：150/150 confirmed → 独立、确定性 overlay + manifest
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
        "status": STATUS_HUMAN_REVIEWED,
        "n_cases": len(cases),
        "cases": cases,
        "created_by": "corpus_v2_human_review_apply.py",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = out_dir / "human-reviewed-truth-overlay.json"
    overlay_path.write_text(json.dumps(overlay, ensure_ascii=False,
                                       indent=1) + "\n", encoding="utf-8")
    reviewers = sorted({r["human_reviewer"] for r in filled})
    inputs = {
        "human_review_pack": {"path": str(pack_path.resolve()),
                              "sha256": _sha256_file(pack_path)},
        "original_pack_sha256": m["pack_sha256"],
    }
    for key in ("draft", "chunks", "chunk_manifest", "corpus_manifest",
                "repair_ledger"):
        inputs[key] = {"path": m["inputs"][key]["path"],
                       "sha256": m["inputs"][key]["sha256"]}
    manifest = {
        "overlay_version": OVERLAY_VERSION,
        "status": STATUS_HUMAN_REVIEWED,
        "n_cases": len(cases),
        "decision_counts": counts,
        "reviewers": reviewers,
        "inputs": inputs,
        "overlay_sha256": _sha256_file(overlay_path),
        "created_by": "corpus_v2_human_review_apply.py",
    }
    (out_dir / "human-reviewed-truth-overlay-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return {"status": "overlay", "errors": [], "counts": counts,
            "blocked": [],
            "outputs": ["human-reviewed-truth-overlay.json",
                        "human-reviewed-truth-overlay-manifest.json"]}


def _line(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _issues_report_text(rows: list[dict], blocked: list[str]) -> str:
    counts = {d: sum(1 for r in rows if r["human_review_decision"] == d)
              for d in DECISIONS}
    lines = [
        "# v2 人工终审问题清单报告",
        "",
        "> 存在 reject / needs_followup：**未生成可用于评测的正式 overlay**，",
        "> 不得进入 v2.1。以下问题需人工复核后重新填写并再次导入。",
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
        "overlay 未生成；本报告为人工复核的问题清单；不得自动宣称任何",
        "批准，不得进入 v2.1。",
        "",
    ]
    return "\n".join(lines) + "\n"


# ── overlay 链复检 ────────────────────────────────────────────────────

def verify(overlay_manifest_path: Path, *, overlay_path: Path | None = None,
           pack_path: Path | None = None) -> list[str]:
    """对既有 overlay + manifest 复检（SHA 链、输入不可变性、结构）；
    返回错误列表（空 = 通过）。"""
    errors: list[str] = []
    try:
        m = json.loads(overlay_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"overlay manifest 无法读取: {exc}"]

    if m.get("status") != STATUS_HUMAN_REVIEWED:
        errors.append(f"status 必须为 {STATUS_HUMAN_REVIEWED}")
    if m.get("overlay_version") != OVERLAY_VERSION:
        errors.append("overlay_version 非法")

    ov = overlay_path or overlay_manifest_path.parent / \
        "human-reviewed-truth-overlay.json"
    if not ov.exists():
        errors.append(f"overlay 文件不存在: {ov}")
    elif m.get("overlay_sha256") != _sha256_file(ov):
        errors.append("overlay sha256 漂移（产物被改写）")

    # 输入不可变性：全部文件类 inputs 复算（original_pack_sha256 是
    # SHA 链引用值、无对应文件，跳过——它在 apply 阶段已与重建比对）
    for key, info in m.get("inputs", {}).items():
        if not isinstance(info, dict) or "path" not in info or \
                "sha256" not in info:
            continue
        p = Path(info["path"])
        if not p.exists():
            errors.append(f"inputs.{key}: 文件不存在: {p}")
        elif info["sha256"] != _sha256_file(p):
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
        extra = set(c) - CASE_KEYS
        if extra:
            errors.append(f"{c.get('case_id')}: overlay 非法字段 "
                          f"{sorted(extra)}")
        if c.get("relevance_level") not in RELEVANCE_LEVELS:
            errors.append(f"{c.get('case_id')}: relevance_level 非法")

    # decision_counts 与已填写 pack 复算一致
    pack = pack_path or Path(m.get("inputs", {}).get("human_review_pack",
                                                     {}).get("path", ""))
    if pack.exists():
        rows = _load_rows(pack, "human review pack", errors)
        counts = {d: sum(1 for r in rows if r.get("human_review_decision")
                         == d) for d in DECISIONS}
        if counts != m.get("decision_counts"):
            errors.append(f"decision_counts 与已填写 pack 复算不一致: "
                          f"{counts} vs {m.get('decision_counts')}")
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
        print("usage: corpus_v2_human_review_apply.py apply|verify "
              "[--out DIR]")
        return 2
    cmd = args.pop(0)
    try:
        if cmd == "apply":
            out = Path(_flag(args, "--out") or DEFAULT_OUT)
            res = apply(pack_path=out / "human-review-pack.jsonl",
                        pack_manifest_path=out /
                        "human-review-pack-manifest.json",
                        out_dir=out)
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
                print("no overlay generated (issues only)")
            else:
                print("overlay generated: human-reviewed-truth-overlay.json "
                      "(HUMAN_REVIEWED, no auto approval, not entering "
                      "v2.1 automatically)")
            return 0
        if cmd == "verify":
            out = Path(_flag(args, "--out") or DEFAULT_OUT)
            errs = verify(out / "human-reviewed-truth-overlay-manifest.json")
            if errs:
                for e in errs:
                    print("VERIFY FAILED:", e)
                return 1
            print("verify ok: overlay + manifest chain intact "
                  "(HUMAN_REVIEWED)")
            return 0
    except ValueError as exc:
        print(f"FAILED: {exc}")
        return 2
    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
