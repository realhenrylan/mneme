"""Phase 6-B0.1 — v2.0.11 frozen product contract baseline, hardened entry.

在 Phase 6-B0 基础上硬化 chunk snapshot contract 的**产品入口边界**（修复
三个已独立复现的阻断缺陷，TDD RED→GREEN，见 tests/test_index_contract.py
Group 4/5）：

1. ``src.rag.build_index`` 不再先 ``get_or_create_collection`` 再校验 source
   集合——入口验证前置到任何 PersistentClient / 模型 / collection /
   manifest / BM25 sidecar 写入之前（空 chroma_path 保持无任何文件）；
2. 复用已有 collection 前校验调用方 ``file_paths`` 与 collection manifest
   ``sources`` 均与 snapshot **精确一致**——缺失/额外 source 拒绝，陈旧
   manifest 强制安全重建（绝不复用陈旧索引）；
3. snapshot 保留输入身份（chunks / chunk-manifest / corpus-manifest 路径），
   ``src.rag.prepare_index`` / ``build_index`` 在使用时经
   ``src.index_contract.verify_snapshot_current`` **重新执行**全量验证并
   比对重建契约指纹 / chunk 内容 / source 集合——伪造 fingerprint、
   dataclasses.replace 篡改、载入后输入漂移一律 fail-closed（SnapshotContractError），
   绝不降级为 parser 路径；索引内容永远来自受验证输入的重建，不来自内存对象。

本脚本把 B0 的 contract 基线重新跑进**新目录**
``evaluation/product-baselines/v2.0.11-frozen-contract-hardened/``：
- 先复算**旧 B0 manifest**（self-hash + 全部 inputs / frozen_outputs /
  outputs 字节 SHA）作为 lineage 前置校验——任一漂移 → fail-closed 零产物；
- 复用 B0 的完整管线（冻结 61 项复算 → 6A manifest 复算 → snapshot →
  全产品入口建索引 → 136 case 检索 → 与 6A/B0 对比 → 两次独立构建
  确定性记录）；
- 产物 7 个：B0 的 6 个同名文件 + ``comparison-to-phase6b0.md``（修复说明
  与对比）；manifest 记录旧 B0 manifest 的 lineage SHA。
- 旧 B0 产物、v2.0.11 冻结输入、用户 CHROMA_DB_PATH 一律只读。

CLI
---
::

    python scripts/evaluate_v211_frozen_product_contract_hardened.py
        [--output DIR] [--phase6b0-dir DIR] [--skip-determinism]

退出码：0=成功；2=冻结 / 6A / 旧 B0 / contract 漂移（fail-closed，零产物）；
1=其他错误。

不包含任何 LLM/生成路径；检索期间无网络调用（强制离线加载模型）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 强制离线（在导入任何模型库之前无条件设置，与 Phase 6-A/B0 一致）
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.evaluate_v211_frozen_product_baseline as bl6a  # noqa: E402
import scripts.evaluate_v211_frozen_product_contract as cbl  # noqa: E402
import src.index_contract as ic  # noqa: E402

# ── 目录常量 ──────────────────────────────────────────────────────────
PHASE6B0_DIR = cbl.OUTPUT_DIR
HARDENED_DIR = REPO_ROOT / "evaluation/product-baselines/v2.0.11-frozen-contract-hardened"
COLLECTION_NAME = cbl.COLLECTION_NAME
FREEZE_DIR = bl6a.FREEZE_DIR

# 本阶段产物（白名单，测试依赖）：B0 的 6 个同名文件 + 与旧 B0 对比
HARDENED_OUTPUT_FILES = cbl.CONTRACT_OUTPUT_FILES + (
    "comparison-to-phase6b0.md",
)

# 与 6A/B0 对比的指标键（aggregate 域）
_COMPARE_METRIC_KEYS = cbl._COMPARE_METRIC_KEYS

BaselineDrift = cbl.BaselineDrift


# ── 旧 B0 manifest 复算（lineage 前置校验）───────────────────────────

def verify_b0_manifest(phase6b0_dir: Path) -> dict:
    """复算旧 Phase 6-B0 baseline manifest：self-hash + 全部 inputs /
    frozen_outputs / outputs 字节 SHA。纯只读。

    Returns:
        {"verified", "checks", "drift"}
    """
    manifest_path = Path(phase6b0_dir) / "manifest.json"
    checks: list[dict] = []
    if not manifest_path.is_file():
        return {"verified": False, "checks": [], "drift": [{
            "name": "phase6b0-manifest", "kind": "missing",
            "status": "missing", "expected": None, "actual": None,
            "path": str(manifest_path),
        }]}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = bl6a.self_hash(manifest)
    checks.append({
        "name": "phase6b0-manifest self-hash", "kind": "manifest_self_hash",
        "status": "ok" if actual == manifest.get("manifest_sha256") else "mismatch",
        "expected": manifest.get("manifest_sha256"), "actual": actual,
        "path": str(manifest_path),
    })
    for section, base in (("inputs", None), ("frozen_outputs", FREEZE_DIR),
                          ("outputs", Path(phase6b0_dir))):
        for name, rec in sorted(manifest.get(section, {}).items()):
            if isinstance(rec, str):  # outputs 记录为 name -> sha 字符串
                path = base / name
                expected = rec
            else:
                path = Path(rec["path"])
                expected = rec["sha256"]
            actual_sha = bl6a.sha256_bytes(path) if path.is_file() else None
            checks.append({
                "name": f"phase6b0 {section}/{name}", "kind": section,
                "status": ("ok" if actual_sha == expected
                           else ("missing" if actual_sha is None else "mismatch")),
                "expected": expected, "actual": actual_sha, "path": str(path),
            })
    drift = [
        {k: c[k] for k in ("name", "kind", "status", "expected", "actual", "path")}
        for c in checks if c["status"] != "ok"
    ]
    return {"verified": not drift, "checks": checks, "drift": drift}


# ── 与旧 B0 对比（诚实记录，不伪称逐 case 字节一致）──────────────────

def compare_to_phase6b0(
    phase6b0_dir: Path,
    results: list[dict],
    metrics: dict,
    fingerprint: str,
) -> dict:
    """与旧 B0 的 aggregate 指标、分母、指纹、per-case 差异逐项对比。"""
    b0 = Path(phase6b0_dir)
    summary_b0 = json.loads(
        (b0 / "contract-baseline-summary.json").read_text(encoding="utf-8"))
    rows_b0 = {
        r["case_id"]: r
        for r in bl6a.load_jsonl(b0 / "per-case-retrieval-results.jsonl")
    }
    m0 = summary_b0["metrics"]["overall"]
    m1 = metrics["overall"]

    aggregate_deltas: dict[str, float | None] = {}
    for key in _COMPARE_METRIC_KEYS:
        a, b = m0.get(key), m1.get(key)
        aggregate_deltas[key] = (
            round(b - a, 6) if a is not None and b is not None else None)

    den0 = m0["denominators"]
    den1 = m1["denominators"]
    denominators_equal = den0 == den1

    per_case: list[dict] = []
    for r in results:
        other = rows_b0.get(r["case_id"])
        if other is None:
            per_case.append({"case_id": r["case_id"], "note": "missing in B0"})
            continue
        metric_diffs = {
            k: {"phase6b0": other["metrics"].get(k), "hardened": r["metrics"].get(k)}
            for k in _COMPARE_METRIC_KEYS
            if r["metrics"].get(k) != other["metrics"].get(k)
        }
        retrieved_equal = r["retrieved_chunk_ids"] == other["retrieved_chunk_ids"]
        if metric_diffs or not retrieved_equal:
            per_case.append({
                "case_id": r["case_id"],
                "metric_diffs": metric_diffs,
                "retrieved_equal": retrieved_equal,
                "n_retrieved": len(r["retrieved_chunk_ids"]),
                "n_retrieved_b0": len(other["retrieved_chunk_ids"]),
            })
    per_case.sort(key=lambda c: c["case_id"])

    b0_fingerprint = summary_b0.get("contract", {}).get("fingerprint")
    return {
        "phase6b0_dir": str(b0),
        "aggregate_deltas": aggregate_deltas,
        "aggregate_deltas_nonzero": [
            {"key": k, "delta": aggregate_deltas[k]}
            for k in _COMPARE_METRIC_KEYS
            if aggregate_deltas.get(k)
        ],
        "denominators": {
            "phase6b0": den0, "hardened": den1, "equal": denominators_equal},
        "per_case_metric_diff_count": sum(
            1 for c in per_case if c.get("metric_diffs")),
        "per_case_retrieval_diff_count": sum(
            1 for c in per_case if c.get("retrieved_equal") is False),
        "per_case_differences": per_case[:50],
        "fingerprint": {
            "phase6b0": b0_fingerprint,
            "hardened": fingerprint,
            "identical": b0_fingerprint == fingerprint,
        },
        "determinism_b0": summary_b0.get("determinism", {}),
        "note": "两阶段使用同一冻结 1006 chunks、同一产品索引入口与同一检索"
                "代码；入口硬化不改变索引内容（指纹应一致）。任何 per-case "
                "差异来源为 HNSW 跨构建近邻扰动，如实记录，不伪称逐 case "
                "字节一致",
    }


def _render_comparison_to_phase6b0(comparison: dict, b0_report: dict) -> str:
    lines = [
        "# Comparison to Phase 6-B0 — frozen-contract vs frozen-contract-hardened",
        "",
        "## 修复说明（Phase 6-B0.1 产品入口硬化）",
        "",
        "本阶段修复了三个已独立复现的入口边界缺陷（TDD RED→GREEN，",
        "`tests/test_index_contract.py` Group 4/5）：",
        "",
        "1. **build_index 先建 collection 再校验 source 集合**——source 集合不"
        "匹配时已产生空 collection 与 `chroma.sqlite3`；现在验证前置到任何 "
        "PersistentClient / 模型 / collection / manifest / BM25 sidecar 写入"
        "之前，传入的空 `chroma_path` 保持无任何文件。",
        "2. **复用已有 collection 不校验集合**——传入缺少一个 source 的 "
        "`file_paths` 会被静默复用；现在 `file_paths` 必须与 snapshot 源集合"
        "**精确一致**（缺失/额外 → 拒绝），且复用前校验 collection manifest "
        "的 `sources` 与 snapshot 一致（不一致 → 强制安全重建，绝不复用陈旧"
        "索引）。",
        "3. **入口只信任内存对象**——`dataclasses.replace` 篡改（篡改 chunk "
        "文本 + 伪造 fingerprint）仍被接受；现在 snapshot 保留输入身份，"
        "使用时经 `src.index_contract.verify_snapshot_current` 重新执行 "
        "`load_chunk_snapshot` 全量验证并比对重建契约指纹 / chunk 内容 / "
        "source 集合，失败抛 `SnapshotContractError`（fail-closed），索引内容"
        "永远来自受验证输入的重建。",
        "",
        "## 两阶段异同",
        "",
        "- 相同：同一冻结 1006 chunks、同一 136 cases、同一产品索引入口"
        "（`src.rag.prepare_index` + snapshot）、同一检索代码"
        "（embedding → Chroma cosine → BM25 CJK n-gram → RRF k=60）。",
        "- 差异：本阶段入口在**任何写入之前**重新验证 snapshot（指纹应一致，"
        "见下）；旧 B0 产物保持只读，lineage SHA 记录于 manifest。",
        "",
        "## 与旧 B0 的 aggregate 指标对比（Δ = hardened − B0）",
        "",
        "| 指标 | Δ |",
        "|---|---|",
    ]
    for key in _COMPARE_METRIC_KEYS:
        delta = comparison["aggregate_deltas"].get(key)
        lines.append(f"| {key} | {delta if delta is not None else '—'} |")
    lines += [
        "",
        f"- 分母：B0 {comparison['denominators']['phase6b0']} vs "
        f"hardened {comparison['denominators']['hardened']}，"
        f"**{'一致' if comparison['denominators']['equal'] else '不一致'}**。",
        f"- 契约指纹：B0 `{comparison['fingerprint']['phase6b0']}` vs "
        f"hardened `{comparison['fingerprint']['hardened']}`，"
        f"**{'一致' if comparison['fingerprint']['identical'] else '不一致'}**"
        "（同一受验证输入）。",
        f"- per-case 指标差异 case 数：**{comparison['per_case_metric_diff_count']}**；"
        f"per-case 检索集合差异 case 数：**{comparison['per_case_retrieval_diff_count']}**。",
        f"- 非零 aggregate Δ：{comparison['aggregate_deltas_nonzero'] or '无'}",
        "",
        "## 旧 B0 manifest 复算（lineage）",
        "",
        f"- {len(b0_report['checks'])} 项复算"
        f"（self-hash + inputs / frozen_outputs / outputs 字节 SHA）："
        f"**{'通过' if b0_report['verified'] else '失败'}**"
        f"（漂移 {len(b0_report['drift'])} 项）。",
        "",
        "## 确定性",
        "",
        "- 本阶段两次独立构建（determinism）：raw 差异与指标受影响 case 数"
        "见 `contract-baseline-summary.json` 的 determinism（如实记录，不伪称"
        "逐 case 字节一致）。",
        "- 旧 B0 记录的 determinism："
        f"`{comparison['determinism_b0'] or '无'}`。",
        "- HNSW 跨构建近邻扰动是环境/链路事实：同索引重复查询逐位一致，"
        "跨构建在深 rank 处有扰动；聚合指标应稳定，任何差异已在 "
        "`aggregate_deltas` 中如实列出，不做掩盖。",
    ]
    return "\n".join(lines)


# ── 编排（B0 管线 + lineage 前置校验 + 硬化后处理）───────────────────

def run_hardened_baseline(
    *,
    revision_dir: Path,
    chunks_path: Path,
    chunk_manifest_path: Path,
    current_draft_path: Path,
    corpus_manifest_path: Path,
    phase6a_dir: Path,
    phase6b0_dir: Path,
    out_dir: Path,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
    collection_name: str = COLLECTION_NAME,
    verify_determinism: bool = True,
) -> dict:
    """执行只读 hardened contract 基线并写出全部产物。

    顺序（任一漂移 → BaselineDrift，零产物）：
    1. 旧 B0 manifest 复算（lineage 前置校验）；
    2. cbl.run_contract_baseline：冻结 61 项 + 6A manifest 复算 → snapshot →
       全产品入口建索引 → 136 case 检索 → 与 6A 对比 → 两次独立构建；
    3. 与旧 B0 对比 + 修复说明（comparison-to-phase6b0.md）；
    4. summary / dq / manifest 附加硬化与 lineage 段。
    """
    repo_root = Path(repo_root or REPO_ROOT)
    out_dir = Path(out_dir)
    b0_dir = Path(phase6b0_dir)

    # 产物目录不得与任何受保护目录重叠（含旧 B0 目录）
    bl6a._check_output_containment(out_dir, [
        Path(revision_dir), Path(chunks_path).parent,
        Path(current_draft_path).parent, Path(corpus_manifest_path).parent,
        Path(phase6a_dir), b0_dir,
        REPO_ROOT / "evaluation/datasets/v2", REPO_ROOT / "data/v2-corpus",
    ])

    # 1. 旧 B0 manifest 复算（fail-closed：先于任何产物写入）
    b0_report = verify_b0_manifest(b0_dir)
    if not b0_report["verified"]:
        raise BaselineDrift("phase6b0 baseline manifest drift: " + json.dumps(
            b0_report["drift"], ensure_ascii=False))

    # 2. 完整 contract 基线（冻结 / 6A 漂移同样零产物）
    summary = cbl.run_contract_baseline(
        revision_dir=revision_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path,
        corpus_manifest_path=corpus_manifest_path,
        phase6a_dir=phase6a_dir, out_dir=out_dir, data_dir=data_dir,
        repo_root=repo_root, collection_name=collection_name,
        verify_determinism=verify_determinism,
    )

    # lineage 身份 = 旧 B0 manifest 的 self-hash（manifest_sha256，已由
    # verify_b0_manifest 复算核验）——与项目 manifest 互引约定一致
    b0_manifest_sha = json.loads(
        (b0_dir / "manifest.json").read_text(encoding="utf-8")
    )["manifest_sha256"]

    # 3. 与旧 B0 对比 + 修复说明
    comparison_b0 = compare_to_phase6b0(
        b0_dir, summary["results"], summary["metrics"],
        fingerprint=summary["snapshot"].fingerprint,
    )
    (out_dir / "comparison-to-phase6b0.md").write_text(
        _render_comparison_to_phase6b0(comparison_b0, b0_report),
        encoding="utf-8")

    # 4. summary 附加硬化与对比段
    summary_path = out_dir / "contract-baseline-summary.json"
    doc = json.loads(summary_path.read_text(encoding="utf-8"))
    doc["hardening"] = {
        "entry_revalidation": True,
        "mechanism": "src.rag.prepare_index / build_index 在使用时重跑 "
                     "src.index_contract.load_chunk_snapshot 验证并比对重建"
                     "契约指纹 / chunk 内容 / source 集合；验证先于任何 "
                     "PersistentClient / 模型 / collection / manifest / "
                     "BM25 sidecar 写入（fail-closed，绝不降级 parser）",
        "defects_fixed": [
            "build_index 不再先创建 collection 再校验 source 集合——验证"
            "前置到任何写入之前",
            "复用已有 collection 前校验 file_paths 与 manifest sources 均与"
            "snapshot 精确一致——缺失/额外 source 拒绝，陈旧 manifest 强制"
            "安全重建",
            "snapshot 保留输入身份，使用时重新验证——伪造 fingerprint、"
            "dataclasses.replace 篡改、载入后输入漂移一律 fail-closed",
        ],
        "b0_manifest_verified": b0_report["verified"],
        "b0_lineage_sha256": b0_manifest_sha,
    }
    doc["comparison_to_phase6b0"] = comparison_b0
    summary_path.write_text(bl6a.canonical_json(doc), encoding="utf-8")

    # 5. dq 报告附加 lineage 检查（data-analytics skill 不可用 → 等价机械复算）
    dq_path = out_dir / "data-quality-report.json"
    dq = json.loads(dq_path.read_text(encoding="utf-8"))
    dq["checks"].append({
        "name": "contract.b0_manifest_verified",
        "ok": b0_report["verified"],
        "detail": f"{len(b0_report['checks'])} checks, "
                  f"{len(b0_report['drift'])} drift",
    })
    dq["checks"].append({
        "name": "contract.b0_lineage_sha",
        "ok": True,
        "detail": b0_manifest_sha,
    })
    if not b0_report["verified"]:
        dq["passed"] = False
        dq["error_count"] = dq["error_count"] + 1
        dq["errors"].append("contract.b0_manifest_verified: B0 manifest drift")
    dq_path.write_text(bl6a.canonical_json(dq), encoding="utf-8")

    # 6. manifest 附加 lineage + hardening，重算 outputs 与 self-hash
    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["lineage"] = {
        "phase6b0_manifest_sha256": b0_manifest_sha,
        "phase6b0_dir": str(b0_dir),
        "phase6b0_manifest_verified": b0_report["verified"],
        "phase6b0_checks": len(b0_report["checks"]),
        "note": "旧 Phase 6-B0 manifest self-hash + 全部 inputs / "
                "frozen_outputs / outputs 字节复算；任一漂移 → 本基线零产物",
    }
    manifest["hardening"] = doc["hardening"]
    for name in ("contract-baseline-summary.json",
                 "comparison-to-phase6b0.md", "data-quality-report.json"):
        manifest["outputs"][name] = bl6a.sha256_bytes(out_dir / name)
    manifest["manifest_sha256"] = bl6a.self_hash(manifest)
    manifest_path.write_text(bl6a.canonical_json(manifest), encoding="utf-8")

    summary["manifest"] = manifest
    summary["comparison_b0"] = comparison_b0
    summary["b0_report"] = b0_report
    summary["b0_dir"] = b0_dir
    return summary


def main(argv: list[str] | None = None) -> int:
    """CLI。退出码：0=成功；2=冻结/6A/旧 B0/contract 漂移（零产物）；1=其他。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase 6-B0.1: hardened frozen product contract baseline")
    parser.add_argument("--revision-dir", type=Path,
                        default=cbl.FROZEN_REVISION_DIR)
    parser.add_argument("--chunks", type=Path, default=cbl.CHUNKS_PATH)
    parser.add_argument("--chunk-manifest", type=Path,
                        default=cbl.CHUNK_MANIFEST_PATH)
    parser.add_argument("--current-draft", type=Path,
                        default=cbl.CURRENT_DRAFT_PATH)
    parser.add_argument("--corpus-manifest", type=Path,
                        default=cbl.CORPUS_MANIFEST_PATH)
    parser.add_argument("--phase6a-dir", type=Path, default=cbl.PHASE6A_DIR)
    parser.add_argument("--phase6b0-dir", type=Path, default=PHASE6B0_DIR)
    parser.add_argument("--output", type=Path, default=HARDENED_DIR)
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="临时数据目录（默认自动创建并在结束后清理）")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--skip-determinism", action="store_true")
    args = parser.parse_args(argv)

    try:
        summary = run_hardened_baseline(
            revision_dir=args.revision_dir, chunks_path=args.chunks,
            chunk_manifest_path=args.chunk_manifest,
            current_draft_path=args.current_draft,
            corpus_manifest_path=args.corpus_manifest,
            phase6a_dir=args.phase6a_dir, phase6b0_dir=args.phase6b0_dir,
            out_dir=args.output, data_dir=args.data_dir,
            repo_root=args.repo_root,
            verify_determinism=not args.skip_determinism,
        )
    except BaselineDrift as exc:
        print(f"FAIL-CLOSED: {exc}", file=sys.stderr)
        return 2
    except ic.SnapshotContractError as exc:
        print("FAIL-CLOSED: contract validation failed, zero outputs.",
              file=sys.stderr)
        for d in exc.drift:
            print(f"  [{d['name']}] {d['detail']}", file=sys.stderr)
        return 2
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1

    metrics = summary["metrics"]["overall"]
    print(f"hardened contract baseline complete: {summary['case_count']} cases "
          f"-> {args.output}")
    print(f"  fingerprint={summary['snapshot'].fingerprint[:16]}…")
    print(f"  b0 lineage={summary['b0_report']['verified']} "
          f"({len(summary['b0_report']['checks'])} checks)")
    print(f"  chunk recall@5={metrics.get('recall@5'):.4f} "
          f"recall@10={metrics.get('recall@10'):.4f} "
          f"recall@20={metrics.get('recall@20'):.4f} "
          f"mrr={metrics.get('mrr'):.4f}")
    print(f"  denominators: {metrics['denominators']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
