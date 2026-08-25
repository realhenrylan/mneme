"""Phase C / 计划 3.2 第二轮返工契约测试（TDD）。

锁定独立验收第二轮复现的配置契约缺口：
1. `src/llm_gateway.py` 不得自行 `load_dotenv()`（package-root `.env` 不得
   偷偷进入 gateway 进程），也不得以 `os.getenv("LLM_MODEL", ...)` 绕过
   Settings——LLM model/temperature 委托统一配置层；API_KEY/BASE_URL
   保留在 gateway 边界（读取环境变量，但不自行加载 .env）；
2. `.env` 与 reset 的真实契约：进程环境变量 > 启动目录 CWD 的 `.env` >
   默认值；`reset_settings()` 是 TUI/onboarding 的刷新入口，必须真实反映
   `.env` 文件修改（含键删除），且绝不覆盖显式进程环境变量；
3. reset 后 Graph/TUI/security 不持有过期副本：数据目录、embedding 模型、
   LLM model、资源上限在实际消费者中同步更新；TUI 修改模型后走同一刷新
   路径并落到实际 LLM 调用参数；
4. Graph 内部动态 Top-K 恢复既有 3/50 默认（与用户 Top-K 3–20 是两个
   独立概念，名称/消费者明确区分）；
5. `EMBEDDING_MODEL_PATH` 与其他受管路径一样在 Settings 构造时完成 `~`
   展开与相对路径绝对化；调用期 CWD 改变后实际 loader 参数不漂移；
6. `.env` 修改 + reset 后 `MNEME_OFFLINE` 同样生效：离线缺模型时
   ModelScope 下载函数零调用。

测试方式：真实 fresh-process（subprocess，CWD=临时目录 + CWD `.env`，
受管变量与网关边界变量全部清洗）与进程内重置测试结合；全部使用 fake，
禁止真实 LLM/ModelScope/网络/主目录写入。
"""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# 子进程中必须清洗的变量（含 llm_gateway 边界变量，避免父进程环境泄漏）
_SCRUB_ENV = (
    "MNEME_DATA_DIR", "MNEME_DOCUMENT_ROOT", "MNEME_OFFLINE",
    "MNEME_ALLOW_INSECURE_HTTP",
    "MNEME_MAX_DOCUMENT_BYTES", "MNEME_MAX_PDF_PAGES",
    "MNEME_MAX_REMOTE_CONTEXT_CHARS",
    "LLM_MODEL", "LLM_TEMPERATURE", "LLM_TOP_K_MIN", "LLM_TOP_K_MAX",
    "ALPHA", "RAG_REFUSAL_THRESHOLD", "RAG_RERANKER", "RAG_RERANKER_MODEL",
    "RAG_REFUSAL_POLICY", "RAG_SELECTOR_MAX_PER_SOURCE", "RAG_WATCH_DIR",
    "EMBEDDING_MODEL_PATH", "EMBEDDING_MODEL_NAME",
    "API_KEY", "BASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL",
)

import src.config as _config

_BASELINE_CWD = Path.cwd()
_BASELINE_ENV = {key: os.environ.get(key) for key in _SCRUB_ENV}
_BASELINE_DOTENV = dict(_config._dotenv_values)


def _restore_config_test_state() -> None:
    os.chdir(_BASELINE_CWD)
    for key, value in _BASELINE_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    _config._dotenv_values.clear()
    _config._dotenv_values.update(_BASELINE_DOTENV)
    _config.reset_settings()


@pytest.fixture(autouse=True)
def _reset_settings():
    _restore_config_test_state()
    yield
    _restore_config_test_state()


def _run_in_cwd(code: str, cwd: Path, *, env: dict | None = None) -> subprocess.CompletedProcess:
    """真实 fresh-process：CWD=临时目录，PYTHONPATH=仓库根，变量已清洗。"""
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
# 1. LLM Gateway：无第二套 .env 加载语义，model/temperature 委托 Settings
# ═══════════════════════════════════════════════════════════════

class TestGatewayDelegation:
    def test_gateway_fresh_process_does_not_load_package_root_dotenv(
            self, tmp_path):
        """fresh-process：CWD=临时目录（无 .env）时，导入 gateway 不得
        把 package 根目录（仓库根）的 .env 注入进程环境。"""
        code = (
            "import json\n"
            "import os\n"
            "import src.llm_gateway  # noqa: F401\n"
            "from src.config import get_settings\n"
            "print(json.dumps({\n"
            "  'api_key_loaded': 'API_KEY' in os.environ,\n"
            "  'base_url_loaded': 'BASE_URL' in os.environ,\n"
            "  'llm_model_loaded': 'LLM_MODEL' in os.environ,\n"
            "  'model': get_settings().llm_model,\n"
            "  'temperature': get_settings().llm_temperature,\n"
            "}))\n"
        )
        result = _run_in_cwd(code, tmp_path)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout.strip())
        assert payload == {
            "api_key_loaded": False,
            "base_url_loaded": False,
            "llm_model_loaded": False,
            "model": "deepseek-chat",
            "temperature": 0.1,
        }

    def test_gateway_model_and_temperature_delegate_to_settings(
            self, monkeypatch):
        """进程内：llm_call 未显式传入时，model/temperature 从当前 Settings
        解析（env → reset_settings 契约模式），不再用硬编码默认。"""
        from src.llm_gateway import llm_call
        from src.config import reset_settings
        monkeypatch.setenv("LLM_MODEL", "model-from-env")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.66")
        # 测试隔离：显式使用安全 fake gateway 边界变量，不依赖真实
        # .env/凭据泄漏到进程环境。
        monkeypatch.setenv("API_KEY", "sk-fake-test")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        reset_settings()

        captured = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                fake_message = type("M", (), {"content": "ok"})()
                fake_choice = type("C", (), {"message": fake_message})()
                return type("R", (), {"choices": [fake_choice], "usage": None})()

        class FakeClient:
            chat = type("C2", (), {"completions": FakeCompletions()})()

        monkeypatch.setattr("src.llm_gateway._get_client",
                            lambda *a, **k: FakeClient())
        llm_call("t", [{"role": "user", "content": "x"}])
        assert captured["model"] == "model-from-env"
        assert captured["temperature"] == 0.66

    def test_gateway_defaults_without_env_come_from_settings(
            self, monkeypatch):
        """进程内：无任何 env 覆盖时，gateway 未显式传参也用 Settings 默认。"""
        from src.llm_gateway import llm_call
        from src.config import reset_settings
        for key in ("LLM_MODEL", "LLM_TEMPERATURE"):
            monkeypatch.delenv(key, raising=False)
        # 测试隔离：显式使用安全 fake gateway 边界变量。
        monkeypatch.setenv("API_KEY", "sk-fake-test")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        reset_settings()

        captured = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                fake_message = type("M", (), {"content": "ok"})()
                fake_choice = type("C", (), {"message": fake_message})()
                return type("R", (), {"choices": [fake_choice], "usage": None})()

        class FakeClient:
            chat = type("C2", (), {"completions": FakeCompletions()})()

        monkeypatch.setattr("src.llm_gateway._get_client",
                            lambda *a, **k: FakeClient())
        llm_call("t", [{"role": "user", "content": "x"}])
        assert captured["model"] == "deepseek-chat"
        assert captured["temperature"] == 0.1

    def test_gateway_source_has_no_own_dotenv_or_model_getenv(self):
        """契约：gateway 源码不得再 import dotenv、调用 load_dotenv()、
        或以 os.getenv("LLM_MODEL", ...) 绕过 Settings。"""
        import re
        source = (REPO_ROOT / "src" / "llm_gateway.py").read_text(encoding="utf-8")
        assert "from dotenv" not in source
        assert re.search(r"(?m)^load_dotenv\(", source) is None
        assert 'os.getenv("LLM_MODEL"' not in source


# ═══════════════════════════════════════════════════════════════
# 2. .env 与 reset 的真实契约（进程 env > CWD .env > 默认值）
# ═══════════════════════════════════════════════════════════════

class TestResetReflectsDotenv:
    def test_reset_reflects_dotenv_file_modification(self, tmp_path):
        """fresh-process：.env 修改后 reset_settings() 真实反映新值。"""
        _write_env(tmp_path, "LLM_MODEL=model-a\n")
        code = (
            "from src.config import get_settings, reset_settings\n"
            "print('FIRST:' + get_settings().llm_model)\n"
            "with open('.env', 'w', encoding='utf-8') as f:\n"
            "    f.write('LLM_MODEL=model-b\\n')\n"
            "reset_settings()\n"
            "print('SECOND:' + get_settings().llm_model)\n"
        )
        result = _run_in_cwd(code, tmp_path)
        assert result.returncode == 0, result.stderr
        assert "FIRST:model-a" in result.stdout
        assert "SECOND:model-b" in result.stdout

    def test_reset_keeps_explicit_process_env_and_refreshes_other_keys(
            self, tmp_path):
        """fresh-process：显式进程环境变量永远优先（不被 .env 修改覆盖），
        其余 .env 键随 reset 刷新。"""
        _write_env(tmp_path, "LLM_MODEL=model-a\nLLM_TEMPERATURE=0.91\n")
        code = (
            "from src.config import get_settings, reset_settings\n"
            "s = get_settings()\n"
            "print('FIRST:' + s.llm_model + '/' + str(s.llm_temperature))\n"
            "with open('.env', 'w', encoding='utf-8') as f:\n"
            "    f.write('LLM_MODEL=model-b\\nLLM_TEMPERATURE=0.77\\n')\n"
            "reset_settings()\n"
            "s = get_settings()\n"
            "print('SECOND:' + s.llm_model + '/' + str(s.llm_temperature))\n"
        )
        result = _run_in_cwd(code, tmp_path, env={"LLM_MODEL": "process-model"})
        assert result.returncode == 0, result.stderr
        assert "FIRST:process-model/0.91" in result.stdout
        assert "SECOND:process-model/0.77" in result.stdout

    def test_reset_clears_key_removed_from_dotenv(self, tmp_path):
        """fresh-process：从 .env 删除的键在 reset 后回落到默认值。"""
        _write_env(tmp_path, "LLM_MODEL=model-a\n")
        code = (
            "from src.config import get_settings, reset_settings\n"
            "print('FIRST:' + get_settings().llm_model)\n"
            "with open('.env', 'w', encoding='utf-8') as f:\n"
            "    f.write('# LLM_MODEL removed\\n')\n"
            "reset_settings()\n"
            "print('SECOND:' + get_settings().llm_model)\n"
        )
        result = _run_in_cwd(code, tmp_path)
        assert result.returncode == 0, result.stderr
        assert "FIRST:model-a" in result.stdout
        assert "SECOND:deepseek-chat" in result.stdout


# ═══════════════════════════════════════════════════════════════
# 3. reset 后消费者不持有过期副本；TUI 模型切换走同一刷新路径
# ═══════════════════════════════════════════════════════════════

class TestStaleConsumersRefreshed:
    def test_graph_rag_and_tui_service_have_no_stale_import_copies(self):
        """graph_rag/tui.service 不得再 by-value 导入 CHROMA_DB_PATH/
        EMBEDDING_MODEL_NAME 持有过期副本。"""
        import src.graph_rag as gr
        import tui.service as tsvc
        assert not hasattr(gr, "CHROMA_DB_PATH")
        assert not hasattr(gr, "EMBEDDING_MODEL_NAME")
        assert not hasattr(tsvc, "CHROMA_DB_PATH")

    def test_graph_call_time_resolution_tracks_reset(self, tmp_path):
        """fresh-process：Graph 的数据目录/embedding 在 .env 修改 + reset 后
        同步更新（调用期解析）。"""
        _write_env(tmp_path, (
            "MNEME_DATA_DIR=rel-data-a\n"
            "EMBEDDING_MODEL_PATH=rel-emb-a\n"
        ))
        code = (
            "import json\n"
            "import src.graph_rag as gr\n"
            "from src.config import reset_settings\n"
            "print(json.dumps([gr._graph_chroma_db_path(),\n"
            "                 gr._graph_embedding_model_name()]))\n"
            "with open('.env', 'w', encoding='utf-8') as f:\n"
            "    f.write('MNEME_DATA_DIR=rel-data-b\\n'\n"
            "            'EMBEDDING_MODEL_PATH=rel-emb-b\\n')\n"
            "reset_settings()\n"
            "print(json.dumps([gr._graph_chroma_db_path(),\n"
            "                 gr._graph_embedding_model_name()]))\n"
        )
        result = _run_in_cwd(code, tmp_path)
        assert result.returncode == 0, result.stderr
        lines = result.stdout.strip().splitlines()
        first = json.loads(lines[0])
        second = json.loads(lines[1])
        assert first == [
            str(tmp_path / "rel-data-a" / "chroma_db"),
            str(tmp_path / "rel-emb-a"),
        ]
        assert second == [
            str(tmp_path / "rel-data-b" / "chroma_db"),
            str(tmp_path / "rel-emb-b"),
        ]

    def test_tui_service_chroma_path_resolves_at_call_time(
            self, monkeypatch, tmp_path):
        """进程内：TUI service 的 Chroma 落点在 reset 后同步更新。"""
        from src.config import reset_settings
        from tui.service import LocalRagService
        monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data-a"))
        reset_settings()
        service = LocalRagService()
        assert service._chroma_db_path() == str(tmp_path / "data-a" / "chroma_db")
        monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data-b"))
        reset_settings()
        assert service._chroma_db_path() == str(tmp_path / "data-b" / "chroma_db")

    def test_security_resource_limits_refresh_after_reset(self, monkeypatch):
        """进程内：security 资源上限在 reset 后同步更新，不再停留旧值。"""
        import src.security as security
        from src.config import reset_settings
        monkeypatch.setenv("MNEME_MAX_DOCUMENT_BYTES", "11111")
        monkeypatch.setenv("MNEME_MAX_PDF_PAGES", "22")
        reset_settings()
        assert security.MAX_DOCUMENT_BYTES == 11111
        assert security.MAX_PDF_PAGES == 22
        monkeypatch.setenv("MNEME_MAX_DOCUMENT_BYTES", "22222")
        monkeypatch.setenv("MNEME_MAX_PDF_PAGES", "33")
        reset_settings()
        assert security.MAX_DOCUMENT_BYTES == 22222
        assert security.MAX_PDF_PAGES == 33

    def test_tui_model_switch_refreshes_and_reaches_llm_call(
            self, monkeypatch, tmp_path):
        """进程内：TUI /models 切换模型走 reset 刷新路径，实际 LLM 调用
        使用新模型。"""
        import src.rag as rag
        from src.config import get_settings, reset_settings
        from src.llm_gateway import llm_call as real_llm_call
        from rich.console import Console
        from tui.screens.chat import _switch_model

        monkeypatch.chdir(tmp_path)
        _write_env(tmp_path, "LLM_MODEL=old-model\n")
        reset_settings()
        assert get_settings().llm_model == "old-model"

        # 产品代码 _switch_model 直接写 os.environ（非 monkeypatch），
        # 显式保存/还原避免污染同进程后续测试。
        saved = os.environ.get("LLM_MODEL")
        try:
            console = Console(file=io.StringIO(), force_terminal=False)
            monkeypatch.setattr("tui.screens.chat.Prompt.ask",
                                lambda *a, **k: "new-model")
            _switch_model(console)
            assert get_settings().llm_model == "new-model"

            captured = {}

            def fake_llm_call(call_type, messages, model=None, temperature=None,
                              **kw):
                captured["model"] = model
                captured["temperature"] = temperature
                fake_message = type("M", (), {"content": "ok"})()
                fake_choice = type("C", (), {"message": fake_message})()
                return type("R", (), {"choices": [fake_choice]})(), None

            monkeypatch.setattr("src.llm_gateway.llm_call", fake_llm_call)
            rag.answer_with_llm_history("q", "ctx", [])
            assert captured["model"] == "new-model"
        finally:
            monkeypatch.setattr("src.llm_gateway.llm_call", real_llm_call)
            if saved is None:
                os.environ.pop("LLM_MODEL", None)
            else:
                os.environ["LLM_MODEL"] = saved
            from src.config import _dotenv_values
            if saved == "old-model":
                os.environ.pop("LLM_MODEL", None)
                _dotenv_values.pop("LLM_MODEL", None)

    def test_configure_settings_model_branch_refreshes(
            self, monkeypatch, tmp_path):
        """进程内：TUI /settings → LLM Model 分支同样走 reset 刷新路径。"""
        from src.config import get_settings, reset_settings
        from rich.console import Console
        from tui.screens.chat import _configure_settings

        monkeypatch.chdir(tmp_path)
        _write_env(tmp_path, "LLM_MODEL=old-model\n")
        reset_settings()
        assert get_settings().llm_model == "old-model"

        select_answers = iter(["llm_model", "exit"])

        class _FakeSelect:
            def __init__(self, *a, **k):
                pass

            def ask(self):
                return next(select_answers)

        class _FakeText:
            def __init__(self, *a, **k):
                pass

            def ask(self):
                return "cfg-model"

        monkeypatch.setattr("tui.screens.chat.questionary.select", _FakeSelect)
        monkeypatch.setattr("tui.screens.chat.questionary.text", _FakeText)
        console = Console(file=io.StringIO(), force_terminal=False)
        # 产品代码 _configure_settings 直接写 os.environ（非 monkeypatch），
        # 显式保存/还原避免污染同进程后续测试。
        saved = os.environ.get("LLM_MODEL")
        try:
            _configure_settings(console)
            assert get_settings().llm_model == "cfg-model"
        finally:
            # old-model 来自临时 .env，不应被恢复成跨测试的进程环境变量。
            if saved == "old-model":
                os.environ.pop("LLM_MODEL", None)
            elif saved is None:
                os.environ.pop("LLM_MODEL", None)
            else:
                os.environ["LLM_MODEL"] = saved
            # 测试写入的是临时 CWD 的 .env；清掉统一层注入值，避免
            # 后续测试把该临时值误识别为显式进程环境覆盖。
            from src.config import _dotenv_values
            _dotenv_values.pop("LLM_MODEL", None)


# ═══════════════════════════════════════════════════════════════
# 4. Graph 内部动态 Top-K 恢复 3/50；用户 Top-K 保持 3–20
# ═══════════════════════════════════════════════════════════════

class TestGraphTopKContract:
    def test_graph_internal_dynamic_top_k_restored_3_50(self, monkeypatch):
        """graph_rag_pipeline 的内部动态 Top-K 恢复既有固定 3/50。"""
        from src.graph_rag import graph_rag_pipeline

        captured = {}
        docs = ["d0", "d1", "d2"]
        metas = [
            {"chunk_id": "chunk_0", "source_id": "s0",
             "source_name": "a.md", "source": "a.md"},
        ]

        monkeypatch.setattr(
            "src.graph_rag.prepare_graph_index",
            lambda *a, **k: (object(), object(), object(), docs, metas, object()),
        )
        monkeypatch.setattr(
            "src.graph_rag.graph_augmented_retrieve",
            lambda query, model, collection, bm25, all_docs, kg, **kw:
            ([0, 1, 2], docs, [0.9, 0.8, 0.7]),
        )

        def fake_top_k(scores, min_k=None, max_k=None):
            captured["min_k"] = min_k
            captured["max_k"] = max_k
            return 3

        monkeypatch.setattr("src.graph_rag.dynamic_top_k", fake_top_k)
        monkeypatch.setattr("src.graph_rag.retrieval_refused",
                            lambda scores: False)
        monkeypatch.setattr("src.graph_rag.enrich_context",
                            lambda idx, docs, metas: docs)
        monkeypatch.setattr("src.graph_rag.compute_context_k", lambda cands: 1)
        monkeypatch.setattr("src.graph_rag._build_context",
                            lambda *a, **k: "CTX")
        monkeypatch.setattr("src.graph_rag.answer_with_llm_history",
                            lambda q, c, history=None, **kw: "A")
        monkeypatch.setattr("src.graph_rag.format_sources",
                            lambda *a, **k: "SRC")
        monkeypatch.setattr("src.citations.valid_citation_ids_for_context",
                            lambda *a, **k: [])
        monkeypatch.setattr("src.citations.format_citation_status_line",
                            lambda s: "")
        monkeypatch.setattr("src.rag.evaluate_answer_status",
                            lambda a, ids: "not_required")

        answer = graph_rag_pipeline(["f.md"], "q")
        assert answer == "A"
        assert captured == {"min_k": 3, "max_k": 50}

    def test_graph_user_stream_top_k_resolves_settings_range(self, monkeypatch):
        """graph_query_stream（用户路径）的 Top-K 仍从 Settings 用户区间
        （默认 3–20，可 env 覆盖）调用期解析。"""
        from src.config import reset_settings
        from src.graph_rag import graph_query_stream
        monkeypatch.setenv("LLM_TOP_K_MIN", "4")
        monkeypatch.setenv("LLM_TOP_K_MAX", "14")
        reset_settings()

        captured = {}
        docs = ["d0", "d1", "d2"]

        monkeypatch.setattr(
            "src.graph_rag.graph_augmented_retrieve",
            lambda query, model, collection, bm25, all_docs, kg, **kw:
            ([0, 1, 2], docs, [0.9, 0.8, 0.7]),
        )

        def fake_top_k(scores, min_k=None, max_k=None):
            captured["min_k"] = min_k
            captured["max_k"] = max_k
            return 3

        monkeypatch.setattr("src.graph_rag.dynamic_top_k", fake_top_k)
        monkeypatch.setattr("src.graph_rag.retrieval_refused",
                            lambda scores: False)
        monkeypatch.setattr("src.graph_rag.enrich_context",
                            lambda idx, docs, metas: docs)
        monkeypatch.setattr("src.graph_rag.compute_context_k", lambda cands: 1)
        monkeypatch.setattr("src.graph_rag._build_context",
                            lambda *a, **k: "CTX")
        monkeypatch.setattr("src.graph_rag.format_sources",
                            lambda *a, **k: "SRC")
        monkeypatch.setattr("src.graph_rag._record_query_metric",
                            lambda *a, **k: None)
        monkeypatch.setattr("src.citations.valid_citation_ids_for_context",
                            lambda *a, **k: [])
        monkeypatch.setattr(
            "src.graph_rag.answer_with_llm_history_stream",
            lambda q, c, h, **kw: iter(["chunk"]),
        )

        stream, sources = graph_query_stream(
            "q", None, None, None, docs, [], kg=object(), history=[],
        )
        list(stream)
        assert captured == {"min_k": 4, "max_k": 14}

    def test_graph_internal_and_user_ranges_are_distinct_names(self):
        """Graph 内部 3/50 与用户 Top-K 3–20 用不同常量名明确区分。"""
        from src.config import (
            GRAPH_DYNAMIC_MIN_K, GRAPH_DYNAMIC_MAX_K,
            DEFAULT_LLM_TOP_K_MIN, DEFAULT_LLM_TOP_K_MAX,
        )
        assert (GRAPH_DYNAMIC_MIN_K, GRAPH_DYNAMIC_MAX_K) == (3, 50)
        assert (DEFAULT_LLM_TOP_K_MIN, DEFAULT_LLM_TOP_K_MAX) == (3, 20)
        # 两者是不同概念：Graph 内部区间不随用户区间配置变化
        assert GRAPH_DYNAMIC_MAX_K != DEFAULT_LLM_TOP_K_MAX


# ═══════════════════════════════════════════════════════════════
# 5. EMBEDDING_MODEL_PATH：Settings 构造时解析，CWD 改变后不漂移
# ═══════════════════════════════════════════════════════════════

class TestEmbeddingModelPath:
    def test_embedding_model_path_absolutized_at_construction(
            self, monkeypatch, tmp_path):
        """进程内：相对 EMBEDDING_MODEL_PATH 在 Settings 构造时按启动目录
        绝对化；调用期 CWD 改变后不再漂移。"""
        from src.config import get_settings, reset_settings
        monkeypatch.setenv("EMBEDDING_MODEL_PATH", "rel/models/emb")
        monkeypatch.chdir(tmp_path)
        reset_settings()
        expected = str(tmp_path / "rel" / "models" / "emb")
        assert get_settings().embedding_model_name == expected

        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        assert get_settings().embedding_model_name == expected

    def test_embedding_model_path_tilde_expansion(self, monkeypatch, tmp_path):
        """进程内：EMBEDDING_MODEL_PATH 的 ~ 在构造时展开（跨平台）。"""
        from src.config import get_settings, reset_settings
        monkeypatch.setenv("EMBEDDING_MODEL_PATH", "~/models/emb")
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
        monkeypatch.setenv("USERPROFILE", str(tmp_path / "fakehome"))
        reset_settings()
        assert get_settings().embedding_model_name == \
            str(tmp_path / "fakehome" / "models" / "emb")

    def test_loader_param_stable_across_cwd_change(self, monkeypatch, tmp_path):
        """进程内：实际 loader 收到的参数在 CWD 改变前后一致（绝对路径）。"""
        import sys as _sys
        import src.rag as rag
        from src.config import get_settings, reset_settings
        monkeypatch.setenv("EMBEDDING_MODEL_PATH", "rel/models/emb")
        monkeypatch.chdir(tmp_path)
        reset_settings()

        captured = []

        class _FakeST:
            def __init__(self, name, *a, **k):
                captured.append(name)

        monkeypatch.setattr(rag, "SentenceTransformer", _FakeST)
        fake_modelscope = type("FakeModelScope", (), {})()
        fake_modelscope.snapshot_download = \
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("no download"))
        monkeypatch.setitem(_sys.modules, "modelscope", fake_modelscope)

        expected = str(tmp_path / "rel" / "models" / "emb")
        rag._load_sentence_transformer(get_settings().embedding_model_name)

        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        rag._load_sentence_transformer(get_settings().embedding_model_name)

        assert captured == [expected, expected]

    def test_embedding_model_path_dotenv_reset_refresh(self, tmp_path):
        """fresh-process：.env 的 EMBEDDING_MODEL_PATH 修改 + reset 后刷新，
        且始终为启动目录绝对化结果。"""
        _write_env(tmp_path, "EMBEDDING_MODEL_PATH=rel-emb-a\n")
        code = (
            "from src.config import get_settings, reset_settings\n"
            "print('FIRST:' + get_settings().embedding_model_name)\n"
            "with open('.env', 'w', encoding='utf-8') as f:\n"
            "    f.write('EMBEDDING_MODEL_PATH=rel-emb-b\\n')\n"
            "reset_settings()\n"
            "print('SECOND:' + get_settings().embedding_model_name)\n"
        )
        result = _run_in_cwd(code, tmp_path)
        assert result.returncode == 0, result.stderr
        assert "FIRST:" + str(tmp_path / "rel-emb-a") in result.stdout
        assert "SECOND:" + str(tmp_path / "rel-emb-b") in result.stdout


# ═══════════════════════════════════════════════════════════════
# 6. .env 修改 + reset 后 MNEME_OFFLINE 生效：ModelScope 零调用
# ═══════════════════════════════════════════════════════════════

class TestOfflineReset:
    def test_dotenv_offline_flip_via_reset_blocks_modelscope(self, tmp_path):
        """fresh-process：.env 中 MNEME_OFFLINE 0→1 修改 + reset 后，
        离线缺模型时 ModelScope 下载函数零调用。"""
        _write_env(tmp_path, "MNEME_OFFLINE=0\nMNEME_DATA_DIR=rel-data\n")
        code = (
            "import sys, types\n"
            "import src.rag as rag\n"
            "from src.config import reset_settings\n"
            "with open('.env', 'a', encoding='utf-8') as f:\n"
            "    f.write('MNEME_OFFLINE=1\\n')\n"
            "reset_settings()\n"
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
