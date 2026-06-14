from __future__ import annotations

import importlib

from ly_next.core.cli_select import select_option
from ly_next.core.server_port import (
    DEFAULT_LISTEN_PORT,
    _build_port_options,
    clear_recent_ports,
    find_free_port,
    is_port_in_use,
    load_recent_ports,
    remember_port,
    remove_recent_port,
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


def test_resolve_startup_port_always_prompts_in_interactive_mode(monkeypatch):
    monkeypatch.delenv("LY_NEXT_PORT", raising=False)
    monkeypatch.setattr(
        "ly_next.core.server_port.load_recent_ports",
        lambda: [8123],
    )
    monkeypatch.setattr(
        "ly_next.core.server_port.prompt_listen_port",
        lambda **kw: 8123 + 1,
    )
    assert resolve_startup_port(None, 8123, interactive=True) == 8124


def test_resolve_startup_port_fallback(monkeypatch):
    monkeypatch.delenv("LY_NEXT_PORT", raising=False)
    assert resolve_startup_port(None, None, interactive=False) == DEFAULT_LISTEN_PORT


def _patch_data_root(monkeypatch, data_root):
    cfg = importlib.import_module("ly_next.core.config")
    monkeypatch.setattr(cfg, "get_data_root", lambda: data_root)


def test_remember_port_dedupes_and_orders(tmp_path, monkeypatch):
    data_root = tmp_path / "data" / "ly_next"
    data_root.mkdir(parents=True)
    _patch_data_root(monkeypatch, data_root)

    remember_port(9000)
    remember_port(9100)
    remember_port(9000)

    assert load_recent_ports() == [9000, 9100]


def test_build_port_options_puts_recent_first(tmp_path, monkeypatch):
    data_root = tmp_path / "data" / "ly_next"
    data_root.mkdir(parents=True)
    _patch_data_root(monkeypatch, data_root)

    remember_port(8765)
    remember_port(7654)

    options = _build_port_options()
    assert options == [7654, 8765]
    assert 8000 not in options


def test_load_recent_ports_invalid_file(tmp_path, monkeypatch):
    data_root = tmp_path / "data" / "ly_next"
    data_root.mkdir(parents=True)
    _patch_data_root(monkeypatch, data_root)
    (data_root / "recent_ports.json").write_text("{not json", encoding="utf-8")

    assert load_recent_ports() == []


def test_remove_recent_port(tmp_path, monkeypatch):
    data_root = tmp_path / "data" / "ly_next"
    data_root.mkdir(parents=True)
    _patch_data_root(monkeypatch, data_root)

    remember_port(9000)
    remember_port(9100)
    assert remove_recent_port(9000) is True
    assert load_recent_ports() == [9100]
    assert remove_recent_port(9999) is False


def test_clear_recent_ports(tmp_path, monkeypatch):
    data_root = tmp_path / "data" / "ly_next"
    data_root.mkdir(parents=True)
    _patch_data_root(monkeypatch, data_root)

    remember_port(9000)
    clear_recent_ports()
    assert load_recent_ports() == []
    assert not (data_root / "recent_ports.json").is_file()


def test_select_option_non_tty_returns_default(monkeypatch):
    monkeypatch.setattr("ly_next.core.cli_select.sys.stdin.isatty", lambda: False)
    assert select_option(["a", "b"], title="t", default_index=1) == 1


def test_select_option_enter_returns_index(monkeypatch):
    monkeypatch.setattr("ly_next.core.cli_select.sys.stdin.isatty", lambda: True)
    keys = iter(["down", "enter"])
    monkeypatch.setattr(
        "ly_next.core.cli_select._read_key",
        lambda: next(keys),
    )
    assert select_option(["first", "second"], title="pick", default_index=0) == 1
