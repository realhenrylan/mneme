"""Retrieval and generation quality metrics for Mneme RAG evaluation.

All metrics operate on simple Python data structures (lists of IDs and
scores) so they can be used both by the evaluation runner and by unit
tests without any external dependencies.

Metric definitions
------------------
- **Recall@K**: Fraction of relevant items found in top-K results.
- **MRR** (Mean Reciprocal Rank): Reciprocal of the first relevant rank.
- **nDCG@K** (Normalized Discounted Cumulative Gain): Ranking quality
  that accounts for position and graded relevance.
- **Source Recall**: Fraction of relevant *sources* (not chunks) found
  in the top-K results.
"""

from __future__ import annotations

import math
from typing import Sequence


# ── Core retrieval metrics ──────────────────────────────────────────

def recall_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: set[str],
    k: int,
) -> float:
    """Compute Recall@K.

    Args:
        retrieved_ids: Ordered list of retrieved chunk/source IDs.
        relevant_ids: Set of IDs that are relevant (ground truth).
        k: Cutoff rank.

    Returns:
        Recall value in [0, 1].  Returns 0.0 when relevant_ids is empty.
    """
    if not relevant_ids:
        return 0.0
    top_k = set(retrieved_ids[:k])
    return len(top_k & relevant_ids) / len(relevant_ids)


def mean_reciprocal_rank(
    retrieved_ids_list: Sequence[Sequence[str]],
    relevant_ids_list: Sequence[set[str]],
) -> float:
    """Compute Mean Reciprocal Rank (MRR) across multiple queries.

    Args:
        retrieved_ids_list: Per-query ordered retrieved IDs.
        relevant_ids_list: Per-query relevant ID sets.

    Returns:
        MRR value in [0, 1].  Returns 0.0 for empty input.
    """
    if not retrieved_ids_list:
        return 0.0

    rr_sum = 0.0
    for retrieved, relevant in zip(retrieved_ids_list, relevant_ids_list):
        rr = 0.0
        for rank, rid in enumerate(retrieved, start=1):
            if rid in relevant:
                rr = 1.0 / rank
                break
        rr_sum += rr

    return rr_sum / len(retrieved_ids_list)


def ndcg_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: set[str],
    k: int,
) -> float:
    """Compute nDCG@K (Normalized Discounted Cumulative Gain).

    Uses binary relevance: relevant items get gain=1, non-relevant get 0.

    Args:
        retrieved_ids: Ordered list of retrieved IDs.
        relevant_ids: Set of relevant IDs.
        k: Cutoff rank.

    Returns:
        nDCG value in [0, 1].  Returns 0.0 when relevant_ids is empty.
    """
    if not relevant_ids:
        return 0.0

    # DCG
    dcg = 0.0
    for rank, rid in enumerate(retrieved_ids[:k], start=1):
        if rid in relevant_ids:
            dcg += 1.0 / math.log2(rank + 1)

    # Ideal DCG: all relevant items at the top
    idcg = 0.0
    for rank in range(1, min(len(relevant_ids), k) + 1):
        idcg += 1.0 / math.log2(rank + 1)

    return dcg / idcg if idcg > 0 else 0.0


def source_recall_at_k(
    retrieved_source_ids: Sequence[str],
    relevant_source_ids: set[str],
    k: int,
) -> float:
    """Compute source-level Recall@K.

    Unlike chunk-level recall, this measures whether the *sources*
    (documents) containing the answer appear in the top-K results.

    Args:
        retrieved_source_ids: Ordered list of source IDs from retrieval.
        relevant_source_ids: Set of source IDs that are relevant.
        k: Cutoff rank.

    Returns:
        Source recall value in [0, 1].
    """
    if not relevant_source_ids:
        return 0.0
    top_k_sources = set(retrieved_source_ids[:k])
    return len(top_k_sources & relevant_source_ids) / len(relevant_source_ids)


def context_source_recall(
    context_source_ids: Sequence[str],
    relevant_source_ids: set[str],
) -> float:
    """Compute source-level recall over the selected prompt context.

    与 chunk-level ``context_recall`` 对称的 source 版本：测量实际进入
    prompt 的去重 source 集合覆盖了多少 *relevant source*。分母为该
    case 的 relevant sources，故 relevance_level=source 的 case 由此处
    纳入统计（而非 chunk/context/citation 分母）。

    Args:
        context_source_ids: 实际进入 prompt 的去重 source IDs（有序）。
        relevant_source_ids: 该 case 标注的相关 source 集合。

    Returns:
        Source recall 值 ∈ [0, 1]；无 relevant source 时返回 0.0。
    """
    if not relevant_source_ids:
        return 0.0
    context_sources = set(context_source_ids)
    if not context_sources:
        return 0.0
    return len(context_sources & relevant_source_ids) / len(relevant_source_ids)


def context_source_coverage(
    context_source_ids: Sequence[str],
    relevant_source_ids: set[str],
) -> float:
    """Compute source-level coverage (precision) over prompt context.

    与 chunk-level ``context_precision`` 对称的 source 版本：测量 prompt
    context 中的去重 source 有多少是 relevant。回答“context 是否被相关
    source 占据”，用于衡量检索通道对 source recall 之后的 context 选取
    效率。

    Args:
        context_source_ids: 实际进入 prompt 的去重 source IDs（有序）。
        relevant_source_ids: 该 case 标注的相关 source 集合。

    Returns:
        Source coverage 值 ∈ [0, 1]；context 为空时返回 0.0。
    """
    context_sources = set(context_source_ids)
    if not context_sources:
        return 0.0
    return len(context_sources & relevant_source_ids) / len(context_sources)


# ── Aggregation helpers ─────────────────────────────────────────────

def compute_retrieval_metrics(
    retrieved_ids_list: Sequence[Sequence[str]],
    relevant_ids_list: Sequence[set[str]],
    ks: Sequence[int] = (5, 10, 20),
) -> dict[str, float]:
    """Compute a standard suite of retrieval metrics.

    Args:
        retrieved_ids_list: Per-query ordered retrieved IDs.
        relevant_ids_list: Per-query relevant ID sets.
        ks: Cutoff values for Recall@K and nDCG@K.

    Returns:
        Dict with keys like "recall@5", "ndcg@10", "mrr".
    """
    n = len(retrieved_ids_list)
    if n == 0:
        return {f"recall@{k}": 0.0 for k in ks} | {
            f"ndcg@{k}": 0.0 for k in ks
        } | {"mrr": 0.0}

    metrics: dict[str, float] = {}

    # Recall@K
    for k in ks:
        values = [
            recall_at_k(ret, rel, k)
            for ret, rel in zip(retrieved_ids_list, relevant_ids_list)
        ]
        metrics[f"recall@{k}"] = sum(values) / n

    # nDCG@K
    for k in ks:
        values = [
            ndcg_at_k(ret, rel, k)
            for ret, rel in zip(retrieved_ids_list, relevant_ids_list)
        ]
        metrics[f"ndcg@{k}"] = sum(values) / n

    # MRR
    metrics["mrr"] = mean_reciprocal_rank(retrieved_ids_list, relevant_ids_list)

    return metrics


def compute_stratified_metrics(
    retrieved_ids_list: Sequence[Sequence[str]],
    relevant_ids_list: Sequence[set[str]],
    groups: Sequence[str],
    ks: Sequence[int] = (5, 10, 20),
) -> dict[str, dict[str, float]]:
    """Compute retrieval metrics stratified by group labels.

    Useful for per-language or per-query-type breakdowns.

    Args:
        retrieved_ids_list: Per-query ordered retrieved IDs.
        relevant_ids_list: Per-query relevant ID sets.
        groups: Per-query group label (e.g. language, query_type).
        ks: Cutoff values.

    Returns:
        Dict mapping group label → metrics dict.
    """
    by_group: dict[str, tuple[list, list]] = {}
    for ret, rel, group in zip(retrieved_ids_list, relevant_ids_list, groups):
        bucket = by_group.setdefault(group, ([], []))
        bucket[0].append(ret)
        bucket[1].append(rel)

    return {
        group: compute_retrieval_metrics(rets, rels, ks)
        for group, (rets, rels) in by_group.items()
    }
