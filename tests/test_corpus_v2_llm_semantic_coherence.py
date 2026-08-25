"""Tests for scripts.corpus_v2_llm_semantic_coherence — fail-closed
semantic-coherence audit of the deepseek-v4-pro blind adjudications and
targeted re-adjudication of contract-violating cases.

Coherence contract:

- refusal (should_refuse=true): no_answer / partial_topic_overlap_only must
  map to semantic_verdict=confirmed; substantive_answer_exists must map to
  reject; unclear must map to needs_followup; answer_point_supports must be
  empty.
- answerable (should_refuse=false): each answer point must have exactly one
  assessment with contiguous non-duplicate indices; any unsupported point
  forbids confirmed; no unsupported point forbids reject; needs_followup
  requires an explicit inability-to-decide rationale.
- every row: legal verdict, non-empty rationale, reviewer model name, and
  index matching the blind input pack position.

The audit is read-only (coherence-audit.json + coherence-report.md written
into the adjudication directory); violating cases are re-adjudicated with
the same blind input, same model and temperature=0.0, at most 3 attempts,
with the mapping rules stated explicitly in the recheck prompt. After 3
failed attempts a case is fixed to needs_followup with recorded failure
evidence. Original adjudications are never rewritten; the recheck results
and the merged 102 rows live in coherence-recheck/.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.corpus_v2_llm_semantic_adjudication as adj
import scripts.corpus_v2_llm_semantic_coherence as coh

ROOT = Path(__file__).resolve().parents[1]

# ── synthetic world ──────────────────────────────────────────────────

CHUNK_A = "000000000001_chunk_1"
CHUNK_B = "000000000002_chunk_2"
CHUNK_A_TEXT = "X is a widget. X costs 5. C is D."
CHUNK_B_TEXT = "Y and Z together form W."
CHUNKS = [
    {"chunk_id": CHUNK_A, "index": 0, "source": "src-a", "text": CHUNK_A_TEXT},
    {"chunk_id": CHUNK_B, "index": 1, "source": "src-b", "text": CHUNK_B_TEXT},
]


def _ev(chunk_id: str, snippet: str, source_id: str = "src-a") -> dict:
    return {"source_id": source_id, "chunk_id": chunk_id,
            "snippet": snippet, "section": "s1"}


def _blank(case_id: str, *, query: str, query_type: str = "single_fact",
           should_refuse: bool = False, points: list | None = None,
           evidence: list | None = None) -> dict:
    return {
        "case_id": case_id, "query": query, "language": "en",
        "query_type": query_type, "previous_turns": [],
        "should_refuse": should_refuse,
        "relevance_level": "chunk" if evidence else "none",
        "acceptable_answer_points": points or [],
        "relevant_source_ids": sorted({e["source_id"]
                                       for e in (evidence or [])}),
        "evidence": evidence or [],
        "human_review_decision": "", "human_reviewer": "",
        "human_review_notes": "",
    }


CASES = [
    _blank("w-001", query="What is X?",
           points=["X is a widget", "X costs 5"],
           evidence=[_ev(CHUNK_A, "X is a widget. X costs 5.")]),
    _blank("w-002", query="Is A B?", points=["A is B"],
           evidence=[_ev(CHUNK_A, "C is D.")]),
    _blank("w-003", query="Does the corpus mention Q?",
           query_type="no_answer", should_refuse=True,
           evidence=[_ev(CHUNK_B, "Y and Z together form W.", "src-b")]),
    _blank("w-004", query="Does the corpus mention W?",
           query_type="no_answer", should_refuse=True,
           evidence=[_ev(CHUNK_B, "Y and Z together form W.", "src-b")]),
    _blank("w-005", query="How do Y and Z combine?",
           query_type="cross_document", points=["Y and Z together"],
           evidence=[_ev(CHUNK_A, "X is a widget. X costs 5."),
                     _ev(CHUNK_B, "Y and Z together form W.", "src-b")]),
]
BY_ID = {c["case_id"]: c for c in CASES}
CONFIRMED_IDS = ["w-001", "w-003", "w-005"]
REJECT_IDS = ["w-002", "w-004"]
EXPECTED = dict(expected_total=5, expected_confirmed=3,
                expected_reject=2, expected_followup=0)


def _filled(case: dict, decision: str) -> dict:
    r = dict(case)
    r["human_review_decision"] = decision
    r["human_reviewer"] = "LLM_ASSISTED_THIRD_PASS"
    r["human_review_notes"] = "third-pass note"
    return r


FILLED = [_filled(c, "confirmed") for c in CASES if c["case_id"] in CONFIRMED_IDS] \
    + [_filled(c, "reject") for c in CASES if c["case_id"] in REJECT_IDS]

# 每 case 的合法仲裁输出（与第三轮 decision 一致）
LEGAL = {
    "w-001": {"semantic_verdict": "confirmed",
              "verdict_rationale": "证据直接支持两个答案点",
              "answer_point_supports": [
                  {"answer_point_index": 0, "support_level": "direct_snippet",
                   "chunk_id": CHUNK_A, "excerpt": "X is a widget."},
                  {"answer_point_index": 1, "support_level": "direct_snippet",
                   "chunk_id": CHUNK_A, "excerpt": "X costs 5"}]},
    "w-002": {"semantic_verdict": "reject",
              "verdict_rationale": "snippet 不支持答案点",
              "answer_point_supports": [
                  {"answer_point_index": 0, "support_level": "unsupported",
                   "chunk_id": "", "excerpt": ""}]},
    "w-003": {"semantic_verdict": "confirmed",
              "verdict_rationale": "语料确实无 Q 相关内容",
              "refusal_assessment": "no_answer",
              "refusal_evidence": [{"chunk_id": CHUNK_B,
                                    "excerpt": "Y and Z together form W."}]},
    "w-004": {"semantic_verdict": "reject",
              "verdict_rationale": "语料存在实质答案，拒答不当",
              "refusal_assessment": "substantive_answer_exists",
              "refusal_evidence": [{"chunk_id": CHUNK_B,
                                    "excerpt": "Y and Z together form W."}]},
    "w-005": {"semantic_verdict": "confirmed",
              "verdict_rationale": "跨文档证据支持",
              "answer_point_supports": [
                  {"answer_point_index": 0, "support_level": "direct_snippet",
                   "chunk_id": CHUNK_B, "excerpt": "Y and Z together"}]},
}


def _blind_row(case_id: str) -> dict:
    return adj._blind_pack_row(BY_ID[case_id],
                               {CHUNK_A: CHUNK_A_TEXT, CHUNK_B: CHUNK_B_TEXT})


def _fake_llm(by_query: dict | None = None, *,
              resp_model: str = coh.REVIEWER_MODEL):
    """按 query 返回 canned 输出的假 llm_fn（可对同一 query 多轮应答）。"""
    by_query = by_query if by_query is not None else \
        {c["query"]: LEGAL[c["case_id"]] for c in CASES}
    counters: dict[str, int] = {}

    def llm_fn(call_type, messages, model=None, temperature=None,
               max_tokens=None):
        payload = json.loads(messages[1]["content"])
        query = payload["query"]
        n = counters.get(query, 0)
        counters[query] = n + 1
        answers = by_query[query]
        if isinstance(answers, list):
            canned = answers[min(n, len(answers) - 1)]
        else:
            canned = answers
        content = json.dumps(canned, ensure_ascii=False)
        resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            model=resp_model)
        return resp, SimpleNamespace(retries_used=0)

    return llm_fn


def _write_fixture(tmp_path: Path) -> Path:
    """写入合成 blank/filled/chunks，返回目录路径。"""
    (tmp_path / "chunks.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in CHUNKS) + "\n",
        encoding="utf-8")
    (tmp_path / "blank.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in CASES) + "\n",
        encoding="utf-8")
    (tmp_path / "filled.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in FILLED) + "\n",
        encoding="utf-8")
    return tmp_path


def _gen_adjudications(tmp_path: Path) -> Path:
    """用 adj.run + 假模型生成盲包/仲裁目录，返回目录路径。"""
    _write_fixture(tmp_path)
    out = tmp_path / "adj"
    adj.run(tmp_path / "blank.jsonl", tmp_path / "filled.jsonl",
            tmp_path / "chunks.jsonl", out, llm_fn=_fake_llm(),
            control_count=1, **EXPECTED)
    return out


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.open(encoding="utf-8")]


# ── 纯函数：validate_semantic_coherence ──────────────────────────────

class TestValidateSemanticCoherence:
    _MISSING = object()

    def _check(self, case_id: str, verdict: str, *,
               rationale: str = "结构化理由",
               supports: list | None = None,
               refusal_assessment: str | None = None,
               refusal_evidence: list | None = None,
               model: object = _MISSING,
               index: int = 1) -> list[dict]:
        row = dict(_blind_row(case_id), acceptable_answer_points=[])
        src = BY_ID[case_id]
        if not src["should_refuse"]:
            row["acceptable_answer_points"] = src["acceptable_answer_points"]
        m = coh.REVIEWER_MODEL if model is self._MISSING else model
        adj_row = {"index": index, "semantic_verdict": verdict,
                   "verdict_rationale": rationale,
                   "answer_point_supports": supports if supports is not None
                   else [],
                   "refusal_assessment": refusal_assessment,
                   "refusal_evidence": refusal_evidence if refusal_evidence
                   is not None else [],
                   "model": m}
        return coh.validate_semantic_coherence(row, adj_row)

    # 合法组合
    def test_legal_answerable_confirmed(self):
        assert self._check("w-001", "confirmed", supports=LEGAL["w-001"]
                           ["answer_point_supports"]) == []

    def test_legal_unsupported_reject(self):
        assert self._check("w-002", "reject", supports=LEGAL["w-002"]
                           ["answer_point_supports"]) == []

    def test_legal_refusal_no_answer_confirmed(self):
        assert self._check("w-003", "confirmed",
                           refusal_assessment="no_answer") == []

    def test_legal_refusal_partial_confirmed(self):
        assert self._check("w-004", "confirmed",
                           refusal_assessment="partial_topic_overlap_only") == []

    def test_legal_refusal_substantive_reject(self):
        assert self._check("w-004", "reject",
                           refusal_assessment="substantive_answer_exists") == []

    def test_legal_refusal_unclear_followup(self):
        assert self._check("w-004", "needs_followup",
                           rationale="无法确定语料中是否存在相关内容",
                           refusal_assessment="unclear") == []

    def test_legal_followup_with_reason_answerable(self):
        assert self._check("w-001", "needs_followup",
                           rationale="证据片段不足以判断，无法确认答案点支持",
                           supports=LEGAL["w-001"]["answer_point_supports"]) == []

    # 拒答题映射违规
    def test_refusal_no_answer_with_reject_violates(self):
        vs = self._check("w-003", "reject", refusal_assessment="no_answer")
        assert coh.RULE_REFUSAL_ASSESSMENT_MISMATCH in {v["rule"] for v in vs}

    def test_refusal_no_answer_with_followup_violates(self):
        vs = self._check("w-003", "needs_followup",
                         rationale="无法判断", refusal_assessment="no_answer")
        assert coh.RULE_REFUSAL_ASSESSMENT_MISMATCH in {v["rule"] for v in vs}

    def test_refusal_partial_with_reject_violates(self):
        vs = self._check("w-003", "reject",
                         refusal_assessment="partial_topic_overlap_only")
        assert coh.RULE_REFUSAL_ASSESSMENT_MISMATCH in {v["rule"] for v in vs}

    def test_refusal_substantive_with_confirmed_violates(self):
        vs = self._check("w-004", "confirmed",
                         refusal_assessment="substantive_answer_exists")
        assert coh.RULE_REFUSAL_ASSESSMENT_MISMATCH in {v["rule"] for v in vs}

    def test_refusal_unclear_with_confirmed_violates(self):
        vs = self._check("w-004", "confirmed",
                         refusal_assessment="unclear")
        assert coh.RULE_REFUSAL_ASSESSMENT_MISMATCH in {v["rule"] for v in vs}

    def test_refusal_missing_assessment_violates(self):
        vs = self._check("w-003", "confirmed")
        assert coh.RULE_REFUSAL_ASSESSMENT_MISMATCH in {v["rule"] for v in vs}

    def test_refusal_illegal_assessment_violates(self):
        vs = self._check("w-003", "confirmed",
                         refusal_assessment="bogus")
        assert coh.RULE_REFUSAL_ASSESSMENT_MISMATCH in {v["rule"] for v in vs}

    def test_refusal_with_supports_violates(self):
        vs = self._check("w-003", "confirmed",
                         refusal_assessment="no_answer",
                         supports=LEGAL["w-001"]["answer_point_supports"])
        assert coh.RULE_REFUSAL_SUPPORTS_NOT_EMPTY in {v["rule"] for v in vs}

    # 可答题 supports 结构
    def test_supports_missing_point_violates(self):
        vs = self._check("w-001", "confirmed",
                         supports=LEGAL["w-001"]["answer_point_supports"][:1])
        assert coh.RULE_SUPPORTS_NOT_EXACT in {v["rule"] for v in vs}

    def test_supports_duplicate_index_violates(self):
        s = LEGAL["w-001"]["answer_point_supports"]
        vs = self._check("w-001", "confirmed",
                         supports=[s[0], dict(s[0], excerpt="dup")])
        assert coh.RULE_SUPPORTS_NOT_EXACT in {v["rule"] for v in vs}

    def test_supports_non_contiguous_index_violates(self):
        vs = self._check("w-001", "confirmed", supports=[
            {"answer_point_index": 0, "support_level": "direct_snippet",
             "chunk_id": CHUNK_A, "excerpt": "X is a widget."},
            {"answer_point_index": 2, "support_level": "direct_snippet",
             "chunk_id": CHUNK_A, "excerpt": "X costs 5"}])
        assert coh.RULE_SUPPORTS_NOT_EXACT in {v["rule"] for v in vs}

    def test_supports_multiple_per_point_violates(self):
        s = LEGAL["w-001"]["answer_point_supports"]
        vs = self._check("w-001", "confirmed",
                         supports=[s[0], dict(s[0], chunk_id=CHUNK_B), s[1]])
        assert coh.RULE_SUPPORTS_NOT_EXACT in {v["rule"] for v in vs}

    def test_supports_empty_for_answerable_violates(self):
        vs = self._check("w-001", "confirmed", supports=[])
        assert coh.RULE_SUPPORTS_NOT_EXACT in {v["rule"] for v in vs}

    # 可答题 verdict 映射
    def test_unsupported_with_confirmed_violates(self):
        vs = self._check("w-002", "confirmed",
                         supports=LEGAL["w-002"]["answer_point_supports"])
        assert coh.RULE_UNSUPPORTED_WITH_CONFIRMED in {v["rule"] for v in vs}

    def test_all_supported_with_reject_violates(self):
        vs = self._check("w-001", "reject",
                         supports=LEGAL["w-001"]["answer_point_supports"])
        assert coh.RULE_NO_UNSUPPORTED_WITH_REJECT in {v["rule"] for v in vs}

    def test_unsupported_with_followup_is_legal(self):
        assert self._check("w-002", "needs_followup",
                           rationale="无法判断该答案点是否真无支持",
                           supports=LEGAL["w-002"]["answer_point_supports"]) == []

    def test_followup_without_reason_violates(self):
        vs = self._check("w-001", "needs_followup",
                         rationale="证据齐全但结论不足以确认",
                         supports=LEGAL["w-001"]["answer_point_supports"])
        assert coh.RULE_FOLLOWUP_WITHOUT_REASON in {v["rule"] for v in vs}

    # 每行基本合法性
    def test_invalid_verdict_violates(self):
        vs = self._check("w-001", "approved",
                         supports=LEGAL["w-001"]["answer_point_supports"])
        assert coh.RULE_INVALID_VERDICT in {v["rule"] for v in vs}

    def test_empty_rationale_violates(self):
        vs = self._check("w-001", "confirmed", rationale="   ",
                         supports=LEGAL["w-001"]["answer_point_supports"])
        assert coh.RULE_MISSING_RATIONALE in {v["rule"] for v in vs}

    def test_wrong_model_violates(self):
        vs = self._check("w-001", "confirmed", model="deepseek-v4-flash",
                         supports=LEGAL["w-001"]["answer_point_supports"])
        assert coh.RULE_WRONG_MODEL in {v["rule"] for v in vs}

    def test_missing_model_violates(self):
        vs = self._check("w-001", "confirmed", model=None,
                         supports=LEGAL["w-001"]["answer_point_supports"])
        assert coh.RULE_WRONG_MODEL in {v["rule"] for v in vs}

    def test_bad_index_violates(self):
        vs = self._check("w-001", "confirmed", index=0,
                         supports=LEGAL["w-001"]["answer_point_supports"])
        assert coh.RULE_INVALID_INDEX in {v["rule"] for v in vs}

    def test_legal_rows_report_no_violations(self):
        for cid in CASES:
            assert coh.validate_semantic_coherence(
                _blind_row(cid["case_id"]),
                dict(LEGAL[cid["case_id"]], index=1, model=coh.REVIEWER_MODEL,
                     parse_retries=0, retries_used=0)) == []

    def test_validation_is_pure(self):
        row = _blind_row("w-001")
        adj_row = dict(LEGAL["w-001"], index=1, model=coh.REVIEWER_MODEL)
        before = json.dumps([row, adj_row], ensure_ascii=False, sort_keys=True)
        assert coh.validate_semantic_coherence(row, adj_row) == []
        assert json.dumps([row, adj_row], ensure_ascii=False,
                          sort_keys=True) == before


# ── 只读审计 ─────────────────────────────────────────────────────────

class TestAudit:
    def test_audit_writes_json_and_report(self, tmp_path):
        out = _gen_adjudications(tmp_path)
        summary = coh.audit(out, blank_path=tmp_path / "blank.jsonl",
                            filled_path=tmp_path / "filled.jsonl",
                            chunks_path=tmp_path / "chunks.jsonl",
                            control_count=1, **EXPECTED)
        assert summary["n_total"] == 3
        assert (out / "coherence-audit.json").is_file()
        assert (out / "coherence-report.md").is_file()

    def test_audit_finds_all_violators_never_assumes_one(self, tmp_path):
        out = _gen_adjudications(tmp_path)
        # 制造两处违规：w-002 判 confirmed（unsupported 不得 confirmed）；
        # w-004 判 confirmed（substantive_answer_exists 必须 reject）
        idx = _mapping(out)
        rows = _read_jsonl(out / adj.ADJUDICATIONS_FILE)
        for r in rows:
            if r["index"] in {idx["w-002"], idx["w-004"]}:
                r["semantic_verdict"] = "confirmed"
        (out / adj.ADJUDICATIONS_FILE).write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8")
        summary = coh.audit(out, blank_path=tmp_path / "blank.jsonl",
                            filled_path=tmp_path / "filled.jsonl",
                            chunks_path=tmp_path / "chunks.jsonl",
                            control_count=1, **EXPECTED)
        assert summary["n_violating"] == 2
        audit = json.loads((out / "coherence-audit.json")
                           .read_text(encoding="utf-8"))
        by_cid = {v["case_id"]: v for v in audit["violations"]}
        assert set(by_cid) == {"w-002", "w-004"}
        rules2 = {v["rule"] for v in by_cid["w-002"]["rules"]}
        rules3 = {v["rule"] for v in by_cid["w-004"]["rules"]}
        assert coh.RULE_UNSUPPORTED_WITH_CONFIRMED in rules2
        assert coh.RULE_REFUSAL_ASSESSMENT_MISMATCH in rules3
        # 报告列出全部违反 case
        report = (out / "coherence-report.md").read_text(encoding="utf-8")
        assert "w-002" in report and "w-004" in report
        assert "unsupported_with_confirmed" in report
        assert "refusal_assessment_mismatch" in report

    def test_audit_is_read_only_on_inputs(self, tmp_path):
        out = _gen_adjudications(tmp_path)
        before = {
            p.name: p.read_bytes() for p in out.iterdir()
            if p.name in {adj.ADJUDICATIONS_FILE, "blind-input-pack.jsonl",
                          "selection-manifest.json"}}
        blank_before = (tmp_path / "blank.jsonl").read_bytes()
        coh.audit(out, blank_path=tmp_path / "blank.jsonl",
                  filled_path=tmp_path / "filled.jsonl",
                  chunks_path=tmp_path / "chunks.jsonl",
                  control_count=1, **EXPECTED)
        for name, data in before.items():
            assert (out / name).read_bytes() == data
        assert (tmp_path / "blank.jsonl").read_bytes() == blank_before

    def test_audit_rebuilds_blind_pack_deterministically(self, tmp_path):
        out = _gen_adjudications(tmp_path)
        coh.audit(out, blank_path=tmp_path / "blank.jsonl",
                  filled_path=tmp_path / "filled.jsonl",
                  chunks_path=tmp_path / "chunks.jsonl",
                  control_count=1, **EXPECTED)
        a = (out / "coherence-audit.json").read_bytes()
        coh.audit(out, blank_path=tmp_path / "blank.jsonl",
                  filled_path=tmp_path / "filled.jsonl",
                  chunks_path=tmp_path / "chunks.jsonl",
                  control_count=1, **EXPECTED)
        assert (out / "coherence-audit.json").read_bytes() == a

    def test_audit_records_input_shas_and_prompt_sha(self, tmp_path):
        out = _gen_adjudications(tmp_path)
        coh.audit(out, blank_path=tmp_path / "blank.jsonl",
                  filled_path=tmp_path / "filled.jsonl",
                  chunks_path=tmp_path / "chunks.jsonl",
                  control_count=1, **EXPECTED)
        audit = json.loads((out / "coherence-audit.json")
                           .read_text(encoding="utf-8"))
        assert len(audit["prompt_sha256"]) == 64
        assert audit["reviewer_model"] == coh.REVIEWER_MODEL
        assert audit["n_total"] == 3
        assert audit["inputs"]["blind_input_pack"]["sha256"] == \
            adj._sha256_file(out / "blind-input-pack.jsonl")
        assert audit["inputs"]["adjudications"]["rows"] == 3

    def test_audit_tampered_blind_pack_fails_closed(self, tmp_path):
        out = _gen_adjudications(tmp_path)
        (out / "blind-input-pack.jsonl").write_text(
            "{\"query\": \"tampered\"}\n", encoding="utf-8")
        with pytest.raises(coh.CoherenceError, match="盲包"):
            coh.audit(out, blank_path=tmp_path / "blank.jsonl",
                      filled_path=tmp_path / "filled.jsonl",
                      chunks_path=tmp_path / "chunks.jsonl",
                      control_count=1, **EXPECTED)

    def test_audit_missing_adjudication_row_fails_closed(self, tmp_path):
        out = _gen_adjudications(tmp_path)
        rows = _read_jsonl(out / adj.ADJUDICATIONS_FILE)[:-1]
        (out / adj.ADJUDICATIONS_FILE).write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8")
        with pytest.raises(coh.CoherenceError, match="102|覆盖|coverage"):
            coh.audit(out, blank_path=tmp_path / "blank.jsonl",
                      filled_path=tmp_path / "filled.jsonl",
                      chunks_path=tmp_path / "chunks.jsonl",
                      control_count=1, **EXPECTED)

    def test_audit_duplicate_index_fails_closed(self, tmp_path):
        out = _gen_adjudications(tmp_path)
        rows = _read_jsonl(out / adj.ADJUDICATIONS_FILE)
        rows[0]["index"] = 2
        (out / adj.ADJUDICATIONS_FILE).write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8")
        with pytest.raises(coh.CoherenceError):
            coh.audit(out, blank_path=tmp_path / "blank.jsonl",
                      filled_path=tmp_path / "filled.jsonl",
                      chunks_path=tmp_path / "chunks.jsonl",
                      control_count=1, **EXPECTED)


# ── 定点重审 + 合并 ──────────────────────────────────────────────────

def _mapping(out: Path) -> dict[str, int]:
    sel = json.loads((out / "selection-manifest.json")
                     .read_text(encoding="utf-8"))
    return {e["case_id"]: e["index"] for e in sel["mapping"]}


def _violating_world(tmp_path: Path) -> Path:
    """生成仲裁目录并把 w-002 / w-004 改为违规 verdict。"""
    out = _gen_adjudications(tmp_path)
    idx = _mapping(out)
    rows = _read_jsonl(out / adj.ADJUDICATIONS_FILE)
    for r in rows:
        if r["index"] in {idx["w-002"], idx["w-004"]}:
            r["semantic_verdict"] = "confirmed"
    (out / adj.ADJUDICATIONS_FILE).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    return out


def _recheck(tmp_path: Path, *, llm_fn=None, max_attempts: int = 3):
    out = _violating_world(tmp_path)
    coh.audit(out, blank_path=tmp_path / "blank.jsonl",
              filled_path=tmp_path / "filled.jsonl",
              chunks_path=tmp_path / "chunks.jsonl",
              control_count=1, **EXPECTED)
    if llm_fn is None:
        llm_fn = _fake_llm()
    summary = coh.recheck_and_merge(
        out, llm_fn=llm_fn, control_count=1, max_attempts=max_attempts,
        blank_path=tmp_path / "blank.jsonl",
        filled_path=tmp_path / "filled.jsonl",
        chunks_path=tmp_path / "chunks.jsonl", **EXPECTED)
    return summary, out


class TestRecheck:
    def _merged_by_cid(self, out: Path) -> dict[str, dict]:
        idx = _mapping(out)
        merged = {r["index"]: r for r in
                  _read_jsonl(out / "coherence-recheck"
                              / "merged-adjudications.jsonl")}
        return {cid: merged[i] for cid, i in idx.items()}

    def test_merged_102_rows_and_files_written(self, tmp_path):
        summary, out = _recheck(tmp_path)
        rd = out / "coherence-recheck"
        assert rd.is_dir()
        names = {"rechecks.jsonl", "merged-adjudications.jsonl",
                 "comparison-report.md", "manifest.json"}
        assert names <= {p.name for p in rd.iterdir()}
        merged = _read_jsonl(rd / "merged-adjudications.jsonl")
        assert len(merged) == 3
        assert [r["index"] for r in merged] == list(range(1, 4))
        assert summary["n_merged"] == 3

    def test_violators_rechecked_and_merged(self, tmp_path):
        summary, out = _recheck(tmp_path)
        merged = self._merged_by_cid(out)
        # 对照 w-003（未违规）保持原样
        assert merged["w-003"]["source"] == "original"
        assert merged["w-003"]["semantic_verdict"] == "confirmed"
        assert merged["w-003"]["recheck_attempts"] == 0
        # w-002 一次重审通过
        assert merged["w-002"]["source"] == "recheck"
        assert merged["w-002"]["recheck_attempts"] == 1
        assert merged["w-002"]["semantic_verdict"] == "reject"
        assert merged["w-002"]["answer_point_supports"][0]["support_level"] \
            == "unsupported"
        # w-004 重审通过
        assert merged["w-004"]["source"] == "recheck"
        assert merged["w-004"]["semantic_verdict"] == "reject"
        assert merged["w-004"]["refusal_assessment"] == "substantive_answer_exists"
        # 原仲裁文件未被改写
        rows = _read_jsonl(out / adj.ADJUDICATIONS_FILE)
        assert rows[0]["semantic_verdict"] == "confirmed"  # 仍是违规原样
        assert rows[2]["semantic_verdict"] == "confirmed"

    def test_rechecks_jsonl_records_attempts_and_failure_evidence(self, tmp_path):
        summary, out = _recheck(tmp_path)
        rechecks = _read_jsonl(out / "coherence-recheck" / "rechecks.jsonl")
        assert [r["case_id"] for r in rechecks] == ["w-002", "w-004"]
        for r in rechecks:
            assert r["attempts"]
            for a in r["attempts"]:
                assert "raw_content" in a or "parsed" in a
            assert "final" in r

    def test_third_attempt_success_uses_attempt_three(self, tmp_path):
        # w-004 前两次违规（verdict=confirmed + substantive），第三次合法
        def by_query():
            q = {c["query"]: LEGAL[c["case_id"]] for c in CASES}
            q["Does the corpus mention W?"] = [
                {"semantic_verdict": "confirmed",
                 "verdict_rationale": "x",
                 "refusal_assessment": "substantive_answer_exists",
                 "refusal_evidence": []},
                {"semantic_verdict": "confirmed",
                 "verdict_rationale": "x",
                 "refusal_assessment": "substantive_answer_exists",
                 "refusal_evidence": []},
                LEGAL["w-004"],
            ]
            return q
        summary, out = _recheck(tmp_path, llm_fn=_fake_llm(by_query()))
        merged = self._merged_by_cid(out)
        assert merged["w-004"]["recheck_attempts"] == 3
        assert merged["w-004"]["semantic_verdict"] == "reject"

    def test_three_failures_fix_to_needs_followup_with_evidence(self, tmp_path):
        def bad_query():
            q = {c["query"]: LEGAL[c["case_id"]] for c in CASES}
            # w-002 三次都输出违规（unsupported + confirmed）
            q["Is A B?"] = [
                {"semantic_verdict": "confirmed",
                 "verdict_rationale": "x",
                 "answer_point_supports": LEGAL["w-002"]
                 ["answer_point_supports"]}] * 3
            return q
        summary, out = _recheck(tmp_path, llm_fn=_fake_llm(bad_query()))
        merged = self._merged_by_cid(out)
        assert merged["w-002"]["semantic_verdict"] == "needs_followup"
        assert merged["w-002"]["source"] == "recheck"
        assert merged["w-002"]["recheck_attempts"] == 3
        assert merged["w-002"]["fixed_by_rule"] is True
        rechecks = _read_jsonl(out / "coherence-recheck" / "rechecks.jsonl")
        w002 = next(r for r in rechecks if r["case_id"] == "w-002")
        assert len(w002["attempts"]) == 3
        assert all(a["violations"] for a in w002["attempts"])
        assert w002["final"]["semantic_verdict"] == "needs_followup"
        # manifest 记录固定 case 与失败证据
        m = json.loads((out / "coherence-recheck" / "manifest.json")
                       .read_text(encoding="utf-8"))
        assert m["rechecks"]["fixed_needs_followup"] == ["w-002"]
        assert {"case_id": "w-002", "old": "confirmed",
                "new": "needs_followup"} in m["merge"]["changed"]

    def test_code_never_rewrites_verdict_directly(self, tmp_path):
        # 唯一允许的代码改写是 3 次失败后固定 needs_followup；
        # 重审通过的 case 必须来自模型输出（假模型返回 reject → merged reject）
        def bad_first_query():
            q = {c["query"]: LEGAL[c["case_id"]] for c in CASES}
            q["Is A B?"] = [dict(LEGAL["w-002"], semantic_verdict="reject",
                                 verdict_rationale="由模型重审输出")]
            return q
        summary, out = _recheck(tmp_path, llm_fn=_fake_llm(bad_first_query()))
        merged = self._merged_by_cid(out)
        assert merged["w-002"]["semantic_verdict"] == "reject"
        assert "由模型重审输出" in merged["w-002"]["verdict_rationale"]

    def test_comparison_recomputed_on_merged(self, tmp_path):
        summary, out = _recheck(tmp_path)
        comp = summary["comparison"]
        # 合并后 w-002/w-004 均 reject → 与第三轮一致 2/2
        assert comp["disputed"] == {"total": 2, "agree": 2,
                                    "disagree": 0, "uncertain": 0}
        assert comp["controls"] == {"total": 1, "confirmed": 1,
                                    "reject": 0, "needs_followup": 0}
        report = (out / "coherence-recheck" / "comparison-report.md") \
            .read_text(encoding="utf-8")
        assert "一致性重审" in report

    def test_manifest_records_shas_prompts_retries_and_diff(self, tmp_path):
        summary, out = _recheck(tmp_path)
        m = json.loads((out / "coherence-recheck" / "manifest.json")
                       .read_text(encoding="utf-8"))
        assert m["reviewer_model"] == coh.REVIEWER_MODEL
        assert m["temperature"] == 0.0
        assert len(m["original_prompt_sha256"]) == 64
        assert len(m["recheck_prompt_sha256"]) == 64
        assert m["rechecks"]["n_cases"] == 2
        assert m["rechecks"]["attempts_max"] <= 3
        assert m["merge"]["n_changed"] == 2
        assert m["merge"]["n_unchanged"] == 1
        assert set(m["outputs"]) == {"rechecks.jsonl",
                                     "merged-adjudications.jsonl",
                                     "comparison-report.md", "manifest.json"}
        assert all(len(v["sha256"]) == 64 for v in m["outputs"].values())
        assert "DeepSeek 提供方" in m["provider_note"]

    def test_manifest_self_sha_matches_content_hash(self, tmp_path):
        summary, out = _recheck(tmp_path)
        m = json.loads((out / "coherence-recheck" / "manifest.json")
                       .read_text(encoding="utf-8"))
        body = {k: v for k, v in m.items()}
        outputs = dict(body["outputs"])
        del outputs["manifest.json"]
        body["outputs"] = outputs
        recomputed = hashlib.sha256(
            json.dumps(body, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")).hexdigest()
        assert m["outputs"]["manifest.json"]["sha256"] == recomputed

    def test_model_drift_fails_closed(self, tmp_path):
        with pytest.raises(adj.AdjudicationError, match="model drift"):
            _recheck(tmp_path, llm_fn=_fake_llm(resp_model="deepseek-v4-flash"))

    def test_clean_pack_without_violations_skips_recheck(self, tmp_path):
        out = _gen_adjudications(tmp_path)
        coh.audit(out, blank_path=tmp_path / "blank.jsonl",
                  filled_path=tmp_path / "filled.jsonl",
                  chunks_path=tmp_path / "chunks.jsonl",
                  control_count=1, **EXPECTED)
        summary = coh.recheck_and_merge(
            out, llm_fn=_fake_llm(), control_count=1,
            blank_path=tmp_path / "blank.jsonl",
            filled_path=tmp_path / "filled.jsonl",
            chunks_path=tmp_path / "chunks.jsonl", **EXPECTED)
        assert summary["n_violating"] == 0
        merged = _read_jsonl(out / "coherence-recheck"
                             / "merged-adjudications.jsonl")
        assert all(r["source"] == "original" for r in merged)
        assert summary["merge"]["n_changed"] == 0

    def test_audit_file_mismatch_fails_closed(self, tmp_path):
        out = _violating_world(tmp_path)
        # 先审计（写 audit 文件），再篡改审计文件 → recheck 必须拒绝
        coh.audit(out, blank_path=tmp_path / "blank.jsonl",
                  filled_path=tmp_path / "filled.jsonl",
                  chunks_path=tmp_path / "chunks.jsonl",
                  control_count=1, **EXPECTED)
        audit_path = out / "coherence-audit.json"
        a = json.loads(audit_path.read_text(encoding="utf-8"))
        a["n_violating"] = 99
        audit_path.write_text(json.dumps(a, ensure_ascii=False, indent=1),
                              encoding="utf-8")
        with pytest.raises(coh.CoherenceError):
            coh.recheck_and_merge(
                out, llm_fn=_fake_llm(), control_count=1,
                blank_path=tmp_path / "blank.jsonl",
                filled_path=tmp_path / "filled.jsonl",
                chunks_path=tmp_path / "chunks.jsonl", **EXPECTED)


# ── 真实语料（skipif 缺失）───────────────────────────────────────────

BLANK_REAL = ROOT / "evaluation/datasets/v2/human-review/human-review-pack.jsonl"
FILLED_REAL = ROOT / "evaluation/datasets/v2/human-review" / \
    "human-review-pack.llm-filled.jsonl"
CHUNKS_REAL = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
ADJ_DIR_REAL = ROOT / "evaluation/datasets/v2/llm-semantic-adjudication"
REAL_PRESENT = BLANK_REAL.is_file() and FILLED_REAL.is_file() \
    and CHUNKS_REAL.is_file() \
    and (ADJ_DIR_REAL / "blind-input-pack.jsonl").is_file() \
    and (ADJ_DIR_REAL / adj.ADJUDICATIONS_FILE).is_file()

pytestmark = pytest.mark.skipif(not REAL_PRESENT,
                                reason="real corpus files missing")


class TestRealCorpus:
    def test_audit_covers_all_102_and_is_deterministic(self, tmp_path):
        # 修复前 blank pack（Task 12 已批准重生命前 pack；用版本化快照
        # 继续验证修复前盲包重建一致性与审计确定性）
        import v2_repair_snapshot_util as snap
        blank = snap.pre_repair_pack(tmp_path)
        coh.audit(ADJ_DIR_REAL, blank_path=blank,
                  filled_path=FILLED_REAL, chunks_path=CHUNKS_REAL,
                  control_count=20)
        a = (ADJ_DIR_REAL / "coherence-audit.json").read_bytes()
        coh.audit(ADJ_DIR_REAL, blank_path=blank,
                  filled_path=FILLED_REAL, chunks_path=CHUNKS_REAL,
                  control_count=20)
        assert (ADJ_DIR_REAL / "coherence-audit.json").read_bytes() == a
        audit = json.loads((ADJ_DIR_REAL / "coherence-audit.json")
                           .read_text(encoding="utf-8"))
        assert audit["n_total"] == 102
        assert len(audit["violations"]) == audit["n_violating"]

    def test_audit_report_lists_violators_with_rules(self):
        report = (ADJ_DIR_REAL / "coherence-report.md").read_text(
            encoding="utf-8")
        assert "一致性契约" in report
        assert "违反" in report
        assert "人工终审" in report
        assert "HUMAN_REVIEWED" not in report
