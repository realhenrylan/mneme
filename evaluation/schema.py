"""Evaluation data schema for Mneme RAG quality measurement.

This module defines the annotation format used by human annotators and
consumed by evaluation runners.  It is a *static data contract* —
"annotators write, runners read" — and is intentionally separate from
the runtime domain model (``src.domain``) which carries live retrieval
state through the pipeline.

JSONL format
------------
Each line is a JSON object representing one evaluation case::

    {
      "id": "zh-fact-001",
      "query": "南京的面积是多少？",
      "query_type": "single_fact",
      "language": "zh",
      "relevant_source_ids": ["南京城市地理环境.docx"],
      "relevant_chunks": [
        {
          "source_id": "南京城市地理环境.docx",
          "chunk_text_snippet": "南京市总面积6587.02平方公里",
          "page": null,
          "section": "地理概况"
        }
      ],
      "acceptable_answer_points": [
        "南京总面积6587.02平方公里"
      ],
      "should_refuse": false,
      "metadata": {
        "difficulty": "easy",
        "requires_calculation": false
      }
    }

Schema version history
----------------------
- v1: Initial schema with 8 query types and structured annotations.
- v1 (tolerant reader): v2.x datasets extend the v1 contract with
  governance/provenance fields (``note``, ``annotation``,
  ``relevance_level``, ``is_refusal_turn``, ``doc_target``,
  ``relevant_chunk_ids``, ``relevant_chunks[].chunk_id``).  The loader
  keeps the contract static ("annotators write, runners read") while
  ignoring unknown keys, and surfaces ``relevant_chunk_ids`` (the
  human-confirmed authoritative chunk IDs) as a first-class field.
  Round-tripping through EvalCase is lossy for those extensions —
  never write back over an extended dataset file.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any


# ── Schema version ──────────────────────────────────────────────────

SCHEMA_VERSION = 1


# ── Enumerations ────────────────────────────────────────────────────

class QueryType(str, Enum):
    """Core query categories for evaluation coverage.

    Language is a separate dimension (``EvalCase.language``), so query
    types focus on the *task* rather than the language.  This gives 6
    orthogonal categories that, combined with the 3 language labels,
    produce 18 coverage cells.
    """

    SINGLE_FACT = "single_fact"           # 单文档事实
    CROSS_DOCUMENT = "cross_document"     # 跨文档比较
    METADATA = "metadata"                 # 元数据查询（来源、页码等）
    MULTI_TURN = "multi_turn"             # 多轮追问（代词/省略主语）
    NO_ANSWER = "no_answer"               # 无答案/应拒答
    MIXED_INTENT = "mixed_intent"         # 中英混合/多意图


class Language(str, Enum):
    """Query language."""

    ZH = "zh"
    EN = "en"
    MIXED = "mixed"


class Difficulty(str, Enum):
    """Annotation difficulty level."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


# ── Data classes ────────────────────────────────────────────────────

@dataclass(frozen=True)
class RelevantChunk:
    """A chunk that is relevant to answering the query.

    Annotators identify these by reading the source documents and
    marking which passages contain the answer evidence.
    """

    source_id: str
    chunk_text_snippet: str
    page: int | None = None
    section: str | None = None


@dataclass
class EvalCase:
    """One evaluation case in the JSONL dataset.

    Attributes:
        id: Unique identifier (e.g. "zh-fact-001").
        query: The natural-language query string.
        query_type: One of the 8 core query categories.
        language: Query language (zh / en / mixed).
        relevant_source_ids: Source file names that contain the answer.
        relevant_chunks: Specific chunks with evidence.
        acceptable_answer_points: Key facts that a correct answer must include.
        should_refuse: True if the system should decline to answer
            (no relevant evidence in the corpus).
        metadata: Optional annotation metadata (difficulty, etc.).
    """

    id: str
    query: str
    query_type: QueryType
    language: Language
    relevant_source_ids: list[str] = field(default_factory=list)
    relevant_chunks: list[RelevantChunk] = field(default_factory=list)
    # v2.x 增补：人工终审确认的权威相关块 ID（如 "e564a122a7a2_chunk_11"，
    # 与索引 metadata 的 chunk_id 同源同约定）。v1 数据集无此字段（加载后
    # 为空列表，runner 沿用 snippet 匹配回退路径，行为不变）。
    relevant_chunk_ids: list[str] = field(default_factory=list)
    acceptable_answer_points: list[str] = field(default_factory=list)
    should_refuse: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        d = asdict(self)
        d["query_type"] = self.query_type.value
        d["language"] = self.language.value
        d["relevant_chunks"] = [asdict(c) for c in self.relevant_chunks]
        d["schema_version"] = SCHEMA_VERSION
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EvalCase:
        """Deserialize from a JSON-compatible dict.

        容错读取（forward-compatible reader）：数据集演进会在 v1 契约外增补
        治理/溯源字段（v2.x 的 note/annotation/relevance_level/is_refusal_turn/
        doc_target 及 relevant_chunks[].chunk_id），加载器对未知字段一律忽略，
        runner 只消费契约内字段。代价是 load→save **不保真**（扩展字段丢失），
        因此带扩展字段的发布副本（v2.1.jsonl）禁止经 EvalCase 回写——治理
        真值以数据集原文件为准。
        """
        d = dict(d)  # shallow copy
        d.pop("schema_version", None)
        known = {f.name for f in fields(cls)}
        for key in [k for k in d if k not in known]:
            del d[key]
        d["query_type"] = QueryType(d["query_type"])
        d["language"] = Language(d["language"])
        chunk_fields = {f.name for f in fields(RelevantChunk)}
        d["relevant_chunks"] = [
            RelevantChunk(**{k: v for k, v in c.items() if k in chunk_fields})
            for c in d.get("relevant_chunks", [])
        ]
        return cls(**d)


# ── Dataset I/O ─────────────────────────────────────────────────────

def save_dataset(cases: list[EvalCase], path: Path) -> None:
    """Write evaluation cases to a JSONL file.

    Each case is written as a single JSON line for streaming-friendly
    consumption.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case.to_dict(), ensure_ascii=False) + "\n")


def load_dataset(path: Path) -> list[EvalCase]:
    """Read evaluation cases from a JSONL file."""
    cases: list[EvalCase] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                cases.append(EvalCase.from_dict(d))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid JSONL at line {line_no}: {exc}") from exc
    return cases


# ── Dataset split ───────────────────────────────────────────────────

def split_dataset(
    cases: list[EvalCase],
    holdout_ratio: float = 0.12,
    seed: int = 42,
) -> tuple[list[EvalCase], list[EvalCase]]:
    """Split cases into training and holdout subsets.

    The split is stratified by ``query_type`` so that each subset
    preserves the type distribution.  The holdout set is only used for
    final acceptance testing — parameter tuning must use the training
    subset only to prevent overfitting.

    Args:
        cases: Full evaluation dataset.
        holdout_ratio: Fraction reserved for holdout (default 12%).
        seed: Random seed for reproducibility.

    Returns:
        (train_cases, holdout_cases) tuple.
    """
    import random

    rng = random.Random(seed)

    # Group by query_type for stratified sampling
    by_type: dict[QueryType, list[EvalCase]] = {}
    for case in cases:
        by_type.setdefault(case.query_type, []).append(case)

    train: list[EvalCase] = []
    holdout: list[EvalCase] = []

    for qtype, group in by_type.items():
        rng.shuffle(group)
        n_holdout = max(1, round(len(group) * holdout_ratio))
        # Ensure at least 1 case in holdout if group has >= 2 cases
        if len(group) <= 1:
            n_holdout = 0
        holdout.extend(group[:n_holdout])
        train.extend(group[n_holdout:])

    return train, holdout


# ── Validation ──────────────────────────────────────────────────────

def validate_dataset(cases: list[EvalCase]) -> list[str]:
    """Check dataset integrity and return a list of warning messages.

    An empty list means no issues were found.
    """
    warnings: list[str] = []
    seen_ids: set[str] = set()

    for case in cases:
        # Duplicate IDs
        if case.id in seen_ids:
            warnings.append(f"Duplicate case ID: {case.id}")
        seen_ids.add(case.id)

        # should_refuse but has relevant sources
        if case.should_refuse and case.relevant_source_ids:
            warnings.append(
                f"Case {case.id}: should_refuse=True but has "
                f"relevant_source_ids={case.relevant_source_ids}"
            )

        # should_refuse but has answer points
        if case.should_refuse and case.acceptable_answer_points:
            warnings.append(
                f"Case {case.id}: should_refuse=True but has "
                f"acceptable_answer_points"
            )

        # Not should_refuse but no answer points
        if not case.should_refuse and not case.acceptable_answer_points:
            warnings.append(
                f"Case {case.id}: should_refuse=False but has no "
                f"acceptable_answer_points"
            )

        # Not should_refuse but no relevant sources
        if not case.should_refuse and not case.relevant_source_ids:
            warnings.append(
                f"Case {case.id}: should_refuse=False but has no "
                f"relevant_source_ids"
            )

    # Coverage check
    type_counts: dict[str, int] = {}
    for case in cases:
        type_counts[case.query_type.value] = type_counts.get(case.query_type.value, 0) + 1

    for qtype in QueryType:
        if qtype.value not in type_counts:
            warnings.append(f"Missing query type coverage: {qtype.value}")

    return warnings
