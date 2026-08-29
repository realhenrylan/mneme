"""D5 拆解收益计量执行器的单因子构造测试（零 LLM）。

验证 ``evaluation/decompose_ab.py`` 的：
- OFF 臂：真实 rewrite + 零 decompose（单查询直通）；
- ON 臂：冻结 OFF 臂 rewrite（仅 decompose 真实执行）；
- 模块属性（RAG_QUERY_DECOMPOSE）finally 恢复。
"""
from __future__ import annotations

from collections import Counter

import pytest

import src.rag as rag
from evaluation.decompose_ab import _plan_arm
from evaluation.schema import EvalCase, Language, QueryType


@pytest.fixture
def fake_planning_env(monkeypatch):
    """冻结 rewrite/decompose/retrieve：记录真实调用（rewrite 冻结不影响）。"""
    calls = Counter()

    def _fake_rewrite(*args, **kwargs):
        calls["rewrite"] += 1
        return ("rewritten-q", {"changed": False})

    def _fake_decompose(*args, **kwargs):
        calls["decompose"] += 1
        return ["sub-1"]

    def _fake_retrieve(sq, *args, **kwargs):
        return ([0], [f"d0-{sq}"], [0.9])

    monkeypatch.setattr("src.rag_query_rewriter.rewrite_query_llm",
                        _fake_rewrite)
    monkeypatch.setattr("src.rag_query_decomposer.decompose_query_llm",
                        _fake_decompose)
    monkeypatch.setattr("src.rag.retrieve_hybrid_with_sources",
                        _fake_retrieve)
    return calls


def _case() -> EvalCase:
    return EvalCase(
        id="t1", query="如何设置代理？", query_type=QueryType.SINGLE_FACT,
        language=Language.ZH, relevant_chunks=[],
    )


def _bundle():
    docs = ["doc 0"]
    metas = [{"chunk_id": "c0", "chunk_index": 0, "source_id": "s1"}]
    return {"model": None, "collection": None, "bm25": None,
            "documents": docs, "metadatas": metas}


class TestPlanArmSingleFactor:
    def test_off_arm_real_rewrite_zero_decompose(self, fake_planning_env):
        """OFF：真实 rewrite 恰 1 次；decompose 零调用；直通 rewritten。"""
        plan, wall_ms = _plan_arm(_bundle(), _case(), "OFF", None)
        assert fake_planning_env["rewrite"] == 1
        assert fake_planning_env["decompose"] == 0
        assert list(plan.sub_queries) == ["rewritten-q"]
        assert wall_ms >= 0.0

    def test_on_arm_frozen_rewrite_real_decompose(self, fake_planning_env):
        """ON：decompose 仅真实 1 次；rewrite 冻结（不触发真实）；同 off rewrite。"""
        off_plan, _ = _plan_arm(_bundle(), _case(), "OFF", None)
        on_plan, on_wall = _plan_arm(
            _bundle(), _case(), "ON",
            (off_plan.rewritten_query, off_plan.rewrite_log))
        # rewrite 仍只被 OFF 臂真实调用 1 次（ON 冻结不触发 recorder）
        assert fake_planning_env["rewrite"] == 1
        assert fake_planning_env["decompose"] == 1
        assert list(on_plan.sub_queries) == ["sub-1"]
        # 两臂共享同一 rewrite（单因子 = decompose 仅）
        assert on_plan.rewritten_query == off_plan.rewritten_query
        assert on_plan.rewrite_log == off_plan.rewrite_log
        assert on_wall >= 0.0

    def test_module_state_restored_after_arms(self, fake_planning_env):
        """执行后 RAG_QUERY_DECOMPOSE 恢复原值（finally 保证）。"""
        before = rag.RAG_QUERY_DECOMPOSE
        off_plan, _ = _plan_arm(_bundle(), _case(), "OFF", None)
        on_plan, _ = _plan_arm(_bundle(), _case(), "ON", (
            off_plan.rewritten_query, off_plan.rewrite_log))
        assert rag.RAG_QUERY_DECOMPOSE == before
