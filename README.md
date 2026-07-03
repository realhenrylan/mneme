# RAG-SYS: Hybrid Search · Graph RAG

从零实现检索增强生成 (RAG) 的完整项目，覆盖文档索引 → 混合检索 → LLM 生成全链路，附带 Rich TUI 前端。

## 项目结构

```
.
├── src/                         # 生产代码
│   ├── rag.py                   # 核心 RAG 管道（936 行）
│   │                           #   PDF/DOCX/文本解析、chunking、ChromaDB 索引、
│   │                           #   混合检索（semantic + BM25 + RRF）、
│   │                           #   LLM 查询拆解、anchor→enrich 分层检索、
│   │                           #   dynamic_top_k、流式生成、CLI 交互式对话
│   ├── graph_rag.py             # Graph RAG（554 行）
│   │                           #   LLM 实体提取、NetworkX 知识图谱、
│   │                           #   BFS 扩散检索、语义+图谱双路融合、CLI 交互
│   └── rag_query_decomposer.py  # LLM 查询拆解（85 行）
│                               #   OpenAI 兼容 API 拆解复杂查询、KISS 守卫
├── tui/                         # Rich TUI 前端
│   ├── __main__.py              # 入口：python -m tui
│   ├── app.py                   # RagApp 编排（home → loading → chat）
│   ├── service.py               # LocalRagService（桥接 TUI 与后端）
│   ├── theme.py                 # 暗紫配色主题
│   ├── keys.py                  # 斜杠命令定义
│   ├── screens/
│   │   ├── home.py              # 首页：模式选择、目录扫描、文件勾选
│   │   ├── chat.py              # 对话：流式问答、斜杠命令、设置向导
│   │   └── loading.py           # 索引构建进度条
│   ├── components/
│   │   ├── message.py           # 消息面板（用户/助手/来源/错误/警告）
│   │   ├── prompt.py            # 斜杠命令匹配器
│   │   ├── footer.py            # 状态栏（CWD/API/模式/块数）
│   │   └── sidebar.py           # 侧边栏统计面板
│   └── dialogs/
│       ├── file_manager.py      # 文件添加/移除对话框
│       ├── status.py            # 系统状态对话框
│       └── help.py              # 帮助命令对话框
├── tests/                       # 测试套件
│   ├── test_retrieval_fix.py    # 8 项回归测试（空间保留、tokenize、anchor、Recall）
│   ├── test_query_decomposer.py # 9 项测试（5 mock + 2 集成 + 2 回归）
│   ├── test_hierarchical_enrich.py # 6 项测试（4 单元 + 2 集成质量）
│   └── analysis/                # 分析/调试脚本
├── scripts/                     # 分析工具
│   ├── run_temperature_test.py  # Temperature 基准测试（6 温度 × 72 题）
│   ├── generate_report.py       # 生成 Markdown 评测报告
│   └── fix_scoring.py           # 精炼评分脚本
├── plans/                       # 设计文档 / 计划（14 份）
├── reports/                     # 生成的测试报告
├── test_texts/                  # 测试文档（PDF / DOCX / MD）
├── chroma_db/                   # ChromaDB 持久化目录（运行时生成）
└── .env                         # API 密钥配置（需创建）
```

## 核心特性

### 1. 混合检索 (Hybrid Search)

语义检索（Sentence-BERT `all-MiniLM-L6-v2` 余弦相似度）+ BM25 关键词检索 → RRF (Reciprocal Rank Fusion) 融合。BM25 token 使用自定义 `_tokenize()`：支持中英混合、大小写折叠、标点清理。

### 2. LLM 查询拆解

`decompose_query_llm` 使用 LLM 将复合查询拆为多个原子子查询，`ThreadPoolExecutor` 并发检索，按 chunk 去重后送 `dynamic_top_k` 截断。KISS 守卫：简短查询跳过 LLM 调用。

### 3. Anchor → Enrich 分层检索

PDF 首页取前 5 行作为 anchor chunk（`chunk_type:"anchor"`），RRF 分数 ×2 提升。命中 anchor 时自动加载首页全文替换上下文，确保回答包含完整元数据（机构、摘要等）。

### 4. 动态 Top-K

自动选择最优 chunk 数量：去重分数列表 → 降序排列 → 最大间隔 (Max-Gap) 截断。

### 5. Graph RAG

- LLM 批量提取文档实体（带缓存）
- NetworkX 构建知识图谱（共现关系加权）
- `KnowledgeGraph` 类支持 pickle 持久化，避免重复提取
- BFS 扩散检索相关实体
- 语义 + 图谱双路加权融合

### 6. 流式 LLM 生成

`answer_with_llm_history_stream` / `answer_query_stream` 支持 OpenAI 兼容 API 的流式输出，内置 `RateLimitError` / `APIConnectionError` 友好提示。

### 7. Rich TUI 前端

基于 [Rich](https://rich.readthedocs.io/) + [questionary](https://questionary.readthedocs.io/) 的终端界面，支持：

- Standard RAG / Graph RAG 模式切换
- 文件管理（添加/移除/重建索引）+ 实时进度显示
- 流式对话 + 历史记录
- 斜杠命令（`/help` `/files` `/mode` `/alpha` `/models` `/settings` `/status` `/clear` `/quit`）
- 设置向导（API Key / Base URL / Model / Temperature / Top-K / Alpha）
- 暗紫配色主题

## 快速开始

### 环境要求

- Python 3.9+
- 虚拟环境（推荐）

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置

在项目根目录创建 `.env` 文件：

```env
API_KEY=sk-your-key-here
BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_TEMPERATURE=0.1
LLM_TOP_K_MIN=3
LLM_TOP_K_MAX=20
ALPHA=0.7
```

支持任何 OpenAI 兼容 API（DeepSeek / OpenAI / 通义千问等）。

### 运行

**Standard RAG CLI**（交互式对话）：

```bash
python src/rag.py --files test_texts/2405.02357v2.pdf
```

**一次性查询**：

```bash
python src/rag.py --files test_texts/2405.02357v2.pdf --query "RAG 的原理是什么？"
```

**Graph RAG CLI**：

```bash
python src/graph_rag.py --files test_texts/2405.02357v2.pdf
```

**TUI 前端**：

```bash
python -m tui
```

**Temperature 基准测试**：

```bash
python scripts/run_temperature_test.py [--rebuild]
python scripts/generate_report.py
```

## 测试

```bash
# 回归测试（无需 API）
pytest tests/test_retrieval_fix.py -v

# 查询拆解测试（mock 单元测试，无需 API）
pytest tests/test_query_decomposer.py -k "not integration" -v

# 分层 enrich 测试（单元测试，无需 API）
pytest tests/test_hierarchical_enrich.py -k "not integration" -v

# 集成测试（需要 API key）
pytest tests/test_query_decomposer.py tests/test_hierarchical_enrich.py -k "integration" -v

# 全量回归
pytest tests/ -k "not integration" -v
```

## 依赖

| 包 | 用途 |
|---|---|
| chromadb | 向量数据库 |
| sentence-transformers | `all-MiniLM-L6-v2` 嵌入模型 |
| rank_bm25 | BM25 关键词检索 |
| openai | OpenAI 兼容 API 客户端 |
| PyMuPDF / pdfplumber | PDF 文本提取 |
| python-docx | DOCX 文件解析 |
| langchain-text-splitters | RecursiveCharacterTextSplitter |
| networkx | 知识图谱构建 |
| rich | 终端 UI 框架 |
| questionary | 交互式 CLI 提示 |
| python-dotenv | .env 文件加载 |

## 许可

本项目仅供学习参考。
