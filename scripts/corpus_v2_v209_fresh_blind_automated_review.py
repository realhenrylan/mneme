"""v2.0.9 fresh full blind automated review — 全新盲态机器复审（Pro-only）。

任务边界（owner 授权，fail-closed）：
- 仅读取：v2.0.9 candidate（draft-after/evidence-after/manifest）、当前 chunks 与
  chunk manifest、translation-equivalence policy/ledger（仅统一支持语义，不使用
  任何逐条 verdict）、raw-codepoint-v1 strict validator。
- 禁止读取：split/dev/holdout、locked config、检索/生成评测、v2.0.7/v2.0.8 的
  review/triage/decision pack/issues/历史结论、人工 review pack 决策字段。
  v2.0.8 文件仅用于 manifest 输入 SHA 的字节级校验（哈希，不读内容）。
- 模型：deepseek-v4-pro / temperature=0.0 / max_tokens=8000 / thinking disabled /
  最多 3 次同模型重试，无 fallback、无 Flash、无 gpt-5.6-sol。
- 盲态 payload：query / previous_turns（剥离身份与引用）/ should_refuse /
  answer_points / evidence（raw span + snippet + 来源正文）/ 统一支持判定规范。
- 输出：automated-review/ 目录；137/137 confirmed 才生成 candidate-scoped
  automated overlay（LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_9，非人工审核/批准/active/
  v2.1 准入）；任一 reject/needs_followup/错误 → AUTOMATED_REVIEW_GATE_BLOCKED，
  只写 issues，绝不生成 overlay。
- 预检任一失败：零输出、零 overlay、不得调用模型。
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from scripts.corpus_v2_evidence_coordinate_repair import (
    display_snippet, strict_validate, strict_validate_row,
)
from src.llm_gateway import llm_call

# ── 常量 ────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.9-owner-authorized-final-dependency-closed-retirement"
OUT = CANDIDATE / "automated-review"
CHUNKS_PATH = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST_PATH = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT_PATH = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"
V208 = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.8-owner-authorized-semantic-quality-remediation"
TRANS_POLICY_PATH = V208 / "translation-equivalence-policy.md"
TRANS_LEDGER_PATH = V208 / "translation-equivalence-policy-ledger.jsonl"

MODEL = "deepseek-v4-pro"
TEMPERATURE = 0.0
MAX_TOKENS = 8000
MAX_RETRIES = 3                       # 最多 3 次同模型重试（初始 + 3 次重试）
THINKING_DISABLED = {"thinking": {"type": "disabled"}}
FORBIDDEN_MODELS = ("deepseek-v4-flash", "gpt-5.6-sol")

EXPECTED_CASE_COUNT = 137
EXPECTED_EVIDENCE_COUNT = 144
EXPECTED_REFUSAL_COUNT = 31
EXPECTED_ANSWERABLE = 106
EXPECTED_CANDIDATE_RETIRED_CASES = 6
EXPECTED_CANDIDATE_RETIRED_EVIDENCE = 7

TIMESTAMP = "2026-08-11T00:00:00+00:00"
ACTOR = "OWNER_AUTHORIZED_V2_0_9_FRESH_BLIND_AUTOMATED_REVIEW"
OVERLAY_STATUS = "LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_9"
GATE_OK = "AUTOMATED_REVIEW_137_137_CONFIRMED"
GATE_BLOCKED = "AUTOMATED_REVIEW_GATE_BLOCKED"
RULE_VERSION = "v2.0.9-fresh-blind-automated-review-1"
TASK_NAME = "v2.0.9-fresh-full-blind-automated-review"
REVIEW_LABEL = "v2.0.9"
CREATED_BY = "corpus_v2_v209_fresh_blind_automated_review.py"
CANDIDATE_ACTOR = "OWNER_AUTHORIZED_FINAL_DEPENDENCY_CLOSED_RETIREMENT"
CANDIDATE_GATE = "FINAL_DEPENDENCY_CLOSED_RETIREMENT_OK"

# 统一支持判定规范：对所有 case 完全相同的唯一指令文本（含输出契约）
UNIFORM_SUPPORT_SPEC = (
    "支持判定规范：仅当证据直接支撑答案点时判定支持。"
    "翻译可被判定为支持，仅当原文与答案点语义等价且没有新增主张"
    "（原文不得不存在该含义；答案点不得增加任何限定、比较、因果或结论）；"
    "不得因存在翻译政策标签而默认支持。"
    "若证据不足以支撑某一答案点，该答案点应判定为不支持；存在任一答案点"
    "不支持的 case 不应判定为通过（该条仅适用于 should_refuse 为 false 且"
    "存在答案点的 case；should_refuse 为 true 的 case 没有答案点需要证据支撑，"
    "只要拒绝行为正确即应判定 confirmed）。"
    "输出契约：仅返回严格 JSON（不要 Markdown 代码块、不要任何额外文字），"
    "格式为 {\"decision\": \"confirmed|reject|needs_followup\", "
    "\"answer_point_assessments\": [{\"answer_point_index\": <整数，对应上方 "
    "answer_points 数组下标，从 0 开始>，\"supported\": <true|false>，"
    "\"rationale\": \"<该答案点理由>\"}，answer_points 中每条答案点恰好一条]，"
    "\"refusal_assessment\": {\"refusal_required\": <true|false>，"
    "\"rationale\": \"<理由>\"}，\"rationale\": \"<整体理由>\"}。"
    "decision 是审查结论，不是对查询的回复：confirmed = 该 case 的答案点与 "
    "refusal 语义均正确（每条答案点都有证据直接支撑；should_refuse 为 true 的 "
    "case 拒绝行为正确）；reject = 该 case 应被驳回（存在答案点无证据直接支撑，"
    "或拒绝行为与 should_refuse 不符）；needs_followup = 盲态下无法判定，"
    "需进一步核验。"
)

# 盲态 payload 允许的全部键（递归键扫描白名单）
ALLOWED_PAYLOAD_KEYS = {
    "query", "previous_turns", "should_refuse", "answer_points",
    "evidence", "raw_span", "snippet", "source_text", "support_spec",
}

# 高信号泄露词：在真实语料（query/AP/evidence span/snippet）中已核实零命中
HIGH_SIGNAL_LEAK_WORDS = (
    "revision", "overlay", "holdout", "retirement", "cohort", "verdict",
    "reviewer", "batch", "candidate", "split", "evaluation", "v2.0", "v2.1",
    "automated-review", "revision_status", "activation_blocked",
    "human_reviewed", "overlay_generated", "split_reseal_required",
    "v2_1_entered", "owner_authorized", "decision_pack",
    "translation_equivalence", "translation-equivalence", "blind", "probe",
    "deepseek", "gpt-5", "flash", "confirmed", "reject", "needs_followup",
    "decision", "rationale", "refusal", "case_id", "case-id", "case_index",
    "raw_model", "review_results", "reviewed", "review", "triage", "annotate",
    "annotator", "benchmark", "locked",
)

CASE_ID_RE = re.compile(r"^(multi|mixed|zh|en|noanswer)-\d+$")
CASE_ID_IN_TEXT_RE = re.compile(r"\b(multi|mixed|zh|en|noanswer)-\d+\b")
RETIRED_IDS = {"multi-030", "multi-031", "multi-032", "multi-033",
               "multi-034", "mixed-027"}
CHUNK_ID_RE = re.compile(r"^[0-9a-f]{12}_chunk_\d+$")

# previous_turns 剥离白名单：仅保留对话内容字段，剥离全部身份/引用/治理字段
TURN_KEEP_KEYS = {"query", "question", "user", "text", "content", "answer",
                  "response", "assistant", "speaker", "turn_text", "statement"}

SKILL_NOTE = (
    "data-analytics:analyze-data-quality skill 在本环境中不可用（已实际尝试，"
    "无法加载）；已执行等价确定性五维检查（完整性/唯一性/引用完整性/连续性/"
    "一致性），全部为机械复算，无额外 LLM 参与。"
)


class ReviewError(Exception):
    """Fail-closed review failure（任何非法状态立即失败、零输出）。"""


class ForbiddenInputError(ReviewError):
    """尝试内容读取未被授权路径时抛出。"""


# ── 内容读取白名单（禁止读取旧 review / split / human-review 等）─────────
# 内容读取仅允许以下 7 个路径；v2.0.8 其余文件（含 decision packs）仅哈希。
INPUT_READ_PATHS = {
    CANDIDATE / "draft-after.jsonl",
    CANDIDATE / "evidence-after.jsonl",
    CANDIDATE / "manifest.json",
    CHUNKS_PATH,
    CHUNK_MANIFEST_PATH,
    TRANS_POLICY_PATH,
    TRANS_LEDGER_PATH,
}

# v2.0.9 manifest 记录的 14 个输入 → 磁盘路径（全部为字节级哈希校验，不读内容）
INPUT_SHA_MAP = {
    "chain-closure-manifest.json": V208 / "chain-closure-decision-pack" / "manifest.json",
    "chunk-manifest.json": CHUNK_MANIFEST_PATH,
    "chunks.jsonl": CHUNKS_PATH,
    "current-v2-draft.jsonl": CURRENT_DRAFT_PATH,
    "deferred-chain-dependent-cases.jsonl": V208 / "deferred-chain-dependent-cases.jsonl",
    "draft-after.jsonl": V208 / "draft-after.jsonl",
    "draft-before.jsonl": V208 / "draft-before.jsonl",
    "evidence-after.jsonl": V208 / "evidence-after.jsonl",
    "evidence-before.jsonl": V208 / "evidence-before.jsonl",
    "final-blockers-decision-pack.jsonl": V208 / "final-blockers-decision-pack" /
        "final-blockers-decision-pack.jsonl",
    "final-blockers-manifest.json": V208 / "final-blockers-decision-pack" / "manifest.json",
    "mixed-027-retirement-check.json": V208 / "chain-closure-decision-pack" /
        "mixed-027-retirement-check.json",
    "multi-030-closure-options.json": V208 / "chain-closure-decision-pack" /
        "multi-030-closure-options.json",
    "v208-manifest.json": V208 / "manifest.json",
}

# 复审 manifest 的 inputs 记录（candidate + 当前语料 + 翻译等价策略）
def _input_check_map(candidate_dir: Path) -> dict[str, Path]:
    return {
        "candidate-draft-after.jsonl": candidate_dir / "draft-after.jsonl",
        "candidate-evidence-after.jsonl": candidate_dir / "evidence-after.jsonl",
        "candidate-manifest.json": candidate_dir / "manifest.json",
        "chunks.jsonl": CHUNKS_PATH,
        "chunk-manifest.json": CHUNK_MANIFEST_PATH,
        "current-v2-draft.jsonl": CURRENT_DRAFT_PATH,
        "translation-equivalence-policy.md": TRANS_POLICY_PATH,
        "translation-equivalence-policy-ledger.jsonl": TRANS_LEDGER_PATH,
    }


INPUT_CHECK_MAP = _input_check_map(CANDIDATE)


# ── hashing / io 原语 ───────────────────────────────────────────────────

def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _line(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + "\n"


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = _sha256_text(_dump(result))
    return result


def _verify_self_hash(manifest: dict) -> bool:
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    return manifest.get("manifest_sha256") == _sha256_text(_dump(body))


def _read_text(path: Path, allowed: set | None = None) -> str:
    """内容读取门禁：仅允许白名单内的路径（运行时强制禁止读取旧 review 等）。"""
    path = Path(path).resolve()
    allow = {Path(p).resolve() for p in (allowed if allowed is not None
                                         else INPUT_READ_PATHS)}
    if path not in allow:
        raise ForbiddenInputError(f"content read not allowed: {path}")
    return path.read_text(encoding="utf-8")


def _load_chunks(path: Path) -> dict[str, dict]:
    chunks = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        assert "text" in c and "source" in c and "chunk_id" in c
        chunks[c["chunk_id"]] = c
    return chunks


# ── 预检（fail-closed，开始任何 LLM 调用前）────────────────────────────

def _verify_candidate_manifest(candidate_dir: Path, chunks_path: Path,
                               chunk_manifest_path: Path,
                               current_draft_path: Path) -> dict:
    """candidate manifest：自哈希、metadata、counts、输出 SHA、输入 SHA。"""
    mpath = candidate_dir / "manifest.json"
    manifest = json.loads(_read_text(mpath,
                                     allowed=INPUT_READ_PATHS | {mpath.resolve()}))
    if not _verify_self_hash(manifest):
        raise ReviewError("candidate manifest self-hash mismatch")
    meta = {
        "revision_status": manifest.get("revision_status"),
        "activation_blocked": manifest.get("activation_blocked"),
        "human_reviewed": manifest.get("human_reviewed"),
        "overlay_generated": manifest.get("overlay_generated"),
        "split_reseal_required": manifest.get("split_reseal_required"),
        "v2_1_entered": manifest.get("v2_1_entered"),
        "actor": manifest.get("actor"),
    }
    if meta["revision_status"] != "CANDIDATE":
        raise ReviewError(f"candidate not CANDIDATE: {meta['revision_status']}")
    if meta["activation_blocked"] is not True:
        raise ReviewError("candidate activation_blocked must be true")
    if meta["human_reviewed"] is not False:
        raise ReviewError("candidate human_reviewed must be false")
    if meta["overlay_generated"] is not False:
        raise ReviewError("candidate overlay_generated must be false")
    if meta["split_reseal_required"] is not True:
        raise ReviewError("candidate split_reseal_required must be true")
    if meta["v2_1_entered"] is not False:
        raise ReviewError("candidate v2_1_entered must be false")
    if meta["actor"] != CANDIDATE_ACTOR:
        raise ReviewError(f"candidate actor mismatch: {meta['actor']}")
    if manifest.get("gate_verdict") != CANDIDATE_GATE:
        raise ReviewError(f"candidate gate mismatch: {manifest.get('gate_verdict')}")
    counts = manifest.get("counts") or {}
    if counts.get("case_after") != EXPECTED_CASE_COUNT or \
            counts.get("evidence_after") != EXPECTED_EVIDENCE_COUNT or \
            counts.get("retired_cases") != EXPECTED_CANDIDATE_RETIRED_CASES or \
            counts.get("retired_evidence") != EXPECTED_CANDIDATE_RETIRED_EVIDENCE:
        raise ReviewError(f"candidate counts mismatch: {counts}")
    # 输出 SHA
    for name, h in (manifest.get("outputs") or {}).items():
        if _sha256_file(candidate_dir / name) != h:
            raise ReviewError(f"candidate output SHA mismatch: {name}")
    # 输入 SHA（chunks/chunk-manifest/current-draft 按传入路径校验；
    # v2.0.8 文件仅哈希，不读内容）
    sha_sources = dict(INPUT_SHA_MAP)
    sha_sources["chunks.jsonl"] = Path(chunks_path)
    sha_sources["chunk-manifest.json"] = Path(chunk_manifest_path)
    sha_sources["current-v2-draft.jsonl"] = Path(current_draft_path)
    for name, h in (manifest.get("inputs") or {}).items():
        p = sha_sources.get(name)
        if p is None or not p.exists() or _sha256_file(p) != h:
            raise ReviewError(f"candidate input SHA mismatch: {name}")
    return manifest


def preflight(candidate_dir: Path, chunks_path: Path, chunk_manifest_path: Path,
              current_draft_path: Path, trans_policy_path: Path,
              trans_ledger_path: Path) -> dict:
    """全部 fail-closed 门禁；任一漂移抛 ReviewError（调用方零输出）。"""
    checks: dict = {}

    # 1) candidate manifest（自哈希/metadata/counts/输出 SHA/输入 SHA）
    manifest = _verify_candidate_manifest(candidate_dir, chunks_path,
                                          chunk_manifest_path,
                                          current_draft_path)
    checks["manifest_self_hash_ok"] = True
    checks["metadata_ok"] = True
    checks["outputs_sha_ok"] = True
    checks["inputs_sha_ok"] = True
    checks["candidate_manifest_sha256"] = _sha256_file(candidate_dir / "manifest.json")

    # 2) draft：137 行、唯一 id、字段完整
    allowed_reads = {candidate_dir / "draft-after.jsonl",
                     candidate_dir / "evidence-after.jsonl",
                     Path(chunk_manifest_path), Path(trans_policy_path),
                     Path(trans_ledger_path)} | INPUT_READ_PATHS
    draft = [json.loads(l) for l in
             _read_text(candidate_dir / "draft-after.jsonl",
                        allowed=allowed_reads).splitlines() if l.strip()]
    if len(draft) != EXPECTED_CASE_COUNT:
        raise ReviewError(f"draft case count {len(draft)} != {EXPECTED_CASE_COUNT}")
    ids = [r["id"] for r in draft]
    if len(set(ids)) != len(ids):
        raise ReviewError("draft case ids not unique")
    for r in draft:
        if not isinstance(r.get("query"), str) or not r["query"]:
            raise ReviewError(f"case {r.get('id')} missing query")
        if not isinstance(r.get("should_refuse"), bool):
            raise ReviewError(f"case {r.get('id')} should_refuse not bool")
        aps = r.get("acceptable_answer_points")
        if not isinstance(aps, list) or not all(isinstance(a, str) and a
                                                for a in aps):
            raise ReviewError(f"case {r.get('id')} answer points invalid")
    queries = [r["query"] for r in draft]
    if len(set(queries)) != len(queries):
        raise ReviewError("draft queries not unique")
    for r in draft:
        aps = r["acceptable_answer_points"]
        if len(set(aps)) != len(aps):
            raise ReviewError(f"case {r['id']} duplicate answer points")
    checks["case_count"] = len(draft)
    checks["queries_unique"] = True

    # 3) evidence：144 行、strict 合法、covered==passed、legacy/unresolved=0
    evidence = [json.loads(l) for l in
                _read_text(candidate_dir / "evidence-after.jsonl",
                           allowed=allowed_reads).splitlines() if l.strip()]
    if len(evidence) != EXPECTED_EVIDENCE_COUNT:
        raise ReviewError(f"evidence count {len(evidence)} != {EXPECTED_EVIDENCE_COUNT}")
    chunks = _load_chunks(chunks_path)
    try:
        strict_validate(evidence, chunks)
    except Exception as exc:
        raise ReviewError(f"strict validation failed: {exc}") from exc
    legacy = invalid = unresolved = uncovered = 0
    for e in evidence:
        if e.get("coordinate_contract") != "raw-codepoint-v1":
            legacy += 1
        try:
            strict_validate_row(e, chunks)
        except Exception:
            invalid += 1
        if not e.get("raw_chunk_char_range") or not e.get("raw_evidence_span"):
            unresolved += 1
        c = chunks[e["chunk_id"]]
        span = c["text"][e["raw_chunk_char_range"]["start"]:
                         e["raw_chunk_char_range"]["end"]]
        if span != e["raw_evidence_span"] or \
                e.get("chunk_text_sha256") != _sha256_text(c["text"]) or \
                e.get("snippet") != display_snippet(e["raw_evidence_span"]) or \
                e.get("snippet_sha256") != _sha256_text(e.get("snippet", "")):
            uncovered += 1
        if e["case_id"] not in set(ids):
            raise ReviewError(f"evidence case ref not in draft: {e['case_id']}")
        if e["chunk_id"] not in chunks:
            raise ReviewError(f"evidence chunk not found: {e['chunk_id']}")
        if e["source_id"] != c["source"]:
            raise ReviewError(f"evidence source mismatch: {e['case_id']}")
    if legacy or invalid or unresolved or uncovered:
        raise ReviewError(
            f"evidence not all covered: legacy={legacy} invalid={invalid} "
            f"unresolved={unresolved} uncovered={uncovered}")
    checks["evidence_count"] = len(evidence)
    checks["strict_covered"] = len(evidence)
    checks["strict_passed"] = len(evidence)
    checks["legacy"] = legacy
    checks["invalid"] = invalid
    checks["unresolved"] = unresolved
    checks["uncovered"] = uncovered

    # 4) 覆盖关系：answerable 均有 ≥1 evidence；refusal 均无 evidence
    by_id = {r["id"]: r for r in draft}
    ev_per_case: dict[str, list[dict]] = {}
    for e in evidence:
        ev_per_case.setdefault(e["case_id"], []).append(e)
    answerable = [r["id"] for r in draft if r["should_refuse"] is False]
    refusal = [r["id"] for r in draft if r["should_refuse"] is True]
    answerable_without = sorted(c for c in answerable if not ev_per_case.get(c))
    refusal_with = sorted(c for c in refusal if ev_per_case.get(c))
    if len(answerable) != EXPECTED_ANSWERABLE or len(refusal) != EXPECTED_REFUSAL_COUNT:
        raise ReviewError(f"answerable/refusal counts {len(answerable)}/"
                          f"{len(refusal)} != {EXPECTED_ANSWERABLE}/"
                          f"{EXPECTED_REFUSAL_COUNT}")
    if answerable_without or refusal_with:
        raise ReviewError(f"coverage drift: no-evidence={answerable_without} "
                          f"refusal-with-evidence={refusal_with}")
    checks["answerable_cases"] = len(answerable)
    checks["refusal_cases"] = len(refusal)
    checks["answerable_without_evidence"] = answerable_without
    checks["refusal_with_evidence"] = refusal_with

    # 5) 唯一性：evidence (case_id, chunk_id, raw range) 冲突性重复（同 key 不同
    #    内容 → 关系歧义 → fail-closed）；字节级完全相同的重复行是 candidate
    #    自身 data-quality-report 已记录的已知事实（evidence_keys_unique=false，
    #    继承自 v2.0.8），仅记录不阻断。
    seen: dict[tuple, dict] = {}
    duplicate_rows = []
    for e in evidence:
        key = (e["case_id"], e["chunk_id"], e["raw_chunk_char_range"]["start"])
        if key in seen:
            if seen[key] == e:
                duplicate_rows.append(e["case_id"])
            else:
                raise ReviewError(f"conflicting duplicate evidence anchor: {key}")
        else:
            seen[key] = e
    checks["evidence_anchor_conflicts"] = []
    checks["duplicate_evidence_rows"] = sorted(set(duplicate_rows))
    checks["duplicate_evidence_pairs"] = len(duplicate_rows)

    # 6) 连续性：draft 内 case-id 引用全部指向现存 case，且无指向已退役 case
    dangling, to_retired = [], []
    for r in draft:
        meta = r.get("metadata") or {}
        for key in ("follow_up_to", "chain_id"):
            v = meta.get(key)
            if isinstance(v, str) and CASE_ID_RE.match(v):
                if v not in by_id:
                    dangling.append((r["id"], key, v))
                if v in RETIRED_IDS:
                    to_retired.append((r["id"], key, v))
        pt = meta.get("previous_turns")
        if isinstance(pt, list):
            for i, v in enumerate(pt):
                if isinstance(v, str) and CASE_ID_RE.match(v):
                    if v not in by_id:
                        dangling.append((r["id"], f"previous_turns[{i}]", v))
                    if v in RETIRED_IDS:
                        to_retired.append((r["id"], f"previous_turns[{i}]", v))
        dt = r.get("doc_target")
        if isinstance(dt, str) and CASE_ID_RE.match(dt):
            if dt not in by_id:
                dangling.append((r["id"], "doc_target", dt))
            if dt in RETIRED_IDS:
                to_retired.append((r["id"], "doc_target", dt))
    if dangling or to_retired:
        raise ReviewError(f"draft continuity drift: dangling={dangling} "
                          f"to-retired={to_retired}")
    checks["dangling_draft_refs"] = dangling
    checks["refs_to_retired"] = to_retired

    # 7) chunks / chunk manifest 一致性
    cm = json.loads(_read_text(chunk_manifest_path,
                               allowed=allowed_reads))
    if cm.get("n_chunks") != len(chunks):
        raise ReviewError(f"chunk manifest n_chunks {cm.get('n_chunks')} "
                          f"!= {len(chunks)}")
    sources = {}
    for c in chunks.values():
        sources[c["source"]] = sources.get(c["source"], 0) + 1
    if cm.get("per_source") != sources:
        raise ReviewError("chunk manifest per_source mismatch")
    for cid in chunks:
        if not CHUNK_ID_RE.match(cid):
            raise ReviewError(f"chunk id format drift: {cid}")
    checks["chunk_count"] = len(chunks)

    # 8) 当前 draft（仅哈希）与 translation-equivalence 文件（结构核验）
    if not current_draft_path.exists():
        raise ReviewError("current draft missing")
    if not trans_policy_path.exists():
        raise ReviewError("translation policy missing")
    ledger_text = _read_text(trans_ledger_path, allowed=allowed_reads)
    ledger_rows = [l for l in ledger_text.splitlines() if l.strip()]
    if len(ledger_rows) != 3:
        raise ReviewError(f"translation ledger rows {len(ledger_rows)} != 3")
    for row in ledger_rows:
        if not isinstance(json.loads(row), dict):
            raise ReviewError("translation ledger row not object")
    checks["translation_ledger_rows"] = len(ledger_rows)

    return checks


# ── 盲态 payload 构建与泄露扫描 ─────────────────────────────────────────

def _strip_turn(entry) -> str:
    """剥离 previous_turns 条目中的身份/引用/治理字段（白名单保留对话内容）。"""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        kept = [v for k, v in entry.items()
                if k in TURN_KEEP_KEYS and isinstance(v, str)]
        return " ".join(kept)
    return ""


def build_payload(row: dict, evidence_rows: list[dict],
                  chunks: dict[str, dict]) -> dict:
    """构建盲态 payload：仅 query/previous_turns/should_refuse/answer_points/
    evidence（raw span + snippet + 来源正文）/ 统一支持判定规范。"""
    meta = row.get("metadata") or {}
    prev = meta.get("previous_turns")
    turns = [_strip_turn(t) for t in prev] if isinstance(prev, list) else []
    turns = [t for t in turns if t]
    evs = sorted(evidence_rows,
                 key=lambda e: (e["chunk_id"], e["raw_chunk_char_range"]["start"]))
    return {
        "query": row["query"],
        "previous_turns": turns,
        "should_refuse": bool(row["should_refuse"]),
        "answer_points": list(row["acceptable_answer_points"]),
        "evidence": [
            {"raw_span": e["raw_evidence_span"],
             "snippet": e["snippet"],
             "source_text": chunks[e["chunk_id"]]["text"]}
            for e in evs
        ],
        "support_spec": UNIFORM_SUPPORT_SPEC,
    }


def scan_payload(payload: dict) -> None:
    """递归键扫描 + 高信号泄露词扫描；发现泄露整体停止。

    - 结构化字段（query/previous_turns/answer_points）：任务侧撰写内容，做
      完整高信号词 + case-id 扫描；
    - 语料字段（raw_span/snippet/source_text）：逐字节来自 chunks（已 SHA
      门禁），仅做 case-id 引用扫描（语料天然含 split/model 等普通词汇，
      不属治理标签）。
    """
    if not isinstance(payload, dict):
        raise ReviewError("payload not dict")

    def walk(value, path: str) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if k not in ALLOWED_PAYLOAD_KEYS:
                    raise ReviewError(f"payload forbidden key: {path}.{k}")
                walk(v, f"{path}.{k}")
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, f"{path}[{i}]")
        elif isinstance(value, str):
            # support_spec 是统一指令模板（含 decision 词汇），不参与内容扫描
            if path.endswith(".support_spec"):
                return
            corpus_field = (path.endswith(".raw_span") or
                            path.endswith(".snippet") or
                            path.endswith(".source_text"))
            if CASE_ID_IN_TEXT_RE.search(value):
                raise ReviewError(f"payload contains case-id reference at {path}")
            if not corpus_field:
                low = value.lower()
                for word in HIGH_SIGNAL_LEAK_WORDS:
                    if word in low:
                        raise ReviewError(
                            f"payload contains governance word {word!r} at {path}")
        elif isinstance(value, (bool, int, float)) or value is None:
            return
        else:
            raise ReviewError(f"payload unexpected value type at {path}")

    walk(payload, "payload")


# ── 响应 schema / refusal 语义（本地严格验证，fail-closed）──────────────

def validate_response(obj, payload: dict) -> dict:
    """严格验证模型输出：schema、decision 枚举、AP 引用关系、refusal 语义。"""
    if not isinstance(obj, dict):
        raise ReviewError("response not a JSON object")
    top_keys = set(obj.keys())
    if not top_keys <= {"decision", "answer_point_assessments",
                        "refusal_assessment", "rationale"}:
        raise ReviewError(f"response unexpected keys: {sorted(top_keys)}")
    decision = obj.get("decision")
    if decision not in ("confirmed", "reject", "needs_followup"):
        raise ReviewError(f"response decision invalid: {decision!r}")
    if not isinstance(obj.get("rationale"), str) or not obj["rationale"]:
        raise ReviewError("response rationale missing")

    ra = obj.get("refusal_assessment")
    if not isinstance(ra, dict) or set(ra.keys()) != {"refusal_required",
                                                      "rationale"}:
        raise ReviewError("response refusal_assessment invalid")
    refusal_required = ra["refusal_required"]
    if not isinstance(refusal_required, bool):
        raise ReviewError("response refusal_required not bool")

    n_ap = len(payload["answer_points"])
    ass = obj.get("answer_point_assessments")
    if not isinstance(ass, list):
        raise ReviewError("response answer_point_assessments not list")
    if len(ass) != n_ap:
        raise ReviewError(f"response assessments {len(ass)} != answer points {n_ap}")
    idxs = []
    for a in ass:
        if not isinstance(a, dict) or set(a.keys()) != {"answer_point_index",
                                                        "supported",
                                                        "rationale"}:
            raise ReviewError("response assessment schema invalid")
        if not isinstance(a["answer_point_index"], int) or \
                not isinstance(a["supported"], bool):
            raise ReviewError("response assessment field types invalid")
        idxs.append(a["answer_point_index"])
    if sorted(idxs) != list(range(n_ap)):
        raise ReviewError(f"response assessment indices mismatch: {idxs}")

    supported = [a["supported"] for a in ass]
    # refusal 语义一致性：confirmed 必须与 payload 完全一致
    if decision == "confirmed":
        if not all(supported):
            raise ReviewError("confirmed with unsupported answer point")
        if refusal_required != bool(payload["should_refuse"]):
            raise ReviewError("confirmed with refusal semantic mismatch")
    else:
        if all(supported) and refusal_required == bool(payload["should_refuse"]):
            raise ReviewError("reject/needs_followup without any disagreement")

    return {
        "decision": decision,
        "answer_point_assessments": ass,
        "refusal_assessment": ra,
        "rationale": obj["rationale"],
    }


def _strip_json_fence(content: str) -> str:
    """确定性剥离单个 Markdown 代码围栏（```json 或 ```）。

    仅处理「整体被一个代码围栏包裹」的响应；不补字段、不猜坐标、
    不修改 JSON 内部任何内容。其他任何形式原样返回由严格解析处理。
    """
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].strip() in ("```", "```json") and \
                lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return text


def _validate_content(content: str, payload: dict) -> dict:
    """解析模型返回内容为严格 JSON 并验证；任何失败抛 ReviewError。

    允许整体包裹在单个 ```json 代码围栏中的响应（确定性剥离围栏），
    其余部分必须是严格 JSON；不做任何字段补全或坐标猜测。
    """
    text = _strip_json_fence(content)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReviewError(f"response not strict JSON: {exc}") from exc
    return validate_response(obj, payload)


# ── 模型调用：探针 / 单 case 复审（同模型重试，无 fallback）────────────

def _payload_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=1)


def probe(client) -> dict:
    """不读取任何 case 的探针：验证实际返回模型身份 == deepseek-v4-pro。"""
    content = ('Reply with strict JSON only: {"probe": "ok"}')
    model, response_text, _usage = client([{"role": "user", "content": content}])
    if model != MODEL:
        raise ReviewError(f"probe model identity mismatch: {model!r}")
    try:
        obj = json.loads(response_text.strip())
    except json.JSONDecodeError as exc:
        raise ReviewError(f"probe response not JSON: {exc}") from exc
    if not isinstance(obj, dict) or "probe" not in obj:
        raise ReviewError("probe response missing probe key")
    return {"ok": True, "model": model, "expected_model": MODEL,
            "content_sha256": _sha256_text(response_text)}


def review_case(case_id: str, payload: dict, client) -> dict:
    """单 case 复审：最多 3 次同模型重试；耗尽后抛 ReviewError（fail-closed）。"""
    message = [{"role": "user", "content": _payload_text(payload)}]
    last: Exception | None = None
    attempts = 0
    for attempt in range(1, MAX_RETRIES + 2):
        attempts = attempt
        try:
            model, response_text, usage = client(message)
            if model != MODEL:
                raise ReviewError(f"model identity mismatch: {model!r}")
            out = _validate_content(response_text, payload)
            return {
                "case_id": case_id,
                "decision": out["decision"],
                "answer_point_assessments": out["answer_point_assessments"],
                "refusal_assessment": out["refusal_assessment"],
                "rationale": out["rationale"],
                "model": model,
                "payload_sha256": _sha256_text(_payload_text(payload)),
                "response_sha256": _sha256_text(response_text),
                "attempts": attempts,
                "retries_used": attempts - 1,
                "usage": usage,
            }
        except Exception as exc:
            last = exc
    raise ReviewError(f"case {case_id} failed after {attempts} attempts: "
                      f"{last}") from last


def _real_client(messages):
    """真实客户端：统一 gateway，Pro-only 参数，同模型重试，无 fallback。"""
    response, record = llm_call(
        call_type="v209_blind_review",
        messages=messages,
        model=MODEL,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        max_retries=MAX_RETRIES,
        extra_body=THINKING_DISABLED,
    )
    content = response.choices[0].message.content or ""
    usage = None
    if record.token_usage is not None:
        usage = {
            "prompt_tokens": record.token_usage.prompt_tokens,
            "completion_tokens": record.token_usage.completion_tokens,
            "total_tokens": record.token_usage.total_tokens,
        }
    return response.model, content, usage


_DEFAULT_CLIENT = _real_client


# ── 输出构建（成功 / blocked）───────────────────────────────────────────

SUCCESS_FILES = (
    "automated-review-pack.jsonl",
    "automated-review-evidence.jsonl",
    "automated-review.jsonl",
    "raw-model-responses.jsonl",
    "automated-review-summary.json",
    "automated-review-report.md",
    "automated-review-gate-report.md",
    "manifest.json",
    "automated-overlay.json",
)

BLOCKED_FILES = (
    "automated-review-issues.jsonl",
    "automated-review-gate-report.md",
    "manifest.json",
)


def _clean_stale_success(out_dir: Path) -> None:
    """blocked 路径下清理可能残留的成功产物（尤其 overlay）。"""
    for name in SUCCESS_FILES:
        p = out_dir / name
        if p.exists():
            p.unlink()


def _clean_stale_blocked(out_dir: Path) -> None:
    """成功路径下清理可能残留的 blocked 产物（issues）。"""
    p = out_dir / "automated-review-issues.jsonl"
    if p.exists():
        p.unlink()


def _data_quality_five_dims(checks: dict, draft: list[dict],
                            evidence: list[dict], chunks: dict[str, dict],
                            manifest: dict, candidate_dir: Path) -> dict:
    """等价五维确定性检查（data-analytics skill 不可用时的离线复算）。"""
    by_id = {r["id"]: r for r in draft}
    ev_per_case = {}
    for e in evidence:
        ev_per_case.setdefault(e["case_id"], []).append(e)
    completeness = {
        "status": "ok",
        "draft_rows": len(draft),
        "draft_fields_complete": all(
            r.get("query") and isinstance(r.get("should_refuse"), bool) and
            isinstance(r.get("acceptable_answer_points"), list)
            for r in draft),
        "evidence_rows": len(evidence),
        "evidence_fields_complete": all(
            e.get("raw_evidence_span") and e.get("snippet") and
            e.get("chunk_id") and e.get("source_id") for e in evidence),
        "answerable_coverage": all(ev_per_case.get(c)
                                   for c in by_id if not by_id[c]["should_refuse"]),
    }
    duplicate_note = (
        f"{REVIEW_LABEL} candidate has {checks['duplicate_evidence_pairs']} "
        "byte-identical evidence row pair(s); this review records rather than "
        "mutates candidate data."
        if checks["duplicate_evidence_pairs"] else
        "No byte-identical evidence rows are present in the candidate."
    )
    uniqueness = {
        "status": "ok",
        "case_ids_unique": len({r["id"] for r in draft}) == len(draft),
        "queries_unique": len({r["query"] for r in draft}) == len(draft),
        "answer_points_unique": all(
            len(set(r["acceptable_answer_points"])) ==
            len(r["acceptable_answer_points"]) for r in draft),
        "evidence_anchor_conflicts": checks["evidence_anchor_conflicts"],
        "duplicate_evidence_rows": checks["duplicate_evidence_rows"],
        "duplicate_evidence_pairs": checks["duplicate_evidence_pairs"],
        "note": duplicate_note,
    }
    ref_ok = True
    for e in evidence:
        if e["case_id"] not in by_id or e["chunk_id"] not in chunks or \
                chunks[e["chunk_id"]]["source"] != e["source_id"]:
            ref_ok = False
    referential = {
        "status": "ok" if ref_ok else "fail",
        "evidence_to_draft": all(e["case_id"] in by_id for e in evidence),
        "evidence_to_chunks": all(e["chunk_id"] in chunks for e in evidence),
        "source_match": all(chunks[e["chunk_id"]]["source"] == e["source_id"]
                            for e in evidence),
        "raw_span_match": all(
            chunks[e["chunk_id"]]["text"][e["raw_chunk_char_range"]["start"]:
                                          e["raw_chunk_char_range"]["end"]]
            == e["raw_evidence_span"] for e in evidence),
    }
    continuity = {
        "status": "ok",
        "dangling_refs": checks["dangling_draft_refs"],
        "refs_to_retired": checks["refs_to_retired"],
        "previous_turns_rows": sum(
            1 for r in draft if "previous_turns" in (r.get("metadata") or {})),
    }
    consistency = {
        "status": "ok",
        "manifest_self_hash": _verify_self_hash(manifest),
        "outputs_sha": checks["outputs_sha_ok"],
        "inputs_sha": checks["inputs_sha_ok"],
        "strict_validation": f"{checks['strict_covered']}/"
                             f"{checks['strict_passed']}",
        "counts_exact": (checks["case_count"] == EXPECTED_CASE_COUNT and
                         checks["evidence_count"] == EXPECTED_EVIDENCE_COUNT),
    }
    return {
        "completeness": completeness,
        "uniqueness": uniqueness,
        "referential_integrity": referential,
        "continuity": continuity,
        "consistency": consistency,
        "skill_note": SKILL_NOTE,
    }


def _build_success(out_dir: Path, results: dict, payloads: dict,
                   draft: list[dict], evidence: list[dict], chunks: dict,
                   checks: dict, candidate_dir: Path, probe_result: dict,
                   preflight_manifest: dict) -> dict:
    """137/137 confirmed 时写入全部成功产物 + candidate-scoped automated overlay。"""
    by_id = {r["id"]: r for r in draft}
    ev_per_case = {}
    for e in evidence:
        ev_per_case.setdefault(e["case_id"], []).append(e)

    pack_rows = []
    for cid in sorted(results):
        r = results[cid]
        pack_rows.append({
            "case_id": cid,
            "case_index": sorted(results).index(cid),
            "decision": r["decision"],
            "answer_point_assessments": r["answer_point_assessments"],
            "refusal_assessment": r["refusal_assessment"],
            "rationale": r["rationale"],
            "model": r["model"],
            "payload_sha256": r["payload_sha256"],
            "response_sha256": r["response_sha256"],
            "attempts": r["attempts"],
            "retries_used": r["retries_used"],
        })

    ev_rows = []
    for e in sorted(evidence, key=lambda e: (e["case_id"], e["chunk_id"],
                                             e["raw_chunk_char_range"]["start"])):
        ev_rows.append({
            "case_id": e["case_id"],
            "chunk_id": e["chunk_id"],
            "source_id": e["source_id"],
            "raw_chunk_char_range": e["raw_chunk_char_range"],
            "raw_evidence_span": e["raw_evidence_span"],
            "snippet": e["snippet"],
            "snippet_sha256": e["snippet_sha256"],
            "chunk_text_sha256": e["chunk_text_sha256"],
            "decision": results[e["case_id"]]["decision"],
        })

    review_rows = [{
        "case_id": cid,
        "decision": results[cid]["decision"],
        "status": results[cid]["decision"],
        "model": results[cid]["model"],
        "retries_used": results[cid]["retries_used"],
    } for cid in sorted(results)]

    raw_rows = [{
        "case_id": cid,
        "model": results[cid]["model"],
        "response_sha256": results[cid]["response_sha256"],
        "usage": results[cid]["usage"],
        "attempts": results[cid]["attempts"],
    } for cid in sorted(results)]

    dist = {}
    for lst in ev_per_case.values():
        dist[str(len(lst))] = dist.get(str(len(lst)), 0) + 1

    dq = _data_quality_five_dims(checks, draft, evidence, chunks,
                                 preflight_manifest, candidate_dir)
    summary = {
        "task": TASK_NAME,
        "rule_version": RULE_VERSION,
        "gate_verdict": GATE_OK,
        "model": MODEL,
        "parameters": {
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "thinking": "disabled",
            "max_retries": MAX_RETRIES,
            "fallback": "none",
        },
        "probe": probe_result,
        "counts": {
            "case_count": len(results),
            "evidence_count": len(evidence),
            "answerable_cases": checks["answerable_cases"],
            "refusal_cases": checks["refusal_cases"],
            "confirmed": sum(1 for r in results.values()
                             if r["decision"] == "confirmed"),
            "reject": sum(1 for r in results.values()
                          if r["decision"] == "reject"),
            "needs_followup": sum(1 for r in results.values()
                                  if r["decision"] == "needs_followup"),
            "errors": 0,
        },
        "evidence_per_case_distribution": dict(sorted(dist.items())),
        "translation_equivalence": {
            "semantics": "uniform support spec applied to all cases",
            "ledger_rows": checks["translation_ledger_rows"],
            "ledger_rows_used_as_verdicts": 0,
        },
        "data_quality": dq,
        "declarations": {
            "llm_called": True,
            "network_used": True,
            "model_identity_verified": True,
            "no_fallback": True,
            "historical_verdicts_read": False,
            "review_results_reused": False,
            "human_reviewed": False,
            "human_approved": False,
            "overlay_generated": True,
            "active_created": False,
            "split_created": False,
            "v2_1_entered": False,
            "candidate_draft_evidence_unchanged": True,
        },
        "run_at": TIMESTAMP,
        "skill_note": SKILL_NOTE,
    }

    report_md = _report_md(summary, checks, candidate_dir)
    gate_md = _gate_report_md(GATE_OK, summary["counts"],
                              checks, candidate_dir, None)

    manifest_body = {
        "task": TASK_NAME,
        "rule_version": RULE_VERSION,
        "created_by": CREATED_BY,
        "run_at": TIMESTAMP,
        "gate_verdict": GATE_OK,
        "reviewed_revision": candidate_dir.name,
        "reviewed_revision_manifest_sha256": checks["candidate_manifest_sha256"],
        "model": MODEL,
        "parameters": summary["parameters"],
        "counts": summary["counts"],
        "inputs": {name: _sha256_file(p)
                   for name, p in _input_check_map(candidate_dir).items()},
        "metadata": {
            "revision_status": "CANDIDATE",
            "activation_blocked": True,
            "human_reviewed": False,
            "overlay_generated": True,
            "split_reseal_required": True,
            "v2_1_entered": False,
        },
        "declarations": summary["declarations"],
        "validation": {
            "strict_validation_covered_equals_passed": True,
            "case_count_exact": True,
            "evidence_count_exact": True,
            "all_cases_confirmed": True,
            "schema_errors": 0,
            "identity_errors": 0,
            "transport_errors": 0,
        },
        "skill_note": SKILL_NOTE,
    }

    overlay = {
        "status": OVERLAY_STATUS,
        "candidate_scoped": True,
        "revision": candidate_dir.name,
        "candidate_manifest_sha256": checks["candidate_manifest_sha256"],
        "gate_verdict": GATE_OK,
        "case_count": len(results),
        "confirmed_count": len(results),
        "model": MODEL,
        "parameters": summary["parameters"],
        "declarations": {
            "is_human_reviewed": False,
            "is_human_approval": False,
            "is_active_activation": False,
            "is_v2_1_entry": False,
            "is_split_or_lock": False,
            "overlay_status": OVERLAY_STATUS,
            "candidate_draft_evidence_unchanged": True,
            "chunks_unchanged": True,
        },
        "confirmed_case_ids": sorted(results),
        "not_before": ("本 overlay 是用户授权的机器复审结果，不是人工审核、"
                       "不是人工批准、不是 active 版本、不是 v2.1 准入；"
                       "不改变 candidate draft/evidence/chunks。"),
        "generated_by": CREATED_BY,
        "run_at": TIMESTAMP,
    }

    files = {
        "automated-review-pack.jsonl": "".join(_line(r) for r in pack_rows),
        "automated-review-evidence.jsonl": "".join(_line(r) for r in ev_rows),
        "automated-review.jsonl": "".join(_line(r) for r in review_rows),
        "raw-model-responses.jsonl": "".join(_line(r) for r in raw_rows),
        "automated-review-summary.json": _dump(summary),
        "automated-review-report.md": report_md,
        "automated-review-gate-report.md": gate_md,
        "automated-overlay.json": _dump(overlay),
    }
    manifest_body["outputs"] = {}
    for name, content in files.items():
        manifest_body["outputs"][name] = _sha256_text(content)
    manifest = _manifest(manifest_body)
    files["manifest.json"] = _dump(manifest)

    _clean_stale_blocked(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        _atomic_write(out_dir / name, content)
    return manifest


def _build_blocked(out_dir: Path, results: dict, checks: dict,
                   candidate_dir: Path, preflight_manifest: dict) -> dict:
    """存在 reject/needs_followup/error 时：只写 issues，绝不生成 overlay。"""
    _clean_stale_success(out_dir)
    issues = []
    for cid in sorted(results):
        r = results[cid]
        if r["decision"] in ("confirmed",):
            continue
        if r["decision"] in ("reject", "needs_followup"):
            issues.append({
                "case_id": cid,
                "kind": r["decision"],
                "detail": r.get("rationale", ""),
                "attempts": r.get("attempts", 1),
                "response_sha256": r.get("response_sha256"),
            })
        else:
            issues.append({
                "case_id": cid,
                "kind": "error",
                "detail": r.get("error", ""),
                "attempts": r.get("attempts"),
            })
    counts = {
        "case_count": len(results),
        "evidence_count": checks["evidence_count"],
        "answerable_cases": checks["answerable_cases"],
        "refusal_cases": checks["refusal_cases"],
        "confirmed": sum(1 for r in results.values()
                         if r["decision"] == "confirmed"),
        "reject": sum(1 for r in results.values()
                      if r["decision"] == "reject"),
        "needs_followup": sum(1 for r in results.values()
                              if r["decision"] == "needs_followup"),
        "errors": sum(1 for r in results.values()
                      if r["decision"] not in ("confirmed", "reject",
                                               "needs_followup")),
    }
    gate_md = _gate_report_md(GATE_BLOCKED, counts, checks, candidate_dir,
                              issues)
    manifest_body = {
        "task": TASK_NAME,
        "rule_version": RULE_VERSION,
        "created_by": CREATED_BY,
        "run_at": TIMESTAMP,
        "gate_verdict": GATE_BLOCKED,
        "reviewed_revision": candidate_dir.name,
        "reviewed_revision_manifest_sha256": checks["candidate_manifest_sha256"],
        "model": MODEL,
        "parameters": {
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "thinking": "disabled",
            "max_retries": MAX_RETRIES,
            "fallback": "none",
        },
        "counts": counts,
        "inputs": {name: _sha256_file(p)
                   for name, p in _input_check_map(candidate_dir).items()},
        "metadata": {
            "revision_status": "CANDIDATE",
            "activation_blocked": True,
            "human_reviewed": False,
            "overlay_generated": False,
            "split_reseal_required": True,
            "v2_1_entered": False,
        },
        "declarations": {
            "llm_called": True,
            "network_used": True,
            "model_identity_verified": True,
            "no_fallback": True,
            "historical_verdicts_read": False,
            "review_results_reused": False,
            "human_reviewed": False,
            "human_approved": False,
            "overlay_generated": False,
            "active_created": False,
            "split_created": False,
            "v2_1_entered": False,
            "candidate_draft_evidence_unchanged": True,
        },
        "validation": {
            "strict_validation_covered_equals_passed": True,
            "case_count_exact": True,
            "evidence_count_exact": True,
            "all_cases_confirmed": False,
            "schema_errors": counts["errors"],
            "identity_errors": 0,
            "transport_errors": 0,
        },
        "skill_note": SKILL_NOTE,
    }
    files = {
        "automated-review-issues.jsonl": "".join(_line(i) for i in issues),
        "automated-review-gate-report.md": gate_md,
    }
    manifest_body["outputs"] = {name: _sha256_text(content)
                                for name, content in files.items()}
    manifest = _manifest(manifest_body)
    files["manifest.json"] = _dump(manifest)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        _atomic_write(out_dir / name, content)
    return manifest


def _report_md(summary: dict, checks: dict, candidate_dir: Path) -> str:
    c = summary["counts"]
    return (
        f"# {REVIEW_LABEL} Fresh Full Blind Automated Review — 报告\n\n"
        f"- **Revision**：`{candidate_dir.name}`\n"
        f"- **模型**：`{summary['model']}`（temperature=0.0，max_tokens=8000，"
        f"thinking disabled，最多 3 次同模型重试，无 fallback）\n"
        f"- **Gate**：`{GATE_OK}`\n"
        f"- **统计**：{c['case_count']} case / {c['evidence_count']} evidence "
        f"（answerable {c['answerable_cases']} / refusal {c['refusal_cases']}）；"
        f"confirmed {c['confirmed']} / reject {c['reject']} / "
        f"needs_followup {c['needs_followup']} / errors {c['errors']}\n"
        f"- **盲态**：payload 仅含 query / previous_turns（剥离身份与引用）/ "
        f"should_refuse / answer_points / evidence（raw span + snippet + 来源正文）"
        f"/ 统一支持判定规范；无 case_id、revision、batch、retirement、历史 "
        f"decision/rationale、reviewer、issue、cohort、split、holdout/dev、"
        f"评测指标或治理标签（递归键扫描 + 高信号泄露词扫描，全部通过）。\n"
        f"- **翻译等价**：统一支持语义应用于全部 case（`{UNIFORM_SUPPORT_SPEC}`）；"
        f"translation-equivalence ledger 仅用于语义，未使用任何逐条 verdict。\n"
        f"- **预检**：{checks['case_count']}/{checks['evidence_count']} strict"
        f"（covered==passed=={checks['strict_covered']}，legacy/unresolved/"
        f"invalid/uncovered=0）、manifest 自哈希与输入/输出 SHA 与磁盘一致、"
        f"candidate metadata 为 CANDIDATE / activation_blocked / human_reviewed=false"
        f" / 无 overlay。\n"
        f"- **五维数据质量**：完整性 / 唯一性 / 引用完整性 / 连续性 / 一致性全部 ok"
        f"（{SKILL_NOTE}）。\n"
        f"- **overlay**：candidate-scoped automated overlay 已生成，状态 "
        f"`{OVERLAY_STATUS}`。\n\n"
        f"> **边界声明**：本次是用户授权的机器复审，不是人工审核、不是人工批准、"
        f"不是 active 版本、不是 v2.1 准入；不改变 candidate draft/evidence/chunks；"
        f"未生成 active metadata、split、locked config 或 v2.1 文件。\n"
    )


def _gate_report_md(gate: str, counts: dict, checks: dict,
                    candidate_dir: Path, issues) -> str:
    lines = [
        f"# Automated Review Gate Report — {gate}\n",
        f"- **Revision**：`{candidate_dir.name}`",
        f"- **Gate**：`{gate}`",
        f"- **模型**：`{MODEL}`（temperature=0.0 / max_tokens=8000 / "
        f"thinking disabled / max_retries=3 / fallback=none）",
        f"- **预检**：case_count={checks['case_count']}，"
        f"evidence={checks['evidence_count']}，"
        f"strict covered==passed=={checks['strict_covered']}，"
        f"legacy={checks['legacy']} unresolved={checks['unresolved']}，"
        f"answerable={checks['answerable_cases']} refusal={checks['refusal_cases']}",
        f"- **统计**：confirmed={counts['confirmed']} reject={counts['reject']} "
        f"needs_followup={counts['needs_followup']} errors={counts['errors']}",
    ]
    if gate == GATE_OK:
        lines.append(f"- **结论**：{counts['confirmed']}/{counts['case_count']} confirmed，无 schema/transport/identity "
                     "错误；生成 candidate-scoped automated overlay "
                     f"（{OVERLAY_STATUS}）。")
    else:
        lines.append("- **结论**：存在非 confirmed 结果或错误，"
                     "gate=AUTOMATED_REVIEW_GATE_BLOCKED；只写 issues，"
                     "绝不生成 overlay。")
        if issues:
            lines.append(f"- **issues**：{len(issues)} 条（"
                         + ", ".join(sorted({i['case_id'] for i in issues})) + "）")
    return "\n".join(lines) + "\n"


# ── 主流程 ──────────────────────────────────────────────────────────────

def run(*, out_dir: Path = OUT, candidate_dir: Path = CANDIDATE,
        chunks_path: Path = CHUNKS_PATH, chunk_manifest_path: Path = CHUNK_MANIFEST_PATH,
        current_draft_path: Path = CURRENT_DRAFT_PATH,
        trans_policy_path: Path = TRANS_POLICY_PATH,
        trans_ledger_path: Path = TRANS_LEDGER_PATH,
        client=_DEFAULT_CLIENT) -> dict:
    """完整复审流程：预检（fail-closed）→ payload 构建与泄露扫描 → 探针 →
    逐 case 复审 → 聚合输出。预检或探针失败 → ReviewError（零输出）。"""
    checks = preflight(candidate_dir, chunks_path, chunk_manifest_path,
                       current_draft_path, trans_policy_path, trans_ledger_path)

    draft = [json.loads(l) for l in
             (candidate_dir / "draft-after.jsonl").read_text(
                 encoding="utf-8").splitlines() if l.strip()]
    evidence = [json.loads(l) for l in
                (candidate_dir / "evidence-after.jsonl").read_text(
                    encoding="utf-8").splitlines() if l.strip()]
    chunks = _load_chunks(chunks_path)
    ev_per_case: dict[str, list[dict]] = {}
    for e in evidence:
        ev_per_case.setdefault(e["case_id"], []).append(e)

    # 盲态 payload：构建 + 递归键扫描 + 高信号泄露词扫描
    payloads = {}
    for row in draft:
        payload = build_payload(row, ev_per_case.get(row["id"], []), chunks)
        scan_payload(payload)
        payloads[row["id"]] = payload

    # 探针（不读取任何 case）：身份 != deepseek-v4-pro → 整体停止、零输出
    probe_result = probe(client)

    results = {}
    for cid in sorted(payloads):
        try:
            results[cid] = review_case(cid, payloads[cid], client)
        except ReviewError as exc:
            results[cid] = {"decision": "error", "error": str(exc),
                            "attempts": MAX_RETRIES + 1}

    preflight_manifest = json.loads(
        (candidate_dir / "manifest.json").read_text(encoding="utf-8"))
    confirmed = sum(1 for r in results.values() if r["decision"] == "confirmed")
    if confirmed == len(results) and len(results) == EXPECTED_CASE_COUNT:
        manifest = _build_success(out_dir, results, payloads, draft, evidence,
                                  chunks, checks, candidate_dir, probe_result,
                                  preflight_manifest)
        gate = GATE_OK
    else:
        manifest = _build_blocked(out_dir, results, checks, candidate_dir,
                                  preflight_manifest)
        gate = GATE_BLOCKED

    counts = {
        "case_count": len(results),
        "evidence_count": checks["evidence_count"],
        "answerable_cases": checks["answerable_cases"],
        "refusal_cases": checks["refusal_cases"],
        "confirmed": confirmed,
        "reject": sum(1 for r in results.values() if r["decision"] == "reject"),
        "needs_followup": sum(1 for r in results.values()
                              if r["decision"] == "needs_followup"),
        "errors": sum(1 for r in results.values()
                      if r["decision"] not in ("confirmed", "reject",
                                               "needs_followup")),
    }
    return {"gate": gate, "manifest": manifest, "counts": counts,
            "out_dir": out_dir, "probe": probe_result}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--probe-json" in args:
        try:
            result = probe(_DEFAULT_CLIENT)
        except Exception as exc:
            print(json.dumps({"ok": False, "model": None,
                              "expected_model": MODEL, "error": str(exc)},
                             ensure_ascii=False, indent=1))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0

    parser = argparse.ArgumentParser(
        description="v2.0.9 fresh full blind automated review")
    parser.add_argument("command", nargs="?", default="build",
                        choices=("build",))
    parser.add_argument("--out-dir", default=str(OUT))
    parser.add_argument("--candidate-dir", default=str(CANDIDATE))
    parser.add_argument("--chunks", default=str(CHUNKS_PATH))
    parser.add_argument("--chunk-manifest", default=str(CHUNK_MANIFEST_PATH))
    parser.add_argument("--current-draft", default=str(CURRENT_DRAFT_PATH))
    parser.add_argument("--trans-policy", default=str(TRANS_POLICY_PATH))
    parser.add_argument("--trans-ledger", default=str(TRANS_LEDGER_PATH))
    ns = parser.parse_args(args)

    result = run(out_dir=Path(ns.out_dir), candidate_dir=Path(ns.candidate_dir),
                 chunks_path=Path(ns.chunks),
                 chunk_manifest_path=Path(ns.chunk_manifest),
                 current_draft_path=Path(ns.current_draft),
                 trans_policy_path=Path(ns.trans_policy),
                 trans_ledger_path=Path(ns.trans_ledger),
                 client=_DEFAULT_CLIENT)
    print(json.dumps({"gate": result["gate"], "counts": result["counts"],
                      "out_dir": str(result["out_dir"])},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
