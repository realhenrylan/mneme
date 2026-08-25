"""Tests for scripts.evaluate_v211_cross_document_ablation_audit_correction
— Phase 6-C1.1（审计语义修正，只读，不重跑实验）。

The C1.1 correction package must:
- recompute the original C1 manifest self-hash and all 6 original outputs'
  byte SHAs first; any drift aborts fail-closed with zero outputs;
- separate ``data_quality`` (core integrity / uniqueness / metric
  recomputation / referential integrity / lineage & manifest closed loop)
  from ``promotion_eligibility`` (6 pre-locked gate conditions, 4 failed,
  decision NO_PROMOTION) — failed gates are never mixed into
  data-quality checks, and ``data_quality.passed`` never implies promotion;
- accurately reword the run-consistency claim: the NO_PROMOTION conclusion
  and the cd recall@5 failure direction are stable across two independent
  runs, but raw ranking / per-case / some aggregate metrics carry recorded
  HNSW nondeterminism differences;
- never contain the inaccurate phrases 「两次完整独立运行一致」/「30 项全过」;
- manifest self-hash with inputs (original C1 manifest + 6 outputs) /
  outputs SHA closed loop; two builds byte-identical (no timestamps);
- not touch the original C1 dir, frozen revision, 6-A, B0, B0.1; no LLM /
  network / Chroma index build / retrieval rerun; default product path
  unchanged.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.evaluate_v211_cross_document_ablation_audit_correction as ac
from tests.test_evaluate_v211_frozen_product_contract import (  # noqa: E402
    _canonical, _self_hash, _sha256_bytes,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

_EXPECTED_FAILURES = [
    "cd_recall@5_gain",
    "overall_recall@5_no_drop",
    "overall_ndcg10_mrr_no_drop",
    "exceeds_recorded_noise",
]

_CORE_CHECK_NAMES = [
    "completeness.baseline_rows", "completeness.candidate_rows",
    "completeness.baseline_keys", "completeness.candidate_keys",
    "uniqueness.case_ids", "uniqueness.candidate_case_ids",
    "validity.metric_ranges", "consistency.per_case_recompute",
    "consistency.aggregates_vs_mean",
    "referential.retrieved_ids_in_corpus",
    "referential.relevant_ids_in_corpus",
    "referential.mapping_failures_zero",
    "conservation.case_counts", "conservation.mapping_failures_zero",
    "conservation.cross_document_n",
    "strategy.variants_literal_substrings",
    "strategy.candidate_no_duplicate_chunk_ids",
    "lineage.frozen_verified", "lineage.phase6a_verified",
    "lineage.phase6b0_verified", "lineage.hardened_verified",
]  # 21 项核心 data-quality checks（与真实 C1 报告同构）


def _gate_conditions() -> list[dict]:
    return [
        {"id": "cd_recall@5_gain", "ok": False,
         "build1": {"baseline": 0.30, "candidate": 0.28, "delta": -0.02},
         "build2": {"baseline": 0.30, "candidate": 0.28, "delta": -0.02}},
        {"id": "overall_recall@5_no_drop", "ok": False,
         "build1": {"baseline": 0.60, "candidate": 0.55, "delta": -0.05},
         "build2": {"baseline": 0.60, "candidate": 0.56, "delta": -0.04}},
        {"id": "overall_ndcg10_mrr_no_drop", "ok": False,
         "build1": {"baseline": {"mrr": 0.53, "ndcg@10": 0.54},
                    "candidate": {"mrr": 0.50, "ndcg@10": 0.51},
                    "deltas": {"mrr": -0.03, "ndcg@10": -0.03}},
         "build2": {"baseline": {"mrr": 0.53, "ndcg@10": 0.54},
                    "candidate": {"mrr": 0.49, "ndcg@10": 0.52},
                    "deltas": {"mrr": -0.04, "ndcg@10": -0.02}}},
        {"id": "cd_source_recall@5_no_drop", "ok": True,
         "build1": {"baseline": 0.90, "candidate": 0.95, "delta": 0.05},
         "build2": {"baseline": 0.90, "candidate": 0.95, "delta": 0.05}},
        {"id": "exceeds_recorded_noise", "ok": False,
         "min_gain_across_builds": -0.02, "noise_cd_recall5": 0.0,
         "formula": "min(build1_gain, build2_gain) ≥ noise_factor × noise"},
        {"id": "all_checks_passed", "ok": True},
    ]


def _dq_checks() -> list[dict]:
    """镜像真实 C1 报告结构：21 项核心全过 + 9 项 gate.*（4 条 false，
    含重复的 gate.decision_recorded）。"""
    core = [{"name": n, "ok": True, "detail": ""} for n in _CORE_CHECK_NAMES]
    gate = [
        {"name": "gate.conditions_complete", "ok": True, "detail": "conditions=6"},
        {"name": "gate.decision_recorded", "ok": True, "detail": "NO_PROMOTION"},
        {"name": "gate.decision_recorded", "ok": True, "detail": "NO_PROMOTION"},
        {"name": "gate.cd_recall@5_gain", "ok": False, "detail": "NO_PROMOTION"},
        {"name": "gate.overall_recall@5_no_drop", "ok": False,
         "detail": "NO_PROMOTION"},
        {"name": "gate.overall_ndcg10_mrr_no_drop", "ok": False,
         "detail": "NO_PROMOTION"},
        {"name": "gate.cd_source_recall@5_no_drop", "ok": True,
         "detail": "NO_PROMOTION"},
        {"name": "gate.exceeds_recorded_noise", "ok": False,
         "detail": "NO_PROMOTION"},
        {"name": "gate.all_checks_passed", "ok": True, "detail": "NO_PROMOTION"},
    ]
    return core + gate


def _overall(recall5: float, mrr: float, ndcg10: float) -> dict:
    return {"recall@5": recall5, "recall@10": recall5 + 0.1,
            "recall@20": recall5 + 0.2, "ndcg@5": ndcg10 - 0.01,
            "ndcg@10": ndcg10, "ndcg@20": ndcg10 + 0.02, "mrr": mrr,
            "source_recall@5": 0.95, "source_recall@10": 0.98,
            "source_recall@20": 0.98}


def _fixture_original_c1(tmp_path: Path) -> Path:
    """fake 原 C1 目录：7 个文件 + 自洽 manifest（30 条 DQ checks、
    4 条 false gate、build2 候选整体指标与主构建不同、跨运行 per-case
    差异已记录）。"""
    d = tmp_path / "c1"
    d.mkdir(parents=True, exist_ok=True)
    summary = {
        "task": "fixture-c1",
        "baseline": {"metrics": {"overall": _overall(0.60, 0.53, 0.54)}},
        "candidate": {"metrics": {"overall": _overall(0.55, 0.50, 0.53)}},
        "gate": {"decision": "NO_PROMOTION", "failures": list(_EXPECTED_FAILURES),
                 "conditions": _gate_conditions()},
    }
    (d / "ablation-summary.json").write_text(_canonical(summary), encoding="utf-8")
    for name in ("per-case-results-baseline.jsonl",
                 "per-case-results-candidate.jsonl"):
        (d / name).write_text("{}\n", encoding="utf-8")
    (d / "cross-document-analysis.md").write_text("# fixture\n", encoding="utf-8")
    (d / "selection-decision.md").write_text("# fixture\n", encoding="utf-8")
    dq = {"passed": True, "error_count": 0, "errors": [],
          "warning_count": 0, "warnings": [], "checks": _dq_checks(),
          "note": "fixture"}
    (d / "data-quality-report.json").write_text(_canonical(dq), encoding="utf-8")

    outputs = {name: _sha256_bytes((d / name).read_bytes())
               for name in ac.ORIGINAL_OUTPUT_FILES}
    manifest = {
        "task": "fixture-c1",
        "outputs": outputs,
        "determinism": {
            "cd_recall5_noise": 0.0,
            "baseline": {"difference_count": 2, "metric_difference_count": 1},
            "candidate": {"difference_count": 3, "metric_difference_count": 2},
            "build2": {
                "baseline_metrics": _overall(0.60, 0.53, 0.54),
                "candidate_metrics": _overall(0.56, 0.49, 0.52),
                "baseline_cd": {"recall@5": 0.30, "source_recall@5": 0.90},
                "candidate_cd": {"recall@5": 0.29, "source_recall@5": 0.95},
            },
        },
        "verification": {"prior_run": {
            "per_case_diff_count": {"baseline": 5, "candidate": 9},
            "aggregate_deltas": {"baseline": {"mrr": -2.6e-05},
                                 "candidate": {"mrr": 0.005215}},
        }},
        "manifest_sha256": "PLACEHOLDER",
    }
    manifest["manifest_sha256"] = _self_hash(manifest)
    (d / "manifest.json").write_text(_canonical(manifest), encoding="utf-8")
    return d


def _run(tmp_path: Path, out_name: str = "out") -> tuple[Path, dict]:
    original = _fixture_original_c1(tmp_path)
    out = tmp_path / out_name
    result = ac.run_correction(original_dir=original, out_dir=out)
    return original, result


# ── Group 1: fail-closed on original C1 drift ─────────────────────────

def test_verify_original_ablation_ok_on_fixture(tmp_path):
    original = _fixture_original_c1(tmp_path)
    report = ac.verify_original_ablation(original)
    assert report["verified"] is True
    assert report["drift"] == []
    assert len(report["checks"]) == 7  # 1 self-hash + 6 outputs
    manifest = json.loads((original / "manifest.json").read_text(encoding="utf-8"))
    assert report["manifest"]["manifest_sha256"] == manifest["manifest_sha256"]


def test_fail_closed_on_original_manifest_drift(tmp_path):
    original = _fixture_original_c1(tmp_path)
    path = original / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["task"] = "tampered"
    path.write_text(_canonical(doc), encoding="utf-8")  # self-hash 漂移
    out = tmp_path / "out"
    with pytest.raises(ac.CorrectionDrift):
        ac.run_correction(original_dir=original, out_dir=out)
    assert not out.exists()  # fail-closed：零产物


def test_fail_closed_on_original_output_drift(tmp_path):
    original = _fixture_original_c1(tmp_path)
    with open(original / "per-case-results-baseline.jsonl", "a",
              encoding="utf-8") as f:
        f.write("\n")  # 字节 SHA 漂移
    out = tmp_path / "out"
    with pytest.raises(ac.CorrectionDrift):
        ac.run_correction(original_dir=original, out_dir=out)
    assert not out.exists()


# ── Group 2: corrected semantics (data_quality vs promotion_eligibility)

def test_correction_identifies_exactly_four_failed_gates(tmp_path):
    _, result = _run(tmp_path)
    pe = result["corrected_dq"]["promotion_eligibility"]
    assert pe["decision"] == "NO_PROMOTION"
    assert pe["failures"] == _EXPECTED_FAILURES  # 精确 4 条未通过 gate
    assert len(pe["conditions"]) == 6


def test_data_quality_passed_implies_no_false_core_checks(tmp_path):
    _, result = _run(tmp_path)
    dq = result["corrected_dq"]
    assert dq["data_quality"]["passed"] is True
    assert all(c["ok"] for c in dq["data_quality"]["checks"])
    # 失败 gate 只出现在 promotion_eligibility，绝不混入 data_quality
    assert not any(c["name"].startswith("gate.")
                   for c in dq["data_quality"]["checks"])
    pe_false = {c["id"] for c in dq["promotion_eligibility"]["conditions"]
                if not c["ok"]}
    assert pe_false == set(_EXPECTED_FAILURES)


def test_gate_failures_not_counted_as_data_quality_errors(tmp_path):
    _, result = _run(tmp_path)
    dq = result["corrected_dq"]
    assert dq["data_quality"]["error_count"] == 0
    assert len(dq["promotion_eligibility"]["failures"]) == 4


def test_correction_states_dq_does_not_imply_promotion(tmp_path):
    _, result = _run(tmp_path)
    note = result["corrected_dq"]["promotion_eligibility"]["note"]
    assert "不是 data-quality 失败" in note
    assert "不意味着" in note
    summary = json.loads(
        (tmp_path / "out" / "correction-summary.json").read_text(encoding="utf-8"))
    md = (tmp_path / "out" / "CORRECTION.md").read_text(encoding="utf-8")
    assert summary["corrected_verdict"]["data_quality"]["passed"] is True
    assert summary["corrected_verdict"]["promotion_eligibility"]["decision"] \
        == "NO_PROMOTION"
    assert "NO_PROMOTION" in md
    assert "数据质量" in md and "promotion" in md


def test_forbidden_phrases_absent_from_package_docs(tmp_path):
    _, result = _run(tmp_path)
    out = tmp_path / "out"
    texts = {
        "CORRECTION.md": (out / "CORRECTION.md").read_text(encoding="utf-8"),
        "correction-summary.json": (out / "correction-summary.json")
        .read_text(encoding="utf-8"),
        "corrected-data-quality-report.json": (out / "corrected-data-quality-report.json")
        .read_text(encoding="utf-8"),
    }
    for name, text in texts.items():
        assert "两次完整独立运行一致" not in text, name
        assert "30 项全过" not in text, name
    # 正面要求：更正后的表述如实包含「非确定性」差异
    summary = json.loads(texts["correction-summary.json"])
    assert "非确定性" in summary["semantic_corrections"][0]["corrected_statement"]


# ── Group 3: manifest closed loop / byte-identical builds ─────────────

def test_manifest_self_hash_and_closed_loop(tmp_path):
    original, _ = _run(tmp_path)
    out = tmp_path / "out"
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_sha256"] == ac.self_hash(manifest)
    # outputs：3 个（不含 manifest.json，自哈希约定）
    assert set(manifest["outputs"]) == set(ac.CORRECTION_OUTPUT_FILES) - {
        "manifest.json"}
    for name, sha in manifest["outputs"].items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == sha
    # inputs：原 C1 manifest + 6 个原 outputs = 7 项，字节 SHA 闭环
    assert len(manifest["inputs"]) == 7
    assert "original-c1-manifest.json" in manifest["inputs"]
    for name, rec in manifest["inputs"].items():
        assert Path(rec["path"]).is_file()
        assert hashlib.sha256(Path(rec["path"]).read_bytes()).hexdigest() \
            == rec["sha256"]
    orig_manifest = json.loads((original / "manifest.json")
                               .read_text(encoding="utf-8"))
    assert manifest["original_c1"]["manifest_sha256"] == \
        orig_manifest["manifest_sha256"]


def test_two_builds_byte_identical(tmp_path):
    _, _ = _run(tmp_path, out_name="out1")
    _, _ = _run(tmp_path, out_name="out2")
    for name in ac.CORRECTION_OUTPUT_FILES:
        b1 = (tmp_path / "out1" / name).read_bytes()
        b2 = (tmp_path / "out2" / name).read_bytes()
        assert b1 == b2, name  # 无时间戳 → 逐字节一致


def test_does_not_touch_original_c1(tmp_path):
    original = _fixture_original_c1(tmp_path)
    before = {p.name: _sha256_bytes(p.read_bytes())
              for p in sorted(original.iterdir())}
    out = tmp_path / "out"
    ac.run_correction(original_dir=original, out_dir=out)
    after = {p.name: _sha256_bytes(p.read_bytes())
             for p in sorted(original.iterdir())}
    assert before == after  # 原 C1 7 个文件分毫未动
    assert {p.name for p in out.iterdir()} == set(ac.CORRECTION_OUTPUT_FILES)


def test_audit_module_imports_no_heavy_deps():
    """纯 stdlib 审计：不导入 src.* / chromadb / 检索/LLM 链路。"""
    code = (
        "import sys;"
        "import scripts.evaluate_v211_cross_document_ablation_audit_correction;"
        "bad=[m for m in sys.modules if m.startswith('src.')"
        " or m in ('chromadb','sentence_transformers','rank_bm25',"
        "'langchain_text_splitters')];"
        "print('BAD:' + repr(bad))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        cwd=str(REPO_ROOT), timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert "BAD:[]" in out.stdout


def test_main_exit_codes(tmp_path):
    original = _fixture_original_c1(tmp_path)
    out = tmp_path / "out"
    code = ac.main(["--original-dir", str(original), "--output", str(out)])
    assert code == 0
    assert (out / "manifest.json").is_file()
    # 原 C1 输出漂移 → exit 2，零产物
    with open(original / "selection-decision.md", "a", encoding="utf-8") as f:
        f.write("\n")
    out2 = tmp_path / "out2"
    assert ac.main(["--original-dir", str(original), "--output", str(out2)]) == 2
    assert not out2.exists()


# ── Group 4: correction content / determinism facts ───────────────────

def test_correction_summary_records_two_semantic_corrections(tmp_path):
    _, _ = _run(tmp_path)
    summary = json.loads(
        (tmp_path / "out" / "correction-summary.json").read_text(encoding="utf-8"))
    corrections = summary["semantic_corrections"]
    assert len(corrections) == 2
    assert {c["id"] for c in corrections} == {
        "run_consistency_wording", "data_quality_gate_separation"}
    for c in corrections:
        assert c["title"] and c["original_statement"] and c["corrected_statement"]
        assert "evidence" in c


def test_determinism_facts_extracted(tmp_path):
    original, _ = _run(tmp_path)
    out = tmp_path / "out"
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    det = manifest["determinism"]
    assert det["cd_recall5_noise"] == 0.0
    inrun = det["in_run_second_build"]
    # fixture：候选 build2 与主构建存在整体指标差异（HNSW 扰动证据）
    assert inrun["candidate_max_abs_delta"] == 0.01
    assert inrun["baseline_max_abs_delta"] == 0.0
    assert inrun["candidate_raw_difference_count"] == 3
    assert inrun["candidate_metric_difference_count"] == 2
    assert det["cross_run"]["per_case_diff_count"] == {"baseline": 5,
                                                       "candidate": 9}


# ── Group 5: real frozen data (skip-guarded) ──────────────────────────

pytestmark_real = pytest.mark.skipif(
    not ac.ORIGINAL_DIR.exists(),
    reason="original Phase 6-C1 ablation artifacts are local",
)


@pytestmark_real
def test_real_original_c1_verifies_and_corrects(tmp_path):
    report = ac.verify_original_ablation(ac.ORIGINAL_DIR)
    assert report["verified"] is True
    assert report["drift"] == []
    assert len(report["checks"]) == 7
    assert report["manifest"]["manifest_sha256"] == \
        "45f40c63e5dccb18ebe855f575d10410ff59af186585af1d943f5ca35b0cf350"
    out = tmp_path / "out"
    result = ac.run_correction(original_dir=ac.ORIGINAL_DIR, out_dir=out)
    assert result["status"] == "ok"
    assert result["gate_facts"]["failures"] == _EXPECTED_FAILURES
    assert result["corrected_dq"]["data_quality"]["passed"] is True
    assert result["corrected_dq"]["data_quality"]["error_count"] == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_sha256"] == ac.self_hash(manifest)
    for name, sha in manifest["outputs"].items():
        assert ac.sha256_bytes(out / name) == sha


@pytestmark_real
def test_real_protected_inputs_unchanged(tmp_path):
    import scripts.evaluate_v211_frozen_product_baseline as bl6a  # noqa: E402
    import scripts.evaluate_v211_frozen_product_contract as cbl  # noqa: E402
    import scripts.evaluate_v211_frozen_product_contract_hardened as hbl  # noqa: E402

    files = [ac.ORIGINAL_DIR / name
             for name in ("manifest.json", *ac.ORIGINAL_OUTPUT_FILES)] + [
        bl6a.FROZEN_REVISION_DIR / "manifest.json",
        bl6a.FROZEN_REVISION_DIR / "draft-after.jsonl",
        bl6a.FROZEN_REVISION_DIR / "evidence-after.jsonl",
        bl6a.FREEZE_DIR / "manifest.json",
        bl6a.FROZEN_REVISION_DIR / "targeted-re-review/manifest.json",
        bl6a.CHUNKS_PATH,
        bl6a.CHUNK_MANIFEST_PATH,
        cbl.PHASE6A_DIR / "manifest.json",
        cbl.OUTPUT_DIR / "manifest.json",
        hbl.HARDENED_DIR / "manifest.json",
    ]
    before = {str(p): ac.sha256_bytes(p) for p in files if p.is_file()}
    assert before  # 全部路径实际存在
    out = tmp_path / "out"
    ac.run_correction(original_dir=ac.ORIGINAL_DIR, out_dir=out)
    after = {str(p): ac.sha256_bytes(p) for p in files if p.is_file()}
    assert before == after  # 原 C1 / 冻结 revision / 6-A / B0 / B0.1 字节不变
