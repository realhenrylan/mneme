# Graph RAG

When a question spans documents, people, organizations, or concepts, increasing Top-K usually adds noise. Mneme's Graph RAG pipeline uses entity relationships to expand retrieval selectively.

## Pipeline Stages

1. **Entity Extraction**: Ask the LLM to extract entities from chunks in batches
2. **Chunk Mapping**: Preserve the mapping from entities to chunks
3. **Co-occurrence Counting**: Count entity co-occurrences across chunks
4. **Edge Filtering**: Filter accidental relationships with:
   - `min_cooccur` threshold (default: 2) — two entities must co-occur in at least N chunks
   - `max_entities_per_chunk` cap (default: 20) — only top N entities per chunk participate in edge construction
5. **Query Expansion**: Extract query entities and expand one hop through the graph
6. **Alpha Fusion**: Fuse graph candidates with standard hybrid-retrieval results using `alpha` weight

## Why Constraints Matter

An early fully connected subgraph could create many weak edges for a chunk containing many entities. The graph looked rich but retrieved noisily.

Mneme now:
- Preserves the complete entity-to-chunk mapping
- Uses co-occurrence thresholds for edge construction
- Caps per-chunk entities to prevent combinatorial explosion

"Where did an entity occur?" and "Which entities deserve an edge?" are separate decisions.

## Fallback

If the graph is empty, Graph RAG falls back to standard semantic/hybrid retrieval instead of making an empty graph block the pipeline.

## Client Refresh

Entity extraction follows the current model and endpoint configuration. When API key or Base URL changes during a long-lived TUI session, the Graph RAG client refreshes with the configuration fingerprint.

## CLI Usage

```bash
# Interactive Graph RAG session
python -m src.graph_rag --files /path/to/docs --collection my_docs --alpha 0.7

# Single query
python -m src.graph_rag \
  --files /path/to/docs \
  --query "What are the main findings?"
```

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--alpha` | `0.7` | Fusion weight between standard retrieval and graph expansion |
| `--rebuild` | `False` | Force rebuild the collection and graph |

## Best For

Graph RAG is best for connected or cross-document questions — queries that span multiple files, involve relationships between entities, or require understanding of how concepts connect across your knowledge base.
