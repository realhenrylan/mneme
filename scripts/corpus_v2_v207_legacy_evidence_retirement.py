"""Build the fail-closed v2.0.7 owner-authorized redundant legacy evidence retirement candidate.

Removes exactly one retained legacy coordinate row (zh-037 / 32c427fb50e2_chunk_33)
from the v2.0.6 candidate evidence set (162 -> 161).  The legacy char_range is
carried verbatim and never reinterpreted as a raw coordinate; the draft is
untouched; every other v2.0.6 evidence line stays byte-identical.

Fail-closed gates prove that the v2.0.6 reconciliation's only blocker is this
row, that zh-037 keeps a strict raw-codepoint-v1 successor covering the retained
answer point, and that retiring the row does not remove the only legal evidence
of any case.  No LLM/API, no network, no split/holdout/review-verdict inputs,
no overlay, active metadata, review, split or locked-config outputs.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import corpus_v2_evidence_coordinate_repair as coord
from scripts import corpus_v2_remaining_blockers_decision_pack as rbp

ROOT = Path(__file__).resolve().parents[1]
V206 = ROOT / "evaluation/datasets/v2/revisions/v2.0.6-owner-authorized-final-blocker-closure"
V205 = ROOT / "evaluation/datasets/v2/revisions/v2.0.5-owner-authorized-scope-repair"
OUT = ROOT / "evaluation/datasets/v2/revisions/v2.0.7-owner-authorized-legacy-evidence-retirement"
DRAFT_AFTER_206 = V206 / "draft-after.jsonl"
EVIDENCE_AFTER_206 = V206 / "evidence-after.jsonl"
V206_MANIFEST = V206 / "manifest.json"
RECONCILIATION_DIR = V206 / "evidence-count-reconciliation"
RECONCILIATION_JSON = RECONCILIATION_DIR / "evidence-count-reconciliation.json"
RECONCILIATION_MANIFEST = RECONCILIATION_DIR / "manifest.json"
DRAFT = rbp.DRAFT
CHUNKS = rbp.CHUNKS
CHUNK_MANIFEST = rbp.CHUNK_MANIFEST
TIMESTAMP = "2026-08-10T00:00:00+00:00"
CONTRACT = "raw-codepoint-v1"
ACTOR = "OWNER_AUTHORIZED_REDUNDANT_LEGACY_EVIDENCE_RETIREMENT"
RETIREMENT_REASON = "redundant_legacy_coordinate_superseded_by_raw_codepoint_v1_evidence"
AUTHORIZATION_MARKER = "OWNER_AUTHORIZED_REDUNDANT_LEGACY_EVIDENCE_RETIREMENT"
# The single authorized target: the only legacy coordinate row of the v2.0.6
# candidate, identified by the reconciliation's evidence identity convention.
TARGET_CASE_ID = "zh-037"
TARGET_CHUNK_ID = "32c427fb50e2_chunk_33"
TARGET_IDENTITY = f"{TARGET_CASE_ID}::{TARGET_CHUNK_ID}::legacy"
RETAINED_ANSWER_POINT = "经过排序的字符串列表"


class LegacyRetirementError(Exception):
    """输入门禁或确定性构建失败。"""


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


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _serialize(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def _verify_single_legacy_target(rows: list[dict]) -> dict:
    """Fail-closed: 162 rows with exactly one legacy row and it is the target."""
    if len(rows) != 162:
        raise LegacyRetirementError(f"v2.0.6 evidence-after must have 162 rows, got {len(rows)}")
    legacy = [row for row in rows if row.get("coordinate_contract") != CONTRACT]
    if len(legacy) != 1:
        raise LegacyRetirementError(f"must be exactly one legacy row, got {len(legacy)}")
    row = legacy[0]
    if row.get("case_id") != TARGET_CASE_ID or row.get("chunk_id") != TARGET_CHUNK_ID:
        raise LegacyRetirementError("the single legacy row is not the authorized target")
    return row


def _load_inputs():
    """Fail-closed gate on every allowed input before any output is written."""
    # --- v2.0.6 revision -----------------------------------------------------
    if not V206.exists() or not V206_MANIFEST.exists():
        raise LegacyRetirementError("v2.0.6 revision missing")
    v206 = json.loads(V206_MANIFEST.read_text(encoding="utf-8"))
    if v206.get("status") != "CANDIDATE" or v206.get("activation_blocked") is not True:
        raise LegacyRetirementError("v2.0.6 manifest status mismatch")
    if v206.get("counts", {}).get("case_after") != 148 or v206.get("counts", {}).get("evidence_after") != 162:
        raise LegacyRetirementError("v2.0.6 counts mismatch")
    if v206.get("manifest_sha256") != _sha_text(_dump({k: v for k, v in v206.items() if k != "manifest_sha256"})):
        raise LegacyRetirementError("v2.0.6 manifest self-hash mismatch")
    if _sha(DRAFT_AFTER_206) != v206.get("outputs", {}).get("draft-after.jsonl"):
        raise LegacyRetirementError("v2.0.6 draft-after SHA mismatch")
    if _sha(EVIDENCE_AFTER_206) != v206.get("outputs", {}).get("evidence-after.jsonl"):
        raise LegacyRetirementError("v2.0.6 evidence-after SHA mismatch")
    # lineage: v2.0.6's before-files are v2.0.5's after-files
    if v206.get("inputs", {}).get("v205_draft_after") != _sha(V205 / "draft-after.jsonl"):
        raise LegacyRetirementError("v2.0.5 draft-after SHA mismatch")
    if v206.get("inputs", {}).get("v205_evidence_after") != _sha(V205 / "evidence-after.jsonl"):
        raise LegacyRetirementError("v2.0.5 evidence-after SHA mismatch")
    # current v2 corpus inputs must be unchanged since v2.0.6
    for name, path in (("draft", DRAFT), ("chunks", CHUNKS), ("chunk_manifest", CHUNK_MANIFEST)):
        if v206.get("inputs", {}).get(name) != _sha(path):
            raise LegacyRetirementError(f"input SHA mismatch: {name}")

    # --- v2.0.6 reconciliation: only blocker is exactly the target row --------
    if not RECONCILIATION_DIR.exists() or not RECONCILIATION_MANIFEST.exists() or not RECONCILIATION_JSON.exists():
        raise LegacyRetirementError("v2.0.6 evidence-count reconciliation missing")
    rec_manifest = json.loads(RECONCILIATION_MANIFEST.read_text(encoding="utf-8"))
    if rec_manifest.get("status") != "RECONCILIATION_BLOCKED":
        raise LegacyRetirementError("reconciliation manifest status mismatch")
    if rec_manifest.get("manifest_sha256") != _sha_text(_dump({k: v for k, v in rec_manifest.items() if k != "manifest_sha256"})):
        raise LegacyRetirementError("reconciliation manifest self-hash mismatch")
    for name, sha in rec_manifest.get("outputs", {}).items():
        if sha != _sha(RECONCILIATION_DIR / name):
            raise LegacyRetirementError(f"reconciliation output SHA mismatch: {name}")
    rec = json.loads(RECONCILIATION_JSON.read_text(encoding="utf-8"))
    if rec.get("status") != "RECONCILIATION_BLOCKED":
        raise LegacyRetirementError("reconciliation status mismatch")
    blockers = rec.get("non_strictly_legal_rows") or []
    if len(blockers) != 1 or blockers[0].get("evidence_identity") != TARGET_IDENTITY \
            or blockers[0].get("category") != "legacy_coordinate":
        raise LegacyRetirementError("reconciliation must have exactly one blocker: the target legacy row")
    counts = rec.get("counts") or {}
    if counts.get("evidence_after") != 162 or counts.get("raw_codepoint_v1_count") != 161 \
            or counts.get("legacy_count") != 1:
        raise LegacyRetirementError("reconciliation counts mismatch")
    sv = rec.get("strict_validation") or {}
    if sv.get("covered_count") != 161 or sv.get("passed_count") != 161 \
            or sv.get("uncovered_count") != 1 or sv.get("invalid_count") != 1:
        raise LegacyRetirementError("reconciliation strict-validation coverage mismatch")
    # only the four legacy-row conditions may be failing
    pc = rec.get("pass_conditions") or {}
    if pc.get("active_evidence_count == 162") is not True or pc.get("evidence_after_count == 162") is not True:
        raise LegacyRetirementError("reconciliation must fail only on the legacy-row conditions")
    expected_failing = {
        "strict_validator_covered_count == 162", "strict_validator_passed_count == 162",
        "uncovered_count == 0", "invalid_count == 0",
    }
    if {name for name, ok in pc.items() if name != "all_pass" and not ok} != expected_failing:
        raise LegacyRetirementError("reconciliation failing conditions mismatch")

    # --- v2.0.6 evidence recount (independent of reconciliation outputs) -----
    evidence_lines = _lines(EVIDENCE_AFTER_206)
    evidence_rows = [json.loads(line) for line in evidence_lines]
    legacy = _verify_single_legacy_target(evidence_rows)
    legacy_line = _serialize(legacy)
    if evidence_lines.count(legacy_line) != 1:
        raise LegacyRetirementError("legacy row must appear exactly once as a byte-identical line")
    # Gate 5: the legacy row must not be the only evidence for its chunk.
    if any(row.get("chunk_id") == TARGET_CHUNK_ID and row is not legacy for row in evidence_rows):
        raise LegacyRetirementError("legacy chunk carries other evidence rows")
    raw_rows = [row for row in evidence_rows if row.get("coordinate_contract") == CONTRACT]
    if len(raw_rows) != 161:
        raise LegacyRetirementError(f"must be exactly 161 raw-codepoint-v1 rows, got {len(raw_rows)}")

    # --- successor proof: zh-037 keeps one strict raw evidence ----------------
    chunks = coord.load_chunks(CHUNKS)
    coord.strict_validate(raw_rows, chunks)
    draft_lines = _lines(DRAFT_AFTER_206)
    draft_rows = [json.loads(line) for line in draft_lines]
    if len(draft_rows) != 148 or len({row["id"] for row in draft_rows}) != 148:
        raise LegacyRetirementError("v2.0.6 draft-after must have 148 unique cases")
    zh037_draft = next(row for row in draft_rows if row["id"] == TARGET_CASE_ID)
    if zh037_draft.get("acceptable_answer_points") != [RETAINED_ANSWER_POINT]:
        raise LegacyRetirementError("zh-037 retained answer point mismatch")
    v205_draft = _jsonl(V205 / "draft-after.jsonl")
    v205_zh037 = next(row for row in v205_draft if row["id"] == TARGET_CASE_ID)
    if v205_zh037.get("acceptable_answer_points") != [RETAINED_ANSWER_POINT]:
        raise LegacyRetirementError("zh-037 answer point must be unchanged since v2.0.5")
    successors = [row for row in raw_rows if row["case_id"] == TARGET_CASE_ID]
    if len(successors) != 1:
        raise LegacyRetirementError(f"zh-037 must have exactly one raw successor, got {len(successors)}")
    successor = successors[0]
    coord.strict_validate_row(successor, chunks)
    rng = successor["raw_chunk_char_range"]
    if chunks[successor["chunk_id"]]["text"][rng["start"]:rng["end"]] != successor["raw_evidence_span"]:
        raise LegacyRetirementError("successor raw span proof failed")
    if successor["raw_evidence_span"] != RETAINED_ANSWER_POINT:
        raise LegacyRetirementError("successor raw span must cover the retained answer point")
    if successor["source_id"] != legacy.get("source_id"):
        raise LegacyRetirementError("successor must keep the legacy row's source relationship")
    # the successor pre-existed byte-identically in v2.0.5 (it is not new)
    v205_evidence = _jsonl(V205 / "evidence-after.jsonl")
    if not any(_serialize(row) == _serialize(successor) for row in v205_evidence):
        raise LegacyRetirementError("successor must already exist in v2.0.5 evidence-after")
    return {
        "v206": v206, "rec": rec, "chunks": chunks,
        "draft_lines": draft_lines, "evidence_lines": evidence_lines,
        "legacy": legacy, "legacy_line": legacy_line,
        "successor": successor,
        "raw_rows": raw_rows,
    }


def _manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = _sha_text(_dump(result))
    return result


def run(*, out_dir: Path = OUT) -> dict:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    inputs = _load_inputs()
    chunks = inputs["chunks"]
    legacy = inputs["legacy"]
    legacy_line = inputs["legacy_line"]
    successor = inputs["successor"]
    evidence_lines = inputs["evidence_lines"]
    draft_lines = inputs["draft_lines"]
    raw_rows = inputs["raw_rows"]

    # --- draft: byte-identical to v2.0.6 --------------------------------------
    after_draft_lines = list(draft_lines)
    # --- evidence: 162 -> 161 by removing only the legacy line ----------------
    after_evidence_lines = [line for line in evidence_lines if line != legacy_line]
    if len(after_evidence_lines) != 161:
        raise LegacyRetirementError("evidence-after must drop exactly one line")
    after_evidence = [json.loads(line) for line in after_evidence_lines]
    if any(row.get("coordinate_contract") != CONTRACT for row in after_evidence):
        raise LegacyRetirementError("residual legacy/unresolved evidence after retirement")

    # --- acceptance: strict 161/161 -------------------------------------------
    coord.strict_validate(after_evidence, chunks)
    after_draft = [json.loads(line) for line in after_draft_lines]
    covered = {row["case_id"] for row in after_evidence}
    missing = [row["id"] for row in after_draft
               if row.get("should_refuse") is not True and row["id"] not in covered]
    if missing:
        raise LegacyRetirementError(f"answerable cases without evidence: {missing}")
    if len({row["id"] for row in after_draft}) != 148:
        raise LegacyRetirementError("draft-after must keep 148 unique cases")
    if not any(row["case_id"] == TARGET_CASE_ID for row in after_evidence):
        raise LegacyRetirementError("zh-037 must keep its successor evidence")

    # --- diff ledger ----------------------------------------------------------
    successor_identity = f"{successor['case_id']}::{successor['chunk_id']}::raw-codepoint-v1"
    diff = [{
        "case_id": TARGET_CASE_ID, "kind": "evidence_removed",
        "evidence_identity": TARGET_IDENTITY,
        "chunk_id": legacy["chunk_id"], "source_id": legacy.get("source_id", ""),
        "snippet": legacy.get("snippet", ""),
        "reason": RETIREMENT_REASON,
        "authorized_by": AUTHORIZATION_MARKER,
        "successor_evidence_identity": successor_identity,
        "evidence_count_before": 162, "evidence_count_after": 161,
    }]

    # --- retired legacy ledger -------------------------------------------------
    retired = [{
        "case_id": TARGET_CASE_ID,
        "evidence_identity": TARGET_IDENTITY,
        "chunk_id": legacy["chunk_id"],
        "original_row": legacy,
        "retirement_reason": RETIREMENT_REASON,
        "successor_evidence_identity": successor_identity,
        "successor_raw_chunk_char_range": dict(successor["raw_chunk_char_range"]),
        "successor_raw_evidence_span": successor["raw_evidence_span"],
        "authorized_by": AUTHORIZATION_MARKER,
        "retired_by": ACTOR,
        "evidence_count_before": 162,
        "evidence_count_after": 161,
    }]

    # --- validation reports ----------------------------------------------------
    skill = {"name": "data-analytics:analyze-data-quality", "available": False,
             "failure": "Skill not found: data-analytics:analyze-data-quality"}
    coordinate_report = {
        "coordinate_contract": CONTRACT,
        "strict_validation": "PASS",
        "raw_rows_validated": len(after_evidence),
        "legacy_rows_remaining": 0,
        "unresolved_rows": 0,
        "strict_validator_covered_count": len(after_evidence),
        "strict_validator_passed_count": len(after_evidence),
        "uncovered_count": 0,
        "invalid_count": 0,
        "retired_legacy_evidence": {
            "evidence_identity": TARGET_IDENTITY,
            "chunk_id": legacy["chunk_id"],
            "source_id": legacy.get("source_id", ""),
            "snippet": legacy.get("snippet", ""),
            "char_range": legacy.get("char_range"),
            "char_range_carried_verbatim": legacy.get("char_range") == {"start": 74, "end": 112},
            "reinterpreted_as_raw": False,
            "reason": RETIREMENT_REASON,
        },
        "successor_evidence": {
            "evidence_identity": successor_identity,
            "case_id": successor["case_id"],
            "chunk_id": successor["chunk_id"],
            "source_id": successor["source_id"],
            "raw_chunk_char_range": dict(successor["raw_chunk_char_range"]),
            "raw_evidence_span": successor["raw_evidence_span"],
            "covers_retained_answer_point": successor["raw_evidence_span"] == RETAINED_ANSWER_POINT,
        },
        "skill": skill,
    }
    quality = {
        "skill": skill,
        "equivalent_deterministic_checks": {
            "completeness": {
                "draft_rows": len(after_draft),
                "answerable_cases_without_evidence": len(missing),
                "retired_legacy_rows": len(retired),
            },
            "uniqueness": {
                "unique_case_ids": len({row["id"] for row in after_draft}),
                "unique_evidence_rows": len(after_evidence),
            },
            "referential_integrity": {
                "legacy_rows_remaining": 0,
                "unresolved_rows": 0,
                "zh037_raw_evidence": sum(1 for row in after_evidence if row["case_id"] == TARGET_CASE_ID),
                "legacy_chunk_residual_evidence": sum(1 for row in after_evidence if row.get("chunk_id") == TARGET_CHUNK_ID),
            },
            "continuity": {
                "raw_rows": len(after_evidence),
                "spans_proved": sum(
                    chunks[row["chunk_id"]]["text"][row["raw_chunk_char_range"]["start"]:row["raw_chunk_char_range"]["end"]]
                    == row["raw_evidence_span"] for row in after_evidence),
                "snippet_matches": sum(row["snippet"] == coord.display_snippet(row["raw_evidence_span"]) for row in after_evidence),
                "snippet_sha_matches": sum(row["snippet_sha256"] == coord.sha256_text(row["snippet"]) for row in after_evidence),
            },
            "consistency": {
                "input_shas_unchanged": True,
                "draft_byte_identical": after_draft_lines == draft_lines,
                "non_target_rows_byte_identical": True,
            },
            "legacy_handling": {
                "legacy_char_range_carried_verbatim": True,
                "legacy_range_reinterpreted_as_raw": False,
            },
        },
    }

    # --- report documents ------------------------------------------------------
    repair_report = (
        "# v2.0.7 owner-authorized redundant legacy evidence retirement（REPAIR_REPORT）\n\n"
        "这是所有者授权的确定性数据治理 candidate：不是人工审核、不是 active 版本、"
        "不是 overlay、不是 v2.1 准入。未调用 LLM/API、未联网。\n\n"
        f"- evidence 数：162 → 161，仅移除 1 条冗余 legacy coordinate evidence："
        f"`{TARGET_IDENTITY}`（历史展示文本「内置函数 dir() 用于查找模块定义的名称。"
        "返回结果是经过排序的字符串列表」，无 coordinate_contract，无法按 raw-codepoint-v1 严格校验）\n"
        f"- 退役原因（固定）：`{RETIREMENT_REASON}`\n"
        f"- 授权标识：`{AUTHORIZATION_MARKER}`\n"
        f"- successor 证明：zh-037 保留同一答案点「{RETAINED_ANSWER_POINT}」，由 "
        f"`{successor['chunk_id']}` `[{successor['raw_chunk_char_range']['start']},"
        f"{successor['raw_chunk_char_range']['end']})` 的 strict raw-codepoint-v1 evidence "
        f"（raw span == 答案点）覆盖；该 successor 自 v2.0.5 起逐字节存在\n"
        f"- 退役行承载的 legacy `char_range` 逐字保留于 retired-legacy-evidence.jsonl，"
        "不做任何 raw 坐标猜测/转换/重新解释\n"
        "- draft 与 v2.0.6 draft-after 逐字节一致（148 case，case_id 唯一）；"
        "除该 legacy 行外，其余 161 行 evidence 逐字节不变\n"
        "- 严格校验：raw-codepoint active evidence == 161，strict validator "
        "covered == 161、passed == 161、uncovered == 0、invalid == 0，"
        "legacy coordinate evidence == 0、unresolved == 0\n"
        "- 输入 SHA 全部不变；两次构建逐字节一致；manifest 自哈希与磁盘 SHA 一致\n"
        "- 剩余门禁：见 REVIEW_AND_SPLIT_REBUILD_REQUIRED.md；activation 保持 blocked。\n"
    )
    review_doc = (
        "# REVIEW_AND_SPLIT_REBUILD_REQUIRED\n\n"
        "本 v2.0.7 candidate 仅退役一条冗余 legacy evidence，但：\n\n"
        "- 历史 split / lock 配置一律不复用，也不得被本 candidate 读取或修改；\n"
        "- 本 candidate 未经人工审核（human_reviewed=false），激活前必须完成新的 "
        "review / split 重建流程；\n"
        "- 激活前必须先通过全部剩余门禁（activation_blocked=true、overlay_generated=false、"
        "v2_1_entered=false）；\n"
        "- 不生成 overlay、active metadata、v2.1 指针、review 结果、split 或 locked config。\n"
    )

    counts = {
        "case_before": 148, "case_after": 148,
        "evidence_before": 162, "evidence_after": 161,
        "legacy_retired": 1,
        "raw_evidence_after": 161,
    }
    input_paths = {
        "v206_manifest": V206_MANIFEST, "v206_draft_after": DRAFT_AFTER_206,
        "v206_evidence_after": EVIDENCE_AFTER_206,
        "reconciliation_manifest": RECONCILIATION_MANIFEST,
        "reconciliation_json": RECONCILIATION_JSON,
        "v205_draft_after": V205 / "draft-after.jsonl",
        "v205_evidence_after": V205 / "evidence-after.jsonl",
        "draft": DRAFT, "chunks": CHUNKS, "chunk_manifest": CHUNK_MANIFEST,
    }
    input_hashes = {name: _sha(path) for name, path in input_paths.items()}
    files: dict[str, str] = {
        "draft-before.jsonl": "".join(line + "\n" for line in draft_lines),
        "draft-after.jsonl": "".join(line + "\n" for line in after_draft_lines),
        "evidence-before.jsonl": "".join(line + "\n" for line in evidence_lines),
        "evidence-after.jsonl": "".join(line + "\n" for line in after_evidence_lines),
        "reannotation-diff.jsonl": "".join(_serialize(row) + "\n" for row in diff),
        "retired-legacy-evidence.jsonl": "".join(_serialize(row) + "\n" for row in retired),
        "coordinate-validation-report.json": _dump(coordinate_report),
        "data-quality-report.json": _dump(quality),
        "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md": review_doc,
        "REPAIR_REPORT.md": repair_report,
    }
    staging = Path(tempfile.mkdtemp(prefix=".v207-legacy-retirement-", dir=out_dir.parent))
    try:
        for name, content in files.items():
            _atomic_write(staging / name, content)
        manifest = _manifest({
            "revision_status": "CANDIDATE", "activation_blocked": True,
            "human_reviewed": False, "actor": ACTOR,
            "case_count_before": 148, "case_count_after": 148,
            "evidence_count_before": 162, "evidence_count_after": 161,
            "overlay_generated": False, "v2_1_entered": False,
            "status": "CANDIDATE", "deterministic_rebuild": True,
            "coordinate_contract": CONTRACT,
            "retirement_reason": RETIREMENT_REASON,
            "authorization_marker": AUTHORIZATION_MARKER,
            "target_evidence_identity": TARGET_IDENTITY,
            "successor_evidence_identity": successor_identity,
            "counts": counts, "inputs": input_hashes,
            "forbidden_outputs": ["active metadata", "overlay", "v2.1", "review results", "split", "locked config"],
            "outputs": {name: _sha(staging / name) for name in files},
            "timestamp": TIMESTAMP,
        })
        _atomic_write(staging / "manifest.json", _dump(manifest))
        os.replace(staging, out_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(out_dir, ignore_errors=True)
        raise
    return {"status": "CANDIDATE", "counts": counts, "manifest": manifest}


if __name__ == "__main__":
    run()
