"""D1 取消机制测试（3.1 收尾 —— 网络异常/取消不停留 thinking）。

设计出处：``plans/22-SMALL-ITEMS-31-CLOSEOUT-DESIGN-2026-08-29.md`` Part 2-D1：
- ``llm_gateway`` 新增 ``LLMCancelledError``；``llm_call`` 接受
  ``cancel_event``——调用前置位 = 零网络零 client；退避等待改为
  ``cancel_event.wait(backoff)``（取消即时唤醒）；
- ``answer_with_llm_history_stream`` 透传 ``cancel_event``，流消费逐 chunk
  检查，置位 → 关闭响应流 + 抛 ``LLMCancelledError``（**不产出** API 错误
  文本——取消不是错误消息）；
- TUI 生成块捕获 KeyboardInterrupt → 置位事件 → 打印「已取消当前回答」
  → 回输入提示；半截答案不入 history。
"""
from __future__ import annotations

import io
import threading
import time
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from src import rag
from src.llm_gateway import LLMCancelledError, LLMErrorCategory, llm_call


def _fake_response_stream() -> MagicMock:
    """模拟 OpenAI 流式响应：两个 chunk，每个带一个 "x" 增量。"""
    class _Delta:
        content = "x"

    class _Choice:
        delta = _Delta()

    class _Chunk:
        choices = [_Choice()]

    response = MagicMock()
    response.__iter__ = lambda self: iter([_Chunk(), _Chunk()])
    return response


class TestCancelledBeforeStart:
    """调用前取消 = 零网络零 client。"""

    def test_pre_set_event_raises_without_client(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "sk-fake-cancel")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")

        def _boom(*args, **kwargs):
            raise AssertionError("取消后不得创建 client")

        monkeypatch.setattr("src.llm_gateway._get_client", _boom)

        cancel_event = threading.Event()
        cancel_event.set()

        with pytest.raises(LLMCancelledError):
            llm_call("answer", [{"role": "user", "content": "q"}],
                     cancel_event=cancel_event)

    def test_cancelled_recorded_as_cancelled(self, monkeypatch):
        """取消调用计入调用记录且分类为 cancelled（可观测性一致）。"""
        from src.llm_gateway import clear_call_records, get_call_records

        monkeypatch.setenv("API_KEY", "sk-fake-cancel")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        monkeypatch.setattr("src.llm_gateway._get_client",
                            lambda *a, **k: MagicMock())
        clear_call_records()
        try:
            cancel_event = threading.Event()
            cancel_event.set()
            with pytest.raises(LLMCancelledError):
                llm_call("answer", [{"role": "user", "content": "q"}],
                         cancel_event=cancel_event)
            records = get_call_records()
            assert records
            assert records[-1].error_category == LLMErrorCategory.CANCELLED
            assert records[-1].cancelled is True
        finally:
            clear_call_records()


class TestCancelDuringBackoff:
    """退避等待中取消 = 即时返回（不睡满指数退避）。"""

    def test_cancel_interrupts_backoff_without_waiting(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "sk-fake-backoff")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")

        class FakeCompletions:
            def create(self, **kwargs):
                raise type("APIConnectionError", (Exception,), {})()

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            chat = FakeChat()

        monkeypatch.setattr("src.llm_gateway._get_client",
                            lambda *a, **k: FakeClient())

        cancel_event = threading.Event()
        # 第一次失败进入退避（1s）后 0.2s 时置位 → wait 应即时返回
        timer = threading.Timer(0.2, cancel_event.set)
        timer.start()
        start = time.perf_counter()
        try:
            with pytest.raises(LLMCancelledError):
                llm_call("answer", [{"role": "user", "content": "q"}],
                         max_retries=2, cancel_event=cancel_event)
            elapsed = time.perf_counter() - start
            # 若退避未被取消打断，将睡满 1s 后才进入下一次重试
            assert elapsed < 0.8, f"退避未被取消唤醒（耗时 {elapsed:.2f}s）"
        finally:
            timer.cancel()


class TestCancelInStreamConsumption:
    """流消费中取消：关闭响应流 + 抛 LLMCancelledError，且不产出错误文本。"""

    def test_cancel_closes_response_and_raises(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "sk-fake-stream")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        response = _fake_response_stream()
        record = MagicMock()
        monkeypatch.setattr("src.llm_gateway.llm_call",
                            lambda **kwargs: (response, record))

        cancel_event = threading.Event()
        gen = rag.answer_with_llm_history_stream(
            "q", "ctx", [], cancel_event=cancel_event)

        collected = []
        collected.append(next(gen))          # 第一个 chunk 正常
        cancel_event.set()                   # 消费中置位
        with pytest.raises(LLMCancelledError):
            next(gen)                        # 检查置位 → close + raise
        assert collected == ["x"]
        response.close.assert_called_once()  # 响应流被关闭

    def test_cancel_never_yields_api_error_text(self, monkeypatch):
        """取消不产出现有 except 分支的 "[API 请求失败...]" 错误文本。"""
        monkeypatch.setenv("API_KEY", "sk-fake-stream")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        response = _fake_response_stream()
        monkeypatch.setattr("src.llm_gateway.llm_call",
                            lambda **kwargs: (response, MagicMock()))

        cancel_event = threading.Event()
        gen = rag.answer_with_llm_history_stream(
            "q", "ctx", [], cancel_event=cancel_event)
        next(gen)
        cancel_event.set()
        with pytest.raises(LLMCancelledError):
            next(gen)

    def test_generator_close_after_cancel_releases_response(self, monkeypatch):
        """KeyboardInterrupt/TUI 取消后生成器被弃置：关闭响应流。"""
        monkeypatch.setenv("API_KEY", "sk-fake-stream")
        monkeypatch.setenv("BASE_URL", "https://fake.test/v1")
        response = _fake_response_stream()
        monkeypatch.setattr("src.llm_gateway.llm_call",
                            lambda **kwargs: (response, MagicMock()))

        cancel_event = threading.Event()
        gen = rag.answer_with_llm_history_stream(
            "q", "ctx", [], cancel_event=cancel_event)
        next(gen)               # 生成器挂起在 yield
        cancel_event.set()
        gen.close()             # GeneratorExit：finally 释放响应流
        response.close.assert_called_once()


class _FakeService:
    """TUI 测试替身：记录传入的 cancel_event 并按设定抛出。"""

    def __init__(self, raise_keyboard_interrupt: bool = True):
        self.raise_keyboard_interrupt = raise_keyboard_interrupt
        self.cancel_event = None

    def query(self, query, history, **kwargs):
        self.cancel_event = kwargs.get("cancel_event")
        if self.raise_keyboard_interrupt:
            raise KeyboardInterrupt
        return (iter(()), "")

    def graph_query(self, *args, **kwargs):
        raise AssertionError("standard 模式不应走 graph 路径")

    def get_stats(self):
        return {}


class TestTuiCancelRestoresLoop:
    """生成期间 Ctrl+C：置位 cancel_event、打印取消提示、会话不退出。"""

    def test_keyboard_interrupt_sets_event_and_continues(self, monkeypatch):
        import tui.screens.chat as chat

        inputs = iter(["hello", ])

        def _fake_input(prompt="", password=False):
            val = next(inputs, None)
            if val is None:
                raise EOFError
            return val

        console = Console(record=True, file=io.StringIO())
        monkeypatch.setattr(console, "input", _fake_input)
        service = _FakeService(raise_keyboard_interrupt=True)

        chat.run_chat_loop(console, service, "standard",
                           alpha=1.0, temperature=0.2, top_k_range=(3, 20))

        output = console.export_text()
        assert "已取消当前回答" in output
        assert service.cancel_event is not None
        assert service.cancel_event.is_set()   # Ctrl+C 置位事件
        assert "Bye!" in output                # 会话未逸出，回到输入后正常退出
