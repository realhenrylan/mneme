"""D5 拆解开关（RAG_QUERY_DECOMPOSE）测试（3.1 收尾 · 计划步骤 4 计量前置）。

设计出处：``plans/22-SMALL-ITEMS-31-CLOSEOUT-DESIGN-2026-08-29.md``
Part 2-D5：
- ``RAG_QUERY_DECOMPOSE``（on 默认 / off）导入期 fail-fast 门控
  共享规划 helper 的 ``decompose_query_llm`` 调用；
- off = 单查询直通（sub_queries = [rewritten_query]，零拆解 LLM 调用）；
- 默认行为零变化（on = 历史行为逐字节不变）。
"""
from __future__ import annotations

import pytest

import src.rag as rag
from src.rag import _plan_query_runtime


def _patch_planning_deps(monkeypatch, rewrite_ret=("rewritten-q", {"changed": False}),
                         decompose_log=None):
    """冻结 rewrite/decompose/检索三函数：记录调用并返回固定产物。"""
    from src.rag_query_decomposer import decompose_query_llm
    from src.rag_query_rewriter import rewrite_query_llm

    calls = {"rewrite": 0, "decompose": 0}

    def _fake_rewrite(*args, **kwargs):
        calls["rewrite"] += 1
        return rewrite_ret

    def _fake_decompose(*args, **kwargs):
        calls["decompose"] += 1
        if decompose_log is not None:
            kwargs["_provenance_sink"].append(decompose_log)
        return ["sub-1", "sub-2"]

    def _fake_retrieve(sq, *args, **kwargs):
        return ([0, 1], [f"d0-{sq}", f"d1-{sq}"], [0.9, 0.8])

    monkeypatch.setattr("src.rag_query_rewriter.rewrite_query_llm", _fake_rewrite)
    monkeypatch.setattr(src_rag_query_decomposer_module(), "decompose_query_llm",
                        _fake_decompose)
    monkeypatch.setattr("src.rag.retrieve_hybrid_with_sources", _fake_retrieve)
    return calls


def src_rag_query_decomposer_module():
    import src.rag_query_decomposer as m
    return m


def _blank_index():
    docs = [f"doc {i}" for i in range(2)]
    metas = [{"chunk_id": f"c{i}", "chunk_index": i, "source_id": "s1"}
             for i in range(2)]
    return docs, metas


class TestDecomposeSwitchDefault:
    def test_default_is_on(self):
        assert rag.RAG_QUERY_DECOMPOSE == rag.DECOMPOSE_ON


class TestDecomposeSwitchGating:
    def test_off_skips_decompose_and_single_query_passthrough(self, monkeypatch):
        """off：零 decompose 调用；sub_queries 直通 rewritten_query。"""
        docs, metas = _blank_index()
        calls = _patch_planning_deps(monkeypatch, rewrite_ret=("rewritten-q", {"changed": False}))
        monkeypatch.setattr(rag, "RAG_QUERY_DECOMPOSE", rag.DECOMPOSE_OFF)

        plan = _plan_query_runtime("q", None, None, None, docs, metas)
        assert calls["rewrite"] == 1
        assert calls["decompose"] == 0
        assert plan.sub_queries == ["rewritten-q"]

    def test_on_calls_decompose_with_rewritten_query(self, monkeypatch):
        """on（默认）：decompose 以 rewritten_query 为输入被调用。"""
        docs, metas = _blank_index()
        calls = _patch_planning_deps(monkeypatch, rewrite_ret=("rewritten-q", {"changed": False}))
        monkeypatch.setattr(rag, "RAG_QUERY_DECOMPOSE", rag.DECOMPOSE_ON)

        plan = _plan_query_runtime("q", None, None, None, docs, metas)
        assert calls["decompose"] == 1
        assert plan.sub_queries == ["sub-1", "sub-2"]

    def test_off_decompose_stage_not_recorded(self, monkeypatch):
        """off：provenance 侧信道 decompose_stage 为空（零拆解语义）。"""
        docs, metas = _blank_index()
        _patch_planning_deps(monkeypatch, rewrite_ret=("rewritten-q", {"changed": True}))
        monkeypatch.setattr(rag, "RAG_QUERY_DECOMPOSE", rag.DECOMPOSE_OFF)
        plan = _plan_query_runtime("q", None, None, None, docs, metas)
        assert plan.decompose_stage is None
        assert plan.sub_queries == ["rewritten-q"]


class TestDecomposeSwitchValidation:
    def test_invalid_value_rejected_at_import(self):
        import subprocess, sys, pathlib
        script = (
            "import os, sys; "
            "sys.path.insert(0, r'{root}'); "
            "os.environ['RAG_QUERY_DECOMPOSE'] = 'maybe'; "
            "import src.rag").format(root=pathlib.Path(__file__).resolve().parents[1])
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True,
            timeout=60)
        assert result.returncode != 0
        assert "RAG_QUERY_DECOMPOSE" in result.stderr
