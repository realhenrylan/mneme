"""Generate LLM-assisted, owner-decision-only proposals for 13 unresolved coordinates.

The module is deliberately fail-closed: it never edits corpus data or creates an
activation/overlay artifact. The model sees only blind case material and the
coordinate diagnostic; every proposed raw span is independently revalidated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import corpus_v2_evidence_coordinate_repair as coord
from src.llm_gateway import llm_call

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "evaluation/datasets/v2/revisions/v2.0.2-evidence-coordinate-repair"
DEFAULT_OUT = BASE / "resolution-proposals"
DEFAULT_UNRESOLVED = BASE / "coordinate-unresolved.jsonl"
DEFAULT_MIGRATION = BASE / "coordinate-migration.jsonl"
DEFAULT_AUDIT = BASE / "coordinate-audit-before.json"
DEFAULT_QUALITY = BASE / "coordinate-quality-report.json"
DEFAULT_TRIAGE = BASE / "unresolved-triage" / "unresolved-triage.jsonl"
DEFAULT_MANIFEST = BASE / "manifest.json"
DEFAULT_DRAFT = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"
DEFAULT_CHUNKS = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
DEFAULT_CHUNK_MANIFEST = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
MODEL = "deepseek-v4-flash"
TEMPERATURE = 0.0
MAX_TOKENS = 8000
MAX_PROBE_RETRIES = 3
RULE_VERSION = "v2.0.2-coordinate-resolution-proposals-flash-2"
EXTRA_BODY = {"thinking": {"type": "disabled"}}
TIMESTAMP = "2026-08-07T00:00:00+00:00"
ACTIONS = (
    "preserve_raw_format_in_display", "propose_display_normalization_policy",
    "add_exact_raw_evidence", "expand_or_reanchor_evidence",
    "narrow_answer_point", "remove_unsupported_answer_point", "keep_unresolved",
)
CATEGORIES = (
    "format_transform_requires_policy", "semantic_or_content_drift",
    "whitespace_or_line_ending_only", "legacy_range_disambiguable_duplicate",
    "source_or_chunk_integrity_problem",
)

SYSTEM_PROMPT = """你是离线坐标修复建议助手。你只能依据本条输入中的 query、答案点、未解决坐标记录、旧 snippet（可能为空）、同一 chunk 原文和诊断上下文给出所有者决策建议。不得推断任何未提供的语料、历史审阅结论或评测身份。
只能选择一个 action：preserve_raw_format_in_display、propose_display_normalization_policy、add_exact_raw_evidence、expand_or_reanchor_evidence、narrow_answer_point、remove_unsupported_answer_point、keep_unresolved。
必须输出单个 JSON：{"action":...,"recommendation":...,"risk":...,"owner_decisions":[...],"evidence":[{"start":整数,"end":整数,"span":"原文"}],"rationale":"..."}。证据必须是同一 chunk 的连续原文；不能证明时 evidence=[] 且 action=keep_unresolved。任何展示 Markdown、代码或链接的变化都必须同时讨论保留原始格式和拟定展示规范，并说明需要所有者批准。
直接输出最终 JSON，不要输出任何思考过程、分析或解释，不要使用 Markdown 代码块或任何额外文本。"""


class ProposalError(Exception):
    """任何输入、模型或输出契约失败。"""


class StrictJSONParseError(ProposalError):
    """模型响应无法在不修复内容的前提下解析。"""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _canonical(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def build_manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


def verify_manifest(manifest: dict) -> bool:
    got = manifest.get("manifest_sha256")
    body = dict(manifest)
    body.pop("manifest_sha256", None)
    return got == hashlib.sha256(_canonical(body)).hexdigest()


def build_blind_payload(case: dict, unresolved: dict, chunk: dict, old_snippet: str = "") -> dict:
    return {
        "query": case.get("query", ""),
        "acceptable_answer_points": list(case.get("acceptable_answer_points") or []),
        "should_refuse": bool(case.get("should_refuse")),
        "unresolved_coordinate": {
            "chunk_id": unresolved.get("chunk_id"),
            "source_id": unresolved.get("source_id"),
            "legacy_char_range": unresolved.get("legacy_char_range"),
            "reason": unresolved.get("reason"),
        },
        "old_snippet": old_snippet,
        "chunk": {"source": chunk.get("source"), "text": chunk.get("text", "")},
    }


def _validate_schema(value: Any) -> dict:
    if not isinstance(value, dict) or value.get("action") not in ACTIONS:
        raise StrictJSONParseError("LLM response schema/action invalid")
    for key in ("recommendation", "risk", "owner_decisions", "evidence", "rationale"):
        if key not in value:
            raise StrictJSONParseError(f"LLM response missing field: {key}")
    if not isinstance(value["evidence"], list) or not isinstance(value["owner_decisions"], list):
        raise StrictJSONParseError("LLM response list field invalid")
    return value


def parse_model_json_strict(content: str, returned_model: str | None = None) -> dict:
    """解析允许的 JSON 外壳，但绝不修复或猜测模型内容。"""
    if returned_model != MODEL:
        raise ProposalError(f"LLM model identity mismatch: {returned_model!r}")
    if not isinstance(content, str):
        raise StrictJSONParseError("LLM response content is not text")
    text = content.lstrip("\\ufeff").strip()
    if not text:
        raise StrictJSONParseError("LLM response is empty")
    if text.startswith("```"):
        if not (text.endswith("```") and text.count("```") == 2):
            raise StrictJSONParseError("LLM response has incomplete or multiple code fences")
        lines = text.splitlines()
        if not lines or lines[0].strip().lower() not in ("```", "```json") or lines[-1].strip() != "```":
            raise StrictJSONParseError("LLM response code fence is invalid")
        text = "\\n".join(lines[1:-1]).strip()
        if not text:
            raise StrictJSONParseError("LLM response code fence is empty")
    decoder = json.JSONDecoder()
    candidates = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        prefix = text[:index]
        if isinstance(value, dict) and not text[end:].strip() and not any(ch in prefix for ch in "{}"):
            candidates.append((index, end, value))
    if len(candidates) != 1:
        raise StrictJSONParseError("LLM response must contain one complete JSON object")
    start, end, value = candidates[0]
    if not text[:start].strip() and text[end:].strip():
        raise StrictJSONParseError("LLM response has trailing non-whitespace")
    return _validate_schema(value)


def parse_model_response(content: str, returned_model: str | None = None) -> dict:
    return parse_model_json_strict(content, returned_model)


def validate_raw_span(proposal: dict, chunk: dict) -> dict:
    evidence = proposal.get("evidence") or []
    if not evidence:
        evidence = [proposal.get("raw_span")] if proposal.get("raw_span") else []
    if len(evidence) != 1 or not isinstance(evidence[0], dict):
        return {"raw_span_proof": False, "raw_span": None}
    item = evidence[0]
    start, end, span = item.get("start"), item.get("end"), item.get("span")
    text = chunk.get("text", "")
    if (isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int)
            or not isinstance(end, int) or start < 0 or end <= start or end > len(text)
            or text[start:end] != span):
        return {"raw_span_proof": False, "raw_span": None}
    return {"raw_span_proof": True, "raw_span": {"start": start, "end": end, "span": span}}


def auto_applicable(row: dict) -> bool:
    return False


def _response_diagnostic(content: Any, exc: Exception) -> dict:
    raw = content if isinstance(content, str) else ""
    return {"error_type": type(exc).__name__, "response_length": len(raw),
            "response_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "safe_excerpt": raw[:80].replace("\\n", "\\n")}


def _call_and_parse(messages: list[dict], llm_fn: Callable | None) -> tuple[dict, str, int, list[dict]]:
    diagnostics = []
    for attempt in range(1, MAX_PROBE_RETRIES + 1):
        content, returned_model, gateway_retries = _call(messages, llm_fn)
        try:
            parsed = parse_model_json_strict(content, returned_model)
            return parsed, content, gateway_retries + attempt - 1, diagnostics
        except StrictJSONParseError as exc:
            diagnostics.append(_response_diagnostic(content, exc) | {"attempt": attempt})
            if attempt == MAX_PROBE_RETRIES:
                exc.diagnostics = diagnostics
                raise
    raise AssertionError("unreachable")


def probe(*, llm_fn: Callable | None = None) -> dict:
    """调用固定 Flash 模型，验证身份、参数和最小 JSON 契约。"""
    payload = {
        "query": "坐标建议探针",
        "acceptable_answer_points": [],
        "should_refuse": False,
        "unresolved_coordinate": {"reason": "probe"},
        "old_snippet": "",
        "chunk": {"source": "probe", "text": ""},
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
    ]
    parsed, content, retries, diagnostics = _call_and_parse(messages, llm_fn)
    return {"model": MODEL, "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS, "retries_used": retries,
            "action": parsed["action"], "diagnostics": diagnostics}


def _response_content(response: Any) -> tuple[str, str | None]:
    model = getattr(response, "model", None)
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise ProposalError("LLM response has no choices")
    content = getattr(getattr(choices[0], "message", None), "content", None)
    if not isinstance(content, str):
        raise ProposalError("LLM response content missing")
    return content.strip(), model


def _call(messages: list[dict], llm_fn: Callable | None) -> tuple[str, str | None, int]:
    if llm_fn is None:
        # 关闭推理输出，避免 reasoning 占满 max_tokens 预算导致 content 为空。
        response, record = llm_call("coordinate_resolution_proposal", messages,
                                    model=MODEL, temperature=TEMPERATURE,
                                    max_tokens=MAX_TOKENS,
                                    max_retries=MAX_PROBE_RETRIES,
                                    extra_body=EXTRA_BODY)
        content, returned_model = _response_content(response)
        return content, returned_model, int(getattr(record, "retries_used", 0))
    result = llm_fn(messages=messages, model=MODEL, temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS)
    if not isinstance(result, tuple) or len(result) != 2:
        raise ProposalError("LLM gateway returned invalid result")
    content, returned_model = result
    return content, returned_model, 0


def _validate_inputs(unresolved_path: Path, migration_path: Path, audit_path: Path,
                     quality_path: Path, manifest_path: Path, draft_path: Path,
                     chunks_path: Path, chunk_manifest_path: Path) -> tuple[list, list, dict, list, dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != "v2.0.2" or not manifest.get("activation_blocked"):
        raise ProposalError("candidate/activation gate failed")
    if manifest.get("counts") != {"evidence": 161, "migrated": 148, "unresolved": 13} or not verify_manifest(manifest):
        raise ProposalError("v2.0.2 manifest counts/self-hash failed")
    unresolved = _jsonl(unresolved_path)
    if len(unresolved) != 13 or len({(r.get("case_id"), r.get("chunk_id"), r.get("source_id")) for r in unresolved}) != 13:
        raise ProposalError("unresolved set must contain 13 unique rows")
    expected = manifest["inputs"]
    for key, path in (("draft", draft_path), ("chunks", chunks_path), ("evidence", BASE.parent.parent.parent / "automated-review" / "automated-review-evidence.jsonl")):
        if key == "evidence":
            # Evidence is not read; its declared SHA is checked only against the candidate manifest.
            continue
        if _sha(path) != expected[key]["sha256"]:
            raise ProposalError(f"{key} SHA drift")
    draft = _jsonl(draft_path)
    if len(draft) != 150 or len({r.get("id") for r in draft}) != 150:
        raise ProposalError("draft gate failed")
    chunks = {r["chunk_id"]: r for r in _jsonl(chunks_path)}
    if len(chunks) != 1006:
        raise ProposalError("chunk coverage failed")
    for row in unresolved:
        chunk = chunks.get(row.get("chunk_id"))
        if not chunk or chunk.get("source") != row.get("source_id"):
            raise ProposalError("unresolved source/chunk mismatch")
    migration = _jsonl(migration_path)
    if len(migration) != 148:
        raise ProposalError("migration coverage failed")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    if audit.get("evidence_rows") != 161 or audit.get("draft_rows") != 150:
        raise ProposalError("audit baseline drift")
    if not isinstance(quality, dict):
        raise ProposalError("quality report invalid")
    if not chunk_manifest_path.is_file():
        raise ProposalError("chunk manifest missing")
    return unresolved, draft, chunks, migration, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--probe-json", action="store_true")
    args = parser.parse_args(argv)
    if args.probe_json or args.probe:
        result = probe()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    result = run()
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))
    return 0


def run(*, out_dir: Path = DEFAULT_OUT, unresolved_path: Path = DEFAULT_UNRESOLVED,
        migration_path: Path = DEFAULT_MIGRATION, audit_path: Path = DEFAULT_AUDIT,
        quality_path: Path = DEFAULT_QUALITY, triage_path: Path = DEFAULT_TRIAGE,
        manifest_path: Path = DEFAULT_MANIFEST,
        draft_path: Path = DEFAULT_DRAFT, chunks_path: Path = DEFAULT_CHUNKS,
        chunk_manifest_path: Path = DEFAULT_CHUNK_MANIFEST, llm_fn: Callable | None = None) -> dict:
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ProposalError("output directory must be absent or empty")
    unresolved, draft, chunks, migration, candidate_manifest = _validate_inputs(
        unresolved_path, migration_path, audit_path, quality_path, manifest_path,
        draft_path, chunks_path, chunk_manifest_path)
    triage = {r["case_id"]: r for r in _jsonl(triage_path)}
    if len(triage) != 13 or any(r.get("case_id") not in triage for r in unresolved):
        raise ProposalError("triage mapping must cover all 13 unresolved rows")
    by_id = {r["id"]: r for r in draft}
    proposals, raw_rows = [], []
    try:
        for item in sorted(unresolved, key=lambda r: (r["case_id"], r["chunk_id"])):
            case = by_id[item["case_id"]]
            chunk = chunks[item["chunk_id"]]
            triage_row = triage[item["case_id"]]
            blind = build_blind_payload(case, item, chunk)
            parsed, content, retries, diagnostics = _call_and_parse(
                [{"role": "system", "content": SYSTEM_PROMPT},
                 {"role": "user", "content": json.dumps(blind, ensure_ascii=False, sort_keys=True)}], llm_fn)
            returned_model = MODEL
            proof = validate_raw_span(parsed, chunk)
            if not proof["raw_span_proof"]:
                parsed["action"] = "keep_unresolved"
            proposal = {
                "case_id": item["case_id"], "chunk_id": item["chunk_id"],
                "source_id": item["source_id"],
                "root_cause_category": triage_row.get("root_cause_category", ""),
                "candidate_auto_resolution": bool(triage_row.get("candidate_auto_resolution")),
                "model_proposal": parsed, **proof,
                "proposal_status": "LLM_ASSISTED_OWNER_DECISION_REQUIRED",
                "auto_applicable": False, "requires_owner_authorization": True,
            }
            proposals.append(proposal)
            raw_rows.append({"case_id": item["case_id"], "model": returned_model,
                             "raw_response": content, "response_sha256": hashlib.sha256(content.encode()).hexdigest(),
                             "retries_used": retries, "diagnostics": diagnostics})
        if len(proposals) != 13:
            raise ProposalError("proposal coverage failed")
        counts = Counter(r["root_cause_category"] for r in proposals)
        actions = Counter(r["model_proposal"]["action"] for r in proposals)
        no_local = [r["case_id"] for r in proposals if not r["raw_span_proof"]]
        summary = {"category_counts": {c: counts.get(c, 0) for c in CATEGORIES},
                   "action_counts": dict(sorted(actions.items())), "proposal_count": 13,
                   "candidate_auto_resolution_count": 0, "no_local_raw_evidence_case_ids": no_local,
                   "automatic_processing_blocked": True}
        report = "# v2.0.2 Coordinate Resolution Proposals\n\n" + \
            "这是由 `deepseek-v4-flash` 生成的 LLM 辅助所有者决策建议，不是人工审核、自动修复或准入。\n\n" + \
            "本批次不得与此前 `deepseek-v4-pro` 结果混合比较。\n\n" + \
            "所有建议均 `LLM_ASSISTED_OWNER_DECISION_REQUIRED`，`auto_applicable=false`；" \
            "v2.0.2 仍 activation blocked，未生成 overlay。\n"
        matrix = "# OWNER DECISION MATRIX\n\n所有方案尚未采纳；每条均需所有者明确批准。\n\n" + \
            "\n".join(f"- `{r['case_id']}`：建议 `{r['model_proposal']['action']}`；风险：{r['model_proposal']['risk']}；采纳将仅改变经批准的坐标/展示字段。" for r in proposals) + "\n"
        out_dir.mkdir(parents=True, exist_ok=True)
        files = {
            "coordinate-resolution-proposals.jsonl": "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in proposals),
            "raw-model-responses.jsonl": "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in raw_rows),
            "resolution-options-summary.json": _dump(summary),
            "OWNER_DECISION_MATRIX.md": matrix,
            "resolution-proposals-report.md": report,
        }
        for name, text in files.items():
            (out_dir / name).write_text(text, encoding="utf-8", newline="\n")
        body = {"version": "v2.0.2-coordinate-resolution-proposals", "rule_version": RULE_VERSION,
                "timestamp": TIMESTAMP, "model": MODEL, "temperature": TEMPERATURE,
                "max_tokens": MAX_TOKENS, "activation_blocked": True,
                "inputs": {"unresolved": {"sha256": _sha(unresolved_path)}, "migration": {"sha256": _sha(migration_path)},
                           "audit": {"sha256": _sha(audit_path)}, "quality": {"sha256": _sha(quality_path)},
                           "candidate_manifest": {"sha256": _sha(manifest_path)}, "draft": {"sha256": _sha(draft_path)},
                           "chunks": {"sha256": _sha(chunks_path)}, "chunk_manifest": {"sha256": _sha(chunk_manifest_path)}},
                "counts": summary, "outputs": {n: _sha(out_dir / n) for n in files},
                "lineage_note": "Flash-only batch; do not mix or compare with prior Pro results",
                "retry_policy": {"gateway_max_retries": MAX_PROBE_RETRIES},}
        final = build_manifest(body)
        (out_dir / "manifest.json").write_text(_dump(final), encoding="utf-8", newline="\n")
        return {"proposals": proposals, "summary": summary, "manifest": final}
    except Exception as exc:
        if out_dir.exists():
            shutil.rmtree(out_dir)
        diagnostics = getattr(exc, "diagnostics", None)
        if diagnostics:
            print(json.dumps({"failure": diagnostics[-1], "attempts": len(diagnostics)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
