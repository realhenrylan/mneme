"""Build the owner-authorised v2.0.10 coherence-remediation candidate.

The input v2.0.9 candidate and its automated-review triage remain immutable.
This program applies only the explicit authorisation recorded in the current
task: six same-source evidence additions, one safe retirement (``multi-019``),
and removal of one byte-identical ``mixed-033`` evidence row.  It is entirely
deterministic and fails closed before creating an output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.corpus_v2_evidence_coordinate_repair import (  # noqa: E402
    display_snippet,
    strict_validate,
)
from scripts import corpus_v2_v209_final_dependency_closed_retirement as graph_mod  # noqa: E402


V208 = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.8-owner-authorized-semantic-quality-remediation"
V209 = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.9-owner-authorized-final-dependency-closed-retirement"
OUT = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.10-owner-authorized-coherence-remediation"
CHUNKS_PATH = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST_PATH = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT_PATH = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"

TRIAGE_DIR_NAME = "coherence-reject-triage"
TRIAGE_DIR = V209 / "automated-review" / TRIAGE_DIR_NAME

TIMESTAMP = "2026-08-11T00:00:00+00:00"
RULE_VERSION = "v2.0.10-owner-authorized-coherence-remediation-1"
ACTOR = "OWNER_AUTHORIZED_V2_0_10_COHERENCE_REMEDIATION"
AUTHORIZATION = "OWNER_AUTHORIZED_ALL_TRIAGE_REMEDIATIONS"
GATE_OK = "COHERENCE_REMEDIATION_CANDIDATE_OK"
RETIRE_REASON = "no_direct_support_in_declared_source_after_owner_authorization"
DEDUP_REASON = "owner_authorized_byte_identical_duplicate_evidence_removal"
SCOPE_MARKER = "OWNER_AUTHORIZED_SAME_SOURCE_EVIDENCE_SCOPE_REPAIR"
CONTRACT = "raw-codepoint-v1"
ALGORITHM = "raw-span-map-1"
NORMALIZATION = "display-whitespace-v1"

EXPECTED_CASE_BEFORE = 137
EXPECTED_EVIDENCE_BEFORE = 144
EXPECTED_CASE_AFTER = 136
EXPECTED_EVIDENCE_AFTER = 148
EXPECTED_REFUSAL_CASES = 31
EXPECTED_ANSWERABLE_CASES = 105

REPAIR_CASE_IDS = (
    "en-047",
    "en-048",
    "multi-020",
    "multi-028",
    "zh-046",
    "zh-052",
)
RETIRED_CASE_ID = "multi-019"
DEDUP_CASE_ID = "mixed-033"

# These are the exact same-source raw spans published by the v2.0.9 triage.
# They are deliberately explicit rather than selected heuristically at build
# time, so a changed triage result or corpus coordinate blocks the run.
REPAIR_SPECS = (
    {
        "case_id": "en-047", "chunk_id": "761b22915b5e_chunk_7",
        "source_id": "postgresql-tutorial.md", "start": 882, "end": 888,
        "span": "SELECT",
    },
    {
        "case_id": "en-048", "chunk_id": "761b22915b5e_chunk_14",
        "source_id": "postgresql-tutorial.md", "start": 531, "end": 537,
        "span": "window",
    },
    {
        "case_id": "multi-020", "chunk_id": "761b22915b5e_chunk_3",
        "source_id": "postgresql-tutorial.md", "start": 1805, "end": 1813,
        "span": "createdb",
    },
    {
        "case_id": "multi-028", "chunk_id": "761b22915b5e_chunk_12",
        "source_id": "postgresql-tutorial.md", "start": 1362, "end": 1370,
        "span": "ROLLBACK",
    },
    {
        "case_id": "zh-046", "chunk_id": "761b22915b5e_chunk_3",
        "source_id": "postgresql-tutorial.md", "start": 1805, "end": 1813,
        "span": "createdb",
    },
    {
        "case_id": "zh-052", "chunk_id": "761b22915b5e_chunk_0",
        "source_id": "postgresql-tutorial.md", "start": 1672, "end": 1684,
        "span": "Transactions",
    },
)

OUTPUT_FILES = (
    "draft-before.jsonl",
    "evidence-before.jsonl",
    "draft-after.jsonl",
    "evidence-after.jsonl",
    "added-same-source-evidence.jsonl",
    "retired-cases.jsonl",
    "retired-evidence.jsonl",
    "deduplicated-evidence.jsonl",
    "field-level-diff.jsonl",
    "data-quality-report.json",
    "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md",
    "manifest.json",
)


class RemediationError(Exception):
    """A gate failed; the caller must not receive a partial candidate."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _line(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = _sha256_text(_dump(result))
    return result


def _verify_self_hash(manifest: dict) -> bool:
    body = dict(manifest)
    actual = body.pop("manifest_sha256", None)
    return actual == _sha256_text(_dump(body))


def _require(path: Path, label: str) -> Path:
    if not path.is_file():
        raise RemediationError(f"missing {label}: {path}")
    return path


def _verify_outputs(manifest: dict, directory: Path, label: str) -> None:
    for name, digest in (manifest.get("outputs") or {}).items():
        path = directory / name
        if not path.is_file() or _sha256_file(path) != digest:
            raise RemediationError(f"{label} output SHA mismatch: {name}")


def _v209_input_sha_map(*, chunks_path: Path,
                         chunk_manifest_path: Path,
                         current_draft_path: Path) -> dict[str, Path]:
    return {
        "v208-manifest.json": V208 / "manifest.json",
        "draft-after.jsonl": V208 / "draft-after.jsonl",
        "draft-before.jsonl": V208 / "draft-before.jsonl",
        "evidence-after.jsonl": V208 / "evidence-after.jsonl",
        "evidence-before.jsonl": V208 / "evidence-before.jsonl",
        "deferred-chain-dependent-cases.jsonl":
            V208 / "deferred-chain-dependent-cases.jsonl",
        "final-blockers-manifest.json":
            V208 / "final-blockers-decision-pack" / "manifest.json",
        "final-blockers-decision-pack.jsonl":
            V208 / "final-blockers-decision-pack" /
            "final-blockers-decision-pack.jsonl",
        "chain-closure-manifest.json":
            V208 / "chain-closure-decision-pack" / "manifest.json",
        "multi-030-closure-options.json":
            V208 / "chain-closure-decision-pack" /
            "multi-030-closure-options.json",
        "mixed-027-retirement-check.json":
            V208 / "chain-closure-decision-pack" /
            "mixed-027-retirement-check.json",
        "chunks.jsonl": chunks_path,
        "chunk-manifest.json": chunk_manifest_path,
        "current-v2-draft.jsonl": current_draft_path,
    }


def _verify_input_hashes(manifest: dict, mapping: dict[str, Path],
                         label: str) -> None:
    inputs = manifest.get("inputs") or {}
    if not inputs:
        raise RemediationError(f"{label} inputs missing")
    for name, digest in inputs.items():
        path = mapping.get(name)
        if path is None or not path.is_file() or _sha256_file(path) != digest:
            raise RemediationError(f"{label} input SHA mismatch: {name}")


def _load_chunks(path: Path) -> dict[str, dict]:
    rows = _jsonl(path)
    chunks = {row["chunk_id"]: row for row in rows}
    if len(chunks) != len(rows):
        raise RemediationError("duplicate chunk_id in chunks")
    return chunks


def _verify_v209_candidate(candidate_dir: Path, *, chunks_path: Path,
                            chunk_manifest_path: Path,
                            current_draft_path: Path) -> tuple[dict, list[dict],
                                                               list[dict], dict]:
    manifest_path = _require(candidate_dir / "manifest.json", "v2.0.9 manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not _verify_self_hash(manifest):
        raise RemediationError("v2.0.9 candidate manifest self-hash mismatch")
    if manifest.get("gate_verdict") != "FINAL_DEPENDENCY_CLOSED_RETIREMENT_OK":
        raise RemediationError("v2.0.9 candidate gate mismatch")
    if manifest.get("revision_status") != "CANDIDATE" or \
            manifest.get("activation_blocked") is not True or \
            manifest.get("human_reviewed") is not False or \
            manifest.get("overlay_generated") is not False or \
            manifest.get("split_reseal_required") is not True or \
            manifest.get("v2_1_entered") is not False:
        raise RemediationError("v2.0.9 candidate metadata drift")
    counts = manifest.get("counts") or {}
    if counts.get("case_after") != EXPECTED_CASE_BEFORE or \
            counts.get("evidence_after") != EXPECTED_EVIDENCE_BEFORE or \
            counts.get("retired_cases") != 6 or \
            counts.get("retired_evidence") != 7:
        raise RemediationError(f"v2.0.9 candidate counts drift: {counts}")
    _verify_outputs(manifest, candidate_dir, "v2.0.9 candidate")
    _verify_input_hashes(
        manifest,
        _v209_input_sha_map(chunks_path=chunks_path,
                             chunk_manifest_path=chunk_manifest_path,
                             current_draft_path=current_draft_path),
        "v2.0.9 candidate",
    )

    draft = _jsonl(_require(candidate_dir / "draft-after.jsonl", "draft-after"))
    evidence = _jsonl(_require(candidate_dir / "evidence-after.jsonl",
                               "evidence-after"))
    if len(draft) != EXPECTED_CASE_BEFORE or \
            len({row["id"] for row in draft}) != EXPECTED_CASE_BEFORE:
        raise RemediationError("v2.0.9 draft count or uniqueness drift")
    if len(evidence) != EXPECTED_EVIDENCE_BEFORE:
        raise RemediationError("v2.0.9 evidence count drift")
    chunks = _load_chunks(chunks_path)
    try:
        strict_validate(evidence, chunks)
    except Exception as exc:
        raise RemediationError(f"v2.0.9 strict validation failed: {exc}") from exc
    if any(row.get("coordinate_contract") != CONTRACT for row in evidence):
        raise RemediationError("v2.0.9 evidence contains legacy coordinate rows")
    return manifest, draft, evidence, chunks


def _verify_review_and_triage(candidate_dir: Path, *, chunks_path: Path,
                              chunk_manifest_path: Path,
                              current_draft_path: Path,
                              candidate_manifest: dict) -> tuple[list[dict], dict]:
    review_dir = candidate_dir / "automated-review"
    review_manifest_path = _require(review_dir / "manifest.json", "review manifest")
    review_manifest = json.loads(review_manifest_path.read_text(encoding="utf-8"))
    if not _verify_self_hash(review_manifest):
        raise RemediationError("v2.0.9 review manifest self-hash mismatch")
    if review_manifest.get("gate_verdict") != "AUTOMATED_REVIEW_GATE_BLOCKED":
        raise RemediationError("v2.0.9 review gate mismatch")
    _verify_outputs(review_manifest, review_dir, "v2.0.9 review")
    review_input_map = {
        "candidate-draft-after.jsonl": candidate_dir / "draft-after.jsonl",
        "candidate-evidence-after.jsonl": candidate_dir / "evidence-after.jsonl",
        "candidate-manifest.json": candidate_dir / "manifest.json",
        "chunks.jsonl": chunks_path,
        "chunk-manifest.json": chunk_manifest_path,
        "current-v2-draft.jsonl": current_draft_path,
        "translation-equivalence-policy.md": V208 / "translation-equivalence-policy.md",
        "translation-equivalence-policy-ledger.jsonl":
            V208 / "translation-equivalence-policy-ledger.jsonl",
    }
    _verify_input_hashes(review_manifest, review_input_map, "v2.0.9 review")
    review_counts = review_manifest.get("counts") or {}
    if review_counts != {
        "case_count": 137, "evidence_count": 144, "answerable_cases": 106,
        "refusal_cases": 31, "confirmed": 111, "reject": 22,
        "needs_followup": 0, "errors": 4,
    }:
        raise RemediationError(f"v2.0.9 review counts drift: {review_counts}")

    triage_dir = review_dir / TRIAGE_DIR_NAME
    triage_manifest_path = _require(triage_dir / "manifest.json", "triage manifest")
    triage_manifest = json.loads(triage_manifest_path.read_text(encoding="utf-8"))
    if not _verify_self_hash(triage_manifest):
        raise RemediationError("triage manifest self-hash mismatch")
    if triage_manifest.get("gate_verdict") != "COHERENCE_REJECT_TRIAGE_OK":
        raise RemediationError("triage gate mismatch")
    _verify_outputs(triage_manifest, triage_dir, "triage")
    triage_inputs = {
        "candidate-draft-after.jsonl": candidate_dir / "draft-after.jsonl",
        "candidate-evidence-after.jsonl": candidate_dir / "evidence-after.jsonl",
        "chunks.jsonl": chunks_path,
        "chunk-manifest.json": chunk_manifest_path,
    }
    _verify_input_hashes(triage_manifest, triage_inputs, "triage")
    triage_counts = triage_manifest.get("counts") or {}
    if triage_counts != {
        "case_count": 137, "confirmed": 111, "errors": 4,
        "evidence_count": 144, "issues_rows": 26, "needs_followup": 0,
        "reject": 22,
    }:
        raise RemediationError(f"triage counts drift: {triage_counts}")

    rows = _jsonl(triage_dir / "reject-root-cause-triage.jsonl")
    if len(rows) != 22 or len({row.get("case_id") for row in rows}) != 22:
        raise RemediationError("triage reject rows drift")
    by_id = {row["case_id"]: row for row in rows}
    if tuple(sorted(cid for cid, row in by_id.items()
                    if row.get("suggested_action") == "repair_candidate")) != \
            tuple(sorted(REPAIR_CASE_IDS)):
        raise RemediationError("triage repair target set drift")
    retired = by_id.get(RETIRED_CASE_ID)
    if not retired or retired.get("suggested_action") != "retire_case" or \
            retired.get("case_classification") != "no_direct_support_in_declared_source":
        raise RemediationError("triage retirement authorisation fact drift")
    mixed = json.loads((triage_dir / "mixed-033-duplicate-evidence-check.json").read_text(
        encoding="utf-8"))
    advice = mixed.get("deletion_advice") or {}
    if mixed.get("case_id") != DEDUP_CASE_ID or mixed.get("rows") != 2 or \
            mixed.get("byte_identical") is not True or \
            mixed.get("supports_same_answer_point") is not True or \
            advice.get("semantically_safe") is not True or \
            advice.get("owner_authorization_required") is not True:
        raise RemediationError("mixed-033 deduplication fact drift")
    if candidate_manifest.get("manifest_sha256") is None:
        raise RemediationError("candidate manifest self hash missing")
    return rows, mixed


def _verify_repair_specs(reject_rows: list[dict], draft_by_id: dict[str, dict],
                         evidence_rows: list[dict], chunks: dict[str, dict]) -> None:
    by_id = {row["case_id"]: row for row in reject_rows}
    existing = {(row["case_id"], row["chunk_id"],
                 row["raw_chunk_char_range"]["start"],
                 row["raw_chunk_char_range"]["end"])
                for row in evidence_rows}
    if len(REPAIR_SPECS) != len(REPAIR_CASE_IDS) or \
            {spec["case_id"] for spec in REPAIR_SPECS} != set(REPAIR_CASE_IDS):
        raise RemediationError("repair specification set drift")
    for spec in REPAIR_SPECS:
        cid = spec["case_id"]
        row = by_id.get(cid)
        if not row or row.get("suggested_action") != "repair_candidate":
            raise RemediationError(f"{cid}: triage repair authorisation missing")
        match = any(c.get("chunk_id") == spec["chunk_id"] and
                    c.get("start") == spec["start"] and
                    c.get("end") == spec["end"] and
                    c.get("span") == spec["span"] and
                    c.get("overlaps_existing") is False
                    for c in row.get("same_source_candidates") or [])
        if not match:
            raise RemediationError(f"{cid}: authorised same-source span drift")
        chunk = chunks.get(spec["chunk_id"])
        if not chunk or chunk.get("source") != spec["source_id"]:
            raise RemediationError(f"{cid}: source/chunk drift")
        if chunk["text"][spec["start"]:spec["end"]] != spec["span"]:
            raise RemediationError(f"{cid}: raw span no longer rebuilds")
        if spec["source_id"] not in (draft_by_id[cid].get("relevant_source_ids") or []):
            raise RemediationError(f"{cid}: candidate is not from a declared source")
        key = (cid, spec["chunk_id"], spec["start"], spec["end"])
        if key in existing:
            raise RemediationError(f"{cid}: same-source span already present")


def _verify_mixed033_duplicate(evidence_lines: list[str]) -> tuple[str, dict]:
    matches = [(line, json.loads(line)) for line in evidence_lines
               if json.loads(line)["case_id"] == DEDUP_CASE_ID]
    if len(matches) != 2 or matches[0][0] != matches[1][0]:
        raise RemediationError("mixed-033 is not exactly one byte-identical pair")
    return matches[0]


def preflight(*, candidate_dir: Path = V209, chunks_path: Path = CHUNKS_PATH,
              chunk_manifest_path: Path = CHUNK_MANIFEST_PATH,
              current_draft_path: Path = CURRENT_DRAFT_PATH) -> dict:
    """Verify every authorised input before staging any v2.0.10 output."""
    candidate_manifest, draft, evidence, chunks = _verify_v209_candidate(
        candidate_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path,
    )
    reject_rows, mixed_033 = _verify_review_and_triage(
        candidate_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path,
        candidate_manifest=candidate_manifest,
    )
    draft_by_id = {row["id"]: row for row in draft}
    if RETIRED_CASE_ID not in draft_by_id:
        raise RemediationError("multi-019 missing from v2.0.9 draft")
    _verify_repair_specs(reject_rows, draft_by_id, evidence, chunks)

    evidence_lines = (candidate_dir / "evidence-after.jsonl").read_text(
        encoding="utf-8").splitlines()
    duplicate_line, duplicate_row = _verify_mixed033_duplicate(evidence_lines)
    graph = graph_mod._build_dependency_graph(draft, evidence)
    graph_mod._graph_gate(graph, draft_by_id, where="v2.0.9 candidate")
    scenario = graph_mod._retirement_scenario(graph, [RETIRED_CASE_ID])
    if not scenario.get("executable") or scenario.get("dangling_ref_count") != 0:
        raise RemediationError(
            f"multi-019 retirement is not safe: {scenario.get('dangling_refs')}")
    incoming = [edge for edge in graph["edges"] if edge["to"] == RETIRED_CASE_ID]
    if incoming:
        raise RemediationError(f"multi-019 has incoming reference(s): {incoming}")
    if len([row for row in evidence if row["case_id"] == RETIRED_CASE_ID]) != 1:
        raise RemediationError("multi-019 evidence row count drift")

    return {
        "candidate_manifest": candidate_manifest,
        "draft_rows": draft,
        "draft_by_id": draft_by_id,
        "evidence_rows": evidence,
        "draft_lines": (candidate_dir / "draft-after.jsonl").read_text(
            encoding="utf-8").splitlines(),
        "evidence_lines": evidence_lines,
        "chunks": chunks,
        "case_count": len(draft),
        "evidence_count": len(evidence),
        "strict_covered": len(evidence),
        "strict_passed": len(evidence),
        "repair_case_ids": list(REPAIR_CASE_IDS),
        "reject_rows": reject_rows,
        "mixed_033": {
            **mixed_033,
            "duplicate_line": duplicate_line,
            "duplicate_row": duplicate_row,
        },
        "retirement": {"scenario": scenario, "graph": graph},
    }


def _build_evidence_row(spec: dict, chunks: dict[str, dict]) -> dict:
    chunk = chunks[spec["chunk_id"]]
    raw_span = chunk["text"][spec["start"]:spec["end"]]
    if raw_span != spec["span"]:
        raise RemediationError(f"{spec['case_id']}: raw span drift during build")
    snippet = display_snippet(raw_span)
    return {
        "case_id": spec["case_id"],
        "chunk_id": spec["chunk_id"],
        "chunk_text_sha256": _sha256_text(chunk["text"]),
        "coordinate_contract": CONTRACT,
        "mapping_algorithm_version": ALGORITHM,
        "raw_chunk_char_range": {"start": spec["start"], "end": spec["end"]},
        "raw_evidence_span": raw_span,
        "snippet": snippet,
        "snippet_normalization": NORMALIZATION,
        "snippet_sha256": _sha256_text(snippet),
        "source_id": spec["source_id"],
    }


def _verify_after(draft_after: list[dict], evidence_after: list[dict],
                  chunks: dict[str, dict], retained_draft_lines: list[str],
                  retained_evidence_lines: list[str],
                  after_draft_lines: list[str],
                  after_evidence_lines: list[str]) -> dict:
    if len(draft_after) != EXPECTED_CASE_AFTER or \
            len(evidence_after) != EXPECTED_EVIDENCE_AFTER:
        raise RemediationError("v2.0.10 count conservation failed")
    by_id = {row["id"]: row for row in draft_after}
    if len(by_id) != len(draft_after) or RETIRED_CASE_ID in by_id:
        raise RemediationError("v2.0.10 draft identity failed")
    graph = graph_mod._build_dependency_graph(draft_after, evidence_after)
    graph_mod._graph_gate(graph, by_id, where="v2.0.10 candidate")
    dangling_to_retired = [edge for edge in graph["edges"]
                           if edge["to"] == RETIRED_CASE_ID]
    if dangling_to_retired:
        raise RemediationError(
            f"v2.0.10 has reference to retired multi-019: {dangling_to_retired}")
    try:
        strict_validate(evidence_after, chunks)
    except Exception as exc:
        raise RemediationError(f"v2.0.10 strict validation failed: {exc}") from exc
    if any(row.get("coordinate_contract") != CONTRACT for row in evidence_after):
        raise RemediationError("v2.0.10 contains legacy evidence")
    ev_per_case: dict[str, list[dict]] = defaultdict(list)
    for row in evidence_after:
        ev_per_case[row["case_id"]].append(row)
        if row["chunk_id"] not in chunks or \
                chunks[row["chunk_id"]]["source"] != row["source_id"]:
            raise RemediationError("v2.0.10 evidence source integrity failed")
    answerable = [row["id"] for row in draft_after if not row["should_refuse"]]
    refusal = [row["id"] for row in draft_after if row["should_refuse"]]
    if len(answerable) != EXPECTED_ANSWERABLE_CASES or \
            len(refusal) != EXPECTED_REFUSAL_CASES:
        raise RemediationError("v2.0.10 answerable/refusal count drift")
    if any(cid not in ev_per_case for cid in answerable) or \
            any(cid in ev_per_case for cid in refusal):
        raise RemediationError("v2.0.10 evidence coverage drift")
    exact_rows = [_line(row) for row in evidence_after]
    if len(set(exact_rows)) != len(exact_rows):
        raise RemediationError("v2.0.10 exact duplicate evidence remains")
    anchors = [(row["case_id"], row["chunk_id"],
                row["raw_chunk_char_range"]["start"],
                row["raw_chunk_char_range"]["end"])
               for row in evidence_after]
    if len(set(anchors)) != len(anchors):
        raise RemediationError("v2.0.10 duplicate evidence anchor remains")
    if after_draft_lines != retained_draft_lines:
        raise RemediationError("non-retired draft row bytes changed")
    if after_evidence_lines[:len(retained_evidence_lines)] != retained_evidence_lines:
        raise RemediationError("retained evidence row bytes changed")
    return {
        "strict_covered": len(evidence_after),
        "strict_passed": len(evidence_after),
        "answerable_cases_have_evidence": True,
        "refusal_cases_have_no_evidence": True,
        "no_dangling_case_refs": True,
        "evidence_rows_unique": True,
        "evidence_anchors_unique": True,
        "raw_spans_rebuildable": True,
        "non_target_rows_byte_identical": True,
        "graph": graph,
    }


def _data_quality_report(*, verify: dict, draft_after: list[dict],
                         evidence_after: list[dict], retired_case: dict,
                         retired_evidence: list[dict], additions: list[dict]) -> dict:
    checks = {
        "completeness": {
            "case_count_conserved": len(draft_after) == EXPECTED_CASE_AFTER,
            "evidence_count_conserved": len(evidence_after) == EXPECTED_EVIDENCE_AFTER,
            "all_answerable_cases_have_evidence":
                verify["answerable_cases_have_evidence"],
            "all_refusal_cases_have_no_evidence":
                verify["refusal_cases_have_no_evidence"],
        },
        "uniqueness": {
            "draft_case_ids_unique": len({row["id"] for row in draft_after}) == len(draft_after),
            "evidence_rows_unique": verify["evidence_rows_unique"],
            "evidence_anchors_unique": verify["evidence_anchors_unique"],
            "six_repair_actions_unique": len({row["case_id"] for row in additions}) == 6,
        },
        "referential_integrity": {
            "no_dangling_case_references": verify["no_dangling_case_refs"],
            "retired_case_absent_from_after":
                retired_case["case_id"] not in {row["id"] for row in draft_after},
            "retired_evidence_absent_from_after":
                all(row["case_id"] == RETIRED_CASE_ID for row in retired_evidence),
            "same_source_additions_declared": all(
                row["source_id"] == next(spec["source_id"] for spec in REPAIR_SPECS
                                         if spec["case_id"] == row["case_id"])
                for row in additions),
        },
        "continuity": {
            "all_raw_spans_rebuildable": verify["raw_spans_rebuildable"],
            "non_target_rows_byte_identical": verify["non_target_rows_byte_identical"],
            "retired_original_draft_preserved": bool(retired_case["original_draft_row"]),
            "retired_original_evidence_preserved": all(
                bool(row["original_evidence_row"]) for row in retired_evidence),
        },
        "consistency": {
            "strict_covered_equals_passed":
                verify["strict_covered"] == verify["strict_passed"] == EXPECTED_EVIDENCE_AFTER,
            "expected_action_conservation":
                EXPECTED_EVIDENCE_BEFORE - 1 - 1 + len(additions)
                == EXPECTED_EVIDENCE_AFTER,
            "candidate_remains_blocked": True,
            "no_review_results_reused": True,
        },
    }
    return {
        "dataset": "v2.0.10 owner-authorized coherence-remediation candidate",
        "grain": "one draft case and one raw-codepoint evidence row",
        "deterministic_data_quality_checks": checks,
        "findings": [],
        "skill": {
            "name": "data-analytics:analyze-data-quality",
            "available": True,
            "applied": "workflow adapted to deterministic candidate validation",
        },
        "risk": "CANDIDATE only; strict-coordinate validity is not review approval",
    }


def _review_and_split_notice() -> str:
    return (
        "# REVIEW_AND_SPLIT_REBUILD_REQUIRED\n\n"
        "v2.0.10 is a **CANDIDATE** (`activation_blocked=true`, "
        "`human_reviewed=false`).\n\n"
        "- This authorised deterministic remediation adds six same-source raw "
        "evidence rows, retires `multi-019`, and removes one byte-identical "
        "`mixed-033` duplicate evidence row.\n"
        "- v2.0.9 draft/evidence/review/triage remain immutable inputs.\n"
        "- A new full blind automated review of all 136 cases is required; no "
        "previous review result may be reused.\n"
        "- Do not create active metadata, a split, a locked configuration, or a "
        "v2.1 artifact unless a later explicit gate permits it.\n"
        "- Passing strict evidence validation is not human review, confirmation, "
        "or activation approval.\n"
    )


def _input_hashes(candidate_dir: Path, *, chunks_path: Path,
                  chunk_manifest_path: Path,
                  current_draft_path: Path) -> dict[str, str]:
    review_dir = candidate_dir / "automated-review"
    triage_dir = review_dir / TRIAGE_DIR_NAME
    paths = {
        "v209-manifest.json": candidate_dir / "manifest.json",
        "v209-draft-after.jsonl": candidate_dir / "draft-after.jsonl",
        "v209-evidence-after.jsonl": candidate_dir / "evidence-after.jsonl",
        "v209-review-manifest.json": review_dir / "manifest.json",
        "v209-review-issues.jsonl": review_dir / "automated-review-issues.jsonl",
        "v209-triage-manifest.json": triage_dir / "manifest.json",
        "v209-triage-reject-root-cause-triage.jsonl":
            triage_dir / "reject-root-cause-triage.jsonl",
        "v209-mixed-033-duplicate-evidence-check.json":
            triage_dir / "mixed-033-duplicate-evidence-check.json",
        "chunks.jsonl": chunks_path,
        "chunk-manifest.json": chunk_manifest_path,
        "current-v2-draft.jsonl": current_draft_path,
        "translation-equivalence-policy.md": V208 / "translation-equivalence-policy.md",
        "translation-equivalence-policy-ledger.jsonl":
            V208 / "translation-equivalence-policy-ledger.jsonl",
    }
    return {name: _sha256_file(_require(path, name)) for name, path in paths.items()}


def _atomic_directory_write(out_dir: Path, files: dict[str, str]) -> None:
    if out_dir.exists():
        raise RemediationError(f"output directory already exists: {out_dir}")
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".v210-", dir=str(out_dir.parent)))
    try:
        for name, content in files.items():
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        os.replace(staging, out_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        raise


def run(*, out_dir: Path = OUT, candidate_dir: Path = V209,
        chunks_path: Path = CHUNKS_PATH,
        chunk_manifest_path: Path = CHUNK_MANIFEST_PATH,
        current_draft_path: Path = CURRENT_DRAFT_PATH) -> dict:
    """Build v2.0.10 atomically after all fail-closed checks have passed."""
    if out_dir.exists():
        raise RemediationError(f"output directory already exists: {out_dir}")
    checks = preflight(candidate_dir=candidate_dir, chunks_path=chunks_path,
                       chunk_manifest_path=chunk_manifest_path,
                       current_draft_path=current_draft_path)

    draft_before_lines = checks["draft_lines"]
    evidence_before_lines = checks["evidence_lines"]
    draft_by_id = checks["draft_by_id"]
    evidence_by_case: dict[str, list[dict]] = defaultdict(list)
    for row in checks["evidence_rows"]:
        evidence_by_case[row["case_id"]].append(row)

    retained_draft_lines = [line for line in draft_before_lines
                            if json.loads(line)["id"] != RETIRED_CASE_ID]
    if len(retained_draft_lines) != EXPECTED_CASE_AFTER:
        raise RemediationError("draft retirement count drift")

    duplicate_line = checks["mixed_033"]["duplicate_line"]
    duplicate_removed = False
    retired_evidence_original: list[dict] = []
    retained_evidence_lines: list[str] = []
    for line in evidence_before_lines:
        row = json.loads(line)
        if row["case_id"] == RETIRED_CASE_ID:
            retired_evidence_original.append(row)
            continue
        if row["case_id"] == DEDUP_CASE_ID and line == duplicate_line:
            if duplicate_removed:
                continue
            duplicate_removed = True
        retained_evidence_lines.append(line)
    if not duplicate_removed or len(retired_evidence_original) != 1 or \
            len(retained_evidence_lines) != EXPECTED_EVIDENCE_BEFORE - 2:
        raise RemediationError("authorised evidence removals drift")

    additions = [_build_evidence_row(spec, checks["chunks"])
                 for spec in REPAIR_SPECS]
    addition_lines = [_line(row) for row in additions]
    evidence_after_lines = retained_evidence_lines + addition_lines
    draft_after = [json.loads(line) for line in retained_draft_lines]
    evidence_after = [json.loads(line) for line in evidence_after_lines]
    verify = _verify_after(
        draft_after, evidence_after, checks["chunks"], retained_draft_lines,
        retained_evidence_lines, retained_draft_lines, evidence_after_lines)

    retired_case = {
        "case_id": RETIRED_CASE_ID,
        "retired_reason": RETIRE_REASON,
        "retired_by": ACTOR,
        "authorization": AUTHORIZATION,
        "evidence_rows_removed": len(retired_evidence_original),
        "answer_points_removed": len(
            draft_by_id[RETIRED_CASE_ID].get("acceptable_answer_points") or []),
        "retirement_scenario": checks["retirement"]["scenario"],
        "original_draft_row": draft_by_id[RETIRED_CASE_ID],
    }
    retired_evidence = [{
        "case_id": RETIRED_CASE_ID,
        "retired_reason": RETIRE_REASON,
        "retired_by": ACTOR,
        "authorization": AUTHORIZATION,
        "original_evidence_row": row,
    } for row in retired_evidence_original]
    deduplicated = {
        "case_id": DEDUP_CASE_ID,
        "deduplication_reason": DEDUP_REASON,
        "deduplicated_by": ACTOR,
        "authorization": AUTHORIZATION,
        "kept_one_identical_row": True,
        "original_evidence_row": checks["mixed_033"]["duplicate_row"],
    }
    diff_rows = [
        {
            "case_id": spec["case_id"],
            "action": "add_same_source_evidence_scope",
            "marker": SCOPE_MARKER,
            "authorization": AUTHORIZATION,
            "chunk_id": spec["chunk_id"],
            "source_id": spec["source_id"],
            "raw_chunk_char_range": {"start": spec["start"], "end": spec["end"]},
            "raw_evidence_span": spec["span"],
        }
        for spec in REPAIR_SPECS
    ] + [
        {
            "case_id": RETIRED_CASE_ID,
            "action": "retire_case",
            "authorization": AUTHORIZATION,
            "retired_reason": RETIRE_REASON,
            "retirement_scenario": checks["retirement"]["scenario"],
        },
        {
            "case_id": DEDUP_CASE_ID,
            "action": "remove_byte_identical_duplicate_evidence",
            "authorization": AUTHORIZATION,
            "deduplication_reason": DEDUP_REASON,
        },
    ]
    quality_report = _data_quality_report(
        verify=verify, draft_after=draft_after, evidence_after=evidence_after,
        retired_case=retired_case, retired_evidence=retired_evidence,
        additions=additions,
    )
    files = {
        "draft-before.jsonl": "\n".join(draft_before_lines) + "\n",
        "evidence-before.jsonl": "\n".join(evidence_before_lines) + "\n",
        "draft-after.jsonl": "\n".join(retained_draft_lines) + "\n",
        "evidence-after.jsonl": "\n".join(evidence_after_lines) + "\n",
        "added-same-source-evidence.jsonl":
            "".join(_line(row) + "\n" for row in additions),
        "retired-cases.jsonl": _line(retired_case) + "\n",
        "retired-evidence.jsonl":
            "".join(_line(row) + "\n" for row in retired_evidence),
        "deduplicated-evidence.jsonl": _line(deduplicated) + "\n",
        "field-level-diff.jsonl": "".join(_line(row) + "\n" for row in diff_rows),
        "data-quality-report.json": _dump(quality_report),
        "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md": _review_and_split_notice(),
    }
    input_hashes_before = _input_hashes(
        candidate_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path,
    )
    manifest = _manifest({
        "task": "v2.0.10-owner-authorized-coherence-remediation",
        "created_by": "corpus_v2_v210_owner_authorized_coherence_remediation.py",
        "rule_version": RULE_VERSION,
        "run_at": TIMESTAMP,
        "deterministic": True,
        "gate_verdict": GATE_OK,
        "revision_status": "CANDIDATE",
        "activation_blocked": True,
        "human_reviewed": False,
        "overlay_generated": False,
        "split_reseal_required": True,
        "v2_1_entered": False,
        "actor": ACTOR,
        "authorization": AUTHORIZATION,
        "counts": {
            "case_before": EXPECTED_CASE_BEFORE,
            "case_after": EXPECTED_CASE_AFTER,
            "evidence_before": EXPECTED_EVIDENCE_BEFORE,
            "evidence_after": EXPECTED_EVIDENCE_AFTER,
            "same_source_evidence_added": len(additions),
            "retired_cases": 1,
            "retired_evidence": len(retired_evidence),
            "duplicate_evidence_removed": 1,
        },
        "inputs": input_hashes_before,
        "outputs": {name: _sha256_text(text) for name, text in files.items()},
        "declarations": {
            "llm_called": False,
            "network_used": False,
            "review_results_reused": False,
            "overlay_generated": False,
            "active_created": False,
            "split_created": False,
            "v2_1_entered": False,
            "data_modified": "six_same_source_additions_one_retirement_one_deduplication",
            "input_scope": [
                "v2.0.9 candidate draft/evidence/manifest",
                "v2.0.9 automated review manifest/issues",
                "v2.0.9 coherence-reject-triage artifacts",
                "current chunks/chunk manifest/current draft",
                "translation-equivalence policy/ledger hash verification only",
                "raw-codepoint strict validator",
            ],
        },
        "validation": {
            "case_count_exact": len(draft_after) == EXPECTED_CASE_AFTER,
            "evidence_count_exact": len(evidence_after) == EXPECTED_EVIDENCE_AFTER,
            "strict_covered_equals_passed":
                verify["strict_covered"] == verify["strict_passed"] == EXPECTED_EVIDENCE_AFTER,
            "all_answerable_cases_have_evidence": verify["answerable_cases_have_evidence"],
            "no_dangling_case_references": verify["no_dangling_case_refs"],
            "evidence_rows_unique": verify["evidence_rows_unique"],
            "non_target_rows_byte_identical": verify["non_target_rows_byte_identical"],
            "mixed_033_exact_duplicate_removed": True,
            "input_hashes_unchanged_during_build": True,
        },
        "skill_note": "data-analytics:analyze-data-quality workflow applied to deterministic five-dimension candidate validation",
    })
    files["manifest.json"] = _dump(manifest)
    input_hashes_after = _input_hashes(
        candidate_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path,
    )
    if input_hashes_before != input_hashes_after:
        raise RemediationError("an input SHA changed during build")
    if set(files) != set(OUTPUT_FILES):
        raise RemediationError("output file contract drift")
    _atomic_directory_write(out_dir, files)
    return {"manifest": manifest, "draft_after": draft_after,
            "evidence_after": evidence_after, "quality": quality_report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build v2.0.10 owner-authorized coherence remediation candidate")
    parser.add_argument("command", choices=("build",), nargs="?", default="build")
    parser.add_argument("--out-dir", default=str(OUT))
    parser.add_argument("--candidate-dir", default=str(V209))
    parser.add_argument("--chunks", default=str(CHUNKS_PATH))
    parser.add_argument("--chunk-manifest", default=str(CHUNK_MANIFEST_PATH))
    parser.add_argument("--current-draft", default=str(CURRENT_DRAFT_PATH))
    ns = parser.parse_args(argv)
    try:
        result = run(out_dir=Path(ns.out_dir), candidate_dir=Path(ns.candidate_dir),
                     chunks_path=Path(ns.chunks),
                     chunk_manifest_path=Path(ns.chunk_manifest),
                     current_draft_path=Path(ns.current_draft))
    except RemediationError as exc:
        print(f"coherence remediation failed closed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"gate": result["manifest"]["gate_verdict"],
                      "case_count": len(result["draft_after"]),
                      "evidence_count": len(result["evidence_after"]),
                      "out_dir": str(ns.out_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
