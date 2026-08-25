"""Phase C 返工 / 计划 3.2 启动配置契约验收测试（TDD）。

本文件锁定独立验收发现的真实启动顺序缺陷：
- `.env` 必须在任何 `Settings` 构造之前加载（唯一启动配置入口），
  位置 = 进程启动目录（CWD）；真实环境变量始终优先；
- RAG 模块级配置名（DEFAULT_LLM_MODEL/DEFAULT_TEMPERATURE/…）与
  RAG/TUI/CLI/Graph 的实际默认参数必须消费同一个已解析 Settings，
  而不是导入期冻结的静态默认或原始 os.getenv；
- `validate_document_path` 使用已解析的 `Settings.document_root`，
  不在调用期按当前 CWD 重新解释原始环境变量；
- `.env`-only 的 `MNEME_OFFLINE=1` 在真实 fresh-process 中同样禁止
  隐式 ModelScope 下载（fake 调用次数必须为 0）。

测试方式：真实 fresh-process（subprocess，CWD=临时目录 + CWD `.env`）
与进程内重置测试结合；全部使用 fake，禁止真实 LLM/ModelScope/网络/
主目录写入。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# 子进程中必须清洗的受管配置变量（避免父进程环境/仓库 .env 泄漏）
_SCRUB_ENV = (
    "MNEME_DATA_DIR", "MNEME_DOCUMENT_ROOT", "MNEME_OFFLINE",
    "MNEME_ALLOW_INSECURE_HTTP",
    "MNEME_MAX_DOCUMENT_BYTES", "MNEME_MAX_PDF_PAGES",
    "MNEME_MAX_REMOTE_CONTEXT_CHARS",
    "LLM_MODEL", "LLM_TEMPERATURE", "LLM_TOP_K_MIN", "LLM_TOP_K_MAX",
    "ALPHA", "RAG_REFUSAL_THRESHOLD", "RAG_RERANKER", "RAG_RERANKER_MODEL",
    "RAG_REFUSAL_POLICY", "RAG_SELECTOR_MAX_PER_SOURCE", "RAG_WATCH_DIR",
    "EMBEDDING_MODEL_PATH", "EMBEDDING_MODEL_NAME",
)


@pytest.fixture(autouse=True)
def _reset_settings():
    from src.config import reset_settings
    reset_settings()
    yield
    reset_settings()


def _run_in_cwd(code: str, cwd: Path, *, env: dict | None = None) -> subprocess.CompletedProcess:
    """真实 fresh-process：CWD=临时目录，PYTHONPATH=仓库根，受管变量已清洗。"""
    full_env = dict(os.environ)
    for key in _SCRUB_ENV:
        full_env.pop(key, None)
    full_env.pop("PYTHONPATH", None)
    full_env["PYTHONPATH"] = str(REPO_ROOT)
    if env:
        full_env.update({str(k): str(v) for k, v in env.items()})
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=str(cwd), env=full_env,
        timeout=300,
    )


def _write_env(cwd: Path, lines: str) -> Path:
    env_file = cwd / ".env"
    env_file.write_text(lines, encoding="utf-8")
    return env_file


# ═══════════════════════════════════════════════════════════════
# 1. 唯一启动配置入口：CWD .env 在任何 Settings 构造前加载
# ═══════════════════════════════════════════════════════════════

class TestStartupDotenvEntry:
    def test_cwd_dotenv_reaches_settings_and_rag(self, tmp_path):
        """fresh-process：CWD `.env` 同时进入 Settings 与 rag 动态配置名。"""
        _write_env(tmp_path, (
            "LLM_MODEL=dotenv-model\n"
            "LLM_TEMPERATURE=0.91\n"
            "LLM_TOP_K_MIN=9\n"
            "LLM_TOP_K_MAX=19\n"
            "ALPHA=0.55\n"
            "MNEME_DATA_DIR=relative-data\n"
            "MNEME_OFFLINE=1\n"
            "RAG_RERANKER=cross-encoder\n"
        ))
        code = (
            "import json\n"
            "import src.rag as rag\n"
            "from src.config import get_settings\n"
            "s = get_settings()\n"
            "print(json.dumps({\n"
            "  'llm_model': s.llm_model,\n"
            "  'temperature': s.llm_temperature,\n"
            "  'top_k': [s.llm_top_k_min, s.llm_top_k_max],\n"
            "  'alpha': s.alpha,\n"
            "  'offline': s.offline_mode,\n"
            "  'reranker': s.reranker_mode,\n"
            "  'rag_llm_model': rag.DEFAULT_LLM_MODEL,\n"
            "  'rag_temperature': rag.DEFAULT_TEMPERATURE,\n"
            "  'rag_reranker': rag.RAG_RERANKER_MODE,\n"
            "  'rag_refusal': rag.DEFAULT_REFUSAL_THRESHOLD,\n"
            "  'rag_embedding': rag.EMBEDDING_MODEL_NAME,\n"
            "  'chroma': rag.CHROMA_DB_PATH,\n"
            "  'data_dir': str(s.data_dir),\n"
            "}))\n"
        )
        result = _run_in_cwd(code, tmp_path)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout.strip())
        assert payload["llm_model"] == "dotenv-model"
        assert payload["temperature"] == 0.91
        assert payload["top_k"] == [9, 19]
        assert payload["alpha"] == 0.55
        assert payload["offline"] is True
        assert payload["reranker"] == "cross-encoder"
        assert payload["rag_llm_model"] == "dotenv-model"
        assert payload["rag_temperature"] == 0.91
        assert payload["rag_reranker"] == "cross-encoder"
        assert payload["rag_refusal"] == 0.03
        assert payload["rag_embedding"] == "all-MiniLM-L6-v2"
        assert payload["chroma"] == str(tmp_path / "relative-data" / "chroma_db")
        assert payload["data_dir"] == str(tmp_path / "relative-data")

    def test_process_env_beats_cwd_dotenv(self, tmp_path):
        """fresh-process：真实环境变量 > CWD `.env`（同一键），其余键取 .env。"""
        _write_env(tmp_path, (
            "LLM_MODEL=dotenv-model\n"
            "LLM_TEMPERATURE=0.91\n"
        ))
        code = (
            "import json\n"
            "from src.config import get_settings\n"
            "s = get_settings()\n"
            "print(json.dumps([s.llm_model, s.llm_temperature]))\n"
        )
        result = _run_in_cwd(code, tmp_path, env={"LLM_MODEL": "process-model"})
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout.strip()) == ["process-model", 0.91]

    def test_invalid_cwd_dotenv_fails_fast_in_fresh_process(self, tmp_path):
        """fresh-process：CWD `.env` 非法值在导入期（任何副作用前）fail-fast。"""
        _write_env(tmp_path, "LLM_TEMPERATURE=hot\n")
        result = _run_in_cwd("import src.rag", tmp_path)
        assert result.returncode != 0
        assert "LLM_TEMPERATURE" in result.stderr

    def test_cwd_dotenv_offline_blocks_modelscope_download(self, tmp_path):
        """fresh-process：`.env`-only 的 MNEME_OFFLINE=1 同样保证 fake 下载零调用。"""
        _write_env(tmp_path, "MNEME_OFFLINE=1\nMNEME_DATA_DIR=relative-data\n")
        code = (
            "import sys, types\n"
            "import src.rag as rag\n"
            "calls = []\n"
            "class _FakeST:\n"
            "    def __init__(self, name, *a, **k):\n"
            "        raise RuntimeError('missing local: ' + str(name))\n"
            "rag.SentenceTransformer = _FakeST\n"
            "fake = types.ModuleType('modelscope')\n"
            "def _boom(*a, **k):\n"
            "    calls.append((a, k))\n"
            "    raise AssertionError('must not download')\n"
            "fake.snapshot_download = _boom\n"
            "sys.modules['modelscope'] = fake\n"
            "try:\n"
            "    rag._load_sentence_transformer('all-MiniLM-L6-v2')\n"
            "except RuntimeError as exc:\n"
            "    print('OFFLINE_ERR:' + str('MNEME_OFFLINE' in str(exc)))\n"
            "print('CALLS:' + str(len(calls)))\n"
        )
        result = _run_in_cwd(code, tmp_path)
        assert result.returncode == 0, result.stderr
        assert "OFFLINE_ERR:True" in result.stdout
        assert "CALLS:0" in result.stdout


# ═══════════════════════════════════════════════════════════════
# 2. RAG/TUI/CLI/Graph 实际默认参数消费同一个已解析 Settings
# ═══════════════════════════════════════════════════════════════

class TestConsumersUseResolvedSettings:
    def test_rag_answer_defaults_consume_settings(self, monkeypatch):
        """进程内：answer_with_llm_history 的 model/temperature 调用期解析。"""
        import src.rag as rag
        from src.config import reset_settings
        monkeypatch.setenv("LLM_MODEL", "model-from-env")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.77")
        reset_settings()

        recorded = {}

        def fake_llm_call(call_type, messages, model, temperature, **kw):
            recorded["model"] = model
            recorded["temperature"] = temperature
            resp = type("R", (), {})()
            choice = type("C", (), {})()
            msg = type("M", (), {})()
            msg.content = "ok"
            choice.message = msg
            resp.choices = [choice]
            return resp, None

        monkeypatch.setattr("src.llm_gateway.llm_call", fake_llm_call)
        assert rag.answer_with_llm_history("q", "ctx", []) == "ok"
        assert recorded == {"model": "model-from-env", "temperature": 0.77}

    def test_rag_dynamic_config_names_refresh_after_reset(self, monkeypatch):
        """进程内：reset_settings() 后 rag 配置名立即反映新契约（不再冻结）。"""
        import src.rag as rag
        from src.config import get_settings, reset_settings
        monkeypatch.setenv("LLM_MODEL", "model-a")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.31")
        reset_settings()
        assert rag.DEFAULT_LLM_MODEL == "model-a"
        assert rag.DEFAULT_TEMPERATURE == 0.31
        assert rag.DEFAULT_REFUSAL_THRESHOLD == get_settings().refusal_threshold
        monkeypatch.setenv("LLM_MODEL", "model-b")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.42")
        reset_settings()
        assert rag.DEFAULT_LLM_MODEL == "model-b"
        assert rag.DEFAULT_TEMPERATURE == 0.42

    def test_stream_signature_defaults_resolve_at_call_time(self, monkeypatch):
        """进程内：流式入口的 Top-K/temperature 不再冻结为静态默认。"""
        import inspect
        import src.rag as rag
        sig = inspect.signature(rag.answer_query_stream)
        assert sig.parameters["top_k_range"].default is None
        assert sig.parameters["temperature"].default is None
        assert sig.parameters["llm_model"].default is None

    def test_tui_ragapp_consumes_cwd_dotenv(self, tmp_path):
        """fresh-process：TUI RagApp 的真实构造路径使用 CWD `.env` 值。"""
        _write_env(tmp_path, (
            "LLM_TEMPERATURE=0.91\n"
            "ALPHA=0.55\n"
            "LLM_TOP_K_MIN=9\n"
            "LLM_TOP_K_MAX=19\n"
        ))
        code = (
            "import json\n"
            "from tui.app import RagApp\n"
            "app = RagApp()\n"
            "print(json.dumps([app.temperature, app.alpha, list(app.top_k_range)]))\n"
        )
        result = _run_in_cwd(code, tmp_path)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout.strip()) == [0.91, 0.55, [9, 19]]

    def test_cli_graph_answer_defaults_consume_settings(self, monkeypatch):
        """进程内：CLI Graph 路径的 alpha/temperature 调用期解析；内部动态
        Top-K 为 Graph 既有固定 3/50（与用户 Top-K 3–20 不绑定）。"""
        from src.config import reset_settings
        from src.cli_loop import _graph_rag_answer
        monkeypatch.setenv("ALPHA", "0.42")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.66")
        reset_settings()

        captured = {}
        docs = ["d0", "d1", "d2"]
        metas = [
            {"chunk_id": f"chunk_{i}", "source_id": f"s{i}",
             "source_name": "a.md", "source": "a.md"}
            for i in range(3)
        ]

        def fake_retrieve(query, model, collection, bm25, all_docs, kg, alpha):
            captured["alpha"] = alpha
            return [0, 1, 2], docs, [0.9, 0.8, 0.7]

        def fake_top_k(scores, min_k, max_k):
            captured["min_k"] = min_k
            captured["max_k"] = max_k
            return 3

        def fake_answer(query, context, history=None, temperature=None, **kw):
            captured["temperature"] = temperature
            return "A"

        monkeypatch.setattr("src.graph_rag.graph_augmented_retrieve", fake_retrieve)
        monkeypatch.setattr("src.rag.dynamic_top_k", fake_top_k)
        monkeypatch.setattr("src.rag.enrich_context", lambda idx, docs, metas: docs)
        monkeypatch.setattr("src.rag._build_context", lambda *a, **k: "CTX")
        monkeypatch.setattr("src.rag.format_sources", lambda *a, **k: "SRC")
        monkeypatch.setattr("src.rag.answer_with_llm_history", fake_answer)

        answer, sources = _graph_rag_answer(
            "q", None, None, None, docs, metas, kg=object(), history=[],
        )
        assert answer == "A"
        assert captured == {"alpha": 0.42, "temperature": 0.66,
                            "min_k": 3, "max_k": 50}


# ═══════════════════════════════════════════════════════════════
# 3. 文档根：已解析 Settings.document_root，不随调用期 CWD 漂移
# ═══════════════════════════════════════════════════════════════

class TestDocumentRootStability:
    def test_document_root_resolved_once_and_stable(self, monkeypatch, tmp_path):
        from src.config import get_settings, reset_settings
        from src.security import validate_document_path

        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        doc = docs_root / "ok.md"
        doc.write_text("x", encoding="utf-8")

        monkeypatch.setenv("MNEME_DOCUMENT_ROOT", "docs")  # 相对：按启动目录解析
        monkeypatch.chdir(tmp_path)
        reset_settings()
        assert get_settings().document_root == docs_root
        assert get_settings().document_root_explicit is True

        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        # CWD 改变后：原本合法的文件仍合法（根已按启动目录解析，不重新解释）
        expected = str(Path(os.path.realpath(os.path.abspath(doc))))
        assert validate_document_path(doc) == expected

        outside = elsewhere / "out.md"
        outside.write_text("x", encoding="utf-8")
        with pytest.raises(ValueError, match="MNEME_DOCUMENT_ROOT"):
            validate_document_path(outside)

    def test_unset_document_root_keeps_historical_open_behavior(self, monkeypatch,
                                                               tmp_path):
        """未设置 MNEME_DOCUMENT_ROOT 时仍允许任意文件（历史行为不变）。"""
        from src.config import reset_settings
        from src.security import validate_document_path
        monkeypatch.delenv("MNEME_DOCUMENT_ROOT", raising=False)
        reset_settings()
        doc = tmp_path / "free.md"
        doc.write_text("x", encoding="utf-8")
        assert validate_document_path(doc) == str(Path(os.path.realpath(
            os.path.abspath(doc))))
