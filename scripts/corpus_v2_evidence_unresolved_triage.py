"""Deterministic triage for the 13 unresolved v2.0.2 coordinates.

This module is read-only with respect to draft, evidence, chunks, and the
coordinate-repair candidate. It produces diagnostic candidates only; it never
writes evidence, activation metadata, overlays, or active pointers.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts import corpus_v2_evidence_coordinate_repair as coord

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "evaluation/datasets/v2/revisions/v2.0.2-evidence-coordinate-repair"
DEFAULT_UNRESOLVED = BASE / "coordinate-unresolved.jsonl"
DEFAULT_MIGRATION = BASE / "coordinate-migration.jsonl"
DEFAULT_AUDIT = BASE / "coordinate-audit-before.json"
DEFAULT_QUALITY = BASE / "coordinate-quality-report.json"
DEFAULT_MANIFEST = BASE / "manifest.json"
DEFAULT_EVIDENCE = ROOT / "evaluation/datasets/v2/automated-review/automated-review-evidence.jsonl"
DEFAULT_DRAFT = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"
DEFAULT_CHUNKS = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
DEFAULT_OUT = BASE / "unresolved-triage"
CATEGORIES = (
    "whitespace_or_line_ending_only",
    "legacy_range_disambiguable_duplicate",
    "format_transform_requires_policy",
    "semantic_or_content_drift",
    "source_or_chunk_integrity_problem",
)
RULE_VERSION = "v2.0.2-unresolved-triage-1"
TIMESTAMP = "2026-08-07T00:00:00+00:00"
SKILL_NOTE = "Skill not found: data-analytics:analyze-data-quality; deterministic equivalent checks executed"


class TriageError(Exception):
    """Fail-closed input or invariant error."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _dump_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def display_snippet(text: str) -> str:
    return coord.display_snippet(text)


def locate_whitespace_candidate(text: str, snippet: str) -> tuple[int, int]:
    return coord.locate_unique_raw(text, snippet)


def classify_difference(old: str, transformed: str) -> tuple[str, bool]:
    if display_snippet(old) == display_snippet(transformed):
        return "whitespace_or_line_ending_only", True
    markup = ("`", "[", "](", "**", "##", "- ", "|", "```")
    if any(token in old + transformed for token in markup):
        return "format_transform_requires_policy", False
    return "semantic_or_content_drift", False


def _context(text: str, start: int, end: int, radius: int = 48) -> dict:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return {"start": left, "end": right, "text": text[left:right]}


def _draft_case(draft: list[dict], case_id: str) -> dict:
    for row in draft:
        if row.get("id") == case_id:
            return row
    raise TriageError(f"unknown case_id: {case_id}")


def diagnose_row(unresolved: dict, chunk: dict, *, old_snippet: str | None = None) -> dict:
    if unresolved.get("source_id") != chunk.get("source"):
        category = "source_or_chunk_integrity_problem"
        reason = "source mismatch"
        candidate = None
    else:
        snippet = old_snippet if old_snippet is not None else unresolved.get("snippet", "")
        cr = unresolved.get("legacy_char_range") or {}
        text = chunk.get("text", "")
        try:
            start, end = locate_whitespace_candidate(text, snippet)
            category = "whitespace_or_line_ending_only"
            reason = "unique whitespace-normalized raw match"
            candidate = {"start": start, "end": end, "span": text[start:end]}
        except coord.CoordinateUnresolved as exc:
            norm = display_snippet(snippet)
            positions = []
            if norm:
                display = display_snippet(text)
                at = display.find(norm)
                while at >= 0:
                    positions.append(at)
                    at = display.find(norm, at + 1)
            if len(positions) > 1:
                category = "legacy_range_disambiguable_duplicate"
                reason = "multiple normalized matches; legacy range alone is insufficient"
            elif any(token in snippet for token in ("`", "[", "](", "**", "##", "- ", "|")):
                category = "format_transform_requires_policy"
                reason = str(exc)
            else:
                category = "semantic_or_content_drift"
                reason = str(exc)
            candidate = None
    cr = unresolved.get("legacy_char_range") or {}
    start, end = cr.get("start"), cr.get("end")
    raw_context = _context(chunk.get("text", ""), start, end) if isinstance(start, int) and isinstance(end, int) else None
    return {
        "case_id": unresolved.get("case_id"),
        "chunk_id": unresolved.get("chunk_id"),
        "source_id": unresolved.get("source_id"),
        "source": chunk.get("source"),
        "old_snippet": old_snippet if old_snippet is not None else unresolved.get("snippet", ""),
        "legacy_char_range": unresolved.get("legacy_char_range"),
        "root_cause_category": category,
        "raw_context": raw_context,
        "candidate_raw_span": candidate,
        "proof_signals": {
            "legacy_range_is_not_sufficient": category == "legacy_range_disambiguable_duplicate",
            "raw_span_rebuild_pass": bool(candidate and chunk["text"][candidate["start"]:candidate["end"]] == candidate["span"]),
            "source_matches_chunk": unresolved.get("source_id") == chunk.get("source"),
            "diagnostic_reason": reason,
        },
        "candidate_auto_resolution": category == "whitespace_or_line_ending_only" and candidate is not None,
        "risk": "low" if category == "whitespace_or_line_ending_only" else "high",
    }


def _manifest(body: dict) -> dict:
    out = dict(body)
    out.pop("manifest_sha256", None)
    out["manifest_sha256"] = coord.sha256_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    return out


def verify_manifest(manifest: dict) -> bool:
    actual = manifest.get("manifest_sha256")
    body = dict(manifest)
    body.pop("manifest_sha256", None)
    return actual == coord.sha256_text(json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def _validate_inputs(unresolved, migration, manifest, draft, chunks, paths):
    if manifest.get("counts") != {"evidence": 161, "migrated": 148, "unresolved": 13} or not manifest.get("activation_blocked"):
        raise TriageError("v2.0.2 candidate gate failed")
    if len(unresolved) != 13 or len({(r.get("case_id"), r.get("chunk_id"), r.get("source_id")) for r in unresolved}) != 13:
        raise TriageError("unresolved must contain 13 unique rows")
    if len(draft) != 150 or len({r.get("id") for r in draft}) != 150:
        raise TriageError("draft gate failed")
    if len(chunks) != len({r.get("chunk_id") for r in chunks.values()}):
        raise TriageError("duplicate chunk_id")
    expected = manifest.get("inputs", {})
    for key, path_key in (("draft", "draft"), ("chunks", "chunks"), ("evidence", "evidence")):
        if _sha(paths[path_key]) != expected[key]["sha256"]:
            raise TriageError(f"{key} SHA drift")
    if not verify_manifest(manifest):
        raise TriageError("manifest self-hash failed")
    for row in unresolved:
        chunk = chunks.get(row.get("chunk_id"))
        if chunk is None or chunk.get("source") != row.get("source_id"):
            raise TriageError("unresolved source/chunk integrity failed")


def run(*, out_dir: Path = DEFAULT_OUT, unresolved_path: Path = DEFAULT_UNRESOLVED,
        migration_path: Path = DEFAULT_MIGRATION, audit_path: Path = DEFAULT_AUDIT,
        quality_path: Path = DEFAULT_QUALITY, manifest_path: Path = DEFAULT_MANIFEST,
        evidence_path: Path = DEFAULT_EVIDENCE, draft_path: Path = DEFAULT_DRAFT,
        chunks_path: Path = DEFAULT_CHUNKS) -> dict:
    paths = {"draft": draft_path, "chunks": chunks_path, "evidence": evidence_path}
    unresolved = _jsonl(unresolved_path)
    migration = _jsonl(migration_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    draft = _jsonl(draft_path)
    chunks = {r["chunk_id"]: r for r in _jsonl(chunks_path)}
    evidence = _jsonl(evidence_path)
    _validate_inputs(unresolved, migration, manifest, draft, chunks, paths)
    snippets = {(r.get("case_id"), r.get("chunk_id"), r.get("source_id")): r.get("snippet", "") for r in evidence}
    rows = []
    for item in sorted(unresolved, key=lambda r: (r["case_id"], r["chunk_id"], r["source_id"])):
        key = (item.get("case_id"), item.get("chunk_id"), item.get("source_id"))
        rows.append(diagnose_row(item, chunks[item["chunk_id"]], old_snippet=snippets.get(key, "")))
    counts = Counter(r["root_cause_category"] for r in rows)
    summary = {"category_counts": {c: counts.get(c, 0) for c in CATEGORIES}, "candidate_count": sum(r["candidate_auto_resolution"] for r in rows), "candidate_case_ids": [r["case_id"] for r in rows if r["candidate_auto_resolution"]], "automatic_processing_blocked": True, "recommendation": "保留 unresolved；仅后续经复核的候选可机械写入，当前不激活。"}
    outputs = {
        "unresolved-triage.jsonl": "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows) + "\n",
        "resolution-candidates.jsonl": "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows if r["candidate_auto_resolution"]) + ("\n" if any(r["candidate_auto_resolution"] for r in rows) else ""),
        "unresolved-triage-summary.json": _dump_json(summary),
    }
    report = "# v2.0.2 unresolved coordinate triage\n\n" + "\n".join(f"- `{r['case_id']}`: `{r['root_cause_category']}` — {r['proof_signals']['diagnostic_reason']}" for r in rows) + "\n\n自动处理资格不会改变 candidate 的 activation gate；当前不生成 activation metadata、overlay 或 active 指针。\n"
    outputs["unresolved-triage-report.md"] = report
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        (out_dir / name).write_text(content, encoding="utf-8", newline="\n")
    body = {"version": "v2.0.2-unresolved-triage", "rule_version": RULE_VERSION, "timestamp": TIMESTAMP, "activation_blocked": True, "skill_note": SKILL_NOTE, "inputs": {k: {"path": str(paths[k]), "sha256": _sha(paths[k])} for k in paths}, "candidate_manifest_sha256": _sha(manifest_path), "counts": summary["category_counts"], "outputs": {name: _sha(out_dir / name) for name in outputs}}
    final_manifest = _manifest(body)
    (out_dir / "manifest.json").write_text(_dump_json(final_manifest), encoding="utf-8", newline="\n")
    return {"rows": rows, "summary": summary, "manifest": final_manifest}
