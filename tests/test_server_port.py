from __future__ import annotations

from ly_next.core.server_port import (
    DEFAULT_LISTEN_PORT,
    find_free_port,
    is_port_in_use,
    resolve_startup_port,
)


def test_is_port_in_use_localhost():
    free = find_free_port(39000)
    assert not is_port_in_use("127.0.0.1", free)


def test_resolve_startup_port_cli_wins(monkeypatch):
    monkeypatch.delenv("LY_NEXT_PORT", raising=False)
    assert resolve_startup_port(9001, 8000, interactive=False) == 9001


def test_resolve_startup_port_env(monkeypatch):
    monkeypatch.setenv("LY_NEXT_PORT", "9002")
    assert resolve_startup_port(None, 8000, interactive=False) == 9002


def test_resolve_startup_port_config_default(monkeypatch):
    monkeypatch.delenv("LY_NEXT_PORT", raising=False)
    assert resolve_startup_port(None, 8123, interactive=False) == 8123


def test_resolve_startup_port_config_not_used_in_interactive_mode(monkeypatch):
    monkeypatch.delenv("LY_NEXT_PORT", raising=False)
    monkeypatch.setattr(
        "ly_next.core.server_port.prompt_listen_port",
        lambda default, host="0.0.0.0": default + 1,
    )
    assert resolve_startup_port(None, 8123, interactive=True) == 8123 + 1


def test_resolve_startup_port_fallback(monkeypatch):
    monkeypatch.delenv("LY_NEXT_PORT", raising=False)
    assert resolve_startup_port(None, None, interactive=False) == DEFAULT_LISTEN_PORT
