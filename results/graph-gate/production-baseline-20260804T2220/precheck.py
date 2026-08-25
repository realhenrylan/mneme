"""生产基线评测预检：输入指纹与运行时环境校验（fail-closed）。

- 校验当前 dataset（已人工补标）与 corpus 指纹；corpus/index 必须与
  旧 auto-run 锁一致（语料未变、索引未重建）；dataset_sha256 允许不同
  （补标更新，属预期差异）。
- 校验运行时模型/reranker（必须 RAG_RERANKER=none）/prompt/budgets
  与 lock-production.json 一致。
- 校验索引指纹（加载缓存索引，计算 snapshot 与锁定值比对，只读）。
- overlay 若已生成则校验 dataset_sha256 一致性（review_apply 后）；
  未生成时注明 pending（review_apply fail-closed 校验已在生成时完成）。
- 记录历史产物 immutability 快照（结束时复验，证明未改写）。
- 任一失败 → 非零退出，明确输出阻断项。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
LOCK = ROOT / "results/graph-gate/production-baseline-20260804T2220/lock-production.json"
OLD_RUN = ROOT / "results/graph-gate/auto-run-20260804T121410"
DATASET = ROOT / "evaluation/datasets/v1.jsonl"
CORPUS = ROOT / "test_texts"
OVERLAY_DEV = ROOT / "results/graph-gate/production-baseline-20260804T2220/reviewed-production-dev/reviewed-truth-overlay.json"
OVERLAY_HOLDOUT = ROOT / "results/graph-gate/production-baseline-20260804T2220/reviewed-production-holdout/reviewed-truth-overlay.json"
OUT = Path(__file__).resolve().parent

failures: list[str] = []
notes: list[str] = []


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


old = json.loads((OLD_RUN / "lock-generation/locked-config.json").read_text(encoding="utf-8"))
lock = json.loads(LOCK.read_text(encoding="utf-8"))

# ── 1. dataset / corpus ──────────────────────────────────────────────
from evaluation.compare import _compute_corpus_hash, _compute_dataset_hash

cases = [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines()]
source_files: set[str] = set()
for c in cases:
    source_files.update(c.get("relevant_source_ids") or [])

ds_hash = _compute_dataset_hash(DATASET)
corpus_hash = _compute_corpus_hash(CORPUS, sorted(source_files))
if ds_hash != lock["dataset_sha256"]:
    failures.append(f"dataset_sha256: lock={lock['dataset_sha256']} run={ds_hash}")
if corpus_hash != lock["corpus_sha256"]:
    failures.append(f"corpus_sha256: lock={lock['corpus_sha256']} run={corpus_hash}")
if corpus_hash != old["corpus_sha256"]:
    failures.append(
        f"corpus_sha256 differs from old lock: old={old['corpus_sha256']} "
        f"run={corpus_hash} (corpus must be unchanged)")
else:
    notes.append(f"corpus unchanged vs old lock: {corpus_hash} "
                 f"({len(source_files)} source files)")
if ds_hash == old["dataset_sha256"]:
    notes.append(f"WARNING: dataset_sha256 equals old lock ({ds_hash}) — "
                 f"expected re-annotated dataset")
else:
    notes.append(f"dataset_sha256={ds_hash} (updated vs old lock, expected)")

# ── 2. overlay 一致性（dev + holdout 两个 overlay） ──────────────────
for name, ov_path in (("dev", OVERLAY_DEV), ("holdout", OVERLAY_HOLDOUT)):
    if ov_path.exists():
        ov = json.loads(ov_path.read_text(encoding="utf-8"))
        if ov["dataset_sha256"] != ds_hash:
            failures.append(
                f"overlay[{name}] dataset_sha256={ov['dataset_sha256']} "
                f"!= dataset {ds_hash}")
        notes.append(f"overlay[{name}]: {len(ov['entries'])} entries, "
                     f"{len(ov['case_relevance_levels'])} case levels "
                     f"(dataset_sha256 ok)")
    else:
        notes.append(f"overlay[{name}]: MISSING ({ov_path.relative_to(ROOT)})")

# ── 3. 运行时模型 / prompt / budgets vs lock-production ──────────────
from evaluation.locked_config import collect_runtime_budgets, collect_runtime_models
models = collect_runtime_models()
if models["reranker_mode"] != "none":
    failures.append(
        f"reranker_mode={models['reranker_mode']!r} != 'none' "
        "(production baseline is no-reranker)")
else:
    notes.append("reranker_mode=none (production baseline)")
if lock["reranker_mode"] != "none":
    failures.append(f"lock reranker_mode={lock['reranker_mode']!r} != none")
for field in ("embedding_model", "llm_model", "reranker_model", "prompt_id"):
    if models[field] != lock[field]:
        failures.append(f"{field}: lock={lock[field]!r} run={models[field]!r}")
budgets = collect_runtime_budgets()
for key, lv in lock["budgets"].items():
    rv = budgets.get(key)
    if lv != rv:
        failures.append(f"budgets.{key}: lock={lv!r} run={rv!r}")
notes.append(
    f"source_diversity_max_per_source (global default)="
    f"{budgets.get('source_diversity_max_per_source')!r} (expect 3)")

# ── 4. 环境变量（存在性检查，绝不打印值） ────────────────────────────
env_checks = {
    "API_KEY": os.getenv("API_KEY") is not None and len(os.getenv("API_KEY", "")) > 0,
    "BASE_URL": os.getenv("BASE_URL") is not None and len(os.getenv("BASE_URL", "")) > 0,
}
for name, ok in env_checks.items():
    if not ok:
        failures.append(f"env {name}: missing or empty")
    else:
        notes.append(f"env {name}: present (value redacted)")
llm_model_env = os.getenv("LLM_MODEL", "deepseek-chat")
notes.append(f"LLM_MODEL: {llm_model_env!r}")
notes.append(f"RAG_RERANKER env: {os.getenv('RAG_RERANKER', '(unset → none)')!r}")

# ── 5. 索引指纹（加载缓存索引，只读） ─────────────────────────────────
from src.rag import prepare_index, index_fingerprint
from evaluation.compare import _index_snapshot_sha256

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
    file_paths, "eval-autorun-lock", force_rebuild=False)
idx_sha = _index_snapshot_sha256(collection)
if idx_sha != lock["index_sha256"]:
    failures.append(f"index_sha256: lock={lock['index_sha256']} run={idx_sha}")
else:
    notes.append(f"index_sha256={idx_sha} ({len(all_docs)} chunks)")
    fp = index_fingerprint(collection.get()["ids"], all_metadatas)
    notes.append(f"index_fingerprint={fp}")

# ── 6. immutability 快照（结束时复验） ────────────────────────────────
immutable_files = [
    ROOT / "results/graph-gate/decision-report.md",
    OLD_RUN / "automated-decision-report.md",
    OLD_RUN / "dev-full/run-manifest.json",
    OLD_RUN / "dev-full/summary.json",
    OLD_RUN / "dev-full/generation-summary.json",
    OLD_RUN / "holdout-full/run-manifest.json",
    OLD_RUN / "lock-generation/locked-config.json",
    OLD_RUN / "auto-reviewed-truth/reviewed-truth-overlay.json",
    ROOT / "results/graph-gate/reranker-recheck-20260804T185937/reranker-recheck-decision-report.md",
    ROOT / "results/graph-gate/selector-ablation-20260804T202048/selector-ablation-decision-report.md",
    ROOT / "results/graph-gate/citation-denominator-reconciliation-20260804T210032/reconciliation-summary.json",
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
        "lock_production_sha256": sha256_text(json.dumps(lock, sort_keys=True)),
        "dataset_sha256": ds_hash,
        "corpus_sha256": corpus_hash,
        "index_sha256": idx_sha,
        "env": env_checks,
        "llm_model": llm_model_env,
        "notes": notes,
        "immutability_snapshot": snapshot,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

print("=== PRE-CHECK (production baseline) ===")
for n in notes:
    print(f"  ✓ {n}")
if failures:
    print("\n  ✗ BLOCKERS:")
    for f_ in failures:
        print(f"    - {f_}")
    print("\nRESULT: FAIL — refusing to continue")
    sys.exit(1)
print("\nRESULT: PASS — all inputs verified against locked config")
