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
    context_source_recall,
    context_source_coverage,
)
from evaluation.citation_aggregation import (
    aggregate_citations,
    case_counts_from_result,
)
from evaluation.citation_metrics import (
    CitationMetrics,
    evaluate_citations,
    evaluate_citations_context_aware,
)


# ── 常量 ─────────────────────────────────────────────────────────────

EVAL_ROOT = Path(__file__).parent
DATASETS_DIR = EVAL_ROOT / "datasets"

# 实验组名称
ARM_STANDARD = "standard"
ARM_STANDARD_RERANK = "standard-rerank"
ARM_GRAPH_RERANK = "graph-rerank"

# Selector 消融臂（无 reranker，唯一差异是 context selector 同源上限）：
# S0 = 不限同源（max_per_source=None）；S3 = 每源最多 3（生产默认 cap=3）。
ARM_SELECTOR_UNLIMITED = "selector-unlimited"
ARM_SELECTOR_CAP3 = "selector-cap3"
SELECTOR_ABLATION_ARMS = [ARM_SELECTOR_UNLIMITED, ARM_SELECTOR_CAP3]

# 拒答策略消融臂：与 standard 检索配置完全相同（reranker=none、cap=3），
# 唯一差异是生成阶段拒答策略（evidence_calibrated）。A/B 两臂共享同一
# QueryPlan 与 PreparedAnswerEvidence，仅分别调用生成步骤。
ARM_STANDARD_CALIBRATED = "standard-calibrated"
REFUSAL_ABLATION_ARMS = [ARM_STANDARD, ARM_STANDARD_CALIBRATED]

ALL_ARMS = [ARM_STANDARD, ARM_STANDARD_RERANK, ARM_GRAPH_RERANK]

# 每臂 context selector 同源上限（None = 不限；正数 = 每源最多 N）。
# A/B/C 保持生产默认 3（行为不变）；S0/S3 为消融的显式策略。
# locked-config 的 arm_selector_policy 与 run manifest 均以此映射为准
# （fail-closed 校验，防止 S0/S3 配置漂移）。
ARM_SELECTOR_MAX_PER_SOURCE: dict[str, int | None] = {
    ARM_STANDARD: 3,
    ARM_STANDARD_RERANK: 3,
    ARM_GRAPH_RERANK: 3,
    ARM_SELECTOR_UNLIMITED: None,
    ARM_SELECTOR_CAP3: 3,
    ARM_STANDARD_CALIBRATED: 3,
}


def _arm_selector_max_per_source(arm: str) -> int | None:
    """每臂 context selector 的同源上限（None = 不限同源）。

    检索/生成两条路径都必须以此为准，保证同一臂的 context 选择策略一致。
    """
    try:
        return ARM_SELECTOR_MAX_PER_SOURCE[arm]
    except KeyError:
        raise ValueError(f"Unknown arm: {arm}") from None

# Graph 目标切片：cross_document + mixed_intent
GRAPH_TARGET_TYPES = {QueryType.CROSS_DOCUMENT, QueryType.MIXED_INTENT}

# 评测方案版本
COMPARE_VERSION = 1


# ── 数据类 ───────────────────────────────────────────────────────────

# relevance_level 取值：chunk=case 存在可标注的内容 chunk 真值（需补标 chunk）；
# source=元数据类问题无内容 chunk 真值（只能按 source 级评估）。
# None=尚未人工判定。仅人工填写，工具不得替人赋默认值。
RELEVANCE_LEVELS = ("chunk", "source")


def validate_relevance_level(value: str | None) -> None:
    """校验 relevance_level 的合法取值。

    合法值为 None（未判定）或 RELEVANCE_LEVELS 中的值；其余抛 ValueError。
    """
    if value is not None and value not in RELEVANCE_LEVELS:
        raise ValueError(
            f"invalid relevance_level={value!r}; expected None or one of "
            f"{RELEVANCE_LEVELS}",
        )


@dataclass
class GroundTruthEntry:
    """一条 chunk 真值映射记录。"""
    case_id: str
    source_id: str
    normalized_snippet: str
    matched_chunk_ids: list[str]
    match_method: str  # "exact" | "overlap" | "parent" | "source_fallback" | "unmatched"
    reviewer_status: str  # "auto" | "confirmed" | "needs_review"
    relevance_level: str | None = None  # "chunk" | "source" | None（人工判定，默认未判定）


def ground_truth_from_dict(d: dict[str, Any]) -> GroundTruthEntry:
    """从 dict 导入一条 ground truth 记录（导入格式）。

    兼容旧文件（缺少 relevance_level 字段时视为 None），并校验
    relevance_level 取值；非法值抛 ValueError。
    """
    level = d.get("relevance_level")
    validate_relevance_level(level)
    return GroundTruthEntry(
        case_id=d["case_id"],
        source_id=d["source_id"],
        normalized_snippet=d.get("normalized_snippet", ""),
        matched_chunk_ids=list(d.get("matched_chunk_ids", [])),
        match_method=d["match_method"],
        reviewer_status=d["reviewer_status"],
        relevance_level=level,
    )


def load_ground_truth_map(path: Path) -> list[GroundTruthEntry]:
    """读取 ground-truth-map.json 并按导入格式校验。"""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise ValueError(f"ground truth map must be a JSON list: {path}")
    return [ground_truth_from_dict(d) for d in raw]


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
    # 是否具有可靠的 chunk 真值（exact 或 confirmed overlap/parent）
    has_chunk_truth: bool = True

    # 可选字段
    context_token_count: int | None = None

    # 分阶段延迟 (ms)
    rewrite_ms: float = 0.0
    decompose_ms: float = 0.0
    embedding_ms: float = 0.0
    dense_ms: float = 0.0
    bm25_ms: float = 0.0
    entity_ms: float = 0.0   # 实体抽取耗时（来自 QueryPlan 缓存）
    graph_ms: float = 0.0
    rerank_ms: float = 0.0
    context_build_ms: float = 0.0
    total_retrieval_ms: float = 0.0

    # Graph 特有
    alpha: float = 0.7  # Graph 融合权重
    graph_query_entities: list[str] = field(default_factory=list)
    graph_only_chunk_ids: list[str] = field(default_factory=list)  # 仅来自 Graph 通道、不在 base candidates 中的 chunk
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

    def source_candidate_metrics(
        self, ks: tuple[int, ...] = (5, 10),
    ) -> dict[str, float]:
        """计算候选检索层的 source-level 指标。

        与 ``candidate_metrics`` 对称，但按去重 source 而非 chunk 衡量 recall。
        relevance_level=source 的 case（has_chunk_truth=False 但
        relevant_source_ids 非空）由此进入统计；chunk-level 指标不受影响。
        """
        return {
            f"source_recall@{k}": source_recall_at_k(
                self.candidate_source_ids, self.relevant_source_ids, k,
            )
            for k in ks
        }

    def context_source_metrics(self) -> dict[str, float]:
        """计算 prompt context 层的 source-level 指标。

        与 ``context_metrics`` 对称的 source 版本：
        - ``context_source_recall``：context 覆盖了多大比例的 relevant source；
        - ``context_source_coverage``：context 中去重 source 有多少是 relevant。
        无 relevant_source_ids（如 no_answer 与仅 chunk 标注 case）→ recall 为 0，
        coverage 由 context 是否为空决定。
        """
        return {
            "context_source_recall": context_source_recall(
                self.context_source_ids, self.relevant_source_ids,
            ),
            "context_source_coverage": context_source_coverage(
                self.context_source_ids, self.relevant_source_ids,
            ),
        }


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

    # alpha（用于按 alpha 隔离分组）
    alpha: float = 0.7

    # 引用指标
    citation_id_validity: float = 0.0
    citation_precision: float = 0.0
    citation_recall: float = 0.0
    faithfulness: float = 0.0
    correctly_refused: bool | None = None

    # 契约 v2：context-supported 引用指标（正式 guardrail 口径）
    # 引用必须映射到最终送入 LLM 的 context chunk/source 才算有效
    context_supported_citation_validity: float = 0.0
    # 幻觉/不可映射引用数
    fabricated_citation_count: int = 0
    # 候选池可见但未进 context 的引用数
    retrieved_not_in_context_count: int = 0
    # 逐引用状态计数（supported_chunk/supported_source/fabricated/...）
    citation_status_counts: dict = field(default_factory=dict)

    # 答案要点覆盖率
    answer_point_coverage: float = 0.0

    # PreparedAnswerEvidence 指纹（拒答策略消融：每 case 写入，paired
    # 分析据此对 A/B 两臂做 fail-closed 一致性校验；非 ablation 路径
    # 为空，向后兼容既有 JSONL schema）
    evidence_context_sha256: str = ""
    evidence_plan_fingerprint: str = ""
    evidence_retrieval_fingerprint: str = ""
    evidence_citation_map: tuple | list = ()
    evidence_candidate_chunk_ids: tuple | list = ()

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


# ── Reviewed truth overlay 应用与真值门禁 ────────────────────────────

def load_reviewed_truth_overlay(path: Path) -> dict[str, Any]:
    """加载 reviewed-truth-overlay.json；版本/结构非法 → ValueError。

    overlay 由 evaluation.review_apply 生成；本函数校验版本与必需键，
    消费端保证在 prepare_index 前、任何 retrieval/LLM 调用前失败。
    """
    from evaluation.review_apply import REVIEW_APPLY_VERSION
    path = Path(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable reviewed-truth overlay: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("reviewed-truth overlay root must be a JSON object")
    version = raw.get("version")
    if version != REVIEW_APPLY_VERSION:
        raise ValueError(
            f"unsupported reviewed-truth overlay version: {version!r} "
            f"(supported: {REVIEW_APPLY_VERSION})",
        )
    required = {"dataset_sha256", "ground_truth_sha256", "entries",
                "case_relevance_levels", "counts"}
    missing = sorted(required - set(raw))
    if missing:
        raise ValueError(f"reviewed-truth overlay missing fields: {missing}")
    if not isinstance(raw["entries"], list) or not isinstance(
        raw["case_relevance_levels"], list,
    ):
        raise ValueError("overlay entries/case_relevance_levels must be lists")
    return raw


def _overlay_entry_key(entry: dict[str, Any]) -> tuple:
    """overlay entry 的稳定匹配键（与 GT entry 应用侧同构）。"""
    return (
        entry["case_id"],
        entry["source_id"],
        entry["normalized_snippet"],
        tuple(sorted(entry.get("candidate_chunk_ids", []))),
    )


def _gt_entry_key(entry: GroundTruthEntry) -> tuple:
    """本次生成的 GT entry 的稳定键（case/source/snippet/候选 chunk IDs）。"""
    return (
        entry.case_id,
        entry.source_id,
        entry.normalized_snippet,
        tuple(sorted(entry.matched_chunk_ids)),
    )


def apply_reviewed_truth_overlay(
    ground_truth: list[GroundTruthEntry],
    overlay: dict[str, Any],
) -> tuple[list[GroundTruthEntry], list[str]]:
    """把人工决定精确应用到本次生成的 ground truth。

    按稳定键 (case_id, source_id, normalized_snippet, 候选 chunk IDs)
    唯一匹配：overlay entry 未消费、GT entry 重复匹配或 overlay entry
    重复匹配都抛 ValueError（fail-closed，不静默忽略）。

    - confirmed → reviewer_status="confirmed"（可靠 chunk 真值）
    - rejected → reviewer_status="rejected"（显式拒绝，绝不与 confirmed 混淆）
    - 未在 overlay 中的 GT entry 原样保留（exact auto 等）

    Returns:
        (更新后的 ground_truth, source_only_case_ids)
    """
    overlay_by_key: dict[tuple, list[dict]] = {}
    for entry in overlay["entries"]:
        overlay_by_key.setdefault(_overlay_entry_key(entry), []).append(entry)

    errors: list[str] = []
    updated: list[GroundTruthEntry] = []
    consumed: set[tuple] = set()

    for gt_entry in ground_truth:
        key = _gt_entry_key(gt_entry)
        matches = overlay_by_key.get(key, [])
        if len(matches) > 1:
            errors.append(
                f"duplicate overlay match for GT entry "
                f"{gt_entry.case_id}/{gt_entry.source_id}",
            )
        if len(matches) == 1:
            consumed.add(key)
            decision = matches[0]["review_decision"]
            if decision == "confirmed":
                gt_entry.reviewer_status = "confirmed"
            elif decision == "rejected":
                gt_entry.reviewer_status = "rejected"
            else:
                errors.append(
                    f"overlay entry {gt_entry.case_id}/{gt_entry.source_id}: "
                    f"invalid review_decision {decision!r}",
                )
        updated.append(gt_entry)

    # 未消费的 overlay entries（本次 GT 中无对应条目 → 陈旧/不匹配）
    for key in overlay_by_key:
        if key not in consumed:
            errors.append(
                f"overlay entry not consumed by this run's ground truth: "
                f"case_id={key[0]} source_id={key[1]}",
            )

    if errors:
        raise ValueError("; ".join(errors))

    source_only = sorted(
        c["case_id"]
        for c in overlay.get("case_relevance_levels", [])
        if c.get("relevance_level") == "source"
    )
    return updated, source_only


def enforce_truth_gate(
    active_cases: list[EvalCase],
    case_has_reliable_chunk_truth: dict[str, bool],
    overlay: dict[str, Any],
    source_only_case_ids: list[str],
) -> list[str]:
    """真值门禁：返回错误列表（空 = 通过），在任何 LLM/retrieval 前调用。

    使用 overlay 后（有显式人工决定）的 fail-closed 规则：
    - relevance_level=source 的 case 计为 source-only，放行（分母排除由
      case_has_reliable_chunk_truth=False 实现，现有统计口径不倒退）；
    - relevance_level=chunk 但本次无可靠 chunk 真值 → 失败（要求补标）；
    - 无可靠 chunk 真值且无显式 source 决定（如 overlap 全部 reject 或
      缺 chunk truth 未补标）→ 失败（不允许静默失去真值）。
    """
    level_by_case = {
        c["case_id"]: c.get("relevance_level")
        for c in overlay.get("case_relevance_levels", [])
    }
    errors: list[str] = []
    for case in active_cases:
        if case.should_refuse:
            continue
        if case.id in source_only_case_ids:
            continue
        if case_has_reliable_chunk_truth.get(case.id, False):
            continue
        level = level_by_case.get(case.id)
        if level == "chunk":
            errors.append(
                f"case {case.id}: relevance_level=chunk but no reliable "
                f"chunk truth in this run; annotate chunks before formal "
                f"comparison",
            )
        else:
            errors.append(
                f"case {case.id}: no reliable chunk truth and no explicit "
                f"source-level decision; resolve (chunk annotation or "
                f"relevance_level=source) before formal comparison",
            )
    return errors


def get_relevant_chunk_ids(
    case: EvalCase,
    ground_truth: dict[str, list[str]],
    case_has_reliable_chunk_truth: dict[str, bool] | None = None,
) -> set[str]:
    """从 ground truth map 获取 case 的 relevant chunk IDs。

    只使用可靠的 chunk truth 映射 — exact match 或已人工确认
    (reviewer=confirmed) 的 overlap/parent。auto/needs_review 的
    overlap、parent 以及 source_fallback/unmatched 均不进入。

    Args:
        case: 评测 case
        ground_truth: case_id -> matched_chunk_ids 映射（已排除 source_fallback）
        case_has_reliable_chunk_truth: 可选输出参数，记录此 case 是否有可靠 chunk truth

    Returns:
        relevant chunk ID 集合
    """
    ids = set(ground_truth.get(case.id, []))
    if case_has_reliable_chunk_truth is not None:
        case_has_reliable_chunk_truth[case.id] = (
            case.id in ground_truth and len(ground_truth[case.id]) > 0
        )
    return ids


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
    跨进程确定性：chain root 分配前稳定排序、输出按 case_id 稳定排序，
    结果与 PYTHONHASHSEED 无关（同一 seed → 同一 dev/holdout）。

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

    # 对 multi_turn chain 整体分配：chain root 先稳定排序再 shuffle，
    # 避免 set 迭代顺序（随 PYTHONHASHSEED 变化）影响分配 → 跨进程确定性
    chain_roots = sorted(chain_root_ids)
    rng.shuffle(chain_roots)
    n_holdout_chains = max(1, round(len(chain_roots) * holdout_ratio))
    holdout_chain_ids = set(chain_roots[:n_holdout_chains])

    dev_multi: list[EvalCase] = []
    holdout_multi: list[EvalCase] = []
    # sorted(chains.items())：与 dict 插入顺序解耦，进一步保证确定性
    for root_id, chain_cases in sorted(chains.items()):
        if root_id in holdout_chain_ids:
            holdout_multi.extend(chain_cases)
        else:
            dev_multi.extend(chain_cases)

    # 输出稳定排序（按 case_id）：结果 JSONL / review pack / 锁配置可复现，
    # 且不依赖任何集合迭代顺序
    development = sorted(dev_non_multi + dev_multi, key=lambda c: c.id)
    holdout = sorted(holdout_non_multi + holdout_multi, key=lambda c: c.id)

    return development, holdout


def compute_split_fingerprint(
    development: list[EvalCase],
    holdout: list[EvalCase],
) -> str:
    """计算 dev/holdout 拆分的 canonical SHA-256 指纹（确定性）。

    基于排序后的 case_id 列表（与输入顺序、PYTHONHASHSEED 无关）：
    dataset、holdout_ratio、seed 或 split 算法任何变化都会改变指纹。
    写入 locked-config，并在任何索引/LLM/QueryPlan 工作前 fail-closed
    校验当前 split 与锁定指纹一致。
    """
    payload = {
        "development": sorted(c.id for c in development),
        "holdout": sorted(c.id for c in holdout),
    }
    text = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


# ── Query Plan（共享 rewrite/decompose/基础检索结果） ─────────────────

@dataclass
class QueryPlan:
    """同一 case 在 A/B/C 三臂间共享的查询规划结果。

    保证三臂使用完全相同的 rewrite、decompose、基础检索和漂移防护结果，
    消除 LLM 非确定性导致的跨臂差异。
    """

    rewritten_query: str
    rewrite_log: dict[str, Any]
    sub_queries: list[str]
    # 基础检索：chunk_index -> RRF score（去重后、漂移防护后）
    base_candidates: dict[int, float]
    # Graph 实体缓存：同一 case 只抽取一次，C 臂复用
    graph_entities: list[str] = field(default_factory=list)
    # 分阶段延迟
    rewrite_ms: float = 0.0
    decompose_ms: float = 0.0
    embedding_ms: float = 0.0
    dense_ms: float = 0.0
    bm25_ms: float = 0.0
    entity_ms: float = 0.0  # 实体抽取耗时（独立于 graph_ms）


def prepare_query_plan(
    case: EvalCase,
    model,
    collection,
    bm25,
    all_docs: list[str],
    all_metadatas: list[dict],
    history: list[tuple[str, str]] | None = None,
    arms: list[str] | None = None,
    alpha_values: list[float] | None = None,
    kg=None,
) -> QueryPlan:
    """为单个 case 构建共享的查询规划（rewrite + decompose + 基础检索 + 漂移防护）。

    A/B/C 三臂必须复用同一 QueryPlan，唯一差异是：
    - A: 无 reranker，无 Graph
    - B: 有 reranker，无 Graph
    - C: 有 reranker，在 base_candidates 上增量合并 Graph candidates

    若本次运行包含 C 臂且至少有一个 alpha < 1.0，则在此阶段对
    rewritten_query 至多调用一次 extract_entities_from_query，
    结果缓存到 QueryPlan.graph_entities（A/B 不触发）。
    若所有 alpha=1.0，C 也不抽取实体，作为严格 non-Graph control。
    """
    from src.rag import retrieve_hybrid_with_sources
    from src.rag_query_rewriter import rewrite_query_llm, merge_rewrite_results
    from src.rag_query_decomposer import decompose_query_llm
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # ── Step 1: Query rewrite ──
    t0 = time.perf_counter()
    rewritten_query, rewrite_log = rewrite_query_llm(case.query, history=history)
    rewrite_ms = (time.perf_counter() - t0) * 1000

    # ── Step 2: Query decompose ──
    t0 = time.perf_counter()
    sub_queries = decompose_query_llm(rewritten_query)
    if not sub_queries:
        sub_queries = [rewritten_query]
    decompose_ms = (time.perf_counter() - t0) * 1000

    # ── Step 3: 子查询并发检索 ──
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

    # ── Step 4: 漂移防护 ──
    if rewrite_log.get("changed"):
        orig_indices, _, orig_scores = retrieve_hybrid_with_sources(
            case.query, model, collection, bm25, all_docs, all_metadatas,
        )
        orig_score_map: dict[int, float] = {}
        for idx, score in zip(orig_indices, orig_scores):
            orig_score_map[idx] = score
        merged_indices, best_score, _merge_log = merge_rewrite_results(
            list(best_score.keys()), best_score,
            orig_indices, orig_score_map,
        )

    # ── Step 5（可选）：Graph 实体抽取（C 臂 + 存在非 1.0 alpha 时触发） ──
    graph_entities: list[str] = []
    entity_ms = 0.0
    needs_graph_entities = (
        arms is not None
        and ARM_GRAPH_RERANK in arms
        and kg is not None
        and alpha_values is not None
        and any(a < 1.0 for a in alpha_values)
    )
    if needs_graph_entities:
        from src.graph_rag import extract_entities_from_query
        t_entity = time.perf_counter()
        try:
            graph_entities = extract_entities_from_query(rewritten_query)
        except Exception:
            graph_entities = []
        entity_ms = (time.perf_counter() - t_entity) * 1000

    return QueryPlan(
        rewritten_query=rewritten_query,
        rewrite_log=rewrite_log,
        sub_queries=sub_queries,
        base_candidates=dict(best_score),
        graph_entities=graph_entities,
        rewrite_ms=rewrite_ms,
        decompose_ms=decompose_ms,
        entity_ms=entity_ms,
    )


# ── Graph 候选融合（RRF 同量纲） ──────────────────────────────────────

def merge_graph_candidates(
    base_candidates: dict[int, float],
    graph_chunk_ids: list[str],
    all_metadatas: list[dict],
    alpha: float,
    k_rrf: int = 60,
) -> tuple[dict[int, float], list[str]]:
    """RRF 同量纲融合 Graph 候选到 base candidates。

    关键修复：Graph 分数使用与 base RRF 相同的 k=60 参数，
    避免量纲不一致导致 Graph 不公平压过 base 检索。

    融合策略：
    - 同时出现在 base 和 Graph 中：merged = alpha*base + (1-alpha)*graph_rrf
    - 仅 Graph 中（graph-only）：merged = (1-alpha)*graph_rrf
    - 仅 base 中：保留 base 分数
    - alpha=1.0 时禁止加入 graph-only candidates（C 与 B 严格一致）

    Args:
        base_candidates: chunk_index -> RRF score（来自 QueryPlan）
        graph_chunk_ids: Graph 通道返回的 chunk_id 列表（按相关性排序）
        all_metadatas: 全部元数据，用于 chunk_id -> index 反向映射
        alpha: 融合权重，1.0 = 纯 base，0.0 = 纯 Graph
        k_rrf: RRF 参数，默认 60（与 src.rag.rrf_merge 一致）

    Returns:
        (merged_candidates, graph_only_chunk_ids)
    """
    # 构建 chunk_id -> index 反向映射（仅对 base 中出现的 chunk）
    chunk_id_to_idx: dict[str, int] = {}
    for idx in range(len(all_metadatas)):
        cid = all_metadatas[idx].get("chunk_id", f"chunk_{idx}")
        chunk_id_to_idx[cid] = idx

    # 识别 base 中的 chunk_id 集合
    base_chunk_id_set: set[str] = set()
    for idx in base_candidates:
        meta = all_metadatas[idx] if idx < len(all_metadatas) else {}
        base_chunk_id_set.add(meta.get("chunk_id", f"chunk_{idx}"))

    merged = dict(base_candidates)
    graph_only_chunk_ids: list[str] = []

    for rank, g_chunk_id in enumerate(graph_chunk_ids):
        if g_chunk_id not in chunk_id_to_idx:
            continue
        g_idx = chunk_id_to_idx[g_chunk_id]

        # Graph RRF 分数：1 / (rank + k)，rank 从 0 开始
        graph_rrf = 1.0 / (rank + k_rrf)

        if g_idx in merged:
            # 同时出现：alpha*base + (1-alpha)*graph_rrf
            base_score = merged[g_idx]
            merged[g_idx] = alpha * base_score + (1 - alpha) * graph_rrf
        else:
            # Graph-only：alpha=1.0 时禁止加入（C 与 B 严格一致）
            if alpha < 1.0:
                merged[g_idx] = (1 - alpha) * graph_rrf
                if g_chunk_id not in base_chunk_id_set:
                    graph_only_chunk_ids.append(g_chunk_id)

    return merged, graph_only_chunk_ids


def build_query_plan_cache(
    cases: list[EvalCase],
    model,
    collection,
    bm25,
    all_docs: list[str],
    all_metadatas: list[dict],
    chain_map: dict[str, list[EvalCase]] | None = None,
    arms: list[str] | None = None,
    alpha_values: list[float] | None = None,
    kg=None,
) -> dict[str, QueryPlan]:
    """为所有 cases 构建 QueryPlan 缓存（key=case_id）。

    关键修复：QueryPlan 在 alpha/arm 循环外一次性构建，
    所有 arm 和 alpha 共享同一 QueryPlan 实例，避免重复 LLM 调用。

    Args:
        cases: 评测 case 列表
        model, collection, bm25, all_docs, all_metadatas: 索引相关参数
        chain_map: 多轮对话链映射（case_id -> chain）

    Returns:
        dict[case_id, QueryPlan]
    """
    cache: dict[str, QueryPlan] = {}
    for case in cases:
        # 构建多轮历史
        history = None
        if case.query_type == QueryType.MULTI_TURN and chain_map and case.id in chain_map:
            chain = chain_map[case.id]
            turn_idx = next(
                (j for j, c in enumerate(chain) if c.id == case.id), 0,
            )
            history = canonical_history_for_turn(chain, turn_idx)

        # 构建 QueryPlan（每个 case 只调用一次）
        plan = prepare_query_plan(
            case, model, collection, bm25,
            all_docs, all_metadatas, history=history,
            arms=arms, alpha_values=alpha_values, kg=kg,
        )
        cache[case.id] = plan

    return cache


# ── 受控检索管线 ────────────────────────────────────────────────────

def _source_label_from_meta(meta: dict[str, Any]) -> str:
    """从 chunk metadata 提取 source 标签，与 dataset 域对齐。

    优先 ``source_name``（文件名），fallback 至 ``source``、最后是 ``source_id``。
    这是关键设计——：dataset 的 ``relevant_source_ids`` 是文件名一格；
    若用 ``source_id``（SHA-256 路径哈希）作为候选 source 标签，则与真值
    比较恒为 0 交集（source_recall@K 永远 0）。只 could 与 truth 对齐的域名才
    能让 source recall/coverage 有意义。

    Args:
        meta: chunk metadata dict（含 source_name/source/source_id）。

    Returns:
        非 None 的 source 标签字符串；都缺失时返回空字符串。
    """
    return (meta.get("source_name")
            or meta.get("source")
            or meta.get("source_id", ""))


def _chroma_dir_for_collection(collection_name: str) -> Path:
    """评测使用的 chroma 目录（与 src.rag 的 CHROMA_DB_PATH 同源）。

    src.rag 的 CHROMA_DB_PATH 由 _default_chroma_db_path() 计算；
    这里按相同逻辑推导（默认 ~/.mneme/chroma_db），供 KG 缓存路径使用。
    """
    from src.rag import CHROMA_DB_PATH
    return Path(CHROMA_DB_PATH)


def _kg_cache_path(collection_name: str) -> Path:
    """KG 缓存文件路径：<chroma_dir>/<collection_name>_kg.json。"""
    return _chroma_dir_for_collection(collection_name) / f"{collection_name}_kg.json"


def _load_kg_cache(kg_file: Path, current_fp: str):
    """按 index_fingerprint 加载 KG 缓存；不匹配/损坏时返回 None。"""
    from src.graph_rag import KnowledgeGraph
    if not Path(kg_file).exists():
        return None
    try:
        candidate = KnowledgeGraph.load(str(kg_file))
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    if candidate.index_fingerprint != current_fp:
        return None
    return candidate


def _save_kg_cache(kg, kg_file: Path, current_fp: str) -> None:
    """将 KG 保存到磁盘缓存（index_fingerprint 作有效判据）。"""
    kg_file = Path(kg_file)
    kg_file.parent.mkdir(parents=True, exist_ok=True)
    kg.save(str(kg_file), current_fp)


def _run_retrieval_arm(
    case: EvalCase,
    arm: str,
    model,
    collection,
    bm25,
    all_docs: list[str],
    all_metadatas: list[dict],
    query_plan: QueryPlan,
    kg=None,
    alpha: float = 0.7,
    history: list[tuple[str, str]] | None = None,
    ground_truth_chunk_ids: set[str] | None = None,
    b_context_chunk_ids: set[str] | None = None,
    reranker=None,
    has_chunk_truth: bool = True,
) -> RetrievalCaseResult:
    """运行单个 arm 的检索管线。

    A/B/C 三组共享同一 QueryPlan（rewrite/decompose/基础检索/漂移防护）。
    差异仅在：
    - A: 无 reranker，无 Graph
    - B: 有 reranker，无 Graph
    - C: 有 reranker，在 base_candidates 上增量合并 Graph candidates

    C 臂的关键修复：Graph candidates 与 base_candidates 做确定性 RRF 同量纲合并，
    而非用 Graph 结果替换 base candidates。合并策略（通过 merge_graph_candidates）：
    - base candidates 保留原始 RRF 分数
    - 同时出现在两边的 candidates：alpha*base + (1-alpha)*graph_rrf (k=60)
    - Graph-only candidates：仅在 alpha < 1.0 时加入，alpha=1.0 时 C 与 B 严格一致
    """
    from src.rag import (
        dynamic_top_k,
        enrich_context,
        _build_context,
        _get_reranker,
        expand_with_parent,
        expand_with_adjacent,
        select_context_candidates,
    )
    from src.domain import RetrievalCandidate, compute_context_k

    t_start = time.perf_counter()

    # 从共享 QueryPlan 获取 rewrite/decompose 结果
    rewrite_ms = query_plan.rewrite_ms
    decompose_ms = query_plan.decompose_ms

    # 从共享 QueryPlan 获取基础检索结果（漂移防护后）
    best_score: dict[int, float] = dict(query_plan.base_candidates)

    # ── Step 5: Graph 增量合并（仅 C 组 + alpha < 1.0） ──
    # C 臂读取 QueryPlan 已缓存的实体。
    # alpha=1.0 时完全跳过图路径（KG 调用、图遍历、融合），作为 strict non-Graph control。
    graph_ms = 0.0
    graph_query_entities: list[str] = []
    graph_only_chunk_ids: list[str] = []
    if arm == ARM_GRAPH_RERANK and kg is not None and alpha < 1.0:
        # 从 QueryPlan 缓存读取实体（不调用 extract_entities_from_query）
        graph_query_entities = query_plan.graph_entities

        if graph_query_entities:
            # Graph 遍历：从实体出发获取关联 chunk
            t_graph = time.perf_counter()
            related_entities = kg.get_related_entities(
                graph_query_entities, max_hops=1, top_k=10,
            )
            graph_chunk_ids = kg.get_chunks_by_entities(
                [e for e, _s in related_entities], max_chunks=20,
            )
            graph_ms = (time.perf_counter() - t_graph) * 1000

            # RRF 同量纲融合（k=60，与 base RRF 一致）
            best_score, graph_only_chunk_ids = merge_graph_candidates(
                best_score, graph_chunk_ids, all_metadatas, alpha,
            )

    # 排序
    merged = sorted(best_score.keys(), key=lambda i: best_score[i], reverse=True)
    scores_flat = sorted(best_score.values(), reverse=True)

    # ── Step 6: Dynamic Top-K ──
    k = dynamic_top_k(scores_flat)
    top_indices = merged[:k]

    # ── Step 7: 重排（仅 B/C）+ 统一 context selector（三臂对称） ──
    # 三臂 context 构建规则完全一致：已排序候选 → 重排（可选）→
    # select_context_candidates（source diversity + top-k 截断）。
    # A/B/C 只允许「候选排序来源」不同（A=RRF 序；B/C=reranker 后），
    # 不允许在截断/多样性/扩展规则上差异（修复：消除诊断发现的
    # 「A 无 diversity、B/C 独有 top-20 截断」的不对称）。
    rerank_ms = 0.0
    if arm in (ARM_STANDARD_RERANK, ARM_GRAPH_RERANK):
        t0 = time.perf_counter()
        # 优先使用注入的 reranker 实例（validate_reranker 返回值），
        # 否则回退到 _get_reranker() 作为防御性检查
        _reranker = reranker if reranker is not None else _get_reranker()
        if _reranker is None:
            from src.rag import RAG_RERANKER_MODE
            raise RuntimeError(
                f"Reranker required for arm {arm!r} but no reranker instance available. "
                f"Current RAG_RERANKER_MODE={RAG_RERANKER_MODE!r}. "
                f"Set RAG_RERANKER=cross-encoder or use standard arm instead."
            )
        candidates = [
            RetrievalCandidate(
                index=i,
                chunk_id=(all_metadatas[i] or {}).get("chunk_id", f"chunk_{i}"),
                source_id=(all_metadatas[i] or {}).get("source_id", ""),
                source_name=(all_metadatas[i] or {}).get("source_name", "")
                    or (all_metadatas[i] or {}).get("source", ""),
                text=all_docs[i] if i < len(all_docs) else "",
                rrf_score=best_score.get(i),
            )
            for i in top_indices
        ]
        reranked = _reranker.rerank(case.query, candidates, top_k=min(k, 20))
        selected = select_context_candidates(
            reranked, top_k=min(k, 20),
            max_per_source=_arm_selector_max_per_source(arm),
        )
        top_indices = [c.index for c in selected]
        rerank_ms = (time.perf_counter() - t0) * 1000
    else:
        # A 组：无重排，但使用与 B/C 完全相同的 context selector
        candidates = [
            RetrievalCandidate(
                index=i,
                chunk_id=(all_metadatas[i] or {}).get("chunk_id", f"chunk_{i}"),
                source_id=(all_metadatas[i] or {}).get("source_id", ""),
                source_name=(all_metadatas[i] or {}).get("source_name", "")
                    or (all_metadatas[i] or {}).get("source", ""),
                text=all_docs[i] if i < len(all_docs) else "",
                rrf_score=best_score.get(i),
            )
            for i in top_indices
        ]
        selected = select_context_candidates(
            candidates, top_k=min(k, 20),
            max_per_source=_arm_selector_max_per_source(arm),
        )
        top_indices = [c.index for c in selected]

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
        source_id = _source_label_from_meta(meta)
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
        source_id = _source_label_from_meta(meta)
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
        has_chunk_truth=has_chunk_truth,
        alpha=alpha,
        # 分阶段延迟：entity_ms 来自 QueryPlan 缓存，graph_ms 仅含图遍历/融合
        entity_ms=query_plan.entity_ms,
        rewrite_ms=rewrite_ms,
        decompose_ms=decompose_ms,
        graph_ms=graph_ms,
        rerank_ms=rerank_ms,
        context_build_ms=context_build_ms,
        total_retrieval_ms=total_retrieval_ms,
        graph_query_entities=graph_query_entities,
        graph_only_chunk_ids=graph_only_chunk_ids,
        graph_lift=graph_lift,
        graph_pollution=graph_pollution,
    )


def _chunk_to_source_map(all_metadatas: list[dict]) -> dict[str, str]:
    """chunk_id → source 标签映射（与 source recall 同口径）。

    与 ``_source_label_from_meta``（source_name 优先）一致，禁止
    filename/hash 混用回归；用于 citation context-supported 的 source 级判定。
    """
    return {
        str(m.get("chunk_id")): _source_label_from_meta(m)
        for m in all_metadatas if m.get("chunk_id")
    }


def _rebuild_context_text(
    context_chunk_ids: list[str],
    all_docs: list[str],
    all_metadatas: list[dict],
) -> str:
    """从 context chunk 列表重建 context 文本（faithfulness 用）。

    注意：为评测重建文本，非生产 ``_build_context`` 的逐字节输出；启发式
    faithfulness（关键术语出现）对二者等价。chunk 缺失时以空串占位。
    """
    by_chunk = {
        str(m.get("chunk_id")): all_docs[i]
        for i, m in enumerate(all_metadatas) if m.get("chunk_id")
    }
    return "\n\n".join(by_chunk.get(cid, "") for cid in context_chunk_ids)


def _citation_status_counts(evidence) -> dict[str, int]:
    """逐引用判定状态计数（可审计；fabricated/retrieved_not_in_context 等）。"""
    counts: dict[str, int] = {}
    for e in evidence:
        counts[e.status] = counts.get(e.status, 0) + 1
    return counts


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
    evidence=None,
    evidence_cache: dict | None = None,
    evidence_key: tuple | None = None,
    query_plan=None,
) -> GenerationCaseResult:
    """运行单个 arm 的完整生成管线。

    调用与生产一致的 answer_query() 接口，而非自行拼装简化链路。
    """
    from src.rag import answer_query, answer_with_llm_history
    from src.citations import make_citation_records, referenced_citation_ids

    t_start = time.perf_counter()

    try:
        # 调用生产管线
        # A/S0/S3 组：无 reranker（A 是原基线；S0/S3 是 selector 消融双臂）
        # B/C 组：开启 reranker
        # C 组额外传入 kg 和 alpha
        if arm in (ARM_STANDARD, ARM_STANDARD_CALIBRATED,
                   ARM_SELECTOR_UNLIMITED, ARM_SELECTOR_CAP3):
            # 临时关闭 reranker；S0/S3 额外按臂设置 context selector 同源
            # 上限（answer_query 生产路径读取 SELECTOR_MAX_PER_SOURCE）
            # standard-calibrated 额外临时覆盖生成拒答策略
            # （evidence_calibrated），finally 恢复原值。
            import src.rag as rag_module
            original_reranker_mode = rag_module.RAG_RERANKER_MODE
            original_selector = rag_module.SELECTOR_MAX_PER_SOURCE
            original_policy = rag_module.RAG_REFUSAL_POLICY
            rag_module.RAG_RERANKER_MODE = "none"
            rag_module._RERANKER_INSTANCE = None
            rag_module.SELECTOR_MAX_PER_SOURCE = _arm_selector_max_per_source(arm)
            if arm == ARM_STANDARD_CALIBRATED:
                rag_module.RAG_REFUSAL_POLICY = (
                    rag_module.REFUSAL_POLICY_EVIDENCE_CALIBRATED)
            try:
                # 拒答策略消融：A/B 两臂共享同一 PreparedAnswerEvidence
                # （每 case 只构建一次：从共享 QueryPlan 构建，零
                # rewrite/decompose/retrieve/select 重跑），仅分别调用
                # 生成步骤；非 ablation 臂走原 answer_query 路径。
                if evidence is None and evidence_cache is not None                         and query_plan is not None:
                    evidence = rag_module.prepare_answer_evidence(
                        case.query, model, collection, bm25,
                        all_docs, all_metadatas,
                        history=history,
                        query_plan=query_plan,
                    )
                    evidence_cache[evidence_key] = evidence
                if evidence is not None:
                    answer, sources = rag_module.generate_answer(
                        evidence, all_docs, all_metadatas,
                        history=history,
                    )
                else:
                    answer, sources = answer_query(
                        case.query, model, collection, bm25,
                        all_docs, all_metadatas,
                        history=history,
                    )
            finally:
                rag_module.RAG_RERANKER_MODE = original_reranker_mode
                rag_module._RERANKER_INSTANCE = None
                rag_module.SELECTOR_MAX_PER_SOURCE = original_selector
                rag_module.RAG_REFUSAL_POLICY = original_policy
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

        # ── 引用指标（契约 v2：context-aware，禁止占位） ──
        # 证据链：
        #   - sources（生产引用展示，format_sources 输出）：S#→chunk 权威映射
        #   - retrieval_result.context_chunk_ids/context_source_ids：评测检索
        #     网格记录的最终 context（真实证据，非假设）
        #   - candidate_chunk_ids：候选池（区分"检索可见"与"context 支持"）
        #   - chunk_to_source：与 source recall 同口径（source_name 优先）
        # retrieval_result 缺失 → fail-closed（不静默产出引用指标）。
        if retrieval_result is None:
            raise RuntimeError(
                "generation arm requires retrieval_result to evaluate "
                "context-supported citations; refusing to emit citation "
                "metrics without context evidence")
        citation_metrics = evaluate_citations_context_aware(
            answer=answer,
            sources=sources,
            context_chunk_ids=retrieval_result.context_chunk_ids,
            context_source_ids=retrieval_result.context_source_ids,
            candidate_chunk_ids=retrieval_result.candidate_chunk_ids,
            chunk_to_source=_chunk_to_source_map(all_metadatas),
            relevant_chunk_ids=ground_truth_chunk_ids or set(),
            answer_points=case.acceptable_answer_points,
            context_text=_rebuild_context_text(
                retrieval_result.context_chunk_ids, all_docs, all_metadatas),
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
            alpha=alpha,
            citation_id_validity=citation_metrics.citation_id_validity,
            citation_precision=citation_metrics.citation_precision,
            citation_recall=citation_metrics.citation_recall,
            faithfulness=citation_metrics.faithfulness,
            correctly_refused=citation_metrics.correctly_refused,
            context_supported_citation_validity=(
                citation_metrics.context_supported_citation_validity),
            fabricated_citation_count=citation_metrics.fabricated_citation_count,
            retrieved_not_in_context_count=(
                citation_metrics.retrieved_not_in_context_count),
            citation_status_counts=_citation_status_counts(
                citation_metrics.evidence),
            answer_point_coverage=coverage,
            evidence_context_sha256=(
                evidence.context_sha256 if evidence is not None else ""),
            evidence_plan_fingerprint=(
                evidence.plan_fingerprint if evidence is not None else ""),
            evidence_retrieval_fingerprint=(
                evidence.retrieval_fingerprint if evidence is not None else ""),
            evidence_citation_map=(
                list(evidence.citation_map) if evidence is not None else ()),
            evidence_candidate_chunk_ids=(
                list(evidence.candidate_chunk_ids)
                if evidence is not None else ()),
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
            alpha=alpha,
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
        format_sources,
        _validate_and_repair_citations,
        REFUSAL_MESSAGE,
    )
    from src.retrieval import select_context_candidates
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

    # ── Reranker（chunk-aware）+ 统一 context selector ──
    reranker = _get_reranker()
    if reranker is not None:
        candidates = [
            RetrievalCandidate(
                index=i,
                chunk_id=(metadatas[i] or {}).get("chunk_id", f"chunk_{i}"),
                source_id=(metadatas[i] or {}).get("source_id", ""),
                source_name=(metadatas[i] or {}).get("source_name", "")
                    or (metadatas[i] or {}).get("source", ""),
                text=documents[i] if i < len(documents) else "",
                rrf_score=best_score.get(i),
            )
            for i in top_indices
        ]
        reranked = reranker.rerank(query, candidates, top_k=min(k, 20))
        selected = select_context_candidates(reranked, top_k=min(k, 20), max_per_source=3)
        top_indices = [c.index for c in selected]
    else:
        # 无 reranker 时与评测 A 组一致：仍应用统一 selector（对称）
        candidates = [
            RetrievalCandidate(
                index=i,
                chunk_id=(metadatas[i] or {}).get("chunk_id", f"chunk_{i}"),
                source_id=(metadatas[i] or {}).get("source_id", ""),
                source_name=(metadatas[i] or {}).get("source_name", "")
                    or (metadatas[i] or {}).get("source", ""),
                text=documents[i] if i < len(documents) else "",
                rrf_score=best_score.get(i),
            )
            for i in top_indices
        ]
        selected = select_context_candidates(candidates, top_k=min(k, 20), max_per_source=3)
        top_indices = [c.index for c in selected]

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


# ── Reranker 验证 ──────────────────────────────────────────────────

def validate_reranker(arms: list[str]):
    """验证 B/C 臂所需的 reranker 可用性并返回预检实例。

    B（standard-rerank）和 C（graph-rerank）臂依赖 reranker。
    若 arms 包含这些臂但 reranker 不可用，必须立即失败，
    不能静默降级为未 rerank 的运行。

    A-only 运行时返回 None（无需 reranker），否则返回预检得到的
    reranker 实例，供 run_retrieval_grid / _run_retrieval_arm 复用。

    Args:
        arms: 实验组名称列表

    Returns:
        reranker 实例，A-only 时返回 None

    Raises:
        RuntimeError: 若 B/C 臂需要 reranker 但 _get_reranker() 返回 None
    """
    needs_reranker = (
        ARM_STANDARD_RERANK in arms or ARM_GRAPH_RERANK in arms
    )
    if not needs_reranker:
        return None  # A-only 运行，无需 reranker

    from src.rag import _get_reranker, RAG_RERANKER_MODE
    reranker = _get_reranker()
    if reranker is None:
        raise RuntimeError(
            f"Reranker required for arms {arms} but _get_reranker() returned None. "
            f"Current RAG_RERANKER_MODE={RAG_RERANKER_MODE!r}. "
            f"Set RAG_RERANKER=cross-encoder or remove standard-rerank/graph-rerank from arms."
        )
    return reranker


# ── 检索评测网格（alpha × arm × case） ──────────────────────────────

def run_retrieval_grid(
    active_cases: list[EvalCase],
    arms: list[str],
    alpha_values: list[float],
    model,
    collection,
    bm25,
    all_docs: list[str],
    all_metadatas: list[dict],
    kg,
    query_plan_cache: dict[str, QueryPlan],
    gt_map: dict[str, list[str]],
    chain_map: dict[str, list[EvalCase]],
    reranker=None,
    case_has_reliable_chunk_truth: dict[str, bool] | None = None,
) -> list[RetrievalCaseResult]:
    """运行检索评测网格：alpha × arm × case。

    从 query_plan_cache 获取共享 QueryPlan，确保每个 case 只构建一次，
    所有 arm 和 alpha 复用同一实例。B 组 context IDs 跨 arm 持久化，
    用于 C 组 lift/pollution 计算。

    Args:
        active_cases: 评测 case 列表
        arms: 实验组列表（如 ["standard", "standard-rerank", "graph-rerank"]）
        alpha_values: alpha 网格（如 [1.0, 0.7]）
        model: embedding 模型
        collection: ChromaDB collection
        bm25: BM25 索引
        all_docs: 全部文档文本
        all_metadatas: 全部元数据
        kg: KnowledgeGraph 实例（可选）
        query_plan_cache: case_id -> QueryPlan 映射
        gt_map: case_id -> relevant_chunk_ids 映射
        chain_map: case_id -> 多轮对话链映射
        reranker: 预检得到的 reranker 实例（validate_reranker 返回值）
    """
    all_results: list[RetrievalCaseResult] = []

    for alpha in alpha_values:
        print(f"\n{'=' * 60}")
        print(f"  Alpha = {alpha}")
        print(f"{'=' * 60}")

        # B 组 context IDs 必须跨 arm 持久化，用于 C 组 lift/pollution 计算
        b_context_ids: dict[str, set[str]] = {}

        for arm in arms:
            print(f"\n  Arm: {arm}")

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
                gt_chunk_ids = get_relevant_chunk_ids(
                    case, gt_map,
                    case_has_reliable_chunk_truth=case_has_reliable_chunk_truth,
                )

                # 是否具有可靠的 chunk 真值
                _has_truth = (
                    case_has_reliable_chunk_truth is not None
                    and case_has_reliable_chunk_truth.get(case.id, False)
                )

                # C 组需要 B 的 context 作为 lift/pollution 基线
                if arm == ARM_GRAPH_RERANK and case.id not in b_context_ids:
                    if ARM_STANDARD_RERANK in arms:
                        raise RuntimeError(
                            f"B baseline context missing for case {case.id}. "
                            f"Arm 'standard-rerank' must run before 'graph-rerank'."
                        )
                    else:
                        b_context_ids[case.id] = set()

                # 从缓存获取共享 QueryPlan（同一 case 只计算一次）
                query_plan = query_plan_cache[case.id]

                result = _run_retrieval_arm(
                    case, arm, model, collection, bm25,
                    all_docs, all_metadatas, query_plan, kg, alpha,
                    history=history,
                    ground_truth_chunk_ids=gt_chunk_ids,
                    b_context_chunk_ids=b_context_ids.get(case.id),
                    reranker=reranker,
                    has_chunk_truth=_has_truth,
                )
                all_results.append(result)

                # 记录 B 组 context IDs（跨 arm 持久化）
                if arm == ARM_STANDARD_RERANK:
                    b_context_ids[case.id] = set(result.context_chunk_ids)

    return all_results


def run_generation_grid(
    active_cases: list[EvalCase],
    arms: list[str],
    alpha_values: list[float],
    model,
    collection,
    bm25,
    all_docs: list[str],
    all_metadatas: list[dict],
    kg,
    query_plan_cache: dict[str, QueryPlan],
    gt_map: dict[str, list[str]],
    chain_map: dict[str, list[EvalCase]],
    reranker=None,
    retrieval_results_by_alpha: dict[float, list[RetrievalCaseResult]] | None = None,
) -> list[GenerationCaseResult]:
    """运行生成评测网格：alpha × arm × case。

    复用 QueryPlan 缓存（同一 case 的 rewrite/decompose 只计算一次），
    复用同 alpha 的检索结果做 retrieval_ms 归因；不重复 LLM 规划。
    """
    # 按 (alpha, case_id, arm) 建立检索结果索引，用于生成阶段的延迟归因
    ret_index: dict[tuple[float, str, str], RetrievalCaseResult] = {}
    if retrieval_results_by_alpha:
        for alpha, results in retrieval_results_by_alpha.items():
            for r in results:
                ret_index[(alpha, r.case_id, r.arm)] = r

    # 拒答策略消融（A=standard / B=standard-calibrated）共享证据缓存：
    # 每 (alpha, case) 只构建一次 PreparedAnswerEvidence，两臂分别仅调用
    # 生成步骤（零 rewrite/decompose/retrieve/select 重跑）。
    ablation_evidence: dict[tuple[float, str], object] = {}

    all_results: list[GenerationCaseResult] = []

    for alpha in alpha_values:
        print(f"\n{'=' * 60}")
        print(f"  Generation Alpha = {alpha}")
        print(f"{'=' * 60}")

        for arm in arms:
            print(f"\n  Generation Arm: {arm}")

            for i, case in enumerate(active_cases):
                print(f"    [{i+1}/{len(active_cases)}] {case.id}: {case.query[:50]}...")

                history = None
                if case.query_type == QueryType.MULTI_TURN and case.id in chain_map:
                    chain = chain_map[case.id]
                    turn_idx = next(
                        (j for j, c in enumerate(chain) if c.id == case.id), 0,
                    )
                    history = canonical_history_for_turn(chain, turn_idx)

                gt_chunk_ids = get_relevant_chunk_ids(case, gt_map)

                query_plan = query_plan_cache[case.id]
                retrieval_result = ret_index.get((alpha, case.id, arm))

                is_ablation = arm in REFUSAL_ABLATION_ARMS
                evidence_key = (alpha, case.id)
                gen_result = _run_generation_arm(
                    case, arm, model, collection, bm25,
                    all_docs, all_metadatas, kg, alpha,
                    history=history,
                    ground_truth_chunk_ids=gt_chunk_ids,
                    retrieval_result=retrieval_result,
                    evidence=(ablation_evidence.get(evidence_key)
                              if is_ablation else None),
                    evidence_cache=(ablation_evidence if is_ablation else None),
                    evidence_key=(evidence_key if is_ablation else None),
                    query_plan=(query_plan_cache[case.id]
                                if is_ablation else None),
                )
                all_results.append(gen_result)

    return all_results


def group_generation_results_by_alpha(
    results: list[GenerationCaseResult],
) -> dict[float, list[GenerationCaseResult]]:
    """按 alpha 字段分组生成结果（alpha 隔离）。"""
    results_by_alpha: dict[float, list[GenerationCaseResult]] = {}
    for result in results:
        alpha = result.alpha
        if alpha not in results_by_alpha:
            results_by_alpha[alpha] = []
        results_by_alpha[alpha].append(result)
    return results_by_alpha


# ── Run Manifest ────────────────────────────────────────────────────

def _compute_corpus_hash(corpus_dir: Path, source_files: list[str]) -> str:
    """计算语料文件的完整 SHA-256 hash。"""
    h = hashlib.sha256()
    for source_id in sorted(source_files):
        candidate = corpus_dir / source_id
        if not candidate.exists():
            for f in corpus_dir.iterdir():
                if f.name.lower() == source_id.lower():
                    candidate = f
                    break
        if candidate.exists():
            h.update(candidate.read_bytes())
    return h.hexdigest()


def _compute_dataset_hash(dataset_path: Path) -> str:
    """计算数据集文件的完整 SHA-256 hash。"""
    return hashlib.sha256(dataset_path.read_bytes()).hexdigest()


def _safe_url(url: str) -> str | None:
    """安全规范化 URL：移除 userinfo/query/fragment，保留 scheme://hostname:port/path。"""
    if not url:
        return None
    try:
        from urllib.parse import urlsplit, urlunsplit
        parts = urlsplit(url)
        # 保留 hostname 和 port（hostname 不含端口，netloc 含端口但可能含 userinfo）
        host = parts.hostname or ""
        if host and parts.port:
            host = f"{host}:{parts.port}"
        elif not host:
            host = parts.netloc
        safe = urlunsplit((parts.scheme, host, parts.path, '', ''))
        return safe if safe else None
    except Exception:
        return None


def _sanitize_cli_arg(arg: str) -> str:
    """安全处理 CLI 参数：REDACT 明显凭据值。

    - 匹配 --token/--key/--secret/--password/--api-key 等 flag
    - 匹配 NAME=VALUE 中的关键词
    """
    if not isinstance(arg, str):
        return str(arg)
    lower = arg.lower()
    _sensitive_flags = {
        '--token', '--api-key', '--apikey', '--key', '--secret',
        '--password', '--pass', '--auth', '--authorization',
        '--credential', '--credentials',
    }
    # 检查 flag form: --<name> <value>
    for flag in _sensitive_flags:
        if lower.startswith(flag):
            return f"{arg[:arg.find('=')] if '=' in arg else arg} ***REDACTED***"
        if lower.startswith(flag.replace('--', '-')) or lower.startswith(flag.replace('--', '')):
            return f"{arg} ***REDACTED***"
    # 检查 NAME=VALUE 形式（仅当 key 含敏感词时）
    if '=' in arg:
        key = arg.split('=', 1)[0].lower()
        for sf in _sensitive_flags:
            _sf_clean = sf.lstrip('-')
            if _sf_clean in key:
                return f"{key}=***REDACTED***"
    # 检查 URL 中的凭据
    if '://' in arg and '@' in arg:
        return _safe_url(arg) or f"{arg.split('://')[0]}://***REDACTED***"
    return arg


def _sanitize_cli_args(args: list[str]) -> list[str]:
    """批量安全处理 CLI 参数快照。"""
    return [_sanitize_cli_arg(str(a)) for a in args]



def _git_diff_hash() -> str | None:
    """计算 git diff --binary HEAD 的 SHA-256（干净树返回可重复哈希）。"""
    import subprocess
    try:
        diff_bytes = subprocess.check_output(
            ["git", "diff", "--binary", "HEAD"],
            cwd=str(EVAL_ROOT.parent),
            stderr=subprocess.DEVNULL,
        )
        return hashlib.sha256(diff_bytes).hexdigest()
    except Exception:
        return None


def _index_snapshot_sha256(collection: Any) -> str | None:
    """Index 快照 SHA-256：按 id 排序的 (id, metadata) records。

    失败（collection 不可读等）返回 None；locked-config 后验与
    run manifest 共用此口径。
    """
    try:
        all_data = collection.get()
        ids = all_data.get("ids", [])
        metadatas_list = all_data.get("metadatas") or []
        # 配对排序：按 id 稳定排序 (id, metadata) 对
        records = sorted(
            zip(ids, metadatas_list),
            key=lambda x: x[0] if x[0] else "",
        )
        canonical = hashlib.sha256()
        for rid, rmeta in records:
            canonical.update(str(rid).encode())
            canonical.update(json.dumps(rmeta or {}, sort_keys=True, default=str).encode())
        return canonical.hexdigest()
    except Exception:
        return None


def _kg_snapshot_sha256(kg: Any) -> str | None:
    """KG 快照 SHA-256：nodes/edges/weights/mappings/fingerprint/manifest_version。

    边序列化与 KnowledgeGraph.save 的 payload 口径严格一致（仅
    source/target/weight 三元组），确保"内存对象"与"缓存 load 对象"的
    指纹相同——若用 ``get_edge_data`` 全属性，load 后丢失非 weight 属性
    会导致同一 KG 在 lock 与消费进程算出不同指纹（locked-config 后验
    误拒）。失败返回 None。
    """
    try:
        nodes = sorted(str(n) for n in kg.entity_graph.nodes())
        # 边序列化为可排序元组 (source, target, weight) 后排序，避免
        # dict 间 < 比较在部分 Python 版本/键序下抛 TypeError。
        edges = sorted(
            (
                str(u),
                str(v),
                float(d.get("weight", 1.0)),
            )
            for u, v, d in kg.entity_graph.edges(data=True)
        )
        # 实体/区块映射的 key 可能为任意 JSON 类型（LLM 抽取的实体名），
        # 直接 sorted() 会因不可比较类型抛 TypeError。统一 str 化后排序。
        etc = {
            str(k): sorted(str(x) for x in v) for k, v in sorted(
                getattr(kg, "entity_to_chunks", {}).items(),
                key=lambda kv: str(kv[0]),
            )
        }
        cte = {
            str(k): sorted(str(x) for x in v) for k, v in sorted(
                getattr(kg, "chunk_to_entities", {}).items(),
                key=lambda kv: str(kv[0]),
            )
        }
        canonical = hashlib.sha256()
        canonical.update(json.dumps(nodes, sort_keys=True).encode())
        canonical.update(json.dumps(edges, sort_keys=True).encode())
        canonical.update(json.dumps(etc, sort_keys=True).encode())
        canonical.update(json.dumps(cte, sort_keys=True).encode())
        canonical.update(json.dumps(getattr(kg, "index_fingerprint", None)).encode())
        canonical.update(json.dumps(getattr(kg, "manifest_version", None)).encode())
        return canonical.hexdigest()
    except Exception:
        return None


def build_run_manifest(
    dataset_path: Path,
    corpus_dir: Path,
    source_files: list[str],
    arms: list[str],
    alpha_grid: list[float] | None = None,
    seed: int = 42,
    config_path: Path | None = None,
    active_alpha: float | None = None,
    bootstrap_iterations: int | None = None,
    bootstrap_seed: int | None = None,
    cli_args: list[str] | None = None,
    kg: Any = None,
    collection: Any = None,
) -> dict[str, Any]:
    """构建运行 manifest，记录完整的可复现评测环境。"""
    import subprocess

    # Git 信息 — full SHA + dirty + diff hash
    git_commit = "unknown"
    git_dirty = True
    try:
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(EVAL_ROOT.parent),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        status_out = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=str(EVAL_ROOT.parent),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        git_dirty = bool(status_out)
    except Exception:
        pass

    git_diff_sha = _git_diff_hash()

    # config hash（若 config_path 存在）
    config_sha256 = None
    if config_path and config_path.exists():
        try:
            config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
        except Exception:
            config_sha256 = None

    manifest: dict[str, Any] = {
        "compare_version": COMPARE_VERSION,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "git_diff_sha256": git_diff_sha,
        "dataset": dataset_path.name,
        "dataset_hash": _compute_dataset_hash(dataset_path),
        "corpus_hash": _compute_corpus_hash(corpus_dir, source_files),
        "arms": arms,
        # 每臂 selector policy（S0/S3 防配置漂移；A/B/C 记录生产默认 3）
        "arm_selector_policy": {
            arm: ARM_SELECTOR_MAX_PER_SOURCE[arm] for arm in arms
        },
        "alpha_grid": alpha_grid,
        "active_alpha": active_alpha,
        "seed": seed,
        "config_path": str(config_path) if config_path else None,
        "config_sha256": config_sha256,
    }

    # Bootstrap 参数
    if bootstrap_iterations is not None:
        manifest["bootstrap_iterations"] = bootstrap_iterations
    if bootstrap_seed is not None:
        manifest["bootstrap_seed"] = bootstrap_seed

    # CLI 参数快照（Path → str，凭据脱敏）
    manifest["cli_args"] = _sanitize_cli_args(cli_args or [])

    # 模型版本信息
    try:
        from src.rag import EMBEDDING_MODEL_NAME, DEFAULT_LLM_MODEL, RAG_RERANKER_MODE, RERANKER_MODEL_NAME
        manifest["embedding_model"] = EMBEDDING_MODEL_NAME
        manifest["llm_model"] = os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL)
        manifest["reranker_mode"] = RAG_RERANKER_MODE
        manifest["reranker_model"] = RERANKER_MODEL_NAME
    except Exception:
        manifest["embedding_model"] = "unknown"
        manifest["llm_model"] = "unknown"

    # LLM endpoint（脱敏）— 优先 BASE_URL，回退 LLM_BASE_URL
    raw_url = os.getenv("BASE_URL") or os.getenv("LLM_BASE_URL", "")
    manifest["llm_base_url"] = _safe_url(raw_url)

    # 依赖版本
    manifest["python_version"] = __import__('sys').version.split()[0]
    try:
        import sentence_transformers
        manifest["sentence_transformers_version"] = sentence_transformers.__version__
    except Exception:
        manifest["sentence_transformers_version"] = "unknown"

    # Index snapshot SHA-256 — 按 id 排序的 (id, metadata) records
    if collection is not None:
        manifest["index_sha256"] = _index_snapshot_sha256(collection) or "unknown"
    else:
        manifest["index_sha256"] = "unknown"

    # KG snapshot — 完整 canonical 表示（nodes/edges/weights/mappings/fingerprint）
    if kg is not None:
        kg_sha = _kg_snapshot_sha256(kg)
        if kg_sha is None:
            manifest["kg_sha256"] = "unknown"
            manifest["kg_nodes"] = 0
            manifest["kg_edges"] = 0
        else:
            manifest["kg_sha256"] = kg_sha
            manifest["kg_nodes"] = kg.entity_graph.number_of_nodes()
            manifest["kg_edges"] = kg.entity_graph.number_of_edges()
            manifest["kg_index_fingerprint"] = getattr(kg, "index_fingerprint", None)
            manifest["kg_manifest_version"] = getattr(kg, "manifest_version", None)
    else:
        manifest["kg_sha256"] = None

    # 确认无敏感字段
    _sensitive_keys = {"api_key", "token", "password", "secret", "credential", "authorization"}
    for k in manifest:
        if any(s in str(k).lower() for s in _sensitive_keys):
            # 防御性检查：不应出现
            manifest[k] = "***REDACTED***"

    return manifest


# ── Alpha 分组 ────────────────────────────────────────────────────

def group_retrieval_results_by_alpha(
    results: list[RetrievalCaseResult],
) -> dict[float, list[RetrievalCaseResult]]:
    """按 alpha 字段分组检索结果。

    每个 alpha 值对应独立的结果列表，用于独立 compute_summary、
    独立 C-B 配对和独立保存。主要供 main() 使用。
    """
    results_by_alpha: dict[float, list[RetrievalCaseResult]] = {}
    for result in results:
        alpha = result.alpha
        if alpha not in results_by_alpha:
            results_by_alpha[alpha] = []
        results_by_alpha[alpha].append(result)
    return results_by_alpha


def save_retrieval_results_by_alpha(
    results_by_alpha: dict[float, list[RetrievalCaseResult]],
    alpha_values: list[float],
    output_dir: Path,
    active_cases: list[EvalCase],
    arms: list[str],
    ground_truth: list[GroundTruthEntry],
    dataset_path: Path,
    corpus_dir: Path,
    source_files: list[str],
    seed: int = 42,
    config_path: Path | None = None,
    cli_args: list[str] | None = None,
    kg: Any = None,
    collection: Any = None,
    bootstrap_iterations: int | None = None,
    bootstrap_seed: int | None = None,
    gen_results_by_alpha: dict[float, list[GenerationCaseResult]] | None = None,
    include_retrieval: bool = True,
) -> None:
    """按 alpha 分组计算 summary 并保存独立产物。

    每个 alpha 值独立调用 compute_summary()，多 alpha 时保存到
    output_dir/alpha-{value}/，单 alpha 时保存到 output_dir/（向后兼容）。
    多 alpha 时在 output_dir/ 根额外生成 alpha-grid-summary.json 索引。

    可选参数：
    - gen_results_by_alpha: 若提供，同 alpha 保存 generation-cases.jsonl 与生成 summary
    - include_retrieval: False 时跳过检索产物（generation 阶段仅生成产物）
    """
    alpha_summaries: dict[str, Path] = {}

    for alpha in sorted(results_by_alpha.keys()):
        alpha_results = results_by_alpha[alpha]
        alpha_str = f"{alpha:.2f}".rstrip('0').rstrip('.')

        print(f"\n  Computing summary for alpha={alpha_str}...")
        alpha_summary = compute_summary(
            alpha_results, active_cases, arms,
            bootstrap_iterations=bootstrap_iterations,
            bootstrap_seed=bootstrap_seed,
        )

        if len(alpha_values) > 1:
            alpha_output_dir = output_dir / f"alpha-{alpha_str}"
        else:
            alpha_output_dir = output_dir

        alpha_manifest = build_run_manifest(
            dataset_path, corpus_dir, source_files,
            arms, alpha_values, seed, config_path,
            active_alpha=alpha,
            bootstrap_iterations=bootstrap_iterations,
            bootstrap_seed=bootstrap_seed,
            cli_args=cli_args,
            kg=kg,
            collection=collection,
        )

        if include_retrieval:
            save_results(alpha_output_dir, alpha_manifest, ground_truth, alpha_results, alpha_summary)
            print(f"  ✓ Alpha {alpha_str} retrieval results saved to: {alpha_output_dir}")

        # failures.csv：B/C 对齐（需检索结果，且 arms 含 B/C）
        if include_retrieval and ARM_STANDARD_RERANK in arms and ARM_GRAPH_RERANK in arms:
            b_slice = [r for r in alpha_results if r.arm == ARM_STANDARD_RERANK]
            c_slice = [r for r in alpha_results if r.arm == ARM_GRAPH_RERANK]
            failure_rows = build_failures_csv_rows(b_slice, c_slice, alpha)
            write_failures_csv(alpha_output_dir, failure_rows)

        # 生成产物（若提供）
        if gen_results_by_alpha and alpha in gen_results_by_alpha:
            gen_results = gen_results_by_alpha[alpha]
            gen_summary = compute_summary(
                gen_results, active_cases, arms,
                bootstrap_iterations=bootstrap_iterations,
                bootstrap_seed=bootstrap_seed,
            )
            if not include_retrieval:
                # generation 阶段只有生成产物时，manifest 仍须写入
                save_results(alpha_output_dir, alpha_manifest, ground_truth, gen_results, gen_summary)
            else:
                # full 阶段：追加生成产物（复用同一 manifest）
                _save_generation_results(alpha_output_dir, alpha_manifest, ground_truth, gen_results, gen_summary)
            print(f"  ✓ Alpha {alpha_str} generation results saved to: {alpha_output_dir}")

        alpha_summaries[alpha_str] = alpha_output_dir / "summary.json"

    # 多 alpha 时生成 alpha-grid-summary.json 索引文件
    if len(alpha_values) > 1:
        print(f"\n  Generating alpha-grid-summary.json...")
        grid_index = {
            "compare_version": COMPARE_VERSION,
            "alpha_grid": alpha_values,
            "arms": arms,
            "alphas": {
                alpha_str: {
                    "path": str(path.relative_to(output_dir)),
                    "summary_file": "summary.json",
                }
                for alpha_str, path in sorted(alpha_summaries.items())
            },
        }
        grid_index_path = output_dir / "alpha-grid-summary.json"
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(grid_index_path, 'w', encoding='utf-8') as f:
            json.dump(grid_index, f, indent=2, ensure_ascii=False)
        print(f"  ✓ Alpha grid index saved to: {grid_index_path}")

    print(f"\n  All results saved to: {output_dir}")


# ── Summary 统计 ────────────────────────────────────────────────────

def compute_summary(
    results: list[RetrievalCaseResult | GenerationCaseResult],
    cases: list[EvalCase],
    arms: list[str],
    bootstrap_iterations: int = 10000,
    bootstrap_seed: int = 42,
) -> dict[str, Any]:
    """计算汇总统计。

    Raises:
        ValueError: 若 results 包含多个 alpha 值
    """
    # 拒绝混合 alpha
    alphas_in_results: set[float] = set()
    for r in results:
        if hasattr(r, 'alpha'):
            alphas_in_results.add(r.alpha)  # type: ignore[attr-defined]
    if len(alphas_in_results) > 1:
        raise ValueError(
            f"compute_summary received results with multiple alpha values "
            f"{sorted(alphas_in_results)}. "
            f"Use group_retrieval_results_by_alpha() first."
        )

    # 构建 conversation chains 用于多轮 block 重采样
    chains = build_conversation_chains(cases)

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
                # ── 检索指标 ──
                # chunk/context 指标分母：not should_refuse AND has_chunk_truth
                chunk_valid = [r for r in slice_results
                               if not r.should_refuse and r.has_chunk_truth]
                # excluded_no_chunk_truth：answerable 但无可靠 chunk truth
                answerable = [r for r in slice_results if not r.should_refuse]
                excluded_no_truth = len(answerable) - len(chunk_valid)

                retrieved = [r.candidate_chunk_ids for r in chunk_valid]
                relevant = [r.relevant_chunk_ids for r in chunk_valid]
                metrics = compute_retrieval_metrics(retrieved, relevant) if chunk_valid else {}

                # Context 指标（同样仅可靠 chunk truth）
                ctx_recalls = [r.context_metrics()["context_recall"] for r in chunk_valid]
                ctx_precisions = [r.context_metrics()["context_precision"] for r in chunk_valid]
                metrics["context_recall"] = sum(ctx_recalls) / len(ctx_recalls) if ctx_recalls else 0.0
                metrics["context_precision"] = sum(ctx_precisions) / len(ctx_precisions) if ctx_precisions else 0.0

                # 记录排除数
                metrics["n_chunk_valid"] = len(chunk_valid)
                metrics["excluded_no_chunk_truth"] = excluded_no_truth

                # ── Source-level 指标（独立分母，与 chunk 口径隔离）──
                # source_valid 分母：not should_refuse AND 有 relevant_source_ids。
                # 包含 source-only case（has_chunk_truth=False 但 source 非空），
                # 不被 chunk_truth 过滤——chunk/context/citation 分母仍仅
                # chunk_valid，与此口径互不干扰。
                source_valid = [r for r in slice_results
                                if not r.should_refuse and r.relevant_source_ids]
                n_source_only = sum(1 for r in source_valid if not r.has_chunk_truth)
                # 候选层 source recall@5/10（按去重 source 计）
                sr5 = [r.source_candidate_metrics((5, 10))["source_recall@5"]
                       for r in source_valid]
                sr10 = [r.source_candidate_metrics((5, 10))["source_recall@10"]
                        for r in source_valid]
                metrics["source_recall@5"] = sum(sr5) / len(sr5) if sr5 else 0.0
                metrics["source_recall@10"] = sum(sr10) / len(sr10) if sr10 else 0.0
                # Context 层 source recall / coverage
                csr = [r.context_source_metrics()["context_source_recall"]
                       for r in source_valid]
                csc = [r.context_source_metrics()["context_source_coverage"]
                       for r in source_valid]
                metrics["context_source_recall"] = sum(csr) / len(csr) if csr else 0.0
                metrics["context_source_coverage"] = sum(csc) / len(csc) if csc else 0.0
                metrics["n_source_valid"] = len(source_valid)
                metrics["n_source_only"] = n_source_only

                # 延迟 — p95 使用 nearest-rank（边界安全）
                latencies = [r.total_retrieval_ms for r in slice_results]
                metrics["retrieval_ms_p50"] = nearest_rank_percentile(latencies, 0.50) if latencies else 0.0
                metrics["retrieval_ms_p95"] = nearest_rank_percentile(latencies, 0.95) if latencies else 0.0

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

                # 契约 v2：context-supported 引用有效性（正式 guardrail 口径）
                cs_validities = [r.context_supported_citation_validity
                                 for r in slice_results]
                gen_metrics["context_supported_citation_validity"] = (
                    sum(cs_validities) / len(cs_validities)
                    if cs_validities else 0.0)

                # ── 契约 v2 唯一聚合（分母显式命名） ──
                # 上面两个键为 legacy（deprecated，兼容读取；全体 case 分母，
                # 旧口径值不变）；新 guardrail 必须消费 citation_v2 块中的
                # context_supported_citation_validity_micro /
                # context_supported_answer_rate / no_citation_answer_rate /
                # citation_mention_rate（经 evaluation.citation_aggregation
                # 唯一聚合，禁止在调用方手算；分母为 0 → value=None）。
                _citation_counts = [
                    case_counts_from_result(r) for r in slice_results]
                _citation_agg = aggregate_citations(_citation_counts)
                _citation_agg.check_conservation()
                gen_metrics["citation_v2"] = _citation_agg.to_dict()
                fab_counts = [r.fabricated_citation_count
                              for r in slice_results]
                gen_metrics["fabricated_citation_avg"] = (
                    sum(fab_counts) / len(fab_counts)
                    if fab_counts else 0.0)
                noctx_counts = [r.retrieved_not_in_context_count
                                for r in slice_results]
                gen_metrics["retrieved_not_in_context_avg"] = (
                    sum(noctx_counts) / len(noctx_counts)
                    if noctx_counts else 0.0)

                # 拒答
                refusal_results = [r for r in slice_results if r.should_refuse]
                if refusal_results:
                    correct = sum(1 for r in refusal_results if r.correctly_refused is True)
                    gen_metrics["false_answer_rate"] = 1.0 - (correct / len(refusal_results))
                answerable = [r for r in slice_results if not r.should_refuse]
                if answerable:
                    false_refusals = sum(1 for r in answerable if r.correctly_refused is False)
                    gen_metrics["false_refusal_rate"] = false_refusals / len(answerable)

                # 延迟 — p95 使用 nearest-rank
                latencies = [r.total_ms for r in slice_results]
                gen_metrics["total_ms_p50"] = nearest_rank_percentile(latencies, 0.50) if latencies else 0.0
                gen_metrics["total_ms_p95"] = nearest_rank_percentile(latencies, 0.95) if latencies else 0.0

                # Token
                tokens = [r.total_tokens for r in slice_results if r.total_tokens is not None]
                gen_metrics["total_tokens_avg"] = sum(tokens) / len(tokens) if tokens else 0.0

                # 错误率
                errors = sum(1 for r in slice_results if r.error is not None)
                gen_metrics["error_rate"] = errors / len(slice_results) if slice_results else 0.0

                summary[arm_key][slice_name] = gen_metrics

    # 配对差值 (C - B) + bootstrap 95% CI（仅 RetrievalCaseResult；
    # GenerationCaseResult 由下方 McNemar 处理，bootstrap_ci_cb 访问
    # .has_chunk_truth/.context_metrics() 等 retrieval-only 字段，对生成
    # 结果调用会触发 AttributeError，故以 isinstance 守卫跳过。）
    if ARM_GRAPH_RERANK in arms and ARM_STANDARD_RERANK in arms:
        c_results = by_arm.get(ARM_GRAPH_RERANK, [])
        b_results = by_arm.get(ARM_STANDARD_RERANK, [])
        if c_results and b_results and isinstance(c_results[0], RetrievalCaseResult):
            paired_deltas: dict[str, dict] = {}
            for slice_name, slice_cases in all_slices.items():
                slice_ids = {c.id for c in slice_cases}
                # 过滤到该切片
                b_slice = [r for r in b_results if r.case_id in slice_ids]
                c_slice = [r for r in c_results if r.case_id in slice_ids]

                # 用现有 chains 信息做 block 重采样（若有）
                ci_result = paired_bootstrap_ci_cb(
                    b_slice, c_slice,
                    chains=chains,
                    n_iter=bootstrap_iterations,
                    seed=bootstrap_seed,
                )
                if ci_result:
                    paired_deltas[slice_name] = ci_result

            summary["paired_cb"] = paired_deltas

    # McNemar exact test：生成结果的配对二元错误（拒答/false refusal），C vs B
    if ARM_GRAPH_RERANK in arms and ARM_STANDARD_RERANK in arms:
        c_gen = by_arm.get(ARM_GRAPH_RERANK, [])
        b_gen = by_arm.get(ARM_STANDARD_RERANK, [])
        if c_gen and b_gen and isinstance(c_gen[0], GenerationCaseResult):
            b_by_id = {r.case_id: r for r in b_gen}
            b_errors: list[bool] = []
            c_errors: list[bool] = []
            for c_r in c_gen:
                b_r = b_by_id.get(c_r.case_id)
                if b_r is None:
                    continue
                b_err = _generation_binary_error(b_r)
                c_err = _generation_binary_error(c_r)
                if b_err is None or c_err is None:
                    continue
                b_errors.append(b_err)
                c_errors.append(c_err)
            if b_errors:
                summary["mcnemar"] = mcnemar_exact(b_errors, c_errors)

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

    # per-case results (JSONL) — 检索或生成产物按阶段命名
    is_generation = bool(per_case_results) and isinstance(
        per_case_results[0], GenerationCaseResult,
    )
    cases_filename = "generation-cases.jsonl" if is_generation else "retrieval-cases.jsonl"
    with open(output_dir / cases_filename, "w", encoding="utf-8") as f:
        for r in per_case_results:
            d = asdict(r)
            f.write(json.dumps(d, ensure_ascii=False, default=_json_default) + "\n")

    # summary.json
    with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=_json_default)


def _save_generation_results(
    output_dir: Path,
    manifest: dict[str, Any],
    ground_truth: list[GroundTruthEntry],
    gen_results: list[GenerationCaseResult],
    gen_summary: dict[str, Any],
) -> None:
    """full 阶段追加保存生成产物（不覆盖检索产物）。

    - generation-cases.jsonl：生成结果
    - generation-summary.json：生成 summary（与检索 summary.json 分开）
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_dir / "generation-cases.jsonl", "w", encoding="utf-8") as f:
        for r in gen_results:
            d = asdict(r)
            f.write(json.dumps(d, ensure_ascii=False, default=_json_default) + "\n")

    with open(output_dir / "generation-summary.json", "w", encoding="utf-8") as f:
        json.dump(gen_summary, f, ensure_ascii=False, indent=2, default=_json_default)


# ── p95 / percentile helpers ─────────────────────────────────────────

def nearest_rank_percentile(
    values: list[float],
    pct: float,
) -> float:
    """Nearest-rank percentile（边界安全）。

    ceil(pct*n) - 1，保证下标合法（空列表返回 0.0）。
    """
    if not values:
        return 0.0
    n = len(values)
    sorted_vals = sorted(values)
    # nearest-rank: rank = ceil(pct * n)
    import math
    rank = max(1, math.ceil(pct * n))
    idx = rank - 1
    if idx >= n:
        idx = n - 1
    return sorted_vals[idx]


# ── Bootstrap CI ─────────────────────────────────────────────────────

def paired_bootstrap_ci_cb(
    b_results: list[RetrievalCaseResult],
    c_results: list[RetrievalCaseResult],
    chains: dict[str, list[EvalCase]] | None = None,
    n_iter: int = 10000,
    seed: int = 42,
) -> dict[str, Any] | None:
    """Case-level paired bootstrap 95% CI for C-B context_recall delta。

    需求：
    - 仅配对两侧均 answerable 且 has_chunk_truth 的结果
    - 多轮按 conversation block 重采样（block 为独立抽样单位）
    - 非多轮 case 自己是一个 block
    """
    # 构建配对的 case_id → delta
    b_by_id: dict[str, RetrievalCaseResult] = {r.case_id: r for r in b_results}
    c_pair: list[tuple[str, float]] = []  # (case_id, delta)
    for c_r in c_results:
        b_r = b_by_id.get(c_r.case_id)
        if b_r is None:
            continue
        # 过滤：两侧均 answerable 且 has_chunk_truth
        if c_r.should_refuse or b_r.should_refuse:
            continue
        if not c_r.has_chunk_truth or not b_r.has_chunk_truth:
            continue
        c_recall = c_r.context_metrics()["context_recall"]
        b_recall = b_r.context_metrics()["context_recall"]
        c_pair.append((c_r.case_id, c_recall - b_recall))

    if not c_pair:
        return None  # 无可配对数据，不生成 CI

    # 构建 block：每个 block 是 (case_id, delta) 列表
    # 多轮 chain → 一个 block 包含该 chain 的所有 turn
    block_map: dict[str, list[str]] = {}  # root_id → [case_id, ...]
    if chains:
        for root_id, chain_cases in chains.items():
            block_map[root_id] = [c.id for c in chain_cases]

    blocks: list[list[tuple[str, float]]] = []
    assigned: set[str] = set()
    for case_id, delta in c_pair:
        if case_id in assigned:
            continue
        # 寻找此 case 所属的 block
        root = None
        for root_id, case_ids in block_map.items():
            if case_id in case_ids:
                root = root_id
                break
        if root:
            block_pairs = [(cid, d) for (cid, d) in c_pair if cid in block_map[root]]
            blocks.append(block_pairs)
            for cid in block_map[root]:
                assigned.add(cid)
        else:
            # 独立 case（非多轮）
            blocks.append([(case_id, delta)])
            assigned.add(case_id)

    # Bootstrap
    import random
    rng = random.Random(seed)
    n_blocks = len(blocks)
    means: list[float] = []
    for _ in range(n_iter):
        # 有放回抽样 block
        sampled_pairs: list[tuple[str, float]] = []
        for _ in range(n_blocks):
            block = rng.choice(blocks)
            sampled_pairs.extend(block)
        if sampled_pairs:
            means.append(sum(d for _, d in sampled_pairs) / len(sampled_pairs))

    if not means:
        return None

    means_sorted = sorted(means)
    # 95% CI from bootstrap distribution
    ci_low = nearest_rank_percentile(means_sorted, 0.025)
    ci_high = nearest_rank_percentile(means_sorted, 0.975)
    mean_delta = sum(d for _, d in c_pair) / len(c_pair)

    return {
        "mean_delta": mean_delta,
        "n_pairs": len(c_pair),
        "n_blocks": n_blocks,
        "ci95_low": ci_low,
        "ci95_high": ci_high,
        "bootstrap_iterations": n_iter,
        "bootstrap_seed": seed,
    }


def mcnemar_exact(
    binary_b: list[bool],
    binary_c: list[bool],
) -> dict[str, Any]:
    """两侧 McNemar exact test（配对二元错误）。

    纯标准库实现（math.comb 二项式），确定性：
    - discordant pairs: n01 = B 对 C 错, n10 = B 错 C 对
    - exact two-sided p = 2 * sum_{k=0}^{min(n01,n10)} C(n, k) 0.5^n, 上限 1.0
    - 零 discordant pairs 时 p = 1.0（无证据）

    Args:
        binary_b: B 臂各 case 的二元错误（True = 错）
        binary_c: C 臂各 case 的二元错误（True = 错），须与 B 同序配对

    Returns:
        可 JSON 序列化的统计字段
    """
    import math

    if len(binary_b) != len(binary_c):
        raise ValueError(
            f"mcnemar_exact requires equal-length paired arrays, "
            f"got B={len(binary_b)}, C={len(binary_c)}"
        )

    n01 = sum(1 for b, c in zip(binary_b, binary_c) if (not b) and c)
    n10 = sum(1 for b, c in zip(binary_b, binary_c) if b and (not c))
    n = n01 + n10

    if n == 0:
        p_value = 1.0
    else:
        k_min = min(n01, n10)
        # two-sided exact binomial: 2 * P(X <= min(n01,n10)), X ~ Bin(n, 0.5)
        tail = sum(
            math.comb(n, k) * (0.5 ** n)
            for k in range(k_min + 1)
        )
        p_value = min(1.0, 2.0 * tail)

    return {
        "n_pairs": len(binary_b),
        "n_discordant": n,
        "b_only": n10,
        "c_only": n01,
        "p_value": p_value,
        "test": "mcnemar_exact_two_sided",
    }


def _generation_binary_error(gen: GenerationCaseResult) -> bool | None:
    """将生成结果转为二元错误（供 McNemar 使用）。

    - should_refuse: 错误 = 未正确拒答（false answer）
    - answerable: 错误 = 误拒答（false refusal）
    - 无法判定时返回 None（排除）
    """
    if gen.correctly_refused is None:
        return None
    if gen.should_refuse:
        return not gen.correctly_refused
    return gen.correctly_refused is False


def build_failures_csv_rows(
    b_results: list[RetrievalCaseResult],
    c_results: list[RetrievalCaseResult],
    alpha: float,
) -> list[dict[str, Any]]:
    """构建 failures.csv 行：B/C 按 case 对齐，win/loss/flip + lift/pollution。

    仅对 has_chunk_truth 且非拒答的 case 给出 win/loss/equal 相关性结论；
    无可靠 chunk 真值的 case 标记 outcome=""，按是否有 source 真值在 notes 区分：
    - ``source_level_only``：relevant_source_ids 非空，可评估 source 而非 chunk；
    - ``no_reliable_chunk_truth``：无任何真值。
    两者均不计入 chunk-level 相关性结论，绝不伪造 win/loss/equal。
    """
    b_by_id: dict[str, RetrievalCaseResult] = {r.case_id: r for r in b_results}
    rows: list[dict[str, Any]] = []

    for c_r in sorted(c_results, key=lambda r: r.case_id):
        b_r = b_by_id.get(c_r.case_id)
        if b_r is None:
            continue

        row: dict[str, Any] = {
            "case_id": c_r.case_id,
            "alpha": alpha,
            "query_type": c_r.query_type,
            "b_context_recall": None,
            "c_context_recall": None,
            "outcome": "",
            "graph_lift": c_r.graph_lift,
            "graph_pollution": c_r.graph_pollution,
            "flip": c_r.graph_lift or c_r.graph_pollution,
            "has_chunk_truth": c_r.has_chunk_truth,
            "notes": "",
        }

        if b_r.should_refuse or c_r.should_refuse:
            row["notes"] = "refusal_case"
            rows.append(row)
            continue

        if not c_r.has_chunk_truth:
            # 拆分语义：source-only case 有相关 source 真值但无 chunk 真值，
            # 属于可评估 source recall 的样本，而非"无任何真值"。
            # 不伪造 chunk-level win/loss（outcome 保持空），不计算 b/c_context_recall。
            # flip 由 graph_lift/graph_pollution 直读（source-only 因
            # relevant_chunk_ids 为空，lift/pollution 天然为 False → flip=False）。
            if c_r.relevant_source_ids:
                row["notes"] = "source_level_only"
            else:
                row["notes"] = "no_reliable_chunk_truth"
            rows.append(row)
            continue

        b_recall = b_r.context_metrics()["context_recall"]
        c_recall = c_r.context_metrics()["context_recall"]
        row["b_context_recall"] = b_recall
        row["c_context_recall"] = c_recall
        if c_recall > b_recall + 1e-9:
            row["outcome"] = "win"
        elif c_recall < b_recall - 1e-9:
            row["outcome"] = "loss"
        else:
            row["outcome"] = "equal"
        rows.append(row)

    return rows


def write_failures_csv(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    """写入 failures.csv（确定列顺序）。"""
    import csv

    if not rows:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case_id", "alpha", "query_type",
        "b_context_recall", "c_context_recall",
        "outcome", "graph_lift", "graph_pollution", "flip",
        "has_chunk_truth", "notes",
    ]
    path = output_dir / "failures.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


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

    # 默认使用 sys.argv[1:]（真实 CLI 启动路径）
    if argv is None:
        argv = sys.argv[1:]

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
        choices=ALL_ARMS + SELECTOR_ABLATION_ARMS + REFUSAL_ABLATION_ARMS,
        help="实验组 (默认: 全部三组；selector 消融: "
             "selector-unlimited/selector-cap3；拒答策略消融: "
             "standard/standard-calibrated)",
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
        "--lock", action="store_true",
        help="生成 locked-config.json（仅允许 --split development，"
             "必须显式提供 --alpha；alpha 不得从结果自动选择）",
    )
    parser.add_argument(
        "--alpha", type=float, default=None,
        help="显式锁定的单一 alpha（--lock 生成模式必需）",
    )
    parser.add_argument(
        "--reviewed-truth", type=Path, default=None,
        help="人工审阅 overlay 路径（evaluation.review_apply 生成）；"
             "提供后在任何 retrieval/LLM 调用前严格应用人工决定",
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
    parser.add_argument(
        "--bootstrap-iterations", type=int, default=10000,
        help="Bootstrap 迭代次数 (default: 10000)",
    )
    parser.add_argument(
        "--bootstrap-seed", type=int, default=42,
        help="Bootstrap 随机种子 (default: 42)",
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
        split_fp = compute_split_fingerprint(dev_cases, holdout_cases)
    elif args.split == "development":
        dev_cases, holdout_cases = group_aware_split(cases, seed=args.seed)
        split_fp = compute_split_fingerprint(dev_cases, holdout_cases)
    else:  # holdout
        # 完整拆分对与 development 运行同口径（指纹必须基于完整 pair，
        # 否则 holdout 运行时计算的指纹与锁定时的指纹不一致）
        full_dev, full_holdout = group_aware_split(cases, seed=args.seed)
        dev_cases, holdout_cases = [], full_holdout
        split_fp = compute_split_fingerprint(full_dev, full_holdout)

    active_cases = dev_cases if args.split == "development" else holdout_cases if args.split == "holdout" else cases
    print(f"\n  Active cases: {len(active_cases)} ({args.split})")
    # split 指纹：dataset/seed/split 算法的确定性哨兵（锁定配置 fail-closed 用）
    print(f"  Split fingerprint: {split_fp} "
          f"(dev={len(dev_cases)}, holdout={len(holdout_cases)})")

    # ── Locked config 预检（任何索引/LLM/模型工作之前，fail-closed）──
    # 来自 evaluation.locked_config：版本化、确定性、无密钥的配置锁定。
    lock = None
    locked_alpha = None
    if args.lock:
        if args.validate_only:
            print("Error: --lock cannot be combined with --validate-only",
                  file=sys.stderr)
            return 1
        if args.split != "development":
            print("Error: --lock only allowed with --split development "
                  "(alpha must be locked from development results, never holdout)",
                  file=sys.stderr)
            return 1
        if args.alpha is None:
            print("Error: --lock requires an explicit --alpha value "
                  "(alpha is never auto-selected from results)", file=sys.stderr)
            return 1
        if args.config is not None:
            print("Error: --lock cannot be combined with --config "
                  "(generating a lock while validating another is ambiguous)",
                  file=sys.stderr)
            return 1
    if args.split == "holdout" and not args.config:
        print("Error: --split holdout requires --config "
              "(locked-config.json); refusing to run unverified holdout",
              file=sys.stderr)
        return 1
    if args.config:
        from evaluation.locked_config import (
            LockedConfigError,
            collect_runtime_budgets,
            collect_runtime_models,
            compute_effective_prompt_ids,
            default_refusal_policy_by_arm,
            load_locked_config,
            validate_locked_config,
        )
        try:
            lock = load_locked_config(args.config)
        except LockedConfigError as exc:
            print(f"Error: invalid locked config {args.config}:",
                  file=sys.stderr)
            for d in exc.diffs:
                print(f"  - {d}", file=sys.stderr)
            return 1
        models = collect_runtime_models()
        diffs = validate_locked_config(
            lock,
            dataset_name=dataset_path.name,
            dataset_sha256=_compute_dataset_hash(dataset_path),
            corpus_sha256=_compute_corpus_hash(args.corpus_dir, sorted(source_files)),
            seed=args.seed,
            arms=args.arms,
            alpha_grid=args.alpha_grid,
            embedding_model=models["embedding_model"],
            llm_model=models["llm_model"],
            reranker_mode=models["reranker_mode"],
            reranker_model=models["reranker_model"],
            prompt_id=models["prompt_id"],
            budgets=collect_runtime_budgets(),
            split_fingerprint=split_fp,
            arm_selector_policy={
                arm: ARM_SELECTOR_MAX_PER_SOURCE[arm] for arm in args.arms
            },
            # 拒答策略消融：per-arm 策略映射与有效提示指纹必须与锁一致
            # （策略正文/策略名/臂映射任一漂移都在 LLM 前拒绝）
            refusal_policy=default_refusal_policy_by_arm(args.arms),
            effective_prompt_ids=compute_effective_prompt_ids(
                default_refusal_policy_by_arm(args.arms)),
        )
        if diffs:
            print("Error: locked config mismatch — refusing to run:",
                  file=sys.stderr)
            for d in diffs:
                print(f"  - {d}", file=sys.stderr)
            return 1
        locked_alpha = lock["locked_alpha"]
        print(f"  ✓ Locked config verified (locked alpha={locked_alpha})")

    # ── Reviewed truth overlay 预检（prepare_index 前，fail-closed）──
    # 加载并验证 overlay 与当前 dataset 匹配；entries/relevance 的
    # case_id 存在性早期检查。GT 精确应用在本轮 GT 构建后进行。
    overlay = None
    source_only_case_ids: list[str] = []
    if args.reviewed_truth:
        try:
            overlay = load_reviewed_truth_overlay(args.reviewed_truth)
        except ValueError as exc:
            print(f"Error: invalid reviewed-truth overlay: {exc}",
                  file=sys.stderr)
            return 1
        if overlay["dataset_sha256"] != _compute_dataset_hash(dataset_path):
            print("Error: reviewed-truth overlay dataset_sha256 mismatch — "
                  "stale overlay (refusing to run)", file=sys.stderr)
            return 1
        case_ids = {c.id for c in cases}
        unknown_entries = [
            e["case_id"] for e in overlay["entries"]
            if e["case_id"] not in case_ids
        ]
        if unknown_entries:
            print(f"Error: overlay entries reference unknown case_ids: "
                  f"{sorted(set(unknown_entries))}", file=sys.stderr)
            return 1
        answerable_ids = {c.id for c in cases if not c.should_refuse}
        unknown_levels = [
            c["case_id"] for c in overlay["case_relevance_levels"]
            if c["case_id"] not in answerable_ids
        ]
        if unknown_levels:
            print(f"Error: overlay case_relevance_levels reference "
                  f"non-answerable case_ids: {sorted(set(unknown_levels))}",
                  file=sys.stderr)
            return 1
        # overlay entries 引用的标注必须存在于 dataset：dataset 中无该
        # 标注则本次 GT 必然无法匹配（prepare_index 前拒绝陈旧 overlay）
        dataset_norms: dict[str, list[str]] = {}
        for case in cases:
            dataset_norms[case.id] = [
                _normalize_text(rc.chunk_text_snippet)
                for rc in case.relevant_chunks
            ]
        unknown_annotations = sorted({
            e["case_id"] for e in overlay["entries"]
            if e["normalized_snippet"] not in dataset_norms.get(e["case_id"], [])
        })
        if unknown_annotations:
            print(f"Error: overlay entries reference annotations absent "
                  f"from dataset: {unknown_annotations} (stale overlay)",
                  file=sys.stderr)
            return 1
        print("  ✓ Reviewed-truth overlay loaded "
              "(dataset hash verified, case refs valid)")

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
    # force_rebuild=False：复用已构建的索引（collection 已存在且配置匹配时
    # 不重建），保证跨进程评测 index_sha256 稳定，locked-config 后验可复核。
    # 首次运行或源文件变化时 _ensure_client_and_check_rebuild 仍会重建。
    model, collection, bm25, all_docs, all_metadatas = prepare_index(
        file_paths, args.collection_name, force_rebuild=False,
    )
    print(f"Index built: {len(all_docs)} chunks")

    # ── 构建 Graph 索引（如果需要） ──
    kg = None
    if ARM_GRAPH_RERANK in args.arms:
        from src.graph_rag import KnowledgeGraph
        all_data = collection.get()
        all_ids = all_data["ids"]
        # KG 磁盘缓存：LLM 实体抽取非确定性使每次重建的 KG 指纹漂移，
        # locked-config 后验将拒绝。用 index_fingerprint 作为缓存有效性
        # 判据，同一索引复用同一 KG 对象 → kg_sha256 稳定可复核。
        from src.rag import index_fingerprint
        kg_file = _kg_cache_path(args.collection_name)
        current_fp = index_fingerprint(all_ids, all_metadatas)
        kg = _load_kg_cache(kg_file, current_fp)
        if kg is None:
            print("\nBuilding Knowledge Graph...")
            kg = KnowledgeGraph()
            kg.build_from_chunks(all_docs, chunk_ids=all_ids, verbose=True)
            _save_kg_cache(kg, kg_file, current_fp)
            print(f"KG built: {kg.entity_graph.number_of_nodes()} entities, "
                  f"{kg.entity_graph.number_of_edges()} edges")
        else:
            print(f"KG loaded from cache: {kg.entity_graph.number_of_nodes()} "
                  f"entities, {kg.entity_graph.number_of_edges()} edges")

    # ── Locked config 后验：index/KG 指纹（预检通过后才构建索引，fail-closed）──
    # 预检阶段无法计算 index/KG 指纹；此处用实际构建结果复核，任何不一致都拒绝。
    if lock is not None:
        from evaluation.locked_config import validate_locked_config
        diffs = validate_locked_config(
            lock,
            index_sha256=_index_snapshot_sha256(collection),
            kg_sha256=_kg_snapshot_sha256(kg) if kg is not None else None,
        )
        if diffs:
            print("Error: locked config index/KG fingerprint mismatch — "
                  "refusing to run:", file=sys.stderr)
            for d in diffs:
                print(f"  - {d}", file=sys.stderr)
            return 1

    # ── 构建 ground truth map ──
    print("\nBuilding ground truth map...")
    ground_truth = build_ground_truth_map(cases, all_metadatas, all_docs)

    # ── 应用人工审阅 overlay（若有）——精确匹配，任何不一致都失败 ──
    # 位置在 gt_map 构建之前：confirmed 提升为可靠真值、rejected 排除，
    # 之后 gt_map/case_has_reliable_chunk_truth 使用更新后的状态。
    if overlay is not None:
        try:
            ground_truth, source_only_case_ids = apply_reviewed_truth_overlay(
                ground_truth, overlay,
            )
        except ValueError as exc:
            print(f"Error: reviewed-truth overlay application failed — "
                  f"refusing to run: {exc}", file=sys.stderr)
            return 1
        print(f"  Applied reviewed truth overlay: "
              f"{len(source_only_case_ids)} source-only cases")

    # 转为 case_id -> chunk_ids 映射：仅纳入可靠的 chunk 真值
    #   - exact：自动纳入
    #   - overlap / parent：仅 reviewer=confirmed 才纳入
    #   - source_fallback / unmatched：永久排除
    gt_map: dict[str, list[str]] = {}
    case_has_reliable_chunk_truth: dict[str, bool] = {}
    for entry in ground_truth:
        if entry.match_method in ("source_fallback", "unmatched"):
            continue
        # 可靠条件：exact（任意 reviewer），或 overlap/parent 且 reviewer=confirmed
        is_reliable = (
            entry.match_method == "exact"
            or (
                entry.match_method in ("overlap", "parent")
                and entry.reviewer_status == "confirmed"
            )
        )
        if is_reliable:
            gt_map.setdefault(entry.case_id, []).extend(entry.matched_chunk_ids)
            case_has_reliable_chunk_truth[entry.case_id] = True
    # 标记有可靠 chunk 真值的 case
    for case in active_cases:
        if case.id not in case_has_reliable_chunk_truth:
            case_has_reliable_chunk_truth[case.id] = False

    reliable_count = sum(1 for v in case_has_reliable_chunk_truth.values() if v)
    exclude_count = sum(1 for c in active_cases if not c.should_refuse
                        and not case_has_reliable_chunk_truth.get(c.id, False))
    print(f"  Ground truth entries: {len(ground_truth)}")
    exact_count = sum(1 for e in ground_truth if e.match_method == "exact")
    fallback_count = sum(1 for e in ground_truth if e.match_method == "source_fallback")
    print(f"  Exact matches: {exact_count}, Source fallbacks: {fallback_count}")
    print(f"  Cases with reliable chunk truth: {reliable_count}/{len(active_cases)} "
          f"(excluded: {exclude_count} answerable without chunk truth)")

    # ── 真值门禁（使用 overlay 后，在 QueryPlan/retrieval 前 fail-closed）──
    # source-only case 明确计为 source 级并继续从 chunk/context/citation
    # 分母排除（case_has_reliable_chunk_truth=False，现有口径不倒退）；
    # chunk-level 无可靠真值或 reject 导致无真值且无显式 source 决定 → 失败。
    if overlay is not None:
        gate_errors = enforce_truth_gate(
            active_cases, case_has_reliable_chunk_truth,
            overlay, source_only_case_ids,
        )
        if gate_errors:
            print("Error: truth gate failed — refusing formal comparison:",
                  file=sys.stderr)
            for e in gate_errors:
                print(f"  - {e}", file=sys.stderr)
            return 1
        print(f"  ✓ Truth gate passed; source-only cases: "
              f"{len(source_only_case_ids)} (excluded from chunk/context/"
              f"citation denominators; source recall not implemented)")

    # ── 构建多轮链 ──
    chains = build_conversation_chains(cases)
    chain_map: dict[str, list[EvalCase]] = {}
    for root_id, chain in chains.items():
        for c in chain:
            chain_map[c.id] = chain

    # ── 验证 reranker 可用性（B/C 臂必需） ──
    print("\nValidating reranker availability...")
    reranker_instance = validate_reranker(args.arms)
    if reranker_instance is not None:
        print("  ✓ Reranker validation passed (instance obtained)")
    else:
        print("  ✓ A-only run, no reranker needed")

    # ── 构建 QueryPlan 缓存（alpha/arm 循环外，每个 case 只计算一次） ──
    print("\nBuilding query plan cache (one LLM call per case)...")
    if args.lock:
        # --lock 模式：只运行显式锁定的单一 alpha
        alpha_values = [args.alpha]
    elif lock is not None:
        # 已校验：alpha grid（若提供）必须恰好等于锁定值
        alpha_values = args.alpha_grid or [locked_alpha]
    else:
        alpha_values = args.alpha_grid or [0.7]
    query_plan_cache = build_query_plan_cache(
        active_cases, model, collection, bm25,
        all_docs, all_metadatas, chain_map=chain_map,
        arms=args.arms, alpha_values=alpha_values, kg=kg,
    )
    print(f"  Query plan cache built: {len(query_plan_cache)} plans")

    # ── 运行检索评测网格（generation/full 也需检索结果做 context 归因） ──
    output_dir = args.output or (EVAL_ROOT.parent / "results" / "graph-gate" / args.split)

    # ── Locked config 生成（仅 development、显式 --alpha；锁配置与指纹） ──
    # 生成于索引/KG 构建之后以记录指纹；不含任何结果指标，也不读 holdout。
    if args.lock:
        from evaluation.locked_config import (
            build_locked_config,
            collect_runtime_budgets,
            collect_runtime_models,
            compute_effective_prompt_ids,
            default_refusal_policy_by_arm,
            save_locked_config,
        )
        models = collect_runtime_models()
        index_sha = _index_snapshot_sha256(collection)
        kg_sha = _kg_snapshot_sha256(kg) if kg is not None else None
        try:
            lock_cfg = build_locked_config(
                locked_alpha=args.alpha,
                dataset_name=dataset_path.name,
                dataset_sha256=_compute_dataset_hash(dataset_path),
                corpus_sha256=_compute_corpus_hash(args.corpus_dir, sorted(source_files)),
                seed=args.seed,
                arms=args.arms,
                embedding_model=models["embedding_model"],
                llm_model=models["llm_model"],
                reranker_mode=models["reranker_mode"],
                reranker_model=models["reranker_model"],
                prompt_id=models["prompt_id"],
                budgets=collect_runtime_budgets(),
                index_sha256=index_sha,
                kg_sha256=kg_sha,
                split_fingerprint=split_fp,
                arm_selector_policy={
                    arm: ARM_SELECTOR_MAX_PER_SOURCE[arm] for arm in args.arms
                },
                refusal_policy=default_refusal_policy_by_arm(args.arms),
                effective_prompt_ids=compute_effective_prompt_ids(
                    default_refusal_policy_by_arm(args.arms)),
            )
        except ValueError as exc:
            # fail-closed：快照无法计算（None/坏格式）时不写未锁定的 lock
            print(f"Error: cannot generate locked config: {exc}",
                  file=sys.stderr)
            return 1
        lock_path = output_dir / "locked-config.json"
        save_locked_config(lock_cfg, lock_path)
        # 供 run manifest 记录 config_sha256（build_run_manifest 读取 config_path）
        args.config = lock_path
        print(f"  ✓ Locked config written: {lock_path} (alpha={args.alpha})")

    all_results = run_retrieval_grid(
        active_cases=active_cases,
        arms=args.arms,
        alpha_values=alpha_values,
        model=model,
        collection=collection,
        bm25=bm25,
        all_docs=all_docs,
        all_metadatas=all_metadatas,
        kg=kg,
        query_plan_cache=query_plan_cache,
        gt_map=gt_map,
        chain_map=chain_map,
        reranker=reranker_instance,
        case_has_reliable_chunk_truth=case_has_reliable_chunk_truth,
    )

    results_by_alpha = group_retrieval_results_by_alpha(all_results)

    # ── 生成阶段（generation/full）：复用 QueryPlan 缓存与检索结果 ──
    gen_results_by_alpha: dict[float, list[GenerationCaseResult]] | None = None
    if args.phase in ("generation", "full"):
        print(f"\n{'=' * 60}")
        print("  Running generation orchestration...")
        print(f"{'=' * 60}")
        gen_results = run_generation_grid(
            active_cases=active_cases,
            arms=args.arms,
            alpha_values=alpha_values,
            model=model,
            collection=collection,
            bm25=bm25,
            all_docs=all_docs,
            all_metadatas=all_metadatas,
            kg=kg,
            query_plan_cache=query_plan_cache,
            gt_map=gt_map,
            chain_map=chain_map,
            reranker=reranker_instance,
            retrieval_results_by_alpha=results_by_alpha,
        )
        gen_results_by_alpha = group_generation_results_by_alpha(gen_results)

    # ── 按 alpha 分组并保存独立结果 ──
    print(f"\n{'=' * 60}")
    print("  Grouping results by alpha and saving...")
    print(f"{'=' * 60}")

    save_retrieval_results_by_alpha(
        results_by_alpha=results_by_alpha,
        alpha_values=alpha_values,
        output_dir=output_dir,
        active_cases=active_cases,
        arms=args.arms,
        ground_truth=ground_truth,
        dataset_path=dataset_path,
        corpus_dir=args.corpus_dir,
        source_files=sorted(source_files),
        seed=args.seed,
        config_path=args.config,
        cli_args=argv,
        kg=kg,
        collection=collection,
        bootstrap_iterations=args.bootstrap_iterations,
        bootstrap_seed=args.bootstrap_seed,
        gen_results_by_alpha=gen_results_by_alpha,
        include_retrieval=(args.phase in ("retrieval", "full")),
    )

    # ── 打印关键指标（使用最后一个 alpha 的 summary） ──
    if not results_by_alpha:
        print(f"\n{'=' * 60}")
        print("  No results to display")
        print(f"{'=' * 60}")
        return 0

    print(f"\n{'=' * 60}")
    print("  Key Metrics Summary")
    print(f"{'=' * 60}")

    # 对于多 alpha 运行，打印最后一个 alpha 的 summary（通常是默认值 0.7）
    last_alpha = max(results_by_alpha.keys())
    last_alpha_str = f"{last_alpha:.2f}".rstrip('0').rstrip('.')
    # generation/full 阶段优先显示生成 summary；否则显示检索 summary
    if gen_results_by_alpha and last_alpha in gen_results_by_alpha:
        summary = compute_summary(
            gen_results_by_alpha[last_alpha], active_cases, args.arms,
            bootstrap_iterations=args.bootstrap_iterations,
            bootstrap_seed=args.bootstrap_seed,
        )
        print(f"\n  (Showing GENERATION metrics for alpha={last_alpha_str})")
    else:
        summary = compute_summary(
            results_by_alpha[last_alpha], active_cases, args.arms,
            bootstrap_iterations=args.bootstrap_iterations,
            bootstrap_seed=args.bootstrap_seed,
        )
        print(f"\n  (Showing metrics for alpha={last_alpha_str})")

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
                        "answer_point_coverage", "retrieval_ms_p95", "total_ms_p95"]:
                val = slice_metrics.get(key)
                if val is not None:
                    print(f"      {key:25s} {val:.4f}" if isinstance(val, float) else f"      {key:25s} {val}")

    # 配对差值（含 bootstrap CI）
    paired = summary.get("paired_cb", {})
    if paired:
        print(f"\n  Paired C-B deltas (bootstrap 95% CI):")
        for slice_name, delta_info in paired.items():
            print(f"    {slice_name}: mean_delta={delta_info['mean_delta']:.4f} "
                  f"ci95=[{delta_info['ci95_low']:.4f}, {delta_info['ci95_high']:.4f}] "
                  f"(n_pairs={delta_info.get('n_pairs', '?')}"
                  f", n_blocks={delta_info.get('n_blocks', '?')})")

    # McNemar（生成阶段）
    mcnemar = summary.get("mcnemar")
    if mcnemar:
        print(f"\n  McNemar exact test (C vs B binary errors):")
        print(f"    p_value={mcnemar['p_value']:.6f}, discordant={mcnemar['n_discordant']}, "
              f"B-only={mcnemar['b_only']}, C-only={mcnemar['c_only']}, n_pairs={mcnemar['n_pairs']}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
