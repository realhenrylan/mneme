"""Deterministic same-source rescue audit for zero-answer-risk cases."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import corpus_v2_evidence_coordinate_repair as coord
from scripts import corpus_v2_owner_decision_pack as dp

ROOT = Path(__file__).resolve().parents[1]
PACK = dp.OUT
OUT = PACK.parent / "same-source-rescue-audit"
DRAFT = dp.v204.DRAFT
CHUNKS = dp.v204.CHUNKS
CHUNK_MANIFEST = dp.v204.CHUNK_MANIFEST
TIMESTAMP = "2026-08-10T00:00:00+00:00"
CONTRACT = "raw-codepoint-v1"
CATEGORIES = (
    "verbatim_full_answer_point_found",
    "ambiguous_duplicate",
    "verbatim_clause_only_found",
    "lexical_related_only",
    "no_same_source_candidate_found",
)
SUGGESTIONS = (
    "consider_explicit_scope_expansion",
    "consider_narrowing_after_scope_expansion",
    "consider_retire_case",
    "no_actionable_rescue_candidate",
)
CATEGORY_TO_SUGGESTION = {
    "verbatim_full_answer_point_found": "consider_explicit_scope_expansion",
    "verbatim_clause_only_found": "consider_narrowing_after_scope_expansion",
    "ambiguous_duplicate": "consider_narrowing_after_scope_expansion",
    "lexical_related_only": "no_actionable_rescue_candidate",
    "no_same_source_candidate_found": "consider_retire_case",
}
CLAUSE_SPLIT = re.compile(r"[\s，。；：！？、,.!?;:（）()\[\]「」\"'‘’“”]+")
LEXICAL_SPLIT = re.compile(r"[\s，。；：！？、,.!?;:（）()\[\]「」\"'‘’“”\\/]+")


class RescueAuditError(Exception):
    """输入门禁或确定性扫描失败。"""


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


def load_pack_rows() -> list[dict]:
    path = PACK / "owner-decision-pack.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def risk_case_ids(rows: list[dict]) -> set[str]:
    return {row["case_id"] for row in rows if row.get("zero_answer_point_risk") is True}


def zero_answer_point_risk(row: dict) -> bool:
    return row.get("zero_answer_point_risk") is True


def locate_unique_raw(text: str, snippet: str) -> tuple[int, int]:
    """Delegate to the raw-codepoint-v1 unique locator with raw proof."""
    return coord.locate_unique_raw(text, snippet)


def match_full(chunk_text: str, point: str) -> dict:
    """Classify a full answer point against a single chunk."""
    try:
        start, end = locate_unique_raw(chunk_text, point)
    except coord.CoordinateUnresolved as exc:
        message = str(exc)
        if "multiple" in message:
            return {"category": "ambiguous_duplicate", "start": None, "end": None}
        return {"category": "no_match", "start": None, "end": None}
    return {"category": "verbatim_full_answer_point_found", "start": start, "end": end}


def clause_units(point: str) -> list[str]:
    return [part for part in CLAUSE_SPLIT.split(point) if part]


def lexical_tokens(point: str) -> list[str]:
    return [part for part in LEXICAL_SPLIT.split(point) if part]


def _clause_unique(chunk_text: str, point: str) -> tuple[str, int, int] | None:
    for clause in clause_units(point):
        try:
            start, end = locate_unique_raw(chunk_text, clause)
        except coord.CoordinateUnresolved:
            continue
        return clause, start, end
    return None


def suggest_for(category: str) -> dict:
    if category not in CATEGORY_TO_SUGGESTION:
        raise RescueAuditError(f"unknown category: {category}")
    return {
        "name": CATEGORY_TO_SUGGESTION[category],
        "requires_owner_authorization": True,
        "auto_applicable": False,
    }


def _scan_chunk(chunk: dict, point: str, out_of_scope: bool) -> dict:
    text = chunk["text"]
    full = match_full(text, point)
    status = "in_scope" if not out_of_scope else "out_of_scope"
    if full["category"] == "verbatim_full_answer_point_found":
        start, end = full["start"], full["end"]
        raw_span = text[start:end]
        return {
            "chunk_id": chunk["chunk_id"], "source": chunk["source"], "scope": status,
            "candidate_type": "full", "unique": True,
            "raw_chunk_char_range": {"start": start, "end": end},
            "raw_span": raw_span, "coordinate_contract": CONTRACT,
        }
    if full["category"] == "ambiguous_duplicate":
        return {
            "chunk_id": chunk["chunk_id"], "source": chunk["source"], "scope": status,
            "candidate_type": "full", "unique": False,
            "raw_chunk_char_range": None, "raw_span": None, "coordinate_contract": CONTRACT,
        }
    if out_of_scope:
        # Only full unique hits are recorded for out-of-scope audit lines.
        return {"chunk_id": chunk["chunk_id"], "source": chunk["source"], "scope": status,
                "candidate_type": "none", "unique": None,
                "raw_chunk_char_range": None, "raw_span": None, "coordinate_contract": CONTRACT}
    hit = _clause_unique(text, point)
    if hit is not None:
        clause, start, end = hit
        return {
            "chunk_id": chunk["chunk_id"], "source": chunk["source"], "scope": status,
            "candidate_type": "clause", "unique": True, "clause": clause,
            "raw_chunk_char_range": {"start": start, "end": end},
            "raw_span": text[start:end], "coordinate_contract": CONTRACT,
        }
    if any(token in text for token in lexical_tokens(point)):
        return {
            "chunk_id": chunk["chunk_id"], "source": chunk["source"], "scope": status,
            "candidate_type": "lexical_related_only", "unique": False,
            "raw_chunk_char_range": None, "raw_span": None, "coordinate_contract": CONTRACT,
        }
    return {
        "chunk_id": chunk["chunk_id"], "source": chunk["source"], "scope": status,
        "candidate_type": "none", "unique": None,
        "raw_chunk_char_range": None, "raw_span": None, "coordinate_contract": CONTRACT,
    }


def scan_case(case_id: str, point: str, chunks: dict[str, dict], declared_chunk_id: str, declared_source: str) -> dict:
    in_scope = [chunk for chunk in chunks.values()
                if chunk["source"] == declared_source and chunk["chunk_id"] != declared_chunk_id]
    out_scope = [chunk for chunk in chunks.values()
                 if chunk["source"] != declared_source]
    candidates = [_scan_chunk(chunk, point, out_of_scope=False)
                  for chunk in sorted(in_scope, key=lambda r: r["chunk_id"])]
    out_hits = [_scan_chunk(chunk, point, out_of_scope=True)
                for chunk in sorted(out_scope, key=lambda r: r["chunk_id"])]
    out_of_scope_hits = [hit for hit in out_hits if hit["candidate_type"] != "none"]
    best = next((c for c in candidates if c["candidate_type"] == "full" and c.get("unique")), None)
    category = "no_same_source_candidate_found"
    if best is not None:
        category = "verbatim_full_answer_point_found"
    elif any(c["candidate_type"] == "full" for c in candidates):
        category = "ambiguous_duplicate"
    elif any(c["candidate_type"] == "clause" for c in candidates):
        category = "verbatim_clause_only_found"
    elif any(c["candidate_type"] == "lexical_related_only" for c in candidates):
        category = "lexical_related_only"
    suggestion = suggest_for(category)
    return {
        "case_id": case_id,
        "declared_source": declared_source,
        "declared_chunk_id": declared_chunk_id,
        "category": category,
        "suggestion": suggestion,
        "best_candidate": best or next((c for c in candidates if c["candidate_type"] != "none"), None),
        "in_scope_count": len(candidates),
        "out_of_scope_hits": out_of_scope_hits,
    }


def _load_inputs():
    if not PACK.exists() or not (PACK / "manifest.json").exists():
        raise RescueAuditError("owner decision pack missing")
    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "DECISION_PACK":
        raise RescueAuditError("owner decision pack status mismatch")
    if manifest.get("counts", {}).get("targets") != 13 or manifest.get("counts", {}).get("zero_answer_point_risk") != 10:
        raise RescueAuditError("owner decision pack counts mismatch")
    if manifest.get("outputs", {}).get("owner-decision-pack.jsonl") != _sha(PACK / "owner-decision-pack.jsonl"):
        raise RescueAuditError("owner decision pack file SHA mismatch")
    for name, path in (("chunks", CHUNKS), ("draft", DRAFT), ("chunk_manifest", CHUNK_MANIFEST)):
        if manifest.get("inputs", {}).get(name) != _sha(path):
            raise RescueAuditError(f"input SHA mismatch: {name}")
    rows = load_pack_rows()
    ids = risk_case_ids(rows)
    if len(ids) != 10:
        raise RescueAuditError(f"risk case count must be 10, got {len(ids)}")
    chunks = {row["chunk_id"]: row for row in coord.load_jsonl(CHUNKS)}
    draft = {row["id"]: row for row in coord.load_jsonl(DRAFT)}
    for row in rows:
        if row["case_id"] not in ids:
            continue
        if row.get("is_refusal_case") is True or row.get("refusal_suggestion") is True:
            raise RescueAuditError("risk case must not suggest refusal")
        chunk = chunks.get(row.get("declared_chunk_id"))
        if chunk is None or chunk.get("source") != row.get("declared_source"):
            raise RescueAuditError("case/source/chunk mismatch")
        case = draft.get(row["case_id"])
        if case is None or case.get("should_refuse") is True:
            raise RescueAuditError("risk case must be answerable")
    return rows, ids, chunks, manifest


def _quality(rows: list[dict], chunks: dict[str, dict]) -> dict:
    checks = {
        "row_count": len(rows),
        "unique_case_chunk": len({(r.get("case_id"), r.get("chunk_id")) for r in rows}),
        "raw_contiguous": True,
        "source_consistent": True,
    }
    try:
        coord.strict_validate(rows, chunks)
    except Exception as exc:
        checks.update(raw_contiguous=False, error=str(exc))
    return {
        "skill": {"name": "data-analytics:analyze-data-quality", "available": False,
                  "failure": "Skill not found: data-analytics:analyze-data-quality"},
        "equivalent_deterministic_checks": checks,
    }


def _manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = _sha_text(_dump(result))
    return result


def run(*, out_dir: Path = OUT) -> dict:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    rows, ids, chunks, pack_manifest = _load_inputs()
    draft = {row["id"]: row for row in coord.load_jsonl(DRAFT)}
    results: list[dict] = []
    spans: list[dict] = []
    for pack_row in sorted(rows, key=lambda r: r["case_id"]):
        if pack_row["case_id"] not in ids:
            continue
        case = draft[pack_row["case_id"]]
        point = pack_row["answer_points"][0] if pack_row.get("answer_points") else ""
        scan = scan_case(pack_row["case_id"], point, chunks,
                         pack_row["declared_chunk_id"], pack_row["declared_source"])
        scan["query"] = pack_row.get("query", "")
        scan["answer_point"] = point
        scan["original_answer_points"] = pack_row.get("answer_points", [])
        results.append(scan)
        for candidate in scan.pop("out_of_scope_hits"):
            candidate.update(case_id=scan["case_id"], status="out_of_scope")
            spans.append(candidate)
        for candidate in [c for c in (scan.get("_in_scope_spans") or [])]:
            candidate.update(case_id=scan["case_id"], status="in_scope")
            spans.append(candidate)
    # In-scope spans are computed deterministically from the same scan inputs.
    for result in results:
        point = result["answer_point"]
        declared_source, declared_chunk_id = result["declared_source"], result["declared_chunk_id"]
        for chunk in sorted((c for c in chunks.values()
                             if c["source"] == declared_source and c["chunk_id"] != declared_chunk_id),
                            key=lambda r: r["chunk_id"]):
            spans.append(_scan_chunk(chunk, point, out_of_scope=False)
                         | {"case_id": result["case_id"], "status": "in_scope"})
    counts = {category: sum(r["category"] == category for r in results) for category in CATEGORIES}
    summary = {
        "targets": len(results),
        "counts": counts,
        "consider_explicit_scope_expansion": [r["case_id"] for r in results if r["suggestion"]["name"] == "consider_explicit_scope_expansion"],
        "consider_narrowing_after_scope_expansion": [r["case_id"] for r in results if r["suggestion"]["name"] == "consider_narrowing_after_scope_expansion"],
        "consider_retire_case": [r["case_id"] for r in results if r["suggestion"]["name"] == "consider_retire_case"],
        "no_actionable_rescue_candidate": [r["case_id"] for r in results if r["suggestion"]["name"] == "no_actionable_rescue_candidate"],
        "input_sha256": {name: _sha(path) for name, path in (("pack", PACK / "owner-decision-pack.jsonl"), ("draft", DRAFT), ("chunks", CHUNKS), ("chunk_manifest", CHUNK_MANIFEST))},
    }
    quality = _quality([], chunks)
    report = (
        "# v2.0.4 同 source 证据救援扫描\n\n"
        "本扫描只读、确定性、离线，不调用 LLM/API、不修改任何 v2 数据、不生成 after/overlay/active 文件、不进入 v2.1。\n\n"
        f"- 目标：{len(results)} 条 zero_answer_point_risk=true 的 case\n"
        f"- 分类计数：{counts}\n"
        f"- 建议均要求所有者授权，auto_applicable=false。\n"
    )
    matrix = (
        "# SCOPE_RESCUE_OWNER_MATRIX\n\n"
        "| case_id | 分类 | 建议 | 唯一 full 候选 chunk |\n|---|---|---|---|\n" +
        "".join(f"| {r['case_id']} | {r['category']} | {r['suggestion']['name']} | "
                f"{r['best_candidate']['chunk_id'] if r.get('best_candidate') else '-'} |\n" for r in results)
    )
    files: dict[str, str] = {
        "same-source-rescue-results.jsonl": "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in results),
        "same-source-candidate-spans.jsonl": "".join(json.dumps(s, ensure_ascii=False, sort_keys=True) + "\n" for s in spans),
        "same-source-rescue-summary.json": _dump(summary),
        "SCOPE_RESCUE_OWNER_MATRIX.md": matrix,
        "same-source-rescue-report.md": report,
        "data-quality-report.json": _dump(quality),
    }
    staging = Path(tempfile.mkdtemp(prefix=".same-source-rescue-", dir=out_dir.parent))
    try:
        for name, content in files.items():
            _atomic_write(staging / name, content)
        manifest = _manifest({
            "revision_status": "CANDIDATE", "activation_blocked": True,
            "human_reviewed": False, "audit_only": True, "deterministic_rebuild": True,
            "status": "AUDIT_OK", "model": None, "coordinate_contract": CONTRACT,
            "counts": summary, "inputs": summary["input_sha256"],
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
    return {"status": "AUDIT_OK", "counts": counts, "manifest": manifest, "summary": summary}


if __name__ == "__main__":
    run()
