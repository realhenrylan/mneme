# refusal-ablation-20260805T133209 — 运行命令记录

> 目的：拒答策略受控消融（A=standard baseline / B=standard-calibrated
> evidence_calibrated），仅改变生成阶段 system prompt；共享同一
> QueryPlan/检索候选/context/模型/温度/预算/split。
> 结果：**AUTOMATED_DIAGNOSTIC_NO_GO**（G1/G4 不达标，未跑 holdout）。
> 设计：plans/REFUSAL-POLICY-ABLATION-DESIGN-2026-08-05.md。

## 0. TDD 实现（三批次，53 个新测试）

```bash
python -m pytest tests/test_refusal_policy.py tests/test_refusal_policy_locking.py \
  tests/test_refusal_ablation_eval.py tests/test_paired_analysis.py -q   # 53 passed
python -m pytest -q    # 885 passed, 7 skipped
```

## 1. 生成新锁（复用稳定 split 指纹 + 双 overlay）

```bash
python gen_lock.py
# split_fingerprint=454892e4…3690（与稳定 split 锁一致）
# arms=[standard, standard-calibrated]
# refusal_policy={"standard": "baseline", "standard-calibrated": "evidence_calibrated"}
# effective_prompt_ids={standard: d5b905dc…, standard-calibrated: 2d602fb4…}
```

## 2. precheck（PASS）

```bash
RAG_RERANKER=none python precheck.py
# 锁全字段（含 refusal_policy/effective_prompt_ids）/ 稳定 split 指纹 /
# 双 overlay + truth gate / 索引指纹 / env / immutability 快照
```

## 3. smoke 15 条 false_refusal 双臂（PASS）

```bash
RAG_RERANKER=none PYTHONUNBUFFERED=1 python smoke.py
# 每 case prepare_answer_evidence 一次 → A/B 共享 evidence 分别 generate
# A 15/15 拒答、B 14/15（en-016 改善）；5 例检索前哨拒答（策略不可改善）
```

## 4. dev full（95×2 臂，EXIT=0）

```bash
RAG_RERANKER=none PYTHONUNBUFFERED=1 python -m evaluation.compare \
  --dataset v1 --corpus-dir test_texts --split development --phase full \
  --arms standard standard-calibrated --alpha-grid 1.0 --seed 42 \
  --config "...\lock-refusal-ablation.json" \
  --reviewed-truth "...\stable-split-rebuild-20260804T234043\reviewed-production-dev\reviewed-truth-overlay.json" \
  --collection-name eval-autorun-lock \
  --output "...\refusal-ablation-20260805T133209\dev-full" \
  --bootstrap-iterations 1000 --bootstrap-seed 42   # → dev-full.log
```

## 5. 配对分析 + 门槛判定（fail-closed）

```bash
python -m evaluation.paired_analysis \
  --dir-a dev-full --dir-b dev-full --dataset evaluation/datasets/v1.jsonl \
  --output paired-analysis-dev.json
python gate_eval.py    # → AUTOMATED_DIAGNOSTIC_NO_GO（G1/G4 FAIL）
```

## 6. 阶段验证（独立子代理，不采信结论）

- TDD 实现阶段：代码/测试/锁定/不泄露/评测端接线逐项复验
- 受控评测阶段：锁/SHA/指标独立复算/门槛判定/不可变性复验

## 约束

- 未调用任何历史改写；未 stage/commit；未自动切换默认策略
  （RAG_REFUSAL_POLICY 默认保持 baseline）；未批准 guardrail；
  NO_GO → 未运行 holdout full。
