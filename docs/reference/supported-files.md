# Supported File Types

Mneme can index and retrieve from the following file types:

| Type | Extensions |
|------|-----------|
| PDF | `.pdf` |
| Word | `.docx` |
| Text and Markdown | `.txt`, `.md`, `.markdown`, `.log` |
| Web and data | `.html`, `.htm`, `.json`, `.csv`, `.xml`, `.yaml`, `.yml` |
| Configuration | `.toml`, `.cfg`, `.ini`, `.conf` |
| Source code | `.py`, `.js`, `.ts`, `.css`, `.sql`, `.sh`, `.bat` |

## PDF Handling

Mneme uses **PyMuPDF** (`fitz`) as the primary PDF parser, with **pdfplumber** as a fallback. This dual-strategy ensures robust text extraction across different PDF generation methods.

- Word spacing is preserved to prevent concatenation issues (e.g., `UniversityofPennsylvania`)
- The first 5 lines of each PDF are used as an "anchor chunk" to boost retrieval relevance
- Maximum page count is enforced via `MNEME_MAX_PDF_PAGES`

## Security Note

The following are **explicitly rejected** from indexing:
- `.env` files (to prevent API key exposure)
- Paths containing `..` (directory traversal protection)

## Document Limits

| Limit | Default | Control Variable |
|-------|---------|------------------|
| Max file size | 50 MiB | `MNEME_MAX_DOCUMENT_BYTES` |
| Max PDF pages | 2000 | `MNEME_MAX_PDF_PAGES` |
| Allowed root | Optional | `MNEME_DOCUMENT_ROOT` |

Files exceeding these limits are skipped during indexing with a clear log message.
