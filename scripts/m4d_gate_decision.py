"""M4d 门禁机械裁决脚本（预注册判据，只读产物）。

判据（M4 提案 §三、M4b 批准稿）：
- P1（唯一门禁）：臂2 检索缺口率（可答例中 context∩truth=∅ 占比）≤ 0.50
  ⇒ PASS；否则 FAIL（按 M4 §七归档病理 + owner 重决策）。
- 协变（全量报告不作裁决）：修正率（al1 机械 / M3 式 judge 子集）、拒答
  正确率、误拒率、citation v2 联合分布、token 实耗。

用法::

    python scripts/m4d_gate_decision.py \
        --arm2 results/answer-level/m4c-arm2-2026-09-06 \
        --arm1 results/answer-level/m4c-arm1-2026-09-06 \
        --dataset evaluation/datasets/v2.1.jsonl \
        --out results/answer-level/m4c/decision-report.md

    # --judge-dir（可选）：臂2 judge 子集产物（修正率补全）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

P1_THRESHOLD = 0.50  # M4 §三 锁定；M4b Q-M4b-5 确认维持


def _load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _normalized(ids) -> set[str]:
    from evaluation.generation_runner import _normalize_chunk_id

    return {_normalize_chunk_id(x) for x in (ids or [])}


def _gap_rate(outcomes: list[dict]) -> tuple[int, int, float]:
    """P1 口径：可答例（should_refuse=False 且真值非空）中 context∩truth=∅ 占比。"""
    gap = 0
    n = 0
    for o in outcomes:
        if o.get("should_refuse"):
            continue
        truth = _normalized(o.get("relevant_chunk_ids") or [])
        if not truth:
            continue
        n += 1
        ctx = _normalized(o.get("context_chunk_ids") or [])
        if not (ctx & truth):
            gap += 1
    rate = gap / n if n else float("nan")
    return gap, n, rate


def _refusal_panel(outcomes: list[dict]) -> dict:
    probes = [o for o in outcomes if o.get("should_refuse")]
    answerable = [o for o in outcomes if not o.get("should_refuse")]
    correct = sum(
        1 for o in probes
        if (o.get("citation_metrics") or {}).get("correctly_refused") is True)
    false_ref = sum(
        1 for o in answerable
        if (o.get("citation_metrics") or {}).get("correctly_refused") is False)
    return {
        "probe_n": len(probes),
        "correctly_refused": correct,
        "refusal_precision": round(correct / len(probes), 4) if probes else None,
        "answerable_n": len(answerable),
        "false_refusals": false_ref,
        "false_refusal_rate": round(false_ref / len(answerable), 4) if answerable else None,
    }


def _answer_hit(outcomes: list[dict]) -> dict:
    rates = [
        o["answer_hit"]["answer_hit_rate"] for o in outcomes
        if o.get("answer_hit") and o["answer_hit"].get("answer_hit_rate") is not None
    ]
    # 要点级机械命中（M2 口径：20/174）：hit 要点数 / 全部要点数
    points = sum(
        len(o.get("answer_hit", {}).get("points", o.get("answer_hit", {}).get("details", [])))
        for o in outcomes if o.get("answer_hit")
    )
    return {
        "case_avg": round(sum(rates) / len(rates), 4) if rates else None,
        "point_sum_hint": points,
    }


def _fmt_rate(x: float | None) -> str:
    return f"{x:.4f}" if x is not None else "N/A"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm2", required=True, type=Path)
    parser.add_argument("--arm1", type=Path, default=None)
    parser.add_argument("--dataset", default=Path("evaluation/datasets/v2.1.jsonl"))
    parser.add_argument("--judge-dir", type=Path, default=None,
                        help="臂2 judge 子集（M3 协议）密封目录")
    parser.add_argument("--out", default=Path("results/answer-level/m4c/decision-report.md"))
    args = parser.parse_args(argv)

    arm2 = _load_jsonl(args.arm2 / "outcomes.jsonl") if (args.arm2 / "outcomes.jsonl").exists() else []
    arm1 = (_load_jsonl(args.arm1 / "outcomes.jsonl")
            if args.arm1 and (args.arm1 / "outcomes.jsonl").exists() else [])

    gap2, n2, rate2 = _gap_rate(arm2)
    verdict = "PASS" if rate2 <= P1_THRESHOLD else "FAIL"
    lines = [
        "# M4d 门禁机械裁决报告",
        "",
        f"- 日期：2026-09-06",
        f"- 预注册判据：P1 检索缺口率 ≤ {P1_THRESHOLD}（M4 §三锁定，Q-M4b-5 维持）",
        f"- 臂2 产物：`{args.arm2}`（case_count={len(arm2)}）",
    ]
    if arm1:
        gap1, n1, rate1 = _gap_rate(arm1)
        lines += [f"- 臂1 产物：`{args.arm1}`（case_count={len(arm1)}）"]
    else:
        gap1 = n1 = rate1 = None

    lines += [
        "",
        "## 1. P1 门禁（机械）",
        "",
        f"- 臂2 缺口率：**{gap2}/{n2} = {_fmt_rate(rate2)}** → 判据 ≤ 0.50 ⇒ **{verdict}**",
    ]
    if rate1 is not None:
        lines += [f"- 臂1 缺口率：{gap1}/{n1} = {_fmt_rate(rate1)}（V1 阈值单变量增量）"]

    lines += [
        "",
        "## 2. 协变指标（全量报告，不作裁决）",
        "",
        "| 指标 | 臂0(历史 M2) | 臂1 | 臂2 |",
        "| --- | ---: | ---: | ---: |",
    ]
    arm_stats: dict[str, dict] = {}
    for arm_name, outcomes in [("臂1", arm1), ("臂2", arm2)]:
        if not outcomes:
            continue
        rp = _refusal_panel(outcomes)
        ah = _answer_hit(outcomes)
        tok_p = sum(o.get("prompt_tokens") or 0 for o in outcomes)
        tok_c = sum(o.get("completion_tokens") or 0 for o in outcomes)
        c = [o.get("citation_metrics") or {} for o in outcomes]
        prec = sum(x.get("citation_precision", 0.0) for x in c) / len(c)
        recall = sum(x.get("citation_recall", 0.0) for x in c) / len(c)
        arm_stats[arm_name] = {
            "refusal_precision": rp["refusal_precision"],
            "false_refusal_rate": rp["false_refusal_rate"],
            "answer_hit": ah["case_avg"],
            "tokens": tok_p + tok_c,
            "citation_precision": prec,
            "citation_recall": recall,
        }
        print(f"[{arm_name}] 拒答正确率={_fmt_rate(rp['refusal_precision'])} "
              f"误拒率={_fmt_rate(rp['false_refusal_rate'])} "
              f"answer_hit(例均)={_fmt_rate(ah['case_avg'])} "
              f"token={tok_p + tok_c} 引用recall={prec:.4f}/{recall:.4f}")

    for label, key in [("拒答正确率", "refusal_precision"),
                       ("误拒率", "false_refusal_rate"),
                       ("answer_hit(例均)", "answer_hit"),
                       ("token 合计", "tokens"),
                       ("citation precision", "citation_precision"),
                       ("citation recall", "citation_recall")]:
        row = [f"| {label} |"]
        for arm_name in ("臂0(历史 M2)", "臂1", "臂2"):
            st = arm_stats.get(arm_name)
            if st is None:
                value = "—" if label != "token 合计" else "—"
            elif label == "token 合计":
                value = f"{st['tokens']:,}"
            else:
                value = _fmt_rate(st[key])
            row.append(f" {value} |")
        lines.append("".join(row))

    lines += [
        "",
        "## 3. 判定与下步",
        "",
        f"- **{verdict}**：按 M4 §七；FAIL 时归档病理、不回退判据、由 owner 重决策。",
        "",
        "（本报告为机械裁决输出；全部数字可由产物复算。）",
    ]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[m4d] wrote -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
