import os
from dotenv import get_key, set_key  # Issue #1b 修复：.env 解析器脆弱性
from typing import Optional, List
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
import questionary
from questionary import Style as QStyle

from tui.theme import THEME
from tui.components.message import user_message, assistant_message, source_reference, error_panel, warning_panel
from tui.components.prompt import match_command
from tui.components.sidebar import render_sidebar
from tui.keys import COMMANDS

_SUPPORTED_EXTENSIONS = (
    ".pdf", ".docx",
    ".txt", ".md", ".markdown", ".html", ".htm",
    ".json", ".csv", ".xml", ".yaml", ".yml",
    ".toml", ".cfg", ".ini", ".conf", ".log",
    ".py", ".js", ".ts", ".css", ".sql",
    ".sh", ".bat",
)


def _list_supported_files(directory: str = ".") -> List[str]:
    """Return sorted list of files in directory with supported extensions."""
    try:
        entries = os.listdir(directory)
    except OSError:
        return []
    files = sorted(
        f for f in entries
        if os.path.isfile(os.path.join(directory, f))
        and os.path.splitext(f)[1].lower() in _SUPPORTED_EXTENSIONS
    )
    return files


def _api_ok() -> bool:
    """Check whether .env has API_KEY configured (ignoring spaces around =)."""
    if not os.path.isfile(".env"):
        return False
    with open(".env") as f:
        for line in f:
            key, sep, val = line.strip().partition("=")
            if key.strip() == "API_KEY" and val.strip():
                return True
    return False


def _command_bar(service, mode: str = "", alpha: Optional[float] = None) -> str:
    parts = "  ".join(f"[bold {THEME['accent']}]{cmd}[/]" for cmd in COMMANDS)
    extras = []
    dot = THEME["success"] if _api_ok() else THEME["error"]
    extras.append(f"[{dot}]●[/]")
    if mode:
        extras.append(f"[{THEME['text_dim']}]Mode:[/] [bold]{mode.upper()}[/]")
    if service:
        cc = service.get_stats().get("chunk_count", 0)
        if cc:
            extras.append(f"[{THEME['text_dim']}]Chunks:[/] [bold]{cc}[/]")
    if mode == "graph" and alpha is not None:
        extras.append(f"[{THEME['text_dim']}]Alpha:[/] [bold]{alpha:.1f}[/]")
    base = f"[{THEME['text_dim']}]Commands:[/] {parts}"
    if extras:
        base += f"  [{THEME['text_dim']}]┃[/]  " + "  ".join(extras)
    return base


def run_chat_loop(console: Console, service, mode: str, alpha: float,
                  temperature: float, top_k_range: tuple):
    history: list[tuple[str, str]] = []

    console.print(f"[{THEME['success']}]Ready.[/]")
    console.print(_command_bar(service, mode))
    console.print()

    while True:
        try:
            user_input = console.input(
                f"[bold {THEME['accent']}]>[/] "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            console.print(f"\n[{THEME['text_dim']}]Bye![/]")
            break

        if user_input == "\x0c":
            console.clear()
            console.print(_command_bar(service, mode))
            console.print()
            continue

        if not user_input:
            continue

        if user_input.startswith("/"):
            cmd = match_command(user_input)
            if cmd is None:
                console.print(warning_panel("Unknown command.", "Command"))
                continue
            if cmd == "/quit":
                console.print(f"[{THEME['text_dim']}]Bye![/]")
                break
            if cmd == "/clear":
                history.clear()
                console.print(f"[{THEME['success']}]History cleared.[/]")
                continue
            if cmd == "/help":
                _show_help(console)
                continue
            if cmd == "/status":
                stats = service.get_stats()
                console.print()
                console.print(render_sidebar(stats, mode, alpha, temperature, top_k_range))
                console.print()
                continue
            if cmd == "/mode":
                mode = _toggle_mode(console, mode, service)
                continue
            if cmd == "/alpha":
                alpha = _set_alpha(console, alpha)
                continue
            if cmd == "/files":
                _manage_files(console, service)
                continue
            if cmd == "/settings":
                result = _configure_settings(console, alpha, temperature, top_k_range[0], top_k_range[1])
                if result:
                    alpha, temperature, top_k_range = result
                continue
            if cmd == "/models":
                _switch_model(console)
                continue
            continue

        history.append((user_input, ""))

        full_text = ""
        try:
            label = "Graph RAG" if mode == "graph" else "Standard RAG"
            with console.status(
                f"[bold {THEME['accent']}]{label} thinking...[/]",
                spinner="dots",
            ):
                if mode == "graph":
                    stream, sources = service.graph_query(
                        user_input, history[:-1],
                        alpha=alpha, temperature=temperature,
                        top_k_range=top_k_range,
                    )
                else:
                    stream, sources = service.query(
                        user_input, history[:-1],
                        temperature=temperature, top_k_range=top_k_range,
                    )
                for chunk in stream:
                    full_text += chunk
        except Exception as e:
            console.print(error_panel(f"Query failed: {e}"))
            history.pop()
            continue

        history[-1] = (user_input, full_text)

        console.print(user_message(user_input))
        console.print(assistant_message(full_text))
        if sources.strip():
            console.print(source_reference(sources))
        console.print(_command_bar(service, mode, alpha))
        console.print()

    return


def _show_help(console: Console):
    console.print()
    console.print(Panel(
        "\n".join(f"  [bold {THEME['accent']}]{cmd}[/]  {desc}" for cmd, desc in COMMANDS.items()),
        title="[bold " + THEME["accent"] + "]Help[/]",
        border_style=THEME["surface"],
    ))
    console.print()


def _show_status(console: Console, service, mode: str):
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
    console.print()
    console.print(Panel(
        "\n".join(lines),
        title="[bold " + THEME["accent"] + "]Status[/]",
        border_style=THEME["surface"],
    ))
    console.print()


def _toggle_mode(console: Console, mode: str, service) -> str:
    new_mode = "graph" if mode == "standard" else "standard"

    # ── Graph → Standard：直接切换，无需确认 ──
    if new_mode == "standard":
        service.set_mode("standard")
        console.print(f"[{THEME['success']}]Mode → STANDARD[/]")
        return "standard"

    # ── Standard → Graph：需先构建知识图谱 ──
    stats = service.get_stats()
    files = stats.get("files", [])
    collection = stats.get("collection", "rag_demo")

    if not files:
        console.print(warning_panel("No files indexed. Add files first.", "Knowledge Graph"))
        return mode

    if not Confirm.ask(
        f"  [{THEME['text_dim']}]Build knowledge graph for {len(files)} file(s)?[/]",
        default=True,
        console=console,
    ):
        return mode

    try:
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

        def _progress_cb(done, total):
            progress.update(progress_bar, completed=done, total=total,
                            description=f"[{THEME['accent']}]Processing chunks... ({done}/{total})[/]")

        with Progress(
            SpinnerColumn(spinner_name="dots", style=THEME["accent"]),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=None),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            progress_bar = progress.add_task(
                f"[{THEME['accent']}]Building knowledge graph...[/]",
                total=None,
            )
            service.build_kg_from_chromadb(collection, progress_callback=_progress_cb)

        service.set_mode("graph")
        console.print(f"[{THEME['success']}]Knowledge graph ready![/]")
        console.print(f"[{THEME['success']}]Mode → GRAPH[/]")
        return "graph"

    except Exception as e:
        console.print(error_panel(f"Graph build failed: {e}"))
        return mode


def _set_alpha(console: Console, alpha: float) -> float:
    from rich.prompt import FloatPrompt
    new_alpha = FloatPrompt.ask(
        f"  [{THEME['text_dim']}]Alpha (0.0-1.0)[/]",
        default=alpha,
        console=console,
    )
    new_alpha = max(0.0, min(1.0, new_alpha))
    console.print(f"[{THEME['success']}]Alpha → {new_alpha:.1f}[/]")
    return new_alpha


def _manage_files(console: Console, service):
    console.print()
    while True:
        action = Prompt.ask(
            f"  [{THEME['text_dim']}]Action[/]",
            choices=["add", "remove", "list", "exit"],
            default="list",
            console=console,
        )
        if action == "exit":
            break
        if action == "list":
            stats = service.get_stats()
            files = stats.get("files", [])
            if files:
                for f in files:
                    console.print(f"    · {f}")
            else:
                console.print(f"  [{THEME['text_dim']}]No files indexed.[/]")
        elif action == "add":
            while True:
                directory = questionary.path(
                    "Directory to scan (Tab to autocomplete):",
                    only_directories=True,
                    style=_QS,
                ).ask()
                if not directory:
                    break
                directory = os.path.abspath(os.path.expanduser(directory))
                files = _list_supported_files(directory)
                if not files:
                    console.print(warning_panel(f"No supported files in {directory}", "Files"))
                    continue
                selected = questionary.checkbox(
                    f"Select file(s) from {directory}:",
                    choices=files,
                    style=_QS,
                ).ask()
                if not selected:
                    continue
                paths = [os.path.join(directory, f) for f in selected]
                service.add_files(paths)
                console.print(f"[{THEME['success']}]Added {len(paths)} file(s).[/]")
                more = questionary.select(
                    "Add more files?",
                    choices=["No", "Yes"],
                    style=_QS,
                ).ask()
                if more != "Yes":
                    break
        elif action == "remove":
            while True:
                stats = service.get_stats()
                files = stats.get("files", [])
                if not files:
                    console.print(warning_panel("No files to remove.", "Files"))
                    break
                choices = [questionary.Choice(f, f) for f in files]
                choices.append(questionary.Choice("← Back", "__back__"))
                name = questionary.select(
                    "Select file to remove:",
                    choices=choices,
                    style=_QS,
                ).ask()
                if name == "__back__":
                    break
                count = service.remove_file(name)
                console.print(f"[{THEME['success']}]Removed {count} chunks.[/]")
    console.print()


def _read_env(key: str) -> str:
    """Read a single value from .env file using python-dotenv."""
    return get_key(".env", key) or ""


def _write_env(key: str, value: str) -> None:
    """Update or append a key=value in .env file using python-dotenv."""
    set_key(".env", key, value)  # quote_mode 默认 "always"


def _mask_api_key(key: Optional[str]) -> str:
    """掩码显示 API Key，仅保留 'sk-' 前缀和最后 4 位。"""
    if not key:
        return "<not set>"
    if len(key) <= 8:
        return "sk-...****"
    return f"{key[:3]}...{key[-4:]}"   # key[:3] = "sk-"


_QS = QStyle([
    ("qmark", f"fg:{THEME['accent']} bold"),
    ("question", f"fg:{THEME['text']}"),
    ("answer", f"fg:{THEME['accent']} bold"),
    ("pointer", f"fg:{THEME['accent']} bold"),
    ("highlighted", f"fg:{THEME['accent']} bold"),
    ("selected", f"fg:{THEME['text']}"),
    ("text", f"fg:{THEME['text_dim']}"),
    ("instruction", f"fg:{THEME['text_dim']} italic"),
])


def _configure_settings(console: Console, alpha: float = 0.7,
                         temperature: float = 0.1,
                         top_k_min: int = 3, top_k_max: int = 20):
    """Interactive settings menu with arrow-key navigation."""
    cur_alpha = alpha
    cur_temp = temperature
    cur_tk_min = top_k_min
    cur_tk_max = top_k_max

    while True:
        console.clear()
        api_key_display = _mask_api_key(_read_env("API_KEY"))
        base_url_display = _mask_api_key(_read_env("BASE_URL"))

        choices = [
            questionary.Choice(
                f"1. API Key          {api_key_display}", "api_key"),
            questionary.Choice(
                f"2. Base URL         {base_url_display}", "base_url"),
            questionary.Choice(
                f"3. LLM Model        {os.environ.get('LLM_MODEL', 'deepseek-chat')}", "llm_model"),
            questionary.Choice(
                f"4. Temperature      {cur_temp}", "temperature"),
            questionary.Choice(
                f"5. Top-K Min        {cur_tk_min}", "top_k_min"),
            questionary.Choice(
                f"6. Top-K Max        {cur_tk_max}", "top_k_max"),
            questionary.Choice(
                f"7. Alpha            {cur_alpha}", "alpha"),
            questionary.Choice("", None),
            questionary.Choice("q. Exit settings", "exit"),
        ]
        choice = questionary.select(
            "Settings (↑↓ navigate, Enter edit):",
            choices=choices,
            qmark=">",
            style=_QS,
        ).ask()

        if choice is None or choice == "exit":
            break

        if choice == "api_key":
            current = _read_env("API_KEY")
            val = questionary.text("API Key:", default=current, style=_QS).ask()
            if val and val != current:
                _write_env("API_KEY", val); os.environ["API_KEY"] = val
        elif choice == "base_url":
            current = _read_env("BASE_URL")
            val = questionary.text("Base URL:", default=current, style=_QS).ask()
            if val and val != current:
                _write_env("BASE_URL", val); os.environ["BASE_URL"] = val
        elif choice == "llm_model":
            cur = os.environ.get("LLM_MODEL", "deepseek-chat")
            val = questionary.text("LLM Model:", default=cur, style=_QS).ask()
            if val and val != cur:
                _write_env("LLM_MODEL", val); os.environ["LLM_MODEL"] = val
        elif choice == "temperature":
            val = questionary.text("Temperature (0.0-1.0):", default=str(cur_temp), style=_QS).ask()
            if val:
                try:
                    v = max(0.0, min(1.0, float(val)))
                    cur_temp = v
                    _write_env("LLM_TEMPERATURE", str(v))
                    os.environ["LLM_TEMPERATURE"] = str(v)
                except ValueError:
                    pass
        elif choice == "top_k_min":
            val = questionary.text("Top-K Min:", default=str(cur_tk_min), style=_QS).ask()
            if val:
                try:
                    v = max(1, int(val))
                    if v <= cur_tk_max:
                        cur_tk_min = v
                        _write_env("LLM_TOP_K_MIN", str(v))
                        os.environ["LLM_TOP_K_MIN"] = str(v)
                except ValueError:
                    pass
        elif choice == "top_k_max":
            val = questionary.text("Top-K Max:", default=str(cur_tk_max), style=_QS).ask()
            if val:
                try:
                    v = int(val)
                    if v >= cur_tk_min:
                        cur_tk_max = v
                        _write_env("LLM_TOP_K_MAX", str(v))
                        os.environ["LLM_TOP_K_MAX"] = str(v)
                except ValueError:
                    pass
        elif choice == "alpha":
            val = questionary.text("Alpha (0.0-1.0):", default=str(cur_alpha), style=_QS).ask()
            if val:
                try:
                    v = max(0.0, min(1.0, float(val)))
                    cur_alpha = v
                    _write_env("ALPHA", str(v))
                    os.environ["ALPHA"] = str(v)
                except ValueError:
                    pass

    changed = (cur_alpha != alpha or cur_temp != temperature
               or cur_tk_min != top_k_min or cur_tk_max != top_k_max)
    if changed:
        return (cur_alpha, cur_temp, (cur_tk_min, cur_tk_max))
    return None


def _switch_model(console: Console):
    current = os.environ.get("LLM_MODEL", "deepseek-chat")
    console.print()
    model = Prompt.ask(
        f"  [{THEME['text_dim']}]Current model[/] [{THEME['accent']}]({current})[/]",
        console=console,
    ).strip()
    if model and model != current:
        _write_env("LLM_MODEL", model)
        os.environ["LLM_MODEL"] = model
        console.print(f"[{THEME['success']}]Model → {model}[/]")
    console.print()
