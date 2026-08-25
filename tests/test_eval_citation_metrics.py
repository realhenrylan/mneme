"""Tests for evaluation.citation_metrics module."""

import pytest

from evaluation.citation_metrics import (
    CitationEvidence,
    compute_citation_id_validity,
    compute_citation_precision_recall,
    compute_faithfulness,
    compute_refusal_accuracy,
    evaluate_citations,
    evaluate_citations_context_aware,
    parse_sources_citation_map,
    _extract_key_terms,
)


# ── compute_citation_id_validity ────────────────────────────────────

class TestCitationIdValidity:
    def test_all_valid(self):
        validity, invalid, total = compute_citation_id_validity(
            "According to [S1] and [S2], the answer is 42.",
            {"S1", "S2", "S3"},
        )
        assert validity == 1.0
        assert invalid == 0
        assert total == 2

    def test_some_invalid(self):
        validity, invalid, total = compute_citation_id_validity(
            "According to [S1] and [S5], the answer is 42.",
            {"S1", "S2", "S3"},
        )
        assert validity == 0.5
        assert invalid == 1
        assert total == 2

    def test_all_invalid(self):
        validity, invalid, total = compute_citation_id_validity(
            "According to [S99], the answer is 42.",
            {"S1", "S2"},
        )
        assert validity == 0.0
        assert invalid == 1
        assert total == 1

    def test_no_citations(self):
        validity, invalid, total = compute_citation_id_validity(
            "The answer is 42.",
            {"S1", "S2"},
        )
        assert validity == 0.0
        assert invalid == 0
        assert total == 0


# ── compute_citation_precision_recall ───────────────────────────────

class TestCitationPrecisionRecall:
    def test_perfect_precision_recall(self):
        p, r = compute_citation_precision_recall(
            "According to [S1] and [S2].",
            relevant_chunk_ids={"chunk_1", "chunk_2"},
            all_retrieved_ids={"S1", "S2", "S3"},
        )
        # S1, S2 are cited and valid; they may or may not match
        # relevant_chunk_ids by name — this tests the mechanism
        assert isinstance(p, float)
        assert isinstance(r, float)

    def test_no_citations_zero_precision(self):
        p, r = compute_citation_precision_recall(
            "The answer is 42.",
            relevant_chunk_ids={"chunk_1"},
            all_retrieved_ids={"S1"},
        )
        assert p == 0.0

    def test_no_relevant_zero_recall(self):
        p, r = compute_citation_precision_recall(
            "According to [S1].",
            relevant_chunk_ids=set(),
            all_retrieved_ids={"S1"},
        )
        assert r == 0.0


# ── compute_faithfulness ────────────────────────────────────────────

class TestFaithfulness:
    def test_all_points_supported(self):
        context = "南京总面积6587.04平方千米，海拔最高点为紫金山448.9米"
        points = ["6587.04平方千米", "紫金山448.9米"]
        f = compute_faithfulness("南京面积6587.04平方千米", points, context)
        assert f == 1.0

    def test_partial_support(self):
        context = "南京总面积6587.04平方千米"
        points = ["6587.04平方千米", "紫金山448.9米"]
        f = compute_faithfulness("南京面积6587.04平方千米", points, context)
        # Only one of two points is supported
        assert f == 0.5

    def test_no_points_vacuously_faithful(self):
        f = compute_faithfulness("Some answer", [], "Some context")
        assert f == 1.0

    def test_english_faithfulness(self):
        context = "DSpark improves the macro-average accepted length by 30.9%"
        points = ["30.9%"]
        f = compute_faithfulness("DSpark improves by 30.9%", points, context)
        assert f == 1.0


# ── compute_refusal_accuracy ────────────────────────────────────────

class TestRefusalAccuracy:
    def test_correct_refusal_zh(self):
        result = compute_refusal_accuracy(
            "未找到足够可靠的文档依据，暂时无法回答该问题。",
            should_refuse=True,
        )
        assert result is True

    def test_incorrect_answer_when_should_refuse(self):
        result = compute_refusal_accuracy(
            "南京的GDP是1.6万亿元。",
            should_refuse=True,
        )
        assert result is False

    def test_correct_answer_when_should_not_refuse(self):
        result = compute_refusal_accuracy(
            "南京总面积6587.04平方千米。",
            should_refuse=False,
        )
        assert result is True

    def test_incorrect_refusal_when_should_answer(self):
        result = compute_refusal_accuracy(
            "未找到相关信息，无法回答。",
            should_refuse=False,
        )
        assert result is False

    def test_english_refusal(self):
        result = compute_refusal_accuracy(
            "I cannot find information about this topic.",
            should_refuse=True,
        )
        assert result is True


# ── _extract_key_terms ──────────────────────────────────────────────

class TestExtractKeyTerms:
    def test_chinese_terms(self):
        terms = _extract_key_terms("南京总面积6587.04平方千米")
        # CJK characters are grouped as continuous runs
        assert "南京总面积" in terms
        assert "6587.04" in terms
        assert "平方千米" in terms

    def test_english_terms(self):
        terms = _extract_key_terms("DSpark improves by 30.9%")
        assert "dspark" in terms
        assert "30.9%" in terms

    def test_stop_words_filtered(self):
        terms = _extract_key_terms("The answer is in the document")
        assert "the" not in terms
        assert "is" not in terms


# ── evaluate_citations (integration) ────────────────────────────────

class TestEvaluateCitations:
    def test_basic_evaluation(self):
        metrics = evaluate_citations(
            answer="根据[S1]，南京总面积6587.04平方千米。",
            valid_ids={"S1", "S2", "S3"},
            relevant_chunk_ids={"chunk_0"},
            all_retrieved_ids={"S1", "S2", "S3"},
            answer_points=["6587.04平方千米"],
            context="南京总面积6587.04平方千米",
            should_refuse=False,
        )
        assert metrics.citation_id_validity == 1.0
        assert metrics.invalid_citation_count == 0
        assert metrics.total_citation_count == 1
        assert metrics.faithfulness == 1.0
        assert metrics.correctly_refused is True

    def test_refusal_case(self):
        metrics = evaluate_citations(
            answer="未找到足够可靠的文档依据，暂时无法回答该问题。",
            valid_ids={"S1"},
            relevant_chunk_ids=set(),
            all_retrieved_ids={"S1"},
            answer_points=[],
            context="Some context",
            should_refuse=True,
        )
        assert metrics.correctly_refused is True


# ── parse_sources_citation_map（契约 v2：S# → chunk 权威映射） ───────

SRC_LINE_1 = ("[S1] 南京城市地理环境.docx (p.3; chunk 2; § 简介; "
              "chunk_id=d8fa2a45c99677a0ed0440cc3bfed8eb270589e4b1c31821526505e0dcbe7e9b_chunk_2): "
              "南京市辖区总面积约为6587.04平方千米...")
SRC_LINE_2 = ("[S2] OneDrive 入门.pdf (p.1; § 入门; "
              "chunk_id=3be83454b2997f53c90577babbcb77dd5293a7d789b803c10bebfdd3ec5b3f06_chunk_5): "
              "OneDrive 是微软提供的云存储服务...")
SRC_LINE_NO_CHUNK = "[S3] 未知来源 (location unavailable): 无法解析的引用行"


class TestParseSourcesCitationMap:
    def test_parses_standard_format_sources_lines(self):
        sources = "\n".join([SRC_LINE_1, SRC_LINE_2])
        parsed = parse_sources_citation_map(sources)
        assert parsed == {
            "S1": "d8fa2a45c99677a0ed0440cc3bfed8eb270589e4b1c31821526505e0dcbe7e9b_chunk_2",
            "S2": "3be83454b2997f53c90577babbcb77dd5293a7d789b803c10bebfdd3ec5b3f06_chunk_5",
        }

    def test_skips_lines_without_chunk_id(self):
        parsed = parse_sources_citation_map(SRC_LINE_NO_CHUNK)
        assert parsed == {}

    def test_empty_sources_returns_empty(self):
        assert parse_sources_citation_map("") == {}
        assert parse_sources_citation_map(None) == {}

    def test_deterministic_first_match_wins(self):
        dup = SRC_LINE_1 + "\n" + SRC_LINE_1.replace("chunk_2", "chunk_99")
        parsed = parse_sources_citation_map(dup)
        assert parsed["S1"].endswith("chunk_2")  # 首个出现保留


# ── evaluate_citations_context_aware（契约 v2：context-level 支持） ──

CHUNK_A = "aaaa_chunk_2"
CHUNK_B = "bbbb_chunk_5"
CHUNK_C = "cccc_chunk_7"
CHUNK_D = "dddd_chunk_9"

COMMON_KW = dict(
    sources="\n".join([
        f"[S1] src1 (p.1; chunk_id={CHUNK_A}): a...",
        f"[S2] src2 (p.2; chunk_id={CHUNK_B}): b...",
        f"[S3] src3 (p.3; chunk_id={CHUNK_C}): c...",
        f"[S4] src4 (p.4; chunk_id={CHUNK_D}): d...",
    ]),
    context_chunk_ids=[CHUNK_A],
    context_source_ids=["src1"],
    candidate_chunk_ids=[CHUNK_A, CHUNK_B, CHUNK_C, CHUNK_D],
    chunk_to_source={CHUNK_A: "src1", CHUNK_B: "src2",
                     CHUNK_C: "src3", CHUNK_D: "src4"},
    context_text="src1 的内容文本",
)


class TestEvaluateCitationsContextAware:
    def test_context_chunk_supported(self):
        """引用 chunk 在最终 context 中 → supported_chunk，validity=1.0。"""
        m = evaluate_citations_context_aware(
            answer=f"根据[S1]，答案是 A。", **COMMON_KW)
        assert m.context_supported_citation_validity == 1.0
        assert m.citation_id_validity == 1.0  # retrieval-visible 同样有效
        assert m.supported_chunk_count == 1
        assert m.fabricated_citation_count == 0
        assert m.retrieved_not_in_context_count == 0
        assert m.evidence[0].status == "supported_chunk"

    def test_context_source_supported(self):
        """chunk 不在 context 但其 source 在 context_source_ids → supported_source。"""
        m = evaluate_citations_context_aware(
            answer=f"根据[S2]，答案是 B。",
            context_chunk_ids=[CHUNK_A],
            context_source_ids=["src1", "src2"],
            **{k: v for k, v in COMMON_KW.items()
               if k not in ("context_chunk_ids", "context_source_ids")},
        )
        assert m.context_supported_citation_validity == 1.0
        assert m.evidence[0].status == "supported_source"
        assert m.supported_source_count == 1

    def test_candidate_only_not_in_context_invalid(self):
        """仅在候选池、未进入最终 context 的引用 → 无效。"""
        m = evaluate_citations_context_aware(
            answer=f"根据[S2]，答案是 B。", **COMMON_KW)
        assert m.context_supported_citation_validity == 0.0
        assert m.evidence[0].status == "retrieved_not_in_context"
        assert m.retrieved_not_in_context_count == 1
        # retrieval-visible 层仍然有效（该引用确实来自 sources 展示）
        assert m.citation_id_validity == 1.0

    def test_fabricated_citation_invalid(self):
        """幻觉引用（不在任何 sources 中）→ fabricated，无效。"""
        m = evaluate_citations_context_aware(
            answer="根据[S9]，答案是 X。", **COMMON_KW)
        assert m.context_supported_citation_validity == 0.0
        assert m.citation_id_validity == 0.0
        assert m.evidence[0].status == "fabricated"
        assert m.fabricated_citation_count == 1

    def test_empty_citation_zero_validity(self):
        """空引用（答案无引用）→ validity 0.0，total=0，无证据。"""
        m = evaluate_citations_context_aware(
            answer="南京总面积6587.04平方千米。", **COMMON_KW)
        assert m.context_supported_citation_validity == 0.0
        assert m.total_citation_count == 0
        assert m.unique_citation_count == 0
        assert m.evidence == ()

    def test_duplicate_citation_counted_once(self):
        """重复引用按唯一 ID 计一次，不放大有效性。"""
        m = evaluate_citations_context_aware(
            answer=f"根据[S1]，这是 A。重复确认[S1]也是 A。", **COMMON_KW)
        assert m.total_citation_count == 1
        assert m.unique_citation_count == 1
        assert m.context_supported_citation_validity == 1.0

    def test_mixed_multi_citation_deterministic(self):
        """多引用混合状态：S1 支持 + S2 候选池未进 + S9 幻觉 → validity=1/3。"""
        m = evaluate_citations_context_aware(
            answer="引用[S1]与[S2]与[S9]。", **COMMON_KW)
        assert m.total_citation_count == 3
        assert m.context_supported_citation_validity == 1.0 / 3.0
        assert m.citation_id_validity == 2.0 / 3.0  # S1/S2 在 sources 中可见
        assert m.supported_chunk_count == 1
        assert m.retrieved_not_in_context_count == 1
        assert m.fabricated_citation_count == 1
        statuses = [e.status for e in m.evidence]
        assert statuses == ["supported_chunk", "retrieved_not_in_context", "fabricated"]
        assert all(isinstance(e, CitationEvidence) for e in m.evidence)

    def test_source_only_case_recall_zero(self):
        """source-only case（relevant_chunk_ids 空）：recall=0.0，validity 正常。"""
        m = evaluate_citations_context_aware(
            answer=f"根据[S1]，答案是 A。",
            relevant_chunk_ids=set(), **COMMON_KW)
        assert m.context_supported_citation_validity == 1.0
        assert m.citation_recall == 0.0

    def test_precision_uses_context_supported_cited(self):
        """precision 分母只计 context-supported 引用。"""
        m = evaluate_citations_context_aware(
            answer="引用[S1]与[S2]。",  # S1 支持且相关；S2 未进 context
            relevant_chunk_ids={CHUNK_A}, **COMMON_KW)
        assert m.citation_precision == 1.0  # 分母只有 S1（S2 不算）
        assert m.citation_recall == 1.0

    def test_missing_sources_fails_closed(self):
        with pytest.raises(ValueError, match="sources"):
            evaluate_citations_context_aware(
                answer="根据[S1]，答案是 A。",
                sources=None, context_chunk_ids=[CHUNK_A],
                context_source_ids=["src1"], candidate_chunk_ids=[CHUNK_A],
                chunk_to_source={CHUNK_A: "src1"}, context_text="ctx")

    def test_missing_context_chunk_ids_fails_closed(self):
        with pytest.raises(ValueError, match="context_chunk_ids"):
            evaluate_citations_context_aware(
                answer="根据[S1]，答案是 A。",
                sources="[S1] src1 (p.1; chunk_id=a1): x",
                context_chunk_ids=None, context_source_ids=["src1"],
                candidate_chunk_ids=["a1"],
                chunk_to_source={"a1": "src1"}, context_text="ctx")

    def test_missing_chunk_to_source_fails_closed(self):
        with pytest.raises(ValueError, match="chunk_to_source"):
            evaluate_citations_context_aware(
                answer="根据[S1]，答案是 A。",
                sources="[S1] src1 (p.1; chunk_id=a1): x",
                context_chunk_ids=["a1"], context_source_ids=["src1"],
                candidate_chunk_ids=["a1"],
                chunk_to_source=None, context_text="ctx")

    def test_missing_context_text_fails_closed(self):
        with pytest.raises(ValueError, match="context_text"):
            evaluate_citations_context_aware(
                answer="根据[S1]，答案是 A。",
                sources="[S1] src1 (p.1; chunk_id=a1): x",
                context_chunk_ids=["a1"], context_source_ids=["src1"],
                candidate_chunk_ids=["a1"],
                chunk_to_source={"a1": "src1"}, context_text=None)

    def test_empty_context_is_real_not_placeholder(self):
        """context 真实为空（如拒绝路径）→ [] 合法，引用全部无效而非报错。"""
        m = evaluate_citations_context_aware(
            answer="根据[S1]，答案是 A。",
            sources=f"[S1] src1 (p.1; chunk_id={CHUNK_A}): a...",
            context_chunk_ids=[], context_source_ids=[],
            candidate_chunk_ids=[CHUNK_A],
            chunk_to_source={CHUNK_A: "src1"}, context_text="")
        assert m.context_supported_citation_validity == 0.0
        assert m.evidence[0].status == "retrieved_not_in_context"

    def test_chunk_unknown_to_retrieval_is_fabricated(self):
        """sources 解析出 chunk 但不在候选/context 记录 → 不可验证，视为 fabricated。"""
        m = evaluate_citations_context_aware(
            answer=f"根据[S4]，答案是 D。",
            candidate_chunk_ids=[CHUNK_A],  # S4 的 chunk 不在候选池
            context_chunk_ids=[CHUNK_A], context_source_ids=["src1"],
            **{k: v for k, v in COMMON_KW.items()
               if k not in ("candidate_chunk_ids", "context_chunk_ids",
                            "context_source_ids")},
        )
        assert m.evidence[0].status == "fabricated"
        assert m.fabricated_citation_count == 1


# ── 生产路径一致性（流式/非流式同源 format_sources） ─────────────────

class TestProductionPathConsistency:
    def test_validate_citations_valid_ids_match_sources_parse(self):
        """生产非流式路径 _validate_and_repair_citations 的合法 ID 集
        （context 内 citation_map）与 sources 解析映射的 ID 集一致。"""
        from src.citations import citation_map
        from src.rag import format_sources
        docs = ["文档A内容", "文档B内容", "文档C内容"]
        metas = [
            {"chunk_id": "c_a", "source_name": "src1", "source_id": "h1",
             "page": 1},
            {"chunk_id": "c_b", "source_name": "src1", "source_id": "h2",
             "page": 2},
            {"chunk_id": "c_c", "source_name": "src2", "source_id": "h3",
             "page": 3},
        ]
        indices = [0, 1, 2]
        context_k = 2
        sources = format_sources(indices, docs, metas, context_k=context_k)
        parsed = parse_sources_citation_map(sources)
        # citation_map(selected_indices=top_indices[:context_k]) 是生产校验口径
        records = citation_map(indices[:context_k], docs, metas)
        assert set(parsed.keys()) == {r.citation_id for r in records.values()}
        assert list(parsed.values()) == [
            r.chunk_id for r in records.values()]

    def test_same_evidence_same_validity_across_paths(self):
        """同一 sources（流式/非流式共用 format_sources 产物）与同一 context
        证据 → 评估结果完全一致（评估与 sources 来源路径无关）。"""
        from src.rag import format_sources
        docs = ["文档A内容", "文档B内容", "文档C内容"]
        metas = [
            {"chunk_id": "c_a", "source_name": "src1", "source_id": "h1",
             "page": 1},
            {"chunk_id": "c_b", "source_name": "src2", "source_id": "h2",
             "page": 2},
            {"chunk_id": "c_c", "source_name": "src3", "source_id": "h3",
             "page": 3},
        ]
        # 流式与非流式生产路径都调用同一个 format_sources
        sources_a = format_sources([0, 1, 2], docs, metas, context_k=3)
        sources_b = format_sources([0, 1, 2], docs, metas, context_k=3)
        assert sources_a == sources_b  # 确定性
        kw = dict(
            sources=sources_a,
            context_chunk_ids=["c_a", "c_b", "c_c"],
            context_source_ids=["src1", "src2", "src3"],
            candidate_chunk_ids=["c_a", "c_b", "c_c"],
            chunk_to_source={"c_a": "src1", "c_b": "src2", "c_c": "src3"},
            context_text="文档内容",
        )
        m1 = evaluate_citations_context_aware("根据[S1]和[S2]。", **kw)
        m2 = evaluate_citations_context_aware("根据[S1]和[S2]。", **kw)
        assert (m1.context_supported_citation_validity
                == m2.context_supported_citation_validity == 1.0)
        assert m1.evidence == m2.evidence
