"""统一 LLM Gateway — 进程级模型缓存 + LLM 调用网关。

设计原则：
1. 进程级模型缓存：embedding model 只加载一次，线程安全
2. 统一 LLM gateway：连接复用、timeout、有限重试、退避、取消、错误分类、token 统计
3. 所有 LLM 调用通过 gateway，不再各自创建 OpenAI client
4. 统一配置契约：受管默认值（LLM model/temperature）委托
   `src.config.Settings` 在调用期解析，gateway 不自行 `load_dotenv()`、
   不以硬编码默认绕过 Settings。`API_KEY`/`BASE_URL` 是 gateway 边界专属
   变量（仅读取进程环境，不加载 .env——`.env` 由 src.config 统一加载）。
"""

import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from openai import OpenAI

from src.config import get_settings, validate_llm_temperature
from src.security import endpoint_validation_error, validate_endpoint


# ═══════════════════════════════════════════════════════════════
# 错误分类
# ═══════════════════════════════════════════════════════════════

class LLMErrorCategory(str, Enum):
    """LLM 调用错误分类，用于可观测性和调试。"""
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    CONNECTION = "connection"
    AUTH = "auth"
    MODEL_NOT_FOUND = "model_not_found"
    CONTEXT_LENGTH = "context_length"
    SERVER_ERROR = "server_error"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class LLMCancelledError(Exception):
    """LLM 调用被用户取消（``cancel_event`` 置位，D1 取消机制）。

    取消是系统性的可恢复操作：不重试、不作为错误消息产出文本，由调用方
    （TUI 生成块）捕获后回输入提示。与 ``KeyboardInterrupt`` 分离——后者
    会逸出主循环终止会话，取消则保持会话存活。
    """


def classify_error(exc: Exception) -> LLMErrorCategory:
    """将异常分类为 LLMErrorCategory。"""
    exc_name = type(exc).__name__
    exc_module = type(exc).__module__ or ""

    # 取消（D1）：显式类型识别优先于名称匹配（asyncio/threading CancelledError）
    if isinstance(exc, LLMCancelledError):
        return LLMErrorCategory.CANCELLED

    # OpenAI SDK 异常
    if "RateLimitError" in exc_name:
        return LLMErrorCategory.RATE_LIMIT
    if "APIConnectionError" in exc_name:
        return LLMErrorCategory.CONNECTION
    if "AuthenticationError" in exc_name:
        return LLMErrorCategory.AUTH
    if "NotFoundError" in exc_name:
        return LLMErrorCategory.MODEL_NOT_FOUND
    if "BadRequestError" in exc_name:
        msg = str(exc).lower()
        if "context" in msg or "token" in msg or "length" in msg:
            return LLMErrorCategory.CONTEXT_LENGTH
        return LLMErrorCategory.UNKNOWN
    if "InternalServerError" in exc_name:
        return LLMErrorCategory.SERVER_ERROR
    if "APITimeoutError" in exc_name:
        return LLMErrorCategory.TIMEOUT

    # 标准库异常
    if isinstance(exc, TimeoutError):
        return LLMErrorCategory.TIMEOUT
    if isinstance(exc, (ConnectionError, ConnectionResetError, BrokenPipeError)):
        return LLMErrorCategory.CONNECTION

    # CancelledError（asyncio 或 threading）
    if "CancelledError" in exc_name:
        return LLMErrorCategory.CANCELLED

    return LLMErrorCategory.UNKNOWN


# ═══════════════════════════════════════════════════════════════
# Token 使用统计
# ═══════════════════════════════════════════════════════════════

@dataclass
class TokenUsage:
    """单次 LLM 调用的 token 使用量。"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMCallRecord:
    """单次 LLM 调用记录。"""
    call_type: str          # "answer" / "decompose" / "rewrite" / "graph_extract"
    model: str
    latency_ms: float
    error_category: LLMErrorCategory | None = None
    token_usage: TokenUsage | None = None
    retries_used: int = 0
    cancelled: bool = False


# ═══════════════════════════════════════════════════════════════
# 进程级模型缓存
# ═══════════════════════════════════════════════════════════════

_model_cache: dict[str, Any] = {}
_model_cache_lock = threading.Lock()


def get_or_load_model(model_name: str, loader_fn=None):
    """进程级线程安全模型缓存。

    Args:
        model_name: 模型名称/路径，作为缓存 key
        loader_fn: 加载函数，仅在缓存未命中时调用

    Returns:
        缓存或新加载的模型实例
    """
    with _model_cache_lock:
        if model_name in _model_cache:
            return _model_cache[model_name]

    # 在锁外加载（避免加载期间阻塞其他读取）
    if loader_fn is None:
        from src.rag import _load_sentence_transformer
        loader_fn = _load_sentence_transformer

    model = loader_fn(model_name)

    with _model_cache_lock:
        # 双重检查：可能在加载期间已被其他线程缓存
        if model_name not in _model_cache:
            _model_cache[model_name] = model
        return _model_cache[model_name]


def clear_model_cache():
    """清除模型缓存（主要用于测试）。"""
    with _model_cache_lock:
        _model_cache.clear()


# ═══════════════════════════════════════════════════════════════
# 统一 LLM Gateway
# ═══════════════════════════════════════════════════════════════

# 默认配置
DEFAULT_TIMEOUT = 60          # 秒
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF = 1.0   # 秒，指数退避基数
DEFAULT_MAX_CONCURRENT = 4    # 并发上限（默认；RAG_LLM_MAX_CONCURRENCY 覆盖）
MAX_CONCURRENT_CEILING = 32   # 并发上限的最大允许值（D2 设计冻结 1–32）


def validate_max_concurrency(value: str) -> int:
    """校验 ``RAG_LLM_MAX_CONCURRENCY``：1–32 整数，非法值导入期 fail-fast。

    与 ``RAG_CONTEXT_EXPANSION`` 同模式：错误信息含配置名，非法 env 在
    模块导入时直接拒绝启动（不可静默回退默认）。
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"invalid RAG_LLM_MAX_CONCURRENCY {value!r}; "
            f"must be an integer in 1..{MAX_CONCURRENT_CEILING}",
        ) from None
    if not 1 <= n <= MAX_CONCURRENT_CEILING:
        raise ValueError(
            f"invalid RAG_LLM_MAX_CONCURRENCY {value!r}; "
            f"must be in 1..{MAX_CONCURRENT_CEILING}",
        )
    return n


# 并发上限（D2 可配置）：导入期 fail-fast（非法 env 拒绝启动）；
# 默认 4 行为不变。LLM 调用全程基于此值（进程级 semaphore）。
MAX_CONCURRENT = validate_max_concurrency(
    os.getenv("RAG_LLM_MAX_CONCURRENCY", str(DEFAULT_MAX_CONCURRENT)),
)

# 进程级 client 缓存
_client_cache: dict[tuple[str, str], OpenAI] = {}
_client_cache_lock = threading.Lock()

# 并发控制
_concurrent_semaphore = threading.Semaphore(MAX_CONCURRENT)

# 调用记录（最近 500 条）
_call_records: list[LLMCallRecord] = []
_call_records_lock = threading.Lock()
MAX_CALL_RECORDS = 500


def _get_client(api_key: str, base_url: str) -> OpenAI:
    """获取或创建缓存的 OpenAI client。"""
    cache_key = (api_key, base_url)
    with _client_cache_lock:
        if cache_key in _client_cache:
            return _client_cache[cache_key]

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=DEFAULT_TIMEOUT,
        max_retries=0,  # 我们自己管理重试
    )
    with _client_cache_lock:
        if cache_key not in _client_cache:
            _client_cache[cache_key] = client
        return _client_cache[cache_key]


def _record_call(record: LLMCallRecord):
    """记录一次 LLM 调用。"""
    global _call_records
    with _call_records_lock:
        _call_records.append(record)
        if len(_call_records) > MAX_CALL_RECORDS:
            _call_records = _call_records[-MAX_CALL_RECORDS:]


def get_call_records() -> list[LLMCallRecord]:
    """获取调用记录快照。"""
    with _call_records_lock:
        return list(_call_records)


def get_call_summary() -> dict:
    """获取调用统计摘要。"""
    with _call_records_lock:
        records = list(_call_records)

    if not records:
        return {"total_calls": 0}

    total = len(records)
    errors = [r for r in records if r.error_category is not None]
    by_type: dict[str, int] = {}
    by_error: dict[str, int] = {}
    total_prompt = 0
    total_completion = 0
    total_latency = 0.0

    for r in records:
        by_type[r.call_type] = by_type.get(r.call_type, 0) + 1
        if r.error_category:
            by_error[r.error_category.value] = by_error.get(r.error_category.value, 0) + 1
        if r.token_usage:
            total_prompt += r.token_usage.prompt_tokens
            total_completion += r.token_usage.completion_tokens
        total_latency += r.latency_ms

    return {
        "total_calls": total,
        "error_count": len(errors),
        "error_rate": len(errors) / total if total else 0,
        "avg_latency_ms": total_latency / total if total else 0,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "by_type": by_type,
        "by_error": by_error,
    }


def llm_call(
    call_type: str,
    messages: list[dict],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int = 1000,
    timeout: float | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    stream: bool = False,
    extra_body: dict | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[Any, LLMCallRecord]:
    """统一 LLM 调用网关。

    所有 LLM 调用应通过此函数，提供：
    - 连接复用（缓存的 OpenAI client）
    - 统一 timeout
    - 有限重试 + 指数退避
    - 并发控制
    - 错误分类
    - Token 使用统计
    - 调用记录
    - 取消（D1）：``cancel_event`` 置位即时取消——调用前置位 = 零网络
      零 client（入口检查）；退避等待用 ``cancel_event.wait(backoff)``
      （置位即时唤醒）；取消抛 ``LLMCancelledError``（分类 CANCELLED、
      不可重试）。

    Args:
        call_type: 调用类型标识（"answer"/"decompose"/"rewrite"/"graph_extract"）
        messages: OpenAI 格式的消息列表
        model: 模型名称；None 时从统一配置 Settings 解析（调用期）
        temperature: 采样温度；None 时从统一配置 Settings 解析（调用期）
        max_tokens: 最大生成 token 数
        timeout: 超时秒数
        max_retries: 最大重试次数
        stream: 是否流式
        extra_body: 附加请求体字段（如关闭推理模型的 thinking）
        cancel_event: 可取消事件；置位即取消（不重试）

    Returns:
        (response, call_record) 元组
    """
    # 统一配置契约：受管默认值（model/temperature）在调用期从 Settings 解析，
    # 不在 gateway 内维护第二套 .env 加载或硬编码默认。
    if model is None:
        model = get_settings().llm_model
    if temperature is None:
        temperature = get_settings().llm_temperature
    # fail-fast：最终 temperature（显式覆盖或 Settings 解析）在创建 client/
    # 发起请求之前必须通过统一校验（与 Settings 同一规则；错误信息含
    # LLM_TEMPERATURE；拒绝 bool/NaN/inf/非数字/越界——直接 gateway 调用
    # temperature=2.5 曾到达 client.chat.completions.create）。llm_call_safe
    # 经本校验保证非法温度零 client/零网络。
    temperature = validate_llm_temperature(temperature)

    record = LLMCallRecord(
        call_type=call_type,
        model=model or "unknown",
        latency_ms=0,
    )

    # D1：调用前置位 = 零网络零 client（先于任何 api_key/endpoint 检查——
    # 取消优先于配置错误）。
    if cancel_event is not None and cancel_event.is_set():
        record.error_category = LLMErrorCategory.CANCELLED
        record.cancelled = True
        _record_call(record)
        raise LLMCancelledError(
            f"LLM call cancelled before start ({call_type})",
        )

    # gateway 边界变量：仅读取进程环境（.env 由 src.config 统一加载）
    api_key = os.getenv("API_KEY")
    base_url = os.getenv("BASE_URL")

    if not api_key or not base_url:
        record.error_category = LLMErrorCategory.AUTH
        _record_call(record)
        raise ValueError("API_KEY or BASE_URL not configured")

    if endpoint_validation_error(base_url):
        record.error_category = LLMErrorCategory.AUTH
        _record_call(record)
        raise ValueError(f"Invalid BASE_URL: {base_url}")

    base_url = validate_endpoint(base_url)

    effective_timeout = timeout or DEFAULT_TIMEOUT
    client = _get_client(api_key, base_url)

    start = time.perf_counter()
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        # D1：每个 attempt 前检查取消（重试间无等待点被退避 wait 覆盖，
        # 此处兜底保证「置位 → 不再发起下一次请求」）。
        if cancel_event is not None and cancel_event.is_set():
            record.error_category = LLMErrorCategory.CANCELLED
            record.cancelled = True
            record.latency_ms = (time.perf_counter() - start) * 1000
            record.retries_used = attempt
            _record_call(record)
            raise LLMCancelledError(
                f"LLM call cancelled before attempt {attempt} ({call_type})",
            )
        try:
            with _concurrent_semaphore:
                kwargs: dict = {"model": model, "messages": messages,
                                "temperature": temperature, "max_tokens": max_tokens,
                                "timeout": effective_timeout}
                if extra_body:
                    kwargs["extra_body"] = extra_body
                if stream:
                    kwargs["stream"] = True
                response = client.chat.completions.create(**kwargs)

            latency_ms = (time.perf_counter() - start) * 1000
            record.latency_ms = latency_ms
            record.retries_used = attempt

            # 提取 token 使用量（非流式响应才有）
            if not stream and hasattr(response, 'usage') and response.usage:
                record.token_usage = TokenUsage(
                    prompt_tokens=response.usage.prompt_tokens or 0,
                    completion_tokens=response.usage.completion_tokens or 0,
                    total_tokens=response.usage.total_tokens or 0,
                )

            _record_call(record)
            return response, record

        except Exception as exc:
            last_error = exc
            record.error_category = classify_error(exc)

            # 不可重试的错误直接抛出
            if record.error_category in (
                LLMErrorCategory.AUTH,
                LLMErrorCategory.MODEL_NOT_FOUND,
                LLMErrorCategory.CONTEXT_LENGTH,
                LLMErrorCategory.CANCELLED,
            ):
                record.latency_ms = (time.perf_counter() - start) * 1000
                record.retries_used = attempt
                if record.error_category == LLMErrorCategory.CANCELLED:
                    record.cancelled = True
                _record_call(record)
                raise

            # 可重试：指数退避（D1：退避等待可被取消即时唤醒）
            if attempt < max_retries:
                backoff = DEFAULT_RETRY_BACKOFF * (2 ** attempt)
                if cancel_event is not None:
                    if cancel_event.wait(backoff):
                        record.error_category = LLMErrorCategory.CANCELLED
                        record.cancelled = True
                        record.latency_ms = (time.perf_counter() - start) * 1000
                        record.retries_used = attempt
                        _record_call(record)
                        raise LLMCancelledError(
                            f"LLM call cancelled during backoff "
                            f"({call_type})",
                        )
                else:
                    time.sleep(backoff)

    # 所有重试耗尽
    record.latency_ms = (time.perf_counter() - start) * 1000
    record.retries_used = max_retries
    _record_call(record)
    raise last_error  # type: ignore


def llm_call_safe(
    call_type: str,
    messages: list[dict],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int = 1000,
    timeout: float | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> tuple[str | None, LLMCallRecord]:
    """安全版 LLM 调用 — 不抛异常，返回 (content, record)。

    失败时 content 为 None，record.error_category 记录原因。
    适用于 decompose/rewrite 等有降级路径的场景。
    """
    try:
        response, record = llm_call(
            call_type=call_type,
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=max_retries,
            stream=False,
        )
        content = response.choices[0].message.content.strip()
        return content, record
    except Exception as exc:
        record = LLMCallRecord(
            call_type=call_type,
            model=model or "unknown",
            latency_ms=0,
            error_category=classify_error(exc),
        )
        _record_call(record)
        return None, record


def clear_client_cache():
    """清除 client 缓存（主要用于测试）。"""
    with _client_cache_lock:
        _client_cache.clear()


def clear_call_records():
    """清除调用记录（主要用于测试）。"""
    global _call_records
    with _call_records_lock:
        _call_records.clear()
