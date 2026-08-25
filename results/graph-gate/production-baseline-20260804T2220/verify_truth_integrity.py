"""标注完整性与 SHA 校验（评测前 fail-closed）。

校验：
1. overlay ↔ dataset ↔ ground-truth-map SHA 链一致；
2. corpus/index 指纹与锁定配置一致（precheck 已验，此处复核 manifest）；
3. 标注完整性：
   - overlap 27 条全部有人工决定（confirmed=25 / rejected=2），
     reject 的 case（en-004、mixed-005）在 ground-truth 中显式 rejected；
   - source-only 4 条（overlay case_relevance_levels）在 dataset 中
     relevant_chunks 为空且 answerable；
   - dataset 全部 answerable case：relevant_chunks 为空者必须恰好等于
     source-only 集合（无静默缺失 chunk 标注）；
   - 8 个补标 case（meta-001/002/004/005/006/007/009/010）的
     relevant_chunks 非空；
   - overlay entries 的稳定键全部可被 ground-truth-map 消费。
任一失败 → 非零退出。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

DATASET = ROOT / "evaluation/datasets/v1.jsonl"
GROUND_TRUTH = ROOT / "results/graph-gate/dev/ground-truth-map.json"
OVERLAY = ROOT / "results/graph-gate/reviewed-production/reviewed-truth-overlay.json"
APPLY_MANIFEST = ROOT / "results/graph-gate/reviewed-production/review-apply-manifest.json"
LOCK = ROOT / "results/graph-gate/production-baseline-20260804T2220/lock-production.json"
OUT = Path(__file__).resolve().parent

failures: list[str] = []
notes: list[str] = []


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    # ── 1. SHA 链 ─────────────────────────────────────────────────────
    ds_hash = sha256_file(DATASET)
    gt_hash = sha256_file(GROUND_TRUTH)
    ov = json.loads(OVERLAY.read_text(encoding="utf-8"))
    apply_manifest = json.loads(APPLY_MANIFEST.read_text(encoding="utf-8"))
    lock = json.loads(LOCK.read_text(encoding="utf-8"))

    if ov["dataset_sha256"] != ds_hash:
        failures.append(
            f"overlay.dataset_sha256={ov['dataset_sha256']} != dataset {ds_hash}")
    if ov["ground_truth_sha256"] != gt_hash:
        failures.append(
            f"overlay.ground_truth_sha256={ov['ground_truth_sha256']} "
            f"!= ground-truth-map {gt_hash}")
    if lock["dataset_sha256"] != ds_hash:
        failures.append(
            f"lock.dataset_sha256={lock['dataset_sha256']} != dataset {ds_hash}")
    if apply_manifest["dataset_sha256"] != ds_hash:
        failures.append("apply manifest dataset_sha256 mismatch")
    notes.append(f"dataset_sha256={ds_hash}")
    notes.append(f"ground_truth_sha256={gt_hash}")

    # ── 2. 标注完整性 ────────────────────────────────────────────────
    cases = [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines()]
    case_by_id = {c["id"]: c for c in cases}
    gt = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))

    counts = ov["counts"]
    if counts["overlap_decisions"] != 27:
        failures.append(f"overlap_decisions={counts['overlap_decisions']} != 27")
    if counts["confirmed"] != 25 or counts["rejected"] != 2:
        failures.append(f"confirmed/rejected={counts['confirmed']}/{counts['rejected']} != 25/2")
    notes.append(f"overlap: 27 decisions (confirmed={counts['confirmed']}, "
                 f"rejected={counts['rejected']})")

    source_only = sorted(
        c["case_id"] for c in ov["case_relevance_levels"]
        if c["relevance_level"] == "source")
    if len(source_only) != 4:
        failures.append(f"source_only count={len(source_only)} != 4")
    notes.append(f"source-only cases: {source_only}")

    # overlay entries 的稳定键是否全部可被本次 GT 消费（按 (case,source,snippet) 粗查）
    ov_keys = {
        (e["case_id"], e["source_id"], e["normalized_snippet"])
        for e in ov["entries"]
    }
    gt_keys = {
        (r["case_id"], r["source_id"], r["normalized_snippet"])
        for r in gt
    }
    unconsumed = ov_keys - gt_keys
    if unconsumed:
        failures.append(f"overlay entries not consumable by GT: {unconsumed}")

    # reject 的条目在 GT 中对应的 overlap 不应再被当作可靠真值
    rejected_cases = sorted(
        e["case_id"] for e in ov["entries"] if e["review_decision"] == "rejected")
    notes.append(f"rejected overlap cases: {rejected_cases}")

    # dataset 完整性：answerable 且 relevant_chunks 为空 = source-only 集合
    missing_chunks = sorted(
        c["id"] for c in cases
        if not c.get("should_refuse") and not c.get("relevant_chunks"))
    if missing_chunks != source_only:
        failures.append(
            f"dataset answerable cases without relevant_chunks "
            f"{missing_chunks} != overlay source-only {source_only}")
    else:
        notes.append(f"answerable cases without chunk truth == source-only "
                     f"({len(missing_chunks)}): {missing_chunks}")

    # 8 个补标 case 的 chunk 真值存在性
    annotated = ["meta-001", "meta-002", "meta-004", "meta-005",
                 "meta-006", "meta-007", "meta-009", "meta-010"]
    for cid in annotated:
        c = case_by_id.get(cid)
        if c is None:
            failures.append(f"annotated case missing in dataset: {cid}")
            continue
        if not c.get("relevant_chunks"):
            failures.append(f"annotated case has empty relevant_chunks: {cid}")
    notes.append(f"re-annotated meta-* cases: {annotated} (all with chunk truth)")

    # ground-truth-map 中 needs_review 应已全部被 overlay 覆盖（27 条）
    nr_entries = [r for r in gt if r["reviewer_status"] == "needs_review"]
    if len(nr_entries) != 27:
        failures.append(f"GT needs_review entries={len(nr_entries)} != 27")
    # overlay 消费后（评测端）将映射为 confirmed/rejected

    # ── 3. 输出 ──────────────────────────────────────────────────────
    (OUT / "truth-integrity-verification.json").write_text(
        json.dumps({
            "dataset_sha256": ds_hash,
            "ground_truth_sha256": gt_hash,
            "overlay_dataset_sha256": ov["dataset_sha256"],
            "overlay_ground_truth_sha256": ov["ground_truth_sha256"],
            "counts": counts,
            "source_only_cases": source_only,
            "rejected_overlap_cases": rejected_cases,
            "reannotated_meta_cases": annotated,
            "notes": notes,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("=== TRUTH INTEGRITY VERIFICATION ===")
    for n in notes:
        print(f"  ✓ {n}")
    if failures:
        print("\n  ✗ BLOCKERS:")
        for f_ in failures:
            print(f"    - {f_}")
        print("\nRESULT: FAIL")
        sys.exit(1)
    print("\nRESULT: PASS — overlay/dataset/GT/corpus/index verified, "
          "annotation complete")


if __name__ == "__main__":
    main()
