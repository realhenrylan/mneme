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


# ── 拒答特征提取与判断 ──

import re

from src.domain import RefusalFeatures


_CJK_RE = re.compile(r'[\u4e00-\u9fff]')


def extract_refusal_features(
    candidates: list[RetrievalCandidate],
    query: str,
) -> RefusalFeatures:
    """从检索候选中提取可解释拒答特征。

    每个特征都有明确的业务含义，便于调试和阈值调优：
    - top_score: 最高相关性分数（reranker 或 RRF）
    - top1_top2_margin: top1 与 top2 的分数差，差值大说明 top1 独占优势
    - effective_source_count: 有效来源数（有分数的不同来源）
    - query_length: 查询长度
    - has_cjk: 是否含中文（中文查询可能需要更宽松的阈值）
    - max_dense_similarity: dense 通道最高相似度
    - max_bm25_score: BM25 通道最高分
    """
    if not candidates:
        return RefusalFeatures(
            top_score=0.0,
            top1_top2_margin=0.0,
            effective_source_count=0,
            query_length=len(query),
            has_cjk=bool(_CJK_RE.search(query)),
            max_dense_similarity=0.0,
            max_bm25_score=0.0,
        )

    # top_score：优先用 rerank_score，否则用 rrf_score
    scores = []
    for c in candidates:
        score = c.rerank_score if c.rerank_score is not None else c.rrf_score
        if score is not None:
            scores.append(score)

    top_score = max(scores) if scores else 0.0
    top1_top2_margin = 0.0
    if len(scores) >= 2:
        sorted_scores = sorted(scores, reverse=True)
        top1_top2_margin = sorted_scores[0] - sorted_scores[1]

    # 有效来源数
    effective_sources = set()
    for c in candidates:
        score = c.rerank_score if c.rerank_score is not None else c.rrf_score
        if score is not None and score > 0:
            effective_sources.add(c.source_id or c.source_name)

    # 各通道最高分
    dense_scores = [c.dense_similarity for c in candidates if c.dense_similarity is not None]
    bm25_scores = [c.bm25_score for c in candidates if c.bm25_score is not None]

    return RefusalFeatures(
        top_score=top_score,
        top1_top2_margin=top1_top2_margin,
        effective_source_count=len(effective_sources),
        query_length=len(query),
        has_cjk=bool(_CJK_RE.search(query)),
        max_dense_similarity=max(dense_scores) if dense_scores else 0.0,
        max_bm25_score=max(bm25_scores) if bm25_scores else 0.0,
    )


def should_refuse_with_features(
    features: RefusalFeatures,
    rrf_threshold: float = 0.015,
    reranker_threshold: float = 0.3,
    has_reranker: bool = False,
) -> bool:
    """基于可解释特征判断是否拒答。

    决策逻辑：
    1. 如果有 reranker 分数（has_reranker=True），使用 reranker_threshold（默认 0.3）
    2. 否则使用 RRF 分数和 rrf_threshold（默认 0.015）
    3. 无候选时直接拒答

    注意：rrf_threshold 从 0.03 降至 0.015，配合 RRF k=60 的修改，
    使得拒答在合理场景下能真正触发。

    Args:
        features: 拒答特征
        rrf_threshold: RRF 分数拒答阈值
        reranker_threshold: Reranker 分数拒答阈值
        has_reranker: 是否启用了 reranker

    Returns:
        True 表示应拒答
    """
    if features.effective_source_count == 0:
        return True

    if has_reranker:
        return features.top_score < reranker_threshold

    # 否则用 RRF 阈值
    return features.top_score < rrf_threshold
