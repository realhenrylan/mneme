"""M6a Phase 2B: frozen-input preflight, offline paired replay, and core metrics."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT_DIR = ROOT / "results" / "answer-level" / "m6a-phase2b-2026-11-02"
BASELINE_REF = (
    "de8181f:results/answer-level/m6a-paired-2026-11-01/"
    "baseline-outcomes.jsonl"
)
BASELINE_PATH = (
    ROOT / "results" / "answer-level" / "m6a-paired-2026-11-01"
    / "baseline-outcomes.jsonl"
)
RUNTIME_PATH = (
    ROOT / "results" / "answer-level" / "chunk-domain-audit-2026-11-01"
    / "runtime-map.jsonl"
)
MAPPING_PATH = (
    ROOT / "results" / "answer-level" / "chunk-domain-audit-2026-11-01"
    / "mapping.jsonl"
)
DATASET_PATH = ROOT / "evaluation" / "datasets" / "v2.1.jsonl"
MODULE_PATH = ROOT / "src" / "citation_selection.py"
PHASE2A_MANIFEST_PATH = (
    ROOT / "results" / "answer-level" / "m6a-phase2a-2026-11-01"
    / "manifest.json"
)

EXPECTED_HEAD = "402bfffa0ee0b2de6b694df3af02ef44ec935f1a"
BASE_COMMIT = "004e903691943267c261f892ebe16e256df7f71f"
M6A_COMMIT = "614e2605b749d41a137f7b9d1e97e85ba52d907e"
PHASE2A_COMMIT = "744f3738fa2f8eb8552a7ebb420ce67dcde1036b"
BASELINE_BLOB_SHA256 = (
    "5cd71261507a8367c9acb160bb71406fc289e85a19ed761a6fe0604ba85a5c54"
)
BASELINE_RAW_DISCLOSURE_SHA256 = (
    "16d4797c05d68820d474ad42e92a540b25e7508dcd8f6c6cb0b33d1ee47989c6"
)
RUNTIME_RAW_SHA256 = (
    "efe8595872891da599c41ba1ac2031cff181c2f3f7823bb74c7f514889193275"
)
MAPPING_RAW_SHA256 = (
    "d63bf48af0a18d5b49ed3957159b84af71a056242c9af47843f94e9b4973d42d"
)
DATASET_LF_SHA256 = (
    "4597167dadd72ba972373bedc44d27c858b7c7ddbe42f8ede9d37021b38e92a9"
)
DATASET_RAW_DISCLOSURE_SHA256 = (
    "88fa2928f545cf6bcdd4948cbd389e2488e769cf38d0a0db13fc9a1ffc7b27c5"
)
MODULE_SHA256 = (
    "ee9963c76cbf580238b5914a3b1a34d6265bdd66a5bdbfeb3523a457bccc1613"
)
SUPPORTED_STATUSES = {"supported_chunk", "supported_source"}
SLOT_RE = re.compile(r"\[S(\d+)\]")
SLOT_BYTES_RE = re.compile(rb"\[S\d+\]")
THRESHOLD = 0.50
CANDIDATES = {
    "A": lambda c: c["ratio_runtime"] >= THRESHOLD,
    "B": lambda c: (
        c["ratio_runtime"] >= THRESHOLD
        and c["ratio_store"] >= THRESHOLD
    ),
    "C": lambda c: c["ratio_store"] >= THRESHOLD,
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def jsonl_rows(data: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in data.decode("utf-8").splitlines()
            if line.strip()]


def read_git_blob(ref_path: str) -> bytes:
    proc = subprocess.run(
        ["git", "show", ref_path], cwd=ROOT,
        capture_output=True, check=False,
    )
    if proc.returncode:
        raise RuntimeError(
            f"git show {ref_path} failed: "
            f"{proc.stderr.decode('utf-8', 'replace')[:300]}"
        )
    return proc.stdout


def line_count(data: bytes) -> int:
    return sum(1 for line in data.splitlines() if line.strip())


def round4(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def make_passing(
    mapping_rows: list[dict[str, Any]],
    full_to_norm: dict[str, str],
) -> dict[str, dict[str, set[str]]]:
    passing: dict[str, dict[str, set[str]]] = {
        name: {} for name in CANDIDATES
    }
    for row in mapping_rows:
        store_id = row["store_chunk_id"]
        for candidate in row.get("candidates", []):
            runtime_id = candidate["runtime_chunk_id"]
            if runtime_id not in full_to_norm:
                raise ValueError(
                    f"mapping runtime ID absent from runtime map: {runtime_id}"
                )
            for name, predicate in CANDIDATES.items():
                if predicate(candidate):
                    passing[name].setdefault(store_id, set()).add(
                        full_to_norm[runtime_id]
                    )
    return passing


def per_case_metrics(
    row: dict[str, Any],
    selected_norm_ids: set[str],
    context_norm_ids: set[str],
    passing: dict[str, set[str]],
) -> dict[str, float]:
    truth = set(row.get("relevant_chunk_ids") or [])
    truth_runtime: set[str] = set()
    hits = 0
    reachable_truth = 0
    for store_id in truth:
        mapped = passing.get(store_id, set())
        truth_runtime.update(mapped)
        if mapped & selected_norm_ids:
            hits += 1
        if mapped & context_norm_ids:
            reachable_truth += 1

    c1 = hits / len(truth) if truth else 0.0
    precision_evi = (
        len(selected_norm_ids & truth_runtime) / len(selected_norm_ids)
        if selected_norm_ids else 0.0
    )
    recall_evi = (
        len(selected_norm_ids & truth_runtime) / len(truth_runtime)
        if truth_runtime else 0.0
    )
    precision_ctx = (
        len(context_norm_ids & truth_runtime) / len(context_norm_ids)
        if context_norm_ids else 0.0
    )
    recall_ctx = (
        len(context_norm_ids & truth_runtime) / len(truth_runtime)
        if truth_runtime else 0.0
    )
    slots = len(SLOT_RE.findall(row.get("answer", "")))
    oracle = min(slots, reachable_truth) / len(truth) if truth else 0.0
    return {
        "store_hit_recall_evi": c1,
        "precision_evi": precision_evi,
        "recall_evi": recall_evi,
        "precision_ctx": precision_ctx,
        "recall_ctx": recall_ctx,
        "mean_rel_runtime_size": float(len(truth_runtime)),
        "oracle_store_hit_achievable": oracle,
    }


def aggregate_metrics(
    baseline_rows: list[dict[str, Any]],
    runtime_by_norm: dict[str, dict[str, Any]],
    passing_by_candidate: dict[str, dict[str, set[str]]],
    paired_answers: dict[str, str] | None = None,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for name, passing in passing_by_candidate.items():
        rows_by_metric: dict[str, list[float]] = {
            key: [] for key in (
                "store_hit_recall_evi", "precision_evi", "recall_evi",
                "precision_ctx", "recall_ctx", "mean_rel_runtime_size",
                "oracle_store_hit_achievable",
            )
        }
        for row in baseline_rows:
            case_id = row["case_id"]
            ordered = row.get("context_chunk_ids_ordered") or []
            # Baseline ordered IDs are normalized IDs. The runtime map stores
            # the full chunk text alongside each normalized_id.
            context_norm = set(ordered)
            if paired_answers is None:
                evidence = (row.get("citation_metrics") or {}).get(
                    "evidence") or []
                selected_norm = {
                    e["chunk_id"] for e in evidence
                    if e.get("status") in SUPPORTED_STATUSES
                    and e.get("chunk_id")
                }
            else:
                answer = paired_answers[case_id]
                selected_norm: set[str] = set()
                for slot in SLOT_RE.finditer(answer):
                    index = int(slot.group(1)) - 1
                    if 0 <= index < len(ordered):
                        selected_norm.add(ordered[index])

            case = per_case_metrics(row, selected_norm, context_norm, passing)
            for key, value in case.items():
                rows_by_metric[key].append(value)
        output[name] = {
            key: round4(values) for key, values in rows_by_metric.items()
        }
    return output


def inspect_preflight() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    def record(name: str, actual: Any, expected: Any, ok: bool) -> None:
        checks.append({
            "name": name, "actual": actual, "expected": expected,
            "passed": bool(ok),
        })
        if not ok:
            failures.append(name)

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    record("worktree_head", head, EXPECTED_HEAD, head == EXPECTED_HEAD)

    phase2a = json.loads(PHASE2A_MANIFEST_PATH.read_text(encoding="utf-8"))
    phase2a_base = phase2a.get("baseline") or {}
    baseline_blob = read_git_blob(BASELINE_REF)
    baseline_blob_hash = sha256(baseline_blob)
    baseline_rows = jsonl_rows(baseline_blob)
    local_baseline_raw = BASELINE_PATH.read_bytes()
    local_baseline_lf = local_baseline_raw.replace(b"\r\n", b"\n")
    baseline_record_ok = (
        phase2a_base.get("sha256") == BASELINE_BLOB_SHA256
        and phase2a_base.get("rows") == 150
        and phase2a_base.get("cases_failed") == 0
    )
    record(
        "baseline_git_blob_sha256",
        baseline_blob_hash,
        BASELINE_BLOB_SHA256,
        baseline_blob_hash == BASELINE_BLOB_SHA256,
    )
    record("baseline_rows", len(baseline_rows), 150, len(baseline_rows) == 150)
    record(
        "baseline_cases_failed_from_phase2a_manifest",
        phase2a_base.get("cases_failed"), 0,
        phase2a_base.get("cases_failed") == 0,
    )
    local_lf_hash = sha256(local_baseline_lf)
    record(
        "baseline_checkout_lf_equivalence",
        local_lf_hash,
        BASELINE_BLOB_SHA256,
        local_lf_hash == BASELINE_BLOB_SHA256,
    )

    runtime_raw = RUNTIME_PATH.read_bytes()
    runtime_rows = jsonl_rows(runtime_raw)
    runtime_hash = sha256(runtime_raw)
    phase2a_runtime_hash = (phase2a.get("runtime_map") or {}).get("sha256")
    record(
        "runtime_map_rows", len(runtime_rows), 2947,
        len(runtime_rows) == 2947,
    )
    record(
        "runtime_map_worktree_sha256",
        runtime_hash, RUNTIME_RAW_SHA256,
        runtime_hash == RUNTIME_RAW_SHA256 == phase2a_runtime_hash,
    )

    mapping_raw = MAPPING_PATH.read_bytes()
    mapping_rows = jsonl_rows(mapping_raw)
    mapping_hash = sha256(mapping_raw)
    phase2a_mapping_hash = (phase2a.get("mapping") or {}).get("sha256")
    record(
        "mapping_rows", len(mapping_rows), 1006,
        len(mapping_rows) == 1006,
    )
    record(
        "mapping_worktree_sha256",
        mapping_hash, MAPPING_RAW_SHA256,
        mapping_hash == MAPPING_RAW_SHA256 == phase2a_mapping_hash,
    )

    dataset_blob = read_git_blob(
        f"{BASE_COMMIT}:evaluation/datasets/v2.1.jsonl"
    )
    dataset_blob_hash = sha256(dataset_blob)
    dataset_raw = DATASET_PATH.read_bytes()
    dataset_lf_hash = sha256(dataset_raw.replace(b"\r\n", b"\n"))
    dataset_raw_hash = sha256(dataset_raw)
    record(
        "dataset_git_blob_sha256", dataset_blob_hash,
        DATASET_LF_SHA256, dataset_blob_hash == DATASET_LF_SHA256,
    )
    record(
        "dataset_worktree_lf_sha256", dataset_lf_hash,
        DATASET_LF_SHA256, dataset_lf_hash == DATASET_LF_SHA256,
    )

    module_blob = read_git_blob(f"{M6A_COMMIT}:src/citation_selection.py")
    module_blob_hash = sha256(module_blob)
    module_raw = MODULE_PATH.read_bytes()
    module_lf_hash = sha256(module_raw.replace(b"\r\n", b"\n"))
    module_raw_hash = sha256(module_raw)
    record(
        "m6a_module_git_blob_sha256", module_blob_hash,
        MODULE_SHA256, module_blob_hash == MODULE_SHA256,
    )
    record(
        "m6a_module_worktree_lf_sha256", module_lf_hash,
        MODULE_SHA256, module_lf_hash == MODULE_SHA256,
    )

    runtime_by_full: dict[str, dict[str, Any]] = {}
    runtime_by_norm: dict[str, dict[str, Any]] = {}
    full_to_norm: dict[str, str] = {}
    normalized_ids: set[str] = set()
    for row in runtime_rows:
        full_id = row["chunk_id"]
        normalized_id = row["normalized_id"]
        runtime_by_full[full_id] = row
        runtime_by_norm[normalized_id] = row
        full_to_norm[full_id] = normalized_id
        normalized_ids.add(normalized_id)
    record(
        "runtime_map_normalized_id_uniqueness",
        len(runtime_by_norm), 2947,
        len(runtime_by_norm) == 2947,
    )

    ordered_count = 0
    resolved_count = 0
    missing_ids: list[str] = []
    malformed_answers = 0
    for row in baseline_rows:
        answer = row.get("answer")
        if not isinstance(answer, str):
            malformed_answers += 1
        for normalized_id in row.get("context_chunk_ids_ordered") or []:
            ordered_count += 1
            runtime = runtime_by_norm.get(normalized_id)
            if runtime and isinstance(runtime.get("text"), str):
                resolved_count += 1
            else:
                missing_ids.append(normalized_id)
    record(
        "ordered_context_ids_total", ordered_count, 3108,
        ordered_count == 3108,
    )
    record(
        "ordered_context_ids_resolvable_to_runtime_full_text",
        resolved_count, 3108,
        resolved_count == 3108 and not missing_ids,
    )
    record(
        "baseline_answers_are_strings", malformed_answers, 0,
        malformed_answers == 0,
    )

    try:
        passing = make_passing(mapping_rows, full_to_norm)
        control = aggregate_metrics(
            baseline_rows, runtime_by_norm, passing, paired_answers=None
        )
        control_a = control["A"]
        record(
            "control_C1_store_hit_recall_evi",
            control_a["store_hit_recall_evi"], 0.3767,
            control_a["store_hit_recall_evi"] == 0.3767,
        )
        record(
            "control_C3_precision_evi",
            control_a["precision_evi"], 0.3160,
            control_a["precision_evi"] == 0.3160,
        )
        for row in baseline_rows:
            evidence = (row.get("citation_metrics") or {}).get("evidence") or []
            for item in evidence:
                if (item.get("status") in SUPPORTED_STATUSES
                        and item.get("chunk_id")
                        and item["chunk_id"] not in normalized_ids):
                    failures.append("baseline_evidence_id_not_in_runtime_map")
                    checks.append({
                        "name": "baseline_evidence_id_not_in_runtime_map",
                        "actual": "unresolved supported evidence ID",
                        "expected": "all supported IDs resolve",
                        "passed": False,
                    })
                    break
    except Exception as exc:
        control = {}
        failures.append("control_metric_recalculation")
        checks.append({
            "name": "control_metric_recalculation",
            "actual": f"{type(exc).__name__}: {exc}",
            "expected": "Phase 2A-compatible C1/C3 calculation",
            "passed": False,
        })

    generation_prompt = sum(int(row.get("prompt_tokens") or 0)
                            for row in baseline_rows)
    generation_completion = sum(int(row.get("completion_tokens") or 0)
                                for row in baseline_rows)
    judge_miss_count = sum(
        1 for row in baseline_rows
        for point in ((row.get("answer_hit") or {}).get("point_results") or [])
        if point.get("verdict") == "miss"
    )
    refusal_count = sum(1 for row in baseline_rows if row.get("should_refuse"))

    return {
        "status": "INVALID" if failures else "PREFLIGHT_PASS",
        "head": head,
        "base_commit": BASE_COMMIT,
        "m6a_commit": M6A_COMMIT,
        "phase2a_commit": PHASE2A_COMMIT,
        "baseline_ref": BASELINE_REF,
        "baseline_raw_sha256_disclosure": sha256(local_baseline_raw),
        "baseline_raw_sha256_expected_disclosure":
            BASELINE_RAW_DISCLOSURE_SHA256,
        "dataset_raw_sha256_disclosure": dataset_raw_hash,
        "dataset_raw_sha256_expected_disclosure":
            DATASET_RAW_DISCLOSURE_SHA256,
        "m6a_module_raw_sha256_disclosure": module_raw_hash,
        "runtime_map_lf_sha256": sha256(
            runtime_raw.replace(b"\r\n", b"\n")),
        "mapping_lf_sha256": sha256(
            mapping_raw.replace(b"\r\n", b"\n")),
        "runtime_map_rows": len(runtime_rows),
        "mapping_rows": len(mapping_rows),
        "ordered_ids_total": ordered_count,
        "ordered_ids_resolved": resolved_count,
        "control_metrics": control,
        "baseline_generation_tokens": {
            "prompt": generation_prompt,
            "completion": generation_completion,
            "total": generation_prompt + generation_completion,
            "answer_rows": len(baseline_rows),
        },
        "baseline_mechanical_miss_points": judge_miss_count,
        "baseline_refusal_probes": refusal_count,
        "checks": checks,
        "failures": sorted(set(failures)),
        "full_sources_used": False,
    }


def write_json(path: Path, value: Any) -> bytes:
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n").encode("utf-8")
    path.write_bytes(data)
    return data


def write_invalid(snapshot: dict[str, Any], reason: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if any(OUT_DIR.iterdir()):
        raise RuntimeError(f"fail-closed: output directory is not empty: {OUT_DIR}")
    snapshot = {**snapshot, "status": "INVALID", "stop_reason": reason}
    write_json(OUT_DIR / "preflight.json", snapshot)
    decision = {
        "verdict": "INVALID",
        "reason": reason,
        "replay_executed": False,
        "preflight_sha256": sha256(
            (OUT_DIR / "preflight.json").read_bytes()),
    }
    write_json(OUT_DIR / "decision.json", decision)
    (OUT_DIR / "decision.md").write_text(
        "# M6a Phase 2B 决策\n\n"
        "- 裁决：**INVALID**\n"
        f"- 原因：{reason}\n"
        "- 重放：未执行（硬停条件触发）\n",
        encoding="utf-8",
        newline="\n",
    )


def preflight_stage() -> int:
    result = inspect_preflight()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["failures"]:
        write_invalid(result, "; ".join(result["failures"]))
        return 2
    return 0


def replay_stage() -> int:
    preflight = inspect_preflight()
    if preflight["failures"]:
        write_invalid(preflight, "; ".join(preflight["failures"]))
        print("[STOP] preflight failed; replay not run")
        return 2
    if OUT_DIR.exists():
        raise RuntimeError(f"fail-closed: output directory exists: {OUT_DIR}")

    baseline_rows = jsonl_rows(read_git_blob(BASELINE_REF))
    runtime_rows = jsonl_rows(RUNTIME_PATH.read_bytes())
    mapping_rows = jsonl_rows(MAPPING_PATH.read_bytes())
    runtime_by_norm = {row["normalized_id"]: row for row in runtime_rows}
    full_to_norm = {
        row["chunk_id"]: row["normalized_id"] for row in runtime_rows
    }
    passing = make_passing(mapping_rows, full_to_norm)

    from src.citation_selection import retarget_citations

    output_rows: list[dict[str, Any]] = []
    paired_answers: dict[str, str] = {}
    per_case_hashes: list[dict[str, str]] = []
    stats_totals = {
        "examined": 0, "retargeted": 0, "unchanged": 0, "invalid": 0,
        "slots_before": 0, "slots_after": 0, "groups": 0,
    }
    mismatches: list[dict[str, Any]] = []

    for row in baseline_rows:
        case_id = row["case_id"]
        answer = row["answer"]
        ordered_ids = row.get("context_chunk_ids_ordered") or []
        citation_ids = [f"S{i}" for i in range(1, len(ordered_ids) + 1)]
        chunk_texts = [runtime_by_norm[normalized_id]["text"]
                       for normalized_id in ordered_ids]
        paired_answer, stats_obj = retarget_citations(
            answer, citation_ids, chunk_texts
        )
        stats = asdict(stats_obj)
        baseline_bytes = answer.encode("utf-8")
        paired_bytes = paired_answer.encode("utf-8")
        baseline_stripped = SLOT_BYTES_RE.sub(b"", baseline_bytes)
        paired_stripped = SLOT_BYTES_RE.sub(b"", paired_bytes)
        slots_before = len(SLOT_BYTES_RE.findall(baseline_bytes))
        slots_after = len(SLOT_BYTES_RE.findall(paired_bytes))
        if (baseline_stripped != paired_stripped
                or slots_before != slots_after
                or stats.get("slots_before") != stats.get("slots_after")
                or stats.get("slots_after") != slots_after):
            mismatches.append({
                "case_id": case_id,
                "stripped_bytes_equal": baseline_stripped == paired_stripped,
                "baseline_slots": slots_before,
                "paired_slots": slots_after,
                "stats_slots_before": stats.get("slots_before"),
                "stats_slots_after": stats.get("slots_after"),
            })
            continue

        paired_answers[case_id] = paired_answer
        for key in stats_totals:
            stats_totals[key] += int(stats.get(key, 0) or 0)
        input_bundle = {
            "case_id": case_id,
            "answer": answer,
            "context_chunk_ids_ordered": ordered_ids,
        }
        output_bundle = {
            "case_id": case_id,
            "answer_paired": paired_answer,
            "stats": stats,
        }
        input_hash = sha256(canonical_bytes(input_bundle))
        output_hash = sha256(canonical_bytes(output_bundle))
        context_hash = sha256(canonical_bytes(ordered_ids))
        output_rows.append({
            "case_id": case_id,
            "answer_paired": paired_answer,
            "context_chunk_ids_ordered": ordered_ids,
            "stats": stats,
            "input_sha256": input_hash,
            "output_sha256": output_hash,
        })
        per_case_hashes.append({
            "case_id": case_id,
            "input_sha256": input_hash,
            "output_sha256": output_hash,
            "context_chunk_ids_ordered_sha256": context_hash,
        })

    if mismatches:
        snapshot = {
            **preflight,
            "status": "INVALID",
            "consistency_failures": mismatches,
        }
        write_invalid(
            snapshot,
            f"paired consistency failed in {len(mismatches)} case(s)",
        )
        print(f"[STOP] paired consistency failed: {len(mismatches)} case(s)")
        return 3

    if len(output_rows) != 150:
        snapshot = {**preflight, "status": "INVALID",
                    "paired_rows": len(output_rows)}
        write_invalid(snapshot, f"paired rows {len(output_rows)} != 150")
        return 3

    control_metrics = preflight["control_metrics"]
    paired_metrics = aggregate_metrics(
        baseline_rows, runtime_by_norm, passing, paired_answers=paired_answers
    )
    core = {
        "phase": "M6a-Phase2B-offline-paired-replay",
        "status": "replay_complete_pending_C2_G2prime",
        "execution_head": preflight["head"],
        "base_commit": BASE_COMMIT,
        "baseline": {
            "ref": BASELINE_REF,
            "git_blob_sha256": BASELINE_BLOB_SHA256,
            "raw_sha256_disclosure": preflight[
                "baseline_raw_sha256_disclosure"],
        },
        "preflight": preflight,
        "consistency": {
            "cases_total": len(output_rows),
            "cases_stripped_byte_identical": len(output_rows),
            "cases_slot_count_unchanged": len(output_rows),
            "mismatch_count": 0,
        },
        "replay_stats": stats_totals,
        "control_metrics": control_metrics,
        "paired_metrics": paired_metrics,
        "fabricated_status": "unverified_capture_not_fixed",
        "retrieved_not_in_context_status": "unverified_capture_not_fixed",
        "judge_al3": {"status": "pending", "calls": 0, "tokens": 0},
        "per_case_hashes": per_case_hashes,
        "full_sources_used": False,
        "new_answers_generated": 0,
    }

    OUT_DIR.mkdir(parents=True)
    outcomes_bytes = b"".join(canonical_bytes(row) + b"\n"
                               for row in output_rows)
    (OUT_DIR / "outcomes-paired.jsonl").write_bytes(outcomes_bytes)
    core_bytes = write_json(OUT_DIR / "replay-core.json", core)
    print(json.dumps({
        "status": core["status"],
        "paired_cases": len(output_rows),
        "consistency": core["consistency"],
        "replay_stats": stats_totals,
        "control_A": control_metrics["A"],
        "paired_A": paired_metrics["A"],
        "replay_core_sha256": sha256(core_bytes),
        "outcomes_paired_sha256": sha256(outcomes_bytes),
    }, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("preflight", "replay"))
    args = parser.parse_args()
    return preflight_stage() if args.stage == "preflight" else replay_stage()


if __name__ == "__main__":
    sys.exit(main())
