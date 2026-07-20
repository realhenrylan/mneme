# Mneme 项目综合改进评估报告

**评估日期：** 2026-07-20
**范围：** 核心 RAG / Graph RAG、TUI、索引与缓存、测试、依赖、发布配置、安全和可维护性。
**方式：** 静态代码审查与本地测试基线验证；本报告不包含功能实现改动。

---

## 1. 结论摘要

Mneme 已具备完整的本地文档问答产品雏形：混合检索、Graph RAG、来源展示、流式 TUI、文件监听和首次配置引导均已实现。近期对图谱噪音、Graph RAG 上下文增强和代码重复的处理方向也正确。

下一阶段不建议优先继续叠加新的检索策略或 UI 功能，而应先补齐三个基础能力：

1. **索引与来源一致性**：保证修改、删除、同名文件和重复文本不会造成过期或错误引用。
2. **可重复的质量基线**：使测试在干净环境、Windows 和 CI 中稳定运行，且默认不调用真实 LLM。
3. **数据安全与可解释性**：避免密钥泄漏，明确远程数据外发，并让答案可定位到具体证据。

完成以上三项后，再投入性能扩展、评测体系和架构演进，收益最高、返工最少。

---

## 2. 本次验证结果

### 2.1 测试基线

在当前 Windows / Python 3.12 环境执行测试套件，结果如下：

| 项目 | 结果 |
| --- | ---: |
| 通过 | 105 |
| 失败 | 12 |
| 报错 | 3 |
| 警告 | 4 |

主要观察：

- 多个测试直接调用 Unix rm -rf 清理测试数据库；Windows 中只要目标目录已存在就会报 FileNotFoundError。
- 依赖只定义了下限，当前环境解析到 ChromaDB 1.5.9、OpenAI 2.44.0 等较新版本；完整测试出现了 ChromaDB 兼容性异常，说明缺少稳定的受支持依赖组合。
- integration 标记尚未注册，产生未知标记警告。
- 一个端到端测试只检查 .env 是否存在；本机有凭据时，普通测试命令就可能调用真实 LLM 并产生费用。

### 2.2 项目现状亮点

- 标准 RAG 与 Graph RAG 已共享部分 CLI、索引辅助逻辑。
- 图谱已使用 min_cooccur 和 max_entities_per_chunk 抑制全连接噪音。
- PDF anchor 与来源标注已进入上下文构建。
- TUI 已拥有配置、文件管理、监听和流式响应，产品骨架完整。

---

## 3. P0：应先解决的问题

P0 表示会影响答案正确性、删除语义、密钥安全或发布可靠性的问题。建议在新增功能前完成。

### 3.1 索引不会识别文件内容变更

#### 现状

默认 collection 名称只由文件路径列表的 MD5 计算。只要路径不变，即使文件内容、切块参数或 embedding 模型变化，已有 collection 也会被直接复用。

增量添加同一路径文件时，chunk ID 也只依赖路径和序号；如果新版文件的分块变少，旧版本末尾的 chunk 不会自动删除。

#### 影响

- 用户更新文档后，系统可能继续回答旧内容。
- 文件监听的自动索引不能保证索引与磁盘一致。
- 切块或 embedding 配置变更后，旧向量可能与新配置混用。

#### 建议方案

为 collection 保存 manifest，至少记录：

~~~
collection schema version
embedding model identifier and dimension
chunking configuration
canonical source path and source_id
content SHA-256, size, mtime
indexed chunk IDs
~~~

同步逻辑应改为“按来源替换”：规范化路径、比对内容哈希和配置、删除该来源旧 chunk、写入新 chunk，最后原子更新 manifest 和检索快照。不要只以 collection 是否存在来决定复用。

### 3.2 删除按文件名匹配，会误删同名文件

#### 现状与影响

metadata 主要存储 basename，删除也按 filename 匹配。不同目录中的两个 report.pdf 无法区分，删除其中一个会删除两者的 chunk。文件列表、来源展示和后续更新也会发生歧义。

#### 建议方案

- 所有 chunk 保存 source_id 和规范化绝对 source_path；basename 只用于展示。
- 文件删除使用完整路径或 source_id，不能使用 basename。
- 重名时 UI 显示父目录或短 ID。
- 索引、图谱、引用和删除统一以 source_id 为主键。

### 3.3 Graph RAG 删除文件后保留过期图谱

#### 现状

Graph RAG 模式下新增文件会重建并保存图谱；删除文件只更新 collection、文档列表和 BM25，不会重建图谱。

#### 影响

被删文件的实体、关系和 chunk 映射仍可能参与图谱扩展，造成已删除内容重新出现在回答中，也形成敏感数据残留风险。

#### 建议方案

短期内，新增、修改、删除任一来源后都让图谱缓存失效并重建；缓存文件必须绑定 manifest version。中期再做按来源的图谱增量更新。

### 3.4 文本内容被当作检索主键，引用可能错位

#### 现状

RRF 融合、文本到 metadata 的映射和 Graph RAG 都把 chunk 文本当作字典 key。不同文件含有相同标题、版权页、模板段落或重复正文时，后写入的元数据会覆盖先写入的元数据。

#### 影响

- 回答可能基于 A 文件内容，却标注为 B 文件来源。
- 重复内容被错误去重，降低多来源覆盖。
- 图谱无法稳定回溯正确的 chunk、来源和页码。

#### 建议方案

全链路使用稳定的 ChunkRecord：

~~~
chunk_id, source_id, source_path, source_name,
page, chunk_index, text, score
~~~

RRF、去重、图谱映射和引用均使用 chunk_id；仅在展示和构建上下文时读取 text。

### 3.5 配置失败路径泄露完整 API Key

配置保存失败的错误提示中包含完整 API Key，可能进入终端历史、截图、录屏或支持日志。

#### 建议方案

- 立即删除所有完整密钥输出。
- 报错只显示失败原因与配置文件路径；如需显示状态，使用脱敏值。
- 增加回归测试，断言 stdout、stderr、异常对象和 debug 日志均不包含 API Key。

### 3.6 文档提示注入与远程外发缺少显式控制

检索到的原始文档直接拼接进 prompt，而 endpoint 可由用户配置为任意 OpenAI-compatible 服务。

#### 风险

- 恶意文档可能用“忽略指令”等内容诱导模型。
- 私有文件片段会被发往当前远程服务，用户未必意识到。
- 监听目录、异常 PDF 或大文件可能造成无意外发与资源消耗。

#### 建议方案

1. 使用 untrusted document 边界包裹证据；系统提示明确要求不执行文档内指令。
2. 配置页展示 endpoint、模型和“文档片段会发送到远程服务”的说明；首次使用非默认 endpoint 时确认。
3. 增加敏感文件排除、文件大小、页数、chunk 数上限与路径 allowlist。
4. 默认要求远程 endpoint 为 HTTPS；本地 endpoint 允许显式例外。
5. 增加 prompt-injection 回归测试。

### 3.7 不应从不可信来源加载 pickle 图谱缓存

当前 KG 使用 pickle 持久化。若缓存文件可被他人替换或从不可信位置导入，pickle.load 存在任意代码执行风险。

#### 建议方案

使用带 schema version 的 JSON 或 MsgPack（例如 NetworkX node-link 格式）持久化图谱。若短期保留 pickle，应限制为仅加载本地私有数据目录中由当前进程生成的缓存，并在文档中明确风险。

---

## 4. P1：稳定性、性能与配置一致性

### 4.1 文件监听静默吞错，查询与写入并发不安全

监听回调吞掉所有异常；用户不知道文件是否真正入库。监听在后台线程运行，增删有写锁，但查询没有对应读锁，可能读到 BM25、文档列表、图谱和 collection 的不同版本。

#### 建议方案

- 使用单一索引任务队列，串行处理新增、更新、删除和重建图谱。
- 查询使用不可变快照或读写锁；一次查询固定使用同一版本的 docs、metadatas、BM25 和 KG。
- status 页显示待处理、成功、跳过、失败和最近错误，不能静默失败。
- 分别测试 created、modified、moved、deleted 事件。

### 4.2 全量读取和 BM25 重建限制规模

启动已有 collection、每次增删文件都会读取全部 documents/metadatas，并从全量内容重新构建 BM25。语料增长后，内存、启动时间和监听增量更新都会线性恶化。

#### 建议方案

- 让 metadata、BM25 tokenized corpus、图谱与同一个 manifest version 一起持久化。
- 增量更新只处理受影响来源。
- 大语料采用 collection 分片、来源分页，或迁移到支持持久化倒排索引的后端。
- 记录并显示索引、embedding、BM25、图谱构建和缓存命中耗时。

### 4.3 Anchor 在查询阶段重读 PDF

命中 anchor 后会复制全部 documents 并重新打开源 PDF 读取首页。文件若已经移动、删除或修改，会造成“向量检索基于旧内容、上下文却来自新文件”的不一致，也增加每次查询的 I/O 与解析成本。

#### 建议方案

- 在索引阶段保存首页正文或独立首段 chunk。
- 查询阶段只处理命中的 ChunkRecord，不要复制整库文档列表。
- 如必须重读原文件，先验证 content hash；不一致则提示索引过期并同步。

### 4.4 Embedding 配置与实际行为不一致

环境中可配置 EMBEDDING_MODEL_PATH，但模块后续把模型名重新设为固定的 all-MiniLM-L6-v2；ModelScope 回退下载也使用固定名称。

#### 建议方案

- 用单一 Settings 对象集中读取、验证配置。
- 区分 model_id、local_path、provider 和 cache_dir。
- 把模型 ID、维度和归一化方式写入 manifest，不匹配即要求重建。
- 增加环境变量覆盖默认值、不同模型禁止复用 collection 的测试。

### 4.5 Graph RAG client 缓存不随设置刷新

Graph RAG 缓存模块级 OpenAI client；会话中修改 API Key 或 Base URL 后，实体提取可能仍走旧 client。

#### 建议方案

- 将 client 放入服务实例，不使用无版本的模块全局单例。
- 缓存 key 至少包含 endpoint、API Key 指纹和 timeout；设置变更后主动失效。
- 增加“会话内切换 provider 后实体提取使用新 endpoint”的测试。

### 4.6 统一 LLM 调用的超时、重试和取消

问答、查询拆解和实体抽取的超时、重试和错误处理方式不一致；图谱实体抽取不应无限阻塞交互。

建议封装统一 LLM gateway，提供超时、有限重试、指数退避、用户取消、错误分类、脱敏请求日志、并发上限和 token/费用上限。

---

## 5. P1：检索质量、引用与可解释性

### 5.1 建立中英混合 benchmark

目前有针对 anchor 和查询拆解的测试，但缺少可持续比较版本效果的评测体系。

| 类别 | 验收标准 |
| --- | --- |
| 单文档事实问答 | 答案正确且引用正确文件/页码 |
| 元数据问答 | 正确识别标题、作者、文件数量等 |
| 跨文档问答 | 覆盖多个来源，不混淆同名文件 |
| 中英混合查询 | Recall@k、MRR、nDCG 不低于基线 |
| 无依据问题 | 明确拒答，不编造来源 |
| 修改/删除后查询 | 不返回过期内容 |
| 对抗文档 | 不遵循文档中的恶意指令 |

每次修改 chunk、embedding、RRF、Graph RAG 参数或 prompt，都应自动比较新旧指标。

### 5.2 改进中文 BM25 分词

中文连续文本当前会被当作较长连续 token。对中文文档和短查询，这通常不如中文分词或字符 n-gram 稳定。

建议先通过 benchmark 验证，再考虑中文词粒度与字符 bigram 混合，保留英文、数字、缩写和文件名 token，并将标题、文件名、页码设为独立字段权重。

### 5.3 将来源展示升级为可验证引用

当前来源区只展示前五个摘要，回答正文没有关键事实与证据的明确关系。

建议上下文使用稳定 citation ID，例如 S1；要求模型在关键事实后附 citation ID。TUI 将其解析为文件、页码和片段，并在证据不足时显示“未找到可靠依据”。后续可添加打开本地文件、定位页码和复制引用的动作。

---

## 6. P2：架构、发布与维护体验

### 6.1 拆分核心模块职责

src/rag.py 同时承担配置加载、解析、切块、索引、BM25、融合、上下文、LLM 和 CLI。原型期合理，但已成为测试隔离和功能演进的阻力。

建议逐步形成：

~~~
config.py        Settings 与配置验证
domain.py        SourceRecord / ChunkRecord / RetrievalResult
loaders.py       PDF、DOCX、text 解析
chunking.py      切块策略
index_store.py   Chroma、manifest、同步和删除
lexical_index.py BM25 生命周期
retrieval.py     vector、BM25、RRF、rerank
llm_gateway.py   client、超时、重试和流式响应
graph.py         图谱构建、持久化、版本检查
service.py       TUI/CLI 用例层
~~~

优先引入数据模型和依赖注入；不要求一次性重写。

### 6.2 发布与依赖管理

- 选择 pyproject.toml 作为唯一依赖来源，移除或自动生成重复的 requirements.txt。
- 引入 lock file 或 constraints，明确支持 Python 3.10、3.11、3.12 的依赖矩阵。
- 增加 mneme CLI entry point，降低对工作目录和 python -m 的依赖。
- 将 ChromaDB、模型和 KG 缓存移出 src，使用用户数据目录和可配置 MNEME_DATA_DIR。
- 对齐 pyproject.toml 版本和 CHANGELOG 发布版本。
- 补充 MIT LICENSE、贡献说明、发布流程和 GitHub CI workflow。

### 6.3 可观测性

默认不要保存原始问题和文档内容，但应保留脱敏指标：索引耗时、chunk 数、候选数、最终 top-k、来源覆盖率、LLM 耗时、重试次数、错误类别、监听状态和 manifest version。status 页应显示摘要，debug 模式写入本地脱敏日志。

---

## 7. 推荐实施顺序

### 阶段 A：可靠底座

1. 修复 Windows 测试清理、pytest marker、集成测试开关和 CI。
2. 锁定依赖组合，并修复当前测试基线。
3. 移除完整 API Key 的错误输出。
4. 引入 source_id，修复同名文件删除和重复文本引用错位。
5. 在任意来源变更后失效并重建 Graph RAG 缓存。

**完成标准：** 纯单元测试在干净 Windows/Linux 环境稳定通过；不存在误删、过期图谱或明文密钥输出。

### 阶段 B：索引与检索长期正确

1. 实现 content hash 与配置指纹 manifest。
2. 完成按 source 的原子更新、删除和快照切换。
3. RRF、Graph RAG 和 citations 全部迁移至 chunk_id。
4. 加入修改、删除、同名、重复文本的端到端回归测试。

**完成标准：** 磁盘文件、Chroma、BM25、KG 和 TUI 来源展示始终对应同一 manifest version。

### 阶段 C：质量、性能和产品体验

1. 引入 benchmark 与检索质量门槛。
2. 完成引用 ID、页码定位、拒答阈值和提示注入防护。
3. 引入索引队列、查询快照和增量缓存。
4. 逐步拆分核心模块，补齐运行指标。

**完成标准：** 每次优化可量化收益；大文档集更新不阻塞交互；用户能验证关键回答的证据来源。

---

## 8. 建议的首个实施任务

建议将第一个实施任务定为：

> 引入 source_id 与索引 manifest，修复同名文件删除、内容变更重建、图谱缓存失效和重复文本引用错位。

该任务同时解决最高风险的答案正确性问题，并为后续性能优化、可靠引用和图谱增量更新建立统一的数据基础。
