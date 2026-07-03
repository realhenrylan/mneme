import os
from rich.text import Text
from tui.theme import THEME


def render_footer(mode: str, chunk_count: int, api_ok: bool) -> Text:
    text = Text()
    cwd = os.getcwd()
    text.append(f" {cwd}", style=THEME["text_dim"])
    text.append("    ")
    text.append("Ctrl+C quit", style=THEME["text_dim"])
    text.append("    ")
    if api_ok:
        text.append("●", style=THEME["success"])
    else:
        text.append("●", style=THEME["error"])
    text.append(" API", style=THEME["text_dim"])
    text.append("    ")
    text.append(f"{mode}  {chunk_count} chunks", style=THEME["text_dim"])
    return text
