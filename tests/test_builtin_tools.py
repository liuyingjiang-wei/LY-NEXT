from __future__ import annotations

from unittest.mock import MagicMock, patch

from ly_next.tools.builtin import BUILTIN_TOOLS_BY_NAME, register_builtin_tools
from ly_next.tools.registry import ToolRegistry


def test_register_builtin_respects_allowlist():
    reg = ToolRegistry()
    mock = MagicMock()
    mock.get = MagicMock(
        side_effect=lambda k, default=None: (
            ["calculator", "format_json"] if k == "tools.built_in" else default
        )
    )
    with patch("ly_next.tools.builtin.config", mock):
        n = register_builtin_tools(reg)
    assert n == 2
    assert reg.has("calculator") and reg.has("format_json")
    assert not reg.has("http_fetch")


def test_register_builtin_empty_list_registers_nothing():
    reg = ToolRegistry()
    mock = MagicMock()
    mock.get = MagicMock(
        side_effect=lambda k, default=None: [] if k == "tools.built_in" else default
    )
    with patch("ly_next.tools.builtin.config", mock):
        n = register_builtin_tools(reg)
    assert n == 0
    assert len(reg) == 0


def test_register_builtin_none_means_all_names():
    reg = ToolRegistry()
    mock = MagicMock()
    mock.get = MagicMock(
        side_effect=lambda k, default=None: None if k == "tools.built_in" else default
    )
    with patch("ly_next.tools.builtin.config", mock):
        n = register_builtin_tools(reg)
    assert n == len(BUILTIN_TOOLS_BY_NAME)
    for name in BUILTIN_TOOLS_BY_NAME:
        assert reg.has(name)


def test_register_builtin_unknown_name_skipped():
    reg = ToolRegistry()
    mock = MagicMock()
    mock.get = MagicMock(
        side_effect=lambda k, default=None: (
            ["calculator", "not_a_real_tool"] if k == "tools.built_in" else default
        )
    )
    with patch("ly_next.tools.builtin.config", mock):
        n = register_builtin_tools(reg)
    assert n == 1
    assert reg.has("calculator")
