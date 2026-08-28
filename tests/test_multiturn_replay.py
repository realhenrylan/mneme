"""Stage 2 多轮 rewrite 受控回放执行器的单元测试（TDD）。

覆盖（RED → GREEN）：
- 三臂 history 路由（A 全无 / B 仅生成 / C 检索+生成）与 turn-1 空历史归一；
- canonical history 链内累积（同臂前序轮次真实回答，顺序正确）;
- source 级召回计算与拒答计零、follow-up 分母排除 turn-1；
- 预注册门禁三态判定与缺结果 fail-closed；
- 密封产物 manifest 自哈希、输出目录防覆盖；
- 生产路径默认接线（不发起任何真实 LLM/检索调用）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from evaluation.schema import load_dataset, QueryType


# ── 测试夹具：临时多轮数据集（2 链：2 轮 + 3 轮） ─────────────────────

def _case_row(case_id: str, query: str, follow_up_to: str | None,
              sources: list[str]) -> dict:
    return {
        "id": case_id,
        "query": query,
        "query_type": "multi_turn",
        "language": "zh",
        "relevant_source_ids": sources,
        "relevant_chunks": [],
        "acceptable_answer_points": [],
        "should_refuse": False,
        "metadata": {"turn": 0, "follow_up_to": follow_up_to},
    }


@pytest.fixture()
def mt_dataset(tmp_path):
    rows = [
        _case_row("mt-001", "南京概况如何？", None, ["南京.docx"]),
        _case_row("mt-002", "它的最高点呢？", "mt-001", ["南京.docx"]),
        _case_row("mt-003", "苹果是什么？", None, ["苹果.docx"]),
        _case_row("mt-004", "它甜吗？", "mt-003", ["苹果.docx"]),
        _case_row("mt-005", "那价格呢？", "mt-004", ["苹果.docx"]),
    ]
    path = tmp_path / "mt.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    return path


@pytest.fixture()
def chains(mt_dataset):
    from evaluation.compare import build_conversation_chains
    cases = [c for c in load_dataset(mt_dataset)
             if c.query_type == QueryType.MULTI_TURN]
    return build_conversation_chains(cases)


# ── 假证据 / 假引擎 ──────────────────────────────────────────────

@dataclass
class FakeEvidence:
    context_source_ids: tuple[str, ...] = ("南京.docx",)
    context_k: int = 3
    candidate_count: int = 10
    refused: bool = False
    plan_fingerprint: str = "fp"

    @property
    def candidate_chunk_ids(self):
        return tuple(f"c{i}" for i in range(self.candidate_count))


class FakeEngine:
    """记录每次调用的 history 路由，并按脚本返回证据/答案。

    ``query_to_case`` 把查询文本映射回 case_id（prepare/generate 只收到
    query），使证据脚本与答案命名都能按 case 定位。
    """

    def __init__(self, evidence_by_case: dict[str, FakeEvidence],
                 query_to_case: dict[str, str]):
        self.evidence_by_case = evidence_by_case
        self.query_to_case = query_to_case
        self.prepare_calls: list[dict] = []
        self.generate_calls: list[dict] = []

    def prepare(self, *, query, history, llm_temperature=None):
        self.prepare_calls.append({"query": query, "history": history})
        return self.evidence_by_case[self.query_to_case[query]]

    def generate(self, evidence, *, history, llm_temperature=None):
        # prepare 与 generate 严格交替；以 prepare 记录数定位当前 case
        case_id = self.query_to_case[
            self.prepare_calls[len(self.generate_calls)]["query"]]
        self.generate_calls.append({"case_id": case_id, "history": history})
        return f"ans-{case_id}", "sources"


def _engine(chain, evidence_by_case) -> FakeEngine:
    return FakeEngine(evidence_by_case, {c.query: c.id for c in chain})


# ── 三臂路由 ─────────────────────────────────────────────────────

class TestArmRouting:
    def test_arm_A_routes_no_history_anywhere(self, chains):
        import evaluation.multiturn_replay as mtr
        engine = _engine(chains["mt-001"], {"mt-001": FakeEvidence(), "mt-002": FakeEvidence()})
        turns = mtr.run_arm("A", chains["mt-001"],
                            prepare_fn=engine.prepare, generate_fn=engine.generate)
        assert all(c["history"] is None for c in engine.prepare_calls)
        assert all(c["history"] is None for c in engine.generate_calls)
        assert [t.case_id for t in turns] == ["mt-001", "mt-002"]

    def test_arm_B_routes_history_generate_only(self, chains):
        import evaluation.multiturn_replay as mtr
        engine = _engine(chains["mt-001"], {"mt-001": FakeEvidence(), "mt-002": FakeEvidence()})
        mtr.run_arm("B", chains["mt-001"],
                    prepare_fn=engine.prepare, generate_fn=engine.generate)
        # turn-1 空历史归一为 None；turn-2 仅生成侧拿到 canonical history
        assert engine.prepare_calls[1]["history"] is None
        assert engine.generate_calls[1]["history"] == [("南京概况如何？", "ans-mt-001")]

    def test_arm_C_routes_history_both_sides(self, chains):
        import evaluation.multiturn_replay as mtr
        engine = _engine(chains["mt-001"], {"mt-001": FakeEvidence(), "mt-002": FakeEvidence()})
        mtr.run_arm("C", chains["mt-001"],
                    prepare_fn=engine.prepare, generate_fn=engine.generate)
        assert engine.prepare_calls[1]["history"] == [("南京概况如何？", "ans-mt-001")]
        assert engine.generate_calls[1]["history"] == [("南京概况如何？", "ans-mt-001")]

    def test_turn1_history_is_none_in_every_arm(self, chains):
        import evaluation.multiturn_replay as mtr
        for arm in mtr.ARMS:
            engine = _engine(chains["mt-001"], {"mt-001": FakeEvidence(), "mt-002": FakeEvidence()})
            mtr.run_arm(arm, chains["mt-001"],
                        prepare_fn=engine.prepare, generate_fn=engine.generate)
            assert engine.prepare_calls[0]["history"] is None
            assert engine.generate_calls[0]["history"] is None


class TestCanonicalHistory:
    def test_three_turn_chain_accumulates_in_order(self, chains):
        import evaluation.multiturn_replay as mtr
        engine = _engine(chains["mt-003"], {c: FakeEvidence() for c in ("mt-003", "mt-004", "mt-005")})
        turns = mtr.run_arm("C", chains["mt-003"],
                            prepare_fn=engine.prepare, generate_fn=engine.generate)
        third = next(t for t in turns if t.case_id == "mt-005")
        assert third.prepare_history_pairs == 2
        assert engine.prepare_calls[2]["history"] == [
            ("苹果是什么？", "ans-mt-003"), ("它甜吗？", "ans-mt-004")]

    def test_turn_outcome_records_routing_counts(self, chains):
        import evaluation.multiturn_replay as mtr
        engine = _engine(chains["mt-001"], {"mt-001": FakeEvidence(), "mt-002": FakeEvidence()})
        turns = mtr.run_arm("B", chains["mt-001"],
                            prepare_fn=engine.prepare, generate_fn=engine.generate)
        assert turns[0].prepare_history_pairs == 0
        assert turns[0].generate_history_pairs == 0
        assert turns[1].prepare_history_pairs == 0
        assert turns[1].generate_history_pairs == 1


# ── 指标 ─────────────────────────────────────────────────────────

class TestSourceRecall:
    def test_full_and_partial_intersection(self):
        import evaluation.multiturn_replay as mtr
        case_a = _case_with_sources(["南京.docx"])
        assert mtr.case_source_recall(
            FakeEvidence(context_source_ids=("南京.docx", "苹果.docx")),
            case_a) == 1.0
        case_b = _case_with_sources(["南京.docx", "苹果.docx"])
        assert mtr.case_source_recall(
            FakeEvidence(context_source_ids=("南京.docx",)), case_b) == 0.5

    def test_refused_scores_zero(self):
        import evaluation.multiturn_replay as mtr
        case = _case_with_sources(["南京.docx"])
        assert mtr.case_source_recall(
            FakeEvidence(refused=True, context_source_ids=()), case) == 0.0


def _case_with_sources(sources):
    from evaluation.schema import EvalCase, QueryType, Language
    return EvalCase(
        id="x", query="q", query_type=QueryType.MULTI_TURN,
        language=Language("zh"),
        relevant_source_ids=list(sources), relevant_chunks=[],
        acceptable_answer_points=[], should_refuse=False,
        metadata={"turn": 2, "follow_up_to": "root"},
    )


class TestFollowupDenominator:
    def test_followup_ids_exclude_chain_root(self, chains):
        import evaluation.multiturn_replay as mtr
        assert mtr.followup_ids(chains["mt-001"]) == ["mt-002"]
        assert mtr.followup_ids(chains["mt-003"]) == ["mt-004", "mt-005"]


# ── 门禁 ─────────────────────────────────────────────────────────

class TestGate:
    def _recalls(self, a_vals, c_vals, b_vals=None):
        followups = [f"mt-{i:03d}" for i in range(2, 2 + len(a_vals))]
        recalls = {
            "A": dict(zip(followups, a_vals)),
            "C": dict(zip(followups, c_vals)),
        }
        if b_vals is not None:
            recalls["B"] = dict(zip(followups, b_vals))
        return recalls, followups

    def test_gate_accepted(self):
        import evaluation.multiturn_replay as mtr
        recalls, followups = self._recalls([0.5, 0.6], [0.7, 0.8])
        gate = mtr.evaluate_gate(recalls, followups)
        assert gate["verdict"] == "STAGE2_24_ACCEPTED"
        assert gate["mean_delta"] == pytest.approx(0.2)

    def test_gate_not_proven_below_threshold(self):
        import evaluation.multiturn_replay as mtr
        recalls, followups = self._recalls([0.5, 0.6], [0.55, 0.65])
        gate = mtr.evaluate_gate(recalls, followups)
        assert gate["verdict"] == "STAGE2_24_NOT_PROVEN"

    def test_gate_regression(self):
        import evaluation.multiturn_replay as mtr
        recalls, followups = self._recalls([0.5, 0.6], [0.3, 0.4])
        gate = mtr.evaluate_gate(recalls, followups)
        assert gate["verdict"] == "STAGE2_24_REGRESSION"

    def test_single_case_regression_blocks_accept(self):
        import evaluation.multiturn_replay as mtr
        # 均值 +0.10 达标，但单例恶化 0.3 > 0.05 → 不得 ACCEPTED
        recalls, followups = self._recalls([0.5, 0.5], [0.2, 1.0])
        gate = mtr.evaluate_gate(recalls, followups)
        assert gate["verdict"] == "STAGE2_24_NOT_PROVEN"

    def test_missing_followup_fails_closed(self):
        import evaluation.multiturn_replay as mtr
        recalls, followups = self._recalls([0.5, 0.6], [0.7, 0.8])
        del recalls["A"][followups[0]]
        with pytest.raises(mtr.ReplayError):
            mtr.evaluate_gate(recalls, followups)

    def test_thresholds_echoed_from_frozen_constants(self):
        import evaluation.multiturn_replay as mtr
        recalls, followups = self._recalls([0.5], [0.7])
        gate = mtr.evaluate_gate(recalls, followups)
        assert gate["thresholds"] == {
            "min_mean_delta": mtr.GATE_MIN_MEAN_DELTA,
            "max_case_regression": mtr.GATE_MAX_CASE_REGRESSION,
            "n_followups": 1,
        }


# ── 密封产物 ─────────────────────────────────────────────────────

class TestSealedOutputs:
    def _sample_outputs(self, tmp_path):
        import evaluation.multiturn_replay as mtr
        from dataclasses import dataclass as _dc

        @dataclass
        class _Meta:
            source_name: str

        turns = [
            mtr.TurnOutcome(
                case_id="mt-002", arm="C", prepare_history_pairs=1,
                generate_history_pairs=1,
                context_source_ids=("南京.docx",), context_k=3,
                candidate_count=10, refused=False,
                plan_fingerprint="fp-c", answer="a"),
        ]
        recalls = {"A": {"mt-002": 0.5}, "C": {"mt-002": 1.0}}
        gate = mtr.evaluate_gate(recalls, ["mt-002"])
        out = tmp_path / "sealed"
        mtr.write_outputs(
            out, turns=turns, recalls=recalls, gate=gate,
            dataset_sha="d" * 64, corpus_files=["南京.docx"],
            prereg_doc="plans/STAGE2-MULTITURN-ACCEPTANCE-DESIGN-2026-08-28.md")
        return out

    def test_manifest_self_hash_verifies(self, tmp_path):
        out = self._sample_outputs(tmp_path)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        import hashlib
        expect = hashlib.sha256((json.dumps(
            body, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
            .encode("utf-8")).hexdigest()
        assert manifest["manifest_sha256"] == expect

    def test_output_dir_must_not_pre_exist(self, tmp_path):
        import evaluation.multiturn_replay as mtr
        out = tmp_path / "exists"
        out.mkdir()
        with pytest.raises(mtr.ReplayError, match="已存在"):
            mtr.write_outputs(
                out, turns=[], recalls={}, gate={},
                dataset_sha="d" * 64, corpus_files=[], prereg_doc="x")
        assert list(out.iterdir()) == []

    def test_turns_jsonl_written_with_recall(self, tmp_path):
        out = self._sample_outputs(tmp_path)
        rows = [json.loads(l) for l in
                (out / "turns.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(rows) == 1
        assert rows[0]["arm"] == "C" and rows[0]["case_id"] == "mt-002"
        assert rows[0]["source_recall"] == pytest.approx(1.0)


# ── 生产接线 ─────────────────────────────────────────────────────

class TestProductionWiring:
    def test_default_fns_resolve_to_production_path(self):
        import evaluation.multiturn_replay as mtr
        from src.rag import prepare_answer_evidence, generate_answer
        assert mtr.production_prepare() is prepare_answer_evidence
        assert mtr.production_generate() is generate_answer

    def test_unknown_arm_rejected(self, chains):
        import evaluation.multiturn_replay as mtr
        engine = _engine(chains["mt-001"], {"mt-001": FakeEvidence()})
        with pytest.raises(mtr.ReplayError, match="arm"):
            mtr.run_arm("D", chains["mt-001"],
                        prepare_fn=engine.prepare, generate_fn=engine.generate)
