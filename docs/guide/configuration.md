# Configuration

Copy `.env.example` as the starting point. The main settings are:

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | — | OpenAI-compatible API key |
| `BASE_URL` | `https://api.openai.com/v1` | LLM endpoint; remote endpoints must use HTTPS |
| `LLM_MODEL` | `deepseek-chat` | Chat and query-decomposition model |
| `LLM_TEMPERATURE` | `0.2` | Generation temperature |
| `LLM_TOP_K_MIN` | `12` | Minimum retrieved chunks for standard retrieval |
| `LLM_TOP_K_MAX` | `70` | Maximum retrieved chunks for standard retrieval |
| `ALPHA` | `0.7` | Graph RAG semantic/graph fusion weight |
| `RAG_WATCH_DIR` | — | Directory watched by the TUI |
| `EMBEDDING_MODEL_PATH` | — | Local embedding model path; takes precedence |
| `EMBEDDING_MODEL_NAME` | `all-MiniLM-L6-v2` | Embedding model ID used for local/ModelScope loading |
| `MNEME_DOCUMENT_ROOT` | — | Optional root directory allowed for indexed files |
| `MNEME_MAX_DOCUMENT_BYTES` | `52428800` | Maximum document size, 50 MiB |
| `MNEME_MAX_PDF_PAGES` | `2000` | Maximum pages accepted from one PDF |
| `MNEME_MAX_REMOTE_CONTEXT_CHARS` | `60000` | Maximum retrieved context sent to an LLM endpoint |
| `MNEME_ALLOW_INSECURE_HTTP` | unset | Explicitly allow non-local HTTP endpoints; use only for controlled development |

## Embedding Model Loading

Embedding models are first loaded from the configured local path or cache. If unavailable, Mneme uses the configured model identifier for ModelScope fallback; the default is `all-MiniLM-L6-v2`.

## Endpoint Safety

For non-local endpoints, HTTPS is required by default. Plain HTTP is allowed for loopback addresses such as `localhost`, `127.0.0.1`, and `::1`. A non-local HTTP endpoint requires the explicit `MNEME_ALLOW_INSECURE_HTTP=1` override.

## Document Safeguards

- Document size, PDF page count, and an optional allowed document root can be limited
- `.env` is explicitly rejected as an indexable document
- Retrieved text is placed inside explicit untrusted-document boundaries for prompt-injection resistance
