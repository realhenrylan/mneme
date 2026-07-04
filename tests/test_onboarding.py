"""
首次启动引导向导测试
==================
测试 need_onboarding 检测函数和引导流程。
"""

import os
import pytest
from unittest.mock import patch
from pathlib import Path


class TestNeedOnboarding:
    """测试 need_onboarding 函数（真实函数，无重依赖）"""

    def test_no_env_file(self, tmp_path, monkeypatch):
        """无 .env 文件时应触发引导"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("BASE_URL", raising=False)
        from tui.env_check import need_onboarding
        assert need_onboarding() is True

    def test_empty_api_key(self, tmp_path, monkeypatch):
        """API_KEY 为空时应触发引导"""
        env_file = tmp_path / ".env"
        env_file.write_text("BASE_URL=https://api.deepseek.com/v1\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("BASE_URL", raising=False)
        from tui.env_check import need_onboarding
        assert need_onboarding() is True

    def test_empty_base_url(self, tmp_path, monkeypatch):
        """BASE_URL 为空时应触发引导"""
        env_file = tmp_path / ".env"
        env_file.write_text("API_KEY=sk-test123456\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("BASE_URL", raising=False)
        from tui.env_check import need_onboarding
        assert need_onboarding() is True

    def test_complete_config(self, tmp_path, monkeypatch):
        """配置完整时不应触发引导"""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "API_KEY=sk-test123456\n"
            "BASE_URL=https://api.deepseek.com/v1\n"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("BASE_URL", raising=False)
        from tui.env_check import need_onboarding
        assert need_onboarding() is False

    def test_whitespace_only_values(self, tmp_path, monkeypatch):
        """仅有空白字符的值应视为空"""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "API_KEY=   \n"
            "BASE_URL=https://api.deepseek.com/v1\n"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("BASE_URL", raising=False)
        from tui.env_check import need_onboarding
        assert need_onboarding() is True


class TestOnboardingFlow:
    """测试引导流程"""

    def test_onboarding_flow_creates_env_file(self, tmp_path, monkeypatch):
        """引导完成后应创建 .env 文件"""
        monkeypatch.chdir(tmp_path)

        import tui.screens.onboarding
        from tui.screens.onboarding import render_onboarding

        with patch("tui.screens.onboarding.questionary.press_any_key_to_continue") as mock_press, \
             patch("tui.screens.onboarding.questionary.select") as mock_select, \
             patch("tui.screens.onboarding.questionary.text") as mock_text, \
             patch("tui.screens.onboarding.questionary.confirm") as mock_confirm:

            mock_press.return_value.ask.return_value = None
            mock_select.return_value.ask.side_effect = ["DeepSeek", "deepseek-chat"]
            mock_text.return_value.ask.return_value = "sk-test12345678"
            mock_confirm.return_value.ask.return_value = True

            from rich.console import Console

            console = Console()
            result = render_onboarding(console)

            assert result is not None
            assert result["api_key"] == "sk-test12345678"
            assert result["base_url"] == "https://api.deepseek.com/v1"
            assert result["llm_model"] == "deepseek-chat"
            assert os.path.exists(".env")

    def test_onboarding_cancel_does_not_create_env(self, tmp_path, monkeypatch):
        """用户取消引导不应创建 .env"""
        monkeypatch.chdir(tmp_path)

        import tui.screens.onboarding
        from tui.screens.onboarding import render_onboarding

        with patch("tui.screens.onboarding.questionary.press_any_key_to_continue") as mock_press, \
             patch("tui.screens.onboarding.questionary.select") as mock_select:

            mock_press.return_value.ask.return_value = None
            mock_select.return_value.ask.return_value = None

            from rich.console import Console

            console = Console()
            result = render_onboarding(console)

            assert result is None
            assert not os.path.exists(".env")

    def test_onboarding_keyboard_interrupt(self, tmp_path, monkeypatch):
        """Ctrl+C 应正常退出且不创建 .env"""
        monkeypatch.chdir(tmp_path)

        import tui.screens.onboarding
        from tui.screens.onboarding import render_onboarding

        with patch("tui.screens.onboarding.questionary.press_any_key_to_continue") as mock_press:
            mock_press.return_value.ask.side_effect = KeyboardInterrupt()

            from rich.console import Console

            console = Console()
            result = render_onboarding(console)

            assert result is None
            assert not os.path.exists(".env")

    def test_onboarding_custom_provider(self, tmp_path, monkeypatch):
        """自定义 Provider 应要求手动输入 Base URL 和 Model"""
        monkeypatch.chdir(tmp_path)

        import tui.screens.onboarding
        from tui.screens.onboarding import render_onboarding

        with patch("tui.screens.onboarding.questionary.press_any_key_to_continue") as mock_press, \
             patch("tui.screens.onboarding.questionary.select") as mock_select, \
             patch("tui.screens.onboarding.questionary.text") as mock_text, \
             patch("tui.screens.onboarding.questionary.confirm") as mock_confirm:

            mock_press.return_value.ask.return_value = None
            mock_select.return_value.ask.return_value = "自定义"
            mock_text.return_value.ask.side_effect = [
                "sk-test12345678",
                "https://custom.api.com/v1",
                "custom-model",
            ]
            mock_confirm.return_value.ask.return_value = True

            from rich.console import Console

            console = Console()
            result = render_onboarding(console)

            assert result is not None
            assert result["api_key"] == "sk-test12345678"
            assert result["base_url"] == "https://custom.api.com/v1"
            assert result["llm_model"] == "custom-model"

    def test_onboarding_custom_model_selection(self, tmp_path, monkeypatch):
        """选择预设 Provider 后选择自定义模型"""
        monkeypatch.chdir(tmp_path)

        import tui.screens.onboarding
        from tui.screens.onboarding import render_onboarding

        with patch("tui.screens.onboarding.questionary.press_any_key_to_continue") as mock_press, \
             patch("tui.screens.onboarding.questionary.select") as mock_select, \
             patch("tui.screens.onboarding.questionary.text") as mock_text, \
             patch("tui.screens.onboarding.questionary.confirm") as mock_confirm:

            mock_press.return_value.ask.return_value = None
            mock_select.return_value.ask.side_effect = ["OpenAI", "自定义"]
            mock_text.return_value.ask.side_effect = [
                "sk-test12345678",
                "gpt-4-turbo",
            ]
            mock_confirm.return_value.ask.return_value = True

            from rich.console import Console

            console = Console()
            result = render_onboarding(console)

            assert result is not None
            assert result["llm_model"] == "gpt-4-turbo"

    def test_onboarding_openai_provider(self, tmp_path, monkeypatch):
        """选择 OpenAI Provider 应自动设置 Base URL"""
        monkeypatch.chdir(tmp_path)

        import tui.screens.onboarding
        from tui.screens.onboarding import render_onboarding

        with patch("tui.screens.onboarding.questionary.press_any_key_to_continue") as mock_press, \
             patch("tui.screens.onboarding.questionary.select") as mock_select, \
             patch("tui.screens.onboarding.questionary.text") as mock_text, \
             patch("tui.screens.onboarding.questionary.confirm") as mock_confirm:

            mock_press.return_value.ask.return_value = None
            mock_select.return_value.ask.side_effect = ["OpenAI", "gpt-4o"]
            mock_text.return_value.ask.return_value = "sk-openai-test12345"
            mock_confirm.return_value.ask.return_value = True

            from rich.console import Console

            console = Console()
            result = render_onboarding(console)

            assert result is not None
            assert result["api_key"] == "sk-openai-test12345"
            assert result["base_url"] == "https://api.openai.com/v1"
            assert result["llm_model"] == "gpt-4o"


class TestLogoReuse:
    """测试 LOGO 复用"""

    def test_logo_content_consistency(self):
        """home.py 和 onboarding.py 的 LOGO 内容应一致"""
        # 由于 home.py 有 chromadb 依赖，无法直接导入验证对象同一性
        # 但可以通过检查 onboarding.py 和 logo.py 的导入关系验证
        from tui.logo import LOGO
        from tui.screens.onboarding import LOGO as onboarding_logo

        # onboarding 直接从 tui.logo 导入，必然是同一对象
        assert onboarding_logo is LOGO

    def test_logo_import_path_in_home(self):
        """验证 home.py 的 LOGO 导入路径（静态检查）"""
        import ast
        import os

        home_path = os.path.join(os.path.dirname(__file__), "..", "tui", "screens", "home.py")
        with open(home_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        # 检查是否有 `from tui.logo import LOGO` 导入
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "tui.logo":
                    names = [alias.name for alias in node.names]
                    assert "LOGO" in names, "home.py 应从 tui.logo 导入 LOGO"