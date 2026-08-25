# production-baseline-20260804T2220 — 运行命令记录

> 目的：以**人工审核后真值**（reviewed-production overlay）在**生产基线**
> 上运行新的 dev + 独立 holdout full，输出正式候选报告（阈值建议、
> citation v2 guardrail 基线）。全部产物标注为 CANDIDATE（候选），
> 非最终上线批准。
>
> 生产基线：arms=[standard]（RAG_RERANKER=none）、
> RAG_SELECTOR_MAX_PER_SOURCE=3（arm_selector_policy={"standard": 3}）、
> Graph 禁用（无 graph-rerank 臂，kg_sha256=None）、alpha=1.0。

## 1. 预检与完整性校验（均 PASS）

```bash
python results/graph-gate/production-baseline-20260804T2220/gen_lock.py
# lock-production.json: arms=[standard] policy={"standard": 3} reranker=none alpha=1.0
# dataset_sha256=7c131cd7...（已人工补标 meta-* chunk 真值，与旧锁不同属预期）
# corpus_sha256=41fdb853...（与旧锁一致，6 文件未变）

python results/graph-gate/production-baseline-20260804T2220/precheck.py
# PASS: corpus/index 指纹与旧锁一致（index=c6b54781..., 736 chunks）
#       reranker=none、SELECTOR_MAX_PER_SOURCE=3、env 就绪

python -m evaluation.review_apply --dataset evaluation/datasets/v1.jsonl \
  --ground-truth results/graph-gate/dev/ground-truth-map.json \
  --review-pack results/graph-gate/review-pack-chunk-annotated \
  --output results/graph-gate/reviewed-production \
  --notes "Human review: 27/27 overlap decisions (25 confirmed, 2 rejected); 4 source-only; 8 meta-* chunk annotations"
# overlap decisions: 27 (confirmed=25, rejected=2); case relevance: 4 (source=4)

python results/graph-gate/production-baseline-20260804T2220/verify_truth_integrity.py
# PASS: SHA 链一致；27/27 决定；source-only 4 = dataset 无 chunk 真值 case；
#       8 个补标 case 均有 relevant_chunks；overlay 键全部可被 GT 消费
```

## 2. dev 全量 full（94 例，生产基线 + 人工真值）

```bash
PYTHONUNBUFFERED=1 python -m evaluation.compare \
  --dataset v1 --corpus-dir test_texts --split development --phase full \
  --arms standard --alpha-grid 1.0 --seed 42 \
  --config "D:\GitHub\mneme\results\graph-gate\production-baseline-20260804T2220\lock-production.json" \
  --reviewed-truth "D:\GitHub\mneme\results\graph-gate\reviewed-production\reviewed-truth-overlay.json" \
  --collection-name eval-autorun-lock \
  --output "D:\GitHub\mneme\results\graph-gate\production-baseline-20260804T2220\dev-full" \
  --bootstrap-iterations 1000 --bootstrap-seed 42
```

## 3. holdout 全量 full（15 例，同一锁 + 同一 overlay）

```bash
PYTHONUNBUFFERED=1 python -m evaluation.compare \
  --dataset v1 --corpus-dir test_texts --split holdout --phase full \
  --arms standard --alpha-grid 1.0 --seed 42 \
  --config "D:\GitHub\mneme\results\graph-gate\production-baseline-20260804T2220\lock-production.json" \
  --reviewed-truth "D:\GitHub\mneme\results\graph-gate\reviewed-production\reviewed-truth-overlay.json" \
  --collection-name eval-autorun-lock \
  --output "D:\GitHub\mneme\results\graph-gate\production-baseline-20260804T2220\holdout-full" \
  --bootstrap-iterations 1000 --bootstrap-seed 42
```

## 口径与限制

- 真值为人工审核后版本：27/27 overlap（25 confirmed / 2 rejected），
  4 source-only（cross-008/en-013/meta-003/meta-008），8 个 meta-* case
  补标 chunk 真值（dataset v1.jsonl 已更新）。
- 与历史运行（auto-run/reranker-recheck/selector-ablation）**不可直接比**：
  dataset 真值不同（补标+人工审核）——历史 citation 指标基于旧真值。
- citation 指标使用契约 v2 口径（evaluation/citation_aggregation.py
  唯一聚合；compare.py compute_summary 自动输出 citation_v2 块）。
- 不修改任何历史 results 产物与 decision-report.md；不 stage/commit。

## 0. 关键修复与固定（split 确定性）

**框架问题**：`evaluation.compare.group_aware_split` 的 multi-turn chain 分配
依赖 `chain_root_ids` set 迭代顺序（受 PYTHONHASHSEED 随机化影响），
**每个进程的 dev/holdout 划分可能不同**。overlay 生成（review_pack 流程）
与评测运行若在不同进程，split 不一致会导致：
- overlay 条目无法被评测端 GT 消费（fail-closed 拒绝）；
- 评测端 holdout 出现 overlay 未覆盖的 needs_review case → 真值门禁失败
  （实测：无 PYTHONHASHSEED 时 holdout 失败于 multi-006）。

**修复**：本目录全部流程（rebuild_gt_map / precheck / compare 评测）一律
以 `PYTHONHASHSEED=0` 运行，保证 split 确定且 rebuild↔评测严格一致。
（历史各运行未固定 hash seed，其 dev/holdout 集合一致性未验证——本报告
结论仅对 PYTHONHASHSEED=0 的固定 split 有效。）

**真值补标披露**：en-004 / mixed-005 的 relevant_chunks snippet 原为
论文定义的意译（GT 匹配到错误候选 chunk_184，被人工 reject），已修正为
chunk_27（2.1 Speculative Decoding, page 3）的**逐字子串**：
`The target model verifies all candidates in a single forward pass, accepting
the longest prefix consistent with its own distribution`
（语义不变，仅恢复 exact 可匹配性；git diff 可审计）。
