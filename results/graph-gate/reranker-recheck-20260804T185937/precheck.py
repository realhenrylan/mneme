"""reranker-recheck 预检：输入指纹与运行时环境校验（fail-closed）。

- 校验 dataset / corpus / overlay / prompt_id / budgets 与 locked-config 一致
- 校验模型与 reranker 环境（不打印任何 secret）
- 校验索引指纹（加载缓存索引，计算 snapshot 与锁定值比对）
- 记录历史产物 immutability 快照（结束时复验，证明未改写）
- 任一失败 → 非零退出，明确输出阻断项
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
LOCK = ROOT / "results/graph-gate/auto-run-20260804T121410/lock-generation/locked-config.json"
OLD_RUN = ROOT / "results/graph-gate/auto-run-20260804T121410"
DATASET = ROOT / "evaluation/datasets/v1.jsonl"
CORPUS = ROOT / "test_texts"
OVERLAY = OLD_RUN / "auto-reviewed-truth/reviewed-truth-overlay.json"
OUT = Path(__file__).resolve().parent

failures: list[str] = []
notes: list[str] = []


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


lock = json.loads(LOCK.read_text(encoding="utf-8"))

# ── 1. dataset / corpus ──────────────────────────────────────────────
from evaluation.compare import _compute_corpus_hash, _compute_dataset_hash
import json as _json

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
notes.append(f"dataset_sha256={ds_hash}")
notes.append(f"corpus_sha256={corpus_hash} ({len(source_files)} source files)")

# ── 2. overlay 一致性 ────────────────────────────────────────────────
ov = json.loads(OVERLAY.read_text(encoding="utf-8"))
if ov["dataset_sha256"] != ds_hash:
    failures.append(
        f"overlay dataset_sha256={ov['dataset_sha256']} != dataset {ds_hash}")
notes.append(f"overlay: {len(ov['entries'])} entries, "
             f"{len(ov['case_relevance_levels'])} case levels")

# ── 3. 运行时模型 / prompt / budgets vs lock ─────────────────────────
from evaluation.locked_config import collect_runtime_budgets, collect_runtime_models
models = collect_runtime_models()

# 实验变量校验：当前 env 的 reranker_mode 必须恰好命中 A/B 两个 recheck
# lock 之一（其余固定字段两 lock 均与原始 lock 一致，已在 gen_locks 校验）。
recheck_locks = {
    fname: json.loads((OUT / fname).read_text(encoding="utf-8"))
    for fname in ("lock-A.json", "lock-B.json")
}
matched = [name for name, lk in recheck_locks.items()
           if lk["reranker_mode"] == models["reranker_mode"]]
if len(matched) != 1:
    failures.append(
        f"reranker_mode={models['reranker_mode']!r} matches {len(matched)} "
        f"recheck locks (expected exactly 1)")
else:
    notes.append(f"recheck lock matched: {matched[0]} "
                 f"(reranker_mode={models['reranker_mode']!r})")
for field in ("embedding_model", "llm_model", "reranker_model", "prompt_id"):
    lk = recheck_locks[matched[0]] if len(matched) == 1 else recheck_locks["lock-A.json"]
    if models[field] != lk[field]:
        failures.append(f"{field}: lock={lk[field]!r} run={models[field]!r}")
budgets = collect_runtime_budgets()
for key, lv in recheck_locks["lock-A.json"]["budgets"].items():
    rv = budgets.get(key)
    if lv != rv:
        failures.append(f"budgets.{key}: lock={lv!r} run={rv!r}")

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
if llm_model_env != "deepseek-chat":
    notes.append(f"LLM_MODEL env override: {llm_model_env!r}")
else:
    notes.append("LLM_MODEL: default deepseek-chat")
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
    OLD_RUN / "reranker-fix-implementation-report.md",
    OLD_RUN / "reranker-regression-diagnosis.md",
    OLD_RUN / "alpha-selection.json",
    OLD_RUN / "dev-full/run-manifest.json",
    OLD_RUN / "dev-full/summary.json",
    OLD_RUN / "dev-full/generation-summary.json",
    OLD_RUN / "holdout-full/run-manifest.json",
    OLD_RUN / "lock-generation/locked-config.json",
    OLD_RUN / "auto-reviewed-truth/reviewed-truth-overlay.json",
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
        "locked_config_sha256": sha256_text(json.dumps(lock, sort_keys=True)),
        "dataset_sha256": ds_hash,
        "corpus_sha256": corpus_hash,
        "index_sha256": idx_sha,
        "env": env_checks,
        "llm_model": llm_model_env,
        "notes": notes,
        "immutability_snapshot": snapshot,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

print("=== PRE-CHECK ===")
for n in notes:
    print(f"  ✓ {n}")
if failures:
    print("\n  ✗ BLOCKERS:")
    for f_ in failures:
        print(f"    - {f_}")
    print("\nRESULT: FAIL — refusing to continue")
    sys.exit(1)
print("\nRESULT: PASS — all inputs verified against locked config")
