"""evidence_calibrated 拒答策略 + PreparedAnswerEvidence 的单元测试。

覆盖（RED → GREEN，TDD）：
- 默认 RAG_REFUSAL_POLICY=baseline，提示词与重构前逐字节一致（默认行为不变）；
- evidence_calibrated 仅在 system prompt 追加静态指令段，user prompt/模板不变；
- 非法策略值导入期 fail-fast；
- 策略指令不泄露任何真值/评测信息；
- PreparedAnswerEvidence 字段完整、指纹确定性、frozen 不可变；
- answer_query 经 prepare+generate 拆分后 LLM 消息与旧实现一致。
"""
from __future__ import annotations

import hashlib
import importlib
import json
from unittest import mock

import pytest


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestRefusalPolicyDefaults:
    """默认策略与提示词不变性。"""

    def test_default_policy_is_baseline(self):
        import src.rag as rag
        assert rag.RAG_REFUSAL_POLICY == "baseline"

    def test_system_prompt_for_policy_baseline_returns_original(self):
        import src.rag as rag
        assert rag.system_prompt_for_policy("baseline") == rag.SYSTEM_PROMPT

    def test_baseline_llm_messages_system_unchanged(self):
        """baseline 下 _build_llm_messages 的 system 内容必须与旧实现一致。"""
        import src.rag as rag
        messages = rag._build_llm_messages(
            "问题", "文档内容", [("历史问题", "历史回答")],
        )
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == rag.SYSTEM_PROMPT

    def test_user_prompt_template_identical_across_policies(self):
        """两策略下 user prompt（PROMPT_TEMPLATE）必须逐字节相同（来源/引用格式不变）。"""
        import src.rag as rag
        baseline = rag._build_llm_messages("q", "ctx", [])
        with mock.patch.object(rag, "RAG_REFUSAL_POLICY",
                               rag.REFUSAL_POLICY_EVIDENCE_CALIBRATED):
            calibrated = rag._build_llm_messages("q", "ctx", [])
        assert baseline[-1] == calibrated[-1]
        assert baseline[-1]["role"] == "user"
        assert baseline[-1]["content"] == rag.PROMPT_TEMPLATE.format(
            context="ctx", question="q",
        )


class TestEvidenceCalibratedPrompt:
    """evidence_calibrated 策略的提示词构造。"""

    def test_system_prompt_appends_addendum(self):
        import src.rag as rag
        expected = (rag.SYSTEM_PROMPT + "\n\n"
                    + rag.EVIDENCE_CALIBRATED_SYSTEM_PROMPT_ADDENDUM)
        assert rag.system_prompt_for_policy("evidence_calibrated") == expected

    def test_llm_messages_system_contains_addendum(self):
        import src.rag as rag
        with mock.patch.object(rag, "RAG_REFUSAL_POLICY",
                               rag.REFUSAL_POLICY_EVIDENCE_CALIBRATED):
            messages = rag._build_llm_messages("q", "ctx", [])
        assert rag.EVIDENCE_CALIBRATED_SYSTEM_PROMPT_ADDENDUM in messages[0]["content"]
        assert messages[0]["content"].startswith(rag.SYSTEM_PROMPT)

    def test_addendum_directs_answer_when_evidence_sufficient(self):
        """指令语义：证据足以支持时必须作答并引用；仅 context 不足才拒答。"""
        import src.rag as rag
        text = rag.EVIDENCE_CALIBRATED_SYSTEM_PROMPT_ADDENDUM.lower()
        # 必须作答（含引用要求）
        assert "必须基于证据作答" in rag.EVIDENCE_CALIBRATED_SYSTEM_PROMPT_ADDENDUM
        assert "[s1]" in text or "[S1]" in rag.EVIDENCE_CALIBRATED_SYSTEM_PROMPT_ADDENDUM
        # 拒答条件收窄为「context 无法支持」
        assert "仅当" in rag.EVIDENCE_CALIBRATED_SYSTEM_PROMPT_ADDENDUM
        assert "拒答" in rag.EVIDENCE_CALIBRATED_SYSTEM_PROMPT_ADDENDUM

    def test_addendum_does_not_leak_ground_truth(self):
        """策略指令不得包含任何真值/评测专属信息。"""
        import src.rag as rag
        text = rag.EVIDENCE_CALIBRATED_SYSTEM_PROMPT_ADDENDUM
        for forbidden in ("ground_truth", "ground truth", "relevant", "case_id",
                          "GT", "reviewer", "eval", "overlay", "snippet",
                          "holdout", "dev"):
            assert forbidden.lower() not in text.lower(), f"leak: {forbidden}"


class TestRefusalPolicyValidation:
    """非法策略值 fail-fast。"""

    def test_invalid_policy_value_rejected(self):
        import src.rag as rag
        with pytest.raises(ValueError):
            rag.validate_refusal_policy("bogus-policy")
        with pytest.raises(ValueError):
            rag.validate_refusal_policy("")

    def test_valid_policies_accepted(self):
        import src.rag as rag
        for p in rag.REFUSAL_POLICIES:
            assert rag.validate_refusal_policy(p) == p

    def test_import_time_fail_fast_on_invalid_env(self, monkeypatch):
        import src.rag as rag
        monkeypatch.setenv("RAG_REFUSAL_POLICY", "bogus-policy")
        with pytest.raises(ValueError):
            importlib.reload(rag)


class TestPreparedAnswerEvidence:
    """证据对象：字段完整、指纹确定性、不可变。"""

    def _sample_evidence(self):
        from src.domain import PreparedAnswerEvidence
        context = "文档证据文本"
        return PreparedAnswerEvidence(
            query="问题",
            context=context,
            context_sha256=_sha256(context),
            context_k=2,
            top_indices=(3, 7),
            select_indices=(3, 7),
            citation_map=(("S1", "chunk_a"), ("S2", "chunk_b")),
            context_chunk_ids=("chunk_a", "chunk_b"),
            context_source_ids=("doc.pdf",),
            candidate_chunk_ids=("chunk_a", "chunk_b", "chunk_c"),
            top_scores=(0.5, 0.3),
            plan_fingerprint=_sha256("plan"),
            retrieval_fingerprint=_sha256("retrieval"),
        )

    def test_fields_complete_and_frozen(self):
        from src.domain import PreparedAnswerEvidence
        ev = self._sample_evidence()
        assert ev.context_sha256 == _sha256(ev.context)
        assert ev.context_k == 2
        assert ev.refused is False and ev.refusal_reason is None
        with pytest.raises(AttributeError):
            ev.context = "不可变"  # frozen

    def test_fingerprint_deterministic(self):
        a = self._sample_evidence()
        b = self._sample_evidence()
        assert a.plan_fingerprint == b.plan_fingerprint
        assert a.retrieval_fingerprint == b.retrieval_fingerprint
        assert a.context_sha256 == b.context_sha256

    def test_refused_evidence_allowed(self):
        from src.domain import PreparedAnswerEvidence
        ev = PreparedAnswerEvidence(
            query="q", context="", context_sha256=_sha256(""),
            context_k=0, top_indices=(), select_indices=(), citation_map=(),
            context_chunk_ids=(), context_source_ids=(),
            candidate_chunk_ids=(), top_scores=(),
            plan_fingerprint="p", retrieval_fingerprint="r",
            refused=True, refusal_reason="retrieval",
        )
        assert ev.refused is True
        assert ev.refusal_reason == "retrieval"


class TestAnswerQueryRefactorBehaviour:
    """answer_query 重构（prepare + generate 拆分）后默认行为不变。"""

    def _make_env(self):
        """最小化 mock 环境：检索短路 + llm_call 捕获。"""
        import src.rag as rag

        docs = ["chunk 0 内容", "chunk 1 内容"]
        metas = [
            {"chunk_id": "chunk_0", "source_id": "h0",
             "source_name": "doc.pdf", "source": "doc.pdf"},
            {"chunk_id": "chunk_1", "source_id": "h1",
             "source_name": "doc.pdf", "source": "doc.pdf"},
        ]
        llm_messages = []

        def fake_llm_call(call_type, messages, model, temperature, max_tokens,
                          **kwargs):
            llm_messages.append(messages)
            response = mock.Mock()
            response.choices = [mock.Mock()]
            response.choices[0].message.content = "基于文档的答案。"
            return response, None

        def fake_retrieve(sq, model, collection, bm25, documents, metadatas):
            return [0, 1], [], [0.6, 0.4]

        return docs, metas, llm_messages, fake_llm_call, fake_retrieve

    def test_answer_query_baseline_messages_unchanged(self):
        """重构后 answer_query 的 system 消息必须仍是原 SYSTEM_PROMPT（无 addendum）。"""
        import src.rag as rag
        docs, metas, llm_messages, fake_llm_call, fake_retrieve = self._make_env()

        with mock.patch("src.llm_gateway.llm_call", fake_llm_call), \
             mock.patch.object(rag, "retrieve_hybrid_with_sources", fake_retrieve), \
             mock.patch.object(rag, "RAG_REFUSAL_POLICY", "baseline"), \
             mock.patch.object(rag, "_record_query_metric", lambda *a, **k: None):
            answer, sources = rag.answer_query(
                "问题", mock.Mock(), mock.Mock(), mock.Mock(), docs, metas,
            )

        assert answer == "基于文档的答案。"
        assert len(llm_messages) == 1
        system = llm_messages[0][0]
        assert system["role"] == "system"
        assert system["content"] == rag.SYSTEM_PROMPT
        assert rag.EVIDENCE_CALIBRATED_SYSTEM_PROMPT_ADDENDUM not in system["content"]

    def test_generate_answer_respects_policy_override(self):
        """generate_answer 按当前 RAG_REFUSAL_POLICY 选择提示词（评测按臂覆盖生效）。"""
        import src.rag as rag
        from src.domain import PreparedAnswerEvidence
        docs, metas, llm_messages, fake_llm_call, fake_retrieve = self._make_env()
        evidence = PreparedAnswerEvidence(
            query="问题", context="文档证据文本", context_sha256=_sha256("文档证据文本"),
            context_k=1, top_indices=(0,), select_indices=(0,),
            citation_map=(("S1", "chunk_0"),),
            context_chunk_ids=("chunk_0",),
            context_source_ids=("doc.pdf",),
            candidate_chunk_ids=("chunk_0", "chunk_1"),
            top_scores=(0.6,),
            plan_fingerprint="p", retrieval_fingerprint="r",
        )
        with mock.patch("src.llm_gateway.llm_call", fake_llm_call), \
             mock.patch.object(rag, "RAG_REFUSAL_POLICY",
                               rag.REFUSAL_POLICY_EVIDENCE_CALIBRATED):
            answer, sources = rag.generate_answer(
                evidence, docs, metas, history=[],
            )
        assert answer == "基于文档的答案。"
        system = llm_messages[0][0]
        assert rag.EVIDENCE_CALIBRATED_SYSTEM_PROMPT_ADDENDUM in system["content"]

    def test_generate_answer_refused_evidence_returns_refusal(self):
        import src.rag as rag
        from src.domain import PreparedAnswerEvidence
        evidence = PreparedAnswerEvidence(
            query="q", context="", context_sha256=_sha256(""),
            context_k=0, top_indices=(), select_indices=(), citation_map=(),
            context_chunk_ids=(), context_source_ids=(),
            candidate_chunk_ids=(), top_scores=(),
            plan_fingerprint="p", retrieval_fingerprint="r",
            refused=True, refusal_reason="retrieval",
        )
        with mock.patch("src.llm_gateway.llm_call",
                               mock.Mock(side_effect=AssertionError("不应调用 LLM"))):
            answer, sources = rag.generate_answer(
                evidence, [], [], history=[],
            )
        assert answer == rag.REFUSAL_MESSAGE
        assert sources == ""

    def test_answer_query_and_prepare_generate_equivalent(self):
        """answer_query 输出 == prepare + generate 组合输出（生产路径一致性）。"""
        import src.rag as rag
        docs, metas, llm_messages, fake_llm_call, fake_retrieve = self._make_env()

        with mock.patch("src.llm_gateway.llm_call", fake_llm_call), \
             mock.patch.object(rag, "retrieve_hybrid_with_sources", fake_retrieve), \
             mock.patch.object(rag, "RAG_REFUSAL_POLICY", "baseline"), \
             mock.patch.object(rag, "_record_query_metric", lambda *a, **k: None):
            ev = rag.prepare_answer_evidence(
                "问题", mock.Mock(), mock.Mock(), mock.Mock(), docs, metas,
            )
            a1, s1 = rag.generate_answer(ev, docs, metas, history=[])

        llm_messages.clear()
        with mock.patch("src.llm_gateway.llm_call", fake_llm_call), \
             mock.patch.object(rag, "retrieve_hybrid_with_sources", fake_retrieve), \
             mock.patch.object(rag, "RAG_REFUSAL_POLICY", "baseline"), \
             mock.patch.object(rag, "_record_query_metric", lambda *a, **k: None):
            a2, s2 = rag.answer_query(
                "问题", mock.Mock(), mock.Mock(), mock.Mock(), docs, metas,
            )

        assert a1 == a2
        assert s1 == s2
        assert ev.context_sha256 == _sha256(ev.context)

    def test_prepare_from_plan_skips_llm_planning(self):
        """评测路径：从 QueryPlan 构建 evidence 不得再调 rewrite/decompose。"""
        import src.rag as rag
        docs, metas, llm_messages, fake_llm_call, fake_retrieve = self._make_env()

        class FakePlan:
            rewritten_query = "改写后问题"
            rewrite_log = {"changed": False}
            sub_queries = ["改写后问题"]
            base_candidates = {0: 0.6, 1: 0.4}

        with mock.patch("src.llm_gateway.llm_call", fake_llm_call), \
             mock.patch.object(rag, "retrieve_hybrid_with_sources",
                               mock.Mock(side_effect=AssertionError(
                                   "评测路径不得再检索"))), \
             mock.patch("src.rag_query_rewriter.rewrite_query_llm",
                        mock.Mock(side_effect=AssertionError(
                            "评测路径不得再 rewrite"))), \
             mock.patch("src.rag_query_decomposer.decompose_query_llm",
                        mock.Mock(side_effect=AssertionError(
                            "评测路径不得再 decompose"))), \
             mock.patch.object(rag, "_record_query_metric", lambda *a, **k: None):
            ev = rag.prepare_answer_evidence(
                "问题", mock.Mock(), mock.Mock(), mock.Mock(), docs, metas,
                query_plan=FakePlan(),
            )
            answer, sources = rag.generate_answer(ev, docs, metas, history=[])

        assert answer == "基于文档的答案。"
        assert ev.plan_fingerprint != ""
        assert ev.retrieval_fingerprint != ""
        assert set(ev.context_chunk_ids) == {"chunk_0", "chunk_1"}
        assert ev.candidate_chunk_ids == ("chunk_0", "chunk_1")
