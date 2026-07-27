# Safety by Design

Mneme centralizes policy in `src/security.py`, so the CLI, TUI, query decomposer, and Graph RAG share the same checks.

## Endpoint Security

- **HTTPS by default**: Remote endpoints require HTTPS; loopback addresses (`localhost`, `127.0.0.1`, `::1`) may use HTTP
- **Explicit override**: Non-local HTTP requires the explicit `MNEME_ALLOW_INSECURE_HTTP=1` override
- **Client refresh**: Graph RAG caches are bound to the current API key and base URL so endpoint changes take effect immediately

## Document Safeguards

| Control | Default | Purpose |
|---------|---------|---------|
| Document size limit | 50 MiB (`52428800`) | Prevents accidental indexing of huge files |
| PDF page limit | 2000 pages | Caps extraction time and memory |
| Document root | Optional (`MNEME_DOCUMENT_ROOT`) | Restricts indexing to a specific directory tree |
| `.env` rejection | Always | Prevents API keys from being indexed |

## Context Boundaries

Retrieved text is placed inside an explicit untrusted-document boundary:

```text
[Source: report.pdf] [Citation: S1]
<untrusted_document chunk_id="source-a_chunk_3">
Retrieved text ...
</untrusted_document>
```

The model is instructed to treat that section as data, not as instructions. Even if a document contains text such as "ignore previous instructions," it remains inside the untrusted-document region.

### Context Truncation Safety

Context length is bounded (default: 60,000 characters). Mneme truncates only `document_text`, preserving the complete source marker, citation, and opening/closing boundary. A chunk is skipped when the complete safety frame cannot fit. A safety boundary is not the first thing sacrificed under a tight budget.

## Cache Safety

- Graph RAG caches use **schema-validated atomic JSON** rather than loading pickle
- A cache must match the current index fingerprint and manifest version
- Legacy `.pkl` files are invalidated without being loaded

## Data Disclosure

Indexing and retrieval run locally, but retrieved document snippets are sent to the configured endpoint when Mneme performs query decomposition, Graph RAG entity extraction, or answer generation. The onboarding wizard discloses this explicitly.
