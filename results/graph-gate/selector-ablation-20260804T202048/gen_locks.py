"""生成 selector 消融的 locked-config（仅差异：arms + arm_selector_policy）。

- lock-S0.json   : arms=[selector-unlimited]，policy={"selector-unlimited": null}
- lock-S3.json   : arms=[selector-cap3]，policy={"selector-cap3": 3}
- lock-S0S3.json : arms=[selector-unlimited, selector-cap3]（正式运行用）
- 其余字段（dataset/corpus/index 指纹、prompt_id、budgets、seed、alpha=1.0）
  与原 auto-run 锁定配置逐字段一致；kg_sha256=None（无 graph 臂）。
- reranker_mode=none（双臂均为无 reranker 基线；实验变量只有
  selector 的 max_per_source：S0=None 不限同源，S3=3 每源上限）。
- 全部输入来自 precheck 已验证的指纹，无任何 LLM/索引调用。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from evaluation.compare import ARM_SELECTOR_MAX_PER_SOURCE
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
    "lock-S0.json": dict(
        common, arms=["selector-unlimited"], reranker_mode="none",
        arm_selector_policy={"selector-unlimited": ARM_SELECTOR_MAX_PER_SOURCE["selector-unlimited"]},
    ),
    "lock-S3.json": dict(
        common, arms=["selector-cap3"], reranker_mode="none",
        arm_selector_policy={"selector-cap3": ARM_SELECTOR_MAX_PER_SOURCE["selector-cap3"]},
    ),
    "lock-S0S3.json": dict(
        common, arms=["selector-unlimited", "selector-cap3"], reranker_mode="none",
        arm_selector_policy={
            "selector-unlimited": ARM_SELECTOR_MAX_PER_SOURCE["selector-unlimited"],
            "selector-cap3": ARM_SELECTOR_MAX_PER_SOURCE["selector-cap3"],
        },
    ),
}

# 交叉校验：固定字段必须与原 lock 一致（除 arms/reranker_mode/kg 外）；
# per-arm policy 必须与评测框架映射一致，且 lock 加载/校验 roundtrip 放行。
fixed_fields = ("dataset", "dataset_sha256", "corpus_sha256", "index_sha256",
                "embedding_model", "llm_model", "prompt_id", "seed", "locked_alpha")
for fname, cfg in locks.items():
    cfg = build_locked_config(**cfg)
    for f in fixed_fields:
        if cfg[f] != old[f]:
            raise SystemExit(f"{fname}: {f} lock={old[f]!r} new={cfg[f]!r}")
    # per-arm policy 与框架映射一致（防 S0/S3 策略写错）
    expected = {a: ARM_SELECTOR_MAX_PER_SOURCE[a] for a in cfg["arms"]}
    if cfg["arm_selector_policy"] != expected:
        raise SystemExit(
            f"{fname}: arm_selector_policy={cfg['arm_selector_policy']!r} "
            f"expected={expected!r}")
    # roundtrip：load + validate（预检参数）必须放行
    path = OUT / fname
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
        arm_selector_policy=expected,
    )
    if diffs:
        raise SystemExit(f"{fname}: roundtrip validation failed: {diffs}")
    print(f"✓ {fname}: arms={cfg['arms']} arm_selector_policy={cfg['arm_selector_policy']}")

print("All selector-ablation locks written and self-validated.")
