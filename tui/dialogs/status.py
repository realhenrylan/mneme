from rich.console import Console
from rich.panel import Panel
from tui.theme import THEME


def show_status(console: Console, service, mode: str):
    stats = service.get_stats()
    lines = [
        f"  Mode:       {mode.upper()}",
        f"  Collection: {stats.get('collection', '—')}",
        f"  Chunks:     {stats.get('chunk_count', 0)}",
    ]
    if mode == "graph":
        lines.append(f"  Entities:   {stats.get('entity_count', 0)}")
        lines.append(f"  Relations:  {stats.get('relation_count', 0)}")
    files = stats.get("files", [])
    if files:
        lines.append(f"  Files ({len(files)}):")
        for f in files[:10]:
            lines.append(f"    · {f}")
        if len(files) > 10:
            lines.append(f"    · ... +{len(files) - 10} more")
    console.print(Panel(
        "\n".join(lines),
        title="[bold " + THEME["accent"] + "]Status[/]",
        border_style=THEME["surface"],
    ))
