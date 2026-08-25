# 阶段 1.5 特征化拒答 —— 假设生成审计（HGA）设计文档

> 日期：2026-08-05
> 状态：**已批准（用户修订：收缩为 HYPOTHESIS_GENERATING_ONLY 审计）**
> 关联：plans/RAG-IMPROVEMENT-PLAN-2026-08-01.md（阶段 1.5 拒答校准）、
> REFUSAL-THRESHOLD-CALIBRATION-DESIGN-2026-08-05.md（上批阈值扫描，NO_GO）

---

## 一、范围（用户收缩后的规格，逐字执行）

本任务**不是**候选规则筛选，也不是预注册。仅做：

1. 特征字典（feature dictionary）——运行时可获得的记录检索信号；
2. 特征表（每 case 特征 + 独立离线标签）；
3. 全规则枚举（dev 上，≤2 特征、可解释规则族）+ 描述性统计
   （FR 放行数、SR 放行数、precision/recall、PR 曲线、与 0.03 baseline
   净变化）；
4. 可视化（Markdown/CSV 表格 + ASCII 图；matplotlib 不可用，不引入依赖）。

所有输出**必须**标记 `HYPOTHESIS_GENERATING_ONLY`。以下行为**禁止**：

- 把任何规则称为"合格候选"（不得应用放行门槛/判定语）；
- 生成 LLM ablation 预注册文档；
- 使用当前 stable holdout 作为任何规则的确认（holdout 已被探索性
  查看，仅记录特征、不参与枚举与评估）；
- 修改生产拒答逻辑 / 默认配置 / 数据集 / 真值；
- 调用 LLM/API；stage/commit。

## 二、报告必须说明的四项事实

1. 两特征复合规则（如探索阶段示例 `top1 ≥ t OR std 区间`）是
   **post-hoc 假设**——在 4 FR / 6 SR 上穷举得到，无独立验证；
2. 现有 stable holdout 已被探索性查看（设计阶段读取过其特征），
   **不能用于确认**；
3. 当前样本仅 4 FR / 6 SR，**不足以验证复合门控**（功效不足，
   过拟合风险不可排除）；
4. 下一步需**扩充语料**并创建**新的、未查看的 group-aware holdout**。

## 三、未来验证协议（仅记录于报告，不实施）

若未来获得新数据：

1. dev 内**嵌套 GroupKFold**：每折只用**训练折**选择规则（枚举 +
   门槛），再到**验证折**评估一次；选择与评估严格分离；
2. 规则固定后，仅在**全新 holdout** 上评估**一次**（不再回头调参）；
3. 全部通过后，再决定是否开展 LLM 受控实验（届时另走
   brainstorming + 预注册流程）。

## 四、数据与特征

输入（只读）：`refusal-ablation-20260805T133209/dev-full/retrieval-cases.jsonl`
（standard 臂，与 16 FR / 5 前哨同一运行）+ holdout
`production-baseline-stable-20260805T084256/holdout-full/retrieval-cases.jsonl`
（仅特征表，role=`exploratory_only`）。

**特征字典**（全部来自记录信号，确定性）：

| 特征 | 来源 | 备注 |
|---|---|---|
| top1 / top2 / top3 | candidate_scores 降序 | 有方差 |
| gap12 = top1 − top2 | 同上 | 有方差 |
| mean5 / mean10 / mean_all | 同上 | 有方差 |
| std_all（总体标准差） | 同上 | 有方差 |
| ge0.01 / ge0.02 / ge0.025（≥t 的候选数） | 同上 | 有方差 |
| n_candidates | 候选数 | **恒定 70**（不可区分，如实报告） |
| n_candidate_sources | candidate_source_ids | 有方差 |
| n_context_sources / n_context_chunks / context_tokens | context_* 字段 | 拒答 case 恒 0（不可区分） |
| rewrite_flag / decompose_flag | rewrite_ms / decompose_ms | 恒 0 / 恒 True（不可区分） |
| subquery_count | 未记录 | available=False |
| per_source_chunk_max | 无 chunk→source 映射记录 | available=False |

**标签隔离（fail-closed）**：特征集不得包含 `should_refuse`、
`has_chunk_truth`、`relevant_chunk_ids`、`relevant_source_ids`、
`query_type`、`language`、`difficulty`、`case_id`、`review_*` 等
评测字段（单测断言；评测标签仅存于独立 label 字段用于离线描述）。

## 五、规则族与枚举（假设生成）

- 一元：`f ≥ t` / `f ≤ t`；
- 一元区间：`l ≤ f ≤ u`（同特征两阈值，1 特征）；
- 二元：`atom AND atom` / `atom OR atom` / `atom AND range` /
  `atom OR range`（≤2 特征）。
- 阈值网格：dev 拒答子集（10 例）每特征的不同观测值 + 相邻中点
  （确定性；假设空间聚焦于拒答人口，避免枚举爆炸）。
- 枚举去重：按放行签名（released FR ids, released SR ids）合并，
  输出每个签名 + 命中规则数 + 代表规则（≤5 条）；全枚举仅存
  签名级汇总（避免百万行 JSON）。
- 描述性指标（**非门槛**）：FR 放行数（/4）、SR 放行数（/6）、
  拒答子集 precision/recall、与 baseline 净变化（新拒答数）。
- PR 曲线：拒答子集按每个一元特征升降序排序的 PR 点表。

## 六、模块与测试（TDD）

`evaluation/refusal_separability.py`（纯离线，零 LLM）：特征提取、
标签隔离校验、阈值网格、规则构造与求值、签名去重枚举、PR 曲线、
Markdown 渲染、CLI（--dev-retrieval / --holdout-retrieval /
--output-dir）。

`tests/test_refusal_separability.py`：特征确定性、标签隔离
fail-closed（含全部禁用键）、available=False 特征、网格确定性、
规则求值（FR/SR 计数、precision/recall）、枚举确定性/有界/
去重签名/代表规则、PR 曲线、holdout 不入枚举（CLI 集成）、
输出含 `HYPOTHESIS_GENERATING_ONLY` 标记、新拒答报告。

## 七、交付物

`results/graph-gate/refusal-separability-hypothesis-20260805T<ts>/`：

- feature-dictionary.json / features.jsonl（每 case 特征 + label +
  split + role）
- rule-enumeration.json（签名级，含 HYPOTHESIS_GENERATING_ONLY）
- pr-curves.json（一元特征 PR 点表）
- separability-report.md（四项规定说明 + 特征表 + 枚举摘要 +
  ASCII 可视化）
- decision-report.md（结论：仅假设、样本不足、holdout 不可确认、
  未来协议）
- manifest.json（输入 SHA + llm_calls=0 + 不可变性声明）
- run-commands.md；模块副本 refusal_separability.py

另更新 CHANGELOG；验证：pytest、py_compile、git diff --check、
历史产物不可变性复验；不 stage/commit。

## 八、明确不做（本批）

- 不应用任何筛选门槛；不称任何规则为合格；
- 不生成 LLM ablation 预注册；
- 不实施嵌套 GroupKFold（仅记录协议）；
- 不改生产逻辑/默认/数据集/真值；不调用 LLM。
