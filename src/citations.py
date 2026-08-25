"""Stable, query-local citation records for retrieved chunks."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True)
class CitationRecord:
    citation_id: str
    chunk_id: str
    source_id: str
    source_path: str
    source_name: str
    page: int | None
    chunk_index: int | None
    snippet: str


def make_citation_records(
    indices: Iterable[int],
    documents: list[str],
    metadatas: list[dict],
) -> list[CitationRecord]:
    records = []
    for rank, index in enumerate(indices, start=1):
        metadata = metadatas[index] or {}
        source_name = metadata.get("source_name") or metadata.get("source", "unknown")
        records.append(CitationRecord(
            citation_id=f"S{rank}",
            chunk_id=str(metadata.get("chunk_id", f"chunk_{index}")),
            source_id=str(metadata.get("source_id", "")),
            source_path=str(metadata.get("source_path", source_name)),
            source_name=str(source_name),
            page=metadata.get("page"),
            chunk_index=metadata.get("chunk_index", index),
            snippet=documents[index].replace("\n", " ")[:150],
        ))
    return records


def citation_map(
    indices: Iterable[int],
    documents: list[str],
    metadatas: list[dict],
) -> dict[int, CitationRecord]:
    indices = list(indices)
    return {
        index: record
        for index, record in zip(
            indices,
            make_citation_records(indices, documents, metadatas),
        )
    }


def citation_payload(records: Iterable[CitationRecord]) -> list[dict]:
    return [asdict(record) for record in records]


def referenced_citation_ids(answer: str) -> set[str]:
    return set(re.findall(r"\bS\d+\b", answer or ""))


def validate_citations(answer: str, valid_ids: Iterable[str]) -> set[str]:
    """Return citation IDs in the answer that are not in the retrieved set."""
    return referenced_citation_ids(answer) - set(valid_ids)


def valid_citation_ids_for_context(
    indices: Iterable[int],
    documents: list[str],
    metadatas: list[dict],
    context_k: int,
) -> tuple[str, ...]:
    """与实际展示的 sources（format_sources）严格同口径的合法 ID 集。

    format_sources 对 ``indices[:context_k]`` 逐 rank 分配 ``S{rank}``，
    本函数用同一 ``make_citation_records`` 输入——校验合法集与展示来源
    永远一致（Product P0.1）。
    """
    records = make_citation_records(list(indices)[:context_k],
                                    documents, metadatas)
    return tuple(record.citation_id for record in records)


def format_citation_status_line(status) -> str | None:
    """CLI 引用状态行（纯文本，Product P0.2）。

    - unverified → "⚠ 引用未验证：…（原回答未改动）"；
    - verified → "✓ 引用已验证（编号与来源一致）"；
    - not_required / None → None（不显示，避免误导）。
    只陈述编号与 evidence 的对应关系，不声称语义蕴含或事实已验证。
    """
    if status is None:
        return None
    from src.domain import (
        CITATION_NOT_REQUIRED,
        CITATION_UNVERIFIED,
        CITATION_VERIFIED,
    )
    if status.state == CITATION_UNVERIFIED:
        if status.missing:
            return "⚠ 引用未验证：回答未引用任何来源（原回答未改动）"
        return (
            "⚠ 引用未验证：非法引用编号 "
            + "、".join(status.invalid_ids)
            + "（原回答未改动）"
        )
    if status.state == CITATION_VERIFIED:
        return "✓ 引用已验证（编号与来源一致）"
    return None


def evaluate_citation_status(
    answer: str,
    valid_ids: Iterable[str],
    *,
    answer_requires_citation: bool,
    not_required_reason: str | None = None,
) -> CitationStatus:
    """回答的引用终态（Product P0.1 共享校验器）。

    - 不要求引用（拒答 / API 错误 / 无文档证据）→ not_required；
    - 有文档证据时：出现非法 ID 或没有任何引用 → unverified；
    - 全部引用都在合法集内 → verified。

    绝不改写回答文本（非法 ID 保留原样）；只验证编号是否对应实际
    evidence，不声称语义蕴含或事实真实性。
    """
    from src.domain import (
        CITATION_NOT_REQUIRED,
        CITATION_UNVERIFIED,
        CITATION_VERIFIED,
        CitationStatus,
    )

    valid_tuple = tuple(valid_ids)
    if not answer_requires_citation:
        return CitationStatus(
            state=CITATION_NOT_REQUIRED, valid_ids=valid_tuple,
            reason=not_required_reason,
        )
    if not valid_tuple:
        return CitationStatus(state=CITATION_NOT_REQUIRED, reason="no_evidence")
    referenced = referenced_citation_ids(answer)
    invalid = tuple(sorted(referenced - set(valid_tuple)))
    if invalid:
        return CitationStatus(
            state=CITATION_UNVERIFIED, valid_ids=valid_tuple,
            invalid_ids=invalid,
        )
    if not referenced:
        return CitationStatus(
            state=CITATION_UNVERIFIED, valid_ids=valid_tuple, missing=True,
        )
    return CitationStatus(state=CITATION_VERIFIED, valid_ids=valid_tuple)
