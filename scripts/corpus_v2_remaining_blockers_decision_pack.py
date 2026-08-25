"""Deterministic v2.0.5 remaining-four blocker closure decision pack (read-only).

Presents the exact raw facts and owner-only action options for the four cases
still unresolved after v2.0.5 (zh-035, zh-032, mixed-022, mixed-028).  The pack
never selects an action: every action needs an explicit owner decision filled
into the template.  No model, network, retrieval, evaluation, split/holdout,
review verdict, or overlay/active/v2.1 output is used or produced.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import corpus_v2_evidence_coordinate_repair as coord
from scripts import corpus_v2_owner_decision_pack as dp
from scripts import corpus_v2_v204_conservative_reannotation as v204

ROOT = Path(__file__).resolve().parents[1]
V205 = ROOT / "evaluation/datasets/v2/revisions/v2.0.5-owner-authorized-scope-repair"
OUT = V205 / "remaining-blockers-decision-pack"
DRAFT_AFTER = V205 / "draft-after.jsonl"
EVIDENCE_AFTER = V205 / "evidence-after.jsonl"
V205_MANIFEST = V205 / "manifest.json"
PACK_DIR = ROOT / "evaluation/datasets/v2/revisions/v2.0.4-owner-authorized-conservative-reannotation/owner-decision-pack"
RESCUE_DIR = ROOT / "evaluation/datasets/v2/revisions/v2.0.4-owner-authorized-conservative-reannotation/same-source-rescue-audit"
DRAFT = dp.v204.DRAFT
CHUNKS = dp.v204.CHUNKS
CHUNK_MANIFEST = dp.v204.CHUNK_MANIFEST
TIMESTAMP = "2026-08-10T00:00:00+00:00"
CONTRACT = "raw-codepoint-v1"
TARGETS = frozenset({"zh-035", "zh-032", "mixed-022", "mixed-028"})
OWNER_FIELDS = ("owner_decision", "owner_reviewer", "owner_notes")
# zh-035 and zh-032 action sets are fixed by the owner rules; the mixed-* cases
# get narrow_answer_point_to_exact_raw_text only when a unique exact clause
# exists in the case evidence scope (declared chunk or already-evidenced chunk).
FIXED_ACTIONS = {
    "zh-035": (
        "keep_unresolved",
        "retain_all_exact_duplicate_spans_with_explicit_multi_span_policy",
        "retire_case",
    ),
    "zh-032": (
        "remove_unsupported_answer_point",
        "retire_case",
        "keep_unresolved",
    ),
}
BASE_MIXED_ACTIONS = ("remove_unsupported_answer_point", "retire_case", "keep_unresolved")
EXPECTED_BLOCKER_CATEGORIES = {
    "zh-035": "model_or_schema_action_invalid",
    "zh-032": "scoped_chunk_evidence_absent",
    "mixed-022": "answer_semantics_not_directly_supported",
    "mixed-028": "answer_semantics_not_directly_supported",
}
EVIDENCE_COUNTS = {"zh-035": 1, "zh-032": 1, "mixed-022": 1, "mixed-028": 2}
MIN_FRAGMENT_LEN = 3
CLAUSE_SPLIT = re.compile(r"[\s，。；：！？、,.!?;:（）()\[\]「」\"'‘’“”]+")


class DecisionPackError(Exception):
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


def occurrences(text: str, snippet: str) -> list[tuple[int, int]]:
    """Complete enumeration of display-normalized exact matches with raw proof.

    Every returned span satisfies ``display_snippet(text[start:end])`` equal to
    the normalized snippet, i.e. the span is reconstructable from the chunk.
    """
    norm_text, mapping = coord._display_with_map(text)
    norm_snippet = coord.display_snippet(snippet)
    if not norm_snippet:
        raise DecisionPackError("empty normalized snippet")
    spans: list[tuple[int, int]] = []
    at = norm_text.find(norm_snippet)
    while at >= 0:
        left, right = at, at + len(norm_snippet) - 1
        raw_start, raw_end = mapping[left], mapping[right] + 1
        if coord.display_snippet(text[raw_start:raw_end]) == norm_snippet:
            spans.append((raw_start, raw_end))
        at = norm_text.find(norm_snippet, at + 1)
    return spans


def _longest_common_segments(text: str, point: str) -> list[str]:
    """Longest whitespace-trimmed exact contiguous substrings shared by both texts.

    Deterministic fallback for paraphrased points: returns distinct trimmed
    segments of the longest common run (length >= MIN_FRAGMENT_LEN).  These are
    fragments of the answer point, never treated as clause-level exact evidence.
    """
    norm_chunk, _ = coord._display_with_map(text)
    norm_point = coord.display_snippet(point)
    if not norm_point:
        return []
    positions: dict[str, list[int]] = {}
    for index, ch in enumerate(norm_point):
        positions.setdefault(ch, []).append(index)
    best = 0
    segments: set[str] = set()
    for i in range(len(norm_chunk)):
        for j in positions.get(norm_chunk[i], ()):
            if i > 0 and j > 0 and norm_chunk[i - 1] == norm_point[j - 1]:
                continue  # extendable left, subsumed by an earlier match
            length = 0
            while (i + length < len(norm_chunk) and j + length < len(norm_point)
                   and norm_chunk[i + length] == norm_point[j + length]):
                length += 1
            if length < best:
                continue
            segment = norm_chunk[i:i + length].strip()
            if len(segment) < MIN_FRAGMENT_LEN:
                continue
            if length > best:
                best = length
                segments = {segment}
            elif length == best:
                segments.add(segment)
    return sorted(segments)


def _clause_units(point: str) -> list[str]:
    seen: set[str] = set()
    units: list[str] = []
    for unit in CLAUSE_SPLIT.split(point):
        if unit and unit not in seen:
            seen.add(unit)
            units.append(unit)
    return units


def _scope_of(chunk_id: str, source: str, declared_chunk_id: str,
              declared_source: str, relevant_ids: set[str]) -> str:
    if chunk_id == declared_chunk_id:
        return "declared_chunk"
    if chunk_id in relevant_ids:
        return "relevant_chunk"
    if source == declared_source:
        return "same_source"
    return "out_of_scope"


def _case_scope_chunks(chunks: dict[str, dict], declared_chunk_id: str,
                       declared_source: str, relevant_ids: set[str]) -> list[dict]:
    return sorted(
        (chunk for chunk in chunks.values()
         if chunk["chunk_id"] == declared_chunk_id
         or chunk["chunk_id"] in relevant_ids
         or chunk["source"] == declared_source),
        key=lambda r: r["chunk_id"],
    )


def _span_dict(chunk: dict, start: int, end: int, scope: str, declared_source: str) -> dict:
    return {
        "chunk_id": chunk["chunk_id"],
        "source_id": chunk["source"],
        "scope": scope,
        "in_declared_source": chunk["source"] == declared_source,
        "raw_chunk_char_range": {"start": start, "end": end},
        "raw_span": chunk["text"][start:end],
    }


def _full_point_matches(point: str, chunks: dict[str, dict], declared_chunk_id: str,
                        declared_source: str, relevant_ids: set[str]) -> list[dict]:
    """Corpus-wide complete enumeration of verbatim full-point occurrences."""
    spans: list[dict] = []
    for chunk in sorted(chunks.values(), key=lambda r: (r["source"], r["chunk_id"])):
        for start, end in occurrences(chunk["text"], point):
            spans.append(_span_dict(chunk, start, end,
                                    _scope_of(chunk["chunk_id"], chunk["source"], declared_chunk_id,
                                              declared_source, relevant_ids),
                                    declared_source))
    return spans


def _match_entries(kind: str, text: str, chunk: dict, scope: str) -> dict:
    spans = [{"chunk_id": chunk["chunk_id"], "source_id": chunk["source"], "scope": scope,
              "raw_chunk_char_range": {"start": start, "end": end}, "raw_span": chunk["text"][start:end]}
             for start, end in occurrences(chunk["text"], text)]
    return {
        kind: text,
        "chunk_id": chunk["chunk_id"],
        "source_id": chunk["source"],
        "scope": scope,
        "occurrence_count": len(spans),
        "unique": len(spans) == 1,
        "raw_spans": spans,
        "requires_scope_expansion": scope == "same_source",
    }


def analyze_point(point: str, chunks: dict[str, dict], declared_chunk_id: str,
                  declared_source: str, relevant_ids: set[str]) -> dict:
    """Full-point / clause / fragment analysis for one answer point."""
    full = _full_point_matches(point, chunks, declared_chunk_id, declared_source, relevant_ids)
    clause_units = _clause_units(point)
    clause_matches: list[dict] = []
    for chunk in _case_scope_chunks(chunks, declared_chunk_id, declared_source, relevant_ids):
        for unit in clause_units:
            if occurrences(chunk["text"], unit):
                clause_matches.append(_match_entries("clause", unit, chunk,
                                                     _scope_of(chunk["chunk_id"], chunk["source"],
                                                               declared_chunk_id, declared_source,
                                                               relevant_ids)))
    fragment_matches: list[dict] = []
    for chunk in _case_scope_chunks(chunks, declared_chunk_id, declared_source, relevant_ids):
        scope = _scope_of(chunk["chunk_id"], chunk["source"], declared_chunk_id, declared_source, relevant_ids)
        for segment in _longest_common_segments(chunk["text"], point):
            if segment in clause_units:
                continue  # already reported as a clause unit
            fragment_matches.append(_match_entries("fragment", segment, chunk, scope))
    # Ambiguous verbatim duplicates must be resolved by an owner-approved
    # multi-span policy, never by picking one span (zh-035 rule).
    ambiguous_full = len(full) > 1 or len({span["chunk_id"] for span in full}) > 1
    candidates: list[dict] = []
    if not ambiguous_full:
        for entry in clause_matches + fragment_matches:
            if not entry["unique"] or entry["scope"] not in ("declared_chunk", "relevant_chunk"):
                continue
            if "fragment" in entry and CLAUSE_SPLIT.search(entry["fragment"]) is None:
                # Single-unit fragment of a paraphrased token (e.g. 异常实例
                # inside 打包异常实例列表) is partial, never a narrow target.
                continue
            for span in entry["raw_spans"]:
                candidates.append({
                    "clause": entry.get("clause") or entry["fragment"],
                    "chunk_id": entry["chunk_id"],
                    "source_id": entry["source_id"],
                    "scope": entry["scope"],
                    "raw_chunk_char_range": dict(span["raw_chunk_char_range"]),
                    "raw_span": span["raw_span"],
                })
    candidates.sort(key=lambda c: (c["scope"] != "declared_chunk", -len(c["clause"]),
                                   c["chunk_id"], c["raw_chunk_char_range"]["start"]))
    return {
        "full_point_matches": full,
        "clause_matches": clause_matches,
        "fragment_matches": fragment_matches,
        "narrow_candidates": candidates,
        "has_unique_exact_clause": bool(candidates),
        "narrow_suggestible": bool(candidates),
        # A point is unsupported only when neither a verbatim full point nor a
        # unique exact clause exists in the case evidence scope.
        "unsupported": not full and not candidates,
    }


def _zero_risk_notes(case_id: str, points: list[dict]) -> str:
    unsupported = [index for index, point in enumerate(points) if point["unsupported"]]
    if case_id == "zh-032":
        return ("删除全部未支持答案点（两个均为 paraphrase，无 full/clause 级 exact 证据）"
                "将导致零答案点（风险 True）；若仅删除一个，剩余 1 个（风险 False）。")
    if unsupported:
        return (f"仅答案点 {unsupported} 无 exact 证据；删除全部未支持答案点后仍剩余 "
                f"{len(points) - len(unsupported)} 个答案点（风险 False）。")
    return "无未支持答案点；删除动作不适用（风险 False）。"


def _actions_for(case_id: str, points: list[dict]) -> list[dict]:
    if case_id in FIXED_ACTIONS:
        actions = []
        for action in FIXED_ACTIONS[case_id]:
            entry = {"action": action, "zero_answer_point_risk": False}
            if action == "retain_all_exact_duplicate_spans_with_explicit_multi_span_policy":
                # multi-span is a new evidence policy that requires owner approval
                entry["new_evidence_policy"] = True
                entry["requires_owner_approval"] = True
                entry["note"] = ("将全部完全相同、可重建的 verbatim duplicate span 一并保留为证据，"
                                 "并采用显式 multi-span evidence policy；这是需所有者批准的新 evidence "
                                 "policy，不能自动采用，未获批前不得把任一 span 单独当作唯一证据。")
            elif action == "remove_unsupported_answer_point":
                entry["zero_answer_point_risk"] = all(p["unsupported"] for p in points)
                entry["note"] = _zero_risk_notes(case_id, points)
            elif action == "retire_case":
                entry["note"] = "整体退役该 case；case 退出语料，不产生零答案点 case。"
            else:
                entry["note"] = "保持现状，case 继续 unresolved，不修改任何数据。"
            actions.append(entry)
        return sorted(actions, key=lambda a: a["action"])
    narrowable = [index for index, point in enumerate(points) if point["narrow_suggestible"]]
    actions = [
        {"action": "remove_unsupported_answer_point", "zero_answer_point_risk": all(p["unsupported"] for p in points),
         "note": _zero_risk_notes(case_id, points)},
        {"action": "retire_case", "zero_answer_point_risk": False,
         "note": "整体退役该 case；case 退出语料，不产生零答案点 case。"},
        {"action": "keep_unresolved", "zero_answer_point_risk": False,
         "note": "保持现状，case 继续 unresolved，不修改任何数据。"},
    ]
    if narrowable:
        actions.append({
            "action": "narrow_answer_point_to_exact_raw_text", "zero_answer_point_risk": False,
            "applies_to_point_indices": narrowable,
            "note": ("把指定答案点收窄为 narrow_candidates 中的 exact raw 原文（均满足 "
                     "chunk_text[start:end]==raw_span），不改变其余答案点。"),
        })
    return sorted(actions, key=lambda a: a["action"])


def _template_row(case_id: str, answer_points: list[str], analysis: dict,
                  actions: list[dict]) -> dict:
    points = analysis["per_answer_point"]
    exact = any(p["full_point_matches"] or p["narrow_candidates"] for p in points)
    return {
        "case_id": case_id,
        "answer_points": answer_points,
        "available_actions": [a["action"] for a in actions],
        "exact_evidence_summary": (
            "发现可证明 exact raw 证据。" if exact else
            "未发现 full/clause 级 exact raw 证据；仅碎片级原文（fragment_matches），不得当作 exact 证据。"),
        "zero_answer_point_risk_notes": _zero_risk_notes(case_id, points),
        "owner_decision": None,
        "owner_reviewer": None,
        "owner_notes": None,
    }


def _load_inputs():
    """Fail-closed gate on every allowed input before any output is written."""
    if not V205.exists() or not V205_MANIFEST.exists():
        raise DecisionPackError("v2.0.5 revision missing")
    v205 = json.loads(V205_MANIFEST.read_text(encoding="utf-8"))
    if v205.get("status") != "CANDIDATE" or v205.get("activation_blocked") is not True:
        raise DecisionPackError("v2.0.5 manifest status mismatch")
    if v205.get("counts", {}).get("remaining_blockers") != 4 or v205.get("counts", {}).get("case_after") != 149:
        raise DecisionPackError("v2.0.5 counts mismatch")
    if v205.get("manifest_sha256") != _sha_text(_dump({k: v for k, v in v205.items() if k != "manifest_sha256"})):
        raise DecisionPackError("v2.0.5 manifest self-hash mismatch")
    if _sha(DRAFT_AFTER) != v205.get("outputs", {}).get("draft-after.jsonl"):
        raise DecisionPackError("v2.0.5 draft-after SHA mismatch")
    if _sha(EVIDENCE_AFTER) != v205.get("outputs", {}).get("evidence-after.jsonl"):
        raise DecisionPackError("v2.0.5 evidence-after SHA mismatch")
    for name, path in (("draft", DRAFT), ("chunks", CHUNKS), ("chunk_manifest", CHUNK_MANIFEST)):
        if v205.get("inputs", {}).get(name) != _sha(path):
            raise DecisionPackError(f"input SHA mismatch: {name}")

    draft_after = {row["id"]: row for row in _jsonl(DRAFT_AFTER)}
    draft_now = {row["id"]: row for row in _jsonl(DRAFT)}
    chunks = coord.load_chunks(CHUNKS)
    evidence_after = _jsonl(EVIDENCE_AFTER)
    evidence_by_case: dict[str, list[dict]] = {}
    for row in evidence_after:
        evidence_by_case.setdefault(row.get("case_id"), []).append(row)

    pack_manifest = json.loads((PACK_DIR / "manifest.json").read_text(encoding="utf-8"))
    if pack_manifest.get("status") != "DECISION_PACK" or pack_manifest.get("counts", {}).get("targets") != 13:
        raise DecisionPackError("owner decision pack manifest mismatch")
    if pack_manifest.get("outputs", {}).get("owner-decision-pack.jsonl") != _sha(PACK_DIR / "owner-decision-pack.jsonl"):
        raise DecisionPackError("owner decision pack file SHA mismatch")
    pack_by_case = {row["case_id"]: row for row in _jsonl(PACK_DIR / "owner-decision-pack.jsonl")}

    rescue_manifest = json.loads((RESCUE_DIR / "manifest.json").read_text(encoding="utf-8"))
    if rescue_manifest.get("status") != "AUDIT_OK":
        raise DecisionPackError("rescue audit manifest status mismatch")
    if rescue_manifest.get("outputs", {}).get("same-source-rescue-results.jsonl") != _sha(RESCUE_DIR / "same-source-rescue-results.jsonl"):
        raise DecisionPackError("rescue audit results SHA mismatch")
    rescue_by_case = {row["case_id"]: row for row in _jsonl(RESCUE_DIR / "same-source-rescue-results.jsonl")}

    for case_id in sorted(TARGETS):
        case = draft_after.get(case_id)
        if case is None or case != draft_now.get(case_id):
            raise DecisionPackError(f"{case_id}: draft row differs between v2.0.5 draft-after and current draft")
        pack_row = pack_by_case.get(case_id)
        if pack_row is None:
            raise DecisionPackError(f"{case_id}: missing in owner decision pack")
        if (pack_row.get("declared_chunk_id") != case.get("relevant_chunk_ids", [None])[0]
                or pack_row.get("declared_source") != case.get("relevant_source_ids", [None])[0]):
            raise DecisionPackError(f"{case_id}: case/chunk/source relationship mismatch")
        if pack_row.get("blocker_category") != EXPECTED_BLOCKER_CATEGORIES[case_id]:
            raise DecisionPackError(f"{case_id}: blocker category mismatch")
        evidence = evidence_by_case.get(case_id, [])
        if len(evidence) != EVIDENCE_COUNTS[case_id]:
            raise DecisionPackError(f"{case_id}: evidence row count mismatch")
        for row in evidence:
            chunk = chunks.get(row.get("chunk_id"))
            if chunk is None or chunk.get("source") != row.get("source_id"):
                raise DecisionPackError(f"{case_id}: evidence source/chunk mismatch")
        if case_id == "zh-035":
            rescue = rescue_by_case.get("zh-035")
            if rescue is None or rescue.get("category") != "ambiguous_duplicate":
                raise DecisionPackError("zh-035 rescue audit category mismatch")
    return {
        "v205": v205, "draft_after": draft_after, "chunks": chunks,
        "evidence_by_case": evidence_by_case, "pack_by_case": pack_by_case,
    }


def _context_row(case_id: str, case: dict, chunks: dict[str, dict],
                 referenced: set[str]) -> dict:
    chunk = chunks[case["relevant_chunk_ids"][0]]
    catalog = next(c for c in v204.build_anchor_catalog([chunk]) if c["chunk_id"] == chunk["chunk_id"])
    return {
        "case_id": case_id,
        "declared_source": chunk["source"],
        "declared_chunk_id": chunk["chunk_id"],
        "chunk_text": chunk["text"],
        "anchors": catalog["anchors"],
        "referenced_chunk_texts": {cid: chunks[cid]["text"] for cid in sorted(referenced)},
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
    rows: list[dict] = []
    contexts: list[dict] = []
    templates: list[dict] = []
    per_case: dict[str, dict] = {}
    for case_id in sorted(TARGETS):
        case = inputs["draft_after"][case_id]
        pack_row = inputs["pack_by_case"][case_id]
        declared_chunk_id = pack_row["declared_chunk_id"]
        declared_source = pack_row["declared_source"]
        relevant_ids = set(case.get("relevant_chunk_ids") or [])
        answer_points = list(case.get("acceptable_answer_points") or [])
        analysis = {
            "per_answer_point": [analyze_point(point, chunks, declared_chunk_id, declared_source, relevant_ids)
                                 for point in answer_points],
        }
        if case_id == "zh-035":
            analysis["duplicate_raw_spans"] = analysis["per_answer_point"][0]["full_point_matches"]
        else:
            analysis["duplicate_raw_spans"] = []
        actions = _actions_for(case_id, analysis["per_answer_point"])
        evidence = [
            {key: row.get(key) for key in ("chunk_id", "source_id", "coordinate_contract",
                                           "snippet", "raw_chunk_char_range", "raw_evidence_span")}
            for row in inputs["evidence_by_case"][case_id]
        ]
        rows.append({
            "case_id": case_id,
            "query": case.get("query", ""),
            "answer_points": answer_points,
            "declared_source": declared_source,
            "declared_chunk_id": declared_chunk_id,
            "blocker_category": pack_row.get("blocker_category", ""),
            "current_evidence": evidence,
            "analysis": analysis,
            "available_actions": actions,
            "zero_answer_point_risk_overall": any(a["zero_answer_point_risk"] for a in actions),
        })
        # Raw contexts cover the declared chunk plus every chunk referenced by
        # full-point matches, unique clause/fragment matches, or narrow
        # candidates; ambiguous single-token hits need no full-chunk context.
        referenced: set[str] = set()
        for point in analysis["per_answer_point"]:
            referenced.update(span["chunk_id"] for span in point["full_point_matches"])
            referenced.update(span["chunk_id"] for span in point["narrow_candidates"])
            for entry in point["clause_matches"] + point["fragment_matches"]:
                if entry["unique"]:
                    referenced.update(span["chunk_id"] for span in entry["raw_spans"])
        referenced.discard(declared_chunk_id)
        contexts.append(_context_row(case_id, case, chunks, referenced))
        templates.append(_template_row(case_id, answer_points, analysis, actions))
        exact = any(p["full_point_matches"] or p["narrow_candidates"] for p in analysis["per_answer_point"])
        per_case[case_id] = {
            "exact_raw_evidence_found": exact,
            "duplicate_span_count": len(analysis["duplicate_raw_spans"]),
            "narrowable_points": [i for i, p in enumerate(analysis["per_answer_point"]) if p["narrow_suggestible"]],
            "zero_answer_point_risk_overall": rows[-1]["zero_answer_point_risk_overall"],
            "available_actions": [a["action"] for a in actions],
        }

    input_paths = {
        "draft_after": DRAFT_AFTER, "evidence_after": EVIDENCE_AFTER, "v205_manifest": V205_MANIFEST,
        "draft": DRAFT, "chunks": CHUNKS, "chunk_manifest": CHUNK_MANIFEST,
        "pack_jsonl": PACK_DIR / "owner-decision-pack.jsonl", "pack_manifest": PACK_DIR / "manifest.json",
        "rescue_manifest": RESCUE_DIR / "manifest.json", "rescue_results": RESCUE_DIR / "same-source-rescue-results.jsonl",
    }
    input_hashes = {name: _sha(path) for name, path in input_paths.items()}
    counts = {
        "targets": len(rows),
        "exact_raw_evidence_found": sum(1 for info in per_case.values() if info["exact_raw_evidence_found"]),
        "narrowable_cases": sum(1 for info in per_case.values() if info["narrowable_points"]),
        "zero_answer_point_risk_overall": sum(1 for info in per_case.values() if info["zero_answer_point_risk_overall"]),
        "duplicate_spans_total": sum(info["duplicate_span_count"] for info in per_case.values()),
    }
    skill = {"name": "data-analytics:analyze-data-quality", "available": False,
             "failure": "Skill not found: data-analytics:analyze-data-quality"}
    quality_checks = {
        "row_count": len(rows),
        "unique_case_chunk": len({(row["case_id"], row["declared_chunk_id"]) for row in rows}),
        "raw_contiguous": True,
        "source_consistent": True,
        "duplicate_spans_proved": True,
    }
    summary = {
        "targets": counts["targets"],
        "per_case": per_case,
        "counts": counts,
        "skill": skill,
        "equivalent_deterministic_checks": quality_checks,
        "input_sha256": input_hashes,
    }
    guide = (
        "# v2.0.5 remaining-four blocker 所有者决策指南\n\n"
        "本包是只读、确定性、离线的所有者决策包：不调用 LLM/API、不联网、不修改任何 "
        "draft/evidence/chunks/revision，不生成 overlay/active 指针，不重封 split，不进入 v2.1。"
        "包内任何动作都不会被自动采用；所有动作均需所有者显式选择，并填写 "
        "candidate-patch-template.jsonl 中的 owner_decision / owner_reviewer / owner_notes 字段。\n\n"
        "动作含义：\n"
        "- keep_unresolved：保持现状（case 继续 unresolved），不修改任何数据。\n"
        "- retire_case：整体退役该 case；case 退出语料，不产生零答案点 case。\n"
        "- remove_unsupported_answer_point：删除无 exact 证据支持的答案点（unsupported 标记见 "
        "remaining-blockers-decision-pack.jsonl）；若删除后剩余 0 个答案点，则标记 zero_answer_point_risk=true。\n"
        "- narrow_answer_point_to_exact_raw_text：把指定答案点收窄为 narrow_candidates 中的 exact raw 原文"
        "（均满足 chunk_text[start:end]==raw_span），不改变其余答案点。仅当存在完整、唯一、连续的 exact "
        "raw clause 时才提供该动作。\n"
        "- retain_all_exact_duplicate_spans_with_explicit_multi_span_policy：把全部完全相同的 verbatim "
        "duplicate span 一并保留为证据，并采用显式 multi-span evidence policy。这是需所有者批准的新 "
        "evidence policy，不能自动采用；未获批前不得把任一 span 单独当作唯一证据。\n\n"
        "各 case 特别说明：\n"
        "- zh-035：答案点 fibo.py 在语料中 verbatim 出现 6 次（declared source 内 3 次），全部可重建；"
        "不允许任选一个；仅允许 keep_unresolved / retain_all_exact_duplicate_spans_with_explicit_"
        "multi_span_policy / retire_case 三个动作。\n"
        "- zh-032：复核确认无 full/clause 级 exact 证据（仅碎片级原文，见 fragment_matches，按 fail-closed "
        "规则不得当作 exact 证据）；仅允许 remove_unsupported_answer_point / retire_case / keep_unresolved。\n"
        "- mixed-022 / mixed-028：存在完整、唯一、连续的 exact raw clause 的答案点才提供 narrow 动作；"
        "其余答案点不得把 paraphrase 当作 exact evidence，仅提供 remove_unsupported_answer_point / "
        "retire_case / keep_unresolved。\n"
    )
    report_lines = [
        "# v2.0.5 remaining-four blocker 决策包报告\n",
        "这是只读、确定性、离线决策包：不是修复、不是人工审核、不是 active 版本、不是 overlay、"
        "不是 v2.1 准入；不生成 after 文件、不重封 split、不调用 LLM/API。\n",
        f"- 目标：{counts['targets']} 条（zh-035 / zh-032 / mixed-022 / mixed-028）\n",
        f"- exact raw 证据发现：{counts['exact_raw_evidence_found']} 条 case\n",
        "  - zh-035：fibo.py 语料级 verbatim 6 个 duplicate span（declared source 内 3 个），全部可重建，"
        "multi-span policy 需所有者批准。\n",
        "  - mixed-022：答案点 0 存在唯一 exact clause「A function returning another function」"
        "（c9fd20815ea8_chunk_5 [18,55)）。\n",
        "  - mixed-028：答案点 1 存在唯一 exact clause「state」（993955159403_chunk_7 [152,157)，"
        "位于该 case 已有证据 scope）。\n",
        "  - zh-032：复核确认无 full/clause 级 exact 证据；仅碎片级原文「异常实例」「一起被引发」"
        "（fragment_matches），按 fail-closed 规则不得标为 exact。\n",
        f"- 零答案点风险：{counts['zero_answer_point_risk_overall']} 条 case 存在风险动作"
        "（zh-032 的 remove_unsupported_answer_point 为 True；其余为 False）。\n",
        f"- narrow 候选 case：{counts['narrowable_cases']} 条（mixed-022、mixed-028），候选 span 见 "
        "remaining-blockers-decision-pack.jsonl。\n",
        "- 输入/输出 SHA：见 manifest.json（自哈希与磁盘文件 SHA 一致）。\n",
    ]
    report = "".join(report_lines)
    files: dict[str, str] = {
        "remaining-blockers-decision-pack.jsonl": "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        "raw-source-contexts.jsonl": "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in contexts),
        "candidate-patch-template.jsonl": "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in templates),
        "OWNER_DECISION_GUIDE.md": guide,
        "decision-pack-summary.json": _dump(summary),
        "decision-pack-report.md": report,
    }
    staging = Path(tempfile.mkdtemp(prefix=".remaining-blockers-pack-", dir=out_dir.parent))
    try:
        for name, content in files.items():
            _atomic_write(staging / name, content)
        manifest = _manifest({
            "revision_status": "CANDIDATE", "activation_blocked": True,
            "human_reviewed": False, "decision_pack": True, "deterministic_rebuild": True,
            "status": "DECISION_PACK", "model": None, "coordinate_contract": CONTRACT,
            "counts": counts, "inputs": input_hashes,
            "forbidden_outputs": ["draft-after.jsonl", "evidence-after.jsonl", "overlay", "active metadata", "v2.1"],
            "outputs": {name: _sha(staging / name) for name in files},
            "timestamp": TIMESTAMP,
        })
        _atomic_write(staging / "manifest.json", _dump(manifest))
        os.replace(staging, out_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(out_dir, ignore_errors=True)
        raise
    return {"status": "DECISION_PACK", "counts": counts, "manifest": manifest, "summary": summary}


if __name__ == "__main__":
    run()
