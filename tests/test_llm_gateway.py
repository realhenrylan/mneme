"""测试 3.1 单例模型与统一 LLM Gateway。"""

import pytest
import threading
from unittest.mock import MagicMock, patch

from src.llm_gateway import (
    LLMErrorCategory,
    TokenUsage,
    LLMCallRecord,
    classify_error,
    get_or_load_model,
    clear_model_cache,
    get_call_records,
    get_call_summary,
    clear_client_cache,
    clear_call_records,
    _model_cache,
    _call_records,
)
from src.rag_query_decomposer import should_decompose


# ═══════════════════════════════════════════════════════════════
# 错误分类测试
# ═══════════════════════════════════════════════════════════════

class TestClassifyError:
    def test_timeout_error(self):
        assert classify_error(TimeoutError()) == LLMErrorCategory.TIMEOUT

    def test_connection_error(self):
        assert classify_error(ConnectionError()) == LLMErrorCategory.CONNECTION

    def test_connection_reset(self):
        assert classify_error(ConnectionResetError()) == LLMErrorCategory.CONNECTION

    def test_unknown_error(self):
        assert classify_error(ValueError("test")) == LLMErrorCategory.UNKNOWN

    def test_rate_limit_by_name(self):
        """模拟 OpenAI RateLimitError（不导入 openai 异常类）。"""
        exc = type("RateLimitError", (Exception,), {})()
        assert classify_error(exc) == LLMErrorCategory.RATE_LIMIT

    def test_auth_error_by_name(self):
        exc = type("AuthenticationError", (Exception,), {})()
        assert classify_error(exc) == LLMErrorCategory.AUTH

    def test_not_found_by_name(self):
        exc = type("NotFoundError", (Exception,), {})()
        assert classify_error(exc) == LLMErrorCategory.MODEL_NOT_FOUND

    def test_api_timeout_by_name(self):
        exc = type("APITimeoutError", (Exception,), {})()
        assert classify_error(exc) == LLMErrorCategory.TIMEOUT

    def test_cancelled_error(self):
        exc = type("CancelledError", (Exception,), {})()
        assert classify_error(exc) == LLMErrorCategory.CANCELLED

    def test_bad_request_context_length(self):
        exc = type("BadRequestError", (Exception,), {})("context length exceeded")
        assert classify_error(exc) == LLMErrorCategory.CONTEXT_LENGTH

    def test_bad_request_other(self):
        exc = type("BadRequestError", (Exception,), {})("some other bad request")
        assert classify_error(exc) == LLMErrorCategory.UNKNOWN

    def test_internal_server_error(self):
        exc = type("InternalServerError", (Exception,), {})()
        assert classify_error(exc) == LLMErrorCategory.SERVER_ERROR


# ═══════════════════════════════════════════════════════════════
# 进程级模型缓存测试
# ═══════════════════════════════════════════════════════════════

class TestModelCache:
    def setup_method(self):
        clear_model_cache()

    def teardown_method(self):
        clear_model_cache()

    def test_cache_miss_calls_loader(self):
        """缓存未命中时调用 loader。"""
        mock_model = MagicMock()
        loader = MagicMock(return_value=mock_model)
        result = get_or_load_model("test_model", loader)
        assert result is mock_model
        loader.assert_called_once_with("test_model")

    def test_cache_hit_skips_loader(self):
        """缓存命中时不调用 loader。"""
        mock_model = MagicMock()
        loader = MagicMock(return_value=mock_model)
        # 第一次加载
        get_or_load_model("test_model", loader)
        # 第二次应命中缓存
        result = get_or_load_model("test_model", loader)
        assert result is mock_model
        assert loader.call_count == 1  # 只调用一次

    def test_different_models_cached_separately(self):
        """不同模型名分别缓存。"""
        model_a = MagicMock(name="model_a")
        model_b = MagicMock(name="model_b")
        get_or_load_model("model_a", lambda _: model_a)
        get_or_load_model("model_b", lambda _: model_b)
        assert get_or_load_model("model_a", lambda _: None) is model_a
        assert get_or_load_model("model_b", lambda _: None) is model_b

    def test_clear_cache(self):
        """清除缓存后重新加载。"""
        mock_model = MagicMock()
        loader = MagicMock(return_value=mock_model)
        get_or_load_model("test_model", loader)
        clear_model_cache()
        get_or_load_model("test_model", loader)
        assert loader.call_count == 2  # 清除后重新加载

    def test_thread_safety(self):
        """多线程并发访问缓存安全。"""
        mock_model = MagicMock()
        call_count = 0
        lock = threading.Lock()

        def slow_loader(name):
            nonlocal call_count
            with lock:
                call_count += 1
            import time
            time.sleep(0.01)
            return mock_model

        threads = []
        for _ in range(10):
            t = threading.Thread(target=lambda: get_or_load_model("test_model", slow_loader))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        # 由于双重检查，可能调用多次但结果一致
        result = get_or_load_model("test_model", lambda _: None)
        assert result is mock_model


# ═══════════════════════════════════════════════════════════════
# 调用记录与统计测试
# ═══════════════════════════════════════════════════════════════

class TestCallRecords:
    def setup_method(self):
        clear_call_records()

    def teardown_method(self):
        clear_call_records()

    def test_empty_summary(self):
        summary = get_call_summary()
        assert summary["total_calls"] == 0

    def test_record_and_summary(self):
        from src.llm_gateway import _record_call
        _record_call(LLMCallRecord(
            call_type="answer", model="test", latency_ms=100.0,
            token_usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        ))
        _record_call(LLMCallRecord(
            call_type="decompose", model="test", latency_ms=50.0,
            error_category=LLMErrorCategory.TIMEOUT,
        ))
        summary = get_call_summary()
        assert summary["total_calls"] == 2
        assert summary["error_count"] == 1
        assert summary["total_prompt_tokens"] == 10
        assert summary["total_completion_tokens"] == 20
        assert summary["by_type"]["answer"] == 1
        assert summary["by_type"]["decompose"] == 1
        assert summary["by_error"]["timeout"] == 1

    def test_records_trimmed(self):
        """超过 MAX_CALL_RECORDS 时裁剪。"""
        from src.llm_gateway import _record_call, MAX_CALL_RECORDS
        for i in range(MAX_CALL_RECORDS + 50):
            _record_call(LLMCallRecord(
                call_type="test", model="m", latency_ms=float(i),
            ))
        records = get_call_records()
        assert len(records) == MAX_CALL_RECORDS


# ═══════════════════════════════════════════════════════════════
# should_decompose 增强守卫测试
# ═══════════════════════════════════════════════════════════════

class TestShouldDecomposeEnhanced:
    def test_short_query(self):
        assert should_decompose("测试") is False  # ≤4 字

    def test_single_english_word(self):
        assert should_decompose("hello") is False

    def test_simple_chinese_question(self):
        """简单中文问题不需要拆解。"""
        assert should_decompose("这篇论文讲了什么？") is False

    def test_chinese_with_multi_intent_and(self):
        """含'和'的多意图需要拆解。"""
        assert should_decompose("DSpark的主要贡献和作者分别是什么") is True

    def test_chinese_with_multi_intent_yu(self):
        """含'与'的多意图需要拆解。"""
        assert should_decompose("方法与实验结果") is True

    def test_chinese_english_mixed(self):
        """中英混合需要拆解。"""
        assert should_decompose("LLM的主要方法有哪些") is True

    def test_chinese_semicolon_separated(self):
        """分号分隔需要拆解。"""
        assert should_decompose("方法是什么；效果如何") is True

    def test_chinese_dun_separated(self):
        """顿号分隔需要拆解。"""
        assert should_decompose("贡献、方法、实验") is True

    def test_english_multi_word(self):
        """英文多词查询需要拆解。"""
        assert should_decompose("main contributions and authors") is True

    def test_chinese_simple_no_keywords(self):
        """无多意图关键词的中文简单问题不需要拆解。"""
        assert should_decompose("深度学习的原理是什么？") is False

    def test_chinese_simple_question_mark(self):
        """简单中文疑问句不需要拆解。"""
        assert should_decompose("这个方法怎么用？") is False
