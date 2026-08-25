# 检索拒答阈值校准 —— Decision Report

> 目录：`retrieval-refusal-threshold-calibration`；生成时间见 manifest。
> 基线阈值：`0.03`；候选阈值：
> 0.00, 0.01, 0.02, 0.03。

## 结论：AUTOMATED_DIAGNOSTIC_NO_GO

离线扫描显示：当前检索分数**无法分离**“可回答但前哨误拒”与
“应拒答”两类 case——候选阈值 0.00 / 0.01 / 0.02 的新放行集合
完全相同（dev 10 = 4 前哨 FR + 6 应拒答；holdout 2 = 1 + 1），
且前哨 FR 分数带与正确拒答分数带完全交织：任何能放行全部
4 条 dev 前哨 FR 的阈值必然同时放行 ≥3 条正确拒答。

预注册门槛判定：
- G1（前哨 FR 放行 ≥ 4/5）：候选阈值全部满足（5/5）→ PASS；
- G2（主口径：新放行 should_refuse ≤ 10% × 该 split 全部
  should_refuse）：dev 6 > 10% × 22 = 2.2 → FAIL；
  holdout 1 > 10% × 3 = 0.3 → FAIL；
  敏感性（基数 10 / 6 / 22 与 2 / 1 / 3）结论一致 FAIL。

**无合格候选阈值** → 不进入 LLM 评测、不生成锁。

## 生产影响

- 生产 `DEFAULT_REFUSAL_THRESHOLD = 0.03` **保持不变**；
- 不切换任何生产默认、不批准 guardrail；
- `RAG_REFUSAL_POLICY=baseline` 保持不变（evidence_calibrated
  未被启用）。

## 后续建议（需人工决定）

1. 单一 max-score 阈值无法完成拒答校准——RAG-IMPROVEMENT-PLAN
   阶段 1.5 应转向**特征化拒答**（结合候选集质量、来源分布、
   query 类型等特征，而非单分数阈值）；
2. 检索层前哨拒答分层：source-only / chunk 证据缺失两种模式
   需不同处理（en-013、meta-008 为 source-only，检索命中
   相关来源但分数低于 0.03）；
3. 语料扩充后在稳定 split 新指纹下重扫，重新评估阈值候选集。

*本报告由 evaluation/threshold_scan.py 自动生成；未调用 LLM；
未修改任何生产配置与历史产物。*
