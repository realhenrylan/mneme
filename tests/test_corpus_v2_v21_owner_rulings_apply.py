"""Tests for scripts.corpus_v2_v21_owner_rulings_apply — v2.1 裁决落账。

owner 已对 v2.0.11 冻结包中 22 条搁置项作出批次裁决（3 恢复 / 15 维持驳回
归档 / 4 契约聚焦盲审授权）。apply 工具的职责：

- 只读冻结 owner-decision-pack（template/triage/contract 三件 SHA 与 freeze
  manifest 记录逐一比对，任一漂移即 fail-closed 零输出）；
- 将裁决机械展开为 rulings-ledger.jsonl（owner_decision 使用模板自身词表：
  恢复=reject（推翻模型驳回）、维持=confirm、契约=authorize_new_contract_
  focused_blind_review）；
- 产出目录只允许是独立的 v2.1 修订目录，任何输入文件不得被改写；
- 非法状态（缺行/多行/kind 错位/非法处置值）一律零输出失败。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.corpus_v2_v21_owner_rulings_apply as ora

FROZEN = Path("evaluation/datasets/v2/revisions/"
              "v2.0.11-owner-authorized-en048-same-source-repair")
PACK_DIR = FROZEN / "targeted-re-review" / "owner-decision-pack"

RESTORED = {"zh-023", "multi-012", "mixed-022"}
ARCHIVED = {
    "mixed-028", "mixed-029", "zh-036", "zh-054",          # exact 但构造错位
    "en-041", "en-045", "en-051", "mixed-034", "multi-027",
    "zh-050", "zh-058",                                     # partial
    "en-040", "en-047", "zh-046", "zh-052",                 # translation
}
BLIND_REVIEW = {"en-052", "mixed-030", "mixed-033", "zh-040"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_out(out_dir: Path):
    ledger = [json.loads(l) for l in
              (out_dir / "rulings-ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    return ledger, manifest


def _verify_self_hash(manifest: dict) -> bool:
    body = dict(manifest)
    recorded = body.pop("manifest_sha256", None)
    canonical = json.dumps(body, ensure_ascii=False, indent=1,
                           sort_keys=True) + "\n"
    return recorded == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_happy_path_builds_full_rulings_ledger(tmp_path):
    out_dir = tmp_path / "v2.1-owner-rulings"
    ora.run(out_dir=out_dir)

    ledger, manifest = _load_out(out_dir)
    assert len(ledger) == 22
    by_id = {r["case_id"]: r for r in ledger}

    # 处置三分法计数与集合精确匹配
    got = {}
    for r in ledger:
        got.setdefault(r["disposition"], set()).add(r["case_id"])
    assert got["restored_pending_verification"] == RESTORED
    assert got["maintained_reject_archived"] == ARCHIVED
    assert got["contract_blind_review_authorized"] == BLIND_REVIEW

    # owner_decision 必须落在模板自身词表内且与处置一致
    for cid, r in by_id.items():
        if r["disposition"] == "restored_pending_verification":
            assert r["owner_decision"] == "reject"
        elif r["disposition"] == "maintained_reject_archived":
            assert r["owner_decision"] == "confirm"
        else:
            assert r["owner_decision"] == \
                "authorize_new_contract_focused_blind_review"

    # lineage 引用真实冻结输入 SHA
    tpl_sha = _sha(PACK_DIR / "owner-decision-template.jsonl")
    assert all(r["lineage"]["template_sha256"] == tpl_sha for r in ledger)


def test_manifest_self_hash_and_gates(tmp_path):
    out_dir = tmp_path / "v2.1-owner-rulings"
    ora.run(out_dir=out_dir)

    _, manifest = _load_out(out_dir)
    assert _verify_self_hash(manifest)
    assert manifest["gate_verdict"] == "V21_OWNER_RULINGS_APPLY_OK"
    assert manifest["counts"]["restored"] == 3
    assert manifest["counts"]["maintained_reject_archived"] == 15
    assert manifest["counts"]["contract_blind_review_authorized"] == 4


def test_fail_closed_zero_output_on_drifted_template(tmp_path, monkeypatch):
    bad = "0" * 64
    monkeypatch.setitem(ora.EXPECTED_INPUT_SHAS,
                        "owner-decision-template.jsonl", bad)
    out_dir = tmp_path / "v2.1-owner-rulings"
    with pytest.raises(ora.RulingsError):
        ora.run(out_dir=out_dir)
    assert not out_dir.exists()


def test_fail_closed_on_missing_ruling_row(tmp_path, monkeypatch):
    patched = dict(ora.RULINGS)
    patched.pop("zh-058")
    monkeypatch.setattr(ora, "RULINGS", patched)
    out_dir = tmp_path / "v2.1-owner-rulings"
    with pytest.raises(ora.RulingsError):
        ora.run(out_dir=out_dir)
    assert not out_dir.exists()


def test_fail_closed_on_kind_mismatch(tmp_path, monkeypatch):
    patched = dict(ora.RULINGS)
    patched["multi-012"] = ("authorize_new_contract_focused_blind_review",
                            "contract_blind_review_authorized")
    monkeypatch.setattr(ora, "RULINGS", patched)
    out_dir = tmp_path / "v2.1-owner-rulings"
    with pytest.raises(ora.RulingsError):
        ora.run(out_dir=out_dir)
    assert not out_dir.exists()


def test_refuses_existing_output_dir(tmp_path):
    out_dir = tmp_path / "v2.1-owner-rulings"
    out_dir.mkdir()
    with pytest.raises(ora.RulingsError):
        ora.run(out_dir=out_dir)


def test_double_build_byte_identical(tmp_path):
    d1, d2 = tmp_path / "a", tmp_path / "b"
    ora.run(out_dir=d1)
    ora.run(out_dir=d2)
    for name in ("rulings-ledger.jsonl", "manifest.json"):
        assert (d1 / name).read_bytes() == (d2 / name).read_bytes()


def test_frozen_assets_byte_untouched(tmp_path):
    watched = [
        PACK_DIR / "owner-decision-template.jsonl",
        PACK_DIR / "stable-reject-root-cause-triage.jsonl",
        PACK_DIR / "persistent-contract-errors.jsonl",
        FROZEN / "evaluation-freeze" / "freeze-summary.json",
    ]
    before = {p: (_sha(p), p.stat().st_mtime_ns) for p in watched}
    ora.run(out_dir=tmp_path / "out")
    after = {p: (_sha(p), p.stat().st_mtime_ns) for p in watched}
    assert before == after
