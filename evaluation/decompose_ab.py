"""D5 拆解收益计量执行器（计划步骤 4 —— 诊断性 A/B，无 accept/reject 门禁）。

设计依据（预注册）：``plans/22-SMALL-ITEMS-31-CLOSEOUT-DESIGN-2026-08-29.md``
Part 2-D5：``RAG_QUERY_DECOMPOSE`` 开关按臂临时覆盖（模块属性 + finally
恢复，reuse 2.2 消融模式）。

单因子 = decompose 开关（构造保证）：
- OFF 臂：真实 rewrite + 零 decompose（单查询直通）；
- ON 臂：**冻结** OFF 臂的 rewrite 结果（``rewrite_query_llm`` 模块属性
  临时替换为恒等返回），真实 decompose 照常执行——两臂共享同一 rewrite，
  唯一差异是 decompose；
- ``RAG_CONTEXT_EXPANSION`` 两臂固定 on（生产默认），消除扩展阶段差异。

指标（诊断性：报告 deltas 与 n，不设 accept/reject 门禁）：
- containment-aware context recall（run-3 仪器，
  ``parentchild_ab.chunk_context_recall``）；
- 规划墙钟延迟（每 case 每臂的 ``_plan_query_runtime`` 全程毫秒）。

数据卫生：不传 trace_store（观测 Off）；零 trace 写入；v1/冻结树零改写。
成本：OFF 臂 71 次 rewrite LLM + ON 臂 71 次 decompose LLM（零生成）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from evaluation.parentchild_ab import (
    chunk_context_recall, select_target_cases, truth_by_case,
)
from evaluation.schema import EvalCase, QueryType, load_dataset

ARMS = ("OFF", "ON")
PREREG_DOC = "plans/22-SMALL-ITEMS-31-CLOSEOUT-DESIGN-2026-08-29.md"


class AbError(RuntimeError):
    """任何非法状态：调用方应保证零输出 fail-closed。"""


def _plan_arm(
    index_bundle: dict,
    case: EvalCase,
    arm: str,
    frozen_rewrite: tuple[str, dict] | None,
) -> tuple[Any, float]:
    """按臂构建 runtime plan（wrap 为 compare.QueryPlan），返回 (plan, wall_s)。

    ARMD=OFF：真实 rewrite（LLM 调用）；ARMD=ON：冻结 rewrite（零 rewrite
    LLM 调用）+ 真实 decompose。模块属性 finally 恢复。
    """
    from unittest import mock

    import src.rag as rag
    from src.rag import DECOMPOSE_OFF, DECOMPOSE_ON, _plan_query_runtime

    previous_decompose = rag.RAG_QUERY_DECOMPOSE
    rag.RAG_QUERY_DECOMPOSE = DECOMPOSE_ON if arm == "ON" else DECOMPOSE_OFF
    patcher = None
    try:
        if frozen_rewrite is not None:
            import src.rag_query_rewriter as rw
            frozen_q, frozen_log = frozen_rewrite

            def _frozen(*args, **kwargs):
                return frozen_q, frozen_log

            patcher = mock.patch.object(rw, "rewrite_query_llm", _frozen)
            patcher.start()

        started = time.perf_counter()
        runtime_plan = _plan_query_runtime(
            case.query, index_bundle["model"], index_bundle["collection"],
            index_bundle["bm25"], index_bundle["documents"],
            index_bundle["metadatas"], history=None,
        )
        wall_ms = (time.perf_counter() - started) * 1000
    finally:
        if patcher is not None:
            patcher.stop()
        rag.RAG_QUERY_DECOMPOSE = previous_decompose

    from evaluation.compare import QueryPlan

    query_plan = QueryPlan(
        rewritten_query=runtime_plan.rewritten_query,
        rewrite_log=runtime_plan.rewrite_log,
        sub_queries=list(runtime_plan.sub_queries),
        base_candidates=dict(runtime_plan.best_score),
    )
    return query_plan, wall_ms


def _evidence_for_plan(index_bundle: dict, case: EvalCase, plan: Any) -> Any:
    """按臂用 prepare_answer_evidence 构建证据（扩展固定 on，单因子干净）。"""
    import src.rag as rag
    from src.rag import CONTEXT_EXPANSION_ON, prepare_answer_evidence

    previous_expansion = rag.RAG_CONTEXT_EXPANSION
    rag.RAG_CONTEXT_EXPANSION = CONTEXT_EXPANSION_ON
    try:
        return prepare_answer_evidence(
            case.query, index_bundle["model"], index_bundle["collection"],
            index_bundle["bm25"], index_bundle["documents"],
            index_bundle["metadatas"], query_plan=plan,
        )
    finally:
        rag.RAG_CONTEXT_EXPANSION = previous_expansion


def _resolve_corpus(corpus_dir: Path, cases: list[EvalCase]) -> list[Path]:
    names = sorted({s for c in cases for s in c.relevant_source_ids})
    paths = []
    for name in names:
        path = corpus_dir / name
        if not path.exists():
            raise AbError(f"语料缺失: {name}（corpus_dir={corpus_dir}）")
        paths.append(path)
    return paths


def _summarize(values: dict[str, float]) -> dict:
    if not values:
        return {"n": 0}
    vals = list(values.values())
    mean = sum(vals) / len(vals)
    return {
        "n": len(vals),
        "mean": mean,
        "min": min(vals),
        "max": max(vals),
        "median": sorted(vals)[len(vals) // 2],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="evaluation/datasets/v1.jsonl")
    parser.add_argument("--corpus-dir", default="test_texts")
    parser.add_argument("--collection", default="eval_stage3_decompose")
    parser.add_argument("--output", default="results/stage3-decompose",
                        help="结果/报告输出目录（诊断性，非密封）")
    parser.add_argument("--force-rebuild-index", action="store_true")
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset)
    cases = load_dataset(dataset_path)
    candidates = [c for c in cases
                  if c.query_type != QueryType.MULTI_TURN
                  and not c.should_refuse]
    corpus_paths = _resolve_corpus(Path(args.corpus_dir), candidates)
    print(f"[preflight] candidates={len(candidates)} corpus={len(corpus_paths)}")

    from src.rag import prepare_index
    model, collection, bm25, documents, metadatas = prepare_index(
        [str(p) for p in corpus_paths], args.collection,
        args.force_rebuild_index)
    index_bundle = {
        "model": model, "collection": collection, "bm25": bm25,
        "documents": documents, "metadatas": metadatas,
    }
    print(f"[index] chunks={len(documents)}")

    from evaluation.compare import build_ground_truth_map
    truth = truth_by_case(
        build_ground_truth_map(candidates, metadatas, documents))
    targets = select_target_cases(candidates, truth)
    excluded = len(candidates) - len(targets)
    print(f"[targets] n={len(targets)}（剔除无匹配真值 {excluded}）")
    if not targets:
        raise AbError("目标集为空，无法计量")

    text_by_chunk_id = {
        (meta or {}).get("chunk_id", f"chunk_{i}"): documents[i]
        for i, meta in enumerate(metadatas)
    }

    # 逐 case：OFF 臂先行（真实 rewrite 数据源），ON 臂冻结其 rewrite
    rows: list[dict] = []
    recall_by_arm: dict[str, dict[str, float]] = {a: {} for a in ARMS}
    wall_by_arm: dict[str, dict[str, float]] = {a: {} for a in ARMS}
    subquery_counts: dict[str, Counter] = {a: Counter() for a in ARMS}

    for i, case in enumerate(targets, 1):
        off_plan, off_wall = _plan_arm(index_bundle, case, "OFF", None)
        on_plan, on_wall = _plan_arm(
            index_bundle, case, "ON",
            (off_plan.rewritten_query, off_plan.rewrite_log))

        outcomes = {}
        for arm, plan, wall in (
                ("OFF", off_plan, off_wall), ("ON", on_plan, on_wall)):
            evidence = _evidence_for_plan(index_bundle, case, plan)
            outcome = type("Outcome", (), {
                "case_id": case.id,
                "context_chunk_ids": tuple(evidence.context_chunk_ids),
                "context_chunk_texts": tuple(
                    text_by_chunk_id.get(cid, "")
                    for cid in evidence.context_chunk_ids),
                "truth_chunk_ids": tuple(sorted(truth[case.id])),
                "truth_chunk_texts": tuple(
                    text_by_chunk_id.get(tid, "")
                    for tid in sorted(truth[case.id])),
                "refused": bool(evidence.refused),
            })()
            recall = chunk_context_recall(outcome)
            recall_by_arm[arm][case.id] = recall
            wall_by_arm[arm][case.id] = wall
            subquery_counts[arm][len(plan.sub_queries)] += 1
            outcomes[arm] = recall
        rows.append({
            "case_id": case.id,
            "recall_off": outcomes["OFF"],
            "recall_on": outcomes["ON"],
            "recall_delta": outcomes["ON"] - outcomes["OFF"],
            "wall_ms_off": round(off_wall, 1),
            "wall_ms_on": round(on_wall, 1),
            "wall_delta_ms": round(on_wall - off_wall, 1),
        })
        if i % 10 == 0 or i == len(targets):
            print(f"[progress] {i}/{len(targets)} cases done")

    # ── 诊断性汇总（无门禁：报告 deltas 与 n） ──
    deltas = {r["case_id"]: r["recall_delta"] for r in rows}
    wall_deltas = {r["case_id"]: r["wall_delta_ms"] for r in rows}
    summary = {
        "preregistration_doc": PREREG_DOC,
        "n_cases": len(rows),
        "arms": list(ARMS),
        "recall": {
            "off": _summarize(recall_by_arm["OFF"]),
            "on": _summarize(recall_by_arm["ON"]),
            "mean_delta": (
                sum(deltas.values()) / len(deltas) if deltas else 0.0),
            "worst_case_delta": min(deltas.values()) if deltas else None,
            "improved": sum(1 for d in deltas.values() if d > 0),
            "regressed": sum(1 for d in deltas.values() if d < 0),
            "unchanged": sum(1 for d in deltas.values() if d == 0),
        },
        "planning_wall_ms": {
            "off": _summarize(wall_by_arm["OFF"]),
            "on": _summarize(wall_by_arm["ON"]),
            "mean_delta": (
                sum(wall_deltas.values()) / len(wall_deltas)
                if wall_deltas else 0.0),
        },
        "subquery_count_distribution": {
            a: {str(k): v for k, v in sorted(c.items())}
            for a, c in subquery_counts.items()
        },
        "dataset_sha256": hashlib.sha256(
            dataset_path.read_bytes()).hexdigest(),
        "corpus_files": [p.name for p in corpus_paths],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps({"summary": summary, "rows": rows},
                   ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")

    # 报告
    r = summary["recall"]
    w = summary["planning_wall_ms"]
    lines = [
        "# Stage 3.1 · D5 拆解收益计量报告（诊断性，无门禁）",
        "",
        f"- 日期：{summary['generated_at'][:10]}",
        f"- 预注册：{summary['preregistration_doc']} Part 2-D5",
        f"- 目标集：v1 同 2.2（n={summary['n_cases']}，非多轮/非拒答/真值非空）",
        f"- 语料：{len(summary['corpus_files'])} 文件（索引 chunks 见上方日志）",
        f"- dataset_sha256：{summary['dataset_sha256'][:16]}…",
        "",
        "## containment-aware context recall（run-3 仪器）",
        "",
        f"| 指标 | OFF | ON | Δ |",
        f"| --- | --- | --- | --- |",
        f"| mean recall | {r['off']['mean']:.4f} | {r['on']['mean']:.4f} | "
        f"**{r['mean_delta']:+.4f}** |",
        f"| min / max | {r['off']['min']:.4f} / {r['off']['max']:.4f} | "
        f"{r['on']['min']:.4f} / {r['on']['max']:.4f} | — |",
        "",
        f"- worst_case_delta：{r['worst_case_delta']:+.4f}"
        f"（改善 {r['improved']} / 恶化 {r['regressed']} / 持平 {r['unchanged']}）",
        "- 注：诊断性计量，不设 accept/reject 门禁（预注册）。",
        "",
        "## 规划墙钟延迟（rewrite+decompose+检索 全程，毫秒）",
        "",
        f"| 指标 | OFF | ON | Δ |",
        f"| --- | --- | --- | --- |",
        f"| mean | {w['off']['mean']:.0f} | {w['on']['mean']:.0f} | "
        f"**{w['mean_delta']:+.0f}** |",
        f"| median | {w['off']['median']:.0f} | {w['on']['median']:.0f} | — |",
        "",
        f"- 子查询数分布 OFF：{summary['subquery_count_distribution']['OFF']}"
        f"；ON：{summary['subquery_count_distribution']['ON']}",
        "",
        "## 数据卫生",
        "",
        "- 沙箱运行零 trace 写入（未传 trace_store，观测 Off）；",
        "- v1/冻结树零改写；单因子 = decompose 开关（两臂共享同一 rewrite：",
        "  ON 臂冻结 OFF 臂的 rewrite 输出，仅 decompose 真实执行）。",
    ]
    (out_dir / "report-2026-08-29.md").write_text(
        "\n".join(lines), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
