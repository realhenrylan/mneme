"""结构化分块：基于 Section 边界切分 Document。

分块策略：
1. 优先在 Section 边界切分（保留语义完整性）
2. 超长 Section 使用 RecursiveCharacterTextSplitter 二次切分
3. 每个 Chunk 保留来源 Section 的标题路径和类型信息
4. PDF anchor chunk 特殊处理（首页摘要）

与 rag.py 的 CHUNKING_CONFIG 兼容，chunking_version 升至 3。
"""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.domain import Chunk, Document, Section, SectionType


# 分块配置（与 rag.py CHUNKING_CONFIG 对齐，version 升至 3）
CHUNKING_CONFIG_V3 = {
    "version": 3,
    "default": {
        "size": 500,
        "overlap": 50,
        "separators": ["\n\n", "\n", "。", "！", "？", "；", ".", " ", ""],
    },
    "pdf": {
        "size": 400,
        "overlap": 50,
        "separators": ["\n\n", "\n", "。", "！", "？", "；", ".", " ", ""],
    },
    "text": {
        "size": 2000,
        "overlap": 200,
        "separators": ["\n\n", "\n", "。", "！", "？", "；", ".", " ", ""],
    },
}


def _get_splitter(file_type: str) -> RecursiveCharacterTextSplitter:
    """按文件类型获取分块器。"""
    config = CHUNKING_CONFIG_V3.get(file_type, CHUNKING_CONFIG_V3["default"])
    return RecursiveCharacterTextSplitter(
        chunk_size=config["size"],
        chunk_overlap=config["overlap"],
        separators=config["separators"],
    )


def chunk_document(document: Document) -> list[Chunk]:
    """将 Document 的 Sections 切分为 Chunks。

    策略：
    1. 每个 Section 尝试整体作为一个 Chunk
    2. 超长 Section 用 RecursiveCharacterTextSplitter 二次切分
    3. 每个 Chunk 保留 section_heading、section_type、page 等元数据
    4. PDF 文档额外添加 anchor chunk（首页摘要）

    Args:
        document: 解析后的 Document 对象

    Returns:
        Chunk 列表，每个 Chunk 包含文本和元数据
    """
    splitter = _get_splitter(document.file_type)
    chunk_size = splitter._chunk_size
    chunks: list[Chunk] = []
    chunk_counter = 0
    source_id = document.source_id

    for section in document.sections:
        if not section.text.strip():
            continue

        # Section 内文本不超过 chunk_size → 整体作为一个 Chunk
        if len(section.text) <= chunk_size:
            chunk_id = f"{source_id}_chunk_{chunk_counter}"
            chunks.append(Chunk(
                text=section.text,
                chunk_id=chunk_id,
                chunk_index=chunk_counter,
                page=section.page,
                section_heading=section.heading_path,
                section_type=section.section_type,
                char_start=section.char_start,
                char_end=section.char_end,
            ))
            chunk_counter += 1
        else:
            # 超长 Section → 二次切分
            sub_texts = splitter.split_text(section.text)
            for sub_text in sub_texts:
                chunk_id = f"{source_id}_chunk_{chunk_counter}"
                chunks.append(Chunk(
                    text=sub_text,
                    chunk_id=chunk_id,
                    chunk_index=chunk_counter,
                    page=section.page,
                    section_heading=section.heading_path,
                    section_type=section.section_type,
                    char_start=section.char_start,
                    char_end=section.char_end,
                ))
                chunk_counter += 1

    # PDF anchor chunk：首页前 5 行摘要
    if document.file_type == "pdf" and document.sections:
        first_page_sections = [
            s for s in document.sections
            if s.page == 1 and s.text.strip()
        ]
        if first_page_sections:
            anchor_lines = first_page_sections[0].text.splitlines()[:5]
            anchor_text = " ".join(line.strip() for line in anchor_lines if line.strip())
            if anchor_text:
                chunk_id = f"{source_id}_anchor"
                chunks.append(Chunk(
                    text=anchor_text,
                    chunk_id=chunk_id,
                    chunk_index=-1,
                    page=1,
                    section_heading="",
                    section_type=SectionType.OTHER,
                    metadata={"chunk_type": "anchor"},
                ))

    return chunks


def chunks_to_index_data(
    document: Document,
) -> tuple[list[str], list[dict], list[str]]:
    """将 Document 的 Chunks 转换为索引所需的数据。

    Returns:
        (texts, metadatas, ids) 三元组，可直接传入 ChromaDB upsert
    """
    texts: list[str] = []
    metadatas: list[dict] = []
    ids: list[str] = []

    for chunk in document.chunks:
        # 合并 source 级元数据和 chunk 级元数据
        metadata = {
            "source_id": document.source_id,
            "source_path": document.source_path,
            "source_name": document.source_name,
            "source": document.source_name,  # 兼容字段
            "file_type": document.file_type,
            "content_sha256": document.content_sha256,
            "source_size": document.source_size,
            "source_mtime_ns": document.source_mtime_ns,
            # chunk 级元数据
            "chunk_id": chunk.chunk_id,
            "chunk_index": chunk.chunk_index,
            "section_heading": chunk.section_heading,
            "section_type": chunk.section_type.value,
        }
        if chunk.page is not None:
            metadata["page"] = chunk.page
        # anchor chunk 标记
        if chunk.metadata.get("chunk_type") == "anchor":
            metadata["chunk_type"] = "anchor"
        # 扩展元数据
        metadata.update(chunk.metadata)

        texts.append(chunk.text)
        metadatas.append(metadata)
        ids.append(chunk.chunk_id)

    return texts, metadatas, ids
