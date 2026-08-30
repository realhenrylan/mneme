"""Corpus v2.1 activate —— 把人工终审 overlay 落为 v2.1 正式数据集。

背景与定位：v2 草稿（150 case）经 2026-08-29 人工终审（授权代理复核
zcode-agent-2026-08-29 + owner 同日对 8 条阻断行的仲裁批示）产生
``HUMAN_REVIEWED`` 真值覆盖层（overlay）。本工具在 owner 授权下执行
「启用 v2.1 数据集」：overlay 成为**最新权威真值层**，取代 v2.0.x 冻结
候选与历史 rulings 中与之冲突的旧处置（supersession，历史账本永不
改写），据此生成 v2.1 正式数据集版本。

设计原则（与 corpus_v2_human_review_apply.py / corpus_v2_v21_final_
rulings_apply.py 契约对齐）：

- **纯确定性**：无网络、无 LLM/API、无随机数、无运行时时间戳（激活
  日期为常量）；相同输入两次 run 产物逐字节一致（run 内置双构建
  字节断言，验收时另做外部文件级双跑比对）。
- **fail-closed 四门**（任一失败 → 整体报错且**零输出**）：
  1. overlay manifest 状态/计数/SHA 链：status=HUMAN_REVIEWED、
     decision_counts 恰为 150/0/0、重算 overlay.json SHA-256 与
     manifest.overlay_sha256 一致、manifest.inputs 全量文件复算；
  2. 草稿 id 集合 == overlay case_id 集合（双向差集为空，150 条）；
  3. 逐 case 五个真值字段一致（should_refuse / relevance_level /
     acceptable_answer_points / relevant_source_ids / relevant_chunk_ids，
     列表顺序敏感比较；「仅顺序差异」也停止并如实记录）；
  4. 6 条 final-rulings case（zh-023 / multi-012 / mixed-022 / en-052 /
     mixed-030 / mixed-033）必须全部在池内。
- **只读冻结资产**：草稿、overlay、rulings 账本、v2.0.x 修订树一律
  只读；本工具只写新产物目录与 v2.1 发布文件。
- **诚实记录**：review_status 用 ``human_review_confirmed_agent_
  adjudicated``——终审 confirmed 由授权代理执行 + owner 仲裁，绝不
  伪称真人逐条复核；reviewer 如实记录代理标识。
- **透传不重排**：数据集顶层字段（含全部真值字段）原样透传，唯一
  改动是 annotation 内三个审阅字段；行序、键序保持草稿原序。

产物目录：evaluation/datasets/v2/revisions/v2.1-human-review-activation/
（v2.1-dataset.jsonl + manifest.json + activation-report.md），并将
150 行发布到 evaluation/datasets/v2.1.jsonl（发布前用 evaluation/
schema.py 的 load_dataset 做投影自检；schema 不兼容点记录在激活
报告中，绝不修改 schema 本身）。

CLI
---
::

    python scripts/corpus_v2_v21_activate.py activate
        [--out DIR] [--publish PATH | --no-publish]
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

V2_DIR = ROOT / "evaluation/datasets/v2"
DRAFT_PATH = V2_DIR / "annotations/v2-cases-draft.jsonl"
OVERLAY_PATH = V2_DIR / "human-review/human-reviewed-truth-overlay.json"
OVERLAY_MANIFEST_PATH = \
    V2_DIR / "human-review/human-reviewed-truth-overlay-manifest.json"
RULINGS_LEDGER_PATH = \
    V2_DIR / "revisions/v2.1-owner-rulings-batch1/rulings-ledger.jsonl"
FINAL_RULINGS_PATH = V2_DIR / (
    "revisions/v2.1-owner-rulings-batch1/final-rulings-batch2/"
    "final-rulings-ledger.jsonl")
OUT_DIR = V2_DIR / "revisions/v2.1-human-review-activation"
DEFAULT_PUBLISH = ROOT / "evaluation/datasets/v2.1.jsonl"

ACTIVATION_VERSION = "v2.1.0"
# 固定常量而非运行时钟：确定性要求产物不含任何「跑一次变一次」的值
ACTIVATION_DATE = "2026-08-30"
OWNER_ADJUDICATION_DATE = "2026-08-29"
REVIEW_STATUS = "human_review_confirmed_agent_adjudicated"
REVIEWER = "zcode-agent-2026-08-29"
REVIEW_NOTES_APPENDIX = (
    f"{ACTIVATION_VERSION} activation（{ACTIVATION_DATE}）：owner "
    f"{OWNER_ADJUDICATION_DATE} 终审裁决链确认，HUMAN_REVIEWED overlay "
    "为最新权威真值层（reviewed_by 为授权代理复核标识，非真人逐条复核）")
GATE_VERDICT_OK = "ACTIVATED"
STATUS_HUMAN_REVIEWED = "HUMAN_REVIEWED"
EXPECTED_OVERLAY_VERSION = 1
EXPECTED_COUNTS = {"confirmed": 150, "reject": 0, "needs_followup": 0}
N_CASES = 150
TRUTH_FIELDS = ("should_refuse", "relevance_level",
                "acceptable_answer_points", "relevant_source_ids",
                "relevant_chunk_ids")
# owner 2026-08-27 final-rulings（batch2）涉及的 6 条 case：其旧裁决已被
# 2026-08-29 终审 supersession，激活门要求它们必须仍在 150 池内
FINAL_RULINGS_CASES = ("en-052", "mixed-022", "mixed-030", "mixed-033",
                       "multi-012", "zh-023")
# evaluation.schema.EvalCase 只接受 9 个核心字段；以下为 v2 草稿在其
# 之上扩展的字段（发布自检时投影去除，schema 本身一字不改）
SCHEMA_PROJECTION_DROP_TOP = ("note", "annotation", "relevance_level",
                              "is_refusal_turn", "relevant_chunk_ids",
                              "doc_target")


class ActivationError(RuntimeError):
    """任何门失败或非法状态：调用方保证零输出 fail-closed。"""


# ── 基础工具 ──────────────────────────────────────────────────────────

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _line(value: Any) -> str:
    """JSONL 行序列化：与 v2 草稿一致（ensure_ascii=False、默认分隔符、
    键序 = 构造序），保证顶层字段透传时字节结构不变。"""
    return json.dumps(value, ensure_ascii=False)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) \
        + "\n"


def _manifest_self_hash(body: dict) -> dict:
    """manifest 自哈希：排除 manifest_sha256 自身字段后复算回填。"""
    result = dict(body)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = hashlib.sha256(
        _dump(result).encode("utf-8")).hexdigest()
    return result


def _short(value: Any) -> str:
    """错误信息里的值截断展示（避免超长列表撑爆错误输出）。"""
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 120 else text[:117] + "..."


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _list_same_multiset(a: Any, b: Any) -> bool:
    """判断两个列表「内容相同、顺序不同」（用于门 3 的顺序差异归类）。"""
    if not (isinstance(a, list) and isinstance(b, list)):
        return False
    if len(a) != len(b):
        return False
    return (sorted(_canon(x) for x in a)
            == sorted(_canon(x) for x in b))


def _load_json(path: Path, errors: list[str], label: str) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label}: 无法读取或非法 JSON: {exc}")
        return None


def _load_jsonl(path: Path, errors: list[str], label: str) -> list[dict]:
    rows: list[dict] = []
    try:
        for n, ln in enumerate(path.open(encoding="utf-8"), 1):
            if not ln.strip():
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError as exc:
                errors.append(f"{label}: 第 {n} 行非法 JSON: {exc}")
    except OSError as exc:
        errors.append(f"{label}: 无法读取: {exc}")
    return rows


# ── 激活四门 ──────────────────────────────────────────────────────────

def run_checks(draft_path: Path, overlay_path: Path, ovm_path: Path,
               final_rulings_path: Path) -> dict[str, Any]:
    """依次执行门 1-4，收集全部错误（一次性报告，不 fail-fast）；
    返回 checks dict：errors 非空 = 不得激活。"""
    errors: list[str] = []
    checks: dict[str, Any] = {}

    # ── 门 1：overlay manifest 状态 / 计数 / SHA 链 ──
    m = _load_json(ovm_path, errors, "overlay manifest")
    overlay = _load_json(overlay_path, errors, "overlay")
    g1: dict[str, Any] = {"passed": False}
    if m is not None:
        g1["status"] = m.get("status")
        g1["decision_counts"] = m.get("decision_counts")
        if m.get("status") != STATUS_HUMAN_REVIEWED:
            errors.append(f"overlay manifest status 必须为 "
                          f"{STATUS_HUMAN_REVIEWED}，实际 {m.get('status')!r}")
        if m.get("overlay_version") != EXPECTED_OVERLAY_VERSION:
            errors.append(f"overlay manifest overlay_version 必须为 "
                          f"{EXPECTED_OVERLAY_VERSION}，实际 "
                          f"{m.get('overlay_version')!r}")
        if m.get("decision_counts") != EXPECTED_COUNTS:
            errors.append(f"overlay manifest decision_counts 必须恰为 "
                          f"{EXPECTED_COUNTS}（150/150 confirmed），实际 "
                          f"{_short(m.get('decision_counts'))}")
        g1["inputs_verified"] = []
        for key, info in m.get("inputs", {}).items():
            # original_pack_sha256 之类的链引用值没有对应文件，跳过
            if not isinstance(info, dict) or "path" not in info \
                    or "sha256" not in info:
                continue
            g1["inputs_verified"].append(key)
            p = Path(info["path"])
            if not p.exists():
                errors.append(f"ovm.inputs.{key}: 文件不存在: {p}")
            elif info["sha256"] != _sha256_file(p):
                errors.append(f"ovm.inputs.{key}: SHA-256 漂移（输入被改写）")
    if overlay is not None and m is not None:
        actual = _sha256_file(overlay_path)
        g1["overlay_sha256_recomputed"] = actual
        g1["overlay_sha256_recorded"] = m.get("overlay_sha256")
        if actual != m.get("overlay_sha256"):
            errors.append(f"overlay_sha256 漂移（overlay.json 与 manifest "
                          f"记录不一致）：recomputed={actual} "
                          f"recorded={m.get('overlay_sha256')}")
        cases = overlay.get("cases", [])
        g1["overlay_n_cases"] = len(cases)
        if overlay.get("status") != STATUS_HUMAN_REVIEWED:
            errors.append(f"overlay status 必须为 {STATUS_HUMAN_REVIEWED}，"
                          f"实际 {overlay.get('status')!r}")
        if len(cases) != m.get("n_cases") or len(cases) != N_CASES:
            errors.append(f"overlay cases 数量非法：len(cases)={len(cases)} "
                          f"manifest.n_cases={m.get('n_cases')} "
                          f"expected={N_CASES}")
    g1["passed"] = not errors
    checks["gate1_overlay_manifest"] = g1

    # ── 门 2：草稿 id 集合 == overlay case_id 集合 ──
    draft_rows = _load_jsonl(draft_path, errors, "v2 draft")
    g2: dict[str, Any] = {"passed": False}
    draft_ids: set[str] = set()
    if draft_rows:
        draft_ids = {r.get("id", "") for r in draft_rows}
        dups = sorted(i for i in draft_ids
                      if sum(1 for r in draft_rows if r.get("id") == i) > 1)
        if dups:
            errors.append(f"v2 draft 存在重复 case id: {dups}")
        g2["draft_count"] = len(draft_rows)
    if overlay is not None:
        cases = overlay.get("cases", [])
        overlay_ids = {c.get("case_id", "") for c in cases}
        cids = [c.get("case_id", "") for c in cases]
        if len(set(cids)) != len(cids):
            errors.append("overlay 存在重复 case_id")
        if cids != sorted(cids):
            errors.append("overlay cases 未按 case_id 排序")
        g2["overlay_count"] = len(cases)
    if draft_rows and overlay is not None:
        draft_only = sorted(draft_ids - overlay_ids)
        overlay_only = sorted(overlay_ids - draft_ids)
        g2["draft_only"] = draft_only
        g2["overlay_only"] = overlay_only
        if draft_only or overlay_only:
            errors.append(f"草稿池与 overlay case_id 集合不一致（双向差集"
                          f"非空）：draft_only={_short(draft_only)} "
                          f"overlay_only={_short(overlay_only)}")
    g2["passed"] = not errors
    checks["gate2_id_sets"] = g2

    # ── 门 3：逐 case 五真值字段一致（顺序敏感；仅顺序差异也停止）──
    g3: dict[str, Any] = {"passed": False, "cases_compared": 0,
                          "mismatches": [], "order_only": []}
    if draft_rows and overlay is not None:
        draft_by_id = {r.get("id", ""): r for r in draft_rows}
        for c in overlay.get("cases", []):
            cid = c.get("case_id", "")
            d = draft_by_id.get(cid)
            if d is None:
                continue  # 缺失 case 已由门 2 报告，不重复计数
            g3["cases_compared"] += 1
            for field in TRUTH_FIELDS:
                if d.get(field) == c.get(field):
                    continue
                detail = {"case_id": cid, "field": field,
                          "draft": _short(d.get(field)),
                          "overlay": _short(c.get(field))}
                if _list_same_multiset(d.get(field), c.get(field)):
                    # 「仅顺序差异」也是真值层不一致：如实记录并停止，
                    # 绝不静默重排后放行
                    g3["order_only"].append(detail)
                    errors.append(f"{cid}: 真值字段 {field} 草稿与 overlay "
                                  "仅顺序差异（内容相同、顺序不同；如实"
                                  "记录并停止，不允许静默重排）")
                else:
                    g3["mismatches"].append(detail)
                    errors.append(f"{cid}: 真值字段 {field} 草稿与 overlay "
                                  f"不一致（fail-closed）：draft="
                                  f"{detail['draft']} overlay="
                                  f"{detail['overlay']}")
    g3["passed"] = not errors
    checks["gate3_truth_fields"] = g3

    # ── 门 4：6 条 final-rulings case 必须全部在池内 ──
    fr_rows = _load_jsonl(final_rulings_path, errors, "final-rulings ledger")
    g4: dict[str, Any] = {"passed": False}
    fr_ids = {r.get("case_id", "") for r in fr_rows}
    g4["cases"] = sorted(fr_ids)
    missing_ledger = sorted(set(FINAL_RULINGS_CASES) - fr_ids)
    if missing_ledger:
        errors.append(f"final-rulings ledger 缺少预期 case: {missing_ledger}")
    if draft_rows:
        missing_pool = sorted(set(FINAL_RULINGS_CASES) - draft_ids)
        g4["missing_from_pool"] = missing_pool
        if missing_pool:
            errors.append(f"final-rulings case 不在草稿池内: {missing_pool}")
    g4["passed"] = not errors
    checks["gate4_final_rulings"] = g4

    checks["errors"] = sorted(set(errors))
    return checks


# ── 产物构建（纯函数：相同输入 → 相同输出字节）──────────────────────

def build_dataset_rows(draft_rows: list[dict]) -> list[dict]:
    """顶层字段一律透传（键序保持草稿原序）；唯一改动在 annotation 内
    三个审阅字段，如实记录终审状态与激活谱系。"""
    rows: list[dict] = []
    for src in draft_rows:
        row = dict(src)
        ann = dict(src.get("annotation", {}))
        old_notes = (ann.get("review_notes") or "").strip()
        ann["review_status"] = REVIEW_STATUS
        ann["reviewed_by"] = REVIEWER
        ann["review_notes"] = (old_notes + "；" if old_notes
                               else "") + REVIEW_NOTES_APPENDIX
        row["annotation"] = ann
        rows.append(row)
    return rows


def _dataset_text(rows: list[dict]) -> str:
    return "".join(_line(r) + "\n" for r in rows)


def _input_snapshot() -> dict[str, Any]:
    """五类冻结输入的 SHA 快照（激活谱系的锚点）。"""
    return {key: {"path": str(p), "sha256": _sha256_file(p)} for key, p in (
        ("draft", DRAFT_PATH),
        ("overlay", OVERLAY_PATH),
        ("overlay_manifest", OVERLAY_MANIFEST_PATH),
        ("rulings_ledger", RULINGS_LEDGER_PATH),
        ("final_rulings_batch2", FINAL_RULINGS_PATH),
    )}


def build_manifest(checks: dict, dataset_sha: str, report_sha: str,
                   published: dict[str, str] | None) -> dict:
    gates = {name: {**{k: v for k, v in checks[name].items()
                       if k != "passed"},
                    "passed": checks[name]["passed"]}
             for name in ("gate1_overlay_manifest", "gate2_id_sets",
                          "gate3_truth_fields", "gate4_final_rulings")}
    body: dict[str, Any] = {
        "task": "corpus-v2-v21-activate",
        "activation_version": ACTIVATION_VERSION,
        "activation_date": ACTIVATION_DATE,
        "gate_verdict": GATE_VERDICT_OK,
        "n_cases": N_CASES,
        "review_status": REVIEW_STATUS,
        "reviewer": REVIEWER,
        "owner_adjudication_date": OWNER_ADJUDICATION_DATE,
        "inputs": _input_snapshot(),
        "gates": gates,
        "declarations": {
            # overlay 是最新权威真值层：取代 v2.0.x 冻结候选与历史
            # rulings 中与之冲突的旧处置（supersession），历史账本不改写
            "overlay_is_latest_authoritative_truth_layer": True,
            "reviewer_is_authorized_agent_review_plus_owner_adjudication":
                True,
            "truth_fields_passthrough_unchanged": True,
            "frozen_assets_read_only": True,
            "no_llm_api_network_used": True,
            "no_randomness_no_runtime_timestamp": True,
            "double_build_byte_identical": True,
        },
        "products": {
            "v2.1-dataset.jsonl": {"sha256": dataset_sha},
            "activation-report.md": {"sha256": report_sha},
        },
    }
    if published is not None:
        body["products"]["published_v2.1.jsonl"] = published
    return _manifest_self_hash(body)


def _gate_row(name: str, g: dict) -> str:
    detail = {k: v for k, v in g.items() if k != "passed"}
    text = _canon(detail)
    if len(text) > 180:  # 表格内截断展示；完整详情见 manifest.json
        text = text[:177] + "…"
    return f"| {name} | {'PASS' if g['passed'] else 'FAIL'} | {text} |"


def build_report(checks: dict, projection_note: str | None) -> str:
    """激活报告（中文，确定性文本）：Phase A 四问、池构成、supersession
    链、deferred 现状、门结果表、schema 边界发现与确定性说明。"""
    g = {name: checks[name] for name in ("gate1_overlay_manifest",
                                         "gate2_id_sets",
                                         "gate3_truth_fields",
                                         "gate4_final_rulings")}
    ov_sha = g["gate1_overlay_manifest"].get("overlay_sha256_recomputed", "")
    lines = [
        "# v2.1 数据集激活报告（v2.1.0-human-review-activation）",
        "",
        "> 生成工具：`scripts/corpus_v2_v21_activate.py`（确定性产物："
        "无时间戳、无随机数、无网络/LLM 调用）",
        f"> 激活版本：**{ACTIVATION_VERSION}**；激活日期常量："
        f"{ACTIVATION_DATE}；owner 终审裁决日期：{OWNER_ADJUDICATION_DATE}",
        f"> gate_verdict：**{GATE_VERDICT_OK}**（四门全过，fail-closed）",
        "",
        "## 一、结论",
        "",
        f"v2 人工终审 overlay（`human-reviewed-truth-overlay.json`，"
        f"SHA-256 `{ov_sha}`）作为**最新权威真值层**启用，生成 "
        f"v2.1 正式数据集（{N_CASES} case）。数据集顶层真值字段自草稿"
        f"原样透传（不重排、不重算），唯一改动是 `annotation` 内三个"
        f"审阅字段：`review_status` = `{REVIEW_STATUS}`（诚实取值："
        "终审 confirmed 由授权代理复核 + owner 仲裁达成，非真人逐条"
        f"复核）、`reviewed_by` = `{REVIEWER}`、`review_notes` 追加 "
        f"owner 裁决日期（{OWNER_ADJUDICATION_DATE}）与激活版本号"
        f"（{ACTIVATION_VERSION}）。",
        "",
        "## 二、Phase A 谱系侦察四问",
        "",
        "### A1 草稿 150 行 vs v2.0.11 冻结候选 136 行的构成差异",
        "",
        "- 草稿 150 行 = case-freeze（corpus_version v2.0.0，"
        "2026-08-05 密封，`split/case-freeze.json`）`partition=new` "
        "的 150 case 全集；**legacy_dev 110 行不在草稿池中**"
        "（partition=legacy_dev 与草稿 id 零交集，属另一批遗留分区，"
        "由 `evaluation/split_seal.py` 在密封时划分）。",
        "- v2.0.11 冻结候选 136 行全部在草稿池内（v211 ⊂ draft，"
        "反向差集为空）。草稿多出的 14 行是 v2.0.x 治理链在冻结候选层"
        "**分批退休**的 case，退休轨迹（依据各修订目录 manifest 的 "
        "counts.retired 与 draft-before/after 逐版比对）：",
        "  - v2.0.5 退休 zh-033 → 149；v2.0.6 退休 zh-032 → 148；",
        "  - v2.0.8 退休 en-044 / en-050 / mixed-026 / zh-042 / zh-045 "
        "→ 143；v2.0.9 退休 mixed-027 / multi-030~034 → 137；"
        "v2.0.10 退休 multi-019 → 136。",
        "- 这 14 行自草稿创建（annotation_version=v2.0.0、"
        "created_at=2026-08-05、annotated_by=zcode-draft）起就在草稿池："
        "v2.0.x 链只在冻结候选层退休它们，草稿层从未删除。",
        "- 2026-08-29 人工终审对草稿 150 行全集执行（commit f28cce5），"
        "overlay 覆盖全部 150 case → 被退休的 14 行经终审 confirmed，"
        "按 **supersession** 取代旧退休状态。",
        "- 草稿与 v2.0.11 交集 136 行存在 31 处真值字段差异：全部源于 "
        "owner 2026-08-29 仲裁的 8 条证据优先修复（en-044 / en-048 / "
        "en-052 / mixed-022 / zh-057 / noanswer-039 / noanswer-040 / "
        "noanswer-050）落草稿（f28cce5）；overlay 与修复后的草稿一致。",
        "- 依据 manifest/ledger：v2.0.5/6/8/9/10 各修订目录 manifest、"
        "v2.0.11 evaluation-freeze（含 18 条 deferred-owner-decisions）、"
        "commit f28cce5、overlay manifest inputs SHA 链。",
        "",
        "### A2 batch1 里 18 条 deferred-owner-decisions 的现状",
        "",
        "- v2.0.11-freeze 阶段（`evaluation-freeze/"
        "deferred-owner-decisions.jsonl`，owner_decision=deferred）",
        "  的 18 条 case 已被**完整消解**，无遗留：",
        "  1. 全部 18 条进入 batch1 rulings ledger（"
        "`v2.1-owner-rulings-batch1/rulings-ledger.jsonl`）：15 条 "
        "maintained_reject_archived + 3 条 restored_pending_verification"
        "（mixed-022 / multi-012 / zh-023）；",
        "  2. batch2 终裁（final-rulings-batch2）：mixed-022 → "
        "retired_ambiguous_phrasing；multi-012 / zh-023 → "
        "verified_active；",
        "  3. 2026-08-29 人工终审：18 条全部在 overlay 150 池内且 "
        "confirmed——旧处置（含 15 条 maintained_reject_archived 的"
        "「维持退休」）被终审真值取代（supersession），历史 ledger "
        "保持原样未改写。",
        "",
        "### A3 草稿 id 集合与 rulings 分类账的交集",
        "",
        "- rulings ledger 共 22 条 case（15 maintained + 4 "
        "contract_blind_review_authorized + 3 restored），"
        "**全部在草稿 150 行池内**（ledger − draft = 空集）。",
        f"- 6 条 final-rulings case（{', '.join(FINAL_RULINGS_CASES)}）"
        f"**全部在池内**（本工具门 4 固化该约束）。",
        "",
        "### A4 草稿与 overlay 逐 case 真值一致性预检",
        "",
        f"- 预检与正式门 3 双重确认：150 case × 5 真值字段"
        f"（{', '.join(TRUTH_FIELDS)}）草稿顶层值 == overlay 值，"
        "零不一致、零顺序差异——无系统性错位。",
        "",
        "## 三、池构成",
        "",
        "| 构成 | 数量 | 说明 |",
        "|---|---|---|",
        "| 草稿池（= overlay 池 = v2.1 数据集） | 150 | case-freeze "
        "partition=new 全集 |",
        "| ├ 与 v2.0.11 冻结候选交集 | 136 | 修订链持续维护的候选 |",
        "| └ v2.0.x 链外行（曾在候选层退休） | 14 | 2026-08-29 终审 "
        "confirmed，supersession 取代旧退休 |",
        "| legacy_dev 分区 | 110 | 不在草稿池；与激活无关 |",
        "| rulings ledger 涉及 case | 22 | 全在池内 |",
        "",
        "## 四、supersession 逐 case 记录（6 条 final-rulings case）",
        "",
        "历史 ledger 永不改写；下表仅记录「旧裁决 → 新证据链 → 新状态」"
        "的取代链。",
        "",
        "| case | batch1（2026-08-27） | batch2 终裁（2026-08-27） | "
        "2026-08-29 新证据链 | v2.1 终态 |",
        "|---|---|---|---|---|",
        "| zh-023 | restored_pending_verification | verified_active"
        "（机械包含证据 + 新鲜密封盲审两线一致） | 修复后草稿 → 终审 "
        "confirmed（f28cce5 转移）→ overlay | confirmed |",
        "| multi-012 | restored_pending_verification | verified_active"
        "（同上两线一致） | 同上 | confirmed |",
        "| mixed-022 | restored_pending_verification | "
        "retired_ambiguous_phrasing（命题双读歧义退休） | owner 批示"
        "「同意 reject（草稿错误成立）」→ 答案点改写「条目为中英混合："
        "英文定义 + 中文正文解释」→ round-2 修复复核 confirmed "
        "（notes 留档） | confirmed（取代 retired） |",
        "| en-052 | contract_blind_review_authorized | "
        "retired_persistent_contract_error（契约盲审三次独立复现） | "
        "owner 批示 → 问题改「各自保证什么」+ Rust 答案点=内存安全保证"
        " + 证据 chunk_37→chunk_53+43 → round-2 修复复核 confirmed | "
        "confirmed（取代 retired） |",
        "| mixed-030 | contract_blind_review_authorized | "
        "retired_persistent_contract_error | 无专项仲裁修复；由 owner "
        "授权的人工终审对修复后草稿 150 行全集直接 confirmed "
        "（round-1，142 confirmed 之内）→ overlay | confirmed"
        "（取代 retired） |",
        "| mixed-033 | contract_blind_review_authorized | "
        "retired_persistent_contract_error | 同 mixed-030（round-1 "
        "confirmed）→ overlay | confirmed（取代 retired） |",
        "",
        "> 诚实说明：mixed-030 / mixed-033 的旧 retired 裁决由 2026-08-29"
        " 授权代理终审的 150/150 confirmed overlay 整体取代，未单独走"
        " owner 仲裁修复；若 owner 要求补强，可在 v2.1.x 治理轮对这两条"
        "追加专项裁决（历史账本依旧不改写）。",
        "",
        "## 五、激活门结果",
        "",
        "| 门 | 结果 | 详情 |",
        "|---|---|---|",
        _gate_row("1 overlay manifest 状态/计数/SHA 链（含 inputs 全量复算）",
                  g["gate1_overlay_manifest"]),
        _gate_row("2 草稿 id 集合 == overlay case_id 集合（双向差集空）",
                  g["gate2_id_sets"]),
        _gate_row("3 逐 case 五真值字段一致（顺序敏感）",
                  g["gate3_truth_fields"]),
        _gate_row("4 6 条 final-rulings case 在池内",
                  g["gate4_final_rulings"]),
        "",
        "## 六、产物",
        "",
        "| 产物 | 说明 |",
        "|---|---|",
        "| `v2.1-dataset.jsonl` | 150 行，草稿 schema，顶层透传 + "
        "annotation 终审状态 |",
        "| `manifest.json` | 输入 SHA 快照、声明、四门结果、自哈希 |",
        "| `evaluation/datasets/v2.1.jsonl` | 发布副本（与数据集逐字节"
        "一致） |",
        "",
        "## 七、evaluation/schema.py 兼容性边界发现（schema 未改动）",
        "",
        "- `evaluation.schema.EvalCase` 为「annotators write, runners "
        "read」的静态契约，仅接受 9 个核心字段；v2 草稿扩展的顶层字段 "
        "`note / annotation / relevance_level / is_refusal_turn / "
        "relevant_chunk_ids / doc_target` 以及 "
        "`relevant_chunks[].chunk_id` 会导致 `from_dict` 的 "
        "`cls(**d)` 抛 TypeError。",
        "- 发布自检采用**投影验证**：去除上述 6 个顶层扩展字段与 "
        "chunk 内 `chunk_id` 后 `load_dataset` 加载 150 条、"
        "`validate_dataset` 零警告；真值字段（should_refuse / "
        "relevant_chunks / acceptable_answer_points 等）均在契约内。",
        "- v2.1 数据集以草稿 schema（超集）为准发布；schema.py 一字"
        "未改，消费方需要时可自行投影。",
        "",
        "## 八、确定性",
        "",
        "- 产物不含时间戳与随机源；激活日期、裁决日期均为常量。",
        "- run 内置**双构建字节断言**：构建链执行两次，任一字节差异即"
        " fail-closed 零输出。",
        "- 验收时另做外部文件级双跑比对（连跑两次脚本，产物 SHA 一致），"
        "见验收记录。",
        "",
        "## 九、身份与授权声明",
        "",
        f"- 终审 confirmed 由 AI 代理（{REVIEWER}）在 owner 明确授权下"
        f"执行；owner 于 {OWNER_ADJUDICATION_DATE} 对 8 条阻断 case 作出"
        "真人仲裁批示（6 条 reject 草稿错误成立 + noanswer-039/040 "
        "翻可答）。",
        f"- review_status = `{REVIEW_STATUS}` 如实标识「代理复核 + owner "
        "仲裁」，绝不伪称真人逐条复核。",
        "- 冻结资产只读：v2.0.x 修订树、v2.0.11 冻结候选、v1 数据集、"
        "rulings ledger 未被写改；本工具无任何 git 操作。",
        "",
    ]
    if projection_note:
        lines += ["## 十、发布自检", "",
                  f"- `{projection_note}`", ""]
    return "\n".join(lines) + "\n"


# ── 发布自检（schema 投影）───────────────────────────────────────────

def _schema_projection_check(rows: list[dict]) -> str:
    """发布前把 v2 草稿超集行投影为 EvalCase 契约子集，用 load_dataset
    + validate_dataset 机械验证（只在内存/临时文件进行，不改 schema）。"""
    from evaluation.schema import load_dataset, validate_dataset
    projected = []
    for r in rows:
        d = {k: v for k, v in r.items()
             if k not in SCHEMA_PROJECTION_DROP_TOP}
        d["relevant_chunks"] = [
            {k: v for k, v in c.items() if k != "chunk_id"}
            for c in d.get("relevant_chunks", [])]
        projected.append(d)
    fd, tmp_name = tempfile.mkstemp(suffix=".jsonl")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for d in projected:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        cases = load_dataset(tmp)
        warnings = validate_dataset(cases)
    finally:
        tmp.unlink(missing_ok=True)
    if len(cases) != N_CASES:
        raise ActivationError(f"schema 投影自检失败：load_dataset "
                              f"{len(cases)} != {N_CASES}")
    if warnings:
        raise ActivationError(f"schema 投影自检发现警告: {warnings[:5]}")
    return (f"ok: {len(cases)} cases loaded via "
            "evaluation.schema.load_dataset, validate_dataset 0 warnings"
            f"（投影去除 {len(SCHEMA_PROJECTION_DROP_TOP)} 个顶层扩展字段"
            "与 relevant_chunks[].chunk_id；schema 本身未改动）")


# ── 主流程（fail-closed：任何门失败 → 零输出）────────────────────────

def run(out_dir: Path = OUT_DIR, *,
        draft_path: Path = DRAFT_PATH,
        overlay_path: Path = OVERLAY_PATH,
        ovm_path: Path = OVERLAY_MANIFEST_PATH,
        rulings_ledger_path: Path = RULINGS_LEDGER_PATH,
        final_rulings_path: Path = FINAL_RULINGS_PATH,
        publish_path: Path | None = DEFAULT_PUBLISH) -> dict:
    """执行激活：四门 → schema 投影自检 → 双构建断言 → 落盘。
    任一步失败抛 ActivationError，保证零输出。"""
    checks = run_checks(draft_path, overlay_path, ovm_path,
                        final_rulings_path)
    if checks["errors"]:
        raise ActivationError("激活门失败（fail-closed，零输出）：\n  - "
                              + "\n  - ".join(checks["errors"]))
    draft_rows = _load_jsonl(draft_path, [], "v2 draft")

    # schema 投影自检放在落盘之前：失败 = 零输出（不动 schema 本身）
    projection_note: str | None = None
    if publish_path is not None:
        projection_note = _schema_projection_check(draft_rows)

    def _build() -> dict[str, str]:
        # 构建链为纯函数：相同输入 → 相同输出字节（确定性自证的基础）
        dataset_text = _dataset_text(build_dataset_rows(draft_rows))
        dataset_sha = hashlib.sha256(
            dataset_text.encode("utf-8")).hexdigest()
        report_text = build_report(checks, projection_note)
        report_sha = hashlib.sha256(
            report_text.encode("utf-8")).hexdigest()
        published: dict[str, str] | None = None
        if publish_path is not None:
            published = {"path": str(publish_path),
                         "sha256": dataset_sha,
                         "schema_projection_check": projection_note or ""}
        manifest = build_manifest(checks, dataset_sha, report_sha,
                                  published)
        return {"dataset": dataset_text, "report": report_text,
                "manifest": _dump(manifest)}

    # 双构建断言：相同输入必须逐字节一致，否则视为含非确定性来源
    first = _build()
    if first != _build():
        raise ActivationError("双构建字节不一致：产物构建含非确定性来源")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "v2.1-dataset.jsonl").write_text(
        first["dataset"], encoding="utf-8", newline="\n")
    (out_dir / "activation-report.md").write_text(
        first["report"], encoding="utf-8", newline="\n")
    (out_dir / "manifest.json").write_text(
        first["manifest"], encoding="utf-8", newline="\n")
    if publish_path is not None:
        publish_path.write_text(first["dataset"], encoding="utf-8",
                                newline="\n")
    return json.loads(first["manifest"])


# ── CLI ───────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args.pop(0) if args else ""
    if cmd != "activate":
        print("usage: corpus_v2_v21_activate.py activate "
              "[--out DIR] [--publish PATH | --no-publish]")
        return 2
    out_dir = OUT_DIR
    publish_path: Path | None = DEFAULT_PUBLISH
    i = 0
    while i < len(args):
        if args[i] == "--out" and i + 1 < len(args):
            out_dir = Path(args[i + 1])
            i += 2
        elif args[i] == "--publish" and i + 1 < len(args):
            publish_path = Path(args[i + 1])
            i += 2
        elif args[i] == "--no-publish":
            publish_path = None
            i += 1
        else:
            print(f"unknown argument: {args[i]}")
            return 2
    try:
        manifest = run(out_dir=out_dir, publish_path=publish_path)
    except ActivationError as exc:
        print(f"FAIL-CLOSED: {exc}", file=sys.stderr)
        return 1
    print(_dump({
        "gate_verdict": manifest["gate_verdict"],
        "activation_version": manifest["activation_version"],
        "n_cases": manifest["n_cases"],
        "out_dir": str(out_dir),
        "products": manifest["products"],
    }), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
