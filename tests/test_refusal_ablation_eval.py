"""拒答策略消融评测端（evaluation.compare）的单元测试。

覆盖（RED → GREEN）：
- 新臂 standard-calibrated 常量与 REFUSAL_ABLATION_ARMS；
- standard-calibrated 臂临时覆盖 RAG_REFUSAL_POLICY 并 finally 恢复
  （含异常路径）；standard 臂不覆盖（默认行为不变）；
- ablation 双臂共享同一 PreparedAnswerEvidence（每 case 只构建一次）；
- GenerationCaseResult 写入 evidence/context 指纹（context_sha256 /
  plan / retrieval / citation map），随 generation JSONL 落盘；
- run_generation_grid 把同一 evidence_cache 传给两臂。
"""
from __future__ import annotations

from unittest import mock

import pytest


def _mk_case(cid="c1"):
    from evaluation.schema import EvalCase, Language, QueryType
    return EvalCase(
        id=cid, query="q", query_type=QueryType.SINGLE_FACT,
        language=Language.ZH, relevant_chunks=[],
    )


def _mk_plan():
    from evaluation.compare import QueryPlan
    return QueryPlan(
        rewritten_query="q", rewrite_log={"changed": False},
        sub_queries=["q"], base_candidates={0: 0.5},
    )


def _mk_retrieval_result(case_id="c1", arm="standard"):
    from evaluation.compare import RetrievalCaseResult
    return RetrievalCaseResult(
        case_id=case_id, arm=arm, query="q", query_type="single_fact",
        language="zh", should_refuse=False,
        candidate_chunk_ids=["c0"], candidate_source_ids=["s1"],
        candidate_scores=[0.5],
        context_chunk_ids=["c0"], context_source_ids=["s1"],
        relevant_chunk_ids={"c0"}, relevant_source_ids={"s1"},
        alpha=0.7,
    )


class TestAblationArmConstants:
    def test_arm_constant_defined(self):
        from evaluation import compare
        assert compare.ARM_STANDARD_CALIBRATED == "standard-calibrated"
        assert compare.ARM_STANDARD in compare.REFUSAL_ABLATION_ARMS
        assert compare.ARM_STANDARD_CALIBRATED in compare.REFUSAL_ABLATION_ARMS

    def test_arms_choices_accept_ablation(self):
        from evaluation.compare import main
        with mock.patch("sys.argv", [
            "compare", "--dataset", "v1", "--corpus-dir", ".",
            "--split", "development", "--phase", "retrieval",
            "--arms", "standard", "standard-calibrated",
            "--output", "tmp_out",
        ]):
            # 只验证 argparse 接受（后续 mock 管线）
            with mock.patch("evaluation.compare.run_retrieval_grid"), \
                 mock.patch("evaluation.compare.build_query_plan_cache",
                            return_value={}), \
                 mock.patch("evaluation.compare.load_dataset",
                            return_value=[]), \
                 mock.patch("evaluation.compare._compute_dataset_hash",
                            return_value="a" * 64), \
                 mock.patch("evaluation.compare._compute_corpus_hash",
                            return_value="b" * 64), \
                 mock.patch("evaluation.compare.resolve_dataset_path"):
                from pathlib import Path
                with mock.patch("evaluation.compare.Path.mkdir"):
                    rc = main(["--dataset", "v1", "--corpus-dir", ".",
                               "--split", "development", "--phase", "retrieval",
                               "--arms", "standard", "standard-calibrated",
                               "--output", "tmp_out"])
        assert rc in (0, None) or rc == 1  # 解析通过；管线 mock 后可能提前退出


class TestArmPolicyOverride:
    """standard-calibrated 臂覆盖策略并恢复。"""

    def _run_arm(self, arm, policy_before="baseline", force_error=False):
        import src.rag as rag
        from evaluation import compare

        fake_metrics = mock.Mock()
        fake_metrics.evidence = []
        fake_metrics.citation_id_validity = 1.0
        fake_metrics.citation_precision = 1.0
        fake_metrics.citation_recall = 1.0
        fake_metrics.faithfulness = 1.0
        fake_metrics.correctly_refused = True
        fake_metrics.context_supported_citation_validity = 1.0
        fake_metrics.fabricated_citation_count = 0
        fake_metrics.retrieved_not_in_context_count = 0

        with mock.patch.object(rag, "RAG_REFUSAL_POLICY", policy_before), \
             mock.patch.object(rag, "generate_answer",
                               mock.Mock(side_effect=(
                                   RuntimeError("boom") if force_error
                                   else ("answer", "sources")))), \
             mock.patch.object(rag, "prepare_answer_evidence",
                               mock.Mock(return_value=mock.Mock(
                                   context_sha256="ctx",
                                   plan_fingerprint="plan",
                                   retrieval_fingerprint="retr",
                                   citation_map=(("S1", "c0"),),
                               ))), \
             mock.patch.object(rag, "answer_query",
                               mock.Mock(return_value=("answer", "sources"))), \
             mock.patch.object(compare, "evaluate_citations_context_aware",
                               return_value=fake_metrics), \
             mock.patch.object(compare, "compute_answer_point_coverage",
                               return_value=0.5), \
             mock.patch.object(compare, "_chunk_to_source_map",
                               return_value={}), \
             mock.patch.object(compare, "_rebuild_context_text",
                               return_value="ctx text"), \
             mock.patch.object(compare, "_citation_status_counts",
                               return_value={}):
            result = compare._run_generation_arm(
                _mk_case(), arm, model=mock.Mock(), collection=mock.Mock(),
                bm25=mock.Mock(), all_docs=[], all_metadatas=[],
                history=None, ground_truth_chunk_ids=set(),
                retrieval_result=_mk_retrieval_result(arm=arm),
            )
        return result

    def test_calibrated_arm_uses_evidence_calibrated_policy(self):
        import src.rag as rag
        from evaluation import compare
        policy_seen = []

        real_generate = rag.generate_answer
        def spy_generate(evidence, documents, metadatas, **kwargs):
            policy_seen.append(rag.RAG_REFUSAL_POLICY)
            return real_generate(evidence, documents, metadatas, **kwargs)

        with mock.patch.object(rag, "RAG_REFUSAL_POLICY", "baseline"), \
             mock.patch.object(rag, "generate_answer", spy_generate), \
             mock.patch.object(rag, "answer_query",
                               mock.Mock(return_value=("answer", "sources"))), \
             mock.patch.object(compare, "evaluate_citations_context_aware",
                               return_value=mock.Mock(
                                   evidence=[], citation_id_validity=1.0,
                                   citation_precision=1.0, citation_recall=1.0,
                                   faithfulness=1.0, correctly_refused=True,
                                   context_supported_citation_validity=1.0,
                                   fabricated_citation_count=0,
                                   retrieved_not_in_context_count=0)), \
             mock.patch.object(compare, "compute_answer_point_coverage",
                               return_value=0.5), \
             mock.patch.object(compare, "_chunk_to_source_map",
                               return_value={}), \
             mock.patch.object(compare, "_rebuild_context_text",
                               return_value="ctx text"), \
             mock.patch.object(compare, "_citation_status_counts",
                               return_value={}):
            compare._run_generation_arm(
                _mk_case(), "standard-calibrated", model=mock.Mock(),
                collection=mock.Mock(), bm25=mock.Mock(),
                all_docs=[], all_metadatas=[],
                history=None, ground_truth_chunk_ids=set(),
                retrieval_result=_mk_retrieval_result(arm="standard-calibrated"),
                evidence=mock.Mock(
                    refused=False, query="q", context="c", context_k=1,
                    top_indices=(0,), select_indices=(0,),
                    context_sha256="ctx", plan_fingerprint="plan",
                    retrieval_fingerprint="retr", citation_map=(("S1", "c0"),),
                ),
            )
        assert policy_seen == ["evidence_calibrated"]
        # 恢复：模块变量回到覆盖前值
        assert rag.RAG_REFUSAL_POLICY == "baseline"

    def test_standard_arm_does_not_override_policy(self):
        import src.rag as rag
        from evaluation import compare
        with mock.patch.object(rag, "RAG_REFUSAL_POLICY", "baseline"), \
             mock.patch.object(rag, "answer_query",
                               mock.Mock(return_value=("answer", "sources"))), \
             mock.patch.object(compare, "evaluate_citations_context_aware",
                               return_value=mock.Mock(
                                   evidence=[], citation_id_validity=1.0,
                                   citation_precision=1.0, citation_recall=1.0,
                                   faithfulness=1.0, correctly_refused=True,
                                   context_supported_citation_validity=1.0,
                                   fabricated_citation_count=0,
                                   retrieved_not_in_context_count=0)), \
             mock.patch.object(compare, "compute_answer_point_coverage",
                               return_value=0.5), \
             mock.patch.object(compare, "_chunk_to_source_map",
                               return_value={}), \
             mock.patch.object(compare, "_rebuild_context_text",
                               return_value="ctx text"), \
             mock.patch.object(compare, "_citation_status_counts",
                               return_value={}):
            compare._run_generation_arm(
                _mk_case(), "standard", model=mock.Mock(),
                collection=mock.Mock(), bm25=mock.Mock(),
                all_docs=[], all_metadatas=[],
                history=None, ground_truth_chunk_ids=set(),
                retrieval_result=_mk_retrieval_result(arm="standard"),
            )
        assert rag.RAG_REFUSAL_POLICY == "baseline"

    def test_calibrated_arm_restores_policy_on_error(self):
        """异常路径也必须恢复策略（finally）。"""
        import src.rag as rag
        from evaluation import compare
        with mock.patch.object(rag, "RAG_REFUSAL_POLICY", "baseline"), \
             mock.patch.object(rag, "generate_answer",
                               mock.Mock(side_effect=RuntimeError("boom"))), \
             mock.patch.object(rag, "prepare_answer_evidence",
                               mock.Mock(return_value=mock.Mock(
                                   refused=False, query="q", context="c",
                                   context_k=1, top_indices=(0,),
                                   select_indices=(0,),
                               ))), \
             mock.patch.object(compare, "evaluate_citations_context_aware",
                               return_value=mock.Mock(
                                   evidence=[], citation_id_validity=1.0,
                                   citation_precision=1.0, citation_recall=1.0,
                                   faithfulness=1.0, correctly_refused=True,
                                   context_supported_citation_validity=1.0,
                                   fabricated_citation_count=0,
                                   retrieved_not_in_context_count=0)), \
             mock.patch.object(compare, "compute_answer_point_coverage",
                               return_value=0.5), \
             mock.patch.object(compare, "_chunk_to_source_map",
                               return_value={}), \
             mock.patch.object(compare, "_rebuild_context_text",
                               return_value="ctx text"), \
             mock.patch.object(compare, "_citation_status_counts",
                               return_value={}):
            result = compare._run_generation_arm(
                _mk_case(), "standard-calibrated", model=mock.Mock(),
                collection=mock.Mock(), bm25=mock.Mock(),
                all_docs=[], all_metadatas=[],
                history=None, ground_truth_chunk_ids=set(),
                retrieval_result=_mk_retrieval_result(arm="standard-calibrated"),
            )
        assert result.error is not None
        assert rag.RAG_REFUSAL_POLICY == "baseline"


class TestEvidenceSharedOnce:
    """ablation 双臂共享同一 evidence（每 case 只构建一次）。"""

    def test_evidence_built_once_and_reused(self):
        import src.rag as rag
        from evaluation import compare

        evidence = mock.Mock(
            refused=False, query="q", context="c", context_k=1,
            top_indices=(0,), select_indices=(0,),
            context_sha256="ctx", plan_fingerprint="plan",
            retrieval_fingerprint="retr", citation_map=(("S1", "c0"),),
        )
        cache = {}
        with mock.patch.object(rag, "RAG_REFUSAL_POLICY", "baseline"), \
             mock.patch.object(rag, "generate_answer",
                               mock.Mock(return_value=("answer", "sources"))) as gen, \
             mock.patch.object(rag, "prepare_answer_evidence",
                               mock.Mock(return_value=evidence)) as prepare, \
             mock.patch.object(compare, "evaluate_citations_context_aware",
                               return_value=mock.Mock(
                                   evidence=[], citation_id_validity=1.0,
                                   citation_precision=1.0, citation_recall=1.0,
                                   faithfulness=1.0, correctly_refused=True,
                                   context_supported_citation_validity=1.0,
                                   fabricated_citation_count=0,
                                   retrieved_not_in_context_count=0)), \
             mock.patch.object(compare, "compute_answer_point_coverage",
                               return_value=0.5), \
             mock.patch.object(compare, "_chunk_to_source_map",
                               return_value={}), \
             mock.patch.object(compare, "_rebuild_context_text",
                               return_value="ctx text"), \
             mock.patch.object(compare, "_citation_status_counts",
                               return_value={}):
            key = (0.7, "c1")
            # 第一臂：构建并缓存
            compare._run_generation_arm(
                _mk_case(), "standard", model=mock.Mock(),
                collection=mock.Mock(), bm25=mock.Mock(),
                all_docs=[], all_metadatas=[],
                history=None, ground_truth_chunk_ids=set(),
                retrieval_result=_mk_retrieval_result(arm="standard"),
                evidence=None, evidence_cache=cache, evidence_key=key,
                query_plan=_mk_plan(),
            )
            # 第二臂：命中缓存，不再构建
            compare._run_generation_arm(
                _mk_case(), "standard-calibrated", model=mock.Mock(),
                collection=mock.Mock(), bm25=mock.Mock(),
                all_docs=[], all_metadatas=[],
                history=None, ground_truth_chunk_ids=set(),
                retrieval_result=_mk_retrieval_result(arm="standard-calibrated"),
                evidence=cache[key], evidence_cache=cache, evidence_key=key,
                query_plan=_mk_plan(),
            )
        assert prepare.call_count == 1
        assert cache[key] is evidence
        assert gen.call_count == 2


class TestGenerationCaseEvidenceFields:
    """GenerationCaseResult 携带 evidence/context 指纹。"""

    def test_result_carries_evidence_fields(self):
        from evaluation.compare import GenerationCaseResult
        r = GenerationCaseResult(
            case_id="c1", arm="standard-calibrated", query="q",
            query_type="single_fact", language="zh", should_refuse=False,
            answer="a", context="", alpha=0.7,
            evidence_context_sha256="ctxsha",
            evidence_plan_fingerprint="planfp",
            evidence_retrieval_fingerprint="retrfp",
            evidence_citation_map=[["S1", "c0"]],
        )
        d = r.__dict__
        assert d["evidence_context_sha256"] == "ctxsha"
        assert d["evidence_plan_fingerprint"] == "planfp"
        assert d["evidence_retrieval_fingerprint"] == "retrfp"
        assert d["evidence_citation_map"] == [["S1", "c0"]]

    def test_default_evidence_fields_empty(self):
        """非 ablation 路径（历史行为）字段为空，不破坏既有 JSONL schema。"""
        from evaluation.compare import GenerationCaseResult
        r = GenerationCaseResult(
            case_id="c1", arm="standard", query="q",
            query_type="single_fact", language="zh", should_refuse=False,
            answer="a", context="", alpha=0.7,
        )
        assert r.evidence_context_sha256 == ""
        assert r.evidence_plan_fingerprint == ""
        assert r.evidence_retrieval_fingerprint == ""
        assert r.evidence_citation_map == ()


class TestGenerationGridSharedCache:
    """run_generation_grid 对 ablation 臂传递同一 evidence_cache。"""

    def test_grid_passes_same_cache_to_both_arms(self):
        from evaluation.compare import run_generation_grid
        captured = []

        def fake_arm(case, arm, model, collection, bm25, all_docs, all_metadatas,
                     kg, alpha, history, ground_truth_chunk_ids, retrieval_result,
                     evidence=None, evidence_cache=None, evidence_key=None,
                     query_plan=None):
            captured.append((arm, evidence_cache, evidence_key))
            from evaluation.compare import GenerationCaseResult
            return GenerationCaseResult(
                case_id=case.id, arm=arm, query=case.query,
                query_type=case.query_type.value, language=case.language.value,
                should_refuse=False, answer="a", context="", alpha=alpha,
            )

        with mock.patch("evaluation.compare._run_generation_arm",
                        side_effect=fake_arm):
            results = run_generation_grid(
                active_cases=[_mk_case()],
                arms=["standard", "standard-calibrated"],
                alpha_values=[0.7],
                model=None, collection=None, bm25=None,
                all_docs=[], all_metadatas=[],
                kg=None,
                query_plan_cache={"c1": _mk_plan()},
                gt_map={"c1": set()},
                chain_map={},
            )
        assert len(results) == 2
        caches = [c[1] for c in captured]
        assert caches[0] is not None and caches[1] is not None
        assert caches[0] is caches[1]  # 同一缓存对象
        keys = [c[2] for c in captured]
        assert keys[0] == keys[1] == (0.7, "c1")
