"""Phase C / 计划 3.2 第三轮返工契约测试（TDD）。

锁定独立验收第三轮复现的配置契约缺口：
1. `src/rag_query_decomposer.py` / `src/rag_query_rewriter.py` 不得自行
   `load_dotenv()`——导入它们不得把 package-root `.env` 注入进程环境
   （`.env` 仅由 `src.config` 统一加载；API key / Base URL 仍属 gateway
   边界）；
2. 两模块的受管 `model`/`temperature` 改为调用期从 Settings 解析的兼容
   写法：显式参数仍优先，未传时使用统一配置（不再有未说明的
   `deepseek-chat`/`0.0` 默认分叉）；
3. `src.rag._plan_query_runtime()` 同时解析并传递 `llm_model` 与
   `llm_temperature` 给 rewrite/decompose：`LLM_TEMPERATURE=0.66` 经真实
   planning 路径到达 fake gateway 时值仍为 0.66。

测试方式：真实 fresh-process（CWD=系统 temp + 变量清洗）与进程内重置测试
结合；全部使用 fake（fake API_KEY/BASE_URL + fake gateway + fake 检索），
禁止真实 LLM/网络/ModelScope/主目录写入。
"""

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

_FAKE_BOUNDARY = {"API_KEY": "sk-fake-test", "BASE_URL": "https://fake.test/v1"}

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
    from src.config import reset_settings
    reset_settings()
    yield
    reset_settings()


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


def _patch_fake_gateway(monkeypatch, returns: dict):
    """fake llm_call_safe：按 call_type 返回确定性内容并捕获 (call_type,
    model, temperature)。"""
    captured = []

    def fake_safe(call_type, messages, model=None, temperature=None, **kw):
        captured.append((call_type, model, temperature))
        return returns[call_type], SimpleNamespace(retries_used=0)

    monkeypatch.setattr("src.llm_gateway.llm_call_safe", fake_safe)
    return captured


def _patch_fake_retrieve(monkeypatch):
    monkeypatch.setattr(
        "src.rag.retrieve_hybrid_with_sources",
        lambda sq, model, collection, bm25, documents, metadatas, **kw:
        ([0], ["d0 文本"], [0.9]),
    )


# ═══════════════════════════════════════════════════════════════
# 1. 唯一 .env 入口：导入 rewrite/decompose 不得加载 package-root .env
# ═══════════════════════════════════════════════════════════════

class TestNoSecondDotenvEntry:
    def test_import_rewrite_decompose_does_not_inject_package_dotenv(
            self, tmp_path):
        """fresh-process：CWD=临时目录（无 .env）时，导入两模块不得把
        package 根目录（仓库根）的 .env 注入进程环境。"""
        code = (
            "import json\n"
            "import os\n"
            "import src.rag_query_rewriter  # noqa: F401\n"
            "import src.rag_query_decomposer  # noqa: F401\n"
            "print(json.dumps({\n"
            "  'api_key': 'API_KEY' in os.environ,\n"
            "  'base_url': 'BASE_URL' in os.environ,\n"
            "  'llm_model': 'LLM_MODEL' in os.environ,\n"
            "}))\n"
        )
        result = _run_in_cwd(code, tmp_path)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout.strip()) == {
            "api_key": False,
            "base_url": False,
            "llm_model": False,
        }

    def test_planner_modules_have_no_load_dotenv(self):
        """契约：两模块源码不得再 import/调用 load_dotenv。"""
        for name in ("rag_query_decomposer", "rag_query_rewriter"):
            source = (REPO_ROOT / "src" / f"{name}.py").read_text(
                encoding="utf-8",
            )
            assert "load_dotenv" not in source, name


# ═══════════════════════════════════════════════════════════════
# 2. 真实 planning 路径：llm_model 与 llm_temperature 同时传递
# ═══════════════════════════════════════════════════════════════

class TestPlanningPassesManagedParams:
    def test_settings_temperature_reaches_fake_gateway_via_planning(
            self, monkeypatch):
        """进程内：LLM_TEMPERATURE=0.66 经真实 _plan_query_runtime 到达
        fake rewrite/decompose gateway，值仍为 0.66（model 同源）。"""
        import src.rag as rag
        from src.config import reset_settings
        monkeypatch.setenv("LLM_MODEL", "model-plan")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.66")
        monkeypatch.setenv("API_KEY", _FAKE_BOUNDARY["API_KEY"])
        monkeypatch.setenv("BASE_URL", _FAKE_BOUNDARY["BASE_URL"])
        reset_settings()
        captured = _patch_fake_gateway(monkeypatch, {
            "rewrite": "它的作者和贡献分别是什么？",
            "decompose": '["它的作者分别是谁？","它的贡献有哪些？"]',
        })
        _patch_fake_retrieve(monkeypatch)

        runtime = rag._plan_query_runtime(
            "它的作者和贡献分别是什么？",
            None, None, None, DOCS, METAS,
            history=[("X是什么？", "X是...")],
        )
        assert ("rewrite", "model-plan", 0.66) in captured
        assert ("decompose", "model-plan", 0.66) in captured
        assert runtime.rewrite_stage is not None
        assert runtime.decompose_stage is not None

    def test_wrapper_defaults_delegate_to_settings(self, monkeypatch):
        """进程内：未传参时两模块包装函数从 Settings 解析 model/temperature。"""
        from src.config import reset_settings
        from src.rag_query_decomposer import decompose_query_llm
        from src.rag_query_rewriter import rewrite_query_llm
        monkeypatch.setenv("LLM_MODEL", "model-dflt")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.66")
        monkeypatch.setenv("API_KEY", _FAKE_BOUNDARY["API_KEY"])
        monkeypatch.setenv("BASE_URL", _FAKE_BOUNDARY["BASE_URL"])
        reset_settings()
        captured = _patch_fake_gateway(monkeypatch, {
            "rewrite": "它的作者是谁？",
            "decompose": '["作者属于什么学校？"]',
        })

        rewrite_query_llm(
            "它的作者是谁？", history=[("X是什么？", "X是...")],
        )
        decompose_query_llm("LLMs for mobility这篇文章的作者？")
        assert ("rewrite", "model-dflt", 0.66) in captured
        assert ("decompose", "model-dflt", 0.66) in captured

    def test_explicit_params_win_over_settings(self, monkeypatch):
        """进程内：显式 model/temperature 优先于 Settings（兼容写法）。"""
        from src.config import reset_settings
        from src.rag_query_decomposer import decompose_query_llm
        from src.rag_query_rewriter import rewrite_query_llm
        monkeypatch.setenv("LLM_MODEL", "model-settings")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.66")
        monkeypatch.setenv("API_KEY", _FAKE_BOUNDARY["API_KEY"])
        monkeypatch.setenv("BASE_URL", _FAKE_BOUNDARY["BASE_URL"])
        reset_settings()
        captured = _patch_fake_gateway(monkeypatch, {
            "rewrite": "它的作者是谁？",
            "decompose": '["作者属于什么学校？"]',
        })

        rewrite_query_llm(
            "它的作者是谁？", history=[("X是什么？", "X是...")],
            model="explicit-model", temperature=0.42,
        )
        decompose_query_llm(
            "LLMs for mobility这篇文章的作者？",
            model="explicit-model", temperature=0.42,
        )
        assert ("rewrite", "explicit-model", 0.42) in captured
        assert ("decompose", "explicit-model", 0.42) in captured

    def test_planning_explicit_llm_model_still_wins(self, monkeypatch):
        """进程内：_plan_query_runtime 显式 llm_model 优先，temperature
        仍从 Settings 解析并传递。"""
        import src.rag as rag
        from src.config import reset_settings
        monkeypatch.setenv("LLM_MODEL", "model-settings")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.66")
        monkeypatch.setenv("API_KEY", _FAKE_BOUNDARY["API_KEY"])
        monkeypatch.setenv("BASE_URL", _FAKE_BOUNDARY["BASE_URL"])
        reset_settings()
        captured = _patch_fake_gateway(monkeypatch, {
            "rewrite": "它的作者和贡献分别是什么？",
            "decompose": '["A","B"]',
        })
        _patch_fake_retrieve(monkeypatch)

        rag._plan_query_runtime(
            "它的作者和贡献分别是什么？",
            None, None, None, DOCS, METAS,
            history=[("X是什么？", "X是...")],
            llm_model="explicit-plan-model",
        )
        assert ("rewrite", "explicit-plan-model", 0.66) in captured
        assert ("decompose", "explicit-plan-model", 0.66) in captured
