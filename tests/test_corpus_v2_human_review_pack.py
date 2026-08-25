"""Tests for scripts.corpus_v2_human_review_pack — blind human-review pack.

The pack is derived from the v2 draft + chunk corpus **only** and is meant
for a human reviewer: every row carries the query, multi-turn context, the
draft labels and the chunk evidence, plus three *empty* fields the human
fills in.  Fail-closed: no split/dev/holdout identity, no auto-review
conclusions (decision/confidence/rationale/model), no repair actions, no
retrieval scores or candidate sets — any such field is an illegal key and
fails loudly; human fields must start empty; evidence must be contiguous;
manifest SHA drift fails; two builds must be byte-identical.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import scripts.corpus_v2_human_review_pack as hp

CHUNK_TEXT_A = ("Alpha component is defined here. Extra filler text that "
                "extends the chunk beyond the snippet boundary.")
CHUNK_TEXT_B = ("Beta system reference carries details. More padding text "
                "to make this chunk longer.")


def _case(cid: str, query: str, *, source: str = "src-a",
          chunk_id: str | None = None, snippet: str | None = None,
          should_refuse: bool = False, relevance_level: str = "chunk",
          points: list[str] | None = None,
          turn: int = 1, follow_up_to: str | None = None,
          chain_id: str | None = None) -> dict:
    points = ["point"] if points is None else points
    chunks: list[dict] = []
    chunk_ids: list[str] = []
    if chunk_id is not None:
        chunks = [{"chunk_id": chunk_id, "chunk_text_snippet": snippet,
                   "source_id": source, "page": None, "section": "sec"}]
        chunk_ids = [chunk_id]
    return {
        "id": cid, "query": query, "language": "zh",
        "query_type": "single_fact",
        "should_refuse": should_refuse,
        "relevance_level": relevance_level,
        "acceptable_answer_points": points,
        "relevant_source_ids": [] if should_refuse else [source],
        "relevant_chunk_ids": chunk_ids,
        "relevant_chunks": chunks,
        "metadata": {"turn": turn, "follow_up_to": follow_up_to,
                     "chain_id": chain_id, "difficulty": "easy",
                     "band_target": "normal", "construction": "seed"},
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                              for r in rows) + "\n", encoding="utf-8")


@pytest.fixture
def synthetic(tmp_path: Path) -> dict[str, Path]:
    """3-case world: h-001 answerable, h-002 follow-up, h-003 refusal."""
    draft = [
        _case("h-001", "What is the alpha component?",
              chunk_id="chunk-1", snippet="Alpha component is defined here.",
              chain_id="h-001"),
        _case("h-002", "And where does beta fit in?",
              chunk_id="chunk-1", snippet="Alpha component is defined here.",
              turn=2, follow_up_to="h-001", chain_id="h-001"),
        _case("h-003", "What is the answer to an unanswerable question?",
              should_refuse=True, relevance_level="none", points=[]),
    ]
    chunks = [
        {"chunk_id": "chunk-1", "source": "src-a", "text": CHUNK_TEXT_A},
        {"chunk_id": "chunk-2", "source": "src-b", "text": CHUNK_TEXT_B},
    ]
    p = tmp_path
    out = {
        "draft": p / "draft.jsonl", "chunks": p / "chunks.jsonl",
        "chunk_manifest": p / "chunk-manifest.json",
        "corpus_manifest": p / "corpus-manifest.json",
        "ledger": p / "ledger.jsonl",
        "out_a": p / "out-a", "out_b": p / "out-b",
    }
    _write_jsonl(out["draft"], draft)
    _write_jsonl(out["chunks"], chunks)
    out["chunk_manifest"].write_text('{"corpus_version": "x"}\n',
                                     encoding="utf-8")
    out["corpus_manifest"].write_text('{"documents": []}\n', encoding="utf-8")
    _write_jsonl(out["ledger"], [
        {"case_id": "h-001", "action": "corrected", "old_summary": "",
         "new_summary": "", "evidence": [], "rationale": ""},
    ])
    return out


def _build(d: dict[str, Path], out: str = "out_a",
           expected_total: int = 3) -> Path:
    return hp.build_pack(draft_path=d["draft"], chunks_path=d["chunks"],
                         chunk_manifest_path=d["chunk_manifest"],
                         corpus_manifest_path=d["corpus_manifest"],
                         ledger_path=d["ledger"], out_dir=d[out],
                         expected_total=expected_total)


def _rows(pack: Path) -> list[dict]:
    return [json.loads(l) for l in pack.open(encoding="utf-8")
            if l.strip()]


# ── happy path ────────────────────────────────────────────────────────

def test_build_ok_and_row_contract(synthetic: dict[str, Path]) -> None:
    pack = _build(synthetic)
    rows = _rows(pack)
    assert [r["case_id"] for r in rows] == ["h-001", "h-002", "h-003"]
    for r in rows:
        assert set(r) == hp.ALLOWED_KEYS, r["case_id"]
        assert r["human_review_decision"] == ""
        assert r["human_reviewer"] == ""
        assert r["human_review_notes"] == ""
    ev = rows[0]["evidence"]
    assert set(ev[0]) == hp.EVIDENCE_KEYS
    assert ev[0] == {"source_id": "src-a", "chunk_id": "chunk-1",
                     "snippet": "Alpha component is defined here.",
                     "section": "sec"}
    assert rows[0]["relevant_source_ids"] == ["src-a"]
    assert rows[0]["acceptable_answer_points"] == ["point"]


def test_previous_turns_filled(synthetic: dict[str, Path]) -> None:
    rows = _rows(_build(synthetic))
    by_id = {r["case_id"]: r for r in rows}
    assert by_id["h-001"]["previous_turns"] == []
    assert by_id["h-002"]["previous_turns"] == [
        {"case_id": "h-001", "query": "What is the alpha component?"}]


def test_refusal_row_shape(synthetic: dict[str, Path]) -> None:
    rows = _rows(_build(synthetic))
    r = [x for x in rows if x["case_id"] == "h-003"][0]
    assert r["should_refuse"] is True
    assert r["relevance_level"] == "none"
    assert r["evidence"] == []
    assert r["acceptable_answer_points"] == []
    assert r["relevant_source_ids"] == []


def test_two_builds_byte_identical(synthetic: dict[str, Path]) -> None:
    _build(synthetic, "out_a")
    _build(synthetic, "out_b")
    names = ("human-review-pack.jsonl", "human-review-pack-manifest.json",
             "HUMAN_REVIEW_INSTRUCTIONS.md", "human-review-pack-report.md")
    for n in names:
        a = (synthetic["out_a"] / n).read_bytes()
        b = (synthetic["out_b"] / n).read_bytes()
        assert a == b, f"{n} not byte-identical"


def test_verify_ok_after_build(synthetic: dict[str, Path]) -> None:
    pack = _build(synthetic)
    errs = hp.verify(pack.parent / "human-review-pack-manifest.json")
    assert errs == []


# ── build-time fail-closed ────────────────────────────────────────────

def test_missing_chunk_fails(synthetic: dict[str, Path]) -> None:
    draft = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    draft[0]["relevant_chunks"][0]["chunk_id"] = "chunk-999"
    draft[0]["relevant_chunk_ids"] = ["chunk-999"]
    _write_jsonl(synthetic["draft"], draft)
    with pytest.raises(ValueError, match="chunk-999"):
        _build(synthetic)


def test_non_contiguous_snippet_fails(synthetic: dict[str, Path]) -> None:
    draft = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    draft[0]["relevant_chunks"][0]["chunk_text_snippet"] = (
        "Totally unrelated text.")
    _write_jsonl(synthetic["draft"], draft)
    with pytest.raises(ValueError, match="连续"):
        _build(synthetic)


def test_chunk_source_mismatch_fails(synthetic: dict[str, Path]) -> None:
    draft = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    draft[0]["relevant_chunks"][0]["source_id"] = "src-b"
    _write_jsonl(synthetic["draft"], draft)
    with pytest.raises(ValueError, match="source"):
        _build(synthetic)


def test_duplicate_case_id_fails(synthetic: dict[str, Path]) -> None:
    draft = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    _write_jsonl(synthetic["draft"], draft + [dict(draft[0])])
    with pytest.raises(ValueError, match="duplicate"):
        _build(synthetic)


def test_expected_total_mismatch_fails(synthetic: dict[str, Path]) -> None:
    with pytest.raises(ValueError, match="150"):
        hp.build_pack(draft_path=synthetic["draft"],
                      chunks_path=synthetic["chunks"],
                      chunk_manifest_path=synthetic["chunk_manifest"],
                      corpus_manifest_path=synthetic["corpus_manifest"],
                      ledger_path=synthetic["ledger"],
                      out_dir=synthetic["out_a"], expected_total=150)


def test_chunk_level_without_evidence_fails(
        synthetic: dict[str, Path]) -> None:
    draft = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    draft[0]["relevant_chunks"] = []
    draft[0]["relevant_chunk_ids"] = []
    _write_jsonl(synthetic["draft"], draft)
    with pytest.raises(ValueError, match="证据"):
        _build(synthetic)


def test_invalid_relevance_level_fails(synthetic: dict[str, Path]) -> None:
    draft = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    draft[2]["relevance_level"] = "weird"
    _write_jsonl(synthetic["draft"], draft)
    with pytest.raises(ValueError, match="relevance_level"):
        _build(synthetic)


def test_broken_chain_fails(synthetic: dict[str, Path]) -> None:
    draft = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    draft[1]["metadata"]["follow_up_to"] = "h-999"
    _write_jsonl(synthetic["draft"], draft)
    with pytest.raises(ValueError, match="follow_up_to"):
        _build(synthetic)


# ── verify: tamper detection ──────────────────────────────────────────

def _errs_after_pack_edit(synthetic: dict[str, Path],
                          edit) -> list[str]:
    pack = _build(synthetic)
    rows = _rows(pack)
    edit(rows)
    _write_jsonl(pack, rows)
    return hp.verify(pack.parent / "human-review-pack-manifest.json")


def test_verify_detects_filled_human_field(synthetic: dict[str, Path]) -> None:
    def edit(rows: list[dict]) -> None:
        rows[0]["human_review_decision"] = "confirmed"
    errs = _errs_after_pack_edit(synthetic, edit)
    assert any("人工" in e for e in errs)


def test_verify_detects_illegal_key(synthetic: dict[str, Path]) -> None:
    def edit(rows: list[dict]) -> None:
        rows[0]["split"] = "dev"
    errs = _errs_after_pack_edit(synthetic, edit)
    assert any("split" in e for e in errs)


def test_verify_detects_missing_row(synthetic: dict[str, Path]) -> None:
    def edit(rows: list[dict]) -> None:
        rows.pop()
    errs = _errs_after_pack_edit(synthetic, edit)
    assert any("manifest" in e for e in errs)


def test_verify_detects_duplicate_row(synthetic: dict[str, Path]) -> None:
    def edit(rows: list[dict]) -> None:
        rows.append(dict(rows[0]))
    errs = _errs_after_pack_edit(synthetic, edit)
    assert any("重复" in e for e in errs)


def test_verify_detects_unsorted_rows(synthetic: dict[str, Path]) -> None:
    def edit(rows: list[dict]) -> None:
        rows.reverse()
    errs = _errs_after_pack_edit(synthetic, edit)
    assert any("排序" in e for e in errs)


def test_verify_detects_previous_turns_drift(
        synthetic: dict[str, Path]) -> None:
    def edit(rows: list[dict]) -> None:
        rows[1]["previous_turns"] = []
    errs = _errs_after_pack_edit(synthetic, edit)
    assert any("previous_turns" in e for e in errs)


def test_verify_detects_evidence_tamper(synthetic: dict[str, Path]) -> None:
    def edit(rows: list[dict]) -> None:
        rows[0]["evidence"][0]["snippet"] = "Totally unrelated text."
    errs = _errs_after_pack_edit(synthetic, edit)
    assert any("连续" in e for e in errs)


def test_verify_detects_draft_drift(synthetic: dict[str, Path]) -> None:
    _build(synthetic)
    with synthetic["draft"].open("a", encoding="utf-8") as f:
        f.write("tamper\n")
    errs = hp.verify(synthetic["out_a"] / "human-review-pack-manifest.json")
    assert any("漂移" in e for e in errs)


def test_verify_detects_chunks_drift(synthetic: dict[str, Path]) -> None:
    _build(synthetic)
    with synthetic["chunks"].open("a", encoding="utf-8") as f:
        f.write("tamper\n")
    errs = hp.verify(synthetic["out_a"] / "human-review-pack-manifest.json")
    assert any("漂移" in e for e in errs)


def test_verify_detects_forbidden_phrase(synthetic: dict[str, Path]) -> None:
    def edit(rows: list[dict]) -> None:
        rows[0]["query"] = "HUMAN_APPROVED marker"
    errs = _errs_after_pack_edit(synthetic, edit)
    assert any("HUMAN_APPROVED" in e for e in errs)


def test_verify_fails_on_missing_manifest(synthetic: dict[str, Path]) -> None:
    errs = hp.verify(synthetic["out_a"] / "nope-manifest.json")
    assert errs


# ── output purity: no forbidden markers anywhere ──────────────────────

def test_outputs_free_of_forbidden_markers(
        synthetic: dict[str, Path]) -> None:
    pack = _build(synthetic)
    files = [
        pack, pack.parent / "human-review-pack-manifest.json",
        pack.parent / "HUMAN_REVIEW_INSTRUCTIONS.md",
        pack.parent / "human-review-pack-report.md",
    ]
    for f in files:
        text = f.read_text(encoding="utf-8")
        for phrase in hp.FORBIDDEN_PHRASES:
            assert phrase not in text, f"{f.name} contains {phrase!r}"
    pack_text = pack.read_text(encoding="utf-8")
    assert hp._FORBIDDEN_KEY_RE.search(pack_text) is None
    assert "deepseek" not in pack_text.lower()
    assert "LLM_ASSISTED_SECOND_PASS" not in pack_text
    assert "auto-review" not in pack_text


def test_report_aggregates_only(synthetic: dict[str, Path]) -> None:
    pack = _build(synthetic)
    md = (pack.parent / "human-review-pack-report.md").read_text(
        encoding="utf-8")
    assert "3" in md
    assert "尚未进行人工终审" in md
    assert "不得进入 v2.1" in md
    assert re.search(r"[0-9a-f]{64}", md) is not None
    assert "dev" not in md.lower() and "holdout" not in md.lower()
    assert "split" not in md.lower()


def test_instructions_cover_decision_semantics(
        synthetic: dict[str, Path]) -> None:
    pack = _build(synthetic)
    md = (pack.parent / "HUMAN_REVIEW_INSTRUCTIONS.md").read_text(
        encoding="utf-8")
    for word in ("confirmed", "reject", "needs_followup",
                 "human_review_decision", "human_reviewer",
                 "human_review_notes", "不得进入 v2.1", "绝不自动填值"):
        assert word in md


# ── real corpus (offline, no LLM) ─────────────────────────────────────

def test_real_corpus_build_and_verify(tmp_path: Path) -> None:
    """真实语料：150 行、id 与草稿一致、验证通过、两次构建逐字节一致。"""
    d = {
        "draft": hp.DEFAULT_DRAFT, "chunks": hp.DEFAULT_CHUNKS,
        "chunk_manifest": hp.DEFAULT_CHUNK_MANIFEST,
        "corpus_manifest": hp.DEFAULT_CORPUS_MANIFEST,
        "ledger": hp.DEFAULT_LEDGER,
        "out_a": tmp_path / "out-a", "out_b": tmp_path / "out-b",
    }
    pack_a = _build(d, "out_a", expected_total=150)
    pack_b = _build(d, "out_b", expected_total=150)
    rows = _rows(pack_a)
    assert len(rows) == 150
    draft_ids = [json.loads(l)["id"] for l in
                 d["draft"].open(encoding="utf-8") if l.strip()]
    assert [r["case_id"] for r in rows] == sorted(draft_ids)
    assert (pack_a.read_bytes() == pack_b.read_bytes())
    assert (pack_a.parent / "human-review-pack-manifest.json").read_bytes() \
        == (pack_b.parent / "human-review-pack-manifest.json").read_bytes()
    errs = hp.verify(pack_a.parent / "human-review-pack-manifest.json")
    assert errs == []
