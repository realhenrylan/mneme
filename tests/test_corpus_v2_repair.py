"""Tests for scripts.corpus_v2_repair — deterministic repair validator.

Covers the evidence-first repair loop for the 10 second-pass anomalies:
the repair ledger must cover *exactly* the 10 target case ids, every
answer point must be backed by a contiguous chunk snippet (SHA-256 tied
to the ledger), only the target rows may change between old and new
drafts, and annotations must stay ``LLM_ASSISTED`` / ``pending`` with no
HUMAN claims.  Fail-closed: any drift returns an error list instead of
silently passing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.corpus_v2_review as rv
import scripts.corpus_v2_repair as rp

CHUNK_TEXT_1 = ("X is defined as Y in the spec. Additional trailing text "
                "that extends the chunk beyond the snippet boundary.")
CHUNK_TEXT_2 = ("The component mounts when the page loads, and unmounts "
                "when the page is destroyed. Lifecycle notes follow.")


def _annotation(review_notes: str = "LLM_ASSISTED") -> dict:
    return {
        "annotated_by": "mock-draft", "annotation_version": "v2-draft",
        "created_at": "", "review_notes": review_notes,
        "review_status": "pending", "reviewed_by": "",
    }


def _case(cid: str, points: list[str], chunk_id: str, snippet: str,
          source: str = "src-a", **over) -> dict:
    case = {
        "id": cid, "query": "q", "language": "en",
        "query_type": "single_fact", "should_refuse": False,
        "relevance_level": "chunk", "doc_target": "", "note": "",
        "acceptable_answer_points": points,
        "relevant_source_ids": [source],
        "relevant_chunk_ids": [chunk_id],
        "relevant_chunks": [{
            "chunk_id": chunk_id, "chunk_text_snippet": snippet,
            "source_id": source, "page": None, "section": "s",
        }],
        "annotation": _annotation(),
        "metadata": {"chain_id": None, "follow_up_to": None, "turn": 1,
                     "difficulty": "easy", "band_target": "B",
                     "construction": "seed"},
    }
    case.update(over)
    return case


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                              for r in rows) + "\n", encoding="utf-8")


@pytest.fixture
def synthetic(tmp_path: Path) -> dict[str, Path]:
    """3-case world: t-001/t-002 are the repair targets, x-001 untouched."""
    old = [
        _case("t-001", ["X is defined as Y."], "chunk-1",
              "X is defined as Y in the spec."),
        # t-002 旧稿：答案点无证据（snippet 不包含该内容）
        _case("t-002", ["Component mounts instantly."], "chunk-2",
              "The component mounts when the page loads."),
        _case("x-001", ["Lifecycle notes follow."], "chunk-2",
              "The component mounts when the page loads."),
    ]
    new = [
        _case("t-001", ["X is defined as Y."], "chunk-1",
              "X is defined as Y in the spec."),
        # 修复：答案点改为 snippet 直接支持的内容
        _case("t-002",
              ["The component mounts when the page loads, and unmounts "
               "when the page is destroyed."],
              "chunk-2",
              "The component mounts when the page loads, and unmounts "
              "when the page is destroyed."),
        _case("x-001", ["Lifecycle notes follow."], "chunk-2",
              "The component mounts when the page loads."),
    ]
    chunks = {"chunk-1": CHUNK_TEXT_1, "chunk-2": CHUNK_TEXT_2}
    led = [
        {"case_id": "t-001", "action": "retained_after_evidence_check",
         "old_summary": "答案点正确；证据不变",
         "new_summary": "答案点与证据均不变",
         "evidence": [{"chunk_id": "chunk-1", "source_id": "src-a",
                       "snippet_sha256": rv.canonical_sha(
                           new[0]["relevant_chunks"][0]["chunk_text_snippet"])}],
         "rationale": "证据已足够，二审理由不成立。"},
        {"case_id": "t-002", "action": "corrected",
         "old_summary": "答案点无 snippet 支持",
         "new_summary": "答案点与 snippet 一致",
         "evidence": [{"chunk_id": "chunk-2", "source_id": "src-a",
                       "snippet_sha256": rv.canonical_sha(
                           new[1]["relevant_chunks"][0]["chunk_text_snippet"])}],
         "rationale": "修正答案点以匹配 chunk 原文。"},
    ]
    p = tmp_path
    out = {
        "draft": p / "draft.jsonl", "old": p / "old.jsonl",
        "ledger": p / "ledger.jsonl", "chunks": p / "chunks.jsonl",
        "out": p / "out",
    }
    _write_jsonl(out["draft"], new)
    _write_jsonl(out["old"], old)
    _write_jsonl(out["ledger"], led)
    out["chunks"].write_text(
        "\n".join(json.dumps({"chunk_id": k, "source": "src-a", "text": v},
                             ensure_ascii=False) for k, v in chunks.items())
        + "\n", encoding="utf-8")
    return out


_SYNTH_TARGETS = frozenset({"t-001", "t-002"})


def _errs(d: dict) -> list[str]:
    return rp.validate(draft_path=d["draft"], old_draft_path=d["old"],
                       ledger_path=d["ledger"], chunks_path=d["chunks"],
                       expected_total=3, target_ids=_SYNTH_TARGETS)


# ── happy path ────────────────────────────────────────────────────────

def test_valid_repair_passes(synthetic: dict[str, Path]) -> None:
    assert _errs(synthetic) == []


def test_validate_is_deterministic(synthetic: dict[str, Path]) -> None:
    assert _errs(synthetic) == _errs(synthetic)


# ── ledger id set must be exactly the target set ──────────────────────

def test_missing_target_id_fails(synthetic: dict[str, Path]) -> None:
    rows = [json.loads(l) for l in
            synthetic["ledger"].open(encoding="utf-8") if l.strip()]
    _write_jsonl(synthetic["ledger"], rows[:-1])
    errs = _errs(synthetic)
    assert any("目标" in e for e in errs)


def test_extra_target_id_fails(synthetic: dict[str, Path]) -> None:
    rows = [json.loads(l) for l in
            synthetic["ledger"].open(encoding="utf-8") if l.strip()]
    _write_jsonl(synthetic["ledger"],
                 rows + [dict(rows[0], case_id="x-001")])
    errs = _errs(synthetic)
    assert any("x-001" in e for e in errs)


# ── ledger row contract ───────────────────────────────────────────────

def test_invalid_action_fails(synthetic: dict[str, Path]) -> None:
    rows = [json.loads(l) for l in
            synthetic["ledger"].open(encoding="utf-8") if l.strip()]
    rows[0]["action"] = "fixed"
    _write_jsonl(synthetic["ledger"], rows)
    assert any("action" in e for e in _errs(synthetic))


def test_missing_ledger_fields_fail(synthetic: dict[str, Path]) -> None:
    rows = [json.loads(l) for l in
            synthetic["ledger"].open(encoding="utf-8") if l.strip()]
    for field in ("old_summary", "new_summary", "rationale"):
        bad = [dict(r) for r in rows]
        del bad[0][field]
        _write_jsonl(synthetic["ledger"], bad)
        assert any(field in e for e in _errs(synthetic))


def test_snippet_sha_must_match_draft(synthetic: dict[str, Path]) -> None:
    rows = [json.loads(l) for l in
            synthetic["ledger"].open(encoding="utf-8") if l.strip()]
    rows[0]["evidence"][0]["snippet_sha256"] = "0" * 64
    _write_jsonl(synthetic["ledger"], rows)
    assert any("SHA" in e for e in _errs(synthetic))


def test_evidence_must_cover_all_draft_evidence(
        synthetic: dict[str, Path]) -> None:
    rows = [json.loads(l) for l in
            synthetic["ledger"].open(encoding="utf-8") if l.strip()]
    # 草稿新增一块证据，但 ledger 未登记 → 必须失败
    draft = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    draft[0]["relevant_chunks"].append({
        "chunk_id": "chunk-2", "chunk_text_snippet": "Lifecycle notes follow.",
        "source_id": "src-a", "page": None, "section": "s"})
    _write_jsonl(synthetic["draft"], draft)
    assert any("evidence" in e for e in _errs(synthetic))


# ── draft integrity ───────────────────────────────────────────────────

def test_non_target_rows_must_be_unchanged(synthetic: dict[str, Path]) -> None:
    draft = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    for r in draft:
        if r["id"] == "x-001":
            r["acceptable_answer_points"] = ["tampered"]
    _write_jsonl(synthetic["draft"], draft)
    errs = _errs(synthetic)
    assert any("x-001" in e and "保持" in e for e in errs)


def test_duplicate_ids_fail(synthetic: dict[str, Path]) -> None:
    draft = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    _write_jsonl(synthetic["draft"], draft + [draft[0]])
    assert any("重复" in e for e in _errs(synthetic))


def test_row_count_enforced(synthetic: dict[str, Path]) -> None:
    errs = rp.validate(draft_path=synthetic["draft"],
                       old_draft_path=synthetic["old"],
                       ledger_path=synthetic["ledger"],
                       chunks_path=synthetic["chunks"], expected_total=150,
                       target_ids=_SYNTH_TARGETS)
    assert any("150" in e for e in errs)


def test_missing_chunk_reference_fails(synthetic: dict[str, Path]) -> None:
    draft = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    draft[1]["relevant_chunks"][0]["chunk_id"] = "chunk-999"
    draft[1]["relevant_chunk_ids"] = ["chunk-999"]
    _write_jsonl(synthetic["draft"], draft)
    assert any("chunk-999" in e for e in _errs(synthetic))


def test_paraphrased_snippet_fails(synthetic: dict[str, Path]) -> None:
    draft = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    draft[1]["relevant_chunks"][0]["chunk_text_snippet"] = (
        "The component mounts when the page loads. Paraphrased noise.")
    _write_jsonl(synthetic["draft"], draft)
    assert any("连续" in e for e in _errs(synthetic))


# ── annotation invariants ─────────────────────────────────────────────

def test_human_approval_claims_fail(synthetic: dict[str, Path]) -> None:
    draft = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    draft[0]["annotation"]["review_notes"] = "HUMAN_APPROVED"
    _write_jsonl(synthetic["draft"], draft)
    assert any("HUMAN" in e for e in _errs(synthetic))


def test_review_status_must_stay_pending(synthetic: dict[str, Path]) -> None:
    draft = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    draft[0]["annotation"]["review_status"] = "reviewed"
    _write_jsonl(synthetic["draft"], draft)
    assert any("pending" in e for e in _errs(synthetic))


# ── answerable / refusal semantics ────────────────────────────────────

def test_answerable_row_requires_evidence(synthetic: dict[str, Path]) -> None:
    draft = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    draft[1]["relevant_chunks"] = []
    draft[1]["relevant_chunk_ids"] = []
    _write_jsonl(synthetic["draft"], draft)
    assert any("evidence" in e for e in _errs(synthetic))


def test_changed_to_refusal_requires_refusal_semantics(
        synthetic: dict[str, Path]) -> None:
    rows = [json.loads(l) for l in
            synthetic["ledger"].open(encoding="utf-8") if l.strip()]
    rows[1]["action"] = "changed_to_refusal"
    _write_jsonl(synthetic["ledger"], rows)
    errs = _errs(synthetic)
    assert any("refusal" in e for e in errs)


# ── real corpus (offline, no LLM) ─────────────────────────────────────

def test_real_corpus_repair_validates() -> None:
    """真实语料：修复后的草稿 + ledger 通过验证（150 条、10 条目标）。"""
    draft = rp.ROOT / "evaluation" / "datasets" / "v2" / "annotations" / \
        "v2-cases-draft.jsonl"
    ledger = rp.ROOT / "evaluation" / "datasets" / "v2" / "review" / \
        "repair-ledger.jsonl"
    errs = rp.validate(draft_path=draft, old_draft_path=None,
                       ledger_path=ledger, chunks_path=rp.DEFAULT_CHUNKS,
                       expected_total=150)
    assert errs == []


# ── report: full-set aggregates only ──────────────────────────────────

def test_report_contains_full_set_aggregates_only(
        synthetic: dict[str, Path], tmp_path: Path) -> None:
    auto = [
        {"case_id": "t-001", "decision": "confirmed",
         "reviewer_identity": "LLM_ASSISTED_SECOND_PASS",
         "confidence": "high", "issue_categories": []},
        {"case_id": "t-002", "decision": "confirmed",
         "reviewer_identity": "LLM_ASSISTED_SECOND_PASS",
         "confidence": "high", "issue_categories": []},
    ]
    _write_jsonl(tmp_path / "auto.jsonl", auto)
    md = rp.build_report(ledger_path=synthetic["ledger"],
                         draft_path=synthetic["draft"],
                         chunks_path=synthetic["chunks"],
                         auto_path=tmp_path / "auto.jsonl",
                         old_draft_path=None)
    # 全量汇总存在
    assert "confirmed" in md and "2" in md.split("审阅条数")[1][:80]
    # 不按 split 输出
    assert "dev" not in md.lower() and "holdout" not in md.lower()
    assert "LLM_ASSISTED_SECOND_PASS" in md
