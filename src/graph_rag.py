from __future__ import annotations
import os
import time
import hashlib
import json
import math
import argparse
import tempfile
import networkx as nx
from typing import Optional, Generator
from src.rag import (
    build_bm25_index,
    build_index, ask_for_files, _collection_exists,
    _ensure_client_and_check_rebuild,
    _manifest_config_matches,
    add_files_to_index,
    retrieve_hybrid_with_sources, dynamic_top_k,
    answer_with_llm_history, answer_with_llm_history_stream,
    format_sources,
    _build_context,
    enrich_context,
    SentenceTransformer, chromadb,
    EMBEDDING_MODEL_NAME, DEFAULT_COLLECTION_NAME,
    DEFAULT_TOP_K, DEFAULT_MIN_K, DEFAULT_MAX_K,
    CHROMA_DB_PATH, DEFAULT_LLM_MODEL,
    _load_sentence_transformer,
    index_fingerprint,
    load_index_manifest,
    set_manifest_version,
    retrieval_refused, REFUSAL_MESSAGE, _record_query_metric,
)
from src.security import validate_endpoint

from openai import OpenAI
_entity_cache: dict[str, list[str]] = {}
_llm_client: OpenAI | None = None
_llm_client_config: tuple[str, str] | None = None

def _get_llm_client() -> OpenAI:
    global _llm_client, _llm_client_config
    api_key = os.getenv("API_KEY", "")
    base_url = validate_endpoint(os.getenv("BASE_URL"))
    config = (api_key, base_url)
    if _llm_client is None or _llm_client_config != config:
        _llm_client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        _llm_client_config = config
    return _llm_client

EXTRACT_PROMPT_BATCH = """从以下文本段落中分别提取实体。

段落：
{batched_texts}

请按顺序为每个段落提取实体，格式：
---段落1---
实体1
实体2
---段落2---
实体1
...
"""

def extract_entities_llm_batch(texts: list[str],
                               batch_size: int = 5,
                               progress_callback=None) -> list[list[str]]:
    """批量提取实体，带逐文本缓存

    Args:
        texts: 待提取实体的文本列表
        batch_size: 每批处理的文本数量，默认为 5
        progress_callback: 进度回调函数 (done, total)，每批处理后调用
    """

    if not texts:
        return []

    client = _get_llm_client()

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]

        uncached: list[tuple[int, str]] = []
        for j, t in enumerate(batch):
            key = hashlib.md5(t.encode()).hexdigest()
            if key in _entity_cache:
                pass
            else:
                uncached.append((j, t))

        if uncached:
            uncached_texts = [t for _, t in uncached]
            batched_text = "\n\n".join(
                f"---段落{k + 1}---\n{t[:1500]}" for k, t in enumerate(uncached_texts)
            )
            try:
                response = client.chat.completions.create(
                    model=os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL),
                    messages=[
                        {"role": "user", "content": EXTRACT_PROMPT_BATCH.format(batched_texts=batched_text)}
                    ],
                    temperature=0.2,
                )
                content = response.choices[0].message.content or ""

                parsed: list[list[str]] = []
                current: list[str] = []
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("---段落"):
                        if current:
                            parsed.append(current)
                            current = []
                    elif line:
                        # 剥离列表标记前缀（-, *, ·, 空格），保留实体文本
                        # 修复 bug：LLM 返回的 "- 人工智能" 等格式不应被丢弃
                        current.append(line.lstrip("-*· "))
                if current:
                    parsed.append(current)

                while len(parsed) < len(uncached_texts):
                    parsed.append([])
                parsed = parsed[:len(uncached_texts)]

                for (pos, text), entities in zip(uncached, parsed):
                    cache_key = hashlib.md5(text.encode()).hexdigest()
                    _entity_cache[cache_key] = entities

            except Exception as e:
                print(f"[警告] 大模型调用失败：{e}")

        # 每批处理完成后调用进度回调
        if progress_callback:
            progress_callback(min(i + batch_size, len(texts)), len(texts))

    return [_entity_cache.get(hashlib.md5(t.encode()).hexdigest(), []) for t in texts]


class KnowledgeGraph:
    def __init__(self):
        self.entity_graph = nx.Graph()
        self.entity_to_chunks: dict[str, list[str]] = {}
        self.chunk_to_entities: dict[str, list[str]] = {}
        self.index_fingerprint: str | None = None
        self.manifest_version: int | None = None

    def build_from_chunks(
            self,
            chunks: list[str],
            verbose: bool = True,
            max_workers: int = 10,          # [DEPRECATED] 保留但忽略，向后兼容
            progress_callback=None,
            batch_size: int = 5,            # 新参数追加到末尾
            min_cooccur: int = 2,           # 最小共现次数阈值
            max_entities_per_chunk: int = 20,  # 每 chunk 参与建边的最大实体数
            chunk_ids: list[str] | None = None,
    ):
        """
        从文本块构建知识图谱。

        Args:
            chunks: 文本块列表
            verbose: 是否打印进度信息
            max_workers: [DEPRECATED] 保留参数用于向后兼容，实际不再使用。
                         调用时传入此参数不会报错，但会被忽略。
            progress_callback: 进度回调函数 (done, total)
            batch_size: 批量处理的文本数量，默认为 5
            min_cooccur: 最小共现次数阈值。两个实体至少在 N 个 chunk 中共同出现
                         才建立边。默认值 2 过滤偶然共现噪音。
            max_entities_per_chunk: 每 chunk 参与建边的最大实体数。超出部分不参与
                                    建边（但仍记录在 entity_to_chunks 映射中），用于
                                    防止 chunk 中实体过多导致完全子图爆炸。默认值 20。

        Note:
            进度回调在每批处理完成后触发。如需更细粒度的进度控制，
            请直接使用 `extract_entities_llm_batch` 的 progress_callback 参数。
        """
        import warnings

        if max_workers != 10:  # 用户显式传入了非默认值
            warnings.warn(
                "max_workers 参数已废弃，将被忽略。批量处理现在使用 batch_size 参数控制。",
                DeprecationWarning,
                stacklevel=2
            )

        # Rebuilding an existing object must not retain deleted/old mappings.
        self.entity_graph.clear()
        self.entity_to_chunks.clear()
        self.chunk_to_entities.clear()
        # Preserve the historical text-key behavior for direct callers that do
        # not provide Chroma ids; production indexing always supplies ids.
        chunk_ids = chunk_ids or chunks
        if len(chunk_ids) != len(chunks):
            raise ValueError("chunk_ids must have the same length as chunks")

        if verbose:
            print(f"正在从{len(chunks)}个chunks当中提取实体")

        # 直接调用批量处理，extract_entities_llm_batch 内部已实现分批逻辑
        results = extract_entities_llm_batch(
            chunks,
            batch_size=batch_size,
            progress_callback=progress_callback,
        )

        if verbose:
            print(f"进度{len(chunks)}/{len(chunks)}")

        # ── 第一趟：逐 chunk 收集共现统计 ──────────────────────────────────
        # cooccur_counts[(u, v)] = 两个实体在不同 chunk 中共同出现的次数
        cooccur_counts: dict[tuple[str, str], int] = {}

        for chunk_id, entities in zip(chunk_ids, results):

            if not entities:
                continue

            # 1. 记录实体→chunk 映射（始终使用完整列表，不受截断影响）
            unique_all = self._record_entity_chunk_mapping(chunk_id, entities)

            # 2. 统计该 chunk 内实体对的共现次数（仅使用截断列表建边）
            self._count_cooccurrences(unique_all, max_entities_per_chunk, cooccur_counts)

        # ── 第二趟：按阈值建边 ─────────────────────────────────────────────
        self._build_edges_from_cooccurrences(cooccur_counts, min_cooccur)

        if verbose:
            print(f"Graph Stats: ")
            print(f"Entities (nodes):  {self.entity_graph.number_of_nodes()}")
            print(f"Relations (edges): {self.entity_graph.number_of_edges()}")
            print(f"Chunks with Entities: {len(self.chunk_to_entities)}")

    @staticmethod
    def _normalize_pair(u: str, v: str) -> tuple[str, str]:
        """返回按字典序排列的实体对 (u, v)，用于 dict key 的唯一性。"""
        return (u, v) if u < v else (v, u)

    def _record_entity_chunk_mapping(
            self,
            chunk: str,
            entities: list[str],
    ) -> list[str]:
        """更新 entity_to_chunks / chunk_to_entities，返回去重后的实体列表。"""
        unique_all = list(set(entities))
        self.chunk_to_entities[chunk] = unique_all
        for ent in unique_all:
            if ent not in self.entity_to_chunks:
                self.entity_to_chunks[ent] = []
            self.entity_to_chunks[ent].append(chunk)
        return unique_all

    def _count_cooccurrences(
            self,
            unique_entities: list[str],
            max_entities_per_chunk: int,
            cooccur_counts: dict[tuple[str, str], int],
    ) -> None:
        """将截断后实体对的共现次数累加到 cooccur_counts（原地修改）。"""
        capped = unique_entities[:max_entities_per_chunk]
        for i in range(len(capped)):
            for j in range(i + 1, len(capped)):
                pair = self._normalize_pair(capped[i], capped[j])
                cooccur_counts[pair] = cooccur_counts.get(pair, 0) + 1

    def _build_edges_from_cooccurrences(
            self,
            cooccur_counts: dict[tuple[str, str], int],
            min_cooccur: int,
    ) -> None:
        """根据共现统计结果，按阈值向 entity_graph 添加边。"""
        for (u, v), count in cooccur_counts.items():
            if count >= min_cooccur:
                if self.entity_graph.has_edge(u, v):
                    self.entity_graph[u][v]["weight"] += count
                else:
                    self.entity_graph.add_edge(u, v, weight=count)

    def get_related_entities(
            self,
            seed_entities: list[str],
            max_hops: int = 1,
            top_k: int = 10,
            ) -> list[tuple[str, float]]:
        if not seed_entities:
            return []
        lower_to_node = {n.lower(): n for n in self.entity_graph.nodes()}
        seed_nodes = [lower_to_node[e.lower()] for e in seed_entities if e.lower() in lower_to_node]

        if not seed_nodes:
            return []

        related = {}
        visited = set(seed_nodes)

        for node in seed_nodes:
            related[node] = 2.0

        current_ring = set(seed_nodes)

        for hop in range(max_hops):
            next_ring = set()
            for node in current_ring:
                for neighbor in self.entity_graph.neighbors(node):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_ring.add(neighbor)
                        weight = self.entity_graph[node][neighbor].get("weight", 1)
                        related[neighbor] = related.get(neighbor, 0) + weight / (hop + 2)
            current_ring = next_ring

        sorted_related = sorted(related.items(), key = lambda x: x[1], reverse=True)
        return sorted_related[:top_k]

    def get_chunks_by_entities(
            self,
            entities: list[str],
            max_chunks: int = 10,
    ) -> list[str]:
        chunk_scores: dict[str, float] = {}

        for ent in entities:
            chunks = self.entity_to_chunks.get(ent, [])
            for chunk in chunks:
                chunk_scores[chunk] = chunk_scores.get(chunk, 0) + 1

        sorted_chunks = sorted(chunk_scores.items(), key = lambda x: x[1], reverse = True)
        return [chunk for chunk, _ in sorted_chunks[:max_chunks]]

    def save(
        self,
        filepath: str,
        index_fingerprint_value: str | None = None,
        manifest_version: int | None = None,
    ):
        if index_fingerprint_value is not None:
            self.index_fingerprint = index_fingerprint_value
        if manifest_version is not None:
            self.manifest_version = manifest_version
        directory = os.path.dirname(filepath) or "."
        os.makedirs(directory, exist_ok=True)
        temporary_path = None
        payload = {
            "schema_version": 2,
            "entity_graph": {
                "nodes": sorted(str(node) for node in self.entity_graph.nodes),
                "edges": [
                    {
                        "source": str(source),
                        "target": str(target),
                        "weight": float(data.get("weight", 1.0)),
                    }
                    for source, target, data in self.entity_graph.edges(data=True)
                ],
            },
            "entity_to_chunks": {
                str(entity): [str(chunk) for chunk in chunks]
                for entity, chunks in self.entity_to_chunks.items()
            },
            "chunk_to_entities": {
                str(chunk): [str(entity) for entity in entities]
                for chunk, entities in self.chunk_to_entities.items()
            },
            "index_fingerprint": self.index_fingerprint,
            "manifest_version": self.manifest_version,
        }
        try:
            fd, temporary_path = tempfile.mkstemp(
                prefix=".mneme-kg-", suffix=".tmp", dir=directory,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, filepath)
            temporary_path = None
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.remove(temporary_path)

    @classmethod
    def load(cls, filepath: str) -> KnowledgeGraph:
        if os.path.getsize(filepath) > 100 * 1024 * 1024:
            raise ValueError("Graph RAG 缓存超过安全大小上限")
        with open(filepath, "r", encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict) or data.get("schema_version") != 2:
            raise ValueError("不支持的 Graph RAG 缓存 schema")
        expected_keys = {
            "schema_version", "entity_graph", "entity_to_chunks",
            "chunk_to_entities", "index_fingerprint", "manifest_version",
        }
        if set(data) != expected_keys:
            raise ValueError("Graph RAG 缓存字段不符合 schema")

        kg = cls()
        graph_data = data["entity_graph"]
        if not isinstance(graph_data, dict) or set(graph_data) != {"nodes", "edges"}:
            raise ValueError("Graph RAG 图结构不符合 schema")
        nodes = graph_data["nodes"]
        edges = graph_data["edges"]
        if not isinstance(nodes, list) or not all(isinstance(node, str) for node in nodes):
            raise ValueError("Graph RAG 节点数据无效")
        if not isinstance(edges, list):
            raise ValueError("Graph RAG 边数据无效")
        kg.entity_graph.add_nodes_from(nodes)
        for edge in edges:
            if not isinstance(edge, dict) or set(edge) != {"source", "target", "weight"}:
                raise ValueError("Graph RAG 边 schema 无效")
            source, target, weight = edge["source"], edge["target"], edge["weight"]
            if (
                not isinstance(source, str)
                or not isinstance(target, str)
                or not isinstance(weight, (int, float))
                or not math.isfinite(float(weight))
            ):
                raise ValueError("Graph RAG 边数据无效")
            kg.entity_graph.add_edge(source, target, weight=float(weight))

        for key in ("entity_to_chunks", "chunk_to_entities"):
            mapping = data[key]
            if not isinstance(mapping, dict) or not all(
                isinstance(name, str)
                and isinstance(values, list)
                and all(isinstance(value, str) for value in values)
                for name, values in mapping.items()
            ):
                raise ValueError(f"Graph RAG 映射字段无效: {key}")
            setattr(kg, key, mapping)
        kg.index_fingerprint = data.get("index_fingerprint")
        kg.manifest_version = data.get("manifest_version")
        if kg.index_fingerprint is not None and not isinstance(kg.index_fingerprint, str):
            raise ValueError("Graph RAG index fingerprint 无效")
        if kg.manifest_version is not None and not isinstance(kg.manifest_version, int):
            raise ValueError("Graph RAG manifest version 无效")
        return kg


def extract_entities_from_query(query: str) -> list[str]:
    return extract_entities_llm_batch([query])[0]

def graph_augmented_retrieve(
        query: str,
        model: SentenceTransformer,
        collection: chromadb.Collection,
        bm25,
        all_docs: list[str],
        kg: KnowledgeGraph,
        k_vector: int = 20,
        k_graph: int = 5,
        alpha: float = 0.7,
        verbose: bool = True,
        all_ids: list[str] | None = None,
        all_metadatas: list[dict] | None = None,
) -> tuple[list[int], list[str], list[float]]:
    if kg.entity_graph.number_of_nodes() == 0:
        print("[警告] 知识图谱为空，退化为纯语义检索")

    collection_data = collection.get()
    collection_metadatas = all_metadatas or (
        collection_data.get("metadatas", []) if isinstance(collection_data, dict) else []
    )
    all_ids = all_ids or [
        metadata.get("chunk_id", f"chunk_{index}")
        for index, metadata in enumerate(collection_metadatas)
    ]
    if len(all_ids) != len(all_docs):
        all_ids = [f"chunk_{index}" for index in range(len(all_docs))]

    semantic_indices, semantic_docs, semantic_scores = retrieve_hybrid_with_sources(
        query, model, collection, bm25, all_docs,
        metadatas=collection_metadatas, k=k_vector,
    )

    query_entities = extract_entities_from_query(query)
    if verbose:
        print(f"查询实体{query_entities}")

    graph_chunks = []
    if query_entities:
        related_entities = kg.get_related_entities(query_entities, max_hops = 1, top_k = 10)
        if verbose:
            print(f"图谱扩散到的相关实体{[e for e, _ in related_entities[:8]]}")

        graph_chunks = kg.get_chunks_by_entities(
            [e for e, _ in related_entities[:8]],
            max_chunks = k_graph * 2,
        )

    id_to_idx = {chunk_id: index for index, chunk_id in enumerate(all_ids)}

    merged: dict[str, float] = {}

    for rank, doc in enumerate(graph_chunks):
        if doc not in merged:
            merged[doc] = (1 - alpha) / (rank + 1)

    for index, score in zip(semantic_indices, semantic_scores):
        chunk_id = all_ids[index]
        merged[chunk_id] = merged.get(chunk_id, 0.0) + alpha * score

    sorted_merged = sorted(merged.items(), key=lambda x: x[1], reverse=True)
    top = sorted_merged[:k_vector]

    indices = [id_to_idx[chunk_id] for chunk_id, _ in top if chunk_id in id_to_idx]
    docs = [all_docs[id_to_idx[chunk_id]] for chunk_id, _ in top if chunk_id in id_to_idx]
    scores = [score for chunk_id, score in top if chunk_id in id_to_idx]
    return indices, docs, scores


def build_graph_index(
        file_paths: list[str],
        collection_name: str = DEFAULT_COLLECTION_NAME,
        force_rebuild: bool = False,
        progress_callback=None,
) -> tuple:
    model, collection = build_index(
        file_paths,
        collection_name,
        force_rebuild=force_rebuild,
        progress_callback=progress_callback,
    )
    all_data = collection.get()
    all_docs = all_data["documents"]
    all_ids = all_data["ids"]
    all_metadatas = all_data["metadatas"]
    if not all_docs:
        raise ValueError("文档为空")

    manifest = load_index_manifest(collection_name)
    bm25 = set_manifest_version(
        build_bm25_index(all_docs),
        manifest.get("manifest_version") if manifest else None,
    )

    print("\n" + "=" * 60)
    print("构建Knowledge Graph")
    print("=" * 60)
    kg = KnowledgeGraph()
    kg.build_from_chunks(
        all_docs, chunk_ids=all_ids, verbose=True,
        progress_callback=progress_callback,
    )
    kg.manifest_version = manifest.get("manifest_version") if manifest else None
    print(f"知识图谱构建完成: {kg.entity_graph.number_of_nodes()}个实体",
          f"{kg.entity_graph.number_of_edges()}个关系")
    return model, collection, bm25, all_docs, kg


def prepare_graph_index(
        file_paths: list[str],
        collection_name: str,
        force_rebuild: bool = False,
        progress_callback=None,
) -> tuple:
    client, need_build = _ensure_client_and_check_rebuild(
        collection_name, force_rebuild, file_paths=file_paths,
    )
    model_for_config = _load_sentence_transformer(EMBEDDING_MODEL_NAME)
    manifest = load_index_manifest(collection_name)
    config_mismatch = bool(file_paths) and (
        manifest is None
        or not _manifest_config_matches(manifest, model=model_for_config)
    )
    need_build = need_build or config_mismatch
    kg_file = os.path.join(CHROMA_DB_PATH, f"{collection_name}_kg.json")

    if need_build:
        print("索引重构中...")
        model, collection, bm25, all_docs, kg = build_graph_index(
            file_paths, collection_name,
            force_rebuild or config_mismatch,
            progress_callback=progress_callback,
        )
        all_data = collection.get()
        all_metadatas = all_data["metadatas"]
        manifest = load_index_manifest(collection_name)
        kg.save(
            kg_file,
            index_fingerprint(all_data["ids"], all_metadatas),
            manifest.get("manifest_version") if manifest else None,
        )
    else:
        print("检测到已有索引，正在加载...")
        model = model_for_config
        collection = client.get_collection(collection_name)

        all_data = collection.get()
        all_docs = all_data["documents"]
        all_metadatas = all_data["metadatas"]

        manifest = load_index_manifest(collection_name)
        bm25 = set_manifest_version(
            build_bm25_index(all_docs),
            manifest.get("manifest_version") if manifest else None,
        )

        current_fingerprint = index_fingerprint(all_data["ids"], all_metadatas)
        if os.path.exists(kg_file):
            print("加载已缓存的知识图谱...")
            try:
                candidate = KnowledgeGraph.load(kg_file)
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                candidate = None
            current_manifest_version = manifest.get("manifest_version") if manifest else None
            if (
                candidate is not None
                and candidate.index_fingerprint == current_fingerprint
                and candidate.manifest_version == current_manifest_version
            ):
                kg = candidate
            else:
                print("知识图谱缓存与索引版本不一致，重建知识图谱...")
                kg = KnowledgeGraph()
                kg.build_from_chunks(
                    all_docs, chunk_ids=all_data["ids"], verbose=True,
                )
                kg.save(kg_file, current_fingerprint, current_manifest_version)
        else:
            print("重建知识图谱...")
            kg = KnowledgeGraph()
            kg.build_from_chunks(
                all_docs, chunk_ids=all_data["ids"], verbose=True,
            )
            kg.save(
                kg_file,
                current_fingerprint,
                manifest.get("manifest_version") if manifest else None,
            )

    return model, collection, bm25, all_docs, all_metadatas, kg


def graph_rag_pipeline(
        file_paths: list[str],
        query: str,
        collection_name: Optional[str] = None,
        force_rebuild: bool = False,
        alpha: float = 0.7,
        history: list[tuple[str, str]] | None = None,
        temperature: float = 0.1,
):
    if collection_name is None:
        name_input = "|".join(sorted(file_paths))
        collection_name = "graph_rag_" + hashlib.md5(name_input.encode()).hexdigest()[:8]

    _t0 = time.time()
    model, collection, bm25, all_docs, all_metadatas, kg = prepare_graph_index(
        file_paths, collection_name, force_rebuild
    )
    _t1 = time.time()

    _elapsed = _t1 - _t0
    _minutes = int(_elapsed // 60)
    _seconds = int(_elapsed % 60)
    print(f"文档库就绪（用时{_minutes}分{_seconds}秒）")

    print("\n" + "=" * 60)
    print("Graph 增强检索")
    print("=" * 60)

    indices, fused_docs, fused_scores = graph_augmented_retrieve(
        query, model, collection, bm25,
        all_docs, kg, k_vector=20, k_graph=5,
        alpha=alpha,
        all_metadatas=all_metadatas,
    )

    k = dynamic_top_k(fused_scores, min_k = 3, max_k = 50)
    top_docs = fused_docs[:k]
    top_indices = indices[:k]

    if retrieval_refused(fused_scores):
        _record_query_metric(
            _t0, [], fused_scores, all_metadatas, bm25, refused=True,
        )
        print(REFUSAL_MESSAGE)
        return REFUSAL_MESSAGE

    print(f"查询：{query}")
    print(f"动态top_k = {k}")
    for i, doc in enumerate(top_docs[:5]):
        print(f"[{i}] {doc[:150]}")
    if len(top_docs) > 5:
        print(f"共有{len(top_docs)}条结果")

    print("\n" + "=" * 60)
    print("LLM生成回答")
    print("=" * 60)
    enriched_docs = enrich_context(top_indices, all_docs, all_metadatas)
    context = _build_context(top_indices, enriched_docs, all_metadatas)
    _tq0 = time.time()
    answer = answer_with_llm_history(query, context, history = history or [], temperature=temperature)
    _tq1 = time.time()
    _qelapsed = _tq1 - _tq0
    _qminutes = int(_qelapsed // 60)
    _qseconds = int(_qelapsed % 60)
    print(f"\n{answer}（用时{_qminutes}分{_qseconds}秒）")

    sources = format_sources(top_indices, enriched_docs, all_metadatas)
    print(f"\n参考来源：\n{sources}")

    return answer

def main():
    """Graph RAG 命令行入口"""
    from src.cli_loop import run_interactive_session, run_single_query

    parser = argparse.ArgumentParser(description="Graph RAG Pipeline")
    parser.add_argument("--files", nargs="+", default=None)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--query", default=None)
    parser.add_argument("--alpha", type=float, default=0.7, help="语义检索 vs 图谱检索融合权重")
    args = parser.parse_args()

    file_paths = args.files or ask_for_files()
    if not file_paths:
        print("没有文件")
        exit(1)

    collection_name = args.collection or (
        "graph_rag_" + hashlib.md5("|".join(sorted(file_paths)).encode()).hexdigest()[:8]
    )

    # 单次查询路径（graph_rag.py 特有）：先准备索引，再执行单次查询
    if args.query:
        model, collection, bm25, all_docs, all_metadatas, kg = prepare_graph_index(
            file_paths, collection_name, args.rebuild,
        )
        answer, sources = run_single_query(
            args.query,
            model=model, collection=collection, bm25=bm25,
            all_docs=all_docs, all_metadatas=all_metadatas,
            is_graph_rag=True, alpha=args.alpha, kg=kg,
        )
        print(f"\n{answer}")
        print(f"\n参考来源：\n{sources}")
        exit(0)

    # 交互式循环
    run_interactive_session(
        file_paths, collection_name,
        force_rebuild=args.rebuild,
        alpha=args.alpha,
        is_graph_rag=True,
    )


if __name__ == "__main__":
    main()


def graph_query_stream(
    query: str,
    model: SentenceTransformer,
    collection: chromadb.Collection,
    bm25,
    all_docs: list[str],
    all_metadatas: list[dict],
    kg: KnowledgeGraph,
    history=None,
    alpha: float = 0.7,
    temperature: float = 0.1,
    top_k_range=(3, 50),
    llm_model: str = DEFAULT_LLM_MODEL,
) -> tuple[Generator[str, None, None], str]:
    retrieval_start = time.perf_counter()
    indices, docs, scores = graph_augmented_retrieve(
        query, model, collection, bm25, all_docs, kg,
        alpha=alpha, verbose=False, all_metadatas=all_metadatas,
    )
    k = dynamic_top_k(scores, min_k=top_k_range[0], max_k=top_k_range[1])
    top_indices = indices[:k]
    if retrieval_refused(scores):
        _record_query_metric(
            retrieval_start, [], scores, all_metadatas, bm25, refused=True,
        )
        def refusal_stream():
            yield REFUSAL_MESSAGE
        return refusal_stream(), ""
    enriched_docs = enrich_context(top_indices, all_docs, all_metadatas)
    context = _build_context(top_indices, enriched_docs, all_metadatas)
    sources = format_sources(top_indices, enriched_docs, all_metadatas)
    _record_query_metric(
        retrieval_start, top_indices, scores, all_metadatas, bm25,
    )
    stream = answer_with_llm_history_stream(
        query, context, history or [], model=llm_model, temperature=temperature,
    )
    return stream, sources
