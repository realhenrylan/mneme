from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from tui.theme import THEME


def render_sidebar(stats: dict, mode: str, alpha: float,
                   temperature: float, top_k_range: tuple) -> Panel:
    t = Table(show_header=False, box=None, padding=(0, 1), expand=True)
    t.add_column("key", style=THEME["text_dim"], width=12)
    t.add_column("value", style=THEME["text"])

    t.add_row("[bold " + THEME["accent"] + "]Session[/]", "")
    t.add_row("Mode", mode.upper())
    t.add_row("Collection", stats.get("collection") or "—")

    t.add_row("", "")
    t.add_row("[bold " + THEME["accent"] + "]Index Stats[/]", "")
    t.add_row("Chunks", str(stats.get("chunk_count", 0)))

    if mode == "graph":
        t.add_row("Entities", str(stats.get("entity_count", 0)))
        t.add_row("Relations", str(stats.get("relation_count", 0)))

    files = stats.get("files", [])
    if files:
        t.add_row("Files", "")
        for f in files[:8]:
            t.add_row("", f"  · {f}")
        if len(files) > 8:
            t.add_row("", f"  · ... +{len(files) - 8} more")

    t.add_row("", "")
    t.add_row("[bold " + THEME["accent"] + "]Parameters[/]", "")
    t.add_row("Alpha", f"{alpha:.1f}")
    t.add_row("Top-K", str(top_k_range))
    t.add_row("Temp", f"{temperature:.1f}")

    return Panel(
        t,
        title="[bold " + THEME["accent"] + "]Sidebar[/]",
        border_style=THEME["surface"],
        width=40,
    )
