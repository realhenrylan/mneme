"""迁移人工决定：canonical pack（review-pack-chunk-annotated，27 条）
→ 新 split 的 per-split pack（按稳定键机械回填，不替人判定）。

overlap 稳定键：(case_id, source_id, normalized_snippet, sorted candidates)
missing 稳定键：(case_id)

校验（fail-closed）：
- 新 pack 每行都必须从 canonical pack 匹配到决定（无遗漏 → review_apply
  才可过）；缺失 → 非零退出；
- 未迁移的旧条目（如 en-004/mixed-005 的 reject 决定——补标后其标注为
  exact 匹配，不再产生 overlap 行）列出清单供审计（保留于历史记录）。

用法：python migrate_pack_decisions.py <canonical_pack> <new_pack> <output>
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


def migrate(canonical: Path, new_pack: Path, output: Path) -> None:
    can_overlap = load_rows(canonical / "review-overlap.jsonl")
    can_missing = load_rows(canonical / "missing-chunk-truth.jsonl")
    new_overlap = load_rows(new_pack / "review-overlap.jsonl")
    new_missing = load_rows(new_pack / "missing-chunk-truth.jsonl")

    can_ov_map = {_overlap_key(r): r for r in can_overlap}
    can_mi_map = {_missing_key(r): r for r in can_missing}

    filled_overlap, missing_keys = [], []
    for row in new_overlap:
        src = can_ov_map.get(_overlap_key(row))
        if src is None:
            missing_keys.append(_overlap_key(row))
            continue
        row["review_decision"] = src["review_decision"]
        row["reviewer_notes"] = src.get("reviewer_notes", "")
        filled_overlap.append(row)

    filled_missing, missing_mi = [], []
    for row in new_missing:
        src = can_mi_map.get(_missing_key(row))
        if src is None:
            missing_mi.append(_missing_key(row))
            continue
        row["relevance_level"] = src["relevance_level"]
        row["reviewer_notes"] = src.get("reviewer_notes", "")
        filled_missing.append(row)

    output.mkdir(parents=True, exist_ok=True)
    (output / "review-overlap.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in filled_overlap) + "\n",
        encoding="utf-8")
    (output / "missing-chunk-truth.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in filled_missing) + "\n",
        encoding="utf-8")
    shutil.copy2(new_pack / "review-pack-manifest.json",
                 output / "review-pack-manifest.json")

    # 报告
    used_keys = {_overlap_key(r) for r in filled_overlap}
    not_migrated_ov = [
        r for r in can_overlap if _overlap_key(r) not in used_keys
    ]
    not_migrated_mi = [
        r for r in can_missing
        if _missing_key(r) not in {_missing_key(m) for m in filled_missing}
    ]
    print(f"migrated overlap: {len(filled_overlap)}/{len(new_overlap)}")
    print(f"migrated missing: {len(filled_missing)}/{len(new_missing)}")
    print(f"canonical overlap not migrated (no target row): "
          f"[(case, source, decision)] = "
          f"{[(r['case_id'], r['source_id'], r['review_decision']) for r in not_migrated_ov]}")
    print(f"canonical missing not migrated: "
          f"{[r['case_id'] for r in not_migrated_mi]}")
    if missing_keys:
        print(f"!! new overlap rows without source decision: "
              f"{[k[0] for k in missing_keys]}")
        sys.exit(1)
    if missing_mi:
        print(f"!! new missing rows without source decision: {missing_mi}")
        sys.exit(1)
    print(f"written: {output}")


if __name__ == "__main__":
    canonical_dir = Path(sys.argv[1])
    new_dir = Path(sys.argv[2])
    out_dir = Path(sys.argv[3])
    migrate(canonical_dir, new_dir, out_dir)
