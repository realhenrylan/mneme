# Configuration Reference

Mneme is configured through environment variables in a `.env` file.

## Core LLM Settings

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_KEY` | Yes | — | OpenAI-compatible API key |
| `BASE_URL` | Yes | `https://api.openai.com/v1` | LLM endpoint URL |
| `LLM_MODEL` | Yes | `deepseek-chat` | Chat completion model |
| `LLM_TEMPERATURE` | No | `0.2` | Sampling temperature (0.0–2.0) |

## Retrieval Settings

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_TOP_K_MIN` | No | `12` | Minimum chunks retrieved |
| `LLM_TOP_K_MAX` | No | `70` | Maximum chunks retrieved |
| `ALPHA` | No | `0.7` | Graph RAG fusion weight (0.0–1.0) |

## Embedding Model

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `EMBEDDING_MODEL_PATH` | No | — | Local path to a pre-downloaded model |
| `EMBEDDING_MODEL_NAME` | No | `all-MiniLM-L6-v2` | Model ID for ModelScope fallback |

If `EMBEDDING_MODEL_PATH` is set, Mneme loads from that path. Otherwise it tries the local cache, then falls back to ModelScope auto-download.

## File Watching

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RAG_WATCH_DIR` | No | — | Directory to watch for file changes |

## Safety Limits

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MNEME_DOCUMENT_ROOT` | No | — | Restrict indexing to this directory tree |
| `MNEME_MAX_DOCUMENT_BYTES` | No | `52428800` | Max file size (50 MiB) |
| `MNEME_MAX_PDF_PAGES` | No | `2000` | Max PDF pages per file |
| `MNEME_MAX_REMOTE_CONTEXT_CHARS` | No | `60000` | Max context sent to LLM endpoint |
| `MNEME_ALLOW_INSECURE_HTTP` | No | unset | Set to `1` to allow non-local HTTP |

## Example `.env`

```dotenv
# Required
API_KEY=sk-your-api-key-here
BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# Optional
LLM_TEMPERATURE=0.2
LLM_TOP_K_MIN=12
LLM_TOP_K_MAX=70
ALPHA=0.7

# Embedding
EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2

# Watching
RAG_WATCH_DIR=/path/to/docs

# Safety
MNEME_MAX_DOCUMENT_BYTES=52428800
MNEME_MAX_PDF_PAGES=2000
```

## Provider Quick Reference

| Provider | `BASE_URL` | `LLM_MODEL` |
|----------|-----------|-------------|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat`, `deepseek-reasoner` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o`, `gpt-4o-mini`, `gpt-3.5-turbo` |
| Custom | Your URL | Your model |
