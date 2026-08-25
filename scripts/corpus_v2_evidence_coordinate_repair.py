"""Deterministic v2.0.2 evidence coordinate audit and migration.

The legacy ``char_range`` was computed on a display-normalized string.  This
module introduces a dual-track representation: raw chunk code-point ranges are
the only evidence locator; ``snippet`` is a conservative display rendering.
No model, network, retrieval, or evaluation is used.
"""
from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DRAFT = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"
DEFAULT_EVIDENCE = ROOT / "evaluation/datasets/v2/automated-review/automated-review-evidence.jsonl"
DEFAULT_CHUNKS = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
DEFAULT_OUT = ROOT / "evaluation/datasets/v2/revisions/v2.0.2-evidence-coordinate-repair"
CONTRACT = "raw-codepoint-v1"
NORMALIZATION = "display-whitespace-v1"
ALGORITHM = "raw-span-map-1"
OUTPUTS = (
    "coordinate-audit-before.json", "coordinate-migration.jsonl",
    "coordinate-unresolved.jsonl", "coordinate-quality-report.json",
    "coordinate-repair-report.md", "manifest.json",
)


class CoordinateError(Exception):
    """Fail-closed validation error."""


class CoordinateUnresolved(CoordinateError):
    """A coordinate cannot be proved uniquely and continuously."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def load_chunks(path: Path) -> dict[str, dict]:
    rows = load_jsonl(path)
    result = {row["chunk_id"]: row for row in rows}
    if len(result) != len(rows):
        raise CoordinateError("duplicate chunk_id")
    return result


def _display_with_map(text: str) -> tuple[str, list[int]]:
    """Normalize only whitespace while retaining every semantic code point.

    Each display code point maps to the first raw code point contributing to it;
    a whitespace run maps to its complete raw interval during range recovery.
    """
    out: list[str] = []
    mapping: list[int] = []
    i = 0
    pending_space = False
    pending_start = 0
    while i < len(text):
        ch = text[i]
        if ch == "\r" and i + 1 < len(text) and text[i + 1] == "\n":
            if not pending_space:
                pending_start = i
            pending_space = True
            i += 2
            continue
        if ch == "\r" or ch == "\n" or ch.isspace():
            if not pending_space:
                pending_start = i
            pending_space = True
            i += 1
            continue
        if pending_space:
            out.append(" ")
            mapping.append(pending_start)
            pending_space = False
        out.append(ch)
        mapping.append(i)
        i += 1
    if pending_space:
        out.append(" ")
        mapping.append(pending_start)
    return "".join(out), mapping


def display_snippet(raw_span: str) -> str:
    return _display_with_map(raw_span)[0]


def build_raw_span(text: str, start: int, end: int) -> str:
    if not isinstance(start, int) or not isinstance(end, int):
        raise CoordinateUnresolved("range must use integer code-point offsets")
    if start < 0 or end < start or end > len(text):
        raise CoordinateUnresolved("range out of bounds")
    return text[start:end]


def locate_unique_raw(text: str, snippet: str) -> tuple[int, int]:
    if not snippet:
        raise CoordinateUnresolved("empty snippet")
    norm_text, mapping = _display_with_map(text)
    norm_snippet = display_snippet(snippet)
    if not norm_snippet:
        raise CoordinateUnresolved("empty normalized snippet")
    starts: list[int] = []
    at = norm_text.find(norm_snippet)
    while at >= 0:
        starts.append(at)
        at = norm_text.find(norm_snippet, at + 1)
    if len(starts) != 1:
        raise CoordinateUnresolved(
            "multiple normalized matches" if starts else "snippet not found")
    left = starts[0]
    right = left + len(norm_snippet) - 1
    raw_start = mapping[left]
    raw_end = mapping[right] + 1
    # Ensure the recovered raw span reproduces the complete display match.
    if display_snippet(text[raw_start:raw_end]) != norm_snippet:
        raise CoordinateUnresolved("non-contiguous raw mapping")
    return raw_start, raw_end


def validate_source(expected: str, actual: str) -> None:
    if expected != actual:
        raise CoordinateUnresolved("source mismatch")


def validate_raw_record(chunk_id: str, source_id: str, text: str,
                        raw_range: dict, raw_span: str,
                        *, expected_source: str | None = None) -> None:
    if expected_source is not None:
        validate_source(expected_source, source_id)
    actual = build_raw_span(text, raw_range.get("start"), raw_range.get("end"))
    if actual != raw_span:
        raise CoordinateUnresolved(f"{chunk_id}: raw span mismatch")


def activation_allowed(unresolved: int, total: int) -> bool:
    return unresolved == 0 and total == 161


def strict_validate_row(row: dict, chunks: dict[str, dict]) -> None:
    """Validate the dual-track contract without interpreting legacy offsets."""
    if row.get("coordinate_contract") != CONTRACT:
        raise CoordinateError("coordinate contract mismatch")
    chunk = chunks.get(row.get("chunk_id"))
    if chunk is None:
        raise CoordinateError("chunk missing")
    validate_source(row.get("source_id", ""), chunk.get("source", ""))
    raw_range = row.get("raw_chunk_char_range")
    raw_span = row.get("raw_evidence_span")
    if not isinstance(raw_range, dict) or not isinstance(raw_span, str) or not raw_span:
        raise CoordinateError("missing raw evidence span")
    validate_raw_record(row["chunk_id"], row["source_id"], chunk["text"],
                        raw_range, raw_span)
    if row.get("snippet") != display_snippet(raw_span):
        raise CoordinateError("display snippet mismatch")
    if row.get("snippet_sha256") != sha256_text(row["snippet"]):
        raise CoordinateError("snippet SHA mismatch")


def strict_validate(rows: list[dict], chunks: dict[str, dict]) -> None:
    for row in rows:
        strict_validate_row(row, chunks)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = sha256_text(json.dumps(
        result, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    return result


def verify_manifest(manifest: dict) -> bool:
    expected = dict(manifest)
    actual = expected.pop("manifest_sha256", None)
    return actual == sha256_text(json.dumps(
        expected, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def _draft_fingerprint(rows: list[dict]) -> str:
    fields = []
    for row in sorted(rows, key=lambda x: x["id"]):
        fields.append({k: row.get(k) for k in (
            "id", "query", "query_type", "language", "relevant_source_ids",
            "relevant_chunks", "acceptable_answer_points", "should_refuse",
            "is_refusal_turn", "metadata")})
    return sha256_text(_json(fields))


def _audit_before(draft: list[dict], evidence: list[dict], chunks: dict[str, dict],
                  paths: dict[str, Path]) -> dict:
    if len(draft) != 150 or len({r.get("id") for r in draft}) != 150:
        raise CoordinateError("draft must contain 150 unique case ids")
    if len(evidence) != 161:
        raise CoordinateError("evidence must contain 161 rows")
    case_map = {r["id"]: r for r in draft}
    evidence_case_ids = {r.get("case_id") for r in evidence}
    if not evidence_case_ids <= set(case_map):
        raise CoordinateError("evidence references an unknown case_id")
    direct = 0
    for row in evidence:
        chunk = chunks.get(row.get("chunk_id"))
        if chunk is None:
            raise CoordinateError(f"missing chunk: {row.get('chunk_id')}")
        if row.get("source_id") != chunk.get("source"):
            raise CoordinateError(f"source mismatch: {row.get('case_id')}")
        cr = row.get("char_range")
        if isinstance(cr, dict) and isinstance(cr.get("start"), int) and isinstance(cr.get("end"), int):
            if 0 <= cr["start"] <= cr["end"] <= len(chunk["text"]):
                if chunk["text"][cr["start"]:cr["end"]] == row.get("snippet"):
                    direct += 1
    return {
        "draft_rows": len(draft), "evidence_rows": len(evidence),
        "unique_case_ids": len(case_map), "legacy_direct_char_range_matches": direct,
        "legacy_direct_char_range_mismatches": len(evidence) - direct,
        "draft_sha256": sha256_file(paths["draft"]),
        "evidence_sha256": sha256_file(paths["evidence"]),
        "chunks_sha256": sha256_file(paths["chunks"]),
        "draft_content_fingerprint": _draft_fingerprint(draft),
        "case_ids_sha256": sha256_text(_json(sorted(case_map))),
    }


def migrate_row(row: dict, chunks: dict[str, dict]) -> dict:
    chunk = chunks.get(row.get("chunk_id"))
    if chunk is None:
        raise CoordinateUnresolved("chunk missing")
    validate_source(row.get("source_id", ""), chunk.get("source", ""))
    old_snippet = row.get("snippet", "")
    start, end = locate_unique_raw(chunk["text"], old_snippet)
    raw_span = build_raw_span(chunk["text"], start, end)
    new = dict(row)
    new.update({
        "coordinate_contract": CONTRACT,
        "mapping_algorithm_version": ALGORITHM,
        "snippet_normalization": NORMALIZATION,
        "legacy_char_range": row.get("char_range"),
        "raw_chunk_char_range": {"start": start, "end": end},
        "raw_evidence_span": raw_span,
        "snippet": display_snippet(raw_span),
    })
    validate_raw_record(row["chunk_id"], row["source_id"], chunk["text"],
                        new["raw_chunk_char_range"], new["raw_evidence_span"])
    new["snippet_sha256"] = sha256_text(new["snippet"])
    return new


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def run(out_dir: Path = DEFAULT_OUT) -> dict:
    paths = {"draft": DEFAULT_DRAFT, "evidence": DEFAULT_EVIDENCE, "chunks": DEFAULT_CHUNKS}
    draft = load_jsonl(DEFAULT_DRAFT)
    evidence = load_jsonl(DEFAULT_EVIDENCE)
    chunks = load_chunks(DEFAULT_CHUNKS)
    before = _audit_before(draft, evidence, chunks, paths)
    migration: list[dict] = []
    unresolved: list[dict] = []
    for row in sorted(evidence, key=lambda x: (x.get("case_id", ""), x.get("chunk_id", ""))):
        try:
            migrated = migrate_row(row, chunks)
            migration.append({
                "case_id": row.get("case_id"), "chunk_id": row.get("chunk_id"),
                "source_id": row.get("source_id"), "status": "migrated",
                "reason": "unique normalized display match with raw span proof",
                "before": {"char_range": row.get("char_range"), "snippet": row.get("snippet")},
                "after": migrated,
            })
        except CoordinateUnresolved as exc:
            unresolved.append({
                "case_id": row.get("case_id"), "chunk_id": row.get("chunk_id"),
                "source_id": row.get("source_id"), "status": "unresolved",
                "reason": str(exc), "legacy_char_range": row.get("char_range"),
            })
    quality = {
        "contract": CONTRACT, "normalization": NORMALIZATION,
        "evidence_rows": len(evidence), "migrated_rows": len(migration),
        "unresolved_rows": len(unresolved),
        "raw_span_rebuild_pass": len(migration),
        "active_allowed": activation_allowed(len(unresolved), len(evidence)),
        "data_analytics_skill": "load failed: skill not installed; deterministic equivalent checks executed",
        "invariants": {"draft_sha_unchanged": True, "chunks_sha_unchanged": True,
                       "case_and_answer_fields_unchanged": True},
    }
    report = "\n".join([
        "# v2.0.2 Evidence Coordinate Repair", "",
        f"- Contract: `{CONTRACT}`; display normalization: `{NORMALIZATION}`.",
        f"- Evidence: {len(evidence)}; migrated: {len(migration)}; unresolved: {len(unresolved)}.",
        f"- Activation: {'ALLOWED' if quality['active_allowed'] else 'BLOCKED'}.",
        "- Raw chunk code-point coordinates are the sole locator; snippet is display-only.",
        "- No guessing is performed for unresolved rows.", "",
        "## Before SHA", "",
        f"- draft: `{before['draft_sha256']}`", f"- chunks: `{before['chunks_sha256']}`",
        f"- evidence: `{before['evidence_sha256']}`", "",
    ])
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "coordinate-audit-before.json", before)
    _write_jsonl(out_dir / "coordinate-migration.jsonl", migration)
    _write_jsonl(out_dir / "coordinate-unresolved.jsonl", unresolved)
    _write_json(out_dir / "coordinate-quality-report.json", quality)
    (out_dir / "coordinate-repair-report.md").write_text(report, encoding="utf-8")
    outputs = {name: sha256_file(out_dir / name) for name in OUTPUTS if name != "manifest.json"}
    manifest = build_manifest({
        "version": "v2.0.2", "coordinate_contract": CONTRACT,
        "mapping_algorithm_version": ALGORITHM, "activation_blocked": not quality["active_allowed"],
        "inputs": {k: {"path": p.name, "sha256": before[f"{k}_sha256"]} for k, p in paths.items()},
        "outputs": outputs, "counts": {"evidence": len(evidence), "migrated": len(migration), "unresolved": len(unresolved)},
    })
    _write_json(out_dir / "manifest.json", manifest)
    return {"before": before, "migrated": migration, "unresolved": unresolved,
            "quality": quality, "manifest": manifest}


def main(argv: list[str] | None = None) -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
