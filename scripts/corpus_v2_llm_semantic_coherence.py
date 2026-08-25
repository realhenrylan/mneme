"""Corpus v2 semantic-coherence audit and targeted recheck of the
deepseek-v4-pro blind adjudications.

对 ``corpus_v2_llm_semantic_adjudication.py`` 产出的 102 条盲态仲裁做
**语义一致性审计**（只读）：逐条按一致性契约 fail-closed 校验，产出
``coherence-audit.json`` 与 ``coherence-report.md``（列出全部违反 case、
具体违反规则、原模型输出）；对每个违反 case 用相同盲态输入、同一模型
（``deepseek-v4-pro``）、temperature=0.0 定点重审，最多 3 次，提示词
显式包含 verdict 与 support/refusal 映射规则；三次仍不合格则该 case
按规则固定为 ``needs_followup`` 并记录失败证据。原始
``deepseek-v4-pro-adjudications.jsonl`` 绝不改写；重审记录、合并后的
102 条、重算的 comparison report 与 manifest 写入独立的
``coherence-recheck/`` 目录。

一致性契约（validate_semantic_coherence）：

1. 拒答题（should_refuse=true）：no_answer / partial_topic_overlap_only
   必须判 confirmed；substantive_answer_exists 必须判 reject；unclear
   必须判 needs_followup；answer_point_supports 必须为空。
2. 可答题（should_refuse=false）：每个答案点必须恰好一条 assessment，
   index 从 0 连续且不重复；存在 unsupported → 不得 confirmed；全部
   非 unsupported → 不得 reject；needs_followup 必须写明无法判断理由。
3. 每条必须有合法 verdict、非空 rationale、reviewer 模型名与原盲态
   输入 index（1..102 连续唯一）。

fail-closed：审计复算盲包/选择清单/仲裁覆盖与现有文件逐项一致才写
审计产物；重审前审计产物必须与复算一致；合并行（代码固定行除外）必须
全部通过契约；任何漂移立即失败且不产出合并/比较结论。代码不允许自行把
reject 改为 confirmed —— 唯一允许的代码改写是 3 次重审失败后按规则
固定为 needs_followup。

禁止模型：``gpt-5.6-sol``、``deepseek-v4-flash``（FORBIDDEN_MODELS，
代码级守卫）；reviewer_model 固定为 ``deepseek-v4-pro``。

产物：evaluation/datasets/v2/llm-semantic-adjudication/
  coherence-audit.json / coherence-report.md（只读审计）
  coherence-recheck/{rechecks.jsonl, merged-adjudications.jsonl,
  comparison-report.md, manifest.json}
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BLANK_PACK = ROOT / "evaluation" / "datasets" / "v2" / "human-review" / \
    "human-review-pack.jsonl"
DEFAULT_FILLED_PACK = ROOT / "evaluation" / "datasets" / "v2" / "human-review" / \
    "human-review-pack.llm-filled.jsonl"
DEFAULT_CHUNKS = ROOT / "data" / "v2-corpus" / "chunks" / "chunks.jsonl"
DEFAULT_ADJ_DIR = ROOT / "evaluation" / "datasets" / "v2" / \
    "llm-semantic-adjudication"

REVIEWER_MODEL = "deepseek-v4-pro"
TEMPERATURE = 0.0
MAX_TOKENS = 8000
RECON_MAX_ATTEMPTS = 3
EXPECTED_TOTAL = 150
EXPECTED_CONFIRMED = 68
EXPECTED_REJECT = 82
EXPECTED_FOLLOWUP = 0

# 一致性规则标识（审计/重审共用，报告与测试按名引用）
RULE_INVALID_INDEX = "invalid_index"
RULE_INVALID_VERDICT = "invalid_verdict"
RULE_MISSING_RATIONALE = "missing_rationale"
RULE_WRONG_MODEL = "wrong_model"
RULE_REFUSAL_SUPPORTS_NOT_EMPTY = "refusal_supports_not_empty"
RULE_REFUSAL_ASSESSMENT_MISMATCH = "refusal_assessment_mismatch"
RULE_SUPPORTS_NOT_EXACT = "supports_index_not_contiguous"
RULE_UNSUPPORTED_WITH_CONFIRMED = "unsupported_with_confirmed"
RULE_NO_UNSUPPORTED_WITH_REJECT = "no_unsupported_with_reject"
RULE_FOLLOWUP_WITHOUT_REASON = "followup_without_reason"
RULE_UNPARSEABLE = "unparseable"

# needs_followup 的 verdict_rationale 必须包含的「无法判断」语义词
FOLLOWUP_REASON_TERMS = ("无法", "不能确定", "不确定", "难以", "无法判断",
                         "无法确认", "不能判断", "无法判定", "需要进一步",
                         "需要人工")

# 3 次重审失败后由代码按规则固定（唯一允许的代码级 verdict 改写）
FIXED_RATIONALE = ("三次重审均未通过一致性契约，无法由模型判断确认，"
                   "按规则固定为 needs_followup（失败证据见 rechecks.jsonl）")

sys.path.insert(0, str(ROOT))  # 允许直接以 python scripts/... 方式运行
import scripts.corpus_v2_llm_semantic_adjudication as adj  # noqa: E402

RECHECK_OUTPUT_FILES = ("rechecks.jsonl", "merged-adjudications.jsonl",
                        "comparison-report.md", "manifest.json")

RECON_PROMPT = (
    "你是盲态机器语义审阅员，正在对一条评测案例做一致性重审"
    "（coherence recheck）。你上一次的仲裁输出违反了语义一致性契约。"
    "请基于本条消息提供的 query、previous_turns、should_refuse、"
    "acceptable_answer_points、evidence 与 chunks 原文重新仲裁，并严格"
    "遵守以下 verdict 与 support/refusal 映射规则：\n"
    "1. 可答题（should_refuse=false）：\n"
    "   - 对 acceptable_answer_points 中每个答案点恰好输出一条 assessment；"
    "answer_point_index 必须从 0 开始连续且不重复，覆盖全部答案点。\n"
    "   - 任何答案点判为 unsupported → semantic_verdict 必须是 reject 或 "
    "needs_followup，不得是 confirmed。\n"
    "   - 全部答案点都有支持（direct_snippet / within_chunk_outside_snippet "
    "/ faithful_paraphrase）→ semantic_verdict 必须是 confirmed 或 "
    "needs_followup，不得是 reject。\n"
    "   - 不得输出 refusal_assessment 与 refusal_evidence 字段。\n"
    "2. 拒答题（should_refuse=true）：\n"
    "   - refusal_assessment=no_answer 或 partial_topic_overlap_only → "
    "semantic_verdict 必须为 confirmed。\n"
    "   - refusal_assessment=substantive_answer_exists → semantic_verdict "
    "必须为 reject。\n"
    "   - refusal_assessment=unclear → semantic_verdict 必须为 "
    "needs_followup。\n"
    "   - 不得输出 answer_point_supports 字段。\n"
    "3. semantic_verdict=needs_followup 时，verdict_rationale 必须写明具体"
    "无法判断的理由。\n"
    "4. 只能依据本条消息提供的内容判断；引用的 chunk_id 必须是本条 chunks "
    "中的 chunk_id。\n"
    "只输出一个 JSON 对象，不要输出任何其他文本，字段如下：\n"
    '{"semantic_verdict": "confirmed"|"reject"|"needs_followup", '
    '"verdict_rationale": "结构化理由", '
    '"answer_point_supports": [{"answer_point_index": 0, "support_level": '
    '"direct_snippet"|"within_chunk_outside_snippet"|"faithful_paraphrase"|'
    '"unsupported", "chunk_id": "...", "excerpt": "最短必要原文摘录"}], '
    '"refusal_assessment": "no_answer"|"partial_topic_overlap_only"|'
    '"substantive_answer_exists"|"unclear", '
    '"refusal_evidence": [{"chunk_id": "...", "excerpt": "..."}]}'
)


class CoherenceError(Exception):
    """fail-closed 一致性审计/重审失败（任何漂移立即失败）。"""


# ── 一致性契约（纯函数）─────────────────────────────────────────────

# refusal_assessment → 唯一允许的 semantic_verdict
REFUSAL_TO_VERDICT = {
    "no_answer": "confirmed",
    "partial_topic_overlap_only": "confirmed",
    "substantive_answer_exists": "reject",
    "unclear": "needs_followup",
}


def validate_semantic_coherence(input_case: dict, adjudication: dict) -> list[dict]:
    """逐条校验语义一致性契约；返回违规列表，合法返回 []。

    纯函数：不修改入参、不读写文件。input_case 为盲态输入行（6 字段），
    adjudication 为解析后的仲裁输出行。
    """
    violations: list[dict] = []

    def add(rule: str, detail: str) -> None:
        violations.append({"rule": rule, "detail": detail})

    idx = adjudication.get("index")
    if isinstance(idx, bool) or not isinstance(idx, int) or idx < 1:
        add(RULE_INVALID_INDEX, f"index={idx!r} 非法（必须为 >=1 的整数）")
    verdict = adjudication.get("semantic_verdict")
    if verdict not in adj.VERDICTS:
        add(RULE_INVALID_VERDICT, f"semantic_verdict={verdict!r} 非法")
        # 后续映射依赖合法 verdict，直接返回
        return violations
    rationale = str(adjudication.get("verdict_rationale") or "").strip()
    if not rationale:
        add(RULE_MISSING_RATIONALE, "verdict_rationale 为空")
    if adjudication.get("model") != REVIEWER_MODEL:
        add(RULE_WRONG_MODEL,
            f"model={adjudication.get('model')!r} != {REVIEWER_MODEL!r}")

    should_refuse = bool(input_case.get("should_refuse"))
    n_points = len(input_case.get("acceptable_answer_points") or [])
    supports = adjudication.get("answer_point_supports") or []
    if should_refuse:
        if supports:
            add(RULE_REFUSAL_SUPPORTS_NOT_EMPTY,
                f"拒答题不得携带 answer_point_supports（{len(supports)} 条）")
        ra = adjudication.get("refusal_assessment")
        expected = REFUSAL_TO_VERDICT.get(ra) if ra is not None else None
        if expected is None:
            add(RULE_REFUSAL_ASSESSMENT_MISMATCH,
                f"refusal_assessment={ra!r} 缺失或非法")
        elif verdict != expected:
            add(RULE_REFUSAL_ASSESSMENT_MISMATCH,
                f"refusal_assessment={ra} 要求 semantic_verdict={expected}，"
                f"实际 {verdict}")
    else:
        indices = [s.get("answer_point_index") if isinstance(s, dict) else None
                   for s in supports]
        if indices != list(range(n_points)):
            add(RULE_SUPPORTS_NOT_EXACT,
                f"每个答案点必须恰好一条 assessment 且 index 连续不重复："
                f"需要 {list(range(n_points))}，实际 {indices}")
        levels = [s.get("support_level") if isinstance(s, dict) else None
                  for s in supports]
        if "unsupported" in levels and verdict == "confirmed":
            add(RULE_UNSUPPORTED_WITH_CONFIRMED,
                "存在 unsupported 答案点但 semantic_verdict=confirmed")
        elif levels and "unsupported" not in levels and verdict == "reject":
            add(RULE_NO_UNSUPPORTED_WITH_REJECT,
                "全部答案点均有支持但 semantic_verdict=reject")

    if verdict == "needs_followup":
        if not any(t in rationale for t in FOLLOWUP_REASON_TERMS):
            add(RULE_FOLLOWUP_WITHOUT_REASON,
                "needs_followup 的 verdict_rationale 必须写明无法判断的"
                "具体理由")
    return violations


# ── 只读复算（fail-closed）──────────────────────────────────────────

def _read_jsonl(path: Path, label: str) -> list[dict]:
    """逐行解析 JSONL；任何非法行立即抛错（fail-closed）。"""
    out: list[dict] = []
    for n, line in enumerate(path.open(encoding="utf-8"), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise CoherenceError(f"{label} 第 {n} 行非法 JSON: {exc}")
    return out


def _compute_audit(adj_dir: Path, *, blank_path: Path, filled_path: Path,
                   chunks_path: Path, control_count: int,
                   expected_total: int, expected_confirmed: int,
                   expected_reject: int, expected_followup: int) -> dict:
    """复算盲态集合/盲包/仲裁并对 102 条逐条校验；任何漂移抛错。

    返回 material、重建盲包行、原仲裁行、违规明细与 prompt SHA。
    """
    material = adj._load_blind_material(
        blank_path, filled_path, chunks_path, control_count,
        expected_total=expected_total, expected_confirmed=expected_confirmed,
        expected_reject=expected_reject, expected_followup=expected_followup)
    order = material["order"]
    rows = [adj._blind_pack_row(material["blank_by_id"][cid],
                                material["chunk_texts"]) for cid in order]
    prompt_sha = adj._prompt_sha256(rows)

    # 盲包重建必须与现有盲包逐行一致（确定性重建证明）
    pack_path = adj_dir / "blind-input-pack.jsonl"
    if not pack_path.is_file():
        raise CoherenceError("盲包 blind-input-pack.jsonl 缺失")
    expected_pack = "\n".join(adj._line(r) for r in rows) + "\n"
    actual_pack = pack_path.open(encoding="utf-8").read()
    if actual_pack.replace("\r\n", "\n") != expected_pack:
        raise CoherenceError("盲包重建与现有 blind-input-pack.jsonl 不一致"
                             "（fail-closed）")
    # 审计侧选择清单必须与复算顺序一致
    sel_path = adj_dir / "selection-manifest.json"
    if not sel_path.is_file():
        raise CoherenceError("selection-manifest.json 缺失")
    sel = json.loads(sel_path.read_text(encoding="utf-8"))
    mapping = sel.get("mapping")
    if (not mapping or [e.get("case_id") for e in mapping] != order
            or [e.get("index") for e in mapping]
            != list(range(1, len(order) + 1))):
        raise CoherenceError("selection-manifest mapping 与复算顺序不一致"
                             "（fail-closed）")
    # 仲裁覆盖：恰好 len(order) 行、index 连续唯一
    adj_path = adj_dir / adj.ADJUDICATIONS_FILE
    if not adj_path.is_file():
        raise CoherenceError(f"{adj.ADJUDICATIONS_FILE} 缺失")
    adj_rows = _read_jsonl(adj_path, "adjudications")
    if len(adj_rows) != len(order):
        raise CoherenceError(f"adjudications coverage: {len(adj_rows)} != "
                             f"{len(order)}")
    indices = [r.get("index") for r in adj_rows]
    if indices != list(range(1, len(order) + 1)):
        raise CoherenceError(f"adjudications index 不连续或重复: {indices}")

    violations: list[dict] = []
    for i, (cid, row, arow) in enumerate(zip(order, rows, adj_rows), start=1):
        vs = validate_semantic_coherence(row, arow)
        if vs:
            blank = material["blank_by_id"][cid]
            layer = ("拒答" if blank["should_refuse"]
                     else ("跨文档" if blank.get("query_type")
                           == "cross_document" else "答案"))
            violations.append({
                "index": i, "case_id": cid,
                "role": ("control" if cid in material["controls"]
                         else "disputed"),
                "layer": layer, "rules": vs,
                "semantic_verdict": arow.get("semantic_verdict"),
                "verdict_rationale": arow.get("verdict_rationale"),
                "answer_point_supports": arow.get("answer_point_supports"),
                "refusal_assessment": arow.get("refusal_assessment"),
                "refusal_evidence": arow.get("refusal_evidence"),
            })
    return {"material": material, "order": order, "rows": rows,
            "adj_rows": adj_rows, "violations": violations,
            "prompt_sha": prompt_sha}


def _violations_sha256(violations: list[dict]) -> str:
    """违规明细（index/case_id/规则名）的规范 JSON SHA-256。"""
    sig = [{"index": v["index"], "case_id": v["case_id"],
            "rules": [r["rule"] for r in v["rules"]]}
           for v in violations]
    return adj._sha256_text(json.dumps(sig, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")))


# ── 只读审计产物 ────────────────────────────────────────────────────

def _audit_json(c: dict) -> dict:
    return {
        "task": "v2 semantic adjudication coherence audit（只读）",
        "reviewer_model": REVIEWER_MODEL,
        "prompt_sha256": c["prompt_sha"],
        "n_total": len(c["adj_rows"]),
        "n_violating": len(c["violations"]),
        "violations_sha256": _violations_sha256(c["violations"]),
        "violations": c["violations"],
        "created_by": "corpus_v2_llm_semantic_coherence.py audit",
        "note": "只读审计：未修改任何标注、盲包、chunks、manifest 或生产配置；"
                "违反 case 的定点重审产物见 coherence-recheck/",
    }


def _audit_md(c: dict) -> str:
    material = c["material"]
    order = c["order"]
    adj_rows = c["adj_rows"]
    violations = c["violations"]
    n_violations = sum(len(v["rules"]) for v in violations)
    by_rule = Counter(r["rule"] for v in violations for r in v["rules"])
    lines = [
        "# DeepSeek v4 Pro 语义仲裁一致性审计（coherence audit）", "",
        "> 只读审计：未修改任何标注、盲包、chunks、manifest 或生产配置；"
        "违反 case 的定点重审见 coherence-recheck/。", "",
        "## 一、输入与复算", "",
        f"- blank pack / llm-filled：各 {len(material['blank_by_id'])} 行；"
        f"第三轮分布 confirmed {material['n_confirmed']} / reject "
        f"{material['n_reject']} / needs_followup 0。",
        f"- 盲态输入：{len(order)} 条（{len(material['disputed'])} 争议 + "
        f"{len(material['controls'])} 对照）；盲包重建与现有 "
        "blind-input-pack.jsonl 一致；prompt SHA "
        f"{c['prompt_sha'][:16]}…。",
        f"- 仲裁输出：{len(adj_rows)} 条，index 1..{len(adj_rows)} 连续唯一。",
        "", "## 二、语义一致性契约", "",
        "- 拒答题（should_refuse=true）：no_answer / "
        "partial_topic_overlap_only → semantic_verdict=confirmed；"
        "substantive_answer_exists → reject；unclear → needs_followup；"
        "answer_point_supports 必须为空。",
        "- 可答题（should_refuse=false）：每个答案点必须恰好一条 assessment，"
        "index 连续且不重复；存在 unsupported → 不得 confirmed；全部有支持"
        "→ 不得 reject；needs_followup 必须写明无法判断的具体理由。",
        "- 每条：合法 verdict、非空 rationale、reviewer 模型名、index 与"
        "盲态输入一致。", "",
        "## 三、违反统计", "",
        f"- 总条数：{len(adj_rows)}；违反条数：{len(violations)}；"
        f"违反规则数：{n_violations}。", "",
        "| 规则 | 条数 |", "|---|---|",
    ]
    for rule, n in by_rule.most_common():
        lines.append(f"| {rule} | {n} |")
    lines += ["", "## 四、违反 case 明细", "",
              "| index | case_id | 角色 | 层 | semantic_verdict | 违反规则 |",
              "|---|---|---|---|---|---|"]
    for v in violations:
        rules = ", ".join(r["rule"] for r in v["rules"])
        lines.append(f"| {v['index']} | {v['case_id']} | {v['role']} | "
                     f"{v['layer']} | {v['semantic_verdict']} | {rules} |")
    lines += ["", "原模型输出摘录（每个违反 case）：", ""]
    for v in violations:
        lines.append(f"### index {v['index']}（{v['case_id']}，"
                     f"{v['role']} / {v['layer']}）")
        lines.append(f"- semantic_verdict: {v['semantic_verdict']}")
        lines.append(f"- verdict_rationale: {v['verdict_rationale']}")
        if v["answer_point_supports"]:
            lines.append("- answer_point_supports: " +
                         json.dumps(v["answer_point_supports"],
                                    ensure_ascii=False))
        if v["refusal_assessment"] is not None:
            lines.append(f"- refusal_assessment: {v['refusal_assessment']}")
        if v["refusal_evidence"]:
            lines.append("- refusal_evidence: " +
                         json.dumps(v["refusal_evidence"], ensure_ascii=False))
        lines.append("")
    lines += ["## 五、结论", "",
              "- 本审计为机器语义证据，未修改任何标注；违反 case 将以相同"
              "盲态输入、同一模型、temperature=0.0 定点重审（最多 3 次），"
              "提示词显式包含 verdict 与 support/refusal 映射规则；三次仍"
              "不合格按规则固定为 needs_followup 并记录失败证据。",
              "- 结论：**不得视为人工终审、人工批准或上线批准；不构成任何"
              "v2.1 进入决策。**", "",
    ]
    return "\n".join(lines) + "\n"


def audit(adj_dir: Path, *, blank_path: Path = DEFAULT_BLANK_PACK,
          filled_path: Path = DEFAULT_FILLED_PACK,
          chunks_path: Path = DEFAULT_CHUNKS,
          control_count: int = adj.CONTROL_COUNT,
          expected_total: int = EXPECTED_TOTAL,
          expected_confirmed: int = EXPECTED_CONFIRMED,
          expected_reject: int = EXPECTED_REJECT,
          expected_followup: int = EXPECTED_FOLLOWUP) -> dict:
    """只读一致性审计：全部校验通过后才写审计产物。"""
    c = _compute_audit(adj_dir, blank_path=blank_path,
                       filled_path=filled_path, chunks_path=chunks_path,
                       control_count=control_count,
                       expected_total=expected_total,
                       expected_confirmed=expected_confirmed,
                       expected_reject=expected_reject,
                       expected_followup=expected_followup)
    audit_data = _audit_json(c)
    audit_data["inputs"] = {
        "blank_pack": {"sha256": adj._sha256_file(blank_path)},
        "filled_pack": {"sha256": adj._sha256_file(filled_path)},
        "chunks": {"sha256": adj._sha256_file(chunks_path)},
        "blind_input_pack": {"sha256": adj._sha256_file(
            adj_dir / "blind-input-pack.jsonl")},
        "adjudications": {"sha256": adj._sha256_file(
            adj_dir / adj.ADJUDICATIONS_FILE),
            "rows": len(c["adj_rows"])},
        "selection_manifest": {"sha256": adj._sha256_file(
            adj_dir / "selection-manifest.json")},
    }
    (adj_dir / "coherence-audit.json").write_text(
        json.dumps(audit_data, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    (adj_dir / "coherence-report.md").write_text(
        _audit_md(c), encoding="utf-8")
    return {"n_total": len(c["adj_rows"]),
            "n_violating": len(c["violations"]),
            "violations": c["violations"]}


# ── 定点重审 ─────────────────────────────────────────────────────────

def _recheck_case(row: dict, case_id: str, index: int, llm_fn: Callable,
                  model: str, max_attempts: int) -> dict:
    """对单个违规 case 最多 max_attempts 次重审；返回记录（含失败证据）。

    每次 attempt 都是完整的新调用（不追加纠正消息）；输出必须同时满足
    结构解析与一致性契约。三次不合格返回 accepted=False。
    """
    messages = [{"role": "system", "content": RECON_PROMPT},
                {"role": "user", "content": adj._line(row)}]
    chunk_ids = {ch["chunk_id"] for ch in row["chunks"]}
    n_points = len(row["acceptable_answer_points"])
    attempts: list[dict] = []
    retries_total = 0
    for attempt_no in range(1, max_attempts + 1):
        content, retries = adj._llm_content(llm_fn, messages, model, case_id)
        retries_total += retries
        parsed = adj._parse_adjudication(
            content, should_refuse=row["should_refuse"],
            chunk_ids=chunk_ids, n_points=n_points)
        if parsed is None:
            vs = [{"rule": RULE_UNPARSEABLE,
                   "detail": f"输出无法解析（{content[:120]!r}）"}]
        else:
            # index/model 是编排层元数据（原仲裁行同构），由编排层附加
            candidate = dict(parsed)
            candidate["index"] = index
            candidate["model"] = model
            vs = validate_semantic_coherence(row, candidate)
        attempts.append({"attempt": attempt_no, "retries_used": retries,
                         "parsed": parsed, "violations": vs,
                         "raw_content": content})
        if parsed is not None and not vs:
            return {"case_id": case_id, "index": index, "accepted": True,
                    "attempt_count": attempt_no, "attempts": attempts,
                    "retries_used": retries_total, "parsed": parsed}
    return {"case_id": case_id, "index": index, "accepted": False,
            "attempt_count": max_attempts, "attempts": attempts,
            "retries_used": retries_total, "parsed": None}


def _merged_row_from_parsed(index: int, p: dict, model: str,
                            retries: int, attempts: int) -> dict:
    return {"index": index, "semantic_verdict": p["semantic_verdict"],
            "verdict_rationale": p["verdict_rationale"],
            "answer_point_supports": p["answer_point_supports"],
            "refusal_assessment": p["refusal_assessment"],
            "refusal_evidence": p["refusal_evidence"],
            "model": model, "retries_used": retries, "parse_retries": 0,
            "source": "recheck", "recheck_attempts": attempts,
            "fixed_by_rule": False}


def _fixed_row(index: int, model: str, max_attempts: int) -> dict:
    """3 次重审失败后按规则固定为 needs_followup（唯一允许的代码改写）。"""
    return {"index": index, "semantic_verdict": "needs_followup",
            "verdict_rationale": FIXED_RATIONALE,
            "answer_point_supports": [], "refusal_assessment": None,
            "refusal_evidence": [], "model": model,
            "retries_used": 0, "parse_retries": 0,
            "source": "recheck", "recheck_attempts": max_attempts,
            "fixed_by_rule": True}


def recheck_and_merge(adj_dir: Path, *, llm_fn: Callable | None = None,
                      model: str = REVIEWER_MODEL,
                      max_attempts: int = RECON_MAX_ATTEMPTS,
                      blank_path: Path = DEFAULT_BLANK_PACK,
                      filled_path: Path = DEFAULT_FILLED_PACK,
                      chunks_path: Path = DEFAULT_CHUNKS,
                      control_count: int = adj.CONTROL_COUNT,
                      expected_total: int = EXPECTED_TOTAL,
                      expected_confirmed: int = EXPECTED_CONFIRMED,
                      expected_reject: int = EXPECTED_REJECT,
                      expected_followup: int = EXPECTED_FOLLOWUP) -> dict:
    """对违规 case 定点重审，合并 102 条并重算 comparison report。

    所有重审成功（或按规则固定）后才写 rechecks / merged /
    comparison-report / manifest；任何漂移抛错且不产出。
    """
    if model in adj.FORBIDDEN_MODELS:
        raise CoherenceError(f"forbidden model: {model}")
    if model != REVIEWER_MODEL:
        raise CoherenceError(f"reviewer_model must be {REVIEWER_MODEL!r}, "
                             f"got {model!r}")
    c = _compute_audit(adj_dir, blank_path=blank_path,
                       filled_path=filled_path, chunks_path=chunks_path,
                       control_count=control_count,
                       expected_total=expected_total,
                       expected_confirmed=expected_confirmed,
                       expected_reject=expected_reject,
                       expected_followup=expected_followup)
    material = c["material"]
    order = c["order"]
    rows = c["rows"]
    adj_rows = c["adj_rows"]
    violations = c["violations"]
    # 已写审计产物必须与复算一致（fail-closed）
    audit_path = adj_dir / "coherence-audit.json"
    if not audit_path.is_file():
        raise CoherenceError("coherence-audit.json 缺失：请先运行 audit")
    saved = json.loads(audit_path.read_text(encoding="utf-8"))
    if (saved.get("n_total") != len(adj_rows)
            or saved.get("n_violating") != len(violations)
            or saved.get("violations_sha256")
            != _violations_sha256(violations)):
        raise CoherenceError("coherence-audit.json 与复算结果不一致"
                             "（fail-closed）")
    if llm_fn is None:
        from src.llm_gateway import llm_call  # noqa: PLC0415
        llm_fn = llm_call

    # 重审提示词 SHA：system + 违规 case 的盲包行（确定性）
    recheck_payload = {"system": RECON_PROMPT,
                       "cases": [rows[v["index"] - 1] for v in violations]}
    recheck_prompt_sha = adj._sha256_text(
        json.dumps(recheck_payload, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")))

    merged = [dict(r, source="original", recheck_attempts=0)
              for r in adj_rows]
    rechecks: list[dict] = []
    changed: list[dict] = []
    transport_total = 0
    transport_max = 0
    for v in violations:
        i, cid = v["index"], v["case_id"]
        rec = _recheck_case(rows[i - 1], cid, i, llm_fn, model, max_attempts)
        transport_total += rec["retries_used"]
        transport_max = max(transport_max, rec["retries_used"])
        old = adj_rows[i - 1]["semantic_verdict"]
        if rec["accepted"]:
            merged[i - 1] = _merged_row_from_parsed(
                i, rec["parsed"], model, rec["retries_used"],
                rec["attempt_count"])
            new = rec["parsed"]["semantic_verdict"]
        else:
            merged[i - 1] = _fixed_row(i, model, max_attempts)
            new = "needs_followup"
        changed.append({"case_id": cid, "old": old, "new": new})
        rechecks.append({
            "case_id": cid, "index": i, "accepted": rec["accepted"],
            "attempt_count": rec["attempt_count"],
            "attempts": rec["attempts"],
            "final": {"semantic_verdict": merged[i - 1]["semantic_verdict"],
                      "source": merged[i - 1]["source"]},
        })
        print(f"rechecked {i}/{len(order)} {cid} "
              f"({rec['attempt_count']}/{max_attempts} attempts) -> {new}",
              flush=True)

    # 合并 fail-closed：覆盖完整、index 连续、非固定行全部通过契约
    if [m["index"] for m in merged] != list(range(1, len(order) + 1)):
        raise CoherenceError("merged coverage/index drift (fail-closed)")
    for m in merged:
        if not m.get("fixed_by_rule"):
            vs = validate_semantic_coherence(rows[m["index"] - 1], m)
            if vs:
                raise CoherenceError(f"merged 行 index {m['index']} 违反契约"
                                     f": {vs}")

    merged_by_cid = {cid: m for cid, m in zip(order, merged)}
    comparison = adj._compute_comparison(material, merged_by_cid)

    rd = adj_dir / "coherence-recheck"
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "rechecks.jsonl").write_text(
        "\n".join(adj._line(r) for r in rechecks) + "\n", encoding="utf-8")
    (rd / "merged-adjudications.jsonl").write_text(
        "\n".join(adj._line(m) for m in merged) + "\n", encoding="utf-8")
    md = adj._comparison_md(material, merged_by_cid, comparison)
    md = md.replace(
        "> 本报告为机器语义仲裁证据，",
        "> 本报告为**一致性重审后合并结果**的重算版本（原始 102 条仲裁见"
        "父目录 comparison-report.md，\n> 重审记录见 rechecks.jsonl）。\n>\n"
        "> 本报告为机器语义仲裁证据，")
    (rd / "comparison-report.md").write_text(md, encoding="utf-8")

    manifest = _manifest_dict(
        material, c, adj_dir, blank_path, filled_path, chunks_path,
        audit_path, recheck_prompt_sha, rechecks, merged, changed,
        comparison, rd, max_attempts)
    (rd / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return {"n_total": len(order), "n_violating": len(violations),
            "n_merged": len(merged),
            "merge": {"n_changed": len(changed),
                      "n_unchanged": len(order) - len(changed)},
            "comparison": comparison}


# ── manifest ─────────────────────────────────────────────────────────

def _manifest_dict(material: dict, c: dict, adj_dir: Path,
                   blank_path: Path, filled_path: Path, chunks_path: Path,
                   audit_path: Path, recheck_prompt_sha: str,
                   rechecks: list[dict], merged: list[dict],
                   changed: list[dict], comparison: dict, out_dir: Path,
                   max_attempts: int) -> dict:
    """重审 manifest：模型名、双 prompt SHA、输入/输出 SHA、重试与前后差异。

    manifest.json 自身条目的 sha256 为其内容摘要（去掉 outputs 中自身
    条目后的规范 JSON），避免自引用环。
    """
    outputs = {name: {"sha256": adj._sha256_file(out_dir / name)}
               for name in RECHECK_OUTPUT_FILES if name != "manifest.json"}
    body = {
        "task": "v2 semantic adjudication coherence recheck",
        "reviewer_model": REVIEWER_MODEL,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "original_prompt_sha256": c["prompt_sha"],
        "recheck_prompt_sha256": recheck_prompt_sha,
        "recheck_max_attempts": max_attempts,
        "selection": {
            "algorithm": "sha256('v2-semantic-adjudication-v1:' + case_id) "
                         "升序排序，取前 20 条",
            "control_count": len(material["controls"]),
            "disputed_count": len(material["disputed"]),
            "total_cases": len(material["order"]),
        },
        "inputs": {
            "blank_pack": {"sha256": adj._sha256_file(blank_path)},
            "filled_pack": {"sha256": adj._sha256_file(filled_path)},
            "chunks": {"sha256": adj._sha256_file(chunks_path)},
            "blind_input_pack": {"sha256": adj._sha256_file(
                adj_dir / "blind-input-pack.jsonl")},
            "adjudications": {"sha256": adj._sha256_file(
                adj_dir / adj.ADJUDICATIONS_FILE),
                "rows": len(c["adj_rows"])},
            "selection_manifest": {"sha256": adj._sha256_file(
                adj_dir / "selection-manifest.json")},
        },
        "audit": {
            "n_total": len(c["adj_rows"]),
            "n_violating": len(c["violations"]),
            "violations_sha256": _violations_sha256(c["violations"]),
            "audit_files": {
                "coherence-audit.json": {
                    "sha256": adj._sha256_file(audit_path)},
                "coherence-report.md": {"sha256": adj._sha256_file(
                    adj_dir / "coherence-report.md")},
            },
        },
        "rechecks": {
            "n_cases": len(rechecks),
            "attempts_total": sum(r["attempt_count"] for r in rechecks),
            "attempts_max": max((r["attempt_count"] for r in rechecks),
                                default=0),
            "transport_retries_total": sum(
                a["retries_used"] for r in rechecks for a in r["attempts"]),
            "transport_retries_max": max(
                (a["retries_used"] for r in rechecks for a in r["attempts"]),
                default=0),
            "unparseable_total": sum(
                1 for r in rechecks
                for a in r["attempts"]
                if any(v["rule"] == RULE_UNPARSEABLE for v in a["violations"])),
            "fixed_needs_followup": [r["case_id"] for r in rechecks
                                     if not r["accepted"]],
        },
        "merge": {
            "rule": "违规 case 以重审结果替换（模型输出）；三次不合格按"
                    "规则固定为 needs_followup 并记录失败证据",
            "n_changed": len(changed),
            "n_unchanged": len(merged) - len(changed),
            "changed": changed,
        },
        "outputs": outputs,
        "comparison": comparison,
        "provider_note": adj.PROVIDER_NOTE,
        "created_by": "corpus_v2_llm_semantic_coherence.py recheck_and_merge",
    }
    outputs["manifest.json"] = {
        "sha256": adj._sha256_text(json.dumps(body, ensure_ascii=False,
                                              sort_keys=True,
                                              separators=(",", ":"))),
        "note": "内容摘要（去掉 outputs 中自身条目后的规范 JSON）",
    }
    body["outputs"] = outputs
    return body


# ── CLI ──────────────────────────────────────────────────────────────

def _flag(args: list[str], name: str, default: str | None) -> str | None:
    if name in args:
        return args[args.index(name) + 1]
    return default


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    adj_dir = Path(_flag(args, "--adj-dir", str(DEFAULT_ADJ_DIR))
                   or str(DEFAULT_ADJ_DIR))
    try:
        a = audit(adj_dir)
        print(f"coherence audit: {a['n_violating']}/{a['n_total']} "
              f"violating -> {adj_dir / 'coherence-audit.json'}")
        r = recheck_and_merge(adj_dir)
        print(f"coherence recheck: {r['n_merged']} merged, "
              f"{r['merge']['n_changed']} changed -> "
              f"{adj_dir / 'coherence-recheck'}")
        return 0
    except (CoherenceError, adj.AdjudicationError) as exc:
        print(f"FAILED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
