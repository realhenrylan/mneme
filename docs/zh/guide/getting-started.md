# 快速开始

Mneme 索引本地文档并通过 OpenAI 兼容的 LLM 端点回答问题。它提供 Standard RAG 和 Graph RAG 两种模式，带有双语终端 UI 和 Python CLI。

## 前提条件

- Python 3.10 或更新版本
- 一个 OpenAI 兼容的 API 端点和 API Key（例如 DeepSeek 或 OpenAI）

## 安装

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

安装包和开发测试依赖：

```bash
python -m pip install -e ".[dev]"
```

## 配置

```bash
copy .env.example .env       # Windows PowerShell
# cp .env.example .env       # macOS / Linux
```

至少设置以下内容：

```dotenv
API_KEY=sk-your-api-key-here
BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

首次启动时，引导向导可以收集并保存 API 设置。API Key 存储在 `.env` 中；切勿提交该文件或索引其中的密钥。

## 运行终端 UI

```bash
python -m tui
```

UI 支持 Standard RAG 和 Graph RAG、文件管理、目录监听、设置、来源展示和流式回答。

## 运行 CLI

启动交互式 Standard RAG 会话：

```bash
python -m src.rag --files /path/to/docs --collection my_docs
```

启动交互式 Graph RAG 会话：

```bash
python -m src.graph_rag --files /path/to/docs --collection my_docs --alpha 0.7
```

当你有意重建 collection 时使用 `--rebuild`。Graph RAG 也支持单次查询：

```bash
python -m src.graph_rag \
  --files /path/to/docs \
  --query "主要发现是什么？"
```

## 下一步

- [配置参考](/zh/guide/configuration) — 所有环境变量及其含义
- [TUI 命令](/zh/guide/tui-commands) — 斜杠命令和快捷键
- [混合检索](/zh/features/hybrid-retrieval) — Mneme 如何结合语义和词法搜索
- [Graph RAG](/zh/features/graph-rag) — 实体图构建和检索扩展
