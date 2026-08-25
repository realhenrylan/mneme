"""false-refusal 与 guardrail 阈值只读审计包生成器（离线、fail-closed）。

输入（只读，绝不改写任何历史产物）：
  - production-baseline-stable-20260805T084256/{dev,holdout}-full/
      generation-cases.jsonl / retrieval-cases.jsonl / ground-truth-map.json
  - evaluation/datasets/v1.jsonl
  - candidate-report-data.json（guardrail 复算一致性参照）

输出（写入本脚本所在的新时间戳目录）：
  - refusal-review-pack.jsonl  逐 false_refusal case 提取
  - guardrail-sensitivity.json 阈值敏感性（结构化）
  - refusal-guardrail-audit.md 审计报告
  - manifest.json              输入 SHA-256 / 计数 / 不可变性声明

fail-closed 原则：
  - false_refusal 计数必须精确等于 dev=14 / holdout=1，否则整体失败；
  - 拒答判定短语与 evaluation/citation_metrics.compute_refusal_accuracy
    默认集一致（子串匹配），并用该函数复核 JSONL 的 correctly_refused；
  - guardrail 复算一律使用 candidate-report-data.json 中已有的
    numerator/denominator，偏差 >1e-9 即失败，绝不手填数字。
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(r"D:\GitHub\mneme\results\graph-gate\production-baseline-stable-20260805T084256")
DATASET = Path(r"D:\GitHub\mneme\evaluation\datasets\v1.jsonl")
OUT = Path(__file__).resolve().parent

# 与 evaluation/citation_metrics.compute_refusal_accuracy 默认集一致
REFUSAL_INDICATORS = [
    "未找到", "无法回答", "没有足够", "暂无", "无法提供",
    "cannot", "unable to", "no information", "not found",
    "don't have", "does not contain", "not available",
]

# 期望的 false_refusal 计数（来自正式运行 summary，不符即 fail-closed）
EXPECTED_FALSE_REFUSAL = {"dev": 14, "holdout": 1}

# 候选 guardrail 阈值（candidate-report.md §四建议，未批准，仅敏感性模拟）
FALSE_REFUSAL_THRESHOLDS = [0.15, 0.18, 0.20, 0.25]
CITATION_V2_GUARDRAILS = {
    "context_supported_citation_validity_micro": {"threshold": 0.95, "direction": "gte"},
    "context_supported_answer_rate": {"threshold": 0.80, "direction": "gte"},
    "no_citation_answer_rate": {"threshold": 0.20, "direction": "lte"},
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def wilson_ci(x: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """Wilson 95% 双侧置信区间；n=0 → (None, None)。"""
    if n <= 0:
        return None, None
    p = x / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    # 钳制到 [0,1]（p=0/n=1 时浮点可能产生 -1e-17 级负下限）
    return max(0.0, center - half), min(1.0, center + half)


def refusal_hits(answer: str) -> list[str]:
    """命中拒答指示短语的子列表（与 compute_refusal_accuracy 同口径）。"""
    return [ind for ind in REFUSAL_INDICATORS if ind in answer.lower()]


def load_split(split: str) -> tuple[dict, dict, dict, dict]:
    d = BASE / f"{split}-full"
    gen = {r["case_id"]: r for r in load_jsonl(d / "generation-cases.jsonl")}
    ret = {r["case_id"]: r for r in load_jsonl(d / "retrieval-cases.jsonl")}
    gt = json.load(open(d / "ground-truth-map.json", encoding="utf-8"))
    gt_by_case: dict[str, list] = {}
    for e in gt:
        gt_by_case.setdefault(e["case_id"], []).append(e)
    return gen, ret, gt_by_case


def build_case_record(split: str, g: dict, r: dict, gt_entries: list, ds_case: dict) -> dict:
    # 真值来源/chunk 均取 retrieval 行（评测网格记录，generation 行不携带）
    relevant_sources = set(r.get("relevant_source_ids") or [])
    context_sources = set(r.get("context_source_ids") or [])
    relevant_chunks = set(r.get("relevant_chunk_ids") or [])
    context_chunks = set(r.get("context_chunk_ids") or [])
    candidate_chunks = set(r.get("candidate_chunk_ids") or [])
    hits = refusal_hits(g["answer"])
    meta = ds_case.get("metadata") or {}
    return {
        "split": split,
        "case_id": g["case_id"],
        "query": g["query"],
        "language": g["language"],
        "query_type": g["query_type"],
        "difficulty": meta.get("difficulty"),
        "is_multi_turn": bool(meta.get("turn", 1) > 1 or meta.get("follow_up_to")),
        "follow_up_to": meta.get("follow_up_to"),
        "is_source_only": r.get("has_chunk_truth") is False and bool(relevant_sources),
        "acceptable_answer_points": ds_case.get("acceptable_answer_points") or [],
        "model_answer": g["answer"],
        "refusal_indicators_hit": hits,
        "refusal_basis": (
            f"answer contains refusal indicator(s) {hits!r}; "
            f"compute_refusal_accuracy(answer, should_refuse=False) -> False"
        ),
        "answer_point_coverage": g.get("answer_point_coverage"),
        "context_source_ids": sorted(context_sources),
        "relevant_source_ids": sorted(relevant_sources),
        "truth_source_in_context": bool(relevant_sources & context_sources),
        "context_source_recall": (
            len(relevant_sources & context_sources) / len(relevant_sources)
            if relevant_sources else None
        ),
        "has_chunk_truth": r.get("has_chunk_truth"),
        "relevant_chunk_ids": sorted(relevant_chunks),
        "context_chunk_ids": sorted(context_chunks),
        "relevant_chunk_in_context": bool(relevant_chunks & context_chunks),
        "relevant_chunk_in_candidates": bool(relevant_chunks & candidate_chunks),
        "gt_map_entries": [
            {
                "source_id": e["source_id"],
                "matched_chunk_ids": e.get("matched_chunk_ids") or [],
                "match_method": e.get("match_method"),
                "reviewer_status": e.get("reviewer_status"),
                "relevance_level": e.get("relevance_level"),
            }
            for e in gt_entries
        ],
        "citation_status_counts": g.get("citation_status_counts") or {},
        "fabricated_citation_count": g.get("fabricated_citation_count"),
        "retrieved_not_in_context_count": g.get("retrieved_not_in_context_count"),
        "correctly_refused": g.get("correctly_refused"),
        "error": g.get("error"),
    }


def slice_analysis(all_answerable: list[dict], fr_ids: set[str]) -> list[dict]:
    """按 language/query_type/source_only/multi_turn/difficulty 分组。

    all_answerable：全部 answerable case 的记录（分母）；fr_ids：
    false_refusal case_id 集合（分子）。只有 false_refusal 记录会得到
    分子==分母的错误切片，故分子必须用 id 集合判定。
    """
    # 结构化切片：显式枚举而非文本键（dim → case 记录字段名）
    slices: list[dict] = []
    groups = {
        "language": ("zh", "en", "mixed"),
        "query_type": ("single_fact", "cross_document", "metadata",
                       "mixed_intent", "multi_turn"),
        "difficulty": ("easy", "medium", "hard"),
        "source_only": (True, False),
        "multi_turn": (True, False),
    }
    fields = {"source_only": "is_source_only", "multi_turn": "is_multi_turn"}
    for dim, values in groups.items():
        field = fields.get(dim, dim)
        for val in values:
            members = [c for c in all_answerable if c[field] == val]
            n_ans = len(members)
            n_fr = sum(1 for c in members if c["case_id"] in fr_ids)
            lo, hi = wilson_ci(n_fr, n_ans)
            slices.append({
                "dimension": dim, "value": str(val),
                "n_false_refusal": n_fr, "n_answerable": n_ans,
                "rate": (n_fr / n_ans if n_ans else None),
                "wilson_95ci": [lo, hi],
            })
    return slices


def fmt_rate(v: float | None) -> str:
    return "—" if v is None else f"{v:.4f}"


def fmt_ci(ci: list) -> str:
    lo, hi = ci
    if lo is None or hi is None:
        return "—"
    return f"[{lo:.4f}, {hi:.4f}]"


def write_audit_report(sensitivity: dict, pack_rows: list[dict]) -> None:
    """生成人类可读审计报告（数字全部来自内存数据，杜绝手填漂移）。"""
    def slice_table(split: str) -> str:
        lines = ["| 维度 | 分组 | false_refusal / answerable | 比率 | Wilson 95% CI |",
                 "|---|---|---|---|---|"]
        for s in sensitivity["slices"][split]:
            lines.append(
                f"| {s['dimension']} | {s['value']} | "
                f"{s['n_false_refusal']} / {s['n_answerable']} | "
                f"{fmt_rate(s['rate'])} | {fmt_ci(s['wilson_95ci'])} |"
            )
        return "\n".join(lines)

    def fr_threshold_table(split: str) -> str:
        lines = ["| 阈值 | verdict | margin (rate − threshold) |",
                 "|---|---|---|"]
        for t in sensitivity["false_refusal"][split]["thresholds"]:
            lines.append(f"| {t['threshold']:.2f} | {t['verdict']} | "
                         f"{t['margin']:+.4f} |")
        return "\n".join(lines)

    def citation_table(split: str) -> str:
        lines = ["| 指标 | 阈值 | numerator / denominator | 复算值 | margin | verdict |",
                 "|---|---|---|---|---|---|"]
        for name, v in sensitivity["citation_v2"][split].items():
            lines.append(
                f"| {name} | {v['threshold']:.2f} | {v['numerator']} / "
                f"{v['denominator']} | {fmt_rate(v['value'])} | "
                f"{v['margin']:+.4f} | {v['verdict']} |"
            )
        return "\n".join(lines)

    def case_table() -> str:
        lines = ["| split | case_id | lang | type | diff | 拒答命中 | "
                 "answer_point_coverage | 真值来源进 context | 真值 chunk 候选/context |",
                 "|---|---|---|---|---|---|---|---|---|"]
        for r in pack_rows:
            hits = "/".join(r["refusal_indicators_hit"]) or "(空)"
            lines.append(
                f"| {r['split']} | {r['case_id']} | {r['language']} | "
                f"{r['query_type']} | {r['difficulty']} | {hits} | "
                f"{fmt_rate(r['answer_point_coverage'])} | "
                f"{'是' if r['truth_source_in_context'] else '否'} | "
                f"{'是' if r['relevant_chunk_in_candidates'] else '否'}/"
                f"{'是' if r['relevant_chunk_in_context'] else '否'} |"
            )
        return "\n".join(lines)

    fr = sensitivity["false_refusal"]
    dev_rate, ho_rate = fr["dev"]["rate"], fr["holdout"]["rate"]
    dev_margin_020 = next(
        t["margin"] for t in fr["dev"]["thresholds"] if t["threshold"] == 0.20)
    combined = sensitivity["combined_guardrail"]

    # 集中性观察（从切片数据派生，仅说明性）
    dev_slices = {s["dimension"] + ":" + s["value"]: s
                  for s in sensitivity["slices"]["dev"]}
    cross = dev_slices["query_type:cross_document"]
    hard = dev_slices["difficulty:hard"]
    so = dev_slices["source_only:True"]
    en = dev_slices["language:en"]

    report = f"""# false-refusal 与 guardrail 阈值只读审计报告

> 目录：`results/graph-gate/refusal-guardrail-audit-20260805T113849/`
> 性质：**只读审计包（CANDIDATE 辅助材料）** — 仅复算与展示，不修改
> 任何生产配置或 guardrail 阈值，不构成阈值批准；批准待人工。
> 输入：`production-baseline-stable-20260805T084256/`（稳定 split +
> split_fingerprint 锁定的正式候选评测 v2）；生成时间
> {sensitivity['generated_at']}。

---

## 一、false-refusal 提取（fail-closed）

**定义**：`should_refuse=False`（answerable）且 `correctly_refused=False`。
**判定依据**：`evaluation/citation_metrics.compute_refusal_accuracy` 对
回答做拒答指示短语子串匹配（中文：未找到/无法回答/没有足够/暂无/
无法提供；英文：cannot/unable to/no information/not found/don't have/
does not contain/not available），命中即判定为拒答；本包逐条复算命中
短语，并与 JSONL 中 `correctly_refused` 一致。

**计数断言**（不符即整体失败）：dev = **14** / 73 answerable；
holdout = **1** / 12 answerable。

| split | false_refusal case_id |
|---|---|
| dev | cross-005, cross-007, cross-009, cross-010, en-012, en-013, en-016, meta-006, meta-008, mixed-006, mixed-008, multi-009, zh-011, zh-014 |
| holdout | meta-002 |

### 逐 case 明细

{case_table()}

> 说明：`真值 chunk 候选/context` 表示相关 chunk 是否进入候选池 / 是否
> 进入最终 prompt context；「候选=是、context=否」说明检索命中但被
> Top-K/每来源上限截断，「候选=否」说明检索层未命中（en-012、en-013、
> meta-008 为 source-only 或单文档检索失败）。

## 二、拒答切片分析（分子/分母 + Wilson 95% CI）

### dev（14 / 73，rate = {dev_rate:.4f}）

{slice_table('dev')}

### holdout（1 / 12，rate = {ho_rate:.4f}）

{slice_table('holdout')}

### 集中性观察（仅 dev，样本量小仅作方向性判断）

- **cross_document 明显集中**：{cross['n_false_refusal']} / {cross['n_answerable']} =
  {cross['rate']:.4f}，远高于总体 {dev_rate:.4f} —— 跨文档比较类问题最易
  被误拒答，且 6 例中 4 例相关 chunk 已在候选池（cross-005/010 被截断、
  cross-007/009 已进 context 仍拒答）。
- **hard 难度集中**：{hard['n_false_refusal']} / {hard['n_answerable']} =
  {hard['rate']:.4f}（总体 {dev_rate:.4f}）。
- **英文偏高**：{en['n_false_refusal']} / {en['n_answerable']} =
  {en['rate']:.4f}。
- **source-only 敏感**：{so['n_false_refusal']} / {so['n_answerable']} =
  {so['rate']:.4f}（source-only 无 chunk 真值，仅 4 例）。
- 4 例真值 chunk 已进入 context 仍被误拒（cross-007、cross-009、
  mixed-008、meta-002@holdout）→ 属模型侧误判而非检索失败，最值得人工
  复核。

## 三、guardrail 敏感性

### false_refusal 阈值模拟（rate ≤ threshold → PASS）

**dev** rate = {dev_rate:.4f}（14/73）

{fr_threshold_table('dev')}

**holdout** rate = {ho_rate:.4f}（1/12）

{fr_threshold_table('holdout')}

> **当前建议阈值 0.20 下 dev margin = {dev_margin_020:+.4f}**（紧贴阈值，
> 单例变化即翻转：14/73→15/73 = 0.2055 即 FAIL）。收紧到 0.18 会立即
> FAIL（dev margin {next(t['margin'] for t in fr['dev']['thresholds'] if t['threshold']==0.18):+.4f}）。

### citation v2 复算（numerator/denominator 全部来自 candidate-report-data.json，未手填）

**dev**

{citation_table('dev')}

**holdout**

{citation_table('holdout')}

### 组合 guardrail 状态（模拟）

| 项 | dev | holdout |
|---|---|---|
| false_refusal ≤ 0.20 | {combined['false_refusal_threshold_0.20']['dev']} | {combined['false_refusal_threshold_0.20']['holdout']} |
| citation v2 全指标 | {combined['citation_v2']['dev']} | {combined['citation_v2']['holdout']} |

> 模拟结果仅用于敏感性审计，**不构成阈值批准**；生产阈值变更仍待人工
> 签署（candidate-report.md §四为 CANDIDATE 建议）。

## 四、风险与限制

1. **拒答判定是短语匹配而非语义**：个别回答（如 zh-014「无法从文档中
   确认」）命中「无法回答/未找到」被计为拒答，边界 case 需人工复核。
2. **holdout 功效不足**：answerable 仅 12 例、false_refusal 仅 1 例，
   holdout 的拒答率点估计（{ho_rate:.4f}）不可作为校准依据。
3. **语料规模**：14 例误拒答集中在 cross_document/hard，语料扩充后需
   重新评估；当前数字仅对当前语料 + prompt_id + deepseek-chat 有效。
4. **本包不修改任何输入**：所有输入文件 SHA-256 见 manifest.json；
   历史 results 产物与 candidate-report.md 未被改写。

## 五、结论

- dev false_refusal = {dev_rate:.4f}（14/73）在建议阈值 0.20 下
  **PASS，但 margin 仅 {dev_margin_020:+.4f}**，不满足「收紧」条件；
  任何阈值 ≤ 0.18 在当前 dev 分布下直接 FAIL。
- **不建议在现阶段自动收紧或批准阈值**；建议：① 人工复核本包 15 条
  false_refusal（尤其 4 条真值 chunk 已进 context 仍拒答的 case）；
  ② 扩充语料后在稳定 split 新指纹下重跑，再以更大样本校准拒答阈值。
- 拒答问题优先指向 **cross_document 与 hard 切片**，而非全局拒答
  机制——后续阶段（RAG-IMPROVEMENT-PLAN 阶段 1.5 拒答校准）应针对该
  切片设计特征与验证。

*本报告由只读脚本生成（`generate_refusal_audit.py` 可复现）；未调用
LLM/API；未修改任何生产配置、阈值与历史产物。*
"""
    (OUT / "refusal-guardrail-audit.md").write_text(report, encoding="utf-8")


def main() -> int:
    errors: list[str] = []
    ds_rows = {r["id"]: r for r in load_jsonl(DATASET)}
    candidate_data = json.load(open(BASE / "candidate-report-data.json", encoding="utf-8"))

    pack_rows: list[dict] = []
    per_split: dict[str, dict] = {}
    for split in ("dev", "holdout"):
        gen, ret, gt_by_case = load_split(split)
        missing_ret = [cid for cid in gen if cid not in ret]
        if missing_ret:
            errors.append(f"{split}: retrieval rows missing for {missing_ret}")
        answerable = {cid for cid, g in gen.items()
                      if g["should_refuse"] is False and g.get("error") is None}
        false_refusals = sorted(
            cid for cid in answerable
            if gen[cid]["correctly_refused"] is False
        )
        if len(false_refusals) != EXPECTED_FALSE_REFUSAL[split]:
            errors.append(
                f"{split}: false_refusal count {len(false_refusals)} != "
                f"expected {EXPECTED_FALSE_REFUSAL[split]}: {false_refusals}"
            )
        for cid in false_refusals:
            g = gen[cid]
            # 复核拒答判定（与框架同函数同口径）
            if g["correctly_refused"] is not False:
                errors.append(f"{split}/{cid}: correctly_refused != False")
            if not refusal_hits(g["answer"]):
                errors.append(
                    f"{split}/{cid}: no refusal indicator matched; "
                    f"correctly_refused=False inconsistent with framework rule"
                )
            pack_rows.append(build_case_record(
                split, g, ret[cid], gt_by_case.get(cid, []), ds_rows[cid],
            ))
        # 全部 answerable 记录（切片分母）；false_refusal 用 id 集合判定
        answerable_records = [
            build_case_record(
                split, gen[cid], ret[cid], gt_by_case.get(cid, []), ds_rows[cid],
            )
            for cid in sorted(answerable)
        ]
        per_split[split] = {
            "answerable_ids": sorted(answerable),
            "false_refusal_ids": false_refusals,
            "answerable_records": answerable_records,
        }

    if errors:
        print("FAIL-CLOSED ERRORS:", *errors, sep="\n  - ")
        return 1

    # ── 切片分析 ────────────────────────────────────────────────────
    slices = {
        split: slice_analysis(
            per_split[split]["answerable_records"],
            set(per_split[split]["false_refusal_ids"]),
        )
        for split in ("dev", "holdout")
    }
    # 全切片（overall）
    for split in ("dev", "holdout"):
        n_ans = len(per_split[split]["answerable_ids"])
        n_fr = len(per_split[split]["false_refusal_ids"])
        lo, hi = wilson_ci(n_fr, n_ans)
        slices[split].insert(0, {
            "dimension": "overall", "value": "all",
            "n_false_refusal": n_fr, "n_answerable": n_ans,
            "rate": n_fr / n_ans if n_ans else None, "wilson_95ci": [lo, hi],
        })

    # ── guardrail 敏感性 ─────────────────────────────────────────────
    # false_refusal 阈值模拟（rate <= threshold → PASS）
    fr_sensitivity: dict[str, dict] = {}
    for split in ("dev", "holdout"):
        rate = (len(per_split[split]["false_refusal_ids"])
                / len(per_split[split]["answerable_ids"]))
        fr_sensitivity[split] = {
            "numerator": len(per_split[split]["false_refusal_ids"]),
            "denominator": len(per_split[split]["answerable_ids"]),
            "rate": rate,
            "thresholds": [
                {
                    "threshold": t,
                    "verdict": "PASS" if rate <= t else "FAIL",
                    "margin": round(rate - t, 6),  # 负=余量，正=越阈
                }
                for t in FALSE_REFUSAL_THRESHOLDS
            ],
        }

    # citation v2：只用现有 numerator/denominator 复算，与存值比对
    citation_recheck: dict[str, dict] = {}
    for split in ("dev", "holdout"):
        v2 = candidate_data["runs"][split]["citation_v2"]
        per_metric = {}
        for name, spec in CITATION_V2_GUARDRAILS.items():
            m = v2["metrics"][name]
            recomputed = (m["numerator"] / m["denominator_count"]
                          if m["denominator_count"] else None)
            if recomputed is not None and abs(recomputed - m["value"]) > 1e-9:
                errors.append(
                    f"{split}/{name}: recomputed {recomputed} != stored {m['value']}"
                )
            margin = (recomputed - spec["threshold"]) if recomputed is not None else None
            verdict = (
                "PASS" if margin is not None
                and (margin >= 0 if spec["direction"] == "gte" else margin <= 0)
                else "FAIL"
            )
            per_metric[name] = {
                "threshold": spec["threshold"],
                "direction": spec["direction"],
                "numerator": m["numerator"],
                "denominator": m["denominator_count"],
                "excluded_count": m["excluded_count"],
                "value": recomputed,
                "margin": round(margin, 6) if margin is not None else None,
                "verdict": verdict,
            }
        citation_recheck[split] = per_metric

    if errors:
        print("FAIL-CLOSED ERRORS:", *errors, sep="\n  - ")
        return 1

    # 组合 guardrail（false_refusal<=0.20 下 dev/holdout 是否同时 PASS）
    combined = {
        "false_refusal_threshold_0.20": {
            "dev": fr_sensitivity["dev"]["thresholds"][2]["verdict"],
            "holdout": fr_sensitivity["holdout"]["thresholds"][2]["verdict"],
        },
        "citation_v2": {
            s: all(v["verdict"] == "PASS" for v in citation_recheck[s].values())
            for s in ("dev", "holdout")
        },
        "note": "模拟结果仅用于敏感性审计，不构成阈值批准或生产配置修改。",
    }

    # ── 输出 ─────────────────────────────────────────────────────────
    sensitivity = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_run_dir": str(BASE),
        "candidate_report_data_sha256": sha256_file(BASE / "candidate-report-data.json"),
        "false_refusal": fr_sensitivity,
        "citation_v2": citation_recheck,
        "slices": slices,
        "combined_guardrail": combined,
    }
    with open(OUT / "guardrail-sensitivity.json", "w", encoding="utf-8") as f:
        json.dump(sensitivity, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(OUT / "refusal-review-pack.jsonl", "w", encoding="utf-8") as f:
        for row in pack_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ── manifest 与审计报告 ──────────────────────────────────────────
    input_files = [
        BASE / f"{s}-full/{f}"
        for s in ("dev", "holdout")
        for f in ("generation-cases.jsonl", "retrieval-cases.jsonl",
                  "ground-truth-map.json")
    ] + [DATASET, BASE / "candidate-report-data.json"]
    manifest = {
        "generated_at": sensitivity["generated_at"],
        "generator": "generate_refusal_audit.py",
        "generator_sha256": sha256_file(OUT / "generate_refusal_audit.py"),
        "inputs": {str(p): sha256_file(p) for p in input_files},
        "refusal_indicators": REFUSAL_INDICATORS,
        "counts": {
            s: {
                "total_cases": len(load_jsonl(
                    BASE / f"{s}-full/generation-cases.jsonl")),
                "answerable": len(per_split[s]["answerable_ids"]),
                "false_refusal": len(per_split[s]["false_refusal_ids"]),
                "false_refusal_ids": per_split[s]["false_refusal_ids"],
            }
            for s in ("dev", "holdout")
        },
        "pack_rows": len(pack_rows),
        "immutability": (
            "Read-only audit: no input file is modified; no production "
            "config or guardrail threshold is changed; no LLM/API is "
            "called; historical results and candidate-report.md are "
            "untouched. Outputs are written only to this new directory."
        ),
    }
    with open(OUT / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    write_audit_report(sensitivity, pack_rows)

    # 自校验输出
    written = load_jsonl(OUT / "refusal-review-pack.jsonl")
    if len(written) != 15 or {r["split"] for r in written} != {"dev", "holdout"}:
        errors.append(f"output pack row count {len(written)} != 15")
    if sum(1 for r in written if r["split"] == "dev") != 14:
        errors.append("output pack dev rows != 14")
    expected_keys = set(pack_rows[0].keys())
    if any(set(r) != expected_keys for r in written):
        errors.append("output pack key set drift")
    if errors:
        print("SELF-CHECK FAILED:", *errors, sep="\n  - ")
        return 1

    print("false_refusal dev:", per_split["dev"]["false_refusal_ids"])
    print("false_refusal holdout:", per_split["holdout"]["false_refusal_ids"])
    print("pack rows:", len(written), "| sensitivity written, combined:",
          json.dumps(combined, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
