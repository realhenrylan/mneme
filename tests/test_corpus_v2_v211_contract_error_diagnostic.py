"""Phase 5-A: contract-error diagnostic + v2.0.11 evaluation freeze — TDD 测试。

覆盖任务验收：
- 4 条 contract error 目标集必须从 Phase 4 pack 与 targeted review 交叉推导，
  恰为 en-052/mixed-030/mixed-033/zh-040；任何新增/遗漏/重复 fail-closed；
- 诊断保留每一次模型尝试的原始响应（raw-model-attempts.jsonl）：匿名 run id、
  attempt 序号、模型身份、原始响应文本与 SHA、解析结果/错误、decision、逐 AP
  supported、refusal assessment、本地契约判断与冲突原因；
- 无效 JSON / schema 错误 / 契约冲突 / 身份不符 / 传输失败均有记录；
- 绝不调用其余 18 条 case；不因旧 contract error 预设 confirmed；
- 18 条 deferred 恰好覆盖 reject 集，且不改 Phase 4 owner 模板；
- candidate / targeted review / Phase 4 pack 前后字节不变；
- 两次 stub 构建逐字节一致；两个 manifest self-hash / inputs / outputs SHA；
- 禁止产物扫描；预检漂移零输出。
"""

import hashlib
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import corpus_v2_v211_contract_error_diagnostic as dg  # noqa: E402

REV = ROOT / "evaluation/datasets/v2/revisions"
V211 = REV / "v2.0.11-owner-authorized-en048-same-source-repair"
V210 = REV / "v2.0.10-owner-authorized-coherence-remediation"
V208 = REV / "v2.0.8-owner-authorized-semantic-quality-remediation"
CHUNKS_PATH = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST_PATH = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT_PATH = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"

ERROR_CASES = ["en-052", "mixed-030", "mixed-033", "zh-040"]
REJECT_IDS = [
    "en-040", "en-041", "en-045", "en-047", "en-051",
    "mixed-022", "mixed-028", "mixed-029", "mixed-034",
    "multi-012", "multi-027",
    "zh-023", "zh-036", "zh-046", "zh-050", "zh-052", "zh-054", "zh-058",
]


# ── helpers ─────────────────────────────────────────────────────────────

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(path: Path):
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _tamper_manifest(path: Path, mutate) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1,
                               sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")


def _tamper_jsonl(path: Path, mutate_rows) -> None:
    rows = [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = mutate_rows(rows)
    path.write_text("".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")) + "\n" for r in rows),
        encoding="utf-8", newline="\n")


@pytest.fixture()
def inputs(tmp_path):
    shutil.copytree(V211, tmp_path / "v211")
    shutil.copytree(V210, tmp_path / "v210")
    for src, name in ((CHUNKS_PATH, "chunks.jsonl"),
                      (CHUNK_MANIFEST_PATH, "chunk-manifest.json"),
                      (CURRENT_DRAFT_PATH, "current-draft.jsonl"),
                      (V208 / "translation-equivalence-policy.md",
                       "translation-equivalence-policy.md"),
                      (V208 / "translation-equivalence-policy-ledger.jsonl",
                       "translation-equivalence-policy-ledger.jsonl")):
        shutil.copy2(src, tmp_path / name)
    return tmp_path


def _payload_sha_map(cand: Path, target_ids: list[str]) -> dict[str, str]:
    draft = _jsonl(cand / "draft-after.jsonl")
    evidence = _jsonl(cand / "evidence-after.jsonl")
    chunks = dg._load_chunks(ROOT / CHUNKS_PATH)
    by_id = {row["id"]: row for row in draft}
    ev_per_case: dict[str, list[dict]] = defaultdict(list)
    for e in evidence:
        ev_per_case[e["case_id"]].append(e)
    return {cid: dg._sha256_text(dg._payload_text(
        dg.build_payload(by_id[cid], ev_per_case.get(cid, []), chunks)))
        for cid in target_ids}


def _valid_response(payload: dict, decision: str, ap_support=None) -> str:
    n = len(payload["answer_points"])
    if ap_support is None:
        ap_support = [decision == "confirmed"] * n
    ass = [{"answer_point_index": i, "supported": ap_support[i],
            "rationale": "stub"} for i in range(n)]
    ra = {"refusal_required": bool(payload.get("should_refuse", False)),
          "rationale": "stub"}
    return json.dumps({"decision": decision,
                       "answer_point_assessments": ass,
                       "refusal_assessment": ra,
                       "rationale": "stub rationale"}, ensure_ascii=False)


def make_stub(cand: Path, sequences: dict[str, list], probe_model="deepseek-v4-pro"):
    """sequences: {case_id: [entry, ...]}，entry ∈
    ("ok", decision) | ("conflict", decision) | ("schema",) | ("bad_json",) |
    ("wrong_model", decision) | ("raise", exc)；
    响应在运行时按真实盲态 payload 构造（AP 数量/refusal 与实际一致）；
    未注册 payload → AssertionError（绝不调用其余 18 条）。"""
    payload_shas = _payload_sha_map(cand, list(sequences))
    sha_to_cid = {h: cid for cid, h in payload_shas.items()}
    counters = {cid: 0 for cid in sequences}

    def client(messages):
        content = messages[0]["content"]
        if '"probe"' in content:
            return (probe_model, '{"probe": "ok"}', None)
        cid = sha_to_cid.get(dg._sha256_text(content))
        if cid is None:
            raise AssertionError(
                f"unexpected payload — would be a non-target case: {content[:80]}")
        i = counters[cid]
        counters[cid] = i + 1
        entries = sequences[cid]
        if i >= len(entries):
            raise AssertionError(f"case {cid} called {i + 1} times "
                                 f"(registered {len(entries)})")
        payload = json.loads(content)
        kind = entries[i][0]
        arg = entries[i][1] if len(entries[i]) > 1 else None
        if kind == "raise":
            raise arg
        if kind == "bad_json":
            return (probe_model, "{not valid json", None)
        if kind == "schema":
            return (probe_model, '{"decision": "confirmed"}', None)
        if kind == "wrong_model":
            return ("some-other-model",
                    _valid_response(payload, arg or "confirmed"), None)
        if kind == "conflict":
            # reject/needs_followup 且全部 AP supported、refusal 一致 →
            # 本地契约冲突（reject without any disagreement）
            n = len(payload["answer_points"])
            return (probe_model,
                    _valid_response(payload, arg or "reject",
                                    ap_support=[True] * n), None)
        return (probe_model, _valid_response(payload, arg or "confirmed"), None)

    return client, counters


def _run_diag(tmp_path, stub, out_name="diag", cand_dir=None):
    cand = cand_dir or tmp_path / "v211"
    out = tmp_path / out_name
    result = dg.run_diagnose(
        out_dir=out,
        candidate_dir=cand,
        review_dir=cand / "targeted-re-review",
        pack_dir=cand / "targeted-re-review" / "owner-decision-pack",
        v210_dir=tmp_path / "v210",
        chunks_path=tmp_path / "chunks.jsonl",
        chunk_manifest_path=tmp_path / "chunk-manifest.json",
        current_draft_path=tmp_path / "current-draft.jsonl",
        trans_policy_path=tmp_path / "translation-equivalence-policy.md",
        trans_ledger_path=tmp_path / "translation-equivalence-policy-ledger.jsonl",
        client=stub)
    return result, out


def _run_freeze(tmp_path, out_name="freeze", diag_dir=None):
    out = tmp_path / out_name
    result = dg.run_freeze(
        out_dir=out,
        candidate_dir=tmp_path / "v211",
        review_dir=tmp_path / "v211" / "targeted-re-review",
        pack_dir=tmp_path / "v211" / "targeted-re-review" / "owner-decision-pack",
        diagnostic_dir=diag_dir or tmp_path / "diag",
        v210_dir=tmp_path / "v210",
        chunks_path=tmp_path / "chunks.jsonl",
        chunk_manifest_path=tmp_path / "chunk-manifest.json",
        current_draft_path=tmp_path / "current-draft.jsonl",
        trans_policy_path=tmp_path / "translation-equivalence-policy.md",
        trans_ledger_path=tmp_path / "translation-equivalence-policy-ledger.jsonl")
    return result, out


# ── 1. 常量与输入存在性 ────────────────────────────────────────────────

def test_constants():
    assert dg.MODEL == "deepseek-v4-pro"
    assert dg.TEMPERATURE == 0.0
    assert dg.MAX_TOKENS == 8000
    assert dg.MAX_RETRIES == 3
    assert dg.THINKING_DISABLED == {"thinking": {"type": "disabled"}}
    assert dg.ERROR_CASES == tuple(ERROR_CASES)
    assert dg.GATE_COMPLETE == "CONTRACT_ERROR_DIAGNOSTIC_COMPLETE"
    assert dg.GATE_FROZEN == "EVALUATION_BASELINE_FROZEN"
    assert len(dg.DIAG_OUTPUT_FILES) == 8
    assert len(dg.FREEZE_OUTPUT_FILES) == 4
    assert "raw-model-attempts.jsonl" in dg.DIAG_OUTPUT_FILES
    assert "manifest.json" in dg.DIAG_OUTPUT_FILES and \
        "manifest.json" in dg.FREEZE_OUTPUT_FILES


def test_real_input_paths_exist():
    assert (V211 / "manifest.json").is_file()
    assert (V211 / "targeted-re-review" / "manifest.json").is_file()
    assert (V211 / "targeted-re-review" / "owner-decision-pack" /
            "manifest.json").is_file()


# ── 2. 目标集交叉推导 ──────────────────────────────────────────────────

def test_derive_error_cases_exact(inputs):
    pack = inputs / "v211" / "targeted-re-review" / "owner-decision-pack"
    review = inputs / "v211" / "targeted-re-review"
    derived = dg.derive_error_cases(pack_dir=pack, review_dir=review)
    assert derived == ERROR_CASES
    assert len(derived) == len(set(derived)) == 4
    # 三源交叉：pack errors / review issues error 行 / pack 模板 contract 行
    pack_errs = {r["case_id"] for r in
                 _jsonl(pack / "persistent-contract-errors.jsonl")}
    issue_errs = {r["case_id"] for r in _jsonl(review / "targeted-review-issues.jsonl")
                  if r["kind"] == "error"}
    template_errs = {r["case_id"] for r in
                     _jsonl(pack / "owner-decision-template.jsonl")
                     if r["kind"] == "persistent_model_output_contract_inconsistency"}
    assert pack_errs == issue_errs == template_errs == set(ERROR_CASES)


def test_derive_fail_closed_on_missing(inputs):
    pack = inputs / "v211" / "targeted-re-review" / "owner-decision-pack"
    review = inputs / "v211" / "targeted-re-review"
    _tamper_jsonl(pack / "persistent-contract-errors.jsonl",
                  lambda rows: [r for r in rows if r["case_id"] != "en-052"])
    with pytest.raises(dg.DiagnosticError):
        dg.derive_error_cases(pack_dir=pack, review_dir=review)


def test_derive_fail_closed_on_duplicate(inputs):
    pack = inputs / "v211" / "targeted-re-review" / "owner-decision-pack"
    review = inputs / "v211" / "targeted-re-review"
    _tamper_jsonl(pack / "persistent-contract-errors.jsonl",
                  lambda rows: rows + [dict(rows[0])])
    with pytest.raises(dg.DiagnosticError):
        dg.derive_error_cases(pack_dir=pack, review_dir=review)


def test_derive_fail_closed_on_extra(inputs):
    pack = inputs / "v211" / "targeted-re-review" / "owner-decision-pack"
    review = inputs / "v211" / "targeted-re-review"
    _tamper_jsonl(pack / "persistent-contract-errors.jsonl",
                  lambda rows: rows + [{"case_id": "en-040"}])
    with pytest.raises(dg.DiagnosticError):
        dg.derive_error_cases(pack_dir=pack, review_dir=review)


# ── 3. 预检与 fail-closed ──────────────────────────────────────────────

def test_preflight_passes(inputs):
    checks = dg.preflight_diagnose(
        candidate_dir=inputs / "v211",
        review_dir=inputs / "v211" / "targeted-re-review",
        pack_dir=inputs / "v211" / "targeted-re-review" / "owner-decision-pack",
        v210_dir=inputs / "v210",
        chunks_path=inputs / "chunks.jsonl",
        chunk_manifest_path=inputs / "chunk-manifest.json",
        current_draft_path=inputs / "current-draft.jsonl",
        trans_policy_path=inputs / "translation-equivalence-policy.md",
        trans_ledger_path=inputs / "translation-equivalence-policy-ledger.jsonl")
    assert checks["strict_covered"] == checks["strict_passed"] == 149
    assert checks["error_ids"] == ERROR_CASES
    assert checks["reject_ids"] == REJECT_IDS


def _assert_fail_closed(tmp_path, mutation, out_name="diag", **kwargs):
    mutation()
    out = tmp_path / out_name
    stub, _ = make_stub(tmp_path / "v211", {cid: [("ok", "confirmed")]
                                            for cid in ERROR_CASES})
    with pytest.raises(dg.DiagnosticError):
        _run_diag(tmp_path, stub, out_name=out_name, **kwargs)
    assert not out.exists()


def test_fail_closed_candidate_manifest(inputs):
    _assert_fail_closed(
        inputs,
        lambda: _tamper_manifest(inputs / "v211" / "manifest.json",
                                 lambda m: m.update({"gate_verdict": "X"})))


def test_fail_closed_review_manifest(inputs):
    _assert_fail_closed(
        inputs,
        lambda: _tamper_manifest(
            inputs / "v211" / "targeted-re-review" / "manifest.json",
            lambda m: m.update({"gate_verdict": "TARGETED_REVIEW_OK"})))


def test_fail_closed_pack_manifest(inputs):
    _assert_fail_closed(
        inputs,
        lambda: _tamper_manifest(
            inputs / "v211" / "targeted-re-review" / "owner-decision-pack" /
            "manifest.json",
            lambda m: m["counts"].update({"reject": 17})))


def test_fail_closed_owner_template_not_empty(inputs):
    def mutate():
        _tamper_jsonl(
            inputs / "v211" / "targeted-re-review" / "owner-decision-pack" /
            "owner-decision-template.jsonl",
            lambda rows: [dict(r, owner_decision="confirmed")
                          if r["case_id"] == "en-040" else r for r in rows])
    _assert_fail_closed(inputs, mutate)


def test_fail_closed_forbidden_artifact(inputs):
    def mutate():
        (inputs / "v211" / "overlay-probe.json").write_text(
            "{}", encoding="utf-8", newline="\n")
    _assert_fail_closed(inputs, mutate)


def test_fail_closed_out_dir_exists(inputs):
    out = inputs / "out"
    out.mkdir()
    stub, _ = make_stub(inputs / "v211", {})
    with pytest.raises(dg.DiagnosticError):
        _run_diag(inputs, stub, out_name="out")
    assert list(out.iterdir()) == []


# ── 4. 诊断运行（stub）─────────────────────────────────────────────────

def _all_confirmed_sequences():
    return {cid: [("ok", "confirmed")] for cid in ERROR_CASES}


def test_run_all_confirmed(inputs):
    stub, counters = make_stub(inputs / "v211", _all_confirmed_sequences())
    result, out = _run_diag(inputs, stub)
    assert result["gate"] == dg.GATE_COMPLETE
    assert result["counts"]["resolved"] == 4
    assert result["counts"]["contract_error"] == 0
    results = {r["case_id"]: r for r in
               _jsonl(out / "contract-error-diagnostic-results.jsonl")}
    for cid in ERROR_CASES:
        assert results[cid]["status"] == "resolved"
        assert results[cid]["decision"] == "confirmed"
        assert results[cid]["attempts"] == 1
        assert results[cid]["resolved"] is True
        assert results[cid]["is_acceptance"] is False
    raw = _jsonl(out / "raw-model-attempts.jsonl")
    assert len(raw) == 4
    assert all(r["parse_result"] == "ok" for r in raw)
    assert (out / "contract-error-diagnostic-issues.jsonl").read_text(
        encoding="utf-8").strip() == "" or \
        len(_jsonl(out / "contract-error-diagnostic-issues.jsonl")) == 0


def test_raw_attempts_record_everything(inputs):
    stub, _ = make_stub(inputs / "v211", _all_confirmed_sequences())
    _, out = _run_diag(inputs, stub)
    raw = _jsonl(out / "raw-model-attempts.jsonl")
    for row in raw:
        assert row["case_run_id"].startswith("run-")
        assert row["attempt"] == 1
        assert row["model"] == "deepseek-v4-pro"
        assert row["raw_response_text"]
        assert row["raw_response_sha256"] == hashlib.sha256(
            row["raw_response_text"].encode("utf-8")).hexdigest()
        assert row["parse_result"] == "ok"
        assert row["parse_error"] is None
        assert row["decision"] == "confirmed"
        assert row["answer_point_supported"] and \
            all(row["answer_point_supported"])
        assert row["refusal_assessment"]["refusal_required"] is False
        assert row["local_contract_judgement"] == "ok"
        assert row["contract_conflict_reason"] is None
        assert "usage" in row


def test_contract_conflict_persists(inputs):
    sequences = {cid: [("conflict", "reject")] * 4 for cid in ERROR_CASES}
    stub, counters = make_stub(inputs / "v211", sequences)
    result, out = _run_diag(inputs, stub)
    assert result["counts"]["contract_error"] == 4
    results = {r["case_id"]: r for r in
               _jsonl(out / "contract-error-diagnostic-results.jsonl")}
    for cid in ERROR_CASES:
        assert results[cid]["status"] == "contract_error"
        assert results[cid]["attempts"] == 4
        assert results[cid]["decision"] is None
    raw = _jsonl(out / "raw-model-attempts.jsonl")
    assert len(raw) == 16
    assert all(r["parse_result"] == "contract_conflict" for r in raw)
    assert all("without any disagreement" in r["contract_conflict_reason"]
               for r in raw)
    issues = _jsonl(out / "contract-error-diagnostic-issues.jsonl")
    assert [i["case_id"] for i in issues] == ERROR_CASES


def test_invalid_json_first_then_valid(inputs):
    sequences = {cid: [("bad_json",), ("ok", "confirmed")]
                 for cid in ERROR_CASES}
    stub, counters = make_stub(inputs / "v211", sequences)
    result, out = _run_diag(inputs, stub)
    assert result["counts"]["resolved"] == 4
    results = {r["case_id"]: r for r in
               _jsonl(out / "contract-error-diagnostic-results.jsonl")}
    for cid in ERROR_CASES:
        assert results[cid]["attempts"] == 2
    raw = _jsonl(out / "raw-model-attempts.jsonl")
    assert len(raw) == 8
    assert [r["parse_result"] for r in raw] == \
        ["invalid_json", "ok"] * 4
    assert raw[0]["raw_response_text"] == "{not valid json"


def test_schema_error_recorded(inputs):
    sequences = {cid: [("schema",), ("ok", "confirmed")]
                 for cid in ERROR_CASES}
    stub, _ = make_stub(inputs / "v211", sequences)
    _, out = _run_diag(inputs, stub)
    raw = _jsonl(out / "raw-model-attempts.jsonl")
    assert raw[0]["parse_result"] == "schema_error"
    assert raw[0]["local_contract_judgement"] == "invalid"
    assert raw[0]["parse_error"]


def test_identity_mismatch_blocked(inputs):
    sequences = {cid: [("wrong_model", "confirmed")] * 4
                 for cid in ERROR_CASES}
    stub, _ = make_stub(inputs / "v211", sequences)
    result, out = _run_diag(inputs, stub)
    assert result["counts"]["identity_blocked"] == 4
    results = {r["case_id"]: r for r in
               _jsonl(out / "contract-error-diagnostic-results.jsonl")}
    for cid in ERROR_CASES:
        assert results[cid]["status"] == "identity_blocked"
        assert results[cid]["attempts"] == 4
    raw = _jsonl(out / "raw-model-attempts.jsonl")
    assert all(r["parse_result"] == "identity_mismatch" for r in raw)


def test_transport_failure_blocked(inputs):
    sequences = {cid: [("raise", TimeoutError("stub timeout"))] * 4
                 for cid in ERROR_CASES}
    stub, _ = make_stub(inputs / "v211", sequences)
    result, out = _run_diag(inputs, stub)
    assert result["counts"]["transport_blocked"] == 4
    raw = _jsonl(out / "raw-model-attempts.jsonl")
    assert len(raw) == 16
    assert all(r["parse_result"] == "transport_error" for r in raw)
    assert all(r["raw_response_text"] is None for r in raw)
    issues = _jsonl(out / "contract-error-diagnostic-issues.jsonl")
    assert all(i["status"] == "transport_blocked" for i in issues)


def test_does_not_call_other_18_cases(inputs):
    sequences = _all_confirmed_sequences()
    stub, counters = make_stub(inputs / "v211", sequences)
    _, out = _run_diag(inputs, stub)
    assert set(counters) == set(ERROR_CASES)
    assert sum(counters.values()) == 4
    assert not (out / "contract-error-diagnostic-results.jsonl").read_text(
        encoding="utf-8").count("en-040")


def test_manual_reject_recorded_not_rewritten(inputs):
    """合法 reject（有分歧）被如实记录，不自动改成 confirmed。"""
    sequences = {cid: [("ok", "confirmed")] for cid in ERROR_CASES}
    sequences["en-052"] = [("ok", "reject")]
    stub, _ = make_stub(inputs / "v211", sequences)
    result, out = _run_diag(inputs, stub)
    results = {r["case_id"]: r for r in
               _jsonl(out / "contract-error-diagnostic-results.jsonl")}
    assert results["en-052"]["status"] == "resolved"
    assert results["en-052"]["decision"] == "reject"
    assert result["counts"]["resolved"] == 4


def test_double_build_byte_identical(inputs):
    stub1, _ = make_stub(inputs / "v211", _all_confirmed_sequences())
    _, out1 = _run_diag(inputs, stub1, out_name="diag1")
    stub2, _ = make_stub(inputs / "v211", _all_confirmed_sequences())
    _, out2 = _run_diag(inputs, stub2, out_name="diag2")
    for name in dg.DIAG_OUTPUT_FILES:
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes(), name


def test_manifest_self_hash_and_outputs(inputs):
    stub, _ = make_stub(inputs / "v211", _all_confirmed_sequences())
    _, out = _run_diag(inputs, stub)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert dg._verify_self_hash(manifest)
    for name, digest in manifest["outputs"].items():
        assert _sha(out / name) == digest


def test_manifest_inputs_match_disk(inputs):
    stub, _ = make_stub(inputs / "v211", _all_confirmed_sequences())
    _, out = _run_diag(inputs, stub)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    paths = {
        "candidate-manifest.json": inputs / "v211" / "manifest.json",
        "pack-manifest.json": inputs / "v211" / "targeted-re-review" /
            "owner-decision-pack" / "manifest.json",
        "review-manifest.json": inputs / "v211" / "targeted-re-review" /
            "manifest.json",
        "chunks.jsonl": inputs / "chunks.jsonl",
    }
    for name, path in paths.items():
        assert manifest["inputs"][name] == _sha(path), name


def test_inputs_unchanged_after_diag(inputs):
    before = {str(p.relative_to(inputs)): _sha(p)
              for p in inputs.rglob("*") if p.is_file()}
    stub, _ = make_stub(inputs / "v211", _all_confirmed_sequences())
    _run_diag(inputs, stub)
    after = {str(p.relative_to(inputs)): _sha(p) for p in
             inputs.rglob("*") if p.is_file() and "diag" not in p.parts}
    assert before == after


def test_declarations_not_acceptance(inputs):
    stub, _ = make_stub(inputs / "v211", _all_confirmed_sequences())
    _, out = _run_diag(inputs, stub)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    d = manifest["declarations"]
    assert d["is_review_acceptance"] is False
    assert d["targeted_review_blocked_unchanged"] is True
    assert d["llm_called"] is True
    assert d["no_fallback"] is True
    assert d["blind_payload"] is True
    assert d["model_identity_verified"] is True
    assert manifest["gate_verdict"] == dg.GATE_COMPLETE
    report = (out / "contract-error-diagnostic-report.md").read_text(
        encoding="utf-8")
    assert "不是 review acceptance" in report or \
        "not review acceptance" in report.lower()


def test_data_quality_five_dims(inputs):
    stub, _ = make_stub(inputs / "v211", _all_confirmed_sequences())
    _, out = _run_diag(inputs, stub)
    dq = json.loads((out / "data-quality-report.json").read_text(
        encoding="utf-8"))
    for dim in ("completeness", "uniqueness", "referential_integrity",
                "continuity", "consistency"):
        assert dq[dim]["status"] == "ok"
    assert dq["skill_note"]


# ── 5. 冻结 ─────────────────────────────────────────────────────────────

def _freeze_inputs(tmp_path):
    """先跑一次 stub 诊断（全 confirmed），再冻结。"""
    stub, _ = make_stub(tmp_path / "v211", _all_confirmed_sequences())
    _run_diag(tmp_path, stub, out_name="diag")
    return _run_freeze(tmp_path)


def test_freeze_deferred_18_rows(inputs):
    _, out = _freeze_inputs(inputs)
    rows = _jsonl(out / "deferred-owner-decisions.jsonl")
    assert len(rows) == 18
    assert [r["case_id"] for r in rows] == REJECT_IDS
    for row in rows:
        assert row["owner_decision"] == "deferred"
        assert "无 candidate 数据动作" in row["decision_note"]
        assert "v2.1" in row["decision_note"]
    # 不含 4 个 error case
    assert not any(r["case_id"] in ERROR_CASES for r in rows)


def test_freeze_does_not_modify_owner_template(inputs):
    pack_tpl = inputs / "v211" / "targeted-re-review" / "owner-decision-pack" / \
        "owner-decision-template.jsonl"
    before = _sha(pack_tpl)
    _, out = _freeze_inputs(inputs)
    assert _sha(pack_tpl) == before
    rows = _jsonl(pack_tpl)
    assert all(r["owner_decision"] == "" and r["owner_reviewer"] == "" and
               r["owner_notes"] == "" for r in rows)


def test_frozen_baseline_md(inputs):
    _, out = _freeze_inputs(inputs)
    md = (out / "FROZEN_EVALUATION_BASELINE.md").read_text(encoding="utf-8")
    assert "CANDIDATE" in md and "activation_blocked" in md
    assert "不是 active" in md and "不是 v2.1" in md
    assert "后续任何语料改进只能进入 v2.1" in md or \
        "仅允许新建 v2.1" in md


def test_freeze_summary(inputs):
    _, out = _freeze_inputs(inputs)
    summary = json.loads((out / "freeze-summary.json").read_text(
        encoding="utf-8"))
    assert summary["deferred_count"] == 18
    assert summary["diagnostic_case_count"] == 4
    assert summary["diagnostic_statuses"]["resolved"] == 4
    assert summary["frozen_revision_status"] == "CANDIDATE"
    assert summary["activation_blocked"] is True
    assert summary["invariants"]["no_overlay"] is True
    assert summary["invariants"]["no_active"] is True
    assert summary["invariants"]["no_v2_1"] is True


def test_freeze_manifest_closure(inputs):
    _, out = _freeze_inputs(inputs)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert dg._verify_self_hash(manifest)
    for name, digest in manifest["outputs"].items():
        assert _sha(out / name) == digest
    assert manifest["gate_verdict"] == dg.GATE_FROZEN
    # inputs 覆盖 diagnostic 输出
    for name in ("diagnostic-manifest.json", "diagnostic-results.jsonl",
                 "diagnostic-raw-model-attempts.jsonl"):
        assert name in manifest["inputs"]


def test_freeze_inputs_unchanged(inputs):
    before = {str(p.relative_to(inputs)): _sha(p)
              for p in inputs.rglob("*") if p.is_file()}
    _, out = _freeze_inputs(inputs)
    after = {str(p.relative_to(inputs)): _sha(p) for p in
             inputs.rglob("*") if p.is_file()
             and "freeze" not in p.parts and "diag" not in p.parts}
    assert before == after


def test_freeze_double_build_byte_identical(inputs):
    stub, _ = make_stub(inputs / "v211", _all_confirmed_sequences())
    _run_diag(inputs, stub, out_name="diag")
    _, out1 = _run_freeze(inputs, out_name="freeze1")
    _, out2 = _run_freeze(inputs, out_name="freeze2")
    for name in dg.FREEZE_OUTPUT_FILES:
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes(), name


def test_freeze_fail_closed_diagnostic_missing(inputs):
    with pytest.raises(dg.DiagnosticError):
        _run_freeze(inputs)
    assert not (inputs / "freeze").exists()


def test_freeze_fail_closed_diag_manifest_tampered(inputs):
    stub, _ = make_stub(inputs / "v211", _all_confirmed_sequences())
    _run_diag(inputs, stub, out_name="diag")
    _tamper_manifest(inputs / "diag" / "manifest.json",
                     lambda m: m.update({"gate_verdict": "X"}))
    with pytest.raises(dg.DiagnosticError):
        _run_freeze(inputs)
    assert not (inputs / "freeze").exists()


def test_freeze_fail_closed_deferred_set_drift(inputs):
    stub, _ = make_stub(inputs / "v211", _all_confirmed_sequences())
    _run_diag(inputs, stub, out_name="diag")
    # 让 pack reject 集漂移（少一条）→ 冻结推导 deferred 集合失败
    _tamper_jsonl(
        inputs / "v211" / "targeted-re-review" / "owner-decision-pack" /
        "stable-reject-root-cause-triage.jsonl",
        lambda rows: [r for r in rows if r["case_id"] != "en-040"])
    with pytest.raises(dg.DiagnosticError):
        _run_freeze(inputs)
    assert not (inputs / "freeze").exists()


def test_freeze_fail_closed_out_dir_exists(inputs):
    stub, _ = make_stub(inputs / "v211", _all_confirmed_sequences())
    _run_diag(inputs, stub, out_name="diag")
    (inputs / "freeze").mkdir()
    with pytest.raises(dg.DiagnosticError):
        _run_freeze(inputs)


def test_freeze_no_forbidden_artifacts(inputs):
    _, out = _freeze_inputs(inputs)
    for name in dg.FREEZE_OUTPUT_FILES:
        low = name.lower()
        for marker in ("overlay", "active", "split", "locked", "v2.1"):
            assert marker not in low, name


# ── 6. 脚本自身确定性 ──────────────────────────────────────────────────

def test_py_compile():
    subprocess.run([sys.executable, "-m", "py_compile",
                    str(ROOT / "scripts" /
                        "corpus_v2_v211_contract_error_diagnostic.py")],
                   check=True, capture_output=True)
