"""拒答策略消融受控评测预检（fail-closed）。

校验（任一失败 → 非零退出）：
1. 锁定配置：load + validate 全字段（含 refusal_policy per-arm 映射与
   effective_prompt_ids 逐臂提示指纹——策略正文/策略名/臂映射任一漂移
   都在任何索引/LLM 工作前拒绝）；
2. 稳定 split：group_aware_split(seed=42) 指纹 == lock.split_fingerprint
   （不依赖 PYTHONHASHSEED）；
3. 双 overlay：dataset/GT SHA 一致、case refs 有效、双 split truth gate；
4. 索引指纹后验：缓存索引快照 == lock.index_sha256；
5. 运行时环境：API_KEY/BASE_URL 存在（不打印值）、RAG_RERANKER=none、
   LLM_MODEL 记录；
6. immutability 快照：历史 results 与 decision-report.md 的 SHA 快照
   （结束时复验，证明未改写）。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent
REBUILD = ROOT / "results/graph-gate/stable-split-rebuild-20260804T234043"
LOCK = OUT / "lock-refusal-ablation.json"
DATASET = ROOT / "evaluation/datasets/v1.jsonl"
CORPUS = ROOT / "test_texts"
DEV_OVERLAY = REBUILD / "reviewed-production-dev/reviewed-truth-overlay.json"
HOLDOUT_OVERLAY = REBUILD / "reviewed-production-holdout/reviewed-truth-overlay.json"
DEV_GT = REBUILD / "ground-truth-map-dev.json"
HOLDOUT_GT = REBUILD / "ground-truth-map-holdout.json"
SPLIT_MANIFEST = REBUILD / "split-manifest.json"

ARMS = ["standard", "standard-calibrated"]

failures: list[str] = []
notes: list[str] = []


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ── 1. 锁定配置（索引/LLM 前） ────────────────────────────────────────
from evaluation.compare import (
    _compute_corpus_hash,
    _compute_dataset_hash,
    _index_snapshot_sha256,
    _normalize_text,
    apply_reviewed_truth_overlay,
    compute_split_fingerprint,
    enforce_truth_gate,
    group_aware_split,
    load_ground_truth_map,
    load_reviewed_truth_overlay,
)
from evaluation.locked_config import (
    LockedConfigError,
    collect_runtime_budgets,
    collect_runtime_models,
    compute_effective_prompt_ids,
    default_refusal_policy_by_arm,
    load_locked_config,
    validate_locked_config,
)
from evaluation.schema import load_dataset
from src.rag import prepare_index

lock = load_locked_config(LOCK)
models = collect_runtime_models()
cases = load_dataset(DATASET)
source_files: set[str] = set()
for c in cases:
    source_files.update(c.relevant_source_ids or [])

ds_hash = _compute_dataset_hash(DATASET)
corpus_hash = _compute_corpus_hash(CORPUS, sorted(source_files))

refusal_policy = default_refusal_policy_by_arm(ARMS)
diffs = validate_locked_config(
    lock,
    dataset_name=DATASET.name,
    dataset_sha256=ds_hash,
    corpus_sha256=corpus_hash,
    seed=42,
    arms=ARMS,
    embedding_model=models["embedding_model"],
    llm_model=models["llm_model"],
    reranker_mode=models["reranker_mode"],
    reranker_model=models["reranker_model"],
    prompt_id=models["prompt_id"],
    budgets=collect_runtime_budgets(),
    arm_selector_policy={a: 3 for a in ARMS},
    refusal_policy=refusal_policy,
    effective_prompt_ids=compute_effective_prompt_ids(refusal_policy),
)
if diffs:
    failures.append(f"locked config mismatch: {diffs}")
else:
    notes.append("locked config verified (含 refusal_policy per-arm 映射与 "
                 "effective_prompt_ids 逐臂提示指纹)")

# ── 2. 稳定 split 指纹 ───────────────────────────────────────────────
dev, holdout = group_aware_split(cases, seed=42)
split_fp = compute_split_fingerprint(dev, holdout)
fp_diffs = validate_locked_config(lock, split_fingerprint=split_fp)
if fp_diffs:
    failures.append(f"split fingerprint mismatch: {fp_diffs}")
else:
    notes.append(f"split fingerprint={split_fp} "
                 f"(dev={len(dev)}, holdout={len(holdout)}), 与 lock 一致")
manifest = json.loads(SPLIT_MANIFEST.read_text(encoding="utf-8"))
if manifest["dev_count"] != len(dev) or manifest["holdout_count"] != len(holdout):
    failures.append("split manifest counts mismatch vs current split")

# ── 3. overlay + truth gate（双 split）───────────────────────────────
for name, ov_path, gt_path in (
    ("dev", DEV_OVERLAY, DEV_GT),
    ("holdout", HOLDOUT_OVERLAY, HOLDOUT_GT),
):
    try:
        overlay = load_reviewed_truth_overlay(ov_path)
    except ValueError as exc:
        failures.append(f"{name}: overlay load failed: {exc}")
        continue
    if overlay["dataset_sha256"] != ds_hash:
        failures.append(f"{name}: overlay dataset_sha256 mismatch (stale)")
    if sha256_file(gt_path) != overlay["ground_truth_sha256"]:
        failures.append(f"{name}: overlay ground_truth_sha256 != GT map")
    case_ids = {c.id for c in cases}
    unknown = sorted({e["case_id"] for e in overlay["entries"]} - case_ids)
    if unknown:
        failures.append(f"{name}: overlay entries unknown case_ids {unknown}")
    dataset_norms = {
        c.id: [_normalize_text(rc.chunk_text_snippet) for rc in c.relevant_chunks]
        for c in cases
    }
    missing_ann = sorted({
        e["case_id"] for e in overlay["entries"]
        if e["normalized_snippet"] not in dataset_norms.get(e["case_id"], [])
    })
    if missing_ann:
        failures.append(f"{name}: overlay entries annotations absent from "
                        f"dataset: {missing_ann}")
    entries = load_ground_truth_map(gt_path)
    try:
        updated, source_only = apply_reviewed_truth_overlay(entries, overlay)
    except ValueError as exc:
        failures.append(f"{name}: overlay application failed: {exc}")
        continue
    split_ids = set(manifest[f"{name}_case_ids"])
    active = [c for c in cases if c.id in split_ids]
    has_truth = {c.id: False for c in active}
    for e in updated:
        if (e.match_method == "exact"
                or (e.match_method in ("overlap", "parent")
                    and e.reviewer_status == "confirmed")):
            has_truth[e.case_id] = True
    gate_errors = enforce_truth_gate(active, has_truth, overlay, source_only)
    if gate_errors:
        failures.append(f"{name}: truth gate FAILED: {gate_errors}")
    else:
        notes.append(f"{name}: overlay consumed ({len(overlay['entries'])} "
                     f"entries), truth gate PASS, "
                     f"source-only={len(source_only)}")

# ── 4. 索引指纹后验 ──────────────────────────────────────────────────
file_paths = []
for source_id in sorted(source_files):
    cand = CORPUS / source_id
    if cand.exists():
        file_paths.append(str(cand))
    else:
        for f in CORPUS.iterdir():
            if f.name.lower() == source_id.lower():
                file_paths.append(str(f))
                break
model, collection, bm25, all_docs, all_metadatas = prepare_index(
    file_paths, "eval-autorun-lock", force_rebuild=False,
)
idx_sha = _index_snapshot_sha256(collection)
if idx_sha != lock["index_sha256"]:
    failures.append(f"index_sha256: lock={lock['index_sha256'][:16]}... "
                    f"run={idx_sha[:16]}...")
else:
    notes.append(f"index_sha256={idx_sha[:16]}... ({len(all_docs)} chunks, "
                 f"与 lock 一致)")

# ── 5. 运行时环境（存在性检查，绝不打印值） ──────────────────────────
env_checks = {
    "API_KEY": bool(os.getenv("API_KEY")),
    "BASE_URL": bool(os.getenv("BASE_URL")),
}
for name, ok in env_checks.items():
    if not ok:
        failures.append(f"env {name}: missing or empty")
    else:
        notes.append(f"env {name}: present (value redacted)")
reranker_env = os.getenv("RAG_RERANKER", "(unset → none)")
if reranker_env != "none":
    failures.append(f"RAG_RERANKER={reranker_env!r} != none")
else:
    notes.append("RAG_RERANKER=none（生产基线）")
llm_model_env = os.getenv("LLM_MODEL", "deepseek-chat")
notes.append(f"LLM_MODEL={llm_model_env!r}")
notes.append(f"PYTHONHASHSEED={os.getenv('PYTHONHASHSEED', '(unset)')} "
             "(仅记录；稳定 split 不依赖)")

# ── 6. immutability 快照 ─────────────────────────────────────────────
immutable_files = [
    ROOT / "results/graph-gate/decision-report.md",
    REBUILD / "split-manifest.json",
    REBUILD / "lock-production-stable.json",
    REBUILD / "reviewed-production-dev/reviewed-truth-overlay.json",
    REBUILD / "reviewed-production-holdout/reviewed-truth-overlay.json",
    REBUILD / "ground-truth-map-dev.json",
    REBUILD / "ground-truth-map-holdout.json",
    ROOT / "results/graph-gate/production-baseline-20260804T2220/candidate-report.md",
    ROOT / "results/graph-gate/production-baseline-20260804T2220/lock-production.json",
    ROOT / "results/graph-gate/production-baseline-20260804T2220/dev-full/run-manifest.json",
    ROOT / "results/graph-gate/production-baseline-20260804T2220/holdout-full/run-manifest.json",
    ROOT / "results/graph-gate/production-baseline-20260804T2220/dev-full/summary.json",
    ROOT / "results/graph-gate/production-baseline-20260804T2220/holdout-full/summary.json",
    ROOT / "results/graph-gate/production-baseline-stable-20260805T084256/precheck-snapshot.json",
    ROOT / "results/graph-gate/production-baseline-stable-20260805T084256/candidate-report-data.json",
    ROOT / "results/graph-gate/production-baseline-stable-20260805T084256/dev-full/generation-cases.jsonl",
    ROOT / "results/graph-gate/production-baseline-stable-20260805T084256/holdout-full/generation-cases.jsonl",
    ROOT / "results/graph-gate/refusal-guardrail-audit-20260805T113849/manifest.json",
    ROOT / "results/graph-gate/refusal-guardrail-audit-20260805T113849/refusal-review-pack.jsonl",
    ROOT / "results/graph-gate/refusal-guardrail-audit-20260805T113849/guardrail-sensitivity.json",
]
snapshot = {}
for f in immutable_files:
    if f.exists():
        snapshot[str(f.relative_to(ROOT))] = sha256_file(f)
    else:
        failures.append(f"immutable file missing: {f.relative_to(ROOT)}")

(OUT / "precheck-snapshot.json").write_text(
    json.dumps({
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "lock_sha256": sha256_file(LOCK),
        "dataset_sha256": ds_hash,
        "corpus_sha256": corpus_hash,
        "index_sha256": idx_sha,
        "split_fingerprint": split_fp,
        "arms": ARMS,
        "refusal_policy": lock["refusal_policy"],
        "effective_prompt_ids": lock["effective_prompt_ids"],
        "immutability_snapshot": snapshot,
    }, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print("=" * 70)
print("PRECHECK RESULTS")
print("=" * 70)
for n in notes:
    print("  [ok]", n)
for f_ in failures:
    print("  [FAIL]", f_)
if failures:
    print("\nPRECHECK FAILED:", len(failures), "blocker(s)")
    sys.exit(1)
print("\nPRECHECK PASS")
