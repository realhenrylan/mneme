# reranker-recheck-20260804T185937 — 运行命令记录

> 全部产物标为 **AUTOMATED_DIAGNOSTIC**（自动化诊断），非人工审核结论。
> 唯一实验变量：reranker（A=none，B=修复后 chunk-aware cross-encoder）。
> Graph 禁用（arms 不含 graph-rerank）；alpha 固定 1.0（无 graph 通道，等价 B）。
> 不修改 auto-run-20260804T121410/ 与 decision-report.md；不 stage/commit。

## 1. 预检

```bash
python -m pytest -q                      # 738 passed, 7 skipped
python -m py_compile evaluation/compare.py evaluation/metrics.py ... # OK
git diff --check                         # clean

python results/graph-gate/reranker-recheck-20260804T185937/precheck.py
# dataset/corpus/index/overlay/prompt_id/budgets 全部与锁定配置一致
# index_sha256=c6b54781..., index_fingerprint=fefbc734...
# env API_KEY/BASE_URL present（值不入库）；LLM_MODEL=deepseek-chat
```

## 2. 生成 recheck 锁配置

```bash
python results/graph-gate/reranker-recheck-20260804T185937/gen_locks.py
# lock-A.json  : arms=[standard]              reranker_mode=none
# lock-B.json  : arms=[standard-rerank]       reranker_mode=cross-encoder
# lock-AB.json : arms=[standard, standard-rerank] reranker_mode=cross-encoder（正式运行用）
# 固定字段（dataset/corpus/index/prompt/budgets/seed/alpha=1.0）与原锁逐字段一致
```

## 3. 分层 smoke（12 例，子集 + 派生 overlay）

```bash
python results/graph-gate/reranker-recheck-20260804T185937/prep_smoke.py
env RAG_RERANKER=cross-encoder PYTHONUNBUFFERED=1 python -m evaluation.compare \
  --dataset "D:\GitHub\mneme\results\graph-gate\reranker-recheck-20260804T185937\smoke-v1.jsonl" \
  --corpus-dir test_texts --split all --phase full \
  --arms standard standard-rerank --alpha-grid 1.0 --seed 42 \
  --reviewed-truth "...\smoke-overlay.json" \
  --collection-name eval-autorun-lock \
  --output "...\smoke" --bootstrap-iterations 1000 --bootstrap-seed 42
# 通过：truth gate / reranker 校验 / 12 plans / A/B 生成完成
```

## 4. dev 全量 full（95 例，正式锁配置）

```bash
env RAG_RERANKER=cross-encoder PYTHONUNBUFFERED=1 python -m evaluation.compare \
  --dataset v1 --corpus-dir test_texts --split development --phase full \
  --arms standard standard-rerank --alpha-grid 1.0 --seed 42 \
  --config "D:\GitHub\mneme\results\graph-gate\reranker-recheck-20260804T185937\lock-AB.json" \
  --reviewed-truth "D:\GitHub\mneme\results\graph-gate\auto-run-20260804T121410\auto-reviewed-truth\reviewed-truth-overlay.json" \
  --collection-name eval-autorun-lock \
  --output "D:\GitHub\mneme\results\graph-gate\reranker-recheck-20260804T185937\dev-full" \
  --bootstrap-iterations 1000 --bootstrap-seed 42
```

## 5. holdout 全量 full（16 例，同一锁配置）

```bash
env RAG_RERANKER=cross-encoder PYTHONUNBUFFERED=1 python -m evaluation.compare \
  --dataset v1 --corpus-dir test_texts --split holdout --phase full \
  --arms standard standard-rerank --alpha-grid 1.0 --seed 42 \
  --config "D:\GitHub\mneme\results\graph-gate\reranker-recheck-20260804T185937\lock-AB.json" \
  --reviewed-truth "D:\GitHub\mneme\results\graph-gate\auto-run-20260804T121410\auto-reviewed-truth\reviewed-truth-overlay.json" \
  --collection-name eval-autorun-lock \
  --output "D:\GitHub\mneme\results\graph-gate\reranker-recheck-20260804T185937\holdout-full" \
  --bootstrap-iterations 1000 --bootstrap-seed 42
```

## 6. A/B 配对分析（只读）

```bash
python results/graph-gate/reranker-recheck-20260804T185937/analyze_ab.py
# → ab-analysis.json（dev/holdout 全指标 + 统计检验 + 切片 + 公平性审计）
```

## 口径限制

- 本目录 A 臂与 auto-run-20260804T121410 的 A 臂**不可直接比**（旧 A 无
  source diversity / 对称 selector；修复改变了 context 选择行为）。
- 一切结论仅来自本次受控 A/B（同一进程、共享 QueryPlan、同一 selector、
  同一 budgets，唯一变量 reranker）。
