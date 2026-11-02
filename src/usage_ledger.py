"""隐私保护的本地用量台账（P2-1 Option A：provider usage 聚合台账）。

设计约束（``plans/P2-1-REAL-USAGE-COST-OBSERVATION-2026-10-31.md`` §7.2）：

- 默认关闭（``RAG_USAGE_LEDGER`` 未设/off）；仅当开关显式开启且 trace
  consent = ``minimal`` 时写入；
- 每行一次**查询**（不是一次 LLM 调用），只含数值/枚举字段；不写
  query/answer/prompt/context/trace_id/session_id 或任何原文；
- provider 未返回 usage 时 token 字段为 ``null``（绝不写 0，绝不估算）；
- 写入失败只记 debug 日志，绝不影响问答主路径；
- 本地 JSONL、按 UTC 月切分、90 天保留、整目录可删。

读取（只读聚合，不输出行级数据）::

    python -m src.usage_ledger report --days 7
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
RETENTION_DAYS = 90
MAX_MODEL_LEN = 128
FINGERPRINT_LEN = 12

# 台账字段（顺序即落盘 JSON 键顺序）；仅白名单字段可写入。
FIELD_ORDER = (
    "schema_version",
    "ts_bucket",
    "origin",
    "route",
    "outcome",
    "model",
    "tokens_prompt",
    "tokens_completion",
    "tokens_total",
    "llm_calls",
    "retry_count",
    "usage_source",
    "ttft_ms",
    "total_ms",
    "retrieval_k",
    "context_chunks",
    "refusal_stage",
    "cache_hit",
    "config_fingerprint",
    "language_bucket",
)

_ORIGINS = ("user", "evaluation", "test")
_ROUTES = ("sync", "stream")
_OUTCOMES = ("answered", "refused_pre_llm", "refused_post_llm", "error")
_USAGE_SOURCES = ("provider", "partial", "missing", "unsupported")
_REFUSAL_STAGES = ("none", "pre_llm", "post_llm")
_LANGUAGE_BUCKETS = ("cjk", "latin", "mixed", "unknown")

_ENV_TRUTHY = frozenset({"1", "true", "yes", "on"})

# 4 个数值型配置 env 的文档化默认值（与 src/config.py、prepare_answer_evidence
# 同口径）；fingerprint 只哈希这 4 个值，不含任何内容字段。
_FINGERPRINT_ENVS = (
    ("RAG_REFUSAL_THRESHOLD", "0.015"),
    ("RAG_DYNAMIC_MIN_K", "25"),
    ("RAG_CONTEXT_MAX_K", "25"),
    ("RAG_CONTEXT_TOKEN_BUDGET", "7000"),
)

_MONTH_FILE_RE = re.compile(r"usage-(\d{4})-(\d{2})\.jsonl")
_CJK_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]"
)
_LATIN_RE = re.compile(r"[A-Za-z\u00c0-\u024f]")

# 进程级写锁：同进程多线程追加同一日文件；跨进程由 O_APPEND 语义兜底。
_write_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════
# 开关 / 路径 / 时间桶
# ═══════════════════════════════════════════════════════════════

def is_enabled() -> bool:
    """``RAG_USAGE_LEDGER`` 真值（1/true/yes/on），默认关闭。"""
    return os.getenv("RAG_USAGE_LEDGER", "").strip().lower() in _ENV_TRUTHY


def usage_dir() -> Path:
    """台账目录：``${MNEME_DATA_DIR}/usage``，未设时 ``~/.mneme/usage``。"""
    raw = os.getenv("MNEME_DATA_DIR")
    base = Path(raw).expanduser() if raw and raw.strip() else Path.home() / ".mneme"
    return base / "usage"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_day(now: datetime | None = None) -> str:
    return (now or _utc_now()).strftime("%Y-%m-%d")


def _path_for(now: datetime) -> Path:
    return usage_dir() / f"usage-{now.strftime('%Y-%m')}.jsonl"


# ═══════════════════════════════════════════════════════════════
# 字段规范化（白名单 / 枚举 / null 语义）
# ═══════════════════════════════════════════════════════════════

def _enum(value, allowed: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _int_or_none(value) -> int | None:
    """非负整数；缺失/非法/布尔 → None（绝不把缺失写成 0）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _model_name(value) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:MAX_MODEL_LEN]


def _fingerprint_value(value) -> str:
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{12}", value):
        return value
    return config_fingerprint()


def _normalize_row(fields: dict | None) -> dict:
    """只保留 §7.2 白名单字段；schema_version/ts_bucket 由本模块填写。"""
    get = fields.get if isinstance(fields, dict) else (lambda _key: None)
    return {
        "schema_version": SCHEMA_VERSION,
        "ts_bucket": _utc_day(),
        "origin": _enum(get("origin"), _ORIGINS, "user"),
        "route": _enum(get("route"), _ROUTES, "sync"),
        "outcome": _enum(get("outcome"), _OUTCOMES, "error"),
        "model": _model_name(get("model")),
        "tokens_prompt": _int_or_none(get("tokens_prompt")),
        "tokens_completion": _int_or_none(get("tokens_completion")),
        "tokens_total": _int_or_none(get("tokens_total")),
        "llm_calls": _int_or_none(get("llm_calls")) or 0,
        "retry_count": _int_or_none(get("retry_count")) or 0,
        "usage_source": _enum(
            get("usage_source"), _USAGE_SOURCES, "missing"),
        "ttft_ms": _int_or_none(get("ttft_ms")),
        "total_ms": _int_or_none(get("total_ms")) or 0,
        "retrieval_k": _int_or_none(get("retrieval_k")),
        "context_chunks": _int_or_none(get("context_chunks")) or 0,
        "refusal_stage": _enum(
            get("refusal_stage"), _REFUSAL_STAGES, "none"),
        "cache_hit": get("cache_hit") is True,
        "config_fingerprint": _fingerprint_value(get("config_fingerprint")),
        "language_bucket": _enum(
            get("language_bucket"), _LANGUAGE_BUCKETS, "unknown"),
    }


# ═══════════════════════════════════════════════════════════════
# 语言桶 / 配置指纹（只存桶与哈希，不存原文 / 不含内容）
# ═══════════════════════════════════════════════════════════════

def language_bucket(query) -> str:
    """查询的语言桶：cjk / latin / mixed / unknown（用完即弃，不落原文）。"""
    if not isinstance(query, str) or not query:
        return "unknown"
    has_cjk = _CJK_RE.search(query) is not None
    has_latin = _LATIN_RE.search(query) is not None
    if has_cjk and has_latin:
        return "mixed"
    if has_cjk:
        return "cjk"
    if has_latin:
        return "latin"
    return "unknown"


def _canonical_env_number(name: str, default: str) -> str:
    raw = os.getenv(name)
    text = raw.strip() if isinstance(raw, str) and raw.strip() else default
    try:
        number = float(text)
    except (TypeError, ValueError):
        return text
    if not math.isfinite(number):
        return text
    if number == int(number):
        return str(int(number))
    return repr(number)


def config_fingerprint() -> str:
    """4 个数值型 env 的 sha256 前 12 位；未设时用文档化默认值。"""
    payload = "|".join(
        f"{name}={_canonical_env_number(name, default)}"
        for name, default in _FINGERPRINT_ENVS
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:FINGERPRINT_LEN]


# ═══════════════════════════════════════════════════════════════
# 落盘：一行一次查询
# ═══════════════════════════════════════════════════════════════

def _append(path: Path, line: str) -> None:
    """追加一行（测试可 monkeypatch 以模拟写盘失败）。"""
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()


def _cleanup_old_files(directory: Path, now: datetime) -> None:
    """删除整月都早于 90 天保留期的台账文件；失败静默。"""
    cutoff = now - timedelta(days=RETENTION_DAYS)
    try:
        candidates = list(directory.glob("usage-*.jsonl"))
    except OSError:
        return
    for path in candidates:
        match = _MONTH_FILE_RE.fullmatch(path.name)
        if match is None:
            continue
        try:
            year, month = int(match.group(1)), int(match.group(2))
            month_start = datetime(year, month, 1, tzinfo=timezone.utc)
        except ValueError:
            continue
        next_month_start = (month_start + timedelta(days=32)).replace(day=1)
        if next_month_start <= cutoff:
            try:
                path.unlink()
            except OSError:
                pass


def record_query_usage(fields: dict, *, consent_minimal: bool = True) -> None:
    """落一行查询级台账（开关 off / consent 非 minimal 时不写任何文件）。

    写入失败只记 debug 日志并返回；绝不向问答主路径抛出异常。
    """
    if not consent_minimal or not is_enabled():
        return
    try:
        row = _normalize_row(fields)
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        now = _utc_now()
        path = _path_for(now)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            _append(path, line)
            _cleanup_old_files(path.parent, now)
    except Exception:  # noqa: BLE001 - 观测失败必须不影响问答
        log.debug("usage ledger write failed", exc_info=True)


# ═══════════════════════════════════════════════════════════════
# 查询级 collector：每次查询汇总并恰好落一行
# ═══════════════════════════════════════════════════════════════

class QueryUsageCollector:
    """一次查询的用量累加器。

    - ``on_call(payload)``：llm_gateway 每次成功调用回调一次（含 stream 流
      结束时的一次）；累加 calls / retries / tokens / model / ttft；
    - ``mark_partial()``：流中断等场景，最终 ``usage_source="partial"``；
    - ``finish(outcome, ...)``：恰好写一行（幂等），返回该行（未规范化前的
      字段字典）供测试/调用方检查；写入失败不影响调用方。

    token 语义：provider 未返回的字段保持 ``None``（不写 0）；部分调用有
    usage 时只累加已知值，``usage_source="partial"``。
    """

    def __init__(
        self,
        *,
        origin: str = "user",
        route: str = "sync",
        language_bucket_value: str = "unknown",
        consent_minimal: bool = True,
        started_at: float | None = None,
    ) -> None:
        self._origin = _enum(origin, _ORIGINS, "user")
        self._route = _enum(route, _ROUTES, "sync")
        self._language_bucket = _enum(
            language_bucket_value, _LANGUAGE_BUCKETS, "unknown")
        self._consent_minimal = bool(consent_minimal)
        self._started_at = (
            time.perf_counter() if started_at is None else started_at)
        self._lock = threading.Lock()
        self._finished = False
        self._partial = False
        self._llm_calls = 0
        self._retry_count = 0
        self._calls_with_usage = 0
        self._calls_missing_usage = 0
        self._calls_unsupported = 0
        self._prompt = 0
        self._completion = 0
        self._total = 0
        self._have_prompt = False
        self._have_completion = False
        self._have_total = False
        self._model = ""
        self._ttft_ms: int | None = None

    # ── 累加 ────────────────────────────────────────────────

    def on_call(self, payload) -> None:
        """llm_gateway 单次成功调用回调（失败/缺失 usage 的 token 为 None）。"""
        if not isinstance(payload, dict):
            return
        prompt = _int_or_none(payload.get("prompt_tokens"))
        completion = _int_or_none(payload.get("completion_tokens"))
        total = _int_or_none(payload.get("total_tokens"))
        if total is None and prompt is not None and completion is not None:
            total = prompt + completion
        source = payload.get("usage_source")
        retries = _int_or_none(payload.get("retries_used")) or 0
        ttft = _int_or_none(payload.get("ttft_ms"))
        with self._lock:
            if self._finished:
                return
            self._llm_calls += 1
            self._retry_count += retries
            model = _model_name(payload.get("model"))
            if model:
                self._model = model
            if ttft is not None and self._ttft_ms is None:
                self._ttft_ms = ttft
            if source == "partial":
                # 上游明确标注部分/未知（如流中断）：最终来源为 partial。
                self._partial = True
            if (prompt is None and completion is None and total is None):
                # usage 缺失/不支持：不写 0，只标注来源。
                self._calls_missing_usage += 1
                if source == "unsupported":
                    self._calls_unsupported += 1
                return
            self._calls_with_usage += 1
            if prompt is not None:
                self._have_prompt = True
                self._prompt += prompt
            if completion is not None:
                self._have_completion = True
                self._completion += completion
            if total is not None:
                self._have_total = True
                self._total += total

    def mark_partial(self) -> None:
        """标记本查询流被中断（可能已生成 token 但无 usage）。"""
        with self._lock:
            if not self._finished:
                self._partial = True

    # ── 汇总 ────────────────────────────────────────────────

    def _usage_source(self) -> str:
        if self._partial:
            return "partial"
        if self._llm_calls == 0:
            return "missing"
        if self._calls_with_usage == 0:
            if (self._calls_unsupported
                    and self._calls_unsupported == self._llm_calls):
                return "unsupported"
            return "missing"
        if self._calls_with_usage == self._llm_calls:
            return "provider"
        return "partial"

    def _token_totals(self) -> tuple[int | None, int | None, int | None]:
        if self._partial:
            # 流中断：本查询可能已有未知 token，按计划不写部分值。
            return None, None, None
        prompt = self._prompt if self._have_prompt else None
        completion = self._completion if self._have_completion else None
        if self._have_total:
            total = self._total
        elif self._have_prompt and self._have_completion:
            total = self._prompt + self._completion
        else:
            total = None
        return prompt, completion, total

    @property
    def llm_calls(self) -> int:
        return self._llm_calls

    @property
    def retry_count(self) -> int:
        return self._retry_count

    # ── 终态：恰好落一行 ────────────────────────────────────

    def finish(
        self,
        outcome: str = "error",
        *,
        refusal_stage: str = "none",
        retrieval_k: int | None = None,
        context_chunks: int = 0,
        total_ms: int | None = None,
        ttft_ms: int | None = None,
        partial: bool | None = None,
    ) -> dict | None:
        """写入唯一一行；重复调用返回 None（不重复落盘）。"""
        with self._lock:
            if self._finished:
                return None
            self._finished = True
            if partial is not None:
                self._partial = bool(partial)
            prompt, completion, total = self._token_totals()
            if ttft_ms is None:
                ttft_ms = self._ttft_ms
            if total_ms is None:
                total_ms = int((time.perf_counter() - self._started_at) * 1000)
            row = {
                "schema_version": SCHEMA_VERSION,
                "ts_bucket": _utc_day(),
                "origin": self._origin,
                "route": self._route,
                "outcome": _enum(outcome, _OUTCOMES, "error"),
                "model": self._model,
                "tokens_prompt": prompt,
                "tokens_completion": completion,
                "tokens_total": total,
                "llm_calls": self._llm_calls,
                "retry_count": self._retry_count,
                "usage_source": self._usage_source(),
                "ttft_ms": _int_or_none(ttft_ms),
                "total_ms": _int_or_none(total_ms) or 0,
                "retrieval_k": _int_or_none(retrieval_k),
                "context_chunks": _int_or_none(context_chunks) or 0,
                "refusal_stage": _enum(
                    refusal_stage, _REFUSAL_STAGES, "none"),
                "cache_hit": False,
                "config_fingerprint": config_fingerprint(),
                "language_bucket": self._language_bucket,
            }
        record_query_usage(row, consent_minimal=self._consent_minimal)
        return row


# ═══════════════════════════════════════════════════════════════
# 只读聚合读取器（report）
# ═══════════════════════════════════════════════════════════════

# 聚合指标：只输出数值字段的 n/mean/分位数，不输出任何行级原始字段。
_METRIC_FIELDS = (
    "tokens_prompt",
    "tokens_completion",
    "tokens_total",
    "total_ms",
    "llm_calls",
    "retry_count",
    "ttft_ms",
    "context_chunks",
    "retrieval_k",
)


def _quantile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    fraction = position - lower
    return (
        sorted_values[lower]
        + (sorted_values[upper] - sorted_values[lower]) * fraction
    )


def _stats(values) -> dict:
    numbers: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if isinstance(value, float) and not math.isfinite(value):
            continue
        numbers.append(float(value))
    numbers.sort()
    count = len(numbers)
    if count == 0:
        return {"n": 0, "mean": None, "p50": None, "p90": None, "p95": None}
    return {
        "n": count,
        "mean": round(sum(numbers) / count, 3),
        "p50": round(_quantile(numbers, 0.50), 3),
        "p90": round(_quantile(numbers, 0.90), 3),
        "p95": round(_quantile(numbers, 0.95), 3),
    }


def _group_stats(rows: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        value = row.get(key)
        value = value if isinstance(value, str) and value else "unknown"
        groups.setdefault(value, []).append(row)
    return {
        value: {
            "n": len(group),
            "tokens_total": _stats([r.get("tokens_total") for r in group]),
            "total_ms": _stats([r.get("total_ms") for r in group]),
            "llm_calls": _stats([r.get("llm_calls") for r in group]),
        }
        for value, group in sorted(groups.items())
    }


def _read_rows(directory: Path, cutoff_day: str) -> list[dict]:
    rows: list[dict] = []
    try:
        paths = sorted(directory.glob("usage-*.jsonl"))
    except OSError:
        return rows
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(row, dict):
                continue
            ts_bucket = row.get("ts_bucket")
            if not isinstance(ts_bucket, str) or ts_bucket < cutoff_day:
                continue
            rows.append(row)
    return rows


def build_report(
    days: int = 7,
    *,
    now: datetime | None = None,
    directory: Path | None = None,
) -> dict:
    """聚合最近 ``days`` 天（含今天）的台账；忽略损坏行与未知字段。"""
    try:
        days = max(1, int(days))
    except (TypeError, ValueError):
        days = 7
    now = now or _utc_now()
    cutoff_day = (now - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    directory = directory if directory is not None else usage_dir()
    rows = _read_rows(directory, cutoff_day)
    return {
        "days": days,
        "n": len(rows),
        "metrics": {
            field: _stats([row.get(field) for row in rows])
            for field in _METRIC_FIELDS
        },
        "by_model": _group_stats(rows, "model"),
        "by_outcome": _group_stats(rows, "outcome"),
        "by_origin": _group_stats(rows, "origin"),
    }


# ═══════════════════════════════════════════════════════════════
# CLI（只读）
# ═══════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.usage_ledger",
        description="Privacy-preserving local usage ledger (read-only reports).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    report_parser = subparsers.add_parser(
        "report", help="aggregate the last N days (default 7)")
    report_parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)

    if args.command == "report":
        report = build_report(days=args.days)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
