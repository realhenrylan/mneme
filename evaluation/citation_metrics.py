"""Citation quality metrics for Mneme RAG evaluation.

Measures:
- **Citation ID validity**: Fraction of citation IDs in the answer that
  correspond to actual retrieved chunks.
- **Citation precision**: Fraction of cited chunks that are relevant.
- **Citation recall**: Fraction of relevant chunks that are cited.
- **Faithfulness**: Whether answer points are supported by cited evidence.
- **Refusal accuracy**: Whether the system correctly refuses to answer
  when no relevant evidence exists.

契约 v2（context-aware citation validity）
-----------------------------------------
旧 ``evaluate_citations`` 只验证"引用 ID 是否在本次检索/引用展示（sources）中"
（retrieval-level visible），无法回答"答案引用的证据是否真的进入了最终送入
LLM 的 prompt context"。契约 v2 引入 ``evaluate_citations_context_aware``，
显式区分三层：

1. **retrieval-level visible**（``citation_id_validity``，兼容旧字段）：
   引用 ID 出现在本次引用展示（``format_sources`` 输出）解析出的 ID 集中。
2. **context-level supported**（``context_supported_citation_validity``，正式
   guardrail 指标）：引用 ID 解析出的 chunk ∈ 最终 context chunk 集合
   （``supported_chunk``），或该 chunk 的 source ∈ 最终 context source 集合
   （``supported_source``）。证据来自评测检索网格记录的
   ``context_chunk_ids``/``context_source_ids``。
3. **最终答案引用有效性**：即 context-level supported（guardrail 用）。

确定性处理规则（对单条 answer）：
- 引用提取 ``referenced_citation_ids``（``\\bS\\d+\\b``，set 语义）——
  **重复引用按唯一 ID 计一次**，不放大有效性。
- **空引用**：validity=0.0，total/unique=0，无证据。
- **fabricated/未知引用**：引用 ID 无法从 sources 解析（幻觉，或 sources 行
  缺 chunk_id 无法映射）→ ``fabricated``，无效。
- **候选池但未进 context**：chunk ∈ candidate 记录但不在 context chunk/source
  记录 → ``retrieved_not_in_context``，无效（检索可见 ≠ context 支持）。
- **多 source/多引用**：每个引用 ID 解析到单一 chunk → 单一 source（sources
  每行一个 chunk）；同一 ID 重复出现取首行（确定性）；解析失败视为 fabricated。
- source 口径与 source recall 一致：``chunk_to_source`` 由
  ``_source_label_from_meta``（source_name 优先）构建，禁止 filename/hash 混用。

fail-closed：``evaluate_citations_context_aware`` 要求
sources/context_chunk_ids/context_source_ids/candidate_chunk_ids/chunk_to_source/
context_text 全部显式提供（None → ValueError）；空列表是"真实空"（合法），
缺值是"未提供"（拒绝）。调用点必须传真实证据，禁止占位。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class CitationEvidence:
    """单条引用的分层判定证据（可审计）。"""

    citation_id: str
    chunk_id: str | None  # sources 解析出的 chunk，None = 无法映射
    status: str  # supported_chunk | supported_source | retrieved_not_in_context | fabricated
    in_context_chunks: bool
    in_context_sources: bool
    in_candidates: bool


@dataclass(frozen=True)
class CitationMetrics:
    """Citation quality metrics for a single query."""

    # Citation ID validity: fraction of cited IDs that are valid
    citation_id_validity: float
    # Number of invalid citation IDs
    invalid_citation_count: int
    # Total citation IDs in the answer
    total_citation_count: int

    # Citation precision: of cited chunks, fraction that are relevant
    citation_precision: float
    # Citation recall: of relevant chunks, fraction that are cited
    citation_recall: float

    # Faithfulness: fraction of answer points supported by evidence
    faithfulness: float

    # Whether the system correctly refused (for should_refuse cases)
    correctly_refused: bool | None

    # ── 契约 v2：context-level supported（正式 guardrail 口径） ──
    # 引用对应 chunk/source 真正进入最终 LLM context 的比例
    context_supported_citation_validity: float = 0.0
    # 去重后的唯一引用数（== total_citation_count，set 语义，字段为可读性）
    unique_citation_count: int = 0
    # 幻觉/不可映射引用数
    fabricated_citation_count: int = 0
    # 候选池可见但未进 context 的引用数
    retrieved_not_in_context_count: int = 0
    supported_chunk_count: int = 0
    supported_source_count: int = 0
    # 逐引用判定证据（确定性顺序：按 ID 数字升序）
    evidence: tuple[CitationEvidence, ...] = ()


def parse_sources_citation_map(sources: str | None) -> dict[str, str]:
    """解析 ``format_sources`` 输出 → {citation_id: chunk_id}。

    每行格式：``[S1] source (p.X; chunk N; § heading; chunk_id=<id>): snippet``。
    - 逐行匹配，行内无 ``chunk_id=`` 则跳过（该引用 ID 无法映射）；
    - 同一 ID 重复出现取首个（确定性）；
    - 空/None 输入返回空 dict。
    """
    result: dict[str, str] = {}
    for line in (sources or "").splitlines():
        m = re.search(r"\[(S\d+)\].*?chunk_id=([^\s);:]+)", line)
        if m:
            result.setdefault(m.group(1), m.group(2))
    return result


def evaluate_citations_context_aware(
    answer: str,
    *,
    sources: str | None,
    context_chunk_ids: Sequence[str] | None,
    context_source_ids: Sequence[str] | None,
    candidate_chunk_ids: Sequence[str] | None,
    chunk_to_source: Mapping[str, str] | None,
    relevant_chunk_ids: set[str] | None = None,
    answer_points: list[str] | None = None,
    context_text: str | None = None,
    should_refuse: bool = False,
) -> CitationMetrics:
    """契约 v2 的 citation 评估：引用有效性必须映射到最终 LLM context。

    fail-closed：sources/context_chunk_ids/context_source_ids/
    candidate_chunk_ids/chunk_to_source/context_text 任一为 None → ValueError
    （缺值 = 未提供，禁止静默产出"有效/无效"指标；空列表/空字符串是真实空，
    合法）。

    Args:
        answer: LLM 生成的回答。
        sources: ``format_sources`` 输出（生产引用展示，S#→chunk 权威映射）。
        context_chunk_ids: 最终送入 LLM 的 context chunk 集合（评测检索网格
            记录的顺序列表）。
        context_source_ids: context 的去重 source 集合（与 source recall 同
            口径，source_name 优先）。
        candidate_chunk_ids: 候选检索层 chunk 集合（区分"检索可见"）。
        chunk_to_source: chunk_id → source 标签（_source_label_from_meta 口径）。
        relevant_chunk_ids: ground-truth 相关 chunk。
        answer_points: ground-truth 答案要点（faithfulness）。
        context_text: 最终 context 文本（faithfulness 用；可由
            context_chunk_ids 重建，非生产逐字节时需在报告中说明）。
        should_refuse: 是否应拒答。
    """
    missing = [
        name for name, value in (
            ("sources", sources),
            ("context_chunk_ids", context_chunk_ids),
            ("context_source_ids", context_source_ids),
            ("candidate_chunk_ids", candidate_chunk_ids),
            ("chunk_to_source", chunk_to_source),
            ("context_text", context_text),
        ) if value is None
    ]
    if missing:
        raise ValueError(
            "evaluate_citations_context_aware requires explicit context "
            f"evidence; missing: {missing} (refusing to emit citation "
            "metrics without context evidence)")

    id2chunk = parse_sources_citation_map(sources)
    visible_ids = set(id2chunk)
    from src.citations import referenced_citation_ids
    cited = referenced_citation_ids(answer)  # set：重复引用计一次
    ctx_set = set(context_chunk_ids)
    src_set = set(context_source_ids)
    cand_set = set(candidate_chunk_ids)

    evidence: list[CitationEvidence] = []
    for cid in sorted(cited,
                      key=lambda x: int(x[1:]) if x[1:].isdigit() else 0):
        chunk = id2chunk.get(cid)
        in_ctx = bool(chunk) and chunk in ctx_set
        in_cand = bool(chunk) and chunk in cand_set
        in_src = False
        if chunk:
            source = chunk_to_source.get(chunk)
            in_src = bool(source) and source in src_set
        if in_ctx:
            status = "supported_chunk"
        elif in_src:
            status = "supported_source"
        elif in_cand:
            status = "retrieved_not_in_context"
        else:
            status = "fabricated"
        evidence.append(CitationEvidence(
            citation_id=cid, chunk_id=chunk, status=status,
            in_context_chunks=in_ctx, in_context_sources=in_src,
            in_candidates=in_cand,
        ))

    total = len(cited)
    supported = sum(1 for e in evidence
                    if e.status in ("supported_chunk", "supported_source"))
    # context-supported 引用映射到的 chunk 集（precision/recall 按 chunk 域）
    supported_chunks = {e.chunk_id for e in evidence
                        if e.status in ("supported_chunk", "supported_source")
                        and e.chunk_id}
    rel = relevant_chunk_ids or set()

    # 契约 v2 正式指标：context-supported 有效性
    cs_validity = supported / total if total else 0.0
    # 旧语义保留（retrieval-visible）：引用 ID 在 sources 展示 ID 集中
    visible_valid = len(cited & visible_ids) / total if total else 0.0

    # precision/recall：分母/分子只计 context-supported 引用（chunk 域）
    if supported_chunks:
        precision = len(supported_chunks & rel) / len(supported_chunks)
    else:
        precision = 0.0
    recall = len(supported_chunks & rel) / len(rel) if rel else 0.0

    faithfulness = compute_faithfulness(answer, answer_points or [],
                                        context_text or "")
    correctly_refused = compute_refusal_accuracy(answer, should_refuse)

    return CitationMetrics(
        citation_id_validity=visible_valid,
        invalid_citation_count=len(cited - visible_ids),
        total_citation_count=total,
        citation_precision=precision,
        citation_recall=recall,
        faithfulness=faithfulness,
        correctly_refused=correctly_refused,
        context_supported_citation_validity=cs_validity,
        unique_citation_count=total,
        fabricated_citation_count=sum(
            1 for e in evidence if e.status == "fabricated"),
        retrieved_not_in_context_count=sum(
            1 for e in evidence if e.status == "retrieved_not_in_context"),
        supported_chunk_count=sum(
            1 for e in evidence if e.status == "supported_chunk"),
        supported_source_count=sum(
            1 for e in evidence if e.status == "supported_source"),
        evidence=tuple(evidence),
    )


def compute_citation_id_validity(
    answer: str,
    valid_ids: set[str],
) -> tuple[float, int, int]:
    """Compute citation ID validity.

    Uses the same ``referenced_citation_ids()`` function as the
    production pipeline to extract citation IDs from the answer.

    Args:
        answer: The LLM-generated answer text.
        valid_ids: Set of valid citation IDs (from retrieved chunks).

    Returns:
        (validity_fraction, invalid_count, total_count) tuple.
    """
    from src.citations import referenced_citation_ids

    cited = referenced_citation_ids(answer)
    if not cited:
        return 0.0, 0, 0

    invalid = cited - valid_ids
    validity = 1.0 - (len(invalid) / len(cited))
    return validity, len(invalid), len(cited)


def compute_citation_precision_recall(
    answer: str,
    relevant_chunk_ids: set[str],
    all_retrieved_ids: set[str],
) -> tuple[float, float]:
    """Compute citation precision and recall.

    Citation precision: of the chunks cited in the answer, what
    fraction are in the relevant set?

    Citation recall: of the relevant chunks, what fraction are
    cited in the answer?

    Args:
        answer: The LLM-generated answer text.
        relevant_chunk_ids: Ground-truth relevant chunk IDs.
        all_retrieved_ids: All chunk IDs that were retrieved.

    Returns:
        (precision, recall) tuple.
    """
    from src.citations import referenced_citation_ids

    cited = referenced_citation_ids(answer)
    # Only consider citations that map to actual retrieved chunks
    valid_cited = cited & all_retrieved_ids

    if not valid_cited:
        precision = 0.0
    else:
        # Precision: of valid citations, how many are relevant?
        relevant_cited = valid_cited & relevant_chunk_ids
        precision = len(relevant_cited) / len(valid_cited)

    if not relevant_chunk_ids:
        recall = 0.0
    else:
        # Recall: of relevant chunks, how many are cited?
        relevant_cited = cited & relevant_chunk_ids
        recall = len(relevant_cited) / len(relevant_chunk_ids)

    return precision, recall


def compute_faithfulness(
    answer: str,
    answer_points: list[str],
    context: str,
) -> float:
    """Compute faithfulness: fraction of answer points supported by context.

    A point is "supported" if its key terms appear in the context.
    This is a simple heuristic check — for rigorous evaluation, use
    an LLM-based faithfulness judge (future work).

    Args:
        answer: The LLM-generated answer text.
        answer_points: Ground-truth answer points that should be covered.
        context: The context text that was provided to the LLM.

    Returns:
        Faithfulness score in [0, 1].
    """
    if not answer_points:
        return 1.0  # No points to verify → vacuously faithful

    supported = 0
    context_lower = context.lower()
    answer_lower = answer.lower()

    for point in answer_points:
        # Check if key terms from the answer point appear in the context
        # Split the point into individual terms (numbers, words)
        terms = _extract_key_terms(point)
        if not terms:
            supported += 1
            continue

        # A point is supported if most of its key terms appear in context
        found = sum(1 for t in terms if t in context_lower)
        if found >= len(terms) * 0.5:  # At least half the terms found
            supported += 1

    return supported / len(answer_points)


def _extract_key_terms(text: str) -> list[str]:
    """Extract key search terms from an answer point.

    Filters out common stop words and keeps meaningful terms.
    """
    import re

    # Split into tokens: words, numbers, CJK characters
    tokens = re.findall(
        r'[a-zA-Z]+[0-9]*|[0-9]+(?:\.[0-9]+)?%?|[\u4e00-\u9fff]+',
        text,
    )
    # Simple stop word filtering
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "shall", "can", "of",
        "in", "on", "at", "to", "for", "with", "by", "from", "and",
        "or", "but", "not", "no", "yes", "it", "its", "this", "that",
    }
    return [t.lower() for t in tokens if t.lower() not in stop_words and len(t) > 1]


def compute_refusal_accuracy(
    answer: str,
    should_refuse: bool,
    refusal_indicators: Sequence[str] | None = None,
) -> bool | None:
    """Check whether the system correctly refused or answered.

    Args:
        answer: The LLM-generated answer text.
        should_refuse: Whether the query should have been refused.
        refusal_indicators: Phrases that indicate a refusal response.

    Returns:
        True if correct (refused when should, answered when shouldn't),
        False if incorrect, None if should_refuse is not applicable.
    """
    if refusal_indicators is None:
        refusal_indicators = [
            "未找到", "无法回答", "没有足够", "暂无", "无法提供",
            "cannot", "unable to", "no information", "not found",
            "don't have", "does not contain", "not available",
        ]

    answer_lower = answer.lower()
    is_refused = any(ind in answer_lower for ind in refusal_indicators)

    if should_refuse:
        return is_refused  # Correct if refused
    else:
        return not is_refused  # Correct if NOT refused


def evaluate_citations(
    answer: str,
    valid_ids: set[str],
    relevant_chunk_ids: set[str],
    all_retrieved_ids: set[str],
    answer_points: list[str],
    context: str,
    should_refuse: bool = False,
) -> CitationMetrics:
    """Compute all citation metrics for a single query.

    Args:
        answer: The LLM-generated answer text.
        valid_ids: Valid citation IDs from retrieved chunks.
        relevant_chunk_ids: Ground-truth relevant chunk IDs.
        all_retrieved_ids: All retrieved chunk IDs.
        answer_points: Ground-truth answer points.
        context: Context provided to the LLM.
        should_refuse: Whether the query should be refused.

    Returns:
        Complete CitationMetrics for this query.
    """
    validity, invalid_count, total_count = compute_citation_id_validity(
        answer, valid_ids,
    )
    precision, recall = compute_citation_precision_recall(
        answer, relevant_chunk_ids, all_retrieved_ids,
    )
    faithfulness = compute_faithfulness(answer, answer_points, context)
    correctly_refused = compute_refusal_accuracy(answer, should_refuse)

    return CitationMetrics(
        citation_id_validity=validity,
        invalid_citation_count=invalid_count,
        total_citation_count=total_count,
        citation_precision=precision,
        citation_recall=recall,
        faithfulness=faithfulness,
        correctly_refused=correctly_refused,
    )
