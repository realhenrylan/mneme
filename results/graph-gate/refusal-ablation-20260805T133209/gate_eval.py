"""拒答策略消融 dev 门槛评估（预注册门槛 fail-closed 判定）。

门槛（预注册于 REFUSAL-POLICY-ABLATION-DESIGN-2026-08-05.md §五）：
G1 dev false_refusal 至少减少 4 例（B ≤ A−4）；
G2 false_answer 不恶化（B rate ≤ A rate）；
G3 citation_v2 micro ≥0.95 且 fabricated=0、retrieved_not_in_context=0；
G4 answer_rate 不低于 baseline（B ≥ A）；
G5 answer_point_coverage 不显著下降（paired delta 95% CI 上界 < −0.05）；
G6 holdout 方向一致（仅 dev 达标后评估）。

任一不达标 → AUTOMATED_DIAGNOSTIC_NO_GO（不跑 holdout full）。
全部数字由 generation JSONL 独立复算，不手填。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
GEN = OUT / "dev-full/generation-cases.jsonl"


def load_rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in open(path, encoding="utf-8")
            if l.strip()]


rows = load_rows(GEN)
by_arm = {}
for r in rows:
    by_arm.setdefault(r["arm"], []).append(r)
a = by_arm["standard"]
b = by_arm["standard-calibrated"]


def summarize(rs):
    answerable = [r for r in rs if r["should_refuse"] is False
                  and r["error"] is None]
    refusals = [r for r in rs if r["should_refuse"] is True]
    fr = sum(1 for r in answerable if r["correctly_refused"] is False)
    fa = sum(1 for r in refusals if r["correctly_refused"] is False)
    total_ids = sum(sum(r["citation_status_counts"].values())
                    for r in answerable)
    sup_ids = sum(
        r["citation_status_counts"].get("supported_chunk", 0)
        + r["citation_status_counts"].get("supported_source", 0)
        for r in answerable)
    fab = sum(r["fabricated_citation_count"] for r in answerable)
    nin = sum(r["retrieved_not_in_context_count"] for r in answerable)
    no_cite = sum(1 for r in answerable if not r["citation_status_counts"])
    cov = (sum(r["answer_point_coverage"] for r in answerable)
           / len(answerable))
    return {
        "n_all": len(rs), "n_answerable": len(answerable),
        "n_refused": len(refusals),
        "false_refusal": fr, "false_refusal_rate": fr / len(answerable),
        "false_answer": fa,
        "false_answer_rate": (fa / len(refusals)) if refusals else None,
        "citation_v2": {
            "micro": sup_ids / total_ids if total_ids else None,
            "total_ids": total_ids, "supported_ids": sup_ids,
            "fabricated": fab, "retrieved_not_in_context": nin,
            "answer_rate": ((len(answerable) - no_cite) / len(answerable)),
            "no_citation": no_cite,
        },
        "answer_point_coverage": cov,
    }


sa, sb = summarize(a), summarize(b)
pa = json.load(open(OUT / "paired-analysis-dev.json", encoding="utf-8"))
cov_ci = pa["paired"]["answer_point_coverage"]["bootstrap95ci_delta"]

gates = {}
gates["G1_false_refusal_reduction"] = {
    "pass": sb["false_refusal"] <= sa["false_refusal"] - 4,
    "detail": f"A={sa['false_refusal']} B={sb['false_refusal']} "
              f"(需 B ≤ {sa['false_refusal'] - 4})",
}
gates["G2_false_answer_not_worse"] = {
    "pass": sb["false_answer_rate"] <= sa["false_answer_rate"],
    "detail": f"A={sa['false_answer_rate']:.4f} B={sb['false_answer_rate']:.4f}",
}
gates["G3_citation_v2"] = {
    "pass": (sb["citation_v2"]["micro"] is not None
             and sb["citation_v2"]["micro"] >= 0.95
             and sb["citation_v2"]["fabricated"] == 0
             and sb["citation_v2"]["retrieved_not_in_context"] == 0),
    "detail": (f"micro={sb['citation_v2']['micro']} "
               f"fabricated={sb['citation_v2']['fabricated']} "
               f"not_in_context={sb['citation_v2']['retrieved_not_in_context']}"),
}
gates["G4_answer_rate_not_lower"] = {
    "pass": sb["citation_v2"]["answer_rate"] >= sa["citation_v2"]["answer_rate"],
    "detail": (f"A={sa['citation_v2']['answer_rate']:.4f} "
               f"B={sb['citation_v2']['answer_rate']:.4f}"),
}
gates["G5_coverage_not_significantly_down"] = {
    "pass": cov_ci is not None and not (cov_ci[1] < -0.05),
    "detail": f"coverage delta 95% CI={cov_ci} (上界 < -0.05 视为显著下降)",
}

verdict = "PASS" if all(g["pass"] for g in gates.values()) else \
    "AUTOMATED_DIAGNOSTIC_NO_GO"
result = {
    "verdict": verdict,
    "gates": gates,
    "a": sa,
    "b": sb,
    "note": "dev 未全部达标 → 不运行 holdout full（预注册门槛，fail-closed）"
            if verdict == "AUTOMATED_DIAGNOSTIC_NO_GO" else
            "dev 达标 → 可运行 holdout full（G6 方向一致性评估）",
}
(OUT / "gate-eval-dev.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

print("=" * 70)
print("DEV GATE EVALUATION (预注册门槛)")
print("=" * 70)
for name, g in gates.items():
    print(f"  [{'PASS' if g['pass'] else 'FAIL'}] {name}: {g['detail']}")
print(f"\nVERDICT: {verdict}")
sys.exit(0 if verdict == "PASS" else 2)
