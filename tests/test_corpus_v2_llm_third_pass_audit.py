"""Tests for scripts.corpus_v2_llm_third_pass_audit — read-only root-cause
audit of the third-pass machine-review disagreement structure.

The audit explains the 68 confirmed / 82 reject / 0 needs_followup split
of the LLM third pass by deterministic text-level diagnostics: answer
point verbatim coverage vs evidence snippets / chunk texts, refusal
reasoning shape (keyword-overlap template vs substantive claim), and
cross-document coverage structure.  It adjudicates nothing, changes no
data, and produces no overlay.

Fail-closed: blank & llm-filled must both be 150 rows with identical
case-id sets, identical rows except the three review fields, valid
evidence mappings, and third-pass statistics consistent with the
manifest/report; any structural tamper, unknown key or illegal decision
stops with ZERO output.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

import scripts.corpus_v2_human_review_apply as hra
import scripts.corpus_v2_human_review_pack as hp
import scripts.corpus_v2_llm_review_apply as llra
import scripts.corpus_v2_llm_third_pass_audit as audit

CHUNK_TEXT_A = ("Alpha component is defined here. Full alpha details here. "
                "Extra filler text that extends the chunk beyond the "
                "snippet boundary.")
CHUNK_TEXT_B = ("Beta system reference carries details. More padding text "
                "to make this chunk longer.")

DIAG_KEYS = frozenset({
    "case_id", "language", "query_type", "should_refuse", "query",
    "acceptable_answer_points", "evidence_summary", "third_pass_notes",
    "diagnostic_category", "mechanical_evidence_integrity",
    "answer_point_verbatim_coverage", "refusal_reasoning_type",
    "requires_semantic_adjudication",
})
CATEGORIES = frozenset({
    "answer_point_not_verbatim_in_snippet", "evidence_mapping_or_source_error",
    "cross_document_coverage_gap", "refusal_keyword_overlap_only",
    "refusal_substantive_answerability_claim", "other_or_unclassified",
})


def _case(cid: str, query: str, *, chunk_ids: list[str] | None = None,
          snippets: list[str] | None = None,
          sources: list[str] | None = None,
          should_refuse: bool = False, points: list[str] | None = None,
          query_type: str = "single_fact",
          turn: int = 1, follow_up_to: str | None = None,
          chain_id: str | None = None) -> dict:
    points = [] if points is None else points
    chunk_ids = chunk_ids or []
    snippets = snippets or []
    sources = sources or []
    chunks: list[dict] = []
    for cid_, sn, src in zip(chunk_ids, snippets, sources):
        chunks.append({"chunk_id": cid_, "chunk_text_snippet": sn,
                       "source_id": src, "page": None, "section": "sec"})
    return {
        "id": cid, "query": query, "language": "zh",
        "query_type": query_type,
        "should_refuse": should_refuse,
        "relevance_level": "none" if should_refuse else "chunk",
        "acceptable_answer_points": points,
        "relevant_source_ids": [] if should_refuse else sources,
        "relevant_chunk_ids": [c for c in chunk_ids],
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
    """8-case world covering every diagnostic category."""
    draft = [
        # 答案点逐字 → confirmed
        _case("a-001", "What is the alpha component?",
              chunk_ids=["000000000001_chunk_1"], snippets=["Alpha component is defined "
                                               "here."], sources=["src-a"],
              points=["Alpha component is defined here."], chain_id="a-001"),
        # 答案点非逐字（单源）→ answer_point_not_verbatim_in_snippet
        _case("a-002", "Describe alpha?",
              chunk_ids=["000000000001_chunk_1"], snippets=["Alpha component is defined "
                                               "here."], sources=["src-a"],
              points=["Paraphrased claim about alpha."]),
        # 跨文档且答案点非逐字 → cross_document_coverage_gap
        _case("a-003", "Compare alpha and beta?",
              chunk_ids=["000000000001_chunk_1", "000000000002_chunk_2"],
              snippets=["Alpha component is defined here.",
                        "Beta system reference carries details."],
              sources=["src-a", "src-b"],
              points=["A cross document assertion."],
              query_type="cross_document"),
        # 答案点不在 snippet 但在 chunk 全文 → 证据截取边界现象
        _case("a-004", "Details about alpha?",
              chunk_ids=["000000000001_chunk_1"], snippets=["Alpha component is defined "
                                               "here."], sources=["src-a"],
              points=["Full alpha details here."]),
        # 拒答题 + 模板型 notes，引用 chunk 确实含关键词 → 语义裁决
        _case("r-001", "Is X answerable?", should_refuse=True),
        # 拒答题 + 模板型 notes，引用 chunk 不存在 → 断言机械不成立
        _case("r-002", "Is Y answerable?", should_refuse=True),
        # 拒答题 + 实质可答断言 → refusal_substantive_answerability_claim
        _case("r-003", "Is Z answerable?", should_refuse=True),
        # 答案点逐字却 reject → 理由被机械否定 → other_or_unclassified
        _case("m-001", "What is beta?",
              chunk_ids=["000000000002_chunk_2"], snippets=["Beta system reference "
                                               "carries details."],
              sources=["src-b"],
              points=["Beta system reference carries details."]),
    ]
    chunks = [
        {"chunk_id": "000000000001_chunk_1", "source": "src-a", "text": CHUNK_TEXT_A},
        {"chunk_id": "000000000002_chunk_2", "source": "src-b", "text": CHUNK_TEXT_B},
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
    }
    _write_jsonl(out["draft"], draft)
    _write_jsonl(out["chunks"], chunks)
    out["chunk_manifest"].write_text('{"corpus_version": "x"}\n',
                                     encoding="utf-8")
    out["corpus_manifest"].write_text('{"documents": []}\n', encoding="utf-8")
    _write_jsonl(out["ledger"], [
        {"case_id": "a-001", "action": "corrected", "old_summary": "",
         "new_summary": "", "evidence": [], "rationale": ""},
    ])
    hp.build_pack(draft_path=out["draft"], chunks_path=out["chunks"],
                  chunk_manifest_path=out["chunk_manifest"],
                  corpus_manifest_path=out["corpus_manifest"],
                  ledger_path=out["ledger"], out_dir=out["pack_dir"],
                  expected_total=8)
    return out


def _orig_rows(world: dict[str, Path]) -> list[dict]:
    return [json.loads(l) for l in
            (world["pack_dir"] / "human-review-pack.jsonl").open(
                encoding="utf-8") if l.strip()]


REJECT_NOTES = {
    "a-002": "答案点 'Paraphrased claim about alpha.' 在 evidence snippet "
             "中找不到直接文本支持",
    "a-003": "答案点 'A cross document assertion.' 在 evidence snippet "
             "中找不到直接文本支持",
    "a-004": "答案点 'Full alpha details here.' 在 evidence snippet 中找"
             "不到直接文本支持",
    "r-001": "chunks 中存在相关内容：000000000001_chunk_1 (src-a) 提到 "
             "filler",
    "r-002": "chunks 中存在相关内容：000000000009_chunk_9 (src-x) 提到 "
             "missing",
    "r-003": "该文档明确说明 X 是 Y，因此该 query 实质可答",
    "m-001": "答案点 'Beta system reference carries details.' 在 evidence "
             "snippet 中找不到直接文本支持",
}
CONFIRMED = {"a-001"}


def _fill(rows: list[dict]) -> list[dict]:
    """全部填写：a-001 confirmed，其余 reject（附 notes）。"""
    filled: list[dict] = []
    for r in rows:
        c = dict(r)
        if c["case_id"] in CONFIRMED:
            c["human_review_decision"] = "confirmed"
            c["human_reviewer"] = "LLM_ASSISTED_THIRD_PASS"
            c["human_review_notes"] = "证据直接支持所有答案点"
        else:
            c["human_review_decision"] = "reject"
            c["human_reviewer"] = "LLM_ASSISTED_THIRD_PASS"
            c["human_review_notes"] = REJECT_NOTES[c["case_id"]]
        filled.append(c)
    return filled


def _make_llm_meta(world: dict[str, Path], filled: list[dict]) -> None:
    dec = {r["case_id"]: r["human_review_decision"] for r in filled}
    counts = Counter(dec.values())
    non_confirmed = [{"case_id": cid, "decision": d, "summary": "s"}
                     for cid, d in sorted(dec.items()) if d != "confirmed"]
    world["llm_manifest"].write_text(json.dumps({
        "total_cases": len(filled), "confirmed": counts["confirmed"],
        "reject": counts["reject"],
        "needs_followup": counts["needs_followup"],
        "non_confirmed": non_confirmed,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    lines = ["# LLM Third-Pass Review Report", "",
             f"- Total cases: {len(filled)}",
             f"- Confirmed: {counts['confirmed']}",
             f"- Reject: {counts['reject']}",
             f"- Needs follow-up: {counts['needs_followup']}", "",
             "## Non-confirmed cases", ""]
    for cid in sorted(dec):
        d = dec[cid]
        if d != "confirmed":
            lines.append(f"- {cid}: {d} — 答案点 'x' 在 evidence snippet "
                         "中找不到直接文本支持")
        else:
            lines.append(f"- {cid}: confirmed")
    world["llm_report"].write_text("\n".join(lines) + "\n",
                                   encoding="utf-8")


def _run(world: dict[str, Path], filled: list[dict],
         out: str = "out", meta: bool = True) -> dict:
    _write_jsonl(world["filled"], filled)
    if meta:
        _make_llm_meta(world, filled)
    return audit.audit(blank_path=world["pack_dir"] / "human-review-pack.jsonl",
                       filled_path=world["filled"],
                       llm_manifest_path=world["llm_manifest"],
                       llm_report_path=world["llm_report"],
                       chunks_path=world["chunks"],
                       out_dir=world[out], expected_total=8)


def _out_files(world: dict[str, Path], out: str = "out") -> list[str]:
    d = world[out]
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def _rows(world: dict[str, Path], out: str = "out") -> list[dict]:
    return [json.loads(l) for l in
            (world[out] / "disagreement-cases.jsonl").open(
                encoding="utf-8") if l.strip()]


def _by_id(world: dict[str, Path], out: str = "out") -> dict[str, dict]:
    return {r["case_id"]: r for r in _rows(world, out)}


def _summary(world: dict[str, Path], out: str = "out") -> dict:
    return json.loads((world[out] / "summary.json").read_text(
        encoding="utf-8"))


# ── happy path：三产物 ────────────────────────────────────────────────

def test_audit_produces_three_outputs(world: dict[str, Path]) -> None:
    res = _run(world, _fill(_orig_rows(world)))
    assert res["status"] == "ok" and res["errors"] == []
    assert _out_files(world) == ["disagreement-audit.md",
                                 "disagreement-cases.jsonl",
                                 "manifest.json", "summary.json"]


def test_disagreement_rows_only_rejects_sorted(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world)))
    rows = _rows(world)
    assert len(rows) == 7
    assert [r["case_id"] for r in rows] == sorted(r["case_id"] for r in rows)
    assert len({r["case_id"] for r in rows}) == 7
    for r in rows:
        assert set(r) == DIAG_KEYS
        assert isinstance(r["should_refuse"], bool)


def test_diagnostic_fields_enum(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world)))
    for r in _rows(world):
        assert r["diagnostic_category"] in CATEGORIES
        assert r["mechanical_evidence_integrity"] in ("ok", "broken")
        assert r["answer_point_verbatim_coverage"] in (
            "all_in_snippet", "partial_in_snippet", "none_in_snippet",
            "no_evidence")
        assert r["refusal_reasoning_type"] in (
            "not_applicable", "keyword_overlap_only",
            "substantive_answerability_claim", "other_or_unverifiable")
        assert isinstance(r["requires_semantic_adjudication"], bool)


def test_category_assignment_per_case(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world)))
    by_id = _by_id(world)
    assert by_id["a-002"]["diagnostic_category"] == \
        "answer_point_not_verbatim_in_snippet"
    assert by_id["a-003"]["diagnostic_category"] == \
        "cross_document_coverage_gap"
    assert by_id["a-004"]["diagnostic_category"] == \
        "answer_point_not_verbatim_in_snippet"
    assert by_id["r-001"]["diagnostic_category"] == \
        "refusal_keyword_overlap_only"
    assert by_id["r-002"]["diagnostic_category"] == \
        "refusal_keyword_overlap_only"
    assert by_id["r-003"]["diagnostic_category"] == \
        "refusal_substantive_answerability_claim"
    assert by_id["m-001"]["diagnostic_category"] == "other_or_unclassified"


def test_verbatim_coverage_values(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world)))
    by_id = _by_id(world)
    assert "a-001" not in by_id  # confirmed 不进 disagreement
    assert by_id["a-002"]["answer_point_verbatim_coverage"] == \
        "none_in_snippet"
    assert by_id["a-004"]["answer_point_verbatim_coverage"] == \
        "none_in_snippet"
    assert by_id["m-001"]["answer_point_verbatim_coverage"] == \
        "all_in_snippet"
    assert by_id["r-001"]["answer_point_verbatim_coverage"] == "no_evidence"


def test_chunk_text_verbatim_marking_in_evidence_summary(
        world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world)))
    ev = _by_id(world)["a-004"]["evidence_summary"]
    assert len(ev) == 1
    assert ev[0]["chunk_text_verbatim"] is True  # 截取边界：点在全文中
    ev2 = _by_id(world)["a-002"]["evidence_summary"]
    assert ev2[0]["chunk_text_verbatim"] is False


def test_refusal_reasoning_type(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world)))
    by_id = _by_id(world)
    assert by_id["r-001"]["refusal_reasoning_type"] == "keyword_overlap_only"
    assert by_id["r-002"]["refusal_reasoning_type"] == "keyword_overlap_only"
    assert by_id["r-003"]["refusal_reasoning_type"] == \
        "substantive_answerability_claim"
    assert by_id["a-002"]["refusal_reasoning_type"] == "not_applicable"


def test_semantic_adjudication_flag(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world)))
    by_id = _by_id(world)
    # 非逐字 → 语义裁决
    assert by_id["a-002"]["requires_semantic_adjudication"] is True
    assert by_id["a-003"]["requires_semantic_adjudication"] is True
    assert by_id["a-004"]["requires_semantic_adjudication"] is True
    # 关键词重合成立 → 语义裁决
    assert by_id["r-001"]["requires_semantic_adjudication"] is True
    # 关键词引用 chunk 不存在 → 断言机械不成立，无需语义
    assert by_id["r-002"]["requires_semantic_adjudication"] is False
    # 实质可答断言 → 语义裁决
    assert by_id["r-003"]["requires_semantic_adjudication"] is True
    # 答案点逐字却 reject → 理由被机械否定
    assert by_id["m-001"]["requires_semantic_adjudication"] is False


# ── summary.json ──────────────────────────────────────────────────────

def test_summary_recomputes_distribution(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world)))
    s = _summary(world)
    assert s["total_cases"] == 8
    assert s["decision_counts"] == {"confirmed": 1, "reject": 7,
                                    "needs_followup": 0}
    assert s["reject_breakdown"]["by_should_refuse"]["answerable"] == \
        {"total": 5, "reject": 4, "reject_rate": 0.8}
    assert s["reject_breakdown"]["by_should_refuse"]["refusal"] == \
        {"total": 3, "reject": 3, "reject_rate": 1.0}
    assert s["reject_breakdown"]["refusal_rows"] == {"total": 3, "reject": 3,
                                                     "reject_rate": 1.0}
    assert s["reject_breakdown"]["cross_document_rows"] == \
        {"total": 1, "reject": 1, "reject_rate": 1.0}
    assert s["diagnostic_summary"]["by_category"] == {
        "answer_point_not_verbatim_in_snippet": 2,
        "cross_document_coverage_gap": 1,
        "refusal_keyword_overlap_only": 2,
        "refusal_substantive_answerability_claim": 1,
        "other_or_unclassified": 1,
        "evidence_mapping_or_source_error": 0,
    }
    assert s["diagnostic_summary"]["semantic_adjudication_required"] == 5
    assert s["diagnostic_summary"]["mechanical_only_adjudication"] == 2
    assert s["diagnostic_summary"]["snippet_boundary_cases"] == 1


def test_summary_lineage_and_conclusion(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world)))
    s = _summary(world)
    assert "SHA" in s["lineage_limitation"]
    assert "不判定" in s["conclusion"] and "overlay" in s["conclusion"]


# ── disagreement-audit.md ─────────────────────────────────────────────

def test_audit_md_sections_and_purity(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world)))
    md = (world["out"] / "disagreement-audit.md").read_text(encoding="utf-8")
    for section in ("复算分布", "拒答题与跨文档题", "诊断类别分布",
                    "谱系限制", "结论"):
        assert section in md
    assert "不判定" in md and "不生成 overlay" in md
    for word in ("dev", "holdout", "split"):
        assert word not in md.lower()


# ── manifest.json ─────────────────────────────────────────────────────

def test_manifest_records_chain_and_counts(world: dict[str, Path]) -> None:
    _run(world, _fill(_orig_rows(world)))
    m = json.loads((world["out"] / "manifest.json").read_text(
        encoding="utf-8"))
    assert m["decision_counts"] == {"confirmed": 1, "reject": 7,
                                    "needs_followup": 0}
    assert m["n_reject_cases"] == 7
    for key in ("blank_pack", "llm_filled_pack", "llm_third_pass_manifest",
                "llm_third_pass_report", "chunks"):
        info = m["inputs"][key]
        assert "path" in info and "sha256" in info
        assert hra._sha256_file(Path(info["path"])) == info["sha256"]
    for name in ("disagreement-cases.jsonl", "summary.json",
                 "disagreement-audit.md"):
        assert "sha256" in m["outputs"][name]
    text = json.dumps(m, ensure_ascii=False)
    for word in ("split", "holdout", "dev", "accuracy", "score"):
        assert word not in text.lower()


# ── 确定性 ───────────────────────────────────────────────────────────

def test_audit_is_deterministic(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world))
    _run(world, rows, out="out")
    _run(world, rows, out="out2")
    for name in ("disagreement-cases.jsonl", "summary.json",
                 "disagreement-audit.md", "manifest.json"):
        assert (world["out"] / name).read_bytes() == \
            (world["out2"] / name).read_bytes()


# ── fail-closed：零输出 ──────────────────────────────────────────────

def _assert_failed_zero_output(world: dict[str, Path], res: dict) -> None:
    assert res["status"] == "failed"
    assert res["errors"]
    assert _out_files(world) == []


def test_missing_row_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world))[:7]
    _assert_failed_zero_output(world, _run(world, rows))


def test_unknown_case_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world))
    rows[0]["case_id"] = "x-999"
    _assert_failed_zero_output(world, _run(world, rows))


def test_tampered_query_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world))
    rows[0]["query"] = "tampered"
    _assert_failed_zero_output(world, _run(world, rows))


def test_illegal_decision_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world))
    rows[0]["human_review_decision"] = "maybe"
    _assert_failed_zero_output(world, _run(world, rows))


def test_non_llm_reviewer_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world))
    rows[0]["human_reviewer"] = "henry"
    _assert_failed_zero_output(world, _run(world, rows))


def test_reject_without_notes_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world))
    rows[1]["human_review_notes"] = ""  # a-002 是 reject 行
    _assert_failed_zero_output(world, _run(world, rows))


def test_broken_evidence_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world))
    rows[1]["evidence"][0]["chunk_id"] = "chunk-999"
    _assert_failed_zero_output(world, _run(world, rows))


def test_llm_manifest_stats_mismatch_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world))
    _write_jsonl(world["filled"], rows)
    _make_llm_meta(world, rows)
    m = json.loads(world["llm_manifest"].read_text(encoding="utf-8"))
    m["reject"] = 6
    world["llm_manifest"].write_text(
        json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    res = _run(world, rows, out="out2", meta=False)
    assert res["status"] == "failed"
    assert _out_files(world, "out2") == []


def test_llm_report_stats_mismatch_fails(world: dict[str, Path]) -> None:
    rows = _fill(_orig_rows(world))
    _write_jsonl(world["filled"], rows)
    _make_llm_meta(world, rows)
    world["llm_report"].write_text(
        "# LLM Third-Pass Review Report\n\n- Total cases: 8\n"
        "- Confirmed: 1\n- Reject: 6\n- Needs follow-up: 0\n\n"
        "## Non-confirmed cases\n\n(none)\n", encoding="utf-8")
    res = _run(world, rows, out="out2", meta=False)
    assert res["status"] == "failed"
    assert _out_files(world, "out2") == []


def test_blank_human_fields_filled_fails(world: dict[str, Path]) -> None:
    blank = world["pack_dir"] / "human-review-pack.jsonl"
    rows = [json.loads(l) for l in blank.open(encoding="utf-8")]
    rows[0]["human_review_decision"] = "confirmed"
    _write_jsonl(blank, rows)
    res = _run(world, _fill(_orig_rows(world)))
    assert res["status"] == "failed"
    assert any("空白" in e for e in res["errors"])


# ── 纯函数级分类 ─────────────────────────────────────────────────────

def test_classify_broken_evidence_first(world: dict[str, Path]) -> None:
    assert audit._classify(should_refuse=False, integrity="broken",
                           coverage="none_in_snippet",
                           refusal_type="not_applicable", cross_doc=False) \
        == "evidence_mapping_or_source_error"


def test_classify_refusal_precedence(world: dict[str, Path]) -> None:
    assert audit._classify(should_refuse=True, integrity="ok",
                           coverage="no_evidence",
                           refusal_type="keyword_overlap_only",
                           cross_doc=False) == "refusal_keyword_overlap_only"
    assert audit._classify(should_refuse=True, integrity="ok",
                           coverage="no_evidence",
                           refusal_type="substantive_answerability_claim",
                           cross_doc=False) == \
        "refusal_substantive_answerability_claim"


def test_verbatim_coverage_partial(world: dict[str, Path]) -> None:
    cov = audit._verbatim_coverage(
        ["Alpha component is defined here.", "not in snippet"],
        ["Alpha component is defined here."])
    assert cov == "partial_in_snippet"


# ── 真实语料（离线，不调用 LLM）──────────────────────────────────────

REAL_DIR = hp.ROOT / "evaluation" / "datasets" / "v2" / "human-review"
REAL_LLM_FILLED = REAL_DIR / "human-review-pack.llm-filled.jsonl"


@pytest.mark.skipif(not REAL_LLM_FILLED.exists(),
                    reason="real llm-filled pack absent")
def test_real_corpus_audit_profile(tmp_path: Path) -> None:
    """真实语料：68/82/0 复算、82 条 reject 全诊断、确定性。"""
    import v2_repair_snapshot_util as snap
    out = tmp_path / "out"
    res = audit.audit(
        blank_path=snap.pre_repair_pack(tmp_path),
        filled_path=REAL_LLM_FILLED,
        llm_manifest_path=REAL_DIR / "llm-third-pass-manifest.json",
        llm_report_path=REAL_DIR / "llm-third-pass-report.md",
        chunks_path=hp.ROOT / "data" / "v2-corpus" / "chunks" /
        "chunks.jsonl",
        out_dir=out)
    assert res["status"] == "ok" and res["errors"] == []
    assert res["counts"] == {"confirmed": 68, "reject": 82,
                             "needs_followup": 0}
    rows = [json.loads(l) for l in
            (out / "disagreement-cases.jsonl").open(encoding="utf-8")]
    assert len(rows) == 82
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    cat = s["diagnostic_summary"]["by_category"]
    assert sum(cat.values()) == 82
    # 拒答题 reject 全部为关键词模板型（探索确认：15 条）
    assert cat["refusal_keyword_overlap_only"] == 15
    assert cat["evidence_mapping_or_source_error"] == 0
    # 答案点非逐字断言全部机械成立；3 条为证据截取边界（点在 chunk 全文）
    assert cat["answer_point_not_verbatim_in_snippet"] + \
        cat["cross_document_coverage_gap"] == 67
    assert s["diagnostic_summary"]["snippet_boundary_cases"] == 3
    # 文本事实不裁决对错：82 条全部需要语义裁决
    assert s["diagnostic_summary"]["semantic_adjudication_required"] == 82
    assert s["diagnostic_summary"]["mechanical_only_adjudication"] == 0
    # 拒答题与跨文档题
    assert s["reject_breakdown"]["refusal_rows"] == \
        {"total": 31, "reject": 15, "reject_rate": 0.4839}
    assert s["reject_breakdown"]["cross_document_rows"]["total"] == 30
    assert s["reject_breakdown"]["cross_document_rows"]["reject"] == 28


@pytest.mark.skipif(not REAL_LLM_FILLED.exists(),
                    reason="real llm-filled pack absent")
def test_real_corpus_audit_deterministic(tmp_path: Path) -> None:
    import v2_repair_snapshot_util as snap
    kwargs = dict(
        blank_path=snap.pre_repair_pack(tmp_path),
        filled_path=REAL_LLM_FILLED,
        llm_manifest_path=REAL_DIR / "llm-third-pass-manifest.json",
        llm_report_path=REAL_DIR / "llm-third-pass-report.md",
        chunks_path=hp.ROOT / "data" / "v2-corpus" / "chunks" /
        "chunks.jsonl")
    audit.audit(out_dir=tmp_path / "o1", **kwargs)
    audit.audit(out_dir=tmp_path / "o2", **kwargs)
    for name in ("disagreement-cases.jsonl", "summary.json",
                 "disagreement-audit.md", "manifest.json"):
        assert (tmp_path / "o1" / name).read_bytes() == \
            (tmp_path / "o2" / name).read_bytes()
