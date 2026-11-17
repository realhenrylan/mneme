# M6a Phase 2B：离线配对重放报告

- 裁决：**FAIL**
- 执行 HEAD：`402bfffa0ee0b2de6b694df3af02ef44ec935f1a`；base：`004e903691943267c261f892ebe16e256df7f71f`
- 预检：通过；baseline 150 例、`cases_failed=0`；runtime map 2,947 行；mapping 1,006 行；3,108/3,108 ordered IDs 可解析到 runtime 全文。

## 指标

| 指标 | control | paired | 门槛 | 结果 |
|---|---:|---:|---:|---|
| C1 `store_hit_recall_evi`（A） | 0.3767 | 0.3578 | ≥ 0.4125 | **FAIL** |
| C2（control 修正率） | 0.5575（74 hit / 6 partial / 66 miss / 8 CE） | 未测 | ≥ 0.55 | 未执行 |
| G2′ | 1.0000 | 未测 | ≥ 0.90 | 未执行 |
| C3 `precision_evi`（A） | 0.3160 | 0.2963 | ≥ 0.3060 | **FAIL** |

`answer_judge_runner` 将答案原文直接传入 judge prompt，保留 `[S#]`。按冻结规则需补判 66 个 control miss，并对 28 个 probe 做 al3 两轮；本环境未配置 `API_KEY` 与 `BASE_URL`，因此没有发起 judge/al3 调用。C2/G2′ 未报告为零分，也未将 control 值冒充 paired 结果。C1 和 C3 precision 已低于硬门槛，裁决为 `FAIL`。

## Control 与 paired 敏感性

| 映射 | control C1 | paired C1 | control C3 precision | paired C3 precision |
|---|---:|---:|---:|---:|
| A：`ratio_runtime >= 0.50` | 0.3767 | 0.3578 | 0.3160 | 0.2963 |
| B：runtime/store 双边 | 0.2367 | 0.2244 | 0.1950 | 0.1806 |
| C：store 单边 | 0.2433 | 0.2311 | 0.2016 | 0.1822 |

A 是已签的单边 runtime 主口径；B/C 仅敏感性。Q2-d 的 context-reachable oracle A=`0.4483`，单独报告，不替代 C1。

## 一致性与预算

- 一致性：150/150 例剥离 `[S#]` 后逐字节一致；150/150 例槽位数不变；槽位 460/460。
- 重放统计：examined=460，retargeted=102，unchanged=358，invalid=0，groups=281。
- baseline 生成用量：1,159,423 prompt + 18,294 completion = 1,177,717 token / 150 answer rows。
- Phase 2B 新生成：0；judge/al3：0 calls、0 token（上限 158,521）。本次合计计入 1,177,717/1,339,224 token；硬上限 1,500,000 token / 400 calls。calls 按 150 个成功答案记录 + 0 次新增调用计；允许的 baseline 文件不含 retry-attempt 明细。

## 输入与披露

- baseline Git blob SHA-256：`5cd71261507a8367c9acb160bb71406fc289e85a19ed761a6fe0604ba85a5c54`；worktree raw CRLF SHA-256 仅披露：`16d4797c05d68820d474ad42e92a540b25e7508dcd8f6c6cb0b33d1ee47989c6`。
- dataset LF SHA-256：`4597167dadd72ba972373bedc44d27c858b7c7ddbe42f8ede9d37021b38e92a9`；worktree raw CRLF SHA-256 仅披露：`88fa2928f545cf6bcdd4948cbd389e2488e769cf38d0a0db13fc9a1ffc7b27c5`。
- M6a 模块 SHA-256：`ee9963c76cbf580238b5914a3b1a34d6265bdd66a5bdbfeb3523a457bccc1613`。
- 未使用 `full_sources` snippet；fabricated/retrieved 均为 **未验证**，不宣称完整 C3；未使用旧 `0.0456` / `0.2067` 指标。
- 未 push，未改产品默认，未改产品 `src/` 路径。
