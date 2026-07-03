# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-07-03

### Added

- Initial release of RAG system with TUI
- Core RAG pipeline with hybrid retrieval (BM25 + ChromaDB vector search)
- Graph RAG mode with knowledge graph construction
- Query decomposition for complex questions
- Hierarchical document enrichment (anchor chunk strategy)
- Rich-based terminal UI with interactive settings
- PDF, DOCX, Markdown, and text file support
- Temperature testing framework for model evaluation
- Comprehensive test suite with unit and integration tests

### Security

#### [#1] - API Key Protection & .env Parser Fix (2026-07-03)

**#1a: API Key Exposure Prevention**
- Added `_mask_api_key()` to mask API keys in TUI (displays `sk-...xxxx` format)
- API keys no longer displayed in plaintext in settings interface
- `.env` file protected by `.gitignore` (not tracked in git history)

**#1b: .env Parser Hardening**
- Replaced fragile custom `_read_env`/`_write_env` with `python-dotenv` standard API
- Fixed handling of values containing `=`, `#`, quotes, and newlines
- Automatic quoting via `set_key()` prevents malformed `.env` entries
- Added 21 unit tests covering all edge cases

**Files Changed:**
- `tui/screens/chat.py`: Refactored env parsing, added masking
- `tests/test_env_security.py`: 21 new tests (all passing)
- `.env.example`: Added template file

### Changed

- `_toggle_mode()` in TUI now shows progress bar during knowledge graph construction
- Graph RAG knowledge graph files saved to `chroma_db/` directory

### Fixed

- [#1] Custom `.env` parser failed on values with `=`, `#`, quotes, or newlines
- [#1] `_mask_api_key` prefix calculation corrected (`key[:3]` = `"sk-"`)

---

## [Unreleased]

### Planned

- Cross-encoder reranking for improved retrieval quality
- Query intent routing for complex multi-part questions
- Multi-language query expansion
- Persistent configuration with validation
