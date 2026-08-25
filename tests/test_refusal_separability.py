"""阶段 1.5 特征化拒答 —— 假设生成审计（HGA）单元测试。

覆盖：特征提取确定性、标签隔离（fail-closed，禁用键不得成为特征）、
阈值网格、规则族（一元/区间/二元 AND/OR/atom∨range）求值与 canonical
串、拒答子集描述性指标、签名去重枚举、PR 曲线、与 baseline 净变化
（新拒答报告）、holdout 不入枚举、输出 HYPOTHESIS_GENERATING_ONLY
标记、ASCII 可视化确定性。
"""

import json

import pytest

from evaluation.refusal_separability import (
    STATUS,
    Atom,
    Range,
    Rule,
    ascii_scatter,
    check_label_isolation,
    enumerate_rules,
    evaluate_rule,
    extract_features,
    label_of,
    net_change_vs_baseline,
    pr_curve,
    threshold_grid,
)


def mk_row(case_id, should_refuse, scores, sources=None, **extra):
    """构造 retrieval-case 行（含评测字段，验证它们不进特征）。"""
    row = {
        "case_id": case_id,
        "should_refuse": should_refuse,
        "candidate_scores": list(scores),
        "candidate_source_ids": sources or [f"s{i}" for i in range(len(scores))],
        "context_source_ids": [],
        "context_chunk_ids": [],
        "context_token_count": 0,
        "rewrite_ms": 0.0,
        "decompose_ms": 600.0,
        "query_type": "single_fact",
        "language": "en",
        "difficulty": "medium",
        "has_chunk_truth": True,
        "relevant_chunk_ids": ["c1"],
        "relevant_source_ids": ["s1"],
        "review_status": "confirmed",
        **extra,
    }
    return row


# ── 特征提取 ────────────────────────────────────────────────────────

def test_extract_features_deterministic():
    row = mk_row("x-1", False, [0.0299, 0.0280, 0.0210, 0.0190, 0.0180])
    assert extract_features(row) == extract_features(row)


def test_extract_features_score_derived():
    feats = extract_features(mk_row("x-1", False, [0.03, 0.02, 0.01]))
    assert feats["top1"] == 0.03
    assert feats["top2"] == 0.02
    assert feats["top3"] == 0.01
    assert feats["gap12"] == pytest.approx(0.01)
    assert feats["mean5"] == pytest.approx(0.02)
    assert feats["mean_all"] == pytest.approx(0.02)
    assert feats["count_ge_002"] == 2
    assert feats["count_ge_0025"] == 1
    assert feats["n_candidates"] == 3


def test_extract_features_empty_scores_none_safe():
    feats = extract_features(mk_row("x-1", True, []))
    assert feats["top1"] is None
    assert feats["gap12"] is None
    assert feats["mean_all"] is None
    assert feats["count_ge_002"] == 0


def test_features_exclude_forbidden_label_fields():
    """评测字段（should_refuse/query_type/difficulty/relevant_*/review/case_id）
    不得出现在特征字典中（标签隔离，fail-closed）。"""
    row = mk_row("x-1", True, [0.02])
    feats = extract_features(row)
    for key in ("should_refuse", "query_type", "language", "difficulty",
                "has_chunk_truth", "relevant_chunk_ids", "relevant_source_ids",
                "case_id", "review_status"):
        assert key not in feats, f"label field leaked into features: {key}"


def test_check_label_isolation_flags_forbidden():
    """显式校验：特征字典含禁用键 → 报告违规（fail-closed）。"""
    feats = extract_features(mk_row("x-1", False, [0.02]))
    assert check_label_isolation(feats) == []
    bad = dict(feats)
    bad["should_refuse"] = True
    bad["review_status"] = "confirmed"
    violations = check_label_isolation(bad)
    assert sorted(violations) == ["review_status", "should_refuse"]


def test_unrecorded_features_marked_unavailable():
    """subquery_count / per_source_chunk_max 未被记录 → None + available=False。"""
    feats = extract_features(mk_row("x-1", False, [0.02]))
    assert feats["subquery_count"] is None
    assert feats["per_source_chunk_max"] is None


# ── 离线标签 ────────────────────────────────────────────────────────

def test_label_of_groups():
    assert label_of(mk_row("a", False, [0.026])) == "FR"      # 前哨 FR
    assert label_of(mk_row("b", True, [0.026])) == "SR"       # 正确拒答
    assert label_of(mk_row("c", False, [0.031])) == "BASELINE_RELEASED"
    assert label_of(mk_row("d", True, [])) == "SR"            # 空分数仍拒答


# ── 阈值网格 ────────────────────────────────────────────────────────

def test_threshold_grid_values_and_midpoints():
    grid = threshold_grid([0.02, 0.01, 0.02, 0.03])
    assert grid == [0.01, 0.015, 0.02, 0.025, 0.03]
    assert threshold_grid([0.02, 0.01]) == threshold_grid([0.02, 0.01])


def test_threshold_grid_empty_and_none():
    assert threshold_grid([]) == []
    assert threshold_grid([None, 0.05]) == [0.05]


# ── 规则族 ──────────────────────────────────────────────────────────

def test_rule_unary_applies():
    feats = {"top1": 0.027, "std_all": 0.003}
    assert Rule((Atom("top1", ">=", 0.026),), None).applies(feats)
    assert not Rule((Atom("top1", ">=", 0.028),), None).applies(feats)
    assert Rule((Atom("top1", "<=", 0.028),), None).applies(feats)
    assert not Rule((Atom("top1", "<=", 0.026),), None).applies(feats)


def test_rule_range_inclusive_bounds():
    feats = {"std_all": 0.00314}
    assert Rule((Range("std_all", 0.00298, 0.00339),), None).applies(feats)
    assert Rule((Range("std_all", 0.00314, 0.00339),), None).applies(feats)
    assert not Rule((Range("std_all", 0.0032, 0.00339),), None).applies(feats)


def test_rule_binary_and_or():
    feats = {"top1": 0.028, "std_all": 0.003}
    r_and = Rule((Atom("top1", ">=", 0.026), Range("std_all", 0.0029, 0.0035)), "AND")
    r_or = Rule((Atom("top1", ">=", 0.026), Range("std_all", 0.0029, 0.0035)), "OR")
    assert r_and.applies(feats)
    assert r_or.applies(feats)
    feats2 = {"top1": 0.02, "std_all": 0.003}
    assert not r_and.applies(feats2)
    assert r_or.applies(feats2)  # OR 分支放行


def test_rule_none_feature_fails_closed():
    """特征值为 None（如空分数）→ 任何条件不成立（fail-closed 不误放行）。"""
    feats = {"top1": None, "std_all": None}
    assert not Rule((Atom("top1", ">=", 0.01),), None).applies(feats)
    assert not Rule((Range("std_all", 0.0, 1.0),), None).applies(feats)


def test_rule_canonical_string():
    r = Rule((Atom("top1", ">=", 0.0274),
              Range("std_all", 0.00298, 0.00339)), "OR")
    assert r.canonical() == "top1 >= 0.0274 OR (std_all >= 0.00298 AND std_all <= 0.00339)"
    assert Rule((Atom("top1", ">=", 0.026),), None).canonical() == "top1 >= 0.026"


# ── 描述性指标（非门槛） ────────────────────────────────────────────

def test_evaluate_rule_metrics():
    rows = [
        mk_row("f1", False, [0.028]),
        mk_row("f2", False, [0.0265]),
        mk_row("s1", True, [0.026]),
        mk_row("s2", True, [0.024]),
    ]
    rule = Rule((Atom("top1", ">=", 0.026),), None)
    m = evaluate_rule(rule, rows)
    assert m["fr_released"] == 2
    assert m["sr_released"] == 1
    assert m["released_fr_ids"] == ["f1", "f2"]
    assert m["released_sr_ids"] == ["s1"]
    assert m["precision"] == pytest.approx(2 / 3)
    assert m["recall"] == pytest.approx(1.0)  # 2/2 FR


def test_net_change_reports_new_refusals():
    """全人口评估：baseline 放行（top1>=0.03）但规则拒答 → 新拒答须报告。"""
    rows = [
        mk_row("f1", False, [0.026]),                      # 拒答子集
        mk_row("ans-1", False, [0.04]),                    # baseline 放行（answerable）
        mk_row("sr-1", True, [0.05]),                      # baseline 放行（SR）
    ]
    rule = Rule((Atom("top1", ">=", 0.06),), None)          # 比 baseline 更严
    net = net_change_vs_baseline(rule, rows)
    assert net["newly_refused_answerable"] == ["ans-1"]
    assert net["newly_refused_sr"] == ["sr-1"]
    # 单调放行规则（top1 >= 0.02）则无新拒答
    rule2 = Rule((Atom("top1", ">=", 0.02),), None)
    net2 = net_change_vs_baseline(rule2, rows)
    assert net2["newly_refused_answerable"] == []
    assert net2["newly_refused_sr"] == []


# ── 枚举（假设生成） ────────────────────────────────────────────────

REFUSED_FIXTURE = [
    mk_row("fr-1", False, [0.02988, 0.02917, 0.02890]),
    mk_row("fr-2", False, [0.02837, 0.02649, 0.02639]),
    mk_row("fr-3", False, [0.02830, 0.02765, 0.02296]),
    mk_row("fr-4", False, [0.02601, 0.02400, 0.02295]),
    mk_row("sr-1", True, [0.02649, 0.02597, 0.02488]),
    mk_row("sr-2", True, [0.02490, 0.02387, 0.02064]),
]


def test_enumerate_rules_deterministic_and_covers_families():
    r1 = enumerate_rules(REFUSED_FIXTURE)
    r2 = enumerate_rules(REFUSED_FIXTURE)
    assert r1 == r2
    assert r1["status"] == STATUS
    assert r1["caveat"].startswith("post-hoc")
    sigs = r1["signatures"]
    assert sigs, "枚举不应为空"
    # 家族覆盖：至少出现一元、区间、AND、OR、atom∨range 之一（以 canonical 检查）
    all_examples = " | ".join(e for s in sigs for e in s["examples"])
    assert ">=" in all_examples
    assert " AND " in all_examples or "OR (" in all_examples
    # 代表规则 ≤ 5
    assert all(len(s["examples"]) <= 5 for s in sigs)
    # 全放行签名存在（top1 >= 极小阈值）
    n_sr_fixture = sum(1 for r in REFUSED_FIXTURE if r["should_refuse"])
    full = [s for s in sigs
            if s["fr_released"] == 4 and s["sr_released"] == n_sr_fixture]
    assert full, "应存在全放行假设（top1 >= 极小阈值）"


def test_enumerate_rules_summary_ordering():
    """摘要排序：fr_released 降序、sr_released 升序。"""
    r = enumerate_rules(REFUSED_FIXTURE)
    sigs = r["signatures"]
    for a, b in zip(sigs, sigs[1:]):
        assert (a["fr_released"], -a["sr_released"]) >= (b["fr_released"], -b["sr_released"])


def test_enumerate_rules_only_refused_population():
    """枚举只接受拒答子集——传入含 baseline 放行 case 的行应被忽略或拒绝。"""
    rows = REFUSED_FIXTURE + [mk_row("ans-1", False, [0.04])]
    with pytest.raises(ValueError, match="refused"):
        enumerate_rules(rows)


# ── PR 曲线 ─────────────────────────────────────────────────────────

def test_pr_curve_points():
    rows = [
        mk_row("fr-1", False, [0.028]),
        mk_row("fr-2", False, [0.026]),
        mk_row("sr-1", True, [0.027]),
        mk_row("sr-2", True, [0.024]),
    ]
    curve = pr_curve(rows, "top1", direction="desc")
    assert curve[0]["n_released"] == 1
    assert curve[0]["fr_hit"] == 1
    assert curve[0]["precision"] == pytest.approx(1.0)
    assert curve[0]["recall"] == pytest.approx(0.5)
    assert curve[-1]["n_released"] == 4
    assert curve[-1]["recall"] == pytest.approx(1.0)
    assert pr_curve(rows, "top1", "desc") == pr_curve(rows, "top1", "desc")


# ── 可视化 ──────────────────────────────────────────────────────────

def test_ascii_scatter_deterministic():
    pts = [("fr-1", 0.0299, 0.006), ("sr-1", 0.0265, 0.0036)]
    a = ascii_scatter(pts)
    b = ascii_scatter(pts)
    assert a == b
    assert "F" in a and "S" in a


# ── CLI 集成 ────────────────────────────────────────────────────────

def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_cli_writes_artifacts_marked_and_holdout_exploratory(tmp_path):
    """CLI：全部 JSON 产物含 HYPOTHESIS_GENERATING_ONLY；holdout 仅
    exploratory_only 角色，且不出现在规则枚举中。"""
    from evaluation.refusal_separability import main

    dev_path = tmp_path / "dev.jsonl"
    ho_path = tmp_path / "ho.jsonl"
    out = tmp_path / "out"
    dev_rows = [
        mk_row("fr-1", False, [0.0299, 0.0292]),
        mk_row("fr-2", False, [0.0284, 0.0265]),
        mk_row("fr-3", False, [0.0283, 0.0277]),
        mk_row("fr-4", False, [0.0260, 0.0240]),
        mk_row("sr-1", True, [0.0265, 0.0260]),
        mk_row("sr-2", True, [0.0249, 0.0239]),
        mk_row("ok-1", False, [0.04, 0.03]),
        mk_row("ok-sr", True, [0.05, 0.04]),
    ]
    ho_rows = [
        mk_row("ho-fr", False, [0.0286, 0.0217]),
        mk_row("ho-sr", True, [0.0218, 0.0215]),
    ]
    write_jsonl(dev_path, dev_rows)
    write_jsonl(ho_path, ho_rows)

    rc = main([
        "--dev-retrieval", str(dev_path),
        "--holdout-retrieval", str(ho_path),
        "--output-dir", str(out),
    ])
    assert rc == 0

    for name in ("feature-dictionary.json", "rule-enumeration.json",
                 "pr-curves.json", "manifest.json"):
        data = json.loads((out / name).read_text(encoding="utf-8"))
        assert data.get("status") == STATUS, name

    feats = [json.loads(l) for l in
             (out / "features.jsonl").read_text(encoding="utf-8").splitlines()]
    roles = {f["case_id"]: f["role"] for f in feats}
    assert roles["ho-fr"] == "exploratory_only"
    assert roles["fr-1"] == "selection_hypothesis"
    enum = json.loads((out / "rule-enumeration.json").read_text(encoding="utf-8"))
    all_ids = {cid for s in enum["signatures"] for cid in
               s["released_fr_ids"] + s["released_sr_ids"]}
    assert "ho-fr" not in all_ids and "ho-sr" not in all_ids

    report = (out / "separability-report.md").read_text(encoding="utf-8")
    assert STATUS in report
    assert "post-hoc" in report
    assert "HYPOTHESIS_GENERATING_ONLY" in (
        out / "decision-report.md").read_text(encoding="utf-8")
    assert (out / "manifest.json").exists()
