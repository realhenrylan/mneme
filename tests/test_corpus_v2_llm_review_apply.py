"""Tests for scripts.corpus_v2_llm_review_apply — diagnostic-only import
of the machine-filled review pack.

The tool validates the LLM-filled copy (reviewer ``LLM_ASSISTED_*``)
against the blank pack and the third-pass manifest/report, reusing the
strict validation helpers of the human-review apply path.  Branches:

- any reject / needs_followup → only ``llm-review-issues.jsonl`` + report,
  ZERO overlay;
- 150/150 confirmed → deterministic ``llm-reviewed-truth-overlay.json``
  with status ``LLM_REVIEWED_DIAGNOSTIC_ONLY`` (reviewer_type LLM);
- any illegal state (row/keys/tamper/evidence/manifest/report drift) →
  fail-closed with ZERO output.

The overlay must never use ``HUMAN_REVIEWED`` / ``HUMAN_APPROVED`` /
approval wording: it is a machine-review diagnostic only and cannot lift
the v2.1 human gate on its own.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

import scripts.corpus_v2_human_review_apply as hra
import scripts.corpus_v2_human_review_pack as hp
import scripts.corpus_v2_llm_review_apply as llra

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
    """3-case world: original pack built by the pack tool + third-pass
    manifest/report slots."""
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
        "llm_manifest": p / "llm-third-pass-manifest.json",
        "llm_report": p / "llm-third-pass-report.md",
        "out": p / "out", "out2": p / "out2",
        "overlay_dir": p / "llm-overlay", "overlay2": p / "llm-overlay2",
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
          reviewer: str = "LLM_ASSISTED_THIRD_PASS",
          notes: str = "") -> list[dict]:
    """返回填写了人工字段的行副本（不改原行）；reject/needs_followup
    自动附带默认 notes 以便测试聚焦于被验证的行为。"""
    filled: list[dict] = []
    for r in rows:
        c = dict(r)
        c["human_review_decision"] = decisions.get(c["case_id"], "")
        c["human_reviewer"] = reviewer
        c["human_review_notes"] = notes
        filled.append(c)
    return filled


def _make_llm_meta(world: dict[str, Path], filled: list[dict]) -> None:
    """从已填写行生成 third-pass manifest + report（与填写副本一致）。"""
    dec = {r["case_id"]: r.get("human_review_decision", "")
           for r in filled}
    counts = Counter(dec.values())
    non_confirmed = [{"case_id": cid, "decision": d, "summary": "s"}
                     for cid, d in sorted(dec.items()) if d != "confirmed"]
    manifest = {
        "total_cases": len(filled),
        "confirmed": counts["confirmed"],
        "reject": counts["reject"],
        "needs_followup": counts["needs_followup"],
        "non_confirmed": non_confirmed,
    }
    world["llm_manifest"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    lines = ["# LLM Third-Pass Review Report", "",
             f"- Total cases: {len(filled)}",
             f"- Confirmed: {counts['confirmed']}",
             f"- Reject: {counts['reject']}",
             f"- Needs follow-up: {counts['needs_followup']}", "",
             "## Non-confirmed cases", ""]
    for cid in sorted(dec):
        d = dec[cid]
        if d != "confirmed":
            lines.append(f"- {cid}: {d} — 答案点 'x' 在 evidence snippet 中"
                         "找不到直接文本支持")
        else:
            lines.append(f"- {cid}: confirmed")
    world["llm_report"].write_text("\n".join(lines) + "\n",
                                   encoding="utf-8")


def _run(world: dict[str, Path], filled: list[dict],
         out: str = "out", overlay: str = "overlay_dir",
         meta: bool = True) -> dict:
    _write_jsonl(world["filled"], filled)
    if meta:
        _make_llm_meta(world, filled)
    return llra.apply(llm_filled_path=world["filled"],
                      pack_path=world["pack_dir"] / "human-review-pack.jsonl",
                      pack_manifest_path=world["pack_dir"] /
                      "human-review-pack-manifest.json",
                      llm_manifest_path=world["llm_manifest"],
                      llm_report_path=world["llm_report"],
                      out_dir=world[out], overlay_dir=world[overlay])


def _files(world: dict[str, Path], key: str) -> list[str]:
    d = world[key]
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


ALL_CONFIRMED = {"h-001": "confirmed", "h-002": "confirmed",
                 "h-003": "confirmed"}


# ── 150/150 confirmed → 诊断 overlay ──────────────────────────────────

def test_all_confirmed_generates_diagnostic_overlay(
        world: dict[str, Path]) -> None:
    res = _run(world, _fill(_orig_rows(world), ALL_CONFIRMED))
    assert res["status"] == "overlay" and res["errors"] == []
    assert res["counts"] == {"confirmed": 3, "reject": 0,
                             "needs_followup": 0}
    assert _files(world, "overlay_dir") == [
        "llm-reviewed-truth-overlay-manifest.json",
        "llm-reviewed-truth-overlay.json"]
    assert _files(world, "out") == []


def test_overlay_status_is_diagnostic_only(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world), ALL_CONFIRMED))
    overlay = json.loads((world["overlay_dir"] /
                          "llm-reviewed-truth-overlay.json").read_text(
                              encoding="utf-8"))
    assert overlay["status"] == "LLM_REVIEWED_DIAGNOSTIC_ONLY"
    assert overlay["reviewer_type"] == "LLM"
    assert overlay["n_cases"] == 3
    assert overlay["overlay_version"] == 1


def test_overlay_cases_sorted_and_shape(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world), ALL_CONFIRMED))
    overlay = json.loads((world["overlay_dir"] /
                          "llm-reviewed-truth-overlay.json").read_text(
                              encoding="utf-8"))
    cases = overlay["cases"]
    assert [c["case_id"] for c in cases] == ["h-001", "h-002", "h-003"]
    for c in cases:
        assert set(c) == hra.CASE_KEYS
        assert c["reviewer"] == "LLM_ASSISTED_THIRD_PASS"
    by_id = {c["case_id"]: c for c in cases}
    assert by_id["h-003"]["should_refuse"] is True
    assert by_id["h-003"]["relevance_level"] == "none"
    assert by_id["h-001"]["relevant_chunk_ids"] == ["chunk-1"]


def test_overlay_has_no_human_approval_wording(
        world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world), ALL_CONFIRMED))
    for name in ("llm-reviewed-truth-overlay.json",
                 "llm-reviewed-truth-overlay-manifest.json"):
        text = (world["overlay_dir"] / name).read_text(encoding="utf-8")
        for phrase in llra.FORBIDDEN_PHRASES:
            assert phrase not in text


def test_apply_is_deterministic(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)
    _run(world, rows, out="out", overlay="overlay_dir")
    _run(world, rows, out="out2", overlay="overlay2")
    for name in ("llm-reviewed-truth-overlay.json",
                 "llm-reviewed-truth-overlay-manifest.json"):
        assert (world["overlay_dir"] / name).read_bytes() == \
            (world["overlay2"] / name).read_bytes()


def test_manifest_records_inputs(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world), ALL_CONFIRMED))
    m = json.loads((world["overlay_dir"] /
                    "llm-reviewed-truth-overlay-manifest.json").read_text(
                        encoding="utf-8"))
    assert m["status"] == "LLM_REVIEWED_DIAGNOSTIC_ONLY"
    assert m["reviewer_type"] == "LLM"
    for key in ("llm_filled_pack", "blank_pack", "llm_third_pass_manifest",
                "llm_third_pass_report", "draft", "chunks",
                "chunk_manifest", "corpus_manifest", "repair_ledger"):
        info = m["inputs"][key]
        assert "path" in info and "sha256" in info
        assert hra._sha256_file(Path(info["path"])) == info["sha256"]
    assert m["inputs"]["original_pack_sha256"] == json.loads(
        (world["pack_dir"] / "human-review-pack-manifest.json").read_text(
            encoding="utf-8"))["pack_sha256"]
    assert m["decision_counts"] == {"confirmed": 3, "reject": 0,
                                    "needs_followup": 0}
    assert m["reviewers"] == ["LLM_ASSISTED_THIRD_PASS"]


def test_blank_pack_untouched(world: dict[str, Path]) -> None:
    blank = world["pack_dir"] / "human-review-pack.jsonl"
    before = blank.read_bytes()
    _run(world, _fill(_orig_rows(world), ALL_CONFIRMED))
    assert blank.read_bytes() == before
    for r in _orig_rows(world):
        for f in hp.HUMAN_FIELDS:
            assert not (r.get(f) or "").strip()


def test_row_order_independent(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)
    _run(world, rows, out="out", overlay="overlay_dir")
    _run(world, list(reversed(rows)), out="out2", overlay="overlay2")
    # overlay 内容与行序无关（按 case_id 规范化）
    assert (world["overlay_dir"] / "llm-reviewed-truth-overlay.json").read_bytes() \
        == (world["overlay2"] / "llm-reviewed-truth-overlay.json").read_bytes()
    # manifest 唯一随行序变化的字段是 llm_filled_pack 输入文件 SHA
    # （文件字节不同属正确记录），其余必须逐字节一致
    m1 = json.loads((world["overlay_dir"] /
                     "llm-reviewed-truth-overlay-manifest.json").read_text(
                         encoding="utf-8"))
    m2 = json.loads((world["overlay2"] /
                     "llm-reviewed-truth-overlay-manifest.json").read_text(
                         encoding="utf-8"))
    m1["inputs"]["llm_filled_pack"]["sha256"] = None
    m2["inputs"]["llm_filled_pack"]["sha256"] = None
    assert m1 == m2


def test_verify_ok(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world), ALL_CONFIRMED))
    errs = llra.verify(world["overlay_dir"] /
                       "llm-reviewed-truth-overlay-manifest.json")
    assert errs == []


def test_verify_detects_overlay_tamper(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world), ALL_CONFIRMED))
    ov = world["overlay_dir"] / "llm-reviewed-truth-overlay.json"
    data = json.loads(ov.read_text(encoding="utf-8"))
    data["cases"][0]["should_refuse"] = True
    ov.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                  encoding="utf-8")
    errs = llra.verify(world["overlay_dir"] /
                       "llm-reviewed-truth-overlay-manifest.json")
    assert any("sha256" in e for e in errs)


def test_verify_detects_input_drift(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world), ALL_CONFIRMED))
    with world["chunks"].open("a", encoding="utf-8") as f:
        f.write('{"chunk_id": "chunk-9", "source": "s", "text": "t"}\n')
    errs = llra.verify(world["overlay_dir"] /
                       "llm-reviewed-truth-overlay-manifest.json")
    assert any("漂移" in e for e in errs)


# ── reject / needs_followup → issues only，零 overlay ─────────────────

def test_any_reject_yields_issues_only(world: dict[str, Path]) -> None:
    res = _run(world, _fill(_orig_rows(world),
                            {**ALL_CONFIRMED, "h-001": "reject"},
                            notes="证据不支持"))
    assert res["status"] == "issues" and res["errors"] == []
    assert res["blocked"] == ["h-001"]
    # 文件名排序：'-'（0x2D）在 '.'（0x2E）之前，report 在前
    assert _files(world, "out") == ["llm-review-issues-report.md",
                                    "llm-review-issues.jsonl"]
    assert _files(world, "overlay_dir") == []


def test_needs_followup_yields_issues_only(world: dict[str, Path]) -> None:
    res = _run(world, _fill(_orig_rows(world),
                            {**ALL_CONFIRMED, "h-003": "needs_followup"},
                            notes="需补充来源"))
    assert res["status"] == "issues"
    assert res["blocked"] == ["h-003"]
    assert _files(world, "overlay_dir") == []


def test_mixed_blocked_sorted(world: dict[str, Path]) -> None:
    res = _run(world, _fill(_orig_rows(world),
                            {"h-001": "reject", "h-002": "needs_followup",
                             "h-003": "confirmed"}, notes="原因"))
    assert res["status"] == "issues"
    assert res["blocked"] == ["h-001", "h-002"]
    assert res["counts"] == {"confirmed": 1, "reject": 1,
                             "needs_followup": 1}


def test_issues_jsonl_content(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world),
                      {**ALL_CONFIRMED, "h-002": "reject"}, notes="n1"))
    rows = [json.loads(l) for l in
            (world["out"] / "llm-review-issues.jsonl").open(
                encoding="utf-8") if l.strip()]
    assert rows == [{"case_id": "h-002", "decision": "reject",
                     "reviewer": "LLM_ASSISTED_THIRD_PASS", "notes": "n1"}]


def test_issues_report_has_counts_and_disclaimer(
        world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world),
                      {**ALL_CONFIRMED, "h-001": "reject"}, notes="n1"))
    text = (world["out"] / "llm-review-issues-report.md").read_text(
        encoding="utf-8")
    assert "confirmed：2" in text and "reject：1" in text
    assert "needs_followup：0" in text
    assert "不是人工终审" in text and "不能单独解除" in text
    for phrase in llra.FORBIDDEN_PHRASES:
        assert phrase not in text


# ── fail-closed：任何非法状态 → 零输出 ────────────────────────────────

def _assert_failed_zero_output(world: dict[str, Path], res: dict) -> None:
    assert res["status"] == "failed"
    assert res["errors"]
    assert _files(world, "out") == [] and _files(world, "overlay_dir") == []


def test_missing_case_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)[:2]
    _assert_failed_zero_output(world, _run(world, rows))


def test_duplicate_case_id_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)
    _assert_failed_zero_output(world, _run(world, rows + [rows[0]]))


def test_unknown_case_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)
    rows[0]["case_id"] = "h-999"
    _assert_failed_zero_output(world, _run(world, rows))


def test_extra_key_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)
    rows[0]["hack"] = "x"
    _assert_failed_zero_output(world, _run(world, rows))


def test_tampered_query_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)
    rows[0]["query"] = "tampered question?"
    _assert_failed_zero_output(world, _run(world, rows))


def test_tampered_should_refuse_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)
    rows[0]["should_refuse"] = True
    _assert_failed_zero_output(world, _run(world, rows))


def test_tampered_snippet_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)
    rows[0]["evidence"][0]["snippet"] = "Totally different evidence text."
    _assert_failed_zero_output(world, _run(world, rows))


def test_empty_decision_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), {"h-001": "", "h-002": "confirmed",
                                     "h-003": "confirmed"})
    _assert_failed_zero_output(world, _run(world, rows))


def test_invalid_decision_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), {"h-001": "maybe",
                                     "h-002": "confirmed",
                                     "h-003": "confirmed"})
    _assert_failed_zero_output(world, _run(world, rows))


def test_empty_reviewer_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED, reviewer="  ")
    _assert_failed_zero_output(world, _run(world, rows))


def test_non_llm_reviewer_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED, reviewer="henry")
    res = _run(world, rows)
    assert res["status"] == "failed"
    assert any("LLM_ASSISTED_" in e for e in res["errors"])


def test_reject_without_notes_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), {**ALL_CONFIRMED, "h-001": "reject"})
    res = _run(world, rows)
    assert res["status"] == "failed"
    assert any("notes" in e for e in res["errors"])


def test_needs_followup_without_notes_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world),
                 {**ALL_CONFIRMED, "h-003": "needs_followup"})
    res = _run(world, rows)
    assert res["status"] == "failed"
    assert any("notes" in e for e in res["errors"])


def test_missing_chunk_reference_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)
    rows[0]["evidence"][0]["chunk_id"] = "chunk-999"
    _assert_failed_zero_output(world, _run(world, rows))


def test_non_contiguous_snippet_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)
    rows[0]["evidence"][0]["snippet"] = "Alpha component paraphrased."
    _assert_failed_zero_output(world, _run(world, rows))


def test_source_mismatch_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)
    rows[0]["evidence"][0]["source_id"] = "src-b"
    _assert_failed_zero_output(world, _run(world, rows))


def test_llm_manifest_count_mismatch_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)
    _write_jsonl(world["filled"], rows)
    _make_llm_meta(world, rows)
    m = json.loads(world["llm_manifest"].read_text(encoding="utf-8"))
    m["confirmed"] = 2
    world["llm_manifest"].write_text(
        json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    res = _run(world, rows, out="out2", overlay="overlay2", meta=False)
    assert res["status"] == "failed"
    assert any("confirmed" in e for e in res["errors"])
    assert _files(world, "out2") == [] and _files(world, "overlay2") == []


def test_llm_manifest_total_mismatch_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)
    _write_jsonl(world["filled"], rows)
    _make_llm_meta(world, rows)
    m = json.loads(world["llm_manifest"].read_text(encoding="utf-8"))
    m["total_cases"] = 150
    world["llm_manifest"].write_text(
        json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    res = _run(world, rows, out="out2", overlay="overlay2", meta=False)
    assert res["status"] == "failed"
    assert any("total_cases" in e for e in res["errors"])
    assert _files(world, "out2") == [] and _files(world, "overlay2") == []


def test_llm_manifest_non_confirmed_mismatch_fails(
        world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)
    _write_jsonl(world["filled"], rows)
    _make_llm_meta(world, rows)
    m = json.loads(world["llm_manifest"].read_text(encoding="utf-8"))
    m["non_confirmed"] = [{"case_id": "h-999", "decision": "reject",
                           "summary": "s"}]
    world["llm_manifest"].write_text(
        json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    res = _run(world, rows, out="out2", overlay="overlay2", meta=False)
    assert res["status"] == "failed"
    assert any("non_confirmed" in e for e in res["errors"])
    assert _files(world, "out2") == [] and _files(world, "overlay2") == []


def test_llm_report_count_mismatch_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)
    _write_jsonl(world["filled"], rows)
    _make_llm_meta(world, rows)
    world["llm_report"].write_text(
        "# LLM Third-Pass Review Report\n\n- Total cases: 150\n"
        "- Confirmed: 3\n- Reject: 0\n- Needs follow-up: 0\n",
        encoding="utf-8")
    res = _run(world, rows, out="out2", overlay="overlay2", meta=False)
    assert res["status"] == "failed"
    assert any("report" in e.lower() for e in res["errors"])
    assert _files(world, "out2") == [] and _files(world, "overlay2") == []


def test_llm_report_case_list_mismatch_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world), ALL_CONFIRMED)
    _write_jsonl(world["filled"], rows)
    _make_llm_meta(world, rows)
    world["llm_report"].write_text(
        "# LLM Third-Pass Review Report\n\n- Total cases: 3\n"
        "- Confirmed: 2\n- Reject: 1\n- Needs follow-up: 0\n\n"
        "## Non-confirmed cases\n\n- h-001: confirmed\n"
        "- h-002: reject — 原因\n- h-003: confirmed\n",
        encoding="utf-8")
    res = _run(world, rows, out="out2", overlay="overlay2", meta=False)
    assert res["status"] == "failed"
    assert _files(world, "out2") == [] and _files(world, "overlay2") == []


def test_manifest_input_sha_drift_fails(world: dict[str, Path]) -> None:
    with world["chunks"].open("a", encoding="utf-8") as f:
        f.write('{"chunk_id": "chunk-9", "source": "s", "text": "t"}\n')
    _assert_failed_zero_output(
        world, _run(world, _fill(_orig_rows(world), ALL_CONFIRMED)))


def test_blank_pack_tampered_fails(world: dict[str, Path]) -> None:
    blank = world["pack_dir"] / "human-review-pack.jsonl"
    rows = [json.loads(l) for l in blank.open(encoding="utf-8")]
    rows[0]["human_review_decision"] = "confirmed"
    _write_jsonl(blank, rows)
    res = _run(world, _fill(_orig_rows(world), ALL_CONFIRMED))
    assert res["status"] == "failed"
    assert any("空白" in e for e in res["errors"])


# ── 真实语料（离线，不调用 LLM）──────────────────────────────────────

REAL_DIR = hp.ROOT / "evaluation" / "datasets" / "v2" / "human-review"
REAL_LLM_FILLED = REAL_DIR / "human-review-pack.llm-filled.jsonl"


@pytest.mark.skipif(not REAL_LLM_FILLED.exists(),
                    reason="real llm-filled pack absent")
def test_real_corpus_llm_filled_yields_issues(tmp_path: Path) -> None:
    """真实机器填写副本：68 confirmed / 82 reject / 0 needs_followup →
    issues 清单，零 overlay。

    Task 12 已批准重生命前空白 pack；此处用版本化快照重建的修复前
    pack + manifest（与 llm-filled 除三个人工字段外逐行一致）。
    """
    import v2_repair_snapshot_util as snap
    pre = snap.pre_repair_dir(tmp_path)
    res = llra.apply(
        llm_filled_path=REAL_LLM_FILLED,
        pack_path=pre / "human-review-pack.jsonl",
        pack_manifest_path=pre / "human-review-pack-manifest.json",
        llm_manifest_path=REAL_DIR / "llm-third-pass-manifest.json",
        llm_report_path=REAL_DIR / "llm-third-pass-report.md",
        out_dir=tmp_path / "out", overlay_dir=tmp_path / "ov")
    assert res["status"] == "issues" and res["errors"] == []
    assert res["counts"] == {"confirmed": 68, "reject": 82,
                             "needs_followup": 0}
    assert len(res["blocked"]) == 82
    assert res["blocked"] == sorted(res["blocked"])
    assert not (tmp_path / "ov").exists()


@pytest.mark.skipif(not REAL_LLM_FILLED.exists(),
                    reason="real llm-filled pack absent")
def test_real_corpus_all_confirmed_overlay(tmp_path: Path) -> None:
    """真实空白包 + 全部 confirmed 的 LLM 填写副本 → 诊断 overlay +
    verify 通过 + 两次运行逐字节一致（仅写 tmp，不改真实文件）。"""
    blank = [json.loads(l) for l in
             (REAL_DIR / "human-review-pack.jsonl").open(
                 encoding="utf-8") if l.strip()]
    filled = []
    for r in blank:
        c = dict(r)
        c["human_review_decision"] = "confirmed"
        c["human_reviewer"] = "LLM_ASSISTED_THIRD_PASS"
        c["human_review_notes"] = "证据直接支持所有答案点"
        filled.append(c)
    filled_path = tmp_path / "filled.jsonl"
    _write_jsonl(filled_path, filled)
    llm_manifest = tmp_path / "llm-third-pass-manifest.json"
    llm_manifest.write_text(json.dumps({
        "total_cases": 150, "confirmed": 150, "reject": 0,
        "needs_followup": 0, "non_confirmed": [],
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    llm_report = tmp_path / "llm-third-pass-report.md"
    llm_report.write_text(
        "# LLM Third-Pass Review Report\n\n- Total cases: 150\n"
        "- Confirmed: 150\n- Reject: 0\n- Needs follow-up: 0\n\n"
        "## Non-confirmed cases\n\n(none)\n", encoding="utf-8")
    for out, ov in (("o1", "v1"), ("o2", "v2")):
        res = llra.apply(llm_filled_path=filled_path,
                         pack_path=REAL_DIR / "human-review-pack.jsonl",
                         pack_manifest_path=REAL_DIR /
                         "human-review-pack-manifest.json",
                         llm_manifest_path=llm_manifest,
                         llm_report_path=llm_report,
                         out_dir=tmp_path / out, overlay_dir=tmp_path / ov)
        assert res["status"] == "overlay" and res["errors"] == []
        assert res["counts"] == {"confirmed": 150, "reject": 0,
                                 "needs_followup": 0}
    assert (tmp_path / "v1" / "llm-reviewed-truth-overlay.json").read_bytes() \
        == (tmp_path / "v2" / "llm-reviewed-truth-overlay.json").read_bytes()
    errs = llra.verify(tmp_path / "v1" /
                       "llm-reviewed-truth-overlay-manifest.json")
    assert errs == []
