"""2.3 解析诊断通道 + TUI 呈现的单元测试（TDD）。

覆盖（RED → GREEN）：
- ``_load_index_chunks`` 诊断 sink：成功路径 / 降级路径 / 零块显式警告 /
  sink=None 行为不变；
- ``tui.service`` 把 sink 透传给 rag 索引入口并把诊断带回 stats；
- TUI 呈现的问题条目过滤器（低质量 / 降级 / 零块 / 异常）。
"""
from __future__ import annotations

import pytest


def _write_txt(tmp_path, content="第一段。\n第二段。"):
    path = tmp_path / "doc.txt"
    path.write_text(content, encoding="utf-8")
    return path


# ── _load_index_chunks 诊断 sink ─────────────────────────────────

class TestLoadIndexChunksSink:
    def test_success_path_emits_diagnostic(self, tmp_path):
        import src.rag as rag
        sink: list = []
        chunks, metas, ids, file_type, source_id, source = \
            rag._load_index_chunks(str(_write_txt(tmp_path)),
                                   diagnostics_sink=sink)
        assert chunks
        assert len(sink) == 1
        d = sink[0]
        assert d["file_type"] == "text"
        assert d["chunk_count"] == len(chunks)
        assert d["parse_degraded"] is False
        assert d["error"] is None
        assert d["parse_quality"] == "native_text"
        assert d["source_name"]

    def test_degraded_path_emits_with_flag(self, tmp_path, monkeypatch):
        from src.loaders import LoaderRegistry
        import src.rag as rag

        def _boom(self, filepath):
            raise RuntimeError("模拟解析失败")

        monkeypatch.setattr(LoaderRegistry, "load", _boom)
        sink: list = []
        chunks, _, _, _, _, source = rag._load_index_chunks(
            str(_write_txt(tmp_path)), diagnostics_sink=sink)
        assert chunks
        assert len(sink) == 1
        d = sink[0]
        assert d["parse_degraded"] is True
        assert "RuntimeError" in d["error"]
        assert d["chunk_count"] == len(chunks)

    def test_zero_chunk_warning_printed(self, tmp_path, capsys):
        import src.rag as rag
        sink: list = []
        chunks, _, _, _, _, _ = rag._load_index_chunks(
            str(_write_txt(tmp_path, content="")),
            diagnostics_sink=sink)
        assert chunks == []
        assert sink[0]["chunk_count"] == 0
        out = capsys.readouterr().out
        assert "0 块" in out, "零块文件必须显式可见，不得静默"

    def test_no_sink_keeps_old_behavior(self, tmp_path):
        import src.rag as rag
        chunks, _, _, _, _, source = rag._load_index_chunks(
            str(_write_txt(tmp_path)))
        assert chunks
        assert "parse_degraded" not in source or \
            source.get("parse_degraded") is not True


# ── tui.service 透传与回带 ───────────────────────────────────────

@pytest.fixture()
def fake_rag_index(monkeypatch):
    """替换 service 层引用的 rag 索引入口：记录 kwargs 并回填诊断。"""
    import tui.service as svc

    calls: dict = {}

    def _fake_prepare_index(file_paths, collection_name, force_rebuild=False,
                            progress_callback=None, **kwargs):
        calls["kwargs"] = kwargs
        sink = kwargs.get("diagnostics_sink")
        if sink is not None:
            sink.append({"source_name": "doc.txt", "file_type": "text",
                         "parse_quality": "native_text",
                         "is_low_quality": False, "chunk_count": 3,
                         "parse_degraded": False, "error": None})
        return "model", "collection", "bm25", ["d"], [{}]

    def _fake_add(file_paths, model, collection, **kwargs):
        calls["add_kwargs"] = kwargs
        sink = kwargs.get("diagnostics_sink")
        if sink is not None:
            sink.append({"source_name": "new.txt", "file_type": "text",
                         "parse_quality": "native_text",
                         "is_low_quality": False, "chunk_count": 1,
                         "parse_degraded": False, "error": None})
        return "bm25", ["d"], [{}]

    monkeypatch.setattr(svc, "prepare_index", _fake_prepare_index)
    monkeypatch.setattr(svc, "add_files_to_index", _fake_add)
    monkeypatch.setattr(svc.LocalRagService, "_ensure_model",
                        lambda self: None)
    monkeypatch.setattr(svc.LocalRagService, "_refresh_snapshot",
                        lambda self: None)
    return calls


class TestServiceDiagnostics:
    def test_prepare_index_forwards_sink_and_returns_diagnostics(
            self, fake_rag_index):
        from tui.service import LocalRagService
        service = LocalRagService()
        stats = service.prepare_index(["doc.txt"], "coll")
        assert "diagnostics_sink" in fake_rag_index["kwargs"]
        assert stats["parse_diagnostics"] == fake_rag_index["kwargs"][
            "diagnostics_sink"]
        assert stats["parse_diagnostics"][0]["source_name"] == "doc.txt"

    def test_add_files_forwards_sink(self, fake_rag_index):
        from tui.service import LocalRagService
        service = LocalRagService()
        stats = service.add_files(["new.txt"])
        assert "diagnostics_sink" in fake_rag_index["add_kwargs"]
        assert stats["parse_diagnostics"][0]["source_name"] == "new.txt"


# ── TUI 呈现：问题条目过滤 ───────────────────────────────────────

class TestWarningFilter:
    def test_flags_problem_entries(self):
        from tui.screens.chat import parse_diagnostics_warnings
        diags = [
            {"source_name": "ok.txt", "is_low_quality": False,
             "parse_degraded": False, "chunk_count": 3, "error": None},
            {"source_name": "scan.pdf", "is_low_quality": True,
             "parse_degraded": False, "chunk_count": 2, "error": None},
            {"source_name": "broken.docx", "is_low_quality": None,
             "parse_degraded": True, "chunk_count": 4,
             "error": "RuntimeError: x"},
            {"source_name": "empty.txt", "is_low_quality": False,
             "parse_degraded": False, "chunk_count": 0, "error": None},
        ]
        flagged = parse_diagnostics_warnings({"parse_diagnostics": diags})
        assert [d["source_name"] for d in flagged] == [
            "scan.pdf", "broken.docx", "empty.txt"]

    def test_clean_or_missing_diagnostics_yield_nothing(self):
        from tui.screens.chat import parse_diagnostics_warnings
        assert parse_diagnostics_warnings({}) == []
        assert parse_diagnostics_warnings({"parse_diagnostics": []}) == []
