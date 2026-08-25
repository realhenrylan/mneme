"""Phase 6-C1 实验性跨文档检索策略（显式 opt-in，绝不进入默认产品路径）。

本模块提供确定性、可审计、无 LLM 的检索消融策略。默认产品检索
（``src.rag.retrieve_hybrid_with_sources`` / ``src.rag.rrf_merge`` 等）
不引用本模块的任何符号；候选策略只能由评测脚本显式按名称调用。

候选策略 ``mechanical-clause-rrf`` v1.0 的设计（Phase 6-C1）：
- **variant 生成**：``generate_query_variants`` 只从原 query 机械提取——
  variants[0] 恒为完整 query，之后依次是强分句（``。！？；!?;`` 与换行）、
  长句（> ``weak_split_threshold`` 字）的弱分句（``，,、``）、中英语言
  边界段（与产品拆解提示同款规则，如 "LLMs for mobility 这篇文章…" 拆为
  "LLMs for mobility" 与 "这篇文章…"）。每个 variant 都是原 query 的字面
  子串——不生成任何新语义文本；去重、非空、按出现顺序、上限
  ``max_variants``。
- **检索**：逐 variant 调用产品检索核心 ``retrieve_hybrid_with_sources``
  （同一 embedding 模型 / Chroma cosine / BM25 CJK n-gram / RRF k=60）。
- **融合**：``fuse_variant_lists`` 跨 variant 做 RRF（k=60，与产品一致）。
  单 variant 时原样透传（保持产品稳定排序，因此 single-query 臂与既有
  基线 runner 逐字节一致）；≥2 variants 时稳定 tie-break 按 ``chunk_id``
  升序；每个结果保留来自哪些 variant 的 rank/score provenance。
- **fail-closed**：``get_strategy`` 对未知策略抛 ``ValueError``，绝不悄悄
  回退或改变默认策略。

v2.0.11 冻结 draft 无 previous-turn 文本字段（仅 chain_id/turn 元数据），
因此本策略的 variant 只来源于原 query——此限制已如实记录于评测产物。

基线臂策略 ``single-query``：variants = [query]，即既有产品检索行为，
用于同 harness 对照并证明 harness 不扰动默认路径。
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

# ── 策略注册表（显式名称 / 版本 / 参数）──────────────────────────────

STRATEGIES: dict[str, dict] = {
    "single-query": {
        "name": "single-query",
        "version": "1.0",
        "no_llm": True,
        "mechanism": "完整原 query 单次检索——即既有产品检索行为"
                     "（dense + BM25 + RRF k=60），作为消融基线臂",
        "params": {},
    },
    "mechanical-clause-rrf": {
        "name": "mechanical-clause-rrf",
        "version": "1.0",
        "no_llm": True,
        "mechanism": "从原 query 机械提取字面子串 variants（完整 query + "
                     "强分句 + 长句弱分句 + 中英语言边界段），逐 variant "
                     "复用产品检索核心，跨 variant RRF(k=60) 融合，"
                     "tie-break 按 chunk_id 升序；保留每个结果的 "
                     "source/citation 身份与 variant provenance",
        "params": {
            "max_variants": 8,
            "weak_split_threshold": 60,
            "rrf_k": 60,
            "top_k": 70,
            "tie_break": "chunk_id_asc",
            "split_delimiters": "strong=。！？；!?;+换行；weak=，,、；"
                                "语言边界=CJK/非CJK 最大连续段",
        },
    },
}

# 稳定分句分隔符（机械、可解释；与产品拆解提示的分句风格一致）
_STRONG_SPLIT = re.compile(r"[。！？；!?;]|\r?\n")
_WEAK_SPLIT = re.compile(r"[，,、]")
_LANGUAGE_RUNS = re.compile(r"[\u4e00-\u9fff]+|[^\u4e00-\u9fff]+")
_EDGE_PUNCT = re.compile(r"^[\s\W_]+|[\s\W_]+$", re.UNICODE)


def get_strategy(name: str) -> dict:
    """按名称取策略定义；未知名称抛 ValueError（fail-closed）。"""
    if name not in STRATEGIES:
        raise ValueError(
            f"unknown retrieval strategy {name!r}; known: "
            f"{sorted(STRATEGIES)}")
    return STRATEGIES[name]


# ── variant 生成（纯机械，无 LLM / 无网络）───────────────────────────

def generate_query_variants(
    query: str,
    *,
    max_variants: int = 8,
    weak_split_threshold: int = 60,
) -> list[str]:
    """从原 query 机械提取确定性 variants（全部为字面子串）。

    顺序：完整 query → 强分句（按出现顺序）→ 长句弱分句 → 语言边界段。
    去重、非空；空 query 抛 ValueError（fail-closed，不静默）。

    为何这样设计（KISS + 可解释）：
    - variants[0] 恒为完整 query：保底一路完整召回，任何切分都不丢失原意；
    - 强分句是"句子/分句"的自然单位（任务推荐方向）；
    - 弱分句只作用于长句，避免短查询被切成无意义碎片；
    - 语言边界段与产品拆解提示（rag_query_decomposer.py）同款规则，
      对中英混合的 cross-document 查询尤其相关。
    """
    q = query.strip()
    if not q:
        raise ValueError("query is empty — cannot generate variants")
    variants = [q]
    seen = {q}

    def _add(text: str) -> None:
        t = text.strip()
        if t and t != q and t not in seen:
            seen.add(t)
            variants.append(t)

    # 1. 强分句（。！？；!?; + 换行），按出现顺序
    for clause in _STRONG_SPLIT.split(q):
        clause = clause.strip()
        if not clause:
            continue
        if len(clause) > weak_split_threshold:
            # 2. 长句再按弱分隔符切分
            for piece in _WEAK_SPLIT.split(clause):
                _add(piece)
        else:
            _add(clause)

    # 3. 中英语言边界段（CJK / 非 CJK 最大连续段，去标点边缘）
    for run in _LANGUAGE_RUNS.findall(q):
        segment = _EDGE_PUNCT.sub("", run).strip()
        if len(segment) >= 2:
            _add(segment)

    return variants[:max_variants]


# ── 融合（跨 variant RRF；稳定 tie-break）────────────────────────────

def fuse_variant_lists(
    per_variant: list[dict],
    *,
    rrf_k: int = 60,
) -> dict:
    """把逐 variant 的有序结果融合为单一确定性排序。

    Args:
        per_variant: [{"variant", "chunk_ids", "scores", "ranks"}]，
            ranks 为 1-based 位次（与产品 RRF 的 rank 口径一致）。
        rrf_k: RRF 常数，与产品 ``src.rag.rrf_merge`` 默认一致（60）。

    Returns:
        {"chunk_ids": [...], "scores": [...], "provenance": [...]}；
        provenance 每项为
        {"chunk_id", "rrf_score", "variant_ranks": [{"variant_index", "rank"}]}。

    单 variant 时原样透传（保持产品稳定排序，不做 chunk_id 重排）——
    这保证 single-query 臂与既有基线 runner 逐字节一致；tie-break
    只在 ≥2 variants 的合并排序中生效。
    """
    if len(per_variant) == 1:
        v = per_variant[0]
        provenance = [
            {"chunk_id": cid, "rrf_score": float(score),
             "variant_ranks": [
                 {"variant_index": 0, "rank": v["ranks"][cid]}]}
            for cid, score in zip(v["chunk_ids"], v["scores"])
        ]
        return {"chunk_ids": list(v["chunk_ids"]),
                "scores": [float(s) for s in v["scores"]],
                "provenance": provenance}

    rrf_scores: dict[str, float] = {}
    variant_ranks: dict[str, list[dict]] = {}
    for variant_index, v in enumerate(per_variant):
        for rank, cid in enumerate(v["chunk_ids"], start=1):
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (rank + rrf_k)
            variant_ranks.setdefault(cid, []).append(
                {"variant_index": variant_index, "rank": rank})

    # 稳定 tie-break：分数降序，同分按 chunk_id 升序（确定性）
    ordered = sorted(rrf_scores.items(),
                     key=lambda kv: (-kv[1], kv[0]))
    chunk_ids = [cid for cid, _ in ordered]
    scores = [score for _, score in ordered]
    provenance = [
        {"chunk_id": cid, "rrf_score": float(rrf_scores[cid]),
         "variant_ranks": variant_ranks[cid]}
        for cid in chunk_ids
    ]
    return {"chunk_ids": chunk_ids, "scores": scores,
            "provenance": provenance}


# ── 逐 variant 检索（复用产品检索核心）───────────────────────────────

def retrieve_variant_lists(
    query: str,
    variants: list[str],
    index: dict,
    *,
    retrieve_fn: Callable | None = None,
    top_k: int = 70,
) -> list[dict]:
    """逐 variant 调用产品检索核心，返回有序结果（含 1-based rank）。

    默认 ``retrieve_fn`` 为 ``src.rag.retrieve_hybrid_with_sources``
    （dense + BM25 + RRF k=60，与产品完全一致）；测试可注入 fake。
    """
    if retrieve_fn is None:
        from src.rag import retrieve_hybrid_with_sources as retrieve_fn
    metadatas = index["metadatas"]
    per_variant = []
    for variant in variants:
        indices, _, scores = retrieve_fn(
            query=variant,
            model=index["model"],
            collection=index["collection"],
            bm25=index["bm25"],
            documents=index["documents"],
            metadatas=metadatas,
            k=top_k,
        )
        chunk_ids = [metadatas[i]["chunk_id"] for i in indices]
        ranks = {cid: rank for rank, cid in enumerate(chunk_ids, start=1)}
        per_variant.append({
            "variant": variant,
            "chunk_ids": chunk_ids,
            "scores": [float(s) for s in scores],
            "ranks": ranks,
        })
    return per_variant


# ── per-case 指标（与 bl6a 同口径，独立实现避免 scripts 依赖）────────

def _per_case_metrics(retrieved_chunk_ids: list[str],
                      relevant_chunk_ids: set[str],
                      retrieved_source_ids: list[str],
                      relevant_source_ids: set[str]) -> dict[str, float]:
    from evaluation.metrics import recall_at_k, ndcg_at_k, source_recall_at_k
    metrics: dict[str, float] = {}
    for k in (5, 10, 20):
        metrics[f"recall@{k}"] = recall_at_k(
            retrieved_chunk_ids, relevant_chunk_ids, k)
        metrics[f"ndcg@{k}"] = ndcg_at_k(
            retrieved_chunk_ids, relevant_chunk_ids, k)
        metrics[f"source_recall@{k}"] = source_recall_at_k(
            retrieved_source_ids, relevant_source_ids, k)
    for rank, cid in enumerate(retrieved_chunk_ids, start=1):
        if cid in relevant_chunk_ids:
            metrics["mrr"] = 1.0 / rank
            break
    else:
        metrics["mrr"] = 0.0
    return metrics


def run_candidate_retrieval(
    cases: list[dict],
    index: dict,
    *,
    strategy: str = "mechanical-clause-rrf",
    top_k: int = 70,
    rrf_k: int = 60,
    max_variants: int = 8,
    provenance_top_n: int = 200,
    retrieve_fn: Callable | None = None,
) -> list[dict]:
    """对每个 case 运行候选策略检索，返回与基线行同构 + 策略 provenance。

    行字段 = bl6a.run_retrieval 的全部字段（case_id / query / query_type /
    language / should_refuse / relevant ids / retrieved ids / scores /
    retrieval_ms / metrics）加 strategy / strategy_version / variants /
    fusion / provenance。未知策略在**任何检索之前**抛 ValueError。
    """
    spec = get_strategy(strategy)  # fail-closed：先于任何检索
    metadatas = index["metadatas"]
    id_to_meta = {
        meta.get("chunk_id"): meta
        for meta in metadatas if meta.get("chunk_id")
    }
    results: list[dict] = []
    for case in cases:
        query = case["query"]
        variants = ([query] if strategy == "single-query"
                    else generate_query_variants(query, max_variants=max_variants))
        start = time.perf_counter()
        per_variant = retrieve_variant_lists(
            query, variants, index, retrieve_fn=retrieve_fn, top_k=top_k)
        fused = fuse_variant_lists(per_variant, rrf_k=rrf_k)
        retrieval_ms = (time.perf_counter() - start) * 1000.0

        retrieved_chunk_ids = fused["chunk_ids"]
        retrieved_source_ids: list[str] = []
        seen_sources: set[str] = set()
        for cid in retrieved_chunk_ids:
            meta = id_to_meta.get(cid) or {}
            source = meta.get("source_name") or meta.get("source")
            if source and source not in seen_sources:
                seen_sources.add(source)
                retrieved_source_ids.append(source)

        relevant_chunks = set(case["relevant_chunk_ids"])
        relevant_sources = set(case["relevant_source_ids"])
        metrics = (
            _per_case_metrics(
                retrieved_chunk_ids, relevant_chunks,
                retrieved_source_ids, relevant_sources,
            ) if relevant_chunks else {}
        )

        # provenance：每个结果保留 source/citation 身份 + variant 来源
        provenance = []
        for cid, score, entry in zip(
                fused["chunk_ids"], fused["scores"], fused["provenance"]):
            if len(provenance) >= provenance_top_n:
                break
            meta = id_to_meta.get(cid) or {}
            provenance.append({
                "chunk_id": cid,
                "source_id": meta.get("source_id", ""),
                "source_path": meta.get("source_path", ""),
                "source_name": meta.get("source_name", ""),
                "rrf_score": float(score),
                "variant_ranks": entry["variant_ranks"],
            })

        results.append({
            "case_id": case["case_id"],
            "query": query,
            "query_type": case["query_type"],
            "language": case["language"],
            "should_refuse": case["should_refuse"],
            "relevant_chunk_ids": case["relevant_chunk_ids"],
            "relevant_source_ids": case["relevant_source_ids"],
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "retrieved_source_ids": retrieved_source_ids,
            "scores": [float(s) for s in fused["scores"]],
            "retrieval_ms": retrieval_ms,
            "metrics": metrics,
            "strategy": spec["name"],
            "strategy_version": spec["version"],
            "variants": variants,
            "fusion": {
                "rrf_k": rrf_k,
                "top_k": top_k,
                "tie_break": spec["params"].get("tie_break", "chunk_id_asc"),
                "variants_retrieved_counts": [
                    {"variant_index": i, "variant": v["variant"],
                     "retrieved": len(v["chunk_ids"])}
                    for i, v in enumerate(per_variant)
                ],
            },
            "provenance": provenance,
        })
    return results
