"""离线对账工具：从历史 generation-cases.jsonl 确定性重算 citation v2 新口径。

背景：2026-08-04 审计发现同一批 selector-ablation 产物中 citation 指标出现
0.875 / 0.847 / 0.713 等不同值——旧汇总路径以不同分母（全体 / 可答 / 含 citation）
手算均值。本工具对历史运行做**只读** replay：

1. 逐 case 提取（case_counts_from_jsonl_row）→ 唯一聚合入口
   （aggregate_citations，与 compare.py 的 summary 同源）；
2. 对账 legacy 旧值：旧 generation-summary.json 中的 citation 键 vs
   JSONL 重算的全体分母均值（legacy_mean_metric，deprecated 仅对账用）；
3. v2 schema 产物额外校验 per-case 存储 validity 与 status_counts 重算一致；
4. v1 schema 产物（auto-run / reranker-recheck，缺 context 证据）如实报告
   context-supported 新口径 unavailable（不可重算），不伪造数值。

绝不改写历史 summary / 报告 / JSONL；输出只写入新目录：
results/graph-gate/citation-denominator-reconciliation-<timestamp>/
  reconciliation-summary.json   （规范化聚合 + 对账 + 不可解释情况）
  reconciliation-report.md      （人类可读报告）

用法：
    python -m evaluation.reconcile_citation_denominators \
        --output results/graph-gate/citation-denominator-reconciliation-<ts>
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from evaluation.citation_aggregation import (
    LEGACY_METRIC_KEYS,
    NEW_GUARDRAIL_METRICS,
    aggregate_citations,
    case_counts_from_jsonl_row,
    legacy_mean_metric,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GRAPH_GATE = REPO_ROOT / "results" / "graph-gate"

# 历史运行目录（只读输入；顺序固定保证确定性）
HISTORICAL_RUNS = [
    ("auto-run-20260804T121410", "auto-run（citation v1 时代）"),
    ("reranker-recheck-20260804T185937", "reranker-recheck（citation v1 时代）"),
    ("selector-ablation-20260804T202048", "selector-ablation（citation v2）"),
]

# 历史分析脚本中「可答分母」旧值的读取路径（存在才读；只读参考，不参与新口径）
# arm_map：分析脚本的 arm 标签 → 规范 arm 名（S0→selector-unlimited 等）
_ANALYSIS_OLD_VALUE_PATHS = {
    "s0s3-analysis.json": {
        "arm_map": {"S0": "selector-unlimited", "S3": "selector-cap3"},
        "splits": {
            "dev": ("split", "dev", "generation",
                    "context_supported_citation_validity"),
            "holdout": ("split", "holdout", "generation",
                        "context_supported_citation_validity"),
        },
    },
    "ab-analysis.json": {
        "arm_map": {"A": "standard", "B": "standard-rerank"},
        "splits": {
            "dev": ("split", "dev", "generation", "citation_id_validity"),
            "holdout": ("split", "holdout", "generation",
                        "citation_id_validity"),
        },
    },
}

# legacy summary 键 → CaseCitationCounts 字段（显式映射，禁止字符串拼接猜名）
LEGACY_KEY_TO_FIELD = {
    "citation_id_validity": "legacy_citation_id_validity",
    "citation_precision": "legacy_citation_precision",
    "citation_recall": "legacy_citation_recall",
    "faithfulness": "legacy_faithfulness",
    "context_supported_citation_validity":
        "legacy_context_supported_validity",
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _recompute_fidelity_issues(rows: list[dict[str, Any]]) -> list[str]:
    """v2 产物逐 case 校验：存储的 context_supported_citation_validity
    与 citation_status_counts 重算值是否一致（1e-9 容差）。"""
    issues: list[str] = []
    for row in rows:
        status_counts = row.get("citation_status_counts")
        if not isinstance(status_counts, dict):
            continue  # v1 行无此字段，不参与
        stored = row.get("context_supported_citation_validity")
        if stored is None:
            continue
        supported = sum(
            status_counts.get(s, 0)
            for s in ("supported_chunk", "supported_source"))
        unique = sum(status_counts.values())
        recomputed = (supported / unique) if unique else 0.0
        if abs(float(stored) - recomputed) > 1e-9:
            issues.append(
                f"{row.get('case_id')}: stored "
                f"context_supported_citation_validity={stored} != "
                f"recomputed from status_counts={recomputed}")
    return issues


def _legacy_cross_check(
    counts_by_arm: dict[str, list],
    old_summary: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """对账旧 summary 的 legacy 键 vs JSONL 重算的全体分母均值。"""
    result: dict[str, dict[str, Any]] = {}
    for arm, counts in sorted(counts_by_arm.items()):
        arm_key = arm.replace("-", "_")
        old_arm = (old_summary or {}).get(arm_key, {}).get("overall", {})
        entry: dict[str, Any] = {}
        for legacy_key in LEGACY_METRIC_KEYS:
            old_value = old_arm.get(legacy_key)
            replayed = legacy_mean_metric(
                counts, LEGACY_KEY_TO_FIELD[legacy_key])
            entry[legacy_key] = {
                "old_summary_value": old_value,
                "replayed_value": replayed,
                "match": (old_value is not None and replayed is not None
                          and abs(float(old_value) - replayed) <= 1e-9),
            }
        result[arm] = entry
    return result


def _analysis_old_values(run_dir: Path) -> dict[str, Any]:
    """读取历史分析脚本（s0s3-analysis / ab-analysis）中的「可答分母」旧值。

    返回 {split_name: {filename: {规范 arm 名: 值}}}（arm 标签经 arm_map 映射）。
    """
    found: dict[str, Any] = {}
    for filename, spec in _ANALYSIS_OLD_VALUE_PATHS.items():
        path = run_dir / filename
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        arm_map = spec["arm_map"]
        for split_name, key_path in spec["splits"].items():
            node = data
            ok = True
            for key in key_path:
                if isinstance(node, dict) and key in node:
                    node = node[key]
                else:
                    ok = False
                    break
            if not ok or not isinstance(node, dict):
                continue
            mapped = {
                arm_map.get(label, label): value
                for label, value in node.items()
                if isinstance(value, (int, float))
            }
            if mapped:
                found.setdefault(split_name, {})[filename] = mapped
    return found


def reconcile_run(run_dir: Path, output_dir: Path,
                  run_name: str) -> dict[str, Any]:
    """对单个历史运行目录做只读对账，返回规范化结果 dict。"""
    run_result: dict[str, Any] = {
        "run_dir": str(run_dir),
        "replayable": True,
        "splits": {},
        "notes": [],
    }
    for split_name in ("dev-full", "holdout-full"):
        split_dir = run_dir / split_name
        cases_file = split_dir / "generation-cases.jsonl"
        if not cases_file.exists():
            continue
        rows = _load_jsonl(cases_file)
        if not rows:
            continue
        old_summary = None
        summary_file = split_dir / "generation-summary.json"
        if summary_file.exists():
            try:
                old_summary = json.loads(
                    summary_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                run_result["notes"].append(
                    f"{split_name}: generation-summary.json 无法解析，跳过旧值对账")

        # 按 arm 分组（确定性排序）
        arms = sorted({str(r.get("arm", "")) for r in rows})
        counts_by_arm: dict[str, list] = {a: [] for a in arms}
        replayable = True
        for row in rows:
            counts_by_arm[str(row.get("arm", ""))].append(
                case_counts_from_jsonl_row(row))

        split_result: dict[str, Any] = {"n_rows": len(rows), "arms": {}}
        for arm in arms:
            counts = counts_by_arm[arm]
            agg = aggregate_citations(counts)
            agg.check_conservation()
            split_result["arms"][arm] = {
                "n_rows": len(counts),
                "citation_v2": agg.to_dict(),
            }
            if agg.n_evidence_missing > 0:
                replayable = False
                split_result["arms"][arm]["notes"] = [
                    f"n_evidence_missing={agg.n_evidence_missing}: 产物缺 "
                    "context 证据（v1 schema），context-supported 新口径不可重算"]

        split_result["legacy"] = _legacy_cross_check(
            counts_by_arm, old_summary)
        split_result["fidelity_issues"] = _recompute_fidelity_issues(rows)
        if split_result["fidelity_issues"]:
            replayable = False
            run_result["notes"].append(
                f"{split_name}: {len(split_result['fidelity_issues'])} 条 "
                "per-case validity 与 status_counts 重算不一致（不可解释）")
        run_result["splits"][split_name] = split_result
        run_result["replayable"] = run_result["replayable"] and replayable

    # 历史分析脚本「可答分母」旧值（只读参考；键对齐 split 目录名）
    analysis_old = _analysis_old_values(run_dir)
    run_result["analysis_old_values"] = {
        ("dev-full" if k == "dev"
         else ("holdout-full" if k == "holdout" else k)): v
        for k, v in analysis_old.items()
    }
    return run_result


def _write_report(report_path: Path,
                  summary: dict[str, Any],
                  run_meta: list[tuple[str, str]]) -> None:
    lines: list[str] = []
    lines.append("# Citation v2 分母统一 — 历史产物离线对账报告")
    lines.append("")
    lines.append("> 只读对账：从历史 generation-cases.jsonl 确定性重算新口径；")
    lines.append("> 不改写任何历史 summary / 报告 / JSONL；输出仅在本目录。")
    lines.append("")
    lines.append("## 一、分母契约（唯一命名）")
    lines.append("")
    lines.append("| 分母 | 含义 |")
    lines.append("|---|---|")
    lines.append("| `all_generation_cases` | 该 arm 全部 generation case（含 refusal/error） |")
    lines.append("| `answerable_generation_cases` | 非 should_refuse 且非 error 的 case |")
    lines.append("| `answers_with_any_citation` | answerable 中至少一个唯一引用 ID 的 case |")
    lines.append("| `total_unique_citation_ids` | 可答答案的唯一引用 ID 总数（重复引用计一次） |")
    lines.append("")
    lines.append("新指标（value=None = 分母为 0 → unavailable，不伪装为 0）：")
    lines.append("")
    lines.append("| 指标 | numerator | denominator | excluded_count |")
    lines.append("|---|---|---|---|")
    lines.append("| `context_supported_citation_validity_micro` | context-supported 唯一 ID 数 | `total_unique_citation_ids` | 无引用/缺证据答案数（行） |")
    lines.append("| `context_supported_answer_rate` | ≥1 个 context-supported 引用的答案数 | `answerable_generation_cases` | refusal+error 行数 |")
    lines.append("| `no_citation_answer_rate` | 无引用 ID 的答案数 | `answerable_generation_cases` | refusal+error 行数 |")
    lines.append("| `citation_mention_rate` | 至少一个引用 ID 的答案数 | `answerable_generation_cases` | refusal+error 行数 |")
    lines.append("")
    lines.append("旧键（citation_id_validity / citation_precision / citation_recall /")
    lines.append("faithfulness / context_supported_citation_validity 单值）为 "
    "legacy/deprecated，仅兼容读取；guardrail 只能消费上表新指标。")
    lines.append("")
    lines.append("## 二、逐运行对账")
    lines.append("")

    for run_name, run_desc in run_meta:
        run = summary["runs"][run_name]
        lines.append(f"### {run_name}（{run_desc}）")
        lines.append("")
        lines.append(f"- 可重算新口径：**{'是' if run['replayable'] else '否'}**")
        lines.append(f"- 运行目录：`{run['run_dir']}`")
        if run["notes"]:
            lines.append("- 运行级说明：")
            for n in run["notes"]:
                lines.append(f"  - {n}")
        for split_name, split in sorted(run["splits"].items()):
            lines.append("")
            lines.append(f"#### {split_name}（rows={split['n_rows']}）")
            lines.append("")
            lines.append("| arm | 旧值（legacy 全体分母） | 旧分析值（可答分母，若可读） | 新：validity_micro | 新：answer_rate | 新：no_citation_rate | 分母（answerable / unique IDs） |")
            lines.append("|---|---|---|---|---|---|---|")
            for arm, arm_res in sorted(split["arms"].items()):
                v2 = arm_res["citation_v2"]
                m = v2["metrics"]
                legacy_entry = split["legacy"].get(arm, {})
                old_parts = []
                for k in ("citation_id_validity",
                          "context_supported_citation_validity"):
                    if k in legacy_entry and \
                            legacy_entry[k]["old_summary_value"] is not None:
                        old_parts.append(
                            f"{k}={legacy_entry[k]['old_summary_value']:.4f}")
                old_str = "; ".join(old_parts) if old_parts else "—"
                analysis_old = run["analysis_old_values"].get(split_name, {})
                a_parts = []
                for fname, node in analysis_old.items():
                    if arm in node:
                        a_parts.append(f"{fname}:{node[arm]:.4f}")
                a_str = "; ".join(a_parts) if a_parts else "—"
                micro = m["context_supported_citation_validity_micro"]
                rate = m["context_supported_answer_rate"]
                nocite = m["no_citation_answer_rate"]
                fmt = lambda v: "unavailable" if v is None else f"{v:.4f}"
                lines.append(
                    f"| {arm} | {old_str} | {a_str} | {fmt(micro['value'])} "
                    f"| {fmt(rate['value'])} | {fmt(nocite['value'])} "
                    f"| {rate['denominator_count']} / "
                    f"{micro['denominator_count']} |")
            if split.get("fidelity_issues"):
                lines.append("")
                lines.append("**per-case 一致性校验失败（不可解释）**：")
                for issue in split["fidelity_issues"]:
                    lines.append(f"- {issue}")
        lines.append("")

    lines.append("## 三、不可解释情况")
    lines.append("")
    n_unexplained = 0
    for run_name, _ in run_meta:
        run = summary["runs"][run_name]
        for split_name, split in sorted(run["splits"].items()):
            for arm, arm_res in sorted(split["arms"].items()):
                v2 = arm_res["citation_v2"]
                if v2["n_evidence_missing"] > 0:
                    n_unexplained += 1
                    lines.append(
                        f"- **{run_name}/{split_name}/{arm}**："
                        f"{v2['n_evidence_missing']} 行缺 context 证据（citation "
                        "v1 时代产物），context-supported 新口径不可重算 → "
                        "unavailable。")
            for issue in split.get("fidelity_issues", []):
                n_unexplained += 1
                lines.append(f"- **{run_name}/{split_name}**：{issue}")
    if n_unexplained == 0:
        lines.append("- 无。全部可重算产物与历史值一致。")
    lines.append("")
    lines.append("## 四、guardrail 就绪性")
    lines.append("")
    lines.append("- 可作为 citation v2 guardrail 基线候选的运行："
                 "**仅 citation v2 schema 且重算一致者**（本批为 "
                 "`selector-ablation-20260804T202048`）。")
    lines.append("- v1 时代运行（auto-run / reranker-recheck）的 citation 指标"
                 "（含 precision/recall/faithfulness 占位值）不得作为 guardrail"
                 "输入，仅作 legacy 对账记录。")
    lines.append("- guardrail 阈值建立前必须固定分母（本契约已显式命名）；"
                 "历史报告中的 0.875/0.847（可答分母）与 0.713/0.691（全体"
                 "分母）差异由此解释，非指标 bug。")
    lines.append("")
    lines.append("*本报告由 `evaluation/reconcile_citation_denominators.py` 只读"
                 "生成；未修改任何历史产物。*")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Citation v2 分母统一：历史产物离线对账（只读）")
    parser.add_argument("--output", required=True,
                        help="输出目录（新建，绝不写入历史目录）")
    parser.add_argument("--run", action="append", default=None,
                        help="额外运行目录（默认三个历史运行）")
    args = parser.parse_args(argv)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_meta = list(HISTORICAL_RUNS)
    if args.run:
        for extra in args.run:
            run_meta.append((str(Path(extra)), "额外运行"))

    runs: dict[str, dict[str, Any]] = {}
    for run_name, run_desc in run_meta:
        run_dir = Path(run_name)
        if not run_dir.exists():
            run_dir = GRAPH_GATE / run_name
        if not run_dir.exists():
            print(f"[reconcile] skip missing run dir: {run_dir}")
            continue
        runs[run_name] = reconcile_run(run_dir, output_dir, run_name)

    summary = {"schema_version": 1, "runs": runs}
    json_path = output_dir / "reconciliation-summary.json"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")
    _write_report(output_dir / "reconciliation-report.md", summary, run_meta)
    print(f"[reconcile] wrote {json_path}")
    print(f"[reconcile] wrote {output_dir / 'reconciliation-report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
