"""Phase C 计划 3.2 第七轮 TUI 配置边界契约测试。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from rich.console import Console


_MANAGED_KEYS = (
    "API_KEY",
    "BASE_URL",
    "LLM_MODEL",
    "LLM_TEMPERATURE",
    "LLM_TOP_K_MIN",
    "LLM_TOP_K_MAX",
    "ALPHA",
)


def _clean_env() -> None:
    for key in _MANAGED_KEYS:
        os.environ.pop(key, None)


def test_need_onboarding_uses_process_credentials_without_env_file(tmp_path):
    script = """
import os
from tui.env_check import need_onboarding
assert need_onboarding('/missing/.env') is False
assert os.environ['API_KEY'] == 'process-api'
assert os.environ['BASE_URL'] == 'https://process.example/v1'
"""
    env = os.environ.copy()
    env.update({"API_KEY": "process-api", "BASE_URL": "https://process.example/v1"})
    for key in _MANAGED_KEYS:
        if key not in ("API_KEY", "BASE_URL"):
            env.pop(key, None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / ".mneme").exists()


def test_need_onboarding_still_triggers_without_credentials_or_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _clean_env()
    from tui.env_check import need_onboarding

    assert need_onboarding(tmp_path / ".env") is True


def test_chat_api_key_edit_never_overwrites_process_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _clean_env()
    os.environ.update({"API_KEY": "process-api", "BASE_URL": "https://process.example/v1"})

    import tui.screens.chat as chat

    choices = ["api_key", "exit"]
    with patch.object(chat.questionary, "select") as select, \
         patch.object(chat.questionary, "text") as text, \
         patch.object(chat, "reset_settings") as reset:
        select.return_value.ask.side_effect = choices
        text.return_value.ask.return_value = "ui-api"
        chat._configure_settings(Console())

    assert os.environ["API_KEY"] == "process-api"
    assert (tmp_path / ".env").exists()
    assert "API_KEY=" in (tmp_path / ".env").read_text()
    reset.assert_called_once()


def test_onboarding_save_refreshes_settings_in_current_process(tmp_path):
    script = """
import os
from rich.console import Console
from src.config import get_settings
from tui.screens.onboarding import _save_config
assert _save_config(Console(), {
    'api_key': 'onboarding-api',
    'base_url': 'https://onboarding.example/v1',
    'llm_model': 'onboarding-model',
}) is True
assert get_settings().llm_model == 'onboarding-model'
assert os.environ['API_KEY'] == 'onboarding-api'
assert os.environ['BASE_URL'] == 'https://onboarding.example/v1'
"""
    env = os.environ.copy()
    for key in _MANAGED_KEYS:
        env.pop(key, None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".env").exists()
    assert not (tmp_path / ".mneme").exists()
