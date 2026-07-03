import os
import sys
from dotenv import get_key
from rich.console import Console
from tui.theme import THEME
from tui.service import LocalRagService
from tui.components.message import error_panel
from tui.screens.home import render_home
from tui.screens.loading import render_loading
from tui.screens.chat import run_chat_loop


class RagApp:
    def __init__(self):
        self.console = Console()
        self.service = LocalRagService()
        self.mode = "standard"
        self.history = []
        self.alpha = 0.7
        self.temperature = 0.1
        self.top_k_range = (3, 20)

    def run(self):
        self.console.clear()
        result = render_home(self.console)
        if result is None:
            return

        self.mode = result["mode"]
        collection = result["collection"]
        files = result["files"]

        ok = render_loading(
            self.console, self.service, files, collection, self.mode,
        )
        if not ok:
            self.console.print(error_panel("Failed to build index."))
            return

        watch_dir = get_key(".env", "RAG_WATCH_DIR") or ""
        if watch_dir and os.path.isdir(watch_dir):
            self.service.set_watch_dir(watch_dir)
            self.service.start_watching()

        try:
            run_chat_loop(
                self.console, self.service, self.mode,
                self.alpha, self.temperature, self.top_k_range,
            )
        finally:
            self.service.stop_watching()
