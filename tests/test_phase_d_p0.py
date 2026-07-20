import json
from unittest.mock import patch

import pytest

import src.rag as rag
from src.graph_rag import KnowledgeGraph
from src.security import endpoint_validation_error, validate_endpoint, validate_document_path


def test_graph_cache_uses_schema_constrained_json(tmp_path):
    cache = tmp_path / "graph.json"
    graph = KnowledgeGraph()
    graph.entity_graph.add_edge("A", "B", weight=2)
    graph.entity_to_chunks = {"A": ["chunk-1"]}
    graph.chunk_to_entities = {"chunk-1": ["A"]}
    graph.save(str(cache), "fingerprint", 3)

    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["entity_graph"]["edges"] == [{
        "source": "A", "target": "B", "weight": 2.0,
    }]
    restored = KnowledgeGraph.load(str(cache))
    assert restored.entity_graph["A"]["B"]["weight"] == 2.0


def test_graph_cache_rejects_non_json_payload(tmp_path):
    cache = tmp_path / "graph.json"
    cache.write_bytes(b"not a trusted pickle")
    with pytest.raises(ValueError):
        KnowledgeGraph.load(str(cache))


def test_graph_client_refreshes_on_environment_change():
    import src.graph_rag as graph_rag

    graph_rag._llm_client = None
    graph_rag._llm_client_config = None
    with patch("src.graph_rag.OpenAI") as openai:
        with patch.dict("os.environ", {
            "API_KEY": "key-a", "BASE_URL": "https://a.example/v1",
        }, clear=True):
            graph_rag._get_llm_client()
        with patch.dict("os.environ", {
            "API_KEY": "key-b", "BASE_URL": "https://b.example/v1",
        }, clear=True):
            graph_rag._get_llm_client()
    assert openai.call_count == 2


def test_remote_endpoint_requires_https_for_non_localhost():
    assert endpoint_validation_error("http://remote.example/v1")
    assert validate_endpoint("http://localhost:8080/v1") == "http://localhost:8080/v1"
    assert validate_endpoint("https://remote.example/v1") == "https://remote.example/v1"


def test_document_path_limit_is_enforced(tmp_path, monkeypatch):
    document = tmp_path / "large.txt"
    document.write_text("12345", encoding="utf-8")
    monkeypatch.setattr("src.security.MAX_DOCUMENT_BYTES", 4)
    with pytest.raises(ValueError, match="大小上限"):
        validate_document_path(document)


@pytest.mark.parametrize(
    ("limit", "expected_block"),
    [(180, True), (1, False)],
)
def test_remote_context_preserves_complete_untrusted_boundaries(
    monkeypatch, limit, expected_block,
):
    """A tight budget may shorten text, but never the safety frame."""
    monkeypatch.setenv("MNEME_MAX_REMOTE_CONTEXT_CHARS", str(limit))
    context = rag._build_context(
        [0], ["x" * 1_000], [{"source": "large.txt", "chunk_id": "chunk-0"}],
    )

    assert len(context) <= limit
    if not expected_block:
        assert context == ""
        return

    assert "[Source: large.txt] [Citation: S1]\n" in context
    assert context.count('<untrusted_document chunk_id="chunk-0">') == 1
    assert context.count("</untrusted_document>") == 1
    assert context.index("<untrusted_document") < context.index(
        "</untrusted_document>"
    )


def test_remote_context_is_bounded(monkeypatch):
    monkeypatch.setenv("MNEME_MAX_REMOTE_CONTEXT_CHARS", "80")
    context = rag._build_context(
        [0], ["x" * 1_000], [{"source": "large.txt", "chunk_id": "chunk-0"}],
    )
    assert len(context) <= 80


def test_embedding_model_fallback_uses_requested_identifier():
    calls = []

    def fake_transformer(value):
        calls.append(value)
        if len(calls) == 1:
            raise RuntimeError("local cache miss")
        return "loaded"

    with patch("src.rag.SentenceTransformer", side_effect=fake_transformer), \
         patch("modelscope.snapshot_download", return_value="models/custom-model") as download:
        assert rag._load_sentence_transformer("custom-model") == "loaded"

    download.assert_called_once_with(
        "sentence-transformers/custom-model", cache_dir="models",
    )
