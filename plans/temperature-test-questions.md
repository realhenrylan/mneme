# 模型温度测试问题集（共 34 题）

> 测试目的：在不同模型温度（如 0.0, 0.1, 0.3, 0.5, 0.7, 1.0）下，分别测试普通 RAG 和 Graph RAG 的回答质量。
> 控制变量：模型、问题、文本内容。唯一变量：temperature 参数。
> 评测维度：事实准确性、完整性、一致性、幻觉程度、多文档综合能力。
> 题目构成：RAG 专用 12 题 + Graph RAG 专用 14 题 + 共有对照 6 题 + 负样本 2 题 = 34 题
> 每种模式实际答题数：12 + 6 + 2 = 20 题/模式（RAG），14 + 6 + 2 = 22 题/模式（Graph RAG）

---

## 一、普通 RAG 模式（12 题）

侧重：检索质量、事实提取、单文档/跨文档信息综合、细节精度。

### 基础事实检索（4 题）

| 编号 | 问题 | 主要涉及文档 |
|------|------|-------------|
| RAG-01 | 南京市的最高点是什么？海拔多少米？ | 南京城市地理环境.docx |
| RAG-02 | OneDrive 的免费存储空间最初提供多少 GB？升级到 Microsoft 365 可以获得多少存储？ | OneDrive 入门.pdf |
| RAG-03 | 在 LLMs for Mobility Analysis 这篇综述中，作者将数据处理技术分为哪三类？ | LLMs_for_Mobility_Analysis_Survey.md |
| RAG-04 | DSpark 论文中提出的 confidence-scheduled verification 主要解决什么问题？ | DSpark_paper.pdf |

### 跨段落/跨文档综合（4 题）

| 编号 | 问题 | 主要涉及文档 |
|------|------|-------------|
| RAG-05 | 综述论文中提到的四种交通预测任务类型分别是什么？请简要说明每一种。 | LLMs_for_Mobility_Analysis_Survey.md |
| RAG-06 | 南京市的河湖水系主要属于什么水系？请列举至少四个南京重要的河湖名称。 | 南京城市地理环境.docx |
| RAG-07 | 在 LLM agent 的数据泄露威胁模型中，攻击者通过什么方式构造恶意 URL？论文提出了什么防护方案？ | prevent-url-data-exfil.pdf |
| RAG-08 | OneDrive 提供了哪些安全功能来保护用户文件？ | OneDrive 入门.pdf |

### 细节精度与数值（2 题）

| 编号 | 问题 | 主要涉及文档 |
|------|------|-------------|
| RAG-09 | 南京市的建成区面积、常住人口、城镇常住人口和城镇化率分别是多少？ | 南京城市地理环境.docx |
| RAG-10 | DSpark 相比 MTP-1 生产基线，在生成速度上提升的百分比范围是多少？ | DSpark_paper.pdf |

### 概念理解与推理（2 题）

| 编号 | 问题 | 主要涉及文档 |
|------|------|-------------|
| RAG-11 | 在智能交通系统中应用 LLM 面临哪些隐私方面的挑战？综述中给出了哪些应对方案？ | LLMs_for_Mobility_Analysis_Survey.md |
| RAG-12 | 南京入选《人类非物质文化遗产代表作名录》的是什么？南京有哪些著名的温泉旅游资源？ | 南京城市地理环境.docx |

---

## 二、Graph RAG 模式（14 题）

侧重：实体关系抽取、多跳推理、跨文档实体关联、知识图谱增强检索。

### 实体关系推理（4 题）

| 编号 | 问题 | 主要涉及文档 |
|------|------|-------------|
| GRAG-01 | "TrafficBERT" 和 "TrafficGPT" 这两个模型分别采用了什么 LLM 基座？它们在交通预测中的作用有何不同？ | LLMs_for_Mobility_Analysis_Survey.md |
| GRAG-02 | 综述中提到了哪些基于 GPT-2 的交通预测模型？它们各自的特点是什么？ | LLMs_for_Mobility_Analysis_Survey.md |
| GRAG-03 | DSpark 的半自回归架构由哪两个模块组成？各自的作用是什么？ | DSpark_paper.pdf |
| GRAG-04 | 在综述论文中，"Tokenization"、"Prompt" 和 "Embedding" 这三种数据预处理技术在交通预测中分别有哪些具体应用案例？ | LLMs_for_Mobility_Analysis_Survey.md |

### 多跳推理与跨实体关联（4 题）

| 编号 | 问题 | 主要涉及文档 |
|------|------|-------------|
| GRAG-05 | 综述中提到的 "UniST" 模型和 "ST-LLM" 模型都用于城市时空预测，它们在技术路线上有什么异同？ | LLMs_for_Mobility_Analysis_Survey.md |
| GRAG-06 | DSpark 的 confidence-scheduled verification 与传统的 speculative decoding 在验证策略上有哪些核心区别？ | DSpark_paper.pdf |
| GRAG-07 | 从 Human Mobility Forecasting 到 Demand Forecasting，LLM 的应用策略有哪些变化？请从模型框架角度分析。 | LLMs_for_Mobility_Analysis_Survey.md |
| GRAG-08 | 在 all-MiniLM-L6-v2 生成嵌入的场景下，DSpark 的并行 draft 生成机制面临的主要挑战是什么？半自回归架构如何缓解这个问题？ | DSpark_paper.pdf |

### 跨文档实体关联（2 题）

| 编号 | 问题 | 主要涉及文档 |
|------|------|-------------|
| GRAG-09 | 综述论文中的 "Fine-tune" 策略与 DSpark 论文中提到的 "fine-grained" 技术有什么关联？两者在 LLM 应用场景中有何不同？ | LLMs_for_Mobility_Analysis_Survey.md + DSpark_paper.pdf |
| GRAG-10 | URL 数据泄露防护论文中描述的 LLM agent 威胁模型，与交通综述中提到的 LLM 隐私问题有何异同？两者提出的防护机制有无重叠之处？ | prevent-url-data-exfil.pdf + LLMs_for_Mobility_Analysis_Survey.md |

### 综合推理与对比（2 题）

| 编号 | 问题 | 主要涉及文档 |
|------|------|-------------|
| GRAG-11 | 南京市的自然资源（水资源、林木资源、生物资源）与人文资源（历史古迹、非物质文化遗产）之间存在哪些地理和历史上的关联？ | 南京城市地理环境.docx |
| GRAG-12 | OneDrive 的安全机制与防止 URL 数据泄露论文中的防护策略，在技术思路上有什么相似之处和本质区别？ | OneDrive 入门.pdf + prevent-url-data-exfil.pdf |

### Graph RAG 补强（2 题）

| 编号 | 问题 | 主要涉及文档 |
|------|------|-------------|
| GRAG-13 | OneDrive 的"个人保管库"（Personal Vault）和"文件加密"在保护机制上有什么不同？它们分别应对哪种安全威胁？ | OneDrive 入门.pdf |
| GRAG-14 | URL 泄露论文中提到 "open redirects" 为什么能绕过 naive domain-based allow-listing？论文的 dynamic policy 如何克服这个漏洞？ | prevent-url-data-exfil.pdf |

---

## 三、共有对照题（COM，6 题，两模式均作答）

> 设计目的：同一问题同时提交给 RAG 和 Graph RAG，直接对比两种检索策略在完全相同的提示词下的表现。

### 单文档多段落综合（3 题）

| 编号 | 问题 | 主要涉及文档 |
|------|------|-------------|
| COM-01 | 在 LLMs for Mobility Analysis 综述中，LLM 在交通预测领域有哪些传统方法不具备的优势？请列举并简要说明。 | LLMs_for_Mobility_Analysis_Survey.md |
| COM-02 | DSpark 论文的核心创新点是什么？这项技术对 LLM serving 系统带来了什么具体改进？ | DSpark_paper.pdf |
| COM-03 | 南京市有哪些自然资源？请按水资源、林木资源、生物资源分类列出。 | 南京城市地理环境.docx |

### 概念对比与推理（2 题）

| 编号 | 问题 | 主要涉及文档 |
|------|------|-------------|
| COM-04 | 综述论文中 Fine-tune 和 Zero-Shot/Few-Shot 两种策略各自适用于什么场景？它们的优缺点分别是什么？ | LLMs_for_Mobility_Analysis_Survey.md |
| COM-05 | 交通综述和 URL 数据泄露论文都提到了"LLM 的隐私风险"，请分别总结两篇论文对该问题的观点和提出的应对方案。 | LLMs_for_Mobility_Analysis_Survey.md + prevent-url-data-exfil.pdf |

### 操作流程类（1 题）

| 编号 | 问题 | 主要涉及文档 |
|------|------|-------------|
| COM-06 | OneDrive 入门指南中，用户如何在不同设备间访问和管理文件？请概括其主要功能路径。 | OneDrive 入门.pdf |

---

## 四、负样本题（NEG，2 题，两模式均作答）

> 设计目的：测试高温下系统是否会编造文档中不存在的答案。预期正确答案是"文档中未提及此信息"或等效表述。

| 编号 | 问题 | 主要涉及文档 |
|------|------|-------------|
| NEG-01 | DSpark 论文中使用的训练数据集名称是什么？数据集规模有多大？ | DSpark_paper.pdf |
| NEG-02 | 根据文档中的信息，南京市目前的 GDP 总量和人均 GDP 分别是多少？ | 南京城市地理环境.docx |

**负样本题评分特殊规则**：
- A（准确性）：回答"不知道/文档未提及"→ A=5（诚实）；编造具体数值→ A=1
- B（完整性）：不适用（无"正确信息"可覆盖），统一记 B=3（中性）
- C（聚焦度）：常规评分
- D（幻觉）：无编造→ D=5；编造数据→ D=1

---

## 五、前提条件：代码修改（Agent 执行前必须先完成）

当前 `rag.py` 和 `graph_rag.py` 中有三处缺陷阻止按计划测试，**Agent 在询问问题前必须先修复**：

### 5.A 必须修复的代码问题

**FIX-1**：`rag.py:answer_query()`（第 620 行）调用 `answer_with_llm_history` 时未传 `temperature` 参数，始终使用默认值 0.1。

→ 在 `answer_query` 签名中增加 `temperature=0.1` 参数，并透传给 `answer_with_llm_history`。

**FIX-2**：`graph_rag.py:graph_rag_pipeline()`（第 384 行）、CLI `__main__`（第 437、476 行）三处调用 `answer_with_llm_history` 均未传 `temperature`。

→ 在 `graph_rag_pipeline` 签名中增加 `temperature=0.1` 参数并透传。

**FIX-3**：`graph_rag.py:prepare_graph_index()`（第 317-330 行）的 `else` 分支在索引已存在时仍会全量重建 KnowledgeGraph。多次查询会导致重复 KG 重建，耗时不可接受。

→ 剥离 KG 构建逻辑到独立步骤，或通过调用 `graph_query_stream`（它不触发 `prepare_graph_index`）绕过。

### 5.B 测试执行方案

鉴于上述限制，**Agent 必须通过 Python API 直接调用流式函数**（它们均透传 `temperature`），而非走 CLI 或 `*_pipeline` 封装。

**执行环境准备**：在同一 Python 进程中先执行一次索引构建，然后复用 `model/collection/bm25/all_docs/metadatas/kg` 对象：

```python
# 伪代码示意，Agent 据实编写
from rag import prepare_index, EMBEDDING_MODEL_NAME
from graph_rag import prepare_graph_index, graph_query_stream, KnowledgeGraph
from rag import answer_query_stream
from sentence_transformers import SentenceTransformer

FILE_PATHS = [
    "test_texts/2405.02357v2.pdf",
    "test_texts/DSpark_paper.pdf",
    "test_texts/LLMs_for_Mobility_Analysis_Survey.md",
    "test_texts/OneDrive 入门.pdf",
    "test_texts/prevent-url-data-exfil.pdf",
    "test_texts/南京城市地理环境.docx",
]

# — RAG 初始化（一次）—
coll_name = "rag_" + hashlib.md5("|".join(sorted(FILE_PATHS)).encode()).hexdigest()[:8]
model, collection, bm25, all_docs, all_metadatas = prepare_index(FILE_PATHS, coll_name)

# — Graph RAG 初始化（一次）—
gcoll_name = "graph_rag_" + hashlib.md5("|".join(sorted(FILE_PATHS)).encode()).hexdigest()[:8]
gmodel, gcollection, gbm25, gall_docs, gall_metadatas, kg = prepare_graph_index(FILE_PATHS, gcoll_name)
```

对每个 temperature × 问题，调用：
- RAG：`stream, sources = answer_query_stream(query, model, collection, bm25, all_docs, all_metadatas, temperature=t)` → 答案 = `"".join(stream)`
- Graph RAG：`stream, sources = graph_query_stream(query, gmodel, gcollection, gbm25, gall_docs, gall_metadatas, kg, temperature=t)` → 答案 = `"".join(stream)`

---

### 温度梯度设置
测试温度值：`[0.0, 0.1, 0.3, 0.5, 0.7, 1.0]`

### 执行步骤

1. **应用 FIX-1/FIX-2/FIX-3** 到对应 Python 文件
2. **初始化索引**（一次）；对每个温度，复用已构建的索引对象
3. **逐题执行**：按 5.B 方案调用流式函数，收集回答原文（6 温度 × 每模式约 20 题 × 2 模式 = 约 252 次调用）
4. **逐题评分**：以期望关键事实为参考，按第 7 节规则给出 A/B/C/D
5. **一致性评分**：收集同一问题 6 个温度回答后给出 E
6. **输出 JSON**：写入 `plans/temperature-test-results.json`

### 注意事项
- 不修改 `graph_rag.py` 中实体提取的 temperature（保持 0.2）
- 若 API 调用触发 RateLimitError，加入 `time.sleep(2)` + 重试
- 运行前先执行一次 `--rebuild` 确保索引完整

---

## 六、每题的期望关键事实（评分参考基准）

> Agent 评分时，逐条比对回答是否包含以下关键事实。同义转述视为命中。缺失则为不完整，编造则为幻觉。

### RAG-01：南京市的最高点是什么？海拔多少米？

- **山名**：紫金山
- **海拔**：448.9 米

### RAG-02：OneDrive 的免费存储空间最初提供多少 GB？升级到 Microsoft 365 可以获得多少存储？

- **免费存储**：5 GB
- **Microsoft 365 存储**：1 TB

### RAG-03：在 LLMs for Mobility Analysis 这篇综述中，作者将数据处理技术分为哪三类？

- **Tokenization（分词/标记化）**
- **Prompt（提示工程）**
- **Embedding（嵌入/编码）**

### RAG-04：DSpark 论文中提出的 confidence-scheduled verification 主要解决什么问题？

- **解决的问题**：传统 speculative decoding 中不加区分地验证长 block 导致在高并发 serving 场景下 batch 容量浪费（token with high rejection risks 被浪费）
- 或答：**减少 verification waste / 提高 throughput**

### RAG-05：综述论文中提到的四种交通预测任务类型分别是什么？请简要说明每一种。

- **Traffic Forecasting**：预测未来交通状况（vehicle flow, speed, congestion）
- **Human Mobility Forecasting**：预测个体/人群的移动行为
- **Demand Forecasting**：预测特定时间地点的交通需求（crowd size, vehicle count）
- **Missing Data Imputation**：填补缺失的交通数据

### RAG-06：南京市的河湖水系主要属于什么水系？请列举至少四个南京重要的河湖名称。

- **水系**：长江水系
- **河湖（任 4 个）**：长江、秦淮河、玄武湖、莫愁湖、汤山温泉、珍珠泉

### RAG-07：在 LLM agent 的数据泄露威胁模型中，攻击者通过什么方式构造恶意 URL？论文提出了什么防护方案？

- **攻击方式**：通过 prompt injection 构造含敏感数据的 URL（如 `?data=YourAddressHere`），诱导 agent 点击链接或加载图片
- **防护方案**：动态 allow-list 策略，仅允许访问已被独立 search index 收录过的 URL（URL-level enforcement）

### RAG-08：OneDrive 提供了哪些安全功能来保护用户文件？

- **个人保管库（Personal Vault）**
- **勒索软件检测和恢复（ransomware detection and recovery）**
- **文件加密（file encryption）**

### RAG-09：南京市的建成区面积、常住人口、城镇常住人口和城镇化率分别是多少？

- **建成区面积**：约 868.28 平方千米
- **常住人口**：954.70 万人
- **城镇常住人口**：832.49 万人
- **城镇化率**：87.2%

### RAG-10：DSpark 相比 MTP-1 生产基线，在生成速度上提升的百分比范围是多少？

- **加速范围**：60%–85%

### RAG-11：在智能交通系统中应用 LLM 面临哪些隐私方面的挑战？综述中给出了哪些应对方案？

- **挑战（至少 3 点）**：
  - ITS 设备缺乏安全存储/管理 secret keys 的能力
  - LLM 会记忆训练数据，可被提取敏感信息
  - LLM 能从公开数据推断出私人信息
  - 与 LLM 频繁交互暴露 private data（实时交通视频、mobility data、车载数据等）
- **应对方案（至少 2 个）**：
  - Differential privacy（差分隐私）- DP-SGD、federated learning
  - Homomorphic encryption + attribute shuffling
  - Blockchain-based framework + noise-adding mechanism

### RAG-12：南京入选《人类非物质文化遗产代表作名录》的是什么？南京有哪些著名的温泉旅游资源？

- **非遗**：南京云锦
- **温泉**：汤山温泉、珍珠泉

---

### GRAG-01："TrafficBERT" 和 "TrafficGPT" 这两个模型分别采用了什么 LLM 基座？它们在交通预测中的作用有何不同？

- **TrafficBERT**：基于 BERT，将交通序列数据编码后接线性层输出；用于 traffic flow forecasting，处理道路级预测
- **TrafficGPT**：基于 GPT-3.5/ChatGLM3-6B/Qwen-14B-Chat/InternLM-Chat-20B；通过 orchestration 与 TFMs 交互进行 deductive reasoning

### GRAG-02：综述中提到了哪些基于 GPT-2 的交通预测模型？它们各自的特点是什么？

- **LLM4TS**：fine-tuned GPT-2 作为 backbone，用于时间序列预测
- **STG-LLM**：fine-tune GPT-2 少量参数 + spatial-temporal graph tokenizer + adapter，用于 spatial-temporal forecasting
- **TPLLM**：GPT-2 作为 base LLM 提供 embedding + CNN/GCN，用于 traffic prediction（尤其有限历史数据场景）

### GRAG-03：DSpark 的半自回归架构由哪两个模块组成？各自的作用是什么？

- **Parallel backbone（并行主干）**：高效生成长 token 序列 draft
- **Lightweight sequential module（轻量序列模块）**：引入 intra-block dependency modeling，缓解 suffix decay

### GRAG-04：在综述论文中，"Tokenization"、"Prompt" 和 "Embedding" 这三种数据预处理技术在交通预测中分别有哪些具体应用案例？

- **Tokenization**：AuxMobLCast（定义 timestamp+location 为 token）、Liu et al. 的 spatial-temporal embedding layer
- **Prompt**：LLMLight（含实时 traffic condition 的 knowledgeable prompt）、Xue et al. 的 prompt mining framework（entropy-based prompt generation + refinement）
- **Embedding**：GT-TDI（semantic descriptions → embedding tensors）、AuxMobLCast（BERT 编码 mobility prompt → contextual + numerical tokens）

### GRAG-05：综述中提到的 "UniST" 模型和 "ST-LLM" 模型都用于城市时空预测，它们在技术路线上有什么异同？

- **UniST**：通用模型，generative pre-training + masking strategies + spatio-temporal knowledge-guided prompts，支持 few-shot/zero-shot 跨场景迁移
- **ST-LLM**：spatial-temporal embedding module + embedding fusion + PFA LLM（Partially Frozen Attention），侧重 traffic demand prediction（taxi/bike）
- **共同点**：都处理 spatial-temporal 预测，都用 LLM 范式

### GRAG-06：DSpark 的 confidence-scheduled verification 与传统的 speculative decoding 在验证策略上有哪些核心区别？

- **传统 speculative decoding**：固定长度验证整个 draft block，不区分 token 质量
- **DSpark confidence-scheduled**：根据 estimated prefix survival probabilities + engine-specific throughput profiles 动态调整每个 request 的验证长度

### GRAG-07：从 Human Mobility Forecasting 到 Demand Forecasting，LLM 的应用策略有哪些变化？请从模型框架角度分析。

- **Human Mobility**：更侧重 prompt engineering（LLM-Mob 的 context-inclusive prompts, LLM-MPM）、few-shot reasoning、trajectory generation（MobilityGPT）
- **Demand Forecasting**：更侧重 fine-tune + integration（ST-LLM 的 embedding fusion、UniST 的 pre-training）、zero-shot prediction of travel choices
- **共同趋势**：从独立使用 LLM reasoning → 将 LLM 嵌入大框架作组件

### GRAG-08：DSpark 的并行 draft 生成机制面临的主要挑战是什么？半自回归架构如何缓解这个问题？

- **挑战**：并行 drafter 一次性生成长序列但缺乏 inter-token dependencies，导致 acceptance decay（后缀 token 通过率急剧下降）
- **缓解方式**：semi-autoregressive 架构 — parallel backbone + lightweight sequential module 引入 intra-block dependency modeling

### GRAG-09：综述论文中的 "Fine-tune" 策略与 DSpark 论文中提到的关联是什么？两者在 LLM 应用场景中有何不同？

> 注意：本题涉及跨文档推理，DSpark 论文与综述论文的 "Fine-tune" 概念可能不直接关联。期望回答能诚实指出这一点。
- **关联**：两篇论文都涉及对预训练模型的参数调整，但目的不同
- **不同**：
  - 综述中 Fine-tune：用领域数据更新 LLM 权重适配交通预测下游任务
  - DSpark 中：可能涉及训练 draft model 或 verification model，与 speculative decoding 的加速场景相关
- **关键评判**：回答不应强行编造二者关系；如果诚实指出"二者应用场景不同，无直接关联"则给高分

### GRAG-10：URL 数据泄露防护论文中描述的 LLM agent 威胁模型，与交通综述中提到的 LLM 隐私问题有何异同？两者提出的防护机制有无重叠之处？

- **相同点**：都关注 LLM 系统可能泄露敏感数据（私人信息、mobility data）
- **不同点**：
  - URL 论文重点：prompt injection → URL-based exfiltration（攻击面是 external resource retrieval）
  - 交通综述重点：LLM 记忆泄露 + 推断攻击 + 频繁交互暴露（攻击面更广）
- **防护机制重叠**：无直接重叠；URL 论文用动态 URL allow-list，交通综述用 differential privacy / homomorphic encryption / blockchain
- **关键评判**：回答若诚实指出"机制无直接重叠但目标相似"即可高分

### GRAG-11：南京市的自然资源（水资源、林木资源、生物资源）与人文资源（历史古迹、非物质文化遗产）之间存在哪些地理和历史上的关联？

> 本题基于南京文档的有限信息，期望回答基于文档提供的线索进行有限推理。
- **地理关联**：长江、秦淮河水系孕育了南京城市文明，形成了沿河的历史古迹（如夫子庙依秦淮河而建）
- **历史关联**：南京作为"六朝古都""十朝都会"的悠久历史，使得自然景观（紫金山、玄武湖）成为承载人文资源（中山陵、明孝陵）的地理载体
- **关键评判**：不强制要求推理深度，但不应编造文档未提及的具体关联细节

### GRAG-12：OneDrive 的安全机制与防止 URL 数据泄露论文中的防护策略，在技术思路上有什么相似之处和本质区别？

- **相似之处**：都是通过"限制可访问范围"来保障安全（OneDrive 用 Personal Vault/加密限制文件访问，URL 论文用 allow-list 限制 URL 访问）
- **本质区别**：
  - OneDrive：静态数据安全（存储加密、勒索软件检测），面向用户数据保护
  - URL 论文：动态交互安全（实时 URL 过滤），面向 LLM agent 的运行时攻击防护
- **关键评判**：回答若诚实指出"技术领域不同但安全哲学相似"即可高分

### GRAG-13：OneDrive 的"个人保管库"（Personal Vault）和"文件加密"在保护机制上有什么不同？它们分别应对哪种安全威胁？

- **Personal Vault**：需要身份验证才能访问，提供额外的访问控制层；应对未经授权的账户访问
- **文件加密**：对文件内容进行加密存储；应对数据传输/存储过程中的窃取
- **关键评判**：两功能的区别在于访问控制 vs 数据加密

### GRAG-14：URL 泄露论文中提到 "open redirects" 为什么能绕过 naive domain-based allow-listing？论文的 dynamic policy 如何克服这个漏洞？

- **open redirects 绕过原理**：受信任的域名（如 google.com/url?q=evil.com）可能包含重定向参数，攻击者可利用合法域名的重定向功能将请求转发到恶意站点，domain allow-list 只看域名无法识别
- **dynamic policy 方案**：仅允许已被独立 search index 收录过的 URL，重定向目标需也经过索引验证
- **关键评判**：核心是 trust-by-association（域名白名单）vs trust-by-verification（URL 级独立验证）

---

### COM-01：在 LLMs for Mobility Analysis 综述中，LLM 在交通预测领域有哪些传统方法不具备的优势？请列举并简要说明。

- **先进推理和上下文理解能力**：能解读数据中的复杂模式
- **灵活的迁移学习**：减少重新训练需求，尤其在 downstream data 有限时
- **可扩展性**：适合实时分析
- **多模态数据处理**：整合多种数据源（temporal sequences、contextual info、visual data 等）
- **可解释性**：能生成上下文解释，增强决策过程理解

### COM-02：DSpark 论文的核心创新点是什么？这项技术对 LLM serving 系统带来了什么具体改进？

- **核心创新**：
  - Semi-autoregressive architecture（parallel backbone + lightweight sequential module）
  - Confidence-scheduled verification（动态调整验证长度）
- **具体改进**：
  - 相比 MTP-1 基线，生成速度提升 60%-85%
  - 在高并发 serving 下防止吞吐率退化
  - 移动了 serving 系统的 Pareto 前沿

### COM-03：南京市有哪些自然资源？请按水资源、林木资源、生物资源分类列出。

- **水资源**：长江、秦淮河、玄武湖、莫愁湖（属长江水系）；汤山温泉、珍珠泉（地下水资源）
- **林木资源**：林木覆盖率 26.4%，建成区绿化覆盖率 45%，人均公共绿地面积 13.7 平方米
- **生物资源**：已记录 2530 种不同物种，其中国家重点保护野生动植物 72 种

### COM-04：综述论文中 Fine-tune 和 Zero-Shot/Few-Shot 两种策略各自适用于什么场景？它们的优缺点分别是什么？

- **Fine-tune**：
  - 适用：有充足领域数据集，需高精度特定任务预测
  - 优点：定制度高，准确性强；缺点：计算成本高，需训练资源
- **Zero-Shot/Few-Shot**：
  - 适用：数据稀缺，快速原型，跨任务迁移
  - 优点：无需训练，即用即得；缺点：精度不如微调，依赖 prompt 质量

### COM-05：交通综述和 URL 数据泄露论文都提到了"LLM 的隐私风险"，请分别总结两篇论文对该问题的观点和提出的应对方案。

- **交通综述**：
  - 观点：ITS 设备密钥管理薄弱；LLM 记忆训练数据可被提取；LLM 能推断私人信息；频繁交互暴露数据
  - 方案：differential privacy（DP-SGD、federated learning）、homomorphic encryption、blockchain-based framework
- **URL 泄露论文**：
  - 观点：prompt injection 可构造恶意 URL 窃取敏感数据；naive domain allow-listing 不够
  - 方案：dynamic policy（URL 级 enforcement，基于独立 search index 收录验证）

### COM-06：OneDrive 入门指南中，用户如何在不同设备间访问和管理文件？请概括其主要功能路径。

- **跨设备访问**：通过 OneDrive.com 或移动应用在任何设备上创建、访问和编辑文件
- **电脑文件夹备份**：自动备份桌面、文档、图片文件夹到 OneDrive
- **手机备份**：iOS/Android 移动应用支持照片视频自动备份、文档扫描
- **共享协作**：与他人共享文档/文件夹/照片，无需对方账户即可查看编辑

---

### NEG-01：DSpark 论文中使用的训练数据集名称是什么？数据集规模有多大？

> **正确答案**：文档中未提及具体训练数据集名称和规模（论文仅提及"offline benchmarks across diverse domains"和"production serving system under live user traffic"等定性描述）。
- 若回答"不知道/文档未提及"→ 正常
- 若回答具体数据集名（如"OpenWebText"、"The Pile"等）→ 幻觉（负分）

### NEG-02：根据文档中的信息，南京市目前的 GDP 总量和人均 GDP 分别是多少？

> **正确答案**：南京城市地理环境文档中未包含 GDP 相关数据（文档仅涵盖地理、自然资源、人文资源）。
- 若回答"文档中未提及 GDP 信息"→ 正常
- 若给出任何具体 GDP 数字 → 幻觉，说明模型在高温下从训练数据中补充了编造信息

---

---

## 七、Agent 评分规则（机械判定标准）

### 7.1 评分维度与权重

| 维度 | 权重 | 评估对象 |
|------|------|---------|
| A. 事实准确性 | 0.30 | 单次回答 |
| B. 完整性 | 0.20 | 单次回答 |
| C. 聚焦度 | 0.10 | 单次回答 |
| D. 幻觉程度 | 0.25 | 单次回答 |
| E. 一致性 | 0.15 | 跨温度（6 个温度） |

### 7.2 单次回答评分规则（A, B, C, D）

**评分流程**：
1. 读取题目的"期望关键事实"列表，标记为 `expected_facts = [f1, f2, ...]`
2. 逐条检查回答文本是否包含该事实（同义转述视为命中）
3. 统计命中数 `hit`、错误数 `wrong`（陈述了但与原文不符）、编造数 `fabricated`（回答中存在但原文不存在的"事实"）

**A. 事实准确性（1-5）**
```
hit_ratio = hit / (hit + wrong + fabricated)
A = round(hit_ratio * 4 + 1)   # 全错→1, 全对→5
若 hit + wrong + fabricated == 0: A = 0  (无法判定)
若命中率 100%: A = 5; >=80%: A = 4; >=60%: A = 3; >=30%: A = 2; <30%: A = 1
```

**B. 完整性（1-5）**
```
coverage = hit / len(expected_facts)
B = round(coverage * 4 + 1)
若 coverage >= 1.0: B = 5; >= 0.8: B = 4; >= 0.6: B = 3; >= 0.3: B = 2; < 0.3: B = 1
```

**C. 聚焦度（1-5）**
```
若回答直接命中问题核心、无明显无关展开: C = 5
若有 1-2 句无关补充: C = 4
若有整段无关内容但核心回答仍可识别: C = 3
若无内容占比过半: C = 2
若完全跑题: C = 1
```

**D. 幻觉程度（1-5）**
```
fabricated_count = 编造事实数
若 fabricated_count == 0: D = 5
若 1 个且不关键: D = 4
若 1-2 个且涉及核心: D = 3
若 >= 3 个: D = 2
若几乎全部编造: D = 1
```

### 7.3 跨温度一致性规则（E）

1. 收集同一问题 6 个温度下的 A 分数，获得 `a_scores = [A_0, A_0.1, ..., A_1.0]`
2. 计算 A 分数的标准差 `std`；同时检查各温度下**期望关键事实命中数**的波动范围 `hit_range = max(hit) - min(hit)`

```
若 std <= 0.50 且 hit_range <= 1:                         E = 5
若 std <= 0.80 且 hit_range <= 2:                         E = 4
若 hit_range > 2 但低温段(0.0-0.3)命中数稳定(差值<=1):     E = 3
若逾半数温度下核心事实与其余温度矛盾:                     E = 2
若各温度下回答方向完全随机、无明显交集:                   E = 1
```

> 说明：E 的核心衡量是"事实命中数"的跨温度稳定性，而非 A/B/C/D 分数的绝对一致。std 仅作辅助参考。

### 7.4 综合得分公式

> **统一使用 7.1 节定义的权重（A=0.30, B=0.20, C=0.10, D=0.25, E=0.15）**。

**单次回答**（A/B/C/D 四维度，权重和 = 0.85）：
```
Score_single = A*0.30 + B*0.20 + C*0.10 + D*0.25
```
范围 [0.85, 4.25]（未包含 E，不归一化，仅在相对比较中使用）。

**单问题汇总**（同权重，含 E 六温度均值，权重和 = 1.00）：
```
A_mean = mean(A across 6 temps)
B_mean = mean(B across 6 temps)
C_mean = mean(C across 6 temps)
D_mean = mean(D across 6 temps)
Score_question = A_mean*0.30 + B_mean*0.20 + C_mean*0.10 + D_mean*0.25 + E*0.15
```
范围 [1.0, 5.0]（各维度 1-5 分，权重和为 1.0，自然落在 5 分制范围内，**无需归一化**）。

**模式总得分**：
```
Score_mode = mean(all Score_question)
```

---

## 八、评分输出 JSON Schema

> Agent 完成评分后，必须输出 JSON 文件 `plans/temperature-test-results.json`，格式如下：

```json
{
  "meta": {
    "test_date": "2026-07-02",
    "temperatures": [0.0, 0.1, 0.3, 0.5, 0.7, 1.0],
    "model": "deepseek-chat",
    "files": [
      "test_texts/2405.02357v2.pdf",
      "test_texts/DSpark_paper.pdf",
      "test_texts/LLMs_for_Mobility_Analysis_Survey.md",
      "test_texts/OneDrive 入门.pdf",
      "test_texts/prevent-url-data-exfil.pdf",
      "test_texts/南京城市地理环境.docx"
    ]
  },
  "results": {
    "rag": {
      "RAG-01": {
        "answers": {
          "0.0": "完整回答文本...",
          "0.1": "...",
          "0.3": "...",
          "0.5": "...",
          "0.7": "...",
          "1.0": "..."
        },
        "scores": {
          "0.0": {"A": 5, "B": 5, "C": 5, "D": 5, "single": 4.25},
          "0.1": {"A": 5, "B": 5, "C": 5, "D": 5, "single": 4.25},
          "0.3": {"A": 4, "B": 5, "C": 5, "D": 4, "single": 3.85},
          "0.5": {"A": 3, "B": 3, "C": 4, "D": 3, "single": 2.65},
          "0.7": {"A": 2, "B": 2, "C": 3, "D": 2, "single": 1.80},
          "1.0": {"A": 1, "B": 1, "C": 2, "D": 1, "single": 1.05}
        },
        "E": 3,
        "score_question": 3.2,
        "notes": ["高温下数值出现偏差"]
      }
    },
    "graph_rag": {
      "GRAG-01": { "...": "同上结构" }
    }
  },
  "summary": {
    "rag": {
      "scores_by_temperature": {
        "0.0": 4.10,
        "0.1": 4.05,
        "0.3": 3.80,
        "0.5": 3.20,
        "0.7": 2.60,
        "1.0": 2.10
      },
      "overall": 3.31,
      "best_temperature": 0.0,
      "hallucination_rate": 0.15,
      "refuse_rate": 0.02
    },
    "graph_rag": {
      "scores_by_temperature": {
        "0.0": 4.00,
        "0.1": 3.95,
        "0.3": 3.70,
        "0.5": 3.10,
        "0.7": 2.50,
        "1.0": 2.00
      },
      "overall": 3.21,
      "best_temperature": 0.0,
      "hallucination_rate": 0.18,
      "refuse_rate": 0.03
    },
    "comparison": {
      "rag_vs_graph_diff": 0.10,
      "rag_better_at": ["基础事实检索", "数值精度"],
      "graph_rag_better_at": ["跨文档关联", "实体关系推理"]
    }
  }
}
```

### JSON 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `meta` | object | 测试元信息 |
| `results.{rag/graph_rag}.{ID}.answers` | object | 各温度下的完整回答原文 |
| `results.{rag/graph_rag}.{ID}.scores` | object | 每个温度下的 A/B/C/D 分及 single 加权分 |
| `results.{rag/graph_rag}.{ID}.E` | number | 一致性评分 |
| `results.{rag/graph_rag}.{ID}.score_question` | number | 汇总分（5 分制） |
| `results.{rag/graph_rag}.{ID}.notes` | array | 关键发现备注 |
| `summary.{rag/graph_rag}.scores_by_temperature` | object | 每个温度下所有题目均分 |
| `summary.{rag/graph_rag}.overall` | number | 模式总均分 |
| `summary.{rag/graph_rag}.hallucination_rate` | number | D < 4 的答题比例 |
| `summary.{rag/graph_rag}.refuse_rate` | number | A=0 且 D=5 的答题比例（模型未编造但回答无可量化事实，含诚实拒绝和检索失败） |
| `summary.comparison` | object | RAG vs Graph RAG 对比分析 |

---

## 九、Agent 执行清单

1. **应用代码修复**：完成第 3.A 节的 FIX-1/FIX-2/FIX-3
2. **读取**本文件，获取全部 34 题及期望关键事实（RAG 12 + Graph RAG 14 + COM 6 + NEG 2）
3. **初始化索引**（一次）：按 5.B 节方案构建 RAG 和 Graph RAG 索引，缓存返回对象
4. **逐题逐温度调用** `answer_query_stream` 和 `graph_query_stream`：
   - RAG 答题：RAG-01~12 + COM-01~06 + NEG-01~02 = 20 题 × 6 温度 = 120 次
   - Graph RAG 答题：GRAG-01~14 + COM-01~06 + NEG-01~02 = 22 题 × 6 温度 = 132 次
   - 总计 252 次调用，收集全部回答原文
5. **逐题评分**（按第 7 节的机械判定规则），给出 A/B/C/D
6. **一致性评分**（按 7.3 节规则，基于 6 个温度下的事实命中数稳定性给出 E）
7. **输出 JSON**（按第 8 节 Schema），写入 `plans/temperature-test-results.json`
