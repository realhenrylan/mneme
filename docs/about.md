# About Mneme

Mneme is a local-document Retrieval-Augmented Generation (RAG) system named after **Mnemosyne**, the Greek goddess of memory in Greek mythology.

## Project Goal

Turn a local document collection into a verifiable, queryable memory. Every answer should be traceable to a specific file, page, and chunk.

## What Mneme Is

- A **Python CLI** for one-shot and batch document Q&A
- A **bilingual terminal UI** (TUI) for interactive sessions with file watching
- A **hybrid retrieval engine** combining semantic search (ChromaDB + Sentence Transformers) and lexical search (BM25)
- A **Graph RAG** mode for cross-document relationship queries
- A **safety-first** system with explicit data boundaries, endpoint validation, and resource limits

## What Mneme Is Not

- Not a cloud service — all indexing happens locally
- Not a guarantee that data never leaves your machine — retrieved snippets are sent to your configured LLM endpoint
- Not a replacement for reading the original documents — it augments reading with fast retrieval and summarization

## Architecture Principles

1. **Identity first** — stable `source_id`, `chunk_id`, and content hashes prevent index drift
2. **Versioned mutations** — atomic manifest updates keep vector store, BM25, and graph cache aligned
3. **Explicit boundaries** — untrusted-document tags separate retrieved text from system instructions
4. **Measurable quality** — benchmark utilities for Recall@k, MRR, nDCG, and quality gates
5. **Offline-safe tests** — CI runs without API keys; integration tests are opt-in

## License

[MIT License](https://github.com/realhenrylan/mneme/blob/main/LICENSE)

## Author

Built by [Henry Lan](https://github.com/realhenrylan).

## Links

- [GitHub Repository](https://github.com/realhenrylan/mneme)
- [Issues & Discussions](https://github.com/realhenrylan/mneme/issues)
- [Homepage](/)
