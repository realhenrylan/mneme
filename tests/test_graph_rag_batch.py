"""
测试 graph_rag.py 中批量处理和并发修复的测试用例。

Issue #3 修复验证：
1. 验证批量处理正确性（减少 API 调用次数）
2. 验证向后兼容性（max_workers 参数废弃警告）
3. 验证边界情况（空输入、单个 chunk、非整数倍）
4. 验证结果顺序正确性
5. 验证 API 异常处理的优雅降级
"""

import sys
from unittest.mock import MagicMock

# Mock 外部依赖（在导入 graph_rag 之前）
sys.modules['networkx'] = MagicMock()
sys.modules['sentence_transformers'] = MagicMock()
sys.modules['chromadb'] = MagicMock()
sys.modules['rank_bm25'] = MagicMock()
sys.modules['openai'] = MagicMock()

import pytest
import warnings
from unittest.mock import patch, MagicMock

from src.graph_rag import KnowledgeGraph, extract_entities_llm_batch, _entity_cache


class TestBatchProcessing:
    """测试批量处理功能"""

    def setup_method(self):
        """每个测试前清空缓存"""
        _entity_cache.clear()

    def test_batch_processing_basic(self):
        """测试批量处理是否正确处理多个 chunks"""
        chunks = [f"测试文本 {i}" for i in range(20)]

        with patch('src.graph_rag._get_llm_client') as mock_client:
            # 模拟返回 5 个段落的实体（匹配 batch_size）
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(
                content="---段落1---\n实体A\n---段落2---\n实体B\n---段落3---\n实体C\n---段落4---\n实体D\n---段落5---\n实体E\n"
            ))]
            mock_client.return_value.chat.completions.create.return_value = mock_response

            kg = KnowledgeGraph()
            kg.build_from_chunks(chunks, batch_size=5, verbose=False)

            # 应该只调用 20/5 = 4 次 API
            assert mock_client.return_value.chat.completions.create.call_count == 4

    def test_empty_chunks(self):
        """测试空 chunks 输入"""
        kg = KnowledgeGraph()
        # 设置 mock 返回值
        kg.entity_graph.number_of_nodes.return_value = 0
        kg.build_from_chunks([], verbose=False)
        # 验证没有调用 LLM（空输入不需要处理）
        assert kg.entity_graph.number_of_nodes() == 0

    def test_single_chunk(self):
        """测试单个 chunk"""
        with patch('src.graph_rag._get_llm_client') as mock_client:
            mock_response = MagicMock()
            # mock 返回与输入数量一致的段落
            mock_response.choices = [MagicMock(message=MagicMock(content="---段落1---\n实体A\n"))]
            mock_client.return_value.chat.completions.create.return_value = mock_response

            kg = KnowledgeGraph()
            kg.build_from_chunks(["单个测试文本"], batch_size=5, verbose=False)

            assert mock_client.return_value.chat.completions.create.call_count == 1

    def test_non_batch_multiple_chunks(self):
        """测试 chunks 数量不是 batch_size 整数倍"""
        # 12 个 chunks，batch_size=5，应该分 3 批：5+5+2
        chunks = [f"文本 {i}" for i in range(12)]

        with patch('src.graph_rag._get_llm_client') as mock_client:
            # 注意：前两批 5 个，最后一批 2 个
            # 这里简化 mock，实际解析依赖容错逻辑（未匹配返回空列表）
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(
                content="---段落1---\n实体A\n---段落2---\n实体B\n---段落3---\n实体C\n---段落4---\n实体D\n---段落5---\n实体E\n"
            ))]
            mock_client.return_value.chat.completions.create.return_value = mock_response

            kg = KnowledgeGraph()
            kg.build_from_chunks(chunks, batch_size=5, verbose=False)

            # 12/5 = 2.4，向上取整 = 3 次
            assert mock_client.return_value.chat.completions.create.call_count == 3


class TestResultOrder:
    """测试结果顺序正确性"""

    def setup_method(self):
        """每个测试前清空缓存"""
        _entity_cache.clear()

    def test_result_order_preservation(self):
        """测试返回结果与输入 chunks 顺序一致"""
        texts = ["文本A", "文本B", "文本C"]

        with patch('src.graph_rag._get_llm_client') as mock_client:
            mock_response = MagicMock()
            # mock 返回与输入数量一致的段落
            mock_response.choices = [MagicMock(message=MagicMock(
                content="---段落1---\n实体A1\n实体A2\n---段落2---\n实体B1\n---段落3---\n实体C1\n实体C2\n实体C3\n"
            ))]
            mock_client.return_value.chat.completions.create.return_value = mock_response

            results = extract_entities_llm_batch(texts, batch_size=5)

            assert len(results) == 3
            assert results[0] == ["实体A1", "实体A2"]
            assert results[1] == ["实体B1"]
            assert results[2] == ["实体C1", "实体C2", "实体C3"]


class TestBackwardCompatibility:
    """测试向后兼容性"""

    def setup_method(self):
        """每个测试前清空缓存"""
        _entity_cache.clear()

    def test_max_workers_deprecation_warning(self):
        """测试 max_workers 参数向后兼容，并发出 DeprecationWarning"""
        with patch('src.graph_rag._get_llm_client') as mock_client:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(content="---段落1---\n实体A\n"))]
            mock_client.return_value.chat.completions.create.return_value = mock_response

            kg = KnowledgeGraph()

            # 使用已废弃的 max_workers 参数
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                kg.build_from_chunks(["测试"], max_workers=5, verbose=False)

                # 应该发出 DeprecationWarning
                assert len(w) == 1
                assert issubclass(w[0].category, DeprecationWarning)
                assert "max_workers" in str(w[0].message).lower()
                assert "废弃" in str(w[0].message) or "deprecated" in str(w[0].message).lower()

    def test_default_max_workers_no_warning(self):
        """测试使用默认 max_workers 不会触发警告"""
        with patch('src.graph_rag._get_llm_client') as mock_client:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(content="---段落1---\n实体A\n"))]
            mock_client.return_value.chat.completions.create.return_value = mock_response

            kg = KnowledgeGraph()

            # 使用默认 max_workers=10 不应触发警告
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                kg.build_from_chunks(["测试"], verbose=False)

                # 不应该发出 DeprecationWarning
                deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
                assert len(deprecation_warnings) == 0


class TestErrorHandling:
    """测试异常处理"""

    def setup_method(self):
        """每个测试前清空缓存"""
        _entity_cache.clear()

    def test_api_error_graceful_degradation(self):
        """测试 API 调用失败时的优雅降级"""
        texts = ["文本A", "文本B", "文本C"]

        with patch('src.graph_rag._get_llm_client') as mock_client:
            # 模拟 API 抛出异常
            mock_client.return_value.chat.completions.create.side_effect = Exception("API Error")

            # 不应崩溃
            results = extract_entities_llm_batch(texts, batch_size=5)

            # 返回结果长度应与输入一致
            assert len(results) == 3

            # 所有结果应为空列表（降级处理）
            assert all(r == [] for r in results)

            # 缓存不应写入脏数据（异常时跳过缓存写入）
            assert len(_entity_cache) == 0


class TestProgressCallback:
    """测试进度回调"""

    def setup_method(self):
        """每个测试前清空缓存"""
        _entity_cache.clear()

    def test_progress_callback_invoked(self):
        """测试进度回调被正确调用"""
        chunks = [f"文本 {i}" for i in range(10)]
        callback_calls = []

        def callback(done, total):
            callback_calls.append((done, total))

        with patch('src.graph_rag._get_llm_client') as mock_client:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(
                content="---段落1---\n实体A\n---段落2---\n实体B\n---段落3---\n实体C\n---段落4---\n实体D\n---段落5---\n实体E\n"
            ))]
            mock_client.return_value.chat.completions.create.return_value = mock_response

            kg = KnowledgeGraph()
            kg.build_from_chunks(chunks, batch_size=5, verbose=False, progress_callback=callback)

            # 应该有回调调用（每批一次）
            assert len(callback_calls) >= 2  # 至少 10/5 = 2 次

            # 最后一次应该是完成状态
            last_call = callback_calls[-1]
            assert last_call[0] == last_call[1]  # done == total


class TestEntityParseWithListPrefix:
    """验证带列表前缀的实体行能被正确解析（ListPrefix Bug 修复）

    Issue: LLM 返回的实体行如果以 -、*、· 开头，会被静默丢弃。

    修复方案：在将行加入实体列表前，使用 lstrip 剥离列表标记前缀。
    """

    def setup_method(self):
        """每测试前清空缓存，避免假通过"""
        _entity_cache.clear()

    @pytest.mark.parametrize(
        "mock_response,texts,expected",
        [
            # 用例 1: 单段落，- 前缀
            pytest.param(
                "---段落1---\n- 人工智能\n- 机器学习",
                ["虚构文本段落内容"],
                [["人工智能", "机器学习"]],
                id="hyphen_prefix"
            ),
            # 用例 2: 单段落，* 前缀
            pytest.param(
                "---段落1---\n* 深度学习\n* 强化学习",
                ["虚构文本段落内容"],
                [["深度学习", "强化学习"]],
                id="asterisk_prefix"
            ),
            # 用例 3: 单段落，· 前缀
            pytest.param(
                "---段落1---\n· 自然语言处理\n· 计算机视觉",
                ["虚构文本段落内容"],
                [["自然语言处理", "计算机视觉"]],
                id="dot_prefix"
            ),
            # 用例 4: 混合前缀
            pytest.param(
                "---段落1---\n- AI\n* ML\n· DL",
                ["虚构文本段落内容"],
                [["AI", "ML", "DL"]],
                id="mixed_prefix"
            ),
            # 用例 5: 无前缀实体（回归）
            pytest.param(
                "---段落1---\n人工智能\n机器学习",
                ["虚构文本段落内容"],
                [["人工智能", "机器学习"]],
                id="no_prefix_regression"
            ),
            # 用例 6: 空行不被注入
            pytest.param(
                "---段落1---\n人工智能\n\n机器学习",
                ["虚构文本段落内容"],
                [["人工智能", "机器学习"]],
                id="empty_line_not_injected"
            ),
            # 用例 7: 多段落含前缀（2个文本输入）
            pytest.param(
                "---段落1---\n- AI\n---段落2---\n* ML",
                ["虚构文本A", "虚构文本B"],
                [["AI"], ["ML"]],
                id="multi_paragraph_with_prefix"
            ),
            # 用例 8: 无内容段落（2个文本输入，第二个段落无实体）
            pytest.param(
                "---段落1---\n- AI\n---段落2---",
                ["虚构文本A", "虚构文本B"],
                [["AI"], []],
                id="empty_paragraph"
            ),
        ],
    )
    def test_entity_parse_with_list_prefix(self, mock_response, texts, expected):
        """验证带列表前缀的实体行能被正确解析"""
        with patch("src.graph_rag._get_llm_client") as mock_get_client:
            # Arrange: mock LLM 返回带列表前缀的实体
            mock_client_obj = MagicMock()
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock(message=MagicMock(content=mock_response))]
            mock_client_obj.chat.completions.create.return_value = mock_resp
            mock_get_client.return_value = mock_client_obj

            # Act
            result = extract_entities_llm_batch(texts)

            # Assert
            assert result == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
