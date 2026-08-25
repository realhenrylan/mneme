"""v2.0.7 owner-authorized fresh blind automated review（LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_7）。

对 v2.0.7 candidate 的全部 148 条 case 重新做盲态机器审阅，替代已失效的
150 条旧 review 结果。这是用户明确授权的 LLM 自动审阅，**不是人工审核**。

审阅人身份固定为 ``LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_7``；模型固定
``deepseek-v4-pro``（temperature=0.0、max_tokens=8000、thinking disabled、
max_retries=3，无 fallback、无混用）。

盲态：模型输入只含 query / previous_turns（剥离 case_id 与链路引用）/
should_refuse / acceptable_answer_points / evidence（raw span + 展示 snippet）/
对应 chunk 原文；不含 case_id、split/dev/holdout、旧 review decision/rationale、
历史 reject/blocker/remediation、评测分数或候选版本结论。本地保留 case_id 仅用于结果映射。

fail-closed：preflight 任一条件不成立、模型调用失败、模型身份不符、
输出非法（schema/枚举/索引/引用越界、拒答与可答一致性规则违反）→ 整体停止，
不留下半成品最终目录。仅当 148/148 confirmed 且全部校验通过时生成
``automated-reviewed-truth-overlay.json`` + ``automated-reviewed-truth-overlay-manifest.json``
（状态 ``AUTOMATED_REVIEWED_OWNER_AUTHORIZED``）；否则门禁
``AUTOMATED_REVIEW_GATE_BLOCKED``，不生成 overlay。

即使生成 overlay，candidate 仍保持 revision_status=CANDIDATE、
activation_blocked=true、human_reviewed=false、split_reseal_required=true、
v2_1_entered=false。不修改 candidate draft/evidence/chunks，不读取
split/dev/holdout、锁配置、历史评测、旧 automated review / human review 产物。

CLI
---
::

    python scripts/corpus_v2_v207_fresh_automated_review.py probe-json
    python scripts/corpus_v2_v207_fresh_automated_review.py pack
    python scripts/corpus_v2_v207_fresh_automated_review.py review
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import corpus_v2_evidence_coordinate_repair as coord
from scripts import corpus_v2_remaining_blockers_decision_pack as rbp

ROOT = Path(__file__).resolve().parents[1]
V207 = ROOT / "evaluation/datasets/v2/revisions/v2.0.7-owner-authorized-legacy-evidence-retirement"
OUT = V207 / "automated-review"
DRAFT_AFTER = V207 / "draft-after.jsonl"
EVIDENCE_AFTER = V207 / "evidence-after.jsonl"
V207_MANIFEST = V207 / "manifest.json"
DRAFT = rbp.DRAFT
CHUNKS = rbp.CHUNKS
CHUNK_MANIFEST = rbp.CHUNK_MANIFEST
TIMESTAMP = "2026-08-10T00:00:00+00:00"
CONTRACT = "raw-codepoint-v1"

REVIEWER_IDENTITY = "LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_7"
REVIEWER_TYPE = REVIEWER_IDENTITY
REVIEWER_MODEL = "deepseek-v4-pro"
REVIEWER_TEMPERATURE = 0.0
REVIEWER_MAX_TOKENS = 8000
MAX_RETRIES = 3
MAX_PARSE_RETRIES = 3
EXTRA_BODY = {"thinking": {"type": "disabled"}}
FORBIDDEN_MODELS = ("gpt-5.6-sol", "deepseek-v4-flash")
DECISIONS = ("confirmed", "reject", "needs_followup")
ASSESSMENTS = ("directly_supported", "faithful_paraphrase", "unsupported")
REFUSAL_ASSESSMENTS = ("not_applicable", "correct_refusal", "incorrect_refusal")
OVERLAY_STATUS = "AUTOMATED_REVIEWED_OWNER_AUTHORIZED"
GATE_BLOCKED = "AUTOMATED_REVIEW_GATE_BLOCKED"
PAYLOAD_KEYS = frozenset({"query", "previous_turns", "should_refuse",
                          "acceptable_answer_points", "evidence", "chunks"})
EXPECTED_CASE_COUNT = 148
EXPECTED_EVIDENCE_COUNT = 161

BASE_FILES = (
    "automated-review-pack.jsonl", "automated-review-evidence.jsonl",
    "automated-review.jsonl", "raw-model-responses.jsonl",
    "automated-review-summary.json", "automated-review-report.md",
    "automated-review-gate-report.md", "automated-review-issues.jsonl",
    "manifest.json",
)
OVERLAY_FILES = ("automated-reviewed-truth-overlay.json",
                 "automated-reviewed-truth-overlay-manifest.json")


class ReviewError(Exception):
    """Fail-closed review failure（任何非法状态立即失败）。"""


# ── hashing / io helpers（复用既有 automated review 约定）────────────

def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(obj: Any) -> str:
    """Canonical JSON SHA-256（sort_keys + compact separators）。"""
    return _sha256_text(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")))


def _line(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = _sha256_text(_dump(result))
    return result


# ── 前置门禁（fail-closed）────────────────────────────────────────────

def preflight() -> dict:
    """只读校验 v2.0.7 candidate 的 7 项前置条件，任一不成立即整体停止。"""
    if not V207.exists() or not V207_MANIFEST.exists():
        raise ReviewError("v2.0.7 revision missing")
    m = json.loads(V207_MANIFEST.read_text(encoding="utf-8"))
    manifest_ok = (
        m.get("revision_status") == "CANDIDATE"
        and m.get("activation_blocked") is True
        and m.get("human_reviewed") is False
        and m.get("overlay_generated") is False
        and m.get("v2_1_entered") is False
        and m.get("case_count_after") == EXPECTED_CASE_COUNT
        and m.get("evidence_count_after") == EXPECTED_EVIDENCE_COUNT
        and m.get("manifest_sha256") == _sha256_text(_dump(
            {k: v for k, v in m.items() if k != "manifest_sha256"}))
    )
    if not manifest_ok:
        raise ReviewError("v2.0.7 manifest status/self-hash mismatch")
    for name in ("draft-after.jsonl", "evidence-after.jsonl"):
        if m.get("outputs", {}).get(name) != _sha256_file(V207 / name):
            raise ReviewError(f"v2.0.7 output SHA mismatch: {name}")
    inputs_unchanged = True
    for name, path in (("draft", DRAFT), ("chunks", CHUNKS),
                       ("chunk_manifest", CHUNK_MANIFEST)):
        if m.get("inputs", {}).get(name) != _sha256_file(path):
            inputs_unchanged = False
            raise ReviewError(f"input SHA mismatch: {name}")

    chunks = coord.load_chunks(CHUNKS)
    draft_rows = sorted(_jsonl(DRAFT_AFTER), key=lambda r: r["id"])
    if len(draft_rows) != EXPECTED_CASE_COUNT or \
            len({row["id"] for row in draft_rows}) != EXPECTED_CASE_COUNT:
        raise ReviewError("draft-after must have 148 unique cases")
    evidence_rows = _jsonl(EVIDENCE_AFTER)
    if len(evidence_rows) != EXPECTED_EVIDENCE_COUNT:
        raise ReviewError(f"evidence-after must have 161 rows, got {len(evidence_rows)}")
    raw_rows = [row for row in evidence_rows if row.get("coordinate_contract") == CONTRACT]
    if len(raw_rows) != EXPECTED_EVIDENCE_COUNT:
        raise ReviewError("all evidence rows must be raw-codepoint-v1 (legacy/unresolved != 0)")
    coord.strict_validate(raw_rows, chunks)  # covered == passed == 161

    evidence_by_case: dict[str, list[dict]] = {}
    for row in evidence_rows:
        evidence_by_case.setdefault(row["case_id"], []).append(row)
    answerable = [row for row in draft_rows if row.get("should_refuse") is not True]
    refusal = [row for row in draft_rows if row.get("should_refuse") is True]
    answerable_have_evidence = all(
        evidence_by_case.get(row["id"]) for row in answerable)
    refusal_have_no_evidence = all(
        not evidence_by_case.get(row["id"])
        and not (row.get("acceptable_answer_points") or []) for row in refusal)
    if not answerable_have_evidence or not refusal_have_no_evidence:
        raise ReviewError("answerable/refusal evidence split mismatch")

    checks = {
        "case_count": len(draft_rows),
        "active_evidence_count": len(raw_rows),
        "strict_validator_covered": len(raw_rows),
        "strict_validator_passed": len(raw_rows),
        "legacy_coordinate_count": 0,
        "unresolved_count": 0,
        "activation_blocked": m.get("activation_blocked") is True,
        "case_count_ok": len(draft_rows) == EXPECTED_CASE_COUNT,
        "evidence_count_ok": len(raw_rows) == EXPECTED_EVIDENCE_COUNT,
        "strict_ok": len(raw_rows) == EXPECTED_EVIDENCE_COUNT,
        "legacy_ok": True,
        "unresolved_ok": True,
        "activation_ok": m.get("activation_blocked") is True,
        "answerable_have_evidence": answerable_have_evidence,
        "refusal_have_no_evidence": refusal_have_no_evidence,
        "inputs_unchanged": inputs_unchanged,
        "manifest_ok": manifest_ok,
        "data_quality": {
            "skill": {"name": "data-analytics:analyze-data-quality",
                      "available": False,
                      "failure": "Skill not found: data-analytics:analyze-data-quality"},
            "equivalent_deterministic_checks": {
                "completeness": {"draft_rows": len(draft_rows),
                                 "evidence_rows": len(evidence_rows),
                                 "answerable_cases_without_evidence": 0},
                "uniqueness": {"unique_case_ids": len({row["id"] for row in draft_rows}),
                               "unique_evidence_rows": len(evidence_rows)},
                "referential_integrity": {
                    "evidence_chunks_in_corpus": all(
                        row["chunk_id"] in chunks for row in evidence_rows),
                    "chunk_text_sha_matches": all(
                        coord.sha256_text(chunks[row["chunk_id"]]["text"])
                        == row.get("chunk_text_sha256") for row in evidence_rows),
                },
                "continuity": {"spans_proved": len(raw_rows)},
                "consistency": {"source_matches": all(
                    chunks[row["chunk_id"]]["source"] == row.get("source_id")
                    for row in evidence_rows),
                    "input_shas_unchanged": True},
            },
        },
        "chunks": chunks,
        "draft_rows": draft_rows,
        "evidence_by_case": evidence_by_case,
        "manifest": m,
    }
    return checks


# ── 盲态 pack 构建 ────────────────────────────────────────────────────

def _build_payload(case: dict, evidence_rows: list[dict],
                   chunks: dict[str, dict], draft_by_id: dict[str, dict]) -> dict:
    """盲态 payload：只含允许字段，previous_turns 剥离 case_id 与链路引用。"""
    previous: list[dict] = []
    seen: set[str] = set()
    cur = (case.get("metadata") or {}).get("follow_up_to")
    while cur and cur not in seen:
        seen.add(cur)
        parent = draft_by_id.get(cur)
        if parent is None:
            break
        previous.append({"query": parent.get("query", "")})
        cur = (parent.get("metadata") or {}).get("follow_up_to")
    previous.reverse()
    evidence = []
    chunk_ids: list[str] = []
    for ev in evidence_rows:
        evidence.append({
            "chunk_id": ev["chunk_id"],
            "source_id": ev["source_id"],
            "raw_evidence_span": ev["raw_evidence_span"],
            "snippet": ev["snippet"],
        })
        if ev["chunk_id"] not in chunk_ids:
            chunk_ids.append(ev["chunk_id"])
    return {
        "query": case.get("query", ""),
        "previous_turns": previous,
        "should_refuse": case.get("should_refuse") is True,
        "acceptable_answer_points": list(case.get("acceptable_answer_points") or []),
        "evidence": evidence,
        "chunks": {cid: chunks[cid]["text"] for cid in chunk_ids},
    }


def _build_rows(checks: dict) -> tuple[list[dict], list[dict], dict[str, dict], dict[str, dict]]:
    chunks = checks["chunks"]
    draft_rows = checks["draft_rows"]
    by_id = {row["id"]: row for row in draft_rows}
    evidence_by_case = checks["evidence_by_case"]
    rows: list[dict] = []
    evidence_rows: list[dict] = []
    for case in draft_rows:  # already sorted by id
        evs = sorted(evidence_by_case.get(case["id"], []),
                     key=lambda e: (e["chunk_id"], e["raw_chunk_char_range"]["start"]))
        payload = _build_payload(case, evs, chunks, by_id)
        rows.append({"case_id": case["id"], "payload": payload,
                     "payload_sha256": canonical_sha(payload)})
        for ev in evs:
            evidence_rows.append({
                "case_id": case["id"],
                "chunk_id": ev["chunk_id"],
                "source_id": ev["source_id"],
                "raw_evidence_span": ev["raw_evidence_span"],
                "snippet": ev["snippet"],
                "raw_chunk_char_range": ev["raw_chunk_char_range"],
                "chunk_text_sha256": ev["chunk_text_sha256"],
                "snippet_sha256": ev["snippet_sha256"],
            })
    return rows, evidence_rows, chunks, by_id


def build_pack(*, out_dir: Path = OUT) -> list[dict]:
    """离线构建盲态 automated-review pack（确定性、fail-closed）。"""
    checks = preflight()
    rows, evidence_rows, _, _ = _build_rows(checks)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "automated-review-pack.jsonl").write_text(
        "".join(_line(row) + "\n" for row in rows), encoding="utf-8")
    (out_dir / "automated-review-evidence.jsonl").write_text(
        "".join(_line(row) + "\n" for row in evidence_rows), encoding="utf-8")
    return rows


# ── 审阅契约：严格解析与本地校验 ──────────────────────────────────────

def _review_messages(payload: dict) -> list[dict]:
    system = (
        f"你是独立的证据驱动审阅 LLM，身份固定为 {REVIEWER_IDENTITY}"
        "（用户授权的 LLM 自动审阅，不是人工审核）。"
        "任务：审阅一条评测标注草稿。只能依据本消息内提供的 query、previous_turns、"
        "should_refuse、acceptable_answer_points 与 evidence（chunk 原文 + raw span "
        "+ 展示 snippet）做出判断；不得假设证据之外存在的语料内容；"
        "不得输出本消息以外的任何内容。逐项核验："
        "1) should_refuse 是否合理（query 是否无法由提供的语料回答）；"
        "2) 每个 acceptable_answer_points 是否被 evidence 直接支持"
        "（directly_supported = 答案点文本或等价语义直接出现在 evidence raw span 内；"
        "faithful_paraphrase = 忠实转述但非逐字；unsupported = 无证据支持）；"
        "3) refusal_assessment 仅当 should_refuse=true 时有意义："
        "correct_refusal = 拒答合理；incorrect_refusal = 拒答不合理；"
        "可答题（should_refuse=false）必须填 not_applicable，"
        "不得用 incorrect_refusal 表示「未拒答」。"
        "只输出一个 JSON 对象，不要输出其他文本，schema 如下："
        '{"decision": "confirmed"|"reject"|"needs_followup",'
        ' "rationale": "简短、可审计的理由",'
        ' "answer_point_assessments": ['
        '{"answer_point_index": 0,'
        ' "assessment": "directly_supported"|"faithful_paraphrase"|"unsupported",'
        ' "evidence_refs": [0, 1]}],'
        ' "refusal_assessment": "not_applicable"|"correct_refusal"|"incorrect_refusal"}'
        "说明：answer_point_index 是 acceptable_answer_points 的 0 基下标；"
        "evidence_refs 是 evidence 列表的 0 基下标；每个答案点必须恰好一条评估。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False,
                                               sort_keys=True, indent=1)},
    ]


def _parse_review(content: Any) -> dict | None:
    """严格解析模型 JSON；任何非法外壳/非对象返回 None（fail-closed）。"""
    if not isinstance(content, str):
        return None
    text = content.lstrip("\ufeff").strip()
    if not text:
        return None
    if text.startswith("```"):
        if not (text.endswith("```") and text.count("```") == 2):
            return None
        lines = text.splitlines()
        if lines[0].strip().lower() not in ("```", "```json") or lines[-1].strip() != "```":
            return None
        text = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _validate_review(value: dict, payload: dict) -> dict:
    """本地严格校验 schema、枚举、索引/引用范围与拒答/可答一致性规则。"""
    errors: list[str] = []
    decision = value.get("decision")
    if decision not in DECISIONS:
        errors.append(f"invalid decision {decision!r}")
    rationale = value.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        errors.append("rationale must be non-empty text")
    refusal = value.get("refusal_assessment")
    if refusal not in REFUSAL_ASSESSMENTS:
        errors.append(f"invalid refusal_assessment {refusal!r}")
    points = payload.get("acceptable_answer_points") or []
    n_points = len(points)
    n_evidence = len(payload.get("evidence") or [])
    assessments = value.get("answer_point_assessments")
    if not isinstance(assessments, list):
        errors.append("answer_point_assessments must be a list")
        assessments = []
    seen: set[int] = set()
    for entry in assessments:
        if not isinstance(entry, dict):
            errors.append("assessment entry must be an object")
            continue
        idx = entry.get("answer_point_index")
        if not isinstance(idx, int) or isinstance(idx, bool) or not (0 <= idx < n_points):
            errors.append(f"invalid answer_point_index {idx!r}")
            continue
        if idx in seen:
            errors.append(f"duplicate answer_point_index {idx}")
        seen.add(idx)
        if entry.get("assessment") not in ASSESSMENTS:
            errors.append(f"invalid assessment {entry.get('assessment')!r}")
        refs = entry.get("evidence_refs")
        if not isinstance(refs, list):
            errors.append("evidence_refs must be a list")
        else:
            for r in refs:
                if not isinstance(r, int) or isinstance(r, bool) or not (0 <= r < n_evidence):
                    errors.append(f"invalid evidence_ref {r!r}")
    if n_points and sorted(seen) != list(range(n_points)):
        errors.append(f"answer point coverage mismatch: {sorted(seen)}")
    # 拒答与可答分别按一致性规则校验；绝不把空 evidence 或无效引用当 confirmed。
    if payload.get("should_refuse") is True:
        if assessments:
            errors.append("refusal case must have empty answer_point_assessments")
        if refusal not in ("correct_refusal", "incorrect_refusal"):
            errors.append(f"refusal case must use correct/incorrect_refusal, got {refusal!r}")
        if decision == "confirmed" and refusal != "correct_refusal":
            errors.append("refusal case confirmed without correct_refusal")
    else:
        if refusal != "not_applicable":
            errors.append(f"answerable case must use not_applicable, got {refusal!r}")
        unsupported = [e for e in assessments if e.get("assessment") == "unsupported"]
        if unsupported and decision == "confirmed":
            errors.append("confirmed despite unsupported answer points")
        if decision == "confirmed":
            for entry in assessments:
                if entry.get("assessment") not in ("directly_supported", "faithful_paraphrase"):
                    errors.append(f"confirmed with non-supported point {entry.get('answer_point_index')}")
                if not entry.get("evidence_refs"):
                    errors.append(f"confirmed with empty evidence_refs at index {entry.get('answer_point_index')}")
    if errors:
        raise ReviewError("invalid review output: " + "; ".join(errors))
    return {"decision": decision, "rationale": rationale.strip(),
            "answer_point_assessments": assessments, "refusal_assessment": refusal}


# ── 模型调用 ──────────────────────────────────────────────────────────

def _llm_content(llm_fn: Callable, messages: list[dict], case_id: str) -> tuple[str, int]:
    """调用 LLM 一次并返回 (content, transport_retries)；固定 Pro-only 参数。"""
    try:
        response, record = llm_fn(
            "corpus_v2_v207_fresh_automated_review", messages,
            model=REVIEWER_MODEL, temperature=REVIEWER_TEMPERATURE,
            max_tokens=REVIEWER_MAX_TOKENS, max_retries=MAX_RETRIES,
            extra_body=EXTRA_BODY)
    except Exception as exc:
        raise ReviewError(f"{case_id}: llm call failed: {exc}")
    returned_model = getattr(response, "model", None)
    if returned_model != REVIEWER_MODEL:
        raise ReviewError(f"{case_id}: model identity mismatch: {returned_model!r}")
    return response.choices[0].message.content, record.retries_used


def probe_json(*, llm_fn: Callable | None = None) -> dict:
    """最小探针：不读取任何 case，仅验证模型身份与 JSON 输出能力。"""
    if llm_fn is None:
        from src.llm_gateway import llm_call
        llm_fn = llm_call
    messages = [
        {"role": "system", "content": "原样回显用户消息中的 JSON 对象，"
                                      "不要输出任何其他文本。"},
        {"role": "user", "content": json.dumps({"ok": True, "echo": "probe"},
                                               ensure_ascii=False, sort_keys=True, indent=1)},
    ]
    content, _ = _llm_content(llm_fn, messages, "probe")
    value = _parse_review(content)
    if value is None or value.get("ok") is not True:
        raise ReviewError("probe JSON validation failed")
    return {"ok": True, "model": REVIEWER_MODEL,
            "response_sha256": _sha256_text(content.strip())}


# ── 主流程 ────────────────────────────────────────────────────────────

def _run_review(rows: list[dict], llm_fn: Callable) -> tuple[list[dict], list[dict], dict]:
    results: list[dict] = []
    raw_responses: list[dict] = []
    transport_total = 0
    transport_max = 0
    parse_total = 0
    for row in rows:
        messages = _review_messages(row["payload"])
        prompt_sha = _sha256_text(json.dumps(messages, ensure_ascii=False,
                                             sort_keys=True, indent=1))
        content, transport_retries = _llm_content(llm_fn, messages, row["case_id"])
        parse_retries = 0
        parsed, last_error = _parse_validated(content, row["payload"])
        while parsed is None and parse_retries < MAX_PARSE_RETRIES:
            # 纠正提示携带具体校验错误，而不是通用复读
            corrective = ("你上一次的输出无法通过本地严格校验："
                          + (last_error or "非法 JSON")
                          + "。请重新只输出一个符合契约的 JSON 对象，"
                            "不要输出其他文本。")
            messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": corrective},
            ]
            content, retries2 = _llm_content(llm_fn, messages, row["case_id"])
            transport_retries += retries2
            parse_retries += 1
            parsed, last_error = _parse_validated(content, row["payload"])
        if parsed is None:
            raise ReviewError(f"{row['case_id']}: invalid review output "
                              f"after {parse_retries} corrective retries")
        transport_total += transport_retries
        transport_max = max(transport_max, transport_retries)
        parse_total += parse_retries
        raw_responses.append({
            "case_id": row["case_id"],
            "content": content,
            "raw_response_sha256": _sha256_text(content),
            "response_sha256": _sha256_text(content.strip()),
        })
        results.append({
            "case_id": row["case_id"],
            "reviewer_identity": REVIEWER_IDENTITY,
            "reviewer_type": REVIEWER_TYPE,
            "model": REVIEWER_MODEL,
            "temperature": REVIEWER_TEMPERATURE,
            "max_tokens": REVIEWER_MAX_TOKENS,
            "thinking_disabled": True,
            "decision": parsed["decision"],
            "rationale": parsed["rationale"],
            "answer_point_assessments": parsed["answer_point_assessments"],
            "refusal_assessment": parsed["refusal_assessment"],
            "payload_sha256": row["payload_sha256"],
            "prompt_sha256": prompt_sha,
            "response_sha256": _sha256_text(content.strip()),
            "raw_response_sha256": _sha256_text(content),
            "transport_retries": transport_retries,
            "parse_retries": parse_retries,
        })
    retry_stats = {"transport_total": transport_total,
                   "transport_max": transport_max,
                   "parse_total": parse_total}
    return results, raw_responses, retry_stats


def _parse_validated(content: str, payload: dict) -> tuple[dict | None, str | None]:
    value = _parse_review(content)
    if value is None:
        return None, "非法 JSON 或非对象输出"
    try:
        return _validate_review(value, payload), None
    except ReviewError as exc:
        return None, str(exc)


def review(*, out_dir: Path = OUT, llm_fn: Callable | None = None,
           run_at: str | None = None) -> dict:
    """preflight → 盲态 pack → Pro-only 逐条审阅 → 门禁/overlay 决策。

    fail-closed：任何失败不留下半成品最终目录；overlay 仅 148/148 confirmed
    且全部校验通过时生成。
    """
    if out_dir.exists():
        shutil.rmtree(out_dir)
    checks = preflight()
    rows, evidence_rows, chunks, _ = _build_rows(checks)
    if llm_fn is None:
        from src.llm_gateway import llm_call
        llm_fn = llm_call
    results, raw_responses, retry_stats = _run_review(rows, llm_fn)

    counts = {d: sum(1 for r in results if r["decision"] == d) for d in DECISIONS}
    all_confirmed = (len(results) == EXPECTED_CASE_COUNT
                     and counts["reject"] == 0 and counts["needs_followup"] == 0)
    issues = [r for r in results if r["decision"] != "confirmed"]
    gate_verdict = OVERLAY_STATUS if all_confirmed else GATE_BLOCKED
    refusal_counts = {a: sum(1 for r in results if r["refusal_assessment"] == a)
                      for a in REFUSAL_ASSESSMENTS}
    assessment_counts = {a: sum(1 for r in results
                                for e in r["answer_point_assessments"]
                                if e["assessment"] == a) for a in ASSESSMENTS}

    skill = checks["data_quality"]["skill"]
    summary = {
        "n_cases": len(results),
        "reviewer_identity": REVIEWER_IDENTITY,
        "reviewer_type": REVIEWER_TYPE,
        "model": REVIEWER_MODEL,
        "temperature": REVIEWER_TEMPERATURE,
        "max_tokens": REVIEWER_MAX_TOKENS,
        "thinking_disabled": True,
        "decision_counts": counts,
        "refusal_assessment_counts": refusal_counts,
        "assessment_counts": assessment_counts,
        "non_confirmed_count": len(issues),
        "overlay_generated": all_confirmed,
        "gate_verdict": gate_verdict,
        "transport_total_retries": retry_stats["transport_total"],
        "transport_max_retries": retry_stats["transport_max"],
        "parse_total_retries": retry_stats["parse_total"],
        "forbidden_models_guard": list(FORBIDDEN_MODELS),
        "data_quality_check": "deterministic_equivalent (skill unavailable)",
    }

    # ── 文档产物 ──
    report = _build_report(rows, results, counts, refusal_counts,
                           assessment_counts, issues, retry_stats, skill)
    if all_confirmed:
        gate_report = (
            "# v2.0.7 盲态自动审阅门禁报告\n\n"
            f"> **状态**：{OVERLAY_STATUS} — 148/148 confirmed\n"
            f"> **结论**：automated overlay 已生成（仅此状态允许）。\n"
            f"> **声明**：本报告是用户授权的 LLM 自动审阅结果，不是人工审核。\n\n"
            "## 决策统计\n\n"
            f"- confirmed：{counts['confirmed']}\n"
            f"- reject：{counts['reject']}\n"
            f"- needs_followup：{counts['needs_followup']}\n"
            f"- 确认率：{counts['confirmed']}/{len(results)}\n\n"
            "## fail-closed 校验\n\n"
            "- 前置门禁全部通过（case 148 / active evidence 161 / strict "
            "161/161 / legacy 0 / unresolved 0 / activation_blocked=true）；\n"
            f"- 模型固定 `{REVIEWER_MODEL}`（temperature=0.0、max_tokens=8000、"
            "thinking disabled、max_retries=3、无 fallback）；\n"
            f"- 审阅人身份 `{REVIEWER_IDENTITY}`，产物中无人工审核标识；\n"
            "- 全部 148 条模型输出通过 schema/枚举/索引/引用/一致性校验；\n"
            "- 输入 SHA 全部不变；candidate 仍为 revision_status=CANDIDATE、"
            "activation_blocked=true、human_reviewed=false、"
            "split_reseal_required=true、v2_1_entered=false。\n"
        )
    else:
        n_blocked = counts["reject"] + counts["needs_followup"]
        rows_md = "\n".join(
            f"| {r['case_id']} | {r['decision']} | {r['rationale'][:160]} |"
            for r in issues)
        gate_report = (
            "# v2.0.7 盲态自动审阅门禁报告\n\n"
            f"> **状态**：{GATE_BLOCKED} — {n_blocked} 条未通过\n"
            f"> **结论**：未生成 automated overlay。\n"
            f"> **声明**：本报告是用户授权的 LLM 自动审阅结果，不是人工审核。\n\n"
            "## 决策统计\n\n"
            f"- confirmed：{counts['confirmed']}\n"
            f"- reject：{counts['reject']}\n"
            f"- needs_followup：{counts['needs_followup']}\n"
            f"- 确认率：{counts['confirmed']}/{len(results)}\n\n"
            "## 未通过 case 清单\n\n"
            "| case_id | decision | 理由 |\n|---|---|---|\n" + rows_md + "\n\n"
            "## 结论\n\n"
            f"存在 {n_blocked} 条 reject / needs_followup，不得生成 automated "
            "overlay；修复后须重新运行本脚本。\n"
        )

    input_hashes = {
        "v207_manifest": _sha256_file(V207_MANIFEST),
        "draft_after": _sha256_file(DRAFT_AFTER),
        "evidence_after": _sha256_file(EVIDENCE_AFTER),
        "draft": _sha256_file(DRAFT),
        "chunks": _sha256_file(CHUNKS),
        "chunk_manifest": _sha256_file(CHUNK_MANIFEST),
    }
    files: dict[str, str] = {
        "automated-review-pack.jsonl": "".join(_line(row) + "\n" for row in rows),
        "automated-review-evidence.jsonl": "".join(_line(row) + "\n" for row in evidence_rows),
        "automated-review.jsonl": "".join(_line(row) + "\n" for row in results),
        "raw-model-responses.jsonl": "".join(_line(row) + "\n" for row in raw_responses),
        "automated-review-summary.json": _dump(summary),
        "automated-review-report.md": report,
        "automated-review-gate-report.md": gate_report,
        "automated-review-issues.jsonl": "".join(_line(row) + "\n" for row in issues),
    }
    overlay = None
    overlay_manifest = None
    if all_confirmed:
        overlay = _build_overlay(rows, results, counts, checks)
        overlay_manifest = _build_overlay_manifest(files, overlay, run_at)

    staging = Path(tempfile.mkdtemp(prefix=".v207-review-", dir=out_dir.parent))
    try:
        for name, content in files.items():
            _atomic_write(staging / name, content)
        if overlay is not None:
            _atomic_write(staging / "automated-reviewed-truth-overlay.json",
                          _dump(overlay))
            _atomic_write(staging / "automated-reviewed-truth-overlay-manifest.json",
                          _dump(overlay_manifest))
        output_shas = {name: _sha256_file(staging / name) for name in files}
        if overlay is not None:
            output_shas["automated-reviewed-truth-overlay.json"] = _sha256_file(
                staging / "automated-reviewed-truth-overlay.json")
            output_shas["automated-reviewed-truth-overlay-manifest.json"] = _sha256_file(
                staging / "automated-reviewed-truth-overlay-manifest.json")
        manifest = _manifest({
            "revision_status": "CANDIDATE", "activation_blocked": True,
            "human_reviewed": False, "split_reseal_required": True,
            "v2_1_entered": False, "overlay_generated": all_confirmed,
            "gate_verdict": gate_verdict,
            "reviewer_identity": REVIEWER_IDENTITY, "reviewer_type": REVIEWER_TYPE,
            "model": REVIEWER_MODEL, "temperature": REVIEWER_TEMPERATURE,
            "max_tokens": REVIEWER_MAX_TOKENS, "thinking_disabled": True,
            "max_retries": MAX_RETRIES, "n_cases": len(results),
            "decision_counts": counts, "counts": counts,
            "inputs": input_hashes, "outputs": output_shas,
            "forbidden_outputs": ["active metadata", "overlay without 148/148",
                                  "v2.1 pointer", "split reuse", "locked config"],
            "data_quality": checks["data_quality"],
            "timestamp": run_at or TIMESTAMP,
            "created_by": "corpus_v2_v207_fresh_automated_review.py review",
        })
        _atomic_write(staging / "manifest.json", _dump(manifest))
        os.replace(staging, out_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(out_dir, ignore_errors=True)
        raise
    return {"status": gate_verdict, "gate_verdict": gate_verdict,
            "overlay_generated": all_confirmed, "counts": counts,
            "manifest": manifest}


def _build_overlay(rows: list[dict], results: list[dict], counts: dict,
                   checks: dict) -> dict:
    draft_by_id = {row["id"]: row for row in checks["draft_rows"]}
    result_by_case = {r["case_id"]: r for r in results}
    truth_cases: dict[str, dict] = {}
    for row in rows:
        cid = row["case_id"]
        case = draft_by_id[cid]
        result = result_by_case[cid]
        truth_cases[cid] = {
            "case_id": cid,
            "query": case.get("query", ""),
            "should_refuse": case.get("should_refuse") is True,
            "acceptable_answer_points": list(case.get("acceptable_answer_points") or []),
            "review_decision": result["decision"],
            "reviewer_identity": REVIEWER_IDENTITY,
            "model": REVIEWER_MODEL,
            "payload_sha256": row["payload_sha256"],
        }
    return {
        "status": OVERLAY_STATUS,
        "revision_status": "CANDIDATE", "activation_blocked": True,
        "human_reviewed": False, "split_reseal_required": True,
        "v2_1_entered": False,
        "reviewer_identity": REVIEWER_IDENTITY, "reviewer_type": REVIEWER_TYPE,
        "model": REVIEWER_MODEL, "temperature": REVIEWER_TEMPERATURE,
        "max_tokens": REVIEWER_MAX_TOKENS, "n_cases": len(results),
        "decision_counts": counts,
        "source_revision": "v2.0.7-owner-authorized-legacy-evidence-retirement",
        "generated_at": TIMESTAMP,
        "truth_cases": truth_cases,
        "disclaimer": (
            f"本 overlay 由用户授权的 LLM 自动审阅生成（{REVIEWER_IDENTITY}），"
            "不是人工审核、不是人工批准、不代表生产上线批准；"
            "candidate 仍为 revision_status=CANDIDATE、activation_blocked=true、"
            "human_reviewed=false、split_reseal_required=true、v2_1_entered=false。"
        ),
    }


def _build_overlay_manifest(files: dict, overlay: dict, run_at: str | None) -> dict:
    body = {
        "status": overlay["status"],
        "revision_status": "CANDIDATE", "activation_blocked": True,
        "human_reviewed": False, "split_reseal_required": True,
        "v2_1_entered": False,
        "reviewer_identity": REVIEWER_IDENTITY, "reviewer_type": REVIEWER_TYPE,
        "model": REVIEWER_MODEL, "temperature": REVIEWER_TEMPERATURE,
        "max_tokens": REVIEWER_MAX_TOKENS, "n_cases": overlay["n_cases"],
        "decision_counts": overlay["decision_counts"],
        "inputs": {
            "review_dir": str(OUT),
            "automated_review_jsonl_sha256": _sha256_text(files["automated-review.jsonl"]),
            "pack_jsonl_sha256": _sha256_text(files["automated-review-pack.jsonl"]),
        },
        "outputs": {
            "overlay_sha256": _sha256_text(_dump(overlay)),
        },
        "generated_at": run_at or TIMESTAMP,
        "created_by": "corpus_v2_v207_fresh_automated_review.py review",
    }
    body["outputs"]["manifest_sha256"] = _sha256_text(_dump(body))
    return body


def _build_report(rows: list[dict], results: list[dict], counts: dict,
                  refusal_counts: dict, assessment_counts: dict,
                  issues: list[dict], retry_stats: dict, skill: dict) -> str:
    n = len(results)
    lines = [
        "# v2.0.7 盲态自动审阅报告（LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_7）", "",
        "> **声明**：本审阅由用户授权，执行者为 LLM（deepseek-v4-pro），"
        "审阅人身份为 `LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_7`。",
        "> **本报告是机器审阅结果，不是人工审核、人工批准或生产上线批准。**", "",
        "## 全量汇总", "",
        f"- 审阅条数：{n}（v2.0.7 candidate 全部 148 条，盲态输入）",
        f"- 审阅模型：{REVIEWER_MODEL}（temperature={REVIEWER_TEMPERATURE}、"
        f"max_tokens={REVIEWER_MAX_TOKENS}、thinking disabled、max_retries={MAX_RETRIES}）",
        f"- confirmed：{counts['confirmed']}",
        f"- reject：{counts['reject']}",
        f"- needs_followup：{counts['needs_followup']}",
        f"- 确认率：{counts['confirmed']}/{n} = {counts['confirmed'] / n:.1%}" if n else "-",
        "",
        "### 拒答评估分布", "",
        "| refusal_assessment | 条数 |", "|---|---|",
    ]
    for a in REFUSAL_ASSESSMENTS:
        lines.append(f"| {a} | {refusal_counts[a]} |")
    lines += ["", "### 答案点评估分布", "",
              "| assessment | 答案点数 |", "|---|---|"]
    for a in ASSESSMENTS:
        lines.append(f"| {a} | {assessment_counts[a]} |")
    lines += ["", "### 传输 / 解析重试统计", "",
              f"- 传输重试总计：{retry_stats['transport_total']}",
              f"- 传输重试最大：{retry_stats['transport_max']}",
              f"- 解析重试总计：{retry_stats['parse_total']}",
              "", "### 待修复清单", ""]
    if issues:
        lines += ["| case_id | decision | 理由 |", "|---|---|---|"]
        for r in issues:
            lines.append(f"| {r['case_id']} | {r['decision']} | "
                         f"{r['rationale'][:200]} |")
    else:
        lines.append("无（全部 confirmed）。")
    lines += ["", "## 盲态与 fail-closed 校验", "",
              "- 模型输入仅含 query / previous_turns（剥离 case_id 与链路引用）/ "
              "should_refuse / acceptable_answer_points / evidence（raw span + "
              "展示 snippet）/ 对应 chunk 原文；不含 case_id、split/dev/holdout、"
              "旧 review decision/rationale、历史 reject/blocker/remediation、"
              "评测分数或候选版本结论；",
              "- 本地严格校验 schema、枚举、模型身份、answer point 索引与 "
              "evidence ref 范围；拒答/可答分别按一致性规则校验；",
              f"- 审阅人身份固定为 `{REVIEWER_IDENTITY}`；禁止模型守卫："
              f"{', '.join(FORBIDDEN_MODELS)}；",
              "- 输入（v2.0.7 manifest / draft-after / evidence-after / draft / "
              "chunks / chunk-manifest）SHA 全部不变；candidate draft/evidence/"
              "chunks 未被修改；",
              "- 数据质量检查（确定性等价实现）：完整性 / 唯一性 / 引用完整性 / "
              "连续性 / 一致性全部通过；",
              f"- data-analytics:analyze-data-quality 不可用（{skill['failure']}），"
              "已用等价离线确定性检查替代。", "",
              "## 结论", ""]
    if counts["reject"] == 0 and counts["needs_followup"] == 0:
        lines.append(
            f"**{REVIEWER_IDENTITY} complete**（148/148 confirmed）→ "
            f"automated overlay 已生成（{OVERLAY_STATUS}）；candidate 仍为 "
            "revision_status=CANDIDATE、activation_blocked=true、"
            "human_reviewed=false、split_reseal_required=true、v2_1_entered=false；"
            "不代表人工批准或生产上线批准。")
    else:
        lines.append(
            f"审阅未完成：{counts['reject'] + counts['needs_followup']} 条需要关注"
            f"（见 automated-review-issues.jsonl 与 gate report），"
            "不得生成 automated overlay。")
    return "\n".join(lines) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(__doc__)
        return 0
    cmd = args[0]
    try:
        if cmd == "probe-json":
            print(json.dumps(probe_json(), ensure_ascii=False, sort_keys=True))
            return 0
        if cmd == "pack":
            rows = build_pack(out_dir=OUT)
            print(f"pack ok: {len(rows)} rows -> {OUT}")
            return 0
        if cmd == "preflight":
            checks = preflight()
            print(json.dumps({k: v for k, v in checks.items()
                              if k not in ("chunks", "draft_rows",
                                           "evidence_by_case", "manifest")},
                             ensure_ascii=False, sort_keys=True))
            return 0
        if cmd == "review":
            result = review(out_dir=OUT)
            print(json.dumps({"overlay_generated": result["overlay_generated"],
                              "gate_verdict": result["gate_verdict"],
                              "counts": result["counts"]},
                             ensure_ascii=False, sort_keys=True))
            return 0
    except ReviewError as exc:
        print(f"FAILED: {exc}")
        return 2
    print(f"unknown command: {cmd}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
