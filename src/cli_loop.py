"""
CLI 交互循环模块
=================

将 rag.py 和 graph_rag.py 的 CLI 循环代码提取为公共模块，
遵循 DRY 原则，消除代码重复。

公共接口：
- run_interactive_session(): 交互式问答循环
- run_single_query(): 单次查询（供 --query 路径使用）

内部辅助函数：
- _print_elapsed(): 统一计时打印格式
- _parse_add_paths(): 解析 +add 命令中的文件路径
- _graph_rag_answer(): Graph RAG 回答生成（封装 6 步 pipeline）
"""

from __future__ import annotations

import time
import sys

# ── 辅助函数 ──

def _print_elapsed(label: str, t0: float, t1: float) -> None:
    """统一计时打印格式。

    Args:
        label: 打印标签（如"文档库就绪"、"回答"）
        t0: 开始时间戳（秒）
        t1: 结束时间戳（秒）
    """
    elapsed = t1 - t0
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    print(f"{label}（用时{minutes}分{seconds}秒）")


def _parse_add_paths(query: str) -> list[str]:
    """解析 +add 命令中的文件路径列表，兼容全角逗号。

    Args:
        query: 用户输入的命令（以 "+add" 开头）

    Returns:
        文件路径列表，已去除前后空格和空路径
    """
    raw_paths = query[4:].strip()
    if not raw_paths:
        return []
    # 支持全角逗号（中文输入法）和半角逗号
    return [p.strip() for p in raw_paths.replace("，", ",").split(",") if p.strip()]


def _graph_rag_answer(
    query: str,
    model,
    collection,
    bm25,
    all_docs: list[str],
    all_metadatas: list[dict],
    kg,
    history: list[tuple[str, str]],
    alpha: float = 0.7,
) -> tuple[str, str]:
    """Graph RAG 回答生成（封装 6 步 pipeline）。

    此函数被 run_interactive_session 和 run_single_query 共用，
    封装了 Graph RAG 的完整回答生成流程。

    Args:
        query: 用户问题
        model: SentenceTransformer 模型
        collection: ChromaDB collection
        bm25: BM25 索引
        all_docs: 全量文档列表
        all_metadatas: 全量元数据列表
        kg: KnowledgeGraph 实例
        history: 问答历史
        alpha: 融合权重（语义检索 vs 图谱检索）

    Returns:
        (answer, sources): 回答文本和格式化的来源信息
    """
    from src.graph_rag import graph_augmented_retrieve
    from src.rag import (
        dynamic_top_k,
        enrich_context,
        _build_context,
        format_sources,
        answer_with_llm_history,
    )

    # 1. Graph 增强检索
    indices, fused_docs, fused_scores = graph_augmented_retrieve(
        query, model, collection, bm25, all_docs, kg, alpha=alpha,
    )

    # 2. 动态 Top-K
    k = dynamic_top_k(fused_scores, min_k=3, max_k=50)
    top_indices = indices[:k]

    # 3. 上下文增强（PDF anchor chunk 替换）
    enriched_docs = enrich_context(top_indices, all_docs, all_metadatas)

    # 4. 构建 context
    context = _build_context(top_indices, enriched_docs, all_metadatas)

    # 5. LLM 生成回答
    answer = answer_with_llm_history(query, context, history=history, temperature=0.1)

    # 6. 格式化来源
    sources = format_sources(top_indices, enriched_docs, all_metadatas)

    return answer, sources


# ── 公共接口 ──

def run_single_query(
    query: str,
    *,    # Keyword-only: 索引准备好的对象
    model, collection, bm25, all_docs, all_metadatas,
    is_graph_rag: bool = False,
    alpha: float = 0.7,
    kg=None,
) -> tuple[str, str]:
    """单次查询，返回 (answer, sources)。供应给 --query 路径。

    Args:
        query: 用户问题
        model: SentenceTransformer 模型
        collection: ChromaDB collection
        bm25: BM25 索引
        all_docs: 全量文档列表
        all_metadatas: 全量元数据列表
        is_graph_rag: 是否启用 Graph RAG 模式
        alpha: Graph RAG 融合权重
        kg: KnowledgeGraph 实例（仅 Graph RAG 模式需要）

    Returns:
        (answer, sources): 回答文本和格式化的来源信息
    """
    if is_graph_rag:
        return _graph_rag_answer(
            query, model, collection, bm25,
            all_docs, all_metadatas, kg=kg, history=[], alpha=alpha,
        )
    else:
        from src.rag import answer_query
        return answer_query(
            query, model, collection, bm25,
            documents=all_docs, metadatas=all_metadatas, history=[],
        )


def run_interactive_session(
    file_paths: list[str],
    collection_name: str,
    *,
    force_rebuild: bool = False,
    alpha: float = 0.7,
    is_graph_rag: bool = False,
) -> None:
    """统一的交互式 CLI 会话入口。

    Args:
        file_paths: 初始文件路径列表
        collection_name: ChromaDB collection 名称
        force_rebuild: 是否强制重建索引
        alpha: Graph RAG 融合权重（仅 graph_rag 模式有效）
        is_graph_rag: 是否启用 Graph RAG 模式
    """
    t0 = time.time()

    if is_graph_rag:
        from src.graph_rag import prepare_graph_index, KnowledgeGraph
        model, collection, bm25, all_docs, all_metadatas, kg = prepare_graph_index(
            file_paths, collection_name, force_rebuild,
        )
        extra_state = kg
    else:
        from src.rag import prepare_index
        model, collection, bm25, all_docs, all_metadatas = prepare_index(
            file_paths, collection_name, force_rebuild,
        )
        extra_state = None

    if not all_docs:
        print("文档库为空")
        sys.exit(1)

    t1 = time.time()
    _print_elapsed("文档库就绪", t0, t1)
    print("-" * 100)

    history: list[tuple[str, str]] = []
    while True:
        query = input("请输入问题（q以退出，+add以添加文件）：")
        if query.lower() in ("q", "quit"):
            break
        if not query:
            continue

        # ── +add 命令 ──
        if query.startswith("+add"):
            paths = _parse_add_paths(query)
            if not paths:
                print("用法: +add <文件路径1>[, <文件路径2>]")
                continue
            from src.rag import add_files_to_index
            bm25, all_docs, all_metadatas = add_files_to_index(paths, model, collection)
            if is_graph_rag:
                # Graph RAG 特有：重建 KG
                from src.graph_rag import KnowledgeGraph
                kg = KnowledgeGraph()
                kg.build_from_chunks(all_docs, verbose=True)
                extra_state = kg
            print(f"已新增索引，当前共 {len(all_docs)} 个文档块")
            continue

        # ── 回答生成 ──
        tq0 = time.time()
        if is_graph_rag:
            answer, sources = _graph_rag_answer(
                query, model, collection, bm25,
                all_docs, all_metadatas, kg=extra_state,
                history=history, alpha=alpha,
            )
        else:
            from src.rag import answer_query
            answer, sources = answer_query(
                query, model, collection, bm25,
                documents=all_docs, metadatas=all_metadatas, history=history,
            )
        tq1 = time.time()

        _print_elapsed(f"\n{answer}", tq0, tq1)
        print(f"\n参考来源：\n{sources}\n")
        print("=" * 100)
        history.append((query, answer))