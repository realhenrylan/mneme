"""Deterministically audit the causes of the blocked v2.0.3 reannotations."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "evaluation/datasets/v2/revisions/v2.0.3-owner-authorized-evidence-reannotation"
BASE = ROOT / "evaluation/datasets/v2/revisions/v2.0.2-evidence-coordinate-repair"
BLOCKERS = REVISION / "reannotation-blockers.jsonl"
V2_MANIFEST = BASE / "manifest.json"
UNRESOLVED = BASE / "coordinate-unresolved.jsonl"
MIGRATION = BASE / "coordinate-migration.jsonl"
DRAFT = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"
CHUNKS = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
DEFAULT_OUT = REVISION / "blocker-audit"
CATEGORIES = (
    "anchor_catalog_insufficient",
    "scoped_chunk_evidence_absent",
    "answer_semantics_not_directly_supported",
    "source_scope_expansion_required",
    "model_or_schema_action_invalid",
    "integrity_or_contract_blocker",
)
OUTPUT_FILES = (
    "blocker-root-causes.jsonl",
    "candidate-source-scope-spans.jsonl",
    "blocker-audit-summary.json",
    "OWNER_NEXT_DECISION_MATRIX.md",
    "blocker-audit-report.md",
    "manifest.json",
)
RULE_VERSION = "v2.0.3-reannotation-blocker-audit-1"
TIMESTAMP = "2026-08-10T00:00:00+00:00"


class AuditError(Exception):
    """输入门禁或审计结果不自洽。"""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _terms(text: str) -> list[str]:
    return [x for x in re.findall(r"[\w]+|[\u4e00-\u9fff]", text.lower()) if len(x) > 1 or "\u4e00" <= x <= "\u9fff"]


def _units(text: str) -> list[tuple[int, int, str]]:
    result = []
    offset = 0
    for line in text.splitlines(keepends=True):
        end = offset + len(line)
        raw = line.rstrip("\r\n")
        if raw:
            result.append((offset, offset + len(raw), raw))
        offset = end
    return result


def build_anchor_catalog(chunks: list[dict]) -> list[dict]:
    output = []
    for chunk in sorted(chunks, key=lambda item: item["chunk_id"]):
        anchors = []
        for index, (start, end, raw) in enumerate(_units(chunk.get("text", ""))):
            anchors.append({
                "anchor_id": f"{chunk['chunk_id']}::a{index:04d}",
                "chunk_id": chunk["chunk_id"],
                "source": chunk.get("source"),
                "raw_span": raw,
                "raw_chunk_char_range": {"start": start, "end": end},
            })
        output.append({"chunk_id": chunk["chunk_id"], "source": chunk.get("source"), "anchors": anchors})
    return output


def _find_spans(text: str, answer: str) -> list[dict]:
    needle = _norm(answer)
    if not needle:
        return []
    units = _units(text)
    spans = []
    for start, end, raw in units:
        if needle in _norm(raw):
            spans.append({"raw_span": raw, "raw_chunk_char_range": {"start": start, "end": end}})
    # A direct answer may cross line boundaries. It is evidence in the raw
    # chunk, but the current line-atomic catalogue cannot represent it safely.
    for left in range(len(units)):
        joined = ""
        for right in range(left, len(units)):
            joined += text[units[right][0]:units[right][1]]
            if needle in _norm(joined) and right > left:
                spans.append({"raw_span": text[units[left][0]:units[right][1]], "raw_chunk_char_range": {"start": units[left][0], "end": units[right][1]}})
                break
            if len(_norm(joined)) > len(needle) * 3:
                break
    return spans


def _candidate_spans(answer: str, chunk: dict) -> list[dict]:
    """Return only direct, contiguous answer-point matches; related terms are not proof."""
    needle = _norm(answer)
    if not needle:
        return []
    result = []
    for start, end, raw in _units(chunk.get("text", "")):
        if needle in _norm(raw):
            result.append({"chunk_id": chunk["chunk_id"], "source": chunk.get("source"), "raw_span": raw, "raw_chunk_char_range": {"start": start, "end": end}, "matched_terms": [answer]})
    return result


def _classify(blocker: dict, case: dict | None, chunk: dict | None, catalog: dict | None, all_chunks: list[dict]) -> tuple[str, str, list[dict]]:
    if not case or not chunk or not catalog:
        return "integrity_or_contract_blocker", "case, chunk, or anchor catalog input is missing", []
    answer_points = case.get("acceptable_answer_points") or []
    if blocker.get("source_id") != chunk.get("source") or blocker.get("chunk_id") not in case.get("relevant_chunk_ids", [blocker.get("chunk_id")]):
        return "integrity_or_contract_blocker", "blocker source/chunk does not match the declared case scope", []
    exact = []
    for answer in answer_points:
        exact.extend(_find_spans(chunk.get("text", ""), answer))
    if exact:
        if any(any(anchor["raw_span"] == item["raw_span"] for anchor in catalog["anchors"]) for item in exact):
            return "model_or_schema_action_invalid", "a direct local anchor exists; the recorded blocker is an invalid model/schema action", []
        return "anchor_catalog_insufficient", "supporting text is continuous but no current atomic anchor matches the answer point", exact
    same_source = [c for c in all_chunks if c.get("source") == blocker.get("source_id") and c.get("chunk_id") != blocker.get("chunk_id")]
    scope = []
    for other in same_source:
        for answer in answer_points:
            scope.extend(_candidate_spans(answer, other))
    if scope:
        return "source_scope_expansion_required", "the scoped chunk lacks support, while another chunk from the same licensed source has candidate text", scope
    related = []
    for answer in answer_points:
        terms = _terms(answer)
        for start, end, raw in _units(chunk.get("text", "")):
            hits = [term for term in terms if _norm(term) in _norm(raw)]
            if hits:
                related.append({"chunk_id": chunk["chunk_id"], "source": chunk.get("source"), "raw_span": raw, "raw_chunk_char_range": {"start": start, "end": end}, "matched_terms": hits})
    if related:
        return "answer_semantics_not_directly_supported", "related terms occur locally, but no single raw span directly supports the full answer point", related
    return "scoped_chunk_evidence_absent", "no candidate raw text supports the answer point inside the declared chunk", []


def audit_rows(blockers: list[dict], draft: list[dict], chunks: list[dict], catalog: list[dict]) -> tuple[list[dict], list[dict]]:
    by_case = {row.get("id"): row for row in draft}
    by_chunk = {row.get("chunk_id"): row for row in chunks}
    by_catalog = {row["chunk_id"]: row for row in catalog}
    rows, scope_rows = [], []
    for blocker in sorted(blockers, key=lambda row: (row.get("case_id", ""), row.get("chunk_id", ""))):
        case = by_case.get(blocker.get("case_id"))
        chunk = by_chunk.get(blocker.get("chunk_id"))
        cat = by_catalog.get(blocker.get("chunk_id"))
        category, explanation, candidates = _classify(blocker, case, chunk, cat, chunks)
        row = {
            "case_id": blocker.get("case_id"), "chunk_id": blocker.get("chunk_id"), "source_id": blocker.get("source_id"),
            "answer_point": (case.get("acceptable_answer_points") if case else []),
            "blocker_reason": blocker.get("reason"), "root_cause_category": category,
            "local_evidence": {"anchor_count": len(cat.get("anchors", [])) if cat else 0, "candidate_raw_span_count": len(candidates)},
            "explanation": explanation,
            "requires_owner_authorization": True,
            "auto_applicable": False,
            "next_action": {"requires_owner_authorization": True, "auto_applicable": False, "recommendation": "review scope and wording before any candidate revision"},
        }
        rows.append(row)
        if category == "source_scope_expansion_required":
            for candidate in candidates:
                scope_rows.append({"case_id": row["case_id"], "requested_source_id": row["source_id"], **candidate, "auto_applicable": False, "requires_owner_authorization": True, "reason": explanation})
    if len(rows) != len(blockers) or any(sum(row["root_cause_category"] == category for row in rows) > len(rows) for category in CATEGORIES):
        raise AuditError("classification coverage failed")
    return rows, scope_rows


def _load_and_gate() -> tuple[list[dict], list[dict], list[dict], list[dict], dict[str, str]]:
    v2 = json.loads(V2_MANIFEST.read_text(encoding="utf-8"))
    if v2.get("counts") != {"evidence": 161, "migrated": 148, "unresolved": 13} or not v2.get("activation_blocked"):
        raise AuditError("v2.0.2 activation gate failed")
    blockers, unresolved, migration, draft, chunks = _jsonl(BLOCKERS), _jsonl(UNRESOLVED), _jsonl(MIGRATION), _jsonl(DRAFT), _jsonl(CHUNKS)
    if len(blockers) != 13 or len(unresolved) != 13 or len(migration) != 148 or len(draft) != 150:
        raise AuditError("baseline count failed")
    key = lambda row: (row.get("case_id"), row.get("chunk_id"), row.get("source_id"))
    if {key(x) for x in blockers} != {key(x) for x in unresolved}:
        raise AuditError("blocker/unresolved target set mismatch")
    if len({row.get("id") for row in draft}) != 150 or len({row.get("chunk_id") for row in chunks}) != len(chunks):
        raise AuditError("input uniqueness failed")
    hashes = {name: _sha(path) for name, path in (("blockers", BLOCKERS), ("unresolved", UNRESOLVED), ("migration", MIGRATION), ("draft", DRAFT), ("chunks", CHUNKS), ("chunk_manifest", CHUNK_MANIFEST), ("v2_manifest", V2_MANIFEST))}
    return blockers, unresolved, migration, draft, chunks, hashes


def run(out_dir: Path = DEFAULT_OUT) -> dict:
    blockers, unresolved, migration, draft, chunks, input_hashes = _load_and_gate()
    forbidden = [out_dir / name for name in ("draft-after.jsonl", "evidence-after.jsonl", "overlay", "active.json")]
    if any(path.exists() for path in forbidden):
        raise AuditError("forbidden activation output already exists")
    catalog = build_anchor_catalog(chunks)
    rows, scope_rows = audit_rows(blockers, draft, chunks, catalog)
    counts = Counter(row["root_cause_category"] for row in rows)
    if set(counts) - set(CATEGORIES) or sum(counts.values()) != 13:
        raise AuditError("category coverage failed")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / OUTPUT_FILES[0]).write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8", newline="\n")
    (out_dir / OUTPUT_FILES[1]).write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in scope_rows), encoding="utf-8", newline="\n")
    summary = {"rule_version": RULE_VERSION, "counts": {"total": 13, "categories": {category: counts.get(category, 0) for category in CATEGORIES}, "scope_candidates": len(scope_rows)}, "case_ids_by_category": {category: [row["case_id"] for row in rows if row["root_cause_category"] == category] for category in CATEGORIES}, "activation_blocked": True, "auto_applicable": False, "requires_owner_authorization": True}
    (out_dir / OUTPUT_FILES[2]).write_text(_dump(summary), encoding="utf-8", newline="\n")
    matrix = "# Owner Next Decision Matrix\n\n| Root cause | Required owner decision | Automatic action |\n|---|---|---|\n" + "\n".join(f"| `{category}` | review wording, scope, or anchor policy | none |" for category in CATEGORIES) + "\n"
    (out_dir / OUTPUT_FILES[3]).write_text(matrix, encoding="utf-8", newline="\n")
    report = "# v2.0.3 Reannotation Blocker Audit\n\n只读、确定性审计；未生成 after 文件、overlay 或 active metadata。\n\n" + "\n".join(f"- `{category}`: {counts.get(category, 0)} — {', '.join(summary['case_ids_by_category'][category]) or 'none'}" for category in CATEGORIES) + "\n\n所有候选均 `requires_owner_authorization=true` 且 `auto_applicable=false`。\n"
    (out_dir / OUTPUT_FILES[4]).write_text(report, encoding="utf-8", newline="\n")
    outputs = {name: _sha(out_dir / name) for name in OUTPUT_FILES[:-1]}
    manifest = {"revision_status": "CANDIDATE", "activation_blocked": True, "rule_version": RULE_VERSION, "timestamp": TIMESTAMP, "inputs": input_hashes, "outputs": outputs, "counts": summary["counts"], "manifest_sha256": ""}
    manifest["manifest_sha256"] = hashlib.sha256(_dump({k: v for k, v in manifest.items() if k != "manifest_sha256"}).encode("utf-8")).hexdigest()
    (out_dir / OUTPUT_FILES[5]).write_text(_dump(manifest), encoding="utf-8", newline="\n")
    return {"counts": summary["counts"], "manifest": manifest}


if __name__ == "__main__":
    run()
