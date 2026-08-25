"""Phase C / 计划 3.2 第四轮返工契约测试（TDD）。

锁定独立验收第四轮复现的两个配置契约缺陷：
A. 显式 `temperature` 未贯穿查询规划：
   - `src.rag._plan_query_runtime()` 必须支持可选 `llm_temperature`
     参数（None 时调用期回退 Settings.llm_temperature）；
   - `prepare_answer_evidence()` 向规划器转发该值；
   - `answer_query()` / `answer_query_stream()` 把各自已解析的显式温度
     传入规划路径——Settings 0.10、调用者传 0.66 时，fake
     planner/rewrite/decompose/gateway 观察到 0.66；
   - 未显式传温度时，规划器仍使用当前 Settings 值（回退行为不变）。
B. TUI 温度范围与 Settings/文档一致（0.0–2.0）：
   - 合法输入 1.5 原样写入并立即生效（reset_settings）；
   - >2 / <0 / 非数字：不写入 .env、不 reset Settings、有可观察错误，
     不得静默 clamp。

全部测试使用系统 temp、fake API_KEY/BASE_URL、fake/fail-fast gateway 与
检索入口，禁止真实 LLM/网络/密钥/主目录写入。
"""

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

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

DOCS = ["d0 文本", "d1 文本", "d2 文本"]
METAS = [
    {"chunk_id": "chunk_0", "source_id": "s0", "source_name": "a.md",
     "source": "a.md"},
    {"chunk_id": "chunk_1", "source_id": "s1", "source_name": "b.md",
     "source": "b.md"},
    {"chunk_id": "chunk_2", "source_id": "s2", "source_name": "c.md",
     "source": "c.md"},
]


@pytest.fixture(autouse=True)
def _reset_settings():
    _restore_config_test_state()
    yield
    _restore_config_test_state()


def _run_in_cwd(code: str, cwd: Path, *, env: dict | None = None) -> subprocess.CompletedProcess:
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


def _patch_gateway_and_retrieve(monkeypatch):
    """fake llm_call_safe（捕获 rewrite/decompose 的 model/temperature）+
    fake 检索。返回 captured 列表。"""
    captured = []

    def fake_safe(call_type, messages, model=None, temperature=None, **kw):
        captured.append((call_type, model, temperature))
        content = (
            "它的作者和贡献分别是什么？" if call_type == "rewrite"
            else '["A","B"]'
        )
        return content, SimpleNamespace(retries_used=0)

    monkeypatch.setattr("src.llm_gateway.llm_call_safe", fake_safe)
    monkeypatch.setattr(
        "src.rag.retrieve_hybrid_with_sources",
        lambda sq, model, collection, bm25, documents, metadatas, **kw:
        ([0], ["d0 文本"], [0.9]),
    )
    return captured


def _patch_answer_downstream(monkeypatch):
    """把 answer 生成的确定性下游 helper 换成 fake（规划路径保持真实）。"""
    import src.rag as rag
    monkeypatch.setattr(rag, "_record_query_metric", lambda *a, **k: None)
    monkeypatch.setattr(rag, "answer_with_llm_history",
                        lambda q, c, history=None, **kw: "ok")
    monkeypatch.setattr(rag, "enrich_context", lambda idx, docs, metas: docs)
    monkeypatch.setattr(rag, "compute_context_k", lambda cands: 1)
    monkeypatch.setattr(rag, "expand_with_parent",
                        lambda idx, docs, metas, ctx: (idx, docs))
    monkeypatch.setattr(rag, "expand_with_adjacent", lambda idx, metas, **kw: idx)
    monkeypatch.setattr(rag, "_build_context", lambda *a, **k: "CTX")
    monkeypatch.setattr(rag, "format_sources", lambda *a, **k: "SRC")
    monkeypatch.setattr(rag, "_validate_and_repair_citations",
                        lambda a, ti, ed, m, ck: (a, None))


# ═══════════════════════════════════════════════════════════════
# A. 显式 temperature 贯穿查询规划
# ═══════════════════════════════════════════════════════════════

class TestExplicitTemperatureThroughPlanning:
    def test_answer_query_passes_explicit_temperature_to_planning(
            self, monkeypatch):
        """同步入口：Settings 温度 0.10、显式 0.66 → 真实规划路径的
        fake rewrite/decompose gateway 观察到 0.66。"""
        import src.rag as rag
        from src.config import reset_settings
        monkeypatch.setenv("LLM_MODEL", "model-plan")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.10")
        monkeypatch.setenv("API_KEY", "sk-fake-test")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        reset_settings()

        captured = _patch_gateway_and_retrieve(monkeypatch)
        _patch_answer_downstream(monkeypatch)

        answer, _ = rag.answer_query(
            "它的作者和贡献分别是什么？", None, None, None, DOCS, METAS,
            history=[("X是什么？", "X是...")], temperature=0.66,
        )
        assert answer == "ok"
        assert ("rewrite", "model-plan", 0.66) in captured
        assert ("decompose", "model-plan", 0.66) in captured

    def test_answer_query_stream_passes_explicit_temperature_to_planning(
            self, monkeypatch):
        """流式入口：Settings 温度 0.10、显式 0.66 → fake gateway 观察到
        0.66。"""
        import src.rag as rag
        from src.config import reset_settings
        monkeypatch.setenv("LLM_MODEL", "model-plan")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.10")
        monkeypatch.setenv("API_KEY", "sk-fake-test")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        reset_settings()

        captured = _patch_gateway_and_retrieve(monkeypatch)
        _patch_answer_downstream(monkeypatch)

        def fake_stream(q, context, history=None, **kw):
            yield "chunk"

        monkeypatch.setattr(rag, "answer_with_llm_history_stream", fake_stream)
        monkeypatch.setattr(
            "src.citations.valid_citation_ids_for_context", lambda *a, **k: [],
        )

        stream, _ = rag.answer_query_stream(
            "它的作者和贡献分别是什么？", None, None, None, DOCS, METAS,
            history=[("X是什么？", "X是...")], temperature=0.66,
        )
        list(stream)
        assert ("rewrite", "model-plan", 0.66) in captured
        assert ("decompose", "model-plan", 0.66) in captured

    def test_planning_settings_fallback_when_no_explicit_temperature(
            self, monkeypatch):
        """未显式传温度：规划器仍使用当前 Settings 值（回退行为不变）。"""
        import src.rag as rag
        from src.config import reset_settings
        monkeypatch.setenv("LLM_TEMPERATURE", "0.10")
        monkeypatch.setenv("API_KEY", "sk-fake-test")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        reset_settings()

        captured = _patch_gateway_and_retrieve(monkeypatch)
        rag._plan_query_runtime(
            "它的作者和贡献分别是什么？", None, None, None, DOCS, METAS,
            history=[("X是什么？", "X是...")],
        )
        assert ("rewrite", "deepseek-chat", 0.10) in captured
        assert ("decompose", "deepseek-chat", 0.10) in captured

    def test_planning_explicit_temperature_wins(self, monkeypatch):
        """规划器显式 llm_temperature 优先于 Settings。"""
        import src.rag as rag
        from src.config import reset_settings
        monkeypatch.setenv("LLM_TEMPERATURE", "0.10")
        monkeypatch.setenv("API_KEY", "sk-fake-test")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        reset_settings()

        captured = _patch_gateway_and_retrieve(monkeypatch)
        rag._plan_query_runtime(
            "它的作者和贡献分别是什么？", None, None, None, DOCS, METAS,
            history=[("X是什么？", "X是...")], llm_temperature=0.66,
        )
        assert ("rewrite", "deepseek-chat", 0.66) in captured
        assert ("decompose", "deepseek-chat", 0.66) in captured

    def test_prepare_answer_evidence_forwards_temperature(self, monkeypatch):
        """prepare_answer_evidence 把 llm_temperature 转发给规划器。"""
        import src.rag as rag
        captured = {}

        def fake_plan(query, model, collection, bm25, documents, metadatas,
                      history=None, retrieval_k=None, llm_model=None,
                      llm_temperature=None, planning_profile="sync"):
            captured["llm_temperature"] = llm_temperature
            return SimpleNamespace(
                rewritten_query=query, rewrite_log={"changed": False},
                sub_queries=[query], best_score={0: 0.9}, merged=[0],
                scores_flat=[0.9], planning_profile="sync", retrieval_k=None,
                rewrite_stage=None, decompose_stage=None,
            )

        monkeypatch.setattr(rag, "_plan_query_runtime", fake_plan)
        _patch_answer_downstream(monkeypatch)

        rag.prepare_answer_evidence(
            "q", None, None, None, DOCS, METAS, history=None,
            llm_temperature=0.66,
        )
        assert captured["llm_temperature"] == 0.66

    def test_fresh_process_explicit_temperature_beats_cwd_dotenv(
            self, tmp_path):
        """fresh-process：CWD `.env` LLM_TEMPERATURE=0.91、显式传 0.66 →
        规划路径 fake gateway 收到 0.66（显式优先）。"""
        (tmp_path / ".env").write_text(
            "LLM_TEMPERATURE=0.91\n", encoding="utf-8",
        )
        code = (
            "import json, os\n"
            "import src.rag as rag\n"
            "import src.llm_gateway as gw\n"
            "from src.config import get_settings\n"
            "os.environ['API_KEY'] = 'sk-fake-test'\n"
            "os.environ['BASE_URL'] = 'https://fake.test/v1'\n"
            "captured = []\n"
            "def fake_safe(call_type, messages, model=None, temperature=None, **kw):\n"
            "    captured.append((call_type, temperature))\n"
            "    content = ('它的作者和贡献分别是什么？' if call_type == 'rewrite'\n"
            "               else '[\"A\",\"B\"]')\n"
            "    return content, type('R', (), {'retries_used': 0})()\n"
            "gw.llm_call_safe = fake_safe\n"
            "rag.retrieve_hybrid_with_sources = (\n"
            "    lambda sq, model, collection, bm25, documents, metadatas, **kw:\n"
            "    ([0], ['d'], [0.9]))\n"
            "rag._plan_query_runtime(\n"
            "    '它的作者和贡献分别是什么？', None, None, None, ['d'],\n"
            "    [{'chunk_id': 'c0', 'source_id': 's0', 'source_name': 'a.md',\n"
            "      'source': 'a.md'}],\n"
            "    history=[('X是什么？', 'X是...')], llm_temperature=0.66)\n"
            "print(json.dumps({\n"
            "  'rewrite': [t for c, t in captured if c == 'rewrite'],\n"
            "  'decompose': [t for c, t in captured if c == 'decompose'],\n"
            "  'settings': get_settings().llm_temperature,\n"
            "}))\n"
        )
        result = _run_in_cwd(code, tmp_path)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout.strip())
        assert payload["rewrite"] == [0.66]
        assert payload["decompose"] == [0.66]
        assert payload["settings"] == 0.91

    def test_fresh_process_planning_uses_cwd_dotenv_temperature(
            self, tmp_path):
        """fresh-process：未显式传温度时，规划路径使用 CWD `.env` 温度。"""
        (tmp_path / ".env").write_text(
            "LLM_TEMPERATURE=0.91\n", encoding="utf-8",
        )
        code = (
            "import json, os\n"
            "import src.rag as rag\n"
            "import src.llm_gateway as gw\n"
            "os.environ['API_KEY'] = 'sk-fake-test'\n"
            "os.environ['BASE_URL'] = 'https://fake.test/v1'\n"
            "captured = []\n"
            "def fake_safe(call_type, messages, model=None, temperature=None, **kw):\n"
            "    captured.append((call_type, temperature))\n"
            "    content = ('它的作者和贡献分别是什么？' if call_type == 'rewrite'\n"
            "               else '[\"A\",\"B\"]')\n"
            "    return content, type('R', (), {'retries_used': 0})()\n"
            "gw.llm_call_safe = fake_safe\n"
            "rag.retrieve_hybrid_with_sources = (\n"
            "    lambda sq, model, collection, bm25, documents, metadatas, **kw:\n"
            "    ([0], ['d'], [0.9]))\n"
            "rag._plan_query_runtime(\n"
            "    '它的作者和贡献分别是什么？', None, None, None, ['d'],\n"
            "    [{'chunk_id': 'c0', 'source_id': 's0', 'source_name': 'a.md',\n"
            "      'source': 'a.md'}],\n"
            "    history=[('X是什么？', 'X是...')])\n"
            "print(json.dumps([t for c, t in captured]))\n"
        )
        result = _run_in_cwd(code, tmp_path)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout.strip()) == [0.91, 0.91]


# ═══════════════════════════════════════════════════════════════
# B. TUI 温度范围 0.0–2.0：合法值保真，非法值拒绝且不写不重置
# ═══════════════════════════════════════════════════════════════

class TestTuiTemperatureRange:
    def _setup(self, monkeypatch, tmp_path, initial: str):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            f"LLM_TEMPERATURE={initial}\n", encoding="utf-8",
        )
        from src.config import reset_settings
        reset_settings()
        select_answers = iter(["temperature", "exit"])

        class _FakeSelect:
            def __init__(self, *a, **k):
                pass

            def ask(self):
                return next(select_answers)

        monkeypatch.setattr("tui.screens.chat.questionary.select", _FakeSelect)
        return os.environ.get("LLM_TEMPERATURE")

    def _restore(self, saved):
        if saved is None:
            os.environ.pop("LLM_TEMPERATURE", None)
        else:
            os.environ["LLM_TEMPERATURE"] = saved

    def test_tui_temperature_1_5_preserved_and_applied(
            self, monkeypatch, tmp_path):
        """合法输入 1.5 原样写入 .env 并立即生效（不再 clamp 为 1.0）。"""
        saved = self._setup(monkeypatch, tmp_path, "0.5")
        from src.config import get_settings
        from rich.console import Console
        from tui.screens.chat import _configure_settings, _read_env

        class _FakeText:
            def __init__(self, *a, **k):
                pass

            def ask(self):
                return "1.5"

        monkeypatch.setattr("tui.screens.chat.questionary.text", _FakeText)
        output = io.StringIO()
        console = Console(file=output, force_terminal=False)
        try:
            _configure_settings(console)
            assert _read_env("LLM_TEMPERATURE") == "1.5"
            assert os.environ.get("LLM_TEMPERATURE") == "1.5"
            assert get_settings().llm_temperature == 1.5
        finally:
            self._restore(saved)

    @pytest.mark.parametrize("bad", ["2.5", "-1", "hot"])
    def test_tui_temperature_invalid_rejected_no_write_no_reset(
            self, monkeypatch, tmp_path, bad):
        """>2 / <0 / 非数字：显示明确错误，不写入 .env、不重置 Settings、
        不静默 clamp。"""
        saved = self._setup(monkeypatch, tmp_path, "0.5")
        from src.config import get_settings
        from rich.console import Console
        from tui.screens.chat import _configure_settings, _read_env

        class _FakeText:
            def __init__(self, *a, **k):
                pass

            def ask(self):
                return bad

        monkeypatch.setattr("tui.screens.chat.questionary.text", _FakeText)
        output = io.StringIO()
        console = Console(file=output, force_terminal=False)
        try:
            _configure_settings(console)
            # 不写入、不重置：.env 与 Settings 保持原值
            assert _read_env("LLM_TEMPERATURE") == "0.5"
            assert os.environ.get("LLM_TEMPERATURE") == "0.5"
            assert get_settings().llm_temperature == 0.5
            # 有可观察错误
            assert "非法" in output.getvalue()
        finally:
            self._restore(saved)
