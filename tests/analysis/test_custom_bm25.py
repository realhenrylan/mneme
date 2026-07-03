#!/usr/bin/env python3
"""
测试：如果用更合理的 BM25 分词（小写、去标点、中英单字），
anchor chunk 能否获得高 BM25 排名。
"""
import sys
import re
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


def tokenize(t: str):
    # 英文单词 + 中文单字，全部小写
    return [tok for tok in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", t.lower()) if tok]


def main():
    client = rag.chromadb.PersistentClient(path=str(TEST_DB_PATH))
    collection = client.get_collection("test_pdf")
    all_data = collection.get()
    docs = all_data["documents"]
    docs.append(ANCHOR)

    # 当前 BM25
    bm25_naive = BM25Okapi([d.split() for d in docs])
    # 改进 BM25
    bm25_good = BM25Okapi([tokenize(d) for d in docs])

    for name, bm25, tok in [
        ("当前 split()", bm25_naive, str.split),
        ("改进分词", bm25_good, tokenize),
    ]:
        scores = bm25.get_scores(tok(QUERY))
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:10]
        print(f"\n{name} — 查询: {QUERY}")
        for r, (idx, s) in enumerate(ranked, 1):
            flag = " [ANCHOR]" if idx == len(docs) - 1 else ""
            print(f"  {r:2}. idx={idx} score={s:.4f}{flag}: {docs[idx][:70].replace(chr(10), ' ')}...")


if __name__ == "__main__":
    main()
