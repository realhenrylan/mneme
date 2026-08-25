"""Tests for scripts.corpus_v2_human_review_apply — strict import of
human review decisions.

The apply tool takes the human-filled review pack (decision ∈
confirmed/reject/needs_followup, non-empty reviewer) and either
(a) generates a deterministic ``human-reviewed-truth-overlay.json`` +
manifest when all rows are confirmed, (b) writes only an issue list when
any row is reject/needs_followup, or (c) fails with ZERO output on any
illegal state (empty/illegal decision, empty reviewer, duplicate/missing/
unknown case, tampered fields or evidence).  Everything except the three
human fields must match the original pack (canonical JSON per case);
input SHA chain and evidence-to-chunk/source mapping are re-verified.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.corpus_v2_human_review_apply as hra
import scripts.corpus_v2_human_review_pack as hp

CHUNK_TEXT_A = ("Alpha component is defined here. Extra filler text that "
                "extends the chunk beyond the snippet boundary.")
CHUNK_TEXT_B = ("Beta system reference carries details. More padding text "
                "to make this chunk longer.")


def _case(cid: str, query: str, *, chunk_id: str | None = None,
          snippet: str | None = None, should_refuse: bool = False,
          relevance_level: str = "chunk", points: list[str] | None = None,
          turn: int = 1, follow_up_to: str | None = None,
          chain_id: str | None = None) -> dict:
    points = ["point"] if points is None else points
    chunks: list[dict] = []
    chunk_ids: list[str] = []
    if chunk_id is not None:
        chunks = [{"chunk_id": chunk_id, "chunk_text_snippet": snippet,
                   "source_id": "src-a", "page": None, "section": "sec"}]
        chunk_ids = [chunk_id]
    return {
        "id": cid, "query": query, "language": "zh",
        "query_type": "single_fact",
        "should_refuse": should_refuse,
        "relevance_level": relevance_level,
        "acceptable_answer_points": points,
        "relevant_source_ids": [] if should_refuse else ["src-a"],
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
def world(tmp_path: Path) -> dict[str, Path]:
    """3-case world with original pack built by the pack tool."""
    draft = [
        _case("h-001", "What is the alpha component?",
              chunk_id="chunk-1",
              snippet="Alpha component is defined here.", chain_id="h-001"),
        _case("h-002", "And where does beta fit in?",
              chunk_id="chunk-1",
              snippet="Alpha component is defined here.",
              turn=2, follow_up_to="h-001", chain_id="h-001"),
        _case("h-003", "Unanswerable question?", should_refuse=True,
              relevance_level="none", points=[]),
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
        "pack_dir": p / "pack", "filled": p / "filled.jsonl",
        "out": p / "out", "out2": p / "out2",
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
    hp.build_pack(draft_path=out["draft"], chunks_path=out["chunks"],
                  chunk_manifest_path=out["chunk_manifest"],
                  corpus_manifest_path=out["corpus_manifest"],
                  ledger_path=out["ledger"], out_dir=out["pack_dir"],
                  expected_total=3)
    return out


def _orig_rows(world: dict[str, Path]) -> list[dict]:
    return [json.loads(l) for l in
            (world["pack_dir"] / "human-review-pack.jsonl").open(
                encoding="utf-8") if l.strip()]


def _fill(rows: list[dict], decisions: dict[str, str],
          reviewer: str = "tester", notes: str = "") -> list[dict]:
    """返回填写了人工字段的行副本（不改原行）。"""
    filled: list[dict] = []
    for r in rows:
        c = dict(r)
        c["human_review_decision"] = decisions.get(c["case_id"], "")
        c["human_reviewer"] = reviewer
        c["human_review_notes"] = notes
        filled.append(c)
    return filled


def _run(world: dict[str, Path], filled: list[dict],
         out: str = "out") -> dict:
    _write_jsonl(world["filled"], filled)
    return hra.apply(pack_path=world["filled"],
                     pack_manifest_path=world["pack_dir"] /
                     "human-review-pack-manifest.json",
                     out_dir=world[out])


def _out_files(world: dict[str, Path], out: str = "out") -> list[str]:
    d = world[out]
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


# ── 150/150 confirmed → overlay ───────────────────────────────────────

def test_all_confirmed_generates_overlay(world: dict[str, Path]) -> None:
    res = _run(world, _fill(_orig_rows(world), {"h-001": "confirmed",
                                                "h-002": "confirmed",
                                                "h-003": "confirmed"}))
    assert res["status"] == "overlay" and res["errors"] == []
    assert res["counts"] == {"confirmed": 3, "reject": 0,
                             "needs_followup": 0}
    files = _out_files(world)
    assert "human-reviewed-truth-overlay.json" in files
    assert "human-reviewed-truth-overlay-manifest.json" in files
    assert not any(f.startswith("human-review-issues") for f in files)


def test_overlay_truth_fields_and_order(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world), {"h-001": "confirmed",
                                          "h-002": "confirmed",
                                          "h-003": "confirmed"}))
    ov = json.loads((world["out"] / "human-reviewed-truth-overlay.json")
                    .read_text(encoding="utf-8"))
    assert ov["status"] == "HUMAN_REVIEWED"
    assert ov["n_cases"] == 3
    cases = ov["cases"]
    assert [c["case_id"] for c in cases] == ["h-001", "h-002", "h-003"]
    assert set(cases[0]) == hra.CASE_KEYS
    assert cases[0]["should_refuse"] is False
    assert cases[0]["relevance_level"] == "chunk"
    assert cases[0]["acceptable_answer_points"] == ["point"]
    assert cases[0]["relevant_source_ids"] == ["src-a"]
    assert cases[0]["relevant_chunk_ids"] == ["chunk-1"]
    assert cases[0]["reviewer"] == "tester"
    assert cases[2]["should_refuse"] is True
    assert cases[2]["relevant_chunk_ids"] == []


def test_overlay_deterministic(world: dict[str, Path]) -> None:
    filled = _fill(_orig_rows(world), {"h-001": "confirmed",
                                       "h-002": "confirmed",
                                       "h-003": "confirmed"})
    _run(world, filled, "out")
    _run(world, filled, "out2")
    for name in ("human-reviewed-truth-overlay.json",
                 "human-reviewed-truth-overlay-manifest.json"):
        assert (world["out"] / name).read_bytes() == \
            (world["out2"] / name).read_bytes()


def test_overlay_manifest_records_inputs(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world), {"h-001": "confirmed",
                                          "h-002": "confirmed",
                                          "h-003": "confirmed"}))
    m = json.loads((world["out"] / "human-reviewed-truth-overlay-manifest.json")
                   .read_text(encoding="utf-8"))
    assert m["status"] == "HUMAN_REVIEWED"
    assert m["reviewers"] == ["tester"]
    for key in ("draft", "chunks", "chunk_manifest", "corpus_manifest",
                "repair_ledger", "human_review_pack"):
        assert key in m["inputs"]
    assert m["inputs"]["human_review_pack"]["sha256"] == \
        hp._sha256_file(world["filled"])


# ── fail-closed: illegal states → zero output ─────────────────────────

def _assert_zero_output(world: dict[str, Path], res: dict) -> None:
    assert res["status"] == "failed"
    assert res["errors"]
    assert _out_files(world) == []


def test_empty_decision_fails_zero_output(world: dict[str, Path]) -> None:
    rows = _orig_rows(world)
    rows[0]["human_review_decision"] = ""
    _assert_zero_output(world, _run(world, rows))


def test_illegal_decision_fails(world: dict[str, Path]) -> None:
    rows = _orig_rows(world)
    rows[0]["human_review_decision"] = "maybe"
    res = _run(world, rows)
    assert res["status"] == "failed"
    assert any("maybe" in e for e in res["errors"])


def test_blank_reviewer_fails(world: dict[str, Path]) -> None:
    rows = _orig_rows(world)
    for r in rows:
        r["human_review_decision"] = "confirmed"
    rows[1]["human_reviewer"] = "   "
    res = _run(world, rows)
    assert res["status"] == "failed"
    assert any("h-002" in e and "reviewer" in e for e in res["errors"])


def test_duplicate_case_fails(world: dict[str, Path]) -> None:
    rows = _orig_rows(world)
    rows.append(dict(rows[0]))
    _assert_zero_output(world, _run(world, rows))


def test_missing_case_fails(world: dict[str, Path]) -> None:
    rows = _orig_rows(world)[:-1]
    _assert_zero_output(world, _run(world, rows))


def test_unknown_case_fails(world: dict[str, Path]) -> None:
    rows = _orig_rows(world)
    rows[0]["case_id"] = "x-999"
    res = _run(world, rows)
    assert res["status"] == "failed"
    assert any("x-999" in e for e in res["errors"])


def test_tampered_query_fails(world: dict[str, Path]) -> None:
    rows = _orig_rows(world)
    rows[0]["query"] = "tampered question?"
    res = _run(world, rows)
    assert res["status"] == "failed"
    assert any("篡改" in e for e in res["errors"])


def test_tampered_should_refuse_fails(world: dict[str, Path]) -> None:
    rows = _orig_rows(world)
    rows[2]["should_refuse"] = False
    res = _run(world, rows)
    assert res["status"] == "failed"
    assert any("篡改" in e for e in res["errors"])


def test_tampered_evidence_fails(world: dict[str, Path]) -> None:
    rows = _orig_rows(world)
    rows[0]["evidence"][0]["snippet"] = "Totally unrelated text."
    res = _run(world, rows)
    assert res["status"] == "failed"
    assert any("篡改" in e for e in res["errors"])


def test_extra_key_fails(world: dict[str, Path]) -> None:
    rows = _orig_rows(world)
    rows[0]["split"] = "dev"
    _assert_zero_output(world, _run(world, rows))


def test_chunks_drift_fails(world: dict[str, Path]) -> None:
    with world["chunks"].open("a", encoding="utf-8") as f:
        f.write("tamper\n")
    res = _run(world, _fill(_orig_rows(world), {"h-001": "confirmed",
                                                "h-002": "confirmed",
                                                "h-003": "confirmed"}))
    assert res["status"] == "failed"
    assert any("chunks" in e for e in res["errors"])


def test_draft_drift_fails(world: dict[str, Path]) -> None:
    with world["draft"].open("a", encoding="utf-8") as f:
        f.write("tamper\n")
    res = _run(world, _fill(_orig_rows(world), {"h-001": "confirmed",
                                                "h-002": "confirmed",
                                                "h-003": "confirmed"}))
    assert res["status"] == "failed"
    assert any("draft" in e for e in res["errors"])


def test_pack_manifest_tamper_fails(world: dict[str, Path]) -> None:
    mpath = world["pack_dir"] / "human-review-pack-manifest.json"
    m = json.loads(mpath.read_text(encoding="utf-8"))
    m["pack_sha256"] = "0" * 64
    mpath.write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n",
                     encoding="utf-8")
    res = _run(world, _fill(_orig_rows(world), {"h-001": "confirmed",
                                                "h-002": "confirmed",
                                                "h-003": "confirmed"}))
    assert res["status"] == "failed"
    assert any("pack" in e for e in res["errors"])


def test_row_order_insensitive(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), {"h-001": "confirmed",
                                     "h-002": "confirmed",
                                     "h-003": "confirmed"})
    rows.reverse()
    res = _run(world, rows)
    assert res["status"] == "overlay" and res["errors"] == []


# ── reject / needs_followup → issue list, no overlay ──────────────────

def test_reject_blocks_overlay_writes_issues(world: dict[str, Path]) -> None:
    res = _run(world, _fill(_orig_rows(world),
                            {"h-001": "confirmed", "h-002": "confirmed",
                             "h-003": "reject"}, notes="证据不足"))
    assert res["status"] == "issues"
    assert res["counts"] == {"confirmed": 2, "reject": 1,
                             "needs_followup": 0}
    assert res["blocked"] == ["h-003"]
    files = _out_files(world)
    assert "human-reviewed-truth-overlay.json" not in files
    assert "human-reviewed-truth-overlay-manifest.json" not in files
    issues = [json.loads(l) for l in
              (world["out"] / "human-review-issues.jsonl").open(
                  encoding="utf-8") if l.strip()]
    assert [i["case_id"] for i in issues] == ["h-003"]
    assert issues[0]["decision"] == "reject" and issues[0]["notes"] == "证据不足"


def test_needs_followup_blocks_overlay(world: dict[str, Path]) -> None:
    res = _run(world, _fill(_orig_rows(world),
                            {"h-001": "needs_followup",
                             "h-002": "confirmed", "h-003": "confirmed"}))
    assert res["status"] == "issues"
    assert res["blocked"] == ["h-001"]
    assert "human-reviewed-truth-overlay.json" not in _out_files(world)


def test_mixed_counts_and_blocked_order(world: dict[str, Path]) -> None:
    res = _run(world, _fill(_orig_rows(world),
                            {"h-001": "confirmed", "h-002": "reject",
                             "h-003": "needs_followup"}, notes="n"))
    assert res["counts"] == {"confirmed": 1, "reject": 1,
                             "needs_followup": 1}
    assert res["blocked"] == ["h-002", "h-003"]
    issues = [json.loads(l) for l in
              (world["out"] / "human-review-issues.jsonl").open(
                  encoding="utf-8") if l.strip()]
    assert [i["case_id"] for i in issues] == ["h-002", "h-003"]


# ── verify: overlay chain re-check ────────────────────────────────────

def test_verify_ok_after_apply(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world), {"h-001": "confirmed",
                                          "h-002": "confirmed",
                                          "h-003": "confirmed"}))
    mpath = world["out"] / "human-reviewed-truth-overlay-manifest.json"
    assert hra.verify(mpath) == []


def test_verify_detects_overlay_tamper(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world), {"h-001": "confirmed",
                                          "h-002": "confirmed",
                                          "h-003": "confirmed"}))
    ov = world["out"] / "human-reviewed-truth-overlay.json"
    ov.write_text(ov.read_text(encoding="utf-8") + "x", encoding="utf-8")
    errs = hra.verify(world["out"] /
                      "human-reviewed-truth-overlay-manifest.json")
    assert any("overlay" in e for e in errs)


def test_verify_detects_draft_drift(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world), {"h-001": "confirmed",
                                          "h-002": "confirmed",
                                          "h-003": "confirmed"}))
    with world["draft"].open("a", encoding="utf-8") as f:
        f.write("tamper\n")
    errs = hra.verify(world["out"] /
                      "human-reviewed-truth-overlay-manifest.json")
    assert any("draft" in e for e in errs)


def test_verify_detects_filled_pack_drift(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world), {"h-001": "confirmed",
                                          "h-002": "confirmed",
                                          "h-003": "confirmed"}))
    rows = [json.loads(l) for l in
            world["filled"].open(encoding="utf-8") if l.strip()]
    rows[0]["human_review_notes"] = "changed after apply"
    _write_jsonl(world["filled"], rows)
    errs = hra.verify(world["out"] /
                      "human-reviewed-truth-overlay-manifest.json")
    assert any("human_review_pack" in e for e in errs)


def test_no_auto_approval_claims(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world), {"h-001": "confirmed",
                                          "h-002": "confirmed",
                                          "h-003": "confirmed"}))
    for name in ("human-reviewed-truth-overlay.json",
                 "human-reviewed-truth-overlay-manifest.json"):
        text = (world["out"] / name).read_text(encoding="utf-8")
        assert "HUMAN_REVIEWED" in text
        assert "上线批准" not in text and "已进入 v2.1" not in text
    report = (world["out"] / "human-review-issues-report.md")
    assert not report.exists()


# ── real corpus (offline, no LLM) ─────────────────────────────────────

def test_real_corpus_confirmed_path(tmp_path: Path) -> None:
    """真实语料：全 150 confirmed → overlay + manifest + verify 通过。"""
    d = {
        "draft": hp.DEFAULT_DRAFT, "chunks": hp.DEFAULT_CHUNKS,
        "chunk_manifest": hp.DEFAULT_CHUNK_MANIFEST,
        "corpus_manifest": hp.DEFAULT_CORPUS_MANIFEST,
        "ledger": hp.DEFAULT_LEDGER,
        "pack_dir": tmp_path / "pack", "filled": tmp_path / "filled.jsonl",
        "out": tmp_path / "out", "out2": tmp_path / "out2",
    }
    hp.build_pack(draft_path=d["draft"], chunks_path=d["chunks"],
                  chunk_manifest_path=d["chunk_manifest"],
                  corpus_manifest_path=d["corpus_manifest"],
                  ledger_path=d["ledger"], out_dir=d["pack_dir"])
    orig = [json.loads(l) for l in
            (d["pack_dir"] / "human-review-pack.jsonl").open(
                encoding="utf-8") if l.strip()]
    assert len(orig) == 150
    filled = _fill(orig, {r["case_id"]: "confirmed" for r in orig},
                   reviewer="tester-human")
    _write_jsonl(d["filled"], filled)
    res = hra.apply(pack_path=d["filled"],
                    pack_manifest_path=d["pack_dir"] /
                    "human-review-pack-manifest.json",
                    out_dir=d["out"])
    assert res["status"] == "overlay" and res["errors"] == []
    assert res["counts"] == {"confirmed": 150, "reject": 0,
                             "needs_followup": 0}
    ov = json.loads((d["out"] / "human-reviewed-truth-overlay.json")
                    .read_text(encoding="utf-8"))
    assert ov["n_cases"] == 150 and ov["status"] == "HUMAN_REVIEWED"
    assert hra.verify(d["out"] /
                      "human-reviewed-truth-overlay-manifest.json") == []
    # 确定性：第二次 apply 逐字节一致
    res2 = hra.apply(pack_path=d["filled"],
                     pack_manifest_path=d["pack_dir"] /
                     "human-review-pack-manifest.json",
                     out_dir=d["out2"])
    assert res2["status"] == "overlay"
    for name in ("human-reviewed-truth-overlay.json",
                 "human-reviewed-truth-overlay-manifest.json"):
        assert (d["out"] / name).read_bytes() == \
            (d["out2"] / name).read_bytes()


def test_real_corpus_unfilled_rejected(tmp_path: Path) -> None:
    """真实语料：未填写（decision 全空）→ 失败且零输出、无 overlay。"""
    d = {
        "draft": hp.DEFAULT_DRAFT, "chunks": hp.DEFAULT_CHUNKS,
        "chunk_manifest": hp.DEFAULT_CHUNK_MANIFEST,
        "corpus_manifest": hp.DEFAULT_CORPUS_MANIFEST,
        "ledger": hp.DEFAULT_LEDGER,
        "pack_dir": tmp_path / "pack", "filled": tmp_path / "filled.jsonl",
        "out": tmp_path / "out",
    }
    hp.build_pack(draft_path=d["draft"], chunks_path=d["chunks"],
                  chunk_manifest_path=d["chunk_manifest"],
                  corpus_manifest_path=d["corpus_manifest"],
                  ledger_path=d["ledger"], out_dir=d["pack_dir"])
    orig = [json.loads(l) for l in
            (d["pack_dir"] / "human-review-pack.jsonl").open(
                encoding="utf-8") if l.strip()]
    _write_jsonl(d["filled"], orig)  # 人工字段保持空
    res = hra.apply(pack_path=d["filled"],
                    pack_manifest_path=d["pack_dir"] /
                    "human-review-pack-manifest.json",
                    out_dir=d["out"])
    assert res["status"] == "failed" and res["errors"]
    assert not d["out"].exists() or \
        list(d["out"].iterdir()) == []
