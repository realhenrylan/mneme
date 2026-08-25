"""稳定 split 重建产物完整性校验（fail-closed，任一失败 → 非零退出）。

校验：
1. SHA 链：overlay ↔ per-split ground-truth-map ↔ dataset 一致；
   lock 的 dataset_sha256 / split_fingerprint 与当前一致；
2. 标注完整性：
   - dev+holdout overlay 的 confirmed 合计 = 25，全部 27 条人工决定
     有去向（25 confirmed 进 pack；2 reject 保留于 canonical pack——
     en-004/mixed-005 补标后为 exact 匹配，不再产生 overlap 行）；
   - source-only 4 条在 dataset 中 relevant_chunks 为空且 answerable，
     dataset 中此类 case 恰好等于 source-only 集合（无静默缺失）；
   - overlay entries 的稳定键全部被 per-split GT map 消费
     （apply_reviewed_truth_overlay 无未消费/未知/重复）；
   - 每个 split 的 enforce_truth_gate 通过（无缺真值且无显式决定的 case）。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from evaluation.compare import (
    apply_reviewed_truth_overlay,
    enforce_truth_gate,
    load_ground_truth_map,
)
from evaluation.schema import load_dataset

OUT = Path(__file__).resolve().parent
DATASET = ROOT / "evaluation/datasets/v1.jsonl"
CANONICAL_PACK = ROOT / "results/graph-gate/review-pack-chunk-annotated"
LOCK = OUT / "lock-production-stable.json"
SPLIT_MANIFEST = OUT / "split-manifest.json"

failures: list[str] = []
notes: list[str] = []


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    ds_hash = sha256_file(DATASET)
    cases = load_dataset(DATASET)
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    split_manifest = json.loads(SPLIT_MANIFEST.read_text(encoding="utf-8"))

    # ── 1. 锁定配置 / split manifest ─────────────────────────────────
    if lock["dataset_sha256"] != ds_hash:
        failures.append(f"lock.dataset_sha256={lock['dataset_sha256']} != dataset {ds_hash}")
    if lock["split_fingerprint"] != split_manifest["split_fingerprint"]:
        failures.append(
            f"lock.split_fingerprint={lock['split_fingerprint']} != "
            f"split-manifest {split_manifest['split_fingerprint']}")
    notes.append(
        f"lock split_fingerprint={lock['split_fingerprint']} "
        f"(dev={split_manifest['dev_count']}, holdout={split_manifest['holdout_count']})")

    # ── 2. canonical 决定来源 ────────────────────────────────────────
    can_overlap = [
        json.loads(l) for l in
        (CANONICAL_PACK / "review-overlap.jsonl").read_text(
            encoding="utf-8").splitlines() if l.strip()
    ]
    can_missing = [
        json.loads(l) for l in
        (CANONICAL_PACK / "missing-chunk-truth.jsonl").read_text(
            encoding="utf-8").splitlines() if l.strip()
    ]
    from collections import Counter
    can_decisions = Counter(r["review_decision"] for r in can_overlap)
    if can_decisions != {"confirmed": 25, "reject": 2}:
        failures.append(f"canonical pack decisions {dict(can_decisions)} != 25/2")
    if any(r["relevance_level"] != "source" for r in can_missing):
        failures.append("canonical pack missing rows not all source-level")
    notes.append(
        f"canonical decisions: {dict(can_decisions)}, "
        f"source-only={len(can_missing)}")

    # ── 3. per-split overlay + GT map 消费性 ──────────────────────────
    total_confirmed = 0
    for name in ("dev", "holdout"):
        ov = json.loads(
            (OUT / f"reviewed-production-{name}/reviewed-truth-overlay.json")
            .read_text(encoding="utf-8"))
        gt_path = OUT / f"ground-truth-map-{name}.json"
        gt_hash = sha256_file(gt_path)
        if ov["dataset_sha256"] != ds_hash:
            failures.append(
                f"{name}: overlay.dataset_sha256={ov['dataset_sha256']} != dataset")
        if ov["ground_truth_sha256"] != gt_hash:
            failures.append(
                f"{name}: overlay.ground_truth_sha256 != gt-map {gt_hash}")
        c = ov["counts"]
        if c["overlap_decisions"] != c["confirmed"] or c["rejected"] != 0:
            failures.append(f"{name}: unexpected overlay counts {c}")
        if c["case_relevance_decisions"] != 4 or c["source_only"] != 4:
            failures.append(f"{name}: expected 4 source-only, got {c}")
        total_confirmed += c["confirmed"]

        # 稳定键消费性：overlay entries 必须全部被 per-split GT map 消费
        entries = load_ground_truth_map(gt_path)
        try:
            updated, source_only = apply_reviewed_truth_overlay(entries, ov)
        except ValueError as exc:
            failures.append(f"{name}: overlay application failed: {exc}")
            continue
        notes.append(f"{name}: overlay entries consumed by GT map "
                     f"({c['confirmed']} confirmed + {c['source_only']} source-only)")

        # 真值门禁：无可靠 chunk 真值且无显式决定 → 失败
        split_ids = set(split_manifest[f"{name}_case_ids"])
        active = [c for c in cases if c.id in split_ids]
        has_truth = {c.id: False for c in active}
        for e in updated:
            if (e.match_method == "exact"
                    or (e.match_method in ("overlap", "parent")
                        and e.reviewer_status == "confirmed")):
                has_truth[e.case_id] = True
        gate_errors = enforce_truth_gate(active, has_truth, ov, source_only)
        if gate_errors:
            failures.append(f"{name}: truth gate FAILED: {gate_errors}")

    if total_confirmed != 25:
        failures.append(f"confirmed total {total_confirmed} != 25")

    # ── 4. dataset 层：缺失 chunk 真值的 answerable case = source-only ──
    no_chunk_truth = sorted(
        c.id for c in cases if not c.should_refuse and not c.relevant_chunks)
    source_only_ids = sorted(set(
        c["case_id"]
        for name in ("dev", "holdout")
        for c in json.loads(
            (OUT / f"reviewed-production-{name}/reviewed-truth-overlay.json")
            .read_text(encoding="utf-8"))["case_relevance_levels"]
        if c["relevance_level"] == "source"
    ))
    if no_chunk_truth != source_only_ids:
        failures.append(
            f"dataset missing-chunk-truth {no_chunk_truth} != "
            f"source-only {source_only_ids}")
    else:
        notes.append(f"source-only cases: {source_only_ids}")

    # ── 5. reject 决定去向（保留于 canonical 历史记录） ────────────────
    rejects = sorted(
        r["case_id"] for r in can_overlap if r["review_decision"] == "reject")
    for cid in rejects:
        case = next(c for c in cases if c.id == cid)
        has_exact = any(
            e.case_id == cid and e.match_method == "exact"
            for name in ("dev", "holdout")
            for e in load_ground_truth_map(OUT / f"ground-truth-map-{name}.json")
        )
        if not has_exact:
            failures.append(
                f"reject case {cid}: no exact truth in new GT maps "
                f"(re-annotation lost?)")
    notes.append(
        f"reject decisions preserved in canonical pack (no overlap rows "
        f"after re-annotation): {rejects}")

    # ── 报告 ─────────────────────────────────────────────────────────
    print("=== TRUTH INTEGRITY VERIFICATION ===")
    for n in notes:
        print(f"  ✓ {n}")
    if failures:
        print("\n  ✗ FAILURES:")
        for f_ in failures:
            print(f"    - {f_}")
        print("\nRESULT: FAIL")
        sys.exit(1)
    print("\nRESULT: PASS — stable-split rebuild artifacts verified")


if __name__ == "__main__":
    main()
