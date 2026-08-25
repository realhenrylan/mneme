from tui.keys import COMMANDS
from tui.components.prompt import match_command
from src.production_observability import ConsentLevel, TraceStore


def test_trace_commands_are_registered_and_matchable():
    assert "/consent" in COMMANDS
    assert "/delete-trace" in COMMANDS
    assert match_command("/consent") == "/consent"
    assert match_command("/delete-trace abc") == "/delete-trace"


def test_exact_consent_is_explicitly_unavailable(tmp_path):
    store = TraceStore(tmp_path / "data" / "traces")
    assert store.set_consent(ConsentLevel.EXACT, confirmed=True) is False
    assert store.consent.level is ConsentLevel.OFF
