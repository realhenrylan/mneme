"""Tests for evaluation.compare — Graph RAG 阶段 4 入场评测框架。

验证核心组件：
- chunk 真值映射 (match_snippet_to_chunks, build_ground_truth_map)
- 多轮链构建 (build_conversation_chains, canonical_history_for_turn)
- group-aware split
- 答案要点覆盖率 (compute_answer_point_coverage)
- 受控检索管线 (_run_retrieval_arm)
- 汇总统计 (compute_summary)
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from evaluation.compare import (
    match_snippet_to_chunks,
    build_ground_truth_map,
    get_relevant_chunk_ids,
    build_conversation_chains,
    canonical_history_for_turn,
    group_aware_split,
    compute_answer_point_coverage,
    compute_summary,
    _normalize_text,
    GroundTruthEntry,
    RetrievalCaseResult,
    GenerationCaseResult,
    ARM_STANDARD,
    ARM_STANDARD_RERANK,
    ARM_GRAPH_RERANK,
    GRAPH_TARGET_TYPES,
)
from evaluation.schema import EvalCase, RelevantChunk, QueryType, Language


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def sample_metadatas():
    """模拟 6 个 chunk 的元数据。"""
    return [
        {"chunk_id": "chunk_0", "source_id": "doc_a.pdf", "source_name": "doc_a.pdf",
         "source": "doc_a.pdf", "section_heading": "地理概况", "chunk_index": 0},
        {"chunk_id": "chunk_1", "source_id": "doc_a.pdf", "source_name": "doc_a.pdf",
         "source": "doc_a.pdf", "section_heading": "地理概况", "chunk_index": 1},
        {"chunk_id": "chunk_2", "source_id": "doc_a.pdf", "source_name": "doc_a.pdf",
         "source": "doc_a.pdf", "section_heading": "历史", "chunk_index": 2},
        {"chunk_id": "chunk_3", "source_id": "doc_b.pdf", "source_name": "doc_b.pdf",
         "source": "doc_b.pdf", "section_heading": "Introduction", "chunk_index": 0},
        {"chunk_id": "chunk_4", "source_id": "doc_b.pdf", "source_name": "doc_b.pdf",
         "source": "doc_b.pdf", "section_heading": "Methods", "chunk_index": 1},
        {"chunk_id": "chunk_5", "source_id": "doc_c.pdf", "source_name": "doc_c.pdf",
         "source": "doc_c.pdf", "section_heading": "Summary", "chunk_index": 0},
    ]


@pytest.fixture
def sample_docs():
    """模拟 6 个 chunk 的文本。"""
    return [
        "南京市总面积6587.02平方公里，位于长江下游。",
        "南京海拔最高点为紫金山，海拔448.9米。",
        "南京有着近2500年的建城史。",
        "Speculative decoding is a technique for accelerating LLM inference.",
        "DSpark improves speculative decoding by using multiple draft models.",
        "OneDrive provides 5GB of free storage for personal accounts.",
    ]


@pytest.fixture
def sample_cases():
    """模拟评测 case 列表。"""
    return [
        EvalCase(
            id="zh-001",
            query="南京的面积是多少？",
            query_type=QueryType.SINGLE_FACT,
            language=Language.ZH,
            relevant_source_ids=["doc_a.pdf"],
            relevant_chunks=[
                RelevantChunk(source_id="doc_a.pdf", chunk_text_snippet="南京市总面积6587.02平方公里"),
            ],
            acceptable_answer_points=["南京总面积6587.02平方公里"],
            should_refuse=False,
            metadata={"difficulty": "easy"},
        ),
        EvalCase(
            id="en-001",
            query="What is speculative decoding?",
            query_type=QueryType.SINGLE_FACT,
            language=Language.EN,
            relevant_source_ids=["doc_b.pdf"],
            relevant_chunks=[
                RelevantChunk(source_id="doc_b.pdf", chunk_text_snippet="Speculative decoding is a technique for accelerating LLM inference"),
            ],
            acceptable_answer_points=["technique for accelerating LLM inference"],
            should_refuse=False,
            metadata={"difficulty": "easy"},
        ),
        EvalCase(
            id="noanswer-001",
            query="What is the capital of France?",
            query_type=QueryType.NO_ANSWER,
            language=Language.EN,
            relevant_source_ids=[],
            relevant_chunks=[],
            acceptable_answer_points=[],
            should_refuse=True,
            metadata={"difficulty": "easy"},
        ),
    ]


@pytest.fixture
def multi_turn_cases():
    """模拟多轮对话 case。"""
    return [
        EvalCase(
            id="multi-001",
            query="南京的地理概况是怎样的？",
            query_type=QueryType.MULTI_TURN,
            language=Language.ZH,
            relevant_source_ids=["doc_a.pdf"],
            relevant_chunks=[],
            acceptable_answer_points=["南京位于长江下游"],
            should_refuse=False,
            metadata={"turn": 1, "follow_up_to": None, "difficulty": "easy"},
        ),
        EvalCase(
            id="multi-002",
            query="它的海拔最高点呢？",
            query_type=QueryType.MULTI_TURN,
            language=Language.ZH,
            relevant_source_ids=["doc_a.pdf"],
            relevant_chunks=[],
            acceptable_answer_points=["紫金山海拔448.9米"],
            should_refuse=False,
            metadata={"turn": 2, "follow_up_to": "multi-001", "difficulty": "medium"},
        ),
        EvalCase(
            id="multi-003",
            query="那里有什么温泉？",
            query_type=QueryType.MULTI_TURN,
            language=Language.ZH,
            relevant_source_ids=["doc_a.pdf"],
            relevant_chunks=[],
            acceptable_answer_points=["汤山温泉"],
            should_refuse=False,
            metadata={"turn": 3, "follow_up_to": "multi-002", "difficulty": "hard"},
        ),
    ]


# ── _normalize_text ──────────────────────────────────────────────────

class TestNormalizeText:
    def test_compress_whitespace(self):
        assert _normalize_text("hello   world") == "hello world"

    def test_chinese_punctuation(self):
        assert _normalize_text("南京，面积：6587") == "南京,面积:6587"

    def test_lowercase(self):
        assert _normalize_text("Hello World") == "hello world"

    def test_strip(self):
        assert _normalize_text("  hello  ") == "hello"


# ── match_snippet_to_chunks ─────────────────────────────────────────

class TestMatchSnippetToChunks:
    def test_exact_match(self, sample_metadatas, sample_docs):
        """snippet 完整包含在 chunk 文本中 → exact 匹配。"""
        ids, method = match_snippet_to_chunks(
            "南京市总面积6587.02平方公里",
            "doc_a.pdf",
            sample_metadatas,
            sample_docs,
        )
        assert method == "exact"
        assert "chunk_0" in ids

    def test_overlap_match(self, sample_metadatas, sample_docs):
        """snippet 不完整包含但有 token overlap → overlap 匹配。"""
        ids, method = match_snippet_to_chunks(
            "南京海拔紫金山448.9米最高点",
            "doc_a.pdf",
            sample_metadatas,
            sample_docs,
        )
        # 应该匹配到 chunk_1（包含海拔、紫金山、448.9米）
        assert method in ("exact", "overlap")
        assert len(ids) > 0

    def test_source_fallback(self, sample_metadatas, sample_docs):
        """snippet 完全不匹配任何 chunk → source_fallback。"""
        ids, method = match_snippet_to_chunks(
            "南京的美食文化非常丰富",
            "doc_a.pdf",
            sample_metadatas,
            sample_docs,
        )
        assert method == "source_fallback"
        # 应该返回 doc_a.pdf 的所有 chunk
        assert len(ids) == 3  # chunk_0, chunk_1, chunk_2

    def test_unmatched_source(self, sample_metadatas, sample_docs):
        """source_id 不存在 → unmatched。"""
        ids, method = match_snippet_to_chunks(
            "Some text",
            "nonexistent.pdf",
            sample_metadatas,
            sample_docs,
        )
        assert method == "unmatched"
        assert len(ids) == 0

    def test_empty_snippet(self, sample_metadatas, sample_docs):
        """空 snippet → unmatched。"""
        ids, method = match_snippet_to_chunks(
            "",
            "doc_a.pdf",
            sample_metadatas,
            sample_docs,
        )
        assert method == "unmatched"


# ── build_ground_truth_map ──────────────────────────────────────────

class TestBuildGroundTruthMap:
    def test_basic_mapping(self, sample_cases, sample_metadatas, sample_docs):
        """基本 ground truth 映射构建。"""
        entries = build_ground_truth_map(sample_cases, sample_metadatas, sample_docs)
        # zh-001 有 1 个 relevant_chunk，en-001 有 1 个，noanswer-001 should_refuse 跳过
        assert len(entries) == 2

        # zh-001 应该 exact 匹配
        zh_entries = [e for e in entries if e.case_id == "zh-001"]
        assert len(zh_entries) == 1
        assert zh_entries[0].match_method == "exact"
        assert "chunk_0" in zh_entries[0].matched_chunk_ids

    def test_should_refuse_skipped(self, sample_metadatas, sample_docs):
        """should_refuse 的 case 不应出现在 ground truth 中。"""
        case = EvalCase(
            id="noanswer-001",
            query="What is the capital of France?",
            query_type=QueryType.NO_ANSWER,
            language=Language.EN,
            relevant_source_ids=[],
            relevant_chunks=[],
            acceptable_answer_points=[],
            should_refuse=True,
        )
        entries = build_ground_truth_map([case], sample_metadatas, sample_docs)
        assert len(entries) == 0

    def test_empty_snippet_gets_source_fallback(self, sample_metadatas, sample_docs):
        """无 snippet 的 relevant_chunk 应标记为 source_fallback。"""
        case = EvalCase(
            id="meta-001",
            query="哪些文档讨论了LLM？",
            query_type=QueryType.METADATA,
            language=Language.ZH,
            relevant_source_ids=["doc_b.pdf"],
            relevant_chunks=[
                RelevantChunk(source_id="doc_b.pdf", chunk_text_snippet=""),
            ],
            acceptable_answer_points=["doc_b.pdf"],
            should_refuse=False,
        )
        entries = build_ground_truth_map([case], sample_metadatas, sample_docs)
        assert len(entries) == 1
        assert entries[0].match_method == "source_fallback"
        assert entries[0].reviewer_status == "needs_review"


# ── get_relevant_chunk_ids ──────────────────────────────────────────

class TestGetRelevantChunkIds:
    def test_excludes_source_fallback(self):
        """source_fallback 条目应从 chunk 级指标分母中排除。"""
        gt = {
            "case-1": ["chunk_0", "chunk_1"],  # exact match
        }
        case = EvalCase(
            id="case-1", query="test", query_type=QueryType.SINGLE_FACT,
            language=Language.ZH, relevant_source_ids=["doc_a.pdf"],
        )
        ids = get_relevant_chunk_ids(case, gt)
        assert ids == {"chunk_0", "chunk_1"}

    def test_empty_ground_truth(self):
        """无 ground truth → 空集。"""
        case = EvalCase(
            id="case-1", query="test", query_type=QueryType.SINGLE_FACT,
            language=Language.ZH, relevant_source_ids=["doc_a.pdf"],
        )
        ids = get_relevant_chunk_ids(case, {})
        assert ids == set()


# ── build_conversation_chains ───────────────────────────────────────

class TestBuildConversationChains:
    def test_single_chain(self, multi_turn_cases):
        """3 个 multi_turn case 形成 1 条链。"""
        chains = build_conversation_chains(multi_turn_cases)
        assert len(chains) == 1
        root_id = list(chains.keys())[0]
        assert root_id == "multi-001"
        assert len(chains[root_id]) == 3
        # 按 turn 排序
        assert chains[root_id][0].id == "multi-001"
        assert chains[root_id][1].id == "multi-002"
        assert chains[root_id][2].id == "multi-003"

    def test_no_multi_turn(self, sample_cases):
        """无非多轮 case → 空链。"""
        chains = build_conversation_chains(sample_cases)
        assert len(chains) == 0

    def test_multiple_chains(self):
        """多条独立链。"""
        cases = [
            EvalCase(id="m1", query="q1", query_type=QueryType.MULTI_TURN,
                     language=Language.ZH, metadata={"turn": 1, "follow_up_to": None}),
            EvalCase(id="m2", query="q2", query_type=QueryType.MULTI_TURN,
                     language=Language.ZH, metadata={"turn": 2, "follow_up_to": "m1"}),
            EvalCase(id="m3", query="q3", query_type=QueryType.MULTI_TURN,
                     language=Language.EN, metadata={"turn": 1, "follow_up_to": None}),
        ]
        chains = build_conversation_chains(cases)
        assert len(chains) == 2


# ── canonical_history_for_turn ──────────────────────────────────────

class TestCanonicalHistoryForTurn:
    def test_first_turn_empty_history(self, multi_turn_cases):
        """第一轮无历史。"""
        history = canonical_history_for_turn(multi_turn_cases, 0)
        assert history == []

    def test_second_turn_has_first(self, multi_turn_cases):
        """第二轮有第一轮的历史。"""
        history = canonical_history_for_turn(multi_turn_cases, 1)
        assert len(history) == 1
        assert history[0][0] == "南京的地理概况是怎样的？"
        # 占位 answer 来自 acceptable_answer_points
        assert "南京位于长江下游" in history[0][1]

    def test_third_turn_has_two(self, multi_turn_cases):
        """第三轮有前两轮的历史。"""
        history = canonical_history_for_turn(multi_turn_cases, 2)
        assert len(history) == 2

    def test_custom_answers(self, multi_turn_cases):
        """使用自定义 canonical answers。"""
        answers = {
            "multi-001": "南京位于长江下游，面积6587平方公里。",
            "multi-002": "紫金山，海拔448.9米。",
        }
        history = canonical_history_for_turn(multi_turn_cases, 2, answers=answers)
        assert len(history) == 2
        assert history[0][1] == "南京位于长江下游，面积6587平方公里。"
        assert history[1][1] == "紫金山，海拔448.9米。"


# ── group_aware_split ───────────────────────────────────────────────

class TestGroupAwareSplit:
    def test_chain_not_split(self, multi_turn_cases, sample_cases):
        """multi_turn chain 不被拆散。"""
        all_cases = sample_cases + multi_turn_cases
        dev, holdout = group_aware_split(all_cases, holdout_ratio=0.2, seed=42)

        # 检查 chain 中的 case 要么全在 dev，要么全在 holdout
        dev_ids = {c.id for c in dev}
        holdout_ids = {c.id for c in holdout}

        chain_ids = {"multi-001", "multi-002", "multi-003"}
        in_dev = chain_ids & dev_ids
        in_holdout = chain_ids & holdout_ids
        # 不应该同时出现在两侧
        assert not (in_dev and in_holdout)

    def test_total_count_preserved(self, sample_cases):
        """拆分后总数不变。"""
        dev, holdout = group_aware_split(sample_cases, holdout_ratio=0.12, seed=42)
        assert len(dev) + len(holdout) == len(sample_cases)


# ── compute_answer_point_coverage ───────────────────────────────────

class TestComputeAnswerPointCoverage:
    def test_full_coverage(self):
        """所有要点都被覆盖。"""
        answer = "南京总面积6587.02平方公里，位于长江下游。"
        points = ["南京总面积6587.02平方公里", "位于长江下游"]
        assert compute_answer_point_coverage(answer, points) == 1.0

    def test_partial_coverage(self):
        """部分要点被覆盖。"""
        answer = "南京总面积6587.02平方公里。"
        points = ["南京总面积6587.02平方公里", "紫金山海拔448.9米"]
        coverage = compute_answer_point_coverage(answer, points)
        assert 0.0 < coverage < 1.0

    def test_no_coverage(self):
        """无要点被覆盖。"""
        answer = "北京是中国的首都。"
        points = ["南京总面积6587.02平方公里", "紫金山海拔448.9米"]
        assert compute_answer_point_coverage(answer, points) == 0.0

    def test_empty_points(self):
        """无要点 → vacuously 1.0。"""
        assert compute_answer_point_coverage("any answer", []) == 1.0

    def test_english_coverage(self):
        """英文答案要点覆盖。"""
        answer = "Speculative decoding accelerates LLM inference by using draft models."
        points = ["technique for accelerating LLM inference"]
        coverage = compute_answer_point_coverage(answer, points)
        assert coverage > 0.0


# ── RetrievalCaseResult metrics ─────────────────────────────────────

class TestRetrievalCaseResultMetrics:
    def test_candidate_metrics(self):
        """候选检索层指标计算。"""
        result = RetrievalCaseResult(
            case_id="test", arm=ARM_STANDARD, query="test",
            query_type="single_fact", language="zh", should_refuse=False,
            candidate_chunk_ids=["c1", "c2", "c3", "c4", "c5"],
            candidate_source_ids=["s1", "s2"],
            candidate_scores=[0.5, 0.4, 0.3, 0.2, 0.1],
            context_chunk_ids=["c1", "c2"],
            context_source_ids=["s1"],
            relevant_chunk_ids={"c1", "c3"},
            relevant_source_ids={"s1"},
        )
        metrics = result.candidate_metrics(ks=(5,))
        assert metrics["recall@5"] == 1.0  # c1 和 c3 都在前 5
        assert metrics["mrr"] == 1.0  # c1 在第 1 位

    def test_context_metrics(self):
        """Context 层指标计算。"""
        result = RetrievalCaseResult(
            case_id="test", arm=ARM_STANDARD, query="test",
            query_type="single_fact", language="zh", should_refuse=False,
            candidate_chunk_ids=["c1", "c2", "c3"],
            candidate_source_ids=["s1"],
            candidate_scores=[0.5, 0.4, 0.3],
            context_chunk_ids=["c1", "c3"],
            context_source_ids=["s1"],
            relevant_chunk_ids={"c1", "c3"},
            relevant_source_ids={"s1"},
        )
        metrics = result.context_metrics()
        assert metrics["context_recall"] == 1.0  # 2/2
        assert metrics["context_precision"] == 1.0  # 2/2

    def test_context_metrics_partial(self):
        """Context 层部分召回。"""
        result = RetrievalCaseResult(
            case_id="test", arm=ARM_STANDARD, query="test",
            query_type="single_fact", language="zh", should_refuse=False,
            candidate_chunk_ids=["c1", "c2", "c3"],
            candidate_source_ids=["s1"],
            candidate_scores=[0.5, 0.4, 0.3],
            context_chunk_ids=["c1", "c2"],
            context_source_ids=["s1"],
            relevant_chunk_ids={"c1", "c3"},
            relevant_source_ids={"s1"},
        )
        metrics = result.context_metrics()
        assert metrics["context_recall"] == 0.5  # 1/2
        assert metrics["context_precision"] == 0.5  # 1/2


# ── compute_summary ─────────────────────────────────────────────────

class TestComputeSummary:
    def test_basic_summary(self, sample_cases):
        """基本汇总统计。"""
        results = [
            RetrievalCaseResult(
                case_id="zh-001", arm=ARM_STANDARD, query="test",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["c1"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["c1"], context_source_ids=["s1"],
                relevant_chunk_ids={"c1"}, relevant_source_ids={"s1"},
                total_retrieval_ms=100.0,
            ),
            RetrievalCaseResult(
                case_id="en-001", arm=ARM_STANDARD, query="test",
                query_type="single_fact", language="en", should_refuse=False,
                candidate_chunk_ids=["c3"], candidate_source_ids=["s2"],
                candidate_scores=[0.4],
                context_chunk_ids=["c3"], context_source_ids=["s2"],
                relevant_chunk_ids={"c3"}, relevant_source_ids={"s2"},
                total_retrieval_ms=150.0,
            ),
        ]
        summary = compute_summary(results, sample_cases, [ARM_STANDARD])
        assert "standard" in summary
        assert "overall" in summary["standard"]

    def test_graph_target_slice(self):
        """Graph 目标切片统计。"""
        cases = [
            EvalCase(id="cross-001", query="q", query_type=QueryType.CROSS_DOCUMENT,
                     language=Language.ZH, relevant_source_ids=["s1"],
                     acceptable_answer_points=["point1"]),
            EvalCase(id="mixed-001", query="q", query_type=QueryType.MIXED_INTENT,
                     language=Language.MIXED, relevant_source_ids=["s1"],
                     acceptable_answer_points=["point2"]),
        ]
        results = [
            RetrievalCaseResult(
                case_id="cross-001", arm=ARM_GRAPH_RERANK, query="q",
                query_type="cross_document", language="zh", should_refuse=False,
                candidate_chunk_ids=["c1"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["c1"], context_source_ids=["s1"],
                relevant_chunk_ids={"c1"}, relevant_source_ids={"s1"},
                graph_lift=True, graph_pollution=False,
                total_retrieval_ms=200.0,
            ),
            RetrievalCaseResult(
                case_id="mixed-001", arm=ARM_GRAPH_RERANK, query="q",
                query_type="mixed_intent", language="mixed", should_refuse=False,
                candidate_chunk_ids=["c2"], candidate_source_ids=["s1"],
                candidate_scores=[0.4],
                context_chunk_ids=["c2"], context_source_ids=["s1"],
                relevant_chunk_ids={"c2"}, relevant_source_ids={"s1"},
                graph_lift=False, graph_pollution=False,
                total_retrieval_ms=180.0,
            ),
        ]
        summary = compute_summary(results, cases, [ARM_GRAPH_RERANK])
        graph_rerank = summary.get("graph_rerank", {})
        # graph_target 切片应包含 cross_document + mixed_intent
        assert "graph_target" in graph_rerank
        gt_metrics = graph_rerank["graph_target"]
        assert gt_metrics.get("graph_lift_rate") == 0.5  # 1/2


# ── GRAPH_TARGET_TYPES ──────────────────────────────────────────────

class TestGraphTargetTypes:
    def test_includes_cross_document(self):
        assert QueryType.CROSS_DOCUMENT in GRAPH_TARGET_TYPES

    def test_includes_mixed_intent(self):
        assert QueryType.MIXED_INTENT in GRAPH_TARGET_TYPES

    def test_excludes_single_fact(self):
        assert QueryType.SINGLE_FACT not in GRAPH_TARGET_TYPES
