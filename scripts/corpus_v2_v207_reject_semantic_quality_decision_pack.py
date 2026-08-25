"""v2.0.7 reject semantic-quality closure decision pack（只读、确定性、离线）。

基于 v2.0.7 reject triage 的 22 条 reject，生成面向所有者批量决策的“语义质量
闭环决策包”。**本任务不是修复**：不修改 candidate draft/evidence/chunks/review/
triage，不调用 LLM/API、不联网、不生成 overlay、active metadata、split 或
v2.1 文件；不提供“放宽 automated review 标准”作为默认动作。

输入（仅允许）：
- v2.0.7 candidate revision（manifest / draft-after / evidence-after）
- v2.0.7 automated-review（canonical / issues / evidence / pack / manifest）
- v2.0.7 reject-triage（全部 7 个输出）
- 当前 v2 draft、chunks、chunk manifest
- raw-codepoint-v1 契约与 strict validator（复用 reject-triage 的 preflight）

不读取：历史 review、split/dev/holdout、锁配置、历史评测、Graph/Reranker 结果。

fail-closed 门禁（任一漂移 → DecisionPackError，零输出）：
- reject 集合恰 22 条；triage 集合 == reject 集合；triage 行恰 22 条唯一
- triage 类别分布恰好 8 / 5 / 6 / 2 / 1（其余类别 0）
- candidate 148 条、strict evidence 161/161、无 automated overlay
- review manifest / candidate manifest / triage manifest 自哈希 + outputs SHA
- triage manifest inputs == 当前磁盘 SHA；review/candidate/triage 输入不变

逐条语义质量分析（纯机械、确定性）：
- 对每个答案点，在同 source 全 chunk 中做归一化逐字匹配（coverage >= 0.75），
  对每个命中扩展出**更完整**的候选：
  - full_sentence：句子单元以句末标点（。！？!?…或句点）结尾且非编号点；
  - full_paragraph：段落单元以句末标点结尾；
  - heading / line_label：仅当无完整句/段时退回行级（标题/TOC 条目等）。
- 边界规则（写入常量以便复算）：空行、标题行（#）、列表/TOC 行
  （^- 或 ^数字.）、真代码块（``` 且至少一侧有空行）为段落边界；行内代码
  栅栏（两侧无空行，如 ``json``）不切分句子；ASCII '.' 后跟数字视为编号点
  而非句末（排除 "4.10." 误判）。
- 每个候选记录 source/chunk/raw range/raw span（chunk_text[start:end] ==
  raw_span 强制断言）、归一化 coverage（全部 >= 0.75，绝不把 partial/
  paraphrase 写成 exact）、在源内精确出现次数与唯一性、是否已在当前 evidence
  span 内（scope_expansion_required = 未覆盖）。
- semantic_quality_insufficient：答案点无任何自包含完整句/段候选 → 仅孤立
  token/标题/短标签支撑。
- removal_zero_risk：推荐移除/退役动作会移除全部答案点。

默认推荐（不自动应用，全部进入五批次建议）：
- cat1 exact_evidence_present_but_review_semantic_disagrees：有自包含完整句
  候选 → replace_answer_point_with_self_contained_exact_raw_text（batch_a）；
  否则仅孤立 token/标题/短标签 → retire_case（batch_d）。
- cat4 evidence_scope_insufficient_but_same_source_candidate_exists：全部答案点
  有逐字候选 → expand_same_source_evidence_scope（batch_b）；部分有
  in_evidence=none 答案点 → remove_unsupported_answer_point（batch_d）；
  全部无证据 → retire_case。
- cat2 partial_or_paraphrase_only：language_mismatch（中文答案点 + 英文源）→
  owner_approved_translation_equivalence_policy（batch_c，不得自动判翻译等价为
  confirmed）；partial_coverage 有 exact 源语言文本 → replace_with_exact_source_
  language_text；否则 remove/retire。
- cat5 no_direct_support_in_declared_source：仅 retire_case / keep_unresolved。
- cat8 review_contract_or_model_semantics_inconsistency（mixed-027）：输出本地
  契约证明，仅 targeted_blind_re_review / keep_unresolved，不因“模型似乎矛盾”
  自动改为 confirmed。

产物（automated-review/reject-semantic-quality-decision-pack/）：
semantic-quality-decision-pack.jsonl / self-contained-raw-candidates.jsonl /
owner-batch-decision-template.jsonl / OWNER_SEMANTIC_QUALITY_DECISION_GUIDE.md /
decision-pack-summary.json / decision-pack-report.md / data-quality-report.json /
manifest.json。

CLI::

    python scripts/corpus_v2_v207_reject_semantic_quality_decision_pack.py
        [--review-dir DIR] [--candidate-dir DIR] [--triage-dir DIR]
        [--out-dir DIR]
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import corpus_v2_evidence_coordinate_repair as coord
from scripts import corpus_v2_remaining_blockers_decision_pack as rbp
from scripts import corpus_v2_v207_review_reject_triage as triage_mod
from scripts.corpus_v2_v207_review_reject_triage import (  # 复用既有确定性原语
    _atomic_write, _collect_spans, _dump, _jsonl, _line, _manifest,
    _match_in_norm, _norm_with_map, _sha256_file, _sha256_text,
    _verify_self_hash,
)

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_DIR = triage_mod.CANDIDATE_DIR
REVIEW_DIR = triage_mod.REVIEW_DIR
TRIAGE_DIR = REVIEW_DIR / "reject-triage"
DEFAULT_OUT = REVIEW_DIR / "reject-semantic-quality-decision-pack"
DRAFT_AFTER = triage_mod.DRAFT_AFTER
EVIDENCE_AFTER = triage_mod.EVIDENCE_AFTER
CANDIDATE_MANIFEST = triage_mod.CANDIDATE_MANIFEST
DRAFT = rbp.DRAFT
CHUNKS = rbp.CHUNKS
CHUNK_MANIFEST = rbp.CHUNK_MANIFEST
TIMESTAMP = "2026-08-10T00:00:00+00:00"
RULE_VERSION = "v2.0.7-reject-semantic-quality-decision-pack-1"
CONTRACT = "raw-codepoint-v1"

EXPECTED_CASE_COUNT = 148
EXPECTED_CONFIRMED = 126
EXPECTED_REJECT = 22
EXPECTED_FOLLOWUP = 0
EXPECTED_EVIDENCE_COUNT = 161

# 类别分布门禁：8 / 5 / 6 / 2 / 1（其余类别必须为 0）
EXPECTED_DISTRIBUTION = {
    "exact_evidence_present_but_review_semantic_disagrees": 8,
    "partial_or_paraphrase_only": 5,
    "evidence_scope_insufficient_but_same_source_candidate_exists": 6,
    "no_direct_support_in_declared_source": 2,
    "review_contract_or_model_semantics_inconsistency": 1,
}
CAT1 = "exact_evidence_present_but_review_semantic_disagrees"
CAT2 = "partial_or_paraphrase_only"
CAT4 = "evidence_scope_insufficient_but_same_source_candidate_exists"
CAT5 = "no_direct_support_in_declared_source"
CAT8 = "review_contract_or_model_semantics_inconsistency"

BATCHES = (
    "batch_a_replace_with_self_contained_exact_text",
    "batch_b_expand_same_source_scope",
    "batch_c_translation_policy_required",
    "batch_d_retire_or_remove",
    "batch_e_targeted_re_review",
)

# 推荐动作词表 → 建议批次（owner 决策参考，绝不自动应用）
ACTIONS_TO_BATCHES = {
    "replace_answer_point_with_self_contained_exact_raw_text": BATCHES[0],
    "replace_with_exact_source_language_text": BATCHES[0],
    "expand_same_source_evidence_scope": BATCHES[1],
    "owner_approved_translation_equivalence_policy": BATCHES[2],
    "remove_semantically_insufficient_answer_point": BATCHES[3],
    "remove_unsupported_answer_point": BATCHES[3],
    "retire_case": BATCHES[3],
    "keep_unresolved": BATCHES[3],
    "targeted_blind_re_review": BATCHES[4],
}

# 各类别的所有者可选动作（“放宽 review 标准”不提供）
OPTIONS_BY_CATEGORY = {
    CAT1: ["replace_answer_point_with_self_contained_exact_raw_text",
           "remove_semantically_insufficient_answer_point",
           "retire_case", "keep_unresolved"],
    CAT2: ["replace_with_exact_source_language_text",
           "owner_approved_translation_equivalence_policy",
           "remove_unsupported_answer_point", "retire_case",
           "keep_unresolved"],
    CAT4: ["expand_same_source_evidence_scope",
           "remove_unsupported_answer_point", "retire_case",
           "keep_unresolved"],
    CAT5: ["retire_case", "keep_unresolved"],
    CAT8: ["targeted_blind_re_review", "keep_unresolved"],
}

OWNER_TEMPLATE_KEYS = ("owner_decision", "owner_reviewer", "owner_notes")

OUTPUT_FILES = (
    "semantic-quality-decision-pack.jsonl",
    "self-contained-raw-candidates.jsonl",
    "owner-batch-decision-template.jsonl",
    "OWNER_SEMANTIC_QUALITY_DECISION_GUIDE.md",
    "decision-pack-summary.json",
    "decision-pack-report.md",
    "data-quality-report.json",
    "manifest.json",
)

# 机械判定阈值（与 v2.0.1/v2.0.7 triage 一致）
MIN_SPAN_LEN = triage_mod.MIN_SPAN_LEN          # 8
COVERAGE_EXACT = triage_mod.COVERAGE_EXACT      # 0.75
CJK_THRESHOLD = triage_mod.CJK_THRESHOLD
CJK_SOURCE_THRESHOLD = triage_mod.CJK_SOURCE_THRESHOLD

# 候选句搜索上限（确定性；写入 manifest 以便复算）
MAX_CANDIDATES_PER_CHUNK = 8
MAX_CANDIDATES_PER_AP = 24

SKILL_NOTE = (
    "data-analytics:analyze-data-quality skill 在本环境中不可用"
    "（已尝试加载，返回 Skill not found）；已按任务约束实施等价的确定性"
    "质量检查（完整性 / 唯一性 / 引用完整性 / 连续性 / 一致性），"
    "全部为机械复算，无 LLM 参与。")

# 句末标点；ASCII '.' 仅在其前一字符非数字且后随空白/结尾时视为句末
# （排除 "4.10." 这类编号点误判）
_TERMINAL = set("。！？!?…")
_LIST_RE = re.compile(r"^\s*([-*+]|\d+(\.\d+)*\.)\s")


class DecisionPackError(Exception):
    """fail-closed 校验失败：零输出。"""


# ── 句子/段落边界（确定性、可复算）─────────────────────────────────────

def _is_sentence_end(text: str, i: int) -> bool:
    ch = text[i]
    if ch in _TERMINAL:
        return True
    if ch == ".":
        prev = text[i - 1] if i > 0 else ""
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if prev.isdigit():      # "3.1." 编号点
            return False
        if nxt and not nxt.isspace():   # "e.g." 缩写点
            return False
        return True
    return False


def _ends_terminal(s: str) -> bool:
    """候选是否以句末标点结尾（排除编号点结尾如 '4.10.'）。"""
    stripped = s.rstrip()
    if not stripped:
        return False
    last = stripped[-1]
    if last in _TERMINAL:
        return True
    if last == ".":
        return len(stripped) >= 2 and not stripped[-2].isdigit()
    return False


def _segment_bounds(text: str, pos: int) -> tuple[int, int]:
    """段落边界：空行 / 标题行 / 列表·TOC 行 / 真代码块（``` 且一侧有空行）。

    行内代码栅栏（两侧无空行，如 ``del``/``json``）不切分句子。
    """
    lines = text.split("\n")
    count = 0
    idx = 0
    for li, ln in enumerate(lines):
        if count + len(ln) > pos:
            idx = li
            break
        count += len(ln) + 1

    def is_boundary(li: int) -> bool:
        s = lines[li].strip()
        if s == "":
            return True
        if s.startswith("#"):
            return True
        if _LIST_RE.match(lines[li]):
            return True
        if s.startswith("```") or s.startswith("~~~"):
            above = lines[li - 1].strip() == "" if li > 0 else True
            below = lines[li + 1].strip() == "" if li + 1 < len(lines) else True
            return above or below
        return False

    start_li = idx
    while start_li > 0 and not is_boundary(start_li - 1):
        start_li -= 1
    end_li = idx
    while end_li < len(lines) - 1 and not is_boundary(end_li + 1):
        end_li += 1
    s = sum(len(l) + 1 for l in lines[:start_li])
    e = sum(len(l) + 1 for l in lines[:end_li]) + len(lines[end_li])
    return s, e


def _sentence_bounds(text: str, seg_s: int, seg_e: int, pos: int
                     ) -> tuple[int, int]:
    """段内包含 pos 的句子单元（含句末标点与尾部闭合引号）。"""
    s = pos
    while s > seg_s and not _is_sentence_end(text, s - 1):
        s -= 1
    e = pos
    while e < seg_e and not _is_sentence_end(text, e):
        e += 1
    if e < seg_e:
        e += 1
    while e < seg_e and text[e] in "」』”’\"')】》›»>…":
        e += 1
    s2, e2 = s, e
    while s2 < e2 and text[s2] in "\n \t":
        s2 += 1
    while e2 > s2 and text[e2 - 1] in "\n \t":
        e2 -= 1
    return s2, e2


def _line_bounds(text: str, pos: int) -> tuple[int, int]:
    s = text.rfind("\n", 0, pos) + 1
    e = text.find("\n", pos)
    if e < 0:
        e = len(text)
    return s, e


# ── fail-closed 输入门禁 ──────────────────────────────────────────────

def _required_files(review_dir: Path, candidate_dir: Path, triage_dir: Path,
                    draft: Path, chunks_path: Path,
                    chunk_manifest: Path) -> list[Path]:
    files = [
        review_dir / "automated-review.jsonl",
        review_dir / "automated-review-issues.jsonl",
        review_dir / "automated-review-evidence.jsonl",
        review_dir / "automated-review-pack.jsonl",
        review_dir / "automated-review-summary.json",
        review_dir / "automated-review-report.md",
        review_dir / "automated-review-gate-report.md",
        review_dir / "raw-model-responses.jsonl",
        review_dir / "manifest.json",
        candidate_dir / "manifest.json",
        candidate_dir / "draft-after.jsonl",
        candidate_dir / "evidence-after.jsonl",
        triage_dir / "review-reject-triage.jsonl",
        triage_dir / "candidate-evidence-spans.jsonl",
        triage_dir / "review-reject-triage-summary.json",
        triage_dir / "owner-decision-template.jsonl",
        triage_dir / "review-reject-triage-report.md",
        triage_dir / "data-quality-report.json",
        triage_dir / "manifest.json",
        draft, chunks_path, chunk_manifest,
    ]
    return files


def preflight(*, review_dir: Path = REVIEW_DIR,
              candidate_dir: Path = CANDIDATE_DIR,
              triage_dir: Path = TRIAGE_DIR, draft: Path = DRAFT,
              chunks_path: Path = CHUNKS,
              chunk_manifest: Path = CHUNK_MANIFEST) -> dict:
    """只读校验全部输入契约；任一漂移 → DecisionPackError（零输出）。"""
    if not all(f.is_file() for f in _required_files(
            review_dir, candidate_dir, triage_dir, draft, chunks_path,
            chunk_manifest)):
        raise DecisionPackError("输入文件缺失")

    # ── review/candidate 侧门禁（复用 reject-triage preflight）──
    try:
        checks = triage_mod.preflight(
            review_dir=review_dir, candidate_dir=candidate_dir, draft=draft,
            chunks_path=chunks_path, chunk_manifest=chunk_manifest)
    except triage_mod.TriageError as exc:
        raise DecisionPackError(f"review/candidate 门禁失败: {exc}") from exc

    # ── triage manifest 自哈希 + outputs SHA ──
    tman = json.loads((triage_dir / "manifest.json").read_text(
        encoding="utf-8"))
    if not _verify_self_hash(tman):
        raise DecisionPackError("triage manifest 自哈希不符")
    triage_manifest_ok = True
    for name, expected in tman.get("outputs", {}).items():
        if expected != _sha256_file(triage_dir / name):
            triage_manifest_ok = False
            raise DecisionPackError(f"triage manifest output SHA 不符: {name}")

    # ── triage manifest inputs == 当前磁盘 SHA（输入链闭环）──
    inputs_unchanged = True
    input_paths = {
        "automated-review.jsonl": review_dir / "automated-review.jsonl",
        "automated-review-issues.jsonl":
            review_dir / "automated-review-issues.jsonl",
        "automated-review-evidence.jsonl":
            review_dir / "automated-review-evidence.jsonl",
        "automated-review-pack.jsonl":
            review_dir / "automated-review-pack.jsonl",
        "review-manifest.json": review_dir / "manifest.json",
        "candidate-manifest.json": candidate_dir / "manifest.json",
        "draft-after.jsonl": candidate_dir / "draft-after.jsonl",
        "evidence-after.jsonl": candidate_dir / "evidence-after.jsonl",
        "draft": draft, "chunks": chunks_path,
        "chunk-manifest": chunk_manifest,
    }
    for name, path in input_paths.items():
        if tman.get("inputs", {}).get(name) != _sha256_file(path):
            inputs_unchanged = False
            raise DecisionPackError(f"triage manifest input SHA 不符: {name}")

    # ── triage 行：22 条唯一、集合 == reject、分布 8/5/6/2/1 ──
    triage_rows = _jsonl(triage_dir / "review-reject-triage.jsonl")
    triage_ids = [r["case_id"] for r in triage_rows]
    if len(triage_rows) != EXPECTED_REJECT or \
            len(set(triage_ids)) != EXPECTED_REJECT:
        raise DecisionPackError("triage 行数/唯一性不符")
    if set(triage_ids) != set(checks["reject_ids"]):
        raise DecisionPackError("triage 集合与 canonical reject 集合不一致")
    counts = Counter(r["category"] for r in triage_rows)
    distribution = {c: counts.get(c, 0) for c in EXPECTED_DISTRIBUTION}
    if distribution != EXPECTED_DISTRIBUTION:
        raise DecisionPackError(
            "triage 类别分布漂移: " + json.dumps(distribution,
                                                 ensure_ascii=False))
    unexpected = [c for c in counts if c not in EXPECTED_DISTRIBUTION
                  and counts[c]]
    if unexpected:
        raise DecisionPackError(f"triage 存在未预期类别: {unexpected}")

    # ── triage summary 一致性（冗余校验）──
    tsummary = json.loads((triage_dir / "review-reject-triage-summary.json")
                          .read_text(encoding="utf-8"))
    if tsummary.get("n_rejects") != EXPECTED_REJECT:
        raise DecisionPackError("triage summary n_rejects 不符")

    skill = {"name": "data-analytics:analyze-data-quality",
             "available": False,
             "failure": "Skill not found: data-analytics:analyze-data-quality"}
    return {
        "canonical_rows": checks["canonical_rows"],
        "confirmed": checks["confirmed"],
        "reject": checks["reject"],
        "needs_followup": checks["needs_followup"],
        "reject_ids": checks["reject_ids"],
        "triage_ids": sorted(triage_ids),
        "triage_rows": len(triage_rows),
        "distribution": distribution,
        "case_count": checks["case_count"],
        "evidence_count": checks["evidence_count"],
        "strict_validator_covered": checks["strict_validator_covered"],
        "strict_validator_passed": checks["strict_validator_passed"],
        "overlay_absent": checks["overlay_absent"],
        "inputs_unchanged": inputs_unchanged,
        "triage_manifest_ok": triage_manifest_ok,
        "refusal_ids": checks["refusal_ids"],
        "canonical_by_id": checks["canonical_by_id"],
        "draft_by_id": checks["draft_by_id"],
        "triage_rows_by_id": {r["case_id"]: r for r in triage_rows},
        "chunks": checks["chunks"],
        "chunk_list": checks["chunk_list"],
        "triage_manifest": tman,
        "data_quality": {
            "skill": skill,
            "equivalent_deterministic_checks": {
                "completeness": {
                    "canonical_rows": len(checks["canonical_by_id"]),
                    "triage_rows": len(triage_rows),
                    "evidence_rows": checks["evidence_count"],
                    "draft_rows": checks["case_count"],
                    "refusal_cases": len(checks["refusal_ids"])},
                "uniqueness": {
                    "canonical_case_ids_unique": True,
                    "triage_case_ids_unique": True,
                    "draft_ids_unique": True},
                "referential_integrity": {
                    "evidence_chunks_in_corpus": True,
                    "triage_manifest_self_hash": True},
                "continuity": {
                    "triage_inputs_unchanged": inputs_unchanged,
                    "triage_spans_proved": True},
                "consistency": {
                    "distribution_exact": distribution == EXPECTED_DISTRIBUTION,
                    "triage_set_matches_rejects": set(triage_ids) ==
                    set(checks["reject_ids"])},
            },
        },
    }


# ── 逐答案点候选句搜索 ────────────────────────────────────────────────

def _search_candidates(case_id: str, ap_idx: int, answer_point: str,
                       triage_row: dict, draft_row: dict, checks: dict,
                       norm_cache: dict) -> tuple[list[dict], list[dict]]:
    """同 source 全文中找出包含答案点（coverage >= 0.75）的更完整候选。

    返回 (ap_analysis, candidate_rows)。候选 span 全部强制
    chunk_text[start:end] == raw_span。
    """
    chunks = checks["chunks"]
    chunk_list = checks["chunk_list"]
    src_ids = set(draft_row.get("relevant_source_ids") or [])
    evidence_chunk_ids = {e["chunk_id"] for e in triage_row["evidence_summary"]}
    relevant_ids = set(draft_row.get("relevant_chunk_ids") or [])
    ev_spans = [(e["chunk_id"], e["raw_chunk_char_range"]["start"],
                 e["raw_chunk_char_range"]["end"])
                for e in triage_row["evidence_summary"]]

    ap_norm, _ = _norm_with_map(answer_point)
    n_ap = max(1, len(ap_norm))
    ms = min(MIN_SPAN_LEN, n_ap)
    candidate_rows: list[dict] = []
    for chunk in chunk_list:
        if chunk["source"] not in src_ids:
            continue
        cid = chunk["chunk_id"]
        if cid not in norm_cache:
            norm_cache[cid] = _norm_with_map(chunk["text"])
        norm, offs = norm_cache[cid]
        spans = _collect_spans(ap_norm, norm, ms)
        per_chunk: list[dict] = []
        for a, e1, b, e2 in spans:
            cov = (e1 - a) / n_ap
            if cov < COVERAGE_EXACT:
                continue
            text = chunk["text"]
            cs = offs[b]
            seg_s, seg_e = _segment_bounds(text, cs)
            ss, se = _sentence_bounds(text, seg_s, seg_e, cs)
            sent = text[ss:se]
            if len(_norm_with_map(sent)[0]) <= n_ap:
                continue  # 候选必须比答案点更完整
            if _ends_terminal(sent):
                ctype = "full_sentence"
            else:
                par = text[seg_s:seg_e].strip("\n ")
                if _ends_terminal(par):
                    ctype = "full_paragraph"
                    ss, se = seg_s, seg_e
                else:
                    ls, le = _line_bounds(text, cs)
                    line = text[ls:le].strip()
                    if not line:
                        continue
                    ctype = ("heading" if line.lstrip().startswith("#")
                             else "line_label")
                    ss, se = ls, le
            if any(r["chunk_id"] == cid and r["raw_chunk_char_range"] ==
                   {"start": ss, "end": se} for r in per_chunk):
                continue
            if any(r["chunk_id"] == cid and r["raw_chunk_char_range"] ==
                   {"start": ss, "end": se} for r in candidate_rows):
                continue
            span_text = text[ss:se]
            if span_text != text[ss:se]:
                raise DecisionPackError(f"{case_id} 候选 span 越界")
            exact_count = sum(
                c2["text"].count(span_text) for c2 in chunk_list
                if c2["source"] == chunk["source"])
            covered = any(cid == ev_cid and ss >= ev_s and se <= ev_e
                          for ev_cid, ev_s, ev_e in ev_spans)
            self_contained = ctype in ("full_sentence", "full_paragraph")
            row = {
                "case_id": case_id,
                "answer_point_index": ap_idx,
                "answer_point": answer_point,
                "candidate_type": ctype,
                "self_contained": self_contained,
                "source_id": chunk["source"],
                "chunk_id": cid,
                "raw_chunk_char_range": {"start": ss, "end": se},
                "raw_span": span_text,
                "coverage": round(cov, 4),
                "exact_count_in_source": exact_count,
                "unique": exact_count == 1,
                "in_evidence_chunk": cid in evidence_chunk_ids,
                "in_relevant_chunk": cid in relevant_ids,
                "scope_expansion_required": not covered,
            }
            per_chunk.append(row)
            candidate_rows.append(row)
            if len(per_chunk) >= MAX_CANDIDATES_PER_CHUNK:
                break
        if len(candidate_rows) >= MAX_CANDIDATES_PER_AP:
            break

    n_self = sum(1 for r in candidate_rows if r["self_contained"])
    refs = [{
        "chunk_id": r["chunk_id"],
        "raw_chunk_char_range": dict(r["raw_chunk_char_range"]),
        "candidate_type": r["candidate_type"],
        "self_contained": r["self_contained"],
        "unique": r["unique"],
        "scope_expansion_required": r["scope_expansion_required"],
        "coverage": r["coverage"],
    } for r in candidate_rows]
    refs.sort(key=lambda r: (r["chunk_id"],
                             r["raw_chunk_char_range"]["start"]))
    analysis = {
        "answer_point_index": ap_idx,
        "answer_point": answer_point,
        "in_evidence": triage_row["answer_points"][ap_idx]["in_evidence"],
        "in_relevant": triage_row["answer_points"][ap_idx]["in_relevant"],
        "same_source_status":
            triage_row["answer_points"][ap_idx]["same_source_status"],
        "other_source_status":
            triage_row["answer_points"][ap_idx]["other_source_status"],
        "language_mismatch":
            triage_row["answer_points"][ap_idx]["language_mismatch"],
        "n_candidates": len(candidate_rows),
        "n_self_contained": n_self,
        "semantic_quality_insufficient": n_self == 0,
        "exact_same_source_support":
            any(r["coverage"] >= COVERAGE_EXACT for r in candidate_rows),
        "candidate_refs": refs,
    }
    return analysis, candidate_rows


# ── 推荐动作 ──────────────────────────────────────────────────────────

def _recommend(category: str, sub_type: str,
               analyses: list[dict]) -> tuple[str, list[int]]:
    """按类别规则给出默认推荐动作与移除目标（不自动应用）。"""
    n_points = len(analyses)
    any_sc = any(a["n_self_contained"] > 0 for a in analyses)
    none_in_ev = [i for i, a in enumerate(analyses)
                  if a["in_evidence"] == "none"]
    exact_anywhere = [i for i, a in enumerate(analyses)
                      if a["exact_same_source_support"]]
    if category == CAT1:
        # 答案点逐字在 evidence 中但模型语义拒绝：优先自包含完整句
        if any_sc:
            return "replace_answer_point_with_self_contained_exact_raw_text", []
        if n_points == 1:
            return "retire_case", [0]
        return "remove_semantically_insufficient_answer_point", [
            i for i, a in enumerate(analyses) if a["n_self_contained"] == 0]
    if category == CAT4:
        if len(exact_anywhere) == n_points:
            return "expand_same_source_evidence_scope", []
        if len(none_in_ev) == n_points:
            return "retire_case", none_in_ev
        if none_in_ev:
            return "remove_unsupported_answer_point", none_in_ev
        return "retire_case", list(range(n_points))
    if category == CAT2:
        if sub_type == "language_mismatch":
            # 翻译等价不能自动判定 → 需所有者策略
            return "owner_approved_translation_equivalence_policy", []
        if exact_anywhere:
            return "replace_with_exact_source_language_text", []
        if len(none_in_ev) == n_points:
            return "retire_case", none_in_ev
        if none_in_ev:
            return "remove_unsupported_answer_point", none_in_ev
        return "retire_case", list(range(n_points))
    if category == CAT5:
        return "retire_case", list(range(n_points))
    # CAT8：模型输出与自身评估矛盾 → 定向盲审，不自动改 confirmed
    return "targeted_blind_re_review", []


def _removal_zero_risk(action: str, targets: list[int],
                       n_points: int) -> bool:
    if action == "retire_case":
        return True
    if action in ("remove_unsupported_answer_point",
                  "remove_semantically_insufficient_answer_point"):
        return len(targets) == n_points
    return False


def _contract_proof(case_id: str, triage_row: dict, draft_row: dict,
                    analyses: list[dict]) -> dict | None:
    """mixed-027 本地契约证明：模型评估与决策矛盾的事实并列。"""
    if triage_row["category"] != CAT8:
        return None
    n_evidence = len(triage_row["evidence_summary"])
    assessments = triage_row.get("answer_point_assessments") or []
    return {
        "case_id": case_id,
        "decision": triage_row["review_decision"],
        "refusal_assessment": triage_row["refusal_assessment"],
        "should_refuse": draft_row.get("should_refuse") is True,
        "answer_point_assessments": [
            {"answer_point_index": a.get("answer_point_index"),
             "assessment": a.get("assessment"),
             "evidence_refs": a.get("evidence_refs") or [],
             "evidence_refs_valid": all(
                 isinstance(r, int) and 0 <= r < n_evidence
                 for r in (a.get("evidence_refs") or []))}
            for a in assessments],
        "local_verbatim_facts": {
            str(a["answer_point_index"]): {
                "in_evidence": a["in_evidence"],
                "same_source_status": a["same_source_status"],
                "n_self_contained": a["n_self_contained"]}
            for a in analyses},
        "contradiction": (
            "全部答案点的模型 assessment 均为 directly_supported / "
            "faithful_paraphrase 却 decision=reject；审阅契约以证据支持为"
            "确认基础（confirmed 要求全部 supported 且 evidence_refs 非空、"
            "unsupported 不得 confirmed），模型自身评估与最终决策构成内部"
            "语义矛盾。本地逐字事实与模型评估并列记录，不作为确认依据。"),
        "review_contract": (
            "decision ∈ {confirmed, reject, needs_followup}；可答题 "
            "refusal_assessment 必须 not_applicable；confirmed 要求全部答案点"
            "supported 且引用非空；契约未强制“全部 supported 必须 confirmed”，"
            "故本矛盾属于模型语义不一致而非 schema 违规。"),
    }


# ── 组装 ──────────────────────────────────────────────────────────────

def _build_pack(checks: dict) -> tuple[list[dict], list[dict]]:
    """22 条决策行 + 全部候选行（确定性排序）。"""
    norm_cache: dict[str, tuple[str, list[int]]] = {}
    rows: list[dict] = []
    candidate_rows: list[dict] = []
    for cid in checks["reject_ids"]:
        triage_row = checks["triage_rows_by_id"][cid]
        draft_row = checks["draft_by_id"][cid]
        analyses: list[dict] = []
        case_cands: list[dict] = []
        for i, ap in enumerate(
                draft_row.get("acceptable_answer_points") or []):
            analysis, cands = _search_candidates(
                cid, i, ap, triage_row, draft_row, checks, norm_cache)
            analyses.append(analysis)
            case_cands.extend(cands)
        action, targets = _recommend(triage_row["category"],
                                     triage_row.get("sub_type", ""),
                                     analyses)
        n_points = len(analyses)
        proof = _contract_proof(cid, triage_row, draft_row, analyses)
        row = {
            "case_id": cid,
            "category": triage_row["category"],
            "sub_type": triage_row.get("sub_type", ""),
            "language": draft_row.get("language", ""),
            "query_type": draft_row.get("query_type", ""),
            "query": draft_row.get("query", ""),
            "touched_by_v205_v206": triage_row["touched_by_v205_v206"],
            "review_decision": triage_row["review_decision"],
            "review_rationale": triage_row["review_rationale"],
            "refusal_assessment": triage_row.get("refusal_assessment"),
            "answer_point_assessments":
                triage_row.get("answer_point_assessments") or [],
            "current_answer_points": list(
                draft_row.get("acceptable_answer_points") or []),
            "current_evidence": [
                {"chunk_id": e["chunk_id"], "source_id": e["source_id"],
                 "raw_chunk_char_range": dict(e["raw_chunk_char_range"]),
                 "raw_evidence_span": e["raw_evidence_span"],
                 "snippet": e["snippet"]}
                for e in triage_row["evidence_summary"]],
            "answer_point_analysis": analyses,
            "evidence_chunk_ids": sorted(
                {e["chunk_id"] for e in triage_row["evidence_summary"]}),
            "relevant_chunk_ids": sorted(
                draft_row.get("relevant_chunk_ids") or []),
            "recommended_action": action,
            "recommended_batch": ACTIONS_TO_BATCHES[action],
            "owner_options": list(OPTIONS_BY_CATEGORY[triage_row["category"]]),
            "removal_targets": list(targets),
            "removal_zero_risk": _removal_zero_risk(action, targets, n_points),
            "zero_answer_point_risk": triage_row["zero_answer_point_risk"],
            "zero_answer_point_risk_reason":
                triage_row["zero_answer_point_risk_reason"],
            "semantic_quality_insufficient": any(
                a["semantic_quality_insufficient"] for a in analyses),
            "contract_proof": proof,
        }
        rows.append(row)
        candidate_rows.extend(case_cands)
    candidate_rows.sort(key=lambda r: (
        r["case_id"], r["answer_point_index"], r["source_id"], r["chunk_id"],
        r["raw_chunk_char_range"]["start"]))
    return rows, candidate_rows


def _build_summary(rows: list[dict], candidate_rows: list[dict]) -> dict:
    by_batch: dict[str, list[str]] = {}
    by_action: dict[str, list[str]] = {}
    for r in rows:
        by_batch.setdefault(r["recommended_batch"], []).append(r["case_id"])
        by_action.setdefault(r["recommended_action"], []).append(r["case_id"])
    return {
        "n_rejects": len(rows),
        "by_batch": {b: {"n": len(ids), "case_ids": sorted(ids)}
                     for b, ids in sorted(by_batch.items())},
        "by_category": dict(sorted(Counter(
            r["category"] for r in rows).items())),
        "by_recommended_action": {a: sorted(ids)
                                  for a, ids in sorted(by_action.items())},
        "semantic_quality_insufficient_cases": sorted(
            r["case_id"] for r in rows if r["semantic_quality_insufficient"]),
        "removal_zero_risk_cases": sorted(
            r["case_id"] for r in rows if r["removal_zero_risk"]),
        "n_candidate_rows": len(candidate_rows),
        "n_self_contained_candidates": sum(
            1 for c in candidate_rows if c["self_contained"]),
        "overlay_generated": False,
        "v2_1_entry": "BLOCKED",
        "deterministic": True,
        "run_at": TIMESTAMP,
        "created_by": "corpus_v2_v207_reject_semantic_quality_decision_pack.py",
    }


def _owner_template(rows: list[dict]) -> list[dict]:
    """owner 批量决策模板：决策行完整只读事实 + 三空字段（不可填值）。"""
    template = []
    for r in rows:
        row = dict(r)
        for key in OWNER_TEMPLATE_KEYS:
            row[key] = ""
        template.append(row)
    return template


def _data_quality_report(checks: dict, rows: list[dict],
                         candidate_rows: list[dict]) -> dict:
    chunks = checks["chunks"]
    draft_by_id = checks["draft_by_id"]
    n_sc = sum(1 for c in candidate_rows if c["self_contained"])
    return {
        "skill_note": SKILL_NOTE,
        "skill": checks["data_quality"]["skill"],
        "equivalent_deterministic_checks": {
            "completeness": {
                "pack_rows": len(rows),
                "candidate_rows": len(candidate_rows),
                "triage_rows": checks["triage_rows"],
                "evidence_rows": checks["evidence_count"],
                "draft_rows": checks["case_count"],
                "refusal_cases": len(checks["refusal_ids"])},
            "uniqueness": {
                "pack_case_ids_unique":
                    len({r["case_id"] for r in rows}) == len(rows),
                "candidate_keys_unique": len({
                    (c["case_id"], c["answer_point_index"], c["chunk_id"],
                     c["raw_chunk_char_range"]["start"],
                     c["raw_chunk_char_range"]["end"])
                    for c in candidate_rows}) == len(candidate_rows),
                "triage_case_ids_unique": True},
            "referential_integrity": {
                "candidate_chunks_in_corpus": all(
                    c["chunk_id"] in chunks for c in candidate_rows),
                "candidate_sources_in_declared": True,
                "evidence_chunks_in_corpus": all(
                    e["chunk_id"] in chunks for row in rows
                    for e in row["current_evidence"])},
            "continuity": {
                "candidates_raw_proved": sum(
                    chunks[c["chunk_id"]]["text"][
                        c["raw_chunk_char_range"]["start"]:
                        c["raw_chunk_char_range"]["end"]] == c["raw_span"]
                    for c in candidate_rows),
                "self_contained_candidates": n_sc,
                "coverage_ge_075_all_candidates": all(
                    c["coverage"] >= COVERAGE_EXACT for c in candidate_rows),
                "triage_inputs_unchanged": checks["inputs_unchanged"]},
            "consistency": {
                "input_shas_unchanged": checks["inputs_unchanged"],
                "distribution_exact":
                    checks["distribution"] == EXPECTED_DISTRIBUTION,
                "batch_mapping_consistent": all(
                    r["recommended_batch"] == ACTIONS_TO_BATCHES[
                        r["recommended_action"]] for r in rows),
                "template_owner_fields_empty": True},
        },
    }


def _build_guide(summary: dict) -> str:
    rows_md = "\n".join(
        f"| {b} | {v['n']} | {', '.join(v['case_ids'])} |"
        for b, v in summary["by_batch"].items())
    actions_md = "\n".join(
        f"- `{a}` → `{b}`" for a, b in ACTIONS_TO_BATCHES.items())
    lines = [
        "# OWNER_SEMANTIC_QUALITY_DECISION_GUIDE.md — v2.0.7 语义质量闭环决策指南", "",
        "## 这是什么", "",
        "本决策包基于 v2.0.7 盲态自动审阅（LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_7）"
        "的 22 条 reject 与 reject-triage 根因分流，为**所有者**提供批量决策的"
        "只读依据。本决策包**不会自动应用任何动作**：所有推荐动作与批次仅是"
        "建议，必须由所有者填写 `owner_decision` / `owner_reviewer` / "
        "`owner_notes` 后，在另行授权的修复步骤中执行。", "",
        "本决策包不是修复、不是人工审核、不是 overlay、不是 v2.1 准入；"
        "未调用 LLM/API、未联网；未生成 active metadata / split。", "",
        "## 输入门禁（fail-closed，全部通过）", "",
        "- reject 集合恰 22 条；triage 集合 == reject 集合",
        "- triage 类别分布恰好 8 / 5 / 6 / 2 / 1",
        "- candidate 148 条；strict raw-codepoint-v1 evidence 161/161；无 overlay",
        "- review / candidate / triage manifest 自哈希与 SHA 链全部一致", "",
        "## 五批次建议（不自动应用）", "",
        "| 批次 | 条数 | case_id |",
        "|---|---|---|",
        rows_md, "",
        "## 推荐动作词表", "",
        actions_md, "",
        "## 各类别决策规则（默认推荐依据）", "",
        f"1. `{CAT1}`（8 条）：不能把逐字 token 命中自动视为高质量真值。"
        "找到同 source 自包含完整 clause/sentence → 推荐 "
        "`replace_answer_point_with_self_contained_exact_raw_text`；"
        "仅孤立 token/标题/短标签 → `remove_semantically_insufficient_"
        "answer_point`，若零答案点则 `retire_case`。不提供放宽 review 标准"
        "作为默认动作。",
        f"2. `{CAT4}`（6 条）：逐条列出唯一、连续、同 source 的 scope "
        "expansion evidence；能完整支撑当前答案点 → "
        "`expand_same_source_evidence_scope`；只能部分支撑 → "
        "收窄/删除/退役选项，不假装充分。",
        f"3. `{CAT2}`（5 条）：区分中文答案点 + 英文来源的 "
        "translation-equivalence 情况；提供五个选项，翻译等价**不自动判为 "
        "confirmed**。",
        f"4. `{CAT5}`（2 条）：仅 `retire_case` / `keep_unresolved`。",
        f"5. `{CAT8}`（1 条，mixed-027）：输出本地契约证明；仅 "
        "`targeted_blind_re_review` / `keep_unresolved`；不因“模型似乎矛盾”"
        "自动改为 confirmed。", "",
        "## 候选与标记", "",
        "- `self-contained-raw-candidates.jsonl`：全部候选均满足 "
        "`chunk_text[start:end] == raw_span`，`coverage >= 0.75`；"
        "partial / paraphrase 不会被写成 exact。",
        "- `scope_expansion_required=true`：候选不在当前 evidence span 内，"
        "作为证据需扩展 scope；候选 source/chunk 不会跨越声明范围而不标记。",
        "- `semantic_quality_insufficient=true`：答案点仅由孤立 token / 标题 / "
        "短标签支撑（无自包含完整句/段候选）。",
        "- `removal_zero_risk=true`：推荐移除/退役会清空全部答案点。", "",
        "## 模板填写", "",
        "`owner-batch-decision-template.jsonl` 每行含 `recommended_action`，"
        "但 `owner_decision` / `owner_reviewer` / `owner_notes` 必须由所有者"
        "填写：",
        "- `owner_decision`：接受 / 拒绝 / 修改推荐动作（从该行 "
        "`owner_options` 中选择）；",
        "- `owner_reviewer`：决策人标识；",
        "- `owner_notes`：决策理由。", "",
        "## 后续步骤", "",
        "所有者完成批量决策后，需另行授权一个确定性修复/重审步骤（本决策包"
        "不做任何修改）。",
    ]
    return "\n".join(lines) + "\n"


def _build_report(rows: list[dict], candidate_rows: list[dict],
                  summary: dict, dq: dict, shas: dict) -> str:
    lines = [
        "# v2.0.7 reject semantic-quality closure decision pack（所有者决策包）", "",
        "> **本任务是只读决策包，不是修复**：不修改 candidate draft/evidence/"
        "chunks/review/triage，不调用 LLM/API、不联网、不生成 overlay / active "
        "metadata / split / v2.1 文件；推荐动作全部不自动应用。",
        "> 唯一事实来源：`automated-review.jsonl`（canonical，"
        f"confirmed={shas['counts']['confirmed']} / "
        f"reject={shas['counts']['reject']} / "
        f"needs_followup={shas['counts']['needs_followup']}）与 "
        "`reject-triage/review-reject-triage.jsonl`（22 条根因分流）。",
        "> 模型 rationale 与 assessment 原样记录、不作为事实；每条推荐均对照"
        "同 source raw 文本可重建性。", "",
        "## 批次总览", "",
        "| 批次 | 条数 | case_id |",
        "|---|---|---|",
    ]
    for batch in BATCHES:
        info = summary["by_batch"].get(batch)
        if not info:
            continue
        lines.append(f"| {batch} | {info['n']} | "
                     f"{', '.join(info['case_ids'])} |")
    lines += [
        "",
        f"- 候选行：{summary['n_candidate_rows']}（自包含完整句/段 "
        f"{summary['n_self_contained_candidates']}）",
        f"- 零答案点风险（移除后归零）："
        f"{', '.join(summary['removal_zero_risk_cases'])}",
        f"- semantic_quality_insufficient："
        f"{', '.join(summary['semantic_quality_insufficient_cases'])}",
        "- 未生成 overlay；gate 保持 BLOCKED；未进入 v2.1。",
    ]

    cand_by_case: dict[str, list[dict]] = {}
    for c in candidate_rows:
        cand_by_case.setdefault(c["case_id"], []).append(c)

    lines += ["", "## 22 条逐条决策", ""]
    for r in rows:
        lines += [
            f"### {r['case_id']} — {r['category']}",
            f"（sub_type={r['sub_type'] or '-'}；推荐 "
            f"`{r['recommended_action']}` → `{r['recommended_batch']}`）", "",
            f"- query：{r['query']}",
            f"- 模型 decision：`{r['review_decision']}`；"
            f"refusal_assessment：`{r['refusal_assessment']}`",
            f"- 模型 rationale：{r['review_rationale']}",
            f"- 模型 assessment：{json.dumps(r['answer_point_assessments'], ensure_ascii=False)}",
            f"- 当前答案点：{json.dumps(r['current_answer_points'], ensure_ascii=False)}",
            f"- 零答案点风险（triage）：{r['zero_answer_point_risk']}；"
            f"移除归零：{r['removal_zero_risk']}；"
            f"semantic_quality_insufficient：{r['semantic_quality_insufficient']}",
            "- 当前 raw evidence：",
        ]
        for e in r["current_evidence"]:
            lines.append(f"  - {e['chunk_id']} "
                         f"[{e['raw_chunk_char_range']['start']}:"
                         f"{e['raw_chunk_char_range']['end']}) "
                         f"`{e['raw_evidence_span'][:80]}`")
        for ap in r["answer_point_analysis"]:
            lines.append(
                f"  - 答案点 {ap['answer_point_index']} "
                f"`{ap['answer_point'][:50]}`：in_evidence="
                f"{ap['in_evidence']}，same_source={ap['same_source_status']}，"
                f"language_mismatch={ap['language_mismatch']}，"
                f"候选 {ap['n_candidates']}（自包含 {ap['n_self_contained']}），"
                f"semantic_quality_insufficient="
                f"{ap['semantic_quality_insufficient']}")
        sc = [c for c in cand_by_case.get(r["case_id"], [])
              if c["self_contained"]]
        if sc:
            lines.append("  - 自包含完整句/段候选：")
            for c in sc[:4]:
                lines.append(
                    f"    - {c['chunk_id']} "
                    f"[{c['raw_chunk_char_range']['start']}:"
                    f"{c['raw_chunk_char_range']['end']}) "
                    f"`{c['candidate_type']}` unique={c['unique']} "
                    f"scope_expansion_required="
                    f"{c['scope_expansion_required']} "
                    f"`{c['raw_span'][:60]}`")
        lines.append(
            f"- 推荐动作：`{r['recommended_action']}`；移除目标："
            f"{r['removal_targets']}；所有者可选：{r['owner_options']}")
        if r["contract_proof"]:
            lines.append(
                f"- 本地契约证明：{json.dumps(r['contract_proof'], ensure_ascii=False)}")
        lines.append("")

    lines += ["", "## 数据质量（等价确定性检查）", "",
              f"- {dq['skill_note']}",
              f"- 候选 raw span 可重建："
              f"{dq['equivalent_deterministic_checks']['continuity']['candidates_raw_proved']}"
              f" / {dq['equivalent_deterministic_checks']['completeness']['candidate_rows']}",
              "", "## SHA 链", "",
              f"- canonical：`{shas['canonical']}`",
              f"- issues：`{shas['issues']}`",
              f"- triage：`{shas['triage']}`",
              f"- triage manifest：`{shas['triage_manifest']}`",
              f"- candidate manifest：`{shas['candidate_manifest']}`",
              f"- draft-after：`{shas['draft_after']}`",
              f"- evidence-after：`{shas['evidence_after']}`", "",
              "## 声明", "",
              "- 未调用任何 LLM/API，未联网；未修改任何输入数据",
              "- 推荐动作与五批次仅为建议，绝不自动应用",
              "- 未生成 overlay / active metadata / split / v2.1 产物",
              "- 未读取历史审阅结论、split/dev/holdout、锁配置或评测结果",
              "- 未 stage / commit / push",
    ]
    return "\n".join(lines) + "\n"


# ── 主流程 ────────────────────────────────────────────────────────────

def run(*, review_dir: Path = REVIEW_DIR, candidate_dir: Path = CANDIDATE_DIR,
        triage_dir: Path = TRIAGE_DIR, out_dir: Path | None = None,
        draft: Path = DRAFT, chunks_path: Path = CHUNKS,
        chunk_manifest: Path = CHUNK_MANIFEST) -> dict:
    """生成 22 条 reject 的语义质量闭环决策包。

    fail-closed：门禁任一漂移 → DecisionPackError，零输出（不留半成品目录）。
    """
    out_dir = out_dir or DEFAULT_OUT
    checks = preflight(review_dir=review_dir, candidate_dir=candidate_dir,
                       triage_dir=triage_dir, draft=draft,
                       chunks_path=chunks_path, chunk_manifest=chunk_manifest)
    rows, candidate_rows = _build_pack(checks)
    summary = _build_summary(rows, candidate_rows)
    template = _owner_template(rows)
    dq = _data_quality_report(checks, rows, candidate_rows)
    shas = {
        "canonical": _sha256_file(review_dir / "automated-review.jsonl"),
        "issues": _sha256_file(review_dir / "automated-review-issues.jsonl"),
        "triage": _sha256_file(triage_dir / "review-reject-triage.jsonl"),
        "triage_manifest": _sha256_file(triage_dir / "manifest.json"),
        "candidate_manifest": _sha256_file(candidate_dir / "manifest.json"),
        "draft_after": _sha256_file(candidate_dir / "draft-after.jsonl"),
        "evidence_after": _sha256_file(candidate_dir / "evidence-after.jsonl"),
        "counts": {"confirmed": checks["confirmed"],
                   "reject": checks["reject"],
                   "needs_followup": checks["needs_followup"]},
    }
    report = _build_report(rows, candidate_rows, summary, dq, shas)
    guide = _build_guide(summary)

    files = {
        "semantic-quality-decision-pack.jsonl":
            "".join(_line(r) + "\n" for r in rows),
        "self-contained-raw-candidates.jsonl":
            "".join(_line(c) + "\n" for c in candidate_rows),
        "owner-batch-decision-template.jsonl":
            "".join(_line(r) + "\n" for r in template),
        "OWNER_SEMANTIC_QUALITY_DECISION_GUIDE.md": guide,
        "decision-pack-summary.json": _dump(summary),
        "decision-pack-report.md": report,
        "data-quality-report.json": _dump(dq),
    }

    # 原子目录替换：staging 全部成功后才替换 out_dir；失败清理
    if out_dir.exists():
        shutil.rmtree(out_dir)
    staging = Path(tempfile.mkdtemp(prefix=".v207-decpack-",
                                    dir=out_dir.parent))
    try:
        for name, content in files.items():
            _atomic_write(staging / name, content)
        outputs_sha = {name: _sha256_file(staging / name) for name in files}
        input_paths = {
            "automated-review.jsonl": review_dir / "automated-review.jsonl",
            "automated-review-issues.jsonl":
                review_dir / "automated-review-issues.jsonl",
            "automated-review-evidence.jsonl":
                review_dir / "automated-review-evidence.jsonl",
            "automated-review-pack.jsonl":
                review_dir / "automated-review-pack.jsonl",
            "review-manifest.json": review_dir / "manifest.json",
            "candidate-manifest.json": candidate_dir / "manifest.json",
            "draft-after.jsonl": candidate_dir / "draft-after.jsonl",
            "evidence-after.jsonl": candidate_dir / "evidence-after.jsonl",
            "draft": draft, "chunks": chunks_path,
            "chunk-manifest": chunk_manifest,
            "triage-review-reject-triage.jsonl":
                triage_dir / "review-reject-triage.jsonl",
            "triage-candidate-evidence-spans.jsonl":
                triage_dir / "candidate-evidence-spans.jsonl",
            "triage-summary.json":
                triage_dir / "review-reject-triage-summary.json",
            "triage-owner-template.jsonl":
                triage_dir / "owner-decision-template.jsonl",
            "triage-report.md": triage_dir / "review-reject-triage-report.md",
            "triage-data-quality-report.json":
                triage_dir / "data-quality-report.json",
            "triage-manifest.json": triage_dir / "manifest.json",
        }
        validation = {
            "reject_set_exact": True,
            "triage_set_matches_rejects": True,
            "distribution_exact": True,
            "strict_validator_161_161": True,
            "overlay_absent": True,
            "sha_chain": True,
            "triage_manifest_ok": True,
        }
        manifest = _manifest({
            "task": "v2.0.7-reject-semantic-quality-decision-pack",
            "description": "v2.0.7 automated-review 22 条 reject 的语义质量"
                           "闭环决策包（只读、离线、无 LLM/API；推荐动作"
                           "不自动应用）",
            "rule_version": RULE_VERSION,
            "llm": None,
            "skill_note": SKILL_NOTE,
            "constants": {
                "min_span_len": MIN_SPAN_LEN,
                "coverage_exact": COVERAGE_EXACT,
                "cjk_threshold": CJK_THRESHOLD,
                "cjk_source_threshold": CJK_SOURCE_THRESHOLD,
                "max_candidates_per_chunk": MAX_CANDIDATES_PER_CHUNK,
                "max_candidates_per_ap": MAX_CANDIDATES_PER_AP,
                "expected_distribution": EXPECTED_DISTRIBUTION,
            },
            "gate_verdict": "DECISION_PACK_OK",
            "n_rejects": len(rows),
            "inputs": {name: _sha256_file(path)
                       for name, path in sorted(input_paths.items())},
            "outputs": outputs_sha,
            "validation": validation,
            "summary_ref": {
                "by_batch": summary["by_batch"],
                "removal_zero_risk_cases":
                    summary["removal_zero_risk_cases"],
                "semantic_quality_insufficient_cases":
                    summary["semantic_quality_insufficient_cases"],
                "n_candidate_rows": summary["n_candidate_rows"],
                "n_self_contained_candidates":
                    summary["n_self_contained_candidates"],
            },
            "declarations": {
                "llm_called": False, "network_used": False,
                "overlay_generated": False, "data_modified": False,
                "v2_1_entered": False, "split_created": False,
                "historical_verdicts_read": False,
            },
            "forbidden_outputs": [
                "overlay", "active metadata", "v2.1 pointer", "split reuse",
                "locked config", "evaluation results", "draft-after",
                "evidence-after"],
            "deterministic": True,
            "run_at": TIMESTAMP,
            "created_by":
                "corpus_v2_v207_reject_semantic_quality_decision_pack.py",
        })
        _atomic_write(staging / "manifest.json", _dump(manifest))
        os.replace(staging, out_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        raise
    return {"rows": rows, "candidates": candidate_rows, "summary": summary,
            "template": template, "data_quality": dq, "manifest": manifest,
            "out_dir": str(out_dir)}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    review_dir = REVIEW_DIR
    candidate_dir = CANDIDATE_DIR
    triage_dir = TRIAGE_DIR
    out_dir = DEFAULT_OUT
    if "--review-dir" in argv:
        i = argv.index("--review-dir")
        review_dir = Path(argv[i + 1])
        del argv[i:i + 2]
    if "--candidate-dir" in argv:
        i = argv.index("--candidate-dir")
        candidate_dir = Path(argv[i + 1])
        del argv[i:i + 2]
    if "--triage-dir" in argv:
        i = argv.index("--triage-dir")
        triage_dir = Path(argv[i + 1])
        del argv[i:i + 2]
    if "--out-dir" in argv:
        i = argv.index("--out-dir")
        out_dir = Path(argv[i + 1])
        del argv[i:i + 2]
    try:
        result = run(review_dir=review_dir, candidate_dir=candidate_dir,
                     triage_dir=triage_dir, out_dir=out_dir)
    except DecisionPackError as exc:
        print(f"decision pack failed closed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"n_rejects": len(result["rows"])},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
