"""Tests for scripts.evaluate_v211_frozen_product_contract_hardened — Phase 6-B0.1.

The hardened contract baseline must:
- re-verify the **old Phase 6-B0 manifest** (self-hash + all inputs /
  frozen_outputs / outputs byte SHAs) before producing anything — lineage
  proof, fail-closed with zero outputs;
- run the full contract pipeline (frozen 61 checks → 6A manifest → snapshot →
  full product entry index → 136-case retrieval) into a NEW directory
  (never overwriting the old B0 artifacts);
- record the old B0 manifest SHA as lineage in the hardened manifest and
  produce an honest comparison-vs-B0 report (aggregate deltas, denominators,
  per-case diffs; HNSW perturbation recorded, never asserted away);
- not touch the old B0 dir, frozen inputs, or the user index; no LLM path.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.evaluate_v211_frozen_product_contract_hardened as hbl
from tests.test_evaluate_v211_frozen_product_contract import (  # noqa: E402
    _canonical, _self_hash, _sha256_bytes, _fixture_full,
)
from tests.test_index_contract import _snapshot_tree  # noqa: E402


def _fixture_b0_dir(root: Path, fx: dict[str, Path]) -> Path:
    """fake 旧 B0 基线目录（6 产物 + 自洽 manifest；frozen_outputs 空）。"""
    b0 = root / "phase6b0"
    b0.mkdir(parents=True, exist_ok=True)
    metric_keys = (
        "recall@5", "recall@10", "recall@20",
        "ndcg@5", "ndcg@10", "ndcg@20", "mrr",
        "source_recall@5", "source_recall@10", "source_recall@20",
    )
    summary = {
        "metrics": {"overall": {
            key: 1.0 for key in metric_keys
        } | {"denominators": {
            "total_cases": 6, "chunk_metrics_cases": 4,
            "no_chunk_truth_cases": 2, "mapping_failure_rows": 0,
        }}},
        "determinism": {"difference_count": 0, "metric_difference_count": 0},
        "contract": {"fingerprint": "0" * 64},
    }
    (b0 / "contract-baseline-summary.json").write_text(
        _canonical(summary), encoding="utf-8")
    rows = []
    for cid_ in ("en-001", "en-002", "zh-003", "mixed-004",
                 "zh-005", "en-006"):
        rows.append({"case_id": cid_,
                     "metrics": ({k: 1.0 for k in metric_keys}
                                 if cid_ not in ("zh-005", "en-006") else {}),
                     "retrieved_chunk_ids": []})
    (b0 / "per-case-retrieval-results.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")
    for name in ("contract-validation-report.md", "comparison-to-phase6a.md",
                 "data-quality-report.json"):
        (b0 / name).write_text(_canonical({"fake": name}), encoding="utf-8")
    b0_manifest = {
        "task": "fixture-phase6b0",
        "inputs": {
            "chunks.jsonl": {"path": str(fx["chunks"]),
                             "sha256": _sha256_bytes(fx["chunks"].read_bytes())},
            "chunk-manifest.json": {"path": str(fx["chunk_manifest"]),
                                    "sha256": _sha256_bytes(
                                        fx["chunk_manifest"].read_bytes())},
            "corpus-manifest.json": {"path": str(fx["corpus"]),
                                     "sha256": _sha256_bytes(
                                         fx["corpus"].read_bytes())},
        },
        "frozen_outputs": {},
        "outputs": {
            name: _sha256_bytes((b0 / name).read_bytes())
            for name in ("contract-baseline-summary.json",
                         "per-case-retrieval-results.jsonl",
                         "contract-validation-report.md",
                         "comparison-to-phase6a.md",
                         "data-quality-report.json")
        },
        "manifest_sha256": "PLACEHOLDER",
    }
    b0_manifest["manifest_sha256"] = _self_hash(b0_manifest)
    (b0 / "manifest.json").write_text(_canonical(b0_manifest),
                                      encoding="utf-8")
    return b0


@pytest.fixture()
def fx(tmp_path):
    return _fixture_full(tmp_path)


def _run(fx: dict[str, Path], tmp_path: Path, out_dir: Path | None = None,
         data_dir: Path | None = None, verify_determinism: bool = False,
         **kwargs) -> dict:
    b0 = _fixture_b0_dir(tmp_path / "b0", fx)
    return hbl.run_hardened_baseline(
        revision_dir=fx["revision"],
        chunks_path=fx["chunks"],
        chunk_manifest_path=fx["chunk_manifest"],
        current_draft_path=fx["draft"],
        corpus_manifest_path=fx["corpus"],
        phase6a_dir=fx["phase6a"],
        phase6b0_dir=b0,
        out_dir=out_dir or (tmp_path / "out"),
        data_dir=data_dir or (tmp_path / "data"),
        repo_root=fx["root"],
        verify_determinism=verify_determinism,
        **kwargs,
    )


# ── Group 1: old B0 manifest re-verification (lineage) ────────────────

def test_verify_b0_manifest_ok_on_fixture(fx, tmp_path):
    b0 = _fixture_b0_dir(tmp_path / "b0", fx)
    report = hbl.verify_b0_manifest(b0)
    assert report["verified"] is True
    assert report["drift"] == []
    assert len(report["checks"]) >= 4


def test_verify_b0_manifest_detects_tamper(fx, tmp_path):
    b0 = _fixture_b0_dir(tmp_path / "b0", fx)
    path = b0 / "contract-baseline-summary.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["metrics"]["overall"]["recall@5"] = 0.5
    path.write_text(_canonical(doc), encoding="utf-8")
    report = hbl.verify_b0_manifest(b0)
    assert report["verified"] is False
    assert any("outputs/contract-baseline-summary.json" in d["name"]
               for d in report["drift"])


def test_verify_b0_manifest_detects_self_hash_drift(fx, tmp_path):
    b0 = _fixture_b0_dir(tmp_path / "b0", fx)
    path = b0 / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["task"] = "tampered"
    path.write_text(_canonical(doc), encoding="utf-8")
    report = hbl.verify_b0_manifest(b0)
    assert report["verified"] is False
    assert any(d["kind"] == "manifest_self_hash" for d in report["drift"])


# ── Group 2: fail-closed runs ─────────────────────────────────────────

def test_hardened_baseline_fixture_ok(fx, tmp_path):
    out_dir = tmp_path / "out"
    summary = _run(fx, tmp_path, out_dir=out_dir)
    assert summary["status"] == "ok"
    assert summary["case_count"] == 6
    expected = set(hbl.HARDENED_OUTPUT_FILES)
    assert {p.name for p in out_dir.iterdir()} == expected
    assert summary["b0_report"]["verified"] is True
    # lineage SHA recorded == 旧 B0 manifest 的实际 self-hash
    b0_manifest = json.loads(
        (summary["b0_dir"] / "manifest.json").read_text(encoding="utf-8"))
    assert summary["manifest"]["lineage"]["phase6b0_manifest_sha256"] == \
        b0_manifest["manifest_sha256"]


def test_fail_closed_on_b0_drift(fx, tmp_path):
    b0 = _fixture_b0_dir(tmp_path / "b0", fx)
    path = b0 / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["task"] = "tampered"
    path.write_text(_canonical(doc), encoding="utf-8")
    out_dir = tmp_path / "out"
    with pytest.raises(hbl.BaselineDrift):
        hbl.run_hardened_baseline(
            revision_dir=fx["revision"], chunks_path=fx["chunks"],
            chunk_manifest_path=fx["chunk_manifest"],
            current_draft_path=fx["draft"],
            corpus_manifest_path=fx["corpus"],
            phase6a_dir=fx["phase6a"], phase6b0_dir=b0,
            out_dir=out_dir, data_dir=tmp_path / "data",
            repo_root=fx["root"], verify_determinism=False,
        )
    assert not out_dir.exists()  # fail-closed：零产物


def test_fail_closed_on_frozen_drift(fx, tmp_path):
    b0 = _fixture_b0_dir(tmp_path / "b0", fx)
    with open(fx["evidence"], "a", encoding="utf-8") as f:
        f.write("\n")
    out_dir = tmp_path / "out"
    with pytest.raises(hbl.BaselineDrift):
        hbl.run_hardened_baseline(
            revision_dir=fx["revision"], chunks_path=fx["chunks"],
            chunk_manifest_path=fx["chunk_manifest"],
            current_draft_path=fx["draft"],
            corpus_manifest_path=fx["corpus"],
            phase6a_dir=fx["phase6a"], phase6b0_dir=b0,
            out_dir=out_dir, data_dir=tmp_path / "data",
            repo_root=fx["root"], verify_determinism=False,
        )
    assert not out_dir.exists()


# ── Group 3: isolation / lineage integrity ────────────────────────────

def test_does_not_touch_b0_or_frozen_inputs(fx, tmp_path, monkeypatch):
    import src.rag as rag

    user_dir = tmp_path / "user_chroma"
    monkeypatch.setattr(rag, "CHROMA_DB_PATH", str(user_dir))
    b0 = _fixture_b0_dir(tmp_path / "b0", fx)
    guard = [fx["root"], b0]
    before = _snapshot_tree(guard)
    out_dir = tmp_path / "out"
    summary = hbl.run_hardened_baseline(
        revision_dir=fx["revision"], chunks_path=fx["chunks"],
        chunk_manifest_path=fx["chunk_manifest"],
        current_draft_path=fx["draft"],
        corpus_manifest_path=fx["corpus"],
        phase6a_dir=fx["phase6a"], phase6b0_dir=b0,
        out_dir=out_dir, repo_root=fx["root"], verify_determinism=False,
    )
    after = _snapshot_tree(guard)
    assert before == after  # 旧 B0 产物与冻结输入分毫未动
    if user_dir.exists():
        assert not list(user_dir.rglob("*"))
    assert summary["manifest"]["isolation"]["cleaned"] is True


def test_manifest_lineage_and_shas(fx, tmp_path):
    out_dir = tmp_path / "out"
    summary = _run(fx, tmp_path, out_dir=out_dir)
    manifest = summary["manifest"]
    assert manifest["manifest_sha256"] == hbl.bl6a.self_hash(manifest)
    # lineage：旧 B0 manifest SHA + 复算通过
    lineage = manifest["lineage"]
    assert lineage["phase6b0_manifest_verified"] is True
    b0_manifest = json.loads(
        (summary["b0_dir"] / "manifest.json").read_text(encoding="utf-8"))
    assert lineage["phase6b0_manifest_sha256"] == b0_manifest["manifest_sha256"]
    # 冻结输入以字节 SHA 记录
    for name in ("chunks.jsonl", "chunk-manifest.json",
                 "corpus-manifest.json", "source:alpha.md"):
        rec = manifest["inputs"][name]
        assert Path(rec["path"]).is_file()
        assert hashlib.sha256(Path(rec["path"]).read_bytes()).hexdigest() == \
            rec["sha256"]
    # 7 个产物 name -> sha 闭环
    for name, sha in manifest["outputs"].items():
        p = out_dir / name
        assert p.is_file()
        assert hashlib.sha256(p.read_bytes()).hexdigest() == sha
    assert "comparison-to-phase6b0.md" in manifest["outputs"]


def test_data_quality_report_includes_lineage_checks(fx, tmp_path):
    out_dir = tmp_path / "out"
    _run(fx, tmp_path, out_dir=out_dir)
    dq = json.loads((out_dir / "data-quality-report.json")
                    .read_text(encoding="utf-8"))
    assert dq["passed"] is True
    assert dq["error_count"] == 0
    names = {c["name"] for c in dq["checks"]}
    assert "contract.b0_manifest_verified" in names
    assert "contract.b0_lineage_sha" in names


def test_comparison_to_b0_honest(fx, tmp_path):
    out_dir = tmp_path / "out"
    summary = _run(fx, tmp_path, out_dir=out_dir)
    cmp_b0 = summary["comparison_b0"]
    assert "aggregate_deltas" in cmp_b0
    assert cmp_b0["denominators"]["equal"] is True
    assert "per_case_metric_diff_count" in cmp_b0
    assert "per_case_retrieval_diff_count" in cmp_b0
    assert "fingerprint" in cmp_b0
    assert "identical" in cmp_b0["fingerprint"]
    md = (out_dir / "comparison-to-phase6b0.md").read_text(encoding="utf-8")
    assert "Phase 6-B0.1" in md
    assert "HNSW" in md


def test_no_llm_generation_calls(fx, tmp_path, monkeypatch):
    import src.rag as rag
    import src.llm_gateway as llm

    def _forbid(*args, **kwargs):
        raise AssertionError("LLM/generation path invoked during baseline")

    monkeypatch.setattr(rag, "answer_with_llm_history", _forbid)
    monkeypatch.setattr(llm, "llm_call", _forbid)
    summary = _run(fx, tmp_path)
    assert summary["status"] == "ok"


def test_main_exit_codes(fx, tmp_path):
    b0 = _fixture_b0_dir(tmp_path / "b0", fx)
    args = [
        "--revision-dir", str(fx["revision"]),
        "--chunks", str(fx["chunks"]),
        "--chunk-manifest", str(fx["chunk_manifest"]),
        "--current-draft", str(fx["draft"]),
        "--corpus-manifest", str(fx["corpus"]),
        "--phase6a-dir", str(fx["phase6a"]),
        "--phase6b0-dir", str(b0),
        "--output", str(tmp_path / "out"),
        "--data-dir", str(tmp_path / "data"),
        "--repo-root", str(fx["root"]),
        "--skip-determinism",
    ]
    assert hbl.main(args) == 0
    assert (tmp_path / "out" / "manifest.json").is_file()
    # b0 漂移 → exit 2，零产物
    path = b0 / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["task"] = "tampered"
    path.write_text(_canonical(doc), encoding="utf-8")
    out2 = tmp_path / "out2"
    code = hbl.main([
        "--revision-dir", str(fx["revision"]),
        "--chunks", str(fx["chunks"]),
        "--chunk-manifest", str(fx["chunk_manifest"]),
        "--current-draft", str(fx["draft"]),
        "--corpus-manifest", str(fx["corpus"]),
        "--phase6a-dir", str(fx["phase6a"]),
        "--phase6b0-dir", str(b0),
        "--output", str(out2),
        "--data-dir", str(tmp_path / "data2"),
        "--repo-root", str(fx["root"]),
    ])
    assert code == 2
    assert not out2.exists()


# ── Group 4: real frozen data (skip-guarded) ──────────────────────────

pytestmark_real = pytest.mark.skipif(
    not hbl.PHASE6B0_DIR.exists(),
    reason="frozen v2.0.11 revision and Phase 6-B0 baseline are local artifacts",
)


@pytestmark_real
def test_real_b0_manifest_verifies():
    report = hbl.verify_b0_manifest(hbl.PHASE6B0_DIR)
    assert report["verified"] is True
    assert report["drift"] == []
    assert len(report["checks"]) >= 50
