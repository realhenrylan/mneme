# Mneme

<p align="center">
  <img src="./.github/images/mneme-logo.svg" alt="MNEME Logo" width="70%">
</p>

> 以希腊记忆女神 Mnemosyne 命名 —— 一个面向本地文档、带终端 UI 的检索增强生成（RAG）系统。

[English](./README.md)

Mneme 为本地文档建立索引，并通过 OpenAI 兼容 API 回答问题。项目提供 Standard RAG 和 Graph RAG 两种模式，以及双语终端 UI 和 Python CLI。

## 特性

- **混合检索** — sentence-transformers + ChromaDB 语义检索，通过 RRF（倒数排名融合）与 BM25 关键词检索融合。
- **Graph RAG** — 使用大语言模型提取实体关系，扩展跨文档关联检索。
- **查询拆解** — 将复杂问题拆分为子查询并发执行。
- **Manifest 一致性索引** — 使用规范化 source ID、内容哈希、稳定 chunk ID、原子化来源替换、精确删除和 manifest 版本，保持索引与文件一致。
- **可核验回答** — 提供查询级引用（`S1`、`S2`……）、来源路径、PDF 页码、chunk ID 和明确的不可信文档边界。
- **安全 Graph RAG 缓存** — 图谱缓存使用带 schema 校验的 JSON，不加载 pickle。
- **TUI 与文件监控** — 支持流式聊天、斜杠命令、设置、文件管理、目录监控，以及串行化索引更新。
- **端点与资源保护** — 远程端点默认要求 HTTPS，并限制发送的上下文、文档大小、PDF 页数和可选路径根目录。

## 支持的文件类型

| 类型 | 扩展名 |
|------|--------|
| PDF | `.pdf` |
| Word | `.docx` |
| 文本与 Markdown | `.txt`、`.md`、`.markdown`、`.log` |
| Web 与数据 | `.html`、`.htm`、`.json`、`.csv`、`.xml`、`.yaml`、`.yml` |
| 配置文件 | `.toml`、`.cfg`、`.ini`、`.conf` |
| 源代码 | `.py`、`.js`、`.ts`、`.css`、`.sql`、`.sh`、`.bat` |

## 架构

```
用户问题
  → 查询拆解
  → 并发混合检索 / Graph RAG 图谱扩展
  → chunk 去重与动态 Top-K
  → PDF 锚点增强
  → 带引用、长度受控的不可信文档上下文
  → 大语言模型回答 + 可核验来源
```

| 模式 | 检索方式 | 适用场景 |
|------|----------|----------|
| **Standard RAG** | BM25 + ChromaDB + RRF 融合 | 通用问答和大规模文档集 |
| **Graph RAG** | Standard RAG + 实体图谱扩展 + alpha 融合 | 关联性强、跨文档的问题 |

## 快速开始

### 环境要求

- Python 3.10 或更高版本
- 一个 OpenAI 兼容 API 端点和 API Key（例如 DeepSeek、OpenAI）

### 安装

```bash
git clone https://github.com/realhenrylan/mneme.git
cd mneme
python -m venv .venv
```

激活虚拟环境：

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

安装项目和开发测试依赖：

```bash
python -m pip install -e ".[dev]"
```

### 配置

```powershell
copy .env.example .env       # Windows PowerShell
# cp .env.example .env       # macOS / Linux
```

至少设置以下配置：

```dotenv
API_KEY=sk-your-api-key-here
BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

首次启动时，配置向导也可以收集并保存 API 设置。API Key 保存在 `.env` 中；不要提交该文件，也不要把密钥、密码等敏感文件加入索引。

### 启动终端 UI

```bash
python -m tui
```

UI 支持 Standard RAG、Graph RAG、文件管理、目录监控、设置、来源展示和流式回答。

### 启动 CLI

启动 Standard RAG 交互式会话：

```bash
python -m src.rag --files /path/to/docs --collection my_docs
```

启动 Graph RAG 交互式会话：

```bash
python -m src.graph_rag --files /path/to/docs --collection my_docs --alpha 0.7
```

只有在确实需要重建 collection 时才使用 `--rebuild`。Graph RAG 还支持单次查询：

```bash
python -m src.graph_rag \
  --files /path/to/docs \
  --query "主要结论是什么？"
```

## TUI 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示全部命令 |
| `/files` | 添加、删除、列出文件，启动或停止监控 |
| `/mode` | 切换 Standard RAG / Graph RAG |
| `/alpha` | 设置 Graph RAG 融合权重 |
| `/settings` | 查看或修改 API 设置 |
| `/models` | 列出可用模型 |
| `/status` | 显示索引和服务状态 |
| `/clear` | 清除聊天历史 |
| `/quit` | 退出 |

文件监控示例：

```text
/files watch /path/to/directory
/files list
/files stop
```

## 配置项

建议以 `.env.example` 为模板。主要配置如下：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `API_KEY` | — | OpenAI 兼容 API Key |
| `BASE_URL` | `https://api.openai.com/v1` | LLM 端点；远程端点必须使用 HTTPS |
| `LLM_MODEL` | `deepseek-chat` | 回答和查询拆解使用的模型 |
| `LLM_TEMPERATURE` | `0.2` | 生成温度 |
| `LLM_TOP_K_MIN` | `12` | Standard RAG 最少检索 chunk 数 |
| `LLM_TOP_K_MAX` | `70` | Standard RAG 最多检索 chunk 数 |
| `ALPHA` | `0.7` | Graph RAG 语义/图谱融合权重 |
| `RAG_WATCH_DIR` | — | TUI 监控目录 |
| `EMBEDDING_MODEL_PATH` | — | 本地 embedding 模型路径，优先使用 |
| `EMBEDDING_MODEL_NAME` | `all-MiniLM-L6-v2` | 本地/ModelScope 加载使用的模型 ID |
| `MNEME_DOCUMENT_ROOT` | — | 允许建立索引的可选根目录 |
| `MNEME_MAX_DOCUMENT_BYTES` | `52428800` | 单个文档大小上限，50 MiB |
| `MNEME_MAX_PDF_PAGES` | `2000` | 单个 PDF 页数上限 |
| `MNEME_MAX_REMOTE_CONTEXT_CHARS` | `60000` | 发送到 LLM 端点的检索上下文上限 |
| `MNEME_ALLOW_INSECURE_HTTP` | 未设置 | 显式允许非本机 HTTP，仅建议受控开发环境使用 |

Embedding 模型会优先从配置的本地路径或缓存加载；不可用时，ModelScope 回退使用用户配置的模型标识，默认是 `all-MiniLM-L6-v2`。

## 数据与端点安全

索引和检索在本地执行，但在查询拆解、Graph RAG 实体抽取或回答生成时，检索到的文档片段会发送到配置的 API 端点。请使用可信端点，不要索引 API Key、密码或其他敏感信息。

非本机端点默认要求 HTTPS。`localhost`、`127.0.0.1` 和 `::1` 等回环地址允许使用 HTTP。非本机 HTTP 必须显式设置 `MNEME_ALLOW_INSECURE_HTTP=1`。

每个回答上下文都在明确的不可信文档边界中携带来源和引用信息。系统把检索文本当作数据而不是指令；当上下文需要缩短时，会保留完整的来源标注和边界框架。

## 项目结构

```
mneme/
├── src/
│   ├── rag.py                    # Standard RAG 流程与索引
│   ├── graph_rag.py              # Graph RAG 流程与 JSON 缓存
│   ├── rag_query_decomposer.py   # 查询拆解
│   ├── citations.py              # 引用记录与校验
│   ├── index_queue.py            # 串行索引更新与快照
│   ├── metrics.py                # 有界运行指标
│   ├── quality.py                # 检索质量指标与门禁
│   └── security.py               # 端点和文档安全策略
├── tui/                          # Rich 终端 UI 和服务层
├── tests/                        # 单元、集成和 Phase A-D 回归测试
├── benchmarks/                  # 检索质量基准数据
├── plans/                        # 设计和评估文档
└── .github/workflows/            # Windows/Linux CI
```

## 测试

运行默认的离线安全测试套件：

```bash
python -m pytest -q
python -m pip check
python -m compileall -q src tui tests
```

真实外部 LLM 测试标记为 integration，默认跳过。确认 API 配置和费用后再显式运行：

```bash
MNEME_RUN_INTEGRATION=1 python -m pytest -m integration -q
```

## 变更记录

参见 [CHANGELOG.md](./CHANGELOG.md)。
