"""v2.0.10 full blind review: RED-first compatibility and safety tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import scripts.corpus_v2_v210_fresh_blind_automated_review as review


ROOT = Path(__file__).resolve().parents[1]
V210 = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.10-owner-authorized-coherence-remediation"


def _copy_candidate(tmp_path: Path) -> Path:
    dest = tmp_path / "candidate"
    shutil.copytree(V210, dest)
    return dest


def _confirmed(payload: dict) -> dict:
    return {
        "decision": "confirmed",
        "answer_point_assessments": [
            {"answer_point_index": i, "supported": True, "rationale": "direct"}
            for i in range(len(payload["answer_points"]))
        ],
        "refusal_assessment": {
            "refusal_required": bool(payload["should_refuse"]),
            "rationale": "consistent",
        },
        "rationale": "all direct",
    }


def _stub(*, reject_case_call: int | None = None):
    calls = []

    def client(messages):
        calls.append(messages)
        content = messages[-1]["content"]
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return review.MODEL, '{"probe":"ok"}', None
        if "query" not in payload:
            return review.MODEL, '{"probe":"ok"}', None
        answer = _confirmed(payload)
        if reject_case_call is not None and len(calls) == reject_case_call:
            answer["decision"] = "reject"
            answer["answer_point_assessments"][0]["supported"] = False
        return review.MODEL, json.dumps(answer, ensure_ascii=False), None

    return client, calls


def test_profile_is_explicitly_v210_and_pro_only():
    assert review.PROFILE.candidate_actor == "OWNER_AUTHORIZED_V2_0_10_COHERENCE_REMEDIATION"
    assert review.PROFILE.candidate_gate == "COHERENCE_REMEDIATION_CANDIDATE_OK"
    assert review.PROFILE.expected_case_count == 136
    assert review.PROFILE.expected_evidence_count == 148
    assert review.PROFILE.expected_answerable == 105
    assert review.PROFILE.expected_refusal_count == 31
    assert review.MODEL == "deepseek-v4-pro"
    assert review.TEMPERATURE == 0.0
    assert review.MAX_TOKENS == 8000
    assert review.THINKING_DISABLED == {"thinking": {"type": "disabled"}}


def test_preflight_accepts_v210_without_reading_v209_review_content(tmp_path):
    candidate = _copy_candidate(tmp_path)

    checks = review.preflight(candidate_dir=candidate)

    assert checks["case_count"] == 136
    assert checks["evidence_count"] == 148
    assert checks["strict_covered"] == checks["strict_passed"] == 148
    assert checks["answerable_cases"] == 105
    assert checks["refusal_cases"] == 31


def test_all_confirmed_writes_v210_overlay_and_136_case_manifest(tmp_path):
    candidate = _copy_candidate(tmp_path)
    out = tmp_path / "review"
    client, calls = _stub()

    result = review.run(out_dir=out, candidate_dir=candidate, client=client)

    assert result["gate"] == review.GATE_OK
    assert result["counts"] == {
        "case_count": 136, "evidence_count": 148, "answerable_cases": 105,
        "refusal_cases": 31, "confirmed": 136, "reject": 0,
        "needs_followup": 0, "errors": 0,
    }
    assert len(calls) == 137  # one zero-case probe plus 136 blinded cases
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["reviewed_revision"] == candidate.name
    assert manifest["gate_verdict"] == "AUTOMATED_REVIEW_136_136_CONFIRMED"
    overlay = json.loads((out / "automated-overlay.json").read_text(encoding="utf-8"))
    assert overlay["status"] == "LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_10"
    assert overlay["case_count"] == overlay["confirmed_count"] == 136


def test_one_reject_blocks_gate_and_never_writes_overlay(tmp_path):
    candidate = _copy_candidate(tmp_path)
    out = tmp_path / "review"
    client, _ = _stub(reject_case_call=2)

    result = review.run(out_dir=out, candidate_dir=candidate, client=client)

    assert result["gate"] == review.GATE_BLOCKED
    assert result["counts"]["reject"] == 1
    assert not (out / "automated-overlay.json").exists()
    assert (out / "automated-review-issues.jsonl").exists()


def test_candidate_sha_drift_stops_before_probe_or_case_call(tmp_path):
    candidate = _copy_candidate(tmp_path)
    draft = candidate / "draft-after.jsonl"
    draft.write_text(draft.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    out = tmp_path / "review"
    client, calls = _stub()

    with pytest.raises(review.ReviewError):
        review.run(out_dir=out, candidate_dir=candidate, client=client)

    assert calls == []
    assert not out.exists()


def test_base_v209_runtime_state_is_restored_after_v210_run(tmp_path):
    candidate = _copy_candidate(tmp_path)
    out = tmp_path / "review"
    client, _ = _stub()
    base_before = review._base_runtime_snapshot()

    review.run(out_dir=out, candidate_dir=candidate, client=client)

    assert review._base_runtime_snapshot() == base_before
