"""M3 judge 跑批 runner：消费 M2 密封产物 → 逐要点 judge → 密封产物。

与 M2 的关系（红线）
--------------------
只消费：M2 outcomes.jsonl（answer/answer_hit/query_type/should_refuse）。
不重跑 M2、不改 M2 产物、不读 context（judge 只判答案覆盖）。

密封范式（沿用 parentchild run-3 / answer-level M2 的 _dump 口径）
------------------------------------------------------------------
outcomes-judge.jsonl + report.json + manifest.json；manifest 自哈希
覆盖其 body（去除 manifest_sha256 字段本身）；输出目录已存在即
fail-closed 拒绝；manifest 快照含 M2 outcomes 与 v2.1.jsonl 的 SHA。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable

from evaluation.answer_judge import (
    JUDGE_MAX_ATTEMPTS,
    JUDGE_MAX_TOKENS,
    JUDGE_VERDICTS,
    JudgePointResult,
    aggregate_judge_results,
    build_judge_messages,
    judge_point_with_llm,
)

JUDGE_PROTOCOL_VERSION = "al2-judge-v1"
JUDGE_LINEAGE = "answer-level-judge"

# M3 预算（owner 批示）：prompt 25–30 万 + completion ~2 万（单次 ~1.5–2k prompt）
BUDGET_PROMPT_RANGE = (250_000, 300_000)
BUDGET_COMPLETION = 20_000


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git_commit() -> str:
    """当前 HEAD 短哈希（lineage 溯源）；非 git 环境返回 unknown。"""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            check=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return "unknown"


# ── M2 消费 ───────────────────────────────────────────────────────

def load_m2_rows(m2_dir: Path) -> list[dict[str, Any]]:
    """读 M2 outcomes.jsonl（150 行密封产物）。"""
    path = Path(m2_dir) / "outcomes.jsonl"
    if not path.exists():
        raise RuntimeError(f"M2 outcomes 不存在: {path}")
    return [json.loads(l) for l in
            path.read_text(encoding="utf-8").splitlines() if l.strip()]


def extract_judge_inputs(m2_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从 M2 行抽 judge 输入面：每条机械 miss 要点一项。

    judge 只读 answer + point（不读 context——证据覆盖由 faithfulness 承担）。
    """
    inputs: list[dict[str, Any]] = []
    for r in m2_rows:
        hit = r.get("answer_hit")
        if not hit:
            continue
        for p in hit.get("point_results") or []:
            if p["verdict"] != "miss":
                continue
            inputs.append({
                "case_id": r["case_id"],
                "query_type": r["query_type"],
                "language": r.get("language"),
                "should_refuse": bool(r.get("should_refuse")),
                "point_text": p["point_text"],
                "answer": r["answer"],
            })
    return inputs


# ── 跑批 ──────────────────────────────────────────────────────────

def run_judge(
    judge_inputs: list[dict[str, Any]],
    *,
    call_fn: Callable[[list[dict[str, str]], int], str | None] | None = None,
    progress: bool = True,
) -> list[JudgePointResult]:
    """顺序跑批：逐要点 judge（协议层重试 ≤3 次），进度打印。

    call_fn 供测试/冒烟注入；None 时走真实网关（call_type="judge"）。
    """
    results: list[JudgePointResult] = []
    total = len(judge_inputs)
    for i, inp in enumerate(judge_inputs, start=1):
        if progress:
            print(f"  [{i}/{total}] {inp['case_id']} :: {inp['point_text'][:40]}")
        r = judge_point_with_llm(
            inp["answer"], inp["point_text"], call_fn=call_fn)
        results.append(replace(
            r,
            case_id=inp["case_id"],
            query_type=inp["query_type"],
            should_refuse=bool(inp["should_refuse"]),
        ))
    return results


def token_summary_for_judge(records: list) -> dict[str, Any]:
    """按 call_type='judge' 过滤网关记录，聚合 token 实耗。"""
    judge_records = [r for r in records if getattr(r, "call_type", "") == "judge"]
    prompt = sum((r.token_usage.prompt_tokens or 0) for r in judge_records
                 if r.token_usage)
    completion = sum((r.token_usage.completion_tokens or 0) for r in judge_records
                     if r.token_usage)
    models = sorted({r.model for r in judge_records})
    return {
        "calls": len(judge_records),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "models": models,
    }


# ── 密封 ──────────────────────────────────────────────────────────

def write_judge_sealed(
    out_dir: Path,
    *,
    judge_results: list[JudgePointResult],
    aggregate: dict[str, Any],
    token_summary: dict[str, Any],
    m2_dir: Path,
    m2_outcomes_sha256: str,
    dataset_name: str,
    dataset_path: Path,
    dataset_sha256: str,
    judge_model: str | None,
) -> None:
    """写密封产物：outcomes-judge.jsonl + report.json + 自哈希 manifest.json。

    目录已存在 → fail-closed 拒绝（沿 M2 write_sealed_outputs 范式）。
    """
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise RuntimeError(f"输出目录已存在，拒绝覆盖（fail-closed）: {out_dir}")
    out_dir.mkdir(parents=True)

    outcomes_bytes = ("\n".join(
        json.dumps(asdict(r), ensure_ascii=False, sort_keys=True)
        for r in judge_results) + ("\n" if judge_results else "")).encode("utf-8")
    (out_dir / "outcomes-judge.jsonl").write_bytes(outcomes_bytes)

    report = {
        "judged_count": len(judge_results),
        **{k: v for k, v in aggregate.items() if k != "no_answer_required"},
        "no_answer_required": aggregate.get("no_answer_required", []),
        "judge_tokens": token_summary,
    }
    report_bytes = _dump(report).encode("utf-8")
    (out_dir / "report.json").write_bytes(report_bytes)

    manifest_body = {
        "lineage": JUDGE_LINEAGE,
        "judge_protocol_version": JUDGE_PROTOCOL_VERSION,
        "judge_model": judge_model,
        "judge_max_tokens": JUDGE_MAX_TOKENS,
        "judge_max_attempts": JUDGE_MAX_ATTEMPTS,
        "judge_verdicts": list(JUDGE_VERDICTS),
        "m2_dir": str(m2_dir),
        "m2_outcomes_sha256": m2_outcomes_sha256,
        "dataset_name": dataset_name,
        "dataset_path": str(dataset_path),
        "dataset_sha256": dataset_sha256,
        "git_commit": _git_commit(),
        "aggregates": report,
        "outcomes_sha256": hashlib.sha256(outcomes_bytes).hexdigest(),
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
    }
    manifest_body["manifest_sha256"] = hashlib.sha256(
        _dump(manifest_body).encode("utf-8")).hexdigest()
    (out_dir / "manifest.json").write_text(_dump(manifest_body), encoding="utf-8")


# ── CLI ───────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="M3 judge 跑批（消费 M2 密封产物，真实 LLM 调用——手工执行）")
    parser.add_argument("--m2-dir", required=True,
                        help="M2 基线密封目录（含 outcomes.jsonl + manifest.json）")
    parser.add_argument("--out-dir", default=None,
                        help="输出目录（默认 results/answer-level/m3-judge-<date>）")
    parser.add_argument("--limit", type=int, default=None,
                        help="仅跑前 N 个 miss 要点（冒烟/试跑）")
    parser.add_argument("--dry-run", type=int, default=0,
                        help="干跑：打印前 N 个要点构建的 prompt（不调 LLM）")
    args = parser.parse_args(argv)

    m2_dir = Path(args.m2_dir)
    m2_manifest = json.loads(
        (m2_dir / "manifest.json").read_text(encoding="utf-8"))
    m2_outcomes_sha = _sha256_file(m2_dir / "outcomes.jsonl")

    inputs = extract_judge_inputs(load_m2_rows(m2_dir))
    print(f"[M3] M2 miss 要点共 {len(inputs)} 条（覆盖 "
          f"{len({i['case_id'] for i in inputs})} 例）")

    if args.dry_run:
        for i, inp in enumerate(inputs[:args.dry_run], start=1):
            print(f"\n===== 要点 {i}/{args.dry_run} "
                  f"({inp['case_id']} :: {inp['point_text'][:40]}) =====")
            for m in build_judge_messages(inp["answer"], inp["point_text"]):
                print(f"--- {m['role']} ---\n{m['content']}")
        return 0

    if args.limit:
        inputs = inputs[:args.limit]
        print(f"[M3] 截取前 {args.limit} 条试跑")

    out_dir = Path(args.out_dir) if args.out_dir else (
        Path("results/answer-level") / f"m3-judge-{time.strftime('%Y-%m-%d')}")
    if out_dir.exists():
        print(f"[M3] fail-closed：输出目录已存在，拒绝覆盖 {out_dir}")
        return 2

    from src.llm_gateway import clear_call_records, get_call_records

    clear_call_records()
    start = time.perf_counter()
    results = run_judge(inputs)
    elapsed = time.perf_counter() - start
    token_summary = token_summary_for_judge(get_call_records())

    judge_rows = [asdict(r) for r in results]
    aggregate = aggregate_judge_results(load_m2_rows(m2_dir), judge_rows)

    settings_model = None
    try:
        from src.config import get_settings
        settings_model = get_settings().llm_model
    except Exception:
        pass
    judge_model = (token_summary["models"][0]
                   if token_summary["models"] else settings_model)

    write_judge_sealed(
        out_dir,
        judge_results=results,
        aggregate=aggregate,
        token_summary=token_summary,
        m2_dir=m2_dir,
        m2_outcomes_sha256=m2_outcomes_sha,
        dataset_name=m2_manifest.get("dataset_name", "v2.1"),
        dataset_path=Path(m2_manifest.get("dataset_path", "evaluation/datasets/v2.1.jsonl")),
        dataset_sha256=_sha256_file(
            Path(m2_manifest.get("dataset_path", "evaluation/datasets/v2.1.jsonl"))),
        judge_model=judge_model,
    )

    budget_prompt_lo, budget_prompt_hi = BUDGET_PROMPT_RANGE
    print(f"\n[M3] 完成 {len(results)} 条，耗时 {elapsed:.0f}s")
    print(f"[M3] judge token: prompt={token_summary['prompt_tokens']:,} "
          f"(预算 {budget_prompt_lo:,}-{budget_prompt_hi:,}), "
          f"completion={token_summary['completion_tokens']:,} "
          f"(预算 {BUDGET_COMPLETION:,})")
    agg = aggregate
    print(f"[M3] 三态: hit={agg['count_hit']} partial={agg['count_partial']} "
          f"miss={agg['count_miss']} contract_error={agg['count_contract_error']}")
    print(f"[M3] 修正0.5={agg['corrected_rate_partial_05']:.4f} "
          f"保守={agg['corrected_rate_partial_0']:.4f} "
          f"分歧率={agg['divergence_rate']:.4f} 契约错误率={agg['contract_error_rate']:.4f}")
    print(f"[M3] 密封产物: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
