"""M5d 门禁机械裁决脚本（预注册判据 G1 ∧ G2'，只读产物）。

判据（M5 提案 §二，owner 已批锁定；G2' 锚定见 M5b 锚定文档）：
- G1：修正率（partial 计 0.5）≥ 0.55；
- G2'：语义拒答正确率（al3-refusal-judge-v1.1）≥ 0.90；
- 两判据同时满足 ⇒ PASS；任一不满足 ⇒ FAIL（互不抵扣）。

用法::

    python scripts/m5d_gate_decision.py \
        --arm2 results/answer-level/m4c-arm2-2026-09-06 \
        --refusal-judge results/answer-level/m5b-arm2-refusal-judge-v11-2026-09-06 \
        --m2-judge results/answer-level/m3-judge-2026-09-05 \
        --out results/answer-level/m5d-decision-2026-09-06/machine.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

G1_THRESHOLD = 0.55
G2PRIME_THRESHOLD = 0.90
MECHANICAL_HIT_POINTS = 20  # M2 机械命中要点数（判定面 174 = 20 + 154）
TOTAL_POINTS = 174


def _load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def compute_g1(judge_dir: Path) -> dict:
    """G1：修正率（partial 计 0.5）= (20 + hit + 0.5×partial) / 174。"""
    rows = _load_jsonl(Path(judge_dir) / "outcomes-judge.jsonl")
    hit = sum(1 for r in rows if r.get("judge_verdict") == "hit")
    partial = sum(1 for r in rows if r.get("judge_verdict") == "partial")
    ce = sum(1 for r in rows if r.get("contract_error"))
    judged = len(rows)
    # 判定面一致性：judged 必须等于 154（174 − 20 机械命中）
    expected_miss = TOTAL_POINTS - MECHANICAL_HIT_POINTS
    value = (MECHANICAL_HIT_POINTS + hit + 0.5 * partial) / TOTAL_POINTS
    return {
        "judged": judged,
        "expected_judged": expected_miss,
        "face_consistent": judged == expected_miss,
        "hit": hit,
        "partial": partial,
        "contract_error": ce,
        "g1_corrected_rate": round(value, 4),
        "g1_conservative_rate": round(
            (MECHANICAL_HIT_POINTS + hit) / TOTAL_POINTS, 4),
        "g1_threshold": G1_THRESHOLD,
        "g1_pass": value >= G1_THRESHOLD,
    }


def compute_g2prime(refusal_judge_dir: Path) -> dict:
    """G2'：语义拒答正确率（契约错误按未正确拒答计入）。"""
    rows = _load_jsonl(
        Path(refusal_judge_dir) / "outcomes-refusal-judge.jsonl")
    n = len(rows)
    refused = sum(1 for r in rows if r.get("semantic_verdict") == "refused")
    ce = sum(1 for r in rows if r.get("contract_error"))
    value = refused / n if n else float("nan")
    return {
        "probes": n,
        "semantic_refused": refused,
        "contract_error": ce,
        "g2prime_rate": round(value, 4) if n else None,
        "g2prime_threshold": G2PRIME_THRESHOLD,
        "g2prime_pass": bool(n) and value >= G2PRIME_THRESHOLD,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm2", required=True, type=Path,
                        help="臂2 密封目录（G1 的 judge 来源可选 --arm2-judge）")
    parser.add_argument("--arm2-judge", type=Path, default=None,
                        help="臂2 judge 子集目录（默认：--arm2-judge 必填于裁决）")
    parser.add_argument("--refusal-judge", required=True, type=Path,
                        help="al3 语义重测量目录（G2'）")
    parser.add_argument("--out", default=Path("results/answer-level/m5d-decision-2026-09-06/machine.json"))
    args = parser.parse_args(argv)

    if args.arm2_judge is None:
        print("[m5d] 需要 --arm2-judge（G1 的 al2 judge 子集目录）")
        return 2

    g1 = compute_g1(args.arm2_judge)
    g2 = compute_g2prime(args.refusal_judge)
    verdict = "PASS" if (g1["g1_pass"] and g2["g2prime_pass"]) else "FAIL"

    result = {
        "date": "2026-09-06",
        "gate": {"G1_threshold": G1_THRESHOLD, "G2prime_threshold": G2PRIME_THRESHOLD},
        "g1": g1,
        "g2prime": g2,
        "verdict": verdict,
        "rule": "G1 ∧ G2' 同时满足 ⇒ PASS；互不抵扣",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"[m5d] G1={g1['g1_corrected_rate']} (≥{G1_THRESHOLD}: {g1['g1_pass']}, "
          f"面一致={g1['face_consistent']})")
    print(f"[m5d] G2'={g2['g2prime_rate']} (≥{G2PRIME_THRESHOLD}: {g2['g2prime_pass']})")
    print(f"[m5d] 裁决 = {verdict} -> {out}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
