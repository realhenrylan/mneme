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

import re
import time
import sys
import os

# ── 辅助函数 ──

_TRACE_ID_RE = re.compile(r"[0-9a-f]{32}")


def _handle_trace_command(query: str) -> bool:
    """处理 ``delete-trace <id>`` 命令；非该命令返回 False 交回问答流程。

    仅接受完整 32 位十六进制 trace ID（trace ID 只由 ``uuid4().hex``
    产生）：模糊/前缀/通配删除可能误删「删除后不可重建的本地诊断」，
    故一律拒绝并提示，不执行任何删除。
    """
    stripped = query.strip()
    if not (stripped == "delete-trace" or stripped.startswith("delete-trace ")):
        return False
    argument = stripped[len("delete-trace"):].strip()
    if not _TRACE_ID_RE.fullmatch(argument):
        print("delete-trace 需要完整的 32 位十六进制 trace ID（拒绝模糊/前缀删除）")
        return True
    from src.production_observability import TraceStore
    store = TraceStore.from_environment()
    store.delete_trace(argument)
    print(f"已删除 trace {argument}")
    return True

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
    alpha: float | None = None,
    *,
    _citation_status_sink: list | None = None,
) -> tuple[str, str]:
    """Graph RAG 回答生成（封装 6 步 pipeline）。

    此函数被 run_interactive_session 和 run_single_query 共用，
    封装了 Graph RAG 的完整回答生成流程。

    引用终态（Product P0.2）：传 ``_citation_status_sink``（keyword-only
    列表）时，按实际进入 prompt 的 context / 实际展示的 sources 计算
    合法 ID 并把 ``CitationStatus`` 追加（与 graph streaming 同口径）；
    不传时行为与旧调用方一致。返回 (answer, sources) 不变，回答文本
    绝不被改写。
    """
    from src.graph_rag import graph_augmented_retrieve
    from src.rag import (
        dynamic_top_k,
        enrich_context,
        _build_context,
        format_sources,
        answer_with_llm_history,
        evaluate_answer_status,
    )
    from src.domain import RetrievalCandidate, compute_context_k

    # 统一配置契约：未显式传入时从当前 Settings 解析（调用期，不冻结导入期值）
    from src.config import (
        get_settings,
        validate_alpha,
        GRAPH_DYNAMIC_MIN_K,
        GRAPH_DYNAMIC_MAX_K,
    )
    _graph_settings = get_settings()
    if alpha is None:
        alpha = _graph_settings.alpha
    # fail-fast：显式 alpha 覆盖值在进入检索/LLM 之前必须通过统一校验
    # （与 Settings 同一规则；错误信息含 ALPHA；alpha=2.0 曾进入
    # graph_augmented_retrieve）。
    alpha = validate_alpha(alpha)

    # 1. Graph 增强检索
    indices, fused_docs, fused_scores = graph_augmented_retrieve(
        query, model, collection, bm25, all_docs, kg, alpha=alpha,
    )

    # 2. 动态 Top-K：Graph 内部策略的既有固定 3/50（GRAPH_DYNAMIC_MIN_K/
    #    MAX_K），与用户 Top-K 区间（LLM_TOP_K_MIN/MAX，默认 3–20）不绑定。
    k = dynamic_top_k(
        fused_scores,
        min_k=GRAPH_DYNAMIC_MIN_K,
        max_k=GRAPH_DYNAMIC_MAX_K,
    )
    top_indices = indices[:k]

    # 3. 上下文增强（PDF anchor chunk 替换）
    enriched_docs = enrich_context(top_indices, all_docs, all_metadatas)

    # 4. 构建 context
    context_k = compute_context_k(
        [RetrievalCandidate(index=i, chunk_id="", source_id="", source_name="")
         for i in top_indices],
    )
    context = _build_context(top_indices, enriched_docs, all_metadatas, context_k=context_k)

    # 5. LLM 生成回答（temperature 来自统一配置契约）
    answer = answer_with_llm_history(
        query, context, history=history,
        temperature=_graph_settings.llm_temperature,
    )

    # 6. 格式化来源
    sources = format_sources(top_indices, enriched_docs, all_metadatas, context_k=context_k)

    # 7. 引用终态（与 graph streaming 同口径；sources 用同一 indices/context_k）
    if _citation_status_sink is not None:
        from src.citations import valid_citation_ids_for_context
        valid_ids = valid_citation_ids_for_context(
            top_indices, enriched_docs, all_metadatas, context_k,
        )
        _citation_status_sink.append(evaluate_answer_status(answer, valid_ids))

    return answer, sources


# ── 公共接口 ──

def run_single_query(
    query: str,
    *,    # Keyword-only: 索引准备好的对象
    model, collection, bm25, all_docs, all_metadatas,
    is_graph_rag: bool = False,
    alpha: float | None = None,
    kg=None,
    _citation_status_sink: list | None = None,
) -> tuple[str, str]:
    """单次查询，返回 (answer, sources)。供应给 --query 路径。

    引用终态（Product P0.2）：传 ``_citation_status_sink`` 时把标准
    answer_query / Graph _graph_rag_answer 的 CitationStatus 转发给
    调用方（如 CLI main 显示状态行）；不传时行为与旧调用方一致。
    """
    sink: list = []
    if is_graph_rag:
        result = _graph_rag_answer(
            query, model, collection, bm25,
            all_docs, all_metadatas, kg=kg, history=[], alpha=alpha,
            _citation_status_sink=sink,
        )
    else:
        from src.rag import answer_query
        result = answer_query(
            query, model, collection, bm25,
            documents=all_docs, metadatas=all_metadatas, history=[],
            _citation_status_sink=sink,
        )
    if _citation_status_sink is not None:
        _citation_status_sink.append(sink[0] if sink else None)
    return result


def run_interactive_session(
    file_paths: list[str],
    collection_name: str,
    *,
    force_rebuild: bool = False,
    alpha: float | None = None,
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
        # ── delete-trace 命令（P1.1-M）：仅精确 32 位 hex ID ──
        if _handle_trace_command(query):
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
                from src.rag import index_fingerprint, CHROMA_DB_PATH, load_index_manifest
                kg = KnowledgeGraph()
                ids = [
                    metadata.get("chunk_id", str(index))
                    for index, metadata in enumerate(all_metadatas)
                ]
                kg.build_from_chunks(all_docs, chunk_ids=ids, verbose=True)
                collection_data = collection.get()
                persisted_ids = collection_data.get("ids") or ids
                kg.save(
                    os.path.join(CHROMA_DB_PATH, f"{collection_name}_kg.json"),
                    index_fingerprint(persisted_ids, all_metadatas),
                    (load_index_manifest(collection_name) or {}).get("manifest_version"),
                )
                extra_state = kg
            print(f"已新增索引，当前共 {len(all_docs)} 个文档块")
            continue

        # ── 回答生成 ──
        tq0 = time.time()
        status_sink: list = []
        if is_graph_rag:
            answer, sources = _graph_rag_answer(
                query, model, collection, bm25,
                all_docs, all_metadatas, kg=extra_state,
                history=history, alpha=alpha,
                _citation_status_sink=status_sink,
            )
        else:
            from src.rag import answer_query
            answer, sources = answer_query(
                query, model, collection, bm25,
                documents=all_docs, metadatas=all_metadatas, history=history,
                _citation_status_sink=status_sink,
            )
        tq1 = time.time()

        _print_elapsed(f"\n{answer}", tq0, tq1)
        print(f"\n参考来源：\n{sources}\n")
        # ── 引用终态（Product P0.2）：独立于回答/来源显示，不进 history ──
        if status_sink:
            from src.citations import format_citation_status_line
            status_line = format_citation_status_line(status_sink[0])
            if status_line:
                print(status_line)
        print("=" * 100)
        history.append((query, answer))
