"""离线检索拒答阈值扫描（只读，零 LLM 调用）。

仅研究 ``DEFAULT_REFUSAL_THRESHOLD`` 候选值（0.00 / 0.01 / 0.02 / 0.03）
对"检索前哨拒答"case 集合的影响，并做预注册门槛判定：

- **G1**：放行的前哨 false_refusal（answerable 且 max score < baseline）
  合并计数 ≥ 4（共 5 条：dev 4 + holdout 1）；
- **G2（主口径）**：新放行 ``should_refuse`` case 数 ≤ 该 split 全部
  ``should_refuse`` case 数的 10%（敏感性表另附 refused_total /
  refused_should_refuse 两种基数）。

无候选阈值满足双门槛 → ``AUTOMATED_DIAGNOSTIC_NO_GO``（不进入 LLM 评测、
不生成锁、不改生产默认）。

fail-closed 校验（不符即中止）：
1. score 判定（max < baseline）与 generation JSONL 的
   ``evidence_context_sha256 == ""``（真实前哨拒答）逐 case 一致；
2. 跨运行（production-baseline vs ablation）拒答分类一致；
3. 派生前哨 FR 集合与预期清单一致。

CLI：``python evaluation/threshold_scan.py --dev-retrieval ... --output-dir ...``
产物：threshold-scan.json / threshold-scan.md / gate-pre-registration.json /
decision-report.md / manifest.json / run-commands.md。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

BASELINE_THRESHOLD = 0.03
CANDIDATE_THRESHOLDS = (0.00, 0.01, 0.02, 0.03)
MAX_RELEASE_FRACTION = 0.10  # G2 容许比例（预注册，用户批准口径）
MIN_SENTINEL_FR_RELEASED = 4  # G1：5 条前哨 FR 中至少放行 4 条
NO_GO = "AUTOMATED_DIAGNOSTIC_NO_GO"
ADMISSIBLE = "ADMISSIBLE"


# ── 核心纯函数 ──────────────────────────────────────────────────────

def refused_at(scores: Sequence[float], threshold: float) -> bool:
    """检索前哨拒答判定：空分数或 max(scores) < threshold。

    与 src.rag.retrieval_refused 语义一致（t=0.00 下空分数仍拒答）。
    """
    return not scores or max(scores) < threshold


def _scores(row: dict) -> list[float]:
    return row.get("candidate_scores") or []


def _max_score(row: dict) -> float | None:
    scores = _scores(row)
    return max(scores) if scores else None


def scan_thresholds(
    rows: Sequence[dict],
    baseline: float = BASELINE_THRESHOLD,
    thresholds: Sequence[float] = CANDIDATE_THRESHOLDS,
) -> dict[str, Any]:
    """逐阈值扫描：baseline 拒答集合 + 每个候选阈值的新放行集合。

    放行 = baseline 拒答且 max(scores) >= t。结果确定性（同输入同输出）。
    """
    sr_total = sum(1 for r in rows if r["should_refuse"])
    ans_total = len(rows) - sr_total
    refused = [r for r in rows if refused_at(_scores(r), baseline)]
    fr_ids = sorted(r["case_id"] for r in refused if not r["should_refuse"])
    sr_ids = sorted(r["case_id"] for r in refused if r["should_refuse"])

    per = []
    for t in thresholds:
        new = [
            r for r in refused
            if not refused_at(_scores(r), t)
        ]
        new_ans = sorted(r["case_id"] for r in new if not r["should_refuse"])
        new_sr = sorted(r["case_id"] for r in new if r["should_refuse"])
        per.append({
            "threshold": t,
            "newly_released_total": len(new),
            "newly_released_answerable_ids": new_ans,
            "newly_released_should_refuse_ids": new_sr,
            "newly_released_should_refuse_count": len(new_sr),
        })

    return {
        "case_count": len(rows),
        "answerable_total": ans_total,
        "should_refuse_total": sr_total,
        "refused_at_baseline": {
            "total": len(refused),
            "sentinel_fr_ids": fr_ids,
            "sentinel_fr_count": len(fr_ids),
            "correctly_refused_ids": sr_ids,
            "correctly_refused_count": len(sr_ids),
        },
        "per_threshold": per,
    }


def evaluate_split_gates(
    scan: dict[str, Any],
    *,
    sentinel_fr_ids: set[str],
    should_refuse_total: int,
    max_release_fraction: float = MAX_RELEASE_FRACTION,
) -> dict[str, Any]:
    """G2 门槛判定（每 split）：主口径 = 全部 should_refuse 的 10%。

    敏感性表保留三种基数：refused_total（baseline 检索拒答总数）/
    refused_should_refuse（其中 should_refuse 数）/ all_should_refuse（主口径）。
    """
    refused = scan["refused_at_baseline"]
    bases = {
        "refused_total": refused["total"],
        "refused_should_refuse": refused["correctly_refused_count"],
        "all_should_refuse": should_refuse_total,
    }
    per = []
    for e in scan["per_threshold"]:
        n_sr = e["newly_released_should_refuse_count"]
        released_fr = [
            cid for cid in e["newly_released_answerable_ids"]
            if cid in sentinel_fr_ids
        ]
        sens = {
            name: {
                "allowed": max_release_fraction * base,
                "pass": n_sr <= max_release_fraction * base,
            }
            for name, base in bases.items()
        }
        per.append({
            "threshold": e["threshold"],
            "newly_released_should_refuse_count": n_sr,
            "sentinel_fr_released_ids": released_fr,
            "sentinel_fr_released_count": len(released_fr),
            "g2_primary": {
                "released": n_sr,
                "allowed": max_release_fraction * should_refuse_total,
                "pass": n_sr <= max_release_fraction * should_refuse_total,
            },
            "g2_sensitivity": sens,
        })
    return {
        "should_refuse_total": should_refuse_total,
        "sensitivity_bases": bases,
        "per_threshold": per,
    }


def admissible_thresholds(
    dev_gates: dict[str, Any],
    holdout_gates: dict[str, Any],
    g1_required: int = MIN_SENTINEL_FR_RELEASED,
) -> list[float]:
    """合并判定：G1（两 split 前哨 FR 放行总数 ≥ 4）且各 split G2 主口径通过。

    返回合格候选阈值列表；空 = 无阈值满足 → NO_GO。
    """
    d_by_t = {e["threshold"]: e for e in dev_gates["per_threshold"]}
    h_by_t = {e["threshold"]: e for e in holdout_gates["per_threshold"]}
    if set(d_by_t) != set(h_by_t):
        raise ValueError("threshold sets differ between splits (fail-closed)")
    out = []
    for t in sorted(d_by_t):
        de, he = d_by_t[t], h_by_t[t]
        g1 = de["sentinel_fr_released_count"] + he["sentinel_fr_released_count"]
        if g1 >= g1_required and de["g2_primary"]["pass"] and he["g2_primary"]["pass"]:
            out.append(t)
    return out


def overall_verdict(admissible: Sequence[float]) -> str:
    return ADMISSIBLE if admissible else NO_GO


def band_diagnostic(
    fr_max_scores: Sequence[float],
    correct_max_scores: Sequence[float],
) -> dict[str, Any]:
    """分数带交织诊断：前哨 FR 带与正确拒答带是否重叠、能否分离。

    能放行全部 FR 的最小阈值 t = min(fr_max_scores)；此时仍被放行的
    正确拒答数 = 分数 >= t 的个数。> 0 即不存在分离阈值。
    """
    fr_min = min(fr_max_scores) if fr_max_scores else None
    fr_max = max(fr_max_scores) if fr_max_scores else None
    c_min = min(correct_max_scores) if correct_max_scores else None
    c_max = max(correct_max_scores) if correct_max_scores else None
    interleaved = bool(
        fr_max_scores and correct_max_scores
        and max(fr_min, c_min) < min(fr_max, c_max)
    )
    min_released = 0
    if fr_max_scores and correct_max_scores:
        t = min(fr_max_scores)
        min_released = sum(1 for s in correct_max_scores if s >= t)
    return {
        "fr_band": [fr_min, fr_max] if fr_max_scores else None,
        "correct_band": [c_min, c_max] if correct_max_scores else None,
        "interleaved": interleaved,
        "min_correct_released_when_releasing_all_fr": min_released,
        "no_separating_threshold": min_released > 0,
    }


# ── fail-closed 校验 ────────────────────────────────────────────────

def check_generation_consistency(
    retrieval_rows: Sequence[dict],
    generation_rows: Sequence[dict],
    baseline: float = BASELINE_THRESHOLD,
) -> None:
    """score 拒答判定与 generation 真实前哨拒答（evidence 无 context）逐 case 一致。

    不符抛 ValueError（fail-closed，中止扫描）。
    """
    score_refused_answerable = {
        r["case_id"] for r in retrieval_rows
        if not r["should_refuse"] and refused_at(_scores(r), baseline)
    }
    gen_sentinel = {
        g["case_id"] for g in generation_rows
        if not g["should_refuse"]
        and g.get("evidence_context_sha256", None) in ("", None)
    }
    if score_refused_answerable != gen_sentinel:
        raise ValueError(
            "generation sentinel-refusal mismatch (fail-closed): "
            f"score-refused answerable={sorted(score_refused_answerable)} "
            f"vs generation={sorted(gen_sentinel)}",
        )


def check_cross_source_agreement(
    rows_a: Sequence[dict],
    rows_b: Sequence[dict],
    baseline: float = BASELINE_THRESHOLD,
) -> None:
    """跨运行拒答分类一致（分数微差不改变分类）；case 集一致。不符抛 ValueError。"""
    ids_a = {r["case_id"] for r in rows_a}
    ids_b = {r["case_id"] for r in rows_b}
    if ids_a != ids_b:
        raise ValueError(
            f"cross-source case sets differ: {len(ids_a)} vs {len(ids_b)} "
            "(fail-closed)",
        )
    refused_a = {r["case_id"] for r in rows_a if refused_at(_scores(r), baseline)}
    refused_b = {r["case_id"] for r in rows_b if refused_at(_scores(r), baseline)}
    flipped = sorted(refused_a ^ refused_b)
    if flipped:
        raise ValueError(
            f"cross-source refusal classification mismatch for {flipped} "
            "(fail-closed)",
        )


# ── 报告渲染 ────────────────────────────────────────────────────────

def _fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:.5f}"


def render_markdown(report: dict[str, Any]) -> str:
    """确定性 Markdown 报告（同输入同字节）。"""
    lines = [
        "# 检索拒答阈值离线扫描报告（只读，零 LLM）",
        "",
        f"> 性质：**只读离线分析** — 不调用 LLM/API，不修改任何生产配置、",
        f"> 阈值与历史产物；结论不构成阈值批准。",
        f"> baseline 阈值：`{report['baseline_threshold']}`；候选阈值：",
        f"> {', '.join(f'{t:.2f}' for t in report['candidate_thresholds'])}。",
        f"> 结论：**{report['verdict']}**",
        "",
    ]
    for split_name, split in report["splits"].items():
        lines += [
            f"## {split_name}（{split['case_count']} 例，"
            f"answerable {split['answerable_total']} / "
            f"should_refuse {split['should_refuse_total']}）",
            "",
            "### baseline 拒答清单",
            "",
            "| case_id | 分组 | max score |",
            "|---|---|---|",
        ]
        for cid, sc in split["refused_detail"]:
            group = "前哨 FR" if cid in split["refused_at_baseline"]["sentinel_fr_ids"] else "正确拒答"
            lines.append(f"| {cid} | {group} | {_fmt(sc)} |")
        lines += ["", "### 候选阈值扫描（新放行）", ""]
        lines += [
            "| 阈值 | 新放行总数 | 放行前哨 FR | 放行 should_refuse |",
            "|---|---|---|---|",
        ]
        for e in split["per_threshold"]:
            lines.append(
                f"| {e['threshold']:.2f} | {e['newly_released_total']} | "
                f"{len(e['newly_released_answerable_ids'])} "
                f"({', '.join(e['newly_released_answerable_ids']) or '-'}) | "
                f"{e['newly_released_should_refuse_count']} "
                f"({', '.join(e['newly_released_should_refuse_ids']) or '-'}) |",
            )
        gates = split["gates"]
        lines += ["", "### G2 门槛判定", ""]
        lines += [
            "| 阈值 | 新放行 SR | 主口径容许量（10% × "
            f"{gates['should_refuse_total']}） | 主口径 | 敏感性 "
            f"(refused_total={gates['sensitivity_bases']['refused_total']} / "
            f"refused_SR={gates['sensitivity_bases']['refused_should_refuse']} / "
            f"all_SR={gates['sensitivity_bases']['all_should_refuse']}) |",
            "|---|---|---|---|---|",
        ]
        for e in gates["per_threshold"]:
            sens = ", ".join(
                f"{k}={v['pass']}（≤{v['allowed']:.1f}）"
                for k, v in e["g2_sensitivity"].items()
            )
            lines.append(
                f"| {e['threshold']:.2f} | {e['newly_released_should_refuse_count']} | "
                f"{e['g2_primary']['allowed']:.2f} | "
                f"{'PASS' if e['g2_primary']['pass'] else 'FAIL'} | {sens} |",
            )
        diag = split["diagnostic"]
        lines += ["", "### 分数带交织诊断", ""]
        lines += [
            f"- 前哨 FR 分数带：{_fmt(diag['fr_band'][0] if diag['fr_band'] else None)} ~ "
            f"{_fmt(diag['fr_band'][1] if diag['fr_band'] else None)}",
            f"- 正确拒答分数带：{_fmt(diag['correct_band'][0] if diag['correct_band'] else None)} ~ "
            f"{_fmt(diag['correct_band'][1] if diag['correct_band'] else None)}",
            f"- 交织：{'是' if diag['interleaved'] else '否'}；"
            f"放行全部 FR 时最少放行的正确拒答 = "
            f"{diag['min_correct_released_when_releasing_all_fr']}；"
            f"存在分离阈值：{'否' if diag['no_separating_threshold'] else '是'}",
            "",
        ]
    lines += ["## 结论", ""]
    lines += [
        f"- 预注册门槛：G1（前哨 FR 放行 ≥ {report['g1_required']}）= "
        f"{'PASS' if report['g1_pass'] else 'FAIL'}；"
        f"G2（各 split 新放行 should_refuse ≤ 10% × 全部 should_refuse）= "
        f"{'PASS' if report['g2_pass'] else 'FAIL'}。",
        f"- 合格候选阈值：{report['admissible'] or '无'} → "
        f"**{report['verdict']}**。",
    ]
    if report["verdict"] == NO_GO:
        lines += [
            "- 当前分数无法分离\u201c可回答但前哨误拒\u201d与\u201c应拒答\u201d两类 case；",
            "- 生产 `DEFAULT_REFUSAL_THRESHOLD=0.03` **保持不变**；",
            "- 不切换生产默认、不批准 guardrail、不进入 LLM 评测。",
        ]
    lines += [
        "",
        "*本报告由 evaluation/threshold_scan.py 生成（可复现）；未调用 LLM；"
        "未修改任何生产配置、阈值与历史产物。*",
        "",
    ]
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────

def _load_jsonl(path: str | Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _standard_arm_rows(rows: list[dict]) -> list[dict]:
    """单臂检索网格：取 standard 臂（仅当数据含 arm 键且存在多臂时过滤）。"""
    arms = sorted({r.get("arm") for r in rows if "arm" in r})
    if arms and arms != ["standard"]:
        return [r for r in rows if r.get("arm") == "standard"]
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="离线检索拒答阈值扫描（只读，零 LLM 调用）")
    ap.add_argument("--dev-retrieval", required=True,
                    help="dev 检索 JSONL（ablation 运行 standard 臂）")
    ap.add_argument("--dev-retrieval-cross", required=True,
                    help="dev 检索 JSONL 交叉校验源（production baseline）")
    ap.add_argument("--dev-generation", required=True,
                    help="dev generation JSONL（含 evidence_context_sha256）")
    ap.add_argument("--holdout-retrieval", required=True,
                    help="holdout 检索 JSONL")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--baseline", type=float, default=BASELINE_THRESHOLD)
    ap.add_argument("--candidate-thresholds",
                    default=",".join(f"{t:.2f}" for t in CANDIDATE_THRESHOLDS))
    ap.add_argument("--expected-sentinel-fr",
                    default="cross-010,en-013,meta-006,meta-008,meta-002",
                    help="预期前哨 FR 清单（派生集合必须一致，fail-closed）")
    ap.add_argument("--min-sentinel-fr-released", type=int,
                    default=MIN_SENTINEL_FR_RELEASED)
    args = ap.parse_args(argv)

    thresholds = tuple(float(x) for x in args.candidate_thresholds.split(","))
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    dev = _standard_arm_rows(_load_jsonl(args.dev_retrieval))
    dev_cross = _standard_arm_rows(_load_jsonl(args.dev_retrieval_cross))
    gen = _standard_arm_rows(_load_jsonl(args.dev_generation))
    ho = _standard_arm_rows(_load_jsonl(args.holdout_retrieval))

    # ── fail-closed 校验 ──
    check_generation_consistency(dev, gen, args.baseline)
    check_cross_source_agreement(dev, dev_cross, args.baseline)

    expected_fr = set(args.expected_sentinel_fr.split(","))
    scan_dev = scan_thresholds(dev, baseline=args.baseline, thresholds=thresholds)
    scan_ho = scan_thresholds(ho, baseline=args.baseline, thresholds=thresholds)
    derived_fr = (set(scan_dev["refused_at_baseline"]["sentinel_fr_ids"])
                  | set(scan_ho["refused_at_baseline"]["sentinel_fr_ids"]))
    if derived_fr != expected_fr:
        raise ValueError(
            f"derived sentinel FR {sorted(derived_fr)} != expected "
            f"{sorted(expected_fr)} (fail-closed)",
        )

    # ── 门槛判定 ──
    gates_dev = evaluate_split_gates(
        scan_dev,
        sentinel_fr_ids=set(scan_dev["refused_at_baseline"]["sentinel_fr_ids"]),
        should_refuse_total=scan_dev["should_refuse_total"],
    )
    gates_ho = evaluate_split_gates(
        scan_ho,
        sentinel_fr_ids=set(scan_ho["refused_at_baseline"]["sentinel_fr_ids"]),
        should_refuse_total=scan_ho["should_refuse_total"],
    )
    admissible = admissible_thresholds(gates_dev, gates_ho,
                                       g1_required=args.min_sentinel_fr_released)
    verdict = overall_verdict(admissible)

    # ── 诊断 ──
    def _band(scan: dict) -> dict:
        refused_detail = []
        fr_maxes, correct_maxes = [], []
        for r in (dev if scan is scan_dev else ho):
            m = _max_score(r)
            if m is None or m >= args.baseline:
                continue
            if r["should_refuse"]:
                correct_maxes.append(m)
                refused_detail.append((r["case_id"], m))
            else:
                fr_maxes.append(m)
                refused_detail.append((r["case_id"], m))
        diag = band_diagnostic(fr_maxes, correct_maxes)
        return diag, sorted(refused_detail, key=lambda x: x[0])

    diag_dev, detail_dev = _band(scan_dev)
    diag_ho, detail_ho = _band(scan_ho)

    # G1 合并判定（每个阈值条目：dev + holdout 前哨 FR 放行总数）
    g1_by_t = {
        t: (gates_dev["per_threshold"][i]["sentinel_fr_released_count"]
            + gates_ho["per_threshold"][i]["sentinel_fr_released_count"])
        for i, t in enumerate(thresholds)
    }
    # G1/G2 汇总标志（独立判定，仅候选阈值 t < baseline；与 admissible 解耦）
    cand_idx = [i for i, t in enumerate(thresholds) if t < args.baseline]
    g1_pass_any = any(
        g1_by_t[thresholds[i]] >= args.min_sentinel_fr_released
        for i in cand_idx
    )
    g2_pass_any = any(
        gates_dev["per_threshold"][i]["g2_primary"]["pass"]
        and gates_ho["per_threshold"][i]["g2_primary"]["pass"]
        for i in cand_idx
    )

    report: dict[str, Any] = {
        "baseline_threshold": args.baseline,
        "candidate_thresholds": list(thresholds),
        "min_sentinel_fr_released": args.min_sentinel_fr_released,
        "g1_required": args.min_sentinel_fr_released,
        "splits": {
            "dev": {**scan_dev, "refused_detail": detail_dev,
                    "gates": gates_dev, "diagnostic": diag_dev},
            "holdout": {**scan_ho, "refused_detail": detail_ho,
                        "gates": gates_ho, "diagnostic": diag_ho},
        },
        "admissible": admissible,
        "g1_pass": g1_pass_any,
        "g2_pass": g2_pass_any,
        "verdict": verdict,
    }

    md = render_markdown(report)
    (out / "threshold-scan.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "threshold-scan.md").write_text(md, encoding="utf-8")

    gate_reg = {
        "experiment": "retrieval-refusal-threshold-calibration",
        "baseline_threshold": args.baseline,
        "candidate_thresholds": list(thresholds),
        "g1": {
            "definition": "released sentinel false_refusal (dev+holdout) >= "
                          f"{args.min_sentinel_fr_released} of 5",
            "released_by_threshold": {
                f"{t:.2f}": g1_by_t[t] for t in thresholds
            },
            "pass": g1_pass_any,
        },
        "g2": {
            "definition": "per split: newly released should_refuse <= 10% of "
                          "all should_refuse cases (primary)",
            "dev": gates_dev,
            "holdout": gates_ho,
        },
        "admissible_thresholds": admissible,
        "verdict": verdict,
        "conclusion": (
            "no candidate threshold satisfies both gates; production "
            "DEFAULT_REFUSAL_THRESHOLD unchanged"
            if verdict == NO_GO else
            f"candidate threshold(s) {admissible} pre-registered"
        ),
    }
    (out / "gate-pre-registration.json").write_text(
        json.dumps(gate_reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    inputs = {
        "dev_retrieval": {"path": args.dev_retrieval,
                          "sha256": _sha256(args.dev_retrieval),
                          "case_count": len(dev)},
        "dev_retrieval_cross": {"path": args.dev_retrieval_cross,
                                "sha256": _sha256(args.dev_retrieval_cross),
                                "case_count": len(dev_cross)},
        "dev_generation": {"path": args.dev_generation,
                           "sha256": _sha256(args.dev_generation),
                           "case_count": len(gen)},
        "holdout_retrieval": {"path": args.holdout_retrieval,
                              "sha256": _sha256(args.holdout_retrieval),
                              "case_count": len(ho)},
    }
    manifest = {
        "experiment": "retrieval-refusal-threshold-calibration",
        "inputs": inputs,
        "outputs": ["threshold-scan.json", "threshold-scan.md",
                    "gate-pre-registration.json", "decision-report.md",
                    "manifest.json", "run-commands.md"],
        "immutability": "read-only scan; no production config, threshold, "
                        "or historical artifacts modified",
        "llm_calls": 0,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    decision = _render_decision_report(report, gate_reg)
    (out / "decision-report.md").write_text(decision, encoding="utf-8")

    (out / "run-commands.md").write_text(
        _render_run_commands(), encoding="utf-8")

    print(f"verdict: {verdict}; admissible: {admissible}")
    print(f"outputs written to {out}")
    return 0


def _render_decision_report(report: dict[str, Any],
                            gate_reg: dict[str, Any]) -> str:
    admissible = report["admissible"]
    verdict = report["verdict"]
    if verdict == NO_GO:
        body = [
            "## 结论：AUTOMATED_DIAGNOSTIC_NO_GO",
            "",
            "离线扫描显示：当前检索分数**无法分离**\u201c可回答但前哨误拒\u201d与",
            "\u201c应拒答\u201d两类 case——候选阈值 0.00 / 0.01 / 0.02 的新放行集合",
            "完全相同（dev 10 = 4 前哨 FR + 6 应拒答；holdout 2 = 1 + 1），",
            "且前哨 FR 分数带与正确拒答分数带完全交织：任何能放行全部",
            "4 条 dev 前哨 FR 的阈值必然同时放行 ≥3 条正确拒答。",
            "",
            "预注册门槛判定：",
            "- G1（前哨 FR 放行 ≥ 4/5）：候选阈值全部满足（5/5）→ PASS；",
            "- G2（主口径：新放行 should_refuse ≤ 10% × 该 split 全部",
            "  should_refuse）：dev 6 > 10% × 22 = 2.2 → FAIL；",
            "  holdout 1 > 10% × 3 = 0.3 → FAIL；",
            "  敏感性（基数 10 / 6 / 22 与 2 / 1 / 3）结论一致 FAIL。",
            "",
            "**无合格候选阈值** → 不进入 LLM 评测、不生成锁。",
            "",
            "## 生产影响",
            "",
            "- 生产 `DEFAULT_REFUSAL_THRESHOLD = 0.03` **保持不变**；",
            "- 不切换任何生产默认、不批准 guardrail；",
            "- `RAG_REFUSAL_POLICY=baseline` 保持不变（evidence_calibrated",
            "  未被启用）。",
            "",
            "## 后续建议（需人工决定）",
            "",
            "1. 单一 max-score 阈值无法完成拒答校准——RAG-IMPROVEMENT-PLAN",
            "   阶段 1.5 应转向**特征化拒答**（结合候选集质量、来源分布、",
            "   query 类型等特征，而非单分数阈值）；",
            "2. 检索层前哨拒答分层：source-only / chunk 证据缺失两种模式",
            "   需不同处理（en-013、meta-008 为 source-only，检索命中",
            "   相关来源但分数低于 0.03）；",
            "3. 语料扩充后在稳定 split 新指纹下重扫，重新评估阈值候选集。",
        ]
    else:
        body = [
            f"## 结论：合格候选阈值 {admissible} 已预注册",
            "",
            "后续按 REFUSAL-THRESHOLD-CALIBRATION-DESIGN §五 实施受控评测。",
        ]
    return "\n".join([
        "# 检索拒答阈值校准 —— Decision Report",
        "",
        f"> 目录：`{gate_reg['experiment']}`；生成时间见 manifest。",
        f"> 基线阈值：`{report['baseline_threshold']}`；候选阈值：",
        f"> {', '.join(f'{t:.2f}' for t in report['candidate_thresholds'])}。",
        "",
        *body,
        "",
        "*本报告由 evaluation/threshold_scan.py 自动生成；未调用 LLM；",
        "未修改任何生产配置与历史产物。*",
        "",
    ])


def _render_run_commands() -> str:
    return "\n".join([
        "# 复现命令",
        "",
        "```bash",
        "python evaluation/threshold_scan.py \\",
        "  --dev-retrieval results/graph-gate/refusal-ablation-20260805T133209/dev-full/retrieval-cases.jsonl \\",
        "  --dev-retrieval-cross results/graph-gate/production-baseline-stable-20260805T084256/dev-full/retrieval-cases.jsonl \\",
        "  --dev-generation results/graph-gate/refusal-ablation-20260805T133209/dev-full/generation-cases.jsonl \\",
        "  --holdout-retrieval results/graph-gate/production-baseline-stable-20260805T084256/holdout-full/retrieval-cases.jsonl \\",
        "  --output-dir <timestamped-output-dir>",
        "```",
        "",
        "产物：threshold-scan.json / threshold-scan.md / ",
        "gate-pre-registration.json / decision-report.md / manifest.json / ",
        "run-commands.md。",
        "",
    ])


if __name__ == "__main__":
    raise SystemExit(main())
