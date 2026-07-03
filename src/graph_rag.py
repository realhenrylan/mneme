from __future__ import annotations
import os
import sys
import time
import hashlib
import pickle
import argparse
import networkx as nx
from typing import Optional

_SRC = os.path.dirname(os.path.abspath(__file__))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
from concurrent.futures import ThreadPoolExecutor, as_completed

from rag import (
    build_bm25_index,
    build_index, ask_for_files, _collection_exists,
    add_files_to_index,
    retrieve_hybrid_with_sources, dynamic_top_k,
    answer_with_llm_history, format_sources,
    SentenceTransformer, chromadb,
    EMBEDDING_MODEL_NAME, DEFAULT_COLLECTION_NAME,
    DEFAULT_TOP_K, DEFAULT_MIN_K, DEFAULT_MAX_K,
    CHROMA_DB_PATH, DEFAULT_LLM_MODEL,
)

from openai import OpenAI
_entity_cache: dict[str, list[str]] = {}

def _get_llm_client() -> OpenAI:
    return OpenAI(
        api_key = os.getenv("API_KEY"),
        base_url = os.getenv("BASE_URL"),
    )

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
                               batch_size: int = 5) -> list[list[str]]:
    """批量提取实体，带逐文本缓存"""

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
                    model="deepseek-chat",
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
                    elif line and not line.startswith(("-", "*", "·")):
                        current.append(line)
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

    return [_entity_cache.get(hashlib.md5(t.encode()).hexdigest(), []) for t in texts]


class KnowledgeGraph:
    def __init__(self):
        self.entity_graph = nx.Graph()
        self.entity_to_chunks: dict[str, list[str]] = {}
        self.chunk_to_entities: dict[str, list[str]] = {}

    def build_from_chunks(
            self,
            chunks: list[str],
            verbose: bool = True,
            max_workers = 10,
            progress_callback=None,
    ):
        if verbose:
            print(f"正在从{len(chunks)}个chunks当中提取实体")

        with ThreadPoolExecutor(max_workers = max_workers) as executor:
            future_to_idx = {
                executor.submit(extract_entities_llm_batch, [c]): i
                for i, c in enumerate(chunks)
            }
            results = [None] * len(chunks)
            done = 0
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                results[idx] = future.result()[0]
                done += 1
                if verbose and done % 10 == 0:
                    print(f"进度{done}/{len(chunks)}")
                if progress_callback:
                    progress_callback(done, len(chunks))

        for i, (chunk, entities) in enumerate(zip(chunks, results)):

            if not entities:
                continue

            unique_entities = list(set(entities))

            self.chunk_to_entities[chunk] = unique_entities
            for ent in unique_entities:
                if ent not in self.entity_to_chunks:
                    self.entity_to_chunks[ent] = []
                self.entity_to_chunks[ent].append(chunk)

            for u in unique_entities:
                for v in unique_entities:
                    if u < v:
                        if self.entity_graph.has_edge(u, v):
                            self.entity_graph[u][v]["weight"] += 1
                        else:
                            self.entity_graph.add_edge(u, v, weight = 1)

        if verbose:
            print(f"Graph Stats: ")
            print(f"Entities (nodes):  {self.entity_graph.number_of_nodes()}")
            print(f"Relations (edges): {self.entity_graph.number_of_edges()}")
            print(f"Chunks with Entities: {len(self.chunk_to_entities)}")

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

    def save(self, filepath: str):
        with open(filepath, "wb") as f:
            pickle.dump({
                "entity_graph": self.entity_graph,
                "entity_to_chunks": self.entity_to_chunks,
                "chunk_to_entities": self.chunk_to_entities,
            }, f)

    @classmethod
    def load(cls, filepath: str) -> KnowledgeGraph:
        kg = cls()
        with open(filepath, "rb") as f:
            data = pickle.load(f)
        kg.entity_graph = data["entity_graph"]
        kg.entity_to_chunks = data["entity_to_chunks"]
        kg.chunk_to_entities = data["chunk_to_entities"]
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
) -> tuple[list[int], list[str], list[float]]:
    if kg.entity_graph.number_of_nodes() == 0:
        print("[警告] 知识图谱为空，退化为纯语义检索")

    _, semantic_docs, semantic_scores = retrieve_hybrid_with_sources(
        query, model, collection, bm25, all_docs, k = k_vector
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

    doc_to_idx = {doc: i for i, doc in enumerate(all_docs)}

    merged: dict[str, float] = {}

    for rank, doc in enumerate(graph_chunks):
        if doc not in merged:
            merged[doc] = (1 - alpha) / (rank + 1)

    for doc, score in zip(semantic_docs, semantic_scores):
        if doc in merged:
            merged[doc] += alpha * score
        else:
            merged[doc] = alpha * score

    sorted_merged = sorted(merged.items(), key=lambda x: x[1], reverse=True)
    top = sorted_merged[:k_vector]

    indices = [doc_to_idx[doc] for doc, _ in top if doc in doc_to_idx]
    docs = [doc for doc, _ in top]
    scores = [s for _, s in top]
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
        force_rebuild,
        progress_callback=progress_callback,
    )
    all_docs = collection.get()["documents"]
    if not all_docs:
        raise ValueError("文档为空")

    bm25 = build_bm25_index(all_docs)

    print("\n" + "=" * 60)
    print("构建Knowledge Graph")
    print("=" * 60)
    kg = KnowledgeGraph()
    kg.build_from_chunks(all_docs, verbose=True, progress_callback=progress_callback)
    print(f"知识图谱构建完成: {kg.entity_graph.number_of_nodes()}个实体",
          f"{kg.entity_graph.number_of_edges()}个关系")
    return model, collection, bm25, all_docs, kg


def prepare_graph_index(
        file_paths: list[str],
        collection_name: str,
        force_rebuild: bool = False,
        progress_callback=None,
) -> tuple:
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    kg_file = os.path.join(CHROMA_DB_PATH, f"{collection_name}_kg.pkl")

    need_build = force_rebuild or not _collection_exists(client, collection_name)

    if need_build:
        print("索引重构中...")
        model, collection, bm25, all_docs, kg = build_graph_index(
            file_paths, collection_name, force_rebuild, progress_callback=progress_callback,
        )
        all_data = collection.get()
        all_metadatas = all_data["metadatas"]
        kg.save(kg_file)
    else:
        print("检测到已有索引，正在加载...")
        model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        collection = client.get_collection(collection_name)

        all_data = collection.get()
        all_docs = all_data["documents"]
        all_metadatas = all_data["metadatas"]

        bm25 = build_bm25_index(all_docs)

        if os.path.exists(kg_file):
            print("加载已缓存的知识图谱...")
            kg = KnowledgeGraph.load(kg_file)
        else:
            print("重建知识图谱...")
            kg = KnowledgeGraph()
            kg.build_from_chunks(all_docs, verbose=True)
            kg.save(kg_file)

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
        all_docs, kg, k_vector = 20, k_graph = 5,
        alpha = alpha
    )

    k = dynamic_top_k(fused_scores, min_k = 3, max_k = 50)
    top_docs = fused_docs[:k]
    top_indices = indices[:k]

    print(f"查询：{query}")
    print(f"动态top_k = {k}")
    for i, doc in enumerate(top_docs[:5]):
        print(f"[{i}] {doc[:150]}")
    if len(top_docs) > 5:
        print(f"共有{len(top_docs)}条结果")

    print("\n" + "=" * 60)
    print("LLM生成回答")
    print("=" * 60)
    context = " ".join(top_docs)
    _tq0 = time.time()
    answer = answer_with_llm_history(query, context, history = history or [], temperature=temperature)
    _tq1 = time.time()
    _qelapsed = _tq1 - _tq0
    _qminutes = int(_qelapsed // 60)
    _qseconds = int(_qelapsed % 60)
    print(f"\n{answer}（用时{_qminutes}分{_qseconds}秒）")

    sources = format_sources(top_indices, all_docs, all_metadatas)
    print(f"\n参考来源：\n{sources}")

    return answer

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Graph RAG Pipeline")
    parser.add_argument("--files", nargs="+", default=None)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--query", default=None)
    parser.add_argument("--alpha", type=float, default=0.7, help="语义检索 vs 图谱检索融合权重")
    args = parser.parse_args()

    if args.files:
        file_paths = args.files
    else:
        file_paths = ask_for_files()
        if not file_paths:
            print("没有文件")
            exit(1)

    collection_name = args.collection or (
        "graph_rag_" + hashlib.md5("|".join(sorted(file_paths)).encode()).hexdigest()[:8]
    )

    _t0 = time.time()
    model, collection, bm25, all_docs, all_metadatas, kg = prepare_graph_index(
        file_paths, collection_name, args.rebuild
    )
    _t1 = time.time()
    _elapsed = _t1 - _t0
    _minutes = int(_elapsed // 60)
    _seconds = int(_elapsed % 60)
    print(f"文档库就绪（用时{_minutes}分{_seconds}秒）\n")
    print("-" * 100)

    if args.query:
        indices, fused_docs, fused_scores = graph_augmented_retrieve(
            args.query, model, collection, bm25,
            all_docs, kg, alpha=args.alpha
        )
        k = dynamic_top_k(fused_scores, min_k=3, max_k=50)
        top_docs = fused_docs[:k]
        top_indices = indices[:k]
        context = " ".join(top_docs)
        answer = answer_with_llm_history(args.query, context, history=[], temperature=0.1)
        print(f"\n{answer}")
        sources = format_sources(top_indices, all_docs, all_metadatas)
        print(f"\n参考来源：\n{sources}")
        exit(0)

    history = []
    while True:
        query = input("请输入问题（q以退出，+add以添加新文件）：")
        if query.lower() in ("q", "quit"):
            break
        if not query:
            continue
        if query.startswith("+add"):
            raw_paths = query[4:].strip()
            if not raw_paths:
                print("用法: +add <文件路径1>[, <文件路径2>]")
                continue
            paths = [p.strip() for p in raw_paths.replace("，", ",").split(",") if p.strip()]
            if not paths:
                print("用法: +add <文件路径1>[, <文件路径2>]")
                continue
            bm25, all_docs, all_metadatas = add_files_to_index(paths, model, collection)
            print("重建知识图谱...")
            kg = KnowledgeGraph()
            kg.build_from_chunks(all_docs, verbose=True)
            print(f"已新增索引，当前共 {len(all_docs)} 个文档块")
            continue

        indices, fused_docs, fused_scores = graph_augmented_retrieve(
            query, model, collection, bm25,
            all_docs, kg, alpha=args.alpha
        )
        k = dynamic_top_k(fused_scores, min_k=3, max_k=50)
        top_docs = fused_docs[:k]
        top_indices = indices[:k]

        context = " ".join(top_docs)
        _tq0 = time.time()
        answer = answer_with_llm_history(query, context, history=history, temperature=0.1)
        _tq1 = time.time()
        _qelapsed = _tq1 - _tq0
        _qminutes = int(_qelapsed // 60)
        _qseconds = int(_qelapsed % 60)

        print(f"\n{answer}（用时{_qminutes}分{_qseconds}秒）")
        sources = format_sources(top_indices, all_docs, all_metadatas)
        print(f"\n参考来源：\n{sources}\n")
        print("=" * 100)

        history.append((query, answer))


from typing import Generator
from rag import answer_with_llm_history_stream


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
    indices, docs, scores = graph_augmented_retrieve(
        query, model, collection, bm25, all_docs, kg,
        alpha=alpha, verbose=False,
    )
    k = dynamic_top_k(scores, min_k=top_k_range[0], max_k=top_k_range[1])
    top_indices = indices[:k]
    context = " ".join(docs[:k])
    sources = format_sources(top_indices, all_docs, all_metadatas)
    stream = answer_with_llm_history_stream(
        query, context, history or [], model=llm_model, temperature=temperature,
    )
    return stream, sources
