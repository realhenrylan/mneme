"""Reproducible retrieval benchmark and quality gates."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable, Iterable


def recall_at_k(ranked_ids: Iterable[str], relevant_ids: Iterable[str], k: int) -> float:
    relevant = set(relevant_ids)
    if not relevant:
        return 1.0
    retrieved = set(list(ranked_ids)[: max(0, int(k))])
    return len(retrieved & relevant) / len(relevant)


def reciprocal_rank(ranked_ids: Iterable[str], relevant_ids: Iterable[str]) -> float:
    relevant = set(relevant_ids)
    if not relevant:
        return 1.0
    for rank, chunk_id in enumerate(ranked_ids, start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked_ids: Iterable[str], relevant_ids: Iterable[str], k: int) -> float:
    relevant = set(relevant_ids)
    if not relevant:
        return 1.0
    ranked = list(ranked_ids)[: max(0, int(k))]
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(ranked, start=1)
        if chunk_id in relevant
    )
    ideal_hits = min(len(relevant), max(0, int(k)))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def evaluate_ranked_results(
    ranked_results: Iterable[Iterable[str]],
    relevant_results: Iterable[Iterable[str]],
    k: int = 5,
) -> dict[str, float]:
    ranked = [list(result) for result in ranked_results]
    relevant = [list(result) for result in relevant_results]
    if len(ranked) != len(relevant):
        raise ValueError("ranked_results and relevant_results must have equal length")
    if not ranked:
        return {f"recall@{k}": 0.0, "mrr": 0.0, f"ndcg@{k}": 0.0}
    return {
        f"recall@{k}": sum(
            recall_at_k(result, truth, k) for result, truth in zip(ranked, relevant)
        ) / len(ranked),
        "mrr": sum(
            reciprocal_rank(result, truth) for result, truth in zip(ranked, relevant)
        ) / len(ranked),
        f"ndcg@{k}": sum(
            ndcg_at_k(result, truth, k) for result, truth in zip(ranked, relevant)
        ) / len(ranked),
    }


def run_benchmark(
    cases: Iterable[dict],
    retrieve: Callable[[str], Iterable[str]],
    k: int = 5,
) -> dict[str, float]:
    """Run benchmark cases against a retrieval callable returning chunk IDs."""
    ranked_results = []
    relevant_results = []
    for case in cases:
        ranked_results.append(list(retrieve(case["query"])))
        relevant_results.append(case.get("relevant_chunk_ids", []))
    return evaluate_ranked_results(ranked_results, relevant_results, k=k)


def load_benchmark(filepath: str | Path) -> dict:
    with open(filepath, "r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("benchmark must contain a cases list")
    return payload


def assert_quality_gates(metrics: dict[str, float], gates: dict[str, float]) -> None:
    failures = [
        f"{name}={metrics.get(name, 0.0):.4f} < {minimum:.4f}"
        for name, minimum in gates.items()
        if metrics.get(name, 0.0) < minimum
    ]
    if failures:
        raise AssertionError("retrieval quality gate failed: " + "; ".join(failures))
