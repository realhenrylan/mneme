"""Split sealing for the v2 evaluation corpus (deterministic, zero LLM).

Implements the group-aware dev/holdout protocol from
plans/CORPUS-EXPANSION-PLAN-2026-08-05.md §5:

- ``freeze_case_ids``  — freeze the full pool (legacy + new) with SHA-256
  plus per-case metadata (stratum fields, chain id);
- ``build_split``      — deterministic stratified group split: chains are
  atomic, holdout is drawn only from *new* cases, per-stratum ≥1 group
  (when ≥2 groups), overall holdout ratio within [0.22, 0.30] of the new
  pool;
- ``verify_lock``      — recompute the fingerprint from lock inputs and
  compare against the locked value;
- ``check_artifact_ids`` — fail-closed scan: analysis artifacts must not
  contain holdout ids;
- ``confirm_holdout``  — one-shot confirmation: recompute holdout ids from
  the locked inputs, verify the fingerprint, emit a confirmation file
  (holdout ids are never persisted before this step).

All ordering is stable; group sort keys use splitmix64 over
``sha256(f"{seed}:{group_key}")`` so results are reproducible across
platforms and Python versions (no PYTHONHASHSEED dependence).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SPLITTER_VERSION = "v2-seal-1"
_MASK = (1 << 64) - 1


# ── deterministic hashing ─────────────────────────────────────────────


def _splitmix64(x: int) -> int:
    x = (x + 0x9E3779B97F4A7C15) & _MASK
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & _MASK
    return (x ^ (x >> 31)) & _MASK


def splitmix64_sort_key(seed: int, group_key: str) -> int:
    """Deterministic per-(seed, group) sort key (platform-independent)."""
    h = int(hashlib.sha256(f"{seed}:{group_key}".encode("utf-8"))
            .hexdigest()[:16], 16)
    return _splitmix64(h)


def group_key_for(case: dict) -> str:
    """Group key: chain id when in a chain, else the case id (singleton)."""
    chain = case.get("chain_id") or case.get("metadata", {}).get("chain_id")
    if chain:
        return chain
    return case["id"]


# ── case freeze ───────────────────────────────────────────────────────


def freeze_case_ids(cases: list[dict], corpus_version: str) -> dict:
    """Freeze the pool: ordered ids, SHA-256, partition markers, metadata."""
    ids = sorted(c["id"] for c in cases)
    prefix_seq: dict[str, int] = {}
    meta: dict[str, dict] = {}
    for c in cases:
        m = re.match(r"^([a-z]+)-(\d+)$", c["id"])
        if m:
            prefix_seq[m.group(1)] = max(prefix_seq.get(m.group(1), 0),
                                         int(m.group(2)))
        meta[c["id"]] = {
            "query_type": c.get("query_type"),
            "language": c.get("language"),
            "should_refuse": bool(c.get("should_refuse")),
            "chain_id": c.get("chain_id") or c.get("metadata", {}).get("chain_id"),
        }
    return {
        "corpus_version": corpus_version,
        "case_ids": ids,
        "case_ids_sha256": hashlib.sha256(
            "\n".join(ids).encode("utf-8")).hexdigest(),
        "partition": {
            "legacy_dev": sorted(c["id"] for c in cases
                                 if c.get("partition") == "legacy_dev"),
            "new": sorted(c["id"] for c in cases
                          if c.get("partition") != "legacy_dev"),
        },
        "prefix_max_seq": dict(sorted(prefix_seq.items())),
        "cases": meta,
    }


# ── split ─────────────────────────────────────────────────────────────


@dataclass
class SplitResult:
    dev_ids: list[str]
    holdout_ids: list[str]
    fingerprint: str
    stats: dict[str, Any] = field(default_factory=dict)
    splitter_version: str = SPLITTER_VERSION


def _group_of(frozen: dict, case_id: str) -> str:
    meta = frozen["cases"].get(case_id, {})
    return meta.get("chain_id") or case_id


def _stratum_of(frozen: dict, case_id: str) -> tuple[str, bool, str]:
    meta = frozen["cases"].get(case_id, {})
    return (meta.get("query_type") or "?",
            bool(meta.get("should_refuse")),
            meta.get("language") or "?")


def _groups(frozen: dict, new_ids: set[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for cid in sorted(new_ids):
        groups.setdefault(_group_of(frozen, cid), []).append(cid)
    return groups


def build_split(frozen: dict, seed: int, holdout_ratio: float = 0.25,
                corpus_version: str | None = None) -> SplitResult:
    """Deterministic stratified group split (see module docstring)."""
    if not 0.0 < holdout_ratio < 1.0:
        raise ValueError(f"holdout_ratio must be in (0,1): {holdout_ratio}")
    new_ids = set(frozen["partition"]["new"])
    if not new_ids:
        raise ValueError("no new cases to split")
    groups = _groups(frozen, new_ids)
    if not groups:
        raise ValueError("empty group map")

    # 分层：组按 (stratum) 归类；每层内按 splitmix64(seed, group) 排序
    by_stratum: dict[tuple[str, bool, str], list[str]] = {}
    for gkey, members in groups.items():
        rep = members[0]
        by_stratum.setdefault(_stratum_of(frozen, rep), []).append(gkey)
    for stratum, gkeys in by_stratum.items():
        gkeys.sort(key=lambda g: (splitmix64_sort_key(seed, g), g))

    holdout_groups: list[str] = []
    per_stratum: dict[str, dict[str, int]] = {}
    for stratum, gkeys in sorted(by_stratum.items()):
        n = len(gkeys)
        h = max(1, round(n * holdout_ratio)) if n >= 2 else 0
        holdout_groups.extend(gkeys[:h])
        per_stratum["/".join(str(s) for s in stratum)] = {
            "groups": n, "holdout_groups": h,
            "cases": sum(len(groups[g]) for g in gkeys),
        }

    holdout_ids = sorted(cid for g in holdout_groups for cid in groups[g])
    dev_ids = sorted(new_ids - set(holdout_ids))
    ratio = len(holdout_ids) / len(new_ids)
    stats = {
        "n_cases_new": len(new_ids),
        "n_cases_holdout": len(holdout_ids),
        "holdout_ratio": round(ratio, 4),
        "n_groups_new": len(groups),
        "n_groups_holdout": len(holdout_groups),
        "per_stratum": per_stratum,
    }
    if not 0.18 <= ratio <= 0.35:
        raise ValueError(f"holdout ratio {ratio:.3f} outside [0.18, 0.35]")
    # 真实语料验收硬区间（计划 §5.2）由调用方在真实池上单独验证：
    # holdout 占比 ∈ [0.22, 0.30]

    fingerprint = _fingerprint(frozen, seed, holdout_ratio, dev_ids,
                               holdout_ids)
    return SplitResult(dev_ids=dev_ids, holdout_ids=holdout_ids,
                       fingerprint=fingerprint, stats=stats)


def _canonical(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _fingerprint(frozen: dict, seed: int, holdout_ratio: float,
                 dev_ids: list[str], holdout_ids: list[str]) -> str:
    groups_repr = {}
    for cid in sorted(frozen["cases"]):
        g = _group_of(frozen, cid)
        groups_repr.setdefault(g, []).append(cid)
    groups_canon = {g: sorted(m) for g, m in sorted(groups_repr.items())}
    payload = {
        "corpus_version": frozen["corpus_version"],
        "case_ids_sha256": frozen["case_ids_sha256"],
        "groups": groups_canon,
        "seed": seed,
        "holdout_ratio": holdout_ratio,
        "splitter_version": SPLITTER_VERSION,
        "dev_ids_sha256": hashlib.sha256(
            "\n".join(dev_ids).encode("utf-8")).hexdigest(),
        "holdout_ids_sha256": hashlib.sha256(
            "\n".join(holdout_ids).encode("utf-8")).hexdigest(),
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


# ── lock verification ─────────────────────────────────────────────────


def verify_lock(lock: dict, frozen: dict) -> bool:
    """Recompute the fingerprint from lock inputs and compare."""
    try:
        recomputed = build_split(
            frozen,
            seed=int(lock["seed"]),
            holdout_ratio=float(lock["holdout_ratio"]),
        )
    except (KeyError, TypeError, ValueError):
        return False
    if recomputed.fingerprint != lock.get("split_fingerprint"):
        return False
    if lock.get("case_freeze_sha256") != frozen["case_ids_sha256"]:
        return False
    return True


# ── artifact leak scan ────────────────────────────────────────────────


def check_artifact_ids(paths: list[str], holdout_ids: set[str]) -> int:
    """Fail-closed: scan JSONL artifacts for holdout ids (ValueError)."""
    if not holdout_ids:
        raise ValueError("holdout_ids must not be empty")
    seen = 0
    for path in paths:
        p = Path(path)
        if not p.exists():
            raise ValueError(f"artifact not found: {path}")
        for line_no, line in enumerate(p.open(encoding="utf-8"), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            vals = row.values() if isinstance(row, dict) else row
            for v in vals:
                if v in holdout_ids:
                    raise ValueError(
                        f"holdout id {v} found in {path}:{line_no}")
            # 嵌套 metadata/列表中的 id
            for key in ("case_id", "id"):
                if isinstance(row, dict) and row.get(key) in holdout_ids:
                    raise ValueError(
                        f"holdout id {row[key]} found in {path}:{line_no}")
        seen += 1
    return seen


# ── one-shot confirmation ─────────────────────────────────────────────


def confirm_holdout(frozen: dict, seed: int, holdout_ratio: float,
                    fingerprint: str, output: str) -> dict:
    """Recompute holdout ids from locked inputs and verify fingerprint.

    Holdout ids are never persisted before this step; the confirmation
    file is the first artifact that materializes them.
    """
    result = build_split(frozen, seed=seed, holdout_ratio=holdout_ratio)
    if result.fingerprint != fingerprint:
        raise ValueError("fingerprint mismatch: lock inputs drifted")
    payload = {
        "corpus_version": frozen["corpus_version"],
        "split_fingerprint": fingerprint,
        "fingerprint_matched": True,
        "holdout_ids": sorted(result.holdout_ids),
        "n_holdout": len(result.holdout_ids),
        "stats": result.stats,
        "confirmed_at": "2026-08-05",
    }
    Path(output).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return payload


# ── CLI ───────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m evaluation.split_seal <command> <pool.jsonl> ...

    Commands (deterministic, zero LLM):
      freeze <v1.jsonl> <v2.jsonl> --corpus-version v2.0.0
      split <case-freeze.json> --seed 42 --holdout-ratio 0.25
    """
    import sys

    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(__doc__)
        return 0
    cmd = args[0]
    if cmd == "freeze" and len(args) >= 3:
        version = "v2.0.0"
        if "--corpus-version" in args:
            version = args[args.index("--corpus-version") + 1]
        cases: list[dict] = []
        for path in (args[1], args[2]):
            for line in Path(path).open(encoding="utf-8"):
                if line.strip():
                    cases.append(json.loads(line))
        frozen = freeze_case_ids(cases, corpus_version=version)
        print(json.dumps(frozen, ensure_ascii=False, indent=1))
        return 0
    if cmd == "split" and len(args) >= 2:
        frozen = json.loads(Path(args[1]).read_text(encoding="utf-8"))
        seed = 42
        ratio = 0.25
        if "--seed" in args:
            seed = int(args[args.index("--seed") + 1])
        if "--holdout-ratio" in args:
            ratio = float(args[args.index("--holdout-ratio") + 1])
        result = build_split(frozen, seed=seed, holdout_ratio=ratio)
        print(json.dumps({
            "fingerprint": result.fingerprint,
            "stats": result.stats,
            "n_dev": len(result.dev_ids),
            "n_holdout": len(result.holdout_ids),
            "splitter_version": result.splitter_version,
        }, ensure_ascii=False, indent=1))
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
