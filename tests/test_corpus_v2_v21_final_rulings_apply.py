"""v2.1 终裁批（batch2）——验证轮与契约盲审结果的 owner 终裁落账。

预注册链：rulings-batch1 → 验证轮预注册 §三 判定映射 → 本 apply。
- zh-023 / multi-012：RESTORED_VERIFICATION_OK（未整体达成，但两案各自
  confirmed）+ 机械证据线一致 → owner 批示 verified_active；
- mixed-022：新鲜盲审 reject 与原审同向、本质为命题双读歧义 → 退休归档
  （retired_ambiguous_phrasing）；
- en-052 / mixed-030 / mixed-033：三次独立复现持续性契约不一致 → 退休
  归档（retired_persistent_contract_error）；
- 输出为纯治理账本（零数据改写），fail-closed 同批次一。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.corpus_v2_v21_final_rulings_apply as fra

RESTORED_ACTIVE = {"zh-023", "multi-012"}
RETIRED_AMBIGUOUS = {"mixed-022"}
RETIRED_CONTRACT = {"en-052", "mixed-030", "mixed-033"}


def _read(out_dir: Path):
    ledger = [json.loads(l) for l in
              (out_dir / "final-rulings-ledger.jsonl").read_text(
                  encoding="utf-8").splitlines()]
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    return ledger, manifest


def _self_hash_ok(manifest: dict) -> bool:
    body = dict(manifest)
    recorded = body.pop("manifest_sha256")
    canonical = json.dumps(body, ensure_ascii=False, indent=1,
                           sort_keys=True) + "\n"
    return recorded == hashlib(canonical)


def hashlib(text: str) -> str:
    import hashlib as _h
    return _h.sha256(text.encode("utf-8")).hexdigest()


def test_happy_path(tmp_path):
    out_dir = tmp_path / "final"
    fra.run(out_dir=out_dir)
    ledger, manifest = _read(out_dir)
    assert len(ledger) == 6
    by_disp = {}
    for r in ledger:
        by_disp.setdefault(r["disposition"], set()).add(r["case_id"])
    assert by_disp["verified_active"] == RESTORED_ACTIVE
    assert by_disp["retired_ambiguous_phrasing"] == RETIRED_AMBIGUOUS
    assert by_disp["retired_persistent_contract_error"] == RETIRED_CONTRACT
    # 每行引用上游审计产物 SHA
    for r in ledger:
        assert r["lineage"]["rulings_template_sha256"]
        if r["case_id"] in RESTORED_ACTIVE | RETIRED_AMBIGUOUS:
            assert r["lineage"]["restored_review_results_sha256"]
        else:
            assert r["lineage"]["contract_review_results_sha256"]


def test_manifest_gates_and_self_hash(tmp_path):
    out_dir = tmp_path / "final"
    fra.run(out_dir=out_dir)
    _, manifest = _read(out_dir)
    assert manifest["gate_verdict"] == "V21_FINAL_RULINGS_APPLY_OK"
    assert manifest["counts"] == {"verified_active": 2,
                                  "retired_ambiguous_phrasing": 1,
                                  "retired_persistent_contract_error": 3}
    assert _self_hash_ok(manifest)


def test_double_build_identical(tmp_path):
    d1, d2 = tmp_path / "a", tmp_path / "b"
    fra.run(out_dir=d1)
    fra.run(out_dir=d2)
    for name in ("final-rulings-ledger.jsonl", "manifest.json"):
        assert (d1 / name).read_bytes() == (d2 / name).read_bytes()


def test_refuses_existing_out(tmp_path):
    out = tmp_path / "final"
    out.mkdir()
    with pytest.raises(fra.FinalRulingsError):
        fra.run(out_dir=out)


def test_upstream_drift_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setitem(fra.EXPECTED_INPUT_SHAS,
                        "owner-decision-template.jsonl", "0" * 64)
    with pytest.raises(fra.FinalRulingsError):
        fra.run(out_dir=tmp_path / "final")
    assert not (tmp_path / "final").exists()
