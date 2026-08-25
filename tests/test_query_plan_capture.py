"""G1-S：synthetic query-plan capture 与 plan/evidence replay 的 TDD 测试。

范围约束（与 Phase 6-G1-S 授权一致）：
- 仅 synthetic fixture；全部使用本地 fake（零 LLM / 零网络 / 零真实检索）；
- 不读取/捕获 v2.0.11 query/history 文本，不触碰 frozen/revision 资产；
- capture 只有显式 output_root 才持久化，默认路径零 I/O。
"""
from __future__ import annotations

import builtins
import hashlib
import json
import math
import pickle
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import src.rag as rag
from src.domain import (
    CapturedCandidateHit,
    CapturedEvidenceReceipt,
    CapturedQueryPlan,
    StageProvenance,
)
from src.rag_query_decomposer import (
    _decompose_query_provenanced,
    decompose_query_llm,
    should_decompose,
)
from src.rag_query_rewriter import (
    _rewrite_query_provenanced,
    rewrite_query_llm,
    should_rewrite,
)

# ── synthetic fixtures（全部新建，与 v2.0.11 无关）──────────────────

DOCS = ["d0 文本", "d1 文本", "d2 文本"]
METAS = [
    {"chunk_id": "chunk_0", "source_id": "s0", "source_name": "a.md",
     "source": "a.md", "chunk_index": 0},
    {"chunk_id": "chunk_1", "source_id": "s1", "source_name": "b.md",
     "source": "b.md", "chunk_index": 0},
    {"chunk_id": "chunk_2", "source_id": "s2", "source_name": "c.md",
     "source": "c.md", "chunk_index": 0},
]
# guard 全部跳过 → 零 LLM（rewrite: 无历史；decompose: 简单中文）
SIMPLE_QUERY = "这篇论文讲了什么？"

_MOCK_ENV = {"API_KEY": "sk-test", "BASE_URL": "https://test"}


def _forbid(*args, **kwargs):
    raise AssertionError("forbidden call in G1-S test")


def _fake_retrieve(sq, model, collection, bm25, documents, metadatas, k=None):
    """确定性 fake 检索：同分候选 1、2 在 0 之前被观察到（测试同分顺序保留）。"""
    return [1, 2, 0], ["d1 文本", "d2 文本", "d0 文本"], [0.7, 0.7, 0.9]


def _fake_retrieve_weak(sq, model, collection, bm25, documents, metadatas, k=None):
    """低于拒答阈值的弱检索。"""
    return [0], ["d0 文本"], [0.01]


def _fake_retrieve_two(sq, model, collection, bm25, documents, metadatas, k=None):
    """双候选 fake（供两文档 parity 测试）。"""
    return [0, 1], ["d0 文本", "d1 文本"], [0.6, 0.4]


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════
# 对象边界（G1-S 一）：domain 对象存在且仅含稳定可序列化字段
# ═══════════════════════════════════════════════════════════════

class TestDomainObjects:
    def test_captured_query_plan_fields_are_stable(self):
        plan = CapturedQueryPlan(
            query="q", rewritten_query="rq", rewrite_log={"changed": False},
            sub_queries=["rq"],
            base_candidates=(
                CapturedCandidateHit(rank=0, chunk_id="chunk_0", score="0.9"),
            ),
            base_candidates_fingerprint="f",
            rewrite_stage=StageProvenance(
                guard_result=False, outcome="no_rewrite_needed",
                requested_model="deepseek-chat", temperature=0.0,
                max_tokens=200, timeout=15, max_retries=2, retries_used=0,
                served_version="unknown",
            ),
            decompose_stage=StageProvenance(
                guard_result=False, outcome="guard_skipped",
                requested_model="deepseek-chat", temperature=0.0,
                max_tokens=150, timeout=30, max_retries=2, retries_used=0,
                served_version="unknown",
            ),
        )
        # 全部字段可 JSON 序列化（不依赖 evaluation.QueryPlan / chunk_index）
        payload = {
            "query": plan.query,
            "rewritten_query": plan.rewritten_query,
            "rewrite_log": plan.rewrite_log,
            "sub_queries": plan.sub_queries,
            "base_candidates": [
                [h.rank, h.chunk_id, h.score] for h in plan.base_candidates
            ],
            "base_candidates_fingerprint": plan.base_candidates_fingerprint,
            "rewrite_stage": plan.rewrite_stage.__dict__,
            "decompose_stage": plan.decompose_stage.__dict__,
        }
        json.dumps(payload, ensure_ascii=False)  # 不抛异常即可序列化

    def test_captured_candidate_hit_rejects_chunk_index_semantics(self):
        """CapturedCandidateHit 没有 chunk_index 字段（稳定标识只有 chunk_id）。"""
        assert not hasattr(CapturedCandidateHit, "chunk_index")
        hit = CapturedCandidateHit(rank=0, chunk_id="chunk_0", score="0.9")
        assert list(hit.__dict__) == ["rank", "chunk_id", "score"]

    def test_captured_evidence_receipt_fields(self):
        receipt = CapturedEvidenceReceipt(
            plan_fingerprint="p", base_candidates_fingerprint="b",
            retrieval_fingerprint="r", context_sha256="c",
            candidate_chunk_ids=("chunk_0", "chunk_1"),
            context_chunk_ids=("chunk_0",),
            refused=False, refusal_reason=None,
        )
        assert receipt.candidate_chunk_ids == ("chunk_0", "chunk_1")
        assert receipt.context_chunk_ids == ("chunk_0",)

    def test_stage_provenance_defaults_to_unknown_served_version(self):
        stage = StageProvenance(
            guard_result=True, outcome="llm_rewrite",
            requested_model="deepseek-chat", temperature=0.0,
            max_tokens=200, timeout=15, max_retries=2, retries_used=1,
        )
        assert stage.served_version == "unknown"


# ═══════════════════════════════════════════════════════════════
# 两阶段 provenance + 薄包装（G1-S 四）
# ═══════════════════════════════════════════════════════════════

class TestRewriteProvenance:
    def test_thin_wrapper_delegates_exactly(self):
        """薄包装 = 以 Settings 解析值调 provenanced 实现（统一配置契约）。

        测试隔离：使用 _MOCK_ENV 的 fake 边界变量与确定性 fake
        llm_call_safe，不依赖真实 .env/凭据泄漏、不发真实网络调用。
        """
        from src.config import get_settings
        resolved = (get_settings().llm_model, get_settings().llm_temperature)
        args = ("它的作者是谁？", [("X是什么？", "X是...")], *resolved, 2)
        with mock.patch.dict("os.environ", _MOCK_ENV):
            with mock.patch(
                "src.llm_gateway.llm_call_safe",
                return_value=("DSpark的作者是谁？", SimpleNamespace(retries_used=0)),
            ):
                r1, l1 = rewrite_query_llm(
                    "它的作者是谁？", history=[("X是什么？", "X是...")],
                )
                r2, l2, stage = _rewrite_query_provenanced(*args)
        assert (r1, l1) == (r2, l2)
        assert isinstance(stage, StageProvenance)
        assert stage.served_version == "unknown"
        assert stage.max_tokens == 200
        assert stage.timeout == 15

    def test_thin_wrapper_sink_receives_stage(self):
        sink: list[StageProvenance] = []
        rewrite_query_llm(
            "它的作者是谁？", history=[("X是什么？", "X是...")],
            _provenance_sink=sink,
        )
        assert len(sink) == 1
        assert isinstance(sink[0], StageProvenance)

    def test_guard_false_outcome(self):
        _, log, stage = _rewrite_query_provenanced(
            "它的作者是谁？", None, "deepseek-chat", 0.0, 2,
        )
        assert log["reason"] == "no_rewrite_needed"
        assert stage.guard_result is False
        assert stage.outcome == "no_rewrite_needed"
        assert stage.retries_used == 0

    def test_no_api_key_outcome(self, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("BASE_URL", raising=False)
        _, log, stage = _rewrite_query_provenanced(
            "它的作者是谁？", [("X是什么？", "X是...")], "deepseek-chat", 0.0, 2,
        )
        assert log["reason"] == "no_api_key"
        assert stage.outcome == "no_api_key"

    def test_invalid_endpoint_outcome(self, monkeypatch):
        with mock.patch.dict("os.environ", _MOCK_ENV):
            with mock.patch(
                "src.rag_query_rewriter.endpoint_validation_error",
                return_value=True,
            ):
                _, log, stage = _rewrite_query_provenanced(
                    "它的作者是谁？", [("X是什么？", "X是...")],
                    "deepseek-chat", 0.0, 2,
                )
        assert log["reason"] == "invalid_endpoint"
        assert stage.outcome == "invalid_endpoint"

    def test_llm_failed_outcome(self):
        with mock.patch.dict("os.environ", _MOCK_ENV):
            with mock.patch("src.llm_gateway.llm_call_safe") as call:
                call.return_value = (None, SimpleNamespace(retries_used=2))
                _, log, stage = _rewrite_query_provenanced(
                    "它的作者是谁？", [("X是什么？", "X是...")],
                    "deepseek-chat", 0.0, 2,
                )
        assert log["reason"] == "llm_failed"
        assert stage.outcome == "llm_failed"
        assert stage.retries_used == 2

    def test_llm_rewrite_outcome(self):
        with mock.patch.dict("os.environ", _MOCK_ENV):
            with mock.patch("src.llm_gateway.llm_call_safe") as call:
                call.return_value = ("DSpark的作者是谁？",
                                     SimpleNamespace(retries_used=1))
                rewritten, log, stage = _rewrite_query_provenanced(
                    "它的作者是谁？", [("DSpark是什么？", "DSpark是...")],
                    "deepseek-chat", 0.0, 2,
                )
        assert rewritten == "DSpark的作者是谁？"
        assert log["changed"] is True
        assert log["reason"] == "llm_rewrite"
        assert stage.outcome == "llm_rewrite"
        assert stage.guard_result is True
        assert stage.retries_used == 1

    def test_llm_returned_unchanged_outcome(self):
        with mock.patch.dict("os.environ", _MOCK_ENV):
            with mock.patch("src.llm_gateway.llm_call_safe") as call:
                call.return_value = ("它的作者是谁？",
                                     SimpleNamespace(retries_used=0))
                _, log, stage = _rewrite_query_provenanced(
                    "它的作者是谁？", [("X是什么？", "X是...")],
                    "deepseek-chat", 0.0, 2,
                )
        assert log["reason"] == "llm_returned_unchanged"
        assert stage.outcome == "llm_returned_unchanged"


class TestDecomposeProvenance:
    def test_thin_wrapper_delegates_exactly(self):
        s1 = decompose_query_llm(SIMPLE_QUERY)
        s2, stage = _decompose_query_provenanced(
            SIMPLE_QUERY, "deepseek-chat", 0.0, 2,
        )
        assert s1 == s2 == [SIMPLE_QUERY]
        assert stage.guard_result is False
        assert stage.outcome == "guard_skipped"
        assert stage.max_tokens == 150
        assert stage.timeout == 30

    def test_guard_skipped_outcome(self):
        assert should_decompose(SIMPLE_QUERY) is False
        sub, stage = _decompose_query_provenanced(SIMPLE_QUERY, "deepseek-chat", 0.0, 2)
        assert sub == [SIMPLE_QUERY]
        assert stage.outcome == "guard_skipped"

    def test_no_api_key_outcome(self, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("BASE_URL", raising=False)
        sub, stage = _decompose_query_provenanced(
            "LLMs for mobility这篇文章的作者？", "deepseek-chat", 0.0, 2,
        )
        assert sub == ["LLMs for mobility这篇文章的作者？"]
        assert stage.outcome == "no_api_key"
        assert stage.guard_result is True

    def test_invalid_endpoint_outcome(self):
        with mock.patch.dict("os.environ", _MOCK_ENV):
            with mock.patch(
                "src.rag_query_decomposer.endpoint_validation_error",
                return_value=True,
            ):
                sub, stage = _decompose_query_provenanced(
                    "LLMs for mobility这篇文章的作者？", "deepseek-chat", 0.0, 2,
                )
        assert sub == ["LLMs for mobility这篇文章的作者？"]
        assert stage.outcome == "invalid_endpoint"

    def test_llm_failed_outcome(self):
        with mock.patch.dict("os.environ", _MOCK_ENV):
            with mock.patch("src.llm_gateway.llm_call_safe") as call:
                call.return_value = (None, SimpleNamespace(retries_used=1))
                sub, stage = _decompose_query_provenanced(
                    "LLMs for mobility这篇文章的作者？", "deepseek-chat", 0.0, 2,
                )
        assert sub == ["LLMs for mobility这篇文章的作者？"]
        assert stage.outcome == "llm_failed"
        assert stage.retries_used == 1

    def test_invalid_json_outcome(self):
        with mock.patch.dict("os.environ", _MOCK_ENV):
            with mock.patch("src.llm_gateway.llm_call_safe") as call:
                call.return_value = ("not json", SimpleNamespace(retries_used=0))
                sub, stage = _decompose_query_provenanced(
                    "LLMs for mobility这篇文章的作者？", "deepseek-chat", 0.0, 2,
                )
        assert sub == ["LLMs for mobility这篇文章的作者？"]
        assert stage.outcome == "invalid_json"

    def test_empty_list_json_outcome(self):
        with mock.patch.dict("os.environ", _MOCK_ENV):
            with mock.patch("src.llm_gateway.llm_call_safe") as call:
                call.return_value = ("[]", SimpleNamespace(retries_used=0))
                sub, stage = _decompose_query_provenanced(
                    "LLMs for mobility这篇文章的作者？", "deepseek-chat", 0.0, 2,
                )
        assert sub == ["LLMs for mobility这篇文章的作者？"]
        assert stage.outcome == "invalid_json"

    def test_llm_decomposed_outcome(self):
        with mock.patch.dict("os.environ", _MOCK_ENV):
            with mock.patch("src.llm_gateway.llm_call_safe") as call:
                call.return_value = ('["LLMs for mobility","作者属于什么学校？"]',
                                     SimpleNamespace(retries_used=0))
                sub, stage = _decompose_query_provenanced(
                    "LLMs for mobility这篇文章的作者？", "deepseek-chat", 0.0, 2,
                )
        assert sub == ["LLMs for mobility", "作者属于什么学校？"]
        assert stage.outcome == "llm_decomposed"


# ═══════════════════════════════════════════════════════════════
# 共享 planning helper（G1-S 二）
# ═══════════════════════════════════════════════════════════════

class TestSharedPlanningHelper:
    def test_helper_and_ordinary_branch_agree(self, monkeypatch):
        """prepare 普通分支 = helper + query_plan 分支（同一规划，指纹/证据一致）。"""
        monkeypatch.setattr(rag, "retrieve_hybrid_with_sources", _fake_retrieve)
        runtime = rag._plan_query_runtime(
            SIMPLE_QUERY, None, None, None, DOCS, METAS, history=None,
        )
        ev_plan = rag.prepare_answer_evidence(
            SIMPLE_QUERY, None, None, None, DOCS, METAS, history=None,
            query_plan=runtime,
        )
        ev_ord = rag.prepare_answer_evidence(
            SIMPLE_QUERY, None, None, None, DOCS, METAS, history=None,
        )
        assert ev_ord.plan_fingerprint == ev_plan.plan_fingerprint
        assert ev_ord.retrieval_fingerprint == ev_plan.retrieval_fingerprint
        assert ev_ord.context == ev_plan.context
        assert ev_ord.context_sha256 == ev_plan.context_sha256
        assert list(ev_ord.top_scores) == list(ev_plan.top_scores)

    def test_equal_score_observation_order_preserved(self, monkeypatch):
        """同分候选按观察顺序保留（不偷偷改成 chunk_id tie-break）。"""
        monkeypatch.setattr(rag, "retrieve_hybrid_with_sources", _fake_retrieve)
        runtime = rag._plan_query_runtime(
            SIMPLE_QUERY, None, None, None, DOCS, METAS, history=None,
        )
        assert runtime.merged == [0, 1, 2]      # 0.9 排前
        assert runtime.merged[1:] == [1, 2]     # 同分 1、2 保持观察顺序
        assert runtime.best_score[1] == 0.7
        assert runtime.best_score[2] == 0.7

    def test_helper_provenance_present_when_unpatched(self, monkeypatch):
        monkeypatch.setattr(rag, "retrieve_hybrid_with_sources", _fake_retrieve)
        runtime = rag._plan_query_runtime(
            SIMPLE_QUERY, None, None, None, DOCS, METAS, history=None,
        )
        assert runtime.rewrite_stage is not None
        assert runtime.rewrite_stage.outcome == "no_rewrite_needed"
        assert runtime.decompose_stage is not None
        assert runtime.decompose_stage.outcome == "guard_skipped"

    def test_stream_and_prepare_share_helper(self, monkeypatch):
        """两候选 fake 下流式与同步路径产出同一 context（helper 已共享）。"""
        monkeypatch.setattr(rag, "retrieve_hybrid_with_sources", _fake_retrieve_two)
        ev = rag.prepare_answer_evidence(
            SIMPLE_QUERY, None, None, None, DOCS[:2], METAS[:2], history=None,
        )
        captured = {}

        def fake_stream(q, context, history, **kwargs):
            captured["context"] = context
            yield "(mocked)"

        monkeypatch.setattr(rag, "answer_with_llm_history_stream", fake_stream)
        stream, _ = rag.answer_query_stream(
            SIMPLE_QUERY, None, None, None, DOCS[:2], METAS[:2],
            top_k_range=(3, 20),
        )
        for _ in stream:
            pass
        assert captured["context"] == ev.context

    def test_query_plan_branch_unchanged(self, monkeypatch):
        """评测注入路径（query_plan=...）零规划零检索，行为不变。"""
        class FakePlan:
            rewritten_query = "改写后问题"
            rewrite_log = {"changed": False}
            sub_queries = ["改写后问题"]
            base_candidates = {0: 0.6, 1: 0.4}

        monkeypatch.setattr(
            rag, "retrieve_hybrid_with_sources", _forbid,
        )
        monkeypatch.setattr(
            rag, "_plan_query_runtime", _forbid,
        )
        ev = rag.prepare_answer_evidence(
            SIMPLE_QUERY, None, None, None, DOCS[:2], METAS[:2],
            query_plan=FakePlan(),
        )
        assert ev.plan_fingerprint != ""
        assert list(ev.candidate_chunk_ids) == ["chunk_0", "chunk_1"]


# ═══════════════════════════════════════════════════════════════
# 默认路径零写入（G1-S 二/五）
# ═══════════════════════════════════════════════════════════════

class TestZeroWriteDefaultPaths:
    @staticmethod
    def _write_spy(monkeypatch):
        writes: list[str] = []
        real_open = builtins.open

        def spy_open(file, mode="r", *a, **k):
            if any(ch in mode for ch in ("w", "a", "x", "+")):
                writes.append(str(file))
            return real_open(file, mode, *a, **k)

        monkeypatch.setattr(builtins, "open", spy_open)
        return writes

    def test_answer_query_zero_writes_without_capability(self, monkeypatch):
        writes = self._write_spy(monkeypatch)
        monkeypatch.setattr(rag, "retrieve_hybrid_with_sources", _fake_retrieve)
        monkeypatch.setattr(
            rag, "answer_with_llm_history", lambda *a, **k: "基于文档的答案。",
        )
        answer, sources = rag.answer_query(
            SIMPLE_QUERY, None, None, None, DOCS, METAS,
        )
        assert answer == "基于文档的答案。"
        assert writes == []  # 无 capability → 零新增 I/O

    def test_answer_query_stream_zero_writes_without_capability(self, monkeypatch):
        writes = self._write_spy(monkeypatch)
        monkeypatch.setattr(rag, "retrieve_hybrid_with_sources", _fake_retrieve)

        def fake_stream(q, context, history, **kwargs):
            yield "(mocked)"

        monkeypatch.setattr(rag, "answer_with_llm_history_stream", fake_stream)
        stream, sources = rag.answer_query_stream(
            SIMPLE_QUERY, None, None, None, DOCS, METAS,
        )
        for _ in stream:
            pass
        assert writes == []  # 无 capability → 零新增 I/O


# ═══════════════════════════════════════════════════════════════
# score 规范化 / base_candidates_fingerprint（G1-S 三）
# ═══════════════════════════════════════════════════════════════

class TestScoreNormalization:
    def test_round_trip_canonical(self):
        from src import query_plan_capture as qpc
        assert qpc.normalize_score(0.7) == "0.7"
        assert qpc.validate_score_str("0.7") == 0.7
        assert qpc.validate_score_str(qpc.normalize_score(0.9)) == 0.9

    def test_rejects_non_finite(self):
        from src import query_plan_capture as qpc
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError):
                qpc.normalize_score(bad)
        for bad_str in ("nan", "inf", "-inf"):
            with pytest.raises(ValueError):
                qpc.validate_score_str(bad_str)

    def test_rejects_bool_and_non_number(self):
        from src import query_plan_capture as qpc
        with pytest.raises(ValueError):
            qpc.normalize_score(True)
        with pytest.raises(ValueError):
            qpc.normalize_score("0.7")

    def test_validate_rejects_non_canonical_strings(self):
        from src import query_plan_capture as qpc
        for bad in ("0.70", "0.7e-1", "+0.7", "abc", " 0.7"):
            with pytest.raises(ValueError):
                qpc.validate_score_str(bad)


class TestBaseCandidatesFingerprint:
    def test_order_sensitive(self):
        from src import query_plan_capture as qpc
        base = [[0, "chunk_0", "0.9"], [1, "chunk_1", "0.7"], [2, "chunk_2", "0.7"]]
        swapped = [[0, "chunk_0", "0.9"], [1, "chunk_2", "0.7"], [2, "chunk_1", "0.7"]]
        assert (qpc.compute_base_candidates_fingerprint(base)
                != qpc.compute_base_candidates_fingerprint(swapped))

    def test_deterministic(self):
        from src import query_plan_capture as qpc
        hits = [[0, "chunk_0", "0.9"], [1, "chunk_1", "0.7"]]
        assert (qpc.compute_base_candidates_fingerprint(hits)
                == qpc.compute_base_candidates_fingerprint(hits))


# ═══════════════════════════════════════════════════════════════
# capability（误用防护）+ capture + seal（G1-S 三/五/六）
# ═══════════════════════════════════════════════════════════════

def _synthetic_chunks(tmp_path, docs=DOCS, metas=METAS) -> Path:
    """与 metadatas 一一对应的 synthetic chunks JSONL（chunks contract 输入）。"""
    path = tmp_path / "synthetic-chunks.jsonl"
    lines = [
        json.dumps(
            {"chunk_id": meta["chunk_id"],
             "text": docs[i] if i < len(docs) else ""},
            ensure_ascii=False,
        )
        for i, meta in enumerate(metas)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _replay_cap(ctx):
    """replay 需要 issuer 签发的 capability（context 绑定输出根与 chunks）。"""
    from src import query_plan_capture as qpc
    return qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)


def _do_capture(tmp_path, monkeypatch, *, docs=DOCS, metas=METAS,
                retrieve=_fake_retrieve, chunks_path=None, query=SIMPLE_QUERY,
                history=None, root_name="capture"):
    """capture 一次 synthetic 规划（fake 检索 + guard 跳过 LLM），返回 (ctx, runtime, evidence)。"""
    monkeypatch.setattr(rag, "retrieve_hybrid_with_sources", retrieve)
    runtime = rag._plan_query_runtime(
        query, None, None, None, docs, metas, history=history,
    )
    evidence = rag.prepare_answer_evidence(
        query, None, None, None, docs, metas, history=history,
        query_plan=runtime,
    )
    if chunks_path is None:
        chunks_path = _synthetic_chunks(tmp_path, docs, metas)
    from src import query_plan_capture as qpc
    ctx = qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(
        tmp_path / root_name, chunks_path,
    )
    qpc.capture_synthetic_plan(
        runtime, evidence,
        qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx),
        metas, history=history,
    )
    return ctx, runtime, evidence


class TestSyntheticCapability:
    def test_plain_scopes_rejected(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, runtime, evidence = _do_capture(tmp_path, monkeypatch)
        for scope in ({"mode": "synthetic_only"}, "synthetic_only", object()):
            with pytest.raises(ValueError, match="SyntheticCaptureCapability"):
                qpc.capture_synthetic_plan(runtime, evidence, scope, METAS)

    def test_capability_not_serializable(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
        with pytest.raises(TypeError):
            json.dumps(cap)
        with pytest.raises(TypeError):
            pickle.dumps(cap)

    def test_issuer_creates_valid_capability(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
        assert isinstance(cap, qpc.SyntheticCaptureCapability)

    def test_capture_requires_metadatas(self, tmp_path, monkeypatch):
        """缺 metadatas → TypeError（不存在默认持久化路径，签名 fail-closed）。"""
        from src import query_plan_capture as qpc
        ctx, runtime, evidence = _do_capture(tmp_path, monkeypatch)
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
        with pytest.raises(TypeError):
            qpc.capture_synthetic_plan(runtime, evidence, cap)


class TestCaptureSeal:
    def test_capture_writes_lf_only(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        for name in (qpc.CAPTURE_FILE_NAME, qpc.MANIFEST_FILE_NAME):
            data = (ctx.output_root / name).read_bytes()
            assert b"\r" not in data, f"{name} contains CR"
            assert data.endswith(b"\n"), f"{name} missing trailing LF"

    def test_line_sha256_excludes_self(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        row = json.loads((ctx.output_root / qpc.CAPTURE_FILE_NAME).read_text(encoding="utf-8"))
        without = {k: v for k, v in row.items() if k != "line_sha256"}
        assert qpc._sha256_text(qpc._canonical_row_json(without)) == row["line_sha256"]

    def test_manifest_self_hash_and_closures(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        manifest = json.loads((ctx.output_root / qpc.MANIFEST_FILE_NAME).read_text(encoding="utf-8"))
        recorded = manifest.pop("manifest_sha256")
        assert qpc._sha256_text(qpc._canonical_manifest_json(manifest)) == recorded

        jsonl_bytes = (ctx.output_root / qpc.CAPTURE_FILE_NAME).read_bytes()
        assert manifest["file_bytes_sha256"] == hashlib.sha256(jsonl_bytes).hexdigest()
        lines = jsonl_bytes.splitlines()
        assert manifest["line_count"] == len(lines) == 1
        rows = [json.loads(line.decode("utf-8")) for line in lines]
        assert manifest["line_hashes"] == [
            qpc._sha256_text(qpc._canonical_row_json(
                {k: v for k, v in row.items() if k != "line_sha256"}))
            for row in rows
        ]
        row = rows[0]
        receipt_sha = qpc._sha256_text(qpc._canonical_row_json(row["evidence"]))
        assert manifest["outputs_sha256"] == qpc._sha256_text(
            json.dumps([receipt_sha], ensure_ascii=False, separators=(",", ":")),
        )

    def test_capture_metadata_and_no_response_fields(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, runtime, _ = _do_capture(tmp_path, monkeypatch)
        row = json.loads((ctx.output_root / qpc.CAPTURE_FILE_NAME).read_text(encoding="utf-8"))
        assert row["mode"] == "synthetic_only"
        assert row["schema_version"] == qpc.CAPTURE_SCHEMA_VERSION
        assert row["run_id"] == "synthetic-run"
        assert row["turn_id"] == "turn-1"
        assert row["plan"]["query"] == SIMPLE_QUERY
        assert "response" not in json.dumps(row, ensure_ascii=False).lower()
        # 稳定候选：rank/chunk_id/score，无 chunk_index
        hit = row["plan"]["base_candidates"][0]
        assert list(hit) == [0, "chunk_0", "0.9"]

    def test_capture_deterministic_across_directories(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx_a, _, _ = _do_capture(tmp_path, monkeypatch, root_name="a")
        ctx_b, _, _ = _do_capture(tmp_path, monkeypatch, root_name="b")
        for name in (qpc.CAPTURE_FILE_NAME, qpc.MANIFEST_FILE_NAME):
            assert (ctx_a.output_root / name).read_bytes() == (ctx_b.output_root / name).read_bytes(), name

    def test_capture_rejects_existing_output_root(self, tmp_path, monkeypatch):
        """输出根必须是新建目标：已 seal 的目录再次 capture 拒绝。"""
        from src import query_plan_capture as qpc
        ctx, runtime, evidence = _do_capture(tmp_path, monkeypatch)
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
        with pytest.raises(ValueError, match="already exists|new target"):
            qpc.capture_synthetic_plan(runtime, evidence, cap, METAS)

    def test_capture_rejects_missing_provenance(self, tmp_path, monkeypatch):
        """planner 被桩拦截（stage 缺失）→ capture fail-closed。"""
        from src import query_plan_capture as qpc
        monkeypatch.setattr(rag, "retrieve_hybrid_with_sources", _fake_retrieve)
        monkeypatch.setattr(
            "src.rag_query_decomposer.decompose_query_llm",
            lambda q, *a, **k: ["sub"],
        )
        runtime = rag._plan_query_runtime(
            SIMPLE_QUERY, None, None, None, DOCS, METAS, history=None,
        )
        assert runtime.decompose_stage is None
        evidence = rag.prepare_answer_evidence(
            SIMPLE_QUERY, None, None, None, DOCS, METAS, history=None,
            query_plan=runtime,
        )
        chunks = _synthetic_chunks(tmp_path)
        ctx = qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(
            tmp_path / "capture", chunks,
        )
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
        with pytest.raises(ValueError, match="provenance unavailable"):
            qpc.capture_synthetic_plan(runtime, evidence, cap, METAS)

    def test_capture_rejects_reranker_non_none(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, runtime, evidence = _do_capture(tmp_path, monkeypatch)
        monkeypatch.setattr(rag, "RAG_RERANKER_MODE", "cross-encoder")
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
        with pytest.raises(ValueError, match="RAG_RERANKER_MODE"):
            qpc.capture_synthetic_plan(runtime, evidence, cap, METAS)

    def test_capture_io_limited_to_output_root_and_chunks(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        chunks = tmp_path / "chunks.jsonl"
        chunks.write_text(
            '{"chunk_id": "chunk_0", "text": "d0"}\n'
            '{"chunk_id": "chunk_1", "text": "d1"}\n'
            '{"chunk_id": "chunk_2", "text": "d2"}\n',
            encoding="utf-8",
        )
        touched: list[str] = []
        real_open = builtins.open

        def spy_open(file, mode="r", *a, **k):
            touched.append(str(file))
            return real_open(file, mode, *a, **k)

        monkeypatch.setattr(builtins, "open", spy_open)
        ctx, _, _ = _do_capture(tmp_path, monkeypatch, chunks_path=chunks)
        root_text = str(ctx.output_root)
        for path in touched:
            assert path.startswith(root_text) or Path(path) == chunks, f"unexpected I/O: {path}"
        assert any(path.endswith(qpc.CAPTURE_FILE_NAME) for path in touched)


# ═══════════════════════════════════════════════════════════════
# replay（G1-S 四：零 LLM / receipt 复算 / 硬阻断 / provenance 告警）
# ═══════════════════════════════════════════════════════════════

class TestReplay:
    def test_replay_zero_llm_zero_retrieval_receipt_all_match(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, _, evidence = _do_capture(tmp_path, monkeypatch)
        with mock.patch("src.llm_gateway.llm_call_safe", _forbid), \
             mock.patch("src.llm_gateway.llm_call", _forbid), \
             mock.patch.object(rag, "answer_with_llm_history", _forbid), \
             mock.patch.object(rag, "answer_with_llm_history_stream", _forbid), \
             mock.patch.object(rag, "retrieve_hybrid_with_sources", _forbid), \
             mock.patch("src.rag_query_rewriter.rewrite_query_llm", _forbid), \
             mock.patch("src.rag_query_decomposer.decompose_query_llm", _forbid):
            evidences = qpc.replay_synthetic_plan(_replay_cap(ctx), None, None, None, DOCS, METAS)
        assert len(evidences) == 1
        replayed = evidences[0]
        assert replayed.plan_fingerprint == evidence.plan_fingerprint
        assert replayed.retrieval_fingerprint == evidence.retrieval_fingerprint
        assert replayed.context_sha256 == evidence.context_sha256
        assert replayed.context == evidence.context
        assert list(replayed.candidate_chunk_ids) == list(evidence.candidate_chunk_ids)
        assert list(replayed.context_chunk_ids) == list(evidence.context_chunk_ids)
        assert replayed.refused == evidence.refused
        assert replayed.refusal_reason == evidence.refusal_reason

    def test_replay_preserves_captured_equal_score_rank(self, tmp_path, monkeypatch):
        """同分候选（chunk_1/chunk_2）按捕获观察顺序回放。"""
        from src import query_plan_capture as qpc
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        evidences = qpc.replay_synthetic_plan(_replay_cap(ctx), None, None, None, DOCS, METAS)
        assert list(evidences[0].candidate_chunk_ids) == [
            "chunk_0", "chunk_1", "chunk_2",
        ]
        assert list(evidences[0].context_chunk_ids) == [
            "chunk_0", "chunk_1", "chunk_2",
        ]

    def test_replay_tampered_line_sha256_rejected(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        jsonl = ctx.output_root / qpc.CAPTURE_FILE_NAME
        text = jsonl.read_text(encoding="utf-8")
        text = text.replace('"这篇论文讲了什么？"', '"被篡改的问题"', 1)
        with open(jsonl, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        with pytest.raises(ValueError, match="line_sha256"):
            qpc.replay_synthetic_plan(_replay_cap(ctx), None, None, None, DOCS, METAS)

    def test_replay_missing_chunk_id_rejected(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        bad_metas = [dict(m) for m in METAS]
        bad_metas[1].pop("chunk_id")
        with pytest.raises(ValueError, match="chunk_id"):
            qpc.replay_synthetic_plan(_replay_cap(ctx), None, None, None, DOCS, bad_metas)

    def test_replay_duplicate_chunk_id_rejected(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        bad_metas = [dict(m) for m in METAS]
        bad_metas[1]["chunk_id"] = "chunk_0"
        with pytest.raises(ValueError, match="duplicate chunk_id"):
            qpc.replay_synthetic_plan(_replay_cap(ctx), None, None, None, DOCS, bad_metas)

    def _crafted_row(self, tmp_path, monkeypatch, mutate):
        """capture 后加载行 → 变更 → 重新 seal 到独立目录（白盒篡改测试）。"""
        from src import query_plan_capture as qpc
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        row = json.loads((ctx.output_root / qpc.CAPTURE_FILE_NAME).read_text(encoding="utf-8"))
        mutate(row)
        crafted = tmp_path / "crafted"
        qpc._write_sealed(crafted, [row], "synthetic-run", "turn-1")
        return qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(crafted, ctx.chunks_path)

    def test_replay_non_contiguous_rank_rejected(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        crafted = self._crafted_row(
            tmp_path, monkeypatch, lambda row: row["plan"]["base_candidates"].__setitem__(0, [5, "chunk_0", "0.9"]),
        )
        with pytest.raises(ValueError, match="non-contiguous rank"):
            qpc.replay_synthetic_plan(_replay_cap(crafted), None, None, None, DOCS, METAS)

    def test_replay_non_canonical_score_rejected(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        crafted = self._crafted_row(
            tmp_path, monkeypatch, lambda row: row["plan"]["base_candidates"][1].__setitem__(2, "0.70"),
        )
        with pytest.raises(ValueError, match="non-canonical score string"):
            qpc.replay_synthetic_plan(_replay_cap(crafted), None, None, None, DOCS, METAS)

    def test_replay_candidate_fingerprint_mismatch_rejected(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        crafted = self._crafted_row(
            tmp_path, monkeypatch, lambda row: row["plan"]["base_candidates"][1].__setitem__(2, "0.8"),
        )
        with pytest.raises(ValueError, match="base_candidates_fingerprint mismatch"):
            qpc.replay_synthetic_plan(_replay_cap(crafted), None, None, None, DOCS, METAS)

    def test_replay_schema_version_drift_rejected(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        crafted = self._crafted_row(
            tmp_path, monkeypatch, lambda row: row.__setitem__("schema_version", 999),
        )
        with pytest.raises(ValueError, match="schema_version"):
            qpc.replay_synthetic_plan(_replay_cap(crafted), None, None, None, DOCS, METAS)

    def test_replay_reranker_non_none_blocked(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        monkeypatch.setattr(rag, "RAG_RERANKER_MODE", "cross-encoder")
        with pytest.raises(ValueError, match="RAG_RERANKER_MODE"):
            qpc.replay_synthetic_plan(_replay_cap(ctx), None, None, None, DOCS, METAS)

    def test_replay_selector_contract_drift_blocked(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        monkeypatch.setattr(rag, "SELECTOR_MAX_PER_SOURCE", 5)
        with pytest.raises(ValueError, match="selector_max_per_source"):
            qpc.replay_synthetic_plan(_replay_cap(ctx), None, None, None, DOCS, METAS)

    def test_replay_remote_limit_drift_blocked(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        monkeypatch.setenv("MNEME_MAX_REMOTE_CONTEXT_CHARS", "70000")
        with pytest.raises(ValueError, match="remote_context_limit"):
            qpc.replay_synthetic_plan(_replay_cap(ctx), None, None, None, DOCS, METAS)

    def test_replay_engine_semver_drift_blocked(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        monkeypatch.setattr(qpc, "REPLAY_ENGINE_SEMVER", "g1s-replay-engine-9.9")
        with pytest.raises(ValueError, match="replay_engine_semver"):
            qpc.replay_synthetic_plan(_replay_cap(ctx), None, None, None, DOCS, METAS)

    def test_replay_provenance_mismatch_warns_only(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        monkeypatch.setattr("src.rag_query_rewriter.REWRITE_PROMPT", "CHANGED PROMPT")
        with pytest.warns(UserWarning, match="provenance drift"):
            evidences = qpc.replay_synthetic_plan(_replay_cap(ctx), None, None, None, DOCS, METAS)
        assert len(evidences) == 1

    def test_replay_chunks_contract(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        chunks = tmp_path / "chunks.jsonl"
        chunks.write_text(
            '{"chunk_id": "chunk_0", "text": "d0"}\n'
            '{"chunk_id": "chunk_1", "text": "d1"}\n'
            '{"chunk_id": "chunk_2", "text": "d2"}\n',
            encoding="utf-8",
        )
        ctx, _, _ = _do_capture(tmp_path, monkeypatch, chunks_path=chunks)
        evidences = qpc.replay_synthetic_plan(
            _replay_cap(ctx), None, None, None, DOCS, METAS,
        )
        assert len(evidences) == 1
        chunks.write_text('{"chunk_id": "chunk_0", "text": "TAMPERED"}\n',
                          encoding="utf-8")
        with pytest.raises(ValueError, match="chunks"):
            qpc.replay_synthetic_plan(
                _replay_cap(ctx), None, None, None, DOCS, METAS,
            )

    def test_replay_receipt_field_mismatch_rejected(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        crafted = self._crafted_row(
            tmp_path, monkeypatch,
            lambda row: row["evidence"].__setitem__("plan_fingerprint", "deadbeef"),
        )
        with pytest.raises(ValueError, match="receipt mismatch"):
            qpc.replay_synthetic_plan(_replay_cap(crafted), None, None, None, DOCS, METAS)

    def test_replay_refused_roundtrip(self, tmp_path, monkeypatch):
        from src import query_plan_capture as qpc
        monkeypatch.delenv("RAG_REFUSAL_THRESHOLD", raising=False)
        ctx, _, evidence = _do_capture(
            tmp_path, monkeypatch, retrieve=_fake_retrieve_weak,
        )
        assert evidence.refused is True
        evidences = qpc.replay_synthetic_plan(_replay_cap(ctx), None, None, None, DOCS, METAS)
        assert len(evidences) == 1
        assert evidences[0].refused is True
        assert evidences[0].refusal_reason == evidence.refusal_reason


# ═══════════════════════════════════════════════════════════════
# 隔离：capture 模块不引用 frozen/revision 路径（G1-S 五）
# ═══════════════════════════════════════════════════════════════

class TestNoFrozenTouch:
    def test_capture_module_has_no_frozen_paths(self):
        from src import query_plan_capture as qpc
        source = Path(qpc.__file__).read_text(encoding="utf-8")
        for forbidden in ("evaluation/datasets", "revisions", "v2.0.11"):
            assert forbidden not in source

    def test_capture_fixtures_are_synthetic_only(self, tmp_path, monkeypatch):
        """capture 全流程 I/O 只落在显式 output_root / chunks_path（synthetic fixture）。"""
        from src import query_plan_capture as qpc
        chunks = tmp_path / "synthetic-chunks.jsonl"
        chunks.write_text(
            '{"chunk_id": "chunk_0", "text": "synthetic"}\n'
            '{"chunk_id": "chunk_1", "text": "synthetic"}\n'
            '{"chunk_id": "chunk_2", "text": "synthetic"}\n',
            encoding="utf-8",
        )
        touched: list[str] = []
        real_open = builtins.open

        def spy_open(file, mode="r", *a, **k):
            touched.append(str(file))
            return real_open(file, mode, *a, **k)

        monkeypatch.setattr(builtins, "open", spy_open)
        ctx, _, _ = _do_capture(tmp_path, monkeypatch, chunks_path=chunks)
        qpc.replay_synthetic_plan(
            _replay_cap(ctx), None, None, None, DOCS, METAS,
        )
        allowed_root = str(ctx.output_root)
        for path in touched:
            assert path.startswith(allowed_root) or Path(path) == chunks, path
