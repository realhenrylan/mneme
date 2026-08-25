"""v2.0.11 targeted re-review of the remaining 22 non-confirmed issues — TDD 测试。

覆盖任务验收：
- 目标集必须从 v2.0.10 triage 的 owner template / triage rows 推导：恰 22 条、
  不含 en-048、恰含 en-052/mixed-030/mixed-033/zh-040、无重复无遗漏；
- 盲态 payload：不含 case_id、旧 review decision/rationale、issue 分类、owner
  决策或内部治理标签（递归键扫描 + 高信号泄露词扫描）；
- Pro-only：--probe-json 身份核验、model=deepseek-v4-pro、temperature=0.0、
  max_tokens=8000、thinking disabled、最多 3 次同模型重试、无 fallback；
- 4 个旧 contract error 也按相同盲态规则复核，不预设为 confirmed；
- 输出只能位于 v2.0.11 的 targeted-re-review/；不改 full review、不生成 overlay、
  不改 candidate metadata、不自动采纳模型结论；
- 22/22 confirmed → TARGETED_REVIEW_OK；任一 reject/needs_followup/身份不符/
  schema 契约错误/传输失败 → TARGETED_REVIEW_BLOCKED（保留可审计产物）；
- 两次构建逐字节一致（模型调用用 stub 覆盖确定性结构）；manifest 自哈希 +
  全部 output SHA；输入 SHA 运行前后不变；禁止激活性产物。
"""

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

import scripts.corpus_v2_v211_targeted_remaining22_review as rv


# ── helpers ─────────────────────────────────────────────────────────────

def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _jsonl(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _copy_candidate(tmp_path: Path) -> Path:
    dst = tmp_path / "candidate"
    shutil.copytree(rv.CANDIDATE, dst)
    return dst


def _copy_review_triage(tmp_path: Path) -> Path:
    """复制真实 v2.0.10 automated-review（含 triage）到 tmp，供篡改测试。"""
    dst = tmp_path / "review"
    shutil.copytree(rv.V210 / "automated-review", dst)
    return dst


def _rewrite_manifest(path: Path, mutate) -> None:
    m = json.loads(path.read_text(encoding="utf-8"))
    mutate(m)
    path.write_text(rv._dump(rv._manifest(m)), encoding="utf-8")


def _tamper_candidate(cand: Path, name: str, mutate_rows) -> None:
    p = cand / name
    rows = _jsonl(p)
    rows = mutate_rows(rows)
    p.write_text("".join(rv._line(r) + "\n" for r in rows),
                 encoding="utf-8", newline="\n")

    def _sync(m):
        m["outputs"][name] = rv._sha256_file(p)
    _rewrite_manifest(cand / "manifest.json", _sync)


def _tamper_triage(review: Path, name: str, mutate_rows) -> None:
    p = review / "coherence-reject-triage" / name
    rows = _jsonl(p)
    rows = mutate_rows(rows)
    p.write_text("".join(rv._line(r) + "\n" for r in rows),
                 encoding="utf-8", newline="\n")

    def _sync(m):
        m["outputs"][name] = rv._sha256_file(p)
    _rewrite_manifest(review / "coherence-reject-triage" / "manifest.json", _sync)


def _payload_sha_map(cand: Path, target_ids: list[str]) -> dict[str, str]:
    """按脚本盲态 payload 构建逻辑复算每个目标 case 的 payload SHA。"""
    draft = _jsonl(cand / "draft-after.jsonl")
    evidence = _jsonl(cand / "evidence-after.jsonl")
    chunks = rv._load_chunks(rv.CHUNKS_PATH)
    by_id = {row["id"]: row for row in draft}
    ev_per_case: dict[str, list[dict]] = {}
    for e in evidence:
        ev_per_case.setdefault(e["case_id"], []).append(e)
    return {cid: rv._sha256_text(rv._payload_text(
        rv.build_payload(by_id[cid], ev_per_case.get(cid, []), chunks)))
        for cid in target_ids}


def make_stub(decisions: dict[str, str]):
    """决策按 payload SHA 注入；未知 payload → 抛异常（传输失败路径）。"""
    def _response(payload: dict, decision: str) -> dict:
        n = len(payload["answer_points"])
        if decision == "confirmed":
            ass = [{"answer_point_index": i, "supported": True,
                    "rationale": "stub ok"} for i in range(n)]
            ra = {"refusal_required": bool(payload["should_refuse"]),
                  "rationale": "stub ok"}
        else:
            ass = [{"answer_point_index": i, "supported": (i > 0),
                    "rationale": "stub no"} for i in range(n)]
            ra = {"refusal_required": (not bool(payload["should_refuse"])
                                       if n == 0
                                       else bool(payload["should_refuse"])),
                  "rationale": "stub no"}
        return {"decision": decision, "answer_point_assessments": ass,
                "refusal_assessment": ra, "rationale": "stub rationale"}

    def client(messages):
        content = messages[0]["content"]
        if '"probe"' in content:
            return ("deepseek-v4-pro", '{"probe": "ok"}', None)
        payload = json.loads(content)
        key = rv._sha256_text(content)
        decision = decisions[key]
        if decision == "error":
            return ("deepseek-v4-pro", "{not valid json", None)
        return ("deepseek-v4-pro", json.dumps(_response(payload, decision),
                                              ensure_ascii=False), None)
    return client


def _run(out_dir: Path, cand: Path, review: Path, stub) -> dict:
    return rv.run(out_dir=out_dir, candidate_dir=cand, review_dir=review,
                  chunks_path=rv.CHUNKS_PATH,
                  chunk_manifest_path=rv.CHUNK_MANIFEST_PATH,
                  current_draft_path=rv.CURRENT_DRAFT_PATH, client=stub)


# ── 1. 常量与输入存在性 ────────────────────────────────────────────────

def test_constants():
    assert rv.MODEL == "deepseek-v4-pro"
    assert rv.TEMPERATURE == 0.0
    assert rv.MAX_TOKENS == 8000
    assert rv.MAX_RETRIES == 3
    assert rv.THINKING_DISABLED == {"thinking": {"type": "disabled"}}
    assert rv.EXPECTED_TARGET_COUNT == 22
    assert rv.EXCLUDED_CASE_ID == "en-048"
    assert set(rv.ERROR_CASES) == {"en-052", "mixed-030", "mixed-033", "zh-040"}
    assert rv.GATE_OK == "TARGETED_REVIEW_OK"
    assert rv.GATE_BLOCKED == "TARGETED_REVIEW_BLOCKED"


def test_input_paths_exist():
    assert rv.CANDIDATE.is_dir()
    assert rv.CANDIDATE.name == "v2.0.11-owner-authorized-en048-same-source-repair"
    assert str(rv.OUT).startswith(str(rv.CANDIDATE))
    assert (rv.V210 / "automated-review" / "manifest.json").is_file()
    assert (rv.TRIAGE_DIR / "owner-decision-template.jsonl").is_file()
    assert (rv.TRIAGE_DIR / "reject-root-cause-triage.jsonl").is_file()
    assert (rv.TRIAGE_DIR / "review-coherence-errors.jsonl").is_file()
    assert rv.CHUNKS_PATH.is_file()
    assert rv.CHUNK_MANIFEST_PATH.is_file()
    assert rv.CURRENT_DRAFT_PATH.is_file()


# ── 2. 目标集推导 ───────────────────────────────────────────────────────

def test_target_set_derivation_real(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    target = rv.derive_target_cases(review_dir=review)
    assert len(target) == 22
    assert len(set(target)) == 22
    assert "en-048" not in target
    for cid in rv.ERROR_CASES:
        assert cid in target
    rejects = {cid for cid in target if cid not in rv.ERROR_CASES}
    assert len(rejects) == 18


def test_target_set_template_equals_union(tmp_path):
    review = _copy_review_triage(tmp_path)
    template = {r["case_id"] for r in _jsonl(
        review / "coherence-reject-triage" / "owner-decision-template.jsonl")}
    rejects = {r["case_id"] for r in _jsonl(
        review / "coherence-reject-triage" / "reject-root-cause-triage.jsonl")}
    errors = {r["case_id"] for r in _jsonl(
        review / "coherence-reject-triage" / "review-coherence-errors.jsonl")}
    assert len(template) == 23
    assert len(rejects) == 19
    assert len(errors) == 4
    assert rejects == template - errors
    assert not (rejects & errors)
    assert set(rv.ERROR_CASES) == errors


def test_preflight_real_inputs_pass(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    checks = rv.preflight(candidate_dir=cand, review_dir=review,
                          chunks_path=rv.CHUNKS_PATH,
                          chunk_manifest_path=rv.CHUNK_MANIFEST_PATH,
                          current_draft_path=rv.CURRENT_DRAFT_PATH)
    assert checks["case_count_ok"] is True
    assert checks["evidence_count_ok"] is True
    assert checks["strict_covered_equals_passed"] is True
    assert checks["candidate_manifest_ok"] is True
    assert checks["review_manifest_ok"] is True
    assert checks["triage_manifest_ok"] is True
    assert checks["input_sha_ok"] is True
    assert checks["target_set_exact"] is True
    assert checks["no_overlay_ok"] is True


def test_preflight_candidate_manifest_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    _rewrite_manifest(cand / "manifest.json",
                      lambda m: m.__setitem__("revision_status", "ACTIVE"))
    with pytest.raises(rv.ReviewError):
        rv.preflight(candidate_dir=cand, review_dir=review,
                     chunks_path=rv.CHUNKS_PATH,
                     chunk_manifest_path=rv.CHUNK_MANIFEST_PATH,
                     current_draft_path=rv.CURRENT_DRAFT_PATH)


def test_preflight_candidate_evidence_tamper_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    _tamper_candidate(cand, "evidence-after.jsonl",
                      lambda rows: rows[: len(rows) - 1])
    with pytest.raises(rv.ReviewError):
        rv.preflight(candidate_dir=cand, review_dir=review,
                     chunks_path=rv.CHUNKS_PATH,
                     chunk_manifest_path=rv.CHUNK_MANIFEST_PATH,
                     current_draft_path=rv.CURRENT_DRAFT_PATH)


def test_preflight_review_manifest_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    _rewrite_manifest(review / "manifest.json",
                      lambda m: m["counts"].__setitem__("reject", 18))
    with pytest.raises(rv.ReviewError):
        rv.preflight(candidate_dir=cand, review_dir=review,
                     chunks_path=rv.CHUNKS_PATH,
                     chunk_manifest_path=rv.CHUNK_MANIFEST_PATH,
                     current_draft_path=rv.CURRENT_DRAFT_PATH)


def test_preflight_triage_manifest_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    _rewrite_manifest(review / "coherence-reject-triage" / "manifest.json",
                      lambda m: m["counts"].__setitem__("reject", 18))
    with pytest.raises(rv.ReviewError):
        rv.preflight(candidate_dir=cand, review_dir=review,
                     chunks_path=rv.CHUNKS_PATH,
                     chunk_manifest_path=rv.CHUNK_MANIFEST_PATH,
                     current_draft_path=rv.CURRENT_DRAFT_PATH)


def test_preflight_template_rows_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    _tamper_triage(review, "owner-decision-template.jsonl",
                   lambda rows: rows[: len(rows) - 1])
    with pytest.raises(rv.ReviewError):
        rv.preflight(candidate_dir=cand, review_dir=review,
                     chunks_path=rv.CHUNKS_PATH,
                     chunk_manifest_path=rv.CHUNK_MANIFEST_PATH,
                     current_draft_path=rv.CURRENT_DRAFT_PATH)


def test_preflight_error_rows_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    _tamper_triage(review, "review-coherence-errors.jsonl",
                   lambda rows: rows[: len(rows) - 1])
    with pytest.raises(rv.ReviewError):
        rv.preflight(candidate_dir=cand, review_dir=review,
                     chunks_path=rv.CHUNKS_PATH,
                     chunk_manifest_path=rv.CHUNK_MANIFEST_PATH,
                     current_draft_path=rv.CURRENT_DRAFT_PATH)


def test_preflight_reject_rows_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    _tamper_triage(review, "reject-root-cause-triage.jsonl",
                   lambda rows: rows[: len(rows) - 1])
    with pytest.raises(rv.ReviewError):
        rv.preflight(candidate_dir=cand, review_dir=review,
                     chunks_path=rv.CHUNKS_PATH,
                     chunk_manifest_path=rv.CHUNK_MANIFEST_PATH,
                     current_draft_path=rv.CURRENT_DRAFT_PATH)


def test_preflight_chunks_sha_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    p = tmp_path / "chunks.jsonl"
    shutil.copy2(rv.CHUNKS_PATH, p)
    with p.open("a", encoding="utf-8") as f:
        f.write("\n")
    with pytest.raises(rv.ReviewError):
        rv.preflight(candidate_dir=cand, review_dir=review, chunks_path=p,
                     chunk_manifest_path=rv.CHUNK_MANIFEST_PATH,
                     current_draft_path=rv.CURRENT_DRAFT_PATH)


# ── 3. 盲态 payload ─────────────────────────────────────────────────────

def test_payloads_are_blind(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    target = rv.derive_target_cases(review_dir=review)
    draft = _jsonl(cand / "draft-after.jsonl")
    evidence = _jsonl(cand / "evidence-after.jsonl")
    chunks = rv._load_chunks(rv.CHUNKS_PATH)
    by_id = {row["id"]: row for row in draft}
    ev_per_case: dict[str, list[dict]] = {}
    for e in evidence:
        ev_per_case.setdefault(e["case_id"], []).append(e)
    for cid in target:
        payload = rv.build_payload(by_id[cid], ev_per_case.get(cid, []), chunks)
        rv.scan_payload(payload)  # 引擎级：递归键白名单 + 高信号泄露词 + case-id
        text = rv._payload_text(payload)
        # 引擎契约：语料字段（raw_span/snippet/source_text）仅扫 case-id 引用；
        # 任务侧字段（query/previous_turns/should_refuse/answer_points）扫治理词
        assert not re.search(r"\b(?:multi|mixed|zh|en|noanswer)-\d+\b", text)
        task_text = json.dumps(
            {k: payload[k] for k in ("query", "previous_turns",
                                     "should_refuse", "answer_points")},
            ensure_ascii=False).lower()
        # 引擎级精确治理标签（与 HIGH_SIGNAL_LEAK_WORDS 同口径，避免 "owner"
        # 之类宽子串误报 ownership 等普通词汇）
        for leak in ("case_id", "case-id", "v2.0.10", "v2.0.11", "confirmed",
                     "reject", "needs_followup", "owner_authorized",
                     "owner_decision", "owner_reviewer", "decision_pack",
                     "revision_status", "activation_blocked", "human_reviewed",
                     "overlay_generated", "split_reseal_required", "v2_1_entered",
                     "triage", "reviewer"):
            assert leak not in task_text
        assert set(payload.keys()) <= rv.ALLOWED_PAYLOAD_KEYS


def test_probe_identity_check_with_stub():
    stub = make_stub({})
    result = rv.probe(stub)
    assert result["ok"] is True
    assert result["model"] == "deepseek-v4-pro"


def test_probe_identity_mismatch_fails_closed(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    target = rv.derive_target_cases(review_dir=review)
    shas = _payload_sha_map(cand, target)
    decisions = {sha: "confirmed" for sha in shas.values()}

    def bad_client(messages):
        content = messages[0]["content"]
        if '"probe"' in content:
            return ("deepseek-v4-flash", '{"probe": "ok"}', None)
        return ("deepseek-v4-flash", "{}", None)

    out = tmp_path / "out"
    with pytest.raises(rv.ReviewError):
        rv.run(out_dir=out, candidate_dir=cand, review_dir=review,
               chunks_path=rv.CHUNKS_PATH,
               chunk_manifest_path=rv.CHUNK_MANIFEST_PATH,
               current_draft_path=rv.CURRENT_DRAFT_PATH, client=bad_client)
    assert not out.exists()


# ── 4. OK / BLOCKED 构建 ────────────────────────────────────────────────

def test_stub_all_confirmed_gate_ok(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    target = rv.derive_target_cases(review_dir=review)
    shas = _payload_sha_map(cand, target)
    stub = make_stub({sha: "confirmed" for sha in shas.values()})
    out = tmp_path / "out"
    result = _run(out, cand, review, stub)
    assert result["gate"] == rv.GATE_OK
    assert result["counts"]["confirmed"] == 22
    assert result["counts"]["reject"] == 0
    assert result["counts"]["errors"] == 0
    assert not (out / "targeted-review-issues.jsonl").exists()
    names = {p.name for p in out.iterdir()}
    assert names == set(rv.OUTPUT_FILES_OK)


def test_stub_rejects_gate_blocked(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    target = rv.derive_target_cases(review_dir=review)
    shas = _payload_sha_map(cand, target)
    decisions = {sha: "confirmed" for sha in shas.values()}
    # 挑两个 case 的 payload（按目标列表顺序）设为 reject
    decisions[shas[target[0]]] = "reject"
    decisions[shas[target[3]]] = "needs_followup"
    stub = make_stub(decisions)
    out = tmp_path / "out"
    result = _run(out, cand, review, stub)
    assert result["gate"] == rv.GATE_BLOCKED
    assert result["counts"]["confirmed"] == 20
    assert result["counts"]["reject"] == 1
    assert result["counts"]["needs_followup"] == 1
    issues = _jsonl(out / "targeted-review-issues.jsonl")
    assert {i["case_id"] for i in issues} == {target[0], target[3]}
    for i in issues:
        assert i["kind"] in ("reject", "needs_followup")
        assert i["response_sha256"]
        assert i["attempts"] == 1
    names = {p.name for p in out.iterdir()}
    assert names == set(rv.OUTPUT_FILES_BLOCKED)


def test_stub_contract_error_gate_blocked(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    target = rv.derive_target_cases(review_dir=review)
    shas = _payload_sha_map(cand, target)
    decisions = {sha: "confirmed" for sha in shas.values()}
    decisions[shas[target[0]]] = "error"
    stub = make_stub(decisions)
    out = tmp_path / "out"
    result = _run(out, cand, review, stub)
    assert result["gate"] == rv.GATE_BLOCKED
    assert result["counts"]["confirmed"] == 21
    assert result["counts"]["errors"] == 1
    issues = _jsonl(out / "targeted-review-issues.jsonl")
    assert len(issues) == 1
    assert issues[0]["case_id"] == target[0]
    assert issues[0]["kind"] == "error"
    assert issues[0]["attempts"] == rv.MAX_RETRIES + 1
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["validation"]["schema_errors"] == 1
    assert m["validation"]["identity_errors"] == 0
    assert m["validation"]["transport_errors"] == 0


def test_results_ledger_covers_all_22(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    target = rv.derive_target_cases(review_dir=review)
    shas = _payload_sha_map(cand, target)
    decisions = {sha: "confirmed" for sha in shas.values()}
    decisions[shas[target[0]]] = "reject"
    stub = make_stub(decisions)
    out = tmp_path / "out"
    _run(out, cand, review, stub)
    rows = _jsonl(out / "targeted-review-results.jsonl")
    assert len(rows) == 22
    assert {r["case_id"] for r in rows} == set(target)
    for r in rows:
        assert r["decision"] in ("confirmed", "reject", "needs_followup")
        assert r["model"] == "deepseek-v4-pro"
        assert r["payload_sha256"]
        assert r["response_sha256"]
        assert r["attempts"] >= 1


def test_manifest_self_hash_and_outputs_sha(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    target = rv.derive_target_cases(review_dir=review)
    shas = _payload_sha_map(cand, target)
    stub = make_stub({sha: "confirmed" for sha in shas.values()})
    out = tmp_path / "out"
    _run(out, cand, review, stub)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert rv._verify_self_hash(m)
    for name, digest in m["outputs"].items():
        assert (out / name).is_file()
        assert rv._sha256_file(out / name) == digest


def test_manifest_inputs_sha_match_sources(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    target = rv.derive_target_cases(review_dir=review)
    shas = _payload_sha_map(cand, target)
    stub = make_stub({sha: "confirmed" for sha in shas.values()})
    out = tmp_path / "out"
    _run(out, cand, review, stub)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    inputs = m["inputs"]
    assert inputs["candidate-draft-after.jsonl"] == _sha(cand / "draft-after.jsonl")
    assert inputs["candidate-evidence-after.jsonl"] == _sha(cand / "evidence-after.jsonl")
    assert inputs["candidate-manifest.json"] == _sha(cand / "manifest.json")
    assert inputs["owner-decision-template.jsonl"] == \
        _sha(review / "coherence-reject-triage" / "owner-decision-template.jsonl")
    assert inputs["reject-root-cause-triage.jsonl"] == \
        _sha(review / "coherence-reject-triage" / "reject-root-cause-triage.jsonl")
    assert inputs["chunks.jsonl"] == _sha(rv.CHUNKS_PATH)


def test_manifest_counts_and_metadata(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    target = rv.derive_target_cases(review_dir=review)
    shas = _payload_sha_map(cand, target)
    stub = make_stub({sha: "confirmed" for sha in shas.values()})
    out = tmp_path / "out"
    _run(out, cand, review, stub)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["counts"]["case_count"] == 22
    assert m["counts"]["confirmed"] == 22
    assert m["counts"]["reject"] == 0
    assert m["counts"]["errors"] == 0
    assert sorted(m["target_set"]) == sorted(target)
    assert m["metadata"] == {
        "revision_status": "CANDIDATE",
        "activation_blocked": True,
        "human_reviewed": False,
        "overlay_generated": False,
        "split_reseal_required": True,
        "v2_1_entered": False,
    }
    assert m["declarations"]["llm_called"] is True
    assert m["declarations"]["no_fallback"] is True
    assert m["declarations"]["old_decisions_in_payload"] is False
    assert m["declarations"]["overlay_generated"] is False
    assert m["validation"]["target_set_exact"] is True
    assert m["validation"]["all_cases_confirmed"] is True


def test_input_sha_unchanged_after_run(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    target = rv.derive_target_cases(review_dir=review)
    shas = _payload_sha_map(cand, target)
    before = {
        "draft": _sha(cand / "draft-after.jsonl"),
        "evidence": _sha(cand / "evidence-after.jsonl"),
        "template": _sha(review / "coherence-reject-triage" /
                         "owner-decision-template.jsonl"),
        "chunks": _sha(rv.CHUNKS_PATH),
    }
    stub = make_stub({sha: "confirmed" for sha in shas.values()})
    out = tmp_path / "out"
    _run(out, cand, review, stub)
    assert _sha(cand / "draft-after.jsonl") == before["draft"]
    assert _sha(cand / "evidence-after.jsonl") == before["evidence"]
    assert _sha(review / "coherence-reject-triage" /
                "owner-decision-template.jsonl") == before["template"]
    assert _sha(rv.CHUNKS_PATH) == before["chunks"]


def test_two_builds_byte_identical(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    target = rv.derive_target_cases(review_dir=review)
    shas = _payload_sha_map(cand, target)
    stub = make_stub({sha: "confirmed" for sha in shas.values()})
    out1, out2 = tmp_path / "out1", tmp_path / "out2"
    _run(out1, cand, review, stub)
    _run(out2, cand, review, stub)
    names1 = {p.name for p in out1.iterdir()}
    names2 = {p.name for p in out2.iterdir()}
    assert names1 == names2
    for name in names1:
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()


def test_no_forbidden_outputs_ok_and_blocked(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    target = rv.derive_target_cases(review_dir=review)
    shas = _payload_sha_map(cand, target)
    for outcome in ("ok", "blocked"):
        decisions = {sha: "confirmed" for sha in shas.values()}
        if outcome == "blocked":
            decisions[shas[target[0]]] = "reject"
        stub = make_stub(decisions)
        out = tmp_path / f"out-{outcome}"
        _run(out, cand, review, stub)
        for p in out.iterdir():
            name = p.name.lower()
            assert not name.startswith(("overlay", "active", "split", "after"))
            assert "v2.1" not in name
            assert not name.startswith(".")


def test_run_output_dir_exists_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    review = _copy_review_triage(tmp_path)
    target = rv.derive_target_cases(review_dir=review)
    shas = _payload_sha_map(cand, target)
    stub = make_stub({sha: "confirmed" for sha in shas.values()})
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(rv.ReviewError):
        _run(out, cand, review, stub)
