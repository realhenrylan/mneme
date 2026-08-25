"""Tests for scripts.evaluate_v211_frozen_product_baseline — Phase 6-A.

Read-only retrieval baseline for the frozen v2.0.11 candidate against the
current Mneme retrieval chain (embedding → Chroma → BM25 → RRF).  The
adapter must be fail-closed and side-effect-free with respect to the
frozen revision: any SHA drift aborts with zero outputs; every artifact is
written only to the designated product-baselines directory; Chroma lives
in a disposable temp data dir; no LLM / generation / network path exists.

Test coverage (per phase contract):
- freeze manifest / candidate manifest / targeted-review manifest
  self-hash recomputation and input-SHA fail-closed drift detection;
- no writes to the frozen revision (byte-identical snapshots) and
  forbidden-artifact scans;
- schema mapping completeness (every draft field mapped or recorded as
  unmapped with a reason), evidence-as-truth and divergence handling,
  mapping failures;
- metric denominators: no fabricated 0/"pass" for cases without
  chunk-level truth (refusal group carries observations only);
- temp-collection isolation (Chroma under the disposable data dir only);
- no LLM/generation invocation during retrieval;
- stable failure-sample ordering;
- manifest self-hash and inputs/outputs SHA recording;
- two offline builds identical on non-time fields;
- parser-drift audit (why the parser stage is measured separately);
- real-data read-only verification + no-write (skip-guarded for clones
  without the untracked frozen revision).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

import scripts.evaluate_v211_frozen_product_baseline as bl

# ── Fixture data ──────────────────────────────────────────────────────

CHUNK_TEXTS = {
    "a1b2c3d4e5f6_chunk_0": (
        "alpha.md",
        "The Gutenberg press was invented around 1440 in Mainz. "
        "Movable type printing transformed Europe.",
    ),
    "a1b2c3d4e5f6_chunk_1": (
        "alpha.md",
        "Gutenberg's Bible was printed in the 1450s. "
        "It is considered a masterpiece of early printing.",
    ),
    "a1b2c3d4e5f6_chunk_2": (
        "alpha.md",
        "The printing revolution spread rapidly across European cities "
        "after 1460.",
    ),
    "b2c3d4e5f6a7_chunk_0": (
        "beta.md",
        "SQLite 使用 B-tree 索引来加速查询。索引可以显著减少扫描的行数。",
    ),
    "b2c3d4e5f6a7_chunk_1": (
        "beta.md",
        "SQLite 事务支持原子提交和回滚。默认使用 journal 模式记录变更。",
    ),
    "b2c3d4e5f6a7_chunk_2": (
        "beta.md",
        "SQLite 支持共享缓存模式。多个连接可以共享同一个页缓存。",
    ),
    "c3d4e5f6a7b8_chunk_0": (
        "gamma.md",
        "RFC 3986 defines URI syntax: scheme, authority, path, query, "
        "fragment.",
    ),
    "c3d4e5f6a7b8_chunk_1": (
        "gamma.md",
        "URI percent-encoding encodes reserved characters like spaces "
        "and slashes.",
    ),
    "c3d4e5f6a7b8_chunk_2": (
        "gamma.md",
        "The query component of a URI may contain key=value pairs "
        "separated by ampersands.",
    ),
}

SOURCE_NAMES = {src for _, (src, _) in CHUNK_TEXTS.items()}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _canonical(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def _self_hash(obj: dict) -> str:
    d = dict(obj)
    d.pop("manifest_sha256", None)
    return _sha256_text(_canonical(d))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


def _snippet(chunk_text: str) -> str:
    # a contiguous substring of the chunk text (display-whitespace style)
    return " ".join(chunk_text.split())[:40]


def _evidence_row(case_id: str, chunk_id: str, source: str,
                  text: str | None = None) -> dict:
    if text is None:
        text = CHUNK_TEXTS[chunk_id][1]
    return {
        "case_id": case_id,
        "chunk_id": chunk_id,
        "chunk_text_sha256": _sha256_text(text),
        "source_id": source,
        "snippet": _snippet(text),
        "raw_evidence_span": text,
        "snippet_sha256": _sha256_text(_snippet(text)),
        "char_range": {"start": 0, "end": len(text)},
        "char_range_start": 0,
        "char_range_end": len(text),
        "raw_chunk_char_range": {"start": 0, "end": len(text)},
        "legacy_char_range": {"start": 0, "end": len(text)},
        "coordinate_contract": "raw-codepoint-v1",
        "mapping_algorithm_version": "raw-span-map-1",
        "snippet_normalization": "display-whitespace-v1",
    }


def _draft_row(
    case_id: str,
    query: str,
    *,
    language: str,
    query_type: str,
    should_refuse: bool,
    truth: list[str] | None,
    acceptable: list[str] | None = None,
    doc_target: str | None = None,
    is_refusal_turn: bool | None = None,
) -> dict:
    sources = sorted({CHUNK_TEXTS[cid][0] for cid in (truth or [])})
    row = {
        "id": case_id,
        "query": query,
        "language": language,
        "query_type": query_type,
        "should_refuse": should_refuse,
        "is_refusal_turn": is_refusal_turn,
        "doc_target": doc_target,
        "relevance_level": "none" if should_refuse else "chunk",
        "note": f"fixture case {case_id}",
        "acceptable_answer_points": acceptable if acceptable is not None else [],
        "annotation": {
            "annotated_by": "zcode-draft",
            "annotation_version": "v2.0.0",
            "created_at": "2026-08-05",
            "review_notes": "FIXTURE",
            "review_status": "pending",
            "reviewed_by": "",
        },
        "metadata": {
            "band_target": "low_refuse" if should_refuse else "normal",
            "chain_id": None,
            "construction": "out_of_corpus" if should_refuse else "natural",
            "difficulty": "easy",
            "follow_up_to": None,
            "turn": 1,
        },
        "relevant_chunk_ids": sorted(truth or []),
        "relevant_chunks": [
            {
                "chunk_id": cid,
                "chunk_text_snippet": _snippet(CHUNK_TEXTS[cid][1]),
                "page": None,
                "section": None,
                "source_id": CHUNK_TEXTS[cid][0],
            }
            for cid in sorted(truth or [])
        ],
        "relevant_source_ids": sources,
    }
    if is_refusal_turn is None:
        del row["is_refusal_turn"]
    if doc_target is None:
        del row["doc_target"]
    return row


def _fixture_chunks(tmp_path: Path) -> Path:
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for cid in sorted(CHUNK_TEXTS):
        source, text = CHUNK_TEXTS[cid]
        rows.append({
            "chunk_id": cid,
            "index": int(cid.split("_")[-1]),
            "source": source,
            "text": text,
        })
    _write_jsonl(chunks_dir / "chunks.jsonl", rows)
    (chunks_dir / "chunk-manifest.json").write_text(_canonical({
        "corpus_version": "v2.0.0-fixture",
        "n_documents": len(SOURCE_NAMES),
        "n_chunks": len(rows),
        "chunker": "fixture",
        "chunks_sha256": _sha256_text(
            "".join(json.dumps(r, ensure_ascii=False) for r in rows)
        ),
    }), encoding="utf-8")
    return chunks_dir


def _fixture_corpus(tmp_path: Path, with_orphan: bool = True) -> dict[str, Path]:
    """Build a frozen-v2.0.11-shaped fixture and return the key paths.

    Mirrors the real layout::

        <root>/revision/...          (candidate manifest + draft + evidence)
        <root>/revision/evaluation-freeze/manifest.json
        <root>/revision/targeted-re-review/manifest.json
        <root>/chunks/...
        <root>/annotations/v2-cases-draft.jsonl
    """
    root = tmp_path / "fixture"
    rev = root / "revision"
    freeze = rev / "evaluation-freeze"
    targeted = rev / "targeted-re-review"
    chunks = _fixture_chunks(root)
    annot = root / "annotations"
    for d in (rev, freeze, targeted, annot):
        d.mkdir(parents=True, exist_ok=True)

    # chunks
    chunks_jsonl = chunks / "chunks.jsonl"
    chunk_manifest = chunks / "chunk-manifest.json"

    # draft: 6 cases — 4 answerable, 2 refusal
    draft_rows = [
        _draft_row(
            "en-001", "When was the Gutenberg press invented and where?",
            language="en", query_type="single_fact", should_refuse=False,
            truth=["a1b2c3d4e5f6_chunk_0"],
            acceptable=["1440", "Mainz"],
        ),
        # divergence case: draft lists an extra chunk (b2c3d4e5f6a7_chunk_2)
        # that the evidence file does not contain — evidence is authoritative.
        _draft_row(
            "en-002", "Compare how indexing and transactions are documented",
            language="en", query_type="cross_document", should_refuse=False,
            truth=["a1b2c3d4e5f6_chunk_1", "b2c3d4e5f6a7_chunk_1",
                   "b2c3d4e5f6a7_chunk_2"],
            acceptable=["indexes", "transactions"],
        ),
        _draft_row(
            "zh-003", "SQLite 的索引有什么作用？",
            language="zh", query_type="single_fact", should_refuse=False,
            truth=["b2c3d4e5f6a7_chunk_0"],
            acceptable=["加速查询"],
        ),
        _draft_row(
            "mixed-004", "What is the URI query component syntax? URI 的查询组件包含什么？",
            language="mixed", query_type="mixed_intent", should_refuse=False,
            truth=["c3d4e5f6a7b8_chunk_2"],
            acceptable=["key=value pairs"],
        ),
        _draft_row(
            "zh-005", "请问如何预订 2030 年火星旅行团？",
            language="zh", query_type="no_answer", should_refuse=True,
            truth=None,
        ),
        _draft_row(
            "en-006", "you said earlier about printing — what came next?",
            language="en", query_type="multi_turn", should_refuse=True,
            truth=None, doc_target="alpha.md", is_refusal_turn=True,
        ),
    ]
    draft_path = annot / "v2-cases-draft.jsonl"
    _write_jsonl(draft_path, draft_rows)
    # draft-after.jsonl == current draft in the real pipeline (same bytes)
    (rev / "draft-after.jsonl").write_bytes(draft_path.read_bytes())

    # evidence: 4 answerable cases + 1 intentionally unmappable row
    evidence_rows = [
        _evidence_row("en-001", "a1b2c3d4e5f6_chunk_0", "alpha.md"),
        _evidence_row("en-002", "a1b2c3d4e5f6_chunk_1", "alpha.md"),
        _evidence_row("en-002", "b2c3d4e5f6a7_chunk_1", "beta.md"),
        _evidence_row("zh-003", "b2c3d4e5f6a7_chunk_0", "beta.md"),
        _evidence_row("mixed-004", "c3d4e5f6a7b8_chunk_2", "gamma.md"),
    ]
    if with_orphan:
        # mapping-failure row: chunk not present in the corpus
        evidence_rows.insert(
            1,
            _evidence_row("en-001", "zz9999999999_chunk_0", "zzz.md",
                          text="orphan evidence text not in the frozen corpus"),
        )
    evidence_path = rev / "evidence-after.jsonl"
    _write_jsonl(evidence_path, evidence_rows)

    # candidate manifest (subset of the real input set — fixture-resolvable)
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
            "chunk-manifest.json": _sha256_bytes(chunk_manifest.read_bytes()),
            "chunks.jsonl": _sha256_bytes(chunks_jsonl.read_bytes()),
            "current-v2-draft.jsonl": _sha256_bytes(draft_path.read_bytes()),
        },
        "outputs": {
            "draft-after.jsonl": _sha256_bytes(rev.joinpath("draft-after.jsonl").read_bytes()),
            "evidence-after.jsonl": _sha256_bytes(evidence_path.read_bytes()),
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

    # targeted-review manifest
    targeted_manifest = {
        "counts": {"case_count": 2, "reject": 2},
        "created_by": "fixture",
        "declarations": {"llm_called": True, "network_used": True,
                         "candidate_draft_evidence_unchanged": True,
                         "overlay_generated": False, "split_created": False,
                         "v2_1_entered": False},
        "gate_verdict": "FIXTURE_TARGETED_BLOCKED",
        "inputs": {
            "candidate-draft-after.jsonl": _sha256_bytes((rev / "draft-after.jsonl").read_bytes()),
            "candidate-evidence-after.jsonl": _sha256_bytes(evidence_path.read_bytes()),
            "candidate-manifest.json": _sha256_bytes(candidate_path.read_bytes()),
            "chunk-manifest.json": _sha256_bytes(chunk_manifest.read_bytes()),
            "chunks.jsonl": _sha256_bytes(chunks_jsonl.read_bytes()),
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
    (targeted / "targeted-review-issues.jsonl").write_text(
        "{}" + "\n", encoding="utf-8")
    (targeted / "targeted-review-results.jsonl").write_text(
        "{}" + "\n", encoding="utf-8")

    # freeze manifest (last — references candidate + targeted SHAs)
    frozen_md = freeze / "FROZEN_EVALUATION_BASELINE.md"
    frozen_md.write_text("# FROZEN EVALUATION BASELINE — fixture\n", encoding="utf-8")
    freeze_summary = freeze / "freeze-summary.json"
    freeze_summary.write_text(_canonical({"task": "fixture-freeze"}),
                              encoding="utf-8")
    deferred = freeze / "deferred-owner-decisions.jsonl"
    deferred.write_text("{}" + "\n", encoding="utf-8")

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
            "candidate-draft-after.jsonl": _sha256_bytes((rev / "draft-after.jsonl").read_bytes()),
            "candidate-evidence-after.jsonl": _sha256_bytes(evidence_path.read_bytes()),
            "candidate-manifest.json": _sha256_bytes(candidate_path.read_bytes()),
            "chunk-manifest.json": _sha256_bytes(chunk_manifest.read_bytes()),
            "chunks.jsonl": _sha256_bytes(chunks_jsonl.read_bytes()),
            "current-v2-draft.jsonl": _sha256_bytes(draft_path.read_bytes()),
            "review-manifest.json": _sha256_bytes(targeted_path.read_bytes()),
            "targeted-review-issues.jsonl": _sha256_bytes((targeted / "targeted-review-issues.jsonl").read_bytes()),
            "targeted-review-results.jsonl": _sha256_bytes((targeted / "targeted-review-results.jsonl").read_bytes()),
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

    return {
        "root": root,
        "revision": rev,
        "freeze": freeze,
        "targeted": targeted,
        "chunks": chunks,
        "annotations": annot,
        "chunks_jsonl": chunks_jsonl,
        "chunk_manifest": chunk_manifest,
        "draft": draft_path,
        "evidence": evidence_path,
        "candidate_manifest": candidate_path,
        "targeted_manifest": targeted_path,
        "freeze_manifest": freeze / "manifest.json",
    }


def _snapshot_tree(paths: list[Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    for base in paths:
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                out[str(p)] = _sha256_bytes(p.read_bytes())
    return out


def _run_baseline(fx: dict[str, Path], tmp_path: Path,
                  out_dir: Path | None = None,
                  data_dir: Path | None = None) -> dict:
    return bl.run_baseline(
        revision_dir=fx["revision"],
        chunks_path=fx["chunks_jsonl"],
        chunk_manifest_path=fx["chunk_manifest"],
        current_draft_path=fx["draft"],
        out_dir=out_dir or (tmp_path / "out"),
        data_dir=data_dir or (tmp_path / "data1"),
        corpus_documents_dir=None,  # fixture 无真实语料文档目录
    )


@pytest.fixture()
def fixture(tmp_path):
    return _fixture_corpus(tmp_path)


# ── Group 1: manifest conventions ─────────────────────────────────────

def test_manifest_self_hash_convention_matches_project(fixture):
    """Manifest self-hash follows the project convention: pop
    ``manifest_sha256``, canonical JSON (indent=1, sort_keys,
    ensure_ascii=False, trailing newline), sha256."""
    declared = json.loads(fixture["freeze_manifest"].read_text(encoding="utf-8"))
    assert bl.self_hash_of_file(fixture["freeze_manifest"]) == declared["manifest_sha256"]
    assert bl.self_hash_of_file(fixture["candidate_manifest"]) == json.loads(
        fixture["candidate_manifest"].read_text(encoding="utf-8"))["manifest_sha256"]
    assert bl.self_hash_of_file(fixture["targeted_manifest"]) == json.loads(
        fixture["targeted_manifest"].read_text(encoding="utf-8"))["manifest_sha256"]


# ── Group 2: fail-closed SHA verification ─────────────────────────────

def test_verify_ok_on_pristine_fixture(fixture):
    report = bl.verify_frozen_inputs(
        revision_dir=fixture["revision"],
        chunks_path=fixture["chunks_jsonl"],
        chunk_manifest_path=fixture["chunk_manifest"],
        current_draft_path=fixture["draft"],
    )
    assert report["verified"] is True
    assert report["drift"] == []


def test_verify_detects_tampered_input(fixture):
    with open(fixture["evidence"], "a", encoding="utf-8") as f:
        f.write("\n")
    report = bl.verify_frozen_inputs(
        revision_dir=fixture["revision"],
        chunks_path=fixture["chunks_jsonl"],
        chunk_manifest_path=fixture["chunk_manifest"],
        current_draft_path=fixture["draft"],
    )
    assert report["verified"] is False
    names = [d["name"] for d in report["drift"]]
    assert "candidate-evidence-after.jsonl" in names


def test_verify_detects_missing_input(fixture):
    fixture["chunks_jsonl"].unlink()
    report = bl.verify_frozen_inputs(
        revision_dir=fixture["revision"],
        chunks_path=fixture["chunks_jsonl"],
        chunk_manifest_path=fixture["chunk_manifest"],
        current_draft_path=fixture["draft"],
    )
    assert report["verified"] is False
    assert any(d["kind"] == "missing" and d["name"] == "chunks.jsonl"
               for d in report["drift"])


def test_verify_detects_freeze_manifest_self_hash_drift(fixture):
    path = fixture["freeze_manifest"]
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["declarations"]["tampered"] = True
    # 故意不重算 manifest_sha256 → 声明哈希与实际内容不一致 → 漂移
    path.write_text(bl.canonical_json(doc), encoding="utf-8")
    report = bl.verify_frozen_inputs(
        revision_dir=fixture["revision"],
        chunks_path=fixture["chunks_jsonl"],
        chunk_manifest_path=fixture["chunk_manifest"],
        current_draft_path=fixture["draft"],
    )
    assert report["verified"] is False
    assert any(d["kind"] == "manifest_self_hash" for d in report["drift"])


def test_verify_detects_candidate_self_hash_drift(fixture):
    path = fixture["candidate_manifest"]
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["counts"]["case_after"] = 7
    path.write_text(bl.canonical_json(doc), encoding="utf-8")
    report = bl.verify_frozen_inputs(
        revision_dir=fixture["revision"],
        chunks_path=fixture["chunks_jsonl"],
        chunk_manifest_path=fixture["chunk_manifest"],
        current_draft_path=fixture["draft"],
    )
    assert report["verified"] is False
    assert any(d["name"] == "candidate manifest self-hash" for d in report["drift"])


def test_main_aborts_without_outputs_on_drift(fixture, tmp_path):
    with open(fixture["evidence"], "a", encoding="utf-8") as f:
        f.write("\n")
    out_dir = tmp_path / "out"
    code = bl.main([
        "--revision-dir", str(fixture["revision"]),
        "--chunks", str(fixture["chunks_jsonl"]),
        "--chunk-manifest", str(fixture["chunk_manifest"]),
        "--current-draft", str(fixture["draft"]),
        "--output", str(out_dir),
        "--data-dir", str(tmp_path / "data"),
    ])
    assert code != 0
    assert not out_dir.exists()


def test_main_rejects_overlapping_output_dir(fixture, tmp_path):
    code = bl.main([
        "--revision-dir", str(fixture["revision"]),
        "--chunks", str(fixture["chunks_jsonl"]),
        "--chunk-manifest", str(fixture["chunk_manifest"]),
        "--current-draft", str(fixture["draft"]),
        "--output", str(fixture["revision"]),  # forbidden: inside revision
        "--data-dir", str(tmp_path / "data"),
    ])
    assert code != 0


# ── Group 3: schema mapping ───────────────────────────────────────────

def test_load_cases_maps_all_fields_with_reasons(fixture):
    cases, report = bl.load_cases(
        fixture["draft"], fixture["evidence"], fixture["chunks_jsonl"],
    )
    assert len(cases) == 6
    mapped = set(report["mapping"]["draft_fields"]["mapped"])
    unmapped = set(report["mapping"]["draft_fields"]["unmapped"])
    assert mapped == {
        "id", "query", "query_type", "language", "should_refuse",
        "acceptable_answer_points", "metadata", "relevant_source_ids",
        "relevant_chunks",
    }
    # every unmapped field carries a reason
    assert unmapped == {
        "annotation", "doc_target", "is_refusal_turn", "note",
        "relevance_level", "relevant_chunk_ids",
    }
    for name in unmapped:
        assert report["mapping"]["draft_fields"]["reasons"].get(name)
    # no v1 schema keys are silently dropped or fabricated
    for case in cases:
        assert case["case_id"] and case["query"]
        assert case["query_type"] in {"single_fact", "cross_document",
                                      "multi_turn", "metadata",
                                      "no_answer", "mixed_intent"}
        assert case["language"] in {"zh", "en", "mixed"}


def test_load_cases_truth_from_evidence_and_divergence(fixture):
    cases, report = bl.load_cases(
        fixture["draft"], fixture["evidence"], fixture["chunks_jsonl"],
    )
    by_id = {c["case_id"]: c for c in cases}
    # en-002: draft lists 3 chunks, evidence only 2 → evidence wins
    assert by_id["en-002"]["relevant_chunk_ids"] == [
        "a1b2c3d4e5f6_chunk_1", "b2c3d4e5f6a7_chunk_1",
    ]
    assert any(
        d["case_id"] == "en-002" and d["kind"] == "draft_vs_evidence_chunks"
        for d in report["mapping"]["divergences"]
    )
    # refusal cases have no chunk truth
    assert by_id["zh-005"]["relevant_chunk_ids"] == []
    assert by_id["en-006"]["relevant_chunk_ids"] == []


def test_load_cases_reports_mapping_failures_honestly(fixture):
    cases, report = bl.load_cases(
        fixture["draft"], fixture["evidence"], fixture["chunks_jsonl"],
    )
    failures = report["mapping"]["mapping_failures"]
    assert "zz9999999999_chunk_0" in failures
    assert failures["zz9999999999_chunk_0"]  # non-empty reason
    by_id = {c["case_id"]: c for c in cases}
    assert "zz9999999999_chunk_0" not in by_id["en-001"]["relevant_chunk_ids"]
    assert report["mapping"]["case_counts"]["no_chunk_truth"] == 2
    assert report["mapping"]["case_counts"]["with_chunk_truth"] == 4


def test_load_cases_rejects_unknown_query_type(fixture):
    rows = [
        json.loads(line)
        for line in fixture["draft"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows[0]["query_type"] = "bogus_type"
    path = fixture["draft"]
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        bl.load_cases(path, fixture["evidence"], fixture["chunks_jsonl"])


# ── Group 4: metrics denominators ─────────────────────────────────────

def test_metrics_denominators_honest(fixture, tmp_path):
    metrics = _run_baseline(fixture, tmp_path)["metrics"]
    overall = metrics["overall"]
    assert overall["denominators"]["chunk_metrics_cases"] == 4
    assert overall["denominators"]["no_chunk_truth_cases"] == 2
    assert overall["denominators"]["mapping_failure_rows"] == 1
    assert overall["denominators"]["total_cases"] == 6
    # refusal group carries observations only — no fabricated recall/0s
    refusal = metrics["by_refusal"]["refusal"]
    assert "recall@5" not in refusal and "ndcg@5" not in refusal
    assert "mrr" not in refusal
    assert "max_score_observation" in refusal
    # per-group denominators
    for group in metrics["by_language"].values():
        assert "n" in group
    for group in metrics["by_query_type"].values():
        assert "n" in group


def test_exact_match_case_scores_retrieved(fixture, tmp_path):
    results = _run_baseline(fixture, tmp_path)["results"]
    by_id = {r["case_id"]: r for r in results}
    zh = by_id["zh-003"]
    assert zh["retrieved_chunk_ids"]
    assert zh["metrics"]["recall@10"] == 1.0  # truth is a single chunk
    assert zh["metrics"]["source_recall@10"] == 1.0
    assert zh["metrics"]["mrr"] > 0


def test_refusal_cases_have_no_fabricated_chunk_metrics(fixture, tmp_path):
    results = _run_baseline(fixture, tmp_path)["results"]
    for r in results:
        if r["should_refuse"]:
            assert r["relevant_chunk_ids"] == []
            assert r["metrics"] == {}  # per-case metrics only for truth cases
        else:
            assert r["metrics"]


# ── Group 5: isolation and no-write guarantees ────────────────────────

def test_index_lives_under_disposable_data_dir(fixture, tmp_path):
    data_dir = tmp_path / "data"
    index = bl.build_frozen_index(
        fixture["chunks_jsonl"], data_dir, "coll_x",
    )
    try:
        assert (data_dir / "chroma_db").exists()
        assert index["collection"].count() == 9
        # no manifest sidecars are written anywhere
        assert not list(data_dir.rglob("*.manifest.json"))
        assert not list(tmp_path.rglob("*.bm25.json"))
    finally:
        bl.close_index(index)


def test_run_baseline_writes_only_outdir_and_tmpdata(fixture, tmp_path):
    protected = [fixture["root"]]
    before = _snapshot_tree(protected)
    out_dir = tmp_path / "out"
    summary = _run_baseline(fixture, tmp_path, out_dir=out_dir)
    after = _snapshot_tree(protected)
    assert before == after  # frozen inputs untouched, no new files
    assert out_dir.exists()
    expected = {
        "baseline-summary.json", "per-case-retrieval-results.jsonl",
        "failure-analysis.md", "schema-compatibility-report.md",
        "BASELINE_SCOPE.md", "manifest.json",
        "data-quality-mechanical-check.json",
    }
    assert {p.name for p in out_dir.iterdir()} == expected
    assert summary["status"] == "ok"


def test_forbidden_artifact_scan_no_new_files(fixture, tmp_path):
    guard_dirs = [fixture["revision"], fixture["chunks"], fixture["annotations"]]
    before = _snapshot_tree(guard_dirs)
    _run_baseline(fixture, tmp_path)
    after = _snapshot_tree(guard_dirs)
    assert before == after


# ── Group 6: no LLM / generation ──────────────────────────────────────

def test_no_llm_generation_calls(fixture, tmp_path, monkeypatch):
    import src.rag as rag
    import src.llm_gateway as llm

    def _forbid(*args, **kwargs):
        raise AssertionError("LLM/generation path invoked during baseline")

    monkeypatch.setattr(rag, "answer_with_llm_history", _forbid)
    monkeypatch.setattr(llm, "llm_call", _forbid)
    summary = _run_baseline(fixture, tmp_path)
    assert summary["status"] == "ok"


def test_no_generation_fields_in_outputs(fixture, tmp_path):
    out_dir = tmp_path / "out"
    _run_baseline(fixture, tmp_path, out_dir=out_dir)
    summary = json.loads(
        (out_dir / "baseline-summary.json").read_text(encoding="utf-8"))
    # 可测性审计: answer-quality / citation 指标必须声明为“未测”，而非数值
    audit = summary["not_measured"]["generation_and_citation"]
    assert audit["measured"] is False
    assert audit["reason"]
    for key in summary["metrics"]["overall"]:
        assert "answer" not in key and "citation" not in key
    rows = [
        json.loads(line)
        for line in (out_dir / "per-case-retrieval-results.jsonl")
        .read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    for row in rows:
        assert "answer" not in row and "citation" not in row
        assert set(row) <= set(bl.PER_CASE_OUTPUT_KEYS)


# ── Group 7: failure analysis ─────────────────────────────────────────

def test_failure_list_stable_and_sorted(fixture, tmp_path):
    results = _run_baseline(fixture, tmp_path)["results"]
    first = bl.failure_list(results)
    second = bl.failure_list(results)
    assert first == second  # deterministic
    keys = [
        (round(f["recall@20"], 6), round(f["source_recall@20"], 6), f["case_id"])
        for f in first
    ]
    assert keys == sorted(keys)
    # only truth-bearing cases appear
    assert all(f["case_id"] in {"en-001", "en-002", "zh-003", "mixed-004"}
               for f in first)
    for f in first:
        assert set(f) == set(bl.FAILURE_ROW_KEYS)
        assert "snippet" not in json.dumps(f)  # no frozen evidence leaked


# ── Group 8: determinism across two offline builds ────────────────────

def test_two_builds_identical_except_timing(fixture, tmp_path):
    r1 = _run_baseline(fixture, tmp_path, data_dir=tmp_path / "d1",
                       out_dir=tmp_path / "o1")
    r2 = _run_baseline(fixture, tmp_path, data_dir=tmp_path / "d2",
                       out_dir=tmp_path / "o2")
    norm = lambda r: [
        {k: v for k, v in row.items() if k != "retrieval_ms"}
        for row in r
    ]
    assert norm(r1["results"]) == norm(r2["results"])
    assert r1["metrics"] == r2["metrics"]


def test_manifest_records_inputs_outputs_shas(fixture, tmp_path):
    out_dir = tmp_path / "out"
    _run_baseline(fixture, tmp_path, out_dir=out_dir)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_sha256"] == bl.self_hash(manifest)
    # declared inputs match the fixture bytes
    for name in ("candidate-draft-after.jsonl", "candidate-evidence-after.jsonl",
                 "chunks.jsonl", "chunk-manifest.json",
                 "current-v2-draft.jsonl"):
        rec = manifest["inputs"][name]
        p = Path(rec["path"])
        assert p.exists()
        assert hashlib.sha256(p.read_bytes()).hexdigest() == rec["sha256"]
    # declared outputs match the on-disk bytes (outputs 记录为 sha 字符串)
    for name, sha in manifest["outputs"].items():
        p = out_dir / name
        assert p.exists()
        assert hashlib.sha256(p.read_bytes()).hexdigest() == sha
    assert manifest["code"]["head"]  # git HEAD recorded
    assert manifest["isolation"]["collection_name"]
    assert manifest["model"]["name"]


def test_data_quality_mechanical_check_passes(fixture, tmp_path):
    """等价机械检查（data-analytics skill 不可用）覆盖六维：完整性/
    唯一性/有效性/一致性/引用完整性/分母分组合理性。

    使用无孤儿 evidence 行的干净 fixture（孤儿行会被机械检查如实判为
    引用完整性失败——fail-closed 行为，另由 tampered 测试覆盖）。
    """
    clean = _fixture_corpus(tmp_path / "clean", with_orphan=False)
    out_dir = tmp_path / "out"
    _run_baseline(clean, tmp_path / "run", out_dir=out_dir)
    dq = json.loads(
        (out_dir / "data-quality-mechanical-check.json")
        .read_text(encoding="utf-8"))
    assert dq["passed"] is True
    assert dq["error_count"] == 0
    names = {c["name"] for c in dq["checks"]}
    for prefix in ("completeness.", "uniqueness.", "validity.",
                   "consistency.", "referential.", "denominators."):
        assert any(n.startswith(prefix) for n in names)


def test_data_quality_mechanical_check_detects_tampered_results(fixture, tmp_path):
    """机械检查必须 fail-closed：篡改 per-case 指标 → 一致性检查失败。"""
    out_dir = tmp_path / "out"
    _run_baseline(fixture, tmp_path, out_dir=out_dir)
    rows = [
        json.loads(line)
        for line in (out_dir / "per-case-retrieval-results.jsonl")
        .read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    rows[0]["metrics"]["recall@5"] = 0.999  # 与复算值不一致
    (out_dir / "per-case-retrieval-results.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")
    frozen_ids = {cid for cid in bl.load_frozen_chunks(fixture["chunks_jsonl"])
                  for cid in [cid["chunk_id"]]}
    dq = bl.data_quality_check(
        results=rows,
        metrics=json.loads((out_dir / "baseline-summary.json")
                           .read_text(encoding="utf-8"))["metrics"],
        failures=bl.failure_list(rows),
        mapping_report={"mapping": {"mapping_failures": {}}},
        manifest=None, frozen_chunk_ids=frozen_ids,
    )
    assert dq["passed"] is False
    assert any("consistency" in c["name"] for c in dq["checks"]
               if not c["ok"])


# ── Group 9: parser drift audit ───────────────────────────────────────def test_parser_drift_audit_structure_and_determinism(fixture, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    # one document per source, text = the source's chunks joined
    by_source: dict[str, list[str]] = {}
    for cid, (source, text) in CHUNK_TEXTS.items():
        by_source.setdefault(source, []).append(text)
    for source, texts in by_source.items():
        (docs / source).write_text("\n\n".join(texts) + "\n", encoding="utf-8")
    audit1 = bl.parser_drift_audit(docs, fixture["chunks_jsonl"])
    audit2 = bl.parser_drift_audit(docs, fixture["chunks_jsonl"])
    assert audit1 == audit2
    assert set(audit1["per_source"]) == SOURCE_NAMES
    for rec in audit1["per_source"].values():
        assert rec["frozen_chunks"] == len(
            [cid for cid, (s, _) in CHUNK_TEXTS.items() if s == rec["source"]])
        assert rec["rebuilt_chunks"] >= 0
        assert 0 <= rec["exact_text_matches"] <= rec["frozen_chunks"]
        assert isinstance(rec["id_format_matches"], bool)


# ── Group 10: real-data read-only verification (skip-guarded) ─────────

REAL_REVISION = bl.FROZEN_REVISION_DIR
REAL_CHUNKS = bl.CHUNKS_PATH
REAL_MANIFEST = bl.CHUNK_MANIFEST_PATH
REAL_DRAFT = bl.CURRENT_DRAFT_PATH

pytestmark_real = pytest.mark.skipif(
    not REAL_REVISION.exists(),
    reason="frozen v2.0.11 revision is an untracked local artifact",
)


@pytestmark_real
def test_real_frozen_inputs_verify_ok():
    report = bl.verify_frozen_inputs(
        revision_dir=REAL_REVISION,
        chunks_path=REAL_CHUNKS,
        chunk_manifest_path=REAL_MANIFEST,
        current_draft_path=REAL_DRAFT,
    )
    assert report["verified"] is True
    assert report["drift"] == []
    assert len(report["checks"]) >= 30


@pytestmark_real
def test_real_frozen_data_read_only_snapshot():
    guard = [REAL_REVISION, REAL_CHUNKS.parent, REAL_DRAFT.parent]
    before = _snapshot_tree(guard)
    cases, report = bl.load_cases(
        REAL_REVISION / "draft-after.jsonl",
        REAL_REVISION / "evidence-after.jsonl",
        REAL_CHUNKS,
    )
    assert len(cases) == 136
    assert report["mapping"]["case_counts"]["with_chunk_truth"] == 105
    assert report["mapping"]["case_counts"]["no_chunk_truth"] == 31
    assert report["mapping"]["mapping_failures"] == {}
    after = _snapshot_tree(guard)
    assert before == after
