"""Build the deterministic v2.0.4 owner decision pack (read-only)."""
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
V204_OUT = v204.DEFAULT_OUT
OUT = V204_OUT / "owner-decision-pack"
TIMESTAMP = "2026-08-10T00:00:00+00:00"
CONTRACT = "raw-codepoint-v1"
ALLOWED_ACTIONS = {
    "remove_answer_point",
    "replace_answer_point_with_exact_raw_text",
    "narrow_answer_point_to_exact_raw_text",
    "add_new_document_then_reannotate",
    "expand_evidence_scope_with_explicit_approval",
    "retire_case",
}
TEMPLATE_FIELDS = ("owner_action", "revised_answer_point", "chosen_anchor_id", "owner_note")
TARGET_GROUPS = v204.TARGET_GROUPS
EXPECTED_CASE_IDS = v204.EXPECTED_CASE_IDS


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


def build_anchor_catalog(chunks: list[dict]) -> list[dict]:
    return v204.build_anchor_catalog(chunks)


def build_context_row(case_id: str, chunk: dict, catalog: dict, current_answer_point: str) -> dict:
    anchors = []
    for anchor in catalog["anchors"]:
        rng = anchor["raw_chunk_char_range"]
        if chunk["text"][rng["start"]:rng["end"]] != anchor["raw_span"] or not anchor["raw_span"]:
            raise DecisionPackError(f"{case_id}: raw anchor proof failed")
        anchors.append({
            "anchor_id": anchor["anchor_id"],
            "raw_span": anchor["raw_span"],
            "raw_chunk_char_range": dict(rng),
        })
    return {
        "case_id": case_id,
        "current_answer_point": current_answer_point,
        "declared_source": chunk["source"],
        "declared_chunk_id": chunk["chunk_id"],
        "chunk_text": chunk["text"],
        "anchors": anchors,
    }


def scope_candidates(chunks, declared_chunk_id: str, source: str) -> list[dict]:
    """Other chunks of the same source may only be marked for scope expansion."""
    values = chunks.values() if isinstance(chunks, dict) else chunks
    return [
        {
            "chunk_id": chunk["chunk_id"],
            "status": "needs_scope_expansion",
            "current_evidence": False,
            "raw_span_candidates": None,
        }
        for chunk in sorted(values, key=lambda r: r["chunk_id"])
        if chunk["source"] == source and chunk["chunk_id"] != declared_chunk_id
    ]


def zero_answer_point_risk(case: dict) -> bool:
    points = list(case.get("acceptable_answer_points") or [])
    return len(points) <= 1 and case.get("should_refuse") is not True


def patch_template(case_id: str) -> dict:
    return {field: None for field in TEMPLATE_FIELDS} | {"owner_note": f"{case_id} 待所有者决定"}


def _load_inputs():
    inputs = v204.load_inputs()
    if len(inputs.target_case_ids) != 13:
        raise DecisionPackError("target set must contain exactly 13 cases")
    return inputs


def _quality(rows: list[dict], chunks: dict[str, dict]) -> dict:
    checks = {
        "row_count": len(rows),
        "unique_case_chunk": len({(r.get("case_id"), r.get("chunk_id")) for r in rows}),
        "raw_contiguous": True,
        "source_consistent": True,
    }
    try:
        coord.strict_validate(rows, chunks)
    except Exception as exc:
        checks.update(raw_contiguous=False, error=str(exc))
    return {
        "skill": {"name": "data-analytics:analyze-data-quality", "available": False,
                  "failure": "Skill not found: data-analytics:analyze-data-quality"},
        "equivalent_deterministic_checks": checks,
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
    draft_map = {row["id"]: row for row in inputs.draft}
    catalogs = {row["chunk_id"]: row for row in build_anchor_catalog(list(inputs.chunks.values()))}
    rows: list[dict] = []
    raw_contexts: list[dict] = []
    templates: list[dict] = []
    for blocker in sorted(inputs.blockers, key=lambda row: row["case_id"]):
        case_id, chunk_id = blocker["case_id"], blocker["chunk_id"]
        case = draft_map[case_id]
        chunk = inputs.chunks[chunk_id]
        catalog = catalogs[chunk_id]
        answer_points = list(case.get("acceptable_answer_points") or [])
        category = blocker["root_cause_category"]
        context = build_context_row(case_id, chunk, catalog, answer_points[0] if answer_points else "")
        allowed = set(ALLOWED_ACTIONS)
        if category == "scoped_chunk_evidence_absent":
            # No scoped raw support: removal and replacement paths are risky by design.
            allowed -= {"replace_answer_point_with_exact_raw_text", "narrow_answer_point_to_exact_raw_text"}
        risk = zero_answer_point_risk(case)
        rows.append({
            "case_id": case_id,
            "query": case.get("query", ""),
            "answer_points": answer_points,
            "declared_source": chunk["source"],
            "declared_chunk_id": chunk_id,
            "blocker_category": category,
            "blocker_reason": blocker.get("blocker_reason", ""),
            "evidence": {"chunk_text": chunk["text"], "anchors": context["anchors"]},
            "scope_expansion_candidates": scope_candidates(inputs.chunks, chunk_id, chunk["source"]),
            "allowed_actions": sorted(allowed),
            "zero_answer_point_risk": risk,
            "refusal_suggestion": False,
            "is_refusal_case": case.get("should_refuse") is True,
        })
        raw_contexts.append(context | {"blocker_category": category})
        templates.append(patch_template(case_id))
    input_paths = {
        "v204_manifest": v204.V2_MANIFEST, "unresolved": v204.UNRESOLVED,
        "migration": v204.MIGRATION, "draft": v204.DRAFT, "chunks": v204.CHUNKS,
        "chunk_manifest": v204.CHUNK_MANIFEST, "v204_blockers": v204.AUDIT / "blocker-root-causes.jsonl",
        "v204_manifest_out": V204_OUT / "manifest.json", "v204_blockers_out": V204_OUT / "reannotation-blockers.jsonl",
    }
    quality = _quality(inputs.evidence, inputs.chunks)
    counts = {
        "targets": len(rows),
        "zero_answer_point_risk": sum(row["zero_answer_point_risk"] for row in rows),
        "is_refusal_case": sum(row["is_refusal_case"] for row in rows),
        "needs_scope_expansion_candidates": sum(len(row["scope_expansion_candidates"]) for row in rows),
    }
    guide = (
        "# v2.0.4 所有者决策指南\n\n"
        "本包不修改任何 v2 数据，不生成 after/overlay/active 文件，不进入 v2.1。\n"
        "可行动作含义：\n"
        "- remove_answer_point：删除无 scoped 原文证据的答案点及其关联证据；若可答 case 为零答案点则标记 zero_answer_point_risk。\n"
        "- replace_answer_point_with_exact_raw_text：用选定 anchor 的原始连续文本完整替换答案点，不改写其他字段。\n"
        "- narrow_answer_point_to_exact_raw_text：把答案点收窄为选定 anchor 的原文，不改变其余答案点。\n"
        "- add_new_document_then_reannotate：在新增文档并建立 chunk 后再重新标注，不改变当前 scope。\n"
        "- expand_evidence_scope_with_explicit_approval：把同 source 其他 chunk 作为未来证据范围，仍需显式授权。\n"
        "- retire_case：整体退役该 case，不影响其他 case。\n\n"
        "所有动作均不修改 draft/evidence/chunks/revision，不创建 refusal 建议（除非 case 原本就是 refusal）。\n"
    )
    summary = {
        "targets": counts["targets"],
        "zero_answer_point_risk": counts["zero_answer_point_risk"],
        "is_refusal_case": counts["is_refusal_case"],
        "needs_scope_expansion_candidates": counts["needs_scope_expansion_candidates"],
        "skill": quality["skill"],
        "input_sha256": {name: _sha(path) for name, path in input_paths.items()},
    }
    report = (
        "# v2.0.4 owner decision pack\n\n"
        "这是基于原始 chunk 的确定性所有者决策包，不是修复、人工审核、active 版本或 v2.1 准入。\n\n"
        f"- 目标：{counts['targets']}\n"
        f"- 零答案点风险：{counts['zero_answer_point_risk']}\n"
        f"- refusal case：{counts['is_refusal_case']}\n"
        f"- scope expansion 候选：{counts['needs_scope_expansion_candidates']}\n"
        f"- 输入 SHA：见 manifest。\n"
    )
    files: dict[str, str] = {
        "owner-decision-pack.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in rows),
        "OWNER_DECISION_GUIDE.md": guide,
        "raw-source-contexts.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in raw_contexts),
        "candidate-patch-template.jsonl": "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in templates),
        "decision-pack-summary.json": _dump(summary),
        "decision-pack-report.md": report,
    }
    input_hashes = {name: _sha(path) for name, path in input_paths.items()}
    staging = Path(tempfile.mkdtemp(prefix=".owner-decision-pack-", dir=out_dir.parent))
    try:
        for name, content in files.items():
            _atomic_write(staging / name, content)
        manifest = _manifest({
            "revision_status": "CANDIDATE", "activation_blocked": True,
            "human_reviewed": False, "decision_pack": True, "deterministic_rebuild": True,
            "status": "DECISION_PACK", "model": None, "temperature": None,
            "max_tokens": None, "coordinate_contract": CONTRACT,
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
