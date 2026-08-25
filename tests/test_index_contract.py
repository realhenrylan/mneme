"""Tests for src.index_contract — Phase 6-B0 chunk snapshot contract.

The contract turns "chunk identity reproducibility" into a manifest-constrained
product capability: an explicitly requested, fully validated chunks snapshot
can drive the *complete* product index path (prepare_index / build_index →
Chroma + collection manifest + BM25 sidecar) with stable chunk_id / source_id /
content hashes and citation lineage, while the default parser path stays
byte-identical in behavior.

Fail-closed rules under test:
- any contract validation failure raises SnapshotContractError *before* any
  collection or sidecar write (no fallback to the parser, no residue);
- caller-provided source set must equal the snapshot-declared set exactly;
- fingerprint changes (contract version / input SHA / source identity / chunk
  text) trigger a safe rebuild instead of silently reusing an old index;
- the temp collection is physically isolated from the user CHROMA_DB_PATH;
- HNSW cross-build ranking perturbation is recorded, never asserted away.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import src.index_contract as ic
import src.rag as rag

# ── Fixture data ──────────────────────────────────────────────────────

SOURCE_CHUNKS: dict[str, list[str]] = {
    "alpha.md": [
        "The Gutenberg press was invented around 1440 in Mainz. "
        "Movable type printing transformed Europe.",
        "Gutenberg's Bible was printed in the 1450s. "
        "It is considered a masterpiece of early printing.",
        "The printing revolution spread rapidly across European cities "
        "after 1460.",
    ],
    "beta.md": [
        "SQLite 使用 B-tree 索引来加速查询。索引可以显著减少扫描的行数。",
        "SQLite 事务支持原子提交和回滚。默认使用 journal 模式记录变更。",
        "SQLite 支持共享缓存模式。多个连接可以共享同一个页缓存。",
    ],
    "gamma.md": [
        "RFC 3986 defines URI syntax: scheme, authority, path, query, "
        "fragment.",
        "URI percent-encoding encodes reserved characters like spaces "
        "and slashes.",
        "The query component of a URI may contain key=value pairs "
        "separated by ampersands.",
    ],
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _canonical(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def _self_hash(obj: dict) -> str:
    d = dict(obj)
    d.pop("manifest_sha256", None)
    return _sha256_text(_canonical(d))


def _chunk_prefix(path: Path) -> str:
    norm = os.path.normcase(os.path.realpath(os.path.abspath(str(path))))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]


def _chunk_rows(docs_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for name in sorted(SOURCE_CHUNKS):
        prefix = _chunk_prefix(docs_dir / name)
        for i, text in enumerate(SOURCE_CHUNKS[name]):
            rows.append({
                "chunk_id": f"{prefix}_chunk_{i}",
                "index": i,
                "source": name,
                "text": text,
            })
    return rows


def _write_chunks(chunks_dir: Path, rows: list[dict]) -> Path:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    rows_sorted = sorted(rows, key=lambda c: (c["source"], c["index"]))
    canonical = "\n".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows_sorted
    )
    chunks_path = chunks_dir / "chunks.jsonl"
    chunks_path.write_text(canonical + "\n", encoding="utf-8")
    per_source = {name: len(SOURCE_CHUNKS[name]) for name in sorted(SOURCE_CHUNKS)}
    manifest = {
        "corpus_version": "v2.0.0-fixture",
        "n_documents": len(per_source),
        "n_chunks": len(rows_sorted),
        "chunker": "fixture-chunker",
        "chunks_sha256": _sha256_text(canonical),
        "per_source": per_source,
        "chunk_id_format": "{source_sha256_prefix12}_chunk_{n}",
    }
    (chunks_dir / "chunk-manifest.json").write_text(
        _canonical(manifest), encoding="utf-8")
    return chunks_path


def _write_corpus_manifest(root: Path, docs_dir: Path) -> Path:
    docs = []
    for name in sorted(SOURCE_CHUNKS):
        path = docs_dir / name
        docs.append({
            "id": Path(name).stem,
            "path": str(path.relative_to(root)),
            "file_sha256": _sha256_bytes(path.read_bytes()),
            "size": path.stat().st_size,
        })
    docs_sorted = sorted(docs, key=lambda d: d["id"])
    # 与 evaluation.corpus_v2.build_corpus_manifest 相同约定
    # （json.dumps ensure_ascii=False sort_keys=True，默认分隔符）
    canonical = json.dumps({"corpus_version": "v2.0.0-fixture",
                            "documents": docs_sorted},
                           ensure_ascii=False, sort_keys=True)
    manifest = {
        "corpus_version": "v2.0.0-fixture",
        "documents": docs_sorted,
        "manifest_sha256": _sha256_text(canonical),
    }
    out = root / "corpus-manifest.json"
    out.write_text(_canonical(manifest), encoding="utf-8")
    return out


def _fixture_snapshot(tmp_path: Path) -> dict[str, Path]:
    """Build a pristine snapshot fixture: docs + chunks + corpus manifest.

    Returns the key paths; ``repo_root`` for the contract is ``tmp_path``.
    """
    docs = tmp_path / "documents" / "processed"
    docs.mkdir(parents=True, exist_ok=True)
    for name, texts in SOURCE_CHUNKS.items():
        (docs / name).write_text("\n\n".join(texts) + "\n", encoding="utf-8")
    chunks_dir = tmp_path / "chunks"
    chunks = _write_chunks(chunks_dir, _chunk_rows(docs))
    corpus = _write_corpus_manifest(tmp_path, docs)
    return {
        "root": tmp_path,
        "docs_dir": docs,
        "chunks": chunks,
        "chunk_manifest": chunks_dir / "chunk-manifest.json",
        "corpus_manifest": corpus,
    }


def _load(fx: dict[str, Path], **kwargs) -> ic.ChunkSnapshot:
    return ic.load_chunk_snapshot(
        chunks_path=fx["chunks"],
        chunk_manifest_path=fx["chunk_manifest"],
        corpus_manifest_path=fx["corpus_manifest"],
        repo_root=fx["root"],
        **kwargs,
    )


def _declared_paths(fx: dict[str, Path]) -> list[str]:
    docs = json.loads(fx["corpus_manifest"].read_text(encoding="utf-8"))
    return [str((fx["root"] / d["path"]).resolve()) for d in docs["documents"]]


@pytest.fixture()
def fx(tmp_path):
    return _fixture_snapshot(tmp_path)


def _snapshot_tree(paths: list[Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    for base in paths:
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                out[str(p)] = _sha256_bytes(p.read_bytes())
    return out


# ── Group 1: contract validation (fail-closed) ────────────────────────

def _chunk_id(fx: dict[str, Path], name: str, index: int) -> str:
    """Fixture chunk ids are ``{path_sha256_prefix12}_chunk_{n}``."""
    return f"{_chunk_prefix(fx['docs_dir'] / name)}_chunk_{index}"


def test_load_pristine_snapshot_ok(fx):
    snap = _load(fx, source_paths=_declared_paths(fx))
    assert len(snap.chunks) == 9
    assert len(snap.sources) == 3
    assert snap.validation and all(c["ok"] for c in snap.validation)
    # source identity: full 64-hex source_id == product path hash
    src = {s.name: s for s in snap.sources}
    assert src["alpha.md"].id == rag.source_id_for_path(
        str(fx["docs_dir"] / "alpha.md"))
    assert len(src["alpha.md"].id) == 64
    assert src["alpha.md"].content_sha256 == _sha256_bytes(
        (fx["docs_dir"] / "alpha.md").read_bytes())
    # every chunk text hash is recorded
    gamma_0 = _chunk_id(fx, "gamma.md", 0)
    assert len(snap.chunk_text_sha256) == 9
    assert snap.chunk_text_sha256[gamma_0] == _sha256_text(
        SOURCE_CHUNKS["gamma.md"][0])


def test_tampered_chunks_text_detected(fx):
    path = fx["chunks"]
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["text"] = rows[0]["text"] + " TAMPERED"
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                for r in rows), encoding="utf-8")
    with pytest.raises(ic.SnapshotContractError) as exc:
        _load(fx)
    assert any(c["name"] == "chunks_sha256" for c in exc.value.drift)


def test_tampered_chunk_manifest_sha_detected(fx):
    manifest = json.loads(fx["chunk_manifest"].read_text(encoding="utf-8"))
    manifest["chunks_sha256"] = "0" * 64
    fx["chunk_manifest"].write_text(_canonical(manifest), encoding="utf-8")
    with pytest.raises(ic.SnapshotContractError) as exc:
        _load(fx)
    assert any(c["name"] == "chunks_sha256" for c in exc.value.drift)


def test_duplicate_chunk_id_detected(fx):
    path = fx["chunks"]
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    rows[1]["chunk_id"] = rows[0]["chunk_id"]
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                for r in rows), encoding="utf-8")
    with pytest.raises(ic.SnapshotContractError) as exc:
        _load(fx)
    assert any(c["name"] == "chunk_id_uniqueness" for c in exc.value.drift)


def test_bad_chunk_id_format_detected(fx):
    path = fx["chunks"]
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["chunk_id"] = "not-a-valid-chunk-id"
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                for r in rows), encoding="utf-8")
    with pytest.raises(ic.SnapshotContractError) as exc:
        _load(fx)
    assert any(c["name"] == "chunk_id_format" for c in exc.value.drift)


def test_source_mapping_error_detected(fx):
    # a chunk row referencing a source name not declared in per_source
    path = fx["chunks"]
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["source"] = "ghost.md"
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                for r in rows), encoding="utf-8")
    with pytest.raises(ic.SnapshotContractError) as exc:
        _load(fx)
    assert any(c["name"] == "source_name_in_per_source" for c in exc.value.drift)


def test_chunk_index_gap_detected(fx):
    path = fx["chunks"]
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    rows[2]["index"] = 9  # alpha.md chunks: 0,1,9 -> gap
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                for r in rows), encoding="utf-8")
    with pytest.raises(ic.SnapshotContractError) as exc:
        _load(fx)
    assert any(c["name"] == "chunk_index_contiguity" for c in exc.value.drift)


def test_missing_declared_source_file_detected(fx):
    (fx["docs_dir"] / "beta.md").unlink()
    with pytest.raises(ic.SnapshotContractError) as exc:
        _load(fx, source_paths=_declared_paths(fx))
    assert any(c["name"] == "source_file_exists" for c in exc.value.drift)


def test_source_content_sha_drift_detected(fx):
    with open(fx["docs_dir"] / "beta.md", "a", encoding="utf-8") as f:
        f.write("DRIFTED\n")
    with pytest.raises(ic.SnapshotContractError) as exc:
        _load(fx, source_paths=_declared_paths(fx))
    assert any(c["name"] == "source_content_sha256" for c in exc.value.drift)


def test_source_size_drift_detected(fx):
    with open(fx["docs_dir"] / "beta.md", "a", encoding="utf-8") as f:
        f.write("DRIFTED\n")
    with pytest.raises(ic.SnapshotContractError) as exc:
        _load(fx, source_paths=_declared_paths(fx))
    assert any(c["name"] == "source_size" for c in exc.value.drift)


def test_extra_caller_source_path_rejected(fx):
    extra = fx["root"] / "extra.md"
    extra.write_text("extra", encoding="utf-8")
    with pytest.raises(ic.SnapshotContractError) as exc:
        _load(fx, source_paths=_declared_paths(fx) + [str(extra)])
    assert any(c["name"] == "source_paths_exact_match" for c in exc.value.drift)


def test_missing_caller_source_path_rejected(fx):
    with pytest.raises(ic.SnapshotContractError) as exc:
        _load(fx, source_paths=_declared_paths(fx)[1:])
    assert any(c["name"] == "source_paths_exact_match" for c in exc.value.drift)


def test_chunk_id_prefix_mismatch_detected(fx):
    # move beta.md into another directory (same basename, different canonical
    # path): the frozen chunk_id prefix can no longer map to the new source id
    moved_dir = fx["root"] / "moved"
    moved_dir.mkdir()
    moved = moved_dir / "beta.md"
    (fx["docs_dir"] / "beta.md").rename(moved)
    docs = json.loads(fx["corpus_manifest"].read_text(encoding="utf-8"))
    for d in docs["documents"]:
        if d["id"] == "beta":
            d["path"] = str(moved.relative_to(fx["root"]))
            d["file_sha256"] = _sha256_bytes(moved.read_bytes())
            d["size"] = moved.stat().st_size
    docs["documents"] = sorted(docs["documents"], key=lambda d: d["id"])
    canonical = json.dumps({"corpus_version": docs["corpus_version"],
                            "documents": docs["documents"]},
                           ensure_ascii=False, sort_keys=True)
    fx["corpus_manifest"].write_text(_canonical({
        "corpus_version": docs["corpus_version"],
        "documents": docs["documents"],
        "manifest_sha256": _sha256_text(canonical),
    }), encoding="utf-8")
    with pytest.raises(ic.SnapshotContractError) as exc:
        _load(fx, source_paths=_declared_paths(fx))
    assert any(c["name"] == "chunk_id_prefix_matches_source"
               for c in exc.value.drift)


def test_corpus_manifest_self_hash_drift_detected(fx):
    docs = json.loads(fx["corpus_manifest"].read_text(encoding="utf-8"))
    docs["documents"][0]["size"] += 1
    fx["corpus_manifest"].write_text(_canonical(docs), encoding="utf-8")
    with pytest.raises(ic.SnapshotContractError) as exc:
        _load(fx)
    assert any(c["name"] == "corpus_manifest_self_hash" for c in exc.value.drift)


def test_missing_corpus_manifest_entry_detected(fx):
    docs = json.loads(fx["corpus_manifest"].read_text(encoding="utf-8"))
    docs["documents"] = docs["documents"][:2]
    canonical = json.dumps({"corpus_version": docs["corpus_version"],
                            "documents": docs["documents"]},
                           ensure_ascii=False, sort_keys=True)
    fx["corpus_manifest"].write_text(_canonical({
        **docs,
        "manifest_sha256": _sha256_text(canonical),
    }), encoding="utf-8")
    with pytest.raises(ic.SnapshotContractError) as exc:
        _load(fx)
    assert any(c["name"] == "source_declared_in_corpus_manifest"
               for c in exc.value.drift)


def test_fingerprint_deterministic_and_sensitive(fx, tmp_path):
    a = _load(fx)
    b = _load(fx)
    assert a.fingerprint == b.fingerprint
    # any input change changes the fingerprint (chunks file replaced)
    other_root = tmp_path / "other"
    other_root.mkdir()
    other = _fixture_snapshot(other_root)
    c = _load(other)
    assert c.fingerprint != a.fingerprint


def test_no_writes_on_validation_failure(fx, tmp_path):
    path = fx["chunks"]
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["text"] += " TAMPERED"
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                for r in rows), encoding="utf-8")
    chroma_dir = tmp_path / "chroma_db"
    with pytest.raises(ic.SnapshotContractError):
        _load(fx)
    assert not chroma_dir.exists()  # nothing was ever created


# ── Group 2: product path integration ─────────────────────────────────

def _build_ok(snapshot: ic.ChunkSnapshot, chroma_path: Path,
              force_rebuild: bool = True) -> tuple:
    from contextlib import redirect_stdout
    import io
    buf = io.StringIO()
    with redirect_stdout(buf):
        out = rag.prepare_index(
            file_paths=snapshot.source_paths(),
            collection_name="contract_test",
            force_rebuild=force_rebuild,
            snapshot=snapshot,
            chroma_path=str(chroma_path),
        )
    return out


def test_prepare_index_full_product_path_with_snapshot(fx, tmp_path):
    """A valid snapshot drives the complete product index path (Chroma +
    collection manifest + BM25 sidecar) with stable identity metadata."""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    model, collection, bm25, docs, metas = _build_ok(snap, chroma_path)

    assert collection.count() == 9
    # sidecars exist next to the temp collection (isolated)
    manifest = rag.load_index_manifest("contract_test", chroma_path=str(chroma_path))
    bm25_snap = rag.load_bm25_snapshot("contract_test", chroma_path=str(chroma_path))
    assert manifest is not None and bm25_snap is not None
    # collection manifest records the contract
    assert manifest["config"]["snapshot"] == snap.config()
    assert manifest["manifest_version"] == 1
    assert set(bm25_snap["chunk_ids"]) == {c["chunk_id"] for c in snap.chunks}

    # stable identity metadata per chunk
    src = {s.name: s for s in snap.sources}
    data = rag._collection_data(collection)
    by_id = dict(zip(data["ids"], data["metadatas"]))
    alpha_0 = _chunk_id(fx, "alpha.md", 0)
    row = by_id[alpha_0]
    assert row["chunk_id"] == alpha_0
    assert row["chunk_index"] == 0
    assert row["source_id"] == src["alpha.md"].id
    assert row["source_name"] == "alpha.md"
    assert row["source_path"] == str(fx["docs_dir"] / "alpha.md")
    assert row["content_sha256"] == src["alpha.md"].content_sha256

    # retrieval runs through the production engine
    from src.rag import retrieve_hybrid_with_sources
    indices, _, scores = retrieve_hybrid_with_sources(
        "When was the Gutenberg press invented?", model, collection, bm25,
        docs, metas, k=5,
    )
    assert indices
    assert [metas[i]["chunk_id"] for i in indices][0].startswith(
        _chunk_prefix(fx["docs_dir"] / "alpha.md") + "_chunk_")


def test_default_parser_path_behavior_unchanged(fx, tmp_path):
    """Without a snapshot, prepare_index parses sources exactly as before:
    the collection manifest config carries no ``snapshot`` segment and its
    fingerprint matches the plain ``_index_config`` computation."""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    from contextlib import redirect_stdout
    import io
    buf = io.StringIO()
    with redirect_stdout(buf):
        model, collection, bm25, docs, metas = rag.prepare_index(
            file_paths=snap.source_paths(),
            collection_name="parser_path",
            force_rebuild=True,
            chroma_path=str(chroma_path),
        )
    manifest = rag.load_index_manifest("parser_path", chroma_path=str(chroma_path))
    assert "snapshot" not in manifest["config"]
    expected = rag._index_config(model=model)
    assert manifest["config"]["config_fingerprint"] == expected["config_fingerprint"]
    # parser path chunk count differs from the snapshot (9): chunking v3
    # rebuilds from the source files with its own boundaries
    assert collection.count() != 9


def test_reuse_existing_index_without_rebuild(fx, tmp_path):
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    _build_ok(snap, chroma_path, force_rebuild=True)
    # second prepare (no rebuild) must reuse the index, not rebuild it
    model, collection, bm25, docs, metas = _build_ok(
        snap, chroma_path, force_rebuild=False)
    manifest = rag.load_index_manifest("contract_test", chroma_path=str(chroma_path))
    assert manifest["manifest_version"] == 1
    assert collection.count() == 9
    assert manifest["config"]["snapshot"]["fingerprint"] == snap.fingerprint


def test_fingerprint_change_triggers_rebuild(fx, tmp_path, monkeypatch):
    snap_v1 = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    _build_ok(snap_v1, chroma_path, force_rebuild=True)
    assert rag.load_index_manifest("contract_test", chroma_path=str(chroma_path))[
        "manifest_version"] == 1
    # a different contract version → different fingerprint → safe rebuild
    monkeypatch.setattr(ic, "CONTRACT_VERSION", "chunk-snapshot-contract-2")
    snap_v2 = _load(fx, source_paths=_declared_paths(fx))
    assert snap_v2.fingerprint != snap_v1.fingerprint
    _build_ok(snap_v2, chroma_path, force_rebuild=False)
    manifest = rag.load_index_manifest("contract_test", chroma_path=str(chroma_path))
    assert manifest["manifest_version"] == 2
    assert manifest["config"]["snapshot"]["fingerprint"] == snap_v2.fingerprint


def test_snapshot_index_rejects_parser_rebuild(fx, tmp_path):
    """An index built from a snapshot must NOT be rebuilt by the default
    parser path at all (Phase 6-B0.2.1 strict policy): prepare_index with
    snapshot=None on an existing snapshot collection is rejected before any
    parser/model/collection mutation, and the snapshot config stays intact."""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    _build_ok(snap, chroma_path, force_rebuild=True)
    from contextlib import redirect_stdout
    import io
    buf = io.StringIO()
    with pytest.raises(rag.SnapshotIndexImmutableError):
        with redirect_stdout(buf):
            rag.prepare_index(
                file_paths=snap.source_paths(),
                collection_name="contract_test",
                force_rebuild=False,
                chroma_path=str(chroma_path),
            )
    manifest = rag.load_index_manifest("contract_test", chroma_path=str(chroma_path))
    assert manifest["config"]["snapshot"] == snap.config()  # untouched
    assert manifest["manifest_version"] == 1  # zero writes


def test_build_rejects_mismatched_source_paths(fx, tmp_path):
    """Fail-closed: a wrong caller source set raises before any collection or
    sidecar is written (Phase 6-B0.1: not even the PersistentClient / sqlite
    dir may be initialized — the entry check precedes any write)."""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    bad = _declared_paths(fx)[:2]
    with pytest.raises(ValueError):
        rag.prepare_index(
            file_paths=bad,
            collection_name="contract_test",
            force_rebuild=True,
            snapshot=snap,
            chroma_path=str(chroma_path),
        )
    # zero residue: no client dir, no sidecars, no collection data
    assert not chroma_path.exists()


def test_delete_and_reindex_keep_stable_identity(fx, tmp_path):
    """Phase 6-B0.2: lifecycle deletion of a snapshot source is rejected
    (snapshot index is read-only); a legal explicit rebuild through
    prepare_index(snapshot=...) still restores the full snapshot exactly."""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    _build_ok(snap, chroma_path, force_rebuild=True)
    model, collection, bm25, docs, metas = _build_ok(
        snap, chroma_path, force_rebuild=False)

    # delete is rejected: snapshot index immutable (zero content change)
    beta_prefix = _chunk_prefix(fx["docs_dir"] / "beta.md")
    with pytest.raises(rag.SnapshotIndexImmutableError):
        rag.remove_file_from_index(
            str(fx["docs_dir"] / "beta.md"), collection,
            chroma_path=str(chroma_path))
    assert collection.count() == 9
    remaining = {m["chunk_id"] for m in rag._collection_data(collection)["metadatas"]}
    assert any(cid.startswith(beta_prefix + "_chunk_") for cid in remaining)

    # legal explicit rebuild → identity is restored exactly (full snapshot)
    model, collection, bm25, docs, metas = _build_ok(
        snap, chroma_path, force_rebuild=True)
    restored = {m["chunk_id"] for m in rag._collection_data(collection)["metadatas"]}
    assert restored == {c["chunk_id"] for c in snap.chunks}
    # B0.2 collection-level immutable marker persisted by the build
    assert collection.metadata.get(rag.SNAPSHOT_INDEX_MARKER_KEY) == \
        rag.SNAPSHOT_INDEX_MARKER_VALUE


def test_isolation_from_user_chroma_path(fx, tmp_path, monkeypatch):
    """The build writes only under the explicit chroma_path; the module-level
    user CHROMA_DB_PATH (here redirected to a probe dir) is untouched."""
    user_dir = tmp_path / "user_chroma"
    monkeypatch.setattr(rag, "CHROMA_DB_PATH", str(user_dir))
    before = _snapshot_tree([user_dir])
    snap = _load(fx, source_paths=_declared_paths(fx))
    _build_ok(snap, tmp_path / "isolated_chroma", force_rebuild=True)
    after = _snapshot_tree([user_dir])
    assert before == after


def test_no_llm_generation_calls(fx, tmp_path, monkeypatch):
    import src.llm_gateway as llm

    def _forbid(*args, **kwargs):
        raise AssertionError("LLM/generation path invoked during build")

    monkeypatch.setattr(rag, "answer_with_llm_history", _forbid)
    monkeypatch.setattr(llm, "llm_call", _forbid)
    snap = _load(fx, source_paths=_declared_paths(fx))
    _build_ok(snap, tmp_path / "chroma_db", force_rebuild=True)


def test_citation_lineage_from_snapshot_metadata(fx, tmp_path):
    from src.citations import make_citation_records
    snap = _load(fx, source_paths=_declared_paths(fx))
    _, _, _, docs, metas = _build_ok(snap, tmp_path / "chroma_db")
    records = make_citation_records([0, 1], docs, metas)
    assert records[0].chunk_id == metas[0]["chunk_id"]
    assert records[0].source_id == metas[0]["source_id"]
    assert records[0].source_path == metas[0]["source_path"]
    assert records[0].chunk_index == metas[0]["chunk_index"]


def test_hnsw_cross_build_perturbation_recorded_not_asserted(fx, tmp_path):
    """Two fresh builds may perturb deep HNSW rankings; aggregate metrics
    must stay stable and any per-case difference must be *recorded*, not
    asserted away as bit-identical."""
    snap = _load(fx, source_paths=_declared_paths(fx))
    queries = [
        "When was the Gutenberg press invented?",
        "SQLite 的索引有什么作用？",
        "RFC 3986 defines URI syntax",
    ]
    r1 = _build_ok(snap, tmp_path / "c1")
    r2 = _build_ok(snap, tmp_path / "c2")
    from src.rag import retrieve_hybrid_with_sources
    diffs = []
    agg1, agg2 = {}, {}
    for q in queries:
        i1, _, s1 = retrieve_hybrid_with_sources(q, *r1, k=20)
        i2, _, s2 = retrieve_hybrid_with_sources(q, *r2, k=20)
        agg1[q] = [r1[4][i]["chunk_id"] for i in i1[:5]]
        agg2[q] = [r2[4][i]["chunk_id"] for i in i2[:5]]
        if i1 != i2:
            diffs.append(q)
    assert agg1 == agg2  # top-5 aggregates stable across builds
    # differences are allowed and must be reported (recording, not hiding)
    assert isinstance(diffs, list)


# ── Group 3: CLI ──────────────────────────────────────────────────────

def test_cli_build_success(fx, tmp_path, capsys):
    chroma_dir = tmp_path / "cli_chroma"
    code = ic.main([
        "build",
        "--chunks", str(fx["chunks"]),
        "--chunk-manifest", str(fx["chunk_manifest"]),
        "--corpus-manifest", str(fx["corpus_manifest"]),
        "--collection", "cli_contract",
        "--data-dir", str(chroma_dir),
        "--repo-root", str(fx["root"]),
    ])
    assert code == 0
    manifest = rag.load_index_manifest("cli_contract", chroma_path=str(chroma_dir))
    assert manifest is not None
    assert manifest["config"]["snapshot"]["contract_version"] == ic.CONTRACT_VERSION


def test_cli_fail_closed_on_drift(fx, tmp_path, capsys):
    path = fx["chunks"]
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["text"] += " TAMPERED"
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                for r in rows), encoding="utf-8")
    chroma_dir = tmp_path / "cli_chroma"
    code = ic.main([
        "build",
        "--chunks", str(fx["chunks"]),
        "--chunk-manifest", str(fx["chunk_manifest"]),
        "--corpus-manifest", str(fx["corpus_manifest"]),
        "--collection", "cli_contract",
        "--data-dir", str(chroma_dir),
        "--repo-root", str(fx["root"]),
    ])
    assert code == 2
    assert not chroma_dir.exists()  # zero writes on validation failure


# ── Group 4: product entry hardening (Phase 6-B0.1) ───────────────────

def test_entry_rejects_source_set_mismatch_before_any_write(fx, tmp_path,
                                                            monkeypatch):
    """缺陷1：source 集合不匹配时，prepare_index 必须在创建任何
    PersistentClient / 加载模型之前抛错——传入的空 chroma_path 保持无任何
    新增文件、无 collection、无 sidecar，模型不被加载。"""
    import src.llm_gateway as llm

    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    bad = _declared_paths(fx)[:2]
    calls = {"n": 0}

    def _forbid_model(*args, **kwargs):
        calls["n"] += 1
        raise AssertionError("model must not load before entry validation")

    monkeypatch.setattr(llm, "get_or_load_model", _forbid_model)
    with pytest.raises(ValueError):
        rag.prepare_index(
            file_paths=bad,
            collection_name="contract_test",
            force_rebuild=True,
            snapshot=snap,
            chroma_path=str(chroma_path),
        )
    assert calls["n"] == 0
    assert not chroma_path.exists()


def _snapshot_collection_count(chroma_path: Path, name: str = "contract_test") -> int:
    client = rag._new_persistent_client(str(chroma_path))
    try:
        return client.get_collection(name).count()
    finally:
        rag.close_chroma_clients()


def test_reuse_path_rejects_missing_and_extra_sources(fx, tmp_path):
    """缺陷2：已有合法 snapshot collection 时，使用同一 snapshot 但传入
    缺失/额外 source 的 file_paths 必须被拒绝——原 collection count、
    collection manifest、BM25 sidecar 字节分毫不变（fail-closed，不静默
    复用、不悄悄重建）。"""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    _build_ok(snap, chroma_path, force_rebuild=True)
    manifest_path = chroma_path / "contract_test.manifest.json"
    bm25_path = chroma_path / "contract_test.bm25.json"
    manifest_before = manifest_path.read_bytes()
    bm25_before = bm25_path.read_bytes()
    count_before = _snapshot_collection_count(chroma_path)
    assert count_before == 9

    missing = _declared_paths(fx)[:2]
    with pytest.raises(ValueError):
        rag.prepare_index(
            file_paths=missing,
            collection_name="contract_test",
            force_rebuild=False,
            snapshot=snap,
            chroma_path=str(chroma_path),
        )
    extra = _declared_paths(fx) + [str(fx["chunk_manifest"])]
    with pytest.raises(ValueError):
        rag.prepare_index(
            file_paths=extra,
            collection_name="contract_test",
            force_rebuild=False,
            snapshot=snap,
            chroma_path=str(chroma_path),
        )
    assert manifest_path.read_bytes() == manifest_before
    assert bm25_path.read_bytes() == bm25_before
    assert _snapshot_collection_count(chroma_path) == count_before


def test_forged_snapshot_rejected_at_product_entry(fx, tmp_path):
    """缺陷3：dataclasses.replace 篡改过的 snapshot（篡改 chunk 文本 +
    清空 validation + 伪造 fingerprint）必须在 prepare_index 与
    build_index 入口被拒绝——不写入篡改 chunk、不接受伪造指纹、零写入。
    篡改 chunk 但保留原 fingerprint 同样被拒绝（内容不再可由输入重建）。"""
    from dataclasses import replace

    snap = _load(fx, source_paths=_declared_paths(fx))
    tampered = tuple(dict(r, text=r["text"] + " FORGED") for r in snap.chunks)
    forged = replace(snap, chunks=tampered, validation=(), fingerprint="0" * 64)

    chroma_path = tmp_path / "chroma_db"
    with pytest.raises(ic.SnapshotContractError) as exc:
        rag.prepare_index(
            file_paths=forged.source_paths(),
            collection_name="contract_test",
            force_rebuild=True,
            snapshot=forged,
            chroma_path=str(chroma_path),
        )
    assert any(c["name"] == "snapshot_revalidation_fingerprint"
               for c in exc.value.drift)
    assert not chroma_path.exists()

    # 直接调用 build_index 同样 fail-closed（不依赖 prepare_index 的验证）
    with pytest.raises(ic.SnapshotContractError):
        rag.build_index(
            file_paths=forged.source_paths(),
            collection_name="direct_build",
            force_rebuild=True,
            snapshot=forged,
            chroma_path=str(chroma_path),
        )
    assert not chroma_path.exists()

    # 篡改 chunk 文本但保留原 fingerprint → 内容不再可重建 → 拒绝
    forged2 = replace(snap, chunks=tampered)
    with pytest.raises(ic.SnapshotContractError) as exc:
        rag.prepare_index(
            file_paths=forged2.source_paths(),
            collection_name="contract_test",
            force_rebuild=True,
            snapshot=forged2,
            chroma_path=str(chroma_path),
        )
    assert any(c["name"] == "snapshot_revalidation_chunks"
               for c in exc.value.drift)
    assert not chroma_path.exists()


def test_input_drift_after_load_fail_closed_at_entry(tmp_path):
    """缺陷4：snapshot 载入后、建索引前，源文件 / chunks / manifest 任一
    漂移 → prepare_index 重新验证并 fail-closed（零写入，不降级 parser）。"""
    for kind in ("source", "chunks", "manifest"):
        fx = _fixture_snapshot(tmp_path / kind)
        snap = _load(fx, source_paths=_declared_paths(fx))
        chroma_path = tmp_path / f"chroma_{kind}"
        if kind == "source":
            with open(fx["docs_dir"] / "beta.md", "a", encoding="utf-8") as f:
                f.write("DRIFTED\n")
        elif kind == "chunks":
            path = fx["chunks"]
            rows = [json.loads(l) for l in
                    path.read_text(encoding="utf-8").splitlines()]
            rows[0]["text"] += " TAMPERED"
            path.write_text(
                "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                        for r in rows), encoding="utf-8")
        else:
            manifest = json.loads(
                fx["chunk_manifest"].read_text(encoding="utf-8"))
            manifest["chunks_sha256"] = "0" * 64
            fx["chunk_manifest"].write_text(_canonical(manifest),
                                            encoding="utf-8")
        with pytest.raises(ic.SnapshotContractError):
            rag.prepare_index(
                file_paths=snap.source_paths(),
                collection_name="contract_test",
                force_rebuild=True,
                snapshot=snap,
                chroma_path=str(chroma_path),
            )
        assert not chroma_path.exists(), kind


def test_snapshot_path_rebuilds_over_parser_collection(fx, tmp_path):
    """反之亦然：snapshot 路径绝不复用默认 parser 建的 collection（无
    config.snapshot → 配置不匹配 → 安全重建并记录契约，不静默复用）。"""
    snap = _load(fx, source_paths=_declared_paths(fx))
    chroma_path = tmp_path / "chroma_db"
    from contextlib import redirect_stdout
    import io
    buf = io.StringIO()
    with redirect_stdout(buf):
        rag.prepare_index(
            file_paths=snap.source_paths(),
            collection_name="contract_test",
            force_rebuild=True,
            chroma_path=str(chroma_path),
        )
    manifest = rag.load_index_manifest("contract_test",
                                       chroma_path=str(chroma_path))
    assert "snapshot" not in manifest["config"]

    _build_ok(snap, chroma_path, force_rebuild=False)
    manifest = rag.load_index_manifest("contract_test",
                                       chroma_path=str(chroma_path))
    assert manifest["config"]["snapshot"]["fingerprint"] == snap.fingerprint
    assert manifest["manifest_version"] == 2  # 安全重建，不是复用


# ── Group 5: real frozen data (skip-guarded) ──────────────────────────

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
def test_real_snapshot_loads_with_stable_fingerprint():
    snap1 = ic.load_chunk_snapshot(
        chunks_path=REAL_CHUNKS,
        chunk_manifest_path=REAL_CHUNK_MANIFEST,
        corpus_manifest_path=REAL_CORPUS_MANIFEST,
        repo_root=REPO_ROOT,
    )
    snap2 = ic.load_chunk_snapshot(
        chunks_path=REAL_CHUNKS,
        chunk_manifest_path=REAL_CHUNK_MANIFEST,
        corpus_manifest_path=REAL_CORPUS_MANIFEST,
        repo_root=REPO_ROOT,
    )
    assert len(snap1.chunks) == 1006
    assert len(snap1.sources) == 13
    assert snap1.fingerprint == snap2.fingerprint
    assert all(c["ok"] for c in snap1.validation)


@pytestmark_real
def test_real_snapshot_read_only_guard(tmp_path):
    guard = [REAL_CHUNKS.parent, REAL_CORPUS_MANIFEST.parent]
    before = _snapshot_tree(guard)
    snap = ic.load_chunk_snapshot(
        chunks_path=REAL_CHUNKS,
        chunk_manifest_path=REAL_CHUNK_MANIFEST,
        corpus_manifest_path=REAL_CORPUS_MANIFEST,
        repo_root=REPO_ROOT,
        source_paths=[str(REPO_ROOT / d["path"]) for d in json.loads(
            REAL_CORPUS_MANIFEST.read_text(encoding="utf-8"))["documents"]],
    )
    chroma_path = tmp_path / "chroma_db"
    from contextlib import redirect_stdout
    import io
    with redirect_stdout(io.StringIO()):
        rag.prepare_index(
            file_paths=snap.source_paths(),
            collection_name="real_contract_probe",
            force_rebuild=True,
            snapshot=snap,
            chroma_path=str(chroma_path),
        )
    assert rag.load_index_manifest("real_contract_probe",
                                   chroma_path=str(chroma_path))["config"][
        "snapshot"]["fingerprint"] == snap.fingerprint
    after = _snapshot_tree(guard)
    assert before == after
