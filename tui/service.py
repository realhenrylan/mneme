import os
import hashlib

import sys
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

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
)
from graph_rag import (
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

    def _ensure_model(self):
        if self._model is None:
            self._model = SentenceTransformer(EMBEDDING_MODEL_NAME)

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
        return answer_query_stream(
            query, self._model, self._collection, self._bm25,
            self._docs, self._metadatas, history,
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
        return graph_query_stream(
            query, self._model, self._collection, self._bm25,
            self._docs, self._metadatas, self._kg,
            history=history, alpha=alpha,
            temperature=temperature, top_k_range=top_k_range,
            llm_model=self._llm_model(),
        )

    def add_files(self, file_paths: list[str]) -> dict:
        self._ensure_model()
        bm25, docs, metadatas = add_files_to_index(
            file_paths, self._model, self._collection,
        )
        self._bm25 = bm25
        self._docs = docs
        self._metadatas = metadatas
        if self._mode == "graph":
            self._kg = KnowledgeGraph()
            self._kg.build_from_chunks(docs, verbose=False)
            kg_file = os.path.join(CHROMA_DB_PATH, f"{self._collection_name}_kg.pkl")
            self._kg.save(kg_file)
        return self.get_stats()

    def remove_file(self, filename: str) -> int:
        return remove_file_from_index(filename, self._collection)

    def get_stats(self) -> dict:
        stats = {
            "collection": self._collection_name,
            "mode": self._mode,
            "chunk_count": len(self._docs) if self._docs else 0,
            "files": [],
        }
        if self._metadatas:
            seen = set()
            for meta in self._metadatas:
                source = meta.get("source", "")
                if source and source not in seen:
                    seen.add(source)
                    stats["files"].append(source)
        if self._mode == "graph" and self._kg:
            stats["entity_count"] = self._kg.entity_graph.number_of_nodes()
            stats["relation_count"] = self._kg.entity_graph.number_of_edges()
        return stats

    def set_mode(self, mode: str):
        """供 /mode 命令更新内部模式标记。"""
        self._mode = mode

    def build_kg_from_chromadb(self, collection_name: str, progress_callback=None):
        """
        从 ChromaDB 持久化数据重建知识图谱（含磁盘缓存检查）。
        - 优先读取 {CHROMA_DB_PATH}/{collection_name}_kg.pkl
        - 缓存命中直接加载，调用 progress_callback(1,1) 避免进度条闪烁
        - 缓存未命中则 LLM 提取实体并 save()
        - 同步 self._docs / self._metadatas，不依赖易失内存
        """
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
        self._collection_name = collection_name

        # 缓存优先
        kg_file = os.path.join(CHROMA_DB_PATH, f"{collection_name}_kg.pkl")
        if os.path.exists(kg_file):
            self._kg = KnowledgeGraph.load(kg_file)
            if progress_callback:
                progress_callback(1, 1)
            return

        # 无缓存，重建
        self._kg = KnowledgeGraph()
        self._kg.build_from_chunks(docs, verbose=False, progress_callback=progress_callback)
        self._kg.save(kg_file)

    def get_kg(self):
        return self._kg
