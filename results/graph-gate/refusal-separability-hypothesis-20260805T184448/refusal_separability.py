"""阶段 1.5 特征化拒答 —— 假设生成审计（HYPOTHESIS_GENERATING_ONLY）。

**本模块只生成假设与描述性统计，不做任何规则筛选/验证/预注册：**

- 特征字典与特征表：仅依赖运行时可获得的记录检索信号
  （retrieval-cases.jsonl），评测标签（should_refuse / relevant_* /
  query_type / difficulty / review 等）严禁作为特征（标签隔离
  fail-closed，测试守护）；
- 全规则枚举（dev 拒答子集，≤2 特征）：一元 >=/<=、一元区间、
  二元 AND/OR、atom∨range / atom∧range，按放行签名去重汇总，
  输出描述性指标（FR/SR 放行数、precision/recall）；
- PR 曲线（拒答子集按一元特征排序）；
- 与 0.03 baseline 的净变化（新拒答报告）。

**已知限制（如实报告，不回避）**：
- 两特征复合规则为 post-hoc 假设（4 FR / 6 SR 上穷举，无独立验证）；
- 现有 stable holdout 已被探索性查看，不能用于确认（仅记录特征，
  不参与枚举与评估）；
- 样本仅 4 FR / 6 SR，不足以验证复合门控；
- 未来协议（仅记录）：扩充语料后 dev 内嵌套 GroupKFold（训练折选
  规则 → 验证折评估），规则固定后仅在全新 holdout 评估一次，再决定
  是否开展 LLM 受控实验。

零 LLM 调用；不修改生产逻辑/默认配置/数据集/真值；不 stage/commit。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

STATUS = "HYPOTHESIS_GENERATING_ONLY"
BASELINE_THRESHOLD = 0.03

# 评测/真值字段：严禁作为运行时特征（标签隔离）
FORBIDDEN_FEATURE_KEYS = {
    "should_refuse",
    "has_chunk_truth",
    "relevant_chunk_ids",
    "relevant_source_ids",
    "query_type",
    "language",
    "difficulty",
    "case_id",
}

# 特征字典（有方差的记录信号才用于枚举）
FEATURE_DEFS: list[dict[str, Any]] = [
    {"name": "top1", "description": "最高候选分数", "source": "candidate_scores"},
    {"name": "top2", "description": "第二高候选分数", "source": "candidate_scores"},
    {"name": "top3", "description": "第三高候选分数", "source": "candidate_scores"},
    {"name": "gap12", "description": "top1 − top2 分数差", "source": "candidate_scores"},
    {"name": "mean5", "description": "前 5 个候选分数均值", "source": "candidate_scores"},
    {"name": "mean10", "description": "前 10 个候选分数均值", "source": "candidate_scores"},
    {"name": "mean_all", "description": "全部候选分数均值", "source": "candidate_scores"},
    {"name": "std_all", "description": "全部候选分数总体标准差", "source": "candidate_scores"},
    {"name": "count_ge_001", "description": "分数 ≥ 0.01 的候选数", "source": "candidate_scores"},
    {"name": "count_ge_002", "description": "分数 ≥ 0.02 的候选数", "source": "candidate_scores"},
    {"name": "count_ge_0025", "description": "分数 ≥ 0.025 的候选数", "source": "candidate_scores"},
    {"name": "n_candidate_sources", "description": "候选去重来源数", "source": "candidate_source_ids"},
    {"name": "n_candidates", "description": "候选 chunk 数", "source": "candidate_scores", "note": "恒定 70（不可区分）"},
    {"name": "n_context_sources", "description": "context 去重来源数", "source": "context_source_ids", "note": "拒答 case 恒 0"},
    {"name": "n_context_chunks", "description": "context chunk 数", "source": "context_chunk_ids", "note": "拒答 case 恒 0"},
    {"name": "context_tokens", "description": "context token 数", "source": "context_token_count", "note": "拒答 case 恒 0"},
    {"name": "rewrite_flag", "description": "rewrite 是否发生（ms>0）", "source": "rewrite_ms", "note": "本运行恒 False（不可区分）"},
    {"name": "decompose_flag", "description": "decompose 是否发生（ms>0）", "source": "decompose_ms", "note": "本运行恒 True"},
    {"name": "subquery_count", "description": "QueryPlan 子查询数量", "source": "未记录", "recorded": False},
    {"name": "per_source_chunk_max", "description": "每来源最大 chunk 数", "source": "未记录（无 chunk→source 映射）", "recorded": False},
]

# 参与枚举的有方差特征
ENUMERATION_FEATURES = [
    "top1", "top2", "top3", "gap12", "mean5", "mean10", "mean_all",
    "std_all", "count_ge_001", "count_ge_002", "count_ge_0025",
    "n_candidate_sources",
]


def _scores(row: dict) -> list[float]:
    return row.get("candidate_scores") or []


def refused_at(scores: Sequence[float], threshold: float = BASELINE_THRESHOLD) -> bool:
    """与 src.rag.retrieval_refused 同语义：空分数或 max < threshold。"""
    return not scores or max(scores) < threshold


# ── 特征提取 ────────────────────────────────────────────────────────

def extract_features(row: dict) -> dict[str, Any]:
    """确定性提取每 case 的运行时特征（不包含任何评测标签字段）。"""
    scores = sorted(_scores(row), reverse=True)
    n = len(scores)
    f: dict[str, Any] = {
        "top1": scores[0] if n else None,
        "top2": scores[1] if n > 1 else None,
        "top3": scores[2] if n > 2 else None,
        "gap12": (scores[0] - scores[1]) if n > 1 else None,
        "mean5": (sum(scores[:5]) / min(5, n)) if n else None,
        "mean10": (sum(scores[:10]) / min(10, n)) if n else None,
        "mean_all": (statistics.fmean(scores)) if n else None,
        "std_all": (statistics.pstdev(scores) if n > 1 else 0.0) if n else None,
        "count_ge_001": sum(1 for x in scores if x >= 0.01),
        "count_ge_002": sum(1 for x in scores if x >= 0.02),
        "count_ge_0025": sum(1 for x in scores if x >= 0.025),
        "n_candidates": n,
        "n_candidate_sources": len(row.get("candidate_source_ids") or []),
        "n_context_sources": len(row.get("context_source_ids") or []),
        "n_context_chunks": len(row.get("context_chunk_ids") or []),
        "context_tokens": row.get("context_token_count", 0),
        "rewrite_flag": bool((row.get("rewrite_ms") or 0.0) > 0),
        "decompose_flag": bool((row.get("decompose_ms") or 0.0) > 0),
        "subquery_count": None,      # 未记录
        "per_source_chunk_max": None,  # 未记录（无 chunk→source 映射）
    }
    return f


def check_label_isolation(features: dict[str, Any]) -> list[str]:
    """特征字典含评测字段 → 返回违规键列表（fail-closed，测试守护）。

    覆盖：FORBIDDEN_FEATURE_KEYS 精确键 + review_* 前缀（人工审阅标记）。
    """
    return sorted(
        k for k in features
        if k in FORBIDDEN_FEATURE_KEYS
        or k.lower().startswith("review")
    )


def label_of(row: dict) -> str:
    """离线标签（仅用于描述性统计，绝不进入特征）：拒答子集分组。"""
    if not refused_at(_scores(row)):
        return "BASELINE_RELEASED"
    return "FR" if not row["should_refuse"] else "SR"


# ── 阈值网格 ────────────────────────────────────────────────────────

def threshold_grid(values: Iterable[float | None]) -> list[float]:
    """确定性网格：去重升序观测值 + 相邻中点。"""
    uniq = sorted({v for v in values if v is not None})
    grid: list[float] = []
    for i, v in enumerate(uniq):
        grid.append(v)
        if i + 1 < len(uniq):
            grid.append((v + uniq[i + 1]) / 2.0)
    return grid


# ── 规则族（≤2 特征，可解释） ───────────────────────────────────────

@dataclass(frozen=True)
class Atom:
    feature: str
    op: str  # ">=" | "<="
    value: float

    def applies(self, feats: dict[str, Any]) -> bool:
        v = feats.get(self.feature)
        if v is None:
            return False  # fail-closed：无值不成立
        return v >= self.value if self.op == ">=" else v <= self.value

    def canonical(self) -> str:
        return f"{self.feature} {self.op} {self.value!r}"


@dataclass(frozen=True)
class Range:
    feature: str
    lo: float
    hi: float

    def applies(self, feats: dict[str, Any]) -> bool:
        v = feats.get(self.feature)
        if v is None:
            return False
        return self.lo <= v <= self.hi

    def canonical(self) -> str:
        return f"({self.feature} >= {self.lo!r} AND {self.feature} <= {self.hi!r})"


@dataclass(frozen=True)
class Rule:
    parts: tuple[Atom | Range, ...]
    combine: str | None = None  # None | "AND" | "OR"

    def applies(self, feats: dict[str, Any]) -> bool:
        results = [p.applies(feats) for p in self.parts]
        if self.combine == "AND":
            return all(results)
        if self.combine == "OR":
            return any(results)
        return results[0]

    def features(self) -> tuple[str, ...]:
        return tuple(sorted({p.feature for p in self.parts}))

    def canonical(self) -> str:
        if len(self.parts) == 1:
            return self.parts[0].canonical()
        return f" {self.combine} ".join(p.canonical() for p in self.parts)


# ── 描述性指标（非门槛） ────────────────────────────────────────────

def evaluate_rule(rule: Rule, refused_rows: Sequence[dict],
                  features_by_id: dict[str, dict] | None = None) -> dict[str, Any]:
    """拒答子集上的描述性指标：FR/SR 放行数与 precision/recall（不判定）。"""
    if features_by_id is None:
        features_by_id = {r["case_id"]: extract_features(r) for r in refused_rows}
    released = [
        r for r in refused_rows
        if rule.applies(features_by_id[r["case_id"]])
    ]
    fr_ids = sorted(r["case_id"] for r in released if not r["should_refuse"])
    sr_ids = sorted(r["case_id"] for r in released if r["should_refuse"])
    n_fr = sum(1 for r in refused_rows if not r["should_refuse"])
    n_rel = len(released)
    return {
        "released_fr_ids": fr_ids,
        "released_sr_ids": sr_ids,
        "fr_released": len(fr_ids),
        "sr_released": len(sr_ids),
        "n_fr_total": n_fr,
        "n_sr_total": len(refused_rows) - n_fr,
        "precision": (len(fr_ids) / n_rel) if n_rel else 0.0,
        "recall": (len(fr_ids) / n_fr) if n_fr else 0.0,
    }


def net_change_vs_baseline(rule: Rule, all_rows: Sequence[dict],
                           features_by_id: dict[str, dict] | None = None) -> dict[str, Any]:
    """与 0.03 baseline 的净变化：新拒答（baseline 放行而规则拒答）。"""
    if features_by_id is None:
        features_by_id = {r["case_id"]: extract_features(r) for r in all_rows}
    newly = [
        r for r in all_rows
        if not refused_at(_scores(r))
        and not rule.applies(features_by_id[r["case_id"]])
    ]
    return {
        "newly_refused_answerable": sorted(
            r["case_id"] for r in newly if not r["should_refuse"]),
        "newly_refused_sr": sorted(
            r["case_id"] for r in newly if r["should_refuse"]),
        "n_newly_refused": len(newly),
    }


# ── 全规则枚举（假设生成） ──────────────────────────────────────────

def _conditions(refused_rows: Sequence[dict],
                features_by_id: dict[str, dict]) -> list[Atom | Range]:
    """条件集：一元 >=/<=（观测值+中点）+ 一元区间（观测值对）。"""
    atoms: list[Atom] = []
    ranges: list[Range] = []
    for feat in ENUMERATION_FEATURES:
        values = [
            features_by_id[r["case_id"]].get(feat) for r in refused_rows
        ]
        grid = threshold_grid(values)
        for t in grid:
            atoms.append(Atom(feat, ">=", t))
            atoms.append(Atom(feat, "<=", t))
        uniq = sorted({v for v in values if v is not None})
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                if uniq[i] < uniq[j]:
                    ranges.append(Range(feat, uniq[i], uniq[j]))
    return atoms + ranges


def enumerate_rules(
    refused_rows: Sequence[dict],
    features_by_id: dict[str, dict] | None = None,
    max_examples: int = 5,
) -> dict[str, Any]:
    """全规则枚举（仅拒答子集；非拒答行 fail-closed 拒绝）。

    按放行签名（released FR ids, released SR ids）去重汇总：
    每个签名输出 fr/sr 放行数、precision/recall、命中规则数与代表规则。
    结果**仅为假设**（post-hoc，未验证），不做任何合格判定。
    """
    if features_by_id is None:
        features_by_id = {r["case_id"]: extract_features(r) for r in refused_rows}
    non_refused = [
        r["case_id"] for r in refused_rows
        if not refused_at(_scores(r))
    ]
    if non_refused:
        raise ValueError(
            f"enumerate_rules requires the baseline-refused population only; "
            f"found non-refused: {non_refused} (fail-closed)",
        )
    if check_label_isolation(next(iter(features_by_id.values()))):
        raise ValueError("label fields leaked into features (fail-closed)")

    # 预计算每条件放行集（避免重复求值）
    conds = _conditions(refused_rows, features_by_id)
    cond_by_canonical: dict[str, Atom | Range] = {
        c.canonical(): c for c in conds
    }
    cond_sets: dict[str, tuple[frozenset, frozenset]] = {}
    for c in conds:
        fr = frozenset(
            r["case_id"] for r in refused_rows
            if not r["should_refuse"] and c.applies(features_by_id[r["case_id"]])
        )
        sr = frozenset(
            r["case_id"] for r in refused_rows
            if r["should_refuse"] and c.applies(features_by_id[r["case_id"]])
        )
        cond_sets[c.canonical()] = (fr, sr)

    sig: dict[tuple, dict[str, Any]] = {}
    all_conds = sorted(cond_sets)

    def add_rule(rule: Rule, fr: frozenset, sr: frozenset) -> None:
        key = (tuple(sorted(fr)), tuple(sorted(sr)))
        entry = sig.setdefault(key, {
            "released_fr_ids": sorted(fr),
            "released_sr_ids": sorted(sr),
            "fr_released": len(fr),
            "sr_released": len(sr),
            "n_fr_total": sum(1 for r in refused_rows if not r["should_refuse"]),
            "n_sr_total": sum(1 for r in refused_rows if r["should_refuse"]),
            "rule_count": 0,
            "examples": [],
        })
        entry["rule_count"] += 1
        if len(entry["examples"]) < max_examples:
            entry["examples"].append(rule.canonical())

    # 一元与区间
    for name in all_conds:
        fr, sr = cond_sets[name]
        add_rule(Rule((cond_by_canonical[name],), None), fr, sr)
    # 二元 AND/OR（含 atom∨range / atom∧range）
    for i in range(len(all_conds)):
        for j in range(i + 1, len(all_conds)):
            a, b = all_conds[i], all_conds[j]
            fr_a, sr_a = cond_sets[a]
            fr_b, sr_b = cond_sets[b]
            add_rule(Rule((cond_by_canonical[a], cond_by_canonical[b]), "AND"),
                     fr_a & fr_b, sr_a & sr_b)
            add_rule(Rule((cond_by_canonical[a], cond_by_canonical[b]), "OR"),
                     fr_a | fr_b, sr_a | sr_b)

    entries = list(sig.values())
    for e in entries:
        n_rel = e["fr_released"] + e["sr_released"]
        e["precision"] = (e["fr_released"] / n_rel) if n_rel else 0.0
        e["recall"] = (
            e["fr_released"] / e["n_fr_total"]) if e["n_fr_total"] else 0.0
        e["examples"].sort()
    entries.sort(key=lambda e: (-e["fr_released"], e["sr_released"],
                                -e["rule_count"]))
    return {
        "status": STATUS,
        "caveat": "post-hoc hypotheses enumerated on the baseline-refused "
                  "population (4 FR / 6 SR); unvalidated; NOT qualified "
                  "candidates; no gates applied",
        "baseline_threshold": BASELINE_THRESHOLD,
        "n_refused": len(refused_rows),
        "n_fr_total": sum(1 for r in refused_rows if not r["should_refuse"]),
        "n_sr_total": sum(1 for r in refused_rows if r["should_refuse"]),
        "n_rules_enumerated": sum(e["rule_count"] for e in entries),
        "n_signatures": len(entries),
        "signatures": entries,
    }


# ── PR 曲线 ─────────────────────────────────────────────────────────

def pr_curve(refused_rows: Sequence[dict],
             feature: str,
             direction: str = "desc",
             features_by_id: dict[str, dict] | None = None) -> list[dict[str, Any]]:
    """拒答子集按单特征排序的 PR 点（描述性，非门槛）。

    desc：放行 = 特征值 ≥ 阈值；asc：放行 = 特征值 ≤ 阈值。
    """
    if features_by_id is None:
        features_by_id = {r["case_id"]: extract_features(r) for r in refused_rows}
    scored = [
        (features_by_id[r["case_id"]].get(feature), r)
        for r in refused_rows
    ]
    scored = [p for p in scored if p[0] is not None]
    reverse = direction == "desc"
    scored.sort(key=lambda p: p[0], reverse=reverse)
    n_fr = sum(1 for _, r in scored if not r["should_refuse"])
    points: list[dict[str, Any]] = []
    fr_hit = 0
    for i, (value, _) in enumerate(scored):
        r = scored[i][1]
        if not r["should_refuse"]:
            fr_hit += 1
        points.append({
            "threshold": value,
            "n_released": i + 1,
            "fr_hit": fr_hit,
            "precision": (fr_hit / (i + 1)),
            "recall": (fr_hit / n_fr) if n_fr else 0.0,
        })
    return points


# ── ASCII 可视化（matplotlib 不可用，不引入依赖） ───────────────────

def ascii_scatter(points: Sequence[tuple[str, float, float]],
                  width: int = 50, height: int = 12) -> str:
    """确定性 ASCII 散点：points = [(label, x, y)]；'*' = 重叠单元。"""
    if not points:
        return "(empty)"
    xs = [p[1] for p in points]
    ys = [p[2] for p in points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    padx = (x1 - x0) * 0.08 if x1 > x0 else 0.001
    pady = (y1 - y0) * 0.08 if y1 > y0 else 0.001
    x0, x1 = x0 - padx, x1 + padx
    y0, y1 = y0 - pady, y1 + pady
    grid = [["."] * width for _ in range(height)]
    for label, x, y in sorted(points, key=lambda p: (p[0], p[1])):
        c = min(width - 1, int((x - x0) / (x1 - x0) * (width - 1)))
        r = min(height - 1, int((y - y0) / (y1 - y0) * (height - 1)))
        r = height - 1 - r
        marker = label[0].upper()
        grid[r][c] = "*" if grid[r][c] != "." else marker
    lines = [f"y: [{y0:.5f}, {y1:.5f}]"]
    lines += ["  |" + "".join(row) for row in grid]
    lines.append(f"  L----x: [{x0:.5f}, {x1:.5f}]")
    # 图例：标记 → 标签（确定性排序）
    legend = {p[0][0].upper(): p[0] for p in sorted(points, key=lambda p: p[0])}
    lines.append("legend: " + "; ".join(
        f"{k}={v}" for k, v in sorted(legend.items())))
    return "\n".join(lines)


# ── 报告渲染 ────────────────────────────────────────────────────────

def _fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:.5f}"


def render_separability_report(
    dev_rows: list[dict],
    ho_rows: list[dict],
    feature_dict: dict[str, Any],
    features_by_id: dict[str, dict],
    enum: dict[str, Any],
    curves: dict[str, Any],
) -> str:
    lines = [
        "# 阶段 1.5 特征化拒答 —— 假设生成审计报告",
        "",
        f"> 状态：**{STATUS}** — 仅生成假设与描述性统计。",
        "> 不筛选规则、不预注册 LLM ablation、不使用 holdout 确认、",
        "> 不改生产逻辑；零 LLM 调用。",
        f"> dev 拒答子集：{enum['n_fr_total']} FR / {enum['n_sr_total']} SR。",
        "",
        "## 一、审计性质（必须声明）",
        "",
        "1. 本报告中的两特征复合规则均为 **post-hoc 假设**——在 "
        f"{enum['n_fr_total']} FR / {enum['n_sr_total']} SR 上穷举得到，",
        "   无独立验证；过拟合风险不可排除。",
        "2. 现有 stable holdout 已被**探索性查看**（特征已读取），",
        "   **不能用于确认**；其特征仅以 exploratory_only 角色记录。",
        "3. 当前样本仅 4 FR / 6 SR，**不足以验证复合门控**（功效不足）。",
        "4. 下一步需**扩充语料**并创建**新的、未查看的 group-aware holdout**。",
        "",
        "## 二、未来验证协议（仅记录，不实施）",
        "",
        "- 扩充语料后：dev 内**嵌套 GroupKFold**——每折只用训练折选择规则，",
        "  再在验证折评估一次；选择与评估严格分离；",
        "- 规则固定后，仅在**全新 holdout** 上评估**一次**；",
        "- 全部通过后再决定是否开展 LLM 受控实验。",
        "",
        "## 三、特征字典",
        "",
        "| 特征 | 说明 | 记录 | 有方差 | 参与枚举 |",
        "|---|---|---|---|---|",
    ]
    for d in feature_dict["features"]:
        lines.append(
            f"| {d['name']} | {d['description']} | "
            f"{'是' if d['recorded'] else '否'} | "
            f"{'是' if d['has_variance'] else '否'} | "
            f"{'是' if d['name'] in ENUMERATION_FEATURES else '否'} |",
        )
    lines += [
        "",
        "> 评测字段（should_refuse / relevant_* / query_type / difficulty /",
        "> case_id / review 等）严禁作为特征（标签隔离 fail-closed）。",
        "",
        "## 四、拒答 case 特征表",
        "",
        "| case | split | label | top1 | top2 | gap12 | mean5 | std_all | ge0.02 | nSrc |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in dev_rows + ho_rows:
        cid = r["case_id"]
        f = features_by_id.get(cid, {})
        split = "dev" if cid in {x["case_id"] for x in dev_rows} else "holdout*"
        lines.append(
            f"| {cid} | {split} | {label_of(r)} | {_fmt(f.get('top1'))} | "
            f"{_fmt(f.get('top2'))} | {_fmt(f.get('gap12'))} | "
            f"{_fmt(f.get('mean5'))} | {_fmt(f.get('std_all'))} | "
            f"{f.get('count_ge_002', 0)} | {f.get('n_candidate_sources', 0)} |",
        )
    lines += [
        "",
        "> holdout* = 已被探索性查看，仅记录特征（exploratory_only），",
        "> 不参与枚举与评估，不能用于确认。",
        "",
        "## 五、规则枚举摘要（假设，未验证）",
        "",
        f"枚举规则总数：{enum['n_rules_enumerated']}；去重放行签名："
        f"{enum['n_signatures']}。按 (FR 放行↓, SR 放行↑) 排序，下表仅展示"
        "前 30 个签名（完整清单见 rule-enumeration.json）：",
        "",
        "| FR | SR | precision | recall | 规则数 | 代表规则（前 2） |",
        "|---|---|---|---|---|---|",
    ]
    for e in enum["signatures"][:30]:
        ex = "; ".join(e["examples"][:2]) or "-"
        lines.append(
            f"| {e['fr_released']}/{e['n_fr_total']} | "
            f"{e['sr_released']}/{e['n_sr_total']} | "
            f"{e['precision']:.2f} | {e['recall']:.2f} | "
            f"{e['rule_count']} | `{ex}` |",
        )
    lines += [
        "",
        "> 上表为**假设清单**：任何一行都不构成合格候选；未应用任何门槛。",
        "",
        "## 六、PR 曲线（拒答子集，一元特征）",
        "",
    ]
    for feat in ("top1", "mean5", "std_all"):
        pts = curves["curves"][feat]["desc"]
        lines += [
            f"### {feat}（desc：放行 = 值 ≥ 阈值）",
            "",
            "| threshold | n_released | fr_hit | precision | recall |",
            "|---|---|---|---|---|",
        ]
        for p in pts:
            lines.append(
                f"| {_fmt(p['threshold'])} | {p['n_released']} | "
                f"{p['fr_hit']} | {p['precision']:.2f} | "
                f"{p['recall']:.2f} |",
            )
        lines.append("")
    lines += [
        "## 七、与 0.03 baseline 的净变化（结构性质）",
        "",
        "本枚举的规则均为「放行条件」形式；当规则含 `top1 >= t`（t ≤ 0.03）",
        "或等价宽松条件时，baseline 已放行（top1 ≥ 0.03）的 case 必然被",
        "规则放行 → **零新拒答**（单调放行）。更严规则（如 `top1 >= 0.06`）",
        "会产生新拒答——枚举输出的每签名按规则不同而异，`net-change` 仅在",
        "选定假设后逐条计算；本报告不评估任何单一规则（假设未选定）。",
        "",
        "## 八、ASCII 可视化（top1 × std_all / top1 × mean5）",
        "",
        "```",
    ]
    dev_ref = [r for r in dev_rows if label_of(r) in ("FR", "SR")]
    fmap = features_by_id
    lines.append("### top1 (x) × std_all (y)")
    lines.append(ascii_scatter([
        (f"{r['case_id']}:{label_of(r)}", fmap[r["case_id"]]["top1"],
         fmap[r["case_id"]]["std_all"])
        for r in dev_ref
    ]))
    lines.append("### top1 (x) × mean5 (y)")
    lines.append(ascii_scatter([
        (f"{r['case_id']}:{label_of(r)}", fmap[r["case_id"]]["top1"],
         fmap[r["case_id"]]["mean5"])
        for r in dev_ref
    ]))
    lines += [
        "```",
        "",
        f"*本报告由 evaluation/refusal_separability.py 生成；{STATUS}；",
        "未调用 LLM；未修改任何生产配置、阈值、数据集、真值与历史产物。*",
        "",
    ]
    return "\n".join(lines)


def render_decision_report(enum: dict[str, Any]) -> str:
    return "\n".join([
        "# 阶段 1.5 特征化拒答 —— Decision Report（假设生成审计）",
        "",
        f"> 状态：**{STATUS}**",
        "",
        "## 结论",
        "",
        "- 本次仅完成**假设生成**：特征字典、特征表、全规则枚举与描述性",
        f"  统计（{enum['n_rules_enumerated']} 条规则 → "
        f"{enum['n_signatures']} 个放行签名）。",
        "- **没有任何规则被认定为合格候选**；未应用筛选门槛；",
        "- **未生成 LLM ablation 预注册**；未修改任何生产逻辑、默认配置、",
        "  数据集与真值。",
        "",
        "## 必须声明",
        "",
        "1. 两特征复合规则为 **post-hoc 假设**（4 FR / 6 SR 穷举，未验证）；",
        "2. 现有 stable holdout 已被探索性查看，**不能用于确认**；",
        "3. 当前样本仅 4 FR / 6 SR，**不足以验证复合门控**；",
        "4. 下一步需**扩充语料**并创建**新的、未查看的 group-aware holdout**。",
        "",
        "## 未来协议（记录，不实施）",
        "",
        "- dev 内嵌套 GroupKFold：每折训练折选规则 → 验证折评估；",
        "- 规则固定后仅在全新 holdout 评估一次；",
        "- 通过后再决定 LLM 受控实验。",
        "",
        "## 建议",
        "",
        "- **扩充语料**（当前 10 条拒答样本不足以验证复合门控）；",
        "- 语料扩充后按上述协议重跑假设生成与验证；",
        "- 在此之前，生产 `DEFAULT_REFUSAL_THRESHOLD=0.03` 与基线拒答逻辑",
        "  **保持不变**。",
        "",
    ])


# ── CLI ─────────────────────────────────────────────────────────────

def _load_jsonl(path: str | Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _standard_rows(rows: list[dict]) -> list[dict]:
    """单臂检索网格：取 standard 臂（仅当存在 arm 键且多臂时过滤）。"""
    arms = sorted({r.get("arm") for r in rows if "arm" in r})
    if arms and arms != ["standard"]:
        return [r for r in rows if r.get("arm") == "standard"]
    return rows


def _sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="阶段 1.5 特征化拒答 —— 假设生成审计（只读，零 LLM）")
    ap.add_argument("--dev-retrieval", required=True,
                    help="dev 检索 JSONL（standard 臂）")
    ap.add_argument("--holdout-retrieval", default=None,
                    help="holdout 检索 JSONL（仅特征记录，exploratory_only）")
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args(argv)

    dev_rows = _standard_rows(_load_jsonl(args.dev_retrieval))
    ho_rows = (_standard_rows(_load_jsonl(args.holdout_retrieval))
               if args.holdout_retrieval else [])
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    features_by_id = {r["case_id"]: extract_features(r) for r in dev_rows + ho_rows}
    # 标签隔离 fail-closed
    for cid, feats in features_by_id.items():
        bad = check_label_isolation(feats)
        if bad:
            raise ValueError(
                f"label fields leaked into features for {cid}: {bad} "
                "(fail-closed)")

    # 特征字典（运行时方差：在拒答子集——规则作用域——上计算）
    dev_refused = [r for r in dev_rows if label_of(r) in ("FR", "SR")]
    feature_dict = {
        "status": STATUS,
        "baseline_threshold": BASELINE_THRESHOLD,
        "features": [
            {
                "name": d["name"],
                "description": d.get("description", ""),
                "source": d.get("source", ""),
                "recorded": d.get("recorded", True),
                "has_variance": len({
                    features_by_id[r["case_id"]].get(d["name"])
                    for r in dev_refused
                    if features_by_id[r["case_id"]].get(d["name"]) is not None
                }) > 1,
                "note": d.get("note", ""),
            }
            for d in FEATURE_DEFS
        ],
        "forbidden_label_fields": sorted(FORBIDDEN_FEATURE_KEYS),
    }
    (out / "feature-dictionary.json").write_text(
        json.dumps(feature_dict, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    # 特征表（标签独立列；holdout 仅 exploratory_only）
    with open(out / "features.jsonl", "w", encoding="utf-8") as f:
        for r in dev_rows + ho_rows:
            cid = r["case_id"]
            f.write(json.dumps({
                "case_id": cid,
                "split": "dev" if cid in {x["case_id"] for x in dev_rows}
                         else "holdout",
                "role": "selection_hypothesis" if cid in
                        {x["case_id"] for x in dev_rows}
                        else "exploratory_only",
                "label": label_of(r),
                "features": features_by_id[cid],
            }, ensure_ascii=False) + "\n")

    # 全规则枚举（dev 拒答子集）
    # 全规则枚举（dev 拒答子集）
    enum = enumerate_rules(dev_refused, features_by_id)
    (out / "rule-enumeration.json").write_text(
        json.dumps(enum, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # PR 曲线（一元特征，desc + asc）
    curves = {
        "status": STATUS,
        "curves": {
            feat: {
                "desc": pr_curve(dev_refused, feat, "desc", features_by_id),
                "asc": pr_curve(dev_refused, feat, "asc", features_by_id),
            }
            for feat in ENUMERATION_FEATURES
        },
    }
    (out / "pr-curves.json").write_text(
        json.dumps(curves, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = render_separability_report(
        dev_rows, ho_rows, feature_dict, features_by_id, enum, curves)
    (out / "separability-report.md").write_text(report, encoding="utf-8")
    (out / "decision-report.md").write_text(
        render_decision_report(enum), encoding="utf-8")

    inputs = {
        "dev_retrieval": {
            "path": args.dev_retrieval,
            "sha256": _sha256(args.dev_retrieval),
            "case_count": len(dev_rows),
        },
    }
    if args.holdout_retrieval:
        inputs["holdout_retrieval"] = {
            "path": args.holdout_retrieval,
            "sha256": _sha256(args.holdout_retrieval),
            "case_count": len(ho_rows),
        }
    manifest = {
        "status": STATUS,
        "inputs": inputs,
        "outputs": ["feature-dictionary.json", "features.jsonl",
                    "rule-enumeration.json", "pr-curves.json",
                    "separability-report.md", "decision-report.md",
                    "manifest.json", "run-commands.md"],
        "llm_calls": 0,
        "immutability": "read-only hypothesis generation; no production "
                        "logic/config/threshold/dataset/truth modified; "
                        "holdout used for feature records only "
                        "(exploratory_only, not confirmatory)",
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (out / "run-commands.md").write_text(
        _render_run_commands(), encoding="utf-8")

    print(f"status: {STATUS}")
    print(f"n_rules={enum['n_rules_enumerated']} "
          f"n_signatures={enum['n_signatures']} "
          f"dev_refused={len(dev_refused)} "
          f"holdout_features={len(ho_rows)} (exploratory_only)")
    print(f"outputs written to {out}")
    return 0


def _render_run_commands() -> str:
    return "\n".join([
        "# 复现命令",
        "",
        "```bash",
        "python evaluation/refusal_separability.py \\",
        "  --dev-retrieval results/graph-gate/refusal-ablation-20260805T133209/dev-full/retrieval-cases.jsonl \\",
        "  --holdout-retrieval results/graph-gate/production-baseline-stable-20260805T084256/holdout-full/retrieval-cases.jsonl \\",
        "  --output-dir <timestamped-output-dir>",
        "```",
        "",
        "产物：feature-dictionary.json / features.jsonl / rule-enumeration.json /",
        "pr-curves.json / separability-report.md / decision-report.md /",
        "manifest.json / run-commands.md（全部标记",
        "HYPOTHESIS_GENERATING_ONLY）。",
        "",
    ])


if __name__ == "__main__":
    raise SystemExit(main())
