# 答案级评测线 M6a 预注册：引用质量线（生成侧引用选择单变量）

- 日期：2026-10-31
- 状态：**已批准（2026-11-01，owner 会话确认；手写签名待补）** —— Q1-a..e 已签，实施按 §八 执行；产品默认变更仍须另行批示
- 签批：2026-11-01（owner 在会话中确认「我同意，可以签」；Q1-a..e 见 §十）
- 上游：[M6 决策包](./ANSWER-LEVEL-M6-CANDIDATES-2026-10-31.md) §二（候选 1 = M6a，owner 2026-10-31 方向认可）、[STATUS P1-2](../docs/STATUS.md)（M6a 预注册已签批）
- 前置基线：M5d 门禁 `PASS`（[裁决报告](../results/answer-level/m5d-decision-2026-09-06/report.md)）、M4c 臂2 密封产物（[控制臂 manifest](../results/answer-level/m4c-arm2-2026-09-06/manifest.json)）、M2 引用构成（[M2 报告](../results/answer-level/m2-baseline-2026-08-30/report.md)）
- 范式与纪律：判据先于数据（[M4 预注册](./ANSWER-LEVEL-M4-GATE-PREREGISTRATION-2026-09-06.md) §三、[M5 预注册](./ANSWER-LEVEL-M5-QUALITY-GATE-PREREGISTRATION-2026-09-06.md) §二）；单变量；不设人工豁免；冻结资产零触碰
- 一句话目标：只在生成侧改**一个**引用变量，把 citation recall 从 **0.0456** 提到 **≥ 0.10**，同时不牺牲答案修正率（≥ 0.55）与语义拒答（≥ 0.90）

> 本文件已于 2026-11-01 获 owner 签批（Q1-a..e，见 §十），C1/C2/C3 与预算自此冻结生效。签批不等于实施批准：实施须按 §八 执行并另立实施记录；产品默认变更仍须 owner 另行批示。本文件本身未运行任何模型调用、未改动任何实现。

---

## 一、背景与缺口（既成事实，非本提案观测结果）

### 1.1 基线事实

| 事实 | 数值 | 来源 |
| --- | ---: | --- |
| citation recall（150 例例均） | **0.0456** | [m5d 报告](../results/answer-level/m5d-decision-2026-09-06/report.md) §3；[m4c 报告](../results/answer-level/m4c-decision-2026-09-06/report.md) §2；[控制臂 report.json](../results/answer-level/m4c-arm2-2026-09-06/report.json) |
| citation precision（150 例例均） | **0.0400** | 同上 |
| 有引用例（M2 期） | **91/150** | [M2 报告](../results/answer-level/m2-baseline-2026-08-30/report.md) §4 |
| 可答案例 | **122** | M2 报告 §4；m4c 报告 §1 |
| 臂2 检索缺口（context∩truth=∅） | **91/122 = 0.7459** | [m4c 报告](../results/answer-level/m4c-decision-2026-09-06/report.md) §1 |
| 可达例数 | **31 = 122 − 91** | [M6 决策包](./ANSWER-LEVEL-M6-CANDIDATES-2026-10-31.md) §1.2；本文件对控制臂复算 `relevant_chunk_ids ∩ context_chunk_ids ≠ ∅` 亦为 31 例 |
| 可达上界 | **0.2067 = 31/150** | M6 决策包 §1.2（原文自标「本包推导」）；当前 0.0456 仅为该上界的 **22%**（0.0456 / 0.2067 = 0.2206） |

> 来源说明：**0.2067 与 31 例不是 m4c 裁决报告的实测字段**，m4c 报告只提供 91/122 的缺口率；31/150 是 M6 决策包 §1.2 由该缺口率推导的结构上界。本文件按「推导值」引用，不冒充实测。另：91/150「有引用」与 91/122「检索缺口」是两个不同口径的 91，不可互相代入。

### 1.2 缺口：来源归因层没有仪器

M5d 门禁只判两件事——答案要点是否命中（修正率 0.5575）、该拒答时是否拒答（语义拒答 1.0）。它**结构性漏掉**了第三件事：答案里的 `[S#]` 是否指向真正支撑该句的 source。于是出现「答案可用、引用近乎空转」：recall 0.0456、precision 0.0400，用户看到引用却无法据此复核来源。这是 M6 §2.1 的问题陈述，也是本线唯一的立项理由。

### 1.3 本线边界（写死）

- **只做生成侧**：引用选择、引用覆盖、引用呈现、答案-引用一致性校验，四选一（§二）。
- **不碰检索排序**：融合权重、reranker、查询改写、召回宽度一律不动；P1 检索变量已于 M4c `FAIL` 后终止，Graph RAG 仍 `NO_PROMOTION`（M6 决策包 §八第 1、2 条）。
- **不改数据集/真值/judge 协议**：v2.1 数据集、`al1/al2/al3` 协议、`deepseek-chat` 模型全部冻结（§七）。
- **不改变答案正文**（本文件主选方案）：只重写 `[S#]` 标记；「答案质量不退化」因此是结构性保证，而不是跑完后祈祷。

---

## 二、单变量范围（四选一，本文件提议「引用选择」）

### 2.1 四个候选方向

| 方向 | 改动对象 | 改提示词 | 改答案正文 | 主要作用面 | 本文件判断 |
| --- | --- | :---: | :---: | --- | --- |
| **A 引用选择** | 每个**既有**引用槽位指向哪个 context chunk（重定向 `[S#]`） | 否 | 否（去引用后逐字节一致） | 控制臂 21 例「已引 context 块、但未引真值块」的选择失败 | **提议锁定** |
| B 引用覆盖 | 为已陈述但未引用的主张**新增**引用槽位 | 否 | 否 | 提升覆盖率；新增槽位会触发 §5.3 的归因折扣 | 不选（易滑向「多引」而非「引对」） |
| C 引用呈现 | `format_sources` 的展示口径 / 顺序 / 去重（[src/rag.py](../src/rag.py#L2103)） | 否 | 否 | 可读性与 ID 解析；不直接改变「引到哪一块」 | 不选（无法独立达成 C1） |
| D 一致性校验 | `_validate_and_repair_citations` 对非法/越界引用做校验与修复（[src/rag.py](../src/rag.py#L2202)） | 否 | 否 | 压 `fabricated` / `retrieved_not_in_context`；对 recall 提升间接 | 不选（C3 基线已是 0，增量空间小） |

### 2.2 提议锁定 A：生成后确定性引用选择

**做什么**：在生成完成之后，对答案中**已经存在**的 `[S#]` 槽位逐个重定向——依据该槽位所在句/段的文本与候选 context chunk 的确定性匹配，选择真正支撑该句的 chunk；槽位数量与位置不变。

**不做什么（写死）**：

- 不新增、不删除引用槽位（新增即属 B，见 §2.3）；
- 不改生成提示词、不改答案正文、不改拒答逻辑、不改检索/融合/reranker；
- 不调用模型：同一输入必须得到同一输出（确定性规则）；
- 运行时只允许读 `query`、`sources`、`context`、`answer`；**禁止读 `relevant_chunk_ids` 或任何真值字段**（泄漏禁令，§七）。

**落点**：复用 `_validate_and_repair_citations` 的调用路径（[src/rag.py](../src/rag.py#L2202)，调用点 [src/rag.py](../src/rag.py#L2915)），但决策规则是「选择」而非「合法性修复」；不得同时叠加修复策略。

**预期作用面（本文件对控制臂 `outcomes.jsonl` 的只读复算，未调用模型）**：

| 集合 | 例数 | 口径 |
| --- | ---: | --- |
| 可答案例 | 122 | `relevant_chunk_ids` 非空 |
| context 内含真值（可达） | 31 | `relevant_chunk_ids ∩ context_chunk_ids ≠ ∅` |
| 其中 recall > 0（已命中） | 10 | `citation_metrics.citation_recall > 0` |
| 其中 recall = 0（**A 的直接目标**） | 21 | 且 21 例的 `supported_chunk_count > 0`，即全部已有 context 内支持引用，属选择失败而非无引用 |
| 可答但零引用 | 9 | 全部 `context` 内无真值块，本线不可达（需改检索，P1 禁区） |

结论：A 的可达面是 **31 例**，其中 **21 例**是纯选择失败，不需要新增引用即可重定向。C1 = 0.10 需要净增 **8.17 个满引用例当量**（0.10 − 0.045556 = 0.054444；0.054444 × 150 = 8.167 ≈ 8.17），落在 21 例之内，结构上可行，但不保证——见 §8 预备检查的门槛。

### 2.3 单变量纪律（写死）

- 一次只改 **A** 一个变量。禁止同时改「选择规则 + 提示词/覆盖策略/呈现口径」；M6 §2.3 明确：若需同时动两项，拆两个里程碑串行，本文件只覆盖第一个（签批后生效）。
- 若实现 A 时必须新增引用槽位才能达标，说明 A 不成立——**停止并回报 owner 改选 B/C/D**，不得边跑边加机制。
- 改选 B/C/D 只能在**签批时**改写本节并重新冻结；跑数之后不得改选、不得混入。
- 允许的代码改动范围：引用选择/校验模块及其单测；不得改 `src/rag.py` 生成路径的其它行为、不得改 `src/config.py` 默认值、不得改拒答/检索/融合/reranker/提示词模板。
- 若实现结果无法做到「答案去掉 `[S#]` 后与对照逐字节一致」，视为变量越界，本次运行作废（§八步骤 3）。

### 2.4 与 M5 §三授权的关系（如实披露）

M5 §三字面只列出第 3 项「答案-引用一致性校验（`_validate_and_repair_citations` 扩展）」，即 §2.1 的 D。M6 §2.3 把 A/B/C/D 四项一并解释为该第 3 项，措辞上宽于 M5 原文。因此：

- A 的治理依据是 **M6 §2.3 + 本文件 Q1-a 签批**，不是 M5 §三的字面授权；
- 若 owner 认为 M5 §三不覆盖「引用选择」，须在 Q1-a 明文写「扩展授权至引用选择」，否则本文件不得实施；
- 本文件不把「方向认可」当作该扩展授权。

---

## 三、控制臂：M4c 臂2 密封产物（只读复用，零成本）

**控制臂**：[results/answer-level/m4c-arm2-2026-09-06/](../results/answer-level/m4c-arm2-2026-09-06/manifest.json) 密封产物，只读。

| 字段 | 值 | 来源 |
| --- | ---: | --- |
| case_count / cases_failed | 150 / 0 | [manifest.json](../results/answer-level/m4c-arm2-2026-09-06/manifest.json) |
| citation_recall_avg | 0.0456 | 同上 |
| citation_precision_avg | 0.0400 | 同上 |
| total_tokens_sum | 1,180,703 | 同上（prompt 1,165,780 + completion 14,923） |
| dataset v2.1 sha256 | `4597167d…8e92a9` | 同上 |
| metric_version | `al1-containment-v1` | 同上 |
| outcomes_sha256 | `157e86dc…5667d` | 同上 |
| manifest_sha256 | `936d34bb…28b52` | 同上 |
| git_commit（产出时） | `1501661…eb4d70` | 同上 |

**复用条件（preflight 逐条机械校验，任一不满足即停）**：

1. 校验 `outcomes_sha256`、`manifest_sha256`、`dataset_sha256` 与上表一致；
2. 用 [evaluation/citation_metrics.py](../evaluation/citation_metrics.py) 的契约 v2 口径从 `outcomes.jsonl` 复算，recall 必须复现 **0.045556 → 0.0456**、precision 复现 **0.0400**；
3. 有效生成配置与臂2 一致：`RAG_REFUSAL_THRESHOLD=0.015`、`RAG_DYNAMIC_MIN_K=25`、`RAG_CONTEXT_MAX_K=25`、`RAG_CONTEXT_TOKEN_BUDGET=7000`、温度 0.1（当前 HEAD 产品默认即臂2 配置，见 [src/config.py](../src/config.py#L37)、[src/domain.py](../src/domain.py) `compute_context_k`）；
4. 运行环境不得注入与臂2 不同的覆盖值；实际生效配置写入运行 manifest；
5. 控制臂文件**零改写、零重跑**；不得为对齐结果重算其任何字段。

**跨 commit 复用说明（如实披露）**：控制臂产出于 `1501661`，当前 HEAD 为 `06634d6`；两者之间 `src/` 只有「臂2 配置转产品默认 + 环境覆盖通道」的改动（[src/config.py](../src/config.py)、[src/domain.py](../src/domain.py)、[src/rag.py](../src/rag.py)），默认值与臂2 的 V3 注入等价。preflight 须以 `git diff 1501661..HEAD -- src` 审计确认无其它生成行为变化；若发现行为差异，控制臂不得直接复用，须回报 owner（不得自行重跑控制臂）。

---

## 四、指标定义（全部复用既有仪器，不新造）

| 指标 | 逐例定义 | 汇总口径 | 来源 |
| --- | --- | --- | --- |
| citation recall | `\|supported_chunks ∩ relevant\| / \|relevant\|`；`relevant` 为空记 0 | **150 例算术平均，分母冻结 150**（28 条拒答探针按 0 计入） | [citation_metrics.py](../evaluation/citation_metrics.py) 第 216–221 行；`al1-containment-v1` |
| citation precision | `\|supported_chunks ∩ relevant\| / \|supported_chunks\|`；无 supported 记 0 | 150 例算术平均 | 同上 第 217–220 行 |
| 修正率（partial = 0.5） | 174 要点 = 机械命中 20 + judge 面 154；`hit=1`、`partial=0.5`、`miss=0`、`contract_error=0` | `(20 + Σhit + 0.5×Σpartial) / 174` | M3 judge（[manifest](../results/answer-level/m3-judge-2026-09-05/manifest.json)）；m5d §2 |
| 语义拒答（al3 v1.1） | 28 条拒答探针的语义判定 `refused / answered` | `semantic_correct / 28`；两轮取**较低**轮，披露一致率 | [m5b v1.1 manifest](../results/answer-level/m5b-arm2-refusal-judge-v11-2026-09-06/manifest.json)；`al3-refusal-judge-v1.1` |
| fabricated | 引用 ID 无法由 `sources` 解析/映射到任何 chunk（幻觉） | 全 150 例 `fabricated_citation_count` **合计** | citation_metrics.py 第 237–238 行 |
| retrieved_not_in_context | 引用 chunk 在候选池内、但不在最终 context 内 | 全 150 例 `retrieved_not_in_context_count` **合计** | citation_metrics.py 第 239–240 行 |

**口径写死**：

- recall/precision 是**逐例指标再平均**，不是全量 micro 汇总；28 条探针没有真值块，按例记 0，这正是「分母冻结 150」的含义。任何剔除探针、改用 122 分母、改数据集版本的做法都会使数字不可比，判为违规。
- `supported` 只认 `supported_chunk` / `supported_source` 两种状态；`fabricated` / `retrieved_not_in_context` 不计入 precision 分子分母，但由 C3 单独守门。
- 以上指标在 M2/M3/M4c/M5d 中已被同一脚本、同一协议复算过；本文件不引入新指标、不调整阈值定义。

---

## 五、判据（提议值，待 owner 签批）

### 5.1 三条判据

| # | 判据 | 阈值 | 数值来源与算术核对 |
| --- | --- | ---: | --- |
| **C1** 主判据 | citation recall（分母冻结 150） | **≥ 0.10** | 可达上界 0.2067 的 **48%**：0.2067 × 0.48 = 0.0992 → 0.10；控制臂 0.0456 的 **2.19 倍**：0.0456 × 2.19 = 0.0999 → 0.10；反向 0.10/0.0456 = 2.19×、0.10/0.2067 = 48.4% |
| **C2** 守卫 | 修正率（partial 计 0.5）∧ 语义拒答（al3 v1.1） | **≥ 0.55** ∧ **≥ 0.90** | M5d 已验证值 0.5575 / 1.0（[m5d 报告](../results/answer-level/m5d-decision-2026-09-06/report.md) §2）；「不得为引用牺牲答案」 |
| **C3** 守卫 | citation precision ∧ fabricated ∧ retrieved_not_in_context | **≥ 0.0400** ∧ **= 0** ∧ **= 0** | 控制臂 precision 0.0400、两类计数均 0（[控制臂 manifest](../results/answer-level/m4c-arm2-2026-09-06/manifest.json)）；契约 v2 复算，防「多引用但引错」 |

### 5.2 裁决

- **C1 ∧ C2 ∧ C3 → `PASS`**；任一不满足 → **`FAIL`**。
- 判据之间**互不抵扣**：C2 很好不能救 C1，C1 很高不能救 C3；不设人工豁免，owner 若要豁免须书面复批本文件。
- 阈值在本文件签批时锁定；跑数后不得调整，不得先看结果再解释阈值，不得补跑挑最好一次。

### 5.3 附加条款：`PASS_WITH_WARNING`（跨方向适用，主选 A 下不触发）

M6 §2.4 原文：若 C1 达标但增量**全部**来自「引用未覆盖 15 例」而未触及选择逻辑，记 `PASS_WITH_WARNING`，要求定位声明，不计入下一阶段资本。

为可机械判定，本文件把该条款操作化如下（**不改变原文语义，只补判定口径**）：

- 判定例集 **U** 以控制臂 `outcomes.jsonl` 复算为准：`relevant ≠ ∅` ∧ `relevant ∩ context ≠ ∅` ∧ `citation_recall = 0`。本文件复算 **U = 21 例**（例号见附录 C）；M6 原文的「15 例」是 M2 期锚点（M2 context 更窄），**不得直接沿用**。差异原因：臂2 把 context 扩到 25 块，更多「未覆盖」进入可达面。
- 归因计数（裁决脚本输出，逐例）：**`add`**（控制臂没有、处理臂新增的 `[S#]`）、**`retarget`**（槽位存在但目标 chunk 改变）、**`delete`**（槽位被删除）。
- `PASS_WITH_WARNING` 的触发条件：C1 达标 ∧ 全部新增命中落在 U 内 ∧ **`add` > 0 且 `retarget` = 0**（即只新增引用、未重定向任何既有槽位，未触及选择逻辑）。
- 若 **`retarget` > 0**（存在既有槽位重定向），视为已触及选择逻辑，记 `PASS`。
- **主选 A 下该条款不触发**：§2.2 禁止新增槽位，`add` 恒为 0；若实测 `add` > 0，先按变量越界作废（§2.3），不进入 warning 裁决。该条款保留给 owner 改选 B 或实现漂移的情形。

> C3 的 precision 下限 0.0400 是「不退化」守卫，不是质量目标；它恰好与「25 块 context 全量喷引用」的 1/25 同量级，单靠 precision 不能证明选择质量。因此本线同时要求 C1 达到上界 48% 档，并用 §5.3 的槽位归因区分「引对」与「多引」。

---

## 六、预算（上界，超支即停）

| 项 | 上界（token） | 推导 / 来源 | LLM 调用 |
| --- | ---: | --- | ---: |
| 处理臂 150 例 × 1 次生成 | **1,180,703** | 与控制臂同配置、无检索变更；控制臂 `total_tokens_sum` 实测 | 150 |
| judge 子集复核（控制臂 66 个 miss 要点 ∪ 处理臂新增 miss 点） | **≤ 66,090** | M3 全 154 要点实测 66,090（[manifest](../results/answer-level/m3-judge-2026-09-05/manifest.json)）；无回归时 66 点只会更低，取全程上限 | ≤ 180 |
| al3 拒答复判（28 探针 × 2 轮） | **≤ 86,000** | M6 §2.5；v1.1 实测 16,190 / 30 次（[manifest](../results/answer-level/m5b-arm2-refusal-judge-v11-2026-09-06/manifest.json)） | ≤ 60 |
| **合计（规划口径）** | **1,332,793 ≤ 1,500,000** | 1,180,703 + 66,090 + 86,000；余量 167,207；judge 用 M3 全 154 要点实测，仅作对照 | **≤ 390 ≤ 400** |
| **合计（同面实测口径）** | **1,339,224 ≤ 1,500,000** | 1,180,703 + 72,521 + 86,000；余量 160,776；judge 用 m4c 臂2 同面实耗，**签批承诺值取此口径** | **≤ 390 ≤ 400** |

**预算执行规则（写死）**：

- 控制臂复用**零成本**；不得重跑控制臂来「对齐」数字。
- 硬上界是**总量 ≤ 1,500,000 token 且调用 ≤ 400 次**；单项为规划值。**签批承诺值取同面实测口径 1,339,224**（judge 72,521，m4c 臂2 实耗，[manifest](../results/answer-level/m4c-arm2-judge-2026-09-06/manifest.json)）；规划口径 1,332,793 仅作对照（judge 66,090，M3 实测），两者相差 6,431（+9.7%），均低于硬上界；差额须在报告中如实披露，不得静默改预算。
- 任一阶段累计 token 或调用数触及硬上界：**立即停止**，密封已完成部分，报告 `BUDGET_EXCEEDED`，不得用部分结果裁决。
- 不补跑、不加跑、不因「快接近显著」扩样；处理臂 150 例只跑一次。

---

## 七、冻结边界（写死）

### 7.1 协议与数据

- 生成协议 `al1-containment-v1`；judge 协议 `al2-judge-v1`（154 要点面）；拒答协议 `al3-refusal-judge-v1.1`（28 探针）。
- 模型 `deepseek-chat`、温度 0.1、judge `max_tokens=500` / `max_attempts=3`，与 M2/M3/M4c/M5d 完全一致。
- 数据集 `v2.1`，sha256 `4597167dadd72ba972373bedc44d27c858b7c7ddbe42f8ede9d37021b38e92a9`；chunk_id 归一口径 `12hex-normalized`。
- 指标版本 `al1-containment-v1`；不新增/不替换指标脚本。

### 7.2 资产零触碰

- v1、v2.0.x 修订树、sealed 产物**零触碰**；控制臂只读，不得改写、重算、重新密封。
- 不自动切换生产默认；不 stage/commit 未经 owner 批示的 `src/` 默认值变更；本线不得复活 P1 检索变量或 Graph RAG。

### 7.3 新产物与自哈希

- 新产物一律落 `results/answer-level/m6a-<stage>-2026-<date>/`，至少含：`outcomes.jsonl`、`manifest.json`（自哈希）、`report.json`、`report.md`。
- manifest 必须记录：`git_commit`、有效配置快照（含全部 `RAG_*` 环境覆盖的实际值）、`dataset_sha256`、`outcomes_sha256`、`manifest_sha256`、`metric_version`、协议版本、judge/al3 token 与调用数、实现规格哈希（§八步骤 1）。
- 实现规格（匹配打分、替换/保留规则、阈值）在跑前写入运行记录并由 manifest 哈希冻结；**不得跑后修改**。

### 7.4 泄漏禁令

- 运行时实现只读 `query` / `sources` / `context` / `answer`；禁止读 `relevant_chunk_ids`、`acceptable_answer_points` 或任何真值字段。
- 真值只允许在**离线裁决脚本**中读取，用于计算 C1/C2/C3 与 U/G 归因；裁决脚本与实现代码分离，随产物归档。
- 允许用控制臂密封产物做离线模拟/阈值选择（不调用模型），模拟脚本与结果须归档；**禁止用处理臂输出回头调规则或阈值**。

### 7.5 本文件作者的边界

- 本文件只新增 `plans/ANSWER-LEVEL-M6a-CITATION-QUALITY-PREREGISTRATION-2026-10-31.md` 一个文件；未修改 `src/`、`tests/`、`evaluation/`、`pyproject.toml`、CI、`docs/STATUS.md`、`CHANGELOG.md`。
- 本文件未运行生成、judge、al3 或任何模型调用；未 commit、未 push。数字均引自既有产物或对密封产物的只读复算，未新造。

---

## 八、实验流程（签批后执行，一次性）

| 步骤 | 动作 | 退出条件 / 产物 |
| --- | --- | --- |
| 0 预备检查 | 工作树干净且 HEAD 锁定；校验控制臂三哈希；复算 0.0456/0.0400；确认有效配置 = 臂2；`git diff 1501661..HEAD -- src` 审计；离线统计 A 的可重定向槽位上限 | 全部通过才进入步骤 1；任一失败 → 停止并回报 owner，不跑数 |
| 1 单变量实现 | 实现 A（确定性重定向，禁止新增槽位）；提交实现 commit；冻结实现规格与配置哈希 | 实现 commit + 规格哈希写入运行记录；代码评审确认未触检索/提示词/拒答 |
| 2 全量跑一次 | 150 例生成一次，密封 `outcomes.jsonl` + 自哈希 `manifest.json` | 产物落 `results/answer-level/m6a-run-2026-*`；cases_failed = 0 |
| 3 正文一致性检查 | 对 150 例剥离 `[S#]` 后与对照答案逐字节比较 | 150/150 一致才继续；任一不一致 → 变量越界，运行作废，不裁决 |
| 4 judge 子集 | 复判「控制臂 66 个 miss 要点 ∪ 处理臂新增 miss 点」；控制臂 74 hit + 6 partial + 8 CE 复用（依据步骤 3 的正文一致性）；分歧取**较差**判定 | judge 产物密封；修正率按 `(20+74+3+new_hit+0.5×new_partial)/174` 复算；披露一致率；若 union > 66 点，追加点属回归证据，照常复判并披露行项超支 |
| 5 al3 拒答复判 | 28 探针 × 2 轮；两轮独立，取较低轮为门禁值 | 产物密封；披露两轮一致率与分歧探针 |
| 6 机械裁决 | 裁决脚本读取三份密封产物，输出 C1/C2/C3、U/G、槽位归因（`add`/`retarget`/`delete`）与最终判定 | `m6a-decision-2026-*` 报告；无人工改数 |
| 7 归档 | 按 M6 §2.9 产物链归档；CHANGELOG/路线图回填由实施阶段在 owner 接收后执行 | 产物自哈希可复验 |

**流程纪律（写死）**：

- 处理臂**只跑一次**；不补跑、不重跑、不换随机种子挑结果（温度 0.1 的生成仍按单次密封）。
- 不看数调阈值、不因结果好而扩样、不因结果差而改判据解释。
- 步骤 0 的离线可重定向上限是**门槛而非调参**：若上限换算的满引用例当量 < 8.17，C1 在结构上不可达，停止并回报 owner 改选 B/C/D 或取消；不得跑后降 C1。
- 步骤 6 只做机械裁决；owner 只在签批判据与接收报告时介入，不在看到数字后改判据。

---

## 九、风险与限制（如实披露）

1. **31 例天花板**：C1 = 0.10 已是可达上界 0.2067 的 48%；若 owner 期望 recall ≥ 0.30，本线**结构上不可能**，须解禁排序（P1 禁区，候选 3 不授权）。
2. **U 例集迁移**：M6 §2.4 的「15 例」是 M2 期锚点；控制臂复算为 **21 例**（context 扩到 25 块）。裁决必须用复算值并列出例号，直接沿用 15 会误判 warning 归属。
3. **控制臂跨 commit 复用**：控制臂产出于 `1501661`，当前 HEAD `06634d6`；虽有「默认值等价」证据，仍须以 `git diff` 审计确认生成行为无其它变化（§三）。
4. **judge 行项预算偏紧**：同面 judge 实测 72,521 > 规划 66,090（+9.7%）；总量 1,500,000 可吸收（合计 1,339,224），但行项超支须披露，避免「静默改预算」。
5. **自判偏置**：`al2`/`al3` 均为 `deepseek-chat` 自判，沿用既有披露，不新增缓解手段；C2 的数字是自判口径，不是人工金标。
6. **P0-1 与「零退化」的边界**：P0-1 已按隔离 A 处置（[STATUS](../docs/STATUS.md) 2026-10-31）。默认套件 **2653 passed / 8 skipped / 318 deselected / 0 failed / 0 errors**；`frozen_stage` 仍有 **240 failed / 78 errors / 2661 deselected** 的 known-red，且**不在本线门禁内**。因此「零退化」只对默认套件负责，PASS 结论须标注该限制；M6 §2.8 第 4 条「P0-1 未处置」为当时快照，M6 顶部已加 2026-10-31 更新注记。
7. **A 的可达性依赖既有槽位**：若离线统计显示可重定向槽位不足 8.17 例当量，C1 不可达；步骤 0 即停，不进入花费。
8. **C3 是弱下限**：0.0400 与「25 块全量喷引用」的 1/25 同量级，单靠 precision 不足以证明选择质量；需配合 C1 与 §5.3 槽位归因阅读。
9. **分母漂移**：任何改数据集、剔除探针、改用 122 分母的做法都会让 recall 不可比，按违规处理并判 `FAIL`。
10. **不改变产品默认**：本线即使 PASS 也不自动切换默认、不 stage/commit；默认变更须 owner 另行批示（M6 §八第 7 条）。

---

## 十、owner 签批表（2026-11-01 已签；手写签名待补）

| 编号 | 批准事项 | 本文件提议 | 签署 | 日期 |
| --- | --- | --- | --- | --- |
| **Q1-a** | 批准候选 1 为 M6a 主选，并确认单变量为「引用选择」（§2.1 A / §2.2）；**同时明确扩展授权至引用选择**（M5 §三只覆盖一致性校验）；若改选 B/C/D，须在此写明并改写 §二后重新冻结 | 批准 A，并扩展授权至生成后确定性重定向既有 `[S#]` 槽位（禁止新增槽位） | 批准（2026-11-01，会话确认） | 2026-11-01 |
| **Q1-b** | 照准 C1 | citation recall ≥ 0.10（上界 0.2067 的 48%、控制臂 0.0456 的 2.19 倍） | 批准（2026-11-01，会话确认） | 2026-11-01 |
| **Q1-c** | 照准 C2 / C3 | 修正率 ≥ 0.55 ∧ 语义拒答 ≥ 0.90；precision ≥ 0.0400 ∧ fabricated = 0 ∧ retrieved_not_in_context = 0 | 批准（2026-11-01，会话确认） | 2026-11-01 |
| **Q1-d** | 批准预算 | 总量 ≤ 1,500,000 token、LLM 调用 ≤ 400 次，超支即停；签批承诺值取同面实耗口径 **1,339,224**（规划对照 1,332,793） | 批准（2026-11-01，会话确认） | 2026-11-01 |
| **Q1-e** | 批准 `PASS_WITH_WARNING` 的 U 例集按控制臂复算值 **21 例**（不是 M6 §2.4 的 15 例），并冻结附录 C 判定式与例号清单 | 批准 U = 21 例；附录 C 的判定式与例号清单随本表签批冻结；若要求沿用 15 例，须改写 §5.3 并说明口径 | 批准（2026-11-01，会话确认） | 2026-11-01 |

**签批说明**：

- 本表已于 2026-11-01 签署；签批后 §五 判据与 §六 预算冻结，实施按 §八 执行。
- Q1-a 的「扩展授权」是实施前提：M5 §三字面只授权 `_validate_and_repair_citations` 的一致性校验，不覆盖引用选择重定向；本次签批已在 Q1-a 中明确授予该扩展。
- 签批即冻结 §五 判据与 §六 预算，跑数后不得二次调整；附加条件须写入备注，否则不生效。
- 若 Q1-a 改选 B/C/D，须同时改写 §2.1/§2.2 的单变量声明与 §5.3 的归因规则，否则本文件自相矛盾，不得执行。
- 签批记录见上表与下方备注；手写签名待 owner 补签。

| 项目 | 内容 |
| --- | --- |
| 备注 | owner 于 2026-11-01 在会话中确认「我同意，可以签」；由 agent 据会话记录落字，手写签名待 owner 补签。 |
| owner 签名 | （待手签） |
| 签批日期 | 2026-11-01 |

---

## 附录 A：数字来源对照表

| 数字 | 值 | 来源（文件 / 节） |
| --- | ---: | --- |
| citation recall（控制臂） | 0.0456 | m5d 报告 §3；m4c 报告 §2；控制臂 `report.json` / `manifest.json` |
| citation precision（控制臂） | 0.0400 | 同上 |
| M2 citation recall / precision | 0.0322 / 0.0300 | m5d 报告 §3；m4c 报告 §2 |
| 有引用例（M2） | 91/150 | M2 报告 §4 |
| M2 引用构成 | 缺口 57 / 未覆盖 15 / 命中 7 / 探针 12 | M2 报告 §4（合计 91） |
| 臂2 检索缺口 | 91/122 | m4c 报告 §1 |
| 可达例数 / 上界 | 31 / 0.2067 | M6 决策包 §1.2（本包推导：122 − 91 = 31；31/150 = 0.2067） |
| 控制臂复算：可达 / 已命中 / U / 零引用 | 31 / 10 / 21 / 9 | 本文件对 `results/answer-level/m4c-arm2-2026-09-06/outcomes.jsonl` 的只读复算（字段见 §2.2） |
| 修正率（控制臂） | 0.5575 = (20+74+3)/174 | m4c 报告 §2；m5d 报告 §2 |
| judge 三态（控制臂） | hit 74 / partial 6 / miss 66 / CE 8 | m4c-arm2-judge manifest `aggregates` |
| 语义拒答（控制臂，al3 v1.1） | 1.0 = 28/28 | m5b v1.1 manifest |
| 生成 token（控制臂） | 1,180,703 | 控制臂 manifest `total_tokens_sum`；prompt 1,165,780 + completion 14,923 |
| judge token（M3 全 154 点） | 66,090 / 178 次 | m3-judge manifest `aggregates.judge_tokens` |
| judge token（臂2 全 154 点） | 72,521 / 180 次 | m4c-arm2-judge manifest `aggregates.judge_tokens` |
| al3 token（v1.1 一轮 28 探针） | 16,190 / 30 次 | m5b v1.1 manifest `aggregates.refusal_judge_tokens` |
| 默认套件 / frozen_stage | 2653 passed / 240 failed / 78 errors / 2661 deselected | [STATUS](../docs/STATUS.md) P0-1 行 |
| 数据集 v2.1 sha256 | `4597167d…8e92a9` | 控制臂 manifest；m3-judge manifest |
| 控制臂 commit | `1501661…eb4d70` | 控制臂 manifest |

## 附录 B：与 M6 决策包 §2.4 / §2.5 的一致性自检

- **C1**：M6 §2.4 =「citation recall（分母冻结 150）≥ 0.10」；本文件 §5.1 同值，且补算术 0.2067×0.48 = 0.0992→0.10、0.0456×2.19 = 0.0999→0.10。
- **C2**：M6 §2.4 =「修正率（partial 计 0.5）≥ 0.55 ∧ 语义拒答（al3 v1.1）≥ 0.90」；本文件同值。
- **C3**：M6 §2.4 =「precision ≥ 0.0400 ∧ fabricated = 0 ∧ retrieved_not_in_context = 0」；本文件同值，并把两类计数明确为 150 例合计。
- **裁决**：M6 §2.4 =「C1 ∧ C2 ∧ C3 → PASS；任一不满足 → FAIL；互不抵扣」；本文件 §5.2 同。
- **warning**：M6 §2.4 =「C1 达标但增量全部来自『引用未覆盖 15 例』而未触及选择逻辑 → PASS_WITH_WARNING」；本文件 §5.3 保留语义，仅把例集改为控制臂复算的 21 例并补槽位归因口径（差异已披露）。
- **预算**：M6 §2.5 =「处理臂 ≈1,180,703；judge ≤66,090；al3 ≤86,000；合计 ≤1,500,000；调用 ≤400」；本文件 §六 逐项同值，仅补充调用数推导 150 + 180 + 60 = 390 与 judge 同面实测 72,521 的风险披露。
- 结论：§2.4 三条判据与 §2.5 四项预算逐项一致；本文件新增的只有「可机械判定的归因口径」与「跨 commit 复用条件」，未改任何阈值或预算数值。

## 附录 C：控制臂复算口径（可复现）

对 `results/answer-level/m4c-arm2-2026-09-06/outcomes.jsonl` 逐条读取以下字段即可复现 §2.2 / §5.3 的例集：

- `relevant_chunk_ids`（真值块集合，空表示拒答探针）；
- `context_chunk_ids`（最终进入 context 的块集合）；
- `citation_metrics.citation_recall`（逐例 recall）；
- `citation_metrics.total_citation_count`（逐例引用槽位数）；
- `citation_metrics.supported_chunk_count`（逐例 context 内支持引用数）。

本文件使用的判定式：

```text
可达例     := |relevant| > 0 且 relevant ∩ context ≠ ∅
已命中例   := 可达 且 citation_recall > 0
U（选择失败）:= 可达 且 citation_recall = 0
零引用可答 := |relevant| > 0 且 total_citation_count = 0
```

复算结果：150 例中 122 例可答、31 例可达、10 例已命中、21 例 U（且 21 例 `supported_chunk_count` 均 > 0）、9 例零引用（且 9 例均不可达）；150 例 recall 均值 0.045556 → 0.0456，与密封 manifest 一致。该复算不调用任何模型。

**U 例号（21 例，按 `outcomes.jsonl` 顺序）**：

`multi-021`, `en-027`, `en-028`, `mixed-017`, `mixed-018`, `mixed-020`, `en-038`, `mixed-022`, `mixed-024`, `mixed-025`, `zh-054`, `en-043`, `en-047`, `en-048`, `en-049`, `en-053`, `mixed-026`, `mixed-029`, `mixed-032`, `mixed-034`, `mixed-035`

清单展示为逗号分隔并保留反引号；哈希口径为去掉反引号、逗号和空白后，按 `outcomes.jsonl` 顺序以换行连接（无末尾换行），SHA-256 为 `b54dc0075cddbbec87e7b480f5f1959631883059dd86985386fda703f534aed8`。该清单与判定式随 Q1-e 冻结。
