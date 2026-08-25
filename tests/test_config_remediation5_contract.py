"""Phase C / 计划 3.2 第五轮返工契约测试（TDD）。

锁定独立验收第五轮复现的两个 fail-fast 缺陷：
A. 显式 `temperature` 覆盖值绕过 Settings 范围校验：`temperature=2.5`
   曾进入查询规划器并触发 rewrite/decompose 的 LLM 路径。非法温度必须
   在规划、检索、LLM gateway、写路径之前失败，错误信息包含
   `LLM_TEMPERATURE`，且 planner/retrieval/gateway 调用数均为 0。
B. `answer_query_stream(top_k_range=(0, 20))` 曾在校验前进入规划器
   （检索宽度 20）。非法用户 Top-K（< 1 或 min > max）必须在计算
   `max(top_k_range)` 与进入规划器之前失败，错误信息明确关联
   `LLM_TOP_K_MIN` / `LLM_TOP_K_MAX`，且调用数均为 0。

同时锁定：合法 `(3, 20)` + 显式 `temperature=0.66` 保持成功路径与
显式优先行为（贯穿 rewrite/decompose，检索宽度 = max(top_k_range) = 20）；
至少一个顶层入口（answer_query / answer_query_stream）与直接下层入口
（prepare_answer_evidence / _plan_query_runtime）分别覆盖，防止未来绕过。

全部测试使用系统 temp、fake API_KEY/BASE_URL、fake/fail-fast gateway
与检索入口；fresh-process 用例在无 `.env` 的临时 CWD 中运行并清洗全部
受管环境变量，禁止真实 LLM/网络/密钥/主目录写入。
"""

import io  # noqa: F401  (保留与第四轮一致的导入基线)
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


def _patch_counters(monkeypatch):
    """fake planner gateway（按 call_type 计数并捕获 model/temperature）+
    fake 检索（计数并捕获 k）+ fake 生成 gateway（计数）。

    返回 (counters, captured, retrieve_k)：
    - counters: rewrite / decompose / retrieve / gateway 调用数；
    - captured: rewrite/decompose 的 (call_type, model, temperature)；
    - retrieve_k: 检索入口收到的 k 列表。
    """
    import src.rag as rag
    counters = {"rewrite": 0, "decompose": 0, "retrieve": 0, "gateway": 0}
    captured = []
    retrieve_k = []

    def fake_safe(call_type, messages, model=None, temperature=None, **kw):
        counters["rewrite" if call_type == "rewrite" else "decompose"] += 1
        captured.append((call_type, model, temperature))
        content = (
            "它的作者和贡献分别是什么？" if call_type == "rewrite"
            else '["A","B"]'
        )
        return content, SimpleNamespace(retries_used=0)

    def fake_retrieve(sq, model, collection, bm25, documents, metadatas, **kw):
        counters["retrieve"] += 1
        retrieve_k.append(kw.get("k"))
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
    return counters, captured, retrieve_k


def _assert_zero_calls(counters):
    assert counters == {"rewrite": 0, "decompose": 0, "retrieve": 0,
                        "gateway": 0}


# ═══════════════════════════════════════════════════════════════
# A. 显式 temperature fail-fast：非法值在规划/检索/gateway 之前失败
# ═══════════════════════════════════════════════════════════════

class TestFailFastExplicitTemperature:
    @pytest.mark.parametrize("bad", [2.5, -0.1, float("nan"), float("inf")])
    def test_answer_query_rejects_invalid_temperature_before_any_call(
            self, monkeypatch, bad):
        """顶层同步入口：2.5 / -0.1 / NaN / inf → 含 LLM_TEMPERATURE 的
        配置错误；planner/retrieval/gateway 调用数均为 0。"""
        import src.rag as rag
        from src.config import reset_settings
        monkeypatch.setenv("LLM_TEMPERATURE", "0.10")
        monkeypatch.setenv("API_KEY", "sk-fake-test")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        reset_settings()
        counters, _, _ = _patch_counters(monkeypatch)
        with pytest.raises(ValueError, match="LLM_TEMPERATURE"):
            rag.answer_query(
                "q", None, None, None, DOCS, METAS, temperature=bad,
            )
        _assert_zero_calls(counters)

    @pytest.mark.parametrize("bad", [2.5, -0.1, float("nan"), float("inf")])
    def test_answer_query_stream_rejects_invalid_temperature_before_any_call(
            self, monkeypatch, bad):
        """顶层流式入口：非法温度在计算 max(top_k_range)/规划器之前失败。"""
        import src.rag as rag
        from src.config import reset_settings
        monkeypatch.setenv("LLM_TEMPERATURE", "0.10")
        monkeypatch.setenv("API_KEY", "sk-fake-test")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        reset_settings()
        counters, _, _ = _patch_counters(monkeypatch)
        with pytest.raises(ValueError, match="LLM_TEMPERATURE"):
            rag.answer_query_stream(
                "q", None, None, None, DOCS, METAS, temperature=bad,
            )
        _assert_zero_calls(counters)

    def test_plan_query_runtime_direct_rejects_invalid_temperature(
            self, monkeypatch):
        """直接下层入口：_plan_query_runtime 显式 llm_temperature 非法 →
        rewrite/decompose/retrieval 均 0 次调用。"""
        import src.rag as rag
        counters, _, _ = _patch_counters(monkeypatch)
        with pytest.raises(ValueError, match="LLM_TEMPERATURE"):
            rag._plan_query_runtime(
                "q", None, None, None, DOCS, METAS, llm_temperature=2.5,
            )
        _assert_zero_calls(counters)

    def test_prepare_answer_evidence_direct_rejects_invalid_temperature(
            self, monkeypatch):
        """直接下层入口：prepare_answer_evidence 显式 llm_temperature 非法
        → 规划器（rewrite/decompose）与检索均 0 次调用。"""
        import src.rag as rag
        counters, _, _ = _patch_counters(monkeypatch)
        with pytest.raises(ValueError, match="LLM_TEMPERATURE"):
            rag.prepare_answer_evidence(
                "q", None, None, None, DOCS, METAS, llm_temperature=2.5,
            )
        _assert_zero_calls(counters)

    def test_generate_answer_rejects_invalid_temperature_before_gateway(
            self, monkeypatch):
        """公开入口：generate_answer 显式非法温度 → LLM gateway 0 次调用。"""
        import src.rag as rag
        counters, _, _ = _patch_counters(monkeypatch)
        evidence = SimpleNamespace(refused=False)
        with pytest.raises(ValueError, match="LLM_TEMPERATURE"):
            rag.generate_answer(
                evidence, DOCS, METAS, temperature=2.5,
            )
        _assert_zero_calls(counters)

    def test_answer_with_llm_history_rejects_invalid_temperature_before_gateway(
            self, monkeypatch):
        """公开入口：answer_with_llm_history 显式非法温度 → llm_call 0 次。"""
        import src.rag as rag
        counters = {"llm_call": 0}

        def fake_llm_call(*a, **k):
            counters["llm_call"] += 1
            return (SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content="ok"))]),
                SimpleNamespace())

        monkeypatch.setattr("src.llm_gateway.llm_call", fake_llm_call)
        with pytest.raises(ValueError, match="LLM_TEMPERATURE"):
            rag.answer_with_llm_history("q", "ctx", [], temperature=2.5)
        assert counters["llm_call"] == 0


# ═══════════════════════════════════════════════════════════════
# B. 显式用户 Top-K fail-fast + 合法路径保持
# ═══════════════════════════════════════════════════════════════

class TestFailFastExplicitTopK:
    def test_answer_query_stream_rejects_top_k_min_below_one(
            self, monkeypatch):
        """top_k_range=(0, 20)：min < 1 → 含 LLM_TOP_K_MIN 的配置错误，
        且规划器/检索/gateway 均 0 次调用（未计算 max、未进规划器）。"""
        import src.rag as rag
        counters, _, _ = _patch_counters(monkeypatch)
        with pytest.raises(ValueError, match="LLM_TOP_K_MIN"):
            rag.answer_query_stream(
                "q", None, None, None, DOCS, METAS, top_k_range=(0, 20),
            )
        _assert_zero_calls(counters)

    def test_answer_query_stream_rejects_inverted_top_k(self, monkeypatch):
        """top_k_range=(21, 20)：min > max → 错误同时关联 LLM_TOP_K_MIN
        与 LLM_TOP_K_MAX；调用数均为 0。"""
        import src.rag as rag
        counters, _, _ = _patch_counters(monkeypatch)
        with pytest.raises(ValueError) as exc_info:
            rag.answer_query_stream(
                "q", None, None, None, DOCS, METAS, top_k_range=(21, 20),
            )
        msg = str(exc_info.value)
        assert "LLM_TOP_K_MIN" in msg
        assert "LLM_TOP_K_MAX" in msg
        _assert_zero_calls(counters)

    def test_answer_query_stream_legal_top_k_and_temperature_keep_behavior(
            self, monkeypatch):
        """合法 (3, 20) + 显式 temperature=0.66：成功路径保留、显式温度
        贯穿 rewrite/decompose（Settings 0.10 不生效）、检索宽度 =
        max(top_k_range) = 20。"""
        import src.rag as rag
        from src.config import reset_settings
        monkeypatch.setenv("LLM_MODEL", "model-plan")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.10")
        monkeypatch.setenv("API_KEY", "sk-fake-test")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        reset_settings()

        counters, captured, retrieve_k = _patch_counters(monkeypatch)
        stream, _ = rag.answer_query_stream(
            "它的作者和贡献分别是什么？", None, None, None, DOCS, METAS,
            history=[("X是什么？", "X是...")],
            top_k_range=(3, 20), temperature=0.66,
        )
        chunks = list(stream)
        assert chunks == ["chunk"]
        assert ("rewrite", "model-plan", 0.66) in captured
        assert ("decompose", "model-plan", 0.66) in captured
        assert 20 in retrieve_k
        assert counters["retrieve"] >= 1


# ═══════════════════════════════════════════════════════════════
# C. fresh-process fail-fast：无真实 .env/密钥/网络
# ═══════════════════════════════════════════════════════════════

class TestFailFastFreshProcess:
    def test_fresh_process_invalid_temperature_fails_fast_zero_calls(
            self, tmp_path):
        """fresh-process（临时 CWD 无 .env、环境变量已清洗）：显式
        temperature=2.5 → LLM_TEMPERATURE 配置错误，planner 0 次调用。"""
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
            "try:\n"
            "    rag.answer_query(\n"
            "        'q', None, None, None, ['d'],\n"
            "        [{'chunk_id': 'c0', 'source_id': 's0', 'source_name': 'a.md',\n"
            "          'source': 'a.md'}], temperature=2.5)\n"
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

    def test_fresh_process_invalid_top_k_fails_fast_zero_calls(
            self, tmp_path):
        """fresh-process：top_k_range=(0, 20) → LLM_TOP_K_MIN 配置错误，
        planner 0 次调用（未计算 max、未进规划器）。"""
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
            "try:\n"
            "    rag.answer_query_stream(\n"
            "        'q', None, None, None, ['d'],\n"
            "        [{'chunk_id': 'c0', 'source_id': 's0', 'source_name': 'a.md',\n"
            "          'source': 'a.md'}], top_k_range=(0, 20))\n"
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
        assert "LLM_TOP_K_MIN" in payload["msg"]
