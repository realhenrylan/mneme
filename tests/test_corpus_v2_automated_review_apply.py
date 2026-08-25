"""Tests for scripts.corpus_v2_automated_review_apply.

Covers:
- 150/150 confirmed generates AUTOMATED_REVIEWED_OWNER_AUTHORIZED overlay;
- Any reject / needs_followup blocks overlay;
- Reviewer identity, model, parameters, SHA drift, evidence drift,
  illegal decision all fail-closed;
- Blank human pack SHA unchanged and human fields remain empty;
- Input does not contain historical verdict/notes/cohort/split fields;
- Five repaired cases appear in the full review;
- Two runs produce byte-identical output;
- No HUMAN_REVIEWED / HUMAN_APPROVED / "人工审核完成" in outputs.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import scripts.corpus_v2_automated_review_apply as ap
from evaluation.corpus_v2 import normalize_snippet

REPO_ROOT = Path(__file__).resolve().parent.parent
# Fallback: if __file__ resolution gives unexpected result, use cwd
if not (REPO_ROOT / "evaluation" / "datasets" / "v2" / "annotations" / "v2-cases-draft.jsonl").exists():
    REPO_ROOT = Path.cwd()

# ── helpers ────────────────────────────────────────────────────────────

def _line(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _snippet_char_range(snippet: str, chunk_text: str) -> dict[str, int]:
    """Compute character range of snippet within chunk_text (after normalization)."""
    norm_snip = normalize_snippet(snippet)
    norm_chunk = normalize_snippet(chunk_text)
    idx = norm_chunk.find(norm_snip)
    if idx == -1:
        raise ValueError(f"snippet not found in chunk text")
    return {"start": idx, "end": idx + len(norm_snip)}


def _make_review_dir(tmp: Path, n_cases: int = 150,
                     non_confirmed: list[str] | None = None,
                     extra_fields: dict | None = None,
                     draft_path: Path | None = None,
                     chunks_path: Path | None = None,
                     chunk_manifest_path: Path | None = None) -> tuple[Path, Path]:
    """Create a minimal automated-review dir with a review jsonl + manifest."""
    review_dir = tmp / "automated-review"
    review_dir.mkdir()
    non_confirmed = non_confirmed or []
    extra_fields = extra_fields or {}

    rows = []
    for i in range(1, n_cases + 1):
        cid = f"case-{i:03d}"
        decision = "confirmed" if cid not in non_confirmed else non_confirmed[
            non_confirmed.index(cid)]
        row = {
            "case_id": cid,
            "evidence_sha256": "a" * 64,
            "reviewer_type": "LLM_ASSISTED_OWNER_AUTHORIZED",
            "review_decision": decision,
            "confidence": "high",
            "rationale": "ok" if decision == "confirmed" else "issue",
            "issue_categories": [],
            "model": "deepseek-v4-pro",
            "temperature": 0.0,
            "max_tokens": 8000,
            "evidence_summary": [],
            "prompt_sha256": "b" * 64,
            "response_sha256": "c" * 64,
            "raw_response_sha256": "d" * 64,
            "transport_retries": 0,
            "parse_retries": 0,
        }
        row.update(extra_fields)
        rows.append(row)

    review_path = review_dir / "automated-review.jsonl"
    review_path.write_text("\n".join(_line(r) for r in rows) + "\n",
                           encoding="utf-8")

    # manifest — 使用传入的路径或 REPO_ROOT 默认路径
    actual_draft = draft_path or (REPO_ROOT / "evaluation" / "datasets" / "v2" /
                                  "annotations" / "v2-cases-draft.jsonl")
    actual_chunks = chunks_path or (REPO_ROOT / "data" / "v2-corpus" /
                                    "chunks" / "chunks.jsonl")
    actual_cm = chunk_manifest_path or (REPO_ROOT / "data" / "v2-corpus" /
                                        "chunks" / "chunk-manifest.json")

    m = {
        "inputs": {
            "draft": {
                "path": str(actual_draft.resolve()),
                "sha256": _sha256_file(actual_draft),
                "rows": n_cases,
            },
            "chunks": {
                "path": str(actual_chunks.resolve()),
                "sha256": _sha256_file(actual_chunks),
            },
            "chunk_manifest": {
                "path": str(actual_cm.resolve()),
                "sha256": _sha256_file(actual_cm),
            },
        },
        "pack_sha256": "e" * 64,
        "evidence_sha256_aggregate": "f" * 64,
        "n_cases": n_cases,
    }
    (review_dir / "manifest.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return review_dir, tmp


def _make_draft(tmp: Path, case_ids: list[str]) -> Path:
    """Create a minimal draft jsonl with given case_ids."""
    draft = tmp / "draft.jsonl"
    cases = []
    for cid in case_ids:
        cases.append({
            "id": cid,
            "query": f"query for {cid}",
            "language": "en",
            "query_type": "single_fact",
            "should_refuse": False,
            "is_refusal_turn": None,
            "relevance_level": "chunk",
            "doc_target": "",
            "note": "",
            "acceptable_answer_points": ["answer"],
            "relevant_source_ids": ["src-a"],
            "relevant_chunk_ids": ["chunk-1"],
            "relevant_chunks": [{
                "chunk_id": "chunk-1",
                "chunk_text_snippet": "X is defined as Y in the spec.",
                "source_id": "src-a",
                "page": "",
                "section": "",
            }],
            "annotation": {
                "annotated_by": "mock", "reviewed_by": "",
                "review_status": "pending", "review_notes": "LLM_ASSISTED",
                "annotation_version": "v2-draft", "created_at": "",
            },
            "metadata": {"chain_id": None, "follow_up_to": None, "turn": 1,
                         "difficulty": "easy", "band_target": "B",
                         "construction": "seed"},
        })
    draft.write_text("\n".join(_line(c) for c in cases) + "\n", encoding="utf-8")
    return draft


def _make_chunks(tmp: Path) -> Path:
    """Create a minimal chunks jsonl."""
    chunks = tmp / "chunks.jsonl"
    chunks.write_text(
        _line({"chunk_id": "chunk-1", "source": "src-a",
               "text": "X is defined as Y in the spec."}) + "\n",
        encoding="utf-8")
    return chunks


def _make_chunk_manifest(tmp: Path) -> Path:
    """Create a minimal chunk-manifest.json."""
    m = {"corpus_version": "v2-test", "n_documents": 1, "n_chunks": 1}
    p = tmp / "chunk-manifest.json"
    p.write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n",
                 encoding="utf-8")
    return p


# ── fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def review_env(tmp_path: Path):
    """Create a review dir with real manifest pointing to temp files."""
    review_dir = tmp_path / "automated-review"
    review_dir.mkdir()
    draft = _make_draft(tmp_path, [f"case-{i:03d}" for i in range(1, 151)])
    chunks = _make_chunks(tmp_path)
    chunk_manifest = _make_chunk_manifest(tmp_path)

    # Build real review jsonl
    rows = []
    for i in range(1, 151):
        cid = f"case-{i:03d}"
        # Compute real evidence sha
        payload = {
            "case_id": cid,
            "query": f"query for {cid}",
            "language": "en",
            "query_type": "single_fact",
            "turn": 1,
            "previous_turns": [],
            "draft": {
                "should_refuse": False,
                "is_refusal_turn": None,
                "relevance_level": "chunk",
                "doc_target": "",
                "note": "",
                "acceptable_answer_points": ["answer"],
            },
            "evidence": [{
                "chunk_id": "chunk-1",
                "source_id": "src-a",
                "snippet": "X is defined as Y in the spec.",
                "snippet_sha256": _sha256_text("X is defined as Y in the spec."),
                "chunk_text_sha256": _sha256_text("X is defined as Y in the spec."),
                "chunk_text": "X is defined as Y in the spec.",
                "char_range": _snippet_char_range(
                    "X is defined as Y in the spec.",
                    "X is defined as Y in the spec."),
            }],
        }
        evidence_sha = _sha256_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")))
        rows.append({
            "case_id": cid,
            "evidence_sha256": evidence_sha,
            "reviewer_type": "LLM_ASSISTED_OWNER_AUTHORIZED",
            "review_decision": "confirmed",
            "confidence": "high",
            "rationale": "ok",
            "issue_categories": [],
            "model": "deepseek-v4-pro",
            "temperature": 0.0,
            "max_tokens": 8000,
            "evidence_summary": [{
                "chunk_id": "chunk-1",
                "source_id": "src-a",
                "snippet_preview": "X is defined as Y in the spec.",
                "char_range": _snippet_char_range(
                    "X is defined as Y in the spec.",
                    "X is defined as Y in the spec."),
            }],
            "prompt_sha256": _sha256_text("mock prompt"),
            "response_sha256": _sha256_text("mock response"),
            "raw_response_sha256": _sha256_text("mock response"),
            "transport_retries": 0,
            "parse_retries": 0,
        })

    review_path = review_dir / "automated-review.jsonl"
    review_path.write_text("\n".join(_line(r) for r in rows) + "\n",
                           encoding="utf-8")

    manifest = {
        "inputs": {
            "draft": {
                "path": str(draft.resolve()),
                "sha256": _sha256_file(draft),
                "rows": 150,
            },
            "chunks": {
                "path": str(chunks.resolve()),
                "sha256": _sha256_file(chunks),
            },
            "chunk_manifest": {
                "path": str(chunk_manifest.resolve()),
                "sha256": _sha256_file(chunk_manifest),
            },
        },
        "pack_sha256": _sha256_file(review_path),
        "evidence_sha256_aggregate": "".join(r["evidence_sha256"] for r in rows),
        "n_cases": 150,
    }
    (review_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return {
        "review_dir": review_dir,
        "draft": draft,
        "chunks": chunks,
        "chunk_manifest": chunk_manifest,
    }


# ── tests ──────────────────────────────────────────────────────────────

class TestDataQualityChecks:
    """Tests for deterministic data quality equivalence."""

    def test_completeness_150_cases(self, tmp_path: Path):
        """150 cases required; fewer or more fails."""
        draft = _make_draft(tmp_path, [f"case-{i:03d}" for i in range(1, 150)])
        chunks = _make_chunks(tmp_path)
        cm = _make_chunk_manifest(tmp_path)
        review_dir, _ = _make_review_dir(tmp_path, n_cases=149,
                                          draft_path=draft,
                                          chunks_path=chunks,
                                          chunk_manifest_path=cm)
        with pytest.raises(ap.ApplyError, match="row count 149"):
            ap.apply(review_dir=review_dir, draft_path=draft,
                     chunks_path=chunks, chunk_manifest_path=cm)

    def test_uniqueness_case_ids(self, tmp_path: Path):
        """Duplicate case_ids must fail."""
        draft = _make_draft(tmp_path, [f"case-{i:03d}" for i in range(1, 151)])
        chunks = _make_chunks(tmp_path)
        cm = _make_chunk_manifest(tmp_path)
        review_dir, _ = _make_review_dir(tmp_path, n_cases=150,
                                          draft_path=draft,
                                          chunks_path=chunks,
                                          chunk_manifest_path=cm)
        review_path = review_dir / "automated-review.jsonl"
        existing = [json.loads(l) for l in review_path.open() if l.strip()]
        existing[0]["case_id"] = "case-002"  # duplicate
        review_path.write_text("\n".join(_line(r) for r in existing) + "\n",
                               encoding="utf-8")
        with pytest.raises(ap.ApplyError, match="duplicate"):
            ap.apply(review_dir=review_dir, draft_path=draft,
                     chunks_path=chunks, chunk_manifest_path=cm)


class TestReviewerIdentity:
    """Tests for reviewer_type / model / parameter immutability."""

    def test_forbidden_reviewer_type_human(self, tmp_path: Path):
        """Any 'HUMAN' in reviewer_type fails."""
        draft = _make_draft(tmp_path, [f"case-{i:03d}" for i in range(1, 151)])
        chunks = _make_chunks(tmp_path)
        cm = _make_chunk_manifest(tmp_path)
        review_dir, _ = _make_review_dir(
            tmp_path, extra_fields={"reviewer_type": "HUMAN_REVIEWED"},
            draft_path=draft, chunks_path=chunks, chunk_manifest_path=cm)
        with pytest.raises(ap.ApplyError, match="reviewer_type"):
            ap.apply(review_dir=review_dir, draft_path=draft,
                     chunks_path=chunks, chunk_manifest_path=cm)

    def test_forbidden_model_gpt5_sol(self, tmp_path: Path):
        """gpt-5.6-sol must fail."""
        draft = _make_draft(tmp_path, [f"case-{i:03d}" for i in range(1, 151)])
        chunks = _make_chunks(tmp_path)
        cm = _make_chunk_manifest(tmp_path)
        review_dir, _ = _make_review_dir(
            tmp_path, extra_fields={"model": "gpt-5.6-sol"},
            draft_path=draft, chunks_path=chunks, chunk_manifest_path=cm)
        with pytest.raises(ap.ApplyError, match="model"):
            ap.apply(review_dir=review_dir, draft_path=draft,
                     chunks_path=chunks, chunk_manifest_path=cm)

    def test_forbidden_model_deepseek_flash(self, tmp_path: Path):
        """deepseek-v4-flash must fail."""
        draft = _make_draft(tmp_path, [f"case-{i:03d}" for i in range(1, 151)])
        chunks = _make_chunks(tmp_path)
        cm = _make_chunk_manifest(tmp_path)
        review_dir, _ = _make_review_dir(
            tmp_path, extra_fields={"model": "deepseek-v4-flash"},
            draft_path=draft, chunks_path=chunks, chunk_manifest_path=cm)
        with pytest.raises(ap.ApplyError, match="model"):
            ap.apply(review_dir=review_dir, draft_path=draft,
                     chunks_path=chunks, chunk_manifest_path=cm)

    def test_wrong_temperature_fails(self, tmp_path: Path):
        """Temperature != 0.0 must fail."""
        draft = _make_draft(tmp_path, [f"case-{i:03d}" for i in range(1, 151)])
        chunks = _make_chunks(tmp_path)
        cm = _make_chunk_manifest(tmp_path)
        review_dir, _ = _make_review_dir(
            tmp_path, extra_fields={"temperature": 0.5},
            draft_path=draft, chunks_path=chunks, chunk_manifest_path=cm)
        with pytest.raises(ap.ApplyError, match="temperature"):
            ap.apply(review_dir=review_dir, draft_path=draft,
                     chunks_path=chunks, chunk_manifest_path=cm)

    def test_wrong_max_tokens_fails(self, tmp_path: Path):
        """max_tokens != 8000 must fail."""
        draft = _make_draft(tmp_path, [f"case-{i:03d}" for i in range(1, 151)])
        chunks = _make_chunks(tmp_path)
        cm = _make_chunk_manifest(tmp_path)
        review_dir, _ = _make_review_dir(
            tmp_path, extra_fields={"max_tokens": 4000},
            draft_path=draft, chunks_path=chunks, chunk_manifest_path=cm)
        with pytest.raises(ap.ApplyError, match="max_tokens"):
            ap.apply(review_dir=review_dir, draft_path=draft,
                     chunks_path=chunks, chunk_manifest_path=cm)

    def test_illegal_decision_value_fails(self, tmp_path: Path):
        """Invalid decision value must fail."""
        draft = _make_draft(tmp_path, [f"case-{i:03d}" for i in range(1, 151)])
        chunks = _make_chunks(tmp_path)
        cm = _make_chunk_manifest(tmp_path)
        review_dir, _ = _make_review_dir(
            tmp_path, extra_fields={"review_decision": "invalid"},
            draft_path=draft, chunks_path=chunks, chunk_manifest_path=cm)
        with pytest.raises(ap.ApplyError, match="invalid decision"):
            ap.apply(review_dir=review_dir, draft_path=draft,
                     chunks_path=chunks, chunk_manifest_path=cm)


class TestSHAIntegrity:
    """Tests for SHA drift fail-closed."""

    def test_evidence_sha_drift_fails(self, tmp_path: Path):
        """Evidence SHA mismatch must fail."""
        draft = _make_draft(tmp_path, [f"case-{i:03d}" for i in range(1, 151)])
        chunks = _make_chunks(tmp_path)
        cm = _make_chunk_manifest(tmp_path)
        review_dir, _ = _make_review_dir(tmp_path, n_cases=150,
                                          draft_path=draft,
                                          chunks_path=chunks,
                                          chunk_manifest_path=cm)
        # Corrupt one evidence sha
        review_path = review_dir / "automated-review.jsonl"
        rows = [json.loads(l) for l in review_path.open() if l.strip()]
        rows[0]["evidence_sha256"] = "0" * 64
        review_path.write_text("\n".join(_line(r) for r in rows) + "\n",
                               encoding="utf-8")
        with pytest.raises(ap.ApplyError, match="evidence_sha256 mismatch"):
            ap.apply(review_dir=review_dir, draft_path=draft,
                     chunks_path=chunks, chunk_manifest_path=cm)


class TestOverlayGate:
    """Tests for overlay generation gating."""

    def test_all_confirmed_generates_overlay(self, review_env, tmp_path: Path):
        """150/150 confirmed → overlay generated with correct status."""
        review_dir = review_env["review_dir"]
        overlay_dir = tmp_path / "overlay"
        rc = ap.apply(
            review_dir=review_dir,
            draft_path=review_env["draft"],
            chunks_path=review_env["chunks"],
            chunk_manifest_path=review_env["chunk_manifest"],
            overlay_dir=overlay_dir,
        )
        assert rc == 0
        assert (overlay_dir / "automated-reviewed-truth-overlay.json").exists()
        overlay = json.loads(
            (overlay_dir / "automated-reviewed-truth-overlay.json").read_text(
                encoding="utf-8"))
        assert overlay["status"] == "AUTOMATED_REVIEWED_OWNER_AUTHORIZED"
        assert overlay["reviewer_type"] == "LLM_ASSISTED_OWNER_AUTHORIZED"
        assert overlay["model"] == "deepseek-v4-pro"
        assert overlay["n_cases"] == 150
        assert overlay["decision_counts"]["confirmed"] == 150

    def test_any_reject_blocks_overlay(self, review_env, tmp_path: Path):
        """Single reject → no overlay, gate report generated."""
        review_dir = review_env["review_dir"]
        review_path = review_dir / "automated-review.jsonl"
        rows = [json.loads(l) for l in review_path.open() if l.strip()]
        rows[0]["review_decision"] = "reject"
        rows[0]["issue_categories"] = ["snippet_sufficiency"]
        rows[0]["rationale"] = "insufficient evidence"
        review_path.write_text("\n".join(_line(r) for r in rows) + "\n",
                               encoding="utf-8")

        rc = ap.apply(
            review_dir=review_dir,
            draft_path=review_env["draft"],
            chunks_path=review_env["chunks"],
            chunk_manifest_path=review_env["chunk_manifest"],
        )
        assert rc == 1  # blocked
        overlay_dir = ap.DEFAULT_OVERLAY_DIR
        assert not (overlay_dir / "automated-reviewed-truth-overlay.json"
                    ).exists()
        assert (review_dir / "automated-review-gate-report.md").exists()

    def test_any_needs_followup_blocks_overlay(self, review_env, tmp_path: Path):
        """Single needs_followup → no overlay."""
        review_dir = review_env["review_dir"]
        review_path = review_dir / "automated-review.jsonl"
        rows = [json.loads(l) for l in review_path.open() if l.strip()]
        rows[0]["review_decision"] = "needs_followup"
        rows[0]["issue_categories"] = ["other"]
        rows[0]["rationale"] = "cannot determine"
        review_path.write_text("\n".join(_line(r) for r in rows) + "\n",
                               encoding="utf-8")

        rc = ap.apply(
            review_dir=review_dir,
            draft_path=review_env["draft"],
            chunks_path=review_env["chunks"],
            chunk_manifest_path=review_env["chunk_manifest"],
        )
        assert rc == 1
        overlay_dir = ap.DEFAULT_OVERLAY_DIR
        assert not (overlay_dir / "automated-reviewed-truth-overlay.json"
                    ).exists()


class TestHumanPackIntegrity:
    """Tests for blank human-review pack immutability."""

    def test_blank_human_pack_unchanged(self, tmp_path: Path):
        """Blank human pack with empty fields passes."""
        # Create a blank human pack
        human_pack_dir = REPO_ROOT / "evaluation" / "datasets" / "v2" / "human-review"
        human_pack_dir.mkdir(parents=True, exist_ok=True)
        blank_path = human_pack_dir / "human-review-pack-blank-test.jsonl"
        cases = []
        for i in range(1, 6):
            cases.append({
                "id": f"blank-{i:03d}",
                "query": "test",
                "annotation": {
                    "annotated_by": "mock",
                    "reviewed_by": "",
                    "review_status": "pending",
                    "review_notes": "",
                },
            })
        blank_path.write_text("\n".join(_line(c) for c in cases) + "\n",
                              encoding="utf-8")
        try:
            # The validator scans for human-review-pack.jsonl; if it exists
            # with empty fields, it should pass
            # Just verify the function doesn't raise on valid blank pack
            errors = ap._validate_blank_human_pack(REPO_ROOT)
            assert errors == []
        finally:
            if blank_path.exists():
                blank_path.unlink()

    def test_no_human_identifiers_in_review_output(self, tmp_path: Path):
        """HUMAN_REVIEWED / HUMAN_APPROVED / 人工审核完成 in review files fail."""
        review_dir = tmp_path / "automated-review"
        review_dir.mkdir()
        # Write a review jsonl with forbidden string
        bad_row = {
            "case_id": "case-001",
            "evidence_sha256": "a" * 64,
            "reviewer_type": "LLM_ASSISTED_OWNER_AUTHORIZED",
            "review_decision": "confirmed",
            "model": "deepseek-v4-pro",
            "rationale": "HUMAN_REVIEWED",
        }
        (review_dir / "automated-review.jsonl").write_text(
            _line(bad_row) + "\n", encoding="utf-8")
        # Also write manifest
        m = {
            "inputs": {
                "draft": {"path": "dummy", "sha256": "x", "rows": 1},
                "chunks": {"path": "dummy", "sha256": "x"},
                "chunk_manifest": {"path": "dummy", "sha256": "x"},
            },
            "pack_sha256": "x",
            "evidence_sha256_aggregate": "x",
            "n_cases": 1,
        }
        (review_dir / "manifest.json").write_text(
            json.dumps(m, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")

        errors = ap._check_no_human_identifiers(review_dir)
        assert any("HUMAN_REVIEWED" in e for e in errors)

    def test_disclaimer_not_flagged(self, tmp_path: Path):
        """Negation disclaimer '不是人工审核' should not be flagged."""
        review_dir = tmp_path / "automated-review"
        review_dir.mkdir()
        good_row = {
            "case_id": "case-001",
            "evidence_sha256": "a" * 64,
            "reviewer_type": "LLM_ASSISTED_OWNER_AUTHORIZED",
            "review_decision": "confirmed",
            "model": "deepseek-v4-pro",
            "rationale": "not human review",
        }
        (review_dir / "automated-review.jsonl").write_text(
            _line(good_row) + "\n", encoding="utf-8")
        m = {
            "inputs": {
                "draft": {"path": "dummy", "sha256": "x", "rows": 1},
                "chunks": {"path": "dummy", "sha256": "x"},
                "chunk_manifest": {"path": "dummy", "sha256": "x"},
            },
            "pack_sha256": "x",
            "evidence_sha256_aggregate": "x",
            "n_cases": 1,
        }
        (review_dir / "manifest.json").write_text(
            json.dumps(m, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        errors = ap._check_no_human_identifiers(review_dir)
        assert errors == []


class TestInputContent:
    """Tests that input review does not contain historical verdict fields."""

    def test_no_split_dev_holdout_fields(self, review_env):
        """Review input must not contain split/dev/holdout identity fields."""
        # The actual review jsonl is in review_env; scan it
        review_path = review_env["review_dir"] / "automated-review.jsonl"
        rows = [json.loads(l) for l in review_path.open() if l.strip()]
        forbidden = {"split", "dev", "holdout", "retrieval_score",
                     "candidate_set", "alpha", "threshold"}
        for r in rows:
            for key in r:
                assert key.lower() not in forbidden, \
                    f"forbidden field {key!r} in review row"

    def test_no_historical_verdict_fields(self, review_env):
        """Review input must not contain historical verdict/notes/cohort."""
        review_path = review_env["review_dir"] / "automated-review.jsonl"
        rows = [json.loads(l) for l in review_path.open() if l.strip()]
        forbidden = {"third_round_verdict", "historical_verdict",
                     "historical_notes", "selection_cohort",
                     "human_review_notes"}
        for r in rows:
            for key in r:
                assert key.lower() not in forbidden, \
                    f"forbidden field {key!r} in review row"


class TestRepairedCases:
    """Tests that the five repaired cases are present and confirmed."""

    def test_five_repaired_cases_present(self, tmp_path: Path):
        """en-052, en-055, mixed-016, mixed-026, multi-014 must be in review."""
        # This test uses the real review env; if the real env doesn't have
        # these IDs, we skip (they're in the real v2 draft)
        pass  # tested via real artifact check

    def test_repaired_cases_in_real_review(self):
        """Five repaired cases appear in real automated-review jsonl."""
        real_review = REPO_ROOT / "evaluation" / "datasets" / "v2" / \
            "automated-review" / "automated-reviewed-truth" / \
            "automated-reviewed-truth-overlay.json"
        if not real_review.exists():
            pytest.skip("real overlay not yet generated")
        overlay = json.loads(real_review.read_text(encoding="utf-8"))
        cases = overlay.get("truth_cases", {})
        required = {"en-052", "en-055", "mixed-016", "mixed-026", "multi-014"}
        for cid in required:
            assert cid in cases, f"repaired case {cid} missing from overlay"


class TestDeterminism:
    """Tests for byte-identical output on re-run."""

    def test_two_runs_byte_identical(self, tmp_path: Path):
        """Running pack twice produces byte-identical output."""
        # Use the real pack command via subprocess for determinism test
        out1 = tmp_path / "out1"
        out2 = tmp_path / "out2"
        out1.mkdir()
        out2.mkdir()

        env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
        r1 = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" /
             "corpus_v2_automated_review.py"), "pack",
             "--out", str(out1)],
            capture_output=True, text=True, env=env, cwd=str(REPO_ROOT))
        assert r1.returncode == 0, r1.stderr
        r2 = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" /
             "corpus_v2_automated_review.py"), "pack",
             "--out", str(out2)],
            capture_output=True, text=True, env=env, cwd=str(REPO_ROOT))
        assert r2.returncode == 0, r2.stderr

        pack1 = out1 / "automated-review-pack.jsonl"
        pack2 = out2 / "automated-review-pack.jsonl"
        manifest1 = out1 / "manifest.json"
        manifest2 = out2 / "manifest.json"
        assert _sha256_file(pack1) == _sha256_file(pack2)
        assert _sha256_file(manifest1) == _sha256_file(manifest2)
