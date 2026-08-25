# v2.0.1 自动审阅对账报告

> 以 canonical `automated-review.jsonl` 为唯一事实来源，
> 对全部派生报告（summary / issues / gate-report / review-report / manifest）做逐项对账。

## canonical 真值

- n_cases：150
- confirmed：113
- reject：20
- needs_followup：17
- **non-confirmed：37**
- overlay_eligible：False

## 逐文件一致性

所有派生报告与 canonical 一致（0 差异）。

## 派生产物重建

- 已重建（内容变化）：无
- 未变化（与重建结果逐字节一致）：summary, issues, gate_report, review_report, manifest
- 重建只修正统计、清单和由其派生的 SHA；
- **未更改**任何 150 条 decision / rationale / evidence / 模型响应；
- canonical / pack / evidence SHA 对账前后不变。

## gate 状态

- verdict：**BLOCKED**（37 条 reject/needs_followup）
- overlay：**未生成**（存在 reject/needs_followup 时严禁生成）

## 结论

canonical 计数为 **113/20/17**，non-confirmed = **37**。
自动 gate 保持 **FAIL/BLOCKED**；未调用 LLM、未生成 overlay、未进入 v2.1、未 stage/commit/push。
