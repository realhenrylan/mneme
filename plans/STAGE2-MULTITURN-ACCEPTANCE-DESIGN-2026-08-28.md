# Stage 2 立项设计：多轮效果验收优先（2.4）+ 摄取降级路径显式化（2.1）

> 日期：2026-08-28
> 状态：**已批准并实施完毕**（2026-08-28 owner 批示「都可以」＝方案 A 立项 +
> §4.1 阈值冻结；M2-M5 全部执行，门禁判定 `STAGE2_24_ACCEPTED`，
> 验收报告 `results/stage2-multiturn/report-2026-08-28.md`）
> 上游依据：`plans/RAG-IMPROVEMENT-PLAN-2026-08-01.md` §四（阶段 2）
> 遵循流程：探索上下文 → 澄清问题 → 方案对比 → 设计呈现 → **审批** → 设计文档（即本文）→ 实施

---

## 一、现状盘点（2026-08-28 探索结论）

阶段 2 四个子项的**代码均已落地**，卡点全部是「效果验收未闭环」而非「功能未实现」：

| 子项 | 已有 | 剩余缺口 |
| --- | --- | --- |
| 2.1 标准文档模型 | `Document/Section/Chunk` 模型、`src/loaders/`（PDF/DOCX/text）、结构化分块已在生产路径 | 旧字符切分**降级路径**仍在 `src/rag.py:1407-1466`（新 loader 失败时静默切回，含 `traceback.print_exc()` 调试残留）；格式/质量提示端到端验收未做 |
| 2.2 Parent-Child/邻接 | `src/chunking.py`（`chunk_document`/`expand_with_parent`/`expand_with_adjacent`）受回归保护 | 无「有/无 parent-child context recall 净收益」结论 |
| 2.3 PDF/DOCX 重点解析 | 标题层级、表格、低质量检测（`document.is_low_quality`）、回退路径 | 真实格式低质量率/失败可见性/TUI 回退的门禁验收未做 |
| 2.4 多轮检索改写 | history-aware rewrite（`src/rag_query_rewriter.py`）+ decompose + 原 query 保底召回**已在线**：history 同时进检索与生成 | 效果未证明——P1.1 确认的「trace 不可复放」遗留项 |

**验收基础设施盘点（比预期完备）**：

- v1 评测集已有多轮子集：10 例、3 条追问链（南京 zh×3、DSpark en×3、OneDrive en×4），
  `metadata.follow_up_to` / `turn` 字段齐全。
- `evaluation/compare.py` 已实现多轮回放：`build_conversation_chains`（follow_up_to 链）、
  `canonical_history_for_turn`（同臂前序轮次真实回答作 canonical history）、保链切分、
  `rewrite_query_llm(case.query, history=history)`。
- 指标函数现成：`recall_at_k` / `source_recall_at_k` / `context_source_recall` /
  chunk 级 `context_recall`（`evaluation/metrics.py`）。
- P1.1 的 210 条 trace 为单轮批量查询，对 2.4 **无复用价值**（缺真实多轮会话）；
  2.4 必须走受控 A/B。

---

## 二、澄清问题与默认裁定

以下四问已呈报 owner；本轮未收到批示，**按推荐默认继续**（均可被 owner 事后推翻，
推翻即修订本文档再实施）：

| # | 问题 | 默认裁定（推荐项） |
| --- | --- | --- |
| Q1 | Stage 2 主目标选哪个子项 | **多轮效果验收 2.4 优先**（基础设施最完备、成本最低、最快闭环一个 [~]） |
| Q2 | 「显著优于基线」判据 | **预注册保守阈值**（样本小，防事后解释；不达标如实记录不通过） |
| Q3 | 旧降级路径处置 | **保留但显式可见**（结构化 warning + 降级标记可追溯；不删路径，避免可用性回退） |
| Q4 | A/B 基线口径 | **history=None 纯单轮**为主门禁；「history 只进生成」作诊断臂（不设门） |

---

## 三、方案对比

### 方案 A：多轮验收优先（推荐，本文档采用）

范围 = 2.4 效果验收（主）+ 2.1 降级路径显式化（辅，小改动）。
理由：四项中唯一「基础设施已就绪、只差一次受控实验」的子项；且多轮 rewrite 是
生产已在线行为，**有被未知伤害的可能性**（rewrite 错误改写会污染检索），无论验收
结论如何都有决策价值。2.2/2.3 的验收依赖更大规模的标注与门禁建设，留待后续轮次。

### 方案 B：摄取质量收尾优先（2.1+2.3）

范围 = 删降级路径 + 低质量门禁/TUI 提示验收。价值真实但需要真实格式语料样本与
门禁设计，且不回答任何「效果」问题——本轮结束四个 [~] 最多变两个半。

### 方案 C：四项全做（2.4 → 2.2 → 2.1/2.3）

一次性收口整个阶段 2。周期最长（预计 2-3 周），且 2.2 的 parent-child A/B 与
2.4 共享评测基建，存在「基建未稳连跑两个实验」的返工风险。不推荐本轮采用；
若 2.4 顺利闭环，2.2 可顺势复用同一套 harness 作为下一轮。

---

## 四、详细设计（方案 A）

### 4.1 实验设计：多轮 rewrite 受控 A/B（主项）

**测试集**：v1 多轮子集全部 10 例（3 链）。链内顺序回放：turn-1 无历史，
三臂**机械同态**（history 为空 ⇒ `should_rewrite` 恒 False ⇒ 无 rewrite），
故 turn-1（multi-001/004/007，n=3）不计入对比，只进逐例报告；
**有效对比集 = 7 条追问**（multi-002/003/005/006/008/009/010）。

**三臂**（canonical history 均取同臂前序轮次的真实回答，臂内自洽）：

| 臂 | 检索 rewrite | 生成注入 history | 含义 |
| --- | --- | --- | --- |
| A 基线 | 关（history=None） | 无 | 旧「检索只用当前 query」纯单轮行为 |
| B 诊断 | 关 | 有 | 「历史只进生成」的旧生产形态 |
| C 处理 | 开（生产现状） | 有 | 「历史进检索 + 进生成」 |

主门禁只比 **A vs C**（单因子）；B vs C 差值 = 「历史进检索」净贡献，仅诊断不设门。

**指标（预注册，跑前冻结）**：

- **主指标**：逐例 source 级 recall（`source_recall@k`，k=该次检索生产实际保留数）
  在 7 条追问上的**均值**。
- 次指标：chunk 级 `context_recall`（relevant_chunks 落入最终 context 比例）、
  `recall@k` 原始值。
- 诊断量：rewrite 触发率与改写率（`rewrite_log.changed`）、漂移防护原 query 路
  合并贡献、拒答计数（多轮子集 should_refuse 全 False，出现拒答即异常信号）。

**门禁（预注册）**：

| 判定 | 条件（7 条追问上） | 门禁名 |
| --- | --- | --- |
| 通过 | mean(C) ≥ mean(A) + 0.10 **且** 无单例 C < A − 0.05 | `STAGE2_24_ACCEPTED` |
| 未证明 | C ≥ A 但未达上述阈值 | `STAGE2_24_NOT_PROVEN`（2.4 保持 [~]） |
| 回归 | mean(C) < mean(A) | `STAGE2_24_REGRESSION`（rewrite 伤害追问，转产品线修复项） |

样本量披露：n=7 属方向性证据，本门禁**不做显著性检验表演**；报告须明示该局限。
阈值一经冻结不得回调（与 P1.1 预注册纪律同源）。

### 4.2 harness 扩展（唯一代码主项）

- 新增薄执行器 `evaluation/multiturn_replay.py`：**只 import 复用**
  `compare.py` 的 chain/history/指标函数与 `rag_query_rewriter`，不改写
  compare.py 既有路径（P0 框架保持零风险）。臂语义 = history 路由参数
  （A：生成与 rewrite 均不传；B：仅生成传；C：均传）。
- 输出密封产物 `results/stage2-multiturn/`：逐例逐臂 JSONL + 决策报告 md +
  manifest（自 SHA256，沿用 v2 治理的 manifest 约定）。
- TDD：先写 arm 路由与 canonical history 装配的失败测试（fake LLM/检索），
  再实现；真实跑一次全链冒烟后密封。

### 4.3 辅项：2.1 降级路径显式化（单一职责小改动）

`src/rag.py` `_load_index_chunks` 异常分支：

1. 移除 `traceback.print_exc()` 调试残留；
2. 降级 warning 结构化：文件类型、来源名、异常类型+摘要（不打印堆栈）；
3. source record 增记 `parse_degraded: true`（落入既有 index manifest，
   满足 2.1「可追溯」验收口径）。

行为不变量：降级后索引照常建成（不 fail-fast），回答路径零影响。
TDD：monkeypatch loader 抛错 → 断言警告文案含异常摘要、无堆栈输出、
manifest 记录 degraded 标记、索引块数与旧路径一致。

### 4.4 里程碑与门禁顺序

| 序 | 事项 | 产出 |
| --- | --- | --- |
| M1 | 本设计审批 + 判据冻结 | 预注册生效 |
| M2 | harness 扩展（TDD） | `evaluation/multiturn_replay.py` + 测试 |
| M3 | 2.1 降级路径显式化（TDD） | `src/rag.py` 小改 + 测试 |
| M4 | 正式 A/B/C 真实跑（真实 LLM，离线 embedding） | sealed results + 报告 |
| M5 | 门禁判定 → 路线图状态更新 + CHANGELOG + 提交 | 2.4 [~]→[x] 仅当 `STAGE2_24_ACCEPTED` |

预估 LLM 成本：≈30 次回答生成 + ≈14 次 rewrite（含链内顺序依赖），量级与 P0
单臂实验相当。

### 4.5 边界与红线

- v1 数据集**现有行零改写**；扩多轮例属独立立项（不与本次验收混做）。
- v2.0.11 冻结树、P1.1 trace 库不受本设计触碰。
- 全程不 stage/commit/push trace 数据与 consent.json（owner push-safety mandate）。
- B/C 臂 canonical history 含模型生成回答，属实验产物，仅落 sealed results，
  不回流评测集。

---

## 五、审批请求

请 owner 裁定：**① 方案 A 是否立项**（或改选 B/C）；**② §4.1 门禁阈值是否冻结**。
批准后从 M2 开始实施；若对 §二 默认裁定有推翻，先修订本文档对应条目。

---

## 六、实施记录（2026-08-28 收官）

- **M2**：`evaluation/multiturn_replay.py` + `tests/test_multiturn_replay.py`（TDD，RED 20 failed → GREEN 20/20）。
- **M3**：`src/rag.py` 降级路径显式化 + `tests/test_rag_degraded_parse_path.py`（RED 1 failed → GREEN 3/3）。
- **全量回归**：2751 passed / 8 skipped / 0 failed（exit 0）。
- **M4**：真实 A/B/C（沙箱 `MNEME_DATA_DIR`、离线 embedding）→
  `results/stage2-multiturn/run-2026-08-28/`（manifest 自哈希复算 OK）+ 决策报告。
- **M5 门禁判定**：mean_delta +0.1429 ≥ 0.10 且 worst_case_delta 0.00 →
  **`STAGE2_24_ACCEPTED`**；路线图 2.4 `[~]` → `[x]`。
