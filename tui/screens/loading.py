from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table
from tui.theme import THEME
from tui.components.message import error_panel


def render_loading(console: Console, service, files: list[str],
                   collection: str, mode: str) -> bool:
    console.print(f"[bold {THEME['accent']}]─── Building Index ───[/]\n")

    file_count = len(files)
    stats = None
    try:
        with Progress(
            SpinnerColumn(spinner_name="dots", style=THEME["accent"]),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=None),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            task = progress.add_task(
                f"[{THEME['accent']}]Processing files...  (0/{file_count})[/]",
                total=file_count,
            )

            def _progress_cb(current, total):
                if total == file_count:
                    progress.update(task, completed=current,
                        description=f"[{THEME['accent']}]Processing files...  ({current}/{total})[/]")
                else:
                    progress.update(task, total=total, completed=current,
                        description=f"[{THEME['accent']}]Building knowledge graph...  ({current}/{total})[/]")

            stats = service.prepare_index(
                files, collection, mode=mode,
                progress_callback=_progress_cb,
            )
    except Exception as e:
        console.print(error_panel(f"Index build failed: {e}"))
        return False

    console.print(f"\n[{THEME['success']}]✓ Index ready![/]")
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column("label", style=THEME["text_dim"], width=10)
    t.add_column("value", style=THEME["text"])
    t.add_row("Files", str(file_count))
    t.add_row("Chunks", str(stats.get("chunk_count", 0)))
    if mode == "graph":
        t.add_row("Entities", str(stats.get("entity_count", 0)))
        t.add_row("Relations", str(stats.get("relation_count", 0)))
    console.print(Panel(t, border_style=THEME["surface"], padding=(0, 1)))
    console.print()
    return True
