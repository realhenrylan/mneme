"""测试 3.4 完整可观测性。"""

import json
import os
import pytest
from src.metrics import QueryMetric, MetricsRecorder, elapsed_ms, GLOBAL_METRICS


class TestQueryMetricExtended:
    def test_basic_fields(self):
        m = QueryMetric(
            retrieval_ms=100.0, candidate_count=10, selected_count=5,
            source_count=3, manifest_version=1,
        )
        assert m.retrieval_ms == 100.0
        assert m.candidate_count == 10
        assert m.context_k is None

    def test_extended_fields_default_none(self):
        m = QueryMetric(
            retrieval_ms=50.0, candidate_count=5, selected_count=3,
            source_count=2, manifest_version=1,
        )
        assert m.index_ms is None
        assert m.embedding_ms is None
        assert m.rewrite_ms is None
        assert m.decompose_ms is None
        assert m.dense_ms is None
        assert m.bm25_ms is None
        assert m.rerank_ms is None
        assert m.llm_ms is None
        assert m.ttft_ms is None
        assert m.prompt_tokens is None
        assert m.completion_tokens is None
        assert m.citation_valid is None
        assert m.citation_invalid is None
        assert m.rewrite_changed is None

    def test_extended_fields_set(self):
        m = QueryMetric(
            retrieval_ms=200.0, candidate_count=20, selected_count=10,
            source_count=5, manifest_version=2,
            rewrite_ms=50.0, decompose_ms=30.0, llm_ms=500.0,
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
            citation_valid=3, citation_invalid=1,
            rewrite_changed=True, rewrite_merge_overlap=5,
        )
        assert m.rewrite_ms == 50.0
        assert m.llm_ms == 500.0
        assert m.prompt_tokens == 100
        assert m.citation_valid == 3
        assert m.rewrite_changed is True

    def test_frozen(self):
        m = QueryMetric(
            retrieval_ms=100.0, candidate_count=10, selected_count=5,
            source_count=3, manifest_version=1,
        )
        with pytest.raises(AttributeError):
            m.retrieval_ms = 200.0


class TestMetricsRecorderExtended:
    def test_default_max_records(self):
        r = MetricsRecorder()
        assert r._max_records == 1000  # 从 100 提升到 1000

    def test_custom_max_records(self):
        r = MetricsRecorder(max_records=50)
        assert r._max_records == 50

    def test_summary_empty(self):
        r = MetricsRecorder()
        s = r.summary()
        assert s["query_count"] == 0

    def test_summary_basic(self):
        r = MetricsRecorder()
        r.record(QueryMetric(
            retrieval_ms=100.0, candidate_count=10, selected_count=5,
            source_count=3, manifest_version=1,
        ))
        s = r.summary()
        assert s["query_count"] == 1
        assert s["retrieval_ms_avg"] == 100.0
        assert s["retrieval_ms_last"] == 100.0

    def test_summary_phase_latency(self):
        """分阶段延迟统计。"""
        r = MetricsRecorder()
        r.record(QueryMetric(
            retrieval_ms=200.0, candidate_count=10, selected_count=5,
            source_count=3, manifest_version=1,
            rewrite_ms=50.0, llm_ms=500.0,
        ))
        s = r.summary()
        assert "rewrite_ms_avg" in s
        assert s["rewrite_ms_avg"] == 50.0
        assert "llm_ms_avg" in s
        assert s["llm_ms_avg"] == 500.0

    def test_summary_token_stats(self):
        """Token 统计。"""
        r = MetricsRecorder()
        r.record(QueryMetric(
            retrieval_ms=100.0, candidate_count=10, selected_count=5,
            source_count=3, manifest_version=1,
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
        ))
        s = r.summary()
        assert s["prompt_tokens_total"] == 100
        assert s["completion_tokens_total"] == 50

    def test_summary_citation_rate(self):
        """引用有效率。"""
        r = MetricsRecorder()
        r.record(QueryMetric(
            retrieval_ms=100.0, candidate_count=10, selected_count=5,
            source_count=3, manifest_version=1,
            citation_valid=3, citation_invalid=1,
        ))
        s = r.summary()
        assert s["citation_valid_rate"] == 0.75

    def test_summary_rewrite_stats(self):
        """Rewrite 统计。"""
        r = MetricsRecorder()
        r.record(QueryMetric(
            retrieval_ms=100.0, candidate_count=10, selected_count=5,
            source_count=3, manifest_version=1,
            rewrite_changed=True,
        ))
        r.record(QueryMetric(
            retrieval_ms=100.0, candidate_count=10, selected_count=5,
            source_count=3, manifest_version=1,
            rewrite_changed=False,
        ))
        s = r.summary()
        assert s["rewrite_count"] == 1
        assert s["rewrite_rate"] == 0.5

    def test_summary_context_k(self):
        """context_k 统计。"""
        r = MetricsRecorder()
        r.record(QueryMetric(
            retrieval_ms=100.0, candidate_count=10, selected_count=5,
            source_count=3, manifest_version=1,
            context_k=5,
        ))
        s = r.summary()
        assert s["context_k_avg"] == 5.0
        assert s["context_k_last"] == 5


class TestMetricsPersistence:
    def test_save_and_load(self, tmp_path):
        """持久化到磁盘并加载。"""
        filepath = str(tmp_path / "metrics.json")
        r = MetricsRecorder(persist_path=filepath)
        r.record(QueryMetric(
            retrieval_ms=100.0, candidate_count=10, selected_count=5,
            source_count=3, manifest_version=1,
        ))
        # 文件应存在
        assert os.path.exists(filepath)

        # 新实例加载
        r2 = MetricsRecorder(persist_path=filepath)
        s = r2.summary()
        assert s["query_count"] == 1

    def test_load_nonexistent(self, tmp_path):
        """加载不存在的文件不报错。"""
        filepath = str(tmp_path / "nonexistent.json")
        r = MetricsRecorder(persist_path=filepath)
        assert r.summary()["query_count"] == 0

    def test_load_invalid_json(self, tmp_path):
        """加载无效 JSON 不报错。"""
        filepath = str(tmp_path / "bad.json")
        with open(filepath, "w") as f:
            f.write("not json")
        r = MetricsRecorder(persist_path=filepath)
        assert r.summary()["query_count"] == 0

    def test_backward_compatible_load(self, tmp_path):
        """旧格式记录（缺少新字段）加载不报错。"""
        filepath = str(tmp_path / "old_metrics.json")
        with open(filepath, "w") as f:
            json.dump([{
                "retrieval_ms": 100.0,
                "candidate_count": 10,
                "selected_count": 5,
                "source_count": 3,
                "manifest_version": 1,
            }], f)
        r = MetricsRecorder(persist_path=filepath)
        s = r.summary()
        assert s["query_count"] == 1


class TestElapsedMs:
    def test_positive(self):
        from time import perf_counter
        start = perf_counter()
        ms = elapsed_ms(start)
        assert ms >= 0.0
