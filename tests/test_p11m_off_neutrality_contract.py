"""P1.1-M 行为中性契约（S2）：consent=Off 时接线零效应。

锁定三条不变式：
1. 接线后的 answer_query / answer_query_stream 在默认 Off 下与未接线
   基线输出逐字节一致（拒答文本、来源串均为字面量比对）；
2. 全程不创建 traces 目录（零写入）；
3. Off 时 TraceStore.emit 为微秒级 no-op。
"""
import time

from src.production_observability import ConsentLevel, TraceStore


def _off_store(tmp_path, monkeypatch) -> TraceStore:
    monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
    store = TraceStore.from_environment()
    assert store.consent.level is ConsentLevel.OFF
    return store


def _refused_evidence(refusal_reason: str = "retrieval"):
    return type("E", (), {
        "refused": True, "top_scores": (), "top_indices": (), "context_k": 0,
        "candidate_chunk_ids": (), "context_chunk_ids": (), "context_source_ids": (),
        "refusal_reason": refusal_reason,
    })()


def test_off_answer_query_output_is_byte_identical_and_creates_no_traces(
        tmp_path, monkeypatch):
    """Off 时同步回答与未接线基线逐字节一致，且零目录创建。"""
    import src.rag as rag

    store = _off_store(tmp_path, monkeypatch)
    monkeypatch.setattr(rag, "_record_query_metric", lambda *a, **k: None)
    monkeypatch.setattr(rag, "prepare_answer_evidence",
                        lambda *a, **k: _refused_evidence())
    monkeypatch.setattr(
        rag, "generate_answer", lambda *a, **k: (rag.REFUSAL_MESSAGE, ""))

    # 显式传入 Off store 与默认环境解析两条路径都必须零效应。
    for kwargs in ({"trace_store": store}, {}):
        answer, sources = rag.answer_query(
            "私有查询", None, None, None, [], [], **kwargs)
        assert answer == rag.REFUSAL_MESSAGE
        assert sources == ""
        assert isinstance(answer, str) and answer == (
            "未找到足够可靠的文档依据，暂时无法回答该问题。")
    assert not (tmp_path / "data" / "traces").exists()


def test_off_answer_query_stream_output_is_byte_identical_and_creates_no_traces(
        tmp_path, monkeypatch):
    """Off 时流式拒绝路径与未接线基线逐字节一致，且零目录创建。"""
    import src.rag as rag
    from src.rag import _RuntimeQueryPlan

    store = _off_store(tmp_path, monkeypatch)
    monkeypatch.setattr(
        rag, "_plan_query_runtime",
        lambda *a, **k: _RuntimeQueryPlan(
            query="q", rewritten_query="", rewrite_log={}, sub_queries=[],
            best_score={}, merged=[], scores_flat=[],
            planning_profile=k.get("planning_profile", "stream"),
            retrieval_k=None, rewrite_stage=None, decompose_stage=None),
    )

    for kwargs in ({"trace_store": store}, {}):
        result, sources = rag.answer_query_stream(
            "私有查询", None, None, None, [], [], **kwargs)
        assert sources == ""
        assert "".join(result) == "未找到足够可靠的文档依据，暂时无法回答该问题。"
    assert not (tmp_path / "data" / "traces").exists()


def test_off_emit_is_microsecond_noop(tmp_path, monkeypatch):
    """Off 时 emit 每次调用为微秒级 no-op（不抛错、恒 False、零 IO）。"""
    store = _off_store(tmp_path, monkeypatch)
    payload = {"chunk_id": "chunk_0", "rank": 1, "score": 0.5}
    iterations = 10000
    start = time.perf_counter()
    for _ in range(iterations):
        assert store.emit("retrieve.dense", payload, trace_id="x") is False
    elapsed_us = (time.perf_counter() - start) / iterations * 1e6
    assert elapsed_us < 50, f"Off emit 平均 {elapsed_us:.2f}µs，超出微秒级预算"


def test_off_begin_trace_returns_empty_without_side_effect(
        tmp_path, monkeypatch):
    store = _off_store(tmp_path, monkeypatch)
    assert store.begin_trace("sync", None) == ""
    assert not (tmp_path / "data" / "traces").exists()


def test_off_finish_and_discard_are_safe_noops(tmp_path, monkeypatch):
    store = _off_store(tmp_path, monkeypatch)
    store.finish_trace("")
    store.discard_trace("")
    assert not (tmp_path / "data" / "traces").exists()
