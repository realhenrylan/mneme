"""M1.1 chunk_id 域归一修复测试（12-hex 归一口径）。

背景（M1 发现）：v2.1 真值 relevant_chunk_ids 遵循 index_contract 冻结格式
``{source_sha256_prefix12}_chunk_{n}``（12-hex），而运行时索引 metadata 的
source_id 为 ``source_id_for_path``（sha256 规范化绝对路径）64-hex 全长——
同一哈希的两种截断，字符串比对两域永不相交（M1 冒烟 citation 全零根因）。

修复：评测侧归一 ``_normalize_chunk_id``——64-hex 截断为 12-hex 前缀，
12-hex 幂等，其余原样；run_case 把比对双方（真值/context/candidate/
chunk_to_source）统一归一到 12-hex 域后再交 citation 指标。
只影响评测侧比对：不改 src/、不改 index_contract.py（产品侧 ID 域是既有
冻结契约，本线只测量）。
"""

from pathlib import Path

import pytest

from evaluation.citation_metrics import evaluate_citations_context_aware
from evaluation.generation_runner import (
    GenerationRunner,
    _normalize_chunk_id,
)
from evaluation.schema import EvalCase, Language, QueryType

# 真实样例（取自 v2 语料 registry 与 M1 冒烟 outcomes 的索引域）：
# 同源同一 chunk 的两种形态
_TRUTH_12HEX = "32c427fb50e2_chunk_115"
_INDEX_64HEX = (
    "32c427fb50e2d80912f2ef69da69781b42bfc6a1ee92b6928b8eea400229356e"
    "_chunk_115"
)
# 无关源（非同源 64-hex，前缀不同）
_UNRELATED_64HEX = (
    "999999999999d80912f2ef69da69781b42bfc6a1ee92b6928b8eea400229356e"
    "_chunk_7"
)


class TestNormalizeChunkId:
    def test_64hex_index_id_normalizes_to_matching_12hex_truth(self):
        assert _normalize_chunk_id(_INDEX_64HEX) == _TRUTH_12HEX

    def test_12hex_input_is_idempotent(self):
        assert _normalize_chunk_id(_TRUTH_12HEX) == _TRUTH_12HEX

    def test_unrelated_64hex_does_not_collapse_to_truth(self):
        assert _normalize_chunk_id(_UNRELATED_64HEX) != _TRUTH_12HEX

    def test_mixed_domain_set_deduplicates_to_single_identity(self):
        normalized = {
            _normalize_chunk_id(x)
            for x in [_INDEX_64HEX, _TRUTH_12HEX, _TRUTH_12HEX]
        }
        assert normalized == {_TRUTH_12HEX}

    def test_non_standard_input_passes_through_unchanged(self):
        assert _normalize_chunk_id("chunk_5") == "chunk_5"
        assert _normalize_chunk_id("") == ""


def _idx_meta():
    return {
        "chunk_id": _INDEX_64HEX,
        "source_name": "python-tutorial-zh.md",
    }


def _make_case() -> EvalCase:
    return EvalCase(
        id="zh-fact-001",
        query="测试问题？",
        query_type=QueryType.SINGLE_FACT,
        language=Language.ZH,
        relevant_source_ids=["python-tutorial-zh.md"],
        relevant_chunks=[],
        relevant_chunk_ids=[_TRUTH_12HEX],
        acceptable_answer_points=["要点A"],
        should_refuse=False,
    )


class TestRunCaseNormalizedDomain:
    def test_run_case_feeds_normalized_domains_into_citation_metrics(self, monkeypatch):
        """端到端：索引侧 64-hex 引用 + 真值 12-hex，归一后 precision/recall 恢复。"""
        runner = GenerationRunner(Path("unused.jsonl"), None)
        runner._index_built = True
        runner._all_docs = ["文档"]
        runner._all_metadatas = [_idx_meta()]

        def fake_answer_query(**kwargs):
            answer = "答案是 42 [S1]"
            sources = (
                "[S1] python-tutorial-zh.md "
                f"(chunk_id={_INDEX_64HEX}): 文档内容"
            )
            return answer, sources

        monkeypatch.setattr("src.rag.answer_query", fake_answer_query)

        result = runner.run_case(_make_case())

        assert result.citation_metrics.citation_precision == 1.0
        assert result.citation_metrics.citation_recall == 1.0
        assert result.citation_metrics.context_supported_citation_validity == 1.0

    def test_run_case_records_normalized_domains_for_diagnosis(self, monkeypatch):
        """outcomes 诊断字段：归一后的 context/relevant chunk 全量落盘（区分
        检索缺口 vs 引用未覆盖两类缺口——M2 citation 报告的分析基础）。"""
        runner = GenerationRunner(Path("unused.jsonl"), None)
        runner._index_built = True
        runner._all_docs = ["文档"]
        runner._all_metadatas = [_idx_meta()]

        def fake_answer_query(**kwargs):
            return "答案是 42 [S1]", (
                "[S1] python-tutorial-zh.md "
                f"(chunk_id={_INDEX_64HEX}): 文档内容"
            )

        monkeypatch.setattr("src.rag.answer_query", fake_answer_query)

        result = runner.run_case(_make_case())

        assert result.context_chunk_ids == [_TRUTH_12HEX]
        assert result.relevant_chunk_ids == [_TRUTH_12HEX]

    def test_run_case_relevant_domain_is_normalized_before_comparison(self):
        """真值侧 12-hex 在归一域内与索引侧 64-hex 可达（集合层验证）。"""
        normalized_relevant = {_normalize_chunk_id(_TRUTH_12HEX)}
        normalized_context = {_normalize_chunk_id(_INDEX_64HEX)}
        assert normalized_relevant & normalized_context == {_TRUTH_12HEX}
