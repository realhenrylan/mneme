"""
RAG (Retrieval-Augmented Generation) 完整实现
=============================================
核心流程:
  1. 文档加载 (自动判断文件类型)
  2. 按文件类型选择分块策略
  3. Embedding 向量化
  4. ChromaDB 建索引
  5. 混合检索 (语义 + BM25 + RRF)
  6. 动态 Top-K
  7. LLM 生成回答

用法:
  python rag.py                  # 默认文档列表
  python rag.py --files a.pdf b.md   # 指定文件
"""

from __future__ import annotations
import os
import sys
import re
import time
import argparse
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

_SRC = os.path.dirname(os.path.abspath(__file__))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from dotenv import load_dotenv

load_dotenv()

# 离线模式：避免 SentenceTransformer 联网检查更新
os.environ.setdefault("HF_HUB_OFFLINE", "1")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CHROMA_DB_PATH = os.path.join(PROJECT_ROOT, "chroma_db")

# ── 配置常量 ──
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
DEFAULT_COLLECTION_NAME = "rag_demo"
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50
DEFAULT_TOP_K = 70
DEFAULT_MIN_K = 12
DEFAULT_MAX_K = 70
DEFAULT_LLM_MODEL = "deepseek-chat"
DEFAULT_TEMPERATURE = 0.2

SYSTEM_PROMPT = (
    "你是一个基于文档内容的问答助手。根据提供的文档回答问题。"
    "如果文档中找不到相关信息，绝对不能私自编造。"
    "每个文档片段前标注了[Source: 文件名]，"
    "你可以通过统计不同的[Source: 文件名]来回答关于文件数量、文件名等元问题。"
)
PROMPT_TEMPLATE = "文档：\n{context}\n\n问题：{question}\n答案："

# ── 支持的文本扩展名 ──
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".html", ".htm",
    ".json", ".csv", ".xml", ".yaml", ".yml",
    ".toml", ".cfg", ".ini", ".conf", ".log",
    ".py", ".js", ".ts", ".css", ".sql",
    ".sh", ".bat", ".gitignore",
}

# ═══════════════════════════════════════════════
# 第一步：用户上传文件路径、文件类型检测
# ═══════════════════════════════════════════════
def ask_for_files() -> list[str]:
    raw = input("请输入要上传文件的路径，多个文件使用逗号分隔：").strip()
    if not raw:
        return []
    paths = [p.strip() for p in raw.replace("，", ",").split(",") if p.strip()]
    valid = []
    for p in paths:
        if os.path.exists(p):
            valid.append(p)
        else:
            print(f"路径{p}不存在")
    return valid


def detect_file_type(filepath: str) -> str:
    """通过文件扩展名判断文件类型。"""
    suffix = os.path.splitext(filepath)[1].lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".docx":
        return "docx"
    if suffix in TEXT_EXTENSIONS:
        return "text"
    raise ValueError(f"不支持的文件类型: {filepath}")


# ═══════════════════════════════════════════════
# 第二步：文档加载
# ═══════════════════════════════════════════════

def load_pdf(filepath: str) -> str:
    try:
        import fitz
        text = ""
        with fitz.open(filepath) as pdf:
            for page in pdf:
                page_text = page.get_text("text")
                if page_text:
                    text += page_text + "\n"
        return text
    except Exception:
        import pdfplumber
        try:
            text = ""
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            return text
        except Exception as e:
            raise ValueError(f"无法解析 PDF 文件 {filepath}: {e}") from e


def load_pdf_pages(filepath: str) -> list[tuple[str, int]]:
    try:
        import fitz
        pages = []
        with fitz.open(filepath) as pdf:
            for page_num, page in enumerate(pdf, start=1):
                page_text = page.get_text("text")
                if page_text:
                    pages.append((page_text, page_num))
        return pages
    except Exception:
        import pdfplumber
        try:
            pages = []
            with pdfplumber.open(filepath) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    page_text = page.extract_text()
                    if page_text:
                        pages.append((page_text, page_num))
            return pages
        except Exception as e:
            raise ValueError(f"无法解析 PDF 文件 {filepath}: {e}") from e


def load_docx(filepath: str) -> str:
    try:
        from docx import Document
        doc = Document(filepath)
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        raise ValueError(f"无法解析 DOCX 文件 {filepath}: {e}") from e


def load_text(filepath: str) -> str:
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        raise ValueError(f"无法读取文本文件 {filepath}: {e}") from e


LOADERS: dict[str, callable] = {
    "pdf": load_pdf,
    "docx": load_docx,
    "text": load_text,
}


def load_document(filepath: str) -> tuple[str, str]:
    file_type = detect_file_type(filepath)
    loader = LOADERS.get(file_type)
    if loader is None:
        raise ValueError(f"不支持的文件类型: {file_type} ({filepath})")
    text = loader(filepath)
    return text, file_type


# ═══════════════════════════════════════════════
# 第三步：按文件类型选择分块策略
# ═══════════════════════════════════════════════

from langchain_text_splitters import RecursiveCharacterTextSplitter


def get_splitter(file_type: str) -> RecursiveCharacterTextSplitter:
    chunk_size = 500
    chunk_overlap = 50
    separators = ["\n\n", "\n", ".", " ", ""]

    if file_type == "pdf":
        chunk_size = 400
    elif file_type == "text":
        chunk_size = 2000
        chunk_overlap = 200

    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=separators,
    )


# ═══════════════════════════════════════════════
# 第四步：Embedding + ChromaDB 索引
# ═══════════════════════════════════════════════

from sentence_transformers import SentenceTransformer
import chromadb

def _collection_exists(client: chromadb.Client, name:str) -> bool:
    try:
        client.get_collection(name)
        return True
    except Exception:
        return False
    
def prepare_index(
        file_paths: list[str],
        collection_name: str,
        force_rebuild: bool = False,
        progress_callback=None,
) -> tuple:
    client = chromadb.PersistentClient(path = CHROMA_DB_PATH)

    # 判断是否需要重新建立索引
    need_build = force_rebuild or not _collection_exists(client, collection_name)

    if need_build:
        print("索引重构中...")
        model, collection = build_index(file_paths, collection_name, client, force_rebuild=force_rebuild, progress_callback=progress_callback)
    else:
        print("检测到已有索引，正在加载...")
        model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        collection = client.get_collection(collection_name)

    all_data = collection.get()
    all_docs = all_data["documents"]
    all_metadatas = all_data["metadatas"]

    bm25 = build_bm25_index(all_docs)

    return model, collection, bm25, all_docs, all_metadatas

def build_index(
    file_paths: list[str],
    collection_name: str = DEFAULT_COLLECTION_NAME,
    client = None,
    force_rebuild: bool = False,
    progress_callback=None,
) -> tuple[SentenceTransformer, chromadb.Collection]:
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    if client is None:
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    # 清除已有数据，避免重复追加或 ID 冲突
    if force_rebuild:
        existing_count = collection.count()
        if existing_count > 0:
            print(f"检测到已有 {existing_count} 条索引，清除后重建")
            existing_ids = collection.get()["ids"]
            if existing_ids:
                collection.delete(ids=existing_ids)

    all_chunks: list[str] = []
    all_metadatas: list[dict] = []
    all_ids: list[str] = []

    for i, fp in enumerate(file_paths):
        if not os.path.exists(fp):
            print(f"  [跳过] 文件不存在: {fp}")
            continue
        if ".." in fp:
            print(f"  [跳过] 路径包含目录遍历: {fp}")
            continue
        if os.path.basename(fp) == ".env":
            print(f"  [跳过] 不支持对环境变量文件建立索引: {fp}")
            continue

        print(f"加载: {fp}")
        file_type = detect_file_type(fp)

        if file_type == "pdf":
            pages = load_pdf_pages(fp)
            splitter = get_splitter(file_type)
            file_prefix = hashlib.md5(fp.encode()).hexdigest()[:8]
            chunk_counter = 0
            for page_text, page_num in pages:
                chunks = splitter.split_text(page_text)
                for chunk in chunks:
                    all_chunks.append(chunk)
                    all_metadatas.append({
                        "source": os.path.basename(fp),
                        "file_type": file_type,
                        "chunk_index": chunk_counter,
                        "page": page_num,
                    })
                    all_ids.append(f"{file_prefix}_chunk_{len(all_chunks)}")
                    chunk_counter += 1
            if pages:
                first_page_text = pages[0][0]
                anchor_lines = first_page_text.splitlines()[:5]
                anchor_text = " ".join(line.strip() for line in anchor_lines if line.strip())
                if anchor_text:
                    all_chunks.append(anchor_text)
                    all_metadatas.append({
                        "source": os.path.basename(fp),
                        "file_type": file_type,
                        "chunk_index": -1,
                        "chunk_type": "anchor",
                        "source_path": fp,
                    })
                    all_ids.append(f"{file_prefix}_anchor")
            print(f" -> {file_type}, {chunk_counter} 个切片")
        else:
            text, _ = load_document(fp)
            splitter = get_splitter(file_type)
            chunks = splitter.split_text(text)
            print(f" -> {file_type}, {len(chunks)} 个切片")
            file_prefix = hashlib.md5(fp.encode()).hexdigest()[:8]
            for idx, chunk in enumerate(chunks):
                all_chunks.append(chunk)
                all_metadatas.append({
                    "source": os.path.basename(fp),
                    "file_type": file_type,
                    "chunk_index": idx,
                })
                all_ids.append(f"{file_prefix}_chunk_{idx}")

        if progress_callback:
            progress_callback(i + 1, len(file_paths))

    if not all_chunks:
        print("没有需要索引的内容")
        return model, collection

    embeddings = model.encode(all_chunks).tolist()

    collection.upsert(
        documents=all_chunks,
        embeddings=embeddings,
        metadatas=all_metadatas,
        ids=all_ids,
    )

    print(f"已索引 {collection.count()} 个文档块")
    return model, collection


def add_files_to_index(
    file_paths: list[str],
    model: SentenceTransformer,
    collection: chromadb.Collection,
) -> tuple[BM25Okapi, list[str], list[dict]]:
    all_chunks: list[str] = []
    all_metadatas: list[dict] = []
    all_ids: list[str] = []

    for fp in file_paths:
        if not os.path.exists(fp):
            print(f"  [跳过] 文件不存在: {fp}")
            continue
        if ".." in fp:
            print(f"  [跳过] 路径包含目录遍历: {fp}")
            continue
        if os.path.basename(fp) == ".env":
            print(f"  [跳过] 不支持对环境变量文件建立索引: {fp}")
            continue

        try:
            print(f"加载: {fp}")
            file_type = detect_file_type(fp)
        except ValueError as e:
            print(f"  [跳过] {e}")
            continue

        splitter = get_splitter(file_type)
        file_prefix = hashlib.md5(fp.encode()).hexdigest()[:8]

        if file_type == "pdf":
            try:
                pages = load_pdf_pages(fp)
            except ValueError as e:
                print(f"  [跳过] {e}")
                continue
            chunk_counter = 0
            for page_text, page_num in pages:
                chunks = splitter.split_text(page_text)
                for chunk in chunks:
                    all_chunks.append(chunk)
                    all_metadatas.append({
                        "source": os.path.basename(fp),
                        "file_type": file_type,
                        "chunk_index": chunk_counter,
                        "page": page_num,
                    })
                    all_ids.append(f"{file_prefix}_chunk_{len(all_chunks)}")
                    chunk_counter += 1
            if pages:
                first_page_text = pages[0][0]
                anchor_lines = first_page_text.splitlines()[:5]
                anchor_text = " ".join(line.strip() for line in anchor_lines if line.strip())
                if anchor_text:
                    all_chunks.append(anchor_text)
                    all_metadatas.append({
                        "source": os.path.basename(fp),
                        "file_type": file_type,
                        "chunk_index": -1,
                        "chunk_type": "anchor",
                        "source_path": fp,
                    })
                    all_ids.append(f"{file_prefix}_anchor")
            print(f" -> {file_type}, {chunk_counter} 个切片")
        else:
            try:
                text, _ = load_document(fp)
            except ValueError as e:
                print(f"  [跳过] {e}")
                continue
            chunks = splitter.split_text(text)
            print(f" -> {file_type}, {len(chunks)} 个切片")
            for idx, chunk in enumerate(chunks):
                all_chunks.append(chunk)
                all_metadatas.append({
                    "source": os.path.basename(fp),
                    "file_type": file_type,
                    "chunk_index": idx,
                })
                all_ids.append(f"{file_prefix}_chunk_{idx}")

    if all_chunks:
        embeddings = model.encode(all_chunks).tolist()
        collection.upsert(
            documents=all_chunks,
            embeddings=embeddings,
            metadatas=all_metadatas,
            ids=all_ids,
        )

    all_data = collection.get()
    all_docs = all_data["documents"]
    all_metadatas_full = all_data["metadatas"]
    bm25 = build_bm25_index(all_docs)

    return bm25, all_docs, all_metadatas_full


# ═══════════════════════════════════════════════
# 第五步：混合检索 (语义 + BM25 + RRF)
# ═══════════════════════════════════════════════

from rank_bm25 import BM25Okapi


_STRIP_PUNCT = re.compile(r'^[:;,\.!?\"\'\)]+|[:;,\.!?\"\'\(]+$')


def _tokenize(text: str) -> list[str]:
    raw = re.findall(r'[a-zA-Z]+[0-9]*|[0-9]+(?:\.[0-9]+)?|[\u4e00-\u9fff]+', text)
    return [_STRIP_PUNCT.sub('', t).lower() for t in raw if _STRIP_PUNCT.sub('', t)]


def build_bm25_index(documents: list[str]) -> BM25Okapi:
    tokenized = [_tokenize(doc) for doc in documents]
    if not tokenized or all(not t for t in tokenized):
        # rank_bm25 crashes on empty corpora (ZeroDivisionError in _initialize / _calc_idf).
        # Return a BM25 with a dummy token that never matches real queries.
        return BM25Okapi([["_"]])
    return BM25Okapi(tokenized)


def rrf_merge(
    semantic_results: list[tuple[str, float]],
    bm25_results: list[tuple[str, float]],
    documents: list[str] | None = None,
    metadatas: list[dict] | None = None,
    k: int = 30,
) -> list[tuple[str, float]]:
    rrf_scores: dict[str, float] = {}
    for rank, (doc, _) in enumerate(semantic_results):
        rrf_scores[doc] = rrf_scores.get(doc, 0.0) + 1.0 / (rank + k)
    for rank, (doc, _) in enumerate(bm25_results):
        rrf_scores[doc] = rrf_scores.get(doc, 0.0) + 1.0 / (rank + k)
    if documents is not None and metadatas is not None:
        doc_to_meta = {doc: meta for doc, meta in zip(documents, metadatas)}
        for doc in rrf_scores:
            meta = doc_to_meta.get(doc, {})
            if meta.get("chunk_type") == "anchor":
                rrf_scores[doc] *= 2
    return sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)


def dynamic_top_k(scores: list[float], min_k: int = DEFAULT_MIN_K, max_k: int = DEFAULT_MAX_K) -> int:
    if len(scores) <= min_k:
        return len(scores)

    max_gap = 0
    cut = max_k
    for i in range(min_k, min(max_k, len(scores))):
        gap = scores[i - 1] - scores[i]
        if gap > max_gap:
            max_gap = gap
            cut = i
    return cut


def _build_context(
    top_indices: list[int],
    docs: list[str],
    metadatas: list[dict],
) -> str:
    """将 top-ranked chunk 拼接为 LLM context，每个 chunk 前标注来源文件名。

    Args:
        top_indices: 排序后的 chunk 索引列表，值作为 docs 和 metadatas 的索引
        docs:        全量文档文本列表（docs[i] 获取第 i 个文档文本）
        metadatas:   全量元数据列表（metadatas[i]["source"] 获取第 i 个文档的文件名）

    Returns:
        带 [Source: filename] 标注的 context 字符串，chunk 间以双换行分隔
    """
    parts = []
    for i in top_indices:
        source = metadatas[i].get("source", "unknown")
        parts.append(f"[Source: {source}]\n{docs[i]}")
    return "\n\n".join(parts)


def enrich_context(
    top_indices: list[int],
    documents: list[str],
    metadatas: list[dict],
) -> list[str]:
    """当 top-k 含 anchor chunk 时，用 PDF 首页全文替换其文本。

    Args:
        top_indices: dynamic_top_k 筛选后的索引列表
        documents: 全部文档文本（按索引查找）
        metadatas: 全部元数据（按索引查找）

    Returns:
        新列表（浅拷贝），anchor chunk 的文本被替换为 PDF 首页全文
    """
    enriched = documents[:]
    for idx in top_indices:
        meta = metadatas[idx]
        if meta.get("chunk_type") == "anchor":
            source_path = meta.get("source_path", "")
            if source_path and os.path.exists(source_path):
                try:
                    pages = load_pdf_pages(source_path)
                    if pages:
                        enriched[idx] = pages[0][0]
                except Exception:
                    pass
    return enriched


def retrieve_hybrid_with_sources(
    query: str,
    model: SentenceTransformer,
    collection: chromadb.Collection,
    bm25: BM25Okapi,
    documents: list[str],
    metadatas: list[dict] | None = None,
    k: int = DEFAULT_TOP_K,
) -> tuple[list[str], list[str], list[float]]:
    query_embedding = model.encode([query]).tolist()
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=k,
    )
    sem_docs = results["documents"][0]
    sem_distances = results["distances"][0]
    semantic_results = list(zip(sem_docs, sem_distances))

    query_tokens = _tokenize(query)
    bm25_scores = bm25.get_scores(query_tokens)
    bm25_results = sorted(
        zip(range(len(documents)), documents, bm25_scores), 
        key=lambda x: x[2], reverse=True
    )

    bm25_for_rrf = [(doc, score) for _, doc, score in bm25_results[:k]]

    fused = rrf_merge(semantic_results, bm25_for_rrf, documents, metadatas)

    # 根据doc内容找到原始索引和metadata
    doc_to_idx = {doc: i for i, doc in enumerate(documents)}
    indices = []
    docs = []
    scores = []
    for doc, score in fused:
        if doc in doc_to_idx:
            indices.append(doc_to_idx[doc])
            docs.append(doc)
            scores.append(score)

    return indices, docs, scores

def format_sources(
        indices: list[int],
        documents: list[str],
        metadatas: list[dict],
) -> str:
    """格式化参考来源，返回 [rank] filename (片段N): 前150字符..."""
    lines = []
    for rank, idx in enumerate(indices[:5], 1):   # 只显示前五个
        meta = metadatas[idx]
        source = meta.get("source", "未知文件")
        chunk_index = meta.get("chunk_index", idx)
        snippet = documents[idx].replace("\n", " ")[:150]
        lines.append(f"[{rank}] {source} (片段{chunk_index}): {snippet}...")
    return "\n".join(lines)

# ═══════════════════════════════════════════════
# 第六步：LLM 生成回答
# ═══════════════════════════════════════════════

from openai import OpenAI, APIError, APIConnectionError, RateLimitError


def answer_with_llm_history(
    question: str,
    context: str,
    history: list[tuple[str, str]],
    model: str = DEFAULT_LLM_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
) -> str:
    api_key = os.getenv("API_KEY")
    base_url = os.getenv("BASE_URL")

    if not api_key or not base_url:
        raise ValueError("请在 .env 文件中设置 API_KEY 和 BASE_URL")

    client = OpenAI(api_key=api_key, base_url=base_url)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    for q, a in history[-5:]:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})

    prompt = PROMPT_TEMPLATE.format(context=context, question=question)
    messages.append({"role": "user", "content": prompt})
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
    except RateLimitError:
        return "API 请求频率超限，请稍后重试。"
    except APIConnectionError:
        return "无法连接到 API 服务，请检查网络或 BASE_URL 配置。"
    except APIError as e:
        return f"API 请求失败: {e}"

    return response.choices[0].message.content

def answer_query(
        query: str,
        model: SentenceTransformer,
        collection: chromadb.Collection,
        bm25: BM25Okapi,
        documents: list[str],
        metadatas: list[dict],
        history = None,
        temperature: float = DEFAULT_TEMPERATURE,
):
    from rag_query_decomposer import decompose_query_llm

    # ── LLM 查询拆解 ──
    sub_queries = decompose_query_llm(query)

    # ── 子查询并发检索 ──
    all_entries = []
    with ThreadPoolExecutor(max_workers=min(4, len(sub_queries))) as executor:
        futures = {
            executor.submit(
                retrieve_hybrid_with_sources,
                sq, model, collection, bm25, documents, metadatas,
            ): sq for sq in sub_queries
        }
        for future in as_completed(futures):
            indices, _, scores = future.result()
            for idx, score in zip(indices, scores):
                all_entries.append((idx, score))

    # ── 按 chunk 去重：仅保留每个 chunk 的最高分 ──
    best_score: dict[int, float] = {}
    for idx, score in all_entries:
        if idx not in best_score or score > best_score[idx]:
            best_score[idx] = score

    merged = sorted(best_score.keys(), key=lambda i: best_score[i], reverse=True)
    scores_flat = sorted(best_score.values(), reverse=True)
    k = dynamic_top_k(scores_flat)
    top_indices = merged[:k]
    enriched_docs = enrich_context(top_indices, documents, metadatas)
    context = _build_context(top_indices, enriched_docs, metadatas)

    answer = answer_with_llm_history(
        query, context, history or [], temperature=temperature,
    )

    sources = format_sources(top_indices, enriched_docs, metadatas)

    return answer, sources


# ═══════════════════════════════════════════════
# RAG 主流程
# ═══════════════════════════════════════════════

def rag_pipeline(
    file_paths: list[str],
    query: str,
    collection_name: Optional[str] = None,
    force_rebuild: bool = False,
) -> Optional[str]:
    if collection_name is None:
        name_input = "|".join(sorted(file_paths))
        collection_name = "rag_" + hashlib.md5(name_input.encode()).hexdigest()[:8]

    print("=" * 60)
    print(f"步骤 1-4: 索引构建 (collection: {collection_name})")
    print("=" * 60)
    _t0 = time.time()
    model, collection, bm25, all_docs, all_metadatas = prepare_index(
        file_paths, collection_name, force_rebuild
    )
    _t1 = time.time()

    if not all_docs:
        print("文档库为空")
        return

    _elapsed = _t1 - _t0
    _minutes = int(_elapsed // 60)
    _seconds = int(_elapsed % 60)
    print(f"文档库就绪（用时{_minutes}分{_seconds}秒）")

    _tq0 = time.time()
    answer, _ = answer_query(query, model, collection, bm25, all_docs, all_metadatas)
    _tq1 = time.time()
    _qelapsed = _tq1 - _tq0
    _qminutes = int(_qelapsed // 60)
    _qseconds = int(_qelapsed % 60)
    print(f"{answer}（用时{_qminutes}分{_qseconds}秒）")
    return answer


# ═══════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG Pipeline")
    parser.add_argument("--files", nargs="+", default=None)
    parser.add_argument("--collection", default=None, help="ChromaDB collection 名称（默认按文件列表自动生成）")
    parser.add_argument("--rebuild", action="store_true", help="强制重建索引")
    parser.add_argument("--query", default=None, help="提问内容（不传则交互式输入）")
    args = parser.parse_args()

    # 1.获取文件路径
    if args.files:
        file_paths = args.files
    else:
        file_paths = ask_for_files()
        if not file_paths:
            print("没有有效文件")
            exit(1)

    # 2.准备索引
    collection_name = args.collection or (
        "rag_" + hashlib.md5("|".join(sorted(file_paths)).encode()).hexdigest()[:8]
    )
    _t0 = time.time()
    model, collection, bm25, all_docs, all_metadatas = prepare_index(
        file_paths, collection_name, args.rebuild
    )
    _t1 = time.time()

    if not all_docs:
        print("文档库为空")
        exit(1)

    _elapsed = _t1 - _t0
    _minutes = int(_elapsed // 60)
    _seconds = int(_elapsed % 60)
    print(f"文档库就绪（用时{_minutes}分{_seconds}秒）\n")
    print("-" * 100)

    # 3.对话循环
    history = []
    while True:
        query = input("请输入问题（q以退出，+add以添加文件）: ")
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
            print(f"已新增索引，当前共 {len(all_docs)} 个文档块")
            continue
        _tq0 = time.time()
        answer, sources = answer_query(
            query = query,
            model = model,
            collection = collection,
            bm25 = bm25,
            documents = all_docs,
            metadatas = all_metadatas,
            history = history,
        )
        _tq1 = time.time()
        _qelapsed = _tq1 - _tq0
        _qminutes = int(_qelapsed // 60)
        _qseconds = int(_qelapsed % 60)

        print(f"\n\n{answer}（用时{_qminutes}分{_qseconds}秒）")
        print(f"\n参考来源：\n{sources}\n\n")
        print("=" * 100)

        history.append((query, answer))


# ═══════════════════════════════════════════════
# 流式 LLM 生成
# ═══════════════════════════════════════════════

from typing import Generator


def answer_with_llm_history_stream(
    question: str,
    context: str,
    history: list[tuple[str, str]],
    model: str = DEFAULT_LLM_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
) -> Generator[str, None, None]:
    api_key = os.getenv("API_KEY")
    base_url = os.getenv("BASE_URL")
    if not api_key or not base_url:
        yield "[错误] 请在 .env 文件中设置 API_KEY 和 BASE_URL"
        return
    client = OpenAI(api_key=api_key, base_url=base_url)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for q, a in history[-5:]:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})
    prompt = PROMPT_TEMPLATE.format(context=context, question=question)
    messages.append({"role": "user", "content": prompt})
    try:
        response = client.chat.completions.create(
            model=model, messages=messages, temperature=temperature, stream=True,
        )
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
    except RateLimitError:
        yield "\n[API 请求频率超限，请稍后重试]"
    except APIConnectionError:
        yield "\n[无法连接到 API 服务，请检查网络或 BASE_URL 配置]"
    except APIError as e:
        yield f"\n[API 请求失败: {e}]"


def answer_query_stream(
    query: str,
    model: SentenceTransformer,
    collection: chromadb.Collection,
    bm25: BM25Okapi,
    documents: list[str],
    metadatas: list[dict],
    history=None,
    top_k_range=(3, 20),
    temperature=0.1,
    llm_model: str = DEFAULT_LLM_MODEL,
) -> tuple[Generator[str, None, None], str]:
    from rag_query_decomposer import decompose_query_llm

    # ── LLM 查询拆解 ──
    sub_queries = decompose_query_llm(query, model=llm_model)

    # ── 子查询并发检索 ──
    all_entries = []  # [(idx, score), ...]
    with ThreadPoolExecutor(max_workers=min(4, len(sub_queries))) as executor:
        futures = {
            executor.submit(
                retrieve_hybrid_with_sources,
                sq, model, collection, bm25, documents, metadatas,
                k=max(top_k_range),
            ): sq for sq in sub_queries
        }
        for future in as_completed(futures):
            indices, _, scores = future.result()
            for idx, score in zip(indices, scores):
                all_entries.append((idx, score))

    # ── 按 chunk 去重：仅保留每个 chunk 的最高分 ──
    best_score: dict[int, float] = {}
    for idx, score in all_entries:
        if idx not in best_score or score > best_score[idx]:
            best_score[idx] = score

    # ── 降序排列 ──
    merged = sorted(best_score.keys(), key=lambda i: best_score[i], reverse=True)

    # dynamic_top_k 作用于去重后的分数列表
    scores_flat = sorted(best_score.values(), reverse=True)
    k = dynamic_top_k(scores_flat, min_k=top_k_range[0], max_k=top_k_range[1])
    top_indices = merged[:k]

    enriched_docs = enrich_context(top_indices, documents, metadatas)
    context = _build_context(top_indices, enriched_docs, metadatas)
    sources = format_sources(top_indices, enriched_docs, metadatas)
    stream = answer_with_llm_history_stream(
        query, context, history or [], model=llm_model, temperature=temperature,
    )
    return stream, sources


def remove_file_from_index(
    filename: str,
    collection: chromadb.Collection,
) -> int:
    all_data = collection.get()
    ids_to_delete = [
        id_ for id_, meta in zip(all_data["ids"], all_data["metadatas"])
        if meta.get("source") == filename
    ]
    if ids_to_delete:
        collection.delete(ids=ids_to_delete)
    return len(ids_to_delete)