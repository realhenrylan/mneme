"""生成拒答策略消融的新 locked-config（A=standard / B=standard-calibrated）。

与稳定 split 锁（lock-production-stable.json）固定字段一致（dataset/
corpus/index SHA、reranker=none、alpha=1.0、kg=None、seed=42、
arm_selector_policy、budgets、模型标识、split_fingerprint），差异仅：
- arms=[standard, standard-calibrated]（新增 B 臂）；
- refusal_policy={"standard": "baseline", "standard-calibrated": "evidence_calibrated"}；
- effective_prompt_ids=逐臂「实际 system prompt + PROMPT_TEMPLATE」SHA-256。

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
    compute_effective_prompt_ids,
    default_refusal_policy_by_arm,
    save_locked_config,
)
from evaluation.schema import load_dataset

OUT = Path(__file__).resolve().parent
STABLE_LOCK = ROOT / "results/graph-gate/stable-split-rebuild-20260804T234043/lock-production-stable.json"
DATASET = ROOT / "evaluation/datasets/v1.jsonl"

old = json.loads(STABLE_LOCK.read_text(encoding="utf-8"))
cases = load_dataset(DATASET)
dev, holdout = group_aware_split(cases, seed=42)
split_fp = compute_split_fingerprint(dev, holdout)
models = collect_runtime_models()
arms = ["standard", "standard-calibrated"]
refusal_policy = default_refusal_policy_by_arm(arms)

cfg = build_locked_config(
    locked_alpha=1.0,
    dataset_name="v1.jsonl",
    dataset_sha256=old["dataset_sha256"],
    corpus_sha256=old["corpus_sha256"],
    seed=42,
    arms=arms,
    embedding_model=models["embedding_model"],
    llm_model=models["llm_model"],
    reranker_mode="none",
    reranker_model=models["reranker_model"],
    prompt_id=models["prompt_id"],
    budgets=collect_runtime_budgets(),
    index_sha256=old["index_sha256"],
    kg_sha256=None,  # 无 graph 臂 → not-applicable
    split_fingerprint=split_fp,
    arm_selector_policy={a: 3 for a in arms},
    refusal_policy=refusal_policy,
    effective_prompt_ids=compute_effective_prompt_ids(refusal_policy),
)

# 交叉校验：固定字段必须与稳定 split 锁一致
for key in ("dataset", "dataset_sha256", "corpus_sha256", "index_sha256",
            "seed", "locked_alpha", "prompt_id", "embedding_model",
            "llm_model", "reranker_mode", "reranker_model", "kg_sha256",
            "split_fingerprint"):
    if cfg[key] != old[key]:
        print(f"!! field {key} differs from stable lock: "
              f"{cfg[key]} vs {old[key]}")
        sys.exit(1)
assert cfg["split_fingerprint"] == old["split_fingerprint"]
assert cfg["split_fingerprint"] == split_fp
print(f"split_fingerprint locked: {split_fp} (matches stable lock)")

path = OUT / "lock-refusal-ablation.json"
save_locked_config(cfg, path)
print(f"written: {path}")
print(f"  arms={cfg['arms']}")
print(f"  refusal_policy={cfg['refusal_policy']}")
print(f"  effective_prompt_ids={cfg['effective_prompt_ids']}")
