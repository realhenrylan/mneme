"""生成 reranker-recheck 的 A/B 两个 locked-config（仅差异：arms + reranker_mode）。

- A lock：arms=[standard]，reranker_mode=none（RAG_RERANKER=none）
- B lock：arms=[standard-rerank]，reranker_mode=cross-encoder
- 其余字段（dataset/corpus/index 指纹、prompt_id、budgets、seed、alpha=1.0）
  与原 auto-run 锁定配置逐字段一致；kg_sha256=None（无 graph 臂，not-applicable）。
- 全部输入来自 precheck 已验证的指纹，无任何 LLM/索引调用。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from evaluation.locked_config import (
    build_locked_config,
    collect_runtime_budgets,
    collect_runtime_models,
    save_locked_config,
)

OUT = Path(__file__).resolve().parent
OLD_LOCK = ROOT / "results/graph-gate/auto-run-20260804T121410/lock-generation/locked-config.json"
old = json.loads(OLD_LOCK.read_text(encoding="utf-8"))
models = collect_runtime_models()
budgets = collect_runtime_budgets()

common = dict(
    locked_alpha=1.0,
    dataset_name="v1.jsonl",
    dataset_sha256=old["dataset_sha256"],
    corpus_sha256=old["corpus_sha256"],
    seed=42,
    embedding_model=models["embedding_model"],
    llm_model=models["llm_model"],
    reranker_model=models["reranker_model"],
    prompt_id=models["prompt_id"],
    budgets=budgets,
    index_sha256=old["index_sha256"],
    kg_sha256=None,  # 无 graph 臂 → KG 指纹 not-applicable
)

locks = {
    "lock-A.json": dict(common, arms=["standard"], reranker_mode="none"),
    "lock-B.json": dict(common, arms=["standard-rerank"], reranker_mode="cross-encoder"),
    "lock-AB.json": dict(common, arms=["standard", "standard-rerank"],
                         reranker_mode="cross-encoder"),
}

# 交叉校验：固定字段必须与原 lock 一致（除 arms/reranker_mode/kg 外）
fixed_fields = ("dataset", "dataset_sha256", "corpus_sha256", "index_sha256",
                "embedding_model", "llm_model", "prompt_id", "seed", "locked_alpha")
for fname, cfg in locks.items():
    cfg = build_locked_config(**cfg)
    for f in fixed_fields:
        if cfg[f] != old[f]:
            raise SystemExit(f"{fname}: {f} lock={old[f]!r} new={cfg[f]!r}")
    if cfg["budgets"] != old["budgets"]:
        raise SystemExit(f"{fname}: budgets differ from original lock")
    save_locked_config(cfg, OUT / fname)
    print(f"✓ {fname} written (arms={cfg['arms']}, reranker_mode={cfg['reranker_mode']}, "
          f"kg_sha256={cfg['kg_sha256']})")
print("✓ Both recheck locks match original lock on all fixed fields")
