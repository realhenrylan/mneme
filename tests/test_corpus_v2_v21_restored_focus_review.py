"""v2.1 恢复案例密封复核（验证轮）— TDD 测试。

预注册：plans/V21-RESTORED-CASES-VERIFICATION-2026-08-27.md（先于任何
复核调用签署；判定映射不因结果调整）。

- 目标集从 rulings 账本 disposition=restored_pending_verification 推导，
  预期恰 3 条（zh-023 / multi-012 / mixed-022）；
- 双向盲态 payload 同契约聚焦盲审规范；
- 3/3 confirmed → RESTORED_VERIFICATION_OK；任一 reject/needs_followup/
  error → RESTORED_VERIFICATION_BLOCKED（保留全部可审计产物，零改写）;
- manifest 自哈希；双构建字节一致；冻结资产 byte-untouched。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.corpus_v2_v21_restored_focus_review as rfr
from tests.test_corpus_v2_v21_contract_focus_review import (
    CONTRACT_IDS,  # noqa: F401  确认相邻模块可并存
)

RESTORED_IDS = {"zh-023", "multi-012", "mixed-022"}
V21_RULINGS = Path("evaluation/datasets/v2/revisions/"
                   "v2.1-owner-rulings-batch1")


def _jsonl(path):
    return [json.loads(l) for l in
            Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def _patch_case_responses(monkeypatch, decision="confirmed"):
    def fake_review_case(case_id, payload, client):
        n = len(payload["answer_points"])
        resp = {
            "decision": decision,
            "answer_point_assessments": [
                {"answer_point_index": i, "supported": True,
                 "rationale": "直接支撑"} for i in range(n)],
            "refusal_assessment": None,
            "rationale": "全部答案点获得证据直接支撑。",
        }
        return {
            "case_id": case_id,
            "decision": resp["decision"],
            "answer_point_assessments": resp["answer_point_assessments"],
            "refusal_assessment": resp["refusal_assessment"],
            "rationale": resp["rationale"],
            "model": "stub-model",
            "payload_sha256": hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()).hexdigest(),
            "response_sha256": hashlib.sha256(
                json.dumps(resp, sort_keys=True).encode()).hexdigest(),
            "attempts": 1,
            "retries_used": 0,
            "usage": {"total_tokens": 1},
        }
    monkeypatch.setattr(rfr.base, "review_case", fake_review_case)


def test_target_set_from_ledger():
    ids = rfr.target_set()
    assert set(ids) == RESTORED_IDS and len(ids) == 3


def test_payload_blind(tmp_path, monkeypatch):
    checks = rfr.load_inputs()
    cid = sorted(RESTORED_IDS)[0]
    payload = rfr.build_blind_payload(checks, cid)
    text = json.dumps(payload, ensure_ascii=False).lower()
    for banned in ("zh-023", "multi-012", "mixed-022", *CONTRACT_IDS,
                   "restored", "推翻", "owner_decision"):
        assert banned not in text, banned
    rfr.base.scan_payload(payload)


def test_ok_gate_when_all_confirmed(tmp_path, monkeypatch):
    _patch_case_responses(monkeypatch, "confirmed")
    out_dir = tmp_path / "out"
    gate = rfr.run(out_dir=out_dir)
    assert gate["gate_verdict"] == "RESTORED_VERIFICATION_OK"
    results = _jsonl(out_dir / "restored-review-results.jsonl")
    assert {r["case_id"] for r in results} == RESTORED_IDS
    assert all(r["rewritten"] is False for r in results)


@pytest.mark.parametrize("bad", ["reject", "needs_followup"])
def test_blocked_gate_on_any_disagreement(tmp_path, monkeypatch, bad):
    state = {"flip": True}

    def fake(case_id, payload, client):
        rec = {
            "case_id": case_id,
            "decision": "confirmed",
            "model": "stub-model", "attempts": 1, "retries_used": 0,
            "payload_sha256": "x", "response_sha256": "y",
        }
        if state["flip"]:
            rec["decision"] = bad
            rec["rationale"] = "分歧"
            state["flip"] = False
        return rec
    monkeypatch.setattr(rfr.base, "review_case", fake)
    gate = rfr.run(out_dir=tmp_path / "out")
    assert gate["gate_verdict"] == "RESTORED_VERIFICATION_BLOCKED"


def test_manifest_self_hash_and_double_build(tmp_path, monkeypatch):
    _patch_case_responses(monkeypatch, "confirmed")
    d1, d2 = tmp_path / "a", tmp_path / "b"
    rfr.run(out_dir=d1)
    rfr.run(out_dir=d2)
    m = json.loads((d1 / "manifest.json").read_text(encoding="utf-8"))
    body = dict(m)
    recorded = body.pop("manifest_sha256")
    canonical = json.dumps(body, ensure_ascii=False, indent=1,
                           sort_keys=True) + "\n"
    assert recorded == hashlib.sha256(canonical.encode()).hexdigest()
    for name in ("restored-review-results.jsonl", "manifest.json",
                 "restored-review-summary.json"):
        assert (d1 / name).read_bytes() == (d2 / name).read_bytes()


def test_frozen_assets_byte_untouched(tmp_path, monkeypatch):
    watched = [
        V21_RULINGS / "rulings-ledger.jsonl",
        Path("evaluation/datasets/v2/revisions/"
             "v2.0.11-owner-authorized-en048-same-source-repair/draft-after.jsonl"),
        Path("evaluation/datasets/v2/revisions/"
             "v2.0.11-owner-authorized-en048-same-source-repair/evidence-after.jsonl"),
    ]
    before = {p: p.read_bytes() for p in watched}
    _patch_case_responses(monkeypatch, "confirmed")
    rfr.run(out_dir=tmp_path / "out")
    assert {p: p.read_bytes() for p in watched} == before
