#!/usr/bin/env python3
"""
验证 RAG 第一性原理总结的实验脚本。
不修改现有代码，仅调用 rag.py 中的函数并做独立分析。
"""
from __future__ import annotations
import os
import sys
import re
import shutil
from pathlib import Path

# 让脚本能找到项目根目录的 rag.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import src.rag as rag
from rank_bm25 import BM25Okapi

# 使用独立的 Chroma 持久化目录，避免污染项目原有索引
TEST_DB_PATH = Path(__file__).resolve().parent / "chroma_db_test"
rag.CHROMA_DB_PATH = str(TEST_DB_PATH)

PDF_FILE = str(PROJECT_ROOT / "test_texts" / "2405.02357v2.pdf")
MD_FILE = str(PROJECT_ROOT / "test_texts" / "LLMs_for_Mobility_Analysis_Survey.md")

MODEL_NAME = rag.EMBEDDING_MODEL_NAME
QUERIES = [
    ("纯主题查询", "traffic forecasting using deep learning"),
    ("纯中文元数据", "这篇文章的作者都属于什么学校"),
    ("中英混合+元数据", "LLMs for mobility的作者是谁"),
    ("中英混合+原题", "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"),
    ("英文+论文名", "authors affiliations of LLMs for mobility survey paper"),
    ("仅论文标识", "LLMs for mobility"),
    ("仅元数据意图", "authors affiliations university"),
    ("机构名", "University of Pennsylvania"),
]


def clear_test_db():
    if TEST_DB_PATH.exists():
        shutil.rmtree(TEST_DB_PATH)
    TEST_DB_PATH.mkdir(parents=True, exist_ok=True)


def build_collection(file_path: str, collection_name: str, force_rebuild: bool = True):
    model, collection = rag.build_index(
        [file_path], collection_name=collection_name, force_rebuild=force_rebuild
    )
    all_data = collection.get()
    docs = all_data["documents"]
    metas = all_data["metadatas"]
    bm25 = rag.build_bm25_index(docs)
    return model, collection, bm25, docs, metas


def find_author_chunks(docs: list[str], label: str) -> list[int]:
    """定位包含作者/机构信息的 chunk 索引（优先第一页作者块）。"""
    indices = []
    for i, doc in enumerate(docs):
        lowered = doc.lower()
        # PDF 无空格 + MD 正常格式：命中作者块的强信号
        if any(k in lowered for k in [
            "zijianzhang", "zijian zhang", "co-firstauthor", "co-first author",
            "correspondingauthor", "corresponding author", "**authors:**"
        ]):
            indices.append(i)
    return indices


def semantic_search(model, collection, query: str, k: int = 20):
    emb = model.encode([query]).tolist()
    res = collection.query(query_embeddings=emb, n_results=k)
    return list(zip(res["documents"][0], res["distances"][0]))


def bm25_search(bm25, docs, query: str, k: int = 20):
    tokens = query.split()
    scores = bm25.get_scores(tokens)
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:k]
    return [(docs[i], s, i) for i, s in ranked]


def rrf_search(model, collection, bm25, docs, query: str, k: int = 20):
    """复现 rag.retrieve_hybrid_with_sources 的融合逻辑。"""
    sem = semantic_search(model, collection, query, k)
    bm = bm25_search(bm25, docs, query, k)
    bm_for_rrf = [(doc, score) for doc, score, _ in bm]
    fused = rag.rrf_merge(sem, bm_for_rrf)
    doc_to_idx = {doc: i for i, doc in enumerate(docs)}
    return [(doc_to_idx[doc], doc, score) for doc, score in fused if doc in doc_to_idx]


def print_section(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def run_retrieval_experiment(model, collection, bm25, docs, metas, label: str):
    print_section(f"检索实验：{label}（共 {len(docs)} 个 chunks）")
    author_indices = find_author_chunks(docs, label)
    print(f"检测到的作者/机构 chunk 索引：{author_indices}")
    for idx in author_indices[:3]:
        snippet = docs[idx].replace("\n", " ")[:200]
        print(f"  [{idx}] {snippet}...")

    print("\n{:<20} {:<40} {:>8} {:>8} {:>8}".format(
        "查询类型", "查询", "RRF-rank", "Sem-rank", "BM25-rank"
    ))
    print("-" * 90)
    for qtype, query in QUERIES:
        rrf_res = rrf_search(model, collection, bm25, docs, query, k=20)
        sem_res = semantic_search(model, collection, query, k=20)
        bm_res = bm25_search(bm25, docs, query, k=20)

        def rank_of_author(results, use_idx=False):
            for r, item in enumerate(results, 1):
                idx = item[0] if use_idx else docs.index(item[0])
                if idx in author_indices:
                    return r
            return ">20"

        rrf_rank = rank_of_author(rrf_res, use_idx=True)
        sem_rank = rank_of_author([(d, _) for d, _ in sem_res])
        bm25_rank = rank_of_author([(d, _, i) for d, _, i in bm_res], use_idx=True)
        print("{:<20} {:<40} {:>8} {:>8} {:>8}".format(
            qtype, query[:38], str(rrf_rank), str(sem_rank), str(bm25_rank)
        ))


def run_embedding_intent_experiment(model, docs_map: dict):
    """
    直接计算 query embedding 与关键 chunks 的 cosine similarity，
    验证“单一 embedding 是否能同时承载主题意图和元数据意图”。
    """
    print_section("单一 embedding 复合意图验证")
    # 选取几个代表性 chunk
    md_chunk0 = docs_map["md"][0]
    pdf_author_indices = find_author_chunks(docs_map["pdf"], "pdf")
    pdf_author_chunk = docs_map["pdf"][pdf_author_indices[0]] if pdf_author_indices else ""

    # 找一个主题 chunk（MD 中 Abstract/Introduction 所在位置，且不能是 chunk 0）
    content_idx = None
    for i, d in enumerate(docs_map["md"]):
        if i == 0:
            continue
        if "traffic forecasting" in d.lower() or "deep learning" in d.lower():
            content_idx = i
            break
    md_content_chunk = docs_map["md"][content_idx] if content_idx is not None else docs_map["md"][1]

    targets = [
        ("MD 元数据 chunk (chunk 0)", md_chunk0),
        ("MD 正文 chunk", md_content_chunk),
        ("PDF 作者 chunk", pdf_author_chunk),
    ]

    query_groups = [
        ("仅主题", "LLMs for mobility"),
        ("仅元数据", "authors affiliations university"),
        ("复合意图", "LLMs for mobility authors affiliations university"),
        ("中英复合", "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"),
        ("中文元数据", "这篇文章的作者都属于什么学校"),
    ]

    print("{:<12}".format("Query"), end="")
    for name, _ in targets:
        print(f"{name:>28}", end="")
    print()
    print("-" * 95)
    for qname, qtext in query_groups:
        q_emb = model.encode(qtext, normalize_embeddings=True)
        print(f"{qname:<12}", end="")
        for _, text in targets:
            t_emb = model.encode(text, normalize_embeddings=True)
            sim = float((q_emb @ t_emb).item())
            print(f"{sim:>28.4f}", end="")
        print()


def run_tokenization_experiment(docs_map: dict):
    print_section("BM25 分词方式对比")
    pdf_author_indices = find_author_chunks(docs_map["pdf"], "pdf")
    if not pdf_author_indices:
        print("未找到 PDF 作者 chunk")
        return
    pdf_author_chunk = docs_map["pdf"][pdf_author_indices[0]]

    queries = [
        "这篇文章的作者都属于什么学校",
        "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？",
        "authors affiliations of LLMs for mobility survey paper",
    ]

    naive_tokenizer = lambda t: t.lower().split()
    mixed_tokenizer = lambda t: [tok for tok in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", t.lower()) if tok]

    for q in queries:
        print(f"\n查询: {q}")
        for name, tokenizer in [("当前 split()", naive_tokenizer), ("中英混合分词", mixed_tokenizer)]:
            q_tokens = tokenizer(q)
            doc_tokens = tokenizer(pdf_author_chunk)
            overlap = set(q_tokens) & set(doc_tokens)
            print(f"  {name}: query tokens={q_tokens[:15]}..., overlap={overlap}")


def run_dynamic_topk_analysis(model, collection, bm25, docs, metas, label: str, query: str):
    print_section(f"dynamic_top_k 截断分析：{label}")
    rrf_res = rrf_search(model, collection, bm25, docs, query, k=20)
    scores = [s for _, _, s in rrf_res]
    k = rag.dynamic_top_k(scores)
    author_indices = find_author_chunks(docs, label)
    selected = [idx for idx, _, _ in rrf_res[:k]]
    author_in_selected = any(i in selected for i in author_indices)
    print(f"查询: {query}")
    print(f"dynamic_top_k 选出 k={k}")
    print(f"作者 chunk 是否被选中: {author_in_selected}")
    print("前 10 个 RRF 分数:")
    for i, (idx, doc, score) in enumerate(rrf_res[:10], 1):
        flag = " [作者]" if idx in author_indices else ""
        snippet = doc.replace("\n", " ")[:80]
        print(f"  {i:2}. score={score:.4f} idx={idx}{flag}: {snippet}...")


def main():
    clear_test_db()

    # 1. 展示 PDF 提取质量
    print_section("PDF 首页文本提取示例（pdfplumber）")
    pages = rag.load_pdf_pages(PDF_FILE)
    if pages:
        first_page = pages[0][0]
        print(first_page[:1200])

    # 2. 构建两个索引
    print_section("构建 MD 索引")
    md_model, md_col, md_bm25, md_docs, md_metas = build_collection(MD_FILE, "test_md")
    print_section("构建 PDF 索引")
    pdf_model, pdf_col, pdf_bm25, pdf_docs, pdf_metas = build_collection(PDF_FILE, "test_pdf", force_rebuild=False)

    # 3. 检索实验
    run_retrieval_experiment(md_model, md_col, md_bm25, md_docs, md_metas, "MD 版本")
    run_retrieval_experiment(pdf_model, pdf_col, pdf_bm25, pdf_docs, pdf_metas, "PDF 版本")

    # 4. embedding 复合意图验证
    run_embedding_intent_experiment(md_model, {"md": md_docs, "pdf": pdf_docs})

    # 5. 分词对比
    run_tokenization_experiment({"md": md_docs, "pdf": pdf_docs})

    # 6. dynamic_top_k 对原始查询的截断影响
    run_dynamic_topk_analysis(
        md_model, md_col, md_bm25, md_docs, md_metas, "MD 版本",
        "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"
    )
    run_dynamic_topk_analysis(
        pdf_model, pdf_col, pdf_bm25, pdf_docs, pdf_metas, "PDF 版本",
        "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"
    )

    print("\n实验完成。")


if __name__ == "__main__":
    main()
