"""上下文扩展开关（RAG_CONTEXT_EXPANSION）的单元测试（TDD）。

覆盖（2.2 验收 E1）：
- 默认 on（无环境变量时行为与重构前逐字节一致）；
- 非法值导入期 fail-fast（与 RAG_REFUSAL_POLICY 同范式）；
- off 时 prepare 路径跳过 parent-child 与邻接扩展（expand 函数零调用，
  select_indices 直接进入 context）；
- 两处扩展调用点（sync/stream）均在门控块内（防回归 tripwire）。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


# ── 常量与校验 ───────────────────────────────────────────────────

class TestSwitchConstants:
    def test_default_is_on(self, monkeypatch):
        monkeypatch.delenv("RAG_CONTEXT_EXPANSION", raising=False)
        import src.rag as rag
        assert rag.RAG_CONTEXT_EXPANSION == "on"

    def test_validate_rejects_unknown_mode(self):
        import src.rag as rag
        with pytest.raises(ValueError, match="RAG_CONTEXT_EXPANSION"):
            rag.validate_context_expansion("sideways")

    def test_import_time_fail_fast(self, monkeypatch):
        monkeypatch.setenv("RAG_CONTEXT_EXPANSION", "sideways")
        import importlib
        import src.rag as rag
        with pytest.raises(ValueError, match="RAG_CONTEXT_EXPANSION"):
            importlib.reload(rag)
        # 恢复：以干净环境重载，避免污染后续测试的模块状态
        monkeypatch.delenv("RAG_CONTEXT_EXPANSION", raising=False)
        importlib.reload(rag)


# ── prepare 路径行为 ─────────────────────────────────────────────

def _plan_stub(base_candidates: dict[int, float]) -> SimpleNamespace:
    return SimpleNamespace(
        rewritten_query="q", rewrite_log={"changed": False},
        sub_queries=["q"], base_candidates=dict(base_candidates),
    )


@pytest.fixture()
def expansion_recorders(monkeypatch):
    calls = {"parent": 0, "adjacent": 0}

    def _fake_parent(indices, enriched_docs, metadatas, budget):
        calls["parent"] += 1
        # 返回域内索引（3 未被 select），模拟 parent 块注入
        out = list(indices)
        if 3 not in out:
            out.append(3)
        return out, None

    def _fake_adjacent(indices, metadatas, max_expand=2):
        calls["adjacent"] += 1
        out = list(indices)
        if 4 not in out:
            out.append(4)
        return out

    import src.rag as rag
    monkeypatch.setattr(rag, "expand_with_parent", _fake_parent)
    monkeypatch.setattr(rag, "expand_with_adjacent", _fake_adjacent)
    return calls


def _context_ids(monkeypatch, mode) -> set[str]:
    import src.rag as rag
    monkeypatch.setattr(rag, "RAG_CONTEXT_EXPANSION", mode)
    documents = [f"doc {i}" for i in range(5)]
    metadatas = [{"chunk_id": f"c{i}", "chunk_index": i} for i in range(5)]
    evidence = rag.prepare_answer_evidence(
        "q", None, None, None, documents, metadatas,
        query_plan=_plan_stub({0: 1.0, 1: 0.9, 2: 0.8}),
    )
    return set(evidence.context_chunk_ids)


class TestPreparePathGating:
    def test_off_context_is_select_set_only(
            self, monkeypatch, expansion_recorders):
        ids = _context_ids(monkeypatch, "off")
        assert expansion_recorders["parent"] == 0
        assert expansion_recorders["adjacent"] == 0
        assert ids and ids <= {"c0", "c1", "c2"}

    def test_on_context_includes_expanded_chunks(
            self, monkeypatch, expansion_recorders):
        off = _context_ids(monkeypatch, "off")
        on = _context_ids(monkeypatch, "on")
        assert expansion_recorders["parent"] == 1
        assert expansion_recorders["adjacent"] == 1
        added = on - off
        assert added and added <= {"c3", "c4"}


# ── 防回归 tripwire：两处调用点都必须在门控块内 ──────────────────

class TestBothCallSitesGated:
    def test_expansion_calls_inside_guard_block(self):
        import inspect
        import src.rag as rag
        source = inspect.getsource(rag)
        assert source.count("expand_with_parent(") == 2
        # 门控块出现两处（sync + stream），每处覆盖两个扩展调用
        assert source.count("if RAG_CONTEXT_EXPANSION == CONTEXT_EXPANSION_ON:") == 2
