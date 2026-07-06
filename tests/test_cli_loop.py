"""
测试 cli_loop 模块的公共接口。

测试策略：
- mock input() 模拟用户输入序列
- mock print() 验证输出
- mock 索引对象（MagicMock），不涉及真实 ChromaDB
"""

import pytest
from unittest.mock import patch, MagicMock, call
import time


class TestParseAddPaths:
    """测试 _parse_add_paths() 路径解析函数"""

    def test_single_path(self):
        """单个路径解析"""
        # 此函数将在 cli_loop.py 中定义
        from src.cli_loop import _parse_add_paths
        result = _parse_add_paths("+add /path/to/file.pdf")
        assert result == ["/path/to/file.pdf"]

    def test_multiple_paths_with_comma(self):
        """多个路径用半角逗号分隔"""
        from src.cli_loop import _parse_add_paths
        result = _parse_add_paths("+add /path/a.pdf, /path/b.pdf")
        assert result == ["/path/a.pdf", "/path/b.pdf"]

    def test_multiple_paths_with_chinese_comma(self):
        """支持全角逗号分隔"""
        from src.cli_loop import _parse_add_paths
        result = _parse_add_paths("+add /path/a.pdf，/path/b.pdf")
        assert result == ["/path/a.pdf", "/path/b.pdf"]

    def test_mixed_comma_types(self):
        """混合全角和半角逗号"""
        from src.cli_loop import _parse_add_paths
        result = _parse_add_paths("+add /path/a.pdf，/path/b.pdf, /path/c.pdf")
        assert result == ["/path/a.pdf", "/path/b.pdf", "/path/c.pdf"]

    def test_empty_paths(self):
        """空字符串返回空列表"""
        from src.cli_loop import _parse_add_paths
        assert _parse_add_paths("+add") == []
        assert _parse_add_paths("+add   ") == []

    def test_paths_with_extra_spaces(self):
        """路径前后有空格时正确 strip"""
        from src.cli_loop import _parse_add_paths
        result = _parse_add_paths("+add  /path/a.pdf  ,  /path/b.pdf  ")
        assert result == ["/path/a.pdf", "/path/b.pdf"]


class TestPrintElapsed:
    """测试 _print_elapsed() 计时打印格式化"""

    def test_zero_seconds(self):
        """0 秒显示为 0 分 0 秒"""
        from src.cli_loop import _print_elapsed
        with patch("builtins.print") as mock_print:
            _print_elapsed("测试", 0.0, 0.0)
            mock_print.assert_called_once_with("测试（用时0分0秒）")

    def test_one_minute_thirty_seconds(self):
        """1 分 30 秒"""
        from src.cli_loop import _print_elapsed
        with patch("builtins.print") as mock_print:
            _print_elapsed("测试", 0.0, 90.0)
            mock_print.assert_called_once_with("测试（用时1分30秒）")

    def test_ten_minutes_zero_seconds(self):
        """10 分 0 秒"""
        from src.cli_loop import _print_elapsed
        with patch("builtins.print") as mock_print:
            _print_elapsed("测试", 0.0, 600.0)
            mock_print.assert_called_once_with("测试（用时10分0秒）")


class TestRunInteractiveSession:
    """测试 run_interactive_session() 交互式循环"""

    @patch("src.rag.prepare_index")
    @patch("builtins.print")
    @patch("builtins.input", return_value="q")
    def test_quit_immediately(self, mock_input, mock_print, mock_prepare):
        """输入 'q' 正常退出"""
        from src.cli_loop import run_interactive_session

        # Mock prepare_index 返回非空结果
        mock_model = MagicMock()
        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "documents": ["doc1"],
            "metadatas": [{"source": "test.pdf"}]
        }
        mock_prepare.return_value = (mock_model, mock_collection, MagicMock(), ["doc1"], [{"source": "test.pdf"}])

        run_interactive_session(["test.pdf"], "test_coll")
        mock_prepare.assert_called_once()

    @patch("src.rag.add_files_to_index")
    @patch("src.rag.prepare_index")
    @patch("builtins.print")
    @patch("builtins.input", side_effect=["+add /new.pdf", "q"])
    def test_add_files_command(self, mock_input, mock_print, mock_prepare, mock_add):
        """+add 命令正确解析路径并添加"""
        from src.cli_loop import run_interactive_session

        mock_model = MagicMock()
        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "documents": ["doc1"],
            "metadatas": [{"source": "test.pdf"}]
        }
        mock_prepare.return_value = (mock_model, mock_collection, MagicMock(), ["doc1"], [{"source": "test.pdf"}])
        mock_add.return_value = (MagicMock(), ["doc1", "doc2"], [{"source": "test.pdf"}, {"source": "new.pdf"}])

        run_interactive_session(["test.pdf"], "test_coll")
        mock_add.assert_called_once_with(["/new.pdf"], mock_model, mock_collection)

    @patch("src.rag.prepare_index")
    @patch("builtins.print")
    @patch("builtins.input", side_effect=["", "q"])
    def test_empty_input_ignored(self, mock_input, mock_print, mock_prepare):
        """空输入被忽略，继续循环"""
        from src.cli_loop import run_interactive_session

        mock_model = MagicMock()
        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "documents": ["doc1"],
            "metadatas": [{"source": "test.pdf"}]
        }
        mock_prepare.return_value = (mock_model, mock_collection, MagicMock(), ["doc1"], [{"source": "test.pdf"}])

        run_interactive_session(["test.pdf"], "test_coll")
        # input 被调用两次（空输入 + q）
        assert mock_input.call_count == 2

    @patch("src.rag.answer_query")
    @patch("src.rag.prepare_index")
    @patch("builtins.print")
    @patch("builtins.input", side_effect=["测试问题", "q"])
    def test_answer_query_flow(self, mock_input, mock_print, mock_prepare, mock_answer):
        """正常问答流程"""
        from src.cli_loop import run_interactive_session

        mock_model = MagicMock()
        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "documents": ["doc1"],
            "metadatas": [{"source": "test.pdf"}]
        }
        mock_prepare.return_value = (mock_model, mock_collection, MagicMock(), ["doc1"], [{"source": "test.pdf"}])
        mock_answer.return_value = ("这是回答", "[1] test.pdf...")

        run_interactive_session(["test.pdf"], "test_coll")
        mock_answer.assert_called_once()

    @patch("src.rag.prepare_index")
    @patch("builtins.print")
    def test_empty_docs_exit(self, mock_print, mock_prepare):
        """空文档库时 sys.exit(1)"""
        from src.cli_loop import run_interactive_session

        mock_prepare.return_value = (MagicMock(), MagicMock(), MagicMock(), [], [])

        with pytest.raises(SystemExit) as exc_info:
            run_interactive_session(["test.pdf"], "test_coll")
        assert exc_info.value.code == 1

    @patch("src.graph_rag.KnowledgeGraph")
    @patch("src.rag.add_files_to_index")
    @patch("src.graph_rag.prepare_graph_index")
    @patch("builtins.print")
    @patch("builtins.input", side_effect=["+add /new.pdf", "q"])
    def test_graph_rag_add_rebuilds_kg(self, mock_input, mock_print, mock_prepare_graph, mock_add, mock_kg_class):
        """Graph RAG 模式下 +add 后重建 KG"""
        from src.cli_loop import run_interactive_session

        mock_model = MagicMock()
        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "documents": ["doc1"],
            "metadatas": [{"source": "test.pdf"}]
        }
        mock_kg = MagicMock()
        mock_prepare_graph.return_value = (mock_model, mock_collection, MagicMock(), ["doc1"], [{"source": "test.pdf"}], mock_kg)
        mock_add.return_value = (MagicMock(), ["doc1", "doc2"], [{"source": "test.pdf"}, {"source": "new.pdf"}])

        new_kg = MagicMock()
        mock_kg_class.return_value = new_kg

        run_interactive_session(["test.pdf"], "test_coll", is_graph_rag=True)
        mock_kg_class.assert_called_once()
        new_kg.build_from_chunks.assert_called_once()


class TestRunSingleQuery:
    """测试 run_single_query() 单次查询"""

    def test_rag_mode(self):
        """标准 RAG 模式调用 answer_query"""
        from src.cli_loop import run_single_query

        mock_model = MagicMock()
        mock_collection = MagicMock()
        mock_bm25 = MagicMock()
        mock_docs = ["doc1"]
        mock_metas = [{"source": "test.pdf"}]

        with patch("src.rag.answer_query", return_value=("回答", "来源")) as mock_answer:
            result = run_single_query(
                "测试问题",
                model=mock_model,
                collection=mock_collection,
                bm25=mock_bm25,
                all_docs=mock_docs,
                all_metadatas=mock_metas,
                is_graph_rag=False,
            )
            assert result == ("回答", "来源")
            mock_answer.assert_called_once()

    def test_graph_rag_mode(self):
        """Graph RAG 模式调用 _graph_rag_answer"""
        from src.cli_loop import run_single_query

        mock_model = MagicMock()
        mock_collection = MagicMock()
        mock_bm25 = MagicMock()
        mock_docs = ["doc1"]
        mock_metas = [{"source": "test.pdf"}]
        mock_kg = MagicMock()

        with patch("src.cli_loop._graph_rag_answer", return_value=("回答", "来源")) as mock_graph_answer:
            result = run_single_query(
                "测试问题",
                model=mock_model,
                collection=mock_collection,
                bm25=mock_bm25,
                all_docs=mock_docs,
                all_metadatas=mock_metas,
                is_graph_rag=True,
                alpha=0.8,
                kg=mock_kg,
            )
            assert result == ("回答", "来源")
            mock_graph_answer.assert_called_once()
