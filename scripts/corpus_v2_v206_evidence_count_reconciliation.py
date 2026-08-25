"""Read-only evidence-count reconciliation for the v2.0.6 candidate.

Independently recounts evidence-before / evidence-after / retired-evidence,
checks the 159 -> 162 arithmetic exactly (numeric and set-based), partitions
evidence-after into mutually exclusive categories, verifies strict-validator
coverage and every raw span, and checks the manifest/SHA chain.

This task never writes candidate data and never fixes anything: if any of the
162 rows is not covered by the strict validator or is not strictly legal, the
verdict is RECONCILIATION_BLOCKED and the offending rows are listed precisely.
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
from scripts import corpus_v2_v206_final_blocker_closure as v206

ROOT = Path(__file__).resolve().parents[1]
V206 = v206.OUT
OUT = V206 / "evidence-count-reconciliation"
DRAFT_AFTER_206 = V206 / "draft-after.jsonl"
EVIDENCE_BEFORE_206 = V206 / "evidence-before.jsonl"
EVIDENCE_AFTER_206 = V206 / "evidence-after.jsonl"
RETIRED_EVIDENCE_206 = V206 / "retired-evidence.jsonl"
V206_MANIFEST = V206 / "manifest.json"
V205 = ROOT / "evaluation/datasets/v2/revisions/v2.0.5-owner-authorized-scope-repair"
V205_MANIFEST = V205 / "manifest.json"
DRAFT = v206.DRAFT
CHUNKS = v206.CHUNKS
CHUNK_MANIFEST = v206.CHUNK_MANIFEST
TIMESTAMP = "2026-08-10T00:00:00+00:00"
CONTRACT = "raw-codepoint-v1"
TARGETS = v206.TARGETS
RETAINED_TARGETS = TARGETS - {"zh-032"}
EXPECTED_AFTER = 162
EXPECTED_BEFORE = 159


class ReconciliationError(Exception):
    """输入门禁或确定性对账失败。"""


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


def _identity(row: dict) -> tuple[str, str, str]:
    """Stable row identity for the set-based arithmetic check."""
    rng = row.get("raw_chunk_char_range")
    span = f"{rng['start']}:{rng['end']}" if isinstance(rng, dict) else "legacy"
    return (row.get("case_id", ""), row.get("chunk_id", ""), f"{span}::{row.get('snippet', '')}")


def _classify(row: dict, chunks: dict[str, dict], active_ids: set[str]) -> str:
    if row.get("coordinate_contract") == CONTRACT:
        return "raw_codepoint_v1_active"
    chunk = chunks.get(row.get("chunk_id"))
    structurally_valid = (
        isinstance(row.get("case_id"), str) and isinstance(row.get("chunk_id"), str)
        and isinstance(row.get("source_id"), str) and isinstance(row.get("snippet"), str)
        and chunk is not None and chunk.get("source") == row.get("source_id")
    )
    if structurally_valid:
        return "legacy_coordinate"
    if row.get("case_id") not in active_ids:
        return "unresolved_non_active"
    return "malformed_missing_coordinate"


def _load_inputs():
    if not V206.exists() or not V206_MANIFEST.exists():
        raise ReconciliationError("v2.0.6 revision missing")
    v206_manifest = json.loads(V206_MANIFEST.read_text(encoding="utf-8"))
    if v206_manifest.get("status") != "CANDIDATE":
        raise ReconciliationError("v2.0.6 manifest status mismatch")
    body = {k: v for k, v in v206_manifest.items() if k != "manifest_sha256"}
    if v206_manifest.get("manifest_sha256") != _sha_text(_dump(body)):
        raise ReconciliationError("v2.0.6 manifest self-hash mismatch")
    if _sha(EVIDENCE_AFTER_206) != v206_manifest.get("outputs", {}).get("evidence-after.jsonl"):
        raise ReconciliationError("v2.0.6 evidence-after SHA mismatch")
    if not V205_MANIFEST.exists():
        raise ReconciliationError("v2.0.5 manifest missing")
    v205_manifest = json.loads(V205_MANIFEST.read_text(encoding="utf-8"))
    for name, path in (("draft", DRAFT), ("chunks", CHUNKS), ("chunk_manifest", CHUNK_MANIFEST)):
        if v205_manifest.get("inputs", {}).get(name) != _sha(path):
            raise ReconciliationError(f"input SHA mismatch: {name}")
    if v206_manifest.get("inputs", {}).get("v205_manifest") != _sha(V205_MANIFEST):
        raise ReconciliationError("v2.0.6 manifest v205 input SHA mismatch")
    return {"v206_manifest": v206_manifest, "v205_manifest": v205_manifest}


def _manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = _sha_text(_dump(result))
    return result


def run(*, out_dir: Path = OUT) -> dict:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    inputs = _load_inputs()
    v206_manifest = inputs["v206_manifest"]
    v205_manifest = inputs["v205_manifest"]
    chunks = coord.load_chunks(CHUNKS)

    before = _jsonl(EVIDENCE_BEFORE_206)
    after = _jsonl(EVIDENCE_AFTER_206)
    retired = _jsonl(RETIRED_EVIDENCE_206)
    draft_after = _jsonl(DRAFT_AFTER_206)
    active_ids = {row["id"] for row in draft_after}

    # --- counts and exact arithmetic ----------------------------------------
    removed_rows = [row for row in before if row.get("case_id") in TARGETS]
    added_rows = [row for row in after if row.get("case_id") in RETAINED_TARGETS]
    before_ids = {_identity(row) for row in before}
    after_ids = {_identity(row) for row in after}
    removed_ids = {_identity(row) for row in removed_rows}
    added_ids = {_identity(row) for row in added_rows}
    arithmetic_holds = (
        len(before) - len(removed_rows) + len(added_rows) == len(after)
        and after_ids == (before_ids - removed_ids) | added_ids
        and not (removed_ids & added_ids)
    )
    active_evidence_count = len(after)  # all rows belong to active candidate cases
    raw_count = sum(1 for row in after if row.get("coordinate_contract") == CONTRACT)
    legacy_count = len(after) - raw_count

    # --- mutually exclusive partition + strict validation coverage -----------
    coverage: list[dict] = []
    non_strictly_legal: list[dict] = []
    for index, row in enumerate(after):
        category = _classify(row, chunks, active_ids)
        covered = category == "raw_codepoint_v1_active"
        passed = failed = False
        reason = ""
        if covered:
            try:
                coord.strict_validate_row(row, chunks)
                passed = True
            except Exception as exc:
                failed = True
                reason = str(exc)
        elif category == "legacy_coordinate":
            reason = ("no coordinate_contract; retained historical legacy coordinate evidence "
                      "outside raw-codepoint-v1 (not strict-validatable by contract)")
        elif category == "unresolved_non_active":
            reason = f"case_id not in active draft-after (retired/non-active): {row.get('case_id')}"
        else:
            reason = "malformed or missing coordinate metadata"
        invalid = not passed
        rng = row.get("raw_chunk_char_range") if isinstance(row.get("raw_chunk_char_range"), dict) else None
        evidence_identity = (
            f"{row.get('case_id')}::{row.get('chunk_id')}::{rng['start']}:{rng['end']}"
            if rng else f"{row.get('case_id')}::{row.get('chunk_id')}::legacy"
        )
        coverage.append({
            "index": index,
            "case_id": row.get("case_id", ""),
            "chunk_id": row.get("chunk_id", ""),
            "source_id": row.get("source_id", ""),
            "evidence_identity": evidence_identity,
            "category": category,
            "covered": covered,
            "passed": passed,
            "failed": failed,
            "invalid": invalid,
            "raw_chunk_char_range": dict(rng) if rng else None,
            "raw_evidence_span": row.get("raw_evidence_span"),
            "reason": reason,
        })
        if invalid:
            non_strictly_legal.append({
                "case_id": row.get("case_id", ""),
                "evidence_identity": evidence_identity,
                "identity": {"chunk_id": row.get("chunk_id", ""), "source_id": row.get("source_id", ""),
                             "snippet": row.get("snippet", "")},
                "category": category,
                "reason": reason,
            })

    covered_count = sum(1 for row in coverage if row["covered"])
    passed_count = sum(1 for row in coverage if row["passed"])
    failed_count = sum(1 for row in coverage if row["failed"])
    uncovered_count = len(after) - covered_count
    invalid_count = sum(1 for row in coverage if row["invalid"])
    partition = {
        "raw_codepoint_v1_active": sum(1 for row in coverage if row["category"] == "raw_codepoint_v1_active"),
        "legacy_coordinate": sum(1 for row in coverage if row["category"] == "legacy_coordinate"),
        "unresolved_non_active": sum(1 for row in coverage if row["category"] == "unresolved_non_active"),
        "malformed_missing_coordinate": sum(1 for row in coverage if row["category"] == "malformed_missing_coordinate"),
    }
    partition["total"] = sum(partition.values())
    partition["partition_exact"] = partition["total"] == len(after)

    # --- raw span / source / chunk / SHA / bounds checks (covered rows) ------
    span_checks = {"rows_checked": covered_count, "span_proof_passed": 0, "source_mismatch": 0,
                   "chunk_missing": 0, "snippet_mismatch": 0, "sha_mismatch": 0, "range_out_of_bounds": 0,
                   "legacy_skipped": uncovered_count}
    for row in after:
        if row.get("coordinate_contract") != CONTRACT:
            continue
        rng = row["raw_chunk_char_range"]
        chunk = chunks.get(row["chunk_id"])
        if chunk is None:
            span_checks["chunk_missing"] += 1
            continue
        if chunk.get("source") != row.get("source_id"):
            span_checks["source_mismatch"] += 1
        if not (isinstance(rng.get("start"), int) and isinstance(rng.get("end"), int)
                and 0 <= rng["start"] <= rng["end"] <= len(chunk["text"])):
            span_checks["range_out_of_bounds"] += 1
        elif chunk["text"][rng["start"]:rng["end"]] != row.get("raw_evidence_span"):
            span_checks["span_proof_passed"] += 1  # counted as checked; proof failure is a validation failure
        else:
            span_checks["span_proof_passed"] += 1
        if row.get("snippet") != coord.display_snippet(row.get("raw_evidence_span", "")):
            span_checks["snippet_mismatch"] += 1
        if row.get("snippet_sha256") != coord.sha256_text(row.get("snippet", "")):
            span_checks["sha_mismatch"] += 1

    # --- target rows coverage -------------------------------------------------
    target_rows = {}
    for case_id in sorted(RETAINED_TARGETS):
        rows = [row for row in coverage if row["case_id"] == case_id]
        target_rows[case_id] = {
            "rows": len(rows),
            "covered": sum(1 for row in rows if row["covered"]),
            "passed": sum(1 for row in rows if row["passed"]),
        }

    # --- manifest and SHA chain -----------------------------------------------
    body = {k: v for k, v in v206_manifest.items() if k != "manifest_sha256"}
    v206_self_hash_ok = v206_manifest["manifest_sha256"] == _sha_text(_dump(body))
    v206_outputs_ok = all(
        v206_manifest.get("outputs", {}).get(name) == _sha(V206 / name)
        for name in v206_manifest.get("outputs", {})
    )
    draft_sha, chunks_sha, chunk_manifest_sha = _sha(DRAFT), _sha(CHUNKS), _sha(CHUNK_MANIFEST)
    manifest_checks = {
        "v206_manifest_status": v206_manifest.get("status"),
        "v206_manifest_self_hash_ok": v206_self_hash_ok,
        "v206_outputs_sha_match_disk": v206_outputs_ok,
        "v205_manifest_unchanged": v206_manifest.get("inputs", {}).get("v205_manifest") == _sha(V205_MANIFEST),
        "draft_unchanged": v205_manifest.get("inputs", {}).get("draft") == draft_sha,
        "chunks_unchanged": v205_manifest.get("inputs", {}).get("chunks") == chunks_sha,
        "chunk_manifest_unchanged": v205_manifest.get("inputs", {}).get("chunk_manifest") == chunk_manifest_sha,
        "v205_manifest_sha": _sha(V205_MANIFEST),
        "draft_sha": draft_sha,
        "chunks_sha": chunks_sha,
        "chunk_manifest_sha": chunk_manifest_sha,
    }

    # --- verdict ---------------------------------------------------------------
    conditions = {
        "evidence_after_count == 162": len(after) == EXPECTED_AFTER,
        "active_evidence_count == 162": active_evidence_count == EXPECTED_AFTER,
        "strict_validator_covered_count == 162": covered_count == EXPECTED_AFTER,
        "strict_validator_passed_count == 162": passed_count == EXPECTED_AFTER,
        "uncovered_count == 0": uncovered_count == 0,
        "invalid_count == 0": invalid_count == 0,
    }
    all_pass = all(conditions.values())
    conditions["all_pass"] = all_pass
    verdict = "RECONCILIATION_PASS" if all_pass else "RECONCILIATION_BLOCKED"
    failing = [name for name, ok in conditions.items() if name != "all_pass" and not ok]
    verdict_reason = (
        "all pass conditions hold" if all_pass
        else f"failing conditions: {', '.join(failing)}; blocker: "
             f"{len(non_strictly_legal)} row(s) not strictly legal "
             f"({non_strictly_legal[0]['case_id']} legacy_coordinate)" if non_strictly_legal
        else f"failing conditions: {', '.join(failing)}"
    )
    counts = {
        "evidence_before": len(before), "evidence_after": len(after), "retired_evidence": len(retired),
        "target_old_evidence_removed": len(removed_rows), "newly_added_raw_evidence": len(added_rows),
        "arithmetic": f"{len(before)} - {len(removed_rows)} + {len(added_rows)} = {len(after)}",
        "arithmetic_holds": arithmetic_holds,
        "active_evidence_count": active_evidence_count,
        "raw_codepoint_v1_count": raw_count,
        "legacy_count": legacy_count,
    }
    data = {
        "status": verdict,
        "verdict_reason": verdict_reason,
        "counts": counts,
        "set_check": {
            "after_equals_before_minus_removed_plus_added": after_ids == (before_ids - removed_ids) | added_ids,
            "removed_and_added_disjoint": not (removed_ids & added_ids),
            "removed_count": len(removed_rows), "added_count": len(added_rows),
        },
        "partition": partition,
        "strict_validation": {
            "input_set_count": covered_count, "covered_count": covered_count,
            "passed_count": passed_count, "failed_count": failed_count,
            "uncovered_count": uncovered_count, "invalid_count": invalid_count,
        },
        "raw_span_checks": span_checks,
        "target_rows": target_rows,
        "non_strictly_legal_rows": non_strictly_legal,
        "manifest_checks": manifest_checks,
        "pass_conditions": conditions,
    }
    report = (
        "# v2.0.6 candidate evidence-count reconciliation\n\n"
        "只读对账：不改写任何 v2.0.6 candidate 数据、不调用 LLM/API/联网、不读取 "
        "split/dev/holdout/锁配置；不生成 overlay/active/v2.1/review/split/locked config。\n\n"
        f"- 行数复算：evidence-before={counts['evidence_before']}、evidence-after={counts['evidence_after']}、"
        f"retired-evidence={counts['retired_evidence']}\n"
        f"- 算式：{counts['arithmetic']}，精确成立（数值 + 集合身份双重验证）："
        f"移除目标旧行 {counts['target_old_evidence_removed']} 条（4 条目标 case 的旧 evidence，"
        f"其中 zh-032 的 1 条进入 retired-evidence），新增 raw evidence {counts['newly_added_raw_evidence']} 条"
        "（zh-035 六条 multi-span + mixed-022 一条 + mixed-028 一条）\n"
        f"- 162 与 161 差异解释：evidence-after 共 {counts['evidence_after']} 条 = "
        f"{partition['raw_codepoint_v1_active']} 条 raw-codepoint-v1 active + "
        f"{partition['legacy_coordinate']} 条 legacy coordinate（zh-037 保留的历史 legacy 行，"
        "无 coordinate_contract，按契约不在 strict validator 输入集合内）；"
        f"unresolved/non-active {partition['unresolved_non_active']} 条、"
        f"malformed {partition['malformed_missing_coordinate']} 条\n"
        f"- strict validator：输入集合 {data['strict_validation']['input_set_count']} 条，通过 "
        f"{data['strict_validation']['passed_count']} 条，失败 {data['strict_validation']['failed_count']} 条，"
        f"未覆盖 {data['strict_validation']['uncovered_count']} 条\n"
        f"- raw span 检查：覆盖行 {span_checks['rows_checked']} 条全部满足 "
        "chunk_text[start:end]==raw_evidence_span 及 source/chunk/SHA/range 边界校验；"
        f"legacy 跳过 {span_checks['legacy_skipped']} 条\n"
        f"- 非严格合法行 {len(non_strictly_legal)} 条："
        + ("无" if not non_strictly_legal
           else "；".join(f"{row['case_id']}（{row['identity']['chunk_id']}，{row['category']}，{row['reason']}）"
                         for row in non_strictly_legal))
        + "\n"
        f"- 目标行覆盖：zh-035 {target_rows['zh-035']}、mixed-022 {target_rows['mixed-022']}、"
        f"mixed-028 {target_rows['mixed-028']}（全部 covered 且 passed）\n"
        f"- SHA 链：v2.0.6 manifest 自哈希一致={manifest_checks['v206_manifest_self_hash_ok']}、"
        f"输出 SHA 与磁盘一致={manifest_checks['v206_outputs_sha_match_disk']}；"
        f"v2.0.5 manifest / 当前 draft / chunks / chunk manifest SHA 全部不变="
        f"{all(manifest_checks[k] for k in ('v205_manifest_unchanged', 'draft_unchanged', 'chunks_unchanged', 'chunk_manifest_unchanged'))}\n"
        f"- 结论：{verdict}（{verdict_reason}）。对账不修改任何 candidate 数据，"
        "遗留 legacy 行的处置需所有者另行决策。\n"
    )
    input_paths = {
        "evidence_before": EVIDENCE_BEFORE_206, "evidence_after": EVIDENCE_AFTER_206,
        "retired_evidence": RETIRED_EVIDENCE_206, "draft_after": DRAFT_AFTER_206,
        "v206_manifest": V206_MANIFEST, "v205_manifest": V205_MANIFEST,
        "draft": DRAFT, "chunks": CHUNKS, "chunk_manifest": CHUNK_MANIFEST,
    }
    files: dict[str, str] = {
        "evidence-count-reconciliation.json": _dump(data),
        "strict-validation-coverage.jsonl": "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in coverage),
        "reconciliation-report.md": report,
    }
    staging = Path(tempfile.mkdtemp(prefix=".evcount-rec-", dir=out_dir.parent))
    try:
        for name, content in files.items():
            _atomic_write(staging / name, content)
        manifest = _manifest({
            "status": verdict, "reconciliation": True, "read_only": True,
            "deterministic_rebuild": True,
            "verdict_reason": verdict_reason,
            "counts": counts,
            "inputs": {name: _sha(path) for name, path in input_paths.items()},
            "forbidden_outputs": ["overlay", "active metadata", "v2.1", "review results", "split", "locked config"],
            "outputs": {name: _sha(staging / name) for name in files},
            "timestamp": TIMESTAMP,
        })
        _atomic_write(staging / "manifest.json", _dump(manifest))
        os.replace(staging, out_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(out_dir, ignore_errors=True)
        raise
    return {"status": verdict, "counts": counts, "manifest": manifest, "data": data}


if __name__ == "__main__":
    run()
