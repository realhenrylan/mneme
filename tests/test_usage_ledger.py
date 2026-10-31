"""P2-1 Option A：provider-usage 台账（默认 off / 隐私 / 每查询一行）测试。

覆盖计划 §7.5 的 12 项与集成要求 1–14：
- 模块：开关 / 路径 / 白名单 / null 语义 / 指纹 / 语言桶 / 90 天清理 /
  report 分位数 / CLI；
- 网关：非流/流式 usage 采集、provider 拒绝 stream_options 的一次回退、
  重试与调用累加、流中断 partial；
- rag：answer_query 单行、pre-LLM 拒答、error 单行、写入失败不影响回答、
  开关/consent 门控、流式 usage-only 尾块不 IndexError、evaluation origin。

全部使用 fake client/response，不触网、不真实调用 LLM。
"""

import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src import usage_ledger
from src.usage_ledger import (
    FIELD_ORDER,
    SCHEMA_VERSION,
    QueryUsageCollector,
    build_report,
    config_fingerprint,
    is_enabled,
    language_bucket,
    record_query_usage,
    usage_dir,
)

UTC = timezone.utc
FORBIDDEN_KEYS = ("query", "answer", "prompt", "context", "trace_id", "session_id")


# ═══════════════════════════════════════════════════════════════
# 公共 fixture / 工具
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def ledger_env(tmp_path, monkeypatch):
    """开启台账，数据目录落在 tmp（隔离真实 ~/.mneme）。"""
    monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RAG_USAGE_LEDGER", "1")
    return tmp_path / "data" / "usage"


def _rows(directory):
    rows = []
    directory = directory if directory is not None else usage_dir()
    if not directory.exists():
        return rows
    for path in sorted(directory.glob("usage-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _usage(prompt=11, completion=7, total=18):
    return type("Usage", (), {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    })()


def _response(content="回答内容", usage=None, model="fake-model"):
    message = type("Message", (), {"content": content, "reasoning_content": ""})()
    choice = type("Choice", (), {"message": message, "finish_reason": "stop"})()
    return type("Response", (), {
        "model": model, "choices": [choice], "usage": usage,
    })()


def _content_chunk(text):
    delta = type("Delta", (), {"content": text})()
    choice = type("Choice", (), {"delta": delta})
    return type("Chunk", (), {"choices": [choice], "usage": None})()


def _usage_chunk(usage):
    return type("Chunk", (), {"choices": [], "usage": usage})()


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.closed = False

    def __iter__(self):
        return iter(self._chunks)

    def close(self):
        self.closed = True


def _fake_client(monkeypatch, *, response=None, stream_factory=None,
                 reject_stream_options=False):
    """安装 fake OpenAI client；返回 create 调用 kwargs 列表。"""
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if reject_stream_options and "stream_options" in kwargs:
                raise RuntimeError("stream_options unsupported")
            if stream_factory is not None:
                return stream_factory()
            return response

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(
        "src.llm_gateway._get_client", lambda *a, **k: FakeClient())
    return calls


@pytest.fixture
def llm_env(monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-fake-test")
    monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
    monkeypatch.setattr("src.llm_gateway.DEFAULT_RETRY_BACKOFF", 0)


def _minimal_store(tmp_path, monkeypatch):
    """真实 TraceStore + minimal consent（落 tmp，供 rag 集成路径使用）。"""
    from src.production_observability import ConsentLevel, TraceStore
    monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
    store = TraceStore.from_environment()
    assert store.set_consent(ConsentLevel.MINIMAL, confirmed=True)
    return store


def _evidence(*, refused=False, context="ctx", context_k=1,
              top_indices=(), select_indices=(), query="如何配置缓存？"):
    from src.domain import PreparedAnswerEvidence
    return PreparedAnswerEvidence(
        query=query,
        context=context,
        context_sha256="0" * 64,
        context_k=context_k,
        top_indices=tuple(top_indices),
        select_indices=tuple(select_indices),
        citation_map=(),
        context_chunk_ids=(),
        context_source_ids=(),
        candidate_chunk_ids=(),
        top_scores=(),
        plan_fingerprint="plan",
        retrieval_fingerprint="retrieval",
        refused=refused,
    )


# ═══════════════════════════════════════════════════════════════
# 1. 模块基础：开关 / 路径 / schema
# ═══════════════════════════════════════════════════════════════

class TestModuleBasics:
    def test_enabled_default_off(self, monkeypatch):
        monkeypatch.delenv("RAG_USAGE_LEDGER", raising=False)
        assert is_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " On "])
    def test_enabled_truthy_values(self, monkeypatch, value):
        monkeypatch.setenv("RAG_USAGE_LEDGER", value)
        assert is_enabled() is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "2"])
    def test_enabled_falsey_values(self, monkeypatch, value):
        monkeypatch.setenv("RAG_USAGE_LEDGER", value)
        assert is_enabled() is False

    def test_usage_dir_uses_mneme_data_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
        assert usage_dir() == tmp_path / "data" / "usage"

    def test_usage_dir_defaults_to_home(self, monkeypatch):
        monkeypatch.delenv("MNEME_DATA_DIR", raising=False)
        assert Path(usage_dir()).as_posix().endswith("/.mneme/usage")

    def test_schema_version_and_field_order(self):
        assert SCHEMA_VERSION == 1
        assert len(FIELD_ORDER) == 20
        assert FIELD_ORDER[0] == "schema_version"
        assert FIELD_ORDER[-1] == "language_bucket"


from pathlib import Path  # noqa: E402  (fixture 方法内使用，置于中段便于阅读)


# ═══════════════════════════════════════════════════════════════
# 2. 语言桶
# ═══════════════════════════════════════════════════════════════

class TestLanguageBucket:
    def test_cjk(self):
        assert language_bucket("如何配置向量缓存？") == "cjk"

    def test_latin(self):
        assert language_bucket("How do I configure the cache?") == "latin"

    def test_mixed(self):
        assert language_bucket("如何配置 vector cache？") == "mixed"

    def test_unknown(self):
        assert language_bucket("") == "unknown"
        assert language_bucket("12345 !!!") == "unknown"
        assert language_bucket(None) == "unknown"


# ═══════════════════════════════════════════════════════════════
# 3. 配置指纹
# ═══════════════════════════════════════════════════════════════

class TestConfigFingerprint:
    def test_stable_and_12_hex(self, monkeypatch):
        for name in ("RAG_REFUSAL_THRESHOLD", "RAG_DYNAMIC_MIN_K",
                     "RAG_CONTEXT_MAX_K", "RAG_CONTEXT_TOKEN_BUDGET"):
            monkeypatch.delenv(name, raising=False)
        first = config_fingerprint()
        assert first == config_fingerprint()
        assert re.fullmatch(r"[0-9a-f]{12}", first)

    def test_changes_with_env_value(self, monkeypatch):
        monkeypatch.delenv("RAG_REFUSAL_THRESHOLD", raising=False)
        baseline = config_fingerprint()
        monkeypatch.setenv("RAG_REFUSAL_THRESHOLD", "0.031")
        assert config_fingerprint() != baseline


# ═══════════════════════════════════════════════════════════════
# 4. record_query_usage：白名单 / null / 隐私 / 失败静默 / 清理
# ═══════════════════════════════════════════════════════════════

class TestRecordQueryUsage:
    def test_writes_one_wellformed_row(self, ledger_env):
        record_query_usage({
            "origin": "user",
            "route": "sync",
            "outcome": "answered",
            "model": "fake-model",
            "tokens_prompt": 11,
            "tokens_completion": 7,
            "tokens_total": 18,
            "llm_calls": 2,
            "retry_count": 0,
            "usage_source": "provider",
            "ttft_ms": None,
            "total_ms": 42,
            "retrieval_k": None,
            "context_chunks": 3,
            "refusal_stage": "none",
            "cache_hit": False,
            "language_bucket": "cjk",
        })
        rows = _rows(ledger_env)
        assert len(rows) == 1
        row = rows[0]
        assert set(row) == set(FIELD_ORDER)
        assert row["schema_version"] == 1
        assert row["ts_bucket"] == datetime.now(UTC).strftime("%Y-%m-%d")
        assert row["tokens_total"] == 18
        assert row["cache_hit"] is False
        assert re.fullmatch(r"[0-9a-f]{12}", row["config_fingerprint"])

    def test_disabled_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.delenv("RAG_USAGE_LEDGER", raising=False)
        record_query_usage({"origin": "user", "outcome": "answered"})
        assert not (tmp_path / "data").exists()

    def test_consent_not_minimal_writes_nothing(self, ledger_env):
        record_query_usage(
            {"origin": "user", "outcome": "answered"}, consent_minimal=False)
        assert not ledger_env.exists()

    def test_missing_tokens_stay_null_never_zero(self, ledger_env):
        record_query_usage({
            "origin": "user", "route": "sync", "outcome": "error",
            "usage_source": "missing", "llm_calls": 1,
        })
        row = _rows(ledger_env)[0]
        assert row["tokens_prompt"] is None
        assert row["tokens_completion"] is None
        assert row["tokens_total"] is None
        assert row["ttft_ms"] is None
        assert row["retrieval_k"] is None

    def test_privacy_whitelist_and_no_text(self, ledger_env):
        record_query_usage({
            "origin": "user", "outcome": "answered",
            "query": "SECRET_QUERY_TEXT",
            "answer": "SECRET_ANSWER_TEXT",
            "prompt": "SECRET_PROMPT_TEXT",
            "context": "SECRET_CONTEXT_TEXT",
            "trace_id": "trace-123",
            "session_id": "session-456",
            "model": "m" * 300,
        })
        row = _rows(ledger_env)[0]
        assert set(row) == set(FIELD_ORDER)
        for key in FORBIDDEN_KEYS:
            assert key not in row
        text = json.dumps(row, ensure_ascii=False)
        for secret in ("SECRET_QUERY_TEXT", "SECRET_ANSWER_TEXT",
                       "SECRET_PROMPT_TEXT", "SECRET_CONTEXT_TEXT",
                       "trace-123", "session-456"):
            assert secret not in text
        assert len(row["model"]) <= usage_ledger.MAX_MODEL_LEN

    def test_enums_are_normalized(self, ledger_env):
        record_query_usage({
            "origin": "bogus", "route": "bogus", "outcome": "bogus",
            "usage_source": "bogus", "refusal_stage": "bogus",
            "language_bucket": "bogus", "cache_hit": "yes",
        })
        row = _rows(ledger_env)[0]
        assert row["origin"] == "user"
        assert row["route"] == "sync"
        assert row["outcome"] == "error"
        assert row["usage_source"] == "missing"
        assert row["refusal_stage"] == "none"
        assert row["language_bucket"] == "unknown"
        assert row["cache_hit"] is False

    def test_write_failure_is_swallowed(self, ledger_env, monkeypatch):
        def boom(path, line):
            raise OSError("disk full")

        monkeypatch.setattr("src.usage_ledger._append", boom)
        record_query_usage({"origin": "user", "outcome": "answered"})
        # 目录可能已安全创建，但不得落任何行，且不得抛异常
        assert _rows(ledger_env) == []

    def test_cleanup_removes_files_older_than_90_days(self, ledger_env):
        ledger_env.mkdir(parents=True)
        old = ledger_env / "usage-2020-01.jsonl"
        old.write_text("{}\n", encoding="utf-8")
        current = ledger_env / usage_ledger._path_for(
            usage_ledger._utc_now()).name
        current.write_text("", encoding="utf-8")
        record_query_usage({"origin": "user", "outcome": "answered"})
        assert not old.exists()
        assert current.exists()
        assert len(_rows(ledger_env)) == 1


# ═══════════════════════════════════════════════════════════════
# 5. collector：累加 / 幂等 / 来源语义
# ═══════════════════════════════════════════════════════════════

class TestCollector:
    def test_finish_writes_exactly_one_row(self, ledger_env):
        collector = QueryUsageCollector(
            origin="user", route="sync", language_bucket_value="latin")
        collector.on_call({
            "model": "fake-model", "prompt_tokens": 11,
            "completion_tokens": 7, "total_tokens": 18,
            "retries_used": 0, "usage_source": "provider",
        })
        row = collector.finish("answered", context_chunks=3)
        assert row is not None
        assert collector.finish("error") is None
        rows = _rows(ledger_env)
        assert len(rows) == 1
        assert rows[0]["outcome"] == "answered"
        assert rows[0]["tokens_total"] == 18
        assert rows[0]["llm_calls"] == 1
        assert rows[0]["usage_source"] == "provider"
        assert rows[0]["language_bucket"] == "latin"

    def test_missing_usage_source_and_null_tokens(self, ledger_env):
        collector = QueryUsageCollector()
        collector.on_call({
            "model": "m", "prompt_tokens": None,
            "completion_tokens": None, "total_tokens": None,
            "usage_source": "missing",
        })
        collector.finish("error")
        row = _rows(ledger_env)[0]
        assert row["usage_source"] == "missing"
        assert row["tokens_prompt"] is None
        assert row["tokens_completion"] is None
        assert row["tokens_total"] is None
        assert row["llm_calls"] == 1

    def test_unsupported_source(self, ledger_env):
        collector = QueryUsageCollector()
        collector.on_call({"usage_source": "unsupported"})
        collector.finish("answered")
        row = _rows(ledger_env)[0]
        assert row["usage_source"] == "unsupported"
        assert row["tokens_total"] is None

    def test_partial_source_nulls_tokens(self, ledger_env):
        collector = QueryUsageCollector()
        collector.on_call({
            "prompt_tokens": 11, "completion_tokens": 7,
            "total_tokens": 18, "usage_source": "provider",
        })
        collector.on_call({"usage_source": "partial"})
        collector.finish("error", partial=True)
        row = _rows(ledger_env)[0]
        assert row["usage_source"] == "partial"
        assert row["tokens_total"] is None

    def test_calls_and_retries_accumulate(self, ledger_env):
        collector = QueryUsageCollector()
        collector.on_call({
            "model": "m1", "prompt_tokens": 10, "completion_tokens": 2,
            "total_tokens": 12, "retries_used": 1, "usage_source": "provider",
            "ttft_ms": 30,
        })
        collector.on_call({
            "model": "m1", "prompt_tokens": 5, "completion_tokens": 3,
            "total_tokens": 8, "retries_used": 0, "usage_source": "provider",
        })
        row = collector.finish("answered")
        assert row["llm_calls"] == 2
        assert row["retry_count"] == 1
        assert row["tokens_prompt"] == 15
        assert row["tokens_completion"] == 5
        assert row["tokens_total"] == 20
        assert row["ttft_ms"] == 30
        assert row["model"] == "m1"


# ═══════════════════════════════════════════════════════════════
# 6. report：固定 fixture 的 n / mean / p50 / p90 / p95
# ═══════════════════════════════════════════════════════════════

class TestReport:
    def _write_fixture(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "usage-2026-11.jsonl"
        rows = [
            {"ts_bucket": "2026-10-30", "model": "m1", "outcome": "answered",
             "origin": "user", "tokens_total": 10, "total_ms": 100,
             "llm_calls": 1},
            {"ts_bucket": "2026-10-30", "model": "m1", "outcome": "answered",
             "origin": "user", "tokens_total": 20, "total_ms": 200,
             "llm_calls": 2},
            {"ts_bucket": "2026-10-31", "model": "m2", "outcome": "error",
             "origin": "evaluation", "tokens_total": 30, "total_ms": 300,
             "llm_calls": 3},
            {"ts_bucket": "2026-10-31", "model": "m2", "outcome": "answered",
             "origin": "user", "tokens_total": 40, "total_ms": 400,
             "llm_calls": 4},
            # 窗口外（7 天 = 2026-10-26 起）
            {"ts_bucket": "2026-10-01", "model": "m1", "outcome": "answered",
             "origin": "user", "tokens_total": 999},
        ]
        lines = [json.dumps(row) for row in rows]
        lines.append("this is not json")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_quantiles_and_groups(self, tmp_path):
        directory = tmp_path / "usage"
        self._write_fixture(directory)
        report = build_report(
            days=7, now=datetime(2026, 11, 1, tzinfo=UTC),
            directory=directory,
        )
        assert report["n"] == 4
        stats = report["metrics"]["tokens_total"]
        assert stats["n"] == 4
        assert stats["mean"] == 25.0
        assert stats["p50"] == 25.0
        assert stats["p90"] == 37.0
        assert stats["p95"] == 38.5
        assert report["by_model"]["m1"]["n"] == 2
        assert report["by_outcome"]["answered"]["n"] == 3
        assert report["by_origin"]["evaluation"]["n"] == 1
        assert report["by_origin"]["evaluation"]["tokens_total"]["n"] == 1

    def test_report_has_no_raw_rows(self, tmp_path):
        directory = tmp_path / "usage"
        self._write_fixture(directory)
        report = build_report(
            days=7, now=datetime(2026, 11, 1, tzinfo=UTC),
            directory=directory,
        )
        assert set(report) == {
            "days", "n", "metrics", "by_model", "by_outcome", "by_origin"}
        text = json.dumps(report)
        assert "2026-10-30" not in text
        assert "query" not in text

    def test_cli_emits_json(self, ledger_env, capsys):
        ledger_env.mkdir(parents=True)
        (ledger_env / "usage-2026-11.jsonl").write_text(
            json.dumps({"ts_bucket": "2026-11-01", "tokens_total": 5}) + "\n",
            encoding="utf-8")
        assert usage_ledger.main(["report", "--days", "7"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["n"] == 1


# ═══════════════════════════════════════════════════════════════
# 7. gateway：usage_sink 采集（非流 / 流式 / 回退 / 重试 / partial）
# ═══════════════════════════════════════════════════════════════

class TestGatewayUsageSink:
    def test_non_stream_usage_payload(self, monkeypatch, llm_env):
        from src.llm_gateway import llm_call
        _fake_client(monkeypatch, response=_response(usage=_usage()))
        captured = []
        response, record = llm_call(
            "answer", [{"role": "user", "content": "q"}],
            model="requested-model", usage_sink=captured.append,
        )
        assert response.choices[0].message.content == "回答内容"
        assert record.token_usage.prompt_tokens == 11
        assert len(captured) == 1
        payload = captured[0]
        assert payload["call_type"] == "answer"
        assert payload["usage_source"] == "provider"
        assert payload["prompt_tokens"] == 11
        assert payload["completion_tokens"] == 7
        assert payload["total_tokens"] == 18
        assert payload["retries_used"] == 0
        assert payload["error_category"] is None

    def test_non_stream_without_usage_is_missing(self, monkeypatch, llm_env):
        from src.llm_gateway import llm_call
        _fake_client(monkeypatch, response=_response(usage=None))
        captured = []
        llm_call("answer", [{"role": "user", "content": "q"}],
                 usage_sink=captured.append)
        payload = captured[0]
        assert payload["usage_source"] == "missing"
        assert payload["prompt_tokens"] is None
        assert payload["completion_tokens"] is None
        assert payload["total_tokens"] is None

    def test_retry_accumulates_calls_and_retries(self, monkeypatch, llm_env):
        from src.llm_gateway import llm_call
        attempts = {"n": 0}

        class FakeCompletions:
            def create(self, **kwargs):
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise RuntimeError("transient")
                return _response(usage=_usage())

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            chat = FakeChat()

        monkeypatch.setattr(
            "src.llm_gateway._get_client", lambda *a, **k: FakeClient())
        collector = QueryUsageCollector()
        response, record = llm_call(
            "answer", [{"role": "user", "content": "q"}],
            max_retries=1, usage_sink=collector.on_call,
        )
        assert attempts["n"] == 2
        assert record.retries_used == 1
        collector.on_call({
            "model": "fake-model", "prompt_tokens": 1,
            "completion_tokens": 1, "total_tokens": 2,
            "usage_source": "provider",
        })
        row = collector.finish("answered")
        assert row["llm_calls"] == 2
        assert row["retry_count"] == 1
        assert row["tokens_total"] == 20

    def test_stream_without_sink_does_not_request_stream_options(
            self, monkeypatch, llm_env):
        """台账 off（无 sink）时不得改变默认流式请求参数。"""
        from src.llm_gateway import llm_call
        calls = _fake_client(
            monkeypatch,
            stream_factory=lambda: _FakeStream([_content_chunk("hi")]),
        )
        response, _ = llm_call(
            "answer", [{"role": "user", "content": "q"}], stream=True,
        )
        assert list(response)
        assert "stream_options" not in calls[0]

    def test_stream_usage_only_final_chunk(self, monkeypatch, llm_env):
        from src.llm_gateway import llm_call
        calls = _fake_client(
            monkeypatch,
            stream_factory=lambda: _FakeStream([
                _content_chunk("hello "), _usage_chunk(_usage(5, 3, 8)),
            ]),
        )
        captured = []
        response, _ = llm_call(
            "answer", [{"role": "user", "content": "q"}],
            stream=True, usage_sink=captured.append,
        )
        text = "".join(
            getattr(getattr(c, "choices", None)[0], "delta").content
            for c in response if getattr(c, "choices", None)
        )
        assert text == "hello "
        assert calls[0]["stream_options"] == {"include_usage": True}
        assert len(captured) == 1
        payload = captured[0]
        assert payload["usage_source"] == "provider"
        assert payload["prompt_tokens"] == 5
        assert payload["completion_tokens"] == 3
        assert payload["total_tokens"] == 8
        assert payload["stream"] is True
        assert isinstance(payload["ttft_ms"], int)

    def test_stream_response_usage_attribute_fallback(
            self, monkeypatch, llm_env):
        """尾块无 usage 时，读取流对象自身暴露的 usage（只读不估算）。"""
        from src.llm_gateway import llm_call

        class _StreamWithUsage(_FakeStream):
            def __init__(self, chunks, usage):
                super().__init__(chunks)
                self.usage = usage

        _fake_client(
            monkeypatch,
            stream_factory=lambda: _StreamWithUsage(
                [_content_chunk("hi")], _usage(2, 1, 3)),
        )
        captured = []
        response, _ = llm_call(
            "answer", [{"role": "user", "content": "q"}],
            stream=True, usage_sink=captured.append,
        )
        list(response)
        assert len(captured) == 1
        assert captured[0]["usage_source"] == "provider"
        assert captured[0]["prompt_tokens"] == 2
        assert captured[0]["completion_tokens"] == 1
        assert captured[0]["total_tokens"] == 3

    def test_stream_rejects_stream_options_falls_back_once(
            self, monkeypatch, llm_env):
        from src.llm_gateway import llm_call
        calls = _fake_client(
            monkeypatch,
            stream_factory=lambda: _FakeStream([_content_chunk("hi")]),
            reject_stream_options=True,
        )
        captured = []
        response, _ = llm_call(
            "answer", [{"role": "user", "content": "q"}],
            stream=True, usage_sink=captured.append,
        )
        list(response)
        assert len(calls) == 2  # 一次拒绝 + 一次去掉参数的回退
        assert "stream_options" in calls[0]
        assert "stream_options" not in calls[1]
        assert len(captured) == 1
        payload = captured[0]
        assert payload["usage_source"] == "unsupported"
        assert payload["prompt_tokens"] is None
        assert payload["total_tokens"] is None

    def test_stream_partial_on_early_close(self, monkeypatch, llm_env):
        from src.llm_gateway import llm_call
        _fake_client(
            monkeypatch,
            stream_factory=lambda: _FakeStream([
                _content_chunk("hel"), _content_chunk("lo"),
            ]),
        )
        captured = []
        response, _ = llm_call(
            "answer", [{"role": "user", "content": "q"}],
            stream=True, usage_sink=captured.append,
        )
        iterator = iter(response)
        next(iterator)
        iterator.close()
        assert len(captured) == 1
        assert captured[0]["usage_source"] == "partial"
        assert captured[0]["total_tokens"] is None

    def test_llm_call_safe_forwards_sink(self, monkeypatch, llm_env):
        from src.llm_gateway import llm_call_safe
        _fake_client(
            monkeypatch,
            response=_response(content="rewritten", usage=_usage()))
        captured = []
        content, record = llm_call_safe(
            "rewrite", [{"role": "user", "content": "q"}],
            usage_sink=captured.append,
        )
        assert content == "rewritten"
        assert captured[0]["call_type"] == "rewrite"
        assert captured[0]["usage_source"] == "provider"


# ═══════════════════════════════════════════════════════════════
# 8. rag 集成：answer_query / 流式 / 门控 / 失败隔离
# ═══════════════════════════════════════════════════════════════

class TestRagIntegration:
    def test_answer_query_records_one_row_with_usage(
            self, tmp_path, monkeypatch, ledger_env, llm_env):
        import src.rag as rag
        store = _minimal_store(tmp_path, monkeypatch)
        _fake_client(monkeypatch, response=_response(usage=_usage()))
        monkeypatch.setattr(
            "src.rag.prepare_answer_evidence",
            lambda *a, **k: _evidence(context="ctx [S1]", context_k=1),
        )
        answer, _sources = rag.answer_query(
            "如何配置缓存？", None, None, None, [], [],
            trace_store=store,
        )
        assert answer == "回答内容"
        rows = _rows(ledger_env)
        assert len(rows) == 1
        row = rows[0]
        assert row["origin"] == "user"
        assert row["route"] == "sync"
        assert row["outcome"] == "answered"
        assert row["tokens_prompt"] == 11
        assert row["tokens_completion"] == 7
        assert row["tokens_total"] == 18
        assert row["llm_calls"] == 1
        assert row["usage_source"] == "provider"
        assert row["language_bucket"] == "cjk"
        assert row["retrieval_k"] is None
        assert row["context_chunks"] == 1
        assert row["refusal_stage"] == "none"

    def test_pre_llm_refusal_zero_calls_zero_tokens(
            self, tmp_path, monkeypatch, ledger_env, llm_env):
        import src.rag as rag
        store = _minimal_store(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "src.rag.prepare_answer_evidence",
            lambda *a, **k: _evidence(refused=True, context="", context_k=0),
        )
        answer, sources = rag.answer_query(
            "无关问题", None, None, None, [], [], trace_store=store)
        assert answer == rag.REFUSAL_MESSAGE
        assert sources == ""
        row = _rows(ledger_env)[0]
        assert row["outcome"] == "refused_pre_llm"
        assert row["refusal_stage"] == "pre_llm"
        assert row["llm_calls"] == 0
        assert row["retry_count"] == 0
        assert row["tokens_prompt"] is None
        assert row["tokens_total"] is None
        assert row["usage_source"] == "missing"
        assert row["context_chunks"] == 0

    def test_exception_records_error_once_and_reraises(
            self, tmp_path, monkeypatch, ledger_env, llm_env):
        import src.rag as rag
        store = _minimal_store(tmp_path, monkeypatch)

        def boom(*a, **k):
            raise RuntimeError("retrieval exploded")

        monkeypatch.setattr("src.rag.prepare_answer_evidence", boom)
        with pytest.raises(RuntimeError):
            rag.answer_query("查询", None, None, None, [], [], trace_store=store)
        rows = _rows(ledger_env)
        assert len(rows) == 1
        assert rows[0]["outcome"] == "error"
        assert rows[0]["llm_calls"] == 0
        assert rows[0]["tokens_total"] is None

    def test_switch_off_writes_no_file(self, tmp_path, monkeypatch, llm_env):
        import src.rag as rag
        monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.delenv("RAG_USAGE_LEDGER", raising=False)
        store = _minimal_store(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "src.rag.prepare_answer_evidence",
            lambda *a, **k: _evidence(refused=True, context="", context_k=0),
        )
        rag.answer_query("查询", None, None, None, [], [], trace_store=store)
        assert not (tmp_path / "data" / "usage").exists()

    def test_no_trace_store_consent_fails_closed(self):
        """无 trace store 时必须 fail-closed，不能绕过 consent。"""
        from src.rag import _usage_consent_minimal
        assert _usage_consent_minimal(None) is False

    def test_consent_not_minimal_writes_no_file(
            self, tmp_path, monkeypatch, llm_env):
        import src.rag as rag
        from src.production_observability import TraceStore
        monkeypatch.setenv("MNEME_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("RAG_USAGE_LEDGER", "1")
        store = TraceStore.from_environment()  # consent 默认 off
        monkeypatch.setattr(
            "src.rag.prepare_answer_evidence",
            lambda *a, **k: _evidence(refused=True, context="", context_k=0),
        )
        rag.answer_query("查询", None, None, None, [], [], trace_store=store)
        assert not (tmp_path / "data" / "usage").exists()

    def test_write_failure_never_breaks_answer(
            self, tmp_path, monkeypatch, ledger_env, llm_env):
        import src.rag as rag
        store = _minimal_store(tmp_path, monkeypatch)
        _fake_client(monkeypatch, response=_response(usage=_usage()))
        monkeypatch.setattr(
            "src.rag.prepare_answer_evidence",
            lambda *a, **k: _evidence(context="ctx", context_k=1),
        )

        def boom(path, line):
            raise OSError("disk full")

        monkeypatch.setattr("src.usage_ledger._append", boom)
        answer, _sources = rag.answer_query(
            "如何配置？", None, None, None, [], [], trace_store=store)
        assert answer == "回答内容"
        assert _rows(ledger_env) == []

    def test_evaluation_origin_is_labeled(
            self, tmp_path, monkeypatch, ledger_env, llm_env):
        import src.rag as rag
        store = _minimal_store(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "src.rag.prepare_answer_evidence",
            lambda *a, **k: _evidence(refused=True, context="", context_k=0),
        )
        rag.answer_query(
            "查询", None, None, None, [], [],
            trace_store=store, usage_origin="evaluation",
        )
        row = _rows(ledger_env)[0]
        assert row["origin"] == "evaluation"
        assert row["outcome"] == "refused_pre_llm"

    def test_stream_usage_only_final_chunk_end_to_end(
            self, tmp_path, monkeypatch, ledger_env, llm_env):
        import src.rag as rag
        store = _minimal_store(tmp_path, monkeypatch)
        _fake_client(
            monkeypatch,
            stream_factory=lambda: _FakeStream([
                _content_chunk("hello "), _usage_chunk(_usage(5, 3, 8)),
            ]),
        )
        chunks = list(rag.answer_with_llm_history_stream(
            "问题", "ctx", [], usage_sink=None,
        ))
        assert "".join(chunks) == "hello "

        collector = QueryUsageCollector(route="stream")
        list(rag.answer_with_llm_history_stream(
            "问题", "ctx", [], usage_sink=collector.on_call,
        ))
        row = collector.finish("answered")
        assert row["usage_source"] == "provider"
        assert row["tokens_total"] == 8
        assert row["ttft_ms"] is not None

    def test_answer_query_stream_pre_llm_refusal_records_stream_route(
            self, tmp_path, monkeypatch, ledger_env, llm_env):
        import src.rag as rag
        store = _minimal_store(tmp_path, monkeypatch)
        plan = SimpleNamespace(best_score={}, merged=[], scores_flat=[])
        monkeypatch.setattr(
            "src.rag._plan_query_runtime", lambda *a, **k: plan)
        stream_result, sources = rag.answer_query_stream(
            "查询", None, None, None, [], [], top_k_range=(3, 5),
            trace_store=store,
        )
        assert sources == ""
        assert list(stream_result) == [rag.REFUSAL_MESSAGE]
        row = _rows(ledger_env)[0]
        assert row["route"] == "stream"
        assert row["outcome"] == "refused_pre_llm"
        assert row["refusal_stage"] == "pre_llm"
        assert row["llm_calls"] == 0
        assert row["retrieval_k"] == 5
        assert row["tokens_total"] is None

    def test_answer_query_stream_answered_records_one_row(
            self, tmp_path, monkeypatch, ledger_env, llm_env):
        import src.rag as rag
        store = _minimal_store(tmp_path, monkeypatch)
        _fake_client(
            monkeypatch,
            stream_factory=lambda: _FakeStream([
                _content_chunk("hello"), _usage_chunk(_usage(5, 3, 8)),
            ]),
        )
        plan = SimpleNamespace(
            best_score={0: 0.9}, merged=[0], scores_flat=[0.9])
        monkeypatch.setattr(
            "src.rag._plan_query_runtime", lambda *a, **k: plan)
        monkeypatch.setattr("src.rag._get_reranker", lambda: None)
        stream_result, sources = rag.answer_query_stream(
            "查询", None, None, None, ["doc0 content"],
            [{"chunk_id": "c0", "source_id": "s0",
              "source_name": "n0", "chunk_index": 0}],
            top_k_range=(3, 5), trace_store=store,
        )
        assert list(stream_result) == ["hello"]
        assert sources
        rows = _rows(ledger_env)
        assert len(rows) == 1
        row = rows[0]
        assert row["route"] == "stream"
        assert row["outcome"] == "answered"
        assert row["tokens_total"] == 8
        assert row["llm_calls"] == 1
        assert row["retrieval_k"] == 5
        assert row["usage_source"] == "provider"

    def test_generate_answer_standalone_evaluation_origin(
            self, tmp_path, monkeypatch, ledger_env, llm_env):
        import src.rag as rag
        _minimal_store(tmp_path, monkeypatch)
        _fake_client(monkeypatch, response=_response(usage=_usage()))
        answer, _sources = rag.generate_answer(
            _evidence(context="ctx", context_k=1), [], [],
            usage_origin="evaluation",
        )
        assert answer == "回答内容"
        row = _rows(ledger_env)[0]
        assert row["origin"] == "evaluation"
        assert row["outcome"] == "answered"
        assert row["tokens_total"] == 18
