"""Build a fail-closed, owner-authorized v2.0.3 evidence candidate.

The model selects a program-created raw anchor. Local code owns all coordinates,
raw spans, and candidate validation; no active corpus or historical revision is
modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import corpus_v2_evidence_coordinate_repair as coord
from src.llm_gateway import llm_call

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "evaluation/datasets/v2/revisions/v2.0.2-evidence-coordinate-repair"
DEFAULT_OUT = ROOT / "evaluation/datasets/v2/revisions/v2.0.3-owner-authorized-evidence-reannotation"
UNRESOLVED = BASE / "coordinate-unresolved.jsonl"
MIGRATION = BASE / "coordinate-migration.jsonl"
V2_MANIFEST = BASE / "manifest.json"
DRAFT = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"
CHUNKS = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
EVIDENCE = ROOT / "evaluation/datasets/v2/automated-review/automated-review-evidence.jsonl"
MODEL = "deepseek-v4-flash"
TEMPERATURE = 0.0
MAX_TOKENS = 8000
MAX_RETRIES = 3
EXTRA_BODY = {"thinking": {"type": "disabled"}}
CANDIDATE_STATUS = "CANDIDATE"
COORDINATE_CONTRACT = "raw-codepoint-v1"
RULE_VERSION = "v2.0.3-owner-authorized-evidence-reannotation-1"
TIMESTAMP = "2026-08-10T00:00:00+00:00"
ACTIONS = {"retain_with_anchor", "narrow_answer_point_with_anchor", "remove_answer_point", "keep_unresolved"}
RISKS = {"low", "medium", "high"}
ALLOWED_RESPONSE_FIELDS = {"action", "answer_point_index", "anchor_id", "revised_answer_point", "rationale", "risk"}
SYSTEM_PROMPT = """你是受所有者授权的离线 evidence 重标注助手。只能从输入提供的原始 anchor_id 中选择一个原文单元，不能输出坐标、quote 或自由定位文本。只输出精确 JSON 字段：action, answer_point_index, anchor_id, revised_answer_point, rationale, risk。action 必须为 retain_with_anchor、narrow_answer_point_with_anchor、remove_answer_point、keep_unresolved 之一。对保留/收窄必须选择 anchor_id 并给出有该原文直接支持的非空 revised_answer_point；remove_answer_point 仅在 scoped 原文明确没有支持时使用；无法证明则 keep_unresolved。"""


class ReannotationError(Exception):
    """输入、模型响应或候选重建失败。"""


@dataclass(frozen=True)
class Inputs:
    unresolved: list[dict]
    migration: list[dict]
    draft: list[dict]
    chunks: dict[str, dict]
    evidence: list[dict]
    candidate_manifest: dict


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = hashlib.sha256(_dump(result).encode("utf-8")).hexdigest()
    return result


def validate_llm_response(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != ALLOWED_RESPONSE_FIELDS:
        raise ReannotationError("LLM schema must contain exactly the quote-free fields")
    if value["action"] not in ACTIONS:
        raise ReannotationError("invalid reannotation action")
    if isinstance(value["answer_point_index"], bool) or not isinstance(value["answer_point_index"], int) or value["answer_point_index"] < 0:
        raise ReannotationError("invalid answer_point_index")
    if value["anchor_id"] is not None and not isinstance(value["anchor_id"], str):
        raise ReannotationError("invalid anchor_id")
    if value["revised_answer_point"] is not None and not isinstance(value["revised_answer_point"], str):
        raise ReannotationError("invalid revised_answer_point")
    if not isinstance(value["rationale"], str) or value["risk"] not in RISKS:
        raise ReannotationError("invalid rationale or risk")
    if value["action"] in {"retain_with_anchor", "narrow_answer_point_with_anchor"} and (not value["anchor_id"] or not value["revised_answer_point"].strip()):
        raise ReannotationError("anchored action requires anchor and revised answer point")
    if value["action"] == "remove_answer_point" and value["revised_answer_point"] is not None:
        raise ReannotationError("remove action cannot invent a replacement")
    if value["action"] in {"remove_answer_point", "keep_unresolved"} and value["anchor_id"] is not None:
        raise ReannotationError("unanchored action cannot provide anchor")
    return value


def _units(text: str) -> list[tuple[int, int, str]]:
    lines = text.splitlines(keepends=True)
    result: list[tuple[int, int, str]] = []
    offset = 0
    for line in lines:
        end = offset + len(line)
        raw = line.rstrip("\r\n")
        if raw:
            result.append((offset, offset + len(raw), raw))
        offset = end
    if not lines and text:
        result.append((0, len(text), text))
    return result


def build_anchor_catalog(chunks: list[dict]) -> list[dict]:
    output = []
    for chunk in sorted(chunks, key=lambda r: r["chunk_id"]):
        anchors = []
        for index, (start, end, raw) in enumerate(_units(chunk.get("text", ""))):
            anchor_id = f"{chunk['chunk_id']}::a{index:04d}"
            anchors.append({"anchor_id": anchor_id, "chunk_id": chunk["chunk_id"], "source": chunk.get("source"), "raw_span": raw, "raw_chunk_char_range": {"start": start, "end": end}, "snippet": raw, "coordinate_contract": COORDINATE_CONTRACT})
        output.append({"chunk_id": chunk["chunk_id"], "source": chunk.get("source"), "anchors": anchors})
    return output


def _parse_response(content: str, returned_model: str | None) -> dict:
    if returned_model != MODEL:
        raise ReannotationError("LLM model identity mismatch")
    text = content.lstrip("\ufeff").strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ReannotationError("LLM response is not strict JSON") from exc
    return validate_llm_response(value)


def _call(messages: list[dict], llm_fn: Callable | None) -> tuple[str, str | None]:
    if llm_fn is not None:
        result = llm_fn(messages=messages, model=MODEL, temperature=TEMPERATURE, max_tokens=MAX_TOKENS)
        if not isinstance(result, tuple) or len(result) != 2:
            raise ReannotationError("invalid LLM result")
        return result
    response, _record = llm_call("owner_authorized_evidence_reannotation", messages, model=MODEL, temperature=TEMPERATURE, max_tokens=MAX_TOKENS, max_retries=MAX_RETRIES, extra_body=EXTRA_BODY)
    choices = getattr(response, "choices", None) or []
    content = getattr(getattr(choices[0], "message", None), "content", None) if choices else None
    if not isinstance(content, str):
        raise ReannotationError("LLM response content missing")
    return content, getattr(response, "model", None)


def resolve_response(case: dict, declared: dict, chunk: dict, catalog: dict, response: dict, answer_index: int) -> dict:
    response = validate_llm_response(response)
    if response["answer_point_index"] != answer_index:
        raise ReannotationError("answer point index mismatch")
    result = {"action": response["action"], "answer_point_index": answer_index, "revised_answer_point": response["revised_answer_point"], "rationale": response["rationale"], "risk": response["risk"], "anchor_id": response["anchor_id"], "raw_evidence_span": None, "raw_chunk_char_range": None, "coordinate_contract": COORDINATE_CONTRACT}
    if response["action"] in {"retain_with_anchor", "narrow_answer_point_with_anchor"}:
        if declared.get("chunk_id") != chunk.get("chunk_id") or declared.get("source_id", declared.get("source")) != chunk.get("source"):
            raise ReannotationError("declared source/chunk mismatch")
        anchor = next((a for a in catalog["anchors"] if a["anchor_id"] == response["anchor_id"]), None)
        if anchor is None or anchor["chunk_id"] != chunk["chunk_id"] or anchor["source"] != chunk.get("source"):
            raise ReannotationError("anchor does not belong to declared chunk")
        span = anchor["raw_span"]; rng = anchor["raw_chunk_char_range"]
        if chunk["text"][rng["start"]:rng["end"]] != span:
            raise ReannotationError("raw anchor cannot be reconstructed")
        result.update(raw_evidence_span=span, raw_chunk_char_range=rng, snippet=span)
    elif response["action"] == "remove_answer_point" and not any(token in response["rationale"].lower() for token in ("no support", "无支持", "没有支持", "unsupported")):
        raise ReannotationError("remove requires explicit no-support rationale")
    return result


def validate_answer_points(points: list[str], answerable: bool) -> None:
    if answerable and not points:
        raise ReannotationError("answerable case cannot have zero answer points")


def load_inputs() -> Inputs:
    manifest = json.loads(V2_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("counts") != {"evidence": 161, "migrated": 148, "unresolved": 13} or not manifest.get("activation_blocked"):
        raise ReannotationError("v2.0.2 baseline failed")
    unresolved = _jsonl(UNRESOLVED); migration = _jsonl(MIGRATION); draft = _jsonl(DRAFT); evidence = _jsonl(EVIDENCE)
    chunks_list = _jsonl(CHUNKS); chunks = {r["chunk_id"]: r for r in chunks_list}
    if len(unresolved) != 13 or len(draft) != 150 or len(evidence) != 161 or len(migration) != 148:
        raise ReannotationError("baseline counts failed")
    if len({r["case_id"] for r in unresolved}) != 13 or len({r["id"] for r in draft}) != 150:
        raise ReannotationError("baseline uniqueness failed")
    for row in unresolved:
        if row["chunk_id"] not in chunks or chunks[row["chunk_id"]]["source"] != row["source_id"]:
            raise ReannotationError("unresolved source/chunk mismatch")
    return Inputs(unresolved, migration, draft, chunks, evidence, manifest)


def validate_candidate_evidence(rows: list[dict], chunks: dict[str, dict]) -> None:
    if len(rows) != 161:
        raise ReannotationError("candidate evidence must contain 161 rows")
    for row in rows:
        rng = row.get("raw_chunk_char_range"); span = row.get("raw_evidence_span")
        chunk = chunks.get(row.get("chunk_id"))
        if not chunk or not isinstance(rng, dict) or not isinstance(span, str) or chunk["text"][rng["start"]:rng["end"]] != span:
            raise ReannotationError("candidate evidence raw proof failed")


def run(*, out_dir: Path = DEFAULT_OUT, llm_fn: Callable | None = None) -> dict:
    try:
        inputs = load_inputs()
        catalogs = {c["chunk_id"]: c for c in build_anchor_catalog(list(inputs.chunks.values()))}
        blockers = []
        responses = []
        draft_by_id = {row["id"]: row for row in inputs.draft}
        for row in sorted(inputs.unresolved, key=lambda item: (item["case_id"], item["chunk_id"])):
            case = draft_by_id[row["case_id"]]
            chunk = inputs.chunks[row["chunk_id"]]
            catalog = catalogs[row["chunk_id"]]
            payload = {"query": case.get("query", ""), "answer_point": (case.get("acceptable_answer_points") or [""])[0], "declared_chunk": {"chunk_id": row["chunk_id"], "source": row["source_id"]}, "anchors": catalog["anchors"]}
            try:
                content, returned_model = _call([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)}], llm_fn)
                parsed = _parse_response(content, returned_model)
                resolved = resolve_response(case, {"chunk_id": row["chunk_id"], "source_id": row["source_id"]}, chunk, catalog, parsed, parsed["answer_point_index"])
                responses.append({"case_id": row["case_id"], "model": returned_model, "response": parsed, "resolved": resolved})
            except Exception as exc:
                blockers.append({"case_id": row["case_id"], "chunk_id": row["chunk_id"], "source_id": row["source_id"], "reason": type(exc).__name__ + ": " + str(exc)[:200]})
        if blockers or len(responses) != len(inputs.unresolved):
            covered = {item["case_id"] for item in blockers}
            for item in inputs.unresolved:
                if item["case_id"] not in covered:
                    blockers.append({"case_id": item["case_id"], "chunk_id": item["chunk_id"], "source_id": item["source_id"], "reason": "candidate construction blocked because all 13 authorized responses were not valid"})
            responses = []
        body = {"revision_status": CANDIDATE_STATUS, "activation_blocked": True, "reannotation_actor": "LLM_ASSISTED_OWNER_AUTHORIZED", "human_reviewed": False, "rule_version": RULE_VERSION, "timestamp": TIMESTAMP, "model": MODEL, "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS, "coordinate_contract": COORDINATE_CONTRACT, "counts": {"unresolved": 13, "blockers": len(blockers)}, "inputs": {"v2_manifest": _sha(V2_MANIFEST), "draft": _sha(DRAFT), "evidence": _sha(EVIDENCE), "chunks": _sha(CHUNKS)}}
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "reannotation-blockers.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in blockers), encoding="utf-8", newline="\n")
        (out_dir / "REANNOTATION_REPORT.md").write_text("# v2.0.3 Owner-Authorized Evidence Reannotation\n\n构建被 fail-closed 阻断；未写入 draft-after/evidence-after，v2.0.2 保持原状。此产物不是人工审核、active 版本、overlay 或 v2.1 准入。\n", encoding="utf-8", newline="\n")
        body["outputs"] = {"reannotation-blockers.jsonl": _sha(out_dir / "reannotation-blockers.jsonl"), "REANNOTATION_REPORT.md": _sha(out_dir / "REANNOTATION_REPORT.md")}
        final = _manifest(body)
        (out_dir / "manifest.json").write_text(_dump(final), encoding="utf-8", newline="\n")
        return {"status": "BLOCKED", "manifest": final, "blockers": blockers}
    except Exception:
        if out_dir.exists():
            shutil.rmtree(out_dir)
        raise


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
