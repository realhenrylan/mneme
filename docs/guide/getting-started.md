# Getting Started

Mneme indexes local documents and answers questions through an OpenAI-compatible LLM endpoint. It provides Standard RAG and Graph RAG modes, with a bilingual terminal UI and a Python CLI.

## Prerequisites

- Python 3.10 or newer
- An OpenAI-compatible API endpoint and API key (for example, DeepSeek or OpenAI)

## Install

```bash
git clone https://github.com/realhenrylan/mneme.git
cd mneme
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Install the package and development test dependencies:

```bash
python -m pip install -e ".[dev]"
```

## Configure

```bash
copy .env.example .env       # Windows PowerShell
# cp .env.example .env       # macOS / Linux
```

At minimum, set:

```dotenv
API_KEY=sk-your-api-key-here
BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

On first launch, the onboarding wizard can collect and save the API settings. API keys are stored in `.env`; never commit that file or index secrets.

## Run the Terminal UI

```bash
python -m tui
```

The UI supports Standard RAG and Graph RAG, file management, directory watching, settings, source display, and streaming answers.

## Run the CLI

Start an interactive Standard RAG session:

```bash
python -m src.rag --files /path/to/docs --collection my_docs
```

Start an interactive Graph RAG session:

```bash
python -m src.graph_rag --files /path/to/docs --collection my_docs --alpha 0.7
```

Use `--rebuild` when you intentionally want to rebuild the collection. Graph RAG also supports a single query:

```bash
python -m src.graph_rag \
  --files /path/to/docs \
  --query "What are the main findings?"
```

## Next Steps

- [Configuration Reference](/guide/configuration) — all environment variables and their meanings
- [TUI Commands](/guide/tui-commands) — slash commands and shortcuts
- [Hybrid Retrieval](/features/hybrid-retrieval) — how Mneme combines semantic and lexical search
- [Graph RAG](/features/graph-rag) — entity graph construction and retrieval expansion
