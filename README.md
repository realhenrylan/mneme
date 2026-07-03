# Mneme

> Named after Mnemosyne, the Greek goddess of memory — a Retrieval-Augmented Generation system with a terminal UI.

Mneme is a bilingual (Chinese/English) RAG system that indexes local documents and answers questions via an LLM. It supports Standard RAG and Graph RAG modes.

## Features

- **Hybrid Retrieval** — Semantic search (sentence-transformers + ChromaDB) fused with BM25 keyword search via RRF (Reciprocal Rank Fusion)
- **Graph RAG** — LLM-extracted entity-relationship knowledge graph augments semantic retrieval with alpha-weighted fusion
- **Query Decomposition** — Complex questions are split into sub-queries and executed concurrently
- **Anchor Chunk Strategy** — PDF first-page summaries boost metadata-oriented query recall (2x RRF score)
- **Rich Terminal UI** — Interactive chat with streaming responses, slash commands, settings management, and file browser
- **File Watcher** — Auto-index newly added files from a watched directory (watchdog-based, 2s debounce)
- **Source Annotation** — Every context chunk is labeled with `[Source: filename]` so the LLM can answer meta-questions
- **Temperature Testing** — Framework for systematic LLM temperature evaluation across test question sets

## Supported File Types

| Type | Extensions |
|------|-----------|
| PDF | `.pdf` |
| Word | `.docx` |
| Markdown | `.md` |
| Text | `.txt` |
| HTML | `.html`, `.htm` |
| Code | `.py`, `.js`, `.ts`, `.css`, `.json`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`, `.conf`, `.md` |

## Architecture

```
User Input → Query Decomposition → Concurrent Hybrid Retrieval →
  → Deduplication → Dynamic Top-K → Context Enrichment →
  → Source Annotation → LLM Generation → Answer + Sources
```

### Dual Mode

| Mode | Retrieval | Best For |
|------|-----------|----------|
| **Standard RAG** | BM25 + ChromaDB + RRF fusion | General Q&A, broad document sets |
| **Graph RAG** | Standard + entity graph expansion + alpha fusion | Connected/cross-document knowledge |

## Quick Start

### Prerequisites

- Python 3.10+
- An OpenAI-compatible API key (DeepSeek, OpenAI, etc.)

### Install

```bash
git clone <repo-url>
cd mneme
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
```

Edit `.env`:

```
API_KEY=sk-your-api-key-here
BASE_URL=https://api.deepseek.com/v1
```

### Run (TUI)

```bash
python -m tui
```

### Run (CLI)

```bash
python src/rag.py --files /path/to/docs --query "your question"
python src/graph_rag.py --files /path/to/docs --query "your question"
```

## TUI Usage

### Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/files` | File management (add/remove/list/watch) |
| `/mode` | Toggle Standard / Graph RAG |
| `/alpha` | Set Graph RAG alpha weight |
| `/settings` | View/change API settings |
| `/models` | List available models |
| `/status` | System status overview |
| `/clear` | Clear chat history |
| `/quit` | Exit |

### File Watcher

```bash
/files watch /path/to/directory   # Start watching a directory
/files stop                       # Stop watching
/files list                       # List indexed files
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | — | OpenAI-compatible API key |
| `BASE_URL` | `https://api.openai.com/v1` | API endpoint |
| `LLM_MODEL` | `deepseek-chat` | Model name |
| `LLM_TEMPERATURE` | `0.2` | Generation temperature |
| `LLM_TOP_K_MIN` | `12` | Minimum retrieved chunks |
| `LLM_TOP_K_MAX` | `70` | Maximum retrieved chunks |
| `ALPHA` | `0.7` | Graph RAG fusion weight |
| `RAG_WATCH_DIR` | — | Auto-watch directory (set via TUI) |

## Project Structure

```
mneme/
├── src/              # Core RAG library
│   ├── rag.py                    # Standard RAG pipeline
│   ├── graph_rag.py              # Graph RAG pipeline
│   └── rag_query_decomposer.py   # Query decomposition
├── tui/              # Rich Terminal UI
│   ├── app.py                    # Orchestrator
│   ├── service.py                # Service wrapper
│   ├── file_watcher.py           # Directory watcher
│   ├── screens/                  # Home, Chat, Loading
│   ├── components/               # Message, Prompt, Sidebar, Footer
│   └── dialogs/                  # File manager, Status, Help
├── tests/            # pytest test suites (5 files, ~54 tests)
├── scripts/          # Analysis & testing tools
├── plans/            # Design documents
└── test_texts/       # Sample documents
```

## Testing

```bash
pytest tests/ -v
```

## Changelog

See [CHANGELOG.md](./CHANGELOG.md).
