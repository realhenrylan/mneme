"""2.2 parent-child 效果验收执行器的单元测试（TDD）。

覆盖（RED → GREEN）：
- 目标集过滤：剔除 multi_turn / should_refuse / 无匹配真值；
- 双臂共享同一 QueryPlan（对象同一性）且扩展开关按臂切换、finally 恢复；
- chunk 级 context recall 计算（拒答计零）；
- 预注册门禁三态与缺结果 fail-closed；
- 密封产物 manifest 自哈希、输出目录防覆盖。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from evaluation.schema import load_dataset


# ── 夹具 ─────────────────────────────────────────────────────────

@dataclass
class FakeEvidence:
    context_chunk_ids: tuple[str, ...] = ("c1", "c2")
    context_k: int = 2
    refused: bool = False
    plan_fingerprint: str = "fp"


def _case_row(case_id, query_type="single_fact", should_refuse=False):
    return {
        "id": case_id, "query": f"q-{case_id}", "query_type": query_type,
        "language": "zh", "relevant_source_ids": ["A.docx"],
        "relevant_chunks": [{"source_id": "A.docx",
                             "chunk_text_snippet": "s", "page": None,
                             "section": None}] if query_type != "no_answer"
        else [],
        "acceptable_answer_points": [], "should_refuse": should_refuse,
        "metadata": {},
    }


@pytest.fixture()
def dataset(tmp_path):
    rows = [
        _case_row("s1"), _case_row("s2"),
        _case_row("m1", query_type="multi_turn"),
        _case_row("n1", query_type="no_answer", should_refuse=True),
    ]
    path = tmp_path / "ds.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    return path


class FakeArms:
    """记录每次调用的臂与扩展开关值；plan 对象透传以验证共享。"""

    def __init__(self, evidence: FakeEvidence):
        self.evidence = evidence
        self.calls: list[tuple[str, object]] = []

    def __call__(self, arm, query, plan):
        self.calls.append((arm, plan))
        return self.evidence


# ── 目标集与真值 ─────────────────────────────────────────────────

class TestTargetSet:
    def test_filter_excludes_multi_turn_refused_and_empty_truth(self, dataset):
        import evaluation.parentchild_ab as pca
        cases = load_dataset(dataset)
        truth = {"s1": {"c1"}, "s2": set(), "m1": {"c9"},
                 "n1": {"c1"}}
        target = pca.select_target_cases(cases, truth)
        assert [c.id for c in target] == ["s1"]

    def test_truth_grouping_by_case(self):
        import evaluation.parentchild_ab as pca
        entries = [
            SimpleNamespace(case_id="s1", matched_chunk_ids=["c1", "c2"]),
            SimpleNamespace(case_id="s1", matched_chunk_ids=["c2"]),
            SimpleNamespace(case_id="s2", matched_chunk_ids=[]),
        ]
        truth = pca.truth_by_case(entries)
        assert truth["s1"] == {"c1", "c2"}
        assert truth["s2"] == set()


# ── 双臂执行 ─────────────────────────────────────────────────────

class TestRunCasePair:
    def test_both_arms_share_same_plan_object(self):
        import evaluation.parentchild_ab as pca
        plan = SimpleNamespace(rewritten_query="q")
        arms = FakeArms(FakeEvidence())
        case = SimpleNamespace(id="s1", query="q")
        on, off = pca.run_case_pair(case, plan, arms)
        assert arms.calls[0][0] == "ON" and arms.calls[1][0] == "OFF"
        assert arms.calls[0][1] is plan and arms.calls[1][1] is plan
        assert on.arm == "ON" and off.arm == "OFF"

    def test_outcome_carries_context_and_truth(self):
        import evaluation.parentchild_ab as pca
        case = SimpleNamespace(id="s1", query="q")
        arms = FakeArms(FakeEvidence(context_chunk_ids=("c1", "c2")))
        on, off = pca.run_case_pair(
            case, SimpleNamespace(), arms, truth={"c1", "c3"})
        assert on.context_chunk_ids == ("c1", "c2")
        assert on.truth_chunk_ids == ("c1", "c3")


# ── 指标与门禁 ───────────────────────────────────────────────────

class TestRecallAndGate:
    def test_chunk_recall_partial(self):
        import evaluation.parentchild_ab as pca
        outcome = SimpleNamespace(
            context_chunk_ids=("c1", "c2"), truth_chunk_ids=("c1", "c3"),
            refused=False)
        assert pca.chunk_context_recall(outcome) == pytest.approx(0.5)

    def test_refused_scores_zero(self):
        import evaluation.parentchild_ab as pca
        outcome = SimpleNamespace(
            context_chunk_ids=(), truth_chunk_ids=("c1",), refused=True)
        assert pca.chunk_context_recall(outcome) == 0.0

    def _recalls(self, off_vals, on_vals):
        ids = [f"s{i}" for i in range(1, len(off_vals) + 1)]
        return {"OFF": dict(zip(ids, off_vals)),
                "ON": dict(zip(ids, on_vals))}, ids

    def test_gate_accepted(self):
        import evaluation.parentchild_ab as pca
        recalls, ids = self._recalls([0.5, 0.5], [0.6, 0.6])
        gate = pca.evaluate_gate(recalls, ids)
        assert gate["verdict"] == "STAGE2_22_ACCEPTED"
        assert gate["mean_delta"] == pytest.approx(0.1)

    def test_gate_not_proven(self):
        import evaluation.parentchild_ab as pca
        recalls, ids = self._recalls([0.5, 0.5], [0.52, 0.52])
        assert pca.evaluate_gate(recalls, ids)["verdict"] == \
            "STAGE2_22_NOT_PROVEN"

    def test_gate_regression(self):
        import evaluation.parentchild_ab as pca
        recalls, ids = self._recalls([0.5, 0.5], [0.3, 0.4])
        assert pca.evaluate_gate(recalls, ids)["verdict"] == \
            "STAGE2_22_REGRESSION"

    def test_single_case_regression_blocks_accept(self):
        import evaluation.parentchild_ab as pca
        # 均值 +0.10 达标但单例恶化 0.2 → 不得 ACCEPTED
        recalls, ids = self._recalls([0.5, 0.5], [0.3, 0.9])
        assert pca.evaluate_gate(recalls, ids)["verdict"] == \
            "STAGE2_22_NOT_PROVEN"

    def test_missing_case_fails_closed(self):
        import evaluation.parentchild_ab as pca
        recalls, ids = self._recalls([0.5, 0.5], [0.6, 0.6])
        del recalls["ON"][ids[0]]
        with pytest.raises(pca.GateError):
            pca.evaluate_gate(recalls, ids)

    def test_thresholds_echoed(self):
        import evaluation.parentchild_ab as pca
        recalls, ids = self._recalls([0.5], [0.6])
        gate = pca.evaluate_gate(recalls, ids)
        assert gate["thresholds"]["min_mean_delta"] == pca.GATE_MIN_MEAN_DELTA
        assert gate["thresholds"]["n_cases"] == 1


# ── 密封产物 ─────────────────────────────────────────────────────

class TestSealedOutputs:
    def _write(self, tmp_path):
        import evaluation.parentchild_ab as pca
        rows = [pca.CaseOutcome(
            case_id="s1", arm="ON", context_chunk_ids=("c1",),
            truth_chunk_ids=("c1", "c2"), context_k=1, refused=False,
            plan_fingerprint="fp")]
        recalls = {"OFF": {"s1": 0.0}, "ON": {"s1": 0.5}}
        gate = pca.evaluate_gate(recalls, ["s1"])
        out = tmp_path / "sealed"
        pca.write_outputs(
            out, outcomes=rows, recalls=recalls, gate=gate,
            dataset_sha="d" * 64, corpus_files=["A.docx"],
            prereg_doc="plans/STAGE2-PART2-DESIGN-2026-08-28.md")
        return out

    def test_manifest_self_hash_verifies(self, tmp_path):
        out = self._write(tmp_path)
        import hashlib
        rows = [json.loads(l) for l in
                (out / "outcomes.jsonl").read_text(encoding="utf-8").splitlines()
                if l.strip()]
        assert rows[0]["chunk_context_recall"] == pytest.approx(0.5)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        expect = hashlib.sha256((json.dumps(
            body, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
            .encode("utf-8")).hexdigest()
        assert manifest["manifest_sha256"] == expect

    def test_output_dir_must_not_pre_exist(self, tmp_path):
        import evaluation.parentchild_ab as pca
        out = tmp_path / "exists"
        out.mkdir()
        with pytest.raises(pca.GateError, match="已存在"):
            pca.write_outputs(
                out, outcomes=[], recalls={}, gate={},
                dataset_sha="d" * 64, corpus_files=[], prereg_doc="x")
