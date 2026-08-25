"""P1 真值人工确认的离线审阅包生成器。

本模块为 Graph RAG 评测 (plans/GRAPH-RAG-EVALUATION-PLAN-2026-08-02.md
§5.1) 的人工复核步骤生成可复现的审阅包，设计原则：

1. **完全离线**：不调用 LLM/API/网络，不构建索引；唯一可选输入
   ``--corpus-json`` 是已有 chunk 文本的本地快照，用于生成匹配证据。
2. **只导出、不判定**：工具不修改任何真值，也不替人填写结论。
   review_decision / relevance_level / reviewer_notes 一律导出为空字段，
   由人工填写后回写。
3. **可复现**：输入相同则输出逐字节相同（无时间戳，排序确定）。

产物
----
- ``review-overlap.jsonl``：全部 reviewer_status=needs_review 的 overlap
  匹配条目（case_id、query、source、snippet、候选 chunk、匹配证据、
  空白 reviewer 字段）。
- ``missing-chunk-truth.jsonl``：可回答但缺少 chunk 真值的 case
  （relevant_chunks 为空），需人工判定 relevance_level=chunk 或 source。
- ``review-pack-manifest.json``：输入文件 SHA-256 与统计，保证可复现。

CLI
---
::

    python -m evaluation.review_pack \
        --dataset evaluation/datasets/v1.jsonl \
        --ground-truth results/graph-gate/dev/ground-truth-map.json \
        --output results/graph-gate/review-pack

    可选：--corpus-json chunks.json  # [{"chunk_id","source_id","text"}, ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from evaluation.compare import (
    _char_bigrams,
    _normalize_text,
    load_ground_truth_map,
)
from evaluation.schema import EvalCase, load_dataset

REVIEW_PACK_VERSION = 1

# 人工可填写的审阅结论（工具只导出空值）
REVIEW_DECISION_VALUES = ("confirmed", "reject")  # needs_review 条目的确认结论
RELEVANCE_LEVEL_VALUES = ("chunk", "source")      # 缺 chunk 真值 case 的层级结论

_TEXT_PREVIEW_CHARS = 120


def _sha256_file(path: Path) -> str:
    """计算文件 SHA-256（读文件，不修改内容）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def load_corpus_chunks(corpus_json: Path | None) -> dict[str, str]:
    """读取可选 chunk 文本快照，返回 chunk_id -> text。

    corpus_json 格式：JSON 数组，每项至少含 ``chunk_id`` 与 ``text``
    （可含 ``source_id``，仅作展示）。未提供时返回空 dict，匹配证据
    字段为空。
    """
    if corpus_json is None:
        return {}
    with open(corpus_json, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise ValueError(f"corpus JSON must be a list: {corpus_json}")
    chunks: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, dict) or "chunk_id" not in item:
            raise ValueError(f"corpus item must have 'chunk_id': {item!r}")
        chunks[str(item["chunk_id"])] = str(item.get("text", ""))
    return chunks


def chunk_evidence(norm_snippet: str, chunk_text: str) -> dict[str, Any]:
    """计算单个候选 chunk 的匹配证据（纯本地、确定性）。

    证据为 snippet 与 chunk 的字符 bigram 重叠比例（与
    ``match_snippet_to_chunks`` 的 overlap 判定同口径）及 chunk 文本预览，
    供人工判断匹配是否成立。
    """
    snippet_bigrams = _char_bigrams(norm_snippet)
    chunk_bigrams = _char_bigrams(chunk_text)
    overlap = (
        len(snippet_bigrams & chunk_bigrams) / len(snippet_bigrams)
        if snippet_bigrams and chunk_bigrams else 0.0
    )
    preview = chunk_text[:_TEXT_PREVIEW_CHARS]
    return {"bigram_overlap": round(overlap, 4), "text_preview": preview}


def build_overlap_review_rows(
    entries: list,
    cases_by_id: dict[str, EvalCase],
    chunk_texts: dict[str, str],
) -> list[dict[str, Any]]:
    """导出全部 reviewer_status=needs_review 的条目为审阅行。

    每行包含 case 上下文（query/query_type/language）、source、snippet、
    候选 chunk、匹配证据，以及空白的 reviewer 字段。排序按
    (case_id, source_id) 保证确定性。
    """
    rows: list[dict[str, Any]] = []
    for entry in sorted(
        (e for e in entries if e.reviewer_status == "needs_review"),
        key=lambda e: (e.case_id, e.source_id),
    ):
        case = cases_by_id.get(entry.case_id)
        evidence = [
            {
                "chunk_id": cid,
                **chunk_evidence(entry.normalized_snippet, chunk_texts.get(cid, "")),
            }
            for cid in entry.matched_chunk_ids
            if cid in chunk_texts
        ]
        rows.append({
            "case_id": entry.case_id,
            "query": case.query if case else "",
            "query_type": case.query_type.value if case else "",
            "language": case.language.value if case else "",
            "source_id": entry.source_id,
            "normalized_snippet": entry.normalized_snippet,
            "candidate_chunk_ids": entry.matched_chunk_ids,
            "match_evidence": evidence,  # 无 corpus 快照时为空列表
            "reviewer_status": entry.reviewer_status,
            # ── 人工填写字段（工具不替人判定）──
            "review_decision": "",   # REVIEW_DECISION_VALUES: confirmed / reject
            "reviewer_notes": "",
        })
    return rows


def build_missing_truth_rows(cases: list[EvalCase]) -> list[dict[str, Any]]:
    """导出可回答但缺少 chunk 真值的 case。

    判定条件：可回答（should_refuse=False）且 relevant_chunks 为空。
    需人工判定 relevance_level=chunk（存在可补标的内容 chunk）或
    source（元数据类问题，无内容 chunk 真值）。排序按 case_id。
    """
    rows: list[dict[str, Any]] = []
    for case in sorted(
        (c for c in cases if not c.should_refuse and not c.relevant_chunks),
        key=lambda c: c.id,
    ):
        rows.append({
            "case_id": case.id,
            "query": case.query,
            "query_type": case.query_type.value,
            "language": case.language.value,
            "relevant_source_ids": list(case.relevant_source_ids),
            "acceptable_answer_points": list(case.acceptable_answer_points),
            "metadata": dict(case.metadata),
            # ── 人工填写字段（工具不替人判定）──
            "relevance_level": "",  # RELEVANCE_LEVEL_VALUES: chunk / source
            "reviewer_notes": "",
        })
    return rows


def build_review_pack(
    dataset_path: Path,
    ground_truth_path: Path,
    output_dir: Path,
    corpus_json: Path | None = None,
) -> dict[str, Any]:
    """生成审阅包并落盘，返回统计信息。

    只读输入（dataset / ground-truth-map / corpus 快照），只写入
    output_dir，绝不修改输入文件。
    """
    dataset_path = Path(dataset_path)
    ground_truth_path = Path(ground_truth_path)

    cases = load_dataset(dataset_path)
    entries = load_ground_truth_map(ground_truth_path)
    cases_by_id = {c.id: c for c in cases}
    chunk_texts = load_corpus_chunks(
        Path(corpus_json) if corpus_json else None,
    )

    overlap_rows = build_overlap_review_rows(entries, cases_by_id, chunk_texts)
    missing_rows = build_missing_truth_rows(cases)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 确定性落盘：排序由 build_*_rows 保证，JSON 键序固定
    with open(output_dir / "review-overlap.jsonl", "w", encoding="utf-8") as f:
        for row in overlap_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    with open(output_dir / "missing-chunk-truth.jsonl", "w", encoding="utf-8") as f:
        for row in missing_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    manifest = {
        "review_pack_version": REVIEW_PACK_VERSION,
        "dataset_path": str(dataset_path),
        "dataset_sha256": _sha256_file(dataset_path),
        "ground_truth_path": str(ground_truth_path),
        "ground_truth_sha256": _sha256_file(ground_truth_path),
        "corpus_json": str(corpus_json) if corpus_json else None,
        "corpus_json_sha256": _sha256_file(Path(corpus_json)) if corpus_json else None,
        "overlap_needs_review_count": len(overlap_rows),
        "missing_chunk_truth_count": len(missing_rows),
        "notes": (
            "review_decision / relevance_level / reviewer_notes 均为空字段，"
            "由人工填写，工具不替人判定。"
        ),
    }
    with open(output_dir / "review-pack-manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return manifest


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.review_pack",
        description="P1 真值人工确认审阅包生成器（离线、只读输入、不判定）。",
    )
    parser.add_argument("--dataset", type=Path, required=True,
                        help="评测数据集 JSONL（evaluation/datasets/v1.jsonl）")
    parser.add_argument("--ground-truth", type=Path, required=True,
                        help="ground-truth-map.json 路径")
    parser.add_argument("--corpus-json", type=Path, default=None,
                        help="可选 chunk 文本快照 JSON（[{chunk_id,text,...}]），"
                             "用于生成匹配证据")
    parser.add_argument("--output", type=Path, required=True,
                        help="审阅包输出目录")
    args = parser.parse_args(argv)

    try:
        manifest = build_review_pack(
            args.dataset, args.ground_truth, args.output, args.corpus_json,
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(f"Review pack written to: {args.output}")
    print(f"  overlap needs_review rows: {manifest['overlap_needs_review_count']}")
    print(f"  missing chunk truth rows:  {manifest['missing_chunk_truth_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
