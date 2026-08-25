"""Tests for scripts.corpus_v2_llm_semantic_adjudication — blind semantic
adjudication of the v2 third-pass review disagreements with deepseek-v4-pro.

The orchestrator builds a blind input pack of 102 cases (82 third-pass
rejects + 20 hidden controls drawn deterministically from the 68
third-pass confirms), asks the model to adjudicate each case with only
query / previous_turns / should_refuse / acceptable_answer_points /
evidence / local chunk texts, then compares model verdicts to the
third-round decisions.

Blindness: model input never contains case_id, decision, reviewer, notes,
repair, cohort or any historical conclusion; the control list lives only
in the audit-side selection-manifest.

Fail-closed: exactly 150 rows in both packs with identical case-id sets,
rows identical except the three review fields, 68/82/0 decision counts,
evidence mappings valid, 102 unique blind rows, legal enums, rationale on
every row, model identity enforced, no comparison conclusions on failure.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.corpus_v2_llm_semantic_adjudication as adj
import scripts.corpus_v2_human_review_apply as hra

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
           language: str = "en", should_refuse: bool = False,
           previous_turns: list | None = None,
           points: list | None = None,
           evidence: list | None = None) -> dict:
    return {
        "case_id": case_id, "query": query, "language": language,
        "query_type": query_type, "previous_turns": previous_turns or [],
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
    _blank("c-001", query="What is X?",
           points=["X is a widget", "X costs 5"],
           evidence=[_ev(CHUNK_A, "X is a widget. X costs 5.")]),
    _blank("c-002", query="Follow up: what is X?", query_type="multi_turn",
           previous_turns=[{"case_id": "c-001", "query": "What is X?"}],
           points=["X is a widget"],
           evidence=[_ev(CHUNK_A, "X costs 5. C is D.")]),
    _blank("c-003", query="How do Y and Z combine?",
           query_type="cross_document", points=["Y and Z together"],
           evidence=[_ev(CHUNK_A, "X is a widget. X costs 5."),
                     _ev(CHUNK_B, "Y and Z together form W.", "src-b")]),
    _blank("c-004", query="Does the corpus mention Q?",
           query_type="no_answer", should_refuse=True,
           evidence=[_ev(CHUNK_B, "Y and Z together form W.", "src-b")]),
    _blank("c-005", query="Does the corpus mention R?",
           query_type="metadata", should_refuse=True, evidence=[]),
    _blank("c-006", query="Is A B?", points=["A is B"],
           evidence=[_ev(CHUNK_A, "C is D.")]),
    _blank("c-007", query="甲乙如何结合？", query_type="cross_document",
           language="zh", points=["甲乙结合"],
           evidence=[_ev(CHUNK_A, "X is a widget. X costs 5."),
                     _ev(CHUNK_B, "Y and Z together form W.", "src-b")]),
    _blank("c-008", query="语料是否提到 W?", query_type="no_answer",
           language="zh", should_refuse=True,
           evidence=[_ev(CHUNK_B, "Y and Z together form W.", "src-b")]),
]
BY_ID = {c["case_id"]: c for c in CASES}

CONFIRMED_IDS = ["c-001", "c-002", "c-003", "c-004", "c-005"]
REJECT_IDS = ["c-006", "c-007", "c-008"]


def _filled(case: dict, decision: str, reviewer: str = "LLM_ASSISTED_THIRD_PASS",
            notes: str = "third-pass note") -> dict:
    r = dict(case)
    r["human_review_decision"] = decision
    r["human_reviewer"] = reviewer
    r["human_review_notes"] = notes
    return r


FILLED = [_filled(c, "confirmed") for c in CASES if c["case_id"] in CONFIRMED_IDS] \
    + [_filled(c, "reject") for c in CASES if c["case_id"] in REJECT_IDS]


# 按包行顺序（case_id 升序）排列的预置模型输出
CANNED = [
    # c-001 confirmed, 两个答案点均 direct_snippet
    {"semantic_verdict": "confirmed", "verdict_rationale": "证据直接支持两个答案点",
     "answer_point_supports": [
         {"answer_point_index": 0, "support_level": "direct_snippet",
          "chunk_id": CHUNK_A, "excerpt": "X is a widget."},
         {"answer_point_index": 1, "support_level": "direct_snippet",
          "chunk_id": CHUNK_A, "excerpt": "X costs 5"}]},
    # c-002 confirmed, within_chunk_outside_snippet
    {"semantic_verdict": "confirmed",
     "verdict_rationale": "答案点位于 chunk 全文但不在 snippet",
     "answer_point_supports": [
         {"answer_point_index": 0, "support_level": "within_chunk_outside_snippet",
          "chunk_id": CHUNK_A, "excerpt": "X is a widget"}]},
    # c-003 confirmed, direct_snippet
    {"semantic_verdict": "confirmed", "verdict_rationale": "跨文档证据支持",
     "answer_point_supports": [
         {"answer_point_index": 0, "support_level": "direct_snippet",
          "chunk_id": CHUNK_B, "excerpt": "Y and Z together"}]},
    # c-004 confirmed, 拒答 no_answer
    {"semantic_verdict": "confirmed", "verdict_rationale": "语料确实无 Q 相关内容",
     "refusal_assessment": "no_answer",
     "refusal_evidence": [{"chunk_id": CHUNK_B,
                           "excerpt": "Y and Z together form W."}]},
    # c-005 confirmed, 拒答 no_answer、无 chunk
    {"semantic_verdict": "confirmed", "verdict_rationale": "无证据 chunk",
     "refusal_assessment": "no_answer", "refusal_evidence": []},
    # c-006 reject, unsupported
    {"semantic_verdict": "reject", "verdict_rationale": "snippet 不支持答案点",
     "answer_point_supports": [
         {"answer_point_index": 0, "support_level": "unsupported",
          "chunk_id": CHUNK_A, "excerpt": ""}]},
    # c-007 reject, unsupported
    {"semantic_verdict": "reject", "verdict_rationale": "跨文档证据不足",
     "answer_point_supports": [
         {"answer_point_index": 0, "support_level": "unsupported",
          "chunk_id": CHUNK_B, "excerpt": ""}]},
    # c-008 reject, 拒答 substantive_answer_exists
    {"semantic_verdict": "reject", "verdict_rationale": "语料存在实质答案，拒答不当",
     "refusal_assessment": "substantive_answer_exists",
     "refusal_evidence": [{"chunk_id": CHUNK_B,
                           "excerpt": "Y and Z together form W."}]},
]
CANNED_BY_QUERY = {CASES[i]["query"]: CANNED[i] for i in range(len(CASES))}


def _fake_llm(canned_by_query: dict | None = None, *,
              resp_model: str = adj.REVIEWER_MODEL,
              fail_first: set[str] | None = None):
    """工厂：返回 (resp, record) 的假 llm_fn；fail_first 的 query 首次返回
    非法 JSON，重试时返回合法输出。"""
    canned_by_query = canned_by_query if canned_by_query is not None \
        else CANNED_BY_QUERY
    calls: dict[str, int] = {}

    def llm_fn(call_type, messages, model=None, temperature=None,
               max_tokens=None):
        # 原始 user payload 在 messages[1]（重试追加消息不改变它）
        payload = json.loads(messages[1]["content"])
        query = payload["query"]
        n = calls.get(query, 0)
        calls[query] = n + 1
        content = json.dumps(canned_by_query[query], ensure_ascii=False)
        if fail_first and query in fail_first and n == 0:
            content = "NOT JSON"
        resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            model=resp_model)
        rec = SimpleNamespace(retries_used=0)
        return resp, rec

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


def _digest(cid: str) -> str:
    """独立实现的选择算法（测试侧复算）。"""
    return hashlib.sha256(
        ("v2-semantic-adjudication-v1:" + cid).encode("utf-8")).hexdigest()


# ── 选择算法 ─────────────────────────────────────────────────────────

class TestSelectControls:
    def test_returns_n_sorted_controls_from_confirmed(self):
        sel = adj.select_controls(CONFIRMED_IDS, n=2)
        assert len(sel) == 2
        assert set(sel) <= set(CONFIRMED_IDS)
        assert sel == sorted(sel)

    def test_selection_matches_independent_digest_sort(self):
        expected = sorted(CONFIRMED_IDS, key=_digest)[:2]
        assert adj.select_controls(CONFIRMED_IDS, n=2) == expected

    def test_deterministic(self):
        assert adj.select_controls(CONFIRMED_IDS, n=2) == \
            adj.select_controls(CONFIRMED_IDS, n=2)

    def test_different_salt_changes_selection(self):
        a = adj.select_controls(CONFIRMED_IDS, n=2,
                                salt="v2-semantic-adjudication-v1:")
        b = adj.select_controls(CONFIRMED_IDS, n=2, salt="test-salt-42:")
        assert a != b


# ── 盲态输入包 ───────────────────────────────────────────────────────

class TestBlindPack:
    def test_row_contains_only_six_fields(self):
        row = adj._blind_pack_row(BY_ID["c-001"],
                                  {CHUNK_A: CHUNK_A_TEXT, CHUNK_B: CHUNK_B_TEXT})
        assert set(row) == {"query", "previous_turns", "should_refuse",
                            "acceptable_answer_points", "evidence", "chunks"}

    def test_no_review_or_cohort_fields_anywhere(self):
        text = ""
        for cid in sorted(BY_ID):
            row = adj._blind_pack_row(BY_ID[cid],
                                      {CHUNK_A: CHUNK_A_TEXT,
                                       CHUNK_B: CHUNK_B_TEXT})
            text += json.dumps(row, ensure_ascii=False)
        for token in ("human_review", "LLM_ASSISTED", "case_id", "query_type",
                      "language", "relevant_source_ids", "relevance_level",
                      "decision", "reviewer", "notes", "cohort", "third_pass"):
            assert token not in text, f"盲包泄露字段: {token}"

    def test_chunks_resolved_from_corpus(self):
        row = adj._blind_pack_row(BY_ID["c-003"],
                                  {CHUNK_A: CHUNK_A_TEXT, CHUNK_B: CHUNK_B_TEXT})
        by_id = {c["chunk_id"]: c["text"] for c in row["chunks"]}
        assert by_id == {CHUNK_A: CHUNK_A_TEXT, CHUNK_B: CHUNK_B_TEXT}

    def test_should_refuse_preserved(self):
        row = adj._blind_pack_row(BY_ID["c-004"],
                                  {CHUNK_A: CHUNK_A_TEXT, CHUNK_B: CHUNK_B_TEXT})
        assert row["should_refuse"] is True

    def test_missing_chunk_fails_closed(self):
        with pytest.raises(KeyError):
            adj._blind_pack_row(BY_ID["c-001"], {})


# ── 输出解析与校验 ───────────────────────────────────────────────────

class TestParseAdjudication:
    def _parse(self, canned: dict, *, should_refuse: bool = False,
               chunk_ids=(CHUNK_A, CHUNK_B), n_points: int = 1):
        return adj._parse_adjudication(json.dumps(canned, ensure_ascii=False),
                                       should_refuse=should_refuse,
                                       chunk_ids=set(chunk_ids),
                                       n_points=n_points)

    def test_valid_answerable(self):
        d = self._parse(CANNED[0], n_points=2)
        assert d["semantic_verdict"] == "confirmed"
        assert d["refusal_assessment"] is None
        assert [s["answer_point_index"] for s in d["answer_point_supports"]] \
            == [0, 1]
        assert d["answer_point_supports"][0]["support_level"] == "direct_snippet"

    def test_answerable_multiple_chunks_per_point_allowed(self):
        # 同一答案点引用两个 chunk：只要全部点覆盖即可
        canned = {"semantic_verdict": "confirmed",
                  "verdict_rationale": "跨 chunk 证据",
                  "answer_point_supports": [
                      {"answer_point_index": 0, "support_level":
                       "faithful_paraphrase", "chunk_id": CHUNK_A,
                       "excerpt": "X is a widget"},
                      {"answer_point_index": 0, "support_level":
                       "faithful_paraphrase", "chunk_id": CHUNK_B,
                       "excerpt": "Y and Z together"},
                      {"answer_point_index": 1, "support_level":
                       "direct_snippet", "chunk_id": CHUNK_A,
                       "excerpt": "X costs 5"}]}
        d = self._parse(canned, n_points=2)
        assert d is not None
        assert len(d["answer_point_supports"]) == 3

    def test_valid_refusal_with_evidence(self):
        d = self._parse(CANNED[3], should_refuse=True, n_points=0)
        assert d["refusal_assessment"] == "no_answer"
        assert len(d["refusal_evidence"]) == 1

    def test_refusal_unclear_allows_empty_evidence(self):
        canned = {"semantic_verdict": "needs_followup",
                  "verdict_rationale": "无法确定",
                  "refusal_assessment": "unclear", "refusal_evidence": []}
        d = self._parse(canned, should_refuse=True, n_points=0)
        assert d["semantic_verdict"] == "needs_followup"

    def test_invalid_verdict_rejected(self):
        canned = dict(CANNED[0], semantic_verdict="approved")
        assert self._parse(canned, n_points=2) is None

    def test_empty_rationale_rejected(self):
        canned = dict(CANNED[0], verdict_rationale="  ")
        assert self._parse(canned, n_points=2) is None

    def test_answerable_missing_point_rejected(self):
        canned = dict(CANNED[0], answer_point_supports=CANNED[0]
                      ["answer_point_supports"][:1])
        assert self._parse(canned, n_points=2) is None

    def test_answerable_duplicate_point_rejected(self):
        canned = dict(CANNED[0], answer_point_supports=[
            dict(CANNED[0]["answer_point_supports"][0],
                 answer_point_index=0),
            dict(CANNED[0]["answer_point_supports"][0],
                 answer_point_index=0)])
        assert self._parse(canned, n_points=2) is None

    def test_invalid_support_level_rejected(self):
        s = dict(CANNED[0]["answer_point_supports"][0],
                 support_level="kinda_supported")
        canned = dict(CANNED[0], answer_point_supports=[
            s, CANNED[0]["answer_point_supports"][1]])
        assert self._parse(canned, n_points=2) is None

    def test_chunk_not_in_case_rejected(self):
        s = dict(CANNED[0]["answer_point_supports"][0],
                 chunk_id="000000000009_chunk_9")
        canned = dict(CANNED[0], answer_point_supports=[
            s, CANNED[0]["answer_point_supports"][1]])
        assert self._parse(canned, n_points=2) is None

    def test_unsupported_allows_empty_excerpt(self):
        d = self._parse(CANNED[5], n_points=1)
        assert d["answer_point_supports"][0]["support_level"] == "unsupported"

    def test_unsupported_allows_empty_or_null_chunk(self):
        canned = {"semantic_verdict": "reject",
                  "verdict_rationale": "无支持",
                  "answer_point_supports": [
                      {"answer_point_index": 0, "support_level": "unsupported",
                       "chunk_id": "", "excerpt": ""}]}
        d = self._parse(canned, n_points=1)
        assert d is not None
        assert d["answer_point_supports"][0]["chunk_id"] == ""
        canned["answer_point_supports"][0]["chunk_id"] = None
        d2 = self._parse(canned, n_points=1)
        assert d2 is not None
        assert d2["answer_point_supports"][0]["chunk_id"] == ""

    def test_answerable_with_refusal_field_normalized(self):
        canned = dict(CANNED[0], refusal_assessment="unclear")
        d = self._parse(canned, n_points=2)
        assert d is not None
        assert d["refusal_assessment"] is None

    def test_answerable_with_illegal_refusal_enum_rejected(self):
        canned = dict(CANNED[0], refusal_assessment="bogus")
        assert self._parse(canned, n_points=2) is None

    def test_refusal_missing_assessment_rejected(self):
        canned = dict(CANNED[3])
        del canned["refusal_assessment"]
        assert self._parse(canned, should_refuse=True, n_points=0) is None

    def test_refusal_with_answer_point_supports_normalized(self):
        canned = dict(CANNED[3],
                      answer_point_supports=CANNED[0]["answer_point_supports"])
        d = self._parse(canned, should_refuse=True, n_points=0)
        assert d is not None
        assert d["answer_point_supports"] == []

    def test_refusal_with_illegal_supports_rejected(self):
        canned = dict(CANNED[3], answer_point_supports="garbage")
        assert self._parse(canned, should_refuse=True, n_points=0) is None

    def test_refusal_evidence_chunk_not_in_case_rejected(self):
        canned = dict(CANNED[3], refusal_evidence=[
            {"chunk_id": "000000000009_chunk_9", "excerpt": "x"}])
        assert self._parse(canned, should_refuse=True, n_points=0) is None

    def test_refusal_nonempty_required_without_unclear(self):
        canned = dict(CANNED[3], refusal_evidence=[])
        assert self._parse(canned, should_refuse=True, n_points=0) is None


# ── 端到端 run（假模型）──────────────────────────────────────────────

def _run(tmp_path: Path, **kw):
    out = tmp_path / "out"
    llm_fn = kw.pop("llm_fn", _fake_llm())
    return adj.run(tmp_path / "blank.jsonl", tmp_path / "filled.jsonl",
                   tmp_path / "chunks.jsonl", out,
                   llm_fn=llm_fn, control_count=2,
                   expected_total=8, expected_confirmed=5,
                   expected_reject=3, expected_followup=0, **kw), out


class TestRun:
    # 盲态集合 = 3 条争议（c-006/007/008）+ 2 条对照（c-003/c-005，v1 盐
    # 确定性选中）= 5 行，按 case_id 升序为 c-003, c-005, c-006, c-007, c-008
    def test_all_five_outputs_written(self, tmp_path):
        _write_fixture(tmp_path)
        summary, out = _run(tmp_path)
        names = {"blind-input-pack.jsonl", "deepseek-v4-pro-adjudications.jsonl",
                 "selection-manifest.json", "comparison-report.md",
                 "manifest.json"}
        assert names <= {p.name for p in out.iterdir()}
        assert summary["n_cases"] == 5

    def test_blind_pack_rows_sorted_and_clean(self, tmp_path):
        _write_fixture(tmp_path)
        _, out = _run(tmp_path)
        rows = [json.loads(l) for l in
                (out / "blind-input-pack.jsonl").open(encoding="utf-8")]
        assert len(rows) == 5
        for r in rows:
            assert set(r) == {"query", "previous_turns", "should_refuse",
                              "acceptable_answer_points", "evidence", "chunks"}
        text = (out / "blind-input-pack.jsonl").read_text(encoding="utf-8")
        for token in ("human_review", "LLM_ASSISTED", "case_id", "query_type"):
            assert token not in text

    def test_adjudications_cover_all_indices_with_legal_enums(self, tmp_path):
        _write_fixture(tmp_path)
        _, out = _run(tmp_path)
        rows = [json.loads(l) for l in (out / "deepseek-v4-pro-adjudications.jsonl")
                .open(encoding="utf-8")]
        assert [r["index"] for r in rows] == list(range(1, 6))
        for r in rows:
            assert r["semantic_verdict"] in adj.VERDICTS
            assert r["verdict_rationale"].strip()
            assert r["model"] == adj.REVIEWER_MODEL

    def test_selection_manifest_audit_side_only(self, tmp_path):
        _write_fixture(tmp_path)
        _, out = _run(tmp_path)
        m = json.loads((out / "selection-manifest.json").read_text(encoding="utf-8"))
        assert len(m["controls"]) == 2
        assert set(m["controls"]) <= set(CONFIRMED_IDS)
        assert set(m["disputed"]) == set(REJECT_IDS)
        assert len(m["mapping"]) == 5
        roles = {e["role"] for e in m["mapping"]}
        assert roles == {"control", "disputed"}
        # 模型输入包中不得出现映射/角色
        pack_text = (out / "blind-input-pack.jsonl").read_text(encoding="utf-8")
        for token in ("controls", "disputed", "mapping", "role"):
            assert token not in pack_text

    def test_manifest_records_model_prompt_shas_retries(self, tmp_path):
        _write_fixture(tmp_path)
        _, out = _run(tmp_path)
        m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert m["reviewer_model"] == "deepseek-v4-pro"
        assert m["temperature"] == 0.0
        assert m["max_tokens"] == adj.MAX_TOKENS
        assert len(m["prompt_sha256"]) == 64
        assert m["selection"]["control_count"] == 2
        assert m["selection"]["disputed_count"] == 3
        assert m["selection"]["total_cases"] == 5
        assert m["inputs"]["blank_pack"]["sha256"] == \
            hra._sha256_file(tmp_path / "blank.jsonl")
        assert m["inputs"]["filled_pack"]["rows"] == 8
        assert set(m["outputs"]) == {
            "blind-input-pack.jsonl", "deepseek-v4-pro-adjudications.jsonl",
            "selection-manifest.json", "comparison-report.md", "manifest.json"}
        assert all(len(v["sha256"]) == 64 for v in m["outputs"].values())
        assert m["retries"]["parse_retries_max"] == 2
        assert "DeepSeek 提供方" in m["provider_note"]
        assert "第三轮模型身份未被历史 manifest 记录" in m["provider_note"]
        assert "不宣称模型或供应商独立性" in m["provider_note"]

    def test_comparison_disputed_agreement(self, tmp_path):
        _write_fixture(tmp_path)
        summary, out = _run(tmp_path)
        comp = summary["comparison"]
        # 82 争议全部 reject（c-006/007/008 均判 reject）
        assert comp["disputed"] == {"total": 3, "agree": 3,
                                    "disagree": 0, "uncertain": 0}
        # 对照全部 confirmed
        assert comp["controls"] == {"total": 2, "confirmed": 2,
                                    "reject": 0, "needs_followup": 0}

    def test_comparison_strata(self, tmp_path):
        _write_fixture(tmp_path)
        summary, _ = _run(tmp_path)
        s = summary["comparison"]["strata"]
        # 答案题：c-001/002/003/006/007
        assert s["answerable"]["disputed"]["total"] == 2
        assert s["answerable"]["disputed"]["agree"] == 2
        assert s["refusal"]["disputed"]["total"] == 1
        assert s["refusal"]["disputed"]["agree"] == 1
        # 跨文档：c-003（对照）+ c-007（争议）
        assert s["cross_document"]["disputed"]["total"] == 1
        assert s["cross_document"]["controls"]["total"] == 1

    def test_support_level_and_refusal_counts(self, tmp_path):
        _write_fixture(tmp_path)
        summary, _ = _run(tmp_path)
        sl = summary["comparison"]["support_levels"]
        assert sl == {"direct_snippet": 1, "within_chunk_outside_snippet": 0,
                      "faithful_paraphrase": 0, "unsupported": 2}
        ra = summary["comparison"]["refusal_assessments"]
        assert ra == {"no_answer": 1, "partial_topic_overlap_only": 0,
                      "substantive_answer_exists": 1, "unclear": 0}

    def test_report_language_and_disclaimers(self, tmp_path):
        _write_fixture(tmp_path)
        _, out = _run(tmp_path)
        text = (out / "comparison-report.md").read_text(encoding="utf-8")
        assert "DeepSeek v4 Pro 盲态机器语义审阅" in text
        assert "人工终审" in text
        assert "HUMAN_REVIEWED" not in text
        assert "不构成任何 v2.1 进入决策" in text
        assert "DeepSeek 提供方" in text
        assert "| 答案题 |" in text and "| 拒答题 |" in text \
            and "| 跨文档题 |" in text

    def test_corrective_retry_records_parse_retries(self, tmp_path):
        _write_fixture(tmp_path)
        _, out = _run(tmp_path, llm_fn=_fake_llm(
            fail_first={"Is A B?"}))
        rows = [json.loads(l) for l in (out / "deepseek-v4-pro-adjudications.jsonl")
                .open(encoding="utf-8")]
        c006 = next(r for r in rows if r["index"] == 3)
        assert c006["parse_retries"] == 1

    def test_model_drift_fails_closed(self, tmp_path):
        _write_fixture(tmp_path)
        with pytest.raises(adj.AdjudicationError, match="model drift"):
            _run(tmp_path, llm_fn=_fake_llm(resp_model="deepseek-v4-flash"))

    def test_persistent_invalid_output_fails_closed(self, tmp_path):
        _write_fixture(tmp_path)

        def bad_llm(call_type, messages, model=None, temperature=None,
                    max_tokens=None):
            resp = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(
                    content="always broken"))], model=adj.REVIEWER_MODEL)
            return resp, SimpleNamespace(retries_used=0)

        with pytest.raises(adj.AdjudicationError, match="invalid decision"):
            adj.run(tmp_path / "blank.jsonl", tmp_path / "filled.jsonl",
                    tmp_path / "chunks.jsonl", tmp_path / "out",
                    llm_fn=bad_llm, control_count=2,
                    expected_total=8, expected_confirmed=5,
                    expected_reject=3, expected_followup=0)

    def test_forbidden_model_rejected_by_code_guard(self, tmp_path):
        _write_fixture(tmp_path)
        for bad in ("gpt-5.6-sol", "deepseek-v4-flash"):
            with pytest.raises(adj.AdjudicationError, match="forbidden"):
                adj.run(tmp_path / "blank.jsonl", tmp_path / "filled.jsonl",
                        tmp_path / "chunks.jsonl", tmp_path / "out",
                        model=bad, llm_fn=_fake_llm(), control_count=2)

    def test_wrong_model_name_rejected(self, tmp_path):
        _write_fixture(tmp_path)
        with pytest.raises(adj.AdjudicationError, match="reviewer_model"):
            adj.run(tmp_path / "blank.jsonl", tmp_path / "filled.jsonl",
                    tmp_path / "chunks.jsonl", tmp_path / "out",
                    model="deepseek-v4-pro-other", llm_fn=_fake_llm(),
                    control_count=2)


# ── fail-closed：输入漂移零输出 ──────────────────────────────────────

class TestFailClosed:
    def _run_abort(self, tmp_path, mutate) -> tuple[list[str], Path]:
        _write_fixture(tmp_path)
        mutate(tmp_path)
        out = tmp_path / "out"
        try:
            adj.run(tmp_path / "blank.jsonl", tmp_path / "filled.jsonl",
                    tmp_path / "chunks.jsonl", out, llm_fn=_fake_llm(),
                    control_count=2, expected_total=8, expected_confirmed=5,
                    expected_reject=3, expected_followup=0)
        except adj.AdjudicationError as exc:
            return str(exc).split("; "), out
        raise AssertionError("expected fail-closed abort")

    def test_decision_count_drift(self, tmp_path):
        def mutate(p):
            rows = [json.loads(l) for l in (p / "filled.jsonl")
                    .open(encoding="utf-8")]
            for r in rows:
                if r["case_id"] == "c-001":
                    r["human_review_decision"] = "reject"
            (p / "filled.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                + "\n", encoding="utf-8")
        errs, out = self._run_abort(tmp_path, mutate)
        assert any("decision counts" in e for e in errs)
        assert not out.exists() or not any(out.iterdir())

    def test_row_tamper_drift(self, tmp_path):
        def mutate(p):
            rows = [json.loads(l) for l in (p / "filled.jsonl")
                    .open(encoding="utf-8")]
            for r in rows:
                if r["case_id"] == "c-002":
                    r["query"] = "tampered"
            (p / "filled.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                + "\n", encoding="utf-8")
        errs, _ = self._run_abort(tmp_path, mutate)
        assert any("篡改" in e for e in errs)

    def test_reviewer_prefix_drift(self, tmp_path):
        def mutate(p):
            rows = [json.loads(l) for l in (p / "filled.jsonl")
                    .open(encoding="utf-8")]
            for r in rows:
                r["human_reviewer"] = "HUMAN_APPROVED"
            (p / "filled.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                + "\n", encoding="utf-8")
        errs, _ = self._run_abort(tmp_path, mutate)
        assert any("LLM_ASSISTED" in e for e in errs)

    def test_missing_chunk_drift(self, tmp_path):
        def mutate(p):
            rows = [json.loads(l) for l in (p / "chunks.jsonl")
                    .open(encoding="utf-8")]
            (p / "chunks.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False)
                          for r in rows[:1]) + "\n", encoding="utf-8")
        errs, _ = self._run_abort(tmp_path, mutate)
        assert any("chunk" in e.lower() for e in errs)

    def test_duplicate_case_drift(self, tmp_path):
        def mutate(p):
            rows = [json.loads(l) for l in (p / "filled.jsonl")
                    .open(encoding="utf-8")]
            rows.append(dict(rows[0]))
            (p / "filled.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                + "\n", encoding="utf-8")
        errs, _ = self._run_abort(tmp_path, mutate)
        assert any("重复" in e for e in errs)

    def test_blank_human_field_filled(self, tmp_path):
        def mutate(p):
            rows = [json.loads(l) for l in (p / "blank.jsonl")
                    .open(encoding="utf-8")]
            rows[0]["human_review_decision"] = "confirmed"
            (p / "blank.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                + "\n", encoding="utf-8")
        errs, _ = self._run_abort(tmp_path, mutate)
        assert any("人工字段" in e for e in errs)


# ── prompt SHA ───────────────────────────────────────────────────────

class TestPromptSha:
    def test_deterministic(self, tmp_path):
        _write_fixture(tmp_path)
        rows = [adj._blind_pack_row(BY_ID[c], {CHUNK_A: CHUNK_A_TEXT,
                                               CHUNK_B: CHUNK_B_TEXT})
                for c in sorted(BY_ID)]
        assert adj._prompt_sha256(rows) == adj._prompt_sha256(rows)

    def test_changes_with_row_content(self, tmp_path):
        _write_fixture(tmp_path)
        rows = [adj._blind_pack_row(BY_ID[c], {CHUNK_A: CHUNK_A_TEXT,
                                               CHUNK_B: CHUNK_B_TEXT})
                for c in sorted(BY_ID)]
        rows2 = [dict(r, query="changed") for r in rows]
        assert adj._prompt_sha256(rows) != adj._prompt_sha256(rows2)


# ── 真实语料（skipif 缺失）───────────────────────────────────────────

BLANK_REAL = ROOT / "evaluation/datasets/v2/human-review/human-review-pack.jsonl"
FILLED_REAL = ROOT / "evaluation/datasets/v2/human-review" / \
    "human-review-pack.llm-filled.jsonl"
CHUNKS_REAL = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
REAL_PRESENT = BLANK_REAL.is_file() and FILLED_REAL.is_file() \
    and CHUNKS_REAL.is_file()

pytestmark = pytest.mark.skipif(not REAL_PRESENT,
                                reason="real corpus files missing")


class TestRealCorpus:
    def _blank(self, tmp_path: Path) -> Path:
        # 修复前 blank pack（Task 12 已批准重生命前 pack；用版本化快照
        # 继续验证修复前不变式，如 blank 与 llm-filled 逐行一致）
        import v2_repair_snapshot_util as snap
        return snap.pre_repair_pack(tmp_path)

    def test_cohort_recomputation_and_controls(self, tmp_path):
        material = adj._load_blind_material(
            self._blank(tmp_path), FILLED_REAL, CHUNKS_REAL, control_count=20)
        assert material["n_confirmed"] == 68
        assert material["n_reject"] == 82
        assert len(material["controls"]) == 20
        assert set(material["controls"]) <= set(material["confirmed_ids"])
        assert material["disputed"] == material["reject_ids"]
        assert len(material["order"]) == 102
        assert len(set(material["order"])) == 102
        assert not set(material["controls"]) & set(material["disputed"])

    def test_blind_pack_structure_no_leak(self, tmp_path):
        material = adj._load_blind_material(
            self._blank(tmp_path), FILLED_REAL, CHUNKS_REAL, control_count=20)
        rows = [adj._blind_pack_row(material["blank_by_id"][cid],
                                    material["chunk_texts"])
                for cid in material["order"]]
        assert len(rows) == 102
        for r in rows:
            assert set(r) == {"query", "previous_turns", "should_refuse",
                              "acceptable_answer_points", "evidence", "chunks"}
        text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
        for token in ("human_review", "LLM_ASSISTED", "case_id", "query_type",
                      "relevant_source_ids", "relevance_level",
                      "cohort", "third_pass"):
            assert token not in text, f"盲包泄露字段: {token}"

    def test_blind_pack_deterministic(self, tmp_path):
        material = adj._load_blind_material(
            self._blank(tmp_path), FILLED_REAL, CHUNKS_REAL, control_count=20)
        rows = [adj._blind_pack_row(material["blank_by_id"][cid],
                                    material["chunk_texts"])
                for cid in material["order"]]
        text1 = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
        material2 = adj._load_blind_material(
            self._blank(tmp_path), FILLED_REAL, CHUNKS_REAL, control_count=20)
        rows2 = [adj._blind_pack_row(material2["blank_by_id"][cid],
                                     material2["chunk_texts"])
                 for cid in material2["order"]]
        text2 = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows2)
        assert text1 == text2
