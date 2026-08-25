"""paired_analysis 模块（拒答策略消融 A/B 配对分析）的单元测试。

覆盖（RED → GREEN）：
- evidence 一致性 fail-closed：同 case A/B 的 context_sha256 / citation
  map / candidate 集任一不同 → 拒绝；
- 配对 W/L/T（拒答二元错误配对）、McNemar exact 输出；
- block bootstrap CI（false_refusal delta、coverage delta）确定性；
- cross_document / hard 切片配对。
"""
from __future__ import annotations

import json

import pytest

from evaluation.paired_analysis import (
    check_evidence_consistency,
    paired_analysis,
)


def _row(case_id, arm, query_type="single_fact", language="zh",
         should_refuse=False, correctly_refused=True, answer_point_coverage=0.5,
         context_sha="ctx", citation_map=(("S1", "c0"),), candidates=("c0",)):
    return {
        "case_id": case_id, "arm": arm, "query": "q", "query_type": query_type,
        "language": language, "should_refuse": should_refuse,
        "answer": "a", "context": "", "alpha": 0.7,
        "correctly_refused": correctly_refused,
        "answer_point_coverage": answer_point_coverage,
        "evidence_context_sha256": context_sha,
        "evidence_plan_fingerprint": "plan",
        "evidence_retrieval_fingerprint": "retr",
        "evidence_citation_map": list(citation_map),
        "evidence_candidate_chunk_ids": list(candidates),
        "error": None,
    }


class TestEvidenceConsistency:
    def test_matching_evidence_passes(self):
        a = _row("c1", "standard")
        b = _row("c1", "standard-calibrated")
        assert check_evidence_consistency([a], [b]) == []

    def test_context_sha_diff_rejected(self):
        a = _row("c1", "standard", context_sha="ctx-a")
        b = _row("c1", "standard-calibrated", context_sha="ctx-b")
        diffs = check_evidence_consistency([a], [b])
        assert any("context_sha256" in d and "c1" in d for d in diffs)

    def test_citation_map_diff_rejected(self):
        a = _row("c1", "standard", citation_map=(("S1", "c0"),))
        b = _row("c1", "standard-calibrated", citation_map=(("S1", "c9"),))
        diffs = check_evidence_consistency([a], [b])
        assert any("citation" in d and "c1" in d for d in diffs)

    def test_candidate_set_diff_rejected(self):
        a = _row("c1", "standard", candidates=("c0", "c1"))
        b = _row("c1", "standard-calibrated", candidates=("c0",))
        diffs = check_evidence_consistency([a], [b])
        assert any("candidate" in d and "c1" in d for d in diffs)

    def test_missing_evidence_fields_rejected(self):
        a = dict(_row("c1", "standard"))
        b = dict(_row("c1", "standard-calibrated"))
        b["evidence_context_sha256"] = ""
        diffs = check_evidence_consistency([a], [b])
        assert diffs


class TestPairedWLT:
    def test_wins_losses_ties(self):
        # W: A 错拒答（false refusal）而 B 答 → B 改善
        a_w = _row("c1", "standard", correctly_refused=False)
        b_w = _row("c1", "standard-calibrated", correctly_refused=True)
        # L: A 答而 B 错拒 → B 恶化
        a_l = _row("c2", "standard", correctly_refused=True)
        b_l = _row("c2", "standard-calibrated", correctly_refused=False)
        # T: 双方都正确
        a_t = _row("c3", "standard", correctly_refused=True)
        b_t = _row("c3", "standard-calibrated", correctly_refused=True)
        res = paired_analysis([a_w, a_l, a_t], [b_w, b_l, b_t])
        p = res["paired"]
        assert p["wins_b"] == 1
        assert p["losses_b"] == 1
        assert p["ties"] == 1
        assert p["n_cases"] == 3

    def test_false_refusal_delta(self):
        a = [_row(f"c{i}", "standard", correctly_refused=False)
             for i in range(4)]
        b = [_row(f"c{i}", "standard-calibrated", correctly_refused=True)
             for i in range(4)]
        res = paired_analysis(a, b)
        assert res["paired"]["false_refusal"]["a"] == 4
        assert res["paired"]["false_refusal"]["b"] == 0
        assert res["paired"]["false_refusal"]["delta"] == -4

    def test_mcnemar_present(self):
        a = [_row("c1", "standard", correctly_refused=False),
             _row("c2", "standard", correctly_refused=True)]
        b = [_row("c1", "standard-calibrated", correctly_refused=True),
             _row("c2", "standard-calibrated", correctly_refused=True)]
        res = paired_analysis(a, b)
        assert "mcnemar" in res["paired"]
        assert res["paired"]["mcnemar"]["b_only"] == 1  # A 错 B 对（B 改善）

    def test_slices_cross_document_and_hard(self):
        # 需要 dataset 提供 metadata.difficulty —— 这里用 language/query_type
        a = [_row("c1", "standard", query_type="cross_document"),
             _row("c2", "standard", query_type="single_fact")]
        b = [_row("c1", "standard-calibrated", query_type="cross_document"),
             _row("c2", "standard-calibrated", query_type="single_fact")]
        res = paired_analysis(a, b)
        slices = res["slices"]
        assert "cross_document" in slices
        assert slices["cross_document"]["n_cases"] == 1
        assert slices["metadata"]["n_cases"] == 0  # 未覆盖组为 0 且存在

    def test_bootstrap_ci_deterministic(self):
        a = [_row(f"c{i}", "standard", answer_point_coverage=0.5)
             for i in range(20)]
        b = [_row(f"c{i}", "standard-calibrated", answer_point_coverage=0.6)
             for i in range(20)]
        r1 = paired_analysis(a, b, n_iter=200, seed=42)
        r2 = paired_analysis(a, b, n_iter=200, seed=42)
        assert (r1["paired"]["answer_point_coverage"]["bootstrap95ci_delta"]
                == r2["paired"]["answer_point_coverage"]["bootstrap95ci_delta"])

    def test_case_id_mismatch_rejected(self):
        a = [_row("c1", "standard")]
        b = [_row("c2", "standard-calibrated")]
        with pytest.raises(ValueError, match="case"):
            paired_analysis(a, b)

    def test_answer_point_coverage_delta(self):
        a = [_row(f"c{i}", "standard", answer_point_coverage=0.0)
             for i in range(5)]
        b = [_row(f"c{i}", "standard-calibrated", answer_point_coverage=1.0)
             for i in range(5)]
        res = paired_analysis(a, b)
        d = res["paired"]["answer_point_coverage"]
        assert d["a_mean"] == pytest.approx(0.0)
        assert d["b_mean"] == pytest.approx(1.0)
        assert d["delta"] == pytest.approx(1.0)
