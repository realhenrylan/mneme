"""M5b al3 重测量 runner：对既有密封产物的探针答案做语义拒答判定。

设计（M5b 批准稿 §二阶段 0）
----------------------------
- **零新生成**：只读既有密封产物（M2/臂1/臂2 的 outcomes.jsonl）的 28 条
  探针答案 + 查询，逐条跑 al3 语义判定；
- 词表口径对照：同探针的 `citation_metrics.correctly_refused`（既有词表口径）
  并列入行，量化两个口径的分歧；
- 密封产物：outcomes-refusal-judge.jsonl + report.json + 自哈希 manifest.json
  （沿 al2 `write_judge_sealed` 范式，目录已存在 fail-closed）。

用法::

    python -m evaluation.refusal_judge_runner \
        --source-dir results/answer-level/m4c-arm2-2026-09-06 \
        --out-dir results/answer-level/m5b-arm2-refusal-judge-2026-09-06

    python -m evaluation.refusal_judge_runner --source-dir ... --dry-run 2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable

from evaluation.refusal_judge import (
    JUDGE_MAX_ATTEMPTS,
    JUDGE_MAX_TOKENS,
    REFUSAL_JUDGE_PROTOCOL_VERSION,
    REFUSAL_VERDICTS,
    RefusalJudgeResult,
    aggregate_refusal_results,
    build_refusal_messages,
    judge_refusal_with_llm,
)

REFUSAL_JUDGE_LINEAGE = "answer-level-refusal-judge"


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            check=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return "unknown"


def load_probe_rows(source_dir: Path) -> list[dict[str, Any]]:
    """从密封产物读探针行（should_refuse=True），附词表口径对照值。"""
    path = Path(source_dir) / "outcomes.jsonl"
    if not path.exists():
        raise RuntimeError(f"密封产物不存在: {path}")
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            if not o.get("should_refuse"):
                continue
            rows.append({
                "case_id": o["case_id"],
                "query": o.get("query", ""),
                "answer": o.get("answer", ""),
                "lexical_verdict": (o.get("citation_metrics") or {}).get(
                    "correctly_refused"),
            })
    return rows


def run_refusal_judge(
    probe_rows: list[dict[str, Any]],
    *,
    call_fn: Callable[[list[dict[str, str]], int], str | None] | None = None,
    progress: bool = True,
) -> list[RefusalJudgeResult]:
    """顺序跑批：逐探针 al3 判定（协议层重试 ≤3），进度打印。"""
    results: list[RefusalJudgeResult] = []
    total = len(probe_rows)
    for i, row in enumerate(probe_rows, start=1):
        if progress:
            print(f"  [{i}/{total}] {row['case_id']}")
        verdict, evidence, attempts, ce = judge_refusal_with_llm(
            row["query"], row["answer"], call_fn=call_fn)
        results.append(RefusalJudgeResult(
            case_id=row["case_id"],
            query=row["query"],
            semantic_verdict=verdict,
            evidence=evidence,
            attempts=attempts,
            contract_error=ce,
            should_refuse=True,
            lexical_verdict=row.get("lexical_verdict"),
        ))
    return results


def token_summary_for_refusal_judge(records: list) -> dict[str, Any]:
    """按 call_type='refusal_judge' 过滤网关记录，聚合 token 实耗。"""
    judge_records = [
        r for r in records
        if getattr(r, "call_type", "") == "refusal_judge"]
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


def write_sealed(
    out_dir: Path,
    *,
    results: list[RefusalJudgeResult],
    aggregate: dict[str, Any],
    token_summary: dict[str, Any],
    source_dir: Path,
    source_sha256: str,
    judge_model: str | None,
) -> None:
    """写密封产物：outcomes-refusal-judge.jsonl + report.json + 自哈希 manifest。"""
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise RuntimeError(f"输出目录已存在，拒绝覆盖（fail-closed）: {out_dir}")
    out_dir.mkdir(parents=True)

    outcomes_bytes = ("\n".join(
        json.dumps(asdict(r), ensure_ascii=False, sort_keys=True)
        for r in results) + ("\n" if results else "")).encode("utf-8")
    (out_dir / "outcomes-refusal-judge.jsonl").write_bytes(outcomes_bytes)

    report = {"judged_count": len(results), **aggregate,
              "refusal_judge_tokens": token_summary}
    report_bytes = _dump(report).encode("utf-8")
    (out_dir / "report.json").write_bytes(report_bytes)

    manifest_body = {
        "lineage": REFUSAL_JUDGE_LINEAGE,
        "judge_protocol_version": REFUSAL_JUDGE_PROTOCOL_VERSION,
        "judge_model": judge_model,
        "judge_max_tokens": JUDGE_MAX_TOKENS,
        "judge_max_attempts": JUDGE_MAX_ATTEMPTS,
        "judge_verdicts": list(REFUSAL_VERDICTS),
        "source_dir": str(source_dir),
        "source_outcomes_sha256": source_sha256,
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
        description="al3 拒答语义重测量（读既有密封产物，真实 LLM 调用）")
    parser.add_argument("--source-dir", required=True,
                        help="源密封目录（含 outcomes.jsonl）")
    parser.add_argument("--out-dir", default=None,
                        help="输出目录（默认 results/answer-level/m5b-<date>）")
    parser.add_argument("--limit", type=int, default=None, help="仅跑前 N 条")
    parser.add_argument("--dry-run", type=int, default=0,
                        help="干跑：打印前 N 条 prompt（不调 LLM）")
    args = parser.parse_args(argv)

    source_dir = Path(args.source_dir)
    probe_rows = load_probe_rows(source_dir)
    print(f"[al3] 探针 {len(probe_rows)} 条（源 {source_dir}）")
    if not probe_rows:
        print("[al3] 无探针行，退出")
        return 2

    if args.dry_run:
        for i, row in enumerate(probe_rows[:args.dry_run], start=1):
            print(f"\n===== 探针 {i}/{args.dry_run} ({row['case_id']}) =====")
            for m in build_refusal_messages(row["query"], row["answer"]):
                print(f"--- {m['role']} ---\n{m['content']}")
        return 0

    if args.limit:
        probe_rows = probe_rows[:args.limit]
        print(f"[al3] 截取前 {args.limit} 条")

    out_dir = Path(args.out_dir) if args.out_dir else (
        Path("results/answer-level") / f"m5b-refusal-judge-{time.strftime('%Y-%m-%d')}")
    if out_dir.exists():
        print(f"[al3] fail-closed：输出目录已存在，拒绝覆盖 {out_dir}")
        return 2

    from src.llm_gateway import clear_call_records, get_call_records

    clear_call_records()
    start = time.perf_counter()
    results = run_refusal_judge(probe_rows)
    elapsed = time.perf_counter() - start
    token_summary = token_summary_for_refusal_judge(get_call_records())

    aggregate = aggregate_refusal_results([asdict(r) for r in results])

    settings_model = None
    try:
        from src.config import get_settings
        settings_model = get_settings().llm_model
    except Exception:
        pass
    judge_model = (token_summary["models"][0]
                   if token_summary["models"] else settings_model)

    write_sealed(
        out_dir,
        results=results,
        aggregate=aggregate,
        token_summary=token_summary,
        source_dir=source_dir,
        source_sha256=_sha256_file(source_dir / "outcomes.jsonl"),
        judge_model=judge_model,
    )
    print(f"\n[al3] 完成 {len(results)} 条，耗时 {elapsed:.0f}s")
    print(f"[al3] token: prompt={token_summary['prompt_tokens']:,} "
          f"completion={token_summary['completion_tokens']:,}")
    print(f"[al3] 语义拒答正确率={aggregate['semantic_refusal_accuracy']} "
          f"（词表口径={aggregate['lexical_refusal_accuracy']}）"
          f" 契约错误率={aggregate['contract_error_rate']} "
          f"分歧={aggregate['disagreement_count']}")
    print(f"[al3] 密封产物: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
