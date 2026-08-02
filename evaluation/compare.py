"""Graph RAG 阶段 4 入场评测：受控对比实验框架。

本模块实现评测方案 (plans/GRAPH-RAG-EVALUATION-PLAN-2026-08-02.md) 中的
P0-P3 步骤，核心设计原则：

1. **可比性**：A/B/C 三组共享同一索引、同一 embedding、同一 query
   rewrite/decompose、同一 reranker、同一 LLM 生成；唯一差异是 Graph
   候选通道和 reranker 开关。
2. **真值精确性**：chunk 真值基于 snippet 匹配而非 source 级扩大。
3. **多轮回放**：使用 canonical history 保证 A/B/C 获得相同对话历史。
4. **结果可审计**：每次运行保存 run-manifest、ground-truth-map、per-case
   结果和 summary。

实验组定义
---------
- A — Standard：当前 Standard 检索链路，reranker 关闭
- B — Standard + Reranker：A + 固定 reranker
- C — Standard + Reranker + Graph：B + Graph 候选通道与融合

CLI 契约
--------
::

    # 数据与语料预检
    python -m evaluation.compare --dataset v1 --corpus-dir test_texts --validate-only

    # 开发集检索与 alpha 扫描
    python -m evaluation.compare --phase retrieval --split development \\
        --arms standard standard-rerank graph-rerank \\
        --alpha-grid 1.0 0.9 0.8 0.7 0.6 0.5 --seed 42 \\
        --output results/graph-gate/dev

    # 锁定配置后的完整生成评测
    python -m evaluation.compare --phase generation --split all \\
        --arms standard standard-rerank graph-rerank \\
        --config results/graph-gate/locked-config.json \\
        --repeats-target 3 --seed 42 \\
        --output results/graph-gate/final

    # 独立 holdout
    python -m evaluation.compare --phase full --split holdout \\
        --config results/graph-gate/locked-config.json \\
        --output results/graph-gate/holdout
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from evaluation.schema import (
    EvalCase,
    Language,
    QueryType,
    load_dataset,
    save_dataset,
    split_dataset,
    validate_dataset,
)
from evaluation.metrics import (
    compute_retrieval_metrics,
    compute_stratified_metrics,
    recall_at_k,
    ndcg_at_k,
    source_recall_at_k,
)
from evaluation.citation_metrics import (
    CitationMetrics,
    evaluate_citations,
)


# ── 常量 ─────────────────────────────────────────────────────────────

EVAL_ROOT = Path(__file__).parent
DATASETS_DIR = EVAL_ROOT / "datasets"

# 实验组名称
ARM_STANDARD = "standard"
ARM_STANDARD_RERANK = "standard-rerank"
ARM_GRAPH_RERANK = "graph-rerank"

ALL_ARMS = [ARM_STANDARD, ARM_STANDARD_RERANK, ARM_GRAPH_RERANK]

# Graph 目标切片：cross_document + mixed_intent
GRAPH_TARGET_TYPES = {QueryType.CROSS_DOCUMENT, QueryType.MIXED_INTENT}

# 评测方案版本
COMPARE_VERSION = 1


# ── 数据类 ───────────────────────────────────────────────────────────

@dataclass
class GroundTruthEntry:
    """一条 chunk 真值映射记录。"""
    case_id: str
    source_id: str
    normalized_snippet: str
    matched_chunk_ids: list[str]
    match_method: str  # "exact" | "overlap" | "parent" | "source_fallback" | "unmatched"
    reviewer_status: str  # "auto" | "confirmed" | "needs_review"


@dataclass
class RetrievalCaseResult:
    """单条 case 在单个 arm 上的检索结果。"""
    case_id: str
    arm: str
    query: str
    query_type: str
    language: str
    should_refuse: bool

    # 候选检索层
    candidate_chunk_ids: list[str]
    candidate_source_ids: list[str]
    candidate_scores: list[float]

    # 实际进入 prompt 的 context 层
    context_chunk_ids: list[str]
    context_source_ids: list[str]

    # 真值
    relevant_chunk_ids: set[str]
    relevant_source_ids: set[str]

    # 可选字段
    context_token_count: int | None = None

    # 分阶段延迟 (ms)
    rewrite_ms: float = 0.0
    decompose_ms: float = 0.0
    embedding_ms: float = 0.0
    dense_ms: float = 0.0
    bm25_ms: float = 0.0
    graph_ms: float = 0.0
    rerank_ms: float = 0.0
    context_build_ms: float = 0.0
    total_retrieval_ms: float = 0.0

    # Graph 特有
    graph_query_entities: list[str] = field(default_factory=list)
    graph_lift: bool = False  # B 未召回但 C 召回了 relevant chunk
    graph_pollution: bool = False  # Graph-only 非相关 chunk 挤出了 B 的 relevant chunk

    def candidate_metrics(self, ks: tuple[int, ...] = (5, 10, 20)) -> dict[str, float]:
        """计算候选检索层指标。"""
        metrics: dict[str, float] = {}
        for k in ks:
            metrics[f"recall@{k}"] = recall_at_k(
                self.candidate_chunk_ids, self.relevant_chunk_ids, k,
            )
            metrics[f"ndcg@{k}"] = ndcg_at_k(
                self.candidate_chunk_ids, self.relevant_chunk_ids, k,
            )
            metrics[f"source_recall@{k}"] = source_recall_at_k(
                self.candidate_source_ids, self.relevant_source_ids, k,
            )
        # MRR
        for rank, cid in enumerate(self.candidate_chunk_ids, start=1):
            if cid in self.relevant_chunk_ids:
                metrics["mrr"] = 1.0 / rank
                break
        else:
            metrics["mrr"] = 0.0
        return metrics

    def context_metrics(self) -> dict[str, float]:
        """计算 context 层指标。"""
        if not self.relevant_chunk_ids:
            return {"context_recall": 0.0, "context_precision": 0.0}
        context_set = set(self.context_chunk_ids)
        if not context_set:
            return {"context_recall": 0.0, "context_precision": 0.0}
        # context recall: relevant chunks 中有多少出现在 context 中
        recalled = len(context_set & self.relevant_chunk_ids)
        context_recall = recalled / len(self.relevant_chunk_ids)
        # context precision: context 中有多少是 relevant 的
        relevant_in_context = len(context_set & self.relevant_chunk_ids)
        context_precision = relevant_in_context / len(context_set) if context_set else 0.0
        return {"context_recall": context_recall, "context_precision": context_precision}


@dataclass
class GenerationCaseResult:
    """单条 case 在单个 arm 上的生成结果。"""
    case_id: str
    arm: str
    query: str
    query_type: str
    language: str
    should_refuse: bool

    # 生成结果
    answer: str
    context: str  # 截断存储

    # 引用指标
    citation_id_validity: float = 0.0
    citation_precision: float = 0.0
    citation_recall: float = 0.0
    faithfulness: float = 0.0
    correctly_refused: bool | None = None

    # 答案要点覆盖率
    answer_point_coverage: float = 0.0

    # Token 使用
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    # 延迟 (ms)
    total_ms: float = 0.0
    retrieval_ms: float = 0.0
    generation_ms: float = 0.0
    ttft_ms: float | None = None

    # 错误
    error: str | None = None


# ── Chunk 真值映射 ──────────────────────────────────────────────────

def _normalize_text(text: str) -> str:
    """规范化文本用于匹配：去除多余空白、统一标点。"""
    import re
    # 压缩连续空白
    text = re.sub(r'\s+', ' ', text)
    # 统一中文标点
    text = text.replace('，', ',').replace('。', '.').replace('：', ':')
    text = text.replace('；', ';').replace('！', '!').replace('？', '?')
    return text.strip().lower()


def _char_bigrams(text: str) -> set[str]:
    """提取字符级 bigram 集合，用于中文友好的文本相似度计算。

    空格分词对中文效果差，bigram 能更好地捕捉字符级重叠。
    """
    # 去除空白后取相邻字符对
    cleaned = text.replace(" ", "")
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[i:i+2] for i in range(len(cleaned) - 1)}


def _meta_matches_source(meta: dict, source_id: str) -> bool:
    """检查 metadata 是否属于指定 source。

    数据集中 source_id 是文件名（如 '南京城市地理环境.docx'），
    而索引中 metadata.source_id 是 SHA-256 hash，metadata.source_name
    和 metadata.source 才是文件名。因此需要多字段匹配。
    """
    for key in ("source_name", "source", "source_id", "source_path"):
        val = meta.get(key, "")
        if val and val == source_id:
            return True
    return False


def match_snippet_to_chunks(
    snippet: str,
    source_id: str,
    all_metadatas: list[dict],
    all_docs: list[str],
) -> tuple[list[str], str]:
    """将标注片段匹配到具体 chunk ID。

    匹配优先级：
    1. 规范化后的 snippet 完整包含在 chunk 文本中
    2. 同 source/page/section 内的 token overlap
    3. 无唯一匹配时返回 source_fallback

    Returns:
        (matched_chunk_ids, match_method)
    """
    norm_snippet = _normalize_text(snippet)
    if not norm_snippet:
        return [], "unmatched"

    # 优先级 1：snippet 完整包含在 chunk 文本中
    exact_matches: list[str] = []
    for idx, meta in enumerate(all_metadatas):
        if not _meta_matches_source(meta, source_id):
            continue
        chunk_id = meta.get("chunk_id", f"chunk_{idx}")
        chunk_text = _normalize_text(all_docs[idx]) if idx < len(all_docs) else ""
        if norm_snippet in chunk_text:
            exact_matches.append(chunk_id)

    if exact_matches:
        return exact_matches, "exact"

    # 优先级 2：字符级 bigram overlap（对中文更友好）
    overlap_matches: list[str] = []
    best_overlap = 0.0
    snippet_bigrams = _char_bigrams(norm_snippet)

    for idx, meta in enumerate(all_metadatas):
        if not _meta_matches_source(meta, source_id):
            continue
        chunk_text = _normalize_text(all_docs[idx]) if idx < len(all_docs) else ""
        chunk_bigrams = _char_bigrams(chunk_text)
        if not snippet_bigrams or not chunk_bigrams:
            continue
        overlap = len(snippet_bigrams & chunk_bigrams) / len(snippet_bigrams)
        if overlap > best_overlap and overlap >= 0.3:
            best_overlap = overlap
            overlap_matches = [meta.get("chunk_id", f"chunk_{idx}")]
        elif overlap == best_overlap and overlap >= 0.3 and overlap_matches:
            overlap_matches.append(meta.get("chunk_id", f"chunk_{idx}"))

    if overlap_matches:
        return overlap_matches, "overlap"

    # 优先级 3：source fallback — 该 source 下所有 chunk
    # 注意：这是最后的手段，标记为 source_fallback 需要人工审核
    source_chunks: list[str] = []
    for idx, meta in enumerate(all_metadatas):
        if _meta_matches_source(meta, source_id):
            source_chunks.append(meta.get("chunk_id", f"chunk_{idx}"))

    if source_chunks:
        return source_chunks, "source_fallback"

    return [], "unmatched"


def build_ground_truth_map(
    cases: list[EvalCase],
    all_metadatas: list[dict],
    all_docs: list[str],
) -> list[GroundTruthEntry]:
    """为所有 case 构建 chunk 真值映射。

    Returns:
        Ground truth entry 列表，每个 entry 对应一条 relevant_chunk 标注。
    """
    entries: list[GroundTruthEntry] = []
    for case in cases:
        if case.should_refuse:
            continue
        for rc in case.relevant_chunks:
            if not rc.chunk_text_snippet:
                # 无 snippet 的条目：标记为 source_fallback
                source_chunks: list[str] = []
                for idx, meta in enumerate(all_metadatas):
                    if _meta_matches_source(meta, rc.source_id):
                        source_chunks.append(meta.get("chunk_id", f"chunk_{idx}"))
                entries.append(GroundTruthEntry(
                    case_id=case.id,
                    source_id=rc.source_id,
                    normalized_snippet="",
                    matched_chunk_ids=source_chunks,
                    match_method="source_fallback" if source_chunks else "unmatched",
                    reviewer_status="needs_review",
                ))
                continue

            matched_ids, method = match_snippet_to_chunks(
                rc.chunk_text_snippet, rc.source_id, all_metadatas, all_docs,
            )
            entries.append(GroundTruthEntry(
                case_id=case.id,
                source_id=rc.source_id,
                normalized_snippet=_normalize_text(rc.chunk_text_snippet),
                matched_chunk_ids=matched_ids,
                match_method=method,
                reviewer_status="auto" if method == "exact" else "needs_review",
            ))
    return entries


def get_relevant_chunk_ids(
    case: EvalCase,
    ground_truth: dict[str, list[str]],
) -> set[str]:
    """从 ground truth map 获取 case 的 relevant chunk IDs。

    只使用 match_method != "source_fallback" 的精确匹配结果。
    source_fallback 条目从 chunk 级指标分母中排除，但仍进入
    source recall 和答案评测。

    Args:
        case: 评测 case
        ground_truth: case_id -> matched_chunk_ids 映射（已排除 source_fallback）

    Returns:
        relevant chunk ID 集合
    """
    return set(ground_truth.get(case.id, []))


# ── 多轮 canonical history ──────────────────────────────────────────

def build_conversation_chains(cases: list[EvalCase]) -> dict[str, list[EvalCase]]:
    """从 multi_turn case 构建 conversation chains。

    Returns:
        chain_root_id -> ordered list of EvalCase (按 turn 排序)
    """
    multi_cases = [c for c in cases if c.query_type == QueryType.MULTI_TURN]
    # 构建 id -> case 映射
    id_to_case: dict[str, EvalCase] = {c.id: c for c in multi_cases}
    # 找到每个 chain 的根节点 (follow_up_to == None)
    chains: dict[str, list[EvalCase]] = {}
    for c in multi_cases:
        follow_up = c.metadata.get("follow_up_to")
        if not follow_up:
            chains[c.id] = [c]

    # 沿 follow_up_to 链向前追溯
    for c in multi_cases:
        follow_up = c.metadata.get("follow_up_to")
        if follow_up:
            # 找到根节点
            root = follow_up
            visited = {c.id}
            while root in id_to_case:
                parent = id_to_case[root]
                if parent.metadata.get("follow_up_to") is None:
                    break
                if parent.id in visited:
                    break  # 防止循环
                visited.add(parent.id)
                root = parent.metadata.get("follow_up_to", parent.id)
            if root in chains:
                chains[root].append(c)
            else:
                # root 不在 chains 中，可能是中间节点
                # 向上追溯找到真正的根
                real_root = root
                while real_root in id_to_case and id_to_case[real_root].metadata.get("follow_up_to"):
                    next_up = id_to_case[real_root].metadata.get("follow_up_to")
                    if next_up in visited:
                        break
                    visited.add(real_root)
                    real_root = next_up
                chains.setdefault(real_root, [])
                if id_to_case.get(real_root) and id_to_case[real_root] not in chains[real_root]:
                    chains[real_root].insert(0, id_to_case[real_root])
                chains[real_root].append(c)

    # 按 turn 排序
    for root_id in chains:
        chains[root_id].sort(key=lambda c: c.metadata.get("turn", 0))

    return chains


def canonical_history_for_turn(
    chain: list[EvalCase],
    turn_index: int,
    answers: dict[str, str] | None = None,
) -> list[tuple[str, str]]:
    """为多轮 case 构建 canonical history。

    使用预先审核的 canonical prior answer，保证 A/B/C 获得完全相同的历史。

    Args:
        chain: 按 turn 排序的 case 列表
        turn_index: 当前 turn 在 chain 中的索引
        answers: case_id -> canonical answer 映射。
                 若为 None，使用 acceptable_answer_points 拼接作为占位。

    Returns:
        [(query, answer), ...] 历史列表
    """
    history: list[tuple[str, str]] = []
    for i in range(turn_index):
        case = chain[i]
        if answers and case.id in answers:
            answer = answers[case.id]
        else:
            # 占位：用 acceptable_answer_points 拼接
            answer = "；".join(case.acceptable_answer_points) if case.acceptable_answer_points else ""
        history.append((case.query, answer))
    return history


# ── Group-aware split ───────────────────────────────────────────────

def group_aware_split(
    cases: list[EvalCase],
    holdout_ratio: float = 0.12,
    seed: int = 42,
) -> tuple[list[EvalCase], list[EvalCase]]:
    """Group-aware 数据集拆分：同一 conversation chain 整体分配到同一侧。

    在 stratified split 基础上，确保 multi_turn chain 不被拆散。

    Args:
        cases: 完整数据集
        holdout_ratio: holdout 比例
        seed: 随机种子

    Returns:
        (development, holdout) 列表
    """
    import random
    rng = random.Random(seed)

    chains = build_conversation_chains(cases)
    # 收集 chain root IDs
    chain_root_ids: set[str] = set(chains.keys())
    # chain 中所有 case IDs
    chain_case_ids: set[str] = set()
    for chain_cases in chains.values():
        for c in chain_cases:
            chain_case_ids.add(c.id)

    # 非 multi_turn 的 case 直接用 stratified split
    non_multi = [c for c in cases if c.id not in chain_case_ids]
    multi = [c for c in cases if c.id in chain_case_ids]

    # 对非 multi_turn case 做 stratified split
    dev_non_multi, holdout_non_multi = split_dataset(non_multi, holdout_ratio=holdout_ratio, seed=seed)

    # 对 multi_turn chain 整体分配
    chain_roots = list(chain_root_ids)
    rng.shuffle(chain_roots)
    n_holdout_chains = max(1, round(len(chain_roots) * holdout_ratio))
    holdout_chain_ids = set(chain_roots[:n_holdout_chains])

    dev_multi: list[EvalCase] = []
    holdout_multi: list[EvalCase] = []
    for root_id, chain_cases in chains.items():
        if root_id in holdout_chain_ids:
            holdout_multi.extend(chain_cases)
        else:
            dev_multi.extend(chain_cases)

    development = list(dev_non_multi) + dev_multi
    holdout = list(holdout_non_multi) + holdout_multi

    return development, holdout


# ── 答案要点覆盖率 ──────────────────────────────────────────────────

def compute_answer_point_coverage(
    answer: str,
    answer_points: list[str],
) -> float:
    """计算答案要点覆盖率。

    每个 answer_point 检查其关键术语是否出现在答案中。
    覆盖率 = 被覆盖的要点数 / 总要点数。

    Args:
        answer: LLM 生成的答案
        answer_points: 标注的可接受答案要点

    Returns:
        覆盖率 [0, 1]
    """
    if not answer_points:
        return 1.0  # 无要点则 vacuously 满分

    from evaluation.citation_metrics import _extract_key_terms
    answer_lower = answer.lower()
    covered = 0
    for point in answer_points:
        terms = _extract_key_terms(point)
        if not terms:
            covered += 1
            continue
        # 至少一半关键术语出现在答案中
        found = sum(1 for t in terms if t in answer_lower)
        if found >= len(terms) * 0.5:
            covered += 1
    return covered / len(answer_points)


# ── 受控检索管线 ────────────────────────────────────────────────────

def _run_retrieval_arm(
    case: EvalCase,
    arm: str,
    model,
    collection,
    bm25,
    all_docs: list[str],
    all_metadatas: list[dict],
    kg=None,
    alpha: float = 0.7,
    history: list[tuple[str, str]] | None = None,
    ground_truth_chunk_ids: set[str] | None = None,
    b_context_chunk_ids: set[str] | None = None,
) -> RetrievalCaseResult:
    """运行单个 arm 的检索管线。

    A/B/C 三组共享：query rewrite、decompose、embedding、原查询保底召回。
    差异仅在：
    - A: 无 reranker，无 Graph
    - B: 有 reranker，无 Graph
    - C: 有 reranker，有 Graph

    Args:
        case: 评测 case
        arm: 实验组名称
        model: embedding 模型
        collection: ChromaDB collection
        bm25: BM25 索引
        all_docs: 全部文档文本
        all_metadatas: 全部文档元数据
        kg: KnowledgeGraph 实例（仅 C 组使用）
        alpha: Graph 融合权重（仅 C 组使用）
        history: 多轮对话历史
        ground_truth_chunk_ids: 精确 chunk 真值
        b_context_chunk_ids: B 组的 context chunk IDs（用于计算 Graph lift/pollution）
    """
    from src.rag import (
        retrieve_hybrid_with_sources,
        dynamic_top_k,
        retrieval_refused,
        enrich_context,
        _build_context,
        _get_reranker,
        expand_with_parent,
        expand_with_adjacent,
        apply_source_diversity,
    )
    from src.rag_query_rewriter import rewrite_query_llm, merge_rewrite_results
    from src.rag_query_decomposer import decompose_query_llm
    from src.domain import RetrievalCandidate, compute_context_k
    from src.citations import make_citation_records

    t_start = time.perf_counter()

    # ── Step 1: Query rewrite（A/B/C 共享） ──
    t0 = time.perf_counter()
    rewritten_query, rewrite_log = rewrite_query_llm(case.query, history=history)
    rewrite_ms = (time.perf_counter() - t0) * 1000

    # ── Step 2: Query decompose（A/B/C 共享） ──
    t0 = time.perf_counter()
    sub_queries = decompose_query_llm(rewritten_query)
    if not sub_queries:
        sub_queries = [rewritten_query]
    decompose_ms = (time.perf_counter() - t0) * 1000

    # ── Step 3: 子查询并发检索（A/B/C 共享基础检索） ──
    from concurrent.futures import ThreadPoolExecutor, as_completed
    all_entries: list[tuple[int, float]] = []
    with ThreadPoolExecutor(max_workers=min(4, len(sub_queries))) as executor:
        futures = {
            executor.submit(
                retrieve_hybrid_with_sources,
                sq, model, collection, bm25, all_docs, all_metadatas,
            ): sq for sq in sub_queries
        }
        for future in as_completed(futures):
            indices, _, scores = future.result()
            for idx, score in zip(indices, scores):
                all_entries.append((idx, score))

    # 按 chunk 去重：仅保留每个 chunk 的最高分
    best_score: dict[int, float] = {}
    for idx, score in all_entries:
        if idx not in best_score or score > best_score[idx]:
            best_score[idx] = score

    # ── Step 4: 漂移防护（A/B/C 共享） ──
    if rewrite_log.get("changed"):
        orig_indices, _, orig_scores = retrieve_hybrid_with_sources(
            case.query, model, collection, bm25, all_docs, all_metadatas,
        )
        orig_score_map: dict[int, float] = {}
        for idx, score in zip(orig_indices, orig_scores):
            orig_score_map[idx] = score
        merged_indices, best_score, merge_log = merge_rewrite_results(
            list(best_score.keys()), best_score,
            orig_indices, orig_score_map,
        )
        merged = merged_indices
        scores_flat = sorted(best_score.values(), reverse=True)
    else:
        merged = sorted(best_score.keys(), key=lambda i: best_score[i], reverse=True)
        scores_flat = sorted(best_score.values(), reverse=True)

    # ── Step 5: Graph 增强检索（仅 C 组） ──
    graph_ms = 0.0
    graph_query_entities: list[str] = []
    if arm == ARM_GRAPH_RERANK and kg is not None:
        t0 = time.perf_counter()
        from src.graph_rag import graph_augmented_retrieve
        # 用已检索的语义结果 + Graph 扩展做融合
        graph_indices, graph_docs, graph_scores = graph_augmented_retrieve(
            case.query, model, collection, bm25, all_docs, kg,
            alpha=alpha, verbose=False, all_metadatas=all_metadatas,
        )
        # 用 Graph 结果替换之前的检索结果
        # 重新构建 best_score
        best_score = {}
        for idx, score in zip(graph_indices, graph_scores):
            if idx not in best_score or score > best_score[idx]:
                best_score[idx] = score
        merged = sorted(best_score.keys(), key=lambda i: best_score[i], reverse=True)
        scores_flat = sorted(best_score.values(), reverse=True)
        graph_ms = (time.perf_counter() - t0) * 1000

        # 提取查询实体（用于诊断）
        try:
            from src.graph_rag import extract_entities_from_query
            graph_query_entities = extract_entities_from_query(case.query)
        except Exception:
            pass

    # ── Step 6: Dynamic Top-K ──
    k = dynamic_top_k(scores_flat)
    top_indices = merged[:k]

    # ── Step 7: Reranker（B/C 组） ──
    rerank_ms = 0.0
    if arm in (ARM_STANDARD_RERANK, ARM_GRAPH_RERANK):
        t0 = time.perf_counter()
        reranker = _get_reranker()
        if reranker is not None:
            candidates = [
                RetrievalCandidate(
                    index=i,
                    chunk_id=(all_metadatas[i] or {}).get("chunk_id", f"chunk_{i}"),
                    source_id=(all_metadatas[i] or {}).get("source_id", ""),
                    source_name=(all_metadatas[i] or {}).get("source_name", "")
                        or (all_metadatas[i] or {}).get("source", ""),
                    rrf_score=best_score.get(i),
                )
                for i in top_indices
            ]
            reranked = reranker.rerank(case.query, candidates, top_k=min(k, 20))
            reranked = apply_source_diversity(reranked, max_per_source=3, top_k=min(k, 20))
            top_indices = [c.index for c in reranked]
        rerank_ms = (time.perf_counter() - t0) * 1000

    # ── Step 8: Context enrichment + Parent-Child + Adjacent ──
    t0 = time.perf_counter()
    enriched_docs = enrich_context(top_indices, all_docs, all_metadatas)
    context_k = compute_context_k(
        [RetrievalCandidate(index=i, chunk_id="", source_id="", source_name="")
         for i in top_indices],
    )
    top_indices, _ = expand_with_parent(top_indices, enriched_docs, all_metadatas, context_k)
    top_indices = expand_with_adjacent(top_indices, all_metadatas, max_expand=2)
    context_k = compute_context_k(
        [RetrievalCandidate(index=i, chunk_id="", source_id="", source_name="")
         for i in top_indices],
    )
    context = _build_context(top_indices, enriched_docs, all_metadatas, context_k=context_k)
    context_build_ms = (time.perf_counter() - t0) * 1000

    total_retrieval_ms = (time.perf_counter() - t_start) * 1000

    # ── 提取 chunk IDs 和 source IDs ──
    # 候选检索层（dynamic_top_k 之前）
    candidate_chunk_ids: list[str] = []
    candidate_source_ids: list[str] = []
    seen_sources: set[str] = set()
    for idx in merged[:70]:  # 最多 70 个候选
        meta = all_metadatas[idx] if idx < len(all_metadatas) else {}
        candidate_chunk_ids.append(meta.get("chunk_id", f"chunk_{idx}"))
        source_id = meta.get("source_id") or meta.get("source_name") or meta.get("source", "")
        if source_id and source_id not in seen_sources:
            candidate_source_ids.append(source_id)
            seen_sources.add(source_id)

    # Context 层（实际进入 prompt 的）
    context_chunk_ids: list[str] = []
    context_source_ids: list[str] = []
    seen_ctx_sources: set[str] = set()
    for idx in top_indices[:context_k]:
        meta = all_metadatas[idx] if idx < len(all_metadatas) else {}
        context_chunk_ids.append(meta.get("chunk_id", f"chunk_{idx}"))
        source_id = meta.get("source_id") or meta.get("source_name") or meta.get("source", "")
        if source_id and source_id not in seen_ctx_sources:
            context_source_ids.append(source_id)
            seen_ctx_sources.add(source_id)

    # ── Graph lift / pollution 计算 ──
    graph_lift = False
    graph_pollution = False
    if arm == ARM_GRAPH_RERANK and ground_truth_chunk_ids is not None and b_context_chunk_ids is not None:
        ctx_set = set(context_chunk_ids)
        # Graph lift: B 未将 relevant chunk 放入 context，C 成功放入
        if b_context_chunk_ids and ground_truth_chunk_ids:
            b_missed = ground_truth_chunk_ids - b_context_chunk_ids
            if b_missed and (b_missed & ctx_set):
                graph_lift = True
        # Graph pollution: Graph-only 非相关 chunk 进入 context，挤出 B 的 relevant chunk
        if b_context_chunk_ids:
            b_relevant_in_ctx = b_context_chunk_ids & ground_truth_chunk_ids
            c_relevant_in_ctx = ctx_set & ground_truth_chunk_ids
            if b_relevant_in_ctx and len(c_relevant_in_ctx) < len(b_relevant_in_ctx):
                graph_pollution = True

    # 估算 context token 数
    context_token_count = None
    if context:
        # 粗略估算：中文约 1.5 token/char，英文约 0.25 token/word
        context_token_count = len(context) // 2

    return RetrievalCaseResult(
        case_id=case.id,
        arm=arm,
        query=case.query,
        query_type=case.query_type.value,
        language=case.language.value,
        should_refuse=case.should_refuse,
        candidate_chunk_ids=candidate_chunk_ids,
        candidate_source_ids=candidate_source_ids,
        candidate_scores=scores_flat[:len(candidate_chunk_ids)],
        context_chunk_ids=context_chunk_ids,
        context_source_ids=context_source_ids,
        context_token_count=context_token_count,
        relevant_chunk_ids=ground_truth_chunk_ids or set(),
        relevant_source_ids=set(case.relevant_source_ids),
        rewrite_ms=rewrite_ms,
        decompose_ms=decompose_ms,
        graph_ms=graph_ms,
        rerank_ms=rerank_ms,
        context_build_ms=context_build_ms,
        total_retrieval_ms=total_retrieval_ms,
        graph_query_entities=graph_query_entities,
        graph_lift=graph_lift,
        graph_pollution=graph_pollution,
    )


# ── 受控生成管线 ────────────────────────────────────────────────────

def _run_generation_arm(
    case: EvalCase,
    arm: str,
    model,
    collection,
    bm25,
    all_docs: list[str],
    all_metadatas: list[dict],
    kg=None,
    alpha: float = 0.7,
    history: list[tuple[str, str]] | None = None,
    ground_truth_chunk_ids: set[str] | None = None,
    retrieval_result: RetrievalCaseResult | None = None,
) -> GenerationCaseResult:
    """运行单个 arm 的完整生成管线。

    调用与生产一致的 answer_query() 接口，而非自行拼装简化链路。
    """
    from src.rag import answer_query, answer_with_llm_history
    from src.citations import make_citation_records, referenced_citation_ids

    t_start = time.perf_counter()

    try:
        # 调用生产管线
        # A 组：关闭 reranker
        # B/C 组：开启 reranker
        # C 组额外传入 kg 和 alpha
        if arm == ARM_STANDARD:
            # 临时关闭 reranker
            import src.rag as rag_module
            original_reranker_mode = rag_module.RAG_RERANKER_MODE
            rag_module.RAG_RERANKER_MODE = "none"
            rag_module._RERANKER_INSTANCE = None
            try:
                answer, sources = answer_query(
                    case.query, model, collection, bm25,
                    all_docs, all_metadatas,
                    history=history,
                )
            finally:
                rag_module.RAG_RERANKER_MODE = original_reranker_mode
                rag_module._RERANKER_INSTANCE = None
        elif arm == ARM_STANDARD_RERANK:
            # 确保 reranker 开启
            import src.rag as rag_module
            original_reranker_mode = rag_module.RAG_RERANKER_MODE
            rag_module.RAG_RERANKER_MODE = "cross-encoder"
            rag_module._RERANKER_INSTANCE = None
            try:
                answer, sources = answer_query(
                    case.query, model, collection, bm25,
                    all_docs, all_metadatas,
                    history=history,
                )
            finally:
                rag_module.RAG_RERANKER_MODE = original_reranker_mode
                rag_module._RERANKER_INSTANCE = None
        elif arm == ARM_GRAPH_RERANK:
            # C 组：使用 Graph 增强检索 + reranker
            # 需要调用 graph_augmented_retrieve 替换标准检索
            # 但仍保留 rewrite/decompose/reranker/parent-child/adjacent/citation
            # 这需要走一条特殊路径
            answer, sources = _graph_enhanced_answer_query(
                case.query, model, collection, bm25,
                all_docs, all_metadatas, kg, alpha,
                history=history,
            )
        else:
            raise ValueError(f"Unknown arm: {arm}")

        generation_ms = (time.perf_counter() - t_start) * 1000

        # 计算引用指标
        # 从 sources 中提取 valid citation IDs
        valid_ids: set[str] = set()
        if sources:
            # sources 格式: [S1] filename (p.X; chunk_id=...): snippet...
            import re
            for match in re.finditer(r'\[(S\d+)\]', sources):
                valid_ids.add(match.group(1))

        # 计算 citation metrics
        citation_metrics = evaluate_citations(
            answer=answer,
            valid_ids=valid_ids,
            relevant_chunk_ids=ground_truth_chunk_ids or set(),
            all_retrieved_ids=set(),  # 从 retrieval_result 获取
            answer_points=case.acceptable_answer_points,
            context="",  # 不传 context，避免重复计算
            should_refuse=case.should_refuse,
        )

        # 答案要点覆盖率
        coverage = compute_answer_point_coverage(answer, case.acceptable_answer_points)

        return GenerationCaseResult(
            case_id=case.id,
            arm=arm,
            query=case.query,
            query_type=case.query_type.value,
            language=case.language.value,
            should_refuse=case.should_refuse,
            answer=answer,
            context="",  # 不存储完整 context
            citation_id_validity=citation_metrics.citation_id_validity,
            citation_precision=citation_metrics.citation_precision,
            citation_recall=citation_metrics.citation_recall,
            faithfulness=citation_metrics.faithfulness,
            correctly_refused=citation_metrics.correctly_refused,
            answer_point_coverage=coverage,
            total_ms=generation_ms,
            retrieval_ms=retrieval_result.total_retrieval_ms if retrieval_result else 0.0,
            generation_ms=generation_ms - (retrieval_result.total_retrieval_ms if retrieval_result else 0.0),
        )

    except Exception as e:
        return GenerationCaseResult(
            case_id=case.id,
            arm=arm,
            query=case.query,
            query_type=case.query_type.value,
            language=case.language.value,
            should_refuse=case.should_refuse,
            answer="",
            context="",
            error=str(e),
            total_ms=(time.perf_counter() - t_start) * 1000,
        )


def _graph_enhanced_answer_query(
    query: str,
    model,
    collection,
    bm25,
    documents: list[str],
    metadatas: list[dict],
    kg,
    alpha: float = 0.7,
    history=None,
    temperature: float = 0.1,
) -> tuple[str, str]:
    """Graph 增强的 answer_query：保留完整 Standard 管线步骤，仅替换检索为 Graph 增强。

    与 _graph_rag_answer 的关键区别：
    - 保留 query rewrite、decompose、漂移防护
    - 保留 reranker、source diversity
    - 保留 parent-child 和 adjacent expansion
    - 保留 citation validation
    - 仅在检索阶段用 graph_augmented_retrieve 替换 retrieve_hybrid_with_sources
    """
    from src.rag import (
        dynamic_top_k, retrieval_refused, enrich_context, _build_context,
        _get_reranker, expand_with_parent, expand_with_adjacent,
        apply_source_diversity, format_sources,
        _validate_and_repair_citations,
        REFUSAL_MESSAGE,
    )
    from src.rag_query_rewriter import rewrite_query_llm, merge_rewrite_results
    from src.rag_query_decomposer import decompose_query_llm
    from src.domain import RetrievalCandidate, compute_context_k
    from src.graph_rag import graph_augmented_retrieve
    from concurrent.futures import ThreadPoolExecutor, as_completed

    retrieval_start = time.perf_counter()

    # ── 多轮改写 ──
    rewritten_query, rewrite_log = rewrite_query_llm(query, history=history)

    # ── LLM 查询拆解 ──
    sub_queries = decompose_query_llm(rewritten_query)
    if not sub_queries:
        sub_queries = [rewritten_query]

    # ── 子查询并发检索（Graph 增强） ──
    # 对每个子查询使用 graph_augmented_retrieve
    all_entries: list[tuple[int, float]] = []
    with ThreadPoolExecutor(max_workers=min(4, len(sub_queries))) as executor:
        futures = {
            executor.submit(
                graph_augmented_retrieve,
                sq, model, collection, bm25, documents, kg,
                alpha=alpha, verbose=False, all_metadatas=metadatas,
            ): sq for sq in sub_queries
        }
        for future in as_completed(futures):
            indices, _, scores = future.result()
            for idx, score in zip(indices, scores):
                all_entries.append((idx, score))

    # 按 chunk 去重
    best_score: dict[int, float] = {}
    for idx, score in all_entries:
        if idx not in best_score or score > best_score[idx]:
            best_score[idx] = score

    # ── 漂移防护 ──
    if rewrite_log.get("changed"):
        orig_indices, _, orig_scores = graph_augmented_retrieve(
            query, model, collection, bm25, documents, kg,
            alpha=alpha, verbose=False, all_metadatas=metadatas,
        )
        orig_score_map: dict[int, float] = {}
        for idx, score in zip(orig_indices, orig_scores):
            orig_score_map[idx] = score
        merged_indices, best_score, merge_log = merge_rewrite_results(
            list(best_score.keys()), best_score,
            orig_indices, orig_score_map,
        )
        merged = merged_indices
        scores_flat = sorted(best_score.values(), reverse=True)
    else:
        merged = sorted(best_score.keys(), key=lambda i: best_score[i], reverse=True)
        scores_flat = sorted(best_score.values(), reverse=True)

    k = dynamic_top_k(scores_flat)
    top_indices = merged[:k]

    if retrieval_refused(scores_flat):
        return REFUSAL_MESSAGE, ""

    # ── Reranker ──
    reranker = _get_reranker()
    if reranker is not None:
        candidates = [
            RetrievalCandidate(
                index=i,
                chunk_id=(metadatas[i] or {}).get("chunk_id", f"chunk_{i}"),
                source_id=(metadatas[i] or {}).get("source_id", ""),
                source_name=(metadatas[i] or {}).get("source_name", "")
                    or (metadatas[i] or {}).get("source", ""),
                rrf_score=best_score.get(i),
            )
            for i in top_indices
        ]
        reranked = reranker.rerank(query, candidates, top_k=min(k, 20))
        reranked = apply_source_diversity(reranked, max_per_source=3, top_k=min(k, 20))
        top_indices = [c.index for c in reranked]

    # ── Context enrichment + Parent-Child + Adjacent ──
    enriched_docs = enrich_context(top_indices, documents, metadatas)
    context_k = compute_context_k(
        [RetrievalCandidate(index=i, chunk_id="", source_id="", source_name="")
         for i in top_indices],
    )
    top_indices, _ = expand_with_parent(top_indices, enriched_docs, metadatas, context_k)
    top_indices = expand_with_adjacent(top_indices, metadatas, max_expand=2)
    context_k = compute_context_k(
        [RetrievalCandidate(index=i, chunk_id="", source_id="", source_name="")
         for i in top_indices],
    )
    context = _build_context(top_indices, enriched_docs, metadatas, context_k=context_k)

    # ── LLM 生成 ──
    from src.rag import answer_with_llm_history
    answer = answer_with_llm_history(query, context, history or [], temperature=temperature)

    # ── 引用校验 ──
    answer, citation_validation = _validate_and_repair_citations(
        answer, top_indices, enriched_docs, metadatas, context_k,
    )

    sources = format_sources(top_indices, enriched_docs, metadatas, context_k=context_k)
    return answer, sources


# ── Run Manifest ────────────────────────────────────────────────────

def _compute_corpus_hash(corpus_dir: Path, source_files: list[str]) -> str:
    """计算语料文件的 SHA-256 hash。"""
    h = hashlib.sha256()
    for source_id in sorted(source_files):
        candidate = corpus_dir / source_id
        if not candidate.exists():
            # 尝试大小写不敏感匹配
            for f in corpus_dir.iterdir():
                if f.name.lower() == source_id.lower():
                    candidate = f
                    break
        if candidate.exists():
            h.update(candidate.read_bytes())
    return h.hexdigest()[:16]


def _compute_dataset_hash(dataset_path: Path) -> str:
    """计算数据集文件的 SHA-256 hash。"""
    return hashlib.sha256(dataset_path.read_bytes()).hexdigest()[:16]


def build_run_manifest(
    dataset_path: Path,
    corpus_dir: Path,
    source_files: list[str],
    arms: list[str],
    alpha_grid: list[float] | None = None,
    seed: int = 42,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """构建运行 manifest，记录评测环境信息。"""
    import subprocess
    git_commit = "unknown"
    git_dirty = True
    try:
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(EVAL_ROOT.parent),
            stderr=subprocess.DEVNULL,
        ).decode().strip()[:12]
        git_dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=str(EVAL_ROOT.parent),
            stderr=subprocess.DEVNULL,
        ).decode().strip())
    except Exception:
        pass

    manifest = {
        "compare_version": COMPARE_VERSION,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "dataset": dataset_path.name,
        "dataset_hash": _compute_dataset_hash(dataset_path),
        "corpus_hash": _compute_corpus_hash(corpus_dir, source_files),
        "arms": arms,
        "alpha_grid": alpha_grid,
        "seed": seed,
        "config_path": str(config_path) if config_path else None,
    }

    # 模型版本信息
    try:
        from src.rag import EMBEDDING_MODEL_NAME, DEFAULT_LLM_MODEL
        manifest["embedding_model"] = EMBEDDING_MODEL_NAME
        manifest["llm_model"] = os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL)
    except Exception:
        pass

    return manifest


# ── Summary 统计 ────────────────────────────────────────────────────

def compute_summary(
    results: list[RetrievalCaseResult | GenerationCaseResult],
    cases: list[EvalCase],
    arms: list[str],
) -> dict[str, Any]:
    """计算汇总统计。"""
    summary: dict[str, Any] = {
        "compare_version": COMPARE_VERSION,
        "case_count": len(cases),
        "arm_count": len(arms),
    }

    # 按 arm 分组
    by_arm: dict[str, list] = {arm: [] for arm in arms}
    for r in results:
        by_arm[r.arm].append(r)

    # 按 query_type 切片
    type_slices = {
        "graph_target": [c for c in cases if c.query_type in GRAPH_TARGET_TYPES],
        "all_answerable": [c for c in cases if not c.should_refuse],
        "no_answer": [c for c in cases if c.should_refuse],
        "multi_turn": [c for c in cases if c.query_type == QueryType.MULTI_TURN],
        "hard": [c for c in cases if c.metadata.get("difficulty") == "hard"],
    }

    # 按语言切片
    lang_slices = {
        f"lang_{lang.value}": [c for c in cases if c.language == lang]
        for lang in Language
    }

    all_slices = {"overall": cases} | type_slices | lang_slices

    # 对每个 arm 和 slice 计算指标
    for arm in arms:
        arm_results = by_arm[arm]
        if not arm_results:
            continue
        arm_key = arm.replace("-", "_")
        summary[arm_key] = {}

        for slice_name, slice_cases in all_slices.items():
            slice_ids = {c.id for c in slice_cases}
            slice_results = [r for r in arm_results if r.case_id in slice_ids]
            if not slice_results:
                continue

            if isinstance(slice_results[0], RetrievalCaseResult):
                # 检索指标
                retrieved = [r.candidate_chunk_ids for r in slice_results]
                relevant = [r.relevant_chunk_ids for r in slice_results]
                metrics = compute_retrieval_metrics(retrieved, relevant)

                # Context 指标
                ctx_recalls = [r.context_metrics()["context_recall"] for r in slice_results]
                ctx_precisions = [r.context_metrics()["context_precision"] for r in slice_results]
                metrics["context_recall"] = sum(ctx_recalls) / len(ctx_recalls) if ctx_recalls else 0.0
                metrics["context_precision"] = sum(ctx_precisions) / len(ctx_precisions) if ctx_precisions else 0.0

                # 延迟
                latencies = [r.total_retrieval_ms for r in slice_results]
                latencies_sorted = sorted(latencies)
                metrics["retrieval_ms_p50"] = latencies_sorted[len(latencies_sorted) // 2] if latencies_sorted else 0.0
                metrics["retrieval_ms_p95"] = latencies_sorted[int(len(latencies_sorted) * 0.95)] if len(latencies_sorted) >= 2 else latencies_sorted[-1] if latencies_sorted else 0.0

                # Graph 特有
                if arm == ARM_GRAPH_RERANK:
                    lift_count = sum(1 for r in slice_results if r.graph_lift)
                    pollution_count = sum(1 for r in slice_results if r.graph_pollution)
                    metrics["graph_lift_rate"] = lift_count / len(slice_results) if slice_results else 0.0
                    metrics["graph_pollution_rate"] = pollution_count / len(slice_results) if slice_results else 0.0

                summary[arm_key][slice_name] = metrics

            elif isinstance(slice_results[0], GenerationCaseResult):
                # 生成指标
                gen_metrics: dict[str, float] = {}
                coverages = [r.answer_point_coverage for r in slice_results if not r.should_refuse]
                gen_metrics["answer_point_coverage"] = sum(coverages) / len(coverages) if coverages else 0.0

                validities = [r.citation_id_validity for r in slice_results]
                gen_metrics["citation_id_validity"] = sum(validities) / len(validities) if validities else 0.0

                # 拒答
                refusal_results = [r for r in slice_results if r.should_refuse]
                if refusal_results:
                    correct = sum(1 for r in refusal_results if r.correctly_refused is True)
                    gen_metrics["false_answer_rate"] = 1.0 - (correct / len(refusal_results))
                answerable = [r for r in slice_results if not r.should_refuse]
                if answerable:
                    false_refusals = sum(1 for r in answerable if r.correctly_refused is False)
                    gen_metrics["false_refusal_rate"] = false_refusals / len(answerable)

                # 延迟
                latencies = [r.total_ms for r in slice_results]
                latencies_sorted = sorted(latencies)
                gen_metrics["total_ms_p50"] = latencies_sorted[len(latencies_sorted) // 2] if latencies_sorted else 0.0
                gen_metrics["total_ms_p95"] = latencies_sorted[int(len(latencies_sorted) * 0.95)] if len(latencies_sorted) >= 2 else latencies_sorted[-1] if latencies_sorted else 0.0

                # Token
                tokens = [r.total_tokens for r in slice_results if r.total_tokens is not None]
                gen_metrics["total_tokens_avg"] = sum(tokens) / len(tokens) if tokens else 0.0

                # 错误率
                errors = sum(1 for r in slice_results if r.error is not None)
                gen_metrics["error_rate"] = errors / len(slice_results) if slice_results else 0.0

                summary[arm_key][slice_name] = gen_metrics

    # 配对差值 (C - B)
    if ARM_GRAPH_RERANK in arms and ARM_STANDARD_RERANK in arms:
        c_results = by_arm.get(ARM_GRAPH_RERANK, [])
        b_results = by_arm.get(ARM_STANDARD_RERANK, [])
        if c_results and b_results:
            # 按 case_id 配对
            b_by_id = {r.case_id: r for r in b_results}
            paired_deltas: dict[str, dict] = {}
            for slice_name, slice_cases in all_slices.items():
                slice_ids = {c.id for c in slice_cases}
                deltas: list[float] = []
                for c_r in c_results:
                    if c_r.case_id not in slice_ids:
                        continue
                    b_r = b_by_id.get(c_r.case_id)
                    if b_r is None:
                        continue
                    if isinstance(c_r, RetrievalCaseResult) and isinstance(b_r, RetrievalCaseResult):
                        c_recall = c_r.context_metrics()["context_recall"]
                        b_recall = b_r.context_metrics()["context_recall"]
                        deltas.append(c_recall - b_recall)
                if deltas:
                    paired_deltas[slice_name] = {
                        "mean_delta": sum(deltas) / len(deltas),
                        "n_pairs": len(deltas),
                    }
            summary["paired_cb"] = paired_deltas

    return summary


# ── 保存结果 ────────────────────────────────────────────────────────

def _json_default(obj: Any) -> Any:
    """JSON 序列化非标准类型。"""
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def save_results(
    output_dir: Path,
    manifest: dict[str, Any],
    ground_truth: list[GroundTruthEntry],
    per_case_results: list,
    summary: dict[str, Any],
) -> None:
    """保存评测结果到目录。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    # run-manifest.json
    with open(output_dir / "run-manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, default=_json_default)

    # ground-truth-map.json
    gt_data = [asdict(e) for e in ground_truth]
    with open(output_dir / "ground-truth-map.json", "w", encoding="utf-8") as f:
        json.dump(gt_data, f, ensure_ascii=False, indent=2, default=_json_default)

    # per-case results (JSONL)
    with open(output_dir / "retrieval-cases.jsonl", "w", encoding="utf-8") as f:
        for r in per_case_results:
            d = asdict(r)
            f.write(json.dumps(d, ensure_ascii=False, default=_json_default) + "\n")

    # summary.json
    with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=_json_default)


# ── CLI ─────────────────────────────────────────────────────────────

def resolve_dataset_path(name: str) -> Path:
    """解析数据集名称到 JSONL 文件路径。"""
    if name.endswith(".jsonl"):
        p = Path(name)
        if p.is_absolute():
            return p
        return DATASETS_DIR / p
    return DATASETS_DIR / f"{name}.jsonl"


def main(argv: list[str] | None = None) -> int:
    """评测对比 CLI 入口。"""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Mneme Graph RAG 阶段 4 入场评测",
    )
    parser.add_argument(
        "--dataset", default="v1",
        help="数据集名称 (e.g. 'v1') 或 JSONL 路径",
    )
    parser.add_argument(
        "--corpus-dir", type=Path, required=True,
        help="语料文件目录",
    )
    parser.add_argument(
        "--phase", choices=["retrieval", "generation", "full"], default="retrieval",
        help="评测阶段：retrieval (仅检索)、generation (检索+生成)、full (完整)",
    )
    parser.add_argument(
        "--split", choices=["development", "holdout", "all"], default="development",
        help="数据集拆分：development / holdout / all",
    )
    parser.add_argument(
        "--arms", nargs="+", default=ALL_ARMS,
        choices=ALL_ARMS,
        help="实验组 (默认: 全部三组)",
    )
    parser.add_argument(
        "--alpha-grid", type=float, nargs="+", default=None,
        help="Alpha 扫描网格 (仅 graph-rerank arm 使用)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="随机种子",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="输出目录",
    )
    parser.add_argument(
        "--config", type=Path, default=None,
        help="锁定配置 JSON 路径 (holdout 运行时必须)",
    )
    parser.add_argument(
        "--repeats-target", type=int, default=1,
        help="目标重复次数 (生成阶段)",
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="仅验证数据集和语料，不运行评测",
    )
    parser.add_argument(
        "--collection-name", default="eval_compare",
        help="ChromaDB collection 名称",
    )

    args = parser.parse_args(argv)
    dataset_path = resolve_dataset_path(args.dataset)

    # ── 验证数据集 ──
    if not dataset_path.exists():
        print(f"Error: Dataset not found: {dataset_path}", file=sys.stderr)
        return 1

    print(f"Loading dataset: {dataset_path}")
    cases = load_dataset(dataset_path)
    print(f"  Loaded {len(cases)} cases")

    warnings = validate_dataset(cases)
    if warnings:
        print(f"\n  ⚠ Dataset validation warnings ({len(warnings)}):")
        for w in warnings:
            print(f"    - {w}")
    else:
        print("  ✓ Dataset validation passed")

    # ── 验证语料 ──
    if not args.corpus_dir.exists():
        print(f"Error: Corpus directory not found: {args.corpus_dir}", file=sys.stderr)
        return 1

    source_files: set[str] = set()
    for case in cases:
        source_files.update(case.relevant_source_ids)

    missing_sources = []
    for source_id in sorted(source_files):
        candidate = args.corpus_dir / source_id
        if not candidate.exists():
            found = any(f.name.lower() == source_id.lower() for f in args.corpus_dir.iterdir())
            if not found:
                missing_sources.append(source_id)

    if missing_sources:
        print(f"\n  ⚠ Missing corpus files ({len(missing_sources)}):")
        for s in missing_sources:
            print(f"    - {s}")

    if args.validate_only:
        # 输出数据集统计
        print(f"\n  Dataset statistics:")
        type_counts: dict[str, int] = {}
        for case in cases:
            type_counts[case.query_type.value] = type_counts.get(case.query_type.value, 0) + 1
        for qt, count in sorted(type_counts.items()):
            print(f"    {qt:20s} {count}")

        # 检查 12 条缺失 chunk 真值
        no_chunk_truth = [
            c for c in cases
            if not c.should_refuse and not c.relevant_chunks
        ]
        if no_chunk_truth:
            print(f"\n  ⚠ {len(no_chunk_truth)} answerable cases without chunk truth:")
            for c in no_chunk_truth:
                print(f"    - {c.id}: {c.query[:60]}")

        # 多轮链检查
        chains = build_conversation_chains(cases)
        print(f"\n  Multi-turn chains: {len(chains)}")
        for root_id, chain in chains.items():
            print(f"    {root_id}: {len(chain)} turns")

        return 0 if not missing_sources else 2

    # ── 数据集拆分 ──
    if args.split == "all":
        dev_cases, holdout_cases = cases, []
    elif args.split == "development":
        dev_cases, holdout_cases = group_aware_split(cases, seed=args.seed)
    else:  # holdout
        _, holdout_cases = group_aware_split(cases, seed=args.seed)
        dev_cases = []

    active_cases = dev_cases if args.split == "development" else holdout_cases if args.split == "holdout" else cases
    print(f"\n  Active cases: {len(active_cases)} ({args.split})")

    # ── 构建索引 ──
    from src.rag import prepare_index

    file_paths: list[str] = []
    for source_id in sorted(source_files):
        candidate = args.corpus_dir / source_id
        if candidate.exists():
            file_paths.append(str(candidate))
        else:
            for f in args.corpus_dir.iterdir():
                if f.name.lower() == source_id.lower():
                    file_paths.append(str(f))
                    break

    print(f"\nBuilding index from {len(file_paths)} source files...")
    model, collection, bm25, all_docs, all_metadatas = prepare_index(
        file_paths, args.collection_name, force_rebuild=True,
    )
    print(f"Index built: {len(all_docs)} chunks")

    # ── 构建 Graph 索引（如果需要） ──
    kg = None
    if ARM_GRAPH_RERANK in args.arms:
        print("\nBuilding Knowledge Graph...")
        from src.graph_rag import KnowledgeGraph
        all_data = collection.get()
        all_ids = all_data["ids"]
        kg = KnowledgeGraph()
        kg.build_from_chunks(all_docs, chunk_ids=all_ids, verbose=True)
        print(f"KG built: {kg.entity_graph.number_of_nodes()} entities, "
              f"{kg.entity_graph.number_of_edges()} edges")

    # ── 构建 ground truth map ──
    print("\nBuilding ground truth map...")
    ground_truth = build_ground_truth_map(cases, all_metadatas, all_docs)
    # 转为 case_id -> chunk_ids 映射（排除 source_fallback）
    gt_map: dict[str, list[str]] = {}
    for entry in ground_truth:
        if entry.match_method not in ("source_fallback", "unmatched"):
            gt_map.setdefault(entry.case_id, []).extend(entry.matched_chunk_ids)
    print(f"  Ground truth entries: {len(ground_truth)}")
    exact_count = sum(1 for e in ground_truth if e.match_method == "exact")
    fallback_count = sum(1 for e in ground_truth if e.match_method == "source_fallback")
    print(f"  Exact matches: {exact_count}, Source fallbacks: {fallback_count}")

    # ── 构建多轮链 ──
    chains = build_conversation_chains(cases)
    chain_map: dict[str, list[EvalCase]] = {}
    for root_id, chain in chains.items():
        for c in chain:
            chain_map[c.id] = chain

    # ── 运行评测 ──
    output_dir = args.output or (EVAL_ROOT.parent / "results" / "graph-gate" / args.split)
    manifest = build_run_manifest(
        dataset_path, args.corpus_dir, sorted(source_files),
        args.arms, args.alpha_grid, args.seed, args.config,
    )

    all_results: list = []
    alpha_values = args.alpha_grid or [0.7]

    for alpha in alpha_values:
        print(f"\n{'=' * 60}")
        print(f"  Alpha = {alpha}")
        print(f"{'=' * 60}")

        for arm in args.arms:
            print(f"\n  Arm: {arm}")
            arm_results: list[RetrievalCaseResult] = []

            # 先运行 B 组，收集 context_chunk_ids 用于 Graph lift/pollution 计算
            b_context_ids: dict[str, set[str]] = {}
            if arm == ARM_GRAPH_RERANK and ARM_STANDARD_RERANK in args.arms:
                # B 组结果已在之前运行
                pass

            for i, case in enumerate(active_cases):
                print(f"    [{i+1}/{len(active_cases)}] {case.id}: {case.query[:50]}...")

                # 多轮历史
                history = None
                if case.query_type == QueryType.MULTI_TURN and case.id in chain_map:
                    chain = chain_map[case.id]
                    turn_idx = next(
                        (j for j, c in enumerate(chain) if c.id == case.id), 0,
                    )
                    history = canonical_history_for_turn(chain, turn_idx)

                # chunk 真值
                gt_chunk_ids = get_relevant_chunk_ids(case, gt_map)

                # B 组 context IDs（用于 Graph lift/pollution）
                b_ctx = b_context_ids.get(case.id)

                if args.phase in ("retrieval", "full"):
                    result = _run_retrieval_arm(
                        case, arm, model, collection, bm25,
                        all_docs, all_metadatas, kg, alpha,
                        history=history,
                        ground_truth_chunk_ids=gt_chunk_ids,
                        b_context_chunk_ids=b_ctx,
                    )
                    arm_results.append(result)

                    # 记录 B 组 context IDs
                    if arm == ARM_STANDARD_RERANK:
                        b_context_ids[case.id] = set(result.context_chunk_ids)

                if args.phase in ("generation", "full"):
                    retrieval_result = arm_results[-1] if arm_results else None
                    gen_result = _run_generation_arm(
                        case, arm, model, collection, bm25,
                        all_docs, all_metadatas, kg, alpha,
                        history=history,
                        ground_truth_chunk_ids=gt_chunk_ids,
                        retrieval_result=retrieval_result,
                    )
                    all_results.append(gen_result)
                else:
                    all_results.extend(arm_results)
                    arm_results = []

    # ── 计算汇总 ──
    print(f"\n{'=' * 60}")
    print("  Computing summary...")
    summary = compute_summary(all_results, active_cases, args.arms)

    # ── 保存结果 ──
    save_results(output_dir, manifest, ground_truth, all_results, summary)
    print(f"\n  Results saved to: {output_dir}")

    # ── 打印关键指标 ──
    print(f"\n{'=' * 60}")
    print("  Key Metrics Summary")
    print(f"{'=' * 60}")

    for arm in args.arms:
        arm_key = arm.replace("-", "_")
        arm_summary = summary.get(arm_key, {})
        if not arm_summary:
            continue
        print(f"\n  {arm}:")
        for slice_name in ["graph_target", "all_answerable", "overall"]:
            slice_metrics = arm_summary.get(slice_name, {})
            if not slice_metrics:
                continue
            print(f"    {slice_name}:")
            for key in ["recall@5", "recall@10", "context_recall", "context_precision",
                        "answer_point_coverage", "retrieval_ms_p50"]:
                val = slice_metrics.get(key)
                if val is not None:
                    print(f"      {key:25s} {val:.4f}" if isinstance(val, float) else f"      {key:25s} {val}")

    # 配对差值
    paired = summary.get("paired_cb", {})
    if paired:
        print(f"\n  Paired C-B deltas:")
        for slice_name, delta_info in paired.items():
            print(f"    {slice_name}: mean_delta={delta_info['mean_delta']:.4f} "
                  f"(n={delta_info['n_pairs']})")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
