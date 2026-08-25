# Comparison to Phase 6-A — frozen-current vs frozen-contract

## 两阶段异同

- 相同：同一冻结 1006 chunks、同一 136 cases、同一检索代码（embedding → Chroma cosine → BM25 CJK n-gram → RRF k=60）。
- 差异：Phase 6-A 用适配器绕过 parser 直接以冻结 chunks 建临时索引（无 sidecar）；本阶段通过**完整产品索引入口**（`src.rag.prepare_index` + chunk snapshot contract）建索引，含 collection manifest 与 BM25 sidecar，且 source 身份为产品级（全 64 位 source_id = 路径哈希；6A 适配器用 basename 作 source_id）。

## aggregate 指标对比（Δ = contract − 6A）

| 指标 | Δ |
|---|---|
| recall@5 | 0.0 |
| recall@10 | 0.0 |
| recall@20 | 0.0 |
| ndcg@5 | 0.0 |
| ndcg@10 | 0.0 |
| ndcg@20 | -5.7e-05 |
| mrr | -4.4e-05 |
| source_recall@5 | 0.0 |
| source_recall@10 | 0.0 |
| source_recall@20 | 0.0 |

- 分母：6A {'chunk_metrics_cases': 105, 'mapping_failure_rows': 0, 'no_chunk_truth_cases': 31, 'total_cases': 136} vs contract {'total_cases': 136, 'chunk_metrics_cases': 105, 'no_chunk_truth_cases': 31, 'mapping_failure_rows': 0}，**一致**。
- chunk 数：1006（两阶段相同）；evidence 映射：105 with-truth / 31 no-truth（相同）。
- per-case 指标差异 case 数：**3**；per-case 检索集合差异 case 数：**27**。
- 非零 aggregate Δ：[{'key': 'ndcg@20', 'delta': -5.7e-05}, {'key': 'mrr', 'delta': -4.4e-05}]

## HNSW 跨构建扰动

- 同索引重复查询逐位一致；跨构建（独立索引）在深 rank 处存在近邻扰动。本阶段确定性复验：
- raw 差异 78 处 / 指标受影响 10 case（明细见 contract-baseline-summary.json determinism）。
- 若聚合指标不一致，差异已在 aggregate_deltas 中如实列出，不做掩盖。