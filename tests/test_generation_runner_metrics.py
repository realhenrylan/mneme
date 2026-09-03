"""generation_runner 指标扩展单元测试：answer-hit 接入、真值 chunk 口径、token 实耗聚合。

范围（章程 M1）：
- run_case 的真值 chunk 解析：v2.1 权威 ``relevant_chunk_ids`` 一等字段优先，
  snippet 匹配仅作 v1 回退（0b5866c 的消费闭环）；
- token 实耗：从 llm_gateway 调用记录按 case 切片聚合（评测进程内），
  不改 src/；
- 聚合报告：answer_hit_rate 只对有效要点>0 的例平均，None 案例单独计数。
"""

import pytest

from evaluation.answer_metrics import AnswerHitResult, PointVerdict
from evaluation.citation_metrics import CitationMetrics
from evaluation.generation_runner import (
    GenerationResult,
    GenerationRunner,
    _collect_case_tokens,
    resolve_relevant_chunk_ids,
)
from pathlib import Path

from evaluation.schema import EvalCase, Language, QueryType, RelevantChunk
from src.llm_gateway import LLMCallRecord, TokenUsage, _record_call, clear_call_records


def _make_case(
    case_id: str = "zh-fact-001",
    *,
    authoritative_ids: list[str] | None = None,
    snippet: str | None = None,
) -> EvalCase:
    relevant_chunks = (
        [RelevantChunk(source_id="doc.md", chunk_text_snippet=snippet)]
        if snippet
        else []
    )
    return EvalCase(
        id=case_id,
        query="测试问题？",
        query_type=QueryType.SINGLE_FACT,
        language=Language.ZH,
        relevant_source_ids=["doc.md"],
        relevant_chunks=relevant_chunks,
        relevant_chunk_ids=authoritative_ids or [],
        acceptable_answer_points=["要点A"],
        should_refuse=False,
    )


# metadatas/documents 构造 snippet exact 匹配场景：
# chunk 文本包含 snippet → match_snippet_to_chunks 命中 "chunk_7"
_INDEX_METADATAS = [{"source": "doc.md", "chunk_id": "chunk_7"}]
_INDEX_DOCS = ["这篇文档包含【权威片段内容】的原文。"]


class TestResolveRelevantChunkIds:
    def test_authoritative_ids_take_priority_over_snippet(self):
        case = _make_case(
            authoritative_ids=["32c427fb50e2_chunk_25"],
            snippet="一个永远不会匹配的片段",
        )
        assert resolve_relevant_chunk_ids(
            case, _INDEX_METADATAS, _INDEX_DOCS,
        ) == {"32c427fb50e2_chunk_25"}

    def test_falls_back_to_snippet_matching_for_v1(self):
        case = _make_case(snippet="权威片段内容")
        assert resolve_relevant_chunk_ids(
            case, _INDEX_METADATAS, _INDEX_DOCS,
        ) == {"chunk_7"}

    def test_returns_empty_set_when_no_truth_available(self):
        case = _make_case()
        assert resolve_relevant_chunk_ids(
            case, _INDEX_METADATAS, _INDEX_DOCS,
        ) == set()


class TestCollectCaseTokens:
    def setup_method(self):
        clear_call_records()

    def teardown_method(self):
        clear_call_records()

    def test_sums_prompt_and_completion_from_gateway_records(self):
        _record_call(LLMCallRecord(
            call_type="rewrite", model="m", latency_ms=1.0,
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
        ))
        _record_call(LLMCallRecord(
            call_type="answer", model="m", latency_ms=1.0,
            token_usage=TokenUsage(prompt_tokens=900, completion_tokens=180, total_tokens=1080),
        ))
        prompt, completion, total = _collect_case_tokens()
        assert prompt == 1000
        assert completion == 200
        assert total == 1200

    def test_ignores_records_without_usage(self):
        _record_call(LLMCallRecord(
            call_type="answer", model="m", latency_ms=1.0, token_usage=None,
        ))
        assert _collect_case_tokens() == (None, None, None)

    def test_returns_none_when_no_records(self):
        assert _collect_case_tokens() == (None, None, None)


def _make_hit_result(rate: float | None) -> AnswerHitResult:
    if rate is None:
        return AnswerHitResult(point_results=(), hit_count=0,
                               effective_point_count=0, answer_hit_rate=None)
    n_hit = int(rate * 2)
    points = tuple(
        PointVerdict(point_text=f"p{i}", normalized=f"p{i}",
                     verdict="hit" if i < n_hit else "miss")
        for i in range(2)
    )
    return AnswerHitResult(point_results=points, hit_count=n_hit,
                           effective_point_count=2, answer_hit_rate=rate)


def _make_generation_result(
    hit_rate: float | None,
    *,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> GenerationResult:
    return GenerationResult(
        case_id="c", query="q", query_type="single_fact", language="zh",
        should_refuse=False, answer="a", context="ctx",
        citation_metrics=CitationMetrics(
            citation_id_validity=0.0, invalid_citation_count=0,
            total_citation_count=0, citation_precision=0.0,
            citation_recall=0.0, faithfulness=0.0, correctly_refused=True,
        ),
        total_ms=1.0, retrieval_ms=0.0, generation_ms=1.0,
        answer_hit=_make_hit_result(hit_rate),
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
    )


class TestAggregateAnswerHit:
    def test_averages_hit_rate_over_effective_cases_only(self):
        results = [
            _make_generation_result(1.0),
            _make_generation_result(0.0),
            _make_generation_result(None),  # 无有效要点（如拒答例）→ 跳过
        ]
        report = GenerationRunner(Path("unused.jsonl"))._aggregate(results)
        assert report["answer_hit_rate_avg"] == pytest.approx(0.5)
        assert report["cases_without_effective_points"] == 1

    def test_all_none_cases_yield_none_average(self):
        results = [_make_generation_result(None), _make_generation_result(None)]
        report = GenerationRunner(Path("unused.jsonl"))._aggregate(results)
        assert report["answer_hit_rate_avg"] is None
        assert report["cases_without_effective_points"] == 2

    def test_token_totals_are_summed_with_averages(self):
        # 无 token 数据的例不计入均值分母（sums 仍只累计有数据的例）
        results = [
            _make_generation_result(1.0, prompt_tokens=100, completion_tokens=20),
            _make_generation_result(0.0, prompt_tokens=900, completion_tokens=180),
            _make_generation_result(0.0, prompt_tokens=None, completion_tokens=None),
        ]
        report = GenerationRunner(Path("unused.jsonl"))._aggregate(results)
        assert report["prompt_tokens_sum"] == 1000
        assert report["completion_tokens_sum"] == 200
        assert report["total_tokens_sum"] == 1200
        assert report["prompt_tokens_avg"] == pytest.approx(500.0)
        assert report["completion_tokens_avg"] == pytest.approx(100.0)
        assert report["total_tokens_avg"] == pytest.approx(600.0)
