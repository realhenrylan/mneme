"""扩展预算调和（reconcile_expansion_budget）的单元测试（TDD）。

2.2 验收修复策略（预注册方向「select 高分原始块保留槽位」）：
- 代表块（select 原块，或已由在场 parent 代表的 child）保序优先；
- 扩展块（parent 去重腾出的空位、邻接邻居）按扩展顺序殿后；
- ``effective_k = max(context_k, len(reps))``——预算放大到恰好容纳全部
  召回代表块，截断只可能裁掉扩展尾部，**扩展永不挤占召回证据**。

回归场景（2.2 实验 mixed-009）：邻接邻居插队把真值块推出预算窗口 →
修复后真值块必须保留。
"""
from __future__ import annotations

import pytest

from src.chunking import reconcile_expansion_budget


def _metas(n: int, parent_of: dict[int, str] | None = None,
           child_type: set[int] | None = None) -> list[dict]:
    parent_of = parent_of or {}
    child_type = child_type or set()
    metas = []
    for i in range(n):
        metas.append({
            "chunk_id": f"c{i}",
            "chunk_index": i,
            "source_id": "s1",
            "chunk_type": "child" if i in child_type else "",
            "parent_chunk_id": parent_of.get(i, ""),
        })
    return metas


class TestRepresentativePreservation:
    def test_rescues_select_chunk_dropped_by_budget_break(self):
        # mixed-009 机制一：expand_with_parent 预算 break 丢弃尾部 select 块
        metas = _metas(5)
        final, k = reconcile_expansion_budget(
            [0, 1, 2], [0, 1], metas, context_k=2)
        assert final[:3] == [0, 1, 2]
        assert k >= 3

    def test_child_covered_by_present_parent_not_duplicated(self):
        # 两个 child 共享同一 parent：parent 替换后 child 不回插（内容重复）
        metas = _metas(5, parent_of={1: "c0", 2: "c0"}, child_type={1, 2})
        final, k = reconcile_expansion_budget([1, 2], [0], metas, context_k=3)
        assert final[0] == 0
        assert 1 not in final and 2 not in final
        assert k >= 1

    def test_child_with_absent_parent_is_rescued(self):
        # parent 也被预算丢弃：child 本身必须回插（证据不可失）
        metas = _metas(5, parent_of={1: "c9"}, child_type={1})
        final, k = reconcile_expansion_budget([1], [], metas, context_k=3)
        assert final == [1]

    def test_neighbors_go_after_representatives(self):
        # mixed-009 机制二：邻居插队推挤真值块出预算窗口 → 修复后代表块
        # 全部在前，邻居殿后；effective_k 只可能裁邻居。
        metas = _metas(8)
        final, k = reconcile_expansion_budget(
            [0, 1, 2], [0, 3, 4, 1, 2, 5], metas, context_k=3)
        assert final[:3] == [0, 1, 2]
        assert final[3:] == [3, 4, 5]
        assert k == 3  # max(context_k, len(reps))

    def test_budget_grows_when_select_exceeds_dynamic_k(self):
        # select 12 块 > dynamic max_k=10：预算放大到容纳全部代表块
        metas = _metas(12)
        final, k = reconcile_expansion_budget(
            list(range(12)), list(range(12)), metas, context_k=10)
        assert final == list(range(12))
        assert k == 12


class TestOrderingAndDedup:
    def test_rep_order_follows_select_order(self):
        metas = _metas(6)
        final, _ = reconcile_expansion_budget(
            [2, 0], [0, 2, 3], metas, context_k=5)
        assert final[:2] == [2, 0]
        assert final[2:] == [3]

    def test_no_duplicate_representative(self):
        metas = _metas(4)
        final, _ = reconcile_expansion_budget(
            [1, 1, 2], [1, 2], metas, context_k=3)
        assert final == [1, 2]

    def test_effective_k_never_below_context_k(self):
        metas = _metas(6)
        _, k = reconcile_expansion_budget(
            [0], [0, 1, 2, 3, 4], metas, context_k=4)
        assert k == 4


# ── 管线级回归：混合-009 型挤占在 prepare 路径被修复 ─────────────────

class TestPipelineDisplacementFixed:
    def test_select_evidence_survives_adjacent_insertion(
            self, monkeypatch):
        import src.rag as rag

        def _fake_parent(indices, enriched_docs, metadatas, budget):
            return list(indices), [(i, i) for i in indices]

        def _fake_adjacent(indices, metadatas, max_expand=2):
            # 第一个块后插入邻居 5 —— 旧代码下把尾部 select 块推出预算窗
            out = list(indices)
            out.insert(1, 5)
            return out

        monkeypatch.setattr(rag, "expand_with_parent", _fake_parent)
        monkeypatch.setattr(rag, "expand_with_adjacent", _fake_adjacent)
        monkeypatch.setattr(rag, "RAG_CONTEXT_EXPANSION", "on")

        documents = [f"doc {i}" for i in range(6)]
        metadatas = [{"chunk_id": f"c{i}", "chunk_index": i,
                      "source_id": "s1"} for i in range(6)]
        plan = SimpleNamespacePlan = type("P", (), {
            "rewritten_query": "q", "rewrite_log": {"changed": False},
            "sub_queries": ["q"],
            "base_candidates": {i: 1.0 - i * 0.1 for i in range(3)},
        })()
        evidence = rag.prepare_answer_evidence(
            "q", None, None, None, documents, metadatas,
            query_plan=plan)
        # 修复后：select 代表块全部在场（旧代码 c2 被邻居 5 挤出预算窗），
        # 且动态预算按扩展后列表计算——邻居 5 也获得预算准入（收益保留）。
        for cid in ("c0", "c1", "c2"):
            assert cid in evidence.context_chunk_ids
        assert "c5" in evidence.context_chunk_ids
