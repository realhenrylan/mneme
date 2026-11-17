# M6a Phase 2A：映射候选与 oracle 上界（只读计算）

- 日期：2026-11-02T14:14:36+0800
- 仓库状态：main 工作树未触碰；worktree `ab4073c` @ `ab4073c1704e3a8e361e8a55373fbf03bad9859c`
- 性质：**只读离线计算**——0 LLM、0 judge、0 al3、0 网络、0 生成；truth 仅在离线脚本使用，未进入产品
- 产物目录：`results/answer-level/m6a-phase2a-2026-11-01/`
- 脚本：`scripts/audit/phase2a_oracle.py`（唯一新增代码，只读）
- 预注册：`plans/ANSWER-LEVEL-M6a-PHASE2A-ORACLE-PREREGISTRATION-2026-11-01.md`
- 上游证据：`docs/AUDIT-CHUNK-DOMAIN-2026-11-01.md` §5A + `results/answer-level/chunk-domain-audit-2026-11-01/`

## 0. 输入核验（全部通过，未触发停止条件）

| 项 | 预期 | 实测 |
|---|---|---|
| worktree HEAD | `ab4073c` | `ab4073c` ✓ |
| runtime-map 行数 | 2,947 | 2,947 ✓ |
| mapping 行数 | 1,006 | 1,006 ✓ |
| a′ baseline 例数 | 150 | 150 ✓ |
| baseline SHA 前缀 | `5cd712` | `5cd71261507a…` ✓ |
| baseline cases_failed | 0 | 0 ✓ |
| ordered IDs 可解析 | 3,108/3,108 | 3,108/3,108 ✓ |
| baseline truth == v2.1 dataset（集合比对） | 0 mismatch | 0 ✓（生产加载路径 `resolve_generation_dataset('v2.1')` → `evaluation/datasets/v2.1.jsonl`，SHA `88fa2928f545…`；truth 按集合比对——指标全部为集合运算） |
| dataset 内容 == baseline 运行时 | 内容相同 | ✓（git blob `4597167d…` == baseline-run 记录值；worktree 裸 SHA `88fa2928f545…` 仅因 `core.autocrlf=true` 将 LF→CRLF，LF 归一后与 blob 逐字节相同——内容零差异） |

- 数据备注（非停止条件）：`mixed-033` 的 dataset `relevant_chunk_ids` 列表内含重复条目 `c9fd20815ea8_chunk_18` ×2；baseline 存的是去重后的单条。集合语义下两者完全一致（Phase 1 `truth_mismatch_vs_dataset=0` 同为集合比对），不构成域不一致，未修改数据集。

- baseline 旧（ID 碰撞域）manifest 值：recall 0.0656 / precision 0.0466 —— 与 Phase 1 §4.1 ID 碰撞复现一致，**不可平移**。
- truth：122/150 例非空（28 拒答例空 truth），distinct store truth chunk 113 个。

## 1. 三种映射候选（t = 0.50，覆盖分母 = 1,006 store chunks）

| 候选 | 规则 | 覆盖率 | 一对多 | 歧义 | 未映射 truth（distinct/113） |
|---|---|---:|---:|---:|---:|
| A | ratio_runtime ≥ 0.50 | 0.9851 | 512 | 512 | 1 |
| B | runtime ≥ 0.50 且 store ≥ 0.50 | 0.7286 | 7 | 7 | 23 |
| C | ratio_store ≥ 0.50（敏感性） | 0.7465 | 16 | 16 | 21 |

读法：A 覆盖 0.9851 与 Phase 1 一致（98.5%）；C 覆盖 0.7465 < 95%，**只作敏感性，不作主口径**（预注册 §3 规则 3）。B 为双边，覆盖 0.7286。

## 2. control（a′ baseline）与 oracle 上界（逐例均值，round 4，150 例）

| 候选 | 映射规则 | 覆盖率 | control C1 (store_hit_recall_evi) | control C3 (precision_evi) | O_store（理论上界） | O_store_ach（context-reachable） | O_evi | O_store_ach − control | ≥0.02? |
|---|---|---:|---:|---:|---:|---:|---:|---:|:--|
| A | ratio_runtime >= 0.50 | 0.9851 | 0.3767 | 0.316 | 0.7667 | 0.4483 | 0.6172 | 0.0716 | 是 |
| B | ratio_runtime >= 0.50 AND ratio_store >= 0.50 | 0.7286 | 0.2367 | 0.195 | 0.7667 | 0.355 | 0.63 | 0.1183 | 是 |
| C | ratio_store >= 0.50 | 0.7465 | 0.2433 | 0.2016 | 0.7667 | 0.365 | 0.6433 | 0.1217 | 是 |

辅助（不参与裁决，详见 control-metrics.json）：A 候选下 recall_evi=0.2342、mean_rel_runtime_size=2.58、precision_ctx=0.0507、case_any_overlap_evi=0.4133；fabricated 合计=0、retrieved_not_in_context 合计=0（**capture 域旧值，Phase 2B 须按预注册 §6 在 capture 修复后重测方可入 C3**）。

**关键读法（2026-11-02 修正）**：`O_store` 假设每个 truth 都可达，**不是 M6a 的可达上界**；M6a 只能重定向到本 case context 内的 chunk，因此阈值只能用 `O_store_ach`（同时扣除未映射 truth 与不在 context 的 truth）。A 候选 context-reachable 真值率约 50%，`O_store_ach` 明显低于 `O_store`；若 Phase 2B 阈值按 `O_store` 设定，会不可达。`O_evi_ach` 见 oracle.json。

**O_store_ach − control ≥ 0.02 判定**：通过（至少一个候选）。存在可分离区间：至少一个候选的 context-reachable O_store − control ≥ 0.02；建议进入 Phase 2B（阈值由 owner 在区间内选定）。

## 3. 决策就绪建议（Q2-a..f，只给建议，不做裁决）

| 编号 | 建议 | 依据 |
|---|---|---|
| Q2-a 映射 | A（单边宽松；B 覆盖 <95% 回退） | **A（单边 runtime，宽松）**：B 覆盖率 0.7286 < 95%，按预注册 §3 回退 A（覆盖 0.9851）；**Phase 2B 报告必须披露“单边宽松”**，并附 B/C 敏感性表。 |
| Q2-b C1 主指标 | `store_hit_recall_evi`（分母 = store truth，一对多免疫） | §2 表：C1 = A 候选 0.3767 / B 0.2367 / C 0.2433 |
| Q2-c C3 主指标 | `precision_evi`（区域级精度）；非劣门槛 = control − 0.01；fabricated/retrieved 两项**未验证**（capture 修复未实施），C3 只能按“precision 非劣 + 两标记未验证”降级表述 | 预注册 §6；本目录 control-metrics.json |
| Q2-d oracle 方法 | `min(m, truth_reachable)/truth` 逐例均值；m = 答案中既有 `\[S\d+\]` 槽位数；truth_reachable = 映射 runtime 与本 case context 有交集的 store truth；不新增/删除槽位；一槽至多命中一个 truth | oracle.json（理论 O_store 仅作上界披露） |
| Q2-e 阈值规则 | Phase 2B 在 [0.3967, 0.4383] 内由 owner 选定；建议中点 0.4125（= control + 0.5×可分离区间，round 4），不得低于 control+0.02、不得高于 O_store_ach−0.01 | 预注册 §6 建议规则 |
| Q2-f 预算 | Phase 2A **0 LLM / 0 token**（本目录即为交付，已满足）；Phase 2B ≤158,521 judge/al3 token（72,521+86,000），且总预算仍受 1,500,000/400 硬上界 | 预注册 §6/§7 |

C 候选补充披露：C 覆盖 0.7465 < 95%，其 control（C1=0.2433、C3=0.2016）与 oracle（O_store=0.7667）**仅作敏感性参考，不得单独作结论**。

## 4. 停止条件核查（本阶段）

| # | 停止条件（任务 §7） | 结果 |
|---|---|---|
| 1 | baseline 非 150 例或 SHA 不符 | 未触发（150 例，SHA `5cd71261507a…`） |
| 2 | runtime map ≠ 2,947 或 mapping ≠ 1,006 | 未触发 |
| 3 | 需要 LLM/网络 | 未触发（全程离线） |
| 4 | 需要改 src/ 或 evaluation/ | 未触发（只读导入生产加载路径，未改动） |
| 5 | 任一候选覆盖率 < 95% 时被当作主口径 | 未触发（C 仅作敏感性报告） |
| — | O_store_ach − control < 0.02 → NO_SEPARABLE_BAND | 未触发（见 §2 判定列） |

## 5. 声明

- 未跑模型：未调用 LLM、未联网、未跑 judge/al3、未生成任何答案；所有数字为 a′ baseline 与 Phase 1 映射的离线复算。
- 未 commit、未 push；产物留在 worktree `eval/m6a-phase2a-2026-11-01`，由父会话复核。
- 未修改 `src/`、`evaluation/`、`plans/`、`docs/`、`CHANGELOG`、数据集、store 与产品默认；本阶段唯一新增代码为 `scripts/audit/phase2a_oracle.py`。
- 运行时真值（v2.1 `relevant_chunk_ids`）仅用于离线比对与 oracle 计算，未写回产品、未用于调阈值。
- 本文件只给建议，Q2-a..f 最终口径与阈值由 owner 签批。
