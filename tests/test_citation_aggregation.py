"""Tests for evaluation.citation_aggregation — Citation v2 分母统一契约。

覆盖（任务 TDD 清单）：
- 同一 case 集的 summary（compute_summary）、pair analysis（reconcile 切片）、
  JSONL replay 逐字段完全一致；
- 全体 / 可答 / 含 citation 三种分母不会混淆；
- 空分母返回 unavailable（None），不伪装为 0；
- source-only、refusal、无引用、重复引用、多引用；
- arm/case 过滤后行守恒（numerator / excluded_count / 分母内未命中）；
- 旧字段可读但不能作为新 guardrail 输入。
"""

import json

import pytest

from evaluation.citation_aggregation import (
    DENOM_ALL_GENERATION_CASES,
    DENOM_ANSWERABLE_GENERATION_CASES,
    DENOM_ANSWERS_WITH_ANY_CITATION,
    DENOM_TOTAL_UNIQUE_CITATION_IDS,
    CaseCitationCounts,
    MetricValue,
    aggregate_citations,
    case_counts_from_jsonl_row,
    case_counts_from_result,
    get_guardrail_metric,
    legacy_mean_metric,
)
from evaluation.compare import GenerationCaseResult, compute_summary
from evaluation.schema import EvalCase, Language, QueryType


# ── 构造辅助 ────────────────────────────────────────────────────────


def cc(case_id, *, refused=False, error=None, unique=None, supported=None,
       fabricated=None, not_in_context=None, other=None,
       legacy_validity=None) -> CaseCitationCounts:
    """构造一个 case 级 citation 事实（supported 缺省 = 全部支持）。"""
    if unique is None:
        supported = supported
    elif supported is None:
        supported = unique
    return CaseCitationCounts(
        case_id=case_id,
        arm="test-arm",
        should_refuse=refused,
        error=error,
        unique_citation_ids=unique,
        supported_citation_ids=supported,
        fabricated_citation_ids=fabricated if fabricated is not None else 0,
        retrieved_not_in_context_ids=(
            not_in_context if not_in_context is not None else 0),
        other_status_ids=other if other is not None else 0,
        legacy_citation_id_validity=legacy_validity,
    )


def gen_result(case_id, *, refused=False, error=None,
               status_counts=None, legacy_validity=0.0,
               legacy_cs_validity=0.0) -> GenerationCaseResult:
    """构造一个 GenerationCaseResult（模拟 _run_generation_arm 输出）。"""
    return GenerationCaseResult(
        case_id=case_id,
        arm="standard",
        query="q",
        query_type="single_fact",
        language="zh",
        should_refuse=refused,
        answer="a",
        context="",
        error=error,
        citation_id_validity=legacy_validity,
        context_supported_citation_validity=legacy_cs_validity,
        citation_status_counts=dict(status_counts or {}),
    )


def eval_case(case_id, *, refused=False) -> EvalCase:
    return EvalCase(
        id=case_id,
        query="q",
        query_type=QueryType.SINGLE_FACT,
        language=Language.ZH,
        should_refuse=refused,
    )


# ── 提取（live / replay 路径） ──────────────────────────────────────


class TestExtraction:
    def test_v2_result_to_counts(self):
        r = gen_result("c1", status_counts={
            "supported_chunk": 2, "fabricated": 1})
        c = case_counts_from_result(r)
        assert c.unique_citation_ids == 3
        assert c.supported_citation_ids == 2
        assert c.fabricated_citation_ids == 1
        assert c.retrieved_not_in_context_ids == 0

    def test_supported_source_counts_as_supported(self):
        r = gen_result("c1", status_counts={
            "supported_chunk": 1, "supported_source": 1,
            "retrieved_not_in_context": 2})
        c = case_counts_from_result(r)
        assert c.unique_citation_ids == 4
        assert c.supported_citation_ids == 2
        assert c.retrieved_not_in_context_ids == 2

    def test_no_citation_result(self):
        r = gen_result("c1", status_counts={})
        c = case_counts_from_result(r)
        assert c.unique_citation_ids == 0
        assert c.supported_citation_ids == 0
        assert c.legacy_citation_id_validity == 0.0

    def test_v2_jsonl_row_roundtrip_equals_result(self):
        r = gen_result("c1", status_counts={"supported_chunk": 1})
        import dataclasses
        row = dataclasses.asdict(r)
        c1 = case_counts_from_result(r)
        c2 = case_counts_from_jsonl_row(row)
        assert c1 == c2

    def test_v1_jsonl_row_missing_evidence(self):
        # 23 字段的 v1 产物：无 citation_status_counts / context 证据
        row = {
            "case_id": "c1", "arm": "standard", "query": "q",
            "query_type": "single_fact", "language": "zh",
            "should_refuse": False, "answer": "a", "context": "",
            "citation_id_validity": 0.5, "citation_precision": 0.0,
            "citation_recall": 0.0, "faithfulness": 0.0,
            "answer_point_coverage": 0.5, "total_ms": 1.0,
        }
        c = case_counts_from_jsonl_row(row)
        assert c.unique_citation_ids is None  # 缺证据 → 不可重算
        assert c.supported_citation_ids is None
        assert c.legacy_citation_id_validity == 0.5  # 旧字段仍可读

    def test_unknown_status_goes_to_other(self):
        r = gen_result("c1", status_counts={
            "supported_chunk": 1, "some_future_status": 2})
        c = case_counts_from_result(r)
        assert c.unique_citation_ids == 3
        assert c.other_status_ids == 2


# ── 分母语义（不混淆） ──────────────────────────────────────────────


class TestDenominatorSemantics:
    def _selector_ablation_shaped_rows(self):
        """复现 selector-ablation dev 的形状：94 行 = 22 refusal + 72 可答
        （63 有引用全支持 + 9 无引用），每行 1 个唯一引用 ID。"""
        rows = []
        for i in range(22):
            rows.append(cc(f"ref-{i}", refused=True))
        for i in range(63):
            rows.append(cc(f"ans-{i}", unique=1, supported=1))
        for i in range(9):
            rows.append(cc(f"nocite-{i}", unique=0, supported=0))
        return rows

    def test_three_denominators_distinct(self):
        agg = aggregate_citations(self._selector_ablation_shaped_rows())
        m = agg.metrics
        # ID 层：分母 = total_unique_citation_ids（63）
        assert m["context_supported_citation_validity_micro"].denominator \
            == DENOM_TOTAL_UNIQUE_CITATION_IDS
        assert m["context_supported_citation_validity_micro"].denominator_count == 63
        assert m["context_supported_citation_validity_micro"].value == 1.0
        # 答案层：分母 = answerable（72）
        assert m["context_supported_answer_rate"].denominator \
            == DENOM_ANSWERABLE_GENERATION_CASES
        assert m["context_supported_answer_rate"].denominator_count == 72
        assert m["context_supported_answer_rate"].value == pytest.approx(63 / 72)
        # 含 citation 分母：63
        assert m["citation_mention_rate"].denominator \
            == DENOM_ANSWERABLE_GENERATION_CASES
        assert m["citation_mention_rate"].value == pytest.approx(63 / 72)
        # no_citation_rate
        assert m["no_citation_answer_rate"].value == pytest.approx(9 / 72)
        # 与旧「全体分母」值（67/94=0.7128）明确不同，且新字段名携带语义
        assert m["context_supported_answer_rate"].value != pytest.approx(67 / 94)

    def test_micro_vs_macro_not_confused(self):
        """契约是 ID 层 micro：Σ supported / Σ unique，不是 per-case 均值。"""
        rows = [
            cc("a", unique=3, supported=2, fabricated=1),  # 2/3
            cc("b", unique=1, supported=0, not_in_context=1),  # 0/1
            cc("c", unique=2, supported=0, fabricated=2),      # 0/2
        ]
        agg = aggregate_citations(rows)
        micro = agg.metrics["context_supported_citation_validity_micro"]
        assert micro.numerator == 2
        assert micro.denominator_count == 6
        assert micro.value == pytest.approx(2 / 6)
        macro = (2 / 3 + 0 / 1 + 0 / 2) / 3
        assert micro.value != pytest.approx(macro)

    def test_all_cases_denominator_reported_but_not_used_for_rates(self):
        agg = aggregate_citations(self._selector_ablation_shaped_rows())
        assert agg.n_all_cases == 94
        # 全体分母只用于行分类展示，不用于 rate 指标
        for name in ("context_supported_answer_rate", "no_citation_answer_rate"):
            assert agg.metrics[name].denominator != DENOM_ALL_GENERATION_CASES


# ── 空分母 → unavailable ────────────────────────────────────────────


class TestEmptyDenominator:
    def test_no_rows_all_unavailable(self):
        agg = aggregate_citations([])
        for m in agg.metrics.values():
            assert m.value is None
            assert m.numerator == 0
        assert agg.n_all_cases == 0

    def test_all_refused_answer_rates_unavailable(self):
        rows = [cc(f"r{i}", refused=True) for i in range(5)]
        agg = aggregate_citations(rows)
        assert agg.n_answerable == 0
        for name in ("context_supported_answer_rate",
                     "no_citation_answer_rate", "citation_mention_rate"):
            assert agg.metrics[name].value is None
        # ID 层也无引用 → unavailable
        assert agg.metrics["context_supported_citation_validity_micro"].value is None

    def test_all_no_citation_validity_unavailable_but_answer_rate_zero(self):
        rows = [cc(f"n{i}", unique=0, supported=0) for i in range(3)]
        agg = aggregate_citations(rows)
        # 分母 total_unique_ids = 0 → 不允许伪装为 0
        assert agg.metrics["context_supported_citation_validity_micro"].value is None
        assert agg.metrics["context_supported_answer_rate"].value == 0.0
        assert agg.metrics["no_citation_answer_rate"].value == 1.0


# ── 守恒（行 / ID 分区，过滤后仍成立） ──────────────────────────────


class TestConservation:
    def _mixed_rows(self):
        return [
            cc("ref", refused=True),
            cc("err", error="boom"),
            cc("s1", unique=2, supported=2),
            cc("s2", unique=1, supported=1),
            cc("unsup", unique=2, supported=0, fabricated=2),
            cc("nocite", unique=0, supported=0),
            cc("missing", unique=None, supported=None),
        ]

    def test_row_partition_conserved(self):
        agg = aggregate_citations(self._mixed_rows())
        assert agg.n_all_cases == 7
        assert agg.n_refused == 1
        assert agg.n_error == 1
        assert agg.n_answerable == 5
        assert agg.n_supported_answers == 2
        assert agg.n_cited_but_unsupported_answers == 1
        assert agg.n_no_citation == 1
        assert agg.n_evidence_missing == 1
        agg.check_conservation()  # 不抛 = 恒等式成立

    def test_arm_filter_conservation(self):
        rows = self._mixed_rows()
        rows = [r for r in rows if r.case_id != "ref"]
        agg = aggregate_citations(rows)
        assert agg.n_all_cases == 6
        agg.check_conservation()

    def test_id_partition_conserved(self):
        rows = [
            cc("a", unique=3, supported=1, fabricated=1, not_in_context=1),
            cc("b", unique=2, supported=2),
            cc("c", unique=1, supported=0, other=1),
        ]
        agg = aggregate_citations(rows)
        assert agg.total_unique_citation_ids == 6
        assert agg.n_supported_ids == 3
        assert agg.n_fabricated_ids == 1
        assert agg.n_retrieved_not_in_context_ids == 1
        assert agg.n_other_status_ids == 1
        agg.check_conservation()

    def test_numerator_plus_excluded_reconciles_with_rows(self):
        """答案层：numerator + excluded（分母外行）+ 分母内未命中行 == 原始行数。"""
        rows = self._mixed_rows()
        agg = aggregate_citations(rows)
        m = agg.metrics["context_supported_answer_rate"]
        # 分母内未命中 = denominator_count − numerator（不支持但有证据的行）
        denom_internal_miss = m.denominator_count - m.numerator
        assert m.numerator + m.excluded_count + denom_internal_miss == agg.n_all_cases
        # 特例：分母内未命中 = 0 时，numerator + excluded_count == 原始行数
        agg2 = aggregate_citations([
            cc("r", refused=True),
            cc("a", unique=1, supported=1),
        ])
        m2 = agg2.metrics["context_supported_answer_rate"]
        assert m2.numerator + m2.excluded_count == agg2.n_all_cases

    def test_refusal_error_citation_ids_not_counted(self):
        """refusal/error 行的引用（若有）不进入 ID 分母（false_answer 由拒答
        指标单独跟踪）。"""
        rows = [
            cc("ref", refused=True, unique=3, supported=3),
            cc("ok", unique=1, supported=1),
        ]
        agg = aggregate_citations(rows)
        assert agg.total_unique_citation_ids == 1
        agg.check_conservation()


# ── 边界：source-only / refusal / 无引用 / 重复引用 / 多引用 ─────────


class TestEdgeCases:
    def test_refusal_excluded_from_answerable(self):
        agg = aggregate_citations([
            cc("r", refused=True),
            cc("a", unique=1, supported=1),
        ])
        assert agg.n_answerable == 1
        assert agg.metrics["context_supported_answer_rate"].denominator_count == 1
        assert agg.metrics["context_supported_answer_rate"].value == 1.0

    def test_source_only_case_citations_aggregate_normally(self):
        """source-only（无 chunk 真值）不影响 citation 聚合——聚合不消费
        relevance 真值，只消费引用与 context 证据。"""
        rows = [cc("src-only", unique=1, supported=1)]
        agg = aggregate_citations(rows)
        assert agg.n_answerable == 1
        assert agg.metrics["context_supported_answer_rate"].value == 1.0

    def test_error_rows_excluded(self):
        agg = aggregate_citations([
            cc("e", error="x"),
            cc("a", unique=1, supported=1),
        ])
        assert agg.n_error == 1
        assert agg.n_answerable == 1
        assert agg.metrics["context_supported_answer_rate"].excluded_count == 1

    def test_duplicate_citation_counted_once(self):
        """重复引用在 citation_metrics 层已按唯一 ID 计一次；本层只信任
        status_counts 的 ID 计数（2 个 supported ID ≠ 4 次出现）。"""
        r = gen_result("c1", status_counts={"supported_chunk": 2})
        c = case_counts_from_result(r)
        assert c.unique_citation_ids == 2  # 非 4
        assert c.supported_citation_ids == 2

    def test_multi_citation_mixed_status(self):
        rows = [
            cc("a", unique=3, supported=1, fabricated=1, not_in_context=1),
        ]
        agg = aggregate_citations(rows)
        assert agg.n_supported_answers == 1
        m = agg.metrics["context_supported_citation_validity_micro"]
        assert m.value == pytest.approx(1 / 3)
        assert agg.n_fabricated_ids == 1
        assert agg.n_retrieved_not_in_context_ids == 1


# ── legacy 隔离 ─────────────────────────────────────────────────────


class TestLegacyIsolation:
    def test_legacy_fields_readable_but_not_consumed(self):
        rows = [
            cc("a", unique=1, supported=1, legacy_validity=0.5),
            cc("b", unique=1, supported=0, fabricated=1, legacy_validity=0.0),
        ]
        agg = aggregate_citations(rows)
        # legacy 值保留在 case 事实中（可读、可对账）
        assert rows[0].legacy_citation_id_validity == 0.5
        # 新指标完全不使用 legacy 字段
        m = agg.metrics["context_supported_citation_validity_micro"]
        assert m.numerator == 1  # 若误用 legacy 会得到不同值

    def test_guardrail_rejects_legacy_names(self):
        agg = aggregate_citations([cc("a", unique=1, supported=1)])
        with pytest.raises(ValueError, match="legacy|deprecated"):
            get_guardrail_metric(agg, "citation_id_validity")
        with pytest.raises(ValueError, match="legacy|deprecated"):
            get_guardrail_metric(agg, "context_supported_citation_validity")
        with pytest.raises(ValueError, match="unknown"):
            get_guardrail_metric(agg, "not_a_metric")
        # 新指标可消费
        assert get_guardrail_metric(
            agg, "context_supported_citation_validity_micro") == 1.0

    def test_legacy_mean_metric_centralized(self):
        """旧「全体分母均值」只允许经 legacy_mean_metric 计算（reconcile 对账
        用），标记 deprecated。"""
        rows = [
            cc("a", unique=1, supported=1, legacy_validity=1.0),
            cc("r", refused=True, legacy_validity=0.0),
        ]
        assert legacy_mean_metric(rows, "legacy_citation_id_validity") == 0.5
        with pytest.raises(ValueError):
            legacy_mean_metric(rows, "not_a_legacy_field")


# ── summary / replay / pair analysis 逐字段一致 ─────────────────────


class TestSummaryReplayConsistency:
    def _mock_generation_run(self):
        """5 个 case 的生成结果：1 refusal、1 error、1 no-citation、
        1 全部支持、1 混合状态。"""
        results = [
            gen_result("ref-1", refused=True, legacy_validity=0.0),
            gen_result("err-1", error="boom"),
            gen_result("nocite-1", status_counts={}),
            gen_result("ok-1", status_counts={"supported_chunk": 1},
                       legacy_validity=1.0, legacy_cs_validity=1.0),
            gen_result("mix-1",
                       status_counts={"supported_chunk": 1, "fabricated": 1},
                       legacy_validity=0.5, legacy_cs_validity=0.5),
        ]
        cases = [
            eval_case("ref-1", refused=True),
            eval_case("err-1"),
            eval_case("nocite-1"),
            eval_case("ok-1"),
            eval_case("mix-1"),
        ]
        return results, cases

    def test_summary_and_jsonl_replay_identical(self):
        """同一 case 集：live 路径（compute_summary）与 JSONL replay 路径
        产出逐字段一致的 citation_v2 块。"""
        import dataclasses

        results, cases = self._mock_generation_run()
        summary = compute_summary(results, cases, arms=["standard"])
        live_v2 = summary["standard"]["overall"]["citation_v2"]

        # JSONL replay：逐 case 序列化 → 反序列化 → 提取 → 聚合
        rows = [dataclasses.asdict(r) for r in results]
        replay_v2 = aggregate_citations(
            [case_counts_from_jsonl_row(r) for r in rows]).to_dict()
        assert live_v2 == replay_v2

        # 契约新字段存在且分母语义正确
        m = live_v2["metrics"]["context_supported_answer_rate"]
        assert m["denominator_count"] == 3  # ok-1/mix-1/nocite-1
        assert m["numerator"] == 2          # ok-1 + mix-1（≥1 支持）
        assert m["value"] == pytest.approx(2 / 3)
        assert live_v2["metrics"]["context_supported_citation_validity_micro"][
            "value"] == pytest.approx(2 / 3)  # 2 supported / 3 unique

    def test_replay_deterministic(self):
        import dataclasses

        results, cases = self._mock_generation_run()
        rows = [dataclasses.asdict(r) for r in results]
        a1 = aggregate_citations(
            [case_counts_from_jsonl_row(r) for r in rows]).to_dict()
        a2 = aggregate_citations(
            [case_counts_from_jsonl_row(r) for r in rows]).to_dict()
        assert json.dumps(a1, sort_keys=True) == json.dumps(a2, sort_keys=True)

    def test_pair_analysis_slice_uses_same_helper(self):
        """pair analysis 的切片过滤与直接聚合一致（reconcile 工具按 arm 过滤
        后调用同一 helper——本测试验证过滤后聚合 = 工具输出）。"""
        rows = [
            cc("a", unique=1, supported=1),
            cc("b", unique=1, supported=0, fabricated=1),
            cc("c", refused=True),
        ]
        full = aggregate_citations(rows)
        filtered = aggregate_citations([r for r in rows if r.arm == "test-arm"])
        # 过滤后行数守恒
        assert filtered.n_all_cases == full.n_all_cases
        filtered.check_conservation()


# ── reconcile 工具（离线 replay） ───────────────────────────────────


class TestReconcileTool:
    def _write_v2_run(self, tmp_path):
        import dataclasses

        run_dir = tmp_path / "selector-ablation-x" / "dev-full"
        run_dir.mkdir(parents=True)
        results = [
            gen_result("ok-1", status_counts={"supported_chunk": 1},
                       legacy_validity=1.0, legacy_cs_validity=1.0),
            gen_result("nocite-1", status_counts={}),
            gen_result("ref-1", refused=True),
        ]
        with open(run_dir / "generation-cases.jsonl", "w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(dataclasses.asdict(r), ensure_ascii=False)
                        + "\n")
        gen_summary = {
            "compare_version": 1, "case_count": 3, "arm_count": 1,
            "standard": {"overall": {
                "context_supported_citation_validity": 1 / 3,
                "citation_id_validity": 1 / 3,
            }},
        }
        with open(run_dir / "generation-summary.json", "w",
                  encoding="utf-8") as f:
            json.dump(gen_summary, f, ensure_ascii=False)
        return tmp_path / "selector-ablation-x"

    def _write_v1_run(self, tmp_path):
        run_dir = tmp_path / "auto-run-x" / "dev-full"
        run_dir.mkdir(parents=True)
        rows = [
            {"case_id": "c1", "arm": "standard", "query": "q",
             "query_type": "single_fact", "language": "zh",
             "should_refuse": False, "answer": "a", "context": "",
             "citation_id_validity": 1.0, "citation_precision": 0.0,
             "citation_recall": 0.0, "faithfulness": 0.0,
             "answer_point_coverage": 1.0, "total_ms": 1.0},
            {"case_id": "c2", "arm": "standard", "query": "q",
             "query_type": "single_fact", "language": "zh",
             "should_refuse": True, "answer": "r", "context": "",
             "citation_id_validity": 0.0, "citation_precision": 0.0,
             "citation_recall": 0.0, "faithfulness": 0.0,
             "answer_point_coverage": 0.0, "total_ms": 1.0},
        ]
        with open(run_dir / "generation-cases.jsonl", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        gen_summary = {
            "compare_version": 1, "case_count": 2, "arm_count": 1,
            "standard": {"overall": {"citation_id_validity": 0.5}},
        }
        with open(run_dir / "generation-summary.json", "w",
                  encoding="utf-8") as f:
            json.dump(gen_summary, f, ensure_ascii=False)
        return tmp_path / "auto-run-x"

    def test_reconcile_v2_run(self, tmp_path):
        from evaluation.reconcile_citation_denominators import main as reconcile_main
        run_dir = self._write_v2_run(tmp_path)
        out = tmp_path / "out"
        rc = reconcile_main(["--output", str(out), "--run", str(run_dir)])
        assert rc == 0
        import json as _json
        summary = _json.loads(
            (out / "reconciliation-summary.json").read_text(encoding="utf-8"))
        assert str(run_dir) in summary["runs"]
        result = summary["runs"][str(run_dir)]
        assert result["replayable"] is True
        arm = result["splits"]["dev-full"]["arms"]["standard"]
        # 3 行：ok-1（支持）、nocite-1（无引用）、ref-1（拒答）→ 可答 2、支持 1
        assert arm["citation_v2"]["metrics"][
            "context_supported_answer_rate"]["value"] == pytest.approx(0.5)
        # 对账：legacy 旧值（全体分母均值）与 JSONL 重算一致
        legacy = result["splits"]["dev-full"]["legacy"]["standard"]
        assert legacy["context_supported_citation_validity"][
            "old_summary_value"] == pytest.approx(1 / 3)
        assert legacy["context_supported_citation_validity"][
            "match"] is True
        assert (out / "reconciliation-summary.json").exists()
        assert (out / "reconciliation-report.md").exists()

    def test_reconcile_v1_run_unavailable_context_supported(self, tmp_path):
        from evaluation.reconcile_citation_denominators import main as reconcile_main
        run_dir = self._write_v1_run(tmp_path)
        out = tmp_path / "out"
        rc = reconcile_main(["--output", str(out), "--run", str(run_dir)])
        assert rc == 0
        import json as _json
        summary = _json.loads(
            (out / "reconciliation-summary.json").read_text(encoding="utf-8"))
        result = summary["runs"][str(run_dir)]
        assert result["replayable"] is False  # 缺 context 证据
        arm = result["splits"]["dev-full"]["arms"]["standard"]
        m = arm["citation_v2"]["metrics"]["context_supported_answer_rate"]
        assert m["value"] is None  # 不可重算 → unavailable
        # legacy 对账仍可做：citation_id_validity 全体均值 0.5 == 旧 summary
        legacy = result["splits"]["dev-full"]["legacy"]["standard"]
        assert legacy["citation_id_validity"][
            "old_summary_value"] == pytest.approx(0.5)
        assert legacy["citation_id_validity"][
            "replayed_value"] == pytest.approx(0.5)

    def test_analysis_old_values_arm_map(self, tmp_path):
        """历史分析脚本（s0s3/ab）的 arm 标签（S0/S3、A/B）映射到规范名。"""
        from evaluation.reconcile_citation_denominators import (
            _analysis_old_values)
        run_dir = tmp_path / "sel"
        run_dir.mkdir()
        (run_dir / "s0s3-analysis.json").write_text(json.dumps({
            "split": {"dev": {"generation": {
                "context_supported_citation_validity": {
                    "S0": 0.875, "S3": 0.847}}}},
        }), encoding="utf-8")
        (run_dir / "ab-analysis.json").write_text(json.dumps({
            "split": {"dev": {"generation": {
                "citation_id_validity": {"A": 0.85, "B": 0.80}}}},
        }), encoding="utf-8")
        out = _analysis_old_values(run_dir)
        assert out["dev"]["s0s3-analysis.json"]["selector-unlimited"] == 0.875
        assert out["dev"]["s0s3-analysis.json"]["selector-cap3"] == 0.847
        assert out["dev"]["ab-analysis.json"]["standard"] == 0.85
        assert out["dev"]["ab-analysis.json"]["standard-rerank"] == 0.80

    def test_reconcile_does_not_modify_historical_inputs(self, tmp_path):
        import dataclasses

        from evaluation.reconcile_citation_denominators import main as reconcile_main
        run_dir = self._write_v2_run(tmp_path)
        cases_file = run_dir / "dev-full" / "generation-cases.jsonl"
        before = cases_file.read_bytes()
        out = tmp_path / "out"
        reconcile_main(["--output", str(out), "--run", str(run_dir)])
        assert cases_file.read_bytes() == before  # 输入未被改写
