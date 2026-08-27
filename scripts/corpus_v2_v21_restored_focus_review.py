"""v2.1 恢复案例密封复核 — 验证轮执行器。

预注册：plans/V21-RESTORED-CASES-VERIFICATION-PREREGISTRATION-2026-08-27.md
（先于任何复核调用签署；§三判定映射锁死）。

owner 已基于机械包含证据推翻 targeted-review 对 zh-023 / multi-012 /
mixed-022 的驳回（rulings 账本 disposition=restored_pending_verification）。
本流程用与其契约聚焦盲审（zh-040，已获 owner 授权路线背书）同级的独立
密封复核作为权威裁决器：「盲审结果为准」。

与 corpus_v2_v21_contract_focus_review 的唯一结构差异：
- 目标集过滤 disposition=restored_pending_verification；
- gate 词表 RESTORED_VERIFICATION_OK / _BLOCKED；
- 盲态禁词增加治理语义词（restored/推翻/owner_decision）。
判定映射：3/3 confirmed → OK；任一分歧 → BLOCKED（零改写，产物留档）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import corpus_v2_v21_contract_focus_review as base_flow  # noqa: E402
from scripts import corpus_v2_v209_fresh_blind_automated_review as base  # noqa: E402
from scripts import corpus_v2_v211_targeted_remaining22_review as rv  # noqa: E402

V21_RULINGS_DIR = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.1-owner-rulings-batch1"
DEFAULT_OUT = V21_RULINGS_DIR / "restored-focus-review"

TIMESTAMP = "2026-08-27T00:00:00+00:00"
RULE_VERSION = "v2.1-restored-focus-review-1"
ACTOR = "OWNER_AUTHORIZED_V21_RESTORED_FOCUS_REVIEW"
GATE_OK = "RESTORED_VERIFICATION_OK"
GATE_BLOCKED = "RESTORED_VERIFICATION_BLOCKED"
EXPECTED_TARGET_COUNT = 3
DISPOSITION_FILTER = "restored_pending_verification"

# 治理语义词在 query 中同样不允许出现（support_spec 豁免同前）
GOVERNANCE_BANNED_WORDS = (*base_flow.CONTRACT_BANNED_WORDS,
                           "restored", "推翻", "owner_decision",
                           "pending", "待验证")

MODEL = rv.MODEL
TEMPERATURE = rv.TEMPERATURE
MAX_RETRIES = rv.MAX_RETRIES


class RestoredReviewError(RuntimeError):
    """fail-closed：预检异常时不产出任何确认口径结论。"""


def target_set() -> list[str]:
    ledger_path = V21_RULINGS_DIR / "rulings-ledger.jsonl"
    rows = [json.loads(l) for l in
            ledger_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    ids = sorted(r["case_id"] for r in rows
                 if r.get("disposition") == DISPOSITION_FILTER)
    if len(ids) != EXPECTED_TARGET_COUNT:
        raise RestoredReviewError(
            f"target set from rulings != {EXPECTED_TARGET_COUNT}: {ids}")
    return ids


def load_inputs() -> dict:
    try:
        checks = rv.preflight()
    except base.ReviewError as exc:
        raise RestoredReviewError(f"candidate preflight failed: {exc}") from exc
    ids = target_set()
    missing = [cid for cid in ids if cid not in checks["by_id"]]
    if missing:
        raise RestoredReviewError(f"target cases missing in draft: {missing}")
    checks["target_set"] = ids
    return checks


def build_blind_payload(checks: dict, case_id: str) -> dict:
    payload = base.build_payload(checks["by_id"][case_id],
                                 checks["ev_per_case"].get(case_id, []),
                                 checks["chunks"])
    base.scan_payload(payload)
    value = json.dumps(payload.get("query", ""), ensure_ascii=False).lower()
    for word in GOVERNANCE_BANNED_WORDS:
        if word.lower() in value:
            raise RestoredReviewError(
                f"payload query contains banned word {word!r}")
    return payload


_client = staticmethod(lambda messages: rv._real_client(messages))


def run(*, out_dir: Path = DEFAULT_OUT) -> dict:
    """完整验证轮：预检 → 盲态 payload → 逐案复核 → 判定映射 → 产物。

    判定映射为预注册 §三 锁死形态：任一非 confirmed ⇒ 整体 BLOCKED，
    不允许部分采纳混入 OK 口径。
    """
    if out_dir.exists():
        raise RestoredReviewError(
            f"review output directory already exists: {out_dir}")
    checks = load_inputs()
    target = checks["target_set"]
    payloads = {cid: build_blind_payload(checks, cid) for cid in target}

    try:
        probe_result = base.probe(_client)
    except Exception as exc:
        raise RestoredReviewError(f"probe failed: {exc}") from exc

    results = {}
    for cid in sorted(payloads):
        try:
            results[cid] = base.review_case(cid, payloads[cid], _client)
        except base.ReviewError as exc:
            results[cid] = {"case_id": cid, "decision": "error",
                            "error": str(exc), "attempts": MAX_RETRIES + 1}

    confirmed = sum(1 for r in results.values()
                    if r["decision"] == "confirmed")
    gate = GATE_OK if confirmed == len(results) else GATE_BLOCKED
    manifest = _write_outputs(out_dir, checks, results, gate)
    return {"gate_verdict": gate, "counts": manifest["counts"],
            "out_dir": out_dir, "probe": probe_result}


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
    rows = []
    for cid in sorted(results):
        r = results[cid]
        row = {"case_id": cid, "rewritten": False,
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
        rows.append(row)

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
        "frozen_revision": base_flow.FROZEN.name,
        "gate_verdict": gate,
        "input_shas": {
            "rulings-ledger.jsonl":
                base_flow._sha256_file(V21_RULINGS_DIR / "rulings-ledger.jsonl"),
            "candidate-manifest.json":
                checks["manifest"].get("manifest_sha256", ""),
        },
        "preregistration":
            "plans/V21-RESTORED-CASES-VERIFICATION-PREREGISTRATION-2026-08-27.md",
        "rule_version": RULE_VERSION,
        "run_at": TIMESTAMP,
        "skill_note": base_flow.SKILL_NOTE,
        "task": "v2.1-restored-focus-review",
    }
    manifest = base_flow._manifest(body)
    out_dir.mkdir(parents=True)
    (out_dir / "restored-review-results.jsonl").write_text(
        "".join(base_flow._line(r) + "\n" for r in rows),
        encoding="utf-8", newline="\n")
    summary = {"gate_verdict": gate, "counts": counts,
               "rule_version": RULE_VERSION, "run_at": TIMESTAMP}
    (out_dir / "restored-review-summary.json").write_text(
        base_flow._dump(summary), encoding="utf-8", newline="\n")
    (out_dir / "manifest.json").write_text(base_flow._dump(manifest),
                                           encoding="utf-8", newline="\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    try:
        result = run(out_dir=args.out_dir)
    except RestoredReviewError as exc:
        print(f"FAIL-CLOSED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"gate_verdict": result["gate_verdict"],
                      "counts": result["counts"],
                      "out_dir": str(result["out_dir"])},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
