# M6a Phase 2A：映射口径与 oracle 预注册（草稿）

- 日期：2026-11-01
- 状态：**草稿，待 owner 签批；未执行、未改代码**
- 关系：承接 `docs/AUDIT-CHUNK-DOMAIN-2026-11-01.md` 与 `results/answer-level/chunk-domain-audit-2026-11-01/report.md`；**不替代** M6a 预注册，只决定 Phase 2B 的映射、指标与上界。
- 一句话：Phase 1 已证明 runtime 域有信号，但旧的 0.0456/0.10/0.0400/0.2067/U=21 全部作废；本文件先冻结“怎么映射、用哪个分母、oracle 多高”，再由 owner 另签 Phase 2B 的 C1/C3 阈值。

---

## 1. 背景与已确认事实

- store 域：`data/v2-corpus/chunks/`，v2.0.0 Recursive，**1,006 chunks**。
- runtime 域：`src.chunking` v3 section/child，**2,947 chunks**；a′ 的 ordered IDs 3,108/3,108 可解析。
- 映射覆盖率 1.00；一对多 930；歧义 16；主口径 `ratio_runtime` t=0.50 条件覆盖率 98.5%。
- `mean_rel_runtime_size=2.58`：一个 store truth 平均映射 2.58 个 runtime chunk。
- 旧 `recall=0.0456` 是跨域 ID 交集伪值；新 `recall_evi=0.2510` 的分母是映射后的 runtime truth，**不是**旧口径；`store_hit_recall_evi=0.3878` 才是按 store truth 分母的近似对应值。
- a′ 可用 runtime map 全文离线重放；`full_sources` 仅 snippet，capture 修复不是 C1/C3 重放的前置条件。

---

## 2. 目标与非目标

**目标**

1. 冻结 store truth → runtime chunk 的映射策略与阈值。
2. 冻结 C1（recall）/C3（precision）的分母与主指标。
3. 在 a′ baseline 上计算 M6a 的 **oracle 上界**（只重定向既有槽位）。
4. 给出 control 与 oracle 之间的可分离区间；若不存在，明确停止 M6a。

**非目标**

- 不跑 LLM、不生成答案、不跑 judge/al3、不产出 M6a PASS/FAIL。
- 不改 `src/`、不改产品默认、不改数据集、不改 store。
- 不重新定义 C2/G2′；C2/G2′ 仍按已签预注册，Phase 2B 只决定是否复用控制臂判定。

---

## 3. 映射策略（三选一，owner 签 Q1）

| 方案 | 规则 | 已知覆盖 | 优点 | 风险 |
|---|---|---|---:|---|
| **A. 单边 runtime** | `overlap / runtime_span_len ≥ 0.50` | 98.5% | 覆盖高，短 runtime 子块可命中长 truth | 短子块完全落入长 truth 即算命中，precision/recall 偏宽松 |
| **B. 双边（推荐优先评估）** | `overlap/runtime_len ≥ 0.50` **且** `overlap/store_len ≥ 0.50` | 待 Phase 2A 计算 | 防止短子块单边膨胀；更接近“同一证据区域” | 覆盖可能 <95%，需先算；长 store chunk 可能只剩少数 runtime 候选 |
| C. 单边 store | `overlap / store_span_len ≥ 0.50` | 74.7% | 要求 runtime 覆盖大部分 store truth | 覆盖 <95%，已判定不可作主口径 |

**决策规则**：

1. 先计算 B 的条件覆盖率；若 ≥95%，**主口径用 B**。
2. 若 B <95%，回退 A，但必须在 Phase 2B 报告中披露“单边宽松”并附 B/C 敏感性。
3. C 一律只作敏感性，不作主口径。
4. 歧义（≥2 候选各 ≥50%）不自动合并；按候选集合处理，记录歧义例数。

---

## 4. 指标定义（owner 签 Q2）

对每个 case：

- `T_store` = dataset `relevant_chunk_ids`（store 域）。
- `T_rt` = 经 §3 映射后的 runtime chunk 集合（可能一对多）。
- `S` = 答案引用的 supported runtime chunk 集合（`citation_metrics.evidence` 中 `supported_chunk`/`supported_source`）。
- `Ctx` = `context_chunk_ids`。

**主指标（推荐）**

- **C1 = `store_hit_recall_evi`**：对每个 store truth chunk，若其映射候选中有任一被 `S` 引用，记 1；`recall = hits / |T_store|`；逐例后对 150 例求均值。
  - 理由：分母是 store truth，最接近旧口径；一对多不改变分母；仍是“任一子块命中”的宽松口径，需在报告中注明。
- **C3 = `precision_evi`**：`|S ∩ T_rt| / |S|`；逐例后对 150 例求均值。
  - 理由：precision 的分母是引用数，不受 truth 映射分母影响；一对多会扩大 truth 区域，需注明“区域级精度”。

**辅助指标（必须并列，不参与裁决）**

- `recall_evi`（分母 `|T_rt|`）：更细的 runtime truth 覆盖，但会因一对多改变分母。
- `recall_ctx` / `precision_ctx`：context 检索面，不是引用面。
- `case_any_overlap`：案例级覆盖，便于与旧 0.2067 的“案例级”直觉对照。
- `mean_rel_runtime_size`、`truth_chunks_unmapped_rate`、歧义数。

**分母冻结**：150 例；空 truth/空引用按 0；逐例均值 round 4（与旧 `citation_metrics` 一致）。

---

## 5. oracle 上界（owner 签 Q3）

M6a 只允许**重定向既有 `[S#]` 槽位**，不新增/删除。对每个 case：

- `m` = 答案中既有引用槽位数（`context_chunk_ids_ordered` 中实际被引用/可重定向的槽位数；实现规格已冻结）。
- `T_store`、`T_rt` 同上。
- `oracle_store_hit = min(m, |T_store|) / |T_store|`。
- `oracle_recall_evi = min(m, |T_rt|) / |T_rt|`。
- 对 150 例求均值，得到 `O_store`、`O_evi`。

**约束**：oracle 只允许每个槽位指向一个 truth 候选，不得一个槽位同时命中多个；不得新增槽位；不得读取运行时真值（离线计算，不进入产品）。

**输出**：

- control（a′ baseline）的 C1/C3；
- `O_store`、`O_evi`；
- `O - control` 的可分离区间；
- 若 `O_store - control < 0.02`，判定“无足够区分空间”，M6a 停止，不进入 Phase 2B。

---

## 6. 阈值重签规则（owner 签 Q4）

Phase 2A 只产出区间，不在本文件里写死最终 C1/C3；Phase 2B 由 owner 在区间内选择。

建议规则（供 owner 选择）：

- **C1（主）**：取 `control + 0.5 × (O_store - control)`，round 4；不得低于 `control + 0.02`，不得高于 `O_store - 0.01`。
- **C3（守卫）**：`precision_evi ≥ control_precision - 0.01`（非劣），且 fabricated=0、retrieved_not_in_context=0；后两项需 capture 修复或 runtime-map 文本核验，若本轮不能验证，C3 降级为“precision 非劣 + 两项标记未验证”，不得宣称完整 C3。
- **C2/G2′**：若 judge/al3 的输入在剥离 `[S#]` 后与控制臂逐字节一致，复用控制臂判定；否则只补判 66 miss + al3 两轮，预算上限 72,521 + 86,000 token。
- **互不抵扣**：C1∧C2∧C3 才 PASS；任一失败即 FAIL。

---

## 7. 预算与边界

- Phase 2A：**0 LLM / 0 token / 0 调用**（纯离线 oracle 与映射）。
- Phase 2B：**0 新生成**（复用 a′ baseline）；judge/al3 上限 158,521 token；总预算仍受 1,500,000/400 硬上界约束。
- 不改 `src/`、不改产品默认、不 push；Phase 2A 产物本地提交需 owner 明确。
- 不读运行时真值进入产品；truth 只在离线脚本。

---

## 8. 产物

Phase 2A 产出目录：`results/answer-level/m6a-phase2a-2026-11-01/`

- `mapping-policy.json`：选定方案、阈值、覆盖率、歧义数。
- `oracle.json`：每例 `m`、`|T_store|`、`|T_rt|`、`oracle_store_hit`、`oracle_recall_evi`、聚合。
- `report.md`：control vs oracle 表、可分离区间、停止/继续建议。
- `manifest.json`：自哈希；记录 git commit、a′ baseline SHA、runtime map SHA、脚本 SHA。
- 脚本：`scripts/audit/phase2a_oracle.py`（只读）。

---

## 9. 停止条件

任一触发即停止，不进入 Phase 2B：

1. B 方案覆盖率 <95% 且 owner 不接受 A 的单边口径；
2. `O_store - control < 0.02`（无足够区分空间）；
3. oracle 计算需要读取运行时真值或修改 `src/`；
4. 需要新生成答案（a′ baseline 不可用）；
5. 任何步骤需要 LLM/网络。

---

## 10. owner 签批表

| 编号 | 待签事项 | 提议 | 签署 | 日期 |
|---|---|---|---|---|
| Q2-a | 映射策略 | 优先 B（双边）；B 覆盖 <95% 时回退 A，附敏感性 |  |  |
| Q2-b | C1 主指标 | `store_hit_recall_evi`（分母 store truth） |  |  |
| Q2-c | C3 主指标 | `precision_evi`；非劣 + fabricated/retrieved 标记 |  |  |
| Q2-d | oracle 方法 | `min(m, truth)/truth`，逐例均值；不新增槽位 |  |  |
| Q2-e | 阈值规则 | Phase 2B 在 control 与 oracle 区间内由 owner 选定 |  |  |
| Q2-f | 预算 | Phase 2A 0 LLM；Phase 2B ≤158,521 judge/al3 |  |  |

**签批说明**：本文件是 Phase 2A 的设计批准，不是 M6a 实施批准；签批后仍不得改产品默认、不得 push；Phase 2B 需另立附录。
