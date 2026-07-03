from __future__ import annotations
from tui.keys import COMMANDS


def match_command(text: str) -> str | None:
    if not text.startswith("/"):
        return None
    parts = text.split()
    cmd = parts[0].lower()
    if cmd in COMMANDS:
        return cmd
    matches = [c for c in COMMANDS if c.startswith(cmd)]
    if len(matches) == 1:
        return matches[0]
    return None
