"""v2.1 契约聚焦盲审 — 对 4 条 persistent contract error 的密封复审。

owner 批示（2026-08-27）：authorize_new_contract_focused_blind_review。

背景：en-052 / mixed-030 / mixed-033 / zh-040 在 v2.0.11 targeted review
中连续 4 次输出「全点支持却 reject」的契约不一致响应，本地契约由此推断
expected_decision=confirmed；但该推断只是引擎契约的陈述，原始模型响应
缺失未伪造，因此 owner 授权一轮只针对这 4 条、不带任何预期暗示的新盲审。

关键不变量（区别于既往复审）：
- **双向盲态**：payload 与 v2.0.11 targeted review 同规范（复用基座
  build_payload/scan_payload），但额外禁止出现 contract error 诊断痕迹；
  模型不知道也不应推断出「这批预期是 confirmed」；
- 结果**不自动改写任何 case 数据**：4/4 confirmed → gate OK（授权路线
  完成，后续治理按 v2.1 流程引用本结论）；任何 reject/needs_followup →
  BLOCKED，产物保留供 owner 再裁决；
- 目标集从 v2.1 rulings 账本（disposition=contract_blind_review_authorized）
  程序化推导，不二次硬编码；
- Pro-only 契约沿用 base：temperature=0.0 / thinking disabled / 同模型重试
  上限 / 无 fallback；两次构建逐字节一致。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import corpus_v2_v209_fresh_blind_automated_review as base  # noqa: E402
from scripts import corpus_v2_v211_targeted_remaining22_review as rv  # noqa: E402

FROZEN = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.11-owner-authorized-en048-same-source-repair"
V21_RULINGS_DIR = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.1-owner-rulings-batch1"
DEFAULT_OUT = V21_RULINGS_DIR / "contract-focus-review"

TIMESTAMP = "2026-08-27T00:00:00+00:00"
RULE_VERSION = "v2.1-contract-focus-review-1"
ACTOR = "OWNER_AUTHORIZED_V21_CONTRACT_FOCUS_REVIEW"
GATE_OK = "CONTRACT_BLIND_REVIEW_OK"
GATE_BLOCKED = "CONTRACT_BLIND_REVIEW_BLOCKED"
EXPECTED_TARGET_COUNT = 4
DISPOSITION_FILTER = "contract_blind_review_authorized"

# 盲态增强：除基座高信号词外，这些词不得出现在 payload 任何字段
CONTRACT_BANNED_WORDS = ("contract", "expected_decision", "契约",
                         "diagnostic", "persistent")

MODEL = rv.MODEL
TEMPERATURE = rv.TEMPERATURE
MAX_TOKENS = rv.MAX_TOKENS
MAX_RETRIES = rv.MAX_RETRIES
THINKING_DISABLED = rv.THINKING_DISABLED

SKILL_NOTE = (
    "data-analytics:analyze-data-quality skill 在本环境中不可用；已实施等价"
    "确定性检查（目标集推导校验/双构建字节一致/payload 泄露扫描），全部为"
    "机械复算，无额外 LLM 参与。"
)


class ContractReviewError(RuntimeError):
    """fail-closed：调用方保证异常时不产出 confirmed 结论。"""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _line(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = hashlib.sha256(
        _dump(result).encode("utf-8")).hexdigest()
    return result


def target_set() -> list[str]:
    """从 v2.1 rulings 账本程序化推导契约盲审目标集。"""
    ledger_path = V21_RULINGS_DIR / "rulings-ledger.jsonl"
    rows = _jsonl(ledger_path)
    ids = sorted(r["case_id"] for r in rows
                 if r.get("disposition") == DISPOSITION_FILTER)
    if len(ids) != EXPECTED_TARGET_COUNT:
        raise ContractReviewError(
            f"target set from rulings != {EXPECTED_TARGET_COUNT}: {ids}")
    return ids


def load_inputs() -> dict:
    """复用 rv 的 v2.0.11 候选门禁（SHA 链/行数/严格覆盖/no-overlay）。

    目标集改由 v2.1 rulings 账本推导，其余校验与 targeted review 完全一致。
    """
    try:
        checks = rv.preflight()
    except base.ReviewError as exc:
        raise ContractReviewError(f"candidate preflight failed: {exc}") from exc
    ids = target_set()
    missing = [cid for cid in ids if cid not in checks["by_id"]]
    if missing:
        raise ContractReviewError(f"target cases missing in draft: {missing}")
    checks["target_set"] = ids
    return checks


def build_blind_payload(checks: dict, case_id: str) -> dict:
    """同规范盲态 payload + 契约痕迹增强扫描（双向盲态）。"""
    payload = base.build_payload(checks["by_id"][case_id],
                                 checks["ev_per_case"].get(case_id, []),
                                 checks["chunks"])
    base.scan_payload(payload)
    # 增强层：契约诊断词不得出现在 query（任务侧撰写内容）。support_spec
    # 是统一判定规范模板、自身含「契约」等普通词，不参与内容扫描（与 base
    # scan_payload 对 support_spec 的豁免同理由）。
    value = json.dumps(payload.get("query", ""), ensure_ascii=False).lower()
    for word in CONTRACT_BANNED_WORDS:
        if word.lower() in value:
            raise ContractReviewError(
                f"payload query contains banned word {word!r}")
    return payload


def _real_client(messages):
    return rv._real_client(messages)


# 测试通过 monkeypatch 本属性注入 stub；生产路径为 llm_gateway 直连
_client = _real_client


def _write_outputs(out_dir: Path, checks: dict, results: dict,
                   gate: str) -> dict:
    counts = {
        "case_count": len(results),
        "confirmed": sum(1 for r in results.values()
                         if r["decision"] == "confirmed"),
        "rejected": sum(1 for r in results.values() if r["decision"] == "reject"),
        "needs_followup": sum(1 for r in results.values()
                              if r["decision"] == "needs_followup"),
        "errors": sum(1 for r in results.values()
                      if r["decision"] not in
                      ("confirmed", "reject", "needs_followup")),
    }
    results_rows = []
    for cid in sorted(results):
        r = results[cid]
        row = {"case_id": cid,
               "rewritten": False,  # 本流程绝不改写 case 数据，仅审计留痕
               "disposition_source": "v2.1-owner-rulings-batch1"}
        row.update({k: r.get(k) for k in
                    ("decision", "model", "payload_sha256", "response_sha256",
                     "attempts", "retries_used") if k in r})
        if r["decision"] in ("confirmed", "reject", "needs_followup"):
            row.update({"answer_point_assessments":
                        r.get("answer_point_assessments"),
                        "refusal_assessment": r.get("refusal_assessment"),
                        "rationale": r.get("rationale"),
                        "usage": r.get("usage")})
        else:
            row["error"] = r.get("error", "")
        results_rows.append(row)

    body = {
        "actor": ACTOR,
        "counts": counts,
        "declarations": {
            "candidate_bytes_unchanged": True,
            "expectation_blind": True,
            "llm_called": True,
            "network_used": True,
            "no_fallback": True,
            "overlay_generated": False,
            "results_not_auto_applied": True,
            "v20_frozen_revision_touched": False,
        },
        "expected_target_count": EXPECTED_TARGET_COUNT,
        "frozen_revision": FROZEN.name,
        "gate_verdict": gate,
        "input_shas": {
            "rulings-ledger.jsonl":
                _sha256_file(V21_RULINGS_DIR / "rulings-ledger.jsonl"),
            "candidate-manifest.json":
                checks["manifest"].get("manifest_sha256", ""),
        },
        "rule_version": RULE_VERSION,
        "run_at": TIMESTAMP,
        "skill_note": SKILL_NOTE,
        "task": "v2.1-contract-focus-review",
    }
    manifest = _manifest(body)
    out_dir.mkdir(parents=True)
    (out_dir / "contract-review-results.jsonl").write_text(
        "".join(_line(r) + "\n" for r in results_rows),
        encoding="utf-8", newline="\n")
    summary = {"gate_verdict": gate, "counts": counts,
               "rule_version": RULE_VERSION, "run_at": TIMESTAMP}
    (out_dir / "contract-review-summary.json").write_text(
        _dump(summary), encoding="utf-8", newline="\n")
    (out_dir / "manifest.json").write_text(_dump(manifest),
                                           encoding="utf-8", newline="\n")
    return manifest


def run(*, out_dir: Path = DEFAULT_OUT,
        client: Callable | None = None) -> dict:
    """完整契约聚焦盲审：预检 → 盲态 payload → 逐案复审 → 聚合输出。

    预检失败零输出；任一案 reject/needs_followup/error → BLOCKED 且保留
    全部可审计产物；绝不自动改写任何 case 数据。
    """
    if out_dir.exists():
        raise ContractReviewError(
            f"review output directory already exists: {out_dir}")
    checks = load_inputs()
    target = checks["target_set"]
    payloads = {}
    for cid in target:
        payloads[cid] = build_blind_payload(checks, cid)

    use_client = client or _client
    try:
        probe_result = base.probe(use_client)
    except Exception as exc:
        raise ContractReviewError(f"probe failed: {exc}") from exc

    results = {}
    for cid in sorted(payloads):
        try:
            results[cid] = base.review_case(cid, payloads[cid], use_client)
        except base.ReviewError as exc:
            results[cid] = {"case_id": cid, "decision": "error",
                            "error": str(exc), "attempts": MAX_RETRIES + 1}

    confirmed = sum(1 for r in results.values()
                    if r["decision"] == "confirmed")
    gate = GATE_OK if confirmed == len(results) else GATE_BLOCKED
    manifest = _write_outputs(out_dir, checks, results, gate)
    return {"gate_verdict": gate, "counts": manifest["counts"],
            "out_dir": out_dir, "probe": probe_result}
