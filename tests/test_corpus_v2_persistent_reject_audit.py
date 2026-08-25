"""Tests for scripts.corpus_v2_persistent_reject_audit — deterministic,
offline repairability audit of the 5 persistently-rejected v2 cases
(en-052 / en-055 / mixed-016 / mixed-026 / multi-014).

What the audit does, per case and per acceptable answer point:

- reprints the current evidence (chunk/source/snippet) and the v4 Pro
  per-point support assessment;
- searches the full text of the case's relevant sources for verbatim
  candidate spans (normalized NFKC + folded whitespace + ascii-lower),
  reporting chunk_id / source_id / char range / minimal verbatim text;
- classifies each point: exact_local_evidence_available |
  only_paraphrase_or_partial_evidence | no_local_evidence_found, with a
  proposed action: add_exact_evidence | narrow_answer_point |
  remove_unsupported_answer_point | manual_semantic_adjudication_required.

Rules (mechanical, deterministic, no LLM):

- search is limited to relevant_source_ids; matches in other documents are
  flagged out_of_scope_only and never used as repair basis;
- a span covering >= COVERAGE_EXACT of the normalized answer point is
  "exact"; otherwise any span >= MIN_SPAN_LEN is "partial"; none is "none";
- narrow_answer_point is only emitted when at least one full clause of the
  answer point appears verbatim (the narrowed point would be directly
  supported);
- add_exact_evidence / narrow_answer_point are never emitted without such a
  verbatim candidate; when the span is already inside the current evidence
  snippet, action becomes manual (evidence_already_present);
- when the answer point language mismatches the source documents
  (CJK vs non-CJK), verbatim matching is inapplicable and the point is
  routed to manual_semantic_adjudication_required with language_mismatch;
- points already supported by v4 Pro (support_level != unsupported) are not
  in the repair scope: action manual with reason point_already_supported.

Fail-closed input validation: merged rows must equal the selection-manifest
mapping, the merged reject set must equal the target case set, the pack must
have the expected row count and contain every target case, every evidence
chunk_id must exist, chunk ids must be unique.

This audit is evidence-repairability analysis only: it is not automatic
repair, not human review, and not a v2.1 gate decision.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.corpus_v2_persistent_reject_audit as pra

ROOT = Path(__file__).resolve().parents[1]

# ── synthetic world ──────────────────────────────────────────────────

CHUNK_A0 = "000000000001_chunk_0"
CHUNK_A1 = "000000000001_chunk_1"
CHUNK_B0 = "000000000002_chunk_0"
A0_TEXT = "The widget is red and it costs five dollars."
A1_TEXT = "The gadget rules guarantee widget safety."
B0_TEXT = "The widget is expensive in this other document."
CHUNKS = [
    {"chunk_id": CHUNK_A0, "index": 0, "source": "src-a", "text": A0_TEXT},
    {"chunk_id": CHUNK_A1, "index": 1, "source": "src-a", "text": A1_TEXT},
    {"chunk_id": CHUNK_B0, "index": 0, "source": "src-b", "text": B0_TEXT},
]
SRC_A = ["src-a"]


def _ev(chunk_id: str, snippet: str, source_id: str = "src-a") -> dict:
    return {"source_id": source_id, "chunk_id": chunk_id,
            "snippet": snippet, "section": "s1"}


def _pack(case_id: str, points: list[str], evidence: list[dict],
          sources: list[str] | None = None) -> dict:
    return {
        "case_id": case_id, "query": "q", "language": "en",
        "query_type": "single_fact", "previous_turns": [],
        "should_refuse": False,
        "relevance_level": "chunk" if evidence else "none",
        "acceptable_answer_points": points,
        "relevant_source_ids": sources or sorted({e["source_id"]
                                                   for e in evidence}),
        "evidence": evidence,
        "human_review_decision": "", "human_reviewer": "",
        "human_review_notes": "",
    }


def _support(idx: int, level: str, chunk_id: str = "", excerpt: str = "") -> dict:
    return {"answer_point_index": idx, "support_level": level,
            "chunk_id": chunk_id, "excerpt": excerpt}


def _merged_row(index: int, verdict: str,
                supports: list[dict] | None = None) -> dict:
    return {"index": index, "semantic_verdict": verdict,
            "verdict_rationale": "synthetic rationale",
            "answer_point_supports": supports or [],
            "refusal_assessment": None, "refusal_evidence": [],
            "model": "deepseek-v4-pro", "source": "original",
            "parse_retries": 0, "retries_used": 0, "recheck_attempts": 0}


# 8 行 merged：7 个 target reject + 1 个 control confirmed
TARGET = ["t-001", "t-002", "t-003", "t-005", "t-006", "t-007", "t-008"]
CASES = [
    # t-001：ap0 已支持（v4 Pro direct_snippet）；ap1 全文有精确原文
    _pack("t-001", ["widget is red", "gadget rules guarantee widget safety"],
          [_ev(CHUNK_A0, A0_TEXT)]),
    # t-002：部分逐字（gadget rules / widget safety），无完整子句
    _pack("t-002", ["gadget rules and widget safety"],
          [_ev(CHUNK_A1, "The gadget rules")]),
    # t-003：范围内无证据（"the red gadget" 不在 src-a），范围外（src-b）
    # 有 "is expensive" 相似内容
    _pack("t-003", ["the red gadget is expensive"],
          [_ev(CHUNK_A1, "The gadget rules")]),
    # t-004：control（merged confirmed，不审计）
    _pack("t-004", ["widget is red"], [_ev(CHUNK_A0, A0_TEXT)]),
    # t-005：中文答案点 vs 英文源文档 → language mismatch
    _pack("t-005", ["小部件是红色的"], [_ev(CHUNK_A0, A0_TEXT)]),
    # t-006：两个子句，其一逐字完整出现 → narrow 可行
    _pack("t-006", ["widget is red, gadget rules are strict"],
          [_ev(CHUNK_A1, "The gadget rules")]),
    # t-007：相关源内无任何证据
    _pack("t-007", ["gadgets are blue"], [_ev(CHUNK_A0, A0_TEXT)]),
    # t-008：有精确原文但已在当前 evidence snippet 内
    _pack("t-008", ["widget is red"],
          [_ev(CHUNK_A0, "The widget is red")]),
]
MERGED = [
    _merged_row(1, "reject", [_support(0, "direct_snippet", CHUNK_A0,
                                       "The widget is red"),
                              _support(1, "unsupported")]),
    _merged_row(2, "reject", [_support(0, "unsupported")]),
    _merged_row(3, "reject", [_support(0, "unsupported")]),
    _merged_row(4, "confirmed", [_support(0, "direct_snippet", CHUNK_A0,
                                          "The widget is red")]),
    _merged_row(5, "reject", [_support(0, "unsupported")]),
    _merged_row(6, "reject", [_support(0, "unsupported")]),
    _merged_row(7, "reject", [_support(0, "unsupported")]),
    _merged_row(8, "reject", [_support(0, "unsupported")]),
]
PACK_ROWS = len(CASES)  # 8


def _sel_manifest(rows: list[dict]) -> dict:
    mapping = [{"index": r["index"], "case_id": c["case_id"],
                "role": "control" if r["semantic_verdict"] == "confirmed"
                else "disputed"}
               for r, c in zip(rows, CASES)]
    disputed = [e["case_id"] for e in mapping if e["role"] == "disputed"]
    controls = [e["case_id"] for e in mapping if e["role"] == "control"]
    return {"total_cases": len(rows), "control_count": len(controls),
            "disputed_count": len(disputed), "controls": controls,
            "disputed": disputed, "selection_algorithm": "synthetic",
            "control_salt": "salt:", "mapping": mapping, "note": "synthetic"}


def _write_fixture(tmp_path: Path) -> Path:
    """写入合成 4 个输入文件，返回输入目录。"""
    inp = tmp_path / "in"
    inp.mkdir(exist_ok=True)
    (inp / "chunks.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in CHUNKS) + "\n",
        encoding="utf-8")
    (inp / "merged-adjudications.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in MERGED) + "\n",
        encoding="utf-8")
    (inp / "selection-manifest.json").write_text(
        json.dumps(_sel_manifest(MERGED), ensure_ascii=False, indent=1),
        encoding="utf-8")
    (inp / "human-review-pack.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in CASES) + "\n",
        encoding="utf-8")
    return inp


def _run(tmp_path: Path, *, target: list[str] | None = None,
         expected_rows: int | None = None) -> dict:
    inp = _write_fixture(tmp_path)
    out = tmp_path / "out"
    return pra.run(merged_path=inp / "merged-adjudications.jsonl",
                   sel_path=inp / "selection-manifest.json",
                   pack_path=inp / "human-review-pack.jsonl",
                   chunks_path=inp / "chunks.jsonl",
                   out_dir=out,
                   target_case_ids=target if target is not None else TARGET,
                   expected_pack_rows=expected_rows
                   if expected_rows is not None else PACK_ROWS)


def _cases_jsonl(out_dir: Path) -> list[dict]:
    return [json.loads(l) for l in
            (out_dir / "persistent-reject-cases.jsonl")
            .open(encoding="utf-8")]


def _points_by_id(out_dir: Path) -> dict[str, list[dict]]:
    return {c["case_id"]: c["answer_points"] for c in _cases_jsonl(out_dir)}


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.open(encoding="utf-8")]


# ── 纯函数：归一化 / 子句 / span 收集 ────────────────────────────────

class TestNormalize:
    def test_norm_folds_whitespace_case_and_returns_offsets(self):
        norm, offs = pra._norm_with_map("A  B\tC\na")
        # 原始: A(0) ' '(1) ' '(2) B(3) '\t'(4) C(5) '\n'(6) a(7)
        assert norm == "a b c a"
        assert offs == [0, 1, 3, 4, 5, 6, 7]

    def test_norm_nfkc_fullwidth(self):
        norm, _ = pra._norm_with_map("＆ 运算符（借用/引用）")
        assert norm == "& 运算符(借用/引用)"

    def test_norm_strips_leading_trailing_space(self):
        norm, _ = pra._norm_with_map("  hello world  ")
        assert norm == "hello world"

    def test_char_range_maps_back_to_original(self):
        norm, offs = pra._norm_with_map(A0_TEXT)
        assert norm == "the widget is red and it costs five dollars."
        assert norm.find("widget is red") == 4
        assert A0_TEXT[offs[4]:offs[4 + len("widget is red")]] == \
            "widget is red"


class TestClauses:
    def test_clauses_split_on_punctuation_and_filter_short(self):
        assert pra._clauses("widget is red, gadget rules are strict") == \
            ["widget is red", "gadget rules are strict"]

    def test_clauses_drop_short_pieces(self):
        assert pra._clauses("a b, c d") == []

    def test_clauses_keep_single_long_clause(self):
        assert pra._clauses("gadget rules and widget safety") == \
            ["gadget rules and widget safety"]


class TestCollectSpans:
    def test_full_verbatim_span(self):
        ap = pra._norm_with_map("widget is red")[0]
        ch = pra._norm_with_map(A0_TEXT)[0]
        spans = pra._collect_spans(ap, ch, pra.MIN_SPAN_LEN)
        assert spans == [(0, len(ap), 4, 4 + len(ap))]

    def test_two_disjoint_spans(self):
        ap = pra._norm_with_map("gadget rules and widget safety")[0]
        ch = pra._norm_with_map(A1_TEXT)[0]
        spans = pra._collect_spans(ap, ch, pra.MIN_SPAN_LEN)
        # "gadget rules"（12）+ "widget safety"（13）
        assert [ap[a:e] for a, e, _, _ in spans] == \
            ["gadget rules", "widget safety"]

    def test_no_span_below_min_len(self):
        ap = pra._norm_with_map("blue")[0]
        ch = pra._norm_with_map(A1_TEXT)[0]
        assert pra._collect_spans(ap, ch, pra.MIN_SPAN_LEN) == []


class TestLanguageMismatch:
    def test_cjk_answer_against_english_source(self):
        assert pra._language_mismatch("小部件是红色的", SRC_A, CHUNKS) is True

    def test_english_answer_against_cjk_source(self):
        zh_chunks = [{"chunk_id": "x", "index": 0, "source": "zh-src",
                      "text": "中文文档内容。"}]
        assert pra._language_mismatch("widget is red", ["zh-src"],
                                      zh_chunks) is True

    def test_matching_language_is_not_mismatch(self):
        assert pra._language_mismatch("widget is red", SRC_A, CHUNKS) is False

    def test_cjk_answer_against_cjk_source(self):
        zh_chunks = [{"chunk_id": "x", "index": 0, "source": "zh-src",
                      "text": "中文文档内容。"}]
        assert pra._language_mismatch("小部件是红色的", ["zh-src"],
                                      zh_chunks) is False


# ── 纯函数：答案点分类 ───────────────────────────────────────────────

def _span(ap_norm: str, a: int, e1: int, text: str) -> dict:
    """构造一个 in-scope span dict（ap 空间 [a,e1)，span_text 为最短必要原文）。"""
    return {"ap_start": a, "ap_end": e1, "chunk_start": 0,
            "chunk_end": len(text), "span_text": text, "in_scope": True}


class TestClassify:
    def test_exact_unsupported_gets_add_exact_evidence(self):
        ap = "widget is red"
        n, _ = pra._norm_with_map(ap)
        spans = [_span(n, 0, len(n), "widget is red")]
        r = pra.classify_answer_point(ap, spans, [], False, "unsupported", [])
        assert r["repair_feasibility"] == "exact_local_evidence_available"
        assert r["proposed_action"] == "add_exact_evidence"
        assert r["max_cover"] == pytest.approx(1.0)

    def test_exact_but_already_in_evidence_goes_manual(self):
        ap = "widget is red"
        n, _ = pra._norm_with_map(ap)
        spans = [_span(n, 0, len(n), "widget is red")]
        r = pra.classify_answer_point(ap, spans, [], False, "unsupported",
                                      ["the widget is red"])
        assert r["proposed_action"] == "manual_semantic_adjudication_required"
        assert r["evidence_already_present"] is True

    def test_partial_without_clause_goes_manual(self):
        ap = "gadget rules and widget safety"
        n, _ = pra._norm_with_map(ap)
        spans = [_span(n, 0, 12, "gadget rules"),
                 _span(n, 16, 29, "widget safety")]
        r = pra.classify_answer_point(ap, spans, [], False, "unsupported", [])
        assert r["repair_feasibility"] == "only_paraphrase_or_partial_evidence"
        assert r["proposed_action"] == "manual_semantic_adjudication_required"

    def test_partial_with_full_clause_goes_narrow(self):
        ap = "widget is red, gadget rules are strict"
        n, _ = pra._norm_with_map(ap)
        spans = [_span(n, 0, 13, "widget is red")]
        r = pra.classify_answer_point(ap, spans, [], False, "unsupported", [])
        assert r["repair_feasibility"] == "only_paraphrase_or_partial_evidence"
        assert r["proposed_action"] == "narrow_answer_point"
        assert r["clause_hit"] is True

    def test_none_with_out_of_scope_goes_manual(self):
        ap = "the red widget is expensive"
        n, _ = pra._norm_with_map(ap)
        out = [_span(n, 0, len(n), "widget is expensive")]
        r = pra.classify_answer_point(ap, [], out, False, "unsupported", [])
        assert r["repair_feasibility"] == "no_local_evidence_found"
        assert r["proposed_action"] == "manual_semantic_adjudication_required"
        assert r["out_of_scope_only"] is True

    def test_none_without_anything_goes_remove(self):
        ap = "gadgets are blue"
        r = pra.classify_answer_point(ap, [], [], False, "unsupported", [])
        assert r["repair_feasibility"] == "no_local_evidence_found"
        assert r["proposed_action"] == "remove_unsupported_answer_point"

    def test_language_mismatch_goes_manual(self):
        ap = "小部件是红色的"
        r = pra.classify_answer_point(ap, [], [], True, "unsupported", [])
        assert r["proposed_action"] == "manual_semantic_adjudication_required"
        assert r["language_mismatch"] is True

    def test_already_supported_point_is_not_repair_scope(self):
        ap = "widget is red"
        n, _ = pra._norm_with_map(ap)
        spans = [_span(n, 0, len(n), "widget is red")]
        r = pra.classify_answer_point(ap, spans, [], False,
                                      "direct_snippet", [])
        assert r["proposed_action"] == "manual_semantic_adjudication_required"
        assert r["point_already_supported"] is True

    def test_classify_is_pure(self):
        ap = "widget is red"
        spans = []
        r1 = pra.classify_answer_point(ap, spans, [], False,
                                       "unsupported", [])
        before = json.dumps([ap, spans], ensure_ascii=False, sort_keys=True)
        pra.classify_answer_point(ap, spans, [], False, "unsupported", [])
        assert json.dumps([ap, spans], ensure_ascii=False, sort_keys=True) \
            == before
        assert r1["proposed_action"] == "remove_unsupported_answer_point"


# ── 集成：审计运行 ───────────────────────────────────────────────────

class TestAuditRun:
    def test_writes_five_outputs_with_expected_rows(self, tmp_path):
        summary = _run(tmp_path)
        out = tmp_path / "out"
        assert set(summary["outputs"]) == set(pra.OUTPUT_FILES)
        cases = _cases_jsonl(out)
        assert [c["case_id"] for c in cases] == TARGET
        assert len(cases) == 7
        assert summary["n_answer_points"] == 8
        assert summary["n_unsupported_points"] == 7

    def test_exact_add_evidence_classification(self, tmp_path):
        summary = _run(tmp_path)
        pts = _points_by_id(tmp_path / "out")
        ap1 = [p for p in pts["t-001"]
               if p["answer_point_index"] == 1][0]
        assert ap1["repair_feasibility"] == "exact_local_evidence_available"
        assert ap1["proposed_action"] == "add_exact_evidence"
        # 候选 span 必须带 chunk/source/字符范围/最短必要原文
        spans = [s for s in _read_jsonl(tmp_path / "out"
                                        / "candidate-evidence-spans.jsonl")
                 if s["case_id"] == "t-001" and s["answer_point_index"] == 1
                 and s["norm_match_len"] == 36]
        assert len(spans) == 1
        s = spans[0]
        assert s["chunk_id"] == CHUNK_A1 and s["source_id"] == "src-a"
        assert s["span_text"] == "gadget rules guarantee widget safety"
        assert s["char_start"] >= 0 and s["char_end"] > s["char_start"]
        assert A1_TEXT[s["char_start"]:s["char_end"]] == s["span_text"]

    def test_already_supported_point_not_in_repair_scope(self, tmp_path):
        _run(tmp_path)
        pts = _points_by_id(tmp_path / "out")
        ap0 = [p for p in pts["t-001"] if p["answer_point_index"] == 0][0]
        assert ap0["current_support"]["support_level"] == "direct_snippet"
        assert ap0["proposed_action"] == "manual_semantic_adjudication_required"
        assert ap0["point_already_supported"] is True

    def test_evidence_already_present_goes_manual(self, tmp_path):
        _run(tmp_path)
        pts = _points_by_id(tmp_path / "out")
        ap0 = pts["t-008"][0]
        assert ap0["proposed_action"] == "manual_semantic_adjudication_required"
        assert ap0["evidence_already_present"] is True

    def test_language_mismatch_case(self, tmp_path):
        _run(tmp_path)
        pts = _points_by_id(tmp_path / "out")
        ap0 = pts["t-005"][0]
        assert ap0["language_mismatch"] is True
        assert ap0["proposed_action"] == "manual_semantic_adjudication_required"
        assert ap0["repair_feasibility"] == "no_local_evidence_found"

    def test_narrow_answer_point_case(self, tmp_path):
        _run(tmp_path)
        pts = _points_by_id(tmp_path / "out")
        ap0 = pts["t-006"][0]
        assert ap0["proposed_action"] == "narrow_answer_point"
        assert ap0["clause_hit"] is True

    def test_out_of_scope_only_case(self, tmp_path):
        _run(tmp_path)
        pts = _points_by_id(tmp_path / "out")
        ap0 = pts["t-003"][0]
        assert ap0["out_of_scope_only"] is True
        assert ap0["proposed_action"] == "manual_semantic_adjudication_required"
        spans = [s for s in _read_jsonl(tmp_path / "out"
                                        / "candidate-evidence-spans.jsonl")
                 if s["case_id"] == "t-003"]
        assert spans and all(s["out_of_scope_only"] is True for s in spans)

    def test_remove_unsupported_case(self, tmp_path):
        _run(tmp_path)
        pts = _points_by_id(tmp_path / "out")
        ap0 = pts["t-007"][0]
        assert ap0["proposed_action"] == "remove_unsupported_answer_point"
        assert ap0["matches"]["in_scope"] == 0

    def test_per_point_current_support_and_third_pass_fields(self, tmp_path):
        _run(tmp_path)
        cases = _cases_jsonl(tmp_path / "out")
        t1 = next(c for c in cases if c["case_id"] == "t-001")
        # 当前 evidence 的 chunk/source/snippet 输出
        assert t1["current_evidence"][0]["chunk_id"] == CHUNK_A0
        assert t1["current_evidence"][0]["source_id"] == "src-a"
        # v4 Pro 拒答理由输出
        assert t1["v4pro_reject_rationale"] == "synthetic rationale"
        # 第三轮理由不在本任务允许读取范围 → 显式 null + 说明
        assert t1["third_pass_reject_reason"] is None
        assert "允许读取" in t1["third_pass_reject_reason_note"]
        # 第三轮 reject 事实（∈ disputed）已确认
        assert t1["third_pass_reject_confirmed"] is True

    def test_summary_json_counts_and_manifest_self_sha(self, tmp_path):
        summary = _run(tmp_path)
        out = tmp_path / "out"
        sj = json.loads((out / "repair-feasibility-summary.json")
                        .read_text(encoding="utf-8"))
        assert sj["n_cases"] == 7 and sj["n_answer_points"] == 8
        assert sj["action_counts"]["add_exact_evidence"] == 1
        assert sj["action_counts"]["manual_semantic_adjudication_required"] \
            >= 4
        assert sj["action_counts"]["narrow_answer_point"] == 1
        assert sj["action_counts"]["remove_unsupported_answer_point"] == 1
        m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        body = {k: v for k, v in m.items()}
        outputs = dict(body["outputs"])
        del outputs["manifest.json"]
        body["outputs"] = outputs
        recomputed = hashlib.sha256(
            json.dumps(body, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")).hexdigest()
        assert m["outputs"]["manifest.json"]["sha256"] == recomputed

    def test_inputs_shas_and_rows_recorded(self, tmp_path):
        summary = _run(tmp_path)
        m = json.loads((tmp_path / "out" / "manifest.json")
                       .read_text(encoding="utf-8"))
        inp = tmp_path / "in"
        assert m["inputs"]["merged-adjudications.jsonl"]["rows"] == 8
        assert m["inputs"]["human-review-pack.jsonl"]["rows"] == 8
        assert m["inputs"]["chunks.jsonl"]["rows"] == 3
        assert len(m["inputs"]["selection-manifest.json"]["sha256"]) == 64

    def test_outputs_deterministic_byte_identical(self, tmp_path):
        _run(tmp_path)
        first = {p.name: p.read_bytes()
                 for p in (tmp_path / "out").iterdir()}
        _run(tmp_path)
        second = {p.name: p.read_bytes()
                  for p in (tmp_path / "out").iterdir()}
        assert set(first) == set(second)
        for name in first:
            assert first[name] == second[name], name

    def test_md_report_has_all_cases_and_disclaimer(self, tmp_path):
        _run(tmp_path)
        md = (tmp_path / "out" / "persistent-reject-evidence-audit.md") \
            .read_text(encoding="utf-8")
        for cid in TARGET:
            assert cid in md
        assert "v2.1" in md or "v2.1 准入" in md
        assert "人工审核" in md or "人工终审" in md
        assert "自动修复" in md or "不代表自动修复" in md
        assert "HUMAN_REVIEWED" not in md


# ── fail-closed 校验 ─────────────────────────────────────────────────

class TestFailClosed:
    def test_extra_reject_not_in_target_fails(self, tmp_path):
        inp = _write_fixture(tmp_path)
        rows = _read_jsonl(inp / "merged-adjudications.jsonl")
        rows[0]["semantic_verdict"] = "reject"  # 仍是 reject，但改 index 映射
        with pytest.raises(pra.PersistentRejectAuditError):
            pra.run(merged_path=inp / "merged-adjudications.jsonl",
                    sel_path=inp / "selection-manifest.json",
                    pack_path=inp / "human-review-pack.jsonl",
                    chunks_path=inp / "chunks.jsonl",
                    out_dir=tmp_path / "out2",
                    target_case_ids=["t-002"], expected_pack_rows=PACK_ROWS)

    def test_merged_missing_target_reject_fails(self, tmp_path):
        inp = _write_fixture(tmp_path)
        rows = _read_jsonl(inp / "merged-adjudications.jsonl")
        rows[0]["semantic_verdict"] = "confirmed"
        (inp / "merged-adjudications.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8")
        with pytest.raises(pra.PersistentRejectAuditError, match="reject"):
            pra.run(merged_path=inp / "merged-adjudications.jsonl",
                    sel_path=inp / "selection-manifest.json",
                    pack_path=inp / "human-review-pack.jsonl",
                    chunks_path=inp / "chunks.jsonl",
                    out_dir=tmp_path / "out2",
                    target_case_ids=TARGET, expected_pack_rows=PACK_ROWS)

    def test_merged_rows_mismatch_manifest_mapping_fails(self, tmp_path):
        inp = _write_fixture(tmp_path)
        sel = json.loads((inp / "selection-manifest.json")
                         .read_text(encoding="utf-8"))
        sel["total_cases"] = 99
        (inp / "selection-manifest.json").write_text(
            json.dumps(sel, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(pra.PersistentRejectAuditError):
            pra.run(merged_path=inp / "merged-adjudications.jsonl",
                    sel_path=inp / "selection-manifest.json",
                    pack_path=inp / "human-review-pack.jsonl",
                    chunks_path=inp / "chunks.jsonl",
                    out_dir=tmp_path / "out2",
                    target_case_ids=TARGET, expected_pack_rows=PACK_ROWS)

    def test_pack_row_count_mismatch_fails(self, tmp_path):
        inp = _write_fixture(tmp_path)
        with pytest.raises(pra.PersistentRejectAuditError, match="150|行数|rows"):
            pra.run(merged_path=inp / "merged-adjudications.jsonl",
                    sel_path=inp / "selection-manifest.json",
                    pack_path=inp / "human-review-pack.jsonl",
                    chunks_path=inp / "chunks.jsonl",
                    out_dir=tmp_path / "out2",
                    target_case_ids=TARGET, expected_pack_rows=150)

    def test_duplicate_chunk_id_fails(self, tmp_path):
        inp = _write_fixture(tmp_path)
        (inp / "chunks.jsonl").write_text(
            "\n".join(json.dumps(c, ensure_ascii=False)
                      for c in CHUNKS + [CHUNKS[0]]) + "\n",
            encoding="utf-8")
        with pytest.raises(pra.PersistentRejectAuditError, match="chunk"):
            pra.run(merged_path=inp / "merged-adjudications.jsonl",
                    sel_path=inp / "selection-manifest.json",
                    pack_path=inp / "human-review-pack.jsonl",
                    chunks_path=inp / "chunks.jsonl",
                    out_dir=tmp_path / "out2",
                    target_case_ids=TARGET, expected_pack_rows=PACK_ROWS)

    def test_missing_evidence_chunk_fails(self, tmp_path):
        inp = _write_fixture(tmp_path)
        packs = _read_jsonl(inp / "human-review-pack.jsonl")
        packs[0]["evidence"] = [_ev("no-such-chunk", "x")]
        (inp / "human-review-pack.jsonl").write_text(
            "\n".join(json.dumps(c, ensure_ascii=False) for c in packs) + "\n",
            encoding="utf-8")
        with pytest.raises(pra.PersistentRejectAuditError, match="chunk"):
            pra.run(merged_path=inp / "merged-adjudications.jsonl",
                    sel_path=inp / "selection-manifest.json",
                    pack_path=inp / "human-review-pack.jsonl",
                    chunks_path=inp / "chunks.jsonl",
                    out_dir=tmp_path / "out2",
                    target_case_ids=TARGET, expected_pack_rows=PACK_ROWS)

    def test_supports_indices_must_cover_answer_points(self, tmp_path):
        inp = _write_fixture(tmp_path)
        rows = _read_jsonl(inp / "merged-adjudications.jsonl")
        rows[0]["answer_point_supports"] = [_support(0, "unsupported")]
        (inp / "merged-adjudications.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8")
        with pytest.raises(pra.PersistentRejectAuditError, match="answer_point"):
            pra.run(merged_path=inp / "merged-adjudications.jsonl",
                    sel_path=inp / "selection-manifest.json",
                    pack_path=inp / "human-review-pack.jsonl",
                    chunks_path=inp / "chunks.jsonl",
                    out_dir=tmp_path / "out2",
                    target_case_ids=TARGET, expected_pack_rows=PACK_ROWS)

    def test_target_missing_from_pack_fails(self, tmp_path):
        inp = _write_fixture(tmp_path)
        packs = [c for c in _read_jsonl(inp / "human-review-pack.jsonl")
                 if c["case_id"] != "t-007"]
        (inp / "human-review-pack.jsonl").write_text(
            "\n".join(json.dumps(c, ensure_ascii=False) for c in packs) + "\n",
            encoding="utf-8")
        with pytest.raises(pra.PersistentRejectAuditError, match="pack"):
            pra.run(merged_path=inp / "merged-adjudications.jsonl",
                    sel_path=inp / "selection-manifest.json",
                    pack_path=inp / "human-review-pack.jsonl",
                    chunks_path=inp / "chunks.jsonl",
                    out_dir=tmp_path / "out2",
                    target_case_ids=TARGET, expected_pack_rows=len(packs))

    def test_target_must_be_in_disputed_set(self, tmp_path):
        inp = _write_fixture(tmp_path)
        sel = json.loads((inp / "selection-manifest.json")
                         .read_text(encoding="utf-8"))
        sel["disputed"] = [c for c in sel["disputed"] if c != "t-007"]
        (inp / "selection-manifest.json").write_text(
            json.dumps(sel, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(pra.PersistentRejectAuditError, match="disputed"):
            pra.run(merged_path=inp / "merged-adjudications.jsonl",
                    sel_path=inp / "selection-manifest.json",
                    pack_path=inp / "human-review-pack.jsonl",
                    chunks_path=inp / "chunks.jsonl",
                    out_dir=tmp_path / "out2",
                    target_case_ids=TARGET, expected_pack_rows=PACK_ROWS)


# ── 真实语料（skipif 缺失）───────────────────────────────────────────

MERGED_REAL = ROOT / "evaluation/datasets/v2/llm-semantic-adjudication" / \
    "coherence-recheck/merged-adjudications.jsonl"
SEL_REAL = ROOT / "evaluation/datasets/v2/llm-semantic-adjudication" / \
    "selection-manifest.json"
PACK_REAL = ROOT / "evaluation/datasets/v2/human-review/human-review-pack.jsonl"
CHUNKS_REAL = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
OUT_REAL = ROOT / "evaluation/datasets/v2/persistent-reject-evidence-audit"
REAL_PRESENT = all(p.is_file() for p in
                   (MERGED_REAL, SEL_REAL, PACK_REAL, CHUNKS_REAL))

pytestmark = pytest.mark.skipif(not REAL_PRESENT,
                                reason="real corpus files missing")


def _run_real(tmp_path: Path) -> tuple[dict, Path]:
    """在临时目录重跑审计（绝不改写历史审计目录 OUT_REAL）。

    修复前 blank pack 来自版本化快照；manifest 含输入路径故无法与历史
    逐字节一致，只比较 4 个不含路径的产物是否与历史逐字节一致。
    """
    import v2_repair_snapshot_util as snap
    out_dir = tmp_path / "out"
    summary = pra.run(merged_path=MERGED_REAL, sel_path=SEL_REAL,
                      pack_path=snap.pre_repair_pack(tmp_path),
                      chunks_path=CHUNKS_REAL, out_dir=out_dir)
    return summary, out_dir


def _assert_matches_stored(out_dir: Path) -> None:
    """4 个不含路径的产物必须与历史审计产物逐字节一致（只读比较）。"""
    for name in ("persistent-reject-cases.jsonl",
                 "candidate-evidence-spans.jsonl",
                 "repair-feasibility-summary.json",
                 "persistent-reject-evidence-audit.md"):
        assert (out_dir / name).read_bytes() == (OUT_REAL / name).read_bytes(), \
            f"{name} 与历史审计产物不一致"


class TestRealCorpus:
    def test_audit_covers_5_cases_and_is_deterministic(self, tmp_path):
        summary1, out1 = _run_real(tmp_path)
        first = {p.name: p.read_bytes() for p in out1.iterdir()}
        summary2, out2 = _run_real(tmp_path)
        second = {p.name: p.read_bytes() for p in out2.iterdir()}
        assert set(first) == set(second)
        for name in first:
            assert first[name] == second[name], name
        assert summary1["n_cases"] == 5
        assert summary1["n_answer_points"] == 9
        assert summary1["n_unsupported_points"] == 5
        _assert_matches_stored(out1)

    def test_key_classifications_on_real_corpus(self, tmp_path):
        _summary, out_dir = _run_real(tmp_path)
        pts = _points_by_id(out_dir)
        # multi-014 第二个答案点：全文有精确原文 → add_exact_evidence
        m14 = [p for p in pts["multi-014"]
               if p["answer_point_index"] == 1][0]
        assert m14["repair_feasibility"] == "exact_local_evidence_available"
        assert m14["proposed_action"] == "add_exact_evidence"
        # en-055：中文答案点 vs 英文文档 → language mismatch → manual
        e55 = pts["en-055"][0]
        assert e55["language_mismatch"] is True
        assert e55["proposed_action"] == "manual_semantic_adjudication_required"
        # en-052 第二个答案点：分散部分支撑（ownership rules / memory safety）
        e52 = [p for p in pts["en-052"] if p["answer_point_index"] == 1][0]
        assert e52["repair_feasibility"] == "only_paraphrase_or_partial_evidence"
        assert e52["proposed_action"] == "manual_semantic_adjudication_required"
        # mixed-026 第二个答案点：相关源内无逐字证据且范围外无命中 → remove
        m26 = [p for p in pts["mixed-026"]
               if p["answer_point_index"] == 1][0]
        assert m26["repair_feasibility"] == "no_local_evidence_found"
        assert m26["proposed_action"] == "remove_unsupported_answer_point"
        # 第三轮理由不在允许读取范围 → null
        cases = _cases_jsonl(out_dir)
        assert all(c["third_pass_reject_reason"] is None for c in cases)
        assert all(c["third_pass_reject_confirmed"] is True for c in cases)

    def test_candidate_spans_carry_full_location_info(self, tmp_path):
        _summary, out_dir = _run_real(tmp_path)
        spans = _read_jsonl(out_dir / "candidate-evidence-spans.jsonl")
        assert spans
        for s in spans:
            assert s["chunk_id"] and s["source_id"]
            assert 0 <= s["char_start"] < s["char_end"]
            assert s["span_text"]
        # multi-014 的精确候选（~38 字符）在 python-tutorial-zh.md 6.4 节 chunk
        m14 = [s for s in spans if s["case_id"] == "multi-014"
               and s["answer_point_index"] == 1]
        assert m14
        exact = [s for s in m14 if "specific_submodule" in s["span_text"]
                 and not s["out_of_scope_only"]]
        assert exact
        assert exact[0]["source_id"] == "python-tutorial-zh.md"
        assert exact[0]["norm_match_len"] >= 30
        assert "from package import specific_submodule" in exact[0]["span_text"]
