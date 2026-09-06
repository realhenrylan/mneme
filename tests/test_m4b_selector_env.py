"""M4c 臂2 选择器档位环境覆盖 — TDD RED→GREEN。

RAG_DYNAMIC_MIN_K / RAG_DYNAMIC_MAX_K / RAG_CONTEXT_MAX_K /
RAG_CONTEXT_TOKEN_BUDGET 四个环境变量在 prepare_answer_evidence 主管道
逐调用读取（G1-S 语义：未设/非法回退默认）；未设时行为与部署默认逐字节一致。
"""

from __future__ import annotations

import pytest

import src.rag as rag


_ENV_KEYS = (
    "RAG_DYNAMIC_MIN_K",
    "RAG_DYNAMIC_MAX_K",
    "RAG_CONTEXT_MAX_K",
    "RAG_CONTEXT_TOKEN_BUDGET",
)


@pytest.fixture()
def clean_selector_env(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


@pytest.fixture()
def flat_expansion(monkeypatch):
    """冻结 parent/adjacent 扩展：context 组成仅由 select 决定（确定性）。"""
    monkeypatch.setattr(rag, "expand_with_parent",
                        lambda indices, docs, metas, budget: (list(indices), None))
    monkeypatch.setattr(rag, "expand_with_adjacent",
                        lambda indices, metas, max_expand=2, texts=None: list(indices))


def _run_prepare(monkeypatch, n_candidates=26) -> rag.PreparedAnswerEvidence:
    """26 个候选、RRF 分数均匀递减（gap=0.01）：默认刀口=12、预算=10。"""
    from types import SimpleNamespace

    documents = [f"doc {i}" for i in range(n_candidates)]
    # 每块独立 source（唯一）：避免生产默认 max_per_source=3 的同源挤占
    # 掩盖选择器档位行为（该挤占单独由管道模拟实验考察）。
    metadatas = [
        {"chunk_id": f"c{i}", "chunk_index": i, "source_id": f"s{i}",
         "source_name": f"s{i}"}
        for i in range(n_candidates)
    ]
    base = {i: round(0.90 - 0.01 * i, 4) for i in range(n_candidates)}
    plan = SimpleNamespace(
        rewritten_query="q", rewrite_log={"changed": False},
        sub_queries=["q"], base_candidates=base,
    )
    return rag.prepare_answer_evidence(
        "q", None, None, None, documents, metadatas, query_plan=plan,
    )


class TestEnvIntOverrideSemantics:
    def test_missing_returns_default(self, monkeypatch):
        monkeypatch.delenv("RAG_TEST_OVERRIDE", raising=False)
        assert rag._env_int_override("RAG_TEST_OVERRIDE", 12) == 12

    def test_valid_positive_overrides(self, monkeypatch):
        monkeypatch.setenv("RAG_TEST_OVERRIDE", "25")
        assert rag._env_int_override("RAG_TEST_OVERRIDE", 12) == 25

    def test_invalid_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("RAG_TEST_OVERRIDE", "abc")
        assert rag._env_int_override("RAG_TEST_OVERRIDE", 12) == 12

    def test_non_positive_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("RAG_TEST_OVERRIDE", "0")
        assert rag._env_int_override("RAG_TEST_OVERRIDE", 12) == 12


class TestPrepareSelectorEnv:
    def test_default_context_bounded_by_dynamic_cut(
            self, monkeypatch, clean_selector_env, flat_expansion):
        # 生产语义：reconcile 把预算抬高到 select 数（select 证据不挤占），
        # 默认刀口=12 → context=12（而非 compute_context_k 的 10）。
        ev = _run_prepare(monkeypatch)
        assert ev.context_k == 12, "默认刀口 12 全进（reconcile 抬高预算）"

    def test_arm2_selector_range_expands_context_to_20(
            self, monkeypatch, clean_selector_env, flat_expansion):
        monkeypatch.setenv("RAG_DYNAMIC_MIN_K", "25")
        monkeypatch.setenv("RAG_CONTEXT_MAX_K", "25")
        monkeypatch.setenv("RAG_CONTEXT_TOKEN_BUDGET", "7000")
        ev = _run_prepare(monkeypatch)
        # select 侧 min(k, 20) 硬顶：臂2 净容量 = 20（预算 25 被 20 抵消）。
        assert ev.context_k == 20, "臂2 档位净容量 = select 硬顶 20"

    def test_invalid_env_falls_back_to_default(
            self, monkeypatch, clean_selector_env, flat_expansion):
        monkeypatch.setenv("RAG_DYNAMIC_MIN_K", "abc")
        monkeypatch.setenv("RAG_CONTEXT_MAX_K", "-1")
        ev = _run_prepare(monkeypatch)
        assert ev.context_k == 12, "非法值应回退默认行为（刀口 12 全进）"

    def test_default_behavior_unchanged_when_unset(
            self, monkeypatch, clean_selector_env, flat_expansion):
        ev_default = _run_prepare(monkeypatch)
        assert ev_default.context_k == 12
        assert ev_default.top_indices[:3] == (0, 1, 2)
