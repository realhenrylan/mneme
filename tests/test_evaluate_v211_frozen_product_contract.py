"""Tests for scripts.evaluate_v211_frozen_product_contract — Phase 6-B0.

The contract baseline must be fail-closed and side-effect-free:
- freeze/candidate/targeted-review manifests AND the Phase 6-A baseline
  manifest are recomputed first; any drift aborts with zero new outputs;
- the index is built through the *full product entry*
  (``src.rag.prepare_index`` + snapshot) into a disposable Chroma dir, with
  collection manifest + BM25 sidecar co-located there;
- the chunk snapshot contract is verified before any write; the collection
  manifest records the contract fingerprint;
- comparison vs Phase 6-A is reported honestly (HNSW perturbation recorded,
  never asserted away);
- no LLM/generation path; frozen inputs byte-identical; no user-index touch.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.evaluate_v211_frozen_product_contract as cbl
from tests.test_evaluate_v211_frozen_product_baseline import (  # noqa: E402
    _canonical, _self_hash, _sha256_bytes, _sha256_text, _snapshot_tree,
    _write_jsonl,
)
from tests.test_index_contract import (  # noqa: E402
    SOURCE_CHUNKS, _chunk_prefix, _chunk_rows, _write_chunks,
    _write_corpus_manifest,
)


def _evidence_row(case_id: str, chunk_id: str, source: str, text: str) -> dict:
    return {
        "case_id": case_id,
        "chunk_id": chunk_id,
        "chunk_text_sha256": _sha256_text(text),
        "source_id": source,
        "snippet": " ".join(text.split())[:40],
        "raw_evidence_span": text,
        "snippet_sha256": _sha256_text(" ".join(text.split())[:40]),
        "char_range": {"start": 0, "end": len(text)},
        "char_range_start": 0,
        "char_range_end": len(text),
        "raw_chunk_char_range": {"start": 0, "end": len(text)},
        "legacy_char_range": {"start": 0, "end": len(text)},
        "coordinate_contract": "raw-codepoint-v1",
        "mapping_algorithm_version": "raw-span-map-1",
        "snippet_normalization": "display-whitespace-v1",
    }


def _draft_row(case_id: str, query: str, *, language: str, query_type: str,
               should_refuse: bool, truth: list[str] | None) -> dict:
    # source ids in the fixture evidence are basenames (product convention)
    sources = sorted({_SOURCE_OF.get(cid, "") for cid in (truth or [])})
    row = {
        "id": case_id,
        "query": query,
        "language": language,
        "query_type": query_type,
        "should_refuse": should_refuse,
        "relevance_level": "none" if should_refuse else "chunk",
        "note": f"fixture case {case_id}",
        "acceptable_answer_points": [],
        "annotation": {"annotated_by": "zcode-draft",
                       "annotation_version": "v2.0.0",
                       "created_at": "2026-08-05",
                       "review_notes": "FIXTURE",
                       "review_status": "pending", "reviewed_by": ""},
        "metadata": {"band_target": "low_refuse" if should_refuse else "normal",
                     "chain_id": None,
                     "construction": "out_of_corpus" if should_refuse else "natural",
                     "difficulty": "easy", "follow_up_to": None, "turn": 1},
        "relevant_chunk_ids": sorted(truth or []),
        "relevant_chunks": [{"chunk_id": cid} for cid in sorted(truth or [])],
        "relevant_source_ids": sources,
    }
    return row


def _fixture_full(tmp_path: Path) -> dict[str, Path]:
    """Frozen-v2.0.11-shaped fixture + snapshot contract + fake 6A baseline."""
    root = tmp_path / "fixture"
    docs = root / "documents" / "processed"
    docs.mkdir(parents=True, exist_ok=True)
    for name, texts in SOURCE_CHUNKS.items():
        (docs / name).write_text("\n\n".join(texts) + "\n", encoding="utf-8")
    chunks_dir = root / "chunks"
    chunks = _write_chunks(chunks_dir, _chunk_rows(docs))
    corpus = _write_corpus_manifest(root, docs)

    def cid(name: str, i: int) -> str:
        return f"{_chunk_prefix(docs / name)}_chunk_{i}"

    global _SOURCE_OF
    _SOURCE_OF = {
        cid("alpha.md", i): "alpha.md" for i in range(3)
    } | {
        cid("beta.md", i): "beta.md" for i in range(3)
    } | {
        cid("gamma.md", i): "gamma.md" for i in range(3)
    }
    rev = root / "revision"
    freeze = rev / "evaluation-freeze"
    targeted = rev / "targeted-re-review"
    annot = root / "annotations"
    for d in (rev, freeze, targeted, annot):
        d.mkdir(parents=True, exist_ok=True)

    draft_rows = [
        _draft_row("en-001", "When was the Gutenberg press invented and where?",
                   language="en", query_type="single_fact", should_refuse=False,
                   truth=[cid("alpha.md", 0)]),
        _draft_row("en-002", "Compare how indexing and transactions are documented",
                   language="en", query_type="cross_document", should_refuse=False,
                   truth=[cid("alpha.md", 1), cid("beta.md", 1)]),
        _draft_row("zh-003", "SQLite 的索引有什么作用？",
                   language="zh", query_type="single_fact", should_refuse=False,
                   truth=[cid("beta.md", 0)]),
        _draft_row("mixed-004", "What is the URI query component syntax?",
                   language="mixed", query_type="mixed_intent", should_refuse=False,
                   truth=[cid("gamma.md", 2)]),
        _draft_row("zh-005", "请问如何预订 2030 年火星旅行团？",
                   language="zh", query_type="no_answer", should_refuse=True,
                   truth=None),
        _draft_row("en-006", "you said earlier about printing — what came next?",
                   language="en", query_type="multi_turn", should_refuse=True,
                   truth=None),
    ]
    draft_path = annot / "v2-cases-draft.jsonl"
    _write_jsonl(draft_path, draft_rows)
    (rev / "draft-after.jsonl").write_bytes(draft_path.read_bytes())

    evidence_rows = [
        _evidence_row("en-001", cid("alpha.md", 0), "alpha.md",
                      SOURCE_CHUNKS["alpha.md"][0]),
        _evidence_row("en-002", cid("alpha.md", 1), "alpha.md",
                      SOURCE_CHUNKS["alpha.md"][1]),
        _evidence_row("en-002", cid("beta.md", 1), "beta.md",
                      SOURCE_CHUNKS["beta.md"][1]),
        _evidence_row("zh-003", cid("beta.md", 0), "beta.md",
                      SOURCE_CHUNKS["beta.md"][0]),
        _evidence_row("mixed-004", cid("gamma.md", 2), "gamma.md",
                      SOURCE_CHUNKS["gamma.md"][2]),
    ]
    evidence = rev / "evidence-after.jsonl"
    _write_jsonl(evidence, evidence_rows)

    # ── candidate / targeted / freeze manifests（与 6A fixture 同构）──
    candidate = {
        "activation_blocked": True,
        "actor": "FIXTURE",
        "counts": {"case_after": 6, "evidence_after": len(evidence_rows)},
        "declarations": {"llm_called": False, "network_used": False,
                         "overlay_generated": False, "split_created": False,
                         "v2_1_entered": False},
        "deterministic": True,
        "gate_verdict": "FIXTURE_CANDIDATE_OK",
        "human_reviewed": False,
        "inputs": {
            "chunk-manifest.json": _sha256_bytes(
                (chunks_dir / "chunk-manifest.json").read_bytes()),
            "chunks.jsonl": _sha256_bytes(chunks.read_bytes()),
            "current-v2-draft.jsonl": _sha256_bytes(draft_path.read_bytes()),
        },
        "outputs": {
            "draft-after.jsonl": _sha256_bytes(
                (rev / "draft-after.jsonl").read_bytes()),
            "evidence-after.jsonl": _sha256_bytes(evidence.read_bytes()),
        },
        "overlay_generated": False,
        "revision_status": "CANDIDATE",
        "rule_version": "fixture-candidate-1",
        "run_at": "2026-08-12T00:00:00+00:00",
        "task": "fixture-candidate",
    }
    candidate["manifest_sha256"] = _self_hash(candidate)
    candidate_path = rev / "manifest.json"
    candidate_path.write_text(_canonical(candidate), encoding="utf-8")

    targeted_manifest = {
        "counts": {"case_count": 2, "reject": 2},
        "created_by": "fixture",
        "declarations": {"llm_called": True, "network_used": True,
                         "candidate_draft_evidence_unchanged": True,
                         "overlay_generated": False, "split_created": False,
                         "v2_1_entered": False},
        "gate_verdict": "FIXTURE_TARGETED_BLOCKED",
        "inputs": {
            "candidate-draft-after.jsonl": _sha256_bytes(
                (rev / "draft-after.jsonl").read_bytes()),
            "candidate-evidence-after.jsonl": _sha256_bytes(
                evidence.read_bytes()),
            "candidate-manifest.json": _sha256_bytes(candidate_path.read_bytes()),
            "chunk-manifest.json": _sha256_bytes(
                (chunks_dir / "chunk-manifest.json").read_bytes()),
            "chunks.jsonl": _sha256_bytes(chunks.read_bytes()),
            "current-v2-draft.jsonl": _sha256_bytes(draft_path.read_bytes()),
        },
        "manifest_sha256": "PLACEHOLDER",
        "metadata": {"activation_blocked": True, "human_reviewed": False,
                     "overlay_generated": False, "revision_status": "CANDIDATE",
                     "split_reseal_required": True, "v2_1_entered": False},
        "model": "fixture-model",
        "outputs": {
            "targeted-review-issues.jsonl": "0" * 64,
            "targeted-review-results.jsonl": "1" * 64,
        },
        "reviewed_revision": "fixture-revision",
        "reviewed_revision_manifest_sha256": _self_hash(candidate),
        "rule_version": "fixture-targeted-1",
        "run_at": "2026-08-12T00:00:00+00:00",
        "task": "fixture-targeted-review",
    }
    targeted_manifest["manifest_sha256"] = _self_hash(targeted_manifest)
    targeted_path = targeted / "manifest.json"
    targeted_path.write_text(_canonical(targeted_manifest), encoding="utf-8")
    (targeted / "targeted-review-issues.jsonl").write_text("{}\n", encoding="utf-8")
    (targeted / "targeted-review-results.jsonl").write_text("{}\n", encoding="utf-8")

    frozen_md = freeze / "FROZEN_EVALUATION_BASELINE.md"
    frozen_md.write_text("# FROZEN EVALUATION BASELINE — fixture\n", encoding="utf-8")
    freeze_summary = freeze / "freeze-summary.json"
    freeze_summary.write_text(_canonical({"task": "fixture-freeze"}),
                              encoding="utf-8")
    deferred = freeze / "deferred-owner-decisions.jsonl"
    deferred.write_text("{}\n", encoding="utf-8")

    freeze_manifest = {
        "activation_blocked": True,
        "counts": {"deferred": 2},
        "created_by": "fixture",
        "declarations": {"candidate_data_unchanged": True, "llm_called": False,
                         "network_used": False, "overlay_generated": False,
                         "split_created": False, "v2_1_entered": False},
        "frozen_revision": "fixture-revision",
        "frozen_revision_manifest_sha256": _sha256_bytes(candidate_path.read_bytes()),
        "frozen_revision_status": "CANDIDATE",
        "gate_verdict": "EVALUATION_BASELINE_FROZEN",
        "inputs": {
            "candidate-draft-after.jsonl": _sha256_bytes(
                (rev / "draft-after.jsonl").read_bytes()),
            "candidate-evidence-after.jsonl": _sha256_bytes(evidence.read_bytes()),
            "candidate-manifest.json": _sha256_bytes(candidate_path.read_bytes()),
            "chunk-manifest.json": _sha256_bytes(
                (chunks_dir / "chunk-manifest.json").read_bytes()),
            "chunks.jsonl": _sha256_bytes(chunks.read_bytes()),
            "current-v2-draft.jsonl": _sha256_bytes(draft_path.read_bytes()),
            "review-manifest.json": _sha256_bytes(targeted_path.read_bytes()),
            "targeted-review-issues.jsonl": _sha256_bytes(
                (targeted / "targeted-review-issues.jsonl").read_bytes()),
            "targeted-review-results.jsonl": _sha256_bytes(
                (targeted / "targeted-review-results.jsonl").read_bytes()),
        },
        "metadata": {"activation_blocked": True, "human_reviewed": False,
                     "overlay_generated": False, "revision_status": "CANDIDATE",
                     "split_reseal_required": True, "v2_1_entered": False},
        "outputs": {
            "FROZEN_EVALUATION_BASELINE.md": _sha256_bytes(frozen_md.read_bytes()),
            "deferred-owner-decisions.jsonl": _sha256_bytes(deferred.read_bytes()),
            "freeze-summary.json": _sha256_bytes(freeze_summary.read_bytes()),
        },
        "rule_version": "fixture-freeze-1",
        "run_at": "2026-08-12T00:00:00+00:00",
        "task": "fixture-freeze",
    }
    freeze_manifest["manifest_sha256"] = _self_hash(freeze_manifest)
    (freeze / "manifest.json").write_text(_canonical(freeze_manifest),
                                          encoding="utf-8")

    # ── fake Phase 6-A baseline dir（verify_phase6a_manifest 可复算）──
    phase6a = tmp_path / "phase6a"
    phase6a.mkdir()
    den = {"total_cases": 6, "chunk_metrics_cases": 4,
           "no_chunk_truth_cases": 2, "mapping_failure_rows": 0}
    summary6a = {"metrics": {"overall": {
        "recall@5": 1.0, "recall@10": 1.0, "recall@20": 1.0,
        "ndcg@5": 1.0, "ndcg@10": 1.0, "ndcg@20": 1.0, "mrr": 1.0,
        "source_recall@5": 1.0, "source_recall@10": 1.0,
        "source_recall@20": 1.0, "denominators": den,
    }}}
    summary6a_path = phase6a / "baseline-summary.json"
    summary6a_path.write_text(_canonical(summary6a), encoding="utf-8")
    per_case_path = phase6a / "per-case-retrieval-results.jsonl"
    _write_jsonl(per_case_path, [
        {"case_id": cid_, "metrics": (
            {k: 1.0 for k in (
                "recall@5", "recall@10", "recall@20",
                "ndcg@5", "ndcg@10", "ndcg@20", "mrr",
                "source_recall@5", "source_recall@10", "source_recall@20",
            )} if cid_ != "zh-005" and cid_ != "en-006" else {}),
         "retrieved_chunk_ids": []}
        for cid_ in ("en-001", "en-002", "zh-003", "mixed-004",
                     "zh-005", "en-006")
    ])
    phase6a_manifest = {
        "task": "fixture-phase6a",
        "inputs": {
            "chunks.jsonl": {"path": str(chunks),
                             "sha256": _sha256_bytes(chunks.read_bytes())},
            "chunk-manifest.json": {
                "path": str(chunks_dir / "chunk-manifest.json"),
                "sha256": _sha256_bytes(
                    (chunks_dir / "chunk-manifest.json").read_bytes())},
            "candidate-draft-after.jsonl": {
                "path": str(rev / "draft-after.jsonl"),
                "sha256": _sha256_bytes((rev / "draft-after.jsonl").read_bytes())},
        },
        "frozen_outputs": {},
        "outputs": {
            "baseline-summary.json": _sha256_bytes(summary6a_path.read_bytes()),
            "per-case-retrieval-results.jsonl": _sha256_bytes(
                per_case_path.read_bytes()),
        },
        "manifest_sha256": "PLACEHOLDER",
    }
    phase6a_manifest["manifest_sha256"] = _self_hash(phase6a_manifest)
    (phase6a / "manifest.json").write_text(_canonical(phase6a_manifest),
                                           encoding="utf-8")

    return {
        "root": root,
        "docs": docs,
        "chunks": chunks,
        "chunk_manifest": chunks_dir / "chunk-manifest.json",
        "corpus": corpus,
        "revision": rev,
        "draft": draft_path,
        "evidence": evidence,
        "phase6a": phase6a,
    }


@pytest.fixture()
def fx(tmp_path):
    return _fixture_full(tmp_path)


def _run(fx: dict[str, Path], tmp_path: Path, out_dir: Path | None = None,
         data_dir: Path | None = None, verify_determinism: bool = True,
         **kwargs) -> dict:
    return cbl.run_contract_baseline(
        revision_dir=fx["revision"],
        chunks_path=fx["chunks"],
        chunk_manifest_path=fx["chunk_manifest"],
        current_draft_path=fx["draft"],
        corpus_manifest_path=fx["corpus"],
        phase6a_dir=fx["phase6a"],
        out_dir=out_dir or (tmp_path / "out"),
        data_dir=data_dir or (tmp_path / "data"),
        repo_root=fx["root"],
        verify_determinism=verify_determinism,
        **kwargs,
    )


# ── Group 1: Phase 6-A manifest verification ─────────────────────────

def test_verify_phase6a_ok_on_fixture(fx):
    report = cbl.verify_phase6a_manifest(fx["phase6a"])
    assert report["verified"] is True
    assert report["drift"] == []


def test_verify_phase6a_detects_tamper(fx):
    path = fx["phase6a"] / "baseline-summary.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["metrics"]["overall"]["recall@5"] = 0.5
    path.write_text(_canonical(doc), encoding="utf-8")
    report = cbl.verify_phase6a_manifest(fx["phase6a"])
    assert report["verified"] is False
    assert any("outputs/baseline-summary.json" in d["name"]
               for d in report["drift"])


def test_verify_phase6a_detects_manifest_self_hash_drift(fx):
    path = fx["phase6a"] / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["task"] = "tampered"
    path.write_text(_canonical(doc), encoding="utf-8")
    report = cbl.verify_phase6a_manifest(fx["phase6a"])
    assert report["verified"] is False
    assert any(d["kind"] == "manifest_self_hash" for d in report["drift"])


# ── Group 2: fail-closed runs ─────────────────────────────────────────

def test_contract_baseline_fixture_ok(fx, tmp_path):
    out_dir = tmp_path / "out"
    summary = _run(fx, tmp_path, out_dir=out_dir, verify_determinism=False)
    assert summary["status"] == "ok"
    assert summary["case_count"] == 6
    assert set(p.name for p in out_dir.iterdir()) == set(cbl.CONTRACT_OUTPUT_FILES)
    # full product path recorded the contract in the collection manifest
    assert summary["snapshot"].fingerprint
    assert summary["manifest"]["contract"]["fingerprint"] == summary["snapshot"].fingerprint


def test_fail_closed_on_frozen_drift(fx, tmp_path):
    with open(fx["evidence"], "a", encoding="utf-8") as f:
        f.write("\n")
    out_dir = tmp_path / "out"
    with pytest.raises(cbl.BaselineDrift):
        _run(fx, tmp_path, out_dir=out_dir)
    assert not out_dir.exists()


def test_fail_closed_on_phase6a_drift(fx, tmp_path):
    path = fx["phase6a"] / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["task"] = "tampered"
    path.write_text(_canonical(doc), encoding="utf-8")
    out_dir = tmp_path / "out"
    with pytest.raises(cbl.BaselineDrift):
        _run(fx, tmp_path, out_dir=out_dir)
    assert not out_dir.exists()


def test_fail_closed_on_chunks_drift(fx, tmp_path):
    """篡改 chunks.jsonl 会先被冻结输入校验捕获（三个 manifest 都声明了
    chunks.jsonl 的 SHA）→ BaselineDrift，零产物。contract 级 fail-closed
    由 tests/test_index_contract.py 的验证组与 CLI 测试覆盖。"""
    path = fx["chunks"]
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["text"] += " TAMPERED"
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                for r in rows), encoding="utf-8")
    out_dir = tmp_path / "out"
    with pytest.raises(cbl.BaselineDrift):
        _run(fx, tmp_path, out_dir=out_dir)
    assert not out_dir.exists()


def test_main_exit_codes(fx, tmp_path):
    args = [
        "--revision-dir", str(fx["revision"]),
        "--chunks", str(fx["chunks"]),
        "--chunk-manifest", str(fx["chunk_manifest"]),
        "--current-draft", str(fx["draft"]),
        "--corpus-manifest", str(fx["corpus"]),
        "--phase6a-dir", str(fx["phase6a"]),
        "--output", str(tmp_path / "out"),
        "--data-dir", str(tmp_path / "data"),
        "--repo-root", str(fx["root"]),
        "--skip-determinism",
    ]
    assert cbl.main(args) == 0
    assert (tmp_path / "out" / "manifest.json").is_file()
    # drift → exit 2, zero new outputs
    out2 = tmp_path / "out2"
    path = fx["phase6a"] / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["task"] = "tampered"
    path.write_text(_canonical(doc), encoding="utf-8")
    code = cbl.main([
        "--revision-dir", str(fx["revision"]),
        "--chunks", str(fx["chunks"]),
        "--chunk-manifest", str(fx["chunk_manifest"]),
        "--current-draft", str(fx["draft"]),
        "--corpus-manifest", str(fx["corpus"]),
        "--phase6a-dir", str(fx["phase6a"]),
        "--output", str(out2),
        "--data-dir", str(tmp_path / "data2"),
        "--repo-root", str(fx["root"]),
    ])
    assert code == 2
    assert not out2.exists()


# ── Group 3: isolation / no-write guarantees ──────────────────────────

def test_frozen_inputs_untouched_and_no_user_index(fx, tmp_path, monkeypatch):
    import src.rag as rag

    user_dir = tmp_path / "user_chroma"
    monkeypatch.setattr(rag, "CHROMA_DB_PATH", str(user_dir))
    guard = [fx["root"], fx["phase6a"]]
    before = _snapshot_tree(guard)
    out_dir = tmp_path / "out"
    # 不传 data_dir → 自动临时目录，结束后清理（cleaned=True）
    summary = cbl.run_contract_baseline(
        revision_dir=fx["revision"],
        chunks_path=fx["chunks"],
        chunk_manifest_path=fx["chunk_manifest"],
        current_draft_path=fx["draft"],
        corpus_manifest_path=fx["corpus"],
        phase6a_dir=fx["phase6a"],
        out_dir=out_dir,
        repo_root=fx["root"],
        verify_determinism=False,
    )
    after = _snapshot_tree(guard)
    assert before == after
    if user_dir.exists():
        assert not list(user_dir.rglob("*"))
    assert summary["manifest"]["isolation"]["cleaned"] is True


def test_no_llm_generation_calls(fx, tmp_path, monkeypatch):
    import src.rag as rag
    import src.llm_gateway as llm

    def _forbid(*args, **kwargs):
        raise AssertionError("LLM/generation path invoked during baseline")

    monkeypatch.setattr(rag, "answer_with_llm_history", _forbid)
    monkeypatch.setattr(llm, "llm_call", _forbid)
    summary = _run(fx, tmp_path, verify_determinism=False)
    assert summary["status"] == "ok"


def test_no_generation_fields_in_outputs(fx, tmp_path):
    out_dir = tmp_path / "out"
    _run(fx, tmp_path, out_dir=out_dir, verify_determinism=False)
    summary = json.loads(
        (out_dir / "contract-baseline-summary.json").read_text(encoding="utf-8"))
    audit = summary["not_measured"]["generation_and_citation"]
    assert audit["measured"] is False and audit["reason"]
    for key in summary["metrics"]["overall"]:
        assert "answer" not in key and "citation" not in key
    rows = [
        json.loads(line)
        for line in (out_dir / "per-case-retrieval-results.jsonl")
        .read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    for row in rows:
        assert "answer" not in row and "citation" not in row
        assert set(row) <= set(cbl.bl6a.PER_CASE_OUTPUT_KEYS)


# ── Group 4: artifacts integrity ──────────────────────────────────────

def test_manifest_self_hash_and_shas(fx, tmp_path):
    out_dir = tmp_path / "out"
    _run(fx, tmp_path, out_dir=out_dir, verify_determinism=False)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_sha256"] == cbl.bl6a.self_hash(manifest)
    # contract inputs recorded with byte-accurate SHA
    for name in ("chunks.jsonl", "chunk-manifest.json",
                 "corpus-manifest.json", "source:alpha.md"):
        rec = manifest["inputs"][name]
        assert Path(rec["path"]).is_file()
        assert hashlib.sha256(Path(rec["path"]).read_bytes()).hexdigest() == rec["sha256"]
    # outputs recorded as name -> sha of on-disk bytes
    for name, sha in manifest["outputs"].items():
        p = out_dir / name
        assert p.is_file()
        assert hashlib.sha256(p.read_bytes()).hexdigest() == sha
    # 6A outputs recorded
    assert set(manifest["phase6a_outputs"]) == {
        "baseline-summary.json", "per-case-retrieval-results.jsonl"}
    assert manifest["contract"]["fingerprint"]
    assert manifest["isolation"]["no_user_index_touched"] is True


def test_data_quality_report_passes(fx, tmp_path):
    out_dir = tmp_path / "out"
    _run(fx, tmp_path, out_dir=out_dir, verify_determinism=False)
    dq = json.loads((out_dir / "data-quality-report.json").read_text(encoding="utf-8"))
    assert dq["passed"] is True
    assert dq["error_count"] == 0
    names = {c["name"] for c in dq["checks"]}
    for prefix in ("completeness.", "uniqueness.", "validity.",
                   "consistency.", "referential.", "denominators.",
                   "contract."):
        assert any(n.startswith(prefix) for n in names), prefix


def test_comparison_report_honest(fx, tmp_path):
    out_dir = tmp_path / "out"
    summary = _run(fx, tmp_path, out_dir=out_dir, verify_determinism=False)
    comparison = summary["comparison"]
    assert "aggregate_deltas" in comparison
    assert comparison["denominators"]["equal"] is True
    # per-case 差异统计是记录而非断言为 0
    assert "per_case_metric_diff_count" in comparison
    assert "per_case_retrieval_diff_count" in comparison


def test_determinism_two_builds_recorded(fx, tmp_path):
    out_dir = tmp_path / "out"
    summary = _run(fx, tmp_path, out_dir=out_dir, verify_determinism=True)
    det = summary["manifest"]["determinism"]
    assert det["cases_compared"] == 6
    # aggregate stability is asserted via metrics equality; raw differences
    # are recorded, not asserted away
    assert "difference_count" in det
    assert "metric_difference_count" in det


# ── Group 5: real frozen data (skip-guarded) ──────────────────────────

pytestmark_real = pytest.mark.skipif(
    not cbl.PHASE6A_DIR.exists(),
    reason="frozen v2.0.11 revision and Phase 6-A baseline are local artifacts",
)


@pytestmark_real
def test_real_phase6a_manifest_verifies():
    report = cbl.verify_phase6a_manifest(cbl.PHASE6A_DIR)
    assert report["verified"] is True
    assert report["drift"] == []
    assert len(report["checks"]) >= 50


@pytestmark_real
def test_real_contract_snapshot_loads():
    snapshot = cbl.load_contract_snapshot(
        chunks_path=cbl.CHUNKS_PATH,
        chunk_manifest_path=cbl.CHUNK_MANIFEST_PATH,
        corpus_manifest_path=cbl.CORPUS_MANIFEST_PATH,
        repo_root=cbl.REPO_ROOT,
    )
    assert len(snapshot.chunks) == 1006
    assert len(snapshot.sources) == 13
    assert all(c["ok"] for c in snapshot.validation)
