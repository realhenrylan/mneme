"""TDD tests for the v2.0.7 owner-authorized fresh blind automated review.

Reviews all 148 cases of the v2.0.7 candidate with a blind LLM review
(deepseek-v4-pro, temperature=0.0, max_tokens=8000, thinking disabled,
max_retries=3, no fallback).  The payloads never contain case ids, chain
references or governance terms; the overlay is generated only when
148/148 are confirmed; any failure leaves zero final outputs.

All model calls are injected stubs so the tests are deterministic and offline.
"""
from __future__ import annotations

import hashlib
import json
import types
from pathlib import Path

import pytest

import scripts.corpus_v2_v207_fresh_automated_review as rp
from scripts import corpus_v2_evidence_coordinate_repair as coord

PAYLOAD_KEYS = frozenset({"query", "previous_turns", "should_refuse",
                          "acceptable_answer_points", "evidence", "chunks"})
# Governance-metadata tokens with zero occurrences in the v2 corpus chunk
# texts (verified against data/v2-corpus/chunks/chunks.jsonl), so any hit in a
# payload is a leak, never legitimate corpus content.
LEAK_TOKENS = ("case_id", "holdout", "reviewer", "rationale", "overlay",
               "blocker", "remediation", "verdict", "reranker", "v2.0.7",
               "v2.1", "candidate", "follow_up", "activation_blocked",
               "revision_status", "AUTOMATED_REVIEW", "OWNER_AUTHORIZED",
               "HUMAN_REVIEWED", "HUMAN_APPROVED", "人工审核")

OVERLAY_FILES = ("automated-reviewed-truth-overlay.json",
                 "automated-reviewed-truth-overlay-manifest.json")
BASE_FILES = frozenset({
    "automated-review-pack.jsonl", "automated-review-evidence.jsonl",
    "automated-review.jsonl", "raw-model-responses.jsonl",
    "automated-review-summary.json", "automated-review-report.md",
    "automated-review-gate-report.md", "automated-review-issues.jsonl",
    "manifest.json",
})


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _self_hash(manifest: dict) -> str:
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    return hashlib.sha256(
        (json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
    ).hexdigest()


# ── stub LLM (deterministic, offline) ─────────────────────────────────

def _resp(content: str, model: str | None = None):
    return types.SimpleNamespace(
        model=model or rp.REVIEWER_MODEL,
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))],
    )


def _rec(retries: int = 0):
    return types.SimpleNamespace(retries_used=retries)


def _review_body(payload: dict, decision: str) -> str:
    """Build a contract-valid review JSON from the payload."""
    points = payload.get("acceptable_answer_points") or []
    n_ev = len(payload.get("evidence") or [])
    assessments = [
        {"answer_point_index": i, "assessment": "directly_supported",
         "evidence_refs": [0] if n_ev else []}
        for i in range(len(points))
    ]
    if payload.get("should_refuse") is True:
        assessments = []
        refusal = "correct_refusal" if decision == "confirmed" else "incorrect_refusal"
    else:
        refusal = "not_applicable"
    return json.dumps({
        "decision": decision,
        "rationale": "stub deterministic rationale",
        "answer_point_assessments": assessments,
        "refusal_assessment": refusal,
    }, ensure_ascii=False, sort_keys=True)


def make_stub(*, reject_queries=frozenset(), garbage_queries=frozenset(),
              transport_fail_queries=frozenset(), wrong_model_queries=frozenset(),
              bad_body_queries=frozenset(), one_bad_queries=frozenset()):
    """Pro-only stub: asserts call parameters and never falls back."""
    calls: list[dict] = []
    seen_messages: list[list[dict]] = []

    def stub(call_type, messages, **kwargs):
        calls.append(kwargs)
        seen_messages.append(messages)
        # Pro-only call parameters, thinking disabled, no fallback model.
        assert kwargs["model"] == rp.REVIEWER_MODEL
        assert kwargs["temperature"] == rp.REVIEWER_TEMPERATURE
        assert kwargs["max_tokens"] == rp.REVIEWER_MAX_TOKENS
        assert kwargs["max_retries"] == rp.MAX_RETRIES
        assert kwargs["extra_body"] == rp.EXTRA_BODY
        if '"probe"' in messages[-1]["content"]:
            return _resp('{"ok": true}'), _rec()
        payload = json.loads(messages[1]["content"])  # original user payload
        q = payload["query"]
        if q in transport_fail_queries:
            raise RuntimeError("stub transport failure")
        if q in wrong_model_queries:
            return _resp(_review_body(payload, "confirmed"), model="wrong-model"), _rec()
        if q in garbage_queries:
            return _resp("this is definitely not json"), _rec()
        if q in bad_body_queries:
            return _resp('{"decision": "bogus", "rationale": ""}'), _rec()
        if q in one_bad_queries:
            if messages[-1]["content"] == messages[1]["content"]:
                # first (non-corrective) call: contract-violating body
                return _resp('{"decision": "confirmed", "rationale": "x", '
                             '"answer_point_assessments": [], '
                             '"refusal_assessment": "incorrect_refusal"}'), _rec()
            return _resp(_review_body(payload, "confirmed")), _rec()
        decision = "reject" if q in reject_queries else "confirmed"
        return _resp(_review_body(payload, decision)), _rec()

    stub.calls = calls
    stub.seen_messages = seen_messages
    return stub


@pytest.fixture(scope="module")
def reviewed(tmp_path_factory):
    """Full review with an all-confirmed stub (offline, deterministic)."""
    out = tmp_path_factory.mktemp("v207rev")
    stub = make_stub()
    result = rp.review(out_dir=out, llm_fn=stub)
    return result, out, stub


# ── constants / preflight ─────────────────────────────────────────────

def test_constants_fixed():
    assert rp.REVIEWER_IDENTITY == "LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_7"
    assert rp.REVIEWER_MODEL == "deepseek-v4-pro"
    assert rp.REVIEWER_TEMPERATURE == 0.0
    assert rp.REVIEWER_MAX_TOKENS == 8000
    assert rp.MAX_RETRIES == 3
    assert rp.EXTRA_BODY == {"thinking": {"type": "disabled"}}
    assert rp.OVERLAY_STATUS == "AUTOMATED_REVIEWED_OWNER_AUTHORIZED"
    assert "deepseek-v4-flash" in rp.FORBIDDEN_MODELS


def test_preflight_passes_on_real_candidate():
    checks = rp.preflight()
    assert checks["case_count"] == 148
    assert checks["active_evidence_count"] == 161
    assert checks["strict_validator_covered"] == 161
    assert checks["strict_validator_passed"] == 161
    assert checks["legacy_coordinate_count"] == 0
    assert checks["unresolved_count"] == 0
    assert checks["activation_blocked"] is True
    assert all(checks[k] is True for k in (
        "case_count_ok", "evidence_count_ok", "strict_ok", "legacy_ok",
        "unresolved_ok", "activation_ok", "answerable_have_evidence",
        "refusal_have_no_evidence", "inputs_unchanged", "manifest_ok"))
    quality = checks["data_quality"]
    assert quality["skill"]["available"] is False
    assert "Skill not found" in quality["skill"]["failure"]


def test_preflight_fail_closed_on_gate_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "V207_MANIFEST", tmp_path / "missing-manifest.json")
    with pytest.raises(rp.ReviewError):
        rp.preflight()


# ── pack / blind payload ──────────────────────────────────────────────

def test_pack_148_rows_sorted_unique_and_sha_locked(reviewed):
    _, out, _ = reviewed
    rows = _jsonl(out / "automated-review-pack.jsonl")
    assert len(rows) == 148
    ids = [r["case_id"] for r in rows]
    assert ids == sorted(ids) and len(set(ids)) == 148
    for row in rows:
        assert row["payload_sha256"] == rp.canonical_sha(row["payload"])


def test_payload_blind_no_case_id_no_leaks_no_chain_refs(reviewed):
    _, out, _ = reviewed
    rows = _jsonl(out / "automated-review-pack.jsonl")
    for row in rows:
        payload = row["payload"]
        assert set(payload) == PAYLOAD_KEYS
        assert "case_id" not in row["payload"]
        # recursive key scan: no identity or chain keys anywhere
        stack = [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                assert "case_id" not in node and "id" not in node
                assert "follow_up_to" not in node and "chain_id" not in node
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        for turn in payload["previous_turns"]:
            assert set(turn) == {"query"}
        # governance-metadata tokens must never appear in the payload
        blob = json.dumps(payload, ensure_ascii=False)
        for token in LEAK_TOKENS:
            assert token not in blob, f"{row['case_id']}: leak token {token!r}"
        assert row["case_id"] not in blob


def test_payload_evidence_correct_and_chunk_texts_present(reviewed):
    _, out, _ = reviewed
    rows = _jsonl(out / "automated-review-pack.jsonl")
    chunks = coord.load_chunks(rp.CHUNKS)
    for row in rows:
        payload = row["payload"]
        for ev in payload["evidence"]:
            assert set(ev) == {"chunk_id", "source_id", "raw_evidence_span", "snippet"}
            chunk = chunks[ev["chunk_id"]]
            assert chunk["source"] == ev["source_id"]
            assert ev["raw_evidence_span"] in chunk["text"]
            # snippet is the display-normalized form of the raw span
            assert ev["snippet"] == coord.display_snippet(ev["raw_evidence_span"])
            assert payload["chunks"][ev["chunk_id"]] == chunk["text"]
        if payload["should_refuse"] is True:
            assert payload["acceptable_answer_points"] == []
            assert payload["evidence"] == []
        else:
            assert payload["acceptable_answer_points"]
            assert payload["evidence"]


# ── review / overlay ──────────────────────────────────────────────────

def test_all_confirmed_generates_overlay(reviewed):
    result, out, stub = reviewed
    assert result["counts"]["confirmed"] == 148
    assert result["counts"]["reject"] == 0
    assert result["counts"]["needs_followup"] == 0
    assert result["overlay_generated"] is True
    for name in OVERLAY_FILES:
        assert (out / name).exists()
    overlay = json.loads((out / "automated-reviewed-truth-overlay.json").read_text(encoding="utf-8"))
    assert overlay["status"] == "AUTOMATED_REVIEWED_OWNER_AUTHORIZED"
    assert overlay["n_cases"] == 148
    assert len(overlay["truth_cases"]) == 148
    assert overlay["decision_counts"]["confirmed"] == 148
    assert overlay["revision_status"] == "CANDIDATE"
    assert overlay["activation_blocked"] is True
    assert overlay["human_reviewed"] is False
    assert overlay["split_reseal_required"] is True
    assert overlay["v2_1_entered"] is False
    om = json.loads((out / "automated-reviewed-truth-overlay-manifest.json").read_text(encoding="utf-8"))
    assert om["status"] == "AUTOMATED_REVIEWED_OWNER_AUTHORIZED"
    assert om["revision_status"] == "CANDIDATE"
    assert om["activation_blocked"] is True
    assert om["human_reviewed"] is False
    assert om["split_reseal_required"] is True
    assert om["v2_1_entered"] is False
    assert _sha(out / "automated-reviewed-truth-overlay.json") == om["outputs"]["overlay_sha256"]
    gate = (out / "automated-review-gate-report.md").read_text(encoding="utf-8")
    assert "AUTOMATED_REVIEWED_OWNER_AUTHORIZED" in gate


def test_any_reject_blocks_overlay(tmp_path_factory):
    pack_tmp = tmp_path_factory.mktemp("v207packq")
    rows = rp.build_pack(out_dir=pack_tmp)
    target = rows[0]  # first sorted case
    out = tmp_path_factory.mktemp("v207block")
    stub = make_stub(reject_queries={target["payload"]["query"]})
    result = rp.review(out_dir=out, llm_fn=stub)
    assert result["overlay_generated"] is False
    assert result["gate_verdict"] == "AUTOMATED_REVIEW_GATE_BLOCKED"
    for name in OVERLAY_FILES:
        assert not (out / name).exists()
    issues = _jsonl(out / "automated-review-issues.jsonl")
    assert [r["case_id"] for r in issues] == [target["case_id"]]
    assert issues[0]["decision"] == "reject"
    gate = (out / "automated-review-gate-report.md").read_text(encoding="utf-8")
    assert "AUTOMATED_REVIEW_GATE_BLOCKED" in gate


def test_transport_failure_fail_closed_zero_output(tmp_path_factory):
    pack_tmp = tmp_path_factory.mktemp("v207packt")
    rows = rp.build_pack(out_dir=pack_tmp)
    target = rows[0]
    out = tmp_path_factory.mktemp("v207fail")
    stub = make_stub(transport_fail_queries={target["payload"]["query"]})
    with pytest.raises(rp.ReviewError):
        rp.review(out_dir=out, llm_fn=stub)
    assert not out.exists() or list(out.iterdir()) == []


def test_garbage_and_bad_schema_fail_closed(tmp_path_factory):
    pack_tmp = tmp_path_factory.mktemp("v207packg")
    rows = rp.build_pack(out_dir=pack_tmp)
    qs = [r["payload"]["query"] for r in rows]
    for kind in ("garbage", "bad_body"):
        out = tmp_path_factory.mktemp(f"v207{kind}")
        stub = make_stub(**{f"{kind}_queries": {qs[0]}})
        with pytest.raises(rp.ReviewError):
            rp.review(out_dir=out, llm_fn=stub)
        assert not out.exists() or list(out.iterdir()) == []


def test_wrong_model_identity_fail_closed(tmp_path_factory):
    pack_tmp = tmp_path_factory.mktemp("v207packm")
    rows = rp.build_pack(out_dir=pack_tmp)
    out = tmp_path_factory.mktemp("v207model")
    stub = make_stub(wrong_model_queries={rows[0]["payload"]["query"]})
    with pytest.raises(rp.ReviewError):
        rp.review(out_dir=out, llm_fn=stub)
    assert not out.exists() or list(out.iterdir()) == []


def test_corrective_retry_carries_specific_error_and_recovers(tmp_path_factory):
    pack_tmp = tmp_path_factory.mktemp("v207packc")
    rows = rp.build_pack(out_dir=pack_tmp)
    target = rows[0]
    assert target["payload"]["should_refuse"] is False  # en-021 answerable
    out = tmp_path_factory.mktemp("v207corr")
    stub = make_stub(one_bad_queries={target["payload"]["query"]})
    result = rp.review(out_dir=out, llm_fn=stub)
    assert result["overlay_generated"] is True
    review_rows = _jsonl(out / "automated-review.jsonl")
    row = next(r for r in review_rows if r["case_id"] == target["case_id"])
    assert row["parse_retries"] == 1
    # the corrective prompt must carry the specific validation error
    corrective = next(m for m in stub.seen_messages if len(m) > 2)
    prompt = corrective[-1]["content"]
    assert "无法通过本地严格校验" in prompt
    assert "answerable case must use not_applicable" in prompt


def test_stub_calls_assert_pro_only_params(reviewed):
    _, _, stub = reviewed
    assert stub.calls
    for kwargs in stub.calls:
        assert kwargs["model"] == rp.REVIEWER_MODEL
        assert kwargs["temperature"] == 0.0
        assert kwargs["max_tokens"] == 8000
        assert kwargs["max_retries"] == 3
        assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_stats_conservation_and_issues_set(reviewed):
    result, out, _ = reviewed
    rows = _jsonl(out / "automated-review.jsonl")
    assert len(rows) == 148
    assert [r["case_id"] for r in rows] == sorted(r["case_id"] for r in rows)
    assert len({r["case_id"] for r in rows}) == 148
    counts = {d: sum(1 for r in rows if r["decision"] == d) for d in rp.DECISIONS}
    assert sum(counts.values()) == 148
    assert counts == result["counts"]
    issues = _jsonl(out / "automated-review-issues.jsonl")
    assert issues == [r for r in rows if r["decision"] != "confirmed"]
    summary = json.loads((out / "automated-review-summary.json").read_text(encoding="utf-8"))
    assert summary["decision_counts"] == counts
    assert summary["n_cases"] == 148
    # refusal assessment conservation with the all-confirmed stub
    refusal = [r["refusal_assessment"] for r in rows]
    assert refusal.count("correct_refusal") == 31
    assert refusal.count("not_applicable") == 117


def test_reviewer_identity_and_contract_fields_every_row(reviewed):
    _, out, _ = reviewed
    rows = _jsonl(out / "automated-review.jsonl")
    for row in rows:
        assert row["reviewer_identity"] == "LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_7"
        assert row["reviewer_type"] == "LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_7"
        assert row["model"] == rp.REVIEWER_MODEL
        assert row["temperature"] == 0.0
        assert row["max_tokens"] == 8000
        assert row["thinking_disabled"] is True
        assert row["decision"] in rp.DECISIONS
        assert row["rationale"]
        assert row["refusal_assessment"] in rp.REFUSAL_ASSESSMENTS
        assert row["prompt_sha256"] and row["response_sha256"] and row["raw_response_sha256"]
        assert row["payload_sha256"]


def test_raw_model_responses_file(reviewed):
    _, out, _ = reviewed
    raw = _jsonl(out / "raw-model-responses.jsonl")
    assert len(raw) == 148
    for row in raw:
        assert row["case_id"]
        assert isinstance(row["content"], str) and row["content"]
        assert hashlib.sha256(row["content"].encode("utf-8")).hexdigest() == row["raw_response_sha256"]


def test_validate_review_contract_rules():
    payload = {
        "query": "q", "previous_turns": [], "should_refuse": False,
        "acceptable_answer_points": ["p0", "p1"],
        "evidence": [{"chunk_id": "c", "source_id": "s",
                      "raw_evidence_span": "x", "snippet": "x"}],
        "chunks": {"c": "x"},
    }
    good = {
        "decision": "confirmed", "rationale": "ok",
        "answer_point_assessments": [
            {"answer_point_index": 0, "assessment": "directly_supported", "evidence_refs": [0]},
            {"answer_point_index": 1, "assessment": "faithful_paraphrase", "evidence_refs": [0]},
        ],
        "refusal_assessment": "not_applicable",
    }
    assert rp._validate_review(good, payload)["decision"] == "confirmed"
    bad_cases = [
        {**good, "decision": "bogus"},
        {**good, "rationale": "   "},
        {**good, "refusal_assessment": "correct_refusal"},
        {**good, "answer_point_assessments": [
            {**good["answer_point_assessments"][0], "assessment": "unsupported"}]},
        {**good, "answer_point_assessments": [
            {**good["answer_point_assessments"][0], "evidence_refs": []},
            good["answer_point_assessments"][1]]},
        {**good, "answer_point_assessments": [
            {**good["answer_point_assessments"][0], "answer_point_index": 5},
            good["answer_point_assessments"][1]]},
        {**good, "answer_point_assessments": [
            {**good["answer_point_assessments"][0], "evidence_refs": [9]},
            good["answer_point_assessments"][1]]},
        {**good, "answer_point_assessments": [good["answer_point_assessments"][0]]},  # missing coverage
        {**good, "answer_point_assessments": [
            good["answer_point_assessments"][0], good["answer_point_assessments"][0]]},  # duplicate
    ]
    for value in bad_cases:
        with pytest.raises(rp.ReviewError):
            rp._validate_review(value, payload)
    refusal_payload = {**payload, "should_refuse": True,
                       "acceptable_answer_points": [], "evidence": []}
    refusal_ok = {"decision": "confirmed", "rationale": "ok",
                  "answer_point_assessments": [],
                  "refusal_assessment": "correct_refusal"}
    assert rp._validate_review(refusal_ok, refusal_payload)["decision"] == "confirmed"
    for value in (
        {**refusal_ok, "refusal_assessment": "not_applicable"},
        {**refusal_ok, "refusal_assessment": "incorrect_refusal"},
        {**refusal_ok, "answer_point_assessments": [
            {"answer_point_index": 0, "assessment": "directly_supported", "evidence_refs": []}]},
    ):
        with pytest.raises(rp.ReviewError):
            rp._validate_review(value, refusal_payload)


def test_input_shas_unchanged_and_manifest_self_hash(reviewed):
    _, out, _ = reviewed
    v207 = json.loads(rp.V207_MANIFEST.read_text(encoding="utf-8"))
    assert v207["manifest_sha256"] == _self_hash(v207)
    for name in ("draft-after.jsonl", "evidence-after.jsonl"):
        assert v207["outputs"][name] == _sha(rp.V207 / name)
    for name, path in (("draft", rp.DRAFT), ("chunks", rp.CHUNKS),
                       ("chunk_manifest", rp.CHUNK_MANIFEST)):
        assert v207["inputs"][name] == _sha(path)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_sha256"] == _self_hash(manifest)
    for name in BASE_FILES - {"manifest.json"}:
        assert manifest["outputs"][name] == _sha(out / name)


def test_determinism_two_runs_byte_identical(tmp_path_factory):
    out1 = tmp_path_factory.mktemp("v207d1")
    out2 = tmp_path_factory.mktemp("v207d2")
    rp.review(out_dir=out1, llm_fn=make_stub())
    rp.review(out_dir=out2, llm_fn=make_stub())
    names = sorted(p.name for p in out1.iterdir())
    assert set(names) == BASE_FILES | set(OVERLAY_FILES)
    for name in names:
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()


def test_no_human_identity_or_v2_1_claims(reviewed):
    _, out, _ = reviewed
    for name in ("automated-review.jsonl", "automated-review-report.md",
                 "automated-review-gate-report.md", "automated-review-issues.jsonl",
                 "automated-reviewed-truth-overlay.json",
                 "automated-reviewed-truth-overlay-manifest.json", "manifest.json"):
        content = (out / name).read_text(encoding="utf-8")
        for forbidden in ("HUMAN_REVIEWED", "HUMAN_APPROVED", "人工审核完成"):
            assert forbidden not in content
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["revision_status"] == "CANDIDATE"
    assert manifest["activation_blocked"] is True
    assert manifest["human_reviewed"] is False
    assert manifest["split_reseal_required"] is True
    assert manifest["v2_1_entered"] is False
    assert manifest["reviewer_identity"] == "LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_7"


def test_probe_json_ok_and_failures():
    ok_stub = make_stub()
    assert rp.probe_json(llm_fn=ok_stub)["ok"] is True
    bad_stub = make_stub(garbage_queries={""})
    # probe payload must not be routed to garbage path (probe has no query key)
    assert rp.probe_json(llm_fn=bad_stub)["ok"] is True
    with pytest.raises(rp.ReviewError):
        rp.probe_json(llm_fn=lambda *a, **k: (_resp("not json"), _rec()))
    with pytest.raises(rp.ReviewError):
        rp.probe_json(llm_fn=lambda *a, **k: (_resp('{"ok": true}', model="wrong-model"), _rec()))
