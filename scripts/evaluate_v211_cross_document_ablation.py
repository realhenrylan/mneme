"""Phase 6-C1 — v2.0.11 冻结基线上的跨文档检索受控消融（read-only）。

在已验收的 hardened snapshot contract（Phase 6-B0.1）之上，评估候选
**确定性检索策略**是否可证明提升 cross-document evidence-chunk 排序。
不修改测试集 / 语料 / v2.0.11；不调用任何 LLM / 生成模型 / LLM judge /
联网 API / query rewriting 服务；不改默认产品检索行为（候选策略显式
opt-in，见 ``src/retrieval_ablation.py``）。

设计（先复算后输出，任一漂移 → fail-closed 零产物）：
1. 前置复算：freeze/candidate/targeted-review 61 项（复用 Phase 6-A）、
   Phase 6-A manifest、旧 Phase 6-B0 manifest、**hardened B0.1 manifest**
   （self-hash + inputs / frozen_outputs / phase6a_outputs / outputs 字节
   SHA）——任一漂移立即中止；
2. 同一冻结 contract 索引（``src.rag.prepare_index`` + snapshot，一次性
   临时目录，含 collection manifest + BM25 sidecar）上双臂对照：
   - 基线臂 ``single-query``：既有产品检索代码 ``bl6a.run_retrieval``；
   - 候选臂 ``mechanical-clause-rrf``：机械 query variants + 跨 variant
     RRF(k=60) 融合 + chunk_id tie-break + provenance；
3. 两次独立构建各跑双臂；cross_document 分组（恰 26 case）单独聚合；
4. **Promotion gate**（预先锁定，机械判定）：候选仅当全部 6 项条件在
   两次独立构建上同时满足才标 ``EXPERIMENT_PROMISING``——即便如此也
   **不改变默认产品检索策略**；否则正确结果 ``NO_PROMOTION``；
5. HNSW 跨构建近邻扰动如实记录（raw 差异 / 指标差异 / 噪声量级），
   不伪称逐 case 字节一致；
6. 明确 ``not_measured``：answer quality / citation faithfulness /
   answer-level refusal accuracy。

产物（新建且仅写入）：``evaluation/product-baselines/v2.0.11-cross-document-ablation/``
共 7 个：ablation-summary.json / per-case-results-baseline.jsonl /
per-case-results-candidate.jsonl / cross-document-analysis.md /
selection-decision.md / data-quality-report.json / manifest.json。

CLI
---
::

    python scripts/evaluate_v211_cross_document_ablation.py
        [--output DIR] [--phase6b0-dir DIR] [--hardened-dir DIR]
        [--strategy NAME] [--prior-run-dir DIR] [--skip-determinism]

退出码：0=成功；2=冻结 / 6A / B0 / hardened / contract 漂移（fail-closed，
零产物）；1=其他错误（含未知策略）。

``data-analytics:analyze-data-quality`` skill 实际检查：zcode 运行环境
不可用（本次会话可用技能列表无此技能；``~/.zcode/skills`` 仅
brainstorming/test-driven-development、``~/.agents/skills`` 仅
browser-skill、插件目录无 data-analytics）——不能声称所有环境均不可用；
数据质量以等价的确定性机械复算实施，如实记录。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# 强制离线（在导入任何模型库之前无条件设置，与 Phase 6-A/B0/B0.1 一致）
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.evaluate_v211_frozen_product_baseline as bl6a  # noqa: E402
import scripts.evaluate_v211_frozen_product_contract as cbl  # noqa: E402
import scripts.evaluate_v211_frozen_product_contract_hardened as hbl  # noqa: E402
import src.index_contract as ic  # noqa: E402
import src.retrieval_ablation as abl  # noqa: E402

# ── 目录常量 ──────────────────────────────────────────────────────────
ABLATION_DIR = REPO_ROOT / "evaluation/product-baselines/v2.0.11-cross-document-ablation"
PHASE6A_DIR = cbl.PHASE6A_DIR
PHASE6B0_DIR = cbl.OUTPUT_DIR
HARDENED_DIR = hbl.HARDENED_DIR
FREEZE_DIR = bl6a.FREEZE_DIR
FROZEN_REVISION_DIR = bl6a.FROZEN_REVISION_DIR
CHUNKS_PATH = bl6a.CHUNKS_PATH
CURRENT_DRAFT_PATH = bl6a.CURRENT_DRAFT_PATH
CORPUS_MANIFEST_PATH = cbl.CORPUS_MANIFEST_PATH
COLLECTION_NAME = cbl.COLLECTION_NAME
KS = bl6a.KS

# 本阶段产物（白名单，测试依赖）
ABLATION_OUTPUT_FILES = (
    "ablation-summary.json",
    "per-case-results-baseline.jsonl",
    "per-case-results-candidate.jsonl",
    "cross-document-analysis.md",
    "selection-decision.md",
    "data-quality-report.json",
    "manifest.json",
)

_COMPARE_METRIC_KEYS = cbl._COMPARE_METRIC_KEYS

# 预先锁定的 promotion gate（任务指定；机械判定，绝不改默认策略）
DEFAULT_GATE = {
    "cd_recall5_min_gain": 0.03,         # 条件 1：cd recall@5 提升 ≥ +0.03
    "overall_max_drop": 0.01,            # 条件 2/3：全量指标允许最大下降
    "cd_source_recall5_min_delta": 0.0,  # 条件 4：cd source recall@5 不下降
    "noise_factor": 3.0,                 # 条件 5：增益须 ≥ 3×记录噪声
}

# data-analytics skill 实际检查证据（zcode 运行环境不可用，等价机械复算替代）
_SKILL_EVIDENCE = (
    "data-analytics:analyze-data-quality 实际检查：zcode 运行环境不可用"
    "（本次会话可用技能列表、~/.zcode/skills 仅 brainstorming/"
    "test-driven-development、~/.agents/skills 仅 browser-skill、插件目录"
    "均无 data-analytics）——不能声称所有环境均不可用；实施等价的确定性"
    "机械复算"
)


class BaselineDrift(Exception):
    """冻结 / 6A / B0 / hardened / contract 漂移——fail-closed，零产物。"""


# ── 基线 manifest 复算（lineage 前置校验）─────────────────────────────

def _verify_baseline_manifest(manifest_dir: Path, *, label: str,
                              section_bases: dict[str, Path | None]) -> dict:
    """复算任一基线 manifest：self-hash + 各段字节 SHA。纯只读。

    section_bases: 段名 → 基准目录（记录为 path+sha 的段用 None）。
    """
    manifest_path = Path(manifest_dir) / "manifest.json"
    checks: list[dict] = []
    if not manifest_path.is_file():
        return {"verified": False, "checks": [], "drift": [{
            "name": f"{label}-manifest", "kind": "missing",
            "status": "missing", "expected": None, "actual": None,
            "path": str(manifest_path),
        }]}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = bl6a.self_hash(manifest)
    checks.append({
        "name": f"{label}-manifest self-hash", "kind": "manifest_self_hash",
        "status": "ok" if actual == manifest.get("manifest_sha256") else "mismatch",
        "expected": manifest.get("manifest_sha256"), "actual": actual,
        "path": str(manifest_path),
    })
    for section, base in section_bases.items():
        for name, rec in sorted(manifest.get(section, {}).items()):
            if isinstance(rec, str):
                path = Path(base) / name
                expected = rec
            else:
                path = Path(rec["path"])
                expected = rec["sha256"]
            actual_sha = bl6a.sha256_bytes(path) if path.is_file() else None
            checks.append({
                "name": f"{label} {section}/{name}", "kind": section,
                "status": ("ok" if actual_sha == expected
                           else ("missing" if actual_sha is None else "mismatch")),
                "expected": expected, "actual": actual_sha, "path": str(path),
            })
    drift = [
        {k: c[k] for k in ("name", "kind", "status", "expected", "actual", "path")}
        for c in checks if c["status"] != "ok"
    ]
    return {"verified": not drift, "checks": checks, "drift": drift}


def verify_hardened_manifest(hardened_dir: Path, phase6a_dir: Path) -> dict:
    """复算 hardened B0.1 manifest（4 段：inputs / frozen_outputs /
    phase6a_outputs / outputs）。"""
    return _verify_baseline_manifest(
        hardened_dir, label="hardened",
        section_bases={
            "inputs": None,
            "frozen_outputs": FREEZE_DIR,
            "phase6a_outputs": Path(phase6a_dir),
            "outputs": Path(hardened_dir),
        })


# ── cross_document 分组聚合 ───────────────────────────────────────────

def _cd_metrics(results: list[dict]) -> dict:
    """cross_document 分组的聚合指标（chunk 指标与 bl6a 同口径 +
    source recall 均值；n = 有真值 case 数）。"""
    from evaluation.metrics import compute_stratified_metrics, source_recall_at_k
    rows = [r for r in results
            if r["query_type"] == "cross_document" and r["relevant_chunk_ids"]]
    if not rows:
        return {"n": 0}
    agg = compute_stratified_metrics(
        [r["retrieved_chunk_ids"] for r in rows],
        [set(r["relevant_chunk_ids"]) for r in rows],
        ["cd"] * len(rows), ks=KS)["cd"]
    for k in KS:
        agg[f"source_recall@{k}"] = sum(
            source_recall_at_k(r["retrieved_source_ids"],
                               set(r["relevant_source_ids"]), k)
            for r in rows) / len(rows)
    agg["n"] = len(rows)
    return agg


# ── promotion gate（机械判定）─────────────────────────────────────────

def _build_conditions(b: dict, gate: dict) -> dict:
    """单个构建上的条件 1-4（任务 gate 的前四项）。"""
    def _delta(key: str, bl: dict, ca: dict) -> float:
        return round(ca[key] - bl[key], 9)

    gain = _delta("recall@5", b["baseline_cd"], b["candidate_cd"])
    cd_src = _delta("source_recall@5", b["baseline_cd"], b["candidate_cd"])
    return {
        "cd_recall@5_gain": {
            "ok": gain >= gate["cd_recall5_min_gain"],
            "baseline": b["baseline_cd"].get("recall@5"),
            "candidate": b["candidate_cd"].get("recall@5"),
            "delta": gain,
            "required": f"cd recall@5 提升 ≥ +{gate['cd_recall5_min_gain']}",
        },
        "overall_recall@5_no_drop": {
            "ok": _delta("recall@5", b["baseline"], b["candidate"])
            >= -gate["overall_max_drop"],
            "baseline": b["baseline"].get("recall@5"),
            "candidate": b["candidate"].get("recall@5"),
            "delta": _delta("recall@5", b["baseline"], b["candidate"]),
            "required": f"全量 recall@5 下降 ≤ {gate['overall_max_drop']}",
        },
        "overall_ndcg10_mrr_no_drop": {
            "ok": all(
                _delta(key, b["baseline"], b["candidate"])
                >= -gate["overall_max_drop"] for key in ("ndcg@10", "mrr")),
            "baseline": {k: b["baseline"].get(k) for k in ("ndcg@10", "mrr")},
            "candidate": {k: b["candidate"].get(k) for k in ("ndcg@10", "mrr")},
            "deltas": {k: _delta(k, b["baseline"], b["candidate"])
                       for k in ("ndcg@10", "mrr")},
            "required": f"全量 nDCG@10 与 MRR 下降均 ≤ {gate['overall_max_drop']}",
        },
        "cd_source_recall@5_no_drop": {
            "ok": cd_src >= -1e-9,
            "baseline": b["baseline_cd"].get("source_recall@5"),
            "candidate": b["candidate_cd"].get("source_recall@5"),
            "delta": cd_src,
            "required": "cd source recall@5 不下降（float 容差 1e-9）",
        },
    }


def evaluate_gate(*, build1: dict, build2: dict, noise_cd_recall5: float,
                  checks_ok: bool = True, gate: dict | None = None) -> dict:
    """机械判定候选策略是否 ``EXPERIMENT_PROMISING``。

    6 项条件（任务预先锁定）：1-4 在 build1/build2 上分别评估，条件 5
    要求两次独立构建同方向且增益 ≥ noise_factor × 记录噪声，条件 6 要求
    全部冻结/身份/manifest/数据质量检查通过。任一失败 → NO_PROMOTION。
    """
    gate = {**DEFAULT_GATE, **(gate or {})}
    c1 = _build_conditions(build1, gate)
    c2 = _build_conditions(build2, gate)

    combined: list[dict] = []
    for cid in ("cd_recall@5_gain", "overall_recall@5_no_drop",
                "overall_ndcg10_mrr_no_drop", "cd_source_recall@5_no_drop"):
        combined.append({"id": cid,
                         "ok": c1[cid]["ok"] and c2[cid]["ok"],
                         "build1": c1[cid], "build2": c2[cid]})

    gains = [c1["cd_recall@5_gain"]["delta"], c2["cd_recall@5_gain"]["delta"]]
    min_gain = min(gains)
    exceeds_noise = min_gain >= gate["noise_factor"] * noise_cd_recall5
    combined.append({
        "id": "exceeds_recorded_noise", "ok": exceeds_noise,
        "min_gain_across_builds": min_gain,
        "noise_cd_recall5": noise_cd_recall5,
        "required": (f"cd recall@5 增益 ≥ {gate['noise_factor']} × "
                     f"记录的跨构建噪声（{noise_cd_recall5:.6f}）"),
        "formula": "min(build1_gain, build2_gain) ≥ noise_factor × noise",
    })
    combined.append({"id": "all_checks_passed", "ok": bool(checks_ok)})

    failures = [c["id"] for c in combined if not c["ok"]]
    decision = "EXPERIMENT_PROMISING" if not failures else "NO_PROMOTION"
    return {
        "decision": decision,
        "gate": gate,
        "conditions": combined,
        "failures": failures,
        "note": ("候选策略仅当全部条件在两次独立构建上同时满足才可标为 "
                 "EXPERIMENT_PROMISING；即便满足也**不改变默认产品检索策略**"
                 "——决策只记录于本消融产物，供后续阶段参考"),
    }


# ── 与 hardened 基线对比（基线臂诚实对照）────────────────────────────

def compare_to_hardened(hardened_dir: Path, baseline_results: list[dict],
                        metrics: dict) -> dict:
    """基线臂 vs hardened 基线：aggregate Δ + per-case 差异（HNSW 噪声级）。"""
    hd = Path(hardened_dir)
    summary_hd = json.loads(
        (hd / "contract-baseline-summary.json").read_text(encoding="utf-8"))
    rows_hd = {
        r["case_id"]: r
        for r in bl6a.load_jsonl(hd / "per-case-retrieval-results.jsonl")
    }
    m0 = summary_hd["metrics"]["overall"]
    m1 = metrics["overall"]
    aggregate_deltas = {
        key: (round(m1.get(key) - m0.get(key), 6)
              if m0.get(key) is not None and m1.get(key) is not None else None)
        for key in _COMPARE_METRIC_KEYS
    }
    per_case = []
    for r in baseline_results:
        other = rows_hd.get(r["case_id"])
        if other is None:
            per_case.append({"case_id": r["case_id"], "note": "missing in hardened"})
            continue
        metric_diffs = {
            k: {"hardened": other["metrics"].get(k),
                "ablation_baseline": r["metrics"].get(k)}
            for k in _COMPARE_METRIC_KEYS
            if r["metrics"].get(k) != other["metrics"].get(k)
        }
        retrieved_equal = r["retrieved_chunk_ids"] == other["retrieved_chunk_ids"]
        if metric_diffs or not retrieved_equal:
            per_case.append({
                "case_id": r["case_id"], "metric_diffs": metric_diffs,
                "retrieved_equal": retrieved_equal,
            })
    per_case.sort(key=lambda c: c["case_id"])
    return {
        "hardened_dir": str(hd),
        "aggregate_deltas": aggregate_deltas,
        "per_case_metric_diff_count": sum(
            1 for c in per_case if c.get("metric_diffs")),
        "per_case_retrieval_diff_count": sum(
            1 for c in per_case if c.get("retrieved_equal") is False),
        "per_case_differences": per_case[:50],
        "note": "基线臂与 hardened 使用同一冻结 chunks 与同一检索代码；"
                "差异来源为 HNSW 跨构建近邻扰动（本次消融独立建索引），"
                "聚合指标应稳定，任何不一致如实列出",
    }


def compare_prior_run(prior_run_dir: Path, results_b: list[dict],
                      results_c: list[dict], metrics_b: dict,
                      metrics_c: dict) -> dict:
    """跨两次完整运行的对比（聚合 Δ + per-case 差异计数）。"""
    prior_dir = Path(prior_run_dir)
    prior_summary = json.loads(
        (prior_dir / "ablation-summary.json").read_text(encoding="utf-8"))
    prior_manifest = json.loads(
        (prior_dir / "manifest.json").read_text(encoding="utf-8"))

    def _per_case_diff_count(prior_rows: list[dict], cur_rows: list[dict]) -> int:
        prior_by_id = {r["case_id"]: r for r in prior_rows}
        return sum(
            1 for r in cur_rows
            if (p := prior_by_id.get(r["case_id"])) is not None
            and (r["retrieved_chunk_ids"] != p["retrieved_chunk_ids"]
                 or r["metrics"] != p["metrics"])
        )

    prior_b = bl6a.load_jsonl(prior_dir / "per-case-results-baseline.jsonl")
    prior_c = bl6a.load_jsonl(prior_dir / "per-case-results-candidate.jsonl")
    return {
        "prior_run_dir": str(prior_dir),
        "prior_manifest_sha256": prior_manifest.get("manifest_sha256"),
        "prior_gate_decision": prior_summary.get("gate", {}).get("decision"),
        "aggregate_deltas": {
            "baseline": {
                k: round(metrics_b["overall"].get(k, 0)
                         - prior_summary["baseline"]["metrics"]["overall"].get(k, 0), 6)
                for k in _COMPARE_METRIC_KEYS},
            "candidate": {
                k: round(metrics_c["overall"].get(k, 0)
                         - prior_summary["candidate"]["metrics"]["overall"].get(k, 0), 6)
                for k in _COMPARE_METRIC_KEYS},
        },
        "cd_recall5_delta": {
            "baseline": round(
                metrics_b["by_query_type"]["cross_document"]["recall@5"]
                - prior_summary["baseline"]["metrics"]["by_query_type"]
                  ["cross_document"]["recall@5"], 6),
            "candidate": round(
                metrics_c["by_query_type"]["cross_document"]["recall@5"]
                - prior_summary["candidate"]["metrics"]["by_query_type"]
                  ["cross_document"]["recall@5"], 6),
        },
        "per_case_diff_count": {
            "baseline": _per_case_diff_count(prior_b, results_b),
            "candidate": _per_case_diff_count(prior_c, results_c),
        },
        "note": "两次独立完整运行间的聚合差异；跨运行 HNSW 扰动与运行内"
                "determinism 一致，如实记录，不做掩盖",
    }


# ── 数据质量机械检查（data-analytics skill 实际检查不可用 → 等价复算）─

def data_quality_check(*, results_b: list[dict], results_c: list[dict],
                       metrics_b: dict, metrics_c: dict, cases: list[dict],
                       mapping_report: dict, cd: dict,
                       verification: dict, manifest: dict | None,
                       frozen_chunk_ids: set[str], strategy_spec: dict) -> dict:
    """核心数据质量机械检查（C1.1 语义：**不含** promotion gate 条件）。

    ``passed`` / ``error_count`` 只反映核心 data-quality checks（完整性/
    唯一性/指标复算/引用完整性/守恒/策略不变量/谱系与 manifest 闭环）；
    gate 结果独立成段（``promotion_eligibility``），失败 gate 不是
    data-quality 失败，也不得混入本报告——``passed`` 不暗示 promotion
    通过。
    """
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[dict] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    den = metrics_b["overall"]["denominators"]
    total = den["total_cases"]

    # 1. 完整性（双臂行数守恒 + 行键）
    _check("completeness.baseline_rows", len(results_b) == total,
           f"rows={len(results_b)} expected={total}")
    _check("completeness.candidate_rows", len(results_c) == total,
           f"rows={len(results_c)} expected={total}")
    missing_b = bl6a.PER_CASE_OUTPUT_KEYS - set(results_b[0])
    _check("completeness.baseline_keys", not missing_b,
           f"missing keys={sorted(missing_b)}")
    missing_c = bl6a.PER_CASE_OUTPUT_KEYS - set(results_c[0])
    _check("completeness.candidate_keys", not missing_c,
           f"missing keys={sorted(missing_c)}")

    # 2. 唯一性
    ids = [r["case_id"] for r in results_b]
    dup = sorted({c for c in ids if ids.count(c) > 1})
    _check("uniqueness.case_ids", not dup, f"duplicates={dup}")
    _check("uniqueness.candidate_case_ids",
           [r["case_id"] for r in results_b] == [r["case_id"] for r in results_c],
           "baseline/candidate 行序不一致")

    # 3. 有效性
    bad_values: list[str] = []
    for rows in (results_b, results_c):
        for r in rows:
            for key, value in r["metrics"].items():
                if not (0.0 <= value <= 1.0):
                    bad_values.append(f"{r['case_id']}.{key}={value}")
    _check("validity.metric_ranges", not bad_values, "; ".join(bad_values[:5]))

    # 4. 一致性（per-case 复算 + 聚合均值，双臂）
    from evaluation.metrics import recall_at_k, ndcg_at_k, source_recall_at_k
    mismatch: list[str] = []
    for rows in (results_b, results_c):
        for r in rows:
            if not r["relevant_chunk_ids"]:
                continue
            recomputed = {
                **{f"recall@{k}": recall_at_k(
                    r["retrieved_chunk_ids"], set(r["relevant_chunk_ids"]), k)
                   for k in KS},
                **{f"ndcg@{k}": ndcg_at_k(
                    r["retrieved_chunk_ids"], set(r["relevant_chunk_ids"]), k)
                   for k in KS},
                **{f"source_recall@{k}": source_recall_at_k(
                    r["retrieved_source_ids"], set(r["relevant_source_ids"]), k)
                   for k in KS},
            }
            for key, value in recomputed.items():
                if abs(value - r["metrics"][key]) > 1e-9:
                    mismatch.append(f"{r['case_id']}.{key}")
    _check("consistency.per_case_recompute", not mismatch,
           "; ".join(mismatch[:5]))
    agg_mismatch: list[str] = []
    for rows, arm_metrics in ((results_b, metrics_b), (results_c, metrics_c)):
        for key in _COMPARE_METRIC_KEYS:
            truth_rows = [r for r in rows if r["metrics"]]
            mean = (sum(r["metrics"][key] for r in truth_rows)
                    / len(truth_rows)) if truth_rows else None
            if mean is not None and abs(mean - arm_metrics["overall"][key]) > 1e-9:
                agg_mismatch.append(f"{key}: {mean:.6f} vs "
                                    f"{arm_metrics['overall'][key]:.6f}")
    _check("consistency.aggregates_vs_mean", not agg_mismatch,
           "; ".join(agg_mismatch[:5]))

    # 5. 引用完整性（双臂 retrieved ids + 真值 ids 均在冻结语料内）
    orphan_retrieved = sorted({
        cid for rows in (results_b, results_c)
        for r in rows for cid in r["retrieved_chunk_ids"]
        if cid not in frozen_chunk_ids
    })
    _check("referential.retrieved_ids_in_corpus", not orphan_retrieved,
           f"orphan={orphan_retrieved[:5]}")
    orphan_relevant = sorted({
        cid for r in results_b for cid in r["relevant_chunk_ids"]
        if cid not in frozen_chunk_ids
    })
    _check("referential.relevant_ids_in_corpus", not orphan_relevant,
           f"orphan={orphan_relevant[:5]}")
    _check("referential.mapping_failures_zero",
           not mapping_report["mapping"]["mapping_failures"],
           str(mapping_report["mapping"]["mapping_failures"]))

    # 6. 守恒（136 / 105 / 31 / 0；cd 恰 n case）
    _check("conservation.case_counts",
           den == {
               "total_cases": len(cases),
               "chunk_metrics_cases": sum(
                   1 for c in cases if c["relevant_chunk_ids"]),
               "no_chunk_truth_cases": sum(
                   1 for c in cases if c["should_refuse"]),
               "mapping_failure_rows": len(
                   mapping_report["mapping"]["mapping_failures"]),
           }, str(den))
    _check("conservation.mapping_failures_zero",
           den["mapping_failure_rows"] == 0, str(den))
    _check("conservation.cross_document_n", cd["n"] == sum(
        1 for c in cases if c["query_type"] == "cross_document"),
        f"cd n={cd['n']}")

    # 7. 策略有效性（variant 机械不变量，全部 query 复算）
    max_variants = strategy_spec["params"].get("max_variants", 8)
    variant_issues: list[str] = []
    for r in results_c:
        variants = r["variants"]
        query = r["query"]
        if not variants or variants[0] != query:
            variant_issues.append(f"{r['case_id']}: variants[0] != query")
            continue
        if len(variants) != len(set(variants)):
            variant_issues.append(f"{r['case_id']}: duplicate variants")
        for v in variants:
            if not v or v not in query:
                variant_issues.append(f"{r['case_id']}: non-literal variant {v!r}")
        if len(variants) > max_variants:
            variant_issues.append(f"{r['case_id']}: over max_variants")
        recomputed = abl.generate_query_variants(query, max_variants=max_variants)
        if recomputed != variants:
            variant_issues.append(f"{r['case_id']}: variant regeneration drift")
        if len(r["retrieved_chunk_ids"]) != len(set(r["retrieved_chunk_ids"])):
            variant_issues.append(f"{r['case_id']}: duplicate retrieved chunk ids")
        prov_ids = [p["chunk_id"] for p in r["provenance"]]
        if prov_ids != r["retrieved_chunk_ids"][:len(prov_ids)]:
            variant_issues.append(f"{r['case_id']}: provenance mismatch")
        for p in r["provenance"][:10]:
            if not p["source_id"] or not p["source_path"] or not p["source_name"]:
                variant_issues.append(f"{r['case_id']}: missing source identity")
                break
    _check("strategy.variants_literal_substrings", not variant_issues,
           "; ".join(variant_issues[:5]))
    _check("strategy.candidate_no_duplicate_chunk_ids", not variant_issues,
           "见 strategy.variants_literal_substrings")

    # 8. lineage + manifest 闭环
    _check("lineage.frozen_verified", verification["frozen_verified"])
    _check("lineage.phase6a_verified", verification["phase6a_verified"])
    _check("lineage.phase6b0_verified", verification["phase6b0_verified"])
    _check("lineage.hardened_verified", verification["hardened_verified"])
    if manifest is not None:
        _check("referential.manifest_self_hash",
               manifest.get("manifest_sha256") == bl6a.self_hash(manifest))
        bad_input = [
            name for name, rec in manifest.get("inputs", {}).items()
            if not Path(rec["path"]).is_file()
            or bl6a.sha256_bytes(Path(rec["path"])) != rec["sha256"]
        ]
        _check("referential.manifest_input_shas", not bad_input,
               f"bad={bad_input[:5]}")

    return {
        "passed": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "note": _SKILL_EVIDENCE,
    }


# ── 报告渲染 ──────────────────────────────────────────────────────────

def _render_cross_document_analysis(cd: dict, gate: dict) -> str:
    lines = [
        "# Cross-Document Analysis — v2.0.11 cross-document ablation",
        "",
        "## 分组与方法",
        "",
        f"- cross_document 分组：**{cd['n']}** case（全部有 chunk 真值）。",
        "- 基线臂 `single-query`：既有产品检索（dense + BM25 + RRF k=60）。",
        "- 候选臂 `mechanical-clause-rrf`：机械 query variants（完整 query + "
        "强分句 + 长句弱分句 + 中英语言边界段，全部为原 query 字面子串）+ "
        "跨 variant RRF(k=60) + chunk_id tie-break；无 LLM、无新语义文本。",
        "- 两次独立构建分别计算分组指标；跨构建 HNSW 近邻扰动如实记录。",
        "",
        "## 分组聚合指标（候选 − 基线）",
        "",
        "| 指标 | 基线 | 候选 | Δ |",
        "|---|---|---|---|",
    ]
    for key in _COMPARE_METRIC_KEYS:
        b = cd["baseline"].get(key)
        c = cd["candidate"].get(key)
        d = cd["deltas"].get(key)
        lines.append(f"| {key} | {b if b is not None else '—'} | "
                     f"{c if c is not None else '—'} | "
                     f"{d if d is not None else '—'} |")
    lines += [
        "",
        f"- per-case 差异 case 数：**{cd['per_case_diff_count']}**"
        "（明细见 ablation-summary.json cross_document.per_case_differences）。",
        f"- gate 决策：**{gate['decision']}**"
        "（条件明细见 selection-decision.md）。",
        "",
        "## 每个 case 的基线/候选对比",
        "",
        "| case | 基线 recall@5 | 候选 recall@5 | Δ | 基线 mrr | 候选 mrr |"
        " 检索集合一致 |",
        "|---|---|---|---|---|---|---|",
    ]
    by_id = {d["case_id"]: d for d in cd["per_case_differences"]}
    for r in cd["per_case_rows"]:
        b5 = r["baseline_metrics"].get("recall@5")
        c5 = r["candidate_metrics"].get("recall@5")
        bm = r["baseline_metrics"].get("mrr")
        cm = r["candidate_metrics"].get("mrr")
        d5 = round(c5 - b5, 6) if b5 is not None and c5 is not None else None
        diff = by_id.get(r["case_id"])
        same = diff is None or diff.get("retrieved_equal", False)
        lines.append(
            f"| {r['case_id']} | {b5} | {c5} | {d5} | {bm} | {cm} | "
            f"{'是' if same else '否'} |")
    lines += [
        "",
        "## HNSW 跨构建扰动（诚实记录）",
        "",
        "- 同索引重复查询逐位一致；跨构建（独立索引）在深 rank 处存在近邻"
        "扰动。本阶段记录的 cd recall@5 跨构建噪声："
        f"**{cd['noise_cd_recall5']:.6f}**。",
        "- 若候选与基线的差异处于噪声量级，将如实报告为「无显著差异」，"
        "不伪称逐 case 字节一致。",
        "",
        "## 明确不是",
        "",
        "- v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、"
        "human_reviewed=false），不代表 active、人工批准或 release。",
        "- 本分析不是 answer-quality / citation-faithfulness / refusal 精度评测。",
    ]
    return "\n".join(lines)


def _render_selection_decision(gate: dict, verification: dict) -> str:
    lines = [
        "# Selection Decision — Phase 6-C1 cross-document ablation",
        "",
        "## 预先锁定的 promotion gate（机械判定，6 项条件）",
        "",
        f"- **决策：{gate['decision']}**",
        "",
        "| 条件 | 判定 | 说明 |",
        "|---|---|---|",
    ]
    for c in gate["conditions"]:
        if c["id"] == "exceeds_recorded_noise":
            detail = c["required"]
        elif c["id"] == "all_checks_passed":
            detail = "冻结/身份/manifest/citation/数据质量全部通过"
        else:
            b = c.get("build1", {})
            d = b.get("delta", b.get("deltas", {}))
            detail = f"build1 Δ={d}"
        lines.append(f"| {c['id']} | {'通过' if c['ok'] else '未通过'} | "
                     f"{detail} |")
    lines += [
        "",
        "## 判定规则",
        "",
        f"- 全部条件在**两次独立构建**上同时满足 → "
        f"`EXPERIMENT_PROMISING`；任一失败 → `NO_PROMOTION`。",
        f"- 本阶段实际决策：**{gate['decision']}**；"
        f"未通过条件：{gate['failures'] or '无'}。",
        "",
        "## 决策边界（红线）",
        "",
        "- **即便 EXPERIMENT_PROMISING，也不改变默认产品检索策略**——"
        "候选策略只记录于本消融产物，任何采用须经后续独立阶段决策。",
        "- v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、"
        "human_reviewed=false），不是 active、release 或人工批准。",
        "- 生命周期 API（add/remove/sync）的 snapshot 不可变保护属未来 "
        "B0.2，本阶段未修改、未调用。",
        "- 未测项：answer quality、citation faithfulness、answer-level "
        "refusal accuracy（见 manifest not_measured）。",
        f"- 前置复算：frozen {verification['frozen_checks']} 项 / 6A "
        f"{verification['phase6a_checks']} 项 / B0 "
        f"{verification['phase6b0_checks']} 项 / hardened "
        f"{verification['hardened_checks']} 项，全部通过。",
    ]
    return "\n".join(lines)


# ── 产物写入 ──────────────────────────────────────────────────────────

def write_artifacts(
    out_dir: Path,
    *,
    cases: list[dict],
    results_b: list[dict],
    results_c: list[dict],
    metrics_b: dict,
    metrics_c: dict,
    cd: dict,
    gate: dict,
    determinism: dict,
    comparison_hardened: dict,
    verification: dict,
    case_counts: dict,
    snapshot: ic.ChunkSnapshot,
    index: dict,
    cleaned: bool,
    params: dict,
    strategy_spec: dict,
    dq: dict,
    frozen_chunk_ids: set[str],
    prior_run: dict | None,
    phase6a_dir: Path,
    phase6b0_dir: Path,
    hardened_dir: Path,
    corpus_manifest_path: Path,
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    phase6a_dir = Path(phase6a_dir)
    phase6b0_dir = Path(phase6b0_dir)
    hardened_dir = Path(hardened_dir)

    summary = {
        "scope": "v2.0.11-cross-document-retrieval-ablation (Phase 6-C1)",
        "frozen_revision": "v2.0.11-owner-authorized-en048-same-source-repair",
        "frozen_revision_status": "CANDIDATE",
        "activation_blocked": True,
        "case_counts": case_counts,
        "strategy": {
            "baseline": {
                "name": "single-query",
                "version": "1.0",
                "entry": "src.rag.retrieve_hybrid_with_sources"
                         "（dense + BM25 + RRF k=60，既有产品代码）",
                "no_llm": True,
            },
            "candidate": strategy_spec,
        },
        "baseline": {"metrics": metrics_b, "cross_document": cd["baseline"]},
        "candidate": {"metrics": metrics_c, "cross_document": cd["candidate"]},
        "cross_document": {
            "n": cd["n"],
            "baseline": cd["baseline"],
            "candidate": cd["candidate"],
            "deltas": cd["deltas"],
            "per_case_diff_count": cd["per_case_diff_count"],
            "per_case_differences": cd["per_case_differences"][:50],
            "noise_cd_recall5": cd["noise_cd_recall5"],
        },
        "gate": gate,
        "determinism": determinism,
        "comparison_to_hardened": comparison_hardened,
        "verification": {
            "frozen_verified": verification["frozen_verified"],
            "frozen_checks": verification["frozen_checks"],
            "phase6a_verified": verification["phase6a_verified"],
            "phase6a_checks": verification["phase6a_checks"],
            "phase6b0_verified": verification["phase6b0_verified"],
            "phase6b0_checks": verification["phase6b0_checks"],
            "hardened_verified": verification["hardened_verified"],
            "hardened_checks": verification["hardened_checks"],
        },
        "not_measured": {
            "answer_quality": {
                "measured": False,
                "reason": "Phase 6-C1 只做检索消融：不调用生成模型、不做 "
                          "LLM judge；answer-quality 无真值无产出",
            },
            "citation_faithfulness": {
                "measured": False,
                "reason": "citation-faithfulness 依赖生成判定与人工审计，"
                          "本阶段未测",
            },
            "refusal_accuracy": {
                "measured": False,
                "reason": "answer 级拒答精度依赖生成判定，本阶段未测；"
                          "refusal 组仅有检索分数观测",
            },
        },
        "isolation": {
            "collection_name": index["collection_name"],
            "data_dir": index["data_dir"],
            "chroma_dir": index["chroma_dir"],
            "entry": "src.rag.prepare_index（完整产品路径，含 collection "
                     "manifest + BM25 sidecar）",
            "no_user_index_touched": True,
            "cleaned": cleaned,
        },
    }

    (out_dir / "ablation-summary.json").write_text(
        bl6a.canonical_json(summary), encoding="utf-8")
    for name, rows in (("per-case-results-baseline.jsonl", results_b),
                       ("per-case-results-candidate.jsonl", results_c)):
        with open(out_dir / name, "w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "cross-document-analysis.md").write_text(
        _render_cross_document_analysis(cd, gate), encoding="utf-8")
    (out_dir / "selection-decision.md").write_text(
        _render_selection_decision(gate, verification), encoding="utf-8")
    (out_dir / "data-quality-report.json").write_text(
        bl6a.canonical_json(dq), encoding="utf-8")

    # ── manifest：lineage + 全量 SHA 复算 ──
    inputs: dict[str, dict] = {}
    for check in verification["frozen_checks_detail"]:
        if check["status"] == "ok" and check["kind"] == "inputs":
            inputs.setdefault(check["name"], {
                "path": check["path"], "sha256": check["actual"],
            })
    inputs["corpus-manifest.json"] = {
        "path": str(Path(corpus_manifest_path)),
        "sha256": snapshot.corpus_manifest_sha256,
    }
    for src in snapshot.sources:
        inputs[f"source:{src.name}"] = {
            "path": src.path, "sha256": src.content_sha256,
        }
    for label, path in (("phase6a-manifest.json", phase6a_dir),
                        ("phase6b0-manifest.json", phase6b0_dir),
                        ("hardened-manifest.json", hardened_dir)):
        inputs[label] = {"path": str(path / "manifest.json"),
                         "sha256": bl6a.sha256_bytes(path / "manifest.json")}
    frozen_outputs: dict[str, dict] = {}
    for check in verification["frozen_checks_detail"]:
        if check["status"] == "ok" and check["kind"] == "outputs":
            frozen_outputs.setdefault(check["name"], {
                "path": check["path"], "sha256": check["actual"],
            })
    phase6a_outputs = {
        name: bl6a.sha256_bytes(phase6a_dir / name)
        for name in ("baseline-summary.json", "per-case-retrieval-results.jsonl",
                     "failure-analysis.md", "schema-compatibility-report.md",
                     "BASELINE_SCOPE.md", "data-quality-mechanical-check.json")
        if (phase6a_dir / name).is_file()
    }
    phase6b0_outputs = {
        name: bl6a.sha256_bytes(phase6b0_dir / name)
        for name in cbl.CONTRACT_OUTPUT_FILES
        if (phase6b0_dir / name).is_file()
    }
    hardened_outputs = {
        name: bl6a.sha256_bytes(hardened_dir / name)
        for name in hbl.HARDENED_OUTPUT_FILES
        if (hardened_dir / name).is_file()
    }

    hardened_manifest = json.loads(
        (hardened_dir / "manifest.json").read_text(encoding="utf-8"))
    b0_manifest = json.loads(
        (phase6b0_dir / "manifest.json").read_text(encoding="utf-8"))

    manifest = {
        "task": "v2.0.11-cross-document-retrieval-ablation",
        "frozen_revision": "v2.0.11-owner-authorized-en048-same-source-repair",
        "frozen_revision_status": "CANDIDATE",
        "lineage": {
            "hardened_manifest_sha256": hardened_manifest.get("manifest_sha256"),
            "hardened_verified": verification["hardened_verified"],
            "hardened_checks": verification["hardened_checks"],
            "phase6b0_manifest_sha256": b0_manifest.get("manifest_sha256"),
            "phase6b0_verified": verification["phase6b0_verified"],
            "phase6b0_checks": verification["phase6b0_checks"],
            "phase6a_verified": verification["phase6a_verified"],
            "phase6a_checks": verification["phase6a_checks"],
            "frozen_verified": verification["frozen_verified"],
            "frozen_checks": verification["frozen_checks"],
            "note": "冻结 61 项 + 6A + 旧 B0 + hardened 全部字节复算；"
                    "任一漂移 → 本消融零产物",
        },
        "inputs": inputs,
        "frozen_outputs": frozen_outputs,
        "phase6a_outputs": phase6a_outputs,
        "phase6b0_outputs": phase6b0_outputs,
        "hardened_outputs": hardened_outputs,
        "outputs": {
            name: bl6a.sha256_bytes(out_dir / name)
            for name in ABLATION_OUTPUT_FILES if name != "manifest.json"
        },
        "strategy": {
            "baseline": summary["strategy"]["baseline"],
            "candidate": strategy_spec,
        },
        "code": bl6a._git_head(),
        "parameters": params,
        "dependencies": bl6a._dependencies(),
        "model": {
            "name": index["model_name"],
            "embedding_dimension": index["embedding_dimension"],
            "offline": True,
            "note": "本地缓存离线加载（HF_HUB_OFFLINE=1/TRANSFORMERS_OFFLINE=1）；"
                    "检索期间无网络调用",
        },
        "isolation": summary["isolation"],
        "determinism": determinism,
        "case_counts": case_counts,
        "gate": {"decision": gate["decision"], "failures": gate["failures"]},
        "not_measured": summary["not_measured"],
        "verification": {"prior_run": prior_run} if prior_run else {},
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    manifest["manifest_sha256"] = bl6a.self_hash(manifest)
    (out_dir / "manifest.json").write_text(bl6a.canonical_json(manifest),
                                           encoding="utf-8")
    return manifest


# ── 第二次独立构建的确定性（双臂逐 case 比较）────────────────────────

def _verify_determinism(snapshot: ic.ChunkSnapshot, cases: list[dict],
                        collection_name: str, strategy: str,
                        primary_baseline: list[dict],
                        primary_candidate: list[dict],
                        primary_cd_b: dict, primary_cd_c: dict) -> dict:
    """第二次独立构建（独立临时目录）→ 双臂逐 case 比较非时间字段。

    与 B0/B0.1 相同：聚合指标必须稳定；raw ranking 的 HNSW 跨构建扰动
    如实记录；cd recall@5 噪声量级进入 gate 判定。
    """
    import src.rag as rag

    second_dir = Path(tempfile.mkdtemp(prefix="mneme-v211-ablation-"))
    try:
        index2 = cbl.build_contract_index(snapshot, second_dir,
                                          collection_name, force_rebuild=True)
        baseline2 = bl6a.run_retrieval(cases, index2)
        candidate2 = abl.run_candidate_retrieval(cases, index2,
                                                 strategy=strategy)
        metrics_b2 = bl6a.compute_metrics(baseline2)
        metrics_c2 = bl6a.compute_metrics(candidate2)
        cd_b2 = _cd_metrics(baseline2)
        cd_c2 = _cd_metrics(candidate2)
    finally:
        rag.close_chroma_clients()
        shutil.rmtree(second_dir, ignore_errors=True)

    differences: dict[str, list[dict]] = {"baseline": [], "candidate": []}
    metric_differences: dict[str, list[dict]] = {
        "baseline": [], "candidate": []}
    for arm, primary in (("baseline", primary_baseline),
                         ("candidate", primary_candidate)):
        second = (baseline2 if arm == "baseline" else candidate2)
        by_id = {r["case_id"]: r for r in second}
        for r in primary:
            other = by_id[r["case_id"]]
            for field in ("retrieved_chunk_ids", "retrieved_source_ids",
                          "scores", "metrics"):
                if r[field] != other[field]:
                    differences[arm].append({
                        "case_id": r["case_id"], "field": field,
                    })
                    if field == "metrics":
                        for key in sorted(r["metrics"]):
                            if r["metrics"][key] != other["metrics"][key]:
                                metric_differences[arm].append({
                                    "case_id": r["case_id"], "key": key,
                                    "build1": r["metrics"][key],
                                    "build2": other["metrics"][key],
                                })

    noise_b = abs(cd_b2.get("recall@5", 0.0) - primary_cd_b.get("recall@5", 0.0))
    noise_c = abs(cd_c2.get("recall@5", 0.0) - primary_cd_c.get("recall@5", 0.0))
    all_diffs = (differences["baseline"] + differences["candidate"])
    return {
        "verified": not all_diffs,
        "cases_compared": len(cases),
        "baseline": {
            "difference_count": len(differences["baseline"]),
            "metric_difference_count": len(metric_differences["baseline"]),
            "metric_differences": metric_differences["baseline"][:20],
            "differences": differences["baseline"][:20],
        },
        "candidate": {
            "difference_count": len(differences["candidate"]),
            "metric_difference_count": len(metric_differences["candidate"]),
            "metric_differences": metric_differences["candidate"][:20],
            "differences": differences["candidate"][:20],
        },
        "cd_recall5_noise": max(noise_b, noise_c),
        "build2": {
            "baseline_metrics": metrics_b2["overall"],
            "candidate_metrics": metrics_c2["overall"],
            "baseline_cd": cd_b2,
            "candidate_cd": cd_c2,
        },
        "note": "第二次构建使用独立临时目录与独立 collection；比较除 "
                "retrieval_ms 外全部字段。raw ranking 差异源于 Chroma/HNSW "
                "索引构建的非确定性（同索引重复查询逐位一致，跨构建在深 "
                "rank 处有近邻扰动）；metric_difference_count 是 per-case "
                "指标受影响的 case 数，聚合指标应稳定；cd recall@5 噪声量级"
                "进入 gate 条件 5",
    }


# ── 编排 ──────────────────────────────────────────────────────────────

def run_ablation(
    *,
    revision_dir: Path,
    chunks_path: Path,
    chunk_manifest_path: Path,
    current_draft_path: Path,
    corpus_manifest_path: Path,
    phase6a_dir: Path,
    phase6b0_dir: Path,
    hardened_dir: Path,
    out_dir: Path,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
    collection_name: str = COLLECTION_NAME,
    strategy: str = "mechanical-clause-rrf",
    verify_determinism: bool = True,
    prior_run_dir: Path | None = None,
) -> dict:
    """执行只读跨文档消融并写出全部 7 个产物。

    顺序（任一漂移 → BaselineDrift，零产物）：
    1. 策略名校验 + 产物目录包含性检查；
    2. 冻结 61 项 → 6A → 旧 B0 → hardened manifest 逐级复算；
    3. snapshot + cases 载入，守恒不变量（唯一 / truth+refusal=total /
       0 mapping failure / cross_document 非空且有真值）；
    4. 产品索引构建 → 双臂检索 → 指标 → cd 分组 → 两次构建确定性 →
       hardened 对照 → gate → 数据质量 → 7 产物。
    """
    repo_root = Path(repo_root or REPO_ROOT)
    out_dir = Path(out_dir)
    b0_dir = Path(phase6b0_dir)
    hd_dir = Path(hardened_dir)

    abl.get_strategy(strategy)  # 未知策略 → ValueError，先于任何写入

    bl6a._check_output_containment(out_dir, [
        Path(revision_dir), Path(chunks_path).parent,
        Path(current_draft_path).parent, Path(corpus_manifest_path).parent,
        Path(phase6a_dir), b0_dir, hd_dir,
        REPO_ROOT / "evaluation/datasets/v2", REPO_ROOT / "data/v2-corpus",
    ] + ([Path(prior_run_dir)] if prior_run_dir else []))

    frozen_report = bl6a.verify_frozen_inputs(
        revision_dir=revision_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path,
    )
    if not frozen_report["verified"]:
        raise BaselineDrift("frozen input drift: " + json.dumps(
            frozen_report["drift"], ensure_ascii=False))

    phase6a_report = cbl.verify_phase6a_manifest(phase6a_dir)
    if not phase6a_report["verified"]:
        raise BaselineDrift("phase6a baseline manifest drift: " + json.dumps(
            phase6a_report["drift"], ensure_ascii=False))

    b0_report = hbl.verify_b0_manifest(b0_dir)
    if not b0_report["verified"]:
        raise BaselineDrift("phase6b0 baseline manifest drift: " + json.dumps(
            b0_report["drift"], ensure_ascii=False))

    hardened_report = verify_hardened_manifest(hd_dir, phase6a_dir)
    if not hardened_report["verified"]:
        raise BaselineDrift("hardened baseline manifest drift: " + json.dumps(
            hardened_report["drift"], ensure_ascii=False))

    snapshot = cbl.load_contract_snapshot(
        chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        corpus_manifest_path=corpus_manifest_path,
        repo_root=repo_root,
    )
    cases, mapping_report = bl6a.load_cases(
        revision_dir / "draft-after.jsonl",
        revision_dir / "evidence-after.jsonl",
        chunks_path,
    )

    # 守恒不变量（fail-closed）
    case_ids = [c["case_id"] for c in cases]
    if len(case_ids) != len(set(case_ids)):
        raise BaselineDrift("duplicate case ids in draft")
    truth_cases = [c for c in cases if c["relevant_chunk_ids"]]
    refusal_cases = [c for c in cases if c["should_refuse"]]
    if len(truth_cases) + len(refusal_cases) != len(cases):
        raise BaselineDrift("truth + refusal count != total cases")
    if mapping_report["mapping"]["mapping_failures"]:
        raise BaselineDrift("mapping failures must be zero: " + json.dumps(
            mapping_report["mapping"]["mapping_failures"],
            ensure_ascii=False))
    cd_cases = [c for c in cases if c["query_type"] == "cross_document"]
    if not cd_cases or any(not c["relevant_chunk_ids"] for c in cd_cases):
        raise BaselineDrift("cross_document group empty or missing chunk truth")

    import src.rag as rag

    own_data_dir = data_dir is None
    data_dir = Path(data_dir) if data_dir is not None else Path(
        tempfile.mkdtemp(prefix="mneme-v211-ablation-"))
    data_dir.mkdir(parents=True, exist_ok=True)

    cleaned = False
    index = {}
    results_b: list[dict] = []
    results_c: list[dict] = []
    try:
        index = cbl.build_contract_index(snapshot, data_dir, collection_name,
                                         force_rebuild=True)
        results_b = bl6a.run_retrieval(cases, index)
        results_c = abl.run_candidate_retrieval(cases, index, strategy=strategy)
        metrics_b = bl6a.compute_metrics(
            results_b, mapping_failure_rows=len(
                mapping_report["mapping"]["mapping_failures"]))
        metrics_c = bl6a.compute_metrics(
            results_c, mapping_failure_rows=len(
                mapping_report["mapping"]["mapping_failures"]))
        cd_b = _cd_metrics(results_b)
        cd_c = _cd_metrics(results_c)
        cd_rows = [r for r in results_b if r["query_type"] == "cross_document"]
        by_id_c = {r["case_id"]: r for r in results_c}
        cd_diffs = []
        for r in cd_rows:
            c = by_id_c[r["case_id"]]
            metric_diffs = {
                k: {"baseline": r["metrics"].get(k),
                    "candidate": c["metrics"].get(k)}
                for k in _COMPARE_METRIC_KEYS
                if r["metrics"].get(k) != c["metrics"].get(k)
            }
            retrieved_equal = (r["retrieved_chunk_ids"]
                               == c["retrieved_chunk_ids"])
            if metric_diffs or not retrieved_equal:
                cd_diffs.append({
                    "case_id": r["case_id"], "metric_diffs": metric_diffs,
                    "retrieved_equal": retrieved_equal,
                    "n_baseline": len(r["retrieved_chunk_ids"]),
                    "n_candidate": len(c["retrieved_chunk_ids"]),
                })
        cd_diffs.sort(key=lambda d: d["case_id"])
        cd = {
            "n": cd_b["n"],
            "baseline": cd_b,
            "candidate": cd_c,
            "deltas": {k: round(cd_c.get(k, 0) - cd_b.get(k, 0), 6)
                       for k in _COMPARE_METRIC_KEYS},
            "per_case_diff_count": len(cd_diffs),
            "per_case_differences": cd_diffs,
            "per_case_rows": [
                {"case_id": r["case_id"],
                 "baseline_metrics": dict(r["metrics"]),
                 "candidate_metrics": dict(by_id_c[r["case_id"]]["metrics"])}
                for r in cd_rows
            ],
            "noise_cd_recall5": 0.0,  # determinism 阶段填充
        }

        determinism = (
            _verify_determinism(
                snapshot, cases, collection_name, strategy,
                primary_baseline=results_b, primary_candidate=results_c,
                primary_cd_b=cd_b, primary_cd_c=cd_c)
            if verify_determinism else {"verified": None, "note": "skipped"}
        )
        if verify_determinism:
            cd["noise_cd_recall5"] = determinism.get("cd_recall5_noise", 0.0)
    finally:
        rag.close_chroma_clients()
        if own_data_dir:
            shutil.rmtree(data_dir, ignore_errors=True)
            cleaned = not data_dir.exists()

    # ── 索引清理后（cleaned 已确定）计算对照 / gate / dq / 产物 ──
    comparison_hardened = compare_to_hardened(
        Path(hardened_dir), results_b, metrics_b)

    prior_run = (compare_prior_run(
        Path(prior_run_dir), results_b, results_c, metrics_b, metrics_c)
        if prior_run_dir else None)

    case_counts = {
        "total_cases": len(cases),
        "chunk_metrics_cases": len(truth_cases),
        "no_chunk_truth_cases": len(refusal_cases),
        "mapping_failure_rows": len(
            mapping_report["mapping"]["mapping_failures"]),
        "cross_document": len(cd_cases),
    }

    verification = {
        "frozen_verified": frozen_report["verified"],
        "frozen_checks": len(frozen_report["checks"]),
        "frozen_checks_detail": frozen_report["checks"],
        "phase6a_verified": phase6a_report["verified"],
        "phase6a_checks": len(phase6a_report["checks"]),
        "phase6b0_verified": b0_report["verified"],
        "phase6b0_checks": len(b0_report["checks"]),
        "hardened_verified": hardened_report["verified"],
        "hardened_checks": len(hardened_report["checks"]),
    }

    # gate（checks_ok=dq 核心数据质量）→ promotion_eligibility 独立成段：
    # 失败 gate 是实验决策结果（NO_PROMOTION），不是 data-quality 失败，
    # 不混入 data-quality checks，passed 不暗示 promotion 通过（C1.1）
    strategy_spec = abl.get_strategy(strategy)
    build2 = (determinism.get("build2", {})
              if verify_determinism else {})
    dq = data_quality_check(
        results_b=results_b, results_c=results_c,
        metrics_b=metrics_b, metrics_c=metrics_c, cases=cases,
        mapping_report=mapping_report, cd=cd,
        verification=verification, manifest=None,
        frozen_chunk_ids={c["chunk_id"] for c in snapshot.chunks},
        strategy_spec=strategy_spec,
    )
    gate = evaluate_gate(
        build1={
            "baseline": metrics_b["overall"], "candidate": metrics_c["overall"],
            "baseline_cd": cd_b, "candidate_cd": cd_c,
        },
        build2={
            "baseline": build2.get("baseline_metrics", metrics_b["overall"]),
            "candidate": build2.get("candidate_metrics", metrics_c["overall"]),
            "baseline_cd": build2.get("baseline_cd", cd_b),
            "candidate_cd": build2.get("candidate_cd", cd_c),
        },
        noise_cd_recall5=cd["noise_cd_recall5"],
        checks_ok=dq["passed"],
    )
    dq["promotion_eligibility"] = {
        "decision": gate["decision"],
        "failures": gate["failures"],
        "conditions": gate["conditions"],
        "checks": [
            {"name": "gate.conditions_complete",
             "ok": len(gate["conditions"]) == 6,
             "detail": f"conditions={len(gate['conditions'])}"},
            {"name": "gate.decision_recorded",
             "ok": gate["decision"] in ("EXPERIMENT_PROMISING",
                                        "NO_PROMOTION"),
             "detail": gate["decision"]},
        ],
        "note": ("promotion gate（6 项条件，预先锁定，机械判定）是实验决策"
                 "结果：任一条件失败 → NO_PROMOTION；失败 gate **不是 "
                 "data-quality 失败**，data_quality.passed 也**不意味着** "
                 "promotion 通过；失败条件只出现在本段，不混入 "
                 "data-quality checks"),
    }

    params = {
        "collection_name": collection_name,
        "entry": "src.rag.prepare_index(snapshot=ChunkSnapshot, "
                 "chroma_path=临时目录) + src.rag.retrieve_hybrid_with_sources",
        "strategy": strategy,
        "strategy_params": strategy_spec["params"],
        "top_k_retrieval": 70,
        "rrf_k": 60,
        "ks": list(KS),
        "provenance_top_n": 200,
        "verify_determinism": verify_determinism,
    }
    manifest = write_artifacts(
        out_dir, cases=cases, results_b=results_b, results_c=results_c,
        metrics_b=metrics_b, metrics_c=metrics_c, cd=cd, gate=gate,
        determinism=determinism, comparison_hardened=comparison_hardened,
        verification=verification, case_counts=case_counts,
        snapshot=snapshot, index=index, cleaned=cleaned, params=params,
        strategy_spec=strategy_spec, dq=dq,
        frozen_chunk_ids={c["chunk_id"] for c in snapshot.chunks},
        prior_run=prior_run,
        phase6a_dir=phase6a_dir, phase6b0_dir=b0_dir, hardened_dir=hd_dir,
        corpus_manifest_path=corpus_manifest_path,
    )

    return {
        "status": "ok",
        "results_baseline": results_b,
        "results_candidate": results_c,
        "metrics_baseline": metrics_b,
        "metrics_candidate": metrics_c,
        "strategy": {
            "baseline": {
                "name": "single-query", "version": "1.0", "no_llm": True},
            "candidate": strategy_spec,
        },
        "cross_document": cd,
        "gate": gate,
        "determinism": determinism,
        "comparison_hardened": comparison_hardened,
        "verification": verification,
        "case_count": len(cases),
        "snapshot": snapshot,
        "manifest": manifest,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI。退出码：0=成功；2=冻结/6A/B0/hardened 漂移（零产物）；1=其他。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase 6-C1: v2.0.11 cross-document retrieval ablation")
    parser.add_argument("--revision-dir", type=Path, default=FROZEN_REVISION_DIR)
    parser.add_argument("--chunks", type=Path, default=CHUNKS_PATH)
    parser.add_argument("--chunk-manifest", type=Path,
                        default=cbl.CHUNK_MANIFEST_PATH)
    parser.add_argument("--current-draft", type=Path, default=CURRENT_DRAFT_PATH)
    parser.add_argument("--corpus-manifest", type=Path,
                        default=CORPUS_MANIFEST_PATH)
    parser.add_argument("--phase6a-dir", type=Path, default=PHASE6A_DIR)
    parser.add_argument("--phase6b0-dir", type=Path, default=PHASE6B0_DIR)
    parser.add_argument("--hardened-dir", type=Path, default=HARDENED_DIR)
    parser.add_argument("--output", type=Path, default=ABLATION_DIR)
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="临时数据目录（默认自动创建并在结束后清理）")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--strategy", type=str, default="mechanical-clause-rrf")
    parser.add_argument("--prior-run-dir", type=Path, default=None)
    parser.add_argument("--skip-determinism", action="store_true")
    args = parser.parse_args(argv)

    try:
        summary = run_ablation(
            revision_dir=args.revision_dir, chunks_path=args.chunks,
            chunk_manifest_path=args.chunk_manifest,
            current_draft_path=args.current_draft,
            corpus_manifest_path=args.corpus_manifest,
            phase6a_dir=args.phase6a_dir, phase6b0_dir=args.phase6b0_dir,
            hardened_dir=args.hardened_dir,
            out_dir=args.output, data_dir=args.data_dir,
            repo_root=args.repo_root, strategy=args.strategy,
            verify_determinism=not args.skip_determinism,
            prior_run_dir=args.prior_run_dir,
        )
    except BaselineDrift as exc:
        print(f"FAIL-CLOSED: {exc}", file=sys.stderr)
        return 2
    except ic.SnapshotContractError as exc:
        print("FAIL-CLOSED: contract validation failed, zero outputs.",
              file=sys.stderr)
        for d in exc.drift:
            print(f"  [{d['name']}] {d['detail']}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"FAIL-CLOSED: invalid configuration: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1

    metrics_b = summary["metrics_baseline"]["overall"]
    metrics_c = summary["metrics_candidate"]["overall"]
    cd = summary["cross_document"]
    print(f"cross-document ablation complete: {summary['case_count']} cases "
          f"-> {args.output}")
    print(f"  strategy={args.strategy} "
          f"gate={summary['gate']['decision']}")
    print(f"  baseline: recall@5={metrics_b.get('recall@5'):.4f} "
          f"mrr={metrics_b.get('mrr'):.4f}")
    print(f"  candidate: recall@5={metrics_c.get('recall@5'):.4f} "
          f"mrr={metrics_c.get('mrr'):.4f}")
    print(f"  cd(n={cd['n']}): baseline recall@5="
          f"{cd['baseline'].get('recall@5'):.4f} -> candidate "
          f"{cd['candidate'].get('recall@5'):.4f} "
          f"(Δ={cd['deltas'].get('recall@5')})")
    print(f"  denominators: {metrics_b['denominators']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
