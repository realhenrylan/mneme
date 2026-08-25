"""Tests for Phase 6-B0.2 — snapshot index lifecycle immutability.

A snapshot-built index stays readable and can be explicitly rebuilt through
``prepare_index`` / ``build_index`` with a re-verified snapshot, but must NOT
be mutated through the lifecycle APIs:

- ``add_files_to_index`` / ``remove_file_from_index`` /
  ``sync_sources(dry_run=False)`` / ``add_sources`` raise
  ``SnapshotIndexImmutableError`` before any file parsing, model.encode,
  collection read/write, ``_commit_index_mutation`` or sidecar write;
- ``sync_sources(dry_run=True)`` and ``compute_source_diff`` stay read-only;
- the collection-level immutable marker (Chroma collection metadata) is the
  authoritative signal; old Phase 6-B0.1 manifest-only snapshot collections
  are blocked too and auto-migrate (marker written) on a legal snapshot
  rebuild;
- parser / legacy indexes keep full add/remove/sync/add_sources behavior.

Fail-closed matrix under test: marker-only (no manifest), marker + malformed
manifest, marker + plain (mismatched) manifest, and a wrong caller-supplied
``chroma_path`` all reject mutation — never downgrade to a parser collection.

Phase 6-B0.2.2: the persist-directory identity is hardened — only a real
persistent client (``settings.is_persistent is True``) with a **stable
absolute** ``persist_directory`` is verifiable. EphemeralClient
(``is_persistent=False`` with the residual ``'./chroma'`` string), remote /
mock doubles, and externally-created PersistentClients whose settings carry
only an unrecorded relative persist path all fail closed for mutation and
default parser rebuild. Mneme-created clients normalize the target directory
to a stable absolute path (``realpath(abspath(...))``) at creation time, so
their identity survives CWD switches; external absolute-path persistent
clients keep ordinary parser/legacy lifecycle behavior.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import chromadb

import pytest

import src.rag as rag
from tests.test_index_contract import (  # noqa: E402
    SOURCE_CHUNKS,
    _build_ok,
    _chunk_prefix,
    _declared_paths,
    _fixture_snapshot,
    _load,
    _sha256_bytes,
    _snapshot_tree,
)
from src.rag import canonical_source_path  # noqa: E402

# ── Fixture ────────────────────────────────────────────────────────────


@pytest.fixture()
def fx(tmp_path):
    return _fixture_snapshot(tmp_path)


@pytest.fixture(autouse=True)
def _release_test_owned_chroma():
    """B0.2.4：只释放「本测试创建」的 Chroma client / system（scoped
    cleanup），不再无差别调用全局 release_chroma_systems()。

    本模块多个测试直接创建真实外部 Chroma client（EphemeralClient /
    PersistentClient(path='rel_db') 等，不经 rag._new_persistent_client
    注册）。Chroma 的 SharedSystemClient 按 persist 标识全局缓存 system：
    相对标识（'rel_db' / 'ephemeral'）会跨测试复用错位，测试结束必须
    释放；但运行前已存在的绝对路径 external client（标识全局唯一）必须
    保持可用，不得 stop / 清空。同时保证 Windows 下 tmp_path 删除前
    文件锁已释放。
    """
    import chromadb

    pre_rag_ids = {id(c) for c in rag._CHROMA_CLIENTS}
    pre_system_ids = set(
        chromadb.api.client.SharedSystemClient._identifier_to_system.keys())
    yield
    for client in list(rag._CHROMA_CLIENTS):
        if id(client) in pre_rag_ids:
            continue  # 运行前已有：保持不动
        close = getattr(client, "close", None)
        if close is not None:
            close()
        if client in rag._CHROMA_CLIENTS:
            rag._CHROMA_CLIENTS.remove(client)
    cache = chromadb.api.client.SharedSystemClient
    for ident in set(cache._identifier_to_system.keys()) - pre_system_ids:
        system = cache._identifier_to_system.pop(ident, None)
        cache._identifier_to_refcount.pop(ident, None)
        if system is not None:
            try:
                system.stop()
            except Exception:
                pass  # 已停止的 system：忽略


class _EncodeForbidden:
    """A model whose encode() raises — proves encode is never reached."""

    def encode(self, *args, **kwargs):
        raise AssertionError("model.encode called during a rejected mutation")

    def get_embedding_dimension(self):
        return 384


def _state(collection, name: str, chroma_path: Path) -> dict:
    """Byte/content snapshot of collection + sidecars (zero-drift proof)."""
    manifest_path = chroma_path / f"{name}.manifest.json"
    bm25_path = chroma_path / f"{name}.bm25.json"
    kg_path = chroma_path / f"{name}_kg.json"
    return {
        "count": collection.count(),
        "ids": sorted(rag._collection_data(collection)["ids"]),
        "manifest": manifest_path.read_bytes() if manifest_path.exists() else None,
        "bm25": bm25_path.read_bytes() if bm25_path.exists() else None,
        "kg": kg_path.read_bytes() if kg_path.exists() else None,
    }


def _assert_state_unchanged(before: dict, after: dict) -> None:
    assert after == before


def _marker_collection(chroma_path: Path, name: str, *, manifest: dict | str | None):
    """Real Chroma collection carrying the B0.2 immutable marker (no manifest
    unless provided), for the fail-closed matrix tests."""
    chroma_path.mkdir(parents=True, exist_ok=True)
    client = rag._new_persistent_client(str(chroma_path))
    collection = client.get_or_create_collection(
        name=name,
        metadata={
            "hnsw:space": "cosine",
            rag.SNAPSHOT_INDEX_MARKER_KEY: rag.SNAPSHOT_INDEX_MARKER_VALUE,
        },
    )
    if manifest is not None:
        if isinstance(manifest, dict):
            (chroma_path / f"{name}.manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        else:  # raw bytes / malformed text
            (chroma_path / f"{name}.manifest.json").write_text(
                manifest, encoding="utf-8")
    return collection


# ── Group 1: four mutation APIs rejected on a real snapshot index ──────

def test_add_files_rejected_before_any_work(fx, tmp_path):
    """add_files_to_index on a snapshot index raises before parsing /
    encode / commit; collection count, ids, manifest, BM25 and graph cache
    bytes stay identical."""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    _, collection, _, _, _ = _build_ok(snap, chroma_path, force_rebuild=True)
    (chroma_path / "contract_test_kg.json").write_bytes(b"cached-graph")

    before = _state(collection, "contract_test", chroma_path)
    with patch("src.rag._load_index_chunks") as mock_load, \
         patch("src.rag._commit_index_mutation") as mock_commit:
        with pytest.raises(rag.SnapshotIndexImmutableError) as exc:
            rag.add_files_to_index(
                [str(fx["docs_dir"] / "beta.md")],
                _EncodeForbidden(), collection, chroma_path=str(chroma_path),
            )
        mock_load.assert_not_called()
        mock_commit.assert_not_called()
    assert "只读" in str(exc.value)
    assert "rebuild" in str(exc.value)
    _assert_state_unchanged(before, _state(collection, "contract_test", chroma_path))


def test_remove_file_rejected_before_any_work(fx, tmp_path):
    """remove_file_from_index is rejected before the collection is even read."""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    _, collection, _, _, _ = _build_ok(snap, chroma_path, force_rebuild=True)
    (chroma_path / "contract_test_kg.json").write_bytes(b"cached-graph")

    before = _state(collection, "contract_test", chroma_path)
    with patch("src.rag._collection_data") as mock_data, \
         patch("src.rag._commit_index_mutation") as mock_commit:
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.remove_file_from_index(
                str(fx["docs_dir"] / "beta.md"), collection,
                chroma_path=str(chroma_path),
            )
        mock_data.assert_not_called()
        mock_commit.assert_not_called()
    _assert_state_unchanged(before, _state(collection, "contract_test", chroma_path))


def test_sync_sources_mutation_rejected_before_diff(fx, tmp_path):
    """sync_sources(dry_run=False) is rejected at the entry — before the
    read-only diff is even computed, and with no model/encode usage."""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    _, collection, _, _, _ = _build_ok(snap, chroma_path, force_rebuild=True)
    (chroma_path / "contract_test_kg.json").write_bytes(b"cached-graph")

    before = _state(collection, "contract_test", chroma_path)
    with patch("src.rag.compute_source_diff") as mock_diff, \
         patch("src.rag._commit_index_mutation") as mock_commit:
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.sync_sources(
                snap.source_paths(), _EncodeForbidden(), collection,
                dry_run=False, chroma_path=str(chroma_path),
            )
        mock_diff.assert_not_called()
        mock_commit.assert_not_called()
    _assert_state_unchanged(before, _state(collection, "contract_test", chroma_path))


def test_add_sources_rejected_before_diff(fx, tmp_path):
    """add_sources cannot bypass add_files_to_index — rejected at the entry."""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    _, collection, _, _, _ = _build_ok(snap, chroma_path, force_rebuild=True)
    (chroma_path / "contract_test_kg.json").write_bytes(b"cached-graph")

    before = _state(collection, "contract_test", chroma_path)
    with patch("src.rag.compute_source_diff") as mock_diff, \
         patch("src.rag._commit_index_mutation") as mock_commit:
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.add_sources(
                [str(fx["docs_dir"] / "beta.md")],
                _EncodeForbidden(), collection, chroma_path=str(chroma_path),
            )
        mock_diff.assert_not_called()
        mock_commit.assert_not_called()
    _assert_state_unchanged(before, _state(collection, "contract_test", chroma_path))


# ── Group 2: read-only paths stay available ────────────────────────────

def test_sync_sources_dry_run_is_read_only(fx, tmp_path):
    """sync_sources(dry_run=True) previews the diff and writes nothing."""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    _, collection, _, _, _ = _build_ok(snap, chroma_path, force_rebuild=True)

    before = _state(collection, "contract_test", chroma_path)
    with patch("src.rag._commit_index_mutation") as mock_commit:
        result = rag.sync_sources(
            snap.source_paths(), MagicMock(), collection,
            dry_run=True, chroma_path=str(chroma_path),
        )
        mock_commit.assert_not_called()
    assert result["added"] == 0 and result["removed"] == 0
    assert set(result["diff"].keys()) == {"to_add", "to_update", "to_remove", "unchanged"}
    _assert_state_unchanged(before, _state(collection, "contract_test", chroma_path))


def test_compute_source_diff_is_read_only(fx, tmp_path):
    """compute_source_diff works on a snapshot index and writes nothing."""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    _, collection, _, _, _ = _build_ok(snap, chroma_path, force_rebuild=True)

    before = _state(collection, "contract_test", chroma_path)
    diff = rag.compute_source_diff(
        snap.source_paths(), collection, chroma_path=str(chroma_path))
    assert diff["to_add"] == [] and diff["to_update"] == []
    assert diff["to_remove"] == [] and len(diff["unchanged"]) == 3
    _assert_state_unchanged(before, _state(collection, "contract_test", chroma_path))


# ── Group 3: old Phase 6-B0.1 manifest-only snapshot blocked + migration ──

def _write_b01_manifest(snap, name: str, target_dir: Path) -> dict:
    """写旧 B0.1 形态 manifest（config.snapshot 存在、无 marker）到
    target_dir，返回 manifest dict。"""
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "manifest_version": 1,
        "collection_name": name,
        "config": {
            "embedding_model": rag.EMBEDDING_MODEL_NAME,
            "normalize": False,
            "chunking": rag.CHUNKING_CONFIG,
            "snapshot": snap.config(),
        },
        "sources": [],
        "indexed_chunk_ids": [],
    }
    (target_dir / f"{name}.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def _b01_manifest_only_collection(snap, chroma_path: Path) -> object:
    """A B0.1-shaped snapshot collection: real Chroma collection WITHOUT the
    B0.2 marker, plus a collection manifest carrying config.snapshot."""
    chroma_path.mkdir(parents=True, exist_ok=True)
    client = rag._new_persistent_client(str(chroma_path))
    collection = client.get_or_create_collection(
        name="b01_legacy", metadata={"hnsw:space": "cosine"},
    )
    _write_b01_manifest(snap, "b01_legacy", chroma_path)
    return collection


def test_old_b01_manifest_only_snapshot_blocked(fx, tmp_path):
    """A B0.1 collection (manifest config.snapshot, no marker yet) is blocked
    from lifecycle mutation — it must not be treated as a parser collection."""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    collection = _b01_manifest_only_collection(snap, chroma_path)

    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.add_files_to_index(
            [str(fx["docs_dir"] / "beta.md")], _EncodeForbidden(),
            collection, chroma_path=str(chroma_path))
    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.remove_file_from_index(
            str(fx["docs_dir"] / "beta.md"), collection,
            chroma_path=str(chroma_path))
    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.sync_sources([], _EncodeForbidden(), collection,
                         dry_run=False, chroma_path=str(chroma_path))
    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.add_sources([], _EncodeForbidden(), collection,
                        chroma_path=str(chroma_path))


def test_legal_rebuild_migrates_marker_and_blocks_mutation(fx, tmp_path):
    """A legal snapshot rebuild writes the collection-level marker (B0.1 →
    B0.2 migration); afterwards mutation is blocked via the marker."""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    collection = _b01_manifest_only_collection(snap, chroma_path)
    assert collection.metadata.get(rag.SNAPSHOT_INDEX_MARKER_KEY) is None

    model, collection, _, _, _ = rag.prepare_index(
        file_paths=snap.source_paths(),
        collection_name="b01_legacy",
        force_rebuild=True,
        snapshot=snap,
        chroma_path=str(chroma_path),
    )
    # migration: marker now persisted at collection level
    assert collection.metadata.get(rag.SNAPSHOT_INDEX_MARKER_KEY) == \
        rag.SNAPSHOT_INDEX_MARKER_VALUE
    assert collection.count() == 9
    # mutation now rejected via the marker path
    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.remove_file_from_index(
            str(fx["docs_dir"] / "beta.md"), collection,
            chroma_path=str(chroma_path))
    assert collection.count() == 9


# ── Group 4: fail-closed marker matrix (never downgrade to parser) ─────

def test_marker_only_no_manifest_rejected(tmp_path):
    """Marker present, manifest missing → conservative reject."""
    chroma_path = tmp_path / "chroma_db"
    collection = _marker_collection(chroma_path, "marker_only", manifest=None)
    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.add_files_to_index([], _EncodeForbidden(), collection,
                               chroma_path=str(chroma_path))


def test_marker_with_malformed_manifest_rejected(tmp_path):
    """Marker present, manifest malformed (not JSON) → conservative reject."""
    chroma_path = tmp_path / "chroma_db"
    collection = _marker_collection(chroma_path, "marker_bad",
                                    manifest="{not-json!!")
    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.add_files_to_index([], _EncodeForbidden(), collection,
                               chroma_path=str(chroma_path))


def test_marker_with_plain_manifest_rejected(tmp_path):
    """Marker present, manifest present but NOT a snapshot manifest
    (marker/sidecar mismatch) → conservative reject, not downgrade."""
    chroma_path = tmp_path / "chroma_db"
    collection = _marker_collection(chroma_path, "marker_plain", manifest={
        "schema_version": 1, "manifest_version": 1,
        "collection_name": "marker_plain", "config": {"embedding_model": "x"},
        "sources": [], "indexed_chunk_ids": [],
    })
    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.add_files_to_index([], _EncodeForbidden(), collection,
                               chroma_path=str(chroma_path))


def test_wrong_chroma_path_cannot_bypass_marker(fx, tmp_path):
    """A caller-supplied wrong chroma_path (manifest unreachable there) must
    not bypass the collection-level marker."""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    _, collection, _, _, _ = _build_ok(snap, chroma_path, force_rebuild=True)
    wrong_path = tmp_path / "wrong_chroma"

    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.remove_file_from_index(
            str(fx["docs_dir"] / "beta.md"), collection,
            chroma_path=str(wrong_path))
    assert collection.count() == 9


# ── Group 5: parser / legacy indexes keep full lifecycle behavior ──────

def test_parser_index_mutation_still_works(fx, tmp_path):
    """A default parser index keeps add/remove/sync/add_sources — B0.2 does
    not change ordinary lifecycle semantics."""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    new_doc = fx["docs_dir"] / "delta.md"
    new_doc.write_text("Delta document with one more paragraph of content.",
                       encoding="utf-8")
    from contextlib import redirect_stdout
    import io
    buf = io.StringIO()
    with redirect_stdout(buf):
        model, collection, bm25, docs, metas = rag.prepare_index(
            file_paths=snap.source_paths(),
            collection_name="parser_lifecycle",
            force_rebuild=True,
            chroma_path=str(chroma_path),
        )
    # no marker on a parser collection
    assert collection.metadata.get(rag.SNAPSHOT_INDEX_MARKER_KEY) is None

    count0 = collection.count()
    with redirect_stdout(buf):
        rag.add_files_to_index(
            [str(new_doc)], model, collection, chroma_path=str(chroma_path))
    assert collection.count() > count0  # add works

    with redirect_stdout(buf):
        removed = rag.remove_file_from_index(
            str(new_doc), collection, chroma_path=str(chroma_path))
    assert removed > 0 and collection.count() == count0  # remove works

    with redirect_stdout(buf):
        result = rag.sync_sources(
            snap.source_paths(), model, collection,
            dry_run=False, chroma_path=str(chroma_path))
    assert result["removed"] == 0 and result["added"] == 0  # sync works

    with redirect_stdout(buf):
        rag.add_sources(
            [str(new_doc)], model, collection, chroma_path=str(chroma_path))
    assert collection.count() > count0  # add_sources works


def test_legacy_collection_without_manifest_mutates(tmp_path):
    """A real Chroma collection with no manifest and no marker (legacy) keeps
    add/remove behavior — no false-positive rejection."""
    chroma_path = tmp_path / "chroma_db"
    chroma_path.mkdir(parents=True, exist_ok=True)
    client = rag._new_persistent_client(str(chroma_path))
    collection = client.get_or_create_collection(
        name="legacy_mut", metadata={"hnsw:space": "cosine"},
    )
    legacy_path = canonical_source_path("legacy")
    collection.add(ids=["legacy-0"], documents=["legacy doc"],
                   metadatas=[{"source_id": "legacy", "source_path": legacy_path}],
                   embeddings=[[0.1] * 384])
    assert rag.load_index_manifest("legacy_mut", chroma_path=str(chroma_path)) is None

    # removal succeeds (no snapshot evidence → not immutable), proving legacy
    # lifecycle behavior is preserved rather than false-positive rejected
    removed = rag.remove_file_from_index(
        legacy_path, collection, chroma_path=str(chroma_path))
    assert removed == 1
    assert collection.count() == 0


# ── Group 6: real frozen snapshot (skip-guarded) ───────────────────────

REAL_CHUNKS = Path(__file__).resolve().parents[1] / "data/v2-corpus/chunks/chunks.jsonl"
REAL_CHUNK_MANIFEST = REAL_CHUNKS.parent / "chunk-manifest.json"
REAL_CORPUS_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "evaluation/datasets/v2/corpus-manifest.json"
)
REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark_real = pytest.mark.skipif(
    not REAL_CHUNKS.exists() or not REAL_CORPUS_MANIFEST.exists(),
    reason="v2 corpus artifacts are local; not present in clones",
)


@pytestmark_real
def test_real_frozen_snapshot_lifecycle_immutable(tmp_path):
    """Real frozen snapshot (1006 chunks / 13 sources) in a temp Chroma:
    all four mutation APIs rejected, read-only paths work, and every attack
    leaves collection content and sidecar bytes untouched."""
    import src.index_contract as ic

    declared = [str(REPO_ROOT / d["path"]) for d in json.loads(
        REAL_CORPUS_MANIFEST.read_text(encoding="utf-8"))["documents"]]
    snap = ic.load_chunk_snapshot(
        chunks_path=REAL_CHUNKS,
        chunk_manifest_path=REAL_CHUNK_MANIFEST,
        corpus_manifest_path=REAL_CORPUS_MANIFEST,
        repo_root=REPO_ROOT,
        source_paths=declared,
    )
    assert len(snap.chunks) == 1006 and len(snap.sources) == 13
    chroma_path = tmp_path / "chroma_db"
    from contextlib import redirect_stdout
    import io
    with redirect_stdout(io.StringIO()):
        model, collection, bm25, docs, metas = rag.prepare_index(
            file_paths=snap.source_paths(),
            collection_name="real_lifecycle_probe",
            force_rebuild=True,
            snapshot=snap,
            chroma_path=str(chroma_path),
        )
    assert collection.metadata.get(rag.SNAPSHOT_INDEX_MARKER_KEY) == \
        rag.SNAPSHOT_INDEX_MARKER_VALUE

    before = _state(collection, "real_lifecycle_probe", chroma_path)
    assert before["count"] == 1006

    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.add_files_to_index([declared[0]], _EncodeForbidden(), collection,
                               chroma_path=str(chroma_path))
    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.remove_file_from_index(declared[0], collection,
                                   chroma_path=str(chroma_path))
    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.sync_sources(snap.source_paths(), _EncodeForbidden(), collection,
                         dry_run=False, chroma_path=str(chroma_path))
    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.add_sources([declared[0]], _EncodeForbidden(), collection,
                        chroma_path=str(chroma_path))
    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.remove_file_from_index(declared[0], collection,
                                   chroma_path=str(tmp_path / "wrong_chroma"))

    diff = rag.compute_source_diff(snap.source_paths(), collection,
                                   chroma_path=str(chroma_path))
    assert diff["to_add"] == [] and diff["to_update"] == []
    assert diff["to_remove"] == [] and len(diff["unchanged"]) == 13

    _assert_state_unchanged(before, _state(collection, "real_lifecycle_probe",
                                           chroma_path))


# ── Group 7: B0.2.1 — caller-supplied chroma_path cannot be trusted ─────

def _b01_with_one_row(collection, snap, fx) -> None:
    """给旧 B0.1 collection 放一行数据，使 count/ids 可被断言为零漂移。"""
    collection.add(
        ids=["b01-probe-0"], documents=["probe"],
        metadatas=[{"source_id": "b01-probe",
                    "source_path": canonical_source_path(
                        str(fx["docs_dir"] / "beta.md"))}],
        embeddings=[[0.1] * 384])


def test_b01_manifest_only_wrong_chroma_path_rejected(fx, tmp_path):
    """缺陷复现 1：旧 B0.1 manifest-only snapshot collection 被错误
    chroma_path 绕过。四个 mutation API 传错误 chroma_path 仍必须拒绝——
    guard 使用 collection 自身实际持久化目录查 manifest，绝不信任调用方
    路径；collection count/ids、正确目录 sidecar 字节不变，错误目录不
    产生任何文件，且无 parse / encode / commit。"""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    collection = _b01_manifest_only_collection(snap, chroma_path)
    _b01_with_one_row(collection, snap, fx)
    wrong_path = tmp_path / "wrong_chroma"
    wrong_path.mkdir(parents=True, exist_ok=True)

    before = _state(collection, "b01_legacy", chroma_path)
    with patch("src.rag._load_index_chunks") as mock_load, \
         patch("src.rag._collection_data") as mock_data, \
         patch("src.rag.compute_source_diff") as mock_diff, \
         patch("src.rag._commit_index_mutation") as mock_commit:
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.add_files_to_index(
                [str(fx["docs_dir"] / "beta.md")], _EncodeForbidden(),
                collection, chroma_path=str(wrong_path))
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.remove_file_from_index(
                str(fx["docs_dir"] / "beta.md"), collection,
                chroma_path=str(wrong_path))
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.sync_sources([], _EncodeForbidden(), collection,
                             dry_run=False, chroma_path=str(wrong_path))
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.add_sources([], _EncodeForbidden(), collection,
                            chroma_path=str(wrong_path))
        mock_load.assert_not_called()
        mock_data.assert_not_called()
        mock_diff.assert_not_called()
        mock_commit.assert_not_called()
    _assert_state_unchanged(before, _state(collection, "b01_legacy",
                                           chroma_path))
    assert list(wrong_path.iterdir()) == []  # 错误目录零文件


def test_b01_manifest_only_none_chroma_path_rejected(fx, tmp_path, monkeypatch):
    """缺陷复现 1（None 形态）：chroma_path=None 落到产品默认目录（不含该
    collection 的 manifest）也不能绕过旧 B0.1 manifest-only collection。"""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    collection = _b01_manifest_only_collection(snap, chroma_path)
    _b01_with_one_row(collection, snap, fx)
    default_db = tmp_path / "default_db"
    monkeypatch.setattr(rag, "CHROMA_DB_PATH", str(default_db))

    before = _state(collection, "b01_legacy", chroma_path)
    with patch("src.rag._collection_data") as mock_data, \
         patch("src.rag._commit_index_mutation") as mock_commit:
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.remove_file_from_index(
                str(fx["docs_dir"] / "beta.md"), collection)
        mock_data.assert_not_called()
        mock_commit.assert_not_called()
    _assert_state_unchanged(before, _state(collection, "b01_legacy",
                                           chroma_path))
    assert not default_db.exists() or list(default_db.iterdir()) == []


def test_parser_rebuild_of_snapshot_collection_rejected(fx, tmp_path):
    """缺陷复现 2：既有 snapshot collection（marker）被 prepare_index
    (snapshot=None) / build_index(snapshot=None) 默认 parser 路径重建会残留
    marker——修复后必须在 parser / model / collection mutation 之前拒绝，
    零写入（parse 与 model 加载均不得发生）。"""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    _, collection, _, _, _ = _build_ok(snap, chroma_path, force_rebuild=True)
    (chroma_path / "contract_test_kg.json").write_bytes(b"cached-graph")

    before = _state(collection, "contract_test", chroma_path)
    with patch("src.rag._load_index_chunks") as mock_load, \
         patch("src.rag._load_sentence_transformer") as mock_model, \
         patch("src.rag._commit_index_mutation") as mock_commit:
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.build_index(
                snap.source_paths(), "contract_test", force_rebuild=True,
                chroma_path=str(chroma_path))
        mock_load.assert_not_called()
        mock_model.assert_not_called()
        mock_commit.assert_not_called()
    with patch("src.rag._load_index_chunks") as mock_load, \
         patch("src.rag._load_sentence_transformer") as mock_model, \
         patch("src.rag._commit_index_mutation") as mock_commit:
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.prepare_index(
                snap.source_paths(), "contract_test", force_rebuild=True,
                chroma_path=str(chroma_path))
        mock_load.assert_not_called()
        mock_model.assert_not_called()
        mock_commit.assert_not_called()
    _assert_state_unchanged(before, _state(collection, "contract_test",
                                           chroma_path))


def test_parser_rebuild_of_b01_manifest_only_collection_rejected(fx, tmp_path):
    """旧 B0.1 manifest-only collection（无 marker）同样拒绝默认 parser
    重建——guard 用 collection 实际目录发现 manifest config.snapshot。"""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    collection = _b01_manifest_only_collection(snap, chroma_path)
    _b01_with_one_row(collection, snap, fx)

    before = _state(collection, "b01_legacy", chroma_path)
    with patch("src.rag._load_index_chunks") as mock_load, \
         patch("src.rag._load_sentence_transformer") as mock_model, \
         patch("src.rag._commit_index_mutation") as mock_commit:
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.prepare_index(
                snap.source_paths(), "b01_legacy", force_rebuild=True,
                chroma_path=str(chroma_path))
        mock_load.assert_not_called()
        mock_model.assert_not_called()
        mock_commit.assert_not_called()
    _assert_state_unchanged(before, _state(collection, "b01_legacy",
                                           chroma_path))


def test_unverifiable_collection_position_fail_closed():
    """无法推导 collection 真实持久化位置（非本地 client / 测试 double）
    时 fail-closed 拒绝——「不确定」绝不降级为「可修改」。"""
    collection = MagicMock()
    collection.name = "opaque_collection"
    with pytest.raises(rag.SnapshotIndexImmutableError) as exc:
        rag.add_files_to_index([], _EncodeForbidden(), collection)
    assert "持久化" in str(exc.value)
    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.sync_sources([], _EncodeForbidden(), collection, dry_run=False)


class _TinyModel:
    """最小可用 encode 模型（parser 路径边界测试用，不加载真实模型）。"""

    def encode(self, texts):
        return [[0.1] * 384 for _ in texts]

    def get_embedding_dimension(self):
        return 384


def test_wrong_chroma_path_rebuild_touches_only_wrong_dir(fx, tmp_path):
    """边界记录：build_index(snapshot=None, 错误 chroma_path) 时 client 看
    不见真实 collection（新目录语义）——真实 snapshot collection 内容与
    sidecar 零触碰，重建只发生在错误目录且产物无 marker；guard 的权威拒绝
    作用于「已持有的真实 collection」（错误路径既不绕过也不误伤）。"""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    _, collection, _, _, _ = _build_ok(snap, chroma_path, force_rebuild=True)
    wrong_path = tmp_path / "wrong_chroma"

    # B0.2.2 修正：rebuild 前保存真实 collection + sidecar 状态，
    # rebuild 后与该预先状态比较——不得自比较（原测试 rebuild 后两次
    # 现读相同值，无法证明「零触碰」）
    before_real = _state(collection, "contract_test", chroma_path)

    from contextlib import redirect_stdout
    import io
    with redirect_stdout(io.StringIO()):
        rag.build_index(
            snap.source_paths(), "contract_test", force_rebuild=True,
            model=_TinyModel(), chroma_path=str(wrong_path))
    # 真实 snapshot collection 零触碰（与 rebuild 前预先采集状态比较）
    _assert_state_unchanged(before_real,
                            _state(collection, "contract_test", chroma_path))
    # 错误目录产出的是普通 parser collection（无 marker、无 snapshot manifest）
    client = rag._new_persistent_client(str(wrong_path))
    rebuilt = client.get_collection("contract_test")
    assert rebuilt.metadata.get(rag.SNAPSHOT_INDEX_MARKER_KEY) is None
    rebuilt_manifest = rag.load_index_manifest(
        "contract_test", chroma_path=str(wrong_path))
    assert rebuilt_manifest.get("config", {}).get("snapshot") is None


# ── Group 8: B0.2.2 — persist-directory identity hardening ─────────────

def test_ephemeral_client_b01_manifest_only_rejected(fx, tmp_path):
    """缺陷复现 1（B0.2.2）：EphemeralClient 的 settings.is_persistent=False、
    persist_directory='./chroma' 只是残留串——旧 B0.1 manifest-only
    collection 的四类 mutation 与 build_index 默认 parser 重建必须
    fail-closed 拒绝（无 parse / encode / commit / collection 写入）；
    collection count/ids、正确 sidecar 字节、错误目录零漂移。

    prepare_index 无法寻址 EphemeralClient collection（其只创建
    PersistentClient），其 parser-rebuild 拒绝由 build_index(client=...)
    覆盖同一 guard 路径。"""
    snap = _load(fx, source_paths=_declared_paths(fx))
    sidecar = tmp_path / "sidecar"
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection(
        name="ephemeral_b01", metadata={"hnsw:space": "cosine"})
    _b01_with_one_row(collection, snap, fx)
    _write_b01_manifest(snap, "ephemeral_b01", sidecar)

    # 审计实测：非持久化 client 携带残留相对串，绝不可当作真实位置
    assert collection._client._system.settings.is_persistent is False
    assert collection._client._system.settings.persist_directory == "./chroma"

    before = _state(collection, "ephemeral_b01", sidecar)
    with patch("src.rag._load_index_chunks") as mock_load, \
         patch("src.rag._collection_data") as mock_data, \
         patch("src.rag.compute_source_diff") as mock_diff, \
         patch("src.rag._commit_index_mutation") as mock_commit:
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.add_files_to_index(
                [str(fx["docs_dir"] / "beta.md")], _EncodeForbidden(),
                collection, chroma_path=str(sidecar))
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.remove_file_from_index(
                str(fx["docs_dir"] / "beta.md"), collection,
                chroma_path=str(sidecar))
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.sync_sources([], _EncodeForbidden(), collection,
                             dry_run=False, chroma_path=str(sidecar))
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.add_sources([], _EncodeForbidden(), collection,
                            chroma_path=str(sidecar))
        mock_load.assert_not_called()
        mock_data.assert_not_called()
        mock_diff.assert_not_called()
        mock_commit.assert_not_called()

    # 默认 parser 重建（显式传入 ephemeral client）同样拒绝
    with patch("src.rag._load_index_chunks") as mock_load, \
         patch("src.rag._load_sentence_transformer") as mock_model, \
         patch("src.rag._commit_index_mutation") as mock_commit:
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.build_index(
                snap.source_paths(), "ephemeral_b01", force_rebuild=True,
                client=client, chroma_path=str(sidecar))
        mock_load.assert_not_called()
        mock_model.assert_not_called()
        mock_commit.assert_not_called()

    _assert_state_unchanged(before,
                            _state(collection, "ephemeral_b01", sidecar))
    wrong_path = tmp_path / "wrong_chroma"
    wrong_path.mkdir(parents=True, exist_ok=True)
    assert list(wrong_path.iterdir()) == []  # 错误目录零文件


def test_external_relative_persistent_client_fail_closed(fx, tmp_path,
                                                         monkeypatch):
    """缺陷复现 2（B0.2.2）：外部以相对路径创建的 PersistentClient
    （persist_directory 保持相对串 'rel_db'）在 CWD 切换后必须 fail-closed：
    四类 mutation（正确 chroma_path / None / 错误路径）与 prepare_index /
    build_index 默认 parser 重建均拒绝；真实 collection + sidecar 零漂移，
    新 CWD 不产生任何残留。"""
    snap = _load(fx, source_paths=_declared_paths(fx))
    dir_a = tmp_path / "dirA"
    dir_b = tmp_path / "dirB"
    dir_a.mkdir()
    dir_b.mkdir()
    monkeypatch.chdir(str(dir_a))
    client = chromadb.PersistentClient(path="rel_db")
    collection = client.get_or_create_collection(
        name="rel_b01", metadata={"hnsw:space": "cosine"})
    _b01_with_one_row(collection, snap, fx)
    _write_b01_manifest(snap, "rel_b01", dir_a / "rel_db")
    monkeypatch.chdir(str(dir_b))

    # 审计实测：创建时只记录了相对路径；mutation 时 CWD 已变，不能 abspath
    assert collection._client._system.settings.persist_directory == "rel_db"

    real_dir = dir_a / "rel_db"
    before = _state(collection, "rel_b01", real_dir)
    wrong_path = tmp_path / "wrong_chroma"
    wrong_path.mkdir(parents=True, exist_ok=True)
    with patch("src.rag._load_index_chunks") as mock_load, \
         patch("src.rag._collection_data") as mock_data, \
         patch("src.rag.compute_source_diff") as mock_diff, \
         patch("src.rag._commit_index_mutation") as mock_commit:
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.add_files_to_index(
                [str(fx["docs_dir"] / "beta.md")], _EncodeForbidden(),
                collection, chroma_path=str(real_dir))
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.remove_file_from_index(
                str(fx["docs_dir"] / "beta.md"), collection,
                chroma_path=str(real_dir))
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.sync_sources([], _EncodeForbidden(), collection,
                             dry_run=False, chroma_path=str(real_dir))
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.add_sources([], _EncodeForbidden(), collection,
                            chroma_path=str(real_dir))
        # 错误路径同样拒绝（fail-closed 发生在 caller path 使用之前）
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.remove_file_from_index(
                str(fx["docs_dir"] / "beta.md"), collection,
                chroma_path=str(wrong_path))
        mock_load.assert_not_called()
        mock_data.assert_not_called()
        mock_diff.assert_not_called()
        mock_commit.assert_not_called()

    # chroma_path=None 同样拒绝
    default_db = tmp_path / "default_db"
    monkeypatch.setattr(rag, "CHROMA_DB_PATH", str(default_db))
    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.remove_file_from_index(
            str(fx["docs_dir"] / "beta.md"), collection)

    # 默认 parser 重建：prepare_index（新 client 指向真实绝对目录）与
    # build_index（显式持有相对 client）都必须拒绝，model 不得加载
    with patch("src.rag._load_index_chunks") as mock_load, \
         patch("src.rag._load_sentence_transformer") as mock_model, \
         patch("src.rag._commit_index_mutation") as mock_commit:
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.prepare_index(
                snap.source_paths(), "rel_b01", force_rebuild=True,
                chroma_path=str(real_dir))
        with pytest.raises(rag.SnapshotIndexImmutableError):
            rag.build_index(
                snap.source_paths(), "rel_b01", force_rebuild=True,
                client=client, chroma_path=str(real_dir))
        mock_load.assert_not_called()
        mock_model.assert_not_called()
        mock_commit.assert_not_called()

    _assert_state_unchanged(before, _state(collection, "rel_b01", real_dir))
    assert not (dir_b / "rel_db").exists()  # 新 CWD 零残留


def test_mneme_relative_client_persists_absolute_location(fx, tmp_path,
                                                          monkeypatch):
    """B0.2.2：Mneme 自建 client 在创建时把目标目录规范化为稳定绝对路径
    （realpath(abspath(...))）——CWD 切换后旧 B0.1 manifest-only 判定仍落在
    真实目录（manifest 分支拒绝，而非 fail-closed），不依赖当前 CWD。"""
    snap = _load(fx, source_paths=_declared_paths(fx))
    dir_a = tmp_path / "dirA"
    dir_b = tmp_path / "dirB"
    dir_a.mkdir()
    dir_b.mkdir()
    monkeypatch.chdir(str(dir_a))
    client = rag._new_persistent_client("rel_db")
    collection = client.get_or_create_collection(
        name="mneme_rel_b01", metadata={"hnsw:space": "cosine"})
    stored = collection._client._system.settings.persist_directory
    assert os.path.isabs(stored)
    assert os.path.realpath(stored) == os.path.realpath(str(dir_a / "rel_db"))
    _b01_with_one_row(collection, snap, fx)
    _write_b01_manifest(snap, "mneme_rel_b01", dir_a / "rel_db")

    monkeypatch.chdir(str(dir_b))
    default_db = tmp_path / "default_db"
    monkeypatch.setattr(rag, "CHROMA_DB_PATH", str(default_db))

    before = _state(collection, "mneme_rel_b01", dir_a / "rel_db")
    with pytest.raises(rag.SnapshotIndexImmutableError) as exc:
        rag.remove_file_from_index(
            str(fx["docs_dir"] / "beta.md"), collection)
    # 经 manifest 分支识别（真实绝对目录），而非 fail-closed 兜底
    assert "旧 B0.1 形态" in str(exc.value)
    _assert_state_unchanged(before,
                            _state(collection, "mneme_rel_b01",
                                   dir_a / "rel_db"))


def test_external_absolute_persistent_client_lifecycle_works(fx, tmp_path):
    """B0.2.2：外部创建的真实绝对路径 PersistentClient（非 Mneme 自建）
    的普通 parser / legacy collection 生命周期不受影响——真实绝对位置可
    验证，不得 false-positive 拒绝。"""
    snap = _load(fx, source_paths=_declared_paths(fx))
    db = tmp_path / "abs_db"
    client = chromadb.PersistentClient(path=str(db))
    collection = client.get_or_create_collection(
        name="ext_abs_parser", metadata={"hnsw:space": "cosine"})
    assert collection._client._system.settings.persist_directory == str(db)

    new_doc = fx["docs_dir"] / "delta.md"
    new_doc.write_text("Delta document with one more paragraph of content.",
                       encoding="utf-8")
    from contextlib import redirect_stdout
    import io
    buf = io.StringIO()
    with redirect_stdout(buf):
        rag.build_index(
            [str(fx["docs_dir"] / "beta.md")], "ext_abs_parser",
            client=client, force_rebuild=True, model=_TinyModel(),
            chroma_path=str(db))
    assert collection.count() > 0
    assert collection.metadata.get(rag.SNAPSHOT_INDEX_MARKER_KEY) is None

    count0 = collection.count()
    with redirect_stdout(buf):
        rag.add_files_to_index(
            [str(new_doc)], _TinyModel(), collection, chroma_path=str(db))
    assert collection.count() > count0  # add works

    with redirect_stdout(buf):
        removed = rag.remove_file_from_index(
            str(new_doc), collection, chroma_path=str(db))
    assert removed > 0 and collection.count() == count0  # remove works

    with redirect_stdout(buf):
        result = rag.sync_sources(
            [str(fx["docs_dir"] / "beta.md")], _TinyModel(), collection,
            dry_run=False, chroma_path=str(db))
    assert result["removed"] == 0 and result["added"] == 0  # sync works

    with redirect_stdout(buf):
        rag.add_sources(
            [str(new_doc)], _TinyModel(), collection, chroma_path=str(db))
    assert collection.count() > count0  # add_sources works
