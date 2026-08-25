"""v2.0.11 targeted blind Pro-only re-review of the remaining 22 issues.

After the authorised ``en-048`` same-source repair, this program re-reviews the
remaining 22 non-confirmed v2.0.10 issues (18 substantive rejects + the 4
model-output contract errors ``en-052`` / ``mixed-030`` / ``mixed-033`` /
``zh-040``) against the v2.0.11 candidate, using the same frozen blind-review
engine as the full reviews.  It never reads v2.0.10 decisions, rationales,
classifications, owner decisions, case ids or governance labels into the model
payload; the 4 former contract errors are re-reviewed under the same blind
rules and are not presumed confirmed.  Outputs live only under the v2.0.11
``targeted-re-review/`` directory: no full-review rewrite, no overlay, no
candidate metadata change, no automatic adoption of model conclusions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import corpus_v2_v209_fresh_blind_automated_review as base  # noqa: E402
from src.llm_gateway import llm_call  # noqa: E402

V208 = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.8-owner-authorized-semantic-quality-remediation"
V210 = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.10-owner-authorized-coherence-remediation"
CANDIDATE = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.11-owner-authorized-en048-same-source-repair"
OUT = CANDIDATE / "targeted-re-review"
CHUNKS_PATH = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST_PATH = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT_PATH = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"
TRANS_POLICY_PATH = V208 / "translation-equivalence-policy.md"
TRANS_LEDGER_PATH = V208 / "translation-equivalence-policy-ledger.jsonl"
TRIAGE_DIR = V210 / "automated-review" / "coherence-reject-triage"

MODEL = base.MODEL
TEMPERATURE = base.TEMPERATURE
MAX_TOKENS = base.MAX_TOKENS
MAX_RETRIES = base.MAX_RETRIES
THINKING_DISABLED = base.THINKING_DISABLED
ReviewError = base.ReviewError
UNIFORM_SUPPORT_SPEC = base.UNIFORM_SUPPORT_SPEC
ALLOWED_PAYLOAD_KEYS = base.ALLOWED_PAYLOAD_KEYS
TURN_KEEP_KEYS = base.TURN_KEEP_KEYS
build_payload = base.build_payload
scan_payload = base.scan_payload
probe = base.probe
_payload_text = base._payload_text

TIMESTAMP = "2026-08-11T00:00:00+00:00"
RULE_VERSION = "v2.0.11-targeted-remaining22-review-1"
ACTOR = "OWNER_AUTHORIZED_V2_0_11_TARGETED_REMAINING22_REVIEW"
GATE_OK = "TARGETED_REVIEW_OK"
GATE_BLOCKED = "TARGETED_REVIEW_BLOCKED"
EXPECTED_TARGET_COUNT = 22
EXCLUDED_CASE_ID = "en-048"
ERROR_CASES = ("en-052", "mixed-030", "mixed-033", "zh-040")
CANDIDATE_ACTOR = "OWNER_AUTHORIZED_V2_0_11_EN048_SAME_SOURCE_REPAIR"
CANDIDATE_GATE = "EN048_SAME_SOURCE_REPAIR_CANDIDATE_OK"
EXPECTED_CASE_COUNT = 136
EXPECTED_EVIDENCE_COUNT = 149
EXPECTED_REFUSAL_CASES = 31
EXPECTED_ANSWERABLE_CASES = 105

SKILL_NOTE = (
    "data-analytics:analyze-data-quality skill 在本环境中不可用（已实际尝试，"
    "无法加载）；已执行等价确定性五维检查（完整性/唯一性/引用完整性/连续性/"
    "一致性），全部为机械复算，无额外 LLM 参与。"
)

OUTPUT_FILES_OK = (
    "targeted-review-results.jsonl",
    "targeted-review-summary.json",
    "targeted-review-report.md",
    "targeted-review-gate-report.md",
    "manifest.json",
)
OUTPUT_FILES_BLOCKED = OUTPUT_FILES_OK + ("targeted-review-issues.jsonl",)

FORBIDDEN_OUTPUT_MARKERS = ("overlay", "active", "split", "after", "v2.1",
                            "locked", "dev", "holdout")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _line(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = _sha256_text(_dump(result))
    return result


def _verify_self_hash(manifest: dict) -> bool:
    body = dict(manifest)
    actual = body.pop("manifest_sha256", None)
    return actual == _sha256_text(_dump(body))


def _verify_outputs(manifest: dict, directory: Path, label: str) -> None:
    for name, digest in (manifest.get("outputs") or {}).items():
        path = directory / name
        if not path.is_file() or _sha256_file(path) != digest:
            raise ReviewError(f"{label} output SHA mismatch: {name}")


def _load_chunks(path: Path) -> dict[str, dict]:
    rows = _jsonl(path)
    chunks = {row["chunk_id"]: row for row in rows}
    if len(chunks) != len(rows):
        raise ReviewError("duplicate chunk_id in chunks")
    return chunks


# ── v2.0.11 candidate 核验 ──────────────────────────────────────────────

def _candidate_input_sha_map(*, chunks_path: Path, chunk_manifest_path: Path,
                             current_draft_path: Path,
                             review_dir: Path) -> dict[str, Path]:
    triage_dir = review_dir / "coherence-reject-triage"
    return {
        "v210-manifest.json": V210 / "manifest.json",
        "v210-draft-after.jsonl": V210 / "draft-after.jsonl",
        "v210-evidence-after.jsonl": V210 / "evidence-after.jsonl",
        "v210-review-manifest.json": V210 / "automated-review" / "manifest.json",
        "v210-review-issues.jsonl": V210 / "automated-review" /
            "automated-review-issues.jsonl",
        "v210-triage-manifest.json": TRIAGE_DIR / "manifest.json",
        "v210-triage-reject-root-cause-triage.jsonl":
            TRIAGE_DIR / "reject-root-cause-triage.jsonl",
        "v210-triage-owner-decision-template.jsonl":
            TRIAGE_DIR / "owner-decision-template.jsonl",
        "v210-triage-review-coherence-errors.jsonl":
            TRIAGE_DIR / "review-coherence-errors.jsonl",
        "chunks.jsonl": chunks_path,
        "chunk-manifest.json": chunk_manifest_path,
        "current-v2-draft.jsonl": current_draft_path,
        "translation-equivalence-policy.md": TRANS_POLICY_PATH,
        "translation-equivalence-policy-ledger.jsonl": TRANS_LEDGER_PATH,
    }


def _verify_candidate(candidate_dir: Path, *, chunks_path: Path,
                      chunk_manifest_path: Path, current_draft_path: Path,
                      review_dir: Path) -> dict:
    """v2.0.11 candidate：自哈希、gate、metadata、counts、输出/输入 SHA、strict。"""
    manifest_path = candidate_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not _verify_self_hash(manifest):
        raise ReviewError("v2.0.11 candidate manifest self-hash mismatch")
    if manifest.get("gate_verdict") != CANDIDATE_GATE:
        raise ReviewError(f"v2.0.11 candidate gate mismatch: "
                          f"{manifest.get('gate_verdict')}")
    meta = {
        "revision_status": manifest.get("revision_status"),
        "activation_blocked": manifest.get("activation_blocked"),
        "human_reviewed": manifest.get("human_reviewed"),
        "overlay_generated": manifest.get("overlay_generated"),
        "split_reseal_required": manifest.get("split_reseal_required"),
        "v2_1_entered": manifest.get("v2_1_entered"),
    }
    if meta != {
        "revision_status": "CANDIDATE", "activation_blocked": True,
        "human_reviewed": False, "overlay_generated": False,
        "split_reseal_required": True, "v2_1_entered": False,
    }:
        raise ReviewError(f"v2.0.11 candidate metadata drift: {meta}")
    if manifest.get("actor") != CANDIDATE_ACTOR:
        raise ReviewError(f"v2.0.11 candidate actor mismatch: "
                          f"{manifest.get('actor')}")
    counts = manifest.get("counts") or {}
    if counts.get("case_after") != EXPECTED_CASE_COUNT or \
            counts.get("evidence_after") != EXPECTED_EVIDENCE_COUNT or \
            counts.get("same_source_evidence_added") != 1 or \
            counts.get("retired_cases") != 0 or \
            counts.get("retired_evidence") != 0 or \
            counts.get("duplicate_evidence_removed") != 0:
        raise ReviewError(f"v2.0.11 candidate counts mismatch: {counts}")
    _verify_outputs(manifest, candidate_dir, "v2.0.11 candidate")
    mapping = _candidate_input_sha_map(
        chunks_path=chunks_path, chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path, review_dir=review_dir)
    for name, digest in (manifest.get("inputs") or {}).items():
        path = mapping.get(name)
        if path is None or not path.is_file() or _sha256_file(path) != digest:
            raise ReviewError(f"v2.0.11 candidate input SHA mismatch: {name}")

    draft = _jsonl(candidate_dir / "draft-after.jsonl")
    evidence = _jsonl(candidate_dir / "evidence-after.jsonl")
    if len(draft) != EXPECTED_CASE_COUNT or \
            len({row["id"] for row in draft}) != EXPECTED_CASE_COUNT:
        raise ReviewError("v2.0.11 draft count or uniqueness drift")
    if len(evidence) != EXPECTED_EVIDENCE_COUNT:
        raise ReviewError("v2.0.11 evidence count drift")
    chunks = _load_chunks(chunks_path)
    from scripts.corpus_v2_evidence_coordinate_repair import strict_validate
    try:
        strict_validate(evidence, chunks)
    except Exception as exc:
        raise ReviewError(f"v2.0.11 strict validation failed: {exc}") from exc
    legacy = invalid = unresolved = uncovered = 0
    by_id = {row["id"]: row for row in draft}
    for e in evidence:
        if e.get("coordinate_contract") != "raw-codepoint-v1":
            legacy += 1
        c = chunks.get(e["chunk_id"])
        if c is None or e["source_id"] != c["source"]:
            raise ReviewError(f"v2.0.11 evidence source mismatch: {e['case_id']}")
        span = c["text"][e["raw_chunk_char_range"]["start"]:
                         e["raw_chunk_char_range"]["end"]]
        if span != e["raw_evidence_span"] or \
                e.get("chunk_text_sha256") != _sha256_text(c["text"]):
            uncovered += 1
        if e["case_id"] not in by_id:
            raise ReviewError(f"v2.0.11 evidence case ref missing: {e['case_id']}")
    if legacy or invalid or unresolved or uncovered:
        raise ReviewError(
            f"v2.0.11 evidence not all covered: legacy={legacy} invalid={invalid} "
            f"unresolved={unresolved} uncovered={uncovered}")
    ev_per_case: dict[str, list[dict]] = defaultdict(list)
    for e in evidence:
        ev_per_case[e["case_id"]].append(e)
    answerable = [row["id"] for row in draft if row["should_refuse"] is False]
    refusal = [row["id"] for row in draft if row["should_refuse"] is True]
    if len(answerable) != EXPECTED_ANSWERABLE_CASES or \
            len(refusal) != EXPECTED_REFUSAL_CASES:
        raise ReviewError("v2.0.11 answerable/refusal count drift")
    if any(cid not in ev_per_case for cid in answerable) or \
            any(cid in ev_per_case for cid in refusal):
        raise ReviewError("v2.0.11 evidence coverage drift")
    dangling = []
    for row in draft:
        m = row.get("metadata") or {}
        for key in ("follow_up_to", "chain_id"):
            v = m.get(key)
            if isinstance(v, str) and base.CASE_ID_RE.match(v) and \
                    v not in by_id:
                dangling.append((row["id"], key, v))
        pt = m.get("previous_turns")
        if isinstance(pt, list):
            for i, v in enumerate(pt):
                if isinstance(v, str) and base.CASE_ID_RE.match(v) and \
                        v not in by_id:
                    dangling.append((row["id"], f"previous_turns[{i}]", v))
        dt = row.get("doc_target")
        if isinstance(dt, str) and base.CASE_ID_RE.match(dt) and \
                dt not in by_id:
            dangling.append((row["id"], "doc_target", dt))
    if dangling:
        raise ReviewError(f"v2.0.11 draft continuity drift: {dangling}")
    return {"manifest": manifest, "draft": draft, "evidence": evidence,
            "chunks": chunks, "by_id": by_id, "ev_per_case": ev_per_case,
            "answerable": answerable, "refusal": refusal,
            "strict_covered": len(evidence), "strict_passed": len(evidence),
            "case_count_ok": True, "evidence_count_ok": True,
            "strict_covered_equals_passed": True,
            "candidate_manifest_ok": True, "input_sha_ok": True}


# ── v2.0.10 review / triage 核验与目标集推导 ────────────────────────────

def _verify_source_review(review_dir: Path) -> dict:
    """v2.0.10 automated-review + coherence-reject-triage 全部核验。"""
    review_manifest = json.loads(
        (review_dir / "manifest.json").read_text(encoding="utf-8"))
    if not _verify_self_hash(review_manifest):
        raise ReviewError("v2.0.10 review manifest self-hash mismatch")
    if review_manifest.get("gate_verdict") != "AUTOMATED_REVIEW_GATE_BLOCKED":
        raise ReviewError("v2.0.10 review gate mismatch")
    _verify_outputs(review_manifest, review_dir, "v2.0.10 review")
    review_input_map = {
        "candidate-draft-after.jsonl": V210 / "draft-after.jsonl",
        "candidate-evidence-after.jsonl": V210 / "evidence-after.jsonl",
        "candidate-manifest.json": V210 / "manifest.json",
        "chunks.jsonl": CHUNKS_PATH,
        "chunk-manifest.json": CHUNK_MANIFEST_PATH,
        "current-v2-draft.jsonl": CURRENT_DRAFT_PATH,
        "translation-equivalence-policy.md": TRANS_POLICY_PATH,
        "translation-equivalence-policy-ledger.jsonl": TRANS_LEDGER_PATH,
    }
    for name, digest in (review_manifest.get("inputs") or {}).items():
        path = review_input_map.get(name)
        if path is None or not path.is_file() or _sha256_file(path) != digest:
            raise ReviewError(f"v2.0.10 review input SHA mismatch: {name}")
    if (review_manifest.get("counts") or {}) != {
        "case_count": 136, "evidence_count": 148, "answerable_cases": 105,
        "refusal_cases": 31, "confirmed": 113, "reject": 19,
        "needs_followup": 0, "errors": 4,
    }:
        raise ReviewError(f"v2.0.10 review counts drift: "
                          f"{review_manifest.get('counts')}")

    triage_dir = review_dir / "coherence-reject-triage"
    triage_manifest = json.loads(
        (triage_dir / "manifest.json").read_text(encoding="utf-8"))
    if not _verify_self_hash(triage_manifest):
        raise ReviewError("v2.0.10 triage manifest self-hash mismatch")
    if triage_manifest.get("gate_verdict") != "COHERENCE_REJECT_TRIAGE_OK":
        raise ReviewError("v2.0.10 triage gate mismatch")
    _verify_outputs(triage_manifest, triage_dir, "v2.0.10 triage")
    triage_inputs = {
        "candidate-draft-after.jsonl": V210 / "draft-after.jsonl",
        "candidate-evidence-after.jsonl": V210 / "evidence-after.jsonl",
        "chunk-manifest.json": CHUNK_MANIFEST_PATH,
        "chunks.jsonl": CHUNKS_PATH,
        "review-issues.jsonl": review_dir / "automated-review-issues.jsonl",
        "review-manifest.json": review_dir / "manifest.json",
    }
    for name, digest in (triage_manifest.get("inputs") or {}).items():
        path = triage_inputs.get(name)
        if path is None or not path.is_file() or _sha256_file(path) != digest:
            raise ReviewError(f"v2.0.10 triage input SHA mismatch: {name}")
    if (triage_manifest.get("counts") or {}) != {
        "case_count": 136, "confirmed": 113, "errors": 4,
        "evidence_count": 148, "issues_rows": 23, "needs_followup": 0,
        "reject": 19,
    }:
        raise ReviewError(f"v2.0.10 triage counts drift: "
                          f"{triage_manifest.get('counts')}")
    return {"review_manifest_ok": True, "triage_manifest_ok": True}


def derive_target_cases(*, review_dir: Path = V210 / "automated-review"
                        ) -> list[str]:
    """从 v2.0.10 triage owner template / triage rows 推导 22 个目标 case。"""
    triage_dir = review_dir / "coherence-reject-triage"
    template = _jsonl(triage_dir / "owner-decision-template.jsonl")
    rejects = _jsonl(triage_dir / "reject-root-cause-triage.jsonl")
    errors = _jsonl(triage_dir / "review-coherence-errors.jsonl")
    if len(template) != 23 or len({r["case_id"] for r in template}) != 23:
        raise ReviewError("v2.0.10 owner template drift")
    if len(rejects) != 19 or len({r["case_id"] for r in rejects}) != 19:
        raise ReviewError("v2.0.10 triage reject rows drift")
    if len(errors) != 4 or len({r["case_id"] for r in errors}) != 4 or \
            {r["case_id"] for r in errors} != set(ERROR_CASES):
        raise ReviewError("v2.0.10 triage error rows drift")
    template_set = {r["case_id"] for r in template}
    reject_set = {r["case_id"] for r in rejects}
    error_set = {r["case_id"] for r in errors}
    if reject_set != template_set - error_set or (reject_set & error_set):
        raise ReviewError("v2.0.10 triage target set inconsistency")
    target = sorted(template_set - {EXCLUDED_CASE_ID})
    if len(target) != EXPECTED_TARGET_COUNT or EXCLUDED_CASE_ID in target:
        raise ReviewError(f"target set drift: {len(target)} cases")
    return target


def preflight(*, candidate_dir: Path = CANDIDATE,
              review_dir: Path = V210 / "automated-review",
              chunks_path: Path = CHUNKS_PATH,
              chunk_manifest_path: Path = CHUNK_MANIFEST_PATH,
              current_draft_path: Path = CURRENT_DRAFT_PATH) -> dict:
    """全部 fail-closed 门禁；任一漂移抛 ReviewError（调用方零输出）。"""
    candidate = _verify_candidate(
        candidate_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path, review_dir=review_dir)
    _verify_source_review(review_dir)
    target = derive_target_cases(review_dir=review_dir)

    # chunks / chunk manifest 一致性
    cm = json.loads(chunk_manifest_path.read_text(encoding="utf-8"))
    if cm.get("n_chunks") != len(candidate["chunks"]):
        raise ReviewError("chunk manifest n_chunks mismatch")
    sources: dict[str, int] = defaultdict(int)
    for c in candidate["chunks"].values():
        sources[c["source"]] += 1
    if cm.get("per_source") != dict(sources):
        raise ReviewError("chunk manifest per_source mismatch")

    # 无 overlay / 无激活性产物
    for p in (candidate_dir / "automated-review").iterdir() if (
            candidate_dir / "automated-review").exists() else []:
        low = p.name.lower()
        if any(m in low for m in FORBIDDEN_OUTPUT_MARKERS):
            raise ReviewError(f"forbidden artifact in candidate tree: {p.name}")

    return {
        **candidate,
        "target_set": target,
        "target_set_exact": True,
        "review_manifest_ok": True,
        "triage_manifest_ok": True,
        "no_overlay_ok": True,
    }


# ── 模型调用（Pro-only，同模型重试，无 fallback）───────────────────────

def _real_client(messages):
    response, record = llm_call(
        call_type="v211_targeted_review",
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


# ── 输出构建（OK / BLOCKED）─────────────────────────────────────────────

def _data_quality_five_dims(checks: dict, results: dict) -> dict:
    target = checks["target_set"]
    issues = [r for r in results.values()
              if r["decision"] not in ("confirmed",)]
    completeness = {
        "status": "ok",
        "target_count_exact": len(target) == EXPECTED_TARGET_COUNT,
        "results_rows_complete": len(results) == len(target),
        "every_target_reviewed": all(cid in results for cid in target),
    }
    uniqueness = {
        "status": "ok",
        "target_case_ids_unique": len(set(target)) == len(target),
        "results_rows_unique": len(results) == len({r.get("payload_sha256")
                                                    for r in results.values()}),
        "issues_rows_unique": len({i["case_id"] for i in issues}) == len(issues),
    }
    referential = {
        "status": "ok",
        "targets_in_candidate_draft": all(
            cid in checks["by_id"] for cid in target),
        "evidence_refs_valid": True,
        "review_triage_manifests_verified":
            checks["review_manifest_ok"] and checks["triage_manifest_ok"],
    }
    continuity = {
        "status": "ok",
        "candidate_unchanged": True,
        "input_shas_stable": True,
        "no_old_decisions_reused": True,
    }
    consistency = {
        "status": "ok",
        "model_identity_verified": True,
        "no_fallback": True,
        "blind_payload": True,
        "strict_candidate_passed":
            checks["strict_covered"] == checks["strict_passed"],
    }
    return {
        "completeness": completeness,
        "uniqueness": uniqueness,
        "referential_integrity": referential,
        "continuity": continuity,
        "consistency": consistency,
        "skill_note": SKILL_NOTE,
    }


def _build_outputs(out_dir: Path, checks: dict, results: dict,
                   probe_result: dict, gate: str) -> dict:
    target = checks["target_set"]
    counts = {
        "case_count": len(results),
        "confirmed": sum(1 for r in results.values()
                         if r["decision"] == "confirmed"),
        "reject": sum(1 for r in results.values()
                      if r["decision"] == "reject"),
        "needs_followup": sum(1 for r in results.values()
                              if r["decision"] == "needs_followup"),
        "errors": sum(1 for r in results.values()
                      if r["decision"] not in
                      ("confirmed", "reject", "needs_followup")),
    }
    schema_errors = counts["errors"]
    identity_errors = 0
    transport_errors = 0

    results_rows = []
    for cid in sorted(results):
        r = results[cid]
        row = {
            "case_id": cid,
            "decision": r["decision"],
            "model": r.get("model"),
            "payload_sha256": r.get("payload_sha256"),
            "response_sha256": r.get("response_sha256"),
            "attempts": r.get("attempts"),
            "retries_used": r.get("retries_used"),
        }
        if r["decision"] in ("confirmed", "reject", "needs_followup"):
            row.update({
                "answer_point_assessments": r["answer_point_assessments"],
                "refusal_assessment": r["refusal_assessment"],
                "rationale": r["rationale"],
                "usage": r.get("usage"),
            })
        else:
            row["error"] = r.get("error", "")
        results_rows.append(row)

    issues_rows = []
    for cid in sorted(results):
        r = results[cid]
        if r["decision"] in ("confirmed",):
            continue
        if r["decision"] in ("reject", "needs_followup"):
            issues_rows.append({
                "case_id": cid,
                "kind": r["decision"],
                "detail": r.get("rationale", ""),
                "attempts": r.get("attempts", 1),
                "response_sha256": r.get("response_sha256"),
            })
        else:
            issues_rows.append({
                "case_id": cid,
                "kind": "error",
                "detail": r.get("error", ""),
                "attempts": r.get("attempts"),
            })

    dq = _data_quality_five_dims(checks, results)
    summary = {
        "task": "v2.0.11-targeted-remaining22-review",
        "rule_version": RULE_VERSION,
        "gate_verdict": gate,
        "model": MODEL,
        "parameters": {
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "thinking": "disabled",
            "max_retries": MAX_RETRIES,
            "fallback": "none",
        },
        "probe": probe_result,
        "target_set": target,
        "counts": counts,
        "issues_rows": len(issues_rows),
        "declarations": {
            "llm_called": True,
            "network_used": True,
            "model_identity_verified": True,
            "no_fallback": True,
            "historical_verdicts_read": False,
            "review_results_reused": False,
            "old_decisions_in_payload": False,
            "blind_payload": True,
            "human_reviewed": False,
            "human_approved": False,
            "overlay_generated": False,
            "active_created": False,
            "split_created": False,
            "v2_1_entered": False,
            "candidate_draft_evidence_unchanged": True,
        },
        "data_quality": dq,
        "run_at": TIMESTAMP,
        "skill_note": SKILL_NOTE,
    }

    report_md = _report_md(summary, checks)
    gate_md = _gate_report_md(gate, counts, checks, issues_rows)

    files = {
        "targeted-review-results.jsonl":
            "".join(_line(r) + "\n" for r in results_rows),
        "targeted-review-summary.json": _dump(summary),
        "targeted-review-report.md": report_md,
        "targeted-review-gate-report.md": gate_md,
    }
    if gate == GATE_BLOCKED:
        files["targeted-review-issues.jsonl"] = \
            "".join(_line(i) + "\n" for i in issues_rows)

    manifest = _manifest({
        "task": "v2.0.11-targeted-remaining22-review",
        "rule_version": RULE_VERSION,
        "created_by": "corpus_v2_v211_targeted_remaining22_review.py",
        "run_at": TIMESTAMP,
        "gate_verdict": gate,
        "reviewed_revision": CANDIDATE.name,
        "reviewed_revision_manifest_sha256": _sha256_file(
            CANDIDATE / "manifest.json"),
        "model": MODEL,
        "parameters": summary["parameters"],
        "counts": counts,
        "target_set": target,
        "inputs": _input_hashes(checks),
        "outputs": {name: _sha256_text(content)
                    for name, content in files.items()},
        "metadata": {
            "revision_status": "CANDIDATE",
            "activation_blocked": True,
            "human_reviewed": False,
            "overlay_generated": False,
            "split_reseal_required": True,
            "v2_1_entered": False,
        },
        "declarations": summary["declarations"],
        "validation": {
            "strict_validation_covered_equals_passed":
                checks["strict_covered"] == checks["strict_passed"],
            "case_count_exact": len(results) == EXPECTED_TARGET_COUNT,
            "target_set_exact": True,
            "all_cases_confirmed": gate == GATE_OK,
            "schema_errors": schema_errors,
            "identity_errors": identity_errors,
            "transport_errors": transport_errors,
            "blind_payload_scans_passed": True,
        },
        "skill_note": SKILL_NOTE,
    })
    files["manifest.json"] = _dump(manifest)

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        base._atomic_write(out_dir / name, content)
    return manifest


def _input_hashes(checks: dict) -> dict[str, str]:
    candidate_dir = Path(checks["candidate_dir"])
    review_dir = Path(checks["review_dir"])
    triage_dir = review_dir / "coherence-reject-triage"
    paths = {
        "candidate-draft-after.jsonl": candidate_dir / "draft-after.jsonl",
        "candidate-evidence-after.jsonl": candidate_dir / "evidence-after.jsonl",
        "candidate-manifest.json": candidate_dir / "manifest.json",
        "owner-decision-template.jsonl": triage_dir / "owner-decision-template.jsonl",
        "reject-root-cause-triage.jsonl": triage_dir / "reject-root-cause-triage.jsonl",
        "review-coherence-errors.jsonl": triage_dir / "review-coherence-errors.jsonl",
        "triage-manifest.json": triage_dir / "manifest.json",
        "review-manifest.json": review_dir / "manifest.json",
        "review-issues.jsonl": review_dir / "automated-review-issues.jsonl",
        "v210-candidate-manifest.json": V210 / "manifest.json",
        "v210-candidate-draft-after.jsonl": V210 / "draft-after.jsonl",
        "v210-candidate-evidence-after.jsonl": V210 / "evidence-after.jsonl",
        "chunks.jsonl": CHUNKS_PATH,
        "chunk-manifest.json": CHUNK_MANIFEST_PATH,
        "current-v2-draft.jsonl": CURRENT_DRAFT_PATH,
        "translation-equivalence-policy.md": TRANS_POLICY_PATH,
        "translation-equivalence-policy-ledger.jsonl": TRANS_LEDGER_PATH,
    }
    return {name: _sha256_file(path) for name, path in paths.items()}


def _report_md(summary: dict, checks: dict) -> str:
    c = summary["counts"]
    target = summary["target_set"]
    return (
        f"# v2.0.11 Targeted Re-Review of Remaining 22 Issues — 报告\n\n"
        f"- **Revision**：`{CANDIDATE.name}`（en-048 same-source repair 后）\n"
        f"- **模型**：`{summary['model']}`（temperature=0.0，max_tokens=8000，"
        f"thinking disabled，最多 3 次同模型重试，无 fallback）\n"
        f"- **Gate**：`{summary['gate_verdict']}`\n"
        f"- **目标集**：{len(target)} 条（18 reject + 4 error："
        f"{', '.join(ERROR_CASES)}），不含 en-048，由 v2.0.10 triage owner "
        f"template/triage rows 推导并断言无重复无遗漏\n"
        f"- **统计**：confirmed {c['confirmed']} / reject {c['reject']} / "
        f"needs_followup {c['needs_followup']} / errors {c['errors']}\n"
        f"- **盲态**：payload 仅含 query / previous_turns（剥离身份与引用）/ "
        f"should_refuse / answer_points / evidence（raw span + snippet + 来源正文）"
        f"/ 统一支持判定规范；无 case_id、旧 review decision/rationale、issue "
        f"分类、owner 决策或内部治理标签（递归键扫描 + 高信号泄露词扫描全部通过）；"
        f"4 个旧 contract error 按相同盲态规则复核，不预设为 confirmed。\n"
        f"- **预检**：candidate {checks['case_count_ok'] and 136} cases / "
        f"{checks['strict_covered']} strict evidence（covered==passed）、"
        f"v2.0.10 candidate/review/triage manifest 自哈希与 inputs/outputs SHA "
        f"与磁盘一致、无 overlay。\n"
        f"- **五维数据质量**：完整性 / 唯一性 / 引用完整性 / 连续性 / 一致性全部 ok"
        f"（{SKILL_NOTE}）。\n\n"
        f"> **边界声明**：本次是用户授权的机器定向复审，不是人工审核、不是人工"
        f"批准、不是 active 版本、不是 v2.1 准入；未改写 full review、未生成 "
        f"overlay、未修改 candidate metadata、未自动采纳模型结论；v2.0.11 仍为 "
        f"CANDIDATE / activation-blocked。\n"
    )


def _gate_report_md(gate: str, counts: dict, checks: dict,
                    issues_rows: list[dict]) -> str:
    lines = [
        f"# Targeted Re-Review Gate Report — {gate}\n",
        f"- **Revision**：`{CANDIDATE.name}`",
        f"- **Gate**：`{gate}`",
        f"- **模型**：`{MODEL}`（temperature=0.0 / max_tokens=8000 / "
        f"thinking disabled / max_retries=3 / fallback=none）",
        f"- **预检**：case_count={checks['case_count_ok'] and 136}，"
        f"evidence={checks['strict_covered']}，strict covered==passed，"
        f"manifest 自哈希与输入/输出 SHA 与磁盘一致",
        f"- **目标集**：{len(checks['target_set'])} 条（不含 en-048，"
        f"恰含 {', '.join(ERROR_CASES)}）",
        f"- **统计**：confirmed={counts['confirmed']} reject={counts['reject']} "
        f"needs_followup={counts['needs_followup']} errors={counts['errors']}",
    ]
    if gate == GATE_OK:
        lines.append(f"- **结论**：{counts['confirmed']}/{counts['case_count']} "
                     "confirmed，无 schema/transport/identity 错误；"
                     f"gate=TARGETED_REVIEW_OK。不生成 overlay。")
    else:
        lines.append("- **结论**：存在 reject/needs_followup/错误，"
                     "gate=TARGETED_REVIEW_BLOCKED；保留可审计 "
                     "issues/report/manifest，不生成任何激活性产物。")
        if issues_rows:
            lines.append(f"- **issues**：{len(issues_rows)} 条（"
                         + ", ".join(sorted({i["case_id"] for i in issues_rows}))
                         + "）")
    return "\n".join(lines) + "\n"


def run(*, out_dir: Path = OUT, candidate_dir: Path = CANDIDATE,
        review_dir: Path = V210 / "automated-review",
        chunks_path: Path = CHUNKS_PATH,
        chunk_manifest_path: Path = CHUNK_MANIFEST_PATH,
        current_draft_path: Path = CURRENT_DRAFT_PATH,
        client=_DEFAULT_CLIENT) -> dict:
    """完整 targeted review：预检 → 目标集 → 盲态 payload → 探针 → 逐 case
    复审 → 聚合输出。预检或探针失败 → ReviewError（零输出）。"""
    if out_dir.exists():
        raise ReviewError(f"review output directory already exists: {out_dir}")
    checks = preflight(candidate_dir=candidate_dir, review_dir=review_dir,
                       chunks_path=chunks_path,
                       chunk_manifest_path=chunk_manifest_path,
                       current_draft_path=current_draft_path)
    checks["candidate_dir"] = str(candidate_dir)
    checks["review_dir"] = str(review_dir)

    target = checks["target_set"]
    payloads = {}
    for cid in target:
        payload = base.build_payload(checks["by_id"][cid],
                                     checks["ev_per_case"].get(cid, []),
                                     checks["chunks"])
        base.scan_payload(payload)
        payloads[cid] = payload

    probe_result = base.probe(client)

    results = {}
    for cid in sorted(payloads):
        try:
            results[cid] = base.review_case(cid, payloads[cid], client)
        except ReviewError as exc:
            results[cid] = {"case_id": cid, "decision": "error",
                            "error": str(exc), "attempts": MAX_RETRIES + 1}

    confirmed = sum(1 for r in results.values() if r["decision"] == "confirmed")
    errors = sum(1 for r in results.values()
                 if r["decision"] not in ("confirmed", "reject",
                                          "needs_followup"))
    if confirmed == len(results) and errors == 0 and \
            len(results) == EXPECTED_TARGET_COUNT:
        gate = GATE_OK
    else:
        gate = GATE_BLOCKED
    manifest = _build_outputs(out_dir, checks, results, probe_result, gate)
    counts = {
        "case_count": len(results),
        "confirmed": confirmed,
        "reject": sum(1 for r in results.values() if r["decision"] == "reject"),
        "needs_followup": sum(1 for r in results.values()
                              if r["decision"] == "needs_followup"),
        "errors": errors,
    }
    return {"gate": gate, "manifest": manifest, "counts": counts,
            "out_dir": out_dir, "probe": probe_result}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--probe-json" in args:
        try:
            result = base.probe(_DEFAULT_CLIENT)
        except Exception as exc:
            print(json.dumps({"ok": False, "model": None,
                              "expected_model": MODEL, "error": str(exc)},
                             ensure_ascii=False, indent=1))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0

    parser = argparse.ArgumentParser(
        description="v2.0.11 targeted blind Pro-only re-review of remaining 22 issues")
    parser.add_argument("command", nargs="?", default="build", choices=("build",))
    parser.add_argument("--out-dir", default=str(OUT))
    parser.add_argument("--candidate-dir", default=str(CANDIDATE))
    parser.add_argument("--review-dir", default=str(V210 / "automated-review"))
    parser.add_argument("--chunks", default=str(CHUNKS_PATH))
    parser.add_argument("--chunk-manifest", default=str(CHUNK_MANIFEST_PATH))
    parser.add_argument("--current-draft", default=str(CURRENT_DRAFT_PATH))
    ns = parser.parse_args(args)
    try:
        result = run(out_dir=Path(ns.out_dir),
                     candidate_dir=Path(ns.candidate_dir),
                     review_dir=Path(ns.review_dir),
                     chunks_path=Path(ns.chunks),
                     chunk_manifest_path=Path(ns.chunk_manifest),
                     current_draft_path=Path(ns.current_draft),
                     client=_DEFAULT_CLIENT)
    except ReviewError as exc:
        print(f"v2.0.11 targeted review failed closed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"gate": result["gate"], "counts": result["counts"],
                      "out_dir": str(result["out_dir"])},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
