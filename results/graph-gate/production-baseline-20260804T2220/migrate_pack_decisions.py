"""迁移人工决定：旧 pack（已填）→ 新 pack（按 split 重新导出，未填）。

按稳定键机械复制人工决定（不替人判定）：
- overlap 稳定键：(case_id, source_id, normalized_snippet, sorted candidates)
- missing 稳定键：(case_id)

校验：
- 新 pack 每行都必须从旧 pack 匹配到决定（无遗漏 → review_apply 才可过）；
- 旧 pack 中未迁移的条目（split/补标后不再需要）列出清单供审核。

用法：
python migrate_pack_decisions.py <old_pack_dir> <new_pack_dir> <output_dir>
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def _overlap_key(row: dict) -> tuple:
    return (
        row["case_id"], row["source_id"], row["normalized_snippet"],
        tuple(sorted(row["candidate_chunk_ids"])),
    )


def _missing_key(row: dict) -> str:
    return row["case_id"]


def load_rows(path: Path) -> list[dict]:
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def migrate(old_pack: Path, new_pack: Path, output: Path) -> None:
    old_overlap = load_rows(old_pack / "review-overlap.jsonl")
    old_missing = load_rows(old_pack / "missing-chunk-truth.jsonl")
    new_overlap = load_rows(new_pack / "review-overlap.jsonl")
    new_missing = load_rows(new_pack / "missing-chunk-truth.jsonl")

    old_ov_map = {_overlap_key(r): r for r in old_overlap}
    old_mi_map = {_missing_key(r): r for r in old_missing}

    filled_overlap, missing_keys = [], []
    for row in new_overlap:
        src = old_ov_map.get(_overlap_key(row))
        if src is None:
            missing_keys.append(_overlap_key(row))
            continue
        row["review_decision"] = src["review_decision"]
        row["reviewer_notes"] = src.get("reviewer_notes", "")
        filled_overlap.append(row)

    filled_missing, missing_mi = [], []
    for row in new_missing:
        src = old_mi_map.get(_missing_key(row))
        if src is None:
            missing_mi.append(_missing_key(row))
            continue
        row["relevance_level"] = src["relevance_level"]
        row["reviewer_notes"] = src.get("reviewer_notes", "")
        filled_missing.append(row)

    # 输出
    output.mkdir(parents=True, exist_ok=True)
    (output / "review-overlap.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in filled_overlap) + "\n",
        encoding="utf-8")
    (output / "missing-chunk-truth.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in filled_missing) + "\n",
        encoding="utf-8")
    shutil.copy2(new_pack / "review-pack-manifest.json", output / "review-pack-manifest.json")

    # 报告
    used_old = {_overlap_key(r) for r in filled_overlap}
    not_migrated_ov = [
        r for r in old_overlap if _overlap_key(r) not in used_old
    ]
    not_migrated_mi = [
        r for r in old_missing
        if _missing_key(r) not in {_missing_key(m) for m in filled_missing}
    ]
    print(f"migrated overlap: {len(filled_overlap)}/{len(new_overlap)}")
    print(f"migrated missing: {len(filled_missing)}/{len(new_missing)}")
    print(f"old overlap not migrated (no longer needed): "
          f"{[(r['case_id'], r['source_id']) for r in not_migrated_ov]}")
    print(f"old missing not migrated: {[r['case_id'] for r in not_migrated_mi]}")
    if missing_keys:
        print(f"!! new overlap rows without source decision: "
              f"{[k[0] for k in missing_keys]}")
        sys.exit(1)
    if missing_mi:
        print(f"!! new missing rows without source decision: {missing_mi}")
        sys.exit(1)
    print(f"written: {output}")


if __name__ == "__main__":
    old_dir = Path(sys.argv[1])
    new_dir = Path(sys.argv[2])
    out_dir = Path(sys.argv[3])
    migrate(old_dir, new_dir, out_dir)
