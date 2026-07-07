from __future__ import annotations
import os
import time
import hashlib
import pickle
import argparse
import networkx as nx
from typing import Optional, Generator
from src.rag import (
    build_bm25_index,
    build_index, ask_for_files, _collection_exists,
    _ensure_client_and_check_rebuild,
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
)

from openai import OpenAI
_entity_cache: dict[str, list[str]] = {}
_llm_client: OpenAI | None = None

def _get_llm_client() -> OpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenAI(
            api_key = os.getenv("API_KEY"),
            base_url = os.getenv("BASE_URL"),
        )
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

    def build_from_chunks(
            self,
            chunks: list[str],
            verbose: bool = True,
            max_workers: int = 10,          # [DEPRECATED] 保留但忽略，向后兼容
            progress_callback=None,
            batch_size: int = 5,            # 新参数追加到末尾
            min_cooccur: int = 2,           # 最小共现次数阈值
            max_entities_per_chunk: int = 20,  # 每 chunk 参与建边的最大实体数
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

        for chunk, entities in zip(chunks, results):

            if not entities:
                continue

            # 1. 记录实体→chunk 映射（始终使用完整列表，不受截断影响）
            unique_all = self._record_entity_chunk_mapping(chunk, entities)

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
        force_rebuild=force_rebuild,
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
    client, need_build = _ensure_client_and_check_rebuild(collection_name, force_rebuild)
    kg_file = os.path.join(CHROMA_DB_PATH, f"{collection_name}_kg.pkl")

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
        model = _load_sentence_transformer(EMBEDDING_MODEL_NAME)
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
    indices, docs, scores = graph_augmented_retrieve(
        query, model, collection, bm25, all_docs, kg,
        alpha=alpha, verbose=False,
    )
    k = dynamic_top_k(scores, min_k=top_k_range[0], max_k=top_k_range[1])
    top_indices = indices[:k]
    enriched_docs = enrich_context(top_indices, all_docs, all_metadatas)
    context = _build_context(top_indices, enriched_docs, all_metadatas)
    sources = format_sources(top_indices, enriched_docs, all_metadatas)
    stream = answer_with_llm_history_stream(
        query, context, history or [], model=llm_model, temperature=temperature,
    )
    return stream, sources
