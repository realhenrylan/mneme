from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text
from rich.spinner import Spinner
from tui.theme import THEME


def user_message(text: str) -> Panel:
    return Panel(
        text,
        border_style=THEME["user_border"],
        title="[bold " + THEME["user_border"] + "]User[/]",
        padding=(0, 1),
    )


def assistant_message(text: str) -> Panel:
    return Panel(
        Markdown(text),
        border_style=THEME["assistant_border"],
        title="[bold " + THEME["assistant_border"] + "]Assistant[/]",
        padding=(0, 1),
    )


def source_reference(sources: str) -> Panel:
    return Panel(
        sources,
        border_style=THEME["source_border"],
        title="[bold " + THEME["source_border"] + "]Sources[/]",
        padding=(0, 1),
    )


def thinking_message(status: str = "Thinking...") -> Panel:
    spinner = Spinner("dots", style=THEME["accent"])
    text = Text()
    text.append_text(spinner.render(None))
    text.append(f" {status}", style=THEME["text_dim"])
    return Panel(
        text,
        border_style=THEME["assistant_border"],
        title="[bold " + THEME["assistant_border"] + "]Assistant[/]",
        padding=(0, 1),
    )


def error_panel(message: str, title: str = "Error") -> Panel:
    return Panel(
        f"[{THEME['error']}]✗ {message}[/]",
        border_style=THEME["error"],
        title=f"[bold {THEME['error']}]{title}[/]",
        padding=(0, 1),
    )


def warning_panel(message: str, title: str = "Warning") -> Panel:
    return Panel(
        f"[{THEME['warning']}]⚠ {message}[/]",
        border_style=THEME["warning"],
        title=f"[bold {THEME['warning']}]{title}[/]",
        padding=(0, 1),
    )
