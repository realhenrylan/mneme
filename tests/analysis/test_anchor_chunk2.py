#!/usr/bin/env python3
"""
验证：把 MD 的 chunk 0（标题+作者+摘要）作为 anchor 加入 PDF 索引后，
原查询的召回情况。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import src.rag as rag

TEST_DB_PATH = Path(__file__).resolve().parent / "chroma_db_test"
rag.CHROMA_DB_PATH = str(TEST_DB_PATH)

QUERY = "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"

# 读取 MD chunk 0 作为 anchor
md_text = rag.load_text(str(PROJECT_ROOT / "test_texts" / "LLMs_for_Mobility_Analysis_Survey.md"))
splitter = rag.get_splitter("text")
md_chunks = splitter.split_text(md_text)
ANCHOR = md_chunks[0]


def main():
    client = rag.chromadb.PersistentClient(path=str(TEST_DB_PATH))
    collection = client.get_collection("test_pdf")
    model = rag.SentenceTransformer(rag.EMBEDDING_MODEL_NAME)

    emb = model.encode([ANCHOR]).tolist()
    collection.add(
        ids=["md_anchor_chunk"],
        documents=[ANCHOR],
        metadatas=[{"source": "md_anchor", "chunk_index": 999}],
        embeddings=emb,
    )

    all_data = collection.get()
    docs = all_data["documents"]
    bm25 = rag.build_bm25_index(docs)

    indices, _, scores = rag.retrieve_hybrid_with_sources(QUERY, model, collection, bm25, docs, k=20)
    k = rag.dynamic_top_k(scores)

    print(f"加入 MD chunk 0 anchor 后，文档总数: {len(docs)}")
    print(f"dynamic_top_k 选出 k={k}")
    print("\nTop-10 RRF 结果:")
    for r, (idx, score) in enumerate(zip(indices, scores), 1):
        is_anchor = idx == len(docs) - 1
        flag = " [ANCHOR]" if is_anchor else ""
        print(f"  {r:2}. idx={idx} score={score:.4f}{flag}: {docs[idx][:90].replace(chr(10), ' ')}...")
        if r >= 10:
            break


if __name__ == "__main__":
    main()
