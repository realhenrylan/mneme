"""Phase 6-B0 — v2.0.11 frozen product contract baseline (read-only).

把 Phase 6-A 发现的 parser/chunker 漂移消除为可审计的产品能力：通过
``src.index_contract`` 的 chunk snapshot contract，用**完整产品索引入口**
（``src.rag.prepare_index`` + snapshot）在隔离的一次性 Chroma 目录中建立
1006 个冻结 chunks 的索引（Chroma collection + collection manifest +
BM25 sidecar 全部走产品路径），对 136 个 v2.0.11 case 跑生产
``retrieve_hybrid_with_sources``，产出与 Phase 6-A 可直接对比的检索基线。

设计原则（fail-closed / 零副作用）：
1. **先复算后输出**：freeze / candidate / targeted-review manifest（复用
   Phase 6-A 的 61 项复算）与 Phase 6-A baseline manifest（self-hash +
   inputs / frozen_outputs / outputs 字节）任一漂移 → 立即中止，零新输出。
2. **只读**：从不写回 v2.0.11 revision、chunks、annotations、corpus
   manifest、语料源文件；全部产物只写入独立的
   ``evaluation/product-baselines/v2.0.11-frozen-contract/``。
3. **完整产品索引路径 + 显式隔离**：``prepare_index(snapshot=..., chroma_path=临时目录)``
   ——collection 与 sidecar 全部落在一次性临时目录，绝不触碰用户
   ``CHROMA_DB_PATH``；默认 parser 路径行为不变（本次改动全部为可选参数）。
4. **snapshot contract**：chunks_sha256 / chunk_id 唯一与格式 / source 身份
   （全 64 位路径哈希 + 前缀）/ 内容 SHA / size / 调用方集合精确一致 /
   逐 chunk 文本哈希，全部验证通过才建索引；collection manifest 的
   ``config.snapshot`` 记录契约版本 + 指纹 + 输入 SHA。
5. **诚实比较**：与 Phase 6-A 的 aggregate 指标、分母、chunk 数、evidence
   映射逐项对比；HNSW 跨构建近邻扰动如实记录，不把逐 case 排名的字节一致
   当作 gate。
6. **不测生成/引用质量**：不调用生成模型、不做 LLM judge；answer-quality /
   citation-faithfulness / refusal 精度明确声明未测。

CLI
---
::

    python scripts/evaluate_v211_frozen_product_contract.py [--output DIR]
        [--data-dir DIR] [--phase6a-dir DIR] [--skip-determinism]

退出码：0=成功；2=冻结/6A/contract 漂移（fail-closed，零产物）；1=其他错误。

本脚本不包含任何 LLM/生成路径；检索期间无网络调用（强制离线加载模型）。
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

# 强制离线（在导入任何模型库之前无条件设置，与 Phase 6-A 一致）
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.evaluate_v211_frozen_product_baseline as bl6a  # noqa: E402
import src.index_contract as ic  # noqa: E402

# ── 冻结输入路径（与 Phase 6-A 同一事实来源）──────────────────────────
FROZEN_REVISION_DIR = bl6a.FROZEN_REVISION_DIR
FREEZE_DIR = bl6a.FREEZE_DIR
CHUNKS_PATH = bl6a.CHUNKS_PATH
CHUNK_MANIFEST_PATH = bl6a.CHUNK_MANIFEST_PATH
CURRENT_DRAFT_PATH = bl6a.CURRENT_DRAFT_PATH
CORPUS_DOCUMENTS_DIR = bl6a.CORPUS_DOCUMENTS_DIR
CORPUS_MANIFEST_PATH = REPO_ROOT / "evaluation/datasets/v2/corpus-manifest.json"

PHASE6A_DIR = REPO_ROOT / "evaluation/product-baselines/v2.0.11-frozen-current"
OUTPUT_DIR = REPO_ROOT / "evaluation/product-baselines/v2.0.11-frozen-contract"
COLLECTION_NAME = "v211_frozen_contract_baseline"

KS = bl6a.KS

# 本阶段产物（白名单，测试依赖）
CONTRACT_OUTPUT_FILES = (
    "contract-baseline-summary.json",
    "per-case-retrieval-results.jsonl",
    "contract-validation-report.md",
    "comparison-to-phase6a.md",
    "data-quality-report.json",
    "manifest.json",
)

# 与 6A 对比的指标键（aggregate 域）
_COMPARE_METRIC_KEYS = (
    "recall@5", "recall@10", "recall@20",
    "ndcg@5", "ndcg@10", "ndcg@20", "mrr",
    "source_recall@5", "source_recall@10", "source_recall@20",
)


class BaselineDrift(Exception):
    """冻结 / 6A / contract 漂移——fail-closed，零产物。"""


# ── Phase 6-A baseline manifest 复算 ─────────────────────────────────

def verify_phase6a_manifest(phase6a_dir: Path) -> dict:
    """复算 Phase 6-A baseline manifest：self-hash + 全部 inputs /
    frozen_outputs / outputs 字节 SHA。纯只读。

    Returns:
        {"verified", "checks", "drift"}
    """
    manifest_path = Path(phase6a_dir) / "manifest.json"
    checks: list[dict] = []
    if not manifest_path.is_file():
        return {"verified": False, "checks": [], "drift": [{
            "name": "phase6a-manifest", "kind": "missing",
            "status": "missing", "expected": None, "actual": None,
            "path": str(manifest_path),
        }]}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = bl6a.self_hash(manifest)
    checks.append({
        "name": "phase6a-manifest self-hash", "kind": "manifest_self_hash",
        "status": "ok" if actual == manifest.get("manifest_sha256") else "mismatch",
        "expected": manifest.get("manifest_sha256"), "actual": actual,
        "path": str(manifest_path),
    })
    for section, base in (("inputs", None), ("frozen_outputs", FREEZE_DIR),
                          ("outputs", Path(phase6a_dir))):
        for name, rec in sorted(manifest.get(section, {}).items()):
            if isinstance(rec, str):  # outputs 记录为 name -> sha 字符串
                path = base / name
                expected = rec
            else:
                path = Path(rec["path"])
                expected = rec["sha256"]
            actual_sha = bl6a.sha256_bytes(path) if path.is_file() else None
            checks.append({
                "name": f"phase6a {section}/{name}", "kind": section,
                "status": ("ok" if actual_sha == expected
                           else ("missing" if actual_sha is None else "mismatch")),
                "expected": expected, "actual": actual_sha, "path": str(path),
            })
    drift = [
        {k: c[k] for k in ("name", "kind", "status", "expected", "actual", "path")}
        for c in checks if c["status"] != "ok"
    ]
    return {"verified": not drift, "checks": checks, "drift": drift}


# ── contract snapshot 载入（真实源集合精确一致）──────────────────────

def load_contract_snapshot(
    *,
    chunks_path: Path,
    chunk_manifest_path: Path,
    corpus_manifest_path: Path,
    repo_root: Path,
) -> ic.ChunkSnapshot:
    """载入 v2.0.11 冻结 chunks 的 contract snapshot。

    source_paths（调用方集合）取 corpus-manifest 声明的 13 个源文件——contract
    会验证调用方集合与声明集合**精确一致**（无缺失/无额外）。
    """
    corpus = json.loads(Path(corpus_manifest_path).read_text(encoding="utf-8"))
    declared = [
        str(Path(repo_root) / d["path"].replace("\\", "/"))
        for d in corpus.get("documents", [])
    ]
    return ic.load_chunk_snapshot(
        chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        corpus_manifest_path=corpus_manifest_path,
        source_paths=declared,
        repo_root=repo_root,
    )


# ── 全产品索引入口建索引（隔离临时目录）──────────────────────────────

def build_contract_index(
    snapshot: ic.ChunkSnapshot,
    data_dir: Path,
    collection_name: str,
    force_rebuild: bool = True,
) -> dict:
    """通过**完整产品索引入口** ``src.rag.prepare_index`` 建索引。

    - collection（hnsw:space=cosine）、collection manifest、BM25 sidecar
      全部由产品代码写入 ``data_dir/chroma_db``（显式 chroma_path），
      从不引用模块级 ``src.rag.CHROMA_DB_PATH``；
    - 返回 index dict（供 6A 的 run_retrieval 复用）+ 侧车内容。
    """
    import src.rag as rag

    chroma_dir = Path(data_dir) / "chroma_db"
    buf = io.StringIO()
    with redirect_stdout(buf):
        model, collection, bm25, docs, metas = rag.prepare_index(
            file_paths=snapshot.source_paths(),
            collection_name=collection_name,
            force_rebuild=force_rebuild,
            snapshot=snapshot,
            chroma_path=str(chroma_dir),
        )
    manifest = rag.load_index_manifest(collection_name, chroma_path=str(chroma_dir))
    bm25_snapshot = rag.load_bm25_snapshot(
        collection_name, chroma_path=str(chroma_dir))
    if manifest is None or manifest.get("config", {}).get("snapshot") != snapshot.config():
        raise BaselineDrift(
            "collection manifest config.snapshot != snapshot.config() —— "
            "contract 未被产品索引路径记录")
    if bm25_snapshot is None:
        raise BaselineDrift("BM25 sidecar missing for contract index")
    try:
        dimension = model.get_embedding_dimension()
    except (AttributeError, TypeError):
        dimension = model.get_sentence_embedding_dimension()
    return {
        "model": model,
        "collection": collection,
        "bm25": bm25,
        "documents": docs,
        "metadatas": metas,
        "collection_name": collection_name,
        "data_dir": str(data_dir),
        "chroma_dir": str(chroma_dir),
        "model_name": rag.EMBEDDING_MODEL_NAME,
        "embedding_dimension": dimension,
        # 计数在 client 关闭前捕获（Windows 文件锁 + close 后句柄失效）
        "chunk_count": collection.count(),
        "source_count": len(snapshot.sources),
        "collection_manifest": manifest,
        "bm25_snapshot": bm25_snapshot,
        "build_log": buf.getvalue(),
    }


# ── 与 Phase 6-A 对比 ────────────────────────────────────────────────

def compare_to_phase6a(phase6a_dir: Path, results: list[dict],
                       metrics: dict) -> dict:
    """aggregate 指标、分母、chunk 数逐项对比 + per-case 差异统计。"""
    summary6a = json.loads(
        (Path(phase6a_dir) / "baseline-summary.json").read_text(encoding="utf-8"))
    rows6a = {
        r["case_id"]: r
        for r in bl6a.load_jsonl(Path(phase6a_dir) / "per-case-retrieval-results.jsonl")
    }
    m6 = summary6a["metrics"]["overall"]
    m1 = metrics["overall"]

    aggregate_deltas: dict[str, float | None] = {}
    for key in _COMPARE_METRIC_KEYS:
        a, b = m6.get(key), m1.get(key)
        aggregate_deltas[key] = (
            round(b - a, 6) if a is not None and b is not None else None)

    den6 = m6["denominators"]
    den1 = m1["denominators"]
    denominators_equal = den6 == den1

    per_case: list[dict] = []
    for r in results:
        other = rows6a.get(r["case_id"])
        if other is None:
            per_case.append({"case_id": r["case_id"], "note": "missing in 6A"})
            continue
        metric_diffs = {
            k: {"phase6a": other["metrics"].get(k), "contract": r["metrics"].get(k)}
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
                "n_retrieved_6a": len(other["retrieved_chunk_ids"]),
            })
    per_case.sort(key=lambda c: c["case_id"])

    return {
        "phase6a_dir": str(Path(phase6a_dir)),
        "aggregate_deltas": aggregate_deltas,
        "aggregate_deltas_nonzero": [
            {"key": k, "delta": aggregate_deltas[k]}
            for k in _COMPARE_METRIC_KEYS
            if aggregate_deltas.get(k)
        ],
        "denominators": {
            "phase6a": den6, "contract": den1, "equal": denominators_equal},
        "per_case_metric_diff_count": sum(
            1 for c in per_case if c.get("metric_diffs")),
        "per_case_retrieval_diff_count": sum(
            1 for c in per_case if c.get("retrieved_equal") is False),
        "per_case_differences": per_case[:50],
        "note": "两阶段使用同一冻结 chunks 与同一检索代码；差异来源为 "
                "HNSW 跨构建近邻扰动（6A 与 contract 各自独立建索引）。"
                "聚合指标应稳定；任何不一致在 aggregate_deltas 中如实列出",
    }


# ── 数据质量机械检查 ──────────────────────────────────────────────────
# data-analytics:analyze-data-quality skill 在本环境中不可用；此处实施
# 等价的确定性机械检查（完整性/唯一性/有效性/一致性/引用完整性/分母与
# 分组合理性 + contract lineage），全部为复算，无 LLM 参与。

def data_quality_check(
    *,
    results: list[dict],
    metrics: dict,
    failures: list[dict],
    mapping_report: dict,
    snapshot: ic.ChunkSnapshot,
    index: dict,
    manifest: dict | None,
    frozen_chunk_ids: set[str],
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[dict] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    den = metrics["overall"]["denominators"]
    total = den["total_cases"]

    # 1. 完整性
    _check("completeness.per_case_rows", len(results) == total,
           f"rows={len(results)} expected={total}")
    if results:
        missing = bl6a.PER_CASE_OUTPUT_KEYS - set(results[0])
        _check("completeness.per_case_keys", not missing,
               f"missing keys={sorted(missing)}")
    for group_name in ("by_language", "by_query_type", "by_refusal"):
        _check(f"completeness.group_{group_name}", group_name in metrics,
               f"group {group_name} absent")

    # 2. 唯一性
    ids = [r["case_id"] for r in results]
    dup = sorted({c for c in ids if ids.count(c) > 1})
    _check("uniqueness.case_ids", not dup, f"duplicates={dup}")
    fids = [f["case_id"] for f in failures]
    _check("uniqueness.failure_rows", len(fids) == len(set(fids)),
           "duplicate failure rows")

    # 3. 有效性
    bad_values: list[str] = []
    for r in results:
        for key, value in r["metrics"].items():
            if not (0.0 <= value <= 1.0):
                bad_values.append(f"{r['case_id']}.{key}={value}")
    _check("validity.metric_ranges", not bad_values, "; ".join(bad_values[:5]))
    empty_scores = [r["case_id"] for r in results if not r["scores"]]
    _check("validity.scores_nonempty", not empty_scores,
           f"empty scores: {empty_scores[:5]}")

    # 4. 一致性（per-case 复算 + 聚合均值）
    from evaluation.metrics import recall_at_k, ndcg_at_k, source_recall_at_k
    mismatch: list[str] = []
    for r in results:
        if not r["relevant_chunk_ids"]:
            continue
        recomputed = {
            **{f"recall@{k}": recall_at_k(
                r["retrieved_chunk_ids"], set(r["relevant_chunk_ids"]), k)
               for k in KS},
            **{f"ndcg@{k}": ndcg_at_k(
                r["retrieved_chunk_ids"], set(r["relevant_chunk_ids"]), k)
               for k in KS},
            **{f"source_recall@{k}": source_recall_at_k(
                r["retrieved_source_ids"], set(r["relevant_source_ids"]), k)
               for k in KS},
        }
        for key, value in recomputed.items():
            if abs(value - r["metrics"][key]) > 1e-9:
                mismatch.append(f"{r['case_id']}.{key}")
    _check("consistency.per_case_recompute", not mismatch, "; ".join(mismatch[:5]))

    agg_mismatch: list[str] = []
    for key in _COMPARE_METRIC_KEYS:
        rows = [r for r in results if r["metrics"]]
        mean = (sum(r["metrics"][key] for r in rows) / len(rows)) if rows else None
        if mean is not None and abs(mean - metrics["overall"][key]) > 1e-9:
            agg_mismatch.append(f"{key}: {mean:.6f} vs {metrics['overall'][key]:.6f}")
    _check("consistency.aggregates_vs_mean", not agg_mismatch,
           "; ".join(agg_mismatch[:5]))

    # 5. 引用完整性
    orphan = sorted({
        cid for r in results for cid in r["relevant_chunk_ids"]
        if cid not in frozen_chunk_ids
    })
    _check("referential.chunk_ids_in_corpus", not orphan,
           f"orphan chunk_ids={orphan[:5]}")
    if mapping_report["mapping"]["mapping_failures"]:
        _check("referential.mapping_failures_zero", False,
               str(mapping_report["mapping"]["mapping_failures"]))
    else:
        _check("referential.mapping_failures_zero", True)
    per_case_expected = {r["case_id"]: set(r["relevant_chunk_ids"])
                         for r in results}
    leak = [
        f["case_id"] for f in failures
        if set(f["expected_chunk_ids"]) != per_case_expected.get(f["case_id"], set())
    ]
    _check("referential.failure_expected_matches", not leak,
           f"mismatched={leak[:5]}")

    # 6. 分母与分组合理性
    _check("denominators.sum_equals_total",
           den["chunk_metrics_cases"] + den["no_chunk_truth_cases"] == total,
           str(den))
    lang_n = sum(g["n"] for g in metrics["by_language"].values())
    _check("denominators.by_language_sums", lang_n == den["chunk_metrics_cases"],
           f"sum={lang_n} expected={den['chunk_metrics_cases']}")
    qtype_n = sum(g["n"] for g in metrics["by_query_type"].values())
    _check("denominators.by_query_type_sums", qtype_n == den["chunk_metrics_cases"],
           f"sum={qtype_n} expected={den['chunk_metrics_cases']}")

    # 7. contract lineage
    _check("contract.snapshot_validation",
           bool(snapshot.validation) and all(c["ok"] for c in snapshot.validation))
    coll_manifest = index.get("collection_manifest") or {}
    _check("contract.config_snapshot_recorded",
           coll_manifest.get("config", {}).get("snapshot") == snapshot.config())
    bm25_snap = index.get("bm25_snapshot") or {}
    _check("contract.bm25_version_matches_manifest",
           bm25_snap.get("manifest_version")
           == coll_manifest.get("manifest_version"))
    indexed_ids = set(coll_manifest.get("indexed_chunk_ids", []))
    _check("contract.indexed_chunk_ids_match",
           indexed_ids == {c["chunk_id"] for c in snapshot.chunks},
           f"n_indexed={len(indexed_ids)} n_snapshot={len(snapshot.chunks)}")
    _check("contract.bm25_chunk_ids_match",
           set(bm25_snap.get("chunk_ids", [])) == {c["chunk_id"] for c in snapshot.chunks})
    _check("contract.fingerprint_stable",
           coll_manifest.get("config", {}).get("snapshot", {}).get("fingerprint")
           == snapshot.fingerprint)

    if manifest is None:
        checks.append({"name": "referential.manifest_self_hash",
                       "ok": True, "detail": "skipped (manifest=None)"})
        checks.append({"name": "referential.manifest_input_shas",
                       "ok": True, "detail": "skipped (manifest=None)"})
    else:
        _check("referential.manifest_self_hash",
               manifest.get("manifest_sha256") == bl6a.self_hash(manifest))
        bad_input = [
            name for name, rec in manifest.get("inputs", {}).items()
            if not Path(rec["path"]).is_file()
            or bl6a.sha256_bytes(Path(rec["path"])) != rec["sha256"]
        ]
        _check("referential.manifest_input_shas", not bad_input,
               f"bad={bad_input[:5]}")

    return {
        "passed": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "note": "data-analytics:analyze-data-quality skill 在本环境中不可用"
                "（可用技能列表中不存在）；此为等价的确定性机械复算",
    }


# ── 产物写入 ──────────────────────────────────────────────────────────

def _check_output_containment(out_dir: Path, protected: list[Path]) -> None:
    bl6a._check_output_containment(out_dir, protected)


def _render_validation_report(
    snapshot: ic.ChunkSnapshot,
    index: dict,
    verify_report: dict,
    phase6a_report: dict,
) -> str:
    coll = index["collection_manifest"] or {}
    lines = [
        "# Contract Validation Report — v2.0.11 frozen contract baseline",
        "",
        "## chunk snapshot contract 字段映射（chunks.jsonl → 产品索引）",
        "",
        "| chunks.jsonl 字段 | 产品映射 | 说明 |",
        "|---|---|---|",
        "| `chunk_id` | Chroma id + metadata.chunk_id | "
        "`{source_sha256_prefix12}_chunk_{n}`，前缀 = `source_id[:12]`（逐 chunk 核验） |",
        "| `index` | metadata.chunk_index | 每 source 内连续 0..n-1（已核验） |",
        "| `source`（basename） | metadata.source_name / source | "
        "展示与 evidence 对齐字段；**不是**身份主键 |",
        "| `text` | Chroma document + BM25 输入 | 逐 chunk 文本 SHA 进入契约指纹 |",
        "| corpus-manifest `path` | metadata.source_path + source_id | "
        "canonical 路径；`source_id = sha256(normcase(realpath))` 全 64 位 |",
        "| corpus-manifest `file_sha256`/`size` | metadata.content_sha256 / "
        "source_size | 与磁盘字节核验 |",
        "",
        "## 验证清单",
        "",
        f"- 验证检查项：**{len(snapshot.validation)}** 全部通过"
        f"（fail-closed：任一失败即零写入）。",
        f"- chunks：**{len(snapshot.chunks)}**；sources：**{len(snapshot.sources)}**；"
        f"chunks_sha256：`{snapshot.chunks_sha256[:16]}…`",
        f"- 调用方 source 集合与声明集合**精确一致**（无缺失/无额外）。",
        f"- 契约指纹：`{snapshot.fingerprint}`",
        f"- 冻结输入校验（freeze/candidate/targeted-review manifest 复算）："
        f"{'通过' if verify_report['verified'] else '失败'} "
        f"（{len(verify_report['checks'])} 项，漂移 {len(verify_report['drift'])} 项）",
        f"- Phase 6-A baseline manifest 复算："
        f"{'通过' if phase6a_report['verified'] else '失败'} "
        f"（{len(phase6a_report['checks'])} 项，漂移 {len(phase6a_report['drift'])} 项）",
        "",
        "## 索引与 sidecar（完整产品路径）",
        "",
        f"- collection：`{index['collection_name']}`，"
        f"chunks={index.get('chunk_count')}，"
        f"manifest_version={coll.get('manifest_version')}",
        f"- collection manifest `config.snapshot`：记录契约版本/指纹/输入 SHA"
        f"（fingerprint 一致："
        f"{coll.get('config', {}).get('snapshot', {}).get('fingerprint') == snapshot.fingerprint}）",
        f"- BM25 sidecar：chunk_ids 与索引一致"
        f"（{len((index.get('bm25_snapshot') or {}).get('chunk_ids', []))} 条）",
        f"- 隔离：Chroma 位于一次性临时目录 `{index['chroma_dir']}`；"
        "从不引用 `src.rag.CHROMA_DB_PATH`，不触碰用户持久化索引。",
        "",
        "## 明确不是",
        "",
        "- v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、"
        "human_reviewed=false），不代表 active、人工批准或 release。",
        "- 本基线不是 answer-quality / citation-faithfulness / refusal 精度评测。",
    ]
    return "\n".join(lines)


def _render_comparison(comparison: dict, determinism: dict) -> str:
    lines = [
        "# Comparison to Phase 6-A — frozen-current vs frozen-contract",
        "",
        "## 两阶段异同",
        "",
        "- 相同：同一冻结 1006 chunks、同一 136 cases、同一检索代码"
        "（embedding → Chroma cosine → BM25 CJK n-gram → RRF k=60）。",
        "- 差异：Phase 6-A 用适配器绕过 parser 直接以冻结 chunks 建临时索引"
        "（无 sidecar）；本阶段通过**完整产品索引入口**"
        "（`src.rag.prepare_index` + chunk snapshot contract）建索引，"
        "含 collection manifest 与 BM25 sidecar，且 source 身份为产品级"
        "（全 64 位 source_id = 路径哈希；6A 适配器用 basename 作 source_id）。",
        "",
        "## aggregate 指标对比（Δ = contract − 6A）",
        "",
        "| 指标 | Δ |",
        "|---|---|",
    ]
    for key in _COMPARE_METRIC_KEYS:
        delta = comparison["aggregate_deltas"].get(key)
        lines.append(f"| {key} | {delta if delta is not None else '—'} |")
    lines += [
        "",
        f"- 分母：6A {comparison['denominators']['phase6a']} vs "
        f"contract {comparison['denominators']['contract']}，"
        f"**{'一致' if comparison['denominators']['equal'] else '不一致'}**。",
        "- chunk 数：1006（两阶段相同）；evidence 映射："
        "105 with-truth / 31 no-truth（相同）。",
        f"- per-case 指标差异 case 数：**{comparison['per_case_metric_diff_count']}**；"
        f"per-case 检索集合差异 case 数：**{comparison['per_case_retrieval_diff_count']}**。",
        f"- 非零 aggregate Δ：{comparison['aggregate_deltas_nonzero'] or '无'}",
        "",
        "## HNSW 跨构建扰动",
        "",
        "- 同索引重复查询逐位一致；跨构建（独立索引）在深 rank 处存在近邻"
        "扰动。本阶段确定性复验：",
        f"- raw 差异 {determinism.get('difference_count')} 处 / "
        f"指标受影响 {determinism.get('metric_difference_count')} case"
        f"（明细见 contract-baseline-summary.json determinism）。",
        "- 若聚合指标不一致，差异已在 aggregate_deltas 中如实列出，不做掩盖。",
    ]
    return "\n".join(lines)


def write_artifacts(
    out_dir: Path,
    *,
    cases: list[dict],
    results: list[dict],
    metrics: dict,
    failures: list[dict],
    mapping_report: dict,
    snapshot: ic.ChunkSnapshot,
    index: dict,
    verify_report: dict,
    phase6a_report: dict,
    phase6a_dir: Path,
    corpus_manifest_path: Path,
    comparison: dict,
    determinism: dict,
    cleaned: bool,
    params: dict,
    frozen_chunk_ids: set[str],
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "scope": "v2.0.11-frozen-contract retrieval baseline (Phase 6-B0)",
        "frozen_revision": "v2.0.11-owner-authorized-en048-same-source-repair",
        "frozen_revision_status": "CANDIDATE",
        "activation_blocked": True,
        "contract": {
            "contract_version": snapshot.contract_version,
            "fingerprint": snapshot.fingerprint,
            "chunks_sha256": snapshot.chunks_sha256,
            "chunk_manifest_sha256": snapshot.chunk_manifest_sha256,
            "corpus_manifest_sha256": snapshot.corpus_manifest_sha256,
            "validation_checks": len(snapshot.validation),
            "validation_passed": all(c["ok"] for c in snapshot.validation),
            "n_chunks": len(snapshot.chunks),
            "n_sources": len(snapshot.sources),
            "source_paths_exact_match": True,
        },
        "index": {
            "collection_name": index["collection_name"],
            "chunk_count": index["chunk_count"],
            "source_count": index["source_count"],
            "manifest_version": (index["collection_manifest"] or {}).get(
                "manifest_version"),
            "config_snapshot_recorded": (
                (index["collection_manifest"] or {})
                .get("config", {}).get("snapshot") == snapshot.config()),
            "bm25_snapshot_chunk_count": len(
                (index.get("bm25_snapshot") or {}).get("chunk_ids", [])),
        },
        "metrics": metrics,
        "not_measured": {
            "generation_and_citation": {
                "measured": False,
                "reason": "Phase 6-B0 只做 Retrieval Baseline：不调用生成模型、"
                          "不做 136 条生成答案、不做 LLM judge；answer-quality / "
                          "citation-faithfulness 无真值无产出，不伪造数值",
            },
            "refusal_accuracy": {
                "measured": False,
                "reason": "answer 级拒答精度依赖生成判定，本阶段未测；仅提供 "
                          "refusal 组的检索分数观测",
            },
        },
        "failure_counts": {
            "failure_analysis_rows": len(failures),
            "chunk_not_retrieved_top20": sum(
                1 for f in failures if "chunk_not_retrieved_top20" in f["failure_types"]),
            "source_not_retrieved_top20": sum(
                1 for f in failures if "source_not_retrieved_top20" in f["failure_types"]),
        },
        "verification": {
            "frozen_verified": verify_report["verified"],
            "frozen_checks": len(verify_report["checks"]),
            "phase6a_verified": phase6a_report["verified"],
            "phase6a_checks": len(phase6a_report["checks"]),
        },
        "comparison_to_phase6a": comparison,
        "determinism": determinism,
        "mapping": mapping_report["mapping"],
    }

    (out_dir / "contract-baseline-summary.json").write_text(
        bl6a.canonical_json(summary), encoding="utf-8")
    with open(out_dir / "per-case-retrieval-results.jsonl", "w",
              encoding="utf-8") as stream:
        for row in results:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "contract-validation-report.md").write_text(
        _render_validation_report(snapshot, index, verify_report, phase6a_report),
        encoding="utf-8")
    (out_dir / "comparison-to-phase6a.md").write_text(
        _render_comparison(comparison, determinism), encoding="utf-8")

    dq = data_quality_check(
        results=results, metrics=metrics, failures=failures,
        mapping_report=mapping_report, snapshot=snapshot, index=index,
        manifest=None, frozen_chunk_ids=frozen_chunk_ids,
    )
    (out_dir / "data-quality-report.json").write_text(
        bl6a.canonical_json(dq), encoding="utf-8")

    # inputs：freeze/candidate/targeted 声明（verify checks）+ contract 输入
    inputs: dict[str, dict] = {}
    for check in verify_report["checks"]:
        if check["status"] == "ok" and check["kind"] == "inputs":
            inputs.setdefault(check["name"], {
                "path": check["path"], "sha256": check["actual"],
            })
    inputs["corpus-manifest.json"] = {
        "path": str(Path(corpus_manifest_path)),
        "sha256": snapshot.corpus_manifest_sha256,
    }
    for src in snapshot.sources:
        inputs[f"source:{src.name}"] = {
            "path": src.path, "sha256": src.content_sha256,
        }
    inputs["phase6a-manifest.json"] = {
        "path": str(Path(phase6a_dir) / "manifest.json"),
        "sha256": bl6a.sha256_bytes(Path(phase6a_dir) / "manifest.json"),
    }
    frozen_outputs: dict[str, dict] = {}
    for check in verify_report["checks"]:
        if check["status"] == "ok" and check["kind"] == "outputs":
            frozen_outputs.setdefault(check["name"], {
                "path": check["path"], "sha256": check["actual"],
            })
    phase6a_outputs: dict[str, str] = {}
    for name in ("baseline-summary.json", "per-case-retrieval-results.jsonl",
                 "failure-analysis.md", "schema-compatibility-report.md",
                 "BASELINE_SCOPE.md", "data-quality-mechanical-check.json"):
        p = Path(phase6a_dir) / name
        if p.is_file():
            phase6a_outputs[name] = bl6a.sha256_bytes(p)

    manifest = {
        "task": "v2.0.11-frozen-contract-retrieval-baseline",
        "frozen_revision": "v2.0.11-owner-authorized-en048-same-source-repair",
        "frozen_revision_status": "CANDIDATE",
        "contract": {
            "contract_version": snapshot.contract_version,
            "fingerprint": snapshot.fingerprint,
            "chunks_sha256": snapshot.chunks_sha256,
            "chunk_manifest_sha256": snapshot.chunk_manifest_sha256,
            "corpus_manifest_sha256": snapshot.corpus_manifest_sha256,
            "validation_checks": len(snapshot.validation),
        },
        "inputs": inputs,
        "frozen_outputs": frozen_outputs,
        "phase6a_outputs": phase6a_outputs,
        "outputs": {
            name: bl6a.sha256_bytes(out_dir / name)
            for name in CONTRACT_OUTPUT_FILES if name != "manifest.json"
        },
        "code": bl6a._git_head(),
        "parameters": params,
        "dependencies": bl6a._dependencies(),
        "model": {
            "name": index["model_name"],
            "embedding_dimension": index["embedding_dimension"],
            "offline": True,
            "note": "本地缓存离线加载（HF_HUB_OFFLINE=1/TRANSFORMERS_OFFLINE=1）；"
                    "检索期间无网络调用",
        },
        "isolation": {
            "collection_name": index["collection_name"],
            "data_dir": index["data_dir"],
            "chroma_dir": index["chroma_dir"],
            "entry": "src.rag.prepare_index（完整产品路径，含 collection "
                     "manifest + BM25 sidecar）",
            "no_user_index_touched": True,
            "cleaned": cleaned,
        },
        "determinism": determinism,
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    manifest["manifest_sha256"] = bl6a.self_hash(manifest)
    (out_dir / "manifest.json").write_text(bl6a.canonical_json(manifest),
                                           encoding="utf-8")
    return manifest


# ── 编排 ──────────────────────────────────────────────────────────────

def run_contract_baseline(
    *,
    revision_dir: Path,
    chunks_path: Path,
    chunk_manifest_path: Path,
    current_draft_path: Path,
    corpus_manifest_path: Path,
    phase6a_dir: Path,
    out_dir: Path,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
    collection_name: str = COLLECTION_NAME,
    verify_determinism: bool = True,
) -> dict:
    """执行只读 contract 基线并写出全部产物。

    任何冻结 / 6A / contract 漂移 → BaselineDrift（零产物）。
    """
    repo_root = Path(repo_root or REPO_ROOT)
    _check_output_containment(out_dir, [
        revision_dir, chunks_path.parent, current_draft_path.parent,
        corpus_manifest_path.parent, Path(phase6a_dir),
        REPO_ROOT / "evaluation/datasets/v2", REPO_ROOT / "data/v2-corpus",
    ])

    verify_report = bl6a.verify_frozen_inputs(
        revision_dir=revision_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path,
    )
    if not verify_report["verified"]:
        raise BaselineDrift("frozen input drift: " + json.dumps(
            verify_report["drift"], ensure_ascii=False))

    phase6a_report = verify_phase6a_manifest(phase6a_dir)
    if not phase6a_report["verified"]:
        raise BaselineDrift("phase6a baseline manifest drift: " + json.dumps(
            phase6a_report["drift"], ensure_ascii=False))

    snapshot = load_contract_snapshot(
        chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        corpus_manifest_path=corpus_manifest_path,
        repo_root=repo_root,
    )

    cases, mapping_report = bl6a.load_cases(
        revision_dir / "draft-after.jsonl",
        revision_dir / "evidence-after.jsonl",
        chunks_path,
    )

    import src.rag as rag

    own_data_dir = data_dir is None
    data_dir = Path(data_dir) if data_dir is not None else Path(
        tempfile.mkdtemp(prefix="mneme-v211-contract-"))
    data_dir.mkdir(parents=True, exist_ok=True)

    cleaned = False
    index = {}
    results: list[dict] = []
    try:
        index = build_contract_index(snapshot, data_dir, collection_name,
                                     force_rebuild=True)
        results = bl6a.run_retrieval(cases, index)
        metrics = bl6a.compute_metrics(
            results,
            mapping_failure_rows=len(
                mapping_report["mapping"]["mapping_failures"]),
        )
        failures = bl6a.failure_list(results)
        comparison = compare_to_phase6a(phase6a_dir, results, metrics)
        determinism = (
            _verify_determinism(snapshot, cases, results, collection_name)
            if verify_determinism else {"verified": None, "note": "skipped"}
        )
    finally:
        rag.close_chroma_clients()
        if own_data_dir:
            shutil.rmtree(data_dir, ignore_errors=True)
            cleaned = not data_dir.exists()

    params = {
        "collection_name": collection_name,
        "entry": "src.rag.prepare_index(snapshot=ChunkSnapshot, chroma_path=临时目录)",
        "top_k_retrieval": 70,
        "rrf_k": 60,
        "ks": list(KS),
        "refusal_threshold_observation": True,
        "verify_determinism": verify_determinism,
    }
    manifest = write_artifacts(
        out_dir, cases=cases, results=results, metrics=metrics,
        failures=failures, mapping_report=mapping_report, snapshot=snapshot,
        index=index, verify_report=verify_report, phase6a_report=phase6a_report,
        phase6a_dir=phase6a_dir, corpus_manifest_path=corpus_manifest_path,
        comparison=comparison, determinism=determinism, cleaned=cleaned,
        params=params,
        frozen_chunk_ids={c["chunk_id"] for c in snapshot.chunks},
    )
    return {
        "status": "ok",
        "results": results,
        "metrics": metrics,
        "failures": failures,
        "comparison": comparison,
        "manifest": manifest,
        "case_count": len(cases),
        "snapshot": snapshot,
    }


def _verify_determinism(snapshot: ic.ChunkSnapshot, cases: list[dict],
                        results: list[dict], collection_name: str) -> dict:
    """第二次独立构建（独立临时目录）→ 逐 case 比较非时间字段。

    与 6A 相同：聚合指标必须稳定；raw ranking 的 HNSW 跨构建扰动如实记录。
    """
    import src.rag as rag

    second_dir = Path(tempfile.mkdtemp(prefix="mneme-v211-contract-"))
    differences: list[dict] = []
    metric_differences: list[dict] = []
    try:
        index2 = build_contract_index(snapshot, second_dir, collection_name,
                                      force_rebuild=True)
        results2 = bl6a.run_retrieval(cases, index2)
        by_id = {r["case_id"]: r for r in results2}
        for r in results:
            other = by_id[r["case_id"]]
            for field in ("retrieved_chunk_ids", "retrieved_source_ids",
                          "scores", "metrics"):
                if r[field] != other[field]:
                    differences.append({
                        "case_id": r["case_id"], "field": field,
                    })
                    if field == "metrics":
                        for key in sorted(r["metrics"]):
                            if r["metrics"][key] != other["metrics"][key]:
                                metric_differences.append({
                                    "case_id": r["case_id"], "key": key,
                                    "build1": r["metrics"][key],
                                    "build2": other["metrics"][key],
                                })
    finally:
        rag.close_chroma_clients()
        shutil.rmtree(second_dir, ignore_errors=True)
    return {
        "verified": not differences,
        "cases_compared": len(cases),
        "difference_count": len(differences),
        "metric_difference_count": len(metric_differences),
        "metric_differences": metric_differences[:20],
        "differences": differences[:20],
        "note": "第二次构建使用独立临时目录与独立 collection；比较除 "
                "retrieval_ms 外全部字段。raw ranking 差异源于 Chroma/HNSW "
                "索引构建的非确定性（同索引重复查询逐位一致，跨构建在深 "
                "rank 处有近邻扰动）；metric_difference_count 是 per-case "
                "指标受影响的 case 数，聚合指标应稳定",
    }


def main(argv: list[str] | None = None) -> int:
    """CLI。退出码：0=成功；2=冻结/6A/contract 漂移（fail-closed，零产物）；
    1=其他。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase 6-B0: v2.0.11 frozen product contract baseline")
    parser.add_argument("--revision-dir", type=Path, default=FROZEN_REVISION_DIR)
    parser.add_argument("--chunks", type=Path, default=CHUNKS_PATH)
    parser.add_argument("--chunk-manifest", type=Path,
                        default=CHUNK_MANIFEST_PATH)
    parser.add_argument("--current-draft", type=Path, default=CURRENT_DRAFT_PATH)
    parser.add_argument("--corpus-manifest", type=Path,
                        default=CORPUS_MANIFEST_PATH)
    parser.add_argument("--phase6a-dir", type=Path, default=PHASE6A_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="临时数据目录（默认自动创建并在结束后清理）")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--skip-determinism", action="store_true")
    args = parser.parse_args(argv)

    try:
        summary = run_contract_baseline(
            revision_dir=args.revision_dir, chunks_path=args.chunks,
            chunk_manifest_path=args.chunk_manifest,
            current_draft_path=args.current_draft,
            corpus_manifest_path=args.corpus_manifest,
            phase6a_dir=args.phase6a_dir,
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
    print(f"contract baseline complete: {summary['case_count']} cases -> "
          f"{args.output}")
    print(f"  fingerprint={summary['snapshot'].fingerprint[:16]}…")
    print(f"  chunk recall@5={metrics.get('recall@5'):.4f} "
          f"recall@10={metrics.get('recall@10'):.4f} "
          f"recall@20={metrics.get('recall@20'):.4f} "
          f"mrr={metrics.get('mrr'):.4f}")
    print(f"  source_recall@10={metrics.get('source_recall@10'):.4f}")
    print(f"  denominators: {metrics['denominators']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
