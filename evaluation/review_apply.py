"""Review pack 人工填写结果的严格导入与 overlay 生成（离线、fail-closed）。

流程（README 使用路径）：
1. 运行 ``evaluation.review_pack`` 导出待审阅条目；
2. 人工填写 ``review-overlap.jsonl`` 的 review_decision（confirmed/reject）
   与 ``missing-chunk-truth.jsonl`` 的 relevance_level（chunk/source）；
3. 运行本模块：严格校验填写结果，产出版本化
   ``reviewed-truth-overlay.json`` + ``review-apply-manifest.json``；
4. ``evaluation.compare --reviewed-truth <overlay>`` 消费人工结论。

fail-closed 原则：
- 先校验 review-pack-manifest 记录的 dataset/ground-truth SHA-256 与
  当前输入一致（陈旧输入拒绝）；
- 严格校验两 JSONL：行数必须等于 manifest 计数（无重复/缺失/未知行）、
  键集必须等于导出模板（无未知列/缺失列）、review_decision 只能
  confirmed/reject、relevance_level 只能 chunk/source；
- 任何空值、非法值、陈旧输入、行集不完整都整体失败，不产生部分输出；
- 输出写入用户指定的新目录，绝不覆盖输入（pack 目录被拒绝作为输出）。

overlay 语义（消费端见 evaluation/compare.apply_reviewed_truth_overlay）：
- overlap confirmed → reviewer_status="confirmed"（可靠 chunk 真值）；
- overlap reject  → reviewer_status="rejected"（显式拒绝，绝不与
  confirmed 混淆）；
- missing-truth 的 relevance_level 按 case_id 保存：chunk（需补标内容
  chunk）或 source（source-only，从 chunk/context/citation 分母排除）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

REVIEW_APPLY_VERSION = 1

OVERLAY_FILENAME = "reviewed-truth-overlay.json"
MANIFEST_FILENAME = "review-apply-manifest.json"

# 导出模板键集（review_pack 导出的 JSONL 行键；键集漂移即拒绝）
OVERLAP_TEMPLATE_KEYS = frozenset({
    "case_id", "query", "query_type", "language", "source_id",
    "normalized_snippet", "candidate_chunk_ids", "match_evidence",
    "reviewer_status", "review_decision", "reviewer_notes",
})
MISSING_TEMPLATE_KEYS = frozenset({
    "case_id", "query", "query_type", "language", "relevant_source_ids",
    "acceptable_answer_points", "metadata", "relevance_level",
    "reviewer_notes",
})

REVIEW_DECISION_VALUES = ("confirmed", "reject")   # 人工可填的 overlap 结论
RELEVANCE_LEVEL_VALUES = ("chunk", "source")       # 人工可填的层级结论

# overlay 中 reject 的规范表示（与 confirmed 显式区分）
REJECTED = "rejected"


class ReviewApplyError(ValueError):
    """review pack 导入/校验失败（携带错误描述列表）。"""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = list(errors)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


# ── 加载与校验 ───────────────────────────────────────────────────────

def load_review_pack(pack_dir: Path) -> tuple[dict[str, Any], list[dict], list[dict]]:
    """读取 review pack 目录（manifest + 两个 JSONL），结构非法即失败。"""
    pack_dir = Path(pack_dir)
    manifest_path = pack_dir / "review-pack-manifest.json"
    overlap_path = pack_dir / "review-overlap.jsonl"
    missing_path = pack_dir / "missing-chunk-truth.jsonl"
    errors: list[str] = []
    for p in (manifest_path, overlap_path, missing_path):
        if not p.exists():
            errors.append(f"missing review pack file: {p.name}")
    if errors:
        raise ReviewApplyError(errors)

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewApplyError([f"unreadable review-pack-manifest.json: {exc}"]) from exc
    if not isinstance(manifest, dict):
        raise ReviewApplyError(["review-pack-manifest.json root must be a JSON object"])

    def _read_rows(path: Path) -> list[dict]:
        rows: list[dict] = []
        with open(path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ReviewApplyError([f"invalid JSON at {path.name}:{line_no}: {exc}"]) from exc
                if not isinstance(row, dict):
                    raise ReviewApplyError([f"non-object row at {path.name}:{line_no}"])
                rows.append(row)
        return rows

    try:
        overlap_rows = _read_rows(overlap_path)
        missing_rows = _read_rows(missing_path)
    except ReviewApplyError:
        raise
    return manifest, overlap_rows, missing_rows


def verify_pack_inputs(
    manifest: dict[str, Any],
    dataset_path: Path,
    ground_truth_path: Path,
) -> None:
    """manifest 记录的输入 SHA-256 必须与当前输入一致（陈旧拒绝）。"""
    errors: list[str] = []
    if _sha256_file(dataset_path) != manifest.get("dataset_sha256"):
        errors.append("dataset sha256 mismatch vs review-pack-manifest "
                      "(stale inputs; re-export the review pack)")
    if _sha256_file(ground_truth_path) != manifest.get("ground_truth_sha256"):
        errors.append("ground_truth sha256 mismatch vs review-pack-manifest "
                      "(stale inputs; re-export the review pack)")
    if errors:
        raise ReviewApplyError(errors)


def validate_filled_rows(
    manifest: dict[str, Any],
    overlap_rows: list[dict],
    missing_rows: list[dict],
) -> None:
    """严格校验填写结果：行数、键集、重复、必填值。失败不产生输出。"""
    errors: list[str] = []

    # 行数必须与 manifest 计数一致（无重复/缺失/未知行）
    n_expected = manifest.get("overlap_needs_review_count")
    if len(overlap_rows) != n_expected:
        errors.append(
            f"overlap rows count {len(overlap_rows)} != manifest "
            f"count {n_expected}",
        )
    m_expected = manifest.get("missing_chunk_truth_count")
    if len(missing_rows) != m_expected:
        errors.append(
            f"missing-truth rows count {len(missing_rows)} != manifest "
            f"count {m_expected}",
        )

    # 键集必须等于导出模板（未知列/缺失列拒绝）
    for i, row in enumerate(overlap_rows):
        if set(row) != OVERLAP_TEMPLATE_KEYS:
            errors.append(f"overlap row {i}: keys mismatch vs template")
    for i, row in enumerate(missing_rows):
        if set(row) != MISSING_TEMPLATE_KEYS:
            errors.append(f"missing-truth row {i}: keys mismatch vs template")

    # 重复行（稳定键：case/source/snippet/候选 chunk）
    seen: set[tuple] = set()
    for row in overlap_rows:
        key = (
            row.get("case_id"), row.get("source_id"),
            row.get("normalized_snippet"),
            tuple(sorted(row.get("candidate_chunk_ids", []))),
        )
        if key in seen:
            errors.append(f"duplicate overlap row: {key}")
        seen.add(key)

    seen_cases: set[str] = set()
    for row in missing_rows:
        cid = row.get("case_id")
        if cid in seen_cases:
            errors.append(f"duplicate missing-truth row: case_id={cid}")
        seen_cases.add(cid)

    # 必填值（空/非法拒绝）
    for row in overlap_rows:
        decision = row.get("review_decision", "")
        if decision not in REVIEW_DECISION_VALUES:
            errors.append(
                f"overlap row {row.get('case_id')}/{row.get('source_id')}: "
                f"review_decision must be one of {REVIEW_DECISION_VALUES}, "
                f"got {decision!r}",
            )
    for row in missing_rows:
        level = row.get("relevance_level", "")
        if level not in RELEVANCE_LEVEL_VALUES:
            errors.append(
                f"missing-truth row {row.get('case_id')}: relevance_level "
                f"must be one of {RELEVANCE_LEVEL_VALUES}, got {level!r}",
            )

    if errors:
        raise ReviewApplyError(errors)


# ── overlay 构建（确定性） ───────────────────────────────────────────

def build_overlay(
    manifest: dict[str, Any],
    overlap_rows: list[dict],
    missing_rows: list[dict],
) -> dict[str, Any]:
    """构建版本化 reviewed-truth overlay（确定性：同输入 → 同字节）。

    只保存已人工决定的 overlay：confirmed → "confirmed"，
    reject → "rejected"（显式映射，绝不混淆）；relevance_level 按
    case_id 保存。不含任何 secret（无 URL/token/模型标识）。
    """
    entries = sorted(
        (
            {
                "case_id": row["case_id"],
                "source_id": row["source_id"],
                "normalized_snippet": row["normalized_snippet"],
                "candidate_chunk_ids": sorted(row["candidate_chunk_ids"]),
                "review_decision": (
                    "confirmed" if row["review_decision"] == "confirmed"
                    else REJECTED
                ),
                "reviewer_notes": row.get("reviewer_notes", ""),
            }
            for row in overlap_rows
        ),
        key=lambda e: (e["case_id"], e["source_id"], e["normalized_snippet"]),
    )
    case_levels = sorted(
        (
            {
                "case_id": row["case_id"],
                "relevance_level": row["relevance_level"],
                "reviewer_notes": row.get("reviewer_notes", ""),
            }
            for row in missing_rows
        ),
        key=lambda c: c["case_id"],
    )
    counts = {
        "overlap_decisions": len(entries),
        "confirmed": sum(1 for e in entries if e["review_decision"] == "confirmed"),
        "rejected": sum(1 for e in entries if e["review_decision"] == REJECTED),
        "case_relevance_decisions": len(case_levels),
        "chunk_level": sum(1 for c in case_levels if c["relevance_level"] == "chunk"),
        "source_only": sum(1 for c in case_levels if c["relevance_level"] == "source"),
    }
    return {
        "version": REVIEW_APPLY_VERSION,
        "dataset_sha256": manifest["dataset_sha256"],
        "ground_truth_sha256": manifest["ground_truth_sha256"],
        "entries": entries,
        "case_relevance_levels": case_levels,
        "counts": counts,
        "notes": (
            "review_decision=confirmed -> reviewer_status=confirmed; "
            "reject -> reviewer_status=rejected (never treated as confirmed); "
            "relevance_level=source -> source-only, excluded from "
            "chunk/context/citation denominators."
        ),
    }


def _atomic_write(path: Path, text: str) -> None:
    """原子写入（临时文件 + os.replace），避免半成品落盘。"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# ── 主流程与 CLI ─────────────────────────────────────────────────────

def apply_review_pack(
    dataset_path: Path,
    ground_truth_path: Path,
    pack_dir: Path,
    output_dir: Path,
    notes: str = "",
) -> dict[str, Any]:
    """严格导入 review pack 并输出 overlay + manifest 到新目录。

    全部校验通过后才写文件（fail-closed，无部分输出）；输出目录不得
    与 pack 目录相同（不覆盖输入）。
    """
    dataset_path = Path(dataset_path)
    ground_truth_path = Path(ground_truth_path)
    pack_dir = Path(pack_dir)
    output_dir = Path(output_dir)

    if output_dir.resolve() == pack_dir.resolve():
        raise ReviewApplyError(
            ["output directory must differ from the review pack directory "
             "(refusing to overwrite inputs)"],
        )

    manifest, overlap_rows, missing_rows = load_review_pack(pack_dir)
    verify_pack_inputs(manifest, dataset_path, ground_truth_path)
    validate_filled_rows(manifest, overlap_rows, missing_rows)

    overlay = build_overlay(manifest, overlap_rows, missing_rows)
    pack_manifest_sha = _sha256_file(pack_dir / "review-pack-manifest.json")

    apply_manifest = {
        "version": REVIEW_APPLY_VERSION,
        "overlay_file": OVERLAY_FILENAME,
        "dataset_sha256": overlay["dataset_sha256"],
        "ground_truth_sha256": overlay["ground_truth_sha256"],
        "review_pack_manifest_sha256": pack_manifest_sha,
        "counts": overlay["counts"],
        "notes": notes,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    overlay_text = json.dumps(overlay, ensure_ascii=False, indent=2) + "\n"
    manifest_text = json.dumps(apply_manifest, ensure_ascii=False, indent=2) + "\n"
    _atomic_write(output_dir / OVERLAY_FILENAME, overlay_text)
    _atomic_write(output_dir / MANIFEST_FILENAME, manifest_text)
    return apply_manifest


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.review_apply",
        description="Review pack 人工填写结果的严格导入与 overlay 生成"
                    "（离线、fail-closed、不覆盖输入）。",
    )
    parser.add_argument("--dataset", type=Path, required=True,
                        help="base 评测数据集 JSONL（与导出 review pack 时一致）")
    parser.add_argument("--ground-truth", type=Path, required=True,
                        help="base ground-truth-map.json（与导出 review pack 时一致）")
    parser.add_argument("--review-pack", type=Path, required=True,
                        help="已人工填写的 review pack 目录")
    parser.add_argument("--output", type=Path, required=True,
                        help="输出新目录（必须与 review pack 目录不同）")
    parser.add_argument("--notes", default="",
                        help="可选备注（写入 apply manifest）")
    args = parser.parse_args(argv)

    try:
        result = apply_review_pack(
            args.dataset, args.ground_truth, args.review_pack, args.output,
            notes=args.notes,
        )
    except ReviewApplyError as exc:
        print("Error: review pack apply failed:", file=sys.stderr)
        for e in exc.errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    counts = result["counts"]
    print(f"Reviewed truth overlay written to: {args.output}")
    print(f"  overlap decisions: {counts['overlap_decisions']} "
          f"(confirmed={counts['confirmed']}, rejected={counts['rejected']})")
    print(f"  case relevance decisions: {counts['case_relevance_decisions']} "
          f"(chunk={counts['chunk_level']}, source={counts['source_only']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
