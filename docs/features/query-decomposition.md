# Query Decomposition

Complex questions are split into sub-queries and retrieved concurrently, then the results are fused into a single comprehensive answer.

## Why Decompose?

A question like "Compare the findings of the 2023 and 2024 reports on renewable energy" requires:
1. Finding the 2023 report's findings
2. Finding the 2024 report's findings
3. Comparing them

A single retrieval query would likely miss one of the reports or dilute the relevance signal. Decomposition ensures each sub-question gets its own focused retrieval.

## How It Works

1. **Analysis**: The LLM analyzes the original question and breaks it into atomic sub-queries
2. **Concurrent Retrieval**: Each sub-query is dispatched to the retrieval pipeline in parallel via `ThreadPoolExecutor`
3. **Result Fusion**: Results from all sub-queries are deduplicated by chunk and scored
4. **Context Assembly**: A single combined context is built and sent to the LLM for the final answer

## Performance

- Sub-queries run concurrently, so total latency is close to the slowest individual query rather than the sum
- Chunk deduplication prevents the same document from being counted multiple times
- Dynamic Top-K is applied to the fused result set

## Integration

Query decomposition is automatically used in both:
- **Standard RAG** pipeline (`answer_query`)
- **Graph RAG** pipeline (`graph_rag_pipeline`)

There is no separate user-facing switch; Mneme decides whether a query is complex enough to benefit from decomposition based on its structure.
