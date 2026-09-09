"""产品默认 = 臂2 配置（owner 2026-09-06 批准切换）——契约测试。

M5d 门禁 PASS 后 owner 批示：把评测验证的臂2 配置设为产品默认：

- 检索拒答阈值 0.03 → **0.015**（`DEFAULT_REFUSAL_THRESHOLD`）
- 检索动态 Top-K 下界 12 → **25**（`RETRIEVAL_DYNAMIC_MIN_K`）
- context 预算上限 10 → **25**、token 预算 3000 → **7000**
  （`compute_context_k` 默认参数）

环境变量覆盖通道保留（实验/回退可显式设回旧值），未设时使用本契约默认。
"""

from __future__ import annotations

import pytest

from src.domain import RetrievalCandidate, compute_context_k


def _candidates(n: int) -> list[RetrievalCandidate]:
    return [
        RetrievalCandidate(index=i, chunk_id=f"c{i}", source_id="s0",
                           source_name="doc")
        for i in range(n)
    ]


class TestProductDefaults:
    def test_refusal_threshold_is_arm2_value(self, monkeypatch):
        monkeypatch.delenv("RAG_REFUSAL_THRESHOLD", raising=False)
        from src.config import Settings
        assert Settings().refusal_threshold == 0.015

    def test_dynamic_min_k_is_arm2_value(self):
        from src.config import RETRIEVAL_DYNAMIC_MIN_K
        assert RETRIEVAL_DYNAMIC_MIN_K == 25

    def test_context_budget_caps_at_25(self):
        # 默认 token_budget=7000, avg=200 → 35, clamped to max_k=25
        assert compute_context_k(_candidates(40)) == 25

    def test_context_budget_ceiling_25(self):
        assert compute_context_k(_candidates(40), token_budget=10000) == 25

    def test_fewer_candidates_than_budget(self):
        assert compute_context_k(_candidates(3)) == 3


class TestEnvOverrideStillWorks:
    def test_refusal_threshold_env_override(self, monkeypatch):
        monkeypatch.setenv("RAG_REFUSAL_THRESHOLD", "0.03")
        from src.config import Settings
        assert Settings().refusal_threshold == 0.03

    def test_dynamic_min_k_env_override_reverts_experiment_value(
            self, monkeypatch):
        """实验/回退通道：显式设回 M2 基线配置仍生效。"""
        monkeypatch.setenv("RAG_DYNAMIC_MIN_K", "12")
        import src.rag as rag
        assert rag._env_int_override(
            "RAG_DYNAMIC_MIN_K", rag.DEFAULT_MIN_K) == 12

    def test_context_max_k_env_override(self, monkeypatch):
        monkeypatch.setenv("RAG_CONTEXT_MAX_K", "10")
        import src.rag as rag
        assert rag._env_int_override("RAG_CONTEXT_MAX_K", 25) == 10
