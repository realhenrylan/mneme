#!/usr/bin/env python3
"""Read-only aggregate for the local P2-1 usage ledger.

The script reads one monthly JSONL ledger and prints only allowlisted metrics.
It never emits row-level data or any query/answer/prompt/trace/session value.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.usage_ledger import usage_dir  # noqa: E402


FIELDS = {
    "schema_version", "ts_bucket", "origin", "route", "outcome", "model",
    "tokens_prompt", "tokens_completion", "tokens_total", "llm_calls",
    "retry_count", "usage_source", "ttft_ms", "total_ms", "retrieval_k",
    "context_chunks", "refusal_stage", "cache_hit", "config_fingerprint",
    "language_bucket",
}
FORBIDDEN = {"query", "answer", "prompt", "trace_id", "session_id"}
OUTCOMES = ("answered", "refused_pre_llm", "refused_post_llm", "error")
SOURCES = ("provider", "partial", "missing", "unsupported")


def _quantile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = (len(sorted_values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return float(sorted_values[lo])
    frac = pos - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def _stats(values) -> dict:
    numbers = [
        float(v) for v in values
        if isinstance(v, (int, float)) and not isinstance(v, bool)
        and math.isfinite(float(v))
    ]
    numbers.sort()
    if not numbers:
        return {"n": 0, "mean": None, "p50": None, "p90": None, "p95": None}
    return {
        "n": len(numbers),
        "mean": round(sum(numbers) / len(numbers), 3),
        "p50": round(_quantile(numbers, 0.50), 3),
        "p90": round(_quantile(numbers, 0.90), 3),
        "p95": round(_quantile(numbers, 0.95), 3),
    }


def _counts(values, denominator: int) -> dict:
    counts = Counter("unknown" if v is None else str(v) for v in values)
    return {
        key: {"n": count, "share": round(count / denominator, 6) if denominator else None}
        for key, count in sorted(counts.items())
    }


def _group_stats(rows: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        value = row.get(key)
        groups[value if isinstance(value, str) and value else "unknown"].append(row)
    return {
        value: {
            "n": len(group),
            "tokens_total": _stats(r.get("tokens_total") for r in group),
            "total_ms": _stats(r.get("total_ms") for r in group),
            "llm_calls": _stats(r.get("llm_calls") for r in group),
        }
        for value, group in sorted(groups.items())
    }


def _read_rows(path: Path) -> tuple[list[dict], int]:
    rows: list[dict] = []
    malformed = 0
    for line in path.open("r", encoding="utf-8"):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            malformed += 1
            continue
        if not isinstance(raw, dict):
            malformed += 1
            continue
        if FORBIDDEN.intersection(raw):
            raise RuntimeError("forbidden schema field detected; analysis stopped")
        if set(raw) - FIELDS:
            raise RuntimeError("unexpected schema field detected; analysis stopped")
        # Keep only the declared allowlist in memory for aggregation.
        rows.append({key: raw.get(key) for key in FIELDS})
    return rows, malformed


def _group_metrics(rows: list[dict]) -> dict:
    user = [r for r in rows if r.get("origin") == "user"]
    provider = [r for r in user if r.get("usage_source") == "provider"]
    corrected = [r for r in user if r.get("tokens_total") is not None]
    refusal_count = sum(r.get("outcome") in {"refused_pre_llm", "refused_post_llm"} for r in user)
    return {
        "user_rows": len(user),
        "provider_rows": len(provider),
        "corrected_n": len(corrected),
        "tokens_total": _stats(r.get("tokens_total") for r in user),
        "tokens_prompt": _stats(r.get("tokens_prompt") for r in user),
        "tokens_completion": _stats(r.get("tokens_completion") for r in user),
        "refusal_count": refusal_count,
        "refusal_rate_corrected_n": round(refusal_count / len(corrected), 6) if corrected else None,
        "total_ms": _stats(r.get("total_ms") for r in user),
        "ttft_ms": _stats(r.get("ttft_ms") for r in user),
    }


def _t6_status(group: dict) -> str:
    provider_n = group["provider_rows"]
    corrected_n = group["provider_corrected_n"]
    if provider_n == 0:
        return "NO_PROVIDER_USAGE"
    if provider_n < 200 or corrected_n < 200:
        return "INSUFFICIENT_SAMPLE"
    total = group["provider_tokens_total"]
    refusal_rate = group["refusal_rate_corrected_n"]
    if ((total["p95"] is not None and total["p95"] > 18741)
            or (total["mean"] is not None and total["mean"] > 9839)
            or (refusal_rate is not None and not 0.20 <= refusal_rate <= 0.40)):
        return "ABOVE_REVIEW"
    if ((total["p95"] is not None and total["p95"] > 15618)
            or (total["mean"] is not None and total["mean"] > 8658)):
        return "ABOVE_WATCH"
    return "WITHIN_WATCH"


def analyze(path: Path) -> dict:
    rows, malformed = _read_rows(path)
    user = [r for r in rows if r.get("origin") == "user"]
    provider = [r for r in user if r.get("usage_source") == "provider"]
    corrected = [r for r in user if r.get("tokens_total") is not None]
    outcomes = Counter(r.get("outcome") for r in user)
    refusals = outcomes.get("refused_pre_llm", 0) + outcomes.get("refused_post_llm", 0)
    fp_groups: dict[str, list[dict]] = defaultdict(list)
    for row in user:
        fp = row.get("config_fingerprint")
        fp_groups[fp if isinstance(fp, str) and fp else "unknown"].append(row)

    per_config = {}
    for fingerprint, group_rows in sorted(fp_groups.items()):
        group_user = [r for r in group_rows if r.get("origin") == "user"]
        group_provider = [r for r in group_user if r.get("usage_source") == "provider"]
        group_corrected = [r for r in group_provider if r.get("tokens_total") is not None]
        group_refusals = sum(r.get("outcome") in {"refused_pre_llm", "refused_post_llm"} for r in group_user)
        group = {
            "user_rows": len(group_user),
            "provider_rows": len(group_provider),
            "provider_corrected_n": len(group_corrected),
            "provider_tokens_total": _stats(r.get("tokens_total") for r in group_provider),
            "refusal_count": group_refusals,
            "refusal_rate_corrected_n": round(group_refusals / len(group_corrected), 6) if group_corrected else None,
        }
        group["t6_status"] = _t6_status(group)
        per_config[fingerprint] = group

    fingerprints = sorted(fp_groups)
    if len(fingerprints) > 1:
        t6_status = "MIXED_CONFIG"
    elif not provider:
        t6_status = "NO_PROVIDER_USAGE"
    elif per_config:
        t6_status = per_config[fingerprints[0]]["t6_status"]
    else:
        t6_status = "NO_PROVIDER_USAGE"

    bucket_values = [r.get("ts_bucket") for r in user if isinstance(r.get("ts_bucket"), str)]
    retry_values = [r.get("retry_count") for r in user]
    retrieval_values = [r.get("retrieval_k") for r in user]
    context_values = [r.get("context_chunks") for r in user]
    cache_hits = sum(r.get("cache_hit") is True for r in user)
    eval_test_n = sum(r.get("origin") in {"evaluation", "test"} for r in rows)

    return {
        "source": {"ledger_path": str(path.resolve()), "rows_read": len(rows), "malformed_rows_skipped": malformed},
        "window": {
            "first_ts_bucket": min(bucket_values) if bucket_values else None,
            "last_ts_bucket": max(bucket_values) if bucket_values else None,
        },
        "counts": {
            "rows_total": len(rows),
            "origin_user": len(user),
            "origin_evaluation_or_test_excluded": eval_test_n,
            "provider_user_rows": len(provider),
            "provider_token_coverage": round(len(provider) / len(user), 6) if user else None,
            "corrected_n_user_tokens_non_null": len(corrected),
            "fingerprint_count": len(fingerprints),
        },
        "by_origin": _group_stats(rows, "origin"),
        "by_outcome_user": {name: outcomes.get(name, 0) for name in OUTCOMES},
        "by_model": _group_stats(rows, "model"),
        "usage_source_user": _counts((r.get("usage_source") for r in user), len(user)),
        "config_fingerprint_user": _counts((r.get("config_fingerprint") for r in user), len(user)),
        "token_stats_user": {
            "tokens_total": _stats(r.get("tokens_total") for r in user),
            "tokens_prompt": _stats(r.get("tokens_prompt") for r in user),
            "tokens_completion": _stats(r.get("tokens_completion") for r in user),
        },
        "latency_ms_user": {
            "total_ms": _stats(r.get("total_ms") for r in user),
            "ttft_ms": _stats(r.get("ttft_ms") for r in user),
        },
        "refusal_user": {
            "counts": {"refused_pre_llm": outcomes.get("refused_pre_llm", 0),
                       "refused_post_llm": outcomes.get("refused_post_llm", 0)},
            "n": refusals,
            "rate_corrected_n": round(refusals / len(corrected), 6) if corrected else None,
            "rate_all_user": round(refusals / len(user), 6) if user else None,
        },
        "refusal_stage_user": _counts((r.get("refusal_stage") for r in user), len(user)),
        "cache_hit_user": {"n": cache_hits, "ratio": round(cache_hits / len(user), 6) if user else None},
        "retry_count_user": {
            "total": sum(v for v in retry_values if isinstance(v, int) and not isinstance(v, bool)),
            "stats": _stats(retry_values),
            "distribution": _counts(retry_values, len(user)),
        },
        "retrieval_k_user": {"stats": _stats(retrieval_values), "distribution": _counts(retrieval_values, len(user))},
        "context_chunks_user": {"stats": _stats(context_values), "distribution": _counts(context_values, len(user))},
        "by_config_fingerprint": per_config,
        "t6": {
            "status": t6_status,
            "thresholds": {
                "tokens_total_p95_watch": 15618,
                "tokens_total_p95_review": 18741,
                "tokens_total_mean_watch": 8658,
                "tokens_total_mean_review": 9839,
                "refusal_rate_band": [0.20, 0.40],
                "provider_sample_target": 200,
            },
        },
        "quality": {
            "forbidden_schema_keys": [],
            "analysis_uses_only_allowlisted_fields": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=None, help="monthly JSONL path")
    args = parser.parse_args()
    if args.ledger is not None:
        ledger = args.ledger.expanduser()
    else:
        ledger = Path(usage_dir()) / "usage-2026-11.jsonl"
    print(json.dumps(analyze(ledger), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
