def test_stream_result_tail_capture_preserves_stream_text(monkeypatch):
    from src.rag import StreamResult

    calls = []
    result = StreamResult(
        chunks=iter(["answer", " text"]),
        valid_ids=(),
        capture_callback=lambda text, status: calls.append((text, status)),
    )
    assert "".join(result) == "answer text"
    assert calls == [("answer text", "not_required")]
