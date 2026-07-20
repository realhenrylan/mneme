"""Small, privacy-preserving runtime metrics for RAG operations.

The recorder intentionally stores timings and counts only.  It never keeps
the user's query, document text, API key, or endpoint.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock
from time import perf_counter
from typing import Any


@dataclass(frozen=True)
class QueryMetric:
    """One completed retrieval/answer preparation measurement."""

    retrieval_ms: float
    candidate_count: int
    selected_count: int
    source_count: int
    manifest_version: int | None
    refused: bool = False
    error_category: str | None = None


class MetricsRecorder:
    """Thread-safe bounded in-memory metrics recorder."""

    def __init__(self, max_records: int = 100) -> None:
        self._max_records = max(1, int(max_records))
        self._records: list[QueryMetric] = []
        self._lock = Lock()

    def record(self, metric: QueryMetric) -> None:
        with self._lock:
            self._records.append(metric)
            del self._records[:-self._max_records]

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(record) for record in self._records]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            records = list(self._records)
        if not records:
            return {
                "query_count": 0,
                "retrieval_ms_avg": 0.0,
                "retrieval_ms_last": 0.0,
                "refusal_count": 0,
                "last_error_category": None,
            }
        return {
            "query_count": len(records),
            "retrieval_ms_avg": round(
                sum(record.retrieval_ms for record in records) / len(records), 3,
            ),
            "retrieval_ms_last": round(records[-1].retrieval_ms, 3),
            "refusal_count": sum(record.refused for record in records),
            "last_error_category": records[-1].error_category,
        }


GLOBAL_METRICS = MetricsRecorder()


def elapsed_ms(start: float) -> float:
    """Return elapsed milliseconds for a ``perf_counter`` start value."""
    return max(0.0, (perf_counter() - start) * 1000.0)
