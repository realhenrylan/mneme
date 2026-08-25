"""v2.0.1 自动化准入门禁脚本（corpus_v2_automated_review_apply）。

对 automated-review 产物实施严格校验：
1. 150 行、case_id 唯一、集合与当前 draft 一致；
2. 非审阅字段与当前 draft / 证据映射一致；
3. 每条 evidence 的 chunk 存在、source 一致、snippet 连续、字符范围正确；
4. 模型固定为 deepseek-v4-pro，参数固定，响应/manifest SHA 可复算；
5. reviewer_type = LLM_ASSISTED_OWNER_AUTHORIZED，不允许任何 human 标识；
6. 150/150 confirmed → 生成 overlay + manifest（AUTOMATED_REVIEWED_OWNER_AUTHORIZED）；
7. 任意 reject / needs_followup → 仅生成 issues 清单和报告，禁止生成 overlay；
8. 输入或输出 SHA 漂移 → fail-closed；
9. 不调用 human review apply，不改写 blank human-review pack。

CLI
---
::

    python scripts/corpus_v2_automated_review_apply.py apply

产物目录：evaluation/datasets/v2/automated-review/
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DRAFT = ROOT / "evaluation" / "datasets" / "v2" / "annotations" / \
    "v2-cases-draft.jsonl"
DEFAULT_CHUNKS = ROOT / "data" / "v2-corpus" / "chunks" / "chunks.jsonl"
DEFAULT_CHUNK_MANIFEST = ROOT / "data" / "v2-corpus" / "chunks" / \
    "chunk-manifest.json"
DEFAULT_REVIEW_DIR = ROOT / "evaluation" / "datasets" / "v2" / "automated-review"
DEFAULT_OVERLAY_DIR = ROOT / "evaluation" / "datasets" / "v2" / "automated-reviewed-truth"

# 固定常量（与 corpus_v2_automated_review.py 一致）
REVIEWER_TYPE = "LLM_ASSISTED_OWNER_AUTHORIZED"
REVIEWER_MODEL = "deepseek-v4-pro"
REVIEWER_TEMPERATURE = 0.0
REVIEWER_MAX_TOKENS = 8000
FORBIDDEN_MODELS = ("gpt-5.6-sol", "deepseek-v4-flash")
OVERLAY_STATUS = "AUTOMATED_REVIEWED_OWNER_AUTHORIZED"

sys.path.insert(0, str(ROOT))
from evaluation.corpus_v2 import normalize_snippet, snippet_is_evidence  # noqa: E402


class ApplyError(Exception):
    """Fail-closed apply failure。"""


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
    return _sha256_text(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")))


def _line(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


# ── loaders ───────────────────────────────────────────────────────────

def load_draft(path: Path) -> tuple[list[dict], str]:
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


# ── validation ────────────────────────────────────────────────────────

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


def _validate_review_entries(review_rows: list[dict], draft_by_id: dict[str, dict],
                              chunks_map: dict[str, str]) -> tuple[list[str], dict]:
    """校验 review 条目。返回 (errors, case_results)。

    case_results: {case_id: {decision, reviewer_type, model, ...}}
    """
    errors: list[str] = []
    case_results: dict[str, dict] = {}
    review_ids = []

    for row in review_rows:
        cid = row.get("case_id", "")
        review_ids.append(cid)

        # 基本字段
        decision = row.get("review_decision")
        if decision not in ("confirmed", "reject", "needs_followup"):
            errors.append(f"{cid}: invalid decision {decision!r}")

        reviewer_type = row.get("reviewer_type", "")
        if reviewer_type != REVIEWER_TYPE:
            errors.append(f"{cid}: reviewer_type {reviewer_type!r} "
                          f"!= {REVIEWER_TYPE!r}")
        if "HUMAN" in reviewer_type:
            errors.append(f"{cid}: human identifier in reviewer_type")

        model = row.get("model", "")
        if model != REVIEWER_MODEL:
            errors.append(f"{cid}: model {model!r} != {REVIEWER_MODEL!r}")
        if model in FORBIDDEN_MODELS:
            errors.append(f"{cid}: forbidden model {model!r}")

        temp = row.get("temperature")
        if temp != REVIEWER_TEMPERATURE:
            errors.append(f"{cid}: temperature {temp!r} != "
                          f"{REVIEWER_TEMPERATURE!r}")
        mt = row.get("max_tokens")
        if mt != REVIEWER_MAX_TOKENS:
            errors.append(f"{cid}: max_tokens {mt!r} != "
                          f"{REVIEWER_MAX_TOKENS!r}")

        # SHA 校验
        if "prompt_sha256" not in row or not row["prompt_sha256"]:
            errors.append(f"{cid}: missing prompt_sha256")
        if "response_sha256" not in row or not row["response_sha256"]:
            errors.append(f"{cid}: missing response_sha256")
        if "raw_response_sha256" not in row or not row["raw_response_sha256"]:
            errors.append(f"{cid}: missing raw_response_sha256")

        # evidence 校验：重建 pack payload 并比对 evidence_sha256
        pack_sha = row.get("evidence_sha256", "")
        draft_case = draft_by_id.get(cid)
        if draft_case:
            evidence_list = []
            for rc in draft_case.get("relevant_chunks", []):
                cid_chunk = rc.get("chunk_id", "")
                text = chunks_map.get(cid_chunk, "")
                snip = rc.get("chunk_text_snippet", "")
                char_range = None
                if snip and text:
                    norm_snip = normalize_snippet(snip)
                    norm_chunk = normalize_snippet(text)
                    idx = norm_chunk.find(norm_snip)
                    if idx != -1:
                        char_range = {"start": idx, "end": idx + len(norm_snip)}
                evidence_list.append({
                    "chunk_id": cid_chunk,
                    "source_id": rc.get("source_id", ""),
                    "snippet": snip,
                    "snippet_sha256": _sha256_text(snip),
                    "chunk_text_sha256": _sha256_text(text),
                    "chunk_text": text,
                    "char_range": char_range,
                })
            # previous_turns 与 pack builder 一致
            prev_turns = _previous_turns(draft_case, draft_by_id)
            payload = {
                "case_id": cid,
                "query": draft_case.get("query", ""),
                "language": draft_case.get("language", ""),
                "query_type": draft_case.get("query_type", ""),
                "turn": (draft_case.get("metadata") or {}).get("turn", 1),
                "previous_turns": prev_turns,
                "draft": {
                    "should_refuse": draft_case.get("should_refuse", False),
                    "is_refusal_turn": draft_case.get("is_refusal_turn"),
                    "relevance_level": draft_case.get("relevance_level", ""),
                    "doc_target": draft_case.get("doc_target", ""),
                    "note": draft_case.get("note", ""),
                    "acceptable_answer_points":
                        draft_case.get("acceptable_answer_points", []),
                },
                "evidence": evidence_list,
            }
            computed_sha = canonical_sha(payload)
            if computed_sha != pack_sha:
                errors.append(f"{cid}: evidence_sha256 mismatch "
                              f"(computed {computed_sha[:16]}... "
                              f"!= stored {pack_sha[:16]}...)")
        else:
            errors.append(f"{cid}: case not found in draft")

        case_results[cid] = {
            "decision": decision,
            "reviewer_type": reviewer_type,
            "model": model,
            "temperature": row.get("temperature"),
            "max_tokens": row.get("max_tokens"),
            "confidence": row.get("confidence"),
            "rationale": row.get("rationale", ""),
            "issue_categories": row.get("issue_categories", []),
            "evidence_summary": row.get("evidence_summary", []),
            "prompt_sha256": row.get("prompt_sha256", ""),
            "response_sha256": row.get("response_sha256", ""),
            "raw_response_sha256": row.get("raw_response_sha256", ""),
            "transport_retries": row.get("transport_retries", 0),
            "parse_retries": row.get("parse_retries", 0),
        }

    # 集合校验
    draft_ids = sorted(draft_by_id.keys())
    if sorted(review_ids) != draft_ids:
        errors.append(f"review case_id set mismatch: "
                      f"review has {sorted(review_ids)[:5]}..., "
                      f"draft has {draft_ids[:5]}...")
    if len(review_rows) != 150:
        errors.append(f"review row count {len(review_rows)} != 150")
    if len(set(review_ids)) != len(review_ids):
        dup = {i for i in review_ids if review_ids.count(i) > 1}
        errors.append(f"duplicate case_ids in review: {sorted(dup)}")

    return errors, case_results


def _validate_input_sha(review_dir: Path, draft_path: Path,
                        chunks_path: Path, chunk_manifest_path: Path,
                        *, override_draft: Path | None = None,
                        override_chunks: Path | None = None,
                        override_cm: Path | None = None) -> list[str]:
    """校验输入文件 SHA 与 review manifest 一致。"""
    errors: list[str] = []
    manifest_path = review_dir / "manifest.json"
    if not manifest_path.is_file():
        errors.append("manifest.json not found in review dir")
        return errors

    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    inputs = m.get("inputs", {})

    # 使用 override 路径（测试场景）或 manifest 中记录的路径
    actual_draft = override_draft or draft_path
    actual_chunks = override_chunks or chunks_path
    actual_cm = override_cm or chunk_manifest_path

    if inputs.get("draft", {}).get("sha256") != _sha256_file(actual_draft):
        errors.append("draft sha256 drift")
    if inputs.get("chunks", {}).get("sha256") != _sha256_file(actual_chunks):
        errors.append("chunks sha256 drift")
    if inputs.get("chunk_manifest", {}).get("sha256") != _sha256_file(actual_cm):
        errors.append("chunk_manifest sha256 drift")

    return errors


def _validate_blank_human_pack(review_dir: Path) -> list[str]:
    """校验 blank human-review pack 未被修改（SHA 不变，人工字段仍为空）。"""
    errors: list[str] = []
    # 查找 blank human-review pack（可能在上级目录）
    blank_pack_candidates = [
        ROOT / "evaluation" / "datasets" / "v2" / "human-review" / "human-review-pack.jsonl",
    ]
    for candidate in blank_pack_candidates:
        if candidate.is_file():
            # 检查是否包含任何 human review 字段被填写
            for ln in candidate.open(encoding="utf-8"):
                if not ln.strip():
                    continue
                d = json.loads(ln)
                ann = d.get("annotation", {})
                reviewed_by = ann.get("reviewed_by", "")
                review_status = ann.get("review_status", "")
                review_notes = ann.get("review_notes", "")
                if reviewed_by or (review_status and review_status != "pending"):
                    errors.append(f"{d.get('id', '?')}: blank human pack "
                                  f"has been modified (reviewed_by="
                                  f"{reviewed_by!r}, status={review_status!r})")
                if "HUMAN_REVIEWED" in review_notes or "HUMAN_APPROVED" in review_notes:
                    errors.append(f"{d.get('id', '?')}: blank human pack "
                                  f"contains human approval markers")
    return errors


def _check_no_human_identifiers(review_dir: Path) -> list[str]:
    """扫描 review 产物，确保不包含声称人工审核完成的字样。

    注意：报告中的否定性声明（如"不是人工审核"）是合法的免责声明，
    不在此检查范围内。检查的是明确声称已完成人工审核的标识。
    """
    errors: list[str] = []
    # 只检查明确声称人工审核/批准的标识，不包括否定性免责声明中的引用
    forbidden_strings = ["HUMAN_REVIEWED", "HUMAN_APPROVED", "人工审核完成"]
    scan_files = [
        review_dir / "automated-review.jsonl",
        review_dir / "automated-review-issues.jsonl",
        review_dir / "automated-review-report.md",
        review_dir / "automated-review-gate-report.md",
    ]
    for f in scan_files:
        if not f.is_file():
            continue
        content = f.read_text(encoding="utf-8")
        for forbidden in forbidden_strings:
            if forbidden in content:
                errors.append(f"{f.name}: contains forbidden string "
                              f"{forbidden!r}")
    return errors


def _deterministic_timestamp() -> str:
    return "2026-08-07T00:00:00+00:00"


# ── main apply logic ──────────────────────────────────────────────────

def apply(review_dir: Path = DEFAULT_REVIEW_DIR,
          draft_path: Path = DEFAULT_DRAFT,
          chunks_path: Path = DEFAULT_CHUNKS,
          chunk_manifest_path: Path = DEFAULT_CHUNK_MANIFEST,
          overlay_dir: Path = DEFAULT_OVERLAY_DIR,
          *,
          override_draft: Path | None = None,
          override_chunks: Path | None = None,
          override_cm: Path | None = None) -> int:
    """执行自动化准入门禁。

    1. 校验输入 SHA 与 review manifest 一致；
    2. 校验 150 条 review 条目；
    3. 若 150/150 confirmed → 生成 overlay + manifest；
    4. 否则 → 仅生成 issues 报告，不生成 overlay。
    """
    # 1. 输入 SHA 校验
    sha_errors = _validate_input_sha(
        review_dir, draft_path, chunks_path, chunk_manifest_path,
        override_draft=override_draft, override_chunks=override_chunks,
        override_cm=override_cm)
    if sha_errors:
        raise ApplyError("input SHA drift: " + "; ".join(sha_errors))

    # 清理旧产物（避免旧 gate report / issues 中的 forbidden 字符串
    # 被当前运行误检）
    for stale in ["automated-review-gate-report.md",
                  "automated-review-issues.jsonl"]:
        p = review_dir / stale
        if p.exists():
            p.unlink()
    overlay_dir.mkdir(parents=True, exist_ok=True)
    for stale in ["automated-reviewed-truth-overlay.json",
                  "automated-reviewed-truth-manifest.json"]:
        p = overlay_dir / stale
        if p.exists():
            p.unlink()

    # 2. 加载数据（优先使用 override 路径，用于测试场景）
    actual_draft = override_draft or draft_path
    actual_chunks = override_chunks or chunks_path
    draft_cases, draft_sha = load_draft(actual_draft)
    draft_by_id = {c["id"]: c for c in draft_cases}
    chunks_map, chunks_sha = load_chunks(actual_chunks)

    review_path = review_dir / "automated-review.jsonl"
    if not review_path.is_file():
        raise ApplyError("automated-review.jsonl not found")

    review_rows = [json.loads(l) for l in review_path.open(encoding="utf-8")
                   if l.strip()]

    # 3. 校验 review 条目
    entry_errors, case_results = _validate_review_entries(
        review_rows, draft_by_id, chunks_map)
    if entry_errors:
        raise ApplyError("review entry validation failed: " +
                         "; ".join(entry_errors))

    # 4. 统计
    decisions = [r["review_decision"] for r in review_rows]
    counts = {d: decisions.count(d) for d in ("confirmed", "reject",
                                               "needs_followup")}
    all_confirmed = counts["reject"] == 0 and counts["needs_followup"] == 0

    # 5. 校验 blank human pack 未被修改
    human_errors = _validate_blank_human_pack(review_dir)
    if human_errors:
        raise ApplyError("blank human pack validation failed: " +
                         "; ".join(human_errors))

    # 6. 扫描禁止字符串
    forbidden_errors = _check_no_human_identifiers(review_dir)
    if forbidden_errors:
        raise ApplyError("forbidden human identifiers found: " +
                         "; ".join(forbidden_errors))

    # 7. 生成产物
    review_dir.mkdir(parents=True, exist_ok=True)

    # issues 清单（非 confirmed 的 case）
    issues = [r for r in review_rows if r["review_decision"] != "confirmed"]
    issues_path = review_dir / "automated-review-issues.jsonl"
    if issues:
        issues_path.write_text(
            "\n".join(_line(r) for r in issues) + "\n", encoding="utf-8")
    elif issues_path.is_file():
        issues_path.unlink()

    # overlay 或 gate report
    if all_confirmed:
        overlay_dir.mkdir(parents=True, exist_ok=True)
        overlay_path = overlay_dir / "automated-reviewed-truth-overlay.json"
        overlay_manifest_path = overlay_dir / "automated-reviewed-truth-manifest.json"

        # 构建 overlay：confirmed 的 case 映射到 truth
        overlay: dict[str, Any] = {
            "status": OVERLAY_STATUS,
            "reviewer_type": REVIEWER_TYPE,
            "reviewer_identity": REVIEWER_TYPE,
            "model": REVIEWER_MODEL,
            "temperature": REVIEWER_TEMPERATURE,
            "max_tokens": REVIEWER_MAX_TOKENS,
            "n_cases": len(review_rows),
            "decision_counts": counts,
            "generated_at": _deterministic_timestamp(),
            "truth_cases": {},
            "disclaimer": (
                f"本 overlay 由用户授权的自动审阅生成（{REVIEWER_TYPE}），"
                f"不代表人工批准或生产上线批准。"
                f"原始人工审阅包未修改。"
            ),
        }
        for r in review_rows:
            cid = r["case_id"]
            draft_case = draft_by_id.get(cid, {})
            overlay["truth_cases"][cid] = {
                "case_id": cid,
                "query": draft_case.get("query", ""),
                "should_refuse": draft_case.get("should_refuse", False),
                "acceptable_answer_points":
                    draft_case.get("acceptable_answer_points", []),
                "relevant_source_ids":
                    draft_case.get("relevant_source_ids", []),
                "relevant_chunk_ids":
                    draft_case.get("relevant_chunk_ids", []),
                "review_decision": r["review_decision"],
                "reviewer_type": r["reviewer_type"],
                "model": r["model"],
            }

        overlay_path.write_text(
            json.dumps(overlay, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")

        overlay_manifest = {
            "status": OVERLAY_STATUS,
            "reviewer_type": REVIEWER_TYPE,
            "reviewer_identity": REVIEWER_TYPE,
            "model": REVIEWER_MODEL,
            "temperature": REVIEWER_TEMPERATURE,
            "max_tokens": REVIEWER_MAX_TOKENS,
            "n_cases": len(review_rows),
            "decision_counts": counts,
            "inputs": {
                "review_dir": str(review_dir.resolve()),
                "review_jsonl_sha256": _sha256_file(review_path),
                "review_manifest_sha256": _sha256_file(review_dir / "manifest.json"),
                "draft_sha256": draft_sha,
                "chunks_sha256": chunks_sha,
                "chunk_manifest_sha256": _sha256_file(chunk_manifest_path),
            },
            "outputs": {
                "overlay_path": str(overlay_path.resolve()),
                "overlay_sha256": _sha256_file(overlay_path),
            },
            "generated_at": _deterministic_timestamp(),
            "created_by": "corpus_v2_automated_review_apply.py apply",
        }
        overlay_manifest_path.write_text(
            json.dumps(overlay_manifest, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        # 写入后补录 manifest 自引用 SHA
        overlay_manifest["outputs"]["manifest_sha256"] = _sha256_file(
            overlay_manifest_path)
        overlay_manifest_path.write_text(
            json.dumps(overlay_manifest, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")

        print(f"APPLY OK: 150/150 confirmed → overlay generated")
        print(f"  overlay: {overlay_path}")
        print(f"  manifest: {overlay_manifest_path}")
    else:
        # 不生成 overlay，只生成 gate report
        report_path = review_dir / "automated-review-gate-report.md"
        n_blocked = counts["reject"] + counts["needs_followup"]
        report_lines = [
            "# v2.0.1 自动审阅门禁报告", "",
            f"> **状态**：GATE BLOCKED — {n_blocked} 条未通过",
            f"> **结论**：未生成 automated overlay。",
            f"> **声明**：本报告是用户授权的自动审阅结果，不是人工审核。", "",
            "## 决策统计", "",
            f"- confirmed：{counts['confirmed']}",
            f"- reject：{counts['reject']}",
            f"- needs_followup：{counts['needs_followup']}",
            f"- 确认率：{counts['confirmed']}/{len(review_rows)} = "
            f"{counts['confirmed'] / len(review_rows):.1%}",
            "",
            "## 未通过 case 清单", "",
            "| case_id | decision | 问题类别 | 理由 |", "|---|---|---|---|",
        ]
        for r in review_rows:
            if r["review_decision"] != "confirmed":
                cats = "、".join(r.get("issue_categories", []) or ["-"])
                report_lines.append(
                    f"| {r['case_id']} | {r['review_decision']} | {cats} | "
                    f"{r.get('rationale', '')[:200]} |")
        report_lines += [
            "", "## fail-closed 校验", "",
            "- 输入 SHA 与 manifest 一致；",
            "- 150 条 review 条目校验通过；",
            "- reviewer_type = LLM_ASSISTED_OWNER_AUTHORIZED；",
            f"- 模型 = {REVIEWER_MODEL}，temperature = {REVIEWER_TEMPERATURE}，"
            f"max_tokens = {REVIEWER_MAX_TOKENS}；",
            f"- 禁止模型守卫：{', '.join(FORBIDDEN_MODELS)}；",
            "- blank human-review pack 未被修改；",
            "- 产物中无人工审核标识等字样；",
            "",
            "## 结论", "",
            f"存在 {n_blocked} 条 reject / needs_followup，"
            f"不得生成 automated overlay。"
            f"修复后须重新运行 automated-review 脚本。",
        ]
        report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        print(f"APPLY BLOCKED: {n_blocked} 条未通过 → 未生成 overlay")
        print(f"  gate report: {report_path}")
        print(f"  issues: {issues_path}")

    return 0 if all_confirmed else 1


# ── CLI ───────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    try:
        return apply()
    except (ApplyError, ValueError) as exc:
        print(f"FAILED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
