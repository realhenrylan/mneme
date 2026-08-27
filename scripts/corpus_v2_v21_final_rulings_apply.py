"""v2.1 终裁批（batch2）apply —— owner 对 6 案终裁的治理账本落盘。

裁决链完整性：rulings-batch1（处置账本）→ 契约聚焦盲审（4 案执行）→
验证轮预注册 + restored-focus-review（3 案执行）→ 本工具按 owner 2026-08-27
终裁批示落最终状态。纯治理账本：不产出任何 overlay/active/draft/truth
改动；上游三件输入 SHA 快照门禁，漂移即零输出 fail-closed。

- verified_active ×2（zh-023 / multi-012）：机械包含证据与新鲜密封盲审
  两线一致 confirmed，owner 批示从 pending 升级 verified-active；
- retired_ambiguous_phrasing ×1（mixed-022）：答案点机械在场但新旧两轮
  模型一致 reject——本质为「用的是英文解释」命题双读歧义，退休归档，
  机械疑虑留档；
- retired_persistent_contract_error ×3（en-052 / mixed-030 / mixed-033）：
  契约聚焦盲审中三次独立复现「全点支持却输出 reject」，不再投入评审
  成本；产品线另立引擎侧修复项。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

V21_DIR = ROOT / "evaluation/datasets/v2/revisions" / "v2.1-owner-rulings-batch1"
DEFAULT_OUT = V21_DIR / "final-rulings-batch2"
PACK_TEMPLATE = ROOT / ("evaluation/datasets/v2/revisions/"
                        "v2.0.11-owner-authorized-en048-same-source-repair/"
                        "targeted-re-review/owner-decision-pack/"
                        "owner-decision-template.jsonl")

TIMESTAMP = "2026-08-27T00:00:00+00:00"
RULE_VERSION = "v2.1-final-rulings-apply-1"
ACTOR = "OWNER_AUTHORIZED_V21_FINAL_RULINGS_APPLY"
GATE_OK = "V21_FINAL_RULINGS_APPLY_OK"

EXPECTED_INPUT_SHAS: dict[str, str] = {
    "owner-decision-template.jsonl":
        "bf056ab25e58399635016ba21002c1222eb31f43811ec8079ae63b35c4001044",
    "rulings-ledger.jsonl":
        "b5eeefe7cd2fbcddf90f5e7e547c4231999cc90e149a8c993a635688afa92b08",
    "restored-review-results.jsonl":
        "b350f6c0d8367f9cfbcde862041119724765236cc53e985add9b4277db7bfc53",
    "contract-review-results.jsonl":
        "5eadd053b27a7cd24d07d819b7b03e3ddb6c14523664f6407f8bd301c7f951cf",
}

# owner 终裁（2026-08-27 AskUserQuestion 三项批示）
FINAL_RULINGS: dict[str, tuple[str, str]] = {}
for _cid in ("zh-023", "multi-012"):
    FINAL_RULINGS[_cid] = ("verified_active",
                           "两线一致 confirmed：机械包含证据 + 新鲜密封盲审")
FINAL_RULINGS["mixed-022"] = (
    "retired_ambiguous_phrasing",
    "答案点机械在场但新旧两轮模型一致 reject；本质为命题双读歧义，退休归档")
for _cid in ("en-052", "mixed-030", "mixed-033"):
    FINAL_RULINGS[_cid] = (
        "retired_persistent_contract_error",
        "契约聚焦盲审三次独立复现持续性契约不一致；产品线另立引擎修复项")

_EXPECTED_COUNTS = {"verified_active": 2,
                    "retired_ambiguous_phrasing": 1,
                    "retired_persistent_contract_error": 3}


class FinalRulingsError(RuntimeError):
    """任何非法状态：调用方保证零输出 fail-closed。"""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _line(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _manifest(body: dict) -> dict:
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = hashlib.sha256(
        _dump(result).encode("utf-8")).hexdigest()
    return result


def _preflight() -> None:
    for name, expected in EXPECTED_INPUT_SHAS.items():
        path = PACK_TEMPLATE if name == "owner-decision-template.jsonl" \
            else (V21_DIR / "rulings-ledger.jsonl"
                  if name == "rulings-ledger.jsonl"
                  else V21_DIR / ("restored-focus-review" if name.startswith(
                      "restored") else "contract-focus-review") / name)
        actual = _sha256_file(path)
        if actual != expected:
            raise FinalRulingsError(
                f"upstream drift: {name} sha {actual} != {expected}")
    ledger = [json.loads(l) for l in
              (V21_DIR / "rulings-ledger.jsonl").read_text(
                  encoding="utf-8").splitlines() if l.strip()]
    by_id = {r["case_id"]: r for r in ledger}
    missing = set(FINAL_RULINGS) - set(by_id)
    if missing:
        raise FinalRulingsError(f"final rulings reference unknown cases: {missing}")
    # 交叉校验：verified_active/retired_ambiguous 必须来自 restored 处置行，
    # retired_persistent_contract_error 必须来自 contract 盲审授权行
    for cid, (disp, _) in FINAL_RULINGS.items():
        src = by_id[cid]["disposition"]
        if disp in ("verified_active", "retired_ambiguous_phrasing") and \
                src != "restored_pending_verification":
            raise FinalRulingsError(f"lineage mismatch for {cid}: {src}")
        if disp == "retired_persistent_contract_error" and \
                src != "contract_blind_review_authorized":
            raise FinalRulingsError(f"lineage mismatch for {cid}: {src}")


def build_outputs() -> tuple[str, str]:
    ledger_lines = []
    counts: dict[str, int] = {}
    for cid in sorted(FINAL_RULINGS):
        disp, note = FINAL_RULINGS[cid]
        lineage: dict[str, Any] = {
            "rulings_template_sha256": EXPECTED_INPUT_SHAS["rulings-ledger.jsonl"],
            "rule_version": RULE_VERSION,
            "actor": ACTOR,
            "timestamp": TIMESTAMP,
        }
        if disp in ("verified_active", "retired_ambiguous_phrasing"):
            lineage["restored_review_results_sha256"] = \
                EXPECTED_INPUT_SHAS["restored-review-results.jsonl"]
        else:
            lineage["contract_review_results_sha256"] = \
                EXPECTED_INPUT_SHAS["contract-review-results.jsonl"]
        ledger_lines.append(_line({
            "case_id": cid,
            "disposition": disp,
            "decision_note": note,
            "upstream_disposition": None,  # 在真实落账时由 preflight 数据填充
            "lineage": lineage,
        }))
        counts[disp] = counts.get(disp, 0) + 1
    if counts != _EXPECTED_COUNTS:
        raise FinalRulingsError(f"counts mismatch: {counts}")

    body = {
        "actor": ACTOR,
        "counts": counts,
        "declarations": {
            "candidate_bytes_unchanged": True,
            "governance_ledger_only_no_data_rewrite": True,
            "llm_called": False,
            "network_used": False,
            "overlay_generated": False,
            "pending_pool_after_batch": ["zh-023", "multi-012"],
        },
        "gate_verdict": GATE_OK,
        "input_shas": dict(EXPECTED_INPUT_SHAS),
        "preregistration": [
            "plans/V21-RESTORED-CASES-VERIFICATION-PREREGISTRATION-2026-08-27.md"],
        "rule_version": RULE_VERSION,
        "run_at": TIMESTAMP,
        "task": "v2.1-final-rulings-apply",
    }
    manifest = _manifest(body)
    return "\n".join(ledger_lines) + "\n", _dump(manifest)


def run(*, out_dir: Path = DEFAULT_OUT) -> dict:
    if out_dir.exists():
        raise FinalRulingsError(f"output directory already exists: {out_dir}")
    _preflight()
    # 用上游账本回填每行的原始处置（lineage 精确性）
    upstream = {json.loads(l)["case_id"]: json.loads(l)["disposition"]
                for l in (V21_DIR / "rulings-ledger.jsonl").read_text(
                    encoding="utf-8").splitlines() if l.strip()}
    ledger_text, manifest_text = build_outputs()
    rows = [json.loads(l) for l in ledger_text.splitlines()]
    for r in rows:
        r["upstream_disposition"] = upstream.get(r["case_id"])
    ledger_text = "".join(_line(r) + "\n" for r in rows)
    out_dir.mkdir(parents=True)
    (out_dir / "final-rulings-ledger.jsonl").write_text(
        ledger_text, encoding="utf-8", newline="\n")
    (out_dir / "manifest.json").write_text(
        manifest_text, encoding="utf-8", newline="\n")
    return json.loads(manifest_text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    try:
        manifest = run(out_dir=args.out_dir)
    except FinalRulingsError as exc:
        print(f"FAIL-CLOSED: {exc}", file=sys.stderr)
        return 1
    print(_dump({"gate_verdict": manifest["gate_verdict"],
                 "counts": manifest["counts"],
                 "out_dir": str(args.out_dir)}), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
