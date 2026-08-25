"""Build the owner-authorised v2.0.11 en-048 same-source repair candidate.

The input v2.0.10 candidate, its automated review and its coherence-reject
triage pack remain immutable.  This program applies exactly one authorised
change: one new raw-codepoint evidence row for ``en-048``, taken verbatim from
the single verified ``same_source`` candidate published by the v2.0.10 triage
(``reject-root-cause-triage.jsonl``).  It never searches for another candidate,
never touches any other case/answer point/evidence/chunk, and fails closed
before creating an output directory on any drift.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.corpus_v2_evidence_coordinate_repair import (  # noqa: E402
    display_snippet,
    strict_validate,
    strict_validate_row,
)

V208 = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.8-owner-authorized-semantic-quality-remediation"
CANDIDATE = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.10-owner-authorized-coherence-remediation"
TRIAGE_DIR = CANDIDATE / "automated-review" / "coherence-reject-triage"
OUT = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.11-owner-authorized-en048-same-source-repair"
CHUNKS_PATH = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST_PATH = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT_PATH = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"
TRANS_POLICY_PATH = V208 / "translation-equivalence-policy.md"
TRANS_LEDGER_PATH = V208 / "translation-equivalence-policy-ledger.jsonl"

TIMESTAMP = "2026-08-11T00:00:00+00:00"
RULE_VERSION = "v2.0.11-owner-authorized-en048-same-source-repair-1"
ACTOR = "OWNER_AUTHORIZED_V2_0_11_EN048_SAME_SOURCE_REPAIR"
AUTHORIZATION = "OWNER_AUTHORIZED_EN048_SAME_SOURCE_REPAIR"
GATE_OK = "EN048_SAME_SOURCE_REPAIR_CANDIDATE_OK"
CANDIDATE_ORIGIN = "v2.0.10-coherence-reject-triage"
SCOPE_MARKER = "OWNER_AUTHORIZED_SAME_SOURCE_EVIDENCE_SCOPE_REPAIR"
CONTRACT = "raw-codepoint-v1"
ALGORITHM = "raw-span-map-1"
NORMALIZATION = "display-whitespace-v1"

TARGET_CASE_ID = "en-048"
ERROR_CASES = ("en-052", "mixed-030", "mixed-033", "zh-040")

EXPECTED_CASE_BEFORE = 136
EXPECTED_EVIDENCE_BEFORE = 148
EXPECTED_CASE_AFTER = 136
EXPECTED_EVIDENCE_AFTER = 149
EXPECTED_REFUSAL_CASES = 31
EXPECTED_ANSWERABLE_CASES = 105

CASE_ID_RE = re.compile(r"^(multi|mixed|zh|en|noanswer)-\d+$")

OUTPUT_FILES = (
    "draft-before.jsonl",
    "evidence-before.jsonl",
    "draft-after.jsonl",
    "evidence-after.jsonl",
    "added-same-source-evidence.jsonl",
    "field-level-diff.jsonl",
    "data-quality-report.json",
    "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md",
    "manifest.json",
)


class RepairError(Exception):
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
        raise RepairError(f"missing {label}: {path}")
    return path


def _verify_outputs(manifest: dict, directory: Path, label: str) -> None:
    for name, digest in (manifest.get("outputs") or {}).items():
        path = directory / name
        if not path.is_file() or _sha256_file(path) != digest:
            raise RepairError(f"{label} output SHA mismatch: {name}")


def _verify_input_hashes(manifest: dict, mapping: dict[str, Path],
                         label: str) -> None:
    inputs = manifest.get("inputs") or {}
    if not inputs:
        raise RepairError(f"{label} inputs missing")
    for name, digest in inputs.items():
        path = mapping.get(name)
        if path is None or not path.is_file() or _sha256_file(path) != digest:
            raise RepairError(f"{label} input SHA mismatch: {name}")


def _load_chunks(path: Path) -> dict[str, dict]:
    rows = _jsonl(path)
    chunks = {row["chunk_id"]: row for row in rows}
    if len(chunks) != len(rows):
        raise RepairError("duplicate chunk_id in chunks")
    return chunks


# ── v2.0.10 输入核验（candidate / review / triage）──────────────────────

def _v210_input_sha_map(*, chunks_path: Path, chunk_manifest_path: Path,
                        current_draft_path: Path) -> dict[str, Path]:
    review_dir = CANDIDATE / "automated-review"
    return {
        "v209-manifest.json": ROOT / "evaluation/datasets/v2/revisions" /
            "v2.0.9-owner-authorized-final-dependency-closed-retirement" /
            "manifest.json",
        "v209-draft-after.jsonl": ROOT / "evaluation/datasets/v2/revisions" /
            "v2.0.9-owner-authorized-final-dependency-closed-retirement" /
            "draft-after.jsonl",
        "v209-evidence-after.jsonl": ROOT / "evaluation/datasets/v2/revisions" /
            "v2.0.9-owner-authorized-final-dependency-closed-retirement" /
            "evidence-after.jsonl",
        "v209-review-manifest.json": ROOT / "evaluation/datasets/v2/revisions" /
            "v2.0.9-owner-authorized-final-dependency-closed-retirement" /
            "automated-review" / "manifest.json",
        "v209-review-issues.jsonl": ROOT / "evaluation/datasets/v2/revisions" /
            "v2.0.9-owner-authorized-final-dependency-closed-retirement" /
            "automated-review" / "automated-review-issues.jsonl",
        "v209-triage-manifest.json": ROOT / "evaluation/datasets/v2/revisions" /
            "v2.0.9-owner-authorized-final-dependency-closed-retirement" /
            "automated-review" / "coherence-reject-triage" / "manifest.json",
        "v209-triage-reject-root-cause-triage.jsonl": ROOT /
            "evaluation/datasets/v2/revisions" /
            "v2.0.9-owner-authorized-final-dependency-closed-retirement" /
            "automated-review" / "coherence-reject-triage" /
            "reject-root-cause-triage.jsonl",
        "v209-mixed-033-duplicate-evidence-check.json": ROOT /
            "evaluation/datasets/v2/revisions" /
            "v2.0.9-owner-authorized-final-dependency-closed-retirement" /
            "automated-review" / "coherence-reject-triage" /
            "mixed-033-duplicate-evidence-check.json",
        "chunks.jsonl": chunks_path,
        "chunk-manifest.json": chunk_manifest_path,
        "current-v2-draft.jsonl": current_draft_path,
        "translation-equivalence-policy.md": TRANS_POLICY_PATH,
        "translation-equivalence-policy-ledger.jsonl": TRANS_LEDGER_PATH,
    }


def _verify_v210_candidate(candidate_dir: Path, *, chunks_path: Path,
                           chunk_manifest_path: Path,
                           current_draft_path: Path
                           ) -> tuple[dict, list[dict], list[str], dict]:
    """v2.0.10 candidate：自哈希、gate、metadata、counts、输出/输入 SHA、strict。"""
    manifest_path = _require(candidate_dir / "manifest.json", "v2.0.10 manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not _verify_self_hash(manifest):
        raise RepairError("v2.0.10 candidate manifest self-hash mismatch")
    if manifest.get("gate_verdict") != "COHERENCE_REMEDIATION_CANDIDATE_OK":
        raise RepairError("v2.0.10 candidate gate mismatch")
    if manifest.get("revision_status") != "CANDIDATE" or \
            manifest.get("activation_blocked") is not True or \
            manifest.get("human_reviewed") is not False or \
            manifest.get("overlay_generated") is not False or \
            manifest.get("split_reseal_required") is not True or \
            manifest.get("v2_1_entered") is not False:
        raise RepairError("v2.0.10 candidate metadata drift")
    counts = manifest.get("counts") or {}
    if counts.get("case_after") != EXPECTED_CASE_BEFORE or \
            counts.get("evidence_after") != EXPECTED_EVIDENCE_BEFORE or \
            counts.get("retired_cases") != 1 or \
            counts.get("retired_evidence") != 1 or \
            counts.get("duplicate_evidence_removed") != 1 or \
            counts.get("same_source_evidence_added") != 6:
        raise RepairError(f"v2.0.10 candidate counts drift: {counts}")
    _verify_outputs(manifest, candidate_dir, "v2.0.10 candidate")
    _verify_input_hashes(
        manifest,
        _v210_input_sha_map(chunks_path=chunks_path,
                            chunk_manifest_path=chunk_manifest_path,
                            current_draft_path=current_draft_path),
        "v2.0.10 candidate",
    )

    draft = _jsonl(_require(candidate_dir / "draft-after.jsonl", "draft-after"))
    evidence_lines = _require(candidate_dir / "evidence-after.jsonl",
                              "evidence-after").read_text(
        encoding="utf-8").splitlines()
    evidence = [json.loads(line) for line in evidence_lines if line.strip()]
    if len(draft) != EXPECTED_CASE_BEFORE or \
            len({row["id"] for row in draft}) != EXPECTED_CASE_BEFORE:
        raise RepairError("v2.0.10 draft count or uniqueness drift")
    if len(evidence) != EXPECTED_EVIDENCE_BEFORE:
        raise RepairError("v2.0.10 evidence count drift")
    chunks = _load_chunks(chunks_path)
    try:
        strict_validate(evidence, chunks)
    except Exception as exc:
        raise RepairError(f"v2.0.10 strict validation failed: {exc}") from exc
    if any(row.get("coordinate_contract") != CONTRACT for row in evidence):
        raise RepairError("v2.0.10 evidence contains legacy coordinate rows")
    return manifest, draft, evidence_lines, chunks


def _verify_review_and_triage(candidate_dir: Path, *, chunks_path: Path,
                              chunk_manifest_path: Path,
                              current_draft_path: Path) -> list[dict]:
    """v2.0.10 automated-review + coherence-reject-triage 全部核验。"""
    review_dir = candidate_dir / "automated-review"
    review_manifest_path = _require(review_dir / "manifest.json", "review manifest")
    review_manifest = json.loads(review_manifest_path.read_text(encoding="utf-8"))
    if not _verify_self_hash(review_manifest):
        raise RepairError("v2.0.10 review manifest self-hash mismatch")
    if review_manifest.get("gate_verdict") != "AUTOMATED_REVIEW_GATE_BLOCKED":
        raise RepairError("v2.0.10 review gate mismatch")
    _verify_outputs(review_manifest, review_dir, "v2.0.10 review")
    review_input_map = {
        "candidate-draft-after.jsonl": candidate_dir / "draft-after.jsonl",
        "candidate-evidence-after.jsonl": candidate_dir / "evidence-after.jsonl",
        "candidate-manifest.json": candidate_dir / "manifest.json",
        "chunks.jsonl": chunks_path,
        "chunk-manifest.json": chunk_manifest_path,
        "current-v2-draft.jsonl": current_draft_path,
        "translation-equivalence-policy.md": TRANS_POLICY_PATH,
        "translation-equivalence-policy-ledger.jsonl": TRANS_LEDGER_PATH,
    }
    _verify_input_hashes(review_manifest, review_input_map, "v2.0.10 review")
    if (review_manifest.get("counts") or {}) != {
        "case_count": 136, "evidence_count": 148, "answerable_cases": 105,
        "refusal_cases": 31, "confirmed": 113, "reject": 19,
        "needs_followup": 0, "errors": 4,
    }:
        raise RepairError(f"v2.0.10 review counts drift: "
                          f"{review_manifest.get('counts')}")

    triage_dir = review_dir / "coherence-reject-triage"
    triage_manifest_path = _require(triage_dir / "manifest.json", "triage manifest")
    triage_manifest = json.loads(triage_manifest_path.read_text(encoding="utf-8"))
    if not _verify_self_hash(triage_manifest):
        raise RepairError("v2.0.10 triage manifest self-hash mismatch")
    if triage_manifest.get("gate_verdict") != "COHERENCE_REJECT_TRIAGE_OK":
        raise RepairError("v2.0.10 triage gate mismatch")
    _verify_outputs(triage_manifest, triage_dir, "v2.0.10 triage")
    triage_inputs = {
        "candidate-draft-after.jsonl": candidate_dir / "draft-after.jsonl",
        "candidate-evidence-after.jsonl": candidate_dir / "evidence-after.jsonl",
        "chunk-manifest.json": chunk_manifest_path,
        "chunks.jsonl": chunks_path,
        "review-issues.jsonl": review_dir / "automated-review-issues.jsonl",
        "review-manifest.json": review_dir / "manifest.json",
    }
    _verify_input_hashes(triage_manifest, triage_inputs, "v2.0.10 triage")
    if (triage_manifest.get("counts") or {}) != {        "case_count": 136, "confirmed": 113, "errors": 4,
        "evidence_count": 148, "issues_rows": 23, "needs_followup": 0,
        "reject": 19,
    }:
        raise RepairError(f"v2.0.10 triage counts drift: "
                          f"{triage_manifest.get('counts')}")

    rows = _jsonl(_require(triage_dir / "reject-root-cause-triage.jsonl",
                           "reject-root-cause-triage"))
    if len(rows) != 19 or len({row.get("case_id") for row in rows}) != 19:
        raise RepairError("v2.0.10 triage reject rows drift")
    error_rows = _jsonl(_require(triage_dir / "review-coherence-errors.jsonl",
                                 "review-coherence-errors"))
    if len(error_rows) != 4 or \
            {row.get("case_id") for row in error_rows} != set(ERROR_CASES):
        raise RepairError("v2.0.10 triage error rows drift")
    template_rows = _jsonl(_require(triage_dir / "owner-decision-template.jsonl",
                                    "owner-decision-template"))
    if len(template_rows) != 23 or \
            len({row.get("case_id") for row in template_rows}) != 23:
        raise RepairError("v2.0.10 triage owner template drift")
    return rows


def _verify_en048_triage_row(row: dict, draft_by_id: dict[str, dict],
                             evidence_rows: list[dict],
                             chunks: dict[str, dict]) -> dict:
    """逐项验证 en-048 的 same_source 候选（唯一授权事实，不得重新搜索）。"""
    if row.get("case_id") != TARGET_CASE_ID:
        raise RepairError("en-048 triage row identity drift")
    if row.get("suggested_action") != "repair_candidate":
        raise RepairError("en-048 triage action drift")
    if row.get("case_classification") != "same_source":
        raise RepairError("en-048 triage classification drift")

    candidates = row.get("same_source_candidates") or []
    if len(candidates) != 1:
        raise RepairError(
            f"en-048 same_source candidate count {len(candidates)} != 1")
    cand = candidates[0]

    # AP 级关系必须与 case 级候选一致
    ap_matches = [ap for ap in row.get("answer_point_relations") or []
                  if ap.get("classification") == "same_source" and
                  ap.get("evidence_relation") == "same_source_candidate" and
                  ap.get("same_source_candidates") == candidates]
    if len(ap_matches) != 1:
        raise RepairError("en-048 AP-level same_source relation drift")

    required = ("source_id", "chunk_id", "start", "end", "span", "via",
                "unique", "overlaps_existing")
    if not all(k in cand for k in required):
        raise RepairError(f"en-048 candidate provenance missing keys: "
                          f"{sorted(set(required) - set(cand))}")
    if not isinstance(cand["start"], int) or not isinstance(cand["end"], int) or \
            cand["end"] <= cand["start"]:
        raise RepairError("en-048 candidate range invalid")
    if cand.get("unique") != 1:
        raise RepairError("en-048 candidate uniqueness drift")
    if cand.get("overlaps_existing") is not False:
        raise RepairError("en-048 candidate overlap flag drift")

    # source/chunk/Unicode [start,end) / raw span 与 chunk 原文严格一致
    chunk = chunks.get(cand["chunk_id"])
    if chunk is None or chunk.get("source") != cand["source_id"]:
        raise RepairError("en-048 candidate source/chunk drift")
    raw_span = chunk["text"][cand["start"]:cand["end"]]
    if raw_span != cand["span"]:
        raise RepairError("en-048 candidate span no longer rebuilds")
    if chunk["text"].count(cand["span"]) != 1:
        raise RepairError("en-048 candidate span not unique in chunk")

    # candidate 必须来自 draft 声明的 source
    draft_row = draft_by_id.get(TARGET_CASE_ID)
    if draft_row is None:
        raise RepairError("en-048 missing from draft")
    if cand["source_id"] not in (draft_row.get("relevant_source_ids") or []):
        raise RepairError("en-048 candidate not from a declared source")

    # 不与现有 evidence span 重叠、anchor 不重复
    for e in evidence_rows:
        if e["chunk_id"] != cand["chunk_id"]:
            continue
        rng = e["raw_chunk_char_range"]
        if e["case_id"] == TARGET_CASE_ID:
            if cand["start"] < rng["end"] and rng["start"] < cand["end"]:
                raise RepairError("en-048 candidate overlaps existing evidence span")
        key = (e["case_id"], e["chunk_id"], rng["start"], rng["end"])
        if key == (TARGET_CASE_ID, cand["chunk_id"], cand["start"], cand["end"]):
            raise RepairError("en-048 candidate anchor already present")
    return cand


def preflight(*, candidate_dir: Path = CANDIDATE, chunks_path: Path = CHUNKS_PATH,
              chunk_manifest_path: Path = CHUNK_MANIFEST_PATH,
              current_draft_path: Path = CURRENT_DRAFT_PATH) -> dict:
    """Verify every authorised input before staging any v2.0.11 output."""
    candidate_manifest, draft, evidence_lines, chunks = _verify_v210_candidate(
        candidate_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path)
    reject_rows = _verify_review_and_triage(
        candidate_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path)

    draft_by_id = {row["id"]: row for row in draft}
    evidence = [json.loads(line) for line in evidence_lines if line.strip()]
    en048_row = next((r for r in reject_rows if r["case_id"] == TARGET_CASE_ID),
                     None)
    if en048_row is None:
        raise RepairError("en-048 missing from v2.0.10 triage")
    candidate = _verify_en048_triage_row(en048_row, draft_by_id, evidence, chunks)

    return {
        "candidate_manifest": candidate_manifest,
        "draft_rows": draft,
        "draft_by_id": draft_by_id,
        "evidence_lines": evidence_lines,
        "chunks": chunks,
        "candidate": candidate,
        "case_count": len(draft),
        "evidence_count": len(evidence),
        "strict_covered": len(evidence),
        "strict_passed": len(evidence),
        "en048_authorized": True,
        "candidate_rebuilds": True,
        "candidate_unique": True,
        "no_span_overlap": True,
        "no_duplicate_anchor": True,
        "declared_source": True,
        "case_count_ok": True,
        "evidence_count_ok": True,
        "strict_covered_equals_passed": True,
        "candidate_manifest_ok": True,
        "review_manifest_ok": True,
        "triage_manifest_ok": True,
        "input_sha_ok": True,
    }


def _build_evidence_row(candidate: dict, chunks: dict[str, dict]) -> dict:
    chunk = chunks[candidate["chunk_id"]]
    raw_span = chunk["text"][candidate["start"]:candidate["end"]]
    if raw_span != candidate["span"]:
        raise RepairError("en-048 raw span drift during build")
    snippet = display_snippet(raw_span)
    return {
        "case_id": TARGET_CASE_ID,
        "chunk_id": candidate["chunk_id"],
        "chunk_text_sha256": _sha256_text(chunk["text"]),
        "coordinate_contract": CONTRACT,
        "mapping_algorithm_version": ALGORITHM,
        "raw_chunk_char_range": {"start": candidate["start"],
                                 "end": candidate["end"]},
        "raw_evidence_span": raw_span,
        "snippet": snippet,
        "snippet_normalization": NORMALIZATION,
        "snippet_sha256": _sha256_text(snippet),
        "source_id": candidate["source_id"],
    }


def _verify_after(draft_after: list[dict], evidence_after: list[dict],
                  chunks: dict[str, dict], draft_before_lines: list[str],
                  evidence_before_lines: list[str],
                  after_draft_lines: list[str],
                  after_evidence_lines: list[str]) -> dict:
    if len(draft_after) != EXPECTED_CASE_AFTER or \
            len(evidence_after) != EXPECTED_EVIDENCE_AFTER:
        raise RepairError("v2.0.11 count conservation failed")
    by_id = {row["id"]: row for row in draft_after}
    if len(by_id) != len(draft_after):
        raise RepairError("v2.0.11 draft identity failed")
    try:
        strict_validate(evidence_after, chunks)
    except Exception as exc:
        raise RepairError(f"v2.0.11 strict validation failed: {exc}") from exc
    if any(row.get("coordinate_contract") != CONTRACT for row in evidence_after):
        raise RepairError("v2.0.11 contains legacy evidence")
    ev_per_case: dict[str, list[dict]] = defaultdict(list)
    for row in evidence_after:
        ev_per_case[row["case_id"]].append(row)
        if row["chunk_id"] not in chunks or \
                chunks[row["chunk_id"]]["source"] != row["source_id"]:
            raise RepairError("v2.0.11 evidence source integrity failed")
    answerable = [row["id"] for row in draft_after if not row["should_refuse"]]
    refusal = [row["id"] for row in draft_after if row["should_refuse"]]
    if len(answerable) != EXPECTED_ANSWERABLE_CASES or \
            len(refusal) != EXPECTED_REFUSAL_CASES:
        raise RepairError("v2.0.11 answerable/refusal count drift")
    if any(cid not in ev_per_case for cid in answerable) or \
            any(cid in ev_per_case for cid in refusal):
        raise RepairError("v2.0.11 evidence coverage drift")
    exact_rows = [_line(row) for row in evidence_after]
    if len(set(exact_rows)) != len(exact_rows):
        raise RepairError("v2.0.11 exact duplicate evidence remains")
    anchors = [(row["case_id"], row["chunk_id"],
                row["raw_chunk_char_range"]["start"],
                row["raw_chunk_char_range"]["end"])
               for row in evidence_after]
    if len(set(anchors)) != len(anchors):
        raise RepairError("v2.0.11 duplicate evidence anchor remains")
    # 连续性：draft 内 case-id 引用全部指向现存 case
    dangling = []
    for row in draft_after:
        meta = row.get("metadata") or {}
        for key in ("follow_up_to", "chain_id"):
            v = meta.get(key)
            if isinstance(v, str) and CASE_ID_RE.match(v) and v not in by_id:
                dangling.append((row["id"], key, v))
        pt = meta.get("previous_turns")
        if isinstance(pt, list):
            for i, v in enumerate(pt):
                if isinstance(v, str) and CASE_ID_RE.match(v) and v not in by_id:
                    dangling.append((row["id"], f"previous_turns[{i}]", v))
        dt = row.get("doc_target")
        if isinstance(dt, str) and CASE_ID_RE.match(dt) and dt not in by_id:
            dangling.append((row["id"], "doc_target", dt))
    if dangling:
        raise RepairError(f"v2.0.11 draft continuity drift: {dangling}")
    # 字节级守恒：draft 全量一致；evidence 仅允许末尾追加一条
    if after_draft_lines != draft_before_lines:
        raise RepairError("v2.0.11 draft row bytes changed")
    if len(after_evidence_lines) != len(evidence_before_lines) + 1 or \
            after_evidence_lines[:len(evidence_before_lines)] != evidence_before_lines:
        raise RepairError("v2.0.11 retained evidence row bytes changed")
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
    }


def _data_quality_report(*, verify: dict, draft_after: list[dict],
                         evidence_after: list[dict], addition: dict,
                         candidate: dict) -> dict:
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
            "single_repair_action_unique": addition["case_id"] == TARGET_CASE_ID,
        },
        "referential_integrity": {
            "no_dangling_case_references": verify["no_dangling_case_refs"],
            "added_evidence_source_declared":
                addition["source_id"] in (next(
                    row["relevant_source_ids"] for row in draft_after
                    if row["id"] == TARGET_CASE_ID)),
            "same_source_addition_declared":
                addition["source_id"] == candidate["source_id"],
        },
        "continuity": {
            "all_raw_spans_rebuildable": verify["raw_spans_rebuildable"],
            "non_target_rows_byte_identical":
                verify["non_target_rows_byte_identical"],
            "draft_unchanged_byte_identical": True,
            "candidate_origin_recorded": True,
        },
        "consistency": {
            "strict_covered_equals_passed":
                verify["strict_covered"] == verify["strict_passed"] == EXPECTED_EVIDENCE_AFTER,
            "expected_action_conservation":
                EXPECTED_EVIDENCE_BEFORE + 1 == EXPECTED_EVIDENCE_AFTER,
            "candidate_remains_blocked": True,
            "no_review_results_reused": True,
        },
    }
    return {
        "dataset": "v2.0.11 owner-authorized en-048 same-source repair candidate",
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
        "v2.0.11 is a **CANDIDATE** (`activation_blocked=true`, "
        "`human_reviewed=false`).\n\n"
        "- This authorised deterministic repair adds exactly one same-source "
        "raw evidence row for `en-048` (span `functions`, chunk "
        "`761b22915b5e_chunk_14`), taken verbatim from the single verified "
        "same-source candidate of the v2.0.10 coherence-reject-triage pack.\n"
        "- v2.0.10 draft/evidence/review/triage remain immutable inputs.\n"
        "- A targeted blind Pro-only re-review of the remaining 22 non-confirmed "
        "issues (and, later, a full review) is required; no previous review "
        "result may be reused.\n"
        "- Do not create active metadata, a split, a locked configuration, or a "
        "v2.1 artifact unless a later explicit gate permits it.\n"
        "- Passing strict evidence validation is not human review, confirmation, "
        "or activation approval.\n"
    )


def _input_hashes(candidate_dir: Path, *, chunks_path: Path,
                  chunk_manifest_path: Path,
                  current_draft_path: Path) -> dict[str, str]:
    review_dir = candidate_dir / "automated-review"
    triage_dir = review_dir / "coherence-reject-triage"
    paths = {
        "v210-manifest.json": candidate_dir / "manifest.json",
        "v210-draft-after.jsonl": candidate_dir / "draft-after.jsonl",
        "v210-evidence-after.jsonl": candidate_dir / "evidence-after.jsonl",
        "v210-review-manifest.json": review_dir / "manifest.json",
        "v210-review-issues.jsonl": review_dir / "automated-review-issues.jsonl",
        "v210-triage-manifest.json": triage_dir / "manifest.json",
        "v210-triage-reject-root-cause-triage.jsonl":
            triage_dir / "reject-root-cause-triage.jsonl",
        "v210-triage-owner-decision-template.jsonl":
            triage_dir / "owner-decision-template.jsonl",
        "v210-triage-review-coherence-errors.jsonl":
            triage_dir / "review-coherence-errors.jsonl",
        "chunks.jsonl": chunks_path,
        "chunk-manifest.json": chunk_manifest_path,
        "current-v2-draft.jsonl": current_draft_path,
        "translation-equivalence-policy.md": TRANS_POLICY_PATH,
        "translation-equivalence-policy-ledger.jsonl": TRANS_LEDGER_PATH,
    }
    return {name: _sha256_file(_require(path, name))
            for name, path in paths.items()}


def _atomic_directory_write(out_dir: Path, files: dict[str, str]) -> None:
    if out_dir.exists():
        raise RepairError(f"output directory already exists: {out_dir}")
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".v211-", dir=str(out_dir.parent)))
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


def run(*, out_dir: Path = OUT, candidate_dir: Path = CANDIDATE,
        chunks_path: Path = CHUNKS_PATH,
        chunk_manifest_path: Path = CHUNK_MANIFEST_PATH,
        current_draft_path: Path = CURRENT_DRAFT_PATH) -> dict:
    """Build v2.0.11 atomically after all fail-closed checks have passed."""
    if out_dir.exists():
        raise RepairError(f"output directory already exists: {out_dir}")
    checks = preflight(candidate_dir=candidate_dir, chunks_path=chunks_path,
                       chunk_manifest_path=chunk_manifest_path,
                       current_draft_path=current_draft_path)

    draft_before_lines = (candidate_dir / "draft-after.jsonl").read_text(
        encoding="utf-8").splitlines()
    evidence_before_lines = checks["evidence_lines"]
    if len(draft_before_lines) != EXPECTED_CASE_BEFORE or \
            len(evidence_before_lines) != EXPECTED_EVIDENCE_BEFORE:
        raise RepairError("v2.0.11 before-count drift")

    addition = _build_evidence_row(checks["candidate"], checks["chunks"])
    addition_line = _line(addition)
    evidence_after_lines = evidence_before_lines + [addition_line]
    draft_after = [json.loads(line) for line in draft_before_lines]
    evidence_after = [json.loads(line) for line in evidence_after_lines]
    verify = _verify_after(
        draft_after, evidence_after, checks["chunks"], draft_before_lines,
        evidence_before_lines, draft_before_lines, evidence_after_lines)
    # 新增行单独过 strict validator（独立于整体校验）
    strict_validate_row(addition, checks["chunks"])

    diff_row = {
        "case_id": TARGET_CASE_ID,
        "action": "add_same_source_evidence_scope",
        "marker": SCOPE_MARKER,
        "authorization": AUTHORIZATION,
        "candidate_origin": CANDIDATE_ORIGIN,
        "chunk_id": addition["chunk_id"],
        "source_id": addition["source_id"],
        "raw_chunk_char_range": addition["raw_chunk_char_range"],
        "raw_evidence_span": addition["raw_evidence_span"],
        "via": checks["candidate"]["via"],
        "unique": checks["candidate"]["unique"],
        "overlaps_existing": checks["candidate"]["overlaps_existing"],
    }
    quality_report = _data_quality_report(
        verify=verify, draft_after=draft_after, evidence_after=evidence_after,
        addition=addition, candidate=checks["candidate"])

    files = {
        "draft-before.jsonl": "\n".join(draft_before_lines) + "\n",
        "evidence-before.jsonl": "\n".join(evidence_before_lines) + "\n",
        "draft-after.jsonl": "\n".join(draft_before_lines) + "\n",
        "evidence-after.jsonl": "\n".join(evidence_after_lines) + "\n",
        "added-same-source-evidence.jsonl": _line(addition) + "\n",
        "field-level-diff.jsonl": _line(diff_row) + "\n",
        "data-quality-report.json": _dump(quality_report),
        "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md": _review_and_split_notice(),
    }
    input_hashes_before = _input_hashes(
        candidate_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path)
    manifest = _manifest({
        "task": "v2.0.11-owner-authorized-en048-same-source-repair",
        "created_by": "corpus_v2_v211_owner_authorized_en048_repair.py",
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
            "same_source_evidence_added": 1,
            "retired_cases": 0,
            "retired_evidence": 0,
            "duplicate_evidence_removed": 0,
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
            "data_modified": "one_same_source_evidence_added_for_en048",
            "candidate_origin": "v2.0.10-coherence-reject-triage-verified-same-source-candidate",
            "input_scope": [
                "v2.0.10 candidate draft/evidence/manifest",
                "v2.0.10 automated review manifest/issues",
                "v2.0.10 coherence-reject-triage artifacts",
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
            "all_answerable_cases_have_evidence":
                verify["answerable_cases_have_evidence"],
            "no_dangling_case_references": verify["no_dangling_case_refs"],
            "evidence_rows_unique": verify["evidence_rows_unique"],
            "evidence_anchors_unique": verify["evidence_anchors_unique"],
            "draft_byte_identical_to_v210": True,
            "evidence_non_target_rows_byte_identical":
                verify["non_target_rows_byte_identical"],
            "same_source_candidate_rebuilds": True,
            "same_source_candidate_unique": True,
            "no_evidence_span_overlap": True,
            "input_hashes_unchanged_during_build": True,
        },
        "skill_note": "data-analytics:analyze-data-quality workflow applied to deterministic five-dimension candidate validation",
    })
    files["manifest.json"] = _dump(manifest)
    input_hashes_after = _input_hashes(
        candidate_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path)
    if input_hashes_before != input_hashes_after:
        raise RepairError("an input SHA changed during build")
    if set(files) != set(OUTPUT_FILES):
        raise RepairError("output file contract drift")
    _atomic_directory_write(out_dir, files)
    return {"manifest": manifest, "draft_after": draft_after,
            "evidence_after": evidence_after, "quality": quality_report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build v2.0.11 owner-authorized en-048 same-source repair candidate")
    parser.add_argument("command", choices=("build",), nargs="?", default="build")
    parser.add_argument("--out-dir", default=str(OUT))
    parser.add_argument("--candidate-dir", default=str(CANDIDATE))
    parser.add_argument("--chunks", default=str(CHUNKS_PATH))
    parser.add_argument("--chunk-manifest", default=str(CHUNK_MANIFEST_PATH))
    parser.add_argument("--current-draft", default=str(CURRENT_DRAFT_PATH))
    ns = parser.parse_args(argv)
    try:
        result = run(out_dir=Path(ns.out_dir), candidate_dir=Path(ns.candidate_dir),
                     chunks_path=Path(ns.chunks),
                     chunk_manifest_path=Path(ns.chunk_manifest),
                     current_draft_path=Path(ns.current_draft))
    except RepairError as exc:
        print(f"en-048 repair failed closed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"gate": result["manifest"]["gate_verdict"],
                      "case_count": len(result["draft_after"]),
                      "evidence_count": len(result["evidence_after"]),
                      "out_dir": str(ns.out_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
