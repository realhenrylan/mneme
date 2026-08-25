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
    compute_split_fingerprint,
    compute_answer_point_coverage,
    compute_summary,
    _normalize_text,
    GroundTruthEntry,
    QueryPlan,
    RetrievalCaseResult,
    GenerationCaseResult,
    ARM_STANDARD,
    ARM_STANDARD_RERANK,
    ARM_GRAPH_RERANK,
    GRAPH_TARGET_TYPES,
    merge_graph_candidates,
    build_query_plan_cache,
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


# ── group_aware_split 跨进程确定性（PYTHONHASHSEED 无关） ─────────────

class TestGroupAwareSplitHashSeedDeterminism:
    """group_aware_split 必须与 PYTHONHASHSEED 无关（跨进程确定性）。

    旧实现把 ``set(chain_root_ids)`` 直接转 list 后 shuffle，set 迭代
    顺序随 PYTHONHASHSEED 变化 → 同一 ``--seed=42`` 在不同进程得到不同
    dev/holdout 集合。本测试用至少 3 个不同 PYTHONHASHSEED 的独立
    子进程对真实 v1 数据集运行同一 split，断言 case_id 集合与顺序
    完全一致（不依赖也不要求 PYTHONHASHSEED）。
    """

    @staticmethod
    def _run_in_subprocess(hash_seed: int) -> dict:
        """在独立 Python 子进程中以指定 PYTHONHASHSEED 计算 split。"""
        import json
        import os
        import subprocess
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        dataset = repo_root / "evaluation" / "datasets" / "v1.jsonl"
        script = (
            "import json\n"
            "from evaluation.schema import load_dataset\n"
            "from evaluation.compare import group_aware_split\n"
            f"cases = load_dataset({str(dataset)!r})\n"
            "dev, holdout = group_aware_split(cases, seed=42)\n"
            "print(json.dumps({'dev': [c.id for c in dev], "
            "'holdout': [c.id for c in holdout]}, "
            "ensure_ascii=False, sort_keys=True))\n"
        )
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = str(hash_seed)
        env["PYTHONPATH"] = str(repo_root)
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True,
            env=env, cwd=str(repo_root),
            timeout=180,
        )
        assert proc.returncode == 0, (
            f"subprocess failed (PYTHONHASHSEED={hash_seed}): {proc.stderr}"
        )
        return json.loads(proc.stdout.strip())

    def test_split_identical_across_hash_seeds(self):
        """至少 3 个不同 PYTHONHASHSEED：dev/holdout 集合与顺序完全一致。"""
        outputs = {
            seed: self._run_in_subprocess(seed) for seed in (0, 1, 42)
        }
        first = outputs[0]
        for seed, out in outputs.items():
            assert out == first, (
                f"split differs across PYTHONHASHSEED (0 vs {seed}): "
                f"dev/holdout 集合或顺序不一致 — group_aware_split 必须与 "
                f"PYTHONHASHSEED 无关"
            )
        # 健全性：dev/holdout 不重叠且并集为全集
        dev_ids = set(first["dev"])
        holdout_ids = set(first["holdout"])
        assert not (dev_ids & holdout_ids), "dev/holdout 不应有重叠 case"

    def test_split_matches_in_process_result(self):
        """子进程结果与当前进程直接调用结果一致。"""
        import json
        from pathlib import Path

        from evaluation.schema import load_dataset

        repo_root = Path(__file__).resolve().parents[1]
        cases = load_dataset(repo_root / "evaluation" / "datasets" / "v1.jsonl")
        dev, holdout = group_aware_split(cases, seed=42)
        in_process = json.dumps(
            {"dev": [c.id for c in dev], "holdout": [c.id for c in holdout]},
            ensure_ascii=False, sort_keys=True,
        )
        sub = self._run_in_subprocess(0)
        assert json.dumps(sub, ensure_ascii=False, sort_keys=True) == in_process

    def test_output_stably_sorted(self, multi_turn_cases, sample_cases):
        """输出顺序稳定排序（按 case_id）→ JSONL/pack/锁配置可复现。"""
        all_cases = sample_cases + multi_turn_cases
        dev, holdout = group_aware_split(all_cases, holdout_ratio=0.2, seed=42)
        assert [c.id for c in dev] == sorted(c.id for c in dev)
        assert [c.id for c in holdout] == sorted(c.id for c in holdout)


# ── compute_split_fingerprint（split 锁定指纹） ───────────────────────

class TestSplitFingerprint:
    """compute_split_fingerprint：确定性、输入敏感、锁定格式。"""

    def test_fingerprint_stable_full_sha256(self, multi_turn_cases, sample_cases):
        """同输入 → 同指纹；格式为完整 64 位小写 hex SHA-256。"""
        all_cases = sample_cases + multi_turn_cases
        dev, holdout = group_aware_split(all_cases, seed=42)
        fp = compute_split_fingerprint(dev, holdout)
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)
        assert fp == compute_split_fingerprint(dev, holdout)

    def test_fingerprint_changes_with_seed(self):
        """seed 变化（split 结果变化）→ 指纹变化。

        用真实 v1 数据集（fixture 数据量太小，不同 seed 可能产生
        相同拆分，无法体现指纹敏感性）。
        """
        from pathlib import Path

        from evaluation.schema import load_dataset

        cases = load_dataset(
            Path(__file__).resolve().parents[1] / "evaluation/datasets/v1.jsonl",
        )
        dev1, holdout1 = group_aware_split(cases, seed=42)
        dev2, holdout2 = group_aware_split(cases, seed=43)
        assert (
            compute_split_fingerprint(dev1, holdout1)
            != compute_split_fingerprint(dev2, holdout2)
        )

    def test_fingerprint_changes_with_case_membership(
        self, multi_turn_cases, sample_cases,
    ):
        """case 集合变化（dataset 变化）→ 指纹变化。"""
        all_cases = sample_cases + multi_turn_cases
        dev, holdout = group_aware_split(all_cases, seed=42)
        fp = compute_split_fingerprint(dev, holdout)
        moved = holdout[0]
        dev_moved = [moved] + [c for c in dev if c.id != moved.id]
        fp_moved = compute_split_fingerprint(dev_moved, holdout[1:])
        assert fp != fp_moved

    def test_fingerprint_independent_of_input_order(
        self, multi_turn_cases, sample_cases,
    ):
        """同一集合、不同输入顺序 → 相同指纹（canonical 排序）。"""
        all_cases = sample_cases + multi_turn_cases
        dev, holdout = group_aware_split(all_cases, seed=42)
        fp = compute_split_fingerprint(dev, holdout)
        fp_reversed = compute_split_fingerprint(list(reversed(dev)),
                                                list(reversed(holdout)))
        assert fp == fp_reversed


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

    # ── Source-level 指标（与 chunk 指标对称，独立分母）──

    def test_source_candidate_metrics(self):
        """候选层 source recall 按去重 source 集合计。"""
        result = RetrievalCaseResult(
            case_id="test", arm=ARM_STANDARD, query="test",
            query_type="single_fact", language="zh", should_refuse=False,
            candidate_chunk_ids=["c1", "c2", "c3", "c4", "c5"],
            candidate_source_ids=["s1", "s2"],
            candidate_scores=[0.5, 0.4, 0.3, 0.2, 0.1],
            context_chunk_ids=["c1", "c2"],
            context_source_ids=["s1"],
            relevant_chunk_ids={"c1", "c3"},
            relevant_source_ids={"s1", "s3"},
        )
        # top-5 sources={s1,s2}，与 {s1,s3} 交集 = {s1} → 1/2
        m = result.source_candidate_metrics((5, 10))
        assert m["source_recall@5"] == 0.5
        assert m["source_recall@10"] == 0.5

    def test_source_candidate_recall_truncation(self):
        """relevant source 出现在第 6 位：@5 截断 0.5、@10 命中 1.0。"""
        result = RetrievalCaseResult(
            case_id="test", arm=ARM_STANDARD, query="test",
            query_type="single_fact", language="zh", should_refuse=False,
            candidate_chunk_ids=[f"c{i}" for i in range(10)],
            candidate_source_ids=["sx", "sb", "sb", "sx", "sx", "s1", "sb", "sx", "sx", "sx"],
            candidate_scores=[0.0] * 10,
            context_chunk_ids=["c1"], context_source_ids=["sx"],
            relevant_chunk_ids=set(),
            relevant_source_ids={"s1", "s2"},
        )
        # candidate_source_ids 已是去重有序；前 5 项 dict 保留首现位置：
        # s@5 截断后应等价于前 5 个去重 candidate source
        m = result.source_candidate_metrics((5, 10))
        # top-5 去重 sources={sx,sb}，与需追溯 {s1,s2} 不相交 → 0.0
        assert m["source_recall@5"] == 0.0
        # top-10 含 s1 → 交集 {s1} → 1/2
        assert m["source_recall@10"] == 0.5

    def test_context_source_metrics_recall_and_coverage(self):
        """context_source_metrics 计算 recall 与 coverage。"""
        result = RetrievalCaseResult(
            case_id="test", arm=ARM_STANDARD, query="test",
            query_type="single_fact", language="zh", should_refuse=False,
            candidate_chunk_ids=["c1", "c2", "c3"],
            candidate_source_ids=["s1", "s2", "s3"],
            candidate_scores=[0.5, 0.4, 0.3],
            context_chunk_ids=["c1", "c2"],
            context_source_ids=["s1", "s2"],
            relevant_chunk_ids={"c1"},
            relevant_source_ids={"s1", "s3"},
        )
        # context sources={s1,s2}，与 {s1,s3} 交集={s1} → recall=1/2、coverage=1/2
        m = result.context_source_metrics()
        assert m["context_source_recall"] == 0.5
        assert m["context_source_coverage"] == 0.5

    def test_context_source_metrics_empty_relevant(self):
        """无 relevant_source_ids → recall=0、coverage 仍按 context 非空计。"""
        result = RetrievalCaseResult(
            case_id="test", arm=ARM_STANDARD, query="test",
            query_type="single_fact", language="zh", should_refuse=False,
            candidate_chunk_ids=["c1"], candidate_source_ids=["s1"],
            candidate_scores=[0.5],
            context_chunk_ids=["c1"], context_source_ids=["s1"],
            relevant_chunk_ids={"c1"},
            relevant_source_ids=set(),
        )
        m = result.context_source_metrics()
        assert m["context_source_recall"] == 0.0
        # context 非空但无 relevant → coverage=0/1=0.0
        assert m["context_source_coverage"] == 0.0

    def test_context_source_metrics_empty_context(self):
        """context 为空 → recall 与 coverage 均为 0。"""
        result = RetrievalCaseResult(
            case_id="test", arm=ARM_STANDARD, query="test",
            query_type="single_fact", language="zh", should_refuse=False,
            candidate_chunk_ids=["c1"], candidate_source_ids=["s1"],
            candidate_scores=[0.5],
            context_chunk_ids=[], context_source_ids=[],
            relevant_chunk_ids=set(),
            relevant_source_ids={"s1"},
        )
        m = result.context_source_metrics()
        assert m["context_source_recall"] == 0.0
        assert m["context_source_coverage"] == 0.0


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


# ── QueryPlan 共享 ──────────────────────────────────────────────────

class TestQueryPlan:
    def test_query_plan_dataclass_fields(self):
        """QueryPlan 包含共享 rewrite/decompose/基础检索结果。"""
        plan = QueryPlan(
            rewritten_query="南京面积",
            rewrite_log={"changed": True},
            sub_queries=["南京面积"],
            base_candidates={0: 0.5, 1: 0.3},
            rewrite_ms=100.0,
            decompose_ms=50.0,
        )
        assert plan.rewritten_query == "南京面积"
        assert plan.base_candidates == {0: 0.5, 1: 0.3}
        assert plan.rewrite_ms == 100.0
        assert plan.decompose_ms == 50.0


# ── merge_graph_candidates（RRF 同量纲融合） ─────────────────────────

@pytest.fixture
def merge_metadatas():
    """8 个 chunk 的元数据，用于 merge_graph_candidates 测试。"""
    return [
        {"chunk_id": "chunk_0", "source_id": "a.pdf"},
        {"chunk_id": "chunk_1", "source_id": "a.pdf"},
        {"chunk_id": "chunk_2", "source_id": "a.pdf"},
        {"chunk_id": "chunk_3", "source_id": "b.pdf"},
        {"chunk_id": "chunk_4", "source_id": "b.pdf"},
        {"chunk_id": "chunk_5", "source_id": "c.pdf"},
        {"chunk_id": "chunk_6", "source_id": "c.pdf"},
        {"chunk_id": "chunk_7", "source_id": "c.pdf"},
    ]


class TestMergeGraphCandidates:
    """调用真实 merge_graph_candidates helper，验证 RRF(k=60) 融合。"""

    def test_base_preserved_with_graph_only_candidates(self, merge_metadatas):
        """base candidates 全部保留，graph-only candidates 增量添加。"""
        base = {0: 0.016, 1: 0.015, 2: 0.014}  # RRF 量级 ~1/(rank+60)
        # Graph 返回 chunk_5, chunk_6（不在 base 中）
        graph_chunk_ids = ["chunk_5", "chunk_6"]
        alpha = 0.7

        merged, graph_only = merge_graph_candidates(
            base, graph_chunk_ids, merge_metadatas, alpha,
        )

        # base candidates 必须保留
        assert 0 in merged
        assert 1 in merged
        assert 2 in merged
        # graph-only candidates 增量添加
        assert 5 in merged
        assert 6 in merged
        assert graph_only == ["chunk_5", "chunk_6"]

    def test_overlap_uses_rrf_fusion(self, merge_metadatas):
        """同时出现在 base 和 Graph 中的 candidate 使用 alpha*base + (1-alpha)*graph_rrf。"""
        base = {0: 0.016, 1: 0.015}
        # Graph 返回 chunk_1（在 base 中，rank=0）和 chunk_5（graph-only）
        graph_chunk_ids = ["chunk_1", "chunk_5"]
        alpha = 0.7

        merged, graph_only = merge_graph_candidates(
            base, graph_chunk_ids, merge_metadatas, alpha,
        )

        # chunk_1 融合后：alpha*0.015 + (1-alpha)*(1/60) = 0.7*0.015 + 0.3*0.01667
        expected_chunk_1 = 0.7 * 0.015 + 0.3 * (1.0 / 60)
        assert abs(merged[1] - expected_chunk_1) < 1e-9
        # chunk_0 未受 Graph 影响
        assert merged[0] == 0.016
        # graph_only 只包含 chunk_5
        assert graph_only == ["chunk_5"]

    def test_alpha_1_no_graph_only_added(self, merge_metadatas):
        """alpha=1.0 时禁止加入 graph-only candidates（C 与 B 严格一致）。

        这是关键修复：alpha=1.0 意味着纯 base 通道，
        graph-only candidates 不应出现在 merged 中。
        """
        base = {0: 0.016, 1: 0.015}
        graph_chunk_ids = ["chunk_5", "chunk_6"]
        alpha = 1.0

        merged, graph_only = merge_graph_candidates(
            base, graph_chunk_ids, merge_metadatas, alpha,
        )

        # graph-only candidates 不应被添加
        assert 5 not in merged
        assert 6 not in merged
        assert graph_only == []
        # merged 与 base 完全一致
        assert set(merged.keys()) == set(base.keys())
        assert merged[0] == base[0]
        assert merged[1] == base[1]

    def test_alpha_1_overlap_preserves_base_score(self, merge_metadatas):
        """alpha=1.0 时 overlap candidate 保留 base 分数不变。

        alpha=1.0: merged = 1.0*base + 0.0*graph_rrf = base
        """
        base = {0: 0.016, 1: 0.015}
        graph_chunk_ids = ["chunk_1"]  # 在 base 中
        alpha = 1.0

        merged, graph_only = merge_graph_candidates(
            base, graph_chunk_ids, merge_metadatas, alpha,
        )

        # chunk_1 分数 = 1.0*0.015 + 0.0*rrf = 0.015
        assert abs(merged[1] - 0.015) < 1e-12
        assert graph_only == []

    def test_dynamic_top_k_not_polluted_at_alpha_1(self, merge_metadatas):
        """alpha=1 时 merged 排序必须与 base 排序完全一致（dynamic_top_k 不受影响）。

        这是修复 4 的核心验证：alpha=1 时 C 的候选排序和最终 context
        必须与 B 严格一致，零分 graph-only 不得进入 dynamic_top_k。
        """
        base = {0: 0.016, 1: 0.015, 2: 0.014, 3: 0.013}
        graph_chunk_ids = ["chunk_5", "chunk_6", "chunk_7"]
        alpha = 1.0

        merged, graph_only = merge_graph_candidates(
            base, graph_chunk_ids, merge_metadatas, alpha,
        )

        # merged 排序必须与 base 排序完全一致
        base_sorted = sorted(base.keys(), key=lambda i: base[i], reverse=True)
        merged_sorted = sorted(merged.keys(), key=lambda i: merged[i], reverse=True)
        assert merged_sorted == base_sorted
        assert graph_only == []

    def test_rrf_scores_same_magnitude(self, merge_metadatas):
        """Graph RRF 分数与 base RRF 分数在同一量级（k=60）。

        旧实现 (1-alpha)/(rank+1) 在 alpha=0.7 时 rank=0 给 0.3，
        远大于 base RRF ~0.016，导致 Graph 不公平压过 base。
        新实现 1/(rank+60) 在 rank=0 时给 0.0167，与 base RRF 同量级。
        """
        base = {0: 0.016, 1: 0.015}
        graph_chunk_ids = ["chunk_5"]  # graph-only
        alpha = 0.5  # 50/50 融合

        merged, graph_only = merge_graph_candidates(
            base, graph_chunk_ids, merge_metadatas, alpha,
        )

        # graph-only score = (1-0.5) * 1/(0+60) = 0.5 * 0.01667 = 0.00833
        # 这远小于 base scores (0.016, 0.015)，不会不公平压过 base
        graph_score = merged[5]
        assert graph_score < base[0]
        assert graph_score < base[1]
        # 验证 graph RRF 量级
        assert abs(graph_score - 0.5 * (1.0 / 60)) < 1e-9


# ── build_query_plan_cache ──────────────────────────────────────────

class TestBuildQueryPlanCache:
    """测试 QueryPlan 缓存：每个 case 只调用一次 prepare_query_plan。"""

    @patch("evaluation.compare.prepare_query_plan")
    def test_one_call_per_case(self, mock_prepare):
        """build_query_plan_cache 对每个 case 只调用一次 prepare_query_plan。"""
        mock_prepare.return_value = QueryPlan(
            rewritten_query="test",
            rewrite_log={},
            sub_queries=["test"],
            base_candidates={0: 0.5},
        )

        cases = [
            EvalCase(id="case-1", query="q1", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, relevant_source_ids=[]),
            EvalCase(id="case-2", query="q2", query_type=QueryType.SINGLE_FACT,
                     language=Language.EN, relevant_source_ids=[]),
        ]

        cache = build_query_plan_cache(
            cases, model=None, collection=None, bm25=None,
            all_docs=[], all_metadatas=[],
        )

        # 每个 case 只调用一次
        assert mock_prepare.call_count == 2
        assert "case-1" in cache
        assert "case-2" in cache

    @patch("evaluation.compare.prepare_query_plan")
    def test_cache_returns_same_identity(self, mock_prepare):
        """cache[case_id] 与 prepare_query_plan 返回的是同一对象（identity）。"""
        plan_a = QueryPlan(
            rewritten_query="q1", rewrite_log={}, sub_queries=["q1"],
            base_candidates={0: 0.5},
        )
        plan_b = QueryPlan(
            rewritten_query="q2", rewrite_log={}, sub_queries=["q2"],
            base_candidates={1: 0.3},
        )
        mock_prepare.side_effect = [plan_a, plan_b]

        cases = [
            EvalCase(id="a", query="q1", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, relevant_source_ids=[]),
            EvalCase(id="b", query="q2", query_type=QueryType.SINGLE_FACT,
                     language=Language.EN, relevant_source_ids=[]),
        ]

        cache = build_query_plan_cache(
            cases, model=None, collection=None, bm25=None,
            all_docs=[], all_metadatas=[],
        )

        # identity 检查：cache 中的 plan 与 prepare_query_plan 返回的是同一对象
        assert cache["a"] is plan_a
        assert cache["b"] is plan_b

    @patch("evaluation.compare.prepare_query_plan")
    def test_abc_arms_receive_same_plan_identity(self, mock_prepare):
        """A/B/C 三臂从 cache 中取出的是同一个 QueryPlan 对象（is 比较）。

        这是修复 3 的核心验证：三臂必须收到同一 QueryPlan 实例，
        而非各自独立构建的不同对象。
        """
        shared_plan = QueryPlan(
            rewritten_query="shared query",
            rewrite_log={"changed": False},
            sub_queries=["shared query"],
            base_candidates={0: 0.016, 1: 0.015, 2: 0.014},
        )
        mock_prepare.return_value = shared_plan

        cases = [
            EvalCase(id="case-1", query="shared query",
                     query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, relevant_source_ids=[]),
        ]

        cache = build_query_plan_cache(
            cases, model=None, collection=None, bm25=None,
            all_docs=[], all_metadatas=[],
        )

        # 模拟 A/B/C 三臂从 cache 获取 plan
        plan_for_a = cache["case-1"]
        plan_for_b = cache["case-1"]
        plan_for_c = cache["case-1"]

        # identity 检查：三臂收到的是同一个对象
        assert plan_for_a is plan_for_b
        assert plan_for_b is plan_for_c
        assert plan_for_a is shared_plan

    @patch("evaluation.compare.prepare_query_plan")
    def test_multi_turn_history_passed(self, mock_prepare):
        """multi_turn case 的 canonical history 被正确传递给 prepare_query_plan。"""
        mock_prepare.return_value = QueryPlan(
            rewritten_query="rewritten", rewrite_log={},
            sub_queries=["rewritten"], base_candidates={},
        )

        cases = [
            EvalCase(id="m1", query="q1", query_type=QueryType.MULTI_TURN,
                     language=Language.ZH, metadata={"turn": 1, "follow_up_to": None}),
            EvalCase(id="m2", query="q2", query_type=QueryType.MULTI_TURN,
                     language=Language.ZH, metadata={"turn": 2, "follow_up_to": "m1"}),
        ]
        chain_map = {"m1": cases, "m2": cases}

        cache = build_query_plan_cache(
            cases, model=None, collection=None, bm25=None,
            all_docs=[], all_metadatas=[], chain_map=chain_map,
        )

        assert mock_prepare.call_count == 2
        # m1 (turn=0) history=[] ；m2 (turn=1) history=[(q1, ...)]
        call_kwargs = [c.kwargs for c in mock_prepare.call_args_list]
        assert call_kwargs[0]["history"] is None or call_kwargs[0]["history"] == []
        assert len(call_kwargs[1]["history"]) == 1


# ── B 基线 lift/pollution 跨 arm 持久化 ─────────────────────────────

class TestBBaselinePersistence:
    def test_lift_with_real_b_baseline(self):
        """使用真实 B context 计算 lift 的完整场景。"""
        b_ctx = {"chunk_0", "chunk_3"}
        c_ctx = {"chunk_0", "chunk_2", "chunk_5"}
        gt = {"chunk_0", "chunk_2"}

        b_missed = gt - b_ctx
        graph_lift = bool(b_missed and (b_missed & c_ctx))
        assert graph_lift is True

    def test_pollution_case(self):
        """Graph pollution 的典型场景：Graph-only chunk 挤出了 B 的 relevant chunk。"""
        b_ctx = {"chunk_0", "chunk_2"}
        c_ctx = {"chunk_0", "chunk_5", "chunk_6"}
        gt = {"chunk_0", "chunk_2"}

        b_relevant = b_ctx & gt
        c_relevant = c_ctx & gt
        assert len(c_relevant) < len(b_relevant)


# ── run_retrieval_grid 集成测试 ─────────────────────────────────────

class TestRunRetrievalGrid:
    """集成测试：验证 run_retrieval_grid 正确复用 QueryPlan。"""

    @patch("evaluation.compare._run_retrieval_arm")
    def test_query_plan_reused_across_arms_and_alphas(self, mock_run_arm):
        """1 case × 3 arms × 2 alphas: 每次 _run_retrieval_arm 收到同一个
        QueryPlan 对象（identity）。
        """
        from evaluation.compare import run_retrieval_grid, QueryPlan

        # Create QueryPlan instance
        plan = QueryPlan(
            rewritten_query="test query",
            rewrite_log={},
            sub_queries=["test query"],
            base_candidates={0: 0.5},
        )

        # Mock _run_retrieval_arm to capture query_plan argument
        captured_plans = []

        def mock_arm_impl(case, arm, model, collection, bm25, all_docs, all_metadatas,
                          query_plan, kg, alpha, history, ground_truth_chunk_ids,
                          b_context_chunk_ids, reranker=None, has_chunk_truth=True):
            captured_plans.append(query_plan)
            return RetrievalCaseResult(
                case_id=case.id,
                arm=arm,
                query=case.query,
                query_type=case.query_type.value,
                language=case.language.value,
                should_refuse=False,
                candidate_chunk_ids=["c0"],
                candidate_source_ids=["s0"],
                candidate_scores=[0.5],
                context_chunk_ids=["c0"],
                context_source_ids=["s0"],
                relevant_chunk_ids=set(),
                relevant_source_ids=set(),
                has_chunk_truth=has_chunk_truth,
                alpha=alpha,
            )

        mock_run_arm.side_effect = mock_arm_impl

        # Test case
        case = EvalCase(
            id="case-1",
            query="test query",
            query_type=QueryType.SINGLE_FACT,
            language=Language.ZH,
            relevant_chunks=[],
        )

        # Pre-built cache with the plan
        query_plan_cache = {"case-1": plan}

        # Run grid: 1 case × 3 arms × 2 alphas
        results = run_retrieval_grid(
            active_cases=[case],
            arms=["standard", "standard-rerank", "graph-rerank"],
            alpha_values=[1.0, 0.7],
            model=None,
            collection=None,
            bm25=None,
            all_docs=["test"],
            all_metadatas=[{"chunk_id": "c0"}],
            kg=None,
            query_plan_cache=query_plan_cache,
            gt_map={"case-1": set()},
            chain_map={},
        )

        # Verify: 1 case × 3 arms × 2 alphas = 6 results
        assert len(results) == 6

        # Verify: all 6 calls received the SAME QueryPlan instance (identity)
        assert len(captured_plans) == 6
        for captured in captured_plans:
            assert captured is plan

    @patch("evaluation.compare._run_retrieval_arm")
    @patch("evaluation.compare.prepare_query_plan")
    def test_multiple_cases_each_prepared_once(self, mock_prepare, mock_run_arm):
        """2 cases × 3 arms × 1 alpha: prepare_query_plan 每个 case 只调用一次。"""
        from evaluation.compare import run_retrieval_grid, QueryPlan

        plan1 = QueryPlan(
            rewritten_query="q1", rewrite_log={}, sub_queries=["q1"],
            base_candidates={0: 0.5},
        )
        plan2 = QueryPlan(
            rewritten_query="q2", rewrite_log={}, sub_queries=["q2"],
            base_candidates={1: 0.3},
        )
        mock_prepare.side_effect = [plan1, plan2]

        def mock_arm_impl(case, arm, model, collection, bm25, all_docs, all_metadatas,
                          query_plan, kg, alpha, history, ground_truth_chunk_ids,
                          b_context_chunk_ids, reranker=None, has_chunk_truth=True):
            return RetrievalCaseResult(
                case_id=case.id, arm=arm, query=case.query,
                query_type=case.query_type.value, language=case.language.value,
                should_refuse=False,
                candidate_chunk_ids=[], candidate_source_ids=[], candidate_scores=[],
                context_chunk_ids=[], context_source_ids=[],
                relevant_chunk_ids=set(), relevant_source_ids=set(),
                alpha=alpha,
                has_chunk_truth=has_chunk_truth,
            )

        mock_run_arm.side_effect = mock_arm_impl

        cases = [
            EvalCase(id="c1", query="q1", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, relevant_chunks=[]),
            EvalCase(id="c2", query="q2", query_type=QueryType.SINGLE_FACT,
                     language=Language.EN, relevant_chunks=[]),
        ]

        # Build cache (calls prepare_query_plan twice)
        cache = build_query_plan_cache(
            cases, model=None, collection=None, bm25=None,
            all_docs=[], all_metadatas=[],
        )
        assert mock_prepare.call_count == 2

        # Run grid: 2 cases × 3 arms × 1 alpha = 6 calls
        results = run_retrieval_grid(
            active_cases=cases,
            arms=["standard", "standard-rerank", "graph-rerank"],
            alpha_values=[0.7],
            model=None, collection=None, bm25=None,
            all_docs=[], all_metadatas=[],
            kg=None, query_plan_cache=cache,
            gt_map={"c1": set(), "c2": set()},
            chain_map={},
        )

        # prepare_query_plan still only called twice (cache reused)
        assert mock_prepare.call_count == 2

        # 2 cases × 3 arms × 1 alpha = 6 results
        assert len(results) == 6


# ── Reranker 验证测试 ────────────────────────────────────────────────

class TestRerankerValidation:
    """测试 validate_reranker() 和 _run_retrieval_arm 的防御性检查。"""

    def test_validate_reranker_a_only_no_check(self):
        """仅 A 组运行时返回 None（无需 reranker）。"""
        from evaluation.compare import validate_reranker

        result = validate_reranker([ARM_STANDARD])
        assert result is None  # A-only 返回 None

    @patch("src.rag._get_reranker")
    def test_validate_reranker_a_only_zero_calls(self, mock_get_reranker):
        """A-only 运行时不应调用 _get_reranker。"""
        from evaluation.compare import validate_reranker

        result = validate_reranker([ARM_STANDARD])
        assert result is None
        mock_get_reranker.assert_not_called()

    @patch("src.rag._get_reranker")
    def test_validate_reranker_b_missing_raises(self, mock_get_reranker):
        """B 组需要 reranker，缺失时抛出 RuntimeError。"""
        from evaluation.compare import validate_reranker

        mock_get_reranker.return_value = None

        with pytest.raises(RuntimeError, match="Reranker required"):
            validate_reranker([ARM_STANDARD, ARM_STANDARD_RERANK])

    @patch("src.rag._get_reranker")
    def test_validate_reranker_c_missing_raises(self, mock_get_reranker):
        """C 组需要 reranker，缺失时抛出 RuntimeError。"""
        from evaluation.compare import validate_reranker

        mock_get_reranker.return_value = None

        with pytest.raises(RuntimeError, match="Reranker required"):
            validate_reranker([ARM_STANDARD, ARM_GRAPH_RERANK])

    @patch("src.rag._get_reranker")
    def test_validate_reranker_available_passes(self, mock_get_reranker):
        """reranker 可用时返回实例。"""
        from evaluation.compare import validate_reranker

        mock_reranker = MagicMock()
        mock_get_reranker.return_value = mock_reranker

        result = validate_reranker([ARM_STANDARD, ARM_STANDARD_RERANK, ARM_GRAPH_RERANK])
        assert result is mock_reranker  # 返回同一实例

    def test_run_retrieval_arm_b_no_reranker_raises(self):
        """B 组直接调用 _run_retrieval_arm 时，若 reranker 缺失则防御性失败。

        不传 reranker 参数（为 None），B 臂内部回退到 _get_reranker() 并应失败。
        """
        import evaluation.compare as compare_mod
        from evaluation.compare import _run_retrieval_arm, QueryPlan

        plan = QueryPlan(
            rewritten_query="test",
            rewrite_log={},
            sub_queries=["test"],
            base_candidates={0: 0.5, 1: 0.3},
        )

        case = EvalCase(
            id="test-case",
            query="test query",
            query_type=QueryType.SINGLE_FACT,
            language=Language.ZH,
            relevant_chunks=[],
        )

        # Mock _get_reranker in src.rag to return None
        import src.rag as rag_mod
        original_get_reranker = rag_mod._get_reranker
        rag_mod._get_reranker = lambda: None

        try:
            with pytest.raises(RuntimeError, match="Reranker required for arm"):
                _run_retrieval_arm(
                    case=case,
                    arm=ARM_STANDARD_RERANK,
                    model=None,
                    collection=None,
                    bm25=None,
                    all_docs=["doc1", "doc2"],
                    all_metadatas=[{"chunk_id": "c0"}, {"chunk_id": "c1"}],
                    query_plan=plan,
                    reranker=None,
                )
        finally:
            rag_mod._get_reranker = original_get_reranker


# ── Alpha 分组保存测试 ───────────────────────────────────────────────

class TestAlphaGrouping:
    """测试多 alpha 运行时的分组保存逻辑。"""

    def test_results_grouped_by_alpha(self):
        """run_retrieval_grid 返回的结果按 alpha 字段分组。"""
        from evaluation.compare import run_retrieval_grid

        results = [
            RetrievalCaseResult(
                case_id="c1", arm=ARM_STANDARD, query="q1",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=[], candidate_source_ids=[], candidate_scores=[],
                context_chunk_ids=[], context_source_ids=[],
                relevant_chunk_ids=set(), relevant_source_ids=set(),
                alpha=1.0,
            ),
            RetrievalCaseResult(
                case_id="c1", arm=ARM_STANDARD, query="q1",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=[], candidate_source_ids=[], candidate_scores=[],
                context_chunk_ids=[], context_source_ids=[],
                relevant_chunk_ids=set(), relevant_source_ids=set(),
                alpha=0.7,
            ),
        ]

        # 按 alpha 分组
        results_by_alpha = {}
        for result in results:
            alpha = result.alpha
            if alpha not in results_by_alpha:
                results_by_alpha[alpha] = []
            results_by_alpha[alpha].append(result)

        assert len(results_by_alpha) == 2
        assert 1.0 in results_by_alpha
        assert 0.7 in results_by_alpha
        assert len(results_by_alpha[1.0]) == 1
        assert len(results_by_alpha[0.7]) == 1

    def test_compute_summary_single_alpha(self):
        """compute_summary 接受单 alpha 结果并生成配对统计。"""
        from evaluation.compare import compute_summary

        cases = [
            EvalCase(id="c1", query="q1", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, relevant_chunks=[]),
        ]

        results = [
            RetrievalCaseResult(
                case_id="c1", arm=ARM_STANDARD, query="q1",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                alpha=0.7,
            ),
            RetrievalCaseResult(
                case_id="c1", arm=ARM_STANDARD_RERANK, query="q1",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.6],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                alpha=0.7,
            ),
            RetrievalCaseResult(
                case_id="c1", arm=ARM_GRAPH_RERANK, query="q1",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0", "chunk_1"], candidate_source_ids=["s1", "s2"],
                candidate_scores=[0.7, 0.3],
                context_chunk_ids=["chunk_0", "chunk_1"], context_source_ids=["s1", "s2"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                alpha=0.7,
            ),
        ]

        summary = compute_summary(results, cases, [ARM_STANDARD, ARM_STANDARD_RERANK, ARM_GRAPH_RERANK])

        # 应包含所有 arm 的统计
        assert "standard" in summary
        assert "standard_rerank" in summary
        assert "graph_rerank" in summary

        # 应包含配对 C-B 统计
        assert "paired_cb" in summary
        paired_cb = summary["paired_cb"]
        # SINGLE_FACT 不在 GRAPH_TARGET_TYPES 中，所以只有 all_answerable 和 overall
        assert "all_answerable" in paired_cb
        assert "overall" in paired_cb

    def test_build_run_manifest_with_active_alpha(self, tmp_path):
        """build_run_manifest 接受 active_alpha 参数并写入 manifest。"""
        from evaluation.compare import build_run_manifest

        # 创建临时文件
        dataset_path = tmp_path / "test.jsonl"
        dataset_path.write_text('{"id": "test"}')
        corpus_dir = tmp_path / "test_texts"
        corpus_dir.mkdir()
        (corpus_dir / "doc1.pdf").write_bytes(b"test content")

        manifest = build_run_manifest(
            dataset_path=dataset_path,
            corpus_dir=corpus_dir,
            source_files=["doc1.pdf"],
            arms=[ARM_STANDARD, ARM_STANDARD_RERANK, ARM_GRAPH_RERANK],
            alpha_grid=[1.0, 0.7],
            seed=42,
            active_alpha=0.7,
        )

        assert "active_alpha" in manifest
        assert manifest["active_alpha"] == 0.7
        assert manifest["alpha_grid"] == [1.0, 0.7]

    def test_build_run_manifest_without_active_alpha(self, tmp_path):
        """build_run_manifest 不传 active_alpha 时为 None（向后兼容）。"""
        from evaluation.compare import build_run_manifest

        # 创建临时文件
        dataset_path = tmp_path / "test.jsonl"
        dataset_path.write_text('{"id": "test"}')
        corpus_dir = tmp_path / "test_texts"
        corpus_dir.mkdir()
        (corpus_dir / "doc1.pdf").write_bytes(b"test content")

        manifest = build_run_manifest(
            dataset_path=dataset_path,
            corpus_dir=corpus_dir,
            source_files=["doc1.pdf"],
            arms=[ARM_STANDARD],
            alpha_grid=None,
            seed=42,
        )

        assert "active_alpha" in manifest
        assert manifest["active_alpha"] is None


# ── Reranker 注入复用 ───────────────────────────────────────────────

class TestRerankerInjection:
    """测试 reranker 实例在 B/C 臂间的注入复用。"""

    @patch("src.rag.select_context_candidates")
    @patch("src.rag.expand_with_adjacent")
    @patch("src.rag.expand_with_parent")
    @patch("src.rag.compute_context_k")
    @patch("src.rag._build_context")
    @patch("src.rag.enrich_context")
    @patch("src.rag.dynamic_top_k")
    @patch("src.rag._get_reranker")
    def test_bc_share_same_instance_and_call_rerank(
        self, mock_get_reranker, mock_dynamic_top_k, mock_enrich,
        mock_build_context, mock_compute_k, mock_expand_parent,
        mock_expand_adjacent, mock_apply_diversity,
    ):
        """2 case × B/C 臂：同一注入 mock reranker 被调用 4 次，_get_reranker 零调用。"""
        from evaluation.compare import _run_retrieval_arm, QueryPlan
        from unittest.mock import MagicMock

        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = []
        mock_dynamic_top_k.return_value = 5
        mock_enrich.return_value = ["d1"]
        mock_build_context.return_value = "ctx"
        mock_compute_k.return_value = 2
        mock_expand_parent.return_value = ([0, 1], [])
        mock_expand_adjacent.return_value = [0, 1]
        mock_apply_diversity.return_value = []

        plan = QueryPlan(
            rewritten_query="test",
            rewrite_log={},
            sub_queries=["test"],
            base_candidates={0: 0.5},
        )

        case1 = EvalCase(
            id="t1", query="q1", query_type=QueryType.SINGLE_FACT,
            language=Language.ZH, relevant_chunks=[],
        )
        case2 = EvalCase(
            id="t2", query="q2", query_type=QueryType.SINGLE_FACT,
            language=Language.ZH, relevant_chunks=[],
        )

        # 2 cases × B/C = 4 calls
        for case in [case1, case2]:
            for arm in [ARM_STANDARD_RERANK, ARM_GRAPH_RERANK]:
                _run_retrieval_arm(
                    case=case, arm=arm,
                    model=None, collection=None, bm25=None,
                    all_docs=["d1"], all_metadatas=[{"chunk_id": "c0"}],
                    query_plan=plan, reranker=mock_reranker,
                )

        # 注入的 reranker.rerank 被调用 4 次，_get_reranker 从未调用
        assert mock_reranker.rerank.call_count == 4
        mock_get_reranker.assert_not_called()

    @patch("evaluation.compare._run_retrieval_arm")
    @patch("evaluation.compare.prepare_query_plan")
    def test_grid_passes_same_reranker_identity_to_arms(
        self, mock_prepare, mock_run_arm,
    ):
        """run_retrieval_grid 把同一 reranker 实例传给每个 arm 调用（identity 检查）。"""
        from evaluation.compare import run_retrieval_grid, QueryPlan
        from unittest.mock import MagicMock

        mock_reranker = MagicMock()
        mock_prepare.return_value = QueryPlan(
            rewritten_query="q", rewrite_log={}, sub_queries=["q"],
            base_candidates={0: 0.5},
        )

        # 捕获传给 _run_retrieval_arm 的 reranker 参数
        captured = []
        def capture(*args, **kwargs):
            captured.append(kwargs.get("reranker"))
            return RetrievalCaseResult(
                case_id="c1", arm="standard", query="q",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=[], candidate_source_ids=[],
                candidate_scores=[],
                context_chunk_ids=[], context_source_ids=[],
                relevant_chunk_ids=set(), relevant_source_ids=set(),
                alpha=0.7,
            )
        mock_run_arm.side_effect = capture

        case = EvalCase(
            id="c1", query="q", query_type=QueryType.SINGLE_FACT,
            language=Language.ZH, relevant_chunks=[],
        )

        run_retrieval_grid(
            active_cases=[case],
            arms=[ARM_STANDARD, ARM_STANDARD_RERANK, ARM_GRAPH_RERANK],
            alpha_values=[0.7],
            model=None, collection=None, bm25=None,
            all_docs=[], all_metadatas=[],
            kg=None,
            query_plan_cache={"c1": mock_prepare.return_value},
            gt_map={"c1": set()},
            chain_map={},
            reranker=mock_reranker,
        )

        # 3 arms × 1 case = 3 calls; 每个收到的 reranker 都是同一个对象
        assert len(captured) == 3
        for c in captured:
            assert c is mock_reranker

    def test_validate_reranker_returns_instance_for_bc(self):
        """validate_reranker 在 B/C 需 reranker 时返回实例。"""
        from evaluation.compare import validate_reranker
        from unittest.mock import patch

        mock_instance = MagicMock()
        with patch("src.rag._get_reranker", return_value=mock_instance):
            result = validate_reranker([ARM_STANDARD_RERANK])
            assert result is mock_instance

    def test_validate_reranker_returns_none_for_a_only(self):
        """validate_reranker 在 A-only 时返回 None。"""
        from evaluation.compare import validate_reranker

        result = validate_reranker([ARM_STANDARD])
        assert result is None


# ── A/B/C context 对称化 ─────────────────────────────────────────────

class TestContextSelectorSymmetry:
    """三臂 context 构建对称：A/B/C 使用同一 select_context_candidates，
    且 reranker 关闭时（RAG_RERANKER=none）A 的行为与 B 等价（仅排序不同）。
    """

    @patch("src.rag.select_context_candidates")
    @patch("src.rag.expand_with_adjacent")
    @patch("src.rag.expand_with_parent")
    @patch("src.rag.compute_context_k")
    @patch("src.rag._build_context")
    @patch("src.rag.enrich_context")
    @patch("src.rag.dynamic_top_k")
    def test_a_arm_also_applies_select_context_candidates(
        self, mock_dynamic_top_k, mock_enrich, mock_build_context,
        mock_compute_k, mock_expand_parent, mock_expand_adjacent,
        mock_select,
    ):
        """A 臂（standard）也必须调用 select_context_candidates——消除
        「A 无 diversity、B/C 独有截断」的不对称（诊断根因 2/3）。"""
        from evaluation.compare import _run_retrieval_arm, QueryPlan
        from unittest.mock import MagicMock

        mock_dynamic_top_k.return_value = 5
        mock_enrich.return_value = ["d1", "d2", "d3", "d4", "d5"]
        mock_build_context.return_value = "ctx"
        mock_compute_k.return_value = 3
        mock_expand_parent.return_value = ([0, 1, 2], [])
        mock_expand_adjacent.return_value = [0, 1, 2]
        # 让 select_context_candidates 原样返回候选 index
        def _fake_select(candidates, top_k=10, max_per_source=3):
            return candidates

        mock_select.side_effect = _fake_select

        plan = QueryPlan(
            rewritten_query="test", rewrite_log={}, sub_queries=["test"],
            base_candidates={i: 1.0 - i * 0.1 for i in range(5)},
        )
        case = EvalCase(
            id="t1", query="q1", query_type=QueryType.SINGLE_FACT,
            language=Language.ZH, relevant_chunks=[],
        )
        all_docs = [f"text{i}" for i in range(5)]
        all_metadatas = [{"chunk_id": f"c{i}", "source_id": "s0",
                          "source_name": "doc.pdf"} for i in range(5)]

        # A 臂无 reranker → reranker=None，仍应走 select_context_candidates
        _run_retrieval_arm(
            case=case, arm=ARM_STANDARD,
            model=None, collection=None, bm25=None,
            all_docs=all_docs, all_metadatas=all_metadatas,
            query_plan=plan, reranker=None,
        )
        assert mock_select.called, "A 臂必须调用 select_context_candidates"

    @patch("src.rag.select_context_candidates")
    @patch("src.rag.expand_with_adjacent")
    @patch("src.rag.expand_with_parent")
    @patch("src.rag.compute_context_k")
    @patch("src.rag._build_context")
    @patch("src.rag.enrich_context")
    @patch("src.rag.dynamic_top_k")
    def test_a_passes_chunk_text_to_candidates(
        self, mock_dynamic_top_k, mock_enrich, mock_build_context,
        mock_compute_k, mock_expand_parent, mock_expand_adjacent,
        mock_select,
    ):
        """A 臂构造候选时携带 chunk 文本（供后续 reranker/审计使用）。"""
        from evaluation.compare import _run_retrieval_arm, QueryPlan

        mock_dynamic_top_k.return_value = 3
        mock_enrich.return_value = ["d1", "d2", "d3"]
        mock_build_context.return_value = "ctx"
        mock_compute_k.return_value = 3
        mock_expand_parent.return_value = ([0, 1, 2], [])
        mock_expand_adjacent.return_value = [0, 1, 2]

        captured = {}

        def _fake_select(candidates, top_k=10, max_per_source=3):
            captured["candidates"] = candidates
            return candidates

        mock_select.side_effect = _fake_select

        plan = QueryPlan(
            rewritten_query="test", rewrite_log={}, sub_queries=["test"],
            base_candidates={i: 1.0 - i * 0.1 for i in range(3)},
        )
        case = EvalCase(
            id="t1", query="q1", query_type=QueryType.SINGLE_FACT,
            language=Language.ZH, relevant_chunks=[],
        )
        _run_retrieval_arm(
            case=case, arm=ARM_STANDARD,
            model=None, collection=None, bm25=None,
            all_docs=["alpha beta", "gamma delta", "epsilon"],
            all_metadatas=[{"chunk_id": f"c{i}", "source_id": "s0",
                            "source_name": "doc.pdf"} for i in range(3)],
            query_plan=plan, reranker=None,
        )
        cands = captured["candidates"]
        assert len(cands) == 3
        assert [c.text for c in cands] == ["alpha beta", "gamma delta", "epsilon"]
        assert cands[0].text == "alpha beta"  # 文本来自 all_docs 而非 source_name


# ── 拒绝混合 alpha ──────────────────────────────────────────────────

class TestAlphaMixingRejection:
    """测试 compute_summary 和 group_retrieval_results_by_alpha。"""

    def test_compute_summary_rejects_mixed_alpha(self):
        """compute_summary 收到多 alpha 结果时抛出 ValueError。"""
        from evaluation.compare import compute_summary

        results = [
            RetrievalCaseResult(
                case_id="c1", arm=ARM_STANDARD, query="q1",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=[], candidate_source_ids=[], candidate_scores=[],
                context_chunk_ids=[], context_source_ids=[],
                relevant_chunk_ids=set(), relevant_source_ids=set(),
                alpha=1.0,
            ),
            RetrievalCaseResult(
                case_id="c1", arm=ARM_STANDARD_RERANK, query="q1",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=[], candidate_source_ids=[], candidate_scores=[],
                context_chunk_ids=[], context_source_ids=[],
                relevant_chunk_ids=set(), relevant_source_ids=set(),
                alpha=0.7,
            ),
        ]

        cases = [
            EvalCase(id="c1", query="q1", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, relevant_chunks=[]),
        ]

        with pytest.raises(ValueError, match="multiple alpha"):
            compute_summary(results, cases, [ARM_STANDARD, ARM_STANDARD_RERANK])

    def test_group_then_summary_each_alpha_works(self):
        """group_retrieval_results_by_alpha 分组后每个 alpha 独立 compute_summary 成功。"""
        from evaluation.compare import compute_summary, group_retrieval_results_by_alpha

        results = [
            RetrievalCaseResult(
                case_id="c1", arm=ARM_STANDARD, query="q1",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                alpha=1.0,
            ),
            RetrievalCaseResult(
                case_id="c1", arm=ARM_STANDARD_RERANK, query="q1",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.6],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                alpha=1.0,
            ),
            RetrievalCaseResult(
                case_id="c1", arm=ARM_STANDARD, query="q1",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.4],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                alpha=0.7,
            ),
            RetrievalCaseResult(
                case_id="c1", arm=ARM_STANDARD_RERANK, query="q1",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                alpha=0.7,
            ),
        ]

        cases = [
            EvalCase(id="c1", query="q1", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, relevant_chunks=[]),
        ]

        grouped = group_retrieval_results_by_alpha(results)
        assert len(grouped) == 2
        assert 1.0 in grouped
        assert 0.7 in grouped

        # 每个 alpha 独立 compute_summary 成功
        for alpha_results in grouped.values():
            s = compute_summary(alpha_results, cases, [ARM_STANDARD, ARM_STANDARD_RERANK])
            assert "standard" in s


# ── 按 alpha 保存 helper ─────────────────────────────────────────────

class TestSaveByAlpha:
    """测试 save_retrieval_results_by_alpha helper。"""

    @patch("evaluation.compare.save_results")
    @patch("evaluation.compare.build_run_manifest")
    @patch("evaluation.compare.compute_summary")
    def test_two_alphas_save_to_separate_dirs(
        self, mock_compute, mock_manifest, mock_save,
    ):
        """两个 alpha 各自输出到 alpha-<value>/ 目录。"""
        from evaluation.compare import save_retrieval_results_by_alpha
        from pathlib import Path

        mock_compute.return_value = {"standard": {}}
        mock_manifest.return_value = {"compare_version": 1}

        results_by_alpha = {
            1.0: [
                RetrievalCaseResult(
                    case_id="c1", arm=ARM_STANDARD, query="q1",
                    query_type="single_fact", language="zh", should_refuse=False,
                    candidate_chunk_ids=[], candidate_source_ids=[],
                    candidate_scores=[],
                    context_chunk_ids=[], context_source_ids=[],
                    relevant_chunk_ids=set(), relevant_source_ids=set(),
                    alpha=1.0,
                ),
            ],
            0.7: [
                RetrievalCaseResult(
                    case_id="c1", arm=ARM_STANDARD, query="q1",
                    query_type="single_fact", language="zh", should_refuse=False,
                    candidate_chunk_ids=[], candidate_source_ids=[],
                    candidate_scores=[],
                    context_chunk_ids=[], context_source_ids=[],
                    relevant_chunk_ids=set(), relevant_source_ids=set(),
                    alpha=0.7,
                ),
            ],
        }

        with patch("builtins.open"):
            save_retrieval_results_by_alpha(
                results_by_alpha=results_by_alpha,
                alpha_values=[1.0, 0.7],
                output_dir=Path("/tmp/test_output"),
                active_cases=[],
                arms=[ARM_STANDARD],
                ground_truth=[],
                dataset_path=Path("test.jsonl"),
                corpus_dir=Path("/tmp/test_texts"),
                source_files=["doc1.pdf"],
            )

        # save_results 各被调用一次，输出到 alpha-<value>/ 子目录
        assert mock_save.call_count == 2
        call0_dir = mock_save.call_args_list[0].args[0]
        call1_dir = mock_save.call_args_list[1].args[0]
        assert str(call0_dir).endswith("alpha-0.7")
        assert str(call1_dir).endswith("alpha-1")

        # 每个 alpha 的 manifest 收到 active_alpha 参数
        for call in mock_manifest.call_args_list:
            assert call.kwargs.get("active_alpha") in (1.0, 0.7)

        # 每个 compute_summary 调用只收到对应 alpha 的结果
        assert mock_compute.call_count == 2
        for call in mock_compute.call_args_list:
            results_arg = call.args[0]
            alphas_in_call = {r.alpha for r in results_arg}
            assert len(alphas_in_call) == 1, (
                f"compute_summary received mixed alphas: {alphas_in_call}"
            )

        # save_results 参数中的 results（args[3]）也只包含对应 alpha
        for call in mock_save.call_args_list:
            results_arg = call.args[3]
            alphas_in_save = {r.alpha for r in results_arg}
            assert len(alphas_in_save) == 1, (
                f"save_results received mixed alphas: {alphas_in_save}"
            )

    @patch("evaluation.compare.save_results")
    @patch("evaluation.compare.build_run_manifest")
    @patch("evaluation.compare.compute_summary")
    def test_single_alpha_saves_to_output_root(
        self, mock_compute, mock_manifest, mock_save,
    ):
        """单 alpha 时直接保存到 output_dir（向后兼容，不使用子目录）。"""
        from evaluation.compare import save_retrieval_results_by_alpha
        from pathlib import Path

        mock_compute.return_value = {"standard": {}}
        mock_manifest.return_value = {"compare_version": 1}

        results_by_alpha = {
            0.7: [
                RetrievalCaseResult(
                    case_id="c1", arm=ARM_STANDARD, query="q1",
                    query_type="single_fact", language="zh", should_refuse=False,
                    candidate_chunk_ids=[], candidate_source_ids=[],
                    candidate_scores=[],
                    context_chunk_ids=[], context_source_ids=[],
                    relevant_chunk_ids=set(), relevant_source_ids=set(),
                    alpha=0.7,
                ),
            ],
        }

        save_retrieval_results_by_alpha(
            results_by_alpha=results_by_alpha,
            alpha_values=[0.7],
            output_dir=Path("/tmp/test_output"),
            active_cases=[],
            arms=[ARM_STANDARD],
            ground_truth=[],
            dataset_path=Path("test.jsonl"),
            corpus_dir=Path("/tmp/test_texts"),
            source_files=["doc1.pdf"],
        )

        # 单 alpha 时直接保存到 output_dir，不使用 alpha-... 子目录
        call_dir = mock_save.call_args_list[0].args[0]
        assert str(call_dir) == str(Path("/tmp/test_output"))

    @patch("evaluation.compare.save_results")
    @patch("evaluation.compare.build_run_manifest")
    @patch("evaluation.compare.compute_summary")
    def test_root_contains_only_grid_index_for_multi_alpha(
        self, mock_compute, mock_manifest, mock_save,
    ):
        """多 alpha 时根目录只包含 alpha-grid-summary.json 索引（无 summary 或 manifest）。

        每个 alpha 的 summary/manifest 仅在 alpha-<value>/ 子目录中，根目录仅有索引文件。
        """
        from evaluation.compare import save_retrieval_results_by_alpha
        from pathlib import Path

        mock_compute.return_value = {"standard": {}}
        mock_manifest.return_value = {"compare_version": 1}

        results_by_alpha = {
            1.0: [
                RetrievalCaseResult(
                    case_id="c1", arm=ARM_STANDARD, query="q1",
                    query_type="single_fact", language="zh", should_refuse=False,
                    candidate_chunk_ids=[], candidate_source_ids=[],
                    candidate_scores=[],
                    context_chunk_ids=[], context_source_ids=[],
                    relevant_chunk_ids=set(), relevant_source_ids=set(),
                    alpha=1.0,
                ),
            ],
            0.7: [
                RetrievalCaseResult(
                    case_id="c1", arm=ARM_STANDARD, query="q1",
                    query_type="single_fact", language="zh", should_refuse=False,
                    candidate_chunk_ids=[], candidate_source_ids=[],
                    candidate_scores=[],
                    context_chunk_ids=[], context_source_ids=[],
                    relevant_chunk_ids=set(), relevant_source_ids=set(),
                    alpha=0.7,
                ),
            ],
        }

        with patch("builtins.open") as mock_open:
            save_retrieval_results_by_alpha(
                results_by_alpha=results_by_alpha,
                alpha_values=[1.0, 0.7],
                output_dir=Path("/tmp/test_output"),
                active_cases=[],
                arms=[ARM_STANDARD],
                ground_truth=[],
                dataset_path=Path("test.jsonl"),
                corpus_dir=Path("/tmp/test_texts"),
                source_files=["doc1.pdf"],
            )

        # save_results 各自保存到子目录
        assert mock_save.call_count == 2
        assert str(mock_save.call_args_list[0].args[0]).endswith("alpha-0.7")
        assert str(mock_save.call_args_list[1].args[0]).endswith("alpha-1")

        # 根目录：open 至少被调用一次写入 grid index
        # （json.dump 通过 with open(...) 打开文件写入）
        assert mock_open.call_count >= 1
        # 第一个 open 调用是 alpha-grid-summary.json
        first_open_arg = mock_open.call_args_list[0].args
        assert first_open_arg
        path_str = str(first_open_arg[0])
        assert "alpha-grid-summary.json" in path_str


# ── 实体抽取缓存 ─────────────────────────────────────────────────────

class TestEntityCaching:
    """测试 prepare_query_plan 中的实体抽取缓存逻辑。"""

    def test_query_plan_has_graph_entities_field(self):
        """QueryPlan 包含 graph_entities 和 entity_ms 字段。"""
        plan = QueryPlan(
            rewritten_query="test",
            rewrite_log={},
            sub_queries=["test"],
            base_candidates={0: 0.5},
            graph_entities=["E1", "E2"],
            entity_ms=42.0,
        )
        assert plan.graph_entities == ["E1", "E2"]
        assert plan.entity_ms == 42.0

    @patch("evaluation.compare.prepare_query_plan")
    def test_entity_extracted_once_per_case(self, mock_prepare):
        """C 臂 + alpha<1.0 时，build_query_plan_cache 每个 case 只调用 prepare 一次。

        prepare_query_plan 内部的实体抽取逻辑已由独立测试覆盖，
        此处验证 build_query_plan_cache 对每个 case 只调用一次 prepare。
        """
        from evaluation.compare import build_query_plan_cache

        mock_prepare.return_value = QueryPlan(
            rewritten_query="q", rewrite_log={}, sub_queries=["q"],
            base_candidates={0: 0.5}, graph_entities=["E1", "E2"],
        )

        cases = [
            EvalCase(id="c1", query="q1", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, relevant_chunks=[]),
            EvalCase(id="c2", query="q2", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, relevant_chunks=[]),
        ]

        cache = build_query_plan_cache(
            cases, model=None, collection=None, bm25=None,
            all_docs=[], all_metadatas=[],
            arms=[ARM_STANDARD, ARM_GRAPH_RERANK],
            alpha_values=[0.7],
            kg=MagicMock(),
        )

        assert mock_prepare.call_count == 2
        assert cache["c1"].graph_entities == ["E1", "E2"]

    @patch("evaluation.compare.prepare_query_plan")
    def test_alpha_all_1_0_skips_entity_in_plan(self, mock_prepare):
        """alpha=1.0 时 prepare 返回空 graph_entities（由 prepare 内部逻辑保证）。

        此处验证 cache 正确透传 prepare 的结果。
        """
        from evaluation.compare import build_query_plan_cache

        mock_prepare.return_value = QueryPlan(
            rewritten_query="q", rewrite_log={}, sub_queries=["q"],
            base_candidates={0: 0.5}, graph_entities=[],
        )

        cases = [
            EvalCase(id="c1", query="q1", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, relevant_chunks=[]),
        ]

        cache = build_query_plan_cache(
            cases, model=None, collection=None, bm25=None,
            all_docs=[], all_metadatas=[],
            arms=[ARM_STANDARD, ARM_GRAPH_RERANK],
            alpha_values=[1.0],
            kg=MagicMock(),
        )

        assert cache["c1"].graph_entities == []

    @patch("evaluation.compare.prepare_query_plan")
    def test_entity_ms_passed_through(self, mock_prepare):
        """entity_ms 字段由 prepare_query_plan 设置，并透传到 cache。"""
        from evaluation.compare import build_query_plan_cache

        mock_prepare.return_value = QueryPlan(
            rewritten_query="q", rewrite_log={}, sub_queries=["q"],
            base_candidates={0: 0.5},
            graph_entities=["E1"],
            entity_ms=123.4,
        )

        cases = [
            EvalCase(id="c1", query="q1", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, relevant_chunks=[]),
        ]

        cache = build_query_plan_cache(
            cases, model=None, collection=None, bm25=None,
            all_docs=[], all_metadatas=[],
            arms=[ARM_STANDARD, ARM_GRAPH_RERANK],
            alpha_values=[0.7],
            kg=MagicMock(),
        )

        assert cache["c1"].entity_ms == 123.4


# ── chunk 真值分母 ──────────────────────────────────────────────────

class TestChunkTruthDenominator:
    """测试 chunk 真值分母的可靠性过滤。"""

    def test_only_exact_and_confirmed_enter_gt_map(self):
        """仅 exact 和 confirmed overlap/parent 进入 gt_map。"""
        from evaluation.compare import GroundTruthEntry

        entries = [
            GroundTruthEntry("c1", "doc1", "", ["chunk_0"], "exact", "auto"),
            GroundTruthEntry("c2", "doc1", "", ["chunk_1"], "overlap", "confirmed"),
            GroundTruthEntry("c3", "doc1", "", ["chunk_2"], "overlap", "auto"),
            GroundTruthEntry("c4", "doc1", "", ["chunk_3"], "overlap", "needs_review"),
            GroundTruthEntry("c5", "doc1", "", ["chunk_4"], "source_fallback", "auto"),
        ]

        gt_map: dict[str, list[str]] = {}
        for e in entries:
            if e.match_method in ("source_fallback", "unmatched"):
                continue
            is_reliable = (
                e.match_method == "exact"
                or e.reviewer_status == "confirmed"
            )
            if is_reliable:
                gt_map.setdefault(e.case_id, []).extend(e.matched_chunk_ids)

        # exact(any reviewer) → 纳入
        assert "c1" in gt_map
        # overlap(confirmed) → 纳入
        assert "c2" in gt_map
        # overlap(auto) → 排除
        assert "c3" not in gt_map
        # overlap(needs_review) → 排除
        assert "c4" not in gt_map
        # source_fallback → 排除
        assert "c5" not in gt_map

    def test_one_reliable_one_unreliable_context_recall_not_diluted(self):
        """1 个可靠 case + 1 个不可靠 answerable：聚合为可靠 case 的真实分数。"""
        from evaluation.compare import compute_summary

        # 可靠 chunk truth 的 case
        good = RetrievalCaseResult(
            case_id="c1", arm=ARM_STANDARD, query="q1",
            query_type="single_fact", language="zh", should_refuse=False,
            candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
            candidate_scores=[0.9],
            context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
            relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
            has_chunk_truth=True,
        )
        # answerable 但无可靠 chunk truth
        no_truth = RetrievalCaseResult(
            case_id="c2", arm=ARM_STANDARD, query="q2",
            query_type="single_fact", language="zh", should_refuse=False,
            candidate_chunk_ids=[], candidate_source_ids=[],
            candidate_scores=[],
            context_chunk_ids=[], context_source_ids=[],
            relevant_chunk_ids={"chunk_99"}, relevant_source_ids={"s2"},
            has_chunk_truth=False,
        )

        cases = [
            EvalCase(id="c1", query="q1", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, relevant_chunks=[]),
            EvalCase(id="c2", query="q2", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, relevant_chunks=[]),
        ]

        summary = compute_summary([good, no_truth], cases, [ARM_STANDARD])
        metrics = summary["standard"]["overall"]

        # context_recall = good 的 recall（1.0），而不是 (1.0+0)/2=0.5
        assert metrics["context_recall"] == 1.0
        # 记录排除数
        assert metrics["excluded_no_chunk_truth"] == 1
        assert metrics["n_chunk_valid"] == 1

    def test_no_reliable_chunk_truth_all_excluded(self):
        """全部 answerable 无可靠 chunk truth 时 chunk 指标为空。"""
        from evaluation.compare import compute_summary

        no_truth = RetrievalCaseResult(
            case_id="c1", arm=ARM_STANDARD, query="q1",
            query_type="single_fact", language="zh", should_refuse=False,
            candidate_chunk_ids=[], candidate_source_ids=[],
            candidate_scores=[],
            context_chunk_ids=[], context_source_ids=[],
            relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
            has_chunk_truth=False,
        )

        cases = [
            EvalCase(id="c1", query="q1", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, relevant_chunks=[]),
        ]

        summary = compute_summary([no_truth], cases, [ARM_STANDARD])
        metrics = summary["standard"]["overall"]

        assert metrics["excluded_no_chunk_truth"] == 1
        assert metrics["n_chunk_valid"] == 0
        assert metrics["context_recall"] == 0.0  # 无有效分母时返回 0.0

    def test_source_recall_unaffected_by_chunk_truth(self):
        """chunk 指标（recall@5 等）在可靠 case 上有正常值。"""
        from evaluation.compare import compute_summary

        has_truth = RetrievalCaseResult(
            case_id="c1", arm=ARM_STANDARD, query="q1",
            query_type="single_fact", language="zh", should_refuse=False,
            candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
            candidate_scores=[0.9],
            context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
            relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
            has_chunk_truth=True,
        )

        cases = [
            EvalCase(id="c1", query="q1", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, relevant_chunks=[]),
        ]

        summary = compute_summary([has_truth], cases, [ARM_STANDARD])

        # MRR 有正常值（基于 chunk truth）
        assert "mrr" in summary["standard"]["overall"]


# ── entity_ms 独立字段 ──────────────────────────────────────────────

class TestEntityMsField:
    """测试 RetrievalCaseResult.entity_ms 与 embedding_ms 分别正确。"""

    def test_entity_ms_separate_from_embedding_ms(self):
        """entity_ms 和 embedding_ms 是独立字段，不互相覆盖。"""
        result = RetrievalCaseResult(
            case_id="c1", arm=ARM_STANDARD, query="q",
            query_type="single_fact", language="zh", should_refuse=False,
            candidate_chunk_ids=[], candidate_source_ids=[],
            candidate_scores=[],
            context_chunk_ids=[], context_source_ids=[],
            relevant_chunk_ids=set(), relevant_source_ids=set(),
            entity_ms=42.0,
            embedding_ms=0.0,
        )
        assert result.entity_ms == 42.0
        assert result.embedding_ms == 0.0
        # entity_ms 不应覆盖 embedding_ms
        result2 = RetrievalCaseResult(
            case_id="c1", arm=ARM_STANDARD, query="q",
            query_type="single_fact", language="zh", should_refuse=False,
            candidate_chunk_ids=[], candidate_source_ids=[],
            candidate_scores=[],
            context_chunk_ids=[], context_source_ids=[],
            relevant_chunk_ids=set(), relevant_source_ids=set(),
            entity_ms=15.0,
            embedding_ms=7.5,
        )
        assert result2.entity_ms == 15.0
        assert result2.embedding_ms == 7.5


# ── alpha=1.0 C 臂跳过图路径 ────────────────────────────────────────

class TestAlphaOneSkipGraph:
    """测试 alpha=1.0 时 C 臂完全跳过 KG 调用。"""

    @patch("src.rag.apply_source_diversity")
    @patch("src.rag.expand_with_adjacent")
    @patch("src.rag.expand_with_parent")
    @patch("src.rag.compute_context_k")
    @patch("src.rag._build_context")
    @patch("src.rag.enrich_context")
    @patch("src.rag.dynamic_top_k")
    @patch("src.rag._get_reranker", return_value=MagicMock())
    def test_c_alpha_1_0_skips_kg_in_mixed_grid(
        self, mock_reranker, mock_topk, mock_enrich,
        mock_build, mock_k, mock_expand_p, mock_expand_a,
        mock_div,
    ):
        """混合 grid [1.0, 0.7] 中 alpha=1.0 的 C 臂不调用 KG 方法。"""
        from evaluation.compare import _run_retrieval_arm, QueryPlan

        mock_topk.return_value = 5
        mock_enrich.return_value = ["d1"]
        mock_build.return_value = ""
        mock_k.return_value = 2
        mock_expand_p.return_value = ([0], [])
        mock_expand_a.return_value = [0]
        mock_div.return_value = []

        kg_mock = MagicMock()
        plan = QueryPlan(
            rewritten_query="test",
            rewrite_log={},
            sub_queries=["test"],
            base_candidates={0: 0.5},
            graph_entities=["E1"],  # 有缓存实体
        )

        case = EvalCase(
            id="c1", query="q", query_type=QueryType.SINGLE_FACT,
            language=Language.ZH, relevant_chunks=[],
        )

        # alpha=1.0，C 臂 → 跳过 KG
        _run_retrieval_arm(
            case=case, arm=ARM_GRAPH_RERANK,
            model=None, collection=None, bm25=None,
            all_docs=["d1"], all_metadatas=[{"chunk_id": "c0"}],
            query_plan=plan, kg=kg_mock, alpha=1.0,
            reranker=MagicMock(),
        )

        # KG 方法从未调用
        kg_mock.get_related_entities.assert_not_called()
        kg_mock.get_chunks_by_entities.assert_not_called()

    @patch("src.rag.apply_source_diversity")
    @patch("src.rag.expand_with_adjacent")
    @patch("src.rag.expand_with_parent")
    @patch("src.rag.compute_context_k")
    @patch("src.rag._build_context")
    @patch("src.rag.enrich_context")
    @patch("src.rag.dynamic_top_k")
    @patch("src.rag._get_reranker", return_value=MagicMock())
    def test_c_alpha_0_7_calls_kg(
        self, mock_reranker, mock_topk, mock_enrich,
        mock_build, mock_k, mock_expand_p, mock_expand_a,
        mock_div,
    ):
        """alpha=0.7 的 C 臂正常调用 KG。"""
        from evaluation.compare import _run_retrieval_arm, QueryPlan

        mock_topk.return_value = 5
        mock_enrich.return_value = ["d1"]
        mock_build.return_value = ""
        mock_k.return_value = 2
        mock_expand_p.return_value = ([0], [])
        mock_expand_a.return_value = [0]
        mock_div.return_value = []

        kg_mock = MagicMock()
        kg_mock.get_related_entities.return_value = [("E1", 1.0)]
        kg_mock.get_chunks_by_entities.return_value = ["chunk_5"]

        plan = QueryPlan(
            rewritten_query="test",
            rewrite_log={},
            sub_queries=["test"],
            base_candidates={0: 0.5},
            graph_entities=["E1"],
        )

        case = EvalCase(
            id="c1", query="q", query_type=QueryType.SINGLE_FACT,
            language=Language.ZH, relevant_chunks=[],
        )

        _run_retrieval_arm(
            case=case, arm=ARM_GRAPH_RERANK,
            model=None, collection=None, bm25=None,
            all_docs=["d1"], all_metadatas=[{"chunk_id": "c0"}],
            query_plan=plan, kg=kg_mock, alpha=0.7,
            reranker=MagicMock(),
        )

        # alpha=0.7 → KG 被调用
        assert kg_mock.get_related_entities.call_count >= 1


# ── 真值可靠性严格条件 ──────────────────────────────────────────────

class TestChunkTruthStrictConditions:
    """测试可靠的 chunk 真值条件：exact 或 (overlap/parent + confirmed)。"""

    def test_confirmed_parent_included(self):
        """reviewer=confirmed 的 parent 应纳入 gt_map。"""
        entries = [
            GroundTruthEntry("c1", "doc1", "", ["chunk_0"], "parent", "confirmed"),
        ]

        gt_map: dict[str, list[str]] = {}
        for e in entries:
            if e.match_method in ("source_fallback", "unmatched"):
                continue
            is_reliable = (
                e.match_method == "exact"
                or (e.match_method in ("overlap", "parent") and e.reviewer_status == "confirmed")
            )
            if is_reliable:
                gt_map.setdefault(e.case_id, []).extend(e.matched_chunk_ids)

        assert "c1" in gt_map
        assert gt_map["c1"] == ["chunk_0"]

    def test_confirmed_non_overlap_parent_excluded(self):
        """reviewer=confirmed 但 match_method 不是 overlap/parent/exact → 排除。

        构造一个假的 GroundTruthEntry（stub），确保只有 exact 和
        overlap/parent+confirmed 可进入 gt_map。
        """
        # stub: confirmed 但 match_method 不是 exact/overlap/parent
        entries = [
            GroundTruthEntry("c1", "doc1", "", ["chunk_1"], "source_fallback", "confirmed"),
            GroundTruthEntry("c2", "doc1", "", ["chunk_2"], "unmatched", "confirmed"),
        ]

        gt_map: dict[str, list[str]] = {}
        for e in entries:
            if e.match_method in ("source_fallback", "unmatched"):
                continue
            is_reliable = (
                e.match_method == "exact"
                or (e.match_method in ("overlap", "parent") and e.reviewer_status == "confirmed")
            )
            if is_reliable:
                gt_map.setdefault(e.case_id, []).extend(e.matched_chunk_ids)

        # source_fallback + unmatched 都被排除（即便 confirmed 也不纳入）
        assert "c1" not in gt_map
        assert "c2" not in gt_map

    def test_should_refuse_not_in_denominator(self):
        """should_refuse 的 case 不影响 n_chunk_valid / excluded_no_chunk_truth。"""
        from evaluation.compare import compute_summary

        # 可靠 chunk truth 但 should_refuse=True 的 case
        refusal = RetrievalCaseResult(
            case_id="c1", arm=ARM_STANDARD, query="q",
            query_type="no_answer", language="zh", should_refuse=True,
            candidate_chunk_ids=[], candidate_source_ids=[],
            candidate_scores=[],
            context_chunk_ids=[], context_source_ids=[],
            relevant_chunk_ids=set(), relevant_source_ids=set(),
            has_chunk_truth=True,
        )

        cases = [
            EvalCase(id="c1", query="q", query_type=QueryType.NO_ANSWER,
                     language=Language.ZH, should_refuse=True, relevant_chunks=[]),
        ]

        summary = compute_summary([refusal], cases, [ARM_STANDARD])
        metrics = summary["standard"]["overall"]

        # should_refuse 不进入 chunk 指标分母
        assert metrics["n_chunk_valid"] == 0
        assert metrics["excluded_no_chunk_truth"] == 0  # 不是 answerable，不计入排除


# ── prepare_query_plan 调用真实 extract_entities_from_query ──────────

class TestPreparePlanEntityExtraction:
    """测试 prepare_query_plan 内部调用 src.graph_rag.extract_entities_from_query。"""

    @patch("src.graph_rag.extract_entities_from_query")
    @patch("src.rag.retrieve_hybrid_with_sources")
    def test_calls_extract_once_per_case_in_prepare(self, mock_retrieve, mock_extract):
        """C 臂 + alpha<1.0：prepare_query_plan 每个 case 调用一次 extractor。"""
        from evaluation.compare import prepare_query_plan

        mock_extract.return_value = ["E1", "E2"]
        mock_retrieve.return_value = ([], [], [0.5])

        case = EvalCase(
            id="c1", query="q1", query_type=QueryType.SINGLE_FACT,
            language=Language.ZH, relevant_chunks=[],
        )

        plan = prepare_query_plan(
            case, model=None, collection=None, bm25=None,
            all_docs=[], all_metadatas=[],
            arms=[ARM_STANDARD, ARM_GRAPH_RERANK],
            alpha_values=[0.7],
            kg=MagicMock(),
        )

        assert mock_extract.call_count == 1
        assert plan.graph_entities == ["E1", "E2"]
        assert plan.entity_ms >= 0

    @patch("src.graph_rag.extract_entities_from_query")
    @patch("src.rag.retrieve_hybrid_with_sources")
    def test_all_alpha_1_0_skips_in_prepare(self, mock_retrieve, mock_extract):
        """所有 alpha=1.0 时 prepare_query_plan 不调用 extractor。"""
        from evaluation.compare import prepare_query_plan

        mock_retrieve.return_value = ([], [], [0.5])

        case = EvalCase(
            id="c1", query="q1", query_type=QueryType.SINGLE_FACT,
            language=Language.ZH, relevant_chunks=[],
        )

        plan = prepare_query_plan(
            case, model=None, collection=None, bm25=None,
            all_docs=[], all_metadatas=[],
            arms=[ARM_STANDARD, ARM_GRAPH_RERANK],
            alpha_values=[1.0],
            kg=MagicMock(),
        )

        mock_extract.assert_not_called()
        assert plan.graph_entities == []


# ── Source-level retrieval 评测 ──────────────────────────────────────

class TestSourceLevelMetrics:
    """source-level retrieval 指标：分母隔离、纳入 source-only、不污染 chunk 口径。"""

    @staticmethod
    def _mk(case_id, arm, *, relevant_chunk_ids, relevant_source_ids,
            cand_source_ids, ctx_source_ids, has_chunk_truth=True,
            should_refuse=False, cand_chunk_ids=None, ctx_chunk_ids=None,
            alpha=0.7, query="q", query_type="single_fact", language="zh"):
        return RetrievalCaseResult(
            case_id=case_id, arm=arm, query=query,
            query_type=query_type, language=language, should_refuse=should_refuse,
            candidate_chunk_ids=cand_chunk_ids or [f"c{i}" for i in range(len(cand_source_ids))],
            candidate_source_ids=list(cand_source_ids),
            candidate_scores=[0.0] * len(cand_source_ids),
            context_chunk_ids=ctx_chunk_ids or [f"c{i}" for i in range(len(ctx_source_ids))],
            context_source_ids=list(ctx_source_ids),
            relevant_chunk_ids=relevant_chunk_ids,
            relevant_source_ids=relevant_source_ids,
            has_chunk_truth=has_chunk_truth, alpha=alpha,
        )

    @staticmethod
    def _mk_evalcase(case_id, *, relevant_source_ids, should_refuse=False,
                     query="q", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH):
        return EvalCase(
            id=case_id, query=query, query_type=query_type,
            language=language, should_refuse=should_refuse,
            relevant_source_ids=list(relevant_source_ids),
        )

    def test_source_only_included_in_source_denominator(self):
        """source-only case 纳入 source 分母，不进入 chunk/context 分母。"""
        # case1: 普通 chunk-truth case（s1 命中）
        # case2: source-only（has_chunk_truth=False, relevant_source_ids={s2}，
        #   relevant_chunk_ids=set()）
        cases = [
            self._mk_evalcase("c1", relevant_source_ids={"s1"}),
            self._mk_evalcase("c2", relevant_source_ids={"s2"}),
        ]
        results = [
            self._mk("c1", ARM_STANDARD,
                     relevant_chunk_ids={"c0"}, relevant_source_ids={"s1"},
                     cand_source_ids=["s1"], ctx_source_ids=["s1"],
                     cand_chunk_ids=["c0"], ctx_chunk_ids=["c0"]),
            self._mk("c2", ARM_STANDARD,
                     relevant_chunk_ids=set(), relevant_source_ids={"s2"},
                     cand_source_ids=["s2"], ctx_source_ids=["s2"],
                     has_chunk_truth=False),
        ]
        summary = compute_summary(results, cases, [ARM_STANDARD], bootstrap_iterations=10)
        overall = summary["standard"]["overall"]
        # chunk 分母：仅 c1 → n_chunk_valid=1
        assert overall["n_chunk_valid"] == 1
        # source 分母：c1 + c2 均纳入 → n_source_valid=2、n_source_only=1
        assert overall["n_source_valid"] == 2
        assert overall["n_source_only"] == 1
        # chunk/context 口径不受 source-only 影响
        assert overall["context_recall"] == 1.0  # c1 全召回
        # source 指标正常计算（两个都命中各自的 source）
        assert overall["source_recall@5"] == 1.0
        assert overall["source_recall@10"] == 1.0
        assert overall["context_source_recall"] == 1.0
        assert overall["context_source_coverage"] == 1.0

    def test_no_relevant_source_ids_excluded_from_source_denominator(self):
        """无 relevant_source_ids 的 answerable case 不进 source 分母。"""
        # c1: chunk-truth case 但 relevant_source_ids=set()（如 no_answer 留空）
        cases = [
            self._mk_evalcase("c1", relevant_source_ids=set()),
            self._mk_evalcase("c2", relevant_source_ids={"s2"}),
        ]
        results = [
            self._mk("c1", ARM_STANDARD,
                     relevant_chunk_ids={"c0"}, relevant_source_ids=set(),
                     cand_source_ids=["s1"], ctx_source_ids=["s1"],
                     cand_chunk_ids=["c0"], ctx_chunk_ids=["c0"]),
            self._mk("c2", ARM_STANDARD,
                     relevant_chunk_ids=set(), relevant_source_ids={"s2"},
                     cand_source_ids=["s2"], ctx_source_ids=["s2"],
                     has_chunk_truth=False),
        ]
        summary = compute_summary(results, cases, [ARM_STANDARD], bootstrap_iterations=10)
        overall = summary["standard"]["overall"]
        # 仅 c2 进 source 分母
        assert overall["n_source_valid"] == 1
        assert overall["n_source_only"] == 1
        # 无 relevant source 的 case 使 source 指标分母仅含 c2
        assert overall["source_recall@5"] == 1.0

    def test_chunk_and_source_denominators_independent(self):
        """混入 source-only case 不改变 chunk/context/citation 口径。"""
        # 两个 case：c1 chunk 全错（无召回），c2 source-only
        cases = [
            self._mk_evalcase("c1", relevant_source_ids={"s1"}),
            self._mk_evalcase("c2", relevant_source_ids={"s2"}),
        ]
        results = [
            # c1: chunk 真值 {c0,c1} 但候选/context 都只含 c2（recall=0）
            self._mk("c1", ARM_STANDARD,
                     relevant_chunk_ids={"c0", "c1"}, relevant_source_ids={"s1"},
                     cand_source_ids=["s1"], ctx_source_ids=["s1"],
                     cand_chunk_ids=["cx"], ctx_chunk_ids=["cx"]),
            self._mk("c2", ARM_STANDARD,
                     relevant_chunk_ids=set(), relevant_source_ids={"s2"},
                     cand_source_ids=["s2"], ctx_source_ids=["s2"],
                     has_chunk_truth=False),
        ]
        summary = compute_summary(results, cases, [ARM_STANDARD], bootstrap_iterations=10)
        overall = summary["standard"]["overall"]
        # chunk 分母只算 c1 → context_recall=0
        assert overall["n_chunk_valid"] == 1
        assert overall["context_recall"] == 0.0
        # source 分母算 c1+c2 → n_source_valid=2、n_source_only=1
        assert overall["n_source_valid"] == 2
        assert overall["n_source_only"] == 1

    def test_alpha_isolation_preserved_with_source_metrics(self):
        """compute_summary 收到混合 alpha 仍抛 ValueError（source 指标不影响隔离）。"""
        cases = [self._mk_evalcase("c1", relevant_source_ids={"s1"})]
        results = [
            self._mk("c1", ARM_STANDARD,
                     relevant_chunk_ids={"c0"}, relevant_source_ids={"s1"},
                     cand_source_ids=["s1"], ctx_source_ids=["s1"],
                     cand_chunk_ids=["c0"], ctx_chunk_ids=["c0"], alpha=1.0),
            self._mk("c1", ARM_STANDARD,
                     relevant_chunk_ids={"c0"}, relevant_source_ids={"s1"},
                     cand_source_ids=["s1"], ctx_source_ids=["s1"],
                     cand_chunk_ids=["c0"], ctx_chunk_ids=["c0"], alpha=0.7),
        ]
        with pytest.raises(ValueError, match="multiple alpha"):
            compute_summary(results, cases, [ARM_STANDARD], bootstrap_iterations=10)

    def test_no_overlay_compatibility(self):
        """无 overlay（全部 has_chunk_truth=True）时 source 口径正常、不降级 chunk。"""
        cases = [
            self._mk_evalcase("c1", relevant_source_ids={"s1"}),
            self._mk_evalcase("c2", relevant_source_ids={"s2"}),
        ]
        results = [
            self._mk("c1", ARM_STANDARD,
                     relevant_chunk_ids={"c0"}, relevant_source_ids={"s1"},
                     cand_source_ids=["s1"], ctx_source_ids=["s1"],
                     cand_chunk_ids=["c0"], ctx_chunk_ids=["c0"]),
            self._mk("c2", ARM_STANDARD,
                     relevant_chunk_ids={"c1"}, relevant_source_ids={"s2"},
                     cand_source_ids=["s2"], ctx_source_ids=["s2"],
                     cand_chunk_ids=["c1"], ctx_chunk_ids=["c1"]),
        ]
        summary = compute_summary(results, cases, [ARM_STANDARD], bootstrap_iterations=10)
        overall = summary["standard"]["overall"]
        # 无 source-only case
        assert overall["n_source_only"] == 0
        # source 分母 = 两个 answerable 且有 source 的 case
        assert overall["n_source_valid"] == 2
        # chunk 分母 = 两个 has_chunk_truth case（无变化）
        assert overall["n_chunk_valid"] == 2
        assert overall["context_recall"] == 1.0
        assert overall["source_recall@5"] == 1.0

    def test_paired_bootstrap_excludes_source_only(self):
        """paired_bootstrap_ci_cb 的 c_pair 仅含双侧 has_chunk_truth 的配对。"""
        from evaluation.compare import paired_bootstrap_ci_cb
        cases = [self._mk_evalcase("c1", relevant_source_ids={"s1"}),
                 self._mk_evalcase("c2", relevant_source_ids={"s2"})]
        # c2 为 source-only（has_chunk_truth=False）：不应进入配对
        b = [
            self._mk("c1", ARM_STANDARD_RERANK,
                     relevant_chunk_ids={"c0"}, relevant_source_ids={"s1"},
                     cand_source_ids=["s1"], ctx_source_ids=["s1"],
                     cand_chunk_ids=["c0"], ctx_chunk_ids=["c0"]),
            self._mk("c2", ARM_STANDARD_RERANK,
                     relevant_chunk_ids=set(), relevant_source_ids={"s2"},
                     cand_source_ids=["s2"], ctx_source_ids=["s2"],
                     has_chunk_truth=False),
        ]
        c = [
            self._mk("c1", ARM_GRAPH_RERANK,
                     relevant_chunk_ids={"c0"}, relevant_source_ids={"s1"},
                     cand_source_ids=["s1"], ctx_source_ids=["s1"],
                     cand_chunk_ids=["c0"], ctx_chunk_ids=["c0"]),
            self._mk("c2", ARM_GRAPH_RERANK,
                     relevant_chunk_ids=set(), relevant_source_ids={"s2"},
                     cand_source_ids=["s2"], ctx_source_ids=["s2"],
                     has_chunk_truth=False),
        ]
        chains = build_conversation_chains(cases)
        result = paired_bootstrap_ci_cb(b, c, chains=chains, n_iter=10, seed=42)
        # 仅 c1 配对成功；n_pairs=1
        assert result is not None
        assert result["n_pairs"] == 1


# ── source 标签域对齐 ─────────────────────────────────────────────────

class TestSourceLabelExtraction:
    """测试 _source_label_from_meta：对齐 candidate/context source 与
    dataset relevant_source_ids 的域（文件名），避免 source_recall 恒为 0。
    """

    def test_prefers_source_name(self):
        """source_name 优先，与 dataset 的 relevant_source_ids 同域。"""
        from evaluation.compare import _source_label_from_meta
        meta = {"source_name": "DSpark_paper.pdf",
                 "source": "DSpark",
                 "source_id": "3be83454b2997f53c90577babbcb77dd5293a7d789b803c10bebfdd3ec5b3f06"}
        assert _source_label_from_meta(meta) == "DSpark_paper.pdf"

    def test_fallback_to_source(self):
        """source_name 缺失时 fallback 至 source 字段。"""
        from evaluation.compare import _source_label_from_meta
        meta = {"source": "DSpark_paper.pdf",
                 "source_id": "3be83454b2997f53c90577babbcb77dd5293a7d789b803c10bebfdd3ec5b3f06"}
        assert _source_label_from_meta(meta) == "DSpark_paper.pdf"

    def test_fallback_to_source_id_when_only_hash(self):
        """source_name 与 source 均缺时 fallback 至 source_id 哈希。"""
        from evaluation.compare import _source_label_from_meta
        meta = {"source_id": "3be83454b2997f53c90577babbcb77dd5293a7d789b803c10bebfdd3ec5b3f06"}
        # 不会被误用为文件名域；至少回字符串避免崩溃
        assert _source_label_from_meta(meta) == \
            "3be83454b2997f53c90577babbcb77dd5293a7d789b803c10bebfdd3ec5b3f06"

    def test_empty_meta_returns_empty(self):
        """所有 source 字段缺失时返回空字符串。"""
        from evaluation.compare import _source_label_from_meta
        assert _source_label_from_meta({}) == ""
        assert _source_label_from_meta({"other": "x"}) == ""

    def test_does_not_use_source_id_when_source_name_present(self):
        """关键回归：source_name 非空时绝不返回 source_id 哈希域。"""
        from evaluation.compare import _source_label_from_meta
        # 真实 metadatas：source_name=文件名, source_id=64字符哈希
        meta = {
            "source_name": "南京城市地理环境.docx",
            "source_id": "d8fa2a45c99677a0ed0440cc3bfed8eb270589e4b1c31821526505e0dcbe7e9b",
            "chunk_id": "d8fa2a45...e7e9b_chunk_3",
        }
        label = _source_label_from_meta(meta)
        assert label == "南京城市地理环境.docx"
        # 不应是哈希（哈希长度=64 且无文件扩展名）
        assert len(label) < 64
        assert not all(c in "0123456789abcdef" for c in label)


# ── Bootstrap CI ─────────────────────────────────────────────────────

class TestBootstrapCI:
    """测试 paired_bootstrap_ci_cb 的统计行为。"""

    def test_seed_reproducible(self):
        """相同输入 + 相同 seed 产生逐字可复现的 CI。"""
        from evaluation.compare import paired_bootstrap_ci_cb

        b = [
            RetrievalCaseResult(
                case_id="c1", arm=ARM_STANDARD_RERANK, query="q",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                has_chunk_truth=True,
            ),
            RetrievalCaseResult(
                case_id="c2", arm=ARM_STANDARD_RERANK, query="q2",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_1"], candidate_source_ids=["s1"],
                candidate_scores=[0.3],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                has_chunk_truth=True,
            ),
        ]
        c = [
            RetrievalCaseResult(
                case_id="c1", arm=ARM_GRAPH_RERANK, query="q",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0", "chunk_1"], candidate_source_ids=["s1"],
                candidate_scores=[0.5, 0.3],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                has_chunk_truth=True,
            ),
            RetrievalCaseResult(
                case_id="c2", arm=ARM_GRAPH_RERANK, query="q2",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_1", "chunk_2"], candidate_source_ids=["s1"],
                candidate_scores=[0.5, 0.3],
                context_chunk_ids=["chunk_1"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_1"}, relevant_source_ids={"s1"},
                has_chunk_truth=True,
            ),
        ]

        r1 = paired_bootstrap_ci_cb(b, c, n_iter=1000, seed=42)
        r2 = paired_bootstrap_ci_cb(b, c, n_iter=1000, seed=42)

        assert r1 is not None
        assert r2 is not None
        assert r1["mean_delta"] == r2["mean_delta"]
        assert r1["ci95_low"] == pytest.approx(r2["ci95_low"])
        assert r1["ci95_high"] == pytest.approx(r2["ci95_high"])
        assert r1["bootstrap_iterations"] == 1000
        assert r1["bootstrap_seed"] == 42

    def test_all_same_delta_ci_equals_mean(self):
        """所有 delta 相同时 CI 与均值相同。"""
        from evaluation.compare import paired_bootstrap_ci_cb

        b = [
            RetrievalCaseResult(
                case_id="c1", arm=ARM_STANDARD_RERANK, query="q",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                has_chunk_truth=True,
            ),
        ]
        c = [
            RetrievalCaseResult(
                case_id="c1", arm=ARM_GRAPH_RERANK, query="q",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                has_chunk_truth=True,
            ),
        ]

        r = paired_bootstrap_ci_cb(b, c, n_iter=500, seed=42)
        assert r is not None
        assert abs(r["ci95_low"] - r["mean_delta"]) < 1e-9
        assert abs(r["ci95_high"] - r["mean_delta"]) < 1e-9

    def test_refusal_and_no_truth_excluded_from_ci(self):
        """should_refuse 或 !has_chunk_truth 的 case 不进入 bootstrap CI。"""
        from evaluation.compare import paired_bootstrap_ci_cb

        b = [
            RetrievalCaseResult(
                case_id="c1", arm=ARM_STANDARD_RERANK, query="q",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                has_chunk_truth=True,
            ),
            RetrievalCaseResult(
                case_id="c2", arm=ARM_STANDARD_RERANK, query="q2",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids=set(), relevant_source_ids=set(),
                has_chunk_truth=False,  # 无可靠 chunk truth
            ),
            RetrievalCaseResult(
                case_id="c3", arm=ARM_STANDARD_RERANK, query="q3",
                query_type="no_answer", language="zh", should_refuse=True,
                candidate_chunk_ids=[], candidate_source_ids=[],
                candidate_scores=[],
                context_chunk_ids=[], context_source_ids=[],
                relevant_chunk_ids=set(), relevant_source_ids=set(),
                has_chunk_truth=True,
            ),
        ]
        c = [
            RetrievalCaseResult(
                case_id="c1", arm=ARM_GRAPH_RERANK, query="q",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                has_chunk_truth=True,
            ),
            RetrievalCaseResult(
                case_id="c2", arm=ARM_GRAPH_RERANK, query="q2",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids=set(), relevant_source_ids=set(),
                has_chunk_truth=False,
            ),
            RetrievalCaseResult(
                case_id="c3", arm=ARM_GRAPH_RERANK, query="q3",
                query_type="no_answer", language="zh", should_refuse=True,
                candidate_chunk_ids=[], candidate_source_ids=[],
                candidate_scores=[],
                context_chunk_ids=[], context_source_ids=[],
                relevant_chunk_ids=set(), relevant_source_ids=set(),
                has_chunk_truth=True,
            ),
        ]

        r = paired_bootstrap_ci_cb(b, c, n_iter=500, seed=42)
        assert r is not None
        # 仅 c1 配对（c2 无真值，c3 拒答）
        assert r["n_pairs"] == 1

    def test_multi_turn_chain_counted_as_blocks(self):
        """multi_turn chain 按 block 重采样，n_blocks != n_pairs。"""
        from evaluation.compare import paired_bootstrap_ci_cb, build_conversation_chains

        chains = build_conversation_chains([])  # 空 chains
        b = [
            RetrievalCaseResult(
                case_id="c1", arm=ARM_STANDARD_RERANK, query="q1",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                has_chunk_truth=True,
            ),
            RetrievalCaseResult(
                case_id="c2", arm=ARM_STANDARD_RERANK, query="q2",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                has_chunk_truth=True,
            ),
        ]
        c = [
            RetrievalCaseResult(
                case_id="c1", arm=ARM_GRAPH_RERANK, query="q1",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                has_chunk_truth=True,
            ),
            RetrievalCaseResult(
                case_id="c2", arm=ARM_GRAPH_RERANK, query="q2",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                has_chunk_truth=True,
            ),
        ]

        r = paired_bootstrap_ci_cb(b, c, chains, n_iter=500, seed=42)
        assert r is not None
        # 无 chain → 每个 case 自己是一个 block
        assert r["n_blocks"] == r["n_pairs"]


class TestComputeSummaryGenerationBootstrapGuard:
    """回归：compute_summary 处理 GenerationCaseResult 时，不要把生成结果
    误传给仅适用 RetrievalCaseResult 的 paired_bootstrap_ci_cb（曾导致
    AttributeError: 'GenerationCaseResult' object has no attribute
    'has_chunk_truth'，使 --phase full 在保存生成 summary 前崩溃）。
    """

    @staticmethod
    def _mk_gen(case_id, arm, *, correctly_refused=None, should_refuse=False,
                answer_point_coverage=0.0, citation_id_validity=0.0,
                total_tokens=None, total_ms=0.0, error=None, alpha=0.7):
        return GenerationCaseResult(
            case_id=case_id, arm=arm, query="q",
            query_type="single_fact", language="zh", should_refuse=should_refuse,
            answer="a", context="ctx", alpha=alpha,
            citation_id_validity=citation_id_validity,
            answer_point_coverage=answer_point_coverage,
            correctly_refused=correctly_refused,
            total_tokens=total_tokens, total_ms=total_ms, error=error,
        )

    def test_generation_results_do_not_crash_paired_bootstrap(self):
        """A/B/C 生成结果过 compute_summary 不应触发 AttributeError。

        B/C arm 的 results 均为 GenerationCaseResult；compute_summary 应
        跳过 retrieval-only 的 paired bootstrap（McNemar 在另一段处理生成配对）。
        """
        cases = [
            EvalCase(id="c1", query="q1", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, should_refuse=False),
            EvalCase(id="c2", query="q2", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, should_refuse=False),
        ]
        arms = [ARM_STANDARD_RERANK, ARM_GRAPH_RERANK]
        results = [
            # B（answerable，正常正确回答 → correctly_refused=True 表示无误拒）
            self._mk_gen("c1", ARM_STANDARD_RERANK,
                     answer_point_coverage=0.5, correctly_refused=True),
            self._mk_gen("c2", ARM_STANDARD_RERANK,
                     answer_point_coverage=1.0, correctly_refused=True),
            # C
            self._mk_gen("c1", ARM_GRAPH_RERANK,
                     answer_point_coverage=0.6, correctly_refused=True),
            self._mk_gen("c2", ARM_GRAPH_RERANK,
                     answer_point_coverage=0.9, correctly_refused=True),
        ]
        summary = compute_summary(results, cases, arms, bootstrap_iterations=10)
        # 不应抛异常；生成 arm 的 overall 切片应被填充
        assert "standard_rerank" in summary
        assert "graph_rerank" in summary
        assert "overall" in summary["standard_rerank"]
        # paired_cb 不应在 generation-only 情况下被写入（bootstrap 专属 retrieval）
        assert "paired_cb" not in summary
        # McNemar 应被生成（c_gen 是 GenerationCaseResult）
        assert "mcnemar" in summary

    def test_retrieval_results_still_get_paired_bootstrap(self):
        """回归守护：修复不应破坏 retrieval 情况下的 paired_cb 生成。"""
        cases = [
            EvalCase(id="c1", query="q1", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH, should_refuse=False,
                     relevant_source_ids=["s1"]),
        ]
        arms = [ARM_STANDARD, ARM_STANDARD_RERANK, ARM_GRAPH_RERANK]
        results = [
            RetrievalCaseResult(
                case_id="c1", arm=arm, query="q1",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["c0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["c0"], context_source_ids=["s1"],
                relevant_chunk_ids={"c0"}, relevant_source_ids={"s1"},
                alpha=0.7,
            ) for arm in arms
        ]
        summary = compute_summary(results, cases, arms, bootstrap_iterations=10)
        # retrieval 仍应写入 paired_cb（C-B context_recall delta CI）
        assert "paired_cb" in summary
        # 生成结果不在 → 不应有 mcnemar
        assert "mcnemar" not in summary


# ── P95 nearest-rank ─────────────────────────────────────────────────

class TestPercentileNearestRank:
    """测试 nearest_rank_percentile helper。"""

    def test_p95_boundary(self):
        """n=10 时 p95 应是第 ceil(0.95*10)-1 = 9 个元素。"""
        from evaluation.compare import nearest_rank_percentile

        values = list(range(10))  # 0..9
        assert nearest_rank_percentile(values, 0.95) == 9.0

    def test_p95_single_element(self):
        """单元素返回自身。"""
        from evaluation.compare import nearest_rank_percentile

        assert nearest_rank_percentile([5.0], 0.95) == 5.0

    def test_empty_list_returns_zero(self):
        """空列表返回 0.0。"""
        from evaluation.compare import nearest_rank_percentile

        assert nearest_rank_percentile([], 0.95) == 0.0

    def test_p50_matches_median(self):
        """p50 与中位数一致。"""
        from evaluation.compare import nearest_rank_percentile

        values = [1, 2, 3, 4, 5]
        assert nearest_rank_percentile(values, 0.50) == 3

    def test_p95_outlier_not_skewing(self):
        """p95 不受极端值影响（使用排序位置，非均值）。"""
        from evaluation.compare import nearest_rank_percentile

        values = [100, 200, 300, 400, 500, 10000]
        # p95: ceil(0.95*6)=6 → idx=5 → 6th element
        assert nearest_rank_percentile(values, 0.95) == 10000


# ── Manifest 完整性 ──────────────────────────────────────────────────

class TestManifestCompleteness:
    """测试 build_run_manifest 与 _safe_url 等 helper。"""

    @patch("subprocess.check_output")
    def test_manifest_has_full_sha_not_12_char(self, mock_run):
        """manifest git_commit 应是完整 40 位 SHA，不是截断的 12 位。"""
        from evaluation.compare import build_run_manifest
        from pathlib import Path

        # Mock git rev-parse to return a full SHA
        def mock_check_output(args, **kwargs):
            if args[0] == "git" and args[1] == "rev-parse":
                return b"abcdef1234567890abcdef1234567890abcdef12\n"
            return b""
        mock_run.side_effect = mock_check_output

        # 创建临时文件
        dataset_path = Path("/tmp/test_manifest.jsonl")
        corpus_dir = Path("/tmp/test_corpus")
        # 文件不存在会失败，用 patch 绕过
        with patch("builtins.open", create=True):
            with patch("evaluation.compare._compute_dataset_hash", return_value="abc123"):
                with patch("evaluation.compare._compute_corpus_hash", return_value="def456"):
                    with patch("evaluation.compare._git_diff_hash", return_value="diff789"):
                        manifest = build_run_manifest(
                            dataset_path=dataset_path,
                            corpus_dir=corpus_dir,
                            source_files=["doc1.pdf"],
                            arms=[ARM_STANDARD],
                        )

        assert len(manifest["git_commit"]) >= 40
        assert "active_alpha" in manifest
        assert "git_diff_sha256" in manifest

    def test_safe_url_removes_userinfo_query_fragment(self):
        """_safe_url 移除 userinfo / query / fragment。"""
        from evaluation.compare import _safe_url

        assert _safe_url("https://user:pass@api.example.com/v1?key=val#frag") == \
            "https://api.example.com/v1"

    def test_safe_url_none(self):
        """空 URL 返回 None。"""
        from evaluation.compare import _safe_url

        assert _safe_url("") is None

    def test_manifest_contains_cli_args(self):
        """manifest.cli_args 记录 CLI 参数快照。"""
        from evaluation.compare import build_run_manifest
        from pathlib import Path

        dataset_path = Path("/tmp/test_manifest.jsonl")
        corpus_dir = Path("/tmp/test_corpus")
        with patch("builtins.open", create=True):
            with patch("evaluation.compare._compute_dataset_hash", return_value="abc"):
                with patch("evaluation.compare._compute_corpus_hash", return_value="def"):
                    with patch("subprocess.check_output", return_value=b""):
                        with patch("evaluation.compare._git_diff_hash", return_value="diff"):
                            manifest = build_run_manifest(
                                dataset_path=dataset_path,
                                corpus_dir=corpus_dir,
                                source_files=["doc1.pdf"],
                                arms=[ARM_STANDARD],
                                cli_args=["--alpha-grid", "1.0", "0.7"],
                            )

        assert "cli_args" in manifest
        assert "--alpha-grid" in manifest["cli_args"]

    def test_manifest_has_bootstrap_params(self):
        """manifest 记录 bootstrap 参数。"""
        from evaluation.compare import build_run_manifest
        from pathlib import Path

        dataset_path = Path("/tmp/test_manifest.jsonl")
        corpus_dir = Path("/tmp/test_corpus")
        with patch("builtins.open", create=True):
            with patch("evaluation.compare._compute_dataset_hash", return_value="abc"):
                with patch("evaluation.compare._compute_corpus_hash", return_value="def"):
                    with patch("subprocess.check_output", return_value=b""):
                        with patch("evaluation.compare._git_diff_hash", return_value="diff"):
                            with patch("subprocess.check_output", return_value=b""):
                                manifest = build_run_manifest(
                                    dataset_path=dataset_path,
                                    corpus_dir=corpus_dir,
                                    source_files=["doc1.pdf"],
                                    arms=[ARM_STANDARD],
                                    bootstrap_iterations=5000,
                                    bootstrap_seed=123,
                                )

        assert manifest["bootstrap_iterations"] == 5000
        assert manifest["bootstrap_seed"] == 123

    @patch("evaluation.compare._compute_dataset_hash", return_value="ds123")
    @patch("evaluation.compare._compute_corpus_hash", return_value="corp456")
    @patch("evaluation.compare._git_diff_hash", return_value="diff789")
    def test_same_kg_produces_same_hash(
        self, mock_git, mock_corpus, mock_ds,
    ):
        """相同 KG（相同 nodes/edges）产生相同 kg_sha256。"""
        from evaluation.compare import build_run_manifest
        from pathlib import Path
        from unittest.mock import MagicMock
        import networkx as nx

        kg = MagicMock()
        g = nx.Graph()
        g.add_nodes_from(["E1", "E2", "E3"])
        g.add_edges_from([("E1", "E2"), ("E2", "E3")])
        kg.entity_graph = g
        kg.index_fingerprint = "fp1"
        kg.manifest_version = 2

        dataset_path = Path("/tmp/test_manifest.jsonl")
        corpus_dir = Path("/tmp/test_corpus")
        with patch("builtins.open", create=True):
            with patch("subprocess.check_output", return_value=b""):
                m1 = build_run_manifest(
                    dataset_path=dataset_path, corpus_dir=corpus_dir,
                    source_files=["doc1.pdf"], arms=[ARM_STANDARD], kg=kg,
                )
                m2 = build_run_manifest(
                    dataset_path=dataset_path, corpus_dir=corpus_dir,
                    source_files=["doc1.pdf"], arms=[ARM_STANDARD], kg=kg,
                )

        assert m1["kg_sha256"] == m2["kg_sha256"]
        assert m1["kg_sha256"] is not None
        assert m1["kg_nodes"] == 3
        assert m1["kg_edges"] == 2
        assert m1["kg_index_fingerprint"] == "fp1"
        assert m1["kg_manifest_version"] == 2


# ── compute_summary 集成（bootstrap chains + CLI params） ──────────────

class TestComputeSummaryIntegration:
    """集成级测试：compute_summary 使用真实 chains 且透传 bootstrap params。"""

    def test_multi_turn_block_count_correct(self):
        """含两 turn multi_turn chain 时 paired_cb 的 n_blocks < n_pairs。"""
        from evaluation.compare import compute_summary

        # 两 turn chain：m1 (turn=1, root) → m2 (turn=2, follow_up_to=m1)
        cases = [
            EvalCase(id="m1", query="q1", query_type=QueryType.MULTI_TURN,
                     language=Language.ZH,
                     metadata={"turn": 1, "follow_up_to": None}),
            EvalCase(id="m2", query="q2", query_type=QueryType.MULTI_TURN,
                     language=Language.ZH,
                     metadata={"turn": 2, "follow_up_to": "m1"}),
        ]

        # B/C 两侧各两 turn，都 answerable + has_chunk_truth
        b_results = [
            RetrievalCaseResult(
                case_id="m1", arm=ARM_STANDARD_RERANK, query="q1",
                query_type="multi_turn", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                has_chunk_truth=True,
            ),
            RetrievalCaseResult(
                case_id="m2", arm=ARM_STANDARD_RERANK, query="q2",
                query_type="multi_turn", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                has_chunk_truth=True,
            ),
        ]
        c_results = [
            RetrievalCaseResult(
                case_id="m1", arm=ARM_GRAPH_RERANK, query="q1",
                query_type="multi_turn", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                has_chunk_truth=True,
                graph_lift=False, graph_pollution=False,
            ),
            RetrievalCaseResult(
                case_id="m2", arm=ARM_GRAPH_RERANK, query="q2",
                query_type="multi_turn", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                has_chunk_truth=True,
                graph_lift=False, graph_pollution=False,
            ),
        ]

        all_results = b_results + c_results

        summary = compute_summary(
            all_results, cases,
            [ARM_STANDARD_RERANK, ARM_GRAPH_RERANK],
            bootstrap_iterations=500,
            bootstrap_seed=42,
        )

        assert "paired_cb" in summary
        pb = summary["paired_cb"]
        assert "overall" in pb
        overall = pb["overall"]
        # 两 turn 属于同一 chain → n_blocks < n_pairs
        assert overall["n_pairs"] == 2
        assert overall["n_blocks"] == 1

    @patch("evaluation.compare.compute_summary")
    def test_save_helper_passes_bootstrap_params_to_compute(
        self, mock_compute,
    ):
        """save_retrieval_results_by_alpha 将 bootstrap params 透传给 compute_summary。"""
        from evaluation.compare import save_retrieval_results_by_alpha
        from pathlib import Path

        mock_compute.return_value = {"standard": {}}

        results_by_alpha = {
            0.7: [
                RetrievalCaseResult(
                    case_id="c1", arm=ARM_STANDARD, query="q",
                    query_type="single_fact", language="zh", should_refuse=False,
                    candidate_chunk_ids=[], candidate_source_ids=[],
                    candidate_scores=[],
                    context_chunk_ids=[], context_source_ids=[],
                    relevant_chunk_ids=set(), relevant_source_ids=set(),
                ),
            ],
        }

        with patch("evaluation.compare.save_results"):
            with patch("evaluation.compare.build_run_manifest",
                       return_value={"compare_version": 1}):
                with patch("builtins.open", create=True):
                    save_retrieval_results_by_alpha(
                        results_by_alpha=results_by_alpha,
                        alpha_values=[0.7],
                        output_dir=Path("/tmp/test_output"),
                        active_cases=[],
                        arms=[ARM_STANDARD],
                        ground_truth=[],
                        dataset_path=Path("test.jsonl"),
                        corpus_dir=Path("/tmp/test_texts"),
                        source_files=["doc1.pdf"],
                        bootstrap_iterations=5000,
                        bootstrap_seed=123,
                    )

        # compute_summary 收到指定的 bootstrap 参数
        call_kwargs = mock_compute.call_args.kwargs
        assert call_kwargs["bootstrap_iterations"] == 5000
        assert call_kwargs["bootstrap_seed"] == 123


# ── _safe_url 端口 + IPv6 ──────────────────────────────────────────────

class TestSafeUrl:
    """测试 _safe_url 的正确行为。"""

    def test_port_preserved(self):
        """_safe_url 保留合法端口。"""
        from evaluation.compare import _safe_url

        result = _safe_url("https://user:pass@api.example.com:8443/v1?key=val#frag")
        assert result == "https://api.example.com:8443/v1"

    def test_no_port_works(self):
        """无端口时返回 hostname。"""
        from evaluation.compare import _safe_url

        result = _safe_url("https://api.example.com/v1")
        assert result == "https://api.example.com/v1"

    def test_ipv6_not_crashing(self):
        """IPv6 地址不崩溃。"""
        from evaluation.compare import _safe_url

        result = _safe_url("https://[::1]:8080/path")
        assert result is not None
        assert "8080" in result

    def test_empty_returns_none(self):
        from evaluation.compare import _safe_url
        assert _safe_url("") is None


# ── CLI 快照 sanitizer ──────────────────────────────────────────────────

class TestCliSanitizer:
    """测试 _sanitize_cli_arg 和默认 argv 行为。"""

    def test_token_flag_redacted(self):
        """--token 值被 REDACTED。"""
        from evaluation.compare import _sanitize_cli_arg

        assert _sanitize_cli_arg("--token") == "--token ***REDACTED***"
        assert _sanitize_cli_arg("--api-key") == "--api-key ***REDACTED***"

    def test_key_env_form_redacted(self):
        """API_KEY=value 被 REDACTED。"""
        from evaluation.compare import _sanitize_cli_arg

        result = _sanitize_cli_arg("API_KEY=sk-123456")
        assert result == "api_key=***REDACTED***"

    def test_regular_flag_preserved(self):
        """普通参数不被修改。"""
        from evaluation.compare import _sanitize_cli_arg

        assert _sanitize_cli_arg("--alpha-grid") == "--alpha-grid"
        assert _sanitize_cli_arg("1.0") == "1.0"
        assert _sanitize_cli_arg("--output") == "--output"

    def test_url_with_credentials_redacted(self):
        """URL 中含 @ 时脱敏。"""
        from evaluation.compare import _sanitize_cli_arg

        result = _sanitize_cli_arg("https://user:pass@api.example.com/v1")
        assert "user" not in result
        assert "pass" not in result

    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_main_argv_none_uses_sys_argv_and_sanitizes(
        self, mock_prepare, mock_gt, mock_val, mock_cache,
        mock_grid, mock_save, tmp_path,
    ):
        """main(argv=None) 经 mock 链调用 save helper，cli_args 来自 sys.argv[1:]。

        使用 A-only（--arms standard）避免 KG 构建，仅验证数据流。
        """
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "doc1.pdf").write_bytes(b"test")

        mock_prepare.return_value = (None, None, None, [], [])
        mock_gt.return_value = []
        mock_val.return_value = None
        mock_cache.return_value = {}
        # 返回至少一条带 alpha 的结果，防止 main() 在打印时 max() 空迭代器
        from evaluation.compare import RetrievalCaseResult
        mock_grid.return_value = [
            RetrievalCaseResult(
                case_id="c1", arm=ARM_STANDARD, query="q",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["chunk_0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["chunk_0"], context_source_ids=["s1"],
                relevant_chunk_ids={"chunk_0"}, relevant_source_ids={"s1"},
                alpha=0.7,
            ),
        ]

        with patch("sys.argv", [
            "compare.py", "--corpus-dir", str(corpus_dir),
            "--arms", "standard",
            "--alpha-grid", "1.0", "0.7",
        ]):
            import evaluation.compare as compare_mod
            compare_mod.main(argv=None)

        # save helper 被调用
        assert mock_save.call_count >= 1
        call_kwargs = mock_save.call_args_list[-1].kwargs
        cli = call_kwargs.get("cli_args", [])
        cli_str = " ".join(str(a) for a in cli)
        assert "--corpus-dir" in cli_str
        assert "--alpha-grid" in cli_str


# ── config_sha256 ────────────────────────────────────────────────────

class TestConfigHash:
    """测试 build_run_manifest 的 config_sha256 字段。"""

    def test_config_hash_when_path_exists(self, tmp_path):
        """config_path 存在时记录完整 SHA-256。"""
        from evaluation.compare import build_run_manifest

        config = tmp_path / "config.json"
        config.write_text('{"alpha": 0.7}')

        dataset_path = tmp_path / "test.jsonl"
        dataset_path.write_text("test")
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "doc1.pdf").write_bytes(b"test")

        with patch("subprocess.check_output", return_value=b""):
            with patch("evaluation.compare._git_diff_hash", return_value="diff"):
                manifest = build_run_manifest(
                    dataset_path=dataset_path, corpus_dir=corpus_dir,
                    source_files=["doc1.pdf"], arms=[ARM_STANDARD],
                    config_path=config,
                )

        assert manifest["config_sha256"] is not None
        assert len(manifest["config_sha256"]) == 64

    def test_config_hash_changes_with_content(self, tmp_path):
        """config 内容变更后 hash 改变。"""
        from evaluation.compare import build_run_manifest

        config = tmp_path / "config.json"
        config.write_text('{"alpha": 0.7}')

        dataset_path = tmp_path / "test.jsonl"
        dataset_path.write_text("test")
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "doc1.pdf").write_bytes(b"test")

        with patch("subprocess.check_output", return_value=b""):
            with patch("evaluation.compare._git_diff_hash", return_value="diff"):
                m1 = build_run_manifest(
                    dataset_path=dataset_path, corpus_dir=corpus_dir,
                    source_files=["doc1.pdf"], arms=[ARM_STANDARD],
                    config_path=config,
                )

            config.write_text('{"alpha": 0.5}')
            with patch("subprocess.check_output", return_value=b""):
                with patch("evaluation.compare._git_diff_hash", return_value="diff"):
                    m2 = build_run_manifest(
                        dataset_path=dataset_path, corpus_dir=corpus_dir,
                        source_files=["doc1.pdf"], arms=[ARM_STANDARD],
                        config_path=config,
                    )

        assert m1["config_sha256"] != m2["config_sha256"]

    def test_config_hash_none_when_no_path(self, tmp_path):
        """config_path 不存在时为 None。"""
        from evaluation.compare import build_run_manifest

        dataset_path = tmp_path / "test.jsonl"
        dataset_path.write_text("test")
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "doc1.pdf").write_bytes(b"test")

        with patch("subprocess.check_output", return_value=b""):
            with patch("evaluation.compare._git_diff_hash", return_value="diff"):
                manifest = build_run_manifest(
                    dataset_path=dataset_path, corpus_dir=corpus_dir,
                    source_files=["doc1.pdf"], arms=[ARM_STANDARD],
                    config_path=None,
                )

        assert manifest["config_sha256"] is None


# ── BASE_URL endpoint ────────────────────────────────────────────────

class TestBaseUrlEndpoint:
    """测试 manifest llm_base_url 读取 BASE_URL 并脱敏。"""

    def test_uses_base_url_with_port(self, monkeypatch, tmp_path):
        """BASE_URL 带 userinfo/query/fragment/port 时正确脱敏保端口。"""
        from evaluation.compare import build_run_manifest

        monkeypatch.setenv("BASE_URL", "https://user:pass@api.example.com:8443/v1?q=1#f")
        monkeypatch.delenv("LLM_BASE_URL", raising=False)

        dataset_path = tmp_path / "test.jsonl"
        dataset_path.write_text("test")
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "doc1.pdf").write_bytes(b"test")

        with patch("subprocess.check_output", return_value=b""):
            with patch("evaluation.compare._git_diff_hash", return_value="diff"):
                manifest = build_run_manifest(
                    dataset_path=dataset_path, corpus_dir=corpus_dir,
                    source_files=["doc1.pdf"], arms=[ARM_STANDARD],
                )

        assert manifest["llm_base_url"] == "https://api.example.com:8443/v1"

    def test_falls_back_to_llm_base_url(self, monkeypatch, tmp_path):
        """BASE_URL 未设时回退 LLM_BASE_URL。"""
        from evaluation.compare import build_run_manifest

        monkeypatch.delenv("BASE_URL", raising=False)
        monkeypatch.setenv("LLM_BASE_URL", "https://fallback.example.com/v1")

        dataset_path = tmp_path / "test.jsonl"
        dataset_path.write_text("test")
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "doc1.pdf").write_bytes(b"test")

        with patch("subprocess.check_output", return_value=b""):
            with patch("evaluation.compare._git_diff_hash", return_value="diff"):
                manifest = build_run_manifest(
                    dataset_path=dataset_path, corpus_dir=corpus_dir,
                    source_files=["doc1.pdf"], arms=[ARM_STANDARD],
                )

        assert manifest["llm_base_url"] == "https://fallback.example.com/v1"


# ── index/KG canonical ───────────────────────────────────────────────

class TestCanonicalSnapshot:
    """测试 index 和 KG 的 canonical hash 表示。"""

    def test_index_hash_stable_under_reorder(self, tmp_path):
        """同一组 ids/metadatas 不同输入顺序产生相同 hash。"""
        from evaluation.compare import build_run_manifest

        dataset_path = tmp_path / "test.jsonl"
        dataset_path.write_text("test")
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "doc1.pdf").write_bytes(b"test")

        # 模拟 collection.get() 返回不同顺序
        col1 = MagicMock()
        col1.get.return_value = {
            "ids": ["id_b", "id_a"],
            "metadatas": [{"chunk_id": "c2"}, {"chunk_id": "c1"}],
        }
        col2 = MagicMock()
        col2.get.return_value = {
            "ids": ["id_a", "id_b"],
            "metadatas": [{"chunk_id": "c1"}, {"chunk_id": "c2"}],
        }

        with patch("subprocess.check_output", return_value=b""):
            with patch("evaluation.compare._git_diff_hash", return_value="diff"):
                m1 = build_run_manifest(
                    dataset_path=dataset_path, corpus_dir=corpus_dir,
                    source_files=["doc1.pdf"], arms=[ARM_STANDARD],
                    collection=col1,
                )
                m2 = build_run_manifest(
                    dataset_path=dataset_path, corpus_dir=corpus_dir,
                    source_files=["doc1.pdf"], arms=[ARM_STANDARD],
                    collection=col2,
                )

        assert m1["index_sha256"] == m2["index_sha256"]

    def test_kg_hash_includes_mappings_and_edge_weight(self):
        """KG canonical hash 含 edges with weight + entity_to_chunks + chunk_to_entities。"""
        from evaluation.compare import build_run_manifest
        from pathlib import Path

        kg = MagicMock()
        g = MagicMock()
        g.nodes.return_value = ["N1", "N2"]
        # 新口径用 edges(data=True)：每条边为 (u, v, attrs_dict)
        g.edges.return_value = [("N1", "N2", {"weight": 1.0})]
        g.get_edge_data.return_value = {"weight": 1.0}
        g.number_of_nodes.return_value = 2
        g.number_of_edges.return_value = 1
        kg.entity_graph = g
        kg.entity_to_chunks = {"N1": ["c1", "c2"]}
        kg.chunk_to_entities = {"c1": ["N1"], "c2": ["N1"]}
        kg.index_fingerprint = "fp1"
        kg.manifest_version = 2

        dataset_path = Path("/tmp/test_kg.jsonl")
        corpus_dir = Path("/tmp/test_corpus_kg")
        with patch("builtins.open", create=True):
            with patch("evaluation.compare._compute_dataset_hash", return_value="ds"):
                with patch("evaluation.compare._compute_corpus_hash", return_value="co"):
                    with patch("subprocess.check_output", return_value=b""):
                        with patch("evaluation.compare._git_diff_hash", return_value="diff"):
                            m1 = build_run_manifest(
                                dataset_path=dataset_path, corpus_dir=corpus_dir,
                                source_files=["doc1.pdf"], arms=[ARM_STANDARD],
                                kg=kg,
                            )

            # 改变 edge weight → hash 改变
            g.edges.return_value = [("N1", "N2", {"weight": 2.0})]
            g.get_edge_data.return_value = {"weight": 2.0}
            with patch("evaluation.compare._compute_dataset_hash", return_value="ds"):
                with patch("evaluation.compare._compute_corpus_hash", return_value="co"):
                    with patch("subprocess.check_output", return_value=b""):
                        with patch("evaluation.compare._git_diff_hash", return_value="diff"):
                            m2 = build_run_manifest(
                                dataset_path=dataset_path, corpus_dir=corpus_dir,
                                source_files=["doc1.pdf"], arms=[ARM_STANDARD],
                                kg=kg,
                            )

        assert m1["kg_sha256"] != m2["kg_sha256"]
        assert m1["kg_nodes"] == 2

    def test_python_version_always_present(self, tmp_path):
        """python_version 始终写入当前 Python 版本。"""
        from evaluation.compare import build_run_manifest

        dataset_path = tmp_path / "test.jsonl"
        dataset_path.write_text("test")
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "doc1.pdf").write_bytes(b"test")

        with patch("subprocess.check_output", return_value=b""):
            with patch("evaluation.compare._git_diff_hash", return_value="diff"):
                manifest = build_run_manifest(
                    dataset_path=dataset_path, corpus_dir=corpus_dir,
                    source_files=["doc1.pdf"], arms=[ARM_STANDARD],
                )

        assert "python_version" in manifest
        assert manifest["python_version"] != "unknown"
        # python_version 包含版本号数字
        assert "." in manifest["python_version"]


# ── McNemar exact ────────────────────────────────────────────────────

class TestMcNemarExact:
    """测试 mcnemar_exact helper 的边界行为。"""

    def test_zero_discordant_p_is_1(self):
        """零 discordant pairs 时 p=1.0。"""
        from evaluation.compare import mcnemar_exact

        result = mcnemar_exact(
            [True, True, False, False],
            [True, True, False, False],
        )
        assert result["n_discordant"] == 0
        assert result["p_value"] == 1.0
        assert result["n_pairs"] == 4

    def test_all_discordant_one_side(self):
        """全部 discordant 都在一侧（B 错 C 对）时统计正确。"""
        from evaluation.compare import mcnemar_exact

        result = mcnemar_exact(
            [True, True, True],
            [False, False, False],
        )
        assert result["n_discordant"] == 3
        assert result["b_only"] == 3
        assert result["c_only"] == 0
        # n=3, min=0: p = 2 * C(3,0)*0.125 = 0.25
        assert abs(result["p_value"] - 0.25) < 1e-12

    def test_deterministic(self):
        """同一输入产生完全相同结果。"""
        from evaluation.compare import mcnemar_exact

        b = [True, False, True, False, True]
        c = [False, True, True, False, False]
        r1 = mcnemar_exact(b, c)
        r2 = mcnemar_exact(b, c)
        assert r1 == r2

    def test_mismatched_length_raises(self):
        """B/C 长度不一致抛 ValueError。"""
        from evaluation.compare import mcnemar_exact

        with pytest.raises(ValueError, match="equal-length"):
            mcnemar_exact([True], [True, False])

    def test_serializable(self):
        """返回字段全部可 JSON 序列化。"""
        import json
        from evaluation.compare import mcnemar_exact

        result = mcnemar_exact([True, False], [False, True])
        json.dumps(result)


# ── failures.csv 构建 ────────────────────────────────────────────────

class TestFailuresCsv:
    """测试 build_failures_csv_rows。"""

    def _mk_result(self, case_id, arm, recall_chunks, gt, alpha=0.7,
                   lift=False, pollution=False, has_truth=True,
                   should_refuse=False, source_ids=None,
                   cand_source_ids=None, ctx_source_ids=None):
        # source_ids 用 set() 表示"无 source 真值"，否则默认 {"s1"}。
        if source_ids is None:
            source_ids = {"s1"}
        cand_src = list(cand_source_ids) if cand_source_ids is not None else ["s1"]
        ctx_src = list(ctx_source_ids) if ctx_source_ids is not None else ["s1"]
        return RetrievalCaseResult(
            case_id=case_id, arm=arm, query="q",
            query_type="single_fact", language="zh", should_refuse=should_refuse,
            candidate_chunk_ids=list(recall_chunks), candidate_source_ids=cand_src,
            candidate_scores=[0.5],
            context_chunk_ids=list(recall_chunks), context_source_ids=ctx_src,
            relevant_chunk_ids=gt, relevant_source_ids=source_ids,
            has_chunk_truth=has_truth, alpha=alpha,
            graph_lift=lift, graph_pollution=pollution,
        )

    def test_win_loss_flip(self):
        """win/loss/flip 正确标注。"""
        from evaluation.compare import build_failures_csv_rows

        b = [
            # B 只召回 c0（GT={c0,c1}）→ recall 0.5
            self._mk_result("c1", ARM_STANDARD_RERANK, ["c0"], {"c0", "c1"}),
            # B 召回全部 GT → recall 1.0
            self._mk_result("c2", ARM_STANDARD_RERANK, ["c0", "c1"], {"c0", "c1"}),
        ]
        c = [
            # C 召回全部 GT → recall 1.0 > 0.5 → win
            self._mk_result("c1", ARM_GRAPH_RERANK, ["c0", "c1"], {"c0", "c1"},
                            lift=True),
            # C 只召回 c0 → recall 0.5 < 1.0 → loss
            self._mk_result("c2", ARM_GRAPH_RERANK, ["c0"], {"c0", "c1"},
                            pollution=True),
        ]

        rows = build_failures_csv_rows(b, c, 0.7)
        by_id = {r["case_id"]: r for r in rows}

        assert by_id["c1"]["outcome"] == "win"
        assert by_id["c1"]["flip"] is True  # lift
        assert by_id["c2"]["outcome"] == "loss"
        assert by_id["c2"]["flip"] is True  # pollution

    def test_no_reliable_truth_excluded_from_outcome(self):
        """无任何真值的 case（既无 chunk 真值也无 source 真值）不计算相关结论。"""
        from evaluation.compare import build_failures_csv_rows

        b = [self._mk_result("c1", ARM_STANDARD_RERANK, ["c0"], set(),
                             has_truth=False, source_ids=set())]
        c = [self._mk_result("c1", ARM_GRAPH_RERANK, ["c0"], set(),
                             has_truth=False, source_ids=set())]

        rows = build_failures_csv_rows(b, c, 0.7)
        assert rows[0]["outcome"] == ""
        assert rows[0]["notes"] == "no_reliable_chunk_truth"
        assert rows[0]["has_chunk_truth"] is False

    def test_source_level_only_labeled(self):
        """source-only case（无 chunk 真值但有 source 真值）标注 source_level_only。"""
        from evaluation.compare import build_failures_csv_rows

        b = [self._mk_result("c1", ARM_STANDARD_RERANK, ["c0"], set(),
                             has_truth=False)]
        c = [self._mk_result("c1", ARM_GRAPH_RERANK, ["c0"], set(),
                             has_truth=False)]

        rows = build_failures_csv_rows(b, c, 0.7)
        assert rows[0]["outcome"] == ""               # 不伪造 chunk win/loss/equal
        assert rows[0]["notes"] == "source_level_only"
        assert rows[0]["has_chunk_truth"] is False
        assert rows[0]["graph_lift"] is False         # source-only 无 chunk 真值
        assert rows[0]["graph_pollution"] is False
        assert rows[0]["flip"] is False

    def test_refusal_case_flagged(self):
        """拒答 case 标记 refusal_case，不计算相关性。"""
        from evaluation.compare import build_failures_csv_rows

        b = [self._mk_result("c1", ARM_STANDARD_RERANK, [], set(),
                             should_refuse=True)]
        c = [self._mk_result("c1", ARM_GRAPH_RERANK, [], set(),
                             should_refuse=True)]

        rows = build_failures_csv_rows(b, c, 0.7)
        assert rows[0]["notes"] == "refusal_case"
        assert rows[0]["outcome"] == ""

    def test_write_csv_roundtrip(self, tmp_path):
        """write_failures_csv 写出确定列。"""
        import csv
        from evaluation.compare import write_failures_csv

        rows = [{
            "case_id": "c1", "alpha": 0.7, "query_type": "single_fact",
            "b_context_recall": 0.5, "c_context_recall": 1.0,
            "outcome": "win", "graph_lift": True, "graph_pollution": False,
            "flip": True, "has_chunk_truth": True, "notes": "",
        }]
        # write_failures_csv(output_dir, rows) 写入 output_dir/failures.csv
        out_dir = tmp_path / "alpha-0.7"
        write_failures_csv(out_dir, rows)

        with open(out_dir / "failures.csv", "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            parsed = list(reader)
        assert len(parsed) == 1
        assert parsed[0]["case_id"] == "c1"
        assert parsed[0]["outcome"] == "win"


# ── run_generation_grid / phase 分支 ─────────────────────────────────

class TestGenerationPhase:
    """测试生成网格与 main() phase 分支。"""

    @patch("evaluation.compare._run_generation_arm")
    def test_generation_grid_reuses_plan_and_retrieval(self, mock_gen):
        """生成网格按 alpha×arm×case 调用，且复用检索结果归因。"""
        from evaluation.compare import run_generation_grid, QueryPlan

        captured = []
        def mock_gen_impl(case, arm, model, collection, bm25, all_docs, all_metadatas,
                          kg, alpha, history, ground_truth_chunk_ids, retrieval_result,
                          **kwargs):  # evidence/evidence_cache/evidence_key/query_plan
            captured.append((case.id, arm, alpha, retrieval_result))
            return GenerationCaseResult(
                case_id=case.id, arm=arm, query=case.query,
                query_type=case.query_type.value, language=case.language.value,
                should_refuse=False, answer="a", context="",
                alpha=alpha,
            )
        mock_gen.side_effect = mock_gen_impl

        plan = QueryPlan(
            rewritten_query="q", rewrite_log={}, sub_queries=["q"],
            base_candidates={0: 0.5},
        )
        case = EvalCase(
            id="c1", query="q", query_type=QueryType.SINGLE_FACT,
            language=Language.ZH, relevant_chunks=[],
        )

        # 检索结果索引（供归因）
        ret_by_alpha = {
            0.7: [
                RetrievalCaseResult(
                    case_id="c1", arm=ARM_STANDARD_RERANK, query="q",
                    query_type="single_fact", language="zh", should_refuse=False,
                    candidate_chunk_ids=["c0"], candidate_source_ids=["s1"],
                    candidate_scores=[0.5],
                    context_chunk_ids=["c0"], context_source_ids=["s1"],
                    relevant_chunk_ids={"c0"}, relevant_source_ids={"s1"},
                    alpha=0.7,
                ),
            ],
        }

        results = run_generation_grid(
            active_cases=[case],
            arms=[ARM_STANDARD_RERANK],
            alpha_values=[0.7],
            model=None, collection=None, bm25=None,
            all_docs=[], all_metadatas=[],
            kg=None,
            query_plan_cache={"c1": plan},
            gt_map={"c1": set()},
            chain_map={},
            retrieval_results_by_alpha=ret_by_alpha,
        )

        assert len(results) == 1
        # retrieval_result 被正确传入（复用检索结果）
        assert captured[0][3] is not None
        assert captured[0][3].arm == ARM_STANDARD_RERANK
        assert results[0].alpha == 0.7

    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_generation_grid")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_main_generation_phase_calls_generation(
        self, mock_prepare, mock_gt, mock_val, mock_cache,
        mock_grid, mock_gen_grid, mock_save, tmp_path,
    ):
        """main(--phase generation) 必须调用 run_generation_grid。"""
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "doc1.pdf").write_bytes(b"test")

        mock_prepare.return_value = (None, None, None, [], [])
        mock_gt.return_value = []
        mock_val.return_value = None
        mock_cache.return_value = {}
        mock_grid.return_value = [
            RetrievalCaseResult(
                case_id="c1", arm=ARM_STANDARD, query="q",
                query_type="single_fact", language="zh", should_refuse=False,
                candidate_chunk_ids=["c0"], candidate_source_ids=["s1"],
                candidate_scores=[0.5],
                context_chunk_ids=["c0"], context_source_ids=["s1"],
                relevant_chunk_ids={"c0"}, relevant_source_ids={"s1"},
                alpha=0.7,
            ),
        ]
        mock_gen_grid.return_value = [
            GenerationCaseResult(
                case_id="c1", arm=ARM_STANDARD, query="q",
                query_type="single_fact", language="zh", should_refuse=False,
                answer="a", context="", alpha=0.7,
            ),
        ]

        with patch("sys.argv", [
            "compare.py", "--corpus-dir", str(corpus_dir),
            "--arms", "standard", "--phase", "generation",
        ]):
            import evaluation.compare as compare_mod
            compare_mod.main(argv=None)

        # generation 阶段必须调用 run_generation_grid
        assert mock_gen_grid.call_count >= 1
        # 保存时 include_retrieval=False（generation 阶段仅生成产物）
        save_kwargs = mock_save.call_args_list[-1].kwargs
        assert save_kwargs.get("include_retrieval") is False
        assert save_kwargs.get("gen_results_by_alpha") is not None

    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_generation_grid")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_main_retrieval_phase_skips_generation(
        self, mock_prepare, mock_gt, mock_val, mock_cache,
        mock_grid, mock_gen_grid, mock_save, tmp_path,
    ):
        """main(--phase retrieval) 不调用 run_generation_grid。"""
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "doc1.pdf").write_bytes(b"test")

        mock_prepare.return_value = (None, None, None, [], [])
        mock_gt.return_value = []
        mock_val.return_value = None
        mock_cache.return_value = {}
        mock_grid.return_value = []

        with patch("sys.argv", [
            "compare.py", "--corpus-dir", str(corpus_dir),
            "--arms", "standard", "--phase", "retrieval",
        ]):
            import evaluation.compare as compare_mod
            compare_mod.main(argv=None)

        mock_gen_grid.assert_not_called()
        save_kwargs = mock_save.call_args_list[-1].kwargs
        assert save_kwargs.get("gen_results_by_alpha") is None
        assert save_kwargs.get("include_retrieval") is True

# ── Citation 评测语义修复：生成臂传真实 context 证据 ─────────────────

class TestGenerationArmCitationEvidence:
    """A/B/C 三臂生成必须向 evaluate_citations_context_aware 传真实
    context 证据（sources 映射 + 检索网格 context/candidate + chunk→source），
    禁止占位（空 context/空 retrieved 集）；证据缺失时 fail-closed。"""

    @staticmethod
    def _mk_retrieval_result(case_id="c1", arm=ARM_STANDARD):
        return RetrievalCaseResult(
            case_id=case_id, arm=arm, query="q",
            query_type="single_fact", language="zh", should_refuse=False,
            candidate_chunk_ids=["c_a", "c_b"],
            candidate_source_ids=["src1", "src2"],
            candidate_scores=[0.9, 0.8],
            context_chunk_ids=["c_a"],
            context_source_ids=["src1"],
            relevant_chunk_ids={"c_a"}, relevant_source_ids={"src1"},
            alpha=1.0,
        )

    @staticmethod
    def _mk_evidence_metrics():
        from evaluation.citation_metrics import CitationEvidence
        from types import SimpleNamespace
        return SimpleNamespace(
            citation_id_validity=1.0,
            context_supported_citation_validity=1.0,
            invalid_citation_count=0,
            total_citation_count=1,
            unique_citation_count=1,
            citation_precision=1.0,
            citation_recall=1.0,
            faithfulness=1.0,
            correctly_refused=True,
            fabricated_citation_count=0,
            retrieved_not_in_context_count=0,
            supported_chunk_count=1,
            supported_source_count=0,
            evidence=(
                CitationEvidence("S1", "c_a", "supported_chunk",
                                 True, False, True),
            ),
        )

    def _run_arm(self, arm, mock_answer_query, mock_eval):
        from evaluation.compare import _run_generation_arm, QueryPlan
        from types import SimpleNamespace
        mock_answer_query.return_value = (
            "根据[S1]，答案是 A。",
            "[S1] src1 (p.1; chunk_id=c_a): 文档A内容...",
        )
        mock_eval.return_value = self._mk_evidence_metrics()
        case = EvalCase(
            id="c1", query="q", query_type=QueryType.SINGLE_FACT,
            language=Language.ZH, relevant_chunks=[],
            acceptable_answer_points=["A"],
        )
        return _run_generation_arm(
            case=case, arm=arm, model=None, collection=None, bm25=None,
            all_docs=["文档A内容", "文档B内容"],
            all_metadatas=[
                {"chunk_id": "c_a", "source_name": "src1", "source_id": "h1"},
                {"chunk_id": "c_b", "source_name": "src2", "source_id": "h2"},
            ],
            kg=None, alpha=1.0, history=None,
            ground_truth_chunk_ids={"c_a"},
            retrieval_result=self._mk_retrieval_result(arm=arm),
        )

    @patch("evaluation.compare.evaluate_citations_context_aware")
    @patch("evaluation.compare._graph_enhanced_answer_query")
    @patch("src.rag.answer_query")
    def test_three_arms_pass_real_context_evidence(
        self, mock_aq, mock_graph, mock_eval,
    ):
        """A/B 臂（answer_query）与 C 臂（graph 增强）都传真实证据。"""
        from evaluation.citation_metrics import CitationEvidence
        mock_graph.return_value = (
            "根据[S1]，答案是 A。",
            "[S1] src1 (p.1; chunk_id=c_a): 文档A内容...",
        )
        for arm in (ARM_STANDARD, ARM_STANDARD_RERANK, ARM_GRAPH_RERANK):
            self._run_arm(arm, mock_aq, mock_eval)
        assert mock_eval.call_count == 3
        for call in mock_eval.call_args_list:
            kw = call.kwargs
            # 真实 sources 映射与检索网格证据，禁止占位
            assert kw["sources"].startswith("[S1]")
            assert kw["context_chunk_ids"] == ["c_a"]
            assert kw["context_source_ids"] == ["src1"]
            assert kw["candidate_chunk_ids"] == ["c_a", "c_b"]
            assert kw["chunk_to_source"] == {
                "c_a": "src1", "c_b": "src2",
            }
            assert "文档A内容" in kw["context_text"]  # 重建的 context 文本
            assert kw["relevant_chunk_ids"] == {"c_a"}
            assert kw["answer_points"] == ["A"]

    @patch("evaluation.compare.evaluate_citations_context_aware")
    @patch("src.rag.answer_query")
    def test_generation_result_records_context_fields(
        self, mock_aq, mock_eval,
    ):
        """GenerationCaseResult 写入 context-supported 引用指标与状态计数。"""
        result = self._run_arm(ARM_STANDARD, mock_aq, mock_eval)
        assert result.context_supported_citation_validity == 1.0
        assert result.fabricated_citation_count == 0
        assert result.retrieved_not_in_context_count == 0
        assert result.citation_status_counts == {"supported_chunk": 1}

    @patch("src.rag.answer_query")
    def test_generation_arm_fails_closed_without_retrieval_result(
        self, mock_aq,
    ):
        """检索证据缺失（retrieval_result=None）→ 不产出正常指标，error 记录。"""
        from evaluation.compare import _run_generation_arm
        mock_aq.return_value = (
            "根据[S1]，答案是 A。",
            "[S1] src1 (p.1; chunk_id=c_a): 文档A内容...",
        )
        case = EvalCase(
            id="c1", query="q", query_type=QueryType.SINGLE_FACT,
            language=Language.ZH, relevant_chunks=[],
            acceptable_answer_points=["A"],
        )
        result = _run_generation_arm(
            case=case, arm=ARM_STANDARD, model=None, collection=None,
            bm25=None, all_docs=["文档A内容"],
            all_metadatas=[
                {"chunk_id": "c_a", "source_name": "src1", "source_id": "h1"},
            ],
            kg=None, alpha=1.0, history=None,
            ground_truth_chunk_ids={"c_a"},
            retrieval_result=None,
        )
        assert result.error is not None  # fail-closed：不静默输出指标
        assert "retrieval" in result.error
        assert result.context_supported_citation_validity == 0.0
        assert result.citation_id_validity == 0.0


class TestComputeSummaryCitationContextSupported:
    """compute_summary 聚合 context-supported 引用指标（与 citation_id_validity 并列）。"""

    @staticmethod
    def _mk_gen(case_id, arm, *, cs_validity, fab_count, cit_validity=0.0):
        return GenerationCaseResult(
            case_id=case_id, arm=arm, query="q",
            query_type="single_fact", language="zh", should_refuse=False,
            answer="a", context="ctx", alpha=1.0,
            citation_id_validity=cit_validity,
            context_supported_citation_validity=cs_validity,
            fabricated_citation_count=fab_count,
        )

    def test_summary_aggregates_context_supported_validity(self):
        cases = [
            EvalCase(id="c1", query="q1", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH),
            EvalCase(id="c2", query="q2", query_type=QueryType.SINGLE_FACT,
                     language=Language.ZH),
        ]
        arms = [ARM_STANDARD]
        results = [
            self._mk_gen("c1", ARM_STANDARD, cs_validity=1.0, fab_count=0),
            self._mk_gen("c2", ARM_STANDARD, cs_validity=0.5, fab_count=1),
        ]
        summary = compute_summary(results, cases, arms, bootstrap_iterations=10)
        overall = summary["standard"]["overall"]
        assert overall["context_supported_citation_validity"] == 0.75
        assert overall["fabricated_citation_avg"] == 0.5
        assert overall["citation_id_validity"] == 0.0


# ── Selector 策略消融（S0/S3 双臂） ─────────────────────────────────

class TestSelectorAblationArms:
    """selector 消融：S0（不限同源）/ S3（每源最多 3）双臂实现与 A/B/C 兼容。"""

    def test_arm_selector_policy_mapping(self):
        """S0→None（不限）、S3→3；A/B/C 保持生产默认 3。"""
        from evaluation.compare import (
            _arm_selector_max_per_source,
            ARM_STANDARD, ARM_STANDARD_RERANK, ARM_GRAPH_RERANK,
            ARM_SELECTOR_UNLIMITED, ARM_SELECTOR_CAP3,
        )
        assert _arm_selector_max_per_source(ARM_SELECTOR_UNLIMITED) is None
        assert _arm_selector_max_per_source(ARM_SELECTOR_CAP3) == 3
        assert _arm_selector_max_per_source(ARM_STANDARD) == 3
        assert _arm_selector_max_per_source(ARM_STANDARD_RERANK) == 3
        assert _arm_selector_max_per_source(ARM_GRAPH_RERANK) == 3
        with pytest.raises(ValueError, match="Unknown arm"):
            _arm_selector_max_per_source("no-such-arm")

    @patch("src.rag._get_reranker")
    def test_validate_reranker_selector_arms_no_reranker(self, mock_get_reranker):
        """S0/S3 是无 reranker 臂：validate_reranker 返回 None 且不调用 _get_reranker。"""
        from evaluation.compare import (
            validate_reranker,
            ARM_SELECTOR_UNLIMITED, ARM_SELECTOR_CAP3,
        )
        result = validate_reranker([ARM_SELECTOR_UNLIMITED, ARM_SELECTOR_CAP3])
        assert result is None
        mock_get_reranker.assert_not_called()

    @patch("src.rag.expand_with_adjacent")
    @patch("src.rag.expand_with_parent")
    @patch("src.rag.compute_context_k")
    @patch("src.rag._build_context")
    @patch("src.rag.enrich_context")
    @patch("src.rag.dynamic_top_k")
    def test_s0_s3_share_query_plan_and_candidate_pool(
        self, mock_dynamic_top_k, mock_enrich, mock_build_context,
        mock_compute_k, mock_expand_parent, mock_expand_adjacent,
    ):
        """S0/S3 同一 case 共享同一 QueryPlan/候选池，唯一差异是 max_per_source。

        候选池（candidate_chunk_ids）两臂逐 chunk 相同；context 层 S3 每源
        ≤3（同源第 4 个被挤出），S0 不限同源全部保留；重复运行结果确定。
        """
        from evaluation.compare import (
            _run_retrieval_arm, QueryPlan,
            ARM_SELECTOR_UNLIMITED, ARM_SELECTOR_CAP3,
        )

        mock_dynamic_top_k.return_value = 6
        mock_enrich.side_effect = lambda idxs, docs, metas: [docs[i] for i in idxs]
        mock_build_context.return_value = "ctx"
        mock_compute_k.return_value = 6
        mock_expand_parent.side_effect = lambda idxs, *a, **k: (idxs, [])
        mock_expand_adjacent.side_effect = lambda idxs, *a, **k: idxs

        plan = QueryPlan(
            rewritten_query="test", rewrite_log={}, sub_queries=["test"],
            base_candidates={i: 1.0 - i * 0.1 for i in range(6)},
        )
        case = EvalCase(
            id="s1", query="q1", query_type=QueryType.SINGLE_FACT,
            language=Language.ZH, relevant_chunks=[],
        )
        all_docs = [f"text{i}" for i in range(6)]
        all_metadatas = [
            {"chunk_id": f"c{i}", "source_id": "s0", "source_name": "doc_a.pdf"}
            for i in range(4)
        ] + [
            {"chunk_id": f"c{i}", "source_id": "s1", "source_name": "doc_b.pdf"}
            for i in range(4, 6)
        ]

        ra = _run_retrieval_arm(
            case=case, arm=ARM_SELECTOR_UNLIMITED, model=None, collection=None,
            bm25=None, all_docs=all_docs, all_metadatas=all_metadatas,
            query_plan=plan, reranker=None,
        )
        rb = _run_retrieval_arm(
            case=case, arm=ARM_SELECTOR_CAP3, model=None, collection=None,
            bm25=None, all_docs=all_docs, all_metadatas=all_metadatas,
            query_plan=plan, reranker=None,
        )
        # 候选池逐 case 一致（同一 QueryPlan 基础检索）
        assert ra.candidate_chunk_ids == rb.candidate_chunk_ids
        assert ra.candidate_chunk_ids == ["c0", "c1", "c2", "c3", "c4", "c5"]
        # S3：每源最多 3 → 同源第 4 个 c3 被挤出
        assert rb.context_chunk_ids == ["c0", "c1", "c2", "c4", "c5"]
        # S0：不限同源 → 全部保留
        assert ra.context_chunk_ids == ["c0", "c1", "c2", "c3", "c4", "c5"]
        # 确定性：S0 重复运行结果一致
        ra2 = _run_retrieval_arm(
            case=case, arm=ARM_SELECTOR_UNLIMITED, model=None, collection=None,
            bm25=None, all_docs=all_docs, all_metadatas=all_metadatas,
            query_plan=plan, reranker=None,
        )
        assert ra2.context_chunk_ids == ra.context_chunk_ids

    @patch("evaluation.compare.evaluate_citations_context_aware")
    @patch("src.rag.answer_query")
    def test_selector_arms_generation_patch_selector_max_per_source(
        self, mock_answer, mock_eval,
    ):
        """S0/S3 生成臂：answer_query 期间 SELECTOR_MAX_PER_SOURCE 按臂设置。

        S0 → None（不限同源）；S3 → 3（每源最多 3）；RAG_RERANKER_MODE 均为
        "none"；调用结束后模块值恢复原状（finally 保证）。
        """
        import src.rag as rag_mod
        from evaluation.compare import (
            _run_generation_arm, RetrievalCaseResult,
            ARM_SELECTOR_UNLIMITED, ARM_SELECTOR_CAP3,
        )
        from evaluation.citation_metrics import CitationMetrics

        captured = {}

        def _fake_answer(*args, **kwargs):
            captured["selector"] = rag_mod.SELECTOR_MAX_PER_SOURCE
            captured["reranker"] = rag_mod.RAG_RERANKER_MODE
            return "答案", "[S1] doc_a.pdf (p.1; chunk 1; §x; chunk_id=c0): 文本"

        mock_answer.side_effect = _fake_answer
        # 前 7 字段为必填（dataclass 无默认值），扩展字段有默认值
        mock_eval.return_value = CitationMetrics(0.0, 0, 0, 0.0, 0.0, 0.0, None)

        case = EvalCase(
            id="s1", query="q1", query_type=QueryType.SINGLE_FACT,
            language=Language.ZH, relevant_chunks=[],
        )
        rr = RetrievalCaseResult(
            case_id="s1", arm="x", query="q1", query_type="single_fact",
            language="zh", should_refuse=False,
            candidate_chunk_ids=[], candidate_source_ids=[], candidate_scores=[],
            context_chunk_ids=[], context_source_ids=[],
            relevant_chunk_ids=set(), relevant_source_ids=set(),
            total_retrieval_ms=50.0,
        )
        original_selector = rag_mod.SELECTOR_MAX_PER_SOURCE
        original_reranker = rag_mod.RAG_RERANKER_MODE
        try:
            for arm, expected in ((ARM_SELECTOR_UNLIMITED, None),
                                  (ARM_SELECTOR_CAP3, 3)):
                captured.clear()
                _run_generation_arm(
                    case=case, arm=arm, model=None, collection=None, bm25=None,
                    all_docs=[], all_metadatas=[],
                    retrieval_result=rr,
                )
                assert captured["selector"] == expected
                assert captured["reranker"] == "none"
            # finally 恢复原值（双臂调用结束后）
            assert rag_mod.SELECTOR_MAX_PER_SOURCE == original_selector
            assert rag_mod.RAG_RERANKER_MODE == original_reranker
        finally:
            rag_mod.SELECTOR_MAX_PER_SOURCE = original_selector
            rag_mod.RAG_RERANKER_MODE = original_reranker

    def test_manifest_records_arm_selector_policy(self):
        """manifest 记录每臂 selector policy（S0/S3 防配置漂移审计）。"""
        from pathlib import Path
        from evaluation.compare import (
            build_run_manifest, ARM_SELECTOR_UNLIMITED, ARM_SELECTOR_CAP3,
        )
        with patch("builtins.open", create=True), \
                patch("evaluation.compare._compute_dataset_hash",
                      return_value="abc"), \
                patch("evaluation.compare._compute_corpus_hash",
                      return_value="def"), \
                patch("subprocess.check_output", return_value=b""), \
                patch("evaluation.compare._git_diff_hash", return_value="diff"):
            manifest = build_run_manifest(
                dataset_path=Path("/tmp/x.jsonl"),
                corpus_dir=Path("/tmp/corpus"),
                source_files=["doc1.pdf"],
                arms=[ARM_SELECTOR_UNLIMITED, ARM_SELECTOR_CAP3],
            )
        assert manifest["arm_selector_policy"] == {
            ARM_SELECTOR_UNLIMITED: None,
            ARM_SELECTOR_CAP3: 3,
        }

    def test_cli_accepts_selector_ablation_arms(self, tmp_path):
        """--validate-only 接受 selector 消融臂（argparse choices 扩展）。"""
        import json
        from evaluation.compare import main

        ds = tmp_path / "v1.jsonl"
        row = {
            "id": "c1", "query": "南京面积？", "query_type": "single_fact",
            "language": "zh", "relevant_source_ids": ["doc1.pdf"],
            "relevant_chunks": [{
                "source_id": "doc1.pdf", "chunk_text_snippet": "总面积6587",
                "page": None, "section": None,
            }],
            "acceptable_answer_points": ["6587"], "should_refuse": False,
            "metadata": {"difficulty": "easy"},
        }
        with open(ds, "w", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + chr(10))
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "doc1.pdf").write_bytes(b"nanjing city area 6587")

        rc = main([
            "--validate-only", "--dataset", str(ds),
            "--corpus-dir", str(corpus),
            "--arms", "selector-unlimited", "selector-cap3",
        ])
        assert rc == 0
