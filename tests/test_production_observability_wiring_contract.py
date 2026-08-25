"""P1.1-M 接线新行为契约：超出既有观测测试范围的负向/正向锁定。

覆盖：
- CLI delete-trace 仅接受完整 32 位 hex，拒绝模糊删除（含空参/短 ID）；
- TUI /consent 说明面板（本地、最小化、不存原文、不上传、默认关闭）与
  显式 on/off；TUI /delete-trace 同样的 32-hex 严格性；
- StreamResult 在 GeneratorExit 时经 capture_discard 清理且不触发终态回调；
- 同步 answer_query 异常路径 discard_trace 后原样重抛；
- _plan_query_runtime 的分通道事件（dense/BM25 候选含 chunk_id/rank/score、
  RRF 融合、rewrite 盐化哈希、decompose 数量）在 On 时发射、Off 时零事件。
"""
import io
import json

import pytest
from rich.console import Console

from src.production_observability import ConsentLevel, TraceStore


def _store_minimal(tmp_path, monkeypatch) -> TraceStore:
    monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
    store = TraceStore.from_environment()
    assert store.set_consent(ConsentLevel.MINIMAL, confirmed=True)
    return store


def _console() -> tuple[Console, io.StringIO]:
    buffer = io.StringIO()
    # 固定宽度：避免面板自动换行把关键词拆断
    return Console(file=buffer, width=200), buffer


# ── CLI：delete-trace 严格匹配 ─────────────────────────────────────────


def test_cli_delete_trace_rejects_partial_id(monkeypatch, capsys):
    from src.cli_loop import _handle_trace_command

    calls = []
    monkeypatch.setattr(
        "src.production_observability.TraceStore.from_environment",
        lambda: type("Store", (), {
            "delete_trace": lambda self, value: calls.append(value)})(),
    )
    assert _handle_trace_command("delete-trace abc123") is True
    assert "32" in capsys.readouterr().out
    assert _handle_trace_command("delete-trace") is True
    capsys.readouterr()
    assert _handle_trace_command("delete-trace " + "A" * 32) is True  # 大写非法
    assert calls == []


def test_cli_delete_trace_rejects_vague_keywords(monkeypatch, capsys):
    from src.cli_loop import _handle_trace_command

    calls = []
    monkeypatch.setattr(
        "src.production_observability.TraceStore.from_environment",
        lambda: type("Store", (), {
            "delete_trace": lambda self, value: calls.append(value)})(),
    )
    assert _handle_trace_command("delete-trace all") is True
    assert _handle_trace_command("delete-trace *") is True
    assert calls == []
    # 相邻词不构成该命令，交回问答流程
    assert _handle_trace_command("delete-trace-all") is False


# ── TUI：/consent 与 /delete-trace ────────────────────────────────────


def test_tui_consent_panel_shows_minimization_facts(tmp_path, monkeypatch):
    from tui.screens.chat import _handle_consent

    monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
    console, buffer = _console()
    _handle_consent(console, "/consent")
    text = buffer.getvalue()
    for keyword in ("默认关闭", "不上传", "30 天"):
        assert keyword in text
    assert not (tmp_path / "data" / "traces").exists()


def test_tui_consent_on_requires_explicit_argument_and_enables(
        tmp_path, monkeypatch):
    from tui.screens.chat import _handle_consent

    monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
    console, _ = _console()
    _handle_consent(console, "/consent on")
    store = TraceStore.from_environment()
    assert store.consent.level is ConsentLevel.MINIMAL
    console2, _ = _console()
    _handle_consent(console2, "/consent off")
    store2 = TraceStore.from_environment()
    assert store2.consent.level is ConsentLevel.OFF
    assert not list((tmp_path / "data" / "traces").glob("*.jsonl"))


def test_tui_delete_trace_strict_hex(tmp_path, monkeypatch):
    from tui.screens.chat import _handle_delete_trace

    monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
    store = _store_minimal(tmp_path, monkeypatch)
    trace_id = store.begin_trace("sync", None)
    store.finish_trace(trace_id)
    console, buffer = _console()
    _handle_delete_trace(console, f"/delete-trace {trace_id[:8]}")
    assert "32" in buffer.getvalue()
    assert (tmp_path / "data" / "traces" / f"{trace_id}.jsonl").exists()
    console2, buffer2 = _console()
    _handle_delete_trace(console2, f"/delete-trace {trace_id}")
    assert "已删除" in buffer2.getvalue()
    with pytest.raises(Exception):
        store.replay(trace_id)


# ── StreamResult：GeneratorExit 清理与终态回调 ────────────────────────


def test_stream_result_generator_exit_invokes_discard_not_callback():
    from src.rag import StreamResult

    events = []

    def chunks():
        yield "a"
        yield "b"

    result = StreamResult(
        chunks=chunks(),
        valid_ids=(),
        capture_callback=lambda text, state: events.append(("callback", text)),
        capture_discard=lambda: events.append(("discard",)),
    )
    iterator = iter(result)
    assert next(iterator) == "a"
    iterator.close()
    assert events == [("discard",)]


def test_answer_query_exception_discards_trace_and_reraises(monkeypatch):
    import src.rag as rag

    events = []

    class Store:
        def begin_trace(self, planning_profile, retrieval_k):
            events.append(("begin", planning_profile, retrieval_k))
            return "t-1"

        def emit(self, event_type, payload, *, trace_id=""):
            events.append(("emit", event_type))

        def emit_sensitive(self, event_type, text, *, trace_id):
            events.append(("sensitive", event_type))

        def finish_trace(self, trace_id):
            events.append(("finish", trace_id))
            return True

        def discard_trace(self, trace_id):
            events.append(("discard", trace_id))

    class Boom(RuntimeError):
        pass

    def failing_prepare(*args, **kwargs):
        raise Boom("retrieval exploded")

    monkeypatch.setattr(
        "src.production_observability.TraceStore.from_environment",
        lambda: Store())
    monkeypatch.setattr(rag, "prepare_answer_evidence", failing_prepare)
    with pytest.raises(Boom):
        rag.answer_query("q", None, None, None, [], [])
    assert ("begin", "sync", None) in events
    assert ("discard", "t-1") in events
    assert not any(tag == "finish" for tag, *_ in events)


# ── _plan_query_runtime：分通道事件 On 发射 / Off 零事件 ──────────────


class _FakeModel:
    def encode(self, texts):
        return [[0.0]] * len(texts)


class _FakeCollection:
    def query(self, query_embeddings, n_results):
        return {"documents": [["d"]], "distances": [[0.5]], "ids": [["c0"]]}


class _FakeBM25:
    def get_scores(self, tokens):
        return [0.4]


def _install_planning_stubs(monkeypatch, events):
    """拦截 rewrite/decompose/检索三个外部边界；其余规划逻辑真实执行。"""
    import src.rag as rag

    monkeypatch.setattr(
        rag, "retrieve_hybrid_with_sources",
        lambda query, model, collection, bm25, documents, metadatas, k=None,
        _channel_sink=None: (
            _fake_hybrid(documents, metadatas, k, _channel_sink)),
    )
    monkeypatch.setattr(
        "src.rag_query_rewriter.rewrite_query_llm",
        lambda query, **k: events.append(("rewritten",)) or (
            query + "-rw", {"changed": False}),
    )
    monkeypatch.setattr(
        "src.rag_query_decomposer.decompose_query_llm",
        lambda query, **k: ["sq1"],
    )


def _fake_hybrid(documents, metadatas, k, sink):
    if sink is not None:
        sink["dense"] = [{"chunk_id": "c0", "rank": 1, "score": 0.5}]
        sink["bm25"] = [{"chunk_id": "c0", "rank": 1, "score": 0.4}]
    return [0], ["doc0"], [0.45]


def test_plan_runtime_emits_channel_events_when_on(monkeypatch, tmp_path):
    import src.rag as rag

    events = []
    _install_planning_stubs(monkeypatch, events)
    store = _store_minimal(tmp_path, monkeypatch)
    trace_id = store.begin_trace("stream", 20)
    plan = rag._plan_query_runtime(
        "问题", _FakeModel(), _FakeCollection(), _FakeBM25(),
        ["doc0"], [{"chunk_id": "c0"}],
        llm_model="fake-model", llm_temperature=0.3,
        planning_profile="stream", retrieval_k=20,
        trace_store=store, trace_id=trace_id,
    )
    assert store.finish_trace(trace_id)
    segment = next((tmp_path / "data" / "traces").glob("*.jsonl"))
    lines = [json.loads(line) for line in segment.read_text().splitlines()]
    by_type = {}
    for event in lines:
        by_type.setdefault(event["event_type"], []).append(event)

    rewrite = by_type["rewrite.decided"][0]
    assert set(rewrite) >= {"result_sha256", "result_length", "result_script"}
    assert by_type["decompose.decided"][0]["sub_query_count"] == 1
    dense = by_type["retrieve.dense"][0]
    assert dense["candidates"][0]["chunk_id"] == "c0"
    assert dense["candidates"][0]["rank"] == 1
    bm25 = by_type["retrieve.bm25"][0]
    assert bm25["candidates"][0]["score"] == pytest.approx(0.4)
    fusion = by_type["fusion.rrf"][0]
    assert fusion["merged_count"] >= 1
    assert by_type["trace.end"][0]["end_reason"] == "normal"
    # 原文绝不落盘
    raw = segment.read_text()
    assert "问题" not in raw and "-rw" not in raw and "sq1" not in raw


def test_plan_runtime_off_emits_nothing_and_no_files(monkeypatch, tmp_path):
    import src.rag as rag

    _install_planning_stubs(monkeypatch, [])
    monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
    off_store = TraceStore.from_environment()
    trace_id = off_store.begin_trace("stream", 20)
    rag._plan_query_runtime(
        "问题", _FakeModel(), _FakeCollection(), _FakeBM25(),
        ["doc0"], [{"chunk_id": "c0"}],
        llm_model="fake-model", llm_temperature=0.3,
        planning_profile="stream", retrieval_k=20,
        trace_store=off_store, trace_id=trace_id,
    )
    off_store.finish_trace(trace_id) if trace_id else None
    assert not (tmp_path / "data" / "traces").exists()
