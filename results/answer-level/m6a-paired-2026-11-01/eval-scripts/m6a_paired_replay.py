"""M6a 配对重放（0 LLM 调用，2026-11-01 已签 addendum 第五节）。

对基线（m6a-paired-base-2026-11-01，capture on）逐例离线重放冻结实现
``retarget_citations``（git show 614e260:src/citation_selection.py，SHA 校验
后经 importlib 加载，不复制进 src/），再用 evaluation/citation_metrics.py
计算 paired citation_metrics。

真值（acceptable_answer_points / should_refuse / relevant）只在本离线
脚本读取；retarget_citations 只接收 answer/citation_ids/chunk_texts。

断言（任一失败 → consistency.json 记 INVALID，退出码 2，不跑 judge/al3）：
  1. stats.slots_before == stats.slots_after
  2. add == 0 且 delete == 0（按位比较原始/新 [S#] 序列）
  3. 剥离 [S#] 令牌后 new_answer == baseline answer（逐字节）

输出（results/answer-level/m6a-paired-2026-11-01/）：
  outcomes-paired.jsonl / consistency.json / replay-stats.json
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

BASELINE_DIR = ROOT / "results" / "answer-level" / "m6a-paired-base-2026-11-01"
OUT_DIR = ROOT / "results" / "answer-level" / "m6a-paired-2026-11-01"
CHUNKS_PATH = ROOT / "data" / "v2-corpus" / "chunks" / "chunks.jsonl"
DATASET_PATH = ROOT / "evaluation" / "datasets" / "v2.1.jsonl"

M6A_MODULE_COMMIT = "614e260"
M6A_MODULE_SHA256 = (
    "ee9963c76cbf580238b5914a3b1a34d6265bdd66a5bdbfeb3523a457bccc1613")

_TOKEN_RE = re.compile(r"\[S[0-9]+\]")
_STRIP_RE = re.compile(r"\[S[0-9]+\]")

sys.path.insert(0, str(ROOT))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def dump_line(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def load_frozen_module():
    """git show 614e260 → SHA 校验 → 临时文件 → importlib 加载（禁入 src/）。"""
    blob = subprocess.run(
        ["git", "show", f"{M6A_MODULE_COMMIT}:src/citation_selection.py"],
        cwd=str(ROOT), capture_output=True, timeout=120,
    )
    if blob.returncode != 0:
        raise RuntimeError(f"git show {M6A_MODULE_COMMIT} 失败: {blob.stderr!r}")
    actual = sha256_bytes(blob.stdout)
    if actual != M6A_MODULE_SHA256:
        raise RuntimeError(
            f"M6a 模块 SHA 不符：expected {M6A_MODULE_SHA256}, got {actual}")
    tmp_dir = Path(tempfile.mkdtemp(prefix="m6a_paired_replay_"))
    module_path = tmp_dir / "citation_selection.py"
    module_path.write_bytes(blob.stdout)
    spec = importlib.util.spec_from_file_location(
        "_m6a_citation_selection_frozen", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclass 解析需要 sys.modules 注册（_is_type 查 cls.__module__）
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, actual


def token_slots(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def main() -> int:
    # 输出目录 fail-closed（preflight 已确认不存在）
    OUT_DIR.mkdir(parents=True, exist_ok=False)

    # 1) chunk store：chunk_id -> text / source（12-hex 域）
    chunk_text: dict[str, str] = {}
    chunk_source: dict[str, str] = {}
    for row in load_jsonl(CHUNKS_PATH):
        cid = str(row["chunk_id"])
        chunk_text[cid] = str(row["text"])
        chunk_source[cid] = str(row.get("source") or "")
    print(f"[chunks] {len(chunk_text)} chunks loaded")

    # 2) 冻结模块（SHA 校验 + importlib）
    module, module_sha = load_frozen_module()
    retarget_citations = module.retarget_citations
    print(f"[module] frozen citation_selection loaded (sha {module_sha[:16]}…)")

    # 3) 基线 outcomes（capture on）+ 数据集真值（离线读）
    base_rows = load_jsonl(BASELINE_DIR / "outcomes.jsonl")
    if len(base_rows) != 150:
        raise RuntimeError(f"基线应为 150 行，实际 {len(base_rows)}")
    from evaluation.schema import load_dataset
    cases = {c.id: c for c in load_dataset(DATASET_PATH)}

    from evaluation.citation_metrics import evaluate_citations_context_aware

    paired_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    total_add = total_retarget = total_delete = 0
    stats_sums = {
        "examined": 0, "retargeted": 0, "unchanged": 0, "invalid": 0,
        "groups": 0,
    }
    fail_closed_cases = 0
    per_case_slots: list[dict[str, Any]] = []

    for row in base_rows:
        case_id = row["case_id"]
        answer = row["answer"]
        full_sources = row.get("full_sources") or ""
        ordered = list(row.get("context_chunk_ids_ordered") or [])

        case_failures: list[str] = []
        if not full_sources:
            case_failures.append("full_sources 为空")
        if not ordered:
            case_failures.append("context_chunk_ids_ordered 为空")
        missing = [c for c in ordered if c not in chunk_text]
        if missing:
            case_failures.append(f"chunk store 缺失: {missing[:5]}")

        if case_failures:
            failures.append({"case_id": case_id, "reasons": case_failures})
            continue

        citation_ids = [f"S{i}" for i in range(1, len(ordered) + 1)]
        chunk_texts = [chunk_text[c] for c in ordered]

        # 重放：retarget 只看 answer/citation_ids/chunk_texts（无真值）
        new_answer, stats = retarget_citations(answer, citation_ids, chunk_texts)

        # add/retarget/delete：按位比较原始/新 [S#] 序列
        orig_slots = token_slots(answer)
        new_slots = token_slots(new_answer)
        add = max(0, len(new_slots) - len(orig_slots))
        delete = max(0, len(orig_slots) - len(new_slots))
        retarget_changes = sum(
            1 for a, b in zip(orig_slots, new_slots) if a != b)
        total_add += add
        total_retarget += retarget_changes
        total_delete += delete
        for k in stats_sums:
            stats_sums[k] += int(getattr(stats, k))
        if stats.fail_closed:
            fail_closed_cases += 1

        # 断言 1/2/3
        if stats.slots_before != stats.slots_after:
            case_failures.append(
                f"slots_before {stats.slots_before} != slots_after "
                f"{stats.slots_after}")
        if add != 0 or delete != 0:
            case_failures.append(f"add={add} delete={delete}（应全 0）")
        stripped_new = _STRIP_RE.sub("", new_answer).encode("utf-8")
        stripped_old = _STRIP_RE.sub("", answer).encode("utf-8")
        if stripped_new != stripped_old:
            case_failures.append("剥离 [S#] 后答案非逐字节相同")

        # paired citation_metrics（离线读真值：answer_points/should_refuse/
        # relevant 来自基线 outcome 记录与数据集）
        case = cases[case_id]
        chunk_to_source = dict(chunk_source)
        context_source_ids = sorted({chunk_source[c] for c in ordered})
        paired_metrics = evaluate_citations_context_aware(
            new_answer,
            sources=full_sources,
            context_chunk_ids=ordered,
            context_source_ids=context_source_ids,
            candidate_chunk_ids=ordered,
            chunk_to_source=chunk_to_source,
            relevant_chunk_ids={str(c) for c in row["relevant_chunk_ids"]},
            answer_points=list(case.acceptable_answer_points),
            context_text=full_sources,
            should_refuse=bool(row["should_refuse"]),
        )

        paired_row = {
            "case_id": case_id,
            "query": row["query"],
            "query_type": row["query_type"],
            "language": row["language"],
            "should_refuse": row["should_refuse"],
            "baseline_answer": answer,
            "paired_answer": new_answer,
            "full_sources": full_sources,
            "context_chunk_ids_ordered": ordered,
            "retarget_stats": {
                "examined": stats.examined,
                "retargeted": stats.retargeted,
                "unchanged": stats.unchanged,
                "invalid": stats.invalid,
                "slots_before": stats.slots_before,
                "slots_after": stats.slots_after,
                "groups": stats.groups,
                "fail_closed": stats.fail_closed,
            },
            "slot_changes": {
                "add": add, "retarget": retarget_changes, "delete": delete,
            },
            "citation_metrics": paired_metrics.to_dict()
            if hasattr(paired_metrics, "to_dict")
            else _metrics_to_dict(paired_metrics),
            "baseline_citation_metrics": row["citation_metrics"],
            "assertions_ok": not case_failures,
            "assertion_failures": case_failures,
        }
        paired_rows.append(paired_row)
        per_case_slots.append({
            "case_id": case_id,
            "add": add, "retarget": retarget_changes, "delete": delete,
            "fail_closed": stats.fail_closed,
        })
        if case_failures:
            failures.append({"case_id": case_id, "reasons": case_failures})

    # ── 输出 ──
    with (OUT_DIR / "outcomes-paired.jsonl").open("w", encoding="utf-8") as f:
        for r in paired_rows:
            f.write(dump_line(r) + "\n")

    ok = not failures and len(paired_rows) == 150
    consistency = {
        "stage": "m6a-paired-replay-consistency",
        "checked_cases": len(paired_rows),
        "assertions": [
            "slots_before == slots_after",
            "add == 0 and delete == 0",
            "stripped([S#]) new_answer == baseline answer (byte-identical)",
        ],
        "failures": failures,
        "chunk_store_unresolvable_cases": [
            f for f in failures if any("chunk store 缺失" in r
                                      for r in f["reasons"])],
        "ok": ok,
        "verdict": "CONSISTENT" if ok else "INVALID",
    }
    (OUT_DIR / "consistency.json").write_text(
        json.dumps(consistency, ensure_ascii=False, indent=1,
                   sort_keys=True) + "\n",
        encoding="utf-8")

    recalls = [r["citation_metrics"]["citation_recall"] for r in paired_rows]
    precisions = [r["citation_metrics"]["citation_precision"]
                  for r in paired_rows]
    replay_stats = {
        "stage": "m6a-paired-replay-stats",
        "module_sha256": module_sha,
        "cases": len(paired_rows),
        "slot_totals": {
            "add": total_add, "retarget": total_retarget,
            "delete": total_delete,
        },
        "stats_sums": stats_sums,
        "fail_closed_cases": fail_closed_cases,
        "per_case": per_case_slots,
        "paired_aggregates": {
            "citation_recall_raw": (sum(recalls) / len(recalls))
            if recalls else 0.0,
            "citation_recall_avg": round(sum(recalls) / len(recalls), 4)
            if recalls else 0.0,
            "citation_precision_raw": (sum(precisions) / len(precisions))
            if precisions else 0.0,
            "citation_precision_avg": round(sum(precisions) / len(precisions),
                                            4) if precisions else 0.0,
            "fabricated_citation_count": sum(
                r["citation_metrics"]["fabricated_citation_count"]
                for r in paired_rows),
            "retrieved_not_in_context_count": sum(
                r["citation_metrics"]["retrieved_not_in_context_count"]
                for r in paired_rows),
        },
    }
    (OUT_DIR / "replay-stats.json").write_text(
        json.dumps(replay_stats, ensure_ascii=False, indent=1,
                   sort_keys=True) + "\n",
        encoding="utf-8")

    print(f"[replay] cases={len(paired_rows)} add={total_add} "
          f"retarget={total_retarget} delete={total_delete} "
          f"fail_closed={fail_closed_cases}")
    print(f"[replay] paired recall_avg="
          f"{replay_stats['paired_aggregates']['citation_recall_avg']} "
          f"precision_avg="
          f"{replay_stats['paired_aggregates']['citation_precision_avg']}")
    print(f"[replay] consistency: {consistency['verdict']}")
    return 0 if ok else 2


def _metrics_to_dict(metrics: Any) -> dict[str, Any]:
    """CitationMetrics → JSON 字典（tuple→list，兼容无 to_dict 的版本）。"""
    import dataclasses
    out: dict[str, Any] = {}
    for f in dataclasses.fields(metrics):
        value = getattr(metrics, f.name)
        if isinstance(value, tuple):
            value = [
                _metrics_to_dict(v) if dataclasses.is_dataclass(v) else v
                for v in value
            ]
        elif dataclasses.is_dataclass(value):
            value = _metrics_to_dict(value)
        out[f.name] = value
    return out


if __name__ == "__main__":
    raise SystemExit(main())
