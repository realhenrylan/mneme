"""v2.0.9 fresh full blind automated review — TDD 测试（先 RED 再 GREEN）。

覆盖任务验收：
- 137/144 strict 预检；禁止读取旧 review；
- payload 无身份/治理信息泄露；Pro-only 参数与身份校验；
- 同模型重试、失败清理、无 fallback；翻译等价规范对所有 case 一致；
- decision/refusal schema fail-closed；统计守恒；
- 全 confirmed 才可生成非人工 automated overlay；非 confirmed 零 overlay；
- candidate 与输入 SHA 不变；注入 stub 的两次构建逐字节一致。
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

import scripts.corpus_v2_v209_fresh_blind_automated_review as ar


# ── helpers ─────────────────────────────────────────────────────────────

def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _jsonl(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _copy_candidate(tmp_path: Path) -> Path:
    dst = tmp_path / "candidate"
    shutil.copytree(ar.CANDIDATE, dst)
    return dst


def _rewrite_manifest(cand: Path, mutate) -> None:
    """读取 candidate manifest、应用 mutate、重算自哈希后写回。"""
    p = cand / "manifest.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    mutate(m)
    p.write_text(ar._dump(ar._manifest(m)), encoding="utf-8")


def _tamper_output(cand: Path, name: str, mutate_rows) -> None:
    """篡改 candidate 输出文件并同步更新 manifest outputs SHA（使后续门禁可达）。"""
    p = cand / name
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    mutate_rows(rows)
    p.write_text("".join(ar._line(r) + "\n" for r in rows), encoding="utf-8")

    def _sync(m):
        m["outputs"][name] = ar._sha256_file(p)
    _rewrite_manifest(cand, _sync)


# ── stub 模型客户端 ─────────────────────────────────────────────────────

def _confirmed_answer(payload: dict) -> dict:
    """对任意盲态 payload 构造合法 confirmed 响应（适配 AP 数与 refusal 语义）。"""
    assessments = [
        {"answer_point_index": i, "supported": True, "rationale": "证据直接支撑该答案点。"}
        for i in range(len(payload["answer_points"]))
    ]
    return {
        "decision": "confirmed",
        "answer_point_assessments": assessments,
        "refusal_assessment": {
            "refusal_required": bool(payload["should_refuse"]),
            "rationale": "符合预期。",
        },
        "rationale": "所有答案点均获直接证据支持，refusal 语义与预期一致。",
    }


def _responder(messages):
    """默认 stub responder：probe 回 probe JSON，case 回 confirmed。"""
    content = messages[-1]["content"]
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return '{"probe": "ok"}'
    if "query" not in payload:
        return '{"probe": "ok"}'
    return json.dumps(_confirmed_answer(payload), ensure_ascii=False, sort_keys=True)


def _make_stub(responder=None, model=ar.MODEL, fail_first=0, always_raise=None):
    """创建可注入 stub client：client(messages) -> (model, content, usage)。"""
    calls = []
    responder = responder or _responder

    def client(messages):
        calls.append({"messages": list(messages)})
        if always_raise is not None:
            raise always_raise
        if fail_first and len(calls) <= fail_first:
            raise RuntimeError("stub transport failure")
        return model, responder(messages), None

    return client, calls


def _synthetic_row(**overrides) -> dict:
    row = {
        "id": "zh-001",
        "query": "Python 的列表支持哪些操作？",
        "should_refuse": False,
        "acceptable_answer_points": ["列表支持索引与切片"],
        "metadata": {"follow_up_to": None, "chain_id": "zh-001", "turn": 1},
    }
    row.update(overrides)
    return row


def _payload(**overrides) -> dict:
    """构造盲态 payload（与真实管线一致的形状）。"""
    return ar.build_payload(_synthetic_row(**overrides), [], {})


# ── 1. 常量与规范 ───────────────────────────────────────────────────────

def test_constants_pro_only():
    assert ar.MODEL == "deepseek-v4-pro"
    assert ar.TEMPERATURE == 0.0
    assert ar.MAX_TOKENS == 8000
    assert ar.THINKING_DISABLED == {"thinking": {"type": "disabled"}}
    assert ar.MAX_RETRIES == 3
    assert "deepseek-v4-flash" in ar.FORBIDDEN_MODELS
    assert "gpt-5.6-sol" in ar.FORBIDDEN_MODELS


def test_uniform_support_spec_contains_mandated_semantics():
    spec = ar.UNIFORM_SUPPORT_SPEC
    assert "仅当证据直接支撑答案点时判定支持" in spec
    assert "翻译" in spec and "语义等价" in spec and "没有新增主张" in spec
    assert "翻译政策标签" in spec


def test_uniform_support_spec_contains_output_contract():
    # 输出契约必须对全部 case 一致（同一字符串），明确严格 JSON 字段
    spec = ar.UNIFORM_SUPPORT_SPEC
    assert "decision" in spec
    assert "answer_point_assessments" in spec
    assert "refusal_assessment" in spec
    assert "rationale" in spec
    assert "answer_point_index" in spec
    assert "仅返回严格 JSON" in spec
    assert "decision 是审查结论" in spec
    assert "confirmed" in spec and "reject" in spec and "needs_followup" in spec


def test_validate_content_strips_single_json_fence():
    payload = _payload()
    answer = _confirmed_answer(payload)
    fenced = "```json\n" + json.dumps(answer, ensure_ascii=False) + "\n```"
    out = ar._validate_content(fenced, payload)
    assert out["decision"] == "confirmed"


def test_validate_content_rejects_garbage_around_json():
    payload = _payload()
    answer = _confirmed_answer(payload)
    # 围栏外有额外文字 → 仍严格失败（不是单围栏包裹）
    bad = "好的，结果如下：\n```json\n" + json.dumps(answer, ensure_ascii=False) + "\n```"
    with pytest.raises(ar.ReviewError):
        ar._validate_content(bad, payload)


def test_strip_json_fence_only_single_wrapper():
    assert ar._strip_json_fence("```json\n{\"a\": 1}\n```") == '{"a": 1}'
    assert ar._strip_json_fence('{"a": 1}') == '{"a": 1}'
    # 双重围栏/不完整围栏不剥离（交给严格解析失败）
    assert ar._strip_json_fence("```\n```\n{\"a\": 1}") != '{"a": 1}'


def test_leak_words_are_high_signal_and_spec_verified():
    # 泄漏词必须在真实语料（query/AP/evidence span/snippet）中零命中，否则误杀
    assert ar.HIGH_SIGNAL_LEAK_WORDS
    draft = _jsonl(ar.CANDIDATE / "draft-after.jsonl")
    ev = _jsonl(ar.CANDIDATE / "evidence-after.jsonl")
    strings = [r["query"] for r in draft]
    strings += [ap for r in draft for ap in (r.get("acceptable_answer_points") or [])]
    strings += [e["raw_evidence_span"] for e in ev]
    strings += [e["snippet"] for e in ev]
    for word in ar.HIGH_SIGNAL_LEAK_WORDS:
        low = word.lower()
        assert not any(low in s.lower() for s in strings), word


# ── 2. 预检（fail-closed，真实输入）────────────────────────────────────

def test_preflight_passes_real_inputs():
    checks = ar.preflight(ar.CANDIDATE, ar.CHUNKS_PATH, ar.CHUNK_MANIFEST_PATH,
                          ar.CURRENT_DRAFT_PATH, ar.TRANS_POLICY_PATH,
                          ar.TRANS_LEDGER_PATH)
    assert checks["case_count"] == 137
    assert checks["evidence_count"] == 144
    assert checks["strict_covered"] == 144
    assert checks["strict_passed"] == 144
    assert checks["legacy"] == 0
    assert checks["unresolved"] == 0
    assert checks["invalid"] == 0
    assert checks["uncovered"] == 0
    assert checks["answerable_cases"] == 106
    assert checks["refusal_cases"] == 31
    assert checks["answerable_without_evidence"] == []
    assert checks["refusal_with_evidence"] == []
    assert checks["metadata_ok"] is True
    assert checks["manifest_self_hash_ok"] is True
    assert checks["outputs_sha_ok"] is True
    assert checks["inputs_sha_ok"] is True
    assert checks["queries_unique"] is True
    assert checks["dangling_draft_refs"] == []
    assert checks["refs_to_retired"] == []
    assert checks["translation_ledger_rows"] == 3
    # 唯一性：无冲突性重复；字节级相同的重复行（mixed-033）是 candidate 自身
    # data-quality-report 已记录的已知事实（evidence_keys_unique=false），记录不阻断
    assert checks["evidence_anchor_conflicts"] == []
    assert checks["duplicate_evidence_rows"] == ["mixed-033"]
    assert checks["duplicate_evidence_pairs"] == 1


def test_preflight_manifest_status_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    _rewrite_manifest(cand, lambda m: m.update({"revision_status": "ACTIVE"}))
    with pytest.raises(ar.ReviewError):
        ar.preflight(cand, ar.CHUNKS_PATH, ar.CHUNK_MANIFEST_PATH,
                     ar.CURRENT_DRAFT_PATH, ar.TRANS_POLICY_PATH,
                     ar.TRANS_LEDGER_PATH)


def test_preflight_manifest_counts_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    _rewrite_manifest(cand, lambda m: m["counts"].update({"case_after": 138}))
    with pytest.raises(ar.ReviewError):
        ar.preflight(cand, ar.CHUNKS_PATH, ar.CHUNK_MANIFEST_PATH,
                     ar.CURRENT_DRAFT_PATH, ar.TRANS_POLICY_PATH,
                     ar.TRANS_LEDGER_PATH)


def test_preflight_manifest_selfhash_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    p = cand / "manifest.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    m["manifest_sha256"] = "0" * 64
    p.write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n",
                 encoding="utf-8")
    with pytest.raises(ar.ReviewError):
        ar.preflight(cand, ar.CHUNKS_PATH, ar.CHUNK_MANIFEST_PATH,
                     ar.CURRENT_DRAFT_PATH, ar.TRANS_POLICY_PATH,
                     ar.TRANS_LEDGER_PATH)


def test_preflight_draft_count_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)

    def _drop(rows):
        rows.pop(0)
    _tamper_output(cand, "draft-after.jsonl", _drop)
    with pytest.raises(ar.ReviewError):
        ar.preflight(cand, ar.CHUNKS_PATH, ar.CHUNK_MANIFEST_PATH,
                     ar.CURRENT_DRAFT_PATH, ar.TRANS_POLICY_PATH,
                     ar.TRANS_LEDGER_PATH)


def test_preflight_draft_query_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    # 直接篡改候选 draft 而不更新 manifest outputs SHA → 输出 SHA 门禁 fail-closed
    p = cand / "draft-after.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    rows[0]["query"] = rows[0]["query"] + "（被篡改）"
    p.write_text("".join(ar._line(r) + "\n" for r in rows), encoding="utf-8")
    with pytest.raises(ar.ReviewError):
        ar.preflight(cand, ar.CHUNKS_PATH, ar.CHUNK_MANIFEST_PATH,
                     ar.CURRENT_DRAFT_PATH, ar.TRANS_POLICY_PATH,
                     ar.TRANS_LEDGER_PATH)


def test_preflight_evidence_count_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)

    def _drop(rows):
        rows.pop(0)
    _tamper_output(cand, "evidence-after.jsonl", _drop)
    with pytest.raises(ar.ReviewError):
        ar.preflight(cand, ar.CHUNKS_PATH, ar.CHUNK_MANIFEST_PATH,
                     ar.CURRENT_DRAFT_PATH, ar.TRANS_POLICY_PATH,
                     ar.TRANS_LEDGER_PATH)


def test_preflight_evidence_span_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)

    def _mutate(rows):
        rows[0]["raw_evidence_span"] = rows[0]["raw_evidence_span"] + "x"
    _tamper_output(cand, "evidence-after.jsonl", _mutate)
    with pytest.raises(ar.ReviewError):
        ar.preflight(cand, ar.CHUNKS_PATH, ar.CHUNK_MANIFEST_PATH,
                     ar.CURRENT_DRAFT_PATH, ar.TRANS_POLICY_PATH,
                     ar.TRANS_LEDGER_PATH)


def test_preflight_evidence_case_ref_drift_fails(tmp_path):
    cand = _copy_candidate(tmp_path)

    def _mutate(rows):
        rows[0]["case_id"] = "multi-999"
    _tamper_output(cand, "evidence-after.jsonl", _mutate)
    with pytest.raises(ar.ReviewError):
        ar.preflight(cand, ar.CHUNKS_PATH, ar.CHUNK_MANIFEST_PATH,
                     ar.CURRENT_DRAFT_PATH, ar.TRANS_POLICY_PATH,
                     ar.TRANS_LEDGER_PATH)


def test_preflight_answerable_without_evidence_fails(tmp_path):
    cand = _copy_candidate(tmp_path)
    ev = _jsonl(cand / "evidence-after.jsonl")
    target = next(e["case_id"] for e in ev)

    def _drop(rows):
        rows[:] = [r for r in rows if r["case_id"] != target]
    _tamper_output(cand, "evidence-after.jsonl", _drop)
    with pytest.raises(ar.ReviewError):
        ar.preflight(cand, ar.CHUNKS_PATH, ar.CHUNK_MANIFEST_PATH,
                     ar.CURRENT_DRAFT_PATH, ar.TRANS_POLICY_PATH,
                     ar.TRANS_LEDGER_PATH)


def test_preflight_chunks_sha_drift_fails(tmp_path):
    p = tmp_path / "chunks.jsonl"
    p.write_text(Path(ar.CHUNKS_PATH).read_text(encoding="utf-8") + "\n",
                 encoding="utf-8")
    with pytest.raises(ar.ReviewError):
        ar.preflight(ar.CANDIDATE, p, ar.CHUNK_MANIFEST_PATH,
                     ar.CURRENT_DRAFT_PATH, ar.TRANS_POLICY_PATH,
                     ar.TRANS_LEDGER_PATH)


def test_preflight_chunk_manifest_sha_drift_fails(tmp_path):
    p = tmp_path / "chunk-manifest.json"
    m = json.loads(Path(ar.CHUNK_MANIFEST_PATH).read_text(encoding="utf-8"))
    m["n_chunks"] = 999  # 内容漂移 → 输入 SHA 门禁失败
    p.write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n",
                 encoding="utf-8")
    with pytest.raises(ar.ReviewError):
        ar.preflight(ar.CANDIDATE, ar.CHUNKS_PATH, p,
                     ar.CURRENT_DRAFT_PATH, ar.TRANS_POLICY_PATH,
                     ar.TRANS_LEDGER_PATH)


def test_preflight_current_draft_sha_drift_fails(tmp_path):
    p = tmp_path / "v2-cases-draft.jsonl"
    p.write_text(Path(ar.CURRENT_DRAFT_PATH).read_text(encoding="utf-8") + "\n",
                 encoding="utf-8")
    with pytest.raises(ar.ReviewError):
        ar.preflight(ar.CANDIDATE, ar.CHUNKS_PATH, ar.CHUNK_MANIFEST_PATH,
                     p, ar.TRANS_POLICY_PATH, ar.TRANS_LEDGER_PATH)


def test_preflight_translation_ledger_drift_fails(tmp_path):
    p = tmp_path / "ledger.jsonl"
    p.write_text('{"case_id": "zh-001", "not_confirmed": true}\n',
                 encoding="utf-8")
    with pytest.raises(ar.ReviewError):
        ar.preflight(ar.CANDIDATE, ar.CHUNKS_PATH, ar.CHUNK_MANIFEST_PATH,
                     ar.CURRENT_DRAFT_PATH, ar.TRANS_POLICY_PATH, p)


def test_preflight_translation_policy_missing_fails(tmp_path):
    with pytest.raises(ar.ReviewError):
        ar.preflight(ar.CANDIDATE, ar.CHUNKS_PATH, ar.CHUNK_MANIFEST_PATH,
                     ar.CURRENT_DRAFT_PATH, tmp_path / "nope.md",
                     ar.TRANS_LEDGER_PATH)


# ── 3. 禁止读取旧 review ────────────────────────────────────────────────

def test_content_read_paths_are_allowlisted_only():
    allowed = {str(p) for p in ar.INPUT_READ_PATHS}
    forbidden_fragments = (
        "split", "holdout", "locked", "human-review", "v2.0.7",
        "targeted-re-review", "automated-review", "llm-semantic-adjudication",
        "llm-third-pass-audit", "persistent-reject", "evaluation/results",
        "retrieval", "generation",
    )
    for p in allowed:
        for frag in forbidden_fragments:
            assert frag not in p.lower(), (p, frag)
    # 内容读取必须恰好覆盖：candidate draft/evidence/manifest + chunks + chunk
    # manifest + translation policy/ledger
    assert len(allowed) == 7


def test_hash_only_inputs_cover_manifest_input_sha_map():
    # 输入 SHA 门禁所需的 v2.0.8 文件仅作字节级哈希（不读内容）
    for key, p in ar.INPUT_SHA_MAP.items():
        assert isinstance(p, Path)
    assert any("final-blockers-decision-pack" in str(p)
               for p in ar.INPUT_SHA_MAP.values())
    assert any("chain-closure-decision-pack" in str(p)
               for p in ar.INPUT_SHA_MAP.values())


def test_read_input_rejects_non_allowlisted_path(tmp_path):
    with pytest.raises(ar.ForbiddenInputError):
        ar._read_text(tmp_path / "evil.jsonl")


# ── 4. 盲态 payload ─────────────────────────────────────────────────────

def test_payload_blind_structure():
    row = _jsonl(ar.CANDIDATE / "draft-after.jsonl")[0]
    payload = ar.build_payload(row, [], {})
    assert set(payload.keys()) == {"query", "previous_turns", "should_refuse",
                                   "answer_points", "evidence", "support_spec"}
    ar.scan_payload(payload)  # 递归键扫描通过（evidence 子键在白名单内）
    assert payload["query"] == row["query"]
    assert payload["should_refuse"] == row["should_refuse"]
    assert payload["answer_points"] == row["acceptable_answer_points"]
    assert payload["previous_turns"] == []
    assert payload["support_spec"] == ar.UNIFORM_SUPPORT_SPEC


def test_payload_evidence_fields_real_case():
    draft = {r["id"]: r for r in _jsonl(ar.CANDIDATE / "draft-after.jsonl")}
    ev = _jsonl(ar.CANDIDATE / "evidence-after.jsonl")
    chunks = ar._load_chunks(ar.CHUNKS_PATH)
    per_case = {}
    for e in ev:
        per_case.setdefault(e["case_id"], []).append(e)
    cid = next(c for c in per_case if len(per_case[c]) == 2)
    payload = ar.build_payload(draft[cid], per_case[cid], chunks)
    evs = sorted(per_case[cid], key=lambda e: (e["chunk_id"], e["raw_chunk_char_range"]["start"]))
    assert len(payload["evidence"]) == 2
    for got, src in zip(payload["evidence"], evs):
        assert got["raw_span"] == src["raw_evidence_span"]
        assert got["snippet"] == src["snippet"]
        assert got["source_text"] == chunks[src["chunk_id"]]["text"]


def test_payload_previous_turns_stripped():
    row = _synthetic_row()
    row["metadata"]["previous_turns"] = [
        {"query": "第一轮问题", "case_id": "multi-011",
         "chain_id": "multi-011", "follow_up_to": "multi-010",
         "doc_target": "python-tutorial-zh"},
        "纯文本轮次",
    ]
    payload = ar.build_payload(row, [], {})
    assert payload["previous_turns"] == ["第一轮问题", "纯文本轮次"]
    assert ar.CASE_ID_RE.search(json.dumps(payload, ensure_ascii=False)) is None


def test_payload_refusal_case():
    draft = {r["id"]: r for r in _jsonl(ar.CANDIDATE / "draft-after.jsonl")}
    cid = next(r for r in draft if draft[r]["should_refuse"])
    payload = ar.build_payload(draft[cid], [], {})
    assert payload["should_refuse"] is True
    assert payload["answer_points"] == []
    assert payload["evidence"] == []


def test_leak_scan_rejects_case_id():
    row = _synthetic_row(query="为什么 multi-999 没有答案？")
    payload = ar.build_payload(row, [], {})
    with pytest.raises(ar.ReviewError):
        ar.scan_payload(payload)


def test_leak_scan_rejects_governance_word():
    row = _synthetic_row(query="这是 revision 相关的问题吗？")
    payload = ar.build_payload(row, [], {})
    with pytest.raises(ar.ReviewError):
        ar.scan_payload(payload)


def test_key_scan_rejects_extra_key():
    row = _synthetic_row()
    payload = ar.build_payload(row, [], {})
    payload["case_id"] = "zh-001"
    with pytest.raises(ar.ReviewError):
        ar.scan_payload(payload)


def test_all_real_payloads_pass_leak_scan():
    draft = _jsonl(ar.CANDIDATE / "draft-after.jsonl")
    ev = _jsonl(ar.CANDIDATE / "evidence-after.jsonl")
    chunks = ar._load_chunks(ar.CHUNKS_PATH)
    per_case = {}
    for e in ev:
        per_case.setdefault(e["case_id"], []).append(e)
    for row in draft:
        payload = ar.build_payload(row, per_case.get(row["id"], []), chunks)
        ar.scan_payload(payload)  # 不抛即通过


# ── 5. 响应 schema / refusal 语义（fail-closed）───────────────────────

def test_validate_confirmed_ok():
    payload = _payload()
    answer = _confirmed_answer(payload)
    out = ar.validate_response(answer, payload)
    assert out["decision"] == "confirmed"
    assert out["answer_point_assessments"][0]["supported"] is True


def test_validate_reject_ok():
    payload = _payload(acceptable_answer_points=["甲", "乙"])
    answer = {
        "decision": "reject",
        "answer_point_assessments": [
            {"answer_point_index": 0, "supported": True, "rationale": "ok"},
            {"answer_point_index": 1, "supported": False,
             "rationale": "证据不足"},
        ],
        "refusal_assessment": {"refusal_required": False, "rationale": "ok"},
        "rationale": "AP1 无证据支持",
    }
    out = ar.validate_response(answer, payload)
    assert out["decision"] == "reject"


def test_validate_bad_decision():
    payload = _payload()
    answer = _confirmed_answer(payload)
    answer["decision"] = "approve"
    with pytest.raises(ar.ReviewError):
        ar.validate_response(answer, payload)


def test_validate_extra_top_key():
    payload = _payload()
    answer = _confirmed_answer(payload)
    answer["case_id"] = "zh-001"
    with pytest.raises(ar.ReviewError):
        ar.validate_response(answer, payload)


def test_validate_missing_assessment_index():
    payload = _payload(acceptable_answer_points=["甲", "乙"])
    answer = _confirmed_answer(payload)
    answer["answer_point_assessments"] = answer["answer_point_assessments"][:1]
    with pytest.raises(ar.ReviewError):
        ar.validate_response(answer, payload)


def test_validate_extra_assessment_index():
    payload = _payload()
    answer = _confirmed_answer(payload)
    answer["answer_point_assessments"].append(
        {"answer_point_index": 1, "supported": True, "rationale": "x"})
    with pytest.raises(ar.ReviewError):
        ar.validate_response(answer, payload)


def test_validate_refusal_case_assessments_forbidden():
    payload = _payload(should_refuse=True, acceptable_answer_points=[])
    answer = _confirmed_answer(payload)
    answer["answer_point_assessments"] = [
        {"answer_point_index": 0, "supported": True, "rationale": "x"}]
    with pytest.raises(ar.ReviewError):
        ar.validate_response(answer, payload)


def test_validate_confirmed_with_unsupported_ap():
    payload = _payload()
    answer = _confirmed_answer(payload)
    answer["answer_point_assessments"][0]["supported"] = False
    with pytest.raises(ar.ReviewError):
        ar.validate_response(answer, payload)


def test_validate_reject_with_all_supported():
    payload = _payload(acceptable_answer_points=["甲", "乙"])
    answer = _confirmed_answer(payload)
    answer["decision"] = "reject"
    with pytest.raises(ar.ReviewError):
        ar.validate_response(answer, payload)


def test_validate_confirmed_refusal_semantic_mismatch():
    payload = _payload(should_refuse=True, acceptable_answer_points=[])
    answer = _confirmed_answer(payload)
    answer["refusal_assessment"]["refusal_required"] = False
    with pytest.raises(ar.ReviewError):
        ar.validate_response(answer, payload)


def test_validate_non_bool_supported():
    payload = _payload()
    answer = _confirmed_answer(payload)
    answer["answer_point_assessments"][0]["supported"] = "yes"
    with pytest.raises(ar.ReviewError):
        ar.validate_response(answer, payload)


def test_validate_not_json_content():
    payload = _payload()
    with pytest.raises(ar.ReviewError):
        ar._validate_content("this is not json", payload)


# ── 6. 模型调用：同模型重试、无 fallback、失败清理 ────────────────────

def test_review_case_retries_then_ok():
    payload = _payload()
    client, calls = _make_stub(fail_first=2)
    result = ar.review_case("zh-001", payload, client)
    assert result["decision"] == "confirmed"
    assert len(calls) == 3
    assert calls[0]["messages"][-1]["content"] == json.dumps(
        payload, ensure_ascii=False, indent=1)


def test_review_case_all_transport_failures_block():
    payload = _payload()
    client, calls = _make_stub(always_raise=RuntimeError("boom"))
    with pytest.raises(ar.ReviewError) as ei:
        ar.review_case("zh-001", payload, client)
    assert "attempts" in str(ei.value)
    assert len(calls) == ar.MAX_RETRIES + 1


def test_review_case_invalid_json_retries_then_blocked():
    payload = _payload()
    responses = [("not json") for _ in range(4)]
    client, calls = _make_stub(responder=lambda m: responses.pop(0))
    with pytest.raises(ar.ReviewError):
        ar.review_case("zh-001", payload, client)
    assert len(calls) == ar.MAX_RETRIES + 1


def test_review_case_identity_mismatch_retries_same_model():
    payload = _payload()

    def responder(messages):
        return json.dumps(_confirmed_answer(json.loads(messages[-1]["content"])),
                          ensure_ascii=False, sort_keys=True)

    calls = []

    def client(messages):
        calls.append(messages)
        if len(calls) <= 2:
            return "deepseek-v4-flash", '{"probe": "ok"}', None  # 身份错误
        return ar.MODEL, responder(messages), None

    result = ar.review_case("zh-001", payload, client)
    assert result["decision"] == "confirmed"
    assert len(calls) == 3
    # 无 fallback：所有请求模型都是同一种
    assert all("model" not in m[-1] for m in calls)


def test_no_fallback_models_requested():
    client, calls = _make_stub()
    payloads = [ar.build_payload(_synthetic_row(id=f"zh-{i:03d}"), [], {})
                for i in range(3)]
    for cid, p in zip(("zh-001", "zh-002", "zh-003"), payloads):
        ar.review_case(cid, p, client)
    for call in calls:
        assert call["messages"][-1]["content"].startswith("{")
        assert call["messages"][-1]["role"] == "user"


# ── 7. 完整构建：成功路径（全 confirmed）──────────────────────────────

def _run_build(tmp_path, client, out_name="out"):
    out = tmp_path / out_name
    result = ar.run(out_dir=out, candidate_dir=ar.CANDIDATE,
                    chunks_path=ar.CHUNKS_PATH,
                    chunk_manifest_path=ar.CHUNK_MANIFEST_PATH,
                    current_draft_path=ar.CURRENT_DRAFT_PATH,
                    trans_policy_path=ar.TRANS_POLICY_PATH,
                    trans_ledger_path=ar.TRANS_LEDGER_PATH,
                    client=client)
    return out, result


def test_build_success_all_confirmed(tmp_path):
    client, calls = _make_stub()
    out, result = _run_build(tmp_path, client)
    assert result["gate"] == ar.GATE_OK
    # 137 次 case 调用 + 1 次探针
    assert len(calls) == 138
    files = {p.name for p in out.iterdir()}
    assert files == {
        "automated-review-pack.jsonl",
        "automated-review-evidence.jsonl",
        "automated-review.jsonl",
        "raw-model-responses.jsonl",
        "automated-review-summary.json",
        "automated-review-report.md",
        "automated-review-gate-report.md",
        "manifest.json",
        "automated-overlay.json",
    }
    assert "automated-review-issues.jsonl" not in files


def test_build_success_pack_rows(tmp_path):
    client, _ = _make_stub()
    out, _ = _run_build(tmp_path, client)
    pack = _jsonl(out / "automated-review-pack.jsonl")
    assert len(pack) == 137
    assert [p["case_id"] for p in pack] == sorted(p["case_id"] for p in pack)
    assert all(p["decision"] == "confirmed" for p in pack)
    assert all(p["model"] == ar.MODEL for p in pack)
    assert all(p["attempts"] == 1 for p in pack)
    assert all(p["payload_sha256"] for p in pack)


def test_build_success_evidence_and_review_rows(tmp_path):
    client, _ = _make_stub()
    out, _ = _run_build(tmp_path, client)
    ev = _jsonl(out / "automated-review-evidence.jsonl")
    assert len(ev) == 144
    assert all(e["decision"] == "confirmed" for e in ev)
    rows = _jsonl(out / "automated-review.jsonl")
    assert len(rows) == 137
    assert all(r["status"] == "confirmed" for r in rows)
    raw = _jsonl(out / "raw-model-responses.jsonl")
    assert len(raw) == 137
    assert all(r["model"] == ar.MODEL for r in raw)


def test_build_success_overlay(tmp_path):
    client, _ = _make_stub()
    out, _ = _run_build(tmp_path, client)
    overlay = json.loads((out / "automated-overlay.json").read_text(encoding="utf-8"))
    assert overlay["status"] == "LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_9"
    assert overlay["candidate_scoped"] is True
    assert overlay["case_count"] == 137
    assert overlay["confirmed_count"] == 137
    assert overlay["gate_verdict"] == ar.GATE_OK
    d = overlay["declarations"]
    assert d["is_human_reviewed"] is False
    assert d["is_human_approval"] is False
    assert d["is_active_activation"] is False
    assert d["is_v2_1_entry"] is False
    assert d["is_split_or_lock"] is False
    assert d["candidate_draft_evidence_unchanged"] is True
    assert len(overlay["confirmed_case_ids"]) == 137


def test_build_success_summary_and_manifest(tmp_path):
    client, _ = _make_stub()
    out, result = _run_build(tmp_path, client)
    summary = json.loads((out / "automated-review-summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["case_count"] == 137
    assert summary["counts"]["confirmed"] == 137
    assert summary["counts"]["reject"] == 0
    assert summary["counts"]["needs_followup"] == 0
    assert summary["counts"]["errors"] == 0
    assert summary["model"] == ar.MODEL
    assert summary["parameters"]["temperature"] == 0.0
    assert summary["parameters"]["max_tokens"] == 8000
    assert summary["parameters"]["thinking"] == "disabled"
    assert summary["parameters"]["fallback"] == "none"
    assert summary["parameters"]["max_retries"] == 3
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert ar._verify_self_hash(m)
    assert m["gate_verdict"] == ar.GATE_OK
    # 输出 SHA 与磁盘一致
    for name, h in m["outputs"].items():
        assert _sha(out / name) == h
    # 输入 SHA 与磁盘一致
    for name, h in m["inputs"].items():
        assert _sha(ar.INPUT_CHECK_MAP[name]) == h
    assert m["declarations"]["llm_called"] is True
    assert m["declarations"]["network_used"] is True
    assert m["declarations"]["no_fallback"] is True
    assert m["declarations"]["historical_verdicts_read"] is False
    assert m["declarations"]["human_reviewed"] is False
    assert m["declarations"]["overlay_generated"] is True
    assert m["declarations"]["active_created"] is False
    assert m["declarations"]["split_created"] is False
    assert m["declarations"]["v2_1_entered"] is False
    assert m["metadata"]["revision_status"] == "CANDIDATE"
    assert m["metadata"]["activation_blocked"] is True


def test_build_success_data_quality_five_dims(tmp_path):
    client, _ = _make_stub()
    out, _ = _run_build(tmp_path, client)
    summary = json.loads((out / "automated-review-summary.json").read_text(encoding="utf-8"))
    dq = summary["data_quality"]
    for dim in ("completeness", "uniqueness", "referential_integrity",
                "continuity", "consistency"):
        assert dim in dq
        assert dq[dim]["status"] == "ok"
    assert "skill_note" in summary


def test_build_success_statistics_conservation(tmp_path):
    client, _ = _make_stub()
    out, _ = _run_build(tmp_path, client)
    summary = json.loads((out / "automated-review-summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["answerable_cases"] == 106
    assert summary["counts"]["refusal_cases"] == 31
    assert summary["evidence_per_case_distribution"] == {"1": 78, "2": 22, "3": 4, "4": 1, "6": 1}


def test_build_success_gate_report_and_report(tmp_path):
    client, _ = _make_stub()
    out, _ = _run_build(tmp_path, client)
    gate = (out / "automated-review-gate-report.md").read_text(encoding="utf-8")
    assert ar.GATE_OK in gate
    assert "137/137" in gate
    assert "137" in gate and "144" in gate
    report = (out / "automated-review-report.md").read_text(encoding="utf-8")
    for frag in ("deepseek-v4-pro", "137", "confirmed", "不是人工审核",
                 "不是人工批准", "不是 active", "不是 v2.1"):
        assert frag in report


def test_build_candidate_unchanged(tmp_path):
    before = {p.name: _sha(ar.CANDIDATE / p.name)
              for p in ar.CANDIDATE.iterdir() if p.is_file()}
    client, _ = _make_stub()
    _run_build(tmp_path, client)
    after = {p.name: _sha(ar.CANDIDATE / p.name)
             for p in ar.CANDIDATE.iterdir() if p.is_file()}
    assert before == after


def test_build_twice_byte_identical(tmp_path):
    client, _ = _make_stub()
    out, _ = _run_build(tmp_path, client)
    snapshot = {p.name: p.read_bytes() for p in out.iterdir()}
    out2, _ = _run_build(tmp_path, client, out_name="out2")
    for name, data in snapshot.items():
        assert (out2 / name).read_bytes() == data, name


def _reject_answer(payload: dict) -> dict:
    """对任意 payload 构造 schema 合法的 reject 响应（首个 case 触发）。"""
    n = len(payload["answer_points"])
    assessments = [
        {"answer_point_index": i, "supported": False, "rationale": "证据不足"}
        for i in range(n)
    ]
    return {
        "decision": "reject",
        "answer_point_assessments": assessments,
        "refusal_assessment": {
            "refusal_required": not bool(payload["should_refuse"]),
            "rationale": "拒绝语义与预期不符",
        },
        "rationale": "AP 无直接证据支持或 refusal 语义不符",
    }


def _first_case_blocked_responder(decision="reject"):
    """首个 case 返回指定非 confirmed 判定，其余 confirmed。"""
    state = {"count": 0}

    def responder(messages):
        content = messages[-1]["content"]
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return '{"probe": "ok"}'
        if "query" not in payload:
            return '{"probe": "ok"}'
        state["count"] += 1
        if state["count"] == 1:
            answer = _reject_answer(payload)
            answer["decision"] = decision
            return json.dumps(answer, ensure_ascii=False, sort_keys=True)
        return json.dumps(_confirmed_answer(payload), ensure_ascii=False,
                          sort_keys=True)

    return responder


def test_build_blocked_single_reject(tmp_path):
    client, _ = _make_stub(responder=_first_case_blocked_responder("reject"))
    out, result = _run_build(tmp_path, client)
    assert result["gate"] == ar.GATE_BLOCKED
    files = {p.name for p in out.iterdir()}
    assert files == {
        "automated-review-issues.jsonl",
        "automated-review-gate-report.md",
        "manifest.json",
    }
    # 绝不生成 overlay
    assert not (out / "automated-overlay.json").exists()
    issues = _jsonl(out / "automated-review-issues.jsonl")
    assert len(issues) >= 1
    assert all(i["case_id"] for i in issues)
    assert all(i["kind"] == "reject" for i in issues)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["gate_verdict"] == ar.GATE_BLOCKED
    gate = (out / "automated-review-gate-report.md").read_text(encoding="utf-8")
    assert ar.GATE_BLOCKED in gate


def test_build_blocked_no_overlay_after_success(tmp_path):
    # 先成功构建，再 blocked 构建到同一目录：残留 overlay 必须被清理
    out = tmp_path / "out"
    client, _ = _make_stub()
    ar.run(out_dir=out, candidate_dir=ar.CANDIDATE, chunks_path=ar.CHUNKS_PATH,
           chunk_manifest_path=ar.CHUNK_MANIFEST_PATH,
           current_draft_path=ar.CURRENT_DRAFT_PATH,
           trans_policy_path=ar.TRANS_POLICY_PATH,
           trans_ledger_path=ar.TRANS_LEDGER_PATH, client=client)
    assert (out / "automated-overlay.json").exists()

    client2, _ = _make_stub(responder=_first_case_blocked_responder("needs_followup"))
    result = ar.run(out_dir=out, candidate_dir=ar.CANDIDATE,
                    chunks_path=ar.CHUNKS_PATH,
                    chunk_manifest_path=ar.CHUNK_MANIFEST_PATH,
                    current_draft_path=ar.CURRENT_DRAFT_PATH,
                    trans_policy_path=ar.TRANS_POLICY_PATH,
                    trans_ledger_path=ar.TRANS_LEDGER_PATH, client=client2)
    assert result["gate"] == ar.GATE_BLOCKED
    assert not (out / "automated-overlay.json").exists()
    assert (out / "automated-review-issues.jsonl").exists()
    assert not (out / "automated-review-pack.jsonl").exists()


def test_build_blocked_schema_error(tmp_path):
    calls = []

    def client(messages):
        calls.append(messages)
        if messages[-1]["content"].startswith("Reply with strict JSON"):
            return ar.MODEL, '{"probe": "ok"}', None  # 探针正常
        return ar.MODEL, '{"decision": "confirmed", "unexpected": true}', None

    out, result = _run_build(tmp_path, client)
    assert result["gate"] == ar.GATE_BLOCKED
    issues = _jsonl(out / "automated-review-issues.jsonl")
    assert issues and all(i["kind"] == "error" for i in issues)
    assert not (out / "automated-overlay.json").exists()


def test_preflight_failure_produces_zero_output(tmp_path):
    cand = _copy_candidate(tmp_path)
    _rewrite_manifest(cand, lambda m: m.update({"revision_status": "ACTIVE"}))
    out = tmp_path / "out"
    with pytest.raises(ar.ReviewError):
        ar.run(out_dir=out, candidate_dir=cand, chunks_path=ar.CHUNKS_PATH,
               chunk_manifest_path=ar.CHUNK_MANIFEST_PATH,
               current_draft_path=ar.CURRENT_DRAFT_PATH,
               trans_policy_path=ar.TRANS_POLICY_PATH,
               trans_ledger_path=ar.TRANS_LEDGER_PATH,
               client=_make_stub()[0])
    assert not out.exists()


def test_preflight_failure_no_model_calls(tmp_path):
    cand = _copy_candidate(tmp_path)
    _rewrite_manifest(cand, lambda m: m.update({"revision_status": "ACTIVE"}))
    client, calls = _make_stub()
    with pytest.raises(ar.ReviewError):
        ar.run(out_dir=tmp_path / "out", candidate_dir=cand,
               chunks_path=ar.CHUNKS_PATH,
               chunk_manifest_path=ar.CHUNK_MANIFEST_PATH,
               current_draft_path=ar.CURRENT_DRAFT_PATH,
               trans_policy_path=ar.TRANS_POLICY_PATH,
               trans_ledger_path=ar.TRANS_LEDGER_PATH, client=client)
    assert calls == []


# ── 8. 探针 ─────────────────────────────────────────────────────────────

def test_probe_ok_no_case_data():
    client, calls = _make_stub()
    result = ar.probe(client)
    assert result["ok"] is True
    assert result["model"] == ar.MODEL
    content = calls[0]["messages"][-1]["content"]
    assert "query" not in content
    assert "multi-" not in content


def test_probe_identity_fail():
    def client(messages):
        return "deepseek-v4-flash", '{"probe": "ok"}', None

    with pytest.raises(ar.ReviewError):
        ar.probe(client)


def test_probe_bad_content_fail():
    def client(messages):
        return ar.MODEL, "not json", None

    with pytest.raises(ar.ReviewError):
        ar.probe(client)


# ── 9. CLI ──────────────────────────────────────────────────────────────

def test_cli_build_with_stub(monkeypatch, tmp_path):
    client, _ = _make_stub()
    monkeypatch.setattr(ar, "_DEFAULT_CLIENT", client)
    out = tmp_path / "cli-out"
    rc = ar.main(["build", "--out-dir", str(out)])
    assert rc == 0
    assert (out / "automated-overlay.json").exists()
    assert (out / "manifest.json").exists()


def test_cli_probe_json_with_stub(monkeypatch, capsys):
    client, calls = _make_stub()
    monkeypatch.setattr(ar, "_DEFAULT_CLIENT", client)
    rc = ar.main(["--probe-json"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["ok"] is True
    assert parsed["model"] == ar.MODEL


def test_cli_probe_json_fail(monkeypatch, capsys):
    def client(messages):
        return "deepseek-v4-flash", '{"probe": "ok"}', None

    monkeypatch.setattr(ar, "_DEFAULT_CLIENT", client)
    rc = ar.main(["--probe-json"])
    assert rc == 2


# ── 10. 禁止产物 ────────────────────────────────────────────────────────

def test_no_forbidden_outputs_success(tmp_path):
    client, _ = _make_stub()
    out, _ = _run_build(tmp_path, client)
    names = {p.name for p in out.iterdir()}
    for bad in ("active", "split", "locked", "v2.1", "dev", "holdout"):
        assert not any(n == bad or n.startswith(bad) for n in names)


def test_no_forbidden_outputs_blocked(tmp_path):
    client, _ = _make_stub(responder=_first_case_blocked_responder("reject"))
    out, result = _run_build(tmp_path, client)
    assert result["gate"] == ar.GATE_BLOCKED
    names = {p.name for p in out.iterdir()}
    assert "automated-overlay.json" not in names
    for bad in ("active", "split", "locked", "v2.1", "dev", "holdout"):
        assert not any(n == bad or n.startswith(bad) for n in names)
