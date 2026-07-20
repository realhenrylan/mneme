from __future__ import annotations

import os
import json
import threading

from tui.file_watcher import FileWatcher
from src.index_queue import IndexQueue, make_snapshot
from src.metrics import GLOBAL_METRICS

from src.rag import (
    prepare_index, build_bm25_index,
    SentenceTransformer, chromadb,
    DEFAULT_COLLECTION_NAME,
    add_files_to_index,
    answer_query, answer_query_stream,
    answer_with_llm_history, answer_with_llm_history_stream,
    remove_file_from_index,
    CHROMA_DB_PATH,
    EMBEDDING_MODEL_NAME, DEFAULT_LLM_MODEL,
    _collection_exists,
    _load_sentence_transformer,
    index_fingerprint,
    load_index_manifest,
    load_bm25_snapshot,
    set_manifest_version,
    close_chroma_clients,
)
from src.graph_rag import (
    prepare_graph_index,
    graph_query_stream,
    KnowledgeGraph,
)


class LocalRagService:
    def __init__(self):
        self._model = None
        self._collection = None
        self._bm25 = None
        self._docs = None
        self._metadatas = None
        self._kg = None
        self._mode = "standard"
        self._collection_name = None
        self._watch_dir = None
        self._watcher = None
        self._lock = threading.Lock()
        self._index_queue = IndexQueue()
        self._snapshot = None

    def _ensure_model(self):
        if self._model is None:
            self._model = _load_sentence_transformer(EMBEDDING_MODEL_NAME)

    def prepare_index(
        self,
        file_paths: list[str],
        collection_name: str,
        force_rebuild: bool = False,
        mode: str = "standard",
        progress_callback=None,
    ) -> dict:
        self._mode = mode
        self._collection_name = collection_name

        if mode == "graph":
            return self._build_graph_index(file_paths, collection_name, force_rebuild, progress_callback)
        return self._build_standard_index(file_paths, collection_name, force_rebuild, progress_callback)

    def _build_standard_index(self, file_paths, collection_name, force_rebuild, progress_callback=None):
        self._ensure_model()
        model, collection, bm25, docs, metadatas = prepare_index(
            file_paths, collection_name, force_rebuild, progress_callback=progress_callback,
        )
        self._model = model
        self._collection = collection
        self._bm25 = bm25
        self._docs = docs
        self._metadatas = metadatas
        self._refresh_snapshot()
        return self.get_stats()

    def _build_graph_index(self, file_paths, collection_name, force_rebuild, progress_callback=None):
        self._ensure_model()
        model, collection, bm25, docs, metadatas, kg = prepare_graph_index(
            file_paths, collection_name, force_rebuild, progress_callback=progress_callback,
        )
        self._model = model
        self._collection = collection
        self._bm25 = bm25
        self._docs = docs
        self._metadatas = metadatas
        self._kg = kg
        self._refresh_snapshot()
        return self.get_stats()

    def _llm_model(self) -> str:
        return os.environ.get("LLM_MODEL", DEFAULT_LLM_MODEL)

    def query(
        self,
        query: str,
        history: list[tuple[str, str]],
        temperature: float = 0.1,
        top_k_range: tuple = (3, 20),
    ) -> tuple:
        return self._index_queue.run(
            self._query_from_snapshot,
            query, history, temperature, top_k_range,
        )

    def _query_from_snapshot(
        self,
        query: str,
        history: list[tuple[str, str]],
        temperature: float,
        top_k_range: tuple,
    ) -> tuple:
        snapshot = self._snapshot
        if snapshot is None:
            raise RuntimeError("index is not prepared")
        return answer_query_stream(
            query, self._model, snapshot.collection, snapshot.bm25,
            list(snapshot.documents), list(snapshot.metadatas), history,
            top_k_range=top_k_range, temperature=temperature,
            llm_model=self._llm_model(),
        )

    def graph_query(
        self,
        query: str,
        history: list[tuple[str, str]],
        alpha: float = 0.7,
        temperature: float = 0.1,
        top_k_range: tuple = (3, 50),
    ) -> tuple:
        return self._index_queue.run(
            self._graph_query_from_snapshot,
            query, history, alpha, temperature, top_k_range,
        )

    def _graph_query_from_snapshot(
        self,
        query: str,
        history: list[tuple[str, str]],
        alpha: float,
        temperature: float,
        top_k_range: tuple,
    ) -> tuple:
        snapshot = self._snapshot
        if snapshot is None:
            raise RuntimeError("index is not prepared")
        return graph_query_stream(
            query, self._model, snapshot.collection, snapshot.bm25,
            list(snapshot.documents), list(snapshot.metadatas), self._kg,
            history=history, alpha=alpha,
            temperature=temperature, top_k_range=top_k_range,
            llm_model=self._llm_model(),
        )

    def add_files(self, file_paths: list[str]) -> dict:
        return self._index_queue.run(self._add_files_sync, file_paths)

    def _add_files_sync(self, file_paths: list[str]) -> dict:
        self._ensure_model()
        bm25, docs, metadatas = add_files_to_index(
            file_paths, self._model, self._collection,
        )
        self._bm25 = bm25
        self._docs = docs
        self._metadatas = metadatas
        if self._mode == "graph":
            self._kg = KnowledgeGraph()
            ids = [
                metadata.get("chunk_id", str(index))
                for index, metadata in enumerate(metadatas)
            ]
            self._kg.build_from_chunks(docs, chunk_ids=ids, verbose=False)
            kg_file = os.path.join(CHROMA_DB_PATH, f"{self._collection_name}_kg.json")
            manifest = load_index_manifest(self._collection_name)
            self._kg.save(
                kg_file,
                index_fingerprint(self._collection.get()["ids"], metadatas),
                manifest.get("manifest_version") if manifest else None,
            )
        self._refresh_snapshot()
        return self.get_stats()

    def remove_file(self, filename: str) -> int:
        return self._index_queue.run(self._remove_file_sync, filename)

    def _remove_file_sync(self, filename: str) -> int:
        count = remove_file_from_index(filename, self._collection)
        if self._collection is not None:
            all_data = self._collection.get()
            self._docs = all_data["documents"]
            self._metadatas = all_data["metadatas"]
            manifest = load_index_manifest(self._collection_name)
            self._bm25 = set_manifest_version(
                build_bm25_index(
                    self._docs,
                    ids=all_data.get("ids", []),
                ),
                manifest.get("manifest_version") if manifest else None,
            )
            if self._mode == "graph":
                kg_file = os.path.join(CHROMA_DB_PATH, f"{self._collection_name}_kg.json")
                if self._docs:
                    self._kg = KnowledgeGraph()
                    ids = all_data.get("ids", [])
                    self._kg.build_from_chunks(
                        self._docs,
                        chunk_ids=ids,
                        verbose=False,
                    )
                    self._kg.save(
                        kg_file,
                        index_fingerprint(ids, self._metadatas),
                        manifest.get("manifest_version") if manifest else None,
                    )
                else:
                    self._kg = None
                    try:
                        os.remove(kg_file)
                    except FileNotFoundError:
                        pass
        self._refresh_snapshot()
        return count

    def get_stats(self) -> dict:
        stats = {
            "collection": self._collection_name,
            "mode": self._mode,
            "chunk_count": len(self._docs) if self._docs else 0,
            "files": [],
        }
        manifest = load_index_manifest(self._collection_name) if self._collection_name else None
        stats["manifest_version"] = manifest.get("manifest_version") if manifest else None
        stats["bm25_manifest_version"] = getattr(self._bm25, "manifest_version", None)
        stats["snapshot_manifest_version"] = (
            self._snapshot.manifest_version if self._snapshot else None
        )
        stats["index_queue"] = self._index_queue.status()
        stats["metrics"] = GLOBAL_METRICS.summary()
        if self._metadatas:
            seen = set()
            for meta in self._metadatas:
                source = meta.get("source_path") or meta.get("source", "")
                if source and source not in seen:
                    seen.add(source)
                    stats["files"].append(source)
        if self._mode == "graph" and self._kg:
            stats["entity_count"] = self._kg.entity_graph.number_of_nodes()
            stats["relation_count"] = self._kg.entity_graph.number_of_edges()
        return stats

    def _refresh_snapshot(self) -> None:
        """Publish one immutable query view after every completed mutation."""
        if self._collection is None:
            self._snapshot = None
            return
        all_data = self._collection.get()
        manifest = load_index_manifest(self._collection_name) if self._collection_name else None
        with self._lock:
            self._snapshot = make_snapshot(
                self._collection,
                self._bm25,
                all_data.get("documents", []),
                all_data.get("metadatas", []),
                all_data.get("ids", []),
                manifest.get("manifest_version") if manifest else None,
            )

    def set_mode(self, mode: str):
        self._mode = mode

    def build_kg_from_chromadb(self, collection_name: str, progress_callback=None):
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        if not _collection_exists(client, collection_name):
            raise RuntimeError(f"Collection '{collection_name}' not found.")

        collection = client.get_collection(collection_name)
        all_data = collection.get()
        docs = all_data["documents"]
        metadatas = all_data["metadatas"]
        if not docs:
            raise RuntimeError(f"Collection '{collection_name}' is empty.")

        self._docs = docs
        self._metadatas = metadatas
        self._collection = collection
        self._collection_name = collection_name
        manifest = load_index_manifest(collection_name)
        self._bm25 = set_manifest_version(
            build_bm25_index(
                docs,
                ids=all_data.get("ids", []),
                previous_snapshot=load_bm25_snapshot(collection_name),
            ),
            manifest.get("manifest_version") if manifest else None,
        )
        self._refresh_snapshot()

        kg_file = os.path.join(CHROMA_DB_PATH, f"{collection_name}_kg.json")
        current_fingerprint = index_fingerprint(all_data["ids"], metadatas)
        manifest = load_index_manifest(collection_name)
        current_manifest_version = manifest.get("manifest_version") if manifest else None
        if os.path.exists(kg_file):
            try:
                candidate = KnowledgeGraph.load(kg_file)
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                candidate = None
            if (
                candidate is not None
                and candidate.index_fingerprint == current_fingerprint
                and candidate.manifest_version == current_manifest_version
            ):
                self._kg = candidate
            else:
                self._kg = KnowledgeGraph()
                self._kg.build_from_chunks(
                    docs, chunk_ids=all_data["ids"], verbose=False,
                    progress_callback=progress_callback,
                )
                self._kg.save(kg_file, current_fingerprint, current_manifest_version)
            if progress_callback:
                progress_callback(1, 1)
            return

        self._kg = KnowledgeGraph()
        self._kg.build_from_chunks(
            docs, chunk_ids=all_data["ids"], verbose=False,
            progress_callback=progress_callback,
        )
        self._kg.save(kg_file, current_fingerprint, current_manifest_version)

    def get_kg(self):
        return self._kg

    def set_watch_dir(self, dir: str) -> None:
        self.stop_watching()
        self._watch_dir = os.path.abspath(dir)
        from dotenv import set_key
        set_key(".env", "RAG_WATCH_DIR", self._watch_dir)

    def get_watch_dir(self) -> str | None:
        return self._watch_dir

    def start_watching(self) -> None:
        if self._watcher is not None and self._watcher._running:
            return
        watch_dir = self._watch_dir
        if not watch_dir or not os.path.isdir(watch_dir):
            return
        self._watcher = FileWatcher(
            watch_dir,
            self._on_new_file,
            self._on_removed_file,
        )
        self._watcher.start()

    def stop_watching(self) -> None:
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None

    def close(self) -> None:
        """Stop background work and release Chroma's shared file handles."""
        self.stop_watching()
        self._index_queue.close()
        close_chroma_clients()
        try:
            chromadb.api.client.SharedSystemClient.clear_system_cache()
        except AttributeError:
            # Lightweight test doubles may not expose Chroma's shared cache.
            pass

    def _on_new_file(self, path: str) -> None:
        try:
            self.add_files([path])
        except Exception:
            pass

    def _on_removed_file(self, path: str) -> None:
        try:
            self.remove_file(path)
        except Exception:
            pass
