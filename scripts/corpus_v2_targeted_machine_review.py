"""Corpus v2 targeted post-repair machine review of the five
persistent-reject cases (MACHINE_REVIEWED_DIAGNOSTIC_ONLY).

对修复后的 5 条持续 reject case（en-052 / en-055 / mixed-016 /
mixed-026 / multi-014）用 ``deepseek-v4-pro``（temperature=0.0、
max_tokens=8000）逐条盲态机器复审：

1. **盲态**：输入仅含 query、previous_turns（仅 query 文本）、
   should_refuse、修复后的 acceptable_answer_points、对应 evidence 与
   完整 scoped chunks 原文；绝不传入 case_id、历史 decision、第三轮
   notes、cohort、split、任何「持续 reject」标签或预期 verdict。
2. **契约**：复用语义仲裁 JSON 契约（``corpus_v2_llm_semantic_
   adjudication``）与 coherence validator（``corpus_v2_llm_semantic_
   coherence``）：输出必须完整、可解析、模型身份正确、逐答案点 support
   index 连续唯一、verdict 与 support/refusal 映射一致。
3. **fail-closed**：任一条为 reject / needs_followup / 无效 JSON /
   coherence 违规 → 输出诊断报告并停止；绝不生成任何 truth overlay。
   即使 5 条全部 confirmed，也只产出
   ``MACHINE_REVIEWED_DIAGNOSTIC_ONLY`` 报告——明确它不是人工终审、
   不是上线批准、不是 v2.1 准入。
4. **逐条留痕**：每条保留 prompt SHA-256、响应 SHA-256、原始响应、
   解析重试与传输重试记录。
5. **确定性**：盲包结构、prompt、manifest 结构可复现；输入 pack
   逐字节确定；同输入 + 同模型输出可重建。

禁止模型：``gpt-5.6-sol``、``deepseek-v4-flash``（FORBIDDEN_MODELS，
代码级守卫）；reviewer_model 固定为 ``deepseek-v4-pro``，不可用则
fail-closed 停止，不回退。

产物目录：evaluation/datasets/v2/targeted-post-repair-machine-review/
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # 允许直接以 python scripts/... 方式运行
import scripts.corpus_v2_human_review_pack as hp  # noqa: E402
import scripts.corpus_v2_llm_semantic_adjudication as adj  # noqa: E402
import scripts.corpus_v2_llm_semantic_coherence as coherence  # noqa: E402
import scripts.corpus_v2_review as rv  # noqa: E402

DEFAULT_DRAFT = rv.DEFAULT_DRAFT
DEFAULT_CHUNKS = rv.DEFAULT_CHUNKS
DEFAULT_OUT = ROOT / "evaluation" / "datasets" / "v2" / \
    "targeted-post-repair-machine-review"

TARGET_CASE_IDS = ("en-052", "en-055", "mixed-016", "mixed-026", "multi-014")
EXPECTED_TOTAL = 150
REVIEWER_MODEL = adj.REVIEWER_MODEL          # deepseek-v4-pro
TEMPERATURE = adj.TEMPERATURE
MAX_TOKENS = adj.MAX_TOKENS
OUTPUT_FILES = ("targeted-input-pack.jsonl", "post-repair-reviews.jsonl",
                "raw-responses.jsonl", "MACHINE_REVIEWED_DIAGNOSTIC_ONLY.md",
                "manifest.json")

# 盲态输入中禁止出现的 JSON 键形态（历史结论 / 分层 / 评测结构）
FORBIDDEN_INPUT_KEYS = ("decision", "verdict", "cohort", "split", "holdout",
                        "dev_set", "reviewer", "notes", "persistent", "third",
                        "rationale", "case_id", "overlay", "reviewed_by",
                        "review_status")

# 盲态行唯一允许的顶层键（与语义仲裁盲包同构）
BLIND_ROW_KEYS = frozenset({"query", "previous_turns", "should_refuse",
                            "acceptable_answer_points", "evidence", "chunks"})


class MachineReviewError(Exception):
    """fail-closed 复审失败（任何漂移立即失败，不产出 overlay）。"""


# ── 盲态输入构建 ─────────────────────────────────────────────────────

def _leak_scan(row: dict, case_id: str) -> list[str]:
    """盲态泄漏扫描：case_id 与任何历史/分层结构键不得出现在输入中。"""
    text = json.dumps(row, ensure_ascii=False)
    errs: list[str] = []
    if case_id in text:
        errs.append(f"case_id 泄漏: {case_id}")
    for key in FORBIDDEN_INPUT_KEYS:
        if f'"{key}"' in text:
            errs.append(f"禁止结构键: {key}")
    return errs


def build_targeted_input(draft_path: Path, chunks_path: Path,
                         out_dir: Path | None = None, *,
                         target_ids: tuple[str, ...] = TARGET_CASE_IDS,
                         expected_total: int = EXPECTED_TOTAL) -> dict:
    """构建 5 条盲态输入行（纯确定性；可选写出 targeted-input-pack）。

    输入仅来自修复后的草稿：query / previous_turns / should_refuse /
    修复后的答案点 / evidence / 完整 scoped chunks。任何证据或盲态
    泄漏问题立即失败。
    """
    cases, draft_sha = rv.load_draft(draft_path)
    if len(cases) != expected_total:
        raise MachineReviewError(f"草稿行数 {len(cases)} != {expected_total}"
                                 "（fail-closed）")
    chunks, chunk_sources, chunks_sha = hp._load_chunks(chunks_path)
    by_id = {c["id"]: c for c in cases}
    missing = set(target_ids) - set(by_id)
    if missing:
        raise MachineReviewError(f"目标 case 缺失: {sorted(missing)}"
                                 "（fail-closed）")

    rows: list[dict] = []
    for cid in target_ids:
        case = by_id[cid]
        errs = rv._chain_errors(case, by_id)
        if errs:
            raise MachineReviewError(f"{cid}: 多轮链破损: {errs}")
        evidence: list[dict] = []
        for rc in case.get("relevant_chunks") or []:
            ck = chunks.get(rc.get("chunk_id", ""), "")
            if not ck:
                raise MachineReviewError(f"{cid}: chunk 引用不存在: "
                                         f"{rc.get('chunk_id')}")
            if chunk_sources.get(rc["chunk_id"]) != rc.get("source_id"):
                raise MachineReviewError(f"{cid}: {rc['chunk_id']}: source "
                                         "不一致（fail-closed）")
            if not rv.snippet_is_evidence(rc.get("chunk_text_snippet", ""),
                                          ck):
                raise MachineReviewError(f"{cid}: {rc['chunk_id']}: snippet "
                                         "不是连续证据（fail-closed）")
            evidence.append({"source_id": rc["source_id"],
                             "chunk_id": rc["chunk_id"],
                             "snippet": rc["chunk_text_snippet"],
                             "section": rc.get("section")})
        if case.get("relevance_level") == "chunk" and not evidence:
            raise MachineReviewError(f"{cid}: relevance_level=chunk 但无"
                                     "chunk 证据")
        turns = [{"query": t["query"]}
                 for t in rv._previous_turns(case, by_id)]
        cids = sorted({ev["chunk_id"] for ev in evidence})
        row = {
            "query": case["query"],
            "previous_turns": turns,
            "should_refuse": bool(case.get("should_refuse")),
            "acceptable_answer_points":
                list(case.get("acceptable_answer_points") or []),
            "evidence": evidence,
            "chunks": [{"chunk_id": c, "text": chunks[c]} for c in cids],
        }
        if set(row) != BLIND_ROW_KEYS:
            raise MachineReviewError(f"{cid}: 盲态行字段漂移: {sorted(set(row))}")
        leaks = _leak_scan(row, cid)
        if leaks:
            raise MachineReviewError(f"{cid}: 盲态泄漏（fail-closed）: "
                                     + "; ".join(leaks))
        rows.append(row)

    pack_text = "\n".join(adj._line(r) for r in rows) + "\n"
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "targeted-input-pack.jsonl").write_text(pack_text,
                                                           encoding="utf-8",
                                                           newline="\n")
    return {"rows": rows, "pack_bytes": pack_text.encode("utf-8"),
            "cases_by_id": by_id, "chunk_texts": chunks,
            "draft_sha256": draft_sha, "chunks_sha256": chunks_sha,
            "n_targets": len(target_ids)}


# ── 复审流程 ─────────────────────────────────────────────────────────

def _case_prompt_sha(row: dict) -> str:
    payload = {"system": adj.SYSTEM_PROMPT, "user": row}
    return adj._sha256_text(json.dumps(payload, ensure_ascii=False,
                                       sort_keys=True,
                                       separators=(",", ":")))


def run(draft_path: Path, chunks_path: Path, out_dir: Path, *,
        model: str = REVIEWER_MODEL, llm_fn=None,
        target_ids: tuple[str, ...] = TARGET_CASE_IDS) -> dict:
    """5 条盲态复审全流程；任何失败抛 MachineReviewError 且不产出 overlay。

    全部 confirmed 才写 post-repair-reviews 与
    MACHINE_REVIEWED_DIAGNOSTIC_ONLY 报告；否则只写诊断报告 + manifest
    并停止。
    """
    if model in adj.FORBIDDEN_MODELS:
        raise MachineReviewError(f"forbidden model: {model}")
    if model != REVIEWER_MODEL:
        raise MachineReviewError(f"reviewer_model must be {REVIEWER_MODEL!r}, "
                                 f"got {model!r}")
    built = build_targeted_input(draft_path, chunks_path, out_dir,
                                 target_ids=target_ids)
    rows = built["rows"]
    if llm_fn is None:
        from src.llm_gateway import llm_call  # noqa: PLC0415
        llm_fn = llm_call

    records: list[dict] = []
    for i, (cid, row) in enumerate(zip(target_ids, rows), start=1):
        try:
            record = _review_one(cid, i, row, llm_fn, model)
        except adj.AdjudicationError as exc:
            raise MachineReviewError(str(exc)) from exc
        records.append(record)
        print(f"reviewed {i}/{len(target_ids)} {cid} -> {record['status']}",
              flush=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "raw-responses.jsonl").write_text(
        "\n".join(adj._line({"case_id": r["case_id"], "index": r["index"],
                             "prompt_sha256": r["prompt_sha256"],
                             "response_sha256": r["response_sha256"],
                             "raw_content": r["raw_content"],
                             "parse_retries": r["parse_retries"],
                             "retries_used": r["retries_used"]})
                  for r in records) + "\n", encoding="utf-8", newline="\n")

    failed = [r for r in records if r["status"] != "confirmed"]
    if failed:
        (out_dir / "diagnostic-report.md").write_text(
            _diagnostic_md(records, failed), encoding="utf-8", newline="\n")
        (out_dir / "manifest.json").write_text(
            json.dumps(_fail_manifest_dict(built, records, out_dir, model),
                       ensure_ascii=False, indent=1) + "\n", encoding="utf-8",
                       newline="\n")
        detail = ", ".join(f"{r['case_id']}={r['status']}" for r in failed)
        raise MachineReviewError(
            f"fail-closed: {len(failed)} 条未确认（{detail}）；输出诊断报告"
            "并停止，不生成任何 overlay")

    review_rows = [{
        "index": r["index"],
        "semantic_verdict": "confirmed",
        "verdict_rationale": r["parsed"]["verdict_rationale"],
        "answer_point_supports": r["parsed"]["answer_point_supports"],
        "refusal_assessment": None,
        "refusal_evidence": [],
        "model": model,
        "retries_used": r["retries_used"],
        "parse_retries": r["parse_retries"],
    } for r in records]
    (out_dir / "post-repair-reviews.jsonl").write_text(
        "\n".join(adj._line(x) for x in review_rows) + "\n",
        encoding="utf-8")
    (out_dir / "MACHINE_REVIEWED_DIAGNOSTIC_ONLY.md").write_text(
        _report_md(built, records, review_rows), encoding="utf-8", newline="\n")
    (out_dir / "manifest.json").write_text(
        json.dumps(_manifest_dict(built, records, review_rows, out_dir,
                                  model), ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return {"status": "all_confirmed", "fail_closed": False,
            "n_reviewed": len(records),
            "verdicts": [r["status"] for r in records]}


def _review_one(case_id: str, index: int, row: dict, llm_fn, model: str) -> dict:
    """单条复审：最多 2 次纠正性解析重试；记录 prompt/响应 SHA 与重试。"""
    messages = [{"role": "system", "content": adj.SYSTEM_PROMPT},
                {"role": "user", "content": adj._line(row)}]
    prompt_sha = _case_prompt_sha(row)
    chunk_ids = {c["chunk_id"] for c in row["chunks"]}
    n_points = len(row["acceptable_answer_points"])
    content, retries = adj._llm_content(llm_fn, messages, model, case_id)
    response_sha = adj._sha256_text(content)
    attempts = [{"attempt": 1, "raw_content": content,
                 "response_sha256": response_sha, "retries_used": retries}]
    parsed = adj._parse_adjudication(
        content, should_refuse=row["should_refuse"],
        chunk_ids=chunk_ids, n_points=n_points)
    parse_retries = 0
    while parsed is None and parse_retries < 2:
        messages = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": "你上一次的输出无法解析为合法 JSON。"
                                        "请只输出一个 JSON 对象，字段与枚举"
                                        "值必须与系统提示完全一致。"}]
        content, retries2 = adj._llm_content(llm_fn, messages, model, case_id)
        retries += retries2
        parse_retries += 1
        response_sha = adj._sha256_text(content)
        attempts.append({"attempt": parse_retries + 1,
                         "raw_content": content,
                         "response_sha256": response_sha,
                         "retries_used": retries2})
        parsed = adj._parse_adjudication(
            content, should_refuse=row["should_refuse"],
            chunk_ids=chunk_ids, n_points=n_points)

    violations: list[dict] = []
    if parsed is not None:
        candidate = dict(parsed)
        candidate["index"] = index
        candidate["model"] = model
        violations = coherence.validate_semantic_coherence(row, candidate)
    if parsed is None:
        status = "unparseable"
    elif violations:
        status = "coherence_violation"
    else:
        status = parsed["semantic_verdict"]
    return {
        "case_id": case_id, "index": index, "prompt_sha256": prompt_sha,
        "response_sha256": response_sha, "raw_content": content,
        "parse_retries": parse_retries, "retries_used": retries,
        "attempts": attempts, "status": status, "parsed": parsed,
        "violations": violations,
    }


# ── 报告与 manifest ──────────────────────────────────────────────────

def _report_md(built: dict, records: list[dict], review_rows: list[dict]) -> str:
    lines = [
        "# MACHINE_REVIEWED_DIAGNOSTIC_ONLY — v2 持续 reject 修复后定点机器复审", "",
        "> 本报告为 **MACHINE_REVIEWED_DIAGNOSTIC_ONLY** 机器复审诊断报告："
        "只提供机器语义复审证据，**不是人工终审、不是上线批准、不是 v2.1 "
        "准入**；不修改任何标注，不生成任何 overlay。", "",
        "## 一、输入（盲态）", "",
        f"- 复审条数：{built['n_targets']}（en-052 / en-055 / mixed-016 / "
        "mixed-026 / multi-014）。",
        "- 每条仅含 query、previous_turns（仅 query 文本）、should_refuse、"
        "修复后的 acceptable_answer_points、evidence 与完整 scoped chunks；"
        "不含 case_id、历史 decision、第三轮 notes、cohort、split 或任何"
        "「持续 reject」标签与预期 verdict。",
        "- 盲包 targeted-input-pack.jsonl 逐字节确定可重建。", "",
        "## 二、模型与契约", "",
        f"- 模型：{REVIEWER_MODEL}，temperature={TEMPERATURE}，"
        f"max_tokens={MAX_TOKENS}。",
        "- 契约：语义仲裁 JSON 契约 + coherence 校验（verdict 与 "
        "support/refusal 映射、逐答案点 support index 连续唯一）。", "",
        "## 三、逐条结果", "",
        "| index | semantic_verdict | parse_retries | transport_retries |",
        "|---|---|---|---|",
    ]
    for r in records:
        lines.append(f"| {r['index']} | {r['status']} | {r['parse_retries']} "
                     f"| {r['retries_used']} |")
    lines += ["", "## 四、逐条留痕", "",
              "| index | prompt_sha256 | response_sha256 |", "|---|---|---|"]
    for r in records:
        lines.append(f"| {r['index']} | {r['prompt_sha256'][:16]}… | "
                     f"{r['response_sha256'][:16]}… |")
    lines += ["", "原始响应、解析重试与传输重试记录见 raw-responses.jsonl。", "",
              "## 五、结论", "",
              "5 条全部通过机器复审（confirmed）仅代表机器语义证据；"
              "**不是人工终审、不是人工批准、不是 v2.1 准入**。", "",
    ]
    return "\n".join(lines) + "\n"


def _diagnostic_md(records: list[dict], failed: list[dict]) -> str:
    lines = [
        "# FAIL_CLOSED 诊断报告 — 修复后定点机器复审未通过", "",
        "> 任一条仍为 reject / needs_followup / 无效 JSON / coherence 违规，"
        "按规则停止；**未生成任何 truth overlay，不构成任何 v2.1 决策**。", "",
        "## 未通过明细", "",
        "| index | case_id | status | 违规规则 |", "|---|---|---|---|",
    ]
    for r in failed:
        rules = ", ".join(v["rule"] for v in r["violations"]) or "-"
        lines.append(f"| {r['index']} | {r['case_id']} | {r['status']} | "
                     f"{rules} |")
    lines += ["", "## 全部记录状态", "",
              "| index | case_id | status |", "|---|---|---|"]
    for r in records:
        lines.append(f"| {r['index']} | {r['case_id']} | {r['status']} |")
    lines += ["", "原始响应与重试记录见 raw-responses.jsonl；"
                  "失败 case 的原模型输出摘录如下：", ""]
    for r in failed:
        lines.append(f"### index {r['index']}（{r['case_id']}）")
        lines.append(f"```\n{r['raw_content'][:800]}\n```")
    lines += ["", "## 停止声明", "",
              "机器复审未全量通过：本报告仅为诊断证据，未生成 overlay；"
              "修复后的草稿维持现状，等待人工裁决。", "",
    ]
    return "\n".join(lines) + "\n"


def _manifest_dict(built: dict, records: list[dict], review_rows: list[dict],
                   out_dir: Path, model: str) -> dict:
    outputs = {}
    for name in OUTPUT_FILES:
        if name != "manifest.json":
            p = out_dir / name
            if p.is_file():  # 失败路径可能不产出 reviews / report
                outputs[name] = {"sha256": _sha256_file(p)}
    body = {
        "task": "targeted post-repair machine review (diagnostic only)",
        "reviewer_model": model,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "n_cases": len(records),
        "inputs": {
            "draft": {"sha256": built["draft_sha256"]},
            "chunks": {"sha256": built["chunks_sha256"]},
        },
        "cases": [{
            "case_id": r["case_id"], "index": r["index"],
            "prompt_sha256": r["prompt_sha256"],
            "response_sha256": r["response_sha256"],
            "parse_retries": r["parse_retries"],
            "retries_used": r["retries_used"],
            "status": r["status"],
        } for r in records],
        "verdicts": {"confirmed": len(review_rows),
                     "reject": 0, "needs_followup": 0},
        "retries": {
            "transport_retries_total": sum(r["retries_used"]
                                           for r in records),
            "transport_retries_max": max((r["retries_used"]
                                          for r in records), default=0),
            "parse_retries_total": sum(r["parse_retries"] for r in records),
            "parse_retries_max": 2,
        },
        "outputs": outputs,
        "fail_closed": False,
        "status": "MACHINE_REVIEWED_DIAGNOSTIC_ONLY",
        "created_by": "corpus_v2_targeted_machine_review.py run",
        "note": "机器复审诊断证据；不是人工终审、不是上线批准、不是 v2.1 "
                "准入；未生成任何 overlay。",
    }
    return body


def _fail_manifest_dict(built: dict, records: list[dict], out_dir: Path,
                        model: str) -> dict:
    body = _manifest_dict(built, records, [], out_dir, model)
    body["fail_closed"] = True
    body["verdicts"] = {"confirmed": 0, "reject": 0, "needs_followup": 0}
    body["status"] = "FAIL_CLOSED"
    body["failed"] = [{"case_id": r["case_id"], "index": r["index"],
                       "status": r["status"],
                       "violations": r["violations"]}
                      for r in records if r["status"] != "confirmed"]
    return body


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


# ── CLI ──────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    out = DEFAULT_OUT
    if "--out" in args:
        out = Path(args[args.index("--out") + 1])
    try:
        summary = run(DEFAULT_DRAFT, DEFAULT_CHUNKS, out)
    except MachineReviewError as exc:
        print(f"FAILED: {exc}")
        return 2
    print(f"post-repair machine review: {summary['n_reviewed']} cases "
          f"all confirmed -> {out} "
          f"(MACHINE_REVIEWED_DIAGNOSTIC_ONLY)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
