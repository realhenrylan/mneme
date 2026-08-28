"""结构化分块：基于 Section 边界切分 Document + Parent-Child 关系。

分块策略：
1. 优先在 Section 边界切分（保留语义完整性）
2. 超长 Section 使用 RecursiveCharacterTextSplitter 二次切分
3. 每个 Chunk 保留来源 Section 的标题路径和类型信息
4. Parent-Child 关系：超长 Section 切分后，创建 parent chunk（完整 Section 文本）
5. 邻接扩展：chunk metadata 记录前后相邻 chunk_id
6. PDF anchor chunk 特殊处理（首页摘要）

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

# Parent chunk 的最大长度：超过此长度的 Section 不创建 parent chunk
# 避免 parent chunk 过大导致 embedding 质量下降
MAX_PARENT_CHUNK_CHARS = 2000


def _get_splitter(file_type: str) -> RecursiveCharacterTextSplitter:
    """按文件类型获取分块器。"""
    config = CHUNKING_CONFIG_V3.get(file_type, CHUNKING_CONFIG_V3["default"])
    return RecursiveCharacterTextSplitter(
        chunk_size=config["size"],
        chunk_overlap=config["overlap"],
        separators=config["separators"],
    )


def chunk_document(document: Document) -> list[Chunk]:
    """将 Document 的 Sections 切分为 Chunks，建立 Parent-Child 关系。

    策略：
    1. 每个 Section 尝试整体作为一个 Chunk
    2. 超长 Section 用 RecursiveCharacterTextSplitter 二次切分为 child chunks
    3. 超长 Section 额外创建 parent chunk（完整 Section 文本），child chunks 通过
       parent_chunk_id 关联到 parent
    4. 每个 Chunk 保留 section_heading、section_type、page 等元数据
    5. PDF 文档额外添加 anchor chunk（首页摘要）
    6. 邻接关系通过 chunk_index 顺序推断，不显式存储

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

        # Section 内文本不超过 chunk_size → 整体作为一个 Chunk（无 parent-child）
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
            # 超长 Section → 创建 parent chunk + child chunks
            # parent chunk：Section 完整文本（用于提供完整上下文）
            # child chunks：切分后的片段（用于精确召回）
            parent_chunk_id = None

            # 如果 Section 不太长，创建 parent chunk
            if len(section.text) <= MAX_PARENT_CHUNK_CHARS:
                parent_chunk_id = f"{source_id}_chunk_{chunk_counter}"
                chunks.append(Chunk(
                    text=section.text,
                    chunk_id=parent_chunk_id,
                    chunk_index=chunk_counter,
                    page=section.page,
                    section_heading=section.heading_path,
                    section_type=section.section_type,
                    char_start=section.char_start,
                    char_end=section.char_end,
                    metadata={"chunk_type": "parent"},
                ))
                chunk_counter += 1

            # 切分为 child chunks
            sub_texts = splitter.split_text(section.text)
            child_chunk_ids: list[str] = []
            for sub_text in sub_texts:
                chunk_id = f"{source_id}_chunk_{chunk_counter}"
                child_chunk_ids.append(chunk_id)
                chunks.append(Chunk(
                    text=sub_text,
                    chunk_id=chunk_id,
                    chunk_index=chunk_counter,
                    page=section.page,
                    section_heading=section.heading_path,
                    section_type=section.section_type,
                    char_start=section.char_start,
                    char_end=section.char_end,
                    parent_chunk_id=parent_chunk_id,
                    metadata={"chunk_type": "child"},
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


def expand_with_parent(
    top_indices: list[int],
    documents: list[str],
    metadatas: list[dict],
    context_k: int,
) -> tuple[list[int], list[str]]:
    """对召回的 child chunks，用其 parent chunk 替换，提供更完整的上下文。

    策略：
    1. 遍历 top_indices 中的每个 chunk
    2. 如果 chunk 是 child 类型且有 parent_chunk_id，用 parent 替换
    3. 去重：多个 child 指向同一 parent 时只保留一个
    4. 替换后不超过 context_k 个 chunk

    Args:
        top_indices: 排序后的 chunk 索引列表
        documents: 全量文档文本列表
        metadatas: 全量元数据列表
        context_k: 最大 chunk 数

    Returns:
        (expanded_indices, expansion_info) 元组
        expansion_info 是替换记录列表，每项为 (original_idx, parent_idx) 或 (idx, idx)
    """
    # 建立 chunk_id → index 的映射
    chunk_id_to_idx: dict[str, int] = {}
    for i, meta in enumerate(metadatas):
        cid = meta.get("chunk_id", "")
        if cid:
            chunk_id_to_idx[cid] = i

    expanded: list[int] = []
    seen_parents: set[str] = set()  # 已添加的 parent chunk_id
    expansion_info: list[tuple[int, int]] = []

    for idx in top_indices:
        if len(expanded) >= context_k:
            break

        meta = metadatas[idx] if idx < len(metadatas) else {}
        chunk_type = meta.get("chunk_type", "")
        parent_chunk_id = meta.get("parent_chunk_id", "")

        if chunk_type == "child" and parent_chunk_id and parent_chunk_id in chunk_id_to_idx:
            # child chunk → 用 parent 替换
            if parent_chunk_id not in seen_parents:
                parent_idx = chunk_id_to_idx[parent_chunk_id]
                expanded.append(parent_idx)
                seen_parents.add(parent_chunk_id)
                expansion_info.append((idx, parent_idx))
            # 同一 parent 的其他 child 不再重复添加
        else:
            # 非 child chunk 或无 parent → 直接添加
            expanded.append(idx)
            expansion_info.append((idx, idx))

    return expanded, expansion_info


def expand_with_adjacent(
    top_indices: list[int],
    metadatas: list[dict],
    max_expand: int = 2,
) -> list[int]:
    """邻接扩展：召回某个 chunk 时，自动包含其前后相邻 chunk。

    策略：
    1. 对每个召回的 chunk，查找同一 source 内 chunk_index 相邻的 chunk
    2. 最多扩展 max_expand 个相邻 chunk（前后各 1 个）
    3. 去重并保持顺序

    Args:
        top_indices: 排序后的 chunk 索引列表
        metadatas: 全量元数据列表
        max_expand: 最大扩展数量

    Returns:
        扩展后的索引列表（去重，保持原顺序优先）
    """
    if max_expand <= 0:
        return list(top_indices)

    # 建立 (source_id, chunk_index) → global_index 的映射
    source_chunk_map: dict[tuple[str, int], int] = {}
    for i, meta in enumerate(metadatas):
        source_id = meta.get("source_id", "")
        chunk_index = meta.get("chunk_index", -1)
        if source_id and chunk_index >= 0:
            source_chunk_map[(source_id, chunk_index)] = i

    # 对每个召回的 chunk，查找相邻 chunk
    expanded_set: set[int] = set()
    expanded_ordered: list[int] = []

    for idx in top_indices:
        if idx not in expanded_set:
            expanded_set.add(idx)
            expanded_ordered.append(idx)

        meta = metadatas[idx] if idx < len(metadatas) else {}
        source_id = meta.get("source_id", "")
        chunk_index = meta.get("chunk_index", -1)

        if not source_id or chunk_index < 0:
            continue

        # 前一个 chunk
        added = 0
        prev_key = (source_id, chunk_index - 1)
        if prev_key in source_chunk_map and added < max_expand:
            prev_idx = source_chunk_map[prev_key]
            if prev_idx not in expanded_set:
                expanded_set.add(prev_idx)
                expanded_ordered.append(prev_idx)
                added += 1

        # 后一个 chunk
        next_key = (source_id, chunk_index + 1)
        if next_key in source_chunk_map and added < max_expand:
            next_idx = source_chunk_map[next_key]
            if next_idx not in expanded_set:
                expanded_set.add(next_idx)
                expanded_ordered.append(next_idx)
                added += 1

    return expanded_ordered


def reconcile_expansion_budget(
    select_indices: list[int] | tuple[int, ...],
    expanded: list[int],
    metadatas: list[dict],
    context_k: int,
) -> tuple[list[int], int]:
    """扩展预算调和：select 召回证据保留槽位（2.2 验收修复策略）。

    扩展的两个挤占源——``expand_with_parent`` 预算 break 丢弃尾部 select
    块、邻接邻居插队把 select 块推出预算窗口——统一在此调和：

    1. 代表块：按 select 顺序收集；每个 select 块由「自身或其在场 parent」
       代表（child 已被 parent 替换时不重复入列，避免内容重复；parent 也
       缺席时 child 自身回插，召回证据不可失）；
    2. 扩展块：expanded 中不属于代表集的（邻接邻居、parent 去重腾出者）
       按扩展顺序殿后；
    3. ``effective_k = max(context_k, len(reps))``——预算放大到恰好容纳
       全部代表块，后续按 k 取前缀的截断只可能裁掉扩展尾部。

    Returns:
        (调和后索引列表, 有效 context_k)
    """
    chunk_id_to_idx: dict[str, int] = {}
    for i, meta in enumerate(metadatas):
        cid = meta.get("chunk_id", "")
        if cid:
            chunk_id_to_idx[cid] = i

    present = set(expanded)
    reps: list[int] = []
    seen: set[int] = set()
    for idx in select_indices:
        meta = metadatas[idx] if idx < len(metadatas) else {}
        if idx in present:
            rep = idx
        else:
            parent_id = meta.get("parent_chunk_id", "")
            parent_idx = chunk_id_to_idx.get(parent_id) if parent_id else None
            if (meta.get("chunk_type") == "child" and parent_id
                    and parent_idx is not None and parent_idx in present):
                rep = parent_idx
            else:
                rep = idx
        if rep not in seen:
            seen.add(rep)
            reps.append(rep)

    expansion_only = [i for i in expanded if i not in seen]
    final = reps + expansion_only
    effective_k = max(context_k, len(reps))
    return final, effective_k


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
            # 2.1 可追溯口径：解析器代次随 chunk 持久化（chroma 可查）
            "parser_version": document.parser_version,
        }
        if chunk.page is not None:
            metadata["page"] = chunk.page
        # Parent-Child 关系
        if chunk.parent_chunk_id is not None:
            metadata["parent_chunk_id"] = chunk.parent_chunk_id
        # chunk_type 标记（parent/child/anchor）
        chunk_type = chunk.metadata.get("chunk_type", "")
        if chunk_type:
            metadata["chunk_type"] = chunk_type
        # 扩展元数据（排除已处理的 chunk_type）
        for key, value in chunk.metadata.items():
            if key != "chunk_type":  # chunk_type 已处理
                metadata[key] = value

        texts.append(chunk.text)
        metadatas.append(metadata)
        ids.append(chunk.chunk_id)

    return texts, metadatas, ids
