def test_answer_query_attempts_tail_capture_without_changing_answer(monkeypatch):
    import src.rag as rag

    events = []

    class Store:
        def begin_trace(self, planning_profile, retrieval_k):
            events.append(("begin", planning_profile, retrieval_k))
            return "trace-1"

        def emit(self, event_type, payload, *, trace_id=""):
            events.append(("emit", event_type, trace_id))

        def emit_sensitive(self, event_type, text, *, trace_id):
            events.append(("sensitive", event_type, trace_id))

        def finish_trace(self, trace_id):
            events.append(("finish", trace_id))
            return True

        def discard_trace(self, trace_id):
            events.append(("discard", trace_id))

    store = Store()
    monkeypatch.setattr("src.production_observability.TraceStore.from_environment", lambda: store)
    monkeypatch.setattr(rag, "_record_query_metric", lambda *args, **kwargs: None)
    monkeypatch.setattr(rag, "prepare_answer_evidence", lambda *args, **kwargs: type("E", (), {
        "refused": True, "top_scores": (), "top_indices": (), "context_k": 0,
        "candidate_chunk_ids": (), "context_chunk_ids": (), "context_source_ids": (),
        "refusal_reason": "retrieval",
    })())
    monkeypatch.setattr(rag, "generate_answer", lambda *args, **kwargs: (rag.REFUSAL_MESSAGE, ""))
    result = rag.answer_query("private query", None, None, None, [], [])
    assert result[0] == rag.REFUSAL_MESSAGE
    assert ("begin", "sync", None) in events
    assert any(tag == "finish" for tag, *_ in events)
    assert not any(tag == "discard" for tag, *_ in events)