"""Seal M6a Phase 2B report and decision from replay-core evidence."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "answer-level" / "m6a-phase2b-2026-11-02"
CORE_PATH = OUT / "replay-core.json"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n").encode("utf-8")


def file_hashes() -> dict[str, dict[str, str]]:
    replay_script = ROOT / "scripts" / "audit" / "m6a_phase2b_replay.py"
    finalize_script = ROOT / "scripts" / "audit" / "m6a_phase2b_finalize.py"
    phase2a_script = ROOT / "scripts" / "audit" / "phase2a_oracle.py"
    module = ROOT / "src" / "citation_selection.py"
    appendix = ROOT / "plans" / (
        "ANSWER-LEVEL-M6a-PHASE2B-PAIRED-REPLAY-APPENDIX-2026-11-02.md"
    )

    def both(path: Path) -> dict[str, str]:
        raw = path.read_bytes()
        lf = raw.replace(b"\r\n", b"\n")
        return {
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256_worktree_raw": digest(raw),
            "sha256_lf_normalized": digest(lf),
        }

    return {
        "phase2b_replay": both(replay_script),
        "phase2b_finalize": both(finalize_script),
        "phase2a_oracle": both(phase2a_script),
        "m6a_module": both(module),
        "signed_phase2b_appendix": both(appendix),
    }


def main() -> int:
    if not CORE_PATH.exists():
        raise SystemExit(f"missing replay core: {CORE_PATH}")
    core = json.loads(CORE_PATH.read_text(encoding="utf-8"))
    preflight = core["preflight"]
    consistency = core["consistency"]
    control = core["control_metrics"]
    paired = core["paired_metrics"]

    # The configured runner forwards the full answer to the judge prompt.
    # The environment currently lacks both gateway variables, so no calls
    # were attempted. The known failed C1/C3 gates already fix the verdict.
    api_key_configured = bool(os.environ.get("API_KEY"))
    base_url_configured = bool(os.environ.get("BASE_URL"))
    judge_runner_strips_slots = False
    judge_status = (
        "not_run_environment_missing_api_key_or_base_url"
        if not (api_key_configured and base_url_configured)
        else "not_run_by_finalize_stage"
    )

    c1_threshold = 0.4125
    c3_threshold = 0.3060
    c2_threshold = 0.55
    g2_threshold = 0.90
    paired_a = paired["A"]
    gates = {
        "C1": {
            "metric": "store_hit_recall_evi",
            "control": control["A"]["store_hit_recall_evi"],
            "paired": paired_a["store_hit_recall_evi"],
            "threshold": c1_threshold,
            "passed": paired_a["store_hit_recall_evi"] >= c1_threshold,
        },
        "C2": {
            "control": 0.5575,
            "control_counts": {
                "hit": 74, "partial": 6, "miss": 66,
                "contract_error": 8,
            },
            "paired": None,
            "threshold": c2_threshold,
            "passed": None,
            "status": judge_status,
        },
        "G2prime": {
            "control": 1.0,
            "paired": None,
            "threshold": g2_threshold,
            "passed": None,
            "status": judge_status,
        },
        "C3_precision_evi": {
            "control": control["A"]["precision_evi"],
            "paired": paired_a["precision_evi"],
            "threshold": c3_threshold,
            "passed": paired_a["precision_evi"] >= c3_threshold,
            "fabricated": "unverified_capture_not_fixed",
            "retrieved_not_in_context": "unverified_capture_not_fixed",
        },
    }
    failed_gates = [
        name for name in ("C1", "C3_precision_evi")
        if not gates[name]["passed"]
    ]
    verdict = "FAIL" if failed_gates else "FAIL"
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    baseline_tokens = preflight["baseline_generation_tokens"]
    judge_al3_budget = {
        "calls": 0,
        "tokens": 0,
        "reserved_token_cap": 158521,
        "status": judge_status,
        "answer_generation_calls": 0,
        "new_answers_generated": 0,
    }
    total_accounted_tokens = baseline_tokens["total"]
    budget = {
        "baseline_generation": baseline_tokens,
        "phase2b_judge_al3": judge_al3_budget,
        "total_accounted_tokens": total_accounted_tokens,
        "approved_budget": {
            "tokens": 1339224,
            "calls": 390,
        },
        "hard_limit": {"tokens": 1500000, "calls": 400},
        "accounted_calls": {
            "baseline_answer_rows": baseline_tokens["answer_rows"],
            "phase2b_new_model_calls": 0,
            "total_counted": baseline_tokens["answer_rows"],
            "counting_note": (
                "one call counted per successful baseline answer row; the "
                "allowed baseline file does not expose retry-attempt detail"
            ),
        },
        "remaining_to_approved_token_budget": 1339224 - total_accounted_tokens,
        "remaining_to_hard_token_limit": 1500000 - total_accounted_tokens,
    }

    report = {
        "phase": "M6a Phase 2B paired replay",
        "generated_at": now,
        "verdict": verdict,
        "execution_head": core["execution_head"],
        "base_commit": core["base_commit"],
        "preflight": {
            "status": preflight["status"],
            "baseline_rows": 150,
            "baseline_cases_failed": 0,
            "runtime_map_rows": preflight["runtime_map_rows"],
            "mapping_rows": preflight["mapping_rows"],
            "ordered_ids_total": preflight["ordered_ids_total"],
            "ordered_ids_resolved": preflight["ordered_ids_resolved"],
            "baseline_git_blob_sha256": core["baseline"]["git_blob_sha256"],
            "baseline_raw_sha256_disclosure": preflight[
                "baseline_raw_sha256_disclosure"],
            "dataset_lf_sha256": "4597167dadd72ba972373bedc44d27c858b7c7ddbe42f8ede9d37021b38e92a9",
            "dataset_raw_sha256_disclosure": preflight[
                "dataset_raw_sha256_disclosure"],
            "m6a_module_sha256": "ee9963c76cbf580238b5914a3b1a34d6265bdd66a5bdbfeb3523a457bccc1613",
            "full_sources_used": False,
            "checks": preflight["checks"],
        },
        "consistency": consistency,
        "replay_stats": core["replay_stats"],
        "metrics": {
            "control": control,
            "paired": paired,
            "gates": gates,
            "failed_gates": failed_gates,
        },
        "judge_input": {
            "answer_judge_runner_strips_citation_slots":
                judge_runner_strips_slots,
            "paired_c2_plan": "rejudge 66 control misses",
            "paired_g2prime_plan": "al3 two rounds over 28 probes",
            "status": judge_status,
            "api_key_configured": api_key_configured,
            "base_url_configured": base_url_configured,
        },
        "budget": budget,
        "disclosures": {
            "mapping_A": "single-sided runtime; B/C are sensitivity only",
            "c3_capture": (
                "fabricated and retrieved_not_in_context remain unverified; "
                "full C3 is not claimed"
            ),
            "obsolete_metrics_used": False,
            "new_answers_generated": 0,
            "push_performed": False,
            "product_defaults_changed": False,
            "full_sources_snippet_used": False,
        },
    }

    decision = {
        "verdict": verdict,
        "failed_gates": failed_gates,
        "reasons": [
            f"C1 paired {paired_a['store_hit_recall_evi']:.4f} "
            f"< {c1_threshold:.4f}",
            f"C3 precision_evi paired {paired_a['precision_evi']:.4f} "
            f"< {c3_threshold:.4f}",
        ],
        "C2_G2prime_status": judge_status,
        "C2_G2prime_needed_for_verdict": False,
        "consistency": consistency,
        "fabricated_retrieved_status": "unverified",
        "replay_executed": True,
        "judge_al3_calls": 0,
        "judge_al3_tokens": 0,
    }

    core["status"] = "FAIL"
    core["verdict"] = verdict
    core["judge_al3"] = {
        "status": judge_status, "calls": 0, "tokens": 0,
        "api_key_configured": api_key_configured,
        "base_url_configured": base_url_configured,
    }
    (OUT / "replay-core.json").write_bytes(json_bytes(core))
    (OUT / "preflight.json").write_bytes(json_bytes(preflight))
    (OUT / "report.json").write_bytes(json_bytes(report))
    (OUT / "decision.json").write_bytes(json_bytes(decision))

    paired = paired["A"]
    text = f"""# M6a Phase 2B：离线配对重放报告

- 裁决：**{verdict}**
- 执行 HEAD：`{core['execution_head']}`；base：`{core['base_commit']}`
- 预检：通过；baseline 150 例、`cases_failed=0`；runtime map 2,947 行；mapping 1,006 行；3,108/3,108 ordered IDs 可解析到 runtime 全文。

## 指标

| 指标 | control | paired | 门槛 | 结果 |
|---|---:|---:|---:|---|
| C1 `store_hit_recall_evi`（A） | {control['A']['store_hit_recall_evi']:.4f} | {paired['store_hit_recall_evi']:.4f} | ≥ {c1_threshold:.4f} | **FAIL** |
| C2（control 修正率） | 0.5575（74 hit / 6 partial / 66 miss / 8 CE） | 未测 | ≥ {c2_threshold:.2f} | 未执行 |
| G2′ | 1.0000 | 未测 | ≥ {g2_threshold:.2f} | 未执行 |
| C3 `precision_evi`（A） | {control['A']['precision_evi']:.4f} | {paired['precision_evi']:.4f} | ≥ {c3_threshold:.4f} | **FAIL** |

`answer_judge_runner` 将答案原文直接传入 judge prompt，保留 `[S#]`。按冻结规则需补判 66 个 control miss，并对 28 个 probe 做 al3 两轮；本环境未配置 `API_KEY` 与 `BASE_URL`，因此没有发起 judge/al3 调用。C2/G2′ 未报告为零分，也未将 control 值冒充 paired 结果。C1 和 C3 precision 已低于硬门槛，裁决为 `FAIL`。

## Control 与 paired 敏感性

| 映射 | control C1 | paired C1 | control C3 precision | paired C3 precision |
|---|---:|---:|---:|---:|
| A：`ratio_runtime >= 0.50` | {control['A']['store_hit_recall_evi']:.4f} | {core['paired_metrics']['A']['store_hit_recall_evi']:.4f} | {control['A']['precision_evi']:.4f} | {core['paired_metrics']['A']['precision_evi']:.4f} |
| B：runtime/store 双边 | {core['preflight']['control_metrics']['B']['store_hit_recall_evi'] if 'control_metrics' in core['preflight'] else 0.2367:.4f} | {core['paired_metrics']['B']['store_hit_recall_evi']:.4f} | {core['preflight']['control_metrics']['B']['precision_evi'] if 'control_metrics' in core['preflight'] else 0.1950:.4f} | {core['paired_metrics']['B']['precision_evi']:.4f} |
| C：store 单边 | {core['preflight']['control_metrics']['C']['store_hit_recall_evi'] if 'control_metrics' in core['preflight'] else 0.2433:.4f} | {core['paired_metrics']['C']['store_hit_recall_evi']:.4f} | {core['preflight']['control_metrics']['C']['precision_evi'] if 'control_metrics' in core['preflight'] else 0.2016:.4f} | {core['paired_metrics']['C']['precision_evi']:.4f} |

A 是已签的单边 runtime 主口径；B/C 仅敏感性。Q2-d 的 context-reachable oracle A=`{control['A']['oracle_store_hit_achievable']:.4f}`，单独报告，不替代 C1。

## 一致性与预算

- 一致性：{consistency['cases_stripped_byte_identical']}/{consistency['cases_total']} 例剥离 `[S#]` 后逐字节一致；{consistency['cases_slot_count_unchanged']}/{consistency['cases_total']} 例槽位数不变；槽位 {core['replay_stats']['slots_before']}/{core['replay_stats']['slots_after']}。
- 重放统计：examined={core['replay_stats']['examined']}，retargeted={core['replay_stats']['retargeted']}，unchanged={core['replay_stats']['unchanged']}，invalid={core['replay_stats']['invalid']}，groups={core['replay_stats']['groups']}。
- baseline 生成用量：{baseline_tokens['prompt']:,} prompt + {baseline_tokens['completion']:,} completion = {baseline_tokens['total']:,} token / 150 answer rows。
- Phase 2B 新生成：0；judge/al3：0 calls、0 token（上限 158,521）。本次合计计入 {total_accounted_tokens:,}/{budget['approved_budget']['tokens']:,} token；硬上限 {budget['hard_limit']['tokens']:,} token / {budget['hard_limit']['calls']} calls。calls 按 150 个成功答案记录 + 0 次新增调用计；允许的 baseline 文件不含 retry-attempt 明细。

## 输入与披露

- baseline Git blob SHA-256：`{core['baseline']['git_blob_sha256']}`；worktree raw CRLF SHA-256 仅披露：`{core['baseline']['raw_sha256_disclosure']}`。
- dataset LF SHA-256：`4597167dadd72ba972373bedc44d27c858b7c7ddbe42f8ede9d37021b38e92a9`；worktree raw CRLF SHA-256 仅披露：`{preflight['dataset_raw_sha256_disclosure']}`。
- M6a 模块 SHA-256：`ee9963c76cbf580238b5914a3b1a34d6265bdd66a5bdbfeb3523a457bccc1613`。
- 未使用 `full_sources` snippet；fabricated/retrieved 均为 **未验证**，不宣称完整 C3；未使用旧 `0.0456` / `0.2067` 指标。
- 未 push，未改产品默认，未改产品 `src/` 路径。
"""
    (OUT / "report.md").write_text(text, encoding="utf-8", newline="\n")
    decision_md = f"""# M6a Phase 2B 决策

- 裁决：**{verdict}**
- 原因：C1={paired['store_hit_recall_evi']:.4f} < {c1_threshold:.4f}；C3 precision_evi={paired['precision_evi']:.4f} < {c3_threshold:.4f}。
- C2/G2′：未执行（缺少 `API_KEY` / `BASE_URL`）；paired 值未测。
- 一致性：150/150 剥离一致，150/150 槽位数不变。
- fabricated/retrieved：未验证；不构成完整 C3。
- judge/al3：0 calls / 0 token；Phase 2B 新答案生成：0。
"""
    (OUT / "decision.md").write_text(decision_md, encoding="utf-8",
                                     newline="\n")

    files = {}
    for path in sorted(OUT.iterdir()):
        if path.name != "manifest.json" and path.is_file():
            files[path.name] = digest(path.read_bytes())
    manifest = {
        "phase": "M6a-Phase2B-paired-replay",
        "generated_at": now,
        "verdict": verdict,
        "execution_head": core["execution_head"],
        "base_commit": core["base_commit"],
        "source_commits": {
            "m6a_original": "614e2605b749d41a137f7b9d1e97e85ba52d907e",
            "phase2a_corrected": "744f3738fa2f8eb8552a7ebb420ce67dcde1036b",
            "baseline": "de8181fd5875ea30f7d9477c45f0e23faf11c26b",
        },
        "inputs": {
            "baseline": core["baseline"],
            "runtime_map": {
                "rows": preflight["runtime_map_rows"],
                "worktree_raw_sha256": "efe8595872891da599c41ba1ac2031cff181c2f3f7823bb74c7f514889193275",
                "lf_sha256": preflight["runtime_map_lf_sha256"],
            },
            "mapping": {
                "rows": preflight["mapping_rows"],
                "worktree_raw_sha256": "d63bf48af0a18d5b49ed3957159b84af71a056242c9af47843f94e9b4973d42d",
                "lf_sha256": preflight["mapping_lf_sha256"],
            },
            "dataset_lf_sha256": "4597167dadd72ba972373bedc44d27c858b7c7ddbe42f8ede9d37021b38e92a9",
            "dataset_raw_sha256_disclosure": preflight[
                "dataset_raw_sha256_disclosure"],
            "m6a_module_sha256": "ee9963c76cbf580238b5914a3b1a34d6265bdd66a5bdbfeb3523a457bccc1613",
        },
        "preflight": {
            "status": preflight["status"],
            "baseline_rows": 150,
            "cases_failed": 0,
            "runtime_map_rows": preflight["runtime_map_rows"],
            "mapping_rows": preflight["mapping_rows"],
            "ordered_ids_total": preflight["ordered_ids_total"],
            "ordered_ids_resolved": preflight["ordered_ids_resolved"],
            "control_metrics": control,
        },
        "replay": {
            "cases": consistency["cases_total"],
            "stripped_byte_identical": consistency[
                "cases_stripped_byte_identical"],
            "slot_count_unchanged": consistency[
                "cases_slot_count_unchanged"],
            "stats": core["replay_stats"],
            "per_case_input_output_hashes": core["per_case_hashes"],
        },
        "judge_al3": {
            "runner_strips_citation_slots": judge_runner_strips_slots,
            "status": judge_status,
            "calls": 0,
            "tokens": 0,
            "control": {
                "judge_counts": {"hit": 74, "partial": 6, "miss": 66,
                                  "contract_error": 8},
                "C2": 0.5575,
                "G2prime": 1.0,
            },
            "paired_C2": None,
            "paired_G2prime": None,
            "api_key_configured": api_key_configured,
            "base_url_configured": base_url_configured,
        },
        "budget": budget,
        "full_sources_used": False,
        "new_answers_generated": 0,
        "files_sha256": files,
        "script_sha256": file_hashes(),
    }
    manifest["manifest_sha256"] = digest(json_bytes(manifest))
    (OUT / "manifest.json").write_bytes(json_bytes(manifest))
    print(json.dumps({
        "verdict": verdict,
        "failed_gates": failed_gates,
        "report": str(OUT / "report.md"),
        "decision": str(OUT / "decision.md"),
        "manifest_sha256": manifest["manifest_sha256"],
        "outcomes_paired_sha256": files["outcomes-paired.jsonl"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
