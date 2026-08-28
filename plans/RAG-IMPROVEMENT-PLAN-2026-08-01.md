# Mneme RAG 改进计划

> 基于 `RAG-IMPROVEMENT-REPORT-2026-08-01.md` 制定
> 制定日期：2026-08-01
> 状态：进行中（2026-08-13 已按当前工作树、测试与产物证据回填）
>
> **进度标记说明**：`[x]` = 核心交付已实现且有可验证证据；`[~]` =
> 实现、实验或工具链已存在，但原计划的效果门槛、默认启用或治理前提尚未
> 满足；`[ ]` = 尚未开始或缺少足够证据；`[!]` = 已有明确阻断结论，禁止
> 以“已完成”或“可产品化”表述。`[x]` 不等同于已发布、已激活或已证明所有
> 质量指标达标。
>
> **回填原则**：本文件保留原始路线和历史预计工期；以下状态只反映已核验的
> 当前实现，不把 v2.0.11 的 CANDIDATE/frozen 评测资产、synthetic replay
> 或未获准的实验结果误记为生产质量改进。
> 原文中的“关键代码位置”行号属于 2026-08-01 快照，可能已随重构漂移；状态
> 回填以模块与当前行为为准，不把旧行号当作现状证据。

---

## 一、总体策略

报告的核心判断是：**工程可靠性处于"可用原型后期"，效果工程处于"尚未建立可信基线"**。因此改进策略遵循以下原则：

1. **先度量，再优化**——没有评测集的优化是盲目的。阶段 0 的唯一目标是让后续改动都能回答"提高了什么、牺牲了什么"。
2. **先 Standard，再 Graph**——先把 Standard RAG 做成可度量、可校准的可靠基线，再决定 Graph RAG 是否默认开放。
3. **每个阶段独立可交付**——每个阶段完成后，系统都应处于可发布状态，不依赖后续阶段。
4. **单一职责**——每个工作项只做一件事，完成后更新 CHANGELOG 并通过测试验证。

---

## 二、阶段 0：建立可比较基线（P0，最先执行）

> **目标**：让后续任何改动都能在评测集上证明净收益或净损失。
> **预计工作量**：3 个中等工作项 + 2 个小工作项 ≈ 3-4 周
> **前置条件**：无
> **第一里程碑**：80 条最小评测集 + 检索 runner 可运行（0.1 + 0.2），约 1.5 周
>
> **当前进度：** `[~]` 基础评测、指标和 CI 工具链已落地；但 v1 的
> 110 条数据没有显式 train/holdout 分区，且 Windows 默认 GBK 控制台下
> `--validate-only` 会因输出 `✓` 失败（设置 `PYTHONIOENCODING=utf-8` 后
> 校验通过）。因此不能把“可比较基线”整体标为完全完成。

### [~] 0.1 真实评测集 v1

| 属性 | 内容 |
| --- | --- |
| **交付物** | 80-150 条 JSONL 评测文件 + 标注规范文档 |
| **完成标准** | 覆盖 8 类核心查询（中文、英文、中英混合、元数据、单文档事实、跨文档比较、多轮追问、无答案/拒答）；每条至少标注 `relevant_source_ids`、页码/section、可接受答案要点、是否应拒答；重要样例再标相关 chunk ID |
| **工作量** | M |
| **涉及文件** | 新增 `evaluation/datasets/`、`evaluation/schema.py` |

> **当前回填：** `evaluation/datasets/v1.jsonl` 已有 110 条用例，覆盖
> 中文/英文/混合语言与 single_fact、metadata、mixed_intent、cross_document、
> multi_turn、no_answer 类型；`evaluation/ANNOTATION_GUIDE.md`、schema 与
> strict 校验路径均已存在。原计划要求的显式 train/holdout 分区尚未写入 v1
> 行或等价锁定契约，故保留 `[~]`。

**实施步骤**：

1. 定义评测数据 schema（JSONL 格式，每条包含 `query`、`query_type`、`language`、`relevant_source_ids`、`relevant_chunks`、`acceptable_answer_points`、`should_refuse`、`metadata`）

> **边界声明**：`evaluation/schema.py` 只描述评测标注格式（静态数据结构），`src/domain.py`（阶段 1.3 引入）描述运行时领域模型（`RetrievalCandidate`、`Source`、`Chunk` 等）。两者虽都含 chunk/source 概念但职责不同：评测 schema 是"标注者写入、runner 读取"的契约，领域模型是"检索/生成链路传递"的运行时类型。
2. 准备评测语料：从项目已有 PDF/DOCX 样例 + 新增中文文档样例中选取
3. 编写 80-150 条评测查询，按 8 类分布（建议：中文 20、英文 20、混合 15、元数据 10、单文档事实 15、跨文档 10、多轮 10、无答案/拒答 25-30）
4. 人工标注每条查询的相关来源和答案要点
5. 划分训练子集（85-90%）与 holdout 子集（10-15%）：调参只看训练子集，最终验收在 holdout 上跑，防止过拟合
6. 编写标注规范文档 `evaluation/ANNOTATION_GUIDE.md`

### [~] 0.2 实际检索评测 Runner

| 属性 | 内容 |
| --- | --- |
| **交付物** | 经过 Mneme 实际 parser/embedding/Chroma/BM25/RRF 链路的评测 runner |
| **完成标准** | 输出逐例候选列表与 Recall@K、MRR、nDCG 指标；可复现运行 |
| **工作量** | M |
| **涉及文件** | 新增 `evaluation/runner.py`、`evaluation/metrics.py` |

> **当前回填：** `evaluation/runner.py`、`evaluation/metrics.py` 与
> `evaluation/run.py` 已实现真实索引/检索链路、逐例输出和分层指标；v1
> `--validate-only` 在 UTF-8 输出下实测通过。默认 Windows GBK 输出兼容问题
> 尚未修复，且未把 v1 的可重复性/holdout 门槛完整封闭，故保留 `[~]`。

**实施步骤**：

1. 实现 `RetrievalRunner`：调用 Mneme 的 `build_index()` → `retrieve_hybrid_with_sources()` 链路，对评测集逐条运行
2. 实现 `RetrievalMetrics`：计算 Recall@5/10/20、MRR、nDCG、source recall
3. 输出结构化报告：总体 + 按语言/查询类型分层
4. 记录当前基线分数，作为后续改动的参照
5. 添加 CLI 入口：`python -m evaluation.run --dataset v1 --output results/baseline.json`

### [~] 0.3 生成与引用评测

| 属性 | 内容 |
| --- | --- |
| **交付物** | correctness、faithfulness、citation precision/recall、refusal 评测 |
| **完成标准** | 人工抽样可复核；原始文档不写入日志；与检索评测独立运行 |
| **工作量** | M |
| **涉及文件** | 新增 `evaluation/generation_runner.py`、`evaluation/citation_metrics.py` |

> **当前回填：** generation runner、citation metrics、上下文证据口径与
> 聚合契约已实现；后续 Product P0.1/P0.2/P0.2.1 也已完成真实回答入口的
> citation integrity 展示闭环。原计划中的人工抽样复核、稳定生成质量门禁和
> holdout 验收尚不应由现有代码或 CANDIDATE 资产替代，故保留 `[~]`。

**实施步骤**：

1. 实现 `GenerationRunner`：在检索结果基础上调用 LLM 生成回答
2. 实现 `CitationValidator`：调用 `src/citations.py` 的现有解析函数，校验引用 ID 合法性
3. 实现 faithfulness 评测：对比回答要点与上下文证据的覆盖关系
4. 实现 refusal 评测：对 `should_refuse=true` 的查询验证系统是否正确拒答
5. 生成评测单独运行，避免把检索失败和生成失败混为一谈

### [x] 0.4 Docker bind mount 遮蔽预下载模型修复

| 属性 | 内容 |
| --- | --- |
| **交付物** | 修复 `docker-compose.yml` 的 bind mount 遮蔽镜像内预下载模型的问题 |
| **完成标准** | 新宿主机首次 `docker compose up` 不因空 `./models` 目录而重新触发模型下载 |
| **工作量** | S（约半天） |
| **涉及文件** | 修改 `docker-compose.yml`、`Dockerfile` |

> **当前回填：** `docker-entrypoint.sh` 会在挂载的 `/app/models` 为空时从
> `/app/models-image` 恢复镜像内预下载模型，已覆盖本项原始遮蔽问题。

**实施步骤**：

1. 修改 `docker-compose.yml`：将 `./models` bind mount 改为 named volume，或在 entrypoint 中检测镜像内模型并复制到挂载目录
2. 验证新宿主机首次启动不重新下载模型
3. 更新 README 中 Docker 相关说明

**原因**：这是新用户第一天就会踩的坑（空 `./models` 遮蔽镜像内 `/app/models`），不应拖到阶段 3。

### [x] 0.5 CI 分层

| 属性 | 内容 |
| --- | --- |
| **交付物** | 三层 CI 配置：unit / offline retrieval / scheduled generation |
| **完成标准** | PR 能发现检索回归；外部费用可控 |
| **工作量** | S |
| **涉及文件** | 修改 `.github/workflows/`、`pyproject.toml` |

> **当前回填：** `.github/workflows/ci.yml` 已包含跨平台 unit tests、离线
> retrieval evaluation 与需显式标签的 generation evaluation 三层；检索相关
> 变更也具备独立回归检查入口。

**实施步骤**：

1. **Layer 1 — 快速纯单元测试**：现有 139 个测试，每次 PR 必跑
2. **Layer 2 — 离线检索评测**：使用固定本地模型 + 评测集 v1；触发机制为 **path-based + label-based**——当 PR 修改 `src/rag.py`、`src/lexical.py`、`src/retrieval.py`、`src/graph_rag.py` 或 `evaluation/` 目录时自动触发；也可通过 `run-retrieval-eval` GitHub label 手动触发；主分支每日定时运行一次
3. **Layer 3 — 完整生成评测**：需要外部 LLM API，手动触发或每日定时运行
4. 在 CI 中添加检索回归检测：与基线对比，Recall 下降超过阈值则标记警告

---

## 三、阶段 1：修复 Standard RAG 核心效果闭环（P0）

> **目标**：让 Standard RAG 的检索、拒答、上下文和引用形成可校准的闭环。
> **预计工作量**：4 个中等工作项 + 2 个小工作项 ≈ 4-5 周
> **前置条件**：阶段 0 完成（有评测集和基线分数）
>
> **当前进度：** `[~]` 多个生产漏斗组件已经实现并受测试保护，但“某一默认
> 检索策略取得净收益”的效果门槛尚未整体通过。特别是跨文档候选策略的受控
> 消融已得出 `NO_PROMOTION`，不能把有代码或有实验等同于默认策略已优化。

### [~] 1.1 中文 Sparse Baseline（CJK n-gram + 字段权重）

| 属性 | 内容 |
| --- | --- |
| **交付物** | CJK 字符 n-gram tokenizer + 元数据字段加权 |
| **完成标准** | 中文与混合查询的 Recall 显著高于当前基线（在评测集 v1 上验证） |
| **工作量** | M |
| **涉及文件** | 修改 `src/rag.py` 的 `_tokenize()`；新增 `src/lexical.py` |

> **当前回填：** `src/lexical.py` 已实现 CJK unigram/bigram tokenizer、字段
> 加权 BM25 语料和相应测试，生产 RAG 已调用该词法路径。尚无按本计划定义的
> 独立、获准的中文/混合 Recall 净收益结论，故不标为效果完成。

> **⚠️ 与 1.2 的执行顺序依赖**：若 1.2 决定切换 embedding 模型（如 bge-m3），会全量重建索引，使 1.1 在旧模型上验证的 sparse 结论需在新模型上重测。建议两者合并为一次「sparse + dense 联合基线对比」，或明确「1.2 切换模型后，1.1 的 Recall 对比必须在新模型上重跑」。

**实施步骤**：

1. 实现 CJK n-gram tokenizer：英文/数字按空格和标点分词，CJK 字符按 bigram/trigram 切分
2. 将文件名、标题、section、页码等元数据作为独立可加权字段加入 BM25 索引
3. 在评测集 v1 上对比当前 tokenizer vs n-gram tokenizer 的 Recall 差异
4. 如果产品语料偏自然语言，再评测中文分词器（如 jieba）作为可选方案
5. 将 tokenizer 配置纳入 manifest 指纹

**关键代码位置**：
- 当前 tokenizer：`src/rag.py:1090-1092`（连续 CJK 被当作一个 token）
- BM25 构建：`src/rag.py:866-878`
- 分块分隔符：`src/rag.py:153-170`（缺少中文标点 `。！？；`）

### [~] 1.2 多语种 Embedding 对比

| 属性 | 内容 |
| --- | --- |
| **交付物** | 当前 `all-MiniLM-L6-v2` 与 1-2 个多语种候选的离线对比结果 |
| **完成标准** | 以质量/延迟/内存共同决策是否切换模型 |
| **工作量** | M |
| **涉及文件** | 修改 `src/rag.py` 的 embedding 加载逻辑；新增 `evaluation/embedding_benchmark.py` |

> **当前回填：** `evaluation/embedding_benchmark.py` 已存在，模型与 manifest
> 配置入口也已集中；默认仍为 `all-MiniLM-L6-v2`，没有已验收的多语种候选
> 对比结论或默认模型切换，故保留 `[~]`。

**实施步骤**：

1. 在评测集 v1 上测量当前 `all-MiniLM-L6-v2` 的 dense retrieval 基线
2. 候选模型：`BAAI/bge-m3`（dense/sparse/multi-vector，100+ 语言）、`intfloat/multilingual-e5-base`（100 种语言）
3. 对比维度：Recall@K、索引构建时间、查询延迟、内存占用、索引体积
4. 记录对比结果，决定是否切换默认模型
5. 将 embedding 模型、query/document 前缀、归一化方式纳入 manifest 指纹

**关键代码位置**：
- 当前 embedding 加载：`src/rag.py:67-74`

### [x] 1.3 统一 Candidate 模型与 Top-K 语义

| 属性 | 内容 |
| --- | --- |
| **交付物** | `RetrievalCandidate` 数据类 + candidate/rerank/context 三层 K 分离 |
| **完成标准** | 每个候选保留各通道 raw/normalized score；UI、指标、来源与真实 prompt 一致 |
| **工作量** | S |
| **涉及文件** | 新增 `src/domain.py`；修改 `src/rag.py`、`src/metrics.py`、`tui/dialogs/status.py` |

> **当前回填：** `RetrievalCandidate`、`compute_context_k`、candidate/selector/
> context 漏斗和与实际 context 同口径的 sources/citation ID 已在当前生产路径
> 实现；P0.1–P0.2.1 又验证了流式、非流式、TUI、CLI 与 Graph 的来源展示/
> citation status 一致性。本项的核心语义交付已完成。

**实施步骤**：

1. 定义 `RetrievalCandidate` 数据类：包含 `dense_similarity`、`bm25_score`、各通道 rank、RRF score、graph score、rerank score、source_id、chunk_id
2. 明确三层 K 语义：
   - `candidate_k`：各通道召回的候选数（当前 dynamic_top_k 的输出）
   - `rerank_k`：重排后保留的候选数（阶段 1.4 引入 reranker 后生效）
   - `context_k`：最终进入 LLM prompt 的证据数（当前硬编码为 5，改为 token budget 控制）
3. 修复 `_build_context()` 的 `top_indices[:5]` 硬编码（`src/rag.py:1170-1186`）
4. 修复 `format_sources()` 的 `indices[:5]` 硬编码（`src/rag.py:1340-1347`）
5. 修复 `selected_count` 指标：记录实际进入 prompt 的数量，而非 dynamic_top_k 的值
6. 来源展示只展示实际进入 prompt 的证据

**关键代码位置**：
- `_build_context()` 硬编码前 5：`src/rag.py:1170-1186`
- `format_sources()` 硬编码前 5：`src/rag.py:1340-1347`
- `selected_count` 记录为 22 而非实际 5：`src/rag.py:1385-1406`

### [~] 1.4 Reranker

| 属性 | 内容 |
| --- | --- |
| **交付物** | Top 20-50 候选重排到 context 5-10 |
| **完成标准** | Context precision 上升且 recall 不显著下降（在评测集 v1 上验证） |
| **工作量** | M |
| **涉及文件** | 新增 `src/retrieval.py`；修改 `src/rag.py` 的融合逻辑 |

> **当前回填：** `src/retrieval.py` 已提供 CrossEncoder reranker、统一 selector
> 和同源覆盖约束，生产路径可通过配置启用；默认仍为关闭，且没有本计划要求的
> context precision/recall 净收益验收，因此保留 `[~]`。

**实施步骤**：

1. 选型：本地 cross-encoder reranker（如 `cross-encoder/ms-marco-MiniLM-L-6-v2`）或 LLM-based reranker
2. 实现 reranker 接口：输入候选列表 + query，输出重排后列表 + rerank score
3. 在融合排名后、上下文构建前插入 reranker 步骤
4. 在评测集 v1 上对比有/无 reranker 的 context precision/recall
5. 加入每来源上限、子查询覆盖约束：跨文档问题优先覆盖不同来源

### [~] 1.5 拒答校准

| 属性 | 内容 |
| --- | --- |
| **交付物** | 基于 reranker top score、top1-top2 margin、有效来源数等可解释特征的拒答机制 |
| **完成标准** | 在有/无答案标注集上达到预设 precision/recall；避免默认总放行 |
| **工作量** | M |
| **涉及文件** | 修改 `src/rag.py` 的拒答逻辑；新增 `src/retrieval.py` 的拒答判断 |

> **当前回填：** 可解释特征提取、拒答策略/阈值的评测与消融工具已存在；默认
> 生产拒答仍不能被表述为已完成的全局校准，且没有已获准的阈值提升结论，故
> 保留 `[~]`。

**实施步骤**：

1. 让每个候选保留原始相关性特征（dense_similarity、bm25_score、rerank score）
2. 实现可解释拒答特征：reranker top score、top1-top2 margin、有效来源数、query 类型
3. 在评测集 v1 的 `should_refuse` 子集上选阈值
4. 分开记录检索拒答、生成拒答、API 错误，不把三者都当作普通回答文本
5. 修复当前 RRF 阈值问题：`1/(rank+30)` 导致任一通道第一名就超过默认阈值 0.03

**关键代码位置**：
- RRF 计算：`src/rag.py:1131-1153`（`1/(rank+30)` 导致阈值形同虚设）
- 拒答阈值：`src/rag.py:180-184,1375-1382`（默认 0.03）
- BM25 不剔除 0 分文档：`src/rag.py:1282-1324`

### [x] 1.6 引用闭环

| 属性 | 内容 |
| --- | --- |
| **交付物** | 引用 ID 校验 + 一次修复 + 失败状态标记 |
| **完成标准** | 非法引用率降为 0；无引用事实可检测 |
| **工作量** | M |
| **涉及文件** | 修改 `src/rag.py` 的回答路径；利用 `src/citations.py:63-69` |

> **当前回填（安全策略替代原第 2 步）：** 已完成 citation ID 校验、来源同口径
> 显示和 `verified`/`unverified`/`not_required` 终态：覆盖 Standard/Graph、
> stream/non-stream、TUI/CLI/pipeline。非法编号保留原文并明确标记为
> `unverified`，**不**再用额外 LLM 调用把 `[S99]` 猜测性改写为 `[S1]`；这是
> 对原“自动修复”步骤的安全替代，而不是声称非法编号从回答中消失。语义
> faithfulness 与 citation precision/recall 仍应由生成评测独立衡量。

**实施步骤**：

1. 在 `answer_query()` 和 `answer_query_stream()` 生成结束后，调用 `src/citations.py` 的 `validate_citations()` 校验引用 ID
2. 非法 ID 触发一次受限修复：向 LLM 发送"请修正以下非法引用"的修复请求
3. 修复仍失败则明确标记回答为"不可验证"，TUI 展示警告
4. 对需要事实依据的回答要求至少一个有效引用；纯对话/操作说明按 query 类型豁免
5. 在评测集 v1 上测量 citation precision/recall

**关键代码位置**：
- 已有引用校验函数：`src/citations.py:63-69`
- 回答路径未调用校验：`src/rag.py` 的 `answer_query()`、`answer_query_stream()`
- Graph 回答路径也未调用校验：`src/graph_rag.py`

---

## 四、阶段 2：结构化摄取与多轮效果（P1）

> **目标**：提升文档解析质量，让多轮问答的检索也能利用历史上下文。
> **预计工作量**：3 个中等工作项 + 1 个大工作项 ≈ 5-6 周
> **前置条件**：阶段 1 完成（Standard RAG 效果闭环已建立）
>
> **当前进度：** `[~]` 结构化模型、loader、parent/adjacent 和 history-aware
> rewrite 已有实现。2.3 已于 2026-08-28 通过「失败可见、可回退」端到端验收
> （`STAGE2_23_ACCEPTED`）；2.4 已于同日通过受控多轮 A/B/C 验收门禁
> （`STAGE2_24_ACCEPTED`）；2.2 于同日通过 round-3 终审
> （`STAGE2_22_ACCEPTED`，containment-aware 主指标）；2.1 已收口 `[x]`。
> **阶段 2 四个子项全部完成。**

### [x] 2.1 标准文档模型

| 属性 | 内容 |
| --- | --- |
| **交付物** | `Document → Section → Chunk` 数据模型，所有 parser 产出统一 schema |
| **完成标准** | section、page、type、parser version 均可追溯 |
| **工作量** | M |
| **涉及文件** | 新增 `src/domain.py` 的文档模型；新增 `src/loaders/` 目录；修改 `src/rag.py` 的解析逻辑 |

> **当前回填：** `Document`、`Section`、`Chunk` 数据模型，`src/loaders/` 的
> PDF/DOCX/text loader 与 `src/chunking.py` 已实现并进入当前 parser 路径。旧
> 兼容解析函数仍存在，且所有格式/质量提示的端到端产品验收尚未完成，故保留
> `[~]`。
>
> 2026-08-28：旧降级路径已显式化（结构化警告 + source record `parse_degraded`
> 标记随 index manifest 可追溯，移除调试堆栈残留）。
>
> 2026-08-28 收口：`[~]` → `[x]`。完成标准「section、page、type、parser
> version 均可追溯」由端到端验收锁定
> （`tests/test_document_model_traceability.py`）：chunk metadata 与 manifest
> source record 均携带四项字段——parser_version 落库（pdf 2.0 / docx、text
> 1.0 / 旧路径 legacy-1.0）；section 追溯口径 = 字段在场 + section_type
> 非空（无标题节 heading 合法为空，标题路径以至少一块非空 heading 可证）。
> 格式/质量提示端到端产品验收由同日 2.3 验收（`STAGE2_23_ACCEPTED`）覆盖；
> 旧兼容路径处置遵 owner 批示「保留但显式可见」（降级警告 + `legacy-1.0`
> 代次标注 + manifest 可追溯）。

**实施步骤**：

1. 定义 `Document`、`Section`、`Chunk` 数据类：包含标题路径、页码、section type、字符/token 范围、解析器版本
2. 将 PDF/DOCX/text 解析逻辑从 `src/rag.py` 迁移到 `src/loaders/` 下的独立模块
3. 每个 loader 输出统一的 `Document` 对象
4. 分格式建立质量等级：原生文本、结构化解析、OCR；TUI 在低质量解析时提示用户

### [x] 2.2 Parent-Child / 邻接扩展

| 属性 | 内容 |
| --- | --- |
| **交付物** | 小 chunk 召回 + 大 parent/邻接窗口回答 |
| **完成标准** | 跨边界问答的 context recall 提升（在评测集 v1 上验证） |
| **工作量** | M |
| **涉及文件** | 新增 `src/chunking.py`；修改 `src/rag.py` 的分块和上下文构建逻辑 |

> **当前回填：** parent-child、邻接扩展、anchor 与 context budget 已在
> `src/chunking.py`/`src.rag` 实现并受回归测试保护；尚无满足本项标准的
> context recall 净收益结论，故不标为效果完成。
>
> 2026-08-28 A/B 实验（`evaluation/parentchild_ab.py`，n=71，单因子由
> 共享 QueryPlan 构造保证）：chunk 级 context recall 均值 OFF 0.434 →
> ON 0.553（+11.9pp ≥ 预注册 0.05），但 mixed-009 出现 1.00 → 0.00 的
> 扩展挤占回退（3 例恶化 / 13 例改善 / 55 例不变），单例护栏拦截 →
> `STAGE2_22_NOT_PROVEN`（`results/stage2-parentchild/report-2026-08-28.md`）。
> 产品线登记：扩展预算策略（高分原始块保留槽位 / parent 与同级 child 去重 /
> 扩展时放大 context_k）；`RAG_CONTEXT_EXPANSION=off` 保留为生产逃生阀。
>
> 2026-08-28 第 2 轮（预算调和修复后重跑）：新增
> `reconcile_expansion_budget`（select 代表块保序优先 + 预算下限 ≥ 代表块数，
> 扩展结构上不可能再挤占召回证据）——真挤占案例 3→0（mixed-009 型修复证实），
> 唯一残差 en-017 为**度量仪器失明**：真值 child 块全文包含于在场 parent 块
> （机械验证 15⊆13），chunk-id 集合交集对 parent 替换结构性计 0；
> containment-corrected 诊断 Δ=+0.1373 / worst=+0.00（非门禁量）。
> 冻结门禁仍判 `STAGE2_22_NOT_PROVEN`，保持 `[~]`；
> 下一轮预注册提案（主指标改 containment-aware 匹配，阈值不变）待 owner 批准
> （`results/stage2-parentchild/report-2026-08-28-run2.md`）。附带登记：
> 邻接扩展无最小块长守卫（4 字符碎块入 context）、parent 划分质量专项。
>
> 2026-08-28 第 3 轮终审：owner 批准 round-3 预注册修订（修仪器非调阈值，
> 阈值冻结不变）——主指标改 containment-aware 真值匹配（id 命中，或真值
> 文本空白归一后被任一 context 块文本包含；空文本真值显式排除），密封
> manifest 记 `metric_version = r3-containment-aware`；复用 run-2 同一沙箱
> 索引快照（dataset sha 与 corpus 文件逐一一致，单变量只换仪器）。重跑
> n=71：mean OFF 0.4377 → ON 0.5680（**Δ=+0.1303 ≥ 0.05**），worst_case
> **0.0**（71 例无一恶化）→ **`STAGE2_22_ACCEPTED`**，2.2 `[~]→[x]`。
> en-017 复核：ON 臂 context 含 parent chunk_13，真值 chunk_15 文本包含于
> 其间 → recall 1.0（round-2 失明案例消解）。产物
> `results/stage2-parentchild/run-3-2026-08-28/`（自哈希复算 OK）、报告
> `report-2026-08-28-run3.md`。预算调和修复作为行为改进独立于门禁保留；
> 附带登记两项（邻接最小块长守卫、parent 划分质量）仍留产品线。

**实施步骤**：

1. 实现结构化分块：基于标题、段落、表格等结构信号分块，而非纯字符切分
2. 实现 parent-child 关系：小 chunk 负责召回，关联的 parent chunk 负责提供完整上下文
3. 实现邻接扩展：召回某个 chunk 时，自动包含其前后相邻 chunk
4. PDF 首页 anchor 在索引阶段持久化，不再查询时重读源 PDF
5. 在评测集 v1 上对比有/无 parent-child 的 context recall

### [x] 2.3 PDF/DOCX 重点解析

| 属性 | 内容 |
| --- | --- |
| **交付物** | 表格提取、标题层级、低质量检测与回退 |
| **完成标准** | 目标格式的解析失败可见、可回退 |
| **工作量** | L |
| **涉及文件** | 修改 `src/loaders/pdf_loader.py`、`src/loaders/docx_loader.py` |

> **当前回填：** PDF/DOCX loaders 已支持标题层级、表格、解析质量与回退路径；
> 真实用户主要格式的低质量率、失败可见性与 TUI 回退验收仍未形成完整门禁，故
> 保留 `[~]`。
>
> 2026-08-28 验收闭环：`[~]` → `[x]`（`STAGE2_23_ACCEPTED`）。fitz 程序化
> 夹具矩阵（原生 PDF / 仿真扫描件 / 空 txt / loader 异常 / 正常 docx+txt）
> 证明三条可见性通道（CLI 警告、结构化诊断 sink、TUI warning_panel 于初始
> 建库与 /files add 呈现）同时成立且降级可回退
> （`results/stage2-parsing-acceptance/report-2026-08-28.md`）。边界如实
> 入档：降级路径非无条件兜底（旧路径同样失败时显式跳过该文件）；
> `prepare_graph_index` 未接诊断 sink（standard 路径专属）。

**实施步骤**：

1. PDF：引入表格提取（如 pdfplumber 或 camelot）、标题层级识别、低质量扫描页检测
2. DOCX：提取表格、页眉页脚、列表结构
3. 实现低质量检测：空文本率、低质量页率、每格式失败率
4. 解析失败必须可见，不能静默建立空索引
5. 优先支持真实使用最多的 2-3 种格式，不继续扩大"纯文本兼容"扩展名列表

### [x] 2.4 多轮检索改写

| 属性 | 内容 |
| --- | --- |
| **交付物** | History-aware standalone query rewrite + 原查询保底召回 |
| **完成标准** | 代词追问集显著优于当前基线（在评测集 v1 的多轮子集上验证） |
| **工作量** | M |
| **涉及文件** | 修改 `src/rag.py` 的检索入口；新增 `src/rag_query_rewriter.py` |

> **当前回填（2026-08-28 验收闭环）：** 受控 A/B/C 回放（`evaluation/multiturn_replay.py`，
> 走生产 prepare/generate 拆分路径；canonical history 臂内自洽）在 v1 多轮子集
> 3 链 10 例上执行：追问 7 例 source recall 均值 A 0.857 → C 1.000
> （Δ=+0.143 ≥ 预注册 0.10，无单例恶化），门禁 `STAGE2_24_ACCEPTED`；
> 拒答翻转（multi-010：无历史裸查被检索前哨拒答，rewrite 注入历史后证据入场）
> 完整复现本项设计目标现象。天花板效应与 n=7 方向性局限见
> `results/stage2-multiturn/report-2026-08-28.md` 披露。`[~]` → `[x]`。

**实施步骤**：

1. 在检索前增加 history-aware standalone query rewrite：利用最近 5 轮历史，将省略主语的追问改写为独立可检索问题
2. 将"上下文消歧"和"多意图拆解"分成两个步骤，避免一个 prompt 同时承担代词解析、语言切分和查询扩展
3. 漂移防护：保留原 query 一路召回，与 rewrite 结果合并去重
4. 记录 rewrite 文本与原查询的结果覆盖差异
5. 在评测集 v1 的多轮子集上对比有/无 rewrite 的 Recall

**关键代码位置**：
- 历史只进入生成：`src/rag.py:1415-1427`
- 检索只用当前 query：`src/rag.py:1462-1511,1636-1695`

---

## 五、阶段 3：性能、运维与规模（P1/P2）

> **目标**：消除冷启动瓶颈，统一配置，提升可观测性，为更大规模语料做准备。
> **预计工作量**：3 个中等工作项 + 1 个大工作项 + 2 个小工作项 ≈ 5-6 周
> **前置条件**：阶段 2 完成（效果闭环已建立，可以安全优化性能）
>
> **当前进度：** `[~]` 配置、模型缓存、LLM gateway、BM25 snapshot 和来源
> 生命周期 API 已有实装；持久化观测、规模预算与完整用户工作流仍未封闭。

### [~] 3.1 单例模型与统一 LLM Gateway

| 属性 | 内容 |
| --- | --- |
| **交付物** | 进程级模型缓存 + 统一 LLM gateway（timeout、retry、cancel、usage） |
| **完成标准** | 无重复加载；错误分类可见；网络异常时 TUI 不会长时间停在 thinking 状态 |
| **工作量** | M |
| **涉及文件** | 新增 `src/llm_gateway.py`；修改 `src/rag.py`、`tui/service.py`、`src/graph_rag.py` |

> **当前回填：** `src.llm_gateway`、进程级 embedding model cache、错误分类和
> retry/timeout 路径已存在；取消、并发上限、真实成本/延迟目标与拆解收益的完整
> 观测未完成，故保留 `[~]`。

**实施步骤**：

1. 服务实例只持有一个 embedding model；`prepare_index()` 接受已加载 model 或使用进程级线程安全缓存
2. 封装统一 LLM gateway：连接池、timeout、有限重试、退避、取消、并发上限、错误分类、token 使用统计
3. **增强**现有 `should_decompose()` 确定性守卫规则（`src/rag_query_decomposer.py:37-44`）：当前仅跳过 ≤4 字或单个英文单词，中文 4 字以上简单问题仍会调 LLM；增加中文简单问题判断（如不含多意图关键词、不含中英混合），减少不必要的 LLM 调用
4. 对拆解带来的 Recall 增益和额外延迟分别计量

**关键代码位置**：
- 重复模型加载：`tui/service.py:52-75` + `src/rag.py:843-861`
- ModelScope 重复下载：`src/rag.py` 的 `_load_sentence_transformer()`
- 查询拆解守卫规则过弱：`src/rag_query_decomposer.py:37-44`（`should_decompose()` 仅跳过 ≤4 字或单个英文单词，中文简单问题仍调 LLM）
- 缺少统一 timeout：`src/rag.py:1430-1460,1601-1633`；`src/graph_rag.py:66-138`

### [x] 3.2 数据目录与配置统一

| 属性 | 内容 |
| --- | --- |
| **交付物** | `MNEME_DATA_DIR` 环境变量 + `Settings` 配置类 |
| **完成标准** | 包目录只读也可运行；CLI/TUI 默认一致；所有配置有文档 |
| **工作量** | S |
| **涉及文件** | 新增 `src/config.py`；修改 `src/rag.py`、`tui/app.py`、`.env.example` |

> **当前状态（第六轮返工完成，待独立验收，保持 `[~]`）：** 独立验收第六轮
> 复现的配置契约绕过已修复并 TDD 验证：① **共享 ALPHA 校验**
> （`src/config.py` 新增 `validate_alpha`：仅接受有限、非布尔数值且
> 0.0–1.0，拒绝 NaN/inf/非数字/布尔，错误信息含 `ALPHA`）；Settings 与
> 全部显式覆盖入口（`graph_rag_pipeline`/`graph_query_stream`/
> `cli_loop._graph_rag_answer`）共用——`alpha=2.0` 曾进入
> `prepare_graph_index()` 写路径、`alpha=nan` 曾进入 retrieval、CLI
> Graph 路径 `alpha=2.0` 曾进入 retrieval，现均在索引构建/检索前抛含
> 配置名的 ValueError 且调用数 0。② **用户 Top-K 范围容器校验**：新增
> `validate_user_top_k_container`（`validate_user_top_k_range` 兼容
> 保留），RAG/Graph 流式入口在任何下标使用、`max(top_k_range)`、
> planner/retrieval 之前完成——`(3,20,999)` 曾只验前两个元素进入
> planner/retrieval、`(3,)` 曾抛 IndexError；现 `(3,20,999)`/`(3,)`/
> 非序列/布尔/浮点均抛含 `LLM_TOP_K_MIN`/`LLM_TOP_K_MAX` 的
> ValueError 且调用数 0；用户 3–20 与内部 70/12/70、Graph 内部 3/50
> 的分离未变。③ **gateway 直接调用温度 fail-fast**：`llm_gateway.llm_call`
> 在创建 client/发起请求前对最终 temperature（显式或 Settings 解析）
> 统一校验（`temperature=2.5` 曾到达 `client.chat.completions.create`）；
> `llm_call_safe` 非法温度零 client/零网络。④ **布尔值拒绝**：
> `validate_llm_temperature(True)` 曾返回 1.0，现拒绝 True/False；
> 合法字符串数值保留（测试说明）。⑤ **文档修正**：`.env.example`/
> README 的 `BASE_URL` 明确为必填 gateway 配置（无内置默认值），不再
> 虚构默认值。未改检索策略、dynamic Top-K 数值、拒答默认策略、
> reranker、Graph 默认策略、citation 语义、`RAG_REFUSAL_THRESHOLD`
> G1-S 语义（G1-S/Graph/CLI 回归零漂移）。TDD：新增
> `tests/test_config_remediation6_contract.py`（31 个）：RED 26 failed /
> 5 passed（5 个通过项为修复前即满足的锁定测试，如实标注）→
> GREEN 31 passed；配置契约 + remediation2/3/4/5/6 + gateway +
> env_security + onboarding **216 passed**；planner/capture/Graph/CLI/
> citation/retrieval/refusal 回归（13 文件）**298 passed / 4 skipped**；
> 清空真实凭据 + CWD=系统 temp 隔离验证 **133 passed / 4 skipped**；
> py_compile 6/6、C 线 `git diff --check` 通过（新增文件
> `--no-index --check` 无 whitespace 错误、手工字节扫描 CLEAN）。
> 本项已由独立验收确认完成，见下方最终验收记录。
>
> **最终验收（2026-08-17，`C_3_2_DECISION = ACCEPT_C32_COMPLETE`）：** 第七轮 TUI 配置边界与 remediation2 测试清理已闭环；remediation2–6 组合 **86 passed**，完整配置组 **148 passed**，TUI/onboarding/env 组 **39 passed**，第七轮契约测试 **4 passed**，fresh-process smoke **5/5**，静态检查全部通过。所有验证使用系统临时目录、fake/fail-fast gateway 与 socket 阻断，证明零真实 LLM/API/网络/ModelScope 调用；未提交、推送或发布。
>
> 已知未解决边界保留为后续项且不阻断本项完成：`docker-compose` 挂载方向、G1-S 拒答容错语义、CLI 用户 Top-K 覆盖入口。上述边界不属于本次 3.2 收尾范围。
>
> **当前状态（第五轮返工完成，待独立验收，保持 `[~]`）：** 独立验收第五轮
> 复现的 fail-fast 缺口已修复并 TDD 验证：① **共享校验器**（`src/config.py`
> 新增 `validate_llm_temperature`：有限数值且 0.0–2.0，拒绝 NaN/inf/非数字、
> 错误信息含 `LLM_TEMPERATURE`；`validate_user_top_k_range`：两个整数均 ≥ 1
> 且 min ≤ max、错误信息关联 `LLM_TOP_K_MIN`/`LLM_TOP_K_MAX`）；`Settings`
> 与全部显式覆盖入口共用同一规则。② **显式覆盖 fail-fast**——
> `answer_query`/`answer_query_stream`（校验在计算 `max(top_k_range)` 与
> `_plan_query_runtime` 之前）/`prepare_answer_evidence`/`_plan_query_runtime`/
> `generate_answer`/`answer_with_llm_history(_stream)`/`graph_rag` 入口均在
> 进入规划器、检索器、LLM gateway 或写路径之前校验——实测复现
> （`temperature=2.5` 曾进入规划器触发 rewrite/decompose LLM 路径；
> `top_k_range=(0, 20)` 曾以检索宽度 20 进入规划器）修复后非法值抛含配置名
> 的 ValueError 且 planner/retrieval/gateway 调用数均为 0。③ 合法路径不变：
> 显式 0.66 继续优先并贯穿 rewrite/decompose；合法 `(3, 20)` 检索宽度仍为
> 20；未改模型选择、检索宽度策略、动态 Top-K、拒答、reranker、Graph 默认
> 策略、citation 语义（G1-S 零漂移）。④ `tests/test_query_plan_capture.py`
> 移除文件末尾多余空行（字节级，未格式化无关内容）。TDD：新增
> `tests/test_config_remediation5_contract.py`（17 个）：RED 16 failed /
> 1 passed（1 个通过项为合法路径锁定测试，修复前即应通过，如实标注）→
> GREEN 17 passed；配置契约 + remediation2/3/4/5 + gateway + env_security +
> onboarding **185 passed**；planner/capture/Graph/CLI/citation/retrieval/
> refusal 回归（13 文件）**298 passed / 4 skipped**；py_compile、C 线
> `git diff --check` 通过（新增文件 `--no-index --check` 无 whitespace
> 错误、手工扫描 CLEAN）。本项保持 `[~]` 直至新的独立验收确认。
>
> **当前状态（第四轮返工完成，待独立验收，保持 `[~]`）：** 独立验收第四轮
> 复现的两个配置契约缺口已修复并 TDD 验证：① **显式 temperature 贯穿查询
> 规划**——`src/rag._plan_query_runtime()` 新增向后兼容可选参数
> `llm_temperature`（None 时调用期回退 `Settings.llm_temperature`，未传参
> 行为不变）；`prepare_answer_evidence()` 转发该值；`answer_query()`/
> `answer_query_stream()` 把各自已解析的显式温度传入规划路径——Settings
> 0.10 + 显式 0.66 时，真实规划路径的 fake rewrite/decompose gateway
> 观察到 0.66（同步/流式均锁定；未改模型选择、检索宽度、provenance/
> capture 语义）。② **TUI 温度范围统一 0.0–2.0**——`tui/screens/chat.py`
> 提示与合法范围对齐 Settings/.env.example/README：合法 1.5 原样写入并
> `reset_settings()` 立即生效；>2/<0/非数字显示明确错误、不写入 .env、
> 不重置 Settings、不静默 clamp。TDD：新增
> `tests/test_config_remediation4_contract.py`（11 个）：RED 9 failed /
> 2 passed（2 个通过项为回退行为锁定测试，修复前即应通过，如实标注）→
> GREEN 11 passed；配置三组 + remediation2/3/4 + gateway + env_security
> **155 passed**；planner/capture/Graph/CLI/citation/retrieval/refusal
> 回归 **258 passed / 4 skipped**；清空真实凭据 + CWD=系统 temp 隔离验证
> **96 passed / 4 skipped**；fresh-process smoke 覆盖环境变量优先、CWD
> `.env`、路径稳定、离线 ModelScope 零调用、显式温度优先。py_compile、
> C 线 `git diff --check` 通过。本项保持 `[~]` 直至新的独立验收确认。
>
> **当前状态（第三轮返工完成，待独立验收，保持 `[~]`）：** 独立验收第三轮
> 复现的配置契约缺口已修复并 TDD 验证：① `src/rag_query_decomposer.py` /
> `src/rag_query_rewriter.py` 删除自行 `load_dotenv()`——`.env` 仅由
> `src.config` 统一加载（源码扫描 + fresh-process 导入探针锁定；API_KEY/
> BASE_URL 仍属 gateway 边界，两模块只做读取预检）；② 两模块受管
> `model`/`temperature` 参数默认改 None、调用期从 Settings 解析（显式参数
> 优先；不再有未说明的 `deepseek-chat`/`0.0` 默认分叉；G1-S provenance
> 记录解析后生效值）；③ `src/rag._plan_query_runtime()` 同时解析并传递
> `llm_model` 与 `llm_temperature` 给 rewrite/decompose——`LLM_TEMPERATURE=0.66`
> 经真实 planning 路径到达 fake gateway 时值仍为 0.66（测试锁定）；未改
> 检索算法/Top-K/拒答/reranker/Graph 策略/citation 语义。④ 测试隔离修复：
> `tests/test_config_remediation2_contract.py` 两个 gateway 调用测试与
> `tests/test_llm_gateway.py` 两个 extra_body 测试显式设置 fake
> API_KEY/BASE_URL 并继续 mock `_get_client`；`test_query_plan_capture.py`
> 的 rewrite 薄包装测试改为确定性 fake（不再依赖真实 .env/凭据泄漏）。
> TDD：新增 `tests/test_config_remediation3_contract.py`（6 个）：
> RED 4 failed / 2 passed（2 个通过项为 fresh-process 导入探针与显式参数
> 优先锁定测试，修复前即应通过，如实标注）→ GREEN 6 passed；配置三组 +
> remediation2/3 + gateway + env_security **144 passed**；planner/capture/
> Graph/citation/retrieval 回归 **239 passed / 4 skipped**；清空真实凭据 +
> CWD=系统 temp 的隔离验证 **177 passed / 4 skipped**（仅
> `test_query_plan_capture_hardening` 的 CWD 假设测试需在仓库根运行，
> 仓库根下 239 passed 含其通过）。py_compile、C 线 `git diff --check` 通过。
> 本项保持 `[~]` 直至新的独立验收确认。
>
> **当前状态（第二轮返工完成，待独立验收，保持 `[~]`）：** 独立验收第二轮
> 复现的五个配置契约缺口已按返工包修复并 TDD 验证：① `src/llm_gateway.py`
> 移除自行 `load_dotenv()`（package-root `.env` 不再偷进 gateway 进程）与
> `os.getenv("LLM_MODEL", ...)` 绕过——LLM model/temperature 委托 Settings
> 调用期解析，`API_KEY`/`BASE_URL` 保留在 gateway 边界（只读进程环境，不
> 自行加载 .env）；② `.env`/reset 真实契约：进程环境变量 > CWD `.env` >
> 默认值，`reset_settings()` 真实反映 `.env` 文件修改（新值/新增键/删除键），
> 且绝不覆盖显式进程环境变量（含运行期被外部改写的键）；③ reset 后无陈旧
> 消费者：`graph_rag`/`tui.service` 不再 by-value 导入 `CHROMA_DB_PATH`/
> `EMBEDDING_MODEL_NAME`（改为调用期解析 `_graph_chroma_db_path()`/
> `_graph_embedding_model_name()`/`LocalRagService._chroma_db_path()`），
> `security` 资源上限注册刷新回调，TUI `/models` 与 `/settings → LLM Model`
> 改后走同一 `reset_settings()` 刷新路径并落到实际 LLM 调用参数；④ Graph
> 内部动态 Top-K 恢复既有固定 **3/50**（`GRAPH_DYNAMIC_MIN_K/MAX_K`，
> 与用户 Top-K 3–20 名称/消费者/中英文文档明确区分），`graph_query_stream`
> 用户区间仍为 3–20（默认从 Settings 解析）；⑤ `EMBEDDING_MODEL_PATH` 在
> Settings 构造时完成 `~` 展开与相对路径绝对化，调用期 CWD 改变后 loader
> 参数不漂移。TDD：新增 `tests/test_config_remediation2_contract.py`
> （20 个 fresh-process/进程内契约测试）+ 更新 CLI Graph Top-K 断言：
> RED 21 failed / 1 passed → GREEN 22 passed；受影响回归组 326 passed。
> 本项保持 `[~]` 直至新的独立验收确认。
>
> **当前状态（首轮返工完成，待独立验收，2026-08-13，保持 `[~]`）：** 独立验收
> 发现的启动配置分叉已按返工包修复并验证：唯一启动配置入口
> （`<启动目录>/.env` 在任何 Settings 构造前加载、进程 env 始终优先）、
> RAG 模块级常量随 `reset_settings()` 刷新回调同步、RAG/TUI/CLI/Graph
> 默认参数在调用期消费已解析 Settings、`validate_document_path` 使用已解析
> `document_root`（启动后不随 CWD 漂移）、真实 fresh-process 契约测试
> （`tests/test_config_startup_contract.py`，11 个）。TDD：RED 11 failed /
> 51 passed → GREEN 62 passed；受影响回归组 635 passed；全量 pytest
> 2566 passed / 8 skipped（exit 0）。完成标准三项已满足并验证，但首轮
> 闭环声明曾被独立验收推翻，本项保持 `[~]` 直至新的独立验收确认。
> 已知后续项（不阻塞）：`docker-compose.yml` 的 `./chroma_db` 与 `./models`
> 挂载仍指向旧路径语义，需另行统一。
>
> **2026-08-14 独立验收结论：`C_3_2_DECISION = STOP_C32_ACCEPTANCE_FAILED`**
> （报告：`results/config-contract-acceptance/c32-acceptance-report.md`）。
> 9 项门槛独立复核 8 项通过（Settings 唯一默认值来源、MNEME_DATA_DIR
> 默认/~展开/相对→绝对/落点/零写入、.env 优先级与 reset 生效、Top-K
> (3,20) 与内部宽度 (70,12,70) 分离、非法配置导入期 fail-fast、
> MNEME_OFFLINE 精确承诺、无新增 capture/遥测/检索算法变化、受保护资产
> 367 文件全量测试前后字节身份一致；配置定向 147 passed、相关回归
> 275 passed、全量 pytest 2566 passed / 8 skipped、编译 68/68、
> git diff --check 通过）。**阻断缺陷（另开修复任务，未自行修复）**：
> TUI 会话内 LLM 模型切换回归——`tui/service.py::_llm_model` 改读缓存
> Settings 后，`tui/screens/chat.py` 的 `/models` 与 `/settings → LLM Model`
> 只写 `.env`/`os.environ` 而不调用 `reset_settings()`，会话内切换不再
> 即时生效（fresh-process 探针复现：仅 reset 后生效；返工前该路径为
> 调用期 os.getenv 读取、即时生效）。本项保持 `[~]`，待修复后重新验收。

**实施步骤**：

1. 实现 `Settings` 类：集中管理模型 ID、本地路径、cache dir、下载策略、数据目录
2. Chroma 数据目录改为 `MNEME_DATA_DIR/chroma_db`（默认 `~/.mneme/chroma_db`），不再写入 `src/chroma_db`
3. 统一 CLI 与 TUI 的默认值：temperature、Top-K 范围等
4. 离线模式不能隐式触发远程 ModelScope 下载
5. `RAG_REFUSAL_THRESHOLD` 等配置项加入文档

**关键代码位置**：
- Chroma 路径硬编码：`src/rag.py:138-140`
- CLI/TUI 默认值不一致：`README.zh.md:191-194` vs `.env.example:10-17` vs `tui/app.py:20-30`

### [~] 3.3 持久化 Sparse / 增量更新

| 属性 | 内容 |
| --- | --- |
| **交付物** | 持久化词法索引 + 增量 BM25 更新 |
| **完成标准** | 目标规模下启动/增删达到 p95 预算 |
| **工作量** | L |
| **涉及文件** | 新增 `src/lexical.py`；修改 `src/rag.py` 的 BM25 构建逻辑 |

> **当前回填：** BM25 snapshot 的保存/加载/重建与增量词法更新路径已实现并有
> 专项测试；目标规模的启动、增删 p95 预算与更大规模全文索引迁移尚未验收，故
> 保留 `[~]`。

**实施步骤**：

1. 将 BM25 索引持久化到磁盘，避免每次启动全量重建
2. 实现增量更新：新增/删除文档时只更新受影响的词项
3. 超过预设 chunk 规模后迁移到持久化全文索引（如 Whoosh 或 SQLite FTS5）
4. 或按 collection/source 分片，避免 Python 内存 BM25 成为上限

**关键代码位置**：
- 全量读入内存构建 BM25：`src/rag.py:866-878`

### [~] 3.4 完整可观测性

| 属性 | 内容 |
| --- | --- |
| **交付物** | 分阶段延迟、TTFT、token、成本、有效证据数等指标 |
| **完成标准** | status 页与实际执行一致；所有异常可分类且可在 status 查到 |
| **工作量** | M |
| **涉及文件** | 修改 `src/metrics.py`；修改 `tui/dialogs/status.py` |

> **当前回填：** `MetricsRecorder` 与查询指标已存在，但默认生产 recorder 不
> 持久化 query-plan/response trace；Phase 6-F0 也已明确这不足以 exact replay。
> 本项不得标为完成。P1.1-G0（2026-08-13）已产出只做观测、不改策略的三级
> opt-in 契约设计：`plans/P1.1-PRODUCTION-OBSERVABILITY-REPLAY-CONTRACT-2026-08-13.md`；
> 实现与否取决于 owner 对 §6 决策表的批复。

**实施步骤**：

1. 扩展指标：索引耗时、embedding 耗时、query rewrite 耗时、各检索通道耗时、rerank 耗时、TTFT、总耗时、token 使用量、成本、引用有效率
2. 指标持久化：不再只保存最近 100 条内存记录
3. 文件监听回调不再静默吞掉异常（`tui/service.py:379-389`），记录最近失败、路径、重试状态
4. status 页展示实际进入 prompt 的证据数，而非候选数

**关键代码位置**：
- 当前指标只记录最近 100 条：`src/metrics.py:15-64`
- 监听回调静默吞异常：`tui/service.py:379-389`

### [~] 3.5 来源生命周期对账

| 属性 | 内容 |
| --- | --- |
| **交付物** | `sync_sources(desired_set)` 与 `add_sources(delta)` 两种 API |
| **完成标准** | CLI `--files` 语义文档化；删除前展示差异并要求显式确认 |
| **工作量** | S |
| **涉及文件** | 修改 `src/rag.py` 的 `build_index()` 和 `_ensure_client_and_check_rebuild()` |

> **当前回填：** `sync_sources(desired_set)`、`add_sources(delta)`、删除 API、
> manifest/snapshot 不可变保护均已存在；CLI 的显式确认语义和知识库级用户
> 工作流仍由独立 UX 计划管理，故保留 `[~]`。

**实施步骤**：

1. 明确两种 API：`sync_sources(desired_set)` 删除多余来源，`add_sources(delta)` 只增不删
2. CLI `--files` 默认采用 desired-set 语义，文档化
3. 删除前展示差异并要求显式 `--sync` 或 `--prune`
4. manifest 记录最近同步模式和时间，status 页展示 indexed sources 与当前选择的差异

**关键代码位置**：
- 只检查传入文件：`src/rag.py:806-834`
- 不删除多余来源：`src/rag.py:958-1018,1706-1743`

---

## 六、阶段 4：有条件地产品化 Graph RAG（P1）

> **目标**：只有阶段 0-2 的评测证明 Graph 对目标查询有净收益时才进入。
> **预计工作量**：视评测结果而定
> **前置条件**：阶段 0-2 完成，且评测证明 Graph 有显著净收益
>
> **当前进度：** `[!] NO_PROMOTION`。冻结 v2.0.11 上的受控跨文档检索消融
> 已记录候选策略相对基线的 Recall@5、nDCG@10、MRR 下滑，未通过预设 gate。
> 这不是“待补一个测试”或“已完成待发布”：在新的、独立且预先注册的净收益证据
> 出现前，Graph 不得作为默认产品策略推进。

### [ ] 4.1 实体 Schema 与确定性图构建

| 属性 | 内容 |
| --- | --- |
| **交付物** | 受 schema 约束的 JSON 实体抽取 + 确定性排序与去重 |
| **完成标准** | 图在不同运行间完全一致 |
| **工作量** | M |

**实施步骤**：

1. 实体抽取改为受 schema 约束的 JSON，至少包含 canonical name、type、aliases
2. 排序和去重必须确定性：不再使用 `list(set(entities))`
3. exact entity 无边时直接回退 `entity_to_chunks`，避免稀疏图丢失精确命中
4. 查询实体匹配增加别名、规范化和模糊匹配

### [ ] 4.2 分数标定与增量缓存

| 属性 | 内容 |
| --- | --- |
| **交付物** | Graph 分数与 RRF 同量纲 + 增量实体缓存 |
| **完成标准** | alpha 在评测集上做敏感性分析；来源变更时只更新受影响 chunk |
| **工作量** | M |

**实施步骤**：

1. 修复分数量纲：不能直接对 RRF 与 `1/(rank+1)` 相加
2. alpha 必须在固定评测集上做敏感性分析
3. 缓存实体抽取结果到 chunk ID + content hash
4. 来源变更时只更新受影响 chunk 的实体，图合并可后置
5. 在同一评测集上固定比较 Standard、Standard+reranker、Graph 三组

### [ ] 4.3 Graph 安全与产品边界

| 属性 | 内容 |
| --- | --- |
| **交付物** | 建库前外发确认 + 敏感信息扫描 + "仅 Standard/本地建库"模式 |
| **完成标准** | 用户明确知晓并同意 Graph 建库的数据外发 |
| **工作量** | S |

**实施步骤**：

1. Graph 首次建库前显示预计外发 chunk 数、endpoint 和风险确认
2. 提供"仅 Standard/本地建库"模式
3. 加入敏感信息扫描与路径 denylist
4. 在固定真实模型上运行间接提示注入和数据泄露回归集

---

## 七、模块重构路线（贯穿各阶段）

> **当前回填：** 已落地或正在被生产路径使用的模块包括 `config.py`、
> `domain.py`、`loaders/`、`chunking.py`、`lexical.py`、`retrieval.py`、
> `llm_gateway.py` 与 `evaluation/`。`index_store.py`、独立 `graph.py` 以及
> 完整的 service/UI 职责迁移仍未完成；保留以下图作为目标架构，而非完成清单。

报告指出 `src/rag.py` 1743 行、`src/graph_rag.py` 793 行，承担了过多职责。建议按以下目标架构逐步迁移，**不需要一次性重写**：

```text
config.py          Settings、路径、模型与策略版本        ← 阶段 3.2
domain.py          Source / Section / Chunk / RetrievalCandidate / Citation  ← 阶段 1.3
loaders/           PDF、DOCX、text、结构化格式解析器      ← 阶段 2.1
chunking.py        结构化与 parent-child 分块            ← 阶段 2.2
index_store.py     Chroma、manifest、source sync、snapshot ← 阶段 3.5
lexical.py         tokenizer 与持久化词法索引            ← 阶段 1.1 + 3.3
retrieval.py       dense/sparse、融合、重排、覆盖与拒答   ← 阶段 1.3-1.5
llm_gateway.py     client、timeout、retry、stream、usage  ← 阶段 3.1
graph.py           实体 schema、缓存、图增量与检索       ← 阶段 4
evaluation/        数据集、runner、指标、回归对比         ← 阶段 0
service.py         TUI/CLI 用例编排                      ← 阶段 3.1
```

**迁移原则**：
- 先引入 `RetrievalCandidate` 和 `Settings`，再逐段迁移最有价值
- 每次迁移只移动一个职责，保持测试通过
- 迁移后原模块通过 import 委托，不破坏外部接口

---

## 八、验收指标总览

| 层级 | 指标 | 初始建议 | 验证阶段 |
| --- | --- | --- | --- |
| 摄取 | 解析成功率、空文本率、低质量页率、每格式失败率 | 失败必须可见；不能静默建立空索引 | 阶段 2 |
| 检索 | Recall@5/10、MRR、nDCG、source recall | 总体与中文/混合/元数据/跨文档分层报告 | 阶段 0+ |
| 上下文 | context recall、context precision、来源覆盖、token 数 | 只统计实际进入 prompt 的证据 | 阶段 1 |
| 回答 | correctness、faithfulness、完整性 | 同时报告平均值和失败案例 | 阶段 0+ |
| 引用 | ID validity、citation precision/recall | ID validity=100%；其余先基线后设门禁 | 阶段 1 |
| 拒答 | answerable recall、unanswerable precision/recall、误拒率 | 独立调阈值，不从 RRF 常量推断 | 阶段 1 |
| 性能 | 冷/热启动、index p50/p95、retrieval p50/p95、TTFT、total | 按 1k/10k/目标 chunk 规模分层 | 阶段 3 |
| 成本 | query rewrite、Graph build、answer tokens/费用 | Standard 与 Graph 单独统计 | 阶段 3+4 |
| 稳定性 | 索引版本不一致、监听失败、API 错误、恢复时间 | 所有异常可分类且可在 status 查到 | 阶段 3 |

**每次检索相关 PR 都应附一张对比表**：总体、中文、英文、中英混合、无答案、跨文档六个切片，至少列 Recall@K、context precision、citation、拒答和延迟变化。

---

## 九、风险与依赖

| 风险 | 影响 | 缓解措施 |
| --- | --- | --- |
| 评测集标注成本高 | 阶段 0 延期 | 先做 80 条最小集，后续迭代扩充 |
| 评测集过拟合 | 针对评测集调参导致实际效果未提升 | 预留 10-15% holdout 子集，最终验收在 holdout 上跑；调参只看训练子集 |
| 多语种 embedding 切换可能影响现有索引 | 需要全量重建 | 切换前提供迁移脚本；manifest 指纹自动检测不兼容 |
| Graph RAG 评测可能证明无净收益 | 阶段 4 不启动 | 这是预期结果，不是风险；Standard RAG 基线已足够 |
| 模块重构可能引入回归 | 测试失败 | 每次只迁移一个职责；CI Layer 1 保证工程回归 |
| 外部 LLM API 费用 | 生成评测成本 | CI Layer 3 手动触发或每日定时；使用最便宜模型 |
| Docker bind mount 遮蔽预下载模型 | 新用户首次启动慢 | 已提前到阶段 0.4 修复 |

---

## 十、执行优先级总结

```
阶段 0（建立基线）  ← 最先执行，3-4 周
  │
  ▼
阶段 1（Standard RAG 闭环）  ← 4-5 周
  │
  ▼
阶段 2（结构化摄取 + 多轮）  ← 5-6 周
  │
  ├──────────────────────┐
  ▼                      ▼
阶段 3（性能/运维）    阶段 4（Graph RAG，条件触发）
5-6 周                  视评测结果而定
```

**当前下一步行动：** `[x] P1.1-G0 生产检索观测、精确 replay 与隐私边界契约
设计`——设计阶段已完成（`plans/P1.1-PRODUCTION-OBSERVABILITY-REPLAY-CONTRACT-2026-08-13.md`，
纯设计、未实现任何 capture）；`[x] P1.1-M Minimal-only 实现`——已获 owner
授权实施（`MINIMAL_CAPTURE_READY`）：默认 Off、显式 consent、本地
`MNEME_DATA_DIR/traces`、不保存原始 query/answer/model response、30 天保留、
单 trace 删除与撤回、sync/stream 均接入 Standard RAG（Graph 不接入）；
`src/query_plan_capture.py` 保持 synthetic-only。C 线验收决策：
`C_3_2_DECISION = ACCEPT_C32_COMPLETE`（manifest 见
`results/config-contract-acceptance/manifest.json`）。B 线状态纠正：
`[x] Phase 6-B0.2 Snapshot Index Lifecycle Immutability`——B0.2.5 独立
验收通过（`B_0_2_DECISION = ACCEPT_B02_LIFECYCLE_HARDENING_COMPLETE`，
报告见 `results/b02-lifecycle-acceptance/`），B0.2 子线正式关闭；B0.2.2
fail-closed 产品语义不变，v2.0.11 仍为只读 CANDIDATE。
**P1.1-M 接线状态（2026-08-25 回填）：** 上述实现在 2026-08-17 曾为通过
C 线 manifest v5 门控**回退三处接线**（`src/rag.py`/`src/cli_loop.py`/
`tui/screens/chat.py` 恢复 v5 冻结字节；`src/production_observability.py`
与观测测试保留于工作树）；随后按 Owner 批准的「门控管入口」策略完成
**重新接线**——manifest v5 保持入口冻结证据不重新生成，接线后行为中性
偏离由 Off 零效应契约测试单独验证（详见 CHANGELOG 2026-08-25 条目与
`results/config-contract-acceptance/p11-m-final-acceptance-report.md`）。
**P1.1-E 启用落地（2026-08-25，owner-only 采集期待启动）：** owner 已锁定
启用决策单（`ENABLED_FOR = owner_only`，决策原文见 replay 契约 §6.1），本阶段
仅固化守卫与治理，不改变任何检索策略：①防泄漏守卫——traces root 解析到仓库
工作树内即在写盘前 fail-closed 拒绝 capture 启动；②只读巡检命令
`python -m src.production_observability patrol`；③`.gitignore` 纵深防御 +
README 推送前自检清单；④采集与分析计划见
`plans/P1.1-COLLECTION-AND-ANALYSIS-PLAN-2026-08-25.md`。截至回填时未开启
consent、未采集任何真实 trace；实际开启是 owner 手工 `/consent` 动作，样本
达标（200 条 / 跨文档 ≥30 / 4 周，先到为准）后的聚合分析与预注册实验为
后续独立任务。

**P1.0 回填（诊断已完成，结论固定）：** `[x] P1.0 生产检索—证据漏斗只读
根因诊断` → **`P1.0_DECISION = STOP_EVIDENCE_INSUFFICIENT`**。诊断基于当前
生产源码 + 冻结产物 + 确定性本地复算：漏斗 case 级损失可量化（候选召回
96.2% → final context 保留 61.0%；dynamic top-k 截断 18/105、selector 同源
约束 17/105、相邻扩展 2/105、候选完全缺失 4/105），但唯一的受控消融
（selector S0/S3）证明检索层指标改善（+8.9pp context_recall）不传导答案
质量（+0.2pp coverage）；拒答阈值扫描与特征化拒答分别 NO_GO 与样本不足。
因此默认产品策略（dynamic top-k / selector max_per_source / 拒答 / reranker /
Graph / rewrite-decompose）**均不得改动**。下一步 P1.1-G0 只做观测契约设计
（见 `plans/P1.1-PRODUCTION-OBSERVABILITY-REPLAY-CONTRACT-2026-08-13.md`）：
补齐 P1.0 无法获得的观测（dense/BM25 通道 trace、immutable production
query-plan trace、stream/sync 对照、false-refusal 样本），三级显式 opt-in
（Off 默认 / Minimal diagnostic / Exact replay），未获 owner 对隐私与留存的
明确决定前不得实现真实 production capture。Graph 产品化继续保持
`[!] NO_PROMOTION`。
