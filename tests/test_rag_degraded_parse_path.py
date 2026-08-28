"""2.1 摄取降级路径显式化的单元测试（TDD）。

背景（设计 §4.3）：``src.rag._load_index_chunks`` 在新 loader 失败时静默
降级到旧字符切分路径，且残留 ``traceback.print_exc()`` 调试输出。验收
口径要求降级**显式可见且可追溯**：

- 降级警告含异常类型+摘要，不打印堆栈；
- source record 记 ``parse_degraded`` / ``parse_degraded_reason``，
  随既有 index manifest 落盘可追溯；
- 降级行为本身不变（索引照常建成，不 fail-fast）；
- 成功路径不得带 degraded 标记。
"""
from __future__ import annotations

import pytest

import src.rag as rag


def _write_txt(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("第一段内容，用于旧路径字符切分。\n第二段内容。\n",
                    encoding="utf-8")
    return path


@pytest.fixture()
def broken_loader(monkeypatch):
    from src.loaders import LoaderRegistry

    def _boom(self, filepath):
        raise RuntimeError("模拟解析失败")

    monkeypatch.setattr(LoaderRegistry, "load", _boom)


def test_degraded_path_builds_chunks_and_records_flag(tmp_path, broken_loader):
    path = _write_txt(tmp_path)
    chunks, metadatas, ids, file_type, source_id, source = \
        rag._load_index_chunks(str(path))
    assert chunks, "降级后索引块不应为空（行为不变量）"
    assert source["parse_degraded"] is True
    assert "RuntimeError" in source["parse_degraded_reason"]
    assert "模拟解析失败" in source["parse_degraded_reason"]


def test_degraded_warning_visible_without_traceback(
        tmp_path, broken_loader, capsys):
    path = _write_txt(tmp_path)
    rag._load_index_chunks(str(path))
    out = capsys.readouterr().out
    assert "降级" in out
    assert "模拟解析失败" in out
    assert "Traceback" not in out, "调试堆栈残留必须移除"


def test_success_path_has_no_degraded_flag(tmp_path):
    path = _write_txt(tmp_path)
    chunks, metadatas, ids, file_type, source_id, source = \
        rag._load_index_chunks(str(path))
    assert chunks
    assert not source.get("parse_degraded")
