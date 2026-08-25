"""Build the fail-closed v2.0.4 conservative reannotation candidate."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import corpus_v2_evidence_coordinate_repair as coord
from scripts import corpus_v2_owner_authorized_evidence_reannotation as v203

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "evaluation/datasets/v2/revisions/v2.0.2-evidence-coordinate-repair"
AUDIT = ROOT / "evaluation/datasets/v2/revisions/v2.0.3-owner-authorized-evidence-reannotation/blocker-audit"
DRAFT = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"
EVIDENCE = ROOT / "evaluation/datasets/v2/automated-review/automated-review-evidence.jsonl"
CHUNKS = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
V2_MANIFEST = BASE / "manifest.json"
UNRESOLVED = BASE / "coordinate-unresolved.jsonl"
MIGRATION = BASE / "coordinate-migration.jsonl"
DEFAULT_OUT = ROOT / "evaluation/datasets/v2/revisions/v2.0.4-owner-authorized-conservative-reannotation"
MODEL = "deepseek-v4-flash"
TEMPERATURE = 0.0
MAX_TOKENS = 8000
MAX_RETRIES = 3
EXTRA_BODY = {"thinking": {"type": "disabled"}}
CONTRACT = "raw-codepoint-v1"
RULE_VERSION = "v2.0.4-owner-authorized-conservative-reannotation-1"
TIMESTAMP = "2026-08-10T00:00:00+00:00"
TARGET_GROUPS = {
    "scoped_chunk_evidence_absent": {"zh-032", "zh-033"},
    "answer_semantics_not_directly_supported": {"mixed-022", "mixed-028", "mixed-029", "zh-026", "zh-029", "zh-036", "zh-054", "zh-055"},
    "model_or_schema_action_invalid": {"zh-023", "zh-035", "zh-037"},
}
EXPECTED_CASE_IDS = frozenset().union(*map(frozenset, TARGET_GROUPS.values()))
ALLOWED_FIELDS = {"action", "answer_point_index", "anchor_id", "rationale", "risk"}
ACTIONS = {"retain_with_anchor", "keep_unresolved"}
RISKS = {"low", "medium", "high"}


class ReannotationError(Exception):
    """预检、模型契约或候选构建失败。"""


@dataclass(frozen=True)
class Inputs:
    unresolved: list[dict]
    blockers: list[dict]
    migration: list[dict]
    draft: list[dict]
    evidence: list[dict]
    chunks: dict[str, dict]
    manifest: dict
    target_case_ids: frozenset[str]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = hashlib.sha256(_dump(result).encode()).hexdigest()
    return result


def build_anchor_catalog(chunks: list[dict]) -> list[dict]:
    return v203.build_anchor_catalog(chunks)


def validate_llm_response(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != ALLOWED_FIELDS:
        raise ReannotationError("LLM schema must be anchor-only and exact")
    if value["action"] not in ACTIONS:
        raise ReannotationError("invalid action")
    if isinstance(value["answer_point_index"], bool) or not isinstance(value["answer_point_index"], int) or value["answer_point_index"] < 0:
        raise ReannotationError("invalid answer point index")
    if not isinstance(value["anchor_id"], str) or not value["anchor_id"]:
        raise ReannotationError("anchor_id is required")
    if not isinstance(value["rationale"], str) or not value["rationale"].strip() or value["risk"] not in RISKS:
        raise ReannotationError("invalid rationale or risk")
    return value


def resolve_anchor_response(response: dict, chunk: dict, catalog: dict, *, original_answer: str, preserve_original: bool) -> dict:
    value = validate_llm_response(response)
    anchor = next((a for a in catalog["anchors"] if a["anchor_id"] == value["anchor_id"]), None)
    if anchor is None or anchor["chunk_id"] != chunk["chunk_id"] or anchor["source"] != chunk.get("source"):
        raise ReannotationError("anchor does not belong to declared chunk")
    rng = anchor["raw_chunk_char_range"]
    span = anchor["raw_span"]
    if chunk["text"][rng["start"]:rng["end"]] != span or not span:
        raise ReannotationError("raw anchor proof failed")
    # Only presentation line-ending normalization is allowed; content is local raw text.
    revised = original_answer if preserve_original else span.replace("\r\n", "\n").replace("\r", "\n")
    return {"action": value["action"], "answer_point_index": value["answer_point_index"], "anchor_id": value["anchor_id"], "revised_answer_point": revised, "raw_evidence_span": span, "raw_chunk_char_range": dict(rng), "coordinate_contract": CONTRACT, "rationale": value["rationale"], "risk": value["risk"]}


def _call(messages: list[dict], llm_fn: Callable | None) -> tuple[str, str | None]:
    if llm_fn is not None:
        result = llm_fn(messages=messages, model=MODEL, temperature=TEMPERATURE, max_tokens=MAX_TOKENS, extra_body=EXTRA_BODY)
        if not isinstance(result, tuple) or len(result) != 2:
            raise ReannotationError("invalid LLM result")
        return result
    from src.llm_gateway import llm_call
    response, _record = llm_call("v204_conservative_reannotation", messages, model=MODEL, temperature=TEMPERATURE, max_tokens=MAX_TOKENS, max_retries=MAX_RETRIES, extra_body=EXTRA_BODY)
    choices = getattr(response, "choices", None) or []
    content = getattr(getattr(choices[0], "message", None), "content", None) if choices else None
    if not isinstance(content, str):
        raise ReannotationError("LLM response content missing")
    return content, getattr(response, "model", None)


def _parse(content: str, returned_model: str | None) -> dict:
    if returned_model != MODEL:
        raise ReannotationError("LLM model identity mismatch")
    try:
        value = json.loads(content.lstrip("\ufeff").strip())
    except (TypeError, json.JSONDecodeError) as exc:
        raise ReannotationError("LLM response is not strict JSON") from exc
    return validate_llm_response(value)


def load_inputs() -> Inputs:
    manifest = json.loads(V2_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("counts") != {"evidence": 161, "migrated": 148, "unresolved": 13} or manifest.get("activation_blocked") is not True:
        raise ReannotationError("v2.0.2 baseline gate failed")
    unresolved, migration, draft, evidence = _jsonl(UNRESOLVED), _jsonl(MIGRATION), _jsonl(DRAFT), _jsonl(EVIDENCE)
    blockers = _jsonl(AUDIT / "blocker-root-causes.jsonl")
    chunks = {r["chunk_id"]: r for r in _jsonl(CHUNKS)}
    if len(unresolved) != 13 or len(blockers) != 13 or len(migration) != 148 or len(draft) != 150 or len(evidence) != 161:
        raise ReannotationError("baseline counts failed")
    key = lambda r: (r.get("case_id"), r.get("chunk_id"), r.get("source_id"))
    if {key(r) for r in unresolved} != {key(r) for r in blockers}:
        raise ReannotationError("unresolved/blocker set mismatch")
    by_cat = {cat: {r["case_id"] for r in blockers if r.get("root_cause_category") == cat} for cat in TARGET_GROUPS}
    if by_cat != TARGET_GROUPS or set().union(*by_cat.values()) != set(EXPECTED_CASE_IDS):
        raise ReannotationError("target groups mismatch")
    for row in unresolved:
        if row["chunk_id"] not in chunks or chunks[row["chunk_id"]].get("source") != row["source_id"]:
            raise ReannotationError("source/chunk mismatch")
    return Inputs(unresolved, blockers, migration, draft, evidence, chunks, manifest, frozenset(EXPECTED_CASE_IDS))


def _target_evidence(row: dict, chunk: dict, resolved: dict) -> dict:
    out = dict(row)
    span = resolved["raw_evidence_span"]
    out.pop("char_range", None); out.pop("char_range_start", None); out.pop("char_range_end", None)
    out.update({"source_id": chunk["source"], "chunk_text_sha256": _sha_text(chunk["text"]), "coordinate_contract": CONTRACT, "raw_chunk_char_range": resolved["raw_chunk_char_range"], "raw_evidence_span": span, "snippet": coord.display_snippet(span), "snippet_sha256": coord.sha256_text(coord.display_snippet(span))})
    return out


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _quality(rows: list[dict], chunks: dict[str, dict]) -> dict:
    checks = {"row_count": len(rows), "unique_case_chunk": len({(r.get("case_id"), r.get("chunk_id")) for r in rows}), "raw_contiguous": True, "source_consistent": True}
    try: coord.strict_validate(rows, chunks)
    except Exception as exc: checks.update(raw_contiguous=False, error=str(exc))
    return {"skill": {"name": "data-analytics:analyze-data-quality", "available": False, "failure": "Skill not found: data-analytics:analyze-data-quality"}, "equivalent_deterministic_checks": checks}


def run(*, out_dir: Path = DEFAULT_OUT, llm_fn: Callable | None = None) -> dict:
    inputs = load_inputs()
    if out_dir.exists(): shutil.rmtree(out_dir)
    catalogs = {r["chunk_id"]: r for r in build_anchor_catalog(list(inputs.chunks.values()))}
    blockers: list[dict] = []
    selections: list[dict] = []
    resolved_by_case: dict[str, dict] = {}
    draft_map = {r["id"]: r for r in inputs.draft}
    by_case_evidence = {case: [r for r in inputs.evidence if r.get("case_id") == case] for case in inputs.target_case_ids}
    for blocker in sorted(inputs.blockers, key=lambda r: r["case_id"]):
        case_id, chunk_id = blocker["case_id"], blocker["chunk_id"]
        case, chunk, catalog = draft_map[case_id], inputs.chunks[chunk_id], catalogs[chunk_id]
        category = blocker["root_cause_category"]
        if category == "scoped_chunk_evidence_absent":
            points = case.get("acceptable_answer_points") or []
            if len(points) <= 1 or case.get("should_refuse") is False:
                blockers.append({**{k: blocker.get(k) for k in ("case_id", "chunk_id", "source_id")}, "reason": "deleting unsupported points would leave an answerable case with zero answer points"})
                continue
            # The audit identifies each absent case as having no scoped support;
            # remove all its unsupported points and their case-local evidence.
            resolved_by_case[case_id] = {"action": "remove_answer_points", "removed_points": list(points), "raw_evidence_span": None, "raw_chunk_char_range": None}
            selections.append({"case_id": case_id, "chunk_id": chunk_id, "source_id": chunk["source"], "action": "remove_answer_points", "removed_points": list(points)})
            continue
        try:
            payload = {"case_id": case_id, "query": case.get("query", ""), "answer_points": case.get("acceptable_answer_points", []), "declared_chunk": {"chunk_id": chunk_id, "source": chunk["source"]}, "anchors": catalog["anchors"]}
            content, returned_model = _call([{"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)}], llm_fn)
            parsed = _parse(content, returned_model)
            if parsed["answer_point_index"] >= len(case.get("acceptable_answer_points") or []): raise ReannotationError("answer point index out of range")
            resolved = resolve_anchor_response(parsed, chunk, catalog, original_answer=case["acceptable_answer_points"][parsed["answer_point_index"]], preserve_original=category == "model_or_schema_action_invalid")
            if category == "model_or_schema_action_invalid" and resolved["raw_evidence_span"].replace("\r\n", " ").find(case["acceptable_answer_points"][0]) < 0:
                raise ReannotationError("selected anchor does not directly support original answer point")
            resolved_by_case[case_id] = resolved
            selections.append({"case_id": case_id, "chunk_id": chunk_id, "source_id": chunk["source"], "response": parsed, "resolved": resolved})
        except Exception as exc:
            blockers.append({"case_id": case_id, "chunk_id": chunk_id, "source_id": chunk["source"], "reason": type(exc).__name__ + ": " + str(exc)[:240]})
    common = {"revision_status": "CANDIDATE", "activation_blocked": True, "reannotation_actor": "LLM_ASSISTED_OWNER_AUTHORIZED", "human_reviewed": False, "rule_version": RULE_VERSION, "timestamp": TIMESTAMP, "model": MODEL, "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS, "thinking": EXTRA_BODY}
    input_hashes = {name: _sha(path) for name, path in (("draft", DRAFT), ("evidence", EVIDENCE), ("chunks", CHUNKS), ("chunk_manifest", CHUNK_MANIFEST), ("v2_manifest", V2_MANIFEST), ("unresolved", UNRESOLVED), ("migration", MIGRATION))}
    out_dir.mkdir(parents=True, exist_ok=True)
    if blockers:
        files = {"reannotation-blockers.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in blockers), "REANNOTATION_REPORT.md": "# v2.0.4 Conservative Reannotation\n\n构建被 fail-closed 阻断，未生成任何 after 文件。此产物不是人工审核、active 版本、overlay 或 v2.1 准入。\n", "ACTIVATION_BLOCKED.md": "# Activation blocked\n\nCandidate only; no activation metadata or overlay was generated.\n"}
        for name, content in files.items(): _atomic_write(out_dir / name, content)
        manifest = _manifest({**common, "status": "BLOCKED", "counts": {"targets": 13, "blockers": len(blockers)}, "inputs": input_hashes, "outputs": {n: _sha(out_dir / n) for n in files}})
        _atomic_write(out_dir / "manifest.json", _dump(manifest))
        return {"status": "BLOCKED", "manifest": manifest, "blockers": blockers}
    # Construct candidate files only after every target has passed its local checks.
    draft_after = [dict(row) for row in inputs.draft]
    evidence_after = []
    migration_after = { (r["case_id"], r["chunk_id"]): r["after"] for r in inputs.migration if r.get("status") == "migrated" and isinstance(r.get("after"), dict) }
    for row in inputs.evidence:
        key = (row.get("case_id"), row.get("chunk_id"))
        if key in migration_after:
            evidence_after.append(dict(migration_after[key]))
        else:
            raise ReannotationError("missing migrated evidence baseline")
    deleted = []
    diffs = []
    for case_id, resolved in resolved_by_case.items():
        case = next(row for row in draft_after if row["id"] == case_id)
        before_points = list(case.get("acceptable_answer_points") or [])
        if resolved.get("action") == "remove_answer_points":
            case["acceptable_answer_points"] = []
            for row in list(evidence_after):
                if row.get("case_id") == case_id:
                    deleted.append({"case_id": case_id, "chunk_id": row.get("chunk_id"), "reason": "orphan evidence after unsupported answer-point deletion", "evidence": row})
                    evidence_after.remove(row)
            after_points = []
        else:
            index = resolved["answer_point_index"]
            case["acceptable_answer_points"] = list(before_points)
            case["acceptable_answer_points"][index] = resolved["revised_answer_point"]
            candidates = [row for row in evidence_after if row.get("case_id") == case_id and row.get("chunk_id") == next(b["chunk_id"] for b in inputs.blockers if b["case_id"] == case_id)]
            if not candidates:
                raise ReannotationError("target evidence row missing")
            replacement = _target_evidence(candidates[0], inputs.chunks[next(b["chunk_id"] for b in inputs.blockers if b["case_id"] == case_id)], resolved)
            evidence_after[evidence_after.index(candidates[0])] = replacement
            after_points = list(case["acceptable_answer_points"])
        diffs.append({"case_id": case_id, "action": resolved.get("action"), "answer_point_before": before_points, "answer_point_after": after_points, "anchor_id": resolved.get("anchor_id"), "raw_chunk_char_range": resolved.get("raw_chunk_char_range"), "raw_evidence_span": resolved.get("raw_evidence_span")})
    for case in draft_after:
        if case["id"] in TARGET_GROUPS["scoped_chunk_evidence_absent"] and not case.get("acceptable_answer_points"):
            raise ReannotationError("answerable case has zero answer points")
    coord.strict_validate(evidence_after, inputs.chunks)
    quality = _quality(evidence_after, inputs.chunks)
    files = {
        "draft-before.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in inputs.draft),
        "draft-after.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in draft_after),
        "evidence-before.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in inputs.evidence),
        "evidence-after.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in evidence_after),
        "reannotation-diff.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in diffs),
        "deleted-orphan-evidence.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in deleted),
        "raw-anchor-catalog.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in catalogs.values()),
        "llm-anchor-selections.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in selections),
        "coordinate-validation-report.json": _dump({"contract": CONTRACT, "strict_valid": True, "before_evidence": len(inputs.evidence), "after_evidence": len(evidence_after)}),
        "data-quality-report.json": _dump(quality),
        "REANNOTATION_REPORT.md": "# v2.0.4 Conservative Reannotation\n\n这是用户授权的 LLM 辅助 candidate 重标注，不是人工审核、active 版本、overlay 或 v2.1 准入。\n\n所有保留 evidence 已通过 raw-codepoint-v1 strict validator。\n",
        "ACTIVATION_BLOCKED.md": "# Activation blocked\n\nCandidate only; activation remains blocked and no overlay or active metadata was generated.\n",
    }
    for name, content in files.items(): _atomic_write(out_dir / name, content)
    manifest = _manifest({**common, "status": "CANDIDATE", "coordinate_contract": CONTRACT, "counts": {"targets": 13, "evidence_before": len(inputs.evidence), "evidence_after": len(evidence_after), "deleted_orphan_evidence": len(deleted), "blockers": 0}, "inputs": input_hashes, "outputs": {n: _sha(out_dir / n) for n in files}})
    _atomic_write(out_dir / "manifest.json", _dump(manifest))
    return {"status": "CANDIDATE", "manifest": manifest, "diffs": diffs}


if __name__ == "__main__":
    run()
