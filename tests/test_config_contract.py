"""Phase C / 计划 3.2「数据目录与配置统一」契约验收测试（TDD）。

本文件锁定统一配置契约：
- src.config.Settings 是受管配置唯一默认值来源
- 覆盖规则：真实环境变量 > .env（load_dotenv 不覆盖既有环境变量）> 契约默认值
- 用户 Top-K（LLM_TOP_K_MIN/MAX，TUI/流式区间）与内部检索宽度
  （DEFAULT_TOP_K/MIN_K/MAX_K，70/12/70）是两个独立概念，不绑定
- MNEME_OFFLINE=1 的精确承诺：仅禁止隐式远程 ModelScope 下载
- 非法数值/非法范围在任何索引、模型加载、网络或目录写入之前 fail-fast
- 配置读取零写入（无 ensure_dirs()/无索引动作时）

全部测试使用 fake/mock 与临时目录：禁止真实 LLM、ModelScope 下载、网络调用
或用户主目录写入。
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_settings():
    from src.config import reset_settings
    reset_settings()
    yield
    reset_settings()


def _run_python(code: str, *, env: dict | None = None,
                remove_env: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    """在全新 Python 进程中运行代码（证明 CLI/RAG 新进程契约）。"""
    full_env = dict(os.environ)
    for key in remove_env:
        full_env.pop(key, None)
    if env:
        full_env.update({str(k): str(v) for k, v in env.items()})
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=str(REPO_ROOT), env=full_env,
        timeout=300,
    )


# ═══════════════════════════════════════════════════════════════
# 1. 默认值、环境变量覆盖、单例重置与跨入口一致性
# ═══════════════════════════════════════════════════════════════

class TestDefaultsAndOverrides:
    def test_defaults_match_contract(self, monkeypatch):
        """无任何环境变量时 Settings 返回契约默认值。"""
        for key in ("MNEME_DATA_DIR", "LLM_TEMPERATURE", "ALPHA",
                    "LLM_TOP_K_MIN", "LLM_TOP_K_MAX", "RAG_REFUSAL_THRESHOLD",
                    "RAG_RERANKER", "MNEME_OFFLINE", "LLM_MODEL",
                    "EMBEDDING_MODEL_PATH", "EMBEDDING_MODEL_NAME"):
            monkeypatch.delenv(key, raising=False)
        from src.config import Settings
        s = Settings()
        assert s.llm_model == "deepseek-chat"
        assert s.llm_temperature == 0.1
        assert (s.llm_top_k_min, s.llm_top_k_max) == (3, 20)
        assert s.alpha == 0.7
        assert s.refusal_threshold == 0.03
        assert s.embedding_model_name == "all-MiniLM-L6-v2"
        assert s.reranker_mode == "none"
        assert s.reranker_model_name == "cross-encoder/ms-marco-MiniLM-L-6-v2"
        assert s.max_document_bytes == 52428800
        assert s.max_pdf_pages == 2000
        assert s.max_remote_context_chars == 60000
        assert s.offline_mode is False

    def test_env_overrides_defaults(self, monkeypatch):
        monkeypatch.setenv("LLM_TEMPERATURE", "0.5")
        monkeypatch.setenv("ALPHA", "0.4")
        monkeypatch.setenv("LLM_TOP_K_MIN", "4")
        monkeypatch.setenv("LLM_TOP_K_MAX", "14")
        from src.config import Settings
        s = Settings()
        assert s.llm_temperature == 0.5
        assert s.alpha == 0.4
        assert (s.llm_top_k_min, s.llm_top_k_max) == (4, 14)

    def test_env_beats_dotenv(self, monkeypatch, tmp_path):
        """真实环境变量优先于 .env（load_dotenv 不覆盖既有变量）。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("LLM_TEMPERATURE=0.9\n", encoding="utf-8")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.5")
        from dotenv import load_dotenv
        from src.config import Settings
        saved = os.environ.get("LLM_TEMPERATURE")
        try:
            load_dotenv(tmp_path / ".env")
            assert Settings().llm_temperature == 0.5
        finally:
            # load_dotenv 会真实改写 os.environ（非 monkeypatch，不自动还原），
            # 显式还原以免污染同进程后续测试的 Settings 构造。
            if saved is None:
                os.environ.pop("LLM_TEMPERATURE", None)
            else:
                os.environ["LLM_TEMPERATURE"] = saved

    def test_dotenv_applied_when_no_env(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("LLM_TEMPERATURE=0.9\n", encoding="utf-8")
        monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
        from dotenv import load_dotenv
        from src.config import Settings
        saved = os.environ.get("LLM_TEMPERATURE")
        try:
            load_dotenv(tmp_path / ".env")
            assert Settings().llm_temperature == 0.9
        finally:
            # 同上：load_dotenv 的 os.environ 改写不自动还原，显式还原。
            if saved is None:
                os.environ.pop("LLM_TEMPERATURE", None)
            else:
                os.environ["LLM_TEMPERATURE"] = saved

    def test_singleton_and_reset(self):
        from src.config import get_settings, reset_settings
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
        reset_settings()
        s3 = get_settings()
        assert s1 is not s3

    def test_rag_module_constants_derive_from_contract(self, monkeypatch):
        """rag.py 的公开常量与 Settings 契约默认值一致（同源派生）。"""
        for key in ("MNEME_DATA_DIR", "LLM_TEMPERATURE", "ALPHA",
                    "LLM_TOP_K_MIN", "LLM_TOP_K_MAX", "RAG_REFUSAL_THRESHOLD",
                    "RAG_RERANKER", "EMBEDDING_MODEL_PATH",
                    "EMBEDDING_MODEL_NAME"):
            monkeypatch.delenv(key, raising=False)
        import src.rag as rag
        from src.config import Settings
        s = Settings()
        assert rag.DEFAULT_EMBEDDING_MODEL == s.embedding_model_name
        assert rag.EMBEDDING_MODEL_NAME == s.embedding_model_name
        assert rag.DEFAULT_LLM_MODEL == s.llm_model == "deepseek-chat"
        assert rag.DEFAULT_TEMPERATURE == s.llm_temperature == 0.1
        assert rag.DEFAULT_REFUSAL_THRESHOLD == s.refusal_threshold == 0.03
        assert rag.RAG_RERANKER_MODE == s.reranker_mode == "none"
        assert rag.RERANKER_MODEL_NAME == s.reranker_model_name
        assert rag.DEFAULT_TOP_K == s.retrieval_candidate_k == 70
        assert rag.DEFAULT_MIN_K == s.retrieval_dynamic_min_k == 12
        assert rag.DEFAULT_MAX_K == s.retrieval_dynamic_max_k == 70
        assert rag.CHROMA_DB_PATH == str(s.chroma_db_path)

    def test_user_top_k_distinct_from_internal_retrieval_width(self, monkeypatch):
        """用户 Top-K 与内部检索宽度是两个概念：分别正确、不绑定。"""
        for key in ("LLM_TOP_K_MIN", "LLM_TOP_K_MAX"):
            monkeypatch.delenv(key, raising=False)
        import inspect
        import src.rag as rag
        from src.config import Settings
        s = Settings()
        # 用户区间：TUI/流式路径默认从 Settings 调用期解析（签名默认 None，
        # 不再冻结静态值——真实 .env/环境变量在启动入口加载后生效）
        stream_sig = inspect.signature(rag.answer_query_stream)
        assert stream_sig.parameters["top_k_range"].default is None
        assert stream_sig.parameters["temperature"].default is None
        assert (s.llm_top_k_min, s.llm_top_k_max) == (3, 20)
        # 内部检索宽度：同步路径 dynamic_top_k 默认 (12, 70)
        dynamic_sig = inspect.signature(rag.dynamic_top_k)
        assert dynamic_sig.parameters["min_k"].default == 12
        assert dynamic_sig.parameters["max_k"].default == 70
        assert (s.retrieval_dynamic_min_k, s.retrieval_dynamic_max_k) == (12, 70)
        # 两者明确不同，不得被文档或实现绑定
        assert s.llm_top_k_min != s.retrieval_dynamic_min_k
        assert s.llm_top_k_max != s.retrieval_dynamic_max_k


# ═══════════════════════════════════════════════════════════════
# 2. 数据目录落点：Chroma/BM25/manifest 在 MNEME_DATA_DIR 下，不进包目录
# ═══════════════════════════════════════════════════════════════

class TestDataDirectoryContract:
    def test_data_dir_override_lands_chroma_bm25_manifest_under_it(
            self, monkeypatch, tmp_path):
        import src.rag as rag
        monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "mneme-data"))
        from src.config import Settings
        s = Settings()
        chroma_dir = s.chroma_db_path
        assert chroma_dir == tmp_path / "mneme-data" / "chroma_db"
        client = rag._new_persistent_client(str(chroma_dir))
        try:
            persist_dir = client._system.settings.persist_directory
            assert Path(persist_dir) == chroma_dir.resolve()
        finally:
            rag.close_chroma_clients()
        assert Path(rag._manifest_path("c1", str(chroma_dir))) == \
            chroma_dir / "c1.manifest.json"
        assert Path(rag._bm25_snapshot_path("c1", str(chroma_dir))) == \
            chroma_dir / "c1.bm25.json"
        assert not str(chroma_dir).startswith(str(REPO_ROOT / "src"))

    def test_default_data_dir_is_home_not_src(self, monkeypatch):
        monkeypatch.delenv("MNEME_DATA_DIR", raising=False)
        from src.config import Settings
        s = Settings()
        assert s.data_dir == Path.home() / ".mneme"
        assert s.chroma_db_path == Path.home() / ".mneme" / "chroma_db"
        assert not str(s.chroma_db_path).startswith(str(REPO_ROOT / "src"))

    def test_tilde_data_dir_expands_cross_platform(self, monkeypatch, tmp_path):
        """文档承诺的 ~ 语法在 Windows/Python 下真实展开。"""
        monkeypatch.setenv("MNEME_DATA_DIR", "~/mneme-data")
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
        monkeypatch.setenv("USERPROFILE", str(tmp_path / "fakehome"))
        from src.config import Settings
        s = Settings()
        assert s.data_dir == tmp_path / "fakehome" / "mneme-data"
        assert s.data_dir.is_absolute()

    def test_relative_data_dir_becomes_absolute(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MNEME_DATA_DIR", "data/rel")
        monkeypatch.chdir(tmp_path)
        from src.config import Settings
        s = Settings()
        assert s.data_dir == tmp_path / "data" / "rel"
        assert s.data_dir.is_absolute()

    def test_fresh_process_uses_same_contract(self, tmp_path):
        """CLI/RAG 新进程启动时与 Settings 使用同一配置契约。"""
        data_dir = tmp_path / "proc-data"
        code = (
            "import src.rag as rag\n"
            "from src.config import get_settings\n"
            "print(rag.CHROMA_DB_PATH)\n"
            "print(rag._manifest_path('c', None))\n"
            "print(rag._bm25_snapshot_path('c', None))\n"
            "print(rag.EMBEDDING_MODEL_NAME)\n"
            "print(rag.DEFAULT_TEMPERATURE)\n"
            "print(get_settings().llm_top_k_min)\n"
        )
        result = _run_python(code, env={"MNEME_DATA_DIR": str(data_dir)})
        assert result.returncode == 0, result.stderr
        lines = result.stdout.strip().splitlines()
        chroma = data_dir / "chroma_db"
        assert Path(lines[0]) == chroma
        assert Path(lines[1]) == chroma / "c.manifest.json"
        assert Path(lines[2]) == chroma / "c.bm25.json"
        assert lines[3] == "all-MiniLM-L6-v2"
        assert lines[4] == "0.1"
        assert lines[5] == "3"

    def test_fresh_process_default_data_dir_is_home_not_src(self, tmp_path):
        code = "import src.rag as rag; print(rag.CHROMA_DB_PATH)"
        home = tmp_path / "home"
        result = _run_python(
            code, env={"HOME": str(home), "USERPROFILE": str(home)},
            remove_env=("MNEME_DATA_DIR",),
        )
        assert result.returncode == 0, result.stderr
        chroma = Path(result.stdout.strip())
        assert chroma == home / ".mneme" / "chroma_db"
        assert not str(chroma).startswith(str(REPO_ROOT / "src"))

    def test_invalid_config_fails_in_fresh_process_before_writes(self, tmp_path):
        """非法配置在导入期（任何索引/模型/网络/目录写入之前）fail-fast。"""
        data_dir = tmp_path / "never-created"
        result = _run_python(
            "import src.rag",
            env={"MNEME_DATA_DIR": str(data_dir), "LLM_TOP_K_MIN": "0"},
        )
        assert result.returncode != 0
        assert "LLM_TOP_K_MIN" in result.stderr
        assert not data_dir.exists()


# ═══════════════════════════════════════════════════════════════
# 4. TUI 使用同一 Settings，不再单独用 .env 读取出不同默认值
# ═══════════════════════════════════════════════════════════════

class TestTuiUsesSettings:
    def test_ragapp_env_beats_dotenv(self, monkeypatch, tmp_path):
        """RagApp 经 Settings 读取：真实环境变量优先于 .env 文件值。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            "LLM_TEMPERATURE=0.9\nALPHA=0.4\nLLM_TOP_K_MIN=9\n"
            "LLM_TOP_K_MAX=30\nRAG_WATCH_DIR=dotenv-watch\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("LLM_TEMPERATURE", "0.5")
        monkeypatch.setenv("ALPHA", "0.6")
        monkeypatch.setenv("LLM_TOP_K_MIN", "4")
        monkeypatch.setenv("LLM_TOP_K_MAX", "14")
        monkeypatch.setenv("RAG_WATCH_DIR", "env-watch")
        # 契约模式：env → reset_settings()（重载 CWD .env + 重建 Settings）。
        # reset_settings 现在会经刷新回调立即重建 Settings 单例，因此读取
        # 前必须先重置；真实环境变量仍优先于 .env。
        from src.config import reset_settings
        reset_settings()
        from tui.app import RagApp
        app = RagApp()
        assert app.temperature == 0.5
        assert app.alpha == 0.6
        assert app.top_k_range == (4, 14)
        assert app._read_watch_dir() == "env-watch"

    def test_ragapp_defaults_match_settings(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        for key in ("LLM_TEMPERATURE", "ALPHA", "LLM_TOP_K_MIN",
                    "LLM_TOP_K_MAX", "RAG_WATCH_DIR"):
            monkeypatch.delenv(key, raising=False)
        from tui.app import RagApp
        app = RagApp()
        assert app.temperature == 0.1
        assert app.alpha == 0.7
        assert app.top_k_range == (3, 20)
        assert app._read_watch_dir() == ""


# ═══════════════════════════════════════════════════════════════
# 6. MNEME_OFFLINE=1：缺失本地模型只给明确本地错误，绝不调用 ModelScope
# ═══════════════════════════════════════════════════════════════

class TestOfflineMode:
    def test_offline_missing_model_raises_local_error_no_modelscope(
            self, monkeypatch):
        import src.rag as rag
        monkeypatch.setenv("MNEME_OFFLINE", "1")
        from src.config import reset_settings
        reset_settings()

        calls = []

        class _FakeSentenceTransformer:
            def __init__(self, model_name, *args, **kwargs):
                raise RuntimeError(f"missing locally: {model_name}")

        monkeypatch.setattr(rag, "SentenceTransformer", _FakeSentenceTransformer)
        fake_modelscope = type("FakeModelScope", (), {})()
        def _boom(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("ModelScope 下载在离线模式被调用")
        fake_modelscope.snapshot_download = _boom
        monkeypatch.setitem(sys.modules, "modelscope", fake_modelscope)

        with pytest.raises(RuntimeError) as exc_info:
            rag._load_sentence_transformer("all-MiniLM-L6-v2")
        message = str(exc_info.value)
        assert "MNEME_OFFLINE" in message
        assert "本地" in message
        assert calls == []

    def test_offline_local_model_still_loads(self, monkeypatch):
        """离线只禁止隐式下载，本地模型照常加载。"""
        import src.rag as rag
        monkeypatch.setenv("MNEME_OFFLINE", "1")
        from src.config import reset_settings
        reset_settings()

        class _FakeSentenceTransformer:
            def __init__(self, model_name, *args, **kwargs):
                self.model_name = model_name

        monkeypatch.setattr(rag, "SentenceTransformer", _FakeSentenceTransformer)
        fake_modelscope = type("FakeModelScope", (), {})()
        def _boom(*args, **kwargs):
            raise AssertionError("ModelScope 下载在离线模式被调用")
        fake_modelscope.snapshot_download = _boom
        monkeypatch.setitem(sys.modules, "modelscope", fake_modelscope)

        model = rag._load_sentence_transformer("some/local/path")
        assert model.model_name == "some/local/path"

    def test_online_fallback_uses_modelscope_and_settings_cache_dir(
            self, monkeypatch, tmp_path):
        import src.rag as rag
        monkeypatch.setenv("MNEME_OFFLINE", "0")
        monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
        from src.config import reset_settings, get_settings
        reset_settings()

        calls = []

        class _FakeSentenceTransformer:
            def __init__(self, model_name, *args, **kwargs):
                if model_name != "/fake/modelscope/path":
                    raise RuntimeError("not local")

        monkeypatch.setattr(rag, "SentenceTransformer", _FakeSentenceTransformer)
        fake_modelscope = type("FakeModelScope", (), {})()
        def _snapshot_download(model_id, cache_dir=None):
            calls.append({"model_id": model_id, "cache_dir": cache_dir})
            return "/fake/modelscope/path"
        fake_modelscope.snapshot_download = _snapshot_download
        monkeypatch.setitem(sys.modules, "modelscope", fake_modelscope)

        rag._load_sentence_transformer("all-MiniLM-L6-v2")
        assert len(calls) == 1
        assert calls[0]["model_id"] == "sentence-transformers/all-MiniLM-L6-v2"
        # 自动下载缓存必须落在稳定数据目录（MNEME_DATA_DIR/models），
        # 而不是 CWD 相对路径
        assert calls[0]["cache_dir"] == str(get_settings().model_cache_dir)
        assert Path(calls[0]["cache_dir"]).is_absolute()


# ═══════════════════════════════════════════════════════════════
# 7. 非法数值/非法范围 fail-fast（先于任何副作用）
# ═══════════════════════════════════════════════════════════════

class TestFailFastValidation:
    def test_invalid_temperature_string_names_var(self, monkeypatch):
        monkeypatch.setenv("LLM_TEMPERATURE", "hot")
        from src.config import Settings
        with pytest.raises(ValueError, match="LLM_TEMPERATURE"):
            Settings()

    def test_temperature_out_of_range(self, monkeypatch):
        monkeypatch.setenv("LLM_TEMPERATURE", "2.5")
        from src.config import Settings
        with pytest.raises(ValueError, match="LLM_TEMPERATURE"):
            Settings()

    def test_top_k_min_less_than_one(self, monkeypatch):
        monkeypatch.setenv("LLM_TOP_K_MIN", "0")
        from src.config import Settings
        with pytest.raises(ValueError, match="LLM_TOP_K_MIN"):
            Settings()

    def test_top_k_min_greater_than_max(self, monkeypatch):
        monkeypatch.setenv("LLM_TOP_K_MIN", "25")
        monkeypatch.setenv("LLM_TOP_K_MAX", "20")
        from src.config import Settings
        with pytest.raises(ValueError, match="LLM_TOP_K_(MIN|MAX)"):
            Settings()

    def test_alpha_out_of_range(self, monkeypatch):
        monkeypatch.setenv("ALPHA", "1.5")
        from src.config import Settings
        with pytest.raises(ValueError, match="ALPHA"):
            Settings()

    def test_refusal_threshold_invalid_string_names_var(self, monkeypatch):
        monkeypatch.setenv("RAG_REFUSAL_THRESHOLD", "not-a-number")
        from src.config import Settings
        with pytest.raises(ValueError, match="RAG_REFUSAL_THRESHOLD"):
            Settings()

    def test_resource_limit_zero_rejected(self, monkeypatch):
        monkeypatch.setenv("MNEME_MAX_DOCUMENT_BYTES", "0")
        from src.config import Settings
        with pytest.raises(ValueError, match="MNEME_MAX_DOCUMENT_BYTES"):
            Settings()

    def test_reranker_mode_unknown_rejected(self, monkeypatch):
        monkeypatch.setenv("RAG_RERANKER", "fancy-mode")
        from src.config import Settings
        with pytest.raises(ValueError, match="RAG_RERANKER"):
            Settings()

    def test_validation_before_any_writes(self, monkeypatch, tmp_path):
        """校验失败发生在任何目录写入之前。"""
        data_dir = tmp_path / "data"
        monkeypatch.setenv("MNEME_DATA_DIR", str(data_dir))
        monkeypatch.setenv("LLM_TOP_K_MIN", "0")
        from src.config import Settings
        with pytest.raises(ValueError, match="LLM_TOP_K_MIN"):
            Settings()
        assert not data_dir.exists()
        assert not (data_dir / "chroma_db").exists()

    def test_security_constants_derive_from_settings(self):
        import src.security as security
        from src.config import Settings
        s = Settings()
        assert security.DEFAULT_MAX_DOCUMENT_BYTES == 50 * 1024 * 1024
        assert security.DEFAULT_MAX_PDF_PAGES == 2000
        assert security.DEFAULT_MAX_REMOTE_CONTEXT_CHARS == 60000
        assert security.MAX_DOCUMENT_BYTES == s.max_document_bytes
        assert security.MAX_PDF_PAGES == s.max_pdf_pages
        assert security.MAX_REMOTE_CONTEXT_CHARS == s.max_remote_context_chars


# ═══════════════════════════════════════════════════════════════
# 9. 配置读取零写入
# ═══════════════════════════════════════════════════════════════

class TestZeroWriteConfigReads:
    def test_settings_construction_and_reads_create_nothing(
            self, monkeypatch, tmp_path):
        data_dir = tmp_path / "data"
        monkeypatch.setenv("MNEME_DATA_DIR", str(data_dir))
        from src.config import Settings, get_settings, reset_settings
        reset_settings()
        s = get_settings()
        _ = s.to_dict()
        s2 = Settings()
        _ = s2.to_dict()
        assert not data_dir.exists()
        assert not s.chroma_db_path.exists()
        assert not s.model_cache_dir.exists()


# ═══════════════════════════════════════════════════════════════
# 8. .env.example 与中英文 README 的配置名和默认值与实现一致
# ═══════════════════════════════════════════════════════════════

class TestDocumentationConsistency:
    def test_env_example_defaults_match_implementation(self):
        text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        for needle in (
            "# LLM_MODEL=deepseek-chat",
            "# LLM_TEMPERATURE=0.1",
            "# LLM_TOP_K_MIN=3",
            "# LLM_TOP_K_MAX=20",
            "# ALPHA=0.7",
            "# RAG_REFUSAL_THRESHOLD=0.03",
            "# MNEME_DATA_DIR=~/.mneme",
            "# MNEME_OFFLINE=1",
            "# RAG_RERANKER=none",
            "# RAG_RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2",
            "# EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2",
            "# MNEME_MAX_DOCUMENT_BYTES=52428800",
            "# MNEME_MAX_PDF_PAGES=2000",
            "# MNEME_MAX_REMOTE_CONTEXT_CHARS=60000",
            "# MNEME_DOCUMENT_ROOT=./documents",
        ):
            assert needle in text, f".env.example 缺少 {needle!r}"

    def test_readme_tables_match_implementation(self):
        en = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        zh = (REPO_ROOT / "README.zh.md").read_text(encoding="utf-8")
        rows_en = (
            "| `LLM_MODEL` | `deepseek-chat` |",
            "| `LLM_TEMPERATURE` | `0.1` |",
            "| `LLM_TOP_K_MIN` | `3` |",
            "| `LLM_TOP_K_MAX` | `20` |",
            "| `ALPHA` | `0.7` |",
            "| `MNEME_DATA_DIR` | `~/.mneme` |",
            "| `RAG_REFUSAL_THRESHOLD` | `0.03` |",
            "| `RAG_RERANKER` | `none` |",
            "| `MNEME_OFFLINE` |",
            "| `EMBEDDING_MODEL_NAME` | `all-MiniLM-L6-v2` |",
        )
        rows_zh = (
            "| `LLM_MODEL` | `deepseek-chat` |",
            "| `LLM_TEMPERATURE` | `0.1` |",
            "| `LLM_TOP_K_MIN` | `3` |",
            "| `LLM_TOP_K_MAX` | `20` |",
            "| `ALPHA` | `0.7` |",
            "| `MNEME_DATA_DIR` | `~/.mneme` |",
            "| `RAG_REFUSAL_THRESHOLD` | `0.03` |",
            "| `RAG_RERANKER` | `none` |",
            "| `MNEME_OFFLINE` |",
            "| `EMBEDDING_MODEL_NAME` | `all-MiniLM-L6-v2` |",
        )
        for needle in rows_en:
            assert needle in en, f"README.md 缺少/不符 {needle!r}"
        for needle in rows_zh:
            assert needle in zh, f"README.zh.md 缺少/不符 {needle!r}"

    def test_docs_state_offline_boundary_and_precedence(self):
        en = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        zh = (REPO_ROOT / "README.zh.md").read_text(encoding="utf-8")
        assert "environment variables > `.env` > built-in defaults" in en
        assert "真实环境变量 > `.env` > 内置默认值" in zh
        assert "%USERPROFILE%" in en and "%USERPROFILE%" in zh
        assert "only blocks implicit remote ModelScope downloads" in en
        assert "仅禁止隐式远程 ModelScope 下载" in zh
