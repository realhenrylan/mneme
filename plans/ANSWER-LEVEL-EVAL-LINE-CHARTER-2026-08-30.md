# 答案级评测线立项章程（设计提案）

- 日期：2026-08-30
- 状态：**待 owner 审批——批准前不进入任何实施**
- 前置依赖：评测 runner 已默认切 v2.1（commit 0b5866c，v2.1.jsonl 可被 `load_dataset` 直接消费、`relevant_chunk_ids` 已成为一等字段）
- 关联：2.4 多轮验收（source 级通过≠答案正确）、P1.1 分析（M2 相关性错位置 out of scope 并移交本线）、v2.1 激活（dd66b09）

---

## 一、动机：为什么需要答案级评测线

1. **2.4 验收的关键教训**：多轮 C 臂门禁增量全部来自 multi-010 拒答翻转，「source 级通过 ≠ 答案正确」——证据进场了，答案本身对不对，现有指标不回答。
2. **P1.1 分析的移交**：M2 相关性错位因缺标注判 out of scope，结论明确「未来量化需引入答案级评测」——本线是该移交的承接载体。
3. **指标断层（核心缺口）**：现有全部指标止步于证据层——
   - 检索层：`evaluation/run.py` recall/mrr（v2.1 已切默认）；
   - 引用层：citation 契约 v2 context-aware（citation_id_validity / precision / recall）；
   - 「faithfulness」：`citation_metrics.compute_faithfulness` 实为**答案要点术语 vs context** 的证据覆盖启发式（≥50% 术语命中即算支持），生成答案文本作为参数传入但**不参与判定**；
   - 即：**「生成答案文本是否命中 acceptable_answer_points」目前没有任何指标覆盖**。
4. **真值已就绪**：v2.1 激活后，122 条可答例均带人工终审确认的 `acceptable_answer_points`（含权威 `relevant_chunk_ids`），28 条拒答探针带 `should_refuse` 真值——答案级评测的 ground truth 首次完整可用。

## 二、现状盘点与缺口表

| 资产 | 状态 | 缺口 |
| --- | --- | --- |
| `evaluation/generation_runner.py` | 已有：走生产 `answer_query` 全链（rewrite/decompose/扩展/citation 校验）、citation 契约 v2、refusal precision / false refusal rate、token 统计 | **G3** 库式无 CLI 入口、无密封产物规范（对比 run-3 的自哈希 manifest 范式） |
| `evaluation/citation_metrics.py` | 已有：确定性 faithfulness（证据覆盖启发式，docstring 自认 LLM judge 是 future work） | **G1** 答案要点命中率（answer text vs points）缺失；**G2** 无 LLM judge 协议 |
| v2.1 数据集 | 已激活：150 例权威真值 | 拒答探针 28 例的生成级行为基线未跑过 |
| 成本治理 | 无 | **G4** 无 token 预算/停损/cadence 约定 |

## 三、目标与非目标

**目标**
1. 建立可复现的答案级基线：答案要点命中率（answer-hit）、拒答正确率（生成级）、引用契约 v2 联合报告——**第一轮纯诊断性，不设产品门禁**。
2. 设计并验证受约束 LLM judge 协议（G2），并把 judge 自身的契约错误率作为被测对象如实统计。
3. 成本可控：预算前置、单轮跑完即停、密封产物可复核。

**非目标**
- 不改产品检索/生成策略（本线只测量）；
- 第一轮不设任何产品门禁（阈值门禁须第二轮预注册后另行提案）；
- 不动冻结资产（v1、v2.0.x 修订树、sealed 产物零触碰）；
- 不迁移 v1 数据集；不改 v2.1 数据集文件。

## 四、方案对比（三选一，推荐 B）

### 方案 A：纯机械线
answer-hit 判定复用 containment 思路：要点文本空白归一后被答案文本包含（run-3 仪器同族，含空要点排除、大小写/空白归一）。加 refusal 生成级指标 + citation v2，联合报告。
- 优点：零 LLM judge、确定性、便宜（成本 = 生成调用本身）、可进 CI 冒烟。
- 局限：**只能当命中下界**——同义改写、中英互译、指代变换型要点会系统性漏判（v2.1 混合语言要点占比不低），低报率高是结构性的。

### 方案 B：机械下界 + 受约束 judge（推荐）
方案 A 之上，仅对机械未命中的要点引入 LLM judge 二次判定：
- 输出受**外置词表**硬校验：`{hit, miss, partial}` 三值 enum + 必须附带答案原文证据片段（snippet 必须是答案文本的规范化子串，程序化验证）；
- 词表外输出或缺证据 → fail-closed 重试（≤2 次）→ 仍失败记 `contract_error`，**该要点按 miss 计入并单独披露契约错误率**——直接复刻 mixed-030/mixed-033 的教训（引擎侧 decision 词表外置校验/解码约束方向的评测侧预演）；
- judge 面精确收窄：只判机械未命中例，成本随质量提升自然下降。
- 优点：成本按需增长；judge 可靠性可量化（契约错误率、与机械判定的分歧率）；中文语义等价漏判被兜住。
- 局限：引入 judge 变量（同模型自判的偏置须披露）；协议需要 TDD 严格约束。

### 方案 C：最小 refusal 线
只跑 28 条拒答探针（生成级拒答正确率）+ citation v2。
- 优点：最便宜。
- 缺点：答案质量仍不可量化，M2 移交的量化诉求未承接——不推荐单独立项，仅可作为 B 的降级退路。

**推荐：方案 B 分阶段**——M1 机械下界先行（全量、确定性、可复核），M2 judge 只补机械未命中面。若 owner 希望首期最小成本，可先批 A，judge 协议作为 A 报告后的增量提案。

## 五、里程碑（批准后执行，全程 TDD）

| 阶段 | 内容 | 退出标准 |
| --- | --- | --- |
| M1 | generation_runner 薄 CLI 驱动 + answer-hit 机械指标（containment 族，TDD）+ 密封产物自哈希范式 + **n=10 冒烟** | 冒烟密封报告落盘、指标口径与单元测试对齐 |
| M2 | 全量 150 例基线（122 生成 + 28 拒答），诊断性报告（含 token 实耗、refusal 混淆矩阵、citation v2 联合分布） | 密封产物 + 报告；**无门禁判定**，只有基线数字 |
| M3 | judge 子集（仅机械未命中要点）+ 契约错误率/分歧率统计 | judge 协议 TDD 全绿；judge 可靠性数据入报告 |
| M4（可选） | 基于两轮基线预注册阈值门禁提案 | 另行呈批，不在本章程内 |

## 六、成本预算与数据卫生红线

- **预算**：M1 冒烟 ≈10 次生成；M2 ≈122 次生成 + 28 次拒答探针执行；M3 judge ≤ 机械未命中要点数（上界 122 例全部要点）。具体模型/配额以 owner 批示为准；**单轮跑完即停**，失败补跑需显式授权。
- **数据卫生**：沙箱 `MNEME_DATA_DIR` 运行、trace 默认 Off、实验窗口零真实 trace 写入（沿用 run-3/run-4 巡检范式）；冻结资产只读；密封产物（outcomes + 自哈希 manifest）落 `results/answer-level/`。
- **身份诚实**：judge 若为 LLM，报告中如实标注模型身份与版本；机械指标确定性口径随 manifest 记录（沿用 `metric_version` 惯例）。

## 七、待 owner 审批的决策点

- **Q1 方案选择**：推荐 B（分阶段 M1 机械下界 → M3 judge）；备选 A（先纯机械，judge 另提案）。
- **Q2 模型与配额**：M2 全量 ≈150 次生成的模型与额度确认（当前 API_KEY 配额是否覆盖）。
- **Q3 门禁姿态**：确认第一轮纯诊断、第二轮预注册升级门禁的节奏。
