# TUI Commands

Mneme's Rich-based terminal UI supports slash commands and keyboard shortcuts.

## Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/files` | Add, remove, list, watch, or stop watching files |
| `/mode` | Toggle Standard RAG / Graph RAG |
| `/alpha` | Set the Graph RAG fusion weight |
| `/settings` | View or change API settings |
| `/models` | List available models |
| `/status` | Show index and service status |
| `/clear` | Clear chat history |
| `/quit` | Exit |

## File Management Examples

```text
/files watch /path/to/directory
/files list
/files stop
/files add /path/to/file.pdf
/files remove /path/to/file.pdf
```

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+P` | Open command palette |
| `Ctrl+L` | Toggle sidebar |
| `Ctrl+N` | New session |
| `Ctrl+K` | Clear chat |
| `Ctrl+C` | Exit |

## Mode Switching

Use `/mode` to switch between Standard RAG and Graph RAG. When switching to Graph RAG from Standard, Mneme will:

1. Show a confirmation prompt
2. Build the knowledge graph from the current index (with a progress bar)
3. Switch the retrieval mode

When switching back to Standard RAG, the mode changes immediately without rebuilding.

## Settings

Use `/settings` to view and modify:
- API Key (masked for security)
- Base URL
- LLM Model
- Temperature
- Top-K Min / Max
- Alpha (Graph RAG weight)

All changes are persisted to `.env` and take effect immediately.
