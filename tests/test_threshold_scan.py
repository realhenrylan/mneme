"""离线检索拒答阈值扫描 —— 纯函数与 CLI 的单元测试（RED → GREEN）。

覆盖：拒答判定边界、逐阈值放行集、G1/G2 预注册门槛（主口径 + 敏感性）、
分数带交织诊断、fail-closed 一致性校验（生成证据 / 跨运行）、输出确定性。
"""

import json
import math

import pytest

from evaluation.threshold_scan import (
    BASELINE_THRESHOLD,
    CANDIDATE_THRESHOLDS,
    admissible_thresholds,
    band_diagnostic,
    check_cross_source_agreement,
    check_generation_consistency,
    evaluate_split_gates,
    overall_verdict,
    refused_at,
    scan_thresholds,
)


def mk_row(case_id, should_refuse, scores, query_type="single_fact"):
    """构造最小 retrieval-case 行（与 retrieval-cases.jsonl 同键名）。"""
    return {
        "case_id": case_id,
        "should_refuse": should_refuse,
        "candidate_scores": list(scores),
        "query_type": query_type,
        "language": "en",
    }


def mk_generation_row(case_id, should_refuse, context_sha=""):
    """构造 generation 行（ablation 运行格式，含 evidence 字段）。"""
    return {
        "case_id": case_id,
        "arm": "standard",
        "should_refuse": should_refuse,
        "evidence_context_sha256": context_sha,
        "correctly_refused": False,
    }


# ── refused_at 边界 ─────────────────────────────────────────────────

def test_refused_at_empty_scores_refused_even_at_zero():
    """空分数在阈值 0.00 下仍然拒答（not scores 优先）。"""
    assert refused_at([], 0.00) is True
    assert refused_at([], 0.03) is True


def test_refused_at_equal_max_is_released():
    """max == threshold 不放行边界语义：max < t 才拒答。"""
    assert refused_at([0.02], 0.02) is False
    assert refused_at([0.0199999], 0.02) is True


def test_refused_at_above_threshold_released():
    assert refused_at([0.03, 0.05], 0.03) is False
    assert refused_at([0.0299], 0.03) is True


# ── scan_thresholds 逐阈值放行 ──────────────────────────────────────

DEV_FR = [  # 4 条前哨 FR（answerable，max < 0.03）
    ("cross-010", 0.02988), ("en-013", 0.02837),
    ("meta-006", 0.02830), ("meta-008", 0.02601),
]
DEV_SR = [  # 6 条正确拒答（should_refuse，max < 0.03）
    ("noanswer-006", 0.02649), ("noanswer-008", 0.02490),
    ("noanswer-012", 0.02938), ("noanswer-020", 0.02353),
    ("noanswer-022", 0.02210), ("noanswer-024", 0.02649),
]


def dev_rows():
    rows = []
    for cid, sc in DEV_FR:
        rows.append(mk_row(cid, False, [sc]))
    for cid, sc in DEV_SR:
        rows.append(mk_row(cid, True, [sc]))
    # 31 条 max >= 0.03（15 条 answerable + 16 条 should_refuse）
    for i in range(15):
        rows.append(mk_row(f"ans-{i:03d}", False, [0.05 + i / 1000]))
    for i in range(16):
        rows.append(mk_row(f"sr-{i:03d}", True, [0.04 + i / 1000]))
    return rows


def test_scan_thresholds_release_sets():
    """候选阈值 0.00/0.01/0.02 放行集一致（分数带无 <0.02 的 case）；0.03 不放行。"""
    scan = scan_thresholds(dev_rows())
    assert scan["case_count"] == 41
    assert scan["answerable_total"] == 19
    assert scan["should_refuse_total"] == 22  # 6 前哨拒答 SR + 16 高分段 SR
    refused = scan["refused_at_baseline"]
    assert refused["total"] == 10
    assert set(refused["sentinel_fr_ids"]) == {c for c, _ in DEV_FR}
    assert set(refused["correctly_refused_ids"]) == {c for c, _ in DEV_SR}

    entries = {e["threshold"]: e for e in scan["per_threshold"]}
    assert set(entries) == set(CANDIDATE_THRESHOLDS)
    for t in (0.00, 0.01, 0.02):
        e = entries[t]
        assert e["newly_released_total"] == 10
        assert set(e["newly_released_answerable_ids"]) == {c for c, _ in DEV_FR}
        assert set(e["newly_released_should_refuse_ids"]) == {c for c, _ in DEV_SR}
        assert len(e["newly_released_answerable_ids"]) == 4
    e = entries[0.03]
    assert e["newly_released_total"] == 0


def test_empty_scores_case_never_released():
    """空分数 case 在所有候选阈值下仍拒答（不出现在任何放行集）。"""
    rows = dev_rows() + [mk_row("no-score-001", False, [])]
    scan = scan_thresholds(rows)
    for e in scan["per_threshold"]:
        assert "no-score-001" not in e["newly_released_answerable_ids"]
        assert "no-score-001" not in e["newly_released_should_refuse_ids"]


def test_scan_thresholds_deterministic():
    """同输入 → 同结果（确定性，供报告字节级复现）。"""
    rows = dev_rows()
    assert scan_thresholds(rows) == scan_thresholds(rows)


# ── evaluate_split_gates（G2 主口径 + 敏感性） ──────────────────────

def test_g2_primary_fail_when_exceeds_ten_percent():
    """主口径：新放行 should_refuse 6 > 10% × 22 = 2.2 → FAIL。"""
    gates = evaluate_split_gates(
        scan_thresholds(dev_rows()),
        sentinel_fr_ids={c for c, _ in DEV_FR},
        should_refuse_total=22,
    )
    entry = gates["per_threshold"][0]  # t=0.00
    assert entry["g2_primary"]["pass"] is False
    assert entry["g2_primary"]["released"] == 6
    assert math.isclose(entry["g2_primary"]["allowed"], 2.2)


def test_g2_primary_pass_at_boundary():
    """边界：2 条新放行 ≤ 10% × 22 = 2.2 → PASS。"""
    rows = [mk_row(c, False, [0.028]) for c, _ in DEV_FR]  # 4 FR
    rows += [mk_row("ok-1", True, [0.026]), mk_row("ok-2", True, [0.025])]
    rows += [mk_row(f"x-{i}", False, [0.05]) for i in range(10)]
    gates = evaluate_split_gates(
        scan_thresholds(rows),
        sentinel_fr_ids={c for c, _ in DEV_FR},
        should_refuse_total=22,
    )
    for e in gates["per_threshold"]:
        assert e["g2_primary"]["pass"] is True


def test_g2_sensitivity_all_bases_fail():
    """敏感性表：基数 refused_total(10)/refused_should_refuse(6)/all(22) 均 FAIL。"""
    gates = evaluate_split_gates(
        scan_thresholds(dev_rows()),
        sentinel_fr_ids={c for c, _ in DEV_FR},
        should_refuse_total=22,
    )
    sens = gates["per_threshold"][0]["g2_sensitivity"]
    assert set(sens) == {"refused_total", "refused_should_refuse", "all_should_refuse"}
    assert all(v["pass"] is False for v in sens.values())
    assert math.isclose(sens["refused_total"]["allowed"], 1.0)
    assert math.isclose(sens["refused_should_refuse"]["allowed"], 0.6)
    assert math.isclose(sens["all_should_refuse"]["allowed"], 2.2)


def test_gate_sentinel_fr_release_count():
    """每阈值条目报告该 split 前哨 FR 放行数。"""
    gates = evaluate_split_gates(
        scan_thresholds(dev_rows()),
        sentinel_fr_ids={c for c, _ in DEV_FR},
        should_refuse_total=22,
    )
    for e in gates["per_threshold"]:
        if e["threshold"] in (0.00, 0.01, 0.02):
            assert e["sentinel_fr_released_count"] == 4
        else:  # t=0.03（baseline 本身）不放行任何 case
            assert e["sentinel_fr_released_count"] == 0


# ── 合并判定：admissible_thresholds / overall_verdict ───────────────

def test_admissible_thresholds_empty_when_g2_fails():
    """G2 失败 → 无合格阈值（即使 G1 5/5 放行）。"""
    dev_gates = evaluate_split_gates(
        scan_thresholds(dev_rows()),
        sentinel_fr_ids={c for c, _ in DEV_FR},
        should_refuse_total=22,
    )
    # holdout：meta-002 放行、noanswer-010 放行（1 条新 SR，>10%×3=0.3）
    ho_rows = [
        mk_row("meta-002", False, [0.02857]),
        mk_row("noanswer-010", True, [0.02700]),
        mk_row("h-ok-1", True, [0.05]),
        mk_row("h-ok-2", False, [0.06]),
    ]
    ho_gates = evaluate_split_gates(
        scan_thresholds(ho_rows),
        sentinel_fr_ids={"meta-002"},
        should_refuse_total=3,
    )
    admissible = admissible_thresholds(dev_gates, ho_gates)
    assert admissible == []
    assert overall_verdict(admissible) == "AUTOMATED_DIAGNOSTIC_NO_GO"


def test_admissible_thresholds_found_when_gates_pass():
    """G1 与 G2 均满足 → 阈值合格，verdict=ADMISSIBLE。"""
    rows = [mk_row(c, False, [0.028]) for c, _ in DEV_FR]
    rows += [mk_row("ok-1", True, [0.026]), mk_row("ok-2", True, [0.025])]
    rows += [mk_row(f"x-{i}", False, [0.05]) for i in range(10)]
    dev_gates = evaluate_split_gates(
        scan_thresholds(rows),
        sentinel_fr_ids={c for c, _ in DEV_FR},
        should_refuse_total=22,
    )
    ho_rows = [mk_row("meta-002", False, [0.02857]),
               mk_row("h-ok", True, [0.05]), mk_row("h-ok2", False, [0.06])]
    ho_gates = evaluate_split_gates(
        scan_thresholds(ho_rows),
        sentinel_fr_ids={"meta-002"},
        should_refuse_total=3,
    )
    admissible = admissible_thresholds(dev_gates, ho_gates)
    assert 0.02 in admissible
    assert overall_verdict(admissible) == "ADMISSIBLE"


def test_g1_requires_at_least_four_sentinel_fr():
    """G1 合并口径：放行前哨 FR 总数 ≥ 4（默认，5 条中至少 4）。"""
    rows = [mk_row(c, False, [0.028]) for c, _ in DEV_FR[:3]]  # 只放行 3 条
    rows += [mk_row(f"y-{i}", True, [0.029]) for i in range(3)]
    rows += [mk_row(f"x-{i}", False, [0.05]) for i in range(10)]
    dev_gates = evaluate_split_gates(
        scan_thresholds(rows),
        sentinel_fr_ids={c for c, _ in DEV_FR},
        should_refuse_total=22,
    )
    ho_gates = evaluate_split_gates(
        scan_thresholds([mk_row("meta-002", False, [0.02857]),
                         mk_row("h", True, [0.05]), mk_row("h2", False, [0.06])]),
        sentinel_fr_ids={"meta-002"},
        should_refuse_total=3,
    )
    # dev 3 + holdout 1 = 4 ≥ 4 → G1 通过（但 G2 失败 → 仍无合格阈值）
    admissible = admissible_thresholds(dev_gates, ho_gates)
    assert admissible == []  # G2 主导
    # 单独验证 G1 计数语义：合并放行数 = 4
    assert dev_gates["per_threshold"][0]["sentinel_fr_released_count"] == 3
    assert ho_gates["per_threshold"][0]["sentinel_fr_released_count"] == 1


# ── band_diagnostic 分数带交织 ──────────────────────────────────────

def test_band_diagnostic_interleaved():
    """FR 带 [0.026,0.03) 与正确拒答带 [0.022,0.03) 交织：无分离阈值。"""
    diag = band_diagnostic(
        [sc for _, sc in DEV_FR],
        [sc for _, sc in DEV_SR],
    )
    assert diag["interleaved"] is True
    assert diag["min_correct_released_when_releasing_all_fr"] == 3
    assert diag["no_separating_threshold"] is True


def test_band_diagnostic_separable():
    """分数带不重叠 → 放行全部 FR 时可不放行任何正确拒答。"""
    diag = band_diagnostic([0.028, 0.029], [0.020, 0.021])
    assert diag["interleaved"] is False
    assert diag["min_correct_released_when_releasing_all_fr"] == 0
    assert diag["no_separating_threshold"] is False


def test_band_diagnostic_empty_correct_band():
    diag = band_diagnostic([0.028, 0.029], [])
    assert diag["interleaved"] is False
    assert diag["min_correct_released_when_releasing_all_fr"] == 0


# ── fail-closed 一致性校验 ──────────────────────────────────────────

def test_generation_consistency_passes_when_equal():
    """score 拒答（max<0.03）与 generation evidence 前哨拒答完全一致 → 通过。"""
    retrieval_rows = dev_rows()
    gen_rows = [
        mk_generation_row(c, False, context_sha="")
        for c, _ in DEV_FR
    ]
    gen_rows += [
        mk_generation_row(c, True)
        for c, _ in DEV_SR
    ]
    gen_rows += [
        mk_generation_row(f"ans-{i:03d}", False, context_sha="a" * 64)
        for i in range(15)
    ]
    gen_rows += [
        mk_generation_row(f"sr-{i:03d}", True, context_sha="b" * 64)
        for i in range(16)
    ]
    check_generation_consistency(retrieval_rows, gen_rows, BASELINE_THRESHOLD)


def test_generation_consistency_mismatch_raises():
    """generation 前哨拒答多出/缺少 case → ValueError（fail-closed）。"""
    retrieval_rows = dev_rows()
    gen_rows = [  # 缺少 meta-008 的前哨拒答标记（被错误地构建了 context）
        mk_generation_row(c, False, context_sha="")
        for c, _ in DEV_FR if c != "meta-008"
    ]
    gen_rows += [mk_generation_row("meta-008", False, context_sha="c" * 64)]
    gen_rows += [mk_generation_row(c, True) for c, _ in DEV_SR]
    gen_rows += [mk_generation_row(f"x-{i}", False, context_sha="d" * 64)
                 for i in range(20)]
    with pytest.raises(ValueError, match="generation"):
        check_generation_consistency(retrieval_rows, gen_rows, BASELINE_THRESHOLD)


def test_cross_source_agreement_passes_when_classification_same():
    """跨运行分数微差不改变拒答分类 → 通过。"""
    rows_a = dev_rows()
    rows_b = []
    for r in rows_a:
        rr = dict(r)
        scores = [s * 1.00001 for s in rr["candidate_scores"]]  # 微差
        rr["candidate_scores"] = scores
        rows_b.append(rr)
    check_cross_source_agreement(rows_a, rows_b, BASELINE_THRESHOLD)


def test_cross_source_mismatch_raises():
    """同一 case 跨运行拒答分类翻转 → ValueError（fail-closed）。"""
    rows_a = dev_rows()
    rows_b = []
    for r in rows_a:
        rr = dict(r)
        if r["case_id"] == "cross-010":
            rr["candidate_scores"] = [0.029]  # < 0.03 → 分类从拒答变放行? 不变
            rr["candidate_scores"] = [0.031]  # 分类翻转（放行）
        rows_b.append(rr)
    with pytest.raises(ValueError, match="cross-source"):
        check_cross_source_agreement(rows_a, rows_b, BASELINE_THRESHOLD)


def test_cross_source_case_set_mismatch_raises():
    rows_a = dev_rows()
    rows_b = [r for r in rows_a if r["case_id"] != "ans-001"]
    with pytest.raises(ValueError, match="case"):
        check_cross_source_agreement(rows_a, rows_b, BASELINE_THRESHOLD)


# ── CLI 集成 ────────────────────────────────────────────────────────

def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_main_writes_report_and_no_go(tmp_path):
    """CLI 全流程：写入 4 个产物，verdict=NO_GO，输出确定性。"""
    from evaluation.threshold_scan import main

    dev_path = tmp_path / "dev.jsonl"
    ho_path = tmp_path / "ho.jsonl"
    gen_path = tmp_path / "gen.jsonl"
    out = tmp_path / "out"
    write_jsonl(dev_path, dev_rows())
    write_jsonl(ho_path, [
        mk_row("meta-002", False, [0.02857]),
        mk_row("noanswer-010", True, [0.02700]),
        mk_row("h-1", True, [0.05]),
        mk_row("h-2", False, [0.06]),
    ])
    gen_rows = [
        mk_generation_row(c, False, context_sha="")
        for c, _ in DEV_FR
    ]
    gen_rows += [mk_generation_row(c, True) for c, _ in DEV_SR]
    gen_rows += [
        mk_generation_row(f"ans-{i:03d}", False, context_sha="a" * 64)
        for i in range(15)
    ]
    gen_rows += [
        mk_generation_row(f"sr-{i:03d}", True, context_sha="b" * 64)
        for i in range(16)
    ]
    write_jsonl(gen_path, gen_rows)

    argv = [
        "--dev-retrieval", str(dev_path),
        "--dev-retrieval-cross", str(dev_path),
        "--dev-generation", str(gen_path),
        "--holdout-retrieval", str(ho_path),
        "--output-dir", str(out),
    ]
    rc = main(argv)
    assert rc == 0

    scan = json.loads((out / "threshold-scan.json").read_text(encoding="utf-8"))
    assert scan["verdict"] == "AUTOMATED_DIAGNOSTIC_NO_GO"
    # G1（前哨 FR 放行 ≥4）独立于总体 verdict 判定：候选阈值放行 5/5 → PASS；
    # G2（主口径）两 split 均 FAIL → 阻塞项，故总体 NO_GO
    assert scan["g1_pass"] is True
    assert scan["g2_pass"] is False
    gate = json.loads((out / "gate-pre-registration.json").read_text(encoding="utf-8"))
    assert gate["verdict"] == "AUTOMATED_DIAGNOSTIC_NO_GO"
    assert (out / "threshold-scan.md").exists()
    assert (out / "decision-report.md").exists()
    assert (out / "manifest.json").exists()

    # 输出确定性：同输入再跑一次 → 关键文件字节一致
    out2 = tmp_path / "out2"
    argv2 = argv[:-2] + ["--output-dir", str(out2)]
    assert main(argv2) == 0
    assert (out2 / "threshold-scan.json").read_bytes() == (
        out / "threshold-scan.json").read_bytes()
    assert (out2 / "gate-pre-registration.json").read_bytes() == (
        out / "gate-pre-registration.json").read_bytes()
