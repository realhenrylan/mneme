"""解析诊断的 TUI 呈现助手（2.3 验收）。

独立小模块：chat.py（/files add）与 loading.py（初始建库）共用，
避免两屏互相 import。
"""

from __future__ import annotations

from rich.console import Console

from tui.components.message import warning_panel


def parse_diagnostics_warnings(stats: dict) -> list[dict]:
    """从索引 stats 过滤需要向用户呈现的解析问题条目。

    判定口径（任一命中即呈现）：低质量解析、降级到旧路径、解析异常、
    零块产出——正常条目不产生噪音。
    """
    diags = stats.get("parse_diagnostics") or []
    return [
        d for d in diags
        if d.get("is_low_quality") or d.get("parse_degraded")
        or d.get("error") or d.get("chunk_count") == 0
    ]


def render_parse_diagnostics(console: Console, stats: dict) -> None:
    """把问题条目渲染为 warning_panel（无问题条目时完全静默）。"""
    for d in parse_diagnostics_warnings(stats):
        source = d.get("source_name", "?")
        if d.get("error"):
            detail = f"{source}：降级解析（{d['error']}）"
        elif d.get("chunk_count") == 0:
            detail = f"{source}：解析产出 0 块，该文件未进入索引"
        elif d.get("is_low_quality"):
            detail = (f"{source}：低质量解析"
                      f"（quality={d.get('parse_quality')}），建议检查源文件")
        else:
            continue
        console.print(warning_panel(detail, "解析诊断"))
