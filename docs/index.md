---
layout: home

hero:
  name: Mneme
  text: Local-document RAG with Graph RAG
  tagline: Named after Mnemosyne, the Greek goddess of memory — a local-document Retrieval-Augmented Generation system with a terminal UI.
  image:
    src: /tui-screenshot.png
    alt: Mneme TUI Preview
  actions:
    - theme: brand
      text: Get Started
      link: /guide/getting-started
    - theme: alt
      text: View on GitHub
      link: https://github.com/realhenrylan/mneme

features:
  - icon: 🔍
    title: Hybrid Retrieval
    details: Sentence-transformers + ChromaDB semantic search fused with BM25 keyword search using RRF (Reciprocal Rank Fusion). Best of both semantic and lexical worlds.
    link: /features/hybrid-retrieval
  - icon: 🕸️
    title: Graph RAG
    details: LLM-extracted entity relationships expand retrieval for connected, cross-document questions. Co-occurrence thresholds keep the graph clean.
    link: /features/graph-rag
  - icon: 🧩
    title: Query Decomposition
    details: Complex questions are split into sub-queries and retrieved concurrently, then fused into a single comprehensive answer.
    link: /features/query-decomposition
  - icon: 🛡️
    title: Safety by Design
    details: HTTPS-by-default endpoints, bounded document sizes, explicit untrusted-document boundaries, and schema-validated JSON caches.
    link: /features/safety
  - icon: 💻
    title: Terminal UI
    details: Rich-based bilingual TUI with streaming chat, slash commands, file management, settings, and debounced directory watching.
    link: /guide/tui-commands
  - icon: 📄
    title: Wide Format Support
    details: PDF, DOCX, Markdown, HTML, JSON, CSV, source code, and configuration files. Index locally, query with verifiable citations.
    link: /reference/supported-files
---

## Quick Preview

```bash
# Clone and install
git clone https://github.com/realhenrylan/mneme.git
cd mneme
python -m venv .venv
.venv\Scripts\Activate.ps1  # Windows
# source .venv/bin/activate  # macOS / Linux
python -m pip install -e ".[dev]"

# Configure
copy .env.example .env
# Edit .env with your API_KEY and BASE_URL

# Launch the TUI
python -m tui
```

Learn more in the [Getting Started guide](/guide/getting-started).
