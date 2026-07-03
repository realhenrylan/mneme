#!/usr/bin/env python3
"""
验证：为 PDF 版索引补一个“元数据 anchor chunk”后，
原查询是否能召回作者/机构信息。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import src.rag as rag
from rank_bm25 import BM25Okapi

TEST_DB_PATH = Path(__file__).resolve().parent / "chroma_db_test"
rag.CHROMA_DB_PATH = str(TEST_DB_PATH)

QUERY = "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"

ANCHOR = """Title: Large Language Models for Mobility Analysis in Transportation Systems: A Survey on Forecasting Tasks
Authors: Zijian Zhang, Yujie Sun, Zepu Wang, Yuqi Nie, Xiaobo Ma, Ruolin Li, Peng Sun, Xuegang Ban
Affiliations: University of Pennsylvania, University of Washington, Princeton University, The University of Arizona, University of South California, Duke Kunshan University"""


def find_author_chunks(docs):
    return [i for i, d in enumerate(docs) if "Zijian Zhang" in d or "University of Pennsylvania" in d]


def main():
    client = rag.chromadb.PersistentClient(path=str(TEST_DB_PATH))
    collection = client.get_collection("test_pdf")
    model = rag.SentenceTransformer(rag.EMBEDDING_MODEL_NAME)

    # 添加 anchor chunk
    emb = model.encode([ANCHOR]).tolist()
    collection.add(
        ids=["anchor_chunk"],
        documents=[ANCHOR],
        metadatas=[{"source": "anchor", "chunk_index": 999}],
        embeddings=emb,
    )

    all_data = collection.get()
    docs = all_data["documents"]
    bm25 = rag.build_bm25_index(docs)

    rrf_res = rag.retrieve_hybrid_with_sources(QUERY, model, collection, bm25, docs, k=20)
    indices, _, scores = rrf_res
    k = rag.dynamic_top_k(scores)
    author_indices = find_author_chunks(docs)
    author_in_selected = any(i in indices[:k] for i in author_indices)

    print(f"添加 anchor chunk 后，文档总数: {len(docs)}")
    print(f"作者/机构相关 chunk 索引: {author_indices}")
    print(f"dynamic_top_k 选出 k={k}")
    print(f"作者 chunk 是否被选中: {author_in_selected}")
    print("\nTop-10 RRF 结果:")
    for r, (idx, doc, score) in enumerate(zip(indices, rrf_res[1], scores), 1):
        flag = " [作者/anchor]" if idx in author_indices or "anchor" in doc else ""
        print(f"  {r:2}. idx={idx} score={score:.4f}{flag}: {doc[:90].replace(chr(10), ' ')}...")
        if r >= 10:
            break


if __name__ == "__main__":
    main()
