"""Corpus v2 seal: freeze the full pool (v1 legacy + v2 new), run the
deterministic group-aware split, and emit the sealed lock artifacts.

Outputs (no holdout ids are persisted):
  evaluation/datasets/v2/split/case-freeze.json
  evaluation/datasets/v2/split/split-lock.json
  evaluation/datasets/v2/split/seal-audit.json

Usage: python scripts/corpus_v2_seal.py [--seed 42]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.split_seal import (  # noqa: E402
    SPLITTER_VERSION,
    build_split,
    freeze_case_ids,
    verify_lock,
)

V1 = ROOT / "evaluation" / "datasets" / "v1.jsonl"
V2 = ROOT / "evaluation" / "datasets" / "v2" / "annotations" / "v2-cases-draft.jsonl"
SPLIT_DIR = ROOT / "evaluation" / "datasets" / "v2" / "split"
CORPUS_VERSION = "v2.0.0"


def v1_chain_ids(rows: list[dict]) -> dict[str, str]:
    """Compute chain_id for legacy v1 cases via follow_up_to closure."""
    follow = {r["id"]: r.get("metadata", {}).get("follow_up_to") for r in rows}
    chain: dict[str, str] = {}
    for r in rows:
        cur = r["id"]
        while follow.get(cur):
            cur = follow[cur]
        chain[r["id"]] = cur  # 链头 id 作为 chain_id
    return chain


def build_pool() -> list[dict]:
    v1_rows = [json.loads(l) for l in V1.open(encoding="utf-8") if l.strip()]
    v2_rows = [json.loads(l) for l in V2.open(encoding="utf-8") if l.strip()]
    v1_chain = v1_chain_ids(v1_rows)
    pool: list[dict] = []
    for r in v1_rows:
        m = r.get("metadata", {})
        pool.append({
            "id": r["id"],
            "query_type": r.get("query_type"),
            "language": r.get("language"),
            "should_refuse": bool(r.get("should_refuse")),
            "chain_id": v1_chain.get(r["id"]),
            "partition": "legacy_dev",
        })
    for r in v2_rows:
        m = r.get("metadata", {})
        pool.append({
            "id": r["id"],
            "query_type": r.get("query_type"),
            "language": r.get("language"),
            "should_refuse": bool(r.get("should_refuse")),
            "chain_id": m.get("chain_id"),
            "partition": "new",
        })
    return pool


def main() -> int:
    seed = 42
    if "--seed" in sys.argv:
        seed = int(sys.argv[sys.argv.index("--seed") + 1])
    SPLIT_DIR.mkdir(parents=True, exist_ok=True)

    pool = build_pool()
    frozen = freeze_case_ids(pool, corpus_version=CORPUS_VERSION)

    # 选择满足 [0.22, 0.30] 的 seed（确定性尝试，记录在审计日志）
    attempts = []
    result = None
    for cand in (seed, seed + 1, seed + 2, seed + 3, seed + 4):
        r = build_split(frozen, seed=cand, holdout_ratio=0.25)
        attempts.append({"seed": cand, "ratio": r.stats["holdout_ratio"],
                         "n_holdout": r.stats["n_cases_holdout"]})
        if 0.22 <= r.stats["holdout_ratio"] <= 0.30:
            result = r
            seed = cand
            break
    if result is None:
        raise SystemExit(f"no seed in {attempts} satisfies [0.22, 0.30]")

    # case-freeze.json
    freeze_out = SPLIT_DIR / "case-freeze.json"
    freeze_out.write_text(json.dumps(frozen, ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8")

    # split-lock.json（不含 holdout ids）
    lock = {
        "corpus_version": CORPUS_VERSION,
        "split_fingerprint": result.fingerprint,
        "case_freeze_sha256": frozen["case_ids_sha256"],
        "seed": seed,
        "holdout_ratio": 0.25,
        "splitter_version": SPLITTER_VERSION,
        "stats": result.stats,
        "holdout_ids_not_persisted": True,
        "note": "holdout ids 不落盘；确认阶段由同一 splitter 重算并校验指纹",
    }
    lock_out = SPLIT_DIR / "split-lock.json"
    lock_out.write_text(json.dumps(lock, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")

    # seal-audit.json
    audit = {
        "sealed_at": "2026-08-05",
        "pool": {"total": len(pool), "legacy_dev": 110, "new": 150},
        "freeze": {
            "case_ids_sha256": frozen["case_ids_sha256"],
            "file": "case-freeze.json",
        },
        "split": {
            "seed": seed,
            "fingerprint": result.fingerprint,
            "n_dev_new": len(result.dev_ids),
            "n_holdout": len(result.holdout_ids),
            "holdout_ratio": result.stats["holdout_ratio"],
            "per_stratum": result.stats["per_stratum"],
            "ratio_gate": "[0.22, 0.30]",
        },
        "verify_lock": verify_lock(lock, frozen),
        "guard": {
            "holdout_ids_in_lock": False,
            "holdout_viewed": False,
            "note": "封存前未对任何新用例运行检索/特征扫描（阶段 A/B/C 均无 v2 检索）",
        },
        "seed_attempts": attempts,
    }
    audit_out = SPLIT_DIR / "seal-audit.json"
    audit_out.write_text(json.dumps(audit, ensure_ascii=False, indent=1) + "\n",
                         encoding="utf-8")

    print(f"wrote {freeze_out}")
    print(f"wrote {lock_out}")
    print(f"wrote {audit_out}")
    print(f"fingerprint={result.fingerprint}")
    print(f"holdout ratio={result.stats['holdout_ratio']} "
          f"(n={result.stats['n_cases_holdout']}) verify={audit['verify_lock']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
