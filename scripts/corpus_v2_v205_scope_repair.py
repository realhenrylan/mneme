"""Build the v2.0.5 owner-authorized deterministic scope repair candidate."""
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
from scripts import corpus_v2_v204_conservative_reannotation as v204

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "evaluation/datasets/v2/revisions/v2.0.5-owner-authorized-scope-repair"
RESCUE = v204.DEFAULT_OUT / "same-source-rescue-audit"
PACK = v204.DEFAULT_OUT / "owner-decision-pack"
DRAFT = v204.DRAFT
CHUNKS = v204.CHUNKS
CHUNK_MANIFEST = v204.CHUNK_MANIFEST
TIMESTAMP = "2026-08-10T00:00:00+00:00"
CONTRACT = "raw-codepoint-v1"
ALGORITHM = "raw-span-map-1"
NORMALIZATION = "display-whitespace-v1"
RETIRE = {"zh-033"}
EXPAND = {"zh-037"}
NARROW = {"mixed-029", "zh-023", "zh-026", "zh-029", "zh-036", "zh-054", "zh-055"}
UNRESOLVED = {"zh-035", "zh-032", "mixed-022", "mixed-028"}
ALL_TARGETS = RETIRE | EXPAND | NARROW | UNRESOLVED
RETIRE_REASON = "no_same_source_candidate_found_after_owner_authorized_rescue_scan"
ACTOR = "OWNER_AUTHORIZED_DETERMINISTIC_SCOPE_REPAIR"


class ScopeRepairError(Exception):
    """输入门禁或确定性修复失败。"""


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


def load_chunks() -> dict[str, dict]:
    return {row["chunk_id"]: row for row in _jsonl(CHUNKS)}


def _display(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def old_declared_chunk(case_id: str) -> str:
    results = {row["case_id"]: row for row in _jsonl(RESCUE / "same-source-rescue-results.jsonl")}
    return results[case_id]["declared_chunk_id"]


def choose_clause_span(case_id: str, results_by_case: dict, spans_by_case: dict) -> tuple[dict, bool]:
    """Deterministic clause selection: best_candidate first, then sorted fallback."""
    best = results_by_case.get(case_id, {}).get("best_candidate")
    if best and best.get("candidate_type") == "clause" and best.get("unique") and best.get("raw_chunk_char_range"):
        return best, False
    candidates = [
        span for span in spans_by_case.get(case_id, [])
        if span.get("candidate_type") == "clause" and span.get("status") == "in_scope" and span.get("unique")
    ]
    if not candidates:
        raise ScopeRepairError(f"{case_id}: no unique clause span")
    chosen = sorted(candidates, key=lambda span: (span["chunk_id"], span["raw_chunk_char_range"]["start"]))[0]
    return chosen, True


def build_evidence_row(case_id: str, chunk: dict, rng: dict, span: str) -> dict:
    snippet = coord.display_snippet(span)
    return {
        "case_id": case_id,
        "chunk_id": chunk["chunk_id"],
        "source_id": chunk["source"],
        "chunk_text_sha256": _sha_text(chunk["text"]),
        "coordinate_contract": CONTRACT,
        "mapping_algorithm_version": ALGORITHM,
        "snippet_normalization": NORMALIZATION,
        "raw_chunk_char_range": dict(rng),
        "raw_evidence_span": span,
        "snippet": snippet,
        "snippet_sha256": _sha_text(snippet),
    }


def _rebuild_evidence_before(inputs) -> list[dict]:
    migration_after = {
        (row["case_id"], row["chunk_id"]): row["after"]
        for row in inputs.migration if row.get("status") == "migrated" and isinstance(row.get("after"), dict)
    }
    rows = []
    for row in inputs.evidence:
        key = (row.get("case_id"), row.get("chunk_id"))
        rows.append(dict(migration_after[key]) if key in migration_after else dict(row))
    if len(rows) != 161:
        raise ScopeRepairError("evidence baseline must contain 161 rows")
    return rows


def _verify_span(span: dict, chunks: dict[str, dict], case_id: str) -> None:
    chunk = chunks.get(span.get("chunk_id"))
    rng = span.get("raw_chunk_char_range")
    raw_span = span.get("raw_span")
    if chunk is None or not isinstance(rng, dict) or not isinstance(raw_span, str) or not raw_span:
        raise ScopeRepairError(f"{case_id}: span incomplete")
    coord.validate_raw_record(chunk["chunk_id"], chunk["source"], chunk["text"], rng, raw_span)


def _load_inputs() -> tuple:
    inputs = v204.load_inputs()
    if len(inputs.target_case_ids) != 13:
        raise ScopeRepairError("target set must contain exactly 13 cases")
    audit_manifest = json.loads((RESCUE / "manifest.json").read_text(encoding="utf-8"))
    if audit_manifest.get("status") != "AUDIT_OK":
        raise ScopeRepairError("rescue audit status mismatch")
    if audit_manifest.get("inputs", {}).get("chunks") != _sha(CHUNKS) or \
       audit_manifest.get("inputs", {}).get("draft") != _sha(DRAFT) or \
       audit_manifest.get("inputs", {}).get("chunk_manifest") != _sha(CHUNK_MANIFEST):
        raise ScopeRepairError("rescue audit input SHA mismatch")
    if audit_manifest.get("inputs", {}).get("pack") != _sha(PACK / "owner-decision-pack.jsonl"):
        raise ScopeRepairError("decision pack SHA mismatch")
    results = _jsonl(RESCUE / "same-source-rescue-results.jsonl")
    spans = _jsonl(RESCUE / "same-source-candidate-spans.jsonl")
    by_case = {row["case_id"]: row for row in results}
    for case_id in NARROW:
        if by_case[case_id]["category"] != "verbatim_clause_only_found":
            raise ScopeRepairError(f"{case_id}: rescue category mismatch")
    if by_case["zh-037"]["category"] != "verbatim_full_answer_point_found":
        raise ScopeRepairError("zh-037: rescue category mismatch")
    if by_case["zh-035"]["category"] != "ambiguous_duplicate":
        raise ScopeRepairError("zh-035: rescue category mismatch")
    if by_case["zh-033"]["category"] != "no_same_source_candidate_found":
        raise ScopeRepairError("zh-033: rescue category mismatch")
    draft = inputs.draft
    for row in draft:
        meta = row.get("metadata") or {}
        if meta.get("follow_up_to") == "zh-033" or (meta.get("chain_id") or "") == "zh-033" or row.get("doc_target") == "zh-033":
            raise ScopeRepairError("zh-033 has chain or follow-up dependency")
    return inputs, results, spans


def _validate_evidence(rows: list[dict], chunks: dict[str, dict]) -> dict:
    """Raw-codepoint rows must pass strict validation; legacy rows keep dual-track checks.

    Legacy char_range values are known-unreliable (the v2.0.2 repair exists because
    many direct slices mismatch), so legacy rows are only checked for source/chunk
    integrity; direct-slice match counts are reported for observability.
    """
    legacy_direct = 0
    legacy_total = 0
    for row in rows:
        if row.get("coordinate_contract") == CONTRACT:
            coord.strict_validate_row(row, chunks)
            continue
        legacy_total += 1
        chunk = chunks.get(row.get("chunk_id"))
        if chunk is None or chunk.get("source") != row.get("source_id"):
            raise ScopeRepairError("legacy evidence source/chunk mismatch")
        cr = row.get("char_range")
        if isinstance(cr, dict) and isinstance(cr.get("start"), int) and isinstance(cr.get("end"), int):
            if 0 <= cr["start"] <= cr["end"] <= len(chunk["text"]) and chunk["text"][cr["start"]:cr["end"]] == row.get("snippet"):
                legacy_direct += 1
    return {"legacy_direct_char_range_matches": legacy_direct, "legacy_rows": legacy_total}


def _manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = _sha_text(_dump(result))
    return result


def run(*, out_dir: Path = DEFAULT_OUT) -> dict:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    inputs, results, spans = _load_inputs()
    chunks = load_chunks()
    results_by_case = {row["case_id"]: row for row in results}
    spans_by_case: dict[str, list[dict]] = {}
    for span in spans:
        spans_by_case.setdefault(span["case_id"], []).append(span)

    # 1. Deterministic clause spans for the 7 narrowed cases.
    clause_choices: dict[str, tuple[dict, bool]] = {}
    for case_id in sorted(NARROW):
        clause_choices[case_id] = choose_clause_span(case_id, results_by_case, spans_by_case)

    # 2. zh-037 full unique span.
    zh037_full = results_by_case["zh-037"]["best_candidate"]
    if zh037_full.get("candidate_type") != "full" or not zh037_full.get("unique"):
        raise ScopeRepairError("zh-037 full span missing")

    additions: list[dict] = []
    for case_id, (span, fallback) in clause_choices.items():
        _verify_span(span, chunks, case_id)
        chunk = chunks[span["chunk_id"]]
        evidence = build_evidence_row(case_id, chunk, span["raw_chunk_char_range"], span["raw_span"])
        coord.strict_validate_row(evidence, chunks)
        additions.append({
            "case_id": case_id, "chunk_id": span["chunk_id"], "source_id": chunk["source"],
            "candidate_type": "clause", "raw_chunk_char_range": dict(span["raw_chunk_char_range"]),
            "raw_span": span["raw_span"], "fallback_selection": fallback, "evidence": evidence,
        })
    _verify_span(zh037_full, chunks, "zh-037")
    chunk = chunks[zh037_full["chunk_id"]]
    evidence = build_evidence_row("zh-037", chunk, zh037_full["raw_chunk_char_range"], zh037_full["raw_span"])
    coord.strict_validate_row(evidence, chunks)
    additions.append({
        "case_id": "zh-037", "chunk_id": zh037_full["chunk_id"], "source_id": chunk["source"],
        "candidate_type": "full", "raw_chunk_char_range": dict(zh037_full["raw_chunk_char_range"]),
        "raw_span": zh037_full["raw_span"], "fallback_selection": False, "evidence": evidence,
    })

    # 3. Rebuild draft-after.
    draft_after: list[dict] = []
    removed_ids: set[str] = set()
    for row in inputs.draft:
        if row["id"] in RETIRE:
            removed_ids.add(row["id"])
            continue
        if row["id"] in NARROW:
            modified = dict(row)
            points = list(modified.get("acceptable_answer_points") or [])
            chosen = next(a for a in additions if a["case_id"] == row["id"])
            points[0] = _display(chosen["raw_span"])
            modified["acceptable_answer_points"] = points
            draft_after.append(modified)
        else:
            draft_after.append(row)
    if removed_ids != RETIRE or len(draft_after) != 149:
        raise ScopeRepairError("draft-after count must be 149")

    # 4. Rebuild evidence-after and track removals.
    evidence_before = _rebuild_evidence_before(inputs)
    removed_evidence: list[dict] = []
    kept_evidence: list[dict] = []
    for row in evidence_before:
        case_id = row.get("case_id")
        if case_id in RETIRE:
            removed_evidence.append({"case_id": case_id, "chunk_id": row.get("chunk_id"), "reason": "case retired", "evidence": row})
        elif case_id in NARROW:
            removed_evidence.append({"case_id": case_id, "chunk_id": row.get("chunk_id"), "reason": "orphan evidence for replaced answer point", "evidence": row})
        else:
            kept_evidence.append(row)
    evidence_after = kept_evidence + [add["evidence"] for add in additions]
    legacy_checks = _validate_evidence(evidence_after, chunks)
    evidence_after = sorted(evidence_after, key=lambda row: (row.get("case_id", ""), row.get("chunk_id", "")))

    # 5. Diff ledger.
    diffs: list[dict] = []
    for case_id in sorted(ALL_TARGETS):
        if case_id in RETIRE:
            diffs.append({"case_id": case_id, "action": "retire", "answer_point_before": None, "answer_point_after": None})
        elif case_id in EXPAND:
            diffs.append({"case_id": case_id, "action": "expand_scope_keep_answer", "answer_point_before": None, "answer_point_after": None})
        elif case_id in NARROW:
            chosen = next(a for a in additions if a["case_id"] == case_id)
            diffs.append({
                "case_id": case_id, "action": "narrow_answer_point",
                "answer_point_before": (results_by_case[case_id].get("original_answer_points") or [None])[0],
                "answer_point_after": _display(chosen["raw_span"]),
                "chosen_chunk_id": chosen["chunk_id"], "raw_chunk_char_range": chosen["raw_chunk_char_range"],
                "fallback_selection": chosen["fallback_selection"],
            })
        else:
            diffs.append({"case_id": case_id, "action": "keep_unresolved", "answer_point_before": None, "answer_point_after": None})

    common = {
        "revision_status": "CANDIDATE", "activation_blocked": True, "human_reviewed": False,
        "actor": ACTOR, "case_count_before": 150, "case_count_after": 149,
        "status": "CANDIDATE", "coordinate_contract": CONTRACT, "timestamp": TIMESTAMP,
    }
    counts = {
        "case_before": 150, "case_after": 149,
        "retired": len(RETIRE), "expanded_scope": len(EXPAND), "narrowed": len(NARROW),
        "remaining_blockers": len(UNRESOLVED),
        "evidence_before": len(evidence_before), "evidence_after": len(evidence_after),
        "orphan_evidence_removed": len(removed_evidence), "evidence_added": len(additions),
    }
    input_paths = {
        "draft": DRAFT, "chunks": CHUNKS, "chunk_manifest": CHUNK_MANIFEST,
        "v2_manifest": v204.V2_MANIFEST, "unresolved": v204.UNRESOLVED, "migration": v204.MIGRATION,
        "rescue_results": RESCUE / "same-source-rescue-results.jsonl",
        "rescue_spans": RESCUE / "same-source-candidate-spans.jsonl",
        "rescue_manifest": RESCUE / "manifest.json",
        "pack": PACK / "owner-decision-pack.jsonl",
    }
    input_hashes = {name: _sha(path) for name, path in input_paths.items()}
    remaining_md = (
        "# REMAINING_BLOCKERS\n\n以下 case 在 v2.0.5 中保持 unresolved，本 revision 不声称全量 coordinate 通过：\n\n" +
        "".join(f"- {case_id}\n" for case_id in sorted(UNRESOLVED))
    )
    split_md = (
        "# SPLIT_RESEAL_REQUIRED\n\n"
        "v2.0.5 修改了 case 集合（150→149，retired zh-033）与 evidence，"
        "历史 split/dev/holdout 划分和 lock 均不可复用；重新划分并重新封存前不得激活。\n"
    )
    report_md = (
        "# v2.0.5 owner-authorized same-source scope repair candidate\n\n"
        "这是 owner-authorized candidate 数据修复，不是人工审核、不是 active 版本、不是 overlay、不是 v2.1 准入。\n\n"
        f"- case：150 → 149（retire zh-033）\n"
        f"- 已处理：retire 1（zh-033）、scope 扩展 1（zh-037）、clause 收窄 7（{sorted(NARROW)}）\n"
        f"- 保持 unresolved 4：{sorted(UNRESOLVED)}\n"
        f"- evidence：{counts['evidence_before']} → {counts['evidence_after']}（orphan 删除 {counts['orphan_evidence_removed']}，新增 {counts['evidence_added']}）\n"
    )
    quality = {
        "skill": {"name": "data-analytics:analyze-data-quality", "available": False,
                  "failure": "Skill not found: data-analytics:analyze-data-quality"},
        "equivalent_deterministic_checks": {
            "validate_evidence_after": True,
            "draft_rows_after": len(draft_after),
            "evidence_rows_after": len(evidence_after),
            **legacy_checks,
        },
    }
    files: dict[str, str] = {
        "draft-before.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in inputs.draft),
        "draft-after.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in draft_after),
        "evidence-before.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in evidence_before),
        "evidence-after.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in evidence_after),
        "reannotation-diff.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in diffs),
        "retired-cases.jsonl": "".join(json.dumps({"case_id": c, "reason": RETIRE_REASON}, ensure_ascii=False, sort_keys=True) + "\n" for c in sorted(RETIRE)),
        "retired-evidence.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in removed_evidence),
        "raw-scope-additions.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in additions),
        "coordinate-validation-report.json": _dump({
            "contract": CONTRACT, "strict_valid": True,
            "evidence_before": len(evidence_before), "evidence_after": len(evidence_after),
            "additions_validated": len(additions),
        }),
        "data-quality-report.json": _dump(quality),
        "REMAINING_BLOCKERS.md": remaining_md,
        "SPLIT_RESEAL_REQUIRED.md": split_md,
        "REPAIR_REPORT.md": report_md,
    }
    staging = Path(tempfile.mkdtemp(prefix=".v2.0.5-scope-repair-", dir=out_dir.parent))
    try:
        for name, content in files.items():
            _atomic_write(staging / name, content)
        manifest = _manifest({
            **common,
            "counts": counts, "inputs": input_hashes,
            "forbidden_outputs": ["overlay", "active metadata", "v2.1 pointer", "split reuse"],
            "outputs": {name: _sha(staging / name) for name in files},
        })
        _atomic_write(staging / "manifest.json", _dump(manifest))
        os.replace(staging, out_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(out_dir, ignore_errors=True)
        raise
    return {"status": "CANDIDATE", "counts": counts, "manifest": manifest, "diffs": diffs}


if __name__ == "__main__":
    run()
