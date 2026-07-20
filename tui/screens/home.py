import os
import chromadb
import questionary
from questionary import Style as QStyle
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from tui.theme import THEME
from tui.logo import LOGO
from tui.keys import COMMANDS
from tui.components.message import error_panel, warning_panel

from src.rag import CHROMA_DB_PATH, SUPPORTED_EXTENSIONS as _SUPPORTED_EXTENSIONS, _collection_exists


_QS = QStyle([
    ("qmark", f"fg:{THEME['accent']}"),
    ("question", f"fg:{THEME['text']} bold"),
    ("answer", f"fg:{THEME['accent']} bold"),
    ("pointer", f"fg:{THEME['accent']} bold"),
    ("highlighted", f"fg:{THEME['accent']} bold"),
    ("selected", f"fg:{THEME['accent']}"),
    ("text", f"fg:{THEME['text_dim']}"),
    ("instruction", f"fg:{THEME['text_dim']} italic"),
])


def _list_supported_files(directory: str) -> list[str]:
    try:
        entries = os.listdir(directory)
    except OSError:
        return []
    return sorted(
        f for f in entries
        if os.path.isfile(os.path.join(directory, f))
        and os.path.splitext(f)[1].lower() in _SUPPORTED_EXTENSIONS
    )


def render_home(console: Console) -> dict:
    console.clear()
    console.print(Panel(LOGO, border_style=THEME["accent"], expand=False))
    console.print(
        f"[bold {THEME['accent']}]  Mneme — Knowledge-Augmented Q&A System[/]\n",
    )

    mode_choices = {"1": "standard", "2": "graph"}
    console.print(f"  [{THEME['text_dim']}]Select RAG mode:[/]")
    console.print(f"    [bold {THEME['accent']}]1[/]  Standard RAG")
    console.print(f"    [bold {THEME['accent']}]2[/]  Graph RAG\n")

    while True:
        choice = Prompt.ask(
            f"  [{THEME['text_dim']}]Mode[/]",
            choices=["1", "2"],
            default="1",
            console=console,
        )
        mode = mode_choices[choice]
        break

    # Ask collection name first so we can check if it already exists
    console.print()
    default_name = "graph_rag" if mode == "graph" else "rag_demo"
    collection = Prompt.ask(
        f"  [{THEME['text_dim']}]Collection name[/]",
        default=default_name,
        console=console,
    ).strip()
    collection = collection or default_name

    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    try:
        exists = _collection_exists(client, collection)
    finally:
        client.close()

    console.print()
    if not exists:
        valid_paths = []
        directory = questionary.path(
            "Directory to scan (Tab to autocomplete):",
            only_directories=True,
            style=_QS,
        ).ask()
        if directory:
            directory = os.path.abspath(os.path.expanduser(directory))
            files = _list_supported_files(directory)
            if files:
                selected = questionary.checkbox(
                    f"Select file(s) from {directory}:",
                    choices=files,
                    style=_QS,
                ).ask()
                if selected:
                    valid_paths = [os.path.join(directory, f) for f in selected]
        if not valid_paths:
            console.print(error_panel("No valid files. Exiting."))
            return None
    else:
        console.print(
            f"  [{THEME['text_dim']}]Existing collection [bold]{collection}[/] found, reusing index. "
            f"Use [bold]/files[/] to add more files later.[/]"
        )
        valid_paths = []

    # ── 命令速览 ──
    cmd_table = Table(show_header=False, box=None, padding=(0, 2))
    cmd_table.add_column("cmd", no_wrap=True)
    cmd_table.add_column("desc")
    for cmd, desc in COMMANDS.items():
        cmd_table.add_row(
            f"[bold {THEME['accent']}]{cmd}[/]",
            f"[{THEME['text_dim']}]{desc}[/]",
        )
    console.print()
    console.print(Panel(
        cmd_table,
        title=f"[bold {THEME['accent']}]Slash Commands[/]",
        border_style=THEME["surface"],
        padding=(0, 1),
    ))
    console.print(
        f"  [{THEME['text_dim']}]Keyboard: Ctrl+L clear  |  Ctrl+C quit[/]"
    )
    console.print()

    if not Confirm.ask(
        f"  [{THEME['text_dim']}]Start building index?[/]",
        default=True,
        console=console,
    ):
        return None

    return {
        "files": valid_paths,
        "mode": mode,
        "collection": collection,
    }
