"""Citation quality metrics for Mneme RAG evaluation.

Measures:
- **Citation ID validity**: Fraction of citation IDs in the answer that
  correspond to actual retrieved chunks.
- **Citation precision**: Fraction of cited chunks that are relevant.
- **Citation recall**: Fraction of relevant chunks that are cited.
- **Faithfulness**: Whether answer points are supported by cited evidence.
- **Refusal accuracy**: Whether the system correctly refuses to answer
  when no relevant evidence exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


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
