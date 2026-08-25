"""
测试 Graph RAG 实体提取使用正确的模型名
"""
import os
import pytest
from unittest.mock import patch, MagicMock, call
import hashlib


class TestEntityExtractionModelSelection:
    """验证 extract_entities_llm_batch 使用正确的 LLM 模型

    统一配置契约（Phase C 返工）：实体提取的模型从已解析 Settings 读取
    （单一默认值来源），测试按契约模式设置：env → reset_settings()。
    """

    def test_uses_default_llm_model_when_no_env(self):
        """无环境变量时使用 Settings 默认模型（= 契约默认 deepseek-chat）。"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "---段落1---\n实体A"
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict(os.environ):
            os.environ.pop("LLM_MODEL", None)
            # 契约模式：env → reset_settings()（重建 Settings + 刷新模块常量）
            from src.config import reset_settings, DEFAULT_LLM_MODEL
            reset_settings()
            import src.rag as rag

            with patch("src.graph_rag._get_llm_client", return_value=mock_client):
                from src.graph_rag import extract_entities_llm_batch, _entity_cache
                # 清除缓存，确保会调用 mock
                _entity_cache.clear()
                extract_entities_llm_batch(["测试文本"])

                # 验证调用时使用了 Settings 默认模型
                call_args = mock_client.chat.completions.create.call_args
                assert call_args.kwargs["model"] == DEFAULT_LLM_MODEL
                assert call_args.kwargs["model"] == rag.DEFAULT_LLM_MODEL

    def test_uses_env_llm_model_when_set(self):
        """设置环境变量 LLM_MODEL 时优先使用"""
        test_model = "gpt-4o-mini"

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "---段落1---\n实体A"
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict(os.environ, {"LLM_MODEL": test_model}):
            from src.config import reset_settings
            reset_settings()
            with patch("src.graph_rag._get_llm_client", return_value=mock_client):
                from src.graph_rag import extract_entities_llm_batch, _entity_cache
                # 清除缓存
                _entity_cache.clear()
                extract_entities_llm_batch(["测试文本"])

                # 验证调用时使用了环境变量中的模型
                call_args = mock_client.chat.completions.create.call_args
                assert call_args.kwargs["model"] == test_model

    def test_model_not_hardcoded_deepseek_chat(self):
        """确保不再硬编码 'deepseek-chat'"""
        # 使用一个不会是默认值的模型名
        test_model = "claude-3-opus"

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "---段落1---\n实体A"
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict(os.environ, {"LLM_MODEL": test_model}):
            from src.config import reset_settings
            reset_settings()
            with patch("src.graph_rag._get_llm_client", return_value=mock_client):
                from src.graph_rag import extract_entities_llm_batch, _entity_cache
                # 清除缓存
                _entity_cache.clear()
                extract_entities_llm_batch(["测试文本"])

                call_args = mock_client.chat.completions.create.call_args
                # 确保不是硬编码的 "deepseek-chat"
                assert call_args.kwargs["model"] != "deepseek-chat"
                assert call_args.kwargs["model"] == test_model