from rich.console import Console
from rich.panel import Panel
from tui.theme import THEME
from tui.keys import COMMANDS


def show_help(console: Console):
    lines = []
    for cmd, desc in COMMANDS.items():
        lines.append(f"  [bold {THEME['accent']}]{cmd}[/]  {desc}")
    console.print(Panel(
        "\n".join(lines),
        title="[bold " + THEME["accent"] + "]Help[/]",
        border_style=THEME["surface"],
    ))
