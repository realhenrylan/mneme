# Selection Decision — Phase 6-C1 cross-document ablation

## 预先锁定的 promotion gate（机械判定，6 项条件）

- **决策：NO_PROMOTION**

| 条件 | 判定 | 说明 |
|---|---|---|
| cd_recall@5_gain | 未通过 | build1 Δ=-0.025641026 |
| overall_recall@5_no_drop | 未通过 | build1 Δ=-0.068253968 |
| overall_ndcg10_mrr_no_drop | 未通过 | build1 Δ={'ndcg@10': -0.062804959, 'mrr': -0.083309255} |
| cd_source_recall@5_no_drop | 通过 | build1 Δ=0.019230769 |
| exceeds_recorded_noise | 未通过 | cd recall@5 增益 ≥ 3.0 × 记录的跨构建噪声（0.000000） |
| all_checks_passed | 通过 | 冻结/身份/manifest/citation/数据质量全部通过 |

## 判定规则

- 全部条件在**两次独立构建**上同时满足 → `EXPERIMENT_PROMISING`；任一失败 → `NO_PROMOTION`。
- 本阶段实际决策：**NO_PROMOTION**；未通过条件：['cd_recall@5_gain', 'overall_recall@5_no_drop', 'overall_ndcg10_mrr_no_drop', 'exceeds_recorded_noise']。

## 决策边界（红线）

- **即便 EXPERIMENT_PROMISING，也不改变默认产品检索策略**——候选策略只记录于本消融产物，任何采用须经后续独立阶段决策。
- v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、human_reviewed=false），不是 active、release 或人工批准。
- 生命周期 API（add/remove/sync）的 snapshot 不可变保护属未来 B0.2，本阶段未修改、未调用。
- 未测项：answer quality、citation faithfulness、answer-level refusal accuracy（见 manifest not_measured）。
- 前置复算：frozen 61 项 / 6A 50 项 / B0 64 项 / hardened 71 项，全部通过。