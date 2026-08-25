# 候选报告 Addendum：稳定 split 修复与事实修正

> 本文件是 `results/graph-gate/production-baseline-20260804T2220/candidate-report.md`
> 的补充（addendum）。**不改写原报告**；原报告保持历史状态。
> 日期：2026-08-04（稳定 split 重建 `stable-split-rebuild-20260804T234043/`）

## 一、背景：group-aware split 的跨进程不确定性与永久修复

原候选报告 §三 披露的 PYTHONHASHSEED 缺陷（`group_aware_split` 把
`set(chain_root_ids)` 直接转 list 后 shuffle，set 迭代顺序随
PYTHONHASHSEED 变化）此前仅用 `PYTHONHASHSEED=0` 运行绕过，**不是
永久修复**。本批已在框架层修复（TDD 驱动）：

1. **chain root 分配前稳定排序**（`sorted(chain_root_ids)`）再
   `Random(seed)` shuffle；chain 遍历改 `sorted(chains.items())`；
2. **最终 dev/holdout 输出按 case_id 稳定排序**——结果 JSONL、review
   pack、锁配置全部可复现；
3. **split 指纹锁定**：`compute_split_fingerprint`（canonical 排序后
   case_id 列表的 SHA-256）写入 locked-config（新锁必填，旧锁加载
   向后兼容），`compare` 在任何索引/LLM/QueryPlan 工作前 fail-closed
   校验当前 split 指纹，dataset 或 split 算法变化导致集合不一致时
   拒绝运行并明确报错。

修复验证：`tests/test_compare.py::TestGroupAwareSplitHashSeedDeterminism`
在 3 个不同 PYTHONHASHSEED（0/1/42）的独立子进程中对真实 v1 数据集
断言 dev/holdout case_id 集合与顺序完全一致；旧代码实测失败
（seed=1 的 holdout 为 multi-004/005/006 链，seed=0/42 为
multi-007/008/009/010 链），修复后全绿。

## 二、split 变化与旧结果作废声明

修复后同一 `--seed=42` 的稳定拆分（不再依赖 PYTHONHASHSEED）：

| | 旧（PYTHONHASHSEED=0，已作废） | 新（稳定 split，当前） |
|---|---|---|
| dev | 94 例 | **95 例** |
| holdout | 16 例（含 multi-007/008/009/010 链） | **15 例（含 multi-004/005/006 链）** |
| split 指纹 | 未锁定（不可复现） | `454892e4b9968e9ed85807b605fc6fffe920dd1aa3a665c29f8235eafeaa3690` |

**因此原候选报告 §二 的 dev/holdout 指标（micro=1.0000 等）不能作为
新稳定 split 下的正式基线**——它们基于旧（已作废）拆分。正式指标需在
新锁定指纹（`lock-production-stable.json`）下重跑一轮评测后产生；
本次任务约束不重跑评测、不调用 LLM/API，故新基线指标待后续运行。

## 三、事实修正：25 条 overlap 决策为 LLM 辅助审阅，非人工签署

原候选报告将 27 条决定表述为「人工审核」并作为 guardrail 支持证据。
事实修正如下：

- **25 条 confirmed overlap 决策是 LLM 辅助审阅产生的**（证据清单由
  本地脚本提取、决策经 LLM 辅助比对文本后确认），**不是独立人工签署**；
  2 条 reject（en-004、mixed-005）同理；
- 因此原报告 §四 的 **guardrail 阈值建议（micro≥0.95、
  answer_rate≥0.80、no_citation≤0.20、false_refusal≤0.20）仍是
  自动化建议，正式 guardrail 基线待人工批准后签署**；
- 8 个 meta-* case 的 chunk 补标与 2 个 snippet 修正属技术性修正
  （已披露），不改变上述事实修正。

## 四、稳定 split 下的真值重建（本批产物）

在修复后的稳定 split 下重建了全部离线真值产物（新目录
`results/graph-gate/stable-split-rebuild-20260804T234043/`，
**未改写任何历史 results / decision-report.md / 原 candidate-report.md**）：

| split | 规模 | GT entries | overlap 决定（迁移） | source-only |
|---|---|---|---|---|
| dev | 95 | 84（exact 63 + overlap 21） | 21/21 confirmed | 4（cross-008、en-013、meta-003、meta-008） |
| holdout | 15 | 16（exact 12 + overlap 4） | 4/4 confirmed | 4（同上） |

- 迁移：按稳定键（case_id, source_id, normalized_snippet, sorted
  candidates）从 canonical pack（`review-pack-chunk-annotated/`，27 条
  决定）机械回填，**25 confirmed 全部进 pack、4 source-only 保留**；
  2 条 reject（en-004、mixed-005）无目标行（补标后其标注为 exact
  匹配，不再产生 overlap 行）——决定**保留于 canonical pack 历史记录**；
- `review_apply` 严格导入（行数/键集/必填值/去重/SHA 校验）双 split
  均 PASS；`verify_truth_integrity.py` 校验 SHA 链、消费性
  （overlay entries 全部被 GT map 消费）、真值门禁（无缺真值且无显式
  决定的 case）全部 PASS；
- 新锁定配置 `lock-production-stable.json`：固定字段与历史
  `lock-production.json` 逐字段一致，仅新增 `split_fingerprint`
  （新锁必填）。

## 五、结论

- 框架缺陷已永久修复：split 跨进程确定、指纹锁定 fail-closed 校验；
- 旧候选数字作废声明如上；**正式 guardrail 基线 = 人工批准阈值 +
  新稳定 split 下重跑评测**，两者都未完成，属待办；
- 下一步（需人工指示）：批准阈值、扩充语料后在新锁定指纹下重跑
  dev + holdout full。
