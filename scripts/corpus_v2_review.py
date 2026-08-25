"""Corpus v2 evidence-driven second-pass review (LLM_ASSISTED_SECOND_PASS).

对 150 条 LLM_ASSISTED 草稿执行独立的证据驱动二次审阅。设计原则：

1. **只读、不改写**：本脚本绝不修改 v2 原始草稿、chunks、manifest、
   case-freeze、split-lock；reject / needs_followup 只输出待修复清单。
2. **无 split 身份**：审阅输入（evidence-review pack）不含任何
   dev/holdout/split 字段、检索分数、候选集或历史评测结果；报告只输出
   全量汇总，绝不按 split 分析。
3. **确定性**：pack 与报告结构可复现（无时间戳的产物逐字节相同）；
   LLM 调用 temperature=0.0、按 case_id 排序逐条执行。
4. **fail-closed**：evidence SHA 漂移、缺失证据、非法状态、重复/遗漏
   case、或原始草稿被改写，立即失败并拒绝产出产物。

审阅人身份固定为 ``LLM_ASSISTED_SECOND_PASS``——LLM 辅助二次审阅，
**绝不伪称人工审核**；全部 150 条 confirmed 才允许输出
"LLM-assisted candidate review complete" 结论，且仍非人工批准。

禁止模型：``gpt-5.6-sol``（FORBIDDEN_MODELS，代码级守卫）。

CLI
---
::

    python scripts/corpus_v2_review.py pack      # 离线构建 evidence-review pack
    python scripts/corpus_v2_review.py review    # LLM 逐条二审（150 条）
    python scripts/corpus_v2_review.py verify    # 对既有产物重跑 fail-closed 校验

产物目录：evaluation/datasets/v2/review/
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DRAFT = ROOT / "evaluation" / "datasets" / "v2" / "annotations" / \
    "v2-cases-draft.jsonl"
DEFAULT_CHUNKS = ROOT / "data" / "v2-corpus" / "chunks" / "chunks.jsonl"
DEFAULT_CHUNK_MANIFEST = ROOT / "data" / "v2-corpus" / "chunks" / \
    "chunk-manifest.json"
DEFAULT_OUT = ROOT / "evaluation" / "datasets" / "v2" / "review"

PACK_VERSION = 1
REVIEWER_IDENTITY = "LLM_ASSISTED_SECOND_PASS"
DECISIONS = ("confirmed", "reject", "needs_followup")
CONFIDENCE_LEVELS = ("high", "medium", "low")
ISSUE_CATEGORIES = ("answerable_refusal", "chunk_source_relevance",
                    "snippet_sufficiency", "multi_turn_chain", "other")
FORBIDDEN_MODELS = ("gpt-5.6-sol",)
DEFAULT_MODEL = "deepseek-chat"

sys.path.insert(0, str(ROOT))
from evaluation.corpus_v2 import snippet_is_evidence  # noqa: E402


class ReviewError(Exception):
    """Fail-closed review failure（任何非法状态立即失败）。"""


# ── hashing helpers ───────────────────────────────────────────────────

def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def canonical_sha(obj: Any) -> str:
    """Canonical JSON SHA-256（sort_keys + compact separators）。"""
    return _sha256_text(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")))


def _line(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


# ── loaders ───────────────────────────────────────────────────────────

def load_draft(path: Path) -> tuple[list[dict], str]:
    """Load draft cases (sorted by id); ValueError on duplicate ids."""
    cases: list[dict] = []
    for ln in path.open(encoding="utf-8"):
        if ln.strip():
            cases.append(json.loads(ln))
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        dup = {i for i in ids if ids.count(i) > 1}
        raise ValueError(f"duplicate case ids in draft: {sorted(dup)}")
    return sorted(cases, key=lambda c: c["id"]), _sha256_file(path)


def load_chunks(path: Path) -> tuple[dict[str, str], str]:
    chunks: dict[str, str] = {}
    for ln in path.open(encoding="utf-8"):
        if ln.strip():
            d = json.loads(ln)
            chunks[d["chunk_id"]] = d["text"]
    return chunks, _sha256_file(path)


# ── multi-turn chain validation (structural, fail-closed) ─────────────

def _chain_errors(case: dict, by_id: dict[str, dict]) -> list[str]:
    """校验多轮链结构：turn 连续、follow_up_to 存在、chain_id 一致。"""
    meta = case.get("metadata") or {}
    turn = meta.get("turn") or 1
    fu = meta.get("follow_up_to")
    chain_id = meta.get("chain_id")
    errs: list[str] = []
    if turn > 1:
        if not fu:
            errs.append(f"{case['id']}: turn={turn} but follow_up_to missing")
        else:
            parent = by_id.get(fu)
            if parent is None:
                errs.append(f"{case['id']}: follow_up_to {fu} missing")
            else:
                p_meta = parent.get("metadata") or {}
                if (p_meta.get("turn") or 1) != turn - 1:
                    errs.append(f"{case['id']}: parent {fu} turn "
                                f"{p_meta.get('turn')} != {turn - 1}")
                if p_meta.get("chain_id") != chain_id:
                    errs.append(f"{case['id']}: chain_id mismatch with "
                                f"parent {fu}")
    elif fu:
        errs.append(f"{case['id']}: turn=1 must not have follow_up_to")
    return errs


def _previous_turns(case: dict, by_id: dict[str, dict]) -> list[dict]:
    """沿 follow_up_to 回溯到链头，返回 head-first 的 previous-turn 上下文。"""
    turns: list[dict] = []
    seen: set[str] = set()
    cur = (case.get("metadata") or {}).get("follow_up_to")
    while cur and cur not in seen:
        seen.add(cur)
        parent = by_id.get(cur)
        if parent is None:
            break
        turns.append({"case_id": parent["id"], "query": parent["query"]})
        cur = (parent.get("metadata") or {}).get("follow_up_to")
    turns.reverse()
    return turns


# ── pack ──────────────────────────────────────────────────────────────

def build_pack(draft_path: Path, chunks_path: Path,
               chunk_manifest_path: Path, out_dir: Path) -> Path:
    """构建 evidence-review pack（离线、确定性、fail-closed）。

    每条 = case_id + query + previous-turn 上下文 + 草稿标签 +
    source/chunk 原文证据（snippet + 完整 chunk 文本）+ evidence SHA-256。
    不含任何 split / dev / holdout / 检索 / 候选 / 历史评测字段。
    """
    cases, draft_sha = load_draft(draft_path)
    chunks, chunks_sha = load_chunks(chunks_path)
    by_id = {c["id"]: c for c in cases}

    rows: list[dict] = []
    for case in cases:
        errs = _chain_errors(case, by_id)
        if errs:
            raise ValueError("multi-turn chain broken: " + "; ".join(errs))
        evidence: list[dict] = []
        for rc in case.get("relevant_chunks") or []:
            cid = rc.get("chunk_id", "")
            text = chunks.get(cid, "")
            if not text:
                raise ValueError(f"{case['id']}: chunk missing: {cid}")
            snip = rc.get("chunk_text_snippet", "")
            # 缺失证据：chunk 级 case 必须带连续证据 snippet（fail-closed）
            if not snippet_is_evidence(snip, text):
                raise ValueError(
                    f"{case['id']}: {cid}: snippet is not contiguous "
                    f"evidence of chunk text")
            evidence.append({
                "chunk_id": cid,
                "source_id": rc.get("source_id", ""),
                "snippet": snip,
                "snippet_sha256": _sha256_text(snip),
                "chunk_text_sha256": _sha256_text(text),
                "chunk_text": text,
            })
        if case.get("relevance_level") == "chunk" and not evidence:
            raise ValueError(f"{case['id']}: relevance_level=chunk but no "
                             f"chunk evidence")

        row: dict[str, Any] = {
            "case_id": case["id"],
            "query": case["query"],
            "language": case.get("language", ""),
            "query_type": case.get("query_type", ""),
            "turn": (case.get("metadata") or {}).get("turn", 1),
            "previous_turns": _previous_turns(case, by_id),
            "draft": {
                "should_refuse": case.get("should_refuse", False),
                "is_refusal_turn": case.get("is_refusal_turn"),
                "relevance_level": case.get("relevance_level", ""),
                "doc_target": case.get("doc_target", ""),
                "note": case.get("note", ""),
                "acceptable_answer_points":
                    case.get("acceptable_answer_points", []),
            },
            "evidence": evidence,
        }
        row["evidence_sha256"] = canonical_sha(
            {k: v for k, v in row.items() if k != "evidence_sha256"})
        rows.append(row)

    rows.sort(key=lambda r: r["case_id"])
    out_dir.mkdir(parents=True, exist_ok=True)
    pack_path = out_dir / "evidence-review-pack.jsonl"
    pack_path.write_text("\n".join(_line(r) for r in rows) + "\n",
                         encoding="utf-8")
    manifest = {
        "pack_version": PACK_VERSION,
        "reviewer_identity": REVIEWER_IDENTITY,
        "n_cases": len(rows),
        "inputs": {
            "draft": {"path": str(Path(draft_path).resolve()),
                      "sha256": draft_sha, "rows": len(cases)},
            "chunks": {"path": str(Path(chunks_path).resolve()),
                       "sha256": chunks_sha},
            "chunk_manifest": {"path": str(Path(chunk_manifest_path).resolve()),
                               "sha256": _sha256_file(chunk_manifest_path)},
        },
        "pack_sha256": _sha256_file(pack_path),
        "evidence_sha256_aggregate": _sha256_text(
            "".join(r["evidence_sha256"] for r in rows)),
        "created_by": "corpus_v2_review.py pack",
    }
    (out_dir / "evidence-review-pack-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return pack_path


# ── fail-closed verification ──────────────────────────────────────────

def verify(pack_path: Path, pack_manifest_path: Path,
           draft_path: Path | None = None, chunks_path: Path | None = None,
           auto_path: Path | None = None) -> list[str]:
    """fail-closed 校验：输入 SHA 漂移、evidence SHA 漂移、非法状态、
    重复/遗漏 case、reviewer 身份。返回错误列表（空 = 通过）。"""
    errors: list[str] = []
    m = json.loads(pack_manifest_path.read_text(encoding="utf-8"))
    draft_path = draft_path or Path(m["inputs"]["draft"]["path"])
    chunks_path = chunks_path or Path(m["inputs"]["chunks"]["path"])

    # 原始草稿 / 语料被改写 → 立即失败
    if m["inputs"]["draft"]["sha256"] != _sha256_file(draft_path):
        errors.append("draft sha256 drift: current draft file no longer "
                      "matches pack manifest input")
    if m["inputs"]["chunks"]["sha256"] != _sha256_file(chunks_path):
        errors.append("chunks sha256 drift: current chunks file no longer "
                      "matches pack manifest input")

    # pack 完整性
    if m["pack_sha256"] != _sha256_file(pack_path):
        errors.append("pack sha256 mismatch: evidence-review-pack.jsonl "
                      "was modified after manifest was written")
    rows = [json.loads(l) for l in pack_path.open(encoding="utf-8")
            if l.strip()]
    ids = [r["case_id"] for r in rows]
    if len(rows) != m["n_cases"]:
        errors.append(f"pack row count {len(rows)} != manifest "
                      f"{m['n_cases']} (case 遗漏/重复)")
    if len(set(ids)) != len(ids):
        dup = {i for i in ids if ids.count(i) > 1}
        errors.append(f"duplicate case ids in pack: {sorted(dup)}")
    if ids != sorted(ids):
        errors.append("pack rows not sorted by case_id")
    for r in rows:
        payload = {k: v for k, v in r.items() if k != "evidence_sha256"}
        if canonical_sha(payload) != r["evidence_sha256"]:
            errors.append(f"{r['case_id']}: evidence_sha256 drift "
                          f"(row content modified)")

    # auto-review 产物
    if auto_path and auto_path.is_file():
        arows = [json.loads(l) for l in auto_path.open(encoding="utf-8")
                 if l.strip()]
        aid = {a["case_id"] for a in arows}
        if len(arows) != len(rows):
            errors.append(f"auto-review row count {len(arows)} != "
                          f"pack {len(rows)}")
        if aid != set(ids):
            errors.append("auto-review case id set mismatch with pack")
        pack_sha = {r["case_id"]: r["evidence_sha256"] for r in rows}
        for a in arows:
            if a["decision"] not in DECISIONS:
                errors.append(f"{a['case_id']}: invalid decision "
                              f"{a['decision']!r}")
            if a["reviewer_identity"] != REVIEWER_IDENTITY:
                errors.append(f"{a['case_id']}: reviewer identity spoof "
                              f"{a['reviewer_identity']!r}")
            if a.get("evidence_sha256") != pack_sha.get(a["case_id"]):
                errors.append(f"{a['case_id']}: auto-review evidence sha "
                              f"mismatch with pack")
    return errors


# ── LLM review ────────────────────────────────────────────────────────

def _review_messages(payload: dict) -> list[dict]:
    system = (
        f"你是独立的证据驱动审阅 LLM，身份固定为 {REVIEWER_IDENTITY}"
        "（LLM 辅助二次审阅，不是人工审核）。"
        "任务：审阅一条评测标注草稿。只能依据本消息内提供的 query、"
        "多轮上下文、草稿标签和 chunk 原文证据做出判断；"
        "不得假设证据之外存在的语料内容。逐项核验："
        "1) answerable/refusal：should_refuse / is_refusal_turn 与 query 是否一致，"
        "拒绝回答是否合理；"
        "2) chunk/source 相关性：relevant chunk 原文是否真的支撑 query 的回答；"
        "3) snippet 充分性：chunk_text_snippet 是否足以支撑"
        "acceptable_answer_points 中的每个答案点；"
        "4) 多轮关系：previous_turns 上下文下，当前 query 的 follow-up 依赖是否合理。"
        "只输出一个 JSON 对象，不要输出其他任何文本："
        '{"decision": "confirmed"|"reject"|"needs_followup",'
        ' "confidence": "high"|"medium"|"low",'
        ' "rationale": "结构化理由",'
        ' "issue_categories": ["answerable_refusal"|"chunk_source_relevance"'
        '|"snippet_sufficiency"|"multi_turn_chain"|"other"]}'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False,
                                               sort_keys=True, indent=1)},
    ]


def _parse_decision(content: str) -> dict | None:
    """严格解析 LLM 决策 JSON；任何非法值返回 None（fail-closed）。"""
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    decision = d.get("decision")
    confidence = d.get("confidence")
    rationale = str(d.get("rationale", "")).strip()
    if decision not in DECISIONS or confidence not in CONFIDENCE_LEVELS:
        return None
    if not rationale:
        return None
    cats = [c for c in (d.get("issue_categories") or [])
            if c in ISSUE_CATEGORIES]
    return {"decision": decision, "confidence": confidence,
            "rationale": rationale, "issue_categories": cats}


def review(pack_path: Path, pack_manifest_path: Path, out_dir: Path,
           *, model: str | None = None,
           llm_fn: Callable | None = None,
           run_at: str | None = None) -> int:
    """对 pack 全部 case 逐条二审，产出 auto-review 审计产物。

    fail-closed：任何 case 的 LLM 输出非法（不可解析 / 非法值 / 调用失败）
    即抛 ReviewError，且不产出任何 auto-review 产物。
    """
    if model is None:
        model = os.getenv("LLM_MODEL", DEFAULT_MODEL)
    if model in FORBIDDEN_MODELS:
        raise ValueError(f"forbidden model: {model}")
    if llm_fn is None:
        from src.llm_gateway import llm_call
        llm_fn = llm_call

    errs = verify(pack_path, pack_manifest_path)
    if errs:
        raise ReviewError("fail-closed: " + "; ".join(errs))

    rows = [json.loads(l) for l in pack_path.open(encoding="utf-8")
            if l.strip()]
    results: list[dict] = []
    for i, r in enumerate(rows, start=1):
        payload = {k: v for k, v in r.items() if k != "evidence_sha256"}
        messages = _review_messages(payload)
        content = _llm_content(llm_fn, messages, model, r["case_id"])
        parsed = _parse_decision(content)
        if parsed is None:
            # 一次纠正性重试：告知输出无法解析，要求只输出 JSON
            messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": "你上一次的输出无法解析为合法 "
                                            "JSON。请只输出一个 JSON 对象。"},
            ]
            content = _llm_content(llm_fn, messages, model, r["case_id"])
            parsed = _parse_decision(content)
        if parsed is None:
            raise ReviewError(f"{r['case_id']}: invalid decision output "
                              f"(unparseable or illegal values)")
        results.append({
            "case_id": r["case_id"],
            "evidence_sha256": r["evidence_sha256"],
            "reviewer_identity": REVIEWER_IDENTITY,
            "decision": parsed["decision"],
            "confidence": parsed["confidence"],
            "rationale": parsed["rationale"],
            "issue_categories": parsed["issue_categories"],
            "model": model,
        })
        print(f"reviewed {i}/{len(rows)} {r['case_id']} "
              f"{parsed['decision']}", flush=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "auto-review.jsonl").write_text(
        "\n".join(_line(x) for x in results) + "\n", encoding="utf-8")

    fix = [x for x in results if x["decision"] != "confirmed"]
    if fix:
        (out_dir / "auto-review-fixlist.jsonl").write_text(
            "\n".join(_line(x) for x in fix) + "\n", encoding="utf-8")

    (out_dir / "auto-review-evidence-report.md").write_text(
        build_report(rows, results), encoding="utf-8")

    counts = {d: sum(1 for x in results if x["decision"] == d)
              for d in DECISIONS}
    m = json.loads(pack_manifest_path.read_text(encoding="utf-8"))
    manifest = {
        "reviewer_identity": REVIEWER_IDENTITY,
        "model": model,
        "n_cases": len(results),
        "decision_counts": counts,
        "inputs": m["inputs"],
        "pack_sha256": m["pack_sha256"],
        "evidence_sha256_aggregate": m["evidence_sha256_aggregate"],
        "run_at": run_at or datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "created_by": "corpus_v2_review.py review",
    }
    (out_dir / "auto-review-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return 0


def _llm_content(llm_fn: Callable, messages: list[dict], model: str,
                 case_id: str) -> str:
    """调用 LLM 一次并返回消息文本；调用失败立即抛 ReviewError。"""
    try:
        resp, _rec = llm_fn("corpus_v2_review", messages, model=model,
                            temperature=0.0, max_tokens=1500)
        return resp.choices[0].message.content
    except ReviewError:
        raise
    except Exception as exc:
        raise ReviewError(f"{case_id}: llm call failed: {exc}")


# ── report ────────────────────────────────────────────────────────────

def build_report(pack_rows: list[dict], results: list[dict]) -> str:
    """全量汇总报告（绝不按 split 分析）。"""
    n = len(results)
    counts = {d: sum(1 for r in results if r["decision"] == d)
              for d in DECISIONS}
    conf = {c: sum(1 for r in results if r["confidence"] == c)
            for c in CONFIDENCE_LEVELS}
    cats = {c: sum(1 for r in results if c in r["issue_categories"])
            for c in ISSUE_CATEGORIES}
    n_review = counts["reject"] + counts["needs_followup"]

    lines = [
        "# v2 证据驱动二次审阅报告（LLM_ASSISTED_SECOND_PASS）", "",
        "> 自动二审：独立审阅 LLM 逐条核验草稿真值；审阅人身份固定为",
        "> `LLM_ASSISTED_SECOND_PASS`。本报告与 auto-review 产物均为 LLM",
        "> 辅助结果，**未经人工批准**，绝不伪称人工审核。", "",
        "## 全量汇总（不按 split 分析）", "",
        f"- 审阅条数：{n}",
        f"- 审阅模型：{results[0]['model']}",
        f"- confirmed：{counts['confirmed']}",
        f"- reject：{counts['reject']}",
        f"- needs_followup：{counts['needs_followup']}",
        f"- 草稿与二审一致率（confirmed / 总数）："
        f"{counts['confirmed']}/{n} = "
        f"{counts['confirmed'] / n:.1%}",
        "",
        "### 置信度分布", "",
        "| 置信度 | 条数 |", "|---|---|",
    ]
    for c in CONFIDENCE_LEVELS:
        lines.append(f"| {c} | {conf[c]} |")
    lines += ["", "### 问题类别分布（reject / needs_followup 提及）", "",
              "| 问题类别 | 提及次数 |", "|---|---|"]
    for c in ISSUE_CATEGORIES:
        lines.append(f"| {c} | {cats[c]} |")
    lines += ["", "### 待修复清单", ""]
    if n_review:
        lines += ["| case_id | decision | 问题类别 | 理由 |", "|---|---|---|---|"]
        for r in results:
            if r["decision"] == "confirmed":
                continue
            lines.append(f"| {r['case_id']} | {r['decision']} | "
                         f"{'、'.join(r['issue_categories']) or '-'} | "
                         f"{r['rationale']} |")
    else:
        lines.append("无（全部 confirmed）。")
    lines += ["", "## fail-closed 校验", "",
              "- 输入（草稿 / chunks）SHA 与 pack manifest 一致；",
              "- 每条 evidence SHA-256 复算一致；case 无重复、无遗漏；",
              "- reviewer 身份固定为 `LLM_ASSISTED_SECOND_PASS`；",
              "- 原始草稿未被改写（本次审阅为只读，未修改任何标注）。", "",
              "## 结论", ""]
    if counts["reject"] == 0 and counts["needs_followup"] == 0:
        lines.append("**LLM-assisted candidate review complete**"
                     "（仍为 LLM_ASSISTED 状态，未经人工批准；"
                     "下一步：人工终审或进入 dev-only v2.1 校准）")
    else:
        lines.append(f"二审未完成：{n_review} 条待修复"
                     "（见待修复清单与 auto-review-fixlist.jsonl），"
                     "不得进入最终语料。")
    return "\n".join(lines) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────

def _flag(args: list[str], name: str, default: str | None) -> str | None:
    if name in args:
        return args[args.index(name) + 1]
    return default


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(__doc__)
        return 0
    cmd = args[0]
    try:
        if cmd == "pack":
            out = Path(_flag(args, "--out", str(DEFAULT_OUT)) or
                       str(DEFAULT_OUT))
            pack = build_pack(DEFAULT_DRAFT, DEFAULT_CHUNKS,
                              DEFAULT_CHUNK_MANIFEST, out)
            n = sum(1 for _ in pack.open(encoding="utf-8") if _.strip())
            print(f"wrote evidence-review pack: {pack} (n={n})")
            return 0
        if cmd == "review":
            out = Path(_flag(args, "--out", str(DEFAULT_OUT)) or
                       str(DEFAULT_OUT))
            model = _flag(args, "--model", None)
            return review(out / "evidence-review-pack.jsonl",
                          out / "evidence-review-pack-manifest.json",
                          out, model=model)
        if cmd == "verify":
            out = Path(_flag(args, "--out", str(DEFAULT_OUT)) or
                       str(DEFAULT_OUT))
            errs = verify(out / "evidence-review-pack.jsonl",
                          out / "evidence-review-pack-manifest.json",
                          auto_path=out / "auto-review.jsonl")
            if errs:
                for e in errs:
                    print("VERIFY FAILED:", e)
                return 1
            print("verify ok: pack + auto-review artifacts intact")
            return 0
    except (ValueError, ReviewError) as exc:
        print(f"FAILED: {exc}")
        return 2
    print(f"unknown command: {cmd}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
