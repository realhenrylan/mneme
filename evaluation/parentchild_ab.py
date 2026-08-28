"""2.2 parent-child / 邻接扩展效果验收执行器（A/B 双臂）。

设计依据（预注册，阈值冻结后实现，不得回调）：
``plans/STAGE2-PART2-DESIGN-2026-08-28.md`` Part 1

核心设计——**单因子由构造保证**：每 case 只构建一次 ``QueryPlan``
（compare.prepare_query_plan：rewrite + decompose + 检索），ON/OFF 两臂
都以 ``prepare_answer_evidence(query_plan=plan)`` 复用同一计划对象，
唯一差异是 select 之后的扩展阶段（由 ``RAG_CONTEXT_EXPANSION`` 模块
开关门控，按臂临时覆盖、finally 恢复——与拒答策略消融同模式）。

指标：chunk 级 context recall（真值来自 ``compare.build_ground_truth_map``
的 snippet→chunk 匹配）。零 LLM 生成调用（只跑规划，不跑回答）。

门禁（n=预期 71，剔除 multi_turn/should_refuse/无匹配真值）：
``STAGE2_22_ACCEPTED`` / ``STAGE2_22_NOT_PROVEN`` / ``STAGE2_22_REGRESSION``。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from evaluation.schema import EvalCase, QueryType, load_dataset

# ── 预注册常量（设计 Part 1 冻结；修改即违反预注册纪律） ────────────────
ARMS = ("ON", "OFF")
GATE_MIN_MEAN_DELTA = 0.05        # mean(ON) - mean(OFF) 的通过下限
GATE_MAX_CASE_REGRESSION = 0.05   # 单例恶化容限（幅度）

GATE_ACCEPT = "STAGE2_22_ACCEPTED"
GATE_NOT_PROVEN = "STAGE2_22_NOT_PROVEN"
GATE_REGRESSION = "STAGE2_22_REGRESSION"

GATE_ARM_BASE = "OFF"
GATE_ARM_TREATMENT = "ON"

PREREG_DOC = "plans/STAGE2-PART2-DESIGN-2026-08-28.md"


class GateError(RuntimeError):
    """任何非法状态：调用方应保证零输出 fail-closed。"""


@dataclass
class CaseOutcome:
    """单臂单 case 的产物（context 侧指标输入；零生成调用）。"""

    case_id: str
    arm: str
    context_chunk_ids: tuple[str, ...]
    truth_chunk_ids: tuple[str, ...]
    context_k: int
    refused: bool
    plan_fingerprint: str


# ── 真值与目标集 ─────────────────────────────────────────────────

def truth_by_case(entries: list[Any]) -> dict[str, set[str]]:
    """GroundTruthEntry 列表 → case_id → 匹配真值 chunk id 集。"""
    out: dict[str, set[str]] = {}
    for e in entries:
        out.setdefault(e.case_id, set()).update(e.matched_chunk_ids)
    return out


def select_target_cases(
    cases: list[EvalCase], truth: dict[str, set[str]],
) -> list[EvalCase]:
    """预注册目标集：非 multi_turn、非 should_refuse、且真值非空。

    multi_turn 由 2.4 实验单独度量（其 canonical history 需要答案回放，
    与本实验正交）；无匹配真值的 case 无法计算 chunk recall，剔除并
    由调用方上报数量。
    """
    return [
        c for c in cases
        if c.query_type != QueryType.MULTI_TURN
        and not c.should_refuse
        and truth.get(c.id)
    ]


# ── 双臂执行 ─────────────────────────────────────────────────────

def make_prepare_arms(index_bundle: dict, llm_temperature: float | None = None):
    """默认生产接线：按臂覆盖 ``RAG_CONTEXT_EXPANSION`` 后调生产 prepare。

    覆盖为模块属性临时替换（评测消融的既有模式），finally 恢复；
    两臂共用同一 ``query_plan`` 对象——规划与检索零重复、零漂移。
    """
    from src import rag
    from src.rag import prepare_answer_evidence

    def _run(arm: str, query: str, plan: Any):
        if arm not in ARMS:
            raise GateError(f"未知 arm: {arm!r}（可选 {ARMS}）")
        previous = rag.RAG_CONTEXT_EXPANSION
        rag.RAG_CONTEXT_EXPANSION = (
            rag.CONTEXT_EXPANSION_ON if arm == "ON"
            else rag.CONTEXT_EXPANSION_OFF)
        try:
            return prepare_answer_evidence(
                query, index_bundle["model"], index_bundle["collection"],
                index_bundle["bm25"], index_bundle["documents"],
                index_bundle["metadatas"],
                query_plan=plan, llm_temperature=llm_temperature)
        finally:
            rag.RAG_CONTEXT_EXPANSION = previous

    return _run


def run_case_pair(
    case: EvalCase,
    plan: Any,
    prepare_arms: Callable,
    truth: set[str] = frozenset(),
) -> tuple[CaseOutcome, CaseOutcome]:
    """同一计划跑 ON/OFF 两臂，返回 (ON, OFF) 两个 CaseOutcome。"""
    outcomes: list[CaseOutcome] = []
    for arm in ARMS:
        evidence = prepare_arms(arm, case.query, plan)
        outcomes.append(CaseOutcome(
            case_id=case.id, arm=arm,
            context_chunk_ids=tuple(evidence.context_chunk_ids),
            truth_chunk_ids=tuple(truth),
            context_k=int(evidence.context_k),
            refused=bool(evidence.refused),
            plan_fingerprint=getattr(evidence, "plan_fingerprint", ""),
        ))
    return outcomes[0], outcomes[1]


# ── 指标与门禁 ───────────────────────────────────────────────────

def chunk_context_recall(outcome: Any) -> float:
    """主指标：最终 context 对真值 chunk 的覆盖率；拒答无 context 计 0。"""
    if getattr(outcome, "refused", False):
        return 0.0
    truth = set(outcome.truth_chunk_ids)
    if not truth:
        raise GateError(
            f"case {outcome.case_id!r} 真值为空（目标集过滤应已剔除）")
    covered = set(outcome.context_chunk_ids) & truth
    return len(covered) / len(truth)


def evaluate_gate(recalls: dict[str, dict[str, float]], case_ids: list[str]) -> dict:
    """预注册三态门禁（OFF vs ON）。缺结果即抛错（fail-closed）。"""
    for arm in (GATE_ARM_BASE, GATE_ARM_TREATMENT):
        missing = [c for c in case_ids if c not in recalls.get(arm, {})]
        if missing:
            raise GateError(f"{arm} 臂缺少 case 结果: {missing}")
    if not case_ids:
        raise GateError("case 集为空，无法判定门禁")

    n = len(case_ids)
    mean_off = sum(recalls[GATE_ARM_BASE][c] for c in case_ids) / n
    mean_on = sum(recalls[GATE_ARM_TREATMENT][c] for c in case_ids) / n
    per_case_delta = {
        c: recalls[GATE_ARM_TREATMENT][c] - recalls[GATE_ARM_BASE][c]
        for c in case_ids}
    worst = min(per_case_delta.values())

    # 预注册判定顺序：通过条件（均值达阈且无单例超限恶化）→ 均值方向二分。
    if (mean_on - mean_off >= GATE_MIN_MEAN_DELTA
            and worst >= -GATE_MAX_CASE_REGRESSION):
        verdict = GATE_ACCEPT
    elif mean_on >= mean_off:
        verdict = GATE_NOT_PROVEN
    else:
        verdict = GATE_REGRESSION

    return {
        "verdict": verdict,
        "mean_off": mean_off,
        "mean_on": mean_on,
        "mean_delta": mean_on - mean_off,
        "worst_case_delta": worst,
        "per_case_delta": per_case_delta,
        "thresholds": {
            "min_mean_delta": GATE_MIN_MEAN_DELTA,
            "max_case_regression": GATE_MAX_CASE_REGRESSION,
            "n_cases": n,
        },
    }


# ── 密封产物 ─────────────────────────────────────────────────────

def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_outputs(
    out_dir: Path,
    *,
    outcomes: list[CaseOutcome],
    recalls: dict[str, dict[str, float]],
    gate: dict,
    dataset_sha: str,
    corpus_files: list[str],
    prereg_doc: str,
) -> None:
    """写密封产物：outcomes.jsonl + 自哈希 manifest。目录拒绝已存在。"""
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise GateError(f"输出目录已存在，拒绝覆盖（fail-closed）: {out_dir}")
    out_dir.mkdir(parents=True)

    rows = []
    for o in outcomes:
        row = asdict(o)
        row["context_chunk_ids"] = list(o.context_chunk_ids)
        row["truth_chunk_ids"] = list(o.truth_chunk_ids)
        row["chunk_context_recall"] = recalls.get(o.arm, {}).get(o.case_id)
        rows.append(row)
    outcomes_bytes = ("\n".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows)
        + ("\n" if rows else "")).encode("utf-8")
    (out_dir / "outcomes.jsonl").write_bytes(outcomes_bytes)

    manifest_body = {
        "lineage": "stage2-parentchild-acceptance",
        "preregistration_doc": prereg_doc,
        "dataset_sha256": dataset_sha,
        "corpus_files": corpus_files,
        "arms": list(ARMS),
        "gate_thresholds": {
            "min_mean_delta": GATE_MIN_MEAN_DELTA,
            "max_case_regression": GATE_MAX_CASE_REGRESSION,
        },
        "row_count": len(rows),
        "outcomes_sha256": _sha256_bytes(outcomes_bytes),
        "gate": gate,
    }
    manifest_body["manifest_sha256"] = _sha256_bytes(
        _dump(manifest_body).encode("utf-8"))
    (out_dir / "manifest.json").write_text(_dump(manifest_body), encoding="utf-8")


# ── CLI（真实运行入口） ──────────────────────────────────────────

def _resolve_corpus(corpus_dir: Path, cases: list[EvalCase]) -> list[Path]:
    names = sorted({s for c in cases for s in c.relevant_source_ids})
    paths = []
    for name in names:
        path = corpus_dir / name
        if not path.exists():
            raise GateError(f"语料缺失: {name}（corpus_dir={corpus_dir}）")
        paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="2.2 parent-child 效果验收 A/B（真实运行）")
    parser.add_argument("--dataset", default="evaluation/datasets/v1.jsonl")
    parser.add_argument("--corpus-dir", default="test_texts")
    parser.add_argument("--collection", default="eval_stage2_parentchild")
    parser.add_argument("--output", required=True,
                        help="密封输出目录（必须不存在）")
    parser.add_argument("--force-rebuild-index", action="store_true")
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset)
    cases = load_dataset(dataset_path)
    # 目标集候选（真值映射前先按预注册规则粗筛，真值只对这些 case 构建）
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
        raise GateError("目标集为空，无法判定门禁")

    from evaluation.compare import prepare_query_plan
    prepare_arms = make_prepare_arms(index_bundle)
    outcomes: list[CaseOutcome] = []
    recalls: dict[str, dict[str, float]] = {arm: {} for arm in ARMS}
    for i, case in enumerate(targets, 1):
        # 每 case 一次规划（LLM rewrite+decompose+检索各一次），双臂共享
        plan = prepare_query_plan(
            case, model, collection, bm25, documents, metadatas, history=None)
        on, off = run_case_pair(
            case, plan, prepare_arms, truth=truth[case.id])
        outcomes.extend([on, off])
        recalls["ON"][case.id] = chunk_context_recall(on)
        recalls["OFF"][case.id] = chunk_context_recall(off)
        if i % 10 == 0 or i == len(targets):
            print(f"[progress] {i}/{len(targets)} cases done")

    gate = evaluate_gate(recalls, [c.id for c in targets])
    write_outputs(
        Path(args.output), outcomes=outcomes, recalls=recalls, gate=gate,
        dataset_sha=_sha256_bytes(dataset_path.read_bytes()),
        corpus_files=[p.name for p in corpus_paths],
        prereg_doc=PREREG_DOC)

    print(json.dumps(
        {k: gate[k] for k in ("verdict", "mean_off", "mean_on",
                              "mean_delta", "worst_case_delta")},
        ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
