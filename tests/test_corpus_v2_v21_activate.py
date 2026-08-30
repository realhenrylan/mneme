"""Tests for scripts.corpus_v2_v21_activate — v2.1 数据集激活工具。

激活工具把人工终审 overlay 作为最新权威真值层，从 v2 草稿生成
v2.1 正式数据集。核心契约：

- fail-closed 四门：overlay manifest 状态/计数/SHA 链、草稿与 overlay
  id 双向一致、逐 case 五个真值字段一致（顺序敏感）、6 条
  final-rulings case 必须在池内；任何一门失败 → 整体报错且零输出；
- 顶层真值字段一律原样透传，唯一改动是 annotation 内三个审阅字段；
- manifest 自哈希（排除 manifest_sha256 自身字段）可独立复算；
- 纯确定性：相同输入两次 run 产物逐字节一致。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.corpus_v2_v21_activate as act


# ── 工具 ─────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                              for r in rows) + "\n", encoding="utf-8")


def _copy_inputs(tmp: Path) -> dict[str, Path]:
    """把五个冻结输入复制到 tmp，并让 overlay manifest 的 inputs 路径
    指向 tmp 副本（SHA 值保持原值）。用于精确命中单个门的篡改测试。"""
    src = {
        "draft": act.DRAFT_PATH,
        "overlay": act.OVERLAY_PATH,
        "ovm": act.OVERLAY_MANIFEST_PATH,
        "ledger": act.RULINGS_LEDGER_PATH,
        "final": act.FINAL_RULINGS_PATH,
    }
    dst = {k: tmp / v.name for k, v in src.items()}
    for k, v in src.items():
        dst[k].write_bytes(v.read_bytes())
    m = _load_json(dst["ovm"])
    m["inputs"]["draft"]["path"] = str(dst["draft"])
    if "chunks" in m["inputs"] and isinstance(m["inputs"]["chunks"], dict):
        # chunks 等其余输入保持仓库真实路径（只读复算）
        pass
    dst["ovm"].write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8")
    return dst


def _resign_ovm(ovm_path: Path, overlay_path: Path) -> None:
    """篡改 overlay 后重算其 SHA 写回 manifest 副本（跳过门 1 SHA 门，
    用于精确命中门 2/门 3）。"""
    m = _load_json(ovm_path)
    m["overlay_sha256"] = act._sha256_file(overlay_path)
    ovm_path.write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")


def _run_kwargs(paths: dict[str, Path], out: Path) -> dict:
    return {
        "out_dir": out,
        "draft_path": paths["draft"],
        "overlay_path": paths["overlay"],
        "ovm_path": paths["ovm"],
        "rulings_ledger_path": paths["ledger"],
        "final_rulings_path": paths["final"],
        "publish_path": None,  # 测试不发布仓库级 v2.1.jsonl
    }


# ── 门 1：overlay manifest 状态 / 计数 / SHA 链 ──────────────────────

def test_real_frozen_inputs_pass_all_gates():
    """仓库真实冻结输入（只读）四门全过——SHA 链完整性的基线证明。"""
    checks = act.run_checks(act.DRAFT_PATH, act.OVERLAY_PATH,
                            act.OVERLAY_MANIFEST_PATH, act.FINAL_RULINGS_PATH)
    assert checks["errors"] == []
    for gate in ("gate1_overlay_manifest", "gate2_id_sets",
                 "gate3_truth_fields", "gate4_final_rulings"):
        assert checks[gate]["passed"] is True, gate


def test_gate1_status_not_human_reviewed(tmp_path):
    paths = _copy_inputs(tmp_path)
    m = _load_json(paths["ovm"])
    m["status"] = "DRAFT"
    paths["ovm"].write_text(json.dumps(m, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    checks = act.run_checks(paths["draft"], paths["overlay"], paths["ovm"],
                            paths["final"])
    assert checks["errors"], "status 非法必须失败"
    assert "HUMAN_REVIEWED" in " ".join(checks["errors"])


def test_gate1_decision_counts_tampered_fail_closed(tmp_path):
    paths = _copy_inputs(tmp_path)
    m = _load_json(paths["ovm"])
    m["decision_counts"]["reject"] = 1  # 150/0/0 之外任何计数都不可激活
    paths["ovm"].write_text(json.dumps(m, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    checks = act.run_checks(paths["draft"], paths["overlay"], paths["ovm"],
                            paths["final"])
    assert checks["errors"]


def test_gate1_overlay_sha_drift_fail_closed(tmp_path):
    paths = _copy_inputs(tmp_path)
    ov = _load_json(paths["overlay"])
    ov["cases"][0]["reviewer"] = "tampered"  # 产物被改写
    paths["overlay"].write_text(json.dumps(ov, ensure_ascii=False) + "\n",
                                encoding="utf-8")
    checks = act.run_checks(paths["draft"], paths["overlay"], paths["ovm"],
                            paths["final"])
    assert any("overlay_sha256" in e or "漂移" in e for e in checks["errors"])


def test_gate1_input_draft_sha_drift_fail_closed(tmp_path):
    """SHA 链断裂：草稿被改一行 → manifest inputs.draft SHA 不匹配。"""
    paths = _copy_inputs(tmp_path)
    rows = _load_jsonl(paths["draft"])
    rows[0]["query"] = rows[0]["query"] + "（被篡改）"
    _write_jsonl(paths["draft"], rows)
    checks = act.run_checks(paths["draft"], paths["overlay"], paths["ovm"],
                            paths["final"])
    assert any("draft" in e and ("SHA" in e or "漂移" in e)
               for e in checks["errors"])


# ── 门 2：草稿 id 集合 == overlay case_id 集合 ───────────────────────

def test_gate2_id_set_mismatch_fail_closed(tmp_path):
    paths = _copy_inputs(tmp_path)
    ov = _load_json(paths["overlay"])
    removed = ov["cases"].pop()  # overlay 少一个 case
    paths["overlay"].write_text(json.dumps(ov, ensure_ascii=False) + "\n",
                                encoding="utf-8")
    _resign_ovm(paths["ovm"], paths["overlay"])
    checks = act.run_checks(paths["draft"], paths["overlay"], paths["ovm"],
                            paths["final"])
    assert checks["errors"]
    assert removed["case_id"] in json.dumps(checks["errors"], ensure_ascii=False)


# ── 门 3：逐 case 真值字段一致（篡改 → fail-closed）─────────────────

def test_gate3_truth_field_tampered_fail_closed(tmp_path):
    paths = _copy_inputs(tmp_path)
    ov = _load_json(paths["overlay"])
    case = ov["cases"][0]
    case["should_refuse"] = not case["should_refuse"]
    paths["overlay"].write_text(json.dumps(ov, ensure_ascii=False) + "\n",
                                encoding="utf-8")
    _resign_ovm(paths["ovm"], paths["overlay"])
    checks = act.run_checks(paths["draft"], paths["overlay"], paths["ovm"],
                            paths["final"])
    assert checks["errors"]
    joined = json.dumps(checks["errors"], ensure_ascii=False)
    assert case["case_id"] in joined and "should_refuse" in joined


def test_gate3_order_only_difference_is_recorded_and_stops(tmp_path):
    """列表仅顺序不同：内容相同也不放行，且错误如实注明顺序差异。"""
    paths = _copy_inputs(tmp_path)
    ov = _load_json(paths["overlay"])
    target = next(c for c in ov["cases"]
                  if len(c["acceptable_answer_points"]) >= 2)
    target["acceptable_answer_points"] = \
        list(reversed(target["acceptable_answer_points"]))
    paths["overlay"].write_text(json.dumps(ov, ensure_ascii=False) + "\n",
                                encoding="utf-8")
    _resign_ovm(paths["ovm"], paths["overlay"])
    checks = act.run_checks(paths["draft"], paths["overlay"], paths["ovm"],
                            paths["final"])
    assert checks["errors"], "顺序差异也必须停止"
    joined = json.dumps(checks["errors"], ensure_ascii=False)
    assert "顺序" in joined


# ── 门 4：6 条 final-rulings case 必须在池内 ─────────────────────────

def test_gate4_final_rulings_case_missing_fail_closed(tmp_path):
    paths = _copy_inputs(tmp_path)
    rows = _load_jsonl(paths["final"])
    dropped = rows.pop(0)
    _write_jsonl(paths["final"], rows)
    checks = act.run_checks(paths["draft"], paths["overlay"], paths["ovm"],
                            paths["final"])
    assert checks["errors"]
    assert dropped["case_id"] in json.dumps(checks["errors"],
                                            ensure_ascii=False)


# ── 正常 run：产物与透传契约 ─────────────────────────────────────────

def test_run_writes_products_and_truth_passthrough(tmp_path):
    out = tmp_path / "out"
    manifest = act.run(**_run_kwargs(_copy_inputs(tmp_path), out))
    assert manifest["gate_verdict"] == "ACTIVATED"

    ds_path = out / "v2.1-dataset.jsonl"
    report_path = out / "activation-report.md"
    for p in (ds_path, report_path, out / "manifest.json"):
        assert p.exists(), p

    draft = _load_jsonl(act.DRAFT_PATH)
    ds = _load_jsonl(ds_path)
    assert len(ds) == 150 == len(draft)
    draft_by_id = {r["id"]: r for r in draft}
    for row in ds:
        src = draft_by_id[row["id"]]
        # 顶层真值字段逐字段透传（原样，不重排不重算）
        for f in act.TRUTH_FIELDS:
            assert row[f] == src[f], (row["id"], f)
        # 顶层其余字段也透传（query/metadata/note/…）
        for k, v in src.items():
            if k != "annotation":
                assert row[k] == v, (row["id"], k)
        # annotation：三个审阅字段如实改写，其余保持草稿原值
        assert row["annotation"]["review_status"] == act.REVIEW_STATUS
        assert row["annotation"]["reviewed_by"] == act.REVIEWER
        assert act.ACTIVATION_VERSION in row["annotation"]["review_notes"]
        assert act.OWNER_ADJUDICATION_DATE in row["annotation"]["review_notes"]
        for keep in ("annotated_by", "annotation_version", "created_at"):
            assert row["annotation"][keep] == src["annotation"][keep], \
                (row["id"], keep)


def test_run_manifest_self_hash_recomputable(tmp_path):
    out = tmp_path / "out"
    act.run(**_run_kwargs(_copy_inputs(tmp_path), out))
    m = _load_json(out / "manifest.json")
    recorded = m.pop("manifest_sha256")
    body = json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    import hashlib
    assert hashlib.sha256(body.encode("utf-8")).hexdigest() == recorded
    # 输入 SHA 快照与真实冻结文件一致
    for key, real in (("draft", act.DRAFT_PATH),
                      ("overlay", act.OVERLAY_PATH),
                      ("overlay_manifest", act.OVERLAY_MANIFEST_PATH),
                      ("rulings_ledger", act.RULINGS_LEDGER_PATH),
                      ("final_rulings_batch2", act.FINAL_RULINGS_PATH)):
        assert m["inputs"][key]["sha256"] == act._sha256_file(real), key


def test_run_deterministic_two_runs_byte_identical(tmp_path):
    """确定性证明：两次独立 run 产物逐字节一致。"""
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    act.run(**_run_kwargs(_copy_inputs(tmp_path), out_a))
    act.run(**_run_kwargs(_copy_inputs(tmp_path), out_b))
    for name in ("v2.1-dataset.jsonl", "manifest.json",
                 "activation-report.md"):
        assert (out_a / name).read_bytes() == (out_b / name).read_bytes(), name


def test_run_fail_closed_zero_output(tmp_path):
    paths = _copy_inputs(tmp_path)
    ov = _load_json(paths["overlay"])
    ov["cases"][0]["relevance_level"] = "bogus"  # 篡改真值
    paths["overlay"].write_text(json.dumps(ov, ensure_ascii=False) + "\n",
                                encoding="utf-8")
    out = tmp_path / "out"
    with pytest.raises(act.ActivationError):
        act.run(**_run_kwargs(paths, out))
    assert not out.exists() or not any(out.iterdir()), "fail-closed 必须零输出"
