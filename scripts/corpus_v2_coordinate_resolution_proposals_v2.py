"""Generate quote-only, owner-gated coordinate proposals for v2.0.2."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import corpus_v2_coordinate_resolution_proposals as base

BASE = base.BASE
DEFAULT_OUT = BASE / "resolution-proposals-v2"
MODEL = base.MODEL
TEMPERATURE = base.TEMPERATURE
MAX_TOKENS = base.MAX_TOKENS
MAX_PROBE_RETRIES = base.MAX_PROBE_RETRIES
EXTRA_BODY = base.EXTRA_BODY
TIMESTAMP = "2026-08-10T00:00:00+00:00"
RULE_VERSION = "v2.0.2-coordinate-resolution-proposals-quote-only-flash-1"
ANCHOR_ALGORITHM_VERSION = "raw-codepoint-v1-unique-quote"
ALLOWED_FIELDS = {
    "action", "declared_chunk_id", "evidence_quote", "rationale", "risk",
    "owner_decision_required",
}

SYSTEM_PROMPT = """你是离线坐标修复建议助手。只能依据本条输入中的 query、答案点、诊断上下文和同一 raw chunk 原文给出所有者决策建议。
你只能提供逐字连续的 evidence_quote 和 declared_chunk_id；绝对不要输出 start、end、char_range、坐标、offset 或任何其他字段。
必须输出单个 JSON，且字段严格为：action、declared_chunk_id、evidence_quote、rationale、risk、owner_decision_required。
evidence_quote 必须逐字复制同一 raw chunk 中的连续 Unicode 原文；无法确定时输出空字符串并选择 keep_unresolved。owner_decision_required 必须为 true。
不要翻译、释义、改写、删除 Markdown/代码/标点或拼接非连续文本。直接输出 JSON，不要思考过程、Markdown 代码块或额外文本。"""


class QuoteSchemaError(base.ProposalError):
    """模型 quote-only schema 或字段边界失败。"""


def validate_quote_response(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != ALLOWED_FIELDS:
        raise QuoteSchemaError("quote response fields must match exact quote-only schema")
    if value.get("action") not in base.ACTIONS:
        raise QuoteSchemaError("quote response action invalid")
    if not isinstance(value.get("declared_chunk_id"), str):
        raise QuoteSchemaError("declared_chunk_id must be text")
    if not isinstance(value.get("evidence_quote"), str):
        raise QuoteSchemaError("evidence_quote must be text")
    if not all(isinstance(value.get(k), str) for k in ("rationale", "risk")):
        raise QuoteSchemaError("rationale and risk must be text")
    if value.get("owner_decision_required") is not True:
        raise QuoteSchemaError("owner_decision_required must be true")
    return value


def _parse(content: str, returned_model: str | None) -> dict:
    if returned_model != MODEL:
        raise base.ProposalError(f"LLM model identity mismatch: {returned_model!r}")
    if not isinstance(content, str):
        raise QuoteSchemaError("LLM response content is not text")
    text = content.lstrip("\\ufeff").strip()
    if not text:
        raise QuoteSchemaError("LLM response is empty")
    if text.startswith("```"):
        if not (text.endswith("```") and text.count("```") == 2):
            raise QuoteSchemaError("LLM response code fence invalid")
        lines = text.splitlines()
        if lines[0].strip().lower() not in ("```", "```json") or lines[-1].strip() != "```":
            raise QuoteSchemaError("LLM response code fence invalid")
        text = "\\n".join(lines[1:-1]).strip()
    decoder = json.JSONDecoder()
    candidates = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and not text[end:].strip() and not any(ch in text[:index] for ch in "{}"):
            candidates.append(value)
    if len(candidates) != 1:
        raise QuoteSchemaError("LLM response must contain one complete JSON object")
    return validate_quote_response(candidates[0])


def _call_and_parse_quote(messages: list[dict], llm_fn: Callable | None):
    diagnostics = []
    for attempt in range(1, MAX_PROBE_RETRIES + 1):
        content, returned_model, gateway_retries = base._call(messages, llm_fn)
        try:
            return _parse(content, returned_model), content, gateway_retries + attempt - 1, diagnostics
        except (base.StrictJSONParseError, QuoteSchemaError) as exc:
            diagnostics.append(base._response_diagnostic(content, exc) | {"attempt": attempt})
            if attempt == MAX_PROBE_RETRIES:
                exc.diagnostics = diagnostics
                raise


def anchor_quote(proposal: dict, chunk: dict) -> dict:
    text = chunk.get("text", "")
    quote = proposal.get("evidence_quote", "")
    declared = proposal.get("declared_chunk_id")
    positions = []
    if declared == chunk.get("chunk_id") and quote:
        start = text.find(quote)
        while start >= 0:
            positions.append(start)
            start = text.find(quote, start + 1)
    result = {
        "action": proposal.get("action", "keep_unresolved"),
        "evidence_quote": quote,
        "anchor_match_count": len(positions),
        "raw_evidence_span": None,
        "raw_chunk_char_range": None,
        "anchor_algorithm_version": ANCHOR_ALGORITHM_VERSION,
    }
    if len(positions) == 1:
        start = positions[0]
        end = start + len(quote)
        if text[start:end] == quote:
            result["raw_evidence_span"] = quote
            result["raw_chunk_char_range"] = {"start": start, "end": end}
            return result
    result["action"] = "keep_unresolved"
    return result


def serialize_proposal(item: dict, model_proposal: dict, anchor: dict) -> dict:
    return {
        "case_id": item["case_id"], "chunk_id": item["chunk_id"], "source_id": item["source_id"],
        "model_proposal": model_proposal, **anchor,
        "proposal_status": "LLM_ASSISTED_OWNER_DECISION_REQUIRED",
        "auto_applicable": False, "requires_owner_authorization": True,
    }


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def run(*, out_dir: Path = DEFAULT_OUT, llm_fn: Callable | None = None, **paths) -> dict:
    if out_dir.exists() and any(out_dir.iterdir()):
        raise base.ProposalError("output directory must be absent or empty")
    defaults = {
        "unresolved_path": base.DEFAULT_UNRESOLVED, "migration_path": base.DEFAULT_MIGRATION,
        "audit_path": base.DEFAULT_AUDIT, "quality_path": base.DEFAULT_QUALITY,
        "manifest_path": base.DEFAULT_MANIFEST, "draft_path": base.DEFAULT_DRAFT,
        "chunks_path": base.DEFAULT_CHUNKS, "chunk_manifest_path": base.DEFAULT_CHUNK_MANIFEST,
    }
    defaults.update(paths)
    unresolved, draft, chunks, migration, candidate_manifest = base._validate_inputs(**defaults)
    by_id = {r["id"]: r for r in draft}
    proposals, raw_rows, audits = [], [], []
    try:
        for item in sorted(unresolved, key=lambda r: (r["case_id"], r["chunk_id"])):
            chunk = chunks[item["chunk_id"]]
            payload = base.build_blind_payload(by_id[item["case_id"]], item, chunk)
            messages = [{"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)}]
            parsed, content, retries, diagnostics = _call_and_parse_quote(messages, llm_fn)
            anchor = anchor_quote(parsed, chunk)
            proposals.append(serialize_proposal(item, parsed, anchor))
            audits.append({"case_id": item["case_id"], "chunk_id": item["chunk_id"], **anchor,
                           "model_semantic_suggestion": parsed, "local_raw_coordinate_proven": bool(anchor["raw_chunk_char_range"])})
            raw_rows.append({"case_id": item["case_id"], "model": MODEL, "raw_response": content,
                             "response_sha256": hashlib.sha256(content.encode()).hexdigest(),
                             "retries_used": retries, "diagnostics": diagnostics})
        anchored = sum(bool(r["raw_chunk_char_range"]) for r in proposals)
        summary = {"proposal_count": len(proposals), "unique_raw_anchor_count": anchored,
                   "still_unresolved_count": len(proposals) - anchored,
                   "action_counts": dict(sorted(Counter(r["action"] for r in proposals).items())),
                   "automatic_processing_blocked": True, "activation_blocked": True}
        report = ("# v2.0.2 Quote-Only Coordinate Resolution Proposals\n\n"
                  "模型仅提供语义建议和逐字 evidence_quote；raw 坐标完全由本地 `raw-codepoint-v1` 唯一锚定计算。\n\n"
                  f"13 条中唯一 raw 锚定 {anchored} 条，仍 unresolved {len(proposals)-anchored} 条。\n\n"
                  "即使锚定成功，所有建议仍需所有者授权，`auto_applicable=false`；未激活 v2.0.2、未生成 overlay、未进入 v2.1。\n")
        matrix = "# OWNER DECISION MATRIX v2\n\n" + "\n".join(
            f"- `{r['case_id']}`：模型 quote 建议 `{r['model_proposal']['evidence_quote']}`；本地 raw 锚定={'是' if r['raw_chunk_char_range'] else '否'}；仍需所有者决定。"
            for r in proposals) + "\n"
        out_dir.mkdir(parents=True, exist_ok=True)
        files = {
            "coordinate-resolution-proposals-v2.jsonl": "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in proposals),
            "raw-model-responses-v2.jsonl": "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in raw_rows),
            "local-anchor-audit.jsonl": "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in audits),
            "resolution-options-summary-v2.json": _dump(summary), "OWNER_DECISION_MATRIX-v2.md": matrix,
            "resolution-proposals-v2-report.md": report,
        }
        for name, text in files.items():
            (out_dir / name).write_text(text, encoding="utf-8", newline="\n")
        body = {"version": "v2.0.2-coordinate-resolution-proposals-v2", "rule_version": RULE_VERSION,
                "schema": "quote-only-no-model-coordinates", "anchor_algorithm_version": ANCHOR_ALGORITHM_VERSION,
                "timestamp": TIMESTAMP, "model": MODEL, "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS,
                "thinking": EXTRA_BODY, "activation_blocked": True, "counts": summary,
                "outputs": {n: hashlib.sha256((out_dir / n).read_bytes()).hexdigest() for n in files},
                "lineage_note": "Flash-only quote-only batch; do not mix with prior Pro results",
                "retry_policy": {"gateway_max_retries": MAX_PROBE_RETRIES}}
        body["manifest_sha256"] = hashlib.sha256((json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()).hexdigest()
        (out_dir / "manifest.json").write_text(_dump(body), encoding="utf-8", newline="\n")
        return {"proposals": proposals, "summary": summary, "manifest": body}
    except Exception:
        if out_dir.exists():
            shutil.rmtree(out_dir)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-json", action="store_true")
    args = parser.parse_args(argv)
    if args.probe_json:
        print(json.dumps({"model": MODEL, "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS}, sort_keys=True))
    else:
        print(json.dumps(run()["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
