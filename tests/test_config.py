"""测试 3.2 数据目录与配置统一。"""

import os
import pytest
from pathlib import Path
from src.config import Settings, get_settings, reset_settings, _resolve_data_dir, _resolve_document_root


class TestSettings:
    def setup_method(self):
        reset_settings()

    def teardown_method(self):
        reset_settings()

    def test_default_data_dir(self, monkeypatch):
        """默认数据目录为 ~/.mneme。"""
        monkeypatch.delenv("MNEME_DATA_DIR", raising=False)
        s = Settings()
        assert s.data_dir == Path.home() / ".mneme"

    def test_custom_data_dir(self, monkeypatch):
        """MNEME_DATA_DIR 环境变量覆盖默认路径。"""
        monkeypatch.setenv("MNEME_DATA_DIR", "/tmp/mneme_test")
        s = Settings()
        assert s.data_dir == Path("/tmp/mneme_test")

    def test_chroma_db_path_derived(self, monkeypatch):
        """chroma_db_path 从 data_dir 派生。"""
        monkeypatch.delenv("MNEME_DATA_DIR", raising=False)
        s = Settings()
        assert s.chroma_db_path == s.data_dir / "chroma_db"

    def test_default_temperature(self, monkeypatch):
        """默认温度为 0.1。"""
        monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
        s = Settings()
        assert s.llm_temperature == 0.1

    def test_custom_temperature(self, monkeypatch):
        """LLM_TEMPERATURE 环境变量覆盖。"""
        monkeypatch.setenv("LLM_TEMPERATURE", "0.5")
        s = Settings()
        assert s.llm_temperature == 0.5

    def test_default_top_k_range(self, monkeypatch):
        """默认 top_k 范围为 (3, 20)。"""
        monkeypatch.delenv("LLM_TOP_K_MIN", raising=False)
        monkeypatch.delenv("LLM_TOP_K_MAX", raising=False)
        s = Settings()
        assert s.llm_top_k_min == 3
        assert s.llm_top_k_max == 20

    def test_default_refusal_threshold(self, monkeypatch):
        """默认拒答阈值为 0.03。"""
        monkeypatch.delenv("RAG_REFUSAL_THRESHOLD", raising=False)
        s = Settings()
        assert s.refusal_threshold == 0.03

    def test_offline_mode_default_off(self, monkeypatch):
        """默认离线模式关闭。"""
        monkeypatch.delenv("MNEME_OFFLINE", raising=False)
        s = Settings()
        assert s.offline_mode is False

    def test_offline_mode_enabled(self, monkeypatch):
        """MNEME_OFFLINE=1 开启离线模式。"""
        monkeypatch.setenv("MNEME_OFFLINE", "1")
        s = Settings()
        assert s.offline_mode is True

    def test_allow_insecure_default_off(self, monkeypatch):
        """默认不允许不安全 HTTP。"""
        monkeypatch.delenv("MNEME_ALLOW_INSECURE_HTTP", raising=False)
        s = Settings()
        assert s.allow_insecure_http is False

    def test_to_dict(self, monkeypatch):
        """to_dict 包含所有配置项。"""
        monkeypatch.delenv("MNEME_DATA_DIR", raising=False)
        s = Settings()
        d = s.to_dict()
        assert "data_dir" in d
        assert "chroma_db_path" in d
        assert "llm_temperature" in d
        assert "llm_top_k_range" in d
        assert "offline_mode" in d

    def test_ensure_dirs(self, monkeypatch, tmp_path):
        """ensure_dirs 创建数据目录。"""
        test_dir = tmp_path / "mneme_test"
        monkeypatch.setenv("MNEME_DATA_DIR", str(test_dir))
        s = Settings()
        s.ensure_dirs()
        assert test_dir.exists()
        assert (test_dir / "chroma_db").exists()


class TestGlobalSettings:
    def setup_method(self):
        reset_settings()

    def teardown_method(self):
        reset_settings()

    def test_singleton(self):
        """get_settings 返回同一实例。"""
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_reset(self):
        """reset_settings 后获取新实例。"""
        s1 = get_settings()
        reset_settings()
        s2 = get_settings()
        assert s1 is not s2


class TestResolveDataDir:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("MNEME_DATA_DIR", "/custom/path")
        assert _resolve_data_dir() == Path("/custom/path")

    def test_default(self, monkeypatch):
        monkeypatch.delenv("MNEME_DATA_DIR", raising=False)
        assert _resolve_data_dir() == Path.home() / ".mneme"


class TestResolveDocumentRoot:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("MNEME_DOCUMENT_ROOT", "/custom/docs")
        assert _resolve_document_root() == Path("/custom/docs")

    def test_default(self, monkeypatch):
        monkeypatch.delenv("MNEME_DOCUMENT_ROOT", raising=False)
        assert _resolve_document_root() == Path.cwd() / "documents"
