---
title: "Turning Local Documents into Verifiable Memory: Engineering RAG and Graph RAG in Mneme"
description: "How Mneme turns a local-document Q&A prototype into a maintainable RAG system through hybrid retrieval, index consistency, evidence boundaries, and explicit security controls."
date: 2026-07-23
tags:
  - Python
  - RAG
  - Graph RAG
  - ChromaDB
  - TUI
lang: en-US
slug: mneme-rag-engineering-en
---

# Turning Local Documents into Verifiable Memory: Engineering RAG and Graph RAG in Mneme

Many RAG projects start with a short pipeline: split documents into chunks, generate embeddings, retrieve a few passages, and ask an LLM to answer. That is enough to get a demo running. It is not enough to make the system dependable. The harder questions are more basic: what happens when a file changes? Can two files with the same name remain distinct? Can an answer be traced back to a page and a chunk? What stops an instruction inside a document from being treated as a system instruction?

Mneme is a local-document RAG system built around those questions. It is named after Mnemosyne, the Greek goddess of memory, and provides a Python CLI, a bilingual terminal UI, and two retrieval modes: Standard RAG and Graph RAG. This post focuses on the engineering decisions behind the project rather than repeating a feature list.

## 1. Start with the complete data path

Mneme’s core path looks like this:

```text
Local files
  → path normalization, type and resource validation
  → document splitting with stable identities
  → ChromaDB semantic index + BM25 lexical index
  → RRF fusion and dynamic Top-K
  → PDF anchor enrichment / Graph RAG expansion
  → bounded context with sources and safety boundaries
  → LLM answer with verifiable citations
```

The important design choice is that indexing, retrieval, context construction, and answer generation are not independent features. They share the same source identity and version model, and the final answer must be able to point back to a file, page, and chunk.

Mneme supports PDF, DOCX, Markdown, HTML, JSON, CSV, XML, YAML, common configuration files, and several source-code formats. Indexing happens locally, but retrieved passages are sent to the configured OpenAI-compatible endpoint when Mneme performs query decomposition, Graph RAG entity extraction, or answer generation. “Local indexing” therefore does not mean that data can never leave the machine; that boundary has to be explicit.

## 2. Why hybrid retrieval

Pure vector retrieval is good at semantic similarity, but it is not always reliable for filenames, abbreviations, numbers, proper nouns, or exact phrases. Pure BM25 can miss a useful paraphrase. Mneme keeps both retrieval signals:

- Sentence Transformers produce embeddings, with ChromaDB providing semantic retrieval;
- BM25 provides lexical retrieval and reuses tokenization for unchanged chunks;
- RRF (Reciprocal Rank Fusion) combines the ranked lists instead of comparing incompatible raw scores.

RRF is simple and explainable. It does not require semantic distances and BM25 scores to share the same scale. After fusion, Mneme selects a dynamic Top-K from score gaps: a clear gap becomes a natural cutoff, while configured lower and upper bounds still apply when the gap is not decisive.

This design also leaves retrieval quality measurable. Recall@k, MRR, and nDCG can be used as regression signals instead of relying on the impression that an answer “feels better.” The repository includes benchmark data and quality-gate helpers, so chunking, embedding, and fusion changes can be evaluated systematically.

## 3. Graph RAG is for relationships, not just a larger Top-K

When a question spans documents, people, organizations, or concepts, increasing Top-K usually adds noise. Mneme’s Graph RAG pipeline works in stages:

1. Ask the LLM to extract entities from chunks in batches.
2. Preserve the mapping from entities to chunks.
3. Count entity co-occurrences across chunks.
4. Filter accidental relationships with a minimum co-occurrence threshold and cap the number of entities that participate in edge construction per chunk.
5. Extract query entities and expand one hop through the graph.
6. Fuse graph candidates with the standard hybrid-retrieval results using `alpha`.

The constraints matter. An early fully connected subgraph could create many weak edges for a chunk containing many entities. The graph looked rich but retrieved noisily. Mneme now preserves the complete entity-to-chunk mapping while using co-occurrence thresholds and a per-chunk entity cap for edge construction. “Where did an entity occur?” and “Which entities deserve an edge?” are separate decisions.

If the graph is empty, Graph RAG falls back to standard semantic/hybrid retrieval instead of making an empty graph block the pipeline. Entity extraction also follows the current model and endpoint configuration; when API key or Base URL changes during a long-lived TUI session, the Graph RAG client refreshes with the configuration fingerprint.

## 4. The most underestimated RAG problem: index consistency

The most dangerous vector-store bug is often not low recall. It is retrieving content that should no longer exist. Mneme does not use a basename or the document body as the unique identity. It uses a shared identity model:

- a normalized absolute path is used to derive `source_id`;
- the file content is tracked with SHA-256;
- every chunk has a stable `chunk_id`;
- every collection has a versioned manifest;
- ChromaDB, BM25 snapshots, Graph RAG caches, and citation records use the same identity model.

That supports several awkward but common cases: two directories can contain `report.pdf` with identical text and still remain separate; changing one file replaces only its own chunks; deleting a file deletes the exact source rather than every file with the same basename; and a failed update rolls the collection, manifest, and BM25 snapshot back together.

An index update is therefore more than one `upsert`. A source mutation has to keep vector data, lexical retrieval, the manifest, graph cache, and query snapshots aligned. Treating the mutation as one recoverable unit prevents a half-successful state such as “the vector store is new, but the manifest is old.”

## 5. Citations are part of the context protocol

Mneme creates query-local citation IDs such as `S1` and `S2`. A citation record includes the source path, display name, PDF page, and chunk ID, so `[S1]` in an answer can be traced to a concrete piece of evidence.

More importantly, retrieved text is placed inside an explicit untrusted-document boundary:

```text
[Source: report.pdf] [Citation: S1]
<untrusted_document chunk_id="source-a_chunk_3">
Retrieved text ...
</untrusted_document>
```

The model is instructed to treat that section as data, not as instructions. Even if a document contains text such as “ignore previous instructions,” it should remain inside the untrusted-document region.

Context length is bounded; the default cap is 60,000 characters sent to the remote endpoint. The implementation cannot simply truncate the entire serialized string. If only an opening tag remains, the protocol boundary is incomplete. Mneme truncates only `document_text`, preserves the complete source marker, citation, and opening/closing boundary, and skips a chunk when the complete safety frame cannot fit. A safety boundary should not be the first thing sacrificed under a tight budget.

## 6. Security has to cover files, endpoints, and caches

Mneme centralizes policy in the lightweight `src/security.py`, so the CLI, TUI, query decomposer, and Graph RAG share the same checks:

- remote endpoints require HTTPS by default; loopback addresses such as `localhost`, `127.0.0.1`, and `::1` may use HTTP;
- non-local HTTP requires the explicit `MNEME_ALLOW_INSECURE_HTTP=1` override;
- document size, PDF page count, and an optional allowed document root can be limited;
- `.env` is explicitly rejected as an indexable document;
- Graph RAG caches use schema-validated atomic JSON rather than loading pickle;
- a cache must match the current index fingerprint and manifest version.

These controls protect different layers. Endpoint validation protects transport, resource limits control accidental large inputs, path restrictions control the data scope, JSON avoids executable deserialization in the knowledge base, and manifest versions prevent an old graph from being attached to a new index.

## 7. The TUI makes background updates predictable

The CLI is useful for scripts and one-shot queries. Mneme’s Rich TUI is designed for longer sessions: streaming answers, file management, settings, source display, Standard RAG / Graph RAG switching, and directory watching.

The watcher debounces file events. Actual add, modify, delete, and rebuild operations go through a single-worker `IndexQueue`. Queries do not read lists that are being mutated; they use an immutable snapshot containing the collection, BM25 index, documents, metadata, and manifest version selected for that query. This prevents one request from observing a new BM25 index, an old document list, and a graph from yet another version.

The tradeoff is slightly less write concurrency in exchange for a state model that is easier to reason about. For a personal knowledge base and small-to-medium document collections, “no half-applied update, no silent failure, stable query versions” is often more valuable than maximizing write parallelism.

## 8. Test the boundaries, not only the happy path

The test suite covers more than whether one document can produce an answer. It also checks:

- whether same-name paths and duplicate text keep independent identities;
- whether modify, delete, and failed upsert operations roll the manifest back correctly;
- whether the Graph JSON schema, size, fingerprint, and version are validated;
- whether low-evidence retrieval refuses before calling the LLM;
- whether citations, PDF pages, and untrusted-document boundaries remain complete;
- whether the index queue is serialized and snapshots are isolated from later mutations;
- whether cleanup works across Windows and Linux, and real external LLM tests are explicitly enabled through `MNEME_RUN_INTEGRATION=1`.

The default suite stays offline-safe. Tests that require an external service are opt-in. That keeps local development and CI independent of personal API credentials while turning security behavior into stable regression tests.

## Conclusion: reliable RAG keeps uncertainty inside explicit boundaries

The main lesson from Mneme is that RAG quality is not determined by the retrieval model alone. It is determined jointly by identity, versioning, evidence, and security boundaries.

Hybrid retrieval improves useful recall. Graph RAG connects cross-document relationships. The manifest keeps the index aligned with changing files. Citations and untrusted-document boundaries make answers traceable. Endpoint and resource policies control the data flow. Queues and snapshots keep a long-running TUI consistent.

Mneme is still a local-first personal knowledge-base tool, not a guarantee that sensitive data can never leave the machine. Sensitive documents still require a trusted LLM endpoint or a controlled local service. That is exactly why the data boundary belongs in the architecture, not only in the README: it is one of the most durable engineering practices in the project.

See [README.md](./README.md) for the project entry point and setup instructions.
