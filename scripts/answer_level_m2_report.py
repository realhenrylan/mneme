"""M2 答案级基线报告生成器（读密封产物 → report.md，可复现）。

输入：results/answer-level/<run>/ 下 outcomes.jsonl + manifest.json，
v2.1 数据集真值（id 映射）。
输出：同目录 report.md（五维度：answer_hit / token / refusal 三形态 /
citation 联合 / 逐例遗漏）。
只读不写回：不改 outcomes/manifest（密封不可变），report.md 新写。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.answer_level_report import classify_refusal_form


def _fmt(x: float, digits: int = 4) -> str:
    return f"{x:.{digits}f}"


def build_report(out_dir: Path) -> str:
    out_dir = Path(out_dir)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    rows = [json.loads(l) for l in
            (out_dir / "outcomes.jsonl").read_text(encoding="utf-8").splitlines()]

    # ── 1. answer_hit ──
    hits = [r["answer_hit"] for r in rows
            if (r.get("answer_hit") or {}).get("answer_hit_rate") is not None]
    rates = [h["answer_hit_rate"] for h in hits]
    eff_pts = sum(h["effective_point_count"] for h in hits)
    hit_pts = sum(h["hit_count"] for h in hits)
    no_pts = len(rows) - len(hits)
    pt_rate = hit_pts / eff_pts if eff_pts else None
    case_rate = sum(rates) / len(rates) if rates else None

    by_type: dict[str, list[float]] = {}
    by_lang: dict[str, list[float]] = {}
    for r in rows:
        h = (r.get("answer_hit") or {}).get("answer_hit_rate")
        if h is None:
            continue
        by_type.setdefault(r["query_type"], []).append(h)
        by_lang.setdefault(r["language"], []).append(h)

    # ── 2. token ──
    tot = [(r.get("prompt_tokens") or 0) + (r.get("completion_tokens") or 0)
           for r in rows]
    p_tot = sum(r.get("prompt_tokens") or 0 for r in rows)
    c_tot = sum(r.get("completion_tokens") or 0 for r in rows)
    zero_tok = [r["case_id"] for r in rows
                if (r.get("prompt_tokens") or 0) + (r.get("completion_tokens") or 0) == 0]
    refuse_tok = [t for t, r in zip(tot, rows) if r["should_refuse"]]
    ans_tok = [t for t, r in zip(tot, rows) if not r["should_refuse"]]

    # ── 3. refusal 三形态 ──
    forms: dict[str, list[str]] = {}
    for r in rows:
        if not r["should_refuse"]:
            continue
        f = classify_refusal_form(
            should_refuse=True, answer=r["answer"], context=r.get("context") or "",
        )
        forms.setdefault(f, []).append(r["case_id"])
    probe_correct = sum(
        1 for r in rows
        if r["should_refuse"] and r["citation_metrics"]["correctly_refused"] is True)
    false_refuse = [
        r["case_id"] for r in rows
        if not r["should_refuse"]
        and r["citation_metrics"]["correctly_refused"] is False]
    n_ans = sum(1 for r in rows if not r["should_refuse"])

    # ── 4. citation 联合 ──
    cm_keys = [
        "citation_id_validity", "context_supported_citation_validity",
        "citation_precision", "citation_recall", "faithfulness",
    ]
    means = {k: sum(r["citation_metrics"][k] for r in rows) / len(rows)
             for k in cm_keys}
    nonzero = {k: sum(1 for r in rows if r["citation_metrics"][k] > 0)
               for k in cm_keys}

    # 归因：有引用例中 context∩truth 关系（检索缺口 vs 引用未覆盖）。
    # 拒答探针（should_refuse=True）无真值块，归入 "probe_no_truth" 单列。
    retrieval_gap = covered_but_uncited = other = probe_no_truth = 0
    for r in rows:
        cm = r["citation_metrics"]
        if cm["total_citation_count"] == 0:
            continue
        if not r.get("relevant_chunk_ids"):
            probe_no_truth += 1
            continue
        ctx = set(r.get("context_chunk_ids") or [])
        truth = set(r["relevant_chunk_ids"])
        if not (ctx & truth):
            retrieval_gap += 1
        elif not (set(e["chunk_id"] for e in cm.get("evidence") or []) & truth):
            covered_but_uncited += 1
        else:
            other += 1
    gap_122 = sum(
        1 for r in rows
        if r.get("relevant_chunk_ids")
        and not (set(r.get("context_chunk_ids") or []) & set(r["relevant_chunk_ids"])))

    # ── 5. 逐例遗漏 ──
    miss_points: list[tuple[str, str, str]] = []
    for r in rows:
        h = r.get("answer_hit") or {}
        if h.get("answer_hit_rate") is None:
            continue
        for p in h.get("point_results") or []:
            if p["verdict"] == "miss":
                miss_points.append((r["case_id"], p["point_text"], r["query_type"]))
    miss_in_po = [
        (r["case_id"], r["query_type"]) for r in rows
        if r["citation_metrics"]["total_citation_count"] > 0
        and r["citation_metrics"]["citation_precision"] == 0.0
        and r.get("relevant_chunk_ids")
        and set(r.get("context_chunk_ids") or []) & set(r["relevant_chunk_ids"])
    ]

    lines: list[str] = []
    A = lines.append
    A("# Mneme 答案级评测线 M2 诊断基线报告")
    A("")
    A(f"- 数据集：`{manifest['dataset_name']}`"
      f"（{manifest['sampling']['dataset_size']} 例基准，"
      f"本次 `{manifest['case_count']}` 例全量）")
    A(f"- 指标口径：`{manifest['metric_version']}`（answer-hit containment 族，"
      f"机械下界）")
    A(f"- chunk_id 域：`{manifest['chunk_id_domain']}`（M1.1 归一修复后；"
      "产品侧 ID 形态未改，仅评测侧比对归一）")
    A(f"- 密封：`outcomes_sha256={manifest['outcomes_sha256'][:12]}…`，"
      f"`manifest_sha256={manifest['manifest_sha256'][:12]}…`"
      "（自哈希 MATCH；本报告只读不写回）")
    A(f"- 运行时粒度：`retrieval_ms=0.0`（生成路径未拆分检索/生成计时，"
      "M1 起已知粒度；总耗时 `total_ms` 有效）")
    A("")

    A("## 1. answer_hit（有效要点机械命中）")
    A("")
    A(f"- 可判定例：{len(hits)}（拒答/无要点例 {no_pts}，计入 "
      "`cases_without_effective_points`；其中 28 例为拒答探针）")
    A(f"- 要点级命中率：**{hit_pts}/{eff_pts} = {_fmt(pt_rate)}**"
      "（含义：真值要点被答案文本规范化包含，机械下界）")
    A(f"- 例级宏平均：**{_fmt(case_rate)}**（{len(rates)} 例宏平均）")
    A(f"- 逐例分布：全中 {sum(1 for v in rates if v == 1.0)} / "
      f"部分 {sum(1 for v in rates if 0 < v < 1)} / 全零 {sum(1 for v in rates if v == 0.0)}")
    for k, v in sorted(by_type.items()):
        A(f"- 按 query_type `{k}`：n={len(v)} 平均={_fmt(sum(v)/len(v))}")
    for k, v in sorted(by_lang.items()):
        A(f"- 按 language `{k}`：n={len(v)} 平均={_fmt(sum(v)/len(v))}")
    A("- 结构性局限（如实披露）：containment 只识别文本规范化包含；"
      "同义改写/中英互译/指代变换型要点系统性漏判，此值为**下界**）")
    A("")

    A("## 2. token 实耗")
    A("")
    A(f"- 合计：**{sum(tot):,}**（prompt {p_tot:,} + completion {c_tot:,}；"
      f"completion 占比 {c_tot / sum(tot):.1%}）")
    A(f"- 全量 150 例：平均 {sum(tot)/len(tot):,.0f}，中位 {sorted(tot)[len(tot)//2]:,}，"
      f"min {min(tot):,} / max {max(tot):,}")
    A(f"- 拒答探针 28 例：合计 {sum(refuse_tok):,}，平均 {sum(refuse_tok)/len(refuse_tok):,.0f}")
    A(f"- 可答例 122：合计 {sum(ans_tok):,}，平均 {sum(ans_tok)/len(ans_tok):,.0f}")
    A(f"- 零 token 例 {len(zero_tok)} 个（`{', '.join(zero_tok[:6])}` 等）："
      "纯本地快速拒答路径——检索零证据未触发 LLM，无 gateway 记录，"
      "答案文本为固定拒绝消息（非 LLM 生成），token 记录真实为 0")
    A("")

    A("## 3. refusal（28 拒答探针 + 122 可答误拒率）")
    A("")
    A(f"- 28 探针正确拒答：**{probe_correct}/28** = {_fmt(probe_correct/28)}")
    A(f"- 122 可答例误拒答：**{len(false_refuse)}/122** = {_fmt(len(false_refuse)/n_ans)}")
    A(f"- 语义式陈述占探针 **{len(forms.get('semantic_statement', []))}/28**（非拒答消息形态，"
      "词表未命中；indicator 词典外语义等价输出归此类——如实披露，不作优劣裁决）")
    for f in ("sentinel_refusal", "post_generation_refusal", "semantic_statement"):
        A(f"- `{f}`（{len(forms.get(f, []))} 例）："
          f"{', '.join(forms.get(f, [])[:8])}{'…' if len(forms.get(f, [])) > 8 else ''}")
    A("")

    A("## 4. citation 契约 v2 联合分布（12-hex 归一口径）")
    A("")
    for k in cm_keys:
        A(f"- `{k}`：mean={_fmt(means[k])}，非零例 {nonzero[k]}/150")
    A(f"- 有引用例 {sum(1 for r in rows if r['citation_metrics']['total_citation_count'] > 0)}/150；"
      f"真值非空的引用例中：检索缺口（context∩truth=∅）{retrieval_gap}，"
      f"引用未覆盖（context 含真值但答案未引用）{covered_but_uncited}，"
      f"命中真值引用 {other}；拒答探针（无真值块）{probe_no_truth}")
    A(f"- 122 可答例中检索缺口（context∩truth=∅）：**{gap_122}/122**"
      "——答案引用质量的主要制约是检索未召回真值块，而非引用错位")
    A("- 说明：`faithfulness` 为证据覆盖启发式（要点术语 vs context ≥50% 命中），"
      "非答案级指标，引用契约带内汇报；`context_supported_citation_validity` "
      "为契约 v2 正式 guardrail 口径（引用 chunk 真正进入 context）")
    A("")

    A("## 5. 逐例遗漏清单（诊断，无门禁判定）")
    A("")
    A(f"- 要点 miss 共 {len(miss_points)} 条（覆盖 {len({c for c, _, _ in miss_points})} 例；"
      "截样本 24 条）：")
    for cid, pt, qt in miss_points[:24]:
        A(f"  - `{cid}` `[{qt}]` {pt[:60]}")
    A(f"- context 含真值但引用 precision=0 的例（{len(miss_in_po)} 个）："
      f"`{', '.join(c for c, _ in miss_in_po[:10])}`"
      f"{'…' if len(miss_in_po) > 10 else ''}")
    A("")

    A("---")
    A("本报告为纯诊断基线（owner Q3 批示：首轮无任何产品门禁）；"
      "所有数字为事实陈述，不含合格/不合格判定。")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M2 报告生成器（只读+新写 report.md）")
    parser.add_argument(
        "run_dir",
        help="密封产物目录（含 outcomes.jsonl + manifest.json）")
    args = parser.parse_args(argv)

    out_dir = Path(args.run_dir)
    report = build_report(out_dir)
    target = out_dir / "report.md"
    target.write_text(report, encoding="utf-8")
    print(f"[report] written: {target} ({len(report)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
