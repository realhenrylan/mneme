"""测试 3.5 来源生命周期对账。"""

import pytest
from unittest.mock import MagicMock, patch
from src.rag import compute_source_diff, sync_sources, add_sources


class TestComputeSourceDiff:
    def test_empty_desired_with_empty_index(self):
        """空 desired + 空索引 → 无差异。"""
        collection = MagicMock()
        collection.name = "test"
        with patch("src.rag.load_index_manifest", return_value=None):
            diff = compute_source_diff([], collection)
        assert diff["to_add"] == []
        assert diff["to_remove"] == []
        assert diff["to_update"] == []
        assert diff["unchanged"] == []

    def test_new_files_to_add(self):
        """新文件出现在 to_add。"""
        collection = MagicMock()
        collection.name = "test"
        manifest = {"sources": []}
        with patch("src.rag.load_index_manifest", return_value=manifest), \
             patch("src.rag.canonical_source_path", side_effect=lambda x: x):
            diff = compute_source_diff(["/path/a.pdf", "/path/b.pdf"], collection)
        assert len(diff["to_add"]) == 2
        assert diff["to_remove"] == []

    def test_stale_sources_to_remove(self):
        """索引中多余的来源出现在 to_remove。"""
        collection = MagicMock()
        collection.name = "test"
        manifest = {
            "sources": [
                {"source_path": "/path/old.pdf", "source_id": "abc123"},
            ]
        }
        with patch("src.rag.load_index_manifest", return_value=manifest), \
             patch("src.rag.canonical_source_path", side_effect=lambda x: x):
            diff = compute_source_diff(["/path/new.pdf"], collection)
        assert "/path/old.pdf" in diff["to_remove"]
        assert "/path/new.pdf" in diff["to_add"]

    def test_unchanged_sources(self):
        """未变更的来源出现在 unchanged。"""
        collection = MagicMock()
        collection.name = "test"
        manifest = {
            "sources": [
                {"source_path": "/path/a.pdf", "source_id": "abc123"},
            ]
        }
        with patch("src.rag.load_index_manifest", return_value=manifest), \
             patch("src.rag.canonical_source_path", side_effect=lambda x: x), \
             patch("src.rag._source_needs_sync", return_value=False):
            diff = compute_source_diff(["/path/a.pdf"], collection)
        assert "/path/a.pdf" in diff["unchanged"]
        assert diff["to_add"] == []
        assert diff["to_remove"] == []

    def test_changed_sources_to_update(self):
        """变更的来源出现在 to_update。"""
        collection = MagicMock()
        collection.name = "test"
        manifest = {
            "sources": [
                {"source_path": "/path/a.pdf", "source_id": "abc123"},
            ]
        }
        with patch("src.rag.load_index_manifest", return_value=manifest), \
             patch("src.rag.canonical_source_path", side_effect=lambda x: x), \
             patch("src.rag._source_needs_sync", return_value=True):
            diff = compute_source_diff(["/path/a.pdf"], collection)
        assert "/path/a.pdf" in diff["to_update"]


class TestSyncSources:
    def test_dry_run_no_changes(self):
        """dry_run 模式不执行变更。"""
        collection = MagicMock()
        collection.name = "test"
        model = MagicMock()
        manifest = {"sources": []}
        with patch("src.rag.load_index_manifest", return_value=manifest), \
             patch("src.rag.canonical_source_path", side_effect=lambda x: x):
            result = sync_sources(["/path/a.pdf"], model, collection, dry_run=True)
        assert result["added"] == 0
        assert result["removed"] == 0

    def test_sync_removes_and_adds(self, tmp_path):
        """sync 删除多余来源并添加新来源。"""
        collection = MagicMock()
        collection.name = "test"
        # B0.2.1：guard 从 collection 推导真实持久化目录——测试 double 显式提供
        collection._client._system.settings.persist_directory = str(tmp_path)
        # B0.2.2：persist 身份需双重验证（真实持久化 client + 绝对路径）
        collection._client._system.settings.is_persistent = True
        model = MagicMock()
        manifest = {
            "sources": [
                {"source_path": "/path/old.pdf", "source_id": "old_id"},
            ]
        }
        with patch("src.rag.load_index_manifest", return_value=manifest), \
             patch("src.rag.canonical_source_path", side_effect=lambda x: x), \
             patch("src.rag.remove_file_from_index", return_value=5) as mock_remove, \
             patch("src.rag.add_files_to_index", return_value=(MagicMock(), [], [])) as mock_add:
            result = sync_sources(["/path/new.pdf"], model, collection)
        assert result["removed"] == 1
        assert result["added"] == 1
        # chroma_path 为新增可选参数（默认 None → 产品默认目录，行为不变）
        mock_remove.assert_called_once_with(
            "/path/old.pdf", collection, chroma_path=None)
        mock_add.assert_called_once()


class TestAddSources:
    def test_add_only_no_removal(self, tmp_path):
        """add_sources 只增不删。"""
        collection = MagicMock()
        collection.name = "test"
        # B0.2.1：guard 从 collection 推导真实持久化目录——测试 double 显式提供
        collection._client._system.settings.persist_directory = str(tmp_path)
        # B0.2.2：persist 身份需双重验证（真实持久化 client + 绝对路径）
        collection._client._system.settings.is_persistent = True
        model = MagicMock()
        manifest = {
            "sources": [
                {"source_path": "/path/old.pdf", "source_id": "old_id"},
            ]
        }
        with patch("src.rag.load_index_manifest", return_value=manifest), \
             patch("src.rag.canonical_source_path", side_effect=lambda x: x), \
             patch("src.rag.add_files_to_index", return_value=(MagicMock(), [], [])) as mock_add:
            result = add_sources(["/path/new.pdf"], model, collection)
        assert result["added"] == 1
        # 不应调用 remove_file_from_index
        assert result.get("removed", 0) == 0

    def test_add_updates_changed(self, tmp_path):
        """add_sources 更新变更的文件。"""
        collection = MagicMock()
        collection.name = "test"
        # B0.2.1：guard 从 collection 推导真实持久化目录——测试 double 显式提供
        collection._client._system.settings.persist_directory = str(tmp_path)
        # B0.2.2：persist 身份需双重验证（真实持久化 client + 绝对路径）
        collection._client._system.settings.is_persistent = True
        model = MagicMock()
        manifest = {
            "sources": [
                {"source_path": "/path/a.pdf", "source_id": "abc123"},
            ]
        }
        with patch("src.rag.load_index_manifest", return_value=manifest), \
             patch("src.rag.canonical_source_path", side_effect=lambda x: x), \
             patch("src.rag._source_needs_sync", return_value=True), \
             patch("src.rag.remove_file_from_index", return_value=3) as mock_remove, \
             patch("src.rag.add_files_to_index", return_value=(MagicMock(), [], [])) as mock_add:
            result = add_sources(["/path/a.pdf"], model, collection)
        assert result["updated"] == 1
        mock_remove.assert_called_once()
