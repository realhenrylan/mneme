"""End-to-end regression tests for the Phase B source manifest."""

import json

import pytest

import src.rag as rag
from src.graph_rag import KnowledgeGraph


class _FakeCollection:
    def __init__(self, name: str):
        self.name = name
        self.rows = {}
        self.fail_next_upsert = False

    def get(self, include=None):
        rows = [self.rows[key] for key in sorted(self.rows)]
        result = {
            "ids": [row["id"] for row in rows],
            "documents": [row["document"] for row in rows],
            "metadatas": [row["metadata"] for row in rows],
        }
        if include and "embeddings" in include:
            result["embeddings"] = [row["embedding"] for row in rows]
        return result

    def upsert(self, documents, metadatas, ids, embeddings=None):
        if self.fail_next_upsert:
            self.fail_next_upsert = False
            raise RuntimeError("simulated Chroma failure")
        for index, chunk_id in enumerate(ids):
            self.rows[chunk_id] = {
                "id": chunk_id,
                "document": documents[index],
                "metadata": metadatas[index],
                "embedding": embeddings[index] if embeddings else [0.0, 0.0, 0.0],
            }

    def delete(self, ids):
        for chunk_id in ids:
            self.rows.pop(chunk_id, None)

    def count(self):
        return len(self.rows)


class _FakeClient:
    def __init__(self):
        self.collections = {}

    def get_or_create_collection(self, name, metadata=None):
        return self.collections.setdefault(name, _FakeCollection(name))


class _FakeModel:
    def get_sentence_embedding_dimension(self):
        return 3

    def encode(self, texts):
        return [[float(index), 0.0, 1.0] for index, _ in enumerate(texts)]


def test_manifest_tracks_modify_delete_same_name_and_duplicate_text(tmp_path, monkeypatch):
    left = tmp_path / "left" / "report.txt"
    right = tmp_path / "right" / "report.txt"
    left.parent.mkdir()
    right.parent.mkdir()
    left.write_text("same reusable paragraph", encoding="utf-8")
    right.write_text("same reusable paragraph", encoding="utf-8")

    db_path = tmp_path / "db"
    monkeypatch.setattr(rag, "CHROMA_DB_PATH", str(db_path))
    client = _FakeClient()
    model = _FakeModel()

    _, collection = rag.build_index(
        [str(left), str(right)], "phase_b", client=client,
        force_rebuild=True, model=model,
    )
    manifest = rag.load_index_manifest("phase_b")
    assert manifest["manifest_version"] == 1
    assert len(manifest["sources"]) == 2
    assert len(collection.get()["ids"]) == 2
    assert len(set(collection.get()["ids"])) == 2

    left.write_text("changed left source", encoding="utf-8")
    bm25, docs, _ = rag.add_files_to_index([str(left)], model, collection)
    manifest = rag.load_index_manifest("phase_b")
    assert manifest["manifest_version"] == 2
    assert bm25.manifest_version == 2
    assert any("changed left source" in doc for doc in docs)
    assert len(manifest["sources"]) == 2

    assert rag.remove_file_from_index(str(right), collection) == 1
    manifest = rag.load_index_manifest("phase_b")
    assert manifest["manifest_version"] == 3
    assert len(manifest["sources"]) == 1
    assert manifest["sources"][0]["source_path"] == rag.canonical_source_path(str(left))
    snapshot = rag.load_bm25_snapshot("phase_b")
    assert snapshot["manifest_version"] == 3
    assert snapshot["chunk_ids"] == manifest["indexed_chunk_ids"]


def test_manifest_and_collection_roll_back_on_upsert_failure(tmp_path, monkeypatch):
    source = tmp_path / "notes.txt"
    source.write_text("before", encoding="utf-8")
    monkeypatch.setattr(rag, "CHROMA_DB_PATH", str(tmp_path / "db"))
    client = _FakeClient()
    model = _FakeModel()

    _, collection = rag.build_index(
        [str(source)], "rollback", client=client,
        force_rebuild=True, model=model,
    )
    before_manifest = rag.load_index_manifest("rollback")
    before_ids = collection.get()["ids"]
    source.write_text("after", encoding="utf-8")
    collection.fail_next_upsert = True

    with pytest.raises(RuntimeError, match="simulated Chroma failure"):
        rag.add_files_to_index([str(source)], model, collection)

    assert collection.get()["ids"] == before_ids
    assert collection.get()["documents"] == ["before"]
    assert rag.load_index_manifest("rollback") == before_manifest
    with open(rag._manifest_path("rollback"), encoding="utf-8") as stream:
        assert json.load(stream)["manifest_version"] == 1


def test_graph_cache_persists_manifest_version(tmp_path):
    cache = tmp_path / "graph.json"
    graph = KnowledgeGraph()
    graph.save(str(cache), "fingerprint", 7)

    restored = KnowledgeGraph.load(str(cache))
    assert restored.index_fingerprint == "fingerprint"
    assert restored.manifest_version == 7
