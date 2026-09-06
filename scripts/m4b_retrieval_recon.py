"""M4b 侦查：检索缺口机制的本地重放分解（零 LLM 调用）。

目的
----
M2 基线显示可答例 122 中 99 例 context∩truth=∅（检索缺口）。本脚本在
修复前的配置上重放检索（仅原 query、无 rewrite/decompose 规划——见
「局限」），把缺口分解为三类机制：

1. **通道未召回**：真值块不在 dense top-k 也不在 bm25 top-k；
2. **融合/截断丢失**：真值块在候选面内，但 RRF 融合后排名靠后/被拒答；
3. **检索早退（拒答）**：max RRF score < RAG_REFUSAL_THRESHOLD（0.03，
   早期拒绝）→ 无 LLM 生成，答案 = 固定拒答消息。

同时对照 M2 实况（answer 是否固定拒答消息、context_chunk_ids 是否空），
检验「M2 空 context ≈ 检索早退」的机制假设。

局限（如实声明，不得当作基准复现）
----------------------------------
- 不执行 rewrite/decompose（LLM 规划在 M2 路径中先于检索，改写可能改变
  子查询）。本脚本是「原 query 语义检索能力」的初步机制检验；
- 每通道深度固定 k=70（DEFAULT_TOP_K，与 M2 路径的候选宽度一致）；
- 拒答阈值取默认 0.03（M2 运行时 .env 无覆盖，已核验仅 LLM_MODEL 设置）。

用法::

    python scripts/m4b_retrieval_recon.py [--out results/answer-level/m4b-recon.scratch.jsonl]
    python scripts/m4b_retrieval_recon.py --limit 3   # 冒烟自检
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.generation_runner import _normalize_chunk_id


def _truth_ids(outcome: dict) -> set[str]:
    """M2 outcomes 的 relevant_chunk_ids 已是 12-hex 归一域。"""
    return set(outcome.get("relevant_chunk_ids") or [])


def _norm_many(ids) -> set[str]:
    return {_normalize_chunk_id(c) for c in ids}


def _first_rank(id_list, truth: set[str]) -> int | None:
    """真值块在候选序列中的首个 rank（0-based）；None = 未出现。"""
    for rank, cid in enumerate(id_list):
        if _normalize_chunk_id(cid) in truth:
            return rank
    return None


def _max_score_per_truth(fused, truth: set[str]) -> tuple[int | None, float | None]:
    """真值块的 fused rank 与分数（12-hex 域）。"""
    for rank, (cid, score) in enumerate(fused):
        if _normalize_chunk_id(cid) in truth:
            return rank, float(score)
    return None, None


def build_index(corpus_dir: Path, dataset_path: Path, chroma_path: Path, collection_name: str):
    """复刻 GenerationRunner.build_index 的语料选择 + 沙箱索引（零产品污染）。"""
    from evaluation.schema import load_dataset
    from src.rag import prepare_index

    cases = load_dataset(dataset_path)
    source_files: set[str] = set()
    for case in cases:
        source_files.update(case.relevant_source_ids)

    file_paths: list[str] = []
    for source_id in sorted(source_files):
        candidate = corpus_dir / source_id
        if candidate.exists():
            file_paths.append(str(candidate))
        else:
            for f in corpus_dir.iterdir():
                if f.name.lower() == source_id.lower():
                    file_paths.append(str(f))
                    break
    if not file_paths:
        raise FileNotFoundError(f"No source files under {corpus_dir}")

    print(f"[recon] index: {len(file_paths)} files -> collection={collection_name}")
    model, collection, bm25, docs, metadatas = prepare_index(
        file_paths, collection_name, force_rebuild=True, chroma_path=str(chroma_path),
    )
    print(f"[recon] index built: {len(docs)} chunks")
    return model, collection, bm25, docs, metadatas


def recon_case(
    query: str,
    truth: set[str],
    model, collection, bm25, docs, metadatas,
    refusal_threshold: float,
    top_k: int = 70,
    dynamic_min_k: int = 12,
    dynamic_max_k: int = 70,
) -> dict:
    from src.rag import retrieve_hybrid_with_sources, retrieval_refused

    # 一次调用：_channel_sink 只开观测侧信道，不改变检索结果
    # （公开契约：默认 None 零开销；传入时返回内容不变）。
    sink: dict = {}
    indices, _, scores = retrieve_hybrid_with_sources(
        query, model, collection, bm25, docs, metadatas,
        k=top_k, _channel_sink=sink,
    )
    fused_ids = [str((metadatas[i] or {}).get("chunk_id", f"chunk_{i}")) for i in indices]
    fused_scores = [float(s) for s in scores]
    fused = list(zip(fused_ids, fused_scores))

    # 排序/预算层复现（与 prepare_answer_evidence 同参数）：
    # dynamic_top_k 刀口（默认 min 12 / max 70）+ compute_context_k（默认 10）。
    from src.rag import compute_context_k, dynamic_top_k
    cutoff_k = dynamic_top_k(fused_scores)
    ctx_k = compute_context_k([None] * len(fused)) if fused else 0

    # 分通道候选 ID（观测侧信道：dense/bm25 各自的 chunk_id/rank/score）
    dense_ids = [c["chunk_id"] for c in sink.get("dense", [])]
    bm25_ids = [c["chunk_id"] for c in sink.get("bm25", [])]

    truth_rank_dense = _first_rank(dense_ids, truth)
    truth_rank_bm25 = _first_rank(bm25_ids, truth)
    truth_rank_fused = _first_rank(fused_ids, truth)
    # 真值块是否被双通道各自召回
    in_dense = truth_rank_dense is not None
    in_bm25 = truth_rank_bm25 is not None

    max_score = max((s for _, s in fused), default=0.0)
    refused = bool(not fused or max_score < refusal_threshold)

    return {
        "in_dense": in_dense,
        "in_bm25": in_bm25,
        "truth_rank_dense": truth_rank_dense,
        "truth_rank_bm25": truth_rank_bm25,
        "truth_rank_fused": truth_rank_fused,
        "fused_count": len(fused),
        "max_rrf_score": round(max_score, 6),
        "recon_refused": refused,  # 重放判定（无 rewrite 规划）
        "dynamic_k": cutoff_k,   # dynamic_top_k 刀口（min12-max70，含分界）
        "context_k": ctx_k,      # compute_context_k 预算（默认 ≤10）
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="results/answer-level/m4b-recon.scratch.jsonl")
    parser.add_argument("--limit", type=int, default=None, help="冒烟：仅前 N 例")
    parser.add_argument(
        "--m2-dir", default="results/answer-level/m2-baseline-2026-08-30",
        help="outcomes 源目录（M2 密封默认；臂1/臂2 伴生重放指向其产物目录）")
    parser.add_argument(
        "--refusal-threshold", type=float, default=0.03,
        help="检索拒答阈值（默认 0.03 = Settings 默认；M2 运行时无覆盖）")
    parser.add_argument(
        "--top-k", type=int, default=70,
        help="每通道候选深度（默认 70 = DEFAULT_TOP_K；深度检验用更大值）")
    parser.add_argument(
        "--dynamic-min-k", type=int, default=12,
        help="dynamic_top_k min_k（默认 12；臂2 伴生重放传 25）")
    parser.add_argument(
        "--dynamic-max-k", type=int, default=70,
        help="dynamic_top_k max_k（默认 70）")
    args = parser.parse_args(argv)

    m2_dir = Path(args.m2_dir)
    corpus_dir = Path("data/v2-corpus/documents/processed")
    dataset_path = Path("evaluation/datasets/v2.1.jsonl")

    from src.rag import REFUSAL_MESSAGE

    outcomes = []
    with open(m2_dir / "outcomes.jsonl", encoding="utf-8") as f:
        for line in f:
            outcomes.append(json.loads(line))
    if args.limit:
        outcomes = outcomes[: args.limit]
    print(f"[recon] cases: {len(outcomes)}")

    # Windows 下 chroma 文件句柄在进程退出前不被释放，临时目录清理
    # 可能失败——残留仅位于系统 temp，不影响仓库与结果。
    with tempfile.TemporaryDirectory(
        prefix="mneme-m4b-recon-", ignore_cleanup_errors=True) as tmp:
        chroma_path = Path(tmp) / "chroma_db"
        model, collection, bm25, docs, metadatas = build_index(
            corpus_dir, dataset_path, chroma_path, "m4b_recon")

        rows = []
        for o in outcomes:
            truth = _truth_ids(o)
            info = recon_case(
                o["query"], truth, model, collection, bm25, docs, metadatas,
                args.refusal_threshold, top_k=args.top_k,
                dynamic_min_k=args.dynamic_min_k, dynamic_max_k=args.dynamic_max_k,
            )
            info.update({
                "case_id": o["case_id"],
                "query_type": o.get("query_type"),
                "language": o.get("language"),
                "should_refuse": o.get("should_refuse"),
                "truth_count": len(truth),
                "m2_context_empty": not (o.get("context") or "").strip(),
                "m2_answer_is_refusal_msg": (o.get("answer") or "").strip().startswith(
                    REFUSAL_MESSAGE[:20]),
                "m2_ctx_contains_truth": bool(
                    _norm_many(o.get("context_chunk_ids") or []) & truth),
            })
            rows.append(info)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"[recon] wrote {len(rows)} rows -> {out}")

    # ── 汇总 ──
    answerable = [r for r in rows if not r["should_refuse"]]
    gaps = [r for r in answerable if not r["m2_ctx_contains_truth"]]
    empty = [r for r in answerable if r["m2_context_empty"]]
    print(f"\n[recon] answerable={len(answerable)} gap={len(gaps)} "
          f"m2-empty-context={len(empty)}")
    for label, grp in [("全部可答", answerable), ("缺口例", gaps), ("空context例", empty)]:
        if not grp:
            continue
        n = len(grp)
        refused = sum(1 for r in grp if r["recon_refused"])
        ch_miss = sum(1 for r in grp if not r["in_dense"] and not r["in_bm25"])
        ch_single = sum(1 for r in grp if r["in_dense"] != r["in_bm25"])
        ch_both = sum(1 for r in grp if r["in_dense"] and r["in_bm25"])
        in_fused = sum(1 for r in grp if r["truth_rank_fused"] is not None)
        print(f"  [{label} n={n}] 重放拒答={refused} | 真值块: "
              f"双通道={ch_both} 单通道={ch_single} 零通道={ch_miss} "
              f"| 在fused内={in_fused}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
