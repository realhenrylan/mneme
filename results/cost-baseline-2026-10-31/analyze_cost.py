#!/usr/bin/env python3
"""T6 / P2-1：臂2 成本基线离线分析（一次性脚本，可复算）。

只读 `results/answer-level/` 下的密封产物（report.json / manifest.json /
outcomes*.jsonl），不做任何网络或 LLM 调用，不读取 data/ 下的真实 trace/consent。
输出同目录 `cost.json`；`--check` 模式重算并与已落盘 JSON 比对。

口径约定
- token = prompt_tokens + completion_tokens；M2 的 11 例快速拒答在 outcomes
  中为 `null`，本脚本显式归一为 0，并单独计数（不静默丢弃）。
- 分位数采用线性插值（numpy 默认 / R type-7）：h = (n-1)*k/100，在相邻次序
  统计量间插值后四舍五入到整数 token；n=1 时取该值。该口径与密封 report.md
  的中位数（M2 = 3,485）一致。
- 均值一律注明分母：150（全部）或 122（可答）/ 28（拒答探针）。

用法
    python results/cost-baseline-2026-10-31/analyze_cost.py          # 生成 cost.json
    python results/cost-baseline-2026-10-31/analyze_cost.py --check  # 校验可复现
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ANSWER_LEVEL = ROOT / "results" / "answer-level"
OUT_PATH = HERE / "cost.json"

# ── 输入清单（只读；sha256 取自各自 manifest.json 的 outcomes_sha256）─────
GENERATION_INPUTS = [
    {
        "key": "m2",
        "label": "M2（历史基线）",
        "dir": "m2-baseline-2026-08-30",
        "config": {
            "RAG_REFUSAL_THRESHOLD": 0.03,
            "RAG_DYNAMIC_MIN_K": 12,
            "RAG_CONTEXT_MAX_K": 10,
            "RAG_CONTEXT_TOKEN_BUDGET": 3000,
        },
    },
    {
        "key": "arm1",
        "label": "臂1（V1 阈值 0.015）",
        "dir": "m4c-arm1-2026-09-06",
        "config": {
            "RAG_REFUSAL_THRESHOLD": 0.015,
            "RAG_DYNAMIC_MIN_K": 12,
            "RAG_CONTEXT_MAX_K": 10,
            "RAG_CONTEXT_TOKEN_BUDGET": 3000,
        },
    },
    {
        "key": "arm2",
        "label": "臂2（V1+V3，当前产品默认）",
        "dir": "m4c-arm2-2026-09-06",
        "config": {
            "RAG_REFUSAL_THRESHOLD": 0.015,
            "RAG_DYNAMIC_MIN_K": 25,
            "RAG_CONTEXT_MAX_K": 25,
            "RAG_CONTEXT_TOKEN_BUDGET": 7000,
        },
    },
]

JUDGE_INPUTS = [
    {
        "key": "g1_m2",
        "label": "M3 al2 judge（M2 面，G1 分母）",
        "dir": "m3-judge-2026-09-05",
        "file": "report.json",
        "outcomes": "outcomes-judge.jsonl",
        "tokens_key": "judge_tokens",
    },
    {
        "key": "g1_arm2",
        "label": "M5 臂2 al2 judge（臂2 面，G1 分母）",
        "dir": "m4c-arm2-judge-2026-09-06",
        "file": "report.json",
        "outcomes": "outcomes-judge.jsonl",
        "tokens_key": "judge_tokens",
    },
    {
        "key": "g2_m2",
        "label": "M5b al3 v1.1（M2 探针 28）",
        "dir": "m5b-m2-refusal-judge-v11-2026-09-06",
        "file": "report.json",
        "outcomes": "outcomes-refusal-judge.jsonl",
        "tokens_key": "refusal_judge_tokens",
    },
    {
        "key": "g2_arm1",
        "label": "M5b al3 v1.1（臂1 探针 28）",
        "dir": "m5b-arm1-refusal-judge-v11-2026-09-06",
        "file": "report.json",
        "outcomes": "outcomes-refusal-judge.jsonl",
        "tokens_key": "refusal_judge_tokens",
    },
    {
        "key": "g2_arm2",
        "label": "M5b al3 v1.1（臂2 探针 28）",
        "dir": "m5b-arm2-refusal-judge-v11-2026-09-06",
        "file": "report.json",
        "outcomes": "outcomes-refusal-judge.jsonl",
        "tokens_key": "refusal_judge_tokens",
    },
]

# G1 修正率（partial 计 0.5）取自密封裁决产物；臂1 未跑 al2 judge，故缺失。
G1_SEALED = {
    "m2": {"g1_corrected_rate": 0.4397, "g1_conservative_rate": 0.4195, "source": "results/answer-level/m3-judge-2026-09-05/report.json"},
    "arm1": {"g1_corrected_rate": None, "g1_conservative_rate": None, "source": None},
    "arm2": {"g1_corrected_rate": 0.5575, "g1_conservative_rate": 0.5402, "source": "results/answer-level/m5d-decision-2026-09-06/machine.json"},
}

# M5d 三基线对照（密封报告 §2）；仅用于交叉校验，不参与计算。
SEALED_REFERENCE = {
    "m2": {"g1": 0.4397, "g2prime": 1.0, "false_refusal_rate": 0.3934, "semantic_refusal": 1.0, "lexical_refusal_accuracy": 0.3929},
    "arm1": {"g1": None, "g2prime": 0.9286, "false_refusal_rate": 0.2131, "semantic_refusal": 0.9286, "lexical_refusal_accuracy": 0.25},
    "arm2": {"g1": 0.5575, "g2prime": 1.0, "false_refusal_rate": 0.1393, "semantic_refusal": 1.0, "lexical_refusal_accuracy": 0.1786},
}


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_jsonl(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def r2(value):
    return None if value is None else round(float(value), 2)


def percentile(values, k: float):
    """线性插值分位（numpy 默认 / R type-7），与密封 report.md 的中位口径一致。

    h = (n-1) * k/100；结果在相邻两个次序统计量间线性插值，最后四舍五入到整数 token。
    n=1 时直接返回该值。
    """
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    if n == 1:
        return int(round(ordered[0]))
    h = (n - 1) * k / 100.0
    lo = int(math.floor(h))
    hi = int(math.ceil(h))
    if lo == hi:
        return int(round(ordered[lo]))
    frac = h - lo
    value = ordered[lo] + frac * (ordered[hi] - ordered[lo])
    return int(round(value))


def describe(values):
    if not values:
        return {"n": 0}
    n = len(values)
    total = sum(values)
    mean = total / n
    sd = statistics.pstdev(values) if n > 1 else 0.0
    return {
        "n": n,
        "sum": total,
        "mean": r2(mean),
        "min": min(values),
        "p50": percentile(values, 50),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
        "max": max(values),
        "sd": r2(sd),
        "cv": r2(sd / mean) if mean else None,
    }


def tokens_of(row):
    """null 归一为 0；返回 (prompt, completion, had_null)。"""
    prompt = row.get("prompt_tokens")
    completion = row.get("completion_tokens")
    had_null = prompt is None or completion is None
    return int(prompt or 0), int(completion or 0), had_null


def build():
    baselines = {}
    raw = {}

    for spec in GENERATION_INPUTS:
        out_dir = ANSWER_LEVEL / spec["dir"]
        report = load_json(out_dir / "report.json")
        manifest = load_json(out_dir / "manifest.json")
        outcomes_path = out_dir / "outcomes.jsonl"
        rows = load_jsonl(outcomes_path)
        raw[spec["key"]] = rows

        actual_sha = sha256_of(outcomes_path)
        expected_sha = manifest.get("outcomes_sha256")

        prompt_sum = completion_sum = 0
        null_cases = []
        per_case = {}
        groups = {"answerable": [], "refusal_probe": []}
        latency_groups = {"answerable": [], "refusal_probe": []}
        tokens = []
        prompts = []
        completions = []
        latencies = []
        latency_token_bearing = []

        for row in rows:
            prompt, completion, had_null = tokens_of(row)
            total = prompt + completion
            prompt_sum += prompt
            completion_sum += completion
            if had_null:
                null_cases.append(row["case_id"])
            per_case[row["case_id"]] = {
                "prompt": prompt,
                "completion": completion,
                "total": total,
                "generation_ms": r2(row.get("generation_ms")),
                "should_refuse": bool(row["should_refuse"]),
                "query_type": row.get("query_type"),
            }
            tokens.append(total)
            prompts.append(prompt)
            completions.append(completion)
            gen_ms = row.get("generation_ms")
            if gen_ms is not None:
                latencies.append(float(gen_ms))
                if total > 0:
                    latency_token_bearing.append(float(gen_ms))
            bucket = "refusal_probe" if row["should_refuse"] else "answerable"
            groups[bucket].append(total)
            if gen_ms is not None:
                latency_groups[bucket].append(float(gen_ms))

        total_sum = prompt_sum + completion_sum
        case_count = len(rows)
        answerable = groups["answerable"]
        probes = groups["refusal_probe"]

        baselines[spec["key"]] = {
            "label": spec["label"],
            "dir": f"results/answer-level/{spec['dir']}",
            "config": spec["config"],
            "case_count": case_count,
            "answerable_count": len(answerable),
            "refusal_probe_count": len(probes),
            "prompt_tokens_sum": prompt_sum,
            "completion_tokens_sum": completion_sum,
            "total_tokens_sum": total_sum,
            "prompt_share": round(prompt_sum / total_sum, 4),
            "prompt_share_pct": round(prompt_sum / total_sum * 100, 1),
            "completion_share": round(completion_sum / total_sum, 4),
            "completion_share_pct": round(completion_sum / total_sum * 100, 1),
            "prompt_per_completion": round(prompt_sum / completion_sum, 2),
            "per_case_all": {
                "mean_prompt": r2(prompt_sum / case_count),
                "mean_completion": r2(completion_sum / case_count),
                "mean_total": r2(total_sum / case_count),
                "median_total": percentile(tokens, 50),
            },
            "per_case_token_bearing": {
                "n": case_count - len(null_cases),
                "mean_total": r2(total_sum / (case_count - len(null_cases))),
                "note": "密封 report.json 的 *_avg 字段实际分母（M2=139）" if null_cases else "无零 token 例，与全量分母一致",
            },
            "null_token_cases": {
                "count": len(null_cases),
                "share_of_cases_pct": round(len(null_cases) / case_count * 100, 1),
                "case_ids": sorted(null_cases),
                "answerable": sum(1 for cid in null_cases if not per_case[cid]["should_refuse"]),
                "refusal_probe": sum(1 for cid in null_cases if per_case[cid]["should_refuse"]),
            },
            "distributions": {
                "total_tokens": {
                    "all": describe(tokens),
                    "answerable": describe(answerable),
                    "refusal_probe": describe(probes),
                },
                "prompt_tokens": {
                    "all": describe(prompts),
                    "answerable": describe([per_case[c]["prompt"] for c in per_case if not per_case[c]["should_refuse"]]),
                    "refusal_probe": describe([per_case[c]["prompt"] for c in per_case if per_case[c]["should_refuse"]]),
                },
                "completion_tokens": {
                    "all": describe(completions),
                    "answerable": describe([per_case[c]["completion"] for c in per_case if not per_case[c]["should_refuse"]]),
                    "refusal_probe": describe([per_case[c]["completion"] for c in per_case if per_case[c]["should_refuse"]]),
                },
            },
            "latency_ms": {
                "field": "generation_ms（端到端生成耗时，与 total_ms 相同；非 TTFT，retrieval_ms 恒为 0）",
                "all": describe(latencies),
                "token_bearing": describe(latency_token_bearing),
                "answerable": describe(latency_groups["answerable"]),
                "refusal_probe": describe(latency_groups["refusal_probe"]),
            },
            "sealed_crosscheck": {
                "report_total_tokens_sum": report.get("total_tokens_sum"),
                "recomputed_total_tokens_sum": total_sum,
                "total_tokens_match": report.get("total_tokens_sum") == total_sum,
                "report_prompt_tokens_sum": report.get("prompt_tokens_sum"),
                "recomputed_prompt_tokens_sum": prompt_sum,
                "prompt_tokens_match": report.get("prompt_tokens_sum") == prompt_sum,
                "report_completion_tokens_sum": report.get("completion_tokens_sum"),
                "recomputed_completion_tokens_sum": completion_sum,
                "completion_tokens_match": report.get("completion_tokens_sum") == completion_sum,
                "report_total_tokens_avg": report.get("total_tokens_avg"),
                "report_avg_denominator": round(total_sum / report["total_tokens_avg"], 2) if report.get("total_tokens_avg") else None,
            },
            "outcomes_sha256": {
                "expected": expected_sha,
                "actual": actual_sha,
                "match": expected_sha == actual_sha,
            },
            "per_case": per_case,
        }

    # ── 对比：倍数、拆分、逐例差分 ─────────────────────────────────────
    m2 = baselines["m2"]
    arm1 = baselines["arm1"]
    arm2 = baselines["arm2"]
    multi = {
        "arm1_over_m2": {
            "ratio": round(arm1["total_tokens_sum"] / m2["total_tokens_sum"], 3),
            "delta_tokens": arm1["total_tokens_sum"] - m2["total_tokens_sum"],
            "delta_pct": round((arm1["total_tokens_sum"] / m2["total_tokens_sum"] - 1) * 100, 1),
            "per_case_ratio": round(arm1["per_case_all"]["mean_total"] / m2["per_case_all"]["mean_total"], 3),
            "prompt_ratio": round(arm1["prompt_tokens_sum"] / m2["prompt_tokens_sum"], 3),
            "completion_ratio": round(arm1["completion_tokens_sum"] / m2["completion_tokens_sum"], 3),
        },
        "arm2_over_m2": {
            "ratio": round(arm2["total_tokens_sum"] / m2["total_tokens_sum"], 3),
            "delta_tokens": arm2["total_tokens_sum"] - m2["total_tokens_sum"],
            "delta_pct": round((arm2["total_tokens_sum"] / m2["total_tokens_sum"] - 1) * 100, 1),
            "per_case_ratio": round(arm2["per_case_all"]["mean_total"] / m2["per_case_all"]["mean_total"], 3),
            "prompt_ratio": round(arm2["prompt_tokens_sum"] / m2["prompt_tokens_sum"], 3),
            "completion_ratio": round(arm2["completion_tokens_sum"] / m2["completion_tokens_sum"], 3),
            "prompt_delta": arm2["prompt_tokens_sum"] - m2["prompt_tokens_sum"],
            "prompt_delta_pct": round((arm2["prompt_tokens_sum"] / m2["prompt_tokens_sum"] - 1) * 100, 1),
            "prompt_delta_per_case": r2((arm2["prompt_tokens_sum"] - m2["prompt_tokens_sum"]) / 150),
            "completion_delta": arm2["completion_tokens_sum"] - m2["completion_tokens_sum"],
            "completion_delta_pct": round((arm2["completion_tokens_sum"] / m2["completion_tokens_sum"] - 1) * 100, 1),
            "prompt_share_of_delta": round((arm2["prompt_tokens_sum"] - m2["prompt_tokens_sum"]) / (arm2["total_tokens_sum"] - m2["total_tokens_sum"]), 4),
            "prompt_share_of_delta_pct": round((arm2["prompt_tokens_sum"] - m2["prompt_tokens_sum"]) / (arm2["total_tokens_sum"] - m2["total_tokens_sum"]) * 100, 2),
        },
        "arm2_over_arm1": {
            "ratio": round(arm2["total_tokens_sum"] / arm1["total_tokens_sum"], 3),
            "delta_tokens": arm2["total_tokens_sum"] - arm1["total_tokens_sum"],
            "delta_pct": round((arm2["total_tokens_sum"] / arm1["total_tokens_sum"] - 1) * 100, 1),
        },
        "sealed_report_means": {
            "m2_report_avg": 3176.2,
            "arm1_report_avg": 3855.0,
            "arm2_report_avg": 7871.4,
            "note": "M2 的 *_avg 分母是 139（token>0 的例），臂1/臂2 分母是 150；混用会低估 arm2/m2 约 7.3%",
            "m2_avg_overstatement_pct": round((m2["per_case_token_bearing"]["mean_total"] / m2["per_case_all"]["mean_total"] - 1) * 100, 1),
            "naive_ratio_using_report_means": round(arm2["per_case_all"]["mean_total"] / m2["per_case_token_bearing"]["mean_total"], 3),
            "naive_ratio_understatement_pct": round(
                (1 - (arm2["per_case_all"]["mean_total"] / m2["per_case_token_bearing"]["mean_total"]) / (arm2["total_tokens_sum"] / m2["total_tokens_sum"])) * 100,
                1,
            ),
        },
    }

    # 逐例差分（按 case_id 对齐；M2 null 视为 0）
    m2_cases = m2["per_case"]
    arm2_cases = arm2["per_case"]
    assert set(m2_cases) == set(arm2_cases), "case_id 集合不一致"
    deltas = {cid: arm2_cases[cid]["total"] - m2_cases[cid]["total"] for cid in m2_cases}
    delta_values = list(deltas.values())
    top10 = sorted(deltas.items(), key=lambda kv: kv[1], reverse=True)[:10]
    zero_ids = m2["null_token_cases"]["case_ids"]
    zero_arm2_sum = sum(arm2_cases[cid]["total"] for cid in zero_ids)
    zero_arm2_mean = zero_arm2_sum / len(zero_ids)
    other_ids = [cid for cid in m2_cases if cid not in set(zero_ids)]
    other_arm2_sum = sum(arm2_cases[cid]["total"] for cid in other_ids)
    other_m2_sum = sum(m2_cases[cid]["total"] for cid in other_ids)
    total_delta = arm2["total_tokens_sum"] - m2["total_tokens_sum"]

    delta_block = {
        "matched_cases": len(deltas),
        "delta_total": total_delta,
        "delta_mean_per_case": r2(total_delta / len(deltas)),
        "distribution": describe(delta_values),
        "cases_cheaper_under_arm2": sum(1 for v in delta_values if v < 0),
        "cases_unchanged": sum(1 for v in delta_values if v == 0),
        "top10": [{"case_id": cid, "delta": val} for cid, val in top10],
        "top10_delta_share": round(sum(val for _, val in top10) / total_delta, 4),
        "top10_delta_share_pct": round(sum(val for _, val in top10) / total_delta * 100, 2),
        "by_label": {
            "answerable": {
                "n": m2["answerable_count"],
                "delta_mean": r2(
                    (arm2["distributions"]["total_tokens"]["answerable"]["sum"]
                     - m2["distributions"]["total_tokens"]["answerable"]["sum"]) / m2["answerable_count"]
                ),
                "delta_sum": arm2["distributions"]["total_tokens"]["answerable"]["sum"] - m2["distributions"]["total_tokens"]["answerable"]["sum"],
            },
            "refusal_probe": {
                "n": m2["refusal_probe_count"],
                "delta_mean": r2(
                    (arm2["distributions"]["total_tokens"]["refusal_probe"]["sum"]
                     - m2["distributions"]["total_tokens"]["refusal_probe"]["sum"]) / m2["refusal_probe_count"]
                ),
                "delta_sum": arm2["distributions"]["total_tokens"]["refusal_probe"]["sum"] - m2["distributions"]["total_tokens"]["refusal_probe"]["sum"],
            },
        },
        "zero_token_attribution": {
            "case_count": len(zero_ids),
            "arm2_tokens_sum": zero_arm2_sum,
            "arm2_tokens_mean": r2(zero_arm2_mean),
            "arm2_tokens_share_of_total": round(zero_arm2_sum / arm2["total_tokens_sum"], 4),
            "arm2_tokens_share_of_total_pct": round(zero_arm2_sum / arm2["total_tokens_sum"] * 100, 2),
            "delta_sum": zero_arm2_sum,
            "delta_share_of_total_delta": round(zero_arm2_sum / total_delta, 4),
            "delta_share_of_total_delta_pct": round(zero_arm2_sum / total_delta * 100, 2),
            "other_139_cases": {
                "m2_sum": other_m2_sum,
                "arm2_sum": other_arm2_sum,
                "delta_sum": other_arm2_sum - other_m2_sum,
                "ratio": round(other_arm2_sum / other_m2_sum, 3),
                "delta_pct": round((other_arm2_sum / other_m2_sum - 1) * 100, 1),
            },
            "m2_total_if_zero_cases_priced_at_m2_mean": m2["total_tokens_sum"] + round(zero_arm2_mean * 0) + m2["per_case_all"]["mean_total"] * len(zero_ids),
            "note": "按 M2 自身 150 例均值给 11 例计价后的假设总量与倍数见 report.md §8",
        },
    }
    # 若按 M2 自身均值给这 11 例计价，M2 假设总量与 arm2/m2 倍数
    hypothetical_m2 = m2["total_tokens_sum"] + m2["per_case_all"]["mean_total"] * len(zero_ids)
    delta_block["zero_token_attribution"]["m2_total_if_zero_cases_priced_at_m2_mean"] = r2(hypothetical_m2)
    delta_block["zero_token_attribution"]["hypothetical_ratio"] = round(arm2["total_tokens_sum"] / hypothetical_m2, 3)
    delta_block["zero_token_attribution"]["hypothetical_delta_pct"] = round((arm2["total_tokens_sum"] / hypothetical_m2 - 1) * 100, 1)

    # ── G1 与 token 的兑换率 ───────────────────────────────────────────
    g1_delta_points = round((0.5575 - 0.4397) * 174, 1)
    g1 = {
        "rates": G1_SEALED,
        "face": {
            "points_total": 174,
            "judged_points": 154,
            "mechanical_hit": 20,
            "denominator_note": "G1 = (20 + judge_hit + 0.5*partial) / 174；两基线同面（M5d face_consistent=true）",
            "m2_corrected_points": round(0.4397 * 174, 1),
            "arm2_corrected_points": round(0.5575 * 174, 1),
            "corrected_points_delta": g1_delta_points,
        },
        "marginal_cost": {
            "delta_tokens_total": total_delta,
            "delta_tokens_per_case": r2(total_delta / 150),
            "delta_g1_corrected": round(0.5575 - 0.4397, 4),
            "delta_g1_conservative": round(0.5402 - 0.4195, 4),
            "tokens_per_0.01_g1_total": r2(total_delta / ((0.5575 - 0.4397) / 0.01)),
            "tokens_per_0.01_g1_per_case": r2(total_delta / 150 / ((0.5575 - 0.4397) / 0.01)),
            "tokens_per_0.01_g1_conservative_total": r2(total_delta / ((0.5402 - 0.4195) / 0.01)),
            "tokens_per_0.01_g1_per_case_conservative": r2(total_delta / 150 / ((0.5402 - 0.4195) / 0.01)),
            "tokens_per_additional_corrected_point": r2(total_delta / g1_delta_points),
            "tokens_per_1000_queries_per_0.01_g1": r2(total_delta / 150 / ((0.5575 - 0.4397) / 0.01) * 1000),
            "as_share_of_m2_per_query_cost": round(
                (total_delta / 150 / ((0.5575 - 0.4397) / 0.01)) / m2["per_case_all"]["mean_total"], 4
            ),
            "as_pct_of_m2_per_query_cost": round(
                (total_delta / 150 / ((0.5575 - 0.4397) / 0.01)) / m2["per_case_all"]["mean_total"] * 100, 2
            ),
            "note": "毛成本兑换率：臂2 同时改了 V1 阈值、V3 档位并移除免费拒答路径，不能作单变量因果价格",
        },
    }

    # ── judge 侧（单独列，不与生成混算）────────────────────────────────
    judge_entries = {}
    judge_total = 0
    for spec in JUDGE_INPUTS:
        out_dir = ANSWER_LEVEL / spec["dir"]
        payload = load_json(out_dir / spec["file"])
        manifest = load_json(out_dir / "manifest.json")
        tokens = payload[spec["tokens_key"]]
        reported_total = tokens["total_tokens"]
        recomputed = tokens["prompt_tokens"] + tokens["completion_tokens"]
        judge_total += reported_total
        outcomes_path = out_dir / spec["outcomes"]
        expected_outcomes_sha = manifest.get("outcomes_sha256")
        actual_outcomes_sha = sha256_of(outcomes_path)
        entry = {
            "label": spec["label"],
            "dir": f"results/answer-level/{spec['dir']}",
            "protocol": manifest.get("judge_protocol_version"),
            "model": tokens.get("models"),
            "calls": tokens["calls"],
            "prompt_tokens": tokens["prompt_tokens"],
            "completion_tokens": tokens["completion_tokens"],
            "total_tokens": reported_total,
            "tokens_per_call": r2(reported_total / tokens["calls"]),
            "sum_recomputed": recomputed,
            "sum_consistent": reported_total == recomputed,
            "outcomes_sha256": {
                "expected": expected_outcomes_sha,
                "actual": actual_outcomes_sha,
                "match": expected_outcomes_sha == actual_outcomes_sha,
            },
            "judged_count": payload.get("judged_count"),
            "total_points": payload.get("total_points"),
        }
        if spec["key"].startswith("g1"):
            entry["tokens_per_judged_point"] = r2(reported_total / payload["total_points"])
        else:
            entry["probe_count"] = payload.get("probe_count")
            entry["tokens_per_probe"] = r2(reported_total / payload["probe_count"])
        judge_entries[spec["key"]] = entry

    judge_block = {
        "policy": "judge 调用是评测/回放的一次性成本，不进入单次用户查询；本块独立于生成侧统计",
        "entries": judge_entries,
        "total_tokens_v11": judge_total,
        "by_face": {
            "g1": {
                "total_tokens": judge_entries["g1_m2"]["total_tokens"] + judge_entries["g1_arm2"]["total_tokens"],
                "share_of_m2_generation": round(judge_entries["g1_m2"]["total_tokens"] / m2["total_tokens_sum"], 4),
                "share_of_m2_generation_pct": round(judge_entries["g1_m2"]["total_tokens"] / m2["total_tokens_sum"] * 100, 2),
                "share_of_arm2_generation": round(judge_entries["g1_arm2"]["total_tokens"] / arm2["total_tokens_sum"], 4),
                "share_of_arm2_generation_pct": round(judge_entries["g1_arm2"]["total_tokens"] / arm2["total_tokens_sum"] * 100, 2),
                "note": "G1 judge 相对其判定的那次生成评测的开销占比（6%~15%）",
            },
            "g2prime": {
                "total_tokens": sum(judge_entries[k]["total_tokens"] for k in ("g2_m2", "g2_arm1", "g2_arm2")),
                "per_probe_mean": r2(sum(judge_entries[k]["total_tokens"] for k in ("g2_m2", "g2_arm1", "g2_arm2")) / 84),
            },
        },
        "history_excluded": {
            "al3_v1_tokens": 36032,
            "note": "al3 v1 轮（m5b-*-refusal-judge-2026-09-06）合计 36,032，属协议迭代的历史成本；为避免与 v1.1 双计，未计入 total_tokens_v11。M5d 披露的 al3 两轮 ≈8.6 万 = v1 3.6 万 + v1.1 4.8 万",
        },
        "all_judge_including_v1": judge_total + 36032,
    }

    # ── 外推：每 1,000 次查询 ──────────────────────────────────────────
    mix = {
        "answerable": m2["answerable_count"] / 150,
        "refusal_probe": m2["refusal_probe_count"] / 150,
    }
    extrapolation = {
        "unit": "tokens",
        "assumptions": [
            "查询与 v2.1 基准同分布：可答 122/150（81.3%）、不可答探针 28/150（18.7%）",
            "单轮问答；不含多轮对话累积的上下文增长",
            "prompt 模板、检索深度、模型与答案长度维持评测时配置（臂2 = 25 块 / 7,000 token 预算）",
            "不含缓存命中、重试、失败重放；不含 embedding 侧 token（评测未计量）",
            "不含 judge/监控开销（见 §7，单独列示）",
        ],
        "eval_mix": {k: round(v, 4) for k, v in mix.items()},
        "eval_mix_pct": {k: round(v * 100, 2) for k, v in mix.items()},
        "per_1000_queries": {
            key: {
                "eval_mix": {
                    "total": round(1000 * baselines[key]["per_case_all"]["mean_total"]),
                    "prompt": round(1000 * baselines[key]["per_case_all"]["mean_prompt"]),
                    "completion": round(1000 * baselines[key]["per_case_all"]["mean_completion"]),
                },
                "all_answerable": round(1000 * baselines[key]["distributions"]["total_tokens"]["answerable"]["mean"]),
                "all_refusal_probe": round(1000 * baselines[key]["distributions"]["total_tokens"]["refusal_probe"]["mean"]),
            }
            for key in ("m2", "arm1", "arm2")
        },
        "delta_per_1000_queries_arm2_minus_m2": {
            "eval_mix": round(1000 * (arm2["per_case_all"]["mean_total"] - m2["per_case_all"]["mean_total"])),
            "all_answerable": round(1000 * (arm2["distributions"]["total_tokens"]["answerable"]["mean"] - m2["distributions"]["total_tokens"]["answerable"]["mean"])),
        },
        "scale_examples": {
            "1000_queries_per_day_monthly_tokens": {
                "m2": round(1000 * m2["per_case_all"]["mean_total"] * 30),
                "arm2": round(1000 * arm2["per_case_all"]["mean_total"] * 30),
            },
            "note": "仅量级示例，不是预算承诺；30 天/月",
        },
    }

    # ── 观察方案阈值（从臂2 基线派生，倍数为政策选择）───────────────────
    arm2_p95 = arm2["distributions"]["total_tokens"]["all"]["p95"]
    arm2_mean = arm2["per_case_all"]["mean_total"]
    arm2_cv = arm2["distributions"]["total_tokens"]["all"]["cv"]
    arm2_false_refusal = SEALED_REFERENCE["arm2"]["false_refusal_rate"]
    implied_refusal_rate = round((28 + arm2_false_refusal * 122) / 150, 4)
    z_alpha = 1.959964
    z_power = 0.841621
    sample_factor = 2 * (z_alpha + z_power) ** 2
    thresholds = {
        "p95_tokens_per_query": {
            "baseline": arm2_p95,
            "warn_multiplier": 1.25,
            "warn": round(arm2_p95 * 1.25),
            "recheck_multiplier": 1.5,
            "recheck": round(arm2_p95 * 1.5),
            "window": "7 日滚动",
        },
        "mean_tokens_per_query": {
            "baseline": arm2_mean,
            "warn_multiplier": 1.1,
            "warn": round(arm2_mean * 1.1),
            "recheck_multiplier": 1.25,
            "recheck": round(arm2_mean * 1.25),
            "window": "7 日滚动",
        },
        "refusal_rate": {
            "baseline_eval_mix_derived": implied_refusal_rate,
            "derivation": "(28 探针正确拒答 + 0.1393*122 误拒) / 150；非逐例标签复算",
            "warn_band": [0.20, 0.40],
            "recheck_drift_pp": 10,
            "window": "7 日滚动，连续 3 日越界",
        },
        "ttft_ms": {
            "baseline": None,
            "note": "密封产物无 TTFT 字段（只有 generation_ms 全生成耗时，retrieval_ms 恒为 0）；阈值是初始政策值，需首批真实数据校准",
            "warn_mean": 1500,
            "recheck_mean": 2000,
            "recheck_p95": 3000,
            "generation_ms_proxy_baseline": arm2["latency_ms"]["all"]["mean"],
        },
        "false_refusal_rate": {
            "baseline_m2": SEALED_REFERENCE["m2"]["false_refusal_rate"],
            "baseline_arm2": arm2_false_refusal,
            "recheck_above": 0.20,
            "measurement": "仅能由带标签的 150 例回放测得；生产侧无标签",
        },
        "quality_regression": {
            "g1_gate": 0.55,
            "g1_recheck_below": 0.55,
            "g1_rollback_below": 0.52,
            "g2prime_gate": 0.90,
            "note": "G1 门禁 0.55 来自 M5d 预注册；0.52 为本报告建议的硬回退线（保留 0.0375 余量）",
        },
        "sample_size": {
            "basis": "两样本均值比较，α=0.05 双侧、power=0.80：n = 2*(1.96+0.8416)^2*(CV/δ)^2；CV 取臂2 逐例 total token 的 CV",
            "alpha": 0.05,
            "power": 0.80,
            "cv": arm2_cv,
            "n_per_window_delta_10pct": int(math.ceil(sample_factor * (arm2_cv / 0.10) ** 2)),
            "n_per_window_delta_15pct": int(math.ceil(sample_factor * (arm2_cv / 0.15) ** 2)),
            "p95_stability_n": 1000,
            "note": "未计日间流量构成漂移（overdispersion），实际样本量应上浮；建议以「≥1,000 查询/周」为最小观察窗口，低于此量级只看周均值与总量，不看 p95",
        },
    }

    consistency = {
        "generation_sums_match_sealed_report": all(
            baselines[k]["sealed_crosscheck"]["total_tokens_match"] for k in ("m2", "arm1", "arm2")
        ),
        "outcomes_sha256_match_manifest": all(
            baselines[k]["outcomes_sha256"]["match"] for k in ("m2", "arm1", "arm2")
        ),
        "judge_sums_recomputed": all(judge_entries[k]["sum_consistent"] for k in judge_entries),
        "judge_outcomes_sha256_match_manifest": all(
            judge_entries[k]["outcomes_sha256"]["match"] for k in judge_entries
        ),
        "case_counts_expected": {
            k: baselines[k]["case_count"] == 150 and baselines[k]["answerable_count"] == 122 and baselines[k]["refusal_probe_count"] == 28
            for k in ("m2", "arm1", "arm2")
        },
        "m2_report_avg_denominator": baselines["m2"]["sealed_crosscheck"]["report_avg_denominator"],
        "g1_face_consistent": round(0.4397 * 174, 1) == 76.5 and round(0.5575 * 174, 1) == 97.0,
        "report_md_numbers_checked_by": "人工 + `grep` 抽查（见 report.md §11）",
    }

    gaps = [
        {
            "id": "G-1",
            "severity": "high",
            "issue": "臂1 未跑 al2 judge，无 G1；V1 与 V3 的边际成本/收益无法分别归因",
            "impact": "成本-质量曲线在臂1 处断裂；本报告的 G1 兑换率是 V1+V3 的合成价格",
            "fix": "若需归因，补跑臂1 面 al2 judge（约 7 万 token / 180 calls）",
        },
        {
            "id": "G-2",
            "severity": "high",
            "issue": "M2 的 11 例快速拒答在 outcomes 中 prompt_tokens/completion_tokens 为 null（非 0）；密封 report 的 *_avg 分母为 139",
            "impact": "直接比较密封均值会低估 arm2/m2 倍数约 7.3%（2.478 vs 2.674）；下游 sum() 需显式 null→0",
            "fix": "读取方统一 null→0 并统一 150 分母；或在 M2 产物侧补 0（不改密封件，只在派生层归一）",
        },
        {
            "id": "G-3",
            "severity": "high",
            "issue": "无 TTFT 字段；retrieval_ms 恒为 0（检索/生成未拆分计时）",
            "impact": "无法用密封数据设定 TTFT 阈值，只能以 generation_ms 作代理；延迟观察方案需新增埋点",
            "fix": "生产侧记录 ttft_ms 与 retrieval_ms；评测侧后续加同名字段",
        },
        {
            "id": "G-4",
            "severity": "medium",
            "issue": "judge 只有聚合 token，无逐例/逐点计量",
            "impact": "无法按 case 或 query_type 拆分 judge 成本，也无法核对单次调用异常",
            "fix": "judge runner 输出每次调用的 token 记录（不改判据）",
        },
        {
            "id": "G-5",
            "severity": "medium",
            "issue": "token 只覆盖生成调用；embedding/检索侧与 reranker 的 token/算力未计量（默认 reranker=none）",
            "impact": "若未来开启远端 embedding 或 reranker，成本基线不完整",
            "fix": "在成本基线中单列 embedding/reranker 行，或明确声明不计",
        },
        {
            "id": "G-6",
            "severity": "medium",
            "issue": "n=150，p90/p95 尾部不稳（p95 = 第 143 个次序统计量）",
            "impact": "阈值参考值有抽样误差；单日小样本 p95 抖动大",
            "fix": "阈值用 7 日滚动；样本量按 §12.4 估算（≥1,000 查询/周）",
        },
        {
            "id": "G-7",
            "severity": "medium",
            "issue": "评测是单轮、固定 prompt 模板、无缓存/重试；生产多轮与缓存会改变分布",
            "impact": "1,000 次查询外推是量级估计，不是预算承诺",
            "fix": "首批真实数据到位后重估，并区分 cache_hit / multi_turn",
        },
        {
            "id": "G-8",
            "severity": "low",
            "issue": "拒答口径存在词表（0.3929/0.25/0.1786）与语义（1.0/0.9286/1.0）两套读数",
            "impact": "若误用词表口径会高估拒答失效；本报告成本结论用语义口径，成本倍数不受影响",
            "fix": "文档统一引用 G2' 语义口径，词表口径仅作历史记录",
        },
        {
            "id": "G-9",
            "severity": "low",
            "issue": "臂2 的 +167% 混入了「免费拒答路径消失」的政策变化",
            "impact": "其中约 19pp 不是上下文扩容的边际价格（见 §8）",
            "fix": "对外表述成本时同时给「纯上下文扩容」近似值",
        },
    ]

    document = {
        "schema_version": "mneme-cost-baseline-v1",
        "task": "T6 / P2-1：臂2 成本基线与观察方案（离线分析）",
        "date": "2026-10-31",
        "repo_commit": "1066d60",
        "mode": "offline-only；只读已密封评测产物；未采集真实 trace；无外部 LLM/网络调用",
        "token_unit": "tokens = prompt_tokens + completion_tokens",
        "percentile_method": "nearest-rank: p_k = sorted[ceil(k/100*n)-1]",
        "inputs": {
            "generation": [
                {"key": spec["key"], "dir": f"results/answer-level/{spec['dir']}", "files": ["report.json", "manifest.json", "outcomes.jsonl"]}
                for spec in GENERATION_INPUTS
            ],
            "judge": [
                {"key": spec["key"], "dir": f"results/answer-level/{spec['dir']}", "files": [spec["file"], "manifest.json"], "protocol": load_json(ANSWER_LEVEL / spec["dir"] / "manifest.json").get("judge_protocol_version")}
                for spec in JUDGE_INPUTS
            ],
            "sealed_reference": SEALED_REFERENCE,
        },
        "baselines": baselines,
        "comparison": multi,
        "per_case_delta": delta_block,
        "g1_cost": g1,
        "judge": judge_block,
        "extrapolation": extrapolation,
        "observation_plan_thresholds": thresholds,
        "consistency": consistency,
        "gaps": gaps,
    }
    # per_case 明细体积较大，但保留可复核性；cost.json 约 100KB。
    return document


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    document = build()
    if "--check" in argv:
        if not OUT_PATH.exists():
            print("cost.json 不存在，先运行不带 --check 的生成模式", file=sys.stderr)
            return 2
        existing = load_json(OUT_PATH)
        if existing == document:
            print("OK: cost.json 与重算结果一致")
            return 0
        print("MISMATCH: cost.json 与重算结果不一致", file=sys.stderr)
        return 1

    OUT_PATH.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {OUT_PATH.relative_to(ROOT)}")

    for key in ("m2", "arm1", "arm2"):
        b = document["baselines"][key]
        d = b["distributions"]["total_tokens"]
        print(
            f"{key:5s} sum={b['total_tokens_sum']:>9,} "
            f"prompt={b['prompt_tokens_sum']:>9,} completion={b['completion_tokens_sum']:>7,} "
            f"mean/all={b['per_case_all']['mean_total']:>8.2f} "
            f"p50={d['all']['p50']:>5} p90={d['all']['p90']:>5} p95={d['all']['p95']:>5} max={d['all']['max']:>5} "
            f"ans_mean={d['answerable']['mean']:>8.2f} probe_mean={d['refusal_probe']['mean']:>8.2f}"
        )
    print(
        "arm2/m2 total=%.3fx  per-case=%.3fx  prompt=%.3fx  completion=%.3fx"
        % (
            document["comparison"]["arm2_over_m2"]["ratio"],
            document["comparison"]["arm2_over_m2"]["per_case_ratio"],
            document["comparison"]["arm2_over_m2"]["prompt_ratio"],
            document["comparison"]["arm2_over_m2"]["completion_ratio"],
        )
    )
    g = document["g1_cost"]["marginal_cost"]
    print(
        "G1 +%.4f  delta_tokens=%d  tokens per +0.01 G1=%.2f (total) / %.2f (per query)  per corrected point=%.2f"
        % (
            g["delta_g1_corrected"],
            g["delta_tokens_total"],
            g["tokens_per_0.01_g1_total"],
            g["tokens_per_0.01_g1_per_case"],
            g["tokens_per_additional_corrected_point"],
        )
    )
    print(
        "judge v1.1 total=%d (%.1f%% of M2+arm2 generation)"
        % (
            document["judge"]["total_tokens_v11"],
            100 * document["judge"]["total_tokens_v11"] / (document["baselines"]["m2"]["total_tokens_sum"] + document["baselines"]["arm2"]["total_tokens_sum"]),
        )
    )
    print("thresholds:", json.dumps(document["observation_plan_thresholds"]["p95_tokens_per_query"], ensure_ascii=False))
    print("extrapolation per 1000:", json.dumps(document["extrapolation"]["per_1000_queries"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
