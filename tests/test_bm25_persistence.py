"""测试 3.3 持久化 Sparse / 增量更新。"""

import json
import os
import pytest
from unittest.mock import MagicMock

from src.lexical import (
    build_bm25_index,
    save_bm25_snapshot,
    load_bm25_snapshot_from_disk,
    incremental_bm25_update,
    build_bm25_from_snapshot,
    cjk_ngram_tokenize,
    BM25_SNAPSHOT_VERSION,
)


class TestBm25SnapshotPersistence:
    def test_save_and_load(self, tmp_path):
        """保存和加载 BM25 快照。"""
        docs = ["hello world", "测试中文"]
        ids = ["chunk_0", "chunk_1"]
        bm25 = build_bm25_index(docs, ids=ids)

        filepath = str(tmp_path / "bm25_snapshot.json")
        save_bm25_snapshot(bm25, filepath, manifest_version=1)

        # 文件存在
        assert os.path.exists(filepath)

        # 加载
        snapshot = load_bm25_snapshot_from_disk(filepath)
        assert snapshot is not None
        assert snapshot["schema_version"] == BM25_SNAPSHOT_VERSION
        assert snapshot["manifest_version"] == 1
        assert "chunk_0" in snapshot["tokenized"]
        assert "chunk_1" in snapshot["tokenized"]

    def test_load_nonexistent(self, tmp_path):
        """加载不存在的文件返回 None。"""
        result = load_bm25_snapshot_from_disk(str(tmp_path / "nonexistent.json"))
        assert result is None

    def test_load_invalid_json(self, tmp_path):
        """加载无效 JSON 返回 None。"""
        filepath = str(tmp_path / "bad.json")
        with open(filepath, "w") as f:
            f.write("not json")
        result = load_bm25_snapshot_from_disk(filepath)
        assert result is None

    def test_load_old_version_returns_none(self, tmp_path):
        """旧版快照返回 None 触发全量重建。"""
        filepath = str(tmp_path / "old_snapshot.json")
        with open(filepath, "w") as f:
            json.dump({"schema_version": 1, "tokenized": {}}, f)
        result = load_bm25_snapshot_from_disk(filepath)
        assert result is None

    def test_roundtrip_preserves_tokens(self, tmp_path):
        """保存-加载-重建后 token 一致。"""
        docs = ["hello world", "南京总面积"]
        ids = ["c0", "c1"]
        bm25 = build_bm25_index(docs, ids=ids)

        filepath = str(tmp_path / "bm25.json")
        save_bm25_snapshot(bm25, filepath)

        snapshot = load_bm25_snapshot_from_disk(filepath)
        bm25_restored = build_bm25_from_snapshot(snapshot)

        # 验证 tokenized 数据一致
        original_tokens = getattr(bm25, "tokenized_by_chunk_id", {})
        restored_tokens = getattr(bm25_restored, "tokenized_by_chunk_id", {})
        for cid in original_tokens:
            assert original_tokens[cid] == restored_tokens[cid]


class TestIncrementalBm25Update:
    def test_add_new_chunks(self):
        """新增 chunk 只 tokenize 新内容。"""
        existing = {
            "schema_version": BM25_SNAPSHOT_VERSION,
            "document_hashes": {"c0": "hash0"},
            "tokenized": {"c0": ["hello", "world"]},
        }
        updated = incremental_bm25_update(
            existing,
            new_documents=["new document"],
            new_ids=["c1"],
        )
        assert "c0" in updated["tokenized"]  # 旧数据保留
        assert "c1" in updated["tokenized"]  # 新数据已 tokenize
        assert updated["tokenized"]["c0"] == ["hello", "world"]  # 旧 token 不变

    def test_remove_chunks(self):
        """删除 chunk 从快照中移除。"""
        existing = {
            "schema_version": BM25_SNAPSHOT_VERSION,
            "document_hashes": {"c0": "hash0", "c1": "hash1"},
            "tokenized": {"c0": ["hello"], "c1": ["world"]},
        }
        updated = incremental_bm25_update(
            existing,
            new_documents=[],
            new_ids=[],
            removed_ids={"c1"},
        )
        assert "c0" in updated["tokenized"]
        assert "c1" not in updated["tokenized"]

    def test_unchanged_chunk_reuses_cache(self):
        """未变更的 chunk 复用缓存 token。"""
        doc = "hello world"
        import hashlib
        doc_hash = hashlib.sha256(doc.encode("utf-8", errors="replace")).hexdigest()

        existing = {
            "schema_version": BM25_SNAPSHOT_VERSION,
            "document_hashes": {"c0": doc_hash},
            "tokenized": {"c0": ["cached_token"]},
        }
        updated = incremental_bm25_update(
            existing,
            new_documents=[doc],
            new_ids=["c0"],
        )
        # hash 匹配，应复用缓存
        assert updated["tokenized"]["c0"] == ["cached_token"]

    def test_changed_chunk_retokenizes(self):
        """变更的 chunk 重新 tokenize。"""
        existing = {
            "schema_version": BM25_SNAPSHOT_VERSION,
            "document_hashes": {"c0": "old_hash"},
            "tokenized": {"c0": ["old_token"]},
        }
        updated = incremental_bm25_update(
            existing,
            new_documents=["new content"],
            new_ids=["c0"],
        )
        # hash 不匹配，应重新 tokenize
        assert updated["tokenized"]["c0"] != ["old_token"]
        assert "new" in updated["tokenized"]["c0"] or "content" in updated["tokenized"]["c0"]

    def test_empty_existing(self):
        """无现有快照时全量 tokenize。"""
        updated = incremental_bm25_update(
            None,
            new_documents=["hello world"],
            new_ids=["c0"],
        )
        assert "c0" in updated["tokenized"]

    def test_with_metadatas(self):
        """带元数据的增量更新。"""
        updated = incremental_bm25_update(
            None,
            new_documents=["test content"],
            new_ids=["c0"],
            new_metadatas=[{"source_name": "test.pdf"}],
        )
        assert "c0" in updated["tokenized"]


class TestBuildBm25FromSnapshot:
    def test_from_snapshot(self):
        """从快照构建 BM25 索引。"""
        snapshot = {
            "schema_version": BM25_SNAPSHOT_VERSION,
            "document_hashes": {"c0": "h0", "c1": "h1"},
            "tokenized": {
                "c0": ["hello", "world"],
                "c1": ["test", "document"],
            },
        }
        bm25 = build_bm25_from_snapshot(snapshot)
        assert bm25 is not None
        # 可以查询
        scores = bm25.get_scores(["hello"])
        assert len(scores) == 2

    def test_empty_snapshot(self):
        """空快照返回空索引。"""
        snapshot = {
            "schema_version": BM25_SNAPSHOT_VERSION,
            "document_hashes": {},
            "tokenized": {},
        }
        bm25 = build_bm25_from_snapshot(snapshot)
        assert bm25 is not None

    def test_preserves_attributes(self):
        """从快照构建后保留 tokenized_by_chunk_id 和 document_hashes。"""
        snapshot = {
            "schema_version": BM25_SNAPSHOT_VERSION,
            "document_hashes": {"c0": "h0"},
            "tokenized": {"c0": ["hello"]},
        }
        bm25 = build_bm25_from_snapshot(snapshot)
        assert getattr(bm25, "tokenized_by_chunk_id", None) is not None
        assert getattr(bm25, "document_hashes", None) is not None
