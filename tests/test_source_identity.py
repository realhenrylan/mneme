"""Regression tests for source/chunk identity and exact source deletion."""

from unittest.mock import MagicMock, patch

from src.rag import (
    _ensure_client_and_check_rebuild,
    build_bm25_index,
    canonical_source_path,
    format_sources,
    remove_file_from_index,
    retrieve_hybrid_with_sources,
    source_id_for_path,
)
from src.graph_rag import KnowledgeGraph


def test_same_basename_paths_have_different_source_ids(tmp_path):
    left = tmp_path / "left" / "report.pdf"
    right = tmp_path / "right" / "report.pdf"
    left.parent.mkdir()
    right.parent.mkdir()

    assert source_id_for_path(left) != source_id_for_path(right)
    assert canonical_source_path(left) != canonical_source_path(right)


def test_remove_matches_exact_source_path_not_basename(tmp_path):
    left = tmp_path / "left" / "report.pdf"
    right = tmp_path / "right" / "report.pdf"
    left.parent.mkdir()
    right.parent.mkdir()
    collection = MagicMock()
    collection.name = "source_identity_test"
    collection.get.return_value = {
        "ids": ["left-chunk", "right-chunk"],
        "metadatas": [
            {"source_id": source_id_for_path(left), "source_path": canonical_source_path(left)},
            {"source_id": source_id_for_path(right), "source_path": canonical_source_path(right)},
        ],
    }

    assert remove_file_from_index(str(left), collection) == 1
    collection.delete.assert_called_once_with(ids=["left-chunk"])


def test_duplicate_text_keeps_distinct_retrieval_rows():
    text = "the same reusable paragraph"
    documents = [text, text]
    metadatas = [
        {"chunk_id": "source-a-chunk-0", "source": "report.pdf", "source_path": "A/report.pdf"},
        {"chunk_id": "source-b-chunk-0", "source": "report.pdf", "source_path": "B/report.pdf"},
    ]
    collection = MagicMock()
    collection.query.return_value = {
        "ids": [["source-b-chunk-0", "source-a-chunk-0"]],
        "documents": [[text, text]],
        "distances": [[0.1, 0.2]],
    }
    model = MagicMock()
    model.encode.return_value.tolist.return_value = [[0.0]]

    indices, retrieved, _ = retrieve_hybrid_with_sources(
        "reusable paragraph",
        model,
        collection,
        build_bm25_index(documents),
        documents,
        metadatas,
        k=2,
    )

    assert set(indices) == {0, 1}
    assert retrieved == [text, text]
    sources = format_sources(indices, documents, metadatas)
    assert "A/report.pdf" in sources
    assert "B/report.pdf" in sources


def test_changed_source_requires_rebuild(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("new content", encoding="utf-8")
    collection = MagicMock()
    collection.get.return_value = {
        "metadatas": [{
            "source_id": source_id_for_path(source),
            "source_path": canonical_source_path(source),
            "content_sha256": "old-hash",
        }],
    }
    client = MagicMock()
    client.get_collection.return_value = collection

    with patch("src.rag.chromadb.PersistentClient", return_value=client), \
         patch("src.rag._collection_exists", return_value=True):
        _, need_build = _ensure_client_and_check_rebuild(
            "changed-source", force_rebuild=False, file_paths=[str(source)],
        )

    assert need_build is True


def test_graph_mapping_uses_chunk_ids_for_duplicate_text():
    kg = KnowledgeGraph()
    with patch(
        "src.graph_rag.extract_entities_llm_batch",
        return_value=[["SharedEntity"], ["SharedEntity"]],
    ):
        kg.build_from_chunks(
            ["same text", "same text"],
            chunk_ids=["source-a-chunk-0", "source-b-chunk-0"],
            verbose=False,
        )

    assert set(kg.get_chunks_by_entities(["SharedEntity"])) == {
        "source-a-chunk-0",
        "source-b-chunk-0",
    }


def test_source_removal_invalidates_graph_cache(tmp_path, monkeypatch):
    import src.rag as rag

    source = tmp_path / "report.pdf"
    source.write_text("content", encoding="utf-8")
    cache = tmp_path / "cache_test_kg.json"
    cache.write_bytes(b"cached")
    collection = MagicMock()
    collection.name = "cache_test"
    collection.get.return_value = {
        "ids": ["chunk-0"],
        "metadatas": [{
            "source_id": source_id_for_path(source),
            "source_path": canonical_source_path(source),
        }],
    }
    monkeypatch.setattr(rag, "CHROMA_DB_PATH", str(tmp_path))

    assert remove_file_from_index(str(source), collection) == 1
    assert not cache.exists()
