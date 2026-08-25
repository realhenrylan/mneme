# selector-ablation-20260804T202048 — 运行命令记录

> 全部产物标为 **AUTOMATED_DIAGNOSTIC**（自动化诊断），非人工审核结论。
> 唯一实验变量：context selector 同源上限（S0=selector-unlimited 不限同源
> max_per_source=None；S3=selector-cap3 每源最多 3）。双臂均无 reranker
> （RAG_RERANKER=none）、Graph 禁用（arms 不含 graph-rerank）、alpha=1.0。
> 不修改 auto-run-20260804T121410/、reranker-recheck-20260804T185937/、
> citation-eval-fix-20260804T200234/ 与 decision-report.md；不 stage/commit。

## 1. 预检

```bash
python -m pytest -q                      # 783 passed, 7 skipped
python -m py_compile src/retrieval.py src/rag.py evaluation/compare.py \
  evaluation/locked_config.py ...        # OK
git diff --check                         # clean

python results/graph-gate/selector-ablation-20260804T202048/precheck.py
# dataset/corpus/index/overlay/prompt_id/budgets 全部与锁定配置一致
# index_sha256=c6b54781..., index_fingerprint=fefbc734...
# env API_KEY/BASE_URL present（值不入库）；LLM_MODEL=deepseek-chat
# RAG_RERANKER 未设置 → none（双臂均为无 reranker 基线）
```

## 2. 生成消融锁配置

```bash
python results/graph-gate/selector-ablation-20260804T202048/gen_locks.py
# lock-S0.json  : arms=[selector-unlimited]      policy={"selector-unlimited": null}
# lock-S3.json  : arms=[selector-cap3]           policy={"selector-cap3": 3}
# lock-S0S3.json: arms=[selector-unlimited, selector-cap3]（正式运行用）
# 固定字段（dataset/corpus/index/prompt/budgets/seed/alpha=1.0）与原锁逐字段一致；
# per-arm policy 与评测框架 ARM_SELECTOR_MAX_PER_SOURCE 映射一致，
# load + validate roundtrip 放行（fail-closed 防 S0/S3 配置漂移）
```

## 3. 分层 smoke（12 例，子集 + 派生 overlay）

```bash
python results/graph-gate/selector-ablation-20260804T202048/prep_smoke.py
PYTHONUNBUFFERED=1 python -m evaluation.compare \
  --dataset "D:\GitHub\mneme\results\graph-gate\selector-ablation-20260804T202048\smoke-v1.jsonl" \
  --corpus-dir test_texts --split all --phase full \
  --arms selector-unlimited selector-cap3 --alpha-grid 1.0 --seed 42 \
  --reviewed-truth "...\smoke-overlay.json" \
  --collection-name eval-autorun-lock \
  --output "...\smoke" --bootstrap-iterations 1000 --bootstrap-seed 42
# 通过：truth gate / 双臂（无 reranker 校验）/ 12 plans / S0+S3 生成完成
# 候选池逐 case 相同（sanity 验证）；manifest 记录 arm_selector_policy
```

## 4. dev 全量 full（94 例，正式锁配置）

```bash
PYTHONUNBUFFERED=1 python -m evaluation.compare \
  --dataset v1 --corpus-dir test_texts --split development --phase full \
  --arms selector-unlimited selector-cap3 --alpha-grid 1.0 --seed 42 \
  --config "D:\GitHub\mneme\results\graph-gate\selector-ablation-20260804T202048\lock-S0S3.json" \
  --reviewed-truth "D:\GitHub\mneme\results\graph-gate\auto-run-20260804T121410\auto-reviewed-truth\reviewed-truth-overlay.json" \
  --collection-name eval-autorun-lock \
  --output "D:\GitHub\mneme\results\graph-gate\selector-ablation-20260804T202048\dev-full" \
  --bootstrap-iterations 1000 --bootstrap-seed 42
```

## 5. holdout 全量 full（15 例，同一锁配置）

```bash
PYTHONUNBUFFERED=1 python -m evaluation.compare \
  --dataset v1 --corpus-dir test_texts --split holdout --phase full \
  --arms selector-unlimited selector-cap3 --alpha-grid 1.0 --seed 42 \
  --config "...\lock-S0S3.json" \
  --reviewed-truth "...\auto-run-20260804T121410\auto-reviewed-truth\reviewed-truth-overlay.json" \
  --collection-name eval-autorun-lock \
  --output "...\holdout-full" --bootstrap-iterations 1000 --bootstrap-seed 42
```

## 6. S0/S3 配对分析（只读）

```bash
python results/graph-gate/selector-ablation-20260804T202048/analyze_s0s3.py
# → s0s3-analysis.json（dev/holdout 全指标 + 统计检验 + 切片 + 公平性审计）
# → dev-full/failures.csv、holdout-full/failures.csv（S0/S3 对齐）
```

## 口径限制

- 本目录双臂与 reranker-recheck / auto-run 的任一历史臂**不可直接比**（不同
  实验设置：reranker 有无、selector 策略、框架版本）。一切结论仅来自本次
  受控 S0/S3（同一进程、共享 QueryPlan、同一候选池，唯一变量 max_per_source）。
- cap=3 是「选择层」约束：最终 context 经 parent/adjacent 扩展后可超 3
  （生产既有行为，双臂一致）；选择层差异以同源 rank≥4 保留数佐证。
- citation 指标使用契约 v2 口径（context_supported_citation_validity）。
- 真值 overlay 为 auto-run 自动标注的 provisional 版本（非人工审核）。
