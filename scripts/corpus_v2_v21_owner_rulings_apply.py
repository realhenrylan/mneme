"""v2.1 owner rulings apply — 将 owner 对 22 条搁置项的批次裁决落为 v2.1 账本。

背景：v2.0.11 冻结包（`evaluation-freeze`）把 18 条 targeted-review reject
与 4 条 persistent contract error 搁置为「未来仅可进入 v2.1 治理流程」。
owner 已于 2026-08-27 对全部 22 条作出批次裁决：

- `restored_pending_verification` ×3（zh-023 / multi-012 / mixed-022）：
  targeted review 的模型驳回与机械证据矛盾（自认证据包含原句仍驳回、
  以"缩写省略限定"苛责正确答案点、因条目双语并存而过度驳回），owner 批示
  推翻该轮驳回——表达为模板词表中的 `owner_decision="reject"`（对 review
  结论 reject，而非对 case 本身）；
- `maintained_reject_archived` ×15：4 条 exact 但构造错位（答案点虽逐字
  在场但与查询意图不匹配——恢复反而污染评测集）、7 条 partial、
  4 条 translation，全部维持原审驳回并归档退休；
- `contract_blind_review_authorized` ×4（en-052 / mixed-030 / mixed-033 /
  zh-040）：授权后续契约聚焦密封盲审（独立脚本执行，本工具仅落账授权）。

安全性质：
- 输入 = 冻结决策包三件套 + freeze-summary；SHA 与本文 EXPECTED_INPUT_SHAS
  （构建时点快照）逐一比对，任一漂移 fail-closed 零输出；
- 输出目录必须是全新目录（拒绝已存在路径），只写两个新文件；
- 处置↔kind↔owner_decision 三者交叉校验，任何错位零输出；
- 双构建字节一致；冻结资产 byte-untouched 由测试看守。
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

FROZEN = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.0.11-owner-authorized-en048-same-source-repair"
PACK_DIR = FROZEN / "targeted-re-review" / "owner-decision-pack"
FREEZE_SUMMARY = FROZEN / "evaluation-freeze" / "freeze-summary.json"
DEFAULT_OUT = ROOT / "evaluation/datasets/v2/revisions" / \
    "v2.1-owner-rulings-batch1"

TIMESTAMP = "2026-08-27T00:00:00+00:00"
RULE_VERSION = "v2.1-owner-rulings-apply-1"
ACTOR = "OWNER_AUTHORIZED_V21_RULINGS_APPLY"
GATE_OK = "V21_OWNER_RULINGS_APPLY_OK"

# 构建时点输入快照 SHA256 —— fail-closed 基准；上游字节一变即拒产。
# 键 = owner-decision-pack/ 下实体文件名（无 pack- 前缀；freeze manifest
# 里的 pack-* 为早期打包逻辑名，SHA 已验证与实体逐一 MATCH）。
EXPECTED_INPUT_SHAS: dict[str, str] = {
    "owner-decision-template.jsonl":
        "bf056ab25e58399635016ba21002c1222eb31f43811ec8079ae63b35c4001044",
    "stable-reject-root-cause-triage.jsonl":
        "6f0873b47d3414bec5c1f2a303b824c521493ec662ff9730692850a43ccbf240",
    "persistent-contract-errors.jsonl":
        "4b69d2533af56ea78a7fd66c0c30786292aa481de6f3f8bf0a3776f376728cc0",
    "freeze-summary.json": "17c8ba4f2c5d18a3ff9aa0ca0a6a7a53f32229ffcb5992852aaa4844c627dade",
}

# owner 批示（2026-08-27 AskUserQuestion 四项批示的机械展开）：
# case_id -> (owner_decision[模板词表], disposition)
RULINGS: dict[str, tuple[str, str]] = {}
for _cid in ("zh-023", "multi-012", "mixed-022"):
    RULINGS[_cid] = ("reject", "restored_pending_verification")
for _cid in ("mixed-028", "mixed-029", "zh-036", "zh-054",
             "en-041", "en-045", "en-051", "mixed-034", "multi-027",
             "zh-050", "zh-058", "en-040", "en-047", "zh-046", "zh-052"):
    RULINGS[_cid] = ("confirm", "maintained_reject_archived")
for _cid in ("en-052", "mixed-030", "mixed-033", "zh-040"):
    RULINGS[_cid] = ("authorize_new_contract_focused_blind_review",
                     "contract_blind_review_authorized")

_KIND_FOR_DISPOSITION = {
    "restored_pending_verification": {"kind": "reject", "classification_any": True},
    "maintained_reject_archived": {"kind": "reject", "classification_any": True},
    "contract_blind_review_authorized": {
        "kind": "persistent_model_output_contract_inconsistency",
        "classification_any": False,
        "classification": "contract_error"},
}

RESTORED_NOTE = (
    "owner 推翻 targeted-review 驳回：模型驳回与机械证据矛盾"
    "（exact 包含关系成立）；恢复进入 v2.1 待验证集。")
ARCHIVED_NOTE_MAP = {
    "exact": "答案点逐字在场但与查询意图错位（语料构造缺陷），维持驳回归档。",
    "partial": "部分/改写级支撑不足全点直接支撑标准，维持驳回归档。",
    "translation": "仅跨语言关联（共享 token），不可证直接支撑，维持驳回归档。",
}
BLIND_NOTE = ("owner 授权契约聚焦密封盲审（独立 sealed 流程执行）；"
              "expected_decision_from_local_contract=confirmed 为引擎契约"
              "推断，盲审结果为准。")


class RulingsError(RuntimeError):
    """任何非法状态：调用方应保证零输出 fail-closed。"""


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


def _preflight() -> dict[str, dict]:
    """读取并校验四件冻结输入；返回按 case_id 索引的包行。

    任一 SHA 漂移 / 行数异常 / case 集不合即抛 RulingsError。
    """
    for name, expected in EXPECTED_INPUT_SHAS.items():
        path = FREEZE_SUMMARY if name == "freeze-summary.json" \
            else PACK_DIR / name
        actual = _sha256_file(path)
        if actual != expected:
            raise RulingsError(
                f"frozen input drift: {name} sha {actual} != {expected}")

    template = _jsonl(PACK_DIR / "owner-decision-template.jsonl")
    triage = {r["case_id"]: r for r in
              _jsonl(PACK_DIR / "stable-reject-root-cause-triage.jsonl")}
    errors = {r["case_id"]: r for r in
              _jsonl(PACK_DIR / "persistent-contract-errors.jsonl")}
    freeze = json.loads(FREEZE_SUMMARY.read_text(encoding="utf-8"))

    if len(template) != 22 or len(set(r["case_id"] for r in template)) != 22:
        raise RulingsError(f"template rows != 22 unique: {len(template)}")
    if freeze.get("deferred_count") != 18 or \
            freeze.get("diagnostic_case_count") != 4 or \
            not freeze.get("activation_blocked"):
        raise RulingsError("freeze summary counters drifted from v2.0.11 seal")

    pack_by_id = {r["case_id"]: r for r in template}
    if set(pack_by_id) != set(RULINGS):
        raise RulingsError(
            f"ruling/template case-set mismatch: "
            f"{set(pack_by_id) ^ set(RULINGS)}")
    for cid, row in pack_by_id.items():
        kind = row.get("kind")
        classification = row.get("classification")
        decision, disposition = RULINGS[cid]
        spec = _KIND_FOR_DISPOSITION[disposition]
        if kind != spec["kind"]:
            raise RulingsError(f"kind mismatch for {cid}: {kind}")
        if not spec["classification_any"] and classification != spec["classification"]:
            raise RulingsError(
                f"classification mismatch for {cid}: {classification}")
        # 交叉完整性：reject 行必须能在 triage 或 errors 中找到出处
        if kind == "reject" and cid not in triage:
            raise RulingsError(f"reject row without triage lineage: {cid}")
        if kind != "reject" and cid not in errors:
            raise RulingsError(f"contract row without error ledger: {cid}")
    return {"template": pack_by_id, "triage": triage, "errors": errors,
            "freeze": freeze}


def build_outputs(pack: dict[str, dict]) -> tuple[str, str]:
    """由裁决表机械展开账本与 manifest（纯函数，供双构建一致性检验）。"""
    ledger_lines = []
    counts = {"restored": 0, "maintained_reject_archived": 0,
              "contract_blind_review_authorized": 0}
    template: dict = pack["template"]
    triage: dict = pack["triage"]
    errors: dict = pack["errors"]

    tpl_sha = EXPECTED_INPUT_SHAS["owner-decision-template.jsonl"]

    for cid in sorted(RULINGS):
        decision, disposition = RULINGS[cid]
        trow = template[cid]
        relations = triage.get(cid, {}).get("answer_point_relations") or []
        classes = "/".join(a["classification"] for a in relations) or \
            trow.get("classification", "")
        if disposition == "restored_pending_verification":
            note = RESTORED_NOTE
        elif disposition == "maintained_reject_archived":
            note = ARCHIVED_NOTE_MAP.get(classes.split("/")[0],
                                         ARCHIVED_NOTE_MAP["partial"])
        else:
            note = BLIND_NOTE
        record = {
            "case_id": cid,
            "disposition": disposition,
            "owner_decision": decision,
            "classification": trow.get("classification"),
            "answer_point_classifications": [
                a["classification"] for a in relations] or None,
            "decision_note": note,
            "v210_lineage_only": triage.get(cid, {}).get(
                "v210_triage_lineage", {}).get("lineage_only"),
            "targeted_review_decision": trow.get(
                "targeted_review_decision") if not relations else
                triage[cid].get("targeted_review_decision"),
            "lineage": {
                "frozen_revision":
                    "v2.0.11-owner-authorized-en048-same-source-repair",
                "owner_decision_pack": "targeted-re-review/owner-decision-pack",
                "template_sha256": tpl_sha,
                "rule_version": RULE_VERSION,
                "actor": ACTOR,
                "timestamp": TIMESTAMP,
            },
        }
        ledger_lines.append(_line(record))
        key = {"restored_pending_verification": "restored",
               "maintained_reject_archived": "maintained_reject_archived",
               "contract_blind_review_authorized":
                   "contract_blind_review_authorized"}[disposition]
        counts[key] += 1

    body = {
        "actor": ACTOR,
        "counts": counts,
        "declarations": {
            "candidate_bytes_unchanged": True,
            "frozen_inputs_read_only": True,
            "human_approved_by_owner_batch_ruling": True,
            "llm_called": False,
            "network_used": False,
            "overlay_generated": False,
            "restored_cases_enter_verification_pool": counts["restored"],
            "rulings_only_no_data_rewrite": True,
            "v20_frozen_revision_touched": False,
        },
        "frozen_revision": "v2.0.11-owner-authorized-en048-same-source-repair",
        "gate_verdict": GATE_OK,
        "input_shas": dict(EXPECTED_INPUT_SHAS),
        "rule_version": RULE_VERSION,
        "run_at": TIMESTAMP,
        "skill_note": (
            "data-analytics:analyze-data-quality skill 在本环境中不可用；"
            "已实施等价确定性检查（SHA 校验/集合一致/kind 交叉校验/双构建"
            "字节一致），全部为机械复算，无额外 LLM 参与。"),
        "task": "v2.1-owner-rulings-apply",
    }
    manifest = _manifest(body)
    return "\n".join(ledger_lines) + "\n", _dump(manifest)


def run(*, out_dir: Path = DEFAULT_OUT) -> dict:
    if out_dir.exists():
        raise RulingsError(f"output directory already exists: {out_dir}")
    try:
        pack = _preflight()
        ledger_text, manifest_text = build_outputs(pack)
    except RulingsError:
        raise
    out_dir.mkdir(parents=True)  # preflight 全过后才建目录：异常时零输出
    (out_dir / "rulings-ledger.jsonl").write_text(ledger_text,
                                                  encoding="utf-8",
                                                  newline="\n")
    (out_dir / "manifest.json").write_text(manifest_text, encoding="utf-8",
                                           newline="\n")
    return json.loads(manifest_text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    try:
        manifest = run(out_dir=args.out_dir)
    except RulingsError as exc:
        print(f"FAIL-CLOSED: {exc}", file=sys.stderr)
        return 1
    print(_dump({"gate_verdict": manifest["gate_verdict"],
                 "counts": manifest["counts"],
                 "out_dir": str(args.out_dir)}), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
