"""词法分析模块：CJK n-gram tokenizer、字段加权 BM25 语料构建。

从 src/rag.py 的 _tokenize() 迁移并增强，解决连续 CJK 字符被当作一个 token 的问题。
同时支持元数据字段加权，让 BM25 能利用 source_name、section 等结构化信息。

3.3 增强：持久化 BM25 快照 + 增量更新，避免每次启动全量重建。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Sequence

from rank_bm25 import BM25Okapi


# ── CJK 字符范围 ──

_CJK_RANGES = (
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3400, 0x4DBF),   # CJK Extension A
    (0x20000, 0x2A6DF), # CJK Extension B
    (0xF900, 0xFAFF),   # CJK Compatibility Ideographs
    (0x2F800, 0x2FA1F), # CJK Compatibility Ideographs Supplement
)


def is_cjk(ch: str) -> bool:
    """判断字符是否为 CJK 汉字。"""
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


# ── 标点清理 ──

_STRIP_PUNCT = re.compile(r'^[:;,\.!?\"\'\)\]]+|[:;,\.!?\"\'\(\[]+$')


# ── n-gram tokenizer ──


def _cjk_ngrams(chars: list[str], n: int = 2) -> list[str]:
    """从 CJK 字符列表生成 n-gram。

    单字也保留（作为 unigram 补充），确保短查询也能匹配。
    示例：["南", "京", "总", "面", "积"] → ["南", "南京", "京", "京总", "总", "总面", "面", "面积", "积"]
    """
    if not chars:
        return []
    result: list[str] = []
    for i, ch in enumerate(chars):
        # 保留单字（unigram），对短查询至关重要
        result.append(ch)
        # 生成 bigram
        if i + 1 < len(chars):
            result.append(ch + chars[i + 1])
    return result


def cjk_ngram_tokenize(text: str, n: int = 2) -> list[str]:
    """CJK 字符按 n-gram 切分，英文/数字按空格和标点分词。

    处理规则：
    1. CJK 字符：收集连续 CJK 序列，生成 unigram + bigram
    2. 英文/数字：按空格和标点分词，保留完整词
    3. 混合文本：CJK 和非 CJK 交替出现时，各自独立处理
    4. 所有 token 小写化
    5. 不做停用词过滤（BM25Okapi 内部有 IDF 处理）

    示例：
      "南京总面积约6587km2" → ["南", "南京", "京", "京总", "总", "总面", "面", "面积", "积", "6587km2"]
      "What is RAG?" → ["what", "is", "rag"]
    """
    tokens: list[str] = []
    cjk_buffer: list[str] = []
    non_cjk_buffer: list[str] = []

    def flush_cjk():
        nonlocal cjk_buffer
        if cjk_buffer:
            tokens.extend(_cjk_ngrams(cjk_buffer, n))
            cjk_buffer = []

    def flush_non_cjk():
        nonlocal non_cjk_buffer
        if non_cjk_buffer:
            word = "".join(non_cjk_buffer).lower()
            stripped = _STRIP_PUNCT.sub("", word)
            if stripped:
                tokens.append(stripped)
            non_cjk_buffer = []

    for ch in text:
        if is_cjk(ch):
            flush_non_cjk()
            cjk_buffer.append(ch)
        else:
            flush_cjk()
            # 空格和标点作为分隔符（包括 CJK 标点）
            if ch in (" ", "\t", "\n", "\r"):
                flush_non_cjk()
            elif ch in ".,;:!?\"'()[]{}<>-/\\|@#$%^&*+=~`。，、；：！？「」『』（）【】《》—…·":
                flush_non_cjk()
            else:
                non_cjk_buffer.append(ch)

    flush_cjk()
    flush_non_cjk()
    return tokens


# ── 向后兼容的 _tokenize ──


def _tokenize_legacy(text: str) -> list[str]:
    """原始 tokenizer（连续 CJK 被当作一个 token），用于向后兼容和基线对比。"""
    raw = re.findall(r'[a-zA-Z]+[0-9]*|[0-9]+(?:\.[0-9]+)?|[\u4e00-\u9fff]+', text)
    return [_STRIP_PUNCT.sub('', t).lower() for t in raw if _STRIP_PUNCT.sub('', t)]


# ── 字段加权 BM25 语料构建 ──


def build_weighted_bm25_corpus(
    documents: list[str],
    metadatas: list[dict],
    field_weights: dict[str, float] | None = None,
) -> list[str]:
    """构建带字段权重的 BM25 语料。

    字段权重通过重复文本实现：source_name 权重 2.0 意味着重复 2 次。
    这让 BM25 的 IDF/TF 计算自然地提升命中文档名的查询排名。

    Args:
        documents: chunk 文本列表
        metadatas: chunk 元数据列表
        field_weights: 字段权重映射，默认 {"source_name": 2.0, "section": 1.5}

    Returns:
        加权后的语料列表，每个元素是对应 chunk 的加权文本
    """
    weights = field_weights if field_weights is not None else {"source_name": 2.0, "section": 1.5, "section_heading": 1.5}
    corpus: list[str] = []
    for doc, meta in zip(documents, metadatas):
        parts = [doc]  # content * 1.0
        name = meta.get("source_name", "")
        if name and "source_name" in weights:
            repeat = max(1, int(weights["source_name"]))
            parts.extend([name] * repeat)
        section = meta.get("section", "")
        if section and "section" in weights:
            repeat = max(1, int(weights["section"]))
            parts.extend([section] * repeat)
        # section_heading：新字段，标题路径参与 BM25 索引
        section_heading = meta.get("section_heading", "")
        if section_heading and "section_heading" in weights:
            repeat = max(1, int(weights["section_heading"]))
            parts.extend([section_heading] * repeat)
        corpus.append(" ".join(parts))
    return corpus


# ── BM25 索引构建 ──


def build_bm25_index(
    documents: list[str],
    ids: list[str] | None = None,
    previous_snapshot: dict | None = None,
    metadatas: list[dict] | None = None,
    field_weights: dict[str, float] | None = None,
    use_cjk_ngram: bool = True,
) -> BM25Okapi:
    """构建 BM25 索引，支持 CJK n-gram tokenizer 和字段加权。

    Args:
        documents: chunk 文本列表
        ids: chunk ID 列表
        previous_snapshot: 上次索引快照（用于增量复用 tokenization）
        metadatas: chunk 元数据列表（用于字段加权）
        field_weights: 字段权重映射
        use_cjk_ngram: 是否使用 CJK n-gram tokenizer（True）或原始 tokenizer（False）

    Returns:
        BM25Okapi 索引实例
    """
    ids = ids or [str(index) for index in range(len(documents))]
    previous_snapshot = previous_snapshot or {}
    previous_hashes = previous_snapshot.get("document_hashes", {})
    previous_tokens = previous_snapshot.get("tokenized", {})

    # 选择 tokenizer
    tokenize_fn = cjk_ngram_tokenize if use_cjk_ngram else _tokenize_legacy

    # 构建加权语料（如果提供了 metadatas）
    if metadatas is not None and field_weights is not False:
        corpus = build_weighted_bm25_corpus(documents, metadatas, field_weights)
    else:
        corpus = documents

    tokenized: list[list[str]] = []
    cache: dict[str, list[str]] = {}
    for chunk_id, document in zip(ids, corpus):
        document = document or ""
        document_hash = hashlib.sha256(
            document.encode("utf-8", errors="replace")
        ).hexdigest()
        if (
            previous_hashes.get(chunk_id) == document_hash
            and isinstance(previous_tokens.get(chunk_id), list)
        ):
            tokens = previous_tokens[chunk_id]
        else:
            tokens = tokenize_fn(document)
        tokenized.append(tokens)
        cache[chunk_id] = tokens

    # rank_bm25 crashes on empty corpora (ZeroDivisionError in _initialize / _calc_idf).
    index = BM25Okapi(tokenized if tokenized and any(tokenized) else [["_"]])
    setattr(index, "tokenized_by_chunk_id", cache)
    setattr(index, "document_hashes", {
        chunk_id: hashlib.sha256((document or "").encode("utf-8", errors="replace")).hexdigest()
        for chunk_id, document in zip(ids, corpus)
    })
    return index


# ═══════════════════════════════════════════════════════════════
# BM25 快照持久化与增量更新
# ═══════════════════════════════════════════════════════════════

BM25_SNAPSHOT_VERSION = 2  # 快照格式版本


def save_bm25_snapshot(
    bm25_index: BM25Okapi,
    filepath: str,
    manifest_version: int | None = None,
) -> None:
    """将 BM25 索引快照持久化到磁盘。

    保存 tokenized 结果和 document hashes，下次启动可直接加载，
    避免全量重新 tokenize。
    """
    tokenized = getattr(bm25_index, "tokenized_by_chunk_id", {})
    doc_hashes = getattr(bm25_index, "document_hashes", {})

    snapshot = {
        "schema_version": BM25_SNAPSHOT_VERSION,
        "manifest_version": manifest_version,
        "chunk_ids": sorted(tokenized.keys()),
        "document_hashes": doc_hashes,
        "tokenized": tokenized,
    }

    # 原子写入：先写临时文件，再 rename
    tmp_path = filepath + ".tmp"
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False)
    # Windows 需要先删除目标文件
    if os.path.exists(filepath):
        os.replace(tmp_path, filepath)
    else:
        os.rename(tmp_path, filepath)


def load_bm25_snapshot_from_disk(filepath: str) -> dict | None:
    """从磁盘加载 BM25 快照。

    Returns:
        快照字典，或 None（文件不存在或格式错误）
    """
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            snapshot = json.load(f)
        # 版本检查
        if snapshot.get("schema_version", 1) < BM25_SNAPSHOT_VERSION:
            # 旧版快照格式不兼容，返回 None 触发全量重建
            return None
        return snapshot
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def incremental_bm25_update(
    existing_snapshot: dict | None,
    new_documents: list[str],
    new_ids: list[str],
    new_metadatas: list[dict] | None = None,
    removed_ids: set[str] | None = None,
    field_weights: dict[str, float] | None = None,
    use_cjk_ngram: bool = True,
) -> dict:
    """增量更新 BM25 快照数据。

    只对新增/变更的 chunk 重新 tokenize，已存在且未变更的 chunk 复用缓存。
    删除的 chunk 从快照中移除。

    Args:
        existing_snapshot: 现有快照（来自 load_bm25_snapshot_from_disk）
        new_documents: 新增/更新的 chunk 文本
        new_ids: 对应的 chunk ID
        new_metadatas: 对应的元数据
        removed_ids: 需要删除的 chunk ID 集合
        field_weights: 字段权重
        use_cjk_ngram: 是否使用 CJK n-gram

    Returns:
        更新后的快照字典（可直接传给 build_bm25_index 的 previous_snapshot）
    """
    existing_snapshot = existing_snapshot or {}
    previous_hashes = existing_snapshot.get("document_hashes", {})
    previous_tokens = existing_snapshot.get("tokenized", {})

    tokenize_fn = cjk_ngram_tokenize if use_cjk_ngram else _tokenize_legacy
    removed_ids = removed_ids or set()

    # 移除已删除的 chunk
    for rid in removed_ids:
        previous_hashes.pop(rid, None)
        previous_tokens.pop(rid, None)

    # 构建加权语料
    if new_metadatas is not None and field_weights is not False:
        corpus = build_weighted_bm25_corpus(new_documents, new_metadatas, field_weights)
    else:
        corpus = new_documents

    # 增量 tokenize：只处理新增/变更的 chunk
    for chunk_id, document in zip(new_ids, corpus):
        document = document or ""
        doc_hash = hashlib.sha256(
            document.encode("utf-8", errors="replace")
        ).hexdigest()

        if previous_hashes.get(chunk_id) == doc_hash and isinstance(previous_tokens.get(chunk_id), list):
            # 未变更，复用缓存
            continue

        # 新增或变更，重新 tokenize
        previous_tokens[chunk_id] = tokenize_fn(document)
        previous_hashes[chunk_id] = doc_hash

    return {
        "schema_version": BM25_SNAPSHOT_VERSION,
        "document_hashes": previous_hashes,
        "tokenized": previous_tokens,
    }


def build_bm25_from_snapshot(
    snapshot: dict,
    use_cjk_ngram: bool = True,
) -> BM25Okapi:
    """从快照数据构建 BM25 索引（跳过 tokenize 步骤）。

    适用于启动时从持久化快照恢复，避免全量重新 tokenize。
    """
    tokenized_by_id = snapshot.get("tokenized", {})
    chunk_ids = sorted(tokenized_by_id.keys())

    if not chunk_ids or not any(tokenized_by_id.values()):
        index = BM25Okapi([["_"]])
        setattr(index, "tokenized_by_chunk_id", {})
        setattr(index, "document_hashes", {})
        return index

    tokenized_list = [tokenized_by_id[cid] for cid in chunk_ids]
    index = BM25Okapi(tokenized_list)
    setattr(index, "tokenized_by_chunk_id", tokenized_by_id)
    setattr(index, "document_hashes", snapshot.get("document_hashes", {}))
    return index
