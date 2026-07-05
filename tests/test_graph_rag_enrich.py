"""
测试 graph_rag.py 中 enrich_context 集成。

TDD: Red → Green → Refactor

Mock 策略注解：
- 所有涉及 main() 的测试都需要 mock prepare_graph_index（否则会真正初始化 ChromaDB）
- main() 中 exit(0)/exit(1) 是 Python 内建函数，需 patch("builtins.exit")
- input() 是 Python 内建函数，需 patch("builtins.input")
- time.time() 必须设 return_value，否则 MagicMock - MagicMock 导致 int() TypeError
- 涉及 print 的测试可 patch("builtins.print") 减少输出噪音
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.graph_rag import (
    graph_query_stream,
    graph_rag_pipeline,
    main,
)


def test_graph_query_stream_calls_enrich_context():
    """graph_query_stream 调用 enrich_context 并将 enrich 后的 docs 传递下去"""
    all_docs = ["short anchor", "body text 1", "body text 2"]
    all_metas = [
        {"source": "a.pdf", "chunk_type": "anchor", "source_path": "/fake/a.pdf"},
        {"source": "a.pdf", "chunk_type": "body"},
        {"source": "a.pdf", "chunk_type": "body"},
    ]
    enriched_expected = ["full first page text...", "body text 1", "body text 2"]

    with (
        patch("src.graph_rag.graph_augmented_retrieve") as mock_retrieve,
        patch("src.graph_rag.dynamic_top_k") as mock_top_k,
        patch("src.graph_rag.enrich_context") as mock_enrich,
        patch("src.graph_rag._build_context") as mock_build,
        patch("src.graph_rag.format_sources") as mock_sources,
        patch("src.graph_rag.answer_with_llm_history_stream") as mock_stream,
    ):
        mock_retrieve.return_value = ([0, 1, 2], all_docs, [0.9, 0.8, 0.7])
        mock_top_k.return_value = 3
        mock_enrich.return_value = enriched_expected
        mock_stream.return_value = iter(["t1", "t2"])

        stream, sources = graph_query_stream(
            "test query", None, None, None,
            all_docs, all_metas, None,
        )

        # enrich_context 应被调用
        mock_enrich.assert_called_once_with([0, 1, 2], all_docs, all_metas)

        # _build_context 应收到 enriched_docs
        mock_build.assert_called_once_with([0, 1, 2], enriched_expected, all_metas)

        # format_sources 应收到 enriched_docs
        mock_sources.assert_called_once_with([0, 1, 2], enriched_expected, all_metas)


def test_graph_rag_pipeline_calls_enrich_context():
    """graph_rag_pipeline 调用 enrich_context 并传递 enrich 后的 docs"""
    all_docs = ["short anchor", "body text"]
    all_metas = [
        {"source": "a.pdf", "chunk_type": "anchor", "source_path": "/fake/a.pdf"},
        {"source": "a.pdf", "chunk_type": "body"},
    ]
    enriched_expected = ["full first page...", "body text"]

    with (
        patch("src.graph_rag.graph_augmented_retrieve") as mock_retrieve,
        patch("src.graph_rag.dynamic_top_k") as mock_top_k,
        patch("src.graph_rag.enrich_context") as mock_enrich,
        patch("src.graph_rag._build_context") as mock_build,
        patch("src.graph_rag.format_sources") as mock_sources,
        patch("src.graph_rag.answer_with_llm_history") as mock_answer,
        patch("src.graph_rag.prepare_graph_index") as mock_prepare,
        patch("time.time", return_value=0.0),   # 必须设返回值，否则 MagicMock 差值导致 int() TypeError
        patch("builtins.print"),                 # 消除函数内大量 print 对测试输出的噪音
    ):
        mock_retrieve.return_value = ([0, 1], all_docs, [0.9, 0.8])
        mock_top_k.return_value = 2
        mock_enrich.return_value = enriched_expected
        mock_answer.return_value = "mock answer"
        mock_prepare.return_value = (None, None, None, all_docs, all_metas, None)

        result = graph_rag_pipeline(
            ["/fake/test.pdf"], "test query",
        )

        # enrich_context 应被调用
        mock_enrich.assert_called_once_with([0, 1], all_docs, all_metas)

        # _build_context 应收到 enriched_docs
        mock_build.assert_called_once_with([0, 1], enriched_expected, all_metas)

        # format_sources 应收到 enriched_docs
        mock_sources.assert_called_once_with([0, 1], enriched_expected, all_metas)


def test_interactive_loop_calls_enrich_context():
    """main() 交互式循环调用 enrich_context"""
    all_docs = ["short anchor", "body text"]
    all_metas = [
        {"source": "a.pdf", "chunk_type": "anchor", "source_path": "/fake/a.pdf"},
        {"source": "a.pdf", "chunk_type": "body"},
    ]
    enriched_expected = ["full first page...", "body text"]

    with (
        patch("src.graph_rag.graph_augmented_retrieve") as mock_retrieve,
        patch("src.graph_rag.dynamic_top_k") as mock_top_k,
        patch("src.graph_rag.enrich_context") as mock_enrich,
        patch("src.graph_rag._build_context") as mock_build,
        patch("src.graph_rag.format_sources") as mock_sources,
        patch("src.graph_rag.answer_with_llm_history") as mock_answer,
        patch("src.graph_rag.prepare_graph_index") as mock_prepare,
        patch("builtins.input") as mock_input,   # input 是内建函数，graph_rag.py 无模块级引用
        patch("time.time", return_value=0.0),    # 必须设返回值，否则 int() TypeError
        patch("builtins.print"),                 # 消除 main() 内 print 噪音
        patch("sys.argv", [
            "graph_rag.py",
            "--files", "/fake/test.pdf",         # 绕过 ask_for_files，直接给文件
        ]),
    ):
        mock_retrieve.return_value = ([0, 1], all_docs, [0.9, 0.8])
        mock_top_k.return_value = 2
        mock_enrich.return_value = enriched_expected
        mock_answer.return_value = "mock answer"
        mock_prepare.return_value = (None, None, None, all_docs, all_metas, None)
        # 先发一个查询，再退出
        mock_input.side_effect = ["test query", "q"]

        main()

        # enrich_context 应被调用一次（查询时）
        mock_enrich.assert_called_once_with([0, 1], all_docs, all_metas)

        # _build_context 应收到 enriched_docs
        mock_build.assert_called_once_with([0, 1], enriched_expected, all_metas)

        # format_sources 应收到 enriched_docs
        mock_sources.assert_called_once_with([0, 1], enriched_expected, all_metas)


def test_cli_query_calls_enrich_context():
    """main() 中 --query 参数路径调用 enrich_context"""
    all_docs = ["short anchor", "body text"]
    all_metas = [
        {"source": "a.pdf", "chunk_type": "anchor", "source_path": "/fake/a.pdf"},
        {"source": "a.pdf", "chunk_type": "body"},
    ]
    enriched_expected = ["full first page...", "body text"]

    with (
        patch("src.graph_rag.graph_augmented_retrieve") as mock_retrieve,
        patch("src.graph_rag.dynamic_top_k") as mock_top_k,
        patch("src.graph_rag.enrich_context") as mock_enrich,
        patch("src.graph_rag._build_context") as mock_build,
        patch("src.graph_rag.format_sources") as mock_sources,
        patch("src.graph_rag.answer_with_llm_history") as mock_answer,
        patch("src.graph_rag.prepare_graph_index") as mock_prepare,
        patch("builtins.exit") as mock_exit,     # main() 用内建 exit() 结束，非 sys.exit
        patch("time.time", return_value=0.0),    # 必须设返回值，否则 int() TypeError
        patch("builtins.print"),                 # 消除 main() 内 print 噪音
        patch("sys.argv", [
            "graph_rag.py",
            "--files", "/fake/test.pdf",         # 必须提供 --files，否则走 ask_for_files → exit(1)
            "--query", "test query",
        ]),
    ):
        mock_retrieve.return_value = ([0, 1], all_docs, [0.9, 0.8])
        mock_top_k.return_value = 2
        mock_enrich.return_value = enriched_expected
        mock_answer.return_value = "mock answer"
        mock_prepare.return_value = (None, None, None, all_docs, all_metas, None)
        # exit(0) 被 mock 接管，不真正退出进程
        mock_exit.side_effect = SystemExit(0)

        try:
            main()
        except SystemExit:
            pass

        # enrich_context 应被调用
        mock_enrich.assert_called_once_with([0, 1], all_docs, all_metas)

        # _build_context 应收到 enriched_docs
        mock_build.assert_called_once_with([0, 1], enriched_expected, all_metas)

        # format_sources 应收到 enriched_docs
        mock_sources.assert_called_once_with([0, 1], enriched_expected, all_metas)
