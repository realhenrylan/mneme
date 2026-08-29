"""D3 错误分类可见测试（3.1 收尾 —— gateway 调用摘要进入 /status）。

设计出处：``plans/22-SMALL-ITEMS-31-CLOSEOUT-DESIGN-2026-08-29.md``
Part 2-D3：
- ``service.get_stats()`` 附 gateway 调用摘要（调用数 / 错误率 / 分类分布 /
  token 合计）；
- TUI ``/status``（``render_sidebar``）渲染一行；无调用记录时零噪音。
"""
from __future__ import annotations

import io
from unittest.mock import patch

from rich.console import Console

from tui.components.sidebar import render_sidebar
from tui.service import LocalRagService


def _panel_text(panel) -> str:
    """将 Panel 内容以 Rich 渲染为纯文本（Table 无 .render()，走 console）。"""
    buf = io.StringIO()
    Console(file=buf, width=40).print(panel.renderable)
    return buf.getvalue()


class TestStatsIncludeGatewaySummary:
    def test_get_stats_attaches_gateway_summary(self):
        """get_stats() 附 gateway 摘要：错误率 / 分类分布 / token 合计。"""
        from src.llm_gateway import get_call_summary

        expected = get_call_summary()
        with patch("src.llm_gateway.get_call_summary", return_value={
            "total_calls": 7,
            "error_count": 1,
            "error_rate": 1 / 7,
            "avg_latency_ms": 120.0,
            "total_prompt_tokens": 500,
            "total_completion_tokens": 300,
            "by_type": {"answer": 5, "decompose": 2},
            "by_error": {"rate_limit": 1},
        }):
            stats = LocalRagService().get_stats()

        gw = stats.get("llm_gateway")
        assert gw is not None
        assert gw["total_calls"] == 7
        assert gw["error_rate"] == 1 / 7
        assert gw["by_error"]["rate_limit"] == 1
        assert gw["total_prompt_tokens"] == 500
        assert gw["total_completion_tokens"] == 300


class TestSidebarRendersGatewayLine:
    def test_renders_one_line_when_calls_recorded(self):
        stats = {"chunk_count": 0, "files": [], "llm_gateway": {
            "total_calls": 42, "error_rate": 0.05,
            "total_prompt_tokens": 1000, "total_completion_tokens": 800,
            "by_error": {"timeout": 2},
        }}
        panel = render_sidebar(stats, "standard", 1.0, 0.2, (3, 20))
        text = _panel_text(panel)
        assert "LLM Calls" in text
        assert "42" in text
        assert "5% err" in text
        assert "1800 tok" in text

    def test_zero_calls_produces_no_noise(self):
        """无调用记录时 /status 不渲染 gateway 行（零噪音）。"""
        stats = {"chunk_count": 0, "files": [], "llm_gateway": {
            "total_calls": 0, "error_rate": 0.0,
        }}
        panel = render_sidebar(stats, "standard", 1.0, 0.2, (3, 20))
        text = _panel_text(panel)
        assert "LLM Calls" not in text

    def test_missing_gateway_key_produces_no_noise(self):
        """stats 无 llm_gateway 键（旧数据）时同样零噪音。"""
        stats = {"chunk_count": 0, "files": []}
        panel = render_sidebar(stats, "standard", 1.0, 0.2, (3, 20))
        assert "LLM Calls" not in _panel_text(panel)
