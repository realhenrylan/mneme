# 答案级评测线 M6a 配对重放附录（a′）：单次基线生成 + 离线引用选择

- 日期：2026-11-01
- 状态：**已批准（2026-11-01，owner 会话确认；手写签名待补）** —— Q2-a..d 已签，执行按 §五；产品默认变更仍须另行批示
- 签批：2026-11-01（owner 在会话中确认「按a签」；Q2-a..d 见 §九）
- 上游：[M6a 预注册](./ANSWER-LEVEL-M6a-CITATION-QUALITY-PREREGISTRATION-2026-10-31.md)（2026-11-01 已签批，C1/C2/C3 与预算冻结）
- 触发：M6a 正式评测 `INVALID_VARIABLE_LEAK`（产物在本地分支 `eval/m6a-2026-11-01 @ 48ff45e`，未 push；本文件不链接未合并分支文件）
- 本附录只替代原预注册 §八 的步骤 2–3；C1/C2/C3 阈值、预算硬上界、冻结边界、泄漏禁令不变
- 一句话：**不再重新生成处理臂正文**；先生成一次带完整有序 context 的基线，再对同一批基线答案离线调用 `retarget_citations`，只改 `[S#]`

---

## 一、为什么原 (a) 不能直接执行

原建议是“用控制臂 `m4c-arm2-2026-09-06/outcomes.jsonl` 的 150 条答案做离线配对重放”。复核后发现控制臂产物**没有保存完整有序 context**：

- `evaluation/generation_runner.py:320` 把 `context` 落盘为 `sources[:500]`，只保留前 500 字符；完整 `sources` 未入库。
- `context_chunk_ids` 是 `sorted({...})`（`generation_runner.py:287-289`），只保留**集合**，丢失 `S1..Sn` 的 rank 顺序。
- `retarget_citations` 需要**有序**的 `citation_ids` 与等长的完整 `chunk_texts`；仅凭 500 字符前缀、排序后的 chunk ID 集合和 cited 的 `evidence`，无法还原全部 S# 槽位与候选 chunk 文本。
- 不能把排序后的 ID 强行当作 rank 顺序：那会把 `[S3]` 指向错误的 chunk，产物不可信。
- 也不能用 M6a 处理臂的 `outcomes` 代替：同一字段同样截断 500 字符，且它是处理臂，不是基线。

因此，**沿用密封 M4c 控制臂做离线重放不可行**；需要一次新的基线生成，但**不需要第二次生成处理臂**。

---

## 二、a′ 设计：一次基线生成 + 离线配对处理

### 2.1 基线生成（只生成一次）

- 数据集：v2.1 全 150 例；配置与臂2 一致（`RAG_REFUSAL_THRESHOLD=0.015`、`RAG_DYNAMIC_MIN_K=25`、`RAG_CONTEXT_MAX_K=25`、`RAG_CONTEXT_TOKEN_BUDGET=7000`、温度 0.1）。
- 模型/协议：`deepseek-chat`、`al1-containment-v1`；不启用 M6a hook（基线必须是**未重定向**的原始答案）。
- 分支安排：基线从 `1eef4c9`（无 M6a hook）建评测分支，只叠加 `evaluation/` 的 capture 改动；离线配对脚本从 `614e260` 只读复制/导入 `src/citation_selection.py`，不把 hook 接回 `src/rag.py`。基线代码与配对代码分离，避免“基线无意中跑处理臂”。
- 与 M4c 控制臂的区别：这是一次**新的基线运行**，不是密封 M4c 控制臂；M4c 仍作为历史参照，不得改写、重算、重新密封。C1 基线以本附录的基线运行复算，并在报告中同时披露 M4c 历史值 0.0456。
- 关键新增：评测侧捕获**完整有序 context**，至少包括：
  - `context_chunk_ids_ordered`：与 `S1..Sn` 一一对应的 chunk_id 顺序；
  - `context_chunk_texts`：与 `S1..Sn` 一一对应的完整 chunk 文本；
  - 或等价的完整 `sources` 原文（可由 `S#` 解析回顺序与文本）。
- 该捕获只改 `evaluation/` 的落盘，不改 `src/rag.py` 的生成行为；不得改变答案、sources、检索、提示词。

### 2.2 离线配对处理

对基线 `outcomes.jsonl` 的每个 case：

1. 读取基线 `answer`、有序 `citation_ids`（`S1..Sn`）、有序 `chunk_texts`；
2. 直接调用 M6a 已冻结的 `src/citation_selection.py::retarget_citations(answer, citation_ids, chunk_texts)`；
3. 写 paired outcome：答案只可能改变 `[S#]` 内部数字；`sources` 列表与槽位数不变；
4. 记录逐例 `stats`（`examined/retargeted/unchanged/invalid/slots_before/slots_after/groups/fail_closed`）与槽位归因（`add/retarget/delete`）；
5. **不调用任何模型**；不读 `relevant_chunk_ids` 等真值字段；真值只在离线裁决脚本读取。

### 2.3 一致性断言（替代原步骤 3）

- 对 150 例剥离 `[S#]` 后，paired answer 必须与 baseline answer **逐字节一致**；不一致 → 运行作废，不裁决。
- 槽位数必须 150/150 不变；若 `slots_after != slots_before` 任一例 → 变量越界，作废。
- `add` 必须为 0、`delete` 必须为 0；`retarget` 可为正。若出现 `add/delete` → 变量越界，作废。
- 因为 base answer 相同，上述断言在设计上应 150/150 通过；断言仍须机械执行并落盘。

---

## 三、指标与判据（不变）

- C1：citation recall（分母冻结 150）≥ **0.10**。
- C2：修正率（partial=0.5）≥ **0.55** ∧ 语义拒答（al3 v1.1）≥ **0.90**。
- C3：citation precision ≥ **0.0400** ∧ `fabricated = 0` ∧ `retrieved_not_in_context = 0`。
- 裁决：C1 ∧ C2 ∧ C3 → `PASS`；任一不满足 → `FAIL`；互不抵扣。
- `PASS_WITH_WARNING`：主选 A 下不触发；若 `retarget > 0`，视为触及选择逻辑；`add > 0` 按变量越界作废。

### 3.1 C2/G2′ 的取数

- 基线答案与 paired 答案在剥离 `[S#]` 后逐字节一致，因此答案要点判定应不变。
- 优先在**基线**上运行 judge（154 要点面）与 al3（28 探针 ×2 轮），把结果作为 C2/G2′ 的守卫值；paired 侧不重复跑，报告中披露“引用令牌不同、正文相同”的事实。
- 若 judge 实现会读取 `[S#]` 令牌并因此改变判定，则只对受影响的点补判；补判调用与 token 计入总预算，且不得改变 C2 公式。
- 任何情况下不得用 paired 处理臂输出回头调规则或阈值。

---

## 四、评测侧改动范围（仅 evaluation/）

允许新增/修改：

- `evaluation/generation_runner.py`：增加可选 `capture_full_context`（默认 off），在结果中落盘有序 `context_chunk_ids_ordered` / `context_chunk_texts`；不得改变默认行为。
- `scripts/m6a_paired_replay.py`：离线读取基线 outcomes，调用已冻结的 `retarget_citations`，写 paired outcomes 与 stats。
- `scripts/m6a_preflight.py` / `m6a_consistency_check.py` / `m6a_gate_decision.py`：按本附录扩展输入；不改变判据算法。

禁止：

- 不改 `src/rag.py`、`src/citation_selection.py`、`src/config.py`、检索/reranker/提示词/拒答。
- 不改 trace schema、consent 语义、产品默认。
- 不改 M4c 密封产物、M6a 预注册原文、M6a 实现提交 `614e260`。

---

## 五、执行步骤（签批后一次性）

| 步骤 | 动作 | 退出条件 |
| --- | --- | --- |
| 0 预检 | 工作树干净、HEAD 锁定；校验 M4c 三哈希（仅作历史参照）；复算 0.0456/0.0400；确认臂2 配置；确认 `src/citation_selection.py` 哈希与 `614e260` 一致；确认 capture 开关默认 off | 全部通过；任一失败停止 |
| 1 基线生成 | 150 例生成一次，M6a hook 关闭；开启 `capture_full_context`；密封 `outcomes.jsonl`/`manifest.json` | `cases_failed=0`；有序 context 150/150 非空；token 记录 |
| 2 离线配对 | 对基线答案逐例调用 `retarget_citations`；写 paired outcomes + stats | 150/150 产出；无模型调用 |
| 3 一致性 | 剥离 `[S#]` 逐字节比较；槽位数、add/delete 检查 | 150/150 一致；add=0、delete=0；否则作废 |
| 4 C1/C3 | 用 `evaluation/citation_metrics.py` 契约 v2 复算 paired outcomes 的 recall/precision/fabricated/retrieved_not_in_context | 输出 C1/C3 数值 |
| 5 C2/G2′ | 在基线上跑 judge（154 点）与 al3（28×2）；按 §3.1 处理 | 输出修正率与语义拒答；披露一致率 |
| 6 裁决 | 机械读取三份密封产物；输出 C1/C2/C3、U/G、槽位归因与 PASS/FAIL | 无人工改数 |
| 7 归档 | 产物落 `results/answer-level/m6a-paired-2026-11-01/`；manifest 自哈希 | 可复验 |

---

## 六、预算

| 项 | 上界（token） | 调用 |
| --- | ---: | ---: |
| 基线 150 例 ×1 次生成 | 1,180,703 | 150 |
| judge 基线 154 点 | ≤72,521 | ≤180 |
| al3 28 探针 ×2 轮 | ≤86,000 | ≤60 |
| **合计** | **≤1,339,224** | **≤390** |
| 硬上界 | **1,500,000** | **400** |

- 离线配对 `retarget_citations` **0 token / 0 调用**。
- 若基线生成 token 超出 1,180,703，按实际记录累计；总量触及 1,500,000 或 400 调用即停，报告 `BUDGET_EXCEEDED`，不得用部分结果裁决。
- 不补跑、不重跑、不换种子；基线 150 例只生成一次。

---

## 七、产物与 manifest

目录：`results/answer-level/m6a-paired-2026-11-01/`

至少包含：

- `outcomes.jsonl`（基线）、`outcomes-paired.jsonl`（配对处理）；
- `manifest.json`（自哈希）：记录 git commit、有效 `RAG_*` 配置、dataset SHA、基线/配对 outcomes SHA、manifest SHA、metric/protocol 版本、M6a 实现文件 SHA、judge/al3 token 与调用数、capture 开关；
- `consistency.json`（150/150、槽位、add/retarget/delete）；
- `report.json` / `report.md`（C1/C2/C3、U/G、槽位归因、PASS/FAIL）；
- 评测脚本副本与运行日志。

---

## 八、风险与限制

1. **新基线不等于 M4c 控制臂**：本附录用一次新的基线生成替代密封 M4c 控制臂；C1 基线以新基线复算，M4c 0.0456 仅作历史参照。这是治理上的实质变更，须 owner 在本附录签批。
2. **基线成本**：仍需 1.18M 生成 token；但不再生成处理臂，总预算与原预注册相同，未增加。
3. **C2/G2′ 的引用敏感性**：若 judge 读取 `[S#]`，按 §3.1 只补判受影响点；不得因此改 C2 阈值。
4. **capture 只改评测落盘**：必须确认默认 off、生成行为不变；若 capture 改变答案或 sources，作废。
5. **单次生成仍受温度 0.1 影响**：但 baseline 与 paired 共用同一批答案，配对性由构造保证，不再受二次采样影响。
6. **不改变产品默认**：本附录即使 PASS 也不切换默认、不 push；默认变更须 owner 另行批示。

---

## 九、owner 签批表（2026-11-01 已签；手写签名待补）

| 编号 | 批准事项 | 本附录提议 | 签署 | 日期 |
| --- | --- | --- | --- | --- |
| **Q2-a** | 批准 a′：以一次新的基线生成替代密封 M4c 控制臂，离线配对应用 M6a | 批准；M4c 仅历史参照 | 批准（2026-11-01，会话确认） | 2026-11-01 |
| **Q2-b** | 批准评测侧新增 `capture_full_context`（默认 off）与离线配对脚本 | 批准；只改 evaluation/，不改 src/ | 批准（2026-11-01，会话确认） | 2026-11-01 |
| **Q2-c** | 批准预算：基线 1,180,703 + judge ≤72,521 + al3 ≤86,000，总量 ≤1,339,224/390，硬上界 1.5M/400 | 批准 | 批准（2026-11-01，会话确认） | 2026-11-01 |
| **Q2-d** | 确认 C1/C2/C3 与原预注册一致，不因本次方法修正而调整 | 确认 | 批准（2026-11-01，会话确认） | 2026-11-01 |

**签批说明**：

- Q2-a..d 已于 2026-11-01 签署；签批后 §二–§五 的 a′ 方法、评测侧改动范围与预算冻结。
- 本附录与原预注册共同构成 M6a 的评测协议；原预注册 §八步骤 2–3 由本附录 §五步骤 1–3 替代，其余条款继续有效。
- 签批不等于产品默认切换；即使 PASS，也不自动改默认，须 owner 另行批示。

| 项目 | 内容 |
| --- | --- |
| 备注 | owner 于 2026-11-01 在会话中确认「按a签」；由 agent 据会话记录落字，手写签名待 owner 补签。 |
| owner 签名 | （待手签） |
| 签批日期 | 2026-11-01 |
