"""生成稳定 split 的 locked-config（含 split_fingerprint）。

与历史 lock-production.json 的唯一差异：新增 split_fingerprint（新锁
必填——build_locked_config 已强制）；其余固定字段（dataset/corpus/
index 指纹、arms、reranker_mode=none、alpha=1.0、kg=None、seed=42、
arm_selector_policy={"standard": 3}、budgets、模型标识）逐字段交叉
校验与旧锁一致后写入。

不调用 LLM/API；不改写任何历史 results。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from evaluation.compare import compute_split_fingerprint, group_aware_split
from evaluation.locked_config import (
    build_locked_config,
    collect_runtime_budgets,
    collect_runtime_models,
    load_locked_config,
    save_locked_config,
    validate_locked_config,
)
from evaluation.schema import load_dataset

OUT = Path(__file__).resolve().parent
OLD_LOCK = ROOT / "results/graph-gate/production-baseline-20260804T2220/lock-production.json"
DATASET = ROOT / "evaluation/datasets/v1.jsonl"

old = json.loads(OLD_LOCK.read_text(encoding="utf-8"))
cases = load_dataset(DATASET)
dev, holdout = group_aware_split(cases, seed=42)
split_fp = compute_split_fingerprint(dev, holdout)
models = collect_runtime_models()

cfg = build_locked_config(
    locked_alpha=1.0,
    dataset_name="v1.jsonl",
    dataset_sha256=old["dataset_sha256"],
    corpus_sha256=old["corpus_sha256"],
    seed=42,
    arms=["standard"],
    embedding_model=models["embedding_model"],
    llm_model=models["llm_model"],
    reranker_mode="none",
    reranker_model=models["reranker_model"],
    prompt_id=models["prompt_id"],
    budgets=collect_runtime_budgets(),
    index_sha256=old["index_sha256"],
    kg_sha256=None,  # 无 graph 臂 → not-applicable
    split_fingerprint=split_fp,
    arm_selector_policy={"standard": 3},
)

# 交叉校验：固定字段必须与旧锁一致（除新增 split_fingerprint 外）
fixed_fields = ("locked_alpha", "dataset", "dataset_sha256", "corpus_sha256",
                "index_sha256", "kg_sha256", "embedding_model", "llm_model",
                "reranker_mode", "reranker_model", "prompt_id", "arms",
                "seed", "budgets", "arm_selector_policy")
for f in fixed_fields:
    if cfg[f] != old[f]:
        raise SystemExit(f"field drift vs old lock: {f}: "
                         f"old={old[f]!r} new={cfg[f]!r}")
if old.get("split_fingerprint") is not None:
    raise SystemExit("old lock unexpectedly already has split_fingerprint")
print("✓ fixed fields identical to historical lock-production.json")
print(f"✓ split_fingerprint={split_fp} (dev={len(dev)}, holdout={len(holdout)})")

# roundtrip：load + validate（预检参数）必须放行
path = OUT / "lock-production-stable.json"
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
    split_fingerprint=split_fp,
    arm_selector_policy=cfg["arm_selector_policy"],
)
if diffs:
    raise SystemExit(f"roundtrip validation failed: {diffs}")
print(f"✓ roundtrip load+validate PASS → {path.relative_to(ROOT)}")
