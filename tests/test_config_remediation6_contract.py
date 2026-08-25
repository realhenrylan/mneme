"""Phase C / 计划 3.2 第六轮返工契约测试（TDD）。

锁定独立验收第六轮复现的配置契约绕过：

A. 用户 Top-K 范围容器绕过：`answer_query_stream(top_k_range=(3,20,999))`
   只验证前两个元素随后进入 RAG planner；`graph_query_stream` 同样进入
   retrieval；`top_k_range=(3,)` 抛 IndexError 而非带配置名的 fail-fast。
   RAG/Graph 流式入口必须只接受恰好两个整数的序列（1 <= min <= max）；
   `(3,20,999)` / `(3,)` / 非序列 / 布尔值 / 浮点值均须在 planner/retrieval
   前抛含 `LLM_TOP_K_MIN` 或 `LLM_TOP_K_MAX` 的 ValueError，且调用数均为 0。
B. 显式 alpha 绕过 Settings 校验：`graph_rag_pipeline(alpha=2.0)` 曾进入
   `prepare_graph_index()` 写路径；`graph_query_stream(alpha=nan)` 曾进入
   retrieval；`cli_loop._graph_rag_answer(alpha=2.0)` 曾进入 retrieval。
   ALPHA 仅接受有限、非布尔数值且 0.0 <= v <= 1.0，错误信息必须包含
   `ALPHA`，且在索引构建/检索之前失败（0 调用）。
C. 直接 gateway 绕过温度校验：`llm_gateway.llm_call(temperature=2.5)` 曾
   调用 fake client。最终 temperature（显式或 Settings 解析）必须在
   `_get_client()`/网络之前通过统一校验；`llm_call_safe` 非法温度也必须
   零 client/零网络。温度拒绝 True/False、NaN、inf、非数字与越界值；
   合法字符串数值保留（有测试说明）。
D. 布尔值不作为合法温度：`validate_llm_temperature(True)` 曾返回 1.0。

同时锁定合法路径：`temperature=0.66`（gateway 透传）、`alpha=0.7`、
`top_k_range=(3,20)`（Graph 流式动态 Top-K 仍收到 3/20，与 Graph 内部
3/50 分离）行为不变。

全部测试使用系统 temp、fake API_KEY/BASE_URL、fake/fail-fast gateway 与
检索入口（修复前代码若通过校验继续执行，也会在任何真实 LLM/网络之前被
fake 下游拦截）；fresh-process 用例在无 `.env` 的临时 CWD 中运行并清洗
全部受管环境变量，禁止真实 LLM/网络/密钥/主目录写入。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

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

DOCS = ["d0 文本", "d1 文本", "d2 文本"]
METAS = [
    {"chunk_id": "chunk_0", "source_id": "s0", "source_name": "a.md",
     "source": "a.md"},
    {"chunk_id": "chunk_1", "source_id": "s1", "source_name": "b.md",
     "source": "b.md"},
    {"chunk_id": "chunk_2", "source_id": "s2", "source_name": "c.md",
     "source": "c.md"},
]

# 非法 Top-K 范围容器：长度错误 / 长度不足 / 非序列 / 布尔 / 浮点元素
BAD_TOP_K_CONTAINERS = [
    (3, 20, 999),
    (3,),
    5,
    True,
    (3.0, 20),
]


@pytest.fixture(autouse=True)
def _reset_settings():
    from src.config import reset_settings
    reset_settings()
    yield
    reset_settings()


def _run_in_cwd(code: str, cwd: Path) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    for key in _SCRUB_ENV:
        full_env.pop(key, None)
    full_env.pop("PYTHONPATH", None)
    full_env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=str(cwd), env=full_env,
        timeout=300,
    )


def _patch_rag_counters(monkeypatch):
    """fake RAG planner gateway（计数）+ fake 检索（计数）+ fake 生成
    gateway（计数）+ 纯下游替换。修复前代码若通过校验继续执行也会被
    fake 下游拦截，绝不触达真实 LLM/网络。"""
    import src.rag as rag
    counters = {"rewrite": 0, "decompose": 0, "retrieve": 0, "gateway": 0}

    def fake_safe(call_type, messages, model=None, temperature=None, **kw):
        counters["rewrite" if call_type == "rewrite" else "decompose"] += 1
        content = (
            "它的作者和贡献分别是什么？" if call_type == "rewrite"
            else '["A","B"]'
        )
        return content, type("R", (), {"retries_used": 0})()

    def fake_retrieve(sq, model, collection, bm25, documents, metadatas, **kw):
        counters["retrieve"] += 1
        return ([0], ["d0 文本"], [0.9])

    def fake_answer(q, context, history=None, **kw):
        counters["gateway"] += 1
        return "ok"

    def fake_stream(q, context, history=None, **kw):
        counters["gateway"] += 1
        yield "chunk"

    monkeypatch.setattr("src.llm_gateway.llm_call_safe", fake_safe)
    monkeypatch.setattr(rag, "retrieve_hybrid_with_sources", fake_retrieve)
    monkeypatch.setattr(rag, "answer_with_llm_history", fake_answer)
    monkeypatch.setattr(rag, "answer_with_llm_history_stream", fake_stream)
    monkeypatch.setattr(rag, "_record_query_metric", lambda *a, **k: None)
    monkeypatch.setattr(rag, "enrich_context", lambda idx, docs, metas: docs)
    monkeypatch.setattr(rag, "compute_context_k", lambda cands: 1)
    monkeypatch.setattr(
        rag, "expand_with_parent", lambda idx, docs, metas, ctx: (idx, docs))
    monkeypatch.setattr(
        rag, "expand_with_adjacent", lambda idx, metas, **kw: idx)
    monkeypatch.setattr(rag, "_build_context", lambda *a, **k: "CTX")
    monkeypatch.setattr(rag, "format_sources", lambda *a, **k: "SRC")
    monkeypatch.setattr(
        rag, "_validate_and_repair_citations",
        lambda a, ti, ed, m, ck: (a, None))
    monkeypatch.setattr(
        "src.citations.valid_citation_ids_for_context", lambda *a, **k: [])
    return counters


def _assert_zero_calls(counters):
    assert counters == {"rewrite": 0, "decompose": 0, "retrieve": 0,
                        "gateway": 0}


def _patch_graph_downstream(monkeypatch):
    """fake Graph 下游（graph_rag 模块属性 + cli_loop 函数内导入的
    src.rag/src.domain/src.citations 模块属性）。修复前代码若通过校验
    继续执行也会被 fake 下游拦截，绝不触达真实 LLM/网络。"""
    monkeypatch.setattr("src.graph_rag.dynamic_top_k",
                        lambda scores, min_k=None, max_k=None: 1)
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
    monkeypatch.setattr("src.graph_rag.answer_with_llm_history",
                        lambda q, c, history=None, **kw: "A")
    monkeypatch.setattr("src.graph_rag.answer_with_llm_history_stream",
                        lambda q, c, h, **kw: iter(["chunk"]))
    monkeypatch.setattr("src.citations.valid_citation_ids_for_context",
                        lambda *a, **k: [])
    monkeypatch.setattr("src.citations.format_citation_status_line",
                        lambda s: "")
    monkeypatch.setattr("src.rag.evaluate_answer_status",
                        lambda a, ids: "not_required")
    # cli_loop._graph_rag_answer 在函数内从 src.rag/src.domain 导入
    monkeypatch.setattr("src.rag.dynamic_top_k",
                        lambda scores, min_k=None, max_k=None: 1)
    monkeypatch.setattr("src.rag.enrich_context",
                        lambda idx, docs, metas: docs)
    monkeypatch.setattr("src.domain.compute_context_k", lambda cands: 1)
    monkeypatch.setattr("src.rag._build_context", lambda *a, **k: "CTX")
    monkeypatch.setattr("src.rag.answer_with_llm_history",
                        lambda q, c, history=None, **kw: "A")
    monkeypatch.setattr("src.rag.format_sources", lambda *a, **k: "SRC")


# ═══════════════════════════════════════════════════════════════
# A. 用户 Top-K 范围容器 fail-fast（RAG 与 Graph 流式入口）
# ═══════════════════════════════════════════════════════════════

class TestUserTopKContainerFailFast:
    @pytest.mark.parametrize("bad", BAD_TOP_K_CONTAINERS)
    def test_answer_query_stream_rejects_bad_container_before_planner(
            self, monkeypatch, bad):
        """RAG 流式入口：非法容器 → 含配置名的 ValueError，
        planner/retrieval/gateway 均 0 次调用（未下标、未计算 max）。"""
        import src.rag as rag
        counters = _patch_rag_counters(monkeypatch)
        with pytest.raises(ValueError) as exc_info:
            rag.answer_query_stream(
                "q", None, None, None, DOCS, METAS, top_k_range=bad,
            )
        msg = str(exc_info.value)
        assert "LLM_TOP_K_MIN" in msg or "LLM_TOP_K_MAX" in msg
        _assert_zero_calls(counters)

    @pytest.mark.parametrize("bad", BAD_TOP_K_CONTAINERS)
    def test_graph_query_stream_rejects_bad_container_before_retrieval(
            self, monkeypatch, bad):
        """Graph 流式入口：非法容器 → 含配置名的 ValueError，
        graph retrieval 0 次调用。"""
        from src.graph_rag import graph_query_stream
        graph_calls = {"retrieve": 0}

        def fake_retrieve(query, model, collection, bm25, all_docs, kg, **kw):
            graph_calls["retrieve"] += 1
            return ([0], DOCS, [0.9])

        monkeypatch.setattr(
            "src.graph_rag.graph_augmented_retrieve", fake_retrieve)
        _patch_graph_downstream(monkeypatch)
        with pytest.raises(ValueError) as exc_info:
            graph_query_stream(
                "q", None, None, None, DOCS, METAS, kg=object(),
                top_k_range=bad,
            )
        msg = str(exc_info.value)
        assert "LLM_TOP_K_MIN" in msg or "LLM_TOP_K_MAX" in msg
        assert graph_calls == {"retrieve": 0}

    def test_graph_query_stream_legal_range_keeps_behavior(self, monkeypatch):
        """合法 (3,20) + alpha=0.7 + temperature=0.66：Graph 流式路径保留
        ——retrieval 1 次且收到 alpha=0.7，动态 Top-K 收到用户区间
        min_k=3/max_k=20（与 Graph 内部 3/50 分离）。"""
        from src.config import reset_settings
        from src.graph_rag import graph_query_stream
        monkeypatch.setenv("API_KEY", "sk-fake-test")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        reset_settings()

        captured = {}
        graph_calls = {"retrieve": 0}

        def fake_retrieve(query, model, collection, bm25, all_docs, kg, **kw):
            graph_calls["retrieve"] += 1
            captured["alpha"] = kw.get("alpha")
            return ([0], DOCS, [0.9])

        def fake_top_k(scores, min_k=None, max_k=None):
            captured["min_k"] = min_k
            captured["max_k"] = max_k
            return 1

        _patch_graph_downstream(monkeypatch)
        monkeypatch.setattr(
            "src.graph_rag.graph_augmented_retrieve", fake_retrieve)
        monkeypatch.setattr("src.graph_rag.dynamic_top_k", fake_top_k)

        stream, sources = graph_query_stream(
            "q", None, None, None, DOCS, METAS, kg=object(), history=[],
            alpha=0.7, temperature=0.66, top_k_range=(3, 20),
        )
        assert list(stream) == ["chunk"]
        assert graph_calls["retrieve"] == 1
        assert captured == {"alpha": 0.7, "min_k": 3, "max_k": 20}


# ═══════════════════════════════════════════════════════════════
# B. 显式 ALPHA fail-fast（管线 / Graph 流式 / CLI Graph 路径）
# ═══════════════════════════════════════════════════════════════

class TestAlphaFailFast:
    def test_graph_rag_pipeline_rejects_alpha_before_index_build(
            self, monkeypatch):
        """graph_rag_pipeline(alpha=2.0)：含 ALPHA 的 ValueError，
        prepare_graph_index（写路径）与 retrieval 均 0 次调用。"""
        from src.graph_rag import graph_rag_pipeline
        calls = {"prepare": 0, "retrieve": 0}

        def fake_prepare(*a, **k):
            calls["prepare"] += 1
            return (None, None, None, [], [], None)

        def fake_retrieve(*a, **k):
            calls["retrieve"] += 1
            return ([], [], [])

        monkeypatch.setattr("src.graph_rag.prepare_graph_index", fake_prepare)
        monkeypatch.setattr(
            "src.graph_rag.graph_augmented_retrieve", fake_retrieve)
        _patch_graph_downstream(monkeypatch)
        with pytest.raises(ValueError, match="ALPHA"):
            graph_rag_pipeline(["f.md"], "q", alpha=2.0)
        assert calls == {"prepare": 0, "retrieve": 0}

    def test_graph_query_stream_rejects_alpha_nan_before_retrieval(
            self, monkeypatch):
        """graph_query_stream(alpha=nan)：含 ALPHA 的 ValueError，
        retrieval 0 次调用。"""
        from src.graph_rag import graph_query_stream
        calls = {"retrieve": 0}

        def fake_retrieve(*a, **k):
            calls["retrieve"] += 1
            return ([], [], [])

        monkeypatch.setattr(
            "src.graph_rag.graph_augmented_retrieve", fake_retrieve)
        _patch_graph_downstream(monkeypatch)
        with pytest.raises(ValueError, match="ALPHA"):
            graph_query_stream(
                "q", None, None, None, DOCS, METAS, kg=object(),
                alpha=float("nan"),
            )
        assert calls == {"retrieve": 0}

    def test_cli_graph_answer_rejects_alpha_before_retrieval(
            self, monkeypatch):
        """cli_loop._graph_rag_answer(alpha=2.0)：含 ALPHA 的 ValueError，
        retrieval 0 次调用（CLI Graph 路径）。"""
        from src.cli_loop import _graph_rag_answer
        calls = {"retrieve": 0}

        def fake_retrieve(*a, **k):
            calls["retrieve"] += 1
            return ([], [], [])

        monkeypatch.setattr(
            "src.graph_rag.graph_augmented_retrieve", fake_retrieve)
        _patch_graph_downstream(monkeypatch)
        with pytest.raises(ValueError, match="ALPHA"):
            _graph_rag_answer(
                "q", None, None, None, DOCS, METAS, kg=object(), history=[],
                alpha=2.0,
            )
        assert calls == {"retrieve": 0}

    def test_validate_alpha_rejects_bool_and_non_finite(self):
        """校验器单元：True/False/NaN/inf/非数字/越界 → 含 ALPHA 错误；
        合法 0.7 通过；字符串 "0.7" 兼容接受并规范化（测试说明：与
        温度一致保留合法字符串数值的既有兼容行为）。"""
        from src.config import validate_alpha
        for bad in (True, False, float("nan"), float("inf"),
                    "not-a-number", 1.5, -0.1):
            with pytest.raises(ValueError, match="ALPHA"):
                validate_alpha(bad)
        assert validate_alpha(0.7) == 0.7
        assert validate_alpha("0.7") == 0.7


# ═══════════════════════════════════════════════════════════════
# C. gateway 直接调用温度 fail-fast（llm_call / llm_call_safe）
# ═══════════════════════════════════════════════════════════════

class TestGatewayTemperatureFailFast:
    @pytest.mark.parametrize("bad", [2.5, -0.1, float("nan"), float("inf"),
                                     True])
    def test_llm_call_rejects_invalid_temperature_before_client(
            self, monkeypatch, bad):
        """直接 gateway 入口：非法温度 → 含 LLM_TEMPERATURE 的 ValueError，
        _get_client 0 次调用（在创建 client/网络之前失败）。"""
        from src.llm_gateway import llm_call
        monkeypatch.setenv("API_KEY", "sk-fake-test")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        calls = {"client": 0}

        def fake_get_client(api_key, base_url):
            calls["client"] += 1
            return None

        monkeypatch.setattr("src.llm_gateway._get_client", fake_get_client)
        with pytest.raises(ValueError, match="LLM_TEMPERATURE"):
            llm_call(
                "t", [{"role": "user", "content": "x"}],
                model="m", temperature=bad,
            )
        assert calls == {"client": 0}

    @pytest.mark.parametrize("bad", [2.5, -0.1, float("nan"), float("inf"),
                                     True])
    def test_llm_call_safe_invalid_temperature_zero_client(
            self, monkeypatch, bad):
        """llm_call_safe：非法温度 → (None, record)，_get_client 0 次调用
        （零 client/零网络）。"""
        from src.llm_gateway import llm_call_safe
        monkeypatch.setenv("API_KEY", "sk-fake-test")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        calls = {"client": 0}

        def fake_get_client(api_key, base_url):
            calls["client"] += 1
            return None

        monkeypatch.setattr("src.llm_gateway._get_client", fake_get_client)
        content, record = llm_call_safe(
            "t", [{"role": "user", "content": "x"}],
            model="m", temperature=bad,
        )
        assert content is None
        assert record.error_category is not None
        assert calls == {"client": 0}

    def test_llm_call_legal_temperature_forwarded(self, monkeypatch):
        """合法 temperature=0.66：原样透传 client.chat.completions.create。"""
        from src.llm_gateway import llm_call
        monkeypatch.setenv("API_KEY", "sk-fake-test")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        captured = {}
        calls = {"client": 0}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                fake_message = type("M", (), {"content": "ok"})()
                fake_choice = type("C", (), {"message": fake_message})()
                return type("R", (), {
                    "model": "m", "choices": [fake_choice], "usage": None,
                })()

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            chat = FakeChat()

        def fake_get_client(api_key, base_url):
            calls["client"] += 1
            return FakeClient()

        monkeypatch.setattr("src.llm_gateway._get_client", fake_get_client)
        response, _ = llm_call(
            "t", [{"role": "user", "content": "x"}],
            model="m", temperature=0.66,
        )
        assert calls["client"] == 1
        assert captured["temperature"] == 0.66

    def test_validate_llm_temperature_rejects_booleans(self):
        """布尔值不是合法温度：True/False → 含 LLM_TEMPERATURE 错误
        （此前 validate_llm_temperature(True) 返回 1.0）。"""
        from src.config import validate_llm_temperature
        for bad in (True, False):
            with pytest.raises(ValueError, match="LLM_TEMPERATURE"):
                validate_llm_temperature(bad)

    def test_validate_llm_temperature_accepts_numeric_string(self):
        """兼容行为（测试说明）：合法字符串数值仍被接受并规范化 float
        （与 Settings .env 解析路径一致）；非法字符串拒绝。"""
        from src.config import validate_llm_temperature
        assert validate_llm_temperature("0.66") == 0.66
        assert validate_llm_temperature(0.66) == 0.66
        with pytest.raises(ValueError, match="LLM_TEMPERATURE"):
            validate_llm_temperature("not-a-number")


# ═══════════════════════════════════════════════════════════════
# D. fresh-process fail-fast：无真实 .env/密钥/网络
# ═══════════════════════════════════════════════════════════════

class TestFreshProcessFailFast:
    def test_fresh_process_top_k_container_fails_fast(self, tmp_path):
        """fresh-process：top_k_range=(3,20,999) → 含 LLM_TOP_K 配置名的
        ValueError，planner 0 次调用（未进规划器/检索）。"""
        code = (
            "import json, os\n"
            "import src.rag as rag\n"
            "import src.llm_gateway as gw\n"
            "os.environ['API_KEY'] = 'sk-fake-test'\n"
            "os.environ['BASE_URL'] = 'https://fake.test/v1'\n"
            "calls = []\n"
            "def fake_safe(call_type, messages, model=None, temperature=None, **kw):\n"
            "    calls.append(call_type)\n"
            "    return 'q', type('R', (), {'retries_used': 0})()\n"
            "gw.llm_call_safe = fake_safe\n"
            "rag.retrieve_hybrid_with_sources = (\n"
            "    lambda sq, model, collection, bm25, documents, metadatas, **kw:\n"
            "    ([0], ['d'], [0.9]))\n"
            "rag.answer_with_llm_history_stream = (\n"
            "    lambda q, c, h, **kw: iter(['chunk']))\n"
            "rag._record_query_metric = lambda *a, **k: None\n"
            "rag.enrich_context = lambda idx, docs, metas: docs\n"
            "rag.compute_context_k = lambda cands: 1\n"
            "rag.expand_with_parent = (\n"
            "    lambda idx, docs, metas, ctx: (idx, docs))\n"
            "rag.expand_with_adjacent = lambda idx, metas, **kw: idx\n"
            "rag._build_context = lambda *a, **k: 'CTX'\n"
            "rag.format_sources = lambda *a, **k: 'SRC'\n"
            "try:\n"
            "    rag.answer_query_stream(\n"
            "        'q', None, None, None, ['d'],\n"
            "        [{'chunk_id': 'c0', 'source_id': 's0', 'source_name': 'a.md',\n"
            "          'source': 'a.md'}], top_k_range=(3, 20, 999))\n"
            "    print(json.dumps({'raised': False, 'calls': len(calls)}))\n"
            "except ValueError as exc:\n"
            "    print(json.dumps({'raised': True, 'calls': len(calls),\n"
            "                      'msg': str(exc)}))\n"
        )
        result = _run_in_cwd(code, tmp_path)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout.strip())
        assert payload["raised"] is True
        assert payload["calls"] == 0
        msg = payload["msg"]
        assert "LLM_TOP_K_MIN" in msg or "LLM_TOP_K_MAX" in msg

    def test_fresh_process_graph_alpha_fails_fast(self, tmp_path):
        """fresh-process：graph_rag_pipeline(alpha=2.0) → 含 ALPHA 的
        ValueError，prepare_graph_index（写路径）0 次调用。"""
        code = (
            "import json\n"
            "import src.graph_rag as g\n"
            "import src.rag as rag\n"
            "import src.citations as cit\n"
            "calls = []\n"
            "def fake_prepare(*a, **k):\n"
            "    calls.append('prepare')\n"
            "    return (None, None, None, [], [], None)\n"
            "def fake_retrieve(*a, **k):\n"
            "    calls.append('retrieve')\n"
            "    return ([], [], [])\n"
            "g.prepare_graph_index = fake_prepare\n"
            "g.graph_augmented_retrieve = fake_retrieve\n"
            "g.dynamic_top_k = lambda scores, min_k=None, max_k=None: 1\n"
            "g.retrieval_refused = lambda scores: False\n"
            "g.enrich_context = lambda idx, docs, metas: docs\n"
            "g.compute_context_k = lambda cands: 1\n"
            "g._build_context = lambda *a, **k: 'CTX'\n"
            "g.format_sources = lambda *a, **k: 'SRC'\n"
            "g._record_query_metric = lambda *a, **k: None\n"
            "g.answer_with_llm_history = (\n"
            "    lambda q, c, history=None, **kw: 'A')\n"
            "g.answer_with_llm_history_stream = (\n"
            "    lambda q, c, h, **kw: iter(['chunk']))\n"
            "cit.valid_citation_ids_for_context = lambda *a, **k: []\n"
            "cit.format_citation_status_line = lambda s: ''\n"
            "rag.evaluate_answer_status = lambda a, ids: 'not_required'\n"
            "try:\n"
            "    g.graph_rag_pipeline(['f.md'], 'q', alpha=2.0)\n"
            "    print(json.dumps({'raised': False, 'calls': len(calls)}))\n"
            "except ValueError as exc:\n"
            "    print(json.dumps({'raised': True, 'calls': len(calls),\n"
            "                      'msg': str(exc)}))\n"
        )
        result = _run_in_cwd(code, tmp_path)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout.strip())
        assert payload["raised"] is True
        assert payload["calls"] == 0
        assert "ALPHA" in payload["msg"]

    def test_fresh_process_gateway_temperature_fails_fast(self, tmp_path):
        """fresh-process：llm_call(temperature=True) → 含 LLM_TEMPERATURE
        的 ValueError，_get_client 0 次调用（零 client/零网络）。"""
        code = (
            "import json, os\n"
            "import src.llm_gateway as gw\n"
            "os.environ['API_KEY'] = 'sk-fake-test'\n"
            "os.environ['BASE_URL'] = 'https://fake.test/v1'\n"
            "calls = []\n"
            "def fake_client(*a, **k):\n"
            "    calls.append('client')\n"
            "    return None\n"
            "gw._get_client = fake_client\n"
            "try:\n"
            "    gw.llm_call(\n"
            "        't', [{'role': 'user', 'content': 'x'}],\n"
            "        model='m', temperature=True)\n"
            "    print(json.dumps({'raised': False, 'calls': len(calls)}))\n"
            "except ValueError as exc:\n"
            "    print(json.dumps({'raised': True, 'calls': len(calls),\n"
            "                      'msg': str(exc)}))\n"
        )
        result = _run_in_cwd(code, tmp_path)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout.strip())
        assert payload["raised"] is True
        assert payload["calls"] == 0
        assert "LLM_TEMPERATURE" in payload["msg"]
