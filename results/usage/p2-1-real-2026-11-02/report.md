# P2-1 真实使用成本观察（本地停止报告）

**状态：INSUFFICIENT_SAMPLE**。这是观察样本，不是产品通过/失败结论。

> AI 生成问题，origin=user；不代表人类自然使用。

## 执行与部署信息

- 仓库执行 commit：`36ae6f378bb8fa8bfda8861604002484a47166d4`
- 本次查询进程临时环境：`RAG_USAGE_LEDGER=1`、`PYTHONUTF8=1`；`MNEME_DATA_DIR` 未设置，沿用默认目录 `C:\Users\Henry Lan\.mneme`。
- trace consent：`minimal`。
- TUI 未重启；没有创建长期服务。
- 未修改产品代码、默认配置或 consent；未 commit/push。
- 台账路径：`C:\Users\Henry Lan\.mneme\usage\usage-2026-11.jsonl`
- 台账 SHA-256：`bb6212f804674ab27b9dac64c11469c6db81f23645e207e98e43dbd8352e6520`
- 报告生成时间：`2026-11-08T13:26:35.068661+00:00`

## 窗口与样本量

- 首末 `ts_bucket`：`2026-11-02` 至 `2026-11-06`（UTC 日桶）。
- `origin=user`：47 条；其中 `usage_source=provider`：45 条，覆盖率 95.74%。
- 修正后 n（`origin=user` 且 `tokens_total` 非 null）：45。
- 排除项：`origin=evaluation/test` 共 0 条。
- `config_fingerprint`：`3b34e9a5c952`。
- 停止条件：最近一次台账写入时间为 `2026-11-06T12:28:59.964966+00:00`；超过 24 小时没有新台账行，按停止规则结束采集。provider 样本目标为 200，当前为 45。

## 聚合指标

| 指标 | 结果 |
|---|---|
| tokens_total | n=45; mean=1976.400; p50=1916.000; p90=2458.000; p95=2708.000 |
| tokens_prompt | n=45; mean=1744.911; p50=1719.000; p90=2004.400; p95=2135.200 |
| tokens_completion | n=45; mean=231.489; p50=129.000; p90=548.200; p95=766.600 |
| total_ms | p95=11299.400 ms（n=47） |
| ttft_ms | p95=3091.800 ms（n=45） |
| 拒答率 | 0 / 修正后 n 45 = 0.00% |
| cache_hit | 0 / 47 = 0.00% |
| retry_count | 总量 0；分布：0: 47 (100.00%) |
| retrieval_k | 20: 47 (100.00%) |
| context_chunks | 10: 17 (36.17%)；11: 15 (31.91%)；12: 7 (14.89%)；13: 2 (4.26%)；14: 1 (2.13%)；6: 1 (2.13%)；9: 4 (8.51%) |

- usage_source：missing: 2 (4.26%)；provider: 45 (95.74%)。
- by_outcome.user：answered: 45；error: 2；refused_post_llm: 0；refused_pre_llm: 0。
- by_refusal_stage.user：none: 47 (100.00%)。
- by_origin / by_model 汇总：
  - origin `user`：n=47；tokens_total p95=2708.000；total_ms p95=11299.400；llm_calls mean=1.404。
  - model `deepseek-chat`：n=45；tokens_total p95=2708.000；total_ms p95=8004.400；llm_calls mean=1.467。
  - model `unknown`：n=2；tokens_total p95=null；total_ms p95=11954.050；llm_calls mean=0.000。

## T6 观察阈值

- tokens_total p95：预警 15,618；复评 18,741。
- tokens_total 均值：预警 8,658；复评 9,839。
- 拒答率观察带：[20%, 40%]。
- 本次状态：**INSUFFICIENT_SAMPLE**。样本数尚未达到 200 条 provider-backed user 查询，因此不形成 T6 成本判断。阈值仅作观察参考。

## 数据质量与限制

- 台账 schema 未发现 query/answer/prompt/trace_id/session_id 字段；分析只使用白名单数值、枚举字段。
- 保留的 2 条 `error/missing` 行由 owner 说明属于 402 余额不足期间的失败样本；未删除、未补 token。
- 缺失 token 保持 null，没有估算或用文本长度替代。
- 当前只有一个 `config_fingerprint`，未混合配置。
- 本样本由 AI 生成问题并以 `origin=user` 写入，不代表人类自然使用；样本量和窗口也不足以代表长期真实使用。

## 结论

样本不足（`INSUFFICIENT_SAMPLE`）：已因 24 小时无新台账行触发停止条件。继续观察是否恢复、如何恢复由 owner 审核决定。本报告不评价产品通过或失败，也不建议据此调整阈值、配置或产品默认。
