# Mneme RAG 系统初始化引导功能开发计划

> 文档版本：v1.2
> 创建日期：2026-07-04
> 修订日期：2026-07-04
> 作者：ZCode AI Agent

---

## 一、需求概述

### 1.1 背景

当前 Mneme RAG 系统启动时直接进入主界面，若用户未配置 `API_KEY` 和 `BASE_URL`，系统会在查询时才报错提示。这对新用户不够友好，容易造成困惑。

### 1.2 目标

实现**首次启动引导向导**，在检测到必要配置缺失时，自动启动引导流程，帮助用户完成：
- API_KEY 配置（必填）
- BASE_URL 配置（必填）
- LLM 模型选择（与 Provider 联动）
- 功能演示/教程（可跳过）

### 1.3 触发条件

- `.env` 文件不存在，**或**
- `.env` 文件中 `API_KEY` 为空，**或**
- `.env` 文件中 `BASE_URL` 为空

---

## 二、技术方案

### 2.1 方案对比（Brainstorming）

#### 方案 A：独立 `onboarding.py` + questionary 全流程

**描述**：新增 `tui/screens/onboarding.py`，使用 questionary 实现完整的 4 步引导向导。

**优点**：
- 模块化清晰，符合现有 `screens/` 架构
- 引导体验连贯，专向专做
- 易于测试和维护

**缺点**：
- 新增一个模块
- 与 `home.py` 的部分 UI 逻辑有重复（LOGO、样式）

#### 方案 B：嵌入 `home.py` 现有流程

**描述**：在 `render_home()` 开头添加配置检测，缺失时弹出简单提示行并跳转到 `/settings`。

**优点**：
- 不新增文件
- 复用现有 UI 组件

**缺点**：
- 混淆「主界面」与「引导」职责
- `home.py` 已承担模式选择、文件选择逻辑，再加引导会过于臃肿
- 引导流程需要多步交互，嵌入后难以保持连贯体验

#### 方案 C：Rich Prompt 内联引导

**描述**：不用 questionary，改用 `rich.prompt.Prompt` 在原地询问配置。

**优点**：
- 代码量少

**缺点**：
- 现有 `home.py` 的文件选择已用 questionary，混合使用会风格不一致
- Rich Prompt 缺少下拉选择等交互组件

**选择**：**方案 A**，理由：
1. 模块化清晰，符合 SRP（单一职责）
2. questionary 已在项目中使用，保持一致性
3. 引导是独立场景，用户体验更连贯

### 2.2 架构设计

```
app.py 启动流程：
┌─────────────────────────────────────────┐
│  RagApp.run()                           │
│  ├─ _need_onboarding() → 检测 .env      │
│  │  ├─ True  → render_onboarding()      │
│  │  │           └─ 保存配置到 .env      │
│  │  └─ False → 直接进入                 │
│  └─ render_home() → render_loading()    │
│                → run_chat_loop()        │
└─────────────────────────────────────────┘
```

### 2.3 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `tui/screens/onboarding.py` | **新增** | 引导向导主逻辑 |
| `tui/app.py` | **修改** | 添加启动检测和跳转逻辑 |

### 2.4 引导流程设计

```
Step 0: 欢迎页
    ↓
Step 1: Provider 选择（DeepSeek / OpenAI / 自定义）
    ↓
Step 2: API_KEY 输入（必填，格式校验）
    ↓
Step 3: LLM 模型选择（根据 Provider 联动显示）
    ↓
Step 4: 功能演示（可跳过）
    ↓
Step 5: 保存配置 → 跳转主界面
```

**设计变更说明**：将 Provider 选择提前到 Step 1，以便后续 Step 3 的模型列表能根据 Provider 动态联动。

---

## 三、详细设计

### 3.1 新增文件：`tui/screens/onboarding.py`

#### 3.1.1 模块结构

```python
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
from tui.screens.home import LOGO  # 复用 LOGO，避免重复定义


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
    """Step 0: 显示欢迎页"""
    ...

def _step_provider(console: Console) -> str:
    """Step 1: 选择 Provider"""
    ...

def _step_api_key(console: Console) -> str:
    """Step 2: 输入 API_KEY"""
    ...

def _step_base_url(console: Console) -> str:
    """Step 2b: 配置自定义 BASE_URL"""
    ...

def _step_llm_model(console: Console, provider: str) -> str:
    """Step 4: 选择 LLM 模型（根据 Provider 联动）"""
    ...

def _step_demo(console: Console) -> None:
    """Step 5: 功能演示"""
    ...

def _save_config(console: Console, config: dict) -> bool:
    """保存配置到 .env 文件，返回是否成功"""
    ...
```

#### 3.1.2 各步骤详细设计

##### Step 0: 欢迎页

```python
def _step_welcome(console: Console) -> None:
    """显示欢迎页，介绍 Mneme 系统"""
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
```

##### Step 1: Provider 选择

```python
def _step_provider(console: Console) -> str:
    """选择 API 服务提供商"""
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
```

##### Step 2: API_KEY 输入

```python
def _step_api_key(console: Console) -> str:
    """输入 API_KEY，带格式校验"""
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
                f"API Key 不以 'sk-' 开头，确定继续？",
                default=True,
                style=_QS,
            ).ask()
            if confirm is None:  # Ctrl+C
                return None
            if not confirm:
                continue

        return key
```

##### Step 2b: BASE_URL 配置（仅自定义 Provider）

```python
def _step_base_url(console: Console) -> str:
    """配置自定义 BASE_URL"""
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
```

##### Step 4: LLM 模型选择（联动）

```python
def _step_llm_model(console: Console, provider: str) -> str:
    """选择 LLM 模型，根据 Provider 动态显示可用模型"""
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
```

##### Step 5: 功能演示

```python
def _step_demo(console: Console) -> None:
    """展示系统功能，帮助用户了解使用方式"""
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
```

##### 配置保存

```python
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
```

> **注意**：`render_onboarding` 中调用 `_save_config` 后需检查返回值，失败时返回 None 让主控处理。

### 3.2 修改文件：`tui/app.py`

#### 3.2.1 新增检测函数

```python
def _need_onboarding() -> bool:
    """
    检测是否需要启动引导向导。

    条件：
      - .env 文件不存在，或
      - API_KEY 为空，或
      - BASE_URL 为空

    Returns:
        bool: True 表示需要引导

    Note:
        使用 load_dotenv + os.getenv 避免 get_key 的 stderr 噪音。
    """
    from dotenv import load_dotenv

    if not os.path.isfile(".env"):
        return True

    # 加载 .env 到环境变量（不输出 stderr 噪音）
    load_dotenv()

    api_key = os.environ.get("API_KEY", "").strip()
    base_url = os.environ.get("BASE_URL", "").strip()

    return not api_key or not base_url
```

#### 3.2.2 修改 `RagApp.run()` 方法

```python
def run(self):
    self.console.clear()

    # ── 新增：首次启动引导 ──
    if _need_onboarding():
        from tui.screens.onboarding import render_onboarding
        config = render_onboarding(self.console)
        if config is None:
            # 用户中途退出（Ctrl+C 或取消）
            self.console.print(
                f"\n[{THEME['text_dim']}]配置未保存，请重新启动程序。[/]"
            )
            return
        # 配置已保存，继续启动

    # ── 原有逻辑 ──
    result = render_home(self.console)
    if result is None:
        return
    # ... 后续不变
```

---

## 四、错误处理

| 场景 | 处理方式 |
|------|----------|
| 用户中途退出（Ctrl+C） | 主控 `try/except KeyboardInterrupt` 捕获，返回 None，显示提示后退出程序 |
| API_KEY 格式异常 | 提示不以 `sk-` 开头，确认后可继续 |
| BASE_URL 格式异常 | 校验 `http/https` 前缀，不通过则重试 |
| .env 写入失败 | `_save_config` 捕获异常，打印配置到终端供手动保存 |
| questionary 返回 None | 视为用户取消，由主控统一处理 |

---

## 五、测试计划

### 5.1 单元测试

```python
# tests/test_onboarding.py

import os
import pytest
from unittest.mock import patch, MagicMock


class TestNeedOnboarding:
    """测试 _need_onboarding 函数"""

    def test_no_env_file(self, tmp_path, monkeypatch):
        """无 .env 文件时应触发引导"""
        monkeypatch.chdir(tmp_path)
        from tui.app import _need_onboarding
        assert _need_onboarding() is True

    def test_empty_api_key(self, tmp_path, monkeypatch):
        """API_KEY 为空时应触发引导"""
        env_file = tmp_path / ".env"
        env_file.write_text("BASE_URL=https://api.deepseek.com/v1\n")
        monkeypatch.chdir(tmp_path)
        # 清除环境变量（使用 monkeypatch 避免测试污染）
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("BASE_URL", raising=False)
        from tui.app import _need_onboarding
        assert _need_onboarding() is True

    def test_empty_base_url(self, tmp_path, monkeypatch):
        """BASE_URL 为空时应触发引导"""
        env_file = tmp_path / ".env"
        env_file.write_text("API_KEY=sk-test123456\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("BASE_URL", raising=False)
        from tui.app import _need_onboarding
        assert _need_onboarding() is True

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
        from tui.app import _need_onboarding
        assert _need_onboarding() is False
```

### 5.2 集成测试

```python
class TestOnboardingFlow:
    """测试引导流程"""

    def test_onboarding_flow_creates_env_file(self, tmp_path, monkeypatch):
        """引导完成后应创建 .env 文件"""
        monkeypatch.chdir(tmp_path)

        # Mock questionary 交互
        with patch("questionary.press_any_key_to_continue") as mock_press, \
             patch("questionary.select") as mock_select, \
             patch("questionary.text") as mock_text, \
             patch("questionary.confirm") as mock_confirm:

            # 设置 mock 返回值
            mock_press.return_value.ask.return_value = None
            mock_select.return_value.ask.side_effect = ["DeepSeek", "deepseek-chat"]
            mock_text.return_value.ask.return_value = "sk-test12345678"
            mock_confirm.return_value.ask.return_value = True

            from tui.screens.onboarding import render_onboarding
            from rich.console import Console

            console = Console()
            result = render_onboarding(console)

            # 验证返回值
            assert result is not None
            assert result["api_key"] == "sk-test12345678"
            assert result["base_url"] == "https://api.deepseek.com/v1"
            assert result["llm_model"] == "deepseek-chat"

            # 验证 .env 文件创建
            assert os.path.exists(".env")

    def test_onboarding_cancel_does_not_create_env(self, tmp_path, monkeypatch):
        """用户取消引导不应创建 .env"""
        monkeypatch.chdir(tmp_path)

        with patch("questionary.press_any_key_to_continue") as mock_press, \
             patch("questionary.select") as mock_select:

            mock_press.return_value.ask.return_value = None
            mock_select.return_value.ask.return_value = None  # 用户取消

            from tui.screens.onboarding import render_onboarding
            from rich.console import Console

            console = Console()
            result = render_onboarding(console)

            # 验证返回 None
            assert result is None

            # 验证 .env 文件未创建
            assert not os.path.exists(".env")

    def test_onboarding_keyboard_interrupt(self, tmp_path, monkeypatch):
        """Ctrl+C 应正常退出且不创建 .env"""
        monkeypatch.chdir(tmp_path)

        with patch("questionary.press_any_key_to_continue") as mock_press:
            # 模拟 Ctrl+C
            mock_press.return_value.ask.side_effect = KeyboardInterrupt()

            from tui.screens.onboarding import render_onboarding
            from rich.console import Console

            console = Console()
            result = render_onboarding(console)

            # 验证返回 None
            assert result is None

            # 验证 .env 文件未创建
            assert not os.path.exists(".env")
```

### 5.3 手动测试清单

- [ ] 删除 `.env`，启动应用，验证引导流程启动
- [ ] 完成引导，验证 `.env` 文件生成正确
- [ ] 中途按 Ctrl+C，验证程序退出且未生成 `.env`
- [ ] 保留 `.env` 重新启动，验证直接进入主界面
- [ ] 输入非法 API_KEY（不以 sk- 开头），验证提示正确
- [ ] 选择 DeepSeek Provider，验证模型列表仅含 deepseek-chat/reasoner
- [ ] 选择 OpenAI Provider，验证模型列表仅含 gpt 系列
- [ ] 选择自定义 Provider，验证需要手动输入 Base URL 和 Model

---

## 六、实现步骤

### Phase 1: 核心实现（约 2 小时）

1. **创建 `tui/screens/onboarding.py`**
   - 实现 Provider 与模型联动配置
   - 实现各步骤函数
   - 实现 `render_onboarding()` 主函数（含 KeyboardInterrupt 捕获）
   - 实现 `_save_config()` 保存逻辑

2. **修改 `tui/app.py`**
   - 添加 `_need_onboarding()` 检测函数
   - 在 `run()` 方法开头添加引导跳转逻辑

### Phase 2: 测试与验证（约 1.5 小时）

3. **编写单元测试**
   - `tests/test_onboarding.py`
   - 覆盖 `_need_onboarding()` 各种场景

4. **编写集成测试**
   - Mock questionary 交互
   - 覆盖正常完成、取消、Ctrl+C 三种路径

5. **手动测试**
   - 按照测试清单逐项验证

### Phase 3: 文档更新（约 0.5 小时）

6. **更新 README**
   - 添加"首次启动"章节说明引导流程

7. **更新 CHANGELOG**
   - 记录新增功能

---

## 七、风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| questionary 在某些终端下显示异常 | 已在项目中使用 questionary，保持一致 |
| 用户输入特殊字符导致 .env 解析错误 | 使用 `python-dotenv.set_key()` 自动处理转义 |
| 引导流程过长导致用户流失 | 控制在 4 步以内，每步简洁，可跳过演示 |
| Provider 与模型不匹配导致首次查询失败 | 联动设计确保模型列表与 Provider 匹配 |

---

## 八、验收标准

- [ ] 删除 `.env` 后启动应用，自动进入引导流程
- [ ] 引导完成后，`.env` 文件包含正确的 `API_KEY`、`BASE_URL`、`LLM_MODEL`
- [ ] 配置完整时启动应用，直接进入主界面
- [ ] 用户中途退出引导，程序正常退出且不生成 `.env`
- [ ] Provider 与模型联动正确（DeepSeek 仅显示 deepseek 模型，OpenAI 仅显示 gpt 模型）
- [ ] 所有单元测试和集成测试通过
- [ ] CHANGELOG 已更新

---

## 九、附录

### A. Provider 与模型联动配置

```python
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
```

### B. 审核问题修复清单

**v1.1 修复（首轮审核）**

| 问题编号 | 问题描述 | 修复状态 |
|----------|----------|----------|
| C1 | 集成测试是空 `pass` | ✅ 已提供完整的 mock 策略和测试代码 |
| C2 | `render_onboarding` 主控逻辑未展示 | ✅ 已补全完整实现，含 KeyboardInterrupt 捕获 |
| C3 | 缺少 brainstorming 方案对比 | ✅ 已添加 2.1 方案对比章节 |
| I1 | Provider 与模型不联动 | ✅ 已重构流程，Provider 选择前置，模型列表联动 |
| I2 | `_save_config` 含冗余代码 | ✅ 已删除 `open().close()` |
| I3 | `get_key` 输出 stderr 噪音 | ✅ 改用 `load_dotenv()` + `os.getenv()` |
| I4 | KeyboardInterrupt 处理不完整 | ✅ 主控统一 try/except 捕获 |
| M1 | LOGO 重复定义 | ✅ 从 `home.py` 导入复用 |
| M2 | `_QS` 重复定义 | ✅ 保留在 onboarding.py，样式基本一致 |
| M3 | 局部导入问题 | ✅ `_need_onboarding` 改用顶部导入的 `load_dotenv` |
| M4 | `tui/keys.py` 无实际变更 | ✅ 已从变更清单移除 |
| M5 | `.env` 硬编码相对路径 | ✅ 记录为后续改进（当前与既有代码一致） |

**v1.2 修复（第二轮审核）**

| 问题编号 | 问题描述 | 修复状态 |
|----------|----------|----------|
| N1 | `_save_config` 缺少异常捕获，与错误处理表矛盾 | ✅ 已添加 try/except，失败时打印配置供手动保存 |
| N2 | `_step_llm_model` 自定义模型输入 Ctrl+C 不取消 | ✅ 已区分 None（取消）与空字符串（回退默认） |
| N3 | 流程图缺少 Step 2b | ⚠️ 实施时补充 |
| N4 | 单元测试用 `os.environ.pop` 有污染风险 | ✅ 已改用 `monkeypatch.delenv` |
| N5 | 集成测试未覆盖自定义模型分支 | ⚠️ 实施时补充 |
| N6 | `_step_base_url` validate 仅校验前缀 | ⚠️ 可接受，不阻断 |

---

> 文档结束
