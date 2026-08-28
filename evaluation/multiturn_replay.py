"""Stage 2 多轮 rewrite 受控 A/B/C 回放执行器。

设计依据（预注册，阈值冻结后实现，不得回调）：
``plans/STAGE2-MULTITURN-ACCEPTANCE-DESIGN-2026-08-28.md`` §4.1/§4.2

三臂语义（canonical history 取同臂前序轮次的真实回答，臂内自洽）：
- **A 基线**：检索 rewrite 关（history=None）+ 生成无 history —— 旧纯单轮行为；
- **B 诊断**：检索 rewrite 关 + 生成注入 history —— 「历史只进生成」旧形态；
- **C 处理**：history 进 rewrite + 进生成 —— 现生产路径。

主门禁只比 A vs C（单因子）；B 仅诊断不设门。与 compare.py 的 A/B/C
（reranker/Graph 语义）不同构：本执行器走生产 ``prepare_answer_evidence``
→ ``generate_answer`` 拆分（Product P0.1），保证实验路径即生产路径；
链构建复用 ``compare.build_conversation_chains``，指标复用
``metrics.context_source_recall``。

真实运行约定（M4）：调用方负责以沙箱 ``MNEME_DATA_DIR`` 启动（trace 与
chroma 均落沙箱，不触碰 owner 真实数据目录）；embedding 侧离线环境变量由
conftest 同源的调用环境提供。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from evaluation.metrics import context_source_recall
from evaluation.schema import EvalCase, QueryType, load_dataset

# ── 预注册常量（设计 §4.1 冻结；修改即违反预注册纪律） ────────────────
ARMS = ("A", "B", "C")
GATE_MIN_MEAN_DELTA = 0.10        # mean(C) - mean(A) 的通过下限
GATE_MAX_CASE_REGRESSION = 0.05   # 单例恶化容限（幅度）

GATE_ACCEPT = "STAGE2_24_ACCEPTED"
GATE_NOT_PROVEN = "STAGE2_24_NOT_PROVEN"
GATE_REGRESSION = "STAGE2_24_REGRESSION"

GATE_ARM_BASE = "A"
GATE_ARM_TREATMENT = "C"


class ReplayError(RuntimeError):
    """任何非法状态：调用方应保证零输出 fail-closed。"""


@dataclass
class TurnOutcome:
    """单臂单轮的回放产物（含路由证据与指标输入）。"""

    case_id: str
    arm: str
    prepare_history_pairs: int    # 传入检索规划侧的 history 长度（路由证据）
    generate_history_pairs: int   # 传入生成侧的 history 长度
    context_source_ids: tuple[str, ...]
    context_k: int
    candidate_count: int
    refused: bool
    plan_fingerprint: str         # C vs A 指纹差异 = rewrite 改写了规划（诊断）
    answer: str


def followup_ids(chain: list[EvalCase]) -> list[str]:
    """链内追问 case（排除根轮）；turn-1 三臂机械同态，不入门禁分母。"""
    return [c.id for c in chain[1:]]


# ── 生产路径默认接线 ─────────────────────────────────────────────

def production_prepare():
    from src.rag import prepare_answer_evidence
    return prepare_answer_evidence


def production_generate():
    from src.rag import generate_answer
    return generate_answer


def _make_production_prepare(index_bundle: dict, default_temperature):
    fn = production_prepare()

    def _prepare(*, query, history, llm_temperature=None):
        temperature = llm_temperature if llm_temperature is not None \
            else default_temperature
        return fn(
            query, index_bundle["model"], index_bundle["collection"],
            index_bundle["bm25"], index_bundle["documents"],
            index_bundle["metadatas"],
            history=history, llm_temperature=temperature)

    return _prepare


def _make_production_generate(index_bundle, default_temperature):
    fn = production_generate()

    def _generate(evidence, *, history, llm_temperature=None):
        temperature = llm_temperature if llm_temperature is not None \
            else default_temperature
        return fn(evidence, index_bundle["documents"],
                  index_bundle["metadatas"],
                  temperature=temperature, history=history)

    return _generate


# ── 三臂回放 ─────────────────────────────────────────────────────

def run_arm(
    arm: str,
    chain: list[EvalCase],
    *,
    prepare_fn: Callable | None = None,
    generate_fn: Callable | None = None,
    index_bundle: dict | None = None,
    llm_temperature: float | None = None,
) -> list[TurnOutcome]:
    """按臂语义顺序回放一条对话链。

    canonical history 每轮累积 ``(query, answer)``；是否**注入**检索/生成
    由臂决定（A 双不注入 / B 仅生成 / C 双注入）。空历史归一为 None，
    使 turn-1 在三臂下与无历史调用逐字节同态。
    """
    if arm not in ARMS:
        raise ReplayError(f"未知 arm: {arm!r}（可选 {ARMS}）")
    if prepare_fn is None or generate_fn is None:
        if index_bundle is None:
            raise ReplayError("默认生产路径需要 index_bundle")
        prepare_fn = prepare_fn or _make_production_prepare(
            index_bundle, llm_temperature)
        generate_fn = generate_fn or _make_production_generate(
            index_bundle, llm_temperature)

    outcomes: list[TurnOutcome] = []
    history: list[tuple[str, str]] = []
    for case in chain:
        canonical = list(history) or None
        h_prepare = canonical if arm == "C" else None
        h_generate = canonical if arm in ("B", "C") else None

        evidence = prepare_fn(
            query=case.query, history=h_prepare,
            llm_temperature=llm_temperature)
        answer, _sources = generate_fn(
            evidence, history=h_generate, llm_temperature=llm_temperature)

        outcomes.append(TurnOutcome(
            case_id=case.id, arm=arm,
            prepare_history_pairs=len(h_prepare) if h_prepare else 0,
            generate_history_pairs=len(h_generate) if h_generate else 0,
            context_source_ids=tuple(evidence.context_source_ids),
            context_k=int(evidence.context_k),
            candidate_count=len(evidence.candidate_chunk_ids),
            refused=bool(evidence.refused),
            plan_fingerprint=getattr(evidence, "plan_fingerprint", ""),
            answer=answer,
        ))
        history.append((case.query, answer))
    return outcomes


# ── 指标与门禁 ───────────────────────────────────────────────────

def case_source_recall(evidence: Any, case: EvalCase) -> float:
    """主指标：实际进入 prompt 的 context 对 relevant sources 的覆盖。

    检索前哨拒答（refused）时无 context，按 0.0 计入（拒答本身是
    独立诊断量，不做剔除——剔除即改变预注册分母）。
    """
    if getattr(evidence, "refused", False):
        return 0.0
    return context_source_recall(
        list(evidence.context_source_ids), set(case.relevant_source_ids))


def evaluate_gate(
    recalls: dict[str, dict[str, float]],
    followups: list[str],
) -> dict:
    """预注册三态门禁（A vs C 单因子；B 仅附诊断均值）。缺结果即抛错。"""
    for arm in (GATE_ARM_BASE, GATE_ARM_TREATMENT):
        missing = [cid for cid in followups if cid not in recalls.get(arm, {})]
        if missing:
            raise ReplayError(f"{arm} 臂缺少 follow-up 结果: {missing}")
    if not followups:
        raise ReplayError("follow-up 集为空，无法判定门禁")

    n = len(followups)
    mean_a = sum(recalls[GATE_ARM_BASE][c] for c in followups) / n
    mean_c = sum(recalls[GATE_ARM_TREATMENT][c] for c in followups) / n
    per_case_delta = {
        c: recalls[GATE_ARM_TREATMENT][c] - recalls[GATE_ARM_BASE][c]
        for c in followups}
    worst = min(per_case_delta.values())

    # 预注册判定顺序：先验通过条件（均值达阈 且 无单例超限恶化），
    # 再按均值方向二分（未证明 / 回归）。
    if (mean_c - mean_a >= GATE_MIN_MEAN_DELTA
            and worst >= -GATE_MAX_CASE_REGRESSION):
        verdict = GATE_ACCEPT
    elif mean_c >= mean_a:
        verdict = GATE_NOT_PROVEN
    else:
        verdict = GATE_REGRESSION

    gate = {
        "verdict": verdict,
        "mean_a": mean_a,
        "mean_c": mean_c,
        "mean_delta": mean_c - mean_a,
        "worst_case_delta": worst,
        "per_case_delta": per_case_delta,
        "thresholds": {
            "min_mean_delta": GATE_MIN_MEAN_DELTA,
            "max_case_regression": GATE_MAX_CASE_REGRESSION,
            "n_followups": n,
        },
    }
    if "B" in recalls and all(c in recalls["B"] for c in followups):
        gate["mean_b"] = sum(recalls["B"][c] for c in followups) / n
    return gate


# ── 密封产物 ─────────────────────────────────────────────────────

def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_outputs(
    out_dir: Path,
    *,
    turns: list[TurnOutcome],
    recalls: dict[str, dict[str, float]],
    gate: dict,
    dataset_sha: str,
    corpus_files: list[str],
    prereg_doc: str,
) -> None:
    """写密封产物：turns.jsonl + 自哈希 manifest。输出目录拒绝已存在。"""
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise ReplayError(f"输出目录已存在，拒绝覆盖（fail-closed）: {out_dir}")
    out_dir.mkdir(parents=True)

    rows = []
    for t in turns:
        row = asdict(t)
        row["context_source_ids"] = list(t.context_source_ids)
        row["source_recall"] = recalls.get(t.arm, {}).get(t.case_id)
        rows.append(row)
    turns_bytes = ("\n".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows)
        + ("\n" if rows else "")).encode("utf-8")
    (out_dir / "turns.jsonl").write_bytes(turns_bytes)

    manifest_body = {
        "lineage": "stage2-multiturn-acceptance",
        "preregistration_doc": prereg_doc,
        "dataset_sha256": dataset_sha,
        "corpus_files": corpus_files,
        "arms": list(ARMS),
        "gate_thresholds": {
            "min_mean_delta": GATE_MIN_MEAN_DELTA,
            "max_case_regression": GATE_MAX_CASE_REGRESSION,
        },
        "row_count": len(rows),
        "turns_sha256": _sha256_bytes(turns_bytes),
        "gate": gate,
    }
    manifest_body["manifest_sha256"] = _sha256_bytes(
        _dump(manifest_body).encode("utf-8"))
    (out_dir / "manifest.json").write_text(
        _dump(manifest_body), encoding="utf-8")


# ── CLI（M4 真实运行入口） ────────────────────────────────────────

def _load_chains(dataset_path: Path) -> tuple[list[EvalCase], dict]:
    cases = load_dataset(dataset_path)
    multi = [c for c in cases if c.query_type == QueryType.MULTI_TURN]
    if not multi:
        raise ReplayError(f"数据集无 multi_turn case: {dataset_path}")
    from evaluation.compare import build_conversation_chains
    chains = build_conversation_chains(multi)
    return multi, chains


def _resolve_corpus(corpus_dir: Path, multi_cases: list[EvalCase]) -> list[Path]:
    """union(relevant_source_ids) 必须全部在语料目录内（fail-closed）。"""
    names = sorted({s for c in multi_cases for s in c.relevant_source_ids})
    paths = []
    for name in names:
        path = corpus_dir / name
        if not path.exists():
            raise ReplayError(f"语料缺失: {name}（corpus_dir={corpus_dir}）")
        paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stage 2 多轮 rewrite 受控 A/B/C 回放（M4）")
    parser.add_argument("--dataset", default="evaluation/datasets/v1.jsonl")
    parser.add_argument("--corpus-dir", default="test_texts")
    parser.add_argument("--collection", default="eval_stage2_multiturn")
    parser.add_argument("--output", required=True,
                        help="密封输出目录（必须不存在）")
    parser.add_argument("--force-rebuild-index", action="store_true")
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset)
    multi, chains = _load_chains(dataset_path)
    corpus_paths = _resolve_corpus(Path(args.corpus_dir), multi)
    print(f"[preflight] multi_turn cases={len(multi)} "
          f"chains={len(chains)} corpus={len(corpus_paths)}")

    from src.rag import prepare_index
    bundle_inputs = prepare_index(
        [str(p) for p in corpus_paths], args.collection,
        args.force_rebuild_index)
    model, collection, bm25, documents, metadatas = bundle_inputs
    index_bundle = {
        "model": model, "collection": collection, "bm25": bm25,
        "documents": documents, "metadatas": metadatas,
    }
    print(f"[index] chunks={len(documents)}")

    turns: list[TurnOutcome] = []
    recalls: dict[str, dict[str, float]] = {arm: {} for arm in ARMS}
    case_by_id = {c.id: c for c in multi}
    for arm in ARMS:
        for root_id in sorted(chains):
            arm_turns = run_arm(
                arm, chains[root_id], index_bundle=index_bundle)
            turns.extend(arm_turns)
            for t in arm_turns:
                recalls[arm][t.case_id] = case_source_recall(
                    t, case_by_id[t.case_id])
            print(f"[arm {arm}] chain {root_id} done "
                  f"({len(arm_turns)} turns)")

    followups = [cid for chain in chains.values()
                 for cid in followup_ids(chain)]
    gate = evaluate_gate(recalls, followups)
    write_outputs(
        Path(args.output), turns=turns, recalls=recalls, gate=gate,
        dataset_sha=_sha256_bytes(dataset_path.read_bytes()),
        corpus_files=[p.name for p in corpus_paths],
        prereg_doc="plans/STAGE2-MULTITURN-ACCEPTANCE-DESIGN-2026-08-28.md")

    print(json.dumps(
        {k: gate[k] for k in ("verdict", "mean_a", "mean_b", "mean_c",
                              "mean_delta", "worst_case_delta")
         if k in gate}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
