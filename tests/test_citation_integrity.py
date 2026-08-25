"""Product P0.1：Citation Integrity for Streaming UI 的 TDD 测试。

覆盖验收：
- standard stream：合法 / 非法 / 缺失 / 拒答 / API 错误 五态；
- graph stream：合法 / 非法 / 缺失；
- 非流式 answer_query 与 streaming 同一输入得到相同 citation status；
- `[S99]` 绝不被改成任意合法 `[S#]`（原回答文本保留）；
- TUI 对 unverified 显示独立提示，且不污染下一轮 history；
- 实际展示的 sources 与校验用的合法 ID 集严格一致；
- 无额外 LLM/API 调用（校验只读文本，零新调用）；
- 旧调用方兼容（`stream, sources = ...` 解包 + `for chunk in stream`）。

全部使用本地 fake（零 LLM / 零网络 / 零真实检索）。
"""
from __future__ import annotations

import io
import re
from contextlib import contextmanager
from unittest import mock

import pytest
from rich.console import Console

import src.rag as rag
from src import citations
from src.domain import (
    CITATION_NOT_REQUIRED,
    CITATION_UNVERIFIED,
    CITATION_VERIFIED,
    CitationStatus,
)

DOCS = ["d0 文本", "d1 文本"]
METAS = [
    {"chunk_id": "chunk_0", "source_id": "s0", "source_name": "a.md",
     "source": "a.md"},
    {"chunk_id": "chunk_1", "source_id": "s1", "source_name": "b.md",
     "source": "b.md"},
]
# guard 全部跳过 → 零 LLM 规划（rewrite: 无历史；decompose: 简单中文）
SIMPLE_QUERY = "这篇论文讲了什么？"


def _fake_retrieve(sq, model, collection, bm25, documents, metadatas, k=None):
    return [0, 1], ["d0 文本", "d1 文本"], [0.9, 0.8]


def _fake_retrieve_weak(sq, model, collection, bm25, documents, metadatas, k=None):
    return [0], ["d0 文本"], [0.01]


def _stream_chunks(*texts):
    def gen():
        for t in texts:
            yield t
    return gen()


def _fake_llm_call_content(content: str, *, side_effect=None):
    """patch src.llm_gateway.llm_call 返回 stream 化响应或抛异常。"""
    if side_effect is not None:
        return mock.Mock(side_effect=side_effect)

    def handler(call_type, messages, model, temperature, max_tokens, **kwargs):
        if kwargs.get("stream"):
            response = mock.Mock()
            chunk = mock.Mock()
            chunk.choices = [mock.Mock()]
            chunk.choices[0].delta = mock.Mock(content=content)
            response.__iter__ = mock.Mock(return_value=iter([chunk]))
            return response, None
        response = mock.Mock()
        response.choices = [mock.Mock()]
        response.choices[0].message = mock.Mock(content=content)
        return response, None

    return handler


def _standard_stream(monkeypatch, answer_text, *, retrieve=_fake_retrieve):
    """真实 answer_query_stream 链路 + fake 检索/LLM，返回 (stream, sources)。"""
    monkeypatch.setattr(rag, "retrieve_hybrid_with_sources", retrieve)
    monkeypatch.setattr(
        "src.llm_gateway.llm_call", _fake_llm_call_content(answer_text),
    )
    return rag.answer_query_stream(
        SIMPLE_QUERY, None, None, None, DOCS, METAS,
    )


def _consume(stream) -> str:
    text = "".join(stream)
    return text


def _ids_in_sources(sources: str) -> set[str]:
    return set(re.findall(r"\[(S\d+)\]", sources))


# ═══════════════════════════════════════════════════════════════
# 共享校验器（单元）
# ═══════════════════════════════════════════════════════════════

class TestEvaluateCitationStatus:
    def test_all_valid_verified(self):
        status = citations.evaluate_citation_status(
            "根据[S1]和[S2]", ["S1", "S2"], answer_requires_citation=True,
        )
        assert status.state == CITATION_VERIFIED
        assert status.invalid_ids == ()
        assert status.missing is False

    def test_invalid_id_unverified_and_not_rewritten(self):
        status = citations.evaluate_citation_status(
            "根据[S99]", ["S1"], answer_requires_citation=True,
        )
        assert status.state == CITATION_UNVERIFIED
        assert status.invalid_ids == ("S99",)

    def test_missing_citation_unverified(self):
        status = citations.evaluate_citation_status(
            "没有任何引用", ["S1", "S2"], answer_requires_citation=True,
        )
        assert status.state == CITATION_UNVERIFIED
        assert status.missing is True

    def test_no_evidence_not_required(self):
        status = citations.evaluate_citation_status(
            "没有任何引用", [], answer_requires_citation=True,
        )
        assert status.state == CITATION_NOT_REQUIRED
        assert status.reason == "no_evidence"

    def test_answer_not_required_passthrough(self):
        status = citations.evaluate_citation_status(
            "无法连接到 API 服务，请检查网络或 BASE_URL 配置。", ["S1"],
            answer_requires_citation=False, not_required_reason="api_error",
        )
        assert status.state == CITATION_NOT_REQUIRED
        assert status.reason == "api_error"

    def test_valid_ids_strictly_used(self):
        """valid_ids 之外的任何 ID 都是非法（不因数字接近而放行）。"""
        status = citations.evaluate_citation_status(
            "根据[S2]", ["S1"], answer_requires_citation=True,
        )
        assert status.state == CITATION_UNVERIFIED
        assert status.invalid_ids == ("S2",)


class TestValidIdsForContext:
    def test_ids_match_sources_format_exactly(self):
        ids = citations.valid_citation_ids_for_context(
            [0, 1, 2], DOCS + ["d2 文本"], METAS + [
                {"chunk_id": "chunk_2", "source_id": "s2",
                 "source_name": "c.md", "source": "c.md"},
            ], context_k=2,
        )
        assert ids == ("S1", "S2")
        sources = rag.format_sources(
            [0, 1, 2], DOCS + ["d2 文本"], METAS + [
                {"chunk_id": "chunk_2", "source_id": "s2",
                 "source_name": "c.md", "source": "c.md"},
            ], context_k=2,
        )
        assert set(ids) == _ids_in_sources(sources)


# ═══════════════════════════════════════════════════════════════
# standard stream：五态 + [S99] 不改写 + sources 严格一致
# ═══════════════════════════════════════════════════════════════

class TestStandardStreamCitationStatus:
    def test_legal_citation_verified(self, monkeypatch):
        stream, sources = _standard_stream(monkeypatch, "根据[S1]和[S2]的描述。")
        text = _consume(stream)
        assert "根据[S1]和[S2]" in text
        assert stream.citation_status.state == CITATION_VERIFIED
        assert stream.citation_status.invalid_ids == ()
        assert set(stream.citation_status.valid_ids) == _ids_in_sources(sources)

    def test_illegal_citation_unverified_and_text_kept(self, monkeypatch):
        stream, sources = _standard_stream(monkeypatch, "根据[S1]和[S99]的描述。")
        text = _consume(stream)
        # 原回答文本必须保留：非法 ID 绝不被改写为合法 ID
        assert "[S99]" in text
        assert "[S2]" not in text
        assert stream.citation_status.state == CITATION_UNVERIFIED
        assert stream.citation_status.invalid_ids == ("S99",)
        assert set(stream.citation_status.valid_ids) == _ids_in_sources(sources)

    def test_missing_citation_unverified(self, monkeypatch):
        stream, _ = _standard_stream(monkeypatch, "这是一段没有引用的回答。")
        _consume(stream)
        assert stream.citation_status.state == CITATION_UNVERIFIED
        assert stream.citation_status.missing is True

    def test_refused_not_required(self, monkeypatch):
        stream, sources = _standard_stream(
            monkeypatch, "不应调用", retrieve=_fake_retrieve_weak,
        )
        text = _consume(stream)
        assert text == rag.REFUSAL_MESSAGE
        assert stream.citation_status.state == CITATION_NOT_REQUIRED
        assert stream.citation_status.reason == "refused"
        assert sources == ""

    def test_api_error_not_required(self, monkeypatch):
        from openai import APIConnectionError

        monkeypatch.setattr(rag, "retrieve_hybrid_with_sources", _fake_retrieve)
        monkeypatch.setattr(
            "src.llm_gateway.llm_call",
            mock.Mock(side_effect=APIConnectionError(request=mock.Mock())),
        )
        stream, _ = rag.answer_query_stream(
            SIMPLE_QUERY, None, None, None, DOCS, METAS,
        )
        text = _consume(stream)
        assert "无法连接到 API 服务" in text
        assert stream.citation_status.state == CITATION_NOT_REQUIRED
        assert stream.citation_status.reason == "api_error"

    def test_valid_ids_strictly_match_displayed_sources(self, monkeypatch):
        stream, sources = _standard_stream(monkeypatch, "根据[S1]和[S2]的描述。")
        _consume(stream)
        assert set(stream.citation_status.valid_ids) == {"S1", "S2"}
        assert set(stream.citation_status.valid_ids) == _ids_in_sources(sources)
        assert len(stream.citation_status.valid_ids) == 2

    def test_no_extra_llm_calls(self, monkeypatch):
        monkeypatch.setattr(rag, "retrieve_hybrid_with_sources", _fake_retrieve)
        llm_call = mock.Mock()
        llm_call.side_effect = _fake_llm_call_content("根据[S1]的描述。")
        monkeypatch.setattr("src.llm_gateway.llm_call", llm_call)
        monkeypatch.setattr(
            "src.llm_gateway.llm_call_safe",
            mock.Mock(side_effect=AssertionError("规划不应调用 LLM")),
        )
        stream, _ = rag.answer_query_stream(
            SIMPLE_QUERY, None, None, None, DOCS, METAS,
        )
        _consume(stream)
        # 仅一次生成调用；校验不发起任何额外 LLM/API 调用
        assert llm_call.call_count == 1


# ═══════════════════════════════════════════════════════════════
# graph stream：合法 / 非法 / 缺失
# ═══════════════════════════════════════════════════════════════

class TestGraphStreamCitationStatus:
    def _graph_env(self, monkeypatch, answer_text):
        from src import graph_rag

        monkeypatch.setattr(
            graph_rag, "graph_augmented_retrieve",
            lambda query, model, collection, bm25, docs, kg, alpha=0.7,
            verbose=False, all_metadatas=None: ([0, 1], DOCS, [0.9, 0.8]),
        )
        monkeypatch.setattr(
            "src.llm_gateway.llm_call", _fake_llm_call_content(answer_text),
        )
        return graph_rag

    def test_graph_legal_citation_verified(self, monkeypatch):
        graph_rag = self._graph_env(monkeypatch, "根据[S1]和[S2]的描述。")
        stream, sources = graph_rag.graph_query_stream(
            SIMPLE_QUERY, None, None, None, DOCS, METAS, None,
        )
        text = _consume(stream)
        assert "根据[S1]和[S2]" in text
        assert stream.citation_status.state == CITATION_VERIFIED
        assert set(stream.citation_status.valid_ids) == _ids_in_sources(sources)

    def test_graph_illegal_citation_unverified_and_text_kept(self, monkeypatch):
        graph_rag = self._graph_env(monkeypatch, "根据[S99]的描述。")
        stream, _ = graph_rag.graph_query_stream(
            SIMPLE_QUERY, None, None, None, DOCS, METAS, None,
        )
        text = _consume(stream)
        assert "[S99]" in text
        assert stream.citation_status.state == CITATION_UNVERIFIED
        assert stream.citation_status.invalid_ids == ("S99",)

    def test_graph_missing_citation_unverified(self, monkeypatch):
        graph_rag = self._graph_env(monkeypatch, "这是一段没有引用的回答。")
        stream, _ = graph_rag.graph_query_stream(
            SIMPLE_QUERY, None, None, None, DOCS, METAS, None,
        )
        _consume(stream)
        assert stream.citation_status.state == CITATION_UNVERIFIED
        assert stream.citation_status.missing is True


# ═══════════════════════════════════════════════════════════════
# 非流式与流式一致：[S99] 不改写 + 同一输入相同 status
# ═══════════════════════════════════════════════════════════════

class TestNonStreamParity:
    def _non_stream(self, monkeypatch, answer_text, *, sink_required=True):
        monkeypatch.setattr(rag, "retrieve_hybrid_with_sources", _fake_retrieve)
        monkeypatch.setattr(
            "src.llm_gateway.llm_call", _fake_llm_call_content(answer_text),
        )
        sink: list = []
        answer, sources = rag.answer_query(
            SIMPLE_QUERY, None, None, None, DOCS, METAS,
            _citation_status_sink=sink,
        )
        return answer, sources, sink

    def test_non_stream_keeps_illegal_citation_untouched(self, monkeypatch):
        answer, sources, sink = self._non_stream(monkeypatch, "根据[S99]的描述。")
        assert "[S99]" in answer      # 绝不被改成合法 [S#]
        assert "[S1]" not in answer
        assert sink[0].state == CITATION_UNVERIFIED
        assert sink[0].invalid_ids == ("S99",)
        assert set(sink[0].valid_ids) == _ids_in_sources(sources)

    def test_non_stream_and_stream_same_status(self, monkeypatch):
        # 非流式
        answer, sources_a, sink = self._non_stream(monkeypatch, "根据[S1]和[S2]。")
        # 流式（同一 query/docs/metas/检索/LLM 内容）
        stream, sources_b = _standard_stream(monkeypatch, "根据[S1]和[S2]。")
        text = _consume(stream)
        assert answer == text
        assert sink[0] == stream.citation_status
        assert sources_a == sources_b

    def test_non_stream_missing_citation_unverified(self, monkeypatch):
        _, _, sink = self._non_stream(monkeypatch, "没有引用的回答。")
        assert sink[0].state == CITATION_UNVERIFIED
        assert sink[0].missing is True

    def test_non_stream_without_sink_unchanged_signature(self, monkeypatch):
        """不传 sink 时行为与旧调用方一致（返回 (answer, sources)）。"""
        monkeypatch.setattr(rag, "retrieve_hybrid_with_sources", _fake_retrieve)
        monkeypatch.setattr(
            "src.llm_gateway.llm_call", _fake_llm_call_content("根据[S1]。"),
        )
        answer, sources = rag.answer_query(
            SIMPLE_QUERY, None, None, None, DOCS, METAS,
        )
        assert "根据[S1]" in answer
        assert sources

    def test_validate_and_repair_no_longer_rewrites(self):
        """非流式校验函数不再做'最近合法编号替换'。"""
        answer, validation = rag._validate_and_repair_citations(
            "根据[S99]的描述", [0, 1], DOCS, METAS,
        )
        assert answer == "根据[S99]的描述"  # 原样
        assert validation.invalid_ids == {"S99"}
        assert validation.unverified is True
        assert validation.repaired is False


# ═══════════════════════════════════════════════════════════════
# TUI：独立提示 + 不污染下一轮 history + 旧调用方兼容
# ═══════════════════════════════════════════════════════════════

class _FakeConsole:
    """输入序列 + 真实 rich 渲染输出的假 Console。"""

    def __init__(self, inputs):
        self._inputs = list(inputs)
        self._buffer = io.StringIO()
        self._rich = Console(
            file=self._buffer, force_terminal=False, width=80,
        )

    def input(self, prompt=""):
        if not self._inputs:
            raise EOFError
        return self._inputs.pop(0)

    def print(self, *args, **kwargs):
        self._rich.print(*args, **kwargs)

    @property
    def output_text(self) -> str:
        return self._buffer.getvalue()

    def clear(self):
        pass

    @contextmanager
    def status(self, *args, **kwargs):
        yield


class _FakeService:
    def __init__(self, stream, sources=""):
        self._stream = stream
        self._sources = sources
        self.history_seen: list[list] = []

    def query(self, query, history, temperature=0.1, top_k_range=(3, 20)):
        self.history_seen.append(list(history))
        return self._stream, self._sources

    def get_stats(self):
        return {"chunk_count": 0}


class TestTUIRendering:
    def test_citation_status_panel_states(self):
        from tui.screens.chat import citation_status_panel

        unverified = citation_status_panel(CitationStatus(
            state=CITATION_UNVERIFIED, valid_ids=("S1",),
            invalid_ids=("S99",),
        ))
        assert unverified is not None
        assert "引用未验证" in str(unverified.title)
        assert "S99" in str(unverified.renderable)

        verified = citation_status_panel(CitationStatus(
            state=CITATION_VERIFIED, valid_ids=("S1", "S2"),
        ))
        assert verified is not None
        assert "引用已验证" in str(verified.title)

        not_required = citation_status_panel(CitationStatus(
            state=CITATION_NOT_REQUIRED, reason="refused",
        ))
        assert not_required is None

    def test_run_chat_loop_shows_unverified_banner_and_history_clean(
            self, monkeypatch, tmp_path):
        """unverified 提示独立显示；下一轮 history 不含提示文本。"""
        from tui.screens import chat as chat_module
        from src.rag import StreamResult

        answer_text = "根据[S99]的回答正文。"
        stream = StreamResult(
            chunks=_stream_chunks(answer_text),
            valid_ids=("S1", "S2"),
        )
        service = _FakeService(stream, sources="[S1] a.md (...)")
        console = _FakeConsole(["问题A", "问题B", "/quit"])
        monkeypatch.setattr(chat_module, "_api_ok", lambda: False)

        chat_module.run_chat_loop(console, service, "standard", 0.7, 0.1,
                                  (3, 20))

        # 第一轮消费后 citation_status 已计算（unverified）
        assert stream.citation_status is not None
        assert stream.citation_status.state == CITATION_UNVERIFIED
        # 独立提示被打印
        rendered = console.output_text
        assert "引用未验证" in rendered
        # 第二轮查询收到的 history 只含纯回答（提示文本未混入）
        assert len(service.history_seen) == 2
        assert service.history_seen[1] == [("问题A", answer_text)]
        # 提示文本不在任何 history 轮次里
        for hist in service.history_seen:
            assert all("引用未验证" not in h[1] for h in hist)

    def test_old_callers_iterate_and_unpack(self):
        """旧调用方兼容：tuple 解包 + 迭代器协议。"""
        from src.rag import StreamResult

        stream = StreamResult(
            chunks=_stream_chunks("片段一", "片段二"),
            valid_ids=("S1",),
        )
        result_stream, sources = (stream, "[S1] a.md")
        assert sources
        assert list(result_stream) == ["片段一", "片段二"]
        assert stream.citation_status is not None
