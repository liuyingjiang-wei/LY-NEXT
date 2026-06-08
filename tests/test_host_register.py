from __future__ import annotations

from ly_next.tools.builtin import register_builtin_tools
from ly_next.tools.registry import ToolRegistry


def test_register_host_tools_when_enabled(monkeypatch):
    monkeypatch.setattr("ly_next.tools.host_register.host_tools_enabled", lambda: True)
    monkeypatch.setattr("ly_next.tools.host_register.host_exec_enabled", lambda: True)

    reg = ToolRegistry()
    register_builtin_tools(reg)

    names = reg.list_tool_names()
    assert "host_read_file" in names
    assert "host_run_command" in names


def test_skip_host_tools_when_disabled(monkeypatch):
    monkeypatch.setattr("ly_next.tools.host_register.host_tools_enabled", lambda: False)

    reg = ToolRegistry()
    n = register_builtin_tools(reg)
    assert n > 0
    assert "host_read_file" not in reg.list_tool_names()
