"""Tests for scripts.evaluate_v211_cross_document_ablation — Phase 6-C1.

The cross-document ablation must be fail-closed and side-effect-free:
- the hardened B0.1 / old B0 / Phase 6-A / frozen manifests are recomputed
  first; any drift aborts with zero outputs;
- baseline (single-query, existing product retrieval code) and candidate
  (``mechanical-clause-rrf``, deterministic no-LLM variants + RRF fusion)
  run side by side on the same frozen contract index;
- the promotion gate is mechanical and honest: 6 pre-locked conditions,
  evaluated per build, decision ``EXPERIMENT_PROMISING`` only when every
  condition holds on both independent builds — otherwise ``NO_PROMOTION``;
  the default product strategy is never changed;
- 7 artifacts with manifest self-hash, hardened lineage SHA, recomputed
  input/output SHAs, HNSW differences recorded, ``not_measured`` declared;
- no LLM / generation / query-rewriting path; no user-index touch.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.evaluate_v211_cross_document_ablation as abl
from tests.test_evaluate_v211_frozen_product_contract import (  # noqa: E402
    _canonical, _self_hash, _sha256_bytes, _fixture_full,
)
from tests.test_evaluate_v211_frozen_product_contract_hardened import (  # noqa: E402
    _fixture_b0_dir,
)
from tests.test_index_contract import _snapshot_tree  # noqa: E402

ABLATION_OUTPUT_FILES = {
    "ablation-summary.json",
    "per-case-results-baseline.jsonl",
    "per-case-results-candidate.jsonl",
    "cross-document-analysis.md",
    "selection-decision.md",
    "data-quality-report.json",
    "manifest.json",
}


def _fixture_hardened_dir(root: Path, fx: dict[str, Path]) -> Path:
    """fake hardened B0.1 基线目录（7 产物 + 自洽 manifest，含
    phase6a_outputs 段）。"""
    hd = root / "hardened"
    hd.mkdir(parents=True, exist_ok=True)
    summary = {"metrics": {"overall": {
        "recall@5": 1.0, "recall@10": 1.0, "recall@20": 1.0,
        "ndcg@5": 1.0, "ndcg@10": 1.0, "ndcg@20": 1.0, "mrr": 1.0,
        "source_recall@5": 1.0, "source_recall@10": 1.0,
        "source_recall@20": 1.0, "denominators": {
            "total_cases": 6, "chunk_metrics_cases": 4,
            "no_chunk_truth_cases": 2, "mapping_failure_rows": 0,
        }}},
        "determinism": {"difference_count": 0, "metric_difference_count": 0},
        "contract": {"fingerprint": "0" * 64},
    }
    (hd / "contract-baseline-summary.json").write_text(
        _canonical(summary), encoding="utf-8")
    rows = []
    for cid_ in ("en-001", "en-002", "zh-003", "mixed-004",
                 "zh-005", "en-006"):
        rows.append({"case_id": cid_, "metrics": {}, "retrieved_chunk_ids": []})
    (hd / "per-case-retrieval-results.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")
    for name in ("contract-validation-report.md", "comparison-to-phase6a.md",
                 "comparison-to-phase6b0.md", "data-quality-report.json"):
        (hd / name).write_text(_canonical({"fake": name}), encoding="utf-8")
    phase6a = fx["phase6a"]
    hd_manifest = {
        "task": "fixture-phase6b01",
        "inputs": {
            "chunks.jsonl": {"path": str(fx["chunks"]),
                             "sha256": _sha256_bytes(fx["chunks"].read_bytes())},
            "corpus-manifest.json": {"path": str(fx["corpus"]),
                                     "sha256": _sha256_bytes(
                                         fx["corpus"].read_bytes())},
        },
        "frozen_outputs": {},
        "phase6a_outputs": {
            "baseline-summary.json": _sha256_bytes(
                (phase6a / "baseline-summary.json").read_bytes()),
            "per-case-retrieval-results.jsonl": _sha256_bytes(
                (phase6a / "per-case-retrieval-results.jsonl").read_bytes()),
        },
        "outputs": {
            name: _sha256_bytes((hd / name).read_bytes())
            for name in ("contract-baseline-summary.json",
                         "per-case-retrieval-results.jsonl",
                         "contract-validation-report.md",
                         "comparison-to-phase6a.md",
                         "comparison-to-phase6b0.md",
                         "data-quality-report.json")
        },
        "manifest_sha256": "PLACEHOLDER",
    }
    hd_manifest["manifest_sha256"] = _self_hash(hd_manifest)
    (hd / "manifest.json").write_text(_canonical(hd_manifest),
                                      encoding="utf-8")
    return hd


@pytest.fixture()
def fx(tmp_path):
    return _fixture_full(tmp_path)


def _run(fx: dict[str, Path], tmp_path: Path, out_dir: Path | None = None,
         data_dir: Path | None = None, verify_determinism: bool = False,
         strategy: str = "mechanical-clause-rrf", prior_run_dir=None,
         **kwargs) -> dict:
    b0 = _fixture_b0_dir(tmp_path / "b0", fx)
    hd = _fixture_hardened_dir(tmp_path / "hardened", fx)
    return abl.run_ablation(
        revision_dir=fx["revision"], chunks_path=fx["chunks"],
        chunk_manifest_path=fx["chunk_manifest"],
        current_draft_path=fx["draft"],
        corpus_manifest_path=fx["corpus"],
        phase6a_dir=fx["phase6a"], phase6b0_dir=b0, hardened_dir=hd,
        out_dir=out_dir or (tmp_path / "out"),
        data_dir=data_dir or (tmp_path / "data"),
        repo_root=fx["root"], strategy=strategy,
        verify_determinism=verify_determinism,
        prior_run_dir=prior_run_dir, **kwargs,
    )


# ── Group 1: hardened manifest re-verification (lineage) ──────────────

def test_verify_hardened_manifest_ok_on_fixture(fx, tmp_path):
    hd = _fixture_hardened_dir(tmp_path / "hardened", fx)
    report = abl.verify_hardened_manifest(hd, fx["phase6a"])
    assert report["verified"] is True
    assert report["drift"] == []
    assert len(report["checks"]) >= 6


def test_verify_hardened_manifest_detects_tamper(fx, tmp_path):
    hd = _fixture_hardened_dir(tmp_path / "hardened", fx)
    path = hd / "contract-baseline-summary.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["metrics"]["overall"]["recall@5"] = 0.5
    path.write_text(_canonical(doc), encoding="utf-8")
    report = abl.verify_hardened_manifest(hd, fx["phase6a"])
    assert report["verified"] is False
    assert any("outputs/contract-baseline-summary.json" in d["name"]
               for d in report["drift"])


def test_verify_hardened_manifest_detects_self_hash_drift(fx, tmp_path):
    hd = _fixture_hardened_dir(tmp_path / "hardened", fx)
    path = hd / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["task"] = "tampered"
    path.write_text(_canonical(doc), encoding="utf-8")
    report = abl.verify_hardened_manifest(hd, fx["phase6a"])
    assert report["verified"] is False
    assert any(d["kind"] == "manifest_self_hash" for d in report["drift"])


# ── Group 2: gate evaluation (mechanical, per build) ──────────────────

def _overall(recall5=0.6, recall10=0.66, recall20=0.75, ndcg5=0.52,
             ndcg10=0.54, ndcg20=0.57, mrr=0.53,
             src5=0.95, src10=0.98, src20=0.98) -> dict:
    return {"recall@5": recall5, "recall@10": recall10, "recall@20": recall20,
            "ndcg@5": ndcg5, "ndcg@10": ndcg10, "ndcg@20": ndcg20,
            "mrr": mrr, "source_recall@5": src5, "source_recall@10": src10,
            "source_recall@20": src20}


def _cd(recall5=0.35, src5=0.9) -> dict:
    return {"recall@5": recall5, "source_recall@5": src5}


def _build(base, cand, base_cd, cand_cd):
    return {"baseline": base, "candidate": cand,
            "baseline_cd": base_cd, "candidate_cd": cand_cd}


def test_gate_no_promotion_when_cd_gain_below_threshold():
    b = _build(_overall(), _overall(recall5=0.61), _cd(recall5=0.30),
               _cd(recall5=0.31))  # gain +0.01 < +0.03
    out = abl.evaluate_gate(build1=b, build2=b, noise_cd_recall5=0.0,
                            checks_ok=True)
    assert out["decision"] == "NO_PROMOTION"
    cond = {c["id"]: c for c in out["conditions"]}
    assert cond["cd_recall@5_gain"]["ok"] is False


def test_gate_no_promotion_when_overall_recall_drops():
    b = _build(_overall(recall5=0.60), _overall(recall5=0.58),
               _cd(recall5=0.30), _cd(recall5=0.34))
    out = abl.evaluate_gate(build1=b, build2=b, noise_cd_recall5=0.0,
                            checks_ok=True)
    assert out["decision"] == "NO_PROMOTION"
    cond = {c["id"]: c for c in out["conditions"]}
    assert cond["overall_recall@5_no_drop"]["ok"] is False


def test_gate_no_promotion_when_ndcg_or_mrr_drops():
    b = _build(_overall(ndcg10=0.54, mrr=0.53), _overall(ndcg10=0.52, mrr=0.53),
               _cd(recall5=0.30), _cd(recall5=0.35))
    out = abl.evaluate_gate(build1=b, build2=b, noise_cd_recall5=0.0,
                            checks_ok=True)
    assert out["decision"] == "NO_PROMOTION"
    cond = {c["id"]: c for c in out["conditions"]}
    assert cond["overall_ndcg10_mrr_no_drop"]["ok"] is False


def test_gate_no_promotion_when_cd_source_recall_drops():
    b = _build(_overall(), _overall(), _cd(recall5=0.30, src5=0.95),
               _cd(recall5=0.35, src5=0.94))
    out = abl.evaluate_gate(build1=b, build2=b, noise_cd_recall5=0.0,
                            checks_ok=True)
    assert out["decision"] == "NO_PROMOTION"
    cond = {c["id"]: c for c in out["conditions"]}
    assert cond["cd_source_recall@5_no_drop"]["ok"] is False


def test_gate_no_promotion_unless_both_builds_pass():
    b1 = _build(_overall(), _overall(recall5=0.61), _cd(recall5=0.30),
                _cd(recall5=0.35))
    b2 = _build(_overall(), _overall(recall5=0.58), _cd(recall5=0.30),
                _cd(recall5=0.35))  # build2 全量 recall@5 下降 0.02 > 0.01
    out = abl.evaluate_gate(build1=b1, build2=b2, noise_cd_recall5=0.0,
                            checks_ok=True)
    assert out["decision"] == "NO_PROMOTION"
    cond = {c["id"]: c for c in out["conditions"]}
    assert cond["overall_recall@5_no_drop"]["ok"] is False
    assert cond["overall_recall@5_no_drop"]["build2"]["ok"] is False
    assert cond["overall_recall@5_no_drop"]["build1"]["ok"] is True


def test_gate_no_promotion_when_gain_within_recorded_noise():
    b = _build(_overall(), _overall(recall5=0.61), _cd(recall5=0.30),
               _cd(recall5=0.34))  # gain +0.04 ≥ 0.03
    out = abl.evaluate_gate(build1=b, build2=b, noise_cd_recall5=0.05,
                            checks_ok=True)  # 噪声 0.05：增益不明显大于噪声
    assert out["decision"] == "NO_PROMOTION"
    cond = {c["id"]: c for c in out["conditions"]}
    assert cond["exceeds_recorded_noise"]["ok"] is False


def test_gate_no_promotion_when_checks_fail():
    b = _build(_overall(), _overall(recall5=0.61), _cd(recall5=0.30),
               _cd(recall5=0.35))
    out = abl.evaluate_gate(build1=b, build2=b, noise_cd_recall5=0.0,
                            checks_ok=False)
    assert out["decision"] == "NO_PROMOTION"
    assert out["failures"] == ["all_checks_passed"]


def test_gate_promising_when_all_conditions_met():
    b1 = _build(_overall(), _overall(recall5=0.61, ndcg10=0.55, mrr=0.54),
                _cd(recall5=0.30), _cd(recall5=0.35))
    b2 = _build(_overall(), _overall(recall5=0.61, ndcg10=0.55, mrr=0.54),
                _cd(recall5=0.30), _cd(recall5=0.35))
    out = abl.evaluate_gate(build1=b1, build2=b2, noise_cd_recall5=0.001,
                            checks_ok=True)
    assert out["decision"] == "EXPERIMENT_PROMISING"
    assert all(c["ok"] for c in out["conditions"])
    assert out["failures"] == []
    # 决策永不改变默认策略（机械记录）
    assert out["note"]


# ── Group 3: fail-closed runs ─────────────────────────────────────────

def test_ablation_fixture_ok(fx, tmp_path):
    out_dir = tmp_path / "out"
    summary = _run(fx, tmp_path, out_dir=out_dir)
    assert summary["status"] == "ok"
    assert summary["case_count"] == 6
    assert {p.name for p in out_dir.iterdir()} == ABLATION_OUTPUT_FILES
    assert summary["verification"]["frozen_verified"] is True
    assert summary["verification"]["phase6a_verified"] is True
    assert summary["verification"]["phase6b0_verified"] is True
    assert summary["verification"]["hardened_verified"] is True
    assert summary["gate"]["decision"] in ("EXPERIMENT_PROMISING",
                                           "NO_PROMOTION")
    assert summary["strategy"]["candidate"]["name"] == "mechanical-clause-rrf"
    assert summary["strategy"]["candidate"]["no_llm"] is True
    assert summary["strategy"]["baseline"]["name"] == "single-query"
    # 双臂都产出 6 行 per-case
    base_rows = abl.bl6a.load_jsonl(out_dir / "per-case-results-baseline.jsonl")
    cand_rows = abl.bl6a.load_jsonl(out_dir / "per-case-results-candidate.jsonl")
    assert len(base_rows) == len(cand_rows) == 6
    assert all("strategy" in r and "provenance" in r for r in cand_rows)
    assert not any("strategy" in r for r in base_rows)  # 基线行保持既有形状


def test_fail_closed_on_hardened_drift(fx, tmp_path):
    hd = _fixture_hardened_dir(tmp_path / "hardened", fx)
    path = hd / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["task"] = "tampered"
    path.write_text(_canonical(doc), encoding="utf-8")
    b0 = _fixture_b0_dir(tmp_path / "b0", fx)
    out_dir = tmp_path / "out"
    with pytest.raises(abl.BaselineDrift):
        abl.run_ablation(
            revision_dir=fx["revision"], chunks_path=fx["chunks"],
            chunk_manifest_path=fx["chunk_manifest"],
            current_draft_path=fx["draft"],
            corpus_manifest_path=fx["corpus"],
            phase6a_dir=fx["phase6a"], phase6b0_dir=b0, hardened_dir=hd,
            out_dir=out_dir, data_dir=tmp_path / "data",
            repo_root=fx["root"], verify_determinism=False,
        )
    assert not out_dir.exists()  # fail-closed：零产物


def test_fail_closed_on_frozen_drift(fx, tmp_path):
    with open(fx["evidence"], "a", encoding="utf-8") as f:
        f.write("\n")
    with pytest.raises(abl.BaselineDrift):
        _run(fx, tmp_path)
    assert not (tmp_path / "out").exists()


def test_fail_closed_on_b0_drift(fx, tmp_path):
    b0 = _fixture_b0_dir(tmp_path / "b0", fx)
    path = b0 / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["task"] = "tampered"
    path.write_text(_canonical(doc), encoding="utf-8")
    out_dir = tmp_path / "out"
    with pytest.raises(abl.BaselineDrift):
        abl.run_ablation(
            revision_dir=fx["revision"], chunks_path=fx["chunks"],
            chunk_manifest_path=fx["chunk_manifest"],
            current_draft_path=fx["draft"],
            corpus_manifest_path=fx["corpus"],
            phase6a_dir=fx["phase6a"], phase6b0_dir=b0,
            hardened_dir=_fixture_hardened_dir(tmp_path / "hardened", fx),
            out_dir=out_dir, data_dir=tmp_path / "data",
            repo_root=fx["root"], verify_determinism=False,
        )
    assert not out_dir.exists()


# ── Group 4: isolation / lineage integrity ────────────────────────────

def test_does_not_touch_protected_inputs(fx, tmp_path, monkeypatch):
    import src.rag as rag

    user_dir = tmp_path / "user_chroma"
    monkeypatch.setattr(rag, "CHROMA_DB_PATH", str(user_dir))
    b0 = _fixture_b0_dir(tmp_path / "b0", fx)
    hd = _fixture_hardened_dir(tmp_path / "hardened", fx)
    guard = [fx["root"], b0, hd]
    before = _snapshot_tree(guard)
    out_dir = tmp_path / "out"
    summary = abl.run_ablation(
        revision_dir=fx["revision"], chunks_path=fx["chunks"],
        chunk_manifest_path=fx["chunk_manifest"],
        current_draft_path=fx["draft"],
        corpus_manifest_path=fx["corpus"],
        phase6a_dir=fx["phase6a"], phase6b0_dir=b0, hardened_dir=hd,
        out_dir=out_dir, repo_root=fx["root"], verify_determinism=False,
    )
    after = _snapshot_tree(guard)
    assert before == after
    if user_dir.exists():
        assert not list(user_dir.rglob("*"))
    assert summary["manifest"]["isolation"]["cleaned"] is True
    assert summary["manifest"]["isolation"]["no_user_index_touched"] is True


def test_manifest_self_hash_lineage_and_outputs(fx, tmp_path):
    out_dir = tmp_path / "out"
    summary = _run(fx, tmp_path, out_dir=out_dir)
    manifest = summary["manifest"]
    assert manifest["manifest_sha256"] == abl.bl6a.self_hash(manifest)
    lineage = manifest["lineage"]
    hd = _fixture_hardened_dir(tmp_path / "hardened", fx)
    hd_manifest = json.loads((hd / "manifest.json").read_text(encoding="utf-8"))
    assert lineage["hardened_manifest_sha256"] == hd_manifest["manifest_sha256"]
    assert lineage["hardened_verified"] is True
    assert lineage["phase6b0_verified"] is True
    assert lineage["phase6a_verified"] is True
    assert lineage["frozen_verified"] is True
    for name, sha in manifest["outputs"].items():
        p = out_dir / name
        assert p.is_file()
        assert hashlib.sha256(p.read_bytes()).hexdigest() == sha
    # outputs 不含 manifest.json（自哈希约定，与 B0/B0.1 一致）
    assert set(manifest["outputs"]) == ABLATION_OUTPUT_FILES - {"manifest.json"}
    # hardened 输出以字节 SHA 记录
    for name, sha in manifest["hardened_outputs"].items():
        p = hd / name
        assert p.is_file()
        assert hashlib.sha256(p.read_bytes()).hexdigest() == sha
    # not_measured 声明
    assert manifest["not_measured"]["answer_quality"]["measured"] is False
    assert manifest["not_measured"]["citation_faithfulness"]["measured"] is False
    assert manifest["not_measured"]["refusal_accuracy"]["measured"] is False


def test_data_quality_report_passes(fx, tmp_path):
    out_dir = tmp_path / "out"
    _run(fx, tmp_path, out_dir=out_dir)
    dq = json.loads((out_dir / "data-quality-report.json")
                    .read_text(encoding="utf-8"))
    # C1.1 语义修正：passed/error_count 只反映核心 data-quality checks
    assert dq["passed"] is True
    assert dq["error_count"] == 0
    names = {c["name"] for c in dq["checks"]}
    assert "conservation.case_counts" in names
    assert "conservation.mapping_failures_zero" in names
    assert "strategy.variants_literal_substrings" in names
    assert "strategy.candidate_no_duplicate_chunk_ids" in names
    assert "lineage.hardened_verified" in names
    # 核心 checks 无 false；gate 条件绝不混入 data-quality checks
    assert all(c["ok"] for c in dq["checks"])
    assert not any(c["name"].startswith("gate.") for c in dq["checks"])
    # gate 结果独立成段：promotion_eligibility（不是 data-quality 失败）
    pe = dq["promotion_eligibility"]
    assert pe["decision"] in ("EXPERIMENT_PROMISING", "NO_PROMOTION")
    assert len(pe["conditions"]) == 6
    assert set(pe["failures"]) == {
        c["id"] for c in pe["conditions"] if not c["ok"]}
    assert any(c["name"] == "gate.conditions_complete" for c in pe["checks"])


def test_data_quality_gate_separation(fx, tmp_path):
    out_dir = tmp_path / "out"
    summary = _run(fx, tmp_path, out_dir=out_dir)
    dq = json.loads((out_dir / "data-quality-report.json")
                    .read_text(encoding="utf-8"))
    # 失败 gate 只存在于 promotion_eligibility，data_quality.passed 不暗示
    # promotion 通过
    assert dq["passed"] is True
    assert not any(not c["ok"] for c in dq["checks"])
    pe = dq["promotion_eligibility"]
    assert pe["decision"] == summary["gate"]["decision"]
    assert pe["failures"] == summary["gate"]["failures"]
    assert sorted(pe["failures"]) == sorted(
        c["id"] for c in summary["gate"]["conditions"] if not c["ok"])
    assert "data-quality" in pe["note"] and "promotion" in pe["note"]


def test_cross_document_group_reported(fx, tmp_path):
    out_dir = tmp_path / "out"
    summary = _run(fx, tmp_path, out_dir=out_dir)
    cd = summary["cross_document"]
    assert cd["n"] == 1  # fixture 只有一个 cross_document case
    assert "baseline" in cd and "candidate" in cd
    assert "deltas" in cd
    md = (out_dir / "cross-document-analysis.md").read_text(encoding="utf-8")
    assert "cross_document" in md
    assert "HNSW" in md


def test_selection_decision_document(fx, tmp_path):
    out_dir = tmp_path / "out"
    summary = _run(fx, tmp_path, out_dir=out_dir)
    md = (out_dir / "selection-decision.md").read_text(encoding="utf-8")
    assert summary["gate"]["decision"] in md
    assert "NO_PROMOTION" in md or "EXPERIMENT_PROMISING" in md
    # 明确声明不改默认产品策略
    assert "默认产品检索策略" in md and "不改变" in md


def test_prior_run_comparison_recorded(fx, tmp_path):
    run1_dir = tmp_path / "run1"
    _run(fx, tmp_path, out_dir=run1_dir)
    out_dir = tmp_path / "out"
    summary = _run(fx, tmp_path, out_dir=out_dir, prior_run_dir=run1_dir)
    prior = summary["manifest"]["verification"]["prior_run"]
    assert prior["prior_run_dir"] == str(run1_dir)
    assert "baseline" in prior["aggregate_deltas"]
    assert "candidate" in prior["aggregate_deltas"]
    assert "per_case_diff_count" in prior


# ── Group 5: CLI / no-LLM ─────────────────────────────────────────────

def test_no_llm_generation_calls(fx, tmp_path, monkeypatch):
    import src.rag as rag
    import src.llm_gateway as llm
    import src.rag_query_decomposer as qd
    import src.rag_query_rewriter as qr

    def _forbid(*args, **kwargs):
        raise AssertionError("LLM/generation/rewriting path invoked")

    monkeypatch.setattr(rag, "answer_with_llm_history", _forbid)
    monkeypatch.setattr(llm, "llm_call", _forbid)
    monkeypatch.setattr(qd, "decompose_query_llm", _forbid)
    monkeypatch.setattr(qr, "rewrite_query_llm", _forbid)
    summary = _run(fx, tmp_path)
    assert summary["status"] == "ok"


def test_main_exit_codes(fx, tmp_path):
    b0 = _fixture_b0_dir(tmp_path / "b0", fx)
    hd = _fixture_hardened_dir(tmp_path / "hardened", fx)
    args = [
        "--revision-dir", str(fx["revision"]),
        "--chunks", str(fx["chunks"]),
        "--chunk-manifest", str(fx["chunk_manifest"]),
        "--current-draft", str(fx["draft"]),
        "--corpus-manifest", str(fx["corpus"]),
        "--phase6a-dir", str(fx["phase6a"]),
        "--phase6b0-dir", str(b0),
        "--hardened-dir", str(hd),
        "--output", str(tmp_path / "out"),
        "--data-dir", str(tmp_path / "data"),
        "--repo-root", str(fx["root"]),
        "--skip-determinism",
    ]
    assert abl.main(args) == 0
    assert (tmp_path / "out" / "manifest.json").is_file()
    # 未知策略 → exit 1（配置错误，非漂移），零产物
    out2 = tmp_path / "out2"
    code = abl.main(args[:10] + ["--strategy", "bogus"] + args[10:] + [
        "--output", str(out2), "--data-dir", str(tmp_path / "data2")])
    assert code == 1
    assert not out2.exists()
    # hardened 漂移 → exit 2，零产物
    path = hd / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["task"] = "tampered"
    path.write_text(_canonical(doc), encoding="utf-8")
    out3 = tmp_path / "out3"
    code = abl.main([
        "--revision-dir", str(fx["revision"]),
        "--chunks", str(fx["chunks"]),
        "--chunk-manifest", str(fx["chunk_manifest"]),
        "--current-draft", str(fx["draft"]),
        "--corpus-manifest", str(fx["corpus"]),
        "--phase6a-dir", str(fx["phase6a"]),
        "--phase6b0-dir", str(b0),
        "--hardened-dir", str(hd),
        "--output", str(out3),
        "--data-dir", str(tmp_path / "data3"),
        "--repo-root", str(fx["root"]),
    ])
    assert code == 2
    assert not out3.exists()


# ── Group 6: real frozen data (skip-guarded) ──────────────────────────

pytestmark_real = pytest.mark.skipif(
    not abl.HARDENED_DIR.exists(),
    reason="frozen v2.0.11 revision and hardened baseline are local artifacts",
)


@pytestmark_real
def test_real_hardened_manifest_verifies():
    report = abl.verify_hardened_manifest(abl.HARDENED_DIR, abl.PHASE6A_DIR)
    assert report["verified"] is True
    assert report["drift"] == []
    assert len(report["checks"]) >= 50


@pytestmark_real
def test_real_case_conservation_and_cd_count():
    cases, mapping = abl.bl6a.load_cases(
        abl.FROZEN_REVISION_DIR / "draft-after.jsonl",
        abl.FROZEN_REVISION_DIR / "evidence-after.jsonl",
        abl.CHUNKS_PATH,
    )
    assert len(cases) == 136
    assert len({c["case_id"] for c in cases}) == 136  # 唯一守恒
    truth = [c for c in cases if c["relevant_chunk_ids"]]
    refusal = [c for c in cases if c["should_refuse"]]
    assert len(truth) == 105
    assert len(refusal) == 31
    assert len(mapping["mapping"]["mapping_failures"]) == 0
    cd = [c for c in cases if c["query_type"] == "cross_document"]
    assert len(cd) == 26
    assert all(c["relevant_chunk_ids"] for c in cd)  # 26 个都有 chunk 真值
