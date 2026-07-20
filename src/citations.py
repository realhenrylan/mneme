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
