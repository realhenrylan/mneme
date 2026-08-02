"""Runtime metrics for RAG operations — 完整可观测性。

记录分阶段延迟、TTFT、token 使用量、引用有效率等指标。
支持持久化到磁盘，不再只保存最近 100 条内存记录。

隐私保护：不记录用户查询、文档文本、API Key 或端点。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any


@dataclass(frozen=True)
class QueryMetric:
    """One completed retrieval/answer preparation measurement."""

    # ── 基础指标 ──
    retrieval_ms: float
    candidate_count: int
    selected_count: int
    source_count: int
    manifest_version: int | None
    refused: bool = False
    error_category: str | None = None
    context_k: int | None = None  # 实际进入 prompt 的证据数
    refusal_type: str | None = None  # 拒答类型：retrieval / generation / api_error

    # ── 3.4 新增：分阶段延迟 ──
    index_ms: float | None = None       # 索引构建耗时
    embedding_ms: float | None = None   # embedding 编码耗时
    rewrite_ms: float | None = None     # query rewrite 耗时
    decompose_ms: float | None = None   # query decompose 耗时
    dense_ms: float | None = None       # dense 检索耗时
    bm25_ms: float | None = None        # BM25 检索耗时
    rerank_ms: float | None = None      # rerank 耗时
    llm_ms: float | None = None         # LLM 生成耗时
    ttft_ms: float | None = None        # Time To First Token（流式）

    # ── 3.4 新增：token 与引用 ──
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    citation_valid: int | None = None   # 有效引用数
    citation_invalid: int | None = None # 无效引用数

    # ── 3.4 新增：rewrite 信息 ──
    rewrite_changed: bool | None = None  # 查询是否被改写
    rewrite_merge_overlap: int | None = None  # 原查询与改写结果重叠数


class MetricsRecorder:
    """Thread-safe metrics recorder with optional disk persistence."""

    def __init__(
        self,
        max_records: int = 1000,
        persist_path: str | None = None,
    ) -> None:
        self._max_records = max(1, int(max_records))
        self._records: list[QueryMetric] = []
        self._lock = Lock()
        self._persist_path = persist_path

        # 启动时从磁盘加载历史记录
        if persist_path:
            self._load_from_disk()

    def record(self, metric: QueryMetric) -> None:
        with self._lock:
            self._records.append(metric)
            del self._records[:-self._max_records]
        # 异步持久化（不阻塞调用方）
        if self._persist_path:
            self._save_to_disk()

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

        # 基础统计
        result: dict[str, Any] = {
            "query_count": len(records),
            "retrieval_ms_avg": round(
                sum(r.retrieval_ms for r in records) / len(records), 3,
            ),
            "retrieval_ms_last": round(records[-1].retrieval_ms, 3),
            "refusal_count": sum(r.refused for r in records),
            "last_error_category": records[-1].error_category,
        }

        # 分阶段延迟统计（仅统计有值的记录）
        for phase in ("index_ms", "embedding_ms", "rewrite_ms", "decompose_ms",
                       "dense_ms", "bm25_ms", "rerank_ms", "llm_ms", "ttft_ms"):
            values = [getattr(r, phase) for r in records if getattr(r, phase) is not None]
            if values:
                result[f"{phase}_avg"] = round(sum(values) / len(values), 3)
                result[f"{phase}_last"] = round(values[-1], 3)

        # Token 统计
        prompt_tokens = [r.prompt_tokens for r in records if r.prompt_tokens is not None]
        completion_tokens = [r.completion_tokens for r in records if r.completion_tokens is not None]
        if prompt_tokens:
            result["prompt_tokens_total"] = sum(prompt_tokens)
            result["prompt_tokens_avg"] = round(sum(prompt_tokens) / len(prompt_tokens), 1)
        if completion_tokens:
            result["completion_tokens_total"] = sum(completion_tokens)
            result["completion_tokens_avg"] = round(sum(completion_tokens) / len(completion_tokens), 1)

        # 引用有效率
        valid = [r.citation_valid for r in records if r.citation_valid is not None]
        invalid = [r.citation_invalid for r in records if r.citation_invalid is not None]
        if valid and invalid:
            total_citations = sum(valid) + sum(invalid)
            result["citation_valid_rate"] = round(sum(valid) / total_citations, 3) if total_citations else 0

        # Rewrite 统计
        rewrites = [r for r in records if r.rewrite_changed is not None]
        if rewrites:
            result["rewrite_count"] = sum(1 for r in rewrites if r.rewrite_changed)
            result["rewrite_rate"] = round(
                sum(1 for r in rewrites if r.rewrite_changed) / len(rewrites), 3,
            )

        # context_k 统计
        context_ks = [r.context_k for r in records if r.context_k is not None]
        if context_ks:
            result["context_k_avg"] = round(sum(context_ks) / len(context_ks), 1)
            result["context_k_last"] = context_ks[-1]

        return result

    def _save_to_disk(self) -> None:
        """将记录持久化到磁盘。"""
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with self._lock:
                data = [asdict(r) for r in self._records]
            tmp_path = self._persist_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            if os.path.exists(self._persist_path):
                os.replace(tmp_path, self._persist_path)
            else:
                os.rename(tmp_path, self._persist_path)
        except OSError:
            pass  # 持久化失败不影响主流程

    def _load_from_disk(self) -> None:
        """从磁盘加载历史记录。"""
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                for item in data[-self._max_records:]:
                    try:
                        self._records.append(QueryMetric(**item))
                    except TypeError:
                        pass  # 忽略格式不兼容的旧记录
        except (json.JSONDecodeError, OSError):
            pass


GLOBAL_METRICS = MetricsRecorder()


def elapsed_ms(start: float) -> float:
    """Return elapsed milliseconds for a ``perf_counter`` start value."""
    return max(0.0, (perf_counter() - start) * 1000.0)
