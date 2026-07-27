---
layout: home

hero:
  name: Mneme
  text: 本地文档 RAG 与 Graph RAG
  tagline: 以 Mnemosyne——希腊神话中的记忆女神——命名，一个带有终端 UI 的本地文档检索增强生成系统。
  image:
    src: /tui-screenshot.png
    alt: Mneme TUI 预览
  actions:
    - theme: brand
      text: 快速开始
      link: /zh/guide/getting-started
    - theme: alt
      text: GitHub
      link: https://github.com/realhenrylan/mneme

features:
  - icon: 🔍
    title: 混合检索
    details: Sentence-transformers + ChromaDB 语义搜索与 BM25 关键词搜索通过 RRF（倒数排名融合）结合，兼顾语义和词法两个世界。
    link: /zh/features/hybrid-retrieval
  - icon: 🕸️
    title: Graph RAG
    details: LLM 提取的实体关系扩展检索，支持跨文档关联问题。共现阈值保持图谱清洁。
    link: /zh/features/graph-rag
  - icon: 🧩
    title: 查询拆解
    details: 复杂问题被拆分为子查询并发检索，然后融合为单一综合回答。
    link: /zh/features/query-decomposition
  - icon: 🛡️
    title: 安全设计
    details: 默认 HTTPS 端点、有界文档大小、显式不可信文档边界和 Schema 验证的 JSON 缓存。
    link: /zh/features/safety
  - icon: 💻
    title: 终端 UI
    details: 基于 Rich 的双语 TUI，支持流式聊天、斜杠命令、文件管理、设置和防抖目录监听。
    link: /zh/guide/tui-commands
  - icon: 📄
    title: 广泛格式支持
    details: PDF、DOCX、Markdown、HTML、JSON、CSV、源代码和配置文件。本地索引，可验证引用查询。
    link: /zh/reference/supported-files
---

## 快速预览

```bash
# 克隆并安装
git clone https://github.com/realhenrylan/mneme.git
cd mneme
python -m venv .venv
.venv\Scripts\Activate.ps1  # Windows
# source .venv/bin/activate  # macOS / Linux
python -m pip install -e ".[dev]"

# 配置
copy .env.example .env
# 编辑 .env 填入你的 API_KEY 和 BASE_URL

# 启动 TUI
python -m tui
```

了解更多请阅读[快速开始指南](/zh/guide/getting-started)。
