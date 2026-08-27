"""v2.1 契约聚焦盲审（4 条 contract error）— TDD 测试。

覆盖 owner 批示的「authorize_new_contract_focused_blind_review」路线：

- 目标集恰为 en-052 / mixed-030 / mixed-033 / zh-040（来自 v2.1 rulings
  账本 disposition=contract_blind_review_authorized 的行，不硬编码重复）；
- 盲态 payload 与 v2.0.11 targeted review 同规范（复用基座 build_payload/
  scan_payload）：不含 case_id、旧 review 结论、契约不一致诊断或「预期
  confirmed」暗示——模型不得被引导到期望答案；
- 4/4 confirmed → CONTRACT_BLIND_REVIEW_OK；任何 reject/needs_followup →
  BLOCKED（保留可审计产物），且**不自动改写任何 case 数据**——结果仅落
  审计目录；
- fail-closed：目标集漂移 / payload 泄露 / schema 契约错误时零输出或
  BLOCKED，绝不产出 confirmed 账本；
- 双构建字节一致（stub 模型调用）；manifest 自哈希；冻结资产零触碰。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

import scripts.corpus_v2_v21_contract_focus_review as cfr

FROZEN = Path("evaluation/datasets/v2/revisions/"
              "v2.0.11-owner-authorized-en048-same-source-repair")
V21_RULINGS = Path("evaluation/datasets/v2/revisions/"
                   "v2.1-owner-rulings-batch1")
CONTRACT_IDS = {"en-052", "mixed-030", "mixed-033", "zh-040"}


def _jsonl(path):
    return [json.loads(l) for l in
            Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def _confirmed_response(payload):
    n = len(payload["answer_points"])
    return {
        "decision": "confirmed",
        "answer_point_assessments": [
            {"answer_point_index": i, "supported": True,
             "rationale": "直接支撑"} for i in range(n)],
        "refusal_assessment": None,
        "rationale": "全部答案点获得证据直接支撑。",
    }


def _stub_client_all_confirmed(messages):
    # base 接口：client(messages) -> (model, content, usage)；
    # probe 与 review_case 共用同一签名，payload 不经 client 传递
    return ("stub-model", json.dumps({"probe": "ok"}, ensure_ascii=False),
            {"total_tokens": 1})


def _patch_case_responses(monkeypatch, mutate=None):
    """把 review_case 替换为确定性 stub：全 confirmed（或经 mutate 篡改）。"""
    def fake_review_case(case_id, payload, client):
        resp = _confirmed_response(payload)
        if mutate is not None:
            mutate(resp)
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
    monkeypatch.setattr(cfr.base, "review_case", fake_review_case)


def test_target_set_from_rulings_ledger():
    ids = cfr.target_set()
    assert set(ids) == CONTRACT_IDS
    assert len(ids) == 4


def test_payload_is_blind_against_expectation():
    """payload 中不得出现「预期结论」类治理信息。

    断言范围 = 全 payload 的 case-id 与 expected_decision、以及 query 的
    契约诊断词；support_spec 是统一判定规范模板（自身含「契约」等普通词，
    与 base.scan_payload 的豁免同理），不参与禁词扫描。
    """
    checks = cfr.load_inputs()
    cid = sorted(CONTRACT_IDS)[0]
    payload = cfr.build_blind_payload(checks, cid)
    text = json.dumps(payload, ensure_ascii=False).lower()
    for banned in ("en-052", "mixed-030", "mixed-033", "zh-040",
                   "expected_decision"):
        assert banned not in text, banned
    q = payload["query"].lower()
    for banned in ("contract", "契约", "diagnostic", "persistent"):
        assert banned not in q, banned
    cfr.base.scan_payload(payload)


def test_happy_path_all_confirmed_gates_ok(tmp_path, monkeypatch):
    _patch_case_responses(monkeypatch)
    out_dir = tmp_path / "contract-focus-review"
    gate = cfr.run(out_dir=out_dir)
    assert gate["gate_verdict"] == "CONTRACT_BLIND_REVIEW_OK"
    results = _jsonl(out_dir / "contract-review-results.jsonl")
    assert {r["case_id"] for r in results} == CONTRACT_IDS
    assert all(r["decision"] == "confirmed" for r in results)
    # 响应记录里保留模型原始判定（审计用），但无改写标记
    assert all(r["rewritten"] is False for r in results)


def test_any_reject_blocks_and_keeps_records(tmp_path, monkeypatch):
    def force_reject(resp):
        resp["decision"] = "reject"
    _patch_case_responses(monkeypatch, mutate=force_reject)
    out_dir = tmp_path / "contract-focus-review"
    gate = cfr.run(out_dir=out_dir)
    assert gate["gate_verdict"] == "CONTRACT_BLIND_REVIEW_BLOCKED"
    summary = json.loads(
        (out_dir / "contract-review-summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["rejected"] >= 1


def test_manifest_self_hash(tmp_path, monkeypatch):
    _patch_case_responses(monkeypatch)
    out_dir = tmp_path / "out"
    cfr.run(out_dir=out_dir)
    m = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    body = dict(m)
    recorded = body.pop("manifest_sha256")
    canonical = json.dumps(body, ensure_ascii=False, indent=1,
                           sort_keys=True) + "\n"
    assert recorded == hashlib.sha256(canonical.encode()).hexdigest()


def test_double_build_byte_identical(tmp_path, monkeypatch):
    _patch_case_responses(monkeypatch)
    d1, d2 = tmp_path / "a", tmp_path / "b"
    cfr.run(out_dir=d1)
    cfr.run(out_dir=d2)
    for name in ("contract-review-results.jsonl", "manifest.json",
                 "contract-review-summary.json"):
        assert (d1 / name).read_bytes() == (d2 / name).read_bytes()


def test_frozen_assets_byte_untouched(tmp_path, monkeypatch):
    watched = [
        V21_RULINGS / "rulings-ledger.jsonl",
        FROZEN / "targeted-re-review" / "owner-decision-pack" /
        "persistent-contract-errors.jsonl",
        FROZEN / "draft-after.jsonl",
        FROZEN / "evidence-after.jsonl",
    ]
    before = {p: p.read_bytes() for p in watched}
    _patch_case_responses(monkeypatch)
    cfr.run(out_dir=tmp_path / "out")
    assert {p: p.read_bytes() for p in watched} == before
