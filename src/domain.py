"""运行时领域模型：检索候选、拒答特征、引用校验。

与 evaluation/schema.py 的区别：
- evaluation/schema.py 是"标注者写入、runner 读取"的评测数据契约
- 本模块是"检索/生成链路传递"的运行时类型，携带各通道原始分数和融合状态
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class RetrievalCandidate:
    """检索候选，保留各通道原始分数和融合分数。

    各通道分数为 None 表示该通道未召回此候选。
    """

    index: int  # 在 collection 中的原始位置
    chunk_id: str
    source_id: str
    source_name: str

    # 各通道原始分数
    dense_similarity: float | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    graph_score: float | None = None
    rerank_score: float | None = None

    # 各通道排名
    dense_rank: int | None = None
    bm25_rank: int | None = None
    rrf_rank: int | None = None

    def with_scores(
        self,
        *,
        rrf_score: float | None = None,
        rrf_rank: int | None = None,
        rerank_score: float | None = None,
    ) -> RetrievalCandidate:
        """返回更新了指定分数的新候选（frozen dataclass 不可变，用 replace）。"""
        return replace(
            self,
            rrf_score=rrf_score if rrf_score is not None else self.rrf_score,
            rrf_rank=rrf_rank if rrf_rank is not None else self.rrf_rank,
            rerank_score=rerank_score if rerank_score is not None else self.rerank_score,
        )


@dataclass(frozen=True)
class RefusalFeatures:
    """拒答判断的可解释特征。

    每个特征都有明确的业务含义，便于调试和阈值调优。
    """

    top_score: float  # reranker 最高分（若有）或 RRF 最高分
    top1_top2_margin: float  # top1 与 top2 的分数差
    effective_source_count: int  # 有效来源数（score > 0 的不同来源）
    query_length: int  # 查询长度
    has_cjk: bool  # 是否含中文
    max_dense_similarity: float  # dense 通道最高相似度
    max_bm25_score: float  # BM25 通道最高分


@dataclass
class CitationValidation:
    """引用校验结果。"""

    valid_ids: set[str]  # 合法引用 ID
    invalid_ids: set[str]  # 非法引用 ID
    repaired: bool = False  # 是否经过修复
    repair_success: bool = False  # 修复是否成功
    unverified: bool = False  # 是否标记为不可验证


def compute_context_k(
    candidates: list[RetrievalCandidate],
    token_budget: int = 3000,
    avg_chunk_tokens: int = 200,
    min_k: int = 3,
    max_k: int = 10,
) -> int:
    """基于 token budget 计算实际进入 prompt 的候选数。

    token_budget: LLM context 中分配给检索证据的 token 预算（默认 3000，约 4K 字符）
    avg_chunk_tokens: 每个 chunk 的平均 token 数（默认 200，基于 DEFAULT_CHUNK_SIZE=500 字符 ÷ ~2.5 字符/token）
    """
    budget_k = max(min_k, min(max_k, token_budget // avg_chunk_tokens))
    return min(len(candidates), budget_k)
