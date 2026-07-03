# Plan: Auto-Watch Directory for File Ingestion

## Principle
- KISS: Keep all codes simple and stupid. Leave space for imporovement.

## Goal
Replace the TUI `/files` → `add` interactive flow with an automatic directory watcher.
When a user drops/copies files into a designated watch directory via the file manager,
the system detects new files, slices them, and indexes them automatically without manual `/add`.

## Background
Currently `/files` → `add` opens an interactive prompt (`questionary.path` + `questionary.checkbox`)
to let the user manually select files. The user wants this replaced by a passive watcher:
- User sets a watch directory via `/files watch <dir>`
- Files placed into that directory are auto-ingested
- Files removed from that directory are auto-deleted from the index

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Watch-dir persistence | `.env` key `RAG_WATCH_DIR` | Survives restarts, simple, no new config format |
| Delete sync | Yes | Symmetric with "drop in → add", "remove → delete" |
| Watch scope | Single-level (`recursive=False`) | Lower complexity; recursive can be added later |
| Duplicate guard | Filename + path match against existing `source` metadata | Aligns with existing `remove_file_from_index` logic |
| Debounce | 2 s after last `created`/`moved` event | Avoids indexing partially-written files |
| Supported events | `created`, `moved` (into dir), `deleted` | Covers copy, move, and delete operations |
| Thread safety | `threading.Lock` around `add_files`/`remove_file` | Prevents race conditions between watcher thread and query thread |
| Dotfile/temp filter | Yes, ignore `.*`, `~*`, `Thumbs.db` | Avoids indexing system/temp files |
| Interactive add | Retain `/files add <path>` | One-off ingest for files outside the watch directory |

## Affected Files

1. `requirements.txt` — `watchdog>=3.0.0` already present (no-op)
2. `tui/file_watcher.py` — **new module**
3. `tui/service.py` — add watch-dir state, lifecycle methods, thread-safe mutations
4. `tui/screens/chat.py` — rewrite `/files` command UI
5. `tui/app.py` — defer watcher start until after index is ready

## Implementation Steps

### Step 1: Dependency (no-op)
`watchdog>=3.0.0` is already in `requirements.txt`.

### Step 2: Extract shared constant `_SUPPORTED_EXTENSIONS`
Create `tui/constants.py` (or `src/constants.py`) and move `_SUPPORTED_EXTENSIONS` from `chat.py` and `home.py` into it.
- `tui/screens/chat.py` line 16 and `tui/screens/home.py` line 30 both define the same tuple.
- `tui/file_watcher.py` will import from this shared location.

### Step 3: Create `tui/file_watcher.py`
Implement a `FileWatcher` class using `watchdog.observers.Observer` and `watchdog.events.FileSystemEventHandler`.

Responsibilities:
- Accept a `watch_dir` and callbacks `on_new_file(path)` / `on_removed_file(path)`
- Register handlers for `on_created`, `on_moved`, `on_deleted`
- **Event semantics:**
  - `on_created`: a new file appears in the watch dir (covers copy, move-in, new file)
  - `on_moved`: a file is renamed **within** the watch dir; check if `dest_path` is still inside `watch_dir`
  - `on_deleted`: a file is deleted or moved out of the watch dir
- Debounce: when a `created`/`moved` event fires, start/restart a 2-second timer; only call `on_new_file` when the timer expires without new events for that path
- Filter by supported extensions (import from shared constant)
- **Filter dotfiles/temp files:** ignore files starting with `.`, `~`, or named `Thumbs.db`
- Track already-processed paths to avoid duplicate ingestion
- Provide `start()` and `stop()` methods

### Step 4: Extend `tui/service.py`
Add to `LocalRagService`:
- `_watch_dir: str | None = None`
- `_watcher: FileWatcher | None = None`
- `_lock: threading.Lock` — protects `add_files` and `remove_file`
- `set_watch_dir(dir: str) -> None`
- `get_watch_dir() -> str | None`
- `start_watching() -> None`
- `stop_watching() -> None`
- `_on_new_file(path: str) -> None` — calls `self.add_files([path])`
- `_on_removed_file(path: str) -> None` — calls `self.remove_file(os.path.basename(path))`, then **refreshes state**:
  ```python
  all_data = self._collection.get()
  self._docs = all_data["documents"]
  self._metadatas = all_data["metadatas"]
  self._bm25 = build_bm25_index(self._docs)
  ```

On `set_watch_dir`:
1. Stop any existing watcher
2. Persist the path to `.env` (`RAG_WATCH_DIR`)
3. **Do NOT start the watcher here** — defer to `app.py` after index is ready

**Thread safety:** Wrap `add_files` and `remove_file` bodies with `self._lock`.

**Graph mode incremental update (optional but recommended):**
Instead of rebuilding the entire KG on every `add_files`, consider:
- Extract only the new chunks added by `add_files_to_index`
- Call `kg.add_chunks(new_chunks)` (if `KnowledgeGraph` supports incremental add)
- If not supported, document that graph mode will trigger a full KG rebuild on each file addition

### Step 5: Rewrite `/files` in `tui/screens/chat.py`
Replace the current `_manage_files` function.

New `/files` behavior:
- **No arguments** — show current watch directory and indexed file list
- `/files watch <dir>` — set watch directory (calls `service.set_watch_dir(dir)`)
- `/files stop` — stop watching (calls `service.stop_watching()`)
- `/files list` — list indexed files
- `/files remove <filename>` — remove a file from the index
- `/files add <path>` — one-off ingest for files outside the watch directory (retains old interactive flow or accepts a direct path)

### Step 6: Update `tui/app.py`
In `RagApp.run()`:
- After `render_loading()` returns successfully (index is ready), check `.env` for `RAG_WATCH_DIR`
- If present and valid, call `self.service.set_watch_dir(...)` to start watching
- On app exit, call `self.service.stop_watching()`

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| File copy triggers multiple `created` events | 2-second debounce timer per path |
| Large file ingestion blocks UI | Run `add_files` in a background thread; show a spinner in the TUI |
| `watchdog` not installed | Already in `requirements.txt`; document `pip install -r requirements.txt` |
| Watch directory deleted while watching | Catch `OSError` in `FileWatcher`; stop gracefully |
| Same file added twice (e.g. renamed) | Track processed paths in `FileWatcher`; skip if already seen in this session |
| Stale state after removal | `remove_file` refreshes `self._docs`, `self._metadatas`, `self._bm25` from ChromaDB |
| Watcher starts before index ready | Defer `set_watch_dir` until after `render_loading()` succeeds |
| Race conditions between threads | `threading.Lock` around `add_files`/`remove_file` |
| Full KG rebuild on every add (graph mode) | Document as known limitation; incremental KG update is out of scope |

## Validation

1. Run TUI, execute `/files watch /tmp/test-watch`
2. Copy a PDF into `/tmp/test-watch`
3. Verify: TUI shows "Indexing..." then "Added 1 file(s)"
4. Query the system; answer should reference the new file
5. Delete the PDF from `/tmp/test-watch`
6. Verify: TUI shows "Removed X chunks"
7. Query the system again; the deleted file's content should no longer appear
8. Restart TUI; verify it auto-starts watching `/tmp/test-watch` (from `.env`)
9. Delete the watch directory while TUI is running; verify graceful handling
10. Copy a `.DS_Store` file into `/tmp/test-watch`; verify it is ignored

## Open Questions

- Should recursive watching be supported in a future iteration? (Out of scope for now)
- Should `KnowledgeGraph` support incremental `add_chunks` to avoid full rebuilds? (Out of scope for now)
