"""Tests for scripts.corpus_v2_remediation_triage — deterministic,
offline root-cause triage of the 37 blocking cases (reject ∪ needs_followup)
in the v2.0.1 automated review.

What the triage does, per blocking case and per acceptable answer point:

- fail-closed gate: canonical must be exactly 113 confirmed / 20 reject /
  17 needs_followup (non-confirmed = 37), issues must be exactly the 37,
  canonical SHA must match manifest.review_sha256; any drift → TriageError,
  zero outputs;
- deterministic field checks: refusal labels (should_refuse / is_refusal_turn /
  answer points / review refusal assessment) and evidence scope
  (evidence source/chunk vs draft relevant scope);
- per answer point: language mismatch check, verbatim span collection in the
  relevant sources (in-scope) and elsewhere (out-of-scope), max coverage,
  exact/partial/none status, whether an exact span is already inside the
  current evidence snippet;
- per case, exactly one of five mutually exclusive categories:
  exact_local_evidence_available (mechanically repairable evidence gap) |
  partial_or_paraphrase_evidence_only (owner policy, no auto-modify) |
  no_local_evidence_found (removable point / zero-point modeling) |
  refusal_label_or_schema_inconsistency (label fields contradict) |
  semantic_judgment_unresolved (evidence sufficient; blocker is semantic).

Guarantees under test: 37 rows classified exactly once; out-of-scope spans
never used as repair basis; historical third-round verdicts are never read
(source-scan); two runs are byte-identical; input files are never modified;
no overlay is generated; the 150 canonical decisions are never rewritten.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.corpus_v2_remediation_triage as rt

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEW_DIR = REPO_ROOT / "evaluation" / "datasets" / "v2" / "automated-review"
DRAFT_PATH = (REPO_ROOT / "evaluation" / "datasets" / "v2" / "annotations"
              / "v2-cases-draft.jsonl")
CHUNKS_PATH = REPO_ROOT / "data" / "v2-corpus" / "chunks" / "chunks.jsonl"

CATEGORIES = (
    "exact_local_evidence_available",
    "partial_or_paraphrase_evidence_only",
    "no_local_evidence_found",
    "refusal_label_or_schema_inconsistency",
    "semantic_judgment_unresolved",
)

# 锁定后的真实数据预期分类（由确定性规则推出，测试用于防回归）
EXPECTED_CATEGORY = {
    "en-029": "partial_or_paraphrase_evidence_only",
    "en-031": "exact_local_evidence_available",
    "en-034": "semantic_judgment_unresolved",
    "en-041": "partial_or_paraphrase_evidence_only",
    "en-042": "partial_or_paraphrase_evidence_only",
    "en-044": "partial_or_paraphrase_evidence_only",
    "en-048": "partial_or_paraphrase_evidence_only",
    "en-049": "partial_or_paraphrase_evidence_only",
    "en-051": "partial_or_paraphrase_evidence_only",
    "en-052": "refusal_label_or_schema_inconsistency",
    "mixed-016": "partial_or_paraphrase_evidence_only",
    "mixed-027": "refusal_label_or_schema_inconsistency",
    "mixed-029": "partial_or_paraphrase_evidence_only",
    "multi-018": "partial_or_paraphrase_evidence_only",
    "multi-019": "partial_or_paraphrase_evidence_only",
    "multi-020": "exact_local_evidence_available",
    "multi-028": "partial_or_paraphrase_evidence_only",
    "noanswer-026": "refusal_label_or_schema_inconsistency",
    "noanswer-029": "refusal_label_or_schema_inconsistency",
    "noanswer-030": "refusal_label_or_schema_inconsistency",
    "noanswer-031": "refusal_label_or_schema_inconsistency",
    "noanswer-032": "refusal_label_or_schema_inconsistency",
    "noanswer-037": "refusal_label_or_schema_inconsistency",
    "noanswer-040": "refusal_label_or_schema_inconsistency",
    "noanswer-044": "refusal_label_or_schema_inconsistency",
    "noanswer-045": "refusal_label_or_schema_inconsistency",
    "noanswer-052": "refusal_label_or_schema_inconsistency",
    "noanswer-054": "refusal_label_or_schema_inconsistency",
    "zh-040": "exact_local_evidence_available",
    "zh-042": "partial_or_paraphrase_evidence_only",
    "zh-045": "no_local_evidence_found",
    "zh-046": "partial_or_paraphrase_evidence_only",
    "zh-048": "partial_or_paraphrase_evidence_only",
    "zh-050": "partial_or_paraphrase_evidence_only",
    "zh-052": "partial_or_paraphrase_evidence_only",
    "zh-053": "partial_or_paraphrase_evidence_only",
    "zh-056": "no_local_evidence_found",
}

# 历史第三轮相关路径 / 关键词：分流逻辑严禁引用（防历史 verdict 影响）
FORBIDDEN_SOURCE_MARKERS = (
    "llm-third-pass", "third-pass", "llm-filled", "llm-semantic-adjudication",
    "selection-manifest", "merged-adjudications", "persistent-reject",
    "human-review-pack", "coherence",
)


# ── helpers ────────────────────────────────────────────────────────────

def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _line(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]


# ── 真实数据测试 ───────────────────────────────────────────────────────

class TestCanonicalGate:
    """canonical 113/20/17/37 门禁（fail-closed）。"""

    def test_canonical_counts_exact(self):
        rows = _load_jsonl(REVIEW_DIR / "automated-review.jsonl")
        assert len(rows) == 150
        assert len({r["case_id"] for r in rows}) == 150
        counts = {}
        for r in rows:
            counts[r["review_decision"]] = counts.get(r["review_decision"], 0) + 1
        assert counts == {"confirmed": 113, "reject": 20,
                          "needs_followup": 17}
        non_confirmed = [r["case_id"] for r in rows
                         if r["review_decision"] != "confirmed"]
        assert len(non_confirmed) == 37

    def test_issues_exactly_non_confirmed(self):
        issues = _load_jsonl(REVIEW_DIR / "automated-review-issues.jsonl")
        canon = _load_jsonl(REVIEW_DIR / "automated-review.jsonl")
        assert len(issues) == 37
        assert len({i["case_id"] for i in issues}) == 37
        expected = {r["case_id"] for r in canon
                    if r["review_decision"] != "confirmed"}
        assert {i["case_id"] for i in issues} == expected

    def test_fail_closed_on_count_drift(self, tmp_path):
        """canonical 计数漂移 → TriageError，零输出。"""
        (draft_p, chunks_p, canon_p, issues_p, ev_p, man_p) = \
            _synthetic_inputs(tmp_path, tamper="counts")
        out = tmp_path / "out"
        with pytest.raises(rt.TriageError):
            rt.run(review_dir=tmp_path, draft_path=draft_p,
                   chunks_path=chunks_p, out_dir=out,
                   expected_counts=(0, 6, 1))
        assert not out.exists() or not list(out.iterdir())

    def test_fail_closed_on_sha_drift(self, tmp_path):
        """canonical SHA 与 manifest 漂移 → TriageError，零输出。"""
        (draft_p, chunks_p, canon_p, issues_p, ev_p, man_p) = \
            _synthetic_inputs(tmp_path, tamper="sha")
        out = tmp_path / "out"
        with pytest.raises(rt.TriageError):
            rt.run(review_dir=tmp_path, draft_path=draft_p,
                   chunks_path=chunks_p, out_dir=out,
                   expected_counts=(0, 6, 1))
        assert not out.exists() or not list(out.iterdir())


class TestRealTriage:
    """真实 37 条分流结果与证据规格。"""

    @pytest.fixture(scope="class")
    def run_result(self, tmp_path_factory):
        out = tmp_path_factory.mktemp("triage-real")
        return rt.run(review_dir=REVIEW_DIR, draft_path=DRAFT_PATH,
                      chunks_path=CHUNKS_PATH, out_dir=out)

    def test_37_rows_exactly_once(self, run_result):
        rows = run_result["triage"]
        assert len(rows) == 37
        assert len({r["case_id"] for r in rows}) == 37
        canon = _load_jsonl(REVIEW_DIR / "automated-review.jsonl")
        expected = {r["case_id"] for r in canon
                    if r["review_decision"] != "confirmed"}
        assert {r["case_id"] for r in rows} == expected

    def test_categories_mutually_exclusive_and_cover(self, run_result):
        for r in run_result["triage"]:
            assert r["category"] in CATEGORIES
        assert len(run_result["triage"]) == 37

    def test_expected_distribution_locked(self, run_result):
        got = {r["case_id"]: r["category"] for r in run_result["triage"]}
        assert got == EXPECTED_CATEGORY

    def test_mechanically_repairable_only_for_cat1(self, run_result):
        for r in run_result["triage"]:
            if r["category"] == "exact_local_evidence_available":
                assert r["mechanically_repairable"] is True
                assert r["requires_owner_policy"] is False
            else:
                assert r["mechanically_repairable"] is False
                assert r["requires_owner_policy"] is True

    def test_cat1_evidence_specs_are_exact_contiguous_spans(self, run_result):
        chunks = {c["chunk_id"]: c
                  for c in _load_jsonl(CHUNKS_PATH)}
        for r in run_result["triage"]:
            if r["category"] != "exact_local_evidence_available":
                continue
            assert r["evidence_specs"], f"{r['case_id']} 缺 evidence_specs"
            for spec in r["evidence_specs"]:
                ch = chunks[spec["chunk_id"]]
                assert spec["source_id"] == ch["source"]
                s, e = spec["char_start"], spec["char_end"]
                assert 0 <= s < e <= len(ch["text"])
                assert spec["span_text"] == ch["text"][s:e]
                assert spec["coverage"] >= rt.COVERAGE_EXACT
                assert spec["in_scope"] is True
                # 连续性：span 是 chunk 的连续切片，且归一化后是答案点的
                # 连续子串
                ap_norm = rt._norm_with_map(
                    r["answer_points"][spec["answer_point_index"]][
                        "answer_point"])[0]
                span_norm = rt._norm_with_map(spec["span_text"])[0]
                assert span_norm in ap_norm

    def test_out_of_scope_spans_never_repair_basis(self, run_result):
        for r in run_result["triage"]:
            for spec in r.get("evidence_specs") or []:
                assert spec["in_scope"] is True
        for sp in run_result["spans"]:
            if sp.get("out_of_scope_only"):
                assert sp.get("repair_basis") is False

    def test_refusal_cases_subtypes(self, run_result):
        got = {r["case_id"]: r for r in run_result["triage"]}
        for cid in ("noanswer-026", "noanswer-054"):
            assert got[cid]["category"] == \
                "refusal_label_or_schema_inconsistency"
            assert got[cid]["sub_type"] == "missing_refusal_turn_label"
            assert got[cid]["contradiction"] == {
                "should_refuse": True, "is_refusal_turn": None}
        assert got["en-052"]["sub_type"] == "refusal_assessment_conflict"
        assert got["mixed-027"]["sub_type"] == "refusal_assessment_conflict"

    def test_cat3_subtype_zero_points_modeling(self, run_result):
        got = {r["case_id"]: r for r in run_result["triage"]}
        for cid in ("zh-045", "zh-056"):
            assert got[cid]["category"] == "no_local_evidence_found"
            assert got[cid]["sub_type"] == "zero_answer_points_modeling"

    def test_candidate_spans_validity(self, run_result):
        chunks = {c["chunk_id"]: c for c in _load_jsonl(CHUNKS_PATH)}
        for sp in run_result["spans"]:
            ch = chunks[sp["chunk_id"]]
            assert sp["source_id"] == ch["source"]
            s, e = sp["char_start"], sp["char_end"]
            assert 0 <= s < e <= len(ch["text"])
            assert sp["span_text"] == ch["text"][s:e]
            # 最短 span 阈值随答案点长度收缩（min(8, 答案点归一化长度)）
            ap_norm = rt._norm_with_map(sp["answer_point"])[0]
            assert sp["norm_match_len"] >= min(rt.MIN_SPAN_LEN, len(ap_norm))
            assert sp["in_scope"] in (True, False)

    def test_issue_id_and_decision_fields(self, run_result):
        canon = {r["case_id"]: r for r in
                 _load_jsonl(REVIEW_DIR / "automated-review.jsonl")}
        for r in run_result["triage"]:
            assert r["decision"] == canon[r["case_id"]]["review_decision"]
            assert r["decision"] in ("reject", "needs_followup")
            assert r["issue_id"] == r["case_id"]

    def test_data_quality_report_sections(self, run_result):
        dq = run_result["data_quality"]
        for section in ("completeness", "uniqueness", "snippet_continuity",
                        "source_consistency", "answer_point_evidence_coverage"):
            assert section in dq
        assert dq["completeness"]["canonical_rows"] == 150
        assert dq["uniqueness"]["canonical_case_ids_unique"] is True
        assert dq["snippet_continuity"]["snippet_sha256_self_consistent"] == 161
        assert dq["source_consistency"]["evidence_source_matches_chunk"] is True

    def test_manifest_outputs_sha(self, run_result):
        out = Path(run_result["out_dir"])
        for name in rt.OUTPUT_FILES:
            assert (out / name).is_file(), name
        m = run_result["manifest"]
        assert m["inputs"]["automated-review.jsonl"]["sha256"] == \
            _sha256_file(REVIEW_DIR / "automated-review.jsonl")
        for name in rt.OUTPUT_FILES:
            if name == "manifest.json":
                continue
            assert m["outputs"][name]["sha256"] == \
                _sha256_file(out / name)
        # 输出路径为相对文件名（跨目录确定性）
        assert m["outputs"]["blocking-case-triage.jsonl"]["path"] == \
            "blocking-case-triage.jsonl"
        # manifest 自身 SHA：去除 manifest_sha256 键后的规范化序列化复算
        body = {k: v for k, v in m.items() if k != "manifest_sha256"}
        assert m["manifest_sha256"] == _sha256_text(
            json.dumps(body, ensure_ascii=False, indent=1) + "\n")


class TestNoHistoricalInfluence:
    """分流逻辑不得读取历史第三轮 verdict/notes。"""

    def test_source_does_not_reference_forbidden_paths(self):
        src = Path(rt.__file__).read_text(encoding="utf-8")
        for marker in FORBIDDEN_SOURCE_MARKERS:
            assert marker.lower() not in src.lower(), marker


class TestDeterminismAndSafety:
    """确定性重建、输入 SHA 不变、不生成 overlay、不改写 150 条数据。"""

    @pytest.fixture(scope="class")
    def two_runs(self, tmp_path_factory):
        out1 = tmp_path_factory.mktemp("triage-det-1")
        out2 = tmp_path_factory.mktemp("triage-det-2")
        inputs = (REVIEW_DIR / "automated-review.jsonl",
                  REVIEW_DIR / "automated-review-evidence.jsonl",
                  REVIEW_DIR / "automated-review-issues.jsonl",
                  REVIEW_DIR / "manifest.json",
                  DRAFT_PATH, CHUNKS_PATH)
        shas_before = {p.name: _sha256_file(p) for p in inputs}
        r1 = rt.run(review_dir=REVIEW_DIR, draft_path=DRAFT_PATH,
                    chunks_path=CHUNKS_PATH, out_dir=out1)
        r2 = rt.run(review_dir=REVIEW_DIR, draft_path=DRAFT_PATH,
                    chunks_path=CHUNKS_PATH, out_dir=out2)
        shas_after = {p.name: _sha256_file(p) for p in inputs}
        return r1, r2, shas_before, shas_after, out1, out2

    def test_two_runs_byte_identical(self, two_runs):
        r1, r2, _, _, out1, out2 = two_runs
        for name in rt.OUTPUT_FILES:
            assert (out1 / name).read_bytes() == (out2 / name).read_bytes()

    def test_input_shas_unchanged(self, two_runs):
        _, _, before, after, _, _ = two_runs
        assert before == after

    def test_no_overlay_and_no_input_rewrite(self, two_runs):
        r1, _, _, _, out1, _ = two_runs
        # 输出只出现在 out_dir，且文件名恰为 OUTPUT_FILES
        written = {str(p.relative_to(out1)) for p in out1.rglob("*")
                   if p.is_file()}
        assert written == set(rt.OUTPUT_FILES)
        # 未生成 overlay（任何文件名含 overlay 的产物）
        assert not any("overlay" in str(p).lower()
                       for p in out1.rglob("*"))
        # canonical 150 条 decision 未被改写（sha 已断言，此处再核对内容）
        canon = _load_jsonl(REVIEW_DIR / "automated-review.jsonl")
        assert len(canon) == 150
        assert all(r["review_decision"] in ("confirmed", "reject",
                                            "needs_followup")
                   for r in canon)


# ── 合成数据：五类边界 ─────────────────────────────────────────────────

def _synthetic_inputs(tmp: Path, tamper: str = ""):
    """构造 7 条合成 case 的完整输入（draft/chunks/canonical/issues/
    evidence/manifest），支持 tamper=counts|sha 破坏门禁。"""
    chunks = [
        {"chunk_id": "a_chunk_0", "index": 0, "source": "doc-a.txt",
         "text": "Alpha rule: every value has exactly one owner. "
                 "The owner drops the value when leaving scope. "
                 "Beta command is createdb and it creates a database. "
                 "Gamma section title module input output."},
        {"chunk_id": "b_chunk_0", "index": 0, "source": "doc-b.txt",
         "text": "Unrelated documentation about graphs and trees. "
                 "Nothing about alpha beta or gamma here."},
    ]
    chunk_text = {c["chunk_id"]: c["text"] for c in chunks}

    def draft_row(cid, aps, refuse=False, srcs=("doc-a.txt",),
                  cids=("a_chunk_0",), qtype="single_turn"):
        return {"id": cid, "query": "q-" + cid, "query_type": qtype,
                "language": "en", "relevant_source_ids": list(srcs),
                "relevant_chunks": [{"source_id": srcs[0],
                                     "chunk_id": cids[0],
                                     "chunk_text_snippet": ""}],
                "relevant_chunk_ids": list(cids),
                "acceptable_answer_points": list(aps),
                "should_refuse": refuse,
                "is_refusal_turn": None,
                "metadata": {"difficulty": "hard"}}

    draft = [
        draft_row("c-exact-gap", ["createdb"]),        # exact 但 snippet 无
        draft_row("c-exact-in", ["Alpha rule"]),        # exact 且 snippet 有
        draft_row("c-partial", ["createdb creates database"]),  # partial
        # 一个 supported + 一个 unsupported → 可删除 unsupported 点
        draft_row("c-none-multi",
                  ["Alpha rule", "Zeta missing topic"]),
        draft_row("c-none-single", ["Zeta missing topic"]),  # none → 零答案点
        draft_row("c-refuse-label", [], refuse=True),  # refusal 缺标签
        draft_row("c-zero-points", []),                # 零答案点建模
    ]

    def canon_row(cid, decision, refusal=False):
        ev = [] if refusal else [
            {"chunk_id": "a_chunk_0", "char_range": {"start": 0, "end": 45},
             "snippet_preview": "Alpha rule: every value has exactly one "
                                "owner. The owner drops",
             "source_id": "doc-a.txt"}]
        return {"case_id": cid, "review_decision": decision,
                "reviewer_type": "LLM_ASSISTED_OWNER_AUTHORIZED",
                "confidence": "high", "evidence_summary": ev,
                "issue_categories": [], "rationale": "r-" + cid}

    canon = [
        canon_row("c-exact-gap", "reject"),
        canon_row("c-exact-in", "reject"),
        canon_row("c-partial", "needs_followup"),
        canon_row("c-none-multi", "reject"),
        canon_row("c-none-single", "reject"),
        canon_row("c-refuse-label", "reject", refusal=True),
        canon_row("c-zero-points", "reject"),
    ]
    if tamper == "counts":
        canon[0]["review_decision"] = "confirmed"

    issues = list(canon)

    def ev_row(cid):
        return {"case_id": cid, "chunk_id": "a_chunk_0",
                "char_range_start": 0, "char_range_end": 45,
                "snippet": "Alpha rule: every value has exactly one owner. "
                           "The owner drops",
                "source_id": "doc-a.txt",
                "snippet_sha256": _sha256_text(
                    "Alpha rule: every value has exactly one owner. "
                    "The owner drops"),
                "chunk_text_sha256": _sha256_text(chunk_text["a_chunk_0"])}

    evidence = [ev_row(c["case_id"]) for c in canon if c["evidence_summary"]]

    chunks_path = tmp / "chunks.jsonl"
    chunks_path.write_text("\n".join(_line(c) for c in chunks) + "\n",
                           encoding="utf-8")
    draft_path = tmp / "draft.jsonl"
    draft_path.write_text("\n".join(_line(d) for d in draft) + "\n",
                          encoding="utf-8")
    canon_path = tmp / "automated-review.jsonl"
    canon_path.write_text("\n".join(_line(c) for c in canon) + "\n",
                          encoding="utf-8")
    issues_path = tmp / "automated-review-issues.jsonl"
    issues_path.write_text("\n".join(_line(i) for i in issues) + "\n",
                           encoding="utf-8")
    ev_path = tmp / "automated-review-evidence.jsonl"
    ev_path.write_text("\n".join(_line(e) for e in evidence) + "\n",
                       encoding="utf-8")
    man = {"reviewer_type": "LLM_ASSISTED_OWNER_AUTHORIZED",
           "review_sha256": _sha256_file(canon_path),
           "inputs": {"draft": {"sha256": _sha256_file(draft_path)},
                      "chunks": {"sha256": _sha256_file(chunks_path)}},
           "decision_counts": {"confirmed": 0, "reject": 6,
                               "needs_followup": 1}}
    if tamper == "sha":
        man["review_sha256"] = "0" * 64
    man_path = tmp / "manifest.json"
    man_path.write_text(_line(man), encoding="utf-8")
    return (draft_path, chunks_path, canon_path, issues_path, ev_path,
            man_path)


def _run_synthetic(tmp_path, tamper=""):
    (draft_p, chunks_p, canon_p, issues_p, ev_p, man_p) = \
        _synthetic_inputs(tmp_path, tamper=tamper)
    out = tmp_path / "out"
    result = rt.run(review_dir=tmp_path, draft_path=draft_p,
                    chunks_path=chunks_p, out_dir=out,
                    expected_counts=(0, 6, 1))
    return result, out


class TestSyntheticBoundaries:
    """五类边界：exact 缺口 / exact 已入 snippet / partial / none /
    拒答标签矛盾 / 语言不匹配 / 零答案点建模。"""

    def test_exact_outside_snippet_is_cat1(self, tmp_path):
        result, _ = _run_synthetic(tmp_path)
        row = next(r for r in result["triage"]
                   if r["case_id"] == "c-exact-gap")
        assert row["category"] == "exact_local_evidence_available"
        assert row["mechanically_repairable"] is True
        spec = row["evidence_specs"][0]
        assert spec["chunk_id"] == "a_chunk_0"
        assert spec["span_text"] == "createdb"
        assert spec["coverage"] == 1.0

    def test_exact_in_snippet_is_cat5(self, tmp_path):
        result, _ = _run_synthetic(tmp_path)
        row = next(r for r in result["triage"]
                   if r["case_id"] == "c-exact-in")
        assert row["category"] == "semantic_judgment_unresolved"
        assert row["mechanically_repairable"] is False

    def test_partial_only_is_cat2(self, tmp_path):
        result, _ = _run_synthetic(tmp_path)
        row = next(r for r in result["triage"]
                   if r["case_id"] == "c-partial")
        assert row["category"] == "partial_or_paraphrase_evidence_only"
        assert row["requires_owner_policy"] is True
        assert row["mechanically_repairable"] is False

    def test_none_multi_point_is_cat3_removable(self, tmp_path):
        result, _ = _run_synthetic(tmp_path)
        row = next(r for r in result["triage"]
                   if r["case_id"] == "c-none-multi")
        assert row["category"] == "no_local_evidence_found"
        assert row["sub_type"] == "unsupported_answer_point_removable"

    def test_none_single_point_is_cat3_zero_modeling(self, tmp_path):
        result, _ = _run_synthetic(tmp_path)
        row = next(r for r in result["triage"]
                   if r["case_id"] == "c-none-single")
        assert row["category"] == "no_local_evidence_found"
        assert row["sub_type"] == "zero_answer_points_modeling"

    def test_refusal_missing_label_is_cat4(self, tmp_path):
        result, _ = _run_synthetic(tmp_path)
        row = next(r for r in result["triage"]
                   if r["case_id"] == "c-refuse-label")
        assert row["category"] == "refusal_label_or_schema_inconsistency"
        assert row["sub_type"] == "missing_refusal_turn_label"
        assert row["contradiction"] == {
            "should_refuse": True, "is_refusal_turn": None}

    def test_zero_aps_non_refusal_is_cat3(self, tmp_path):
        result, _ = _run_synthetic(tmp_path)
        row = next(r for r in result["triage"]
                   if r["case_id"] == "c-zero-points")
        assert row["category"] == "no_local_evidence_found"
        assert row["sub_type"] == "zero_answer_points_modeling"

    def test_language_mismatch_is_cat2(self, tmp_path):
        """中文答案点 + 英文源文档 → 逐字匹配不适用 → cat2 需所有者裁决。"""
        (draft_p, chunks_p, canon_p, issues_p, ev_p, man_p) = \
            _synthetic_inputs(tmp_path)
        draft = _load_jsonl(draft_p)
        draft.append({"id": "c-lang", "query": "q", "query_type": "single",
                      "language": "zh",
                      "relevant_source_ids": ["doc-b.txt"],
                      "relevant_chunks": [],
                      "relevant_chunk_ids": ["b_chunk_0"],
                      "acceptable_answer_points": ["每值唯一所有者"],
                      "should_refuse": False, "is_refusal_turn": None,
                      "metadata": {}})
        draft_p.write_text("\n".join(_line(d) for d in draft) + "\n",
                           encoding="utf-8")
        canon = _load_jsonl(canon_p)
        canon.append({"case_id": "c-lang", "review_decision": "reject",
                      "reviewer_type": "LLM_ASSISTED_OWNER_AUTHORIZED",
                      "confidence": "high", "evidence_summary": [],
                      "issue_categories": [], "rationale": "r"})
        canon_p.write_text("\n".join(_line(c) for c in canon) + "\n",
                           encoding="utf-8")
        issues_p.write_text("\n".join(_line(c) for c in canon) + "\n",
                            encoding="utf-8")
        man = json.loads(man_p.read_text(encoding="utf-8"))
        man["review_sha256"] = _sha256_file(canon_p)
        man["inputs"]["draft"]["sha256"] = _sha256_file(draft_p)
        man_p.write_text(_line(man), encoding="utf-8")
        out = tmp_path / "out"
        result = rt.run(review_dir=tmp_path, draft_path=draft_p,
                        chunks_path=chunks_p, out_dir=out,
                        expected_counts=(0, 7, 1))
        row = next(r for r in result["triage"] if r["case_id"] == "c-lang")
        assert row["category"] == "partial_or_paraphrase_evidence_only"
        assert row["answer_points"][0]["status"] == "language_mismatch"
