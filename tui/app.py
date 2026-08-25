import os
import sys
from rich.console import Console
from tui.theme import THEME
from tui.env_check import need_onboarding
from tui.service import LocalRagService
from tui.components.message import error_panel
from tui.screens.home import render_home
from tui.screens.loading import render_loading
from tui.screens.chat import run_chat_loop

from src.config import get_settings, reset_settings


class RagApp:
    def __init__(self):
        self.console = Console()
        self.service = LocalRagService()
        self.mode = "standard"
        self.history = []
        # 统一配置契约：TUI 与 CLI/RAG 共用同一 Settings
        # （真实环境变量 > .env > 契约默认值），不再用 get_key 绕过
        # Settings 单独读 .env 得到不同的默认值。
        self._load_settings()

    def _load_settings(self):
        """从统一配置契约读取受管配置（alpha/temperature/用户 Top-K）。"""
        settings = get_settings()
        self.alpha = settings.alpha
        self.temperature = settings.llm_temperature
        self.top_k_range = (
            settings.llm_top_k_min,
            settings.llm_top_k_max,
        )

    def _read_watch_dir(self) -> str:
        """文件监控目录（TUI 专属、非受管契约配置）：环境变量优先。

        .env 已由 load_dotenv 注入环境变量，且真实环境变量优先——
        与统一契约的覆盖规则一致。
        """
        return os.environ.get("RAG_WATCH_DIR", "").strip()

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
            # 配置已保存（写入 .env 并同步 os.environ）；重建 Settings
            # 使 LLM_MODEL 等新值在本进程立即生效。
            reset_settings()
            self._load_settings()

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

        watch_dir = self._read_watch_dir()
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
            self.service.close()
