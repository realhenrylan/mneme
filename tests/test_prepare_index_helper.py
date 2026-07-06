"""
测试 _ensure_client_and_check_rebuild() 辅助函数。

此函数在 prepare_index 和 prepare_graph_index 中共用，
用于创建 ChromaDB client 并判断是否需要重建索引。
"""

import pytest
from unittest.mock import patch, MagicMock


class TestEnsureClientAndCheckRebuild:
    """测试 _ensure_client_and_check_rebuild() 的边界条件"""

    def test_need_build_when_force_rebuild(self):
        """force_rebuild=True 时必须返回 need_build=True"""
        # 由于函数尚未创建，此测试预期失败（Red phase）
        from src.rag import _ensure_client_and_check_rebuild

        mock_client = MagicMock()
        with patch("src.rag.chromadb.PersistentClient", return_value=mock_client):
            with patch("src.rag._collection_exists", return_value=True):
                client, need_build = _ensure_client_and_check_rebuild(
                    "test_collection", force_rebuild=True
                )
                assert need_build is True
                assert client is mock_client

    def test_need_build_when_collection_missing(self):
        """collection 不存在时返回 need_build=True"""
        from src.rag import _ensure_client_and_check_rebuild

        mock_client = MagicMock()
        with patch("src.rag.chromadb.PersistentClient", return_value=mock_client):
            with patch("src.rag._collection_exists", return_value=False):
                client, need_build = _ensure_client_and_check_rebuild(
                    "test_collection", force_rebuild=False
                )
                assert need_build is True
                assert client is mock_client

    def test_no_need_build_when_collection_exists(self):
        """collection 存在且非 force_rebuild 时返回 need_build=False"""
        from src.rag import _ensure_client_and_check_rebuild

        mock_client = MagicMock()
        with patch("src.rag.chromadb.PersistentClient", return_value=mock_client):
            with patch("src.rag._collection_exists", return_value=True):
                client, need_build = _ensure_client_and_check_rebuild(
                    "test_collection", force_rebuild=False
                )
                assert need_build is False
                assert client is mock_client