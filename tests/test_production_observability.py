import hashlib
import json
from pathlib import Path

import pytest

from src.production_observability import (
    EVENT_TYPES,
    ConsentLevel,
    TraceDeletedError,
    TraceStore,
    canonical_event_bytes,
    salted_digest,
)


def test_off_does_not_create_trace_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
    store = TraceStore.from_environment()
    assert store.consent.level is ConsentLevel.OFF
    assert store.emit("trace.begin", {"planning_profile": "sync"}) is False
    assert not (tmp_path / "data").exists()


def test_minimal_consent_persists_without_salt_or_sensitive_text(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
    store = TraceStore.from_environment()
    assert store.set_consent(ConsentLevel.MINIMAL, confirmed=True)
    trace_id = store.begin_trace("sync", 20)
    store.emit_sensitive("rewrite.decided", "rewritten secret", trace_id=trace_id)
    store.finish_trace(trace_id)
    consent = (tmp_path / "data" / "traces" / "consent.json").read_text()
    assert "secret" not in consent
    assert "salt" not in consent
    segment = next((tmp_path / "data" / "traces").glob("*.jsonl"))
    text = segment.read_text()
    assert "rewritten secret" not in text
    assert "sha256" in text


def test_canonical_line_hash_and_manifest_are_self_consistent(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
    store = TraceStore.from_environment()
    store.set_consent(ConsentLevel.MINIMAL, confirmed=True)
    trace_id = store.begin_trace("sync", 20)
    for event_type in EVENT_TYPES:
        if event_type in {"trace.begin", "trace.end"}:
            continue
        store.emit(event_type, store.minimum_payload(event_type), trace_id=trace_id)
    store.finish_trace(trace_id)
    segment = next((tmp_path / "data" / "traces").glob("*.jsonl"))
    manifest = json.loads(segment.with_suffix(".manifest.json").read_text())
    lines = segment.read_bytes().splitlines()
    assert all(b"\r" not in line for line in lines)
    assert manifest["segment_sha256"] == hashlib.sha256(segment.read_bytes()).hexdigest()
    manifest_copy = dict(manifest)
    self_sha = manifest_copy.pop("self_sha256")
    assert self_sha == hashlib.sha256(
        (json.dumps(manifest_copy, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    assert len(manifest["line_sha256"]) == len(lines)
    for line, expected in zip(lines, manifest["line_sha256"]):
        obj = json.loads(line)
        assert obj["line_sha256"] == expected
        assert canonical_event_bytes(obj, include_hash=False)


def test_invalid_paths_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        TraceStore(tmp_path / "repo" / "src")


def test_delete_writes_tombstone_and_replay_rejects(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
    store = TraceStore.from_environment()
    store.set_consent(ConsentLevel.MINIMAL, confirmed=True)
    trace_id = store.begin_trace("sync", 20)
    store.finish_trace(trace_id)
    assert store.delete_trace(trace_id)
    with pytest.raises(TraceDeletedError):
        store.replay(trace_id)
    tombstones = json.loads((tmp_path / "data" / "traces" / "tombstones.json").read_text())
    assert tombstones[0]["trace_id"] == trace_id
    assert "query" not in json.dumps(tombstones)


def test_salted_digest_has_length_and_script_without_plaintext():
    digest, length, script = salted_digest("秘密 query", b"session salt")
    assert digest == hashlib.sha256(b"session salt" + "秘密 query".encode()).hexdigest()
    assert length == 8
    assert script == "cjk"
