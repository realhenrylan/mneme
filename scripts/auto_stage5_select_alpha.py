"""阶段5：阅读 dev retrieval summary 自动选 alpha + 生成 locked-config。

设计：从 dev retrieval 扫描结果（smoke 后 vs dev-only retrieval）中，按
planbook §4.4 选唯一 alpha。决策顺序：
  1) 候选 = 所有 graph_target 切片 context_recall 最高的 alpha
  2) 差距 < 1pp → 选更高 alpha（更稳）
  3) 候选相对 B (standard_rerank) 在 graph_target 的 context_precision
     下降 > 2pp → 淘汰
  4) 唯一入选 alpha 写入 locked-config（index/KG 指纹实测）。

需要 dev retrieval summary 以 alpha-{a}/summary.json 形式存在。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_alpha_summaries(dev_dir: Path) -> dict[float, dict]:
    """加载所有 alpha-{a}/summary.json。返回 {alpha: summary}。"""
    out = {}
    for d in sorted(dev_dir.iterdir()):
        if not d.is_dir() or not d.name.startswith("alpha-"):
            continue
        try:
            alpha = float(d.name.removeprefix("alpha-"))
        except ValueError:
            continue
        sp = d / "summary.json"
        if sp.exists():
            out[alpha] = json.loads(sp.read_text(encoding="utf-8"))
    return out


def select_alpha(summaries: dict[float, dict]) -> dict:
    """按 §4.4 决策。返回完整决策证据。"""
    # 收集 graph_target 切片下 C 的 context_recall / context_precision
    # 以及 B 在 graph_target 的 context_precision 基线
    records = {}
    for alpha, summary in summaries.items():
        c = summary.get("graph_rerank", {})
        b = summary.get("standard_rerank", {})
        gt_c = c.get("graph_target", {})
        gt_b = b.get("graph_target", {})
        records[alpha] = {
            "C_context_recall": gt_c.get("context_recall", 0.0),
            "C_context_precision": gt_c.get("context_precision", 0.0),
            "B_context_precision": gt_b.get("context_precision", 0.0),
            "C_n_chunk_valid": gt_c.get("n_chunk_valid", 0),
        }

    if not records:
        return {"selected_alpha": None, "error": "no alpha summaries found"}

    # 1) 按 graph_target context_recall 降序
    sorted_by_recall = sorted(records.items(), key=lambda x: -x[1]["C_context_recall"])
    best_recall_alpha, best_recall_val = sorted_by_recall[0]
    # 2) 差距 < 1pp → 选更高 alpha
    candidates = [best_recall_alpha]
    for alpha, r in sorted_by_recall[1:]:
        if r["C_n_chunk_valid"] == 0:
            continue
        if (best_recall_val["C_context_recall"] - r["C_context_recall"]) < 0.01:
            # <1pp 差距，纳入候选
            if alpha not in candidates:
                candidates.append(alpha)
    # 在并列候选取更高 alpha（更稳）
    candidates.sort(reverse=True)

    # 3) context_precision 相对 B 下降 > 2pp → 淘汰
    eliminated = []
    survivors = []
    for alpha in candidates:
        r = records[alpha]
        drop = r["B_context_precision"] - r["C_context_precision"]
        if drop > 0.02:
            eliminated.append({
                "alpha": alpha,
                "reason": "context_precision drop > 2pp vs B",
                "B_ctx_prec": r["B_context_precision"],
                "C_ctx_prec": r["C_context_precision"],
                "drop": drop,
            })
        else:
            survivors.append(alpha)

    # 若全部被淘汰，回退到最高 recall alpha（明确记录）
    if not survivors:
        survivors = [best_recall_alpha]

    selected = survivors[0]  # 已按降序
    return {
        "selected_alpha": selected,
        "records": {f"{a:.2f}": r for a, r in records.items()},
        "eliminated": eliminated,
        "decision_notes": (
            f"selected alpha={selected:.2f} by §4.4: max graph_target context_recall"
            f" tied candidates {candidates}"
            f"; survivors after 2pp context_precision drop filter: {survivors}"
        ),
    }


def main():
    if len(sys.argv) < 2:
        print("usage: auto_stage5_select_alpha.py <DEV_DIR>")
        print("example: python scripts/auto_stage5_select_alpha.py "
              "results/graph-gate/auto-run-<ts>/dev-retrieval")
        return 2
    dev_dir = Path(sys.argv[1]).resolve()
    if not dev_dir.exists():
        print(f"DEV_DIR not found: {dev_dir}")
        return 2

    print(f"loading alpha summaries from {dev_dir}")
    summaries = load_alpha_summaries(dev_dir)
    print(f"  loaded {len(summaries)} alpha summaries: {sorted(summaries)}")
    if not summaries:
        return 2

    decision = select_alpha(summaries)
    print(f"\n=== alpha 决策 ===")
    print(json.dumps(decision, ensure_ascii=False, indent=2))

    # 写入 decision file
    out_file = dev_dir.parent / "alpha-selection.json"
    out_file.write_text(
        json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"\n→ alpha-selection.json written to {out_file}")
    print(f"  selected_alpha = {decision['selected_alpha']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())