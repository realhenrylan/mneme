def test_cli_delete_trace_command_is_handled(monkeypatch, capsys):
    from src.cli_loop import _handle_trace_command

    calls = []
    monkeypatch.setattr(
        "src.production_observability.TraceStore.from_environment",
        lambda: type("Store", (), {"delete_trace": lambda self, value: calls.append(value)})(),
    )
    assert _handle_trace_command("delete-trace " + "a" * 32) is True
    assert calls == ["a" * 32]
    assert "已删除" in capsys.readouterr().out


def test_cli_non_trace_command_is_not_consumed():
    from src.cli_loop import _handle_trace_command

    assert _handle_trace_command("ordinary query") is False
