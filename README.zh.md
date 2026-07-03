# Mneme

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./.github/images/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="./.github/images/logo-light.svg">
    <img alt="Mneme Logo" src="./.github/images/logo-light.svg" width="70%">
  </picture>
</p>

> 以希腊记忆女神 Mnemosyne 命名 —— 一个带终端 UI 的检索增强生成（RAG）系统。

Mneme 是一个双语（中文/英文）RAG 系统，可对本地文档建立索引，并通过大语言模型回答问题。支持 Standard RAG 和 Graph RAG 两种模式。

## 特性

- **混合检索** — 语义搜索（sentence-transformers + ChromaDB）通过 RRF（倒数排名融合）与 BM25 关键词检索融合
- **Graph RAG** — 大语言模型提取的实体关系知识图谱，通过 alpha 加权融合增强语义检索
- **查询拆解** — 将复杂问题拆分为子查询并并发执行
- **锚点块策略** — PDF 首页摘要提升面向元数据查询的召回率（RRF 分数 2x 提升）
- **Rich 终端 UI** — 支持流式响应、斜杠命令、设置管理和文件浏览器的交互式聊天
- **文件监控** — 自动为监控目录中新添加的文件建立索引（基于 watchdog，2 秒防抖）
- **来源标注** — 每个上下文块都标注 `[Source: filename]`，使大语言模型能够回答元问题
- **温度测试** — 系统化评估不同大语言模型温度参数的测试框架

## 支持的文件类型

| 类型 | 扩展名 |
|------|--------|
| PDF | `.pdf` |
| Word | `.docx` |
| Markdown | `.md` |
| 文本 | `.txt` |
| HTML | `.html`, `.htm` |
| 代码 | `.py`, `.js`, `.ts`, `.css`, `.json`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`, `.conf`, `.md` |

## 架构

```
用户输入 → 查询拆解 → 并发混合检索 →
  → 去重 → 动态 Top-K → 上下文增强 →
  → 来源标注 → 大语言模型生成 → 回答 + 来源
```

### 双模式

| 模式 | 检索方式 | 适用场景 |
|------|---------|---------|
| **Standard RAG** | BM25 + ChromaDB + RRF 融合 | 通用问答、广泛文档集 |
| **Graph RAG** | Standard + 实体图谱扩展 + alpha 融合 | 关联性/跨文档知识 |

## 快速开始

### 环境要求

- Python 3.10+
- 一个 OpenAI 兼容的 API 密钥（DeepSeek、OpenAI 等）

### 安装

```bash
git clone https://github.com/HongyiLanDP/mneme.git
cd mneme
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 配置

```bash
cp .env.example .env
```

编辑 `.env`：

```
API_KEY=sk-your-api-key-here
BASE_URL=https://api.deepseek.com/v1
```

### 运行（TUI）

```bash
python -m tui
```

### 运行（CLI）

```bash
python src/rag.py --files /path/to/docs --query "你的问题"
python src/graph_rag.py --files /path/to/docs --query "你的问题"
```

## TUI 使用

### 斜杠命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示所有命令 |
| `/files` | 文件管理（添加/移除/列表/监控） |
| `/mode` | 切换 Standard / Graph RAG 模式 |
| `/alpha` | 设置 Graph RAG alpha 权重 |
| `/settings` | 查看/更改 API 设置 |
| `/models` | 列出可用模型 |
| `/status` | 系统状态概览 |
| `/clear` | 清除聊天历史 |
| `/quit` | 退出 |

### 文件监控

```bash
/files watch /path/to/directory   # 开始监控目录
/files stop                       # 停止监控
/files list                       # 列出已索引文件
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `API_KEY` | — | OpenAI 兼容的 API 密钥 |
| `BASE_URL` | `https://api.openai.com/v1` | API 端点 |
| `LLM_MODEL` | `deepseek-chat` | 模型名称 |
| `LLM_TEMPERATURE` | `0.2` | 生成温度 |
| `LLM_TOP_K_MIN` | `12` | 最小检索块数 |
| `LLM_TOP_K_MAX` | `70` | 最大检索块数 |
| `ALPHA` | `0.7` | Graph RAG 融合权重 |
| `RAG_WATCH_DIR` | — | 自动监控目录（通过 TUI 设置） |

## 项目结构

```
mneme/
├── src/              # 核心 RAG 库
│   ├── rag.py                    # Standard RAG 流水线
│   ├── graph_rag.py              # Graph RAG 流水线
│   └── rag_query_decomposer.py   # 查询拆解
├── tui/              # Rich 终端 UI
│   ├── app.py                    # 编排器
│   ├── service.py                # 服务包装器
│   ├── file_watcher.py           # 目录监控器
│   ├── screens/                  # 首页、聊天、加载
│   ├── components/               # 消息、提示、侧边栏、页脚
│   └── dialogs/                  # 文件管理、状态、帮助
├── tests/            # pytest 测试套件（5 个文件，约 54 个测试）
├── scripts/          # 分析与测试工具
├── plans/            # 设计文档
└── test_texts/       # 示例文档
```

## 测试

```bash
pytest tests/ -v
```

## 更新日志

参见 [CHANGELOG.md](./CHANGELOG.md)。

## 英文版

查看 [README.md](./README.md) 获取英文版本。
