"""Product P0.2：非流式 CLI Citation Integrity parity 的 TDD 测试。

覆盖验收：
- 标准 CLI interactive 与单次路径（run_single_query / rag_pipeline）的
  合法、非法、缺失；
- Graph CLI interactive、Graph 单次查询（--query）、graph_rag_pipeline
  的合法、非法、缺失，以及与 Graph streaming 同口径的拒答/API 错误；
- 提示独立展示且不污染下一轮 history（history 只存原始回答）；
- sources 与 valid IDs 严格一致；
- `[S99]` 原样保留；
- 不增加 LLM/API 调用；
- 旧调用方仍可按 `(answer, sources)` 使用。

全部使用本地 fake（零 LLM / 零网络 / 零真实检索）。
"""
from __future__ import annotations

from unittest import mock

import pytest

import src.rag as rag
from src import cli_loop
from src.domain import (
    CITATION_NOT_REQUIRED,
    CITATION_UNVERIFIED,
    CITATION_VERIFIED,
    CitationStatus,
    PreparedAnswerEvidence,
)

DOCS = ["d0 文本", "d1 文本"]
METAS = [
    {"chunk_id": "chunk_0", "source_id": "s0", "source_name": "a.md",
     "source": "a.md"},
    {"chunk_id": "chunk_1", "source_id": "s1", "source_name": "b.md",
     "source": "b.md"},
]
QUERY = "这篇论文讲了什么？"


def _parse_ids(sources: str) -> set[str]:
    import re
    return set(re.findall(r"\[(S\d+)\]", sources))


# ═══════════════════════════════════════════════════════════════
# 共享 helper（单元）
# ═══════════════════════════════════════════════════════════════

class TestEvaluateAnswerStatus:
    def test_refused_not_required(self):
        status = rag.evaluate_answer_status(rag.REFUSAL_MESSAGE, ("S1",))
        assert status.state == CITATION_NOT_REQUIRED
        assert status.reason == "refused"

    def test_api_error_not_required(self):
        status = rag.evaluate_answer_status(
            "无法连接到 API 服务，请检查网络或 BASE_URL 配置。", ("S1",),
        )
        assert status.state == CITATION_NOT_REQUIRED
        assert status.reason == "api_error"

    def test_verified_unverified_missing(self):
        assert rag.evaluate_answer_status(
            "根据[S1]。", ("S1",)).state == CITATION_VERIFIED
        assert rag.evaluate_answer_status(
            "根据[S99]。", ("S1",)).state == CITATION_UNVERIFIED
        missing = rag.evaluate_answer_status("无引用。", ("S1",))
        assert missing.state == CITATION_UNVERIFIED
        assert missing.missing is True


class TestFormatStatusLine:
    def test_line_states(self):
        from src.citations import format_citation_status_line

        line = format_citation_status_line(CitationStatus(
            state=CITATION_UNVERIFIED, valid_ids=("S1",),
            invalid_ids=("S99",),
        ))
        assert "引用未验证" in line
        assert "S99" in line

        missing = format_citation_status_line(CitationStatus(
            state=CITATION_UNVERIFIED, valid_ids=("S1",), missing=True,
        ))
        assert "未引用任何来源" in missing

        verified = format_citation_status_line(CitationStatus(
            state=CITATION_VERIFIED, valid_ids=("S1",),
        ))
        assert "引用已验证" in verified

        assert format_citation_status_line(CitationStatus(
            state=CITATION_NOT_REQUIRED, reason="refused")) is None
        assert format_citation_status_line(None) is None


# ═══════════════════════════════════════════════════════════════
# _graph_rag_answer：真实校验（patch 底层检索/LLM）
# ═══════════════════════════════════════════════════════════════

class TestGraphRagAnswer:
    def _answer(self, monkeypatch, llm_content):
        from src import graph_rag

        monkeypatch.setattr(
            graph_rag, "graph_augmented_retrieve",
            lambda query, model, collection, bm25, docs, kg, alpha=0.7,
            verbose=False, all_metadatas=None: ([0, 1], DOCS, [0.9, 0.8]),
        )
        calls = {"n": 0}

        def fake_llm(question, context, history=None, temperature=0.1):
            calls["n"] += 1
            return llm_content

        monkeypatch.setattr("src.rag.answer_with_llm_history", fake_llm)
        sink: list = []
        answer, sources = cli_loop._graph_rag_answer(
            QUERY, None, None, None, DOCS, METAS, None, history=[],
            _citation_status_sink=sink,
        )
        return answer, sources, sink, calls

    def test_graph_answer_legal_verified(self, monkeypatch):
        answer, sources, sink, _ = self._answer(monkeypatch, "根据[S1]和[S2]。")
        assert answer == "根据[S1]和[S2]。"
        assert sink[0].state == CITATION_VERIFIED
        assert set(sink[0].valid_ids) == _parse_ids(sources)

    def test_graph_answer_illegal_unverified_text_kept(self, monkeypatch):
        answer, sources, sink, _ = self._answer(monkeypatch, "根据[S99]。")
        assert "[S99]" in answer          # 原样保留，绝不被替换
        assert "[S1]" not in answer
        assert sink[0].state == CITATION_UNVERIFIED
        assert sink[0].invalid_ids == ("S99",)
        assert set(sink[0].valid_ids) == _parse_ids(sources)

    def test_graph_answer_missing_unverified(self, monkeypatch):
        _, _, sink, _ = self._answer(monkeypatch, "没有引用的回答。")
        assert sink[0].state == CITATION_UNVERIFIED
        assert sink[0].missing is True

    def test_graph_answer_api_error_not_required(self, monkeypatch):
        _, _, sink, _ = self._answer(
            monkeypatch, "无法连接到 API 服务，请检查网络或 BASE_URL 配置。",
        )
        assert sink[0].state == CITATION_NOT_REQUIRED
        assert sink[0].reason == "api_error"

    def test_graph_answer_zero_extra_llm(self, monkeypatch):
        monkeypatch.setattr(
            "src.llm_gateway.llm_call_safe",
            mock.Mock(side_effect=AssertionError("规划不应调用 LLM")),
        )
        _, _, _, calls = self._answer(monkeypatch, "根据[S1]。")
        assert calls["n"] == 1  # 仅一次生成调用

    def test_graph_answer_without_sink_unchanged(self, monkeypatch):
        """旧调用方：不传 sink → 返回 (answer, sources) 行为不变。"""
        from src import graph_rag

        monkeypatch.setattr(
            graph_rag, "graph_augmented_retrieve",
            lambda query, model, collection, bm25, docs, kg, alpha=0.7,
            verbose=False, all_metadatas=None: ([0, 1], DOCS, [0.9, 0.8]),
        )
        monkeypatch.setattr(
            "src.rag.answer_with_llm_history",
            lambda q, c, history=None, temperature=0.1: "根据[S1]。",
        )
        answer, sources = cli_loop._graph_rag_answer(
            QUERY, None, None, None, DOCS, METAS, None, history=[],
        )
        assert answer == "根据[S1]。"
        assert sources


# ═══════════════════════════════════════════════════════════════
# run_single_query：status side-channel 转发（标准 + Graph）
# ═══════════════════════════════════════════════════════════════

class TestRunSingleQuery:
    def test_standard_forwards_status(self, monkeypatch):
        status = CitationStatus(state=CITATION_UNVERIFIED,
                                valid_ids=("S1",), invalid_ids=("S99",))

        def fake_answer_query(query, model, collection, bm25, documents,
                              metadatas, history=None, temperature=0.1, *,
                              _citation_status_sink=None):
            if _citation_status_sink is not None:
                _citation_status_sink.append(status)
            return "根据[S99]。", "[S1] a.md"

        monkeypatch.setattr("src.rag.answer_query", fake_answer_query)
        sink: list = []
        answer, sources = cli_loop.run_single_query(
            QUERY, model=None, collection=None, bm25=None,
            all_docs=DOCS, all_metadatas=METAS, _citation_status_sink=sink,
        )
        assert (answer, sources) == ("根据[S99]。", "[S1] a.md")
        assert sink == [status]

    def test_graph_forwards_status(self, monkeypatch):
        status = CitationStatus(state=CITATION_VERIFIED,
                                valid_ids=("S1", "S2"))

        def fake_graph_answer(query, model, collection, bm25, all_docs,
                              all_metadatas, kg, history, alpha=0.7, *,
                              _citation_status_sink=None):
            if _citation_status_sink is not None:
                _citation_status_sink.append(status)
            return "根据[S1]。", "[S1] a.md"

        monkeypatch.setattr(cli_loop, "_graph_rag_answer", fake_graph_answer)
        sink: list = []
        answer, sources = cli_loop.run_single_query(
            QUERY, model=None, collection=None, bm25=None,
            all_docs=DOCS, all_metadatas=METAS, is_graph_rag=True,
            _citation_status_sink=sink,
        )
        assert (answer, sources) == ("根据[S1]。", "[S1] a.md")
        assert sink == [status]

    def test_without_sink_unchanged(self, monkeypatch):
        monkeypatch.setattr(
            "src.rag.answer_query",
            lambda query, model, collection, bm25, documents, metadatas,
            history=None, temperature=0.1, **kw: ("A", "SRC"),
        )
        assert cli_loop.run_single_query(
            QUERY, model=None, collection=None, bm25=None,
            all_docs=DOCS, all_metadatas=METAS,
        ) == ("A", "SRC")


# ═══════════════════════════════════════════════════════════════
# run_interactive_session：标准 + Graph，提示独立且 history 不污染
# ═══════════════════════════════════════════════════════════════

class TestInteractiveSession:
    def _fake_answer(self, status, history_seen):
        def fake(query, model, collection, bm25, documents, metadatas,
                 history=None, temperature=0.1, *, _citation_status_sink=None):
            history_seen.append(list(history or []))
            if _citation_status_sink is not None:
                _citation_status_sink.append(status)
            return "根据[S99]的回答正文。", "[S1] a.md"
        return fake

    def _fake_graph_answer(self, status, history_seen):
        def fake(query, model, collection, bm25, all_docs, all_metadatas,
                 kg, history, alpha=0.7, *, _citation_status_sink=None):
            history_seen.append(list(history or []))
            if _citation_status_sink is not None:
                _citation_status_sink.append(status)
            return "根据[S99]的回答正文。", "[S1] a.md"
        return fake

    def test_standard_interactive_shows_banner_history_clean(
            self, monkeypatch, capsys):
        monkeypatch.setattr(
            "src.rag.prepare_index",
            lambda files, name, rebuild: (None, None, None, DOCS, METAS),
        )
        history_seen: list[list] = []
        monkeypatch.setattr("src.rag.answer_query", self._fake_answer(
            CitationStatus(state=CITATION_UNVERIFIED, valid_ids=("S1",),
                           invalid_ids=("S99",)),
            history_seen,
        ))
        inputs = iter(["问题A", "问题B", "q"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

        cli_loop.run_interactive_session(["f1"], "col")

        out = capsys.readouterr().out
        assert "引用未验证" in out
        assert "S99" in out
        # 两轮查询；第二轮 history 只含原始回答（提示未混入）
        assert len(history_seen) == 2
        assert history_seen[1] == [("问题A", "根据[S99]的回答正文。")]
        assert all("引用未验证" not in h[1] for h in history_seen[1])

    def test_graph_interactive_shows_banner_history_clean(
            self, monkeypatch, capsys):
        from src import graph_rag
        monkeypatch.setattr(
            graph_rag, "prepare_graph_index",
            lambda files, name, rebuild: (None, None, None, DOCS, METAS, None),
        )
        history_seen: list[list] = []
        monkeypatch.setattr(cli_loop, "_graph_rag_answer",
                            self._fake_graph_answer(
            CitationStatus(state=CITATION_UNVERIFIED, valid_ids=("S1",),
                           invalid_ids=("S99",)),
            history_seen,
        ))
        inputs = iter(["问题A", "问题B", "q"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

        cli_loop.run_interactive_session(
            ["f1"], "col", is_graph_rag=True,
        )

        out = capsys.readouterr().out
        assert "引用未验证" in out
        assert len(history_seen) == 2
        assert history_seen[1] == [("问题A", "根据[S99]的回答正文。")]

    def test_interactive_verified_shows_verified_line(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "src.rag.prepare_index",
            lambda files, name, rebuild: (None, None, None, DOCS, METAS),
        )
        history_seen: list[list] = []
        monkeypatch.setattr("src.rag.answer_query", self._fake_answer(
            CitationStatus(state=CITATION_VERIFIED, valid_ids=("S1", "S2")),
            history_seen,
        ))
        inputs = iter(["问题A", "q"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

        cli_loop.run_interactive_session(["f1"], "col")

        out = capsys.readouterr().out
        assert "引用已验证" in out
        assert "引用未验证" not in out


# ═══════════════════════════════════════════════════════════════
# rag_pipeline 与 graph_rag_pipeline：独立非流式入口
# ═══════════════════════════════════════════════════════════════

class TestPipelines:
    def test_rag_pipeline_shows_unverified_line(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "src.rag.prepare_index",
            lambda files, name, rebuild: (None, None, None, DOCS, METAS),
        )

        def fake_answer_query(query, model, collection, bm25, documents,
                              metadatas, history=None, temperature=0.1, *,
                              _citation_status_sink=None):
            if _citation_status_sink is not None:
                _citation_status_sink.append(CitationStatus(
                    state=CITATION_UNVERIFIED, valid_ids=("S1",),
                    invalid_ids=("S99",),
                ))
            return "根据[S99]的回答正文。", "[S1] a.md"

        monkeypatch.setattr("src.rag.answer_query", fake_answer_query)
        result = rag.rag_pipeline(["f1"], QUERY, collection_name="col")
        out = capsys.readouterr().out
        assert result == "根据[S99]的回答正文。"
        assert "引用未验证" in out
        assert "S99" in out

    def test_graph_rag_pipeline_verified_line_and_missing_line(
            self, monkeypatch, capsys):
        from src import graph_rag

        monkeypatch.setattr(
            graph_rag, "prepare_graph_index",
            lambda files, name, rebuild: (None, None, None, DOCS, METAS, None),
        )
        monkeypatch.setattr(
            graph_rag, "graph_augmented_retrieve",
            lambda query, model, collection, bm25, docs, kg, k_vector=20,
            k_graph=5, alpha=0.7, all_metadatas=None: (
                [0, 1], DOCS, [0.9, 0.8],
            ),
        )
        contents = iter(["根据[S1]和[S2]。", "没有引用的回答。"])
        # graph_rag 模块级 import 绑定 answer_with_llm_history →
        # patch graph_rag 命名空间（patch src.rag 不会拦截 pipeline 调用）
        monkeypatch.setattr(
            "src.graph_rag.answer_with_llm_history",
            lambda q, c, history=None, temperature=0.1: next(contents),
        )
        result_a = graph_rag.graph_rag_pipeline(["f1"], QUERY,
                                                collection_name="col")
        out_a = capsys.readouterr().out
        result_b = graph_rag.graph_rag_pipeline(["f1"], QUERY,
                                                collection_name="col")
        out_b = capsys.readouterr().out
        assert result_a == "根据[S1]和[S2]。"   # 原文保留
        assert result_b == "没有引用的回答。"   # 原文保留
        assert "引用已验证" in out_a           # 第一次：全部合法
        assert "未引用任何来源" in out_b       # 第二次：缺失引用

    def test_graph_rag_pipeline_refused_no_banner(self, monkeypatch, capsys):
        from src import graph_rag

        monkeypatch.setattr(
            graph_rag, "prepare_graph_index",
            lambda files, name, rebuild: (None, None, None, DOCS, METAS, None),
        )
        monkeypatch.setattr(
            graph_rag, "graph_augmented_retrieve",
            lambda query, model, collection, bm25, docs, kg, k_vector=20,
            k_graph=5, alpha=0.7, all_metadatas=None: (
                [0], ["d0 文本"], [0.01],
            ),
        )
        result = graph_rag.graph_rag_pipeline(["f1"], QUERY,
                                              collection_name="col")
        out = capsys.readouterr().out
        assert result == rag.REFUSAL_MESSAGE
        assert rag.REFUSAL_MESSAGE in out
        assert "引用未验证" not in out    # 拒答不显示误导提示
        assert "引用已验证" not in out


# ═══════════════════════════════════════════════════════════════
# rag_pipeline 来源展示闭环（Product P0.2.1）
# ═══════════════════════════════════════════════════════════════

class TestRagPipelineSourcesClosure:
    """P0.2.1：rag_pipeline 打印与 citation status 同口径的来源块。

    不 patch answer_query——patch prepare_answer_evidence（返回构造的
    evidence，跳过真实检索与规划）与 answer_with_llm_history（固定回答），
    使 sources 生成（format_sources）与 status 计算
    （valid_citation_ids_for_context + evaluate_answer_status）都走真实
    代码，同口径由真实实现保证。llm_call_safe 被 patch 为 fail-fast：
    任何意外触达 LLM gateway 的调用立即失败（零 LLM/API 硬约束）。
    """

    @staticmethod
    def _evidence(*, refused: bool = False) -> PreparedAnswerEvidence:
        return PreparedAnswerEvidence(
            query=QUERY,
            context="[S1] d0 文本\n[S2] d1 文本",
            context_sha256="a" * 64,
            context_k=2,
            top_indices=(0, 1),
            select_indices=(0, 1),
            citation_map=(("S1", "chunk_0"), ("S2", "chunk_1")),
            context_chunk_ids=("chunk_0", "chunk_1"),
            context_source_ids=("s0", "s1"),
            candidate_chunk_ids=("chunk_0", "chunk_1"),
            top_scores=(0.9, 0.8),
            plan_fingerprint="plan",
            retrieval_fingerprint="retrieval",
            refused=refused,
        )

    def _run(self, monkeypatch, answer_text: str, *, refused: bool = False):
        evidence = self._evidence(refused=refused)
        monkeypatch.setattr(
            "src.rag.prepare_index",
            lambda files, name, rebuild: (None, None, None, DOCS, METAS),
        )
        monkeypatch.setattr(
            "src.rag.prepare_answer_evidence",
            lambda *args, **kwargs: evidence,
        )
        monkeypatch.setattr(
            "src.rag.answer_with_llm_history",
            lambda q, c, history=None, temperature=0.1: answer_text,
        )
        # fail-fast：任何意外触达 LLM gateway 的调用立即失败
        monkeypatch.setattr(
            "src.llm_gateway.llm_call_safe",
            mock.Mock(side_effect=AssertionError("pipeline 不应调用 LLM")),
        )
        return rag.rag_pipeline(["f1"], QUERY, collection_name="col")

    def test_legal_sources_printed_before_verified_line(self, monkeypatch, capsys):
        result = self._run(monkeypatch, "根据[S1]和[S2]。")
        out = capsys.readouterr().out
        assert result == "根据[S1]和[S2]。"           # 原回答不变
        assert "参考来源" in out                      # 来源块已展示
        assert "[S1] a.md" in out                     # 同一 [S1] 来源
        assert "[S2] b.md" in out
        assert "引用已验证" in out                    # 随后显示 verified
        assert out.index("参考来源") < out.index("引用已验证")

    def test_illegal_keeps_text_sources_shown_unverified_line(
            self, monkeypatch, capsys):
        result = self._run(monkeypatch, "根据[S99]。")
        out = capsys.readouterr().out
        assert result == "根据[S99]。"                # [S99] 原样保留
        assert "[S99]" in out                         # 回答正文未被改写
        assert "参考来源" in out                      # 实际来源仍展示
        assert "[S1] a.md" in out
        assert "引用未验证" in out                    # 随后显示 unverified
        assert out.index("参考来源") < out.index("引用未验证")

    def test_refused_no_sources_no_banner(self, monkeypatch, capsys):
        result = self._run(monkeypatch, "", refused=True)
        out = capsys.readouterr().out
        assert result == rag.REFUSAL_MESSAGE          # 返回值不变
        assert "参考来源" not in out                  # 无来源块
        assert "引用未验证" not in out                # 无 citation banner
        assert "引用已验证" not in out

    def test_printed_sources_ids_exactly_match_status_valid_ids(
            self, monkeypatch, capsys):
        """实际打印的来源块 ID 与 status 所用合法 ID 集精确一致。"""
        from src.citations import valid_citation_ids_for_context

        self._run(monkeypatch, "根据[S1]和[S2]。")
        out = capsys.readouterr().out
        sources_block = out.split("参考来源：", 1)[1].split("引用已验证", 1)[0]
        printed_ids = _parse_ids(sources_block)
        valid_ids = set(
            valid_citation_ids_for_context((0, 1), DOCS, METAS, context_k=2)
        )
        assert printed_ids == valid_ids == {"S1", "S2"}

    def test_zero_extra_llm_calls(self, monkeypatch):
        """生成仅一次本地 fake 调用；LLM gateway 零调用（fail-fast 硬约束）。"""
        calls = []

        def fake_generate(q, c, history=None, temperature=0.1):
            calls.append(1)
            return "根据[S1]。"

        monkeypatch.setattr(
            "src.rag.prepare_index",
            lambda files, name, rebuild: (None, None, None, DOCS, METAS),
        )
        monkeypatch.setattr(
            "src.rag.prepare_answer_evidence",
            lambda *args, **kwargs: self._evidence(),
        )
        monkeypatch.setattr("src.rag.answer_with_llm_history", fake_generate)
        gateway = mock.Mock(side_effect=AssertionError("pipeline 不应调用 LLM"))
        monkeypatch.setattr("src.llm_gateway.llm_call_safe", gateway)
        rag.rag_pipeline(["f1"], QUERY, collection_name="col")
        assert calls == [1]              # 仅一次生成调用（无任何额外调用）
        gateway.assert_not_called()      # LLM gateway 零调用


# ═══════════════════════════════════════════════════════════════
# Graph --query（main）：状态行显示
# ═══════════════════════════════════════════════════════════════

class TestGraphQueryMain:
    def test_main_query_shows_status_line(self, monkeypatch, capsys):
        from src import graph_rag

        monkeypatch.setattr(
            graph_rag, "prepare_graph_index",
            lambda files, name, rebuild: (None, None, None, DOCS, METAS, None),
        )

        def fake_run_single_query(query, *, model, collection, bm25,
                                  all_docs, all_metadatas, is_graph_rag=False,
                                  alpha=0.7, kg=None,
                                  _citation_status_sink=None):
            if _citation_status_sink is not None:
                _citation_status_sink.append(CitationStatus(
                    state=CITATION_UNVERIFIED, valid_ids=("S1",),
                    invalid_ids=("S99",),
                ))
            return "根据[S99]的回答正文。", "[S1] a.md"

        monkeypatch.setattr("src.cli_loop.run_single_query",
                            fake_run_single_query)
        monkeypatch.setattr("sys.argv", [
            "graph_rag", "--files", "f1", "--query", QUERY,
        ])
        with pytest.raises(SystemExit) as exc_info:
            graph_rag.main()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "根据[S99]的回答正文。" in out
        assert "引用未验证" in out
        assert "S99" in out
