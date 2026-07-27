# Hybrid Retrieval

Pure vector retrieval is good at semantic similarity, but it is not always reliable for filenames, abbreviations, numbers, proper nouns, or exact phrases. Pure BM25 can miss a useful paraphrase. Mneme keeps both retrieval signals.

## Architecture

```
User question
  → query decomposition
  → concurrent hybrid retrieval / Graph RAG expansion
  → chunk deduplication and dynamic Top-K
  → PDF anchor enrichment
  → cited, bounded untrusted-document context
  → LLM answer + verifiable sources
```

## Components

### Semantic Search

- **Sentence Transformers** produce embeddings
- **ChromaDB** provides semantic retrieval with cosine similarity
- Default model: `all-MiniLM-L6-v2` (auto-downloaded from ModelScope if not cached)

### Lexical Search

- **BM25** provides keyword-based retrieval
- Custom tokenization supports bilingual text, case folding, and punctuation stripping
- Incremental BM25 tokenization reuse for unchanged chunks on index updates

### RRF Fusion

RRF (Reciprocal Rank Fusion) combines the ranked lists instead of comparing incompatible raw scores:

```
RRF score = Σ 1 / (k + rank)
```

RRF is simple and explainable. It does not require semantic distances and BM25 scores to share the same scale.

### Dynamic Top-K

After fusion, Mneme selects a dynamic Top-K from score gaps:
- A clear gap becomes a natural cutoff
- Configured lower (`LLM_TOP_K_MIN`) and upper (`LLM_TOP_K_MAX`) bounds still apply when the gap is not decisive

## Retrieval Quality

This design leaves retrieval quality measurable. Recall@k, MRR, and nDCG can be used as regression signals instead of relying on the impression that an answer "feels better." The repository includes benchmark data and quality-gate helpers under `benchmarks/`.

## Best For

Standard RAG (hybrid retrieval) is best for general Q&A and broad document sets. For connected or cross-document questions, use [Graph RAG](/features/graph-rag).
