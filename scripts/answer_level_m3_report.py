"""M3 judge 报告生成器（读密封产物 → report.md，可复现）。

输入：results/answer-level/m3-judge-<date>/ 下 outcomes-judge.jsonl +
report.json + manifest.json。
输出：同目录 report.md（三态分布 / 修正口径两份 / 分歧率 / 跨类分布 /
3 例 no_answer 型 / token 实耗与预算对比 / 自判偏置披露 / 全量清单）。
只读不写回：不改 outcomes-judge/report/manifest（密封不可变），
report.md 新写。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.answer_judge_runner import BUDGET_COMPLETION, BUDGET_PROMPT_RANGE


def _fmt(x: float | None, digits: int = 4) -> str:
    return f"{x:.{digits}f}" if x is not None else "N/A"


def _cell(text: str | None, width: int = 48) -> str:
    """markdown 单元格安全化：竖线/换行转义（表格渲染完整性）。"""
    return (str(text or "").replace("|", "/").replace("\n", " "))[:width]


def build_report(out_dir: Path) -> str:
    out_dir = Path(out_dir)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    rows = [json.loads(l) for l in
            (out_dir / "outcomes-judge.jsonl").read_text(encoding="utf-8")
            .splitlines()]

    agg = {k: report[k] for k in (
        "judged_count", "mechanical_hit_count", "total_points",
        "mechanical_rate", "count_hit", "count_partial", "count_miss",
        "count_contract_error", "corrected_rate_partial_05",
        "corrected_rate_partial_0", "divergence_count", "divergence_rate",
        "contract_error_rate", "by_query_type")}
    tokens = report.get("judge_tokens", {})
    tok = tokens.get("total_tokens", 0)
    tok_prompt = tokens.get("prompt_tokens", 0)
    tok_comp = tokens.get("completion_tokens", 0)
    calls = tokens.get("calls", 0)

    lo, hi = BUDGET_PROMPT_RANGE
    prompt_pct = tok_prompt / ((lo + hi) / 2) if (lo + hi) else 0.0

    lines: list[str] = []
    A = lines.append
    A("# Mneme 答案级评测线 M3 报告：受约束 judge 子集")
    A("")
    A(f"- 协议版本：`{manifest['judge_protocol_version']}`"
      f"（verdict 外置词表 {manifest['judge_verdicts']}；"
      f"max_tokens={manifest['judge_max_tokens']}；"
      f"尝试上限={manifest['judge_max_attempts']}）")
    A(f"- judge 模型：`{manifest.get('judge_model')}`"
      "（llm_call 缺省走 Settings，与 M2 生成同模型——见 §8 自判偏置披露）")
    A(f"- 数据源：M2 密封产物 `{manifest['m2_dir']}`"
      f"（m2_outcomes_sha256={manifest['m2_outcomes_sha256'][:12]}…），"
      f"数据集 `{manifest['dataset_name']}`"
      f"（dataset_sha256={manifest['dataset_sha256'][:12]}…）")
    A(f"- 密封：`outcomes_sha256={manifest['outcomes_sha256'][:12]}…`，"
      f"`manifest_sha256={manifest['manifest_sha256'][:12]}…`"
      "（自哈希 MATCH；本报告只读不写回）")
    A(f"- 本轮基线：judge 只判 M2 机械 miss 要点（{agg['judged_count']} 条 / "
      f"覆盖 {len({r['case_id'] for r in rows})} 例），不重跑 M2。")
    A("")

    A("## 1. judge 三态分布与契约错误率")
    A("")
    n = agg["judged_count"]
    A(f"- hit **{agg['count_hit']}** / partial **{agg['count_partial']}** / "
      f"miss **{agg['count_miss']}** / contract_error **{agg['count_contract_error']}**"
      f"（X+Y+Z+W={n}）")
    A(f"- contract_error_rate = **{_fmt(agg['contract_error_rate'])}**"
      f"（{agg['count_contract_error']}/{n}；契约错误行按 miss 计入，"
      "但未进三态分布与修正分子——如实披露 judge 自身可靠性）")
    A(f"- 平均尝试次数：{sum(r['attempts'] for r in rows) / n:.2f}"
      f"（min {min(r['attempts'] for r in rows)} / "
      f"max {max(r['attempts'] for r in rows)}）")
    A("")

    A("## 2. 修正口径（两面并列，不作门禁/不作优劣结论）")
    A("")
    A(f"- 机械下界（M2 containment）：**{_fmt(agg['mechanical_rate'])}**"
      f"（{agg['mechanical_hit_count']}/{agg['total_points']}）")
    A(f"- 修正命中率（partial 计 0.5）：**{_fmt(agg['corrected_rate_partial_05'])}**"
      f" = ({agg['mechanical_hit_count']} + {agg['count_hit']} + "
      f"0.5×{agg['count_partial']})/{agg['total_points']}")
    A(f"- 保守修正（partial 计 0）：**{_fmt(agg['corrected_rate_partial_0'])}**"
      f" = ({agg['mechanical_hit_count']} + {agg['count_hit']})/"
      f"{agg['total_points']}")
    A("- 口径说明：containment 机械下界对同义改写/中英互译系统性漏判，"
      "judge 修正只覆盖机械未命中面；两条修正曲线是同一事实的上下界展示，"
      "本轮为诊断基线，无任何产品门禁判定。")
    A("")

    A("## 3. 分歧率")
    A("")
    A(f"- 分歧率 = (X+Y)/{n} = **{_fmt(agg['divergence_rate'])}**"
      f"（{agg['divergence_count']}/{n}）——机械下界低估量的直接度量："
      "judge 把多少机械 miss 翻转为 hit/partial。")
    A("")

    A("## 4. 跨类分布（query_type × judge verdict）")
    A("")
    A("| query_type | hit | partial | miss | contract_error | 小计 |")
    A("| --- | ---: | ---: | ---: | ---: | ---: |")
    for qt, b in sorted(agg["by_query_type"].items()):
        s = sum(b.values())
        A(f"| `{qt}` | {b['hit']} | {b['partial']} | {b['miss']} | "
          f"{b['contract_error']} | {s} |")
    A(f"- multi_turn 系（M2 近全 miss 重点群体）："
      f"共 {sum(agg['by_query_type'].get('multi_turn', {}).values())} 条，"
      f"hit {agg['by_query_type'].get('multi_turn', {}).get('hit', 0)} / "
      f"partial {agg['by_query_type'].get('multi_turn', {}).get('partial', 0)} / "
      f"miss {agg['by_query_type'].get('multi_turn', {}).get('miss', 0)} / "
      f"contract_error "
      f"{agg['by_query_type'].get('multi_turn', {}).get('contract_error', 0)}")
    A("")

    A("## 5. no_answer 型 3 例（M2 披露：语义正确但措辞不等价）")
    A("")
    A("| case | 要点 | judge verdict | contract_error | evidence |")
    A("| --- | --- | --- | --- | --- |")
    for r in report.get("no_answer_required", []):
        A(f"| `{r['case_id']}` | {_cell(r['point_text'], 50)} | "
          f"{r['judge_verdict']} | {r['contract_error']} | {_cell(r.get('evidence'))} |")
    if not report.get("no_answer_required"):
        A("|（无） | | | | |")
    A("")

    A("## 6. judge token 实耗与预算对比")
    A("")
    A(f"- judge 调用：**{calls} 次**（call_type='judge' 网关记录过滤）")
    A(f"- prompt：**{tok_prompt:,}**（预算 {lo:,}–{hi:,}，"
      f"占中值 {prompt_pct:.1%}）；completion：**{tok_comp:,}**"
      f"（预算 {BUDGET_COMPLETION:,}）；合计 **{tok:,}**")
    A(f"- 单次平均：prompt {tok_prompt / calls:,.0f} / "
      f"completion {tok_comp / calls:,.0f}" if calls else "- 无调用记录")
    A("")

    A("## 7. 同模型自判偏置披露")
    A("")
    A("- judge 与 M2 生成使用**同一模型**"
      f"（`{manifest.get('judge_model')}`，llm_call 均缺省走 Settings），"
      "即「生成者的同门模型审自己的答案」——语义等价判断存在同构偏置可能，"
      "本报告不以此为结论，仅如实披露身份。")
    A("")

    A("## 8. 逐要点清单（全量，无截断）")
    A("")
    A("| case | query_type | 要点 | judge verdict | attempts | contract_error | evidence |")
    A("| --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        A(f"| `{r['case_id']}` | {r['query_type']} | "
          f"{_cell(r['point_text'], 36)} | {r['judge_verdict']} | "
          f"{r['attempts']} | {r['contract_error']} | {_cell(r.get('evidence'))} |")
    A("")
    A("---")
    A("本报告为第二轮诊断基线（owner 批示：M3 无门禁判定；"
      "M4 预注册阈值门禁另行呈批）。所有数字为事实陈述。")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M3 报告生成器（只读+新写 report.md）")
    parser.add_argument("run_dir", help="密封产物目录")
    args = parser.parse_args(argv)

    out_dir = Path(args.run_dir)
    report = build_report(out_dir)
    target = out_dir / "report.md"
    target.write_text(report, encoding="utf-8")
    print(f"[report] written: {target} ({len(report)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
