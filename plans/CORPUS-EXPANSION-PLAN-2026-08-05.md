# Mneme RAG 评测语料 v2 扩充与新 holdout 构建方案（corpus-expansion-plan）

> 制定日期：2026-08-05
> 性质：**只读设计** — 本方案不下载、不抓取、不导入外部文档、不调用 LLM/API、
> 不改现有数据集与生产配置；实施需用户按 §7 提供文档与授权后另行批准。
> 关联：阶段 1.5 假设生成审计结论（`plans/REFUSAL-SEPARABILITY-HYPOTHESIS-AUDIT-DESIGN-2026-08-05.md`）、
> 检索拒答阈值扫描 NO_GO（`results/graph-gate/refusal-threshold-scan-20260805T154407/`）、
> `plans/RAG-IMPROVEMENT-PLAN-2026-08-01.md` 阶段 0/1.5。

---

## 0. 背景与目标

### 0.1 为什么需要 v2

阶段 1.5 的离线审计得到三个互相制约的结论：

1. **单一 max-score 阈值不可分离前哨误拒（FR）与正确拒答（SR）**：分数带
   [0.0221, 0.0299] 完全交织，任何释放全部 dev FR 的阈值必然同时释放
   ≥3 条 SR（阈值扫描 NO_GO）；
2. **两特征复合规则无法被验证**：595,984 条规则中虽有 FR=4/4、SR=0/6 的
   "完美"签名，但均为围绕观测值形成的窄带记忆型过拟合（如
   `top3 ∈ [0.022948, 0.022962]`，宽度 0.000014）——**样本量 4 FR / 6 SR
   不足以支撑复合门控的验证**；
3. **现有 stable holdout（15 例）已被探索性查看**，不能再承担任何确认角色。

因此下一步的唯一通路是：**扩充语料与用例 → 在扩大的 dev 池内做嵌套
GroupKFold 规则选择 → 在全新的、从未被查看的 holdout 上一次性确认**。
本方案即为该通路的语料与标注协议设计。

### 0.2 目标

- 给出 v2 语料准入规范（来源/许可证/指纹/去重/质量门槛，§2）；
- 给出规模与分层目标及统计依据（§3）；
- 给出 v2 标注 schema、review pack、ground truth 与人工审核流程（§4）；
- 给出全新 group-aware dev/holdout 划分协议（冻结、指纹、封印，§5）；
- 给出数据版本与目录建议（§6）与用户需提供的资源清单（§7）。

### 0.3 设计原则

- **holdout 纯净性**：旧 110 例全部已被查看 → 新 holdout 只含新用例；
  划分前冻结 case_id；holdout 在规则选择完成前不可查看、不可参与任何
  特征分析（协议与守卫见 §5）；
- **可追溯**：文档、标注、划分全部以 SHA-256 指纹锁定，任何变更走
  change request 并生成新指纹；
- **向后兼容**：v2 schema 只做增量字段，v1 数据集与现有评测链路不受影响；
- **KISS**：分层与划分算法纯确定性（无跨进程随机性），实现时不依赖
  PYTHONHASHSEED 等环境因素。

---

## 1. 现有语料盘点（6 文档 / 736 chunks / 110 用例）

### 1.1 文档层（`test_texts/`，6 篇，索引 736 chunks）

| 文件 | 类型 | 语言 | chunk 数* | 用例引用数 | 主题域 | 结构特征 |
|---|---|---|---|---|---|---|
| DSpark_paper.pdf | PDF 论文 | en | ~361 | 22 | LLM 推理/工具 | 长文、章节、图表 |
| 2405.02357v2.pdf | PDF arXiv 论文 | en | ~261 | 12 | LLM 智能体 | 长文、章节 |
| prevent-url-data-exfil.pdf | PDF 论文 | en | 53 | 13 | 数据外泄防护 | 中等、技术细节 |
| LLMs_for_Mobility_Analysis_Survey.md | MD 综述 | en | 39 | 14 | LLM+时空分析 | 标题层级 |
| 南京城市地理环境.docx | DOCX 资料 | zh | 11 | 29 | 城市地理 | 短、含表格 |
| OneDrive 入门.pdf | PDF 产品指南 | zh | 7 | 23 | 产品使用 | 短、步骤式 |

\* chunk 数为 dev 检索候选可观测估计（dev 全候选去重后 660 条 + 未召回
余量，合计 ≈732/736）；source 前缀经
`source_id = sha256(normcase(规范化绝对路径))`（`src/rag.py:459`）反推映射。

### 1.2 用例层（`evaluation/datasets/v1.jsonl`，110 = dev 95 + holdout 15）

- 语言：zh 46 / en 46 / mixed 18；
- 类型：single_fact 35 / metadata 16 / mixed_intent 11 / cross_document 13 /
  multi_turn 10 / no_answer 25（no_answer = should_refuse 25，全部为拒答）；
- 真值：chunk 级 81（73.6%）、source-only 4（en-013、meta-003、meta-008、
  cross-008）、无真值（应拒答）25；
- 难度：easy 63 / medium 34 / hard 13；
- 多轮链：3 条（链长 4/3/3，共 10 例），其余 100 例为单例；
- 前哨 FR：dev 4（cross-010、en-013、meta-006、meta-008）+ holdout 1
  （meta-002）；dev SR 22 / holdout SR 3；
- 分数带：dev FR [0.0260, 0.0299] vs dev SR [0.0221, 0.0294]（交织）；
  并入 holdout（FR 0.02857、SR 0.02184）后并集带 [0.0218, 0.0299]，共 12 例；
- 旧 holdout 15 例（已查看、不可再作确认）：cross-006、en-001、meta-002、
  meta-007、mixed-010、mixed-012、multi-004、multi-005、multi-006、
  noanswer-010、noanswer-015、noanswer-025、zh-006、zh-010、zh-013。

### 1.3 覆盖缺口清单（v2 需针对性补足）

| # | 缺口 | 现状 | v2 对策 |
|---|---|---|---|
| G1 | **中文 chunk 占比极低** | 中文文档仅 18/736 chunk（≈2.4%），中文查询却占 42%（46/110） | 新增中文文档 3–4 篇（≥1 篇长文档），中文 chunk 占比目标 ≥20% |
| G2 | **领域单一** | AI/LLM 论文占 ≈85% chunk | 新增 2–3 个全新领域（技术/产品/FAQ） |
| G3 | **文档类型单一** | PDF 4 / MD 1 / DOCX 1 | 增加 HTML 源、API 参考、changelog、表格密集文档 |
| G4 | **无中英混合文档** | mixed 查询 18 例缺乏混合文档支撑 | 新增中英混合文档 1–2 篇 |
| G5 | **multi_turn 链太少** | 3 条链（共 10 例），链长 ≤4 | 新增 ≥8 条链（≥24 轮，链长 2–5，含跨文档链与拒答轮） |
| G6 | **低分带样本不足（核心）** | 交织带 [0.0218, 0.0299] 仅 12 例（dev FR 4+SR 6、holdout 1+1） | dev 侧交织带 ≥30 例、近带 ≥15 例（§3.3） |
| G7 | **metadata 维度受限** | 无版本/日期/发布信息类文档内容 | 引入含版本号、日期、发布说明的文档 |
| G8 | **hard 用例不足** | 13 例（11.8%） | 全池 hard ≥25%（§3.3） |
| G9 | **同主题集群单一** | 仅 AI 论文一个有效集群（3 篇） | 新增 ≥1 个同主题新集群 + AI 集群补充，支撑 cross_document 与低分 SR 构造 |
| G10 | **source-only 真值稀缺场景** | 4 例均为元数据类 | 保持 source-only ≤10% 新增（§4.2），避免真值降级滥用 |

---

## 2. v2 语料准入规范

### 2.1 来源与许可证

**三类可接受来源**：

1. 用户自有文档（项目/公司/个人资料）——需用户确认可复制入评测语料并允许衍生标注；
2. 许可证明确的公开文档——CC-BY、CC-BY-SA、MIT、Apache-2.0、PSF 等允许
   复制与衍生使用的许可证（标注属衍生使用，禁止 CC-BY-ND 类）；
3. 政府/机构公开数据——用途声明明确、无再分发限制。

**每篇文档必填出处记录**（写入 `corpus-manifest.json`）：

- `source_url`（或本地路径 + 授权说明）、`license`（SPDX 或 URL）、
  `license_notes`、`obtained_date`、`provider`（提供人/获取方式）。

**硬性禁止**：网页抓取、无许可证/来源不明、付费内容、含商业机密或
个人信息（未经用户明确脱敏授权）。

### 2.2 文档元数据与指纹

每篇文档记录：`file_sha256`（必填，内容级）、`doc_type`（pdf/docx/md/html）、
`language`（zh/en/mixed，自动检测 + 人工确认）、`title`、`pub_date` /
`last_modified`（可空）、`parser`（解析器 + 版本）、`char_count`、
`chunk_count`、`topic_note`（主题/用途，供构造用例与分层参考）。

`corpus-manifest.json` 记录全部文档元数据 + 自身 SHA-256；**文档内容级
指纹（file_sha256）是语料版本的权威锚点**。

### 2.3 敏感信息处理

- 自动扫描模式：邮箱、电话、身份证/护照号、银行卡、地址、API key、
  密码、私钥、内部域名/URL；
- 凭据类（key/password/私钥）**0 容忍**：命中即拒绝入库；
- 个人数据：由用户决定脱敏或排除；决定记录在 manifest；
- 语料仅本地存储；评测产物只含 chunk id 与摘要片段，不含原文
  （沿用现有 review pack 语义，见 §4.4）。

### 2.4 去重与近重复

- **精确去重**：SHA-256 相同 → 保留一份，其余记录 alias；
- **近重复**：归一化文本（去空白/标点/大小写）字符 5-gram Jaccard
  ≥ 0.85 → 人工判定（合并 / 剔除 / 保留并记录 dup 关系）；
- 新文档与现有 6 篇 v1 文档同样做近重复检测（不允许"翻版文档"混入，
  否则近重复文档跨 dev/holdout 会构成近似泄漏）；
- chunk 级重复段落检测（Jaccard ≥ 0.85 标记），防止单篇内部重复膨胀
  有效语料规模。

### 2.5 最小正文质量

- 有效文本 ≥ 800 字符（去除导航/页眉页脚/模板文本后统计）；
- 乱码检测：非法 UTF-8、控制字符率 >1%、mojibake 模式命中 → 拒绝；
- 结构信号：PDF 需 ≥1 级标题层级或 ≥80% 页含正文文本；DOCX/MD/HTML
  需有标题或列表结构（保证可 chunk 化与溯源）；
- 语言检测结果与申报一致（不一致 → 人工确认后修正申报或拒绝）。

### 2.6 解析成功率

- **逐文档判定**（无批次稀释）：PDF 无文本页 ≤10%；DOCX 段落/表格提取
  无异常；MD/HTML 结构完整保留；
- 任一文档不达标 → 不入库（可修复后随下一小版本进入）；
- 解析器版本记录进 manifest（解析结果随解析器版本变化时可重放）。

### 2.7 chunk 质量门槛（摄入后、入库前）

- **长度**：主带 200–600 字符（≥90% 的 chunk）；<100 或 >1200 字符
  ≤5%（长表格/代码块豁免需注明）；
- **完整性**：无截断句子/表格（表格独立 chunk）；chunk 不跨标题边界，
  标题归属唯一；
- **溯源**：每个 chunk 记录 `source`、标题路径、chunk 序号、页码（PDF）；
- **编码**：UTF-8 合法、无控制字符、无残留分隔符；
- **人工抽检**：每文档 ≥20 chunk（不足则全检），可读性通过率 100%；
- 产出 `chunks.jsonl` + `chunk-manifest.json`（SHA-256）；chunk id 沿用
  运行时格式 `{source_sha256_prefix}_chunk_{n}`（与 `src/rag.py` 一致）。

### 2.8 文档数量与主题建议

- 新增 **8–16 篇（推荐 10–12）**：中文 3–4、英文 5–7、中英混合 1–2；
- 主题构成建议：
  - ≥1 个与现有 AI/LLM 集群同主题的新文档（支撑 cross_document 扩容与
    低分 SR 的"主题相近但无证据"构造）；
  - 2–3 个全新领域（技术手册 / API 参考 / 教程 FAQ / 产品 changelog），
    其中 ≥1 篇含版本号与日期（支撑 metadata 与时效类查询）；
  - ≥1 篇表格/列表密集文档（支撑 chunk 真值定位与表格检索）；
- 每篇文档预计支撑 8–15 个新用例（§3.3 的 150 例总量据此规划）。

---

## 3. 数据规模与分层目标（含统计依据）

### 3.1 现状基数

全池 110：dev 95（FR 4 / SR 22 / answerable 73）、holdout 15（FR 1 / SR 3 /
answerable 12）；交织带 [0.0218, 0.0299] 共 12 例。

### 3.2 统计依据（门槛推导）

**a) G2 的 10% 容许量（dev 侧）**
错误放行门槛 = 10% × dev 全部 should_refuse。dev SR=30 → 容许 3 条；
SR=42 → 容许 4 条。用 Wilson 单侧 95% 上界衡量"通过门槛后仍可能对应
的真实错误率"：3/30 ≈ 0.23，4/42 ≈ 0.20。推荐 **dev SR ≥ 40**，使
容许量 ≥4 且上界可控。

**b) FR 样本（嵌套 GroupKFold 需求）**
5 折嵌套 CV 需要：每折验证折 ≥2–3 条 FR（放行率分母），训练折 ≥6–8 条
FR（规则枚举与选择）。推荐 **dev FR ≥ 12–15**（旧 4 + 新 8–11）。

**c) 错误放行率的可检测性（dev 侧粗算，正态近似）**
dev SR=42、观测上限 4 条时，真实错误率 30% → 观测 ≥5 条的概率 ≈99.7%；
20% → ≈93%；10% → ≈44%（正态近似）。结论：dev 侧能可靠排除"明显恶化"，
10% vs 20% 的精细区分仍需 holdout 确认与 LLM 受控实验——这是协议分级
（dev 选择 → holdout 确认）的统计依据。

**d) holdout 规模**
旧 110 例已全部查看 → holdout **只能由新用例组成**。新池 150 例的
25–30% → holdout **38–45 例（目标 ≈40）**，其中 SR ≥10（10% 容许 1 条）、
FR ≥5、每个 query_type 层 ≥1 组、每个语言层 ≥5。

**e) 低分带（阶段 1.5 核心矛盾）**
交织带现状仅 12 例。目标：dev 侧交织带 ≥30 例（可回答 ≥15、应拒答 ≥15）、
近带 [0.03, 0.05) ≥15 例。**低分带通过构造意图（band_target）标记，不依赖
运行时分数**；落带确认只在 dev 侧 v2.1 扫描轮进行（§5.4 注），holdout 侧
不扫描（构造规则先在 dev 侧验证有效，再以相同规则用于 holdout）。

**f) 记忆型过拟合与样本量**
4 FR/6 SR 时，两特征规则族存在大量窄带记忆签名（FR=4/4、SR=0/6）。
FR 12–15 / SR 40+ 时：同族规则在嵌套 CV 的验证折上可量化方差，窄带规则
难以跨折稳定 → **样本量是规则可信度的前提**，也是本次规模目标的直接依据。

### 3.3 规模目标（全池 ≈260 = 旧 110 + 新 150）

| 维度 | 新 150（±10% 容差） | 全池 260 |
|---|---|---|
| 语言 | zh 60 / en 60 / mixed 30 | zh 106 / en 106 / mixed 48 |
| 类型 | single_fact 34 / metadata 19 / cross_document 31 / multi_turn 24 / mixed_intent 12 / no_answer 30 | 69 / 35 / 44 / 34 / 23 / 55 |
| 拒答 | should_refuse ≥30（no_answer 30） | 55（21%） |
| 难度 | easy 40% / medium 35% / hard 25%（hard ≥52） | hard ≥65（25%） |
| 前哨 FR 目标 | 新增 8–11（dev 侧）；holdout ≥5 | dev ≥12–15、holdout ≥5 |
| band_target | low_answerable 18–22 / low_refuse 18–22 / near_band 15–20 / normal 其余 | — |
| 多轮链 | ≥8 条链（≥24 轮，链长 2–5）；跨文档链 ≥2；含拒答轮链 ≥1 | ≥11 条链 |

**dev/holdout 拒答分配（自洽约束）**：新 SR 30 例中 holdout 取 10–12
（§3.2d），其余 18–20 进 dev → dev SR 40–42（含旧 22）、holdout SR
10–12（dev SR ≥40 满足 §3.2a 的容许量 ≥4）。

**分层采样规则**：

- 分层变量：`query_type × should_refuse × language`（18 个有效层：
  5 个可回答类型 ×3 语言 + no_answer ×3 语言）；`band_target` 仅作为
  dev 侧参考维度，不进入 holdout 分层；
- 每个有效层新用例 ≥5；多轮链整体计入所在层；
- holdout 每层 ≥1 组（链组或单例组）→ 分层设计保证每层 ≥2 组
  （至少 1 条链 + 若干单例），否则该层 holdout 取 0 组并记录。

### 3.4 低分带用例构造规则（band_target 语义）

| band_target | 构造思路 | 例 |
|---|---|---|
| `low_answerable` | 模糊指代 / 多义词 / 间接表达，答案存在但检索难命中 | "那篇论文里提到的 agent 框架的调度方式"（多义词诱导） |
| `low_refuse` | 主题与语料相近但证据不在语料中 | "用 DSpark 的方法处理 mobility 数据的效果"（跨论文捏造组合） |
| `near_band` | 正常可答但证据密度低/需跨段整合 | "总结 X 文档中关于限制条件的全部表述"（分散证据） |
| `normal` | 直接、规范提问 | 常规事实/元数据/多轮查询 |

> 注：band_target 是**构造意图**而非分数承诺。dev 侧允许在 v2.1 扫描轮
> 用检索分数校验落带并调整构造；holdout 侧**禁止**任何分数扫描，只按
> 构造意图分层（偏差作为已知风险记录于确认报告）。

---

## 4. v2 标注 schema、review pack、ground truth 与人工审核

### 4.1 schema v2（增量字段，向后兼容 v1）

`evaluation/schema.py` SCHEMA_VERSION 提升至 2，EvalCase 新增字段（全部
带默认值，v1 文件仍可加载，评分链路不变）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `relevance_level` | string | 新用例必填 | `chunk` / `source` / `none` |
| `relevant_chunks[].chunk_id` | string | chunk 级必填 | 指向 chunk manifest 的 id |
| `relevant_chunk_ids` | string[] | chunk 级必填 | 与 relevant_chunks 一一对应 |
| `annotation.annotated_by` / `reviewed_by` | string | 必填 | 标注/复核人 |
| `annotation.review_status` | string | 必填 | pending / approved / rejected / needs_revision |
| `annotation.review_notes` | string | source-only 必填 | 理由说明 |
| `annotation.annotation_version` / `created_at` | string | 必填 | 版本与时间 |
| `metadata.difficulty` | string | 新用例必填 | easy / medium / hard（沿用 v1 定义） |
| `metadata.band_target` | string | 新用例必填 | low_answerable / low_refuse / near_band / normal |
| `metadata.construction` | string | 新用例必填 | natural / fuzzy_query / cross_doc / follow_up / out_of_corpus / metadata |
| `metadata.chain_id` | string | 链中用例必填 | 链头 case id |

实现约束：`EvalCase.from_dict` 目前对未知键抛 TypeError——v2 字段须以
默认值加入 dataclass；`validate_dataset` 增加 v2 校验（见 4.2）。

### 4.2 合法组合（fail-closed 校验，写入 schema 校验器）

| relevance_level | should_refuse | relevant_source_ids | relevant_chunk_ids | 说明 |
|---|---|---|---|---|
| `none` | true | `[]` | `[]` | 应拒答 |
| `chunk` | false | 非空 | 非空 ⊆ chunk manifest | 有 chunk 级真值 |
| `source` | false | 非空 | `[]` | source-only |

**source-only 规则**（继承 v1 语义，见 `evaluation/REVIEW_PACK_README.md`）：

- 仅"答案点**不可可靠定位**到具体 chunk"（元数据类、数量类、全文档分布类）
  允许标 `source`；能定位的一律标 `chunk`；
- 每条 source-only 必须填写 `review_notes` 说明理由；
- 新增用例中 source-only 占比 ≤10%；
- `relevant_chunk_ids` 必须存在于 v2 chunk manifest，且 ⊆ 对应 source 的
  chunk 集（校验时逐条检查，防 chunk id 伪造）。

### 4.3 标注流程（单人项目 → 两阶段；双人 IAA 为可选增强）

```
阶段 1 构造   按 §3.3 分层目标与 §3.4 构造规则生成 query 草稿
   ↓
阶段 2 首标注  ZCode 辅助起草（通读文档 → 标来源/chunk/答案点/
               should_refuse/难度/band_target/construction）
   ↓
阶段 3 终审    用户逐条 approved / revise / reject（revise 必须附意见；
               reject 注明原因：重写或剔除）
   ↓
阶段 4 修正循环 直至 100% approved；分歧全部裁决并记录
   ↓
阶段 5 锁定    ground truth（§4.5）
```

- 多轮链**按链整体标注与审核**（链内 follow_up 语义完整），不允许链内
  部分用例处于 pending；
- 双人模式（可选）IAA 门槛：should_refuse Cohen's κ ≥0.85、source 级
  一致率 ≥90%、chunk 级一致率 ≥80%；分歧 100% 裁决记录。

### 4.4 review pack v2（复用现有语义：只导出、不判定、fail-closed 导入）

- `annotation-pack.jsonl`：每条 case 一行（query + 相关片段 + 首标注
  字段），人工填 `review_decision`（approved / revise / reject）+ notes；
- 多轮链按链分组呈现；source-only 必须复核确认；
- `review_apply` v2 严格校验（与现有 `evaluation/review_apply.py` 同款
  fail-closed：manifest SHA、行数、键集、必填值），输出 gt-overlay；
- 与现有 review pack 的区别：v2 pack 覆盖**全部新用例**（含答案点与
  拒答判定），而不仅是 chunk 真值补标。

### 4.5 ground truth 锁定

- `gt-v2.jsonl` = 100% approved 的 v2 用例；
- `gt-manifest.json`：SHA-256、corpus_version、case-freeze 哈希、审核统计
  （各 review_status 计数、IAA 值）、锁定时间、变更历史；
- **锁定后不可变**；修改走 change request（diff + 理由 + 新指纹），
  全程记录于 manifest；
- 锁定 ground truth 与 §5 的 case-freeze 同步完成（同一版本号）。

---

## 5. 全新 group-aware dev/holdout 划分协议

### 5.1 原则

1. **holdout 只含新用例**（旧 110 例已全部被查看，全部归入 dev 池并
   标记 `generation="v1"`、`explored=true`，报告中注明其已被探索）；
2. **链是分组单位**（`metadata.follow_up_to` 闭包），链不跨 dev/holdout；
3. 划分前 **case_id 冻结**；
4. **holdout 在规则选择完成前不可查看、不可参与任何特征分析**。

### 5.2 划分步骤（纯确定性，跨平台可复现）

```
1 冻结     case-freeze.json：{corpus_version, 全池 case id 有序列表 + SHA-256,
           各 prefix 已用序号, partition 标记(legacy_dev/new)}；
           id 唯一性校验 fail-closed
2 分组     chain_id（链头 id）+ 链内 case 列表；无 follow_up 的用例 = 单例组
3 分层     每层(query_type × should_refuse × language)内，组按
           sortkey = splitmix64(sha256(f"{seed}:{group_key}")) 排序
           （纯整数运算 + sha256，跨 Python 版本/平台确定）
4 采样     每层取前 h 组入 holdout：h = max(1, round(0.25 × n_groups))
           当 n_groups ≥2；n_groups=1 时 h=0（该层无 holdout，记录）
5 校验     holdout 占比 ∈ [0.22, 0.30]；每层 ≥1 组（可行时）；链完整；
           holdout ∩ 旧 110 = ∅；任一不满足 → 调整 seed 重新划分并记录
6 指纹     split_fingerprint = SHA-256(canonical JSON of {
             corpus_version, case_freeze_sha256, 分组表 sha256, seed,
             splitter_version, holdout_ratio, dev/holdout id 列表 sha256 })
7 锁定     split-lock.json：{fingerprint, 输入（不含 holdout id 列表！）,
           每层计数, splitter_version}；holdout ids 不落盘——确认阶段由
           同一 splitter 重算并校验指纹
```

> 旧实现教训（`compare.py::group_aware_split` 曾因 `set` 迭代顺序跨进程
> 不确定）：本协议全部排序基于稳定有序输入 + 纯函数哈希，不依赖
> PYTHONHASHSEED（沿用已修复的稳定排序约定）。

### 5.3 封印与守卫（阶段 A / B / C）

| 阶段 | 允许 | 禁止 |
|---|---|---|
| A 划分前 | 文档阅读、用例构造、标注 | 查看任何 v2 case 的检索分数/特征 |
| B 规则选择 | dev 池全部分析（特征提取、嵌套 GroupKFold、规则枚举） | 任何涉及 holdout case 的运行；分析产物出现 holdout id（写入时 fail-closed 校验） |
| C 一次性确认 | 重算 holdout ids → 校验指纹一致 → 运行检索 + 锁定规则 → 输出确认报告 | 确认后再调整规则、二次运行 holdout、对 holdout 做任何探索性分析 |

**自动化守卫（未来实施，契约先行）**：`evaluation/split_seal.py` 提供
五个确定性入口——`freeze_case_ids` / `build_split` / `verify_lock` /
`check_artifact_ids`（扫描分析产物 JSONL，出现 holdout id → ValueError）/
`confirm_holdout`。本计划只定义契约，不实施。

### 5.4 dev 内部协议（规则选择，未来阶段执行）

- **嵌套 GroupKFold**（5 折，按链分组）：每折仅用训练折选择规则 →
  验证折评估 → 各折方向一致 → 全 dev 选出唯一规则；
- 规则固定后**仅在全新 holdout 上评估一次**；通过后再决定 LLM 受控实验；
- 无规则通过 → 停止并建议再扩充（与阶段 1.5 协议一致）；
- dev 侧低分带校准（v2.1 扫描轮）：对 dev 用例运行检索、检查 max score
  落带、调整构造并重标（属 dev 分析，不违反封印）；**该扫描绝不接触
  holdout**。

---

## 6. 数据版本与目录建议

### 6.1 版本规则

- **v2.0.0**：首版（文档集 + 标注 + split 冻结）；
- **v2.1.x**：文档增补/替换（须重新 case-freeze 与 split 指纹）；
- **v2.0.x**：标注修订（走 change request，不改变文档集）；
- 每个版本联动三件套：`corpus-manifest.json` + `case-freeze.json` +
  `split-lock.json`；旧版本冻结只读；
- 检索实验前用 corpus 指纹校验索引一致性（chunk manifest 是 chunk 的
  权威来源，不是 Chroma DB——避免"本地索引是部分重建"这类状态进入评测）。

### 6.2 目录建议

```
evaluation/datasets/
  v1.jsonl                    (冻结，不动)
  v2/
    corpus-manifest.json     文档清单（sha256/license/来源/日期/parser）  ← 入 git
    annotations/             annotation packs（标注/复核记录）           ← 入 git
    gt-v2.jsonl              锁定真值 + gt-manifest.json                  ← 入 git
    split/
      case-freeze.json       冻结 case_id + 指纹                         ← 入 git
      split-lock.json        划分指纹 + 输入（不含 holdout ids）         ← 入 git
    v2.jsonl                 汇总数据集（schema_version=2）              ← 入 git
data/v2-corpus/               (本地数据目录，建议不入 git；
                              与阶段 3.2 的 MNEME_DATA_DIR 方向一致)
    documents/               原始文档 + 每篇 sha256
    chunks/                  chunks.jsonl + chunk-manifest.json
results/graph-gate/
    corpus-v2-<ts>/          未来实验输出（检索/特征/确认）
```

### 6.3 一致性约束

- `band_target` 是构造意图，**不随模型/索引版本变化**（检索分数与语料
  版本解耦）；
- 任何实验产物 manifest 必须记录其使用的 corpus 指纹与 split 指纹，
  跨指纹对比一律禁止直接比较。

---

## 7. 需要用户提供/授权的资源（明确清单）

1. **新文档 8–16 篇（推荐 10–12）**，建议构成（§2.8）：
   - 中文 3–4 篇：技术/产品文档、≥1 篇含表格与版本信息、≥1 篇教程/FAQ 类；
   - 英文 5–7 篇：技术文档/API 参考/论文，其中 ≥2 篇同主题可比较
     （新集群或补充 AI 集群）；
   - 中英混合 1–2 篇：双语产品文档/说明；
   - 每篇附：来源（URL/本地路径）、许可证（SPDX 或 URL）或授权说明、
     发布日期（如适用）。
2. **授权确认**：自有文档可复制入评测语料并允许衍生标注；第三方文档
   许可证允许复制 + 标注（CC-BY 类可，CC-BY-ND/无许可证不可）。
3. **敏感信息决定**：含个人数据的文档 → 脱敏或排除；凭据类 → 不入库。
4. **标注投入确认**：150 新例终审估算 15–30 小时（可分 2–3 批）；
   确认 v2.0.0 一次到位，或先 80–100 例启动（v2.0.0 后 v2.1.x 扩充）。
5. **存放决定**：`data/v2-corpus` 不入 git 是否可接受（或改为入 git）。
6. **双人 IAA**：是否需要第二位复核人（无则记录单人终审流程）。
7. **未来阶段指示**：数据就绪后是否按 §5.4 实施 `split_seal` 工具与
   嵌套 GroupKFold 规则选择。

---

## 8. 验收与验证（未来实施阶段的检查点）

| 阶段 | 通过标准 | 证据 |
|---|---|---|
| 文档准入 | §2 全部门槛通过 | corpus-manifest.json + 扫描记录 |
| 索引与分块 | chunk 质量门槛通过、chunk manifest 指纹 | chunk-manifest.json |
| 标注 | 100% approved；IAA 达标（双人模式）；source-only ≤10% | annotation packs + gt-manifest.json |
| GT 锁定 | gt 指纹与 case-freeze 同步 | gt-v2.jsonl + gt-manifest.json |
| 划分冻结 | 指纹锁定；holdout 占比/分层/链完整性校验通过 | case-freeze.json + split-lock.json |
| 分析守卫 | 全部分析产物无 holdout id（fail-closed 扫描） | check_artifact_ids 输出 |
| holdout 确认 | 指纹一致；锁定规则一次性评估 | holdout-confirmation.json + 报告 |

**本方案自身验证**：只读分析（零代码改动）；文档数字自洽检查、
`git diff --check`、完整测试套件无回归（见交付说明）。

---

## 附：术语与常量速查

- **FR**（前哨误拒）：answerable 但被检索前哨（max < 0.03）拒绝；
- **SR**（正确拒答）：should_refuse 且被拒答（含前哨拒答与生成拒答）；
- **交织带**：[0.0218, 0.0299]（dev + holdout 全部拒答 case 的 max score 范围）；
- **G2 口径**：新放行 should_refuse ≤ 10% × 该 split 全部 should_refuse；
- **splitmix64**：确定性 64 位哈希（纯整数运算），用于组排序 key；
- **Wilson 上界**：单侧 95% 置信上界（3/30 ≈ 0.23，4/42 ≈ 0.20）。
