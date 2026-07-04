import os
import sys
from dotenv import get_key
from rich.console import Console
from tui.theme import THEME
from tui.env_check import need_onboarding
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
        # 从 .env 读取用户自定义配置，否则使用默认值
        alpha_val = get_key(".env", "ALPHA")
        temp_val = get_key(".env", "LLM_TEMPERATURE")
        tk_min = get_key(".env", "LLM_TOP_K_MIN")
        tk_max = get_key(".env", "LLM_TOP_K_MAX")
        self.alpha = float(alpha_val) if alpha_val else 0.7
        self.temperature = float(temp_val) if temp_val else 0.1
        self.top_k_range = (
            int(tk_min) if tk_min else 3,
            int(tk_max) if tk_max else 20,
        )

    def run(self):
        self.console.clear()

        # ── 首次启动引导 ──
        if need_onboarding():
            from tui.screens.onboarding import render_onboarding
            config = render_onboarding(self.console)
            if config is None:
                # 用户中途退出（Ctrl+C 或取消）
                self.console.print(
                    f"\n[{THEME['text_dim']}]配置未保存，请重新启动程序。[/]"
                )
                return
            # 配置已保存，继续启动

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
