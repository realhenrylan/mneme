"""Shared endpoint and document safety policy.

The RAG application sends retrieved document text to the configured LLM
endpoint.  Keep the policy in a dependency-light module so the CLI, TUI,
query decomposer, and Graph RAG use the same checks.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from src.config import (
    get_settings,
    register_settings_refresh_callback,
    DEFAULT_MAX_DOCUMENT_BYTES,
    DEFAULT_MAX_PDF_PAGES,
    DEFAULT_MAX_REMOTE_CONTEXT_CHARS,
)

# 统一配置契约：资源上限模块常量由 src.config.Settings 派生（唯一默认值
# 来源）。非法环境变量值在 Settings 构造（进程启动）时 fail-fast，发生在
# 任何索引、模型加载、网络或目录写入之前。`.env` 由 src.config 在模块
# 导入时（本行之前）加载，因此这里的导入期 get_settings() 已包含 .env 值。
_SETTINGS = get_settings()

MAX_DOCUMENT_BYTES = _SETTINGS.max_document_bytes
MAX_PDF_PAGES = _SETTINGS.max_pdf_pages
MAX_REMOTE_CONTEXT_CHARS = _SETTINGS.max_remote_context_chars


def _refresh_security_globals() -> None:
    """reset_settings() 回调：资源上限常量重新从当前 Settings 解析。

    公开名称（MAX_DOCUMENT_BYTES/MAX_PDF_PAGES/MAX_REMOTE_CONTEXT_CHARS）
    保留；回调保证 reset 后实际消费者（validate_document_path /
    validate_pdf_page_count 等使用这些常量的路径）不再使用旧值。
    """
    global MAX_DOCUMENT_BYTES, MAX_PDF_PAGES, MAX_REMOTE_CONTEXT_CHARS
    settings = get_settings()
    MAX_DOCUMENT_BYTES = settings.max_document_bytes
    MAX_PDF_PAGES = settings.max_pdf_pages
    MAX_REMOTE_CONTEXT_CHARS = settings.max_remote_context_chars


register_settings_refresh_callback(_refresh_security_globals)


def _positive_int_env(name: str, default: int) -> int:
    """按调用时刻读取 env 的容错解析（remote_context_limit 用）。

    模块常量已由 Settings 派生并在进程启动时 fail-fast；本函数仅服务于
    remote_context_limit() 的既有“每次调用可重载”语义（P1.0 capture 合同
    记录其调用时刻值），不改其行为。
    """
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _is_loopback(hostname: str | None) -> bool:
    return hostname in {"localhost", "127.0.0.1", "::1"}


def endpoint_validation_error(url: str | None) -> str | None:
    """Return a user-facing validation error, or ``None`` when valid.

    HTTPS is required for remote endpoints.  Plain HTTP remains available for
    local development and can be explicitly enabled for a non-local endpoint
    with ``MNEME_ALLOW_INSECURE_HTTP=1``.
    """
    value = (url or "").strip()
    if not value:
        return "Base URL 不能为空"
    if len(value) > 2048:
        return "Base URL 过长"
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        return "Base URL 格式无效"
    if parsed.scheme not in {"http", "https"} or not hostname:
        return "Base URL 必须使用 http:// 或 https:// 并包含主机名"
    if parsed.username or parsed.password:
        return "Base URL 不得包含用户名或密码"
    if parsed.scheme == "http":
        allow_insecure = os.getenv("MNEME_ALLOW_INSECURE_HTTP", "").strip().lower()
        if not _is_loopback(hostname) and allow_insecure not in {"1", "true", "yes", "on"}:
            return "远程 Base URL 必须使用 HTTPS；仅允许本机 HTTP，或显式设置 MNEME_ALLOW_INSECURE_HTTP=1"
    return None


def validate_endpoint(url: str | None) -> str:
    """Validate and return a normalized endpoint URL."""
    value = (url or "").strip()
    error = endpoint_validation_error(value)
    if error:
        raise ValueError(error)
    return value.rstrip("/")


def validate_document_path(filepath: str | os.PathLike[str]) -> str:
    """Validate a document path before it is read or indexed."""
    path = Path(os.path.realpath(os.path.abspath(os.fspath(filepath))))
    if not path.is_file():
        raise ValueError(f"文档不存在或不是普通文件: {path}")
    if path.name == ".env":
        raise ValueError("禁止对 .env 建立索引")

    # 统一配置契约：显式设置 MNEME_DOCUMENT_ROOT 时使用 Settings 已解析
    # （启动时绝对化）的 document_root——不在调用期按当前 CWD 重新解释
    # 原始环境变量，CWD 改变后根目录不会漂移。未显式设置时沿用历史
    # 行为（不施加根目录限制）。
    settings = get_settings()
    if settings.document_root_explicit:
        root = Path(os.path.realpath(os.path.abspath(
            os.fspath(settings.document_root)
        )))
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"文档路径必须位于 MNEME_DOCUMENT_ROOT 下: {root}") from exc

    size = path.stat().st_size
    if size > MAX_DOCUMENT_BYTES:
        limit_mb = MAX_DOCUMENT_BYTES / (1024 * 1024)
        raise ValueError(f"文档超过大小上限 ({limit_mb:.0f} MiB): {path}")
    return str(path)


def validate_pdf_page_count(page_count: int, filepath: str | os.PathLike[str]) -> None:
    if page_count > MAX_PDF_PAGES:
        raise ValueError(
            f"PDF 页数超过上限 ({MAX_PDF_PAGES}): {os.fspath(filepath)}"
        )


def remote_context_limit() -> int:
    """Return the current context cap, allowing tests and long-lived TUI runs to reload it."""
    return _positive_int_env(
        "MNEME_MAX_REMOTE_CONTEXT_CHARS", DEFAULT_MAX_REMOTE_CONTEXT_CHARS,
    )
