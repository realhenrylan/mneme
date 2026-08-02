"""检索模块：Reranker 接口、CrossEncoder 实现、来源覆盖约束。

从 src/rag.py 的融合逻辑中提取，提供可插拔的 reranker 接口。
插入位置：RRF 融合后、_build_context() 前。

流程：
  dense + bm25 → RRF merge → dynamic_top_k → Reranker → context_k → _build_context
"""

from __future__ import annotations

import dataclasses
from typing import Protocol, runtime_checkable

from src.domain import RetrievalCandidate


# ── Reranker 接口 ──


@runtime_checkable
class Reranker(Protocol):
    """重排器接口：输入候选列表 + query，输出重排后列表。"""

    def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        top_k: int = 10,
    ) -> list[RetrievalCandidate]:
        ...


# ── CrossEncoder Reranker ──


class CrossEncoderReranker:
    """本地 cross-encoder reranker。

    使用 sentence-transformers 的 CrossEncoder 模型对候选重排。
    适合对 top 20-50 候选重排到 context 5-10。
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    ) -> None:
        self._model_name = model_name
        self._model = None  # 延迟加载

    def _ensure_model(self):
        """延迟加载 cross-encoder 模型。"""
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self._model_name)

    def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        top_k: int = 10,
    ) -> list[RetrievalCandidate]:
        """对候选列表重排，返回 top_k 候选（带 rerank_score）。"""
        if not candidates:
            return []

        self._ensure_model()

        # 构建 (query, snippet) 对
        # 使用 source_name 作为 snippet 的替代（候选中没有 snippet 字段）
        # 实际使用时，调用方应确保候选有足够信息
        pairs = [(query, c.source_name) for c in candidates]
        scores = self._model.predict(pairs)

        # 更新 rerank_score
        scored = [
            dataclasses.replace(c, rerank_score=float(scores[i]))
            for i, c in enumerate(candidates)
        ]
        scored.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        return scored[:top_k]

    @property
    def model_name(self) -> str:
        return self._model_name


# ── NoOp Reranker（用于 A/B 对比） ──


class NoOpReranker:
    """不做重排的 reranker，用于 A/B 对比基线。"""

    def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        top_k: int = 10,
    ) -> list[RetrievalCandidate]:
        return candidates[:top_k]


# ── 来源覆盖约束 ──


def apply_source_diversity(
    candidates: list[RetrievalCandidate],
    max_per_source: int = 3,
    top_k: int = 10,
) -> list[RetrievalCandidate]:
    """应用来源多样性约束：同一来源最多 max_per_source 个 chunk。

    对跨文档查询尤其重要，确保不同来源都有代表。
    保持原始排序，只跳过超额的同来源候选。

    Args:
        candidates: 已排序的候选列表
        max_per_source: 每个来源的最大候选数
        top_k: 最终返回的候选数

    Returns:
        应用约束后的候选列表
    """
    result: list[RetrievalCandidate] = []
    source_count: dict[str, int] = {}

    for c in candidates:
        source = c.source_id or c.source_name
        count = source_count.get(source, 0)
        if count < max_per_source:
            result.append(c)
            source_count[source] = count + 1
            if len(result) >= top_k:
                break

    return result
