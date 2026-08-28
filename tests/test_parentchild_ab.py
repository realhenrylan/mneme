"""2.2 parent-child 效果验收执行器的单元测试（TDD）。

覆盖（RED → GREEN）：
- 目标集过滤：剔除 multi_turn / should_refuse / 无匹配真值；
- 双臂共享同一 QueryPlan（对象同一性）且扩展开关按臂切换、finally 恢复；
- chunk 级 context recall 计算（拒答计零）；
- round-3 预注册修订：containment-aware 真值匹配（id 命中或真值文本空白
  归一后被任一 context 块文本包含；空文本真值不适用；长度不一致 fail-closed）；
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
        on, off = pca.run_case_pair(case, plan, arms, chunk_text_by_id={})
        assert arms.calls[0][0] == "ON" and arms.calls[1][0] == "OFF"
        assert arms.calls[0][1] is plan and arms.calls[1][1] is plan
        assert on.arm == "ON" and off.arm == "OFF"

    def test_outcome_carries_context_and_truth(self):
        import evaluation.parentchild_ab as pca
        case = SimpleNamespace(id="s1", query="q")
        arms = FakeArms(FakeEvidence(context_chunk_ids=("c1", "c2")))
        texts = {"c1": "text-c1", "c2": "text-c2", "c3": "text-c3"}
        on, off = pca.run_case_pair(
            case, SimpleNamespace(), arms, truth={"c1", "c3"},
            chunk_text_by_id=texts)
        assert on.context_chunk_ids == ("c1", "c2")
        assert on.truth_chunk_ids == ("c1", "c3")
        # round-3：文本按 chunk_id 从同一索引快照反查，与 id 元组对齐
        assert on.context_chunk_texts == ("text-c1", "text-c2")
        assert on.truth_chunk_texts == ("text-c1", "text-c3")


# ── 指标与门禁 ───────────────────────────────────────────────────

class TestRecallAndGate:
    def test_chunk_recall_partial(self):
        import evaluation.parentchild_ab as pca
        outcome = SimpleNamespace(
            case_id="s1",
            context_chunk_ids=("c1", "c2"), context_chunk_texts=("t-c1", "t-c2"),
            truth_chunk_ids=("c1", "c3"), truth_chunk_texts=("t-c1", "t-c3"),
            refused=False)
        assert pca.chunk_context_recall(outcome) == pytest.approx(0.5)

    def test_refused_scores_zero(self):
        import evaluation.parentchild_ab as pca
        outcome = SimpleNamespace(
            case_id="s1", context_chunk_ids=(), context_chunk_texts=(),
            truth_chunk_ids=("c1",), truth_chunk_texts=("t-c1",), refused=True)
        assert pca.chunk_context_recall(outcome) == 0.0


class TestContainmentAwareRecall:
    """round-3 预注册修订：containment-aware 真值匹配（owner 2026-08-28 批准）。

    修仪器非调阈值：parent 替换（设计行为）后 child id 不在场，但真值文本
    完整包含于在场 parent 文本时必须计覆盖；真位移（文本也不在场）仍计 0。
    """

    def test_truth_text_contained_in_context_counts_as_covered(self):
        import evaluation.parentchild_ab as pca
        outcome = SimpleNamespace(
            case_id="en-017",
            context_chunk_ids=("chunk_13", "chunk_14"),
            context_chunk_texts=("header 真值证据全文 tail", "other"),
            truth_chunk_ids=("chunk_13", "chunk_15"),
            truth_chunk_texts=("header 真值证据全文 tail", "真值证据全文"),
            refused=False)
        # 13 按 id 命中；15 文本包含于 13（parent 替换）→ 双覆盖
        assert pca.chunk_context_recall(outcome) == 1.0

    def test_true_displacement_still_scores_zero(self):
        import evaluation.parentchild_ab as pca
        outcome = SimpleNamespace(
            case_id="mixed-009",
            context_chunk_ids=("c9",), context_chunk_texts=("无关内容",),
            truth_chunk_ids=("c1",), truth_chunk_texts=("独有证据文本",),
            refused=False)
        # 文本也不在场 = 真位移，containment 不得把丢失洗成覆盖
        assert pca.chunk_context_recall(outcome) == 0.0

    def test_mixed_id_and_containment(self):
        import evaluation.parentchild_ab as pca
        outcome = SimpleNamespace(
            case_id="s1",
            context_chunk_ids=("c1", "c9"),
            context_chunk_texts=("t-one", "wrap 其他 tail"),
            truth_chunk_ids=("c1", "c15"),
            truth_chunk_texts=("t-one", "X中段Y"),
            refused=False)
        # c1 按 id 命中；c15 id 与文本均不在场 → 半覆盖
        assert pca.chunk_context_recall(outcome) == pytest.approx(0.5)

    def test_empty_truth_text_not_trivially_covered(self):
        import evaluation.parentchild_ab as pca
        outcome = SimpleNamespace(
            case_id="s1",
            context_chunk_ids=("c9",), context_chunk_texts=("anything",),
            truth_chunk_ids=("c7",), truth_chunk_texts=("",),
            refused=False)
        # 空串是任何串的子串，预注册定义显式排除（否则恒真）
        assert pca.chunk_context_recall(outcome) == 0.0

    def test_whitespace_normalization(self):
        import evaluation.parentchild_ab as pca
        outcome = SimpleNamespace(
            case_id="s1",
            context_chunk_ids=("c9",),
            context_chunk_texts=("前文\n第一段  续行\t后文",),
            truth_chunk_ids=("c1",), truth_chunk_texts=("第一段 续行",),
            refused=False)
        # 连续空白折叠为单空格：parent 拼接/换行差异不破坏包含判定
        assert pca.chunk_context_recall(outcome) == 1.0

    def test_truth_id_text_length_mismatch_fails_closed(self):
        import evaluation.parentchild_ab as pca
        outcome = SimpleNamespace(
            case_id="s1",
            context_chunk_ids=("c1",), context_chunk_texts=("t",),
            truth_chunk_ids=("c1", "c2"), truth_chunk_texts=("t1",),
            refused=False)
        with pytest.raises(pca.GateError):
            pca.chunk_context_recall(outcome)

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
            context_chunk_texts=("text-c1",),
            truth_chunk_ids=("c1", "c2"), truth_chunk_texts=("text-c1", "text-c2"),
            context_k=1, refused=False,
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
        import evaluation.parentchild_ab as pca
        out = self._write(tmp_path)
        import hashlib
        rows = [json.loads(l) for l in
                (out / "outcomes.jsonl").read_text(encoding="utf-8").splitlines()
                if l.strip()]
        assert rows[0]["chunk_context_recall"] == pytest.approx(0.5)
        # round-3：文本随密封产物落盘，供 containment 口径复核
        assert rows[0]["context_chunk_texts"] == ["text-c1"]
        assert rows[0]["truth_chunk_texts"] == ["text-c1", "text-c2"]
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["metric_version"] == pca.METRIC_VERSION
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
