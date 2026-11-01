#!/usr/bin/env python3
"""Phase 1 finalizer: write manifest.json for the chunk-domain audit.

Read-only: hashes existing audit products + inputs + scripts, records the
git commit and run time, and self-hashes with the same convention used by
rebuild_runtime_map.py (sha256 of the canonical JSON body computed before
adding the manifest_self_sha256 field).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "results" / "answer-level" / "chunk-domain-audit-2026-11-01"
SCRIPTS_DIR = REPO / "scripts" / "audit"

PRODUCTS = [
    "runtime-map.jsonl",
    "runtime-map-manifest.json",
    "mapping.jsonl",
    "bridge-stats.json",
    "metrics.json",
    "baseline-audit.json",
    "report.md",
]
SCRIPTS = [
    "rebuild_runtime_map.py",
    "build_store_bridge.py",
    "recompute_metrics.py",
    "audit_baseline.py",
    "finalize_audit.py",
]
INPUTS = [
    "evaluation/datasets/v2.1.jsonl",
    "data/v2-corpus/chunks/chunk-manifest.json",
    "data/v2-corpus/chunks/chunks.jsonl",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    ).stdout.strip()


def main() -> None:
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    manifest: dict = {
        "phase": "Phase1-chunk-domain-audit-2026-11-01",
        "generated_at": now,
        "git_commit": git("rev-parse", "HEAD"),
        "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_status_porcelain_nonempty": bool(git("status", "--porcelain")),
        "stop_conditions": {
            "runtime_count_is_2947": True,
            "context_id_resolvability_ge_95pct": True,
            "store_to_runtime_coverage_ge_95pct": True,
            "no_src_modification_required": True,
            "no_llm_or_network_used": True,
            "any_triggered": False,
        },
        "key_numbers": {
            "runtime_chunks": 2947,
            "store_chunks": 1006,
            "mapping_coverage_any": 1.0,
            "old_manifest": {
                "m2": {"recall": 0.0322, "precision": 0.03},
                "arm1": {"recall": 0.0322, "precision": 0.0333},
                "arm2": {"recall": 0.0456, "precision": 0.04},
            },
            "bridged_t050_runtime": {
                "m2": {"rec_ctx": 0.2955, "prec_ctx": 0.071,
                       "rec_evi": 0.1928, "prec_evi": 0.294},
                "arm1": {"rec_ctx": 0.3489, "prec_ctx": 0.0792,
                         "rec_evi": 0.2267, "prec_evi": 0.3336},
                "arm2": {"rec_ctx": 0.4008, "prec_ctx": 0.0521,
                         "rec_evi": 0.251, "prec_evi": 0.3494},
            },
            "a_prime_ordered_id_resolvable_rate": 1.0,
            "a_prime_full_sources_snippet_only_cases": "150/150",
            "c1_c3_definable_in_runtime_domain": True,
        },
        "products": {},
        "scripts": {},
        "inputs": {},
        "read_only_guarantees": [
            "no changes to src/, evaluation/, tests/, config/, data/",
            "no LLM calls, no network, no judge/al3, no M2/M4c/M6a reruns",
            "no push, no commit, no docs/STATUS.md or CHANGELOG update",
            "truth read only in offline mapping/recompute scripts",
            "no ID-based chunk mapping; every mapping has source+span or "
            "text evidence",
        ],
    }

    for name in PRODUCTS:
        path = OUT_DIR / name
        if path.exists():
            manifest["products"][name] = sha256_file(path)

    for name in SCRIPTS:
        path = SCRIPTS_DIR / name
        if path.exists():
            manifest["scripts"][name] = sha256_file(path)

    for rel in INPUTS:
        path = REPO / rel
        if path.exists():
            manifest["inputs"][rel] = sha256_file(path)

    # extracted a' baseline (from branch eval/m6a-paired-2026-11-01 @ de8181f)
    baseline_tmp = OUT_DIR / "_tmp-baseline-outcomes.jsonl"
    if baseline_tmp.exists():
        manifest["inputs"][
            "_tmp-baseline-outcomes.jsonl (extracted via "
            "git show de8181f:results/answer-level/m6a-paired-2026-11-01/"
            "baseline-outcomes.jsonl"
        ] = sha256_file(baseline_tmp)

    # self-hash: canonical body WITHOUT the self field (same convention as
    # rebuild_runtime_map.py:301-302)
    body = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    manifest["manifest_self_sha256"] = sha256_text(body)

    out_path = OUT_DIR / "manifest.json"
    out_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"wrote {out_path}")
    print(f"manifest_self_sha256={manifest['manifest_self_sha256']}")


if __name__ == "__main__":
    main()
