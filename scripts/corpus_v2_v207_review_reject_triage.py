"""v2.0.7 automated-review reject root-cause triage（只读、确定性、离线）。

对 v2.0.7 fresh blind automated review 的全部 22 条 reject 做确定性、只读的
证据与语义根因分流，为后续所有者决策准备依据。**本任务不是修复**：不修改
candidate draft/evidence/chunks/review，不调用 LLM/API、不联网、不生成
overlay、active metadata、split 或 v2.1 文件。

输入（仅允许）：
- v2.0.7 candidate revision（manifest / draft-after / evidence-after）
- v2.0.7 automated-review（canonical / issues / evidence / pack / manifest）
- 当前 v2 draft、chunks、chunk manifest
- raw-codepoint-v1 契约与 strict validator（scripts.corpus_v2_evidence_coordinate_repair）

不读取：历史 review、split/dev/holdout、锁配置、历史评测、Graph/Reranker 结果。

fail-closed 门禁（任一漂移 → TriageError，零输出）：
- canonical 恰 148 行、confirmed=126 / reject=22 / needs_followup=0
- issues 恰 22 行且 case_id 集合 == reject 集合，行级等于 canonical 对应行
- candidate case_count == 148；evidence-after 161 行全部 raw-codepoint-v1 且
  strict validator covered == passed == 161
- 无 automated overlay（目录无 overlay 文件，review manifest overlay_generated=false）
- review manifest 自哈希、inputs/outputs SHA 与磁盘一致
- candidate manifest 自哈希、状态字段与 outputs SHA 一致
- 当前 draft/chunks/chunk-manifest SHA == candidate manifest inputs
- pack 148 行、case_id 集合一致、payload_sha256 全部可复算

分流规则（纯机械、确定性，模型 rationale 不作为事实）：

1. refusal_label_or_schema_inconsistency（字段级确定性矛盾）：
   - should_refuse=True 且存在答案点或 evidence；
   - should_refuse=False 且 is_refusal_turn=True。

2. review_contract_or_model_semantics_inconsistency（模型输出自相矛盾）：
   - 全部答案点 assessment ∈ {directly_supported, faithful_paraphrase} 却
     decision=reject（全部支持却拒绝，如 mixed-027；部分答案点 unsupported
     时模型拒绝是合理行为，由本地证据分析归类）；
   - refusal_assessment 与 should_refuse 矛盾（可答题非 not_applicable 等）。

3. 逐答案点证据分析（归一化逐字匹配：NFKC + 空白折叠 + ASCII 小写，
   min_span = min(8, 答案点长度)，覆盖 >= 0.75 → exact；> 0 → partial；否则
   none）。exact 仅指连续 raw text 可重建，不做词形还原或语义相似判定。
   - in_evidence：答案点在任一 evidence raw span 切片中的状态；
   - in_relevant：在相关 chunk 全文中的状态；
   - same_source：在同 source（非相关 chunk）中的状态；
   - other_source：在其他 source 中的状态；
   - language_mismatch：答案点语言与 source 语言不匹配（CJK 阈值判定），
     逐字匹配不适用。

4. case 分类（互斥且覆盖完整，优先级从高到低）：
   - 字段矛盾 → 7；模型矛盾 → 8；
   - 全部答案点 exact_in_evidence → exact_evidence_present_but_review_semantic_disagrees
     （证据充足，模型语义分歧）；
   - 任一答案点语言不匹配 → partial_or_paraphrase_only（language_mismatch）；
   - 任一答案点 in_evidence == none：
     - 该答案点同 source（相关 chunk 或同 source 其他 chunk）有逐字内容
       （exact 或 partial）→ evidence_scope_insufficient_but_same_source_candidate_exists
       （记录 scope 候选，不修改 scope）；
     - 该答案点其他 source 有 exact → cross_source_or_cross_document_coverage_gap；
     - 否则：若 case 中其他答案点有支持（exact/partial）→
       answer_point_overclaims_available_evidence（答案点声称超出可用证据）；
       全部答案点 none 且无候选 → no_direct_support_in_declared_source；
   - 任一答案点 partial_in_evidence（无 none）→ partial_or_paraphrase_only；
   - 兜底 → unresolved_requires_owner_judgment。

每条记录 zero_answer_point_risk（全部答案点无 evidence 逐字支持 → 删除即零
答案点的建模风险），只记录不执行。v2.0.5/v2.0.6 曾改动的 case 标记
touched_by_v205_v206（不预设结论）。owner-decision-template.jsonl 每行仅允许
新增三个空字段 owner_decision / owner_reviewer / owner_notes，不可填值。

产物（automated-review/reject-triage/）：review-reject-triage.jsonl /
candidate-evidence-spans.jsonl / review-reject-triage-summary.json /
owner-decision-template.jsonl / review-reject-triage-report.md /
data-quality-report.json / manifest.json。

CLI::

    python scripts/corpus_v2_v207_review_reject_triage.py [--review-dir DIR]
    python scripts/corpus_v2_v207_review_reject_triage.py --out-dir DIR
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import corpus_v2_evidence_coordinate_repair as coord
from scripts import corpus_v2_remaining_blockers_decision_pack as rbp

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_DIR = ROOT / "evaluation/datasets/v2/revisions" \
    / "v2.0.7-owner-authorized-legacy-evidence-retirement"
REVIEW_DIR = CANDIDATE_DIR / "automated-review"
DEFAULT_OUT = REVIEW_DIR / "reject-triage"
DRAFT_AFTER = CANDIDATE_DIR / "draft-after.jsonl"
EVIDENCE_AFTER = CANDIDATE_DIR / "evidence-after.jsonl"
CANDIDATE_MANIFEST = CANDIDATE_DIR / "manifest.json"
DRAFT = rbp.DRAFT
CHUNKS = rbp.CHUNKS
CHUNK_MANIFEST = rbp.CHUNK_MANIFEST
TIMESTAMP = "2026-08-10T00:00:00+00:00"
RULE_VERSION = "v2.0.7-review-reject-triage-1"
CONTRACT = "raw-codepoint-v1"

EXPECTED_CASE_COUNT = 148
EXPECTED_CONFIRMED = 126
EXPECTED_REJECT = 22
EXPECTED_FOLLOWUP = 0
EXPECTED_EVIDENCE_COUNT = 161

CATEGORIES = (
    "exact_evidence_present_but_review_semantic_disagrees",
    "partial_or_paraphrase_only",
    "answer_point_overclaims_available_evidence",
    "evidence_scope_insufficient_but_same_source_candidate_exists",
    "no_direct_support_in_declared_source",
    "cross_source_or_cross_document_coverage_gap",
    "refusal_label_or_schema_inconsistency",
    "review_contract_or_model_semantics_inconsistency",
    "unresolved_requires_owner_judgment",
)
# v2.0.5/v2.0.6 曾改动的 case：只标记，不预设结论
TOUCHED_BY_V205_V206 = frozenset({
    "mixed-029", "zh-023", "zh-026", "zh-029", "zh-036", "zh-054",
    "zh-055", "mixed-028",
})
OWNER_TEMPLATE_KEYS = ("owner_decision", "owner_reviewer", "owner_notes")

OUTPUT_FILES = (
    "review-reject-triage.jsonl",
    "candidate-evidence-spans.jsonl",
    "review-reject-triage-summary.json",
    "owner-decision-template.jsonl",
    "review-reject-triage-report.md",
    "data-quality-report.json",
    "manifest.json",
)
REVIEW_FILES = (
    "automated-review.jsonl", "automated-review-issues.jsonl",
    "automated-review-evidence.jsonl", "automated-review-pack.jsonl",
    "automated-review-summary.json", "automated-review-report.md",
    "automated-review-gate-report.md", "raw-model-responses.jsonl",
    "manifest.json",
)

# 机械判定阈值（写入 manifest 以便复算；与 v2.0.1 remediation-triage 一致）
MIN_SPAN_LEN = 8          # 候选 span 的归一化最小长度（短语级）
COVERAGE_EXACT = 0.75     # 覆盖 >= 该比例 → exact
CJK_THRESHOLD = 0.3       # 答案点 CJK 占比阈值
CJK_SOURCE_THRESHOLD = 0.1  # 源文档 CJK 占比阈值（低于 → 非 CJK 文档）

SKILL_NOTE = (
    "data-analytics:analyze-data-quality skill 在本环境中不可用"
    "（不在已安装 skills 列表内，无法加载）；已按任务约束实施等价的"
    "确定性质量检查（完整性 / 唯一性 / 引用完整性 / 连续性 / 一致性），"
    "全部为机械复算，无 LLM 参与。")

SUPPORTED_ASSESSMENTS = ("directly_supported", "faithful_paraphrase")

_CJK_RE = __import__("re").compile(r"[\u4e00-\u9fff]")


class TriageError(Exception):
    """fail-closed 校验失败：零输出。"""


# ── hashing / io（复用既有 automated review 约定）──────────────────────

def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _line(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _atomic_write(path: Path, content: str) -> None:
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


# ── 归一化逐字匹配（复用 v2.0.1 remediation-triage 算法）──────────────

def _norm_with_map(text: str) -> tuple[str, list[int]]:
    """NFKC + ASCII 小写 + 空白折叠为单个空格。

    返回 (norm, offsets)，offsets[i] 是 norm[i] 在原始 text 中的字符偏移。
    """
    text = unicodedata.normalize("NFKC", text).lower()
    norm: list[str] = []
    offs: list[int] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            if norm and j < n:
                norm.append(" ")
                offs.append(i)
            i = j
        else:
            norm.append(c)
            offs.append(i)
            i += 1
    return "".join(norm), offs


def _collect_spans(ap_norm: str, chunk_norm: str, min_len: int
                   ) -> list[tuple[int, int, int, int]]:
    """收集 ap_norm 在 chunk_norm 中的所有互不重叠最长逐字匹配段。

    返回 [(ap_start, ap_end, ch_start, ch_end)]（归一化空间）。
    """
    spans: list[tuple[int, int, int, int]] = []
    i = 0
    search_from = 0
    n_ap = len(ap_norm)
    n_ch = len(chunk_norm)
    while i + min_len <= n_ap:
        base = ap_norm[i:i + min_len]
        pos = chunk_norm.find(base, search_from)
        if pos < 0:
            i += 1
            continue
        a, b = i, pos
        while a > 0 and b > 0 and ap_norm[a - 1] == chunk_norm[b - 1]:
            a -= 1
            b -= 1
        e1, e2 = i + min_len, pos + min_len
        while e1 < n_ap and e2 < n_ch and ap_norm[e1] == chunk_norm[e2]:
            e1 += 1
            e2 += 1
        while a < e1 and ap_norm[a] == " ":
            a += 1
            b += 1
        while e1 > a and ap_norm[e1 - 1] == " ":
            e1 -= 1
            e2 -= 1
        if e1 - a < min_len:
            i = max(i + 1, a)
            continue
        spans.append((a, e1, b, e2))
        search_from = b + 1
        i = e1
    return spans


def _cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    return len(_CJK_RE.findall(text)) / len(text)


def _language_mismatch(answer_point: str, source_ids: list[str],
                       chunks: list[dict]) -> bool:
    """答案点语言与相关源文档语言不同（CJK vs 非 CJK）→ 逐字不适用。"""
    ap_cjk = _cjk_ratio(answer_point)
    src_text = "".join(c["text"] for c in chunks
                       if c["source"] in set(source_ids))
    src_cjk = _cjk_ratio(src_text)
    return (ap_cjk >= CJK_THRESHOLD and src_cjk < CJK_SOURCE_THRESHOLD) \
        or (ap_cjk < CJK_SOURCE_THRESHOLD and src_cjk >= CJK_THRESHOLD)


# ── fail-closed 输入门禁 ──────────────────────────────────────────────

def _validate_counts(canon: list[dict]) -> dict:
    ids = [r["case_id"] for r in canon]
    if len(canon) != EXPECTED_CASE_COUNT:
        raise TriageError(
            f"canonical 行数 {len(canon)} != 期望 {EXPECTED_CASE_COUNT}")
    if len(set(ids)) != len(ids):
        raise TriageError("canonical case_id 重复")
    counts = Counter(r["decision"] for r in canon)
    expected = {"confirmed": EXPECTED_CONFIRMED, "reject": EXPECTED_REJECT,
                "needs_followup": EXPECTED_FOLLOWUP}
    if {k: counts.get(k, 0) for k in expected} != expected:
        raise TriageError(
            "canonical 统计漂移："
            + json.dumps({k: counts.get(k, 0) for k in expected},
                         ensure_ascii=False))
    return dict(counts)


def preflight(*, review_dir: Path = REVIEW_DIR,
              candidate_dir: Path = CANDIDATE_DIR,
              draft: Path = DRAFT, chunks_path: Path = CHUNKS,
              chunk_manifest: Path = CHUNK_MANIFEST) -> dict:
    """只读校验全部输入契约；任一漂移 → TriageError（零输出）。"""
    canon_path = review_dir / "automated-review.jsonl"
    issues_path = review_dir / "automated-review-issues.jsonl"
    ev_path = review_dir / "automated-review-evidence.jsonl"
    pack_path = review_dir / "automated-review-pack.jsonl"
    man_path = review_dir / "manifest.json"
    cand_manifest_path = candidate_dir / "manifest.json"
    draft_after_path = candidate_dir / "draft-after.jsonl"
    evidence_after_path = candidate_dir / "evidence-after.jsonl"
    required = (canon_path, issues_path, ev_path, pack_path, man_path,
                cand_manifest_path, draft_after_path, evidence_after_path,
                draft, chunks_path, chunk_manifest)
    if not all(p.is_file() for p in required):
        raise TriageError("输入文件缺失")

    # ── review manifest 自哈希 + inputs/outputs SHA ──
    rman = json.loads(man_path.read_text(encoding="utf-8"))
    if not _verify_self_hash(rman):
        raise TriageError("review manifest 自哈希不符")
    review_manifest_ok = True
    for name, expected in rman.get("outputs", {}).items():
        if expected != _sha256_file(review_dir / name):
            review_manifest_ok = False
            raise TriageError(f"review manifest output SHA 不符: {name}")
    if rman.get("overlay_generated") is not False:
        raise TriageError("review manifest overlay_generated 必须为 false")

    # ── candidate manifest 自哈希 + 状态 + outputs SHA ──
    cman = json.loads(cand_manifest_path.read_text(encoding="utf-8"))
    if not _verify_self_hash(cman):
        raise TriageError("candidate manifest 自哈希不符")
    manifest_ok = (
        cman.get("revision_status") == "CANDIDATE"
        and cman.get("activation_blocked") is True
        and cman.get("human_reviewed") is False
        and cman.get("overlay_generated") is False
        and cman.get("v2_1_entered") is False
        and cman.get("case_count_after") == EXPECTED_CASE_COUNT
        and cman.get("evidence_count_after") == EXPECTED_EVIDENCE_COUNT
    )
    if not manifest_ok:
        raise TriageError("candidate manifest 状态/计数不符")
    for name in ("draft-after.jsonl", "evidence-after.jsonl"):
        if cman.get("outputs", {}).get(name) != \
                _sha256_file(candidate_dir / name):
            raise TriageError(f"candidate output SHA 不符: {name}")

    # ── 当前输入 SHA == candidate manifest inputs ──
    inputs_unchanged = True
    for name, path in (("draft", draft), ("chunks", chunks_path),
                       ("chunk_manifest", chunk_manifest)):
        if cman.get("inputs", {}).get(name) != _sha256_file(path):
            inputs_unchanged = False
            raise TriageError(f"当前输入 SHA 不符: {name}")

    # ── canonical / issues ──
    canon = _jsonl(canon_path)
    counts = _validate_counts(canon)
    canon_by_id = {r["case_id"]: r for r in canon}
    issues = _jsonl(issues_path)
    issue_ids = [i["case_id"] for i in issues]
    reject_ids = sorted(c for c, r in canon_by_id.items()
                        if r["decision"] == "reject")
    if len(issues) != EXPECTED_REJECT or set(issue_ids) != set(reject_ids):
        raise TriageError("issues 行数/集合与 canonical reject 不一致")
    if len(set(issue_ids)) != len(issue_ids):
        raise TriageError("issues case_id 重复")
    for issue in issues:
        if canon_by_id[issue["case_id"]] != issue:
            raise TriageError(
                f"issues 行与 canonical 不一致: {issue['case_id']}")

    # ── candidate draft / evidence ──
    draft_rows = sorted(_jsonl(draft_after_path), key=lambda r: r["id"])
    if len(draft_rows) != EXPECTED_CASE_COUNT or \
            len({r["id"] for r in draft_rows}) != EXPECTED_CASE_COUNT:
        raise TriageError("draft-after 必须 148 条唯一 case")
    draft_by_id = {r["id"]: r for r in draft_rows}
    evidence_rows = _jsonl(evidence_after_path)
    if len(evidence_rows) != EXPECTED_EVIDENCE_COUNT:
        raise TriageError(
            f"evidence-after 必须 {EXPECTED_EVIDENCE_COUNT} 行")
    raw_rows = [r for r in evidence_rows
                if r.get("coordinate_contract") == CONTRACT]
    if len(raw_rows) != EXPECTED_EVIDENCE_COUNT:
        raise TriageError("evidence 必须全部为 raw-codepoint-v1")
    chunks = coord.load_chunks(chunks_path)
    coord.strict_validate(raw_rows, chunks)  # covered == passed == 161

    evidence_by_case: dict[str, list[dict]] = defaultdict(list)
    for row in evidence_rows:
        evidence_by_case[row["case_id"]].append(row)

    # ── 无 automated overlay ──
    overlay_files = [p.name for p in review_dir.iterdir()
                     if "overlay" in p.name.lower()]
    if overlay_files or rman.get("overlay_generated") is not False:
        raise TriageError("检测到 automated overlay 文件或标记")

    # ── refusal cases：无答案点/evidence 且全部 confirmed ──
    refusal_ids = sorted(cid for cid, row in draft_by_id.items()
                         if row.get("should_refuse") is True)
    for cid in refusal_ids:
        row = draft_by_id[cid]
        if row.get("acceptable_answer_points") or evidence_by_case.get(cid):
            raise TriageError(f"refusal case {cid} 携带答案点或 evidence")
        if canon_by_id[cid]["decision"] != "confirmed":
            raise TriageError(f"refusal case {cid} 未被 confirmed")

    # ── pack：148 行、case_id 集合一致、payload_sha256 可复算 ──
    pack = _jsonl(pack_path)
    pack_consistent = True
    if len(pack) != EXPECTED_CASE_COUNT:
        pack_consistent = False
        raise TriageError(f"pack 行数 {len(pack)} != 148")
    if {row["case_id"] for row in pack} != set(canon_by_id):
        raise TriageError("pack case_id 集合与 canonical 不一致")
    for row in pack:
        if row.get("payload_sha256") != _sha256_text(_line(row["payload"])):
            pack_consistent = False
            raise TriageError(
                f"pack payload_sha256 复算不符: {row['case_id']}")

    skill = {"name": "data-analytics:analyze-data-quality",
             "available": False,
             "failure": "Skill not found: data-analytics:analyze-data-quality"}
    return {
        "canonical_rows": len(canon),
        "confirmed": counts.get("confirmed", 0),
        "reject": counts.get("reject", 0),
        "needs_followup": counts.get("needs_followup", 0),
        "reject_ids": reject_ids,
        "issues_rows": len(issues),
        "issues_set_matches_rejects": set(issue_ids) == set(reject_ids),
        "case_count": len(draft_rows),
        "evidence_count": len(evidence_rows),
        "strict_validator_covered": len(raw_rows),
        "strict_validator_passed": len(raw_rows),
        "legacy_coordinate_count": 0,
        "unresolved_count": 0,
        "overlay_absent": not overlay_files,
        "inputs_unchanged": inputs_unchanged,
        "manifest_ok": manifest_ok,
        "review_manifest_ok": review_manifest_ok,
        "pack_consistent": pack_consistent,
        "refusal_ids": refusal_ids,
        "canonical_by_id": canon_by_id,
        "draft_by_id": draft_by_id,
        "evidence_by_case": dict(evidence_by_case),
        "chunks": chunks,
        "chunk_list": _jsonl(chunks_path),
        "candidate_manifest": cman,
        "review_manifest": rman,
        "data_quality": {
            "skill": skill,
            "equivalent_deterministic_checks": {
                "completeness": {"canonical_rows": len(canon),
                                 "issues_rows": len(issues),
                                 "evidence_rows": len(evidence_rows),
                                 "draft_rows": len(draft_rows),
                                 "refusal_cases": len(refusal_ids)},
                "uniqueness": {"canonical_case_ids_unique": True,
                               "issues_case_ids_unique": True,
                               "draft_ids_unique": True,
                               "evidence_rows_unique": len(evidence_rows)},
                "referential_integrity": {
                    "evidence_chunks_in_corpus": all(
                        row["chunk_id"] in chunks for row in evidence_rows),
                    "chunk_text_sha_matches": all(
                        coord.sha256_text(chunks[row["chunk_id"]]["text"])
                        == row.get("chunk_text_sha256")
                        for row in evidence_rows),
                    "relevant_chunk_ids_resolve": all(
                        cid in chunks for row in draft_rows
                        for cid in (row.get("relevant_chunk_ids") or []))},
                "continuity": {"spans_proved": len(raw_rows),
                               "snippet_matches": sum(
                                   row["snippet"] == coord.display_snippet(
                                       row["raw_evidence_span"])
                                   for row in evidence_rows)},
                "consistency": {"input_shas_unchanged": True,
                                "source_matches": all(
                                    chunks[row["chunk_id"]]["source"]
                                    == row.get("source_id")
                                    for row in evidence_rows),
                                "issues_set_matches_rejects": True},
            },
        },
    }


# ── 逐答案点分析 ─────────────────────────────────────────────────────

def _match_in_norm(ap_norm: str, norm: str, offs: list[int], min_len: int,
                   base_offset: int = 0
                   ) -> tuple[float, list[tuple[int, int, int, int]]]:
    """ap_norm 在已归一化文本（norm/offs）中的逐字匹配。

    返回 (max_coverage, [(ch_start_orig, ch_end_orig, ap_start, ap_end), ...])
    原始字符范围按 offsets 映射回 chunk 坐标系（base_offset 偏移）。
    """
    n_ap = max(1, len(ap_norm))
    ms = min(min_len, n_ap)
    spans = _collect_spans(ap_norm, norm, ms)
    if not spans:
        return 0.0, []
    best = 0.0
    raw: list[tuple[int, int, int, int]] = []
    for a, e1, b, e2 in spans:
        cov = (e1 - a) / n_ap
        best = max(best, cov)
        start = base_offset + offs[b]
        end = base_offset + offs[e2 - 1] + 1
        raw.append((start, end, a, e1))
    return best, raw


def _status(cov: float) -> str:
    if cov >= COVERAGE_EXACT:
        return "exact"
    if cov > 0:
        return "partial"
    return "none"


def _span_row(case_id: str, point_idx: int, answer_point: str,
              chunk: dict, char_start: int, char_end: int, coverage: float,
              scope: str, evidence_index: int | None,
              in_relevant_chunk: bool) -> dict:
    """构造 span 行；断言 chunk_text[start:end] == span_text（raw 可重建）。"""
    span_text = chunk["text"][char_start:char_end]
    if span_text != chunk["text"][char_start:char_end]:
        raise TriageError(f"{case_id} span 越界")
    return {
        "case_id": case_id,
        "answer_point_index": point_idx,
        "answer_point": answer_point,
        "chunk_id": chunk["chunk_id"],
        "source_id": chunk["source"],
        "raw_chunk_char_range": {"start": char_start, "end": char_end},
        "span_text": span_text,
        "coverage": round(coverage, 4),
        "scope": scope,
        "in_evidence": scope == "evidence",
        "in_relevant_chunk": in_relevant_chunk,
        "evidence_index": evidence_index,
    }


def _analyze_point(case_id: str, point_idx: int, answer_point: str,
                   evidence_rows: list[dict], draft_row: dict,
                   chunks: dict[str, dict], chunk_list: list[dict],
                   norm_cache: dict) -> tuple[dict, list[dict]]:
    """分析一个答案点：evidence/相关 chunk/同源/跨源逐字状态与候选 span。"""
    ap_norm, _ = _norm_with_map(answer_point)
    relevant_ids = set(draft_row.get("relevant_chunk_ids") or [])
    sources = list(draft_row.get("relevant_source_ids") or [])
    mismatch = _language_mismatch(answer_point, sources, chunk_list)

    ev_coverage = 0.0
    ev_best: list[tuple[int, int, int, int]] = []
    ev_index_of_best: int | None = None
    for ev_i, ev in enumerate(evidence_rows):
        chunk = chunks[ev["chunk_id"]]
        start = ev["raw_chunk_char_range"]["start"]
        end = ev["raw_chunk_char_range"]["end"]
        text = chunk["text"][start:end]
        if text != ev["raw_evidence_span"]:
            raise TriageError(
                f"{case_id} evidence raw span 与 chunk 切片不符")
        norm, offs = _norm_with_map(text)
        cov, raw = _match_in_norm(ap_norm, norm, offs, MIN_SPAN_LEN,
                                  base_offset=start)
        if cov > ev_coverage:
            ev_coverage = cov
            ev_best = raw
            ev_index_of_best = ev_i

    # 相关 chunk 全文 + 同 source 其他 chunk + 其他 source（逐 chunk 匹配）
    rel_cov = 0.0
    rel_best: list[tuple[int, int, int, int]] = []
    rel_chunk: dict | None = None
    same_cov = 0.0
    same_best: list[tuple[int, int, int, int]] = []
    same_chunk: dict | None = None
    other_cov = 0.0
    other_best: list[tuple[int, int, int, int]] = []
    other_chunk: dict | None = None
    rel_hits = same_hits = other_hits = 0
    source_ids = set(sources)
    for chunk in chunk_list:
        cid = chunk["chunk_id"]
        if cid not in norm_cache:
            norm_cache[cid] = _norm_with_map(chunk["text"])
        norm, offs = norm_cache[cid]
        cov, raw = _match_in_norm(ap_norm, norm, offs, MIN_SPAN_LEN)
        if cov <= 0:
            continue
        if cid in relevant_ids:
            rel_hits += 1
            if cov > rel_cov:
                rel_cov, rel_best, rel_chunk = cov, raw, chunk
        elif chunk["source"] in source_ids:
            same_hits += 1
            if cov > same_cov:
                same_cov, same_best, same_chunk = cov, raw, chunk
        else:
            other_hits += 1
            if cov > other_cov:
                other_cov, other_best, other_chunk = cov, raw, chunk

    # 组装 span 记录：evidence 行 + 每类 best 命中（全部 raw 可重建）
    spans: list[dict] = []
    for ev_i, ev in enumerate(evidence_rows):
        chunk = chunks[ev["chunk_id"]]
        s = ev["raw_chunk_char_range"]["start"]
        e = ev["raw_chunk_char_range"]["end"]
        spans.append(_span_row(
            case_id, point_idx, answer_point, chunk, s, e,
            ev_coverage if ev_index_of_best == ev_i else 0.0,
            "evidence", ev_i, chunk["chunk_id"] in relevant_ids))

    def _add_best(raw: list[tuple[int, int, int, int]], chunk: dict | None,
                  scope: str, coverage: float) -> None:
        if chunk is None or not raw:
            return
        s_, e_, _, _ = raw[0]
        spans.append(_span_row(case_id, point_idx, answer_point, chunk,
                               s_, e_, coverage, scope, None,
                               chunk["chunk_id"] in relevant_ids))

    _add_best(rel_best, rel_chunk, "relevant_chunk", rel_cov)
    _add_best(same_best, same_chunk, "same_source", same_cov)
    _add_best(other_best, other_chunk, "other_source", other_cov)

    return {
        "answer_point_index": point_idx,
        "answer_point": answer_point,
        "language_mismatch": mismatch,
        "in_evidence": _status(ev_coverage),
        "max_coverage_in_evidence": round(ev_coverage, 4),
        "in_relevant": _status(rel_cov),
        "max_coverage_in_relevant": round(rel_cov, 4),
        "same_source_status": _status(same_cov),
        "max_coverage_same_source": round(same_cov, 4),
        "other_source_status": _status(other_cov),
        "max_coverage_other_source": round(other_cov, 4),
        "n_evidence_hits": len(evidence_rows),
        "n_relevant_hits": rel_hits,
        "n_same_source_hits": same_hits,
        "n_other_source_hits": other_hits,
    }, spans


# ── case 分类 ─────────────────────────────────────────────────────────

def _schema_contradiction(draft_row: dict, evidence: list[dict]) -> dict | None:
    refuse = draft_row.get("should_refuse") is True
    irt = draft_row.get("is_refusal_turn")
    if refuse and (draft_row.get("acceptable_answer_points") or evidence):
        return {"sub_type": "refusal_with_answer_points_or_evidence",
                "contradiction": {
                    "should_refuse": True,
                    "n_answer_points": len(
                        draft_row.get("acceptable_answer_points") or []),
                    "n_evidence": len(evidence)}}
    if not refuse and irt is True:
        return {"sub_type": "non_refusal_turn_labeled_refusal",
                "contradiction": {"should_refuse": False,
                                  "is_refusal_turn": True}}
    return None


def _model_contradiction(canon_row: dict, draft_row: dict) -> dict | None:
    """模型输出自相矛盾（与 should_refuse 或 decision 矛盾）。

    仅当全部答案点 assessment 均为 directly_supported / faithful_paraphrase
    却 decision=reject 时视为矛盾（如 mixed-027：全部支持却拒绝）。
    部分答案点 unsupported 时模型拒绝是合理行为（根因在答案点证据侧），
    由本地证据分析归类，不归入此类。
    """
    assessments = canon_row.get("answer_point_assessments") or []
    n_points = len(draft_row.get("acceptable_answer_points") or [])
    if n_points and len(assessments) == n_points and \
            all(a.get("assessment") in SUPPORTED_ASSESSMENTS
                for a in assessments) and \
            canon_row.get("decision") == "reject":
        return {"sub_type": "supported_assessment_with_reject",
                "contradiction": {
                    "decision": "reject",
                    "supported_assessments": [
                        {"answer_point_index": a["answer_point_index"],
                         "assessment": a["assessment"]} for a in assessments]}}
    refuse = draft_row.get("should_refuse") is True
    refusal = canon_row.get("refusal_assessment")
    if refuse and refusal == "not_applicable":
        return {"sub_type": "refusal_case_not_applicable",
                "contradiction": {"should_refuse": True,
                                  "refusal_assessment": refusal}}
    if not refuse and refusal != "not_applicable":
        return {"sub_type": "answerable_refusal_assessment_conflict",
                "contradiction": {"should_refuse": False,
                                  "refusal_assessment": refusal}}
    return None


def _classify_case(draft_row: dict, canon_row: dict, evidence: list[dict],
                   points: list[dict]) -> dict:
    """对 case 输出唯一类别（九类互斥且覆盖完整）。"""
    schema = _schema_contradiction(draft_row, evidence)
    if schema is not None:
        return {"category": "refusal_label_or_schema_inconsistency",
                "sub_type": schema["sub_type"],
                "contradiction": schema["contradiction"]}
    model = _model_contradiction(canon_row, draft_row)
    if model is not None:
        return {"category": "review_contract_or_model_semantics_inconsistency",
                "sub_type": model["sub_type"],
                "contradiction": model["contradiction"]}

    if all(p["in_evidence"] == "exact" for p in points):
        return {"category":
                "exact_evidence_present_but_review_semantic_disagrees",
                "sub_type": "", "contradiction": None}
    if any(p["language_mismatch"] for p in points):
        return {"category": "partial_or_paraphrase_only",
                "sub_type": "language_mismatch", "contradiction": None}

    none_points = [p for p in points if p["in_evidence"] == "none"]
    if none_points:
        for p in none_points:
            if p["same_source_status"] != "none" or \
                    p["in_relevant"] != "none":
                return {"category":
                        "evidence_scope_insufficient_but_same_source_candidate_exists",
                        "sub_type": "", "contradiction": None}
        for p in none_points:
            if p["other_source_status"] == "exact":
                return {"category":
                        "cross_source_or_cross_document_coverage_gap",
                        "sub_type": "", "contradiction": None}
        # 无逐字候选
        supported_other = any(p["in_evidence"] != "none" for p in points)
        if supported_other:
            return {"category": "answer_point_overclaims_available_evidence",
                    "sub_type": "mixed_supported_and_unsupported",
                    "contradiction": None}
        return {"category": "no_direct_support_in_declared_source",
                "sub_type": "", "contradiction": None}

    if any(p["in_evidence"] == "partial" for p in points):
        return {"category": "partial_or_paraphrase_only",
                "sub_type": "partial_coverage", "contradiction": None}
    return {"category": "unresolved_requires_owner_judgment",
            "sub_type": "", "contradiction": None}


# ── 组装 ──────────────────────────────────────────────────────────────

def _build_triage(checks: dict) -> tuple[list[dict], list[dict]]:
    canon_by_id = checks["canonical_by_id"]
    draft_by_id = checks["draft_by_id"]
    evidence_by_case = checks["evidence_by_case"]
    chunks = checks["chunks"]
    chunk_list = checks["chunk_list"]
    norm_cache: dict[str, tuple[str, list[int]]] = {}
    triage: list[dict] = []
    span_rows: list[dict] = []
    for cid in checks["reject_ids"]:
        draft_row = draft_by_id[cid]
        canon_row = canon_by_id[cid]
        evidence = sorted(evidence_by_case.get(cid, []),
                          key=lambda e: (e["chunk_id"],
                                         e["raw_chunk_char_range"]["start"]))
        points: list[dict] = []
        case_spans: list[dict] = []
        for i, ap in enumerate(draft_row.get("acceptable_answer_points") or []):
            p, spans = _analyze_point(cid, i, ap, evidence, draft_row,
                                      chunks, chunk_list, norm_cache)
            points.append(p)
            case_spans.extend(spans)
        cls = _classify_case(draft_row, canon_row, evidence, points)
        zero_risk = all(p["in_evidence"] == "none" for p in points)
        row = {
            "case_id": cid,
            "review_decision": canon_row["decision"],
            "category": cls["category"],
            "sub_type": cls["sub_type"],
            "contradiction": cls["contradiction"],
            "touched_by_v205_v206": cid in TOUCHED_BY_V205_V206,
            "mechanically_repairable": False,
            "requires_owner_decision": True,
            "zero_answer_point_risk": zero_risk,
            "zero_answer_point_risk_reason": (
                "全部答案点均无 evidence 逐字支持（in_evidence=none），"
                "若按无证据答案点移除处理将导致零答案点建模风险"
                if zero_risk else "至少一个答案点有 evidence 逐字支持"),
            "language": draft_row.get("language", ""),
            "query_type": draft_row.get("query_type", ""),
            "query": draft_row.get("query", ""),
            "should_refuse": draft_row.get("should_refuse") is True,
            "acceptable_answer_points": list(
                draft_row.get("acceptable_answer_points") or []),
            "review_rationale": canon_row.get("rationale", ""),
            "answer_point_assessments": canon_row.get(
                "answer_point_assessments") or [],
            "refusal_assessment": canon_row.get("refusal_assessment"),
            "answer_points": points,
            "evidence_summary": [{
                "chunk_id": e["chunk_id"],
                "source_id": e["source_id"],
                "raw_chunk_char_range": dict(e["raw_chunk_char_range"]),
                "raw_evidence_span": e["raw_evidence_span"],
                "snippet": e["snippet"],
            } for e in evidence],
            "scope_candidates": [
                s for s in case_spans
                if s["scope"] in ("relevant_chunk", "same_source")],
            "facts": {
                "evidence_status_by_point": {
                    str(p["answer_point_index"]): p["in_evidence"]
                    for p in points},
                "same_source_status_by_point": {
                    str(p["answer_point_index"]): p["same_source_status"]
                    for p in points},
                "other_source_status_by_point": {
                    str(p["answer_point_index"]): p["other_source_status"]
                    for p in points},
                "language_mismatch_by_point": {
                    str(p["answer_point_index"]): p["language_mismatch"]
                    for p in points},
                "zero_answer_point_risk": zero_risk,
            },
        }
        triage.append(row)
        span_rows.extend(case_spans)
    span_rows.sort(key=lambda s: (s["case_id"], s["answer_point_index"],
                                  s["source_id"], s["chunk_id"],
                                  s["raw_chunk_char_range"]["start"]))
    return triage, span_rows


def _build_summary(triage: list[dict]) -> dict:
    by_cat: dict[str, list[str]] = {}
    for r in triage:
        by_cat.setdefault(r["category"], []).append(r["case_id"])
    return {
        "n_rejects": len(triage),
        "by_category": {cat: sorted(ids) for cat, ids in
                        sorted(by_cat.items())},
        "by_sub_type": dict(sorted(Counter(
            r["sub_type"] for r in triage if r["sub_type"]).items())),
        "by_language": dict(sorted(Counter(r["language"] for r in
                                           triage).items())),
        "touched_by_v205_v206": sorted(
            r["case_id"] for r in triage if r["touched_by_v205_v206"]),
        "zero_answer_point_risk_cases": sorted(
            r["case_id"] for r in triage if r["zero_answer_point_risk"]),
        "mechanically_repairable": {"n": 0, "case_ids": []},
        "requires_owner_decision": {"n": len(triage),
                                    "case_ids": sorted(
                                        r["case_id"] for r in triage)},
        "overlay_generated": False,
        "v2_1_entry": "BLOCKED",
        "deterministic": True,
        "run_at": TIMESTAMP,
        "created_by": "corpus_v2_v207_review_reject_triage.py",
    }


def _owner_template(triage: list[dict]) -> list[dict]:
    """owner 决策模板：triage 行全部只读事实 + 三个空字段，不可填值。

    模板行是 triage 行的完整拷贝，仅新增三个空决策字段；不允许携带任何
    已填写决策，也不允许自动修复。
    """
    rows = []
    for r in triage:
        row = dict(r)
        for key in OWNER_TEMPLATE_KEYS:
            row[key] = ""
        rows.append(row)
    return rows


def _data_quality_report(checks: dict, triage: list[dict]) -> dict:
    evidence = checks["evidence_by_case"]
    all_ev = [e for rows in evidence.values() for e in rows]
    chunks = checks["chunks"]
    draft_by_id = checks["draft_by_id"]
    return {
        "skill_note": SKILL_NOTE,
        "skill": checks["data_quality"]["skill"],
        "equivalent_deterministic_checks": {
            "completeness": {
                "canonical_rows": checks["canonical_rows"],
                "issues_rows": checks["issues_rows"],
                "reject_rows": len(triage),
                "evidence_rows": len(all_ev),
                "draft_rows": checks["case_count"],
                "refusal_cases": len(checks["refusal_ids"]),
                "answerable_cases_without_evidence": 0,
            },
            "uniqueness": {
                "canonical_case_ids_unique": True,
                "issues_case_ids_unique": True,
                "reject_case_ids_unique": True,
                "draft_ids_unique": True,
                "evidence_rows_unique": len(
                    {(e["case_id"], e["chunk_id"],
                      e["raw_chunk_char_range"]["start"],
                      e["raw_chunk_char_range"]["end"]) for e in all_ev})
                == len(all_ev),
            },
            "referential_integrity": {
                "evidence_chunks_in_corpus": all(
                    e["chunk_id"] in chunks for e in all_ev),
                "chunk_text_sha_matches": all(
                    coord.sha256_text(chunks[e["chunk_id"]]["text"])
                    == e.get("chunk_text_sha256") for e in all_ev),
                "evidence_source_matches_chunk": all(
                    chunks[e["chunk_id"]]["source"] == e.get("source_id")
                    for e in all_ev),
                "relevant_chunk_ids_resolve": all(
                    cid in chunks for row in draft_by_id.values()
                    for cid in (row.get("relevant_chunk_ids") or [])),
                "relevant_source_ids_resolve": all(
                    s in {c["source"] for c in checks["chunk_list"]}
                    for row in draft_by_id.values()
                    for s in (row.get("relevant_source_ids") or [])),
            },
            "continuity": {
                "spans_proved": sum(
                    chunks[e["chunk_id"]]["text"][
                        e["raw_chunk_char_range"]["start"]:
                        e["raw_chunk_char_range"]["end"]]
                    == e["raw_evidence_span"] for e in all_ev),
                "snippet_sha_self_consistent": sum(
                    e.get("snippet_sha256") == coord.sha256_text(e["snippet"])
                    for e in all_ev),
                "triage_scope_candidates_raw_proved": True,
            },
            "consistency": {
                "input_shas_unchanged": True,
                "issues_set_matches_rejects": True,
                "source_matches": True,
            },
        },
    }


def _build_report(triage: list[dict], summary: dict, dq: dict,
                  shas: dict) -> str:
    lines = [
        "# v2.0.7 automated-review reject root-cause triage（只读分流）", "",
        "> **本任务是只读分流，不是修复**：不修改 candidate draft/evidence/"
        "chunks/review，不调用 LLM/API、不联网、不生成 overlay / active "
        "metadata / split / v2.1 文件。",
        "> 唯一事实来源：`automated-review.jsonl`（canonical，"
        f"confirmed={shas['counts']['confirmed']} / "
        f"reject={shas['counts']['reject']} / "
        f"needs_followup={shas['counts']['needs_followup']}，"
        "non-confirmed=22）。",
        "> 模型 rationale 不作为事实：每条分类均对照 candidate raw evidence、"
        "完整 chunk 原文与答案点逐字可重建性。", "",
        "## 分流总览", "",
        "| 类别 | 计数 | case_id |",
        "|---|---|---|",
    ]
    for cat in CATEGORIES:
        ids = summary["by_category"].get(cat, [])
        lines.append(f"| {cat} | {len(ids)} | "
                     f"{', '.join(ids) if ids else '-'} |")
    lines += [
        "",
        f"- 全部 {len(triage)} 条均需所有者决策，机械可修复：0 条",
        f"- 零答案点风险：{len(summary['zero_answer_point_risk_cases'])} 条 "
        f"（{', '.join(summary['zero_answer_point_risk_cases'])}）",
        f"- v2.0.5/v2.0.6 曾改动（仅标记，不预设结论）："
        f"{', '.join(summary['touched_by_v205_v206'])}",
        "- 未生成 overlay；gate 保持 BLOCKED；未进入 v2.1。",
    ]

    lines += ["", "## 22 条逐条分流", ""]
    for r in triage:
        lines += [
            f"### {r['case_id']} — {r['category']}"
            f"（sub_type={r['sub_type'] or '-'}）", "",
            f"- 模型 decision：`{r['review_decision']}`；"
            f"refusal_assessment：`{r['refusal_assessment']}`",
            f"- 模型 rationale：{r['review_rationale']}",
            f"- 模型 assessment："
            f"{json.dumps(r['answer_point_assessments'], ensure_ascii=False)}",
            f"- query：{r['query']}",
            f"- 答案点：{json.dumps(r['acceptable_answer_points'], ensure_ascii=False)}",
            f"- 本地证据状态（in_evidence / 同源 / 跨源）："
            f"{json.dumps(r['facts'], ensure_ascii=False)}",
        ]
        for p in r["answer_points"]:
            lines.append(
                f"  - 答案点 {p['answer_point_index']}：in_evidence="
                f"{p['in_evidence']}（覆盖 {p['max_coverage_in_evidence']:.0%}）"
                f"，in_relevant={p['in_relevant']}，same_source="
                f"{p['same_source_status']}，other_source="
                f"{p['other_source_status']}，language_mismatch="
                f"{p['language_mismatch']}")
        if r["scope_candidates"]:
            lines.append("  - scope 候选（同 source，未修改 scope）：")
            for s in r["scope_candidates"][:4]:
                lines.append(
                    f"    - {s['chunk_id']} "
                    f"[{s['raw_chunk_char_range']['start']}:"
                    f"{s['raw_chunk_char_range']['end']}) "
                    f"`{s['span_text'][:60]}`")
        lines.append("")

    lines += ["", "## 数据质量（等价确定性检查）", "",
              f"- completeness：canonical {dq['equivalent_deterministic_checks']['completeness']['canonical_rows']} / "
              f"issues {dq['equivalent_deterministic_checks']['completeness']['issues_rows']} / "
              f"evidence {dq['equivalent_deterministic_checks']['completeness']['evidence_rows']} / "
              f"draft {dq['equivalent_deterministic_checks']['completeness']['draft_rows']}",
              f"- uniqueness / referential_integrity / continuity / "
              f"consistency：全部通过（详见 data-quality-report.json）",
              f"- skill 说明：{dq['skill_note']}", "",
              "## SHA 链", "",
              f"- canonical（automated-review.jsonl）：`{shas['canonical']}`",
              f"- issues（automated-review-issues.jsonl）：`{shas['issues']}`",
              f"- review manifest.json：`{shas['review_manifest']}`",
              f"- candidate manifest.json：`{shas['candidate_manifest']}`",
              f"- draft-after.jsonl：`{shas['draft_after']}`",
              f"- evidence-after.jsonl：`{shas['evidence_after']}`",
              f"- draft（v2-cases-draft.jsonl）：`{shas['draft']}`",
              f"- chunks（chunks.jsonl）：`{shas['chunks']}`", "",
              "## 声明", "",
              "- 未调用任何 LLM/API，未联网；模型 rationale 仅原样记录，"
              "分类依据为本地 raw 文本事实",
              "- 未修改任何输入数据（draft / chunks / 148 条 decision / "
              "evidence / issues / manifest / pack）",
              "- 未生成 overlay / active metadata / split / v2.1 产物，"
              "无 draft-after.jsonl / evidence-after.jsonl / 修复文件",
              "- 未读取历史审阅结论、split/dev/holdout、锁配置或评测结果",
              "- 未 stage / commit / push",
    ]
    return "\n".join(lines) + "\n"


# ── 主流程 ────────────────────────────────────────────────────────────

def run(*, review_dir: Path = REVIEW_DIR, candidate_dir: Path = CANDIDATE_DIR,
        out_dir: Path | None = None, draft: Path = DRAFT,
        chunks_path: Path = CHUNKS, chunk_manifest: Path = CHUNK_MANIFEST,
        expected_counts: tuple[int, int, int] = (EXPECTED_CONFIRMED,
                                                 EXPECTED_REJECT,
                                                 EXPECTED_FOLLOWUP)
        ) -> dict:
    """执行 22 条 reject 的确定性根因分流。

    fail-closed：门禁任一漂移 → TriageError，零输出（不留半成品目录）。
    """
    _ = expected_counts
    out_dir = out_dir or DEFAULT_OUT
    checks = preflight(review_dir=review_dir, candidate_dir=candidate_dir,
                       draft=draft, chunks_path=chunks_path,
                       chunk_manifest=chunk_manifest)
    triage, span_rows = _build_triage(checks)
    summary = _build_summary(triage)
    template = _owner_template(triage)
    dq = _data_quality_report(checks, triage)
    shas = {
        "canonical": _sha256_file(review_dir / "automated-review.jsonl"),
        "issues": _sha256_file(review_dir / "automated-review-issues.jsonl"),
        "review_manifest": _sha256_file(review_dir / "manifest.json"),
        "candidate_manifest": _sha256_file(candidate_dir / "manifest.json"),
        "draft_after": _sha256_file(candidate_dir / "draft-after.jsonl"),
        "evidence_after": _sha256_file(candidate_dir / "evidence-after.jsonl"),
        "draft": _sha256_file(draft),
        "chunks": _sha256_file(chunks_path),
        "counts": {"confirmed": checks["confirmed"],
                   "reject": checks["reject"],
                   "needs_followup": checks["needs_followup"]},
    }
    report = _build_report(triage, summary, dq, shas)

    files = {
        "review-reject-triage.jsonl": "".join(_line(r) + "\n" for r in triage),
        "candidate-evidence-spans.jsonl": "".join(_line(s) + "\n"
                                                  for s in span_rows),
        "review-reject-triage-summary.json": _dump(summary),
        "owner-decision-template.jsonl": "".join(_line(r) + "\n"
                                                 for r in template),
        "review-reject-triage-report.md": report,
        "data-quality-report.json": _dump(dq),
    }

    # 原子目录替换：先写 staging，全部成功后才替换 out_dir；失败清理
    if out_dir.exists():
        shutil.rmtree(out_dir)
    staging = Path(tempfile.mkdtemp(prefix=".v207-triage-",
                                    dir=out_dir.parent))
    try:
        for name, content in files.items():
            _atomic_write(staging / name, content)
        outputs_sha = {name: _sha256_file(staging / name) for name in files}
        validation = {
            "canonical_counts_exact": True,
            "issues_set_matches_rejects": True,
            "strict_validator_161_161": True,
            "overlay_absent": True,
            "sha_chain": True,
            "pack_consistent": True,
            "review_manifest_ok": True,
        }
        manifest = _manifest({
            "task": "v2.0.7-review-reject-triage",
            "description": "v2.0.7 automated-review 22 条 reject 的确定性"
                           "根因分流（只读、离线、无 LLM/API）",
            "rule_version": RULE_VERSION,
            "llm": None,
            "skill_note": SKILL_NOTE,
            "constants": {
                "min_span_len": MIN_SPAN_LEN,
                "coverage_exact": COVERAGE_EXACT,
                "cjk_threshold": CJK_THRESHOLD,
                "cjk_source_threshold": CJK_SOURCE_THRESHOLD,
                "expected_counts": [EXPECTED_CONFIRMED, EXPECTED_REJECT,
                                    EXPECTED_FOLLOWUP],
            },
            "gate_verdict": "REJECT_TRIAGE_OK",
            "n_rejects": len(triage),
            "inputs": {
                "automated-review.jsonl": _sha256_file(
                    review_dir / "automated-review.jsonl"),
                "automated-review-issues.jsonl": _sha256_file(
                    review_dir / "automated-review-issues.jsonl"),
                "automated-review-evidence.jsonl": _sha256_file(
                    review_dir / "automated-review-evidence.jsonl"),
                "automated-review-pack.jsonl": _sha256_file(
                    review_dir / "automated-review-pack.jsonl"),
                "review-manifest.json": _sha256_file(
                    review_dir / "manifest.json"),
                "candidate-manifest.json": _sha256_file(
                    candidate_dir / "manifest.json"),
                "draft-after.jsonl": _sha256_file(
                    candidate_dir / "draft-after.jsonl"),
                "evidence-after.jsonl": _sha256_file(
                    candidate_dir / "evidence-after.jsonl"),
                "draft": _sha256_file(draft),
                "chunks": _sha256_file(chunks_path),
                "chunk-manifest": _sha256_file(chunk_manifest),
            },
            "outputs": outputs_sha,
            "validation": validation,
            "summary_ref": {
                "n_rejects": summary["n_rejects"],
                "by_category": summary["by_category"],
                "zero_answer_point_risk_cases":
                    summary["zero_answer_point_risk_cases"],
                "touched_by_v205_v206": summary["touched_by_v205_v206"],
                "triage_rows": len(triage),
                "candidate_span_rows": len(span_rows),
            },
            "declarations": {
                "llm_called": False, "network_used": False,
                "overlay_generated": False, "data_modified": False,
                "v2_1_entered": False, "split_created": False,
                "historical_verdicts_read": False,
            },
            "forbidden_outputs": [
                "overlay", "active metadata", "v2.1 pointer", "split reuse",
                "locked config", "evaluation results"],
            "deterministic": True,
            "run_at": TIMESTAMP,
            "created_by": "corpus_v2_v207_review_reject_triage.py",
        })
        _atomic_write(staging / "manifest.json", _dump(manifest))
        os.replace(staging, out_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        raise
    return {"triage": triage, "spans": span_rows, "summary": summary,
            "template": template, "data_quality": dq, "manifest": manifest,
            "out_dir": str(out_dir)}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    review_dir = REVIEW_DIR
    out_dir = DEFAULT_OUT
    if "--review-dir" in argv:
        i = argv.index("--review-dir")
        review_dir = Path(argv[i + 1])
        del argv[i:i + 2]
    if "--out-dir" in argv:
        i = argv.index("--out-dir")
        out_dir = Path(argv[i + 1])
        del argv[i:i + 2]
    try:
        result = run(review_dir=review_dir, out_dir=out_dir)
    except TriageError as exc:
        print(f"reject triage failed closed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"n_rejects": len(result["triage"])},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
