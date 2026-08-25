# Comparison to Phase 6-B0 — frozen-contract vs frozen-contract-hardened

## 修复说明（Phase 6-B0.1 产品入口硬化）

本阶段修复了三个已独立复现的入口边界缺陷（TDD RED→GREEN，
`tests/test_index_contract.py` Group 4/5）：

1. **build_index 先建 collection 再校验 source 集合**——source 集合不匹配时已产生空 collection 与 `chroma.sqlite3`；现在验证前置到任何 PersistentClient / 模型 / collection / manifest / BM25 sidecar 写入之前，传入的空 `chroma_path` 保持无任何文件。
2. **复用已有 collection 不校验集合**——传入缺少一个 source 的 `file_paths` 会被静默复用；现在 `file_paths` 必须与 snapshot 源集合**精确一致**（缺失/额外 → 拒绝），且复用前校验 collection manifest 的 `sources` 与 snapshot 一致（不一致 → 强制安全重建，绝不复用陈旧索引）。
3. **入口只信任内存对象**——`dataclasses.replace` 篡改（篡改 chunk 文本 + 伪造 fingerprint）仍被接受；现在 snapshot 保留输入身份，使用时经 `src.index_contract.verify_snapshot_current` 重新执行 `load_chunk_snapshot` 全量验证并比对重建契约指纹 / chunk 内容 / source 集合，失败抛 `SnapshotContractError`（fail-closed），索引内容永远来自受验证输入的重建。

## 两阶段异同

- 相同：同一冻结 1006 chunks、同一 136 cases、同一产品索引入口（`src.rag.prepare_index` + snapshot）、同一检索代码（embedding → Chroma cosine → BM25 CJK n-gram → RRF k=60）。
- 差异：本阶段入口在**任何写入之前**重新验证 snapshot（指纹应一致，见下）；旧 B0 产物保持只读，lineage SHA 记录于 manifest。

## 与旧 B0 的 aggregate 指标对比（Δ = hardened − B0）

| 指标 | Δ |
|---|---|
| recall@5 | 0.0 |
| recall@10 | 0.0 |
| recall@20 | 0.0 |
| ndcg@5 | 0.002155 |
| ndcg@10 | 0.002155 |
| ndcg@20 | 0.002155 |
| mrr | 0.004779 |
| source_recall@5 | 0.0 |
| source_recall@10 | 0.0 |
| source_recall@20 | 0.0 |

- 分母：B0 {'chunk_metrics_cases': 105, 'mapping_failure_rows': 0, 'no_chunk_truth_cases': 31, 'total_cases': 136} vs hardened {'total_cases': 136, 'chunk_metrics_cases': 105, 'no_chunk_truth_cases': 31, 'mapping_failure_rows': 0}，**一致**。
- 契约指纹：B0 `4a78d5f357d7b7e6381da9a78fa15b9d2773b818a29ab52223b03b06ed20687e` vs hardened `4a78d5f357d7b7e6381da9a78fa15b9d2773b818a29ab52223b03b06ed20687e`，**一致**（同一受验证输入）。
- per-case 指标差异 case 数：**2**；per-case 检索集合差异 case 数：**32**。
- 非零 aggregate Δ：[{'key': 'ndcg@5', 'delta': 0.002155}, {'key': 'ndcg@10', 'delta': 0.002155}, {'key': 'ndcg@20', 'delta': 0.002155}, {'key': 'mrr', 'delta': 0.004779}]

## 旧 B0 manifest 复算（lineage）

- 64 项复算（self-hash + inputs / frozen_outputs / outputs 字节 SHA）：**通过**（漂移 0 项）。

## 确定性

- 本阶段两次独立构建（determinism）：raw 差异与指标受影响 case 数见 `contract-baseline-summary.json` 的 determinism（如实记录，不伪称逐 case 字节一致）。
- 旧 B0 记录的 determinism：`{'cases_compared': 136, 'difference_count': 75, 'differences': [{'case_id': 'multi-016', 'field': 'retrieved_chunk_ids'}, {'case_id': 'multi-016', 'field': 'scores'}, {'case_id': 'multi-018', 'field': 'retrieved_chunk_ids'}, {'case_id': 'multi-021', 'field': 'retrieved_chunk_ids'}, {'case_id': 'multi-021', 'field': 'scores'}, {'case_id': 'multi-025', 'field': 'retrieved_chunk_ids'}, {'case_id': 'multi-025', 'field': 'scores'}, {'case_id': 'zh-024', 'field': 'retrieved_chunk_ids'}, {'case_id': 'zh-024', 'field': 'scores'}, {'case_id': 'zh-030', 'field': 'retrieved_chunk_ids'}, {'case_id': 'zh-030', 'field': 'scores'}, {'case_id': 'zh-030', 'field': 'metrics'}, {'case_id': 'en-022', 'field': 'retrieved_chunk_ids'}, {'case_id': 'en-022', 'field': 'scores'}, {'case_id': 'en-023', 'field': 'retrieved_chunk_ids'}, {'case_id': 'en-023', 'field': 'retrieved_source_ids'}, {'case_id': 'en-023', 'field': 'scores'}, {'case_id': 'en-024', 'field': 'retrieved_chunk_ids'}, {'case_id': 'en-024', 'field': 'retrieved_source_ids'}, {'case_id': 'en-024', 'field': 'scores'}], 'metric_difference_count': 9, 'metric_differences': [{'build1': 0.041666666666666664, 'build2': 0.043478260869565216, 'case_id': 'zh-030', 'key': 'mrr'}, {'build1': 0.04, 'build2': 0.041666666666666664, 'case_id': 'en-024', 'key': 'mrr'}, {'build1': 0.5, 'build2': 1.0, 'case_id': 'zh-048', 'key': 'mrr'}, {'build1': 0.6934264036172708, 'build2': 0.9197207891481876, 'case_id': 'zh-048', 'key': 'ndcg@10'}, {'build1': 0.6934264036172708, 'build2': 0.9197207891481876, 'case_id': 'zh-048', 'key': 'ndcg@20'}, {'build1': 0.6934264036172708, 'build2': 0.9197207891481876, 'case_id': 'zh-048', 'key': 'ndcg@5'}, {'build1': 0.1111111111111111, 'build2': 0.125, 'case_id': 'zh-051', 'key': 'mrr'}, {'build1': 0.18457569677956817, 'build2': 0.19342640361727081, 'case_id': 'zh-051', 'key': 'ndcg@10'}, {'build1': 0.18457569677956817, 'build2': 0.19342640361727081, 'case_id': 'zh-051', 'key': 'ndcg@20'}], 'note': '第二次构建使用独立临时目录与独立 collection；比较除 retrieval_ms 外全部字段。raw ranking 差异源于 Chroma/HNSW 索引构建的非确定性（同索引重复查询逐位一致，跨构建在深 rank 处有近邻扰动）；metric_difference_count 是 per-case 指标受影响的 case 数，聚合指标应稳定', 'verified': False}`。
- HNSW 跨构建近邻扰动是环境/链路事实：同索引重复查询逐位一致，跨构建在深 rank 处有扰动；聚合指标应稳定，任何差异已在 `aggregate_deltas` 中如实列出，不做掩盖。