import os
import re
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
import questionary
from questionary import Style as QStyle

from src.config import (
    get_effective_env_value,
    persist_env_settings,
    reset_settings,
)  # 统一配置契约
from tui.theme import THEME
from tui.components.message import user_message, assistant_message, source_reference, error_panel, warning_panel
from tui.components.prompt import match_command
from tui.components.sidebar import render_sidebar
from tui.keys import COMMANDS


def _api_ok() -> bool:
    """Check whether .env has API_KEY configured (ignoring spaces around =)."""
    if not os.path.isfile(".env"):
        return False
    with open(".env") as f:
        for line in f:
            key, sep, val = line.strip().partition("=")
            if key.strip() == "API_KEY" and val.strip():
                return True
    return False


def _command_bar(service, mode: str = "", alpha: Optional[float] = None) -> str:
    parts = "  ".join(f"[bold {THEME['accent']}]{cmd}[/]" for cmd in COMMANDS)
    extras = []
    dot = THEME["success"] if _api_ok() else THEME["error"]
    extras.append(f"[{dot}]●[/]")
    if mode:
        extras.append(f"[{THEME['text_dim']}]Mode:[/] [bold]{mode.upper()}[/]")
    if service:
        cc = service.get_stats().get("chunk_count", 0)
        if cc:
            extras.append(f"[{THEME['text_dim']}]Chunks:[/] [bold]{cc}[/]")
    if mode == "graph" and alpha is not None:
        extras.append(f"[{THEME['text_dim']}]Alpha:[/] [bold]{alpha:.1f}[/]")
    base = f"[{THEME['text_dim']}]Commands:[/] {parts}"
    if extras:
        base += f"  [{THEME['text_dim']}]┃[/]  " + "  ".join(extras)
    return base


def citation_status_panel(status):
    """引用终态 → 独立提示 Panel（Product P0.1）。

    - unverified：显示"引用未验证"（非法编号/零引用，原回答未改动）；
    - verified：显示"引用已验证"（编号与展示来源一致）；
    - not_required（拒答 / API 错误 / 无文档证据）或 status 为 None：
      不显示任何提示（避免误导）。

    只验证编号是否对应实际 evidence，不声称语义蕴含或事实真实性。
    提示独立于回答渲染，绝不混入用户回答历史。
    """
    if status is None:
        return None
    from src.domain import CITATION_NOT_REQUIRED, CITATION_UNVERIFIED

    if status.state == CITATION_UNVERIFIED:
        if status.missing:
            detail = "回答未引用任何来源（原回答未改动）。"
        else:
            detail = (
                "回答包含无法对应到当前来源的引用编号（原回答未改动）："
                + "、".join(status.invalid_ids)
            )
        return warning_panel(detail, "引用未验证")
    if status.state == CITATION_NOT_REQUIRED:
        return None
    return Panel(
        f"[{THEME['success']}]引用已验证（编号与来源一致）[/]",
        title=f"[{THEME['text_dim']}]引用已验证[/]",
        border_style=THEME["surface"],
    )


_TRACE_ID_RE = re.compile(r"[0-9a-f]{32}")


def _handle_consent(console: Console, user_input: str) -> None:
    """本地检索观测同意状态（P1.1-M）：用户可见说明 + 显式开启/撤回。

    说明必须覆盖 Owner 固定的六项事实：本地保存、最小化采集、不存原文、
    不上传、可撤回/删除、默认关闭。开启需要用户显式键入 ``/consent on``
    （键入本身即 confirmed opt-in）；``/consent off`` 撤回并清除已封存
    trace（撤回停采）。不带参数时只读展示当前状态与说明，零写入。
    """
    from src.production_observability import ConsentLevel, TraceStore

    argument = user_input.strip()[len("/consent"):].strip().lower()
    try:
        store = TraceStore.from_environment()
    except Exception as exc:
        console.print(error_panel(f"Trace 存储路径不可用：{exc}"))
        return
    if argument in {"on", "minimal"}:
        if store.set_consent(ConsentLevel.MINIMAL, confirmed=True):
            console.print(
                f"[{THEME['success']}]已开启 Minimal 本地观测"
                f"（仅本机保存，随时 /consent off 撤回）。[/]"
            )
        else:
            console.print(warning_panel("开启失败：请检查数据目录权限。"))
        return
    if argument in {"off", "revoke"}:
        store.revoke_consent()
        console.print(
            f"[{THEME['success']}]已撤回同意并删除本机已封存 trace；"
            f"后续不再采集。[/]"
        )
        return
    enabled = store.consent.level is ConsentLevel.MINIMAL
    state = "已开启（Minimal）" if enabled else "默认关闭"
    body = (
        f"当前状态：{state}\n\n"
        "本地检索观测说明：\n"
        "- 默认关闭；仅在显式同意后采集最小诊断\n"
        "- 数据仅保存在本机数据目录的 traces/ 下，不上传任何服务器\n"
        "- 不保存原始问题 / 对话历史 / 回答 / 模型原文；只记录长度、脚本类型、\n"
        "  盐化哈希与检索漏斗元数据（chunk_id / rank / score 等）\n"
        "- 会话盐值不落盘，跨会话聚合按设计不可用\n"
        "- 本地保留 30 天滚动清理\n\n"
        "操作：/consent on 开启 · /consent off 撤回并清除 · "
        "/delete-trace <32位ID> 删除单条"
    )
    console.print(Panel(
        body,
        title=f"[{THEME['text_dim']}]本地观测同意[/]",
        border_style=THEME["surface"],
    ))


def _handle_delete_trace(console: Console, user_input: str) -> None:
    """删除单条本地观测 trace：仅接受完整 32 位 hex ID（拒绝模糊删除）。"""
    from src.production_observability import TraceStore

    argument = user_input.strip()[len("/delete-trace"):].strip()
    if not _TRACE_ID_RE.fullmatch(argument):
        console.print(warning_panel(
            "/delete-trace 需要完整的 32 位十六进制 trace ID（拒绝模糊删除）。"))
        return
    try:
        store = TraceStore.from_environment()
        store.delete_trace(argument)
    except Exception as exc:
        console.print(error_panel(f"删除失败：{exc}"))
        return
    console.print(f"[{THEME['success']}]已删除 trace {argument}。[/]")


def run_chat_loop(console: Console, service, mode: str, alpha: float,
                  temperature: float, top_k_range: tuple):
    history: list[tuple[str, str]] = []

    console.print(f"[{THEME['success']}]Ready.[/]")
    console.print(_command_bar(service, mode))
    console.print()

    while True:
        try:
            user_input = console.input(
                f"[bold {THEME['accent']}]>[/] "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            console.print(f"\n[{THEME['text_dim']}]Bye![/]")
            break

        if user_input == "\x0c":
            console.clear()
            console.print(_command_bar(service, mode))
            console.print()
            continue

        if not user_input:
            continue

        if user_input.startswith("/"):
            cmd = match_command(user_input)
            if cmd is None:
                console.print(warning_panel("Unknown command.", "Command"))
                continue
            if cmd == "/quit":
                console.print(f"[{THEME['text_dim']}]Bye![/]")
                break
            if cmd == "/clear":
                history.clear()
                console.print(f"[{THEME['success']}]History cleared.[/]")
                continue
            if cmd == "/help":
                _show_help(console)
                continue
            if cmd == "/status":
                stats = service.get_stats()
                console.print()
                console.print(render_sidebar(stats, mode, alpha, temperature, top_k_range))
                console.print()
                continue
            if cmd == "/mode":
                mode = _toggle_mode(console, mode, service)
                continue
            if cmd == "/alpha":
                alpha = _set_alpha(console, alpha)
                continue
            if cmd == "/files":
                _handle_files(console, service, user_input)
                continue
            if cmd == "/settings":
                result = _configure_settings(console, alpha, temperature, top_k_range[0], top_k_range[1])
                if result:
                    alpha, temperature, top_k_range = result
                continue
            if cmd == "/models":
                _switch_model(console)
                continue
            if cmd == "/consent":
                _handle_consent(console, user_input)
                continue
            if cmd == "/delete-trace":
                _handle_delete_trace(console, user_input)
                continue
            continue

        history.append((user_input, ""))

        full_text = ""
        try:
            label = "Graph RAG" if mode == "graph" else "Standard RAG"
            with console.status(
                f"[bold {THEME['accent']}]{label} thinking...[/]",
                spinner="dots",
            ):
                if mode == "graph":
                    stream, sources = service.graph_query(
                        user_input, history[:-1],
                        alpha=alpha, temperature=temperature,
                        top_k_range=top_k_range,
                    )
                else:
                    stream, sources = service.query(
                        user_input, history[:-1],
                        temperature=temperature, top_k_range=top_k_range,
                    )
                for chunk in stream:
                    full_text += chunk
        except Exception as e:
            console.print(error_panel(f"Query failed: {e}"))
            history.pop()
            continue

        # ── 引用终态（Product P0.1）：流完整消费后才计算/读取 ──
        status = getattr(stream, "citation_status", None)
        status_panel = citation_status_panel(status)

        history[-1] = (user_input, full_text)

        console.print(user_message(user_input))
        console.print(assistant_message(full_text))
        if sources.strip():
            console.print(source_reference(sources))
        if status_panel is not None:
            console.print(status_panel)
        console.print(_command_bar(service, mode, alpha))
        console.print()

    return


def _show_help(console: Console):
    console.print()
    console.print(Panel(
        "\n".join(f"  [bold {THEME['accent']}]{cmd}[/]  {desc}" for cmd, desc in COMMANDS.items()),
        title="[bold " + THEME["accent"] + "]Help[/]",
        border_style=THEME["surface"],
    ))
    console.print()


def _show_status(console: Console, service, mode: str):
    stats = service.get_stats()
    lines = [
        f"  Mode:       {mode.upper()}",
        f"  Collection: {stats.get('collection', '—')}",
        f"  Chunks:     {stats.get('chunk_count', 0)}",
    ]
    if mode == "graph":
        lines.append(f"  Entities:   {stats.get('entity_count', 0)}")
        lines.append(f"  Relations:  {stats.get('relation_count', 0)}")
    files = stats.get("files", [])
    if files:
        lines.append(f"  Files ({len(files)}):")
        for f in files[:10]:
            lines.append(f"    · {f}")
        if len(files) > 10:
            lines.append(f"    · ... +{len(files) - 10} more")
    console.print()
    console.print(Panel(
        "\n".join(lines),
        title="[bold " + THEME["accent"] + "]Status[/]",
        border_style=THEME["surface"],
    ))
    console.print()


def _toggle_mode(console: Console, mode: str, service) -> str:
    new_mode = "graph" if mode == "standard" else "standard"

    # ── Graph → Standard：直接切换，无需确认 ──
    if new_mode == "standard":
        service.set_mode("standard")
        console.print(f"[{THEME['success']}]Mode → STANDARD[/]")
        return "standard"

    # ── Standard → Graph：需先构建知识图谱 ──
    stats = service.get_stats()
    files = stats.get("files", [])
    collection = stats.get("collection", "rag_demo")

    if not files:
        console.print(warning_panel("No files indexed. Add files first.", "Knowledge Graph"))
        return mode

    if not Confirm.ask(
        f"  [{THEME['text_dim']}]Build knowledge graph for {len(files)} file(s)?[/]",
        default=True,
        console=console,
    ):
        return mode

    try:
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

        def _progress_cb(done, total):
            progress.update(progress_bar, completed=done, total=total,
                            description=f"[{THEME['accent']}]Processing chunks... ({done}/{total})[/]")

        with Progress(
            SpinnerColumn(spinner_name="dots", style=THEME["accent"]),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=None),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            progress_bar = progress.add_task(
                f"[{THEME['accent']}]Building knowledge graph...[/]",
                total=None,
            )
            service.build_kg_from_chromadb(collection, progress_callback=_progress_cb)

        service.set_mode("graph")
        console.print(f"[{THEME['success']}]Knowledge graph ready![/]")
        console.print(f"[{THEME['success']}]Mode → GRAPH[/]")
        return "graph"

    except Exception as e:
        console.print(error_panel(f"Graph build failed: {e}"))
        return mode


def _set_alpha(console: Console, alpha: float) -> float:
    from rich.prompt import FloatPrompt
    new_alpha = FloatPrompt.ask(
        f"  [{THEME['text_dim']}]Alpha (0.0-1.0)[/]",
        default=alpha,
        console=console,
    )
    new_alpha = max(0.0, min(1.0, new_alpha))
    console.print(f"[{THEME['success']}]Alpha → {new_alpha:.1f}[/]")
    return new_alpha


def _handle_files(console: Console, service, user_input: str):
    parts = user_input.split(maxsplit=2)
    sub = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""

    if sub == "watch" and arg:
        target = os.path.abspath(os.path.expanduser(arg))
        if not os.path.isdir(target):
            console.print(error_panel(f"Directory not found: {target}", "Files"))
            return
        service.set_watch_dir(target)
        service.start_watching()
        console.print(f"[{THEME['success']}]Watching: {target}[/]")
        return

    if sub == "stop":
        service.stop_watching()
        console.print(f"[{THEME['success']}]Watcher stopped.[/]")
        return

    if sub == "list" or sub == "":
        watch_dir = service.get_watch_dir()
        if watch_dir:
            console.print(f"  [{THEME['text_dim']}]Watch directory:[/] [bold]{watch_dir}[/]")
        else:
            console.print(f"  [{THEME['text_dim']}]Watch directory:[/] [dim]<not set>[/]")
        stats = service.get_stats()
        files = stats.get("files", [])
        if files:
            console.print(f"  [{THEME['text_dim']}]Indexed files ({len(files)}):[/]")
            for f in files:
                console.print(f"    · {f}")
        else:
            console.print(f"  [{THEME['text_dim']}]No files indexed.[/]")
        return

    if sub == "remove" and arg:
        count = service.remove_file(arg)
        console.print(f"[{THEME['success']}]Removed {count} chunks.[/]")
        return

    if sub == "add" and arg:
        path = os.path.abspath(os.path.expanduser(arg))
        if not os.path.isfile(path):
            console.print(error_panel(f"File not found: {path}", "Files"))
            return
        result = service.add_files([path])
        console.print(f"[{THEME['success']}]Added {result.get('chunk_count', 0)} chunk(s).[/]")
        return

    console.print(warning_panel("Usage: /files [watch <dir> | stop | list | remove <file> | add <path>]", "Files"))


def _read_env(key: str) -> str:
    """读取统一配置层已解析的有效值。"""
    return get_effective_env_value(key)


def _write_env(key: str, value: str, console: Optional[Console] = None) -> bool:
    """只持久化 `.env`，不改写显式进程环境；返回是否存在该环境覆盖。"""
    explicit_keys = persist_env_settings({key: value})
    if key in explicit_keys and console is not None:
        console.print(
            f"[{THEME['warning']}]提示：进程环境变量优先，{key} 写入 .env 后"
            "仅在重启且未设置进程变量时生效。[/]"
        )
    reset_settings()
    return key in explicit_keys


def _mask_api_key(key: Optional[str]) -> str:
    """掩码显示 API Key，仅保留 'sk-' 前缀和最后 4 位。"""
    if not key:
        return "<not set>"
    if len(key) <= 8:
        return "sk-...****"
    return f"{key[:3]}...{key[-4:]}"   # key[:3] = "sk-"


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


def _configure_settings(console: Console, alpha: float = 0.7,
                         temperature: float = 0.1,
                         top_k_min: int = 3, top_k_max: int = 20):
    """Interactive settings menu with arrow-key navigation."""
    cur_alpha = alpha
    cur_temp = temperature
    cur_tk_min = top_k_min
    cur_tk_max = top_k_max
    model_changed = False

    while True:
        console.clear()
        api_key_display = _mask_api_key(_read_env("API_KEY"))
        base_url_display = _mask_api_key(_read_env("BASE_URL"))

        choices = [
            questionary.Choice(
                f"1. API Key          {api_key_display}", "api_key"),
            questionary.Choice(
                f"2. Base URL         {base_url_display}", "base_url"),
            questionary.Choice(
                f"3. LLM Model        {os.environ.get('LLM_MODEL', 'deepseek-chat')}", "llm_model"),
            questionary.Choice(
                f"4. Temperature      {cur_temp}", "temperature"),
            questionary.Choice(
                f"5. Top-K Min        {cur_tk_min}", "top_k_min"),
            questionary.Choice(
                f"6. Top-K Max        {cur_tk_max}", "top_k_max"),
            questionary.Choice(
                f"7. Alpha            {cur_alpha}", "alpha"),
            questionary.Choice("", None),
            questionary.Choice("q. Exit settings", "exit"),
        ]
        choice = questionary.select(
            "Settings (↑↓ navigate, Enter edit):",
            choices=choices,
            qmark=">",
            style=_QS,
        ).ask()

        if choice is None or choice == "exit":
            break

        if choice == "api_key":
            current = _read_env("API_KEY")
            val = questionary.text("API Key:", default=current, style=_QS).ask()
            if val and val != current:
                _write_env("API_KEY", val, console)
        elif choice == "base_url":
            current = _read_env("BASE_URL")
            val = questionary.text("Base URL:", default=current, style=_QS).ask()
            if val and val != current:
                _write_env("BASE_URL", val, console)
        elif choice == "llm_model":
            cur = _read_env("LLM_MODEL") or "deepseek-chat"
            val = questionary.text("LLM Model:", default=cur, style=_QS).ask()
            if val and val != cur:
                _write_env("LLM_MODEL", val, console)
                model_changed = True
        elif choice == "temperature":
            # 统一配置契约：合法范围 0.0–2.0（与 Settings/.env.example/README
            # 一致）。非法值显示明确错误并保持原配置不变——不静默 clamp、
            # 不写入 .env、不重置 Settings。
            val = questionary.text("Temperature (0.0-2.0):", default=str(cur_temp), style=_QS).ask()
            if val is None:
                continue  # 用户取消：不改变配置
            try:
                v = float(val.strip())
            except ValueError:
                console.print(error_panel(
                    f"非法温度 {val!r}：必须是数字，允许范围 0.0–2.0",
                    "Invalid Temperature",
                ))
                continue
            if not (0.0 <= v <= 2.0):
                console.print(error_panel(
                    f"非法温度 {val!r}：必须介于 0.0–2.0，输入未保存",
                    "Invalid Temperature",
                ))
                continue
            cur_temp = v
            _write_env("LLM_TEMPERATURE", str(v), console)
        elif choice == "top_k_min":
            val = questionary.text("Top-K Min:", default=str(cur_tk_min), style=_QS).ask()
            if val:
                try:
                    v = max(1, int(val))
                    if v <= cur_tk_max:
                        cur_tk_min = v
                        _write_env("LLM_TOP_K_MIN", str(v), console)
                except ValueError:
                    pass
        elif choice == "top_k_max":
            val = questionary.text("Top-K Max:", default=str(cur_tk_max), style=_QS).ask()
            if val:
                try:
                    v = int(val)
                    if v >= cur_tk_min:
                        cur_tk_max = v
                        _write_env("LLM_TOP_K_MAX", str(v), console)
                except ValueError:
                    pass
        elif choice == "alpha":
            val = questionary.text("Alpha (0.0-1.0):", default=str(cur_alpha), style=_QS).ask()
            if val:
                try:
                    v = max(0.0, min(1.0, float(val)))
                    cur_alpha = v
                    _write_env("ALPHA", str(v), console)
                except ValueError:
                    pass

    changed = (cur_alpha != alpha or cur_temp != temperature
               or cur_tk_min != top_k_min or cur_tk_max != top_k_max)
    if model_changed:
        reset_settings()
    # 数值设置直接写入时已通过统一配置层刷新。
    if changed:
        return (cur_alpha, cur_temp, (cur_tk_min, cur_tk_max))
    return None


def _switch_model(console: Console):
    current = os.environ.get("LLM_MODEL", "deepseek-chat")
    console.print()
    model = Prompt.ask(
        f"  [{THEME['text_dim']}]Current model[/] [{THEME['accent']}]({current})[/]",
        console=console,
    ).strip()
    if model and model != current:
        _write_env("LLM_MODEL", model, console)
        # `_write_env` 已通过统一配置层刷新 Settings；显式进程环境仍优先。
        console.print(f"[{THEME['success']}]Model → {model}[/]")
    console.print()
