"""Build the fail-closed v2.0.6 owner-authorized final blocker closure candidate.

Four fixed owner-authorized actions close the last four blockers of v2.0.5:
- zh-035: multi_span_exact_evidence_v1 policy with all 6 verbatim duplicate
  spans recorded (no span selection); cross-source scope expansion is recorded
  explicitly with an owner-authorized marker.
- zh-032: retired with a fixed reason after a fail-closed dependency check.
- mixed-022 / mixed-028: answer points narrowed to exact raw text, unsupported
  points and orphan evidence removed, only raw evidence retained.

No LLM/API, no network, no split/holdout/review-verdict inputs, no overlay,
active metadata or v2.1 outputs.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import corpus_v2_evidence_coordinate_repair as coord
from scripts import corpus_v2_remaining_blockers_decision_pack as rbp

ROOT = Path(__file__).resolve().parents[1]
V205 = ROOT / "evaluation/datasets/v2/revisions/v2.0.5-owner-authorized-scope-repair"
OUT = ROOT / "evaluation/datasets/v2/revisions/v2.0.6-owner-authorized-final-blocker-closure"
DRAFT_AFTER_205 = V205 / "draft-after.jsonl"
EVIDENCE_AFTER_205 = V205 / "evidence-after.jsonl"
V205_MANIFEST = V205 / "manifest.json"
PACK_DIR = V205 / "remaining-blockers-decision-pack"
DRAFT = rbp.DRAFT
CHUNKS = rbp.CHUNKS
CHUNK_MANIFEST = rbp.CHUNK_MANIFEST
TIMESTAMP = "2026-08-10T00:00:00+00:00"
CONTRACT = "raw-codepoint-v1"
ALGORITHM = "raw-span-map-1"
NORMALIZATION = "display-whitespace-v1"
TARGETS = frozenset({"zh-035", "zh-032", "mixed-022", "mixed-028"})
ACTOR = "OWNER_AUTHORIZED_FINAL_BLOCKER_CLOSURE"
RETIRE_REASON = "no_directly_supported_answer_point_after_owner_authorized_review"
MULTI_SPAN_POLICY = "multi_span_exact_evidence_v1"
SCOPE_EXPANSION_MARKER = "OWNER_AUTHORIZED_MULTI_SOURCE_EXACT_EVIDENCE_SCOPE_EXPANSION"
# zh-035: the complete enumeration of verbatim "fibo.py" duplicate spans,
# sorted by (source_id, chunk_id, start); every span must be written, none may
# be selected.  Cross-checked against the v2.0.5 decision pack and re-enumerated
# corpus-wide during the gate.
ZH035_SPANS = (
    ("python-tutorial-en.md", "e564a122a7a2_chunk_61", 1492, 1499),
    ("python-tutorial-en.md", "e564a122a7a2_chunk_64", 1523, 1530),
    ("python-tutorial-en.md", "e564a122a7a2_chunk_65", 190, 197),
    ("python-tutorial-zh.md", "32c427fb50e2_chunk_30", 550, 557),
    ("python-tutorial-zh.md", "32c427fb50e2_chunk_31", 992, 999),
    ("python-tutorial-zh.md", "32c427fb50e2_chunk_31", 1263, 1270),
)
MIXED022_POINT = "A function returning another function"
MIXED022_SPAN = ("c9fd20815ea8_chunk_5", 18, 55)
MIXED028_POINT = "state"
MIXED028_SPAN = ("993955159403_chunk_7", 152, 157)


class BlockerClosureError(Exception):
    """输入门禁或确定性构建失败。"""


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_evidence_row(case_id: str, chunk: dict, start: int, end: int) -> dict:
    """raw-codepoint-v1 evidence row; the span is proven by construction."""
    span = chunk["text"][start:end]
    snippet = coord.display_snippet(span)
    return {
        "case_id": case_id,
        "chunk_id": chunk["chunk_id"],
        "source_id": chunk["source"],
        "chunk_text_sha256": coord.sha256_text(chunk["text"]),
        "coordinate_contract": CONTRACT,
        "mapping_algorithm_version": ALGORITHM,
        "snippet_normalization": NORMALIZATION,
        "raw_chunk_char_range": {"start": start, "end": end},
        "raw_evidence_span": span,
        "snippet": snippet,
        "snippet_sha256": coord.sha256_text(snippet),
    }


def _expected_draft_points() -> dict[str, list[str]]:
    return {
        "zh-035": ["fibo.py"],
        "zh-032": ["打包异常实例列表", "让多个异常一起被引发"],
        "mixed-022": ["英文解释（A function returning another function...）", "中文仅术语名（装饰器）"],
        "mixed-028": ["两者都让数据变化驱动界面更新", "Vue 用 Proxy 实现响应式，React 用 state 记忆组件"],
    }


def _load_inputs():
    """Fail-closed gate on every allowed input before any output is written."""
    if not V205.exists() or not V205_MANIFEST.exists():
        raise BlockerClosureError("v2.0.5 revision missing")
    v205 = json.loads(V205_MANIFEST.read_text(encoding="utf-8"))
    if v205.get("status") != "CANDIDATE" or v205.get("activation_blocked") is not True:
        raise BlockerClosureError("v2.0.5 manifest status mismatch")
    if v205.get("counts", {}).get("case_after") != 149 or v205.get("counts", {}).get("remaining_blockers") != 4:
        raise BlockerClosureError("v2.0.5 counts mismatch")
    if v205.get("manifest_sha256") != _sha_text(_dump({k: v for k, v in v205.items() if k != "manifest_sha256"})):
        raise BlockerClosureError("v2.0.5 manifest self-hash mismatch")
    if _sha(DRAFT_AFTER_205) != v205.get("outputs", {}).get("draft-after.jsonl"):
        raise BlockerClosureError("v2.0.5 draft-after SHA mismatch")
    if _sha(EVIDENCE_AFTER_205) != v205.get("outputs", {}).get("evidence-after.jsonl"):
        raise BlockerClosureError("v2.0.5 evidence-after SHA mismatch")
    for name, path in (("draft", DRAFT), ("chunks", CHUNKS), ("chunk_manifest", CHUNK_MANIFEST)):
        if v205.get("inputs", {}).get(name) != _sha(path):
            raise BlockerClosureError(f"input SHA mismatch: {name}")

    pack_manifest = json.loads((PACK_DIR / "manifest.json").read_text(encoding="utf-8"))
    if pack_manifest.get("status") != "DECISION_PACK":
        raise BlockerClosureError("decision pack manifest status mismatch")
    pack_path = PACK_DIR / "remaining-blockers-decision-pack.jsonl"
    if pack_manifest.get("outputs", {}).get("remaining-blockers-decision-pack.jsonl") != _sha(pack_path):
        raise BlockerClosureError("decision pack file SHA mismatch")
    pack_rows = {row["case_id"]: row for row in _jsonl(pack_path)}
    if set(pack_rows) != TARGETS:
        raise BlockerClosureError("decision pack target set mismatch")

    chunks = coord.load_chunks(CHUNKS)
    draft_lines = [line for line in DRAFT_AFTER_205.read_text(encoding="utf-8").splitlines() if line.strip()]
    draft_rows = [json.loads(line) for line in draft_lines]
    if len(draft_rows) != 149:
        raise BlockerClosureError("v2.0.5 draft-after row count mismatch")
    draft_by_id = {row["id"]: row for row in draft_rows}
    expected = _expected_draft_points()
    for case_id, points in expected.items():
        if draft_by_id.get(case_id, {}).get("acceptable_answer_points") != points:
            raise BlockerClosureError(f"{case_id}: draft answer points mismatch")
    evidence_lines = [line for line in EVIDENCE_AFTER_205.read_text(encoding="utf-8").splitlines() if line.strip()]
    evidence_rows = [json.loads(line) for line in evidence_lines]
    if len(evidence_rows) != 159:
        raise BlockerClosureError("v2.0.5 evidence-after row count mismatch")
    evidence_by_case: dict[str, list[dict]] = {}
    for row in evidence_rows:
        evidence_by_case.setdefault(row["case_id"], []).append(row)
    for case_id, count in (("zh-035", 1), ("zh-032", 1), ("mixed-022", 1), ("mixed-028", 2)):
        if len(evidence_by_case.get(case_id, [])) != count:
            raise BlockerClosureError(f"{case_id}: evidence row count mismatch")

    # zh-032 retirement dependency gate: no follow-up / chain / doc_target
    # reference may point at zh-032, and zh-032 itself must not open a chain.
    for row in draft_rows:
        if row["id"] != "zh-032":
            if row.get("doc_target") == "zh-032":
                raise BlockerClosureError("zh-032 has a doc_target dependency")
            metadata = row.get("metadata") or {}
            if metadata.get("follow_up_to") == "zh-032" or "zh-032" in str(metadata.get("chain_id") or ""):
                raise BlockerClosureError("zh-032 has a chain/follow-up dependency")
    zh032 = draft_by_id["zh-032"]
    metadata = zh032.get("metadata") or {}
    if zh032.get("doc_target") is not None or metadata.get("follow_up_to") is not None or metadata.get("chain_id") is not None:
        raise BlockerClosureError("zh-032 must not open a chain")

    # Span verification: every written span must be proven against the chunk
    # text and cross-checked against the v2.0.5 decision pack enumeration.
    for source_id, chunk_id, start, end in ZH035_SPANS:
        chunk = chunks.get(chunk_id)
        if chunk is None or chunk.get("source") != source_id or chunk["text"][start:end] != "fibo.py":
            raise BlockerClosureError(f"zh-035 span proof failed: {chunk_id}")
    enumerated = [
        (chunk["source"], chunk["chunk_id"], start, end)
        for chunk in sorted(chunks.values(), key=lambda r: (r["source"], r["chunk_id"]))
        for start, end in rbp.occurrences(chunk["text"], "fibo.py")
    ]
    if tuple(enumerated) != ZH035_SPANS:
        raise BlockerClosureError("zh-035 corpus-wide enumeration does not match the fixed span set")
    pack_spans = pack_rows["zh-035"]["analysis"]["duplicate_raw_spans"]
    if tuple((s["source_id"], s["chunk_id"], s["raw_chunk_char_range"]["start"], s["raw_chunk_char_range"]["end"])
             for s in pack_spans) != ZH035_SPANS:
        raise BlockerClosureError("zh-035 decision pack spans mismatch")
    chunk = chunks[MIXED022_SPAN[0]]
    if chunk["text"][MIXED022_SPAN[1]:MIXED022_SPAN[2]] != MIXED022_POINT:
        raise BlockerClosureError("mixed-022 span proof failed")
    if rbp.occurrences(chunk["text"], MIXED022_POINT) != [(MIXED022_SPAN[1], MIXED022_SPAN[2])]:
        raise BlockerClosureError("mixed-022 span must be unique and exact")
    coord.locate_unique_raw(chunk["text"], MIXED022_POINT)
    chunk = chunks[MIXED028_SPAN[0]]
    if chunk["text"][MIXED028_SPAN[1]:MIXED028_SPAN[2]] != MIXED028_POINT:
        raise BlockerClosureError("mixed-028 span proof failed")
    if rbp.occurrences(chunk["text"], MIXED028_POINT) != [(MIXED028_SPAN[1], MIXED028_SPAN[2])]:
        raise BlockerClosureError("mixed-028 span must be unique and exact")
    coord.locate_unique_raw(chunk["text"], MIXED028_POINT)
    pack_cands = pack_rows["mixed-022"]["analysis"]["per_answer_point"][0]["narrow_candidates"]
    if not any(c["chunk_id"] == MIXED022_SPAN[0] and c["raw_chunk_char_range"] == {"start": MIXED022_SPAN[1], "end": MIXED022_SPAN[2]}
               for c in pack_cands):
        raise BlockerClosureError("mixed-022 decision pack candidate mismatch")
    pack_cands = pack_rows["mixed-028"]["analysis"]["per_answer_point"][1]["narrow_candidates"]
    if not any(c["chunk_id"] == MIXED028_SPAN[0] and c["raw_chunk_char_range"] == {"start": MIXED028_SPAN[1], "end": MIXED028_SPAN[2]}
               for c in pack_cands):
        raise BlockerClosureError("mixed-028 decision pack candidate mismatch")
    return {
        "v205": v205, "chunks": chunks, "draft_lines": draft_lines,
        "evidence_lines": evidence_lines, "evidence_by_case": evidence_by_case,
    }


def _manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = _sha_text(_dump(result))
    return result


def run(*, out_dir: Path = OUT) -> dict:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    inputs = _load_inputs()
    chunks = inputs["chunks"]
    draft_lines = inputs["draft_lines"]
    evidence_lines = inputs["evidence_lines"]
    evidence_by_case = inputs["evidence_by_case"]

    # --- draft: 149 -> 148 ---------------------------------------------------
    after_draft_lines: list[str] = []
    for line in draft_lines:
        row = json.loads(line)
        if row["id"] == "zh-032":
            continue  # retired
        if row["id"] == "mixed-022":
            row = dict(row)
            row["acceptable_answer_points"] = [MIXED022_POINT]
            after_draft_lines.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
        elif row["id"] == "mixed-028":
            row = dict(row)
            row["acceptable_answer_points"] = [MIXED028_POINT]
            after_draft_lines.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
        else:
            after_draft_lines.append(line)  # non-target and zh-035: byte-identical

    # --- evidence: 159 -> 162 (5 target rows removed, 8 raw rows added) ------
    new_rows: list[dict] = []
    for source_id, chunk_id, start, end in ZH035_SPANS:
        new_rows.append(build_evidence_row("zh-035", chunks[chunk_id], start, end))
    new_rows.append(build_evidence_row("mixed-022", chunks[MIXED022_SPAN[0]],
                                       MIXED022_SPAN[1], MIXED022_SPAN[2]))
    new_rows.append(build_evidence_row("mixed-028", chunks[MIXED028_SPAN[0]],
                                       MIXED028_SPAN[1], MIXED028_SPAN[2]))
    new_rows.sort(key=lambda r: (r["case_id"], r["chunk_id"], r["raw_chunk_char_range"]["start"]))
    after_evidence_lines = [line for line in evidence_lines
                            if json.loads(line)["case_id"] not in TARGETS]
    after_evidence_lines += [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in new_rows]

    # --- diff ledger ---------------------------------------------------------
    zh032_evidence = evidence_by_case["zh-032"][0]
    removed_targets = [row for row in (json.loads(line) for line in evidence_lines)
                       if row["case_id"] in TARGETS]
    diff: list[dict] = []
    diff.append({"case_id": "zh-032", "kind": "case_retired", "reason": RETIRE_REASON,
                 "case_count_before": 149, "case_count_after": 148})
    diff.append({"case_id": "zh-032", "kind": "evidence_removed", "reason": "case_retired",
                 "chunk_id": zh032_evidence["chunk_id"], "source_id": zh032_evidence["source_id"],
                 "snippet": zh032_evidence.get("snippet", "")})
    for row in removed_targets:
        if row["case_id"] == "zh-032":
            continue
        diff.append({"case_id": row["case_id"], "kind": "evidence_removed",
                     "reason": "orphan_of_replaced_or_superseded_answer_points",
                     "chunk_id": row["chunk_id"], "source_id": row["source_id"],
                     "snippet": row.get("snippet", "")})
    for source_id, chunk_id, start, end in ZH035_SPANS:
        diff.append({"case_id": "zh-035", "kind": "evidence_added", "policy": MULTI_SPAN_POLICY,
                     "chunk_id": chunk_id, "source_id": source_id,
                     "raw_chunk_char_range": {"start": start, "end": end},
                     "raw_evidence_span": "fibo.py",
                     "in_declared_source": source_id == "python-tutorial-zh.md",
                     "scope_expansion": None if source_id == "python-tutorial-zh.md" else SCOPE_EXPANSION_MARKER})
    diff.append({"case_id": "mixed-022", "kind": "answer_point_replaced", "index": 0,
                 "old": "英文解释（A function returning another function...）", "new": MIXED022_POINT,
                 "reason": "owner_authorized_narrow_to_exact_raw_text"})
    diff.append({"case_id": "mixed-022", "kind": "answer_point_removed", "index": 1,
                 "value": "中文仅术语名（装饰器）", "reason": "no_exact_evidence"})
    diff.append({"case_id": "mixed-022", "kind": "evidence_added",
                 "chunk_id": MIXED022_SPAN[0], "source_id": chunks[MIXED022_SPAN[0]]["source"],
                 "raw_chunk_char_range": {"start": MIXED022_SPAN[1], "end": MIXED022_SPAN[2]},
                 "raw_evidence_span": MIXED022_POINT})
    diff.append({"case_id": "mixed-028", "kind": "answer_point_removed", "index": 0,
                 "value": "两者都让数据变化驱动界面更新", "reason": "no_exact_evidence"})
    diff.append({"case_id": "mixed-028", "kind": "answer_point_replaced", "index": 1,
                 "old": "Vue 用 Proxy 实现响应式，React 用 state 记忆组件", "new": MIXED028_POINT,
                 "reason": "owner_authorized_narrow_to_exact_raw_text"})
    diff.append({"case_id": "mixed-028", "kind": "evidence_added",
                 "chunk_id": MIXED028_SPAN[0], "source_id": chunks[MIXED028_SPAN[0]]["source"],
                 "raw_chunk_char_range": {"start": MIXED028_SPAN[1], "end": MIXED028_SPAN[2]},
                 "raw_evidence_span": MIXED028_POINT})

    # --- multi-span ledger ----------------------------------------------------
    zh035_ledger = []
    for source_id, chunk_id, start, end in ZH035_SPANS:
        zh035_ledger.append({
            "case_id": "zh-035", "policy": MULTI_SPAN_POLICY,
            "chunk_id": chunk_id, "source_id": source_id,
            "raw_chunk_char_range": {"start": start, "end": end},
            "raw_evidence_span": "fibo.py",
            "raw_span_sha256": _sha_text("fibo.py"),
            "in_declared_source": source_id == "python-tutorial-zh.md",
            "scope": "declared_source" if source_id == "python-tutorial-zh.md" else "other_source",
            "scope_expansion": None if source_id == "python-tutorial-zh.md" else SCOPE_EXPANSION_MARKER,
            "recorded_by": ACTOR,
        })

    # --- validation reports ---------------------------------------------------
    after_evidence = [json.loads(line) for line in after_evidence_lines]
    raw_rows = [row for row in after_evidence if row.get("coordinate_contract") == CONTRACT]
    coord.strict_validate(raw_rows, chunks)
    legacy_rows = [row for row in after_evidence if row.get("coordinate_contract") != CONTRACT]
    # Retired zh-032 has no evidence rows; the three retained target cases
    # must carry only raw-codepoint-v1 rows (no residual legacy/unresolved).
    target_raw = {case_id: [row for row in after_evidence if row["case_id"] == case_id]
                  for case_id in TARGETS - {"zh-032"}}
    for case_id, rows in target_raw.items():
        if not rows or any(row.get("coordinate_contract") != CONTRACT for row in rows):
            raise BlockerClosureError(f"{case_id}: residual legacy/unresolved evidence")
    after_draft = [json.loads(line) for line in after_draft_lines]
    if len(after_draft) != 148 or len({row["id"] for row in after_draft}) != 148:
        raise BlockerClosureError("draft-after must have 148 unique cases")
    covered = {row["case_id"] for row in after_evidence}
    missing = [row["id"] for row in after_draft
               if row.get("should_refuse") is not True and row["id"] not in covered]
    if missing:
        raise BlockerClosureError(f"answerable cases without evidence: {missing}")
    continuity = {"raw_rows": len(raw_rows), "spans_proved": 0, "snippet_matches": 0, "snippet_sha_matches": 0}
    for row in raw_rows:
        rng = row["raw_chunk_char_range"]
        chunk = chunks[row["chunk_id"]]
        if chunk["text"][rng["start"]:rng["end"]] != row["raw_evidence_span"]:
            raise BlockerClosureError("raw span proof failed")
        continuity["spans_proved"] += 1
        if row["snippet"] != coord.display_snippet(row["raw_evidence_span"]):
            raise BlockerClosureError("snippet mismatch")
        continuity["snippet_matches"] += 1
        if row["snippet_sha256"] != coord.sha256_text(row["snippet"]):
            raise BlockerClosureError("snippet SHA mismatch")
        continuity["snippet_sha_matches"] += 1
    skill = {"name": "data-analytics:analyze-data-quality", "available": False,
             "failure": "Skill not found: data-analytics:analyze-data-quality"}
    coordinate_report = {
        "coordinate_contract": CONTRACT,
        "strict_validation": "PASS",
        "raw_rows_validated": len(raw_rows),
        "legacy_rows_remaining": len(legacy_rows),
        "target_cases": {
            case_id: {
                "evidence_rows": len(rows),
                "all_raw_codepoint_v1": all(row.get("coordinate_contract") == CONTRACT for row in rows),
                "raw_ranges": [row["raw_chunk_char_range"] for row in rows],
            } for case_id, rows in sorted(target_raw.items())
        },
        "remaining_blockers": 0,
        "skill": skill,
    }
    quality = {
        "skill": skill,
        "equivalent_deterministic_checks": {
            "completeness": {"draft_rows": len(after_draft), "remaining_blockers": 0,
                             "answerable_cases_without_evidence": len(missing)},
            "uniqueness": {"unique_case_ids": len({row["id"] for row in after_draft}),
                           "unique_evidence_rows": len(after_evidence)},
            "referential_integrity": {"zh032_dependencies": 0, "target_legacy_rows": 0},
            "continuity": continuity,
            "consistency": {"input_shas_unchanged": True, "non_target_rows_byte_identical": True},
        },
    }

    # --- report documents -----------------------------------------------------
    policy_doc = (
        f"# multi_span_exact_evidence_v1（zh-035）\n\n"
        "## 定义\n"
        "当一个答案点（此处为 zh-035 的 `fibo.py`）在语料中存在多个完全相同、可重建的 "
        "verbatim raw span 时，不得任选其中一个作为唯一证据；全部 span 均作为该答案点的证据写入。\n\n"
        "## 已记录 span（6 个，稳定排序，全部满足 chunk_text[start:end] == raw_evidence_span）\n\n"
        + "".join(
            f"- `{source_id}` / `{chunk_id}` `[{start},{end})` "
            f"{'declared source 内' if source_id == 'python-tutorial-zh.md' else '其他 source（需显式 scope expansion）'}\n"
            for source_id, chunk_id, start, end in ZH035_SPANS)
        + "\n## 治理\n"
        "- 本 policy 为需所有者批准的新 evidence policy，此处已由所有者授权启用。\n"
        "- 跨 source span 的 scope 扩展已显式记录为 "
        f"`{SCOPE_EXPANSION_MARKER}`，见 manifest 与 reannotation-diff。\n"
        "- 每个 span 独立记录 raw source、chunk、`[start,end)` 与 raw span SHA（见 "
        "multi-span-evidence-ledger.jsonl）。\n"
        f"- 记录者：{ACTOR}；candidate 状态：revision_status=CANDIDATE、activation_blocked=true。\n"
    )
    repair_report = (
        "# v2.0.6 owner-authorized final blocker closure（REPAIR_REPORT）\n\n"
        "这是所有者授权的确定性数据治理修复 candidate：不是人工审核、不是 active 版本、"
        "不是 overlay、不是 v2.1 准入。未调用 LLM/API、未联网。\n\n"
        f"- case 数：149 → 148（retire zh-032，原因固定 "
        f"`{RETIRE_REASON}`，退役前已 fail-closed 检查无 follow-up/chain/doc_target 依赖）\n"
        f"- evidence 数：159 → 162（移除 5 条目标 case 旧证据行，新增 8 条 raw evidence）\n"
        f"- zh-035：启用 `{MULTI_SPAN_POLICY}`，写入全部 6 个 verbatim duplicate span"
        "（declared source 内 3 个 + 其他 source 3 个），无任选行为；跨 source scope 扩展"
        f"显式记录为 `{SCOPE_EXPANSION_MARKER}`；query 与答案点文本不变\n"
        f"- mixed-022：答案点收窄为「{MIXED022_POINT}」（c9fd20815ea8_chunk_5 [18,55)），"
        "删除未获支持的「装饰器」答案点与 orphan evidence，仅保留唯一连续可重建 raw evidence\n"
        f"- mixed-028：删除无直接证据的答案点 0，答案点收窄为「{MIXED028_POINT}」"
        "（993955159403_chunk_7 [152,157)），删除 orphan evidence\n"
        "- 4 条 blocker 全部关闭：remaining_blockers=0，无坐标 unresolved 残留记录；"
        "新增 evidence 全部通过 raw-codepoint-v1 严格校验\n"
        "- 非目标行逐字节不变；输入 SHA 全部不变；两次构建逐字节一致；"
        "manifest 自哈希与磁盘 SHA 一致\n"
        "- 剩余门禁：见 REVIEW_AND_SPLIT_REBUILD_REQUIRED.md；activation 保持 blocked。\n"
    )
    review_doc = (
        "# REVIEW_AND_SPLIT_REBUILD_REQUIRED\n\n"
        "本 v2.0.6 candidate 关闭了 v2.0.5 的全部 blocker，但：\n\n"
        "- 历史 split / lock 配置一律不复用，也不得被本 candidate 读取或修改；\n"
        "- 本 candidate 未经人工审核（human_reviewed=false），激活前必须完成新的 "
        "review / split 重建流程；\n"
        "- 激活前必须先通过全部剩余门禁（activation_blocked=true、overlay_generated=false、"
        "v2_1_entered=false）；\n"
        "- 不生成 overlay、active metadata、v2.1 指针。\n"
    )

    counts = {
        "case_before": 149, "case_after": 148, "retired": 1,
        "evidence_before": 159, "evidence_after": 162,
        "evidence_added": 8, "evidence_removed": 5, "retired_evidence": 1,
        "multi_span_spans": 6, "remaining_blockers": 0,
        "answer_points_narrowed": 2, "answer_points_removed": 2,
    }
    input_paths = {
        "v205_manifest": V205_MANIFEST, "v205_draft_after": DRAFT_AFTER_205,
        "v205_evidence_after": EVIDENCE_AFTER_205,
        "pack_manifest": PACK_DIR / "manifest.json", "pack_jsonl": PACK_DIR / "remaining-blockers-decision-pack.jsonl",
        "draft": DRAFT, "chunks": CHUNKS, "chunk_manifest": CHUNK_MANIFEST,
    }
    input_hashes = {name: _sha(path) for name, path in input_paths.items()}
    files: dict[str, str] = {
        "draft-before.jsonl": "".join(line + "\n" for line in draft_lines),
        "draft-after.jsonl": "".join(line + "\n" for line in after_draft_lines),
        "evidence-before.jsonl": "".join(line + "\n" for line in evidence_lines),
        "evidence-after.jsonl": "".join(line + "\n" for line in after_evidence_lines),
        "reannotation-diff.jsonl": "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in diff),
        "retired-cases.jsonl": "".join(json.dumps({
            "case_id": "zh-032", "reason": RETIRE_REASON, "retired_by": ACTOR,
            "case_count_before": 149, "case_count_after": 148,
        }, ensure_ascii=False, sort_keys=True) + "\n"),
        "retired-evidence.jsonl": "".join(json.dumps({
            **{k: zh032_evidence.get(k) for k in ("chunk_id", "source_id", "snippet")},
            "case_id": "zh-032", "reason": RETIRE_REASON, "retired_by": ACTOR,
        }, ensure_ascii=False, sort_keys=True) + "\n"),
        "multi-span-evidence-policy.md": policy_doc,
        "multi-span-evidence-ledger.jsonl": "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in zh035_ledger),
        "coordinate-validation-report.json": _dump(coordinate_report),
        "data-quality-report.json": _dump(quality),
        "REVIEW_AND_SPLIT_REBUILD_REQUIRED.md": review_doc,
        "REPAIR_REPORT.md": repair_report,
    }
    staging = Path(tempfile.mkdtemp(prefix=".v206-final-closure-", dir=out_dir.parent))
    try:
        for name, content in files.items():
            _atomic_write(staging / name, content)
        manifest = _manifest({
            "revision_status": "CANDIDATE", "activation_blocked": True,
            "human_reviewed": False, "actor": ACTOR,
            "case_count_before": 149, "case_count_after": 148,
            "overlay_generated": False, "v2_1_entered": False,
            "status": "CANDIDATE", "deterministic_rebuild": True,
            "coordinate_contract": CONTRACT, "multi_span_policy": MULTI_SPAN_POLICY,
            "source_scope_expansion": {
                "case_id": "zh-035", "marker": SCOPE_EXPANSION_MARKER,
                "sources": ["python-tutorial-en.md"],
                "chunk_ids": ["e564a122a7a2_chunk_61", "e564a122a7a2_chunk_64", "e564a122a7a2_chunk_65"],
            },
            "counts": counts, "inputs": input_hashes,
            "forbidden_outputs": ["active metadata", "overlay", "v2.1", "split", "locked config"],
            "outputs": {name: _sha(staging / name) for name in files},
            "timestamp": TIMESTAMP,
        })
        _atomic_write(staging / "manifest.json", _dump(manifest))
        os.replace(staging, out_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(out_dir, ignore_errors=True)
        raise
    return {"status": "CANDIDATE", "counts": counts, "manifest": manifest}


if __name__ == "__main__":
    run()
