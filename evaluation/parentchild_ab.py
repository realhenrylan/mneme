"""2.2 parent-child / 邻接扩展效果验收执行器（A/B 双臂）。

设计依据（预注册，阈值冻结后实现，不得回调）：
``plans/STAGE2-PART2-DESIGN-2026-08-28.md`` Part 1

核心设计——**单因子由构造保证**：每 case 只构建一次 ``QueryPlan``
（compare.prepare_query_plan：rewrite + decompose + 检索），ON/OFF 两臂
都以 ``prepare_answer_evidence(query_plan=plan)`` 复用同一计划对象，
唯一差异是 select 之后的扩展阶段（由 ``RAG_CONTEXT_EXPANSION`` 模块
开关门控，按臂临时覆盖、finally 恢复——与拒答策略消融同模式）。

指标（round-3 预注册修订，owner 2026-08-28 批准）：containment-aware 真值
覆盖——真值块按 id 命中，或其文本（空白归一）被任一 context 块文本包含
即计覆盖（parent 替换是设计行为，chunk-id 交集对之结构性失明——修仪器
非调阈值，阈值不变）；密封 manifest 记 ``metric_version`` 区分口径。

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
# 主指标口径版本：run-1/2 = chunk-id 集合交集；run-3 起 containment-aware
# （设计文档 Round-3 节，owner 批准后修订，阈值未动）
METRIC_VERSION = "r3-containment-aware"


class GateError(RuntimeError):
    """任何非法状态：调用方应保证零输出 fail-closed。"""


@dataclass
class CaseOutcome:
    """单臂单 case 的产物（context 侧指标输入；零生成调用）。

    round-3：携带 context/真值块文本（与 id 元组逐位对齐，按 chunk_id
    从同一索引快照反查），供 containment 主指标与密封产物复核。
    """

    case_id: str
    arm: str
    context_chunk_ids: tuple[str, ...]
    truth_chunk_ids: tuple[str, ...]
    context_k: int
    refused: bool
    plan_fingerprint: str
    context_chunk_texts: tuple[str, ...] = ()
    truth_chunk_texts: tuple[str, ...] = ()


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
    *,
    chunk_text_by_id: dict[str, str],
) -> tuple[CaseOutcome, CaseOutcome]:
    """同一计划跑 ON/OFF 两臂，返回 (ON, OFF) 两个 CaseOutcome。

    round-3：``chunk_text_by_id``（索引快照的 chunk_id → 块全文）必传——
    文本与 id 同源同快照，是 containment 主指标的输入与产物复核依据。
    """
    # 排序固化：真值集合转元组若依赖 set 迭代序，密封产物将随
    # PYTHONHASHSEED 逐进程漂移，破坏逐字节可复现性。
    ordered_truth = tuple(sorted(truth))
    truth_texts = tuple(chunk_text_by_id.get(tid, "") for tid in ordered_truth)
    outcomes: list[CaseOutcome] = []
    for arm in ARMS:
        evidence = prepare_arms(arm, case.query, plan)
        context_chunk_ids = tuple(evidence.context_chunk_ids)
        outcomes.append(CaseOutcome(
            case_id=case.id, arm=arm,
            context_chunk_ids=context_chunk_ids,
            context_chunk_texts=tuple(
                chunk_text_by_id.get(cid, "") for cid in context_chunk_ids),
            truth_chunk_ids=ordered_truth,
            truth_chunk_texts=truth_texts,
            context_k=int(evidence.context_k),
            refused=bool(evidence.refused),
            plan_fingerprint=getattr(evidence, "plan_fingerprint", ""),
        ))
    return outcomes[0], outcomes[1]


# ── 指标与门禁 ───────────────────────────────────────────────────

def _norm_text(text: str) -> str:
    """空白归一：连续空白折叠为单空格（parent 拼接/换行差异不破坏包含判定）。"""
    return " ".join((text or "").split())


def chunk_context_recall(outcome: Any) -> float:
    """主指标（round-3 预注册修订）：containment-aware 真值覆盖。

    真值块计入覆盖，当且仅当满足其一（设计文档 Round-3 节冻结定义）：
    1. id 命中：真值 chunk_id ∈ context chunk id 集（select 直接召回）；
    2. 文本包含：真值块文本（空白归一）是任一 context 块文本（同归一）
       的连续子串——parent 替换/邻接携带是「证据在场」的设计行为；
       空文本真值不适用本条（空串是任何串的子串，必须显式排除）。

    拒答无 context 计 0；真值为空属非法状态 fail-closed（不变）。
    """
    if getattr(outcome, "refused", False):
        return 0.0
    truth_ids = tuple(outcome.truth_chunk_ids)
    truth_texts = tuple(outcome.truth_chunk_texts)
    if not truth_ids:
        raise GateError(
            f"case {outcome.case_id!r} 真值为空（目标集过滤应已剔除）")
    if len(truth_texts) != len(truth_ids):
        raise GateError(
            f"case {outcome.case_id!r} 真值 id/text 数量不一致"
            f"（{len(truth_ids)} vs {len(truth_texts)}）")
    ctx_ids = set(outcome.context_chunk_ids)
    ctx_norm = [_norm_text(t) for t in outcome.context_chunk_texts]
    covered = 0
    for tid, ttext in zip(truth_ids, truth_texts):
        if tid in ctx_ids:
            covered += 1
            continue
        t_norm = _norm_text(ttext)
        if t_norm and any(t_norm in c for c in ctx_norm):
            covered += 1
    return covered / len(truth_ids)


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
        row["context_chunk_texts"] = list(o.context_chunk_texts)
        row["truth_chunk_texts"] = list(o.truth_chunk_texts)
        row["chunk_context_recall"] = recalls.get(o.arm, {}).get(o.case_id)
        rows.append(row)
    outcomes_bytes = ("\n".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows)
        + ("\n" if rows else "")).encode("utf-8")
    (out_dir / "outcomes.jsonl").write_bytes(outcomes_bytes)

    manifest_body = {
        "lineage": "stage2-parentchild-acceptance",
        "preregistration_doc": prereg_doc,
        "metric_version": METRIC_VERSION,
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
    # containment 主指标的文本反查表：与索引同一快照（chunk_id 兜底命名
    # 约定与 rag._ordered_chunk_ids 一致，保证 context id 必可命中）
    text_by_chunk_id = {
        (meta or {}).get("chunk_id", f"chunk_{i}"): documents[i]
        for i, meta in enumerate(metadatas)
    }
    prepare_arms = make_prepare_arms(index_bundle)
    outcomes: list[CaseOutcome] = []
    recalls: dict[str, dict[str, float]] = {arm: {} for arm in ARMS}
    for i, case in enumerate(targets, 1):
        # 每 case 一次规划（LLM rewrite+decompose+检索各一次），双臂共享
        plan = prepare_query_plan(
            case, model, collection, bm25, documents, metadatas, history=None)
        on, off = run_case_pair(
            case, plan, prepare_arms, truth=truth[case.id],
            chunk_text_by_id=text_by_chunk_id)
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
