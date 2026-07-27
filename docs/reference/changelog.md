# Changelog

See the full changelog on GitHub: [CHANGELOG.md](https://github.com/realhenrylan/mneme/blob/main/CHANGELOG.md)

## Highlights

### Unreleased

- **Embedding Model Auto-Download**: Fallback to ModelScope for `all-MiniLM-L6-v2` when local cache is unavailable (China network-friendly)
- **CLI Loop Refactor**: Extracted shared interactive session logic from `rag.py` and `graph_rag.py` into `src/cli_loop.py`
- **Import Cleanup**: Eliminated `sys.path` hacks and circular imports; added `pyproject.toml` for editable installs
- **LLM Client Singleton**: Module-level lazy initialization to reduce `OpenAI` client creation overhead
- **Logo Refresh**: Transparent SVG wordmark rebuilt from original glyphs

### 1.1.0 (2026-07-04)

- **Onboarding Wizard**: First-launch setup wizard for API key, provider, base URL, and model selection
- **Provider & Model Linkage**: DeepSeek, OpenAI, and custom provider presets with available model lists

### 1.0.3 (2026-07-04)

- Fixed error scenes incorrectly displaying Sources alongside error messages

### 1.0.2 (2026-07-04)

- Fixed Temperature, Alpha, Top-K Min/Max settings lost after restart

### 1.0.1 (2026-07-03)

- Fixed thread-unsafe `_entity_cache` writes and incorrect per-chunk API calls in Graph RAG batch processing

### 1.0.0 (2026-07-03)

- Initial release with TUI, hybrid retrieval, Graph RAG, query decomposition, and comprehensive test suite

---

For the complete version history with all changes, fixes, and refactor details, visit the [GitHub repository](https://github.com/realhenrylan/mneme/blob/main/CHANGELOG.md).
