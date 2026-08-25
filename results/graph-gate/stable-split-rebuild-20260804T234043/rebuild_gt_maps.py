"""稳定 split 重建：split manifest + per-split GT map + review pack。

背景：group_aware_split 修复（chain root 稳定排序 + 输出稳定排序）后，
split 与 PYTHONHASHSEED 无关，同一 --seed=42 跨进程得到同一结果。
本脚本用修复后的稳定 split 重建：

1. split-manifest.json：split 指纹（canonical SHA-256）+ dev/holdout
   case 列表（供 locked-config 锁定与跨进程复现）；
2. per-split ground-truth-map（从缓存索引只读重建，不改索引）；
3. per-split review pack（导出未填决定，供迁移脚本回填人工结论）。

不调用 LLM/API；不重跑评测；不改写任何历史 results。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from evaluation.compare import (
    build_ground_truth_map,
    compute_split_fingerprint,
    group_aware_split,
)
from evaluation.review_pack import build_review_pack
from evaluation.schema import load_dataset
from src.rag import prepare_index

OUT = Path(__file__).resolve().parent
DATASET = ROOT / "evaluation/datasets/v1.jsonl"
CORPUS = ROOT / "test_texts"
SEED = 42
HOLDOUT_RATIO = 0.12


def _source_files(cases) -> list[str]:
    """与 compare main() 同口径：relevant_source_ids → corpus 文件路径。"""
    files: set[str] = set()
    for c in cases:
        files.update(c.relevant_source_ids or [])
    paths = []
    for sid in sorted(files):
        cand = CORPUS / sid
        if cand.exists():
            paths.append(str(cand))
        else:
            for f in CORPUS.iterdir():
                if f.name.lower() == sid.lower():
                    paths.append(str(f))
                    break
    return paths


def _entry_dict(entry) -> dict:
    return {
        "case_id": entry.case_id,
        "source_id": entry.source_id,
        "normalized_snippet": entry.normalized_snippet,
        "matched_chunk_ids": entry.matched_chunk_ids,
        "match_method": entry.match_method,
        "reviewer_status": entry.reviewer_status,
    }


def main() -> None:
    cases = load_dataset(DATASET)
    dev, holdout = group_aware_split(cases, seed=SEED)
    fp = compute_split_fingerprint(dev, holdout)

    # ── 1. split manifest ─────────────────────────────────────────────
    manifest = {
        "algorithm": (
            "evaluation.compare.group_aware_split "
            "(stable: sorted chain roots + sorted output, PYTHONHASHSEED-independent)"
        ),
        "seed": SEED,
        "holdout_ratio": HOLDOUT_RATIO,
        "split_fingerprint": fp,
        "total_cases": len(cases),
        "dev_count": len(dev),
        "holdout_count": len(holdout),
        "dev_case_ids": sorted(c.id for c in dev),
        "holdout_case_ids": sorted(c.id for c in holdout),
    }
    (OUT / "split-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"split: dev={len(dev)} holdout={len(holdout)} "
          f"fingerprint={fp}")
    print(f"written: {OUT.name}/split-manifest.json")

    # ── 2. per-split GT map（缓存索引只读）────────────────────────────
    file_paths = _source_files(cases)
    model, collection, bm25, all_docs, all_metadatas = prepare_index(
        file_paths, "eval-autorun-lock", force_rebuild=False,
    )

    for name, split_cases in (("dev", dev), ("holdout", holdout)):
        entries = build_ground_truth_map(
            split_cases, all_metadatas, all_docs)
        gt_path = OUT / f"ground-truth-map-{name}.json"
        gt_path.write_text(
            json.dumps([_entry_dict(e) for e in entries],
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        by_method = Counter(e.match_method for e in entries)
        by_status = Counter(e.reviewer_status for e in entries)
        print(f"=== {name} ({len(split_cases)} cases) ===")
        print(f"  entries={len(entries)} by_method={dict(by_method)} "
              f"by_reviewer_status={dict(by_status)}")

        # ── 3. per-split review pack（未填决定）────────────────────────
        pack_dir = OUT / f"review-pack-{name}"
        pack_manifest = build_review_pack(DATASET, gt_path, pack_dir)
        print(f"  pack: overlap={pack_manifest['overlap_needs_review_count']} "
              f"missing={pack_manifest['missing_chunk_truth_count']} "
              f"→ {pack_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
