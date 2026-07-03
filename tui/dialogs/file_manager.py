import os
import questionary
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from tui.theme import THEME
from tui.components.message import warning_panel

_QS = questionary.Style([
    ("qmark", f"fg:{THEME['accent']}"),
    ("question", f"fg:{THEME['text']} bold"),
    ("answer", f"fg:{THEME['accent']} bold"),
    ("pointer", f"fg:{THEME['accent']} bold"),
    ("highlighted", f"fg:{THEME['accent']} bold"),
    ("selected", f"fg:{THEME['accent']}"),
    ("text", f"fg:{THEME['text_dim']}"),
    ("instruction", f"fg:{THEME['text_dim']} italic"),
])


def manage_files(console: Console, service):
    console.print()
    action = Prompt.ask(
        f"  [{THEME['text_dim']}]Action[/]",
        choices=["add", "remove", "list"],
        default="list",
        console=console,
    )
    if action == "list":
        stats = service.get_stats()
        files = stats.get("files", [])
        if files:
            for f in files:
                console.print(f"    · {f}")
        else:
            console.print(f"  [{THEME['text_dim']}]No files indexed.[/]")
    elif action == "add":
        paths_input = Prompt.ask(
            f"  [{THEME['text_dim']}]Files to add (comma-separated)[/]",
            console=console,
        ).strip()
        paths = [p.strip() for p in paths_input.replace("，", ",").split(",") if p.strip()]
        valid = [p for p in paths if os.path.exists(p)]
        if valid:
            service.add_files(valid)
            console.print(f"[{THEME['success']}]Added {len(valid)} file(s).[/]")
        else:
            console.print(warning_panel("No valid paths.", "Files"))
    elif action == "remove":
        stats = service.get_stats()
        files = stats.get("files", [])
        if not files:
            console.print(warning_panel("No files to remove.", "Files"))
        else:
            choices = [questionary.Choice(f, f) for f in files]
            name = questionary.select(
                "Select file to remove:",
                choices=choices,
                style=_QS,
            ).ask()
            if name:
                count = service.remove_file(name)
                console.print(f"[{THEME['success']}]Removed {count} chunks.[/]")
    console.print()
