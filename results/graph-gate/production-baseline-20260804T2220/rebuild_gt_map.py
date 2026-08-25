"""离线重建 ground-truth map（基于**当前** dataset + 缓存索引，只读）。

用途：
1. 验证 dev/holdout 全部 case 的 snippet→chunk 匹配方法分布
   （exact=auto 可靠 / overlap=needs_review 需 overlay 覆盖 /
   source_fallback/unmatched=无可靠真值）；
2. 为重新导出 review pack 提供与新 dataset 一致的 GT map（新文件，
   不改 dev/ground-truth-map.json 历史产物）。

用法：python production-baseline-20260804T2220/rebuild_gt_map.py
输出：ground-truth-map-dev-new.json / ground-truth-map-holdout-new.json
      + 控制台方法分布统计。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from evaluation.compare import build_ground_truth_map, group_aware_split
from evaluation.schema import load_dataset
from src.rag import prepare_index

OUT = Path(__file__).resolve().parent
DATASET = ROOT / "evaluation/datasets/v1.jsonl"
CORPUS = ROOT / "test_texts"


def _source_files(cases) -> list[str]:
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


def _entry_summary(entries) -> dict:
    by_method = Counter(e.match_method for e in entries)
    by_status = Counter(e.reviewer_status for e in entries)
    needs_review_cases = sorted(
        {e.case_id for e in entries if e.reviewer_status == "needs_review"})
    no_truth_cases = sorted(
        {e.case_id for e in entries
         if e.match_method in ("source_fallback", "unmatched")})
    return {
        "entry_count": len(entries),
        "by_method": dict(by_method),
        "by_reviewer_status": dict(by_status),
        "needs_review_cases": needs_review_cases,
        "no_reliable_truth_cases": no_truth_cases,
    }


def main() -> None:
    cases = load_dataset(DATASET)
    dev, holdout = group_aware_split(cases, seed=42)
    file_paths = _source_files(cases)
    model, collection, bm25, all_docs, all_metadatas = prepare_index(
        file_paths, "eval-autorun-lock", force_rebuild=False)

    for name, split_cases in (("dev", dev), ("holdout", holdout)):
        entries = build_ground_truth_map(
            split_cases, all_metadatas, all_docs)
        summary = _entry_summary(entries)
        path = OUT / f"ground-truth-map-{name}-new.json"
        path.write_text(
            json.dumps([
                {
                    "case_id": e.case_id,
                    "source_id": e.source_id,
                    "normalized_snippet": e.normalized_snippet,
                    "matched_chunk_ids": e.matched_chunk_ids,
                    "match_method": e.match_method,
                    "reviewer_status": e.reviewer_status,
                }
                for e in entries
            ], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"=== {name} ({len(split_cases)} cases) ===")
        print(f"  entries: {summary['entry_count']}")
        print(f"  by_method: {summary['by_method']}")
        print(f"  by_reviewer_status: {summary['by_reviewer_status']}")
        print(f"  needs_review cases: {summary['needs_review_cases']}")
        print(f"  no_reliable_truth cases: {summary['no_reliable_truth_cases']}")
        print(f"  written: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
