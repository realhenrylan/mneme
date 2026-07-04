"""
首次启动引导向导
================
在检测到 .env 缺失或必要配置为空时自动启动，
引导用户完成 Provider、API_KEY、LLM 模型等基础配置。
"""

import os
from dotenv import set_key
from rich.console import Console
from rich.panel import Panel
import questionary
from questionary import Style as QStyle

from tui.theme import THEME
from tui.logo import LOGO
from tui.components.message import error_panel


# ── Provider 与模型联动配置 ────────────────────────────────

PROVIDER_CONFIG = {
    "DeepSeek": {
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
    },
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
        "default_model": "gpt-4o-mini",
    },
    "自定义": {
        "base_url": None,  # 需要手动输入
        "models": [],       # 需要手动输入
        "default_model": None,
    },
}


# ── questionary 样式（复用 home.py 的 _QS） ─────────────────

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


# ── 公共接口 ───────────────────────────────────────────────

def render_onboarding(console: Console) -> dict:
    """
    渲染引导向导，返回用户配置字典。

    Returns:
        dict: {
            'api_key': str,
            'base_url': str,
            'llm_model': str,
        }
        或 None（用户中途退出）
    """
    config = {}

    try:
        # Step 0: 欢迎页
        _step_welcome(console)

        # Step 1: Provider 选择
        provider = _step_provider(console)
        if provider is None:
            return None
        config["provider"] = provider

        # Step 2: API_KEY 输入
        api_key = _step_api_key(console)
        if api_key is None:
            return None
        config["api_key"] = api_key

        # Step 3: BASE_URL 配置（仅自定义 Provider 需要）
        if PROVIDER_CONFIG[provider]["base_url"] is None:
            base_url = _step_base_url(console)
            if base_url is None:
                return None
            config["base_url"] = base_url
        else:
            config["base_url"] = PROVIDER_CONFIG[provider]["base_url"]

        # Step 4: LLM 模型选择（联动）
        llm_model = _step_llm_model(console, provider)
        if llm_model is None:
            return None
        config["llm_model"] = llm_model

        # Step 5: 功能演示
        _step_demo(console)

        # 保存配置
        if not _save_config(console, config):
            return None

        return config

    except KeyboardInterrupt:
        # 统一捕获 Ctrl+C，返回 None 表示用户取消
        return None


# ── 内部步骤函数 ────────────────────────────────────────────

def _step_welcome(console: Console) -> None:
    """Step 0: 显示欢迎页，介绍 Mneme 系统"""
    console.clear()
    console.print(Panel(LOGO, border_style=THEME["accent"]))
    console.print()
    console.print(
        f"[bold {THEME['accent']}]  欢迎使用 Mneme 知识问答系统[/]\n"
    )
    console.print(
        f"  [{THEME['text_dim']}]"
        "Mneme 是一个基于 RAG 技术的智能问答系统，支持：\n"
        "  · 标准语义检索 (Standard RAG)\n"
        "  · 知识图谱增强检索 (Graph RAG)\n"
        "  · 多格式文档支持 (PDF, DOCX, Markdown, 代码等)\n"
        "[/]\n"
    )
    console.print(
        f"  [{THEME['text_dim']}]接下来将引导您完成基础配置（约 1 分钟）。[/]"
    )
    questionary.press_any_key_to_continue(
        message="Press Enter to continue...",
        style=_QS,
    ).ask()


def _step_provider(console: Console) -> str:
    """Step 1: 选择 API 服务提供商"""
    console.clear()
    console.print(f"[bold {THEME['accent']}]Step 1/4: 选择 API 服务提供商[/]\n")
    console.print(
        f"  [{THEME['text_dim']}]请选择您要使用的 LLM 服务提供商：[/]\n"
    )

    choice = questionary.select(
        "Provider:",
        choices=list(PROVIDER_CONFIG.keys()),
        style=_QS,
    ).ask()

    return choice  # None 表示 Ctrl+C，由主控函数处理


def _step_api_key(console: Console) -> str:
    """Step 2: 输入 API_KEY，带格式校验"""
    console.clear()
    console.print(f"[bold {THEME['accent']}]Step 2/4: API Key 配置[/]\n")
    console.print(
        f"  [{THEME['text_dim']}]"
        "请输入您的 LLM API Key。\n"
        "  · DeepSeek: 在 https://platform.deepseek.com/ 获取\n"
        "  · OpenAI: 在 https://platform.openai.com/ 获取\n"
        "[/]\n"
    )

    while True:
        key = questionary.text(
            "API Key:",
            validate=lambda x: len(x.strip()) >= 10 or "API Key 长度不足",
            style=_QS,
        ).ask()

        if key is None:  # Ctrl+C
            return None

        key = key.strip()
        # 格式提示（不强制校验，因为不同平台格式可能不同）
        if not key.startswith("sk-"):
            confirm = questionary.confirm(
                "API Key 不以 'sk-' 开头，确定继续？",
                default=True,
                style=_QS,
            ).ask()
            if confirm is None:  # Ctrl+C
                return None
            if not confirm:
                continue

        return key


def _step_base_url(console: Console) -> str:
    """Step 3: 配置自定义 BASE_URL"""
    console.clear()
    console.print(f"[bold {THEME['accent']}]Step 2b/4: 自定义 Base URL[/]\n")
    console.print(
        f"  [{THEME['text_dim']}]请输入 API Base URL：[/]\n"
    )

    url = questionary.text(
        "Base URL:",
        validate=lambda x: x.strip().startswith("http") or "URL 应以 http/https 开头",
        style=_QS,
    ).ask()

    return url.strip() if url else None


def _step_llm_model(console: Console, provider: str) -> str:
    """Step 4: 选择 LLM 模型，根据 Provider 动态显示可用模型"""
    console.clear()
    console.print(f"[bold {THEME['accent']}]Step 3/4: LLM 模型选择[/]\n")

    provider_cfg = PROVIDER_CONFIG[provider]

    if provider_cfg["models"]:
        # 有预设模型列表
        console.print(
            f"  [{THEME['text_dim']}]请选择要使用的语言模型：[/]\n"
        )
        choices = provider_cfg["models"] + ["自定义"]
        choice = questionary.select(
            "Model:",
            choices=choices,
            style=_QS,
        ).ask()

        if choice is None:
            return None

        if choice == "自定义":
            model = questionary.text(
                "Model name:",
                default=provider_cfg["default_model"] or "",
                style=_QS,
            ).ask()
            # 区分 None（Ctrl+C 取消）与空字符串（回退默认）
            if model is None:
                return None
            return model.strip() or provider_cfg["default_model"]

        return choice
    else:
        # 自定义 Provider，手动输入
        console.print(
            f"  [{THEME['text_dim']}]请输入要使用的模型名称：[/]\n"
        )
        model = questionary.text(
            "Model name:",
            style=_QS,
        ).ask()
        # 区分 None（取消）与空字符串
        if model is None:
            return None
        return model.strip() or None


def _step_demo(console: Console) -> None:
    """Step 5: 展示系统功能，帮助用户了解使用方式"""
    console.clear()
    console.print(f"[bold {THEME['accent']}]Step 4/4: 功能速览[/]\n")

    # 功能卡片
    features = [
        ("Standard RAG", "基于向量相似度的语义检索，适合快速问答"),
        ("Graph RAG", "结合知识图谱的增强检索，适合复杂推理"),
        ("/files", "管理索引文档：添加、移除、监控目录"),
        ("/settings", "调整参数：temperature、top-k、alpha"),
        ("/mode", "切换 Standard/Graph 模式"),
        ("/help", "查看所有命令"),
    ]

    for name, desc in features:
        console.print(
            f"  [bold {THEME['accent']}]{name}[/] "
            f"[{THEME['text_dim']}]{desc}[/]"
        )

    console.print()
    questionary.press_any_key_to_continue(
        message="Press Enter to finish setup...",
        style=_QS,
    ).ask()


def _save_config(console: Console, config: dict) -> bool:
    """
    保存配置到 .env 文件。

    Returns:
        bool: True 表示保存成功，False 表示失败

    Note:
        set_key 会自动创建文件，并对值加引号。
    """
    try:
        # 写入配置（set_key 对不存在的文件会自动创建）
        set_key(".env", "API_KEY", config["api_key"])
        set_key(".env", "BASE_URL", config["base_url"])
        set_key(".env", "LLM_MODEL", config["llm_model"])

        # 同步到环境变量（当前进程生效）
        os.environ["API_KEY"] = config["api_key"]
        os.environ["BASE_URL"] = config["base_url"]
        os.environ["LLM_MODEL"] = config["llm_model"]

        console.print(
            f"\n[bold {THEME['success']}]✓ 配置已保存到 .env[/]\n"
        )
        return True

    except Exception as e:
        # 写入失败，打印配置供用户手动保存
        console.print(error_panel(
            f"保存配置失败: {e}\n\n"
            "请手动创建 .env 文件并添加以下内容：\n"
            f"  API_KEY='{config['api_key']}'\n"
            f"  BASE_URL='{config['base_url']}'\n"
            f"  LLM_MODEL='{config['llm_model']}'",
            title="配置保存失败",
        ))
        return False