"""Phase 6-C1.1 — v2.0.11 跨文档检索消融「审计语义修正」（只读，不重跑实验）。

范围：对 Phase 6-C1 产物（``evaluation/product-baselines/
v2.0.11-cross-document-ablation/``）做**有限报告/产物正确性修正**，不
迭代测试集/语料/v2.0.11，也不重新跑检索。两项语义修正：

1. **运行一致性表述**：原 C1 记录不能支持「两次完整独立运行一致」的
   表述——如实更正为：``NO_PROMOTION`` 结论与 cross-document recall@5
   失败方向在两次独立完整运行间稳定，但 raw ranking / 逐案例指标 /
   部分候选整体聚合指标存在**已记录的 HNSW 非确定性差异**（跨运行
   per-case 差异与运行内第二次构建的整体指标差异均取自原 manifest）。
2. **data_quality 与 promotion_eligibility 分离**：原
   ``data-quality-report.json`` 为 ``passed=true`` / ``error_count=0``，
   但 30 条 checks 中追加了 4 条 ``ok=false`` 的 gate 条件（追加于
   error_count 计算之后）——「全部通过」的表述不成立。更正后的数据
   模型：``data_quality``（核心完整性/唯一性/指标复算/引用完整性/谱系
   与 manifest 闭环）与 ``promotion_eligibility``（6 条预先锁定的 gate
   条件、4 条未通过、决策 ``NO_PROMOTION``）分离；失败 gate 不是
   data-quality 失败，也不混入 data-quality checks；
   ``data_quality.passed`` **不暗示** promotion 通过。

fail-closed：先复算原 C1 manifest self-hash 与全部 6 个原 C1 outputs
字节 SHA（对照原 manifest 记录的 outputs SHA）；任一漂移 → 零输出，
退出码 2。

红线：不覆盖/重跑原 C1 产物（原目录字节不动）；本脚本纯 stdlib（不导入
src.* / chromadb / 检索 / LLM 链路），无网络、无 Chroma 建索引、无检索
重跑、无 overlay/active/split/locked/v2.1 产物；冻结 revision、6-A、
B0、B0.1 字节不动；默认产品检索路径不变；不 stage/commit/push。

产物（新建且仅写入）：``evaluation/product-baselines/
v2.0.11-cross-document-ablation-audit-correction/`` 共 4 个：
correction-summary.json / corrected-data-quality-report.json /
CORRECTION.md / manifest.json（项目 canonical self-hash 约定；manifest
无时间戳 → 两次构建逐字节一致）。

``data-analytics:analyze-data-quality`` 实际检查：zcode 运行环境不可用
（本次会话可用技能列表、``~/.zcode/skills``、``~/.agents/skills``、插件
目录均无此技能）——不能声称所有环境均不可用；实施等价的确定性机械复算。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── 目录常量 ──────────────────────────────────────────────────────────
ORIGINAL_DIR = (
    REPO_ROOT
    / "evaluation/product-baselines/v2.0.11-cross-document-ablation"
)
CORRECTION_DIR = (
    REPO_ROOT
    / "evaluation/product-baselines/v2.0.11-cross-document-ablation-audit-correction"
)

# 原 C1 的 6 个非 manifest 产物（字节 SHA 逐项复算）
ORIGINAL_OUTPUT_FILES = (
    "ablation-summary.json",
    "per-case-results-baseline.jsonl",
    "per-case-results-candidate.jsonl",
    "cross-document-analysis.md",
    "selection-decision.md",
    "data-quality-report.json",
)

# 本阶段产物（白名单，测试依赖）
CORRECTION_OUTPUT_FILES = (
    "correction-summary.json",
    "corrected-data-quality-report.json",
    "CORRECTION.md",
    "manifest.json",
)

_COMPARE_METRIC_KEYS = (
    "recall@5", "recall@10", "recall@20",
    "ndcg@5", "ndcg@10", "ndcg@20", "mrr",
    "source_recall@5", "source_recall@10", "source_recall@20",
)

_GATE_DECISIONS = ("EXPERIMENT_PROMISING", "NO_PROMOTION")

# 禁止措辞：更正包文档/总结不得再出现（CHANGELOG 同步修正）
_FORBIDDEN_PHRASES = ("两次完整独立运行一致", "30 项全过")

# data-analytics skill 实际检查证据（zcode 运行环境不可用，等价复算替代）
_SKILL_EVIDENCE = (
    "data-analytics:analyze-data-quality 实际检查：zcode 运行环境不可用"
    "（本次会话可用技能列表、~/.zcode/skills 仅 brainstorming/"
    "test-driven-development、~/.agents/skills 仅 browser-skill、插件目录"
    "均无 data-analytics）——不能声称所有环境均不可用；实施等价的确定性"
    "机械复算"
)

_NOT_MEASURED = {
    "answer_quality": {
        "measured": False,
        "reason": "C1.1 只做报告语义修正，不重跑检索、不调用生成模型；"
                  "answer-quality 无真值无产出（沿用 C1 声明）",
    },
    "citation_faithfulness": {
        "measured": False,
        "reason": "citation-faithfulness 依赖生成判定与人工审计，未测（沿用 C1 声明）",
    },
    "refusal_accuracy": {
        "measured": False,
        "reason": "answer 级拒答精度依赖生成判定，未测（沿用 C1 声明）",
    },
}


class CorrectionDrift(Exception):
    """原 C1 manifest/outputs 漂移或 gate 事实不一致——fail-closed，零产物。"""


# ── 哈希与 manifest 约定（与项目既有 runner 同构）────────────────────

def sha256_bytes(path: Path) -> str:
    """字节 SHA-256（只读输入的身份标识）。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_json(obj: dict) -> str:
    """项目 manifest 规范序列化：indent=1, sort_keys, ensure_ascii=False + 换行。"""
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def self_hash(obj: dict) -> str:
    """先移除 ``manifest_sha256`` 再计算 self-hash（既有约定）。"""
    d = dict(obj)
    d.pop("manifest_sha256", None)
    return hashlib.sha256(canonical_json(d).encode("utf-8")).hexdigest()


def _git_head() -> dict:
    """代码身份（与既有 runner 同构；dirty 标志如实记录）。"""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            cwd=REPO_ROOT, timeout=10,
        ).stdout.strip()
    except Exception:
        head = ""
    try:
        porcelain = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True,
            cwd=REPO_ROOT, timeout=10,
        ).stdout
        dirty = bool(porcelain.strip())
    except Exception:
        dirty = None
    return {"head": head, "dirty": dirty}


# ── 原 C1 核验（fail-closed 依据）─────────────────────────────────────

def verify_original_ablation(original_dir: Path) -> dict:
    """复算原 C1 manifest self-hash + 6 个 outputs 字节 SHA。

    输出 SHA 以原 manifest 记录的 ``outputs`` 段为基准（文件被改动必然
    漂移）；manifest 缺失/JSON 损坏亦记 drift。纯只读。
    """
    original_dir = Path(original_dir)
    checks: list[dict] = []
    manifest: dict = {}
    summary: dict = {}
    dq: dict = {}
    manifest_path = original_dir / "manifest.json"

    if not manifest_path.is_file():
        checks.append({
            "name": "original-c1-manifest.json", "kind": "missing",
            "status": "missing", "expected": None, "actual": None,
            "path": str(manifest_path),
        })
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            checks.append({
                "name": "original-c1-manifest.json", "kind": "json",
                "status": "mismatch", "expected": None,
                "actual": f"JSONDecodeError: {exc}", "path": str(manifest_path),
            })
            manifest = {}
        else:
            actual = self_hash(manifest)
            checks.append({
                "name": "original-c1-manifest.json self-hash",
                "kind": "manifest_self_hash",
                "status": ("ok" if actual == manifest.get("manifest_sha256")
                           else "mismatch"),
                "expected": manifest.get("manifest_sha256"), "actual": actual,
                "path": str(manifest_path),
            })

    recorded = manifest.get("outputs", {})
    for name in ORIGINAL_OUTPUT_FILES:
        path = original_dir / name
        actual_sha = sha256_bytes(path) if path.is_file() else None
        expected = recorded.get(name)
        checks.append({
            "name": name, "kind": "output",
            "status": ("ok" if expected is not None and actual_sha == expected
                       else ("missing" if actual_sha is None
                             else ("unrecorded" if expected is None
                                   else "mismatch"))),
            "expected": expected, "actual": actual_sha, "path": str(path),
        })

    # 解析 summary / dq（gate 事实与确定性证据的来源；损坏亦漂移）
    for name in ("ablation-summary.json", "data-quality-report.json"):
        path = original_dir / name
        if not path.is_file():
            continue
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            checks.append({
                "name": f"parse:{name}", "kind": "json", "status": "mismatch",
                "expected": None, "actual": f"JSONDecodeError: {exc}",
                "path": str(path),
            })
        else:
            if name == "ablation-summary.json":
                summary = parsed
            else:
                dq = parsed

    drift = [
        {k: c[k] for k in ("name", "kind", "status", "expected", "actual",
                           "path") if k in c}
        for c in checks if c["status"] != "ok"
    ]
    return {
        "verified": not drift, "checks": checks, "drift": drift,
        "manifest": manifest, "summary": summary, "dq": dq,
        "original_dir": original_dir,
    }


# ── gate 事实提取（交叉核验后原样转述）──────────────────────────────

def extract_gate_facts(summary: dict, dq: dict) -> dict:
    """机械提取 gate 事实并交叉核验：

    - 恰 6 条 conditions；decision ∈ {EXPERIMENT_PROMISING, NO_PROMOTION}；
    - conditions 中 ok=false 的 id 集 == 记录的 failures（严格一致）；
    - 原 DQ checks 中 ``gate.*`` 的 false 项 == ``gate.<failure>`` 集
      （原报告「passed 但 checks 含 false gate」结构的旁证）。

    任何不一致 → ``verified=False``（fail-closed，零产物）。
    """
    problems: list[str] = []
    gate = summary.get("gate", {}) if summary else {}
    conditions = list(gate.get("conditions", []))
    failures = list(gate.get("failures", []))
    decision = gate.get("decision")

    if not summary:
        problems.append("ablation-summary.json 缺失或不可解析")
    if len(conditions) != 6:
        problems.append(f"gate conditions={len(conditions)} 期望=6")
    if decision not in _GATE_DECISIONS:
        problems.append(f"gate decision={decision!r}")
    derived = [c["id"] for c in conditions if not c.get("ok")]
    if sorted(derived) != sorted(failures):
        problems.append(f"conditions 中未通过条件 {sorted(derived)} "
                        f"!= 记录 failures {sorted(failures)}")
    dq_gate_false = [
        c["name"] for c in dq.get("checks", [])
        if str(c.get("name", "")).startswith("gate.") and not c.get("ok")
    ]
    expected_dq_false = [f"gate.{f}" for f in failures]
    if sorted(dq_gate_false) != sorted(expected_dq_false):
        problems.append(f"原 DQ 中 false gate checks {sorted(dq_gate_false)} "
                        f"!= 期望 {sorted(expected_dq_false)}")

    return {
        "verified": not problems, "problems": problems,
        "decision": decision, "failures": failures, "conditions": conditions,
        "dq_gate_false_count": len(dq_gate_false),
    }


# ── 确定性事实（全部取自原 C1 记录，不重算）──────────────────────────

def extract_determinism_facts(manifest: dict, summary: dict) -> dict:
    """机械提取已记录的 HNSW 非确定性证据：

    - 运行内第二次独立构建（build2）vs 主构建的整体聚合指标差异（双臂）；
    - 运行内跨构建 raw / metric per-case 差异计数；
    - 跨运行（prior_run）per-case 差异计数与聚合 Δ；
    - cd recall@5 跨构建噪声量级。
    """
    det = manifest.get("determinism", {}) or {}
    build2 = det.get("build2", {}) or {}
    b1 = (summary.get("baseline", {}).get("metrics", {})
          .get("overall", {})) if summary else {}
    c1 = (summary.get("candidate", {}).get("metrics", {})
          .get("overall", {})) if summary else {}
    b2 = build2.get("baseline_metrics", {}) or {}
    c2 = build2.get("candidate_metrics", {}) or {}

    def _deltas(a: dict, b: dict) -> dict:
        return {k: round(b.get(k, 0) - a.get(k, 0), 6)
                for k in _COMPARE_METRIC_KEYS if k in a and k in b}

    b_deltas = _deltas(b1, b2)
    c_deltas = _deltas(c1, c2)
    prior = (manifest.get("verification", {}).get("prior_run", {}) or {})

    return {
        "cd_recall5_noise": det.get("cd_recall5_noise"),
        "in_run_second_build": {
            "baseline_aggregate_deltas": b_deltas,
            "baseline_max_abs_delta": max(
                (abs(v) for v in b_deltas.values()), default=0.0),
            "candidate_aggregate_deltas": c_deltas,
            "candidate_max_abs_delta": max(
                (abs(v) for v in c_deltas.values()), default=0.0),
            "baseline_raw_difference_count": (det.get("baseline", {}) or {})
            .get("difference_count"),
            "candidate_raw_difference_count": (det.get("candidate", {}) or {})
            .get("difference_count"),
            "baseline_metric_difference_count": (det.get("baseline", {}) or {})
            .get("metric_difference_count"),
            "candidate_metric_difference_count": (det.get("candidate", {}) or {})
            .get("metric_difference_count"),
        },
        "cross_run": {
            "per_case_diff_count": prior.get("per_case_diff_count"),
            "aggregate_deltas": prior.get("aggregate_deltas"),
            "prior_manifest_sha256": prior.get("prior_manifest_sha256"),
        },
    }


# ── 更正后的数据模型（data_quality / promotion_eligibility 分离）──────

def build_corrected_data_quality(original_dq: dict, gate_facts: dict) -> dict:
    """分离数据质量与 promotion 资格。

    - ``data_quality``：只含核心检查（原 checks 中非 ``gate.*`` 项），
      ``passed`` 由这些检查**重新计算**（passed=true 时核心 checks 必无
      false，构造上保证）；失败 gate 不混入。
    - ``promotion_eligibility``：6 条 gate 条件、失败条件与决策；附带
      gate 结构检查（conditions 恰 6 条 / decision 已记录）。
    """
    core = [dict(c) for c in original_dq.get("checks", [])
            if not str(c.get("name", "")).startswith("gate.")]
    errors = [c for c in core if not c["ok"]]
    return {
        "data_quality": {
            "passed": not errors,
            "error_count": len(errors),
            "errors": [f"{c['name']}: {c.get('detail', '')}" for c in errors],
            "warning_count": 0,
            "warnings": [],
            "checks": core,
            "note": (_SKILL_EVIDENCE + "；data_quality 只含核心完整性/唯一性/"
                     "指标复算/引用完整性/谱系与 manifest 闭环检查，"
                     "不含 promotion gate 条件"),
        },
        "promotion_eligibility": {
            "decision": gate_facts["decision"],
            "failures": list(gate_facts["failures"]),
            "conditions": gate_facts["conditions"],
            "checks": [
                {"name": "gate.conditions_complete",
                 "ok": len(gate_facts["conditions"]) == 6,
                 "detail": f"conditions={len(gate_facts['conditions'])}"},
                {"name": "gate.decision_recorded",
                 "ok": gate_facts["decision"] in _GATE_DECISIONS,
                 "detail": gate_facts["decision"]},
            ],
            "note": ("promotion gate（6 项条件，预先锁定，机械判定）是实验"
                     "决策结果：任一条件失败 → NO_PROMOTION；失败 gate "
                     "**不是 data-quality 失败**，data_quality.passed 也"
                     "**不意味着** promotion 通过；失败条件只出现在本段，"
                     "不混入 data_quality.checks"),
        },
        "note": _SKILL_EVIDENCE,
    }


# ── 修正总结 / 文档渲染 ──────────────────────────────────────────────

def build_correction_summary(*, report: dict, gate_facts: dict,
                             determinism_facts: dict,
                             corrected_dq: dict) -> dict:
    """两份语义修正的 before/after 总结（不含被禁止的措辞）。"""
    det = determinism_facts
    inrun = det["in_run_second_build"]
    cross = det["cross_run"]
    cand_delta_str = ", ".join(
        f"{k} Δ{v:+.6g}" for k, v in inrun["candidate_aggregate_deltas"].items()
        if abs(v) >= 1e-6) or "无差异"
    cross_aggregates = cross.get("aggregate_deltas") or {}
    cross_max = max((abs(v) for d in cross_aggregates.values()
                     for v in (d.values() if isinstance(d, dict) else [d])),
                    default=0.0)

    corr_determinism = {
        "id": "run_consistency_wording",
        "title": ("运行一致性表述：NO_PROMOTION 结论与失败方向稳定，"
                  "raw ranking / 逐案例 / 部分聚合指标存在已记录的 HNSW "
                  "非确定性差异"),
        "original_statement": (
            "原 CHANGELOG/记录以「运行一致」概括两次独立完整运行（并称基线"
            "聚合与 hardened 相同、cd recall@5 跨构建噪声为 0），未区分"
            "「结论方向稳定」与「逐案例/部分聚合指标一致」——该表述不成立"),
        "corrected_statement": (
            f"NO_PROMOTION 结论与 cross-document recall@5 失败方向在两次"
            f"独立完整运行间稳定；但 raw ranking（跨运行 per-case 差异 "
            f"baseline {cross['per_case_diff_count'].get('baseline')} / "
            f"candidate {cross['per_case_diff_count'].get('candidate')}；"
            f"运行内第二次构建 raw 差异 baseline "
            f"{inrun['baseline_raw_difference_count']} / candidate "
            f"{inrun['candidate_raw_difference_count']}）、逐案例指标"
            f"（运行内 metric 差异 baseline "
            f"{inrun['baseline_metric_difference_count']} / candidate "
            f"{inrun['candidate_metric_difference_count']} case）与候选"
            f"整体聚合指标（运行内 build2 相对主构建：{cand_delta_str}，"
            f"max|Δ|={inrun['candidate_max_abs_delta']:.6g}；跨运行聚合 Δ "
            f"max|Δ|={cross_max:.6g}）存在已记录的 HNSW 非确定性差异——"
            f"任何「完全一致/逐位一致」的表述均不成立"),
        "evidence": det,
    }

    original_checks = original_dq_for_evidence(corrected_dq, report)
    corr_dq = {
        "id": "data_quality_gate_separation",
        "title": ("分离 data_quality 与 promotion_eligibility：失败 gate "
                  "不是数据质量失败，passed 不暗示 promotion 通过"),
        "original_statement": (
            f"原 data-quality-report.json passed={original_checks['passed']} "
            f"/ error_count={original_checks['error_count']}，但 "
            f"{original_checks['check_count']} 条 checks 中追加了 "
            f"{gate_facts['dq_gate_false_count']} 条 ok=false 的 gate 条件"
            f"（追加于 error_count 计算之后）——「全部通过」的表述不成立"),
        "corrected_statement": (
            f"核心 data-quality 检查（完整性/唯一性/指标复算/引用完整性/"
            f"谱系与 manifest 闭环）共 {len(corrected_dq['data_quality']['checks'])} "
            f"项全部通过；promotion gate 6 条中 {len(gate_facts['failures'])} "
            f"条未通过 → NO_PROMOTION；失败 gate 是实验决策结果，不是 "
            f"data-quality 失败，也不得混入 data-quality checks"),
        "evidence": {
            "original": original_checks,
            "corrected": {
                "core_check_count": len(corrected_dq["data_quality"]["checks"]),
                "data_quality_passed": corrected_dq["data_quality"]["passed"],
                "promotion_failures": list(gate_facts["failures"]),
            },
        },
    }

    summary = {
        "task": "v2.0.11-cross-document-ablation-audit-correction",
        "phase": "C1.1",
        "audit_version": "1.0",
        "scope": "报告/产物语义修正（只读审计；不重跑实验、不改原 C1 产物）",
        "original_c1": {
            "dir": str(report["original_dir"]),
            "verified": report["verified"],
            "checks": len(report["checks"]),
            "manifest_sha256": report["manifest"].get("manifest_sha256"),
            "outputs": {name: sha256_bytes(Path(report["original_dir"]) / name)
                        for name in ORIGINAL_OUTPUT_FILES},
        },
        "semantic_corrections": [corr_determinism, corr_dq],
        "corrected_verdict": {
            "data_quality": {
                "passed": corrected_dq["data_quality"]["passed"],
                "error_count": corrected_dq["data_quality"]["error_count"],
                "core_check_count": len(
                    corrected_dq["data_quality"]["checks"]),
            },
            "promotion_eligibility": {
                "decision": gate_facts["decision"],
                "failures": list(gate_facts["failures"]),
            },
        },
        "determinism": det,
        "declarations": {
            "llm_called": False,
            "network_used": False,
            "chroma_index_built": False,
            "retrieval_rerun": False,
            "overlay_generated": False,
            "split_created": False,
            "v2_1_entered": False,
            "original_c1_overwritten": False,
        },
        "not_measured": _NOT_MEASURED,
        "skill_evidence": _SKILL_EVIDENCE,
    }
    summary["manifest_sha256"] = self_hash(summary)
    return summary


def original_dq_for_evidence(corrected_dq: dict, report: dict) -> dict:
    """原 DQ 报告的核验证据（check 数/通过数等）。"""
    original_dq = report.get("dq", {})
    checks = original_dq.get("checks", [])
    return {
        "passed": original_dq.get("passed"),
        "error_count": original_dq.get("error_count"),
        "check_count": len(checks),
        "gate_named_check_count": sum(
            1 for c in checks if str(c.get("name", "")).startswith("gate.")),
    }


def render_correction_md(summary: dict) -> str:
    """CORRECTION.md：两项修正的 before/after + 核验 + 边界声明。"""
    det = summary["determinism"]
    inrun = det["in_run_second_build"]
    cross = det["cross_run"]
    corr = {c["id"]: c for c in summary["semantic_corrections"]}
    verdict = summary["corrected_verdict"]
    lines = [
        "# Audit Correction — Phase 6-C1.1（v2.0.11 跨文档检索消融）",
        "",
        "## 范围",
        "",
        "- 对 Phase 6-C1 产物的**报告/产物语义修正**（只读审计）：不重跑实验、"
        "不迭代测试集/语料/v2.0.11。",
        "- 原 C1 目录与全部 7 个原文件字节不变：本包只读核验并记录 SHA，"
        "绝不覆盖。",
        "- 无 LLM / 网络 / Chroma 建索引 / 检索重跑 / overlay/active/split/"
        "locked/v2.1 产物；默认产品检索路径不变。",
        "",
        "## 语义修正 1：运行一致性表述",
        "",
        f"- **原表述**：{corr['run_consistency_wording']['original_statement']}。",
        f"- **更正后**：{corr['run_consistency_wording']['corrected_statement']}。",
        "- 证据（全部取自原 C1 manifest/summary 记录，本包不重算）：",
        f"  - 运行内第二次独立构建整体指标差异：基线 max|Δ|="
        f"{inrun['baseline_max_abs_delta']:.6g}，候选 max|Δ|="
        f"{inrun['candidate_max_abs_delta']:.6g}；",
        f"  - 运行内跨构建 raw 差异：基线 {inrun['baseline_raw_difference_count']}"
        f" / 候选 {inrun['candidate_raw_difference_count']}；metric 差异："
        f"基线 {inrun['baseline_metric_difference_count']}"
        f" / 候选 {inrun['candidate_metric_difference_count']} case；",
        f"  - 跨运行 per-case 差异：baseline {cross['per_case_diff_count'].get('baseline')}"
        f" / candidate {cross['per_case_diff_count'].get('candidate')}；"
        f"cd recall@5 跨构建噪声 {det['cd_recall5_noise']}。",
        "",
        "## 语义修正 2：data_quality 与 promotion_eligibility 分离",
        "",
        f"- **原表述**：{corr['data_quality_gate_separation']['original_statement']}。",
        f"- **更正后**：{corr['data_quality_gate_separation']['corrected_statement']}。",
        "- 数据模型（corrected-data-quality-report.json）：",
        "  - `data_quality`：核心完整性/唯一性/指标复算/引用完整性/谱系与 "
        "manifest 闭环检查，`passed` 由这些检查重新计算——passed=true 时 "
        "核心 checks 必无 false；",
        "  - `promotion_eligibility`：6 条预先锁定的 gate 条件、失败条件与 "
        "决策——失败 gate 不是 data-quality 失败，也不混入 "
        "`data_quality.checks`；`data_quality.passed` **不暗示** promotion "
        "通过。",
        "",
        "## 原 C1 核验",
        "",
        f"- manifest self-hash：`{summary['original_c1']['manifest_sha256']}`"
        "（复算一致）；",
        f"- 6 个原 C1 outputs 字节 SHA 全部复算一致（{summary['original_c1']['checks']}"
        " 项检查；明细见 manifest.json inputs 与 correction-summary.json）。",
        "",
        "## 最终判定（更正后，与原 C1 一致）",
        "",
        f"- 核心数据质量：{'通过' if verdict['data_quality']['passed'] else '未通过'}。",
        f"- Promotion gate：{len(verdict['promotion_eligibility']['failures'])}/6"
        f" 条未通过（{verdict['promotion_eligibility']['failures']}）→ "
        f"**{verdict['promotion_eligibility']['decision']}**。",
        f"- 默认产品检索策略**未改变**（候选仅记录于消融产物，任何采用须经"
        "后续独立阶段决策）。",
        f"- v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、"
        "human_reviewed=false），不是 active、release 或人工批准。",
        "",
        "## 未测项与限制",
        "",
        "- not_measured：answer quality / citation faithfulness / "
        "answer-level refusal accuracy（沿用原 C1 声明，见 manifest）。",
        f"- `data-analytics:analyze-data-quality` 实际检查：zcode 运行环境"
        "不可用（本次会话可用技能列表、`~/.zcode/skills`、`~/.agents/skills`、"
        "插件目录均无）——不能声称所有环境均不可用；实施等价确定性复算。",
        "- 本包不重算检索指标；全部数字取自原 C1 记录并如实转述。",
        "- 未 stage/commit/push；既有脏工作区保留。",
    ]
    return "\n".join(lines) + "\n"


# ── 产物写入 ──────────────────────────────────────────────────────────

def write_package(
    *,
    out_dir: Path,
    original_dir: Path,
    correction_summary: dict,
    corrected_dq: dict,
    gate_facts: dict,
    determinism_facts: dict,
    md_text: str,
) -> dict:
    """写 4 个产物并返回 manifest（self-hash；无时间戳 → 逐字节一致）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    original_dir = Path(original_dir)

    (out_dir / "correction-summary.json").write_text(
        canonical_json(correction_summary), encoding="utf-8")
    (out_dir / "corrected-data-quality-report.json").write_text(
        canonical_json(corrected_dq), encoding="utf-8")
    (out_dir / "CORRECTION.md").write_text(md_text, encoding="utf-8")

    inputs: dict[str, dict] = {
        "original-c1-manifest.json": {
            "path": str(original_dir / "manifest.json"),
            "sha256": sha256_bytes(original_dir / "manifest.json"),
        },
    }
    for name in ORIGINAL_OUTPUT_FILES:
        inputs[name] = {
            "path": str(original_dir / name),
            "sha256": sha256_bytes(original_dir / name),
        }

    manifest = {
        "task": "v2.0.11-cross-document-ablation-audit-correction",
        "phase": "C1.1",
        "audit_version": "1.0",
        "original_c1": {
            "dir": str(original_dir),
            "manifest_sha256": correction_summary["original_c1"]
            ["manifest_sha256"],
            "outputs": {name: sha256_bytes(original_dir / name)
                        for name in ORIGINAL_OUTPUT_FILES},
        },
        "inputs": inputs,
        "outputs": {
            name: sha256_bytes(out_dir / name)
            for name in CORRECTION_OUTPUT_FILES if name != "manifest.json"
        },
        "semantic_corrections": correction_summary["semantic_corrections"],
        "data_quality": {
            "passed": corrected_dq["data_quality"]["passed"],
            "error_count": corrected_dq["data_quality"]["error_count"],
        },
        "promotion_eligibility": {
            "decision": gate_facts["decision"],
            "failures": list(gate_facts["failures"]),
        },
        "determinism": determinism_facts,
        "declarations": correction_summary["declarations"],
        "code": _git_head(),
        "dependencies": {"python": sys.version.split()[0]},
        "not_measured": _NOT_MEASURED,
    }
    manifest["manifest_sha256"] = self_hash(manifest)
    (out_dir / "manifest.json").write_text(canonical_json(manifest),
                                           encoding="utf-8")
    return manifest


# ── 编排 ──────────────────────────────────────────────────────────────

def run_correction(*, original_dir: Path, out_dir: Path) -> dict:
    """执行 C1.1 审计语义修正并写出 4 个产物。

    顺序（任一漂移 → CorrectionDrift，零产物）：
    1. 原 C1 manifest self-hash + 6 outputs 字节 SHA 复算；
    2. gate 事实提取与交叉核验；
    3. 确定性证据提取 → 更正数据模型 → 总结 → 文档；
    4. 禁止措辞自检（产物中出现即中止）；
    5. 写 4 产物（manifest self-hash 闭环）。
    """
    original_dir = Path(original_dir)
    out_dir = Path(out_dir)
    if out_dir == original_dir or original_dir in out_dir.parents:
        raise ValueError("out_dir 不得是原 C1 目录或其子目录")

    report = verify_original_ablation(original_dir)
    if not report["verified"]:
        raise CorrectionDrift("original C1 drift: " + json.dumps(
            report["drift"], ensure_ascii=False))

    gate_facts = extract_gate_facts(report["summary"], report["dq"])
    if not gate_facts["verified"]:
        raise CorrectionDrift("gate facts inconsistency: " + json.dumps(
            gate_facts["problems"], ensure_ascii=False))

    determinism_facts = extract_determinism_facts(
        report["manifest"], report["summary"])
    corrected_dq = build_corrected_data_quality(report["dq"], gate_facts)
    correction_summary = build_correction_summary(
        report=report, gate_facts=gate_facts,
        determinism_facts=determinism_facts, corrected_dq=corrected_dq)
    md_text = render_correction_md(correction_summary)

    # 禁止措辞自检（fail-closed）
    for text, where in (
            (md_text, "CORRECTION.md"),
            (json.dumps(correction_summary, ensure_ascii=False),
             "correction-summary.json"),
            (json.dumps(corrected_dq, ensure_ascii=False),
             "corrected-data-quality-report.json")):
        for phrase in _FORBIDDEN_PHRASES:
            if phrase in text:
                raise CorrectionDrift(
                    f"forbidden phrase {phrase!r} leaked into {where}")

    manifest = write_package(
        out_dir=out_dir, original_dir=original_dir,
        correction_summary=correction_summary, corrected_dq=corrected_dq,
        gate_facts=gate_facts, determinism_facts=determinism_facts,
        md_text=md_text,
    )
    return {
        "status": "ok",
        "manifest": manifest,
        "correction_summary": correction_summary,
        "corrected_dq": corrected_dq,
        "gate_facts": gate_facts,
        "determinism": determinism_facts,
        "verification": report,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI。退出码：0=成功；2=原 C1 漂移 / gate 不一致（零产物）；1=其他。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase 6-C1.1: v2.0.11 ablation audit correction")
    parser.add_argument("--original-dir", type=Path, default=ORIGINAL_DIR)
    parser.add_argument("--output", type=Path, default=CORRECTION_DIR)
    args = parser.parse_args(argv)

    try:
        result = run_correction(original_dir=args.original_dir,
                                out_dir=args.output)
    except CorrectionDrift as exc:
        print(f"FAIL-CLOSED: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"FAIL-CLOSED: invalid configuration: {exc}", file=sys.stderr)
        return 1
    except Exception:
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1

    verdict = result["corrected_dq"]
    print(f"audit correction complete: {args.output}")
    print(f"  original C1 verified: "
          f"{result['verification']['verified']} "
          f"({len(result['verification']['checks'])} checks)")
    print(f"  data_quality passed={verdict['data_quality']['passed']} "
          f"error_count={verdict['data_quality']['error_count']}")
    print(f"  promotion_eligibility decision="
          f"{result['gate_facts']['decision']} "
          f"failures={result['gate_facts']['failures']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
