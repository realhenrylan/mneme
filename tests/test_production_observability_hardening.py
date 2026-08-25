import json
import os
import time

import pytest

from src.production_observability import ConsentLevel, TraceStore, TraceDeletedError


def test_retention_prunes_old_trace_and_records_tombstone(tmp_path):
    store = TraceStore(tmp_path / "data" / "traces")
    store.set_consent(ConsentLevel.MINIMAL, confirmed=True)
    trace_id = store.begin_trace("sync", 20)
    store.finish_trace(trace_id)
    segment = tmp_path / "data" / "traces" / f"{trace_id}.jsonl"
    old = time.time() - 31 * 86400
    os.utime(segment, (old, old))
    assert store.prune(now=time.time()) == 1
    with pytest.raises(TraceDeletedError):
        store.replay(trace_id)


def test_capture_failure_is_fail_open(tmp_path, monkeypatch):
    store = TraceStore(tmp_path / "data" / "traces")
    store.set_consent(ConsentLevel.MINIMAL, confirmed=True)
    trace_id = store.begin_trace("sync", 20)
    monkeypatch.setattr(store, "_seal", lambda *args: (_ for _ in ()).throw(OSError("full")))
    assert store.finish_trace(trace_id) is False
    assert list((tmp_path / "data" / "traces").glob("*.jsonl")) == []


def test_restart_starts_new_in_memory_salt_without_persisting_it(tmp_path):
    path = tmp_path / "data" / "traces"
    first = TraceStore(path)
    first.set_consent(ConsentLevel.MINIMAL, confirmed=True)
    first_salt = first.consent.salt
    second = TraceStore(path)
    assert second.consent.level is ConsentLevel.MINIMAL
    assert second.consent.salt
    assert second.consent.salt != first_salt
    assert "salt" not in (path / "consent.json").read_text()


def test_revoke_consent_marks_active_traces_deleted(tmp_path):
    store = TraceStore(tmp_path / "data" / "traces")
    store.set_consent(ConsentLevel.MINIMAL, confirmed=True)
    trace_id = store.begin_trace("sync", 20)
    store.finish_trace(trace_id)
    store.revoke_consent()
    with pytest.raises(TraceDeletedError):
        store.replay(trace_id)


def test_event_schema_rejects_unknown_event_and_non_json_payload(tmp_path):
    store = TraceStore(tmp_path / "data" / "traces")
    store.set_consent(ConsentLevel.MINIMAL, confirmed=True)
    trace_id = store.begin_trace("sync", 20)
    with pytest.raises(ValueError):
        store.emit("unknown.event", {}, trace_id=trace_id)
    with pytest.raises(ValueError):
        store.emit("retrieve.dense", {"bad": b"secret"}, trace_id=trace_id)
