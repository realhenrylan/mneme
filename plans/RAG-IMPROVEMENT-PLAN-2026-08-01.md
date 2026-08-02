# Mneme RAG 改进计划

> 基于 `RAG-IMPROVEMENT-REPORT-2026-08-01.md` 制定
> 制定日期：2026-08-01
> 状态：待审批

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

### 0.1 真实评测集 v1

| 属性 | 内容 |
| --- | --- |
| **交付物** | 80-150 条 JSONL 评测文件 + 标注规范文档 |
| **完成标准** | 覆盖 8 类核心查询（中文、英文、中英混合、元数据、单文档事实、跨文档比较、多轮追问、无答案/拒答）；每条至少标注 `relevant_source_ids`、页码/section、可接受答案要点、是否应拒答；重要样例再标相关 chunk ID |
| **工作量** | M |
| **涉及文件** | 新增 `evaluation/datasets/`、`evaluation/schema.py` |

**实施步骤**：

1. 定义评测数据 schema（JSONL 格式，每条包含 `query`、`query_type`、`language`、`relevant_source_ids`、`relevant_chunks`、`acceptable_answer_points`、`should_refuse`、`metadata`）

> **边界声明**：`evaluation/schema.py` 只描述评测标注格式（静态数据结构），`src/domain.py`（阶段 1.3 引入）描述运行时领域模型（`RetrievalCandidate`、`Source`、`Chunk` 等）。两者虽都含 chunk/source 概念但职责不同：评测 schema 是"标注者写入、runner 读取"的契约，领域模型是"检索/生成链路传递"的运行时类型。
2. 准备评测语料：从项目已有 PDF/DOCX 样例 + 新增中文文档样例中选取
3. 编写 80-150 条评测查询，按 8 类分布（建议：中文 20、英文 20、混合 15、元数据 10、单文档事实 15、跨文档 10、多轮 10、无答案/拒答 25-30）
4. 人工标注每条查询的相关来源和答案要点
5. 划分训练子集（85-90%）与 holdout 子集（10-15%）：调参只看训练子集，最终验收在 holdout 上跑，防止过拟合
6. 编写标注规范文档 `evaluation/ANNOTATION_GUIDE.md`

### 0.2 实际检索评测 Runner

| 属性 | 内容 |
| --- | --- |
| **交付物** | 经过 Mneme 实际 parser/embedding/Chroma/BM25/RRF 链路的评测 runner |
| **完成标准** | 输出逐例候选列表与 Recall@K、MRR、nDCG 指标；可复现运行 |
| **工作量** | M |
| **涉及文件** | 新增 `evaluation/runner.py`、`evaluation/metrics.py` |

**实施步骤**：

1. 实现 `RetrievalRunner`：调用 Mneme 的 `build_index()` → `retrieve_hybrid_with_sources()` 链路，对评测集逐条运行
2. 实现 `RetrievalMetrics`：计算 Recall@5/10/20、MRR、nDCG、source recall
3. 输出结构化报告：总体 + 按语言/查询类型分层
4. 记录当前基线分数，作为后续改动的参照
5. 添加 CLI 入口：`python -m evaluation.run --dataset v1 --output results/baseline.json`

### 0.3 生成与引用评测

| 属性 | 内容 |
| --- | --- |
| **交付物** | correctness、faithfulness、citation precision/recall、refusal 评测 |
| **完成标准** | 人工抽样可复核；原始文档不写入日志；与检索评测独立运行 |
| **工作量** | M |
| **涉及文件** | 新增 `evaluation/generation_runner.py`、`evaluation/citation_metrics.py` |

**实施步骤**：

1. 实现 `GenerationRunner`：在检索结果基础上调用 LLM 生成回答
2. 实现 `CitationValidator`：调用 `src/citations.py` 的现有解析函数，校验引用 ID 合法性
3. 实现 faithfulness 评测：对比回答要点与上下文证据的覆盖关系
4. 实现 refusal 评测：对 `should_refuse=true` 的查询验证系统是否正确拒答
5. 生成评测单独运行，避免把检索失败和生成失败混为一谈

### 0.4 Docker bind mount 遮蔽预下载模型修复

| 属性 | 内容 |
| --- | --- |
| **交付物** | 修复 `docker-compose.yml` 的 bind mount 遮蔽镜像内预下载模型的问题 |
| **完成标准** | 新宿主机首次 `docker compose up` 不因空 `./models` 目录而重新触发模型下载 |
| **工作量** | S（约半天） |
| **涉及文件** | 修改 `docker-compose.yml`、`Dockerfile` |

**实施步骤**：

1. 修改 `docker-compose.yml`：将 `./models` bind mount 改为 named volume，或在 entrypoint 中检测镜像内模型并复制到挂载目录
2. 验证新宿主机首次启动不重新下载模型
3. 更新 README 中 Docker 相关说明

**原因**：这是新用户第一天就会踩的坑（空 `./models` 遮蔽镜像内 `/app/models`），不应拖到阶段 3。

### 0.5 CI 分层

| 属性 | 内容 |
| --- | --- |
| **交付物** | 三层 CI 配置：unit / offline retrieval / scheduled generation |
| **完成标准** | PR 能发现检索回归；外部费用可控 |
| **工作量** | S |
| **涉及文件** | 修改 `.github/workflows/`、`pyproject.toml` |

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

### 1.1 中文 Sparse Baseline（CJK n-gram + 字段权重）

| 属性 | 内容 |
| --- | --- |
| **交付物** | CJK 字符 n-gram tokenizer + 元数据字段加权 |
| **完成标准** | 中文与混合查询的 Recall 显著高于当前基线（在评测集 v1 上验证） |
| **工作量** | M |
| **涉及文件** | 修改 `src/rag.py` 的 `_tokenize()`；新增 `src/lexical.py` |

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

### 1.2 多语种 Embedding 对比

| 属性 | 内容 |
| --- | --- |
| **交付物** | 当前 `all-MiniLM-L6-v2` 与 1-2 个多语种候选的离线对比结果 |
| **完成标准** | 以质量/延迟/内存共同决策是否切换模型 |
| **工作量** | M |
| **涉及文件** | 修改 `src/rag.py` 的 embedding 加载逻辑；新增 `evaluation/embedding_benchmark.py` |

**实施步骤**：

1. 在评测集 v1 上测量当前 `all-MiniLM-L6-v2` 的 dense retrieval 基线
2. 候选模型：`BAAI/bge-m3`（dense/sparse/multi-vector，100+ 语言）、`intfloat/multilingual-e5-base`（100 种语言）
3. 对比维度：Recall@K、索引构建时间、查询延迟、内存占用、索引体积
4. 记录对比结果，决定是否切换默认模型
5. 将 embedding 模型、query/document 前缀、归一化方式纳入 manifest 指纹

**关键代码位置**：
- 当前 embedding 加载：`src/rag.py:67-74`

### 1.3 统一 Candidate 模型与 Top-K 语义

| 属性 | 内容 |
| --- | --- |
| **交付物** | `RetrievalCandidate` 数据类 + candidate/rerank/context 三层 K 分离 |
| **完成标准** | 每个候选保留各通道 raw/normalized score；UI、指标、来源与真实 prompt 一致 |
| **工作量** | S |
| **涉及文件** | 新增 `src/domain.py`；修改 `src/rag.py`、`src/metrics.py`、`tui/dialogs/status.py` |

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

### 1.4 Reranker

| 属性 | 内容 |
| --- | --- |
| **交付物** | Top 20-50 候选重排到 context 5-10 |
| **完成标准** | Context precision 上升且 recall 不显著下降（在评测集 v1 上验证） |
| **工作量** | M |
| **涉及文件** | 新增 `src/retrieval.py`；修改 `src/rag.py` 的融合逻辑 |

**实施步骤**：

1. 选型：本地 cross-encoder reranker（如 `cross-encoder/ms-marco-MiniLM-L-6-v2`）或 LLM-based reranker
2. 实现 reranker 接口：输入候选列表 + query，输出重排后列表 + rerank score
3. 在融合排名后、上下文构建前插入 reranker 步骤
4. 在评测集 v1 上对比有/无 reranker 的 context precision/recall
5. 加入每来源上限、子查询覆盖约束：跨文档问题优先覆盖不同来源

### 1.5 拒答校准

| 属性 | 内容 |
| --- | --- |
| **交付物** | 基于 reranker top score、top1-top2 margin、有效来源数等可解释特征的拒答机制 |
| **完成标准** | 在有/无答案标注集上达到预设 precision/recall；避免默认总放行 |
| **工作量** | M |
| **涉及文件** | 修改 `src/rag.py` 的拒答逻辑；新增 `src/retrieval.py` 的拒答判断 |

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

### 1.6 引用闭环

| 属性 | 内容 |
| --- | --- |
| **交付物** | 引用 ID 校验 + 一次修复 + 失败状态标记 |
| **完成标准** | 非法引用率降为 0；无引用事实可检测 |
| **工作量** | M |
| **涉及文件** | 修改 `src/rag.py` 的回答路径；利用 `src/citations.py:63-69` |

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

### 2.1 标准文档模型

| 属性 | 内容 |
| --- | --- |
| **交付物** | `Document → Section → Chunk` 数据模型，所有 parser 产出统一 schema |
| **完成标准** | section、page、type、parser version 均可追溯 |
| **工作量** | M |
| **涉及文件** | 新增 `src/domain.py` 的文档模型；新增 `src/loaders/` 目录；修改 `src/rag.py` 的解析逻辑 |

**实施步骤**：

1. 定义 `Document`、`Section`、`Chunk` 数据类：包含标题路径、页码、section type、字符/token 范围、解析器版本
2. 将 PDF/DOCX/text 解析逻辑从 `src/rag.py` 迁移到 `src/loaders/` 下的独立模块
3. 每个 loader 输出统一的 `Document` 对象
4. 分格式建立质量等级：原生文本、结构化解析、OCR；TUI 在低质量解析时提示用户

### 2.2 Parent-Child / 邻接扩展

| 属性 | 内容 |
| --- | --- |
| **交付物** | 小 chunk 召回 + 大 parent/邻接窗口回答 |
| **完成标准** | 跨边界问答的 context recall 提升（在评测集 v1 上验证） |
| **工作量** | M |
| **涉及文件** | 新增 `src/chunking.py`；修改 `src/rag.py` 的分块和上下文构建逻辑 |

**实施步骤**：

1. 实现结构化分块：基于标题、段落、表格等结构信号分块，而非纯字符切分
2. 实现 parent-child 关系：小 chunk 负责召回，关联的 parent chunk 负责提供完整上下文
3. 实现邻接扩展：召回某个 chunk 时，自动包含其前后相邻 chunk
4. PDF 首页 anchor 在索引阶段持久化，不再查询时重读源 PDF
5. 在评测集 v1 上对比有/无 parent-child 的 context recall

### 2.3 PDF/DOCX 重点解析

| 属性 | 内容 |
| --- | --- |
| **交付物** | 表格提取、标题层级、低质量检测与回退 |
| **完成标准** | 目标格式的解析失败可见、可回退 |
| **工作量** | L |
| **涉及文件** | 修改 `src/loaders/pdf_loader.py`、`src/loaders/docx_loader.py` |

**实施步骤**：

1. PDF：引入表格提取（如 pdfplumber 或 camelot）、标题层级识别、低质量扫描页检测
2. DOCX：提取表格、页眉页脚、列表结构
3. 实现低质量检测：空文本率、低质量页率、每格式失败率
4. 解析失败必须可见，不能静默建立空索引
5. 优先支持真实使用最多的 2-3 种格式，不继续扩大"纯文本兼容"扩展名列表

### 2.4 多轮检索改写

| 属性 | 内容 |
| --- | --- |
| **交付物** | History-aware standalone query rewrite + 原查询保底召回 |
| **完成标准** | 代词追问集显著优于当前基线（在评测集 v1 的多轮子集上验证） |
| **工作量** | M |
| **涉及文件** | 修改 `src/rag.py` 的检索入口；新增 `src/rag_query_rewriter.py` |

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

### 3.1 单例模型与统一 LLM Gateway

| 属性 | 内容 |
| --- | --- |
| **交付物** | 进程级模型缓存 + 统一 LLM gateway（timeout、retry、cancel、usage） |
| **完成标准** | 无重复加载；错误分类可见；网络异常时 TUI 不会长时间停在 thinking 状态 |
| **工作量** | M |
| **涉及文件** | 新增 `src/llm_gateway.py`；修改 `src/rag.py`、`tui/service.py`、`src/graph_rag.py` |

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

### 3.2 数据目录与配置统一

| 属性 | 内容 |
| --- | --- |
| **交付物** | `MNEME_DATA_DIR` 环境变量 + `Settings` 配置类 |
| **完成标准** | 包目录只读也可运行；CLI/TUI 默认一致；所有配置有文档 |
| **工作量** | S |
| **涉及文件** | 新增 `src/config.py`；修改 `src/rag.py`、`tui/app.py`、`.env.example` |

**实施步骤**：

1. 实现 `Settings` 类：集中管理模型 ID、本地路径、cache dir、下载策略、数据目录
2. Chroma 数据目录改为 `MNEME_DATA_DIR/chroma_db`（默认 `~/.mneme/chroma_db`），不再写入 `src/chroma_db`
3. 统一 CLI 与 TUI 的默认值：temperature、Top-K 范围等
4. 离线模式不能隐式触发远程 ModelScope 下载
5. `RAG_REFUSAL_THRESHOLD` 等配置项加入文档

**关键代码位置**：
- Chroma 路径硬编码：`src/rag.py:138-140`
- CLI/TUI 默认值不一致：`README.zh.md:191-194` vs `.env.example:10-17` vs `tui/app.py:20-30`

### 3.3 持久化 Sparse / 增量更新

| 属性 | 内容 |
| --- | --- |
| **交付物** | 持久化词法索引 + 增量 BM25 更新 |
| **完成标准** | 目标规模下启动/增删达到 p95 预算 |
| **工作量** | L |
| **涉及文件** | 新增 `src/lexical.py`；修改 `src/rag.py` 的 BM25 构建逻辑 |

**实施步骤**：

1. 将 BM25 索引持久化到磁盘，避免每次启动全量重建
2. 实现增量更新：新增/删除文档时只更新受影响的词项
3. 超过预设 chunk 规模后迁移到持久化全文索引（如 Whoosh 或 SQLite FTS5）
4. 或按 collection/source 分片，避免 Python 内存 BM25 成为上限

**关键代码位置**：
- 全量读入内存构建 BM25：`src/rag.py:866-878`

### 3.4 完整可观测性

| 属性 | 内容 |
| --- | --- |
| **交付物** | 分阶段延迟、TTFT、token、成本、有效证据数等指标 |
| **完成标准** | status 页与实际执行一致；所有异常可分类且可在 status 查到 |
| **工作量** | M |
| **涉及文件** | 修改 `src/metrics.py`；修改 `tui/dialogs/status.py` |

**实施步骤**：

1. 扩展指标：索引耗时、embedding 耗时、query rewrite 耗时、各检索通道耗时、rerank 耗时、TTFT、总耗时、token 使用量、成本、引用有效率
2. 指标持久化：不再只保存最近 100 条内存记录
3. 文件监听回调不再静默吞掉异常（`tui/service.py:379-389`），记录最近失败、路径、重试状态
4. status 页展示实际进入 prompt 的证据数，而非候选数

**关键代码位置**：
- 当前指标只记录最近 100 条：`src/metrics.py:15-64`
- 监听回调静默吞异常：`tui/service.py:379-389`

### 3.5 来源生命周期对账

| 属性 | 内容 |
| --- | --- |
| **交付物** | `sync_sources(desired_set)` 与 `add_sources(delta)` 两种 API |
| **完成标准** | CLI `--files` 语义文档化；删除前展示差异并要求显式确认 |
| **工作量** | S |
| **涉及文件** | 修改 `src/rag.py` 的 `build_index()` 和 `_ensure_client_and_check_rebuild()` |

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

### 4.1 实体 Schema 与确定性图构建

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

### 4.2 分数标定与增量缓存

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

### 4.3 Graph 安全与产品边界

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

**下一步行动**：审批本计划后，从阶段 0.1（真实评测集 v1）开始执行。
