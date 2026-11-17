"""M6a 配对重放裁决（2026-11-01 已签 addendum 第七节）。

机械读取密封产物，不改数、不看数调阈值：
  - paired：replay-stats.json 的 citation_recall_avg / citation_precision_avg
    / fabricated_citation_count / retrieved_not_in_context_count 合计；
  - 基线 judge：report.json 的 hit/partial/miss/CE 与 answer_hit 机械命中数；
  - al3 两轮取较低轮；
  - 预算实际值（签批口径：生成 150 调用=1/例；judge/al3 用 sealed report
    的网关级 calls）。

C1 = paired recall_avg >= 0.10
C2 = (mechanical_hit + judge_hit + 0.5*judge_partial) / 174 >= 0.55
     ∧ al3 较低轮 semantic_correct / 28 >= 0.90
C3 = paired precision_avg >= 0.0400 ∧ fabricated=0 ∧ retrieved_not_in_context=0
C1 ∧ C2 ∧ C3 → PASS；任一不满足 → FAIL；
一致性 / 预算 / 哈希失败 → INVALID（优先于 C 裁决）。

输出（results/answer-level/m6a-paired-2026-11-01/）：
  decision.json / report.json / report.md / manifest.json（自哈希）
  + 归档副本（基线 outcomes 副本、评测脚本副本、运行日志，addendum §七）。
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "results" / "answer-level" / "m6a-paired-2026-11-01"
BASELINE_DIR = ROOT / "results" / "answer-level" / "m6a-paired-base-2026-11-01"
JUDGE_DIR = ROOT / "results" / "answer-level" / "m6a-paired-judge-2026-11-01"
AL3_R1_DIR = ROOT / "results" / "answer-level" / "m6a-paired-al3-round1-2026-11-01"
AL3_R2_DIR = ROOT / "results" / "answer-level" / "m6a-paired-al3-round2-2026-11-01"

BASE_COMMIT = "746712d"
M6A_MODULE_COMMIT = "614e260"
M6A_MODULE_SHA256 = (
    "ee9963c76cbf580238b5914a3b1a34d6265bdd66a5bdbfeb3523a457bccc1613")

# 预算硬上界（签批口径；生成记 150 调用=1/例，judge/al3 用网关级含重试）
BUDGET_TOKEN_CAP = 1_500_000
BUDGET_CALL_CAP = 400
GEN_CALLS_SIGNED = 150

# C 阈值（预注册冻结；不得改）
C1_RECALL_MIN = 0.10
C2_RATE_MIN = 0.55
C2_POINTS_DENOM = 174
C2_REFUSAL_MIN = 0.90
C2_REFUSAL_DENOM = 28
C3_PRECISION_MIN = 0.0400


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump_body(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def verify_manifest_self_hash(manifest: dict[str, Any]) -> bool:
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    return hashlib.sha256(
        dump_body(body).encode("utf-8")).hexdigest() == manifest.get(
        "manifest_sha256")


def verify_sealed_dir(name: str, d: Path, outcomes_name: str) -> dict[str, Any]:
    """密封目录一致性：manifest 自哈希 + 产物文件哈希 + 血缘字段。"""
    result: dict[str, Any] = {"dir": name, "ok": True, "problems": []}
    if not (d / "manifest.json").exists():
        result["absent"] = True
        result["problems"].append("未运行（目录不存在）")
        result["manifest_fields"] = {}
        return result
    manifest = load_json(d / "manifest.json")
    if not verify_manifest_self_hash(manifest):
        result["ok"] = False
        result["problems"].append("manifest 自哈希不符")
    for field, fname in (("outcomes_sha256", outcomes_name),
                         ("report_sha256", "report.json")):
        expected = manifest.get(field)
        if expected is not None:
            actual = sha256_file(d / fname)
            if actual != expected:
                result["ok"] = False
                result["problems"].append(
                    f"{fname} 哈希不符: {actual} != {expected}")
    result["manifest_fields"] = {
        k: v for k, v in manifest.items()
        if k.endswith("_sha256") and k != "manifest_sha256"}
    return result


def main() -> int:
    problems: list[str] = []

    # ── 一致性：重放断言 ──
    consistency = load_json(OUT_DIR / "consistency.json")
    consistency_ok = bool(consistency.get("ok")) and \
        consistency.get("verdict") == "CONSISTENT"
    if not consistency_ok:
        problems.append("离线重放一致性断言失败（见 consistency.json）")

    # ── 哈希：M6a 模块 + src/ 零改动 + 各密封目录 ──
    blob = subprocess.run(
        ["git", "show", f"{M6A_MODULE_COMMIT}:src/citation_selection.py"],
        cwd=str(ROOT), capture_output=True, timeout=120)
    module_sha = hashlib.sha256(blob.stdout).hexdigest() if \
        blob.returncode == 0 else None
    module_sha_ok = module_sha == M6A_MODULE_SHA256
    if not module_sha_ok:
        problems.append(f"M6a 模块 SHA 不符: {module_sha}")

    diff = subprocess.run(
        ["git", "diff", f"{BASE_COMMIT}..HEAD", "--", "src/"],
        cwd=str(ROOT), capture_output=True, timeout=120)
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "src/"],
        cwd=str(ROOT), capture_output=True, timeout=120)
    src_clean = (diff.returncode == 0 and not diff.stdout.strip()
                 and not dirty.stdout.strip())
    if not src_clean:
        problems.append("src/ 相对 746712d 有改动或未提交变更")

    sealed = {
        "baseline": verify_sealed_dir(
            "baseline", BASELINE_DIR, "outcomes.jsonl"),
        "judge": verify_sealed_dir(
            "judge", JUDGE_DIR, "outcomes-judge.jsonl"),
        "al3_round1": verify_sealed_dir(
            "al3_round1", AL3_R1_DIR, "outcomes-refusal-judge.jsonl"),
        "al3_round2": verify_sealed_dir(
            "al3_round2", AL3_R2_DIR, "outcomes-refusal-judge.jsonl"),
    }
    baseline_outcomes_sha = sha256_file(BASELINE_DIR / "outcomes.jsonl")
    # 血缘交叉校验：judge/al3 的 source/m2 outcomes 哈希 == 基线 outcomes 哈希
    for key, field in (("judge", "m2_outcomes_sha256"),
                       ("al3_round1", "source_outcomes_sha256"),
                       ("al3_round2", "source_outcomes_sha256")):
        linked = sealed[key]["manifest_fields"].get(field)
        if linked is not None and linked != baseline_outcomes_sha:
            sealed[key]["ok"] = False
            sealed[key]["problems"].append(
                f"{field} 与基线 outcomes 哈希不符")
    sealed_ok = all(v["ok"] for v in sealed.values())
    if not sealed_ok:
        problems.append("密封产物哈希/血缘校验失败")

    # ── paired 指标（机械读取 replay-stats.json） ──
    replay_stats = load_json(OUT_DIR / "replay-stats.json")
    paired = replay_stats["paired_aggregates"]
    slot_totals = replay_stats["slot_totals"]

    # ── 基线聚合（C1/C3 对比 + 预算 tokens） ──
    base_report = load_json(BASELINE_DIR / "report.json")
    base_rows = load_jsonl(BASELINE_DIR / "outcomes.jsonl")
    base_fabricated = sum(
        r["citation_metrics"]["fabricated_citation_count"] for r in base_rows)
    base_retrieved = sum(
        r["citation_metrics"]["retrieved_not_in_context_count"]
        for r in base_rows)

    # ── 可裁决性闸：一致性 CONSISTENT 且 judge/al3 密封产物齐备 ──
    # INVALID 停止条件触发时 judge/al3 不得运行，C1/C2/C3 一律不裁
    # （禁止以部分结果裁决）。
    judge_available = all(
        (d / "report.json").exists()
        for d in (JUDGE_DIR, AL3_R1_DIR, AL3_R2_DIR))
    if not (consistency_ok and judge_available):
        if not consistency_ok:
            problems.append(
                "离线重放一致性前置失败（chunk store 无法解析全部 "
                "context_chunk_ids_ordered，缺失即停止，任务书五.1/五.5）")
        if not judge_available:
            problems.append(
                "judge/al3 未运行（INVALID 停止条件触发，0 LLM 调用）")
        return _finalize_invalid(
            problems=problems,
            consistency=consistency,
            replay_stats=load_json(OUT_DIR / "replay-stats.json"),
            base_report=base_report,
            base_rows=base_rows,
            base_fabricated=base_fabricated,
            base_retrieved=base_retrieved,
            sealed=sealed,
            sealed_ok=sealed_ok,
            module_sha=module_sha,
            module_sha_ok=module_sha_ok,
            src_clean=src_clean,
            consistency_ok=consistency_ok,
            baseline_outcomes_sha=baseline_outcomes_sha,
        )

    # ── C2：基线 judge ──
    judge_report = load_json(JUDGE_DIR / "report.json")
    judge_agg = judge_report  # report = {judged_count, **aggregate, judge_tokens}
    c2_numerator = (
        judge_agg["mechanical_hit_count"]
        + judge_agg["count_hit"]
        + 0.5 * judge_agg["count_partial"])
    c2_rate = c2_numerator / C2_POINTS_DENOM
    c2_judge_ok = c2_rate >= C2_RATE_MIN

    # ── C2：al3 两轮取较低轮 ──
    r1_report = load_json(AL3_R1_DIR / "report.json")
    r2_report = load_json(AL3_R2_DIR / "report.json")
    r1_correct = r1_report["semantic_correct"]
    r2_correct = r2_report["semantic_correct"]
    lower_correct = min(r1_correct, r2_correct)
    lower_round = "round1" if r1_correct <= r2_correct else "round2"
    g2_prime = lower_correct / C2_REFUSAL_DENOM
    c2_refusal_ok = g2_prime >= C2_REFUSAL_MIN

    # al3 跨轮一致率与分歧探针
    r1_rows = {r["case_id"]: r for r in load_jsonl(
        AL3_R1_DIR / "outcomes-refusal-judge.jsonl")}
    r2_rows = {r["case_id"]: r for r in load_jsonl(
        AL3_R2_DIR / "outcomes-refusal-judge.jsonl")}
    agree = 0
    probes: list[dict[str, Any]] = []
    for cid in sorted(set(r1_rows) & set(r2_rows)):
        v1 = r1_rows[cid].get("semantic_verdict")
        v2 = r2_rows[cid].get("semantic_verdict")
        if v1 == v2:
            agree += 1
        else:
            probes.append({
                "case_id": cid,
                "query": r1_rows[cid].get("query"),
                "round1_semantic_verdict": v1,
                "round2_semantic_verdict": v2,
                "lexical_verdict": r1_rows[cid].get("lexical_verdict"),
            })
    n_rounds = len(set(r1_rows) & set(r2_rows))
    round_agreement_rate = agree / n_rounds if n_rounds else None

    # ── 预算（签批口径） ──
    gen_tokens = int(base_report.get("total_tokens_sum") or 0)
    judge_tokens = judge_agg.get("judge_tokens") or {}
    r1_tokens = r1_report.get("refusal_judge_tokens") or {}
    r2_tokens = r2_report.get("refusal_judge_tokens") or {}
    budget = {
        "accounting": (
            "签批口径：生成 calls=150（1 生成调用/例）；judge/al3 用 sealed "
            "report 的网关级 calls（含重试）；replay 0 LLM 调用。"),
        "generation_tokens": gen_tokens,
        "generation_calls": GEN_CALLS_SIGNED,
        "judge_tokens": judge_tokens,
        "al3_round1_tokens": r1_tokens,
        "al3_round2_tokens": r2_tokens,
        "replay_calls": 0,
        "rejudge_calls": 0,
    }
    total_tokens = (
        gen_tokens
        + int(judge_tokens.get("total_tokens") or 0)
        + int(r1_tokens.get("total_tokens") or 0)
        + int(r2_tokens.get("total_tokens") or 0))
    total_calls = (
        GEN_CALLS_SIGNED
        + int(judge_tokens.get("calls") or 0)
        + int(r1_tokens.get("calls") or 0)
        + int(r2_tokens.get("calls") or 0))
    budget["total_tokens"] = total_tokens
    budget["total_calls"] = total_calls
    budget["token_cap"] = BUDGET_TOKEN_CAP
    budget["call_cap"] = BUDGET_CALL_CAP
    budget_ok = total_tokens <= BUDGET_TOKEN_CAP and total_calls <= BUDGET_CALL_CAP
    budget["ok"] = budget_ok
    if not budget_ok:
        problems.append(
            f"预算超限: tokens={total_tokens} calls={total_calls}")

    # ── C1 / C3 ──
    c1_value = paired["citation_recall_avg"]
    c1_ok = c1_value >= C1_RECALL_MIN
    c3_precision_ok = paired["citation_precision_avg"] >= C3_PRECISION_MIN
    c3_fabricated_ok = paired["fabricated_citation_count"] == 0
    c3_retrieved_ok = paired["retrieved_not_in_context_count"] == 0
    c3_ok = c3_precision_ok and c3_fabricated_ok and c3_retrieved_ok

    if problems:
        verdict = "INVALID"
    else:
        verdict = "PASS" if (c1_ok and c2_judge_ok and c2_refusal_ok
                             and c3_ok) else "FAIL"

    decision = {
        "stage": "m6a-paired-decision",
        "protocol": "M6a paired replay addendum 2026-11-01 (signed Q2-a..d)",
        "c1": {
            "metric": "paired citation_recall_avg",
            "value": c1_value,
            "value_raw": paired["citation_recall_raw"],
            "threshold": C1_RECALL_MIN,
            "ok": c1_ok,
        },
        "c2": {
            "formula": (
                "(mechanical_hit + judge_hit + 0.5*judge_partial) / 174 "
                ">= 0.55 AND lower-round semantic_correct / 28 >= 0.90"),
            "judge_part": {
                "mechanical_hit": judge_agg["mechanical_hit_count"],
                "judge_hit": judge_agg["count_hit"],
                "judge_partial": judge_agg["count_partial"],
                "judge_miss": judge_agg["count_miss"],
                "judge_contract_error": judge_agg["count_contract_error"],
                "judged_count": judge_agg["judged_count"],
                "total_points_recorded": judge_agg["total_points"],
                "denominator": C2_POINTS_DENOM,
                "value": c2_rate,
                "threshold": C2_RATE_MIN,
                "ok": c2_judge_ok,
            },
            "refusal_part": {
                "round1_semantic_correct": r1_correct,
                "round2_semantic_correct": r2_correct,
                "lower_round": lower_round,
                "lower_semantic_correct": lower_correct,
                "denominator": C2_REFUSAL_DENOM,
                "value_g2_prime": g2_prime,
                "threshold": C2_REFUSAL_MIN,
                "ok": c2_refusal_ok,
                "round_agreement_rate": round_agreement_rate,
                "disagreement_probes": probes,
            },
            "ok": c2_judge_ok and c2_refusal_ok,
        },
        "c3": {
            "paired_precision_avg": paired["citation_precision_avg"],
            "paired_precision_raw": paired["citation_precision_raw"],
            "precision_threshold": C3_PRECISION_MIN,
            "fabricated_citation_count": paired["fabricated_citation_count"],
            "retrieved_not_in_context_count":
                paired["retrieved_not_in_context_count"],
            "ok": c3_ok,
        },
        "baseline_vs_paired": {
            "baseline_citation_recall_avg":
                base_report["citation_recall_avg"],
            "paired_citation_recall_avg": c1_value,
            "baseline_citation_precision_avg":
                base_report["citation_precision_avg"],
            "paired_citation_precision_avg":
                paired["citation_precision_avg"],
            "baseline_fabricated_citation_count": base_fabricated,
            "baseline_retrieved_not_in_context_count": base_retrieved,
        },
        "slot_attribution": {
            **slot_totals,
            "stats_sums": replay_stats["stats_sums"],
            "fail_closed_cases": replay_stats["fail_closed_cases"],
            "examined_note": (
                "add/retarget/delete 按位比较基线与 paired 的 [S#] 序列；"
                "retarget=同槽位 ID 变化数。"),
        },
        "budget": budget,
        "integrity": {
            "consistency_ok": consistency_ok,
            "m6a_module_sha256": module_sha,
            "m6a_module_sha256_ok": module_sha_ok,
            "src_clean": src_clean,
            "sealed_dirs": sealed,
            "sealed_ok": sealed_ok,
        },
        "problems": problems,
        "verdict": verdict,
    }
    (OUT_DIR / "decision.json").write_text(
        dump_body(decision), encoding="utf-8")

    # ── report.json（机器可读全量） ──
    report = {
        "stage": "m6a-paired-report",
        "decision": decision,
        "baseline_report_aggregates": base_report,
        "judge_aggregate": judge_agg,
        "al3_round1_report": r1_report,
        "al3_round2_report": r2_report,
        "replay_stats": replay_stats,
    }
    (OUT_DIR / "report.json").write_text(dump_body(report), encoding="utf-8")

    # ── report.md ──
    md = _render_report_md(decision, report)
    (OUT_DIR / "report.md").write_text(md, encoding="utf-8")

    # ── 归档副本（addendum §七）：基线 outcomes 副本 + 评测脚本副本 ──
    shutil.copy2(BASELINE_DIR / "outcomes.jsonl",
                 OUT_DIR / "baseline-outcomes.jsonl")
    scripts_dir = OUT_DIR / "eval-scripts"
    scripts_dir.mkdir(exist_ok=True)
    for src in (
        ROOT / "scripts" / "m6a_preflight.py",
        ROOT / "scripts" / "m6a_paired_replay.py",
        ROOT / "scripts" / "m6a_paired_decision.py",
        ROOT / "evaluation" / "generation_runner.py",
        ROOT / "evaluation" / "citation_metrics.py",
    ):
        shutil.copy2(src, scripts_dir / src.name)

    # ── 运行日志：decision 自身摘要（其余阶段日志由外层 tee 至 logs/） ──
    logs_dir = OUT_DIR / "logs"
    logs_dir.mkdir(exist_ok=True)
    (logs_dir / "decision.log").write_text(
        f"verdict={verdict}\n"
        f"C1={c1_value} (>= {C1_RECALL_MIN}: {c1_ok})\n"
        f"C2_rate={c2_rate} (>= {C2_RATE_MIN}: {c2_judge_ok})\n"
        f"G2'={g2_prime} lower={lower_round} "
        f"(>= {C2_REFUSAL_MIN}: {c2_refusal_ok})\n"
        f"C3 precision={paired['citation_precision_avg']} "
        f"fabricated={paired['fabricated_citation_count']} "
        f"retrieved={paired['retrieved_not_in_context_count']} "
        f"(ok: {c3_ok})\n"
        f"budget tokens={total_tokens} calls={total_calls} ok={budget_ok}\n"
        f"problems={problems}\n",
        encoding="utf-8")

    # ── manifest.json（自哈希，覆盖目录内全部文件） ──
    files: dict[str, str] = {}
    for p in sorted(OUT_DIR.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            files[str(p.relative_to(OUT_DIR)).replace("\\", "/")] = \
                sha256_file(p)
    manifest_body = {
        "stage": "m6a-paired-decision",
        "lineage": "m6a-paired-replay-2026-11-01",
        "protocol": "M6a paired replay addendum 2026-11-01 (signed Q2-a..d)",
        "base_commit": BASE_COMMIT,
        "head_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT),
            capture_output=True, text=True, timeout=60).stdout.strip(),
        "m6a_module_commit": M6A_MODULE_COMMIT,
        "m6a_module_sha256": module_sha,
        "baseline_outcomes_sha256": baseline_outcomes_sha,
        "verdict": verdict,
        "files": files,
    }
    manifest = dict(manifest_body)
    manifest["manifest_sha256"] = hashlib.sha256(
        dump_body(manifest_body).encode("utf-8")).hexdigest()
    (OUT_DIR / "manifest.json").write_text(dump_body(manifest),
                                           encoding="utf-8")

    print(f"[decision] verdict={verdict}")
    print(f"[decision] C1 recall={c1_value} ok={c1_ok}")
    print(f"[decision] C2 rate={c2_rate:.4f} ok={c2_judge_ok} | "
          f"G2'={g2_prime:.4f} ({lower_round}) ok={c2_refusal_ok}")
    print(f"[decision] C3 precision={paired['citation_precision_avg']} "
          f"fabricated={paired['fabricated_citation_count']} "
          f"retrieved={paired['retrieved_not_in_context_count']} "
          f"ok={c3_ok}")
    print(f"[decision] budget tokens={total_tokens} calls={total_calls} "
          f"ok={budget_ok}")
    if problems:
        for p in problems:
            print(f"[decision] PROBLEM: {p}")
    return 0


def _render_report_md(decision: dict[str, Any],
                      report: dict[str, Any]) -> str:
    c1 = decision["c1"]
    c2 = decision["c2"]
    c3 = decision["c3"]
    bp = decision["baseline_vs_paired"]
    slot = decision["slot_attribution"]
    budget = decision["budget"]
    integ = decision["integrity"]
    refusal = c2["refusal_part"]
    judge_part = c2["judge_part"]

    def _yn(ok: bool) -> str:
        return "满足" if ok else "不满足"

    probes_lines = "\n".join(
        f"- {p['case_id']}: R1={p['round1_semantic_verdict']} / "
        f"R2={p['round2_semantic_verdict']}（lexical="
        f"{p['lexical_verdict']}）｜{str(p['query'])[:60]}"
        for p in refusal["disagreement_probes"]) or "- 无分歧"

    sealed_lines = "\n".join(
        f"- {k}: ok={v['ok']}"
        + (f" problems={v['problems']}" if v["problems"] else "")
        for k, v in integ["sealed_dirs"].items())

    return f"""# M6a 配对重放附录评测报告（2026-11-01）

- 协议：M6a paired replay addendum 2026-11-01（已签 Q2-a..d）
- 分支：eval/m6a-paired-2026-11-01（基线 {BASE_COMMIT}）
- 最终裁决：**{decision['verdict']}**

## 1. C1/C2/C3 裁决

| 判据 | 公式 | 值 | 阈值 | 结果 |
|---|---|---|---|---|
| C1 | paired citation_recall_avg | {c1['value']}（raw {c1['value_raw']}） | ≥ {c1['threshold']} | {_yn(c1['ok'])} |
| C2-judge | (mech_hit + judge_hit + 0.5×judge_partial) / 174 | {c2['judge_part']['value']:.6f} | ≥ {c2['judge_part']['threshold']} | {_yn(c2['judge_part']['ok'])} |
| C2-G2′ | al3 较低轮 semantic_correct / 28 | {refusal['value_g2_prime']:.6f}（{refusal['lower_round']}={refusal['lower_semantic_correct']}/28） | ≥ {refusal['threshold']} | {_yn(refusal['ok'])} |
| C3 | paired precision ∧ fabricated=0 ∧ retrieved_not_in_context=0 | precision={c3['paired_precision_avg']}（raw {c3['paired_precision_raw']}），fabricated={c3['fabricated_citation_count']}，retrieved={c3['retrieved_not_in_context_count']} | ≥ {c3['precision_threshold']} ∧ 0 ∧ 0 | {_yn(c3['ok'])} |

C2 分子构成：mechanical_hit={judge_part['mechanical_hit']}、
judge_hit={judge_part['judge_hit']}、judge_partial={judge_part['judge_partial']}、
judge_miss={judge_part['judge_miss']}、CE={judge_part['judge_contract_error']}
（judged={judge_part['judged_count']}；CE 按 miss 计不进分子）。
judge 报告记录 total_points={judge_part['total_points_recorded']}，
C2 分母按预注册固定 174。

## 2. 基线 vs paired（C1/C3 对比）

| 指标 | 新基线（capture on） | paired 重放 | Δ |
|---|---|---|---|
| citation_recall_avg | {bp['baseline_citation_recall_avg']} | {bp['paired_citation_recall_avg']} | {round(bp['paired_citation_recall_avg'] - bp['baseline_citation_recall_avg'], 4)} |
| citation_precision_avg | {bp['baseline_citation_precision_avg']} | {c3['paired_precision_avg']} | {round(c3['paired_precision_avg'] - bp['baseline_citation_precision_avg'], 4)} |
| fabricated 合计 | {bp['baseline_fabricated_citation_count']} | {c3['fabricated_citation_count']} | {c3['fabricated_citation_count'] - bp['baseline_fabricated_citation_count']} |
| retrieved_not_in_context 合计 | {bp['baseline_retrieved_not_in_context_count']} | {c3['retrieved_not_in_context_count']} | {c3['retrieved_not_in_context_count'] - bp['baseline_retrieved_not_in_context_count']} |

## 3. C2 / G2′ 明细

- 基线 judge（al2-judge-v1，174 有效要点中的 miss 送判）：
  hit={judge_part['judge_hit']} partial={judge_part['judge_partial']}
  miss={judge_part['judge_miss']} CE={judge_part['judge_contract_error']}，
  机械命中 {judge_part['mechanical_hit']}。
- al3 两轮：round1 semantic_correct={refusal['round1_semantic_correct']}、
  round2={refusal['round2_semantic_correct']}；取较低轮
  {refusal['lower_round']}（{refusal['lower_semantic_correct']}/28 =
  {refusal['value_g2_prime']:.6f}）为 G2′。
- 跨轮一致率：{refusal['round_agreement_rate']}（{refusal['round_agreement_rate'] and round(refusal['round_agreement_rate'], 4)}）。
- 分歧探针：

{probes_lines}

## 4. 槽位归因（add / retarget / delete）

- add={slot['add']}、retarget={slot['retarget']}、delete={slot['delete']}
  （按位比较基线与 paired 的 [S#] 序列；retarget=同槽位 ID 变化数）。
- 冻结模块统计合计：{json.dumps(slot['stats_sums'], ensure_ascii=False)}；
  fail_closed 例数={slot['fail_closed_cases']}。
- 断言全过：slots_before==slots_after、add==0、delete==0、剥离 [S#] 后
  答案逐字节不变（consistency.json）。

## 5. 预算

- 口径：{budget['accounting']}
- 生成 tokens={budget['generation_tokens']}（calls={budget['generation_calls']}）；
  judge tokens={budget['judge_tokens'].get('total_tokens')}
  （calls={budget['judge_tokens'].get('calls')}）；
  al3 r1 tokens={budget['al3_round1_tokens'].get('total_tokens')}
  （calls={budget['al3_round1_tokens'].get('calls')}）、
  r2 tokens={budget['al3_round2_tokens'].get('total_tokens')}
  （calls={budget['al3_round2_tokens'].get('calls')}）；
  replay 0 LLM 调用；补判 0 调用。
- 合计 tokens={budget['total_tokens']} / 上界 {budget['token_cap']}；
  calls={budget['total_calls']} / 上界 {budget['call_cap']}；
  预算闸：{'通过' if budget['ok'] else '**超限（INVALID）**'}。
- 说明：网关级调用可能高于每例口径（rewrite/decompose/内部重试亦占调用），
  生成侧按签批口径记 150（1 生成调用/例）。

## 6. 哈希与完整性

- M6a 冻结模块（git show {M6A_MODULE_COMMIT}:src/citation_selection.py）：
  {integ['m6a_module_sha256']}（校验 {'通过' if integ['m6a_module_sha256_ok'] else '失败'}）。
- src/ 相对 {BASE_COMMIT} 零改动：{'通过' if integ['src_clean'] else '失败'}。
- 密封目录校验（manifest 自哈希 + 产物哈希 + 血缘）：

{sealed_lines}

- 离线重放一致性：{'CONSISTENT' if integ['consistency_ok'] else 'INVALID'}。
- 产物清单与逐文件哈希：manifest.json（自哈希）。

## 7. Judge [S#] 敏感性（任务第六节判据）

answer_judge_runner 的 judge 输入含 [S#] 令牌（answer_judge_runner.py 的
extract_judge_inputs 直传 answer；answer_judge.py 的 build_judge_messages
将 answer 原文嵌入 prompt；parse_judge_response 的 evidence 包含校验基于
未剥 [S#] 的 normalize_for_containment）。但配对重放的断言保证：剥离 [S#]
后 paired 答案与基线答案逐字节相同 → 剥离引用后 judge 输入在基线与配对间
完全一致 → 按判据直接在基线运行 answer_judge_runner，不补判（补判调用 0，
计入 400 的份额为 0），C2 公式未改动。

## 8. 局限

- **新基线不是 M4c 密封控制臂**：M4c（m4c-arm2-2026-09-06，sealed）recall
  0.0456/precision 0.0400 与本次新基线的差异含运行间非确定性（生成模型、
  检索并列、rewrite/decompose 波动）；C1/C3 的基线→paired 增益只在
  同基线配对（within-run）口径下成立，不得外推为对 M4c 的因果改进。
- paired 重放是离线确定性后处理：只重定向既有 [S#] 令牌，不重新生成答案，
  不度量答案文本质量变化。
- al3 两轮为同一 prompt 的两次采样，一致率与分歧探针只反映采样噪声。
- judge 判定为 LLM 采样（temperature 0.1），contract_error 按 miss 计。

## 9. 偏离与说明

- generation_runner 在既有字段/行为外新增纯 stdout 预算监控行
  （[budget] 逐例 token 累计），不改任何行为与产物；已在本节披露。
- preflight 在任务书 B 清单之外增加三个前置闸（LLM 凭据、后续输出目录
  不存在、chunks 语料在）：失败即停、不生成，属 fail-closed 加严，不改变
  任何判据与阈值。
- M4c manifest 的哈希锚采用 manifest 自哈希（936d34bb…）而非文件哈希，
  与密封 runner 的自哈希约定一致。
- 未做补跑/重跑/换种子；未修改任何阈值；未触碰 src/ 与产品默认。

## 10. 产物目录

- results/answer-level/m6a-paired-preflight-2026-11-01/（preflight.json）
- results/answer-level/m6a-paired-base-2026-11-01/（基线密封，capture on）
- results/answer-level/m6a-paired-2026-11-01/（outcomes-paired.jsonl、
  consistency.json、replay-stats.json、decision.json、report.json、
  report.md、manifest.json、baseline-outcomes.jsonl、eval-scripts/、logs/）
- results/answer-level/m6a-paired-judge-2026-11-01/（基线 judge）
- results/answer-level/m6a-paired-al3-round{1,2}-2026-11-01/（al3 两轮）
"""


def _budget_probe(base_report: dict[str, Any]) -> dict[str, Any]:
    gen_tokens = int(base_report.get("total_tokens_sum") or 0)
    return {
        "accounting": (
            "签批口径：生成 calls=150（1 生成调用/例）；judge/al3 未运行 "
            "0 调用；replay 0 LLM 调用。"),
        "generation_tokens": gen_tokens,
        "generation_calls": GEN_CALLS_SIGNED,
        "judge_tokens": {},
        "al3_round1_tokens": {},
        "al3_round2_tokens": {},
        "replay_calls": 0,
        "rejudge_calls": 0,
        "total_tokens": gen_tokens,
        "total_calls": GEN_CALLS_SIGNED,
        "token_cap": BUDGET_TOKEN_CAP,
        "call_cap": BUDGET_CALL_CAP,
        "ok": gen_tokens <= BUDGET_TOKEN_CAP and GEN_CALLS_SIGNED <= BUDGET_CALL_CAP,
    }


def _diagnose_chunk_domain(base_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """机械复算 chunk_id 域错位证据（全部来自密封产物与 chunk store）。"""
    store_text: dict[str, str] = {}
    for line in (ROOT / "data" / "v2-corpus" / "chunks" / "chunks.jsonl"
                 ).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            store_text[str(row["chunk_id"])] = str(row["text"])

    def _norm(s: str) -> str:
        return " ".join(s.split())

    store_norm = {k: _norm(v) for k, v in store_text.items()}
    pat = re.compile(r"^\[(S\d+)\].*?chunk_id=([^\s);:]+)\): (.*)$")

    distinct_ids: set[str] = set()
    missing_ids: set[str] = set()
    snippet_checked = 0
    snippet_matched = 0
    unresolvable_cases = 0
    for row in base_rows:
        ids = list(row.get("context_chunk_ids_ordered") or [])
        distinct_ids.update(ids)
        case_missing = [i for i in ids if i not in store_text]
        missing_ids.update(case_missing)
        if case_missing:
            unresolvable_cases += 1
        for line in (row.get("full_sources") or "").splitlines():
            m = pat.match(line)
            if not m:
                continue
            cid, snippet = m.group(2), _norm(m.group(3))
            if cid not in store_norm or not snippet:
                continue
            snippet_checked += 1
            if snippet in store_norm[cid]:
                snippet_matched += 1

    truth_ids: set[str] = set()
    for row in base_rows:
        truth_ids.update(row.get("relevant_chunk_ids") or [])
    return {
        "store_file": "data/v2-corpus/chunks/chunks.jsonl",
        "store_chunker": (
            "src.rag.get_splitter RecursiveCharacterTextSplitter "
            "size=2000 overlap=200（chunk-manifest.json，corpus v2.0.0，"
            "1006 chunks）"),
        "runtime_chunker": (
            "运行时索引 section/切片切分（prepare_index，2947 chunks）"),
        "cases_total": len(base_rows),
        "cases_with_unresolvable_ids": unresolvable_cases,
        "distinct_ordered_ids": len(distinct_ids),
        "distinct_missing_ids": len(missing_ids),
        "snippet_text_checks": snippet_checked,
        "snippet_text_matches_normalized": snippet_matched,
        "truth_ids_total": len(truth_ids),
        "truth_ids_in_store": sum(1 for i in truth_ids if i in store_text),
    }


def _finalize_invalid(
    *,
    problems: list[str],
    consistency: dict[str, Any],
    replay_stats: dict[str, Any],
    base_report: dict[str, Any],
    base_rows: list[dict[str, Any]],
    base_fabricated: int,
    base_retrieved: int,
    sealed: dict[str, Any],
    sealed_ok: bool,
    module_sha: str | None,
    module_sha_ok: bool,
    src_clean: bool,
    consistency_ok: bool,
    baseline_outcomes_sha: str,
) -> int:
    """INVALID 收尾：不裁 C1/C2/C3，不跑 judge/al3；写全套产物与归档。"""
    diagnosis = _diagnose_chunk_domain(base_rows)
    budget = _budget_probe(base_report)
    note = "未裁决（INVALID 停止条件触发；禁止以部分结果裁决）"
    decision = {
        "stage": "m6a-paired-decision",
        "protocol": "M6a paired replay addendum 2026-11-01 (signed Q2-a..d)",
        "c1": {"metric": "paired citation_recall_avg", "value": None,
               "threshold": C1_RECALL_MIN, "ok": None, "note": note},
        "c2": {"formula": "(mechanical_hit + judge_hit + 0.5*judge_partial) "
               "/ 174 >= 0.55 AND lower-round semantic_correct / 28 >= 0.90",
               "value": None, "ok": None, "note": note},
        "c3": {"precision_threshold": C3_PRECISION_MIN, "value": None,
               "ok": None, "note": note},
        "baseline_vs_paired": {
            "baseline_citation_recall_avg": base_report["citation_recall_avg"],
            "paired_citation_recall_avg": None,
            "baseline_citation_precision_avg":
                base_report["citation_precision_avg"],
            "paired_citation_precision_avg": None,
            "baseline_fabricated_citation_count": base_fabricated,
            "baseline_retrieved_not_in_context_count": base_retrieved,
            "note": note,
        },
        "slot_attribution": {
            **replay_stats.get("slot_totals", {}),
            "stats_sums": replay_stats.get("stats_sums", {}),
            "fail_closed_cases": replay_stats.get("fail_closed_cases"),
            "cases_replayed": replay_stats.get("cases"),
            "note": (
                "仅为可解析的 12 例部分结果，且同 ID 异文（域碰撞），"
                "不可用于裁决"),
        },
        "budget": budget,
        "integrity": {
            "consistency_ok": consistency_ok,
            "consistency_verdict": consistency.get("verdict"),
            "m6a_module_sha256": module_sha,
            "m6a_module_sha256_ok": module_sha_ok,
            "src_clean": src_clean,
            "sealed_dirs": sealed,
            "sealed_ok": sealed_ok,
        },
        "chunk_domain_diagnosis": diagnosis,
        "problems": problems,
        "verdict": "INVALID",
    }
    (OUT_DIR / "decision.json").write_text(dump_body(decision), encoding="utf-8")
    report = {
        "stage": "m6a-paired-report",
        "decision": decision,
        "baseline_report_aggregates": base_report,
        "replay_stats": replay_stats,
        "consistency": consistency,
    }
    (OUT_DIR / "report.json").write_text(dump_body(report), encoding="utf-8")
    (OUT_DIR / "report.md").write_text(
        _render_invalid_md(decision, diagnosis, problems, budget, sealed),
        encoding="utf-8")
    _write_artifacts_and_manifest(
        verdict="INVALID", module_sha=module_sha,
        baseline_outcomes_sha=baseline_outcomes_sha, decision=decision)
    print("[decision] verdict=INVALID（不裁 C1/C2/C3；judge/al3 未运行）")
    for p in problems:
        print(f"[decision] PROBLEM: {p}")
    return 0


def _write_artifacts_and_manifest(
    *,
    verdict: str,
    module_sha: str | None,
    baseline_outcomes_sha: str,
    decision: dict[str, Any],
) -> None:
    """归档副本（addendum §七）+ 自哈希 manifest（覆盖目录内全部文件）。"""
    shutil.copy2(BASELINE_DIR / "outcomes.jsonl",
                 OUT_DIR / "baseline-outcomes.jsonl")
    scripts_dir = OUT_DIR / "eval-scripts"
    scripts_dir.mkdir(exist_ok=True)
    for src in (
        ROOT / "scripts" / "m6a_preflight.py",
        ROOT / "scripts" / "m6a_paired_replay.py",
        ROOT / "scripts" / "m6a_paired_decision.py",
        ROOT / "evaluation" / "generation_runner.py",
        ROOT / "evaluation" / "citation_metrics.py",
    ):
        shutil.copy2(src, scripts_dir / src.name)
    logs_dir = OUT_DIR / "logs"
    logs_dir.mkdir(exist_ok=True)
    (logs_dir / "decision.log").write_text(
        f"verdict={verdict}\nproblems={decision.get('problems')}\n",
        encoding="utf-8")
    files: dict[str, str] = {}
    for p in sorted(OUT_DIR.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            files[str(p.relative_to(OUT_DIR)).replace("\\", "/")] = \
                sha256_file(p)
    manifest_body = {
        "stage": "m6a-paired-decision",
        "lineage": "m6a-paired-replay-2026-11-01",
        "protocol": "M6a paired replay addendum 2026-11-01 (signed Q2-a..d)",
        "base_commit": BASE_COMMIT,
        "head_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT),
            capture_output=True, text=True, timeout=60).stdout.strip(),
        "m6a_module_commit": M6A_MODULE_COMMIT,
        "m6a_module_sha256": module_sha,
        "baseline_outcomes_sha256": baseline_outcomes_sha,
        "verdict": verdict,
        "files": files,
    }
    manifest = dict(manifest_body)
    manifest["manifest_sha256"] = hashlib.sha256(
        dump_body(manifest_body).encode("utf-8")).hexdigest()
    (OUT_DIR / "manifest.json").write_text(dump_body(manifest), encoding="utf-8")


def _render_invalid_md(
    decision: dict[str, Any],
    diagnosis: dict[str, Any],
    problems: list[str],
    budget: dict[str, Any],
    sealed: dict[str, Any],
) -> str:
    base = decision["baseline_vs_paired"]
    problems_md = "\n".join(f"- {p}" for p in problems)
    sealed_md = "\n".join(
        f"- {k}: ok={v['ok']}{'（未运行）' if v.get('absent') else ''}"
        + (f" problems={v['problems']}" if v["problems"] else "")
        for k, v in sealed.items())
    return f"""# M6a 配对重放附录评测报告（2026-11-01）

- 协议：M6a paired replay addendum 2026-11-01（已签 Q2-a..d）
- 分支：eval/m6a-paired-2026-11-01（基线 {BASE_COMMIT}）
- 最终裁决：**INVALID**（一致性前置失败；不裁 C1/C2/C3；judge/al3 未运行）

## 1. C1/C2/C3 裁决

**未裁决**。任务书五.1「所有 context_chunk_ids_ordered 必须能解析，缺失即
停止」与五.5「任一断言失败 → 写 INVALID，停止，不跑 judge/al3」的停止条件
触发；按七「一致性…失败 → INVALID」，且禁止以部分结果裁决，C1/C2/C3 全部
不裁（值 = 未裁决，非 0/非 FAIL）。

## 2. INVALID 根因：chunk_id 域错位（机械复算证据）

- chunk store（{diagnosis['store_file']}）：{diagnosis['store_chunker']}。
- 运行时索引：{diagnosis['runtime_chunker']}。两者同用
  `{{source_sha256_prefix12}}_chunk_{{n}}` 格式，但 `_chunk_{{n}}` 序号空间
  语义不同（同 ID 异文）。
- 前置可解析性：{diagnosis['cases_total']} 例中
  **{diagnosis['cases_with_unresolvable_ids']} 例**含 store 中不存在的
  context_chunk_ids_ordered（distinct {diagnosis['distinct_missing_ids']} /
  {diagnosis['distinct_ordered_ids']} 个 ID 缺失；缺失编号恰为超出 store 各
  源上限的部分）。
- 同 ID 文本校验（折叠空白后 snippet ⊆ store 文本）：
  **{diagnosis['snippet_text_matches_normalized']} /
  {diagnosis['snippet_text_checks']} 吻合** —— 即使 ID 可解析也是同 ID 异文，
  不可用于重建 context。
- 真值域归属：dataset relevant_chunk_ids
  （{diagnosis['truth_ids_in_store']}/{diagnosis['truth_ids_total']} 全部在
  store 域内）→ 真值 = store 切分域，运行时 context = 另一套切分域。
- 任务书五.3 的 chunk store 文本仅对 store 域 ID 有意义；在域错位下重放会
  测错对象，故按契约停止。

## 3. 基线（唯一生成，已密封，验收闸全过）

- 150/150 有 full_sources 与 context_chunk_ids_ordered；cases_failed=0；
  无 [Generation error] 答案；capture on 的断言（S1..Sn 连续）全过。
- 新基线聚合：recall_avg={base['baseline_citation_recall_avg']}、
  precision_avg={base['baseline_citation_precision_avg']}、
  fabricated={base['baseline_fabricated_citation_count']}、
  retrieved_not_in_context={base['baseline_retrieved_not_in_context_count']}
  （与 M4c 的 0.0456/0.0400 对比含运行间非确定性；且两值均受上述域错位
  影响，属域碰撞噪声，仅如实记录）。
- paired：**未裁决**（重放仅 12 例可解析且同 ID 异文，为不可用部分结果，
  不进任何裁决）。

## 4. C2 / G2′

**未计算**：answer judge 与 al3 两轮均未运行（INVALID 停止，0 LLM 调用）。

## 5. 槽位归因（add / retarget / delete）

仅 12 例部分重放的机械记录（不可用于裁决）：add={decision['slot_attribution'].get('add')}、
retarget={decision['slot_attribution'].get('retarget')}、
delete={decision['slot_attribution'].get('delete')}、
fail_closed={decision['slot_attribution'].get('fail_closed_cases')}。

## 6. 预算

- 口径：{budget['accounting']}
- 生成 tokens={budget['generation_tokens']}（calls={budget['generation_calls']}）；
  replay 0；judge 0；al3 0。
- 合计 tokens={budget['total_tokens']} / 上界 {budget['token_cap']}；
  calls={budget['total_calls']} / 上界 {budget['call_cap']}；未触及预算上界。

## 7. 哈希与完整性

- M6a 冻结模块（git show {M6A_MODULE_COMMIT}:src/citation_selection.py）：
  {decision['integrity']['m6a_module_sha256']}
  （校验 {'通过' if decision['integrity']['m6a_module_sha256_ok'] else '失败'}）。
- src/ 相对 {BASE_COMMIT} 零改动：{'通过' if decision['integrity']['src_clean'] else '失败'}。
- 密封目录校验：

{sealed_md}

- 产物清单与逐文件哈希：manifest.json（自哈希）。

## 8. 局限与阻塞

- **阻塞**：chunk store 与运行时索引切分域不一致（见 §2），无法在不改动
  产品/数据契约的前提下完成配对重放。可行的解阻方向（供签批方决策，本次
  未执行）：(a) 用与 store 相同的 splitter 重建评测侧离线 context 文本映射；
  (b) 由数据方提供 runtime 域 chunk 文本库；(c) 修订 addendum 的 chunk
  store 前提。
- 新基线不是 M4c 密封控制臂；本次未做任何补跑/重跑/换种子/改阈值。

## 9. 偏离与说明

- replay 脚本首轮在加载冻结模块时因 importlib 未注册 sys.modules 崩溃
  （发生在任何数据处理之前，0 产物）；修复 loader 后执行一次正式重放
  （确定性离线，0 LLM 调用），其 12 例部分产物仅存档为证据，不裁决。
- generation_runner 新增纯 stdout 预算监控行（[budget]），不改行为/产物。
- preflight 在任务书 B 清单外增加三个 fail-closed 前置闸（LLM 凭据、输出
  目录不存在、chunks 语料在），全过后生成。
- M4c manifest 哈希锚采用 manifest 自哈希口径（936d34bb…）。
- 问题清单：

{problems_md}
"""


if __name__ == "__main__":
    raise SystemExit(main())
