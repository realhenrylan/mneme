# Add Files Mid-Session to RAG

## Goal
Allow users to add new files to the `rag.py` index during the interactive chat loop without restarting the program.

## Command Format
Input starting with `+add` followed by file path(s):
```
+add new_doc.pdf
+add doc1.md, doc2.pdf
```
Consistent with existing `q`/`quit` convention. Unambiguous — `+` won't appear as a query start.

## Changes to `rag.py`

### 1. New function `add_files_to_index` (after `build_index`, ~line 279)
```python
def add_files_to_index(
    file_paths: list[str],
    model: SentenceTransformer,
    collection: chromadb.Collection,
) -> tuple[BM25Okapi, list[str], list[dict]]:
```
- Per file: validate path / `..` / `.env` check → `load_document` → chunk → embed → `collection.upsert`
- Re-fetch all data (`collection.get()`), rebuild BM25 via `build_bm25_index`
- Return `(bm25, all_docs, all_metadatas)`

### 2. Modify interactive loop (`__main__`, ~line 537)
Before the answer-query block, add:
```python
if query.startswith("+add "):
    paths = [p.strip() for p in query[5:].replace("，", ",").split(",") if p.strip()]
    if not paths:
        print("用法: +add <文件路径1>[, <文件路径2>]")
        continue
    bm25, all_docs, all_metadatas = add_files_to_index(paths, model, collection)
    print(f"已新增索引，当前共 {len(all_docs)} 个文档块")
    continue
```

## Edge Cases
| Case | Handling |
|------|----------|
| File not found | Skip with message |
| `..` in path | Skip (existing check) |
| `.env` file | Skip (existing check) |
| Unsupported file type | Catch `ValueError` from `load_document`, print, continue |
| Already-indexed file | ChromaDB `upsert` replaces by ID; no duplicates |
| `+add` with no path | Print usage hint (`+add <filepath>`) |
| Chinese comma `，` | Normalize to `,` before split |

## Out of Scope
- `graph_rag.py` (entity graph needs separate update logic)
- Removing files mid-session
- Listing indexed files
- `rag_pipeline()` one-shot function (not interactive)

## Validation
1. Start session with file A: `python rag.py --files A.md`
2. Query about A's content → verified
3. `+add B.pdf` → confirmation printed
4. Query about B's content → B's chunks appear in reference sources
5. `+add` with non-existent path → skip message
6. `+add` same file again → no duplicates in source output
7. `+add` with unsupported type → error message
