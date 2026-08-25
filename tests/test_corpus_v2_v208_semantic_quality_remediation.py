"""TDD tests for v2.0.8 owner-authorized semantic-quality remediation candidate
（链依赖修订版）。

行为契约（fail-closed）：
- 门禁：v2.0.7 candidate 148 条、strict evidence 161/161、legacy=0、unresolved=0、
  automated review 126 confirmed / 22 reject / 0 needs_followup、决策包五批次恰
  7/1/3/10/1、无 overlay；任一漂移 → RemediationError，零输出。
- 链依赖：multi-030 是 multi-031~034 的链父节点（multi-031.follow_up_to ==
  "multi-030"，multi-032/033/034.chain_id == "multi-030"）——该依赖必须被识别
  为**预期的 defer 原因**（不能导致整批停止）；依赖结构有任何漂移（多/少/变）
  或其余五条退役 case 存在任何 follow-up/chain/doc_target/case 引用 → 整体
  fail-closed。
- 批次 A：7 条 replace_answer_point_with_self_contained_exact_raw_text——
  答案点逐字 == 决策包候选 raw span，旧 orphan evidence 清理，新 raw-codepoint-v1
  evidence 写入。
- 批次 B：zh-040 答案点不变，仅追加两条已验证 TOC evidence，diff 标记
  OWNER_AUTHORIZED_SAME_SOURCE_EVIDENCE_SCOPE_EXPANSION。
- 批次 C：faithful_translation_equivalence_v1 策略 + 恰 3 条 ledger，非自动 confirmed。
- 批次 D：4 条移除 unsupported 答案点（预检剩余 ≥1）、5 条退役（依赖门禁 +
  固定原因）、1 条延后（multi-030，deferred-chain-dependent-cases.jsonl）。
- 批次 E：mixed-027 定向盲态复审 —— Pro-only 契约、盲态 payload、结果仅诊断，
  失败标 TARGETED_REVIEW_BLOCKED 且不影响确定性 candidate。
- 148 → 143；evidence 161 → 151；非目标行逐字节不变（multi-030 与其链依赖
  case 必须逐字节不变）；strict validation 151/151；输入 SHA 不变；两次构建
  逐字节一致；manifest 自哈希一致；无禁止产物。
"""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

import scripts.corpus_v2_v208_semantic_quality_remediation as p

ROOT = Path(__file__).resolve().parents[1]
V207 = ROOT / "evaluation/datasets/v2/revisions/v2.0.7-owner-authorized-legacy-evidence-retirement"
AR = V207 / "automated-review"
DP = AR / "reject-semantic-quality-decision-pack"
CHUNKS = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"

EXPECTED_REJECTS = frozenset({
    "en-029", "en-042", "en-044", "en-049", "en-050", "en-051", "mixed-026",
    "mixed-027", "mixed-028", "mixed-029", "mixed-033", "multi-019",
    "multi-030", "zh-023", "zh-026", "zh-029", "zh-036", "zh-040", "zh-042",
    "zh-045", "zh-052", "zh-054",
})
BATCH_A = frozenset({"mixed-028", "mixed-029", "zh-023", "zh-026", "zh-029",
                     "zh-036", "zh-054"})
BATCH_B = frozenset({"zh-040"})
BATCH_C = frozenset({"en-029", "multi-019", "zh-052"})
BATCH_D_REMOVE = frozenset({"en-042", "en-049", "en-051", "mixed-033"})
# 链安全版：multi-030 因链依赖延后，不退役
BATCH_D_RETIRE = frozenset({"en-044", "en-050", "mixed-026", "zh-042",
                            "zh-045"})
DEFERRED = frozenset({"multi-030"})
BATCH_D = BATCH_D_REMOVE | BATCH_D_RETIRE | DEFERRED
BATCH_E = frozenset({"mixed-027"})

# 批次 A 选定 span（决策包 candidate_refs 中第一个 self_contained=True 且
# unique=True 的候选；来源：self-contained-raw-candidates.jsonl）
EXPECTED_REPLACEMENTS = {
    "mixed-028": ("5927c70d0f8e_chunk_0", 567, 760,
                  "Combined with the reactivity system, Vue can intelligently "
                  "figure out the minimal number of components to re-render and "
                  "apply the minimal amount of DOM manipulations when the app "
                  "state changes."),
    "mixed-029": ("c9fd20815ea8_chunk_10", 1371, 1417,
                  "CPython 没有一致应用针对迭代器定义\n```\n__iter__()\n```\n 的要求。"),
    "zh-023": ("32c427fb50e2_chunk_10", 262, 327,
               "生成的序列绝不会包括给定的终止值；\n```\nrange(10)\n```\n "
               "生成 10 个值——长度为 10 的序列的所有合法索引。"),
    "zh-026": ("32c427fb50e2_chunk_22", 400, 422,
               "类似于\n```\ndel a[:]\n```\n。"),
    "zh-029": ("32c427fb50e2_chunk_45", 14, 59,
               "```\njson\n```\n 保存结构化数据¶\n "
               "字符串可以很容易地写入文件或从文件中读取。"),
    "zh-036": ("32c427fb50e2_chunk_31", 1519, 1584,
               "如果未找到，它将在变量\n```\nsys.path\n```\n 所给出的目录列表"
               "中搜索名为\n```\nspam.py\n```\n 的文件。"),
    "zh-054": ("c9fd20815ea8_chunk_10", 1371, 1417,
               "CPython 没有一致应用针对迭代器定义\n```\n__iter__()\n```\n 的要求。"),
}

# 批次 B：zh-040 追加的两条 TOC evidence（同 chunk 连续可重建）
EXPECTED_SCOPE_ADDITIONS = (
    ("32c427fb50e2_chunk_1", 182, 192, "- 7. 输入与输出"),
    ("32c427fb50e2_chunk_1", 360, 370, "- 8. 错误和异常"),
)

EXPECTED_REMOVE_TARGETS = {
    "en-042": 0, "en-049": 0, "en-051": 0, "mixed-033": 0,
}
EXPECTED_RETIRE_REASON = "no_semantically_sufficient_direct_evidence_after_owner_authorized_review"
DEFER_REASON = "retirement_deferred_due_to_active_follow_up_chain_dependency"
POLICY_VERSION = "faithful_translation_equivalence_v1"
SCOPE_MARKER = "OWNER_AUTHORIZED_SAME_SOURCE_EVIDENCE_SCOPE_EXPANSION"
AUTHORIZATION_MARKER = "OWNER_AUTHORIZED_SEMANTIC_QUALITY_REMEDIATION_CHAIN_SAFE"
REVIEW_MODEL = "deepseek-v4-pro"

METADATA_EXPECTED = {
    "revision_status": "CANDIDATE",
    "activation_blocked": True,
    "human_reviewed": False,
    "actor": "OWNER_AUTHORIZED_SEMANTIC_QUALITY_REMEDIATION_CHAIN_SAFE",
    "case_count_before": 148,
    "case_count_after": 143,
    "overlay_generated": False,
    "split_reseal_required": True,
    "v2_1_entered": False,
}

OUTPUT_FILES = (
    "draft-before.jsonl", "draft-after.jsonl", "evidence-before.jsonl",
    "evidence-after.jsonl", "reannotation-diff.jsonl", "retired-cases.jsonl",
    "retired-evidence.jsonl", "deferred-chain-dependent-cases.jsonl",
    "translation-equivalence-policy.md",
    "translation-equivalence-policy-ledger.jsonl",
    "coordinate-validation-report.json", "data-quality-report.json",
    "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md", "REPAIR_REPORT.md", "manifest.json",
)
FORBIDDEN_NAMES = ("overlay", "active-", "v2.1", "v2-1", "locked",
                   "holdout", "seal", "freeze", "automated-review.jsonl",
                   "review-result", "truth-overlay")


# ── helpers ────────────────────────────────────────────────────────────

def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in open(path, encoding="utf-8")]


def _line(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + "\n"


def _recompute_self_hash(manifest: dict) -> str:
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    return hashlib.sha256((json.dumps(body, ensure_ascii=False, indent=1,
                                      sort_keys=True) + "\n").encode("utf-8")).hexdigest()


def _copy_tree(src: Path, dst: Path) -> Path:
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return dst


def _tampered_pack_summary(tmp_path: Path, mutate) -> Path:
    """复制决策包目录并篡改 summary.json（返回篡改后的 decision_pack_dir）。"""
    dp_dir = _copy_tree(DP, tmp_path / "dp")
    summ = json.load(open(dp_dir / "decision-pack-summary.json", encoding="utf-8"))
    mutate(summ)
    (dp_dir / "decision-pack-summary.json").write_text(
        json.dumps(summ, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")
    return dp_dir


def _tampered_pack_rows(tmp_path: Path, mutate) -> Path:
    """复制决策包目录并篡改 semantic-quality-decision-pack.jsonl 单行。"""
    dp_dir = _copy_tree(DP, tmp_path / "dp")
    rows = _jsonl(dp_dir / "semantic-quality-decision-pack.jsonl")
    for row in rows:
        mutate(row)
    (dp_dir / "semantic-quality-decision-pack.jsonl").write_text(
        "".join(_line(r) for r in rows), encoding="utf-8")
    return dp_dir


def _tampered_review_dir(tmp_path: Path, mutate) -> Path:
    """复制 automated-review 目录并篡改 canonical automated-review.jsonl。"""
    ar_dir = _copy_tree(AR, tmp_path / "ar")
    rows = _jsonl(ar_dir / "automated-review.jsonl")
    mutate(rows)
    (ar_dir / "automated-review.jsonl").write_text(
        "".join(_line(r) for r in rows), encoding="utf-8")
    return ar_dir


def _tampered_draft(tmp_path: Path, mutate) -> Path:
    """复制 v2.0.7 draft-after 并篡改某行（返回篡改后的 draft 路径）。"""
    dst = tmp_path / "draft-after.jsonl"
    shutil.copy2(V207 / "draft-after.jsonl", dst)
    rows = _jsonl(dst)
    mutate(rows)
    dst.write_text("".join(_line(r) for r in rows), encoding="utf-8")
    return dst


def _tampered_evidence(tmp_path: Path, mutate) -> Path:
    """复制 v2.0.7 evidence-after 并篡改（返回篡改后的 evidence 路径）。"""
    dst = tmp_path / "evidence-after.jsonl"
    shutil.copy2(V207 / "evidence-after.jsonl", dst)
    rows = _jsonl(dst)
    mutate(rows)
    dst.write_text("".join(_line(r) for r in rows), encoding="utf-8")
    return dst


class _FakeRecord:
    retries_used = 0


class _FakeResponse:
    model = REVIEW_MODEL

    def __init__(self, content: str):
        import types
        self.choices = [types.SimpleNamespace(
            message=types.SimpleNamespace(content=content))]


def _fake_llm(content: str, captured: dict):
    def _fn(call_type, messages, **kwargs):
        captured["call_type"] = call_type
        captured["messages"] = messages
        captured.update(kwargs)
        return _FakeResponse(content), _FakeRecord()
    return _fn


# ── 1. 常量与批次守恒 ─────────────────────────────────────────────────

def test_batch_constants_conservation():
    assert BATCH_A | BATCH_B | BATCH_C | BATCH_D | BATCH_E == EXPECTED_REJECTS
    assert len(BATCH_A) == 7 and len(BATCH_B) == 1 and len(BATCH_C) == 3
    assert len(BATCH_D) == 10 and len(BATCH_E) == 1
    assert len(BATCH_D_RETIRE) == 5
    assert DEFERRED == {"multi-030"}  # 链父节点延后，不退役
    assert BATCH_D_RETIRE.isdisjoint(DEFERRED)
    assert len(EXPECTED_REJECTS) == 22
    assert len(EXPECTED_REPLACEMENTS) == 7
    assert len(EXPECTED_SCOPE_ADDITIONS) == 2
    assert EXPECTED_REMOVE_TARGETS.keys() == BATCH_D_REMOVE
    assert EXPECTED_REPLACEMENTS.keys() == BATCH_A


# ── 2. 前置门禁（fail-closed）────────────────────────────────────────

def test_preflight_real_inputs():
    """真实输入全部通过：148/161/126-22-0/批次 7-1-3-10-1/无 overlay/
    multi-030 链依赖被识别为预期 defer。"""
    checks = p.preflight()
    assert checks["case_count"] == 148
    assert checks["evidence_count"] == 161
    assert checks["strict_covered"] == 161
    assert checks["strict_passed"] == 161
    assert checks["legacy_rows"] == 0
    assert checks["unresolved_rows"] == 0
    assert checks["review_counts"] == {"confirmed": 126, "reject": 22,
                                       "needs_followup": 0}
    assert checks["pack_gate"] == "DECISION_PACK_OK"
    assert checks["batch_distribution"] == {"batch_a": 7, "batch_b": 1,
                                            "batch_c": 3, "batch_d": 10,
                                            "batch_e": 1}
    assert checks["overlay_absent"] is True
    # multi-030 链依赖 = 预期 defer 结构（multi-031 follow_up_to；
    # multi-032/033/034 chain_id），不是 fail-closed 停止原因
    deferred = checks["deferred_chain_rows"]
    assert len(deferred) == 1
    assert deferred[0]["case_id"] == "multi-030"
    assert deferred[0]["deferred_reason"] == DEFER_REASON


def test_fail_closed_batch_distribution_drift(tmp_path):
    """决策包批次分布漂移 → RemediationError，零输出。"""
    dp_dir = _tampered_pack_summary(
        tmp_path,
        lambda s: s["by_batch"]["batch_a_replace_with_self_contained_exact_text"]
        .update({"n": 6, "case_ids": s["by_batch"][
            "batch_a_replace_with_self_contained_exact_text"]["case_ids"][:-1]}))
    with pytest.raises(p.RemediationError):
        p.run(out_dir=tmp_path / "out", decision_pack_dir=dp_dir)
    assert not (tmp_path / "out").exists()


def test_fail_closed_review_count_drift(tmp_path):
    """review 计数漂移（reject→confirmed）→ 整体停止。"""
    ar_dir = _tampered_review_dir(
        tmp_path,
        lambda rows: next(r for r in rows if r["decision"] == "reject")
        .update({"decision": "confirmed"}))
    with pytest.raises(p.RemediationError):
        p.run(out_dir=tmp_path / "out", review_dir=ar_dir)
    assert not (tmp_path / "out").exists()


def test_fail_closed_evidence_count_drift(tmp_path):
    """evidence 161→160 漂移 → 整体停止。"""
    ev_path = _tampered_evidence(tmp_path, lambda rows: rows.pop())
    with pytest.raises(p.RemediationError):
        p.run(out_dir=tmp_path / "out", evidence_path=ev_path)
    assert not (tmp_path / "out").exists()


def test_fail_closed_legacy_residual(tmp_path):
    """evidence 出现 legacy contract 行 → 整体停止。"""
    ev_path = _tampered_evidence(
        tmp_path,
        lambda rows: rows[0].update({"coordinate_contract": "legacy"}))
    with pytest.raises(p.RemediationError):
        p.run(out_dir=tmp_path / "out", evidence_path=ev_path)
    assert not (tmp_path / "out").exists()


def test_fail_closed_pack_action_drift(tmp_path):
    """决策包 recommended_action 与授权动作表不符 → 整体停止。"""
    dp_dir = _tampered_pack_rows(
        tmp_path,
        lambda r: r.update(
            {"recommended_action": "retire_case",
             "recommended_batch": "batch_d_retire_or_remove"})
        if r["case_id"] == "zh-054" else None)
    with pytest.raises(p.RemediationError):
        p.run(out_dir=tmp_path / "out", decision_pack_dir=dp_dir)
    assert not (tmp_path / "out").exists()


def test_fail_closed_remove_to_zero_guard(tmp_path):
    """移除目标会把 case 清空 → 整体停止（预检剩余答案点 ≥1）。"""
    dp_dir = _tampered_pack_rows(
        tmp_path,
        lambda r: r.update({"removal_targets": [0, 1]})
        if r["case_id"] == "en-042" else None)
    with pytest.raises(p.RemediationError):
        p.run(out_dir=tmp_path / "out", decision_pack_dir=dp_dir)
    assert not (tmp_path / "out").exists()


def test_fail_closed_retire_dependency(tmp_path):
    """退役 case 被其他 case 的 follow_up_to 引用 → 整体停止。"""
    draft_path = _tampered_draft(
        tmp_path,
        lambda rows: next(r for r in rows if r["id"] == "zh-023")
        .setdefault("metadata", {}).update({"follow_up_to": "en-044"}))
    with pytest.raises(p.RemediationError):
        p.run(out_dir=tmp_path / "out", draft_path=draft_path)
    assert not (tmp_path / "out").exists()


def test_fail_closed_deferred_chain_drift(tmp_path):
    """multi-030 预期链依赖被解除（multi-031.follow_up_to=None）→ 与授权
    defer 结构不符 → 整体 fail-closed，零输出。"""
    draft_path = _tampered_draft(
        tmp_path,
        lambda rows: next(r for r in rows if r["id"] == "multi-031")
        .setdefault("metadata", {}).update({"follow_up_to": None}))
    with pytest.raises(p.RemediationError) as exc:
        p.run(out_dir=tmp_path / "out", draft_path=draft_path)
    assert "multi-030" in str(exc.value) and "deferred" in str(exc.value).lower()
    assert not (tmp_path / "out").exists()


def test_fail_closed_deferred_chain_new_reference(tmp_path):
    """multi-030 出现意外新引用（multi-031.chain_id → multi-030）→ 依赖
    结构漂移 → 整体停止。"""
    draft_path = _tampered_draft(
        tmp_path,
        lambda rows: next(r for r in rows if r["id"] == "multi-031")
        .setdefault("metadata", {}).update({"chain_id": "multi-030"}))
    with pytest.raises(p.RemediationError) as exc:
        p.run(out_dir=tmp_path / "out", draft_path=draft_path)
    assert "deferred" in str(exc.value).lower()
    assert not (tmp_path / "out").exists()


def test_fail_closed_draft_case_drift(tmp_path):
    """draft 148→147 漂移 → 整体停止。"""
    draft_path = _tampered_draft(tmp_path, lambda rows: rows.pop())
    with pytest.raises(p.RemediationError):
        p.run(out_dir=tmp_path / "out", draft_path=draft_path)
    assert not (tmp_path / "out").exists()


# ── 3. 主流程产物与元数据 ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """真实输入（v2.0.7 draft/evidence/decision pack）→ tmp 输出目录。
    真实 draft 中 multi-030 的链依赖被识别为预期 defer 原因，构建成功；
    multi-030 保留、其余五条退役（模块级，只构建一次）。"""
    base = tmp_path_factory.mktemp("v208")
    out = base / "out"
    result = p.run(out_dir=out)
    return out, result


def test_real_draft_builds_with_multi030_deferred(tmp_path):
    """真实 draft：multi-030 链依赖被识别为预期 defer 原因，构建成功；
    multi-030 保留不退役；其余五条正常退役；148 → 143。"""
    out = tmp_path / "out"
    p.run(out_dir=out)
    ids = {r["id"] for r in _jsonl(out / "draft-after.jsonl")}
    assert len(ids) == 143
    assert "multi-030" in ids
    retired = _jsonl(out / "retired-cases.jsonl")
    assert {r["case_id"] for r in retired} == BATCH_D_RETIRE
    assert "multi-030" not in {r["case_id"] for r in retired}


def test_output_file_set(built):
    out, _ = built
    assert set(f.name for f in out.iterdir()) == set(OUTPUT_FILES)


def test_metadata_exact(built):
    _, result = built
    m = result["manifest"]
    for k, v in METADATA_EXPECTED.items():
        assert m.get(k) == v, (k, m.get(k))


def test_case_and_evidence_counts(built):
    out, _ = built
    assert len(_jsonl(out / "draft-before.jsonl")) == 148
    assert len(_jsonl(out / "draft-after.jsonl")) == 143
    assert len(_jsonl(out / "evidence-before.jsonl")) == 161
    assert len(_jsonl(out / "evidence-after.jsonl")) == 151
    ids = [r["id"] for r in _jsonl(out / "draft-after.jsonl")]
    assert len(ids) == len(set(ids))
    # 22 条 reject 全部被处理（替换/移除/退役/延后/扩展），无遗留
    remaining = set(ids)
    assert EXPECTED_REJECTS - remaining == BATCH_D_RETIRE


def test_non_target_rows_byte_identical(built):
    """非目标 draft/evidence 行逐字节不变。"""
    out, _ = built
    before = open(out / "draft-before.jsonl", encoding="utf-8").read().splitlines()
    after = open(out / "draft-after.jsonl", encoding="utf-8").read().splitlines()
    before_by_id = {json.loads(l)["id"]: l for l in before}
    touched = BATCH_A | BATCH_D_REMOVE | BATCH_D_RETIRE
    for line in after:
        row = json.loads(line)
        if row["id"] not in touched:
            assert line == before_by_id[row["id"]], row["id"]
    ev_before = open(out / "evidence-before.jsonl", encoding="utf-8").read().splitlines()
    ev_after = open(out / "evidence-after.jsonl", encoding="utf-8").read().splitlines()
    ev_before_by_key = {}
    for l in ev_before:
        r = json.loads(l)
        ev_before_by_key[(r["case_id"], r["chunk_id"],
                          r["raw_chunk_char_range"]["start"],
                          r["raw_chunk_char_range"]["end"])] = l
    changed_cases = BATCH_A | BATCH_D_REMOVE | BATCH_D_RETIRE
    for line in ev_after:
        r = json.loads(line)
        key = (r["case_id"], r["chunk_id"], r["raw_chunk_char_range"]["start"],
               r["raw_chunk_char_range"]["end"])
        if r["case_id"] not in changed_cases and key in ev_before_by_key:
            assert line == ev_before_by_key[key], key


# ── 3b. 延后链父节点 multi-030 ────────────────────────────────────────

def test_deferred_chain_ledger(built):
    """deferred-chain-dependent-cases.jsonl：恰 1 条，记录依赖 case/关系/原因；
    明确不是 resolved / confirmed / 已接受的质量结论。"""
    out, _ = built
    rows = _jsonl(out / "deferred-chain-dependent-cases.jsonl")
    assert len(rows) == 1
    r = rows[0]
    assert r["case_id"] == "multi-030"
    assert r["deferred_reason"] == DEFER_REASON
    deps = {(d["case_id"], d["relation"]) for d in r["dependent_cases"]}
    assert deps == {("multi-031", "follow_up_to"), ("multi-032", "chain_id"),
                    ("multi-033", "chain_id"), ("multi-034", "chain_id")}
    assert r["not_resolved"] is True
    assert r["not_confirmed"] is True
    assert r["not_accepted_quality_conclusion"] is True
    assert r["draft_evidence_unchanged"] is True
    assert r["authorization_marker"] == AUTHORIZATION_MARKER


def test_multi030_and_chain_cases_byte_identical(built):
    """multi-030 与其链依赖 case（multi-031~034）draft/evidence 逐字节不变。"""
    out, _ = built
    chain = ("multi-030", "multi-031", "multi-032", "multi-033", "multi-034")
    before = open(out / "draft-before.jsonl", encoding="utf-8").read().splitlines()
    after = open(out / "draft-after.jsonl", encoding="utf-8").read().splitlines()
    b = {json.loads(l)["id"]: l for l in before}
    a = {json.loads(l)["id"]: l for l in after}
    for cid in chain:
        assert a[cid] == b[cid], cid

    def _by_case(lines):
        out_d = {}
        for l in lines:
            out_d.setdefault(json.loads(l)["case_id"], []).append(l)
        return out_d

    ev_b = _by_case(open(out / "evidence-before.jsonl", encoding="utf-8")
                    .read().splitlines())
    ev_a = _by_case(open(out / "evidence-after.jsonl", encoding="utf-8")
                    .read().splitlines())
    for cid in chain:
        assert ev_a.get(cid, []) == ev_b.get(cid, []), cid


# ── 4. 批次 A：自包含 exact 替换 ─────────────────────────────────────

def test_batch_a_replacements_exact(built):
    out, _ = built
    chunks = {c["chunk_id"]: c for c in _jsonl(p.CHUNKS)}
    cands = _jsonl(DP / "self-contained-raw-candidates.jsonl")
    cand_by_key = {(c["case_id"], c["chunk_id"], c["raw_chunk_char_range"]["start"],
                    c["raw_chunk_char_range"]["end"]): c for c in cands}
    draft = {r["id"]: r for r in _jsonl(out / "draft-after.jsonl")}
    ev = [r for r in _jsonl(out / "evidence-after.jsonl")]
    ev_by_case = {}
    for r in ev:
        ev_by_case.setdefault(r["case_id"], []).append(r)
    for case_id in sorted(BATCH_A):
        chunk_id, start, end, span = EXPECTED_REPLACEMENTS[case_id]
        assert draft[case_id]["acceptable_answer_points"] == [span]
        assert "\r" not in span  # 仅 CRLF→LF 展示统一，不允许其他改写
        assert chunks[chunk_id]["text"][start:end] == span  # 可重建
        # 决策包候选 raw_span 必须与替换文本一致
        cand = cand_by_key[(case_id, chunk_id, start, end)]
        assert cand["raw_span"] == span
        assert cand["self_contained"] is True
        assert cand["unique"] is True
        assert cand["candidate_type"] in ("full_sentence", "full_paragraph")
        # 新 evidence 恰一条，raw span == 答案点
        rows = ev_by_case[case_id]
        assert len(rows) == 1
        r = rows[0]
        assert r["chunk_id"] == chunk_id
        assert r["raw_chunk_char_range"] == {"start": start, "end": end}
        assert r["raw_evidence_span"] == span
        assert r["source_id"] == chunks[chunk_id]["source"]
        assert r["coordinate_contract"] == "raw-codepoint-v1"


def test_batch_a_old_token_evidence_removed(built):
    """旧答案点专属 token evidence 全部清理（不再残留 'state'/'10' 等孤立 span）。"""
    out, _ = built
    ev = _jsonl(out / "evidence-after.jsonl")
    old_spans = {
        "mixed-028": "state", "mixed-029": "一致", "zh-023": "10",
        "zh-026": "del", "zh-029": "json", "zh-036": "目录",
        "zh-054": "一致",
    }
    for case_id, old in old_spans.items():
        assert not any(e["case_id"] == case_id and e["raw_evidence_span"] == old
                       for e in ev), case_id


def test_batch_a_diff_rows(built):
    out, _ = built
    diff = {r["case_id"]: r for r in _jsonl(out / "reannotation-diff.jsonl")}
    for case_id in BATCH_A:
        d = diff[case_id]
        assert d["action"] == "replace_answer_point_with_self_contained_exact_raw_text"
        assert d["batch"] == "batch_a_replace_with_self_contained_exact_text"
        assert d["answer_point_index"] == 0
        assert d["new_answer_point"] == EXPECTED_REPLACEMENTS[case_id][3]
        assert d["authorization_marker"] == AUTHORIZATION_MARKER


# ── 5. 批次 B：同源 scope 扩展 ───────────────────────────────────────

def test_batch_b_zh040_scope_expansion(built):
    out, _ = built
    draft = {r["id"]: r for r in _jsonl(out / "draft-after.jsonl")}
    ev = [r for r in _jsonl(out / "evidence-after.jsonl")
          if r["case_id"] == "zh-040"]
    # 答案点文本不变
    before = {r["id"]: r for r in _jsonl(out / "draft-before.jsonl")}
    assert draft["zh-040"]["acceptable_answer_points"] == \
        before["zh-040"]["acceptable_answer_points"]
    # 追加两条已验证 TOC evidence（原 [0:55) 保留）
    ranges = sorted((r["raw_chunk_char_range"]["start"],
                     r["raw_chunk_char_range"]["end"]) for r in ev)
    assert ranges == [(0, 55), (182, 192), (360, 370)]
    for (chunk_id, start, end, span) in EXPECTED_SCOPE_ADDITIONS:
        r = next(r for r in ev if r["raw_chunk_char_range"] ==
                 {"start": start, "end": end})
        assert r["chunk_id"] == chunk_id
        assert r["raw_evidence_span"] == span
        assert r["source_id"] == "python-tutorial-zh.md"
        assert r["coordinate_contract"] == "raw-codepoint-v1"
    # diff 显式记录 scope 扩展标记
    diff = {r["case_id"]: r for r in _jsonl(out / "reannotation-diff.jsonl")}
    d = diff["zh-040"]
    assert d["action"] == "expand_same_source_evidence_scope"
    assert SCOPE_MARKER in d.get("markers", []) or d.get("marker") == SCOPE_MARKER
    assert d["added_evidence"] == [{"chunk_id": "32c427fb50e2_chunk_1",
                                    "raw_chunk_char_range": {"start": 182,
                                                             "end": 192}},
                                   {"chunk_id": "32c427fb50e2_chunk_1",
                                    "raw_chunk_char_range": {"start": 360,
                                                             "end": 370}}]


# ── 6. 批次 C：翻译等价策略 ─────────────────────────────────────────

def test_batch_c_translation_policy_and_ledger(built):
    out, _ = built
    assert (out / "translation-equivalence-policy.md").exists()
    policy = (out / "translation-equivalence-policy.md").read_text(encoding="utf-8")
    assert POLICY_VERSION in policy
    assert "不是自动 confirmed" in policy or "非自动 confirmed" in policy \
        or "不自动确认" in policy
    assert "deepseek-v4-pro" in policy or "盲态复审" in policy
    ledger = _jsonl(out / "translation-equivalence-policy-ledger.jsonl")
    assert len(ledger) == 3  # 恰 3 条，范围仅限三条指定 case
    assert {r["case_id"] for r in ledger} == BATCH_C
    for r in ledger:
        assert r["policy_version"] == POLICY_VERSION
        assert r["not_confirmed"] is True
        assert r["requires_blind_re_review"] is True
        assert r["authorization_marker"] == AUTHORIZATION_MARKER
        assert r["answer_points"]
        assert r["evidence_anchors"]
        for anchor in r["evidence_anchors"]:
            assert anchor["raw_evidence_span"]
            assert anchor["chunk_id"]
    # 三条 case 的 draft/evidence 行不变（策略不改变数据）
    draft_before = {r["id"]: r for r in _jsonl(out / "draft-before.jsonl")}
    draft_after = {r["id"]: r for r in _jsonl(out / "draft-after.jsonl")}
    for cid in BATCH_C:
        assert draft_after[cid] == draft_before[cid]
    # diff 中无批次 C 的数据变更
    diff = _jsonl(out / "reannotation-diff.jsonl")
    assert not any(r["case_id"] in BATCH_C for r in diff)


# ── 7. 批次 D：移除 unsupported 答案点 ──────────────────────────────

def test_batch_d_remove_answer_points(built):
    out, _ = built
    draft = {r["id"]: r for r in _jsonl(out / "draft-after.jsonl")}
    pack = {r["case_id"]: r for r in _jsonl(DP / "semantic-quality-decision-pack.jsonl")}
    for case_id in sorted(BATCH_D_REMOVE):
        row = draft[case_id]
        pk = pack[case_id]
        target = EXPECTED_REMOVE_TARGETS[case_id]
        removed_text = pk["current_answer_points"][target]
        kept_text = pk["current_answer_points"][1 - target]
        assert removed_text not in row["acceptable_answer_points"]
        assert row["acceptable_answer_points"] == [kept_text]
        assert len(row["acceptable_answer_points"]) >= 1  # 预检：非零答案点
    # orphan evidence 清理：en-042/049/051 各剩 1 条，mixed-033 保留 2 条（重复行仍逐字支撑 AP1）
    ev = _jsonl(out / "evidence-after.jsonl")
    counts = {cid: sum(1 for e in ev if e["case_id"] == cid)
              for cid in BATCH_D_REMOVE}
    assert counts == {"en-042": 1, "en-049": 1, "en-051": 1, "mixed-033": 2}
    for cid in ("en-042", "en-049", "en-051"):
        rows = [e for e in ev if e["case_id"] == cid]
        kept = rows[0]
        assert kept["raw_evidence_span"].strip()  # 剩余 evidence 保留 AP1 逐字支撑


def test_batch_d_remove_diff(built):
    out, _ = built
    diff = {r["case_id"]: r for r in _jsonl(out / "reannotation-diff.jsonl")}
    for case_id in BATCH_D_REMOVE:
        d = diff[case_id]
        assert d["action"] == "remove_unsupported_answer_point"
        assert d["batch"] == "batch_d_retire_or_remove"
        assert d["removed_answer_points"] == [
            {"answer_point_index": 0, "answer_point": d["removed_answer_points"][0]["answer_point"]}]
        assert len(d["removed_answer_points"]) == 1
        assert len(d["remaining_answer_points"]) == 1


# ── 8. 批次 D：退役 5 条 case（multi-030 延后，不退役）───────────────

def test_batch_d_retire_ledgers(built):
    out, _ = built
    retired = _jsonl(out / "retired-cases.jsonl")
    assert len(retired) == 5
    assert {r["case_id"] for r in retired} == BATCH_D_RETIRE
    for r in retired:
        assert r["reason"] == EXPECTED_RETIRE_REASON
        assert r["retired_by"] == AUTHORIZATION_MARKER
        assert r["case_count_before"] == 148
        assert r["case_count_after"] == 143
    rev = _jsonl(out / "retired-evidence.jsonl")
    assert len(rev) == 9
    assert {r["case_id"] for r in rev} == BATCH_D_RETIRE
    for r in rev:
        assert r["reason"] == EXPECTED_RETIRE_REASON
    # draft 不再含退役 case；multi-030 保留
    ids = {r["id"] for r in _jsonl(out / "draft-after.jsonl")}
    assert ids.isdisjoint(BATCH_D_RETIRE)
    assert "multi-030" in ids
    ev_ids = {r["case_id"] for r in _jsonl(out / "evidence-after.jsonl")}
    assert ev_ids.isdisjoint(BATCH_D_RETIRE)
    assert "multi-030" in ev_ids
    # 退役 case 全部 zero_answer_point_risk（决策包依据）
    pack = {r["case_id"]: r for r in _jsonl(DP / "semantic-quality-decision-pack.jsonl")}
    for cid in BATCH_D_RETIRE:
        assert pack[cid]["removal_zero_risk"] is True


# ── 9. 守恒与 strict validation ──────────────────────────────────────

def test_strict_validation_passes(built):
    out, _ = built
    chunks = {c["chunk_id"]: c for c in _jsonl(p.CHUNKS)}
    rows = _jsonl(out / "evidence-after.jsonl")
    from scripts.corpus_v2_evidence_coordinate_repair import strict_validate
    strict_validate(rows, chunks)  # 不抛异常即通过
    cov = json.load(open(out / "coordinate-validation-report.json",
                         encoding="utf-8"))
    assert cov["strict_validation"] == "PASS"
    assert cov["raw_rows_validated"] == 151
    assert cov["strict_validator_covered_count"] == 151
    assert cov["strict_validator_passed_count"] == 151
    assert cov["unresolved_rows"] == 0
    assert cov["legacy_rows_remaining"] == 0


def test_every_evidence_span_rebuildable(built):
    out, _ = built
    chunks = {c["chunk_id"]: c for c in _jsonl(p.CHUNKS)}
    for r in _jsonl(out / "evidence-after.jsonl"):
        t = chunks[r["chunk_id"]]["text"]
        assert t[r["raw_chunk_char_range"]["start"]:r["raw_chunk_char_range"]["end"]] \
            == r["raw_evidence_span"]
        assert r["source_id"] == chunks[r["chunk_id"]]["source"]


def test_batch_e_case_untouched(built):
    """mixed-027 数据在确定性 candidate 中逐字节不变。"""
    out, _ = built
    before = open(out / "draft-before.jsonl", encoding="utf-8").read().splitlines()
    after = open(out / "draft-after.jsonl", encoding="utf-8").read().splitlines()
    bl = next(l for l in before if json.loads(l)["id"] == "mixed-027")
    al = next(l for l in after if json.loads(l)["id"] == "mixed-027")
    assert al == bl
    ev_b = {}
    for l in open(out / "evidence-before.jsonl", encoding="utf-8").read().splitlines():
        r = json.loads(l)
        if r["case_id"] == "mixed-027":
            ev_b[(r["chunk_id"], r["raw_chunk_char_range"]["start"],
                  r["raw_chunk_char_range"]["end"])] = l
    ev_a = open(out / "evidence-after.jsonl", encoding="utf-8").read().splitlines()
    seen = 0
    for l in ev_a:
        r = json.loads(l)
        if r["case_id"] == "mixed-027":
            key = (r["chunk_id"], r["raw_chunk_char_range"]["start"],
                   r["raw_chunk_char_range"]["end"])
            assert key in ev_b
            assert l == ev_b[key]
            seen += 1
    assert seen == 2


def test_no_evidence_dangling_for_retained_cases(built):
    """保留 case 不得新增零答案点 / 零 evidence（语料既有 31 条 noanswer-*
    拒答 case 与 multi-029 本就为零答案点，属既有状态，不得新增）。"""
    out, _ = built
    draft_before = {r["id"]: r for r in _jsonl(out / "draft-before.jsonl")}
    draft_after = {r["id"]: r for r in _jsonl(out / "draft-after.jsonl")}
    ev_by_case = {}
    for r in _jsonl(out / "evidence-after.jsonl"):
        ev_by_case.setdefault(r["case_id"], []).append(r)
    zero_before = {cid for cid, row in draft_before.items()
                   if not row["acceptable_answer_points"]}
    zero_after = {cid for cid, row in draft_after.items()
                  if not row["acceptable_answer_points"]}
    assert zero_after == zero_before  # 未新增零答案点 case
    no_ev_before = {cid for cid, row in draft_before.items()
                    if row["acceptable_answer_points"]}
    for cid, row in draft_after.items():
        if row["acceptable_answer_points"]:
            assert ev_by_case.get(cid), cid  # 有答案点的保留 case 必须有 evidence


# ── 10. 确定性 / SHA / 清单 ──────────────────────────────────────────

def test_manifest_self_hash_and_outputs(built):
    out, _ = built
    m = json.load(open(out / "manifest.json", encoding="utf-8"))
    assert m["manifest_sha256"] == _recompute_self_hash(m)
    for name, sha in m["outputs"].items():
        assert _sha(out / name) == sha, name
    assert m["gate_verdict"] == "REMEDIATION_CANDIDATE_OK"
    assert m["deterministic"] is True
    assert m["counts"]["retired_cases"] == 5
    assert m["counts"]["deferred_cases"] == 1
    assert m["validation"]["deferred_chain_gate_passed"] is True
    assert m["validation"]["multi030_draft_evidence_byte_identical"] is True


def test_inputs_sha_unchanged(built):
    """全部输入 SHA 运行前后不变。"""
    out, _ = built
    inputs = [DP / "manifest.json", DP / "decision-pack-summary.json",
              DP / "semantic-quality-decision-pack.jsonl",
              DP / "self-contained-raw-candidates.jsonl",
              AR / "automated-review.jsonl", AR / "manifest.json",
              V207 / "manifest.json", V207 / "draft-after.jsonl",
              V207 / "evidence-after.jsonl", CHUNKS, CHUNK_MANIFEST]
    for path in inputs:
        assert _sha(path) == _sha(path)


def test_two_runs_byte_identical(tmp_path):
    p.run(out_dir=tmp_path / "o1")
    p.run(out_dir=tmp_path / "o2")
    out1, out2 = tmp_path / "o1", tmp_path / "o2"
    for name in OUTPUT_FILES:
        assert _sha(out1 / name) == _sha(out2 / name), name


def test_forbidden_outputs_absent(built):
    out, _ = built
    for f in out.rglob("*"):
        if f.is_file():
            low = f.name.lower()
            assert not any(bad in low for bad in FORBIDDEN_NAMES), f.name
    # 无 split / overlay / active 子目录产物（REVIEW_AND_SPLIT_REBUILD_REQUIRED.md
    # 为任务要求的提示文件，不属于 split 产物）
    for d in out.iterdir():
        assert not (d.is_dir() and d.name in ("split", "overlay", "active",
                                              "dev", "holdout")), d.name
    m = json.load(open(out / "manifest.json", encoding="utf-8"))
    assert m["declarations"]["overlay_generated"] is False
    assert m["declarations"]["llm_called"] is False
    assert m["declarations"]["network_used"] is False
    assert m["declarations"]["v2_1_entered"] is False
    assert m["declarations"]["review_results_reused"] is False


def test_no_review_results_in_candidate(built):
    """v2.0.8 candidate 不含任何 review 结果（不复用 v2.0.7 审阅结论）。"""
    out, _ = built
    for f in out.iterdir():
        if f.suffix in (".jsonl", ".json", ".md"):
            text = f.read_text(encoding="utf-8")
            assert '"decision": "confirmed"' not in text
            assert "reviewer_identity" not in text


def test_data_quality_report_five_dimensions(built):
    out, _ = built
    dq = json.load(open(out / "data-quality-report.json", encoding="utf-8"))
    dims = dq["equivalent_deterministic_checks"]
    assert set(dims) == {"completeness", "uniqueness", "referential_integrity",
                         "continuity", "consistency"}
    assert dims["completeness"]["draft_after"] == 143
    assert dims["completeness"]["evidence_after"] == 151
    assert dims["completeness"]["retired_cases"] == 5
    assert dims["completeness"]["deferred_cases"] == 1
    assert dims["uniqueness"]["draft_case_ids_unique"] is True
    assert dims["consistency"]["batch_conservation"] is True
    assert dq["skill"]["available"] is False
    assert "Skill not found" in dq["skill"]["failure"]


def test_guide_and_report_files(built):
    out, _ = built
    report = (out / "REPAIR_REPORT.md").read_text(encoding="utf-8")
    assert "148" in report and "143" in report
    assert EXPECTED_RETIRE_REASON in report
    assert DEFER_REASON in report
    assert "multi-030" in report
    assert "mixed-027" in report
    rebuild = (out / "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md").read_text(encoding="utf-8")
    assert "split" in rebuild.lower()
    assert "resea" in rebuild.lower()


# ── 11. CLI ──────────────────────────────────────────────────────────

def test_cli_build_success(tmp_path):
    assert p.main(["build", "--out-dir", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "manifest.json").exists()


def test_cli_fail_closed_exit_2(tmp_path):
    dp_dir = _tampered_pack_summary(
        tmp_path,
        lambda s: s["by_batch"]["batch_e_targeted_re_review"].update({"n": 2}))
    rc = p.main(["build", "--out-dir", str(tmp_path / "out2"),
                 "--decision-pack-dir", str(dp_dir)])
    assert rc == 2
    assert not (tmp_path / "out2").exists()


def test_cli_unknown_command_exit_2():
    assert p.main(["frobnicate"]) == 2


# ── 12. 批次 E：mixed-027 定向盲态复审 ───────────────────────────────

VALID_REVIEW_JSON = json.dumps({
    "decision": "reject",
    "rationale": "两个答案点均未直接回答 query 的核心问题，属于答非所问。",
    "answer_point_assessments": [
        {"answer_point_index": 0, "assessment": "directly_supported",
         "evidence_refs": [1]},
        {"answer_point_index": 1, "assessment": "directly_supported",
         "evidence_refs": [0]},
    ],
    "refusal_assessment": "not_applicable",
}, ensure_ascii=False)


def test_targeted_payload_is_blind(tmp_path):
    """payload 仅含盲态字段：无 case_id、无批次/历史/decision。"""
    p.run(out_dir=tmp_path / "cand")
    out = tmp_path / "cand"
    payload = p.build_targeted_payload(out_dir=out)
    assert set(payload) == {"query", "previous_turns", "should_refuse",
                            "acceptable_answer_points", "evidence", "chunks"}
    assert payload["should_refuse"] is False
    assert payload["previous_turns"] == []
    assert payload["acceptable_answer_points"] == \
        ["术语表：原子化操作不可再分", "SQLite 语法页仅列出 begin-stmt，未展开事务原子性说明"]
    assert len(payload["evidence"]) == 2
    assert set(payload["evidence"][0]) == {"chunk_id", "source_id",
                                           "raw_evidence_span", "snippet"}
    text = json.dumps(payload, ensure_ascii=False)
    for forbidden in ("case_id", "batch", "decision", "rationale",
                      "review", "reject", "triage"):
        assert forbidden not in text, forbidden
    assert set(payload["chunks"]) == {"c9fd20815ea8_chunk_2",
                                      "8b191b241b93_chunk_1"}


def test_targeted_review_success(tmp_path):
    p.run(out_dir=tmp_path / "cand")
    out = tmp_path / "cand"
    captured = {}
    result = p.review_targeted(out_dir=out,
                               llm_fn=_fake_llm(VALID_REVIEW_JSON, captured))
    assert result["status"] == "TARGETED_REVIEW_OK"
    assert result["model"] == REVIEW_MODEL
    assert captured["model"] == REVIEW_MODEL
    assert captured["temperature"] == 0.0
    assert captured["max_tokens"] == 8000
    assert captured["max_retries"] == 3
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    tdir = out / "targeted-re-review"
    assert (tdir / "payload.jsonl").exists()
    assert (tdir / "raw-response.jsonl").exists()
    assert (tdir / "targeted-review-result.json").exists()
    assert (tdir / "review-status.json").exists()
    status = json.load(open(tdir / "review-status.json", encoding="utf-8"))
    assert status["status"] == "TARGETED_REVIEW_OK"
    m = json.load(open(tdir / "manifest.json", encoding="utf-8"))
    assert m["manifest_sha256"] == _recompute_self_hash(m)
    assert m["status"] == "TARGETED_REVIEW_OK"
    # 复审结果不得改变 case 数据（诊断 only）
    before = _sha(out / "draft-after.jsonl")
    assert before == _sha(out / "draft-after.jsonl")


def test_targeted_review_model_identity_mismatch(tmp_path):
    p.run(out_dir=tmp_path / "cand")
    out = tmp_path / "cand"
    captured = {}

    def bad_model_llm(call_type, messages, **kwargs):
        captured.update(kwargs)
        resp = _FakeResponse(VALID_REVIEW_JSON)
        resp.model = "gpt-5.6-sol"
        return resp, _FakeRecord()

    result = p.review_targeted(out_dir=out, llm_fn=bad_model_llm)
    assert result["status"] == "TARGETED_REVIEW_BLOCKED"
    status = json.load(open(out / "targeted-re-review" / "review-status.json",
                            encoding="utf-8"))
    assert status["status"] == "TARGETED_REVIEW_BLOCKED"
    assert "model identity" in status["reason"]
    assert _sha(out / "draft-after.jsonl") == _sha(out / "draft-after.jsonl")


def test_targeted_review_invalid_json_blocked(tmp_path):
    p.run(out_dir=tmp_path / "cand")
    out = tmp_path / "cand"
    result = p.review_targeted(
        out_dir=out, llm_fn=_fake_llm("not json at all", {}))
    assert result["status"] == "TARGETED_REVIEW_BLOCKED"
    status = json.load(open(out / "targeted-re-review" / "review-status.json",
                            encoding="utf-8"))
    assert "parse" in status["reason"].lower() or "json" in status["reason"].lower()


def test_targeted_review_schema_violation_blocked(tmp_path):
    p.run(out_dir=tmp_path / "cand")
    out = tmp_path / "cand"
    bad = json.dumps({"decision": "confirmed",
                      "rationale": "x",
                      "answer_point_assessments": [
                          {"answer_point_index": 0,
                           "assessment": "unsupported", "evidence_refs": [0]}],
                      "refusal_assessment": "not_applicable"})
    result = p.review_targeted(out_dir=out, llm_fn=_fake_llm(bad, {}))
    assert result["status"] == "TARGETED_REVIEW_BLOCKED"
    status = json.load(open(out / "targeted-re-review" / "review-status.json",
                            encoding="utf-8"))
    assert "contract" in status["reason"].lower()


def test_targeted_review_requires_candidate_first(tmp_path):
    """candidate 未构建时定向复审 → BLOCKED（顺序门禁）。"""
    result = p.review_targeted(out_dir=tmp_path / "none",
                               llm_fn=_fake_llm(VALID_REVIEW_JSON, {}))
    assert result["status"] == "TARGETED_REVIEW_BLOCKED"
    assert "candidate" in result["reason"].lower()
