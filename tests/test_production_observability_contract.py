import json
from pathlib import Path

import pytest

from src.production_observability import ConsentLevel, TraceStore


def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
    store = TraceStore.from_environment()
    assert store.set_consent(ConsentLevel.MINIMAL, confirmed=True)
    return store


def test_minimal_emit_rejects_raw_sensitive_fields(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    trace_id = store.begin_trace("sync", None)
    with pytest.raises(ValueError, match="sensitive"):
        store.emit("context.built", {"query": "raw question"}, trace_id=trace_id)


def test_verify_integrity_checks_receipts_and_manifest(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    trace_id = store.begin_trace("sync", None)
    store.emit("context.built", {"context_ids": ["chunk-1"]}, trace_id=trace_id)
    assert store.finish_trace(trace_id)
    assert store.verify_integrity(trace_id)

    segment = Path(store.root) / f"{trace_id}.jsonl"
    segment.write_bytes(segment.read_bytes().replace(b"chunk-1", b"chunk-2"))
    with pytest.raises(ValueError, match="integrity"):
        store.verify_integrity(trace_id)


def test_exact_replay_is_explicitly_rejected(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    with pytest.raises(NotImplementedError, match="Exact replay"):
        store.exact_replay("0" * 32)


def test_consent_json_has_no_salt_or_raw_input(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    consent = json.loads((Path(store.root) / "consent.json").read_text())
    assert "salt" not in consent
    assert "query" not in json.dumps(consent)
