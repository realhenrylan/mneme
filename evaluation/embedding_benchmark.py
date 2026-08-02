"""Embedding 模型对比评测工具。

对比不同 embedding 模型在检索质量、索引构建时间、查询延迟、内存占用上的表现。
用于决策是否从 all-MiniLM-L6-v2 切换到多语种模型（如 bge-m3）。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from evaluation.schema import EvalCase, load_dataset
from evaluation.metrics import compute_retrieval_metrics


@dataclass
class EmbeddingComparison:
    """单个 embedding 模型的评测结果。"""

    model_name: str
    # 检索质量指标
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    # 分层指标（按语言）
    by_language: dict[str, dict[str, float]] = field(default_factory=dict)
    # 性能指标
    index_build_ms: float = 0.0
    query_ms_p50: float = 0.0
    query_ms_p95: float = 0.0
    memory_mb: float = 0.0
    index_size_mb: float = 0.0
    # 维度
    embedding_dim: int = 0


def _measure_memory() -> float:
    """测量当前进程的内存占用（MB）。"""
    try:
        import psutil
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / (1024 * 1024)
    except ImportError:
        return 0.0


def run_single_model_benchmark(
    model_name: str,
    dataset: list[EvalCase],
    corpus_dir: str,
    collection_name: str = "bench_eval",
    ks: tuple[int, ...] = (5, 10),
) -> EmbeddingComparison:
    """对单个 embedding 模型运行检索评测。

    Args:
        model_name: embedding 模型名称或路径
        dataset: 评测数据集
        corpus_dir: 语料目录
        collection_name: ChromaDB collection 名称
        ks: 评测的 K 值

    Returns:
        EmbeddingComparison 评测结果
    """
    from src.rag import (
        prepare_index,
        retrieve_hybrid_with_sources,
    )

    # 1. 构建索引并测量时间
    mem_before = _measure_memory()
    build_start = time.perf_counter()

    # 设置环境变量让 prepare_index 使用指定模型
    old_model = os.environ.get("EMBEDDING_MODEL_NAME", "")
    os.environ["EMBEDDING_MODEL_NAME"] = model_name

    try:
        model, collection, bm25, all_docs, all_metadatas = prepare_index(
            [corpus_dir],
            collection_name=collection_name,
            force_rebuild=True,
        )
    finally:
        # 恢复环境变量
        if old_model:
            os.environ["EMBEDDING_MODEL_NAME"] = old_model
        elif "EMBEDDING_MODEL_NAME" in os.environ:
            del os.environ["EMBEDDING_MODEL_NAME"]

    build_ms = (time.perf_counter() - build_start) * 1000
    mem_after = _measure_memory()

    # 获取 embedding 维度
    embedding_dim = model.get_sentence_embedding_dimension()

    # 2. 逐条运行检索评测
    all_retrieved_ids: list[list[str]] = []
    all_relevant_ids: list[list[str]] = []
    query_times: list[float] = []

    # 构建 chunk_id → index 映射
    all_ids = [
        meta.get("chunk_id", f"chunk_{i}")
        for i, meta in enumerate(all_metadatas)
    ]

    for case in dataset:
        if case.should_refuse:
            continue  # 跳过拒答类查询

        query_start = time.perf_counter()
        indices, docs, scores = retrieve_hybrid_with_sources(
            query=case.query,
            model=model,
            collection=collection,
            bm25=bm25,
            documents=all_docs,
            metadatas=all_metadatas,
        )
        query_ms = (time.perf_counter() - query_start) * 1000
        query_times.append(query_ms)

        # 映射到 chunk_id
        retrieved_chunk_ids = [all_ids[i] for i in indices if i < len(all_ids)]
        relevant_chunk_ids = [
            chunk.source_id for chunk in case.relevant_chunks
        ]

        all_retrieved_ids.append(retrieved_chunk_ids)
        all_relevant_ids.append(relevant_chunk_ids)

    # 3. 计算指标
    metrics = compute_retrieval_metrics(all_retrieved_ids, all_relevant_ids, ks=ks)

    # 4. 分层指标（按语言）
    by_language: dict[str, dict[str, float]] = {}
    lang_groups: dict[str, tuple[list, list]] = {}
    for i, case in enumerate(dataset):
        if case.should_refuse:
            continue
        lang = case.language.value if hasattr(case.language, "value") else str(case.language)
        if lang not in lang_groups:
            lang_groups[lang] = ([], [])
        lang_groups[lang][0].append(all_retrieved_ids[i])
        lang_groups[lang][1].append(all_relevant_ids[i])

    for lang, (retrieved, relevant) in lang_groups.items():
        if retrieved:
            by_language[lang] = compute_retrieval_metrics(retrieved, relevant, ks=ks)

    # 5. 计算性能指标
    query_times_sorted = sorted(query_times)
    p50_idx = len(query_times_sorted) // 2
    p95_idx = int(len(query_times_sorted) * 0.95)

    return EmbeddingComparison(
        model_name=model_name,
        recall_at_5=metrics.get("recall@5", 0.0),
        recall_at_10=metrics.get("recall@10", 0.0),
        mrr=metrics.get("mrr", 0.0),
        ndcg_at_5=metrics.get("ndcg@5", 0.0),
        by_language=by_language,
        index_build_ms=build_ms,
        query_ms_p50=query_times_sorted[p50_idx] if query_times_sorted else 0.0,
        query_ms_p95=query_times_sorted[min(p95_idx, len(query_times_sorted) - 1)] if query_times_sorted else 0.0,
        memory_mb=mem_after - mem_before,
        embedding_dim=embedding_dim,
    )


def print_comparison_table(comparisons: list[EmbeddingComparison]) -> str:
    """打印对比表格。"""
    lines = []
    header = f"{'Model':<30} {'Dim':>4} {'R@5':>6} {'R@10':>6} {'MRR':>6} {'nDCG@5':>7} {'Build(ms)':>10} {'Qp50(ms)':>9} {'Mem(MB)':>8}"
    lines.append(header)
    lines.append("-" * len(header))
    for c in comparisons:
        line = (
            f"{c.model_name:<30} {c.embedding_dim:>4} "
            f"{c.recall_at_5:>6.3f} {c.recall_at_10:>6.3f} "
            f"{c.mrr:>6.3f} {c.ndcg_at_5:>7.3f} "
            f"{c.index_build_ms:>10.0f} {c.query_ms_p50:>9.1f} "
            f"{c.memory_mb:>8.1f}"
        )
        lines.append(line)

    # 分层对比
    all_langs = set()
    for c in comparisons:
        all_langs.update(c.by_language.keys())
    for lang in sorted(all_langs):
        lines.append(f"\n--- {lang} ---")
        header2 = f"{'Model':<30} {'R@5':>6} {'R@10':>6} {'MRR':>6}"
        lines.append(header2)
        lines.append("-" * len(header2))
        for c in comparisons:
            lang_metrics = c.by_language.get(lang, {})
            line = (
                f"{c.model_name:<30} "
                f"{lang_metrics.get('recall@5', 0.0):>6.3f} "
                f"{lang_metrics.get('recall@10', 0.0):>6.3f} "
                f"{lang_metrics.get('mrr', 0.0):>6.3f}"
            )
            lines.append(line)

    return "\n".join(lines)
