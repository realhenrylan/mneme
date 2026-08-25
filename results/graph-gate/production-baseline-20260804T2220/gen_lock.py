"""生成生产基线（production baseline）的 locked-config。

- arms=[standard]（生产语义臂），RAG_RERANKER=none、alpha=1.0、
  Graph 禁用（无 graph-rerank 臂 → kg_sha256=None）。
- arm_selector_policy={"standard": 3}（生产默认每源上限 3，
  ARM_SELECTOR_MAX_PER_SOURCE 映射）。
- dataset_sha256/corpus_sha256 本地计算（当前 dataset 已人工补标
  meta-* chunk 真值，dataset_sha256 与旧 auto-run 锁不同属预期）；
- index_sha256 沿用旧锁值（corpus 未变、索引未重建，precheck 验证）；
- 交叉校验：corpus/index/prompt/budgets/seed/alpha 必须与旧锁一致；
  load + validate roundtrip 放行。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from evaluation.compare import _compute_corpus_hash, _compute_dataset_hash
from evaluation.locked_config import (
    build_locked_config,
    collect_runtime_budgets,
    collect_runtime_models,
    load_locked_config,
    save_locked_config,
    validate_locked_config,
)

OUT = Path(__file__).resolve().parent
OLD_LOCK = ROOT / "results/graph-gate/auto-run-20260804T121410/lock-generation/locked-config.json"
DATASET = ROOT / "evaluation/datasets/v1.jsonl"
CORPUS = ROOT / "test_texts"

old = json.loads(OLD_LOCK.read_text(encoding="utf-8"))
models = collect_runtime_models()
budgets = collect_runtime_budgets()

cases = [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines()]
source_files: set[str] = set()
for c in cases:
    source_files.update(c.get("relevant_source_ids") or [])

ds_hash = _compute_dataset_hash(DATASET)
corpus_hash = _compute_corpus_hash(CORPUS, sorted(source_files))

cfg = build_locked_config(
    locked_alpha=1.0,
    dataset_name="v1.jsonl",
    dataset_sha256=ds_hash,
    corpus_sha256=corpus_hash,
    seed=42,
    arms=["standard"],
    embedding_model=models["embedding_model"],
    llm_model=models["llm_model"],
    reranker_mode="none",
    reranker_model=models["reranker_model"],
    prompt_id=models["prompt_id"],
    budgets=budgets,
    index_sha256=old["index_sha256"],
    kg_sha256=None,  # 无 graph 臂 → KG 指纹 not-applicable
    arm_selector_policy={"standard": 3},
)

# 交叉校验：dataset_sha256 允许不同（dataset 已补标更新）；
# corpus/index/prompt/budgets/seed/alpha 必须与旧锁一致。
fixed_fields = ("corpus_sha256", "index_sha256", "embedding_model", "llm_model",
                "prompt_id", "seed", "locked_alpha")
for f in fixed_fields:
    if cfg[f] != old[f]:
        raise SystemExit(f"fixed field mismatch: {f} lock={old[f]!r} new={cfg[f]!r}")
if cfg["dataset_sha256"] == old["dataset_sha256"]:
    raise SystemExit(
        "dataset_sha256 unchanged vs old lock — dataset was expected to be "
        "re-annotated (meta-* chunk truth); refusing stale lock")

path = OUT / "lock-production.json"
save_locked_config(cfg, path)
loaded = load_locked_config(path)
diffs = validate_locked_config(
    loaded,
    dataset_name=cfg["dataset"],
    dataset_sha256=cfg["dataset_sha256"],
    corpus_sha256=cfg["corpus_sha256"],
    seed=cfg["seed"],
    arms=cfg["arms"],
    embedding_model=models["embedding_model"],
    llm_model=models["llm_model"],
    reranker_mode=cfg["reranker_mode"],
    reranker_model=models["reranker_model"],
    prompt_id=models["prompt_id"],
    budgets=collect_runtime_budgets(),
    arm_selector_policy={"standard": 3},
)
if diffs:
    raise SystemExit(f"roundtrip validation failed: {diffs}")
print(f"✓ lock-production.json written: arms={cfg['arms']} "
      f"arm_selector_policy={cfg['arm_selector_policy']} "
      f"reranker_mode={cfg['reranker_mode']} alpha=1.0")
print(f"  dataset_sha256={ds_hash}")
print(f"  corpus_sha256={corpus_hash} ({len(source_files)} source files)")
print(f"  index_sha256={old['index_sha256']} (inherited from old lock; "
      f"precheck verifies)")
