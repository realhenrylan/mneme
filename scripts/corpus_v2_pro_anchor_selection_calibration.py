"""Calibrate Pro-only raw-anchor selection without modifying v2 data."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import corpus_v2_evidence_coordinate_repair as coord
from scripts import corpus_v2_v204_conservative_reannotation as v204

ROOT = Path(__file__).resolve().parents[1]
V204_OUT = v204.DEFAULT_OUT
OUT = V204_OUT / "pro-anchor-calibration"
MODEL = "deepseek-v4-pro"
TEMPERATURE = 0.0
MAX_TOKENS = 8000
MAX_RETRIES = 3
EXTRA_BODY = {"thinking": {"type": "disabled"}}
CONTRACT = "raw-codepoint-v1"
TIMESTAMP = "2026-08-10T00:00:00+00:00"
ALLOWED_FIELDS = {"action", "answer_point_index", "anchor_id", "rationale", "risk"}
ACTIONS = {"select_anchor", "no_valid_anchor"}
RISKS = {"low", "medium", "high"}
EXPECTED_CASE_IDS = v204.EXPECTED_CASE_IDS


class CalibrationError(Exception):
    """输入、模型契约或本地 anchor 校验失败。"""


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def build_anchor_catalog(chunks: list[dict]) -> list[dict]:
    return v204.build_anchor_catalog(chunks)


def build_payload(query: str, answer_points: list[str], catalog: dict) -> dict:
    """Expose only semantic prompt data and local anchor text to the model."""
    return {
        "query": query,
        "answer_points": answer_points,
        "anchors": [
            {"anchor_id": anchor["anchor_id"], "raw_span": anchor["raw_span"]}
            for anchor in catalog["anchors"]
        ],
    }


def validate_model_response(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != ALLOWED_FIELDS:
        raise CalibrationError("model schema must contain exact anchor-only fields")
    if value["action"] not in ACTIONS:
        raise CalibrationError("invalid calibration action")
    index = value["answer_point_index"]
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise CalibrationError("invalid answer point index")
    anchor_id = value["anchor_id"]
    if value["action"] == "select_anchor":
        if not isinstance(anchor_id, str) or not anchor_id:
            raise CalibrationError("select_anchor requires anchor_id")
    elif anchor_id is not None:
        raise CalibrationError("no_valid_anchor requires null anchor_id")
    if not isinstance(value["rationale"], str) or not value["rationale"].strip():
        raise CalibrationError("rationale is required")
    if value["risk"] not in RISKS:
        raise CalibrationError("invalid risk")
    return value


def validate_anchor_selection(response: dict, chunk: dict, catalog: dict) -> dict:
    value = validate_model_response(response)
    if value["action"] == "no_valid_anchor":
        return {
            "valid": True,
            "action": value["action"],
            "answer_point_index": value["answer_point_index"],
            "anchor_id": None,
            "raw_chunk_char_range": None,
            "raw_evidence_span": None,
            "coordinate_contract": CONTRACT,
        }
    anchor = next((a for a in catalog["anchors"] if a["anchor_id"] == value["anchor_id"]), None)
    if anchor is None:
        raise CalibrationError("anchor_id is not in the declared catalog")
    if anchor["chunk_id"] != chunk["chunk_id"] or anchor["source"] != chunk["source"]:
        raise CalibrationError("anchor ownership mismatch")
    raw_range = anchor["raw_chunk_char_range"]
    raw_span = anchor["raw_span"]
    if not isinstance(raw_range, dict) or not isinstance(raw_span, str) or not raw_span:
        raise CalibrationError("anchor is incomplete")
    coord.validate_raw_record(chunk["chunk_id"], chunk["source"], chunk["text"], raw_range, raw_span)
    return {
        "valid": True,
        "action": value["action"],
        "answer_point_index": value["answer_point_index"],
        "anchor_id": anchor["anchor_id"],
        "raw_chunk_char_range": dict(raw_range),
        "raw_evidence_span": raw_span,
        "coordinate_contract": CONTRACT,
    }


def _call(messages: list[dict], llm_fn: Callable | None) -> tuple[str, str | None]:
    if llm_fn is not None:
        result = llm_fn(
            messages=messages, model=MODEL, temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS, max_retries=MAX_RETRIES,
            extra_body=EXTRA_BODY,
        )
        if not isinstance(result, tuple) or len(result) != 2:
            raise CalibrationError("invalid LLM result")
        return result
    from src.llm_gateway import llm_call
    response, _record = llm_call(
        "v204_pro_anchor_calibration", messages, model=MODEL,
        temperature=TEMPERATURE, max_tokens=MAX_TOKENS,
        max_retries=MAX_RETRIES, extra_body=EXTRA_BODY,
    )
    choices = getattr(response, "choices", None) or []
    content = getattr(getattr(choices[0], "message", None), "content", None) if choices else None
    if not isinstance(content, str):
        raise CalibrationError("LLM response content missing")
    return content, getattr(response, "model", None)


def _parse(content: str, returned_model: str | None) -> dict:
    if returned_model != MODEL:
        raise CalibrationError("LLM model identity mismatch")
    try:
        value = json.loads(content.lstrip("\ufeff").strip())
    except (TypeError, json.JSONDecodeError) as exc:
        raise CalibrationError("LLM response is not strict JSON") from exc
    return validate_model_response(value)


def _load_inputs():
    inputs = v204.load_inputs()
    if len(inputs.target_case_ids) != 13:
        raise CalibrationError("target set must contain exactly 13 cases")
    # Validate all catalogs before any model call, so malformed local evidence fails closed.
    catalogs = {row["chunk_id"]: row for row in build_anchor_catalog(list(inputs.chunks.values()))}
    for blocker in inputs.blockers:
        catalog = catalogs.get(blocker["chunk_id"])
        chunk = inputs.chunks.get(blocker["chunk_id"])
        if catalog is None or chunk is None or blocker["source_id"] != chunk["source"]:
            raise CalibrationError("blocker source/chunk gate failed")
        for anchor in catalog["anchors"]:
            coord.validate_raw_record(chunk["chunk_id"], chunk["source"], chunk["text"], anchor["raw_chunk_char_range"], anchor["raw_span"])
    return inputs, catalogs


def _flash_comparison() -> dict:
    manifest_path = V204_OUT / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationError(f"v2.0.4 Flash manifest unavailable: {exc}") from exc
    return {
        "model": manifest.get("model"),
        "status": manifest.get("status"),
        "targets": manifest.get("counts", {}).get("targets"),
        "flash_blockers": manifest.get("counts", {}).get("blockers"),
        "flash_successful_anchor_selections": 0,
        "interpretation": "Flash candidate was BLOCKED; Pro results are diagnostic only and are not directly comparable as an active revision.",
    }


def _manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = _sha_text(_dump(result))
    return result


def run(*, out_dir: Path = OUT, llm_fn: Callable | None = None) -> dict:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    inputs, catalogs = _load_inputs()
    draft_map = {row["id"]: row for row in inputs.draft}
    blockers = sorted(inputs.blockers, key=lambda row: row["case_id"])
    selections: list[dict] = []
    raw_responses: list[dict] = []
    validations: list[dict] = []
    try:
        for index, blocker in enumerate(blockers):
            case = draft_map[blocker["case_id"]]
            chunk = inputs.chunks[blocker["chunk_id"]]
            catalog = catalogs[blocker["chunk_id"]]
            answer_points = list(case.get("acceptable_answer_points") or [])
            payload = build_payload(case.get("query", ""), answer_points, catalog)
            try:
                content, returned_model = _call(
                    [{"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)}],
                    llm_fn,
                )
                raw_responses.append({"target_index": index, "content": content, "returned_model": returned_model})
                parsed = _parse(content, returned_model)
                if parsed["answer_point_index"] >= len(answer_points):
                    raise CalibrationError("answer point index out of range")
                local = validate_anchor_selection(parsed, chunk, catalog)
            except Exception as exc:
                raw_responses.append({"target_index": index, "content": None, "returned_model": None, "error": f"{type(exc).__name__}: {exc}"})
                validations.append({"target_index": index, "status": "model_or_transport_failure", "error": f"{type(exc).__name__}: {exc}"})
                raise
            selections.append({"target_index": index, "response": parsed, "local": local})
            validations.append({"target_index": index, "status": "valid", "local": local})
    except Exception as exc:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise CalibrationError(f"target calibration failed: {type(exc).__name__}: {exc}") from exc
    summary = {
        "targets": 13,
        "json_valid": len(selections),
        "valid_anchor_selections": sum(row["response"]["action"] == "select_anchor" for row in selections),
        "no_valid_anchor": sum(row["response"]["action"] == "no_valid_anchor" for row in selections),
        "model_or_transport_failures": 0,
        "flash_comparison": _flash_comparison(),
    }
    input_paths = {
        "v204_manifest": v204.V2_MANIFEST, "unresolved": v204.UNRESOLVED,
        "migration": v204.MIGRATION, "draft": v204.DRAFT, "chunks": v204.CHUNKS,
        "chunk_manifest": v204.CHUNK_MANIFEST, "v204_blockers": v204.AUDIT / "blocker-root-causes.jsonl",
    }
    files: dict[str, str] = {
        "pro-anchor-selections.jsonl": "".join(_dump(row) for row in selections),
        "raw-model-responses.jsonl": "".join(_dump(row) for row in raw_responses),
        "local-anchor-validation.jsonl": "".join(_dump(row) for row in validations),
        "calibration-summary.json": _dump(summary),
        "calibration-report.md": "# v2.0.4 Pro raw-anchor selection calibration\n\n" +
        "本报告仅记录 deepseek-v4-pro 的只读 anchor 选择诊断，不是 candidate 应用、人工审核、active 版本、overlay 或 v2.1 准入。\n\n" +
        f"- JSON 合法：{summary['json_valid']}/13\n- 有效 anchor 选择：{summary['valid_anchor_selections']}\n- no_valid_anchor：{summary['no_valid_anchor']}\n- 模型/传输失败：{summary['model_or_transport_failures']}\n\n" +
        "Flash 对照仅引用既有 BLOCKED manifest；任何 Pro 结果仍需后续人工/治理审查，不能自动应用。\n",
    }
    input_hashes = {name: _sha(path) for name, path in input_paths.items()}
    staging = Path(tempfile.mkdtemp(prefix=".pro-anchor-calibration-", dir=out_dir.parent))
    try:
        for name, content in files.items():
            _atomic_write(staging / name, content)
        manifest = _manifest({
            "revision_status": "CANDIDATE", "activation_blocked": True,
            "human_reviewed": False, "calibration_only": True,
            "reannotation_actor": "LLM_ASSISTED_OWNER_AUTHORIZED",
            "status": "CALIBRATED", "model": MODEL, "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS, "max_retries": MAX_RETRIES,
            "thinking": EXTRA_BODY, "coordinate_contract": CONTRACT,
            "counts": summary, "inputs": input_hashes,
            "forbidden_outputs": ["draft-after.jsonl", "evidence-after.jsonl", "overlay", "active metadata", "v2.1"],
            "outputs": {name: _sha(staging / name) for name in files},
            "timestamp": TIMESTAMP,
        })
        _atomic_write(staging / "manifest.json", _dump(manifest))
        os.replace(staging, out_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(out_dir, ignore_errors=True)
        raise
    return {"status": "CALIBRATED", "summary": summary, "manifest": manifest}


if __name__ == "__main__":
    run()
